from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

try:
    from app.config import Settings
    from app.services.payments.base import PaymentQueryResult
    from app.services.payments.service import PaymentService, ResolvedPaymentProvider
    from app.workers.payment_reconcile import reconcile_pending_payments_once
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过支付对账服务测试：{exc.name}") from exc


class _RowsResult:
    def __init__(self, rows: list[tuple[object, object]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[object, object]]:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[tuple[object, object]] | None = None) -> None:
        self.rows = rows or []
        self.flush_count = 0
        self.commit_count = 0

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    async def execute(self, query: object) -> _RowsResult:
        return _RowsResult(self.rows)

    async def flush(self) -> None:
        self.flush_count += 1

    async def commit(self) -> None:
        self.commit_count += 1


def _session_factory(session: _FakeSession):
    def factory() -> _FakeSession:
        return session

    return factory


class _FakeProvider:
    provider = "epusdt_gmpay"

    def __init__(self, results: dict[str, PaymentQueryResult]) -> None:
        self.results = results
        self.queried_trade_numbers: list[str] = []

    async def query_order(self, provider_trade_no: str) -> PaymentQueryResult:
        self.queried_trade_numbers.append(provider_trade_no)
        return self.results[provider_trade_no]


class _TestPaymentService(PaymentService):
    def __init__(self, provider: _FakeProvider, *, delivery_record_id: int | None = 66) -> None:
        super().__init__(Settings())
        self.provider = provider
        self.delivery_record_id = delivery_record_id
        self.settlement_count = 0
        self.ensure_delivery_count = 0
        self.settled_order_ids: list[int] = []
        self.ensured_order_ids: list[int] = []

    async def _resolve_epusdt_provider(self, session: object, order: object) -> ResolvedPaymentProvider | None:
        return ResolvedPaymentProvider(scope_type="tenant", provider=self.provider)

    async def _record_platform_settlement_if_needed(self, session: object, order: object) -> None:
        self.settlement_count += 1
        self.settled_order_ids.append(order.id)

    async def _ensure_delivery_record(self, session: object, order: object) -> int | None:
        self.ensure_delivery_count += 1
        self.ensured_order_ids.append(order.id)
        return self.delivery_record_id


