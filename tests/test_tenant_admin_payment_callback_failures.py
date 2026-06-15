from __future__ import annotations

from datetime import datetime, timezone
import logging
from types import SimpleNamespace
import unittest
import warnings
from unittest.mock import AsyncMock, ANY, patch

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)
logging.getLogger("httpx").setLevel(logging.WARNING)

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.services.api_keys import ApiKeyService
    from app.services.payments.failures import PaymentCallbackFailureSummary, PaymentCallbackRejectionSummary
    from app.web.tenant_admin import create_tenant_admin_router
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过 Tenant Admin 支付回调失败观测测试：{exc.name}") from exc


class _FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    async def commit(self) -> None:
        self.commit_count += 1


def _session_factory(session: _FakeSession):
    def factory() -> _FakeSession:
        return session

    return factory


def _client(settings: Settings) -> TestClient:
    app = FastAPI()
    app.state.redis = None
    app.include_router(create_tenant_admin_router(settings))
    return TestClient(app)


def _api_key(*, tenant_id: int = 7, scopes: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        tenant_id=tenant_id,
        scopes_json=scopes or ["payments:read"],
        ip_allowlist_json=[],
    )


def _authenticate(api_key: object):
    async def authenticate(self: ApiKeyService, session: object, plain_key: str) -> object | None:
        return api_key

    return authenticate


class TenantAdminPaymentCallbackFailureRouteTest(unittest.TestCase):
    def test_list_payment_callback_failures_requires_payments_read_scope_before_service(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:write"]))):
                with patch("app.web.tenant_admin.PaymentCallbackFailureLogService") as service:
                    response = client.get(
                        "/api/v1/tenant/payments/callback-failures",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        service.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_list_payment_callback_failures_returns_safe_tenant_scoped_payload(self) -> None:
        session = _FakeSession()
        now = datetime.now(timezone.utc)
        failures = [
            PaymentCallbackFailureSummary(
                callback_id=9,
                created_at=now,
                processed_at=now,
                order_id=55,
                out_trade_no="ORD123",
                order_status="expired",
                provider="token188",
                process_status="failed",
                failure_reason="订单已过期或不可支付",
            )
        ]
        list_failures = AsyncMock(return_value=failures)
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:read"]))):
                with patch("app.web.tenant_admin.PaymentCallbackFailureLogService") as service:
                    service.return_value.list_failures = list_failures
                    response = client.get(
                        "/api/v1/tenant/payments/callback-failures"
                        "?provider=token188&process_status=failed&out_trade_no=ORD123&limit=5",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(1, len(payload["failures"]))
        item = payload["failures"][0]
        self.assertEqual(9, item["callback_id"])
        self.assertEqual(55, item["order_id"])
        self.assertEqual("ORD123", item["out_trade_no"])
        self.assertEqual("expired", item["order_status"])
        self.assertEqual("token188", item["provider"])
        self.assertEqual("failed", item["process_status"])
        self.assertEqual("订单已过期或不可支付", item["failure_reason"])
        self.assertNotIn("payload_json", response.text)
        self.assertNotIn("payload_hash", response.text)
        self.assertNotIn("provider_trade_no", response.text)
        self.assertNotIn("plain-secret", response.text)
        list_failures.assert_awaited_once_with(
            session,
            tenant_id=7,
            provider="token188",
            process_status="failed",
            out_trade_no="ORD123",
            limit=5,
        )

    def test_list_payment_callback_failures_value_error_returns_400_without_secret(self) -> None:
        session = _FakeSession()
        list_failures = AsyncMock(side_effect=ValueError("signature signing_text plain-secret"))
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:read"]))):
                with patch("app.web.tenant_admin.PaymentCallbackFailureLogService") as service:
                    service.return_value.list_failures = list_failures
                    response = client.get(
                        "/api/v1/tenant/payments/callback-failures?process_status=processed",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("支付回调查询参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("signing_text", response.text)
        list_failures.assert_awaited_once_with(
            ANY,
            tenant_id=7,
            provider=None,
            process_status="processed",
            out_trade_no=None,
            limit=20,
        )

    def test_list_payment_callback_rejections_requires_payments_read_scope_before_service(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:write"]))):
                with patch("app.web.tenant_admin.PaymentCallbackRejectionAuditService") as service:
                    response = client.get(
                        "/api/v1/tenant/payments/callback-rejections",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        service.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_list_payment_callback_rejections_returns_safe_tenant_scoped_payload(self) -> None:
        session = _FakeSession()
        now = datetime.now(timezone.utc)
        rejections = [
            PaymentCallbackRejectionSummary(
                audit_log_id=12,
                created_at=now,
                provider="token188",
                reason_category="invalid_callback",
                failure_reason="支付回调参数无效",
                http_status=400,
                out_trade_no="ORD123",
                order_id=55,
                order_status="pending",
                payload_field_count=4,
            )
        ]
        list_rejections = AsyncMock(return_value=rejections)
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:read"]))):
                with patch("app.web.tenant_admin.PaymentCallbackRejectionAuditService") as service:
                    service.return_value.list_rejections = list_rejections
                    response = client.get(
                        "/api/v1/tenant/payments/callback-rejections"
                        "?provider=token188&reason_category=invalid_callback&out_trade_no=ORD123&limit=5",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(1, len(payload["rejections"]))
        item = payload["rejections"][0]
        self.assertEqual(12, item["audit_log_id"])
        self.assertEqual("token188", item["provider"])
        self.assertEqual("invalid_callback", item["reason_category"])
        self.assertEqual("支付回调参数无效", item["failure_reason"])
        self.assertEqual(400, item["http_status"])
        self.assertEqual("ORD123", item["out_trade_no"])
        self.assertEqual(55, item["order_id"])
        self.assertEqual("pending", item["order_status"])
        self.assertEqual(4, item["payload_field_count"])
        self.assertNotIn("payload_json", response.text)
        self.assertNotIn("payload_hash", response.text)
        self.assertNotIn("provider_trade_no", response.text)
        self.assertNotIn("plain-secret", response.text)
        list_rejections.assert_awaited_once_with(
            session,
            tenant_id=7,
            provider="token188",
            reason_category="invalid_callback",
            out_trade_no="ORD123",
            limit=5,
        )

    def test_list_payment_callback_rejections_value_error_returns_400_without_secret(self) -> None:
        session = _FakeSession()
        list_rejections = AsyncMock(side_effect=ValueError("signature signing_text plain-secret"))
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:read"]))):
                with patch("app.web.tenant_admin.PaymentCallbackRejectionAuditService") as service:
                    service.return_value.list_rejections = list_rejections
                    response = client.get(
                        "/api/v1/tenant/payments/callback-rejections?reason_category=secret",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("支付回调查询参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("signing_text", response.text)
        list_rejections.assert_awaited_once_with(
            ANY,
            tenant_id=7,
            provider=None,
            reason_category="secret",
            out_trade_no=None,
            limit=20,
        )


if __name__ == "__main__":
    unittest.main()
