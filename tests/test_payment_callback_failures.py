from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

try:
    from app.services.payments.failures import PaymentCallbackFailureLogService
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过支付回调失败观测服务测试：{exc.name}") from exc


class _RowsResult:
    def __init__(self, rows: list[tuple[object, object]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[object, object]]:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[tuple[object, object]]) -> None:
        self.rows = rows

    async def execute(self, query: object) -> _RowsResult:
        return _RowsResult(self.rows)


class PaymentCallbackFailureLogServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_list_failures_returns_tenant_scoped_safe_summaries(self) -> None:
        now = datetime.now(timezone.utc)
        rows = [
            (
                _callback(
                    callback_id=1,
                    provider="token188",
                    process_status="failed",
                    error_message="订单已过期或不可支付",
                    now=now,
                ),
                _order(order_id=10, tenant_id=7, out_trade_no="ORD123", status="expired"),
            ),
            (
                _callback(
                    callback_id=2,
                    provider="token188",
                    process_status="failed",
                    error_message="secret=plain-secret",
                    now=now,
                ),
                _order(order_id=11, tenant_id=8, out_trade_no="ORD999", status="pending"),
            ),
        ]
        service = PaymentCallbackFailureLogService()

        failures = await service.list_failures(
            _FakeSession(rows),
            tenant_id=7,
            provider="token188",
            process_status="failed",
            limit=20,
        )

        self.assertEqual(1, len(failures))
        failure = failures[0]
        self.assertEqual(1, failure.callback_id)
        self.assertEqual(10, failure.order_id)
        self.assertEqual("ORD123", failure.out_trade_no)
        self.assertEqual("expired", failure.order_status)
        self.assertEqual("token188", failure.provider)
        self.assertEqual("failed", failure.process_status)
        self.assertEqual("订单已过期或不可支付", failure.failure_reason)
        self.assertNotIn("payload_json", repr(failure))
        self.assertNotIn("provider_trade_no", repr(failure))

    async def test_list_failures_supports_ignored_status_and_out_trade_no_filter(self) -> None:
        now = datetime.now(timezone.utc)
        rows = [
            (
                _callback(callback_id=1, provider="epay_compatible", process_status="ignored", now=now),
                _order(order_id=10, tenant_id=7, out_trade_no="ORD123", status="pending"),
            ),
            (
                _callback(callback_id=2, provider="epay_compatible", process_status="failed", now=now),
                _order(order_id=11, tenant_id=7, out_trade_no="ORD456", status="pending"),
            ),
        ]
        service = PaymentCallbackFailureLogService()

        failures = await service.list_failures(
            _FakeSession(rows),
            tenant_id=7,
            provider="epay_compatible",
            process_status="ignored",
            out_trade_no="ORD123",
            limit=20,
        )

        self.assertEqual(1, len(failures))
        self.assertEqual("ignored", failures[0].process_status)
        self.assertEqual("ORD123", failures[0].out_trade_no)
        self.assertEqual("支付回调未处理成功", failures[0].failure_reason)

    async def test_list_failures_rejects_invalid_filters_before_response(self) -> None:
        service = PaymentCallbackFailureLogService()
        session = _FakeSession([])

        with self.assertRaisesRegex(ValueError, "process_status"):
            await service.list_failures(session, tenant_id=7, process_status="processed")
        with self.assertRaisesRegex(ValueError, "支付 provider"):
            await service.list_failures(session, tenant_id=7, provider="unknown")
        with self.assertRaisesRegex(ValueError, "out_trade_no"):
            await service.list_failures(session, tenant_id=7, out_trade_no="A" * 97)
        with self.assertRaisesRegex(ValueError, "limit"):
            await service.list_failures(session, tenant_id=7, limit=True)

    async def test_list_failures_redacts_sensitive_error_message(self) -> None:
        now = datetime.now(timezone.utc)
        rows = [
            (
                _callback(
                    callback_id=1,
                    provider="lemzf",
                    process_status="failed",
                    error_message="signature signing_text contains plain-secret",
                    now=now,
                ),
                _order(order_id=10, tenant_id=7, out_trade_no="ORD123", status="pending"),
            )
        ]
        service = PaymentCallbackFailureLogService()

        failures = await service.list_failures(_FakeSession(rows), tenant_id=7, provider="lemzf")

        self.assertEqual("支付回调未处理成功", failures[0].failure_reason)
        self.assertNotIn("plain-secret", repr(failures[0]))
        self.assertNotIn("signing_text", repr(failures[0]))


def _callback(
    *,
    callback_id: int,
    provider: str,
    process_status: str,
    now: datetime,
    error_message: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=callback_id,
        provider=provider,
        out_trade_no="ORD123",
        process_status=process_status,
        error_message=error_message,
        created_at=now,
        processed_at=now,
        payload_json={"secret_key": "plain-secret"},
        payload_hash="hash-secret",
        provider_trade_no="UPSTREAM-SECRET",
    )


def _order(*, order_id: int, tenant_id: int, out_trade_no: str, status: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=order_id,
        tenant_id=tenant_id,
        out_trade_no=out_trade_no,
        status=status,
    )


if __name__ == "__main__":
    unittest.main()
