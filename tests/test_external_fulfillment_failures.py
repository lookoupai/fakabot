from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

try:
    from app.services.external_sources.failures import (
        EXTERNAL_FULFILLMENT_FAILED_ACTION,
        ExternalFulfillmentFailureLogService,
    )
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过外部履约失败观测测试：{exc.name}") from exc


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

    async def execute(self, query: object) -> _FakeResult:
        self.execute_count += 1
        return _FakeResult(self.rows)


def _audit_row(
    *,
    audit_log_id: int = 1,
    tenant_id: int = 7,
    action: str = EXTERNAL_FULFILLMENT_FAILED_ACTION,
    target_type: str = "order",
    metadata: dict[str, object] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=audit_log_id,
        tenant_id=tenant_id,
        action=action,
        target_type=target_type,
        metadata_json=metadata
        or {
            "order_id": 13,
            "out_trade_no": "ORD-1",
            "product_id": 101,
            "provider_name": "acg",
            "source": "main",
            "external_product_id": "sku-1",
            "connection_id": 44,
            "external_order_id": "EXT-1",
            "failure_reason": "外部履约失败",
            "failure_stage": "fetch_delivery",
            "failure_category": "upstream_error",
            "failure_retryable": True,
            "upstream_status_code": 503,
            "failure_fingerprint": "f" * 64,
            "raw_payload": "secret-body",
            "api_key": "provider-secret",
        },
        created_at=datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc),
    )


class ExternalFulfillmentFailureLogServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_list_failures_returns_safe_whitelisted_summary(self) -> None:
        session = _FakeSession([_audit_row()])

        failures = await ExternalFulfillmentFailureLogService().list_failures(
            session,
            tenant_id=7,
            limit=20,
        )

        self.assertEqual(1, session.execute_count)
        self.assertEqual(1, len(failures))
        failure = failures[0]
        self.assertEqual(1, failure.audit_log_id)
        self.assertEqual(13, failure.order_id)
        self.assertEqual("ORD-1", failure.out_trade_no)
        self.assertEqual(101, failure.product_id)
        self.assertEqual("acg", failure.provider_name)
        self.assertEqual("main", failure.source_key)
        self.assertEqual("sku-1", failure.external_product_id)
        self.assertEqual(44, failure.connection_id)
        self.assertEqual("EXT-1", failure.external_order_id)
        self.assertEqual("fetch_delivery", failure.failure_stage)
        self.assertEqual("upstream_error", failure.failure_category)
        self.assertTrue(failure.failure_retryable)
        self.assertEqual(503, failure.upstream_status_code)
        self.assertEqual("f" * 64, failure.failure_fingerprint)
        self.assertNotIn("secret-body", repr(failure))
        self.assertNotIn("provider-secret", repr(failure))
        self.assertFalse(hasattr(failure, "metadata_json"))

    async def test_list_failures_filters_safe_metadata_values_and_redacts_sensitive_reason(self) -> None:
        rows = [
            _audit_row(audit_log_id=1),
            _audit_row(
                audit_log_id=2,
                metadata={
                    "order_id": 14,
                    "provider_name": "other",
                    "source": "main",
                    "failure_stage": "fetch_delivery",
                    "failure_category": "upstream_error",
                    "failure_reason": "Authorization token plain-secret",
                },
            ),
            _audit_row(
                audit_log_id=3,
                metadata={
                    "order_id": 15,
                    "out_trade_no": "ORD-3",
                    "provider_name": "acg",
                    "source": "backup",
                    "failure_stage": "load_credentials",
                    "failure_category": "connection_missing",
                    "failure_retryable": False,
                },
            ),
        ]
        session = _FakeSession(rows)

        failures = await ExternalFulfillmentFailureLogService().list_failures(
            session,
            tenant_id=7,
            out_trade_no=" ORD-1 ",
            provider_name=" acg ",
            source_key=" main ",
            failure_stage=" fetch_delivery ",
            failure_category=" upstream_error ",
            failure_retryable=True,
            limit=10,
        )

        self.assertEqual([1], [failure.audit_log_id for failure in failures])
        sensitive = ExternalFulfillmentFailureLogService()._to_summary(rows[1])
        self.assertEqual("外部履约失败", sensitive.failure_reason)

    async def test_list_failures_can_filter_non_retryable_order_failure(self) -> None:
        rows = [
            _audit_row(audit_log_id=1),
            _audit_row(
                audit_log_id=2,
                metadata={
                    "order_id": 14,
                    "out_trade_no": "ORD-2",
                    "provider_name": "acg",
                    "source": "main",
                    "failure_stage": "load_credentials",
                    "failure_category": "connection_missing",
                    "failure_retryable": False,
                },
            ),
        ]
        session = _FakeSession(rows)

        failures = await ExternalFulfillmentFailureLogService().list_failures(
            session,
            tenant_id=7,
            out_trade_no="ORD-2",
            failure_retryable=False,
        )

        self.assertEqual([2], [failure.audit_log_id for failure in failures])

    async def test_list_failures_rejects_invalid_filters(self) -> None:
        session = _FakeSession([])

        with self.assertRaisesRegex(ValueError, "provider_name"):
            await ExternalFulfillmentFailureLogService().list_failures(
                session,
                tenant_id=7,
                provider_name="Bad Provider",
            )

        with self.assertRaisesRegex(ValueError, "limit"):
            await ExternalFulfillmentFailureLogService().list_failures(
                session,
                tenant_id=7,
                limit=True,
            )

        with self.assertRaisesRegex(ValueError, "out_trade_no"):
            await ExternalFulfillmentFailureLogService().list_failures(
                session,
                tenant_id=7,
                out_trade_no="",
            )

        with self.assertRaisesRegex(ValueError, "failure_retryable"):
            await ExternalFulfillmentFailureLogService().list_failures(
                session,
                tenant_id=7,
                failure_retryable="true",  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
