from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import warnings
from unittest.mock import AsyncMock, MagicMock, patch

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)
logging.getLogger("httpx").setLevel(logging.WARNING)

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.services.admin_web import (
        ADMIN_WEB_SESSION_COOKIE_NAME,
        AdminWebApplicationHandleCodec,
        AdminWebBindingCodeError,
        AdminWebBindingCodeStore,
        AdminWebBusinessPluginCapabilitiesSummary,
        AdminWebBusinessPluginCapabilityItem,
        AdminWebCreatedResellerProductItem,
        AdminWebCreatedSupplierOfferItem,
        AdminWebExternalCatalogSyncProductItem,
        AdminWebExternalCatalogSyncResultItem,
        AdminWebExternalSourceCatalogProductItem,
        AdminWebExternalSourceCatalogProductsPage,
        AdminWebExternalFulfillmentAttemptItem,
        AdminWebExternalSourceConnectionHandleCodec,
        AdminWebExternalSourceConnectionItem,
        AdminWebExternalSourceConnectionsPage,
        AdminWebExternalSourceProviderItem,
        AdminWebInventoryImportResult,
        AdminWebPaymentCallbackFailureItem,
        AdminWebPaymentCallbackRejectionItem,
        AdminWebProductDeliveryFileResult,
        AdminWebResellerApplicationItem,
        AdminWebResellerProductItem,
        AdminWebReportExportDownloadHandleCodec,
        AdminWebService,
        AdminWebSessionCodec,
        AdminWebSessionError,
        AdminWebSessionSummary,
        AdminWebSubscriptionRenewalOrder,
        AdminWebOrderDeliveryDiagnosticItem,
        AdminWebOrderExternalFulfillmentDiagnosticItem,
        AdminWebOrderPaymentCallbackDiagnosticItem,
        AdminWebOrderPaymentDiagnosticItem,
        AdminWebOrderTrc20DirectDiagnosticItem,
        AdminWebSupplierApplicationItem,
        AdminWebSupplierOfferApprovalItem,
        AdminWebSupplierOfferItem,
        AdminWebSupplierRuleHandleCodec,
        AdminWebSupplierRuleItem,
        AdminWebSupplyMarketOfferItem,
        AdminWebCreatedTenantApiKeyItem,
        AdminWebTenantFinanceAuditItem,
        AdminWebTenantFinanceBalanceItem,
        AdminWebTenantFinanceDashboard,
        AdminWebTenantAuditLogsPage,
        AdminWebTenantAuditLogItem,
        AdminWebTenantApiKeyHandleCodec,
        AdminWebTenantApiKeyItem,
        AdminWebTenantApiKeyRevokeResult,
        AdminWebTenantApiKeysPage,
        AdminWebTenantRiskDashboard,
        AdminWebTenantRiskDisputeItem,
        AdminWebTenantRiskAfterSaleItem,
        AdminWebTenantSubscriptionDashboard,
        AdminWebTenantSubscriptionInvoiceItem,
        AdminWebTenantWithdrawalItem,
        AdminWebTenantOrderItem,
        AdminWebTenantOrderDiagnostics,
        AdminWebTenantOrderObservability,
        AdminWebTenantOrdersPage,
        AdminWebTenantOverview,
        AdminWebTenantPaymentProviderConfigItem,
        AdminWebTenantPaymentProviderConfigsPage,
        AdminWebTenantPaymentProviderOverview,
        AdminWebTenantProductBatchStatusUpdate,
        AdminWebTenantProductItem,
        AdminWebTenantProductsPage,
        AdminWebTenantReportExportDownloadFile,
        AdminWebTenantReportExportJobItem,
        AdminWebTenantReportExportJobsPage,
        AdminWebTenantStoreSettings,
        AdminWebTenantSupplyDashboard,
        AdminWebUserSummary,
        AdminWebWorkspaceSummary,
        PLATFORM_WORKSPACE_ID,
    )
    from app.services.business_plugins import BusinessPluginManifest
    from app.services.external_sources.base import ExternalSourceError
    from app.services.external_sources.sync import ExternalCatalogSyncResult, SyncedExternalProduct
    from app.services.file_inspection import InspectionResult
    from app.services.payments import PaymentUnavailableError
    from app.services.subscriptions import PlatformSubscriptionPlanSummary, SubscriptionAdjustmentResult, SubscriptionOrder
    from app.services.telegram_webapp import TelegramWebAppUser
    from app.web.admin_web import (
        AdminWebPlatformStatsResponse,
        _list_platform_payment_provider_observations,
        create_admin_web_router,
    )
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过 Admin Web 测试：{exc.name}") from exc


TEST_SESSION_NOW = 4102444800


class _FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0
        self.flush_count = 0
        self.added: list[object] = []

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    async def commit(self) -> None:
        self.commit_count += 1

    async def flush(self) -> None:
        self.flush_count += 1

    def add(self, item: object) -> None:
        self.added.append(item)


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expires: dict[str, int] = {}
        self.deleted_keys: list[str] = []

    async def set(self, key: str, value: str, *, ex: int, nx: bool = False) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.expires[key] = ex
        return True

    async def getdel(self, key: str) -> str | None:
        self.expires.pop(key, None)
        return self.values.pop(key, None)

    async def incr(self, key: str) -> int:
        value = int(self.values.get(key, "0")) + 1
        self.values[key] = str(value)
        return value

    async def expire(self, key: str, seconds: int) -> bool:
        self.expires[key] = seconds
        return True

    async def delete(self, *keys: str) -> int:
        self.deleted_keys.extend(keys)
        removed = 0
        for key in keys:
            if key in self.values:
                removed += 1
                self.values.pop(key, None)
                self.expires.pop(key, None)
        return removed


class _RowsResult:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[object, ...]]:
        return self._rows


def _session_factory(session: _FakeSession):
    def factory() -> _FakeSession:
        return session

    return factory


def _settings(*, storage_root: str = "/tmp/fakabot-test-storage") -> Settings:
    return Settings(
        master_bot_token="123:master-token",
        token_encryption_key="test-session-secret",
        public_base_url="https://example.com",
        platform_admin_ids={123},
        storage_root=storage_root,
    )


def _client(settings: Settings) -> TestClient:
    app = FastAPI()
    app.state.redis = None
    app.include_router(create_admin_web_router(settings))
    return TestClient(app)


def _origin_headers(origin: str = "https://example.com") -> dict[str, str]:
    return {"Origin": origin}


def _payment_config_item(
    *,
    provider: str,
    display_name: str = "epusdt GMPay",
    enabled: bool = True,
    merchant_id_masked: str | None = "12***90",
) -> AdminWebTenantPaymentProviderConfigItem:
    return AdminWebTenantPaymentProviderConfigItem(
        provider=provider,
        display_name=display_name,
        enabled=enabled,
        scope_type="tenant",
        gateway_url="https://pay.example",
        merchant_id_masked=merchant_id_masked,
        asset="USDT",
        network="TRC20",
        payment_type="alipay" if provider == "epay_compatible" else None,
        device="mobile" if provider == "epay_compatible" else None,
        return_url_configured=False,
        subject="FakaBot Order" if provider == "epay_compatible" else None,
        key_configured=True,
        create_payment_available=True,
        callback_available=True,
        query_order_available=provider == "epusdt_gmpay",
        reconcile_available=provider == "epusdt_gmpay",
        production_ready=False,
        staging_verified=False,
        offline_only=provider == "epay_compatible",
    )


def _plugin_capability_item(
    *,
    plugin_id: str = "external_source_mcy_shop",
    provider_name: str | None = "mcy_shop",
    kind: str = "external_source",
    name: str = "mcy_shop 外部货源插件",
) -> AdminWebBusinessPluginCapabilityItem:
    return AdminWebBusinessPluginCapabilityItem(
        plugin_id=plugin_id,
        provider_name=provider_name,
        kind=kind,
        name=name,
        version="builtin",
        contract_version="external_source_provider_v1" if kind == "external_source" else "payment_provider_v1",
        capabilities={"catalog_sync": True, "order": kind == "external_source", "delivery": kind == "external_source"},
        production_ready=False,
        staging_verified=False,
        offline_only=True,
        tenant_configurable=True,
        platform_configurable=False,
        requires_tenant_enablement=True,
        workspace_configured=True,
        workspace_enabled=True,
        scope_type="tenant",
        active_connection_count=1 if kind == "external_source" else 0,
        disabled_connection_count=0,
    )


def _external_source_connections_page(settings: Settings) -> AdminWebExternalSourceConnectionsPage:
    return AdminWebExternalSourceConnectionsPage(
        providers=(
            AdminWebExternalSourceProviderItem(
                provider_name="mcy_shop",
                integration_kind="offline_fixture",
                contract_name="mcy_shop_offline_fixture_v1",
                production_ready=False,
                staging_verified=False,
                catalog_sync_available=True,
                catalog_context_available=True,
                catalog_product_available=True,
                catalog_product_context_available=True,
                order_available=True,
                order_context_available=True,
                delivery_available=True,
                delivery_context_available=True,
                auto_fulfillment_idempotent_available=False,
            ),
        ),
        connections=(
            AdminWebExternalSourceConnectionItem(
                connection_handle=AdminWebExternalSourceConnectionHandleCodec(settings).encode(
                    tenant_id=7,
                    connection_id=11,
                ),
                provider_name="mcy_shop",
                source_key="fixture",
                display_name="Fixture Shop",
                status="active",
                credential_field_count=2,
                created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
                last_used_at=None,
            ),
        ),
    )


def _admin_web_external_catalog_sync_result() -> AdminWebExternalCatalogSyncResultItem:
    return AdminWebExternalCatalogSyncResultItem(
        provider_name="mcy_shop",
        source_key="fixture",
        created_count=1,
        updated_count=2,
        skipped_count=1,
        next_cursor="next-page",
        products=(
            AdminWebExternalCatalogSyncProductItem(
                product_id=101,
                action="created",
                status="on",
                skipped_reason=None,
            ),
            AdminWebExternalCatalogSyncProductItem(
                product_id=None,
                action="skipped",
                status="skipped",
                skipped_reason="外部商品不存在",
            ),
        ),
    )


def _admin_web_external_source_catalog_products_page(settings: Settings) -> AdminWebExternalSourceCatalogProductsPage:
    return AdminWebExternalSourceCatalogProductsPage(
        connection_handle=AdminWebExternalSourceConnectionHandleCodec(settings).encode(
            tenant_id=7,
            connection_id=11,
        ),
        provider_name="mcy_shop",
        source_key="fixture",
        display_name="Fixture Shop",
        status="active",
        total_count=1,
        limit=20,
        offset=0,
        items=(
            AdminWebExternalSourceCatalogProductItem(
                product_id=101,
                name="Fixture Card",
                category="cards",
                status="on",
                delivery_type="card_pool",
                price=Decimal("9.99000000"),
                currency="USDT",
                available_count=3,
                updated_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
            ),
        ),
    )


def _summary(*, current_workspace_id: str | None = None) -> AdminWebSessionSummary:
    return AdminWebSessionSummary(
        user=AdminWebUserSummary(
            telegram_user_id=123,
            username="owner",
            first_name="Owner",
            is_platform_admin=True,
        ),
        workspaces=(
            AdminWebWorkspaceSummary(
                workspace_id=PLATFORM_WORKSPACE_ID,
                kind="platform",
                role="platform_admin",
                title="主 Bot 管理",
            ),
            AdminWebWorkspaceSummary(
                workspace_id="tn_demo",
                kind="tenant",
                role="owner",
                title="Demo Store",
                tenant_public_id="tn_demo",
                bot_username="demo_bot",
                tenant_status="active",
                bot_status="active",
                supplier_enabled=True,
                reseller_enabled=True,
            ),
        ),
        current_workspace_id=current_workspace_id,
    )


def _telegram_user() -> TelegramWebAppUser:
    return TelegramWebAppUser(id=123, username="owner", first_name="Owner", language_code="zh")


