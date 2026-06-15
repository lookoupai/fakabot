from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

try:
    from app.db.models.tenants import AuditLog
    from app.services.payments.failures import (
        PAYMENT_CALLBACK_REJECTION_ACTION,
        PaymentCallbackRejectionAuditService,
    )
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过支付回调拒绝审计测试：{exc.name}") from exc


class _ScalarResult:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object | None:
        return self._value


class _RowsResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class _RecordSession:
    def __init__(self, order: object | None) -> None:
        self.order = order
        self.added: list[object] = []
        self.flush_count = 0

    async def execute(self, query: object) -> _ScalarResult:
        return _ScalarResult(self.order)

    def add(self, item: object) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        self.flush_count += 1


class _ListSession:
    def __init__(self, logs: list[object]) -> None:
        self.logs = logs

    async def execute(self, query: object) -> _RowsResult:
        return _RowsResult(self.logs)


class PaymentCallbackRejectionAuditServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_record_rejection_writes_tenant_audit_without_payload_or_secret(self) -> None:
        order = SimpleNamespace(id=55, tenant_id=7, status="pending", out_trade_no="ORD123")
        session = _RecordSession(order)
        service = PaymentCallbackRejectionAuditService()

        await service.record_rejection(
            session,
            provider_name="token188",
            payload={
                "orderNo": "ORD123",
                "key": "plain-secret",
                "sign": "secret-signature",
                "provider_trade_no": "UPSTREAM-SECRET",
            },
            reason_category="invalid_callback",
            http_status=400,
        )

        self.assertEqual(1, session.flush_count)
        self.assertEqual(1, len(session.added))
        audit = session.added[0]
        self.assertIsInstance(audit, AuditLog)
        self.assertEqual(7, audit.tenant_id)
        self.assertIsNone(audit.actor_user_id)
        self.assertEqual(PAYMENT_CALLBACK_REJECTION_ACTION, audit.action)
        self.assertEqual("order", audit.target_type)
        self.assertEqual("55", audit.target_id)
        self.assertEqual("token188", audit.metadata_json["provider"])
        self.assertEqual("invalid_callback", audit.metadata_json["reason_category"])
        self.assertEqual("支付回调参数无效", audit.metadata_json["failure_reason"])
        self.assertEqual(400, audit.metadata_json["http_status"])
        self.assertEqual("ORD123", audit.metadata_json["out_trade_no"])
        self.assertEqual(55, audit.metadata_json["order_id"])
        self.assertEqual("pending", audit.metadata_json["order_status"])
        self.assertEqual(4, audit.metadata_json["payload_field_count"])
        self.assertNotIn("key", audit.metadata_json)
        self.assertNotIn("sign", audit.metadata_json)
        self.assertNotIn("provider_trade_no", audit.metadata_json)
        self.assertNotIn("plain-secret", repr(audit.metadata_json))
        self.assertNotIn("secret-signature", repr(audit.metadata_json))
        self.assertNotIn("UPSTREAM-SECRET", repr(audit.metadata_json))

    async def test_record_rejection_without_order_keeps_platform_scoped_safe_audit(self) -> None:
        session = _RecordSession(order=None)
        service = PaymentCallbackRejectionAuditService()

        await service.record_rejection(
            session,
            provider_name="unknown_provider",
            payload={"out_trade_no": "ORD404", "secret_key": "plain-secret"},
            reason_category="payment_unavailable",
            http_status=503,
        )

        audit = session.added[0]
        self.assertIsNone(audit.tenant_id)
        self.assertEqual("payment_callback", audit.target_type)
        self.assertEqual("ORD404", audit.target_id)
        self.assertEqual("unknown_provider", audit.metadata_json["provider"])
        self.assertEqual("payment_unavailable", audit.metadata_json["reason_category"])
        self.assertEqual("支付配置暂不可用", audit.metadata_json["failure_reason"])
        self.assertEqual("ORD404", audit.metadata_json["out_trade_no"])
        self.assertNotIn("secret_key", audit.metadata_json)
        self.assertNotIn("plain-secret", repr(audit.metadata_json))

    async def test_record_payload_malformed_rejection_without_payload_keeps_zero_field_count(self) -> None:
        session = _RecordSession(order=None)
        service = PaymentCallbackRejectionAuditService()

        await service.record_rejection(
            session,
            provider_name="token188",
            payload=None,
            reason_category="payload_malformed",
            http_status=413,
        )

        audit = session.added[0]
        self.assertIsNone(audit.tenant_id)
        self.assertEqual("payment_callback", audit.target_type)
        self.assertEqual("token188", audit.target_id)
        self.assertEqual("token188", audit.metadata_json["provider"])
        self.assertEqual("payload_malformed", audit.metadata_json["reason_category"])
        self.assertEqual("支付回调 payload 无法解析", audit.metadata_json["failure_reason"])
        self.assertEqual(413, audit.metadata_json["http_status"])
        self.assertEqual(0, audit.metadata_json["payload_field_count"])
        self.assertNotIn("out_trade_no", audit.metadata_json)
        self.assertNotIn("payload", audit.metadata_json)

    async def test_list_rejections_returns_tenant_scoped_safe_summaries(self) -> None:
        now = datetime.now(timezone.utc)
        logs = [
            _audit_log(
                audit_log_id=1,
                tenant_id=7,
                provider="token188",
                reason_category="invalid_callback",
                out_trade_no="ORD123",
                now=now,
            ),
            _audit_log(
                audit_log_id=2,
                tenant_id=8,
                provider="token188",
                reason_category="invalid_callback",
                out_trade_no="ORD999",
                now=now,
            ),
            _audit_log(
                audit_log_id=3,
                tenant_id=7,
                provider="lemzf",
                reason_category="payload_malformed",
                out_trade_no="ORD456",
                now=now,
            ),
        ]
        service = PaymentCallbackRejectionAuditService()

        rejections = await service.list_rejections(
            _ListSession(logs),
            tenant_id=7,
            provider="token188",
            reason_category="invalid_callback",
            out_trade_no="ORD123",
            limit=20,
        )

        self.assertEqual(1, len(rejections))
        rejection = rejections[0]
        self.assertEqual(1, rejection.audit_log_id)
        self.assertEqual("token188", rejection.provider)
        self.assertEqual("invalid_callback", rejection.reason_category)
        self.assertEqual("支付回调参数无效", rejection.failure_reason)
        self.assertEqual(400, rejection.http_status)
        self.assertEqual("ORD123", rejection.out_trade_no)
        self.assertEqual(55, rejection.order_id)
        self.assertEqual("pending", rejection.order_status)
        self.assertEqual(3, rejection.payload_field_count)
        self.assertNotIn("plain-secret", repr(rejection))
        self.assertNotIn("payload_json", repr(rejection))
        self.assertNotIn("provider_trade_no", repr(rejection))

    async def test_list_rejections_rejects_invalid_filters_before_response(self) -> None:
        service = PaymentCallbackRejectionAuditService()
        session = _ListSession([])

        with self.assertRaisesRegex(ValueError, "reason_category"):
            await service.list_rejections(session, tenant_id=7, reason_category="secret=plain-secret")
        with self.assertRaisesRegex(ValueError, "支付 provider"):
            await service.list_rejections(session, tenant_id=7, provider="unknown")
        with self.assertRaisesRegex(ValueError, "out_trade_no"):
            await service.list_rejections(session, tenant_id=7, out_trade_no="A" * 97)
        with self.assertRaisesRegex(ValueError, "limit"):
            await service.list_rejections(session, tenant_id=7, limit=True)


def _audit_log(
    *,
    audit_log_id: int,
    tenant_id: int,
    provider: str,
    reason_category: str,
    out_trade_no: str,
    now: datetime,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=audit_log_id,
        tenant_id=tenant_id,
        actor_user_id=None,
        action=PAYMENT_CALLBACK_REJECTION_ACTION,
        target_type="order",
        target_id="55",
        created_at=now,
        metadata_json={
            "provider": provider,
            "reason_category": reason_category,
            "failure_reason": "支付回调参数无效",
            "http_status": 400,
            "out_trade_no": out_trade_no,
            "order_id": 55,
            "order_status": "pending",
            "payload_field_count": 3,
            "payload_json": {"secret_key": "plain-secret"},
            "provider_trade_no": "UPSTREAM-SECRET",
        },
    )


if __name__ == "__main__":
    unittest.main()
