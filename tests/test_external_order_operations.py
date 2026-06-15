from __future__ import annotations

import unittest
from datetime import datetime
from decimal import Decimal
from typing import Optional
from unittest.mock import patch

try:
    from app.services.external_sources import (
        ExternalAuthenticatedOperationContext,
        ExternalDelivery,
        ExternalOrder,
        ExternalOrderOperationService,
        ExternalOrderRequest,
        ExternalProviderNotRegisteredError,
        ExternalSourceRuntimeCredentials,
        ExternalSourceError,
        ExternalSourceOperationContext,
    )
    from app.services.external_sources.limits import (
        MAX_EXTERNAL_DELIVERY_ITEM_LENGTH,
        MAX_EXTERNAL_DELIVERY_ITEMS,
        MAX_EXTERNAL_DELIVERY_MESSAGE_LENGTH,
    )
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过外部订单编排测试：{exc.name}") from exc


class FakeContextOrderProvider:
    provider = "acg"

    def __init__(self) -> None:
        self.context_calls: list[tuple[str, ExternalSourceOperationContext]] = []
        self.create_requests: list[ExternalOrderRequest] = []

    async def create_order(self, tenant_id: int, request: ExternalOrderRequest) -> ExternalOrder:
        raise AssertionError("context-aware provider should receive create_order_with_context")

    async def query_order(self, tenant_id: int, external_order_id: str) -> Optional[ExternalOrder]:
        raise AssertionError("context-aware provider should receive query_order_with_context")

    async def fetch_delivery(self, tenant_id: int, external_order_id: str) -> Optional[ExternalDelivery]:
        raise AssertionError("context-aware provider should receive fetch_delivery_with_context")

    async def create_order_with_context(
        self,
        context: ExternalSourceOperationContext,
        request: ExternalOrderRequest,
    ) -> ExternalOrder:
        self.context_calls.append(("create", context))
        self.create_requests.append(request)
        return ExternalOrder(
            provider=self.provider,
            external_order_id="ext-order-1",
            external_product_id=request.external_product_id,
            status="paid",
            quantity=request.quantity,
            amount=Decimal("1.00"),
        )

    async def query_order_with_context(
        self,
        context: ExternalSourceOperationContext,
        external_order_id: str,
    ) -> Optional[ExternalOrder]:
        self.context_calls.append(("query", context))
        return ExternalOrder(
            provider=self.provider,
            external_order_id=external_order_id,
            external_product_id="sku-1",
            status="delivered",
            quantity=1,
            amount=Decimal("1.00"),
        )

    async def fetch_delivery_with_context(
        self,
        context: ExternalSourceOperationContext,
        external_order_id: str,
    ) -> Optional[ExternalDelivery]:
        self.context_calls.append(("delivery", context))
        return ExternalDelivery(
            provider=self.provider,
            external_order_id=external_order_id,
            delivery_type="card_pool",
            items=("card-1",),
        )


class FakeLegacyOrderProvider:
    provider = "legacy"

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    async def create_order(self, tenant_id: int, request: ExternalOrderRequest) -> ExternalOrder:
        self.calls.append(("create", tenant_id))
        return ExternalOrder(
            provider=self.provider,
            external_order_id="legacy-order-1",
            external_product_id=request.external_product_id,
            status="created",
            quantity=request.quantity,
            amount=Decimal("2.00"),
        )

    async def query_order(self, tenant_id: int, external_order_id: str) -> Optional[ExternalOrder]:
        self.calls.append(("query", tenant_id))
        return ExternalOrder(
            provider=self.provider,
            external_order_id=external_order_id,
            external_product_id="sku-1",
            status="paid",
            quantity=1,
            amount=Decimal("2.00"),
        )

    async def fetch_delivery(self, tenant_id: int, external_order_id: str) -> Optional[ExternalDelivery]:
        self.calls.append(("delivery", tenant_id))
        return ExternalDelivery(
            provider=self.provider,
            external_order_id=external_order_id,
            delivery_type="card_pool",
            items=("legacy-card",),
        )


def _runtime_auth(
    *,
    tenant_id: int = 7,
    connection_id: int = 11,
    provider_name: str = "acg",
    source_key: str = "shop-a",
) -> ExternalSourceRuntimeCredentials:
    return ExternalSourceRuntimeCredentials(
        connection_id=connection_id,
        tenant_id=tenant_id,
        provider_name=provider_name,
        source_key=source_key,
        credential_fields=["sensitive_1"],
        credentials={"api_key": "secret-value"},
    )


class FakeCatalogOnlyProvider:
    provider = "catalog-only"

    async def list_products(self, tenant_id: int, cursor: Optional[str] = None, limit: int = 50):
        raise AssertionError("order operation service must not call catalog methods")


class FakeOrderOnlyProvider:
    provider = "order-only"

    async def create_order(self, tenant_id: int, request: ExternalOrderRequest) -> ExternalOrder:
        return ExternalOrder(
            provider=self.provider,
            external_order_id="order-only-1",
            external_product_id=request.external_product_id,
            status="created",
            quantity=request.quantity,
            amount=Decimal("3.00"),
        )

    async def query_order(self, tenant_id: int, external_order_id: str) -> Optional[ExternalOrder]:
        return ExternalOrder(
            provider=self.provider,
            external_order_id=external_order_id,
            external_product_id="sku-1",
            status="created",
            quantity=1,
            amount=Decimal("3.00"),
        )


