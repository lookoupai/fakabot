from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

try:
    from app.services.external_sources.attempts import (
        SENSITIVE_ATTEMPT_VALUE_MARKERS,
        ExternalFulfillmentAttemptLogService,
    )
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过外部履约 attempt 观测测试：{exc.name}") from exc


class _FakeScalars:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class _FakeResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class _FakeSession:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.execute_count = 0
        self.executed_queries: list[object] = []

    async def execute(self, query: object) -> _FakeResult:
        self.execute_count += 1
        self.executed_queries.append(query)
        return _FakeResult(self.rows)


def _attempt_row(
    *,
    attempt_id: int = 1,
    tenant_id: int = 7,
    out_trade_no: str = "ORD-1",
    provider_name: str = "acg",
    source_key: str = "main",
    external_order_id: str | None = "EXT-1",
    attempt_source: str = "auto",
    status: str = "failed",
    failure_retryable: bool | None = True,
    failure_reason: str | None = "外部履约失败",
) -> SimpleNamespace:
    now = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
    return SimpleNamespace(
        id=attempt_id,
        tenant_id=tenant_id,
        created_at=now,
        started_at=now,
        finished_at=now,
        order_id=13,
        out_trade_no=out_trade_no,
        product_id=101,
        provider_name=provider_name,
        source_key=source_key,
        external_product_id="sku-1",
        connection_id=44,
        external_order_id=external_order_id,
        delivery_record_id=88,
        attempt_source=attempt_source,
        status=status,
        imported=status == "imported",
        item_count=2,
        failure_reason=failure_reason,
        failure_stage="fetch_delivery" if status == "failed" else None,
        failure_category="upstream_error" if status == "failed" else None,
        failure_retryable=failure_retryable,
        upstream_status_code=503 if status == "failed" else None,
        failure_fingerprint="f" * 64 if status == "failed" else None,
        raw_payload={"token": "provider-secret"},
        credentials={"api_key": "plain-secret"},
    )


