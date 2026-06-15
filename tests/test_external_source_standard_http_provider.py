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
        register_provider,
        register_builtin_external_providers,
    )
    import app.services.external_sources.registry as provider_registry
    from app.services.external_sources.standard_http import (
        STANDARD_HTTP_CONTRACT,
        STANDARD_HTTP_PROVIDER,
        create_standard_http_provider,
        validate_standard_http_credentials,
    )
    from app.services.external_sources.mcy_shop import MCY_SHOP_PROVIDER
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过 standard_http 外部源测试：{exc.name}") from exc


class _FakeHttpTransport:
    def __init__(
        self,
        *,
        sensitive_catalog_payload: bool = False,
        non_json_catalog: bool = False,
        custom_paths: bool = False,
        oversized_catalog_page: bool = False,
        oversized_delivery_items: bool = False,
        oversized_delivery_item: bool = False,
        non_idempotent_orders: bool = False,
    ) -> None:
        self.requests: list[ExternalHttpRequest] = []
        self.sensitive_catalog_payload = sensitive_catalog_payload
        self.non_json_catalog = non_json_catalog
        self.custom_paths = custom_paths
        self.oversized_catalog_page = oversized_catalog_page
        self.oversized_delivery_items = oversized_delivery_items
        self.oversized_delivery_item = oversized_delivery_item
        self.non_idempotent_orders = non_idempotent_orders
        self.created_order_count = 0

    async def request(self, request: ExternalHttpRequest) -> ExternalHttpResponse:
        self.requests.append(request)
        path = urlsplit(request.url).path
        query = parse_qs(urlsplit(request.url).query)
        self._assert_auth(request)
        catalog_path = "/api/v1/products" if self.custom_paths else "/api/catalog"
        product_path = "/api/v1/products/sku-1" if self.custom_paths else "/api/catalog/sku-1"
        create_order_path = "/api/v1/purchase" if self.custom_paths else "/api/orders"
        query_order_path = "/api/v1/purchase/ext-order-1" if self.custom_paths else "/api/orders/ext-order-1"
        delivery_path = "/api/v1/purchase/ext-order-1/cards" if self.custom_paths else "/api/deliveries/ext-order-1"
        if request.method == "GET" and path == catalog_path:
            if self.non_json_catalog:
                return ExternalHttpResponse(status_code=200, text="not-json")
            product = {
                "id": "sku-1",
                "name": "HTTP JSON 卡密",
                "price": "6.60",
                "currency": "USDT",
                "status": "on",
                "delivery_type": "card_pool",
                "stock_count": 9,
                "description": "上游商品",
                "category": "账号",
            }
            if self.sensitive_catalog_payload:
                product["api_key"] = "provider-secret"
            products = [product] * 101 if self.oversized_catalog_page else [product]
            return ExternalHttpResponse(
                status_code=200,
                json_payload={
                    "products": products,
                    "next_cursor": None,
                    "echo_limit": query.get("limit", [""])[0],
                },
            )
        if request.method == "GET" and path == product_path:
            return ExternalHttpResponse(
                status_code=200,
                json_payload={
                    "id": "sku-1",
                    "name": "HTTP JSON 卡密",
                    "price": "6.60",
                    "currency": "USDT",
                    "status": "on",
                    "delivery_type": "card_pool",
                },
            )
        if request.method == "POST" and path == create_order_path:
            payload = request.json_payload or {}
            self.created_order_count += 1
            order_id = "ext-order-1"
            if self.non_idempotent_orders:
                order_id = f"ext-order-{self.created_order_count}"
            return ExternalHttpResponse(
                status_code=200,
                json_payload={
                    "order_id": order_id,
                    "external_product_id": payload.get("external_product_id"),
                    "quantity": payload.get("quantity"),
                    "amount": "6.60",
                    "currency": "USDT",
                    "status": "paid",
                    "delivery_ready": True,
                },
            )
        if request.method == "GET" and path == query_order_path:
            return ExternalHttpResponse(
                status_code=200,
                json_payload={
                    "order_id": "ext-order-1",
                    "external_product_id": "sku-1",
                    "quantity": 1,
                    "amount": "6.60",
                    "currency": "USDT",
                    "status": "delivered",
                    "delivery_ready": True,
                },
            )
        if request.method == "GET" and path == delivery_path:
            items = ["CARD-1"]
            if self.oversized_delivery_items:
                items = [f"CARD-{index}" for index in range(101)]
            elif self.oversized_delivery_item:
                items = ["C" * 513]
            return ExternalHttpResponse(
                status_code=200,
                json_payload={
                    "order_id": "ext-order-1",
                    "delivery_type": "card_pool",
                    "items": items,
                    "message": "请妥善保存",
                },
            )
        return ExternalHttpResponse(status_code=404, json_payload={"error": "not found"})

    def _assert_auth(self, request: ExternalHttpRequest) -> None:
        if request.headers.get("X-API-Key") != "provider-secret":
            raise AssertionError("standard_http request must carry runtime auth header")
        if request.headers.get("X-Source-Key") != "shop-a":
            raise AssertionError("standard_http request must carry source key")


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
        "base_url": "https://upstream.example/api",
        "api_key": "provider-secret",
        "timeout_seconds": "5",
    }
    if credentials:
        base_credentials.update(credentials)
    return ExternalSourceRuntimeCredentials(
        connection_id=11,
        tenant_id=7,
        provider_name=STANDARD_HTTP_PROVIDER,
        source_key="shop-a",
        credential_fields=["sensitive_1", "sensitive_2", "sensitive_3", "sensitive_4"],
        credentials=base_credentials,
    )


