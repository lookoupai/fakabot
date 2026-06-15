from __future__ import annotations

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
    from app.services.payments.configs import PaymentProviderSummary, USDT_TRC20_DIRECT_PROVIDER
    from app.services.payments.epay_compatible import EPAY_COMPATIBLE_PROVIDER, LEMZF_PROVIDER
    from app.services.payments.token188 import TOKEN188_PROVIDER
    from app.services.api_keys import ApiKeyService
    from app.web.tenant_admin import create_tenant_admin_router
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过 Tenant Admin 支付配置测试：{exc.name}") from exc


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
        scopes_json=scopes or ["payments:read", "payments:write"],
        ip_allowlist_json=[],
    )


def _authenticate(api_key: object):
    async def authenticate(self: ApiKeyService, session: object, plain_key: str) -> object | None:
        return api_key

    return authenticate


class TenantAdminPaymentConfigRouteTest(unittest.TestCase):
    def test_get_payment_config_requires_payments_read_scope_before_service(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:write"]))):
                with patch("app.web.tenant_admin.PaymentConfigService") as service:
                    response = client.get(
                        "/api/v1/tenant/payments/epusdt/config",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        service.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_get_payment_config_is_tenant_scoped_and_redacted(self) -> None:
        session = _FakeSession()
        get_status = AsyncMock(
            return_value=SimpleNamespace(
                enabled=True,
                scope_type="tenant",
                base_url="https://pay.example",
                pid="MERCHANT1234",
                token="USDT",
                network="TRC20",
                secret_configured=True,
            )
        )
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:read"]))):
                with patch("app.web.tenant_admin.PaymentConfigService") as service:
                    service.return_value.get_tenant_epusdt_status = get_status
                    response = client.get(
                        "/api/v1/tenant/payments/epusdt/config",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("epusdt_gmpay", payload["provider"])
        self.assertTrue(payload["enabled"])
        self.assertEqual("tenant", payload["scope_type"])
        self.assertEqual("https://pay.example", payload["base_url"])
        self.assertEqual("ME***34", payload["pid_masked"])
        self.assertEqual("USDT", payload["asset"])
        self.assertEqual("TRC20", payload["network"])
        self.assertTrue(payload["key_configured"])
        self.assertNotIn("MERCHANT1234", response.text)
        self.assertNotIn("secret_key", response.text)
        self.assertNotIn("config_encrypted", response.text)
        self.assertNotIn("credentials", response.text)
        self.assertNotIn("token", response.text.lower())
        self.assertEqual(1, session.commit_count)
        get_status.assert_awaited_once_with(session, ANY, 7)

    def test_update_payment_config_requires_payments_write_scope_before_service(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:read"]))):
                with patch("app.web.tenant_admin.PaymentConfigService") as service:
                    response = client.put(
                        "/api/v1/tenant/payments/epusdt/config",
                        headers={"X-API-Key": "fk_live_test"},
                        json=_update_payload(secret_key="plain-secret"),
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        service.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_update_payment_config_commits_and_returns_safe_payload(self) -> None:
        session = _FakeSession()
        upsert = AsyncMock(return_value=None)
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:write"]))):
                with patch("app.web.tenant_admin.PaymentConfigService") as service:
                    service.return_value.upsert_tenant_epusdt_config = upsert
                    response = client.put(
                        "/api/v1/tenant/payments/epusdt/config",
                        headers={"X-API-Key": "fk_live_test"},
                        json=_update_payload(),
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("epusdt_gmpay", payload["provider"])
        self.assertTrue(payload["enabled"])
        self.assertEqual("tenant", payload["scope_type"])
        self.assertEqual("https://pay.example", payload["base_url"])
        self.assertEqual("ME***34", payload["pid_masked"])
        self.assertEqual("USDT", payload["asset"])
        self.assertEqual("TRC20", payload["network"])
        self.assertTrue(payload["key_configured"])
        self.assertNotIn("MERCHANT1234", response.text)
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("secret_key", response.text)
        self.assertNotIn("config_encrypted", response.text)
        self.assertNotIn("token", response.text.lower())
        self.assertEqual(2, session.commit_count)
        upsert.assert_awaited_once()
        kwargs = upsert.await_args.kwargs
        self.assertIs(session, kwargs["session"])
        self.assertEqual(7, kwargs["tenant_id"])
        self.assertEqual("https://pay.example", kwargs["base_url"])
        self.assertEqual("MERCHANT1234", kwargs["pid"])
        self.assertEqual("plain-secret", kwargs["secret_key"])
        self.assertEqual("USDT", kwargs["token"])
        self.assertEqual("TRC20", kwargs["network"])

    def test_update_payment_config_value_error_returns_400_and_redacts_secret(self) -> None:
        session = _FakeSession()
        upsert = AsyncMock(side_effect=ValueError("secret=plain-secret"))
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:write"]))):
                with patch("app.web.tenant_admin.PaymentConfigService") as service:
                    service.return_value.upsert_tenant_epusdt_config = upsert
                    response = client.put(
                        "/api/v1/tenant/payments/epusdt/config",
                        headers={"X-API-Key": "fk_live_test"},
                        json=_update_payload(secret_key="plain-secret"),
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("支付配置参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("secret=", response.text)
        self.assertEqual(1, session.commit_count)

    def test_update_payment_config_rejects_unsafe_base_url_before_service(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:write"]))):
                with patch("app.web.tenant_admin.PaymentConfigService") as service:
                    response = client.put(
                        "/api/v1/tenant/payments/epusdt/config",
                        headers={"X-API-Key": "fk_live_test"},
                        json=_update_payload(
                            base_url="https://user:plain-secret@pay.example/path?token=plain-secret",
                            secret_key="plain-secret",
                        ),
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("支付配置参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("token=", response.text)
        service.return_value.upsert_tenant_epusdt_config.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_update_payment_config_missing_crypto_key_returns_503_without_route_commit(self) -> None:
        session = _FakeSession()
        upsert = AsyncMock(side_effect=RuntimeError("缺少 TOKEN_ENCRYPTION_KEY secret=plain-secret"))
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:write"]))):
                with patch("app.web.tenant_admin.PaymentConfigService") as service:
                    service.return_value.upsert_tenant_epusdt_config = upsert
                    response = client.put(
                        "/api/v1/tenant/payments/epusdt/config",
                        headers={"X-API-Key": "fk_live_test"},
                        json=_update_payload(secret_key="plain-secret"),
                    )

        self.assertEqual(503, response.status_code)
        self.assertEqual("支付配置暂不可用", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("TOKEN_ENCRYPTION_KEY", response.text)
        self.assertEqual(1, session.commit_count)

    def test_disable_payment_config_requires_payments_write_scope_before_service(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:read"]))):
                with patch("app.web.tenant_admin.PaymentConfigService") as service:
                    response = client.delete(
                        "/api/v1/tenant/payments/epusdt/config",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        service.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_disable_payment_config_commits_and_returns_safe_payload(self) -> None:
        session = _FakeSession()
        disable = AsyncMock(return_value=True)
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:write"]))):
                with patch("app.web.tenant_admin.PaymentConfigService") as service:
                    service.return_value.disable_tenant_epusdt_config = disable
                    response = client.delete(
                        "/api/v1/tenant/payments/epusdt/config",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        self.assertEqual({"provider": "epusdt_gmpay", "disabled": True}, response.json())
        self.assertEqual(2, session.commit_count)
        disable.assert_awaited_once_with(session, 7)

    def test_disable_payment_config_returns_404_for_missing_tenant_config(self) -> None:
        session = _FakeSession()
        disable = AsyncMock(return_value=False)
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:write"]))):
                with patch("app.web.tenant_admin.PaymentConfigService") as service:
                    service.return_value.disable_tenant_epusdt_config = disable
                    response = client.delete(
                        "/api/v1/tenant/payments/epusdt/config",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(404, response.status_code)
        self.assertEqual("租户 epusdt 配置不存在", response.json()["detail"])
        self.assertEqual(2, session.commit_count)

    def test_list_payment_providers_requires_payments_read_scope_before_payload(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:write"]))):
                with patch("app.web.tenant_admin.PaymentConfigService") as service:
                    response = client.get(
                        "/api/v1/tenant/payments/providers",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        service.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_list_payment_providers_returns_safe_capability_summary(self) -> None:
        session = _FakeSession()
        summaries = [
            PaymentProviderSummary(
                provider_name="epusdt_gmpay",
                display_name="epusdt GMPay",
                integration_kind="self_hosted_gateway",
                contract_name="epusdt_gmpay_v1",
                production_ready=False,
                staging_verified=False,
                tenant_configurable=True,
                platform_configurable=True,
                create_payment_available=True,
                callback_available=True,
                query_order_available=True,
                reconcile_available=True,
                offline_only=False,
                supported_assets=("USDT",),
                supported_networks=("TRC20",),
            ),
            PaymentProviderSummary(
                provider_name=TOKEN188_PROVIDER,
                display_name="TOKEN188",
                integration_kind="offline_payment_page",
                contract_name="token188_offline_page_v1",
                production_ready=False,
                staging_verified=False,
                tenant_configurable=True,
                platform_configurable=False,
                create_payment_available=True,
                callback_available=True,
                query_order_available=False,
                reconcile_available=False,
                offline_only=True,
                supported_assets=("USDT",),
                supported_networks=("TRX",),
            ),
        ]
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:read"]))):
                with patch("app.web.tenant_admin.PaymentConfigService") as service:
                    service.return_value.list_tenant_payment_provider_summaries = AsyncMock(return_value=summaries)
                    response = client.get(
                        "/api/v1/tenant/payments/providers",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(2, len(payload["providers"]))
        epusdt = payload["providers"][0]
        self.assertEqual("epusdt_gmpay", epusdt["provider_name"])
        self.assertEqual("self_hosted_gateway", epusdt["integration_kind"])
        self.assertTrue(epusdt["query_order_available"])
        self.assertTrue(epusdt["reconcile_available"])
        token188 = payload["providers"][1]
        self.assertEqual(TOKEN188_PROVIDER, token188["provider_name"])
        self.assertTrue(token188["offline_only"])
        self.assertFalse(token188["production_ready"])
        self.assertFalse(token188["staging_verified"])
        self.assertEqual(["USDT"], token188["supported_assets"])
        self.assertEqual(["TRX"], token188["supported_networks"])
        self.assertNotIn("gateway_url", response.text)
        self.assertNotIn("merchant_id", response.text)
        self.assertNotIn("monitor_address", response.text)
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("config_encrypted", response.text)

    def test_list_payment_providers_includes_offline_status_for_token188_epay_and_lemzf(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:read"]))):
                response = client.get(
                    "/api/v1/tenant/payments/providers",
                    headers={"X-API-Key": "fk_live_test"},
                )

        self.assertEqual(200, response.status_code)
        providers = {item["provider_name"]: item for item in response.json()["providers"]}
        for provider in (TOKEN188_PROVIDER, EPAY_COMPATIBLE_PROVIDER, LEMZF_PROVIDER):
            with self.subTest(provider=provider):
                self.assertTrue(providers[provider]["offline_only"])
                self.assertFalse(providers[provider]["query_order_available"])
                self.assertFalse(providers[provider]["reconcile_available"])
                self.assertFalse(providers[provider]["production_ready"])
                self.assertFalse(providers[provider]["staging_verified"])
        direct = providers[USDT_TRC20_DIRECT_PROVIDER]
        self.assertEqual("offline_direct_chain_config", direct["integration_kind"])
        self.assertEqual("usdt_trc20_direct_offline_config_v1", direct["contract_name"])
        self.assertTrue(direct["offline_only"])
        self.assertTrue(direct["create_payment_available"])
        self.assertFalse(direct["callback_available"])
        self.assertFalse(direct["query_order_available"])
        self.assertFalse(direct["reconcile_available"])
        self.assertEqual(["USDT"], direct["supported_assets"])
        self.assertEqual(["TRC20"], direct["supported_networks"])

    def test_list_payment_providers_does_not_claim_real_staging_or_unsupported_capabilities(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:read"]))):
                response = client.get(
                    "/api/v1/tenant/payments/providers",
                    headers={"X-API-Key": "fk_live_test"},
                )

        self.assertEqual(200, response.status_code)
        providers = {item["provider_name"]: item for item in response.json()["providers"]}
        for provider, summary in providers.items():
            with self.subTest(provider=provider):
                self.assertFalse(summary["production_ready"])
                self.assertFalse(summary["staging_verified"])
        for provider in (TOKEN188_PROVIDER, EPAY_COMPATIBLE_PROVIDER, LEMZF_PROVIDER):
            with self.subTest(provider=provider):
                summary = providers[provider]
                self.assertTrue(summary["offline_only"])
                self.assertTrue(summary["create_payment_available"])
                self.assertTrue(summary["callback_available"])
                self.assertFalse(summary["query_order_available"])
                self.assertFalse(summary["reconcile_available"])
        direct = providers[USDT_TRC20_DIRECT_PROVIDER]
        self.assertTrue(direct["offline_only"])
        self.assertTrue(direct["create_payment_available"])
        self.assertFalse(direct["callback_available"])
        self.assertFalse(direct["query_order_available"])
        self.assertFalse(direct["reconcile_available"])

    def test_list_payment_providers_does_not_expose_credentials_or_gateway_values(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:read"]))):
                response = client.get(
                    "/api/v1/tenant/payments/providers",
                    headers={"X-API-Key": "fk_live_test"},
                )

        self.assertEqual(200, response.status_code)
        forbidden = (
            "gateway_url",
            "return_url",
            "merchant_id",
            "pid",
            "monitor_address",
            "provider_trade_no",
            "signature",
            "signing_text",
            "secret",
            "secret_key",
            "api_key",
            "password",
            "credentials",
            "config_encrypted",
            "raw_payload",
        )
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, response.text)
        for item in response.json()["providers"]:
            self.assertNotIn("token", item)

    def test_get_generic_payment_config_requires_payments_read_scope_before_service(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:write"]))):
                with patch("app.web.tenant_admin.PaymentConfigService") as service:
                    response = client.get(
                        f"/api/v1/tenant/payments/{TOKEN188_PROVIDER}/config",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        service.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_get_generic_payment_config_is_tenant_scoped_and_redacted_for_token188(self) -> None:
        session = _FakeSession()
        get_status = AsyncMock(
            return_value=SimpleNamespace(
                provider=TOKEN188_PROVIDER,
                enabled=True,
                scope_type="tenant",
                gateway_url="https://pay.example/",
                merchant_id="MERCHANT1234",
                monitor_address="TADDRESS1234",
                asset=None,
                network=None,
                chain_type="TRX",
                payment_type=None,
                device=None,
                subject=None,
                return_url="https://store.example/",
                key_configured=True,
            )
        )
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:read"]))):
                with patch("app.web.tenant_admin.PaymentConfigService") as service:
                    service.return_value.get_tenant_payment_config_status = get_status
                    response = client.get(
                        f"/api/v1/tenant/payments/{TOKEN188_PROVIDER}/config",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(TOKEN188_PROVIDER, payload["provider"])
        self.assertEqual("ME***34", payload["merchant_id_masked"])
        self.assertEqual("TA***34", payload["monitor_address_masked"])
        self.assertEqual("TRX", payload["chain_type"])
        self.assertTrue(payload["return_url_configured"])
        self.assertTrue(payload["key_configured"])
        self.assertNotIn("MERCHANT1234", response.text)
        self.assertNotIn("TADDRESS1234", response.text)
        self.assertNotIn("secret", response.text.lower())
        self.assertNotIn("config_encrypted", response.text)
        get_status.assert_awaited_once_with(session, ANY, 7, TOKEN188_PROVIDER)

    def test_get_trc20_direct_config_is_tenant_scoped_and_redacted(self) -> None:
        session = _FakeSession()
        get_status = AsyncMock(
            return_value=SimpleNamespace(
                provider=USDT_TRC20_DIRECT_PROVIDER,
                enabled=True,
                scope_type="tenant",
                gateway_url=None,
                merchant_id=None,
                monitor_address="T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
                asset="USDT",
                network="TRC20",
                chain_type=None,
                payment_type=None,
                device=None,
                subject=None,
                return_url=None,
                cny_per_usdt="7.25",
                min_usdt_amount="2.50",
                timeout_seconds=7200,
                key_configured=False,
            )
        )
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:read"]))):
                with patch("app.web.tenant_admin.PaymentConfigService") as service:
                    service.return_value.get_tenant_payment_config_status = get_status
                    response = client.get(
                        f"/api/v1/tenant/payments/{USDT_TRC20_DIRECT_PROVIDER}/config",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(USDT_TRC20_DIRECT_PROVIDER, payload["provider"])
        self.assertEqual("T9***wb", payload["monitor_address_masked"])
        self.assertEqual("USDT", payload["asset"])
        self.assertEqual("TRC20", payload["network"])
        self.assertEqual("7.25", payload["cny_per_usdt"])
        self.assertEqual("2.50", payload["min_usdt_amount"])
        self.assertEqual(7200, payload["timeout_seconds"])
        self.assertFalse(payload["key_configured"])
        self.assertNotIn("T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb", response.text)
        self.assertNotIn("secret", response.text.lower())
        self.assertNotIn("config_encrypted", response.text)
        get_status.assert_awaited_once_with(session, ANY, 7, USDT_TRC20_DIRECT_PROVIDER)

    def test_update_token188_config_commits_and_returns_safe_payload(self) -> None:
        self._assert_generic_update_commits_and_returns_safe_payload(
            provider=TOKEN188_PROVIDER,
            request_payload=_token188_payload(key="plain-secret"),
            status=SimpleNamespace(
                provider=TOKEN188_PROVIDER,
                enabled=True,
                scope_type="tenant",
                gateway_url="https://pay.example/",
                merchant_id="MERCHANT1234",
                monitor_address="TADDRESS1234",
                asset=None,
                network=None,
                chain_type="TRX",
                payment_type=None,
                device=None,
                subject=None,
                return_url=None,
                key_configured=True,
            ),
            forbidden=("MERCHANT1234", "TADDRESS1234", "plain-secret"),
        )

    def test_update_epay_compatible_config_commits_and_returns_safe_payload(self) -> None:
        self._assert_generic_update_commits_and_returns_safe_payload(
            provider=EPAY_COMPATIBLE_PROVIDER,
            request_payload=_epay_payload(key="plain-secret"),
            status=SimpleNamespace(
                provider=EPAY_COMPATIBLE_PROVIDER,
                enabled=True,
                scope_type="tenant",
                gateway_url="https://pay.example/submit.php",
                merchant_id="MERCHANT1234",
                monitor_address=None,
                asset=None,
                network=None,
                chain_type=None,
                payment_type="alipay",
                device="mobile",
                subject="Shop Order",
                return_url=None,
                key_configured=True,
            ),
            forbidden=("MERCHANT1234", "plain-secret"),
        )

    def test_update_lemzf_config_commits_and_returns_safe_payload(self) -> None:
        self._assert_generic_update_commits_and_returns_safe_payload(
            provider=LEMZF_PROVIDER,
            request_payload=_epay_payload(key="plain-secret"),
            status=SimpleNamespace(
                provider=LEMZF_PROVIDER,
                enabled=True,
                scope_type="tenant",
                gateway_url="https://pay.example/submit.php",
                merchant_id="MERCHANT1234",
                monitor_address=None,
                asset=None,
                network=None,
                chain_type=None,
                payment_type="alipay",
                device="mobile",
                subject="Shop Order",
                return_url=None,
                key_configured=True,
            ),
            forbidden=("MERCHANT1234", "plain-secret"),
        )

    def test_update_trc20_direct_config_commits_and_returns_masked_address_without_key(self) -> None:
        session = _FakeSession()
        upsert = AsyncMock(
            return_value=SimpleNamespace(
                provider=USDT_TRC20_DIRECT_PROVIDER,
                enabled=True,
                scope_type="tenant",
                gateway_url=None,
                merchant_id=None,
                monitor_address="T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
                asset="USDT",
                network="TRC20",
                chain_type=None,
                payment_type=None,
                device=None,
                subject=None,
                return_url=None,
                cny_per_usdt="7.25",
                min_usdt_amount="2.50",
                timeout_seconds=7200,
                key_configured=False,
            )
        )
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:write"]))):
                with patch("app.web.tenant_admin.PaymentConfigService") as service:
                    service.return_value.upsert_tenant_payment_config = upsert
                    response = client.put(
                        f"/api/v1/tenant/payments/{USDT_TRC20_DIRECT_PROVIDER}/config",
                        headers={"X-API-Key": "fk_live_test"},
                        json=_trc20_direct_payload(),
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(USDT_TRC20_DIRECT_PROVIDER, payload["provider"])
        self.assertTrue(payload["enabled"])
        self.assertEqual("tenant", payload["scope_type"])
        self.assertEqual("T9***wb", payload["monitor_address_masked"])
        self.assertEqual("USDT", payload["asset"])
        self.assertEqual("TRC20", payload["network"])
        self.assertEqual("7.25", payload["cny_per_usdt"])
        self.assertEqual("2.50", payload["min_usdt_amount"])
        self.assertEqual(7200, payload["timeout_seconds"])
        self.assertFalse(payload["key_configured"])
        self.assertNotIn("T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb", response.text)
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("config_encrypted", response.text)
        self.assertEqual(2, session.commit_count)
        upsert.assert_awaited_once()
        kwargs = upsert.await_args.kwargs
        self.assertIs(session, kwargs["session"])
        self.assertEqual(7, kwargs["tenant_id"])
        self.assertEqual(USDT_TRC20_DIRECT_PROVIDER, kwargs["provider"])
        self.assertEqual(_trc20_direct_payload(), kwargs["config_payload"])

    def test_update_payment_provider_config_rejects_unsupported_provider_before_service(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:write"]))):
                with patch("app.web.tenant_admin.PaymentConfigService") as service:
                    response = client.put(
                        "/api/v1/tenant/payments/unknown/config",
                        headers={"X-API-Key": "fk_live_test"},
                        json=_token188_payload(key="plain-secret"),
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("支付配置参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        service.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_update_payment_provider_config_rejects_unsafe_gateway_url_before_service(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:write"]))):
                with patch("app.web.tenant_admin.PaymentConfigService") as service:
                    response = client.put(
                        f"/api/v1/tenant/payments/{TOKEN188_PROVIDER}/config",
                        headers={"X-API-Key": "fk_live_test"},
                        json=_token188_payload(
                            gateway_url="https://pay.example/?key=plain-secret",
                            key="plain-secret",
                        ),
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("支付配置参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        service.return_value.upsert_tenant_payment_config.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_update_trc20_direct_config_rejects_unsupported_sensitive_fields_before_service(self) -> None:
        for field_name in ("gateway_url", "key", "secret_key", "tron_api_key"):
            with self.subTest(field=field_name):
                session = _FakeSession()
                client = _client(Settings())

                with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
                    with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:write"]))):
                        with patch("app.web.tenant_admin.PaymentConfigService") as service:
                            payload = dict(_trc20_direct_payload())
                            payload[field_name] = "https://pay.example/?token=plain-secret" if field_name == "gateway_url" else "plain-secret"
                            response = client.put(
                                f"/api/v1/tenant/payments/{USDT_TRC20_DIRECT_PROVIDER}/config",
                                headers={"X-API-Key": "fk_live_test"},
                                json=payload,
                            )

                self.assertEqual(400, response.status_code)
                self.assertEqual("支付配置参数无效", response.json()["detail"])
                self.assertNotIn("plain-secret", response.text)
                service.return_value.upsert_tenant_payment_config.assert_not_called()
                self.assertEqual(1, session.commit_count)

    def test_update_payment_provider_config_value_error_returns_400_and_redacts_secret(self) -> None:
        session = _FakeSession()
        upsert = AsyncMock(side_effect=ValueError("key=plain-secret"))
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:write"]))):
                with patch("app.web.tenant_admin.PaymentConfigService") as service:
                    service.return_value.upsert_tenant_payment_config = upsert
                    response = client.put(
                        f"/api/v1/tenant/payments/{TOKEN188_PROVIDER}/config",
                        headers={"X-API-Key": "fk_live_test"},
                        json=_token188_payload(key="plain-secret"),
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("支付配置参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("key=", response.text)
        self.assertEqual(1, session.commit_count)

    def _assert_generic_update_commits_and_returns_safe_payload(
        self,
        *,
        provider: str,
        request_payload: dict[str, str],
        status: SimpleNamespace,
        forbidden: tuple[str, ...],
    ) -> None:
        session = _FakeSession()
        upsert = AsyncMock(return_value=status)
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:write"]))):
                with patch("app.web.tenant_admin.PaymentConfigService") as service:
                    service.return_value.upsert_tenant_payment_config = upsert
                    response = client.put(
                        f"/api/v1/tenant/payments/{provider}/config",
                        headers={"X-API-Key": "fk_live_test"},
                        json=request_payload,
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(provider, payload["provider"])
        self.assertTrue(payload["enabled"])
        self.assertEqual("tenant", payload["scope_type"])
        self.assertTrue(payload["key_configured"])
        for value in forbidden:
            self.assertNotIn(value, response.text)
        self.assertNotIn("config_encrypted", response.text)
        self.assertEqual(2, session.commit_count)
        upsert.assert_awaited_once()
        kwargs = upsert.await_args.kwargs
        self.assertIs(session, kwargs["session"])
        self.assertEqual(7, kwargs["tenant_id"])
        self.assertEqual(provider, kwargs["provider"])


def _update_payload(
    *,
    base_url: str = " https://pay.example/ ",
    secret_key: str = "plain-secret",
) -> dict[str, str]:
    return {
        "base_url": base_url,
        "pid": " MERCHANT1234 ",
        "secret_key": f" {secret_key} ",
        "token": " USDT ",
        "network": " TRC20 ",
    }


def _token188_payload(
    *,
    gateway_url: str = " https://pay.example/ ",
    key: str = "plain-secret",
) -> dict[str, str]:
    return {
        "gateway_url": gateway_url,
        "merchant_id": " MERCHANT1234 ",
        "key": f" {key} ",
        "monitor_address": " TADDRESS1234 ",
        "chain_type": " TRX ",
    }


def _epay_payload(*, key: str = "plain-secret") -> dict[str, str]:
    return {
        "gateway_url": " https://pay.example/submit.php ",
        "merchant_id": " MERCHANT1234 ",
        "key": f" {key} ",
        "payment_type": " alipay ",
        "device": " mobile ",
        "subject": " Shop Order ",
    }


def _trc20_direct_payload() -> dict[str, object]:
    return {
        "monitor_address": "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
        "token": "USDT",
        "network": "TRC20",
        "cny_per_usdt": "7.25",
        "min_usdt_amount": "2.50",
        "timeout_seconds": 7200,
    }


if __name__ == "__main__":
    unittest.main()
