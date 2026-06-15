from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import logging
from types import SimpleNamespace
import unittest
import warnings
from unittest.mock import ANY, AsyncMock, patch

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
    from app.services.external_sources import (
        ExternalDelivery,
        ExternalFulfillmentAttemptSummary,
        ExternalFulfillmentFailureSummary,
        ExternalOrder,
        ExternalSourceError,
    )
    from app.services.external_sources.connections import ExternalSourceRuntimeCredentials
    from app.services.external_sources.fulfillment import ExternalDeliveryImportResult
    from app.web.tenant_admin import create_tenant_admin_router
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过 Tenant Admin 外部订单操作测试：{exc.name}") from exc


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
        scopes_json=scopes or ["external_sources:read", "external_sources:write"],
        ip_allowlist_json=[],
    )


def _authenticate(api_key: object):
    async def authenticate(self: ApiKeyService, session: object, plain_key: str) -> object | None:
        return api_key

    return authenticate


def _connection_summary(
    *,
    connection_id: int = 12,
    provider_name: str = "acg",
    source_key: str = "main",
    status: str = "active",
) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        connection_id=connection_id,
        provider_name=provider_name,
        source_key=source_key,
        display_name="ACG 主连接",
        status=status,
        credential_fields=["sensitive_1"],
        credentials={"api_key": "plain-secret"},
        credentials_encrypted="encrypted-secret",
        created_at=now,
        last_used_at=None,
    )


def _runtime_auth() -> ExternalSourceRuntimeCredentials:
    return ExternalSourceRuntimeCredentials(
        connection_id=12,
        tenant_id=7,
        provider_name="acg",
        source_key="main",
        credential_fields=["sensitive_1"],
        credentials={"api_key": "correct-secret"},
    )


def _external_order() -> ExternalOrder:
    return ExternalOrder(
        provider="acg",
        external_order_id="EXT-1",
        external_product_id="sku-1",
        status="paid",
        quantity=2,
        amount=Decimal("18.50"),
        currency="USDT",
        delivery_ready=True,
        raw_payload={"internal_id": "upstream-raw"},
    )


def _external_delivery() -> ExternalDelivery:
    return ExternalDelivery(
        provider="acg",
        external_order_id="EXT-1",
        delivery_type="card_pool",
        items=("card-a", "card-b"),
        message="已发货",
        raw_payload={"internal_id": "delivery-raw"},
    )