class StandardHttpExternalSourceProviderTest(unittest.TestCase):
    def test_standard_http_provider_registers_as_builtin_once(self) -> None:
        previous_providers = dict(provider_registry._providers)
        provider_registry._providers.clear()
        try:
            register_builtin_external_providers()
            register_builtin_external_providers()

            self.assertEqual([MCY_SHOP_PROVIDER, STANDARD_HTTP_PROVIDER], list_providers())
            summary = describe_provider(provider_registry._providers[STANDARD_HTTP_PROVIDER])
            self.assertTrue(summary.capabilities.catalog_context_available)
            self.assertTrue(summary.capabilities.catalog_product_context_available)
            self.assertTrue(summary.capabilities.order_context_available)
            self.assertTrue(summary.capabilities.delivery_context_available)
            self.assertFalse(summary.capabilities.auto_fulfillment_idempotent_available)
            self.assertEqual("generic_http_json", summary.integration_kind)
            self.assertEqual(STANDARD_HTTP_CONTRACT, summary.contract_name)
            self.assertFalse(summary.production_ready)
            self.assertFalse(summary.staging_verified)
        finally:
            provider_registry._providers.clear()
            provider_registry._providers.update(previous_providers)

    def test_standard_http_provider_does_not_claim_production_or_auto_fulfillment(self) -> None:
        provider = create_standard_http_provider(_FakeHttpTransport())
        summary = describe_provider(provider)

        self.assertFalse(provider.production_ready)
        self.assertFalse(provider.staging_verified)
        self.assertFalse(provider.auto_fulfillment_idempotent)
        self.assertFalse(summary.production_ready)
        self.assertFalse(summary.staging_verified)
        self.assertFalse(summary.capabilities.auto_fulfillment_idempotent_available)
        self.assertTrue(summary.capabilities.order_context_available)
        self.assertTrue(summary.capabilities.delivery_context_available)

    def test_standard_http_provider_requires_authenticated_context_before_http_call(self) -> None:
        transport = _FakeHttpTransport()
        provider = create_standard_http_provider(transport)

        with self.assertRaisesRegex(Exception, "runtime_auth|运行时凭据"):
            asyncio.run(provider.list_products_with_context(SimpleNamespace(source_key="shop-a"), limit=10))

        self.assertEqual([], transport.requests)

    def test_standard_http_credentials_repr_redacts_api_key(self) -> None:
        credentials = validate_standard_http_credentials(
            {
                "base_url": "https://fixture.example",
                "api_key": "provider-secret",
            }
        )

        self.assertEqual("provider-secret", credentials.api_key)
        self.assertNotIn("provider-secret", repr(credentials))
        self.assertNotIn("api_key=", repr(credentials))

    def test_standard_http_provider_syncs_catalog_with_runtime_credentials(self) -> None:
        transport = _FakeHttpTransport()
        provider = create_standard_http_provider(transport)
        repository = _FakeCatalogRepository()
        service = ExternalCatalogSyncService(repository=repository)

        result = asyncio.run(
            service.sync_catalog(
                object(),
                tenant_id=7,
                provider=provider,
                source_key="shop-a",
                connection_id=11,
                runtime_auth=_runtime_auth(),
            )
        )

        self.assertEqual(1, result.created_count)
        self.assertEqual(0, result.skipped_count)
        self.assertEqual("sku-1", result.products[0].external_id)
        self.assertEqual("on", result.products[0].status)
        self.assertEqual(1, len(transport.requests))
        request = transport.requests[0]
        self.assertEqual("GET", request.method)
        self.assertEqual("/api/catalog", urlsplit(request.url).path)
        self.assertEqual("50", parse_qs(urlsplit(request.url).query)["limit"][0])
        self.assertEqual("provider-secret", request.headers["X-API-Key"])
        self.assertNotIn("provider-secret", repr(request))
        self.assertNotIn("provider-secret", repr(result))
        stored = repository.products[(7, STANDARD_HTTP_PROVIDER, "shop-a", "sku-1")]
        self.assertEqual("HTTP JSON 卡密", stored.name)
        self.assertEqual(Decimal("6.60"), stored.suggested_price)

    def test_standard_http_provider_order_lifecycle_redacts_credentials(self) -> None:
        transport = _FakeHttpTransport()
        provider = create_standard_http_provider(transport)
        service = ExternalOrderOperationService()
        previous_providers = dict(provider_registry._providers)
        provider_registry._providers.clear()
        try:
            register_provider(provider)
            created = asyncio.run(
                service.create_registered_order(
                    tenant_id=7,
                    provider_name=STANDARD_HTTP_PROVIDER,
                    source_key="shop-a",
                    connection_id=11,
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
                    provider_name=STANDARD_HTTP_PROVIDER,
                    source_key="shop-a",
                    connection_id=11,
                    runtime_auth=_runtime_auth(),
                    external_order_id=created.external_order_id,
                )
            )
            delivery = asyncio.run(
                service.fetch_registered_delivery(
                    tenant_id=7,
                    provider_name=STANDARD_HTTP_PROVIDER,
                    source_key="shop-a",
                    connection_id=11,
                    runtime_auth=_runtime_auth(),
                    external_order_id=created.external_order_id,
                )
            )
        finally:
            provider_registry._providers.clear()
            provider_registry._providers.update(previous_providers)

        self.assertEqual("ext-order-1", created.external_order_id)
        self.assertEqual("delivered", queried.status)
        self.assertEqual(("CARD-1",), delivery.items)
        self.assertEqual(["POST", "GET", "GET"], [request.method for request in transport.requests])
        rendered_requests = "\n".join(repr(request) for request in transport.requests)
        self.assertNotIn("provider-secret", rendered_requests)
        self.assertNotIn("ORD123", repr(created.raw_payload))
        self.assertNotIn("provider-secret", repr(created))
        self.assertNotIn("provider-secret", repr(queried))
        self.assertNotIn("provider-secret", repr(delivery))
        self.assertNotIn("CARD-1", repr(delivery))
        self.assertNotIn("请妥善保存", repr(delivery))

    def test_standard_http_offline_idempotency_probe_uses_duplicate_out_trade_no_without_claiming_auto(self) -> None:
        transport = _FakeHttpTransport()
        provider = create_standard_http_provider(transport)

        proof = asyncio.run(
            ExternalProviderOfflineIdempotencyProbe().prove(
                provider=provider,
                tenant_id=7,
                source_key="shop-a",
                connection_id=11,
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
        self.assertEqual("ext-order-1", proof.external_order_id)
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
        self.assertNotIn("CARD-1", repr(proof))

    def test_standard_http_offline_idempotency_probe_rejects_non_idempotent_duplicate_order(self) -> None:
        transport = _FakeHttpTransport(non_idempotent_orders=True)
        provider = create_standard_http_provider(transport)

        with self.assertRaisesRegex(ValueError, "重复建单未证明"):
            asyncio.run(
                ExternalProviderOfflineIdempotencyProbe().prove(
                    provider=provider,
                    tenant_id=7,
                    source_key="shop-a",
                    connection_id=11,
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

    def test_standard_http_provider_uses_configured_safe_path_templates(self) -> None:
        transport = _FakeHttpTransport(custom_paths=True)
        provider = create_standard_http_provider(transport)
        service = ExternalOrderOperationService()
        runtime_auth = _runtime_auth(
            {
                "catalog_path": "v1/products",
                "product_path": "v1/products/{external_product_id}",
                "create_order_path": "v1/purchase",
                "query_order_path": "v1/purchase/{external_order_id}",
                "delivery_path": "v1/purchase/{external_order_id}/cards",
            }
        )
        previous_providers = dict(provider_registry._providers)
        provider_registry._providers.clear()
        register_provider(provider)

        try:
            product = asyncio.run(
                provider.get_product_with_context(
                    SimpleNamespace(source_key="shop-a", runtime_auth=runtime_auth),
                    "sku-1",
                )
            )
            created = asyncio.run(
                service.create_registered_order(
                    tenant_id=7,
                    provider_name=STANDARD_HTTP_PROVIDER,
                    source_key="shop-a",
                    connection_id=11,
                    runtime_auth=runtime_auth,
                    request=ExternalOrderRequest(external_product_id="sku-1", quantity=1),
                )
            )
            queried = asyncio.run(
                service.query_registered_order(
                    tenant_id=7,
                    provider_name=STANDARD_HTTP_PROVIDER,
                    source_key="shop-a",
                    connection_id=11,
                    runtime_auth=runtime_auth,
                    external_order_id=created.external_order_id,
                )
            )
            delivery = asyncio.run(
                service.fetch_registered_delivery(
                    tenant_id=7,
                    provider_name=STANDARD_HTTP_PROVIDER,
                    source_key="shop-a",
                    connection_id=11,
                    runtime_auth=runtime_auth,
                    external_order_id=created.external_order_id,
                )
            )
        finally:
            provider_registry._providers.clear()
            provider_registry._providers.update(previous_providers)

        self.assertEqual("sku-1", product.external_product_id)
        self.assertEqual("delivered", queried.status)
        self.assertEqual(("CARD-1",), delivery.items)
        self.assertEqual(
            [
                "/api/v1/products/sku-1",
                "/api/v1/purchase",
                "/api/v1/purchase/ext-order-1",
                "/api/v1/purchase/ext-order-1/cards",
            ],
            [urlsplit(request.url).path for request in transport.requests],
        )
        rendered_requests = "\n".join(repr(request) for request in transport.requests)
        self.assertNotIn("provider-secret", rendered_requests)

    def test_standard_http_provider_rejects_unsafe_path_templates_before_http_call(self) -> None:
        for credentials in (
            {"catalog_path": "../catalog"},
            {"product_path": "catalog/{unsupported}"},
            {"query_order_path": "orders/{external_order_id}/../detail"},
            {"catalog_path": "https://upstream.example/catalog"},
            {"catalog_path": "catalog?api_key=provider-secret"},
            {"catalog_path": "catalog#section"},
        ):
            with self.subTest(credentials=credentials):
                transport = _FakeHttpTransport()
                provider = create_standard_http_provider(transport)
                service = ExternalCatalogSyncService(repository=_FakeCatalogRepository())

                with self.assertRaisesRegex(Exception, "凭据无效|目录获取失败"):
                    try:
                        asyncio.run(
                            service.sync_catalog(
                                object(),
                                tenant_id=7,
                                provider=provider,
                                source_key="shop-a",
                                connection_id=11,
                                runtime_auth=_runtime_auth(credentials),
                            )
                        )
                    except Exception as exc:
                        self.assertNotIn("provider-secret", str(exc))
                        raise

                self.assertEqual([], transport.requests)

    def test_standard_http_provider_rejects_unsafe_base_url_before_http_call(self) -> None:
        unsafe_base_urls = (
            "http://127.0.0.1/api",
            "http://169.254.169.254/latest",
            "http://localhost/api",
            "http://metadata.google.internal/api",
            "http://service.local/api",
            "https://upstream.example/api?token=provider-secret",
        )
        for base_url in unsafe_base_urls:
            with self.subTest(base_url=base_url):
                transport = _FakeHttpTransport()
                provider = create_standard_http_provider(transport)
                service = ExternalCatalogSyncService(repository=_FakeCatalogRepository())

                with self.assertRaisesRegex(Exception, "凭据无效|目录获取失败"):
                    try:
                        asyncio.run(
                            service.sync_catalog(
                                object(),
                                tenant_id=7,
                                provider=provider,
                                source_key="shop-a",
                                connection_id=11,
                                runtime_auth=_runtime_auth({"base_url": base_url}),
                            )
                        )
                    except Exception as exc:
                        self.assertNotIn("provider-secret", str(exc))
                        raise

                self.assertEqual([], transport.requests)

    def test_standard_http_provider_requires_endpoint_specific_template_variables(self) -> None:
        invalid_credentials = (
            {"catalog_path": "catalog/{external_product_id}"},
            {"product_path": "catalog"},
            {"product_path": "orders/{external_order_id}"},
            {"create_order_path": "orders/{external_order_id}"},
            {"query_order_path": "orders"},
            {"query_order_path": "products/{external_product_id}"},
            {"delivery_path": "deliveries"},
            {"delivery_path": "products/{external_product_id}"},
        )
        for credentials in invalid_credentials:
            with self.subTest(credentials=credentials):
                transport = _FakeHttpTransport()
                provider = create_standard_http_provider(transport)
                service = ExternalCatalogSyncService(repository=_FakeCatalogRepository())

                with self.assertRaisesRegex(Exception, "凭据无效|目录获取失败"):
                    try:
                        asyncio.run(
                            service.sync_catalog(
                                object(),
                                tenant_id=7,
                                provider=provider,
                                source_key="shop-a",
                                connection_id=11,
                                runtime_auth=_runtime_auth(credentials),
                            )
                        )
                    except Exception as exc:
                        self.assertNotIn("provider-secret", str(exc))
                        raise

                self.assertEqual([], transport.requests)

    def test_standard_http_provider_rejects_path_variable_path_injection(self) -> None:
        transport = _FakeHttpTransport()
        provider = create_standard_http_provider(transport)

        with self.assertRaisesRegex(Exception, "path segment|路径"):
            asyncio.run(
                provider.get_product_with_context(
                    SimpleNamespace(source_key="shop-a", runtime_auth=_runtime_auth()),
                    "../sku-1",
                )
            )

        self.assertEqual([], transport.requests)

    def test_standard_http_provider_rejects_sensitive_raw_payload(self) -> None:
        transport = _FakeHttpTransport(sensitive_catalog_payload=True)
        provider = create_standard_http_provider(transport)
        service = ExternalCatalogSyncService(repository=_FakeCatalogRepository())

        with self.assertRaisesRegex(Exception, "敏感|目录获取失败"):
            asyncio.run(
                service.sync_catalog(
                    object(),
                    tenant_id=7,
                    provider=provider,
                    source_key="shop-a",
                    connection_id=11,
                    runtime_auth=_runtime_auth(),
                )
            )

        self.assertEqual(1, len(transport.requests))
        self.assertNotIn("provider-secret", repr(transport.requests[0]))

    def test_standard_http_provider_non_json_response_is_protocol_error(self) -> None:
        transport = _FakeHttpTransport(non_json_catalog=True)
        provider = create_standard_http_provider(transport)
        service = ExternalCatalogSyncService(repository=_FakeCatalogRepository())

        with self.assertRaisesRegex(Exception, "目录获取失败|不是 JSON"):
            asyncio.run(
                service.sync_catalog(
                    object(),
                    tenant_id=7,
                    provider=provider,
                    source_key="shop-a",
                    connection_id=11,
                    runtime_auth=_runtime_auth(),
                )
            )

        self.assertNotIn("provider-secret", repr(transport.requests[0]))

    def test_standard_http_provider_rejects_too_many_catalog_products(self) -> None:
        transport = _FakeHttpTransport(oversized_catalog_page=True)
        provider = create_standard_http_provider(transport)
        service = ExternalCatalogSyncService(repository=_FakeCatalogRepository())

        with self.assertRaisesRegex(Exception, "目录获取失败|数量不能超过|列表过大"):
            asyncio.run(
                service.sync_catalog(
                    object(),
                    tenant_id=7,
                    provider=provider,
                    source_key="shop-a",
                    connection_id=11,
                    runtime_auth=_runtime_auth(),
                )
            )

        self.assertNotIn("provider-secret", repr(transport.requests[0]))

    def test_standard_http_provider_rejects_too_many_delivery_items(self) -> None:
        transport = _FakeHttpTransport(oversized_delivery_items=True)
        provider = create_standard_http_provider(transport)

        with self.assertRaisesRegex(Exception, "发货条目.*数量|发货条目过多"):
            asyncio.run(
                provider.fetch_delivery_with_context(
                    SimpleNamespace(source_key="shop-a", runtime_auth=_runtime_auth()),
                    "ext-order-1",
                )
            )

        self.assertNotIn("provider-secret", repr(transport.requests[0]))
        self.assertNotIn("CARD-100", repr(transport.requests[0]))

    def test_standard_http_provider_rejects_oversized_delivery_item(self) -> None:
        transport = _FakeHttpTransport(oversized_delivery_item=True)
        provider = create_standard_http_provider(transport)

        with self.assertRaisesRegex(Exception, "发货条目.*过长"):
            asyncio.run(
                provider.fetch_delivery_with_context(
                    SimpleNamespace(source_key="shop-a", runtime_auth=_runtime_auth()),
                    "ext-order-1",
                )
            )

        self.assertNotIn("provider-secret", repr(transport.requests[0]))


if __name__ == "__main__":
    unittest.main()
