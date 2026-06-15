from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest

try:
    from app.services.order_diagnostics import OrderDiagnosticsService
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过订单排障摘要服务测试：{exc.name}") from exc


class _ScalarList:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return self._values


class _Result:
    def __init__(self, *, scalar: object | None = None, values: list[object] | None = None) -> None:
        self._scalar = scalar
        self._values = values or []

    def scalar_one_or_none(self) -> object | None:
        return self._scalar

    def scalars(self) -> _ScalarList:
        return _ScalarList(self._values)


class _FakeSession:
    def __init__(self, results: list[_Result]) -> None:
        self.results = list(results)
        self.executed_queries: list[object] = []

    async def execute(self, query: object) -> _Result:
        self.executed_queries.append(query)
        if not self.results:
            raise AssertionError("未预期的 session.execute 调用")
        return self.results.pop(0)


class OrderDiagnosticsServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_get_summary_returns_safe_payment_callback_delivery_and_external_mapping(self) -> None:
        now = datetime.now(timezone.utc)
        session = _FakeSession(
            [
                _Result(scalar=_order(now=now)),
                _Result(values=[_payment(now=now)]),
                _Result(values=[_callback(now=now, error_message="signature signing_text plain-secret")]),
                _Result(scalar=_delivery(now=now, error_message="token=plain-secret")),
                _Result(scalar=_product()),
                _Result(scalar=2),
                _Result(scalar=_attempt(now=now)),
            ]
        )
        service = OrderDiagnosticsService()

        summary = await service.get_summary(session, tenant_id=7, out_trade_no=" ORD123 ")

        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(55, summary.order_id)
        self.assertEqual("ORD123", summary.out_trade_no)
        self.assertEqual("paid", summary.status)
        self.assertEqual("tenant_direct", summary.payment_mode)
        self.assertEqual("token188", summary.payment_provider)
        self.assertEqual(1, summary.payment_count)
        self.assertEqual(1, summary.callback_count)
        self.assertEqual({"failed": 1}, summary.callback_status_counts)
        self.assertEqual(1, len(summary.payments))
        payment = summary.payments[0]
        self.assertEqual(91, payment.payment_id)
        self.assertEqual("token188", payment.provider)
        self.assertEqual("paid", payment.status)
        self.assertTrue(payment.has_payment_url)
        self.assertNotIn("https://pay.example", repr(payment))
        self.assertNotIn("provider_trade_no", repr(payment))
        self.assertEqual(1, len(summary.callbacks))
        callback = summary.callbacks[0]
        self.assertEqual(81, callback.callback_id)
        self.assertEqual("支付回调未处理成功", callback.failure_reason)
        self.assertNotIn("plain-secret", repr(callback))
        self.assertNotIn("signing_text", repr(callback))
        self.assertIsNotNone(summary.delivery)
        assert summary.delivery is not None
        self.assertEqual(71, summary.delivery.delivery_record_id)
        self.assertEqual("未记录失败原因", summary.delivery.failure_reason)
        self.assertTrue(summary.delivery.has_inventory_item)
        self.assertTrue(summary.delivery.has_uploaded_file)
        self.assertTrue(summary.delivery.has_telegram_chat)
        self.assertNotIn("telegram_chat_id", repr(summary.delivery))
        self.assertTrue(summary.external_fulfillment.expected)
        self.assertEqual(2, summary.external_fulfillment.attempt_count)
        self.assertEqual("failed", summary.external_fulfillment.latest_attempt_status)
        self.assertEqual("manual", summary.external_fulfillment.latest_attempt_source)
        self.assertEqual(now, summary.external_fulfillment.latest_attempt_at)
        self.assertEqual("fetch_delivery", summary.external_fulfillment.latest_failure_stage)
        self.assertEqual("upstream_error", summary.external_fulfillment.latest_failure_category)
        self.assertTrue(summary.external_fulfillment.latest_failure_retryable)
        self.assertEqual(503, summary.external_fulfillment.latest_upstream_status_code)
        self.assertEqual(2, summary.external_fulfillment.latest_item_count)
        self.assertTrue(summary.external_fulfillment.latest_delivery_record_linked)
        self.assertNotIn("standard_http", repr(summary.external_fulfillment))
        self.assertNotIn("sku-1", repr(summary.external_fulfillment))
        self.assertNotIn("EXT-SECRET", repr(summary.external_fulfillment))
        self.assertNotIn("connection_id", repr(summary.external_fulfillment))
        self.assertNotIn("delivery_record_id", repr(summary.external_fulfillment))
        self.assertNotIn("supplier_tenant_id", repr(summary))
        self.assertNotIn("locked_inventory_item_id", repr(summary))
        self.assertEqual(7, len(session.executed_queries))
        attempt_count_query = str(session.executed_queries[-2])
        latest_attempt_query = str(session.executed_queries[-1])
        self.assertIn("external_fulfillment_attempts.tenant_id", attempt_count_query)
        self.assertIn("external_fulfillment_attempts.order_id", attempt_count_query)
        self.assertIn("external_fulfillment_attempts.tenant_id", latest_attempt_query)
        self.assertIn("external_fulfillment_attempts.order_id", latest_attempt_query)

    async def test_get_summary_returns_none_for_missing_or_cross_tenant_order(self) -> None:
        session = _FakeSession([_Result(scalar=None)])
        service = OrderDiagnosticsService()

        summary = await service.get_summary(session, tenant_id=7, out_trade_no="ORD404")

        self.assertIsNone(summary)
        self.assertEqual(1, len(session.executed_queries))

    async def test_get_summary_rejects_invalid_out_trade_no_before_query(self) -> None:
        session = _FakeSession([])
        service = OrderDiagnosticsService()

        with self.assertRaisesRegex(ValueError, "out_trade_no"):
            await service.get_summary(session, tenant_id=7, out_trade_no="A" * 97)

        self.assertEqual([], session.executed_queries)

    async def test_get_summary_does_not_query_product_for_reseller_order(self) -> None:
        now = datetime.now(timezone.utc)
        order = _order(now=now)
        order.source_type = "reseller"
        order.self_product_id = None
        order.supplier_tenant_id = 99
        session = _FakeSession(
            [
                _Result(scalar=order),
                _Result(values=[]),
                _Result(values=[]),
                _Result(scalar=None),
            ]
        )
        service = OrderDiagnosticsService()

        summary = await service.get_summary(session, tenant_id=7, out_trade_no="ORD123")

        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertFalse(summary.external_fulfillment.expected)
        self.assertEqual(4, len(session.executed_queries))
        self.assertNotIn("supplier_tenant_id", repr(summary))

    async def test_get_summary_returns_external_fulfillment_attempt_overview_without_sensitive_identifiers(
        self,
    ) -> None:
        now = datetime.now(timezone.utc)
        session = _FakeSession(
            [
                _Result(scalar=_order(now=now)),
                _Result(values=[]),
                _Result(values=[]),
                _Result(scalar=None),
                _Result(scalar=_product()),
                _Result(scalar=1),
                _Result(scalar=_attempt(now=now)),
            ]
        )
        service = OrderDiagnosticsService()

        summary = await service.get_summary(session, tenant_id=7, out_trade_no="ORD123")

        self.assertIsNotNone(summary)
        assert summary is not None
        external = summary.external_fulfillment
        self.assertTrue(external.expected)
        self.assertEqual(1, external.attempt_count)
        self.assertEqual("failed", external.latest_attempt_status)
        self.assertEqual("manual", external.latest_attempt_source)
        self.assertEqual(now, external.latest_attempt_at)
        self.assertEqual("fetch_delivery", external.latest_failure_stage)
        self.assertEqual("upstream_error", external.latest_failure_category)
        self.assertTrue(external.latest_failure_retryable)
        self.assertEqual(503, external.latest_upstream_status_code)
        self.assertEqual(2, external.latest_item_count)
        self.assertTrue(external.latest_delivery_record_linked)
        self.assertNotIn("standard_http", repr(external))
        self.assertNotIn("sku-1", repr(external))
        self.assertNotIn("EXT-SECRET", repr(external))
        self.assertNotIn("connection_id", repr(external))
        self.assertNotIn("delivery_record_id", repr(external))
        self.assertNotIn("failure_reason", repr(external))
        self.assertNotIn("failure_fingerprint", repr(external))

    async def test_get_summary_returns_external_attempt_zero_count_without_latest_fields(self) -> None:
        now = datetime.now(timezone.utc)
        session = _FakeSession(
            [
                _Result(scalar=_order(now=now)),
                _Result(values=[]),
                _Result(values=[]),
                _Result(scalar=None),
                _Result(scalar=_product()),
                _Result(scalar=0),
            ]
        )
        service = OrderDiagnosticsService()

        summary = await service.get_summary(session, tenant_id=7, out_trade_no="ORD123")

        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertTrue(summary.external_fulfillment.expected)
        self.assertEqual(0, summary.external_fulfillment.attempt_count)
        self.assertIsNone(summary.external_fulfillment.latest_attempt_status)
        self.assertIsNone(summary.external_fulfillment.latest_attempt_source)
        self.assertIsNone(summary.external_fulfillment.latest_attempt_at)
        self.assertEqual(0, summary.external_fulfillment.latest_item_count)
        self.assertFalse(summary.external_fulfillment.latest_delivery_record_linked)
        self.assertEqual(6, len(session.executed_queries))


