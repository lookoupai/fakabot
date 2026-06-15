from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
import unittest

try:
    from app.services.external_sources import (
        ExternalCatalogSyncService,
        ExternalHttpRequest,
        ExternalHttpResponse,
        ExternalOrderOperationService,
        ExternalOrderRequest,
        ExternalProviderOfflineIdempotencyProbe,
        ExternalSourceRuntimeCredentials,
        describe_provider,
        list_providers,
        register_builtin_external_providers,
        register_provider,
    )
    import app.services.external_sources.registry as provider_registry
    from app.services.external_sources.mcy_shop import (
        MCY_SHOP_OFFLINE_FIXTURE_CONTRACT,
        MCY_SHOP_PROVIDER,
        create_mcy_shop_provider,
        validate_mcy_shop_credentials,
    )
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过 mcy_shop 外部源测试：{exc.name}") from exc


class _FakeMcyShopTransport:
    def __init__(
        self,
        *,
        sensitive_catalog_payload: bool = False,
        non_json_catalog: bool = False,
        oversized_catalog_page: bool = False,
        oversized_delivery_items: bool = False,
        oversized_delivery_item: bool = False,
        non_idempotent_orders: bool = False,
    ) -> None:
        self.requests: list[ExternalHttpRequest] = []
        self.sensitive_catalog_payload = sensitive_catalog_payload
        self.non_json_catalog = non_json_catalog
        self.oversized_catalog_page = oversized_catalog_page
        self.oversized_delivery_items = oversized_delivery_items
        self.oversized_delivery_item = oversized_delivery_item
        self.non_idempotent_orders = non_idempotent_orders
        self.created_order_count = 0

    async def request(self, request: ExternalHttpRequest) -> ExternalHttpResponse:
        self.requests.append(request)
        self._assert_auth(request)
        path = urlsplit(request.url).path
        query = parse_qs(urlsplit(request.url).query)
        if request.method == "GET" and path == "/fixture/mcy-shop-fixture/products":
            if self.non_json_catalog:
                return ExternalHttpResponse(status_code=200, text="not-json")
            product = _fixture_product()
            if self.sensitive_catalog_payload:
                product["api_key"] = "provider-secret"
            products = [product] * 101 if self.oversized_catalog_page else [product]
            return ExternalHttpResponse(
                status_code=200,
                json_payload={
                    "items": products,
                    "next_cursor": None,
                    "echo_limit": query.get("limit", [""])[0],
                },
            )
        if request.method == "GET" and path == "/fixture/mcy-shop-fixture/products/sku-1":
            return ExternalHttpResponse(status_code=200, json_payload=_fixture_product())
        if request.method == "POST" and path == "/fixture/mcy-shop-fixture/orders":
            payload = request.json_payload or {}
            self.created_order_count += 1
            order_id = "mcy-order-1"
            if self.non_idempotent_orders:
                order_id = f"mcy-order-{self.created_order_count}"
            return ExternalHttpResponse(
                status_code=200,
                json_payload={
                    "trade_id": order_id,
                    "product_id": payload.get("external_product_id"),
                    "quantity": payload.get("quantity"),
                    "total_amount": "8.80",
                    "currency": "USDT",
                    "state": "paid",
                    "delivery_ready": True,
                },
            )
        if request.method == "GET" and path == "/fixture/mcy-shop-fixture/orders/mcy-order-1":
            return ExternalHttpResponse(
                status_code=200,
                json_payload={
                    "trade_id": "mcy-order-1",
                    "product_id": "sku-1",
                    "quantity": 1,
                    "total_amount": "8.80",
                    "currency": "USDT",
                    "state": "delivered",
                    "delivery_ready": True,
                },
            )
        if request.method == "GET" and path == "/fixture/mcy-shop-fixture/deliveries/mcy-order-1":
            cards = ["MCY-CARD-1"]
            if self.oversized_delivery_items:
                cards = [f"MCY-CARD-{index}" for index in range(101)]
            elif self.oversized_delivery_item:
                cards = ["M" * 513]
            return ExternalHttpResponse(
                status_code=200,
                json_payload={
                    "trade_id": "mcy-order-1",
                    "delivery_kind": "card_pool",
                    "cards": cards,
                    "message": "离线 fixture 发货",
                },
            )
        return ExternalHttpResponse(status_code=404, json_payload={"error": "not found"})

    def _assert_auth(self, request: ExternalHttpRequest) -> None:
        if request.headers.get("X-API-Key") != "provider-secret":
            raise AssertionError("mcy_shop request must carry runtime auth header")
        if request.headers.get("X-Source-Key") != "shop-a":
            raise AssertionError("mcy_shop request must carry source key")
        if request.headers.get("X-Fakabot-External-Contract") != MCY_SHOP_OFFLINE_FIXTURE_CONTRACT:
            raise AssertionError("mcy_shop request must declare offline fixture contract")


