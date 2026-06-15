from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Optional
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

try:
    from app.services.external_sources import (
        ExternalCatalogSyncService,
        ExternalDelivery,
        ExternalHttpClient,
        ExternalHttpRequest,
        ExternalHttpResponse,
        ExternalOrder,
        ExternalOrderOperationService,
        ExternalOrderRequest,
        ExternalProduct,
        ExternalProductPage,
        ExternalSourceRuntimeCredentials,
    )
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过外部源 HTTP provider 合同测试：{exc.name}") from exc


class _FakeHttpTransport:
    def __init__(self, *, oversized_catalog_page: bool = False) -> None:
        self.requests: list[ExternalHttpRequest] = []
        self.oversized_catalog_page = oversized_catalog_page

    async def request(self, request: ExternalHttpRequest) -> ExternalHttpResponse:
        self.requests.append(request)
        path = urlsplit(request.url).path
        query = parse_qs(urlsplit(request.url).query)
        if request.method == "GET" and path == "/catalog":
            self._assert_auth(request)
            product = {
                "id": "sku-1",
                "name": "外部卡密商品",
                "price": "6.60",
                "currency": "USDT",
                "status": "on",
                "delivery_type": "card_pool",
                "stock_count": 9,
                "description": "上游商品",
                "category": "账号",
            }
            products = [product] * 101 if self.oversized_catalog_page else [product]
            return ExternalHttpResponse(
                status_code=200,
                json_payload={
                    "products": products,
                    "next_cursor": None,
                    "echo_limit": query.get("limit", [""])[0],
                },
            )
        if request.method == "POST" and path == "/orders":
            self._assert_auth(request)
            payload = request.json_payload or {}
            return ExternalHttpResponse(
                status_code=200,
                json_payload={
                    "order_id": "ext-order-1",
                    "external_product_id": payload.get("external_product_id"),
                    "quantity": payload.get("quantity"),
                    "amount": "6.60",
                    "currency": "USDT",
                    "status": "paid",
                    "delivery_ready": True,
                },
            )
        if request.method == "GET" and path == "/orders/ext-order-1":
            self._assert_auth(request)
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
        if request.method == "GET" and path == "/deliveries/ext-order-1":
            self._assert_auth(request)
            return ExternalHttpResponse(
                status_code=200,
                json_payload={
                    "order_id": "ext-order-1",
                    "delivery_type": "card_pool",
                    "items": ["CARD-1"],
                    "message": "请妥善保存",
                },
            )
        return ExternalHttpResponse(status_code=404, json_payload={"error": "not found"})

    def _assert_auth(self, request: ExternalHttpRequest) -> None:
        if request.headers.get("X-API-Key") != "provider-secret":
            raise AssertionError("fake provider request must carry runtime auth")