def _order(*, now: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        id=55,
        tenant_id=7,
        buyer_telegram_user_id=42,
        source_type="self",
        self_product_id=101,
        supplier_tenant_id=None,
        amount=Decimal("10.00"),
        currency="USDT",
        status="paid",
        payment_mode="tenant_direct",
        payment_provider="token188",
        out_trade_no="ORD123",
        locked_inventory_item_id=501,
        created_at=now,
        expires_at=now + timedelta(minutes=30),
        paid_at=now,
        delivered_at=None,
    )


def _payment(*, now: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        id=91,
        order_id=55,
        tenant_id=7,
        provider="token188",
        provider_trade_no="UPSTREAM-SECRET",
        amount=Decimal("10.00"),
        currency="USDT",
        status="paid",
        payment_url="https://pay.example/checkout?token=plain-secret",
        raw_request_hash="raw-hash",
        idempotency_key="token188:ORD123",
        created_at=now,
        paid_at=now,
    )


def _callback(*, now: datetime, error_message: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=81,
        provider="token188",
        out_trade_no="ORD123",
        provider_trade_no="UPSTREAM-SECRET",
        payload_hash="payload-hash",
        payload_json={"secret_key": "plain-secret"},
        process_status="failed",
        error_message=error_message,
        created_at=now,
        processed_at=now,
    )