class ExternalFulfillmentAttemptLogServiceTest(unittest.IsolatedAsyncioTestCase):
    def test_sensitive_attempt_value_markers_cover_common_secret_terms(self) -> None:
        self.assertIn("token", SENSITIVE_ATTEMPT_VALUE_MARKERS)
        self.assertIn("secret", SENSITIVE_ATTEMPT_VALUE_MARKERS)
        self.assertIn("payload", SENSITIVE_ATTEMPT_VALUE_MARKERS)

    async def test_list_attempts_returns_safe_whitelisted_summary(self) -> None:
        session = _FakeSession([_attempt_row()])

        attempts = await ExternalFulfillmentAttemptLogService().list_attempts(
            session,
            tenant_id=7,
            limit=20,
        )

        self.assertEqual(1, session.execute_count)
        self.assertEqual(1, len(attempts))
        attempt = attempts[0]
        self.assertEqual(1, attempt.attempt_id)
        self.assertEqual(13, attempt.order_id)
        self.assertEqual("ORD-1", attempt.out_trade_no)
        self.assertEqual(101, attempt.product_id)
        self.assertEqual("acg", attempt.provider_name)
        self.assertEqual("main", attempt.source_key)
        self.assertEqual("sku-1", attempt.external_product_id)
        self.assertEqual(44, attempt.connection_id)
        self.assertEqual("EXT-1", attempt.external_order_id)
        self.assertEqual(88, attempt.delivery_record_id)
        self.assertEqual("auto", attempt.attempt_source)
        self.assertEqual("failed", attempt.status)
        self.assertFalse(attempt.imported)
        self.assertEqual(2, attempt.item_count)
        self.assertEqual("fetch_delivery", attempt.failure_stage)
        self.assertEqual("upstream_error", attempt.failure_category)
        self.assertTrue(attempt.failure_retryable)
        self.assertEqual(503, attempt.upstream_status_code)
        self.assertEqual("f" * 64, attempt.failure_fingerprint)
        self.assertNotIn("raw_payload", repr(attempt))
        self.assertNotIn("provider-secret", repr(attempt))
        self.assertFalse(hasattr(attempt, "tenant_id"))

    async def test_list_attempts_filters_by_status_source_order_and_retryable(self) -> None:
        rows = [
            _attempt_row(attempt_id=1),
            _attempt_row(attempt_id=2, out_trade_no="ORD-2", failure_retryable=False),
            _attempt_row(attempt_id=3, provider_name="other", failure_retryable=False),
            _attempt_row(attempt_id=4, status="imported", failure_retryable=None),
            _attempt_row(attempt_id=5, status="succeeded", failure_retryable=None),
        ]
        session = _FakeSession(rows)

        attempts = await ExternalFulfillmentAttemptLogService().list_attempts(
            session,
            tenant_id=7,
            out_trade_no=" ORD-2 ",
            provider_name=" acg ",
            source_key=" main ",
            external_order_id=" EXT-1 ",
            attempt_source=" auto ",
            status=" failed ",
            failure_stage=" fetch_delivery ",
            failure_category=" upstream_error ",
            failure_retryable=False,
            limit=10,
        )

        self.assertEqual([2], [attempt.attempt_id for attempt in attempts])

    async def test_list_attempts_filters_succeeded_lifecycle_status(self) -> None:
        rows = [
            _attempt_row(attempt_id=1, status="started", failure_retryable=None),
            _attempt_row(attempt_id=2, status="running", failure_retryable=None),
            _attempt_row(attempt_id=3, status="succeeded", failure_retryable=None),
            _attempt_row(attempt_id=4, status="already_delivered", failure_retryable=None),
            _attempt_row(attempt_id=5, status="imported", failure_retryable=None),
            _attempt_row(attempt_id=6, status="failed"),
        ]
        session = _FakeSession(rows)

        attempts = await ExternalFulfillmentAttemptLogService().list_attempts(
            session,
            tenant_id=7,
            status="succeeded",
            limit=20,
        )

        self.assertEqual([3], [attempt.attempt_id for attempt in attempts])

    async def test_list_attempts_accepts_running_lifecycle_status(self) -> None:
        rows = [
            _attempt_row(attempt_id=1, status="started", failure_retryable=None),
            _attempt_row(attempt_id=2, status="running", failure_retryable=None),
            _attempt_row(attempt_id=3, status="succeeded", failure_retryable=None),
        ]
        session = _FakeSession(rows)

        attempts = await ExternalFulfillmentAttemptLogService().list_attempts(
            session,
            tenant_id=7,
            status="running",
            limit=20,
        )

        self.assertEqual([2], [attempt.attempt_id for attempt in attempts])

    async def test_list_attempts_clamps_limit_and_keeps_tenant_filter_in_query(self) -> None:
        session = _FakeSession([_attempt_row(attempt_id=1), _attempt_row(attempt_id=2)])

        await ExternalFulfillmentAttemptLogService().list_attempts(session, tenant_id=7, limit=999)

        self.assertEqual(1, session.execute_count)
        compiled = str(session.executed_queries[0])
        self.assertIn("external_fulfillment_attempts.tenant_id", compiled)
        self.assertIn("ORDER BY", compiled)

    async def test_list_attempts_rejects_invalid_filters_before_query(self) -> None:
        session = _FakeSession([])
        service = ExternalFulfillmentAttemptLogService()

        with self.assertRaisesRegex(ValueError, "attempt_source"):
            await service.list_attempts(session, tenant_id=7, attempt_source="system")
        with self.assertRaisesRegex(ValueError, "status"):
            await service.list_attempts(session, tenant_id=7, status="unknown")
        with self.assertRaisesRegex(ValueError, "limit"):
            await service.list_attempts(session, tenant_id=7, limit=True)
        with self.assertRaisesRegex(ValueError, "external_order_id"):
            await service.list_attempts(session, tenant_id=7, external_order_id="EXT\n1")

        self.assertEqual(0, session.execute_count)

    async def test_list_attempts_redacts_sensitive_failure_reason(self) -> None:
        rows = [
            _attempt_row(
                attempt_id=1,
                failure_reason="Authorization token plain-secret raw_payload card_secret",
            )
        ]

        attempts = await ExternalFulfillmentAttemptLogService().list_attempts(
            _FakeSession(rows),
            tenant_id=7,
        )

        self.assertEqual("外部履约失败", attempts[0].failure_reason)
        self.assertNotIn("plain-secret", repr(attempts[0]))
        self.assertNotIn("raw_payload", repr(attempts[0]))
        self.assertNotIn("card_secret", repr(attempts[0]))


if __name__ == "__main__":
    unittest.main()
