from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy.exc import IntegrityError

try:
    from app.config import Settings
    from app.db.models.orders import DeliveryRecord, Payment, PaymentCallback
    from app.services.payments.base import PaymentCallbackResult
    from app.services.payments.epay_compatible import EPAY_COMPATIBLE_PROVIDER, LEMZF_PROVIDER
    from app.services.payments.service import PaymentService, ResolvedPaymentProvider
    from app.services.payments.token188 import TOKEN188_PROVIDER
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过支付回调服务测试：{exc.name}") from exc


class _ScalarResult:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object | None:
        return self._value


class _FakeSession:
    def __init__(self, *scalars: object | None, flush_errors: list[Exception] | None = None) -> None:
        self._scalars = list(scalars)
        self.added: list[object] = []
        self.flush_errors = flush_errors or []
        self.flush_count = 0

    async def execute(self, query: object) -> _ScalarResult:
        if not self._scalars:
            raise AssertionError("未预期的 session.execute 调用")
        return _ScalarResult(self._scalars.pop(0))

    def begin_nested(self) -> "_NestedTransaction":
        return _NestedTransaction(self)

    def add(self, item: object) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        self.flush_count += 1
        if self.flush_errors:
            raise self.flush_errors.pop(0)


class _NestedTransaction:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session
        self.added_count = 0

    async def __aenter__(self) -> "_NestedTransaction":
        self.added_count = len(self.session.added)
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is not None:
            self.session.added = self.session.added[: self.added_count]


class _FakeProvider:
    def __init__(self, result: PaymentCallbackResult, provider: str = "epusdt_gmpay") -> None:
        self.provider = provider
        self._result = result
        self.verify_count = 0

    def verify_callback(self, payload: dict[str, object]) -> PaymentCallbackResult:
        self.verify_count += 1
        return self._result


class _TestPaymentService(PaymentService):
    def __init__(
        self,
        provider: _FakeProvider,
        *,
        callback: PaymentCallback | SimpleNamespace | None = None,
        payment: object | None = None,
        delivery_record_id: int | None = 88,
        find_delivery_record_id: int | None = 88,
        callback_results: list[PaymentCallback | SimpleNamespace | None] | None = None,
    ) -> None:
        super().__init__(Settings())
        self.provider = provider
        self.callback = callback
        self.callback_results = list(callback_results) if callback_results is not None else None
        self.payment = payment
        self.delivery_record_id = delivery_record_id
        self.find_delivery_record_id = find_delivery_record_id
        self.backfill_count = 0
        self.ensure_delivery_count = 0
        self.settlement_count = 0
        self.get_callback_count = 0

    async def _resolve_epusdt_provider(self, session: object, order: object) -> ResolvedPaymentProvider | None:
        return ResolvedPaymentProvider(scope_type="tenant", provider=self.provider)

    async def _resolve_payment_provider(
        self,
        session: object,
        order: object,
        provider_name: str | None = None,
    ) -> ResolvedPaymentProvider | None:
        return ResolvedPaymentProvider(scope_type="tenant", provider=self.provider)

    async def _get_callback(
        self,
        session: object,
        provider: str,
        callback_payload_hash: str,
    ) -> PaymentCallback | SimpleNamespace | None:
        self.get_callback_count += 1
        if self.callback_results is not None:
            if not self.callback_results:
                raise AssertionError("未预期的 _get_callback 调用")
            return self.callback_results.pop(0)
        return self.callback

    async def _get_payment(
        self,
        session: object,
        order_id: int,
        provider: str,
        for_update: bool = False,
    ) -> object | None:
        return self.payment

    async def _record_platform_settlement_if_needed(self, session: object, order: object) -> None:
        self.settlement_count += 1
        return None

    async def _ensure_delivery_record(self, session: object, order: object) -> int | None:
        self.ensure_delivery_count += 1
        return self.delivery_record_id

    async def _backfill_settlement_for_processed_callback(
        self,
        session: object,
        out_trade_no: str,
        scope_type: str,
    ) -> None:
        self.backfill_count += 1

    async def _find_deliverable_record_id(self, session: object, out_trade_no: str) -> int | None:
        return self.find_delivery_record_id


