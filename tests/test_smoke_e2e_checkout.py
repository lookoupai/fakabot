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
    from app.services.orders import OrderService
    from app.services.payments.base import PaymentCallbackResult
    from app.services.payments.service import PaymentService, ResolvedPaymentProvider
    from app.services.token_crypto import TokenCrypto
    from app.workers.delivery_dispatch import dispatch_pending_deliveries_once
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过离线端到端 smoke 测试：{exc.name}") from exc


class _QueuedResult:
    def __init__(self, value: object | None = None, *, values: list[object] | None = None) -> None:
        self._value = value
        self._values = values

    def scalar_one_or_none(self) -> object | None:
        return self._value

    def scalars(self) -> "_QueuedResult":
        return self

    def all(self) -> list[object]:
        return list(self._values or [])


class _NestedTransaction:
    def __init__(self, session: "_SmokeSession") -> None:
        self._session = session
        self._added_count = 0

    async def __aenter__(self) -> "_NestedTransaction":
        self._added_count = len(self._session.added)
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is not None:
            self._session.added = self._session.added[: self._added_count]


class _SmokeSession:
    def __init__(self, *, tenant: object, product: object, variant: object, inventory_item: object) -> None:
        self.tenant = tenant
        self.product = product
        self.variant = variant
        self.inventory_item = inventory_item
        self.order: Order | None = None
        self.payment_callback: PaymentCallback | None = None
        self.payment: Payment | None = None
        self.delivery_record: DeliveryRecord | None = None
        self.added: list[object] = []
        self.execute_results: list[_QueuedResult] = []
        self.commit_count = 0
        self.flush_count = 0
        self._ids = {
            Order: 1001,
            PaymentCallback: 2001,
            Payment: 3001,
            DeliveryRecord: 4001,
        }

    async def __aenter__(self) -> "_SmokeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def queue_scalars(self, *values: object | None) -> None:
        self.execute_results.extend(_QueuedResult(value) for value in values)

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
        if model is InventoryItem and getattr(self.inventory_item, "id", None) == item_id:
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
        self.verify_count = 0

    def verify_callback(self, payload: dict[str, object]) -> PaymentCallbackResult:
        self.verify_count += 1
        return self._result


class _SmokePaymentService(PaymentService):
    def __init__(self, settings: Settings, provider: _FakeProvider) -> None:
        super().__init__(settings)
        self.provider = provider

    async def _resolve_epusdt_provider(self, session: object, order: object) -> ResolvedPaymentProvider | None:
        return ResolvedPaymentProvider(scope_type="tenant", provider=self.provider)

    async def _backfill_settlement_for_processed_callback(
        self,
        session: object,
        out_trade_no: str,
        scope_type: str,
    ) -> None:
        return None

    async def _find_deliverable_record_id(self, session: object, out_trade_no: str) -> int | None:
        delivery = getattr(session, "delivery_record", None)
        if delivery is not None and delivery.status in {"pending", "failed"}:
            return int(delivery.id)
        return None


class OfflineCheckoutE2ESmokeTest(unittest.TestCase):
    def test_self_card_order_payment_callback_delivery_and_duplicate_callback(self) -> None:
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
            external_source=None,
            source_key="",
            external_id=None,
        )
        variant = SimpleNamespace(id=201, status="on", price=Decimal("12.50"), currency="USDT")
        inventory_item = SimpleNamespace(
            id=501,
            tenant_id=7,
            content_encrypted=crypto.encrypt_token("CARD-SECRET-1"),
        )
        session = _SmokeSession(
            tenant=tenant,
            product=product,
            variant=variant,
            inventory_item=inventory_item,
        )
        session.queue_scalar_list([])

        with patch("app.services.orders.ProductRepository") as product_repo, patch(
            "app.services.orders.InventoryService"
        ) as order_inventory_service, patch("app.services.orders.RiskControlService") as risk_service:
            product_repo.return_value.get_product_with_default_variant = AsyncMock(return_value=(product, variant))
            order_inventory_service.return_value.lock_one_available_item = AsyncMock(
                return_value=SimpleNamespace(inventory_item_id=inventory_item.id)
            )
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

        self.assertEqual(1001, created.order_id)
        self.assertEqual(inventory_item.id, created.locked_inventory_item_id)
        assert session.order is not None
        self.assertEqual("pending", session.order.status)
        self.assertEqual(inventory_item.id, session.order.locked_inventory_item_id)

        verified = PaymentCallbackResult(
            provider="epusdt_gmpay",
            out_trade_no=session.order.out_trade_no,
            provider_trade_no="TRADE123",
            paid=True,
            payload_hash="payload-hash-1",
            raw_payload={"order_id": session.order.out_trade_no, "status": "paid"},
        )
        provider = _FakeProvider(verified)
        payment_service = _SmokePaymentService(settings, provider)
        session.queue_scalars(session.order, session.order, None, None, None)

        with patch("app.services.payments.service.InventoryService") as payment_inventory_service:
            payment_inventory_service.return_value.mark_locked_item_used = AsyncMock(return_value=True)
            result = asyncio.run(
                payment_service.process_epusdt_callback(
                    session,
                    {"order_id": session.order.out_trade_no},
                )
            )

        self.assertTrue(result.ok)
        self.assertEqual("processed", result.message)
        self.assertEqual(session.delivery_record.id, result.delivery_record_id)
        self.assertEqual("paid", session.order.status)
        self.assertIsNotNone(session.payment)
        self.assertEqual("paid", session.payment.status)
        self.assertIsNotNone(session.payment_callback)
        self.assertEqual("processed", session.payment_callback.process_status)
        self.assertEqual("pending", session.delivery_record.status)
        payment_inventory_service.return_value.mark_locked_item_used.assert_awaited_once()

        encrypted_bot_token = crypto.encrypt_token("123456:tenant-bot-token")
        session.queue_scalar_list([])
        session.queue_scalar_list([session.delivery_record.id])
        session.queue_scalars(session.delivery_record)
        bot = SimpleNamespace(session=SimpleNamespace(close=AsyncMock()))
        with patch("app.workers.delivery_dispatch.TenantRepository") as tenant_repo, patch(
            "app.workers.delivery_dispatch.create_bot",
            return_value=bot,
        ) as create_bot, patch(
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
        create_bot.assert_called_once_with("123456:tenant-bot-token")
        send_delivery.assert_awaited_once()
        self.assertEqual("sent", session.delivery_record.status)
        self.assertEqual("delivered", session.order.status)
        self.assertIsNotNone(session.order.delivered_at)

        session.queue_scalars(session.order, session.order, session.payment_callback)
        duplicate = asyncio.run(
            payment_service.process_epusdt_callback(
                session,
                {"order_id": session.order.out_trade_no},
            )
        )

        self.assertTrue(duplicate.ok)
        self.assertEqual("duplicate", duplicate.message)
        self.assertIsNone(duplicate.delivery_record_id)
        self.assertEqual(2, provider.verify_count)
        self.assertEqual(1, len([item for item in session.added if isinstance(item, DeliveryRecord)]))
        self.assertEqual("sent", session.delivery_record.status)


def _session_factory(session: _SmokeSession):
    def factory() -> _SmokeSession:
        return session

    return factory


if __name__ == "__main__":
    unittest.main()
