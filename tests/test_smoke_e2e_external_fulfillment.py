from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

try:
    from cryptography.fernet import Fernet
    from pydantic import SecretStr

    from app.config import Settings
    from app.db.models.orders import DeliveryRecord, Order, Payment, PaymentCallback
    from app.db.models.products import InventoryItem, Product
    from app.db.models.tenants import Tenant
    from app.services.external_sources.auto_fulfillment import ExternalAutoFulfillmentService
    from app.services.external_sources.base import ExternalDelivery, ExternalOrder
    from app.services.external_sources.fulfillment import ExternalDeliveryImportService
    from app.services.orders import OrderService
    from app.services.payments.base import PaymentCallbackResult
    from app.services.payments.service import PaymentService, ResolvedPaymentProvider
    from app.services.token_crypto import TokenCrypto
    from app.workers.delivery_dispatch import dispatch_pending_deliveries_once
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过外部履约端到端 smoke 测试：{exc.name}") from exc


class _QueuedResult:
    def __init__(
        self,
        value: object | None = None,
        *,
        rows: list[tuple[object, object]] | None = None,
        values: list[object] | None = None,
    ) -> None:
        self._value = value
        self._rows = rows
        self._values = values

    def scalar_one_or_none(self) -> object | None:
        return self._value

    def all(self) -> list[tuple[object, object]] | list[object]:
        if self._rows is not None:
            return list(self._rows)
        return list(self._values or [])

    def scalars(self) -> "_QueuedResult":
        return self


class _NestedTransaction:
    def __init__(self, session: "_ExternalSmokeSession") -> None:
        self._session = session
        self._added_count = 0

    async def __aenter__(self) -> "_NestedTransaction":
        self._added_count = len(self._session.added)
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is not None:
            self._session.added = self._session.added[: self._added_count]


class _ExternalSmokeSession:
    def __init__(self, *, tenant: object, product: object, variant: object) -> None:
        self.tenant = tenant
        self.product = product
        self.variant = variant
        self.order: Order | None = None
        self.payment_callback: PaymentCallback | None = None
        self.payment: Payment | None = None
        self.inventory_item: InventoryItem | None = None
        self.delivery_record: DeliveryRecord | None = None
        self.added: list[object] = []
        self.execute_results: list[_QueuedResult] = []
        self.commit_count = 0
        self.flush_count = 0
        self._ids = {
            Order: 1001,
            PaymentCallback: 2001,
            Payment: 3001,
            InventoryItem: 4001,
            DeliveryRecord: 5001,
        }

    async def __aenter__(self) -> "_ExternalSmokeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def queue_scalars(self, *values: object | None) -> None:
        self.execute_results.extend(_QueuedResult(value) for value in values)

    def queue_rows(self, rows: list[tuple[object, object]]) -> None:
        self.execute_results.append(_QueuedResult(rows=rows))

    def queue_scalar_list(self, values: list[object]) -> None:
        self.execute_results.append(_QueuedResult(values=values))

    async def execute(self, query: object) -> _QueuedResult:
        if not self.execute_results:
            raise AssertionError("未预期的 session.execute 调用")
        return self.execute_results.pop(0)

    async def get(self, model: object, item_id: int) -> object | None:
        if model is Tenant and getattr(self.tenant, "id", None) == item_id:
            return self.tenant
        if model is Product and getattr(self.product, "id", None) == item_id:
            return self.product
        if model is Order and self.order is not None and self.order.id == item_id:
            return self.order
        if model is InventoryItem and self.inventory_item is not None and self.inventory_item.id == item_id:
            return self.inventory_item
        if model is DeliveryRecord and self.delivery_record is not None and self.delivery_record.id == item_id:
            return self.delivery_record
        return None

    def begin_nested(self) -> _NestedTransaction:
        return _NestedTransaction(self)

    def add(self, item: object) -> None:
        model = type(item)
        if model in self._ids and getattr(item, "id", None) is None:
            setattr(item, "id", self._ids[model])
            self._ids[model] += 1
        if isinstance(item, Order):
            self.order = item
        elif isinstance(item, PaymentCallback):
            self.payment_callback = item
        elif isinstance(item, Payment):
            self.payment = item
        elif isinstance(item, InventoryItem):
            self.inventory_item = item
        elif isinstance(item, DeliveryRecord):
            self.delivery_record = item
        self.added.append(item)

    async def flush(self) -> None:
        self.flush_count += 1

    async def commit(self) -> None:
        self.commit_count += 1