def _json_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key))
            keys.update(_json_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.update(_json_keys(item))
    return keys


class AdminWebRouteTest(unittest.TestCase):
    def test_master_telegram_session_sets_http_only_cookie_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.admin_web.validate_telegram_webapp_init_data", return_value=_telegram_user()) as validate:
                with patch(
                    "app.web.admin_web.AdminWebService.create_or_update_webapp_user",
                    new=AsyncMock(return_value=SimpleNamespace(is_banned=False)),
                ):
                    with patch(
                        "app.web.admin_web.AdminWebService.session_summary",
                        new=AsyncMock(return_value=_summary()),
                    ):
                        response = client.post(
                            "/api/v1/admin-web/sessions/telegram",
                            json={"init_data": "valid=fake", "entrypoint": "master"},
                            headers=_origin_headers(),
                        )

        self.assertEqual(200, response.status_code)
        validate.assert_called_once()
        self.assertEqual(1, session.commit_count)
        cookie = response.headers.get("set-cookie", "")
        self.assertIn(ADMIN_WEB_SESSION_COOKIE_NAME, cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Max-Age=86400", cookie)
        payload_text = response.text.lower()
        self.assertIn("tn_demo", payload_text)
        self.assertNotIn("tenant_id", payload_text)
        self.assertNotIn("encrypted_token", payload_text)
        self.assertNotIn("plain_key", payload_text)
        self.assertNotIn("master-token", payload_text)

    def test_tenant_entrypoint_requires_workspace_access_before_cookie(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.admin_web._resolve_entrypoint_bot_token", new=AsyncMock(return_value="tenant-token")):
                with patch("app.web.admin_web.validate_telegram_webapp_init_data", return_value=_telegram_user()):
                    with patch(
                        "app.web.admin_web.AdminWebService.create_or_update_webapp_user",
                        new=AsyncMock(return_value=SimpleNamespace(is_banned=False)),
                    ):
                        with patch(
                            "app.web.admin_web.AdminWebService.ensure_workspace_access",
                            new=AsyncMock(side_effect=AdminWebSessionError("无权访问该管理工作区")),
                        ):
                            response = client.post(
                                "/api/v1/admin-web/sessions/telegram",
                                json={
                                    "init_data": "valid=fake",
                                    "entrypoint": "tenant",
                                    "tenant_public_id": "tn_demo",
                                },
                                headers=_origin_headers(),
                            )

        self.assertEqual(403, response.status_code)
        self.assertEqual("无权访问该管理工作区", response.json()["detail"])
        self.assertNotIn(ADMIN_WEB_SESSION_COOKIE_NAME, response.headers.get("set-cookie", ""))
        self.assertEqual(0, session.commit_count)

    def test_select_workspace_refreshes_cookie_for_accessible_workspace(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        claims = codec.new_claims(telegram_user_id=123, current_workspace_id=None)
        session_token = codec.encode(claims)
        client.cookies.set(ADMIN_WEB_SESSION_COOKIE_NAME, session_token)

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.ensure_workspace_access",
                new=AsyncMock(return_value=None),
            ):
                with patch(
                    "app.web.admin_web.AdminWebService.session_summary",
                    new=AsyncMock(return_value=_summary(current_workspace_id="tn_demo")),
                ):
                    response = client.post(
                        "/api/v1/admin-web/workspaces/select",
                        json={"workspace_id": "tn_demo"},
                        headers=_origin_headers(),
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("tn_demo", payload["current_workspace_id"])
        self.assertIn(ADMIN_WEB_SESSION_COOKIE_NAME, response.headers.get("set-cookie", ""))
        self.assertNotIn("tenant_id", response.text.lower())
        self.assertNotIn("secret", response.text.lower())

    def test_missing_cookie_is_rejected_before_workspace_query(self) -> None:
        settings = _settings()
        client = _client(settings)

        with patch(
            "app.web.admin_web.AdminWebService.list_workspaces",
            new=AsyncMock(side_effect=AssertionError("不应查询工作区")),
        ):
            response = client.get("/api/v1/admin-web/workspaces")

        self.assertEqual(401, response.status_code)
        self.assertEqual("缺少管理后台会话", response.json()["detail"])

    def test_tenant_overview_requires_current_clone_bot_workspace(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_overview",
            new=AsyncMock(side_effect=AssertionError("不应查询租户概览")),
        ):
            response = client.get("/api/v1/admin-web/tenant/overview")

        self.assertEqual(403, response.status_code)
        self.assertEqual("请选择克隆 Bot 工作区", response.json()["detail"])

    def test_tenant_overview_returns_safe_current_workspace_summary(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        overview = AdminWebTenantOverview(
            workspace=AdminWebWorkspaceSummary(
                workspace_id="tn_demo",
                kind="tenant",
                role="owner",
                title="Demo Store",
                tenant_public_id="tn_demo",
                bot_username="demo_bot",
                tenant_status="active",
                bot_status="active",
                supplier_enabled=True,
                reseller_enabled=True,
            ),
            tenant_public_id="tn_demo",
            store_name="Demo Store",
            tenant_status="active",
            bot_username="demo_bot",
            bot_status="active",
            product_count=5,
            published_product_count=3,
            available_inventory_count=21,
            order_count=8,
            pending_order_count=2,
            paid_order_count=1,
            delivered_order_count=4,
            payment_provider_count=2,
            enabled_payment_provider_count=1,
            payment_providers=(
                AdminWebTenantPaymentProviderOverview(
                    provider_name="epusdt_gmpay",
                    display_name="epusdt GMPay",
                    enabled=True,
                    scope_type="tenant",
                    key_configured=True,
                    create_payment_available=True,
                ),
                AdminWebTenantPaymentProviderOverview(
                    provider_name="epay_compatible",
                    display_name="易支付兼容",
                    enabled=False,
                    scope_type="tenant",
                    key_configured=False,
                    create_payment_available=True,
                ),
            ),
            subscription_status="active",
            subscription_plan_code="default_monthly",
            subscription_period_ends_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            ledger_currency="USDT",
            ledger_pending_balance=Decimal("1.5"),
            ledger_available_balance=Decimal("9.25"),
            ledger_frozen_balance=Decimal("0"),
            pending_withdrawal_count=1,
            supplier_enabled=True,
            reseller_enabled=True,
            supplier_offer_count=2,
            reseller_product_count=3,
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_overview",
                new=AsyncMock(return_value=overview),
            ) as tenant_overview:
                response = client.get("/api/v1/admin-web/tenant/overview")

        self.assertEqual(200, response.status_code)
        tenant_overview.assert_awaited_once_with(
            session,
            settings=settings,
            telegram_user_id=123,
            workspace_id="tn_demo",
        )
        payload = response.json()
        self.assertEqual("tn_demo", payload["tenant_public_id"])
        self.assertEqual("Demo Store", payload["store_name"])
        self.assertEqual(5, payload["products"]["total_count"])
        self.assertEqual(21, payload["products"]["available_inventory_count"])
        self.assertEqual(8, payload["orders"]["total_count"])
        self.assertEqual(1, payload["payments"]["enabled_count"])
        self.assertEqual("epusdt_gmpay", payload["payments"]["providers"][0]["provider_name"])
        self.assertEqual("default_monthly", payload["subscription"]["plan_code"])
        self.assertEqual("9.25", payload["finance"]["available_balance"])
        self.assertEqual(2, payload["supply"]["supplier_offer_count"])
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "tenant_bot_id",
            "owner_user_id",
            "encrypted_token",
            "token_hash",
            "webhook_secret",
            "plain_key",
            "secret_key",
            "payment_url",
            "storage_key",
            "raw_payload",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_overview_rejects_lost_workspace_access(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(_FakeSession())):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_overview",
                new=AsyncMock(side_effect=AdminWebSessionError("无权访问该管理工作区")),
            ):
                response = client.get("/api/v1/admin-web/tenant/overview")

        self.assertEqual(403, response.status_code)
        self.assertEqual("无权访问该管理工作区", response.json()["detail"])

    def test_tenant_settings_returns_current_workspace_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        store_settings = AdminWebTenantStoreSettings(
            store_name="Demo Store",
            welcome_text="欢迎光临",
            support_text="@support",
            order_timeout_minutes=30,
            self_sale_enabled=True,
            supplier_enabled=True,
            reseller_enabled=False,
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_store_settings",
                new=AsyncMock(return_value=store_settings),
            ) as tenant_store_settings:
                response = client.get("/api/v1/admin-web/tenant/settings")

        self.assertEqual(200, response.status_code)
        tenant_store_settings.assert_awaited_once_with(
            session,
            telegram_user_id=123,
            workspace_id="tn_demo",
        )
        self.assertEqual(
            {
                "store_name": "Demo Store",
                "welcome_text": "欢迎光临",
                "support_text": "@support",
                "order_timeout_minutes": 30,
                "self_sale_enabled": True,
                "supplier_enabled": True,
                "reseller_enabled": False,
            },
            response.json(),
        )
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "tenant_bot_id",
            "owner_user_id",
            "encrypted_token",
            "token_hash",
            "webhook_secret",
            "api_key",
            "secret",
            "raw_payload",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_update_settings_uses_current_workspace_origin_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        store_settings = AdminWebTenantStoreSettings(
            store_name="新店铺",
            welcome_text="欢迎下单",
            support_text="@help",
            order_timeout_minutes=45,
            self_sale_enabled=True,
            supplier_enabled=True,
            reseller_enabled=True,
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_update_store_settings",
                new=AsyncMock(return_value=store_settings),
            ) as update_settings:
                response = client.patch(
                    "/api/v1/admin-web/tenant/settings",
                    json={
                        "store_name": "新店铺",
                        "welcome_text": "欢迎下单",
                        "support_text": "@help",
                        "order_timeout_minutes": 45,
                        "self_sale_enabled": True,
                        "supplier_enabled": True,
                        "reseller_enabled": True,
                    },
                    headers=_origin_headers(),
                )

        self.assertEqual(200, response.status_code)
        update_settings.assert_awaited_once_with(
            session,
            telegram_user_id=123,
            workspace_id="tn_demo",
            store_name="新店铺",
            welcome_text="欢迎下单",
            support_text="@help",
            order_timeout_minutes=45,
            self_sale_enabled=True,
            supplier_enabled=True,
            reseller_enabled=True,
        )
        self.assertEqual(1, session.commit_count)
        payload = response.json()
        self.assertEqual("新店铺", payload["store_name"])
        self.assertEqual("欢迎下单", payload["welcome_text"])
        self.assertEqual("@help", payload["support_text"])
        self.assertEqual(45, payload["order_timeout_minutes"])
        self.assertTrue(payload["self_sale_enabled"])
        self.assertTrue(payload["supplier_enabled"])
        self.assertTrue(payload["reseller_enabled"])
        response_text = response.text.lower()
        for forbidden in ("tenant_id", "owner_user_id", "token", "secret", "raw_payload"):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_update_settings_feature_flags_only_uses_current_workspace_origin(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        store_settings = AdminWebTenantStoreSettings(
            store_name="Demo Store",
            welcome_text="欢迎下单",
            support_text="@help",
            order_timeout_minutes=45,
            self_sale_enabled=False,
            supplier_enabled=True,
            reseller_enabled=False,
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_update_store_settings",
                new=AsyncMock(return_value=store_settings),
            ) as update_settings:
                response = client.patch(
                    "/api/v1/admin-web/tenant/settings",
                    json={
                        "self_sale_enabled": False,
                        "supplier_enabled": True,
                        "reseller_enabled": False,
                    },
                    headers=_origin_headers(),
                )

        self.assertEqual(200, response.status_code)
        update_settings.assert_awaited_once_with(
            session,
            telegram_user_id=123,
            workspace_id="tn_demo",
            store_name=None,
            welcome_text=None,
            support_text=None,
            order_timeout_minutes=None,
            self_sale_enabled=False,
            supplier_enabled=True,
            reseller_enabled=False,
        )
        self.assertEqual(1, session.commit_count)
        payload = response.json()
        self.assertFalse(payload["self_sale_enabled"])
        self.assertTrue(payload["supplier_enabled"])
        self.assertFalse(payload["reseller_enabled"])
        response_text = response.text.lower()
        for forbidden in ("feature_flags", "clone_enabled", "tenant_id", "token", "secret", "raw_payload"):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_update_settings_rejects_extra_fields_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_update_store_settings",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.patch(
                "/api/v1/admin-web/tenant/settings",
                json={"store_name": "新店铺", "tenant_id": 7, "secret": "raw"},
                headers=_origin_headers(),
            )

        self.assertEqual(422, response.status_code)

    def test_tenant_update_settings_rejects_raw_feature_flags_and_clone_enabled_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_update_store_settings",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.patch(
                "/api/v1/admin-web/tenant/settings",
                json={
                    "feature_flags": {"self_sale": False},
                    "clone_enabled": True,
                    "tenant_id": 7,
                },
                headers=_origin_headers(),
            )

        self.assertEqual(422, response.status_code)

    def test_tenant_update_settings_rejects_empty_payload_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_update_store_settings",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.patch(
                "/api/v1/admin-web/tenant/settings",
                json={},
                headers=_origin_headers(),
            )

        self.assertEqual(400, response.status_code)
        self.assertEqual("店铺设置参数无效", response.json()["detail"])

    def test_tenant_update_settings_rejects_null_fields_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_update_store_settings",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.patch(
                "/api/v1/admin-web/tenant/settings",
                json={"welcome_text": None},
                headers=_origin_headers(),
            )

        self.assertEqual(400, response.status_code)
        self.assertEqual("店铺设置参数无效", response.json()["detail"])

    def test_tenant_update_settings_rejects_null_feature_flags_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_update_store_settings",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.patch(
                "/api/v1/admin-web/tenant/settings",
                json={"supplier_enabled": None},
                headers=_origin_headers(),
            )

        self.assertEqual(400, response.status_code)
        self.assertEqual("店铺设置参数无效", response.json()["detail"])

    def test_tenant_update_settings_rejects_missing_or_untrusted_origin(self) -> None:
        settings = _settings()
        client = _client(settings)

        with patch(
            "app.web.admin_web.AdminWebService.tenant_update_store_settings",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            missing_origin_response = client.patch(
                "/api/v1/admin-web/tenant/settings",
                json={"store_name": "新店铺"},
            )
            untrusted_origin_response = client.patch(
                "/api/v1/admin-web/tenant/settings",
                json={"store_name": "新店铺"},
                headers=_origin_headers("https://evil.example"),
            )

        self.assertEqual(403, missing_origin_response.status_code)
        self.assertEqual("缺少管理后台请求来源", missing_origin_response.json()["detail"])
        self.assertEqual(403, untrusted_origin_response.status_code)
        self.assertEqual("管理后台请求来源不允许", untrusted_origin_response.json()["detail"])

    def test_tenant_update_settings_requires_current_clone_bot_workspace(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_update_store_settings",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.patch(
                "/api/v1/admin-web/tenant/settings",
                json={"store_name": "新店铺"},
                headers=_origin_headers(),
            )

        self.assertEqual(403, response.status_code)
        self.assertEqual("请选择克隆 Bot 工作区", response.json()["detail"])

    def test_tenant_update_settings_value_error_returns_400_without_commit(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_update_store_settings",
                new=AsyncMock(side_effect=ValueError("店铺名称长度应为 2-64 个字符")),
            ):
                response = client.patch(
                    "/api/v1/admin-web/tenant/settings",
                    json={"store_name": "新店铺"},
                    headers=_origin_headers(),
                )

        self.assertEqual(400, response.status_code)
        self.assertEqual("店铺名称长度应为 2-64 个字符", response.json()["detail"])
        self.assertEqual(0, session.commit_count)

    def test_tenant_products_requires_current_clone_bot_workspace(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_products",
            new=AsyncMock(side_effect=AssertionError("不应查询商品列表")),
        ):
            response = client.get("/api/v1/admin-web/tenant/products")

        self.assertEqual(403, response.status_code)
        self.assertEqual("请选择克隆 Bot 工作区", response.json()["detail"])

    def test_tenant_products_returns_safe_current_workspace_items(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        products = AdminWebTenantProductsPage(
            total_count=2,
            limit=10,
            offset=20,
            items=(
                AdminWebTenantProductItem(
                    product_id=12,
                    name="Demo Product",
                    category="软件",
                    sort_order=5,
                    status="on",
                    delivery_type="card_pool",
                    price=Decimal("9.9"),
                    currency="USDT",
                    available_count=3,
                ),
            ),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_products",
                new=AsyncMock(return_value=products),
            ) as tenant_products:
                response = client.get(
                    "/api/v1/admin-web/tenant/products",
                    params={
                        "limit": 10,
                        "offset": 20,
                        "query": "demo",
                        "status": "on",
                        "delivery_type": "card_pool",
                        "category": "软件",
                    },
                )

        self.assertEqual(200, response.status_code)
        tenant_products.assert_awaited_once_with(
            session,
            telegram_user_id=123,
            workspace_id="tn_demo",
            limit=10,
            offset=20,
            query="demo",
            status="on",
            delivery_type="card_pool",
            category="软件",
        )
        payload = response.json()
        self.assertEqual(2, payload["total_count"])
        self.assertEqual(20, payload["offset"])
        self.assertEqual(12, payload["items"][0]["product_id"])
        self.assertEqual(3, payload["items"][0]["available_count"])
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "delivery_file_id",
            "storage_key",
            "content_encrypted",
            "content_hash",
            "raw_payload",
            "token",
            "secret",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_update_product_metadata_uses_current_workspace_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        product = AdminWebTenantProductItem(
            product_id=12,
            name="Demo Product",
            category="工具",
            sort_order=9,
            status="on",
            delivery_type="card_pool",
            price=Decimal("9.90"),
            currency="USDT",
            available_count=3,
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_update_product_metadata",
                new=AsyncMock(return_value=product),
            ) as update_product:
                response = client.patch(
                    "/api/v1/admin-web/tenant/products/12/metadata",
                    json={"category": "工具", "sort_order": 9},
                    headers=_origin_headers(),
                )

        self.assertEqual(200, response.status_code)
        update_product.assert_awaited_once_with(
            session,
            telegram_user_id=123,
            workspace_id="tn_demo",
            product_id=12,
            category="工具",
            category_provided=True,
            sort_order=9,
        )
        self.assertEqual(1, session.commit_count)
        payload = response.json()
        self.assertEqual(12, payload["product_id"])
        self.assertEqual("工具", payload["category"])
        response_text = response.text.lower()
        for forbidden in ("tenant_id", "storage_key", "content_encrypted", "raw_payload", "token", "secret"):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_update_product_metadata_rejects_extra_fields_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_update_product_metadata",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.patch(
                "/api/v1/admin-web/tenant/products/12/metadata",
                json={"category": "工具", "price": "1.00", "tenant_id": 7},
                headers=_origin_headers(),
            )

        self.assertEqual(422, response.status_code)

    def test_tenant_update_product_metadata_rejects_empty_payload_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_update_product_metadata",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.patch(
                "/api/v1/admin-web/tenant/products/12/metadata",
                json={},
                headers=_origin_headers(),
            )

        self.assertEqual(400, response.status_code)

    def test_tenant_update_product_metadata_rejects_null_sort_order_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_update_product_metadata",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.patch(
                "/api/v1/admin-web/tenant/products/12/metadata",
                json={"category": "工具", "sort_order": None},
                headers=_origin_headers(),
            )

        self.assertEqual(400, response.status_code)

    def test_tenant_update_product_metadata_rejects_missing_or_untrusted_origin(self) -> None:
        settings = _settings()
        client = _client(settings)

        with patch(
            "app.web.admin_web.AdminWebService.tenant_update_product_metadata",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            missing_origin_response = client.patch(
                "/api/v1/admin-web/tenant/products/12/metadata",
                json={"category": "工具"},
            )
            untrusted_origin_response = client.patch(
                "/api/v1/admin-web/tenant/products/12/metadata",
                json={"category": "工具"},
                headers=_origin_headers("https://evil.example"),
            )

        self.assertEqual(403, missing_origin_response.status_code)
        self.assertEqual("缺少管理后台请求来源", missing_origin_response.json()["detail"])
        self.assertEqual(403, untrusted_origin_response.status_code)
        self.assertEqual("管理后台请求来源不允许", untrusted_origin_response.json()["detail"])

    def test_tenant_update_product_metadata_requires_current_clone_bot_workspace(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_update_product_metadata",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.patch(
                "/api/v1/admin-web/tenant/products/12/metadata",
                json={"category": "工具"},
                headers=_origin_headers(),
            )

        self.assertEqual(403, response.status_code)
        self.assertEqual("请选择克隆 Bot 工作区", response.json()["detail"])

    def test_tenant_update_product_metadata_service_error_returns_403_without_commit(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_update_product_metadata",
                new=AsyncMock(side_effect=AdminWebSessionError("商品不存在或无权限")),
            ):
                response = client.patch(
                    "/api/v1/admin-web/tenant/products/12/metadata",
                    json={"category": "工具"},
                    headers=_origin_headers(),
                )

        self.assertEqual(403, response.status_code)
        self.assertEqual(0, session.commit_count)
        response_text = response.text.lower()
        for forbidden in ("tenant_id", "raw_payload", "token", "secret"):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_create_product_uses_current_workspace_origin_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        product = AdminWebTenantProductItem(
            product_id=31,
            name="Demo Product",
            category="工具",
            sort_order=0,
            status="draft",
            delivery_type="card_pool",
            price=Decimal("12.50"),
            currency="USDT",
            available_count=0,
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_create_product",
                new=AsyncMock(return_value=product),
            ) as create_product:
                response = client.post(
                    "/api/v1/admin-web/tenant/products",
                    json={
                        "name": "Demo Product",
                        "price": "12.50",
                        "delivery_type": "card_pool",
                        "category": "工具",
                        "description": "仅创建草稿",
                    },
                    headers=_origin_headers(),
                )

        self.assertEqual(200, response.status_code)
        create_product.assert_awaited_once_with(
            session,
            telegram_user_id=123,
            workspace_id="tn_demo",
            name="Demo Product",
            price=Decimal("12.50"),
            delivery_type="card_pool",
            description="仅创建草稿",
            category="工具",
        )
        self.assertEqual(1, session.commit_count)
        payload = response.json()
        self.assertEqual(31, payload["product_id"])
        self.assertEqual("draft", payload["status"])
        self.assertEqual("12.50", payload["price"])
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "product_type",
            "external_source",
            "source_key",
            "external_id",
            "description",
            "delivery_file_id",
            "storage_key",
            "content_encrypted",
            "content_hash",
            "raw_payload",
            "token",
            "secret",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_create_product_rejects_extra_fields_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_create_product",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.post(
                "/api/v1/admin-web/tenant/products",
                json={
                    "name": "Demo Product",
                    "price": "12.50",
                    "delivery_type": "card_pool",
                    "tenant_id": 7,
                    "status": "on",
                    "external_source": "upstream",
                },
                headers=_origin_headers(),
            )

        self.assertEqual(422, response.status_code)

    def test_tenant_create_product_rejects_missing_or_untrusted_origin(self) -> None:
        settings = _settings()
        client = _client(settings)
        payload = {"name": "Demo Product", "price": "12.50", "delivery_type": "card_pool"}

        with patch(
            "app.web.admin_web.AdminWebService.tenant_create_product",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            missing_origin_response = client.post("/api/v1/admin-web/tenant/products", json=payload)
            untrusted_origin_response = client.post(
                "/api/v1/admin-web/tenant/products",
                json=payload,
                headers=_origin_headers("https://evil.example"),
            )

        self.assertEqual(403, missing_origin_response.status_code)
        self.assertEqual("缺少管理后台请求来源", missing_origin_response.json()["detail"])
        self.assertEqual(403, untrusted_origin_response.status_code)
        self.assertEqual("管理后台请求来源不允许", untrusted_origin_response.json()["detail"])

    def test_tenant_create_product_requires_current_clone_bot_workspace(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_create_product",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.post(
                "/api/v1/admin-web/tenant/products",
                json={"name": "Demo Product", "price": "12.50", "delivery_type": "card_pool"},
                headers=_origin_headers(),
            )

        self.assertEqual(403, response.status_code)
        self.assertEqual("请选择克隆 Bot 工作区", response.json()["detail"])

    def test_tenant_create_product_service_error_returns_403_without_commit(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_create_product",
                new=AsyncMock(side_effect=AdminWebSessionError("无权访问该管理工作区")),
            ):
                response = client.post(
                    "/api/v1/admin-web/tenant/products",
                    json={"name": "Demo Product", "price": "12.50", "delivery_type": "card_pool"},
                    headers=_origin_headers(),
                )

        self.assertEqual(403, response.status_code)
        self.assertEqual(0, session.commit_count)
        response_text = response.text.lower()
        for forbidden in ("tenant_id", "raw_payload", "token", "secret"):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_create_product_value_error_returns_400_without_commit_or_secret(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_create_product",
                new=AsyncMock(side_effect=ValueError("upstream secret raw_payload leak")),
            ):
                response = client.post(
                    "/api/v1/admin-web/tenant/products",
                    json={"name": "Demo Product", "price": "12.50", "delivery_type": "card_pool"},
                    headers=_origin_headers(),
                )

        self.assertEqual(400, response.status_code)
        self.assertEqual("商品创建参数无效", response.json()["detail"])
        self.assertEqual(0, session.commit_count)
        response_text = response.text.lower()
        for forbidden in ("upstream", "raw_payload", "token", "secret"):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_update_product_price_status_uses_current_workspace_origin_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        product = AdminWebTenantProductItem(
            product_id=12,
            name="Demo Product",
            category="工具",
            sort_order=9,
            status="off",
            delivery_type="card_pool",
            price=Decimal("12.50"),
            currency="USDT",
            available_count=3,
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_update_product_sales",
                new=AsyncMock(return_value=product),
            ) as update_product:
                response = client.patch(
                    "/api/v1/admin-web/tenant/products/12/sales",
                    json={"price": "12.50", "status": "off"},
                    headers=_origin_headers(),
                )

        self.assertEqual(200, response.status_code)
        update_product.assert_awaited_once_with(
            session,
            telegram_user_id=123,
            workspace_id="tn_demo",
            product_id=12,
            price=Decimal("12.50"),
            status="off",
        )
        self.assertEqual(1, session.commit_count)
        payload = response.json()
        self.assertEqual("off", payload["status"])
        self.assertEqual("12.50", payload["price"])
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "delivery_file_id",
            "storage_key",
            "content_encrypted",
            "raw_payload",
            "token",
            "secret",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_update_product_price_status_rejects_extra_fields_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_update_product_sales",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.patch(
                "/api/v1/admin-web/tenant/products/12/sales",
                json={"price": "12.50", "status": "on", "tenant_id": 7},
                headers=_origin_headers(),
            )

        self.assertEqual(422, response.status_code)

    def test_tenant_update_product_price_status_rejects_empty_payload_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_update_product_sales",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.patch(
                "/api/v1/admin-web/tenant/products/12/sales",
                json={},
                headers=_origin_headers(),
            )

        self.assertEqual(400, response.status_code)

    def test_tenant_update_product_price_status_rejects_missing_or_untrusted_origin(self) -> None:
        settings = _settings()
        client = _client(settings)

        with patch(
            "app.web.admin_web.AdminWebService.tenant_update_product_sales",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            missing_origin_response = client.patch(
                "/api/v1/admin-web/tenant/products/12/sales",
                json={"price": "12.50"},
            )
            untrusted_origin_response = client.patch(
                "/api/v1/admin-web/tenant/products/12/sales",
                json={"price": "12.50"},
                headers=_origin_headers("https://evil.example"),
            )

        self.assertEqual(403, missing_origin_response.status_code)
        self.assertEqual("缺少管理后台请求来源", missing_origin_response.json()["detail"])
        self.assertEqual(403, untrusted_origin_response.status_code)
        self.assertEqual("管理后台请求来源不允许", untrusted_origin_response.json()["detail"])

    def test_tenant_update_product_price_status_requires_current_clone_bot_workspace(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_update_product_sales",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.patch(
                "/api/v1/admin-web/tenant/products/12/sales",
                json={"price": "12.50"},
                headers=_origin_headers(),
            )

        self.assertEqual(403, response.status_code)
        self.assertEqual("请选择克隆 Bot 工作区", response.json()["detail"])

    def test_tenant_update_product_price_status_service_error_returns_403_without_commit(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_update_product_sales",
                new=AsyncMock(side_effect=AdminWebSessionError("商品不存在或无权限")),
            ):
                response = client.patch(
                    "/api/v1/admin-web/tenant/products/12/sales",
                    json={"status": "off"},
                    headers=_origin_headers(),
                )

        self.assertEqual(403, response.status_code)
        self.assertEqual(0, session.commit_count)
        response_text = response.text.lower()
        for forbidden in ("tenant_id", "raw_payload", "token", "secret"):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_update_product_price_status_value_error_returns_400_without_commit(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_update_product_sales",
                new=AsyncMock(side_effect=ValueError("文件商品需要先上传并绑定文件")),
            ):
                response = client.patch(
                    "/api/v1/admin-web/tenant/products/12/sales",
                    json={"status": "on"},
                    headers=_origin_headers(),
                )

        self.assertEqual(400, response.status_code)
        self.assertEqual("文件商品需要先上传并绑定文件", response.json()["detail"])
        self.assertEqual(0, session.commit_count)
        response_text = response.text.lower()
        for forbidden in ("storage_key", "delivery_file_id", "raw_payload", "token", "secret"):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_batch_update_product_status_uses_current_workspace_origin_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        result = AdminWebTenantProductBatchStatusUpdate(
            status="off",
            updated_count=2,
            products=(
                AdminWebTenantProductItem(
                    product_id=12,
                    name="Demo Product",
                    category="工具",
                    sort_order=9,
                    status="off",
                    delivery_type="card_pool",
                    price=Decimal("12.50"),
                    currency="USDT",
                    available_count=3,
                ),
                AdminWebTenantProductItem(
                    product_id=13,
                    name="Second Product",
                    category=None,
                    sort_order=10,
                    status="off",
                    delivery_type="card_fixed",
                    price=Decimal("9.90"),
                    currency="USDT",
                    available_count=1,
                ),
            ),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_batch_update_product_status",
                new=AsyncMock(return_value=result),
            ) as batch_update:
                response = client.patch(
                    "/api/v1/admin-web/tenant/products/status",
                    json={"product_ids": [12, 13], "status": "off"},
                    headers=_origin_headers(),
                )

        self.assertEqual(200, response.status_code)
        batch_update.assert_awaited_once_with(
            session,
            telegram_user_id=123,
            workspace_id="tn_demo",
            product_ids=[12, 13],
            status="off",
        )
        self.assertEqual(1, session.commit_count)
        payload = response.json()
        self.assertEqual("off", payload["status"])
        self.assertEqual(2, payload["updated_count"])
        self.assertEqual([12, 13], [item["product_id"] for item in payload["products"]])
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "delivery_file_id",
            "storage_key",
            "content_encrypted",
            "raw_payload",
            "token",
            "secret",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_batch_update_product_status_rejects_extra_internal_fields_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_batch_update_product_status",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.patch(
                "/api/v1/admin-web/tenant/products/status",
                json={"product_ids": [12], "status": "off", "tenant_id": 7},
                headers=_origin_headers(),
            )

        self.assertEqual(422, response.status_code)

    def test_tenant_batch_update_product_status_rejects_missing_or_untrusted_origin(self) -> None:
        settings = _settings()
        client = _client(settings)

        with patch(
            "app.web.admin_web.AdminWebService.tenant_batch_update_product_status",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            missing_origin_response = client.patch(
                "/api/v1/admin-web/tenant/products/status",
                json={"product_ids": [12], "status": "off"},
            )
            untrusted_origin_response = client.patch(
                "/api/v1/admin-web/tenant/products/status",
                json={"product_ids": [12], "status": "off"},
                headers=_origin_headers("https://evil.example"),
            )

        self.assertEqual(403, missing_origin_response.status_code)
        self.assertEqual("缺少管理后台请求来源", missing_origin_response.json()["detail"])
        self.assertEqual(403, untrusted_origin_response.status_code)
        self.assertEqual("管理后台请求来源不允许", untrusted_origin_response.json()["detail"])

    def test_tenant_batch_update_product_status_requires_current_clone_bot_workspace(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_batch_update_product_status",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.patch(
                "/api/v1/admin-web/tenant/products/status",
                json={"product_ids": [12], "status": "off"},
                headers=_origin_headers(),
            )

        self.assertEqual(403, response.status_code)
        self.assertEqual("请选择克隆 Bot 工作区", response.json()["detail"])

    def test_tenant_batch_update_product_status_service_error_returns_403_without_commit(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_batch_update_product_status",
                new=AsyncMock(side_effect=AdminWebSessionError("商品不存在或无权限")),
            ):
                response = client.patch(
                    "/api/v1/admin-web/tenant/products/status",
                    json={"product_ids": [12], "status": "off"},
                    headers=_origin_headers(),
                )

        self.assertEqual(403, response.status_code)
        self.assertEqual(0, session.commit_count)
        response_text = response.text.lower()
        for forbidden in ("tenant_id", "raw_payload", "token", "secret"):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_import_product_inventory_uses_current_workspace_origin_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        import_result = AdminWebInventoryImportResult(
            product_id=12,
            added_count=2,
            existing_count=1,
            input_duplicate_count=1,
            available_count=5,
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_import_product_inventory",
                new=AsyncMock(return_value=import_result),
            ) as import_inventory:
                response = client.post(
                    "/api/v1/admin-web/tenant/products/12/inventory/import",
                    json={"items": ["alpha-card", "beta-card", "alpha-card"]},
                    headers=_origin_headers(),
                )

        self.assertEqual(200, response.status_code)
        import_inventory.assert_awaited_once_with(
            session,
            settings=settings,
            telegram_user_id=123,
            workspace_id="tn_demo",
            product_id=12,
            items=["alpha-card", "beta-card", "alpha-card"],
        )
        self.assertEqual(1, session.commit_count)
        payload = response.json()
        self.assertEqual(
            {
                "product_id": 12,
                "added_count": 2,
                "existing_count": 1,
                "input_duplicate_count": 1,
                "available_count": 5,
            },
            payload,
        )
        response_text = response.text.lower()
        for forbidden in (
            "alpha-card",
            "beta-card",
            "tenant_id",
            "variant_id",
            "inventory_item_id",
            "storage_key",
            "content_encrypted",
            "content_hash",
            "raw_payload",
            "token",
            "secret",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_import_product_inventory_rejects_extra_fields_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_import_product_inventory",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.post(
                "/api/v1/admin-web/tenant/products/12/inventory/import",
                json={
                    "items": ["alpha-card"],
                    "tenant_id": 7,
                    "variant_id": 8,
                    "content_encrypted": "cipher",
                    "storage_key": "file-key",
                    "status": "available",
                },
                headers=_origin_headers(),
            )

        self.assertEqual(422, response.status_code)

    def test_tenant_import_product_inventory_rejects_missing_or_untrusted_origin(self) -> None:
        settings = _settings()
        client = _client(settings)

        with patch(
            "app.web.admin_web.AdminWebService.tenant_import_product_inventory",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            missing_origin_response = client.post(
                "/api/v1/admin-web/tenant/products/12/inventory/import",
                json={"items": ["alpha-card"]},
            )
            untrusted_origin_response = client.post(
                "/api/v1/admin-web/tenant/products/12/inventory/import",
                json={"items": ["alpha-card"]},
                headers=_origin_headers("https://evil.example"),
            )

        self.assertEqual(403, missing_origin_response.status_code)
        self.assertEqual("缺少管理后台请求来源", missing_origin_response.json()["detail"])
        self.assertEqual(403, untrusted_origin_response.status_code)
        self.assertEqual("管理后台请求来源不允许", untrusted_origin_response.json()["detail"])

    def test_tenant_import_product_inventory_requires_current_clone_bot_workspace(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_import_product_inventory",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.post(
                "/api/v1/admin-web/tenant/products/12/inventory/import",
                json={"items": ["alpha-card"]},
                headers=_origin_headers(),
            )

        self.assertEqual(403, response.status_code)
        self.assertEqual("请选择克隆 Bot 工作区", response.json()["detail"])

    def test_tenant_import_product_inventory_value_error_returns_400_without_commit_or_content(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_import_product_inventory",
                new=AsyncMock(side_effect=ValueError("alpha-card raw_payload secret")),
            ):
                response = client.post(
                    "/api/v1/admin-web/tenant/products/12/inventory/import",
                    json={"items": ["alpha-card"]},
                    headers=_origin_headers(),
                )

        self.assertEqual(400, response.status_code)
        self.assertEqual("商品库存导入参数无效", response.json()["detail"])
        self.assertEqual(0, session.commit_count)
        response_text = response.text.lower()
        for forbidden in ("alpha-card", "raw_payload", "token", "secret"):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_import_product_inventory_service_error_returns_403_without_commit(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_import_product_inventory",
                new=AsyncMock(side_effect=AdminWebSessionError("商品不存在或无权限")),
            ):
                response = client.post(
                    "/api/v1/admin-web/tenant/products/12/inventory/import",
                    json={"items": ["alpha-card"]},
                    headers=_origin_headers(),
                )

        self.assertEqual(403, response.status_code)
        self.assertEqual(0, session.commit_count)
        response_text = response.text.lower()
        for forbidden in ("tenant_id", "inventory_item_id", "raw_payload", "token", "secret"):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_upload_product_delivery_file_uses_current_workspace_origin_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        upload_result = AdminWebProductDeliveryFileResult(
            product_id=12,
            filename="payload.zip",
            size_bytes=12,
            content_type="application/zip",
            risk_level="low",
            scan_message="文件扫描完成",
            bound=True,
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_upload_product_delivery_file",
                new=AsyncMock(return_value=upload_result),
            ) as upload_file:
                response = client.post(
                    "/api/v1/admin-web/tenant/products/12/delivery-file",
                    files={"file": ("payload.zip", b"PK\x03\x04demo", "application/zip")},
                    headers=_origin_headers(),
                )

        self.assertEqual(200, response.status_code)
        upload_file.assert_awaited_once_with(
            session,
            settings=settings,
            telegram_user_id=123,
            workspace_id="tn_demo",
            product_id=12,
            filename="payload.zip",
            content_type="application/zip",
            payload=b"PK\x03\x04demo",
        )
        self.assertEqual(1, session.commit_count)
        self.assertEqual(
            {
                "product_id": 12,
                "filename": "payload.zip",
                "size_bytes": 12,
                "content_type": "application/zip",
                "risk_level": "low",
                "scan_message": "文件扫描完成",
                "bound": True,
            },
            response.json(),
        )
        response_text = response.text.lower()
        for forbidden in (
            "storage_key",
            "delivery_file_id",
            "uploaded_file_id",
            "sha256",
            "raw_payload",
            "token",
            "secret",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_upload_product_delivery_file_rejects_missing_or_untrusted_origin(self) -> None:
        settings = _settings()
        client = _client(settings)

        with patch(
            "app.web.admin_web.AdminWebService.tenant_upload_product_delivery_file",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            missing_origin_response = client.post(
                "/api/v1/admin-web/tenant/products/12/delivery-file",
                files={"file": ("payload.zip", b"PK\x03\x04demo", "application/zip")},
            )
            untrusted_origin_response = client.post(
                "/api/v1/admin-web/tenant/products/12/delivery-file",
                files={"file": ("payload.zip", b"PK\x03\x04demo", "application/zip")},
                headers=_origin_headers("https://evil.example"),
            )

        self.assertEqual(403, missing_origin_response.status_code)
        self.assertEqual("缺少管理后台请求来源", missing_origin_response.json()["detail"])
        self.assertEqual(403, untrusted_origin_response.status_code)
        self.assertEqual("管理后台请求来源不允许", untrusted_origin_response.json()["detail"])

    def test_tenant_upload_product_delivery_file_requires_current_clone_bot_workspace(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_upload_product_delivery_file",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.post(
                "/api/v1/admin-web/tenant/products/12/delivery-file",
                files={"file": ("payload.zip", b"PK\x03\x04demo", "application/zip")},
                headers=_origin_headers(),
            )

        self.assertEqual(403, response.status_code)
        self.assertEqual("请选择克隆 Bot 工作区", response.json()["detail"])

    def test_tenant_upload_product_delivery_file_value_error_returns_400_without_commit_or_storage_key(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_upload_product_delivery_file",
                new=AsyncMock(side_effect=ValueError("storage_key=tenants/7/files/plain secret")),
            ):
                response = client.post(
                    "/api/v1/admin-web/tenant/products/12/delivery-file",
                    files={"file": ("payload.zip", b"PK\x03\x04demo", "application/zip")},
                    headers=_origin_headers(),
                )

        self.assertEqual(400, response.status_code)
        self.assertEqual("文件商品绑定参数无效", response.json()["detail"])
        self.assertEqual(0, session.commit_count)
        response_text = response.text.lower()
        for forbidden in ("storage_key", "tenants/7/files", "raw_payload", "token", "secret"):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_upload_product_delivery_file_service_error_returns_403_without_commit(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_upload_product_delivery_file",
                new=AsyncMock(side_effect=AdminWebSessionError("商品不存在或无权限")),
            ):
                response = client.post(
                    "/api/v1/admin-web/tenant/products/12/delivery-file",
                    files={"file": ("payload.zip", b"PK\x03\x04demo", "application/zip")},
                    headers=_origin_headers(),
                )

        self.assertEqual(403, response.status_code)
        self.assertEqual(0, session.commit_count)
        response_text = response.text.lower()
        for forbidden in ("tenant_id", "uploaded_file_id", "delivery_file_id", "storage_key", "raw_payload"):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_payment_configs_returns_safe_current_workspace_items(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        configs = AdminWebTenantPaymentProviderConfigsPage(
            providers=(
                _payment_config_item(provider="epusdt_gmpay", merchant_id_masked="12***90"),
                _payment_config_item(provider="epay_compatible", display_name="易支付兼容", enabled=False),
            ),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_payment_configs",
                new=AsyncMock(return_value=configs),
            ) as list_configs:
                response = client.get("/api/v1/admin-web/tenant/payments/configs")

        self.assertEqual(200, response.status_code)
        list_configs.assert_awaited_once_with(
            session,
            settings=settings,
            telegram_user_id=123,
            workspace_id="tn_demo",
        )
        payload = response.json()
        self.assertEqual("epusdt_gmpay", payload["providers"][0]["provider"])
        self.assertEqual("12***90", payload["providers"][0]["merchant_id_masked"])
        response_text = response.text.lower()
        for forbidden in ("tenant_id", "workspace_id", "config_encrypted", "secret_key", "payment_url", "raw_payload"):
            self.assertNotIn(forbidden, response_text)
        self.assertNotIn("very-secret", response_text)

    def test_business_plugin_capabilities_requires_admin_web_session(self) -> None:
        settings = _settings()
        client = _client(settings)

        with patch(
            "app.web.admin_web.AdminWebService.business_plugin_capabilities",
            new=AsyncMock(side_effect=AssertionError("不应读取插件能力")),
        ):
            response = client.get("/api/v1/admin-web/business-plugins/capabilities")

        self.assertEqual(401, response.status_code)
        self.assertEqual("缺少管理后台会话", response.json()["detail"])

    def test_business_plugin_capabilities_requires_current_workspace(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=None)),
        )

        with patch(
            "app.web.admin_web.AdminWebService.business_plugin_capabilities",
            new=AsyncMock(side_effect=AssertionError("不应读取插件能力")),
        ):
            response = client.get("/api/v1/admin-web/business-plugins/capabilities")

        self.assertEqual(403, response.status_code)
        self.assertEqual("请选择管理工作区", response.json()["detail"])

    def test_business_plugin_capabilities_returns_safe_current_workspace_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        summary = AdminWebBusinessPluginCapabilitiesSummary(
            workspace=AdminWebWorkspaceSummary(
                workspace_id="tn_demo",
                kind="tenant",
                role="owner",
                title="Demo Store",
                tenant_public_id="tn_demo",
                bot_username="demo_bot",
                tenant_status="active",
                bot_status="active",
                supplier_enabled=True,
                reseller_enabled=True,
            ),
            workspace_id="tn_demo",
            workspace_kind="tenant",
            dynamic_loading_enabled=False,
            remote_code_enabled=False,
            real_external_integration_enabled=False,
            plugins=(
                _plugin_capability_item(),
                _plugin_capability_item(
                    plugin_id="payment_epay_compatible",
                    provider_name="epay_compatible",
                    kind="payment",
                    name="易支付兼容 支付插件",
                ),
            ),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.business_plugin_capabilities",
                new=AsyncMock(return_value=summary),
            ) as plugin_capabilities:
                response = client.get("/api/v1/admin-web/business-plugins/capabilities")

        self.assertEqual(200, response.status_code)
        plugin_capabilities.assert_awaited_once_with(
            session,
            telegram_user_id=123,
            workspace_id="tn_demo",
        )
        payload = response.json()
        self.assertEqual("tn_demo", payload["workspace_id"])
        self.assertEqual("tenant", payload["workspace_kind"])
        self.assertFalse(payload["dynamic_loading_enabled"])
        self.assertFalse(payload["remote_code_enabled"])
        self.assertFalse(payload["real_external_integration_enabled"])
        self.assertEqual("external_source_mcy_shop", payload["plugins"][0]["plugin_id"])
        self.assertEqual("mcy_shop", payload["plugins"][0]["provider_name"])
        self.assertEqual(1, payload["plugins"][0]["active_connection_count"])
        self.assertTrue(payload["plugins"][0]["capabilities"]["catalog_sync"])
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "config_encrypted",
            "credentials_encrypted",
            "credential_fields",
            "entrypoint",
            "app.services",
            "api_key",
            "secret",
            "token_hash",
            "raw_payload",
            "storage_key",
            "external_order_id",
            "payment_url",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_business_plugin_capabilities_rejects_non_admin_platform_workspace(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=456, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.business_plugin_capabilities",
                new=AsyncMock(side_effect=AdminWebSessionError("无权访问主 Bot 管理工作区")),
            ):
                response = client.get("/api/v1/admin-web/business-plugins/capabilities")

        self.assertEqual(403, response.status_code)
        self.assertEqual("无权访问主 Bot 管理工作区", response.json()["detail"])

    def test_tenant_external_source_connections_returns_safe_current_workspace_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        page = _external_source_connections_page(settings)

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_external_source_connections",
                new=AsyncMock(return_value=page),
            ) as list_connections:
                response = client.get("/api/v1/admin-web/tenant/external-source-connections?provider_name=mcy_shop")

        self.assertEqual(200, response.status_code)
        list_connections.assert_awaited_once_with(
            session,
            settings=settings,
            telegram_user_id=123,
            workspace_id="tn_demo",
            provider_name="mcy_shop",
        )
        payload = response.json()
        self.assertEqual("mcy_shop", payload["providers"][0]["provider_name"])
        self.assertEqual("Fixture Shop", payload["connections"][0]["display_name"])
        self.assertEqual(2, payload["connections"][0]["credential_field_count"])
        self.assertIn("connection_handle", payload["connections"][0])
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "connection_id",
            "credentials",
            "credential_fields",
            "credentials_encrypted",
            "api_key",
            "secret",
            "token",
            "raw_payload",
            "storage_key",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_create_external_source_connection_uses_origin_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        connection = _external_source_connections_page(settings).connections[0]

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_create_external_source_connection",
                new=AsyncMock(return_value=connection),
            ) as create_connection:
                response = client.post(
                    "/api/v1/admin-web/tenant/external-source-connections",
                    json={
                        "provider_name": "mcy_shop",
                        "source_key": "fixture",
                        "display_name": "Fixture Shop",
                        "credentials": {"base_url": "http://mcy-shop-fixture.local", "api_key": "plain-secret"},
                    },
                    headers=_origin_headers(),
                )

        self.assertEqual(200, response.status_code)
        create_connection.assert_awaited_once_with(
            session,
            settings=settings,
            telegram_user_id=123,
            workspace_id="tn_demo",
            provider_name="mcy_shop",
            source_key="fixture",
            display_name="Fixture Shop",
            credentials={"base_url": "http://mcy-shop-fixture.local", "api_key": "plain-secret"},
        )
        self.assertEqual(1, session.commit_count)
        response_text = response.text.lower()
        for forbidden in ("plain-secret", "api_key", "credentials", "tenant_id", "connection_id", "raw_payload"):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_create_external_source_connection_rejects_extra_internal_fields_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_create_external_source_connection",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.post(
                "/api/v1/admin-web/tenant/external-source-connections",
                json={
                    "provider_name": "mcy_shop",
                    "source_key": "fixture",
                    "display_name": "Fixture Shop",
                    "credentials": {"base_url": "http://mcy-shop-fixture.local"},
                    "tenant_id": 7,
                    "credentials_encrypted": "secret",
                },
                headers=_origin_headers(),
            )

        self.assertEqual(422, response.status_code)

    def test_tenant_create_external_source_connection_rejects_missing_origin_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)

        with patch(
            "app.web.admin_web.AdminWebService.tenant_create_external_source_connection",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.post(
                "/api/v1/admin-web/tenant/external-source-connections",
                json={
                    "provider_name": "mcy_shop",
                    "display_name": "Fixture Shop",
                    "credentials": {"base_url": "http://mcy-shop-fixture.local"},
                },
            )

        self.assertEqual(403, response.status_code)

    def test_tenant_disable_external_source_connection_uses_origin_handle_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        connection = _external_source_connections_page(settings).connections[0]

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_disable_external_source_connection",
                new=AsyncMock(return_value=connection),
            ) as disable_connection:
                response = client.post(
                    "/api/v1/admin-web/tenant/external-source-connections/disable",
                    json={"connection_handle": connection.connection_handle},
                    headers=_origin_headers(),
                )

        self.assertEqual(200, response.status_code)
        disable_connection.assert_awaited_once_with(
            session,
            settings=settings,
            telegram_user_id=123,
            workspace_id="tn_demo",
            connection_handle=connection.connection_handle,
        )
        self.assertEqual(1, session.commit_count)
        response_text = response.text.lower()
        for forbidden in ("tenant_id", "connection_id", "credentials", "api_key", "secret", "raw_payload"):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_external_source_catalog_sync_uses_origin_handle_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        connection = _external_source_connections_page(settings).connections[0]
        sync_result = _admin_web_external_catalog_sync_result()

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_sync_external_catalog",
                new=AsyncMock(return_value=sync_result),
            ) as sync_catalog:
                response = client.post(
                    "/api/v1/admin-web/tenant/external-sources/catalog/sync",
                    json={
                        "connection_handle": connection.connection_handle,
                        "cursor": "page-1",
                        "limit": 20,
                        "max_pages": 1,
                    },
                    headers=_origin_headers(),
                )

        self.assertEqual(200, response.status_code)
        sync_catalog.assert_awaited_once_with(
            session,
            settings=settings,
            telegram_user_id=123,
            workspace_id="tn_demo",
            connection_handle=connection.connection_handle,
            cursor="page-1",
            limit=20,
            max_pages=1,
        )
        self.assertEqual(1, session.commit_count)
        payload = response.json()
        self.assertEqual("mcy_shop", payload["provider_name"])
        self.assertEqual("fixture", payload["source_key"])
        self.assertEqual(1, payload["created_count"])
        self.assertEqual(2, payload["updated_count"])
        self.assertEqual(1, payload["skipped_count"])
        self.assertEqual(101, payload["products"][0]["product_id"])
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "connection_id",
            "connection_handle",
            "external_id",
            "external_source",
            "raw_payload",
            "credentials",
            "api_key",
            "password",
            "token",
            "secret",
            "storage_key",
            "delivery",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_external_source_catalog_sync_rejects_extra_internal_fields_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        connection = _external_source_connections_page(settings).connections[0]

        with patch(
            "app.web.admin_web.AdminWebService.tenant_sync_external_catalog",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.post(
                "/api/v1/admin-web/tenant/external-sources/catalog/sync",
                json={
                    "connection_handle": connection.connection_handle,
                    "tenant_id": 7,
                    "connection_id": 11,
                    "provider_name": "mcy_shop",
                    "source_key": "fixture",
                    "external_id": "sku-1",
                    "credentials": {"api_key": "plain-secret"},
                    "raw_payload": {"token": "plain-token"},
                    "storage_key": "exports/private.csv",
                    "delivery": {"items": ["card-secret"]},
                },
                headers=_origin_headers(),
            )

        self.assertEqual(422, response.status_code)

    def test_tenant_external_source_catalog_sync_rejects_missing_origin_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        connection = _external_source_connections_page(settings).connections[0]

        with patch(
            "app.web.admin_web.AdminWebService.tenant_sync_external_catalog",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.post(
                "/api/v1/admin-web/tenant/external-sources/catalog/sync",
                json={"connection_handle": connection.connection_handle},
            )

        self.assertEqual(403, response.status_code)

    def test_tenant_external_source_catalog_products_uses_cookie_session_handle_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        connection = _external_source_connections_page(settings).connections[0]
        products_page = _admin_web_external_source_catalog_products_page(settings)

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_external_source_catalog_products",
                new=AsyncMock(return_value=products_page),
            ) as catalog_products:
                response = client.get(
                    "/api/v1/admin-web/tenant/external-sources/catalog/products",
                    params={
                        "connection_handle": connection.connection_handle,
                        "limit": 20,
                        "offset": 0,
                    },
                )

        self.assertEqual(200, response.status_code)
        catalog_products.assert_awaited_once_with(
            session,
            settings=settings,
            telegram_user_id=123,
            workspace_id="tn_demo",
            connection_handle=connection.connection_handle,
            limit=20,
            offset=0,
        )
        self.assertEqual(0, session.commit_count)
        payload = response.json()
        self.assertEqual("Fixture Shop", payload["display_name"])
        self.assertEqual(1, payload["total_count"])
        self.assertEqual("Fixture Card", payload["items"][0]["name"])
        self.assertEqual("9.99000000", payload["items"][0]["price"])
        self.assertEqual(3, payload["items"][0]["available_count"])
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "connection_id",
            "external_id",
            "external_source",
            "raw_payload",
            "credentials",
            "api_key",
            "password",
            "token",
            "secret",
            "storage_key",
            "delivery_record_id",
            "delivery_content",
            "delivery_items",
            "inventory_item_id",
            "variant_id",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_external_source_catalog_sync_provider_error_returns_redacted_502(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        connection = _external_source_connections_page(settings).connections[0]

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_sync_external_catalog",
                new=AsyncMock(side_effect=ExternalSourceError("api_key=plain-secret")),
            ):
                response = client.post(
                    "/api/v1/admin-web/tenant/external-sources/catalog/sync",
                    json={"connection_handle": connection.connection_handle},
                    headers=_origin_headers(),
                )

        self.assertEqual(502, response.status_code)
        self.assertEqual(0, session.commit_count)
        self.assertEqual("外部源目录同步失败", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("api_key", response.text.lower())

    def test_tenant_update_payment_config_uses_current_workspace_origin_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        config = _payment_config_item(provider="epusdt_gmpay", merchant_id_masked="12***90")

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_update_payment_config",
                new=AsyncMock(return_value=config),
            ) as update_config:
                response = client.put(
                    "/api/v1/admin-web/tenant/payments/epusdt_gmpay/config",
                    json={
                        "base_url": "https://pay.example",
                        "pid": "1234567890",
                        "secret_key": "very-secret",
                        "token": "USDT",
                        "network": "TRC20",
                    },
                    headers=_origin_headers(),
                )

        self.assertEqual(200, response.status_code)
        update_config.assert_awaited_once_with(
            session,
            settings=settings,
            telegram_user_id=123,
            workspace_id="tn_demo",
            provider_name="epusdt_gmpay",
            config_payload={
                "base_url": "https://pay.example",
                "pid": "1234567890",
                "secret_key": "very-secret",
                "token": "USDT",
                "network": "TRC20",
            },
        )
        self.assertEqual(1, session.commit_count)
        response_text = response.text.lower()
        for forbidden in ("very-secret", "secret_key", "config_encrypted", "tenant_id", "raw_payload"):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_update_payment_config_rejects_unsupported_provider_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_update_payment_config",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.put(
                "/api/v1/admin-web/tenant/payments/token188/config",
                json={"gateway_url": "https://pay.example", "merchant_id": "mch", "key": "secret"},
                headers=_origin_headers(),
            )

        self.assertEqual(400, response.status_code)

    def test_tenant_update_payment_config_rejects_missing_origin_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)

        with patch(
            "app.web.admin_web.AdminWebService.tenant_update_payment_config",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.put(
                "/api/v1/admin-web/tenant/payments/epay_compatible/config",
                json={"gateway_url": "https://pay.example", "merchant_id": "mch", "key": "secret"},
            )

        self.assertEqual(403, response.status_code)

    def test_tenant_update_payment_config_rejects_extra_internal_fields_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_update_payment_config",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.put(
                "/api/v1/admin-web/tenant/payments/epay_compatible/config",
                json={
                    "gateway_url": "https://pay.example",
                    "merchant_id": "mch",
                    "key": "secret",
                    "tenant_id": 7,
                },
                headers=_origin_headers(),
            )

        self.assertEqual(422, response.status_code)

    def test_tenant_disable_payment_config_uses_current_workspace_and_origin_gate(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        config = _payment_config_item(provider="epay_compatible", display_name="易支付兼容", enabled=False)

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_disable_payment_config",
                new=AsyncMock(return_value=config),
            ) as disable_config:
                response = client.delete(
                    "/api/v1/admin-web/tenant/payments/epay_compatible/config",
                    headers=_origin_headers(),
                )

        self.assertEqual(200, response.status_code)
        disable_config.assert_awaited_once_with(
            session,
            settings=settings,
            telegram_user_id=123,
            workspace_id="tn_demo",
            provider_name="epay_compatible",
        )
        self.assertEqual(1, session.commit_count)
        self.assertFalse(response.json()["enabled"])

    def test_tenant_orders_returns_safe_current_workspace_items(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        orders = AdminWebTenantOrdersPage(
            total_count=1,
            limit=8,
            offset=8,
            items=(
                AdminWebTenantOrderItem(
                    out_trade_no="ORD123",
                    source_type="reseller",
                    amount=Decimal("12.5"),
                    currency="USDT",
                    status="paid",
                    payment_mode="platform_escrow",
                    buyer_telegram_user_id=456,
                    created_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
                    expires_at=datetime(2026, 6, 1, 12, 15, tzinfo=timezone.utc),
                    paid_at=datetime(2026, 6, 1, 12, 5, tzinfo=timezone.utc),
                    delivered_at=None,
                ),
            ),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_orders",
                new=AsyncMock(return_value=orders),
            ) as tenant_orders:
                response = client.get(
                    "/api/v1/admin-web/tenant/orders",
                    params={
                        "limit": 8,
                        "offset": 8,
                        "out_trade_no": "ORD",
                        "status": "paid",
                        "source_type": "reseller",
                        "payment_mode": "platform_escrow",
                    },
                )

        self.assertEqual(200, response.status_code)
        tenant_orders.assert_awaited_once_with(
            session,
            telegram_user_id=123,
            workspace_id="tn_demo",
            limit=8,
            offset=8,
            out_trade_no="ORD",
            status="paid",
            source_type="reseller",
            payment_mode="platform_escrow",
        )
        payload = response.json()
        self.assertEqual(1, payload["total_count"])
        self.assertEqual(8, payload["offset"])
        self.assertEqual("ORD123", payload["items"][0]["out_trade_no"])
        self.assertEqual("reseller", payload["items"][0]["source_type"])
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "order_id",
            "self_product_id",
            "product_variant_id",
            "locked_inventory_item_id",
            "supplier_tenant_id",
            "reseller_product_id",
            "payment_url",
            "provider_trade_no",
            "payload_json",
            "raw_payload",
            "token",
            "secret",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_orders_clamps_large_limit_before_service(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        orders = AdminWebTenantOrdersPage(total_count=0, limit=100, offset=0, items=())

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_orders",
                new=AsyncMock(return_value=orders),
            ) as tenant_orders:
                response = client.get("/api/v1/admin-web/tenant/orders?limit=500")

        self.assertEqual(200, response.status_code)
        tenant_orders.assert_awaited_once_with(
            session,
            telegram_user_id=123,
            workspace_id="tn_demo",
            limit=100,
            offset=0,
            out_trade_no=None,
            status=None,
            source_type=None,
            payment_mode=None,
        )
        self.assertEqual(100, response.json()["limit"])

    def test_tenant_order_diagnostics_returns_safe_current_workspace_summary(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        diagnostics = AdminWebTenantOrderDiagnostics(
            out_trade_no="ORD123",
            source_type="self",
            status="paid",
            payment_mode="tenant_direct",
            payment_provider="epusdt_gmpay",
            amount=Decimal("12.50"),
            currency="USDT",
            created_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            expires_at=datetime(2026, 6, 1, 12, 15, tzinfo=timezone.utc),
            paid_at=datetime(2026, 6, 1, 12, 5, tzinfo=timezone.utc),
            delivered_at=None,
            payment_count=1,
            callback_count=1,
            callback_status_counts={"failed": 1},
            payments=(
                AdminWebOrderPaymentDiagnosticItem(
                    provider="epusdt_gmpay",
                    status="created",
                    amount=Decimal("12.50"),
                    currency="USDT",
                    has_payment_url=True,
                    created_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
                    paid_at=None,
                ),
            ),
            callbacks=(
                AdminWebOrderPaymentCallbackDiagnosticItem(
                    provider="epusdt_gmpay",
                    process_status="failed",
                    failure_reason="签名校验失败",
                    created_at=datetime(2026, 6, 1, 12, 1, tzinfo=timezone.utc),
                    processed_at=None,
                ),
            ),
            delivery=AdminWebOrderDeliveryDiagnosticItem(
                delivery_type="card_pool",
                status="failed",
                failure_reason="库存不足",
                has_inventory_item=False,
                has_uploaded_file=False,
                has_telegram_chat=False,
                created_at=datetime(2026, 6, 1, 12, 5, tzinfo=timezone.utc),
                updated_at=datetime(2026, 6, 1, 12, 6, tzinfo=timezone.utc),
                sent_at=None,
            ),
            external_fulfillment=AdminWebOrderExternalFulfillmentDiagnosticItem(
                expected=True,
                attempt_count=2,
                latest_attempt_status="failed",
                latest_attempt_trigger="auto",
                latest_attempt_at=datetime(2026, 6, 1, 12, 2, tzinfo=timezone.utc),
                latest_failure_stage="create_order",
                latest_failure_category="upstream_timeout",
                latest_failure_retryable=True,
                latest_upstream_status_code=504,
                latest_item_count=0,
                latest_delivery_record_linked=False,
            ),
            trc20_direct=AdminWebOrderTrc20DirectDiagnosticItem(
                expected=False,
                transfer_count=0,
                latest_match_status=None,
                latest_confirmations=None,
                latest_matched_at=None,
                latest_amount=None,
            ),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_order_diagnostics",
                new=AsyncMock(return_value=diagnostics),
            ) as tenant_order_diagnostics:
                response = client.get("/api/v1/admin-web/tenant/orders/ORD123/diagnostics")

        self.assertEqual(200, response.status_code)
        tenant_order_diagnostics.assert_awaited_once_with(
            session,
            telegram_user_id=123,
            workspace_id="tn_demo",
            out_trade_no="ORD123",
        )
        payload = response.json()
        self.assertEqual("ORD123", payload["out_trade_no"])
        self.assertEqual(1, payload["payment_count"])
        self.assertEqual(True, payload["payments"][0]["has_payment_url"])
        self.assertEqual("auto", payload["external_fulfillment"]["latest_attempt_trigger"])
        response_keys = _json_keys(payload)
        for forbidden in (
            "tenant_id",
            "order_id",
            "payment_id",
            "callback_id",
            "delivery_record_id",
            "inventory_item_id",
            "uploaded_file_id",
            "telegram_chat_id",
            "payment_url",
            "provider_trade_no",
            "payload_json",
            "payload_hash",
            "raw_payload",
            "external_order_id",
            "connection_id",
            "failure_fingerprint",
            "credentials",
            "token",
            "secret",
            "api_key",
        ):
            self.assertNotIn(forbidden, response_keys)

    def test_tenant_order_diagnostics_requires_current_clone_bot_workspace(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_order_diagnostics",
            new=AsyncMock(side_effect=AssertionError("不应查询订单排障")),
        ):
            response = client.get("/api/v1/admin-web/tenant/orders/ORD123/diagnostics")

        self.assertEqual(403, response.status_code)
        self.assertEqual("请选择克隆 Bot 工作区", response.json()["detail"])

    def test_tenant_order_diagnostics_returns_403_for_cross_tenant_or_missing_order(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_order_diagnostics",
                new=AsyncMock(side_effect=AdminWebSessionError("订单不存在或无权限")),
            ):
                response = client.get("/api/v1/admin-web/tenant/orders/ORD404/diagnostics")

        self.assertEqual(403, response.status_code)
        self.assertEqual("订单不存在或无权限", response.json()["detail"])

    def test_tenant_order_observability_returns_safe_current_workspace_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        observability = AdminWebTenantOrderObservability(
            limit=8,
            callback_failures=(
                AdminWebPaymentCallbackFailureItem(
                    created_at=datetime(2026, 6, 1, 12, 1, tzinfo=timezone.utc),
                    processed_at=None,
                    out_trade_no="ORD123",
                    order_status="paid",
                    provider="epusdt_gmpay",
                    process_status="failed",
                    failure_reason="签名校验失败",
                ),
            ),
            callback_rejections=(
                AdminWebPaymentCallbackRejectionItem(
                    created_at=datetime(2026, 6, 1, 12, 2, tzinfo=timezone.utc),
                    provider="epay_compatible",
                    reason_category="invalid_callback",
                    failure_reason="支付回调参数无效",
                    http_status=400,
                    out_trade_no="ORD124",
                    order_status="pending",
                    payload_field_count=5,
                ),
            ),
            external_fulfillment_attempts=(
                AdminWebExternalFulfillmentAttemptItem(
                    created_at=datetime(2026, 6, 1, 12, 3, tzinfo=timezone.utc),
                    started_at=datetime(2026, 6, 1, 12, 3, tzinfo=timezone.utc),
                    finished_at=datetime(2026, 6, 1, 12, 4, tzinfo=timezone.utc),
                    out_trade_no="ORD125",
                    provider_name="mcy_shop",
                    source_key="fixture",
                    attempt_source="auto",
                    status="failed",
                    imported=False,
                    item_count=0,
                    failure_reason="上游超时",
                    failure_stage="create_order",
                    failure_category="upstream_timeout",
                    failure_retryable=True,
                    upstream_status_code=504,
                ),
            ),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_order_observability",
                new=AsyncMock(return_value=observability),
            ) as tenant_order_observability:
                response = client.get(
                    "/api/v1/admin-web/tenant/orders/observability",
                    params={"limit": 8, "out_trade_no": "ORD123"},
                )

        self.assertEqual(200, response.status_code)
        tenant_order_observability.assert_awaited_once_with(
            session,
            telegram_user_id=123,
            workspace_id="tn_demo",
            limit=8,
            out_trade_no="ORD123",
        )
        payload = response.json()
        self.assertEqual(8, payload["limit"])
        self.assertEqual("ORD123", payload["callback_failures"][0]["out_trade_no"])
        self.assertEqual("epay_compatible", payload["callback_rejections"][0]["provider"])
        self.assertEqual("mcy_shop", payload["external_fulfillment_attempts"][0]["provider_name"])
        response_keys = _json_keys(payload)
        for forbidden in (
            "tenant_id",
            "order_id",
            "callback_id",
            "audit_log_id",
            "attempt_id",
            "product_id",
            "connection_id",
            "external_product_id",
            "external_order_id",
            "delivery_record_id",
            "failure_fingerprint",
            "provider_trade_no",
            "payment_url",
            "payload",
            "payload_json",
            "raw_payload",
            "credentials",
            "api_key",
            "token",
            "secret",
            "storage_key",
            "items",
            "message",
        ):
            self.assertNotIn(forbidden, response_keys)

    def test_tenant_order_observability_requires_current_clone_bot_workspace(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_order_observability",
            new=AsyncMock(side_effect=AssertionError("不应查询订单观测")),
        ):
            response = client.get("/api/v1/admin-web/tenant/orders/observability")

        self.assertEqual(403, response.status_code)
        self.assertEqual("请选择克隆 Bot 工作区", response.json()["detail"])

    def test_tenant_order_observability_value_error_returns_400_without_secret(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_order_observability",
                new=AsyncMock(side_effect=ValueError("secret token raw payload")),
            ):
                response = client.get("/api/v1/admin-web/tenant/orders/observability")

        self.assertEqual(400, response.status_code)
        self.assertEqual("订单观测查询参数无效", response.json()["detail"])
        self.assertNotIn("secret", response.text.lower())
        self.assertNotIn("token", response.text.lower())

    def test_tenant_subscription_panel_requires_current_clone_bot_workspace(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_subscription_dashboard",
            new=AsyncMock(side_effect=AssertionError("不应查询订阅面板")),
        ):
            response = client.get("/api/v1/admin-web/tenant/subscription")

        self.assertEqual(403, response.status_code)
        self.assertEqual("请选择克隆 Bot 工作区", response.json()["detail"])

    def test_tenant_subscription_panel_returns_safe_current_workspace_status_and_invoices(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        dashboard = AdminWebTenantSubscriptionDashboard(
            status="active",
            plan_code="default_monthly",
            plan_name="默认月付套餐",
            monthly_price=Decimal("19.90"),
            currency="USDT",
            trial_days=7,
            grace_days=3,
            trial_ends_at=None,
            current_period_ends_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            subscription_ends_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            grace_ends_at=None,
            suspended_at=None,
            data_retention_until=None,
            invoices=(
                AdminWebTenantSubscriptionInvoiceItem(
                    out_trade_no="SUB202606010001",
                    amount=Decimal("19.90"),
                    currency="USDT",
                    status="paid",
                    paid_at=datetime(2026, 6, 1, 12, 5, tzinfo=timezone.utc),
                    created_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
                ),
            ),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_subscription_dashboard",
                new=AsyncMock(return_value=dashboard),
            ) as tenant_subscription_dashboard:
                response = client.get("/api/v1/admin-web/tenant/subscription?invoice_limit=50")

        self.assertEqual(200, response.status_code)
        tenant_subscription_dashboard.assert_awaited_once_with(
            session,
            telegram_user_id=123,
            workspace_id="tn_demo",
            invoice_limit=50,
        )
        payload = response.json()
        self.assertEqual("active", payload["status"])
        self.assertEqual("default_monthly", payload["plan_code"])
        self.assertEqual("SUB202606010001", payload["invoices"][0]["out_trade_no"])
        response_keys = _json_keys(payload)
        for forbidden in (
            "tenant_id",
            "plan_id",
            "subscription_id",
            "invoice_id",
            "payment_id",
            "order_id",
            "payment_url",
            "provider_trade_no",
            "payload",
            "raw_payload",
            "token",
            "secret",
            "api_key",
            "credentials",
        ):
            self.assertNotIn(forbidden, response_keys)

    def test_tenant_subscription_renewal_order_requires_current_clone_bot_workspace(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_create_subscription_renewal_order",
            new=AsyncMock(side_effect=AssertionError("不应创建续费订单")),
        ):
            response = client.post(
                "/api/v1/admin-web/tenant/subscription/renewal-orders",
                json={"months": 1},
                headers=_origin_headers(),
            )

        self.assertEqual(403, response.status_code)
        self.assertEqual("请选择克隆 Bot 工作区", response.json()["detail"])

    def test_tenant_subscription_renewal_order_uses_current_workspace_origin_and_returns_payment_link(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        renewal_order = AdminWebSubscriptionRenewalOrder(
            out_trade_no="SUB_123",
            amount=Decimal("19.90"),
            currency="USDT",
            months=1,
            expires_at=datetime(2026, 6, 1, 12, 30, tzinfo=timezone.utc),
            payment_available=True,
            payment_provider="epusdt_gmpay",
            payment_url="https://pay.example/SUB_123",
            payment_failure_reason=None,
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_create_subscription_renewal_order",
                new=AsyncMock(return_value=renewal_order),
            ) as create_renewal_order:
                response = client.post(
                    "/api/v1/admin-web/tenant/subscription/renewal-orders",
                    json={"months": 1},
                    headers=_origin_headers(),
                )

        self.assertEqual(200, response.status_code)
        create_renewal_order.assert_awaited_once_with(
            session,
            settings=settings,
            telegram_user_id=123,
            workspace_id="tn_demo",
            months=1,
        )
        self.assertEqual(1, session.commit_count)
        payload = response.json()
        self.assertEqual("SUB_123", payload["out_trade_no"])
        self.assertEqual("19.90", payload["amount"])
        self.assertTrue(payload["payment_available"])
        self.assertEqual("https://pay.example/SUB_123", payload["payment_url"])
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "subscription_id",
            "plan_id",
            "invoice_id",
            "order_id",
            "payment_id",
            "provider_trade_no",
            "payload_json",
            "raw_payload",
            "token",
            "secret",
            "api_key",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_subscription_renewal_order_rejects_extra_fields_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_create_subscription_renewal_order",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.post(
                "/api/v1/admin-web/tenant/subscription/renewal-orders",
                json={"months": 1, "tenant_id": 7, "payment_url": "https://evil.example"},
                headers=_origin_headers(),
            )

        self.assertEqual(422, response.status_code)

    def test_tenant_subscription_renewal_order_rejects_missing_or_untrusted_origin(self) -> None:
        settings = _settings()
        client = _client(settings)

        with patch(
            "app.web.admin_web.AdminWebService.tenant_create_subscription_renewal_order",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            missing_origin_response = client.post(
                "/api/v1/admin-web/tenant/subscription/renewal-orders",
                json={"months": 1},
            )
            untrusted_origin_response = client.post(
                "/api/v1/admin-web/tenant/subscription/renewal-orders",
                json={"months": 1},
                headers=_origin_headers("https://evil.example"),
            )

        self.assertEqual(403, missing_origin_response.status_code)
        self.assertEqual("缺少管理后台请求来源", missing_origin_response.json()["detail"])
        self.assertEqual(403, untrusted_origin_response.status_code)
        self.assertEqual("管理后台请求来源不允许", untrusted_origin_response.json()["detail"])

    def test_tenant_subscription_renewal_order_value_error_returns_400_without_commit(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_create_subscription_renewal_order",
                new=AsyncMock(side_effect=ValueError("secret_key=plain")),
            ):
                response = client.post(
                    "/api/v1/admin-web/tenant/subscription/renewal-orders",
                    json={"months": 1},
                    headers=_origin_headers(),
                )

        self.assertEqual(400, response.status_code)
        self.assertEqual("订阅续费参数无效", response.json()["detail"])
        self.assertEqual(0, session.commit_count)
        self.assertNotIn("plain", response.text)

    def test_tenant_finance_panel_requires_current_clone_bot_workspace(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_finance_dashboard",
            new=AsyncMock(side_effect=AssertionError("不应查询财务面板")),
        ):
            response = client.get("/api/v1/admin-web/tenant/finance")

        self.assertEqual(403, response.status_code)
        self.assertEqual("请选择克隆 Bot 工作区", response.json()["detail"])

    def test_tenant_finance_panel_returns_safe_balance_audit_and_withdrawals(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        dashboard = AdminWebTenantFinanceDashboard(
            balance=AdminWebTenantFinanceBalanceItem(
                account_type="main",
                currency="USDT",
                pending_balance=Decimal("1.25"),
                available_balance=Decimal("9.50"),
                frozen_balance=Decimal("2.00"),
            ),
            audit=AdminWebTenantFinanceAuditItem(
                account_type="main",
                currency="USDT",
                stored_pending_balance=Decimal("1.25"),
                stored_available_balance=Decimal("9.50"),
                stored_frozen_balance=Decimal("2.00"),
                computed_pending_balance=Decimal("1.25"),
                computed_available_balance=Decimal("9.50"),
                computed_frozen_balance=Decimal("2.00"),
                pending_difference=Decimal("0"),
                available_difference=Decimal("0"),
                frozen_difference=Decimal("0"),
                is_balanced=True,
            ),
            withdrawals=(
                AdminWebTenantWithdrawalItem(
                    amount=Decimal("2.00"),
                    currency="USDT",
                    network="TRC20",
                    address_masked="TAbc12***XyZ789",
                    status="pending",
                    requested_at=datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc),
                    reviewed_at=None,
                    completed_at=None,
                ),
            ),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_finance_dashboard",
                new=AsyncMock(return_value=dashboard),
            ) as tenant_finance_dashboard:
                response = client.get("/api/v1/admin-web/tenant/finance?withdrawal_limit=50")

        self.assertEqual(200, response.status_code)
        tenant_finance_dashboard.assert_awaited_once_with(
            session,
            telegram_user_id=123,
            workspace_id="tn_demo",
            withdrawal_limit=50,
        )
        payload = response.json()
        self.assertEqual("9.50", payload["balance"]["available_balance"])
        self.assertTrue(payload["audit"]["is_balanced"])
        self.assertEqual("TAbc12***XyZ789", payload["withdrawals"][0]["address_masked"])
        response_keys = _json_keys(payload)
        for forbidden in (
            "tenant_id",
            "ledger_account_id",
            "account_id",
            "ledger_entry_id",
            "withdrawal_id",
            "address",
            "address_encrypted",
            "admin_note",
            "internal_note",
            "payout_reference",
            "payout_proof_url",
            "idempotency_key",
            "actor_user_id",
            "metadata_json",
            "raw_payload",
            "token",
            "secret",
            "api_key",
        ):
            self.assertNotIn(forbidden, response_keys)

    def test_tenant_audit_logs_requires_current_clone_bot_workspace(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_audit_logs",
            new=AsyncMock(side_effect=AssertionError("不应查询租户审计日志")),
        ):
            response = client.get("/api/v1/admin-web/tenant/audit-logs")

        self.assertEqual(403, response.status_code)
        self.assertEqual("请选择克隆 Bot 工作区", response.json()["detail"])

    def test_tenant_audit_logs_returns_safe_current_workspace_items(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        page = AdminWebTenantAuditLogsPage(
            limit=50,
            items=(
                AdminWebTenantAuditLogItem(
                    created_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
                    actor_telegram_user_id=456,
                    actor_username="owner",
                    action="product.update",
                    target_type="product",
                    metadata={"status": "on", "out_trade_no": "ORD123"},
                ),
            ),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_audit_logs",
                new=AsyncMock(return_value=page),
            ) as tenant_audit_logs:
                response = client.get(
                    "/api/v1/admin-web/tenant/audit-logs",
                    params={"limit": 50, "action": "product.update", "target_type": "product"},
                )

        self.assertEqual(200, response.status_code)
        tenant_audit_logs.assert_awaited_once_with(
            session,
            telegram_user_id=123,
            workspace_id="tn_demo",
            limit=50,
            action="product.update",
            target_type="product",
        )
        payload = response.json()
        self.assertEqual(50, payload["limit"])
        self.assertEqual("product.update", payload["items"][0]["action"])
        self.assertEqual("2026-06-01T12:00:00+00:00", payload["items"][0]["created_at"])
        self.assertEqual({"status": "on", "out_trade_no": "ORD123"}, payload["items"][0]["metadata"])
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "actor_user_id",
            "audit_log_id",
            "target_id",
            "metadata_json",
            "raw_payload",
            "payload_json",
            "token",
            "secret",
            "api_key",
            "storage_key",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_risk_panel_requires_current_clone_bot_workspace(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_risk_dashboard",
            new=AsyncMock(side_effect=AssertionError("不应查询租户风控面板")),
        ):
            response = client.get("/api/v1/admin-web/tenant/risk")

        self.assertEqual(403, response.status_code)
        self.assertEqual("请选择克隆 Bot 工作区", response.json()["detail"])

    def test_tenant_risk_panel_returns_safe_current_workspace_items(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        dashboard = AdminWebTenantRiskDashboard(
            status=None,
            limit=100,
            disputes=(
                AdminWebTenantRiskDisputeItem(
                    out_trade_no="ORD123",
                    buyer_telegram_user_id=456,
                    source_type="self",
                    order_status="paid",
                    amount=Decimal("9.90"),
                    currency="USDT",
                    status="open",
                    reason="买家未收到",
                    resolution=None,
                    created_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
                    updated_at=datetime(2026, 6, 1, 12, 5, tzinfo=timezone.utc),
                ),
            ),
            after_sales=(
                AdminWebTenantRiskAfterSaleItem(
                    out_trade_no="ORD456",
                    buyer_telegram_user_id=789,
                    source_type="reseller",
                    order_status="delivered",
                    amount=Decimal("19.90"),
                    currency="USDT",
                    case_type="refund",
                    status="reviewing",
                    requested_amount=Decimal("10.00"),
                    refunded_amount=Decimal("0"),
                    reason="申请部分退款",
                    resolution="客服处理中",
                    created_at=datetime(2026, 6, 2, 13, 0, tzinfo=timezone.utc),
                    updated_at=datetime(2026, 6, 2, 13, 5, tzinfo=timezone.utc),
                ),
            ),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_risk_dashboard",
                new=AsyncMock(return_value=dashboard),
            ) as tenant_risk_dashboard:
                response = client.get(
                    "/api/v1/admin-web/tenant/risk",
                    params={"status": "all", "limit": 500},
                )

        self.assertEqual(200, response.status_code)
        self.assertEqual(0, session.commit_count)
        tenant_risk_dashboard.assert_awaited_once_with(
            session,
            telegram_user_id=123,
            workspace_id="tn_demo",
            status="all",
            limit=100,
        )
        payload = response.json()
        self.assertEqual("all", payload["status"])
        self.assertEqual(100, payload["limit"])
        self.assertEqual("ORD123", payload["disputes"][0]["out_trade_no"])
        self.assertEqual("买家未收到", payload["disputes"][0]["reason"])
        self.assertEqual("ORD456", payload["after_sales"][0]["out_trade_no"])
        self.assertEqual("10.00", payload["after_sales"][0]["requested_amount"])
        response_keys = _json_keys(payload)
        for forbidden in (
            "tenant_id",
            "tenant_bot_id",
            "owner_user_id",
            "dispute_id",
            "case_id",
            "order_id",
            "refund_id",
            "payment_id",
            "callback_id",
            "delivery_record_id",
            "ledger_entry_id",
            "actor_user_id",
            "metadata_json",
            "payload_json",
            "raw_payload",
            "raw_request",
            "raw_response",
            "payment_url",
            "provider_trade_no",
            "idempotency_key",
            "encrypted_token",
            "token_hash",
            "webhook_secret",
            "api_key",
            "secret_key",
            "plain_key",
            "token",
            "secret",
            "credentials",
            "credentials_encrypted",
            "config_encrypted",
            "authorization",
            "cookie",
            "storage_key",
            "content_encrypted",
            "card_secret",
        ):
            self.assertNotIn(forbidden, response_keys)

    def test_tenant_risk_panel_value_error_returns_400_without_secret(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_risk_dashboard",
                new=AsyncMock(side_effect=ValueError("token=plain-secret")),
            ):
                response = client.get(
                    "/api/v1/admin-web/tenant/risk",
                    params={"status": "bad"},
                )

        self.assertEqual(400, response.status_code)
        self.assertEqual("风控查询参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("token=", response.text)

    def test_tenant_report_export_jobs_requires_current_clone_bot_workspace(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_report_export_jobs",
            new=AsyncMock(side_effect=AssertionError("不应查询租户报表任务")),
        ):
            response = client.get("/api/v1/admin-web/tenant/reports/export-jobs")

        self.assertEqual(403, response.status_code)
        self.assertEqual("请选择克隆 Bot 工作区", response.json()["detail"])

    def test_tenant_report_export_jobs_returns_safe_current_workspace_items(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        page = AdminWebTenantReportExportJobsPage(
            status=None,
            report_type="orders",
            limit=100,
            export_jobs=(
                AdminWebTenantReportExportJobItem(
                    report_type="orders",
                    scope_type="tenant",
                    status="completed",
                    row_count=23,
                    download_available=True,
                    download_handle="safe-download-handle",
                    failure_reason=None,
                    expires_at=datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc),
                    created_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
                    started_at=datetime(2026, 6, 1, 12, 1, tzinfo=timezone.utc),
                    finished_at=datetime(2026, 6, 1, 12, 2, tzinfo=timezone.utc),
                ),
                AdminWebTenantReportExportJobItem(
                    report_type="payments",
                    scope_type="tenant",
                    status="failed",
                    row_count=0,
                    download_available=False,
                    download_handle=None,
                    failure_reason="报表导出失败",
                    expires_at=None,
                    created_at=datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc),
                    started_at=datetime(2026, 6, 2, 12, 1, tzinfo=timezone.utc),
                    finished_at=datetime(2026, 6, 2, 12, 2, tzinfo=timezone.utc),
                ),
            ),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_report_export_jobs",
                new=AsyncMock(return_value=page),
            ) as tenant_report_export_jobs:
                response = client.get(
                    "/api/v1/admin-web/tenant/reports/export-jobs",
                    params={"status": "all", "report_type": "orders", "limit": 500},
                )

        self.assertEqual(200, response.status_code)
        self.assertEqual(0, session.commit_count)
        tenant_report_export_jobs.assert_awaited_once_with(
            session,
            settings=settings,
            telegram_user_id=123,
            workspace_id="tn_demo",
            status="all",
            report_type="orders",
            limit=100,
        )
        payload = response.json()
        self.assertEqual("all", payload["status"])
        self.assertEqual("orders", payload["report_type"])
        self.assertEqual(100, payload["limit"])
        self.assertEqual("orders", payload["export_jobs"][0]["report_type"])
        self.assertTrue(payload["export_jobs"][0]["download_available"])
        self.assertEqual("safe-download-handle", payload["export_jobs"][0]["download_handle"])
        self.assertIsNone(payload["export_jobs"][1]["download_handle"])
        self.assertEqual("报表导出失败", payload["export_jobs"][1]["failure_reason"])
        response_keys = _json_keys(payload)
        for forbidden in (
            "export_job_id",
            "tenant_id",
            "requested_by_user_id",
            "filename",
            "download_url",
            "download_token",
            "storage_key",
            "error_message",
            "local_path",
            "path",
            "payload",
            "payload_json",
            "raw_payload",
            "raw_request",
            "raw_response",
            "payment_url",
            "provider_trade_no",
            "token",
            "secret",
            "secret_key",
            "api_key",
            "authorization",
            "cookie",
            "credential",
            "credentials",
            "plain_key",
            "tenant_bot_id",
            "owner_user_id",
            "encrypted_token",
            "token_hash",
            "webhook_secret",
        ):
            self.assertNotIn(forbidden, response_keys)
            self.assertNotIn(forbidden, response.text)

    def test_tenant_report_export_jobs_value_error_returns_400_without_secret(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_report_export_jobs",
                new=AsyncMock(side_effect=ValueError("storage_key=/exports/tenant_7/private.csv token=plain-secret")),
            ):
                response = client.get(
                    "/api/v1/admin-web/tenant/reports/export-jobs",
                    params={"status": "bad"},
                )

        self.assertEqual(400, response.status_code)
        self.assertEqual("报表任务查询参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("storage_key", response.text)

    def test_tenant_report_export_download_requires_current_clone_bot_workspace(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_report_export_download_file",
            new=AsyncMock(side_effect=AssertionError("不应下载租户报表")),
        ):
            response = client.post(
                "/api/v1/admin-web/tenant/reports/export-jobs/download",
                json={"download_handle": "safe-download-handle"},
                headers=_origin_headers(),
            )

        self.assertEqual(403, response.status_code)
        self.assertEqual("请选择克隆 Bot 工作区", response.json()["detail"])

    def test_tenant_report_export_download_rejects_missing_origin_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_report_export_download_file",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.post(
                "/api/v1/admin-web/tenant/reports/export-jobs/download",
                json={"download_handle": "safe-download-handle"},
            )

        self.assertEqual(403, response.status_code)

    def test_tenant_report_export_download_streams_current_tenant_file_with_safe_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = _settings(storage_root=tmp_dir)
            session = _FakeSession()
            client = _client(settings)
            codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
            client.cookies.set(
                ADMIN_WEB_SESSION_COOKIE_NAME,
                codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
            )
            report_path = Path(tmp_dir) / "exports" / "tenant_7" / "81_orders_tenant_7_20260601.csv"
            report_path.parent.mkdir(parents=True)
            report_path.write_text("out_trade_no,amount\nORD123,10.00\n", encoding="utf-8")
            file_info = AdminWebTenantReportExportDownloadFile(
                storage_key="exports/tenant_7/81_orders_tenant_7_20260601.csv",
                filename="orders-report.csv",
            )

            with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
                with patch(
                    "app.web.admin_web.AdminWebService.tenant_report_export_download_file",
                    new=AsyncMock(return_value=file_info),
                ) as download_file:
                    response = client.post(
                        "/api/v1/admin-web/tenant/reports/export-jobs/download",
                        json={"download_handle": "safe-download-handle"},
                        headers=_origin_headers(),
                    )

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, session.commit_count)
        download_file.assert_awaited_once_with(
            session,
            settings=settings,
            telegram_user_id=123,
            workspace_id="tn_demo",
            download_handle="safe-download-handle",
        )
        self.assertEqual("out_trade_no,amount\nORD123,10.00\n", response.text)
        disposition = response.headers.get("content-disposition", "")
        self.assertIn("orders-report.csv", disposition)
        self.assertNotIn("tenant_7", disposition)

    def test_tenant_report_export_download_hides_handle_and_storage_errors(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_report_export_download_file",
                new=AsyncMock(side_effect=ValueError("storage_key=/exports/tenant_7/private.csv token=plain-secret")),
            ):
                response = client.post(
                    "/api/v1/admin-web/tenant/reports/export-jobs/download",
                    json={"download_handle": "tampered-download-handle"},
                    headers=_origin_headers(),
                )

        self.assertEqual(403, response.status_code)
        self.assertEqual("报表文件暂不可下载", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("storage_key", response.text)

    def test_tenant_create_report_export_job_requires_current_clone_bot_workspace(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_create_report_export_job",
            new=AsyncMock(side_effect=AssertionError("不应创建租户报表任务")),
        ):
            response = client.post(
                "/api/v1/admin-web/tenant/reports/export-jobs",
                json={"report_type": "orders"},
                headers=_origin_headers(),
            )

        self.assertEqual(403, response.status_code)
        self.assertEqual("请选择克隆 Bot 工作区", response.json()["detail"])

    def test_tenant_create_report_export_job_uses_current_workspace_origin_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        job = AdminWebTenantReportExportJobItem(
            report_type="orders",
            scope_type="tenant",
            status="pending",
            row_count=0,
            download_available=False,
            download_handle=None,
            failure_reason=None,
            expires_at=None,
            created_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            started_at=None,
            finished_at=None,
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_create_report_export_job",
                new=AsyncMock(return_value=job),
            ) as tenant_create_report_export_job:
                response = client.post(
                    "/api/v1/admin-web/tenant/reports/export-jobs",
                    json={"report_type": "orders"},
                    headers=_origin_headers(),
                )

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, session.commit_count)
        tenant_create_report_export_job.assert_awaited_once_with(
            session,
            settings=settings,
            telegram_user_id=123,
            workspace_id="tn_demo",
            report_type="orders",
        )
        payload = response.json()
        self.assertEqual("orders", payload["report_type"])
        self.assertEqual("tenant", payload["scope_type"])
        self.assertEqual("pending", payload["status"])
        for forbidden in (
            "export_job_id",
            "tenant_id",
            "requested_by_user_id",
            "filename",
            "download_url",
            "download_token",
            "storage_key",
            "error_message",
            "token",
            "secret",
            "api_key",
        ):
            self.assertNotIn(forbidden, response.text)

    def test_tenant_create_report_export_job_rejects_extra_fields_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_create_report_export_job",
            new=AsyncMock(side_effect=AssertionError("不应创建租户报表任务")),
        ):
            response = client.post(
                "/api/v1/admin-web/tenant/reports/export-jobs",
                json={"report_type": "orders", "tenant_id": 7},
                headers=_origin_headers(),
            )

        self.assertEqual(422, response.status_code)

    def test_tenant_create_report_export_job_rejects_missing_or_untrusted_origin(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        payload = {"report_type": "orders"}

        with patch(
            "app.web.admin_web.AdminWebService.tenant_create_report_export_job",
            new=AsyncMock(side_effect=AssertionError("不应创建租户报表任务")),
        ):
            missing_origin_response = client.post(
                "/api/v1/admin-web/tenant/reports/export-jobs",
                json=payload,
            )
            untrusted_origin_response = client.post(
                "/api/v1/admin-web/tenant/reports/export-jobs",
                json=payload,
                headers=_origin_headers("https://evil.example"),
            )

        self.assertEqual(403, missing_origin_response.status_code)
        self.assertEqual("缺少管理后台请求来源", missing_origin_response.json()["detail"])
        self.assertEqual(403, untrusted_origin_response.status_code)
        self.assertEqual("管理后台请求来源不允许", untrusted_origin_response.json()["detail"])

    def test_tenant_api_keys_requires_current_clone_bot_workspace(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_api_keys",
            new=AsyncMock(side_effect=AssertionError("不应查询租户 API Key")),
        ):
            response = client.get("/api/v1/admin-web/tenant/api-keys")

        self.assertEqual(403, response.status_code)
        self.assertEqual("请选择克隆 Bot 工作区", response.json()["detail"])

    def test_tenant_api_keys_returns_safe_current_workspace_items(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        page = AdminWebTenantApiKeysPage(
            limit=100,
            keys=(
                AdminWebTenantApiKeyItem(
                    credential_handle="handle-demo",
                    name="readonly",
                    key_prefix="fk_live_ab12",
                    status="active",
                    scopes=("orders:read", "reports:read"),
                    ip_allowlist=("203.0.113.10",),
                    created_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
                    last_used_at=datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc),
                ),
            ),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_api_keys",
                new=AsyncMock(return_value=page),
            ) as tenant_api_keys:
                response = client.get("/api/v1/admin-web/tenant/api-keys", params={"limit": 500})

        self.assertEqual(200, response.status_code)
        self.assertEqual(0, session.commit_count)
        tenant_api_keys.assert_awaited_once_with(
            session,
            settings=settings,
            telegram_user_id=123,
            workspace_id="tn_demo",
            limit=100,
        )
        payload = response.json()
        self.assertEqual(100, payload["limit"])
        self.assertEqual("handle-demo", payload["keys"][0]["credential_handle"])
        self.assertEqual("readonly", payload["keys"][0]["name"])
        self.assertEqual("fk_live_ab12", payload["keys"][0]["key_prefix"])
        response_keys = _json_keys(payload)
        for forbidden in (
            "api_key_id",
            "tenant_id",
            "user_id",
            "created_by_user_id",
            "key_hash",
            "plain_key",
            "secret",
            "token",
            "authorization",
            "cookie",
        ):
            self.assertNotIn(forbidden, response_keys)
            self.assertNotIn(forbidden, response.text)

    def test_tenant_create_api_key_requires_current_clone_bot_workspace(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_create_api_key",
            new=AsyncMock(side_effect=AssertionError("不应创建租户 API Key")),
        ):
            response = client.post(
                "/api/v1/admin-web/tenant/api-keys",
                json={"name": "readonly", "scopes": ["orders:read"]},
                headers=_origin_headers(),
            )

        self.assertEqual(403, response.status_code)
        self.assertEqual("请选择克隆 Bot 工作区", response.json()["detail"])

    def test_tenant_create_api_key_returns_plain_key_once_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        created = AdminWebCreatedTenantApiKeyItem(
            credential_handle="handle-created",
            name="readonly",
            key_prefix="fk_live_ab12",
            status="active",
            scopes=("orders:read", "reports:read"),
            ip_allowlist=("203.0.113.10",),
            created_at=None,
            last_used_at=None,
            plain_key="fk_live_plain-secret",
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_create_api_key",
                new=AsyncMock(return_value=created),
            ) as tenant_create_api_key:
                response = client.post(
                    "/api/v1/admin-web/tenant/api-keys",
                    json={
                        "name": "readonly",
                        "scopes": ["orders:read", "reports:read"],
                        "ip_allowlist": ["203.0.113.10"],
                    },
                    headers=_origin_headers(),
                )

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, session.commit_count)
        tenant_create_api_key.assert_awaited_once_with(
            session,
            settings=settings,
            telegram_user_id=123,
            workspace_id="tn_demo",
            name="readonly",
            scopes=["orders:read", "reports:read"],
            ip_allowlist=["203.0.113.10"],
        )
        payload = response.json()
        self.assertEqual("fk_live_plain-secret", payload["plain_key"])
        self.assertEqual("handle-created", payload["credential_handle"])
        response_keys = _json_keys(payload)
        for forbidden in (
            "api_key_id",
            "tenant_id",
            "created_by_user_id",
            "key_hash",
        ):
            self.assertNotIn(forbidden, response_keys)
            self.assertNotIn(forbidden, response.text)

    def test_tenant_create_api_key_rejects_extra_fields_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_create_api_key",
            new=AsyncMock(side_effect=AssertionError("不应创建租户 API Key")),
        ):
            response = client.post(
                "/api/v1/admin-web/tenant/api-keys",
                json={"name": "readonly", "tenant_id": 7, "scopes": ["orders:read"]},
                headers=_origin_headers(),
            )

        self.assertEqual(422, response.status_code)

    def test_tenant_create_api_key_rejects_missing_or_untrusted_origin(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        payload = {"name": "readonly", "scopes": ["orders:read"]}

        with patch(
            "app.web.admin_web.AdminWebService.tenant_create_api_key",
            new=AsyncMock(side_effect=AssertionError("不应创建租户 API Key")),
        ):
            missing_origin_response = client.post("/api/v1/admin-web/tenant/api-keys", json=payload)
            untrusted_origin_response = client.post(
                "/api/v1/admin-web/tenant/api-keys",
                json=payload,
                headers=_origin_headers("https://evil.example"),
            )

        self.assertEqual(403, missing_origin_response.status_code)
        self.assertEqual("缺少管理后台请求来源", missing_origin_response.json()["detail"])
        self.assertEqual(403, untrusted_origin_response.status_code)
        self.assertEqual("管理后台请求来源不允许", untrusted_origin_response.json()["detail"])

    def test_tenant_create_api_key_value_error_returns_400_without_secret(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_create_api_key",
                new=AsyncMock(side_effect=ValueError("plain_key=fk_live_secret-token")),
            ):
                response = client.post(
                    "/api/v1/admin-web/tenant/api-keys",
                    json={"name": "readonly", "scopes": ["bad:scope"]},
                    headers=_origin_headers(),
                )

        self.assertEqual(400, response.status_code)
        self.assertEqual("API Key 参数无效", response.json()["detail"])
        self.assertNotIn("fk_live_secret-token", response.text)
        self.assertNotIn("plain_key", response.text)

    def test_tenant_revoke_api_key_requires_current_clone_bot_workspace(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_revoke_api_key",
            new=AsyncMock(side_effect=AssertionError("不应吊销租户 API Key")),
        ):
            response = client.post(
                "/api/v1/admin-web/tenant/api-keys/revoke",
                json={"credential_handle": "handle-demo-value"},
                headers=_origin_headers(),
            )

        self.assertEqual(403, response.status_code)
        self.assertEqual("请选择克隆 Bot 工作区", response.json()["detail"])

    def test_tenant_revoke_api_key_uses_handle_origin_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        result = AdminWebTenantApiKeyRevokeResult(credential_handle="handle-demo-value", revoked=True)

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_revoke_api_key",
                new=AsyncMock(return_value=result),
            ) as tenant_revoke_api_key:
                response = client.post(
                    "/api/v1/admin-web/tenant/api-keys/revoke",
                    json={"credential_handle": "handle-demo-value"},
                    headers=_origin_headers(),
                )

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, session.commit_count)
        tenant_revoke_api_key.assert_awaited_once_with(
            session,
            settings=settings,
            telegram_user_id=123,
            workspace_id="tn_demo",
            credential_handle="handle-demo-value",
        )
        payload = response.json()
        self.assertEqual({"credential_handle": "handle-demo-value", "revoked": True}, payload)
        for forbidden in ("api_key_id", "tenant_id", "key_hash", "plain_key", "secret", "token"):
            self.assertNotIn(forbidden, response.text)

    def test_tenant_revoke_api_key_rejects_extra_fields_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_revoke_api_key",
            new=AsyncMock(side_effect=AssertionError("不应吊销租户 API Key")),
        ):
            response = client.post(
                "/api/v1/admin-web/tenant/api-keys/revoke",
                json={"credential_handle": "handle-demo-value", "api_key_id": 7},
                headers=_origin_headers(),
            )

        self.assertEqual(422, response.status_code)

    def test_tenant_revoke_api_key_rejects_missing_or_untrusted_origin(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        payload = {"credential_handle": "handle-demo-value"}

        with patch(
            "app.web.admin_web.AdminWebService.tenant_revoke_api_key",
            new=AsyncMock(side_effect=AssertionError("不应吊销租户 API Key")),
        ):
            missing_origin_response = client.post("/api/v1/admin-web/tenant/api-keys/revoke", json=payload)
            untrusted_origin_response = client.post(
                "/api/v1/admin-web/tenant/api-keys/revoke",
                json=payload,
                headers=_origin_headers("https://evil.example"),
            )

        self.assertEqual(403, missing_origin_response.status_code)
        self.assertEqual("缺少管理后台请求来源", missing_origin_response.json()["detail"])
        self.assertEqual(403, untrusted_origin_response.status_code)
        self.assertEqual("管理后台请求来源不允许", untrusted_origin_response.json()["detail"])

    def test_tenant_create_withdrawal_requires_current_clone_bot_workspace(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_create_withdrawal_request",
            new=AsyncMock(side_effect=AssertionError("不应创建提现申请")),
        ):
            response = client.post(
                "/api/v1/admin-web/tenant/finance/withdrawals",
                json={"amount": "1.00", "network": "TRC20", "address": "TAbc123456789"},
                headers=_origin_headers(),
            )

        self.assertEqual(403, response.status_code)
        self.assertEqual("请选择克隆 Bot 工作区", response.json()["detail"])

    def test_tenant_create_withdrawal_uses_current_workspace_origin_and_returns_masked_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        withdrawal = AdminWebTenantWithdrawalItem(
            amount=Decimal("1.25"),
            currency="USDT",
            network="TRC20",
            address_masked="TAbc12***XyZ789",
            status="pending",
            requested_at=datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc),
            reviewed_at=None,
            completed_at=None,
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_create_withdrawal_request",
                new=AsyncMock(return_value=withdrawal),
            ) as create_withdrawal:
                response = client.post(
                    "/api/v1/admin-web/tenant/finance/withdrawals",
                    json={
                        "amount": "1.25",
                        "network": "trc20",
                        "address": "TAbc123456XyZ789",
                        "currency": "USDT",
                    },
                    headers=_origin_headers(),
                )

        self.assertEqual(200, response.status_code)
        create_withdrawal.assert_awaited_once_with(
            session,
            telegram_user_id=123,
            workspace_id="tn_demo",
            amount=Decimal("1.25"),
            network="trc20",
            address="TAbc123456XyZ789",
            currency="USDT",
        )
        self.assertEqual(1, session.commit_count)
        payload = response.json()
        self.assertEqual("1.25", payload["amount"])
        self.assertEqual("TAbc12***XyZ789", payload["address_masked"])
        self.assertEqual("pending", payload["status"])
        response_keys = _json_keys(payload)
        for forbidden in (
            "tenant_id",
            "withdrawal_id",
            "ledger_account_id",
            "account_id",
            "ledger_entry_id",
            "address",
            "address_encrypted",
            "admin_note",
            "payout_reference",
            "payout_proof_url",
            "idempotency_key",
            "actor_user_id",
            "token",
            "secret",
            "api_key",
            "credentials",
        ):
            self.assertNotIn(forbidden, response_keys)
        self.assertNotIn("TAbc123456XyZ789", response.text)

    def test_tenant_create_withdrawal_rejects_extra_fields_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_create_withdrawal_request",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.post(
                "/api/v1/admin-web/tenant/finance/withdrawals",
                json={
                    "amount": "1.00",
                    "network": "TRC20",
                    "address": "TAbc123456789",
                    "tenant_id": 7,
                    "status": "completed",
                    "payout_reference": "secret-ref",
                },
                headers=_origin_headers(),
            )

        self.assertEqual(422, response.status_code)

    def test_tenant_create_withdrawal_rejects_missing_or_untrusted_origin(self) -> None:
        settings = _settings()
        client = _client(settings)
        payload = {"amount": "1.00", "network": "TRC20", "address": "TAbc123456789"}

        with patch(
            "app.web.admin_web.AdminWebService.tenant_create_withdrawal_request",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            missing_origin_response = client.post("/api/v1/admin-web/tenant/finance/withdrawals", json=payload)
            untrusted_origin_response = client.post(
                "/api/v1/admin-web/tenant/finance/withdrawals",
                json=payload,
                headers=_origin_headers("https://evil.example"),
            )

        self.assertEqual(403, missing_origin_response.status_code)
        self.assertEqual("缺少管理后台请求来源", missing_origin_response.json()["detail"])
        self.assertEqual(403, untrusted_origin_response.status_code)
        self.assertEqual("管理后台请求来源不允许", untrusted_origin_response.json()["detail"])

    def test_tenant_create_withdrawal_value_error_returns_400_without_commit_or_address(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_create_withdrawal_request",
                new=AsyncMock(side_effect=ValueError("address=TAbc123456XyZ789 secret=plain")),
            ):
                response = client.post(
                    "/api/v1/admin-web/tenant/finance/withdrawals",
                    json={"amount": "1.00", "network": "TRC20", "address": "TAbc123456XyZ789"},
                    headers=_origin_headers(),
                )

        self.assertEqual(400, response.status_code)
        self.assertEqual("财务请求参数无效", response.json()["detail"])
        self.assertEqual(0, session.commit_count)
        self.assertNotIn("TAbc123456XyZ789", response.text)
        self.assertNotIn("plain", response.text)

    def test_tenant_create_withdrawal_runtime_error_returns_503_without_commit_or_secret(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_create_withdrawal_request",
                new=AsyncMock(side_effect=RuntimeError("secret_key=plain")),
            ):
                response = client.post(
                    "/api/v1/admin-web/tenant/finance/withdrawals",
                    json={"amount": "1.00", "network": "TRC20", "address": "TAbc123456789"},
                    headers=_origin_headers(),
                )

        self.assertEqual(503, response.status_code)
        self.assertEqual("提现服务暂不可用", response.json()["detail"])
        self.assertEqual(0, session.commit_count)
        self.assertNotIn("plain", response.text)

    def test_tenant_supply_dashboard_requires_current_clone_bot_workspace(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_supply_dashboard",
            new=AsyncMock(side_effect=AssertionError("不应查询供货代理")),
        ):
            response = client.get("/api/v1/admin-web/tenant/supply/dashboard")

        self.assertEqual(403, response.status_code)
        self.assertEqual("请选择克隆 Bot 工作区", response.json()["detail"])

    def test_tenant_supply_dashboard_returns_safe_current_workspace_summary(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        dashboard = AdminWebTenantSupplyDashboard(
            supplier_enabled=True,
            reseller_enabled=True,
            limit=6,
            supplier_offers=(
                AdminWebSupplierOfferItem(
                    supplier_offer_id=91,
                    product_name="供货卡密",
                    category="会员",
                    delivery_type="card_pool",
                    suggested_price=Decimal("12.00"),
                    min_sale_price=Decimal("11.00"),
                    supplier_cost=Decimal("9.00"),
                    currency="USDT",
                    available_count=8,
                    requires_approval=True,
                    status="on",
                ),
            ),
            supplier_applications=(
                AdminWebSupplierApplicationItem(
                    supplier_application_id="app_handle_91_77",
                    supplier_offer_id=91,
                    reseller_store_name="代理店铺",
                    product_name="供货卡密",
                    status="pending",
                    pricing_value=Decimal("9.00"),
                    min_sale_price=Decimal("11.00"),
                    currency="USDT",
                    updated_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
                ),
            ),
            supplier_rules=(
                AdminWebSupplierRuleItem(
                    supplier_rule_id="rule_handle_91_77",
                    supplier_offer_id=91,
                    reseller_store_name="代理店铺",
                    product_name="供货卡密",
                    status="active",
                    pricing_value=Decimal("8.50"),
                    min_sale_price=Decimal("10.00"),
                    currency="USDT",
                    updated_at=datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc),
                ),
            ),
            market_offers=(
                AdminWebSupplyMarketOfferItem(
                    supplier_offer_id=92,
                    product_name="市场商品",
                    category="会员",
                    delivery_type="card_fixed",
                    suggested_price=Decimal("15.00"),
                    min_sale_price=None,
                    currency="USDT",
                    available_count=5,
                    requires_approval=False,
                    reseller_rule_status=None,
                    can_create_reseller_product=True,
                    supplier_cost=Decimal("10.00"),
                    effective_min_sale_price=None,
                ),
            ),
            reseller_applications=(
                AdminWebResellerApplicationItem(
                    supplier_offer_id=93,
                    product_name="已申请商品",
                    status="pending",
                    pricing_value=Decimal("8.00"),
                    min_sale_price=None,
                    currency="USDT",
                    updated_at=datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc),
                ),
            ),
            reseller_products=(
                AdminWebResellerProductItem(
                    reseller_product_id=201,
                    supplier_offer_id=94,
                    display_name="代理商品",
                    category="会员",
                    sort_order=9,
                    delivery_type="card_pool",
                    sale_price=Decimal("13.00"),
                    currency="USDT",
                    status="on",
                    available_count=7,
                ),
            ),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_supply_dashboard",
                new=AsyncMock(return_value=dashboard),
            ) as tenant_supply_dashboard:
                response = client.get("/api/v1/admin-web/tenant/supply/dashboard?limit=6")

        self.assertEqual(200, response.status_code)
        tenant_supply_dashboard.assert_awaited_once_with(
            session,
            settings=settings,
            telegram_user_id=123,
            workspace_id="tn_demo",
            limit=6,
            market_query=None,
            market_delivery_type=None,
            market_access=None,
            market_min_price=None,
            market_max_price=None,
            market_stock=None,
            market_category=None,
        )
        payload = response.json()
        self.assertTrue(payload["supplier_enabled"])
        self.assertEqual(91, payload["supplier_offers"][0]["supplier_offer_id"])
        self.assertEqual("app_handle_91_77", payload["supplier_applications"][0]["supplier_application_id"])
        self.assertEqual("代理店铺", payload["supplier_applications"][0]["reseller_store_name"])
        self.assertNotIn("reseller_tenant_id", payload["supplier_applications"][0])
        self.assertEqual("rule_handle_91_77", payload["supplier_rules"][0]["supplier_rule_id"])
        self.assertEqual("active", payload["supplier_rules"][0]["status"])
        self.assertNotIn("reseller_tenant_id", payload["supplier_rules"][0])
        self.assertNotIn("rule_id", set(payload["supplier_rules"][0]))
        self.assertEqual(92, payload["market_offers"][0]["supplier_offer_id"])
        self.assertEqual("会员", payload["market_offers"][0]["category"])
        self.assertEqual(201, payload["reseller_products"][0]["reseller_product_id"])
        self.assertEqual("会员", payload["reseller_products"][0]["category"])
        self.assertEqual(9, payload["reseller_products"][0]["sort_order"])
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "supplier_tenant_id",
            "self_product_id",
            "locked_inventory_item_id",
            "variant_id",
            "storage_key",
            "content_hash",
            "token",
            "secret",
            "api_key",
            "raw_payload",
        ):
            self.assertNotIn(forbidden, response_text)
        self.assertNotIn('"rule_id"', response_text)

    def test_tenant_supply_dashboard_passes_market_filters_to_service(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        dashboard = AdminWebTenantSupplyDashboard(
            supplier_enabled=True,
            reseller_enabled=True,
            limit=20,
            supplier_offers=(),
            supplier_applications=(),
            supplier_rules=(),
            market_offers=(),
            reseller_applications=(),
            reseller_products=(),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_supply_dashboard",
                new=AsyncMock(return_value=dashboard),
            ) as tenant_supply_dashboard:
                response = client.get(
                    "/api/v1/admin-web/tenant/supply/dashboard"
                    "?market_query=vip"
                    "&market_category=会员"
                    "&market_delivery_type=card_pool"
                    "&market_access=ready"
                    "&market_min_price=10.5"
                    "&market_max_price=30"
                    "&market_stock=available"
                )

        self.assertEqual(200, response.status_code)
        tenant_supply_dashboard.assert_awaited_once_with(
            session,
            settings=settings,
            telegram_user_id=123,
            workspace_id="tn_demo",
            limit=20,
            market_query="vip",
            market_delivery_type="card_pool",
            market_access="ready",
            market_min_price=Decimal("10.5"),
            market_max_price=Decimal("30"),
            market_stock="available",
            market_category="会员",
        )

    def test_tenant_supply_dashboard_rejects_invalid_market_filters_without_leaking_tenant_ids(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_supply_dashboard",
                new=AsyncMock(side_effect=ValueError("最低售价不能高于最高售价")),
            ):
                response = client.get(
                    "/api/v1/admin-web/tenant/supply/dashboard"
                    "?market_min_price=30&market_max_price=10&tenant_id=999&reseller_tenant_id=888"
                )

        self.assertEqual(400, response.status_code)
        self.assertEqual("供货市场筛选参数无效", response.json()["detail"])
        self.assertNotIn("tenant_id", response.text)
        self.assertNotIn("reseller_tenant_id", response.text)

    def test_tenant_supply_supplier_application_review_uses_current_workspace_and_handle(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        application = AdminWebSupplierApplicationItem(
            supplier_application_id="app_handle_91_77",
            supplier_offer_id=91,
            reseller_store_name="代理店铺",
            product_name="供货卡密",
            status="active",
            pricing_value=Decimal("9.00"),
            min_sale_price=None,
            currency="USDT",
            updated_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_supply_review_supplier_application",
                new=AsyncMock(return_value=application),
            ) as review_application:
                response = client.post(
                    "/api/v1/admin-web/tenant/supply/supplier-applications/review",
                    json={"supplier_application_id": "app_handle_91_77", "action": "approve"},
                    headers=_origin_headers(),
                )

        self.assertEqual(200, response.status_code)
        review_application.assert_awaited_once_with(
            session,
            settings=settings,
            telegram_user_id=123,
            workspace_id="tn_demo",
            supplier_application_id="app_handle_91_77",
            action="approve",
        )
        self.assertEqual(1, session.commit_count)
        payload = response.json()
        self.assertEqual("app_handle_91_77", payload["supplier_application_id"])
        self.assertEqual("active", payload["status"])
        response_text = response.text.lower()
        for forbidden in ("tenant_id", "supplier_tenant_id", "reseller_tenant_id", "token", "secret"):
            self.assertNotIn(forbidden, response_text)
        self.assertNotIn('"rule_id"', response_text)

    def test_tenant_supply_supplier_application_review_rejects_extra_tenant_fields_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_supply_review_supplier_application",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.post(
                "/api/v1/admin-web/tenant/supply/supplier-applications/review",
                json={
                    "supplier_application_id": "app_handle_91_77",
                    "action": "approve",
                    "reseller_tenant_id": 77,
                },
                headers=_origin_headers(),
            )

        self.assertEqual(422, response.status_code)

    def test_tenant_supply_create_supplier_offer_uses_current_workspace_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        offer = AdminWebCreatedSupplierOfferItem(
            supplier_offer_id=91,
            product_name="供货卡密",
            delivery_type="card_pool",
            suggested_price=Decimal("12.00"),
            min_sale_price=Decimal("11.00"),
            supplier_cost=Decimal("9.00"),
            currency="USDT",
            requires_approval=True,
            status="on",
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_supply_create_supplier_offer",
                new=AsyncMock(return_value=offer),
            ) as create_offer:
                response = client.post(
                    "/api/v1/admin-web/tenant/supply/supplier-offers",
                    json={
                        "product_id": 21,
                        "suggested_price": "12.00",
                        "min_sale_price": "11.00",
                        "requires_approval": True,
                    },
                    headers=_origin_headers(),
                )

        self.assertEqual(200, response.status_code)
        create_offer.assert_awaited_once_with(
            session,
            telegram_user_id=123,
            workspace_id="tn_demo",
            product_id=21,
            suggested_price=Decimal("12.00"),
            min_sale_price=Decimal("11.00"),
            requires_approval=True,
        )
        self.assertEqual(1, session.commit_count)
        payload = response.json()
        self.assertEqual(91, payload["supplier_offer_id"])
        response_text = response.text.lower()
        for forbidden in ("tenant_id", "supplier_tenant_id", "product_id", "variant_id", "token", "secret"):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_supply_create_supplier_offer_rejects_extra_tenant_fields_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_supply_create_supplier_offer",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.post(
                "/api/v1/admin-web/tenant/supply/supplier-offers",
                json={
                    "product_id": 21,
                    "suggested_price": "12.00",
                    "tenant_id": 7,
                },
                headers=_origin_headers(),
            )

        self.assertEqual(422, response.status_code)

    def test_tenant_supply_set_supplier_offer_approval_uses_current_workspace(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        setting = AdminWebSupplierOfferApprovalItem(
            supplier_offer_id=91,
            requires_approval=False,
            status="on",
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_supply_set_supplier_offer_approval",
                new=AsyncMock(return_value=setting),
            ) as set_approval:
                response = client.patch(
                    "/api/v1/admin-web/tenant/supply/supplier-offers/91/approval",
                    json={"requires_approval": False},
                    headers=_origin_headers(),
                )

        self.assertEqual(200, response.status_code)
        set_approval.assert_awaited_once_with(
            session,
            telegram_user_id=123,
            workspace_id="tn_demo",
            supplier_offer_id=91,
            requires_approval=False,
        )
        self.assertEqual(1, session.commit_count)
        self.assertEqual({"supplier_offer_id", "requires_approval", "status"}, set(response.json()))
        self.assertNotIn("tenant_id", response.text.lower())

    def test_tenant_supply_set_supplier_rule_uses_current_workspace_and_handle(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        rule = AdminWebSupplierRuleItem(
            supplier_rule_id="rule_handle_91_77",
            supplier_offer_id=91,
            reseller_store_name="代理店铺",
            product_name="供货卡密",
            status="active",
            pricing_value=Decimal("8.50"),
            min_sale_price=Decimal("10.00"),
            currency="USDT",
            updated_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_supply_set_supplier_rule",
                new=AsyncMock(return_value=rule),
            ) as set_rule:
                response = client.post(
                    "/api/v1/admin-web/tenant/supply/supplier-rules",
                    json={
                        "supplier_rule_id": "rule_handle_91_77",
                        "pricing_value": "8.50",
                        "min_sale_price": "10.00",
                    },
                    headers=_origin_headers(),
                )

        self.assertEqual(200, response.status_code)
        set_rule.assert_awaited_once_with(
            session,
            settings=settings,
            telegram_user_id=123,
            workspace_id="tn_demo",
            supplier_rule_id="rule_handle_91_77",
            pricing_value=Decimal("8.50"),
            min_sale_price=Decimal("10.00"),
        )
        self.assertEqual(1, session.commit_count)
        payload = response.json()
        self.assertEqual("rule_handle_91_77", payload["supplier_rule_id"])
        response_text = response.text.lower()
        for forbidden in ("tenant_id", "supplier_tenant_id", "reseller_tenant_id", "token", "secret"):
            self.assertNotIn(forbidden, response_text)
        self.assertNotIn('"rule_id"', response_text)

    def test_tenant_supply_set_supplier_rule_rejects_extra_internal_fields_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_supply_set_supplier_rule",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.post(
                "/api/v1/admin-web/tenant/supply/supplier-rules",
                json={
                    "supplier_rule_id": "rule_handle_91_77",
                    "pricing_value": "8.50",
                    "reseller_tenant_id": 77,
                    "rule_id": 12,
                },
                headers=_origin_headers(),
            )

        self.assertEqual(422, response.status_code)

    def test_tenant_supply_apply_uses_current_workspace_and_origin_gate(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        application = AdminWebResellerApplicationItem(
            supplier_offer_id=91,
            product_name="供货卡密",
            status="pending",
            pricing_value=Decimal("9.00"),
            min_sale_price=None,
            currency="USDT",
            updated_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_supply_apply",
                new=AsyncMock(return_value=application),
            ) as tenant_supply_apply:
                response = client.post(
                    "/api/v1/admin-web/tenant/supply/applications",
                    json={"supplier_offer_id": 91},
                    headers=_origin_headers(),
                )

        self.assertEqual(200, response.status_code)
        tenant_supply_apply.assert_awaited_once_with(
            session,
            telegram_user_id=123,
            workspace_id="tn_demo",
            supplier_offer_id=91,
        )
        self.assertEqual(1, session.commit_count)
        self.assertNotIn("tenant_id", response.text.lower())
        self.assertNotIn("secret", response.text.lower())

        missing_origin_response = client.post(
            "/api/v1/admin-web/tenant/supply/applications",
            json={"supplier_offer_id": 91},
        )
        self.assertEqual(403, missing_origin_response.status_code)

    def test_tenant_supply_create_reseller_product_uses_current_workspace_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        product = AdminWebCreatedResellerProductItem(
            reseller_product_id=201,
            supplier_offer_id=91,
            display_name="代理商品",
            sale_price=Decimal("13.00"),
            currency="USDT",
            status="on",
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_supply_create_reseller_product",
                new=AsyncMock(return_value=product),
            ) as create_reseller_product:
                response = client.post(
                    "/api/v1/admin-web/tenant/supply/reseller-products",
                    json={
                        "supplier_offer_id": 91,
                        "sale_price": "13.00",
                        "display_name": "代理商品",
                    },
                    headers=_origin_headers(),
                )

        self.assertEqual(200, response.status_code)
        create_reseller_product.assert_awaited_once_with(
            session,
            telegram_user_id=123,
            workspace_id="tn_demo",
            supplier_offer_id=91,
            sale_price=Decimal("13.00"),
            display_name="代理商品",
        )
        self.assertEqual(1, session.commit_count)
        payload = response.json()
        self.assertEqual(201, payload["reseller_product_id"])
        response_text = response.text.lower()
        for forbidden in ("tenant_id", "supplier_tenant_id", "reseller_tenant_id", "storage_key", "token", "secret"):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_supply_write_rejects_extra_tenant_fields_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_supply_create_reseller_product",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.post(
                "/api/v1/admin-web/tenant/supply/reseller-products",
                json={
                    "supplier_offer_id": 91,
                    "sale_price": "13.00",
                    "reseller_tenant_id": 7,
                },
                headers=_origin_headers(),
            )

        self.assertEqual(422, response.status_code)

    def test_tenant_supply_update_reseller_product_metadata_uses_current_workspace_origin_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        product = AdminWebResellerProductItem(
            reseller_product_id=201,
            supplier_offer_id=91,
            display_name="代理商品",
            category="会员",
            sort_order=9,
            delivery_type="card_pool",
            sale_price=Decimal("13.00"),
            currency="USDT",
            status="on",
            available_count=7,
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_supply_update_reseller_product_metadata",
                new=AsyncMock(return_value=product),
            ) as update_metadata:
                response = client.patch(
                    "/api/v1/admin-web/tenant/supply/reseller-products/201/metadata",
                    json={"category": "会员", "sort_order": 9},
                    headers=_origin_headers(),
                )

        self.assertEqual(200, response.status_code)
        update_metadata.assert_awaited_once_with(
            session,
            telegram_user_id=123,
            workspace_id="tn_demo",
            reseller_product_id=201,
            category="会员",
            category_provided=True,
            sort_order=9,
        )
        self.assertEqual(1, session.commit_count)
        payload = response.json()
        self.assertEqual(
            {
                "reseller_product_id",
                "supplier_offer_id",
                "display_name",
                "category",
                "sort_order",
                "delivery_type",
                "sale_price",
                "currency",
                "status",
                "available_count",
            },
            set(payload),
        )
        self.assertEqual("会员", payload["category"])
        self.assertEqual(9, payload["sort_order"])
        self.assertNotIn("product_id", set(payload))
        self.assertNotIn("variant_id", set(payload))
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "supplier_tenant_id",
            "reseller_tenant_id",
            "rule_id",
            "supplier_rule_id",
            "storage_key",
            "token",
            "secret",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_supply_update_reseller_product_metadata_rejects_extra_internal_fields_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_supply_update_reseller_product_metadata",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.patch(
                "/api/v1/admin-web/tenant/supply/reseller-products/201/metadata",
                json={
                    "category": "会员",
                    "sort_order": 9,
                    "reseller_tenant_id": 7,
                    "supplier_rule_id": 91,
                },
                headers=_origin_headers(),
            )

        self.assertEqual(422, response.status_code)

    def test_tenant_supply_update_reseller_product_metadata_requires_current_clone_bot_workspace(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_supply_update_reseller_product_metadata",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.patch(
                "/api/v1/admin-web/tenant/supply/reseller-products/201/metadata",
                json={"category": "会员"},
                headers=_origin_headers(),
            )

        self.assertEqual(403, response.status_code)
        self.assertEqual("请选择克隆 Bot 工作区", response.json()["detail"])

    def test_tenant_supply_update_reseller_product_metadata_rejects_missing_or_untrusted_origin(self) -> None:
        settings = _settings()
        client = _client(settings)

        with patch(
            "app.web.admin_web.AdminWebService.tenant_supply_update_reseller_product_metadata",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            missing_origin_response = client.patch(
                "/api/v1/admin-web/tenant/supply/reseller-products/201/metadata",
                json={"category": "会员"},
            )
            untrusted_origin_response = client.patch(
                "/api/v1/admin-web/tenant/supply/reseller-products/201/metadata",
                json={"category": "会员"},
                headers=_origin_headers("https://evil.example"),
            )

        self.assertEqual(403, missing_origin_response.status_code)
        self.assertEqual("缺少管理后台请求来源", missing_origin_response.json()["detail"])
        self.assertEqual(403, untrusted_origin_response.status_code)
        self.assertEqual("管理后台请求来源不允许", untrusted_origin_response.json()["detail"])

    def test_tenant_supply_update_reseller_product_metadata_service_error_returns_403_without_commit(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_supply_update_reseller_product_metadata",
                new=AsyncMock(side_effect=AdminWebSessionError("代理商品不存在或无权限")),
            ):
                response = client.patch(
                    "/api/v1/admin-web/tenant/supply/reseller-products/201/metadata",
                    json={"category": "会员"},
                    headers=_origin_headers(),
                )

        self.assertEqual(403, response.status_code)
        self.assertEqual(0, session.commit_count)
        self.assertNotIn("secret", response.text.lower())

    def test_tenant_supply_update_reseller_product_metadata_value_error_returns_400_without_commit(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_supply_update_reseller_product_metadata",
                new=AsyncMock(side_effect=ValueError("token=plain-secret")),
            ):
                response = client.patch(
                    "/api/v1/admin-web/tenant/supply/reseller-products/201/metadata",
                    json={"category": "会员"},
                    headers=_origin_headers(),
                )

        self.assertEqual(400, response.status_code)
        self.assertEqual("代理商品元数据参数无效", response.json()["detail"])
        self.assertEqual(0, session.commit_count)
        self.assertNotIn("plain-secret", response.text)

    def test_tenant_supply_update_reseller_product_sales_uses_current_workspace_origin_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )
        product = AdminWebResellerProductItem(
            reseller_product_id=201,
            supplier_offer_id=91,
            display_name="新代理商品",
            category="会员",
            sort_order=9,
            delivery_type="card_pool",
            sale_price=Decimal("15.00"),
            currency="USDT",
            status="on",
            available_count=7,
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_supply_update_reseller_product_sales",
                new=AsyncMock(return_value=product),
            ) as update_sales:
                response = client.patch(
                    "/api/v1/admin-web/tenant/supply/reseller-products/201/sales",
                    json={"display_name": "新代理商品", "sale_price": "15.00"},
                    headers=_origin_headers(),
                )

        self.assertEqual(200, response.status_code)
        update_sales.assert_awaited_once_with(
            session,
            telegram_user_id=123,
            workspace_id="tn_demo",
            reseller_product_id=201,
            sale_price=Decimal("15.00"),
            display_name="新代理商品",
            display_name_provided=True,
        )
        self.assertEqual(1, session.commit_count)
        payload = response.json()
        self.assertEqual("新代理商品", payload["display_name"])
        self.assertEqual("15.00", payload["sale_price"])
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "supplier_tenant_id",
            "reseller_tenant_id",
            "rule_id",
            "supplier_rule_id",
            "storage_key",
            "token",
            "secret",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_tenant_supply_update_reseller_product_sales_rejects_extra_internal_fields_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_supply_update_reseller_product_sales",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.patch(
                "/api/v1/admin-web/tenant/supply/reseller-products/201/sales",
                json={
                    "display_name": "代理商品",
                    "sale_price": "15.00",
                    "reseller_tenant_id": 7,
                    "supplier_rule_id": 91,
                },
                headers=_origin_headers(),
            )

        self.assertEqual(422, response.status_code)

    def test_tenant_supply_update_reseller_product_sales_rejects_empty_or_null_price_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch(
            "app.web.admin_web.AdminWebService.tenant_supply_update_reseller_product_sales",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            empty_response = client.patch(
                "/api/v1/admin-web/tenant/supply/reseller-products/201/sales",
                json={},
                headers=_origin_headers(),
            )
            null_price_response = client.patch(
                "/api/v1/admin-web/tenant/supply/reseller-products/201/sales",
                json={"sale_price": None},
                headers=_origin_headers(),
            )

        self.assertEqual(400, empty_response.status_code)
        self.assertEqual("代理商品销售参数无效", empty_response.json()["detail"])
        self.assertEqual(400, null_price_response.status_code)
        self.assertEqual("代理商品售价必须大于 0", null_price_response.json()["detail"])

    def test_tenant_supply_update_reseller_product_sales_rejects_missing_or_untrusted_origin(self) -> None:
        settings = _settings()
        client = _client(settings)

        with patch(
            "app.web.admin_web.AdminWebService.tenant_supply_update_reseller_product_sales",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            missing_origin_response = client.patch(
                "/api/v1/admin-web/tenant/supply/reseller-products/201/sales",
                json={"display_name": "代理商品"},
            )
            untrusted_origin_response = client.patch(
                "/api/v1/admin-web/tenant/supply/reseller-products/201/sales",
                json={"display_name": "代理商品"},
                headers=_origin_headers("https://evil.example"),
            )

        self.assertEqual(403, missing_origin_response.status_code)
        self.assertEqual("缺少管理后台请求来源", missing_origin_response.json()["detail"])
        self.assertEqual(403, untrusted_origin_response.status_code)
        self.assertEqual("管理后台请求来源不允许", untrusted_origin_response.json()["detail"])

    def test_tenant_supply_update_reseller_product_sales_value_error_returns_400_without_commit(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo")),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.tenant_supply_update_reseller_product_sales",
                new=AsyncMock(side_effect=ValueError("token=plain-secret")),
            ):
                response = client.patch(
                    "/api/v1/admin-web/tenant/supply/reseller-products/201/sales",
                    json={"sale_price": "1.00"},
                    headers=_origin_headers(),
                )

        self.assertEqual(400, response.status_code)
        self.assertEqual("代理商品销售参数无效", response.json()["detail"])
        self.assertEqual(0, session.commit_count)
        self.assertNotIn("plain-secret", response.text)

    def test_admin_web_application_handle_codec_round_trips_and_rejects_tampering(self) -> None:
        settings = _settings()
        codec = AdminWebApplicationHandleCodec(settings)

        handle = codec.encode(
            supplier_tenant_id=7,
            supplier_offer_id=91,
            reseller_tenant_id=77,
        )
        self.assertNotIn("reseller_tenant_id", handle)
        self.assertNotIn('"reseller_tenant_id"', handle)
        self.assertNotIn('"supplier_offer_id"', handle)
        decoded = codec.decode(handle, supplier_tenant_id=7)

        self.assertEqual(91, decoded.supplier_offer_id)
        self.assertEqual(77, decoded.reseller_tenant_id)

        with self.assertRaises(AdminWebSessionError):
            codec.decode(handle + "tampered", supplier_tenant_id=7)

        with self.assertRaises(AdminWebSessionError):
            codec.decode(handle, supplier_tenant_id=8)

    def test_admin_web_supplier_rule_handle_codec_round_trips_and_rejects_tampering(self) -> None:
        settings = _settings()
        codec = AdminWebSupplierRuleHandleCodec(settings)

        handle = codec.encode(
            supplier_tenant_id=7,
            supplier_offer_id=91,
            reseller_tenant_id=77,
        )
        self.assertNotIn("reseller_tenant_id", handle)
        self.assertNotIn('"reseller_tenant_id"', handle)
        self.assertNotIn('"supplier_offer_id"', handle)
        decoded = codec.decode(handle, supplier_tenant_id=7)

        self.assertEqual(91, decoded.supplier_offer_id)
        self.assertEqual(77, decoded.reseller_tenant_id)

        with self.assertRaises(AdminWebSessionError):
            codec.decode(handle + "tampered", supplier_tenant_id=7)

        with self.assertRaises(AdminWebSessionError):
            codec.decode(handle, supplier_tenant_id=8)

    def test_admin_web_tenant_api_key_handle_codec_round_trips_and_rejects_tampering(self) -> None:
        settings = _settings()
        codec = AdminWebTenantApiKeyHandleCodec(settings)

        handle = codec.encode(tenant_id=7, api_key_id=91)
        self.assertNotIn("tenant_id", handle)
        self.assertNotIn("api_key_id", handle)
        self.assertNotIn('"tenant_id"', handle)
        self.assertNotIn('"api_key_id"', handle)
        decoded = codec.decode(handle, tenant_id=7)

        self.assertEqual(91, decoded.api_key_id)

        with self.assertRaises(AdminWebSessionError):
            codec.decode(handle + "tampered", tenant_id=7)

        with self.assertRaises(AdminWebSessionError):
            codec.decode(handle, tenant_id=8)

    def test_tenant_supply_dashboard_uses_resolved_workspace_tenant_and_market_filters(self) -> None:
        session = _FakeSession()
        service = AdminWebService()
        supply_service = SimpleNamespace(
            list_supplier_offers=AsyncMock(return_value=[]),
            list_reseller_applications=AsyncMock(return_value=[]),
            list_supplier_reseller_rules=AsyncMock(return_value=[]),
            list_market_offers=AsyncMock(return_value=[]),
            list_my_reseller_applications=AsyncMock(return_value=[]),
            list_reseller_products=AsyncMock(return_value=[]),
        )

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7, supplier_enabled=True, reseller_enabled=True)),
            ):
                with patch("app.services.admin_web.load_tenant_feature_flags", AsyncMock(return_value={"self_sale": True, "supplier": True, "reseller": True})):
                    with patch("app.services.admin_web.SupplyService", return_value=supply_service):
                        dashboard = asyncio.run(
                            service.tenant_supply_dashboard(
                                session,
                                settings=_settings(),
                                telegram_user_id=123,
                                workspace_id="tn_demo",
                                limit=20,
                                market_query="vip",
                                market_delivery_type="card_pool",
                                market_access="ready",
                                market_min_price=Decimal("10"),
                                market_max_price=Decimal("30"),
                                market_stock="available",
                                market_category="会员",
                            )
                        )

        supply_service.list_market_offers.assert_awaited_once_with(
            session=session,
            reseller_tenant_id=7,
            limit=20,
            query="vip",
            delivery_type="card_pool",
            access="ready",
            min_price=Decimal("10"),
            max_price=Decimal("30"),
            stock="available",
            category="会员",
        )
        self.assertEqual(20, dashboard.limit)
        self.assertTrue(dashboard.supplier_enabled)
        self.assertTrue(dashboard.reseller_enabled)

    def test_tenant_supply_update_reseller_product_metadata_uses_resolved_workspace_tenant(self) -> None:
        session = _FakeSession()
        service = AdminWebService()
        product = SimpleNamespace(
            reseller_product_id=201,
            supplier_offer_id=91,
            display_name="代理商品",
            category="会员",
            sort_order=9,
            delivery_type="card_pool",
            sale_price=Decimal("13.00"),
            currency="USDT",
            status="on",
            available_count=7,
        )
        supply_service = SimpleNamespace(update_reseller_product_metadata=AsyncMock(return_value=product))

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.load_tenant_feature_flags", AsyncMock(return_value={"self_sale": True, "supplier": True, "reseller": True})):
                    with patch("app.services.admin_web.SupplyService", return_value=supply_service):
                        updated = asyncio.run(
                            service.tenant_supply_update_reseller_product_metadata(
                                session,
                                telegram_user_id=123,
                                workspace_id="tn_demo",
                                reseller_product_id=201,
                                category="会员",
                                category_provided=True,
                                sort_order=9,
                            )
                        )

        supply_service.update_reseller_product_metadata.assert_awaited_once_with(
            session=session,
            reseller_tenant_id=7,
            reseller_product_id=201,
            category="会员",
            category_provided=True,
            sort_order=9,
        )
        self.assertEqual(201, updated.reseller_product_id)
        self.assertEqual("会员", updated.category)
        self.assertEqual(9, updated.sort_order)

    def test_tenant_supply_update_reseller_product_sales_uses_resolved_workspace_tenant(self) -> None:
        session = _FakeSession()
        service = AdminWebService()
        product = SimpleNamespace(
            reseller_product_id=201,
            supplier_offer_id=91,
            display_name="新代理商品",
            category="会员",
            sort_order=9,
            delivery_type="card_pool",
            sale_price=Decimal("15.00"),
            currency="USDT",
            status="on",
            available_count=7,
        )
        supply_service = SimpleNamespace(update_reseller_product_sales=AsyncMock(return_value=product))

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.load_tenant_feature_flags", AsyncMock(return_value={"self_sale": True, "supplier": True, "reseller": True})):
                    with patch("app.services.admin_web.SupplyService", return_value=supply_service):
                        updated = asyncio.run(
                            service.tenant_supply_update_reseller_product_sales(
                                session,
                                telegram_user_id=123,
                                workspace_id="tn_demo",
                                reseller_product_id=201,
                                sale_price=Decimal("15.00"),
                                display_name="新代理商品",
                                display_name_provided=True,
                            )
                        )

        supply_service.update_reseller_product_sales.assert_awaited_once_with(
            session=session,
            reseller_tenant_id=7,
            reseller_product_id=201,
            sale_price=Decimal("15.00"),
            display_name="新代理商品",
            display_name_provided=True,
        )
        self.assertEqual(201, updated.reseller_product_id)
        self.assertEqual("新代理商品", updated.display_name)
        self.assertEqual(Decimal("15.00"), updated.sale_price)

    def test_tenant_supply_create_supplier_offer_rejects_disabled_supplier_before_supply_service(self) -> None:
        session = _FakeSession()
        service = AdminWebService()

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch(
                    "app.services.admin_web.load_tenant_feature_flags",
                    AsyncMock(return_value={"self_sale": True, "supplier": False, "reseller": True}),
                ):
                    with patch("app.services.admin_web.SupplyService") as supply_service:
                        with self.assertRaisesRegex(ValueError, "供货功能已关闭"):
                            asyncio.run(
                                service.tenant_supply_create_supplier_offer(
                                    session,
                                    telegram_user_id=123,
                                    workspace_id="tn_demo",
                                    product_id=21,
                                    suggested_price=Decimal("12.00"),
                                    min_sale_price=None,
                                    requires_approval=True,
                                )
                            )

        supply_service.return_value.create_supplier_offer.assert_not_called()

    def test_tenant_supply_apply_rejects_disabled_reseller_before_supply_service(self) -> None:
        session = _FakeSession()
        service = AdminWebService()

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch(
                    "app.services.admin_web.load_tenant_feature_flags",
                    AsyncMock(return_value={"self_sale": True, "supplier": True, "reseller": False}),
                ):
                    with patch("app.services.admin_web.SupplyService") as supply_service:
                        with self.assertRaisesRegex(ValueError, "代理售卖功能已关闭"):
                            asyncio.run(
                                service.tenant_supply_apply(
                                    session,
                                    telegram_user_id=123,
                                    workspace_id="tn_demo",
                                    supplier_offer_id=91,
                                )
                            )

        supply_service.return_value.apply_reseller.assert_not_called()

    def test_tenant_products_uses_filters_and_resolved_workspace_tenant(self) -> None:
        session = _FakeSession()
        product = SimpleNamespace(
            id=12,
            name="Demo Product",
            category="软件",
            sort_order=5,
            status="on",
            delivery_type="card_pool",
            suggested_price=Decimal("9.90"),
            currency="USDT",
        )
        variant = SimpleNamespace(price=Decimal("9.90"), currency="USDT")
        repo = SimpleNamespace(
            count_products=AsyncMock(return_value=2),
            list_products=AsyncMock(return_value=[(product, variant, 3)]),
        )
        service = AdminWebService()

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.ProductRepository", return_value=repo):
                    page = asyncio.run(
                        service.tenant_products(
                            session,
                            telegram_user_id=123,
                            workspace_id="tn_demo",
                            limit=10,
                            offset=20,
                            query=" demo ",
                            status="on",
                            delivery_type="card_pool",
                            category=" 软件 ",
                        )
                    )

        repo.count_products.assert_awaited_once_with(
            session,
            7,
            search_query="demo",
            status="on",
            delivery_type="card_pool",
            category="软件",
        )
        repo.list_products.assert_awaited_once_with(
            session,
            7,
            limit=10,
            offset=20,
            search_query="demo",
            status="on",
            delivery_type="card_pool",
            category="软件",
        )
        self.assertEqual(2, page.total_count)
        self.assertEqual(20, page.offset)
        self.assertEqual(12, page.items[0].product_id)
        self.assertEqual(3, page.items[0].available_count)

    def test_tenant_update_product_price_status_uses_resolved_workspace_tenant(self) -> None:
        session = _FakeSession()
        product = SimpleNamespace(
            id=12,
            name="Demo Product",
            category="工具",
            sort_order=9,
            status="off",
            delivery_type="card_pool",
            suggested_price=Decimal("12.50"),
            currency="USDT",
        )
        variant = SimpleNamespace(price=Decimal("12.50"), currency="USDT")
        repo = SimpleNamespace(
            update_self_product=AsyncMock(return_value=product),
            get_product_with_default_variant=AsyncMock(return_value=(product, variant)),
            inventory_summary=AsyncMock(return_value={12: {"available": 4}}),
        )
        service = AdminWebService()

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.ProductRepository", return_value=repo):
                    updated = asyncio.run(
                        service.tenant_update_product_sales(
                            session,
                            telegram_user_id=123,
                            workspace_id="tn_demo",
                            product_id=12,
                            price=Decimal("12.50"),
                            status="off",
                        )
                    )

        repo.update_self_product.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            product_id=12,
            price=Decimal("12.50"),
            status="off",
        )
        repo.get_product_with_default_variant.assert_awaited_once_with(session, 7, 12)
        repo.inventory_summary.assert_awaited_once_with(session, 7, 12)
        self.assertEqual(12, updated.product_id)
        self.assertEqual("off", updated.status)
        self.assertEqual(Decimal("12.50"), updated.price)
        self.assertEqual(4, updated.available_count)

    def test_tenant_batch_update_product_status_uses_resolved_workspace_tenant(self) -> None:
        session = _FakeSession()
        products_by_id = {
            12: SimpleNamespace(
                id=12,
                name="Demo Product",
                category="工具",
                sort_order=9,
                status="off",
                delivery_type="card_pool",
                suggested_price=Decimal("12.50"),
                currency="USDT",
            ),
            13: SimpleNamespace(
                id=13,
                name="Second Product",
                category=None,
                sort_order=10,
                status="off",
                delivery_type="card_fixed",
                suggested_price=Decimal("9.90"),
                currency="USDT",
            ),
        }
        variants_by_id = {
            12: SimpleNamespace(price=Decimal("12.50"), currency="USDT"),
            13: SimpleNamespace(price=Decimal("9.90"), currency="USDT"),
        }

        async def update_self_product(**kwargs: object) -> object:
            product_id = int(kwargs["product_id"])
            return products_by_id[product_id]

        async def get_product_with_default_variant(_session: object, _tenant_id: int, product_id: int) -> object:
            return products_by_id[product_id], variants_by_id[product_id]

        async def inventory_summary(_session: object, _tenant_id: int, product_id: int) -> dict[int, dict[str, int]]:
            return {product_id: {"available": product_id - 10}}

        repo = SimpleNamespace(
            update_self_product=AsyncMock(side_effect=update_self_product),
            get_product_with_default_variant=AsyncMock(side_effect=get_product_with_default_variant),
            inventory_summary=AsyncMock(side_effect=inventory_summary),
        )
        service = AdminWebService()

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.ProductRepository", return_value=repo):
                    result = asyncio.run(
                        service.tenant_batch_update_product_status(
                            session,
                            telegram_user_id=123,
                            workspace_id="tn_demo",
                            product_ids=[12, 13],
                            status="off",
                        )
                    )

        self.assertEqual(2, repo.update_self_product.await_count)
        repo.update_self_product.assert_any_await(
            session=session,
            tenant_id=7,
            product_id=12,
            status="off",
        )
        repo.update_self_product.assert_any_await(
            session=session,
            tenant_id=7,
            product_id=13,
            status="off",
        )
        self.assertEqual(2, repo.get_product_with_default_variant.await_count)
        self.assertEqual(2, repo.inventory_summary.await_count)
        self.assertEqual("off", result.status)
        self.assertEqual(2, result.updated_count)
        self.assertEqual((12, 13), tuple(item.product_id for item in result.products))
        self.assertEqual((2, 3), tuple(item.available_count for item in result.products))

    def test_tenant_batch_update_product_status_rejects_duplicate_ids_before_repo(self) -> None:
        session = _FakeSession()
        repo = SimpleNamespace(update_self_product=AsyncMock())
        service = AdminWebService()

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.ProductRepository", return_value=repo):
                    with self.assertRaisesRegex(ValueError, "批量商品 ID 不能重复"):
                        asyncio.run(
                            service.tenant_batch_update_product_status(
                                session,
                                telegram_user_id=123,
                                workspace_id="tn_demo",
                                product_ids=[12, 12],
                                status="off",
                            )
                        )

        repo.update_self_product.assert_not_awaited()

    def test_tenant_import_product_inventory_uses_resolved_workspace_tenant(self) -> None:
        settings = _settings()
        session = _FakeSession()
        repo = SimpleNamespace(
            add_inventory_items=AsyncMock(return_value=(2, 1)),
            inventory_summary=AsyncMock(return_value={12: {"available": 5}}),
        )
        crypto = SimpleNamespace(
            encrypt_token=MagicMock(side_effect=lambda value: f"encrypted:{value}"),
            token_hash=MagicMock(side_effect=lambda value: f"hash:{value}"),
        )
        service = AdminWebService()

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.ProductRepository", return_value=repo):
                    with patch("app.services.admin_web.TokenCrypto", return_value=crypto) as crypto_factory:
                        result = asyncio.run(
                            service.tenant_import_product_inventory(
                                session,
                                settings=settings,
                                telegram_user_id=123,
                                workspace_id="tn_demo",
                                product_id=12,
                                items=[" alpha-card ", "beta-card", "alpha-card", ""],
                            )
                        )

        crypto_factory.assert_called_once_with(settings)
        crypto.encrypt_token.assert_any_call("alpha-card")
        crypto.encrypt_token.assert_any_call("beta-card")
        crypto.token_hash.assert_any_call("alpha-card")
        crypto.token_hash.assert_any_call("beta-card")
        repo.add_inventory_items.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            product_id=12,
            encrypted_items=[
                ("encrypted:alpha-card", "hash:alpha-card"),
                ("encrypted:beta-card", "hash:beta-card"),
            ],
        )
        repo.inventory_summary.assert_awaited_once_with(session, 7, 12)
        self.assertEqual(12, result.product_id)
        self.assertEqual(2, result.added_count)
        self.assertEqual(1, result.existing_count)
        self.assertEqual(1, result.input_duplicate_count)
        self.assertEqual(5, result.available_count)

    def test_tenant_import_product_inventory_hides_non_self_product_error(self) -> None:
        settings = _settings()
        session = _FakeSession()
        repo = SimpleNamespace(
            add_inventory_items=AsyncMock(side_effect=ValueError("只能为自营商品导入库存")),
        )
        crypto = SimpleNamespace(
            encrypt_token=MagicMock(return_value="encrypted"),
            token_hash=MagicMock(return_value="hash"),
        )
        service = AdminWebService()

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.ProductRepository", return_value=repo):
                    with patch("app.services.admin_web.TokenCrypto", return_value=crypto):
                        with self.assertRaises(AdminWebSessionError):
                            asyncio.run(
                                service.tenant_import_product_inventory(
                                    session,
                                    settings=settings,
                                    telegram_user_id=123,
                                    workspace_id="tn_demo",
                                    product_id=12,
                                    items=["alpha-card"],
                                )
                            )

        repo.add_inventory_items.assert_awaited_once()

    def test_tenant_upload_product_delivery_file_uses_resolved_workspace_tenant(self) -> None:
        settings = _settings()
        session = _FakeSession()
        product = SimpleNamespace(id=12, delivery_type="file_download", file_size_limit=1024)
        stored_file = SimpleNamespace(
            storage_key="tenants/7/files/random_payload.zip",
            original_filename="payload.zip",
            content_type="application/zip",
            size_bytes=12,
            sha256="a" * 64,
        )
        uploaded_file = SimpleNamespace(id=55)
        repo = SimpleNamespace(
            get_product_with_default_variant=AsyncMock(return_value=(product, SimpleNamespace(id=8))),
            create_uploaded_file=AsyncMock(return_value=uploaded_file),
            bind_delivery_file=AsyncMock(return_value=product),
        )
        file_storage = SimpleNamespace(
            store_upload_file=MagicMock(return_value=stored_file),
            resolve_storage_key=MagicMock(return_value="/tmp/storage/tenants/7/files/random_payload.zip"),
        )
        inspector = SimpleNamespace(
            inspect_uploaded_file=AsyncMock(
                return_value=InspectionResult(
                    job_id=101,
                    risk_level="low",
                    entry_count=1,
                    blocked=False,
                    message="文件扫描完成",
                )
            )
        )
        service = AdminWebService()

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch.object(
                    service,
                    "get_user_by_telegram_id",
                    new=AsyncMock(return_value=SimpleNamespace(id=3, is_banned=False)),
                ):
                    with patch("app.services.admin_web.ProductRepository", return_value=repo):
                        with patch("app.services.admin_web.FileStorageService", return_value=file_storage) as storage_factory:
                            with patch("app.services.admin_web.FileInspectionService", return_value=inspector):
                                result = asyncio.run(
                                    service.tenant_upload_product_delivery_file(
                                        session,
                                        settings=settings,
                                        telegram_user_id=123,
                                        workspace_id="tn_demo",
                                        product_id=12,
                                        filename="payload.zip",
                                        content_type="application/zip",
                                        payload=b"PK\x03\x04demo",
                                    )
                                )

        storage_factory.assert_called_once_with(settings)
        repo.get_product_with_default_variant.assert_awaited_once_with(session, 7, 12)
        file_storage.store_upload_file.assert_called_once_with(
            filename="payload.zip",
            content_type="application/zip",
            payload=b"PK\x03\x04demo",
            tenant_id=7,
        )
        repo.create_uploaded_file.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            storage_key="tenants/7/files/random_payload.zip",
            original_filename="payload.zip",
            content_type="application/zip",
            size_bytes=12,
            sha256="a" * 64,
            owner_user_id=3,
        )
        file_storage.resolve_storage_key.assert_called_once_with("tenants/7/files/random_payload.zip")
        inspector.inspect_uploaded_file.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            uploaded_file_id=55,
            file_path="/tmp/storage/tenants/7/files/random_payload.zip",
            requested_by_user_id=3,
        )
        repo.bind_delivery_file.assert_awaited_once_with(session, 7, 12, 55)
        self.assertEqual(12, result.product_id)
        self.assertEqual("payload.zip", result.filename)
        self.assertEqual("low", result.risk_level)
        self.assertTrue(result.bound)

    def test_tenant_upload_product_delivery_file_does_not_bind_blocked_scan(self) -> None:
        settings = _settings()
        session = _FakeSession()
        product = SimpleNamespace(id=12, delivery_type="file_download", file_size_limit=None)
        stored_file = SimpleNamespace(
            storage_key="tenants/7/files/random_payload.zip",
            original_filename="payload.zip",
            content_type="application/zip",
            size_bytes=12,
            sha256="b" * 64,
        )
        repo = SimpleNamespace(
            get_product_with_default_variant=AsyncMock(return_value=(product, SimpleNamespace(id=8))),
            create_uploaded_file=AsyncMock(return_value=SimpleNamespace(id=55)),
            bind_delivery_file=AsyncMock(side_effect=AssertionError("高风险文件不应绑定")),
        )
        file_storage = SimpleNamespace(
            store_upload_file=MagicMock(return_value=stored_file),
            resolve_storage_key=MagicMock(return_value="/tmp/storage/tenants/7/files/random_payload.zip"),
        )
        inspector = SimpleNamespace(
            inspect_uploaded_file=AsyncMock(
                return_value=InspectionResult(
                    job_id=101,
                    risk_level="high",
                    entry_count=1,
                    blocked=True,
                    message="文件包含高风险条目，已阻断绑定",
                )
            )
        )
        service = AdminWebService()

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch.object(
                    service,
                    "get_user_by_telegram_id",
                    new=AsyncMock(return_value=SimpleNamespace(id=3, is_banned=False)),
                ):
                    with patch("app.services.admin_web.ProductRepository", return_value=repo):
                        with patch("app.services.admin_web.FileStorageService", return_value=file_storage):
                            with patch("app.services.admin_web.FileInspectionService", return_value=inspector):
                                result = asyncio.run(
                                    service.tenant_upload_product_delivery_file(
                                        session,
                                        settings=settings,
                                        telegram_user_id=123,
                                        workspace_id="tn_demo",
                                        product_id=12,
                                        filename="payload.zip",
                                        content_type="application/zip",
                                        payload=b"PK\x03\x04demo",
                                    )
                                )

        repo.create_uploaded_file.assert_awaited_once()
        inspector.inspect_uploaded_file.assert_awaited_once()
        repo.bind_delivery_file.assert_not_awaited()
        self.assertEqual("high", result.risk_level)
        self.assertFalse(result.bound)
        self.assertEqual("文件包含高风险条目，已阻断绑定", result.scan_message)

    def test_tenant_update_product_price_status_hides_non_self_product_error(self) -> None:
        session = _FakeSession()
        repo = SimpleNamespace(
            update_self_product=AsyncMock(side_effect=ValueError("只能同步自营商品")),
        )
        service = AdminWebService()

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.ProductRepository", return_value=repo):
                    with self.assertRaises(AdminWebSessionError):
                        asyncio.run(
                            service.tenant_update_product_sales(
                                session,
                                telegram_user_id=123,
                                workspace_id="tn_demo",
                                product_id=12,
                                price=Decimal("12.50"),
                                status="on",
                            )
                        )

        repo.update_self_product.assert_awaited_once()

    def test_tenant_create_product_uses_resolved_workspace_tenant(self) -> None:
        session = _FakeSession()
        product = SimpleNamespace(
            id=31,
            name="Demo Product",
            category="工具",
            sort_order=0,
            status="draft",
            delivery_type="card_pool",
            suggested_price=Decimal("12.50"),
            currency="USDT",
        )
        variant = SimpleNamespace(price=Decimal("12.50"), currency="USDT")
        repo = SimpleNamespace(
            create_self_product=AsyncMock(return_value=product),
            get_product_with_default_variant=AsyncMock(return_value=(product, variant)),
        )
        service = AdminWebService()

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.ProductRepository", return_value=repo):
                    created = asyncio.run(
                        service.tenant_create_product(
                            session,
                            telegram_user_id=123,
                            workspace_id="tn_demo",
                            name="Demo Product",
                            price=Decimal("12.50"),
                            delivery_type="card_pool",
                            description="仅创建草稿",
                            category="工具",
                        )
                    )

        repo.create_self_product.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            name="Demo Product",
            price=Decimal("12.50"),
            delivery_type="card_pool",
            description="仅创建草稿",
            category="工具",
        )
        repo.get_product_with_default_variant.assert_awaited_once_with(session, 7, 31)
        self.assertEqual(31, created.product_id)
        self.assertEqual("draft", created.status)
        self.assertEqual(Decimal("12.50"), created.price)
        self.assertEqual(0, created.available_count)

    def test_tenant_subscription_dashboard_uses_resolved_workspace_tenant(self) -> None:
        session = _FakeSession()
        service = AdminWebService()
        subscription_service = SimpleNamespace(
            get_tenant_subscription_summary=AsyncMock(
                return_value=SimpleNamespace(
                    status="active",
                    plan_code="default_monthly",
                    plan_name="默认月付套餐",
                    monthly_price=Decimal("19.90"),
                    currency="USDT",
                    trial_days=7,
                    grace_days=3,
                    trial_ends_at=None,
                    current_period_ends_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
                    subscription_ends_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
                    grace_ends_at=None,
                    suspended_at=None,
                    data_retention_until=None,
                    created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
                    updated_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
                )
            ),
            list_tenant_subscription_invoices=AsyncMock(return_value=[]),
        )

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.SubscriptionService", return_value=subscription_service):
                    dashboard = asyncio.run(
                        service.tenant_subscription_dashboard(
                            session,
                            telegram_user_id=123,
                            workspace_id="tn_demo",
                            invoice_limit=8,
                        )
                    )

        subscription_service.get_tenant_subscription_summary.assert_awaited_once_with(session, 7)
        subscription_service.list_tenant_subscription_invoices.assert_awaited_once_with(
            session,
            tenant_id=7,
            limit=8,
        )
        self.assertEqual("active", dashboard.status)
        self.assertEqual("default_monthly", dashboard.plan_code)

    def test_tenant_subscription_renewal_order_uses_resolved_workspace_tenant(self) -> None:
        session = _FakeSession()
        settings = _settings()
        renewal_order = SubscriptionOrder(
            order_id=81,
            out_trade_no="SUB_123",
            amount=Decimal("19.90"),
            currency="USDT",
            months=1,
            expires_at=datetime(2026, 6, 1, 12, 30, tzinfo=timezone.utc),
        )
        subscription_service = SimpleNamespace(create_renewal_order=AsyncMock(return_value=renewal_order))
        payment_service = SimpleNamespace(
            create_payment_for_order=AsyncMock(
                return_value=SimpleNamespace(
                    provider="epusdt_gmpay",
                    payment_url="https://pay.example/SUB_123",
                )
            )
        )
        service = AdminWebService()

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.SubscriptionService", return_value=subscription_service):
                    with patch("app.services.admin_web.PaymentService", return_value=payment_service):
                        created = asyncio.run(
                            service.tenant_create_subscription_renewal_order(
                                session,
                                settings=settings,
                                telegram_user_id=123,
                                workspace_id="tn_demo",
                                months=1,
                            )
                        )

        subscription_service.create_renewal_order.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            buyer_telegram_user_id=123,
            months=1,
            monthly_price=settings.subscription_monthly_price,
        )
        payment_service.create_payment_for_order.assert_awaited_once_with(session, 81)
        self.assertEqual("SUB_123", created.out_trade_no)
        self.assertTrue(created.payment_available)
        self.assertEqual("https://pay.example/SUB_123", created.payment_url)

    def test_tenant_subscription_renewal_order_keeps_order_when_payment_unavailable_without_leaking_secret(self) -> None:
        session = _FakeSession()
        settings = _settings()
        renewal_order = SubscriptionOrder(
            order_id=81,
            out_trade_no="SUB_123",
            amount=Decimal("19.90"),
            currency="USDT",
            months=1,
            expires_at=datetime(2026, 6, 1, 12, 30, tzinfo=timezone.utc),
        )
        subscription_service = SimpleNamespace(create_renewal_order=AsyncMock(return_value=renewal_order))
        payment_service = SimpleNamespace(
            create_payment_for_order=AsyncMock(side_effect=PaymentUnavailableError("secret_key=plain"))
        )
        service = AdminWebService()

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.SubscriptionService", return_value=subscription_service):
                    with patch("app.services.admin_web.PaymentService", return_value=payment_service):
                        created = asyncio.run(
                            service.tenant_create_subscription_renewal_order(
                                session,
                                settings=settings,
                                telegram_user_id=123,
                                workspace_id="tn_demo",
                                months=1,
                            )
                        )

        subscription_service.create_renewal_order.assert_awaited_once()
        payment_service.create_payment_for_order.assert_awaited_once_with(session, 81)
        self.assertEqual("SUB_123", created.out_trade_no)
        self.assertFalse(created.payment_available)
        self.assertIsNone(created.payment_provider)
        self.assertIsNone(created.payment_url)
        self.assertEqual("支付配置暂不可用", created.payment_failure_reason)
        self.assertNotIn("plain", created.payment_failure_reason)

    def test_tenant_finance_dashboard_uses_resolved_workspace_tenant_without_creating_account(self) -> None:
        session = _FakeSession()
        service = AdminWebService()
        ledger_service = SimpleNamespace(
            audit_account_balance=AsyncMock(
                return_value=SimpleNamespace(
                    account_type="main",
                    currency="USDT",
                    stored_pending_balance=Decimal("0"),
                    stored_available_balance=Decimal("0"),
                    stored_frozen_balance=Decimal("0"),
                    computed_pending_balance=Decimal("0"),
                    computed_available_balance=Decimal("0"),
                    computed_frozen_balance=Decimal("0"),
                    pending_difference=Decimal("0"),
                    available_difference=Decimal("0"),
                    frozen_difference=Decimal("0"),
                    is_balanced=True,
                )
            ),
            list_withdrawals=AsyncMock(return_value=[]),
        )

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch.object(service, "_load_main_ledger", new=AsyncMock(return_value=None)) as load_main_ledger:
                    with patch("app.services.admin_web.LedgerService", return_value=ledger_service):
                        dashboard = asyncio.run(
                            service.tenant_finance_dashboard(
                                session,
                                telegram_user_id=123,
                                workspace_id="tn_demo",
                                withdrawal_limit=8,
                            )
                        )

        load_main_ledger.assert_awaited_once_with(session, 7)
        self.assertFalse(hasattr(ledger_service, "get_balance"))
        ledger_service.audit_account_balance.assert_awaited_once_with(session, 7)
        ledger_service.list_withdrawals.assert_awaited_once_with(
            session,
            tenant_id=7,
            limit=8,
        )
        self.assertEqual("0", str(dashboard.balance.available_balance))
        self.assertTrue(dashboard.audit.is_balanced)

    def test_tenant_audit_logs_uses_resolved_workspace_tenant_and_safe_metadata(self) -> None:
        session = _FakeSession()
        service = AdminWebService()
        audit_log = SimpleNamespace(
            created_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            actor_telegram_user_id=456,
            actor_username="owner",
            action="order.pay",
            target_type="order",
            metadata_json={"ignored": "raw"},
        )
        audit_service = SimpleNamespace(
            list_tenant_audit_logs=AsyncMock(return_value=[audit_log]),
            safe_metadata_for_tenant_api=MagicMock(
                return_value={
                    "out_trade_no": "ORD123",
                    "order_id": 99,
                    "payment_id": 88,
                    "status": "paid",
                    "nested": {"product_id": 12, "safe": True},
                    "items": [{"tenant_id": 7, "name": "demo"}],
                }
            ),
        )

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.AuditLogService", return_value=audit_service):
                    page = asyncio.run(
                        service.tenant_audit_logs(
                            session,
                            telegram_user_id=123,
                            workspace_id="tn_demo",
                            limit=50,
                            action="order.pay",
                            target_type="order",
                        )
                    )

        audit_service.list_tenant_audit_logs.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            limit=50,
            action="order.pay",
            target_type="order",
        )
        audit_service.safe_metadata_for_tenant_api.assert_called_once_with({"ignored": "raw"})
        self.assertEqual(50, page.limit)
        self.assertEqual("order.pay", page.items[0].action)
        self.assertEqual({"out_trade_no": "ORD123", "status": "paid", "nested": {"safe": True}, "items": [{"name": "demo"}]}, page.items[0].metadata)

    def test_tenant_report_export_jobs_uses_resolved_workspace_tenant_and_sanitizes_failure_text(self) -> None:
        session = _FakeSession()
        service = AdminWebService()
        settings = _settings()
        now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        report_service = SimpleNamespace(
            list_export_jobs=AsyncMock(
                return_value=[
                    SimpleNamespace(
                        export_job_id=81,
                        tenant_id=7,
                        report_type="orders",
                        scope_type="tenant",
                        status="completed",
                        row_count=23,
                        download_url="https://example.test/exports/download/raw-download-token",
                        error_message=None,
                        expires_at=datetime(2099, 6, 1, 13, 0, tzinfo=timezone.utc),
                        created_at=now,
                        started_at=now,
                        finished_at=now,
                    ),
                    SimpleNamespace(
                        export_job_id=82,
                        tenant_id=7,
                        report_type="payments",
                        scope_type="tenant",
                        status="failed",
                        row_count=0,
                        download_url=None,
                        error_message="storage_key=/exports/tenant_7/private.csv token=plain-secret",
                        expires_at=None,
                        created_at=now,
                        started_at=now,
                        finished_at=now,
                    ),
                ]
            ),
        )

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.ReportExportService", return_value=report_service):
                    page = asyncio.run(
                        service.tenant_report_export_jobs(
                            session,
                            settings=settings,
                            telegram_user_id=123,
                            workspace_id="tn_demo",
                            status="all",
                            report_type="orders",
                            limit=500,
                        )
                    )

        report_service.list_export_jobs.assert_awaited_once_with(
            session=session,
            settings=settings,
            tenant_id=7,
            status=None,
            report_type="orders",
            limit=100,
        )
        self.assertIsNone(page.status)
        self.assertEqual("orders", page.report_type)
        self.assertEqual(100, page.limit)
        self.assertTrue(page.export_jobs[0].download_available)
        self.assertIsNotNone(page.export_jobs[0].download_handle)
        self.assertNotEqual("raw-download-token", page.export_jobs[0].download_handle)
        self.assertIsNone(page.export_jobs[1].download_handle)
        self.assertEqual("报表导出失败", page.export_jobs[1].failure_reason)
        self.assertNotIn("plain-secret", repr(page))
        self.assertNotIn("storage_key", repr(page))
        self.assertNotIn("raw-download-token", repr(page))

    def test_tenant_create_report_export_job_uses_resolved_workspace_tenant_and_platform_user_actor(self) -> None:
        session = _FakeSession()
        service = AdminWebService()
        settings = _settings()
        now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        report_service = SimpleNamespace(
            create_export_job=AsyncMock(
                return_value=SimpleNamespace(
                    export_job_id=81,
                    tenant_id=7,
                    report_type="orders",
                    scope_type="tenant",
                    status="pending",
                    row_count=0,
                    download_url=None,
                    error_message=None,
                    expires_at=None,
                    created_at=now,
                    started_at=None,
                    finished_at=None,
                )
            ),
        )

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch.object(
                    service,
                    "get_user_by_telegram_id",
                    new=AsyncMock(return_value=SimpleNamespace(id=3, is_banned=False)),
                ):
                    with patch("app.services.admin_web.ReportExportService", return_value=report_service):
                        job = asyncio.run(
                            service.tenant_create_report_export_job(
                                session,
                                settings=settings,
                                telegram_user_id=123,
                                workspace_id="tn_demo",
                                report_type="orders",
                            )
                        )

        report_service.create_export_job.assert_awaited_once_with(
            session=session,
            settings=settings,
            report_type="orders",
            actor_user_id=3,
            tenant_id=7,
            scope_type="tenant",
        )
        self.assertEqual("orders", job.report_type)
        self.assertEqual("pending", job.status)
        self.assertFalse(job.download_available)
        self.assertNotIn("tenant_id", repr(job))
        self.assertNotIn("actor_user_id", repr(job))

    def test_tenant_report_export_download_uses_handle_and_safe_filename(self) -> None:
        session = _FakeSession()
        service = AdminWebService()
        settings = _settings()
        report_service = SimpleNamespace(
            get_downloadable_tenant_export=AsyncMock(
                return_value=SimpleNamespace(
                    storage_key="exports/tenant_7/81_orders_tenant_7_20260601.csv",
                    filename="orders_tenant_7_20260601.csv",
                    report_type="orders",
                )
            ),
        )
        download_handle = AdminWebReportExportDownloadHandleCodec(settings).encode(
            tenant_id=7,
            export_job_id=81,
        )

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.ReportExportService", return_value=report_service):
                    file_info = asyncio.run(
                        service.tenant_report_export_download_file(
                            session,
                            settings=settings,
                            telegram_user_id=123,
                            workspace_id="tn_demo",
                            download_handle=download_handle,
                        )
                    )

        report_service.get_downloadable_tenant_export.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            export_job_id=81,
        )
        self.assertIsNotNone(file_info)
        self.assertEqual("exports/tenant_7/81_orders_tenant_7_20260601.csv", file_info.storage_key)
        self.assertEqual("orders-report.csv", file_info.filename)
        self.assertNotIn("tenant_7", file_info.filename)

    def test_tenant_report_export_download_rejects_tampered_or_foreign_handle_before_report_service(self) -> None:
        session = _FakeSession()
        service = AdminWebService()
        settings = _settings()
        foreign_handle = AdminWebReportExportDownloadHandleCodec(settings).encode(
            tenant_id=8,
            export_job_id=81,
        )
        report_service = SimpleNamespace(
            get_downloadable_tenant_export=AsyncMock(side_effect=AssertionError("不应查询报表")),
        )

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.ReportExportService", return_value=report_service):
                    with self.assertRaisesRegex(AdminWebSessionError, "报表下载句柄无效"):
                        asyncio.run(
                            service.tenant_report_export_download_file(
                                session,
                                settings=settings,
                                telegram_user_id=123,
                                workspace_id="tn_demo",
                                download_handle=foreign_handle,
                            )
                        )

        report_service.get_downloadable_tenant_export.assert_not_awaited()

    def test_tenant_api_keys_uses_resolved_workspace_tenant_settings_permission_and_safe_handle(self) -> None:
        session = _FakeSession()
        service = AdminWebService()
        settings = _settings()
        now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        repo = SimpleNamespace(has_permission=AsyncMock(return_value=True))
        api_key_service = SimpleNamespace(
            list_tenant_api_keys=AsyncMock(
                return_value=[
                    SimpleNamespace(
                        api_key_id=9,
                        name="readonly",
                        key_prefix="fk_live_ab12",
                        status="active",
                        scopes=["orders:read", "reports:read"],
                        ip_allowlist=["203.0.113.10"],
                        created_at=now,
                        last_used_at=None,
                    )
                ]
            )
        )

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.TenantRepository", return_value=repo):
                    with patch("app.services.admin_web.ApiKeyService", return_value=api_key_service):
                        page = asyncio.run(
                            service.tenant_api_keys(
                                session,
                                settings=settings,
                                telegram_user_id=123,
                                workspace_id="tn_demo",
                                limit=500,
                            )
                        )

        repo.has_permission.assert_awaited_once_with(session, 7, 123, "settings")
        api_key_service.list_tenant_api_keys.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            limit=100,
        )
        self.assertEqual(100, page.limit)
        self.assertEqual("readonly", page.keys[0].name)
        self.assertEqual("fk_live_ab12", page.keys[0].key_prefix)
        self.assertGreater(len(page.keys[0].credential_handle), 16)
        self.assertNotIn("api_key_id", repr(page))
        self.assertNotIn("tenant_id", repr(page))
        self.assertNotIn("key_hash", repr(page))

    def test_tenant_api_keys_rejects_missing_settings_permission_before_service(self) -> None:
        session = _FakeSession()
        service = AdminWebService()
        settings = _settings()
        repo = SimpleNamespace(has_permission=AsyncMock(return_value=False))
        api_key_service = SimpleNamespace(
            list_tenant_api_keys=AsyncMock(side_effect=AssertionError("不应查询 API Key"))
        )

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.TenantRepository", return_value=repo):
                    with patch("app.services.admin_web.ApiKeyService", return_value=api_key_service):
                        with self.assertRaisesRegex(AdminWebSessionError, "无权管理 API Key"):
                            asyncio.run(
                                service.tenant_api_keys(
                                    session,
                                    settings=settings,
                                    telegram_user_id=123,
                                    workspace_id="tn_demo",
                                    limit=20,
                                )
                            )

        repo.has_permission.assert_awaited_once_with(session, 7, 123, "settings")
        api_key_service.list_tenant_api_keys.assert_not_awaited()

    def test_tenant_create_api_key_uses_resolved_workspace_tenant_platform_user_actor_and_safe_handle(self) -> None:
        session = _FakeSession()
        service = AdminWebService()
        settings = _settings()
        repo = SimpleNamespace(has_permission=AsyncMock(return_value=True))
        api_key_service = SimpleNamespace(
            create_tenant_api_key=AsyncMock(
                return_value=SimpleNamespace(
                    api_key_id=9,
                    name="readonly",
                    key_prefix="fk_live_ab12",
                    plain_key="fk_live_plain-secret",
                    status="active",
                    scopes=["orders:read"],
                    ip_allowlist=["203.0.113.10"],
                )
            )
        )

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch.object(
                    service,
                    "get_user_by_telegram_id",
                    new=AsyncMock(return_value=SimpleNamespace(id=3, is_banned=False)),
                ):
                    with patch("app.services.admin_web.TenantRepository", return_value=repo):
                        with patch(
                            "app.services.admin_web.ApiKeyService.create_tenant_api_key",
                            new=api_key_service.create_tenant_api_key,
                        ):
                            created = asyncio.run(
                                service.tenant_create_api_key(
                                    session,
                                    settings=settings,
                                    telegram_user_id=123,
                                    workspace_id="tn_demo",
                                    name=" readonly ",
                                    scopes=["orders:read"],
                                    ip_allowlist=["203.0.113.10"],
                                )
                            )

        repo.has_permission.assert_awaited_once_with(session, 7, 123, "settings")
        api_key_service.create_tenant_api_key.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            name=" readonly ",
            created_by_user_id=3,
            scopes=["orders:read"],
            ip_allowlist=["203.0.113.10"],
        )
        self.assertEqual("fk_live_plain-secret", created.plain_key)
        self.assertGreater(len(created.credential_handle), 16)
        self.assertNotIn("api_key_id", repr(created))
        self.assertNotIn("tenant_id", repr(created))
        self.assertNotIn("key_hash", repr(created))

    def test_tenant_revoke_api_key_uses_resolved_workspace_tenant_handle_and_platform_user_actor(self) -> None:
        session = _FakeSession()
        service = AdminWebService()
        settings = _settings()
        credential_handle = "encoded-handle"
        repo = SimpleNamespace(has_permission=AsyncMock(return_value=True))
        api_key_service = SimpleNamespace(revoke_tenant_api_key=AsyncMock(return_value=True))
        handle_codec = SimpleNamespace(decode=MagicMock(return_value=SimpleNamespace(api_key_id=9)))

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch.object(
                    service,
                    "get_user_by_telegram_id",
                    new=AsyncMock(return_value=SimpleNamespace(id=3, is_banned=False)),
                ):
                    with patch("app.services.admin_web.TenantRepository", return_value=repo):
                        with patch("app.services.admin_web.ApiKeyService", return_value=api_key_service):
                            with patch("app.services.admin_web.AdminWebTenantApiKeyHandleCodec", return_value=handle_codec):
                                result = asyncio.run(
                                    service.tenant_revoke_api_key(
                                        session,
                                        settings=settings,
                                        telegram_user_id=123,
                                        workspace_id="tn_demo",
                                        credential_handle=credential_handle,
                                    )
                                )

        repo.has_permission.assert_awaited_once_with(session, 7, 123, "settings")
        handle_codec.decode.assert_called_once_with(credential_handle, tenant_id=7)
        api_key_service.revoke_tenant_api_key.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            api_key_id=9,
            revoked_by_user_id=3,
        )
        self.assertEqual(AdminWebTenantApiKeyRevokeResult(credential_handle=credential_handle, revoked=True), result)
        self.assertNotIn("api_key_id", repr(result))
        self.assertNotIn("tenant_id", repr(result))

    def test_tenant_revoke_api_key_rejects_missing_key_after_handle_decode(self) -> None:
        session = _FakeSession()
        service = AdminWebService()
        settings = _settings()
        repo = SimpleNamespace(has_permission=AsyncMock(return_value=True))
        api_key_service = SimpleNamespace(revoke_tenant_api_key=AsyncMock(return_value=False))
        handle_codec = SimpleNamespace(decode=MagicMock(return_value=SimpleNamespace(api_key_id=9)))

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch.object(
                    service,
                    "get_user_by_telegram_id",
                    new=AsyncMock(return_value=SimpleNamespace(id=3, is_banned=False)),
                ):
                    with patch("app.services.admin_web.TenantRepository", return_value=repo):
                        with patch("app.services.admin_web.ApiKeyService", return_value=api_key_service):
                            with patch("app.services.admin_web.AdminWebTenantApiKeyHandleCodec", return_value=handle_codec):
                                with self.assertRaisesRegex(ValueError, "API Key 不存在"):
                                    asyncio.run(
                                        service.tenant_revoke_api_key(
                                            session,
                                            settings=settings,
                                            telegram_user_id=123,
                                            workspace_id="tn_demo",
                                            credential_handle="encoded-handle",
                                        )
                                    )

        api_key_service.revoke_tenant_api_key.assert_awaited_once()

    def test_tenant_risk_dashboard_uses_resolved_workspace_tenant_and_sanitizes_text(self) -> None:
        session = _FakeSession()
        service = AdminWebService()
        dispute = SimpleNamespace(
            out_trade_no="ORD123",
            buyer_telegram_user_id=456,
            source_type="self",
            order_status="paid",
            amount=Decimal("9.90"),
            currency="USDT",
            status="open",
            reason="买家未收到",
            resolution="https://pay.example/proof?token=plain-secret",
            created_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 1, 12, 5, tzinfo=timezone.utc),
        )
        after_sale = SimpleNamespace(
            out_trade_no="ORD456",
            buyer_telegram_user_id=789,
            source_type="reseller",
            order_status="delivered",
            amount=Decimal("19.90"),
            currency="USDT",
            case_type="refund",
            status="reviewing",
            requested_amount=Decimal("10.00"),
            refunded_amount=Decimal("0"),
            reason="authorization bearer plain-secret",
            resolution="客服处理中",
            created_at=datetime(2026, 6, 2, 13, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 2, 13, 5, tzinfo=timezone.utc),
        )
        risk_service = SimpleNamespace(
            list_disputes=AsyncMock(return_value=[dispute]),
            list_after_sales=AsyncMock(return_value=[after_sale]),
        )

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.RiskControlService", return_value=risk_service):
                    dashboard = asyncio.run(
                        service.tenant_risk_dashboard(
                            session,
                            telegram_user_id=123,
                            workspace_id="tn_demo",
                            status="all",
                            limit=500,
                        )
                    )

        risk_service.list_disputes.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            status=None,
            limit=100,
        )
        risk_service.list_after_sales.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            status=None,
            limit=100,
        )
        self.assertIsNone(dashboard.status)
        self.assertEqual(100, dashboard.limit)
        self.assertEqual("内容已隐藏", dashboard.disputes[0].resolution)
        self.assertEqual("内容已隐藏", dashboard.after_sales[0].reason)
        self.assertNotIn("plain-secret", repr(dashboard))

    def test_tenant_create_withdrawal_uses_resolved_workspace_tenant_and_platform_user_actor(self) -> None:
        session = _FakeSession()
        service = AdminWebService()
        withdrawal = SimpleNamespace(
            amount=Decimal("1.25"),
            currency="USDT",
            network="TRC20",
            address="TAbc123456XyZ789",
            status="pending",
            requested_at=datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc),
            reviewed_at=None,
            completed_at=None,
        )
        ledger_service = SimpleNamespace(
            create_withdrawal_request=AsyncMock(return_value=withdrawal),
        )

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch.object(
                    service,
                    "get_user_by_telegram_id",
                    new=AsyncMock(return_value=SimpleNamespace(id=55, is_banned=False)),
                ) as get_user:
                    with patch("app.services.admin_web.LedgerService", return_value=ledger_service):
                        created = asyncio.run(
                            service.tenant_create_withdrawal_request(
                                session,
                                telegram_user_id=123,
                                workspace_id="tn_demo",
                                amount=Decimal("1.25"),
                                network="trc20",
                                address=" TAbc123456XyZ789 ",
                                currency="usdt",
                            )
                        )

        get_user.assert_awaited_once_with(session, 123)
        ledger_service.create_withdrawal_request.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            amount=Decimal("1.25"),
            network="TRC20",
            address="TAbc123456XyZ789",
            currency="USDT",
            actor_user_id=55,
        )
        self.assertEqual("TAbc12***XyZ789", created.address_masked)
        self.assertEqual("pending", created.status)

    def test_tenant_create_withdrawal_rejects_invalid_amount_precision_before_ledger(self) -> None:
        session = _FakeSession()
        service = AdminWebService()
        ledger_service = SimpleNamespace(
            create_withdrawal_request=AsyncMock(side_effect=AssertionError("不应创建提现申请")),
        )

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.LedgerService", return_value=ledger_service):
                    with self.assertRaisesRegex(ValueError, "最多支持 8 位小数"):
                        asyncio.run(
                            service.tenant_create_withdrawal_request(
                                session,
                                telegram_user_id=123,
                                workspace_id="tn_demo",
                                amount=Decimal("1.123456789"),
                                network="TRC20",
                                address="TAbc123456789",
                            )
                        )

        ledger_service.create_withdrawal_request.assert_not_called()

    def test_tenant_supply_review_supplier_application_decodes_handle_server_side(self) -> None:
        settings = _settings()
        session = _FakeSession()
        handle = AdminWebApplicationHandleCodec(settings).encode(
            supplier_tenant_id=7,
            supplier_offer_id=91,
            reseller_tenant_id=77,
        )
        reviewed = SimpleNamespace(
            supplier_tenant_id=7,
            supplier_offer_id=91,
            reseller_tenant_id=77,
            reseller_store_name="代理店铺",
            product_name="供货卡密",
            status="active",
            pricing_value=Decimal("9.00"),
            min_sale_price=None,
            currency="USDT",
            updated_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        )
        approve = AsyncMock(return_value=reviewed)
        service = AdminWebService()

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.load_tenant_feature_flags", AsyncMock(return_value={"self_sale": True, "supplier": True, "reseller": True})):
                    with patch("app.services.admin_web.SupplyService") as supply_service:
                        supply_service.return_value.approve_reseller_application = approve
                        application = asyncio.run(
                            service.tenant_supply_review_supplier_application(
                                session,
                                settings=settings,
                                telegram_user_id=123,
                                workspace_id="tn_demo",
                                supplier_application_id=handle,
                                action="approve",
                            )
                        )

        approve.assert_awaited_once_with(
            session=session,
            supplier_tenant_id=7,
            supplier_offer_id=91,
            reseller_tenant_id=77,
            actor_user_id=None,
        )
        decoded = AdminWebApplicationHandleCodec(settings).decode(application.supplier_application_id, supplier_tenant_id=7)
        self.assertEqual(91, decoded.supplier_offer_id)
        self.assertEqual(77, decoded.reseller_tenant_id)
        self.assertEqual("active", application.status)

    def test_tenant_supply_set_supplier_rule_decodes_handle_server_side(self) -> None:
        settings = _settings()
        session = _FakeSession()
        handle = AdminWebSupplierRuleHandleCodec(settings).encode(
            supplier_tenant_id=7,
            supplier_offer_id=91,
            reseller_tenant_id=77,
        )
        updated = SimpleNamespace(
            supplier_tenant_id=7,
            supplier_offer_id=91,
            reseller_tenant_id=77,
            reseller_store_name="代理店铺",
            product_name="供货卡密",
            status="active",
            pricing_value=Decimal("8.50"),
            min_sale_price=Decimal("10.00"),
            currency="USDT",
            updated_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        )
        set_existing_rule = AsyncMock(return_value=updated)
        service = AdminWebService()

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.load_tenant_feature_flags", AsyncMock(return_value={"self_sale": True, "supplier": True, "reseller": True})):
                    with patch("app.services.admin_web.SupplyService") as supply_service:
                        supply_service.return_value.set_existing_reseller_rule = set_existing_rule
                        rule = asyncio.run(
                            service.tenant_supply_set_supplier_rule(
                                session,
                                settings=settings,
                                telegram_user_id=123,
                                workspace_id="tn_demo",
                                supplier_rule_id=handle,
                                pricing_value=Decimal("8.50"),
                                min_sale_price=Decimal("10.00"),
                            )
                        )

        set_existing_rule.assert_awaited_once_with(
            session=session,
            supplier_tenant_id=7,
            supplier_offer_id=91,
            reseller_tenant_id=77,
            actor_user_id=None,
            pricing_value=Decimal("8.50"),
            min_sale_price=Decimal("10.00"),
        )
        decoded = AdminWebSupplierRuleHandleCodec(settings).decode(rule.supplier_rule_id, supplier_tenant_id=7)
        self.assertEqual(91, decoded.supplier_offer_id)
        self.assertEqual(77, decoded.reseller_tenant_id)
        self.assertEqual("active", rule.status)

    def test_tenant_update_product_metadata_uses_resolved_workspace_tenant(self) -> None:
        session = _FakeSession()
        product = SimpleNamespace(
            id=12,
            name="Demo Product",
            category=None,
            sort_order=9,
            status="on",
            delivery_type="card_pool",
            suggested_price=Decimal("9.90"),
            currency="USDT",
        )
        variant = SimpleNamespace(price=Decimal("8.80"), currency="USDT")
        repo = SimpleNamespace(
            set_product_category=AsyncMock(return_value=True),
            set_product_sort_order=AsyncMock(return_value=True),
            get_product_with_default_variant=AsyncMock(return_value=(product, variant)),
            inventory_summary=AsyncMock(return_value={12: {"available": 4}}),
        )
        service = AdminWebService()

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.ProductRepository", return_value=repo):
                    updated = asyncio.run(
                        service.tenant_update_product_metadata(
                            session,
                            telegram_user_id=123,
                            workspace_id="tn_demo",
                            product_id=12,
                            category=None,
                            category_provided=True,
                            sort_order=9,
                        )
                    )

        repo.set_product_category.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            product_id=12,
            category=None,
        )
        repo.set_product_sort_order.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            product_id=12,
            sort_order=9,
        )
        repo.get_product_with_default_variant.assert_awaited_once_with(session, 7, 12)
        repo.inventory_summary.assert_awaited_once_with(session, 7, 12)
        self.assertEqual(12, updated.product_id)
        self.assertIsNone(updated.category)
        self.assertEqual(9, updated.sort_order)
        self.assertEqual(4, updated.available_count)

    def test_tenant_update_store_settings_uses_resolved_workspace_tenant_and_settings_permission(self) -> None:
        session = _FakeSession()
        tenant = SimpleNamespace(
            id=7,
            public_id="tn_demo",
            store_name="旧店铺",
            self_sale_enabled=True,
            supplier_enabled=False,
            reseller_enabled=False,
        )
        repo = SimpleNamespace(
            has_permission=AsyncMock(return_value=True),
            update_store_name=AsyncMock(return_value=None),
            upsert_setting=AsyncMock(return_value=None),
            get_settings=AsyncMock(
                return_value={
                    "welcome": {"text": "欢迎下单"},
                    "support": {"text": "@help"},
                    "order_timeout_minutes": {"value": 45},
                    "feature_flags": {"self_sale": False, "supplier": True, "reseller": True},
                }
            ),
        )
        service = AdminWebService()

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(service, "_load_tenant_by_public_id", new=AsyncMock(return_value=tenant)):
                with patch("app.services.admin_web.TenantRepository", return_value=repo):
                    updated = asyncio.run(
                        service.tenant_update_store_settings(
                            session,
                            telegram_user_id=123,
                            workspace_id="tn_demo",
                            store_name=" 新店铺 ",
                            welcome_text=" 欢迎下单 ",
                            support_text=" @help ",
                            order_timeout_minutes=45,
                            self_sale_enabled=False,
                            supplier_enabled=True,
                            reseller_enabled=True,
                        )
                    )

        repo.has_permission.assert_awaited_once_with(session, 7, 123, "settings")
        repo.update_store_name.assert_awaited_once_with(session, 7, "新店铺")
        repo.upsert_setting.assert_any_await(session, 7, "welcome", {"text": "欢迎下单"})
        repo.upsert_setting.assert_any_await(session, 7, "support", {"text": "@help"})
        repo.upsert_setting.assert_any_await(session, 7, "order_timeout_minutes", {"value": 45})
        repo.upsert_setting.assert_any_await(
            session,
            7,
            "feature_flags",
            {"self_sale": False, "supplier": True, "reseller": True},
        )
        self.assertEqual(2, repo.get_settings.await_count)
        self.assertFalse(tenant.self_sale_enabled)
        self.assertTrue(tenant.supplier_enabled)
        self.assertTrue(tenant.reseller_enabled)
        self.assertEqual("新店铺", updated.store_name)
        self.assertEqual("欢迎下单", updated.welcome_text)
        self.assertEqual("@help", updated.support_text)
        self.assertEqual(45, updated.order_timeout_minutes)
        self.assertFalse(updated.self_sale_enabled)
        self.assertTrue(updated.supplier_enabled)
        self.assertTrue(updated.reseller_enabled)

    def test_tenant_update_store_settings_preserves_existing_feature_flags_on_partial_update(self) -> None:
        session = _FakeSession()
        tenant = SimpleNamespace(
            id=7,
            public_id="tn_demo",
            store_name="Demo Store",
            self_sale_enabled=True,
            supplier_enabled=False,
            reseller_enabled=True,
        )
        repo = SimpleNamespace(
            has_permission=AsyncMock(return_value=True),
            update_store_name=AsyncMock(side_effect=AssertionError("不应更新店铺名称")),
            upsert_setting=AsyncMock(return_value=None),
            get_settings=AsyncMock(
                side_effect=[
                    {
                        "welcome": {"text": "欢迎下单"},
                        "support": {"text": "@help"},
                        "order_timeout_minutes": {"value": 45},
                        "feature_flags": {"self_sale": True, "supplier": False, "reseller": True, "legacy": True},
                    },
                    {
                        "welcome": {"text": "欢迎下单"},
                        "support": {"text": "@help"},
                        "order_timeout_minutes": {"value": 45},
                        "feature_flags": {"self_sale": True, "supplier": True, "reseller": True, "legacy": True},
                    },
                ]
            ),
        )
        service = AdminWebService()

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(service, "_load_tenant_by_public_id", new=AsyncMock(return_value=tenant)):
                with patch("app.services.admin_web.TenantRepository", return_value=repo):
                    updated = asyncio.run(
                        service.tenant_update_store_settings(
                            session,
                            telegram_user_id=123,
                            workspace_id="tn_demo",
                            supplier_enabled=True,
                        )
                    )

        repo.has_permission.assert_awaited_once_with(session, 7, 123, "settings")
        repo.upsert_setting.assert_awaited_once_with(
            session,
            7,
            "feature_flags",
            {"self_sale": True, "supplier": True, "reseller": True, "legacy": True},
        )
        self.assertTrue(tenant.self_sale_enabled)
        self.assertTrue(tenant.supplier_enabled)
        self.assertTrue(tenant.reseller_enabled)
        self.assertTrue(updated.self_sale_enabled)
        self.assertTrue(updated.supplier_enabled)
        self.assertTrue(updated.reseller_enabled)

    def test_tenant_store_settings_reads_feature_flags_compatibility_values(self) -> None:
        session = _FakeSession()
        tenant = SimpleNamespace(
            id=7,
            public_id="tn_demo",
            store_name="Demo Store",
            self_sale_enabled=True,
            supplier_enabled=False,
            reseller_enabled=False,
        )
        repo = SimpleNamespace(
            get_settings=AsyncMock(
                return_value={
                    "welcome": {"text": "欢迎下单"},
                    "support": {"text": "@help"},
                    "order_timeout_minutes": {"value": 45},
                    "feature_flags": {"self_sale": False, "supplier": True, "reseller": True},
                }
            ),
        )
        service = AdminWebService()

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(service, "_load_tenant_by_public_id", new=AsyncMock(return_value=tenant)):
                with patch("app.services.admin_web.TenantRepository", return_value=repo):
                    settings = asyncio.run(
                        service.tenant_store_settings(
                            session,
                            telegram_user_id=123,
                            workspace_id="tn_demo",
                        )
                    )

        repo.get_settings.assert_awaited_once_with(session, 7)
        self.assertFalse(settings.self_sale_enabled)
        self.assertTrue(settings.supplier_enabled)
        self.assertTrue(settings.reseller_enabled)

    def test_tenant_update_store_settings_rejects_missing_settings_permission(self) -> None:
        session = _FakeSession()
        repo = SimpleNamespace(
            has_permission=AsyncMock(return_value=False),
            update_store_name=AsyncMock(side_effect=AssertionError("不应更新店铺名称")),
            upsert_setting=AsyncMock(side_effect=AssertionError("不应更新设置")),
            get_settings=AsyncMock(side_effect=AssertionError("不应读取设置")),
        )
        service = AdminWebService()

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7, store_name="Demo Store")),
            ):
                with patch("app.services.admin_web.TenantRepository", return_value=repo):
                    with self.assertRaisesRegex(AdminWebSessionError, "无权修改店铺设置"):
                        asyncio.run(
                            service.tenant_update_store_settings(
                                session,
                                telegram_user_id=123,
                                workspace_id="tn_demo",
                                store_name="新店铺",
                            )
                        )

        repo.has_permission.assert_awaited_once_with(session, 7, 123, "settings")

    def test_tenant_update_payment_config_uses_resolved_workspace_tenant(self) -> None:
        session = _FakeSession()
        settings = _settings()
        service = AdminWebService()
        status = SimpleNamespace(
            provider="epay_compatible",
            enabled=True,
            scope_type="tenant",
            gateway_url="https://pay.example",
            merchant_id="merchant123456",
            asset=None,
            network=None,
            payment_type="alipay",
            device="mobile",
            return_url=None,
            subject="FakaBot Order",
            key_configured=True,
        )
        payment_service = SimpleNamespace(
            upsert_tenant_payment_config=AsyncMock(return_value=status),
            list_tenant_payment_provider_summaries=AsyncMock(
                return_value=[
                    SimpleNamespace(
                        provider_name="epay_compatible",
                        display_name="易支付兼容",
                        create_payment_available=True,
                        callback_available=True,
                        query_order_available=False,
                        reconcile_available=False,
                        production_ready=False,
                        staging_verified=False,
                        offline_only=True,
                    ),
                ],
            ),
        )

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.PaymentConfigService", return_value=payment_service):
                    config = asyncio.run(
                        service.tenant_update_payment_config(
                            session,
                            settings=settings,
                            telegram_user_id=123,
                            workspace_id="tn_demo",
                            provider_name="epay_compatible",
                            config_payload={"gateway_url": "https://pay.example", "merchant_id": "merchant123456"},
                        )
                    )

        payment_service.upsert_tenant_payment_config.assert_awaited_once_with(
            session=session,
            settings=settings,
            tenant_id=7,
            provider="epay_compatible",
            config_payload={"gateway_url": "https://pay.example", "merchant_id": "merchant123456"},
        )
        self.assertEqual("epay_compatible", config.provider)
        self.assertEqual("me***56", config.merchant_id_masked)
        self.assertTrue(config.key_configured)

    def test_business_plugin_capabilities_uses_workspace_and_safe_non_secret_states(self) -> None:
        session = _FakeSession()
        service = AdminWebService()
        external_connection_service = SimpleNamespace(
            list_connections=AsyncMock(
                return_value=[
                    SimpleNamespace(provider_name="mcy_shop", status="active"),
                    SimpleNamespace(provider_name="mcy_shop", status="disabled"),
                ]
            ),
            load_runtime_credentials=AsyncMock(side_effect=AssertionError("不应解密外部源凭据")),
        )
        manifests = [
            BusinessPluginManifest(
                plugin_id="payment_epay_compatible",
                name="易支付兼容 支付插件",
                version="builtin",
                kind="payment",
                contract_version="epay_compatible_offline_page_v1",
                capabilities={"create_payment": True, "callback": True},
                entrypoint="app.services.payments.configs:list_payment_provider_summaries",
                production_ready=False,
                staging_verified=False,
                offline_only=True,
                tenant_configurable=True,
                platform_configurable=False,
            ),
            BusinessPluginManifest(
                plugin_id="external_source_mcy_shop",
                name="mcy_shop 外部货源插件",
                version="builtin",
                kind="external_source",
                contract_version="mcy_shop_offline_fixture_v1",
                capabilities={"catalog_sync": True, "order": True, "delivery": True},
                entrypoint="fakabot_ext_mcy_shop:create_provider",
                production_ready=False,
                staging_verified=False,
                offline_only=True,
                tenant_configurable=True,
                platform_configurable=False,
            ),
        ]

        with patch.object(
            service,
            "_tenant_workspace",
            new=AsyncMock(return_value=AdminWebWorkspaceSummary(
                workspace_id="tn_demo",
                kind="tenant",
                role="owner",
                title="Demo Store",
            )),
        ) as tenant_workspace:
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ) as load_tenant:
                with patch("app.services.admin_web.list_current_business_plugin_manifests", return_value=manifests):
                    with patch(
                        "app.services.admin_web._load_tenant_payment_plugin_states",
                        new=AsyncMock(return_value={"epay_compatible": {"enabled": True, "scope_type": "tenant"}}),
                    ) as load_payment_states:
                        with patch(
                            "app.services.admin_web.ExternalSourceConnectionService",
                            return_value=external_connection_service,
                        ):
                            with patch(
                                "app.services.admin_web.PaymentConfigService",
                                side_effect=AssertionError("不应解密支付配置"),
                            ):
                                summary = asyncio.run(
                                    service.business_plugin_capabilities(
                                        session,
                                        telegram_user_id=123,
                                        workspace_id="tn_demo",
                                    )
                                )

        tenant_workspace.assert_awaited_once_with(session, 123, "tn_demo")
        load_tenant.assert_awaited_once_with(session, "tn_demo")
        load_payment_states.assert_awaited_once_with(session, 7)
        external_connection_service.list_connections.assert_awaited_once_with(session, tenant_id=7)
        external_connection_service.load_runtime_credentials.assert_not_awaited()
        self.assertEqual("tenant", summary.workspace_kind)
        self.assertFalse(summary.dynamic_loading_enabled)
        self.assertFalse(summary.remote_code_enabled)
        self.assertFalse(summary.real_external_integration_enabled)
        payment = next(plugin for plugin in summary.plugins if plugin.plugin_id == "payment_epay_compatible")
        self.assertEqual("epay_compatible", payment.provider_name)
        self.assertTrue(payment.workspace_configured)
        self.assertTrue(payment.workspace_enabled)
        self.assertEqual("tenant", payment.scope_type)
        external = next(plugin for plugin in summary.plugins if plugin.plugin_id == "external_source_mcy_shop")
        self.assertEqual("mcy_shop", external.provider_name)
        self.assertEqual(1, external.active_connection_count)
        self.assertEqual(1, external.disabled_connection_count)
        self.assertTrue(external.workspace_configured)
        self.assertTrue(external.workspace_enabled)

    def test_business_plugin_capabilities_platform_workspace_requires_platform_admin(self) -> None:
        session = _FakeSession()
        service = AdminWebService()

        with patch.object(
            service,
            "get_user_by_telegram_id",
            new=AsyncMock(return_value=SimpleNamespace(is_banned=False, is_platform_admin=False)),
        ):
            with self.assertRaisesRegex(AdminWebSessionError, "无权访问主 Bot 管理工作区"):
                asyncio.run(
                    service.business_plugin_capabilities(
                        session,
                        telegram_user_id=456,
                        workspace_id=PLATFORM_WORKSPACE_ID,
                    )
                )

    def test_tenant_external_source_connections_uses_resolved_workspace_and_safe_summaries(self) -> None:
        session = _FakeSession()
        settings = _settings()
        service = AdminWebService()
        repo = SimpleNamespace(has_permission=AsyncMock(return_value=True))
        connection_summary = SimpleNamespace(
            connection_id=11,
            provider_name="mcy_shop",
            source_key="fixture",
            display_name="Fixture Shop",
            status="active",
            credential_fields=["sensitive_1", "sensitive_2"],
            created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            last_used_at=None,
        )
        external_connection_service = SimpleNamespace(
            list_connections=AsyncMock(return_value=[connection_summary]),
            load_runtime_credentials=AsyncMock(side_effect=AssertionError("不应解密外部源凭据")),
        )
        provider_summary = SimpleNamespace(
            provider_name="mcy_shop",
            integration_kind="offline_fixture",
            contract_name="mcy_shop_offline_fixture_v1",
            production_ready=False,
            staging_verified=False,
            capabilities=SimpleNamespace(
                catalog_sync_available=True,
                catalog_context_available=True,
                catalog_product_available=True,
                catalog_product_context_available=True,
                order_available=True,
                order_context_available=True,
                delivery_available=True,
                delivery_context_available=True,
                auto_fulfillment_idempotent_available=False,
            ),
        )

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(service, "_load_tenant_by_public_id", new=AsyncMock(return_value=SimpleNamespace(id=7))):
                with patch("app.services.admin_web.TenantRepository", return_value=repo):
                    with patch("app.services.admin_web.list_provider_summaries", return_value=[provider_summary]):
                        with patch(
                            "app.services.admin_web.ExternalSourceConnectionService",
                            return_value=external_connection_service,
                        ):
                            page = asyncio.run(
                                service.tenant_external_source_connections(
                                    session,
                                    settings=settings,
                                    telegram_user_id=123,
                                    workspace_id="tn_demo",
                                    provider_name="mcy_shop",
                                )
                            )

        repo.has_permission.assert_awaited_once_with(session, 7, 123, "settings")
        external_connection_service.list_connections.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            provider_name="mcy_shop",
        )
        external_connection_service.load_runtime_credentials.assert_not_awaited()
        self.assertEqual("mcy_shop", page.providers[0].provider_name)
        self.assertEqual("Fixture Shop", page.connections[0].display_name)
        self.assertEqual(2, page.connections[0].credential_field_count)
        connection_handle = page.connections[0].connection_handle
        self.assertNotEqual("11", connection_handle)
        handle_claims = AdminWebExternalSourceConnectionHandleCodec(settings).decode(connection_handle, tenant_id=7)
        self.assertEqual(11, handle_claims.connection_id)
        with self.assertRaisesRegex(AdminWebSessionError, "外部源连接句柄无效"):
            AdminWebExternalSourceConnectionHandleCodec(settings).decode(connection_handle, tenant_id=8)

    def test_tenant_create_external_source_connection_uses_settings_permission_and_platform_user_actor(self) -> None:
        session = _FakeSession()
        settings = _settings()
        service = AdminWebService()
        repo = SimpleNamespace(has_permission=AsyncMock(return_value=True))
        connection_summary = SimpleNamespace(
            connection_id=11,
            provider_name="mcy_shop",
            source_key="fixture",
            display_name="Fixture Shop",
            status="active",
            credential_fields=["sensitive_1"],
            created_at=None,
            last_used_at=None,
        )
        external_connection_service = SimpleNamespace(
            create_connection=AsyncMock(return_value=connection_summary),
            load_runtime_credentials=AsyncMock(side_effect=AssertionError("不应解密外部源凭据")),
        )

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(service, "_load_tenant_by_public_id", new=AsyncMock(return_value=SimpleNamespace(id=7))):
                with patch.object(
                    service,
                    "get_user_by_telegram_id",
                    new=AsyncMock(return_value=SimpleNamespace(id=501, is_banned=False)),
                ):
                    with patch("app.services.admin_web.TenantRepository", return_value=repo):
                        with patch(
                            "app.services.admin_web.ExternalSourceConnectionService",
                            return_value=external_connection_service,
                        ):
                            item = asyncio.run(
                                service.tenant_create_external_source_connection(
                                    session,
                                    settings=settings,
                                    telegram_user_id=123,
                                    workspace_id="tn_demo",
                                    provider_name="mcy_shop",
                                    source_key="fixture",
                                    display_name="Fixture Shop",
                                    credentials={"base_url": "http://mcy-shop-fixture.local"},
                                )
                            )

        repo.has_permission.assert_awaited_once_with(session, 7, 123, "settings")
        external_connection_service.create_connection.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            provider_name="mcy_shop",
            source_key="fixture",
            display_name="Fixture Shop",
            credentials={"base_url": "http://mcy-shop-fixture.local"},
            settings=settings,
            created_by_user_id=501,
        )
        external_connection_service.load_runtime_credentials.assert_not_awaited()
        self.assertEqual("mcy_shop", item.provider_name)
        self.assertEqual(1, item.credential_field_count)

    def test_tenant_disable_external_source_connection_uses_handle_and_resolved_tenant(self) -> None:
        session = _FakeSession()
        settings = _settings()
        service = AdminWebService()
        repo = SimpleNamespace(has_permission=AsyncMock(return_value=True))
        connection_summary = SimpleNamespace(
            connection_id=11,
            provider_name="mcy_shop",
            source_key="fixture",
            display_name="Fixture Shop",
            status="disabled",
            credential_fields=["sensitive_1"],
            created_at=None,
            last_used_at=None,
        )
        external_connection_service = SimpleNamespace(
            disable_connection=AsyncMock(return_value=True),
            get_connection=AsyncMock(return_value=connection_summary),
            load_runtime_credentials=AsyncMock(side_effect=AssertionError("不应解密外部源凭据")),
        )
        handle = AdminWebExternalSourceConnectionHandleCodec(settings).encode(tenant_id=7, connection_id=11)

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(service, "_load_tenant_by_public_id", new=AsyncMock(return_value=SimpleNamespace(id=7))):
                with patch("app.services.admin_web.TenantRepository", return_value=repo):
                    with patch(
                        "app.services.admin_web.ExternalSourceConnectionService",
                        return_value=external_connection_service,
                    ):
                        item = asyncio.run(
                            service.tenant_disable_external_source_connection(
                                session,
                                settings=settings,
                                telegram_user_id=123,
                                workspace_id="tn_demo",
                                connection_handle=handle,
                            )
                        )

        repo.has_permission.assert_awaited_once_with(session, 7, 123, "settings")
        external_connection_service.disable_connection.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            connection_id=11,
        )
        external_connection_service.get_connection.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            connection_id=11,
        )
        external_connection_service.load_runtime_credentials.assert_not_awaited()
        self.assertEqual("disabled", item.status)

    def test_tenant_external_source_catalog_sync_uses_handle_and_resolved_tenant_connection(self) -> None:
        session = _FakeSession()
        settings = _settings()
        service = AdminWebService()
        repo = SimpleNamespace(has_permission=AsyncMock(return_value=True))
        runtime_auth = SimpleNamespace(credentials={"api_key": "plain-secret"})
        connection_summary = SimpleNamespace(
            connection_id=11,
            provider_name="mcy_shop",
            source_key="fixture",
            display_name="Fixture Shop",
            status="active",
            credential_fields=["sensitive_1"],
            created_at=None,
            last_used_at=None,
        )
        external_connection_service = SimpleNamespace(
            get_connection=AsyncMock(return_value=connection_summary),
            load_runtime_credentials=AsyncMock(return_value=runtime_auth),
        )
        sync_result = ExternalCatalogSyncResult(
            created_count=1,
            updated_count=2,
            skipped_count=1,
            next_cursor="next-page",
            products=[
                SyncedExternalProduct(
                    product_id=101,
                    external_source="mcy_shop",
                    source_key="fixture",
                    external_id="sku-1",
                    action="created",
                    status="on",
                ),
                SyncedExternalProduct(
                    product_id=None,
                    external_source="mcy_shop",
                    source_key="fixture",
                    external_id="secret-sku",
                    action="skipped",
                    status="skipped",
                    skipped_reason="外部商品不存在",
                ),
            ],
        )
        sync_service = SimpleNamespace(sync_registered_catalog=AsyncMock(return_value=sync_result))
        handle = AdminWebExternalSourceConnectionHandleCodec(settings).encode(tenant_id=7, connection_id=11)

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)) as tenant_workspace:
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ) as load_tenant:
                with patch("app.services.admin_web.TenantRepository", return_value=repo):
                    with patch(
                        "app.services.admin_web.ExternalSourceConnectionService",
                        return_value=external_connection_service,
                    ):
                        with patch("app.services.admin_web.ExternalCatalogSyncService", return_value=sync_service):
                            item = asyncio.run(
                                service.tenant_sync_external_catalog(
                                    session,
                                    settings=settings,
                                    telegram_user_id=123,
                                    workspace_id="tn_demo",
                                    connection_handle=handle,
                                    cursor="page-1",
                                    limit=20,
                                    max_pages=1,
                                )
                            )

        tenant_workspace.assert_awaited_once_with(session, 123, "tn_demo")
        load_tenant.assert_awaited_once_with(session, "tn_demo")
        repo.has_permission.assert_awaited_once_with(session, 7, 123, "settings")
        external_connection_service.get_connection.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            connection_id=11,
        )
        external_connection_service.load_runtime_credentials.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            connection_id=11,
            settings=settings,
        )
        sync_service.sync_registered_catalog.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            provider_name="mcy_shop",
            source_key="fixture",
            connection_id=11,
            cursor="page-1",
            limit=20,
            max_pages=1,
            runtime_auth=runtime_auth,
        )
        self.assertEqual("mcy_shop", item.provider_name)
        self.assertEqual("fixture", item.source_key)
        self.assertEqual(1, item.created_count)
        self.assertEqual(2, item.updated_count)
        self.assertEqual(1, item.skipped_count)
        self.assertEqual("next-page", item.next_cursor)
        self.assertEqual(101, item.products[0].product_id)
        self.assertEqual("created", item.products[0].action)
        self.assertFalse(hasattr(item.products[0], "external_id"))
        self.assertFalse(hasattr(item.products[0], "external_source"))

    def test_tenant_external_source_catalog_sync_rejects_tampered_or_foreign_handle_before_sync_service(self) -> None:
        session = _FakeSession()
        settings = _settings()
        service = AdminWebService()
        repo = SimpleNamespace(has_permission=AsyncMock(return_value=True))
        external_connection_service = SimpleNamespace(
            get_connection=AsyncMock(side_effect=AssertionError("不应查询外部源连接")),
            load_runtime_credentials=AsyncMock(side_effect=AssertionError("不应解密外部源凭据")),
        )
        sync_service = SimpleNamespace(
            sync_registered_catalog=AsyncMock(side_effect=AssertionError("不应同步外部目录")),
        )
        foreign_handle = AdminWebExternalSourceConnectionHandleCodec(settings).encode(tenant_id=8, connection_id=11)

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(service, "_load_tenant_by_public_id", new=AsyncMock(return_value=SimpleNamespace(id=7))):
                with patch("app.services.admin_web.TenantRepository", return_value=repo):
                    with patch(
                        "app.services.admin_web.ExternalSourceConnectionService",
                        return_value=external_connection_service,
                    ):
                        with patch("app.services.admin_web.ExternalCatalogSyncService", return_value=sync_service):
                            with self.assertRaisesRegex(AdminWebSessionError, "外部源连接句柄无效"):
                                asyncio.run(
                                    service.tenant_sync_external_catalog(
                                        session,
                                        settings=settings,
                                        telegram_user_id=123,
                                        workspace_id="tn_demo",
                                        connection_handle=foreign_handle,
                                    )
                                )

        repo.has_permission.assert_awaited_once_with(session, 7, 123, "settings")
        external_connection_service.get_connection.assert_not_awaited()
        external_connection_service.load_runtime_credentials.assert_not_awaited()
        sync_service.sync_registered_catalog.assert_not_awaited()

    def test_tenant_external_source_catalog_products_uses_handle_without_runtime_credentials_or_provider(self) -> None:
        session = _FakeSession()
        settings = _settings()
        service = AdminWebService()
        repo = SimpleNamespace(has_permission=AsyncMock(return_value=True))
        connection_summary = SimpleNamespace(
            connection_id=11,
            provider_name="mcy_shop",
            source_key="fixture",
            display_name="Fixture Shop",
            status="active",
            credential_fields=["sensitive_1"],
            created_at=None,
            last_used_at=None,
        )
        external_connection_service = SimpleNamespace(
            get_connection=AsyncMock(return_value=connection_summary),
            load_runtime_credentials=AsyncMock(side_effect=AssertionError("不应解密外部源凭据")),
        )
        product = SimpleNamespace(
            id=101,
            name="Fixture Card",
            category="cards",
            status="on",
            delivery_type="card_pool",
            suggested_price=Decimal("10.00000000"),
            currency="USDT",
            updated_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
        )
        variant = SimpleNamespace(price=Decimal("9.99000000"), currency="USDT")
        handle = AdminWebExternalSourceConnectionHandleCodec(settings).encode(tenant_id=7, connection_id=11)

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)) as tenant_workspace:
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ) as load_tenant:
                with patch("app.services.admin_web.TenantRepository", return_value=repo):
                    with patch(
                        "app.services.admin_web.ExternalSourceConnectionService",
                        return_value=external_connection_service,
                    ):
                        with patch(
                            "app.services.admin_web._count_external_source_catalog_products",
                            new=AsyncMock(return_value=1),
                        ) as count_products:
                            with patch(
                                "app.services.admin_web._list_external_source_catalog_products",
                                new=AsyncMock(return_value=[(product, variant, 3)]),
                            ) as list_products:
                                page = asyncio.run(
                                    service.tenant_external_source_catalog_products(
                                        session,
                                        settings=settings,
                                        telegram_user_id=123,
                                        workspace_id="tn_demo",
                                        connection_handle=handle,
                                        limit=200,
                                        offset=0,
                                    )
                                )

        tenant_workspace.assert_awaited_once_with(session, 123, "tn_demo")
        load_tenant.assert_awaited_once_with(session, "tn_demo")
        repo.has_permission.assert_awaited_once_with(session, 7, 123, "settings")
        external_connection_service.get_connection.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            connection_id=11,
        )
        external_connection_service.load_runtime_credentials.assert_not_awaited()
        count_products.assert_awaited_once_with(
            session,
            tenant_id=7,
            provider_name="mcy_shop",
            source_key="fixture",
        )
        list_products.assert_awaited_once_with(
            session,
            tenant_id=7,
            provider_name="mcy_shop",
            source_key="fixture",
            limit=100,
            offset=0,
        )
        self.assertEqual("mcy_shop", page.provider_name)
        self.assertEqual("Fixture Shop", page.display_name)
        self.assertEqual(1, page.total_count)
        self.assertEqual(100, page.limit)
        self.assertEqual(101, page.items[0].product_id)
        self.assertEqual(Decimal("9.99000000"), page.items[0].price)
        self.assertFalse(hasattr(page.items[0], "external_id"))
        self.assertFalse(hasattr(page.items[0], "external_source"))

    def test_tenant_order_diagnostics_uses_resolved_workspace_tenant_and_strips_internal_ids(self) -> None:
        session = _FakeSession()
        service = AdminWebService()
        summary = SimpleNamespace(
            order_id=99,
            out_trade_no="ORD123",
            source_type="self",
            status="paid",
            payment_mode="tenant_direct",
            payment_provider="epusdt_gmpay",
            amount=Decimal("12.50"),
            currency="USDT",
            created_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            expires_at=datetime(2026, 6, 1, 12, 15, tzinfo=timezone.utc),
            paid_at=datetime(2026, 6, 1, 12, 5, tzinfo=timezone.utc),
            delivered_at=None,
            payment_count=1,
            callback_count=1,
            callback_status_counts={"processed": 1},
            payments=[
                SimpleNamespace(
                    payment_id=88,
                    provider="epusdt_gmpay",
                    status="paid",
                    amount=Decimal("12.50"),
                    currency="USDT",
                    has_payment_url=True,
                    created_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
                    paid_at=datetime(2026, 6, 1, 12, 5, tzinfo=timezone.utc),
                )
            ],
            callbacks=[
                SimpleNamespace(
                    callback_id=77,
                    provider="epusdt_gmpay",
                    process_status="processed",
                    failure_reason="支付回调未处理成功",
                    created_at=datetime(2026, 6, 1, 12, 1, tzinfo=timezone.utc),
                    processed_at=datetime(2026, 6, 1, 12, 2, tzinfo=timezone.utc),
                )
            ],
            delivery=SimpleNamespace(
                delivery_record_id=66,
                delivery_type="card_pool",
                status="sent",
                failure_reason=None,
                has_inventory_item=True,
                has_uploaded_file=False,
                has_telegram_chat=False,
                created_at=datetime(2026, 6, 1, 12, 5, tzinfo=timezone.utc),
                updated_at=datetime(2026, 6, 1, 12, 6, tzinfo=timezone.utc),
                sent_at=datetime(2026, 6, 1, 12, 6, tzinfo=timezone.utc),
            ),
            external_fulfillment=SimpleNamespace(
                expected=True,
                attempt_count=1,
                latest_attempt_status="succeeded",
                latest_attempt_source="manual",
                latest_attempt_at=datetime(2026, 6, 1, 12, 7, tzinfo=timezone.utc),
                latest_failure_stage=None,
                latest_failure_category=None,
                latest_failure_retryable=None,
                latest_upstream_status_code=200,
                latest_item_count=1,
                latest_delivery_record_linked=True,
            ),
            trc20_direct=SimpleNamespace(
                expected=False,
                transfer_count=0,
                latest_match_status=None,
                latest_confirmations=None,
                latest_matched_at=None,
                latest_amount=None,
            ),
        )
        get_summary = AsyncMock(return_value=summary)

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.OrderDiagnosticsService") as diagnostics_service:
                    diagnostics_service.return_value.get_summary = get_summary
                    diagnostics = asyncio.run(
                        service.tenant_order_diagnostics(
                            session,
                            telegram_user_id=123,
                            workspace_id="tn_demo",
                            out_trade_no="ORD123",
                        )
                    )

        get_summary.assert_awaited_once_with(session, tenant_id=7, out_trade_no="ORD123")
        self.assertEqual("ORD123", diagnostics.out_trade_no)
        self.assertEqual("manual", diagnostics.external_fulfillment.latest_attempt_trigger)
        self.assertFalse(hasattr(diagnostics, "order_id"))
        self.assertFalse(hasattr(diagnostics.payments[0], "payment_id"))
        self.assertFalse(hasattr(diagnostics.callbacks[0], "callback_id"))
        self.assertFalse(hasattr(diagnostics.delivery, "delivery_record_id"))

    def test_tenant_order_observability_uses_resolved_workspace_tenant_and_safe_services(self) -> None:
        session = _FakeSession()
        service = AdminWebService()
        callback_failure = SimpleNamespace(
            callback_id=91,
            order_id=81,
            created_at=datetime(2026, 6, 1, 12, 1, tzinfo=timezone.utc),
            processed_at=None,
            out_trade_no="ORD123",
            order_status="paid",
            provider="epusdt_gmpay",
            process_status="failed",
            failure_reason="签名校验失败",
        )
        callback_rejection = SimpleNamespace(
            audit_log_id=71,
            order_id=82,
            created_at=datetime(2026, 6, 1, 12, 2, tzinfo=timezone.utc),
            provider="epay_compatible",
            reason_category="invalid_callback",
            failure_reason="支付回调参数无效",
            http_status=400,
            out_trade_no="ORD123",
            order_status="pending",
            payload_field_count=4,
        )
        fulfillment_attempt = SimpleNamespace(
            attempt_id=61,
            order_id=83,
            product_id=51,
            connection_id=41,
            external_product_id="UP-PROD-1",
            external_order_id="UP-ORDER-1",
            delivery_record_id=31,
            failure_fingerprint="abc",
            created_at=datetime(2026, 6, 1, 12, 3, tzinfo=timezone.utc),
            started_at=datetime(2026, 6, 1, 12, 3, tzinfo=timezone.utc),
            finished_at=datetime(2026, 6, 1, 12, 4, tzinfo=timezone.utc),
            out_trade_no="ORD123",
            provider_name="mcy_shop",
            source_key="fixture",
            attempt_source="auto",
            status="failed",
            imported=False,
            item_count=0,
            failure_reason="上游超时",
            failure_stage="create_order",
            failure_category="upstream_timeout",
            failure_retryable=True,
            upstream_status_code=504,
        )
        list_failures = AsyncMock(return_value=[callback_failure])
        list_rejections = AsyncMock(return_value=[callback_rejection])
        list_attempts = AsyncMock(return_value=[fulfillment_attempt])

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.PaymentCallbackFailureLogService") as failure_service:
                    with patch("app.services.admin_web.PaymentCallbackRejectionAuditService") as rejection_service:
                        with patch("app.services.admin_web.ExternalFulfillmentAttemptLogService") as attempt_service:
                            failure_service.return_value.list_failures = list_failures
                            rejection_service.return_value.list_rejections = list_rejections
                            attempt_service.return_value.list_attempts = list_attempts
                            observability = asyncio.run(
                                service.tenant_order_observability(
                                    session,
                                    telegram_user_id=123,
                                    workspace_id="tn_demo",
                                    limit=8,
                                    out_trade_no="ORD123",
                                )
                            )

        list_failures.assert_awaited_once_with(
            session,
            tenant_id=7,
            process_status="failed",
            out_trade_no="ORD123",
            limit=8,
        )
        list_rejections.assert_awaited_once_with(
            session,
            tenant_id=7,
            out_trade_no="ORD123",
            limit=8,
        )
        list_attempts.assert_awaited_once_with(
            session,
            tenant_id=7,
            out_trade_no="ORD123",
            limit=8,
        )
        self.assertEqual("ORD123", observability.callback_failures[0].out_trade_no)
        self.assertEqual("epay_compatible", observability.callback_rejections[0].provider)
        self.assertEqual("mcy_shop", observability.external_fulfillment_attempts[0].provider_name)
        self.assertFalse(hasattr(observability.callback_failures[0], "callback_id"))
        self.assertFalse(hasattr(observability.callback_failures[0], "order_id"))
        self.assertFalse(hasattr(observability.callback_rejections[0], "audit_log_id"))
        self.assertFalse(hasattr(observability.callback_rejections[0], "order_id"))
        self.assertFalse(hasattr(observability.external_fulfillment_attempts[0], "attempt_id"))
        self.assertFalse(hasattr(observability.external_fulfillment_attempts[0], "order_id"))
        self.assertFalse(hasattr(observability.external_fulfillment_attempts[0], "product_id"))
        self.assertFalse(hasattr(observability.external_fulfillment_attempts[0], "connection_id"))
        self.assertFalse(hasattr(observability.external_fulfillment_attempts[0], "external_product_id"))
        self.assertFalse(hasattr(observability.external_fulfillment_attempts[0], "external_order_id"))
        self.assertFalse(hasattr(observability.external_fulfillment_attempts[0], "delivery_record_id"))
        self.assertFalse(hasattr(observability.external_fulfillment_attempts[0], "failure_fingerprint"))

    def test_tenant_update_payment_config_rejects_non_recent_provider_before_payment_service(self) -> None:
        session = _FakeSession()
        service = AdminWebService()

        with patch.object(service, "_tenant_workspace", new=AsyncMock(return_value=None)):
            with patch.object(
                service,
                "_load_tenant_by_public_id",
                new=AsyncMock(return_value=SimpleNamespace(id=7)),
            ):
                with patch("app.services.admin_web.PaymentConfigService") as payment_service:
                    with self.assertRaises(ValueError):
                        asyncio.run(
                            service.tenant_update_payment_config(
                                session,
                                settings=_settings(),
                                telegram_user_id=123,
                                workspace_id="tn_demo",
                                provider_name="token188",
                                config_payload={"gateway_url": "https://pay.example"},
                            )
                        )

        payment_service.return_value.upsert_tenant_payment_config.assert_not_called()

    def test_write_routes_reject_missing_or_untrusted_origin(self) -> None:
        settings = _settings()
        client = _client(settings)

        missing_origin_response = client.post(
            "/api/v1/admin-web/sessions/telegram",
            json={"init_data": "valid=fake", "entrypoint": "master"},
        )
        untrusted_origin_response = client.post(
            "/api/v1/admin-web/sessions/telegram",
            json={"init_data": "valid=fake", "entrypoint": "master"},
            headers=_origin_headers("https://evil.example"),
        )

        self.assertEqual(403, missing_origin_response.status_code)
        self.assertEqual("缺少管理后台请求来源", missing_origin_response.json()["detail"])
        self.assertEqual(403, untrusted_origin_response.status_code)
        self.assertEqual("管理后台请求来源不允许", untrusted_origin_response.json()["detail"])

    def test_allowed_origin_and_session_ttl_can_be_configured(self) -> None:
        settings = Settings(
            master_bot_token="123:master-token",
            token_encryption_key="test-session-secret",
            public_base_url="https://example.com",
            admin_web_allowed_origins={"https://admin.example"},
            admin_web_session_max_age_seconds=3600,
        )
        session = _FakeSession()
        client = _client(settings)

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.admin_web.validate_telegram_webapp_init_data", return_value=_telegram_user()):
                with patch(
                    "app.web.admin_web.AdminWebService.create_or_update_webapp_user",
                    new=AsyncMock(return_value=SimpleNamespace(is_banned=False)),
                ):
                    with patch(
                        "app.web.admin_web.AdminWebService.session_summary",
                        new=AsyncMock(return_value=_summary()),
                    ):
                        response = client.post(
                            "/api/v1/admin-web/sessions/telegram",
                            json={"init_data": "valid=fake", "entrypoint": "master"},
                            headers=_origin_headers("https://admin.example"),
                        )

        self.assertEqual(200, response.status_code)
        self.assertIn("Max-Age=3600", response.headers.get("set-cookie", ""))

    def test_binding_code_store_hashes_and_consumes_code_once(self) -> None:
        settings = Settings(
            master_bot_token="123:master-token",
            token_encryption_key="test-session-secret",
            admin_web_binding_code_ttl_seconds=120,
        )
        redis = _FakeRedis()

        grant = asyncio.run(
            AdminWebBindingCodeStore(settings, redis).issue_code(
                telegram_user_id=123,
                current_workspace_id="tn_demo",
            )
        )
        self.assertRegex(grant.code, r"^\d{6}$")
        self.assertEqual(120, grant.expires_in_seconds)
        self.assertEqual([120], list(redis.expires.values()))
        self.assertFalse(any(grant.code in key for key in redis.values))
        self.assertFalse(any(grant.code in value for value in redis.values.values()))

        claims = asyncio.run(AdminWebBindingCodeStore(settings, redis).consume_code(grant.code))

        self.assertEqual(123, claims.telegram_user_id)
        self.assertEqual("tn_demo", claims.current_workspace_id)
        with self.assertRaises(AdminWebBindingCodeError):
            asyncio.run(AdminWebBindingCodeStore(settings, redis).consume_code(grant.code))

    def test_binding_code_session_sets_cookie_and_safe_payload(self) -> None:
        settings = _settings()
        redis = _FakeRedis()
        grant = asyncio.run(
            AdminWebBindingCodeStore(settings, redis).issue_code(
                telegram_user_id=123,
                current_workspace_id="tn_demo",
            )
        )
        session = _FakeSession()
        client = _client(settings)
        client.app.state.redis = redis

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web.AdminWebService.session_summary",
                new=AsyncMock(return_value=_summary(current_workspace_id="tn_demo")),
            ) as session_summary:
                response = client.post(
                    "/api/v1/admin-web/sessions/binding-code",
                    json={"code": grant.code},
                    headers=_origin_headers(),
                )

        self.assertEqual(200, response.status_code)
        session_summary.assert_awaited_once()
        self.assertEqual("tn_demo", response.json()["current_workspace_id"])
        self.assertIn(ADMIN_WEB_SESSION_COOKIE_NAME, response.headers.get("set-cookie", ""))
        self.assertNotIn("tenant_id", response.text.lower())
        self.assertNotIn("secret", response.text.lower())

        replay_response = client.post(
            "/api/v1/admin-web/sessions/binding-code",
            json={"code": grant.code},
            headers=_origin_headers(),
        )
        self.assertEqual(401, replay_response.status_code)
        self.assertEqual("绑定码无效或已过期", replay_response.json()["detail"])

    def test_binding_code_session_requires_origin_and_redis(self) -> None:
        settings = _settings()
        client = _client(settings)

        missing_origin_response = client.post(
            "/api/v1/admin-web/sessions/binding-code",
            json={"code": "123456"},
        )
        missing_redis_response = client.post(
            "/api/v1/admin-web/sessions/binding-code",
            json={"code": "123456"},
            headers=_origin_headers(),
        )

        self.assertEqual(403, missing_origin_response.status_code)
        self.assertEqual(503, missing_redis_response.status_code)
        self.assertEqual("绑定码服务暂不可用", missing_redis_response.json()["detail"])

    def test_binding_code_session_rate_limits_failed_attempts(self) -> None:
        settings = Settings(
            master_bot_token="123:master-token",
            token_encryption_key="test-session-secret",
            public_base_url="https://example.com",
            admin_web_binding_code_rate_limit_per_minute=1,
        )
        client = _client(settings)
        client.app.state.redis = _FakeRedis()

        first_response = client.post(
            "/api/v1/admin-web/sessions/binding-code",
            json={"code": "123456"},
            headers=_origin_headers(),
        )
        second_response = client.post(
            "/api/v1/admin-web/sessions/binding-code",
            json={"code": "123456"},
            headers=_origin_headers(),
        )

        self.assertEqual(401, first_response.status_code)
        self.assertEqual(429, second_response.status_code)

    def test_platform_dashboard_requires_platform_admin_session(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web._require_platform_admin_user",
                new=AsyncMock(side_effect=HTTPException(status_code=403, detail="无权访问主 Bot 管理工作区")),
            ):
                response = client.get("/api/v1/admin-web/platform/dashboard")

        self.assertEqual(403, response.status_code)
        self.assertEqual("无权访问主 Bot 管理工作区", response.json()["detail"])

    def test_platform_dashboard_returns_safe_summary_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )
        tenant_payload = {
            "tenant_public_id": "tn_demo",
            "store_name": "Demo Store",
            "tenant_status": "active",
            "bot_username": "demo_bot",
            "bot_status": "active",
            "webhook_status": "healthy",
            "webhook_reset_available": False,
            "owner_telegram_user_id": 123,
            "owner_username": "owner",
            "subscription_status": "active",
            "plan_code": "default",
            "plan_name": "Default",
            "current_period_ends_at": "2026-07-01T00:00:00+00:00",
            "trial_ends_at": None,
            "subscription_ends_at": "2026-07-01T00:00:00+00:00",
            "last_health_checked_at": "2026-06-01T00:00:00+00:00",
            "has_last_error": False,
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        subscription_attention_payload = SimpleNamespace(
            tenant_public_id="tn_demo",
            store_name="Demo Store",
            owner_telegram_user_id=123,
            owner_username="owner",
            tenant_status="active",
            subscription_status="active",
            plan_code="default",
            plan_name="Default",
            attention_reason="expiring_soon",
            trial_ends_at=None,
            current_period_ends_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            subscription_ends_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            grace_ends_at=None,
            suspended_at=None,
            data_retention_until=None,
        )
        stats_payload = AdminWebPlatformStatsResponse(
            tenant_count=1,
            active_tenant_count=1,
            suspended_tenant_count=0,
            trial_subscription_count=0,
            active_subscription_count=1,
            grace_subscription_count=0,
            suspended_subscription_count=0,
            retention_expired_subscription_count=0,
            active_bot_count=1,
            pending_withdrawal_count=0,
            banned_user_count=0,
            disabled_supplier_offer_count=0,
        )
        payment_provider_payload = {
            "provider_name": "epusdt_gmpay",
            "display_name": "epusdt GMPay",
            "integration_kind": "self_hosted_gateway",
            "contract_name": "epusdt_gmpay_v1",
            "production_ready": False,
            "staging_verified": False,
            "tenant_configurable": True,
            "platform_configurable": True,
            "create_payment_available": True,
            "callback_available": True,
            "query_order_available": True,
            "reconcile_available": True,
            "offline_only": False,
            "supported_assets": ["USDT"],
            "supported_networks": ["TRC20"],
            "configured_tenant_count": 1,
            "enabled_tenant_count": 1,
            "missing_config_tenant_count": 0,
            "platform_configured": False,
            "platform_enabled": False,
        }

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web._require_platform_admin_user",
                new=AsyncMock(return_value=SimpleNamespace(id=1, is_platform_admin=True, is_banned=False)),
            ) as require_platform:
                with patch(
                    "app.web.admin_web._list_platform_tenant_bots",
                    new=AsyncMock(return_value=[tenant_payload]),
                ) as list_tenant_bots:
                    with patch(
                        "app.web.admin_web._platform_stats_response",
                        new=AsyncMock(return_value=stats_payload),
                    ):
                        with patch(
                            "app.web.admin_web._list_platform_payment_provider_observations",
                            new=AsyncMock(return_value=[payment_provider_payload]),
                        ) as list_payment_observations, patch(
                            "app.services.payments.configs.PaymentConfigService.get_tenant_payment_config_status",
                            new=AsyncMock(side_effect=AssertionError("不应解密租户支付配置")),
                        ), patch(
                            "app.services.payments.configs.PaymentConfigService.resolve_tenant_payment_config_for_provider",
                            new=AsyncMock(side_effect=AssertionError("不应解析真实支付配置")),
                        ), patch(
                            "app.web.admin_web.LedgerService.list_pending_withdrawals",
                            new=AsyncMock(return_value=[]),
                        ), patch(
                            "app.web.admin_web.SubscriptionService.list_platform_subscription_plans",
                            new=AsyncMock(return_value=[]),
                        ), patch(
                            "app.web.admin_web.SubscriptionService.list_platform_subscription_attention",
                            new=AsyncMock(return_value=[subscription_attention_payload]),
                        ), patch(
                            "app.web.admin_web.RiskControlService.list_banned_platform_users",
                            new=AsyncMock(return_value=[]),
                        ), patch(
                            "app.web.admin_web.AuditLogService.list_platform_risk_audit_logs",
                            new=AsyncMock(return_value=[]),
                        ), patch(
                            "app.web.admin_web.SupplyService.list_platform_supplier_offers",
                            new=AsyncMock(return_value=[]),
                        ):
                            response = client.get("/api/v1/admin-web/platform/dashboard")

        self.assertEqual(200, response.status_code)
        require_platform.assert_awaited_once_with(session, 123)
        payload = response.json()
        self.assertEqual(1, payload["stats"]["tenant_count"])
        self.assertEqual(1, payload["stats"]["active_subscription_count"])
        self.assertEqual(0, payload["stats"]["retention_expired_subscription_count"])
        self.assertEqual("epusdt_gmpay", payload["payment_providers"][0]["provider_name"])
        self.assertEqual(1, payload["payment_providers"][0]["configured_tenant_count"])
        self.assertEqual(0, payload["payment_providers"][0]["missing_config_tenant_count"])
        self.assertEqual("tn_demo", payload["tenants"][0]["tenant_public_id"])
        self.assertEqual("tn_demo", payload["subscription_attention"][0]["tenant_public_id"])
        self.assertEqual("expiring_soon", payload["subscription_attention"][0]["attention_reason"])
        self.assertEqual(123, payload["subscription_attention"][0]["owner_telegram_user_id"])
        list_tenant_bots.assert_awaited_once_with(
            session,
            limit=50,
            offset=0,
            query=None,
            tenant_status="all",
            bot_status="all",
            subscription_status="all",
        )
        list_payment_observations.assert_awaited_once_with(session, settings, tenant_count=1)
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "tenant_bot_id",
            "subscription_id",
            "plan_id",
            "owner_user_id",
            "encrypted_token",
            "token_hash",
            "webhook_secret",
            "api_key",
            "secret_key",
            "config_encrypted",
            "gateway_url",
            "merchant_id",
            "payment_url",
            "storage_key",
            "raw_payload",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_platform_dashboard_passes_tenant_filters_to_safe_listing(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )
        stats_payload = AdminWebPlatformStatsResponse(
            tenant_count=12,
            active_tenant_count=6,
            suspended_tenant_count=1,
            trial_subscription_count=2,
            active_subscription_count=5,
            grace_subscription_count=2,
            suspended_subscription_count=1,
            retention_expired_subscription_count=0,
            active_bot_count=8,
            pending_withdrawal_count=0,
            banned_user_count=0,
            disabled_supplier_offer_count=0,
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web._require_platform_admin_user",
                new=AsyncMock(return_value=SimpleNamespace(id=1, is_platform_admin=True, is_banned=False)),
            ):
                with patch(
                    "app.web.admin_web._list_platform_tenant_bots",
                    new=AsyncMock(return_value=[]),
                ) as list_tenant_bots, patch(
                    "app.web.admin_web._platform_stats_response",
                    new=AsyncMock(return_value=stats_payload),
                ), patch(
                    "app.web.admin_web._list_platform_payment_provider_observations",
                    new=AsyncMock(return_value=[]),
                ), patch(
                    "app.web.admin_web.LedgerService.list_pending_withdrawals",
                    new=AsyncMock(return_value=[]),
                ), patch(
                    "app.web.admin_web.SubscriptionService.list_platform_subscription_plans",
                    new=AsyncMock(return_value=[]),
                ), patch(
                    "app.web.admin_web.SubscriptionService.list_platform_subscription_attention",
                    new=AsyncMock(return_value=[]),
                ), patch(
                    "app.web.admin_web.RiskControlService.list_banned_platform_users",
                    new=AsyncMock(return_value=[]),
                ), patch(
                    "app.web.admin_web.AuditLogService.list_platform_risk_audit_logs",
                    new=AsyncMock(return_value=[]),
                ), patch(
                    "app.web.admin_web.SupplyService.list_platform_supplier_offers",
                    new=AsyncMock(return_value=[]),
                ):
                    response = client.get(
                        "/api/v1/admin-web/platform/dashboard",
                        params={
                            "tenant_limit": 5000,
                            "tenant_offset": 20,
                            "tenant_query": " Demo ",
                            "tenant_status": "active",
                            "bot_status": "disabled",
                            "subscription_status": "grace",
                        },
                    )

        self.assertEqual(200, response.status_code)
        list_tenant_bots.assert_awaited_once_with(
            session,
            limit=100,
            offset=20,
            query=" Demo ",
            tenant_status="active",
            bot_status="disabled",
            subscription_status="grace",
        )
        self.assertEqual([], response.json()["tenants"])

    def test_platform_dashboard_rejects_invalid_tenant_filters_before_listing(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web._list_platform_tenant_bots",
            new=AsyncMock(side_effect=AssertionError("不应查询租户列表")),
        ):
            response = client.get(
                "/api/v1/admin-web/platform/dashboard",
                params={
                    "tenant_status": "deleted",
                    "bot_status": "active",
                    "subscription_status": "all",
                },
            )

        self.assertEqual(422, response.status_code)

    def test_platform_payment_provider_observations_use_aggregate_counts_without_decrypting(self) -> None:
        class AggregateSession(_FakeSession):
            def __init__(self) -> None:
                super().__init__()
                self.query_texts: list[str] = []

            async def execute(self, query: object) -> _RowsResult:
                query_text = str(query)
                self.query_texts.append(query_text)
                if "payment_provider_configs.enabled IS true" in query_text:
                    return _RowsResult([("epusdt_gmpay", 1)])
                return _RowsResult([("epusdt_gmpay", 2), ("epay_compatible", 1), ("unknown_provider", 3)])

        settings = _settings()
        session = AggregateSession()

        with patch(
            "app.services.payments.configs.PaymentConfigService.get_tenant_payment_config_status",
            new=AsyncMock(side_effect=AssertionError("不应解密租户支付配置")),
        ), patch(
            "app.services.payments.configs.PaymentConfigService.resolve_tenant_payment_config_for_provider",
            new=AsyncMock(side_effect=AssertionError("不应解析真实支付配置")),
        ):
            observations = asyncio.run(
                _list_platform_payment_provider_observations(
                    session,
                    settings,
                    tenant_count=3,
                )
            )

        providers = {item.provider_name: item for item in observations}
        self.assertIn("epusdt_gmpay", providers)
        self.assertIn("epay_compatible", providers)
        self.assertEqual(2, providers["epusdt_gmpay"].configured_tenant_count)
        self.assertEqual(1, providers["epusdt_gmpay"].enabled_tenant_count)
        self.assertEqual(1, providers["epusdt_gmpay"].missing_config_tenant_count)
        self.assertEqual(1, providers["epay_compatible"].configured_tenant_count)
        self.assertEqual(0, providers["epay_compatible"].enabled_tenant_count)
        self.assertEqual(2, providers["epay_compatible"].missing_config_tenant_count)
        self.assertTrue(all("config_encrypted" not in query for query in session.query_texts))

    def test_platform_subscription_plan_update_uses_cookie_origin_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )
        plan = PlatformSubscriptionPlanSummary(
            code="pro",
            name="Pro",
            monthly_price=Decimal("29.90000000"),
            currency="USDT",
            trial_days=7,
            grace_days=3,
            enabled=True,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )

        missing_origin_response = client.patch(
            "/api/v1/admin-web/platform/subscription/plans/pro",
            json={"name": "Pro", "monthly_price": "29.9"},
        )
        self.assertEqual(403, missing_origin_response.status_code)

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web._require_platform_admin_user",
                new=AsyncMock(return_value=SimpleNamespace(id=1, is_platform_admin=True, is_banned=False)),
            ) as require_platform:
                with patch(
                    "app.web.admin_web.SubscriptionService.update_platform_subscription_plan",
                    new=AsyncMock(return_value=plan),
                ) as update_plan:
                    response = client.patch(
                        "/api/v1/admin-web/platform/subscription/plans/pro",
                        json={
                            "name": "Pro",
                            "monthly_price": "29.9",
                            "currency": "USDT",
                            "trial_days": 7,
                            "grace_days": 3,
                            "reason": "Admin Web 编辑套餐",
                        },
                        headers=_origin_headers(),
                    )

        self.assertEqual(200, response.status_code)
        require_platform.assert_awaited_once_with(session, 123)
        update_plan.assert_awaited_once_with(
            session,
            code="pro",
            name="Pro",
            monthly_price=Decimal("29.9"),
            currency="USDT",
            trial_days=7,
            grace_days=3,
            reason="Admin Web 编辑套餐",
        )
        self.assertEqual(1, session.commit_count)
        payload = response.json()
        self.assertEqual("pro", payload["code"])
        self.assertEqual("Pro", payload["name"])
        self.assertEqual("29.90000000", payload["monthly_price"])
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "plan_id",
            "subscription_id",
            "invoice_id",
            "order_id",
            "payment_url",
            "provider_trade_no",
            "raw_payload",
            "api_key",
            "token",
            "secret",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_platform_subscription_plan_update_rejects_extra_fields_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.SubscriptionService.update_platform_subscription_plan",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.patch(
                "/api/v1/admin-web/platform/subscription/plans/pro",
                json={
                    "name": "Pro",
                    "monthly_price": "29.9",
                    "plan_id": 1,
                    "tenant_id": 7,
                    "subscription_id": 9,
                    "api_key": "plain-secret",
                    "raw_payload": {"token": "plain-token"},
                },
                headers=_origin_headers(),
            )

        self.assertEqual(422, response.status_code)

    def test_platform_subscription_plan_create_uses_cookie_origin_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )
        plan = PlatformSubscriptionPlanSummary(
            code="starter",
            name="Starter",
            monthly_price=Decimal("9.90000000"),
            currency="USDT",
            trial_days=3,
            grace_days=1,
            enabled=True,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )

        missing_origin_response = client.post(
            "/api/v1/admin-web/platform/subscription/plans",
            json={"code": "starter", "name": "Starter", "monthly_price": "9.9"},
        )
        self.assertEqual(403, missing_origin_response.status_code)

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web._require_platform_admin_user",
                new=AsyncMock(return_value=SimpleNamespace(id=1, is_platform_admin=True, is_banned=False)),
            ) as require_platform:
                with patch(
                    "app.web.admin_web.SubscriptionService.create_platform_subscription_plan",
                    new=AsyncMock(return_value=plan),
                ) as create_plan:
                    response = client.post(
                        "/api/v1/admin-web/platform/subscription/plans",
                        json={
                            "code": "starter",
                            "name": "Starter",
                            "monthly_price": "9.9",
                            "currency": "USDT",
                            "trial_days": 3,
                            "grace_days": 1,
                            "enabled": True,
                            "reason": "Admin Web 创建套餐",
                        },
                        headers=_origin_headers(),
                    )

        self.assertEqual(200, response.status_code)
        require_platform.assert_awaited_once_with(session, 123)
        create_plan.assert_awaited_once_with(
            session,
            code="starter",
            name="Starter",
            monthly_price=Decimal("9.9"),
            currency="USDT",
            trial_days=3,
            grace_days=1,
            enabled=True,
            reason="Admin Web 创建套餐",
        )
        self.assertEqual(1, session.commit_count)
        payload = response.json()
        self.assertEqual("starter", payload["code"])
        self.assertEqual("Starter", payload["name"])
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "plan_id",
            "subscription_id",
            "invoice_id",
            "order_id",
            "payment_url",
            "provider_trade_no",
            "raw_payload",
            "api_key",
            "token",
            "secret",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_platform_subscription_plan_status_uses_cookie_origin_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )
        plan = PlatformSubscriptionPlanSummary(
            code="starter",
            name="Starter",
            monthly_price=Decimal("9.90000000"),
            currency="USDT",
            trial_days=3,
            grace_days=1,
            enabled=False,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )

        missing_origin_response = client.patch(
            "/api/v1/admin-web/platform/subscription/plans/starter/status",
            json={"enabled": False, "reason": "Admin Web 停用套餐"},
        )
        self.assertEqual(403, missing_origin_response.status_code)

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web._require_platform_admin_user",
                new=AsyncMock(return_value=SimpleNamespace(id=1, is_platform_admin=True, is_banned=False)),
            ) as require_platform:
                with patch(
                    "app.web.admin_web.SubscriptionService.set_platform_subscription_plan_enabled",
                    new=AsyncMock(return_value=plan),
                ) as set_enabled:
                    response = client.patch(
                        "/api/v1/admin-web/platform/subscription/plans/starter/status",
                        json={"enabled": False, "reason": "Admin Web 停用套餐"},
                        headers=_origin_headers(),
                    )

        self.assertEqual(200, response.status_code)
        require_platform.assert_awaited_once_with(session, 123)
        set_enabled.assert_awaited_once_with(
            session,
            code="starter",
            enabled=False,
            reason="Admin Web 停用套餐",
        )
        self.assertEqual(1, session.commit_count)
        payload = response.json()
        self.assertEqual("starter", payload["code"])
        self.assertFalse(payload["enabled"])
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "plan_id",
            "subscription_id",
            "invoice_id",
            "order_id",
            "payment_url",
            "provider_trade_no",
            "raw_payload",
            "api_key",
            "token",
            "secret",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_platform_subscription_plan_create_and_status_reject_extra_fields_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.SubscriptionService.create_platform_subscription_plan",
            new=AsyncMock(side_effect=AssertionError("不应进入创建服务层")),
        ):
            create_response = client.post(
                "/api/v1/admin-web/platform/subscription/plans",
                json={
                    "code": "starter",
                    "name": "Starter",
                    "monthly_price": "9.9",
                    "plan_id": 1,
                    "tenant_id": 7,
                    "subscription_id": 9,
                    "raw_payload": {"token": "plain-token"},
                },
                headers=_origin_headers(),
            )

        with patch(
            "app.web.admin_web.SubscriptionService.set_platform_subscription_plan_enabled",
            new=AsyncMock(side_effect=AssertionError("不应进入启停服务层")),
        ):
            status_response = client.patch(
                "/api/v1/admin-web/platform/subscription/plans/starter/status",
                json={
                    "enabled": False,
                    "plan_id": 1,
                    "tenant_id": 7,
                    "invoice_id": 9,
                    "raw_payload": {"token": "plain-token"},
                },
                headers=_origin_headers(),
            )

        self.assertEqual(422, create_response.status_code)
        self.assertEqual(422, status_response.status_code)

    def test_platform_bot_webhook_reset_calls_telegram_after_origin_and_returns_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        redis = _FakeRedis()
        client = _client(settings)
        client.app.state.redis = redis
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )
        tenant_bot = SimpleNamespace(
            tenant_id=7,
            bot_username="demo_bot",
            status="active",
            webhook_secret="old-secret",
            encrypted_token="encrypted-token",
            last_error="previous error",
            last_health_checked_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        fake_bot = SimpleNamespace(
            set_webhook=AsyncMock(return_value=True),
            session=SimpleNamespace(close=AsyncMock(return_value=None)),
        )

        missing_origin_response = client.post(
            "/api/v1/admin-web/platform/bots/tn_demo/webhook/reset",
            json={"reason": "manual reset"},
        )
        self.assertEqual(403, missing_origin_response.status_code)

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web._require_platform_admin_user",
                new=AsyncMock(return_value=SimpleNamespace(id=1, is_platform_admin=True, is_banned=False)),
            ):
                with patch(
                    "app.web.admin_web._get_latest_tenant_bot_by_public_id",
                    new=AsyncMock(return_value=tenant_bot),
                ) as get_tenant_bot:
                    with patch("app.web.admin_web.generate_webhook_secret", return_value="new-secret"):
                        with patch(
                            "app.web.admin_web.TokenCrypto",
                            return_value=SimpleNamespace(decrypt_token=lambda encrypted: "12345678:fake-token"),
                        ):
                            with patch("app.web.admin_web.create_bot", return_value=fake_bot):
                                response = client.post(
                                    "/api/v1/admin-web/platform/bots/tn_demo/webhook/reset",
                                    json={"reason": "manual reset"},
                                    headers=_origin_headers(),
                                )

        self.assertEqual(200, response.status_code)
        get_tenant_bot.assert_awaited_once_with(session, "tn_demo", for_update=True)
        fake_bot.set_webhook.assert_awaited_once_with(
            "https://example.com/telegram/webhook/new-secret",
            allowed_updates=["message", "callback_query"],
            drop_pending_updates=True,
        )
        fake_bot.session.close.assert_awaited_once()
        self.assertEqual("new-secret", tenant_bot.webhook_secret)
        self.assertIsNone(tenant_bot.last_error)
        self.assertEqual(1, session.flush_count)
        self.assertEqual(1, session.commit_count)
        self.assertIn("tenant_webhook:old-secret", redis.deleted_keys)
        self.assertIn("tenant_webhook:new-secret", redis.deleted_keys)
        self.assertTrue(session.added)
        audit = session.added[0]
        self.assertEqual("admin_web.platform_bot_webhook_reset", audit.action)
        self.assertTrue(audit.metadata_json["telegram_webhook_called"])
        payload = response.json()
        self.assertEqual("tn_demo", payload["tenant_public_id"])
        self.assertEqual("demo_bot", payload["bot_username"])
        self.assertTrue(payload["telegram_webhook_called"])
        response_text = response.text.lower()
        for forbidden in ("encrypted_token", "webhook_secret", "old-secret", "new-secret", "fake-token", "token", "secret"):
            self.assertNotIn(forbidden, response_text)

    def test_platform_bot_webhook_reset_telegram_failure_does_not_commit_or_rotate_secret(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )
        tenant_bot = SimpleNamespace(
            tenant_id=7,
            bot_username="demo_bot",
            status="active",
            webhook_secret="old-secret",
            encrypted_token="encrypted-token",
            last_error=None,
            last_health_checked_at=None,
        )
        fake_bot = SimpleNamespace(
            set_webhook=AsyncMock(side_effect=RuntimeError("token plain-secret failed")),
            session=SimpleNamespace(close=AsyncMock(return_value=None)),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web._require_platform_admin_user",
                new=AsyncMock(return_value=SimpleNamespace(id=1, is_platform_admin=True, is_banned=False)),
            ):
                with patch(
                    "app.web.admin_web._get_latest_tenant_bot_by_public_id",
                    new=AsyncMock(return_value=tenant_bot),
                ):
                    with patch("app.web.admin_web.generate_webhook_secret", return_value="new-secret"):
                        with patch(
                            "app.web.admin_web.TokenCrypto",
                            return_value=SimpleNamespace(decrypt_token=lambda encrypted: "12345678:fake-token"),
                        ):
                            with patch("app.web.admin_web.create_bot", return_value=fake_bot):
                                response = client.post(
                                    "/api/v1/admin-web/platform/bots/tn_demo/webhook/reset",
                                    json={"reason": "manual reset"},
                                    headers=_origin_headers(),
                                )

        self.assertEqual(502, response.status_code)
        self.assertEqual("Telegram Webhook 重置失败", response.json()["detail"])
        self.assertEqual("old-secret", tenant_bot.webhook_secret)
        self.assertEqual(0, session.commit_count)
        self.assertEqual(0, session.flush_count)
        fake_bot.session.close.assert_awaited_once()
        response_text = response.text.lower()
        self.assertNotIn("plain-secret", response_text)
        self.assertNotIn("fake-token", response_text)

    def test_platform_user_ban_requires_origin_and_returns_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        missing_origin_response = client.patch(
            "/api/v1/admin-web/platform/risk/users/456/ban-status",
            json={"status": "banned", "reason": "manual risk"},
        )
        self.assertEqual(403, missing_origin_response.status_code)

        status_summary = SimpleNamespace(
            telegram_user_id=456,
            username="buyer",
            is_banned=True,
            ban_source="manual",
            latest_action="platform_risk.user_banned",
            latest_action_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            reason="manual risk",
            trigger_rule=None,
            blocked_count=None,
            threshold=None,
            window_seconds=None,
            created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web._require_platform_admin_user",
                new=AsyncMock(return_value=SimpleNamespace(id=1, is_platform_admin=True, is_banned=False)),
            ):
                with patch(
                    "app.web.admin_web.RiskControlService.ban_platform_user",
                    new=AsyncMock(return_value=SimpleNamespace()),
                ) as ban_user:
                    with patch(
                        "app.web.admin_web.RiskControlService.get_platform_user_ban_status",
                        new=AsyncMock(return_value=status_summary),
                    ):
                        response = client.patch(
                            "/api/v1/admin-web/platform/risk/users/456/ban-status",
                            json={"status": "banned", "reason": "manual risk"},
                            headers=_origin_headers(),
                        )

        self.assertEqual(200, response.status_code)
        ban_user.assert_awaited_once()
        self.assertEqual(1, session.commit_count)
        payload = response.json()
        self.assertEqual(456, payload["telegram_user_id"])
        self.assertTrue(payload["is_banned"])
        response_text = response.text.lower()
        for forbidden in ("tenant_id", "owner_user_id", "token", "secret", "raw_payload"):
            self.assertNotIn(forbidden, response_text)

    def test_platform_user_unban_uses_origin_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )
        status_summary = SimpleNamespace(
            telegram_user_id=456,
            username="buyer",
            is_banned=False,
            ban_source=None,
            latest_action="platform_risk.user_unbanned",
            latest_action_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
            reason="manual restore",
            trigger_rule=None,
            blocked_count=None,
            threshold=None,
            window_seconds=None,
            created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web._require_platform_admin_user",
                new=AsyncMock(return_value=SimpleNamespace(id=1, is_platform_admin=True, is_banned=False)),
            ) as require_platform:
                with patch(
                    "app.web.admin_web.RiskControlService.unban_platform_user",
                    new=AsyncMock(return_value=SimpleNamespace()),
                ) as unban_user:
                    with patch(
                        "app.web.admin_web.RiskControlService.get_platform_user_ban_status",
                        new=AsyncMock(return_value=status_summary),
                    ):
                        response = client.patch(
                            "/api/v1/admin-web/platform/risk/users/456/ban-status",
                            json={"status": "active", "reason": "manual restore"},
                            headers=_origin_headers(),
                        )

        self.assertEqual(200, response.status_code)
        require_platform.assert_awaited_once_with(session, 123)
        unban_user.assert_awaited_once_with(
            session,
            telegram_user_id=456,
            actor_user_id=1,
            reason="manual restore",
        )
        self.assertEqual(1, session.commit_count)
        payload = response.json()
        self.assertEqual(456, payload["telegram_user_id"])
        self.assertFalse(payload["is_banned"])
        self.assertEqual("platform_risk.user_unbanned", payload["latest_action"])
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "platform_user_id",
            "actor_user_id",
            "audit_log_id",
            "metadata_json",
            "owner_user_id",
            "token",
            "secret",
            "raw_payload",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_platform_user_ban_rejects_extra_fields_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.RiskControlService.ban_platform_user",
            new=AsyncMock(side_effect=AssertionError("不应进入封禁服务")),
        ):
            with patch(
                "app.web.admin_web.RiskControlService.unban_platform_user",
                new=AsyncMock(side_effect=AssertionError("不应进入解封服务")),
            ):
                response = client.patch(
                    "/api/v1/admin-web/platform/risk/users/456/ban-status",
                    json={
                        "status": "banned",
                        "reason": "manual risk",
                        "tenant_id": 7,
                        "platform_user_id": 456,
                        "actor_user_id": 1,
                        "audit_log_id": 99,
                        "metadata_json": {"token": "plain-token"},
                        "raw_payload": {"secret": "plain-secret"},
                    },
                    headers=_origin_headers(),
                )

        self.assertEqual(422, response.status_code)
        response_text = response.text.lower()
        self.assertNotIn("plain-token", response_text)
        self.assertNotIn("plain-secret", response_text)

    def test_platform_bot_status_update_uses_origin_and_clears_local_cache_only(self) -> None:
        settings = _settings()
        session = _FakeSession()
        redis = _FakeRedis()
        client = _client(settings)
        client.app.state.redis = redis
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )
        tenant_bot = SimpleNamespace(
            tenant_id=7,
            bot_username="demo_bot",
            status="active",
            webhook_secret="secret-1",
        )

        missing_origin_response = client.patch(
            "/api/v1/admin-web/platform/bots/tn_demo/status",
            json={"status": "disabled", "reason": "manual stop"},
        )
        self.assertEqual(403, missing_origin_response.status_code)

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web._require_platform_admin_user",
                new=AsyncMock(return_value=SimpleNamespace(id=1, is_platform_admin=True, is_banned=False)),
            ) as require_platform:
                with patch(
                    "app.web.admin_web._get_latest_tenant_bot_by_public_id",
                    new=AsyncMock(return_value=tenant_bot),
                ) as get_bot:
                    with patch("app.web.admin_web.create_bot") as create_bot:
                        response = client.patch(
                            "/api/v1/admin-web/platform/bots/tn_demo/status",
                            json={"status": "disabled", "reason": "manual stop"},
                            headers=_origin_headers(),
                        )

        self.assertEqual(200, response.status_code)
        require_platform.assert_awaited_once_with(session, 123)
        get_bot.assert_awaited_once_with(session, "tn_demo", for_update=True)
        create_bot.assert_not_called()
        self.assertEqual("disabled", tenant_bot.status)
        self.assertEqual(1, session.flush_count)
        self.assertEqual(1, session.commit_count)
        self.assertEqual(["tenant_webhook:secret-1"], redis.deleted_keys)
        payload = response.json()
        self.assertEqual("tn_demo", payload["tenant_public_id"])
        self.assertEqual("demo_bot", payload["bot_username"])
        self.assertEqual("active", payload["previous_status"])
        self.assertEqual("disabled", payload["status"])
        self.assertFalse(payload["webhook_reset_available"])
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "tenant_bot_id",
            "encrypted_token",
            "token_hash",
            "webhook_secret",
            "api_key",
            "token",
            "secret-1",
            "raw_payload",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_platform_bot_status_update_rejects_extra_fields_before_lookup(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web._get_latest_tenant_bot_by_public_id",
            new=AsyncMock(side_effect=AssertionError("不应查询 Bot")),
        ):
            response = client.patch(
                "/api/v1/admin-web/platform/bots/tn_demo/status",
                json={
                    "status": "disabled",
                    "tenant_id": 7,
                    "tenant_bot_id": 8,
                    "webhook_secret": "plain-secret",
                    "encrypted_token": "cipher",
                    "raw_payload": {"token": "plain-token"},
                },
                headers=_origin_headers(),
            )

        self.assertEqual(422, response.status_code)

    def test_platform_supplier_offer_status_update_uses_origin_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )
        offer = SimpleNamespace(
            supplier_offer_id=77,
            supplier_store_name="供货店铺",
            product_name="供货商品",
            delivery_type="card_pool",
            suggested_price=Decimal("12.50000000"),
            min_sale_price=Decimal("10.00000000"),
            supplier_cost=Decimal("8.00000000"),
            currency="USDT",
            available_count=9,
            requires_approval=False,
            status="disabled",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )

        missing_origin_response = client.patch(
            "/api/v1/admin-web/platform/supply/supplier-offers/77/status",
            json={"status": "disabled", "reason": "risk review"},
        )
        self.assertEqual(403, missing_origin_response.status_code)

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web._require_platform_admin_user",
                new=AsyncMock(return_value=SimpleNamespace(id=1, is_platform_admin=True, is_banned=False)),
            ) as require_platform:
                with patch(
                    "app.web.admin_web.SupplyService.set_platform_supplier_offer_status",
                    new=AsyncMock(return_value=offer),
                ) as set_status:
                    response = client.patch(
                        "/api/v1/admin-web/platform/supply/supplier-offers/77/status",
                        json={"status": "disabled", "reason": "risk review"},
                        headers=_origin_headers(),
                    )

        self.assertEqual(200, response.status_code)
        require_platform.assert_awaited_once_with(session, 123)
        set_status.assert_awaited_once_with(
            session,
            supplier_offer_id=77,
            status="disabled",
            reason="risk review",
        )
        self.assertEqual(1, session.commit_count)
        payload = response.json()
        self.assertEqual(77, payload["supplier_offer_id"])
        self.assertEqual("disabled", payload["status"])
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "supplier_tenant_id",
            "product_id",
            "variant_id",
            "inventory_item_id",
            "storage_key",
            "api_key",
            "token",
            "secret",
            "raw_payload",
            "delivery_content",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_platform_supplier_offer_status_update_rejects_extra_fields_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.SupplyService.set_platform_supplier_offer_status",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.patch(
                "/api/v1/admin-web/platform/supply/supplier-offers/77/status",
                json={
                    "status": "disabled",
                    "reason": "risk review",
                    "tenant_id": 7,
                    "supplier_tenant_id": 8,
                    "product_id": 9,
                    "storage_key": "plain-storage-key",
                    "raw_payload": {"token": "plain-token"},
                },
                headers=_origin_headers(),
            )

        self.assertEqual(422, response.status_code)

    def test_platform_tenant_suspension_update_uses_origin_and_clears_webhook_cache(self) -> None:
        settings = _settings()
        session = _FakeSession()
        redis = _FakeRedis()
        client = _client(settings)
        client.app.state.redis = redis
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )
        tenant = SimpleNamespace(id=7, public_id="tn_demo")
        result = SimpleNamespace(
            previous_status="active",
            new_status="suspended",
            reason="risk review",
            webhook_secrets=("secret-a", "secret-b"),
        )

        missing_origin_response = client.patch(
            "/api/v1/admin-web/platform/risk/tenants/tn_demo/suspension-status",
            json={"status": "suspended", "reason": "risk review"},
        )
        self.assertEqual(403, missing_origin_response.status_code)

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web._require_platform_admin_user",
                new=AsyncMock(return_value=SimpleNamespace(id=1, is_platform_admin=True, is_banned=False)),
            ) as require_platform:
                with patch(
                    "app.web.admin_web._get_tenant_by_public_id",
                    new=AsyncMock(return_value=tenant),
                ) as get_tenant:
                    with patch(
                        "app.web.admin_web.RiskControlService.suspend_tenant",
                        new=AsyncMock(return_value=result),
                    ) as suspend_tenant:
                        response = client.patch(
                            "/api/v1/admin-web/platform/risk/tenants/tn_demo/suspension-status",
                            json={"status": "suspended", "reason": "risk review"},
                            headers=_origin_headers(),
                        )

        self.assertEqual(200, response.status_code)
        require_platform.assert_awaited_once_with(session, 123)
        get_tenant.assert_awaited_once_with(session, "tn_demo")
        suspend_tenant.assert_awaited_once_with(
            session,
            tenant_id=7,
            actor_user_id=1,
            reason="risk review",
        )
        self.assertEqual(1, session.commit_count)
        self.assertEqual(["tenant_webhook:secret-a", "tenant_webhook:secret-b"], redis.deleted_keys)
        payload = response.json()
        self.assertEqual("tn_demo", payload["tenant_public_id"])
        self.assertEqual("active", payload["previous_status"])
        self.assertEqual("suspended", payload["status"])
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "tenant_bot_id",
            "actor_user_id",
            "webhook_secret",
            "secret-a",
            "secret-b",
            "token",
            "raw_payload",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_platform_tenant_suspension_update_rejects_extra_fields_before_lookup(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web._get_tenant_by_public_id",
            new=AsyncMock(side_effect=AssertionError("不应查询租户")),
        ):
            response = client.patch(
                "/api/v1/admin-web/platform/risk/tenants/tn_demo/suspension-status",
                json={
                    "status": "suspended",
                    "reason": "risk review",
                    "tenant_id": 7,
                    "actor_user_id": 1,
                    "webhook_secret": "plain-secret",
                    "raw_payload": {"token": "plain-token"},
                },
                headers=_origin_headers(),
            )

        self.assertEqual(422, response.status_code)

    def test_platform_tenant_subscription_grant_days_uses_public_tenant_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )
        tenant = SimpleNamespace(id=7, public_id="tn_demo")
        result = SubscriptionAdjustmentResult(
            tenant_id=7,
            status="active",
            previous_period_ends_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            new_period_ends_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            action="subscription.admin_days_granted",
        )

        missing_origin_response = client.post(
            "/api/v1/admin-web/platform/tenants/tn_demo/subscription/grant-days",
            json={"days": 30, "reason": "manual comp"},
        )
        self.assertEqual(403, missing_origin_response.status_code)

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web._require_platform_admin_user",
                new=AsyncMock(return_value=SimpleNamespace(id=1, is_platform_admin=True, is_banned=False)),
            ) as require_platform:
                with patch(
                    "app.web.admin_web._get_tenant_by_public_id",
                    new=AsyncMock(return_value=tenant),
                ) as get_tenant:
                    with patch(
                        "app.web.admin_web.SubscriptionService.grant_days",
                        new=AsyncMock(return_value=result),
                    ) as grant_days:
                        response = client.post(
                            "/api/v1/admin-web/platform/tenants/tn_demo/subscription/grant-days",
                            json={"days": 30, "reason": "manual comp"},
                            headers=_origin_headers(),
                        )

        self.assertEqual(200, response.status_code)
        require_platform.assert_awaited_once_with(session, 123)
        get_tenant.assert_awaited_once_with(session, "tn_demo")
        grant_days.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            actor_user_id=1,
            days=30,
            monthly_price=settings.subscription_monthly_price,
            reason="manual comp",
        )
        self.assertEqual(1, session.commit_count)
        payload = response.json()
        self.assertEqual("tn_demo", payload["tenant_public_id"])
        self.assertEqual("active", payload["status"])
        self.assertEqual("subscription.admin_days_granted", payload["action"])
        self.assertEqual("2026-06-01T00:00:00+00:00", payload["previous_period_ends_at"])
        self.assertEqual("2026-07-01T00:00:00+00:00", payload["new_period_ends_at"])
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "subscription_id",
            "plan_id",
            "invoice_id",
            "order_id",
            "payment_url",
            "actor_user_id",
            "raw_payload",
            "api_key",
            "token",
            "secret",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_platform_tenant_subscription_set_period_end_uses_public_tenant_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )
        tenant = SimpleNamespace(id=7, public_id="tn_demo")
        result = SubscriptionAdjustmentResult(
            tenant_id=7,
            status="active",
            previous_period_ends_at=None,
            new_period_ends_at=datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc),
            action="subscription.admin_expiry_set",
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web._require_platform_admin_user",
                new=AsyncMock(return_value=SimpleNamespace(id=1, is_platform_admin=True, is_banned=False)),
            ) as require_platform:
                with patch(
                    "app.web.admin_web._get_tenant_by_public_id",
                    new=AsyncMock(return_value=tenant),
                ) as get_tenant:
                    with patch(
                        "app.web.admin_web.SubscriptionService.set_period_end",
                        new=AsyncMock(return_value=result),
                    ) as set_period_end:
                        response = client.patch(
                            "/api/v1/admin-web/platform/tenants/tn_demo/subscription/period-end",
                            json={"period_ends_at": "2026-08-31T23:59:59+00:00", "reason": "manual set"},
                            headers=_origin_headers(),
                        )

        self.assertEqual(200, response.status_code)
        require_platform.assert_awaited_once_with(session, 123)
        get_tenant.assert_awaited_once_with(session, "tn_demo")
        set_period_end.assert_awaited_once()
        _, kwargs = set_period_end.await_args
        self.assertIs(session, kwargs["session"])
        self.assertEqual(7, kwargs["tenant_id"])
        self.assertEqual(1, kwargs["actor_user_id"])
        self.assertEqual(datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc), kwargs["period_ends_at"])
        self.assertEqual(settings.subscription_monthly_price, kwargs["monthly_price"])
        self.assertEqual("manual set", kwargs["reason"])
        self.assertEqual(1, session.commit_count)
        payload = response.json()
        self.assertEqual("tn_demo", payload["tenant_public_id"])
        self.assertIsNone(payload["previous_period_ends_at"])
        self.assertEqual("2026-08-31T23:59:59+00:00", payload["new_period_ends_at"])
        self.assertNotIn("tenant_id", response.text)

    def test_platform_tenant_subscription_adjustment_rejects_extra_fields_before_lookup(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web._get_tenant_by_public_id",
            new=AsyncMock(side_effect=AssertionError("不应查询租户")),
        ):
            grant_response = client.post(
                "/api/v1/admin-web/platform/tenants/tn_demo/subscription/grant-days",
                json={
                    "days": 30,
                    "tenant_id": 7,
                    "subscription_id": 8,
                    "order_id": 9,
                    "payment_url": "https://pay.example/secret",
                    "raw_payload": {"token": "plain-token"},
                },
                headers=_origin_headers(),
            )
            period_response = client.patch(
                "/api/v1/admin-web/platform/tenants/tn_demo/subscription/period-end",
                json={
                    "period_ends_at": "2026-08-31T23:59:59+00:00",
                    "plan_id": 1,
                    "invoice_id": 2,
                    "api_key": "plain-key",
                    "raw_payload": {"secret": "plain-secret"},
                },
                headers=_origin_headers(),
            )

        self.assertEqual(422, grant_response.status_code)
        self.assertEqual(422, period_response.status_code)
        combined = f"{grant_response.text.lower()} {period_response.text.lower()}"
        self.assertNotIn("plain-token", combined)
        self.assertNotIn("plain-secret", combined)
        self.assertNotIn("plain-key", combined)
        self.assertNotIn("pay.example", combined)

    def test_platform_withdrawal_detail_uses_cookie_session_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )
        withdrawal = SimpleNamespace(
            withdrawal_id=55,
            tenant_id=7,
            amount=Decimal("30.00000000"),
            currency="USDT",
            network="TRC20",
            address="T1234567890abcdef",
            status="pending",
            requested_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            reviewed_at=None,
            completed_at=None,
            payout_reference="tx-secret-ref",
            payout_proof_url="https://proof.example/secret",
        )

        async def get_model(model: object, item_id: int) -> SimpleNamespace | None:
            return SimpleNamespace(public_id="tn_demo", store_name="演示店铺") if item_id == 7 else None

        session.get = get_model  # type: ignore[attr-defined]

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web._require_platform_admin_user",
                new=AsyncMock(return_value=SimpleNamespace(id=1, is_platform_admin=True, is_banned=False)),
            ) as require_platform:
                with patch(
                    "app.web.admin_web.LedgerService.get_platform_withdrawal",
                    new=AsyncMock(return_value=withdrawal),
                ) as get_withdrawal:
                    response = client.get("/api/v1/admin-web/platform/finance/withdrawals/55")

        self.assertEqual(200, response.status_code)
        require_platform.assert_awaited_once_with(session, 123)
        get_withdrawal.assert_awaited_once_with(session, withdrawal_id=55)
        self.assertEqual(0, session.commit_count)
        payload = response.json()
        self.assertEqual(55, payload["withdrawal_id"])
        self.assertEqual("tn_demo", payload["tenant_public_id"])
        self.assertEqual("演示店铺", payload["store_name"])
        self.assertEqual("pending", payload["status"])
        self.assertEqual("T12345***abcdef", payload["address_masked"])
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "account_id",
            "ledger_entry_id",
            "address_encrypted",
            "t1234567890abcdef",
            "tx-secret-ref",
            "proof.example",
            "admin_note",
            "actor_user_id",
            "raw_payload",
            "api_key",
            "token",
            "secret",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_platform_withdrawal_detail_returns_404_without_commit(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web._require_platform_admin_user",
                new=AsyncMock(return_value=SimpleNamespace(id=1, is_platform_admin=True, is_banned=False)),
            ):
                with patch(
                    "app.web.admin_web.LedgerService.get_platform_withdrawal",
                    new=AsyncMock(return_value=None),
                ):
                    response = client.get("/api/v1/admin-web/platform/finance/withdrawals/999")

        self.assertEqual(404, response.status_code)
        self.assertEqual("提现申请不存在", response.json()["detail"])
        self.assertEqual(0, session.commit_count)
        self.assertNotIn("secret", response.text.lower())

    def test_platform_withdrawal_complete_uses_origin_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )
        withdrawal = SimpleNamespace(
            id=55,
            tenant_id=7,
            amount=Decimal("30.00000000"),
            currency="USDT",
            network="TRC20",
            address="T1234567890abcdef",
            status="completed",
            requested_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            reviewed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            completed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            payout_reference="tx-secret-ref",
            payout_proof_url="https://proof.example/secret",
        )

        async def get_model(model: object, item_id: int) -> SimpleNamespace | None:
            return SimpleNamespace(public_id="tn_demo", store_name="演示店铺") if item_id == 7 else None

        session.get = get_model  # type: ignore[attr-defined]

        missing_origin_response = client.post(
            "/api/v1/admin-web/platform/finance/withdrawals/55/complete",
            json={"admin_note": "paid offline", "payout_reference": "tx-secret-ref"},
        )
        self.assertEqual(403, missing_origin_response.status_code)

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web._require_platform_admin_user",
                new=AsyncMock(return_value=SimpleNamespace(id=1, is_platform_admin=True, is_banned=False)),
            ) as require_platform:
                with patch(
                    "app.web.admin_web.LedgerService.complete_withdrawal",
                    new=AsyncMock(return_value=withdrawal),
                ) as complete_withdrawal:
                    response = client.post(
                        "/api/v1/admin-web/platform/finance/withdrawals/55/complete",
                        json={
                            "admin_note": "paid offline",
                            "payout_reference": "tx-secret-ref",
                            "payout_proof_url": "https://proof.example/secret",
                        },
                        headers=_origin_headers(),
                    )

        self.assertEqual(200, response.status_code)
        require_platform.assert_awaited_once_with(session, 123)
        complete_withdrawal.assert_awaited_once_with(
            session,
            55,
            "paid offline",
            actor_user_id=1,
            payout_reference="tx-secret-ref",
            payout_proof_url="https://proof.example/secret",
        )
        self.assertEqual(1, session.commit_count)
        payload = response.json()
        self.assertEqual(55, payload["withdrawal_id"])
        self.assertEqual("tn_demo", payload["tenant_public_id"])
        self.assertEqual("completed", payload["status"])
        self.assertEqual("T12345***abcdef", payload["address_masked"])
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "account_id",
            "ledger_entry_id",
            "address_encrypted",
            "t1234567890abcdef",
            "tx-secret-ref",
            "proof.example",
            "admin_note",
            "actor_user_id",
            "raw_payload",
            "api_key",
            "token",
            "secret",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_platform_withdrawal_reject_uses_origin_and_safe_payload(self) -> None:
        settings = _settings()
        session = _FakeSession()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )
        withdrawal = SimpleNamespace(
            id=56,
            tenant_id=7,
            amount=Decimal("12.00000000"),
            currency="USDT",
            network="TRC20",
            address="Tabcdef1234567890",
            status="rejected",
            requested_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            reviewed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            completed_at=None,
        )

        async def get_model(model: object, item_id: int) -> SimpleNamespace | None:
            return SimpleNamespace(public_id="tn_demo", store_name="演示店铺") if item_id == 7 else None

        session.get = get_model  # type: ignore[attr-defined]

        missing_origin_response = client.post(
            "/api/v1/admin-web/platform/finance/withdrawals/56/reject",
            json={"admin_note": "invalid address"},
        )
        self.assertEqual(403, missing_origin_response.status_code)

        with patch("app.web.admin_web.get_session_factory", return_value=_session_factory(session)):
            with patch(
                "app.web.admin_web._require_platform_admin_user",
                new=AsyncMock(return_value=SimpleNamespace(id=1, is_platform_admin=True, is_banned=False)),
            ) as require_platform:
                with patch(
                    "app.web.admin_web.LedgerService.reject_withdrawal",
                    new=AsyncMock(return_value=withdrawal),
                ) as reject_withdrawal:
                    response = client.post(
                        "/api/v1/admin-web/platform/finance/withdrawals/56/reject",
                        json={"admin_note": "invalid address"},
                        headers=_origin_headers(),
                    )

        self.assertEqual(200, response.status_code)
        require_platform.assert_awaited_once_with(session, 123)
        reject_withdrawal.assert_awaited_once_with(
            session,
            56,
            "invalid address",
            actor_user_id=1,
        )
        self.assertEqual(1, session.commit_count)
        payload = response.json()
        self.assertEqual(56, payload["withdrawal_id"])
        self.assertEqual("rejected", payload["status"])
        self.assertEqual("Tabcde***567890", payload["address_masked"])
        response_text = response.text.lower()
        for forbidden in (
            "tenant_id",
            "account_id",
            "ledger_entry_id",
            "address_encrypted",
            "tabcdef1234567890",
            "invalid address",
            "admin_note",
            "actor_user_id",
            "raw_payload",
            "api_key",
            "token",
            "secret",
        ):
            self.assertNotIn(forbidden, response_text)

    def test_platform_withdrawal_review_rejects_extra_fields_before_service(self) -> None:
        settings = _settings()
        client = _client(settings)
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        client.cookies.set(
            ADMIN_WEB_SESSION_COOKIE_NAME,
            codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id=PLATFORM_WORKSPACE_ID)),
        )

        with patch(
            "app.web.admin_web.LedgerService.complete_withdrawal",
            new=AsyncMock(side_effect=AssertionError("不应进入服务层")),
        ):
            response = client.post(
                "/api/v1/admin-web/platform/finance/withdrawals/55/complete",
                json={
                    "admin_note": "paid offline",
                    "payout_reference": "tx",
                    "tenant_id": 7,
                    "amount": "999",
                    "address": "plain-address",
                    "actor_user_id": 1,
                    "raw_payload": {"token": "plain-token"},
                },
                headers=_origin_headers(),
            )

        self.assertEqual(422, response.status_code)

    def test_session_codec_rejects_tampered_token(self) -> None:
        settings = _settings()
        codec = AdminWebSessionCodec(settings, now=TEST_SESSION_NOW)
        token = codec.encode(codec.new_claims(telegram_user_id=123, current_workspace_id="tn_demo"))

        with self.assertRaises(AdminWebSessionError):
            codec.decode(token + "tampered")


if __name__ == "__main__":
    unittest.main()
