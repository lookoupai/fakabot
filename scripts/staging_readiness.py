from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]

PASS = "pass"
WARN = "warn"
FAIL = "fail"

REQUIRED_ENV_KEYS = {
    "APP_ENV",
    "PUBLIC_BASE_URL",
    "DATABASE_URL",
    "REDIS_URL",
    "MASTER_BOT_TOKEN",
    "MASTER_WEBHOOK_SECRET",
    "TOKEN_ENCRYPTION_KEY",
    "PLATFORM_ADMIN_IDS",
    "PLATFORM_ADMIN_API_KEY_HASHES",
    "PLATFORM_ADMIN_API_KEY_SCOPES",
    "WEBHOOK_BASE_PATH",
    "STORAGE_ROOT",
    "EPUSDT_BASE_URL",
    "EPUSDT_PID",
    "EPUSDT_SECRET_KEY",
    "WORKERS_ENABLED",
    "TELEGRAM_WEBAPP_REQUIRE_INIT_DATA",
    "ADMIN_WEB_SESSION_MAX_AGE_SECONDS",
    "ADMIN_WEB_BINDING_CODE_TTL_SECONDS",
    "ADMIN_WEB_BINDING_CODE_RATE_LIMIT_PER_MINUTE",
    "ADMIN_WEB_ALLOWED_ORIGINS",
    "PLATFORM_ADMIN_REQUIRE_SIGNATURE",
}

REQUIRED_FILES = (
    "app/main.py",
    "alembic.ini",
    "scripts/verify_migrations.py",
    "docker-compose.yml",
    ".env.example",
    ".gitignore",
    ".dockerignore",
    "workers/storefront/src/worker.mjs",
    "workers/storefront/test/worker.test.mjs",
    "workers/storefront/wrangler.toml.example",
    "app/web/platform_admin.py",
    "app/web/admin_web.py",
    "app/services/admin_web.py",
    "app/services/tenant_features.py",
    "web/admin/package.json",
    "web/admin/src/App.tsx",
)


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    status: str
    detail: str


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline staging readiness checks. Does not read .env, start services, or call external APIs.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero on warnings as well as failures. Default only fails on failed checks.",
    )
    parser.add_argument(
        "--project-root",
        default=str(PROJECT_ROOT),
        help="Project root to inspect. Defaults to repository root.",
    )
    args = parser.parse_args(argv)

    checks = run_checks(Path(args.project_root))
    if args.json:
        print(json.dumps([asdict(check) for check in checks], ensure_ascii=False, indent=2))
    else:
        print_report(checks)

    has_fail = any(check.status == FAIL for check in checks)
    has_warn = any(check.status == WARN for check in checks)
    return 1 if has_fail or (args.strict and has_warn) else 0


def run_checks(project_root: Path = PROJECT_ROOT) -> list[ReadinessCheck]:
    project_root = project_root.resolve()
    checks: list[ReadinessCheck] = []
    checks.extend(_check_required_files(project_root))
    checks.append(_check_env_example(project_root))
    checks.append(_check_secret_ignores(project_root))
    checks.append(_check_fastapi_routes(project_root))
    checks.append(_check_admin_web_contract(project_root))
    checks.append(_check_health_worker_readiness(project_root))
    checks.append(_check_background_worker_scheduler(project_root))
    checks.append(_check_file_inspection_contract(project_root))
    checks.append(_check_tenant_admin_product_metadata_contract(project_root))
    checks.append(_check_external_auto_fulfillment_safety_contract(project_root))
    checks.append(_check_tenant_admin_payment_config_contract(project_root))
    checks.append(_check_trc20_direct_reconcile_contract(project_root))
    checks.append(_check_tenant_admin_trc20_direct_transfer_observation_contract(project_root))
    checks.append(_check_tenant_admin_order_diagnostics_contract(project_root))
    checks.append(_check_tenant_admin_audit_log_contract(project_root))
    checks.append(_check_tenant_admin_risk_observability_contract(project_root))
    checks.append(_check_platform_admin_api_key_scope_contract(project_root))
    checks.append(_check_platform_admin_risk_ban_observability_contract(project_root))
    checks.append(_check_platform_admin_risk_user_ban_action_contract(project_root))
    checks.append(_check_platform_admin_tenant_suspension_action_contract(project_root))
    checks.append(_check_platform_admin_risk_audit_log_contract(project_root))
    checks.append(_check_platform_admin_finance_withdrawal_read_contract(project_root))
    checks.append(_check_platform_admin_finance_withdrawal_review_contract(project_root))
    checks.append(_check_platform_admin_subscription_plan_contract(project_root))
    checks.append(_check_tenant_admin_report_export_jobs_contract(project_root))
    checks.append(_check_tenant_admin_subscription_read_contract(project_root))
    checks.append(_check_tenant_admin_supply_reseller_contract(project_root))
    checks.append(_check_tenant_admin_supply_supplier_contract(project_root))
    checks.append(_check_tenant_admin_supply_supplier_rule_contract(project_root))
    checks.append(_check_platform_admin_supply_offer_status_contract(project_root))
    checks.append(_check_tenant_admin_finance_withdrawal_contract(project_root))
    checks.append(_check_migration_verifier(project_root))
    checks.append(_check_compose_contract(project_root))
    checks.append(_check_worker_storefront(project_root))
    checks.append(_check_worker_storefront_error_states_contract(project_root))
    checks.append(_check_public_store_tests(project_root))
    checks.append(_check_external_http_adapter_contract(project_root))
    checks.append(_check_standard_http_external_provider_contract(project_root))
    checks.append(_check_mcy_shop_external_provider_contract(project_root))
    checks.append(_check_payment_adapter_contract(project_root))
    checks.append(_check_business_plugin_contract(project_root))
    checks.append(_warning_real_external_provider_required())
    checks.append(_warning_real_staging_integration_required())
    return checks


def print_report(checks: Iterable[ReadinessCheck]) -> None:
    counts = {PASS: 0, WARN: 0, FAIL: 0}
    materialized = list(checks)
    for check in materialized:
        counts[check.status] = counts.get(check.status, 0) + 1
        print(f"[{check.status.upper()}] {check.name}: {check.detail}")
    print(
        "[SUMMARY] "
        f"pass={counts.get(PASS, 0)} "
        f"warn={counts.get(WARN, 0)} "
        f"fail={counts.get(FAIL, 0)} "
        "online_actions_executed=false"
    )


def _check_required_files(project_root: Path) -> list[ReadinessCheck]:
    checks: list[ReadinessCheck] = []
    for relative_path in REQUIRED_FILES:
        path = project_root / relative_path
        checks.append(
            ReadinessCheck(
                name=f"required_file:{relative_path}",
                status=PASS if path.is_file() else FAIL,
                detail="exists" if path.is_file() else "missing",
            )
        )
    return checks


def _check_env_example(project_root: Path) -> ReadinessCheck:
    env_example = project_root / ".env.example"
    if not env_example.is_file():
        return ReadinessCheck("env_example_contract", FAIL, ".env.example missing")
    keys = set(_env_example_keys(env_example.read_text(encoding="utf-8")))
    missing = sorted(REQUIRED_ENV_KEYS - keys)
    if missing:
        return ReadinessCheck("env_example_contract", FAIL, f"missing keys: {', '.join(missing)}")
    return ReadinessCheck(
        "env_example_contract",
        PASS,
        "staging-required keys documented; real .env not read",
    )


def _check_secret_ignores(project_root: Path) -> ReadinessCheck:
    gitignore = _read_optional(project_root / ".gitignore")
    dockerignore = _read_optional(project_root / ".dockerignore")
    required_gitignore = [".env", ".env.*", "!.env.example", ".venv/", "logs/", "storage/", "*.sqlite3"]
    required_dockerignore = [".env", ".env.*", "logs/", "storage/"]
    missing = [
        f".gitignore:{pattern}" for pattern in required_gitignore if pattern not in gitignore
    ] + [
        f".dockerignore:{pattern}" for pattern in required_dockerignore if pattern not in dockerignore
    ]
    if missing:
        return ReadinessCheck("secret_and_runtime_ignores", FAIL, f"missing patterns: {', '.join(missing)}")
    return ReadinessCheck("secret_and_runtime_ignores", PASS, ".env, storage, logs, venv and DB artifacts ignored")


def _check_fastapi_routes(project_root: Path) -> ReadinessCheck:
    main_py = _read_optional(project_root / "app" / "main.py")
    required_markers = [
        "health_router",
        "create_webhook_router",
        "create_payment_router",
        "create_file_router",
        "create_export_router",
        "create_public_store_router",
        "create_tenant_admin_router",
        "create_platform_admin_router",
        "create_admin_web_router",
        "BackgroundWorkerManager",
    ]
    missing = [marker for marker in required_markers if marker not in main_py]
    if missing:
        return ReadinessCheck("fastapi_route_mounts", FAIL, f"missing markers: {', '.join(missing)}")
    return ReadinessCheck(
        "fastapi_route_mounts",
        PASS,
        "health, webhook, payment, files, exports, Public Store, Tenant Admin, Platform Admin, Admin Web and workers are wired",
    )


def _check_admin_web_contract(project_root: Path) -> ReadinessCheck:
    web_module = _read_optional(project_root / "app" / "web" / "admin_web.py")
    service_module = _read_optional(project_root / "app" / "services" / "admin_web.py")
    tenant_features = _read_optional(project_root / "app" / "services" / "tenant_features.py")
    config = _read_optional(project_root / "app" / "config.py")
    tests = _read_optional(project_root / "tests" / "test_admin_web.py")
    docs_plan = _read_optional(project_root / "docs" / "Web管理后台开发计划.md")
    docs_roadmap = _read_optional(project_root / "docs" / "实施路线图.md")
    frontend_package = _read_optional(project_root / "web" / "admin" / "package.json")
    frontend_shell = _read_optional(project_root / "web" / "admin" / "src" / "components" / "layout" / "admin-shell.tsx")
    frontend_api = _read_optional(project_root / "web" / "admin" / "src" / "lib" / "admin-web-api.ts")
    master_router = _read_optional(project_root / "app" / "bots" / "routers" / "master.py")
    tenant_router = _read_optional(project_root / "app" / "bots" / "routers" / "tenant.py")
    tenant_web_code_tests = _read_optional(project_root / "tests" / "test_tenant_admin_web_code.py")
    master_lifecycle_tests = _read_optional(project_root / "tests" / "test_master_bot_lifecycle.py")
    openapi_tests = _read_optional(project_root / "tests" / "test_openapi_security_contract.py")
    main_py = _read_optional(project_root / "app" / "main.py")

    missing: list[str] = []
    required_web_markers = [
        "create_admin_web_router",
        "AdminWebSafeValidationRoute",
        "_safe_admin_web_validation_errors",
        'prefix="/api/v1/admin-web"',
        '"/sessions/telegram"',
        '"/sessions/binding-code"',
        '"/workspaces/select"',
        '"/tenant/overview"',
        '"/tenant/settings"',
        '"/tenant/products"',
        '"/tenant/products/{product_id}/metadata"',
        '"/tenant/products/{product_id}/sales"',
        '"/tenant/products/status"',
        '"/tenant/products/{product_id}/inventory/import"',
        '"/tenant/products/{product_id}/delivery-file"',
        '"/tenant/orders"',
        '"/tenant/orders/observability"',
        '"/tenant/orders/{out_trade_no}/diagnostics"',
        '"/tenant/risk"',
        '"/tenant/reports/export-jobs"',
        '"/tenant/reports/export-jobs/download"',
        "AdminWebReportExportJobDownloadRequest",
        "FileResponse",
        "tenant_download_report_export_job",
        "download_handle",
        '"/tenant/api-keys"',
        '"/tenant/api-keys/revoke"',
        '"/tenant/subscription"',
        '"/tenant/subscription/renewal-orders"',
        '"/tenant/finance"',
        '"/tenant/finance/withdrawals"',
        '"/tenant/payments/configs"',
        '"/tenant/payments/{provider_name}/config"',
        '"/business-plugins/capabilities"',
        "AdminWebBusinessPluginCapabilityItemResponse",
        "AdminWebBusinessPluginCapabilitiesResponse",
        "_business_plugin_capabilities_response",
        '"/tenant/external-source-connections"',
        '"/tenant/external-source-connections/disable"',
        '"/tenant/external-sources/catalog/sync"',
        '"/tenant/external-sources/catalog/products"',
        "AdminWebExternalSourceConnectionCreateRequest",
        "AdminWebExternalSourceConnectionDisableRequest",
        "AdminWebExternalCatalogSyncRequest",
        "AdminWebExternalCatalogSyncResponse",
        "AdminWebSyncedExternalCatalogProductResponse",
        "AdminWebExternalSourceCatalogProductItemResponse",
        "AdminWebExternalSourceCatalogProductsResponse",
        "AdminWebExternalSourceProviderItemResponse",
        "AdminWebExternalSourceConnectionItemResponse",
        "AdminWebExternalSourceConnectionsResponse",
        "AdminWebPlatformBotWebhookResetRequest",
        "AdminWebPlatformBotWebhookResetResponse",
        "AdminWebPlatformTenantSubscriptionGrantDaysRequest",
        "AdminWebPlatformTenantSubscriptionSetPeriodEndRequest",
        "AdminWebPlatformTenantSubscriptionAdjustmentResponse",
        "AdminWebPlatformSubscriptionPlanUpdateRequest",
        "AdminWebPlatformSubscriptionPlanItemResponse",
        '"/platform/bots/{tenant_public_id}/webhook/reset"',
        '"/platform/subscription/plans/{plan_code}"',
        '"/platform/finance/withdrawals/{withdrawal_id}"',
        '"/platform/tenants/{tenant_public_id}/subscription/grant-days"',
        '"/platform/tenants/{tenant_public_id}/subscription/period-end"',
        "platform_reset_bot_webhook",
        "platform_update_subscription_plan",
        "platform_withdrawal_detail",
        "platform_grant_tenant_subscription_days",
        "platform_set_tenant_subscription_period_end",
        "_platform_tenant_subscription_adjustment_response",
        "tenant_offset",
        "tenant_query",
        "bot_status",
        "subscription_status",
        "_normalize_platform_tenant_search_query",
        "ADMIN_WEB_TENANT_WEBHOOK_ALLOWED_UPDATES",
        "telegram_webhook_called",
        "tenant_external_source_connections",
        "tenant_create_external_source_connection",
        "tenant_disable_external_source_connection",
        "tenant_sync_external_catalog",
        "tenant_external_source_catalog_products",
        "_external_source_connections_response",
        "_external_source_provider_response",
        "_external_source_connection_response",
        "_external_catalog_sync_response",
        "_external_source_catalog_products_response",
        '"/tenant/supply/dashboard"',
        '"/tenant/supply/applications"',
        '"/tenant/supply/supplier-offers"',
        '"/tenant/supply/supplier-offers/{supplier_offer_id}/approval"',
        '"/tenant/supply/supplier-rules"',
        '"/tenant/supply/supplier-applications/review"',
        '"/tenant/supply/reseller-products"',
        '"/tenant/supply/reseller-products/{reseller_product_id}/metadata"',
        '"/session"',
        '"/workspaces"',
        '"/logout"',
        "validate_telegram_webapp_init_data",
        "httponly=True",
        'samesite="lax"',
        "admin_web_session_max_age_seconds",
        "admin_web_binding_code_rate_limit_per_minute",
        "AdminWebBindingCodeStore",
        "_hit_binding_code_rate_limit",
        "RedisFixedWindowRateLimiter",
        "_require_admin_web_origin",
        "admin_web_allowed_origins",
        'request.headers.get("origin")',
        "AdminWebProductMetadataRequest",
        "AdminWebTenantStoreSettingsRequest",
        "AdminWebProductCreateRequest",
        "AdminWebProductSalesRequest",
        "AdminWebProductBatchStatusRequest",
        "AdminWebTenantProductBatchStatusResponse",
        "AdminWebProductInventoryImportRequest",
        "AdminWebProductInventoryImportResponse",
        "AdminWebProductDeliveryFileResponse",
        "AdminWebResellerProductMetadataRequest",
        "AdminWebResellerProductSalesRequest",
        "UploadFile",
        "File(",
        "tenant_create_product",
        "tenant_store_settings",
        "tenant_update_store_settings",
        "self_sale_enabled",
        "supplier_enabled",
        "reseller_enabled",
        "payload.self_sale_enabled",
        "payload.supplier_enabled",
        "payload.reseller_enabled",
        "tenant_update_product_metadata",
        "tenant_update_product_sales",
        "tenant_batch_update_product_status",
        "tenant_import_product_inventory",
        "tenant_upload_product_delivery_file",
        "category",
        "sort_order",
        "AdminWebPaymentConfigRequest",
        "AdminWebPlatformStatsResponse",
        "AdminWebPlatformPaymentProviderItemResponse",
        "AdminWebPlatformSubscriptionAttentionItemResponse",
        "payment_providers",
        "subscription_attention",
        "_list_platform_payment_provider_observations",
        "list_platform_subscription_attention",
        "_count_tenant_payment_provider_configs_by_provider",
        "PaymentProviderConfig",
        "list_payment_provider_summaries",
        "trial_subscription_count",
        "active_subscription_count",
        "grace_subscription_count",
        "suspended_subscription_count",
        "retention_expired_subscription_count",
        "_count_effective_subscription_status",
        "AdminWebTenantOrderDiagnosticsResponse",
        "AdminWebTenantOrderObservabilityResponse",
        "AdminWebPaymentCallbackFailureItemResponse",
        "AdminWebPaymentCallbackRejectionItemResponse",
        "AdminWebExternalFulfillmentAttemptItemResponse",
        "AdminWebTenantRiskDashboardResponse",
        "AdminWebTenantRiskDisputeItemResponse",
        "AdminWebTenantRiskAfterSaleItemResponse",
        "AdminWebReportExportJobCreateRequest",
        "AdminWebTenantReportExportJobItemResponse",
        "AdminWebTenantReportExportJobsResponse",
        "AdminWebTenantApiKeyCreateRequest",
        "AdminWebTenantApiKeyRevokeRequest",
        "AdminWebTenantApiKeysResponse",
        "AdminWebCreatedTenantApiKeyResponse",
        "AdminWebTenantApiKeyRevokeResponse",
        "AdminWebTenantSubscriptionDashboardResponse",
        "AdminWebSubscriptionRenewalOrderRequest",
        "AdminWebSubscriptionRenewalOrderResponse",
        "AdminWebTenantFinanceDashboardResponse",
        "AdminWebWithdrawalRequest",
        "AdminWebTenantWithdrawalItemResponse",
        "AdminWebExternalCatalogSyncRequest",
        "AdminWebExternalCatalogSyncResponse",
        "AdminWebSyncedExternalCatalogProductResponse",
        "_tenant_order_diagnostics_response",
        "_tenant_order_observability_response",
        "_tenant_risk_dashboard_response",
        "_tenant_report_export_jobs_response",
        "_tenant_report_export_job_response",
        "_tenant_api_keys_response",
        "_created_tenant_api_key_response",
        "_tenant_api_key_revoke_response",
        "_tenant_subscription_dashboard_response",
        "_subscription_renewal_order_response",
        "_tenant_finance_dashboard_response",
        "_tenant_withdrawal_response",
        "_safe_finance_error_detail",
        "_require_admin_web_supply_dashboard_query_params",
        "market_query",
        "market_delivery_type",
        "market_access",
        "market_min_price",
        "market_max_price",
        "market_stock",
        "market_category",
        "AdminWebTenantPaymentProviderConfigsResponse",
        "AdminWebTenantPaymentProviderConfigItemResponse",
        "tenant_payment_configs",
        "tenant_update_payment_config",
        "tenant_disable_payment_config",
        "tenant_sync_external_catalog",
        "_external_catalog_sync_response",
        "tenant_risk_dashboard",
        "tenant_report_export_jobs",
        "tenant_create_report_export_job",
        "tenant_report_export_download_file",
        "tenant_api_keys",
        "tenant_create_api_key",
        "tenant_revoke_api_key",
        "tenant_create_subscription_renewal_order",
        "tenant_create_withdrawal",
        'extra="forbid"',
    ]
    missing.extend(
        f"app/web/admin_web.py:{marker}"
        for marker in required_web_markers
        if marker not in web_module
    )
    required_service_markers = [
        "AdminWebSessionCodec",
        "AdminWebBindingCodeStore",
        "ADMIN_WEB_BINDING_CODE_PREFIX",
        "token_encryption_key",
        "hmac.compare_digest",
        "AdminWebWorkspaceSummary",
        "AdminWebTenantOverview",
        "AdminWebTenantStoreSettings",
        "AdminWebTenantPaymentProviderOverview",
        "AdminWebTenantProductItem",
        "AdminWebTenantProductBatchStatusUpdate",
        "AdminWebInventoryImportResult",
        "AdminWebProductDeliveryFileResult",
        "AdminWebTenantProductsPage",
        "AdminWebTenantOrderItem",
        "AdminWebTenantOrdersPage",
        "AdminWebTenantOrderDiagnostics",
        "AdminWebTenantOrderObservability",
        "AdminWebPaymentCallbackFailureItem",
        "AdminWebPaymentCallbackRejectionItem",
        "AdminWebExternalFulfillmentAttemptItem",
        "AdminWebOrderPaymentDiagnosticItem",
        "AdminWebOrderPaymentCallbackDiagnosticItem",
        "AdminWebOrderDeliveryDiagnosticItem",
        "AdminWebOrderExternalFulfillmentDiagnosticItem",
        "AdminWebOrderTrc20DirectDiagnosticItem",
        "AdminWebTenantRiskDashboard",
        "AdminWebTenantRiskDisputeItem",
        "AdminWebTenantRiskAfterSaleItem",
        "AdminWebTenantReportExportJobItem",
        "AdminWebTenantReportExportJobsPage",
        "AdminWebTenantApiKeyHandleCodec",
        "AdminWebTenantApiKeyItem",
        "AdminWebTenantApiKeysPage",
        "AdminWebCreatedTenantApiKeyItem",
        "AdminWebTenantApiKeyRevokeResult",
        "AdminWebTenantSupplyDashboard",
        "AdminWebSubscriptionRenewalOrder",
        "AdminWebApplicationHandleCodec",
        "AdminWebSupplierRuleHandleCodec",
        "AdminWebCreatedSupplierOfferItem",
        "AdminWebSupplierOfferApprovalItem",
        "AdminWebSupplierRuleItem",
        "AdminWebSupplyMarketOfferItem",
        "AdminWebResellerApplicationItem",
        "AdminWebCreatedResellerProductItem",
        "tenant_overview",
        "tenant_store_settings",
        "tenant_update_store_settings",
        "tenant.self_sale_enabled = self_sale_enabled",
        "tenant.supplier_enabled = supplier_enabled",
        "tenant.reseller_enabled = reseller_enabled",
        'feature_flags["self_sale"]',
        'feature_flags["supplier"]',
        'feature_flags["reseller"]',
        'upsert_setting(session, tenant.id, "feature_flags"',
        "tenant_products",
        "tenant_create_product",
        "tenant_update_product_metadata",
        "tenant_update_product_sales",
        "tenant_batch_update_product_status",
        "tenant_import_product_inventory",
        "tenant_upload_product_delivery_file",
        "tenant_orders",
        "tenant_order_diagnostics",
        "tenant_order_observability",
        "PaymentCallbackFailureLogService",
        "PaymentCallbackRejectionAuditService",
        "ExternalFulfillmentAttemptLogService",
        "OrderDiagnosticsService",
        "OrderDiagnosticsSummary",
        "tenant_risk_dashboard",
        "RiskControlService",
        "_tenant_risk_dispute_item",
        "_tenant_risk_after_sale_item",
        "_normalize_tenant_risk_status",
        "_admin_web_safe_risk_text",
        "tenant_report_export_jobs",
        "tenant_create_report_export_job",
        "tenant_api_keys",
        "tenant_create_api_key",
        "tenant_revoke_api_key",
        "list_tenant_api_keys",
        "create_tenant_api_key",
        "revoke_tenant_api_key",
        "AdminWebTenantApiKeyHandleCodec(settings).decode",
        "_tenant_report_export_job_item",
        "AdminWebTenantReportExportDownloadFile",
        "AdminWebReportExportDownloadHandleClaims",
        "AdminWebReportExportDownloadHandleCodec",
        "_tenant_api_key_item",
        "_created_tenant_api_key_item",
        "_normalize_tenant_report_export_status",
        "_normalize_optional_tenant_report_type",
        "_normalize_required_tenant_report_type",
        "_admin_web_safe_report_failure_text",
        "list_export_jobs",
        "create_export_job",
        "get_downloadable_tenant_export",
        "_admin_web_report_download_filename",
        'scope_type="tenant"',
        "tenant_subscription_dashboard",
        "tenant_create_subscription_renewal_order",
        "tenant_finance_dashboard",
        "tenant_create_withdrawal_request",
        "AdminWebTenantSubscriptionDashboard",
        "AdminWebTenantFinanceDashboard",
        "AdminWebTenantWithdrawalItem",
        "SubscriptionService",
        "PaymentService",
        "LedgerService",
        "create_withdrawal_request",
        "_load_main_ledger",
        "_tenant_finance_withdrawal_request_item",
        "_validate_withdrawal_amount",
        "_normalize_finance_text",
        "actor_user_id=user.id",
        "tenant_payment_configs",
        "tenant_update_payment_config",
        "tenant_disable_payment_config",
        "AdminWebTenantPaymentProviderConfigItem",
        "AdminWebTenantPaymentProviderConfigsPage",
        "AdminWebBusinessPluginCapabilityItem",
        "AdminWebBusinessPluginCapabilitiesSummary",
        "business_plugin_capabilities",
        "BusinessPluginManifest",
        "list_current_business_plugin_manifests",
        "ExternalSourceConnectionService",
        "ExternalProviderSummary",
        "list_provider_summaries",
        "AdminWebExternalSourceProviderItem",
        "AdminWebExternalSourceConnectionItem",
        "AdminWebExternalSourceConnectionsPage",
        "AdminWebExternalCatalogSyncProductItem",
        "AdminWebExternalCatalogSyncResultItem",
        "AdminWebExternalSourceConnectionHandleClaims",
        "AdminWebExternalSourceConnectionHandleCodec",
        "tenant_external_source_connections",
        "tenant_create_external_source_connection",
        "tenant_disable_external_source_connection",
        "tenant_sync_external_catalog",
        "AdminWebExternalSourceConnectionHandleCodec(settings).decode",
        "load_runtime_credentials",
        "ExternalCatalogSyncService",
        "sync_registered_catalog",
        "_admin_web_callback_failure_item",
        "_admin_web_callback_rejection_item",
        "_admin_web_external_fulfillment_attempt_item",
        "_external_source_provider_item",
        "_external_source_connection_item",
        "_external_catalog_sync_result_item",
        "_load_tenant_payment_plugin_states",
        "ADMIN_WEB_PAYMENT_PROVIDERS",
        "PaymentConfigService",
        "tenant_supply_dashboard",
        "tenant_supply_review_supplier_application",
        "tenant_supply_create_supplier_offer",
        "tenant_supply_set_supplier_offer_approval",
        "tenant_supply_set_supplier_rule",
        "tenant_supply_apply",
        "tenant_supply_create_reseller_product",
        "tenant_supply_update_reseller_product_metadata",
        "tenant_supply_update_reseller_product_sales",
        "load_tenant_feature_flags",
        "require_tenant_feature",
        "market_query",
        "market_delivery_type",
        "market_access",
        "market_min_price",
        "market_max_price",
        "market_stock",
        "market_category",
        "list_supplier_reseller_rules",
        "create_self_product",
        "set_existing_reseller_rule",
        "set_product_category",
        "set_product_sort_order",
        "update_self_product",
        "add_inventory_items",
        "get_product_with_default_variant",
        "inventory_summary",
        "FileStorageService",
        "store_upload_file",
        "FileInspectionService",
        "inspect_uploaded_file",
        "create_uploaded_file",
        "bind_delivery_file",
        "file_download",
        "TokenCrypto",
        "card_pool",
        "card_fixed",
        "category_provided",
        "create_renewal_order",
        "create_payment_for_order",
        "subscription_monthly_price",
        "payment_available",
        "payment_failure_reason",
        "SupplyService",
        "EPUSDT_PROVIDER",
        "EPAY_COMPATIBLE_PROVIDER",
        "TenantMember.status == \"active\"",
        "TenantMember.role.in_",
        "workspace_id=tenant.public_id",
        "is_banned",
        "has_permission(session, tenant.id, telegram_user_id, \"settings\")",
    ]
    missing.extend(
        f"app/services/admin_web.py:{marker}"
        for marker in required_service_markers
        if marker not in service_module
    )
    required_tenant_feature_markers = [
        "DEFAULT_TENANT_FEATURE_FLAGS",
        "TENANT_FEATURE_DISABLED_MESSAGES",
        "build_tenant_feature_flags",
        "load_tenant_feature_flags",
        "require_tenant_feature",
        '"self_sale"',
        '"supplier"',
        '"reseller"',
    ]
    missing.extend(
        f"app/services/tenant_features.py:{marker}"
        for marker in required_tenant_feature_markers
        if marker not in tenant_features
    )
    required_config_markers = [
        "admin_web_session_max_age_seconds",
        "admin_web_binding_code_ttl_seconds",
        "admin_web_binding_code_rate_limit_per_minute",
        "admin_web_allowed_origins",
        "parse_admin_web_allowed_origins",
        "validate_admin_web_allowed_origins",
    ]
    missing.extend(
        f"app/config.py:{marker}"
        for marker in required_config_markers
        if marker not in config
    )
    required_test_markers = [
        "test_master_telegram_session_sets_http_only_cookie_and_safe_payload",
        "test_tenant_entrypoint_requires_workspace_access_before_cookie",
        "test_write_routes_reject_missing_or_untrusted_origin",
        "test_allowed_origin_and_session_ttl_can_be_configured",
        "test_binding_code_store_hashes_and_consumes_code_once",
        "test_binding_code_session_sets_cookie_and_safe_payload",
        "test_binding_code_session_requires_origin_and_redis",
        "test_binding_code_session_rate_limits_failed_attempts",
        "test_tenant_overview_requires_current_clone_bot_workspace",
        "test_tenant_overview_returns_safe_current_workspace_summary",
        "test_tenant_overview_rejects_lost_workspace_access",
        "test_tenant_settings_returns_current_workspace_safe_payload",
        "test_tenant_update_settings_uses_current_workspace_origin_and_safe_payload",
        "test_tenant_update_settings_feature_flags_only_uses_current_workspace_origin",
        "test_tenant_update_settings_rejects_extra_fields_before_service",
        "test_tenant_update_settings_rejects_raw_feature_flags_and_clone_enabled_before_service",
        "test_tenant_update_settings_rejects_empty_payload_before_service",
        "test_tenant_update_settings_rejects_null_fields_before_service",
        "test_tenant_update_settings_rejects_null_feature_flags_before_service",
        "test_tenant_update_settings_rejects_missing_or_untrusted_origin",
        "test_tenant_update_settings_requires_current_clone_bot_workspace",
        "test_tenant_update_settings_value_error_returns_400_without_commit",
        "test_tenant_update_store_settings_uses_resolved_workspace_tenant_and_settings_permission",
        "test_tenant_update_store_settings_preserves_existing_feature_flags_on_partial_update",
        "test_tenant_store_settings_reads_feature_flags_compatibility_values",
        "test_tenant_update_store_settings_rejects_missing_settings_permission",
        "test_tenant_products_requires_current_clone_bot_workspace",
        "test_tenant_products_returns_safe_current_workspace_items",
        "test_tenant_update_product_metadata_uses_current_workspace_and_safe_payload",
        "test_tenant_update_product_metadata_rejects_extra_fields_before_service",
        "test_tenant_update_product_metadata_rejects_empty_payload_before_service",
        "test_tenant_update_product_metadata_rejects_null_sort_order_before_service",
        "test_tenant_update_product_metadata_rejects_missing_or_untrusted_origin",
        "test_tenant_update_product_metadata_requires_current_clone_bot_workspace",
        "test_tenant_update_product_metadata_service_error_returns_403_without_commit",
        "test_tenant_update_product_metadata_uses_resolved_workspace_tenant",
        "test_tenant_create_product_uses_current_workspace_origin_and_safe_payload",
        "test_tenant_create_product_rejects_extra_fields_before_service",
        "test_tenant_create_product_rejects_missing_or_untrusted_origin",
        "test_tenant_create_product_requires_current_clone_bot_workspace",
        "test_tenant_create_product_service_error_returns_403_without_commit",
        "test_tenant_create_product_value_error_returns_400_without_commit_or_secret",
        "test_tenant_create_product_uses_resolved_workspace_tenant",
        "test_tenant_update_product_price_status_uses_current_workspace_origin_and_safe_payload",
        "test_tenant_update_product_price_status_rejects_extra_fields_before_service",
        "test_tenant_update_product_price_status_rejects_empty_payload_before_service",
        "test_tenant_update_product_price_status_rejects_missing_or_untrusted_origin",
        "test_tenant_update_product_price_status_requires_current_clone_bot_workspace",
        "test_tenant_update_product_price_status_service_error_returns_403_without_commit",
        "test_tenant_update_product_price_status_value_error_returns_400_without_commit",
        "test_tenant_update_product_price_status_uses_resolved_workspace_tenant",
        "test_tenant_update_product_price_status_hides_non_self_product_error",
        "test_tenant_import_product_inventory_uses_current_workspace_origin_and_safe_payload",
        "test_tenant_import_product_inventory_rejects_extra_fields_before_service",
        "test_tenant_import_product_inventory_rejects_missing_or_untrusted_origin",
        "test_tenant_import_product_inventory_requires_current_clone_bot_workspace",
        "test_tenant_import_product_inventory_value_error_returns_400_without_commit_or_content",
        "test_tenant_import_product_inventory_service_error_returns_403_without_commit",
        "test_tenant_import_product_inventory_uses_resolved_workspace_tenant",
        "test_tenant_import_product_inventory_hides_non_self_product_error",
        "test_tenant_upload_product_delivery_file_uses_current_workspace_origin_and_safe_payload",
        "test_tenant_upload_product_delivery_file_rejects_missing_or_untrusted_origin",
        "test_tenant_upload_product_delivery_file_requires_current_clone_bot_workspace",
        "test_tenant_upload_product_delivery_file_value_error_returns_400_without_commit_or_storage_key",
        "test_tenant_upload_product_delivery_file_service_error_returns_403_without_commit",
        "test_tenant_upload_product_delivery_file_uses_resolved_workspace_tenant",
        "test_tenant_upload_product_delivery_file_does_not_bind_blocked_scan",
        "test_tenant_orders_returns_safe_current_workspace_items",
        "test_tenant_orders_clamps_large_limit_before_service",
        "test_tenant_order_diagnostics_requires_current_clone_bot_workspace",
        "test_tenant_order_diagnostics_returns_safe_current_workspace_summary",
        "test_tenant_order_diagnostics_returns_403_for_cross_tenant_or_missing_order",
        "test_tenant_order_diagnostics_uses_resolved_workspace_tenant_and_strips_internal_ids",
        "test_tenant_order_observability_returns_safe_current_workspace_payload",
        "test_tenant_order_observability_requires_current_clone_bot_workspace",
        "test_tenant_order_observability_value_error_returns_400_without_secret",
        "test_tenant_order_observability_uses_resolved_workspace_tenant_and_safe_services",
        "test_tenant_risk_panel_requires_current_clone_bot_workspace",
        "test_tenant_risk_panel_returns_safe_current_workspace_items",
        "test_tenant_risk_panel_value_error_returns_400_without_secret",
        "test_tenant_risk_dashboard_uses_resolved_workspace_tenant_and_sanitizes_text",
        "test_tenant_report_export_jobs_requires_current_clone_bot_workspace",
        "test_tenant_report_export_jobs_returns_safe_current_workspace_items",
        "test_tenant_report_export_jobs_value_error_returns_400_without_secret",
        "test_tenant_create_report_export_job_requires_current_clone_bot_workspace",
        "test_tenant_create_report_export_job_uses_current_workspace_origin_and_safe_payload",
        "test_tenant_create_report_export_job_rejects_extra_fields_before_service",
        "test_tenant_create_report_export_job_rejects_missing_or_untrusted_origin",
        "test_tenant_report_export_jobs_uses_resolved_workspace_tenant_and_sanitizes_failure_text",
        "test_tenant_create_report_export_job_uses_resolved_workspace_tenant_and_platform_user_actor",
        "test_tenant_report_export_download_requires_current_clone_bot_workspace",
        "test_tenant_report_export_download_rejects_missing_origin_before_service",
        "test_tenant_report_export_download_streams_current_tenant_file_with_safe_filename",
        "test_tenant_report_export_download_hides_handle_and_storage_errors",
        "test_tenant_report_export_download_uses_handle_and_safe_filename",
        "test_tenant_report_export_download_rejects_tampered_or_foreign_handle_before_report_service",
        "test_tenant_api_keys_requires_current_clone_bot_workspace",
        "test_tenant_api_keys_returns_safe_current_workspace_items",
        "test_tenant_create_api_key_requires_current_clone_bot_workspace",
        "test_tenant_create_api_key_returns_plain_key_once_and_safe_payload",
        "test_tenant_create_api_key_rejects_extra_fields_before_service",
        "test_tenant_create_api_key_rejects_missing_or_untrusted_origin",
        "test_tenant_create_api_key_value_error_returns_400_without_secret",
        "test_tenant_revoke_api_key_requires_current_clone_bot_workspace",
        "test_tenant_revoke_api_key_uses_handle_origin_and_safe_payload",
        "test_tenant_revoke_api_key_rejects_extra_fields_before_service",
        "test_tenant_revoke_api_key_rejects_missing_or_untrusted_origin",
        "test_tenant_api_keys_uses_resolved_workspace_tenant_settings_permission_and_safe_handle",
        "test_tenant_api_keys_rejects_missing_settings_permission_before_service",
        "test_tenant_create_api_key_uses_resolved_workspace_tenant_platform_user_actor_and_safe_handle",
        "test_tenant_revoke_api_key_uses_resolved_workspace_tenant_handle_and_platform_user_actor",
        "test_tenant_revoke_api_key_rejects_missing_key_after_handle_decode",
        "test_tenant_subscription_panel_requires_current_clone_bot_workspace",
        "test_tenant_subscription_panel_returns_safe_current_workspace_status_and_invoices",
        "test_tenant_subscription_dashboard_uses_resolved_workspace_tenant",
        "test_tenant_subscription_renewal_order_requires_current_clone_bot_workspace",
        "test_tenant_subscription_renewal_order_uses_current_workspace_origin_and_returns_payment_link",
        "test_tenant_subscription_renewal_order_rejects_extra_fields_before_service",
        "test_tenant_subscription_renewal_order_rejects_missing_or_untrusted_origin",
        "test_tenant_subscription_renewal_order_value_error_returns_400_without_commit",
        "test_tenant_subscription_renewal_order_uses_resolved_workspace_tenant",
        "test_tenant_subscription_renewal_order_keeps_order_when_payment_unavailable_without_leaking_secret",
        "test_tenant_finance_panel_requires_current_clone_bot_workspace",
        "test_tenant_finance_panel_returns_safe_balance_audit_and_withdrawals",
        "test_tenant_finance_dashboard_uses_resolved_workspace_tenant_without_creating_account",
        "test_tenant_create_withdrawal_requires_current_clone_bot_workspace",
        "test_tenant_create_withdrawal_uses_current_workspace_origin_and_returns_masked_payload",
        "test_tenant_create_withdrawal_rejects_extra_fields_before_service",
        "test_tenant_create_withdrawal_rejects_missing_or_untrusted_origin",
        "test_tenant_create_withdrawal_value_error_returns_400_without_commit_or_address",
        "test_tenant_create_withdrawal_runtime_error_returns_503_without_commit_or_secret",
        "test_tenant_create_withdrawal_uses_resolved_workspace_tenant_and_platform_user_actor",
        "test_tenant_create_withdrawal_rejects_invalid_amount_precision_before_ledger",
        "test_tenant_payment_configs_returns_safe_current_workspace_items",
        "test_business_plugin_capabilities_requires_admin_web_session",
        "test_business_plugin_capabilities_requires_current_workspace",
        "test_business_plugin_capabilities_returns_safe_current_workspace_payload",
        "test_business_plugin_capabilities_uses_workspace_and_safe_non_secret_states",
        "test_platform_dashboard_returns_safe_summary_payload",
        "test_platform_dashboard_passes_tenant_filters_to_safe_listing",
        "test_platform_dashboard_rejects_invalid_tenant_filters_before_listing",
        "subscription_attention",
        "attention_reason",
        "test_platform_bot_webhook_reset_calls_telegram_after_origin_and_returns_safe_payload",
        "test_platform_bot_webhook_reset_telegram_failure_does_not_commit_or_rotate_secret",
        "test_platform_bot_status_update_uses_origin_and_clears_local_cache_only",
        "test_platform_bot_status_update_rejects_extra_fields_before_lookup",
        "test_platform_user_ban_requires_origin_and_returns_safe_payload",
        "test_platform_user_unban_uses_origin_and_safe_payload",
        "test_platform_user_ban_rejects_extra_fields_before_service",
        "test_platform_subscription_plan_update_uses_cookie_origin_and_safe_payload",
        "test_platform_subscription_plan_update_rejects_extra_fields_before_service",
        "test_platform_subscription_plan_create_uses_cookie_origin_and_safe_payload",
        "test_platform_subscription_plan_status_uses_cookie_origin_and_safe_payload",
        "test_platform_subscription_plan_create_and_status_reject_extra_fields_before_service",
        "test_platform_tenant_suspension_update_uses_origin_and_clears_webhook_cache",
        "test_platform_tenant_suspension_update_rejects_extra_fields_before_lookup",
        "test_platform_tenant_subscription_grant_days_uses_public_tenant_and_safe_payload",
        "test_platform_tenant_subscription_set_period_end_uses_public_tenant_and_safe_payload",
        "test_platform_tenant_subscription_adjustment_rejects_extra_fields_before_lookup",
        "test_platform_withdrawal_detail_uses_cookie_session_and_safe_payload",
        "test_platform_withdrawal_detail_returns_404_without_commit",
        "test_platform_withdrawal_complete_uses_origin_and_safe_payload",
        "test_platform_withdrawal_reject_uses_origin_and_safe_payload",
        "test_platform_withdrawal_review_rejects_extra_fields_before_service",
        "test_platform_supplier_offer_status_update_uses_origin_and_safe_payload",
        "test_platform_supplier_offer_status_update_rejects_extra_fields_before_service",
        "test_tenant_external_source_connections_returns_safe_current_workspace_payload",
        "test_tenant_create_external_source_connection_uses_origin_and_safe_payload",
        "test_tenant_create_external_source_connection_rejects_extra_internal_fields_before_service",
        "test_tenant_create_external_source_connection_rejects_missing_origin_before_service",
        "test_tenant_disable_external_source_connection_uses_origin_handle_and_safe_payload",
        "test_tenant_external_source_catalog_sync_uses_origin_handle_and_safe_payload",
        "test_tenant_external_source_catalog_sync_rejects_extra_internal_fields_before_service",
        "test_tenant_external_source_catalog_sync_rejects_missing_origin_before_service",
        "test_tenant_external_source_catalog_sync_provider_error_returns_redacted_502",
        "test_tenant_external_source_connections_uses_resolved_workspace_and_safe_summaries",
        "test_tenant_create_external_source_connection_uses_settings_permission_and_platform_user_actor",
        "test_tenant_disable_external_source_connection_uses_handle_and_resolved_tenant",
        "test_tenant_external_source_catalog_sync_uses_handle_and_resolved_tenant_connection",
        "test_tenant_external_source_catalog_sync_rejects_tampered_or_foreign_handle_before_sync_service",
        "test_tenant_update_payment_config_uses_current_workspace_origin_and_safe_payload",
        "test_tenant_update_payment_config_rejects_unsupported_provider_before_service",
        "test_tenant_update_payment_config_rejects_missing_origin_before_service",
        "test_tenant_update_payment_config_rejects_extra_internal_fields_before_service",
        "test_tenant_disable_payment_config_uses_current_workspace_and_origin_gate",
        "test_tenant_update_payment_config_uses_resolved_workspace_tenant",
        "test_tenant_update_payment_config_rejects_non_recent_provider_before_payment_service",
        "test_tenant_supply_dashboard_requires_current_clone_bot_workspace",
        "test_tenant_supply_dashboard_returns_safe_current_workspace_summary",
        "test_tenant_supply_dashboard_passes_market_filters_to_service",
        "test_tenant_supply_dashboard_rejects_invalid_market_filters_without_leaking_tenant_ids",
        "test_tenant_supply_dashboard_uses_resolved_workspace_tenant_and_market_filters",
        "test_tenant_supply_create_supplier_offer_rejects_disabled_supplier_before_supply_service",
        "test_tenant_supply_apply_rejects_disabled_reseller_before_supply_service",
        "test_tenant_supply_supplier_application_review_uses_current_workspace_and_handle",
        "test_tenant_supply_supplier_application_review_rejects_extra_tenant_fields_before_service",
        "test_admin_web_application_handle_codec_round_trips_and_rejects_tampering",
        "test_admin_web_supplier_rule_handle_codec_round_trips_and_rejects_tampering",
        "test_tenant_supply_review_supplier_application_decodes_handle_server_side",
        "test_tenant_supply_set_supplier_rule_uses_current_workspace_and_handle",
        "test_tenant_supply_set_supplier_rule_rejects_extra_internal_fields_before_service",
        "test_tenant_supply_set_supplier_rule_decodes_handle_server_side",
        "test_tenant_supply_apply_uses_current_workspace_and_origin_gate",
        "test_tenant_supply_create_reseller_product_uses_current_workspace_and_safe_payload",
        "test_tenant_supply_update_reseller_product_sales_uses_current_workspace_origin_and_safe_payload",
        "test_tenant_supply_update_reseller_product_sales_uses_resolved_workspace_tenant",
        "test_tenant_supply_write_rejects_extra_tenant_fields_before_service",
        "test_session_codec_rejects_tampered_token",
        "encrypted_token",
        "plain_key",
        "tenant_id",
    ]
    missing.extend(
        f"tests/test_admin_web.py:{marker}"
        for marker in required_test_markers
        if marker not in tests
    )
    required_bot_markers = [
        'Command("admin_web_code")',
        "AdminWebBindingCodeStore",
        "redis_client",
    ]
    missing.extend(
        f"app/bots/routers/master.py:{marker}"
        for marker in required_bot_markers
        if marker not in master_router
    )
    required_tenant_bot_markers = [
        'Command("admin_web_code")',
        "AdminWebBindingCodeStore",
        "tenant_context.tenant_public_id",
        "_ensure_can_manage_message",
        "tenant_feature_disabled_message",
        "tenant_feature_flags",
    ]
    missing.extend(
        f"app/bots/routers/tenant.py:{marker}"
        for marker in required_tenant_bot_markers
        if marker not in tenant_router
    )
    required_binding_code_command_tests = [
        "test_admin_web_code_uses_first_accessible_workspace_without_leaking_internal_ids",
        "test_admin_web_code_with_bot_id_uses_owner_bot_public_workspace",
        "test_owner_can_generate_binding_code_for_current_clone_bot",
        "test_admin_can_generate_binding_code_for_current_clone_bot",
        "test_non_manager_is_rejected_without_issuing_code",
        "test_group_chat_is_rejected_before_permission_lookup_or_code_issue",
        "tenant_public_id",
    ]
    binding_code_command_tests = master_lifecycle_tests + tenant_web_code_tests
    missing.extend(
        f"tests:admin_web_code:{marker}"
        for marker in required_binding_code_command_tests
        if marker not in binding_code_command_tests
    )
    required_frontend_markers = [
        '"vite"',
        '"react"',
        '"tailwindcss"',
        "当前 Bot 工作区",
        "getAdminWebSession",
        "getAdminWebWorkspaces",
        "selectAdminWebWorkspace",
        "createTelegramAdminWebSession",
        "createBindingCodeAdminWebSession",
        "getAdminWebTenantOverview",
        "getAdminWebTenantStoreSettings",
        "updateAdminWebTenantStoreSettings",
        "AdminWebTenantStoreSettingsPayload",
        "getAdminWebTenantProducts",
        "createAdminWebTenantProduct",
        "AdminWebCreateProductPayload",
        "AdminWebProductDeliveryType",
        "updateAdminWebProductMetadata",
        "updateAdminWebProductSales",
        "batchUpdateAdminWebProductStatus",
        "AdminWebProductBatchStatusPayload",
        "AdminWebProductBatchStatusResult",
        "importAdminWebProductInventory",
        "AdminWebProductInventoryImportPayload",
        "AdminWebProductInventoryImportResult",
        "uploadAdminWebProductDeliveryFile",
        "AdminWebProductDeliveryFileResult",
        "getAdminWebTenantOrders",
        "getAdminWebTenantOrderDiagnostics",
        "getAdminWebTenantOrderObservability",
        "getAdminWebTenantRiskDashboard",
        "getAdminWebTenantReportExportJobs",
        "createAdminWebTenantReportExportJob",
        "downloadAdminWebTenantReportExportJob",
        "AdminWebTenantReportDownloadFile",
        "getAdminWebTenantApiKeys",
        "createAdminWebTenantApiKey",
        "revokeAdminWebTenantApiKey",
        "getAdminWebTenantSubscriptionDashboard",
        "createAdminWebTenantSubscriptionRenewalOrder",
        "AdminWebCreateTenantSubscriptionRenewalOrderPayload",
        "AdminWebTenantSubscriptionRenewalOrder",
        "getAdminWebTenantFinanceDashboard",
        "getAdminWebPlatformWithdrawal",
        "grantAdminWebPlatformTenantSubscriptionDays",
        "setAdminWebPlatformTenantSubscriptionPeriodEnd",
        "AdminWebPlatformTenantSubscriptionAdjustment",
        "createAdminWebTenantWithdrawal",
        "AdminWebCreateTenantWithdrawalPayload",
        "AdminWebTenantWithdrawal",
        "getAdminWebTenantPaymentConfigs",
        "getAdminWebBusinessPluginCapabilities",
        "AdminWebBusinessPluginCapability",
        "AdminWebBusinessPluginCapabilitiesResponse",
        "getAdminWebExternalSourceConnections",
        "createAdminWebExternalSourceConnection",
        "disableAdminWebExternalSourceConnection",
        "syncAdminWebExternalCatalog",
        "AdminWebExternalSourceConnectionsResponse",
        "AdminWebExternalSourceConnection",
        "AdminWebCreateExternalSourceConnectionPayload",
        "AdminWebSyncExternalCatalogPayload",
        "AdminWebExternalCatalogSyncResponse",
        "AdminWebSyncedExternalCatalogProduct",
        "赠送 30 天",
        "设置到期",
        "提现详情",
        "正在加载提现详情",
        "外部源连接",
        "创建连接",
        "停用连接",
        "同步目录",
        "credential_field_count",
        "connection_handle",
        "parseExternalSourceCredentials",
        "updateAdminWebTenantPaymentConfig",
        "disableAdminWebTenantPaymentConfig",
        "getAdminWebSupplyDashboard",
        "AdminWebSupplyDashboardFilters",
        "createAdminWebSupplyApplication",
        "createAdminWebResellerProduct",
        "updateAdminWebResellerProductMetadata",
        "updateAdminWebResellerProductSales",
        "AdminWebResellerProductMetadataPayload",
        "AdminWebResellerProductSalesPayload",
        "reviewAdminWebSupplierApplication",
        "createAdminWebSupplierOffer",
        "updateAdminWebSupplierOfferApproval",
        "updateAdminWebSupplierRule",
        "AdminWebTenantOverview",
        "AdminWebTenantStoreSettings",
        "AdminWebTenantProduct",
        "AdminWebTenantOrder",
        "AdminWebTenantOrderDiagnostics",
        "AdminWebTenantOrderObservability",
        "AdminWebPaymentCallbackFailureObservation",
        "AdminWebPaymentCallbackRejectionObservation",
        "AdminWebExternalFulfillmentAttemptObservation",
        "AdminWebTenantRiskDashboard",
        "AdminWebTenantRiskStatusFilter",
        "AdminWebTenantReportExportJobsResponse",
        "AdminWebTenantReportStatusFilter",
        "AdminWebTenantReportTypeFilter",
        "AdminWebTenantApiKeysResponse",
        "AdminWebCreatedTenantApiKey",
        "AdminWebTenantApiKey",
        "AdminWebCreateTenantApiKeyPayload",
        "AdminWebTenantSubscriptionDashboard",
        "AdminWebTenantFinanceDashboard",
        "AdminWebSupplyDashboard",
        "AdminWebSupplyMarketOffer",
        "AdminWebSupplierRule",
        "AdminWebResellerProduct",
        "AdminWebPlatformStats",
        "AdminWebPlatformDashboardFilters",
        "AdminWebPlatformPaymentProvider",
        "AdminWebPlatformSubscriptionAttentionItem",
        "PlatformPaymentProvidersPanel",
        "支付通道观测",
        "configured_tenant_count",
        "missing_config_tenant_count",
        "subscription_attention",
        "subscriptionAttentionReasonLabel",
        "subscriptionAttentionBadgeVariant",
        "PlatformTenantSubscriptionStatusPanel",
        "租户订阅状态",
        "搜索店铺/Bot/owner",
        "上一页",
        "下一页",
        "subscriptionStatusLabel",
        "subscriptionStatusBadgeVariant",
        "CloneBotStoreSettingsForm",
        "店铺设置",
        "保存店铺设置",
        "欢迎语",
        "客服信息",
        "订单超时分钟",
        "FeatureFlagToggle",
        "店铺功能开关",
        "自营",
        "供货",
        "代理",
        "self_sale_enabled",
        "supplier_enabled",
        "reseller_enabled",
        "最近商品",
        "新建商品",
        "创建商品",
        "已创建为草稿商品",
        "商品分类",
        "商品排序",
        "商品售价",
        "商品状态",
        "ProductBatchStatusToolbar",
        "当前页全选",
        "批量上架",
        "批量下架",
        "导入库存",
        "绑定文件",
        "商品交付文件",
        "每行一条库存内容",
        "分类和排序已保存",
        "售价和状态已保存",
        "已导入",
        "最近订单",
        "订单观测",
        "OrderObservabilityPanel",
        "回调失败",
        "回调拒绝",
        "外部履约",
        "订单排障",
        "风控与售后",
        "CloneBotRiskPanel",
        "报表任务",
        "创建报表",
        "CloneBotReportExportJobsPanel",
        "download_available",
        "download_handle",
        "DownloadIcon",
        "下载报表",
        "API Key",
        "CloneBotApiKeysPanel",
        "CloneBotPluginCapabilitiesPanel",
        "插件能力",
        "动态加载",
        "远程代码",
        "真实联调",
        "production_ready",
        "staging_verified",
        "offline_only",
        "仅显示一次",
        "完整租户管理",
        "只读观测",
        "credential_handle",
        "plain_key",
        "订阅与财务",
        "续费下单",
        "打开支付页",
        "最近账单",
        "最近提现",
        "提现申请",
        "提交提现",
        "WithdrawalCreateForm",
        "diagnostics",
        "支付设置",
        "保存配置",
        "EPUSDT 网关地址",
        "易支付网关地址",
        "供应商工作台",
        "开放供货",
        "改为免审批",
        "独立代理规则",
        "保存规则",
        "通过申请",
        "拒绝",
        "代理商工作台",
        "目标克隆 Bot",
        "供货市场选品",
        "market_query",
        "market_delivery_type",
        "market_access",
        "market_min_price",
        "market_max_price",
        "market_stock",
        "market_category",
        "代理状态",
        "库存状态",
        "上架到当前 Bot",
        "申请代理",
        "保存展示/售价",
        "保存分类/排序",
        "代理商品分类",
        "代理商品排序",
        "sale_price",
        "display_name",
        "supplier_rule_id",
        "EPUSDT / 易支付兼容",
        "一次性绑定码",
        'credentials: "include"',
        "供应商入口",
        "代理商入口",
    ]
    missing.extend(
        f"web/admin:{marker}"
        for marker in required_frontend_markers
        if marker not in (frontend_package + frontend_shell + frontend_api)
    )
    required_openapi_markers = [
        "test_admin_web_tenant_overview_uses_cookie_session_without_api_key_security",
        "test_admin_web_tenant_products_and_orders_use_cookie_session_without_api_key_security",
        "test_admin_web_tenant_settings_patch_uses_cookie_session_and_safe_schema",
        "test_admin_web_tenant_order_diagnostics_uses_cookie_session_without_api_key_security",
        "test_admin_web_tenant_order_diagnostics_schema_exposes_safe_fields_only",
        "test_admin_web_tenant_order_observability_uses_cookie_session_without_api_key_security",
        "test_admin_web_tenant_order_observability_schema_exposes_safe_fields_only",
        "test_admin_web_tenant_subscription_and_finance_use_cookie_session_without_api_key_security",
        "test_admin_web_tenant_subscription_and_finance_schemas_expose_safe_fields_only",
        "test_admin_web_tenant_subscription_renewal_order_uses_cookie_session_and_safe_schema",
        "test_admin_web_tenant_withdrawal_create_uses_cookie_session_and_safe_schema",
        "test_admin_web_tenant_report_export_jobs_use_cookie_session_and_safe_schema",
        "test_admin_web_tenant_report_export_download_uses_cookie_session_origin_and_handle_only_schema",
        "test_admin_web_tenant_api_keys_use_cookie_session_and_safe_schema",
        "test_admin_web_tenant_product_metadata_uses_cookie_session_and_safe_schema",
        "test_admin_web_tenant_product_create_uses_cookie_session_and_safe_schema",
        "test_admin_web_tenant_product_price_status_uses_cookie_session_and_safe_schema",
        "test_admin_web_tenant_product_batch_status_uses_cookie_session_and_safe_schema",
        "test_admin_web_tenant_product_inventory_import_uses_cookie_session_and_safe_schema",
        "test_admin_web_tenant_product_delivery_file_upload_uses_cookie_session_and_safe_schema",
        "test_admin_web_tenant_payment_config_routes_use_cookie_session_without_api_key_security",
        "test_admin_web_tenant_payment_config_schema_exposes_safe_fields_only",
        "test_admin_web_business_plugin_capabilities_uses_cookie_session_and_safe_schema",
        "test_admin_web_platform_dashboard_exposes_subscription_status_counts_safely",
        "test_admin_web_platform_bot_status_uses_cookie_session_origin_and_safe_schema",
        "test_admin_web_platform_bot_webhook_reset_uses_cookie_session_origin_and_safe_schema",
        "test_admin_web_platform_withdrawal_detail_uses_cookie_session_and_safe_schema",
        "test_admin_web_platform_subscription_plan_update_uses_cookie_session_origin_and_safe_schema",
        "test_admin_web_platform_supplier_offer_status_uses_cookie_session_origin_and_safe_schema",
        "test_admin_web_remaining_platform_write_operations_use_safe_schemas",
        "test_admin_web_reseller_product_sales_schema_exposes_safe_fields_only",
        "AdminWebPlatformPaymentProviderItemResponse",
        "AdminWebPlatformSubscriptionAttentionItemResponse",
        "AdminWebPlatformBotWebhookResetResponse",
        "payment_providers",
        "subscription_attention",
        "/api/v1/admin-web/business-plugins/capabilities",
        "AdminWebBusinessPluginCapabilityItemResponse",
        "AdminWebBusinessPluginCapabilitiesResponse",
        "test_admin_web_external_source_connections_use_cookie_session_and_safe_schema",
        "test_admin_web_external_source_catalog_sync_uses_cookie_session_origin_and_handle_only_schema",
        "test_admin_web_external_source_catalog_products_uses_cookie_session_and_safe_schema",
        "/api/v1/admin-web/tenant/external-source-connections",
        "/api/v1/admin-web/tenant/external-source-connections/disable",
        "/api/v1/admin-web/tenant/external-sources/catalog/sync",
        "/api/v1/admin-web/tenant/external-sources/catalog/products",
        "AdminWebExternalSourceConnectionItemResponse",
        "AdminWebExternalSourceConnectionsResponse",
        "AdminWebExternalCatalogSyncRequest",
        "AdminWebExternalCatalogSyncResponse",
        "AdminWebSyncedExternalCatalogProductResponse",
        "AdminWebExternalSourceCatalogProductItemResponse",
        "AdminWebExternalSourceCatalogProductsResponse",
        "test_admin_web_tenant_supply_routes_use_cookie_session_without_api_key_security",
        "test_admin_web_tenant_supply_dashboard_filter_params_are_cookie_scoped_query_only",
        "test_admin_web_supply_market_offer_schema_exposes_safe_fields_only",
        "/api/v1/admin-web/tenant/overview",
        "/api/v1/admin-web/tenant/settings",
        "/api/v1/admin-web/tenant/products",
        "/api/v1/admin-web/tenant/products/{product_id}/metadata",
        "/api/v1/admin-web/tenant/products/{product_id}/sales",
        "/api/v1/admin-web/tenant/products/status",
        "/api/v1/admin-web/tenant/products/{product_id}/inventory/import",
        "/api/v1/admin-web/tenant/products/{product_id}/delivery-file",
        "/api/v1/admin-web/tenant/orders",
        "/api/v1/admin-web/tenant/orders/observability",
        "/api/v1/admin-web/tenant/orders/{out_trade_no}/diagnostics",
        "/api/v1/admin-web/tenant/subscription",
        "/api/v1/admin-web/tenant/subscription/renewal-orders",
        "/api/v1/admin-web/tenant/finance",
        "/api/v1/admin-web/tenant/finance/withdrawals",
        "/api/v1/admin-web/tenant/reports/export-jobs",
        "/api/v1/admin-web/tenant/reports/export-jobs/download",
        "/api/v1/admin-web/tenant/api-keys",
        "/api/v1/admin-web/tenant/api-keys/revoke",
        "/api/v1/admin-web/tenant/payments/configs",
        "/api/v1/admin-web/tenant/payments/{provider_name}/config",
        "/api/v1/admin-web/tenant/supply/dashboard",
        "market_query",
        "market_delivery_type",
        "market_access",
        "market_min_price",
        "market_max_price",
        "market_stock",
        "market_category",
        "/api/v1/admin-web/tenant/supply/applications",
        "/api/v1/admin-web/tenant/supply/supplier-offers",
        "/api/v1/admin-web/tenant/supply/supplier-offers/{supplier_offer_id}/approval",
        "/api/v1/admin-web/tenant/supply/supplier-rules",
        "/api/v1/admin-web/tenant/supply/supplier-applications/review",
        "/api/v1/admin-web/tenant/supply/reseller-products",
        "/api/v1/admin-web/tenant/supply/reseller-products/{reseller_product_id}/metadata",
        "/api/v1/admin-web/tenant/supply/reseller-products/{reseller_product_id}/sales",
        "AdminWebProductMetadataRequest",
        "AdminWebTenantStoreSettingsRequest",
        "AdminWebTenantStoreSettingsResponse",
        "self_sale_enabled",
        "supplier_enabled",
        "reseller_enabled",
        "AdminWebResellerProductMetadataRequest",
        "AdminWebResellerProductSalesRequest",
        "AdminWebProductCreateRequest",
        "AdminWebProductSalesRequest",
        "AdminWebProductBatchStatusRequest",
        "AdminWebTenantProductBatchStatusResponse",
        "AdminWebProductInventoryImportRequest",
        "AdminWebProductInventoryImportResponse",
        "AdminWebProductDeliveryFileResponse",
        "AdminWebTenantProductItemResponse",
        "AdminWebTenantOrderDiagnosticsResponse",
        "AdminWebTenantOrderObservabilityResponse",
        "AdminWebPaymentCallbackFailureItemResponse",
        "AdminWebPaymentCallbackRejectionItemResponse",
        "AdminWebExternalFulfillmentAttemptItemResponse",
        "AdminWebTenantSubscriptionDashboardResponse",
        "AdminWebSubscriptionRenewalOrderRequest",
        "AdminWebSubscriptionRenewalOrderResponse",
        "AdminWebTenantFinanceDashboardResponse",
        "AdminWebWithdrawalRequest",
        "AdminWebTenantWithdrawalItemResponse",
        "AdminWebReportExportJobCreateRequest",
        "AdminWebReportExportJobDownloadRequest",
        "AdminWebTenantReportExportJobsResponse",
        "AdminWebTenantReportExportJobItemResponse",
        "download_handle",
        "AdminWebTenantApiKeyCreateRequest",
        "AdminWebTenantApiKeyRevokeRequest",
        "AdminWebTenantApiKeysResponse",
        "AdminWebTenantApiKeyItemResponse",
        "AdminWebCreatedTenantApiKeyResponse",
        "AdminWebTenantApiKeyRevokeResponse",
        "AdminWebPaymentConfigRequest",
        "AdminWebTenantPaymentProviderConfigsResponse",
        "AdminWebTenantPaymentProviderConfigItemResponse",
        "merchant_id_masked",
        "key_configured",
        "additionalProperties",
        "category",
        "sort_order",
        "payment_available",
        "payment_provider",
        "payment_failure_reason",
        "address_masked",
        "TenantAdminApiKeyHeader",
        "order_id",
        "payment_id",
        "callback_id",
        "delivery_record_id",
        "payment_url",
        "provider_trade_no",
        "payload",
        "raw_payload",
        "content_encrypted",
        "content_hash",
        "inventory_item_id",
    ]
    missing.extend(
        f"tests/test_openapi_security_contract.py:{marker}"
        for marker in required_openapi_markers
        if marker not in openapi_tests
    )
    required_doc_markers = [
        "后端已新增 `admin-web` 会话、工作区和克隆 Bot 概览/店铺设置/商品/订单/订阅/财务/报表任务/支付配置/供货代理 BFF",
        "已创建 `web/admin`",
        "httpOnly 管理会话 cookie",
        "一次性绑定码",
        "`/admin_web_code`",
        "`GET /api/v1/admin-web/tenant/overview`",
        "`GET /api/v1/admin-web/tenant/settings`",
        "`PATCH /api/v1/admin-web/tenant/settings`",
        "`GET /api/v1/admin-web/tenant/products`",
        "`POST /api/v1/admin-web/tenant/products`",
        "`PATCH /api/v1/admin-web/tenant/products/{product_id}/metadata`",
        "`PATCH /api/v1/admin-web/tenant/products/{product_id}/sales`",
        "`PATCH /api/v1/admin-web/tenant/products/status`",
        "`POST /api/v1/admin-web/tenant/products/{product_id}/inventory/import`",
        "`GET /api/v1/admin-web/tenant/orders`",
        "`GET /api/v1/admin-web/tenant/orders/observability`",
        "`GET /api/v1/admin-web/tenant/orders/{out_trade_no}/diagnostics`",
        "`GET /api/v1/admin-web/tenant/risk`",
        "`GET /api/v1/admin-web/tenant/subscription`",
        "`POST /api/v1/admin-web/tenant/subscription/renewal-orders`",
        "`GET /api/v1/admin-web/tenant/finance`",
        "`POST /api/v1/admin-web/tenant/finance/withdrawals`",
        "`GET /api/v1/admin-web/tenant/reports/export-jobs`",
        "`POST /api/v1/admin-web/tenant/reports/export-jobs`",
        "`POST /api/v1/admin-web/tenant/reports/export-jobs/download`",
        "`GET /api/v1/admin-web/tenant/api-keys`",
        "`POST /api/v1/admin-web/tenant/api-keys`",
        "`POST /api/v1/admin-web/tenant/api-keys/revoke`",
        "`GET /api/v1/admin-web/tenant/payments/configs`",
        "`PUT /api/v1/admin-web/tenant/payments/{provider_name}/config`",
        "`DELETE /api/v1/admin-web/tenant/payments/{provider_name}/config`",
        "`GET /api/v1/admin-web/business-plugins/capabilities`",
        "`GET /api/v1/admin-web/tenant/supply/dashboard`",
        "`POST /api/v1/admin-web/tenant/supply/applications`",
        "`POST /api/v1/admin-web/tenant/supply/supplier-offers`",
        "`PATCH /api/v1/admin-web/tenant/supply/supplier-offers/{supplier_offer_id}/approval`",
        "`POST /api/v1/admin-web/tenant/supply/supplier-rules`",
        "`POST /api/v1/admin-web/tenant/supply/supplier-applications/review`",
        "`POST /api/v1/admin-web/tenant/supply/reseller-products`",
        "`PATCH /api/v1/admin-web/tenant/supply/reseller-products/{reseller_product_id}/metadata`",
        "`PATCH /api/v1/admin-web/tenant/supply/reseller-products/{reseller_product_id}/sales`",
        "Admin Web 店铺设置合同",
        "`self_sale_enabled`",
        "`supplier_enabled`",
        "`reseller_enabled`",
        "同步租户布尔列和 `tenant_settings.feature_flags`",
        "不允许浏览器直接提交原始 `feature_flags` 或 `clone_enabled`",
        "功能开关业务防线",
        "Public Store、租户 Bot 和订单服务",
        "代理商工作台已接入 Web 供货市场选品",
        "目标克隆 Bot",
        "供应商工作台已接入待审代理申请通过/拒绝",
        "供应商供货商品创建和审批开关已接入",
        "供应商独立代理规则已接入",
        "供货市场支持名称/分类/发货类型/代理状态/价格区间/库存状态筛选",
        "筛选只从 cookie 当前工作区解析目标克隆 Bot",
        "不接受或返回 `tenant_id`、底层商品、库存项或凭据",
        "Admin Web 商品元数据编辑合同",
        "Admin Web 代理商品元数据编辑合同",
        "Admin Web 代理商品销售字段编辑合同",
        "已上架代理商品展示名/售价/分类/排序编辑",
        "Admin Web 商品创建合同",
        "Admin Web 商品价格/状态编辑合同",
        "Admin Web 自营库存导入合同",
        "Admin Web 文件商品绑定合同",
        "Admin Web 续费下单合同",
        "Admin Web 提现申请合同",
        "Admin Web 报表任务合同",
        "download_handle",
        "只代理已完成且当前租户可下载的报表文件",
        "下载文件名使用泛化名称",
        "不返回 `export_job_id`、`tenant_id`、`requested_by_user_id`、`filename`、`download_url`、`download_token`、`storage_key`",
        "Admin Web API Key 管理合同",
        "明文 Key 只在创建响应中返回一次",
        "列表和吊销使用签名 `credential_handle`",
        "不返回 `api_key_id`、`tenant_id`、`key_hash`、`created_by_user_id`",
        "Admin Web 订单排障详情",
        "Admin Web 订单观测 BFF",
        "Admin Web 平台租户订阅状态观测",
        "Admin Web 平台支付通道观测",
        "payment_providers",
        "configured_tenant_count",
        "missing_config_tenant_count",
        "trial_subscription_count",
        "retention_expired_subscription_count",
        "支付回调失败",
        "外部履约 attempts",
        "Admin Web 风控/售后只读 BFF",
        "风控/售后只读面板",
        "不返回 `tenant_id`、`dispute_id`、`case_id`、`order_id`、`refund_id`",
        "备注中出现 URL 或敏感标记时返回",
        "Admin Web 订阅只读面板",
        "Admin Web 财务面板",
        "Admin Web 平台 Bot Webhook 重置",
        "Admin Web 平台租户/Bot 列表服务端分页筛选",
        "Admin Web 平台订阅计划编辑",
        "Admin Web 平台 Bot 状态和平台供货商品状态写操作",
        "不调用真实 Telegram",
        "不删除商品、不触发真实分账",
        "前端显示“订单排障”",
        "前端显示“订单观测”",
        "cookie 当前工作区",
        "Origin 门禁",
        "只支持 `card_pool` / `card_fixed` 自营文本库存",
        "不返回库存明文、密文、hash、storage key 或库存项 ID",
        "只接收浏览器上传的 `file`",
        "低/中风险扫描通过后绑定商品文件，高风险扫描不绑定",
        "不返回 `storage_key`、`delivery_file_id`、`uploaded_file_id`、`sha256`、文件内容或压缩包条目",
        "请求仅允许 `months`",
        "支付配置暂不可用或建链失败时保留续费订单",
        "除新建订单付款所需 `payment_url` 外，不返回内部 ID、上游流水、payload 或凭据",
        "提现申请只创建待审核记录并冻结可用余额",
        "不触发真实打款",
        "响应只返回脱敏地址、金额、币种、网络、状态和时间字段",
        "不触发外部同步",
        "不改库存",
        "不暴露外部凭据",
        "Admin Web 支付配置 BFF",
        "Admin Web 插件能力摘要只读 BFF",
        "Admin Web 外部源连接管理合同",
        "Admin Web 外部源目录同步合同",
        "Admin Web 外部源已同步商品列表",
        "`GET /api/v1/admin-web/tenant/external-source-connections`",
        "`POST /api/v1/admin-web/tenant/external-source-connections`",
        "`POST /api/v1/admin-web/tenant/external-source-connections/disable`",
        "`POST /api/v1/admin-web/tenant/external-sources/catalog/sync`",
        "`GET /api/v1/admin-web/tenant/external-sources/catalog/products`",
        "`connection_handle`",
        "请求仅允许 `connection_handle`、`cursor`、`limit`、`max_pages`",
        "请求仅允许 `connection_handle`、`limit`、`offset`",
        "从 cookie 当前工作区和签名 `connection_handle` 解析租户",
        "只读取已同步落库的本地商品摘要",
        "不返回 `tenant_id`、`connection_id`、`external_id`、`raw_payload`、`credentials`、`token`、`secret`、`storage_key`",
        "不读取或解密外部源凭据",
        "不调用 provider 目录/下单/发货方法",
        "不触发真实上游联调",
        "不执行插件 entrypoint",
        "不导入远程代码",
        "不读取或解密外部源凭据",
        "不读取或暴露 Tenant Admin API Key",
        "不要求 HMAC 签名",
        "不返回内部 ID、完整提现地址、账本流水、payment_url、上游流水或 raw payload",
        "不返回支付密钥、密文、完整收款地址、支付链接、上游流水或 raw payload",
        "不调用真实支付网关，不做保存时连通性测试",
        "调用 Telegram setWebhook",
        "不返回 Bot Token、Webhook secret 或 raw payload",
    ]
    docs_combined = docs_plan + docs_roadmap
    missing.extend(
        f"docs:{marker}"
        for marker in required_doc_markers
        if marker not in docs_combined
    )
    if "application.include_router(create_admin_web_router(settings))" not in main_py:
        missing.append("app/main.py:application.include_router(create_admin_web_router(settings))")
    if missing:
        return ReadinessCheck("admin_web_contract", FAIL, f"missing markers: {', '.join(missing)}")
    return ReadinessCheck(
        "admin_web_contract",
        PASS,
        "Admin Web has session/workspace routes, Telegram initData login, one-time binding-code session exchange, tenant overview/products/orders/order diagnostics/risk/supply BFF, feature-flag business guards, reseller marketplace apply/listing UI bound to current clone Bot, httpOnly cookie, Origin gate, tenant-member workspace isolation, safety tests, docs and shadcn frontend markers",
    )


def _check_health_worker_readiness(project_root: Path) -> ReadinessCheck:
    health = _read_optional(project_root / "app" / "web" / "health.py")
    required_markers = [
        "workers_enabled",
        "worker_manager",
        "is_ready",
        "worker_unavailable",
    ]
    missing = [marker for marker in required_markers if marker not in health]
    if missing:
        return ReadinessCheck("health_worker_readiness_contract", FAIL, f"missing markers: {', '.join(missing)}")
    return ReadinessCheck(
        "health_worker_readiness_contract",
        PASS,
        "/ready checks worker manager readiness when workers are enabled",
    )


def _check_background_worker_scheduler(project_root: Path) -> ReadinessCheck:
    scheduler = _read_optional(project_root / "app" / "workers" / "scheduler.py")
    required_markers = [
        "process_paid_external_orders_once",
        "dispatch_pending_deliveries_once",
        'name="external_fulfillment"',
        "external_fulfillment_interval_seconds",
        "runner=self._process_paid_external_orders",
        "async def _process_paid_external_orders",
        'name="delivery_dispatch"',
        "delivery_dispatch_interval_seconds",
        "runner=self._dispatch_pending_deliveries",
        "async def _dispatch_pending_deliveries",
        "worker_batch_limit",
        "def is_ready",
        "workers_enabled",
        "not task.done()",
    ]
    missing = [marker for marker in required_markers if marker not in scheduler]
    if missing:
        return ReadinessCheck(
            "background_worker_scheduler_contract",
            FAIL,
            f"missing markers: {', '.join(missing)}",
        )
    return ReadinessCheck(
        "background_worker_scheduler_contract",
        PASS,
        "external fulfillment and delivery dispatch workers are scheduled with batch limits and task readiness",
    )


def _check_file_inspection_contract(project_root: Path) -> ReadinessCheck:
    service_path = project_root / "app" / "services" / "file_inspection.py"
    tests_path = project_root / "tests" / "test_file_inspection.py"
    service = _read_optional(service_path)
    tests = _read_optional(tests_path)
    missing: list[str] = []
    service_markers = [
        "MAX_OPAQUE_ARCHIVE_BYTES",
        "MIN_OPAQUE_ARCHIVE_BYTES",
        "_inspect_opaque_archive",
        "_opaque_archive_outer_name_is_sensitive",
        "rar_oversized",
        "7z_oversized",
        "rar_too_small",
        "7z_too_small",
        "文件头和大小校验通过",
    ]
    if not service_path.is_file():
        missing.append("app/services/file_inspection.py")
    missing.extend(f"app/services/file_inspection.py:{marker}" for marker in service_markers if marker not in service)
    test_markers = [
        "test_rar_and_7z_shell_scan_blocks_too_small_magic_only_files",
        "test_rar_and_7z_shell_scan_blocks_sensitive_outer_names",
        "test_rar_and_7z_oversized_files_are_blocked_without_deep_extracting",
        "test_rar_and_7z_medium_risk_message_states_only_header_and_size_check",
    ]
    if not tests_path.is_file():
        missing.append("tests/test_file_inspection.py")
    missing.extend(f"tests/test_file_inspection.py:{marker}" for marker in test_markers if marker not in tests)
    if missing:
        return ReadinessCheck("file_inspection_contract", FAIL, f"missing markers: {', '.join(missing)}")
    return ReadinessCheck(
        "file_inspection_contract",
        PASS,
        "RAR/7Z opaque archive shell scan validates headers, size bounds, tiny magic-only files and sensitive outer names while deep entry scanning remains deferred",
    )


def _check_tenant_admin_product_metadata_contract(project_root: Path) -> ReadinessCheck:
    tenant_admin_path = project_root / "app" / "web" / "tenant_admin.py"
    product_repo_path = project_root / "app" / "db" / "repos" / "products.py"
    openapi_tests_path = project_root / "tests" / "test_openapi_security_contract.py"
    readiness_tests_path = project_root / "tests" / "test_staging_readiness.py"
    roadmap_path = project_root / "docs" / "实施路线图.md"
    handoff_path = project_root / "docs" / "开发交接说明.md"
    database_design_path = project_root / "docs" / "数据库设计.md"

    tenant_admin = _read_optional(tenant_admin_path)
    product_repo = _read_optional(product_repo_path)
    openapi_tests = _read_optional(openapi_tests_path)
    readiness_tests = _read_optional(readiness_tests_path)
    roadmap = _read_optional(roadmap_path)
    handoff = _read_optional(handoff_path)
    database_design = _read_optional(database_design_path)

    missing: list[str] = []
    tenant_admin_markers = [
        "UpdateProductMetadataRequest",
        '"/products/{product_id}/metadata"',
        'require_scope("products:write")',
        "sort_order",
        "category",
        "set_product_sort_order",
        "set_product_category",
    ]
    tenant_admin_response_markers = ["ProductMetadataResponse", "AdminProduct"]
    if not tenant_admin_path.is_file():
        missing.append("app/web/tenant_admin.py")
    missing.extend(
        f"app/web/tenant_admin.py:{marker}"
        for marker in tenant_admin_markers
        if marker not in tenant_admin
    )
    if not any(marker in tenant_admin for marker in tenant_admin_response_markers):
        missing.append("app/web/tenant_admin.py:ProductMetadataResponse or AdminProduct")

    repo_markers = [
        "async def set_product_sort_order",
        "async def set_product_category",
        "Product.tenant_id == tenant_id",
        'Product.status != "deleted"',
        "await session.flush()",
    ]
    if not product_repo_path.is_file():
        missing.append("app/db/repos/products.py")
    missing.extend(
        f"app/db/repos/products.py:{marker}"
        for marker in repo_markers
        if marker not in product_repo
    )

    openapi_test_markers = [
        "test_product_metadata_update_operation_is_documented_as_tenant_admin",
        "/api/v1/tenant/products/{product_id}/metadata",
        "UpdateProductMetadataRequest",
        "ProductMetadataResponse",
        "AdminProduct",
        "sort_order",
        "category",
        "additionalProperties",
        "credentials",
        "raw_payload",
        "token",
        "secret",
    ]
    if not openapi_tests_path.is_file():
        missing.append("tests/test_openapi_security_contract.py")
    missing.extend(
        f"tests/test_openapi_security_contract.py:{marker}"
        for marker in openapi_test_markers
        if marker not in openapi_tests
    )

    readiness_test_markers = [
        "test_tenant_admin_product_metadata_contract_requires_route_scope_safe_schema_and_docs",
        "UpdateProductMetadataRequest",
        "/api/v1/tenant/products/{product_id}/metadata",
        'require_scope("products:write")',
        "set_product_sort_order",
        "set_product_category",
    ]
    if not readiness_tests_path.is_file():
        missing.append("tests/test_staging_readiness.py")
    missing.extend(
        f"tests/test_staging_readiness.py:{marker}"
        for marker in readiness_test_markers
        if marker not in readiness_tests
    )

    document_markers = {
        roadmap_path: [
            "Tenant Admin 商品元数据更新合同",
            "`/api/v1/tenant/products/{product_id}/metadata`",
            "`products:write`",
            "`sort_order`",
            "`category`",
            "不触发外部同步",
            "不改库存",
            "不暴露外部凭据",
        ],
        handoff_path: [
            "Tenant Admin 商品元数据更新合同",
            "`/api/v1/tenant/products/{product_id}/metadata`",
            "`products:write`",
            "`sort_order`",
            "`category`",
            "不触发外部同步",
            "不改库存",
            "不暴露外部凭据",
        ],
        database_design_path: [
            "Tenant Admin 商品元数据更新合同",
            "`sort_order`",
            "`category`",
            "`set_product_sort_order`",
            "`set_product_category`",
            "租户内商品排序/分类管理",
            "不触发外部同步",
            "不改库存",
            "不暴露外部凭据",
        ],
    }
    document_texts = {
        roadmap_path: roadmap,
        handoff_path: handoff,
        database_design_path: database_design,
    }
    for path, markers in document_markers.items():
        if not path.is_file():
            missing.append(str(path.relative_to(project_root)))
        missing.extend(
            f"{path.relative_to(project_root)}:{marker}"
            for marker in markers
            if marker not in document_texts[path]
        )

    if missing:
        return ReadinessCheck(
            "tenant_admin_product_metadata_contract",
            FAIL,
            f"missing markers: {', '.join(missing)}",
        )
    return ReadinessCheck(
        "tenant_admin_product_metadata_contract",
        PASS,
        "Tenant Admin product metadata update is products:write scoped, tenant-scoped and limited to local sort_order/category management without external sync, inventory mutation or credential exposure",
    )


def _check_external_auto_fulfillment_safety_contract(project_root: Path) -> ReadinessCheck:
    service = _read_optional(project_root / "app" / "services" / "external_sources" / "auto_fulfillment.py")
    attempts_service = _read_optional(project_root / "app" / "services" / "external_sources" / "attempts.py")
    external_models = _read_optional(project_root / "app" / "db" / "models" / "external_sources.py")
    attempt_migration = _read_optional(
        project_root / "alembic" / "versions" / "20260606_0021_create_external_fulfillment_attempts.py"
    )
    attempt_lifecycle_migration_paths = sorted(
        (project_root / "alembic" / "versions").glob("20260609_0022*.py")
    )
    attempt_lifecycle_migration = "\n".join(_read_optional(path) for path in attempt_lifecycle_migration_paths)
    failure_log_service = _read_optional(project_root / "app" / "services" / "external_sources" / "failures.py")
    registry = _read_optional(project_root / "app" / "services" / "external_sources" / "registry.py")
    tenant_admin = _read_optional(project_root / "app" / "web" / "tenant_admin.py")
    tests_path = project_root / "tests" / "test_external_auto_fulfillment_service.py"
    tests = _read_optional(tests_path)
    failure_log_tests_path = project_root / "tests" / "test_external_fulfillment_failures.py"
    failure_log_tests = _read_optional(failure_log_tests_path)
    attempt_log_tests_path = project_root / "tests" / "test_external_fulfillment_attempts.py"
    attempt_log_tests = _read_optional(attempt_log_tests_path)
    registry_tests_path = project_root / "tests" / "test_external_provider_registry.py"
    registry_tests = _read_optional(registry_tests_path)
    openapi_tests_path = project_root / "tests" / "test_openapi_security_contract.py"
    openapi_tests = _read_optional(openapi_tests_path)
    tenant_admin_contract_tests_path = project_root / "tests" / "test_tenant_admin_api_keys_contract.py"
    tenant_admin_contract_tests = _read_optional(tenant_admin_contract_tests_path)
    tenant_admin_external_order_tests_path = project_root / "tests" / "test_tenant_admin_external_order_operations.py"
    tenant_admin_external_order_tests = _read_optional(tenant_admin_external_order_tests_path)
    external_delivery_import_tests_path = project_root / "tests" / "test_external_delivery_import_service.py"
    external_delivery_import_tests = _read_optional(external_delivery_import_tests_path)
    external_fulfillment_smoke_tests_path = project_root / "tests" / "test_smoke_e2e_external_fulfillment.py"
    external_fulfillment_smoke_tests = _read_optional(external_fulfillment_smoke_tests_path)
    required_markers = [
        "ExternalAutoFulfillmentError",
        "ExternalAutoFulfillmentAttemptResult",
        "fulfill_tenant_paid_order",
        "status_code",
        "category",
        "retryable",
        "is_provider_auto_fulfillment_available",
        "provider_capability",
        "auto_fulfillment_not_enabled",
        "credentials_load_failed",
        "runtime_auth is None",
        "connection_missing",
        "target_id=str(order.id)",
        "out_trade_no",
        "external_product_id",
        "connection_id",
        "external_order_id",
        "failure_fingerprint",
        "external_fulfillment.failed",
        "_has_same_latest_failure_fingerprint",
        "ExternalFulfillmentAttempt",
        "EXTERNAL_FULFILLMENT_ATTEMPT_STATUSES",
        "attempt_source: str = \"auto\"",
        "_add_attempt_record",
        "_normalize_attempt_source",
        "attempt_source=\"manual\"",
        "attempt_source=\"auto\"",
        '"started"',
        '"running"',
        '"succeeded"',
        "status=\"already_delivered\"",
        "status=\"failed\"",
        "status=\"succeeded\"",
        "delivery_record_id=existing_delivery.id",
        "attempt.failure_reason = _safe_attempt_failure_reason",
        "attempt.failure_fingerprint =",
        "upstream_status_code=_safe_optional_status_code",
        "started_at=now",
        "finished_at=now",
        "delivery_record_id",
        "auto=False",
        '"manual"',
        "return False",
        "with_for_update(of=Order, skip_locked=True)",
        "with_for_update(of=Order)",
        "load_credentials",
        "create_order",
        "fetch_delivery",
        "delivery_pending",
        "import_delivery",
        "seen_order_ids",
    ]
    missing = [marker for marker in required_markers if marker not in service]
    status_update_helpers = [
        "_mark_attempt_record",
        "_update_attempt_record_status",
        "_set_attempt_record_status",
    ]
    if not any(marker in service for marker in status_update_helpers):
        missing.append("app/services/external_sources/auto_fulfillment.py:_mark_attempt_record or equivalent status update helper")
    attempt_model_markers = [
        "ExternalFulfillmentAttempt",
        "__tablename__ = \"external_fulfillment_attempts\"",
        "ck_external_fulfillment_attempts_attempt_source",
        "ck_external_fulfillment_attempts_status",
        "ck_external_fulfillment_attempts_item_count_nonnegative",
        "ck_external_fulfillment_attempts_upstream_status_code",
        "attempt_source",
        "status",
        "imported",
        "'started'",
        "'running'",
        "'succeeded'",
        "'already_delivered'",
        "'failed'",
        "item_count",
        "failure_reason",
        "failure_stage",
        "failure_category",
        "failure_retryable",
        "upstream_status_code",
        "failure_fingerprint",
        "delivery_record_id",
        "started_at",
        "finished_at",
        "ix_external_fulfillment_attempts_tenant_status_created",
        "ix_external_fulfillment_attempts_tenant_order_created",
        "ix_external_fulfillment_attempts_provider_status",
    ]
    if not (project_root / "app" / "db" / "models" / "external_sources.py").is_file():
        missing.append("app/db/models/external_sources.py")
    missing.extend(
        f"app/db/models/external_sources.py:{marker}"
        for marker in attempt_model_markers
        if marker not in external_models
    )
    attempt_migration_markers = [
        "20260606_0021",
        "down_revision: Optional[str] = \"20260606_0020\"",
        "external_fulfillment_attempts",
        "ck_external_fulfillment_attempts_attempt_source",
        "ck_external_fulfillment_attempts_status",
        "ck_external_fulfillment_attempts_item_count_nonnegative",
        "ck_external_fulfillment_attempts_upstream_status_code",
        "ix_external_fulfillment_attempts_tenant_status_created",
        "ix_external_fulfillment_attempts_tenant_order_created",
        "ix_external_fulfillment_attempts_provider_status",
        "sa.ForeignKeyConstraint([\"delivery_record_id\"], [\"delivery_records.id\"])",
    ]
    if not (
        project_root / "alembic" / "versions" / "20260606_0021_create_external_fulfillment_attempts.py"
    ).is_file():
        missing.append("alembic/versions/20260606_0021_create_external_fulfillment_attempts.py")
    missing.extend(
        f"alembic/versions/20260606_0021_create_external_fulfillment_attempts.py:{marker}"
        for marker in attempt_migration_markers
        if marker not in attempt_migration
    )
    attempt_lifecycle_migration_markers = [
        "20260609_0022",
        "down_revision: Optional[str] = \"20260606_0021\"",
        "external_fulfillment_attempts",
        "ck_external_fulfillment_attempts_status",
        "'started'",
        "'running'",
        "'succeeded'",
        "'already_delivered'",
        "'failed'",
    ]
    if not attempt_lifecycle_migration_paths:
        missing.append("alembic/versions/20260609_0022*.py")
    missing.extend(
        f"alembic/versions/20260609_0022*.py:{marker}"
        for marker in attempt_lifecycle_migration_markers
        if marker not in attempt_lifecycle_migration
    )
    attempt_log_service_markers = [
        "ExternalFulfillmentAttemptLogService",
        "ExternalFulfillmentAttemptSummary",
        "list_attempts",
        "EXTERNAL_FULFILLMENT_ATTEMPT_STATUSES",
        "ExternalFulfillmentAttempt",
        "ExternalFulfillmentAttempt.tenant_id == tenant_id",
        "ExternalFulfillmentAttempt.out_trade_no",
        "ExternalFulfillmentAttempt.provider_name",
        "ExternalFulfillmentAttempt.source_key",
        "ExternalFulfillmentAttempt.external_order_id",
        "ExternalFulfillmentAttempt.attempt_source",
        "ExternalFulfillmentAttempt.status",
        "ExternalFulfillmentAttempt.failure_retryable",
        "imported",
        "SENSITIVE_ATTEMPT_VALUE_MARKERS",
        "_safe_attempt_failure_reason",
        "_matches_filters",
    ]
    if not (project_root / "app" / "services" / "external_sources" / "attempts.py").is_file():
        missing.append("app/services/external_sources/attempts.py")
    missing.extend(
        f"app/services/external_sources/attempts.py:{marker}"
        for marker in attempt_log_service_markers
        if marker not in attempts_service
    )
    failure_log_service_markers = [
        "ExternalFulfillmentFailureLogService",
        "ExternalFulfillmentFailureSummary",
        "EXTERNAL_FULFILLMENT_FAILED_ACTION",
        "external_fulfillment.failed",
        "metadata_json",
        "provider_name",
        "source_key",
        "out_trade_no",
        "failure_stage",
        "failure_category",
        "failure_retryable",
        "failure_fingerprint",
        "metadata_json.contains",
        "SENSITIVE_FAILURE_VALUE_MARKERS",
        "_safe_failure_reason",
        "_normalize_optional_out_trade_no",
        "_normalize_optional_bool",
    ]
    if not (project_root / "app" / "services" / "external_sources" / "failures.py").is_file():
        missing.append("app/services/external_sources/failures.py")
    missing.extend(
        f"app/services/external_sources/failures.py:{marker}"
        for marker in failure_log_service_markers
        if marker not in failure_log_service
    )
    registry_markers = [
        "auto_fulfillment_idempotent_available",
        "auto_fulfillment_idempotent",
        "is True",
        "order_context_available",
        "delivery_context_available",
    ]
    if not (project_root / "app" / "services" / "external_sources" / "registry.py").is_file():
        missing.append("app/services/external_sources/registry.py")
    missing.extend(
        f"app/services/external_sources/registry.py:{marker}"
        for marker in registry_markers
        if marker not in registry
    )
    tenant_admin_markers = ["auto_fulfillment_idempotent_available"]
    tenant_admin_import_markers = [
        "ImportExternalDeliveryResponse",
        "imported: bool",
        "dry_run: bool",
        "imported=result.imported",
        "dry_run=result.dry_run",
    ]
    tenant_admin_retry_markers = [
        "RetryExternalFulfillmentResponse",
        '"/orders/{out_trade_no}/external-fulfillment/retry"',
        "retry_external_fulfillment",
        'require_scope("external_sources:write")',
        "ExternalAutoFulfillmentService",
        "fulfill_tenant_paid_order",
        "_external_fulfillment_retry_response",
        "failure_recorded",
        "attempt_status",
    ]
    tenant_admin_failure_markers = [
        "ExternalFulfillmentFailureItem",
        "ListExternalFulfillmentFailuresResponse",
        '"/external-fulfillment/failures"',
        'require_scope("external_sources:read")',
        "ExternalFulfillmentFailureLogService",
        "_external_fulfillment_failure_response",
        "failure_fingerprint",
        "out_trade_no=out_trade_no",
        "failure_retryable=failure_retryable",
    ]
    tenant_admin_attempt_markers = [
        "ExternalFulfillmentAttemptItem",
        "ListExternalFulfillmentAttemptsResponse",
        '"/external-fulfillment/attempts"',
        "list_external_fulfillment_attempts",
        'require_scope("external_sources:read")',
        "ExternalFulfillmentAttemptLogService",
        "_external_fulfillment_attempt_response",
        "external_order_id=external_order_id",
        "attempt_source=attempt_source",
        "status=status",
        "failure_retryable=failure_retryable",
        "外部履约尝试查询参数无效",
    ]
    if not (project_root / "app" / "web" / "tenant_admin.py").is_file():
        missing.append("app/web/tenant_admin.py")
    missing.extend(
        f"app/web/tenant_admin.py:{marker}"
        for marker in tenant_admin_markers
        if marker not in tenant_admin
    )
    missing.extend(
        f"app/web/tenant_admin.py:{marker}"
        for marker in tenant_admin_import_markers
        if marker not in tenant_admin
    )
    missing.extend(
        f"app/web/tenant_admin.py:{marker}"
        for marker in tenant_admin_retry_markers
        if marker not in tenant_admin
    )
    missing.extend(
        f"app/web/tenant_admin.py:{marker}"
        for marker in tenant_admin_failure_markers
        if marker not in tenant_admin
    )
    missing.extend(
        f"app/web/tenant_admin.py:{marker}"
        for marker in tenant_admin_attempt_markers
        if marker not in tenant_admin
    )
    test_markers = [
        "test_fulfill_paid_order_requires_active_runtime_connection_before_provider_call",
        "test_fulfill_paid_order_requires_provider_auto_fulfillment_opt_in_before_credential_load_or_provider_call",
        "test_process_paid_external_orders_locks_only_order_rows_on_postgresql",
        "test_process_paid_external_orders_audits_provider_without_idempotent_auto_fulfillment_opt_in",
        "test_process_paid_external_orders_audits_runtime_credentials_load_error_without_details",
        "test_process_paid_external_orders_audits_missing_runtime_connection_without_provider_call",
        "test_process_paid_external_orders_audits_http_error_classification_without_details",
        "test_process_paid_external_orders_audits_fetch_delivery_http_error_with_external_order_id",
        "test_process_paid_external_orders_audits_import_delivery_failure_without_delivery_content",
        "test_process_paid_external_orders_redacts_unclassified_value_error_reason",
        "test_failure_audit_records_external_product_id_and_connection_id_without_credentials",
        "test_failure_fingerprint_changes_when_product_or_external_mapping_changes",
        "test_delivery_pending_audit_keeps_external_order_id_as_trace_hint",
        "test_failed_audit_target_id_uses_order_id_when_out_trade_no_is_long",
        "test_registered_idempotent_provider_replay_uses_same_out_trade_no_and_local_delivery_gate",
        "test_fulfill_paid_order_transitions_attempt_to_succeeded_without_sensitive_payload",
        "test_process_paid_external_orders_records_failed_attempt_even_when_failure_audit_is_deduped",
        "test_different_failure_fingerprint_still_adds_audit",
        "test_process_paid_external_orders_skips_duplicate_order_rows_in_same_batch",
        "test_process_paid_external_orders_reuses_existing_delivery_record_when_replayed",
        "test_fulfill_tenant_paid_order_imports_single_order_with_safe_attempt_summary",
        "test_fulfill_tenant_paid_order_returns_none_for_missing_order",
        "test_fulfill_tenant_paid_order_reuses_existing_delivery_without_provider_call",
        "test_fulfill_tenant_paid_order_records_safe_manual_failure_summary",
        "test_fulfill_tenant_paid_order_repeated_same_failure_does_not_add_duplicate_audit",
    ]
    if not tests_path.is_file():
        missing.append("tests/test_external_auto_fulfillment_service.py")
    missing.extend(f"tests/test_external_auto_fulfillment_service.py:{marker}" for marker in test_markers if marker not in tests)
    failure_log_test_markers = [
        "test_list_failures_returns_safe_whitelisted_summary",
        "test_list_failures_filters_safe_metadata_values_and_redacts_sensitive_reason",
        "test_list_failures_can_filter_non_retryable_order_failure",
        "test_list_failures_rejects_invalid_filters",
        "metadata_json",
        "provider-secret",
        'failure_retryable="true"',
    ]
    if not failure_log_tests_path.is_file():
        missing.append("tests/test_external_fulfillment_failures.py")
    missing.extend(
        f"tests/test_external_fulfillment_failures.py:{marker}"
        for marker in failure_log_test_markers
        if marker not in failure_log_tests
    )
    attempt_log_test_markers = [
        "test_list_attempts_returns_safe_whitelisted_summary",
        "test_list_attempts_filters_by_status_source_order_and_retryable",
        "test_list_attempts_filters_succeeded_lifecycle_status",
        "test_list_attempts_accepts_running_lifecycle_status",
        "test_list_attempts_clamps_limit_and_keeps_tenant_filter_in_query",
        "test_list_attempts_rejects_invalid_filters_before_query",
        "test_list_attempts_redacts_sensitive_failure_reason",
        "SENSITIVE_ATTEMPT_VALUE_MARKERS",
    ]
    if not attempt_log_tests_path.is_file():
        missing.append("tests/test_external_fulfillment_attempts.py")
    missing.extend(
        f"tests/test_external_fulfillment_attempts.py:{marker}"
        for marker in attempt_log_test_markers
        if marker not in attempt_log_tests
    )
    registry_test_markers = [
        "test_auto_fulfillment_capability_defaults_to_false",
        "test_auto_fulfillment_capability_requires_idempotent_out_trade_no_opt_in_and_context_methods",
        "test_auto_fulfillment_capability_rejects_truthy_non_bool_or_legacy_provider",
    ]
    if not registry_tests_path.is_file():
        missing.append("tests/test_external_provider_registry.py")
    missing.extend(
        f"tests/test_external_provider_registry.py:{marker}"
        for marker in registry_test_markers
        if marker not in registry_tests
    )
    tenant_admin_test_markers = [
        "test_external_source_provider_list_response_exposes_auto_fulfillment_capability_without_credentials",
    ]
    if not tenant_admin_contract_tests_path.is_file():
        missing.append("tests/test_tenant_admin_api_keys_contract.py")
    missing.extend(
        f"tests/test_tenant_admin_api_keys_contract.py:{marker}"
        for marker in tenant_admin_test_markers
        if marker not in tenant_admin_contract_tests
    )
    tenant_admin_external_order_test_markers = [
        "test_import_external_delivery_dry_run_exposes_validation_result_without_sensitive_delivery",
        "test_import_external_delivery_existing_record_response_exposes_reuse_flags",
        "test_list_external_fulfillment_attempts_requires_external_sources_read_scope",
        "test_list_external_fulfillment_attempts_returns_safe_tenant_scoped_attempts_without_sensitive_payload",
        "test_list_external_fulfillment_attempts_invalid_filter_returns_generic_error",
        "test_retry_external_fulfillment_requires_write_scope_before_service",
        "test_retry_external_fulfillment_returns_safe_success_summary_without_delivery_content",
        "test_retry_external_fulfillment_returns_safe_failed_summary_without_upstream_detail",
        "test_retry_external_fulfillment_returns_404_for_missing_order",
        "test_retry_external_fulfillment_error_response_is_generic_without_sensitive_detail",
        "test_list_external_fulfillment_failures_requires_external_sources_read_scope",
        "test_list_external_fulfillment_failures_returns_safe_audit_metadata_without_credentials",
    ]
    if not tenant_admin_external_order_tests_path.is_file():
        missing.append("tests/test_tenant_admin_external_order_operations.py")
    missing.extend(
        f"tests/test_tenant_admin_external_order_operations.py:{marker}"
        for marker in tenant_admin_external_order_test_markers
        if marker not in tenant_admin_external_order_tests
    )
    external_delivery_import_test_markers = [
        "test_import_delivery_dry_run_reuses_existing_delivery_record_without_writing",
        "test_import_delivery_existing_record_rejects_mismatched_external_mapping",
        "test_import_delivery_dry_run_rejects_invalid_content_without_writing",
    ]
    if not external_delivery_import_tests_path.is_file():
        missing.append("tests/test_external_delivery_import_service.py")
    missing.extend(
        f"tests/test_external_delivery_import_service.py:{marker}"
        for marker in external_delivery_import_test_markers
        if marker not in external_delivery_import_tests
    )
    external_fulfillment_smoke_test_markers = [
        "test_external_mapping_order_paid_async_fulfillment_and_dispatch",
        "replay_fulfillment",
        "已有发货记录不应再次调用 provider",
    ]
    if not external_fulfillment_smoke_tests_path.is_file():
        missing.append("tests/test_smoke_e2e_external_fulfillment.py")
    missing.extend(
        f"tests/test_smoke_e2e_external_fulfillment.py:{marker}"
        for marker in external_fulfillment_smoke_test_markers
        if marker not in external_fulfillment_smoke_tests
    )
    openapi_test_markers = [
        "test_external_fulfillment_failure_schema_exposes_safe_fields_only",
        "test_external_fulfillment_attempt_schema_exposes_safe_fields_only",
        "ListExternalFulfillmentFailuresResponse",
        "ExternalFulfillmentFailureItem",
        "ListExternalFulfillmentAttemptsResponse",
        "ExternalFulfillmentAttemptItem",
        "RetryExternalFulfillmentResponse",
        "metadata_json",
        "raw_payload",
    ]
    if not openapi_tests_path.is_file():
        missing.append("tests/test_openapi_security_contract.py")
    missing.extend(
        f"tests/test_openapi_security_contract.py:{marker}"
        for marker in openapi_test_markers
        if marker not in openapi_tests
    )
    if missing:
        return ReadinessCheck(
            "external_auto_fulfillment_safety_contract",
            FAIL,
            f"missing markers: {', '.join(missing)}",
        )
    return ReadinessCheck(
        "external_auto_fulfillment_safety_contract",
        PASS,
        "external auto fulfillment has provider idempotent opt-in gate, append-only lifecycle attempt records and Tenant Admin attempt history, existing-delivery replay idempotency drill, active connection gate, Tenant Admin import, manual retry and failure observability, classified safe audits, duplicate-failure audit noise reduction, order-id audit target and batch de-dup markers; real third-party idempotency and staging remain manual WARN gates",
    )


def _check_tenant_admin_payment_config_contract(project_root: Path) -> ReadinessCheck:
    tenant_admin = _read_optional(project_root / "app" / "web" / "tenant_admin.py")
    api_keys = _read_optional(project_root / "app" / "services" / "api_keys.py")
    payment_configs = _read_optional(project_root / "app" / "services" / "payments" / "configs.py")
    trc20_direct = _read_optional(project_root / "app" / "services" / "payments" / "trc20_direct.py")
    payment_failures = _read_optional(project_root / "app" / "services" / "payments" / "failures.py")
    payment_config_tests_path = project_root / "tests" / "test_tenant_admin_payment_config.py"
    payment_config_tests = _read_optional(payment_config_tests_path)
    payment_config_service_tests_path = project_root / "tests" / "test_payment_config_service.py"
    payment_config_service_tests = _read_optional(payment_config_service_tests_path)
    trc20_direct_tests_path = project_root / "tests" / "test_trc20_direct_core.py"
    trc20_direct_tests = _read_optional(trc20_direct_tests_path)
    payment_create_tests_path = project_root / "tests" / "test_payment_create_service.py"
    payment_create_tests = _read_optional(payment_create_tests_path)
    payment_callback_failure_tests_path = project_root / "tests" / "test_payment_callback_failures.py"
    payment_callback_failure_tests = _read_optional(payment_callback_failure_tests_path)
    tenant_admin_callback_failure_tests_path = project_root / "tests" / "test_tenant_admin_payment_callback_failures.py"
    tenant_admin_callback_failure_tests = _read_optional(tenant_admin_callback_failure_tests_path)
    openapi_tests_path = project_root / "tests" / "test_openapi_security_contract.py"
    openapi_tests = _read_optional(openapi_tests_path)
    required_tenant_admin_markers = [
        "TenantEpusdtConfigResponse",
        "UpdateTenantEpusdtConfigRequest",
        "DisableTenantEpusdtConfigResponse",
        "TenantPaymentProviderConfigResponse",
        "UpdateTenantPaymentProviderConfigRequest",
        "DisableTenantPaymentProviderConfigResponse",
        "TenantPaymentProviderItem",
        "ListTenantPaymentProvidersResponse",
        "TenantPaymentCallbackFailureItem",
        "ListTenantPaymentCallbackFailuresResponse",
        "TenantPaymentCallbackRejectionItem",
        "ListTenantPaymentCallbackRejectionsResponse",
        '"/payments/epusdt/config"',
        '"/payments/providers"',
        '"/payments/callback-failures"',
        '"/payments/callback-rejections"',
        '"/payments/{provider_name}/config"',
        'require_scope("payments:read")',
        'require_scope("payments:write")',
        "PaymentConfigService",
        "TOKEN188_PROVIDER",
        "EPAY_COMPATIBLE_PROVIDER",
        "LEMZF_PROVIDER",
        "pid_masked",
        "merchant_id_masked",
        "monitor_address_masked",
        "gateway_url",
        "asset",
        "cny_per_usdt",
        "min_usdt_amount",
        "timeout_seconds",
        "key_configured",
        "integration_kind",
        "contract_name",
        "production_ready",
        "staging_verified",
        "offline_only",
        "query_order_available",
        "reconcile_available",
        "PaymentCallbackFailureLogService",
        "process_status",
        "failure_reason",
        "_normalize_epusdt_base_url",
        "normalize_epusdt_base_url",
        "validate_payment_provider_config_payload",
        'ConfigDict(extra="allow"',
        '"additionalProperties": False',
        "支付配置参数无效",
        "支付配置暂不可用",
    ]
    missing = [
        f"app/web/tenant_admin.py:{marker}"
        for marker in required_tenant_admin_markers
        if marker not in tenant_admin
    ]
    required_scope_markers = [
        '"payments:read"',
        '"payments:write"',
    ]
    missing.extend(
        f"app/services/api_keys.py:{marker}"
        for marker in required_scope_markers
        if marker not in api_keys
    )
    required_payment_config_service_markers = [
        "normalize_epusdt_base_url",
        "SUPPORTED_TENANT_PAYMENT_PROVIDERS",
        "upsert_tenant_payment_config",
        "disable_tenant_payment_config",
        "get_tenant_payment_config_status",
        "PaymentProviderSummary",
        "list_tenant_payment_provider_summaries",
        "list_payment_provider_summaries",
        "payment_provider_summary",
        "offline_only",
        "reconcile_available",
        "normalize_payment_gateway_url",
        "normalize_token188_gateway_url",
        "normalize_epay_gateway_url",
        "USDT_TRC20_DIRECT_PROVIDER",
        "Trc20DirectConfig",
        "usdt_trc20_direct",
        "usdt_trc20_direct_offline_config_v1",
        "offline_direct_chain_config",
        "TRON_BASE58_ALPHABET",
        "TRON_BASE58_CHECK_VERSION",
        "TRC20_DIRECT_CONFIG_FIELDS",
        "_decode_base58",
        "_reject_unknown_config_fields",
        "create_payment_available=True",
        "callback_available=False",
        "query_order_available=False",
        "reconcile_available=False",
        "offline_only=True",
        "supported_assets=(\"USDT\",)",
        "supported_networks=(\"TRC20\",)",
        "TENANT_DIRECT_PAYMENT_PROVIDER_PRIORITY",
        "TRON_BASE58_CHARS",
        "_reject_config_fields",
        "_normalize_tron_address",
        "_normalize_decimal_config",
        "_normalize_int_config",
        "cny_per_usdt",
        "min_usdt_amount",
        "timeout_seconds",
        "TOKEN188_PROVIDER",
        "EPAY_COMPATIBLE_PROVIDER",
        "LEMZF_PROVIDER",
        "urlsplit",
        "用户信息",
        "query",
        "fragment",
    ]
    missing.extend(
        f"app/services/payments/configs.py:{marker}"
        for marker in required_payment_config_service_markers
        if marker not in payment_configs
    )
    required_trc20_direct_markers = [
        "USDT_TRC20_CONTRACT_ADDRESS",
        "TRC20_TRANSFER_METHOD_ID",
        "TRC20_USDT_SCALE",
        "TronUsdtTransfer",
        "TronUsdtPaymentCandidate",
        "TronUsdtMatchDecision",
        "parse_tron_usdt_transfer",
        "match_tron_usdt_transfer",
        "normalize_tron_address",
        "normalize_tron_tx_hash",
        "tron_address_from_hex",
        "tron_address_to_hex",
        "trc20_usdt_amount_to_raw",
        "trc20_usdt_raw_to_decimal",
        "hashlib",
        "decode_base58",
        "TRON_BASE58_ALPHABET",
        "TRON_BASE58_CHECK_VERSION",
        "ret",
        "TriggerSmartContract",
        "contractRet",
        "SUCCESS",
        "duplicate_tx",
        "not_confirmed",
        "ambiguous",
    ]
    if not (project_root / "app" / "services" / "payments" / "trc20_direct.py").is_file():
        missing.append("app/services/payments/trc20_direct.py")
    missing.extend(
        f"app/services/payments/trc20_direct.py:{marker}"
        for marker in required_trc20_direct_markers
        if marker not in trc20_direct
    )
    required_payment_failure_service_markers = [
        "PaymentCallbackFailureSummary",
        "PaymentCallbackFailureLogService",
        "PAYMENT_CALLBACK_OBSERVABLE_STATUSES",
        "SENSITIVE_PAYMENT_FAILURE_VALUE_MARKERS",
        "Order.out_trade_no == PaymentCallback.out_trade_no",
        "Order.tenant_id == tenant_id",
        "_safe_failure_reason",
        "payload",
        "provider_trade_no",
        "signature",
        "signing_text",
    ]
    if not (project_root / "app" / "services" / "payments" / "failures.py").is_file():
        missing.append("app/services/payments/failures.py")
    missing.extend(
        f"app/services/payments/failures.py:{marker}"
        for marker in required_payment_failure_service_markers
        if marker not in payment_failures
    )
    required_payment_config_test_markers = [
        "test_get_payment_config_requires_payments_read_scope_before_service",
        "test_get_payment_config_is_tenant_scoped_and_redacted",
        "test_update_payment_config_requires_payments_write_scope_before_service",
        "test_update_payment_config_commits_and_returns_safe_payload",
        "test_update_payment_config_value_error_returns_400_and_redacts_secret",
        "test_update_payment_config_missing_crypto_key_returns_503_without_route_commit",
        "test_update_payment_config_rejects_unsafe_base_url_before_service",
        "test_disable_payment_config_requires_payments_write_scope_before_service",
        "test_disable_payment_config_commits_and_returns_safe_payload",
        "test_disable_payment_config_returns_404_for_missing_tenant_config",
        "test_get_generic_payment_config_requires_payments_read_scope_before_service",
        "test_get_generic_payment_config_is_tenant_scoped_and_redacted_for_token188",
        "test_update_token188_config_commits_and_returns_safe_payload",
        "test_update_epay_compatible_config_commits_and_returns_safe_payload",
        "test_update_lemzf_config_commits_and_returns_safe_payload",
        "test_get_trc20_direct_config_is_tenant_scoped_and_redacted",
        "test_update_trc20_direct_config_commits_and_returns_masked_address_without_key",
        "test_update_trc20_direct_config_rejects_unsupported_sensitive_fields_before_service",
        "tron_api_key",
        "test_update_payment_provider_config_rejects_unsupported_provider_before_service",
        "test_update_payment_provider_config_rejects_unsafe_gateway_url_before_service",
        "test_update_payment_provider_config_value_error_returns_400_and_redacts_secret",
        "test_list_payment_providers_requires_payments_read_scope_before_payload",
        "test_list_payment_providers_returns_safe_capability_summary",
        "test_list_payment_providers_includes_offline_status_for_token188_epay_and_lemzf",
        "test_list_payment_providers_does_not_expose_credentials_or_gateway_values",
        "USDT_TRC20_DIRECT_PROVIDER",
    ]
    if not payment_config_tests_path.is_file():
        missing.append("tests/test_tenant_admin_payment_config.py")
    missing.extend(
        f"tests/test_tenant_admin_payment_config.py:{marker}"
        for marker in required_payment_config_test_markers
        if marker not in payment_config_tests
    )
    required_payment_config_service_test_markers = [
        "test_normalize_epusdt_base_url_keeps_safe_gateway_without_trailing_slash",
        "test_normalize_epusdt_base_url_rejects_embedded_credentials_and_query",
        "test_normalize_payment_gateway_url_rejects_userinfo_query_fragment",
        "test_list_payment_provider_summaries_exposes_safe_static_capabilities",
        "test_trc20_direct_config_normalization_is_offline_only_and_rejects_unsafe_values",
        "invalid_checksum_address",
        "TENANT_DIRECT_PAYMENT_PROVIDER_PRIORITY",
        "USDT_TRC20_DIRECT_PROVIDER",
        "TRC20 直付不使用 gateway URL",
    ]
    if not payment_config_service_tests_path.is_file():
        missing.append("tests/test_payment_config_service.py")
    missing.extend(
        f"tests/test_payment_config_service.py:{marker}"
        for marker in required_payment_config_service_test_markers
        if marker not in payment_config_service_tests
    )
    required_trc20_direct_test_markers = [
        "test_parse_standard_trc20_usdt_transfer_without_network",
        "test_parse_ignores_non_matching_transactions",
        "test_parse_rejects_malformed_transfer_without_raw_payload_leak",
        "test_amount_conversion_uses_integer_base_units",
        "test_tron_address_hex_roundtrip_and_tx_hash_normalization",
        "test_match_transfer_requires_confirmation_and_deduplicates_tx_hash",
        "test_match_transfer_reports_safe_mismatch_reasons",
        "test_match_transfer_rejects_ambiguous_candidate_window",
        "plain-secret",
        "duplicate_tx",
        "not_confirmed",
        "ambiguous",
    ]
    if not trc20_direct_tests_path.is_file():
        missing.append("tests/test_trc20_direct_core.py")
    missing.extend(
        f"tests/test_trc20_direct_core.py:{marker}"
        for marker in required_trc20_direct_test_markers
        if marker not in trc20_direct_tests
    )
    required_payment_create_test_markers = [
        "test_create_payment_for_order_creates_trc20_direct_offline_intent_without_network",
        "test_create_payment_for_order_reuses_existing_trc20_direct_intent",
        "test_provider_factory_creates_trc20_direct_offline_provider",
        "test_real_resolver_for_self_order_accepts_explicit_trc20_direct_provider",
        "Trc20DirectConfig",
        "Trc20DirectPaymentProvider",
        "USDT_TRC20_DIRECT_PROVIDER",
    ]
    if not payment_create_tests_path.is_file():
        missing.append("tests/test_payment_create_service.py")
    missing.extend(
        f"tests/test_payment_create_service.py:{marker}"
        for marker in required_payment_create_test_markers
        if marker not in payment_create_tests
    )
    required_payment_callback_failure_test_markers = [
        "test_list_failures_returns_tenant_scoped_safe_summaries",
        "test_list_failures_supports_ignored_status_and_out_trade_no_filter",
        "test_list_failures_redacts_sensitive_error_message",
        "test_list_failures_rejects_invalid_filters_before_response",
        "payload_json",
        "provider_trade_no",
    ]
    if not payment_callback_failure_tests_path.is_file():
        missing.append("tests/test_payment_callback_failures.py")
    missing.extend(
        f"tests/test_payment_callback_failures.py:{marker}"
        for marker in required_payment_callback_failure_test_markers
        if marker not in payment_callback_failure_tests
    )
    required_tenant_admin_callback_failure_test_markers = [
        "test_list_payment_callback_failures_requires_payments_read_scope_before_service",
        "test_list_payment_callback_failures_returns_safe_tenant_scoped_payload",
        "test_list_payment_callback_failures_value_error_returns_400_without_secret",
        "payload_json",
        "payload_hash",
        "provider_trade_no",
    ]
    if not tenant_admin_callback_failure_tests_path.is_file():
        missing.append("tests/test_tenant_admin_payment_callback_failures.py")
    missing.extend(
        f"tests/test_tenant_admin_payment_callback_failures.py:{marker}"
        for marker in required_tenant_admin_callback_failure_test_markers
        if marker not in tenant_admin_callback_failure_tests
    )
    required_openapi_test_markers = [
        "test_payment_config_operations_are_documented_as_tenant_admin",
        "test_payment_config_schema_exposes_safe_fields_only",
        "TenantEpusdtConfigResponse",
        "UpdateTenantEpusdtConfigRequest",
        "DisableTenantEpusdtConfigResponse",
        "TenantPaymentProviderConfigResponse",
        "UpdateTenantPaymentProviderConfigRequest",
        "DisableTenantPaymentProviderConfigResponse",
        "TenantPaymentProviderItem",
        "ListTenantPaymentProvidersResponse",
        "TenantPaymentCallbackFailureItem",
        "ListTenantPaymentCallbackFailuresResponse",
        "TenantPaymentCallbackRejectionItem",
        "ListTenantPaymentCallbackRejectionsResponse",
        "test_generic_payment_provider_config_operations_are_documented_as_tenant_admin",
        "test_generic_payment_provider_config_schema_exposes_safe_fields_only",
        "test_payment_provider_list_operation_is_documented_as_tenant_admin",
        "test_payment_provider_list_schema_exposes_safe_fields_only",
        "test_payment_callback_failure_operation_is_documented_as_tenant_admin",
        "test_payment_callback_failure_schema_exposes_safe_fields_only",
        "test_payment_callback_rejection_operation_is_documented_as_tenant_admin",
        "test_payment_callback_rejection_schema_exposes_safe_fields_only",
        "key_configured",
        "offline_only",
        "reconcile_available",
        "failure_reason",
        "secret_key",
    ]
    if not openapi_tests_path.is_file():
        missing.append("tests/test_openapi_security_contract.py")
    missing.extend(
        f"tests/test_openapi_security_contract.py:{marker}"
        for marker in required_openapi_test_markers
        if marker not in openapi_tests
    )
    if missing:
        return ReadinessCheck("tenant_admin_payment_config_contract", FAIL, f"missing markers: {', '.join(missing)}")
    return ReadinessCheck(
        "tenant_admin_payment_config_contract",
        PASS,
        "Tenant Admin payment config API has epusdt compatibility, generic provider routes, safe payment provider capability summaries and payment callback failure observability with payments scopes, safe request validation, redacted response schemas and route tests",
    )


def _check_trc20_direct_reconcile_contract(project_root: Path) -> ReadinessCheck:
    payment_models = _read_optional(project_root / "app" / "db" / "models" / "orders.py")
    model_exports = _read_optional(project_root / "app" / "db" / "models" / "__init__.py")
    trc20_core = _read_optional(project_root / "app" / "services" / "payments" / "trc20_direct.py")
    reconcile_service = _read_optional(project_root / "app" / "services" / "payments" / "trc20_reconcile.py")
    payment_exports = _read_optional(project_root / "app" / "services" / "payments" / "__init__.py")
    migration_paths = sorted((project_root / "alembic" / "versions").glob("20260609_0023*.py"))
    migration = "\n".join(_read_optional(path) for path in migration_paths)
    tests_path = project_root / "tests" / "test_trc20_direct_reconcile_service.py"
    tests = _read_optional(tests_path)

    missing: list[str] = []
    model_markers = [
        "Trc20DirectTransfer",
        '__tablename__ = "trc20_direct_transfers"',
        "tenant_id",
        "payment_id",
        "order_id",
        "out_trade_no",
        "tx_hash",
        "from_address",
        "to_address",
        "amount",
        "block_number",
        "block_timestamp",
        "confirmations",
        "match_status",
        "'duplicate_tx'",
        "'not_confirmed'",
        "'ambiguous'",
        "'matched'",
    ]
    if not (project_root / "app" / "db" / "models" / "orders.py").is_file():
        missing.append("app/db/models/orders.py")
    missing.extend(
        f"app/db/models/orders.py:{marker}"
        for marker in model_markers
        if marker not in payment_models
    )
    missing.extend(
        f"app/db/models/__init__.py:{marker}"
        for marker in ("Trc20DirectTransfer",)
        if marker not in model_exports
    )

    core_markers = [
        "TronUsdtTransfer",
        "TronUsdtPaymentCandidate",
        "TronUsdtMatchDecision",
        "match_tron_usdt_transfer",
        "duplicate_tx",
        "not_confirmed",
        "ambiguous",
        "matched",
    ]
    missing.extend(
        f"app/services/payments/trc20_direct.py:{marker}"
        for marker in core_markers
        if marker not in trc20_core
    )

    service_markers = [
        "Trc20DirectReconcileService",
        "record_transfer",
        "match_pending_payment",
        "Trc20DirectTransfer",
        "TronUsdtTransfer",
        "TronUsdtPaymentCandidate",
        "match_tron_usdt_transfer",
        "USDT_TRC20_DIRECT_PROVIDER",
        "Payment",
        "Order",
        "tenant_id",
        "tx_hash",
        "out_trade_no",
        "duplicate_tx",
        "not_confirmed",
        "ambiguous",
        "matched",
    ]
    if not (project_root / "app" / "services" / "payments" / "trc20_reconcile.py").is_file():
        missing.append("app/services/payments/trc20_reconcile.py")
    missing.extend(
        f"app/services/payments/trc20_reconcile.py:{marker}"
        for marker in service_markers
        if marker not in reconcile_service
    )
    missing.extend(
        f"app/services/payments/__init__.py:{marker}"
        for marker in ("Trc20DirectReconcileService",)
        if marker not in payment_exports
    )

    migration_markers = [
        "20260609_0023",
        "down_revision: Optional[str] = \"20260609_0022\"",
        "trc20_direct_transfers",
        "tx_hash",
        "tenant_id",
        "payment_id",
        "order_id",
        "out_trade_no",
        "match_status",
        "duplicate_tx",
        "not_confirmed",
        "ambiguous",
        "matched",
    ]
    if not migration_paths:
        missing.append("alembic/versions/20260609_0023*.py")
    missing.extend(
        f"alembic/versions/20260609_0023*.py:{marker}"
        for marker in migration_markers
        if marker not in migration
    )

    test_markers = [
        "test_record_transfer_persists_offline_transfer_without_network_or_env",
        "test_record_transfer_rejects_duplicate_tx_hash_before_matching",
        "test_match_pending_payment_marks_not_confirmed_without_updating_order",
        "test_match_pending_payment_rejects_ambiguous_candidates",
        "test_match_pending_payment_marks_payment_and_order_matched",
        "test_match_pending_payment_is_tenant_scoped",
        "test_match_pending_payment_does_not_expose_raw_payload_or_secret",
        "Trc20DirectReconcileService",
        "record_transfer",
        "match_pending_payment",
        "duplicate_tx",
        "not_confirmed",
        "ambiguous",
        "matched",
    ]
    if not tests_path.is_file():
        missing.append("tests/test_trc20_direct_reconcile_service.py")
    missing.extend(
        f"tests/test_trc20_direct_reconcile_service.py:{marker}"
        for marker in test_markers
        if marker not in tests
    )

    if missing:
        return ReadinessCheck("trc20_direct_reconcile_contract", FAIL, f"missing markers: {', '.join(missing)}")
    return ReadinessCheck(
        "trc20_direct_reconcile_contract",
        PASS,
        "usdt_trc20_direct has offline chain transfer persistence and local pending payment matching markers; this still does not scan TRON, call external APIs, read .env, or prove production direct payments or real reconciliation",
    )


def _check_tenant_admin_trc20_direct_transfer_observation_contract(project_root: Path) -> ReadinessCheck:
    tenant_admin = _read_optional(project_root / "app" / "web" / "tenant_admin.py")
    observation_service_path = project_root / "app" / "services" / "payments" / "trc20_observability.py"
    observation_service = _read_optional(observation_service_path)
    openapi_tests_path = project_root / "tests" / "test_openapi_security_contract.py"
    openapi_tests = _read_optional(openapi_tests_path)
    handoff_doc = _read_optional(project_root / "docs" / "开发交接说明.md")
    roadmap_doc = _read_optional(project_root / "docs" / "实施路线图.md")
    database_doc = _read_optional(project_root / "docs" / "数据库设计.md")

    missing: list[str] = []
    tenant_admin_markers = [
        "TenantTrc20DirectTransferItem",
        "TenantTrc20DirectTransferListResponse",
        '"/payments/trc20-direct/transfers"',
        'require_scope("payments:read")',
        "Trc20DirectTransferObservationService",
        "from_address_masked",
        "to_address_masked",
        "match_status",
        "out_trade_no",
        "tx_hash",
    ]
    missing.extend(
        f"app/web/tenant_admin.py:{marker}"
        for marker in tenant_admin_markers
        if marker not in tenant_admin
    )

    service_markers = [
        "Trc20DirectTransferObservationService",
        "Trc20DirectTransferSummary",
        "list_tenant_transfers",
        "Trc20DirectTransfer.tenant_id == tenant_id",
        "normalize_tron_tx_hash",
        "from_address_masked",
        "to_address_masked",
        "tenant_id",
        "match_status",
        "out_trade_no",
        "tx_hash",
    ]
    if not observation_service_path.is_file():
        missing.append("app/services/payments/trc20_observability.py")
    missing.extend(
        f"app/services/payments/trc20_observability.py:{marker}"
        for marker in service_markers
        if marker not in observation_service
    )

    openapi_markers = [
        "test_trc20_direct_transfer_observation_operation_is_documented_as_tenant_admin",
        "test_trc20_direct_transfer_observation_schema_exposes_safe_fields_only",
        "TenantTrc20DirectTransferItem",
        "TenantTrc20DirectTransferListResponse",
        "/payments/trc20-direct/transfers",
        "from_address_masked",
        "to_address_masked",
        "id",
        "tenant_id",
        "payment_id",
        "order_id",
        "raw_payload",
        "payload_json",
        "metadata_json",
    ]
    if not openapi_tests_path.is_file():
        missing.append("tests/test_openapi_security_contract.py")
    missing.extend(
        f"tests/test_openapi_security_contract.py:{marker}"
        for marker in openapi_markers
        if marker not in openapi_tests
    )

    docs = "\n".join([handoff_doc, roadmap_doc, database_doc])
    doc_markers = [
        "TenantTrc20DirectTransferItem",
        "TenantTrc20DirectTransferListResponse",
        "/payments/trc20-direct/transfers",
        'require_scope("payments:read")',
        "Trc20DirectTransferObservationService",
        "from_address_masked",
        "to_address_masked",
        "不扫链",
        "不外联",
        "不读取 `.env`",
        "不代表生产直付",
    ]
    missing.extend(f"docs/*:{marker}" for marker in doc_markers if marker not in docs)

    if missing:
        return ReadinessCheck(
            "tenant_admin_trc20_direct_transfer_observation_contract",
            FAIL,
            f"missing markers: {', '.join(missing)}",
        )
    return ReadinessCheck(
        "tenant_admin_trc20_direct_transfer_observation_contract",
        PASS,
        "Tenant Admin TRC20 direct transfer observation is a payments:read-only, tenant-scoped and redacted API contract; it does not scan chains, call external APIs, read .env, or prove production direct payments",
    )


def _check_tenant_admin_order_diagnostics_contract(project_root: Path) -> ReadinessCheck:
    tenant_admin = _read_optional(project_root / "app" / "web" / "tenant_admin.py")
    order_diagnostics = _read_optional(project_root / "app" / "services" / "order_diagnostics.py")
    runtime_tests_path = project_root / "tests" / "test_tenant_admin_runtime_auth.py"
    runtime_tests = _read_optional(runtime_tests_path)
    service_tests_path = project_root / "tests" / "test_order_diagnostics_service.py"
    service_tests = _read_optional(service_tests_path)
    openapi_tests_path = project_root / "tests" / "test_openapi_security_contract.py"
    openapi_tests = _read_optional(openapi_tests_path)
    handoff_doc = _read_optional(project_root / "docs" / "开发交接说明.md")
    roadmap_doc = _read_optional(project_root / "docs" / "实施路线图.md")
    database_doc = _read_optional(project_root / "docs" / "数据库设计.md")
    required_tenant_admin_markers = [
        "OrderDiagnosticsResponse",
        "OrderPaymentDiagnosticItem",
        "OrderPaymentCallbackDiagnosticItem",
        "OrderDeliveryDiagnosticItem",
        "OrderExternalFulfillmentDiagnosticItem",
        "OrderTrc20DirectDiagnosticItem",
        '"/orders/{out_trade_no}/diagnostics"',
        'require_scope("orders:read")',
        "OrderDiagnosticsService",
        "_order_diagnostics_response",
        "_order_payment_diagnostic_response",
        "_order_callback_diagnostic_response",
        "_order_delivery_diagnostic_response",
        "_order_external_fulfillment_diagnostic_response",
        "_order_trc20_direct_diagnostic_response",
        "trc20_direct",
        "attempt_count",
        "latest_attempt_status",
        "latest_attempt_source",
        "latest_attempt_at",
        "latest_failure_stage",
        "latest_failure_category",
        "latest_failure_retryable",
        "latest_upstream_status_code",
        "latest_item_count",
        "latest_delivery_record_linked",
        "transfer_count",
        "latest_match_status",
        "latest_confirmations",
        "latest_matched_at",
        "latest_amount",
    ]
    missing = [
        f"app/web/tenant_admin.py:{marker}"
        for marker in required_tenant_admin_markers
        if marker not in tenant_admin
    ]
    required_service_markers = [
        "OrderDiagnosticsService",
        "OrderDiagnosticsSummary",
        "OrderPaymentDiagnostic",
        "OrderPaymentCallbackDiagnostic",
        "OrderDeliveryDiagnostic",
        "OrderExternalFulfillmentDiagnostic",
        "OrderTrc20DirectDiagnostic",
        "ExternalFulfillmentAttempt",
        "ExternalFulfillmentAttempt.tenant_id == tenant_id",
        "ExternalFulfillmentAttempt.order_id == order_id",
        "ExternalFulfillmentAttempt.created_at.desc()",
        "Trc20DirectTransfer",
        "Trc20DirectTransfer.tenant_id == tenant_id",
        "Trc20DirectTransfer.order_id",
        "has_payment_url",
        "has_inventory_item",
        "has_uploaded_file",
        "has_telegram_chat",
        "attempt_count",
        "latest_attempt_status",
        "latest_attempt_source",
        "latest_attempt_at",
        "latest_failure_stage",
        "latest_failure_category",
        "latest_failure_retryable",
        "latest_upstream_status_code",
        "latest_item_count",
        "latest_delivery_record_linked",
        "trc20_direct",
        "transfer_count",
        "latest_match_status",
        "latest_confirmations",
        "latest_matched_at",
        "latest_amount",
        "SENSITIVE_PAYMENT_FAILURE_VALUE_MARKERS",
    ]
    if not (project_root / "app" / "services" / "order_diagnostics.py").is_file():
        missing.append("app/services/order_diagnostics.py")
    missing.extend(
        f"app/services/order_diagnostics.py:{marker}"
        for marker in required_service_markers
        if marker not in order_diagnostics
    )
    required_runtime_test_markers = [
        "test_order_diagnostics_requires_orders_read_scope_before_service",
        "test_order_diagnostics_returns_safe_tenant_scoped_summary",
        "test_order_diagnostics_returns_404_for_cross_tenant_or_missing_order",
        "test_order_diagnostics_value_error_returns_400_without_secret",
        "provider_trade_no",
        "payload_json",
        "payment_url",
        "supplier_tenant_id",
        "external_product_id",
        "attempt_count",
        "latest_attempt_status",
        "latest_attempt_source",
        "latest_attempt_at",
        "latest_failure_stage",
        "latest_failure_category",
        "latest_failure_retryable",
        "latest_upstream_status_code",
        "latest_item_count",
        "latest_delivery_record_linked",
        "failure_fingerprint",
    ]
    if not runtime_tests_path.is_file():
        missing.append("tests/test_tenant_admin_runtime_auth.py")
    missing.extend(
        f"tests/test_tenant_admin_runtime_auth.py:{marker}"
        for marker in required_runtime_test_markers
        if marker not in runtime_tests
    )
    required_service_test_markers = [
        "test_get_summary_returns_safe_payment_callback_delivery_and_external_mapping",
        "test_get_summary_returns_none_for_missing_or_cross_tenant_order",
        "test_get_summary_rejects_invalid_out_trade_no_before_query",
        "test_get_summary_does_not_query_product_for_reseller_order",
        "test_get_summary_returns_external_fulfillment_attempt_overview_without_sensitive_identifiers",
        "test_get_summary_returns_external_attempt_zero_count_without_latest_fields",
        "provider_trade_no",
        "payload_json",
        "payment_url",
        "supplier_tenant_id",
        "attempt_count",
        "latest_attempt_status",
        "latest_attempt_source",
        "latest_attempt_at",
        "latest_failure_stage",
        "latest_failure_category",
        "latest_failure_retryable",
        "latest_upstream_status_code",
        "latest_item_count",
        "latest_delivery_record_linked",
        "external_order_id",
        "connection_id",
        "failure_fingerprint",
    ]
    if not service_tests_path.is_file():
        missing.append("tests/test_order_diagnostics_service.py")
    missing.extend(
        f"tests/test_order_diagnostics_service.py:{marker}"
        for marker in required_service_test_markers
        if marker not in service_tests
    )
    required_openapi_test_markers = [
        "test_order_diagnostics_schema_exposes_safe_fields_only",
        "OrderDiagnosticsResponse",
        "OrderPaymentDiagnosticItem",
        "OrderPaymentCallbackDiagnosticItem",
        "OrderDeliveryDiagnosticItem",
        "OrderExternalFulfillmentDiagnosticItem",
        "OrderTrc20DirectDiagnosticItem",
        "/api/v1/tenant/orders/{out_trade_no}/diagnostics",
        "trc20_direct",
        "transfer_count",
        "latest_match_status",
        "latest_confirmations",
        "latest_matched_at",
        "latest_amount",
        "tx_hash",
        "from_address",
        "to_address",
        "id",
        "tenant_id",
        "payment_id",
        "order_id",
        "provider_trade_no",
        "payload_json",
        "raw_payload",
        "metadata_json",
        "payment_url",
        "supplier_tenant_id",
        "external_product_id",
        "attempt_count",
        "latest_attempt_status",
        "latest_attempt_source",
        "latest_attempt_at",
        "latest_failure_stage",
        "latest_failure_category",
        "latest_failure_retryable",
        "latest_upstream_status_code",
        "latest_item_count",
        "latest_delivery_record_linked",
        "attempt_id",
        "connection_id",
        "external_order_id",
        "failure_fingerprint",
    ]
    if not openapi_tests_path.is_file():
        missing.append("tests/test_openapi_security_contract.py")
    missing.extend(
        f"tests/test_openapi_security_contract.py:{marker}"
        for marker in required_openapi_test_markers
        if marker not in openapi_tests
    )
    docs = "\n".join([handoff_doc, roadmap_doc, database_doc])
    required_doc_markers = [
        "orders:read 安全聚合",
        "trc20_direct",
        "transfer_count",
        "latest_match_status",
        "latest_confirmations",
        "latest_matched_at",
        "latest_amount",
        "完整转账摘要仍走",
        "payments:read",
        "TRC20 转账观测接口",
        "不扫链",
        "不外联",
        "不读取 `.env`",
        "不代表生产直付",
    ]
    missing.extend(f"docs/*:{marker}" for marker in required_doc_markers if marker not in docs)
    if missing:
        return ReadinessCheck("tenant_admin_order_diagnostics_contract", FAIL, f"missing markers: {', '.join(missing)}")
    return ReadinessCheck(
        "tenant_admin_order_diagnostics_contract",
        PASS,
        "Tenant Admin order diagnostics is orders:read scoped, tenant-scoped, read-only and exposes safe payment/callback/delivery/external fulfillment/TRC20 direct aggregate state without payloads, payment URLs, chain transaction hashes, raw addresses, upstream trade numbers, external order identities, connection identities, delivery content or supplier/external credentials",
    )


def _check_tenant_admin_audit_log_contract(project_root: Path) -> ReadinessCheck:
    tenant_admin = _read_optional(project_root / "app" / "web" / "tenant_admin.py")
    api_keys = _read_optional(project_root / "app" / "services" / "api_keys.py")
    audit_service = _read_optional(project_root / "app" / "services" / "audit.py")
    runtime_tests_path = project_root / "tests" / "test_tenant_admin_runtime_auth.py"
    runtime_tests = _read_optional(runtime_tests_path)
    service_tests_path = project_root / "tests" / "test_audit_log_service.py"
    service_tests = _read_optional(service_tests_path)
    openapi_tests_path = project_root / "tests" / "test_openapi_security_contract.py"
    openapi_tests = _read_optional(openapi_tests_path)
    api_key_scope_tests_path = project_root / "tests" / "test_api_key_scopes.py"
    api_key_scope_tests = _read_optional(api_key_scope_tests_path)
    required_tenant_admin_markers = [
        "TenantAuditLogItem",
        "ListTenantAuditLogsResponse",
        '"/audit-logs"',
        'require_scope("audit_logs:read")',
        "AuditLogService",
        "_tenant_audit_log_response",
        "metadata=service.safe_metadata_for_tenant_api",
    ]
    missing = [
        f"app/web/tenant_admin.py:{marker}"
        for marker in required_tenant_admin_markers
        if marker not in tenant_admin
    ]
    required_scope_markers = ['"audit_logs:read"']
    missing.extend(
        f"app/services/api_keys.py:{marker}"
        for marker in required_scope_markers
        if marker not in api_keys
    )
    required_service_markers = [
        "list_tenant_audit_logs",
        "safe_metadata_for_tenant_api",
        "_normalize_optional_filter",
        "SENSITIVE_METADATA_KEYS",
        "signature",
        "authorization",
        "cookie",
        "provider_trade_no",
        "payment_url",
        "raw_request",
        "raw_response",
    ]
    if not (project_root / "app" / "services" / "audit.py").is_file():
        missing.append("app/services/audit.py")
    missing.extend(
        f"app/services/audit.py:{marker}"
        for marker in required_service_markers
        if marker not in audit_service
    )
    required_runtime_test_markers = [
        "test_list_audit_logs_requires_audit_logs_read_scope_before_service",
        "test_list_audit_logs_returns_safe_tenant_scoped_payload",
        "test_list_audit_logs_value_error_returns_400_without_secret",
        "metadata_json",
        "provider_trade_no",
        "payment_url",
        "plain_key",
    ]
    if not runtime_tests_path.is_file():
        missing.append("tests/test_tenant_admin_runtime_auth.py")
    missing.extend(
        f"tests/test_tenant_admin_runtime_auth.py:{marker}"
        for marker in required_runtime_test_markers
        if marker not in runtime_tests
    )
    required_service_test_markers = [
        "test_list_tenant_audit_logs_supports_safe_filters_and_redaction",
        "test_list_tenant_audit_logs_rejects_invalid_filters_before_query",
        "test_safe_metadata_for_tenant_api_removes_sensitive_keys_recursively",
        "signature",
        "authorization",
        "provider_trade_no",
        "payment_url",
    ]
    if not service_tests_path.is_file():
        missing.append("tests/test_audit_log_service.py")
    missing.extend(
        f"tests/test_audit_log_service.py:{marker}"
        for marker in required_service_test_markers
        if marker not in service_tests
    )
    required_openapi_test_markers = [
        "test_tenant_audit_log_operation_is_documented_as_tenant_admin",
        "test_tenant_audit_log_schema_exposes_safe_fields_only",
        "TenantAuditLogItem",
        "ListTenantAuditLogsResponse",
        "/api/v1/tenant/audit-logs",
        "metadata_json",
        "provider_trade_no",
        "payment_url",
        "plain_key",
    ]
    if not openapi_tests_path.is_file():
        missing.append("tests/test_openapi_security_contract.py")
    missing.extend(
        f"tests/test_openapi_security_contract.py:{marker}"
        for marker in required_openapi_test_markers
        if marker not in openapi_tests
    )
    required_scope_test_markers = [
        "audit_logs:read",
        'has_scope(["audit_logs:read"], "audit_logs:read")',
        'has_scope(["orders:read"], "audit_logs:read")',
    ]
    if not api_key_scope_tests_path.is_file():
        missing.append("tests/test_api_key_scopes.py")
    missing.extend(
        f"tests/test_api_key_scopes.py:{marker}"
        for marker in required_scope_test_markers
        if marker not in api_key_scope_tests
    )
    if missing:
        return ReadinessCheck("tenant_admin_audit_log_contract", FAIL, f"missing markers: {', '.join(missing)}")
    return ReadinessCheck(
        "tenant_admin_audit_log_contract",
        PASS,
        "Tenant Admin audit log API is audit_logs:read scoped, tenant-scoped and exposes safe metadata without raw metadata_json, payloads, credentials, payment URLs or upstream trade numbers",
    )


def _check_tenant_admin_risk_observability_contract(project_root: Path) -> ReadinessCheck:
    tenant_admin = _read_optional(project_root / "app" / "web" / "tenant_admin.py")
    api_keys = _read_optional(project_root / "app" / "services" / "api_keys.py")
    risk_service = _read_optional(project_root / "app" / "services" / "risk.py")
    runtime_tests_path = project_root / "tests" / "test_tenant_admin_runtime_auth.py"
    runtime_tests = _read_optional(runtime_tests_path)
    service_tests_path = project_root / "tests" / "test_risk_control_rules.py"
    service_tests = _read_optional(service_tests_path)
    openapi_tests_path = project_root / "tests" / "test_openapi_security_contract.py"
    openapi_tests = _read_optional(openapi_tests_path)
    api_key_scope_tests_path = project_root / "tests" / "test_api_key_scopes.py"
    api_key_scope_tests = _read_optional(api_key_scope_tests_path)
    required_tenant_admin_markers = [
        "TenantRiskDisputeItem",
        "ListTenantRiskDisputesResponse",
        "TenantRiskAfterSaleItem",
        "ListTenantRiskAfterSalesResponse",
        '"/risk/disputes"',
        '"/risk/after-sales"',
        'require_scope("risk:read")',
        "RiskControlService",
        "list_disputes",
        "list_after_sales",
        "_risk_dispute_response",
        "_risk_after_sale_response",
        "_normalize_risk_status",
        "_safe_risk_text",
        "RISK_RESPONSE_SENSITIVE_VALUE_MARKERS",
        "内容已隐藏",
    ]
    missing = [
        f"app/web/tenant_admin.py:{marker}"
        for marker in required_tenant_admin_markers
        if marker not in tenant_admin
    ]
    required_scope_markers = ['"risk:read"']
    missing.extend(
        f"app/services/api_keys.py:{marker}"
        for marker in required_scope_markers
        if marker not in api_keys
    )
    required_risk_service_markers = [
        "DISPUTE_STATUSES",
        "AFTER_SALE_STATUSES",
        "list_disputes",
        "list_after_sales",
        "Dispute.tenant_id == tenant_id",
        "AfterSaleCase.tenant_id == tenant_id",
        "争议状态必须是",
        "售后状态必须是",
    ]
    if not (project_root / "app" / "services" / "risk.py").is_file():
        missing.append("app/services/risk.py")
    missing.extend(
        f"app/services/risk.py:{marker}"
        for marker in required_risk_service_markers
        if marker not in risk_service
    )
    required_runtime_test_markers = [
        "test_list_risk_disputes_requires_risk_read_scope_before_service",
        "test_list_risk_disputes_is_tenant_scoped_and_sanitizes_text",
        "test_list_risk_after_sales_is_tenant_scoped_and_omits_refund_id",
        "test_list_risk_cases_value_error_returns_400_without_secret",
        "risk:read",
        "/api/v1/tenant/risk/disputes",
        "/api/v1/tenant/risk/after-sales",
        "tenant_id=7",
        "内容已隐藏",
        "refund_id",
    ]
    if not runtime_tests_path.is_file():
        missing.append("tests/test_tenant_admin_runtime_auth.py")
    missing.extend(
        f"tests/test_tenant_admin_runtime_auth.py:{marker}"
        for marker in required_runtime_test_markers
        if marker not in runtime_tests
    )
    required_service_test_markers = [
        "test_list_disputes_rejects_invalid_status_before_query",
        "争议状态必须是",
    ]
    if not service_tests_path.is_file():
        missing.append("tests/test_risk_control_rules.py")
    missing.extend(
        f"tests/test_risk_control_rules.py:{marker}"
        for marker in required_service_test_markers
        if marker not in service_tests
    )
    required_openapi_test_markers = [
        "test_tenant_risk_observability_schema_exposes_safe_fields_only",
        "TenantRiskDisputeItem",
        "ListTenantRiskDisputesResponse",
        "TenantRiskAfterSaleItem",
        "ListTenantRiskAfterSalesResponse",
        "/api/v1/tenant/risk/disputes",
        "/api/v1/tenant/risk/after-sales",
        "tenant_id",
        "refund_id",
        "payment_url",
        "provider_trade_no",
    ]
    if not openapi_tests_path.is_file():
        missing.append("tests/test_openapi_security_contract.py")
    missing.extend(
        f"tests/test_openapi_security_contract.py:{marker}"
        for marker in required_openapi_test_markers
        if marker not in openapi_tests
    )
    required_scope_test_markers = [
        '"risk:read"',
        'has_scope(["risk:read"], "risk:read")',
        'has_scope(["orders:read"], "risk:read")',
    ]
    if not api_key_scope_tests_path.is_file():
        missing.append("tests/test_api_key_scopes.py")
    missing.extend(
        f"tests/test_api_key_scopes.py:{marker}"
        for marker in required_scope_test_markers
        if marker not in api_key_scope_tests
    )
    if missing:
        return ReadinessCheck("tenant_admin_risk_observability_contract", FAIL, f"missing markers: {', '.join(missing)}")
    return ReadinessCheck(
        "tenant_admin_risk_observability_contract",
        PASS,
        "Tenant Admin risk observability API is risk:read scoped, tenant-scoped and exposes safe dispute/after-sale summaries without refund internals, credentials, payloads, payment URLs or upstream trade numbers",
    )


def _check_platform_admin_api_key_scope_contract(project_root: Path) -> ReadinessCheck:
    config_path = project_root / "app" / "config.py"
    platform_admin_path = project_root / "app" / "web" / "platform_admin.py"
    openapi_path = project_root / "app" / "web" / "openapi.py"
    runtime_tests_path = project_root / "tests" / "test_platform_admin_runtime_auth.py"
    openapi_tests_path = project_root / "tests" / "test_openapi_security_contract.py"
    env_example_path = project_root / ".env.example"
    roadmap_path = project_root / "docs" / "实施路线图.md"
    handoff_path = project_root / "docs" / "开发交接说明.md"

    config = _read_optional(config_path)
    platform_admin = _read_optional(platform_admin_path)
    openapi = _read_optional(openapi_path)
    runtime_tests = _read_optional(runtime_tests_path)
    openapi_tests = _read_optional(openapi_tests_path)
    env_example = _read_optional(env_example_path)
    roadmap = _read_optional(roadmap_path)
    handoff = _read_optional(handoff_path)

    missing: list[str] = []
    required_config_markers = [
        "PLATFORM_ADMIN_SCOPE_VALUES",
        "platform_admin_api_key_scopes",
        "parse_platform_admin_api_key_scopes",
        "validate_platform_admin_api_key_scopes",
        "validate_platform_admin_api_key_scope_hashes",
        "json.loads",
        "_is_sha256_hex",
        "_parse_scope_values",
        "scope 只能引用已配置的 API Key hash",
        "未知权限",
    ]
    if not config_path.is_file():
        missing.append("app/config.py")
    missing.extend(f"app/config.py:{marker}" for marker in required_config_markers if marker not in config)

    required_platform_admin_markers = [
        "PLATFORM_ADMIN_SCOPE_VALUES",
        "_platform_admin_key_scopes",
        "settings.platform_admin_api_key_scopes",
        "configured_scopes.get(key_hash, set())",
        "frozenset(PLATFORM_ADMIN_SCOPES)",
        "Platform Admin API Key 权限不足",
    ]
    if not platform_admin_path.is_file():
        missing.append("app/web/platform_admin.py")
    missing.extend(
        f"app/web/platform_admin.py:{marker}"
        for marker in required_platform_admin_markers
        if marker not in platform_admin
    )

    required_openapi_markers = [
        "PLATFORM_ADMIN_REQUIRED_SCOPES",
        "x-fakabot-required-scope",
        "platform_risk:read",
        "platform_risk:write",
        "platform_finance:read",
        "platform_finance:write",
        "platform_subscriptions:read",
        "platform_subscriptions:write",
        "platform_supply:read",
        "platform_supply:write",
    ]
    if not openapi_path.is_file():
        missing.append("app/web/openapi.py")
    missing.extend(f"app/web/openapi.py:{marker}" for marker in required_openapi_markers if marker not in openapi)

    if "PLATFORM_ADMIN_API_KEY_SCOPES" not in env_example:
        missing.append(".env.example:PLATFORM_ADMIN_API_KEY_SCOPES")

    required_runtime_test_markers = [
        "test_platform_admin_api_key_scope_config_parses_per_hash_scopes",
        "test_platform_admin_api_key_scope_config_rejects_unknown_or_orphan_scopes",
        "test_scoped_platform_admin_key_can_read_but_cannot_write",
        "test_platform_admin_key_not_listed_in_scope_map_has_no_implicit_full_access",
        "platform_admin_api_key_scopes",
        "pak_read_only",
        "pak_unlisted",
        "Platform Admin API Key 权限不足",
    ]
    if not runtime_tests_path.is_file():
        missing.append("tests/test_platform_admin_runtime_auth.py")
    missing.extend(
        f"tests/test_platform_admin_runtime_auth.py:{marker}"
        for marker in required_runtime_test_markers
        if marker not in runtime_tests
    )

    required_openapi_test_markers = [
        "expected_scopes",
        "x-fakabot-required-scope",
        "platform_subscriptions:read",
        "platform_subscriptions:write",
        "platform_finance:read",
        "platform_supply:write",
    ]
    if not openapi_tests_path.is_file():
        missing.append("tests/test_openapi_security_contract.py")
    missing.extend(
        f"tests/test_openapi_security_contract.py:{marker}"
        for marker in required_openapi_test_markers
        if marker not in openapi_tests
    )

    required_document_markers = {
        roadmap_path: [
            "Platform Admin API Key 支持按 Key 配置 scopes",
            "`PLATFORM_ADMIN_API_KEY_SCOPES`",
            "非空时进入显式授权模式",
        ],
        handoff_path: [
            "`PLATFORM_ADMIN_API_KEY_SCOPES`",
            "只允许 SHA-256 hash",
            "非空时未列入映射的 Key 不再获得隐式全量权限",
        ],
    }
    document_texts = {roadmap_path: roadmap, handoff_path: handoff}
    for path, markers in required_document_markers.items():
        if not path.is_file():
            missing.append(str(path.relative_to(project_root)))
        missing.extend(
            f"{path.relative_to(project_root)}:{marker}"
            for marker in markers
            if marker not in document_texts[path]
        )

    if missing:
        return ReadinessCheck(
            "platform_admin_api_key_scope_contract",
            FAIL,
            f"missing markers: {', '.join(missing)}",
        )
    return ReadinessCheck(
        "platform_admin_api_key_scope_contract",
        PASS,
        "Platform Admin API Keys support optional per-hash scopes; empty scope map preserves legacy full-admin behavior, while explicit scope maps fail closed for unlisted keys and OpenAPI documents required platform scopes",
    )


def _check_platform_admin_risk_ban_observability_contract(project_root: Path) -> ReadinessCheck:
    config = _read_optional(project_root / "app" / "config.py")
    main_py = _read_optional(project_root / "app" / "main.py")
    openapi = _read_optional(project_root / "app" / "web" / "openapi.py")
    platform_admin_path = project_root / "app" / "web" / "platform_admin.py"
    platform_admin = _read_optional(platform_admin_path)
    risk_service = _read_optional(project_root / "app" / "services" / "risk.py")
    api_keys = _read_optional(project_root / "app" / "services" / "api_keys.py")
    runtime_tests_path = project_root / "tests" / "test_platform_admin_runtime_auth.py"
    runtime_tests = _read_optional(runtime_tests_path)
    service_tests_path = project_root / "tests" / "test_risk_control_rules.py"
    service_tests = _read_optional(service_tests_path)
    openapi_tests_path = project_root / "tests" / "test_openapi_security_contract.py"
    openapi_tests = _read_optional(openapi_tests_path)
    app_runtime_tests_path = project_root / "tests" / "test_app_runtime_smoke.py"
    app_runtime_tests = _read_optional(app_runtime_tests_path)

    required_config_markers = [
        "platform_admin_api_key_hashes",
        "platform_admin_require_signature",
        "platform_admin_signature_max_skew_seconds",
        "platform_admin_rate_limit_per_minute",
        "platform_admin_ip_allowlist",
        "平台 Admin API Key hash 必须是 SHA-256 hex",
    ]
    missing = [
        f"app/config.py:{marker}"
        for marker in required_config_markers
        if marker not in config
    ]
    required_main_markers = [
        "create_platform_admin_router",
        "application.include_router(create_platform_admin_router(settings))",
    ]
    missing.extend(
        f"app/main.py:{marker}"
        for marker in required_main_markers
        if marker not in main_py
    )
    required_openapi_markers = [
        "PLATFORM_ADMIN_PATH_PREFIX",
        "PlatformAdminBearer",
        "PlatformAdminApiKeyHeader",
        "X-Platform-API-Key",
        "PLATFORM_ADMIN_REQUIRE_SIGNATURE",
    ]
    missing.extend(
        f"app/web/openapi.py:{marker}"
        for marker in required_openapi_markers
        if marker not in openapi
    )
    required_platform_admin_markers = [
        "create_platform_admin_router",
        '"/api/v1/platform"',
        '"/risk/banned-users"',
        '"/risk/users/{telegram_user_id}/ban-status"',
        "PlatformRiskBannedUserItem",
        "PlatformRiskBanStatusResponse",
        "ListPlatformRiskBannedUsersResponse",
        "PlatformAdminPrincipal",
        "platform_admin_api_key_hashes",
        "hmac.compare_digest",
        "X-Platform-API-Key",
        "Platform Admin API 未启用",
        "require_platform_scope",
        'require_platform_scope("platform_risk:read")',
        "RiskControlService",
        "list_banned_platform_users",
        "get_platform_user_ban_status",
        "_platform_risk_ban_status_response",
        "_safe_platform_error_detail",
    ]
    if not platform_admin_path.is_file():
        missing.append("app/web/platform_admin.py")
    missing.extend(
        f"app/web/platform_admin.py:{marker}"
        for marker in required_platform_admin_markers
        if marker not in platform_admin
    )
    required_service_markers = [
        "PlatformRiskBannedUserSummary",
        "PlatformRiskBanStatusSummary",
        "list_banned_platform_users",
        "get_platform_user_ban_status",
        "PlatformUser.is_banned.is_(True)",
        "PlatformUser.telegram_user_id == telegram_user_id",
        "PLATFORM_BAN_AUDIT_ACTIONS",
        "platform_risk.user_banned",
        "platform_risk.user_auto_banned",
        "platform_risk.user_unbanned",
        "_latest_platform_user_status_audit",
        "_get_platform_user_by_telegram_user_id",
        "_platform_user_ban_summary",
        "_platform_user_ban_status_summary",
        "_sanitize_platform_ban_reason",
        "_normalize_platform_ban_source",
    ]
    missing.extend(
        f"app/services/risk.py:{marker}"
        for marker in required_service_markers
        if marker not in risk_service
    )
    if "platform_risk:read" in api_keys:
        missing.append("app/services/api_keys.py:platform_risk:read must not be in TenantApiKey scopes")
    required_runtime_test_markers = [
        "test_platform_admin_missing_config_fails_closed_before_service",
        "test_tenant_api_key_cannot_access_platform_risk_observability",
        "test_list_banned_users_requires_valid_platform_key_before_service",
        "test_list_banned_users_returns_safe_payload_only",
        "test_list_banned_users_value_error_returns_400_without_secret",
        "test_get_ban_status_missing_config_fails_closed_before_service",
        "test_get_ban_status_rejects_tenant_api_key_before_service",
        "test_get_ban_status_requires_valid_platform_key_before_service",
        "test_get_ban_status_returns_safe_payload_only",
        "test_get_ban_status_returns_404_for_missing_platform_user",
        "test_get_ban_status_value_error_returns_400_without_secret",
        "/api/v1/platform/risk/banned-users",
        "/api/v1/platform/risk/users/123456/ban-status",
        "X-Platform-API-Key",
        "X-API-Key",
    ]
    if not runtime_tests_path.is_file():
        missing.append("tests/test_platform_admin_runtime_auth.py")
    missing.extend(
        f"tests/test_platform_admin_runtime_auth.py:{marker}"
        for marker in required_runtime_test_markers
        if marker not in runtime_tests
    )
    required_service_test_markers = [
        "PlatformRiskObservabilityTest",
        "test_list_banned_platform_users_returns_manual_ban_summary",
        "test_list_banned_platform_users_returns_auto_ban_summary",
        "test_list_banned_platform_users_filters_source_by_latest_action",
        "test_list_banned_platform_users_filters_telegram_user_id_exactly",
        "test_list_banned_platform_users_sanitizes_reason_and_omits_raw_metadata",
        "test_list_banned_platform_users_rejects_invalid_filters_before_query",
        "test_get_platform_user_ban_status_returns_manual_banned_user",
        "test_get_platform_user_ban_status_returns_auto_banned_user",
        "test_get_platform_user_ban_status_returns_unbanned_user_with_latest_unban_action",
        "test_get_platform_user_ban_status_returns_none_for_missing_user",
        "test_get_platform_user_ban_status_uses_db_ban_flag_as_source_of_truth",
        "test_get_platform_user_ban_status_sanitizes_reason_and_trigger_rule",
        "test_get_platform_user_ban_status_rejects_invalid_telegram_user_id_before_query",
    ]
    missing.extend(
        f"tests/test_risk_control_rules.py:{marker}"
        for marker in required_service_test_markers
        if marker not in service_tests
    )
    required_openapi_test_markers = [
        "test_platform_admin_security_schemes_are_declared",
        "test_all_platform_admin_operations_declare_independent_security_and_signature_contract",
        "test_platform_risk_banned_user_schema_exposes_safe_fields_only",
        "test_platform_risk_ban_status_schema_exposes_safe_fields_only",
        "PlatformAdminBearer",
        "PlatformAdminApiKeyHeader",
        "TenantAdminBearer",
        "X-Platform-API-Key",
        "X-API-Key",
        "PLATFORM_ADMIN_REQUIRE_SIGNATURE",
    ]
    missing.extend(
        f"tests/test_openapi_security_contract.py:{marker}"
        for marker in required_openapi_test_markers
        if marker not in openapi_tests
    )
    required_app_runtime_markers = [
        "/api/v1/platform/risk/banned-users",
        "/api/v1/platform/risk/users/{telegram_user_id}/ban-status",
    ]
    missing.extend(
        f"tests/test_app_runtime_smoke.py:{marker}"
        for marker in required_app_runtime_markers
        if marker not in app_runtime_tests
    )
    if missing:
        return ReadinessCheck("platform_admin_risk_ban_observability_contract", FAIL, f"missing markers: {', '.join(missing)}")
    return ReadinessCheck(
        "platform_admin_risk_ban_observability_contract",
        PASS,
        "Platform Admin risk ban observability is independently authenticated, fails closed without hash config and exposes safe banned-user list/status summaries without tenant API keys, raw metadata, actor IDs, tokens or secrets",
    )


def _check_platform_admin_risk_user_ban_action_contract(project_root: Path) -> ReadinessCheck:
    platform_admin_path = project_root / "app" / "web" / "platform_admin.py"
    platform_admin = _read_optional(platform_admin_path)
    tenant_admin = _read_optional(project_root / "app" / "web" / "tenant_admin.py")
    risk_service_path = project_root / "app" / "services" / "risk.py"
    risk_service = _read_optional(risk_service_path)
    api_keys = _read_optional(project_root / "app" / "services" / "api_keys.py")
    runtime_tests_path = project_root / "tests" / "test_platform_admin_runtime_auth.py"
    runtime_tests = _read_optional(runtime_tests_path)
    service_tests_path = project_root / "tests" / "test_risk_control_rules.py"
    service_tests = _read_optional(service_tests_path)
    openapi_tests_path = project_root / "tests" / "test_openapi_security_contract.py"
    openapi_tests = _read_optional(openapi_tests_path)
    roadmap_path = project_root / "docs" / "实施路线图.md"
    handoff_path = project_root / "docs" / "开发交接说明.md"
    full_plan_path = project_root / "docs" / "多租户发卡平台完整方案.md"
    roadmap = _read_optional(roadmap_path)
    handoff = _read_optional(handoff_path)
    full_plan = _read_optional(full_plan_path)

    missing: list[str] = []
    required_platform_admin_markers = [
        "PLATFORM_RISK_WRITE_SCOPE",
        "PlatformRiskBanStatusUpdateRequest",
        '"/risk/users/{telegram_user_id}/ban-status"',
        'require_platform_scope("platform_risk:write")',
        "ban_platform_user",
        "unban_platform_user",
        "get_platform_user_ban_status",
        "_normalize_platform_risk_ban_status",
        "_platform_risk_ban_status_response",
        "_safe_platform_error_detail",
        "actor_user_id=None",
    ]
    if not platform_admin_path.is_file():
        missing.append("app/web/platform_admin.py")
    missing.extend(
        f"app/web/platform_admin.py:{marker}"
        for marker in required_platform_admin_markers
        if marker not in platform_admin
    )

    required_service_markers = [
        "ban_platform_user",
        "unban_platform_user",
        "actor_user_id: Optional[int]",
        "platform_risk.user_banned",
        "platform_risk.user_unbanned",
        "_sanitize_platform_ban_reason(self._normalize_reason(reason))",
        "内容已隐藏",
    ]
    if not risk_service_path.is_file():
        missing.append("app/services/risk.py")
    missing.extend(
        f"app/services/risk.py:{marker}"
        for marker in required_service_markers
        if marker not in risk_service
    )

    if "platform_risk:write" in api_keys:
        missing.append("app/services/api_keys.py:platform_risk:write must not be in TenantApiKey scopes")
    forbidden_tenant_admin_markers = [
        "PlatformRiskBanStatusUpdateRequest",
        "platform_risk:write",
        "/api/v1/platform/risk/users",
    ]
    forbidden_tenant_admin_present = [
        marker for marker in forbidden_tenant_admin_markers if marker in tenant_admin
    ]
    if forbidden_tenant_admin_present:
        missing.append(
            "app/web/tenant_admin.py:must not expose Platform Admin user ban actions "
            f"({', '.join(forbidden_tenant_admin_present)})"
        )

    required_runtime_test_markers = [
        "test_platform_risk_ban_status_update_rejects_tenant_api_key_before_service",
        "test_platform_risk_ban_status_update_requires_platform_risk_write_before_service",
        "test_platform_risk_ban_status_update_requires_signature_before_service",
        "test_platform_risk_ban_status_update_rejects_extra_fields_before_service",
        "test_platform_risk_ban_status_update_rejects_invalid_status_before_service",
        "test_platform_risk_ban_status_update_value_error_returns_400_without_secret",
        "test_platform_risk_ban_status_update_is_platform_scoped_and_redacted",
        "test_platform_risk_ban_status_update_unbans_when_status_active",
        "/api/v1/platform/risk/users/123456/ban-status",
        "X-Platform-API-Key",
        "X-API-Key",
        "actor_user_id=None",
        "metadata_json",
        "token",
        "secret",
    ]
    if not runtime_tests_path.is_file():
        missing.append("tests/test_platform_admin_runtime_auth.py")
    missing.extend(
        f"tests/test_platform_admin_runtime_auth.py:{marker}"
        for marker in required_runtime_test_markers
        if marker not in runtime_tests
    )

    required_service_test_markers = [
        "test_ban_platform_user_updates_status_and_writes_audit",
        "test_ban_platform_user_rejects_duplicate_ban_without_audit",
        "test_ban_platform_user_hides_sensitive_reason_and_allows_platform_api_actor_none",
        "test_unban_platform_user_updates_status_and_writes_audit",
        "test_unban_platform_user_rejects_missing_or_active_user",
        "内容已隐藏",
        "plain-secret",
    ]
    if not service_tests_path.is_file():
        missing.append("tests/test_risk_control_rules.py")
    missing.extend(
        f"tests/test_risk_control_rules.py:{marker}"
        for marker in required_service_test_markers
        if marker not in service_tests
    )

    required_openapi_test_markers = [
        "test_platform_risk_ban_status_update_operation_is_documented_as_platform_admin",
        "test_platform_risk_ban_status_update_schema_exposes_safe_fields_only",
        "PlatformRiskBanStatusUpdateRequest",
        "PlatformRiskBanStatusResponse",
        "/api/v1/platform/risk/users/{telegram_user_id}/ban-status",
        "PlatformAdminBearer",
        "PlatformAdminApiKeyHeader",
        "TenantAdminBearer",
        "X-Platform-API-Key",
        "X-API-Key",
        "additionalProperties",
        "actor_user_id",
        "metadata_json",
        "raw_payload",
        "token",
        "secret",
    ]
    if not openapi_tests_path.is_file():
        missing.append("tests/test_openapi_security_contract.py")
    missing.extend(
        f"tests/test_openapi_security_contract.py:{marker}"
        for marker in required_openapi_test_markers
        if marker not in openapi_tests
    )

    required_document_markers = {
        roadmap_path: [
            "Platform Admin 平台用户封禁/解封 HTTP 写入口",
            "PATCH /api/v1/platform/risk/users/{telegram_user_id}/ban-status",
            "`platform_risk:write`",
            "不复用 Tenant Admin API Key",
        ],
        handoff_path: [
            "Platform Admin 平台用户封禁/解封 HTTP 写入口",
            "`platform_risk:write`",
            "Platform Admin API Key",
            "不得加入 `TenantApiKey`",
        ],
        full_plan_path: [
            "Platform Admin 平台用户封禁/解封 HTTP 写入口",
            "PATCH  /api/v1/platform/risk/users/{telegram_user_id}/ban-status",
            "`platform_risk:write`",
            "不接受客户端传入 actor 或 metadata",
        ],
    }
    document_texts = {
        roadmap_path: roadmap,
        handoff_path: handoff,
        full_plan_path: full_plan,
    }
    for path, markers in required_document_markers.items():
        if not path.is_file():
            missing.append(str(path.relative_to(project_root)))
        missing.extend(
            f"{path.relative_to(project_root)}:{marker}"
            for marker in markers
            if marker not in document_texts[path]
        )

    if missing:
        return ReadinessCheck(
            "platform_admin_risk_user_ban_action_contract",
            FAIL,
            f"missing markers: {', '.join(missing)}",
        )
    return ReadinessCheck(
        "platform_admin_risk_user_ban_action_contract",
        PASS,
        "Platform Admin user ban action API is independently authenticated, platform_risk:write scoped, request-whitelisted and can ban/unban platform users without Tenant Admin scopes, client-supplied actor metadata or sensitive reason leakage",
    )


def _check_platform_admin_tenant_suspension_action_contract(project_root: Path) -> ReadinessCheck:
    platform_admin_path = project_root / "app" / "web" / "platform_admin.py"
    platform_admin = _read_optional(platform_admin_path)
    tenant_admin = _read_optional(project_root / "app" / "web" / "tenant_admin.py")
    risk_service_path = project_root / "app" / "services" / "risk.py"
    risk_service = _read_optional(risk_service_path)
    api_keys = _read_optional(project_root / "app" / "services" / "api_keys.py")
    runtime_tests_path = project_root / "tests" / "test_platform_admin_runtime_auth.py"
    runtime_tests = _read_optional(runtime_tests_path)
    service_tests_path = project_root / "tests" / "test_risk_control_rules.py"
    service_tests = _read_optional(service_tests_path)
    openapi_tests_path = project_root / "tests" / "test_openapi_security_contract.py"
    openapi_tests = _read_optional(openapi_tests_path)
    app_runtime_tests_path = project_root / "tests" / "test_app_runtime_smoke.py"
    app_runtime_tests = _read_optional(app_runtime_tests_path)
    roadmap_path = project_root / "docs" / "实施路线图.md"
    handoff_path = project_root / "docs" / "开发交接说明.md"
    full_plan_path = project_root / "docs" / "多租户发卡平台完整方案.md"
    roadmap = _read_optional(roadmap_path)
    handoff = _read_optional(handoff_path)
    full_plan = _read_optional(full_plan_path)

    missing: list[str] = []
    required_platform_admin_markers = [
        "PlatformTenantSuspensionStatusUpdateRequest",
        "PlatformTenantSuspensionStatusResponse",
        '"/risk/tenants/{tenant_id}/suspension-status"',
        'require_platform_scope("platform_risk:write")',
        "suspend_tenant",
        "resume_tenant",
        "_normalize_platform_tenant_suspension_status",
        "_platform_tenant_suspension_status_response",
        "_clear_tenant_webhook_cache",
        "tenant_webhook:",
        "actor_user_id=None",
    ]
    if not platform_admin_path.is_file():
        missing.append("app/web/platform_admin.py")
    missing.extend(
        f"app/web/platform_admin.py:{marker}"
        for marker in required_platform_admin_markers
        if marker not in platform_admin
    )

    required_service_markers = [
        "suspend_tenant",
        "resume_tenant",
        "actor_user_id: Optional[int]",
        "platform_risk.tenant_suspended",
        "platform_risk.tenant_resumed",
        "_sanitize_platform_ban_reason(self._normalize_reason(reason))",
        "_tenant_webhook_secrets",
    ]
    if not risk_service_path.is_file():
        missing.append("app/services/risk.py")
    missing.extend(
        f"app/services/risk.py:{marker}"
        for marker in required_service_markers
        if marker not in risk_service
    )

    if "platform_risk:write" in api_keys:
        missing.append("app/services/api_keys.py:platform_risk:write must not be in TenantApiKey scopes")
    forbidden_tenant_admin_markers = [
        "PlatformTenantSuspensionStatusUpdateRequest",
        "/api/v1/platform/risk/tenants",
        "suspension-status",
    ]
    forbidden_tenant_admin_present = [
        marker for marker in forbidden_tenant_admin_markers if marker in tenant_admin
    ]
    if forbidden_tenant_admin_present:
        missing.append(
            "app/web/tenant_admin.py:must not expose Platform Admin tenant suspension actions "
            f"({', '.join(forbidden_tenant_admin_present)})"
        )

    required_runtime_test_markers = [
        "test_platform_tenant_suspension_update_rejects_tenant_api_key_before_service",
        "test_platform_tenant_suspension_update_requires_platform_risk_write_before_service",
        "test_platform_tenant_suspension_update_rejects_extra_fields_before_service",
        "test_platform_tenant_suspension_update_rejects_invalid_status_before_service",
        "test_platform_tenant_suspension_update_value_error_returns_400_without_secret",
        "test_platform_tenant_suspension_update_suspends_and_clears_webhook_cache_without_secret",
        "test_platform_tenant_suspension_update_resumes_when_status_active",
        "/api/v1/platform/risk/tenants/7/suspension-status",
        "X-Platform-API-Key",
        "X-API-Key",
        "tenant_webhook:",
        "webhook_secret",
        "actor_user_id=None",
        "metadata_json",
        "token",
        "secret",
    ]
    if not runtime_tests_path.is_file():
        missing.append("tests/test_platform_admin_runtime_auth.py")
    missing.extend(
        f"tests/test_platform_admin_runtime_auth.py:{marker}"
        for marker in required_runtime_test_markers
        if marker not in runtime_tests
    )

    required_service_test_markers = [
        "RiskControlTenantSuspensionTest",
        "test_suspend_tenant_allows_platform_api_actor_none_and_hides_sensitive_reason",
        "test_resume_tenant_allows_platform_api_actor_none_and_restores_previous_status",
        "platform_risk.tenant_suspended",
        "platform_risk.tenant_resumed",
        "内容已隐藏",
        "plain-secret",
    ]
    if not service_tests_path.is_file():
        missing.append("tests/test_risk_control_rules.py")
    missing.extend(
        f"tests/test_risk_control_rules.py:{marker}"
        for marker in required_service_test_markers
        if marker not in service_tests
    )

    required_openapi_test_markers = [
        "test_platform_tenant_suspension_update_operation_is_documented_as_platform_admin",
        "test_platform_tenant_suspension_update_schema_exposes_safe_fields_only",
        "PlatformTenantSuspensionStatusUpdateRequest",
        "PlatformTenantSuspensionStatusResponse",
        "/api/v1/platform/risk/tenants/{tenant_id}/suspension-status",
        "PlatformAdminBearer",
        "PlatformAdminApiKeyHeader",
        "TenantAdminBearer",
        "X-Platform-API-Key",
        "X-API-Key",
        "additionalProperties",
        "actor_user_id",
        "metadata_json",
        "webhook_secret",
        "raw_payload",
        "token",
        "secret",
    ]
    if not openapi_tests_path.is_file():
        missing.append("tests/test_openapi_security_contract.py")
    missing.extend(
        f"tests/test_openapi_security_contract.py:{marker}"
        for marker in required_openapi_test_markers
        if marker not in openapi_tests
    )

    required_app_runtime_markers = [
        "/api/v1/platform/risk/tenants/{tenant_id}/suspension-status",
    ]
    if not app_runtime_tests_path.is_file():
        missing.append("tests/test_app_runtime_smoke.py")
    missing.extend(
        f"tests/test_app_runtime_smoke.py:{marker}"
        for marker in required_app_runtime_markers
        if marker not in app_runtime_tests
    )

    required_document_markers = {
        roadmap_path: [
            "Platform Admin 租户冻结/恢复 HTTP 写入口",
            "PATCH /api/v1/platform/risk/tenants/{tenant_id}/suspension-status",
            "`platform_risk:write`",
            "不复用 Tenant Admin API Key",
            "不调用 Telegram",
        ],
        handoff_path: [
            "Platform Admin 租户冻结/恢复 HTTP 写入口",
            "`platform_risk:write`",
            "Platform Admin API Key",
            "不得加入 `TenantApiKey`",
            "webhook cache",
        ],
        full_plan_path: [
            "Platform Admin 租户冻结/恢复 HTTP 写入口",
            "PATCH  /api/v1/platform/risk/tenants/{tenant_id}/suspension-status",
            "`platform_risk:write`",
            "不接受客户端传入 actor 或 metadata",
            "不调用 Telegram",
        ],
    }
    document_texts = {
        roadmap_path: roadmap,
        handoff_path: handoff,
        full_plan_path: full_plan,
    }
    for path, markers in required_document_markers.items():
        if not path.is_file():
            missing.append(str(path.relative_to(project_root)))
        missing.extend(
            f"{path.relative_to(project_root)}:{marker}"
            for marker in markers
            if marker not in document_texts[path]
        )

    if missing:
        return ReadinessCheck(
            "platform_admin_tenant_suspension_action_contract",
            FAIL,
            f"missing markers: {', '.join(missing)}",
        )
    return ReadinessCheck(
        "platform_admin_tenant_suspension_action_contract",
        PASS,
        "Platform Admin tenant suspension API is independently authenticated, platform_risk:write scoped, request-whitelisted, clears local webhook cache without exposing secrets and can suspend/resume tenants without Tenant Admin scopes, client-supplied actor metadata or real Telegram calls",
    )


def _check_platform_admin_risk_audit_log_contract(project_root: Path) -> ReadinessCheck:
    openapi = _read_optional(project_root / "app" / "web" / "openapi.py")
    platform_admin_path = project_root / "app" / "web" / "platform_admin.py"
    platform_admin = _read_optional(platform_admin_path)
    tenant_admin = _read_optional(project_root / "app" / "web" / "tenant_admin.py")
    audit_service_path = project_root / "app" / "services" / "audit.py"
    audit_service = _read_optional(audit_service_path)
    runtime_tests_path = project_root / "tests" / "test_platform_admin_runtime_auth.py"
    runtime_tests = _read_optional(runtime_tests_path)
    service_tests_path = project_root / "tests" / "test_audit_log_service.py"
    service_tests = _read_optional(service_tests_path)
    openapi_tests_path = project_root / "tests" / "test_openapi_security_contract.py"
    openapi_tests = _read_optional(openapi_tests_path)
    app_runtime_tests_path = project_root / "tests" / "test_app_runtime_smoke.py"
    app_runtime_tests = _read_optional(app_runtime_tests_path)

    required_platform_admin_markers = [
        '"/risk/audit-logs"',
        "PlatformRiskAuditLogItem",
        "ListPlatformRiskAuditLogsResponse",
        "PlatformRiskAuditLogSummary",
        "AuditLogService",
        "list_platform_risk_audit_logs",
        "_platform_risk_audit_log_response",
        'require_platform_scope("platform_risk:read")',
        "_safe_platform_error_detail",
    ]
    missing = [
        f"app/web/platform_admin.py:{marker}"
        for marker in required_platform_admin_markers
        if marker not in platform_admin
    ]
    if not platform_admin_path.is_file():
        missing.append("app/web/platform_admin.py")

    forbidden_tenant_admin_markers = [
        '"/risk/audit-logs"',
        "PlatformRiskAuditLogItem",
        "ListPlatformRiskAuditLogsResponse",
        "list_platform_risk_audit_logs",
    ]
    forbidden_present = [
        marker for marker in forbidden_tenant_admin_markers if marker in tenant_admin
    ]
    if forbidden_present:
        missing.append(
            "app/web/tenant_admin.py:must not expose Platform Admin risk audit logs "
            f"({', '.join(forbidden_present)})"
        )

    required_openapi_markers = [
        "PlatformAdminBearer",
        "PlatformAdminApiKeyHeader",
        "X-Platform-API-Key",
        "PLATFORM_ADMIN_REQUIRE_SIGNATURE",
    ]
    missing.extend(
        f"app/web/openapi.py:{marker}"
        for marker in required_openapi_markers
        if marker not in openapi
    )

    required_service_markers = [
        "PlatformRiskAuditLogSummary",
        "list_platform_risk_audit_logs",
        "AuditLog.tenant_id.is_(None)",
        "AuditLog.action.like",
        "PLATFORM_RISK_ACTION_PREFIX",
        "_to_platform_risk_summary",
        "_normalize_platform_risk_action",
        "_normalize_optional_telegram_user_id",
        "_target_telegram_user_id_from_metadata",
        "_safe_platform_audit_text",
        "PLATFORM_AUDIT_REASON_SENSITIVE_MARKERS",
        "内容已隐藏",
    ]
    if not audit_service_path.is_file():
        missing.append("app/services/audit.py")
    missing.extend(
        f"app/services/audit.py:{marker}"
        for marker in required_service_markers
        if marker not in audit_service
    )

    required_runtime_test_markers = [
        "test_list_platform_risk_audit_logs_missing_config_fails_closed_before_service",
        "test_list_platform_risk_audit_logs_rejects_tenant_api_key_before_service",
        "test_list_platform_risk_audit_logs_requires_valid_platform_key_before_service",
        "test_list_platform_risk_audit_logs_returns_safe_payload_only",
        "test_list_platform_risk_audit_logs_value_error_returns_400_without_secret",
        "/api/v1/platform/risk/audit-logs",
        "X-Platform-API-Key",
        "X-API-Key",
        "metadata_json",
        "payment_url",
        "provider_trade_no",
        "raw_payload",
        "token=",
    ]
    if not runtime_tests_path.is_file():
        missing.append("tests/test_platform_admin_runtime_auth.py")
    missing.extend(
        f"tests/test_platform_admin_runtime_auth.py:{marker}"
        for marker in required_runtime_test_markers
        if marker not in runtime_tests
    )

    required_service_test_markers = [
        "test_list_platform_risk_audit_logs_filters_platform_scope_and_action_prefix",
        "test_list_platform_risk_audit_logs_accepts_platform_action_and_rejects_invalid_before_query",
        "test_list_platform_risk_audit_logs_rejects_invalid_telegram_user_id_before_query",
        "test_list_platform_risk_audit_logs_normalizes_limit_and_rejects_non_integer_before_query",
        "test_list_platform_risk_audit_logs_returns_safe_summary_fields_only",
        "test_list_platform_risk_audit_logs_hides_sensitive_reason_and_risk_rule",
        "test_list_platform_risk_audit_logs_filters_by_target_telegram_user_id",
        "audit_logs.tenant_id IS NULL",
        "audit_logs.action LIKE",
        "platform_risk.%",
        "PlatformRiskAuditLogSummary",
        "metadata_json",
        "payment_url",
        "provider_trade_no",
    ]
    if not service_tests_path.is_file():
        missing.append("tests/test_audit_log_service.py")
    missing.extend(
        f"tests/test_audit_log_service.py:{marker}"
        for marker in required_service_test_markers
        if marker not in service_tests
    )

    required_openapi_test_markers = [
        "test_platform_risk_audit_logs_operation_is_documented_as_platform_admin",
        "test_platform_risk_audit_log_schema_exposes_safe_fields_only",
        "PlatformRiskAuditLogItem",
        "ListPlatformRiskAuditLogsResponse",
        "/api/v1/platform/risk/audit-logs",
        "PlatformAdminBearer",
        "PlatformAdminApiKeyHeader",
        "X-Platform-API-Key",
        "X-API-Key",
        "metadata_json",
        "raw_metadata",
        "tenant_id",
        "actor_user_id",
        "audit_log_id",
        "target_id",
        "token",
        "secret",
        "api_key",
        "authorization",
        "cookie",
        "payload",
        "payment_url",
        "provider_trade_no",
        "raw_payload",
    ]
    if not openapi_tests_path.is_file():
        missing.append("tests/test_openapi_security_contract.py")
    missing.extend(
        f"tests/test_openapi_security_contract.py:{marker}"
        for marker in required_openapi_test_markers
        if marker not in openapi_tests
    )

    required_app_runtime_markers = [
        "/api/v1/platform/risk/audit-logs",
    ]
    if not app_runtime_tests_path.is_file():
        missing.append("tests/test_app_runtime_smoke.py")
    missing.extend(
        f"tests/test_app_runtime_smoke.py:{marker}"
        for marker in required_app_runtime_markers
        if marker not in app_runtime_tests
    )

    if missing:
        return ReadinessCheck("platform_admin_risk_audit_log_contract", FAIL, f"missing markers: {', '.join(missing)}")
    return ReadinessCheck(
        "platform_admin_risk_audit_log_contract",
        PASS,
        "Platform Admin risk audit log API is independently authenticated, platform-scoped to tenant_id=None platform_risk actions and exposes safe read-only summaries without Tenant Admin access, raw metadata, internal IDs, credentials, payloads, payment URLs or upstream trade numbers",
    )


def _check_platform_admin_finance_withdrawal_read_contract(project_root: Path) -> ReadinessCheck:
    platform_admin_path = project_root / "app" / "web" / "platform_admin.py"
    platform_admin = _read_optional(platform_admin_path)
    tenant_admin = _read_optional(project_root / "app" / "web" / "tenant_admin.py")
    ledger_service_path = project_root / "app" / "services" / "ledger.py"
    ledger_service = _read_optional(ledger_service_path)
    api_keys = _read_optional(project_root / "app" / "services" / "api_keys.py")
    runtime_tests_path = project_root / "tests" / "test_platform_admin_runtime_auth.py"
    runtime_tests = _read_optional(runtime_tests_path)
    service_tests_path = project_root / "tests" / "test_ledger_accounting_rules.py"
    service_tests = _read_optional(service_tests_path)
    openapi_tests_path = project_root / "tests" / "test_openapi_security_contract.py"
    openapi_tests = _read_optional(openapi_tests_path)
    app_runtime_tests_path = project_root / "tests" / "test_app_runtime_smoke.py"
    app_runtime_tests = _read_optional(app_runtime_tests_path)
    roadmap_path = project_root / "docs" / "实施路线图.md"
    handoff_path = project_root / "docs" / "开发交接说明.md"
    full_plan_path = project_root / "docs" / "多租户发卡平台完整方案.md"
    roadmap = _read_optional(roadmap_path)
    handoff = _read_optional(handoff_path)
    full_plan = _read_optional(full_plan_path)

    missing: list[str] = []
    required_platform_admin_markers = [
        "PLATFORM_FINANCE_READ_SCOPE",
        '"/finance/withdrawals"',
        '"/finance/withdrawals/{withdrawal_id}"',
        'require_platform_scope("platform_finance:read")',
        "ListPlatformWithdrawalsResponse",
        "PlatformWithdrawalItem",
        "PlatformWithdrawalDetailItem",
        "LedgerService",
        "list_pending_withdrawals",
        "get_platform_withdrawal",
        "_platform_withdrawal_response",
        "_platform_withdrawal_detail_response",
        "address_masked",
        "reviewed_at",
        "completed_at",
        "_safe_platform_finance_error_detail",
    ]
    if not platform_admin_path.is_file():
        missing.append("app/web/platform_admin.py")
    missing.extend(
        f"app/web/platform_admin.py:{marker}"
        for marker in required_platform_admin_markers
        if marker not in platform_admin
    )

    required_service_markers = [
        "list_pending_withdrawals",
        "get_platform_withdrawal",
        'WithdrawalRequest.status == "pending"',
        "WithdrawalRequest.requested_at.asc()",
        "WithdrawalRequest.id.asc()",
        "WithdrawalRequest.id == withdrawal_id",
        "WithdrawalSummary",
    ]
    if not ledger_service_path.is_file():
        missing.append("app/services/ledger.py")
    missing.extend(
        f"app/services/ledger.py:{marker}"
        for marker in required_service_markers
        if marker not in ledger_service
    )

    for forbidden_scope in ("platform_finance:read", "platform_finance:write"):
        if forbidden_scope in api_keys:
            missing.append(f"app/services/api_keys.py:{forbidden_scope} must not be in TenantApiKey scopes")
    forbidden_tenant_admin_markers = [
        "PlatformWithdrawalItem",
        "ListPlatformWithdrawalsResponse",
        "platform_finance",
        "/api/v1/platform/finance",
    ]
    forbidden_tenant_admin_present = [
        marker for marker in forbidden_tenant_admin_markers if marker in tenant_admin
    ]
    if forbidden_tenant_admin_present:
        missing.append(
            "app/web/tenant_admin.py:must not expose Platform Admin finance withdrawal API "
            f"({', '.join(forbidden_tenant_admin_present)})"
        )

    required_runtime_test_markers = [
        "test_platform_finance_withdrawals_rejects_tenant_api_key_before_service",
        "test_platform_finance_withdrawals_missing_config_fails_closed_before_service",
        "test_platform_finance_withdrawals_requires_valid_platform_key_before_service",
        "test_platform_finance_withdrawals_requires_platform_finance_read_before_service",
        "test_platform_finance_withdrawals_requires_signature_before_service",
        "test_platform_finance_withdrawals_value_error_returns_400_without_secret",
        "test_platform_finance_withdrawals_returns_pending_masked_payload_only",
        "test_platform_finance_withdrawal_detail_rejects_tenant_api_key_before_service",
        "test_platform_finance_withdrawal_detail_missing_config_fails_closed_before_service",
        "test_platform_finance_withdrawal_detail_requires_valid_platform_key_before_service",
        "test_platform_finance_withdrawal_detail_requires_platform_finance_read_before_service",
        "test_platform_finance_withdrawal_detail_requires_signature_before_service",
        "test_platform_finance_withdrawal_detail_returns_404_when_missing",
        "test_platform_finance_withdrawal_detail_value_error_returns_400_without_secret",
        "test_platform_finance_withdrawal_detail_returns_masked_payload_only",
        "/api/v1/platform/finance/withdrawals",
        "/api/v1/platform/finance/withdrawals/11",
        "X-Platform-API-Key",
        "X-API-Key",
        "platform_finance:read",
        "address_masked",
        "admin_note",
        "payout_reference",
        "raw_payload",
        "token",
        "secret",
        "api_key",
    ]
    if not runtime_tests_path.is_file():
        missing.append("tests/test_platform_admin_runtime_auth.py")
    missing.extend(
        f"tests/test_platform_admin_runtime_auth.py:{marker}"
        for marker in required_runtime_test_markers
        if marker not in runtime_tests
    )

    required_service_test_markers = [
        "test_list_pending_withdrawals_filters_pending_and_orders_by_oldest_first",
        "test_get_platform_withdrawal_reads_by_withdrawal_id",
        "withdrawal_requests.status",
        "withdrawal_requests.requested_at ASC",
        "withdrawal_requests.id ASC",
        "withdrawal_requests.id =",
    ]
    if not service_tests_path.is_file():
        missing.append("tests/test_ledger_accounting_rules.py")
    missing.extend(
        f"tests/test_ledger_accounting_rules.py:{marker}"
        for marker in required_service_test_markers
        if marker not in service_tests
    )

    required_openapi_test_markers = [
        "test_platform_finance_withdrawals_operation_is_documented_as_platform_admin",
        "test_platform_finance_withdrawal_detail_operation_is_documented_as_platform_admin",
        "test_platform_finance_withdrawal_schema_exposes_safe_fields_only",
        "test_platform_finance_withdrawal_detail_schema_exposes_safe_fields_only",
        "ListPlatformWithdrawalsResponse",
        "PlatformWithdrawalItem",
        "PlatformWithdrawalDetailItem",
        "/api/v1/platform/finance/withdrawals",
        "/api/v1/platform/finance/withdrawals/{withdrawal_id}",
        "PlatformAdminBearer",
        "PlatformAdminApiKeyHeader",
        "TenantAdminBearer",
        "TenantAdminApiKeyHeader",
        "X-Platform-API-Key",
        "X-API-Key",
        "PLATFORM_ADMIN_REQUIRE_SIGNATURE",
        "address_masked",
        "reviewed_at",
        "completed_at",
        "address_encrypted",
        "admin_note",
        "payout_reference",
        "payout_proof_url",
        "metadata_json",
        "raw_payload",
        "token",
        "secret",
        "api_key",
    ]
    if not openapi_tests_path.is_file():
        missing.append("tests/test_openapi_security_contract.py")
    missing.extend(
        f"tests/test_openapi_security_contract.py:{marker}"
        for marker in required_openapi_test_markers
        if marker not in openapi_tests
    )

    required_app_runtime_markers = [
        "/api/v1/platform/finance/withdrawals",
        "/api/v1/platform/finance/withdrawals/{withdrawal_id}",
    ]
    if not app_runtime_tests_path.is_file():
        missing.append("tests/test_app_runtime_smoke.py")
    missing.extend(
        f"tests/test_app_runtime_smoke.py:{marker}"
        for marker in required_app_runtime_markers
        if marker not in app_runtime_tests
    )

    required_document_markers = {
        roadmap_path: [
            "Platform Admin 提现申请只读列表和详情 API",
            "GET /api/v1/platform/finance/withdrawals",
            "GET /api/v1/platform/finance/withdrawals/{withdrawal_id}",
            "`platform_finance:read`",
            "不复用 Tenant Admin API Key",
            "不触发真实打款",
        ],
        handoff_path: [
            "Platform Admin 提现申请只读列表和详情 API",
            "GET /api/v1/platform/finance/withdrawals/{withdrawal_id}",
            "`platform_finance:read`",
            "Platform Admin API Key",
            "不得加入 `TenantApiKey`",
            "提现地址只返回 `address_masked`",
            "不执行链上、银行卡或第三方出款",
        ],
        full_plan_path: [
            "Platform Admin 提现申请只读列表和详情 API",
            "GET    /api/v1/platform/finance/withdrawals",
            "GET    /api/v1/platform/finance/withdrawals/{withdrawal_id}",
            "`platform_finance:read`",
            "只读观测，不审核、不完成、不拒绝、不自动打款",
            "响应不得暴露完整提现地址、加密地址、内部备注、凭据、token、secret、API Key 或 raw payload",
        ],
    }
    document_texts = {
        roadmap_path: roadmap,
        handoff_path: handoff,
        full_plan_path: full_plan,
    }
    for path, markers in required_document_markers.items():
        if not path.is_file():
            missing.append(str(path.relative_to(project_root)))
        missing.extend(
            f"{path.relative_to(project_root)}:{marker}"
            for marker in markers
            if marker not in document_texts[path]
        )

    if missing:
        return ReadinessCheck(
            "platform_admin_finance_withdrawal_read_contract",
            FAIL,
            f"missing markers: {', '.join(missing)}",
        )
    return ReadinessCheck(
        "platform_admin_finance_withdrawal_read_contract",
        PASS,
        "Platform Admin withdrawal read API is independently authenticated, platform_finance:read scoped, exposes pending-list and safe single-detail summaries without Tenant Admin scopes, full addresses, payout internals, credentials, raw payloads or real payout side effects",
    )


def _check_platform_admin_finance_withdrawal_review_contract(project_root: Path) -> ReadinessCheck:
    platform_admin_path = project_root / "app" / "web" / "platform_admin.py"
    platform_admin = _read_optional(platform_admin_path)
    tenant_admin = _read_optional(project_root / "app" / "web" / "tenant_admin.py")
    ledger_service_path = project_root / "app" / "services" / "ledger.py"
    ledger_service = _read_optional(ledger_service_path)
    api_keys = _read_optional(project_root / "app" / "services" / "api_keys.py")
    runtime_tests_path = project_root / "tests" / "test_platform_admin_runtime_auth.py"
    runtime_tests = _read_optional(runtime_tests_path)
    service_tests_path = project_root / "tests" / "test_ledger_accounting_rules.py"
    service_tests = _read_optional(service_tests_path)
    openapi_tests_path = project_root / "tests" / "test_openapi_security_contract.py"
    openapi_tests = _read_optional(openapi_tests_path)
    app_runtime_tests_path = project_root / "tests" / "test_app_runtime_smoke.py"
    app_runtime_tests = _read_optional(app_runtime_tests_path)
    roadmap_path = project_root / "docs" / "实施路线图.md"
    handoff_path = project_root / "docs" / "开发交接说明.md"
    full_plan_path = project_root / "docs" / "多租户发卡平台完整方案.md"
    roadmap = _read_optional(roadmap_path)
    handoff = _read_optional(handoff_path)
    full_plan = _read_optional(full_plan_path)

    missing: list[str] = []
    required_platform_admin_markers = [
        "PLATFORM_FINANCE_WRITE_SCOPE",
        '"platform_finance:write"',
        '"/finance/withdrawals/{withdrawal_id}/complete"',
        '"/finance/withdrawals/{withdrawal_id}/reject"',
        'require_platform_scope("platform_finance:write")',
        "CompletePlatformWithdrawalRequest",
        "RejectPlatformWithdrawalRequest",
        'model_config = ConfigDict(extra="forbid")',
        "complete_withdrawal",
        "reject_withdrawal",
        "payout_reference",
        "payout_proof_url",
        "_platform_withdrawal_detail_response",
        "_platform_withdrawal_summary_from_model",
        "_safe_platform_finance_action_error_detail",
    ]
    if not platform_admin_path.is_file():
        missing.append("app/web/platform_admin.py")
    missing.extend(
        f"app/web/platform_admin.py:{marker}"
        for marker in required_platform_admin_markers
        if marker not in platform_admin
    )

    required_service_markers = [
        "complete_withdrawal",
        "reject_withdrawal",
        "_get_pending_withdrawal",
        'WithdrawalRequest.status == "pending"',
        "withdrawal_completed",
        "withdrawal_rejected",
        "_normalize_optional_text(admin_note",
    ]
    if not ledger_service_path.is_file():
        missing.append("app/services/ledger.py")
    missing.extend(
        f"app/services/ledger.py:{marker}"
        for marker in required_service_markers
        if marker not in ledger_service
    )

    if "platform_finance:write" in api_keys:
        missing.append("app/services/api_keys.py:platform_finance:write must not be in TenantApiKey scopes")
    forbidden_tenant_admin_markers = [
        "CompletePlatformWithdrawalRequest",
        "RejectPlatformWithdrawalRequest",
        "platform_finance:write",
        "/api/v1/platform/finance",
    ]
    forbidden_tenant_admin_present = [
        marker for marker in forbidden_tenant_admin_markers if marker in tenant_admin
    ]
    if forbidden_tenant_admin_present:
        missing.append(
            "app/web/tenant_admin.py:must not expose Platform Admin finance withdrawal review API "
            f"({', '.join(forbidden_tenant_admin_present)})"
        )

    required_runtime_test_markers = [
        "test_platform_finance_withdrawal_complete_rejects_tenant_api_key_before_service",
        "test_platform_finance_withdrawal_complete_missing_config_fails_closed_before_service",
        "test_platform_finance_withdrawal_complete_requires_valid_platform_key_before_service",
        "test_platform_finance_withdrawal_complete_requires_platform_finance_write_before_service",
        "test_platform_finance_withdrawal_complete_requires_signature_before_service",
        "test_platform_finance_withdrawal_complete_returns_masked_payload_only",
        "test_platform_finance_withdrawal_complete_value_error_returns_400_without_secret",
        "test_platform_finance_withdrawal_reject_requires_platform_finance_write_before_service",
        "test_platform_finance_withdrawal_reject_rejects_extra_payout_fields_before_service",
        "test_platform_finance_withdrawal_reject_returns_masked_payload_only",
        "/api/v1/platform/finance/withdrawals/11/complete",
        "/api/v1/platform/finance/withdrawals/11/reject",
        "platform_finance:write",
        "X-Platform-API-Key",
        "X-API-Key",
        "payout_reference",
        "payout_proof_url",
        "admin_note",
        "raw_address",
        "token",
        "secret",
        "api_key",
    ]
    if not runtime_tests_path.is_file():
        missing.append("tests/test_platform_admin_runtime_auth.py")
    missing.extend(
        f"tests/test_platform_admin_runtime_auth.py:{marker}"
        for marker in required_runtime_test_markers
        if marker not in runtime_tests
    )

    required_service_test_markers = [
        "test_reject_withdrawal_returns_frozen_balance_and_rejects_later_completion",
        "资料不完整",
        "withdrawal_rejected",
        "ledger.withdrawal_rejected",
    ]
    if not service_tests_path.is_file():
        missing.append("tests/test_ledger_accounting_rules.py")
    missing.extend(
        f"tests/test_ledger_accounting_rules.py:{marker}"
        for marker in required_service_test_markers
        if marker not in service_tests
    )

    required_openapi_test_markers = [
        "test_platform_finance_withdrawal_review_operations_are_documented_as_platform_admin",
        "test_platform_finance_withdrawal_review_request_schemas_are_whitelisted",
        "CompletePlatformWithdrawalRequest",
        "RejectPlatformWithdrawalRequest",
        "/api/v1/platform/finance/withdrawals/{withdrawal_id}/complete",
        "/api/v1/platform/finance/withdrawals/{withdrawal_id}/reject",
        "PlatformAdminBearer",
        "PlatformAdminApiKeyHeader",
        "TenantAdminBearer",
        "TenantAdminApiKeyHeader",
        "X-Platform-API-Key",
        "X-API-Key",
        "PLATFORM_ADMIN_REQUIRE_SIGNATURE",
        "additionalProperties",
        "payout_reference",
        "payout_proof_url",
        "admin_note",
        "actor_user_id",
        "metadata_json",
        "raw_payload",
        "token",
        "secret",
        "api_key",
    ]
    if not openapi_tests_path.is_file():
        missing.append("tests/test_openapi_security_contract.py")
    missing.extend(
        f"tests/test_openapi_security_contract.py:{marker}"
        for marker in required_openapi_test_markers
        if marker not in openapi_tests
    )

    required_app_runtime_markers = [
        "/api/v1/platform/finance/withdrawals/{withdrawal_id}/complete",
        "/api/v1/platform/finance/withdrawals/{withdrawal_id}/reject",
    ]
    if not app_runtime_tests_path.is_file():
        missing.append("tests/test_app_runtime_smoke.py")
    missing.extend(
        f"tests/test_app_runtime_smoke.py:{marker}"
        for marker in required_app_runtime_markers
        if marker not in app_runtime_tests
    )

    required_document_markers = {
        roadmap_path: [
            "Platform Admin 提现人工审核写入口",
            "POST /api/v1/platform/finance/withdrawals/{withdrawal_id}/complete",
            "POST /api/v1/platform/finance/withdrawals/{withdrawal_id}/reject",
            "`platform_finance:write`",
            "真实自动出款仍不做",
        ],
        handoff_path: [
            "Platform Admin 提现人工审核写入口",
            "POST /api/v1/platform/finance/withdrawals/{withdrawal_id}/complete",
            "POST /api/v1/platform/finance/withdrawals/{withdrawal_id}/reject",
            "`platform_finance:write`",
            "不得加入 `TenantApiKey`",
            "不执行链上、银行卡或第三方出款",
        ],
        full_plan_path: [
            "Platform Admin 提现人工审核写入口要求",
            "POST   /api/v1/platform/finance/withdrawals/{withdrawal_id}/complete",
            "POST   /api/v1/platform/finance/withdrawals/{withdrawal_id}/reject",
            "`platform_finance:write`",
            "只处理 `pending` 提现申请",
            "不执行自动链上、银行卡或第三方出款",
        ],
    }
    document_texts = {
        roadmap_path: roadmap,
        handoff_path: handoff,
        full_plan_path: full_plan,
    }
    for path, markers in required_document_markers.items():
        if not path.is_file():
            missing.append(str(path.relative_to(project_root)))
        missing.extend(
            f"{path.relative_to(project_root)}:{marker}"
            for marker in markers
            if marker not in document_texts[path]
        )

    if missing:
        return ReadinessCheck(
            "platform_admin_finance_withdrawal_review_contract",
            FAIL,
            f"missing markers: {', '.join(missing)}",
        )
    return ReadinessCheck(
        "platform_admin_finance_withdrawal_review_contract",
        PASS,
        "Platform Admin withdrawal review API is platform_finance:write scoped, request-whitelisted and marks manual complete/reject results without Tenant Admin scopes, full addresses, payout internals in responses, raw payloads or automatic payout side effects",
    )


def _check_platform_admin_subscription_plan_contract(project_root: Path) -> ReadinessCheck:
    platform_admin_path = project_root / "app" / "web" / "platform_admin.py"
    platform_admin = _read_optional(platform_admin_path)
    tenant_admin = _read_optional(project_root / "app" / "web" / "tenant_admin.py")
    subscription_service_path = project_root / "app" / "services" / "subscriptions.py"
    subscription_service = _read_optional(subscription_service_path)
    api_keys = _read_optional(project_root / "app" / "services" / "api_keys.py")
    runtime_tests_path = project_root / "tests" / "test_platform_admin_runtime_auth.py"
    runtime_tests = _read_optional(runtime_tests_path)
    service_tests_path = project_root / "tests" / "test_subscription_service.py"
    service_tests = _read_optional(service_tests_path)
    openapi_tests_path = project_root / "tests" / "test_openapi_security_contract.py"
    openapi_tests = _read_optional(openapi_tests_path)
    app_runtime_tests_path = project_root / "tests" / "test_app_runtime_smoke.py"
    app_runtime_tests = _read_optional(app_runtime_tests_path)
    roadmap_path = project_root / "docs" / "实施路线图.md"
    handoff_path = project_root / "docs" / "开发交接说明.md"
    full_plan_path = project_root / "docs" / "多租户发卡平台完整方案.md"
    roadmap = _read_optional(roadmap_path)
    handoff = _read_optional(handoff_path)
    full_plan = _read_optional(full_plan_path)

    missing: list[str] = []
    required_platform_admin_markers = [
        "PLATFORM_SUBSCRIPTIONS_READ_SCOPE",
        "PLATFORM_SUBSCRIPTIONS_WRITE_SCOPE",
        '"platform_subscriptions:read"',
        '"platform_subscriptions:write"',
        '"/subscription/plans"',
        '"/subscription/plans/{plan_code}"',
        '"/subscription/plans/{plan_code}/status"',
        'require_platform_scope("platform_subscriptions:read")',
        'require_platform_scope("platform_subscriptions:write")',
        "PlatformSubscriptionPlanItem",
        "ListPlatformSubscriptionPlansResponse",
        "CreatePlatformSubscriptionPlanRequest",
        "UpdatePlatformSubscriptionPlanRequest",
        "UpdatePlatformSubscriptionPlanStatusRequest",
        'model_config = ConfigDict(extra="forbid")',
        "SubscriptionService",
        "list_platform_subscription_plans",
        "get_platform_subscription_plan",
        "create_platform_subscription_plan",
        "update_platform_subscription_plan",
        "set_platform_subscription_plan_enabled",
        "_platform_subscription_plan_response",
        "_safe_platform_subscription_error_detail",
    ]
    if not platform_admin_path.is_file():
        missing.append("app/web/platform_admin.py")
    missing.extend(
        f"app/web/platform_admin.py:{marker}"
        for marker in required_platform_admin_markers
        if marker not in platform_admin
    )

    required_service_markers = [
        "PlatformSubscriptionPlanSummary",
        "PLATFORM_PLAN_CREATED_ACTION",
        "PLATFORM_PLAN_UPDATED_ACTION",
        "PLATFORM_PLAN_STATUS_UPDATED_ACTION",
        "list_platform_subscription_plans",
        "get_platform_subscription_plan",
        "create_platform_subscription_plan",
        "update_platform_subscription_plan",
        "set_platform_subscription_plan_enabled",
        "_get_plan_by_code",
        "_normalize_plan_code",
        "allowed_chars",
        "_normalize_plan_name",
        "_normalize_plan_currency",
        "_normalize_monthly_price",
        "_normalize_plan_days",
        "_normalize_optional_reason",
        "_plan_summary",
        "_add_platform_plan_audit",
        "SubscriptionPlan.code ==",
        "SubscriptionPlan.enabled.is_",
        "target_type=\"subscription_plan\"",
        "target_id=plan.code",
        "tenant_id=None",
        "plan.monthly_price if plan is not None",
    ]
    if not subscription_service_path.is_file():
        missing.append("app/services/subscriptions.py")
    missing.extend(
        f"app/services/subscriptions.py:{marker}"
        for marker in required_service_markers
        if marker not in subscription_service
    )

    for forbidden_scope in ("platform_subscriptions:read", "platform_subscriptions:write"):
        if forbidden_scope in api_keys:
            missing.append(f"app/services/api_keys.py:{forbidden_scope} must not be in TenantApiKey scopes")
    forbidden_tenant_admin_markers = [
        "PlatformSubscriptionPlanItem",
        "platform_subscriptions",
        "/api/v1/platform/subscription",
    ]
    forbidden_tenant_admin_present = [
        marker for marker in forbidden_tenant_admin_markers if marker in tenant_admin
    ]
    if forbidden_tenant_admin_present:
        missing.append(
            "app/web/tenant_admin.py:must not expose Platform Admin subscription plan API "
            f"({', '.join(forbidden_tenant_admin_present)})"
        )

    required_runtime_test_markers = [
        "test_platform_subscription_plans_rejects_tenant_api_key_before_service",
        "test_platform_subscription_plans_missing_config_fails_closed_before_service",
        "test_platform_subscription_plans_requires_platform_subscriptions_read_before_service",
        "test_platform_subscription_plans_requires_signature_before_service",
        "test_platform_subscription_plans_returns_safe_payload_only",
        "test_get_platform_subscription_plan_returns_safe_payload_only",
        "test_get_platform_subscription_plan_requires_platform_subscriptions_read_before_service",
        "test_get_platform_subscription_plan_returns_404_when_missing",
        "test_create_platform_subscription_plan_requires_write_before_service",
        "test_create_platform_subscription_plan_rejects_extra_fields_before_service",
        "test_create_platform_subscription_plan_commits_and_returns_safe_payload",
        "test_update_platform_subscription_plan_requires_write_before_service",
        "test_update_platform_subscription_plan_returns_404_without_commit_when_missing",
        "test_update_platform_subscription_plan_commits_and_returns_safe_payload",
        "test_update_platform_subscription_plan_status_commits_and_returns_safe_payload",
        "test_platform_subscription_plan_value_error_returns_400_without_secret",
        "/api/v1/platform/subscription/plans",
        "/api/v1/platform/subscription/plans/default_monthly",
        "/api/v1/platform/subscription/plans/default_monthly/status",
        "X-Platform-API-Key",
        "X-API-Key",
        "platform_subscriptions:read",
        "platform_subscriptions:write",
        "plan_id",
        "tenant_id",
        "metadata_json",
        "token",
        "secret",
    ]
    if not runtime_tests_path.is_file():
        missing.append("tests/test_platform_admin_runtime_auth.py")
    missing.extend(
        f"tests/test_platform_admin_runtime_auth.py:{marker}"
        for marker in required_runtime_test_markers
        if marker not in runtime_tests
    )

    required_service_test_markers = [
        "test_list_platform_subscription_plans_filters_enabled_and_returns_safe_summaries",
        "test_get_platform_subscription_plan_returns_none_for_missing_plan",
        "test_create_platform_subscription_plan_adds_plan_and_platform_audit",
        "test_create_platform_subscription_plan_rejects_path_unsafe_code",
        "test_update_platform_subscription_plan_changes_only_plan_fields_and_audits",
        "test_set_platform_subscription_plan_enabled_soft_disables_without_tenant_changes",
        "test_create_renewal_order_uses_current_plan_price_for_future_orders",
        "subscription.plan_created",
        "subscription.plan_updated",
        "subscription.plan_status_updated",
        "basic/v1",
        "plan_id",
    ]
    if not service_tests_path.is_file():
        missing.append("tests/test_subscription_service.py")
    missing.extend(
        f"tests/test_subscription_service.py:{marker}"
        for marker in required_service_test_markers
        if marker not in service_tests
    )

    required_openapi_test_markers = [
        "test_platform_subscription_plan_operations_are_documented_as_platform_admin",
        "test_platform_subscription_plan_schemas_are_whitelisted",
        "PlatformSubscriptionPlanItem",
        "ListPlatformSubscriptionPlansResponse",
        "CreatePlatformSubscriptionPlanRequest",
        "UpdatePlatformSubscriptionPlanRequest",
        "UpdatePlatformSubscriptionPlanStatusRequest",
        "/api/v1/platform/subscription/plans",
        "/api/v1/platform/subscription/plans/{plan_code}",
        "/api/v1/platform/subscription/plans/{plan_code}/status",
        "PlatformAdminBearer",
        "PlatformAdminApiKeyHeader",
        "TenantAdminBearer",
        "TenantAdminApiKeyHeader",
        "X-Platform-API-Key",
        "X-API-Key",
        "PLATFORM_ADMIN_REQUIRE_SIGNATURE",
        "additionalProperties",
        "plan_code",
        "plan_id",
        "tenant_id",
        "metadata_json",
        "raw_payload",
        "token",
        "secret",
        "api_key",
    ]
    if not openapi_tests_path.is_file():
        missing.append("tests/test_openapi_security_contract.py")
    missing.extend(
        f"tests/test_openapi_security_contract.py:{marker}"
        for marker in required_openapi_test_markers
        if marker not in openapi_tests
    )

    required_app_runtime_markers = [
        "/api/v1/platform/subscription/plans",
        "/api/v1/platform/subscription/plans/{plan_code}",
        "/api/v1/platform/subscription/plans/{plan_code}/status",
    ]
    if not app_runtime_tests_path.is_file():
        missing.append("tests/test_app_runtime_smoke.py")
    missing.extend(
        f"tests/test_app_runtime_smoke.py:{marker}"
        for marker in required_app_runtime_markers
        if marker not in app_runtime_tests
    )

    required_document_markers = {
        roadmap_path: [
            "Platform Admin 订阅计划管理 HTTP 入口",
            "GET /api/v1/platform/subscription/plans",
            "GET /api/v1/platform/subscription/plans/{plan_code}",
            "PATCH /api/v1/platform/subscription/plans/{plan_code}/status",
            "`platform_subscriptions:read`",
            "`platform_subscriptions:write`",
            "不回改历史订单、账单或既有租户订阅周期",
        ],
        handoff_path: [
            "Platform Admin 订阅计划管理 HTTP 入口",
            "GET /api/v1/platform/subscription/plans",
            "POST /api/v1/platform/subscription/plans",
            "PATCH /api/v1/platform/subscription/plans/{plan_code}/status",
            "`platform_subscriptions:read`",
            "`platform_subscriptions:write`",
            "不得加入 `TenantApiKey`",
            "不触发支付、Telegram 或第三方外联",
        ],
        full_plan_path: [
            "Platform Admin 订阅计划管理 HTTP 入口要求",
            "GET    /api/v1/platform/subscription/plans",
            "POST   /api/v1/platform/subscription/plans",
            "PATCH  /api/v1/platform/subscription/plans/{plan_code}/status",
            "`platform_subscriptions:read`",
            "`platform_subscriptions:write`",
            "只管理 `subscription_plans`",
            "不重算历史 `subscription_invoices`",
        ],
    }
    document_texts = {
        roadmap_path: roadmap,
        handoff_path: handoff,
        full_plan_path: full_plan,
    }
    for path, markers in required_document_markers.items():
        if not path.is_file():
            missing.append(str(path.relative_to(project_root)))
        missing.extend(
            f"{path.relative_to(project_root)}:{marker}"
            for marker in markers
            if marker not in document_texts[path]
        )

    if missing:
        return ReadinessCheck(
            "platform_admin_subscription_plan_contract",
            FAIL,
            f"missing markers: {', '.join(missing)}",
        )
    return ReadinessCheck(
        "platform_admin_subscription_plan_contract",
        PASS,
        "Platform Admin subscription plan API is independently authenticated, platform_subscriptions scoped, plan_code based, request-whitelisted and limited to subscription_plans management without Tenant Admin scopes, internal IDs, historical invoice rewrites, payment calls or external side effects",
    )


def _check_tenant_admin_report_export_jobs_contract(project_root: Path) -> ReadinessCheck:
    tenant_admin = _read_optional(project_root / "app" / "web" / "tenant_admin.py")
    api_keys = _read_optional(project_root / "app" / "services" / "api_keys.py")
    report_service = _read_optional(project_root / "app" / "services" / "reports.py")
    runtime_tests_path = project_root / "tests" / "test_tenant_admin_runtime_auth.py"
    runtime_tests = _read_optional(runtime_tests_path)
    service_tests_path = project_root / "tests" / "test_report_export_service.py"
    service_tests = _read_optional(service_tests_path)
    openapi_tests_path = project_root / "tests" / "test_openapi_security_contract.py"
    openapi_tests = _read_optional(openapi_tests_path)
    api_key_scope_tests_path = project_root / "tests" / "test_api_key_scopes.py"
    api_key_scope_tests = _read_optional(api_key_scope_tests_path)
    roadmap_path = project_root / "docs" / "实施路线图.md"
    handoff_path = project_root / "docs" / "开发交接说明.md"
    database_design_path = project_root / "docs" / "数据库设计.md"
    roadmap = _read_optional(roadmap_path)
    handoff = _read_optional(handoff_path)
    database_design = _read_optional(database_design_path)
    required_tenant_admin_markers = [
        "TenantReportExportJobItem",
        "ListTenantReportExportJobsResponse",
        "CreateTenantReportExportJobRequest",
        '"/reports/export-jobs"',
        'require_scope("reports:read")',
        'require_scope("reports:write")',
        "ReportExportService",
        "create_export_job",
        "list_export_jobs",
        "tenant_id=api_key.tenant_id",
        "_report_export_job_response",
        "_report_download_available",
        "_normalize_report_export_status",
        "_normalize_report_export_type",
        "_safe_report_failure_text",
        "REPORT_FAILURE_SENSITIVE_VALUE_MARKERS",
        "download_available",
    ]
    missing = [
        f"app/web/tenant_admin.py:{marker}"
        for marker in required_tenant_admin_markers
        if marker not in tenant_admin
    ]
    required_scope_markers = ['"reports:read"', '"reports:write"']
    missing.extend(
        f"app/services/api_keys.py:{marker}"
        for marker in required_scope_markers
        if marker not in api_keys
    )
    required_report_service_markers = [
        "SUPPORTED_EXPORT_JOB_STATUSES",
        "SUPPORTED_REPORT_TYPES",
        "create_export_job",
        "list_export_jobs",
        'status="pending"',
        "report.export_requested",
        "ExportJob.tenant_id == tenant_id",
        "ExportJob.status == normalized_status",
        "ExportJob.report_type == normalized_report_type",
        "_validate_report_type",
        "_normalize_optional_status",
        "_normalize_optional_report_type",
    ]
    if not (project_root / "app" / "services" / "reports.py").is_file():
        missing.append("app/services/reports.py")
    missing.extend(
        f"app/services/reports.py:{marker}"
        for marker in required_report_service_markers
        if marker not in report_service
    )
    required_runtime_test_markers = [
        "test_list_report_export_jobs_requires_reports_read_scope_before_service",
        "test_list_report_export_jobs_is_tenant_scoped_and_redacted",
        "test_list_report_export_jobs_value_error_returns_400_without_secret",
        "reports:read",
        "/api/v1/tenant/reports/export-jobs",
        "tenant_id=7",
        "report_type=\"orders\"",
        "download_available",
        "download_url",
        "download_token",
        "storage_key",
        "requested_by_user_id",
        "test_create_report_export_job_requires_reports_write_scope_before_service",
        "test_create_report_export_job_is_tenant_scoped_pending_and_redacted",
        "test_create_report_export_job_value_error_returns_400_without_secret",
        "reports:write",
        "report_type=\"orders\"",
    ]
    if not runtime_tests_path.is_file():
        missing.append("tests/test_tenant_admin_runtime_auth.py")
    missing.extend(
        f"tests/test_tenant_admin_runtime_auth.py:{marker}"
        for marker in required_runtime_test_markers
        if marker not in runtime_tests
    )
    required_service_test_markers = [
        "test_create_export_job_rejects_invalid_report_type_before_insert",
        "test_list_export_jobs_rejects_invalid_status_before_query",
        "test_list_export_jobs_rejects_invalid_report_type_before_query",
        "报表任务状态必须是",
        "报表类型必须是",
    ]
    if not service_tests_path.is_file():
        missing.append("tests/test_report_export_service.py")
    missing.extend(
        f"tests/test_report_export_service.py:{marker}"
        for marker in required_service_test_markers
        if marker not in service_tests
    )
    required_openapi_test_markers = [
        "test_report_export_jobs_operation_is_documented_as_tenant_admin",
        "test_create_report_export_job_operation_is_documented_as_tenant_admin",
        "test_report_export_jobs_schema_exposes_safe_fields_only",
        "test_create_report_export_job_schema_accepts_report_type_only_and_returns_safe_pending_summary",
        "TenantReportExportJobItem",
        "ListTenantReportExportJobsResponse",
        "CreateTenantReportExportJobRequest",
        "/api/v1/tenant/reports/export-jobs",
        "report_type",
        "additionalProperties",
        "download_available",
        "download_url",
        "download_token",
        "storage_key",
        "raw_error",
        "tenant_id",
        "requested_by_user_id",
    ]
    if not openapi_tests_path.is_file():
        missing.append("tests/test_openapi_security_contract.py")
    missing.extend(
        f"tests/test_openapi_security_contract.py:{marker}"
        for marker in required_openapi_test_markers
        if marker not in openapi_tests
    )
    required_scope_test_markers = [
        '"reports:read"',
        '"reports:write"',
        'has_scope(["reports:read"], "reports:read")',
        'has_scope(["orders:read"], "reports:read")',
        'has_scope(["reports:write"], "reports:write")',
        'has_scope(["reports:read"], "reports:write")',
    ]
    if not api_key_scope_tests_path.is_file():
        missing.append("tests/test_api_key_scopes.py")
    missing.extend(
        f"tests/test_api_key_scopes.py:{marker}"
        for marker in required_scope_test_markers
        if marker not in api_key_scope_tests
    )
    required_document_markers = {
        roadmap_path: [
            "Tenant Admin 报表任务创建 API 合同",
            "`POST /api/v1/tenant/reports/export-jobs`",
            "`reports:write`",
            "`report_type`",
            "`pending`",
            "不同步生成 CSV",
            "不启动 worker",
            "不返回下载链接",
            "`download_token`",
            "`storage_key`",
            "raw error",
        ],
        handoff_path: [
            "Tenant Admin 报表任务创建 API 合同",
            "`POST /api/v1/tenant/reports/export-jobs`",
            "`reports:write`",
            "`report_type`",
            "`pending`",
            "不同步生成 CSV",
            "不启动 worker",
            "不返回下载链接",
            "`download_token`",
            "`storage_key`",
            "raw error",
        ],
        database_design_path: [
            "Tenant Admin 报表任务创建 API 合同",
            "`export_jobs`",
            "`report_type`",
            "`pending`",
            "不同步生成 CSV",
            "不启动 worker",
            "不返回下载链接",
            "`download_token`",
            "`storage_key`",
            "raw error",
        ],
    }
    document_texts = {
        roadmap_path: roadmap,
        handoff_path: handoff,
        database_design_path: database_design,
    }
    for path, markers in required_document_markers.items():
        if not path.is_file():
            missing.append(str(path.relative_to(project_root)))
        missing.extend(
            f"{path.relative_to(project_root)}:{marker}"
            for marker in markers
            if marker not in document_texts[path]
        )
    if missing:
        return ReadinessCheck("tenant_admin_report_export_jobs_contract", FAIL, f"missing markers: {', '.join(missing)}")
    return ReadinessCheck(
        "tenant_admin_report_export_jobs_contract",
        PASS,
        "Tenant Admin report export jobs API has reports:read status listing and reports:write pending job creation contracts, remains tenant-scoped, and exposes safe export status summaries without download tokens, URLs, storage paths, raw errors or tenant internals",
    )


def _check_tenant_admin_subscription_read_contract(project_root: Path) -> ReadinessCheck:
    tenant_admin = _read_optional(project_root / "app" / "web" / "tenant_admin.py")
    api_keys = _read_optional(project_root / "app" / "services" / "api_keys.py")
    subscription_service = _read_optional(project_root / "app" / "services" / "subscriptions.py")
    runtime_tests_path = project_root / "tests" / "test_tenant_admin_runtime_auth.py"
    runtime_tests = _read_optional(runtime_tests_path)
    service_tests_path = project_root / "tests" / "test_subscription_service.py"
    service_tests = _read_optional(service_tests_path)
    openapi_tests_path = project_root / "tests" / "test_openapi_security_contract.py"
    openapi_tests = _read_optional(openapi_tests_path)
    api_key_scope_tests_path = project_root / "tests" / "test_api_key_scopes.py"
    api_key_scope_tests = _read_optional(api_key_scope_tests_path)
    required_tenant_admin_markers = [
        "TenantSubscriptionResponse",
        "TenantSubscriptionInvoiceItem",
        "ListTenantSubscriptionInvoicesResponse",
        "CreateTenantSubscriptionRenewalOrderRequest",
        "TenantSubscriptionRenewalOrderResponse",
        '"/subscription/status"',
        '"/subscription/invoices"',
        '"/subscription/renewal-orders"',
        'require_scope("subscriptions:read")',
        'require_scope("subscriptions:write")',
        "SubscriptionService",
        "PaymentService",
        "PaymentUnavailableError",
        "get_tenant_subscription_summary",
        "list_tenant_subscription_invoices",
        "create_renewal_order",
        "payment_available",
        "payment_failure_reason",
        "_tenant_subscription_response",
        "_tenant_subscription_invoice_response",
    ]
    missing = [
        f"app/web/tenant_admin.py:{marker}"
        for marker in required_tenant_admin_markers
        if marker not in tenant_admin
    ]
    required_scope_markers = ['"subscriptions:read"', '"subscriptions:write"']
    missing.extend(
        f"app/services/api_keys.py:{marker}"
        for marker in required_scope_markers
        if marker not in api_keys
    )
    required_service_markers = [
        "TenantSubscriptionSummary",
        "SubscriptionInvoiceSummary",
        "SubscriptionOrder",
        "get_tenant_subscription_summary",
        "list_tenant_subscription_invoices",
        "create_renewal_order",
        "TenantSubscription.tenant_id == tenant_id",
        "SubscriptionInvoice.tenant_id == tenant_id",
        "SubscriptionInvoice.status == normalized_status",
        "SubscriptionInvoice.created_at.desc()",
        "SubscriptionInvoice.id.desc()",
        "_normalize_invoice_limit",
        "_normalize_invoice_status",
    ]
    if not (project_root / "app" / "services" / "subscriptions.py").is_file():
        missing.append("app/services/subscriptions.py")
    missing.extend(
        f"app/services/subscriptions.py:{marker}"
        for marker in required_service_markers
        if marker not in subscription_service
    )
    required_runtime_test_markers = [
        "test_get_subscription_status_requires_subscriptions_read_scope_before_service",
        "test_get_subscription_status_returns_safe_tenant_scoped_payload",
        "test_get_subscription_status_returns_404_for_missing_tenant",
        "test_list_subscription_invoices_requires_subscriptions_read_scope_before_service",
        "test_list_subscription_invoices_returns_safe_tenant_scoped_payload",
        "test_list_subscription_invoices_value_error_returns_400_without_secret",
        "test_create_subscription_renewal_order_requires_subscriptions_write_before_service",
        "test_create_subscription_renewal_order_rejects_extra_fields_before_service",
        "test_create_subscription_renewal_order_is_tenant_scoped_and_returns_payment_link",
        "test_create_subscription_renewal_order_keeps_order_when_payment_unavailable",
        "/api/v1/tenant/subscription/status",
        "/api/v1/tenant/subscription/invoices",
        "/api/v1/tenant/subscription/renewal-orders",
        "subscriptions:read",
        "subscriptions:write",
        "PaymentUnavailableError",
        "payment_available",
        "payment_failure_reason",
        "subscription_id",
        "plan_id",
        "invoice_id",
        "payment_url",
        "provider_trade_no",
    ]
    if not runtime_tests_path.is_file():
        missing.append("tests/test_tenant_admin_runtime_auth.py")
    missing.extend(
        f"tests/test_tenant_admin_runtime_auth.py:{marker}"
        for marker in required_runtime_test_markers
        if marker not in runtime_tests
    )
    required_service_test_markers = [
        "test_get_tenant_subscription_summary_returns_plan_and_period_without_internal_ids",
        "test_get_tenant_subscription_summary_returns_none_for_missing_tenant",
        "test_list_tenant_subscription_invoices_returns_tenant_scoped_safe_summaries",
        "test_list_tenant_subscription_invoices_clamps_limit_and_orders_by_created_at_id",
        "test_list_tenant_subscription_invoices_rejects_invalid_status_and_limit",
        "subscription_id",
        "plan_id",
        "invoice_id",
    ]
    if not service_tests_path.is_file():
        missing.append("tests/test_subscription_service.py")
    missing.extend(
        f"tests/test_subscription_service.py:{marker}"
        for marker in required_service_test_markers
        if marker not in service_tests
    )
    required_openapi_test_markers = [
        "test_subscription_operations_are_documented_as_tenant_admin",
        "test_subscription_schema_exposes_safe_fields_only",
        "TenantSubscriptionResponse",
        "TenantSubscriptionInvoiceItem",
        "ListTenantSubscriptionInvoicesResponse",
        "CreateTenantSubscriptionRenewalOrderRequest",
        "TenantSubscriptionRenewalOrderResponse",
        "/api/v1/tenant/subscription/status",
        "/api/v1/tenant/subscription/invoices",
        "/api/v1/tenant/subscription/renewal-orders",
        "payment_available",
        "payment_failure_reason",
        "subscription_id",
        "plan_id",
        "invoice_id",
        "payment_url",
        "provider_trade_no",
    ]
    if not openapi_tests_path.is_file():
        missing.append("tests/test_openapi_security_contract.py")
    missing.extend(
        f"tests/test_openapi_security_contract.py:{marker}"
        for marker in required_openapi_test_markers
        if marker not in openapi_tests
    )
    required_scope_test_markers = [
        '"subscriptions:read"',
        '"subscriptions:write"',
        'has_scope(["subscriptions:read"], "subscriptions:read")',
        'has_scope(["subscriptions:write"], "subscriptions:write")',
        'has_scope(["orders:read"], "subscriptions:read")',
        'has_scope(["subscriptions:read"], "subscriptions:write")',
    ]
    if not api_key_scope_tests_path.is_file():
        missing.append("tests/test_api_key_scopes.py")
    missing.extend(
        f"tests/test_api_key_scopes.py:{marker}"
        for marker in required_scope_test_markers
        if marker not in api_key_scope_tests
    )
    if missing:
        return ReadinessCheck("tenant_admin_subscription_read_contract", FAIL, f"missing markers: {', '.join(missing)}")
    return ReadinessCheck(
        "tenant_admin_subscription_read_contract",
        PASS,
        "Tenant Admin subscription API is subscriptions:read/write scoped, tenant-scoped and exposes safe plan, lifecycle, invoice and renewal-order summaries without tenant internals, upstream trade numbers, payloads or credentials; renewal creation may return a payment URL only for the newly created order",
    )


def _check_tenant_admin_supply_reseller_contract(project_root: Path) -> ReadinessCheck:
    tenant_admin = _read_optional(project_root / "app" / "web" / "tenant_admin.py")
    api_keys = _read_optional(project_root / "app" / "services" / "api_keys.py")
    supply_service = _read_optional(project_root / "app" / "services" / "supply.py")
    runtime_tests_path = project_root / "tests" / "test_tenant_admin_runtime_auth.py"
    runtime_tests = _read_optional(runtime_tests_path)
    service_tests_path = project_root / "tests" / "test_supply_service.py"
    service_tests = _read_optional(service_tests_path)
    openapi_tests_path = project_root / "tests" / "test_openapi_security_contract.py"
    openapi_tests = _read_optional(openapi_tests_path)
    api_key_scope_tests_path = project_root / "tests" / "test_api_key_scopes.py"
    api_key_scope_tests = _read_optional(api_key_scope_tests_path)
    roadmap_path = project_root / "docs" / "实施路线图.md"
    handoff_path = project_root / "docs" / "开发交接说明.md"
    full_plan_path = project_root / "docs" / "多租户发卡平台完整方案.md"
    roadmap = _read_optional(roadmap_path)
    handoff = _read_optional(handoff_path)
    full_plan = _read_optional(full_plan_path)
    required_tenant_admin_markers = [
        "TenantSupplyMarketOfferItem",
        "ListTenantSupplyMarketOffersResponse",
        "CreateTenantResellerApplicationRequest",
        "TenantResellerApplicationItem",
        "ListTenantResellerApplicationsResponse",
        "CreateTenantResellerProductRequest",
        "TenantCreatedResellerProductItem",
        "TenantResellerProductItem",
        "ListTenantResellerProductsResponse",
        '"/supply/market-offers"',
        '"/supply/applications"',
        '"/supply/reseller-products"',
        'require_scope("supply:read")',
        'require_scope("supply:write")',
        "SupplyService",
        "list_market_offers",
        "apply_reseller",
        "list_my_reseller_applications",
        "create_reseller_product",
        "list_reseller_products",
        "load_tenant_feature_flags",
        "tenant_feature_disabled_message",
        "_require_tenant_admin_feature",
        '_require_tenant_admin_feature(session, api_key.tenant_id, "reseller")',
        "reseller_tenant_id=api_key.tenant_id",
        "requested_by_user_id=None",
        "_supply_market_offer_response",
        "_reseller_application_response",
        "_created_reseller_product_response",
        "_reseller_product_response",
        "供货代理申请参数无效",
        "代理商品参数无效",
    ]
    missing = [
        f"app/web/tenant_admin.py:{marker}"
        for marker in required_tenant_admin_markers
        if marker not in tenant_admin
    ]
    required_scope_markers = ['"supply:read"', '"supply:write"']
    missing.extend(
        f"app/services/api_keys.py:{marker}"
        for marker in required_scope_markers
        if marker not in api_keys
    )
    required_service_markers = [
        "SupplierOfferSummary",
        "ResellerApplicationSummary",
        "CreatedResellerProduct",
        "ResellerProductSummary",
        "list_market_offers",
        "apply_reseller",
        "list_my_reseller_applications",
        "create_reseller_product",
        "list_reseller_products",
        "update_reseller_product_metadata",
        "update_reseller_product_sales",
        "get_reseller_product_summary",
        "SupplierOffer.supplier_tenant_id != reseller_tenant_id",
        "ResellerProduct.reseller_tenant_id == reseller_tenant_id",
        "hide_supplier=True",
        "category_provided",
        "sort_order",
        "actor_user_id: Optional[int]",
    ]
    if not (project_root / "app" / "services" / "supply.py").is_file():
        missing.append("app/services/supply.py")
    missing.extend(
        f"app/services/supply.py:{marker}"
        for marker in required_service_markers
        if marker not in supply_service
    )
    required_runtime_test_markers = [
        "test_list_supply_market_requires_supply_read_scope_before_service",
        "test_list_supply_market_is_tenant_scoped_and_redacted",
        "test_list_reseller_applications_requires_supply_read_scope_before_service",
        "test_list_reseller_applications_is_tenant_scoped_and_redacted",
        "test_create_reseller_application_requires_supply_write_before_service",
        "test_create_reseller_application_rejects_extra_fields_before_service",
        "test_create_reseller_application_is_tenant_scoped_and_redacted",
        "test_create_reseller_application_value_error_returns_400_without_secret",
        "test_list_reseller_products_requires_supply_read_scope_before_service",
        "test_list_reseller_products_is_tenant_scoped_and_redacted",
        "test_create_reseller_product_requires_supply_write_before_service",
        "test_create_reseller_product_rejects_extra_fields_before_service",
        "test_create_reseller_product_is_tenant_scoped_and_redacted",
        "test_create_reseller_product_value_error_returns_400_without_secret",
        "test_reseller_supply_routes_reject_disabled_reseller_feature_before_service",
        "代理售卖功能已关闭",
        "_assert_json_keys_absent",
        "/api/v1/tenant/supply/market-offers",
        "/api/v1/tenant/supply/applications",
        "/api/v1/tenant/supply/reseller-products",
        "supplier_tenant_id",
        "reseller_tenant_id",
        "product_id",
        "variant_id",
        "storage_key",
        "token",
        "secret",
        "self.assertNotIn(\"供应商\", response.text)",
        "self.assertNotIn(\"代理商\", response.text)",
    ]
    if not runtime_tests_path.is_file():
        missing.append("tests/test_tenant_admin_runtime_auth.py")
    missing.extend(
        f"tests/test_tenant_admin_runtime_auth.py:{marker}"
        for marker in required_runtime_test_markers
        if marker not in runtime_tests
    )
    required_service_test_markers = [
        "test_create_supplier_offer_rejects_invalid_price_before_query",
        "test_create_reseller_product_rejects_invalid_sale_price_before_query",
        "test_update_reseller_product_sales_rejects_invalid_payload_before_query",
        "_NoQuerySession",
        "execute_count",
        "add_count",
        "flush_count",
    ]
    if not service_tests_path.is_file():
        missing.append("tests/test_supply_service.py")
    missing.extend(
        f"tests/test_supply_service.py:{marker}"
        for marker in required_service_test_markers
        if marker not in service_tests
    )
    required_openapi_test_markers = [
        "test_supply_operations_are_documented_as_tenant_admin",
        "test_supply_schema_exposes_safe_fields_only",
        "ListTenantSupplyMarketOffersResponse",
        "TenantSupplyMarketOfferItem",
        "CreateTenantResellerApplicationRequest",
        "TenantResellerApplicationItem",
        "ListTenantResellerApplicationsResponse",
        "CreateTenantResellerProductRequest",
        "TenantCreatedResellerProductItem",
        "TenantResellerProductItem",
        "ListTenantResellerProductsResponse",
        "/api/v1/tenant/supply/market-offers",
        "/api/v1/tenant/supply/applications",
        "/api/v1/tenant/supply/reseller-products",
        "additionalProperties",
        "supplier_tenant_id",
        "reseller_tenant_id",
        "product_id",
        "variant_id",
        "storage_key",
        "token",
        "secret",
    ]
    if not openapi_tests_path.is_file():
        missing.append("tests/test_openapi_security_contract.py")
    missing.extend(
        f"tests/test_openapi_security_contract.py:{marker}"
        for marker in required_openapi_test_markers
        if marker not in openapi_tests
    )
    required_scope_test_markers = [
        '"supply:read"',
        '"supply:write"',
        'has_scope(["supply:read"], "supply:read")',
        'has_scope(["supply:write"], "supply:write")',
        'has_scope(["supply:read"], "supply:write")',
    ]
    if not api_key_scope_tests_path.is_file():
        missing.append("tests/test_api_key_scopes.py")
    missing.extend(
        f"tests/test_api_key_scopes.py:{marker}"
        for marker in required_scope_test_markers
        if marker not in api_key_scope_tests
    )
    required_document_markers = {
        roadmap_path: [
            "Tenant Admin 供货/代理商侧最小 API",
            "`GET /api/v1/tenant/supply/market-offers`",
            "`POST /api/v1/tenant/supply/reseller-products`",
            "`supply:read`",
            "`supply:write`",
            "不返回 `supplier_tenant_id`",
            "不返回 `product_id`",
            "Tenant Admin API 已同步接入功能开关业务防线",
        ],
        handoff_path: [
            "Tenant Admin 供货/代理商侧最小 API",
            "`GET /api/v1/tenant/supply/market-offers`",
            "`POST /api/v1/tenant/supply/reseller-products`",
            "`supply:read`",
            "`supply:write`",
            "不得输出 `supplier_tenant_id`",
            "不得输出 `product_id`",
            "Tenant Admin API 已同步接入功能开关业务防线",
        ],
        full_plan_path: [
            "Tenant Admin 供货/代理商侧最小 API",
            "GET    /api/v1/tenant/supply/market-offers",
            "POST   /api/v1/tenant/supply/reseller-products",
            "`supply:read`",
            "`supply:write`",
            "Tenant Admin 供应商侧供货 API",
            "Tenant Admin API 已同步接入功能开关业务防线",
        ],
    }
    document_texts = {
        roadmap_path: roadmap,
        handoff_path: handoff,
        full_plan_path: full_plan,
    }
    for path, markers in required_document_markers.items():
        if not path.is_file():
            missing.append(str(path.relative_to(project_root)))
        missing.extend(
            f"{path.relative_to(project_root)}:{marker}"
            for marker in markers
            if marker not in document_texts[path]
        )
    if missing:
        return ReadinessCheck("tenant_admin_supply_reseller_contract", FAIL, f"missing markers: {', '.join(missing)}")
    return ReadinessCheck(
        "tenant_admin_supply_reseller_contract",
        PASS,
        "Tenant Admin supply/reseller API has supply scopes, reseller-side market/application/product routes, tenant scoping, feature-flag guardrails, safe DTOs and tests that avoid supplier tenant, product, inventory, file or credential leakage",
    )


def _check_tenant_admin_supply_supplier_contract(project_root: Path) -> ReadinessCheck:
    tenant_admin = _read_optional(project_root / "app" / "web" / "tenant_admin.py")
    supply_service = _read_optional(project_root / "app" / "services" / "supply.py")
    runtime_tests_path = project_root / "tests" / "test_tenant_admin_runtime_auth.py"
    runtime_tests = _read_optional(runtime_tests_path)
    service_tests_path = project_root / "tests" / "test_supply_service.py"
    service_tests = _read_optional(service_tests_path)
    openapi_tests_path = project_root / "tests" / "test_openapi_security_contract.py"
    openapi_tests = _read_optional(openapi_tests_path)
    roadmap_path = project_root / "docs" / "实施路线图.md"
    handoff_path = project_root / "docs" / "开发交接说明.md"
    full_plan_path = project_root / "docs" / "多租户发卡平台完整方案.md"
    roadmap = _read_optional(roadmap_path)
    handoff = _read_optional(handoff_path)
    full_plan = _read_optional(full_plan_path)
    required_tenant_admin_markers = [
        "TenantSupplierOfferItem",
        "ListTenantSupplierOffersResponse",
        "CreateTenantSupplierOfferRequest",
        "TenantCreatedSupplierOfferItem",
        "UpdateTenantSupplierOfferApprovalRequest",
        "TenantSupplierOfferApprovalItem",
        "TenantSupplierApplicationItem",
        "ListTenantSupplierApplicationsResponse",
        "ApproveTenantSupplierApplicationRequest",
        "RejectTenantSupplierApplicationRequest",
        '"/supply/supplier-offers"',
        '"/supply/supplier-offers/{supplier_offer_id}/approval"',
        '"/supply/supplier-applications"',
        '"/supply/supplier-applications/approve"',
        '"/supply/supplier-applications/reject"',
        'require_scope("supply:read")',
        'require_scope("supply:write")',
        "list_supplier_offers",
        "create_supplier_offer",
        "set_supplier_offer_approval",
        "list_reseller_applications",
        "approve_reseller_application",
        "reject_reseller_application",
        "load_tenant_feature_flags",
        "tenant_feature_disabled_message",
        "_require_tenant_admin_feature",
        '_require_tenant_admin_feature(session, api_key.tenant_id, "supplier")',
        "supplier_tenant_id=api_key.tenant_id",
        "actor_user_id=None",
        "_tenant_supplier_offer_response",
        "_created_supplier_offer_response",
        "_supplier_offer_approval_response",
        "_supplier_application_response",
        "供货商品参数无效",
        "供货审批参数无效",
        "代理审批参数无效",
        "代理拒绝参数无效",
    ]
    missing = [
        f"app/web/tenant_admin.py:{marker}"
        for marker in required_tenant_admin_markers
        if marker not in tenant_admin
    ]
    required_service_markers = [
        "SupplierOwnOfferSummary",
        "CreatedSupplierOffer",
        "SupplierApprovalSetting",
        "ResellerApplicationSummary",
        "list_supplier_offers",
        "create_supplier_offer",
        "set_supplier_offer_approval",
        "list_reseller_applications",
        "approve_reseller_application",
        "reject_reseller_application",
        "_require_pending_reseller_application",
        "_get_supplier_product",
        "Product.tenant_id == supplier_tenant_id",
        "_get_supplier_offer_details",
        "offer.supplier_tenant_id != supplier_tenant_id",
        "product.product_type != \"self\"",
        "product.status != \"on\"",
        "variant.status != \"on\"",
        "product.delivery_type not in SUPPORTED_RESELLER_DELIVERY_TYPES",
        "hidden_supplier_allowed=True",
        "rule is None or rule.status != \"pending\"",
        "actor_user_id: Optional[int]",
    ]
    if not (project_root / "app" / "services" / "supply.py").is_file():
        missing.append("app/services/supply.py")
    missing.extend(
        f"app/services/supply.py:{marker}"
        for marker in required_service_markers
        if marker not in supply_service
    )
    required_runtime_test_markers = [
        "test_list_supplier_offers_requires_supply_read_scope_before_service",
        "test_list_supplier_offers_is_tenant_scoped_and_redacted",
        "test_create_supplier_offer_requires_supply_write_before_service",
        "test_create_supplier_offer_rejects_extra_fields_before_service",
        "test_create_supplier_offer_is_tenant_scoped_and_redacted",
        "test_create_supplier_offer_value_error_returns_400_without_secret",
        "test_update_supplier_offer_approval_requires_supply_write_before_service",
        "test_update_supplier_offer_approval_rejects_extra_fields_before_service",
        "test_update_supplier_offer_approval_is_tenant_scoped_and_redacted",
        "test_update_supplier_offer_approval_value_error_returns_400_without_secret",
        "test_list_supplier_applications_requires_supply_read_scope_before_service",
        "test_list_supplier_applications_is_tenant_scoped_and_redacted",
        "test_approve_supplier_application_requires_supply_write_before_service",
        "test_approve_supplier_application_rejects_extra_fields_before_service",
        "test_approve_supplier_application_is_tenant_scoped_and_redacted",
        "test_approve_supplier_application_value_error_returns_400_without_secret",
        "test_reject_supplier_application_requires_supply_write_before_service",
        "test_reject_supplier_application_is_tenant_scoped_and_redacted",
        "test_reject_supplier_application_value_error_returns_400_without_secret",
        "test_supplier_supply_routes_reject_disabled_supplier_feature_before_service",
        "供货功能已关闭",
        "/api/v1/tenant/supply/supplier-offers",
        "/api/v1/tenant/supply/supplier-applications",
        "_assert_json_keys_absent",
        "supplier_tenant_id=7",
        "actor_user_id=None",
        "reseller_tenant_id",
        "reseller_store_name",
        "rule_id",
        "product_id",
        "variant_id",
        "storage_key",
        "token",
        "secret",
    ]
    if not runtime_tests_path.is_file():
        missing.append("tests/test_tenant_admin_runtime_auth.py")
    missing.extend(
        f"tests/test_tenant_admin_runtime_auth.py:{marker}"
        for marker in required_runtime_test_markers
        if marker not in runtime_tests
    )
    required_service_test_markers = [
        "test_create_supplier_offer_rejects_invalid_price_before_query",
        "test_create_supplier_offer_rejects_unsupported_delivery_type_before_offer_query",
        "test_approve_reseller_application_requires_existing_pending_rule_before_approval",
        "test_reject_reseller_application_requires_existing_pending_rule_before_rejection",
        "_require_pending_reseller_application",
        "approve_reseller.assert_not_awaited",
        "reject_reseller.assert_not_awaited",
    ]
    if not service_tests_path.is_file():
        missing.append("tests/test_supply_service.py")
    missing.extend(
        f"tests/test_supply_service.py:{marker}"
        for marker in required_service_test_markers
        if marker not in service_tests
    )
    required_openapi_test_markers = [
        "test_supply_supplier_operations_are_documented_as_tenant_admin",
        "test_supply_supplier_schema_exposes_safe_fields_only",
        "ListTenantSupplierOffersResponse",
        "CreateTenantSupplierOfferRequest",
        "TenantCreatedSupplierOfferItem",
        "UpdateTenantSupplierOfferApprovalRequest",
        "TenantSupplierApplicationItem",
        "ApproveTenantSupplierApplicationRequest",
        "RejectTenantSupplierApplicationRequest",
        "/api/v1/tenant/supply/supplier-offers",
        "/api/v1/tenant/supply/supplier-offers/{supplier_offer_id}/approval",
        "/api/v1/tenant/supply/supplier-applications",
        "/api/v1/tenant/supply/supplier-applications/approve",
        "/api/v1/tenant/supply/supplier-applications/reject",
        "additionalProperties",
        "reseller_tenant_id",
        "reseller_store_name",
        "supplier_response_forbidden",
        "metadata_json",
    ]
    if not openapi_tests_path.is_file():
        missing.append("tests/test_openapi_security_contract.py")
    missing.extend(
        f"tests/test_openapi_security_contract.py:{marker}"
        for marker in required_openapi_test_markers
        if marker not in openapi_tests
    )
    required_document_markers = {
        roadmap_path: [
            "Tenant Admin 供应商侧供货 API",
            "`POST /api/v1/tenant/supply/supplier-offers`",
            "`PATCH /api/v1/tenant/supply/supplier-offers/{supplier_offer_id}/approval`",
            "`POST /api/v1/tenant/supply/supplier-applications/approve`",
            "`POST /api/v1/tenant/supply/supplier-applications/reject`",
            "只允许处理已有 `pending` 申请",
            "供应商侧允许返回 `reseller_tenant_id`",
            "Tenant Admin API 已同步接入功能开关业务防线",
        ],
        handoff_path: [
            "Tenant Admin 供应商侧供货 API",
            "`POST /api/v1/tenant/supply/supplier-offers`",
            "`PATCH /api/v1/tenant/supply/supplier-offers/{supplier_offer_id}/approval`",
            "`POST /api/v1/tenant/supply/supplier-applications/approve`",
            "`POST /api/v1/tenant/supply/supplier-applications/reject`",
            "只允许处理已有 `pending` 申请",
            "供应商侧允许返回 `reseller_tenant_id`",
            "Tenant Admin API 已同步接入功能开关业务防线",
        ],
        full_plan_path: [
            "Tenant Admin 供应商侧供货 API",
            "POST   /api/v1/tenant/supply/supplier-offers",
            "PATCH  /api/v1/tenant/supply/supplier-offers/{supplier_offer_id}/approval",
            "POST   /api/v1/tenant/supply/supplier-applications/approve",
            "POST   /api/v1/tenant/supply/supplier-applications/reject",
            "只允许处理已有 `pending` 申请",
            "平台审核仍后续",
            "Tenant Admin API 已同步接入功能开关业务防线",
        ],
    }
    document_texts = {
        roadmap_path: roadmap,
        handoff_path: handoff,
        full_plan_path: full_plan,
    }
    for path, markers in required_document_markers.items():
        if not path.is_file():
            missing.append(str(path.relative_to(project_root)))
        missing.extend(
            f"{path.relative_to(project_root)}:{marker}"
            for marker in markers
            if marker not in document_texts[path]
        )
    if missing:
        return ReadinessCheck("tenant_admin_supply_supplier_contract", FAIL, f"missing markers: {', '.join(missing)}")
    return ReadinessCheck(
        "tenant_admin_supply_supplier_contract",
        PASS,
        "Tenant Admin supplier-side supply API has offer creation, approval toggle and pending application review routes with supply scopes, tenant scoping, feature-flag guardrails, strict pending-review semantics and role-specific safe DTOs",
    )


def _check_tenant_admin_supply_supplier_rule_contract(project_root: Path) -> ReadinessCheck:
    tenant_admin = _read_optional(project_root / "app" / "web" / "tenant_admin.py")
    supply_service = _read_optional(project_root / "app" / "services" / "supply.py")
    runtime_tests_path = project_root / "tests" / "test_tenant_admin_runtime_auth.py"
    runtime_tests = _read_optional(runtime_tests_path)
    service_tests_path = project_root / "tests" / "test_supply_service.py"
    service_tests = _read_optional(service_tests_path)
    openapi_tests_path = project_root / "tests" / "test_openapi_security_contract.py"
    openapi_tests = _read_optional(openapi_tests_path)
    roadmap_path = project_root / "docs" / "实施路线图.md"
    handoff_path = project_root / "docs" / "开发交接说明.md"
    full_plan_path = project_root / "docs" / "多租户发卡平台完整方案.md"
    roadmap = _read_optional(roadmap_path)
    handoff = _read_optional(handoff_path)
    full_plan = _read_optional(full_plan_path)
    required_tenant_admin_markers = [
        "SetTenantSupplierRuleRequest",
        'extra="forbid"',
        '"/supply/supplier-rules"',
        'require_scope("supply:write")',
        "set_existing_reseller_rule",
        "supplier_tenant_id=api_key.tenant_id",
        "actor_user_id=None",
        "pricing_value",
        "min_sale_price",
        "代理规则参数无效",
        "_supplier_application_response",
    ]
    missing = [
        f"app/web/tenant_admin.py:{marker}"
        for marker in required_tenant_admin_markers
        if marker not in tenant_admin
    ]
    required_service_markers = [
        "set_existing_reseller_rule",
        "_validate_reseller_rule(pricing_value, min_sale_price)",
        "_get_supplier_offer_details",
        "offer.supplier_tenant_id != supplier_tenant_id",
        'rule is None or rule.status not in {"pending", "active"}',
        "approve_reseller(",
        "actor_user_id: Optional[int]",
    ]
    if not (project_root / "app" / "services" / "supply.py").is_file():
        missing.append("app/services/supply.py")
    missing.extend(
        f"app/services/supply.py:{marker}"
        for marker in required_service_markers
        if marker not in supply_service
    )
    required_runtime_test_markers = [
        "test_set_supplier_rule_requires_supply_write_before_service",
        "test_set_supplier_rule_rejects_extra_fields_before_service",
        "test_set_supplier_rule_rejects_invalid_schema_before_service",
        "test_set_supplier_rule_requires_signature_before_service",
        "test_set_supplier_rule_is_tenant_scoped_and_redacted",
        "test_set_supplier_rule_value_error_returns_400_without_secret",
        "/api/v1/tenant/supply/supplier-rules",
        "set_existing_reseller_rule",
        "_assert_json_keys_absent",
        "supplier_tenant_id=7",
        "actor_user_id=None",
        "rule_id",
        "supplier_tenant_id",
        "supplier_store_name",
        "product_id",
        "variant_id",
        "storage_key",
        "token",
        "secret",
    ]
    if not runtime_tests_path.is_file():
        missing.append("tests/test_tenant_admin_runtime_auth.py")
    missing.extend(
        f"tests/test_tenant_admin_runtime_auth.py:{marker}"
        for marker in required_runtime_test_markers
        if marker not in runtime_tests
    )
    required_service_test_markers = [
        "test_set_existing_reseller_rule_rejects_invalid_price_before_query",
        "test_set_existing_reseller_rule_requires_existing_pending_or_active_rule_before_write",
        "test_set_existing_reseller_rule_delegates_with_actor_none_for_existing_rule",
        "_NoQuerySession",
        "approve_reseller.assert_not_awaited",
        "actor_user_id=None",
    ]
    if not service_tests_path.is_file():
        missing.append("tests/test_supply_service.py")
    missing.extend(
        f"tests/test_supply_service.py:{marker}"
        for marker in required_service_test_markers
        if marker not in service_tests
    )
    required_openapi_test_markers = [
        "test_supply_supplier_rule_operation_is_documented_as_tenant_admin",
        "test_supply_supplier_rule_schema_exposes_safe_fields_only",
        "SetTenantSupplierRuleRequest",
        "TenantSupplierApplicationItem",
        "/api/v1/tenant/supply/supplier-rules",
        "additionalProperties",
        "x-fakabot-signature",
        "supplier_offer_id",
        "reseller_tenant_id",
        "pricing_value",
        "min_sale_price",
        "rule_id",
        "supplier_tenant_id",
        "supplier_store_name",
        "product_id",
        "variant_id",
        "storage_key",
        "token",
        "secret",
    ]
    if not openapi_tests_path.is_file():
        missing.append("tests/test_openapi_security_contract.py")
    missing.extend(
        f"tests/test_openapi_security_contract.py:{marker}"
        for marker in required_openapi_test_markers
        if marker not in openapi_tests
    )
    required_document_markers = {
        roadmap_path: [
            "`POST /api/v1/tenant/supply/supplier-rules`",
            "`pricing_value`",
            "`min_sale_price`",
            "不创建不存在的代理规则",
            "不暴露 `rule_id`",
            "独立代理规则 HTTP 最小切片已完成",
        ],
        handoff_path: [
            "`POST /api/v1/tenant/supply/supplier-rules`",
            "`pricing_value`",
            "`min_sale_price`",
            "不创建不存在的代理规则",
            "不返回 `rule_id`",
            "Tenant Admin 独立代理规则 HTTP API 合同检查",
        ],
        full_plan_path: [
            "POST   /api/v1/tenant/supply/supplier-rules",
            "`pricing_value`",
            "`min_sale_price`",
            "不创建不存在的代理规则",
            "不返回 `rule_id`",
            "独立代理规则最小 HTTP 切片已完成",
        ],
    }
    document_texts = {
        roadmap_path: roadmap,
        handoff_path: handoff,
        full_plan_path: full_plan,
    }
    for path, markers in required_document_markers.items():
        if not path.is_file():
            missing.append(str(path.relative_to(project_root)))
        missing.extend(
            f"{path.relative_to(project_root)}:{marker}"
            for marker in markers
            if marker not in document_texts[path]
        )
    if missing:
        return ReadinessCheck(
            "tenant_admin_supply_supplier_rule_contract",
            FAIL,
            f"missing markers: {', '.join(missing)}",
        )
    return ReadinessCheck(
        "tenant_admin_supply_supplier_rule_contract",
        PASS,
        "Tenant Admin supplier-side reseller rule API is supply:write scoped, tenant-scoped, request-whitelisted, generic on errors, limited to existing pending/active reseller relationships and redacted in response; platform review, platform takedown and real settlement integration remain separate gates",
    )


def _check_platform_admin_supply_offer_status_contract(project_root: Path) -> ReadinessCheck:
    platform_admin_path = project_root / "app" / "web" / "platform_admin.py"
    platform_admin = _read_optional(platform_admin_path)
    tenant_admin = _read_optional(project_root / "app" / "web" / "tenant_admin.py")
    supply_service_path = project_root / "app" / "services" / "supply.py"
    supply_service = _read_optional(supply_service_path)
    api_keys = _read_optional(project_root / "app" / "services" / "api_keys.py")
    runtime_tests_path = project_root / "tests" / "test_platform_admin_runtime_auth.py"
    runtime_tests = _read_optional(runtime_tests_path)
    service_tests_path = project_root / "tests" / "test_supply_service.py"
    service_tests = _read_optional(service_tests_path)
    openapi_tests_path = project_root / "tests" / "test_openapi_security_contract.py"
    openapi_tests = _read_optional(openapi_tests_path)
    app_runtime_tests_path = project_root / "tests" / "test_app_runtime_smoke.py"
    app_runtime_tests = _read_optional(app_runtime_tests_path)
    roadmap_path = project_root / "docs" / "实施路线图.md"
    handoff_path = project_root / "docs" / "开发交接说明.md"
    full_plan_path = project_root / "docs" / "多租户发卡平台完整方案.md"
    roadmap = _read_optional(roadmap_path)
    handoff = _read_optional(handoff_path)
    full_plan = _read_optional(full_plan_path)

    missing: list[str] = []
    required_platform_admin_markers = [
        "PlatformSupplierOfferItem",
        "ListPlatformSupplierOffersResponse",
        "UpdatePlatformSupplierOfferStatusRequest",
        '"/supply/supplier-offers"',
        '"/supply/supplier-offers/{supplier_offer_id}/status"',
        'require_platform_scope("platform_supply:read")',
        'require_platform_scope("platform_supply:write")',
        "list_platform_supplier_offers",
        "set_platform_supplier_offer_status",
        "_platform_supplier_offer_response",
        "_safe_platform_supply_error_detail",
        "平台供货管控参数无效",
    ]
    if not platform_admin_path.is_file():
        missing.append("app/web/platform_admin.py")
    missing.extend(
        f"app/web/platform_admin.py:{marker}"
        for marker in required_platform_admin_markers
        if marker not in platform_admin
    )

    required_service_markers = [
        "PlatformSupplierOfferSummary",
        "PLATFORM_SUPPLIER_OFFER_STATUSES",
        "list_platform_supplier_offers",
        "set_platform_supplier_offer_status",
        'SupplierOffer.status != "deleted"',
        'Product.status != "deleted"',
        "platform_supply.supplier_offer_status_updated",
        "_safe_platform_supply_reason",
        "内容已隐藏",
    ]
    if not supply_service_path.is_file():
        missing.append("app/services/supply.py")
    missing.extend(
        f"app/services/supply.py:{marker}"
        for marker in required_service_markers
        if marker not in supply_service
    )

    forbidden_api_key_scopes = ["platform_supply:read", "platform_supply:write"]
    forbidden_scope_present = [scope for scope in forbidden_api_key_scopes if scope in api_keys]
    if forbidden_scope_present:
        missing.append(
            "app/services/api_keys.py:platform_supply scopes must not be in TenantApiKey scopes "
            f"({', '.join(forbidden_scope_present)})"
        )

    forbidden_tenant_admin_markers = [
        "PlatformSupplierOfferItem",
        "platform_supply",
        "/api/v1/platform/supply",
    ]
    forbidden_tenant_admin_present = [
        marker for marker in forbidden_tenant_admin_markers if marker in tenant_admin
    ]
    if forbidden_tenant_admin_present:
        missing.append(
            "app/web/tenant_admin.py:must not expose Platform Admin supply controls "
            f"({', '.join(forbidden_tenant_admin_present)})"
        )

    required_runtime_test_markers = [
        "test_platform_supply_supplier_offers_rejects_tenant_api_key_before_service",
        "test_platform_supply_supplier_offers_requires_valid_platform_key_before_service",
        "test_platform_supply_supplier_offers_returns_safe_payload_only",
        "test_platform_supply_supplier_offer_status_requires_platform_supply_write_before_service",
        "test_platform_supply_supplier_offer_status_requires_signature_before_service",
        "test_platform_supply_supplier_offer_status_rejects_extra_fields_before_service",
        "test_platform_supply_supplier_offer_status_value_error_returns_400_without_secret",
        "test_platform_supply_supplier_offer_status_is_platform_scoped_and_redacted",
        "/api/v1/platform/supply/supplier-offers",
        "/api/v1/platform/supply/supplier-offers/91/status",
        "X-Platform-API-Key",
        "X-API-Key",
        "rule_id",
        "product_id",
        "variant_id",
        "token",
        "secret",
        "api_key",
    ]
    if not runtime_tests_path.is_file():
        missing.append("tests/test_platform_admin_runtime_auth.py")
    missing.extend(
        f"tests/test_platform_admin_runtime_auth.py:{marker}"
        for marker in required_runtime_test_markers
        if marker not in runtime_tests
    )

    required_service_test_markers = [
        "test_list_platform_supplier_offers_rejects_invalid_status_before_query",
        "test_set_platform_supplier_offer_status_rejects_invalid_status_before_query",
        "test_set_platform_supplier_offer_status_changes_only_offer_status_and_audits",
        "test_set_platform_supplier_offer_status_is_idempotent_when_already_disabled",
        "platform_supply.supplier_offer_status_updated",
        "内容已隐藏",
        "AuditLog",
        "_NoQuerySession",
    ]
    if not service_tests_path.is_file():
        missing.append("tests/test_supply_service.py")
    missing.extend(
        f"tests/test_supply_service.py:{marker}"
        for marker in required_service_test_markers
        if marker not in service_tests
    )

    required_openapi_test_markers = [
        "test_platform_supply_operations_are_documented_as_platform_admin",
        "test_platform_supply_supplier_offer_schema_exposes_safe_fields_only",
        "ListPlatformSupplierOffersResponse",
        "PlatformSupplierOfferItem",
        "UpdatePlatformSupplierOfferStatusRequest",
        "/api/v1/platform/supply/supplier-offers",
        "/api/v1/platform/supply/supplier-offers/{supplier_offer_id}/status",
        "PlatformAdminBearer",
        "PlatformAdminApiKeyHeader",
        "X-Platform-API-Key",
        "X-API-Key",
        "PLATFORM_ADMIN_REQUIRE_SIGNATURE",
        "additionalProperties",
        "supplier_tenant_id",
        "supplier_store_name",
        "product_id",
        "variant_id",
        "rule_id",
        "reseller_tenant_id",
        "pricing_value",
        "credentials",
        "raw_payload",
        "metadata_json",
    ]
    if not openapi_tests_path.is_file():
        missing.append("tests/test_openapi_security_contract.py")
    missing.extend(
        f"tests/test_openapi_security_contract.py:{marker}"
        for marker in required_openapi_test_markers
        if marker not in openapi_tests
    )

    required_app_runtime_markers = [
        "/api/v1/platform/supply/supplier-offers",
        "/api/v1/platform/supply/supplier-offers/{supplier_offer_id}/status",
    ]
    if not app_runtime_tests_path.is_file():
        missing.append("tests/test_app_runtime_smoke.py")
    missing.extend(
        f"tests/test_app_runtime_smoke.py:{marker}"
        for marker in required_app_runtime_markers
        if marker not in app_runtime_tests
    )

    required_document_markers = {
        roadmap_path: [
            "Platform Admin 供货商品状态管控 API",
            "GET /api/v1/platform/supply/supplier-offers",
            "PATCH /api/v1/platform/supply/supplier-offers/{supplier_offer_id}/status",
            "不触发真实分账",
            "下架不是删除数据",
        ],
        handoff_path: [
            "Platform Admin 供货商品状态管控 API",
            "`platform_supply:read`",
            "`platform_supply:write`",
            "不复用 Tenant Admin API Key",
            "禁止内部商品/档位、规则、库存、凭据",
        ],
        full_plan_path: [
            "Platform Admin 供货商品状态管控 API",
            "GET    /api/v1/platform/supply/supplier-offers",
            "PATCH  /api/v1/platform/supply/supplier-offers/{supplier_offer_id}/status",
            "状态管控最小 HTTP 切片已完成",
            "真实分账仍后续",
        ],
    }
    document_texts = {
        roadmap_path: roadmap,
        handoff_path: handoff,
        full_plan_path: full_plan,
    }
    for path, markers in required_document_markers.items():
        if not path.is_file():
            missing.append(str(path.relative_to(project_root)))
        missing.extend(
            f"{path.relative_to(project_root)}:{marker}"
            for marker in markers
            if marker not in document_texts[path]
        )

    if missing:
        return ReadinessCheck(
            "platform_admin_supply_offer_status_contract",
            FAIL,
            f"missing markers: {', '.join(missing)}",
        )
    return ReadinessCheck(
        "platform_admin_supply_offer_status_contract",
        PASS,
        "Platform Admin supply offer status API is independently authenticated, platform-scoped, read/write scoped, request-whitelisted and can list or set supplier offer status on/disabled without Tenant Admin scopes, internal IDs, credentials, inventory content, deletion, settlement or downstream rule mutation",
    )


def _check_tenant_admin_finance_withdrawal_contract(project_root: Path) -> ReadinessCheck:
    tenant_admin = _read_optional(project_root / "app" / "web" / "tenant_admin.py")
    ledger_service = _read_optional(project_root / "app" / "services" / "ledger.py")
    api_keys = _read_optional(project_root / "app" / "services" / "api_keys.py")
    finance_tests_path = project_root / "tests" / "test_tenant_admin_finance.py"
    finance_tests = _read_optional(finance_tests_path)
    openapi_tests_path = project_root / "tests" / "test_openapi_security_contract.py"
    openapi_tests = _read_optional(openapi_tests_path)
    api_key_scope_tests_path = project_root / "tests" / "test_api_key_scopes.py"
    api_key_scope_tests = _read_optional(api_key_scope_tests_path)
    required_tenant_admin_markers = [
        "TenantLedgerBalanceResponse",
        "TenantLedgerBalanceAuditResponse",
        "TenantWithdrawalItem",
        "ListTenantWithdrawalsResponse",
        "CreateTenantWithdrawalRequest",
        '"/finance/balance"',
        '"/finance/ledger/audit"',
        '"/finance/withdrawals"',
        '"/finance/withdrawals/{withdrawal_id}"',
        'require_scope("finance:read")',
        'require_scope("finance:write")',
        "LedgerService",
        "audit_account_balance",
        "create_withdrawal_request",
        "list_withdrawals",
        "get_withdrawal",
        "address_masked",
        "_ledger_balance_audit_response",
        "reviewed_at",
        "completed_at",
        "_mask_finance_address",
        "_safe_finance_error_detail",
        "_validate_withdrawal_amount",
        "提现金额最多支持 8 位小数",
    ]
    missing = [
        f"app/web/tenant_admin.py:{marker}"
        for marker in required_tenant_admin_markers
        if marker not in tenant_admin
    ]
    required_ledger_markers = [
        "async def audit_account_balance",
        "async def get_withdrawal",
        "WithdrawalRequest.tenant_id == tenant_id",
        "WithdrawalRequest.id == withdrawal_id",
        "reviewed_at=withdrawal.reviewed_at",
        "completed_at=withdrawal.completed_at",
    ]
    missing.extend(
        f"app/services/ledger.py:{marker}"
        for marker in required_ledger_markers
        if marker not in ledger_service
    )
    required_scope_markers = [
        '"finance:read"',
        '"finance:write"',
    ]
    missing.extend(
        f"app/services/api_keys.py:{marker}"
        for marker in required_scope_markers
        if marker not in api_keys
    )
    required_finance_test_markers = [
        "test_get_finance_balance_requires_finance_read_scope_before_service",
        "test_get_finance_balance_is_tenant_scoped",
        "test_get_finance_ledger_audit_requires_finance_read_scope_before_service",
        "test_get_finance_ledger_audit_is_tenant_scoped_and_safe",
        "test_list_withdrawals_requires_finance_read_scope_before_service",
        "test_list_withdrawals_is_tenant_scoped_and_redacted",
        "test_get_withdrawal_requires_finance_read_scope_before_service",
        "test_get_withdrawal_is_tenant_scoped_and_redacted",
        "test_get_withdrawal_returns_404_for_missing_or_cross_tenant",
        "test_create_withdrawal_requires_finance_write_scope_before_service",
        "test_create_withdrawal_commits_and_returns_masked_address",
        "test_create_withdrawal_value_error_returns_400_and_redacts_address",
        "test_create_withdrawal_runtime_error_returns_503_and_redacts_secret",
        "test_create_withdrawal_rejects_invalid_amount_precision_before_service",
    ]
    if not finance_tests_path.is_file():
        missing.append("tests/test_tenant_admin_finance.py")
    missing.extend(
        f"tests/test_tenant_admin_finance.py:{marker}"
        for marker in required_finance_test_markers
        if marker not in finance_tests
    )
    required_api_key_scope_test_markers = [
        '"finance:read"',
        '"finance:write"',
    ]
    if not api_key_scope_tests_path.is_file():
        missing.append("tests/test_api_key_scopes.py")
    missing.extend(
        f"tests/test_api_key_scopes.py:{marker}"
        for marker in required_api_key_scope_test_markers
        if marker not in api_key_scope_tests
    )
    required_openapi_test_markers = [
        "test_finance_operations_are_documented_as_tenant_admin",
        "test_finance_balance_schema_exposes_safe_fields_only",
        "test_finance_ledger_audit_schema_exposes_safe_fields_only",
        "test_withdrawal_schema_exposes_masked_address_only",
        "TenantLedgerBalanceResponse",
        "TenantLedgerBalanceAuditResponse",
        "TenantWithdrawalItem",
        "CreateTenantWithdrawalRequest",
        "address_masked",
        "/api/v1/tenant/finance/ledger/audit",
        "/api/v1/tenant/finance/withdrawals/{withdrawal_id}",
        "reviewed_at",
        "completed_at",
        "address",
    ]
    if not openapi_tests_path.is_file():
        missing.append("tests/test_openapi_security_contract.py")
    missing.extend(
        f"tests/test_openapi_security_contract.py:{marker}"
        for marker in required_openapi_test_markers
        if marker not in openapi_tests
    )
    if missing:
        return ReadinessCheck("tenant_admin_finance_withdrawal_contract", FAIL, f"missing markers: {', '.join(missing)}")
    return ReadinessCheck(
        "tenant_admin_finance_withdrawal_contract",
        PASS,
        "Tenant Admin finance API has finance scopes, balance, ledger audit and withdrawal request/list/detail routes, LedgerService wiring, masked address responses and contract tests",
    )


def _check_migration_verifier(project_root: Path) -> ReadinessCheck:
    verifier = _read_optional(project_root / "scripts" / "verify_migrations.py")
    versions_dir = project_root / "alembic" / "versions"
    revisions = sorted(versions_dir.glob("*.py")) if versions_dir.is_dir() else []
    required_markers = [
        "EXPECTED_HEAD",
        "20260610_0024",
        "EXPECTED_TABLES",
        "external_fulfillment_attempts",
        "trc20_direct_transfers",
        "online_upgrade_executed=false",
        "--sql",
    ]
    missing = [marker for marker in required_markers if marker not in verifier]
    if not revisions:
        missing.append("alembic/versions/*.py")
    if missing:
        return ReadinessCheck("migration_offline_verifier", FAIL, f"missing markers: {', '.join(missing)}")
    return ReadinessCheck(
        "migration_offline_verifier",
        PASS,
        f"offline verifier present; revisions={len(revisions)}; online migration not executed",
    )


def _check_compose_contract(project_root: Path) -> ReadinessCheck:
    compose = _read_optional(project_root / "docker-compose.yml")
    required_markers = [
        "postgres:",
        "redis:",
        "app:",
        "condition: service_healthy",
        "127.0.0.1:58001:58001",
        "/ready",
        "./storage:/app/storage",
    ]
    missing = [marker for marker in required_markers if marker not in compose]
    if missing:
        return ReadinessCheck("compose_contract", FAIL, f"missing markers: {', '.join(missing)}")
    return ReadinessCheck("compose_contract", PASS, "PostgreSQL, Redis, app healthcheck and storage mount documented")


def _check_worker_storefront(project_root: Path) -> ReadinessCheck:
    worker = _read_optional(project_root / "workers" / "storefront" / "src" / "worker.mjs")
    wrangler = _read_optional(project_root / "workers" / "storefront" / "wrangler.toml.example")
    required_worker_markers = [
        "PUBLIC_STORE_API_PREFIX",
        "proxyPublicStoreApi",
        "publicApiProxyHeaders",
        "shouldPollPublicOrder",
        "normalizePaymentUrl",
        "visibilitychange",
        "pageshow",
        "X-Telegram-Init-Data",
        "sessionStorage",
    ]
    required_wrangler_markers = ["PUBLIC_STORE_API_BASE_URL", "DEFAULT_TENANT_PUBLIC_ID"]
    missing = [marker for marker in required_worker_markers if marker not in worker] + [
        f"wrangler:{marker}" for marker in required_wrangler_markers if marker not in wrangler
    ]
    forbidden_worker_markers = ["TENANT_ADMIN_API_KEY", "PAYMENT_SECRET", "BOT_TOKEN"]
    leaked = [marker for marker in forbidden_worker_markers if marker in worker]
    if missing or leaked:
        detail = []
        if missing:
            detail.append(f"missing markers: {', '.join(missing)}")
        if leaked:
            detail.append(f"forbidden markers in worker: {', '.join(leaked)}")
        return ReadinessCheck("worker_storefront_contract", FAIL, "; ".join(detail))
    return ReadinessCheck(
        "worker_storefront_contract",
        PASS,
        "Worker storefront, same-origin proxy, WebApp initData forwarding and order polling are present",
    )


def _check_worker_storefront_error_states_contract(project_root: Path) -> ReadinessCheck:
    worker = _read_optional(project_root / "workers" / "storefront" / "src" / "worker.mjs")
    worker_test_path = project_root / "workers" / "storefront" / "test" / "worker.test.mjs"
    worker_test = _read_optional(worker_test_path)
    required_worker_markers = [
        "throw apiError(response.status, payload && payload.detail)",
        "apiErrorMessage",
        "safeErrorDetail",
        "请求过于频繁，请稍后再试",
        "服务暂不可用，请稍后重试",
        "订单状态暂时无法刷新，可稍后手动刷新",
        'renderOrder({ type: "warning", text: "订单状态暂时无法刷新，可稍后手动刷新" })',
        "支付链接无效，请联系商家",
        "state.paymentUrl = null",
        "normalizePaymentUrl",
        "data-refresh-order",
        "data-create-payment",
        "payment_url",
        "sessionStorage",
    ]
    required_test_markers = [
        "storefront browser script shows safe payment unavailable message without leaking backend detail",
        "storefront browser script shows safe order refresh rate-limit message without leaking detail",
        "storefront browser script handles polling refresh failure with warning and stops polling",
        "telegram-init-data-secret",
        "provider-secret",
        "refresh-secret",
        "polling-refresh-secret",
        "message warning",
        "assert.equal(intervals[0].active, false)",
        "snapshotBeforePolling",
        "failed payment must not start polling",
        "manual refresh before payment must not start polling",
        "data-payment-link",
    ]
    missing = [
        f"workers/storefront/src/worker.mjs:{marker}"
        for marker in required_worker_markers
        if marker not in worker
    ]
    if not worker_test_path.is_file():
        missing.append("workers/storefront/test/worker.test.mjs")
    missing.extend(
        f"workers/storefront/test/worker.test.mjs:{marker}"
        for marker in required_test_markers
        if marker not in worker_test
    )
    if missing:
        return ReadinessCheck(
            "worker_storefront_error_states_contract",
            FAIL,
            f"missing markers: {', '.join(missing)}",
        )
    return ReadinessCheck(
        "worker_storefront_error_states_contract",
        PASS,
        "Worker browser error states use generic 429/503/payment/order-refresh messages and tests assert sensitive backend details are not rendered or persisted",
    )


def _check_public_store_tests(project_root: Path) -> ReadinessCheck:
    expected_tests = [
        "tests/test_telegram_webapp.py",
        "tests/test_public_store_contract.py",
        "tests/test_public_store_runtime_auth.py",
        "tests/test_openapi_security_contract.py",
        "workers/storefront/test/worker.test.mjs",
    ]
    missing = [relative_path for relative_path in expected_tests if not (project_root / relative_path).is_file()]
    telegram_webapp = _read_optional(project_root / "app" / "services" / "telegram_webapp.py")
    telegram_webapp_tests = _read_optional(project_root / "tests" / "test_telegram_webapp.py")
    public_store_runtime_tests = _read_optional(project_root / "tests" / "test_public_store_runtime_auth.py")
    required_telegram_webapp_markers = [
        "MAX_INIT_DATA_BYTES",
        "MAX_INIT_DATA_FIELDS",
        "MAX_INIT_DATA_FIELD_KEY_LENGTH",
        "MAX_INIT_DATA_FIELD_VALUE_LENGTH",
        "MAX_AUTH_DATE_FUTURE_SKEW_SECONDS",
        "auth_date > current_time + MAX_AUTH_DATE_FUTURE_SKEW_SECONDS",
        "_validate_init_data_field",
        "not isinstance(user, dict)",
        "_optional_user_text",
    ]
    missing.extend(
        f"app/services/telegram_webapp.py:{marker}"
        for marker in required_telegram_webapp_markers
        if marker not in telegram_webapp
    )
    required_telegram_webapp_test_markers = [
        "test_rejects_future_auth_date_beyond_small_clock_skew",
        "test_rejects_oversized_or_too_many_init_data_fields",
        "test_rejects_invalid_user_json_shapes_and_optional_field_types",
    ]
    missing.extend(
        f"tests/test_telegram_webapp.py:{marker}"
        for marker in required_telegram_webapp_test_markers
        if marker not in telegram_webapp_tests
    )
    required_public_store_runtime_markers = [
        "test_create_order_rejects_future_webapp_auth_date_before_order_service",
        "initData auth_date 来自未来",
    ]
    missing.extend(
        f"tests/test_public_store_runtime_auth.py:{marker}"
        for marker in required_public_store_runtime_markers
        if marker not in public_store_runtime_tests
    )
    worker_test = _read_optional(project_root / "workers" / "storefront" / "test" / "worker.test.mjs")
    required_worker_test_markers = [
        "node:vm",
        "storefront browser script completes order payment and polling flow offline",
        "storefront browser script refreshes restored order when page returns to foreground",
        "storefront browser script rejects unsafe payment urls before opening or rendering",
        "FakeSessionStorage",
        "extractStorefrontRuntimeScript",
        "X-Telegram-Init-Data",
        "openLink",
        "setInterval",
        "data-payment-link",
        "unsafe browser api base url parts fall back to worker origin without rendering secrets",
        "rejects backend api urls with credentials query or fragment",
        "rejects unsupported methods without backend fetch",
        "forwards post body to backend",
        "strips cookies",
    ]
    missing.extend(
        f"workers/storefront/test/worker.test.mjs:{marker}"
        for marker in required_worker_test_markers
        if marker not in worker_test
    )
    if missing:
        return ReadinessCheck("public_store_test_contract", FAIL, f"missing tests: {', '.join(missing)}")
    return ReadinessCheck(
        "public_store_test_contract",
        PASS,
        "Public Store backend contract, Worker proxy tests and browser-script flow tests are present",
    )


def _check_external_http_adapter_contract(project_root: Path) -> ReadinessCheck:
    http_module = _read_optional(project_root / "app" / "services" / "external_sources" / "http.py")
    limits_module = _read_optional(project_root / "app" / "services" / "external_sources" / "limits.py")
    http_tests = project_root / "tests" / "test_external_source_http_contract.py"
    required_markers = [
        "ExternalHttpClient",
        "ExternalHttpTransport",
        "ExternalHttpRequest",
        "ExternalHttpResponse",
        "redact_external_http_headers",
        "redact_external_http_url",
        "ExternalHttpError",
        "status_code",
        "category",
        "retryable",
        "categorize_external_http_status",
        "is_external_http_status_retryable",
        "build_external_http_url",
        "path_segments",
        "HTTP base URL 不能包含 query",
        "validate_external_http_public_base_url",
        "UNSAFE_HTTP_HOST_SUFFIXES",
        "ipaddress.ip_address",
        "not address.is_global",
        "quote(segment, safe=\"\")",
        "ExternalHttpxTransport",
        "httpx.AsyncClient",
        "follow_redirects=False",
        "timeout=request.timeout_seconds",
        "MAX_EXTERNAL_HTTP_RESPONSE_BODY_BYTES",
        "_validate_external_http_response_size",
        "_validate_external_http_json_shape",
    ]
    missing = [marker for marker in required_markers if marker not in http_module]
    required_limit_markers = [
        "MAX_EXTERNAL_HTTP_RESPONSE_BODY_BYTES",
        "MAX_EXTERNAL_HTTP_JSON_DEPTH",
        "MAX_EXTERNAL_HTTP_JSON_FIELDS",
        "MAX_EXTERNAL_HTTP_JSON_ARRAY_ITEMS",
        "MAX_EXTERNAL_HTTP_JSON_STRING_LENGTH",
    ]
    missing.extend(
        f"app/services/external_sources/limits.py:{marker}"
        for marker in required_limit_markers
        if marker not in limits_module
    )
    http_test_text = _read_optional(http_tests)
    required_test_markers = [
        "ExternalHttpxTransport",
        "MockTransport",
        "does_not_follow_redirects",
        "test_client_rejects_oversized_response_body_without_details",
        "test_client_rejects_scalar_json_top_level_as_protocol_error",
        "test_client_rejects_overly_complex_json_payload",
        "test_httpx_transport_rejects_oversized_response_before_json_parse",
        "test_build_external_http_url_joins_path_segments_and_encodes_query",
        "test_build_external_http_url_rejects_unsafe_path_segments",
        "test_build_external_http_url_rejects_invalid_or_duplicate_query_keys",
        "test_validate_external_http_public_base_url_rejects_ssrf_targets",
    ]
    if not http_tests.is_file():
        missing.append("tests/test_external_source_http_contract.py")
    missing.extend(
        f"tests/test_external_source_http_contract.py:{marker}"
        for marker in required_test_markers
        if marker not in http_test_text
    )
    provider_contract_tests = project_root / "tests" / "test_external_source_http_provider_contract.py"
    if not provider_contract_tests.is_file():
        missing.append("tests/test_external_source_http_provider_contract.py")
    if missing:
        return ReadinessCheck("external_http_adapter_contract", FAIL, f"missing markers: {', '.join(missing)}")
    return ReadinessCheck(
        "external_http_adapter_contract",
        PASS,
        "HTTP provider adapter safety primitives, safe URL builder, public base URL SSRF guard, structured errors, httpx transport, fake-transport tests and fake provider contract tests are present",
    )


def _check_standard_http_external_provider_contract(project_root: Path) -> ReadinessCheck:
    provider_module = _read_optional(project_root / "app" / "services" / "external_sources" / "standard_http.py")
    sync_module = _read_optional(project_root / "app" / "services" / "external_sources" / "sync.py")
    orders_module = _read_optional(project_root / "app" / "services" / "external_sources" / "orders.py")
    idempotency_module_path = project_root / "app" / "services" / "external_sources" / "idempotency.py"
    idempotency_module = _read_optional(idempotency_module_path)
    exports = _read_optional(project_root / "app" / "services" / "external_sources" / "__init__.py")
    builtins = _read_optional(project_root / "app" / "services" / "external_sources" / "builtins.py")
    connections = _read_optional(project_root / "app" / "services" / "external_sources" / "connections.py")
    main = _read_optional(project_root / "app" / "main.py")
    provider_tests_path = project_root / "tests" / "test_external_source_standard_http_provider.py"
    provider_tests = _read_optional(provider_tests_path)
    tenant_admin_tests_path = project_root / "tests" / "test_tenant_admin_external_sources_provider_list.py"
    tenant_admin_tests = _read_optional(tenant_admin_tests_path)
    tenant_admin_runtime_tests_path = project_root / "tests" / "test_tenant_admin_runtime_auth.py"
    tenant_admin_runtime_tests = _read_optional(tenant_admin_runtime_tests_path)
    tenant_admin_router = _read_optional(project_root / "app" / "web" / "tenant_admin.py")
    required_provider_markers = [
        "STANDARD_HTTP_PROVIDER",
        "STANDARD_HTTP_CONTRACT",
        "DEFAULT_CATALOG_PATH",
        "DEFAULT_PRODUCT_PATH",
        "DEFAULT_CREATE_ORDER_PATH",
        "DEFAULT_QUERY_ORDER_PATH",
        "DEFAULT_DELIVERY_PATH",
        "ALLOWED_PATH_TEMPLATE_VARIABLES",
        "ALLOWED_STANDARD_HTTP_CREDENTIAL_FIELDS",
        "StandardHttpExternalSourceProvider",
        "StandardHttpCredentials",
        "integration_kind = \"generic_http_json\"",
        "contract_name = STANDARD_HTTP_CONTRACT",
        "production_ready = False",
        "staging_verified = False",
        "validate_standard_http_credentials",
        "validate_connection_credentials",
        "ExternalHttpClient",
        "ExternalHttpxTransport",
        "build_external_http_url",
        "validate_external_http_public_base_url",
        "is_sensitive_http_header_name",
        "reject_sensitive_raw_payload_keys",
        "list_products_with_context",
        "get_product_with_context",
        "create_order_with_context",
        "query_order_with_context",
        "fetch_delivery_with_context",
        "auto_fulfillment_idempotent = False",
        "MAX_EXTERNAL_CATALOG_PRODUCTS_PER_PAGE",
        "MAX_EXTERNAL_DELIVERY_ITEMS",
        "MAX_EXTERNAL_DELIVERY_ITEM_LENGTH",
        "MAX_EXTERNAL_DELIVERY_MESSAGE_LENGTH",
        "len(value) > max_items",
        "catalog_path",
        "product_path",
        "create_order_path",
        "query_order_path",
        "delivery_path",
        "_path_template",
        "_path_segments",
        "_template_variables",
    ]
    missing = [
        f"app/services/external_sources/standard_http.py:{marker}"
        for marker in required_provider_markers
        if marker not in provider_module
    ]
    required_sync_markers = [
        "MAX_EXTERNAL_CATALOG_PRODUCTS_PER_PAGE",
        "len(page.products) > MAX_EXTERNAL_CATALOG_PRODUCTS_PER_PAGE",
        "外部发卡源返回目录商品列表过大",
    ]
    missing.extend(
        f"app/services/external_sources/sync.py:{marker}"
        for marker in required_sync_markers
        if marker not in sync_module
    )
    required_order_markers = [
        "MAX_EXTERNAL_DELIVERY_ITEMS",
        "MAX_EXTERNAL_DELIVERY_ITEM_LENGTH",
        "MAX_EXTERNAL_DELIVERY_MESSAGE_LENGTH",
        "外部发卡源返回发货条目过多",
        "外部发卡源返回发货条目过长",
        "外部发卡源返回发货消息过长",
    ]
    missing.extend(
        f"app/services/external_sources/orders.py:{marker}"
        for marker in required_order_markers
        if marker not in orders_module
    )
    required_idempotency_markers = [
        "ExternalProviderOfflineIdempotencyProbe",
        "ExternalProviderOfflineIdempotencyProof",
        "duplicate_external_order_id",
        "_validate_duplicate_order",
        "fetch_delivery_with_context",
        "_required_text(request.out_trade_no",
        "外部源重复建单未证明按 out_trade_no 幂等",
    ]
    if not idempotency_module_path.is_file():
        missing.append("app/services/external_sources/idempotency.py")
    missing.extend(
        f"app/services/external_sources/idempotency.py:{marker}"
        for marker in required_idempotency_markers
        if marker not in idempotency_module
    )
    required_export_markers = [
        "STANDARD_HTTP_PROVIDER",
        "STANDARD_HTTP_CONTRACT",
        "StandardHttpExternalSourceProvider",
        "ExternalProviderOfflineIdempotencyProbe",
        "ExternalProviderOfflineIdempotencyProof",
        "create_standard_http_provider",
        "register_builtin_external_providers",
    ]
    missing.extend(
        f"app/services/external_sources/__init__.py:{marker}"
        for marker in required_export_markers
        if marker not in exports
    )
    required_builtin_markers = [
        "register_builtin_external_providers",
        "get_provider(STANDARD_HTTP_PROVIDER)",
        "register_provider(create_standard_http_provider())",
    ]
    missing.extend(
        f"app/services/external_sources/builtins.py:{marker}"
        for marker in required_builtin_markers
        if marker not in builtins
    )
    if "register_builtin_external_providers()" not in main:
        missing.append("app/main.py:register_builtin_external_providers()")
    required_connection_markers = [
        "_validate_provider_credentials",
        'getattr(provider, "validate_connection_credentials", None)',
        "normalized_credentials = _validate_provider_credentials(provider, normalized_credentials)",
        "TokenCrypto(settings).encrypt_token",
        "build_credentials_hint(normalized_credentials)",
    ]
    missing.extend(
        f"app/services/external_sources/connections.py:{marker}"
        for marker in required_connection_markers
        if marker not in connections
    )
    required_provider_test_markers = [
        "test_standard_http_provider_registers_as_builtin_once",
        "test_standard_http_provider_requires_authenticated_context_before_http_call",
        "test_standard_http_provider_syncs_catalog_with_runtime_credentials",
        "test_standard_http_provider_order_lifecycle_redacts_credentials",
        "test_standard_http_provider_uses_configured_safe_path_templates",
        "test_standard_http_provider_rejects_unsafe_path_templates_before_http_call",
        "test_standard_http_provider_rejects_unsafe_base_url_before_http_call",
        "test_standard_http_provider_requires_endpoint_specific_template_variables",
        "test_standard_http_provider_rejects_path_variable_path_injection",
        "test_standard_http_provider_rejects_sensitive_raw_payload",
        "test_standard_http_provider_non_json_response_is_protocol_error",
        "test_standard_http_provider_rejects_too_many_catalog_products",
        "test_standard_http_provider_rejects_too_many_delivery_items",
        "test_standard_http_provider_rejects_oversized_delivery_item",
        "test_standard_http_offline_idempotency_probe_uses_duplicate_out_trade_no_without_claiming_auto",
        "test_standard_http_offline_idempotency_probe_rejects_non_idempotent_duplicate_order",
        "provider.auto_fulfillment_idempotent",
    ]
    if not provider_tests_path.is_file():
        missing.append("tests/test_external_source_standard_http_provider.py")
    missing.extend(
        f"tests/test_external_source_standard_http_provider.py:{marker}"
        for marker in required_provider_test_markers
        if marker not in provider_tests
    )
    required_tenant_admin_test_markers = [
        "test_list_external_sources_includes_builtin_standard_http_without_credentials",
        "integration_kind",
        "contract_name",
        "production_ready",
        "staging_verified",
        "auto_fulfillment_idempotent_available",
        "catalog_context_available",
        "delivery_context_available",
    ]
    if not tenant_admin_tests_path.is_file():
        missing.append("tests/test_tenant_admin_external_sources_provider_list.py")
    missing.extend(
        f"tests/test_tenant_admin_external_sources_provider_list.py:{marker}"
        for marker in required_tenant_admin_test_markers
        if marker not in tenant_admin_tests
    )
    required_tenant_admin_runtime_test_markers = [
        "test_create_standard_http_external_source_connection_invalid_credentials_returns_400_and_redacts",
        "test_get_external_source_connection_requires_read_scope_before_service",
        "test_get_external_source_connection_is_tenant_scoped_and_redacted",
        "test_get_external_source_connection_returns_404_for_missing_or_cross_tenant_connection",
    ]
    required_tenant_admin_router_markers = [
        '"/external-source-connections/{connection_id}"',
        "get_external_source_connection",
        "ExternalSourceConnectionService().get_connection",
        'require_scope("external_sources:read")',
    ]
    missing.extend(
        f"app/web/tenant_admin.py:{marker}"
        for marker in required_tenant_admin_router_markers
        if marker not in tenant_admin_router
    )
    if not tenant_admin_runtime_tests_path.is_file():
        missing.append("tests/test_tenant_admin_runtime_auth.py")
    missing.extend(
        f"tests/test_tenant_admin_runtime_auth.py:{marker}"
        for marker in required_tenant_admin_runtime_test_markers
        if marker not in tenant_admin_runtime_tests
    )
    connection_tests_path = project_root / "tests" / "test_external_source_connections.py"
    connection_tests = _read_optional(connection_tests_path)
    required_connection_test_markers = [
        "test_create_standard_http_connection_validates_and_encrypts_safe_credentials",
        "test_create_standard_http_connection_rejects_unsafe_credentials_before_encrypting",
        "test_create_connection_uses_provider_validator_without_knowing_specific_provider",
        "test_create_connection_provider_validation_error_happens_before_flush",
        "standard_http 凭据无效",
        "169.254.169.254",
        "service.internal",
    ]
    if not connection_tests_path.is_file():
        missing.append("tests/test_external_source_connections.py")
    missing.extend(
        f"tests/test_external_source_connections.py:{marker}"
        for marker in required_connection_test_markers
        if marker not in connection_tests
    )
    if missing:
        return ReadinessCheck(
            "standard_http_external_provider_contract",
            FAIL,
            f"missing markers: {', '.join(missing)}",
        )
    return ReadinessCheck(
        "standard_http_external_provider_contract",
        PASS,
        "standard_http provider is registered as a builtin HTTP/JSON adapter with context-only credentials, safe integration metadata, public base URL SSRF guard, redacted auth headers, sensitive payload rejection, offline replay idempotency probe tests and no automatic fulfillment idempotency claim",
    )


def _check_mcy_shop_external_provider_contract(project_root: Path) -> ReadinessCheck:
    provider_module = _read_optional(project_root / "app" / "services" / "external_sources" / "mcy_shop.py")
    exports = _read_optional(project_root / "app" / "services" / "external_sources" / "__init__.py")
    builtins = _read_optional(project_root / "app" / "services" / "external_sources" / "builtins.py")
    provider_tests_path = project_root / "tests" / "test_external_source_mcy_shop_provider.py"
    provider_tests = _read_optional(provider_tests_path)
    tenant_admin_tests_path = project_root / "tests" / "test_tenant_admin_external_sources_provider_list.py"
    tenant_admin_tests = _read_optional(tenant_admin_tests_path)
    required_provider_markers = [
        "MCY_SHOP_PROVIDER",
        "MCY_SHOP_OFFLINE_FIXTURE_CONTRACT",
        "ALLOWED_MCY_SHOP_CREDENTIAL_FIELDS",
        "MCY_SHOP_OFFLINE_FIXTURE_ALLOWED_HOSTS",
        "MCY_SHOP_OFFLINE_FIXTURE_ALLOWED_HOST_SUFFIXES",
        "McyShopExternalSourceProvider",
        "McyShopCredentials",
        "integration_kind = \"offline_fixture\"",
        "contract_name = MCY_SHOP_OFFLINE_FIXTURE_CONTRACT",
        "production_ready = False",
        "staging_verified = False",
        "validate_mcy_shop_credentials",
        "validate_connection_credentials",
        "_ensure_mcy_shop_fixture_base_url",
        "_is_mcy_shop_fixture_host",
        "create_mcy_shop_provider",
        "ExternalHttpClient",
        "ExternalHttpxTransport",
        "build_external_http_url",
        "reject_sensitive_raw_payload_keys",
        "list_products_with_context",
        "get_product_with_context",
        "create_order_with_context",
        "query_order_with_context",
        "fetch_delivery_with_context",
        "auto_fulfillment_idempotent = False",
        "MAX_EXTERNAL_CATALOG_PRODUCTS_PER_PAGE",
        "MAX_EXTERNAL_DELIVERY_ITEMS",
        "MAX_EXTERNAL_DELIVERY_ITEM_LENGTH",
        "MAX_EXTERNAL_DELIVERY_MESSAGE_LENGTH",
        "len(value) > max_items",
        "mcy-shop-fixture",
    ]
    missing = [
        f"app/services/external_sources/mcy_shop.py:{marker}"
        for marker in required_provider_markers
        if marker not in provider_module
    ]
    required_export_markers = [
        "MCY_SHOP_PROVIDER",
        "MCY_SHOP_OFFLINE_FIXTURE_CONTRACT",
        "McyShopExternalSourceProvider",
        "ExternalProviderOfflineIdempotencyProbe",
        "ExternalProviderOfflineIdempotencyProof",
        "create_mcy_shop_provider",
        "validate_mcy_shop_credentials",
    ]
    missing.extend(
        f"app/services/external_sources/__init__.py:{marker}"
        for marker in required_export_markers
        if marker not in exports
    )
    required_builtin_markers = [
        "get_provider(MCY_SHOP_PROVIDER)",
        "register_provider(create_mcy_shop_provider())",
    ]
    missing.extend(
        f"app/services/external_sources/builtins.py:{marker}"
        for marker in required_builtin_markers
        if marker not in builtins
    )
    required_provider_test_markers = [
        "test_mcy_shop_provider_registers_as_builtin_offline_contract",
        "test_mcy_shop_provider_requires_authenticated_context_before_http_call",
        "test_mcy_shop_credentials_only_allow_fixture_hosts",
        "test_mcy_shop_provider_syncs_catalog_with_runtime_credentials",
        "test_mcy_shop_provider_order_lifecycle_redacts_credentials",
        "test_mcy_shop_provider_rejects_sensitive_raw_payload",
        "test_mcy_shop_provider_non_json_response_is_protocol_error",
        "test_mcy_shop_provider_rejects_unsafe_credentials_before_http_call",
        "test_mcy_shop_provider_rejects_too_many_catalog_items",
        "test_mcy_shop_provider_rejects_too_many_delivery_items",
        "test_mcy_shop_provider_rejects_oversized_delivery_item",
        "test_mcy_shop_offline_idempotency_probe_uses_duplicate_out_trade_no_without_claiming_auto",
        "test_mcy_shop_offline_idempotency_probe_rejects_non_idempotent_duplicate_order",
        "provider.auto_fulfillment_idempotent",
        "MCY_SHOP_OFFLINE_FIXTURE_CONTRACT",
    ]
    if not provider_tests_path.is_file():
        missing.append("tests/test_external_source_mcy_shop_provider.py")
    missing.extend(
        f"tests/test_external_source_mcy_shop_provider.py:{marker}"
        for marker in required_provider_test_markers
        if marker not in provider_tests
    )
    required_tenant_admin_test_markers = [
        "MCY_SHOP_PROVIDER",
        "integration_kind",
        "contract_name",
        "production_ready",
        "staging_verified",
        "auto_fulfillment_idempotent_available",
        "catalog_context_available",
        "delivery_context_available",
    ]
    if not tenant_admin_tests_path.is_file():
        missing.append("tests/test_tenant_admin_external_sources_provider_list.py")
    missing.extend(
        f"tests/test_tenant_admin_external_sources_provider_list.py:{marker}"
        for marker in required_tenant_admin_test_markers
        if marker not in tenant_admin_tests
    )
    if missing:
        return ReadinessCheck(
            "mcy_shop_external_provider_contract",
            FAIL,
            f"missing markers: {', '.join(missing)}",
        )
    return ReadinessCheck(
        "mcy_shop_external_provider_contract",
        PASS,
        "mcy_shop offline fixture provider skeleton is registered with context-only credentials, safe integration metadata, safe HTTP adapter usage, offline replay idempotency probe tests and no automatic fulfillment idempotency claim; real mcy-shop API mapping is still not claimed",
    )


def _check_payment_adapter_contract(project_root: Path) -> ReadinessCheck:
    epusdt_module = _read_optional(project_root / "app" / "services" / "payments" / "epusdt.py")
    token188_module = _read_optional(project_root / "app" / "services" / "payments" / "token188.py")
    epay_module = _read_optional(project_root / "app" / "services" / "payments" / "epay_compatible.py")
    safety_module = _read_optional(project_root / "app" / "services" / "payments" / "safety.py")
    payment_failures_module = _read_optional(project_root / "app" / "services" / "payments" / "failures.py")
    payment_exports = _read_optional(project_root / "app" / "services" / "payments" / "__init__.py")
    payment_service = _read_optional(project_root / "app" / "services" / "payments" / "service.py")
    payment_configs = _read_optional(project_root / "app" / "services" / "payments" / "configs.py")
    payment_router = _read_optional(project_root / "app" / "web" / "payments.py")
    tenant_admin_router = _read_optional(project_root / "app" / "web" / "tenant_admin.py")
    epusdt_tests_path = project_root / "tests" / "test_payment_epusdt.py"
    epusdt_tests = _read_optional(epusdt_tests_path)
    required_epusdt_markers = [
        "EpusdtGmpayProvider",
        "verify_callback",
        "sanitize_payment_callback_payload",
        "payload_hash(payload)",
        "epusdt 回调缺少订单号",
    ]
    missing = [marker for marker in required_epusdt_markers if marker not in epusdt_module]
    epusdt_test_markers = [
        "test_verify_callback_redacts_nested_sensitive_payload_fields",
        "test_verify_callback_valid_signature_non_success_status_is_unpaid",
        "test_verify_callback_rejects_invalid_signature_or_missing_order_number",
    ]
    if not epusdt_tests_path.is_file():
        missing.append("tests/test_payment_epusdt.py")
    missing.extend(f"tests/test_payment_epusdt.py:{marker}" for marker in epusdt_test_markers if marker not in epusdt_tests)
    token188_tests_path = project_root / "tests" / "test_payment_token188.py"
    token188_tests = _read_optional(token188_tests_path)
    required_token188_markers = [
        "TOKEN188_OFFLINE_QUERY_CONTRACT",
        "Token188Config",
        "Token188Provider",
        "build_token188_offline_query_contract_request",
        "sign_token188_gateway_payload",
        "sign_token188_callback_payload",
        "verify_token188_callback",
        "normalize_token188_offline_query_response",
        "normalize_token188_query_payload",
        "sanitize_payment_callback_payload",
        "金额不能小于 0.01",
        "TOKEN188 回调缺少订单号",
        "NotImplementedError",
    ]
    missing.extend(marker for marker in required_token188_markers if marker not in token188_module)
    required_epay_markers = [
        "EPAY_COMPATIBLE_PROVIDER",
        "EPAY_OFFLINE_QUERY_CONTRACT",
        "LEMZF_PROVIDER",
        "EpayCompatibleConfig",
        "EpayCompatibleProvider",
        "LemzfProvider",
        "build_epay_offline_query_contract_request",
        "sign_epay_payload",
        "verify_epay_callback",
        "normalize_epay_offline_query_response",
        "normalize_epay_query_payload",
        "build_epay_page_payment_params",
        "build_epay_page_payment_url",
        "sanitize_payment_callback_payload",
        "金额不能小于 0.01",
        "易支付回调缺少订单号",
        "NotImplementedError",
    ]
    missing.extend(f"app/services/payments/epay_compatible.py:{marker}" for marker in required_epay_markers if marker not in epay_module)
    required_safety_markers = [
        "sanitize_payment_callback_payload",
        "SENSITIVE_PAYMENT_PAYLOAD_KEYWORDS",
        "authorization",
        "credential",
        "cookie",
        "json.dumps",
    ]
    if not (project_root / "app" / "services" / "payments" / "safety.py").is_file():
        missing.append("app/services/payments/safety.py")
    missing.extend(
        f"app/services/payments/safety.py:{marker}"
        for marker in required_safety_markers
        if marker not in safety_module
    )
    export_markers = [
        "TOKEN188_OFFLINE_QUERY_CONTRACT",
        "Token188Provider",
        "build_token188_offline_query_contract_request",
        "sign_token188_gateway_payload",
        "verify_token188_callback",
        "normalize_token188_offline_query_response",
        "normalize_token188_query_payload",
        "EPAY_OFFLINE_QUERY_CONTRACT",
        "EpayCompatibleProvider",
        "EpayCompatibleConfig",
        "LemzfProvider",
        "build_epay_offline_query_contract_request",
        "sign_epay_payload",
        "verify_epay_callback",
        "normalize_epay_offline_query_response",
        "normalize_epay_query_payload",
        "PaymentCallbackRejectionAuditService",
    ]
    missing.extend(f"app/services/payments/__init__.py:{marker}" for marker in export_markers if marker not in payment_exports)
    payment_failure_markers = [
        "PAYMENT_CALLBACK_REJECTION_ACTION",
        "PaymentCallbackRejectionAuditService",
        "PaymentCallbackRejectionSummary",
        "record_rejection",
        "list_rejections",
        "payload_field_count",
    ]
    missing.extend(
        f"app/services/payments/failures.py:{marker}"
        for marker in payment_failure_markers
        if marker not in payment_failures_module
    )
    service_markers = [
        "PaymentProvider",
        "_resolve_payment_provider",
        "process_payment_callback",
        "TOKEN188_PROVIDER",
        "EPAY_COMPATIBLE_PROVIDER",
        "LEMZF_PROVIDER",
        "resolved_config.provider == USDT_TRC20_DIRECT_PROVIDER",
        "reconcile_pending_payments",
        "Payment.provider == EpusdtGmpayProvider.provider",
    ]
    missing.extend(f"app/services/payments/service.py:{marker}" for marker in service_markers if marker not in payment_service)
    config_markers = [
        "SUPPORTED_TENANT_PAYMENT_PROVIDERS",
        "TENANT_DIRECT_PAYMENT_PROVIDER_PRIORITY",
        "resolve_tenant_payment_config_for_provider",
        "resolve_first_tenant_payment_config",
        "upsert_tenant_payment_config",
        "disable_tenant_payment_config",
        "normalize_payment_gateway_url",
        "normalize_token188_gateway_url",
        "normalize_epay_gateway_url",
        "query_order_available=False",
        "reconcile_available=False",
    ]
    missing.extend(f"app/services/payments/configs.py:{marker}" for marker in config_markers if marker not in payment_configs)
    router_markers = [
        '"/callback/token188"',
        '"/callback/epay_compatible"',
        '"/callback/lemzf"',
        '"/callback/{provider_name}"',
        "_read_callback_payload",
        "MAX_PAYMENT_CALLBACK_BODY_BYTES",
        "MAX_PAYMENT_CALLBACK_QUERY_BYTES",
        "MAX_PAYMENT_CALLBACK_FIELD_COUNT",
        "MAX_PAYMENT_CALLBACK_KEY_LENGTH",
        "MAX_PAYMENT_CALLBACK_VALUE_LENGTH",
        "_read_json_object_no_duplicate_keys",
        "_pairs_to_callback_payload",
        "_validate_callback_payload_shape",
        "_record_callback_rejection",
        "PaymentCallbackRejectionAuditService",
        "process_payment_callback",
        "支付回调参数无效",
        "支付配置暂不可用",
    ]
    missing.extend(f"app/web/payments.py:{marker}" for marker in router_markers if marker not in payment_router)
    tenant_admin_payment_markers = [
        '"/payments/callback-failures"',
        '"/payments/callback-rejections"',
        "PaymentCallbackRejectionAuditService",
        "TenantPaymentCallbackRejectionItem",
        "_payment_callback_rejection_response",
    ]
    missing.extend(
        f"app/web/tenant_admin.py:{marker}"
        for marker in tenant_admin_payment_markers
        if marker not in tenant_admin_router
    )
    token188_test_markers = [
        "test_sign_token188_payloads_match_legacy_gateway_and_callback_algorithms",
        "test_build_payment_params_rejects_amount_truncated_to_zero",
        "test_verify_callback_redacts_nested_sensitive_payload_fields",
        "test_verify_callback_accepts_legacy_order_number_aliases",
        "test_callback_requires_order_number_instead_of_amount_guessing",
        "test_query_order_is_not_claimed_as_supported_before_real_integration",
        "test_normalize_signed_query_payload_maps_statuses_without_network",
        "test_normalize_signed_query_payload_rejects_mismatched_or_unsafe_values",
    ]
    if not token188_tests_path.is_file():
        missing.append("tests/test_payment_token188.py")
    missing.extend(f"tests/test_payment_token188.py:{marker}" for marker in token188_test_markers if marker not in token188_tests)
    epay_tests_path = project_root / "tests" / "test_payment_epay_compatible.py"
    epay_tests = _read_optional(epay_tests_path)
    epay_test_markers = [
        "test_sign_epay_payload_matches_legacy_lemzf_algorithm",
        "test_build_page_payment_params_and_url_without_network",
        "test_build_page_payment_params_rejects_amount_truncated_to_zero",
        "test_verify_callback_accepts_signed_success_payload",
        "test_verify_callback_redacts_nested_sensitive_payload_fields",
        "test_verify_callback_valid_signature_non_success_status_is_unpaid",
        "test_lemzf_provider_uses_lemzf_provider_name_without_network",
        "test_query_order_is_not_claimed_as_supported_before_real_integration",
        "test_normalize_signed_query_payload_maps_statuses_without_network",
        "test_normalize_signed_query_payload_rejects_mismatched_or_unsafe_values",
        "test_normalize_signed_query_payload_preserves_lemzf_provider_name",
    ]
    if not epay_tests_path.is_file():
        missing.append("tests/test_payment_epay_compatible.py")
    missing.extend(f"tests/test_payment_epay_compatible.py:{marker}" for marker in epay_test_markers if marker not in epay_tests)
    offline_query_tests_path = project_root / "tests" / "test_payment_offline_query_contract.py"
    offline_query_tests = _read_optional(offline_query_tests_path)
    offline_query_test_markers = [
        "FakeOfflineQueryTransport",
        "test_token188_offline_query_normalizer_accepts_signed_paid_fixture_without_network",
        "test_token188_offline_query_normalizer_maps_pending_and_expired_fixture_statuses",
        "test_token188_offline_query_normalizer_rejects_mismatched_order_or_signature",
        "test_epay_offline_query_normalizer_accepts_signed_success_fixture_without_network",
        "test_epay_offline_query_normalizer_maps_pending_and_expired_fixture_statuses",
        "test_epay_offline_query_normalizer_rejects_mismatched_pid_order_or_signature",
        "test_lemzf_offline_query_normalizer_keeps_lemzf_provider_name",
    ]
    if not offline_query_tests_path.is_file():
        missing.append("tests/test_payment_offline_query_contract.py")
    missing.extend(
        f"tests/test_payment_offline_query_contract.py:{marker}"
        for marker in offline_query_test_markers
        if marker not in offline_query_tests
    )
    payment_create_tests_path = project_root / "tests" / "test_payment_create_service.py"
    payment_create_tests = _read_optional(payment_create_tests_path)
    payment_create_test_markers = [
        "test_create_payment_for_order_wires_offline_tenant_providers_without_network",
        "test_real_resolver_for_self_order_uses_tenant_provider_before_epusdt_fallback",
    ]
    if not payment_create_tests_path.is_file():
        missing.append("tests/test_payment_create_service.py")
    missing.extend(
        f"tests/test_payment_create_service.py:{marker}"
        for marker in payment_create_test_markers
        if marker not in payment_create_tests
    )
    payment_callback_tests_path = project_root / "tests" / "test_payment_callback_service.py"
    payment_callback_tests = _read_optional(payment_callback_tests_path)
    payment_callback_test_markers = [
        "test_generic_offline_provider_paid_callback_updates_order_payment_and_delivery",
        "process_payment_callback",
    ]
    if not payment_callback_tests_path.is_file():
        missing.append("tests/test_payment_callback_service.py")
    missing.extend(
        f"tests/test_payment_callback_service.py:{marker}"
        for marker in payment_callback_test_markers
        if marker not in payment_callback_tests
    )
    payment_route_tests_path = project_root / "tests" / "test_payment_callback_routes.py"
    payment_route_tests = _read_optional(payment_route_tests_path)
    payment_route_test_markers = [
        "test_offline_provider_callback_routes_delegate_to_generic_service_without_network",
        "test_callback_route_reads_form_urlencoded_payload",
        "test_callback_route_reads_get_query_payload",
        "test_callback_route_error_response_does_not_echo_provider_secret",
        "test_callback_route_records_invalid_callback_rejection_without_echoing_secret",
        "test_callback_route_payment_unavailable_response_is_generic_and_records_rejection",
        "test_callback_route_records_malformed_payload_rejection_before_payment_service",
        "test_callback_route_accepts_nested_json_payload_without_rewriting_fields",
        "test_callback_route_rejects_body_over_size_limit_before_payment_service",
        "test_callback_route_rejects_query_over_size_limit_before_payment_service",
        "test_callback_route_rejects_too_many_json_fields_before_payment_service",
        "test_callback_route_rejects_oversized_key_or_value_before_payment_service",
        "test_callback_route_rejects_duplicate_json_keys_before_payment_service",
        "test_callback_route_rejects_duplicate_form_fields_before_payment_service",
        "test_callback_route_rejects_duplicate_query_fields_before_payment_service",
        "test_callback_route_payload_gate_errors_are_generic_and_audited_without_payload",
        "PaymentUnavailableError",
        "/payments/callback/token188",
        "/payments/callback/epay_compatible",
        "/payments/callback/lemzf",
    ]
    if not payment_route_tests_path.is_file():
        missing.append("tests/test_payment_callback_routes.py")
    missing.extend(
        f"tests/test_payment_callback_routes.py:{marker}"
        for marker in payment_route_test_markers
        if marker not in payment_route_tests
    )
    payment_rejection_tests_path = project_root / "tests" / "test_payment_callback_rejections.py"
    payment_rejection_tests = _read_optional(payment_rejection_tests_path)
    payment_rejection_test_markers = [
        "test_record_rejection_writes_tenant_audit_without_payload_or_secret",
        "test_record_rejection_without_order_keeps_platform_scoped_safe_audit",
        "test_record_payload_malformed_rejection_without_payload_keeps_zero_field_count",
        "test_list_rejections_returns_tenant_scoped_safe_summaries",
    ]
    if not payment_rejection_tests_path.is_file():
        missing.append("tests/test_payment_callback_rejections.py")
    missing.extend(
        f"tests/test_payment_callback_rejections.py:{marker}"
        for marker in payment_rejection_test_markers
        if marker not in payment_rejection_tests
    )
    if missing:
        return ReadinessCheck("payment_adapter_contract", FAIL, f"missing markers: {', '.join(missing)}")
    return ReadinessCheck(
        "payment_adapter_contract",
        PASS,
        "epusdt is wired and TOKEN188, epay-compatible and lemzf offline providers are connected to payment creation, callback routes, tenant config, service-level callback processing, callback failure observation, pre-persistence rejection audit, callback payload parsing gates and offline query payload normalization while real query/reconcile capabilities remain disabled; usdt_trc20_direct can create offline local payment intents for explicit self-order requests while chain scanning, callbacks, query/reconcile and production direct payments remain disabled",
    )


def _check_business_plugin_contract(project_root: Path) -> ReadinessCheck:
    plugin_module = _read_optional(project_root / "app" / "services" / "business_plugins.py")
    service_exports = _read_optional(project_root / "app" / "services" / "__init__.py")
    tests = _read_optional(project_root / "tests" / "test_business_plugins.py")
    plugin_docs = _read_optional(project_root / "docs" / "业务插件架构方案.md")
    roadmap = _read_optional(project_root / "docs" / "实施路线图.md")
    handoff = _read_optional(project_root / "docs" / "开发交接说明.md")
    full_plan = _read_optional(project_root / "docs" / "多租户发卡平台完整方案.md")
    web_plan = _read_optional(project_root / "docs" / "Web管理后台开发计划.md")

    missing: list[str] = []
    module_markers = [
        "BusinessPluginManifest",
        "BusinessPluginRegistry",
        "BUSINESS_PLUGIN_KIND_PAYMENT",
        "BUSINESS_PLUGIN_KIND_EXTERNAL_SOURCE",
        "BUSINESS_PLUGIN_KIND_TENANT_TOOL",
        "ALLOWED_PLUGIN_ENTRYPOINT_PREFIXES",
        "is_plugin_entrypoint_allowed",
        "payment_summary_to_plugin_manifest",
        "external_source_summary_to_plugin_manifest",
        "list_current_business_plugin_manifests",
        "MappingProxyType",
        "from_mapping",
        "production_ready",
        "staging_verified",
        "capability 值必须是布尔值",
        "entrypoint 必须是 module:function 格式",
    ]
    missing.extend(
        f"app/services/business_plugins.py:{marker}" for marker in module_markers if marker not in plugin_module
    )
    export_markers = [
        "BusinessPluginManifest",
        "BusinessPluginRegistry",
        "list_current_business_plugin_manifests",
    ]
    missing.extend(f"app/services/__init__.py:{marker}" for marker in export_markers if marker not in service_exports)
    test_markers = [
        "test_manifest_from_mapping_normalizes_safe_fields",
        "test_manifest_requires_explicit_production_and_staging_flags",
        "test_manifest_rejects_invalid_identity_and_truthy_booleans",
        "test_entrypoint_is_validated_but_not_executed",
        "test_payment_summary_converts_to_plugin_manifest_without_secrets",
        "test_external_source_summary_converts_to_plugin_manifest",
    ]
    missing.extend(f"tests/test_business_plugins.py:{marker}" for marker in test_markers if marker not in tests)
    doc_markers = [
        "长期目标接近 WordPress 插件",
        "当前阶段落地受控适配器插件",
        "`app/services/business_plugins.py`",
        "不导入执行第三方插件代码",
        "不做动态 Bot router 注入",
        "不做动态任务和 handler 注入",
        "当前阶段：业务插件 manifest 能校验",
        "不做任意第三方插件热加载和远程代码执行",
        "Admin Web 插件能力摘要只读 BFF",
        "不执行插件 entrypoint",
        "不读取或解密外部源凭据",
        "不代表插件安装、租户级启停、真实 mcy-shop/acg-faka、真实支付网关或 staging 验证完成",
    ]
    docs_combined = plugin_docs + roadmap + handoff + full_plan + web_plan
    missing.extend(f"docs:{marker}" for marker in doc_markers if marker not in docs_combined)
    if missing:
        return ReadinessCheck("business_plugin_contract", FAIL, f"missing markers: {', '.join(missing)}")
    return ReadinessCheck(
        "business_plugin_contract",
        PASS,
        "Business plugin contract has a static manifest/registry layer for payment and external_source provider summaries, reserves wider plugin kinds without dynamic code loading, and documents that WordPress-like extension is a target state while first-stage delivery stays limited to controlled adapters",
    )


def _warning_real_external_provider_required() -> ReadinessCheck:
    return ReadinessCheck(
        "real_external_provider_integration",
        WARN,
        "standard_http HTTP/JSON and mcy_shop offline fixture providers have offline contracts and local replay probes; concrete third-party mappings, real provider idempotency proof and real staging tests are still required",
    )


def _warning_real_staging_integration_required() -> ReadinessCheck:
    return ReadinessCheck(
        "manual_staging_integration",
        WARN,
        "Real alembic upgrade, Telegram getMe/webhook, epusdt callback, Worker deployment and payment redirect are manual staging gates",
    )


def _env_example_keys(text: str) -> list[str]:
    keys = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _ = stripped.split("=", 1)
        keys.append(key.strip())
    return keys


def _read_optional(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
