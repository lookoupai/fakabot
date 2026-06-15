from __future__ import annotations

import logging
from types import SimpleNamespace
import unittest
import warnings
from unittest.mock import patch

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
    from app.services.external_sources import MCY_SHOP_PROVIDER, STANDARD_HTTP_PROVIDER, register_builtin_external_providers
    import app.services.external_sources.registry as provider_registry
    from app.web.tenant_admin import create_tenant_admin_router
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过 Tenant Admin 外部源列表测试：{exc.name}") from exc


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
        scopes_json=scopes or ["products:read"],
        ip_allowlist_json=[],
    )


def _authenticate(api_key: object):
    async def authenticate(self: ApiKeyService, session: object, plain_key: str) -> object | None:
        return api_key

    return authenticate


class TenantAdminExternalSourcesProviderListTest(unittest.TestCase):
    def test_list_external_sources_includes_builtin_standard_http_without_credentials(self) -> None:
        previous_providers = dict(provider_registry._providers)
        provider_registry._providers.clear()
        session = _FakeSession()
        client = _client(Settings())
        try:
            register_builtin_external_providers()
            with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
                with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key())):
                    response = client.get(
                        "/api/v1/tenant/external-sources",
                        headers={"X-API-Key": "fk_live_test"},
                    )
        finally:
            provider_registry._providers.clear()
            provider_registry._providers.update(previous_providers)

        self.assertEqual(200, response.status_code)
        payload = response.json()
        providers = {item["provider_name"]: item for item in payload["providers"]}
        self.assertIn(STANDARD_HTTP_PROVIDER, providers)
        self.assertIn(MCY_SHOP_PROVIDER, providers)
        standard = providers[STANDARD_HTTP_PROVIDER]
        self.assertEqual("generic_http_json", standard["integration_kind"])
        self.assertEqual("standard_http_json_v1", standard["contract_name"])
        self.assertFalse(standard["production_ready"])
        self.assertFalse(standard["staging_verified"])
        self.assertTrue(standard["catalog_context_available"])
        self.assertTrue(standard["catalog_product_context_available"])
        self.assertTrue(standard["order_context_available"])
        self.assertTrue(standard["delivery_context_available"])
        self.assertFalse(standard["auto_fulfillment_idempotent_available"])
        mcy_shop = providers[MCY_SHOP_PROVIDER]
        self.assertEqual("offline_fixture", mcy_shop["integration_kind"])
        self.assertEqual("mcy_shop_offline_fixture_v1", mcy_shop["contract_name"])
        self.assertFalse(mcy_shop["production_ready"])
        self.assertFalse(mcy_shop["staging_verified"])
        self.assertTrue(mcy_shop["catalog_context_available"])
        self.assertTrue(mcy_shop["catalog_product_context_available"])
        self.assertTrue(mcy_shop["order_context_available"])
        self.assertTrue(mcy_shop["delivery_context_available"])
        self.assertFalse(mcy_shop["auto_fulfillment_idempotent_available"])
        self.assertNotIn("credentials", response.text)
        self.assertNotIn("api_key", response.text)
        self.assertNotIn("secret", response.text)
        self.assertEqual(1, session.commit_count)

    def test_list_external_sources_requires_products_read_scope_before_provider_payload(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["orders:read"]))):
                response = client.get(
                    "/api/v1/tenant/external-sources",
                    headers={"X-API-Key": "fk_live_test"},
                )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        self.assertEqual(1, session.commit_count)


if __name__ == "__main__":
    unittest.main()
