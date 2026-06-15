from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

try:
    from app.services.audit import AuditLogService, PlatformRiskAuditLogSummary
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过审计日志服务测试：{exc.name}") from exc


class _RowsResult:
    def __init__(self, rows: list[tuple[object, object | None]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[object, object | None]]:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[tuple[object, object | None]]) -> None:
        self.rows = rows
        self.executed_queries: list[object] = []

    async def execute(self, query: object) -> _RowsResult:
        self.executed_queries.append(query)
        return _RowsResult(self.rows)


class AuditLogServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_list_platform_risk_audit_logs_filters_platform_scope_and_action_prefix(self) -> None:
        session = _FakeSession([])
        service = AuditLogService()

        logs = await service.list_platform_risk_audit_logs(session)

        self.assertEqual([], logs)
        self.assertEqual(1, len(session.executed_queries))
        sql, params = _compiled_query(session.executed_queries[0])
        self.assertIn("audit_logs.tenant_id IS NULL", sql)
        self.assertIn("audit_logs.action LIKE", sql)
        self.assertIn("platform_risk.%", params.values())

    async def test_list_platform_risk_audit_logs_accepts_platform_action_and_rejects_invalid_before_query(
        self,
    ) -> None:
        service = AuditLogService()
        accepted_session = _FakeSession([])

        await service.list_platform_risk_audit_logs(
            accepted_session,
            action="platform_risk.user_banned",
        )

        self.assertEqual(1, len(accepted_session.executed_queries))
        sql, params = _compiled_query(accepted_session.executed_queries[0])
        self.assertIn("audit_logs.action = ", sql)
        self.assertIn("platform_risk.user_banned", params.values())

        for action in ("tenant_api_key.created", "risk.user_banned", "bad\nvalue"):
            session = _FakeSession([])
            with self.assertRaisesRegex(ValueError, "action|平台风控审计"):
                await service.list_platform_risk_audit_logs(session, action=action)
            self.assertEqual([], session.executed_queries)

    async def test_list_platform_risk_audit_logs_rejects_invalid_telegram_user_id_before_query(self) -> None:
        service = AuditLogService()

        for telegram_user_id in (0, -1, "123456", True):
            session = _FakeSession([])
            with self.assertRaisesRegex(ValueError, "Telegram 用户 ID"):
                await service.list_platform_risk_audit_logs(session, telegram_user_id=telegram_user_id)  # type: ignore[arg-type]
            self.assertEqual([], session.executed_queries)

    async def test_list_platform_risk_audit_logs_normalizes_limit_and_rejects_non_integer_before_query(
        self,
    ) -> None:
        service = AuditLogService()

        for raw_limit, expected_limit in ((0, 1), (1, 1), (100, 100), (500, 100)):
            session = _FakeSession([])
            await service.list_platform_risk_audit_logs(session, limit=raw_limit)
            _, params = _compiled_query(session.executed_queries[0])
            self.assertIn(expected_limit, params.values())

        for invalid_limit in (True, 1.5, "20"):
            session = _FakeSession([])
            with self.assertRaisesRegex(ValueError, "查询数量"):
                await service.list_platform_risk_audit_logs(session, limit=invalid_limit)  # type: ignore[arg-type]
            self.assertEqual([], session.executed_queries)

    async def test_list_platform_risk_audit_logs_returns_safe_summary_fields_only(self) -> None:
        now = datetime.now(timezone.utc)
        raw_values = {
            "raw-token",
            "raw-secret",
            "raw-api-key",
            "https://pay.example/order",
            "UPSTREAM-TRADE-NO",
            "raw-payload",
        }
        rows = [
            (
                _platform_risk_audit_log(
                    now=now,
                    metadata={
                        "telegram_user_id": 998877,
                        "previous_status": "active",
                        "new_status": "banned",
                        "reason": "manual review",
                        "trigger_rule": "repeat failures",
                        "blocked_count": 3,
                        "threshold": 2,
                        "window_seconds": 60,
                        "tenant_id": 7,
                        "actor_user_id": 12,
                        "target_id": "99",
                        "metadata_json": {"token": "raw-token"},
                        "payload": "raw-payload",
                        "token": "raw-token",
                        "secret": "raw-secret",
                        "api_key": "raw-api-key",
                        "payment_url": "https://pay.example/order",
                        "provider_trade_no": "UPSTREAM-TRADE-NO",
                    },
                ),
                SimpleNamespace(id=12, telegram_user_id=123456, username="platform-admin"),
            )
        ]
        service = AuditLogService()

        logs = await service.list_platform_risk_audit_logs(_FakeSession(rows), limit=20)

        self.assertEqual(1, len(logs))
        summary = logs[0]
        self.assertIsInstance(summary, PlatformRiskAuditLogSummary)
        self.assertEqual(
            {
                "created_at",
                "action",
                "target_type",
                "actor_telegram_user_id",
                "actor_username",
                "target_telegram_user_id",
                "previous_status",
                "new_status",
                "reason",
                "risk_rule",
                "blocked_count",
                "threshold",
                "window_seconds",
            },
            set(summary.__dataclass_fields__),
        )
        self.assertEqual(123456, summary.actor_telegram_user_id)
        self.assertEqual("platform-admin", summary.actor_username)
        self.assertEqual(998877, summary.target_telegram_user_id)
        self.assertEqual("manual review", summary.reason)
        self.assertEqual("repeat failures", summary.risk_rule)
        self.assertEqual(3, summary.blocked_count)
        self.assertEqual(2, summary.threshold)
        self.assertEqual(60, summary.window_seconds)
        for forbidden_field in (
            "tenant_id",
            "actor_user_id",
            "target_id",
            "metadata_json",
            "payload",
            "token",
            "secret",
            "api_key",
            "payment_url",
            "provider_trade_no",
        ):
            self.assertNotIn(forbidden_field, summary.__dict__)
        for raw_value in raw_values:
            self.assertNotIn(raw_value, repr(summary))

    async def test_list_platform_risk_audit_logs_hides_sensitive_reason_and_risk_rule(self) -> None:
        now = datetime.now(timezone.utc)
        rows = [
            (
                _platform_risk_audit_log(
                    now=now,
                    metadata={
                        "telegram_user_id": 112233,
                        "reason": "see https://example.test/evidence",
                        "trigger_rule": "api_key leaked in payload",
                    },
                ),
                None,
            )
        ]
        service = AuditLogService()

        logs = await service.list_platform_risk_audit_logs(_FakeSession(rows))

        self.assertEqual(1, len(logs))
        self.assertEqual("内容已隐藏", logs[0].reason)
        self.assertEqual("内容已隐藏", logs[0].risk_rule)

    async def test_list_platform_risk_audit_logs_filters_by_target_telegram_user_id(self) -> None:
        now = datetime.now(timezone.utc)
        rows = [
            (_platform_risk_audit_log(now=now, metadata={"telegram_user_id": 111}), None),
            (_platform_risk_audit_log(now=now, metadata={"buyer_telegram_user_id": 222}), None),
        ]
        session = _FakeSession(rows)
        service = AuditLogService()

        logs = await service.list_platform_risk_audit_logs(session, telegram_user_id=222, limit=10)

        self.assertEqual(1, len(logs))
        self.assertEqual(222, logs[0].target_telegram_user_id)
        _, params = _compiled_query(session.executed_queries[0])
        self.assertIn(100, params.values())

    async def test_list_tenant_audit_logs_supports_safe_filters_and_redaction(self) -> None:
        now = datetime.now(timezone.utc)
        rows = [
            (
                _audit_log(now=now),
                SimpleNamespace(id=12, telegram_user_id=123456, username="owner"),
            )
        ]
        service = AuditLogService()

        logs = await service.list_tenant_audit_logs(
            _FakeSession(rows),
            tenant_id=7,
            limit=200,
            action="tenant_api_key.created",
            target_type="tenant_api_key",
        )

        self.assertEqual(1, len(logs))
        log = logs[0]
        self.assertEqual(1, log.audit_log_id)
        self.assertEqual(7, log.tenant_id)
        self.assertEqual(12, log.actor_user_id)
        self.assertEqual(123456, log.actor_telegram_user_id)
        self.assertEqual("owner", log.actor_username)
        self.assertEqual("***", log.metadata_json["token"])
        self.assertEqual("***", log.metadata_json["nested"]["secret_key"])
        self.assertEqual("***", log.metadata_json["items"][0]["plain_key"])
        self.assertEqual("visible", log.metadata_json["safe"])

    async def test_list_tenant_audit_logs_rejects_invalid_filters_before_query(self) -> None:
        session = _FakeSession([])
        service = AuditLogService()

        with self.assertRaisesRegex(ValueError, "action"):
            await service.list_tenant_audit_logs(session, tenant_id=7, action="A" * 129)
        with self.assertRaisesRegex(ValueError, "target_type"):
            await service.list_tenant_audit_logs(session, tenant_id=7, target_type="bad\nvalue")

        self.assertEqual([], session.executed_queries)

    def test_safe_metadata_for_tenant_api_removes_sensitive_keys_recursively(self) -> None:
        metadata = {
            "token": "raw-token",
            "signature": "raw-signature",
            "signing_text": "raw-signing-text",
            "payment_url": "https://pay.example/?token=raw-token",
            "provider_trade_no": "UPSTREAM-SECRET",
            "headers": {"authorization": "Bearer raw-token", "safe_header": "kept"},
            "nested": {"secret_key": "raw-secret", "safe": "visible"},
            "items": [{"plain_key": "raw-key", "name": "kept"}],
            "amount": "10.00",
        }

        safe = AuditLogService().safe_metadata_for_tenant_api(metadata)

        self.assertEqual("10.00", safe["amount"])
        self.assertEqual("visible", safe["nested"]["safe"])
        self.assertEqual("kept", safe["items"][0]["name"])
        self.assertNotIn("token", safe)
        self.assertNotIn("signature", safe)
        self.assertNotIn("signing_text", safe)
        self.assertNotIn("payment_url", safe)
        self.assertNotIn("provider_trade_no", safe)
        self.assertNotIn("headers", safe)
        self.assertNotIn("secret_key", safe["nested"])
        self.assertNotIn("plain_key", safe["items"][0])
        self.assertNotIn("raw-token", repr(safe))
        self.assertNotIn("raw-secret", repr(safe))
        self.assertNotIn("UPSTREAM-SECRET", repr(safe))


def _audit_log(*, now: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        tenant_id=7,
        actor_user_id=12,
        action="tenant_api_key.created",
        target_type="tenant_api_key",
        target_id="99",
        metadata_json={
            "token": "raw-token",
            "nested": {"secret_key": "raw-secret", "safe": "visible"},
            "items": [{"plain_key": "raw-key", "name": "kept"}],
            "safe": "visible",
        },
        created_at=now,
    )


def _platform_risk_audit_log(*, now: datetime, metadata: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        id=101,
        tenant_id=None,
        actor_user_id=12,
        action="platform_risk.user_banned",
        target_type="platform_user",
        target_id="99",
        metadata_json=metadata,
        created_at=now,
    )


def _compiled_query(query: object) -> tuple[str, dict[str, object]]:
    compiled = query.compile()
    return str(compiled), dict(compiled.params)


if __name__ == "__main__":
    unittest.main()