class FakeOrderResultProvider:
    provider = "acg"

    def __init__(
        self,
        *,
        order: Optional[ExternalOrder] = None,
        delivery: Optional[ExternalDelivery] = None,
    ) -> None:
        self.order = order
        self.delivery = delivery

    async def create_order(self, tenant_id: int, request: ExternalOrderRequest):
        return self.order

    async def query_order(self, tenant_id: int, external_order_id: str):
        return self.order

    async def fetch_delivery(self, tenant_id: int, external_order_id: str):
        return self.delivery


class FakeFailingOperationProvider:
    provider = "acg"

    def __init__(
        self,
        *,
        create_error: Optional[Exception] = None,
        query_error: Optional[Exception] = None,
        delivery_error: Optional[Exception] = None,
    ) -> None:
        self.create_error = create_error
        self.query_error = query_error
        self.delivery_error = delivery_error

    async def create_order(self, tenant_id: int, request: ExternalOrderRequest) -> ExternalOrder:
        if self.create_error is not None:
            raise self.create_error
        return ExternalOrder(
            provider=self.provider,
            external_order_id="ext-order-1",
            external_product_id=request.external_product_id,
            status="created",
            quantity=request.quantity,
            amount=Decimal("1.00"),
        )

    async def query_order(self, tenant_id: int, external_order_id: str) -> Optional[ExternalOrder]:
        if self.query_error is not None:
            raise self.query_error
        return ExternalOrder(
            provider=self.provider,
            external_order_id=external_order_id,
            external_product_id="sku-1",
            status="created",
            quantity=1,
            amount=Decimal("1.00"),
        )

    async def fetch_delivery(self, tenant_id: int, external_order_id: str) -> Optional[ExternalDelivery]:
        if self.delivery_error is not None:
            raise self.delivery_error
        return ExternalDelivery(
            provider=self.provider,
            external_order_id=external_order_id,
            delivery_type="card_pool",
            items=("card-1",),
        )


class FakeFailingContextOperationProvider(FakeFailingOperationProvider):
    def __init__(
        self,
        *,
        create_error: Optional[Exception] = None,
        query_error: Optional[Exception] = None,
        delivery_error: Optional[Exception] = None,
    ) -> None:
        super().__init__(
            create_error=create_error,
            query_error=query_error,
            delivery_error=delivery_error,
        )
        self.context_calls: list[tuple[str, ExternalSourceOperationContext]] = []

    async def create_order(self, tenant_id: int, request: ExternalOrderRequest) -> ExternalOrder:
        raise AssertionError("context-aware provider should receive create_order_with_context")

    async def query_order(self, tenant_id: int, external_order_id: str) -> Optional[ExternalOrder]:
        raise AssertionError("context-aware provider should receive query_order_with_context")

    async def fetch_delivery(self, tenant_id: int, external_order_id: str) -> Optional[ExternalDelivery]:
        raise AssertionError("context-aware provider should receive fetch_delivery_with_context")

    async def create_order_with_context(
        self,
        context: ExternalSourceOperationContext,
        request: ExternalOrderRequest,
    ) -> ExternalOrder:
        self.context_calls.append(("create", context))
        return await super().create_order(context.tenant_id, request)

    async def query_order_with_context(
        self,
        context: ExternalSourceOperationContext,
        external_order_id: str,
    ) -> Optional[ExternalOrder]:
        self.context_calls.append(("query", context))
        return await super().query_order(context.tenant_id, external_order_id)

    async def fetch_delivery_with_context(
        self,
        context: ExternalSourceOperationContext,
        external_order_id: str,
    ) -> Optional[ExternalDelivery]:
        self.context_calls.append(("delivery", context))
        return await super().fetch_delivery(context.tenant_id, external_order_id)


class ExternalOrderOperationServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_context_provider_receives_non_sensitive_operation_context(self) -> None:
        provider = FakeContextOrderProvider()
        provider.provider = " acg "
        service = ExternalOrderOperationService()

        with patch("app.services.external_sources.orders.get_provider", return_value=provider) as get_provider:
            order = await service.create_registered_order(
                tenant_id=7,
                provider_name=" acg ",
                source_key=" shop-a ",
                connection_id=11,
                request=ExternalOrderRequest(external_product_id="sku-1", quantity=1),
            )
            queried = await service.query_registered_order(
                tenant_id=7,
                provider_name="acg",
                source_key=" shop-a ",
                connection_id=11,
                external_order_id=order.external_order_id,
            )
            delivery = await service.fetch_registered_delivery(
                tenant_id=7,
                provider_name="acg",
                source_key=" shop-a ",
                connection_id=11,
                external_order_id=order.external_order_id,
            )

        self.assertEqual("ext-order-1", order.external_order_id)
        self.assertIsNotNone(queried)
        self.assertIsNotNone(delivery)
        self.assertEqual(["acg", "acg", "acg"], [call.args[0] for call in get_provider.call_args_list])
        self.assertEqual(["create", "query", "delivery"], [name for name, _ in provider.context_calls])
        for _, context in provider.context_calls:
            payload = context.__dict__
            self.assertEqual({"tenant_id", "provider_name", "source_key", "connection_id"}, set(payload))
            self.assertEqual(7, context.tenant_id)
            self.assertEqual("acg", context.provider_name)
            self.assertEqual("shop-a", context.source_key)
            self.assertEqual(11, context.connection_id)
            self.assertNotIn("credentials", payload)
            self.assertNotIn("credentials_encrypted", payload)
            self.assertNotIn("token", payload)
            self.assertNotIn("secret", payload)
            self.assertNotIn("api_key", payload)
            self.assertNotIn("password", payload)

    async def test_context_provider_receives_redacted_runtime_auth_when_supplied(self) -> None:
        provider = FakeContextOrderProvider()
        runtime_auth = _runtime_auth()
        service = ExternalOrderOperationService()

        with patch("app.services.external_sources.orders.get_provider", return_value=provider):
            order = await service.create_registered_order(
                tenant_id=7,
                provider_name="acg",
                source_key="shop-a",
                connection_id=11,
                runtime_auth=runtime_auth,
                request=ExternalOrderRequest(external_product_id="sku-1", quantity=1),
            )
            queried = await service.query_registered_order(
                tenant_id=7,
                provider_name="acg",
                source_key="shop-a",
                connection_id=11,
                runtime_auth=runtime_auth,
                external_order_id=order.external_order_id,
            )
            delivery = await service.fetch_registered_delivery(
                tenant_id=7,
                provider_name="acg",
                source_key="shop-a",
                connection_id=11,
                runtime_auth=runtime_auth,
                external_order_id=order.external_order_id,
            )

        self.assertIsNotNone(queried)
        self.assertIsNotNone(delivery)
        self.assertEqual(["create", "query", "delivery"], [name for name, _ in provider.context_calls])
        for _, context in provider.context_calls:
            self.assertIsInstance(context, ExternalAuthenticatedOperationContext)
            self.assertIs(runtime_auth, context.runtime_auth)
            rendered = f"{context!r} {context.__dict__!r}"
            self.assertIn("runtime_auth='***'", repr(context))
            self.assertNotIn("secret-value", rendered)
            self.assertNotIn("api_key", rendered)
            self.assertNotIn("credentials_encrypted", rendered)

    async def test_context_provider_rejects_runtime_auth_mismatch_before_provider_call(self) -> None:
        provider = FakeContextOrderProvider()
        service = ExternalOrderOperationService()

        with patch("app.services.external_sources.orders.get_provider", return_value=provider):
            with self.assertRaisesRegex(ValueError, "runtime_auth source_key"):
                await service.create_registered_order(
                    tenant_id=7,
                    provider_name="acg",
                    source_key="shop-a",
                    connection_id=11,
                    runtime_auth=_runtime_auth(source_key="other"),
                    request=ExternalOrderRequest(external_product_id="sku-1", quantity=1),
                )

        self.assertEqual([], provider.context_calls)

    async def test_create_order_normalizes_request_before_provider_call(self) -> None:
        provider = FakeContextOrderProvider()
        service = ExternalOrderOperationService()

        with patch("app.services.external_sources.orders.get_provider", return_value=provider):
            order = await service.create_registered_order(
                tenant_id=7,
                provider_name="acg",
                request=ExternalOrderRequest(
                    external_product_id=" sku-1 ",
                    quantity=2,
                    out_trade_no=" OUT-1 ",
                    buyer_reference=" buyer-1 ",
                    buyer_contact=" buyer@example.com ",
                    metadata={
                        " trace_id ": " trace-1 ",
                        "empty_note": " ",
                        "ratio": 1.5,
                        "nested": {" flag ": True, " count ": 2},
                        "tags": (" a ", {" k ": " v "}),
                    },
                ),
            )

        self.assertEqual("sku-1", order.external_product_id)
        self.assertEqual(1, len(provider.create_requests))
        request = provider.create_requests[0]
        self.assertEqual("sku-1", request.external_product_id)
        self.assertEqual(2, request.quantity)
        self.assertEqual("OUT-1", request.out_trade_no)
        self.assertEqual("buyer-1", request.buyer_reference)
        self.assertEqual("buyer@example.com", request.buyer_contact)
        self.assertEqual(
            {
                "trace_id": "trace-1",
                "empty_note": "",
                "ratio": 1.5,
                "nested": {"flag": True, "count": 2},
                "tags": ["a", {"k": "v"}],
            },
            request.metadata,
        )

    async def test_invalid_operation_identifiers_are_rejected_before_provider_lookup(self) -> None:
        service = ExternalOrderOperationService()

        with patch("app.services.external_sources.orders.get_provider") as get_provider:
            with self.assertRaisesRegex(ValueError, "tenant_id"):
                await service.create_registered_order(
                    tenant_id=0,
                    provider_name="acg",
                    request=ExternalOrderRequest(external_product_id="sku-1"),
                )
            with self.assertRaisesRegex(ValueError, "tenant_id"):
                await service.create_registered_order(
                    tenant_id=True,
                    provider_name="acg",
                    request=ExternalOrderRequest(external_product_id="sku-1"),
                )
            with self.assertRaisesRegex(ValueError, "tenant_id"):
                await service.create_registered_order(
                    tenant_id="1",
                    provider_name="acg",
                    request=ExternalOrderRequest(external_product_id="sku-1"),
                )
            with self.assertRaisesRegex(ValueError, "connection_id"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    connection_id=0,
                    request=ExternalOrderRequest(external_product_id="sku-1"),
                )
            with self.assertRaisesRegex(ValueError, "connection_id"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    connection_id=True,
                    request=ExternalOrderRequest(external_product_id="sku-1"),
                )
            with self.assertRaisesRegex(ValueError, "connection_id"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    connection_id="1",
                    request=ExternalOrderRequest(external_product_id="sku-1"),
                )
            with self.assertRaisesRegex(ValueError, "request"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=object(),
                )
            with self.assertRaisesRegex(ValueError, "external_product_id"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=ExternalOrderRequest(external_product_id=123),
                )
            with self.assertRaisesRegex(ValueError, "external_product_id"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=ExternalOrderRequest(external_product_id=" "),
                )
            with self.assertRaisesRegex(ValueError, "external_product_id 长度"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=ExternalOrderRequest(external_product_id="x" * 129),
                )
            with self.assertRaisesRegex(ValueError, "external_product_id 不能包含控制字符"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=ExternalOrderRequest(external_product_id="sku\n1"),
                )
            with self.assertRaisesRegex(ValueError, "quantity"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=ExternalOrderRequest(external_product_id="sku-1", quantity=0),
                )
            with self.assertRaisesRegex(ValueError, "quantity"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=ExternalOrderRequest(external_product_id="sku-1", quantity=True),
                )
            with self.assertRaisesRegex(ValueError, "quantity"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=ExternalOrderRequest(external_product_id="sku-1", quantity=Decimal("1")),
                )
            with self.assertRaisesRegex(ValueError, "out_trade_no"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=ExternalOrderRequest(external_product_id="sku-1", out_trade_no=123),
                )
            with self.assertRaisesRegex(ValueError, "out_trade_no"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=ExternalOrderRequest(external_product_id="sku-1", out_trade_no="x" * 97),
                )
            with self.assertRaisesRegex(ValueError, "buyer_reference"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=ExternalOrderRequest(external_product_id="sku-1", buyer_reference=123),
                )
            with self.assertRaisesRegex(ValueError, "buyer_reference"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=ExternalOrderRequest(external_product_id="sku-1", buyer_reference="buyer\n1"),
                )
            with self.assertRaisesRegex(ValueError, "buyer_contact"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=ExternalOrderRequest(external_product_id="sku-1", buyer_contact="x" * 257),
                )
            with self.assertRaisesRegex(ValueError, "metadata"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=ExternalOrderRequest(external_product_id="sku-1", metadata=None),
                )
            with self.assertRaisesRegex(ValueError, "metadata 字段名必须是字符串"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=ExternalOrderRequest(external_product_id="sku-1", metadata={123: "value"}),
                )
            with self.assertRaisesRegex(ValueError, "metadata 字段名重复"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=ExternalOrderRequest(
                        external_product_id="sku-1",
                        metadata={" trace_id ": "one", "trace_id": "two"},
                    ),
                )
            with self.assertRaisesRegex(ValueError, "metadata 字符串值"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=ExternalOrderRequest(
                        external_product_id="sku-1",
                        metadata={"note": "bad\nvalue"},
                    ),
                )
            with self.assertRaisesRegex(ValueError, "metadata 字符串值"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=ExternalOrderRequest(
                        external_product_id="sku-1",
                        metadata={"note": "x" * 513},
                    ),
                )
            with self.assertRaisesRegex(ValueError, "metadata 数字值"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=ExternalOrderRequest(
                        external_product_id="sku-1",
                        metadata={"ratio": float("inf")},
                    ),
                )
            with self.assertRaisesRegex(ValueError, "metadata 字段值"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=ExternalOrderRequest(
                        external_product_id="sku-1",
                        metadata={"amount": Decimal("1.00")},
                    ),
                )
            with self.assertRaisesRegex(ValueError, "metadata 字段值"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=ExternalOrderRequest(
                        external_product_id="sku-1",
                        metadata={"payload": object()},
                    ),
                )
            with self.assertRaisesRegex(ValueError, "metadata 字段值"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=ExternalOrderRequest(
                        external_product_id="sku-1",
                        metadata={"payload": b"bytes"},
                    ),
                )
            with self.assertRaisesRegex(ValueError, "metadata 字段值"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=ExternalOrderRequest(
                        external_product_id="sku-1",
                        metadata={"payload": {"a", "b"}},
                    ),
                )
            with self.assertRaisesRegex(ValueError, "metadata 字段值"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=ExternalOrderRequest(
                        external_product_id="sku-1",
                        metadata={"payload": datetime(2026, 6, 8)},
                    ),
                )
            with self.assertRaisesRegex(ValueError, "metadata 字段名必须是字符串"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=ExternalOrderRequest(
                        external_product_id="sku-1",
                        metadata={"nested": {123: "value"}},
                    ),
                )
            with self.assertRaisesRegex(ValueError, "metadata 数组长度"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=ExternalOrderRequest(
                        external_product_id="sku-1",
                        metadata={"items": list(range(51))},
                    ),
                )
            with self.assertRaisesRegex(ValueError, "metadata 嵌套层级"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=ExternalOrderRequest(
                        external_product_id="sku-1",
                        metadata={"a": {"b": {"c": {"d": {"e": "too-deep"}}}}},
                    ),
                )
            with self.assertRaisesRegex(ValueError, "metadata 包含敏感字段"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    request=ExternalOrderRequest(
                        external_product_id="sku-1",
                        metadata={"nested": {"api_token": "secret"}},
                    ),
                )
            with self.assertRaisesRegex(ValueError, "provider_name"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="ACG",
                    request=ExternalOrderRequest(external_product_id="sku-1"),
                )
            with self.assertRaisesRegex(ValueError, "provider_name"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name=None,
                    request=ExternalOrderRequest(external_product_id="sku-1"),
                )
            with self.assertRaisesRegex(ValueError, "provider_name"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name=123,
                    request=ExternalOrderRequest(external_product_id="sku-1"),
                )
            with self.assertRaisesRegex(ValueError, "provider_name"):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name=" ",
                    request=ExternalOrderRequest(external_product_id="sku-1"),
                )
            with self.assertRaisesRegex(ValueError, "external_order_id"):
                await service.query_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    external_order_id=None,
                )
            with self.assertRaisesRegex(ValueError, "external_order_id"):
                await service.query_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    external_order_id=123,
                )
            with self.assertRaisesRegex(ValueError, "external_order_id"):
                await service.query_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    external_order_id=" ",
                )
            with self.assertRaisesRegex(ValueError, "external_order_id 长度"):
                await service.query_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    external_order_id="x" * 129,
                )
            with self.assertRaisesRegex(ValueError, "external_order_id 不能包含控制字符"):
                await service.query_registered_order(
                    tenant_id=1,
                    provider_name="acg",
                    external_order_id="ext\n1",
                )
            with self.assertRaisesRegex(ValueError, "external_order_id"):
                await service.fetch_registered_delivery(
                    tenant_id=1,
                    provider_name="acg",
                    external_order_id=None,
                )
            with self.assertRaisesRegex(ValueError, "external_order_id"):
                await service.fetch_registered_delivery(
                    tenant_id=1,
                    provider_name="acg",
                    external_order_id=123,
                )
            with self.assertRaisesRegex(ValueError, "external_order_id"):
                await service.fetch_registered_delivery(
                    tenant_id=1,
                    provider_name="acg",
                    external_order_id=" ",
                )
            with self.assertRaisesRegex(ValueError, "external_order_id 长度"):
                await service.fetch_registered_delivery(
                    tenant_id=1,
                    provider_name="acg",
                    external_order_id="x" * 129,
                )
            with self.assertRaisesRegex(ValueError, "external_order_id 不能包含控制字符"):
                await service.fetch_registered_delivery(
                    tenant_id=1,
                    provider_name="acg",
                    external_order_id="ext\n1",
                )

        get_provider.assert_not_called()

    async def test_invalid_source_key_is_rejected_before_provider_lookup(self) -> None:
        service = ExternalOrderOperationService()

        with patch("app.services.external_sources.orders.get_provider") as get_provider:
            with self.assertRaisesRegex(ValueError, "source_key"):
                await service.create_registered_order(
                    tenant_id=7,
                    provider_name="acg",
                    source_key="Shop A",
                    request=ExternalOrderRequest(external_product_id="sku-1"),
                )
            with self.assertRaisesRegex(ValueError, "source_key"):
                await service.create_registered_order(
                    tenant_id=7,
                    provider_name="acg",
                    source_key=None,
                    request=ExternalOrderRequest(external_product_id="sku-1"),
                )
            with self.assertRaisesRegex(ValueError, "source_key"):
                await service.create_registered_order(
                    tenant_id=7,
                    provider_name="acg",
                    source_key=123,
                    request=ExternalOrderRequest(external_product_id="sku-1"),
                )
            with self.assertRaisesRegex(ValueError, "source_key"):
                await service.query_registered_order(
                    tenant_id=7,
                    provider_name="acg",
                    source_key="Shop A",
                    external_order_id="ext-order-1",
                )
            with self.assertRaisesRegex(ValueError, "source_key"):
                await service.fetch_registered_delivery(
                    tenant_id=7,
                    provider_name="acg",
                    source_key="Shop A",
                    external_order_id="ext-order-1",
                )

        get_provider.assert_not_called()

    async def test_legacy_provider_keeps_existing_tenant_id_contract(self) -> None:
        provider = FakeLegacyOrderProvider()
        service = ExternalOrderOperationService()

        with patch("app.services.external_sources.orders.get_provider", return_value=provider):
            order = await service.create_registered_order(
                tenant_id=3,
                provider_name="legacy",
                request=ExternalOrderRequest(external_product_id="sku-1", quantity=2),
            )
            queried = await service.query_registered_order(
                tenant_id=3,
                provider_name="legacy",
                external_order_id=order.external_order_id,
            )
            delivery = await service.fetch_registered_delivery(
                tenant_id=3,
                provider_name="legacy",
                external_order_id=order.external_order_id,
            )

        self.assertEqual("legacy-order-1", order.external_order_id)
        self.assertIsNotNone(queried)
        self.assertIsNotNone(delivery)
        self.assertEqual([("create", 3), ("query", 3), ("delivery", 3)], provider.calls)

    async def test_unknown_provider_is_rejected(self) -> None:
        service = ExternalOrderOperationService()

        with patch("app.services.external_sources.orders.get_provider", return_value=None):
            with self.assertRaises(ExternalProviderNotRegisteredError):
                await service.create_registered_order(
                    tenant_id=1,
                    provider_name="missing",
                    request=ExternalOrderRequest(external_product_id="sku-1"),
                )
            with self.assertRaises(ExternalProviderNotRegisteredError):
                await service.query_registered_order(
                    tenant_id=1,
                    provider_name="missing",
                    external_order_id="ext-order-1",
                )
            with self.assertRaises(ExternalProviderNotRegisteredError):
                await service.fetch_registered_delivery(
                    tenant_id=1,
                    provider_name="missing",
                    external_order_id="ext-order-1",
                )

    async def test_provider_without_order_capability_is_rejected_with_clear_error(self) -> None:
        provider = FakeCatalogOnlyProvider()
        service = ExternalOrderOperationService()

        with patch("app.services.external_sources.orders.get_provider", return_value=provider):
            with self.assertRaisesRegex(ExternalSourceError, "不支持创建订单"):
                await service.create_registered_order(
                    tenant_id=7,
                    provider_name="catalog-only",
                    request=ExternalOrderRequest(external_product_id="sku-1"),
                )
            with self.assertRaisesRegex(ExternalSourceError, "不支持查询订单"):
                await service.query_registered_order(
                    tenant_id=7,
                    provider_name="catalog-only",
                    external_order_id="ext-order-1",
                )
            with self.assertRaisesRegex(ExternalSourceError, "不支持获取发货"):
                await service.fetch_registered_delivery(
                    tenant_id=7,
                    provider_name="catalog-only",
                    external_order_id="ext-order-1",
                )

    async def test_provider_without_delivery_capability_is_rejected_with_clear_error(self) -> None:
        provider = FakeOrderOnlyProvider()
        service = ExternalOrderOperationService()

        with patch("app.services.external_sources.orders.get_provider", return_value=provider):
            order = await service.create_registered_order(
                tenant_id=7,
                provider_name="order-only",
                request=ExternalOrderRequest(external_product_id="sku-1"),
            )
            queried = await service.query_registered_order(
                tenant_id=7,
                provider_name="order-only",
                external_order_id=order.external_order_id,
            )
            with self.assertRaisesRegex(ExternalSourceError, "不支持获取发货"):
                await service.fetch_registered_delivery(
                    tenant_id=7,
                    provider_name="order-only",
                    external_order_id=order.external_order_id,
                )

        self.assertEqual("order-only-1", order.external_order_id)
        self.assertIsNotNone(queried)

    async def test_provider_create_order_errors_are_wrapped_with_cause(self) -> None:
        provider_error = ValueError("bad provider payload")
        provider = FakeFailingOperationProvider(create_error=provider_error)
        service = ExternalOrderOperationService()

        with patch("app.services.external_sources.orders.get_provider", return_value=provider):
            with self.assertRaisesRegex(ExternalSourceError, "创建订单失败") as caught:
                await service.create_registered_order(
                    tenant_id=7,
                    provider_name="acg",
                    request=ExternalOrderRequest(external_product_id="sku-1", quantity=1),
                )

        self.assertIs(provider_error, caught.exception.__cause__)

    async def test_context_provider_create_order_errors_are_wrapped_with_cause(self) -> None:
        provider_error = RuntimeError("upstream create failed")
        provider = FakeFailingContextOperationProvider(create_error=provider_error)
        service = ExternalOrderOperationService()

        with patch("app.services.external_sources.orders.get_provider", return_value=provider):
            with self.assertRaisesRegex(ExternalSourceError, "创建订单失败") as caught:
                await service.create_registered_order(
                    tenant_id=7,
                    provider_name="acg",
                    source_key="shop-a",
                    connection_id=11,
                    request=ExternalOrderRequest(external_product_id="sku-1", quantity=1),
                )

        self.assertIs(provider_error, caught.exception.__cause__)
        self.assertEqual(["create"], [name for name, _ in provider.context_calls])

    async def test_provider_query_order_errors_are_wrapped_with_cause(self) -> None:
        provider_error = TimeoutError("query timeout")
        provider = FakeFailingOperationProvider(query_error=provider_error)
        service = ExternalOrderOperationService()

        with patch("app.services.external_sources.orders.get_provider", return_value=provider):
            with self.assertRaisesRegex(ExternalSourceError, "查询订单失败") as caught:
                await service.query_registered_order(
                    tenant_id=7,
                    provider_name="acg",
                    external_order_id="ext-order-1",
                )

        self.assertIs(provider_error, caught.exception.__cause__)

    async def test_context_provider_query_order_errors_are_wrapped_with_cause(self) -> None:
        provider_error = ValueError("bad query payload")
        provider = FakeFailingContextOperationProvider(query_error=provider_error)
        service = ExternalOrderOperationService()

        with patch("app.services.external_sources.orders.get_provider", return_value=provider):
            with self.assertRaisesRegex(ExternalSourceError, "查询订单失败") as caught:
                await service.query_registered_order(
                    tenant_id=7,
                    provider_name="acg",
                    source_key="shop-a",
                    connection_id=11,
                    external_order_id="ext-order-1",
                )

        self.assertIs(provider_error, caught.exception.__cause__)
        self.assertEqual(["query"], [name for name, _ in provider.context_calls])

    async def test_provider_fetch_delivery_errors_are_wrapped_with_cause(self) -> None:
        provider_error = RuntimeError("delivery failed")
        provider = FakeFailingOperationProvider(delivery_error=provider_error)
        service = ExternalOrderOperationService()

        with patch("app.services.external_sources.orders.get_provider", return_value=provider):
            with self.assertRaisesRegex(ExternalSourceError, "获取发货失败") as caught:
                await service.fetch_registered_delivery(
                    tenant_id=7,
                    provider_name="acg",
                    external_order_id="ext-order-1",
                )

        self.assertIs(provider_error, caught.exception.__cause__)

    async def test_context_provider_fetch_delivery_errors_are_wrapped_with_cause(self) -> None:
        provider_error = TimeoutError("delivery timeout")
        provider = FakeFailingContextOperationProvider(delivery_error=provider_error)
        service = ExternalOrderOperationService()

        with patch("app.services.external_sources.orders.get_provider", return_value=provider):
            with self.assertRaisesRegex(ExternalSourceError, "获取发货失败") as caught:
                await service.fetch_registered_delivery(
                    tenant_id=7,
                    provider_name="acg",
                    source_key="shop-a",
                    connection_id=11,
                    external_order_id="ext-order-1",
                )

        self.assertIs(provider_error, caught.exception.__cause__)
        self.assertEqual(["delivery"], [name for name, _ in provider.context_calls])

    async def test_provider_external_source_error_is_preserved(self) -> None:
        provider_error = ExternalSourceError("外部源限流")
        provider = FakeFailingOperationProvider(create_error=provider_error)
        service = ExternalOrderOperationService()

        with patch("app.services.external_sources.orders.get_provider", return_value=provider):
            with self.assertRaisesRegex(ExternalSourceError, "外部源限流") as caught:
                await service.create_registered_order(
                    tenant_id=7,
                    provider_name="acg",
                    request=ExternalOrderRequest(external_product_id="sku-1", quantity=1),
                )

        self.assertIs(provider_error, caught.exception)
        self.assertIsNone(caught.exception.__cause__)

    async def test_create_order_rejects_invalid_provider_order_result(self) -> None:
        service = ExternalOrderOperationService()
        valid = dict(
            provider="acg",
            external_order_id="ext-order-1",
            external_product_id="sku-1",
            status="created",
            quantity=2,
            amount=Decimal("3.00"),
        )
        cases = [
            (ExternalOrder(**{**valid, "provider": None}), "provider"),
            (ExternalOrder(**{**valid, "provider": 123}), "provider"),
            (ExternalOrder(**{**valid, "provider": "ACG"}), "provider"),
            (ExternalOrder(**{**valid, "provider": "other"}), "provider"),
            (ExternalOrder(**{**valid, "external_order_id": None}), "订单 ID"),
            (ExternalOrder(**{**valid, "external_order_id": 123}), "订单 ID"),
            (ExternalOrder(**{**valid, "external_order_id": " "}), "订单 ID"),
            (ExternalOrder(**{**valid, "external_product_id": None}), "商品 ID"),
            (ExternalOrder(**{**valid, "external_product_id": 123}), "商品 ID"),
            (ExternalOrder(**{**valid, "external_product_id": "sku-2"}), "商品 ID"),
            (ExternalOrder(**{**valid, "quantity": None}), "数量"),
            (ExternalOrder(**{**valid, "quantity": "2"}), "数量"),
            (ExternalOrder(**{**valid, "quantity": []}), "数量"),
            (ExternalOrder(**{**valid, "quantity": Decimal("2")}), "数量"),
            (ExternalOrder(**{**valid, "quantity": 2.0}), "数量"),
            (ExternalOrder(**{**valid, "quantity": True}), "数量"),
            (ExternalOrder(**{**valid, "quantity": 1}), "数量"),
            (ExternalOrder(**{**valid, "amount": Decimal("-1.00")}), "金额"),
            (ExternalOrder(**{**valid, "amount": Decimal("NaN")}), "金额"),
            (ExternalOrder(**{**valid, "amount": "3.00"}), "金额"),
            (ExternalOrder(**{**valid, "status": None}), "状态"),
            (ExternalOrder(**{**valid, "status": []}), "状态"),
            (ExternalOrder(**{**valid, "status": " "}), "状态"),
            (ExternalOrder(**{**valid, "currency": None}), "币种"),
            (ExternalOrder(**{**valid, "currency": []}), "币种"),
            (ExternalOrder(**{**valid, "currency": " "}), "币种"),
            (ExternalOrder(**{**valid, "delivery_ready": "yes"}), "发货状态"),
            (ExternalOrder(**{**valid, "raw_payload": []}), "原始载荷"),
            (ExternalOrder(**{**valid, "raw_payload": {"api_key": "secret"}}), "敏感字段"),
            (ExternalOrder(**{**valid, "raw_payload": {"data": [{"accessToken": "secret"}]}}), "敏感字段"),
            (ExternalOrder(**{**valid, "raw_payload": {"meta": {"secret_key": "secret"}}}), "敏感字段"),
            (ExternalOrder(**{**valid, "raw_payload": {"headers": [{"Cookie": "a=b"}]}}), "敏感字段"),
            (None, "订单结果无效"),
        ]

        for order, pattern in cases:
            with self.subTest(pattern=pattern):
                provider = FakeOrderResultProvider(order=order)
                with patch("app.services.external_sources.orders.get_provider", return_value=provider):
                    with self.assertRaisesRegex(ExternalSourceError, pattern):
                        await service.create_registered_order(
                            tenant_id=7,
                            provider_name="acg",
                            request=ExternalOrderRequest(external_product_id="sku-1", quantity=2),
                        )

    async def test_query_order_rejects_mismatched_provider_order_identity(self) -> None:
        provider = FakeOrderResultProvider(
            order=ExternalOrder(
                provider="acg",
                external_order_id="ext-order-2",
                external_product_id="sku-1",
                status="created",
                quantity=1,
                amount=Decimal("3.00"),
            )
        )
        service = ExternalOrderOperationService()

        with patch("app.services.external_sources.orders.get_provider", return_value=provider):
            with self.assertRaisesRegex(ExternalSourceError, "订单 ID 不匹配"):
                await service.query_registered_order(
                    tenant_id=7,
                    provider_name="acg",
                    external_order_id="ext-order-1",
                )

    async def test_provider_order_and_delivery_results_are_normalized(self) -> None:
        provider = FakeOrderResultProvider(
            order=ExternalOrder(
                provider=" acg ",
                external_order_id=" ext-order-1 ",
                external_product_id=" sku-1 ",
                status=" delivered ",
                quantity=1,
                amount=Decimal("3.00"),
                currency=" USDT ",
                delivery_ready=True,
                raw_payload={"result": {"order_id": "ext-order-1"}},
            ),
            delivery=ExternalDelivery(
                provider=" acg ",
                external_order_id=" ext-order-1 ",
                delivery_type=" card_pool ",
                items=[" card-1 ", " card-2 "],
                message=" 已发货 ",
                raw_payload={"result": {"order_id": "ext-order-1"}},
            ),
        )
        service = ExternalOrderOperationService()

        with patch("app.services.external_sources.orders.get_provider", return_value=provider):
            order = await service.query_registered_order(
                tenant_id=7,
                provider_name="acg",
                external_order_id="ext-order-1",
            )
            delivery = await service.fetch_registered_delivery(
                tenant_id=7,
                provider_name="acg",
                external_order_id="ext-order-1",
            )

        self.assertIsNotNone(order)
        self.assertEqual("acg", order.provider)
        self.assertEqual("ext-order-1", order.external_order_id)
        self.assertEqual("sku-1", order.external_product_id)
        self.assertEqual("delivered", order.status)
        self.assertEqual("USDT", order.currency)
        self.assertTrue(order.delivery_ready)
        self.assertIsNotNone(delivery)
        self.assertEqual("acg", delivery.provider)
        self.assertEqual("ext-order-1", delivery.external_order_id)
        self.assertEqual("card_pool", delivery.delivery_type)
        self.assertEqual(("card-1", "card-2"), delivery.items)
        self.assertEqual("已发货", delivery.message)

    async def test_fetch_delivery_rejects_invalid_provider_delivery_result(self) -> None:
        service = ExternalOrderOperationService()
        valid = dict(
            provider="acg",
            external_order_id="ext-order-1",
            delivery_type="card_pool",
            items=("card-1",),
        )
        cases = [
            (ExternalDelivery(**{**valid, "provider": None}), "provider"),
            (ExternalDelivery(**{**valid, "provider": 123}), "provider"),
            (ExternalDelivery(**{**valid, "provider": "ACG"}), "provider"),
            (ExternalDelivery(**{**valid, "provider": "other"}), "provider"),
            (ExternalDelivery(**{**valid, "external_order_id": None}), "订单 ID"),
            (ExternalDelivery(**{**valid, "external_order_id": 123}), "订单 ID"),
            (ExternalDelivery(**{**valid, "external_order_id": "ext-order-2"}), "订单 ID"),
            (ExternalDelivery(**{**valid, "delivery_type": None}), "发货类型"),
            (ExternalDelivery(**{**valid, "delivery_type": []}), "发货类型"),
            (ExternalDelivery(**{**valid, "delivery_type": " "}), "发货类型"),
            (ExternalDelivery(**{**valid, "items": (), "message": object()}), "发货消息"),
            (ExternalDelivery(**{**valid, "items": (), "message": ["x"]}), "发货消息"),
            (ExternalDelivery(**{**valid, "items": (), "message": " "}), "发货内容"),
            (ExternalDelivery(**{**valid, "items": (" ",)}), "发货条目"),
            (ExternalDelivery(**{**valid, "items": (object(),)}), "发货条目"),
            (
                ExternalDelivery(**{**valid, "items": tuple(f"card-{index}" for index in range(MAX_EXTERNAL_DELIVERY_ITEMS + 1))}),
                "发货条目过多",
            ),
            (ExternalDelivery(**{**valid, "items": ("x" * (MAX_EXTERNAL_DELIVERY_ITEM_LENGTH + 1),)}), "发货条目过长"),
            (ExternalDelivery(**{**valid, "message": object()}), "发货消息"),
            (ExternalDelivery(**{**valid, "message": "x" * (MAX_EXTERNAL_DELIVERY_MESSAGE_LENGTH + 1)}), "发货消息过长"),
            (ExternalDelivery(**{**valid, "raw_payload": []}), "原始载荷"),
            (ExternalDelivery(**{**valid, "raw_payload": {"headers": {"Authorization": "Bearer token"}}}), "敏感字段"),
            (ExternalDelivery(**{**valid, "raw_payload": {"data": {"plain-key": "secret"}}}), "敏感字段"),
        ]

        for delivery, pattern in cases:
            with self.subTest(pattern=pattern):
                provider = FakeOrderResultProvider(delivery=delivery)
                with patch("app.services.external_sources.orders.get_provider", return_value=provider):
                    with self.assertRaisesRegex(ExternalSourceError, pattern):
                        await service.fetch_registered_delivery(
                            tenant_id=7,
                            provider_name="acg",
                            external_order_id="ext-order-1",
                        )

    async def test_query_order_and_fetch_delivery_allow_none_results(self) -> None:
        provider = FakeOrderResultProvider(order=None, delivery=None)
        service = ExternalOrderOperationService()

        with patch("app.services.external_sources.orders.get_provider", return_value=provider):
            queried = await service.query_registered_order(
                tenant_id=7,
                provider_name="acg",
                external_order_id="ext-order-1",
            )
            delivery = await service.fetch_registered_delivery(
                tenant_id=7,
                provider_name="acg",
                external_order_id="ext-order-1",
            )

        self.assertIsNone(queried)
        self.assertIsNone(delivery)

    async def test_provider_raw_payload_allows_non_sensitive_fields(self) -> None:
        provider = FakeOrderResultProvider(
            order=ExternalOrder(
                provider="acg",
                external_order_id="ext-order-1",
                external_product_id="sku-1",
                status="created",
                quantity=1,
                amount=Decimal("3.00"),
                raw_payload={"result": {"order_id": "ext-order-1", "status": "ok"}},
            ),
            delivery=ExternalDelivery(
                provider="acg",
                external_order_id="ext-order-1",
                delivery_type="card_pool",
                items=("card-1",),
                raw_payload={"result": {"order_id": "ext-order-1", "status": "ok"}},
            ),
        )
        service = ExternalOrderOperationService()

        with patch("app.services.external_sources.orders.get_provider", return_value=provider):
            order = await service.query_registered_order(
                tenant_id=7,
                provider_name="acg",
                external_order_id="ext-order-1",
            )
            delivery = await service.fetch_registered_delivery(
                tenant_id=7,
                provider_name="acg",
                external_order_id="ext-order-1",
            )

        self.assertIsNotNone(order)
        self.assertIsNotNone(delivery)


if __name__ == "__main__":
    unittest.main()