class TenantAdminExternalOrderOperationRouteTest(unittest.TestCase):
    def test_create_external_order_requires_write_scope_before_services(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["external_sources:read"]))):
                with patch("app.web.tenant_admin.ExternalOrderOperationService") as operation_service:
                    response = client.post(
                        "/api/v1/tenant/external-sources/acg/orders",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"external_product_id": "sku-1"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        operation_service.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_list_external_fulfillment_failures_requires_external_sources_read_scope(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["orders:read"]))):
                with patch("app.web.tenant_admin.ExternalFulfillmentFailureLogService") as service:
                    response = client.get(
                        "/api/v1/tenant/external-fulfillment/failures",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        service.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_list_external_fulfillment_attempts_requires_external_sources_read_scope(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["orders:read"]))):
                with patch("app.web.tenant_admin.ExternalFulfillmentAttemptLogService") as service:
                    response = client.get(
                        "/api/v1/tenant/external-fulfillment/attempts",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        service.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_list_external_fulfillment_attempts_returns_safe_tenant_scoped_attempts_without_sensitive_payload(
        self,
    ) -> None:
        session = _FakeSession()
        created_at = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
        list_attempts = AsyncMock(
            return_value=[
                ExternalFulfillmentAttemptSummary(
                    attempt_id=22,
                    created_at=created_at,
                    started_at=created_at,
                    finished_at=created_at,
                    order_id=13,
                    out_trade_no="ORD-1",
                    product_id=101,
                    provider_name="acg",
                    source_key="main",
                    external_product_id="sku-1",
                    connection_id=44,
                    external_order_id="EXT-1",
                    delivery_record_id=88,
                    attempt_source="auto",
                    status="failed",
                    imported=False,
                    item_count=2,
                    failure_reason="外部履约失败",
                    failure_stage="fetch_delivery",
                    failure_category="upstream_error",
                    failure_retryable=True,
                    upstream_status_code=503,
                    failure_fingerprint="f" * 64,
                )
            ]
        )
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7))):
                with patch("app.web.tenant_admin.ExternalFulfillmentAttemptLogService") as service:
                    service.return_value.list_attempts = list_attempts
                    response = client.get(
                        "/api/v1/tenant/external-fulfillment/attempts",
                        headers={"X-API-Key": "fk_live_test"},
                        params={
                            "out_trade_no": "ORD-1",
                            "provider_name": "acg",
                            "source_key": "main",
                            "external_order_id": "EXT-1",
                            "attempt_source": "auto",
                            "status": "failed",
                            "failure_stage": "fetch_delivery",
                            "failure_category": "upstream_error",
                            "failure_retryable": True,
                            "limit": 10,
                        },
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(1, len(payload["attempts"]))
        attempt = payload["attempts"][0]
        self.assertEqual(22, attempt["attempt_id"])
        self.assertEqual("2026-06-08T12:00:00+00:00", attempt["created_at"])
        self.assertEqual("2026-06-08T12:00:00+00:00", attempt["started_at"])
        self.assertEqual("2026-06-08T12:00:00+00:00", attempt["finished_at"])
        self.assertEqual(13, attempt["order_id"])
        self.assertEqual("ORD-1", attempt["out_trade_no"])
        self.assertEqual(101, attempt["product_id"])
        self.assertEqual("acg", attempt["provider_name"])
        self.assertEqual("main", attempt["source_key"])
        self.assertEqual("sku-1", attempt["external_product_id"])
        self.assertEqual(44, attempt["connection_id"])
        self.assertEqual("EXT-1", attempt["external_order_id"])
        self.assertEqual(88, attempt["delivery_record_id"])
        self.assertEqual("auto", attempt["attempt_source"])
        self.assertEqual("failed", attempt["status"])
        self.assertFalse(attempt["imported"])
        self.assertEqual(2, attempt["item_count"])
        self.assertEqual("fetch_delivery", attempt["failure_stage"])
        self.assertEqual("upstream_error", attempt["failure_category"])
        self.assertTrue(attempt["failure_retryable"])
        self.assertEqual(503, attempt["upstream_status_code"])
        self.assertEqual("f" * 64, attempt["failure_fingerprint"])
        self.assertNotIn("tenant_id", attempt)
        self.assertNotIn("metadata_json", attempt)
        self.assertNotIn("raw_payload", response.text)
        self.assertNotIn("credentials", response.text)
        self.assertNotIn("api_key", response.text)
        self.assertNotIn("secret", response.text)
        self.assertNotIn("items", response.text)
        self.assertNotIn("message", response.text)
        self.assertEqual(1, session.commit_count)
        list_attempts.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            out_trade_no="ORD-1",
            provider_name="acg",
            source_key="main",
            external_order_id="EXT-1",
            attempt_source="auto",
            status="failed",
            failure_stage="fetch_delivery",
            failure_category="upstream_error",
            failure_retryable=True,
            limit=10,
        )

    def test_list_external_fulfillment_attempts_invalid_filter_returns_generic_error(self) -> None:
        session = _FakeSession()
        list_attempts = AsyncMock(side_effect=ValueError("token=plain-secret raw_payload={}"))
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7))):
                with patch("app.web.tenant_admin.ExternalFulfillmentAttemptLogService") as service:
                    service.return_value.list_attempts = list_attempts
                    response = client.get(
                        "/api/v1/tenant/external-fulfillment/attempts?status=running",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("外部履约尝试查询参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("raw_payload", response.text)
        self.assertEqual(1, session.commit_count)

    def test_list_external_fulfillment_failures_returns_safe_audit_metadata_without_credentials(self) -> None:
        session = _FakeSession()
        created_at = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
        list_failures = AsyncMock(
            return_value=[
                ExternalFulfillmentFailureSummary(
                    audit_log_id=9,
                    created_at=created_at,
                    order_id=13,
                    out_trade_no="ORD-1",
                    product_id=101,
                    provider_name="acg",
                    source_key="main",
                    external_product_id="sku-1",
                    connection_id=44,
                    external_order_id="EXT-1",
                    failure_reason="外部履约失败",
                    failure_stage="fetch_delivery",
                    failure_category="upstream_error",
                    failure_retryable=True,
                    upstream_status_code=503,
                    failure_fingerprint="f" * 64,
                )
            ]
        )
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7))):
                with patch("app.web.tenant_admin.ExternalFulfillmentFailureLogService") as service:
                    service.return_value.list_failures = list_failures
                    response = client.get(
                        "/api/v1/tenant/external-fulfillment/failures",
                        headers={"X-API-Key": "fk_live_test"},
                        params={
                            "out_trade_no": "ORD-1",
                            "provider_name": "acg",
                            "source_key": "main",
                            "failure_stage": "fetch_delivery",
                            "failure_category": "upstream_error",
                            "failure_retryable": True,
                            "limit": 10,
                        },
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(1, len(payload["failures"]))
        failure = payload["failures"][0]
        self.assertEqual(9, failure["audit_log_id"])
        self.assertEqual("2026-06-08T12:00:00+00:00", failure["created_at"])
        self.assertEqual(13, failure["order_id"])
        self.assertEqual("ORD-1", failure["out_trade_no"])
        self.assertEqual(101, failure["product_id"])
        self.assertEqual("acg", failure["provider_name"])
        self.assertEqual("main", failure["source_key"])
        self.assertEqual("sku-1", failure["external_product_id"])
        self.assertEqual(44, failure["connection_id"])
        self.assertEqual("EXT-1", failure["external_order_id"])
        self.assertEqual("fetch_delivery", failure["failure_stage"])
        self.assertEqual("upstream_error", failure["failure_category"])
        self.assertTrue(failure["failure_retryable"])
        self.assertEqual(503, failure["upstream_status_code"])
        self.assertEqual("f" * 64, failure["failure_fingerprint"])
        self.assertNotIn("metadata_json", failure)
        self.assertNotIn("raw_payload", response.text)
        self.assertNotIn("credentials", response.text)
        self.assertNotIn("api_key", response.text)
        self.assertNotIn("secret", response.text)
        self.assertEqual(1, session.commit_count)
        list_failures.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            out_trade_no="ORD-1",
            provider_name="acg",
            source_key="main",
            failure_stage="fetch_delivery",
            failure_category="upstream_error",
            failure_retryable=True,
            limit=10,
        )

    def test_retry_external_fulfillment_requires_write_scope_before_service(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["external_sources:read"]))):
                with patch("app.web.tenant_admin.ExternalAutoFulfillmentService") as service:
                    response = client.post(
                        "/api/v1/tenant/orders/ORD123/external-fulfillment/retry",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        service.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_retry_external_fulfillment_returns_safe_success_summary_without_delivery_content(self) -> None:
        session = _FakeSession()
        fulfill_tenant_paid_order = AsyncMock(
            return_value=SimpleNamespace(
                out_trade_no="ORD123",
                provider_name="acg",
                source_key="main",
                external_order_id="EXT-1",
                delivery_record_id=88,
                item_count=2,
                imported=True,
                attempt_status="imported",
                failure_stage=None,
                failure_category=None,
                failure_retryable=None,
                upstream_status_code=None,
                failure_recorded=False,
                raw_payload={"token": "provider-secret"},
                items=("card-secret-a",),
            )
        )
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["external_sources:write"]))):
                with patch("app.web.tenant_admin.ExternalAutoFulfillmentService") as service:
                    service.return_value.fulfill_tenant_paid_order = fulfill_tenant_paid_order
                    response = client.post(
                        "/api/v1/tenant/orders/ORD123/external-fulfillment/retry",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("ORD123", payload["out_trade_no"])
        self.assertEqual("acg", payload["provider_name"])
        self.assertEqual("main", payload["source_key"])
        self.assertEqual("EXT-1", payload["external_order_id"])
        self.assertEqual(88, payload["delivery_record_id"])
        self.assertEqual(2, payload["item_count"])
        self.assertTrue(payload["imported"])
        self.assertEqual("imported", payload["attempt_status"])
        self.assertFalse(payload["failure_recorded"])
        self.assertNotIn("raw_payload", payload)
        self.assertNotIn("items", payload)
        self.assertNotIn("card-secret-a", response.text)
        self.assertNotIn("provider-secret", response.text)
        self.assertNotIn("token", response.text.lower())
        self.assertEqual(2, session.commit_count)
        fulfill_tenant_paid_order.assert_awaited_once_with(
            session,
            tenant_id=7,
            out_trade_no="ORD123",
            settings=ANY,
        )

    def test_retry_external_fulfillment_returns_safe_failed_summary_without_upstream_detail(self) -> None:
        session = _FakeSession()
        fulfill_tenant_paid_order = AsyncMock(
            return_value=SimpleNamespace(
                out_trade_no="ORD123",
                provider_name="acg",
                source_key="main",
                external_order_id="EXT-1",
                delivery_record_id=None,
                item_count=0,
                imported=False,
                attempt_status="failed",
                failure_stage="fetch_delivery",
                failure_category="upstream_error",
                failure_retryable=True,
                upstream_status_code=503,
                failure_recorded=True,
                raw_payload={"secret": "provider-secret"},
            )
        )
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["external_sources:write"]))):
                with patch("app.web.tenant_admin.ExternalAutoFulfillmentService") as service:
                    service.return_value.fulfill_tenant_paid_order = fulfill_tenant_paid_order
                    response = client.post(
                        "/api/v1/tenant/orders/ORD123/external-fulfillment/retry",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("failed", payload["attempt_status"])
        self.assertEqual("fetch_delivery", payload["failure_stage"])
        self.assertEqual("upstream_error", payload["failure_category"])
        self.assertTrue(payload["failure_retryable"])
        self.assertEqual(503, payload["upstream_status_code"])
        self.assertTrue(payload["failure_recorded"])
        self.assertNotIn("raw_payload", response.text)
        self.assertNotIn("provider-secret", response.text)
        self.assertNotIn("secret", response.text.lower())
        self.assertEqual(2, session.commit_count)

    def test_retry_external_fulfillment_returns_404_for_missing_order(self) -> None:
        session = _FakeSession()
        fulfill_tenant_paid_order = AsyncMock(return_value=None)
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["external_sources:write"]))):
                with patch("app.web.tenant_admin.ExternalAutoFulfillmentService") as service:
                    service.return_value.fulfill_tenant_paid_order = fulfill_tenant_paid_order
                    response = client.post(
                        "/api/v1/tenant/orders/ORD404/external-fulfillment/retry",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(404, response.status_code)
        self.assertEqual("订单不存在", response.json()["detail"])
        self.assertEqual(1, session.commit_count)
        fulfill_tenant_paid_order.assert_awaited_once()

    def test_retry_external_fulfillment_error_response_is_generic_without_sensitive_detail(self) -> None:
        session = _FakeSession()
        fulfill_tenant_paid_order = AsyncMock(side_effect=ValueError("api_key=plain-secret token=provider-token"))
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["external_sources:write"]))):
                with patch("app.web.tenant_admin.ExternalAutoFulfillmentService") as service:
                    service.return_value.fulfill_tenant_paid_order = fulfill_tenant_paid_order
                    response = client.post(
                        "/api/v1/tenant/orders/ORD123/external-fulfillment/retry",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("订单当前不能外部履约", response.json()["detail"])
        self.assertNotIn("api_key", response.text)
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("provider-token", response.text)
        self.assertNotIn("token", response.text.lower())
        self.assertEqual(1, session.commit_count)

    def test_create_external_order_uses_connection_runtime_auth_and_redacts_response(self) -> None:
        session = _FakeSession()
        get_connection = AsyncMock(return_value=_connection_summary())
        load_runtime_credentials = AsyncMock(return_value=_runtime_auth())
        create_registered_order = AsyncMock(return_value=_external_order())
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7))):
                with patch("app.web.tenant_admin.ExternalSourceConnectionService") as connection_service:
                    with patch("app.web.tenant_admin.ExternalOrderOperationService") as operation_service:
                        connection_service.return_value.get_connection = get_connection
                        connection_service.return_value.load_runtime_credentials = load_runtime_credentials
                        operation_service.return_value.create_registered_order = create_registered_order
                        response = client.post(
                            "/api/v1/tenant/external-sources/acg/orders",
                            headers={"X-API-Key": "fk_live_test"},
                            json={
                                "external_product_id": "sku-1",
                                "quantity": 2,
                                "connection_id": 12,
                                "metadata": {"client_order": "ORD-1"},
                            },
                        )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("acg", payload["provider_name"])
        self.assertEqual("main", payload["source_key"])
        self.assertEqual(12, payload["connection_id"])
        self.assertEqual("EXT-1", payload["external_order_id"])
        self.assertEqual("sku-1", payload["external_product_id"])
        self.assertEqual(2, payload["quantity"])
        self.assertTrue(payload["delivery_ready"])
        self.assertNotIn("raw_payload", payload)
        self.assertNotIn("credentials", payload)
        self.assertNotIn("credentials_encrypted", payload)
        self.assertNotIn("plain-secret", str(payload))
        self.assertNotIn("correct-secret", str(payload))
        self.assertNotIn("api_key", str(payload))
        self.assertEqual(1, session.commit_count)
        get_connection.assert_awaited_once_with(session=session, tenant_id=7, connection_id=12)
        load_runtime_credentials.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            connection_id=12,
            settings=ANY,
        )
        create_registered_order.assert_awaited_once()
        call_kwargs = create_registered_order.await_args.kwargs
        self.assertEqual(7, call_kwargs["tenant_id"])
        self.assertEqual("acg", call_kwargs["provider_name"])
        self.assertEqual("main", call_kwargs["source_key"])
        self.assertEqual(12, call_kwargs["connection_id"])
        self.assertIs(call_kwargs["runtime_auth"], load_runtime_credentials.return_value)
        self.assertEqual("sku-1", call_kwargs["request"].external_product_id)
        self.assertEqual({"client_order": "ORD-1"}, call_kwargs["request"].metadata)

    def test_query_external_order_requires_read_scope_and_returns_404_for_missing_order(self) -> None:
        session = _FakeSession()
        query_registered_order = AsyncMock(return_value=None)
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["external_sources:read"]))):
                with patch("app.web.tenant_admin.ExternalOrderOperationService") as operation_service:
                    operation_service.return_value.query_registered_order = query_registered_order
                    response = client.get(
                        "/api/v1/tenant/external-sources/acg/orders/EXT-1?source_key=main",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(404, response.status_code)
        self.assertEqual("外部订单不存在", response.json()["detail"])
        self.assertEqual(1, session.commit_count)
        query_registered_order.assert_awaited_once_with(
            tenant_id=7,
            provider_name="acg",
            external_order_id="EXT-1",
            source_key="main",
            connection_id=None,
            runtime_auth=None,
        )

    def test_fetch_external_delivery_returns_safe_delivery_without_raw_payload(self) -> None:
        session = _FakeSession()
        fetch_registered_delivery = AsyncMock(return_value=_external_delivery())
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["external_sources:read"]))):
                with patch("app.web.tenant_admin.ExternalOrderOperationService") as operation_service:
                    operation_service.return_value.fetch_registered_delivery = fetch_registered_delivery
                    response = client.get(
                        "/api/v1/tenant/external-sources/acg/orders/EXT-1/delivery?source_key=main",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("acg", payload["provider_name"])
        self.assertEqual("EXT-1", payload["external_order_id"])
        self.assertEqual("card_pool", payload["delivery_type"])
        self.assertEqual(["card-a", "card-b"], payload["items"])
        self.assertEqual("已发货", payload["message"])
        self.assertNotIn("raw_payload", payload)
        self.assertNotIn("delivery-raw", str(payload))
        self.assertEqual(1, session.commit_count)
        fetch_registered_delivery.assert_awaited_once_with(
            tenant_id=7,
            provider_name="acg",
            external_order_id="EXT-1",
            source_key="main",
            connection_id=None,
            runtime_auth=None,
        )

    def test_external_order_operation_returns_502_for_provider_error(self) -> None:
        session = _FakeSession()
        create_registered_order = AsyncMock(
            side_effect=ExternalSourceError("upstream error api_key=plain-secret token=provider-token")
        )
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["external_sources:write"]))):
                with patch("app.web.tenant_admin.ExternalOrderOperationService") as operation_service:
                    operation_service.return_value.create_registered_order = create_registered_order
                    response = client.post(
                        "/api/v1/tenant/external-sources/acg/orders",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"external_product_id": "sku-1"},
                    )

        self.assertEqual(502, response.status_code)
        self.assertEqual("外部发卡源暂时不可用", response.json()["detail"])
        self.assertNotIn("api_key", response.text)
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("provider-token", response.text)
        self.assertNotIn("token", response.text.lower())
        self.assertNotIn("credentials", response.text)
        self.assertEqual(1, session.commit_count)

    def test_query_external_order_returns_redacted_502_for_provider_error(self) -> None:
        session = _FakeSession()
        query_registered_order = AsyncMock(
            side_effect=ExternalSourceError("upstream error Authorization=Bearer provider-secret")
        )
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["external_sources:read"]))):
                with patch("app.web.tenant_admin.ExternalOrderOperationService") as operation_service:
                    operation_service.return_value.query_registered_order = query_registered_order
                    response = client.get(
                        "/api/v1/tenant/external-sources/acg/orders/EXT-1?source_key=main",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(502, response.status_code)
        self.assertEqual("外部发卡源暂时不可用", response.json()["detail"])
        self.assertNotIn("Authorization", response.text)
        self.assertNotIn("provider-secret", response.text)
        self.assertNotIn("secret", response.text.lower())
        self.assertEqual(1, session.commit_count)

    def test_fetch_external_delivery_returns_redacted_502_for_provider_error(self) -> None:
        session = _FakeSession()
        fetch_registered_delivery = AsyncMock(
            side_effect=ExternalSourceError("upstream error card_secret=CARD-SECRET cookie=session")
        )
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["external_sources:read"]))):
                with patch("app.web.tenant_admin.ExternalOrderOperationService") as operation_service:
                    operation_service.return_value.fetch_registered_delivery = fetch_registered_delivery
                    response = client.get(
                        "/api/v1/tenant/external-sources/acg/orders/EXT-1/delivery?source_key=main",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(502, response.status_code)
        self.assertEqual("外部发卡源暂时不可用", response.json()["detail"])
        self.assertNotIn("card_secret", response.text)
        self.assertNotIn("CARD-SECRET", response.text)
        self.assertNotIn("cookie", response.text.lower())
        self.assertEqual(1, session.commit_count)

    def test_import_external_delivery_requires_write_scope_before_services(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["external_sources:read"]))):
                with patch("app.web.tenant_admin.ExternalOrderOperationService") as operation_service:
                    with patch("app.web.tenant_admin.ExternalDeliveryImportService") as import_service:
                        response = client.post(
                            "/api/v1/tenant/orders/ORD123/external-delivery/import",
                            headers={"X-API-Key": "fk_live_test"},
                            json={"provider_name": "acg", "external_order_id": "EXT-1"},
                        )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        operation_service.assert_not_called()
        import_service.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_import_external_delivery_uses_runtime_auth_and_redacts_response(self) -> None:
        session = _FakeSession()
        get_connection = AsyncMock(return_value=_connection_summary())
        load_runtime_credentials = AsyncMock(return_value=_runtime_auth())
        fetch_registered_delivery = AsyncMock(
            return_value=ExternalDelivery(
                provider="acg",
                external_order_id="EXT-1",
                delivery_type="card_pool",
                items=("card-secret-a", "card-secret-b"),
                message="internal message",
                raw_payload={"token": "provider-secret"},
            )
        )
        import_delivery = AsyncMock(
            return_value=ExternalDeliveryImportResult(
                out_trade_no="ORD123",
                order_status="paid",
                delivery_record_id=88,
                item_count=2,
                imported=True,
            )
        )
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["external_sources:write"]))):
                with patch("app.web.tenant_admin.ExternalSourceConnectionService") as connection_service:
                    with patch("app.web.tenant_admin.ExternalOrderOperationService") as operation_service:
                        with patch("app.web.tenant_admin.ExternalDeliveryImportService") as import_service_class:
                            connection_service.return_value.get_connection = get_connection
                            connection_service.return_value.load_runtime_credentials = load_runtime_credentials
                            operation_service.return_value.fetch_registered_delivery = fetch_registered_delivery
                            import_service_class.return_value.import_delivery = import_delivery
                            response = client.post(
                                "/api/v1/tenant/orders/ORD123/external-delivery/import",
                                headers={"X-API-Key": "fk_live_test"},
                                json={
                                    "provider_name": "acg",
                                    "external_order_id": "EXT-1",
                                    "connection_id": 12,
                                    "source_key": "main",
                                },
                            )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(
            {"out_trade_no", "order_status", "delivery_record_id", "item_count", "imported", "dry_run"},
            set(payload),
        )
        self.assertEqual("ORD123", payload["out_trade_no"])
        self.assertEqual("paid", payload["order_status"])
        self.assertEqual(88, payload["delivery_record_id"])
        self.assertEqual(2, payload["item_count"])
        self.assertTrue(payload["imported"])
        self.assertFalse(payload["dry_run"])
        self.assertNotIn("card-secret-a", response.text)
        self.assertNotIn("card-secret-b", response.text)
        self.assertNotIn("internal message", response.text)
        self.assertNotIn("raw_payload", response.text)
        self.assertNotIn("provider-secret", response.text)
        self.assertNotIn("credentials", response.text)
        self.assertNotIn("credentials_encrypted", response.text)
        self.assertNotIn("api_key", response.text)
        self.assertEqual(2, session.commit_count)
        get_connection.assert_awaited_once_with(session=session, tenant_id=7, connection_id=12)
        load_runtime_credentials.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            connection_id=12,
            settings=ANY,
        )
        fetch_registered_delivery.assert_awaited_once_with(
            tenant_id=7,
            provider_name="acg",
            external_order_id="EXT-1",
            source_key="main",
            connection_id=12,
            runtime_auth=load_runtime_credentials.return_value,
        )
        import_delivery.assert_awaited_once()
        import_kwargs = import_delivery.await_args.kwargs
        self.assertIs(session, import_kwargs["session"])
        self.assertEqual(7, import_kwargs["tenant_id"])
        self.assertEqual("ORD123", import_kwargs["out_trade_no"])
        self.assertEqual("acg", import_kwargs["provider_name"])
        self.assertEqual("main", import_kwargs["source_key"])
        self.assertIs(fetch_registered_delivery.return_value, import_kwargs["delivery"])
        self.assertFalse(import_kwargs["dry_run"])

    def test_import_external_delivery_dry_run_exposes_validation_result_without_sensitive_delivery(self) -> None:
        session = _FakeSession()
        fetch_registered_delivery = AsyncMock(
            return_value=ExternalDelivery(
                provider="acg",
                external_order_id="EXT-1",
                delivery_type="card_pool",
                items=("card-secret-a", "card-secret-b"),
                message="internal message",
                raw_payload={"token": "provider-secret"},
            )
        )
        import_delivery = AsyncMock(
            return_value=ExternalDeliveryImportResult(
                out_trade_no="ORD123",
                order_status="paid",
                delivery_record_id=None,
                item_count=2,
                imported=False,
                dry_run=True,
            )
        )
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["external_sources:write"]))):
                with patch("app.web.tenant_admin.ExternalOrderOperationService") as operation_service:
                    with patch("app.web.tenant_admin.ExternalDeliveryImportService") as import_service_class:
                        operation_service.return_value.fetch_registered_delivery = fetch_registered_delivery
                        import_service_class.return_value.import_delivery = import_delivery
                        response = client.post(
                            "/api/v1/tenant/orders/ORD123/external-delivery/import",
                            headers={"X-API-Key": "fk_live_test"},
                            json={
                                "provider_name": "acg",
                                "external_order_id": "EXT-1",
                                "source_key": "main",
                                "dry_run": True,
                            },
                        )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("ORD123", payload["out_trade_no"])
        self.assertEqual("paid", payload["order_status"])
        self.assertIsNone(payload["delivery_record_id"])
        self.assertEqual(2, payload["item_count"])
        self.assertFalse(payload["imported"])
        self.assertTrue(payload["dry_run"])
        self.assertNotIn("card-secret-a", response.text)
        self.assertNotIn("card-secret-b", response.text)
        self.assertNotIn("internal message", response.text)
        self.assertNotIn("provider-secret", response.text)
        self.assertNotIn("raw_payload", response.text)
        self.assertEqual(2, session.commit_count)
        import_delivery.assert_awaited_once()
        self.assertTrue(import_delivery.await_args.kwargs["dry_run"])

    def test_import_external_delivery_existing_record_response_exposes_reuse_flags(self) -> None:
        session = _FakeSession()
        fetch_registered_delivery = AsyncMock(
            return_value=ExternalDelivery(
                provider="acg",
                external_order_id="EXT-1",
                delivery_type="card_pool",
                items=("card-secret-a", "card-secret-b"),
                message="internal message",
                raw_payload={"token": "provider-secret"},
            )
        )
        import_delivery = AsyncMock(
            return_value=ExternalDeliveryImportResult(
                out_trade_no="ORD123",
                order_status="delivered",
                delivery_record_id=88,
                item_count=2,
                imported=False,
                dry_run=True,
            )
        )
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["external_sources:write"]))):
                with patch("app.web.tenant_admin.ExternalOrderOperationService") as operation_service:
                    with patch("app.web.tenant_admin.ExternalDeliveryImportService") as import_service_class:
                        operation_service.return_value.fetch_registered_delivery = fetch_registered_delivery
                        import_service_class.return_value.import_delivery = import_delivery
                        response = client.post(
                            "/api/v1/tenant/orders/ORD123/external-delivery/import",
                            headers={"X-API-Key": "fk_live_test"},
                            json={
                                "provider_name": "acg",
                                "external_order_id": "EXT-1",
                                "source_key": "main",
                                "dry_run": True,
                            },
                        )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("ORD123", payload["out_trade_no"])
        self.assertEqual("delivered", payload["order_status"])
        self.assertEqual(88, payload["delivery_record_id"])
        self.assertEqual(2, payload["item_count"])
        self.assertFalse(payload["imported"])
        self.assertTrue(payload["dry_run"])
        self.assertNotIn("card-secret-a", response.text)
        self.assertNotIn("card-secret-b", response.text)
        self.assertNotIn("internal message", response.text)
        self.assertNotIn("provider-secret", response.text)
        self.assertNotIn("raw_payload", response.text)
        self.assertEqual(2, session.commit_count)
        import_delivery.assert_awaited_once()
        self.assertTrue(import_delivery.await_args.kwargs["dry_run"])

    def test_import_external_delivery_returns_404_when_external_delivery_missing(self) -> None:
        session = _FakeSession()
        fetch_registered_delivery = AsyncMock(return_value=None)
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["external_sources:write"]))):
                with patch("app.web.tenant_admin.ExternalOrderOperationService") as operation_service:
                    with patch("app.web.tenant_admin.ExternalDeliveryImportService") as import_service:
                        operation_service.return_value.fetch_registered_delivery = fetch_registered_delivery
                        response = client.post(
                            "/api/v1/tenant/orders/ORD123/external-delivery/import",
                            headers={"X-API-Key": "fk_live_test"},
                            json={"provider_name": "acg", "external_order_id": "EXT-404", "source_key": "main"},
                        )

        self.assertEqual(404, response.status_code)
        self.assertEqual("外部发货不存在", response.json()["detail"])
        self.assertEqual(1, session.commit_count)
        fetch_registered_delivery.assert_awaited_once_with(
            tenant_id=7,
            provider_name="acg",
            external_order_id="EXT-404",
            source_key="main",
            connection_id=None,
            runtime_auth=None,
        )
        import_service.assert_not_called()

    def test_import_external_delivery_returns_redacted_502_for_provider_error(self) -> None:
        session = _FakeSession()
        fetch_registered_delivery = AsyncMock(
            side_effect=ExternalSourceError("upstream Authorization=Bearer token card_secret=CARD-SECRET")
        )
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["external_sources:write"]))):
                with patch("app.web.tenant_admin.ExternalOrderOperationService") as operation_service:
                    with patch("app.web.tenant_admin.ExternalDeliveryImportService") as import_service:
                        operation_service.return_value.fetch_registered_delivery = fetch_registered_delivery
                        response = client.post(
                            "/api/v1/tenant/orders/ORD123/external-delivery/import",
                            headers={"X-API-Key": "fk_live_test"},
                            json={"provider_name": "acg", "external_order_id": "EXT-1", "source_key": "main"},
                        )

        self.assertEqual(502, response.status_code)
        self.assertEqual("外部发货获取失败", response.json()["detail"])
        self.assertNotIn("Authorization", response.text)
        self.assertNotIn("token", response.text.lower())
        self.assertNotIn("CARD-SECRET", response.text)
        self.assertNotIn("card_secret", response.text)
        self.assertEqual(1, session.commit_count)
        import_service.assert_not_called()

    def test_import_external_delivery_maps_missing_local_order_to_404_without_commit(self) -> None:
        session = _FakeSession()
        fetch_registered_delivery = AsyncMock(return_value=_external_delivery())
        import_delivery = AsyncMock(side_effect=ValueError("订单不存在"))
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["external_sources:write"]))):
                with patch("app.web.tenant_admin.ExternalOrderOperationService") as operation_service:
                    with patch("app.web.tenant_admin.ExternalDeliveryImportService") as import_service_class:
                        operation_service.return_value.fetch_registered_delivery = fetch_registered_delivery
                        import_service_class.return_value.import_delivery = import_delivery
                        response = client.post(
                            "/api/v1/tenant/orders/ORD404/external-delivery/import",
                            headers={"X-API-Key": "fk_live_test"},
                            json={"provider_name": "acg", "external_order_id": "EXT-1", "source_key": "main"},
                        )

        self.assertEqual(404, response.status_code)
        self.assertEqual("订单不存在", response.json()["detail"])
        self.assertEqual(1, session.commit_count)
        import_delivery.assert_awaited_once()

    def test_import_external_delivery_maps_import_value_error_to_400_without_commit(self) -> None:
        session = _FakeSession()
        fetch_registered_delivery = AsyncMock(return_value=_external_delivery())
        import_delivery = AsyncMock(side_effect=ValueError("订单商品外部映射不匹配"))
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["external_sources:write"]))):
                with patch("app.web.tenant_admin.ExternalOrderOperationService") as operation_service:
                    with patch("app.web.tenant_admin.ExternalDeliveryImportService") as import_service_class:
                        operation_service.return_value.fetch_registered_delivery = fetch_registered_delivery
                        import_service_class.return_value.import_delivery = import_delivery
                        response = client.post(
                            "/api/v1/tenant/orders/ORD123/external-delivery/import",
                            headers={"X-API-Key": "fk_live_test"},
                            json={"provider_name": "acg", "external_order_id": "EXT-1", "source_key": "main"},
                        )

        self.assertEqual(400, response.status_code)
        self.assertEqual("订单商品外部映射不匹配", response.json()["detail"])
        self.assertEqual(1, session.commit_count)
        import_delivery.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