class PaymentReconcileServiceTest(unittest.TestCase):
    def test_reconcile_paid_and_expired_pending_payments(self) -> None:
        paid_payment = _payment(order_id=1, tenant_id=7, provider_trade_no="TRADE_PAID")
        paid_order = _order(order_id=1, tenant_id=7, locked_inventory_item_id=11)
        expired_payment = _payment(order_id=2, tenant_id=8, provider_trade_no="TRADE_EXPIRED")
        expired_order = _order(order_id=2, tenant_id=8, locked_inventory_item_id=12)
        provider = _FakeProvider(
            {
                "TRADE_PAID": _query_result(
                    provider_trade_no="TRADE_PAID",
                    paid=True,
                    expired=False,
                    status="paid",
                ),
                "TRADE_EXPIRED": _query_result(
                    provider_trade_no="TRADE_EXPIRED",
                    paid=False,
                    expired=True,
                    status="expired",
                ),
            }
        )
        service = _TestPaymentService(provider)
        session = _FakeSession([(paid_payment, paid_order), (expired_payment, expired_order)])
        release_locks = AsyncMock()

        with patch("app.services.payments.service.InventoryService") as inventory_service:
            inventory_service.return_value.release_order_locks = release_locks
            result = asyncio.run(service.reconcile_pending_payments(session, limit=10))

        self.assertEqual(2, result.checked_count)
        self.assertEqual(2, result.changed_count)
        self.assertEqual([66], result.delivery_record_ids)
        self.assertEqual(["TRADE_PAID", "TRADE_EXPIRED"], provider.queried_trade_numbers)
        self.assertEqual("paid", paid_payment.status)
        self.assertIsNotNone(paid_payment.paid_at)
        self.assertEqual("paid", paid_order.status)
        self.assertEqual("epusdt_gmpay", paid_order.payment_provider)
        self.assertEqual("tenant_direct", paid_order.payment_mode)
        self.assertIsNotNone(paid_order.paid_at)
        self.assertEqual(1, service.settlement_count)
        self.assertEqual(1, service.ensure_delivery_count)
        self.assertEqual([1], service.settled_order_ids)
        self.assertEqual([1], service.ensured_order_ids)
        self.assertEqual("expired", expired_payment.status)
        self.assertEqual("expired", expired_order.status)
        self.assertIsNone(expired_order.locked_inventory_item_id)
        self.assertEqual(1, release_locks.await_count)
        self.assertEqual((session, 8, 2), release_locks.await_args.args)
        self.assertEqual(1, session.flush_count)

    def test_reconcile_expired_reseller_payment_releases_supplier_inventory(self) -> None:
        payment = _payment(order_id=3, tenant_id=8, provider_trade_no="TRADE_RESELLER_EXPIRED")
        order = _order(
            order_id=3,
            tenant_id=8,
            locked_inventory_item_id=12,
            source_type="reseller",
            supplier_tenant_id=99,
        )
        provider = _FakeProvider(
            {
                "TRADE_RESELLER_EXPIRED": _query_result(
                    provider_trade_no="TRADE_RESELLER_EXPIRED",
                    paid=False,
                    expired=True,
                    status="expired",
                ),
            }
        )
        service = _TestPaymentService(provider)
        session = _FakeSession([(payment, order)])
        release_locks = AsyncMock()

        with patch("app.services.payments.service.InventoryService") as inventory_service:
            inventory_service.return_value.release_order_locks = release_locks
            result = asyncio.run(service.reconcile_pending_payments(session, limit=10))

        self.assertEqual(1, result.checked_count)
        self.assertEqual(1, result.changed_count)
        self.assertEqual("expired", payment.status)
        self.assertEqual("expired", order.status)
        self.assertIsNone(order.locked_inventory_item_id)
        self.assertEqual((session, 99, 3), release_locks.await_args.args)
        self.assertEqual([], service.settled_order_ids)
        self.assertEqual([], service.ensured_order_ids)

    def test_reconcile_paid_external_payment_allows_async_fulfillment_without_delivery_id(self) -> None:
        payment = _payment(order_id=4, tenant_id=7, provider_trade_no="TRADE_EXTERNAL_PAID")
        order = _order(order_id=4, tenant_id=7, locked_inventory_item_id=None)
        provider = _FakeProvider(
            {
                "TRADE_EXTERNAL_PAID": _query_result(
                    provider_trade_no="TRADE_EXTERNAL_PAID",
                    paid=True,
                    expired=False,
                    status="paid",
                ),
            }
        )
        service = _TestPaymentService(provider, delivery_record_id=None)
        session = _FakeSession([(payment, order)])

        result = asyncio.run(service.reconcile_pending_payments(session, limit=10))

        self.assertEqual(1, result.checked_count)
        self.assertEqual(1, result.changed_count)
        self.assertEqual([], result.delivery_record_ids)
        self.assertEqual("paid", payment.status)
        self.assertEqual("paid", order.status)
        self.assertEqual("epusdt_gmpay", order.payment_provider)
        self.assertEqual("tenant_direct", order.payment_mode)
        self.assertEqual(1, service.settlement_count)
        self.assertEqual([4], service.ensured_order_ids)
        self.assertEqual(1, session.flush_count)

    def test_payment_reconcile_worker_commits_and_returns_changed_count(self) -> None:
        settings = Settings()
        session = _FakeSession([])
        reconcile = AsyncMock(return_value=SimpleNamespace(changed_count=5))

        with patch("app.workers.payment_reconcile.PaymentService") as payment_service:
            payment_service.return_value.reconcile_pending_payments = reconcile
            changed_count = asyncio.run(reconcile_pending_payments_once(settings, _session_factory(session), limit=77))

        self.assertEqual(5, changed_count)
        payment_service.assert_called_once_with(settings)
        self.assertEqual(1, reconcile.await_count)
        self.assertEqual(session, reconcile.await_args.args[0])
        self.assertEqual(77, reconcile.await_args.kwargs["limit"])
        self.assertEqual(1, session.commit_count)


def _payment(*, order_id: int, tenant_id: int, provider_trade_no: str) -> SimpleNamespace:
    return SimpleNamespace(
        order_id=order_id,
        tenant_id=tenant_id,
        provider="epusdt_gmpay",
        provider_trade_no=provider_trade_no,
        status="pending",
        paid_at=None,
    )


def _order(
    *,
    order_id: int,
    tenant_id: int,
    locked_inventory_item_id: int | None,
    source_type: str = "self",
    supplier_tenant_id: int | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=order_id,
        tenant_id=tenant_id,
        source_type=source_type,
        supplier_tenant_id=supplier_tenant_id,
        status="pending",
        payment_provider=None,
        payment_mode="pending_payment",
        paid_at=None,
        locked_inventory_item_id=locked_inventory_item_id,
    )


def _query_result(*, provider_trade_no: str, paid: bool, expired: bool, status: str) -> PaymentQueryResult:
    return PaymentQueryResult(
        provider="epusdt_gmpay",
        provider_trade_no=provider_trade_no,
        paid=paid,
        expired=expired,
        status=status,
        raw_response={"status": status},
    )


if __name__ == "__main__":
    unittest.main()
