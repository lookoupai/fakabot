from __future__ import annotations

from datetime import datetime, timezone
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
    from app.services.external_sources import ExternalSourceError, ExternalSourceRuntimeCredentials
    from app.services.external_sources.sync import ExternalCatalogSyncResult, SyncedExternalProduct
    from app.web.tenant_admin import create_tenant_admin_router
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过 Tenant Admin 外部目录同步测试：{exc.name}") from exc


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
        scopes_json=scopes or ["products:write"],
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


def _sync_result(*, next_cursor: str | None = "next-page") -> ExternalCatalogSyncResult:
    return ExternalCatalogSyncResult(
        created_count=1,
        updated_count=0,
        skipped_count=0,
        next_cursor=next_cursor,
        products=[
            SyncedExternalProduct(
                product_id=42,
                external_source="acg",
                source_key="main",
                external_id="sku-1",
                action="created",
                status="on",
            )
        ],
    )


class TenantAdminExternalCatalogSyncRouteTest(unittest.TestCase):
    def test_sync_external_catalog_requires_products_write_scope_before_services(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["products:read"]))):
                with patch("app.web.tenant_admin.ExternalSourceConnectionService") as connection_service:
                    with patch("app.web.tenant_admin.ExternalCatalogSyncService") as sync_service:
                        response = client.post(
                            "/api/v1/tenant/external-sources/acg/catalog/sync",
                            headers={"X-API-Key": "fk_live_test"},
                            json={"source_key": "main"},
                        )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        connection_service.assert_not_called()
        sync_service.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_sync_external_catalog_uses_tenant_connection_and_passes_sync_arguments(self) -> None:
        session = _FakeSession()
        get_connection = AsyncMock(return_value=_connection_summary())
        load_runtime_credentials = AsyncMock(return_value=_runtime_auth())
        sync_registered_catalog = AsyncMock(return_value=_sync_result())
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7))):
                with patch("app.web.tenant_admin.ExternalSourceConnectionService") as connection_service:
                    with patch("app.web.tenant_admin.ExternalCatalogSyncService") as sync_service:
                        connection_service.return_value.get_connection = get_connection
                        connection_service.return_value.load_runtime_credentials = load_runtime_credentials
                        sync_service.return_value.sync_registered_catalog = sync_registered_catalog
                        response = client.post(
                            "/api/v1/tenant/external-sources/acg/catalog/sync",
                            headers={"X-API-Key": "fk_live_test"},
                            json={
                                "connection_id": 12,
                                "cursor": "cursor-1",
                                "limit": 25,
                                "max_pages": 3,
                            },
                        )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("acg", payload["provider_name"])
        self.assertEqual("main", payload["source_key"])
        self.assertEqual(12, payload["connection_id"])
        self.assertEqual(1, payload["created_count"])
        self.assertEqual("next-page", payload["next_cursor"])
        self.assertEqual("sku-1", payload["products"][0]["external_id"])
        self.assertNotIn("credentials", payload)
        self.assertNotIn("credentials_encrypted", payload)
        self.assertNotIn("plain-secret", str(payload))
        self.assertNotIn("correct-secret", str(payload))
        self.assertNotIn("encrypted-secret", str(payload))
        self.assertNotIn("api_key", str(payload))
        self.assertEqual(2, session.commit_count)
        get_connection.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            connection_id=12,
        )
        load_runtime_credentials.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            connection_id=12,
            settings=ANY,
        )
        sync_registered_catalog.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            provider_name="acg",
            source_key="main",
            connection_id=12,
            cursor="cursor-1",
            limit=25,
            max_pages=3,
            runtime_auth=load_runtime_credentials.return_value,
        )

    def test_sync_external_catalog_rejects_invalid_provider_name_before_services(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7))):
                with patch("app.web.tenant_admin.ExternalSourceConnectionService") as connection_service:
                    with patch("app.web.tenant_admin.ExternalCatalogSyncService") as sync_service:
                        response = client.post(
                            "/api/v1/tenant/external-sources/ACG/catalog/sync",
                            headers={"X-API-Key": "fk_live_test"},
                            json={"source_key": "main"},
                        )

        self.assertEqual(400, response.status_code)
        self.assertIn("provider_name", response.json()["detail"])
        connection_service.assert_not_called()
        sync_service.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_sync_external_catalog_product_requires_products_write_scope_before_services(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["products:read"]))):
                with patch("app.web.tenant_admin.ExternalSourceConnectionService") as connection_service:
                    with patch("app.web.tenant_admin.ExternalCatalogSyncService") as sync_service:
                        response = client.post(
                            "/api/v1/tenant/external-sources/acg/catalog/products/sync",
                            headers={"X-API-Key": "fk_live_test"},
                            json={"external_product_id": "sku-1", "source_key": "main"},
                        )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        connection_service.assert_not_called()
        sync_service.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_sync_external_catalog_product_uses_tenant_connection_and_passes_sync_arguments(self) -> None:
        session = _FakeSession()
        get_connection = AsyncMock(return_value=_connection_summary())
        load_runtime_credentials = AsyncMock(return_value=_runtime_auth())
        sync_registered_product = AsyncMock(return_value=_sync_result(next_cursor=None))
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7))):
                with patch("app.web.tenant_admin.ExternalSourceConnectionService") as connection_service:
                    with patch("app.web.tenant_admin.ExternalCatalogSyncService") as sync_service:
                        connection_service.return_value.get_connection = get_connection
                        connection_service.return_value.load_runtime_credentials = load_runtime_credentials
                        sync_service.return_value.sync_registered_product = sync_registered_product
                        response = client.post(
                            "/api/v1/tenant/external-sources/acg/catalog/products/sync",
                            headers={"X-API-Key": "fk_live_test"},
                            json={"external_product_id": "sku-1", "connection_id": 12},
                        )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("acg", payload["provider_name"])
        self.assertEqual("main", payload["source_key"])
        self.assertEqual(12, payload["connection_id"])
        self.assertEqual(1, payload["created_count"])
        self.assertIsNone(payload["next_cursor"])
        self.assertEqual("sku-1", payload["products"][0]["external_id"])
        self.assertNotIn("credentials", payload)
        self.assertNotIn("credentials_encrypted", payload)
        self.assertNotIn("plain-secret", str(payload))
        self.assertNotIn("correct-secret", str(payload))
        self.assertNotIn("encrypted-secret", str(payload))
        self.assertNotIn("api_key", str(payload))
        self.assertEqual(2, session.commit_count)
        get_connection.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            connection_id=12,
        )
        load_runtime_credentials.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            connection_id=12,
            settings=ANY,
        )
        sync_registered_product.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            provider_name="acg",
            external_product_id="sku-1",
            source_key="main",
            connection_id=12,
            runtime_auth=load_runtime_credentials.return_value,
        )
        sync_service.return_value.sync_registered_catalog.assert_not_called()

    def test_sync_external_catalog_returns_404_for_missing_or_cross_tenant_connection(self) -> None:
        session = _FakeSession()
        get_connection = AsyncMock(return_value=None)
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7))):
                with patch("app.web.tenant_admin.ExternalSourceConnectionService") as connection_service:
                    with patch("app.web.tenant_admin.ExternalCatalogSyncService") as sync_service:
                        connection_service.return_value.get_connection = get_connection
                        response = client.post(
                            "/api/v1/tenant/external-sources/acg/catalog/sync",
                            headers={"X-API-Key": "fk_live_test"},
                            json={"connection_id": 12},
                        )

        self.assertEqual(404, response.status_code)
        self.assertEqual("外部源连接不存在", response.json()["detail"])
        self.assertEqual(1, session.commit_count)
        get_connection.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            connection_id=12,
        )
        sync_service.return_value.sync_registered_catalog.assert_not_called()

    def test_sync_external_catalog_product_returns_404_for_missing_or_cross_tenant_connection(self) -> None:
        session = _FakeSession()
        get_connection = AsyncMock(return_value=None)
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7))):
                with patch("app.web.tenant_admin.ExternalSourceConnectionService") as connection_service:
                    with patch("app.web.tenant_admin.ExternalCatalogSyncService") as sync_service:
                        connection_service.return_value.get_connection = get_connection
                        response = client.post(
                            "/api/v1/tenant/external-sources/acg/catalog/products/sync",
                            headers={"X-API-Key": "fk_live_test"},
                            json={"external_product_id": "sku-1", "connection_id": 12},
                        )

        self.assertEqual(404, response.status_code)
        self.assertEqual("外部源连接不存在", response.json()["detail"])
        self.assertEqual(1, session.commit_count)
        get_connection.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            connection_id=12,
        )
        sync_service.return_value.sync_registered_product.assert_not_called()

    def test_sync_external_catalog_rejects_disabled_connection_before_sync(self) -> None:
        response, session, sync_service = self._post_with_connection(_connection_summary(status="disabled"))

        self.assertEqual(400, response.status_code)
        self.assertEqual("外部源连接未启用", response.json()["detail"])
        self.assertEqual(1, session.commit_count)
        sync_service.return_value.sync_registered_catalog.assert_not_called()

    def test_sync_external_catalog_rejects_provider_mismatch_before_sync(self) -> None:
        response, session, sync_service = self._post_with_connection(_connection_summary(provider_name="other"))

        self.assertEqual(400, response.status_code)
        self.assertEqual("外部源连接 provider 与路径不一致", response.json()["detail"])
        self.assertEqual(1, session.commit_count)
        sync_service.return_value.sync_registered_catalog.assert_not_called()

    def test_sync_external_catalog_rejects_source_key_mismatch_before_sync(self) -> None:
        response, session, sync_service = self._post_with_connection(
            _connection_summary(source_key="main"),
            payload={"connection_id": 12, "source_key": "backup"},
        )

        self.assertEqual(400, response.status_code)
        self.assertEqual("请求 source_key 与外部源连接不一致", response.json()["detail"])
        self.assertEqual(1, session.commit_count)
        sync_service.return_value.sync_registered_catalog.assert_not_called()

    def test_sync_external_catalog_rejects_invalid_connection_source_key_before_sync(self) -> None:
        response, session, sync_service = self._post_with_connection(
            _connection_summary(source_key="main"),
            payload={"connection_id": 12, "source_key": "Shop A"},
        )

        self.assertEqual(400, response.status_code)
        self.assertIn("source_key", response.json()["detail"])
        self.assertEqual(1, session.commit_count)
        sync_service.return_value.sync_registered_catalog.assert_not_called()

    def test_sync_external_catalog_product_rejects_connection_before_sync(self) -> None:
        invalid_connections = [
            (_connection_summary(status="disabled"), "外部源连接未启用"),
            (_connection_summary(provider_name="other"), "外部源连接 provider 与路径不一致"),
            (_connection_summary(source_key="main"), "请求 source_key 与外部源连接不一致"),
        ]
        payloads = [
            {"external_product_id": "sku-1", "connection_id": 12},
            {"external_product_id": "sku-1", "connection_id": 12},
            {"external_product_id": "sku-1", "connection_id": 12, "source_key": "backup"},
        ]
        for (connection, error_message), payload in zip(invalid_connections, payloads):
            with self.subTest(error_message=error_message):
                response, session, sync_service = self._post_product_with_connection(connection, payload=payload)

                self.assertEqual(400, response.status_code)
                self.assertEqual(error_message, response.json()["detail"])
                self.assertEqual(1, session.commit_count)
                sync_service.return_value.sync_registered_product.assert_not_called()

    def test_sync_external_catalog_returns_502_for_provider_contract_error(self) -> None:
        session = _FakeSession()
        sync_registered_catalog = AsyncMock(
            side_effect=ExternalSourceError("upstream error api_key=plain-secret token=provider-token")
        )
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7))):
                with patch("app.web.tenant_admin.ExternalCatalogSyncService") as sync_service:
                    sync_service.return_value.sync_registered_catalog = sync_registered_catalog
                    response = client.post(
                        "/api/v1/tenant/external-sources/acg/catalog/sync",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"source_key": "main"},
                    )

        self.assertEqual(502, response.status_code)
        self.assertEqual("外部发卡源暂时不可用", response.json()["detail"])
        self.assertNotIn("api_key", response.text)
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("provider-token", response.text)
        self.assertNotIn("token", response.text.lower())
        self.assertNotIn("credentials", response.text)
        self.assertNotIn("encrypted-secret", response.text)
        self.assertEqual(1, session.commit_count)
        sync_registered_catalog.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            provider_name="acg",
            source_key="main",
            connection_id=None,
            cursor=None,
            limit=50,
            max_pages=1,
            runtime_auth=None,
        )

    def test_sync_external_catalog_product_returns_502_for_provider_contract_error(self) -> None:
        session = _FakeSession()
        sync_registered_product = AsyncMock(
            side_effect=ExternalSourceError("upstream error secret=provider-secret cookie=session")
        )
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7))):
                with patch("app.web.tenant_admin.ExternalCatalogSyncService") as sync_service:
                    sync_service.return_value.sync_registered_product = sync_registered_product
                    response = client.post(
                        "/api/v1/tenant/external-sources/acg/catalog/products/sync",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"external_product_id": "sku-1", "source_key": "main"},
                    )

        self.assertEqual(502, response.status_code)
        self.assertEqual("外部发卡源暂时不可用", response.json()["detail"])
        self.assertNotIn("secret", response.text.lower())
        self.assertNotIn("provider-secret", response.text)
        self.assertNotIn("cookie", response.text.lower())
        self.assertNotIn("credentials", response.text)
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("encrypted-secret", response.text)
        self.assertEqual(1, session.commit_count)
        sync_registered_product.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            provider_name="acg",
            external_product_id="sku-1",
            source_key="main",
            connection_id=None,
            runtime_auth=None,
        )

    def _post_with_connection(
        self,
        connection: SimpleNamespace,
        *,
        payload: dict[str, object] | None = None,
    ) -> tuple[object, _FakeSession, object]:
        session = _FakeSession()
        get_connection = AsyncMock(return_value=connection)
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7))):
                with patch("app.web.tenant_admin.ExternalSourceConnectionService") as connection_service:
                    with patch("app.web.tenant_admin.ExternalCatalogSyncService") as sync_service:
                        connection_service.return_value.get_connection = get_connection
                        response = client.post(
                            "/api/v1/tenant/external-sources/acg/catalog/sync",
                            headers={"X-API-Key": "fk_live_test"},
                            json=payload or {"connection_id": 12},
                        )

        get_connection.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            connection_id=12,
        )
        return response, session, sync_service

    def _post_product_with_connection(
        self,
        connection: SimpleNamespace,
        *,
        payload: dict[str, object] | None = None,
    ) -> tuple[object, _FakeSession, object]:
        session = _FakeSession()
        get_connection = AsyncMock(return_value=connection)
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7))):
                with patch("app.web.tenant_admin.ExternalSourceConnectionService") as connection_service:
                    with patch("app.web.tenant_admin.ExternalCatalogSyncService") as sync_service:
                        connection_service.return_value.get_connection = get_connection
                        response = client.post(
                            "/api/v1/tenant/external-sources/acg/catalog/products/sync",
                            headers={"X-API-Key": "fk_live_test"},
                            json=payload or {"external_product_id": "sku-1", "connection_id": 12},
                        )
        return response, session, sync_service


if __name__ == "__main__":
    unittest.main()