class _FakeHttpProvider:
    provider = "httpfake"

    def __init__(self, client: ExternalHttpClient, base_url: str = "https://upstream.example") -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")

    async def list_products(self, tenant_id: int, cursor: Optional[str] = None, limit: int = 50) -> ExternalProductPage:
        raise AssertionError("context-aware provider should receive list_products_with_context")

    async def get_product(self, tenant_id: int, external_product_id: str) -> Optional[ExternalProduct]:
        raise AssertionError("context-aware provider should receive get_product_with_context")

    async def list_products_with_context(self, context, cursor: Optional[str] = None, limit: int = 50) -> ExternalProductPage:
        payload = await self.client.request_json(
            ExternalHttpRequest(
                method="GET",
                url=f"{self.base_url}/catalog?cursor={cursor or ''}&limit={limit}",
                headers=self._headers(context),
            )
        )
        return ExternalProductPage(
            products=[self._product_from_payload(item) for item in payload["products"]],
            next_cursor=payload.get("next_cursor"),
        )

    async def get_product_with_context(self, context, external_product_id: str) -> Optional[ExternalProduct]:
        payload = await self.client.request_json(
            ExternalHttpRequest(
                method="GET",
                url=f"{self.base_url}/catalog/{external_product_id}",
                headers=self._headers(context),
            )
        )
        if payload is None:
            return None
        return self._product_from_payload(payload)

    async def create_order(self, tenant_id: int, request: ExternalOrderRequest) -> ExternalOrder:
        raise AssertionError("context-aware provider should receive create_order_with_context")

    async def query_order(self, tenant_id: int, external_order_id: str) -> Optional[ExternalOrder]:
        raise AssertionError("context-aware provider should receive query_order_with_context")

    async def fetch_delivery(self, tenant_id: int, external_order_id: str) -> Optional[ExternalDelivery]:
        raise AssertionError("context-aware provider should receive fetch_delivery_with_context")

    async def create_order_with_context(self, context, request: ExternalOrderRequest) -> ExternalOrder:
        payload = await self.client.request_json(
            ExternalHttpRequest(
                method="POST",
                url=f"{self.base_url}/orders",
                headers=self._headers(context),
                json_payload={
                    "external_product_id": request.external_product_id,
                    "quantity": request.quantity,
                    "out_trade_no": request.out_trade_no,
                    "buyer_reference": request.buyer_reference,
                },
            )
        )
        return self._order_from_payload(payload)

    async def query_order_with_context(self, context, external_order_id: str) -> Optional[ExternalOrder]:
        payload = await self.client.request_json(
            ExternalHttpRequest(
                method="GET",
                url=f"{self.base_url}/orders/{external_order_id}",
                headers=self._headers(context),
            )
        )
        return self._order_from_payload(payload)

    async def fetch_delivery_with_context(self, context, external_order_id: str) -> Optional[ExternalDelivery]:
        payload = await self.client.request_json(
            ExternalHttpRequest(
                method="GET",
                url=f"{self.base_url}/deliveries/{external_order_id}",
                headers=self._headers(context),
            )
        )
        return ExternalDelivery(
            provider=self.provider,
            external_order_id=payload["order_id"],
            delivery_type=payload["delivery_type"],
            items=tuple(payload.get("items") or ()),
            message=payload.get("message"),
            raw_payload={"result": {"order_id": payload["order_id"], "status": "ok"}},
        )

    def _headers(self, context) -> dict[str, str]:
        runtime_auth = getattr(context, "runtime_auth", None)
        credentials = getattr(runtime_auth, "credentials", {}) if runtime_auth is not None else {}
        return {
            "X-API-Key": credentials["api_key"],
            "X-Source-Key": context.source_key,
        }

    def _product_from_payload(self, payload: dict[str, Any]) -> ExternalProduct:
        return ExternalProduct(
            provider=self.provider,
            external_product_id=payload["id"],
            name=payload["name"],
            price=Decimal(payload["price"]),
            currency=payload["currency"],
            status=payload["status"],
            delivery_type=payload["delivery_type"],
            stock_count=payload.get("stock_count"),
            description=payload.get("description"),
            category=payload.get("category"),
            raw_payload={"result": {"external_id": payload["id"], "status": payload["status"]}},
        )

    def _order_from_payload(self, payload: dict[str, Any]) -> ExternalOrder:
        return ExternalOrder(
            provider=self.provider,
            external_order_id=payload["order_id"],
            external_product_id=payload["external_product_id"],
            status=payload["status"],
            quantity=payload["quantity"],
            amount=Decimal(payload["amount"]),
            currency=payload["currency"],
            delivery_ready=payload["delivery_ready"],
            raw_payload={"result": {"order_id": payload["order_id"], "status": payload["status"]}},
        )


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


def _runtime_auth() -> ExternalSourceRuntimeCredentials:
    return ExternalSourceRuntimeCredentials(
        connection_id=11,
        tenant_id=7,
        provider_name="httpfake",
        source_key="shop-a",
        credential_fields=["sensitive_1"],
        credentials={"api_key": "provider-secret"},
    )


class ExternalHttpProviderContractTest(unittest.TestCase):
    def test_fake_http_provider_syncs_catalog_through_existing_service(self) -> None:
        transport = _FakeHttpTransport()
        provider = _FakeHttpProvider(ExternalHttpClient(transport))
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
        self.assertEqual("provider-secret", transport.requests[0].headers["X-API-Key"])
        self.assertNotIn("provider-secret", repr(transport.requests[0]))
        self.assertNotIn("provider-secret", repr(result))
        stored = repository.products[(7, "httpfake", "shop-a", "sku-1")]
        self.assertEqual("外部卡密商品", stored.name)
        self.assertEqual(Decimal("6.60"), stored.suggested_price)

    def test_sync_catalog_rejects_oversized_provider_page(self) -> None:
        transport = _FakeHttpTransport(oversized_catalog_page=True)
        provider = _FakeHttpProvider(ExternalHttpClient(transport))
        service = ExternalCatalogSyncService(repository=_FakeCatalogRepository())

        with self.assertRaisesRegex(Exception, "目录商品列表过大"):
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

    def test_fake_http_provider_order_lifecycle_through_registered_service(self) -> None:
        transport = _FakeHttpTransport()
        provider = _FakeHttpProvider(ExternalHttpClient(transport))
        service = ExternalOrderOperationService()

        with patch("app.services.external_sources.orders.get_provider", return_value=provider):
            created = asyncio.run(
                service.create_registered_order(
                    tenant_id=7,
                    provider_name="httpfake",
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
                    provider_name="httpfake",
                    source_key="shop-a",
                    connection_id=11,
                    runtime_auth=_runtime_auth(),
                    external_order_id=created.external_order_id,
                )
            )
            delivery = asyncio.run(
                service.fetch_registered_delivery(
                    tenant_id=7,
                    provider_name="httpfake",
                    source_key="shop-a",
                    connection_id=11,
                    runtime_auth=_runtime_auth(),
                    external_order_id=created.external_order_id,
                )
            )

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


if __name__ == "__main__":
    unittest.main()