class _FakeCatalogRepository:
    def __init__(self) -> None:
        self.products: dict[tuple[int, str, str, str], SimpleNamespace] = {}
        self.next_id = 1

    async def get_self_product_by_external_ref(self, session, tenant_id, external_source, source_key, external_id):
        return self.products.get((tenant_id, external_source, source_key, external_id)), None

    async def create_self_product(
        self,
        session,
        tenant_id,
        name,
        price,
        delivery_type,
        description=None,
        category=None,
        external_source=None,
        source_key="",
        external_id=None,
    ):
        product = SimpleNamespace(
            id=self.next_id,
            tenant_id=tenant_id,
            name=name,
            suggested_price=price,
            delivery_type=delivery_type,
            description=description,
            category=category,
            external_source=external_source,
            source_key=source_key,
            external_id=external_id,
            status="draft",
        )
        self.next_id += 1
        self.products[(tenant_id, external_source, source_key, external_id)] = product
        return product

    async def update_self_product(self, session, tenant_id, product_id, **kwargs):
        product = self.products[(tenant_id, kwargs["external_source"], kwargs["source_key"], kwargs["external_id"])]
        product.name = kwargs.get("name") or product.name
        product.suggested_price = kwargs.get("price") or product.suggested_price
        product.status = kwargs.get("status") or product.status
        return product

    async def set_product_status(self, session, tenant_id, product_id, status) -> bool:
        for product in self.products.values():
            if product.tenant_id == tenant_id and product.id == product_id:
                product.status = status
                return True
        return False


def _runtime_auth(credentials: dict[str, str] | None = None) -> ExternalSourceRuntimeCredentials:
    base_credentials = {
        "base_url": "https://mcy-fixture.example/fixture",
        "api_key": "provider-secret",
        "timeout_seconds": "5",
    }
    if credentials:
        base_credentials.update(credentials)
    return ExternalSourceRuntimeCredentials(
        connection_id=21,
        tenant_id=7,
        provider_name=MCY_SHOP_PROVIDER,
        source_key="shop-a",
        credential_fields=["sensitive_1", "sensitive_2", "sensitive_3"],
        credentials=base_credentials,
    )


def _fixture_product() -> dict[str, object]:
    return {
        "product_id": "sku-1",
        "title": "mcy_shop 离线卡密",
        "unit_price": "8.80",
        "currency": "USDT",
        "state": "on",
        "delivery_kind": "card_pool",
        "inventory": 6,
        "summary": "仅用于本地 fixture 合同测试",
        "group": "账号",
    }