class _SubscriptionPaymentService(PaymentService):
    def __init__(
        self,
        provider: _FakeProvider,
        *,
        find_delivery_record_id: int | None = None,
    ) -> None:
        super().__init__(Settings())
        self.provider = provider
        self.find_delivery_record_id = find_delivery_record_id

    async def _resolve_epusdt_provider(self, session: object, order: object) -> ResolvedPaymentProvider | None:
        return ResolvedPaymentProvider(scope_type="platform", provider=self.provider)

    async def _resolve_payment_provider(
        self,
        session: object,
        order: object,
        provider_name: str | None = None,
    ) -> ResolvedPaymentProvider | None:
        return ResolvedPaymentProvider(scope_type="platform", provider=self.provider)

    async def _find_deliverable_record_id(self, session: object, out_trade_no: str) -> int | None:
        return self.find_delivery_record_id


class PaymentCallbackServiceTest(unittest.TestCase):
    def test_paid_callback_creates_payment_callback_and_delivery_once(self) -> None:
        order = _pending_order()
        verified = _verified_callback(paid=True)
        provider = _FakeProvider(verified)
        service = _TestPaymentService(provider, delivery_record_id=99)
        session = _FakeSession(order, order)

        result = asyncio.run(service.process_epusdt_callback(session, {"order_id": order.out_trade_no}))

        self.assertTrue(result.ok)
        self.assertEqual("processed", result.message)
        self.assertEqual(99, result.delivery_record_id)
        self.assertEqual("paid", order.status)
        self.assertEqual("epusdt_gmpay", order.payment_provider)
        self.assertEqual("tenant_direct", order.payment_mode)
        self.assertEqual(1, service.ensure_delivery_count)
        self.assertEqual(1, provider.verify_count)
        self.assertEqual(2, session.flush_count)
        self.assertEqual(2, len(session.added))
        self.assertIsInstance(session.added[0], PaymentCallback)
        self.assertEqual("processed", session.added[0].process_status)
        self.assertIsInstance(session.added[1], Payment)
        self.assertEqual("paid", session.added[1].status)

    def test_generic_offline_provider_paid_callback_updates_order_payment_and_delivery(self) -> None:
        for provider_name, payload in [
            (TOKEN188_PROVIDER, {"orderNo": "ORD123"}),
            (EPAY_COMPATIBLE_PROVIDER, {"out_trade_no": "ORD123"}),
            (LEMZF_PROVIDER, {"out_trade_no": "ORD123"}),
        ]:
            with self.subTest(provider=provider_name):
                order = _pending_order()
                verified = _verified_callback(paid=True, provider=provider_name)
                provider = _FakeProvider(verified, provider=provider_name)
                service = _TestPaymentService(provider, delivery_record_id=99)
                session = _FakeSession(order, order)

                result = asyncio.run(service.process_payment_callback(session, provider_name, payload))

                self.assertTrue(result.ok)
                self.assertEqual("processed", result.message)
                self.assertEqual(99, result.delivery_record_id)
                self.assertEqual("paid", order.status)
                self.assertEqual(provider_name, order.payment_provider)
                self.assertEqual("tenant_direct", order.payment_mode)
                self.assertEqual(1, provider.verify_count)
                callbacks = [item for item in session.added if isinstance(item, PaymentCallback)]
                payments = [item for item in session.added if isinstance(item, Payment)]
                self.assertEqual(1, len(callbacks))
                self.assertEqual(provider_name, callbacks[0].provider)
                self.assertEqual(f"hash-{provider_name}", callbacks[0].payload_hash)
                self.assertEqual("processed", callbacks[0].process_status)
                self.assertEqual(1, len(payments))
                self.assertEqual(provider_name, payments[0].provider)
                self.assertEqual(f"{provider_name}:ORD123", payments[0].idempotency_key)
                self.assertEqual("paid", payments[0].status)

    def test_existing_pending_self_order_callback_after_suspension_still_fulfills_existing_order(self) -> None:
        order = _pending_order()
        verified = _verified_callback(paid=True)
        provider = _FakeProvider(verified)
        payment = SimpleNamespace(status="pending", provider_trade_no=None, paid_at=None)
        service = _TestPaymentService(provider, payment=payment, delivery_record_id=99)
        session = _FakeSession(order, order)

        result = asyncio.run(service.process_epusdt_callback(session, {"order_id": order.out_trade_no}))

        self.assertTrue(result.ok)
        self.assertEqual("processed", result.message)
        self.assertEqual(99, result.delivery_record_id)
        self.assertEqual("paid", order.status)
        self.assertEqual("epusdt_gmpay", order.payment_provider)
        self.assertEqual("tenant_direct", order.payment_mode)
        self.assertIsNotNone(order.paid_at)
        self.assertEqual("paid", payment.status)
        self.assertEqual("TRADE123", payment.provider_trade_no)
        self.assertIsNotNone(payment.paid_at)
        self.assertEqual(1, service.ensure_delivery_count)
        self.assertEqual(1, provider.verify_count)
        self.assertEqual(2, session.flush_count)
        callbacks = [item for item in session.added if isinstance(item, PaymentCallback)]
        payments = [item for item in session.added if isinstance(item, Payment)]
        self.assertEqual(1, len(callbacks))
        self.assertEqual("processed", callbacks[0].process_status)
        self.assertEqual([], payments)

    def test_paid_callback_without_immediate_delivery_is_processed_for_async_fulfillment(self) -> None:
        order = _pending_order()
        verified = _verified_callback(paid=True)
        provider = _FakeProvider(verified)
        service = _TestPaymentService(provider, delivery_record_id=None, find_delivery_record_id=None)
        session = _FakeSession(order, order)

        result = asyncio.run(service.process_epusdt_callback(session, {"order_id": order.out_trade_no}))

        self.assertTrue(result.ok)
        self.assertEqual("processed", result.message)
        self.assertIsNone(result.delivery_record_id)
        self.assertEqual("paid", order.status)
        self.assertEqual("epusdt_gmpay", order.payment_provider)
        self.assertEqual("tenant_direct", order.payment_mode)
        self.assertEqual(1, service.ensure_delivery_count)
        self.assertEqual(2, session.flush_count)
        callbacks = [item for item in session.added if isinstance(item, PaymentCallback)]
        self.assertEqual(1, len(callbacks))
        self.assertEqual("processed", callbacks[0].process_status)
        self.assertIsNone(callbacks[0].error_message)

    def test_processed_callback_is_duplicate_and_does_not_create_delivery_again(self) -> None:
        order = _pending_order()
        verified = _verified_callback(paid=True)
        provider = _FakeProvider(verified)
        callback = SimpleNamespace(process_status="processed")
        service = _TestPaymentService(provider, callback=callback, delivery_record_id=77, find_delivery_record_id=77)
        session = _FakeSession(order, order)

        result = asyncio.run(service.process_epusdt_callback(session, {"order_id": order.out_trade_no}))

        self.assertTrue(result.ok)
        self.assertEqual("duplicate", result.message)
        self.assertEqual(77, result.delivery_record_id)
        self.assertEqual(1, service.backfill_count)
        self.assertEqual(0, service.ensure_delivery_count)
        self.assertEqual(0, service.settlement_count)
        self.assertEqual([], session.added)
        self.assertEqual(0, session.flush_count)

    def test_callback_insert_integrity_error_rechecks_processed_callback_as_duplicate(self) -> None:
        order = _pending_order()
        verified = _verified_callback(paid=True)
        provider = _FakeProvider(verified)
        processed_callback = SimpleNamespace(process_status="processed")
        service = _TestPaymentService(
            provider,
            callback_results=[None, processed_callback],
            delivery_record_id=77,
            find_delivery_record_id=77,
        )
        session = _FakeSession(
            order,
            order,
            flush_errors=[IntegrityError("insert payment_callbacks", {}, Exception("duplicate payload"))],
        )

        result = asyncio.run(service.process_epusdt_callback(session, {"order_id": order.out_trade_no}))

        self.assertTrue(result.ok)
        self.assertEqual("duplicate", result.message)
        self.assertEqual(77, result.delivery_record_id)
        self.assertEqual("pending", order.status)
        self.assertEqual(1, provider.verify_count)
        self.assertEqual(2, service.get_callback_count)
        self.assertEqual(1, service.backfill_count)
        self.assertEqual(0, service.ensure_delivery_count)
        self.assertEqual(0, service.settlement_count)
        self.assertEqual([], session.added)
        self.assertEqual(1, session.flush_count)

    def test_same_order_different_payload_hash_after_paid_is_duplicate_without_delivery(self) -> None:
        order = _pending_order()
        order.status = "paid"
        order.payment_provider = "epusdt_gmpay"
        order.paid_at = datetime.now(timezone.utc)
        verified = _verified_callback(paid=True)
        verified.payload_hash = "new-hash"
        provider = _FakeProvider(verified)
        payment = SimpleNamespace(status="paid")
        service = _TestPaymentService(provider, payment=payment, delivery_record_id=66, find_delivery_record_id=66)
        session = _FakeSession(order, order)

        result = asyncio.run(service.process_epusdt_callback(session, {"order_id": order.out_trade_no}))

        self.assertTrue(result.ok)
        self.assertEqual("duplicate", result.message)
        self.assertEqual(66, result.delivery_record_id)
        self.assertEqual("paid", order.status)
        self.assertEqual("tenant_direct", order.payment_mode)
        self.assertEqual(0, service.ensure_delivery_count)
        self.assertEqual(0, service.settlement_count)
        self.assertEqual(1, len(session.added))
        self.assertIsInstance(session.added[0], PaymentCallback)
        self.assertEqual("epusdt_gmpay", session.added[0].provider)
        self.assertEqual("ORD123", session.added[0].out_trade_no)
        self.assertEqual("new-hash", session.added[0].payload_hash)
        self.assertEqual("processed", session.added[0].process_status)
        self.assertIsNone(session.added[0].error_message)
        self.assertIsNotNone(session.added[0].processed_at)

    def test_pending_order_with_paid_payment_different_hash_is_duplicate_without_inventory_use(self) -> None:
        order = _pending_order()
        verified = _verified_callback(paid=True)
        verified.payload_hash = "new-hash"
        provider = _FakeProvider(verified)
        payment = SimpleNamespace(status="paid", paid_at=datetime.now(timezone.utc))
        service = _TestPaymentService(provider, payment=payment, delivery_record_id=66, find_delivery_record_id=66)
        session = _FakeSession(order, order)

        with patch("app.services.payments.service.InventoryService") as inventory_service:
            result = asyncio.run(service.process_epusdt_callback(session, {"order_id": order.out_trade_no}))

        self.assertTrue(result.ok)
        self.assertEqual("duplicate", result.message)
        self.assertEqual("paid", order.status)
        self.assertEqual("epusdt_gmpay", order.payment_provider)
        self.assertEqual("tenant_direct", order.payment_mode)
        self.assertEqual(0, service.ensure_delivery_count)
        self.assertEqual(0, service.settlement_count)
        inventory_service.assert_not_called()
        self.assertEqual(1, len(session.added))
        self.assertIsInstance(session.added[0], PaymentCallback)
        self.assertEqual("processed", session.added[0].process_status)

    def test_paid_order_without_delivery_record_retries_delivery_once(self) -> None:
        order = _pending_order()
        order.status = "paid"
        order.payment_provider = "epusdt_gmpay"
        order.paid_at = datetime.now(timezone.utc)
        verified = _verified_callback(paid=True)
        verified.payload_hash = "new-hash"
        provider = _FakeProvider(verified)
        payment = SimpleNamespace(status="paid", paid_at=order.paid_at)
        service = _TestPaymentService(
            provider,
            payment=payment,
            delivery_record_id=55,
            find_delivery_record_id=None,
        )
        session = _FakeSession(order, order)

        result = asyncio.run(service.process_epusdt_callback(session, {"order_id": order.out_trade_no}))

        self.assertTrue(result.ok)
        self.assertEqual("processed", result.message)
        self.assertEqual(55, result.delivery_record_id)
        self.assertEqual(1, service.settlement_count)
        self.assertEqual(1, service.ensure_delivery_count)
        self.assertEqual(1, len(session.added))
        self.assertIsInstance(session.added[0], PaymentCallback)
        self.assertEqual("processed", session.added[0].process_status)

    def test_expired_pending_order_callback_releases_inventory_and_does_not_deliver(self) -> None:
        order = _pending_order(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        verified = _verified_callback(paid=True)
        provider = _FakeProvider(verified)
        service = _TestPaymentService(provider, delivery_record_id=99)
        session = _FakeSession(order, order)
        release_locks = AsyncMock()

        with patch("app.services.payments.service.InventoryService") as inventory_service:
            inventory_service.return_value.release_order_locks = release_locks
            result = asyncio.run(service.process_epusdt_callback(session, {"order_id": order.out_trade_no}))

        self.assertFalse(result.ok)
        self.assertEqual("order_expired", result.message)
        self.assertEqual("expired", order.status)
        self.assertIsNone(order.locked_inventory_item_id)
        self.assertEqual(0, service.ensure_delivery_count)
        self.assertEqual(1, release_locks.await_count)
        self.assertEqual((session, 7, 12), release_locks.await_args.args)
        self.assertEqual(1, len(session.added))
        self.assertIsInstance(session.added[0], PaymentCallback)
        self.assertEqual("failed", session.added[0].process_status)
        self.assertEqual("订单已过期或不可支付", session.added[0].error_message)

    def test_subscription_paid_callback_applies_subscription_without_delivery_record(self) -> None:
        order = _pending_order(source_type="subscription")
        verified = _verified_callback(paid=True)
        provider = _FakeProvider(verified)
        service = _SubscriptionPaymentService(provider)
        session = _FakeSession(order, order, None, None)

        async def apply_subscription(session_arg: object, order_arg: object) -> None:
            self.assertIs(session, session_arg)
            self.assertIs(order, order_arg)
            order_arg.status = "completed"
            order_arg.delivered_at = datetime.now(timezone.utc)

        with patch(
            "app.services.subscriptions.SubscriptionService.apply_paid_order",
            new=AsyncMock(side_effect=apply_subscription),
        ) as apply_paid_order:
            result = asyncio.run(service.process_epusdt_callback(session, {"order_id": order.out_trade_no}))

        callbacks = [item for item in session.added if isinstance(item, PaymentCallback)]
        payments = [item for item in session.added if isinstance(item, Payment)]
        deliveries = [item for item in session.added if isinstance(item, DeliveryRecord)]
        self.assertTrue(result.ok)
        self.assertEqual("processed", result.message)
        self.assertIsNone(result.delivery_record_id)
        apply_paid_order.assert_awaited_once_with(session, order)
        self.assertEqual("completed", order.status)
        self.assertEqual("epusdt_gmpay", order.payment_provider)
        self.assertEqual("platform_escrow", order.payment_mode)
        self.assertIsNotNone(order.paid_at)
        self.assertIsNotNone(order.delivered_at)
        self.assertEqual([], deliveries)
        self.assertEqual(1, len(callbacks))
        self.assertEqual("processed", callbacks[0].process_status)
        self.assertIsNone(callbacks[0].error_message)
        self.assertIsNotNone(callbacks[0].processed_at)
        self.assertEqual(1, len(payments))
        self.assertEqual(order.id, payments[0].order_id)
        self.assertEqual(order.tenant_id, payments[0].tenant_id)
        self.assertEqual("paid", payments[0].status)
        self.assertEqual("TRADE123", payments[0].provider_trade_no)
        self.assertEqual(order.amount, payments[0].amount)
        self.assertEqual(order.currency, payments[0].currency)
        self.assertIsNotNone(payments[0].paid_at)

    def test_subscription_already_paid_callback_still_applies_subscription(self) -> None:
        order = _pending_order(source_type="subscription")
        paid_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        verified = _verified_callback(paid=True)
        verified.payload_hash = "new-subscription-hash"
        provider = _FakeProvider(verified)
        payment = SimpleNamespace(status="paid", paid_at=paid_at)
        service = _SubscriptionPaymentService(provider, find_delivery_record_id=None)
        session = _FakeSession(order, order, None, payment)

        async def apply_subscription(session_arg: object, order_arg: object) -> None:
            self.assertIs(session, session_arg)
            self.assertIs(order, order_arg)
            order_arg.status = "completed"
            order_arg.delivered_at = datetime.now(timezone.utc)

        with patch(
            "app.services.subscriptions.SubscriptionService.apply_paid_order",
            new=AsyncMock(side_effect=apply_subscription),
        ) as apply_paid_order:
            result = asyncio.run(service.process_epusdt_callback(session, {"order_id": order.out_trade_no}))

        callbacks = [item for item in session.added if isinstance(item, PaymentCallback)]
        payments = [item for item in session.added if isinstance(item, Payment)]
        deliveries = [item for item in session.added if isinstance(item, DeliveryRecord)]
        self.assertTrue(result.ok)
        self.assertEqual("processed", result.message)
        self.assertIsNone(result.delivery_record_id)
        apply_paid_order.assert_awaited_once_with(session, order)
        self.assertEqual("completed", order.status)
        self.assertEqual("epusdt_gmpay", order.payment_provider)
        self.assertEqual("platform_escrow", order.payment_mode)
        self.assertEqual(paid_at, order.paid_at)
        self.assertIsNotNone(order.delivered_at)
        self.assertEqual(1, len(callbacks))
        self.assertEqual("processed", callbacks[0].process_status)
        self.assertIsNone(callbacks[0].error_message)
        self.assertEqual([], payments)
        self.assertEqual([], deliveries)


def _pending_order(
    expires_at: datetime | None = None,
    *,
    source_type: str = "self",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=12,
        tenant_id=7,
        buyer_telegram_user_id=42,
        source_type=source_type,
        self_product_id=3 if source_type == "self" else None,
        subscription_months=1 if source_type == "subscription" else None,
        locked_inventory_item_id=5 if source_type == "self" else None,
        supplier_tenant_id=None,
        amount=Decimal("10.00"),
        currency="USDT",
        payment_mode="pending_payment",
        payment_provider=None,
        status="pending",
        out_trade_no="ORD123",
        expires_at=expires_at or datetime.now(timezone.utc) + timedelta(minutes=10),
        paid_at=None,
        delivered_at=None,
    )


def _verified_callback(*, paid: bool, provider: str = "epusdt_gmpay") -> PaymentCallbackResult:
    return PaymentCallbackResult(
        provider=provider,
        out_trade_no="ORD123",
        provider_trade_no="TRADE123",
        paid=paid,
        payload_hash="hash-123" if provider == "epusdt_gmpay" else f"hash-{provider}",
        raw_payload={"order_id": "ORD123", "status": "paid" if paid else "pending"},
    )


if __name__ == "__main__":
    unittest.main()