def _delivery(*, now: datetime, error_message: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=71,
        order_id=55,
        tenant_id=7,
        buyer_telegram_user_id=42,
        delivery_type="card_pool",
        inventory_item_id=501,
        uploaded_file_id=601,
        telegram_chat_id=-100123,
        status="failed",
        error_message=error_message,
        created_at=now,
        updated_at=now,
        sent_at=None,
    )


def _product() -> SimpleNamespace:
    return SimpleNamespace(
        id=101,
        tenant_id=7,
        external_source="standard_http",
        source_key="main",
        external_id="sku-1",
        storage_key="private.zip",
        telegram_chat_id=-100123,
    )


def _attempt(*, now: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        id=301,
        tenant_id=7,
        order_id=55,
        product_id=101,
        connection_id=44,
        delivery_record_id=88,
        out_trade_no="ORD123",
        provider_name="standard_http",
        source_key="main",
        external_product_id="sku-1",
        external_order_id="EXT-SECRET",
        attempt_source="manual",
        status="failed",
        imported=False,
        item_count=2,
        failure_reason="Authorization token plain-secret raw_payload card_secret",
        failure_stage="fetch_delivery",
        failure_category="upstream_error",
        failure_retryable=True,
        upstream_status_code=503,
        failure_fingerprint="f" * 64,
        created_at=now,
        started_at=now,
        finished_at=now,
    )


if __name__ == "__main__":
    unittest.main()