class McyShopExternalSourceProviderTest(unittest.TestCase):
    def test_mcy_shop_provider_registers_as_builtin_offline_contract(self) -> None:
        previous_providers = dict(provider_registry._providers)
        provider_registry._providers.clear()
        try:
            register_builtin_external_providers()
            register_builtin_external_providers()

            self.assertIn(MCY_SHOP_PROVIDER, list_providers())
            summary = describe_provider(provider_registry._providers[MCY_SHOP_PROVIDER])
            self.assertTrue(summary.capabilities.catalog_context_available)
            self.assertTrue(summary.capabilities.catalog_product_context_available)
            self.assertTrue(summary.capabilities.order_context_available)
            self.assertTrue(summary.capabilities.delivery_context_available)
            self.assertFalse(summary.capabilities.auto_fulfillment_idempotent_available)
            self.assertEqual("offline_fixture", summary.integration_kind)
            self.assertEqual(MCY_SHOP_OFFLINE_FIXTURE_CONTRACT, summary.contract_name)
            self.assertFalse(summary.production_ready)
            self.assertFalse(summary.staging_verified)
        finally:
            provider_registry._providers.clear()
            provider_registry._providers.update(previous_providers)

    def test_mcy_shop_provider_does_not_claim_production_or_auto_fulfillment(self) -> None:
        provider = create_mcy_shop_provider(_FakeMcyShopTransport())
        summary = describe_provider(provider)

        self.assertFalse(provider.production_ready)
        self.assertFalse(provider.staging_verified)
        self.assertFalse(provider.auto_fulfillment_idempotent)
        self.assertFalse(summary.production_ready)
        self.assertFalse(summary.staging_verified)
        self.assertFalse(summary.capabilities.auto_fulfillment_idempotent_available)
        self.assertTrue(summary.capabilities.order_context_available)
        self.assertTrue(summary.capabilities.delivery_context_available)

    def test_mcy_shop_provider_requires_authenticated_context_before_http_call(self) -> None:
        transport = _FakeMcyShopTransport()
        provider = create_mcy_shop_provider(transport)

        with self.assertRaisesRegex(Exception, "runtime_auth|运行时凭据"):
            asyncio.run(provider.list_products_with_context(SimpleNamespace(source_key="shop-a"), limit=10))

        self.assertEqual([], transport.requests)

    def test_mcy_shop_credentials_repr_redacts_api_key(self) -> None:
        credentials = validate_mcy_shop_credentials(
            {
                "base_url": "https://fixture.example",
                "api_key": "provider-secret",
            }
        )

        self.assertEqual("provider-secret", credentials.api_key)
        self.assertNotIn("provider-secret", repr(credentials))
        self.assertNotIn("api_key", repr(credentials))

    def test_mcy_shop_credentials_only_allow_fixture_hosts(self) -> None:
        valid_base_urls = (
            "http://localhost:8080/fixture",
            "http://fixture.localhost/fixture",
            "http://127.0.0.1:8080/fixture",
            "http://[::1]:8080/fixture",
            "https://fixture.test/fixture",
            "https://fixture.example/fixture",
            "https://fixture.example.invalid/fixture",
            "https://fixture.invalid/fixture",
        )

        for base_url in valid_base_urls:
            with self.subTest(base_url=base_url):
                credentials = validate_mcy_shop_credentials(
                    {
                        "base_url": base_url,
                        "api_key": "provider-secret",
                    }
                )
                self.assertEqual("provider-secret", credentials.api_key)

    def test_mcy_shop_provider_syncs_catalog_with_runtime_credentials(self) -> None:
        transport = _FakeMcyShopTransport()
        provider = create_mcy_shop_provider(transport)
        repository = _FakeCatalogRepository()
        service = ExternalCatalogSyncService(repository=repository)

        result = asyncio.run(
            service.sync_catalog(
                object(),
                tenant_id=7,
                provider=provider,
                source_key="shop-a",
                connection_id=21,
                runtime_auth=_runtime_auth(),
            )
        )

        self.assertEqual(1, result.created_count)
        self.assertEqual("sku-1", result.products[0].external_id)
        self.assertEqual(1, len(transport.requests))
        request = transport.requests[0]
        self.assertEqual("GET", request.method)
        self.assertEqual("/fixture/mcy-shop-fixture/products", urlsplit(request.url).path)
        self.assertEqual("50", parse_qs(urlsplit(request.url).query)["limit"][0])
        self.assertEqual("provider-secret", request.headers["X-API-Key"])
        self.assertNotIn("provider-secret", repr(request))
        self.assertNotIn("provider-secret", repr(result))
        stored = repository.products[(7, MCY_SHOP_PROVIDER, "shop-a", "sku-1")]
        self.assertEqual("mcy_shop 离线卡密", stored.name)
        self.assertEqual(Decimal("8.80"), stored.suggested_price)

    def test_mcy_shop_provider_order_lifecycle_redacts_credentials(self) -> None:
        transport = _FakeMcyShopTransport()
        provider = create_mcy_shop_provider(transport)
        service = ExternalOrderOperationService()
        previous_providers = dict(provider_registry._providers)
        provider_registry._providers.clear()
        try:
            register_provider(provider)
            created = asyncio.run(
                service.create_registered_order(
                    tenant_id=7,
                    provider_name=MCY_SHOP_PROVIDER,
                    source_key="shop-a",
                    connection_id=21,
                    runtime_auth=_runtime_auth(),
                    request=ExternalOrderRequest(
                        external_product_id="sku-1",
                        quantity=1,
                        out_trade_no="ORD123",
                        buyer_reference="buyer-42",
                    ),
                )
            )
            queried = asyncio.run(
                service.query_registered_order(
                    tenant_id=7,
                    provider_name=MCY_SHOP_PROVIDER,
                    source_key="shop-a",
                    connection_id=21,
                    runtime_auth=_runtime_auth(),
                    external_order_id=created.external_order_id,
                )
            )
            delivery = asyncio.run(
                service.fetch_registered_delivery(
                    tenant_id=7,
                    provider_name=MCY_SHOP_PROVIDER,
                    source_key="shop-a",
                    connection_id=21,
                    runtime_auth=_runtime_auth(),
                    external_order_id=created.external_order_id,
                )
            )
        finally:
            provider_registry._providers.clear()
            provider_registry._providers.update(previous_providers)

        self.assertEqual("mcy-order-1", created.external_order_id)
        self.assertEqual("delivered", queried.status)
        self.assertEqual(("MCY-CARD-1",), delivery.items)
        self.assertEqual(["POST", "GET", "GET"], [request.method for request in transport.requests])
        rendered_requests = "\n".join(repr(request) for request in transport.requests)
        self.assertNotIn("provider-secret", rendered_requests)
        self.assertNotIn("ORD123", repr(created.raw_payload))
        self.assertNotIn("provider-secret", repr(created))
        self.assertNotIn("provider-secret", repr(queried))
        self.assertNotIn("provider-secret", repr(delivery))
        self.assertNotIn("MCY-CARD-1", repr(delivery))
        self.assertNotIn("离线 fixture 发货", repr(delivery))
        self.assertNotIn("MCY-CARD-1", repr(delivery.raw_payload))

    def test_mcy_shop_offline_idempotency_probe_uses_duplicate_out_trade_no_without_claiming_auto(self) -> None:
        transport = _FakeMcyShopTransport()
        provider = create_mcy_shop_provider(transport)

        proof = asyncio.run(
            ExternalProviderOfflineIdempotencyProbe().prove(
                provider=provider,
                tenant_id=7,
                source_key="shop-a",
                connection_id=21,
                runtime_auth=_runtime_auth(),
                request=ExternalOrderRequest(
                    external_product_id="sku-1",
                    quantity=1,
                    out_trade_no="ORD123",
                    buyer_reference="buyer-42",
                ),
            )
        )

        self.assertTrue(proof.idempotent)
        self.assertEqual("ORD123", proof.out_trade_no)
        self.assertEqual("mcy-order-1", proof.external_order_id)
        self.assertEqual("delivered", proof.query_status)
        self.assertTrue(proof.delivery_ready)
        self.assertEqual(1, proof.delivery_item_count)
        self.assertFalse(provider.auto_fulfillment_idempotent)
        self.assertEqual(["POST", "POST", "GET", "GET"], [request.method for request in transport.requests])
        self.assertEqual(
            ["ORD123", "ORD123"],
            [request.json_payload["out_trade_no"] for request in transport.requests[:2]],
        )
        rendered_requests = "\n".join(repr(request) for request in transport.requests)
        self.assertNotIn("provider-secret", rendered_requests)
        self.assertNotIn("MCY-CARD-1", repr(proof))

    def test_mcy_shop_offline_idempotency_probe_rejects_non_idempotent_duplicate_order(self) -> None:
        transport = _FakeMcyShopTransport(non_idempotent_orders=True)
        provider = create_mcy_shop_provider(transport)

        with self.assertRaisesRegex(ValueError, "重复建单未证明"):
            asyncio.run(
                ExternalProviderOfflineIdempotencyProbe().prove(
                    provider=provider,
                    tenant_id=7,
                    source_key="shop-a",
                    connection_id=21,
                    runtime_auth=_runtime_auth(),
                    request=ExternalOrderRequest(
                        external_product_id="sku-1",
                        quantity=1,
                        out_trade_no="ORD123",
                    ),
                )
            )

        self.assertEqual(["POST", "POST"], [request.method for request in transport.requests])
        self.assertNotIn("provider-secret", repr(transport.requests))

    def test_mcy_shop_provider_rejects_sensitive_raw_payload(self) -> None:
        transport = _FakeMcyShopTransport(sensitive_catalog_payload=True)
        provider = create_mcy_shop_provider(transport)
        service = ExternalCatalogSyncService(repository=_FakeCatalogRepository())

        with self.assertRaisesRegex(Exception, "敏感|目录获取失败"):
            asyncio.run(
                service.sync_catalog(
                    object(),
                    tenant_id=7,
                    provider=provider,
                    source_key="shop-a",
                    connection_id=21,
                    runtime_auth=_runtime_auth(),
                )
            )

        self.assertEqual(1, len(transport.requests))
        self.assertNotIn("provider-secret", repr(transport.requests[0]))

    def test_mcy_shop_provider_non_json_response_is_protocol_error(self) -> None:
        transport = _FakeMcyShopTransport(non_json_catalog=True)
        provider = create_mcy_shop_provider(transport)
        service = ExternalCatalogSyncService(repository=_FakeCatalogRepository())

        with self.assertRaisesRegex(Exception, "目录获取失败|不是 JSON"):
            asyncio.run(
                service.sync_catalog(
                    object(),
                    tenant_id=7,
                    provider=provider,
                    source_key="shop-a",
                    connection_id=21,
                    runtime_auth=_runtime_auth(),
                )
            )

        self.assertNotIn("provider-secret", repr(transport.requests[0]))

    def test_mcy_shop_provider_rejects_unsafe_credentials_before_http_call(self) -> None:
        invalid_credentials = (
            {"api_key": "provider-secret"},
            {"base_url": "https://mcy-fixture.example/fixture?token=plain", "api_key": "provider-secret"},
            {"base_url": "https://user:secret@mcy-fixture.example/fixture", "api_key": "provider-secret"},
            {"base_url": "https://mcy-shop.internal/fixture", "api_key": "provider-secret"},
            {"base_url": "https://api.mcy-shop.example.com/fixture", "api_key": "provider-secret"},
            {"base_url": "http://8.8.8.8/fixture", "api_key": "provider-secret"},
            {"base_url": "https://localhost.evil.com/fixture", "api_key": "provider-secret"},
            {"base_url": "https://mcy-fixture.test.evil.com/fixture", "api_key": "provider-secret"},
            {"base_url": "https://mcy-fixture.example/fixture", "api_key": "provider-secret", "token": "plain"},
        )

        for credentials in invalid_credentials:
            with self.subTest(credentials=credentials):
                transport = _FakeMcyShopTransport()
                provider = create_mcy_shop_provider(transport)
                with self.assertRaisesRegex(ValueError, "mcy_shop 凭据无效") as caught:
                    provider.validate_connection_credentials(credentials)

                self.assertNotIn("provider-secret", str(caught.exception))
                self.assertNotIn("plain", str(caught.exception))

        runtime_invalid_credentials = (
            {"base_url": "", "api_key": "provider-secret"},
            {"base_url": "https://mcy-fixture.example/fixture?token=plain", "api_key": "provider-secret"},
            {"base_url": "https://user:secret@mcy-fixture.example/fixture", "api_key": "provider-secret"},
            {"base_url": "https://mcy-shop.internal/fixture", "api_key": "provider-secret"},
            {"base_url": "https://api.mcy-shop.example.com/fixture", "api_key": "provider-secret"},
            {"base_url": "http://8.8.8.8/fixture", "api_key": "provider-secret"},
            {"base_url": "https://localhost.evil.com/fixture", "api_key": "provider-secret"},
            {"base_url": "https://mcy-fixture.test.evil.com/fixture", "api_key": "provider-secret"},
            {"base_url": "https://mcy-fixture.example/fixture", "api_key": "provider-secret", "token": "plain"},
        )
        for credentials in runtime_invalid_credentials:
            with self.subTest(runtime_credentials=credentials):
                transport = _FakeMcyShopTransport()
                provider = create_mcy_shop_provider(transport)
                with self.assertRaisesRegex(Exception, "mcy_shop provider 凭据无效"):
                    asyncio.run(
                        provider.list_products_with_context(
                            SimpleNamespace(source_key="shop-a", runtime_auth=_runtime_auth(credentials)),
                            limit=10,
                        )
                    )
                self.assertEqual([], transport.requests)

    def test_mcy_shop_provider_rejects_too_many_catalog_items(self) -> None:
        transport = _FakeMcyShopTransport(oversized_catalog_page=True)
        provider = create_mcy_shop_provider(transport)
        service = ExternalCatalogSyncService(repository=_FakeCatalogRepository())

        with self.assertRaisesRegex(Exception, "目录获取失败|数量不能超过|列表过大"):
            asyncio.run(
                service.sync_catalog(
                    object(),
                    tenant_id=7,
                    provider=provider,
                    source_key="shop-a",
                    connection_id=21,
                    runtime_auth=_runtime_auth(),
                )
            )

        self.assertNotIn("provider-secret", repr(transport.requests[0]))

    def test_mcy_shop_provider_rejects_too_many_delivery_items(self) -> None:
        transport = _FakeMcyShopTransport(oversized_delivery_items=True)
        provider = create_mcy_shop_provider(transport)

        with self.assertRaisesRegex(Exception, "发货条目.*数量|发货条目过多"):
            asyncio.run(
                provider.fetch_delivery_with_context(
                    SimpleNamespace(source_key="shop-a", runtime_auth=_runtime_auth()),
                    "mcy-order-1",
                )
            )

        self.assertNotIn("provider-secret", repr(transport.requests[0]))
        self.assertNotIn("MCY-CARD-100", repr(transport.requests[0]))

    def test_mcy_shop_provider_rejects_oversized_delivery_item(self) -> None:
        transport = _FakeMcyShopTransport(oversized_delivery_item=True)
        provider = create_mcy_shop_provider(transport)

        with self.assertRaisesRegex(Exception, "发货条目.*过长"):
            asyncio.run(
                provider.fetch_delivery_with_context(
                    SimpleNamespace(source_key="shop-a", runtime_auth=_runtime_auth()),
                    "mcy-order-1",
                )
            )

        self.assertNotIn("provider-secret", repr(transport.requests[0]))


if __name__ == "__main__":
    unittest.main()