class _FakeProvider:
    provider = "epusdt_gmpay"

    def __init__(self, result: PaymentCallbackResult) -> None:
        self._result = result

    def verify_callback(self, payload: dict[str, object]) -> PaymentCallbackResult:
        return self._result


class _SmokePaymentService(PaymentService):
    def __init__(self, settings: Settings, provider: _FakeProvider) -> None:
        super().__init__(settings)
        self.provider = provider

    async def _resolve_epusdt_provider(self, session: object, order: object) -> ResolvedPaymentProvider | None:
        return ResolvedPaymentProvider(scope_type="tenant", provider=self.provider)


class _ExternalConnectionService:
    def __init__(self, runtime_auth: object) -> None:
        self.runtime_auth = runtime_auth
        self.calls: list[dict[str, object]] = []

    async def load_runtime_credentials_for_source(self, session: object, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.runtime_auth


class _ExternalOperationService:
    def __init__(self) -> None:
        self.create_count = 0
        self.fetch_count = 0

    async def create_registered_order(self, **kwargs: object) -> ExternalOrder:
        self.create_count += 1
        request = kwargs["request"]
        return ExternalOrder(
            provider="acg",
            external_order_id="EXT-ORD-1",
            external_product_id=request.external_product_id,
            status="paid",
            quantity=1,
            amount=Decimal("12.50"),
            currency="USDT",
            delivery_ready=True,
        )

    async def fetch_registered_delivery(self, **kwargs: object) -> ExternalDelivery:
        self.fetch_count += 1
        return ExternalDelivery(
            provider="acg",
            external_order_id="EXT-ORD-1",
            delivery_type="card_pool",
            items=("EXT-CARD-SECRET",),
            message="外部发货",
        )


class ExternalFulfillmentE2ESmokeTest(unittest.TestCase):
    def test_external_mapping_order_paid_async_fulfillment_and_dispatch(self) -> None:
        settings = Settings(token_encryption_key=SecretStr(Fernet.generate_key().decode()))
        crypto = TokenCrypto(settings)
        tenant = SimpleNamespace(id=7, status="active")
        product = SimpleNamespace(
            id=101,
            tenant_id=7,
            status="on",
            delivery_type="card_pool",
            delivery_file_id=None,
            telegram_chat_id=None,
            external_source="acg",
            source_key="main",
            external_id="sku-1",
        )
        variant = SimpleNamespace(id=201, status="on", price=Decimal("12.50"), currency="USDT")
        session = _ExternalSmokeSession(tenant=tenant, product=product, variant=variant)
        session.queue_scalar_list([])

        with patch("app.services.orders.ProductRepository") as product_repo, patch(
            "app.services.orders.InventoryService"
        ) as inventory_service, patch("app.services.orders.RiskControlService") as risk_service:
            product_repo.return_value.get_product_with_default_variant = AsyncMock(return_value=(product, variant))
            risk_service.return_value.ensure_order_creation_allowed = AsyncMock()
            created = asyncio.run(
                OrderService().create_self_order(
                    session=session,
                    tenant_id=7,
                    buyer_telegram_user_id=42,
                    product_id=product.id,
                    order_timeout_minutes=15,
                )
            )

        inventory_service.assert_not_called()
        self.assertIsNone(created.locked_inventory_item_id)
        assert session.order is not None
        self.assertIsNone(session.order.locked_inventory_item_id)

        verified = PaymentCallbackResult(
            provider="epusdt_gmpay",
            out_trade_no=session.order.out_trade_no,
            provider_trade_no="TRADE123",
            paid=True,
            payload_hash="payload-hash-1",
            raw_payload={"order_id": session.order.out_trade_no, "status": "paid"},
        )
        payment_service = _SmokePaymentService(settings, _FakeProvider(verified))
        session.queue_scalars(session.order, session.order, None, None)
        payment_result = asyncio.run(
            payment_service.process_epusdt_callback(
                session,
                {"order_id": session.order.out_trade_no},
            )
        )

        self.assertTrue(payment_result.ok)
        self.assertEqual("processed", payment_result.message)
        self.assertIsNone(payment_result.delivery_record_id)
        self.assertEqual("paid", session.order.status)
        self.assertIsNone(session.delivery_record)

        runtime_auth = SimpleNamespace(connection_id=33, credentials={"api_key": "secret-value"})
        connection_service = _ExternalConnectionService(runtime_auth)
        operation_service = _ExternalOperationService()
        fulfillment_service = ExternalAutoFulfillmentService(
            connection_service=connection_service,
            operation_service=operation_service,
            import_service=ExternalDeliveryImportService(),
        )
        session.queue_rows([(session.order, product)])
        session.queue_scalars(None, session.order, None)

        with patch(
            "app.services.external_sources.auto_fulfillment.is_provider_auto_fulfillment_available",
            return_value=True,
        ):
            fulfillment = asyncio.run(
                fulfillment_service.process_paid_external_orders(
                    session,
                    settings=settings,
                    limit=10,
                )
            )

        self.assertEqual(1, fulfillment.checked_count)
        self.assertEqual(1, fulfillment.imported_count)
        self.assertEqual(0, fulfillment.failed_count)
        self.assertEqual([session.delivery_record.id], fulfillment.delivery_record_ids)
        self.assertEqual(1, operation_service.create_count)
        self.assertEqual(1, operation_service.fetch_count)
        self.assertEqual(1, len(connection_service.calls))
        self.assertIsNotNone(session.inventory_item)
        assert session.inventory_item is not None
        self.assertEqual("used", session.inventory_item.status)
        self.assertEqual(session.order.id, session.inventory_item.used_by_order_id)
        self.assertNotIn("EXT-CARD-SECRET", session.inventory_item.content_encrypted)
        self.assertIn("EXT-CARD-SECRET", crypto.decrypt_token(session.inventory_item.content_encrypted))
        self.assertEqual("pending", session.delivery_record.status)

        session.queue_rows([(session.order, product)])
        session.queue_scalars(session.delivery_record)
        with patch(
            "app.services.external_sources.auto_fulfillment.is_provider_auto_fulfillment_available",
            side_effect=AssertionError("已有发货记录不应再次调用 provider"),
        ):
            replay_fulfillment = asyncio.run(
                fulfillment_service.process_paid_external_orders(
                    session,
                    settings=settings,
                    limit=10,
                )
            )

        self.assertEqual(1, replay_fulfillment.checked_count)
        self.assertEqual(0, replay_fulfillment.imported_count)
        self.assertEqual(0, replay_fulfillment.failed_count)
        self.assertEqual([session.delivery_record.id], replay_fulfillment.delivery_record_ids)
        self.assertEqual(1, operation_service.create_count)
        self.assertEqual(1, operation_service.fetch_count)
        self.assertEqual(1, len(connection_service.calls))
        self.assertEqual(1, len([item for item in session.added if isinstance(item, InventoryItem)]))
        self.assertEqual(1, len([item for item in session.added if isinstance(item, DeliveryRecord)]))

        encrypted_bot_token = crypto.encrypt_token("123456:tenant-bot-token")
        session.queue_scalar_list([])
        session.queue_scalar_list([session.delivery_record.id])
        session.queue_scalars(session.delivery_record)
        bot = SimpleNamespace(session=SimpleNamespace(close=AsyncMock()))
        with patch("app.workers.delivery_dispatch.TenantRepository") as tenant_repo, patch(
            "app.workers.delivery_dispatch.create_bot",
            return_value=bot,
        ), patch(
            "app.workers.delivery_dispatch.send_delivery_instruction",
            new=AsyncMock(),
        ) as send_delivery:
            tenant_repo.return_value.get_active_bot_by_tenant_id = AsyncMock(
                return_value=SimpleNamespace(encrypted_token=encrypted_bot_token)
            )
            sent_count = asyncio.run(
                dispatch_pending_deliveries_once(
                    settings,
                    _session_factory(session),
                    limit=10,
                )
            )

        self.assertEqual(1, sent_count)
        send_delivery.assert_awaited_once()
        self.assertEqual("sent", session.delivery_record.status)
        self.assertEqual("delivered", session.order.status)

        session.queue_rows([])
        with patch(
            "app.services.external_sources.auto_fulfillment.is_provider_auto_fulfillment_available",
            return_value=True,
        ):
            second_fulfillment = asyncio.run(
                fulfillment_service.process_paid_external_orders(
                    session,
                    settings=settings,
                    limit=10,
                )
            )

        self.assertEqual(0, second_fulfillment.checked_count)
        self.assertEqual(1, operation_service.create_count)
        self.assertEqual(1, len([item for item in session.added if isinstance(item, DeliveryRecord)]))


def _session_factory(session: _ExternalSmokeSession):
    def factory() -> _ExternalSmokeSession:
        return session

    return factory


if __name__ == "__main__":
    unittest.main()
