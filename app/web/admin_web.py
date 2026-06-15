from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Optional

from fastapi import APIRouter, Cookie, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select

from app.bots.factory import create_bot
from app.config import Settings
from app.db.models.ledger import WithdrawalRequest
from app.db.models.orders import PaymentProviderConfig
from app.db.models.subscriptions import SubscriptionPlan, TenantSubscription
from app.db.models.supply import SupplierOffer
from app.db.models.tenants import AuditLog, PlatformUser, Tenant, TenantBot
from app.db.session import get_session_factory
from app.services.api_security import (
    ApiRateLimitError,
    FixedWindowRateLimiter,
    RedisFixedWindowRateLimiter,
    hit_rate_limit,
    resolve_client_ip,
)
from app.services.admin_web import (
    ADMIN_WEB_SESSION_COOKIE_NAME,
    AdminWebBindingCodeError,
    AdminWebBindingCodeStore,
    AdminWebBusinessPluginCapabilitiesSummary,
    AdminWebBusinessPluginCapabilityItem,
    AdminWebCreatedSupplierOfferItem,
    AdminWebCreatedTenantApiKeyItem,
    AdminWebExternalCatalogSyncProductItem,
    AdminWebExternalCatalogSyncResultItem,
    AdminWebExternalSourceCatalogProductItem,
    AdminWebExternalSourceCatalogProductsPage,
    AdminWebExternalFulfillmentAttemptItem,
    AdminWebExternalSourceConnectionItem,
    AdminWebExternalSourceConnectionsPage,
    AdminWebExternalSourceProviderItem,
    AdminWebInventoryImportResult,
    AdminWebPaymentCallbackFailureItem,
    AdminWebPaymentCallbackRejectionItem,
    AdminWebProductDeliveryFileResult,
    AdminWebSupplierApplicationItem,
    AdminWebSupplierOfferApprovalItem,
    AdminWebSupplierRuleItem,
    AdminWebService,
    AdminWebSessionCodec,
    AdminWebSessionError,
    AdminWebSessionSummary,
    AdminWebCreatedResellerProductItem,
    AdminWebResellerApplicationItem,
    AdminWebSubscriptionRenewalOrder,
    AdminWebTenantAuditLogsPage,
    AdminWebTenantAuditLogItem,
    AdminWebTenantApiKeyItem,
    AdminWebTenantApiKeyRevokeResult,
    AdminWebTenantApiKeysPage,
    AdminWebTenantFinanceDashboard,
    AdminWebTenantOrdersPage,
    AdminWebTenantOrderDiagnostics,
    AdminWebTenantOrderObservability,
    AdminWebTenantOverview,
    AdminWebTenantPaymentProviderConfigItem,
    AdminWebTenantPaymentProviderConfigsPage,
    AdminWebTenantProductBatchStatusUpdate,
    AdminWebTenantProductItem,
    AdminWebTenantProductsPage,
    AdminWebTenantReportExportDownloadFile,
    AdminWebTenantReportExportJobItem,
    AdminWebTenantReportExportJobsPage,
    AdminWebTenantRiskDashboard,
    AdminWebTenantRiskDisputeItem,
    AdminWebTenantRiskAfterSaleItem,
    AdminWebTenantStoreSettings,
    AdminWebTenantSubscriptionDashboard,
    AdminWebTenantSupplyDashboard,
    AdminWebTenantWithdrawalItem,
    AdminWebWorkspaceSummary,
    PLATFORM_WORKSPACE_ID,
)
from app.services.audit import AuditLogService, PlatformRiskAuditLogSummary
from app.services.external_sources.base import ExternalProviderNotRegisteredError, ExternalSourceError
from app.services.files import FileStorageService
from app.services.ledger import LedgerService, WithdrawalSummary
from app.services.payments.configs import EPUSDT_PROVIDER, PaymentProviderSummary, list_payment_provider_summaries
from app.services.risk import PlatformRiskBannedUserSummary, PlatformRiskBanStatusSummary, RiskControlService
from app.services.subscriptions import (
    SubscriptionAdjustmentResult,
    PlatformSubscriptionAttentionItem,
    PlatformSubscriptionPlanSummary,
    SubscriptionService,
)
from app.services.supply import PlatformSupplierOfferSummary, SupplyService
from app.services.telegram_webapp import TelegramWebAppInitDataError, validate_telegram_webapp_init_data
from app.services.token_crypto import TokenCrypto, generate_webhook_secret


ADMIN_WEB_TENANT_WEBHOOK_ALLOWED_UPDATES = ["message", "callback_query"]


class AdminWebSafeValidationRoute(APIRoute):
    def get_route_handler(self):
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            try:
                return await original_route_handler(request)
            except RequestValidationError as exc:
                return JSONResponse(
                    status_code=422,
                    content={"detail": _safe_admin_web_validation_errors(exc.errors())},
                )

        return custom_route_handler


class AdminWebTelegramSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    init_data: str = Field(min_length=1, max_length=8192)
    entrypoint: Literal["master", "tenant"] = "master"
    tenant_public_id: Optional[str] = Field(default=None, min_length=3, max_length=32)


class AdminWebWorkspaceSelectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(min_length=3, max_length=32)


class AdminWebBindingCodeSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=4, max_length=32)


class AdminWebSupplyApplicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_offer_id: int = Field(gt=0)


class AdminWebProductMetadataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Optional[str] = Field(default=None, max_length=128)
    sort_order: Optional[int] = Field(default=None, ge=-100000, le=100000)


class AdminWebProductCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=255)
    price: Decimal = Field(gt=0)
    delivery_type: Literal["card_pool", "card_fixed", "telegram_invite", "file_download"]
    description: Optional[str] = Field(default=None, max_length=4096)
    category: Optional[str] = Field(default=None, max_length=128)


class AdminWebProductSalesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price: Optional[Decimal] = Field(default=None, gt=0)
    status: Optional[Literal["draft", "on", "off"]] = None


class AdminWebProductBatchStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_ids: list[int] = Field(min_length=1, max_length=50)
    status: Literal["on", "off"]


class AdminWebProductInventoryImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[str] = Field(min_length=1, max_length=1000)


class AdminWebSubscriptionRenewalOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    months: int = Field(ge=1, le=24)


class AdminWebWithdrawalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(gt=0)
    network: str = Field(min_length=2, max_length=32)
    address: str = Field(min_length=8, max_length=256)
    currency: str = Field(default="USDT", min_length=1, max_length=16)


class AdminWebReportExportJobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_type: str = Field(min_length=1, max_length=32)


class AdminWebReportExportJobDownloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    download_handle: str = Field(min_length=16, max_length=512)


class AdminWebTenantApiKeyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    scopes: Optional[list[str]] = Field(default=None, max_length=32)
    ip_allowlist: Optional[list[str]] = Field(default=None, max_length=32)


class AdminWebTenantApiKeyRevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential_handle: str = Field(min_length=16, max_length=512)


class AdminWebExternalSourceConnectionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_name: str = Field(min_length=1, max_length=64)
    source_key: str = Field(default="", max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    credentials: dict[str, str] = Field(min_length=1, max_length=32)


class AdminWebExternalSourceConnectionDisableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_handle: str = Field(min_length=16, max_length=512)


class AdminWebExternalCatalogSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_handle: str = Field(min_length=16, max_length=512)
    cursor: Optional[str] = Field(default=None, max_length=512)
    limit: int = Field(default=20, ge=1, le=100)
    max_pages: int = Field(default=1, ge=1, le=3)


class AdminWebPaymentConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gateway_url: Optional[str] = Field(default=None, max_length=512)
    base_url: Optional[str] = Field(default=None, max_length=512)
    merchant_id: Optional[str] = Field(default=None, max_length=128)
    pid: Optional[str] = Field(default=None, max_length=128)
    key: Optional[str] = Field(default=None, max_length=512)
    secret_key: Optional[str] = Field(default=None, max_length=512)
    token: Optional[str] = Field(default=None, max_length=32)
    network: Optional[str] = Field(default=None, max_length=32)
    payment_type: Optional[str] = Field(default=None, max_length=32)
    device: Optional[str] = Field(default=None, max_length=32)
    return_url: Optional[str] = Field(default=None, max_length=512)
    subject: Optional[str] = Field(default=None, max_length=128)


class AdminWebCreateResellerProductRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_offer_id: int = Field(gt=0)
    sale_price: Decimal = Field(gt=0)
    display_name: Optional[str] = Field(default=None, max_length=255)


class AdminWebResellerProductMetadataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Optional[str] = Field(default=None, max_length=128)
    sort_order: Optional[int] = Field(default=None, ge=-100000, le=100000)


class AdminWebResellerProductSalesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: Optional[str] = Field(default=None, max_length=255)
    sale_price: Optional[Decimal] = Field(default=None, gt=0)


class AdminWebTenantStoreSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_name: Optional[str] = Field(default=None, min_length=2, max_length=64)
    welcome_text: Optional[str] = Field(default=None, max_length=500)
    support_text: Optional[str] = Field(default=None, max_length=300)
    order_timeout_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    self_sale_enabled: Optional[bool] = None
    supplier_enabled: Optional[bool] = None
    reseller_enabled: Optional[bool] = None


class AdminWebSupplierApplicationReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_application_id: str = Field(min_length=16, max_length=512)
    action: Literal["approve", "reject"]


class AdminWebCreateSupplierOfferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int = Field(gt=0)
    suggested_price: Decimal = Field(gt=0)
    min_sale_price: Optional[Decimal] = Field(default=None, ge=0)
    requires_approval: bool = False


class AdminWebSupplierOfferApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requires_approval: bool


class AdminWebSupplierRuleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_rule_id: str = Field(min_length=16, max_length=512)
    pricing_value: Decimal = Field(gt=0)
    min_sale_price: Optional[Decimal] = Field(default=None, ge=0)


class AdminWebUserResponse(BaseModel):
    telegram_user_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    is_platform_admin: bool


class AdminWebWorkspaceResponse(BaseModel):
    workspace_id: str
    kind: str
    role: str
    title: str
    tenant_public_id: Optional[str] = None
    bot_username: Optional[str] = None
    tenant_status: Optional[str] = None
    bot_status: Optional[str] = None
    supplier_enabled: bool = False
    reseller_enabled: bool = False


class AdminWebSessionResponse(BaseModel):
    user: AdminWebUserResponse
    workspaces: list[AdminWebWorkspaceResponse]
    current_workspace_id: Optional[str] = None


class AdminWebTenantProductsOverviewResponse(BaseModel):
    total_count: int
    published_count: int
    available_inventory_count: int


class AdminWebTenantOrdersOverviewResponse(BaseModel):
    total_count: int
    pending_count: int
    paid_count: int
    delivered_count: int


class AdminWebTenantPaymentProviderOverviewResponse(BaseModel):
    provider_name: str
    display_name: str
    enabled: bool
    scope_type: str
    key_configured: bool
    create_payment_available: bool


class AdminWebTenantPaymentsOverviewResponse(BaseModel):
    total_count: int
    enabled_count: int
    providers: list[AdminWebTenantPaymentProviderOverviewResponse]


class AdminWebTenantSubscriptionOverviewResponse(BaseModel):
    status: Optional[str] = None
    plan_code: Optional[str] = None
    current_period_ends_at: Optional[str] = None


class AdminWebTenantFinanceOverviewResponse(BaseModel):
    currency: str
    pending_balance: Decimal
    available_balance: Decimal
    frozen_balance: Decimal
    pending_withdrawal_count: int


class AdminWebTenantSupplyOverviewResponse(BaseModel):
    supplier_enabled: bool
    reseller_enabled: bool
    supplier_offer_count: int
    reseller_product_count: int


class AdminWebTenantOverviewResponse(BaseModel):
    workspace: AdminWebWorkspaceResponse
    tenant_public_id: str
    store_name: str
    tenant_status: str
    bot_username: Optional[str] = None
    bot_status: Optional[str] = None
    products: AdminWebTenantProductsOverviewResponse
    orders: AdminWebTenantOrdersOverviewResponse
    payments: AdminWebTenantPaymentsOverviewResponse
    subscription: AdminWebTenantSubscriptionOverviewResponse
    finance: AdminWebTenantFinanceOverviewResponse
    supply: AdminWebTenantSupplyOverviewResponse


class AdminWebTenantStoreSettingsResponse(BaseModel):
    store_name: str
    welcome_text: str
    support_text: str
    order_timeout_minutes: int
    self_sale_enabled: bool
    supplier_enabled: bool
    reseller_enabled: bool


class AdminWebTenantProductItemResponse(BaseModel):
    product_id: int
    name: str
    category: Optional[str] = None
    sort_order: int
    status: str
    delivery_type: str
    price: Decimal
    currency: str
    available_count: int


class AdminWebTenantProductsResponse(BaseModel):
    total_count: int
    limit: int
    offset: int
    items: list[AdminWebTenantProductItemResponse]


class AdminWebTenantProductBatchStatusResponse(BaseModel):
    status: str
    updated_count: int
    products: list[AdminWebTenantProductItemResponse]


class AdminWebProductInventoryImportResponse(BaseModel):
    product_id: int
    added_count: int
    existing_count: int
    input_duplicate_count: int
    available_count: int


class AdminWebProductDeliveryFileResponse(BaseModel):
    product_id: int
    filename: str
    size_bytes: int
    content_type: Optional[str] = None
    risk_level: str
    scan_message: str
    bound: bool


class AdminWebTenantOrderItemResponse(BaseModel):
    out_trade_no: str
    source_type: str
    amount: Decimal
    currency: str
    status: str
    payment_mode: str
    buyer_telegram_user_id: int
    created_at: str
    expires_at: str
    paid_at: Optional[str] = None
    delivered_at: Optional[str] = None


class AdminWebTenantOrdersResponse(BaseModel):
    total_count: int
    limit: int
    offset: int
    items: list[AdminWebTenantOrderItemResponse]


class AdminWebOrderPaymentDiagnosticItemResponse(BaseModel):
    provider: str
    status: str
    amount: Decimal
    currency: str
    has_payment_url: bool
    created_at: str
    paid_at: Optional[str] = None


class AdminWebOrderPaymentCallbackDiagnosticItemResponse(BaseModel):
    provider: str
    process_status: str
    failure_reason: str
    created_at: str
    processed_at: Optional[str] = None


class AdminWebOrderDeliveryDiagnosticItemResponse(BaseModel):
    delivery_type: str
    status: str
    failure_reason: Optional[str] = None
    has_inventory_item: bool
    has_uploaded_file: bool
    has_telegram_chat: bool
    created_at: str
    updated_at: str
    sent_at: Optional[str] = None


class AdminWebOrderExternalFulfillmentDiagnosticItemResponse(BaseModel):
    expected: bool
    attempt_count: int
    latest_attempt_status: Optional[str] = None
    latest_attempt_trigger: Optional[str] = None
    latest_attempt_at: Optional[str] = None
    latest_failure_stage: Optional[str] = None
    latest_failure_category: Optional[str] = None
    latest_failure_retryable: Optional[bool] = None
    latest_upstream_status_code: Optional[int] = None
    latest_item_count: int
    latest_delivery_record_linked: bool


class AdminWebOrderTrc20DirectDiagnosticItemResponse(BaseModel):
    expected: bool
    transfer_count: int
    latest_match_status: Optional[str] = None
    latest_confirmations: Optional[int] = None
    latest_matched_at: Optional[str] = None
    latest_amount: Optional[Decimal] = None


class AdminWebTenantOrderDiagnosticsResponse(BaseModel):
    out_trade_no: str
    source_type: str
    status: str
    payment_mode: str
    payment_provider: Optional[str] = None
    amount: Decimal
    currency: str
    created_at: str
    expires_at: str
    paid_at: Optional[str] = None
    delivered_at: Optional[str] = None
    payment_count: int
    callback_count: int
    callback_status_counts: dict[str, int]
    payments: list[AdminWebOrderPaymentDiagnosticItemResponse]
    callbacks: list[AdminWebOrderPaymentCallbackDiagnosticItemResponse]
    delivery: Optional[AdminWebOrderDeliveryDiagnosticItemResponse] = None
    external_fulfillment: AdminWebOrderExternalFulfillmentDiagnosticItemResponse
    trc20_direct: AdminWebOrderTrc20DirectDiagnosticItemResponse


class AdminWebPaymentCallbackFailureItemResponse(BaseModel):
    created_at: str
    processed_at: Optional[str] = None
    out_trade_no: str
    order_status: str
    provider: str
    process_status: str
    failure_reason: str


class AdminWebPaymentCallbackRejectionItemResponse(BaseModel):
    created_at: str
    provider: str
    reason_category: str
    failure_reason: str
    http_status: int
    out_trade_no: Optional[str] = None
    order_status: Optional[str] = None
    payload_field_count: int


class AdminWebExternalFulfillmentAttemptItemResponse(BaseModel):
    created_at: str
    started_at: str
    finished_at: str
    out_trade_no: str
    provider_name: str
    source_key: str
    attempt_source: str
    status: str
    imported: bool
    item_count: int
    failure_reason: Optional[str] = None
    failure_stage: Optional[str] = None
    failure_category: Optional[str] = None
    failure_retryable: Optional[bool] = None
    upstream_status_code: Optional[int] = None


class AdminWebTenantOrderObservabilityResponse(BaseModel):
    limit: int
    callback_failures: list[AdminWebPaymentCallbackFailureItemResponse]
    callback_rejections: list[AdminWebPaymentCallbackRejectionItemResponse]
    external_fulfillment_attempts: list[AdminWebExternalFulfillmentAttemptItemResponse]


class AdminWebTenantSubscriptionInvoiceItemResponse(BaseModel):
    out_trade_no: str
    amount: Decimal
    currency: str
    status: str
    paid_at: Optional[str] = None
    created_at: str


class AdminWebTenantSubscriptionDashboardResponse(BaseModel):
    status: str
    plan_code: Optional[str] = None
    plan_name: Optional[str] = None
    monthly_price: Optional[Decimal] = None
    currency: Optional[str] = None
    trial_days: Optional[int] = None
    grace_days: Optional[int] = None
    trial_ends_at: Optional[str] = None
    current_period_ends_at: Optional[str] = None
    subscription_ends_at: Optional[str] = None
    grace_ends_at: Optional[str] = None
    suspended_at: Optional[str] = None
    data_retention_until: Optional[str] = None
    invoices: list[AdminWebTenantSubscriptionInvoiceItemResponse]


class AdminWebSubscriptionRenewalOrderResponse(BaseModel):
    out_trade_no: str
    amount: Decimal
    currency: str
    months: int
    expires_at: str
    payment_available: bool
    payment_provider: Optional[str] = None
    payment_url: Optional[str] = None
    payment_failure_reason: Optional[str] = None


class AdminWebTenantFinanceBalanceResponse(BaseModel):
    account_type: str
    currency: str
    pending_balance: Decimal
    available_balance: Decimal
    frozen_balance: Decimal


class AdminWebTenantFinanceAuditResponse(BaseModel):
    account_type: str
    currency: str
    stored_pending_balance: Decimal
    stored_available_balance: Decimal
    stored_frozen_balance: Decimal
    computed_pending_balance: Decimal
    computed_available_balance: Decimal
    computed_frozen_balance: Decimal
    pending_difference: Decimal
    available_difference: Decimal
    frozen_difference: Decimal
    is_balanced: bool


class AdminWebTenantWithdrawalItemResponse(BaseModel):
    amount: Decimal
    currency: str
    network: str
    address_masked: str
    status: str
    requested_at: str
    reviewed_at: Optional[str] = None
    completed_at: Optional[str] = None


class AdminWebTenantFinanceDashboardResponse(BaseModel):
    balance: AdminWebTenantFinanceBalanceResponse
    audit: AdminWebTenantFinanceAuditResponse
    withdrawals: list[AdminWebTenantWithdrawalItemResponse]


class AdminWebTenantAuditLogItemResponse(BaseModel):
    created_at: str
    actor_telegram_user_id: Optional[int] = None
    actor_username: Optional[str] = None
    action: str
    target_type: Optional[str] = None
    metadata: dict[str, Any]


class AdminWebTenantAuditLogsResponse(BaseModel):
    limit: int
    items: list[AdminWebTenantAuditLogItemResponse]


class AdminWebTenantReportExportJobItemResponse(BaseModel):
    report_type: str
    scope_type: str
    status: str
    row_count: int
    download_available: bool
    download_handle: Optional[str] = None
    failure_reason: Optional[str] = None
    expires_at: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class AdminWebTenantReportExportJobsResponse(BaseModel):
    status: str
    report_type: str
    limit: int
    export_jobs: list[AdminWebTenantReportExportJobItemResponse]


class AdminWebTenantApiKeyItemResponse(BaseModel):
    credential_handle: str
    name: str
    key_prefix: str
    status: str
    scopes: list[str]
    ip_allowlist: list[str]
    created_at: Optional[str] = None
    last_used_at: Optional[str] = None


class AdminWebTenantApiKeysResponse(BaseModel):
    limit: int
    keys: list[AdminWebTenantApiKeyItemResponse]


class AdminWebCreatedTenantApiKeyResponse(AdminWebTenantApiKeyItemResponse):
    plain_key: str


class AdminWebTenantApiKeyRevokeResponse(BaseModel):
    credential_handle: str
    revoked: bool


class AdminWebTenantRiskDisputeItemResponse(BaseModel):
    out_trade_no: str
    buyer_telegram_user_id: int
    source_type: str
    order_status: str
    amount: Decimal
    currency: str
    status: str
    reason: Optional[str] = None
    resolution: Optional[str] = None
    created_at: str
    updated_at: str


class AdminWebTenantRiskAfterSaleItemResponse(BaseModel):
    out_trade_no: str
    buyer_telegram_user_id: int
    source_type: str
    order_status: str
    amount: Decimal
    currency: str
    case_type: str
    status: str
    requested_amount: Optional[Decimal] = None
    refunded_amount: Decimal
    reason: Optional[str] = None
    resolution: Optional[str] = None
    created_at: str
    updated_at: str


class AdminWebTenantRiskDashboardResponse(BaseModel):
    status: str
    limit: int
    disputes: list[AdminWebTenantRiskDisputeItemResponse]
    after_sales: list[AdminWebTenantRiskAfterSaleItemResponse]


class AdminWebTenantPaymentProviderConfigItemResponse(BaseModel):
    provider: str
    display_name: str
    enabled: bool
    scope_type: str
    gateway_url: Optional[str] = None
    merchant_id_masked: Optional[str] = None
    asset: Optional[str] = None
    network: Optional[str] = None
    payment_type: Optional[str] = None
    device: Optional[str] = None
    return_url_configured: bool
    subject: Optional[str] = None
    key_configured: bool
    create_payment_available: bool
    callback_available: bool
    query_order_available: bool
    reconcile_available: bool
    production_ready: bool
    staging_verified: bool
    offline_only: bool


class AdminWebTenantPaymentProviderConfigsResponse(BaseModel):
    providers: list[AdminWebTenantPaymentProviderConfigItemResponse]


class AdminWebBusinessPluginCapabilityItemResponse(BaseModel):
    plugin_id: str
    provider_name: Optional[str] = None
    kind: str
    name: str
    version: str
    contract_version: str
    capabilities: dict[str, bool]
    production_ready: bool
    staging_verified: bool
    offline_only: bool
    tenant_configurable: bool
    platform_configurable: bool
    requires_tenant_enablement: bool
    workspace_configured: Optional[bool] = None
    workspace_enabled: Optional[bool] = None
    scope_type: Optional[str] = None
    active_connection_count: int = 0
    disabled_connection_count: int = 0


class AdminWebBusinessPluginCapabilitiesResponse(BaseModel):
    workspace: Optional[AdminWebWorkspaceResponse] = None
    workspace_id: str
    workspace_kind: str
    dynamic_loading_enabled: bool
    remote_code_enabled: bool
    real_external_integration_enabled: bool
    plugins: list[AdminWebBusinessPluginCapabilityItemResponse]


class AdminWebExternalSourceProviderItemResponse(BaseModel):
    provider_name: str
    integration_kind: str
    contract_name: Optional[str] = None
    production_ready: bool = False
    staging_verified: bool = False
    catalog_sync_available: bool
    catalog_context_available: bool
    catalog_product_available: bool
    catalog_product_context_available: bool
    order_available: bool
    order_context_available: bool
    delivery_available: bool
    delivery_context_available: bool
    auto_fulfillment_idempotent_available: bool = False


class AdminWebExternalSourceConnectionItemResponse(BaseModel):
    connection_handle: str
    provider_name: str
    source_key: str
    display_name: str
    status: str
    credential_field_count: int
    created_at: Optional[str] = None
    last_used_at: Optional[str] = None


class AdminWebExternalSourceConnectionsResponse(BaseModel):
    providers: list[AdminWebExternalSourceProviderItemResponse]
    connections: list[AdminWebExternalSourceConnectionItemResponse]


class AdminWebSyncedExternalCatalogProductResponse(BaseModel):
    product_id: Optional[int] = None
    action: str
    status: str
    skipped_reason: Optional[str] = None


class AdminWebExternalCatalogSyncResponse(BaseModel):
    provider_name: str
    source_key: str
    created_count: int
    updated_count: int
    skipped_count: int
    next_cursor: Optional[str] = None
    products: list[AdminWebSyncedExternalCatalogProductResponse]


class AdminWebExternalSourceCatalogProductItemResponse(BaseModel):
    product_id: int
    name: str
    category: Optional[str] = None
    status: str
    delivery_type: str
    price: Decimal
    currency: str
    available_count: int
    updated_at: Optional[str] = None


class AdminWebExternalSourceCatalogProductsResponse(BaseModel):
    connection_handle: str
    provider_name: str
    source_key: str
    display_name: str
    status: str
    total_count: int
    limit: int
    offset: int
    items: list[AdminWebExternalSourceCatalogProductItemResponse]


class AdminWebSupplierOfferItemResponse(BaseModel):
    supplier_offer_id: int
    product_name: str
    category: Optional[str] = None
    delivery_type: str
    suggested_price: Decimal
    min_sale_price: Optional[Decimal] = None
    supplier_cost: Decimal
    currency: str
    available_count: int
    requires_approval: bool
    status: str


class AdminWebCreatedSupplierOfferItemResponse(BaseModel):
    supplier_offer_id: int
    product_name: str
    delivery_type: str
    suggested_price: Decimal
    min_sale_price: Optional[Decimal] = None
    supplier_cost: Decimal
    currency: str
    requires_approval: bool
    status: str


class AdminWebSupplierOfferApprovalItemResponse(BaseModel):
    supplier_offer_id: int
    requires_approval: bool
    status: str


class AdminWebSupplyMarketOfferItemResponse(BaseModel):
    supplier_offer_id: int
    product_name: str
    category: Optional[str] = None
    delivery_type: str
    suggested_price: Decimal
    min_sale_price: Optional[Decimal] = None
    currency: str
    available_count: int
    requires_approval: bool
    reseller_rule_status: Optional[str] = None
    can_create_reseller_product: bool
    supplier_cost: Decimal
    effective_min_sale_price: Optional[Decimal] = None


class AdminWebSupplierApplicationItemResponse(BaseModel):
    supplier_application_id: str
    supplier_offer_id: int
    reseller_store_name: str
    product_name: str
    status: str
    pricing_value: Decimal
    min_sale_price: Optional[Decimal] = None
    currency: str
    updated_at: str


class AdminWebSupplierRuleItemResponse(BaseModel):
    supplier_rule_id: str
    supplier_offer_id: int
    reseller_store_name: str
    product_name: str
    status: str
    pricing_value: Decimal
    min_sale_price: Optional[Decimal] = None
    currency: str
    updated_at: str


class AdminWebResellerApplicationItemResponse(BaseModel):
    supplier_offer_id: int
    product_name: str
    status: str
    pricing_value: Decimal
    min_sale_price: Optional[Decimal] = None
    currency: str
    updated_at: str


class AdminWebResellerProductItemResponse(BaseModel):
    reseller_product_id: int
    supplier_offer_id: int
    display_name: str
    category: Optional[str] = None
    sort_order: int
    delivery_type: str
    sale_price: Decimal
    currency: str
    status: str
    available_count: int


class AdminWebTenantSupplyDashboardResponse(BaseModel):
    supplier_enabled: bool
    reseller_enabled: bool
    limit: int
    supplier_offers: list[AdminWebSupplierOfferItemResponse]
    supplier_applications: list[AdminWebSupplierApplicationItemResponse]
    supplier_rules: list[AdminWebSupplierRuleItemResponse]
    market_offers: list[AdminWebSupplyMarketOfferItemResponse]
    reseller_applications: list[AdminWebResellerApplicationItemResponse]
    reseller_products: list[AdminWebResellerProductItemResponse]


class AdminWebCreatedResellerProductItemResponse(BaseModel):
    reseller_product_id: int
    supplier_offer_id: int
    display_name: str
    sale_price: Decimal
    currency: str
    status: str


class AdminWebPlatformTenantBotItemResponse(BaseModel):
    tenant_public_id: str
    store_name: str
    tenant_status: str
    bot_username: Optional[str] = None
    bot_status: Optional[str] = None
    webhook_status: str
    webhook_reset_available: bool
    owner_telegram_user_id: int
    owner_username: Optional[str] = None
    subscription_status: Optional[str] = None
    plan_code: Optional[str] = None
    plan_name: Optional[str] = None
    current_period_ends_at: Optional[str] = None
    trial_ends_at: Optional[str] = None
    subscription_ends_at: Optional[str] = None
    last_health_checked_at: Optional[str] = None
    has_last_error: bool
    created_at: str


class AdminWebPlatformStatsResponse(BaseModel):
    tenant_count: int
    active_tenant_count: int
    suspended_tenant_count: int
    trial_subscription_count: int
    active_subscription_count: int
    grace_subscription_count: int
    suspended_subscription_count: int
    retention_expired_subscription_count: int
    active_bot_count: int
    pending_withdrawal_count: int
    banned_user_count: int
    disabled_supplier_offer_count: int


class AdminWebPlatformPaymentProviderItemResponse(BaseModel):
    provider_name: str
    display_name: str
    integration_kind: str
    contract_name: str
    production_ready: bool
    staging_verified: bool
    tenant_configurable: bool
    platform_configurable: bool
    create_payment_available: bool
    callback_available: bool
    query_order_available: bool
    reconcile_available: bool
    offline_only: bool
    supported_assets: list[str]
    supported_networks: list[str]
    configured_tenant_count: int
    enabled_tenant_count: int
    missing_config_tenant_count: int
    platform_configured: bool
    platform_enabled: bool


class AdminWebPlatformWithdrawalItemResponse(BaseModel):
    withdrawal_id: int
    tenant_public_id: Optional[str] = None
    store_name: Optional[str] = None
    amount: Decimal
    currency: str
    network: str
    address_masked: str
    status: str
    requested_at: str
    reviewed_at: Optional[str] = None
    completed_at: Optional[str] = None


class AdminWebPlatformSubscriptionPlanItemResponse(BaseModel):
    code: str
    name: str
    monthly_price: Decimal
    currency: str
    trial_days: int
    grace_days: int
    enabled: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AdminWebPlatformSubscriptionAttentionItemResponse(BaseModel):
    tenant_public_id: str
    store_name: str
    owner_telegram_user_id: int
    owner_username: Optional[str] = None
    tenant_status: str
    subscription_status: str
    plan_code: Optional[str] = None
    plan_name: Optional[str] = None
    attention_reason: str
    trial_ends_at: Optional[str] = None
    current_period_ends_at: Optional[str] = None
    subscription_ends_at: Optional[str] = None
    grace_ends_at: Optional[str] = None
    suspended_at: Optional[str] = None
    data_retention_until: Optional[str] = None


class AdminWebPlatformRiskBannedUserItemResponse(BaseModel):
    telegram_user_id: int
    username: Optional[str] = None
    is_banned: bool
    ban_source: Optional[str] = None
    latest_action: Optional[str] = None
    latest_action_at: Optional[str] = None
    reason: Optional[str] = None
    trigger_rule: Optional[str] = None
    blocked_count: Optional[int] = None
    threshold: Optional[int] = None
    window_seconds: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AdminWebPlatformRiskAuditLogItemResponse(BaseModel):
    created_at: str
    action: str
    target_type: Optional[str] = None
    actor_telegram_user_id: Optional[int] = None
    actor_username: Optional[str] = None
    target_telegram_user_id: Optional[int] = None
    previous_status: Optional[str] = None
    new_status: Optional[str] = None
    reason: Optional[str] = None
    risk_rule: Optional[str] = None
    blocked_count: Optional[int] = None
    threshold: Optional[int] = None
    window_seconds: Optional[int] = None


class AdminWebPlatformSupplierOfferItemResponse(BaseModel):
    supplier_offer_id: int
    supplier_store_name: str
    product_name: str
    delivery_type: str
    suggested_price: Decimal
    min_sale_price: Optional[Decimal] = None
    supplier_cost: Decimal
    currency: str
    available_count: int
    requires_approval: bool
    status: str
    created_at: str
    updated_at: str


class AdminWebPlatformDashboardResponse(BaseModel):
    stats: AdminWebPlatformStatsResponse
    tenants: list[AdminWebPlatformTenantBotItemResponse]
    payment_providers: list[AdminWebPlatformPaymentProviderItemResponse]
    withdrawals: list[AdminWebPlatformWithdrawalItemResponse]
    subscription_plans: list[AdminWebPlatformSubscriptionPlanItemResponse]
    subscription_attention: list[AdminWebPlatformSubscriptionAttentionItemResponse]
    banned_users: list[AdminWebPlatformRiskBannedUserItemResponse]
    risk_audit_logs: list[AdminWebPlatformRiskAuditLogItemResponse]
    supplier_offers: list[AdminWebPlatformSupplierOfferItemResponse]


class AdminWebPlatformRiskBanStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["banned", "active"]
    reason: Optional[str] = Field(default=None, max_length=500)


class AdminWebPlatformTenantSuspensionStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["suspended", "active"]
    reason: Optional[str] = Field(default=None, max_length=500)


class AdminWebPlatformTenantSuspensionStatusResponse(BaseModel):
    tenant_public_id: str
    previous_status: str
    status: str
    reason: Optional[str] = None


class AdminWebPlatformTenantSubscriptionGrantDaysRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = Field(ge=1, le=3650)
    reason: Optional[str] = Field(default=None, max_length=500)


class AdminWebPlatformTenantSubscriptionSetPeriodEndRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period_ends_at: datetime
    reason: Optional[str] = Field(default=None, max_length=500)


class AdminWebPlatformTenantSubscriptionAdjustmentResponse(BaseModel):
    tenant_public_id: str
    status: str
    previous_period_ends_at: Optional[str] = None
    new_period_ends_at: str
    action: str


class AdminWebPlatformBotStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["active", "disabled"]
    reason: Optional[str] = Field(default=None, max_length=500)


class AdminWebPlatformBotStatusResponse(BaseModel):
    tenant_public_id: str
    bot_username: str
    previous_status: str
    status: str
    reason: Optional[str] = None
    webhook_reset_available: bool = False


class AdminWebPlatformBotWebhookResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Optional[str] = Field(default=None, max_length=500)


class AdminWebPlatformBotWebhookResetResponse(BaseModel):
    tenant_public_id: str
    bot_username: str
    status: str
    webhook_status: str
    reason: Optional[str] = None
    telegram_webhook_called: bool = False


class AdminWebPlatformWithdrawalCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    admin_note: Optional[str] = Field(default=None, max_length=500)
    payout_reference: Optional[str] = Field(default=None, max_length=128)
    payout_proof_url: Optional[str] = Field(default=None, max_length=1000)


class AdminWebPlatformWithdrawalRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    admin_note: Optional[str] = Field(default=None, max_length=500)


class AdminWebPlatformSubscriptionPlanCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    monthly_price: Decimal = Field(ge=0)
    currency: str = Field(default="USDT", min_length=1, max_length=16)
    trial_days: int = Field(default=30, ge=0, le=3650)
    grace_days: int = Field(default=0, ge=0, le=365)
    enabled: bool = True
    reason: Optional[str] = Field(default=None, max_length=500)


class AdminWebPlatformSubscriptionPlanUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    monthly_price: Optional[Decimal] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, min_length=1, max_length=16)
    trial_days: Optional[int] = Field(default=None, ge=0, le=3650)
    grace_days: Optional[int] = Field(default=None, ge=0, le=365)
    reason: Optional[str] = Field(default=None, max_length=500)


class AdminWebPlatformSubscriptionPlanStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    reason: Optional[str] = Field(default=None, max_length=500)


class AdminWebPlatformSupplierOfferStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["on", "disabled"]
    reason: Optional[str] = Field(default=None, max_length=255)


def create_admin_web_router(settings: Settings) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/admin-web",
        tags=["admin-web"],
        route_class=AdminWebSafeValidationRoute,
    )
    local_binding_code_rate_limiter = FixedWindowRateLimiter(
        settings.admin_web_binding_code_rate_limit_per_minute,
        window_seconds=settings.rate_limit_window_seconds,
    )
    redis_binding_code_rate_limiter = RedisFixedWindowRateLimiter(
        settings.admin_web_binding_code_rate_limit_per_minute,
        window_seconds=settings.rate_limit_window_seconds,
        key_prefix=f"{settings.rate_limit_key_prefix}:admin-web-binding-code",
    )

    @router.post("/sessions/telegram", response_model=AdminWebSessionResponse)
    async def create_telegram_session(
        payload: AdminWebTelegramSessionRequest,
        request: Request,
        response: Response,
    ) -> AdminWebSessionResponse:
        _require_admin_web_origin(request, settings)
        service = AdminWebService()
        async with get_session_factory()() as session:
            bot_token = await _resolve_entrypoint_bot_token(service, session, settings, payload)
            try:
                telegram_user = validate_telegram_webapp_init_data(
                    payload.init_data,
                    bot_token,
                    max_age_seconds=settings.telegram_webapp_init_data_max_age_seconds,
                )
            except TelegramWebAppInitDataError as exc:
                raise HTTPException(status_code=401, detail=str(exc))

            user = await service.create_or_update_webapp_user(session, telegram_user, settings)
            if user.is_banned:
                raise HTTPException(status_code=403, detail="账号已被平台封禁")

            current_workspace_id = payload.tenant_public_id if payload.entrypoint == "tenant" else None
            if current_workspace_id:
                try:
                    await service.ensure_workspace_access(
                        session,
                        telegram_user_id=telegram_user.id,
                        workspace_id=current_workspace_id,
                    )
                except AdminWebSessionError as exc:
                    raise HTTPException(status_code=403, detail=str(exc))

            summary = await service.session_summary(
                session,
                telegram_user_id=telegram_user.id,
                current_workspace_id=current_workspace_id,
            )
            await session.commit()

        claims = AdminWebSessionCodec(settings).new_claims(
            telegram_user_id=summary.user.telegram_user_id,
            current_workspace_id=summary.current_workspace_id,
        )
        _set_session_cookie(response, settings, AdminWebSessionCodec(settings).encode(claims))
        return _session_response(summary)

    @router.post("/sessions/binding-code", response_model=AdminWebSessionResponse)
    async def create_binding_code_session(
        payload: AdminWebBindingCodeSessionRequest,
        request: Request,
        response: Response,
    ) -> AdminWebSessionResponse:
        _require_admin_web_origin(request, settings)
        redis_client = getattr(request.app.state, "redis", None)
        if redis_client is None:
            raise HTTPException(status_code=503, detail="绑定码服务暂不可用")
        try:
            await _hit_binding_code_rate_limit(
                request,
                settings,
                redis_client,
                redis_binding_code_rate_limiter,
                local_binding_code_rate_limiter,
            )
        except ApiRateLimitError as exc:
            raise HTTPException(status_code=429, detail=str(exc))
        try:
            code_claims = await AdminWebBindingCodeStore(settings, redis_client).consume_code(payload.code)
        except AdminWebBindingCodeError as exc:
            raise HTTPException(status_code=401, detail=str(exc))

        service = AdminWebService()
        async with get_session_factory()() as session:
            try:
                summary = await service.session_summary(
                    session,
                    telegram_user_id=code_claims.telegram_user_id,
                    current_workspace_id=code_claims.current_workspace_id,
                )
            except AdminWebSessionError as exc:
                raise HTTPException(status_code=401, detail=str(exc))

        claims = AdminWebSessionCodec(settings).new_claims(
            telegram_user_id=summary.user.telegram_user_id,
            current_workspace_id=summary.current_workspace_id,
        )
        _set_session_cookie(response, settings, AdminWebSessionCodec(settings).encode(claims))
        return _session_response(summary)

    @router.get("/session", response_model=AdminWebSessionResponse)
    async def get_session(
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebSessionResponse:
        claims = _decode_session_cookie(settings, session_cookie)
        service = AdminWebService()
        async with get_session_factory()() as session:
            try:
                summary = await service.session_summary(
                    session,
                    telegram_user_id=claims.telegram_user_id,
                    current_workspace_id=claims.current_workspace_id,
                )
            except AdminWebSessionError as exc:
                raise HTTPException(status_code=401, detail=str(exc))
        return _session_response(summary)

    @router.get("/workspaces", response_model=list[AdminWebWorkspaceResponse])
    async def list_workspaces(
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> list[AdminWebWorkspaceResponse]:
        claims = _decode_session_cookie(settings, session_cookie)
        service = AdminWebService()
        async with get_session_factory()() as session:
            workspaces = await service.list_workspaces(session, claims.telegram_user_id)
        return [_workspace_response(workspace) for workspace in workspaces]

    @router.get("/tenant/overview", response_model=AdminWebTenantOverviewResponse)
    async def tenant_overview(
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebTenantOverviewResponse:
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        async with get_session_factory()() as session:
            try:
                overview = await service.tenant_overview(
                    session,
                    settings=settings,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                )
            except AdminWebSessionError as exc:
                raise HTTPException(status_code=403, detail=str(exc))
        return _tenant_overview_response(overview)

    @router.get("/tenant/settings", response_model=AdminWebTenantStoreSettingsResponse)
    async def tenant_store_settings(
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebTenantStoreSettingsResponse:
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        async with get_session_factory()() as session:
            try:
                store_settings = await service.tenant_store_settings(
                    session,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                )
            except AdminWebSessionError as exc:
                raise HTTPException(status_code=403, detail=str(exc))
        return _tenant_store_settings_response(store_settings)

    @router.patch("/tenant/settings", response_model=AdminWebTenantStoreSettingsResponse)
    async def tenant_update_store_settings(
        payload: AdminWebTenantStoreSettingsRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebTenantStoreSettingsResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        requested_fields = payload.model_fields_set
        if not requested_fields:
            raise HTTPException(status_code=400, detail="店铺设置参数无效")
        if (
            ("store_name" in requested_fields and payload.store_name is None)
            or ("welcome_text" in requested_fields and payload.welcome_text is None)
            or ("support_text" in requested_fields and payload.support_text is None)
            or ("order_timeout_minutes" in requested_fields and payload.order_timeout_minutes is None)
            or ("self_sale_enabled" in requested_fields and payload.self_sale_enabled is None)
            or ("supplier_enabled" in requested_fields and payload.supplier_enabled is None)
            or ("reseller_enabled" in requested_fields and payload.reseller_enabled is None)
        ):
            raise HTTPException(status_code=400, detail="店铺设置参数无效")
        service = AdminWebService()
        try:
            async with get_session_factory()() as session:
                store_settings = await service.tenant_update_store_settings(
                    session,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    store_name=payload.store_name if "store_name" in requested_fields else None,
                    welcome_text=payload.welcome_text if "welcome_text" in requested_fields else None,
                    support_text=payload.support_text if "support_text" in requested_fields else None,
                    order_timeout_minutes=(
                        payload.order_timeout_minutes if "order_timeout_minutes" in requested_fields else None
                    ),
                    self_sale_enabled=(
                        payload.self_sale_enabled if "self_sale_enabled" in requested_fields else None
                    ),
                    supplier_enabled=(
                        payload.supplier_enabled if "supplier_enabled" in requested_fields else None
                    ),
                    reseller_enabled=(
                        payload.reseller_enabled if "reseller_enabled" in requested_fields else None
                    ),
                )
                await session.commit()
        except AdminWebSessionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            detail = str(exc) if str(exc) else "店铺设置参数无效"
            raise HTTPException(status_code=400, detail=detail)
        return _tenant_store_settings_response(store_settings)

    @router.get("/tenant/products", response_model=AdminWebTenantProductsResponse)
    async def tenant_products(
        limit: int = Query(default=50, ge=1),
        offset: int = Query(default=0, ge=0),
        query: Optional[str] = Query(default=None, max_length=128),
        status: Optional[Literal["draft", "on", "off"]] = None,
        delivery_type: Optional[Literal["card_pool", "card_fixed", "telegram_invite", "file_download"]] = None,
        category: Optional[str] = Query(default=None, max_length=128),
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebTenantProductsResponse:
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        normalized_limit = _normalize_page_limit(limit)
        normalized_offset = _normalize_page_offset(offset)
        service = AdminWebService()
        async with get_session_factory()() as session:
            try:
                products = await service.tenant_products(
                    session,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    limit=normalized_limit,
                    offset=normalized_offset,
                    query=query,
                    status=status,
                    delivery_type=delivery_type,
                    category=category,
                )
            except AdminWebSessionError as exc:
                raise HTTPException(status_code=403, detail=str(exc))
            except ValueError as exc:
                detail = str(exc) if str(exc) else "商品列表筛选参数无效"
                raise HTTPException(status_code=400, detail=detail)
        return _tenant_products_response(products)

    @router.post("/tenant/products", response_model=AdminWebTenantProductItemResponse)
    async def tenant_create_product(
        payload: AdminWebProductCreateRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebTenantProductItemResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        try:
            async with get_session_factory()() as session:
                product = await service.tenant_create_product(
                    session,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    name=payload.name,
                    price=payload.price,
                    delivery_type=payload.delivery_type,
                    description=payload.description,
                    category=payload.category,
                )
                await session.commit()
        except AdminWebSessionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError:
            raise HTTPException(status_code=400, detail="商品创建参数无效")
        return _tenant_product_response(product)

    @router.patch("/tenant/products/status", response_model=AdminWebTenantProductBatchStatusResponse)
    async def tenant_batch_update_product_status(
        payload: AdminWebProductBatchStatusRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebTenantProductBatchStatusResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        try:
            async with get_session_factory()() as session:
                result = await service.tenant_batch_update_product_status(
                    session,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    product_ids=payload.product_ids,
                    status=payload.status,
                )
                await session.commit()
        except AdminWebSessionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            detail = str(exc) if str(exc) else "批量商品状态参数无效"
            raise HTTPException(status_code=400, detail=detail)
        return _tenant_product_batch_status_response(result)

    @router.patch("/tenant/products/{product_id}/metadata", response_model=AdminWebTenantProductItemResponse)
    async def tenant_update_product_metadata(
        product_id: int,
        payload: AdminWebProductMetadataRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebTenantProductItemResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        requested_fields = payload.model_fields_set
        if "category" not in requested_fields and "sort_order" not in requested_fields:
            raise HTTPException(status_code=400, detail="商品元数据参数无效")
        if "sort_order" in requested_fields and payload.sort_order is None:
            raise HTTPException(status_code=400, detail="商品元数据参数无效")
        service = AdminWebService()
        try:
            async with get_session_factory()() as session:
                product = await service.tenant_update_product_metadata(
                    session,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    product_id=product_id,
                    category=payload.category,
                    category_provided="category" in requested_fields,
                    sort_order=payload.sort_order,
                )
                await session.commit()
        except AdminWebSessionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError:
            raise HTTPException(status_code=400, detail="商品元数据参数无效")
        return _tenant_product_response(product)

    @router.patch("/tenant/products/{product_id}/sales", response_model=AdminWebTenantProductItemResponse)
    async def tenant_update_product_sales(
        product_id: int,
        payload: AdminWebProductSalesRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebTenantProductItemResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        requested_fields = payload.model_fields_set
        if "price" not in requested_fields and "status" not in requested_fields:
            raise HTTPException(status_code=400, detail="商品销售参数无效")
        if "price" in requested_fields and payload.price is None:
            raise HTTPException(status_code=400, detail="商品销售参数无效")
        if "status" in requested_fields and payload.status is None:
            raise HTTPException(status_code=400, detail="商品销售参数无效")
        service = AdminWebService()
        try:
            async with get_session_factory()() as session:
                product = await service.tenant_update_product_sales(
                    session,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    product_id=product_id,
                    price=payload.price,
                    status=payload.status,
                )
                await session.commit()
        except AdminWebSessionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            detail = str(exc) if str(exc) else "商品销售参数无效"
            raise HTTPException(status_code=400, detail=detail)
        return _tenant_product_response(product)

    @router.post(
        "/tenant/products/{product_id}/inventory/import",
        response_model=AdminWebProductInventoryImportResponse,
    )
    async def tenant_import_product_inventory(
        product_id: int,
        payload: AdminWebProductInventoryImportRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebProductInventoryImportResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        try:
            async with get_session_factory()() as session:
                result = await service.tenant_import_product_inventory(
                    session,
                    settings=settings,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    product_id=product_id,
                    items=payload.items,
                )
                await session.commit()
        except AdminWebSessionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except RuntimeError:
            raise HTTPException(status_code=503, detail="库存加密配置不可用")
        except ValueError:
            raise HTTPException(status_code=400, detail="商品库存导入参数无效")
        return _inventory_import_response(result)

    @router.post(
        "/tenant/products/{product_id}/delivery-file",
        response_model=AdminWebProductDeliveryFileResponse,
    )
    async def tenant_upload_product_delivery_file(
        product_id: int,
        request: Request,
        file: UploadFile = File(...),
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebProductDeliveryFileResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        payload = await file.read()
        service = AdminWebService()
        try:
            async with get_session_factory()() as session:
                result = await service.tenant_upload_product_delivery_file(
                    session,
                    settings=settings,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    product_id=product_id,
                    filename=file.filename or "file.bin",
                    content_type=file.content_type,
                    payload=payload,
                )
                await session.commit()
        except AdminWebSessionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError:
            raise HTTPException(status_code=400, detail="文件商品绑定参数无效")
        return _product_delivery_file_response(result)

    @router.get("/tenant/orders", response_model=AdminWebTenantOrdersResponse)
    async def tenant_orders(
        limit: int = Query(default=50, ge=1),
        offset: int = Query(default=0, ge=0),
        out_trade_no: Optional[str] = Query(default=None, max_length=96),
        status: Optional[
            Literal["pending", "paid", "delivered", "expired", "completed", "refunded", "partially_refunded"]
        ] = None,
        source_type: Optional[Literal["self", "reseller", "subscription"]] = None,
        payment_mode: Optional[Literal["tenant_direct", "platform_escrow", "platform_subscription"]] = None,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebTenantOrdersResponse:
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        normalized_limit = _normalize_page_limit(limit)
        normalized_offset = _normalize_page_offset(offset)
        service = AdminWebService()
        async with get_session_factory()() as session:
            try:
                orders = await service.tenant_orders(
                    session,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    limit=normalized_limit,
                    offset=normalized_offset,
                    out_trade_no=out_trade_no,
                    status=status,
                    source_type=source_type,
                    payment_mode=payment_mode,
                )
            except AdminWebSessionError as exc:
                raise HTTPException(status_code=403, detail=str(exc))
        return _tenant_orders_response(orders)

    @router.get("/tenant/orders/observability", response_model=AdminWebTenantOrderObservabilityResponse)
    async def tenant_order_observability(
        limit: int = Query(default=10, ge=1, le=50),
        out_trade_no: Optional[str] = Query(default=None, max_length=96),
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebTenantOrderObservabilityResponse:
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        async with get_session_factory()() as session:
            try:
                observability = await service.tenant_order_observability(
                    session,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    limit=limit,
                    out_trade_no=out_trade_no,
                )
            except AdminWebSessionError as exc:
                raise HTTPException(status_code=403, detail=str(exc))
            except ValueError:
                raise HTTPException(status_code=400, detail="订单观测查询参数无效")
        return _tenant_order_observability_response(observability)

    @router.get(
        "/tenant/orders/{out_trade_no}/diagnostics",
        response_model=AdminWebTenantOrderDiagnosticsResponse,
    )
    async def tenant_order_diagnostics(
        out_trade_no: str,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebTenantOrderDiagnosticsResponse:
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        async with get_session_factory()() as session:
            try:
                diagnostics = await service.tenant_order_diagnostics(
                    session,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    out_trade_no=out_trade_no,
                )
            except AdminWebSessionError as exc:
                raise HTTPException(status_code=403, detail=str(exc))
            except ValueError:
                raise HTTPException(status_code=400, detail="订单号参数无效")
        return _tenant_order_diagnostics_response(diagnostics)

    @router.get("/tenant/subscription", response_model=AdminWebTenantSubscriptionDashboardResponse)
    async def tenant_subscription_dashboard(
        invoice_limit: int = 8,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebTenantSubscriptionDashboardResponse:
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        normalized_limit = _normalize_page_limit(invoice_limit)
        service = AdminWebService()
        async with get_session_factory()() as session:
            try:
                dashboard = await service.tenant_subscription_dashboard(
                    session,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    invoice_limit=normalized_limit,
                )
            except AdminWebSessionError as exc:
                raise HTTPException(status_code=403, detail=str(exc))
        return _tenant_subscription_dashboard_response(dashboard)

    @router.post(
        "/tenant/subscription/renewal-orders",
        response_model=AdminWebSubscriptionRenewalOrderResponse,
    )
    async def tenant_create_subscription_renewal_order(
        payload: AdminWebSubscriptionRenewalOrderRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebSubscriptionRenewalOrderResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        try:
            async with get_session_factory()() as session:
                renewal_order = await service.tenant_create_subscription_renewal_order(
                    session,
                    settings=settings,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    months=payload.months,
                )
                await session.commit()
        except AdminWebSessionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError:
            raise HTTPException(status_code=400, detail="订阅续费参数无效")
        return _subscription_renewal_order_response(renewal_order)

    @router.get("/tenant/finance", response_model=AdminWebTenantFinanceDashboardResponse)
    async def tenant_finance_dashboard(
        withdrawal_limit: int = 8,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebTenantFinanceDashboardResponse:
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        normalized_limit = _normalize_page_limit(withdrawal_limit)
        service = AdminWebService()
        async with get_session_factory()() as session:
            try:
                dashboard = await service.tenant_finance_dashboard(
                    session,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    withdrawal_limit=normalized_limit,
                )
            except AdminWebSessionError as exc:
                raise HTTPException(status_code=403, detail=str(exc))
        return _tenant_finance_dashboard_response(dashboard)

    @router.get("/tenant/audit-logs", response_model=AdminWebTenantAuditLogsResponse)
    async def tenant_audit_logs(
        action: Optional[str] = Query(default=None, max_length=128),
        target_type: Optional[str] = Query(default=None, max_length=64),
        limit: int = Query(default=20, ge=1),
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebTenantAuditLogsResponse:
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        normalized_limit = _normalize_page_limit(limit)
        service = AdminWebService()
        async with get_session_factory()() as session:
            try:
                page = await service.tenant_audit_logs(
                    session,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    limit=normalized_limit,
                    action=action,
                    target_type=target_type,
                )
            except AdminWebSessionError as exc:
                raise HTTPException(status_code=403, detail=str(exc))
            except ValueError:
                raise HTTPException(status_code=400, detail="审计日志查询参数无效")
        return _tenant_audit_logs_response(page)

    @router.get("/tenant/risk", response_model=AdminWebTenantRiskDashboardResponse)
    async def tenant_risk_dashboard(
        status: str = Query(default="open", max_length=32),
        limit: int = Query(default=20, ge=1),
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebTenantRiskDashboardResponse:
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        normalized_limit = _normalize_page_limit(limit)
        service = AdminWebService()
        async with get_session_factory()() as session:
            try:
                dashboard = await service.tenant_risk_dashboard(
                    session,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    status=status,
                    limit=normalized_limit,
                )
            except AdminWebSessionError as exc:
                raise HTTPException(status_code=403, detail=str(exc))
            except ValueError:
                raise HTTPException(status_code=400, detail="风控查询参数无效")
        return _tenant_risk_dashboard_response(dashboard)

    @router.get("/tenant/reports/export-jobs", response_model=AdminWebTenantReportExportJobsResponse)
    async def tenant_report_export_jobs(
        status: str = Query(default="all", max_length=32),
        report_type: str = Query(default="all", max_length=32),
        limit: int = Query(default=20, ge=1),
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebTenantReportExportJobsResponse:
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        normalized_limit = _normalize_page_limit(limit)
        service = AdminWebService()
        async with get_session_factory()() as session:
            try:
                page = await service.tenant_report_export_jobs(
                    session,
                    settings=settings,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    status=status,
                    report_type=report_type,
                    limit=normalized_limit,
                )
            except AdminWebSessionError as exc:
                raise HTTPException(status_code=403, detail=str(exc))
            except ValueError:
                raise HTTPException(status_code=400, detail="报表任务查询参数无效")
        return _tenant_report_export_jobs_response(page)

    @router.post("/tenant/reports/export-jobs", response_model=AdminWebTenantReportExportJobItemResponse)
    async def tenant_create_report_export_job(
        payload: AdminWebReportExportJobCreateRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebTenantReportExportJobItemResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        try:
            async with get_session_factory()() as session:
                job = await service.tenant_create_report_export_job(
                    session,
                    settings=settings,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    report_type=payload.report_type,
                )
                await session.commit()
        except AdminWebSessionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError:
            raise HTTPException(status_code=400, detail="报表任务参数无效")
        return _tenant_report_export_job_response(job)

    @router.post("/tenant/reports/export-jobs/download", response_class=FileResponse)
    async def tenant_download_report_export_job(
        payload: AdminWebReportExportJobDownloadRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> FileResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        file_info: Optional[AdminWebTenantReportExportDownloadFile]
        async with get_session_factory()() as session:
            try:
                file_info = await service.tenant_report_export_download_file(
                    session,
                    settings=settings,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    download_handle=payload.download_handle,
                )
                await session.commit()
            except AdminWebSessionError as exc:
                raise HTTPException(status_code=403, detail=str(exc))
            except ValueError as exc:
                await session.commit()
                raise HTTPException(status_code=403, detail="报表文件暂不可下载") from exc
        if file_info is None:
            raise HTTPException(status_code=404, detail="报表不存在")

        try:
            path = FileStorageService(settings).resolve_storage_key(file_info.storage_key)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="报表文件不存在") from exc
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="报表文件不存在")
        return FileResponse(
            path,
            media_type="text/csv; charset=utf-8",
            filename=file_info.filename or "export.csv",
        )

    @router.get("/tenant/api-keys", response_model=AdminWebTenantApiKeysResponse)
    async def tenant_api_keys(
        limit: int = Query(default=20, ge=1),
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebTenantApiKeysResponse:
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        normalized_limit = _normalize_page_limit(limit)
        service = AdminWebService()
        async with get_session_factory()() as session:
            try:
                page = await service.tenant_api_keys(
                    session,
                    settings=settings,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    limit=normalized_limit,
                )
            except AdminWebSessionError as exc:
                raise HTTPException(status_code=403, detail=str(exc))
            except ValueError:
                raise HTTPException(status_code=400, detail="API Key 查询参数无效")
        return _tenant_api_keys_response(page)

    @router.post("/tenant/api-keys", response_model=AdminWebCreatedTenantApiKeyResponse)
    async def tenant_create_api_key(
        payload: AdminWebTenantApiKeyCreateRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebCreatedTenantApiKeyResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        try:
            async with get_session_factory()() as session:
                api_key = await service.tenant_create_api_key(
                    session,
                    settings=settings,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    name=payload.name,
                    scopes=payload.scopes,
                    ip_allowlist=payload.ip_allowlist,
                )
                await session.commit()
        except AdminWebSessionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="API Key 服务暂不可用") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_admin_web_api_key_error_detail(exc))
        return _created_tenant_api_key_response(api_key)

    @router.post("/tenant/api-keys/revoke", response_model=AdminWebTenantApiKeyRevokeResponse)
    async def tenant_revoke_api_key(
        payload: AdminWebTenantApiKeyRevokeRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebTenantApiKeyRevokeResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        try:
            async with get_session_factory()() as session:
                result = await service.tenant_revoke_api_key(
                    session,
                    settings=settings,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    credential_handle=payload.credential_handle,
                )
                await session.commit()
        except AdminWebSessionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="API Key 服务暂不可用") from exc
        except ValueError:
            raise HTTPException(status_code=400, detail="API Key 参数无效")
        return _tenant_api_key_revoke_response(result)

    @router.post("/tenant/finance/withdrawals", response_model=AdminWebTenantWithdrawalItemResponse)
    async def tenant_create_withdrawal(
        payload: AdminWebWithdrawalRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebTenantWithdrawalItemResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        try:
            async with get_session_factory()() as session:
                withdrawal = await service.tenant_create_withdrawal_request(
                    session,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    amount=payload.amount,
                    network=payload.network,
                    address=payload.address,
                    currency=payload.currency,
                )
                await session.commit()
        except AdminWebSessionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="提现服务暂不可用") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_finance_error_detail(exc))
        return _tenant_withdrawal_response(withdrawal)

    @router.get("/tenant/payments/configs", response_model=AdminWebTenantPaymentProviderConfigsResponse)
    async def tenant_payment_configs(
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebTenantPaymentProviderConfigsResponse:
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        async with get_session_factory()() as session:
            try:
                configs = await service.tenant_payment_configs(
                    session,
                    settings=settings,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                )
            except AdminWebSessionError as exc:
                raise HTTPException(status_code=403, detail=str(exc))
            except ValueError:
                raise HTTPException(status_code=400, detail="支付配置参数无效")
        return _tenant_payment_configs_response(configs)

    @router.get("/business-plugins/capabilities", response_model=AdminWebBusinessPluginCapabilitiesResponse)
    async def business_plugin_capabilities(
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebBusinessPluginCapabilitiesResponse:
        claims = _decode_session_cookie(settings, session_cookie)
        if not claims.current_workspace_id:
            raise HTTPException(status_code=403, detail="请选择管理工作区")
        service = AdminWebService()
        async with get_session_factory()() as session:
            try:
                summary = await service.business_plugin_capabilities(
                    session,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=claims.current_workspace_id,
                )
            except AdminWebSessionError as exc:
                raise HTTPException(status_code=403, detail=str(exc))
        return _business_plugin_capabilities_response(summary)

    @router.get("/tenant/external-source-connections", response_model=AdminWebExternalSourceConnectionsResponse)
    async def tenant_external_source_connections(
        provider_name: Optional[str] = Query(default=None, max_length=64),
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebExternalSourceConnectionsResponse:
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        async with get_session_factory()() as session:
            try:
                page = await service.tenant_external_source_connections(
                    session,
                    settings=settings,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    provider_name=provider_name,
                )
            except AdminWebSessionError as exc:
                raise HTTPException(status_code=403, detail=str(exc))
            except ValueError:
                raise HTTPException(status_code=400, detail="外部源连接查询参数无效")
        return _external_source_connections_response(page)

    @router.post("/tenant/external-source-connections", response_model=AdminWebExternalSourceConnectionItemResponse)
    async def tenant_create_external_source_connection(
        payload: AdminWebExternalSourceConnectionCreateRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebExternalSourceConnectionItemResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        try:
            async with get_session_factory()() as session:
                connection = await service.tenant_create_external_source_connection(
                    session,
                    settings=settings,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    provider_name=payload.provider_name,
                    source_key=payload.source_key,
                    display_name=payload.display_name,
                    credentials=payload.credentials,
                )
                await session.commit()
        except AdminWebSessionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="外部源连接服务暂不可用") from exc
        except ValueError:
            raise HTTPException(status_code=400, detail="外部源连接参数无效")
        return _external_source_connection_response(connection)

    @router.post(
        "/tenant/external-source-connections/disable",
        response_model=AdminWebExternalSourceConnectionItemResponse,
    )
    async def tenant_disable_external_source_connection(
        payload: AdminWebExternalSourceConnectionDisableRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebExternalSourceConnectionItemResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        try:
            async with get_session_factory()() as session:
                connection = await service.tenant_disable_external_source_connection(
                    session,
                    settings=settings,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    connection_handle=payload.connection_handle,
                )
                await session.commit()
        except AdminWebSessionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="外部源连接服务暂不可用") from exc
        except ValueError:
            raise HTTPException(status_code=400, detail="外部源连接参数无效")
        return _external_source_connection_response(connection)

    @router.post(
        "/tenant/external-sources/catalog/sync",
        response_model=AdminWebExternalCatalogSyncResponse,
    )
    async def tenant_sync_external_catalog(
        payload: AdminWebExternalCatalogSyncRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebExternalCatalogSyncResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        try:
            async with get_session_factory()() as session:
                result = await service.tenant_sync_external_catalog(
                    session,
                    settings=settings,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    connection_handle=payload.connection_handle,
                    cursor=payload.cursor,
                    limit=payload.limit,
                    max_pages=payload.max_pages,
                )
                await session.commit()
        except AdminWebSessionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ExternalProviderNotRegisteredError as exc:
            raise HTTPException(status_code=404, detail="外部发卡源 provider 不存在") from exc
        except ExternalSourceError as exc:
            raise HTTPException(status_code=502, detail="外部源目录同步失败") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="外部源目录同步服务暂不可用") from exc
        except ValueError:
            raise HTTPException(status_code=400, detail="外部源目录同步参数无效")
        return _external_catalog_sync_response(result)

    @router.get(
        "/tenant/external-sources/catalog/products",
        response_model=AdminWebExternalSourceCatalogProductsResponse,
    )
    async def tenant_external_source_catalog_products(
        connection_handle: str = Query(min_length=16, max_length=512),
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=100000),
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebExternalSourceCatalogProductsResponse:
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        try:
            async with get_session_factory()() as session:
                page = await service.tenant_external_source_catalog_products(
                    session,
                    settings=settings,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    connection_handle=connection_handle,
                    limit=limit,
                    offset=offset,
                )
        except AdminWebSessionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="外部源商品查询服务暂不可用") from exc
        except ValueError:
            raise HTTPException(status_code=400, detail="外部源商品查询参数无效")
        return _external_source_catalog_products_response(page)

    @router.put(
        "/tenant/payments/{provider_name}/config",
        response_model=AdminWebTenantPaymentProviderConfigItemResponse,
    )
    async def tenant_update_payment_config(
        provider_name: str,
        payload: AdminWebPaymentConfigRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebTenantPaymentProviderConfigItemResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        try:
            config_payload = _admin_web_payment_config_payload(provider_name, payload)
            async with get_session_factory()() as session:
                config = await service.tenant_update_payment_config(
                    session,
                    settings=settings,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    provider_name=provider_name,
                    config_payload=config_payload,
                )
                await session.commit()
        except AdminWebSessionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError:
            raise HTTPException(status_code=400, detail="支付配置参数无效")
        return _tenant_payment_config_response(config)

    @router.delete(
        "/tenant/payments/{provider_name}/config",
        response_model=AdminWebTenantPaymentProviderConfigItemResponse,
    )
    async def tenant_disable_payment_config(
        provider_name: str,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebTenantPaymentProviderConfigItemResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        try:
            async with get_session_factory()() as session:
                config = await service.tenant_disable_payment_config(
                    session,
                    settings=settings,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    provider_name=provider_name,
                )
                await session.commit()
        except AdminWebSessionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError:
            raise HTTPException(status_code=400, detail="支付配置参数无效")
        return _tenant_payment_config_response(config)

    @router.get("/tenant/supply/dashboard", response_model=AdminWebTenantSupplyDashboardResponse)
    async def tenant_supply_dashboard(
        request: Request,
        limit: int = 20,
        market_query: Optional[str] = None,
        market_delivery_type: Optional[str] = None,
        market_access: Optional[str] = None,
        market_min_price: Optional[Decimal] = None,
        market_max_price: Optional[Decimal] = None,
        market_stock: Optional[str] = None,
        market_category: Optional[str] = None,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebTenantSupplyDashboardResponse:
        _require_admin_web_supply_dashboard_query_params(request)
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        normalized_limit = _normalize_page_limit(limit)
        service = AdminWebService()
        async with get_session_factory()() as session:
            try:
                dashboard = await service.tenant_supply_dashboard(
                    session,
                    settings=settings,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    limit=normalized_limit,
                    market_query=market_query,
                    market_delivery_type=market_delivery_type,
                    market_access=market_access,
                    market_min_price=market_min_price,
                    market_max_price=market_max_price,
                    market_stock=market_stock,
                    market_category=market_category,
                )
            except AdminWebSessionError as exc:
                raise HTTPException(status_code=403, detail=str(exc))
            except ValueError:
                raise HTTPException(status_code=400, detail="供货市场筛选参数无效")
        return _tenant_supply_dashboard_response(dashboard)

    @router.post("/tenant/supply/applications", response_model=AdminWebResellerApplicationItemResponse)
    async def tenant_supply_apply(
        payload: AdminWebSupplyApplicationRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebResellerApplicationItemResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        try:
            async with get_session_factory()() as session:
                application = await service.tenant_supply_apply(
                    session,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    supplier_offer_id=payload.supplier_offer_id,
                )
                await session.commit()
        except AdminWebSessionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError:
            raise HTTPException(status_code=400, detail="供货代理申请参数无效")
        return _reseller_application_response(application)

    @router.post(
        "/tenant/supply/supplier-applications/review",
        response_model=AdminWebSupplierApplicationItemResponse,
    )
    async def tenant_supply_review_supplier_application(
        payload: AdminWebSupplierApplicationReviewRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebSupplierApplicationItemResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        try:
            async with get_session_factory()() as session:
                application = await service.tenant_supply_review_supplier_application(
                    session,
                    settings=settings,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    supplier_application_id=payload.supplier_application_id,
                    action=payload.action,
                )
                await session.commit()
        except AdminWebSessionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError:
            raise HTTPException(status_code=400, detail="供货申请审核参数无效")
        return _supplier_application_response(application)

    @router.post("/tenant/supply/supplier-offers", response_model=AdminWebCreatedSupplierOfferItemResponse)
    async def tenant_supply_create_supplier_offer(
        payload: AdminWebCreateSupplierOfferRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebCreatedSupplierOfferItemResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        try:
            async with get_session_factory()() as session:
                offer = await service.tenant_supply_create_supplier_offer(
                    session,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    product_id=payload.product_id,
                    suggested_price=payload.suggested_price,
                    min_sale_price=payload.min_sale_price,
                    requires_approval=payload.requires_approval,
                )
                await session.commit()
        except AdminWebSessionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError:
            raise HTTPException(status_code=400, detail="供货商品参数无效")
        return _created_supplier_offer_response(offer)

    @router.patch(
        "/tenant/supply/supplier-offers/{supplier_offer_id}/approval",
        response_model=AdminWebSupplierOfferApprovalItemResponse,
    )
    async def tenant_supply_set_supplier_offer_approval(
        supplier_offer_id: int,
        payload: AdminWebSupplierOfferApprovalRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebSupplierOfferApprovalItemResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        try:
            async with get_session_factory()() as session:
                setting = await service.tenant_supply_set_supplier_offer_approval(
                    session,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    supplier_offer_id=supplier_offer_id,
                    requires_approval=payload.requires_approval,
                )
                await session.commit()
        except AdminWebSessionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError:
            raise HTTPException(status_code=400, detail="供货审批参数无效")
        return _supplier_offer_approval_response(setting)

    @router.post("/tenant/supply/supplier-rules", response_model=AdminWebSupplierRuleItemResponse)
    async def tenant_supply_set_supplier_rule(
        payload: AdminWebSupplierRuleRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebSupplierRuleItemResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        try:
            async with get_session_factory()() as session:
                rule = await service.tenant_supply_set_supplier_rule(
                    session,
                    settings=settings,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    supplier_rule_id=payload.supplier_rule_id,
                    pricing_value=payload.pricing_value,
                    min_sale_price=payload.min_sale_price,
                )
                await session.commit()
        except AdminWebSessionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError:
            raise HTTPException(status_code=400, detail="代理规则参数无效")
        return _supplier_rule_response(rule)

    @router.post("/tenant/supply/reseller-products", response_model=AdminWebCreatedResellerProductItemResponse)
    async def tenant_supply_create_reseller_product(
        payload: AdminWebCreateResellerProductRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebCreatedResellerProductItemResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        try:
            async with get_session_factory()() as session:
                product = await service.tenant_supply_create_reseller_product(
                    session,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    supplier_offer_id=payload.supplier_offer_id,
                    sale_price=payload.sale_price,
                    display_name=payload.display_name,
                )
                await session.commit()
        except AdminWebSessionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError:
            raise HTTPException(status_code=400, detail="代理商品参数无效")
        return _created_reseller_product_response(product)

    @router.patch(
        "/tenant/supply/reseller-products/{reseller_product_id}/metadata",
        response_model=AdminWebResellerProductItemResponse,
    )
    async def tenant_supply_update_reseller_product_metadata(
        reseller_product_id: int,
        payload: AdminWebResellerProductMetadataRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebResellerProductItemResponse:
        _require_admin_web_origin(request, settings)
        requested_fields = payload.model_fields_set
        if "category" not in requested_fields and "sort_order" not in requested_fields:
            raise HTTPException(status_code=400, detail="代理商品元数据参数无效")
        if "sort_order" in requested_fields and payload.sort_order is None:
            raise HTTPException(status_code=400, detail="代理商品排序必须是整数")
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        try:
            async with get_session_factory()() as session:
                product = await service.tenant_supply_update_reseller_product_metadata(
                    session,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    reseller_product_id=reseller_product_id,
                    category=payload.category,
                    category_provided="category" in requested_fields,
                    sort_order=payload.sort_order,
                )
                await session.commit()
        except AdminWebSessionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError:
            raise HTTPException(status_code=400, detail="代理商品元数据参数无效")
        return _reseller_product_response(product)

    @router.patch(
        "/tenant/supply/reseller-products/{reseller_product_id}/sales",
        response_model=AdminWebResellerProductItemResponse,
    )
    async def tenant_supply_update_reseller_product_sales(
        reseller_product_id: int,
        payload: AdminWebResellerProductSalesRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebResellerProductItemResponse:
        _require_admin_web_origin(request, settings)
        requested_fields = payload.model_fields_set
        if "display_name" not in requested_fields and "sale_price" not in requested_fields:
            raise HTTPException(status_code=400, detail="代理商品销售参数无效")
        if "sale_price" in requested_fields and payload.sale_price is None:
            raise HTTPException(status_code=400, detail="代理商品售价必须大于 0")
        claims = _decode_session_cookie(settings, session_cookie)
        workspace_id = _require_current_tenant_workspace(claims.current_workspace_id)
        service = AdminWebService()
        try:
            async with get_session_factory()() as session:
                product = await service.tenant_supply_update_reseller_product_sales(
                    session,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=workspace_id,
                    reseller_product_id=reseller_product_id,
                    sale_price=payload.sale_price,
                    display_name=payload.display_name,
                    display_name_provided="display_name" in requested_fields,
                )
                await session.commit()
        except AdminWebSessionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError:
            raise HTTPException(status_code=400, detail="代理商品销售参数无效")
        return _reseller_product_response(product)

    @router.get("/platform/dashboard", response_model=AdminWebPlatformDashboardResponse)
    async def platform_dashboard(
        tenant_limit: int = 50,
        tenant_offset: int = 0,
        tenant_query: Optional[str] = Query(default=None, max_length=128),
        tenant_status: Optional[Literal["all", "trial", "active", "grace", "suspended", "retention_expired"]] = "all",
        bot_status: Optional[Literal["all", "active", "disabled", "missing"]] = "all",
        subscription_status: Optional[Literal["all", "trial", "active", "grace", "suspended", "retention_expired"]] = "all",
        withdrawal_limit: int = 20,
        plan_limit: int = 20,
        subscription_attention_limit: int = 20,
        risk_limit: int = 20,
        audit_limit: int = 20,
        supply_limit: int = 20,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebPlatformDashboardResponse:
        claims = _decode_session_cookie(settings, session_cookie)
        async with get_session_factory()() as session:
            await _require_platform_admin_user(session, claims.telegram_user_id)
            subscription_service = SubscriptionService()
            tenants = await _list_platform_tenant_bots(
                session,
                limit=_normalize_page_limit(tenant_limit),
                offset=_normalize_page_offset(tenant_offset),
                query=tenant_query,
                tenant_status=tenant_status,
                bot_status=bot_status,
                subscription_status=subscription_status,
            )
            withdrawals = await LedgerService().list_pending_withdrawals(
                session,
                limit=_normalize_page_limit(withdrawal_limit),
            )
            subscription_plans = await subscription_service.list_platform_subscription_plans(
                session,
                limit=_normalize_page_limit(plan_limit),
            )
            subscription_attention = await subscription_service.list_platform_subscription_attention(
                session,
                limit=_normalize_page_limit(subscription_attention_limit),
            )
            banned_users = await RiskControlService(settings).list_banned_platform_users(
                session,
                source="all",
                limit=_normalize_page_limit(risk_limit),
            )
            audit_logs = await AuditLogService().list_platform_risk_audit_logs(
                session,
                limit=_normalize_page_limit(audit_limit),
            )
            supplier_offers = await SupplyService().list_platform_supplier_offers(
                session,
                limit=_normalize_page_limit(supply_limit),
            )
            stats = await _platform_stats_response(session)
            payment_providers = await _list_platform_payment_provider_observations(
                session,
                settings,
                tenant_count=stats.tenant_count,
            )
            withdrawal_responses = [
                await _platform_withdrawal_response(session, withdrawal)
                for withdrawal in withdrawals
            ]
        return AdminWebPlatformDashboardResponse(
            stats=stats,
            tenants=tenants,
            payment_providers=payment_providers,
            withdrawals=withdrawal_responses,
            subscription_plans=[
                _platform_subscription_plan_response(plan)
                for plan in subscription_plans
            ],
            subscription_attention=[
                _platform_subscription_attention_response(item)
                for item in subscription_attention
            ],
            banned_users=[
                _platform_risk_banned_user_response(user)
                for user in banned_users
            ],
            risk_audit_logs=[
                _platform_risk_audit_log_response(audit_log)
                for audit_log in audit_logs
            ],
            supplier_offers=[
                _platform_supplier_offer_response(offer)
                for offer in supplier_offers
            ],
        )

    @router.patch(
        "/platform/risk/users/{telegram_user_id}/ban-status",
        response_model=AdminWebPlatformRiskBannedUserItemResponse,
    )
    async def platform_update_user_ban_status(
        telegram_user_id: int,
        payload: AdminWebPlatformRiskBanStatusUpdateRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebPlatformRiskBannedUserItemResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        try:
            async with get_session_factory()() as session:
                actor = await _require_platform_admin_user(session, claims.telegram_user_id)
                risk_service = RiskControlService(settings)
                if payload.status == "banned":
                    await risk_service.ban_platform_user(
                        session,
                        telegram_user_id=telegram_user_id,
                        actor_user_id=actor.id,
                        reason=payload.reason,
                    )
                else:
                    await risk_service.unban_platform_user(
                        session,
                        telegram_user_id=telegram_user_id,
                        actor_user_id=actor.id,
                        reason=payload.reason,
                    )
                summary = await risk_service.get_platform_user_ban_status(
                    session,
                    telegram_user_id=telegram_user_id,
                )
                await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_admin_web_platform_error_detail(exc))
        if summary is None:
            raise HTTPException(status_code=404, detail="平台用户不存在")
        return _platform_risk_banned_user_response(summary)

    @router.patch(
        "/platform/risk/tenants/{tenant_public_id}/suspension-status",
        response_model=AdminWebPlatformTenantSuspensionStatusResponse,
    )
    async def platform_update_tenant_suspension_status(
        tenant_public_id: str,
        payload: AdminWebPlatformTenantSuspensionStatusUpdateRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebPlatformTenantSuspensionStatusResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        try:
            async with get_session_factory()() as session:
                actor = await _require_platform_admin_user(session, claims.telegram_user_id)
                tenant = await _get_tenant_by_public_id(session, tenant_public_id)
                if tenant is None:
                    raise HTTPException(status_code=404, detail="克隆 Bot 工作区不存在")
                risk_service = RiskControlService(settings)
                if payload.status == "suspended":
                    result = await risk_service.suspend_tenant(
                        session,
                        tenant_id=tenant.id,
                        actor_user_id=actor.id,
                        reason=payload.reason,
                    )
                else:
                    result = await risk_service.resume_tenant(
                        session,
                        tenant_id=tenant.id,
                        actor_user_id=actor.id,
                        reason=payload.reason,
                    )
                await session.commit()
            await _clear_tenant_webhook_cache(request, result.webhook_secrets)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_admin_web_platform_error_detail(exc))
        return AdminWebPlatformTenantSuspensionStatusResponse(
            tenant_public_id=tenant_public_id,
            previous_status=result.previous_status,
            status=result.new_status,
            reason=result.reason,
        )

    @router.post(
        "/platform/tenants/{tenant_public_id}/subscription/grant-days",
        response_model=AdminWebPlatformTenantSubscriptionAdjustmentResponse,
    )
    async def platform_grant_tenant_subscription_days(
        tenant_public_id: str,
        payload: AdminWebPlatformTenantSubscriptionGrantDaysRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebPlatformTenantSubscriptionAdjustmentResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        try:
            async with get_session_factory()() as session:
                actor = await _require_platform_admin_user(session, claims.telegram_user_id)
                tenant = await _get_tenant_by_public_id(session, tenant_public_id)
                if tenant is None:
                    raise HTTPException(status_code=404, detail="克隆 Bot 工作区不存在")
                result = await SubscriptionService().grant_days(
                    session=session,
                    tenant_id=tenant.id,
                    actor_user_id=actor.id,
                    days=payload.days,
                    monthly_price=settings.subscription_monthly_price,
                    reason=payload.reason,
                )
                await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_admin_web_platform_error_detail(exc))
        return _platform_tenant_subscription_adjustment_response(tenant_public_id, result)

    @router.patch(
        "/platform/tenants/{tenant_public_id}/subscription/period-end",
        response_model=AdminWebPlatformTenantSubscriptionAdjustmentResponse,
    )
    async def platform_set_tenant_subscription_period_end(
        tenant_public_id: str,
        payload: AdminWebPlatformTenantSubscriptionSetPeriodEndRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebPlatformTenantSubscriptionAdjustmentResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        try:
            async with get_session_factory()() as session:
                actor = await _require_platform_admin_user(session, claims.telegram_user_id)
                tenant = await _get_tenant_by_public_id(session, tenant_public_id)
                if tenant is None:
                    raise HTTPException(status_code=404, detail="克隆 Bot 工作区不存在")
                result = await SubscriptionService().set_period_end(
                    session=session,
                    tenant_id=tenant.id,
                    actor_user_id=actor.id,
                    period_ends_at=payload.period_ends_at,
                    monthly_price=settings.subscription_monthly_price,
                    reason=payload.reason,
                )
                await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_admin_web_platform_error_detail(exc))
        return _platform_tenant_subscription_adjustment_response(tenant_public_id, result)

    @router.get(
        "/platform/finance/withdrawals/{withdrawal_id}",
        response_model=AdminWebPlatformWithdrawalItemResponse,
    )
    async def platform_withdrawal_detail(
        withdrawal_id: int,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebPlatformWithdrawalItemResponse:
        claims = _decode_session_cookie(settings, session_cookie)
        async with get_session_factory()() as session:
            await _require_platform_admin_user(session, claims.telegram_user_id)
            withdrawal = await LedgerService().get_platform_withdrawal(
                session,
                withdrawal_id=withdrawal_id,
            )
            if withdrawal is None:
                raise HTTPException(status_code=404, detail="提现申请不存在")
            return await _platform_withdrawal_response(session, withdrawal)

    @router.patch("/platform/bots/{tenant_public_id}/status", response_model=AdminWebPlatformBotStatusResponse)
    async def platform_update_bot_status(
        tenant_public_id: str,
        payload: AdminWebPlatformBotStatusUpdateRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebPlatformBotStatusResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        async with get_session_factory()() as session:
            actor = await _require_platform_admin_user(session, claims.telegram_user_id)
            tenant_bot = await _get_latest_tenant_bot_by_public_id(session, tenant_public_id, for_update=True)
            if tenant_bot is None:
                raise HTTPException(status_code=404, detail="克隆 Bot 不存在")
            previous_status = tenant_bot.status
            tenant_bot.status = payload.status
            session.add(
                AuditLog(
                    tenant_id=tenant_bot.tenant_id,
                    actor_user_id=actor.id,
                    action="admin_web.platform_bot_status_updated",
                    target_type="tenant_bot",
                    target_id=str(tenant_public_id),
                    metadata_json={
                        "bot_username": tenant_bot.bot_username,
                        "previous_status": previous_status,
                        "new_status": payload.status,
                        "reason": _safe_admin_web_reason(payload.reason),
                        "telegram_webhook_called": False,
                    },
                )
            )
            await session.flush()
            webhook_secret = tenant_bot.webhook_secret
            bot_username = tenant_bot.bot_username
            await session.commit()
        await _clear_tenant_webhook_cache(request, (webhook_secret,))
        return AdminWebPlatformBotStatusResponse(
            tenant_public_id=tenant_public_id,
            bot_username=bot_username,
            previous_status=previous_status,
            status=payload.status,
            reason=_safe_admin_web_reason(payload.reason),
            webhook_reset_available=payload.status == "active",
        )

    @router.post(
        "/platform/bots/{tenant_public_id}/webhook/reset",
        response_model=AdminWebPlatformBotWebhookResetResponse,
    )
    async def platform_reset_bot_webhook(
        tenant_public_id: str,
        payload: AdminWebPlatformBotWebhookResetRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebPlatformBotWebhookResetResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        candidate_bot = None
        try:
            async with get_session_factory()() as session:
                actor = await _require_platform_admin_user(session, claims.telegram_user_id)
                tenant_bot = await _get_latest_tenant_bot_by_public_id(session, tenant_public_id, for_update=True)
                if tenant_bot is None:
                    raise HTTPException(status_code=404, detail="克隆 Bot 不存在")
                if tenant_bot.status != "active":
                    raise HTTPException(status_code=400, detail="只有 active 状态的 Bot 可以重置 Webhook")
                old_webhook_secret = tenant_bot.webhook_secret
                new_webhook_secret = generate_webhook_secret()
                token = TokenCrypto(settings).decrypt_token(tenant_bot.encrypted_token)
                candidate_bot = create_bot(token)
                webhook_url = f"{settings.public_base_url}{settings.webhook_base_path}/{new_webhook_secret}"
                await candidate_bot.set_webhook(
                    webhook_url,
                    allowed_updates=ADMIN_WEB_TENANT_WEBHOOK_ALLOWED_UPDATES,
                    drop_pending_updates=True,
                )
                tenant_bot.webhook_secret = new_webhook_secret
                tenant_bot.last_error = None
                session.add(
                    AuditLog(
                        tenant_id=tenant_bot.tenant_id,
                        actor_user_id=actor.id,
                        action="admin_web.platform_bot_webhook_reset",
                        target_type="tenant_bot",
                        target_id=str(tenant_public_id),
                        metadata_json={
                            "bot_username": tenant_bot.bot_username,
                            "reason": _safe_admin_web_reason(payload.reason),
                            "telegram_webhook_called": True,
                            "allowed_updates": ADMIN_WEB_TENANT_WEBHOOK_ALLOWED_UPDATES,
                        },
                    )
                )
                await session.flush()
                bot_username = tenant_bot.bot_username
                status = tenant_bot.status
                webhook_status = _platform_webhook_status(tenant_bot)
                await session.commit()
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Telegram Webhook 重置失败") from exc
        finally:
            if candidate_bot is not None:
                await candidate_bot.session.close()
        await _clear_tenant_webhook_cache(request, (old_webhook_secret, new_webhook_secret))
        return AdminWebPlatformBotWebhookResetResponse(
            tenant_public_id=tenant_public_id,
            bot_username=bot_username,
            status=status,
            webhook_status=webhook_status,
            reason=_safe_admin_web_reason(payload.reason),
            telegram_webhook_called=True,
        )

    @router.post(
        "/platform/finance/withdrawals/{withdrawal_id}/complete",
        response_model=AdminWebPlatformWithdrawalItemResponse,
    )
    async def platform_complete_withdrawal(
        withdrawal_id: int,
        payload: AdminWebPlatformWithdrawalCompleteRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebPlatformWithdrawalItemResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        try:
            async with get_session_factory()() as session:
                actor = await _require_platform_admin_user(session, claims.telegram_user_id)
                withdrawal = await LedgerService().complete_withdrawal(
                    session,
                    withdrawal_id,
                    payload.admin_note,
                    actor_user_id=actor.id,
                    payout_reference=payload.payout_reference,
                    payout_proof_url=payload.payout_proof_url,
                )
                summary = _withdrawal_summary_from_model(withdrawal)
                response_payload = await _platform_withdrawal_response(session, summary)
                await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_admin_web_platform_error_detail(exc))
        return response_payload

    @router.post(
        "/platform/finance/withdrawals/{withdrawal_id}/reject",
        response_model=AdminWebPlatformWithdrawalItemResponse,
    )
    async def platform_reject_withdrawal(
        withdrawal_id: int,
        payload: AdminWebPlatformWithdrawalRejectRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebPlatformWithdrawalItemResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        try:
            async with get_session_factory()() as session:
                actor = await _require_platform_admin_user(session, claims.telegram_user_id)
                withdrawal = await LedgerService().reject_withdrawal(
                    session,
                    withdrawal_id,
                    payload.admin_note,
                    actor_user_id=actor.id,
                )
                summary = _withdrawal_summary_from_model(withdrawal)
                response_payload = await _platform_withdrawal_response(session, summary)
                await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_admin_web_platform_error_detail(exc))
        return response_payload

    @router.post(
        "/platform/subscription/plans",
        response_model=AdminWebPlatformSubscriptionPlanItemResponse,
    )
    async def platform_create_subscription_plan(
        payload: AdminWebPlatformSubscriptionPlanCreateRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebPlatformSubscriptionPlanItemResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        try:
            async with get_session_factory()() as session:
                await _require_platform_admin_user(session, claims.telegram_user_id)
                plan = await SubscriptionService().create_platform_subscription_plan(
                    session,
                    code=payload.code,
                    name=payload.name,
                    monthly_price=payload.monthly_price,
                    currency=payload.currency,
                    trial_days=payload.trial_days,
                    grace_days=payload.grace_days,
                    enabled=payload.enabled,
                    reason=payload.reason,
                )
                await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_admin_web_platform_error_detail(exc))
        return _platform_subscription_plan_response(plan)

    @router.patch(
        "/platform/subscription/plans/{plan_code}",
        response_model=AdminWebPlatformSubscriptionPlanItemResponse,
    )
    async def platform_update_subscription_plan(
        plan_code: str,
        payload: AdminWebPlatformSubscriptionPlanUpdateRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebPlatformSubscriptionPlanItemResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        try:
            async with get_session_factory()() as session:
                await _require_platform_admin_user(session, claims.telegram_user_id)
                plan = await SubscriptionService().update_platform_subscription_plan(
                    session,
                    code=plan_code,
                    name=payload.name,
                    monthly_price=payload.monthly_price,
                    currency=payload.currency,
                    trial_days=payload.trial_days,
                    grace_days=payload.grace_days,
                    reason=payload.reason,
                )
                if plan is not None:
                    await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_admin_web_platform_error_detail(exc))
        if plan is None:
            raise HTTPException(status_code=404, detail="订阅计划不存在")
        return _platform_subscription_plan_response(plan)

    @router.patch(
        "/platform/subscription/plans/{plan_code}/status",
        response_model=AdminWebPlatformSubscriptionPlanItemResponse,
    )
    async def platform_update_subscription_plan_status(
        plan_code: str,
        payload: AdminWebPlatformSubscriptionPlanStatusUpdateRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebPlatformSubscriptionPlanItemResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        try:
            async with get_session_factory()() as session:
                await _require_platform_admin_user(session, claims.telegram_user_id)
                plan = await SubscriptionService().set_platform_subscription_plan_enabled(
                    session,
                    code=plan_code,
                    enabled=payload.enabled,
                    reason=payload.reason,
                )
                if plan is not None:
                    await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_admin_web_platform_error_detail(exc))
        if plan is None:
            raise HTTPException(status_code=404, detail="订阅计划不存在")
        return _platform_subscription_plan_response(plan)

    @router.patch(
        "/platform/supply/supplier-offers/{supplier_offer_id}/status",
        response_model=AdminWebPlatformSupplierOfferItemResponse,
    )
    async def platform_update_supplier_offer_status(
        supplier_offer_id: int,
        payload: AdminWebPlatformSupplierOfferStatusUpdateRequest,
        request: Request,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebPlatformSupplierOfferItemResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        try:
            async with get_session_factory()() as session:
                await _require_platform_admin_user(session, claims.telegram_user_id)
                offer = await SupplyService().set_platform_supplier_offer_status(
                    session,
                    supplier_offer_id=supplier_offer_id,
                    status=payload.status,
                    reason=payload.reason,
                )
                await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_admin_web_platform_error_detail(exc))
        return _platform_supplier_offer_response(offer)

    @router.post("/workspaces/select", response_model=AdminWebSessionResponse)
    async def select_workspace(
        payload: AdminWebWorkspaceSelectRequest,
        request: Request,
        response: Response,
        session_cookie: Optional[str] = Cookie(default=None, alias=ADMIN_WEB_SESSION_COOKIE_NAME),
    ) -> AdminWebSessionResponse:
        _require_admin_web_origin(request, settings)
        claims = _decode_session_cookie(settings, session_cookie)
        service = AdminWebService()
        async with get_session_factory()() as session:
            try:
                await service.ensure_workspace_access(
                    session,
                    telegram_user_id=claims.telegram_user_id,
                    workspace_id=payload.workspace_id,
                )
                summary = await service.session_summary(
                    session,
                    telegram_user_id=claims.telegram_user_id,
                    current_workspace_id=payload.workspace_id,
                )
            except AdminWebSessionError as exc:
                raise HTTPException(status_code=403, detail=str(exc))
        refreshed_claims = AdminWebSessionCodec(settings).refresh_workspace(claims, summary.current_workspace_id)
        _set_session_cookie(response, settings, AdminWebSessionCodec(settings).encode(refreshed_claims))
        return _session_response(summary)

    @router.post("/logout")
    async def logout(request: Request, response: Response) -> dict[str, bool]:
        _require_admin_web_origin(request, settings)
        response.delete_cookie(key=ADMIN_WEB_SESSION_COOKIE_NAME, path="/", samesite="lax")
        return {"ok": True}

    return router


async def _resolve_entrypoint_bot_token(
    service: AdminWebService,
    session: object,
    settings: Settings,
    payload: AdminWebTelegramSessionRequest,
) -> str:
    if payload.entrypoint == "master":
        if settings.master_bot_token is None:
            raise HTTPException(status_code=503, detail="主 Bot 未配置，无法进入管理后台")
        return settings.master_bot_token.get_secret_value()
    if not payload.tenant_public_id:
        raise HTTPException(status_code=422, detail="缺少克隆 Bot 工作区")
    tenant_bot = await service.load_tenant_bot_token_for_public_id(session, payload.tenant_public_id)
    if tenant_bot is None:
        raise HTTPException(status_code=404, detail="克隆 Bot 工作区不可用")
    try:
        return TokenCrypto(settings).decrypt_token(tenant_bot.encrypted_token)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


def _decode_session_cookie(settings: Settings, session_cookie: Optional[str]):
    if not session_cookie:
        raise HTTPException(status_code=401, detail="缺少管理后台会话")
    try:
        return AdminWebSessionCodec(settings).decode(session_cookie)
    except AdminWebSessionError as exc:
            raise HTTPException(status_code=401, detail=str(exc))


def _require_current_tenant_workspace(current_workspace_id: Optional[str]) -> str:
    if not current_workspace_id or current_workspace_id == PLATFORM_WORKSPACE_ID:
        raise HTTPException(status_code=403, detail="请选择克隆 Bot 工作区")
    return current_workspace_id


def _normalize_page_limit(limit: int) -> int:
    return min(max(limit, 1), 100)


def _normalize_page_offset(offset: int) -> int:
    return min(max(offset, 0), 100000)


async def _require_platform_admin_user(session: object, telegram_user_id: int) -> PlatformUser:
    user = await AdminWebService().get_user_by_telegram_id(session, telegram_user_id)
    if user is None or user.is_banned or not user.is_platform_admin:
        raise HTTPException(status_code=403, detail="无权访问主 Bot 管理工作区")
    return user


async def _get_tenant_by_public_id(session: object, tenant_public_id: str) -> Optional[Tenant]:
    result = await session.execute(
        select(Tenant)
        .where(Tenant.public_id == tenant_public_id)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _get_latest_tenant_bot_by_public_id(
    session: object,
    tenant_public_id: str,
    *,
    for_update: bool = False,
) -> Optional[TenantBot]:
    query = (
        select(TenantBot)
        .join(Tenant, Tenant.id == TenantBot.tenant_id)
        .where(Tenant.public_id == tenant_public_id)
        .order_by(TenantBot.created_at.desc(), TenantBot.id.desc())
        .limit(1)
    )
    if for_update:
        query = query.with_for_update()
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def _list_platform_tenant_bots(
    session: object,
    *,
    limit: int,
    offset: int = 0,
    query: Optional[str] = None,
    tenant_status: Optional[str] = "all",
    bot_status: Optional[str] = "all",
    subscription_status: Optional[str] = "all",
) -> list[AdminWebPlatformTenantBotItemResponse]:
    statement = (
        select(Tenant, TenantBot, PlatformUser, TenantSubscription, SubscriptionPlan)
        .outerjoin(TenantBot, TenantBot.tenant_id == Tenant.id)
        .join(PlatformUser, PlatformUser.id == Tenant.owner_user_id)
        .outerjoin(TenantSubscription, TenantSubscription.tenant_id == Tenant.id)
        .outerjoin(SubscriptionPlan, SubscriptionPlan.id == TenantSubscription.plan_id)
    )
    normalized_query = _normalize_platform_tenant_search_query(query)
    if normalized_query:
        pattern = f"%{normalized_query}%"
        statement = statement.where(
            or_(
                Tenant.public_id.ilike(pattern),
                Tenant.store_name.ilike(pattern),
                TenantBot.bot_username.ilike(pattern),
                PlatformUser.username.ilike(pattern),
            )
        )
    if tenant_status and tenant_status != "all":
        statement = statement.where(Tenant.status == tenant_status)
    if bot_status and bot_status != "all":
        if bot_status == "missing":
            statement = statement.where(TenantBot.id.is_(None))
        else:
            statement = statement.where(TenantBot.status == bot_status)
    if subscription_status and subscription_status != "all":
        statement = statement.where(func.coalesce(TenantSubscription.status, Tenant.status) == subscription_status)
    result = await session.execute(
        statement
        .order_by(Tenant.created_at.desc(), TenantBot.created_at.desc(), Tenant.id.desc())
        .offset(offset)
        .limit(limit)
    )
    rows: list[AdminWebPlatformTenantBotItemResponse] = []
    for tenant, tenant_bot, owner, subscription, plan in result.all():
        rows.append(
            AdminWebPlatformTenantBotItemResponse(
                tenant_public_id=tenant.public_id,
                store_name=tenant.store_name,
                tenant_status=tenant.status,
                bot_username=tenant_bot.bot_username if tenant_bot is not None else None,
                bot_status=tenant_bot.status if tenant_bot is not None else None,
                webhook_status=_platform_webhook_status(tenant_bot),
                webhook_reset_available=tenant_bot is not None and tenant_bot.status == "active",
                owner_telegram_user_id=owner.telegram_user_id,
                owner_username=owner.username,
                subscription_status=subscription.status if subscription is not None else tenant.status,
                plan_code=plan.code if plan is not None else tenant.plan_code,
                plan_name=plan.name if plan is not None else None,
                current_period_ends_at=(
                    subscription.current_period_ends_at.isoformat()
                    if subscription is not None and subscription.current_period_ends_at is not None
                    else None
                ),
                trial_ends_at=tenant.trial_ends_at.isoformat() if tenant.trial_ends_at is not None else None,
                subscription_ends_at=(
                    tenant.subscription_ends_at.isoformat()
                    if tenant.subscription_ends_at is not None
                    else None
                ),
                last_health_checked_at=(
                    tenant_bot.last_health_checked_at.isoformat()
                    if tenant_bot is not None and tenant_bot.last_health_checked_at is not None
                    else None
                ),
                has_last_error=bool(tenant_bot is not None and tenant_bot.last_error),
                created_at=tenant.created_at.isoformat(),
            )
        )
    return rows


def _normalize_platform_tenant_search_query(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized[:128]


async def _platform_stats_response(session: object) -> AdminWebPlatformStatsResponse:
    return AdminWebPlatformStatsResponse(
        tenant_count=await _count_where(session, Tenant.id),
        active_tenant_count=await _count_where(session, Tenant.id, Tenant.status == "active"),
        suspended_tenant_count=await _count_where(session, Tenant.id, Tenant.status == "suspended"),
        trial_subscription_count=await _count_effective_subscription_status(session, "trial"),
        active_subscription_count=await _count_effective_subscription_status(session, "active"),
        grace_subscription_count=await _count_effective_subscription_status(session, "grace"),
        suspended_subscription_count=await _count_effective_subscription_status(session, "suspended"),
        retention_expired_subscription_count=await _count_effective_subscription_status(
            session,
            "retention_expired",
        ),
        active_bot_count=await _count_where(session, TenantBot.id, TenantBot.status == "active"),
        pending_withdrawal_count=await _count_where(
            session,
            WithdrawalRequest.id,
            WithdrawalRequest.status == "pending",
        ),
        banned_user_count=await _count_where(session, PlatformUser.id, PlatformUser.is_banned.is_(True)),
        disabled_supplier_offer_count=await _count_where(
            session,
            SupplierOffer.id,
            SupplierOffer.status == "disabled",
        ),
    )


async def _count_where(session: object, column: object, *conditions: object) -> int:
    query = select(func.count(column))
    for condition in conditions:
        query = query.where(condition)
    result = await session.execute(query)
    return int(result.scalar_one() or 0)


async def _count_effective_subscription_status(session: object, status: str) -> int:
    result = await session.execute(
        select(func.count(Tenant.id))
        .outerjoin(TenantSubscription, TenantSubscription.tenant_id == Tenant.id)
        .where(func.coalesce(TenantSubscription.status, Tenant.status) == status)
    )
    return int(result.scalar_one() or 0)


async def _list_platform_payment_provider_observations(
    session: object,
    settings: Settings,
    *,
    tenant_count: int,
) -> list[AdminWebPlatformPaymentProviderItemResponse]:
    summaries = list_payment_provider_summaries()
    provider_names = [summary.provider_name for summary in summaries]
    configured_counts = await _count_tenant_payment_provider_configs_by_provider(
        session,
        provider_names,
    )
    enabled_counts = await _count_tenant_payment_provider_configs_by_provider(
        session,
        provider_names,
        enabled=True,
    )
    rows: list[AdminWebPlatformPaymentProviderItemResponse] = []
    for summary in summaries:
        configured_tenant_count = configured_counts.get(summary.provider_name, 0)
        enabled_tenant_count = enabled_counts.get(summary.provider_name, 0)
        platform_configured = _is_platform_payment_provider_configured(settings, summary.provider_name)
        rows.append(
            _platform_payment_provider_response(
                summary,
                configured_tenant_count=configured_tenant_count,
                enabled_tenant_count=enabled_tenant_count,
                missing_config_tenant_count=max(tenant_count - configured_tenant_count, 0),
                platform_configured=platform_configured,
                platform_enabled=platform_configured,
            )
        )
    return rows


async def _count_tenant_payment_provider_configs_by_provider(
    session: object,
    provider_names: list[str],
    *,
    enabled: Optional[bool] = None,
) -> dict[str, int]:
    if not provider_names:
        return {}
    query = (
        select(
            PaymentProviderConfig.provider,
            func.count(func.distinct(PaymentProviderConfig.tenant_id)),
        )
        .where(
            PaymentProviderConfig.provider.in_(provider_names),
            PaymentProviderConfig.scope_type == "tenant",
            PaymentProviderConfig.tenant_id.is_not(None),
        )
        .group_by(PaymentProviderConfig.provider)
    )
    if enabled is not None:
        query = query.where(PaymentProviderConfig.enabled.is_(enabled))
    result = await session.execute(query)
    return {str(provider): int(count or 0) for provider, count in result.all()}


async def _count_tenant_payment_provider_configs(
    session: object,
    provider_name: str,
    *,
    enabled: Optional[bool] = None,
) -> int:
    query = select(func.count(func.distinct(PaymentProviderConfig.tenant_id))).where(
        PaymentProviderConfig.provider == provider_name,
        PaymentProviderConfig.scope_type == "tenant",
        PaymentProviderConfig.tenant_id.is_not(None),
    )
    if enabled is not None:
        query = query.where(PaymentProviderConfig.enabled.is_(enabled))
    result = await session.execute(query)
    return int(result.scalar_one() or 0)


def _is_platform_payment_provider_configured(settings: Settings, provider_name: str) -> bool:
    if provider_name != EPUSDT_PROVIDER:
        return False
    return bool(settings.epusdt_base_url and settings.epusdt_pid and settings.epusdt_secret_key)


def _platform_webhook_status(tenant_bot: Optional[TenantBot]) -> str:
    if tenant_bot is None:
        return "unbound"
    if tenant_bot.status != "active":
        return tenant_bot.status
    if tenant_bot.last_error:
        return "error"
    if tenant_bot.last_health_checked_at is not None:
        return "healthy"
    return "unknown"


def _require_admin_web_supply_dashboard_query_params(request: Request) -> None:
    allowed = {
        "limit",
        "market_query",
        "market_delivery_type",
        "market_access",
        "market_min_price",
        "market_max_price",
        "market_stock",
        "market_category",
    }
    if any(key not in allowed for key in request.query_params):
        raise HTTPException(status_code=400, detail="供货市场筛选参数无效")


def _admin_web_payment_provider(provider_name: str) -> str:
    provider = provider_name.strip().lower()
    if provider == "epusdt":
        provider = "epusdt_gmpay"
    if provider not in {"epusdt_gmpay", "epay_compatible"}:
        raise ValueError("Admin Web 暂只支持 EPUSDT 和易支付兼容配置")
    return provider


def _admin_web_payment_config_payload(
    provider_name: str,
    payload: AdminWebPaymentConfigRequest,
) -> dict[str, object]:
    provider = _admin_web_payment_provider(provider_name)
    if provider == "epusdt_gmpay":
        config = {
            "base_url": payload.base_url or payload.gateway_url,
            "pid": payload.pid or payload.merchant_id,
            "secret_key": payload.secret_key or payload.key,
            "token": payload.token,
            "network": payload.network,
        }
    else:
        config = {
            "gateway_url": payload.gateway_url,
            "merchant_id": payload.merchant_id,
            "key": payload.key,
            "payment_type": payload.payment_type,
            "device": payload.device,
            "return_url": payload.return_url,
            "subject": payload.subject,
        }
    filtered = {key: value for key, value in config.items() if value is not None}
    if not filtered:
        raise ValueError("支付配置参数无效")
    return filtered


def _set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        key=ADMIN_WEB_SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.public_base_url.startswith("https://"),
        samesite="lax",
        max_age=settings.admin_web_session_max_age_seconds,
        path="/",
    )


def _require_admin_web_origin(request: Request, settings: Settings) -> None:
    origin = (request.headers.get("origin") or "").strip().rstrip("/")
    if not origin:
        raise HTTPException(status_code=403, detail="缺少管理后台请求来源")
    allowed_origins = _admin_web_allowed_origins(settings)
    if origin not in allowed_origins:
        raise HTTPException(status_code=403, detail="管理后台请求来源不允许")


def _admin_web_allowed_origins(settings: Settings) -> set[str]:
    origins = set(settings.admin_web_allowed_origins)
    public_origin = _origin_from_url(settings.public_base_url)
    if public_origin:
        origins.add(public_origin)
    return origins


def _origin_from_url(value: str) -> Optional[str]:
    from urllib.parse import urlparse

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


async def _hit_binding_code_rate_limit(
    request: Request,
    settings: Settings,
    redis_client: object,
    redis_limiter: RedisFixedWindowRateLimiter,
    local_limiter: FixedWindowRateLimiter,
) -> None:
    client_ip = resolve_client_ip(
        request.client.host if request.client is not None else None,
        request.headers.get("x-forwarded-for"),
        settings.trusted_proxy_ips,
    )
    await hit_rate_limit(
        redis_client=redis_client,
        redis_limiter=redis_limiter,
        local_limiter=local_limiter,
        key=f"ip:{client_ip}",
    )


async def _platform_withdrawal_response(
    session: object,
    withdrawal: WithdrawalSummary,
) -> AdminWebPlatformWithdrawalItemResponse:
    tenant = await session.get(Tenant, withdrawal.tenant_id)
    return AdminWebPlatformWithdrawalItemResponse(
        withdrawal_id=withdrawal.withdrawal_id,
        tenant_public_id=tenant.public_id if tenant is not None else None,
        store_name=tenant.store_name if tenant is not None else None,
        amount=withdrawal.amount,
        currency=withdrawal.currency,
        network=withdrawal.network,
        address_masked=_mask_admin_web_finance_address(withdrawal.address),
        status=withdrawal.status,
        requested_at=withdrawal.requested_at.isoformat(),
        reviewed_at=withdrawal.reviewed_at.isoformat() if withdrawal.reviewed_at is not None else None,
        completed_at=withdrawal.completed_at.isoformat() if withdrawal.completed_at is not None else None,
    )


def _platform_subscription_plan_response(
    plan: PlatformSubscriptionPlanSummary,
) -> AdminWebPlatformSubscriptionPlanItemResponse:
    return AdminWebPlatformSubscriptionPlanItemResponse(
        code=plan.code,
        name=plan.name,
        monthly_price=plan.monthly_price,
        currency=plan.currency,
        trial_days=plan.trial_days,
        grace_days=plan.grace_days,
        enabled=plan.enabled,
        created_at=plan.created_at.isoformat() if plan.created_at is not None else None,
        updated_at=plan.updated_at.isoformat() if plan.updated_at is not None else None,
    )


def _platform_subscription_attention_response(
    item: PlatformSubscriptionAttentionItem,
) -> AdminWebPlatformSubscriptionAttentionItemResponse:
    return AdminWebPlatformSubscriptionAttentionItemResponse(
        tenant_public_id=item.tenant_public_id,
        store_name=item.store_name,
        owner_telegram_user_id=item.owner_telegram_user_id,
        owner_username=item.owner_username,
        tenant_status=item.tenant_status,
        subscription_status=item.subscription_status,
        plan_code=item.plan_code,
        plan_name=item.plan_name,
        attention_reason=item.attention_reason,
        trial_ends_at=item.trial_ends_at.isoformat() if item.trial_ends_at is not None else None,
        current_period_ends_at=(
            item.current_period_ends_at.isoformat()
            if item.current_period_ends_at is not None
            else None
        ),
        subscription_ends_at=(
            item.subscription_ends_at.isoformat()
            if item.subscription_ends_at is not None
            else None
        ),
        grace_ends_at=item.grace_ends_at.isoformat() if item.grace_ends_at is not None else None,
        suspended_at=item.suspended_at.isoformat() if item.suspended_at is not None else None,
        data_retention_until=(
            item.data_retention_until.isoformat()
            if item.data_retention_until is not None
            else None
        ),
    )


def _platform_tenant_subscription_adjustment_response(
    tenant_public_id: str,
    result: SubscriptionAdjustmentResult,
) -> AdminWebPlatformTenantSubscriptionAdjustmentResponse:
    return AdminWebPlatformTenantSubscriptionAdjustmentResponse(
        tenant_public_id=tenant_public_id,
        status=result.status,
        previous_period_ends_at=(
            result.previous_period_ends_at.isoformat()
            if result.previous_period_ends_at is not None
            else None
        ),
        new_period_ends_at=result.new_period_ends_at.isoformat(),
        action=result.action,
    )


def _platform_payment_provider_response(
    summary: PaymentProviderSummary,
    *,
    configured_tenant_count: int,
    enabled_tenant_count: int,
    missing_config_tenant_count: int,
    platform_configured: bool,
    platform_enabled: bool,
) -> AdminWebPlatformPaymentProviderItemResponse:
    return AdminWebPlatformPaymentProviderItemResponse(
        provider_name=summary.provider_name,
        display_name=summary.display_name,
        integration_kind=summary.integration_kind,
        contract_name=summary.contract_name,
        production_ready=summary.production_ready,
        staging_verified=summary.staging_verified,
        tenant_configurable=summary.tenant_configurable,
        platform_configurable=summary.platform_configurable,
        create_payment_available=summary.create_payment_available,
        callback_available=summary.callback_available,
        query_order_available=summary.query_order_available,
        reconcile_available=summary.reconcile_available,
        offline_only=summary.offline_only,
        supported_assets=list(summary.supported_assets),
        supported_networks=list(summary.supported_networks),
        configured_tenant_count=configured_tenant_count,
        enabled_tenant_count=enabled_tenant_count,
        missing_config_tenant_count=missing_config_tenant_count,
        platform_configured=platform_configured,
        platform_enabled=platform_enabled,
    )


def _platform_risk_banned_user_response(
    summary: PlatformRiskBannedUserSummary | PlatformRiskBanStatusSummary,
) -> AdminWebPlatformRiskBannedUserItemResponse:
    return AdminWebPlatformRiskBannedUserItemResponse(
        telegram_user_id=summary.telegram_user_id,
        username=summary.username,
        is_banned=summary.is_banned,
        ban_source=summary.ban_source,
        latest_action=summary.latest_action,
        latest_action_at=summary.latest_action_at.isoformat() if summary.latest_action_at else None,
        reason=summary.reason,
        trigger_rule=summary.trigger_rule,
        blocked_count=summary.blocked_count,
        threshold=summary.threshold,
        window_seconds=summary.window_seconds,
        created_at=summary.created_at.isoformat() if summary.created_at else None,
        updated_at=summary.updated_at.isoformat() if summary.updated_at else None,
    )


def _platform_risk_audit_log_response(
    summary: PlatformRiskAuditLogSummary,
) -> AdminWebPlatformRiskAuditLogItemResponse:
    return AdminWebPlatformRiskAuditLogItemResponse(
        created_at=summary.created_at.isoformat(),
        action=summary.action,
        target_type=summary.target_type,
        actor_telegram_user_id=summary.actor_telegram_user_id,
        actor_username=summary.actor_username,
        target_telegram_user_id=summary.target_telegram_user_id,
        previous_status=summary.previous_status,
        new_status=summary.new_status,
        reason=summary.reason,
        risk_rule=summary.risk_rule,
        blocked_count=summary.blocked_count,
        threshold=summary.threshold,
        window_seconds=summary.window_seconds,
    )


def _platform_supplier_offer_response(
    offer: PlatformSupplierOfferSummary,
) -> AdminWebPlatformSupplierOfferItemResponse:
    return AdminWebPlatformSupplierOfferItemResponse(
        supplier_offer_id=offer.supplier_offer_id,
        supplier_store_name=offer.supplier_store_name,
        product_name=offer.product_name,
        delivery_type=offer.delivery_type,
        suggested_price=offer.suggested_price,
        min_sale_price=offer.min_sale_price,
        supplier_cost=offer.supplier_cost,
        currency=offer.currency,
        available_count=offer.available_count,
        requires_approval=offer.requires_approval,
        status=offer.status,
        created_at=offer.created_at.isoformat(),
        updated_at=offer.updated_at.isoformat(),
    )


def _withdrawal_summary_from_model(withdrawal: object) -> WithdrawalSummary:
    return WithdrawalSummary(
        withdrawal_id=getattr(withdrawal, "id"),
        tenant_id=getattr(withdrawal, "tenant_id"),
        amount=getattr(withdrawal, "amount"),
        currency=getattr(withdrawal, "currency"),
        network=getattr(withdrawal, "network"),
        address=getattr(withdrawal, "address"),
        status=getattr(withdrawal, "status"),
        requested_at=getattr(withdrawal, "requested_at"),
        payout_reference=getattr(withdrawal, "payout_reference", None),
        payout_proof_url=getattr(withdrawal, "payout_proof_url", None),
        reviewed_at=getattr(withdrawal, "reviewed_at", None),
        completed_at=getattr(withdrawal, "completed_at", None),
    )


def _mask_admin_web_finance_address(value: str) -> str:
    if len(value) <= 12:
        return "***"
    return f"{value[:6]}***{value[-6:]}"


async def _clear_tenant_webhook_cache(request: Request, webhook_secrets: tuple[str, ...]) -> None:
    if not webhook_secrets:
        return
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        return
    keys = [f"tenant_webhook:{secret}" for secret in webhook_secrets if secret]
    if not keys:
        return
    try:
        await redis_client.delete(*keys)
    except Exception:
        return


def _safe_admin_web_platform_error_detail(exc: ValueError) -> str:
    message = str(exc)
    lowered = message.lower()
    if "http://" in lowered or "https://" in lowered:
        return "平台管理参数无效"
    if any(marker in lowered for marker in _admin_web_sensitive_markers()):
        return "平台管理参数无效"
    allowed_markers = (
        "封禁",
        "用户",
        "租户",
        "提现",
        "余额",
        "备注",
        "打款",
        "凭证",
        "订阅计划",
        "订阅月费",
        "试用天数",
        "宽限天数",
        "供货商品",
        "状态",
        "数量",
        "limit",
    )
    if any(marker in message for marker in allowed_markers):
        return message
    return "平台管理参数无效"


def _safe_admin_web_validation_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    safe_errors: list[dict[str, Any]] = []
    for error in errors:
        safe_error: dict[str, Any] = {
            key: value
            for key, value in error.items()
            if key not in {"input", "ctx", "url"}
        }
        if "loc" in safe_error:
            safe_error["loc"] = list(safe_error["loc"])
        safe_errors.append(safe_error)
    return safe_errors


def _safe_admin_web_reason(reason: Optional[str]) -> Optional[str]:
    if reason is None:
        return None
    value = reason.strip()
    if not value:
        return None
    lowered = value.lower()
    if "http://" in lowered or "https://" in lowered:
        return "已隐藏敏感原因"
    if any(marker in lowered for marker in _admin_web_sensitive_markers()):
        return "已隐藏敏感原因"
    return value[:500]


def _admin_web_sensitive_markers() -> tuple[str, ...]:
    return (
        "token",
        "secret",
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "password",
        "private_key",
        "payload",
        "card_secret",
        "卡密",
    )


def _session_response(summary: AdminWebSessionSummary) -> AdminWebSessionResponse:
    return AdminWebSessionResponse(
        user=AdminWebUserResponse(
            telegram_user_id=summary.user.telegram_user_id,
            username=summary.user.username,
            first_name=summary.user.first_name,
            is_platform_admin=summary.user.is_platform_admin,
        ),
        workspaces=[_workspace_response(workspace) for workspace in summary.workspaces],
        current_workspace_id=summary.current_workspace_id,
    )


def _workspace_response(workspace: AdminWebWorkspaceSummary) -> AdminWebWorkspaceResponse:
    return AdminWebWorkspaceResponse(
        workspace_id=workspace.workspace_id,
        kind=workspace.kind,
        role=workspace.role,
        title=workspace.title,
        tenant_public_id=workspace.tenant_public_id,
        bot_username=workspace.bot_username,
        tenant_status=workspace.tenant_status,
        bot_status=workspace.bot_status,
        supplier_enabled=workspace.supplier_enabled,
        reseller_enabled=workspace.reseller_enabled,
    )


def _tenant_overview_response(overview: AdminWebTenantOverview) -> AdminWebTenantOverviewResponse:
    return AdminWebTenantOverviewResponse(
        workspace=_workspace_response(overview.workspace),
        tenant_public_id=overview.tenant_public_id,
        store_name=overview.store_name,
        tenant_status=overview.tenant_status,
        bot_username=overview.bot_username,
        bot_status=overview.bot_status,
        products=AdminWebTenantProductsOverviewResponse(
            total_count=overview.product_count,
            published_count=overview.published_product_count,
            available_inventory_count=overview.available_inventory_count,
        ),
        orders=AdminWebTenantOrdersOverviewResponse(
            total_count=overview.order_count,
            pending_count=overview.pending_order_count,
            paid_count=overview.paid_order_count,
            delivered_count=overview.delivered_order_count,
        ),
        payments=AdminWebTenantPaymentsOverviewResponse(
            total_count=overview.payment_provider_count,
            enabled_count=overview.enabled_payment_provider_count,
            providers=[
                AdminWebTenantPaymentProviderOverviewResponse(
                    provider_name=provider.provider_name,
                    display_name=provider.display_name,
                    enabled=provider.enabled,
                    scope_type=provider.scope_type,
                    key_configured=provider.key_configured,
                    create_payment_available=provider.create_payment_available,
                )
                for provider in overview.payment_providers
            ],
        ),
        subscription=AdminWebTenantSubscriptionOverviewResponse(
            status=overview.subscription_status,
            plan_code=overview.subscription_plan_code,
            current_period_ends_at=(
                overview.subscription_period_ends_at.isoformat()
                if overview.subscription_period_ends_at is not None
                else None
            ),
        ),
        finance=AdminWebTenantFinanceOverviewResponse(
            currency=overview.ledger_currency,
            pending_balance=overview.ledger_pending_balance,
            available_balance=overview.ledger_available_balance,
            frozen_balance=overview.ledger_frozen_balance,
            pending_withdrawal_count=overview.pending_withdrawal_count,
        ),
        supply=AdminWebTenantSupplyOverviewResponse(
            supplier_enabled=overview.supplier_enabled,
            reseller_enabled=overview.reseller_enabled,
            supplier_offer_count=overview.supplier_offer_count,
            reseller_product_count=overview.reseller_product_count,
        ),
    )


def _tenant_store_settings_response(
    store_settings: AdminWebTenantStoreSettings,
) -> AdminWebTenantStoreSettingsResponse:
    return AdminWebTenantStoreSettingsResponse(
        store_name=store_settings.store_name,
        welcome_text=store_settings.welcome_text,
        support_text=store_settings.support_text,
        order_timeout_minutes=store_settings.order_timeout_minutes,
        self_sale_enabled=store_settings.self_sale_enabled,
        supplier_enabled=store_settings.supplier_enabled,
        reseller_enabled=store_settings.reseller_enabled,
    )


def _tenant_products_response(products: AdminWebTenantProductsPage) -> AdminWebTenantProductsResponse:
    return AdminWebTenantProductsResponse(
        total_count=products.total_count,
        limit=products.limit,
        offset=products.offset,
        items=[_tenant_product_response(item) for item in products.items],
    )


def _tenant_product_response(item: AdminWebTenantProductItem) -> AdminWebTenantProductItemResponse:
    return AdminWebTenantProductItemResponse(
        product_id=item.product_id,
        name=item.name,
        category=item.category,
        sort_order=item.sort_order,
        status=item.status,
        delivery_type=item.delivery_type,
        price=item.price,
        currency=item.currency,
        available_count=item.available_count,
    )


def _tenant_product_batch_status_response(
    result: AdminWebTenantProductBatchStatusUpdate,
) -> AdminWebTenantProductBatchStatusResponse:
    return AdminWebTenantProductBatchStatusResponse(
        status=result.status,
        updated_count=result.updated_count,
        products=[_tenant_product_response(item) for item in result.products],
    )


def _inventory_import_response(result: AdminWebInventoryImportResult) -> AdminWebProductInventoryImportResponse:
    return AdminWebProductInventoryImportResponse(
        product_id=result.product_id,
        added_count=result.added_count,
        existing_count=result.existing_count,
        input_duplicate_count=result.input_duplicate_count,
        available_count=result.available_count,
    )


def _product_delivery_file_response(result: AdminWebProductDeliveryFileResult) -> AdminWebProductDeliveryFileResponse:
    return AdminWebProductDeliveryFileResponse(
        product_id=result.product_id,
        filename=result.filename,
        size_bytes=result.size_bytes,
        content_type=result.content_type,
        risk_level=result.risk_level,
        scan_message=result.scan_message,
        bound=result.bound,
    )


def _tenant_orders_response(orders: AdminWebTenantOrdersPage) -> AdminWebTenantOrdersResponse:
    return AdminWebTenantOrdersResponse(
        total_count=orders.total_count,
        limit=orders.limit,
        offset=orders.offset,
        items=[
            AdminWebTenantOrderItemResponse(
                out_trade_no=item.out_trade_no,
                source_type=item.source_type,
                amount=item.amount,
                currency=item.currency,
                status=item.status,
                payment_mode=item.payment_mode,
                buyer_telegram_user_id=item.buyer_telegram_user_id,
                created_at=item.created_at.isoformat(),
                expires_at=item.expires_at.isoformat(),
                paid_at=item.paid_at.isoformat() if item.paid_at is not None else None,
                delivered_at=item.delivered_at.isoformat() if item.delivered_at is not None else None,
            )
            for item in orders.items
        ],
    )


def _tenant_order_diagnostics_response(
    diagnostics: AdminWebTenantOrderDiagnostics,
) -> AdminWebTenantOrderDiagnosticsResponse:
    return AdminWebTenantOrderDiagnosticsResponse(
        out_trade_no=diagnostics.out_trade_no,
        source_type=diagnostics.source_type,
        status=diagnostics.status,
        payment_mode=diagnostics.payment_mode,
        payment_provider=diagnostics.payment_provider,
        amount=diagnostics.amount,
        currency=diagnostics.currency,
        created_at=diagnostics.created_at.isoformat(),
        expires_at=diagnostics.expires_at.isoformat(),
        paid_at=diagnostics.paid_at.isoformat() if diagnostics.paid_at is not None else None,
        delivered_at=diagnostics.delivered_at.isoformat() if diagnostics.delivered_at is not None else None,
        payment_count=diagnostics.payment_count,
        callback_count=diagnostics.callback_count,
        callback_status_counts=diagnostics.callback_status_counts,
        payments=[
            AdminWebOrderPaymentDiagnosticItemResponse(
                provider=payment.provider,
                status=payment.status,
                amount=payment.amount,
                currency=payment.currency,
                has_payment_url=payment.has_payment_url,
                created_at=payment.created_at.isoformat(),
                paid_at=payment.paid_at.isoformat() if payment.paid_at is not None else None,
            )
            for payment in diagnostics.payments
        ],
        callbacks=[
            AdminWebOrderPaymentCallbackDiagnosticItemResponse(
                provider=callback.provider,
                process_status=callback.process_status,
                failure_reason=callback.failure_reason,
                created_at=callback.created_at.isoformat(),
                processed_at=callback.processed_at.isoformat() if callback.processed_at is not None else None,
            )
            for callback in diagnostics.callbacks
        ],
        delivery=(
            AdminWebOrderDeliveryDiagnosticItemResponse(
                delivery_type=diagnostics.delivery.delivery_type,
                status=diagnostics.delivery.status,
                failure_reason=diagnostics.delivery.failure_reason,
                has_inventory_item=diagnostics.delivery.has_inventory_item,
                has_uploaded_file=diagnostics.delivery.has_uploaded_file,
                has_telegram_chat=diagnostics.delivery.has_telegram_chat,
                created_at=diagnostics.delivery.created_at.isoformat(),
                updated_at=diagnostics.delivery.updated_at.isoformat(),
                sent_at=diagnostics.delivery.sent_at.isoformat() if diagnostics.delivery.sent_at is not None else None,
            )
            if diagnostics.delivery is not None
            else None
        ),
        external_fulfillment=AdminWebOrderExternalFulfillmentDiagnosticItemResponse(
            expected=diagnostics.external_fulfillment.expected,
            attempt_count=diagnostics.external_fulfillment.attempt_count,
            latest_attempt_status=diagnostics.external_fulfillment.latest_attempt_status,
            latest_attempt_trigger=diagnostics.external_fulfillment.latest_attempt_trigger,
            latest_attempt_at=(
                diagnostics.external_fulfillment.latest_attempt_at.isoformat()
                if diagnostics.external_fulfillment.latest_attempt_at is not None
                else None
            ),
            latest_failure_stage=diagnostics.external_fulfillment.latest_failure_stage,
            latest_failure_category=diagnostics.external_fulfillment.latest_failure_category,
            latest_failure_retryable=diagnostics.external_fulfillment.latest_failure_retryable,
            latest_upstream_status_code=diagnostics.external_fulfillment.latest_upstream_status_code,
            latest_item_count=diagnostics.external_fulfillment.latest_item_count,
            latest_delivery_record_linked=diagnostics.external_fulfillment.latest_delivery_record_linked,
        ),
        trc20_direct=AdminWebOrderTrc20DirectDiagnosticItemResponse(
            expected=diagnostics.trc20_direct.expected,
            transfer_count=diagnostics.trc20_direct.transfer_count,
            latest_match_status=diagnostics.trc20_direct.latest_match_status,
            latest_confirmations=diagnostics.trc20_direct.latest_confirmations,
            latest_matched_at=(
                diagnostics.trc20_direct.latest_matched_at.isoformat()
                if diagnostics.trc20_direct.latest_matched_at is not None
                else None
            ),
            latest_amount=diagnostics.trc20_direct.latest_amount,
        ),
    )


def _tenant_order_observability_response(
    observability: AdminWebTenantOrderObservability,
) -> AdminWebTenantOrderObservabilityResponse:
    return AdminWebTenantOrderObservabilityResponse(
        limit=observability.limit,
        callback_failures=[
            AdminWebPaymentCallbackFailureItemResponse(
                created_at=item.created_at.isoformat(),
                processed_at=item.processed_at.isoformat() if item.processed_at is not None else None,
                out_trade_no=item.out_trade_no,
                order_status=item.order_status,
                provider=item.provider,
                process_status=item.process_status,
                failure_reason=item.failure_reason,
            )
            for item in observability.callback_failures
        ],
        callback_rejections=[
            AdminWebPaymentCallbackRejectionItemResponse(
                created_at=item.created_at.isoformat(),
                provider=item.provider,
                reason_category=item.reason_category,
                failure_reason=item.failure_reason,
                http_status=item.http_status,
                out_trade_no=item.out_trade_no,
                order_status=item.order_status,
                payload_field_count=item.payload_field_count,
            )
            for item in observability.callback_rejections
        ],
        external_fulfillment_attempts=[
            AdminWebExternalFulfillmentAttemptItemResponse(
                created_at=item.created_at.isoformat(),
                started_at=item.started_at.isoformat(),
                finished_at=item.finished_at.isoformat(),
                out_trade_no=item.out_trade_no,
                provider_name=item.provider_name,
                source_key=item.source_key,
                attempt_source=item.attempt_source,
                status=item.status,
                imported=item.imported,
                item_count=item.item_count,
                failure_reason=item.failure_reason,
                failure_stage=item.failure_stage,
                failure_category=item.failure_category,
                failure_retryable=item.failure_retryable,
                upstream_status_code=item.upstream_status_code,
            )
            for item in observability.external_fulfillment_attempts
        ],
    )


def _tenant_subscription_dashboard_response(
    dashboard: AdminWebTenantSubscriptionDashboard,
) -> AdminWebTenantSubscriptionDashboardResponse:
    return AdminWebTenantSubscriptionDashboardResponse(
        status=dashboard.status,
        plan_code=dashboard.plan_code,
        plan_name=dashboard.plan_name,
        monthly_price=dashboard.monthly_price,
        currency=dashboard.currency,
        trial_days=dashboard.trial_days,
        grace_days=dashboard.grace_days,
        trial_ends_at=dashboard.trial_ends_at.isoformat() if dashboard.trial_ends_at else None,
        current_period_ends_at=(
            dashboard.current_period_ends_at.isoformat() if dashboard.current_period_ends_at else None
        ),
        subscription_ends_at=(
            dashboard.subscription_ends_at.isoformat() if dashboard.subscription_ends_at else None
        ),
        grace_ends_at=dashboard.grace_ends_at.isoformat() if dashboard.grace_ends_at else None,
        suspended_at=dashboard.suspended_at.isoformat() if dashboard.suspended_at else None,
        data_retention_until=(
            dashboard.data_retention_until.isoformat() if dashboard.data_retention_until else None
        ),
        invoices=[
            AdminWebTenantSubscriptionInvoiceItemResponse(
                out_trade_no=invoice.out_trade_no,
                amount=invoice.amount,
                currency=invoice.currency,
                status=invoice.status,
                paid_at=invoice.paid_at.isoformat() if invoice.paid_at else None,
                created_at=invoice.created_at.isoformat(),
            )
            for invoice in dashboard.invoices
        ],
    )


def _subscription_renewal_order_response(
    renewal_order: AdminWebSubscriptionRenewalOrder,
) -> AdminWebSubscriptionRenewalOrderResponse:
    return AdminWebSubscriptionRenewalOrderResponse(
        out_trade_no=renewal_order.out_trade_no,
        amount=renewal_order.amount,
        currency=renewal_order.currency,
        months=renewal_order.months,
        expires_at=renewal_order.expires_at.isoformat(),
        payment_available=renewal_order.payment_available,
        payment_provider=renewal_order.payment_provider,
        payment_url=renewal_order.payment_url,
        payment_failure_reason=renewal_order.payment_failure_reason,
    )


def _tenant_finance_dashboard_response(
    dashboard: AdminWebTenantFinanceDashboard,
) -> AdminWebTenantFinanceDashboardResponse:
    return AdminWebTenantFinanceDashboardResponse(
        balance=AdminWebTenantFinanceBalanceResponse(
            account_type=dashboard.balance.account_type,
            currency=dashboard.balance.currency,
            pending_balance=dashboard.balance.pending_balance,
            available_balance=dashboard.balance.available_balance,
            frozen_balance=dashboard.balance.frozen_balance,
        ),
        audit=AdminWebTenantFinanceAuditResponse(
            account_type=dashboard.audit.account_type,
            currency=dashboard.audit.currency,
            stored_pending_balance=dashboard.audit.stored_pending_balance,
            stored_available_balance=dashboard.audit.stored_available_balance,
            stored_frozen_balance=dashboard.audit.stored_frozen_balance,
            computed_pending_balance=dashboard.audit.computed_pending_balance,
            computed_available_balance=dashboard.audit.computed_available_balance,
            computed_frozen_balance=dashboard.audit.computed_frozen_balance,
            pending_difference=dashboard.audit.pending_difference,
            available_difference=dashboard.audit.available_difference,
            frozen_difference=dashboard.audit.frozen_difference,
            is_balanced=dashboard.audit.is_balanced,
        ),
        withdrawals=[
            AdminWebTenantWithdrawalItemResponse(
                amount=withdrawal.amount,
                currency=withdrawal.currency,
                network=withdrawal.network,
                address_masked=withdrawal.address_masked,
                status=withdrawal.status,
                requested_at=withdrawal.requested_at.isoformat(),
                reviewed_at=withdrawal.reviewed_at.isoformat() if withdrawal.reviewed_at else None,
                completed_at=withdrawal.completed_at.isoformat() if withdrawal.completed_at else None,
            )
            for withdrawal in dashboard.withdrawals
        ],
    )


def _tenant_withdrawal_response(withdrawal: AdminWebTenantWithdrawalItem) -> AdminWebTenantWithdrawalItemResponse:
    return AdminWebTenantWithdrawalItemResponse(
        amount=withdrawal.amount,
        currency=withdrawal.currency,
        network=withdrawal.network,
        address_masked=withdrawal.address_masked,
        status=withdrawal.status,
        requested_at=withdrawal.requested_at.isoformat(),
        reviewed_at=withdrawal.reviewed_at.isoformat() if withdrawal.reviewed_at else None,
        completed_at=withdrawal.completed_at.isoformat() if withdrawal.completed_at else None,
    )


def _tenant_audit_logs_response(page: AdminWebTenantAuditLogsPage) -> AdminWebTenantAuditLogsResponse:
    return AdminWebTenantAuditLogsResponse(
        limit=page.limit,
        items=[_tenant_audit_log_response(item) for item in page.items],
    )


def _tenant_audit_log_response(item: AdminWebTenantAuditLogItem) -> AdminWebTenantAuditLogItemResponse:
    return AdminWebTenantAuditLogItemResponse(
        created_at=item.created_at.isoformat(),
        actor_telegram_user_id=item.actor_telegram_user_id,
        actor_username=item.actor_username,
        action=item.action,
        target_type=item.target_type,
        metadata=item.metadata,
    )


def _tenant_report_export_jobs_response(
    page: AdminWebTenantReportExportJobsPage,
) -> AdminWebTenantReportExportJobsResponse:
    return AdminWebTenantReportExportJobsResponse(
        status=page.status or "all",
        report_type=page.report_type or "all",
        limit=page.limit,
        export_jobs=[_tenant_report_export_job_response(job) for job in page.export_jobs],
    )


def _tenant_report_export_job_response(
    job: AdminWebTenantReportExportJobItem,
) -> AdminWebTenantReportExportJobItemResponse:
    return AdminWebTenantReportExportJobItemResponse(
        report_type=job.report_type,
        scope_type=job.scope_type,
        status=job.status,
        row_count=job.row_count,
        download_available=job.download_available,
        download_handle=job.download_handle,
        failure_reason=job.failure_reason,
        expires_at=job.expires_at.isoformat() if job.expires_at else None,
        created_at=job.created_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at else None,
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
    )


def _tenant_api_keys_response(page: AdminWebTenantApiKeysPage) -> AdminWebTenantApiKeysResponse:
    return AdminWebTenantApiKeysResponse(
        limit=page.limit,
        keys=[_tenant_api_key_response(api_key) for api_key in page.keys],
    )


def _tenant_api_key_response(api_key: AdminWebTenantApiKeyItem) -> AdminWebTenantApiKeyItemResponse:
    return AdminWebTenantApiKeyItemResponse(
        credential_handle=api_key.credential_handle,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        status=api_key.status,
        scopes=list(api_key.scopes),
        ip_allowlist=list(api_key.ip_allowlist),
        created_at=api_key.created_at.isoformat() if api_key.created_at else None,
        last_used_at=api_key.last_used_at.isoformat() if api_key.last_used_at else None,
    )


def _created_tenant_api_key_response(
    api_key: AdminWebCreatedTenantApiKeyItem,
) -> AdminWebCreatedTenantApiKeyResponse:
    item = _tenant_api_key_response(api_key)
    return AdminWebCreatedTenantApiKeyResponse(
        credential_handle=item.credential_handle,
        name=item.name,
        key_prefix=item.key_prefix,
        status=item.status,
        scopes=item.scopes,
        ip_allowlist=item.ip_allowlist,
        created_at=item.created_at,
        last_used_at=item.last_used_at,
        plain_key=api_key.plain_key,
    )


def _tenant_api_key_revoke_response(
    result: AdminWebTenantApiKeyRevokeResult,
) -> AdminWebTenantApiKeyRevokeResponse:
    return AdminWebTenantApiKeyRevokeResponse(
        credential_handle=result.credential_handle,
        revoked=result.revoked,
    )


def _tenant_risk_dashboard_response(
    dashboard: AdminWebTenantRiskDashboard,
) -> AdminWebTenantRiskDashboardResponse:
    return AdminWebTenantRiskDashboardResponse(
        status=dashboard.status or "all",
        limit=dashboard.limit,
        disputes=[_tenant_risk_dispute_response(item) for item in dashboard.disputes],
        after_sales=[_tenant_risk_after_sale_response(item) for item in dashboard.after_sales],
    )


def _tenant_risk_dispute_response(
    item: AdminWebTenantRiskDisputeItem,
) -> AdminWebTenantRiskDisputeItemResponse:
    return AdminWebTenantRiskDisputeItemResponse(
        out_trade_no=item.out_trade_no,
        buyer_telegram_user_id=item.buyer_telegram_user_id,
        source_type=item.source_type,
        order_status=item.order_status,
        amount=item.amount,
        currency=item.currency,
        status=item.status,
        reason=item.reason,
        resolution=item.resolution,
        created_at=item.created_at.isoformat(),
        updated_at=item.updated_at.isoformat(),
    )


def _tenant_risk_after_sale_response(
    item: AdminWebTenantRiskAfterSaleItem,
) -> AdminWebTenantRiskAfterSaleItemResponse:
    return AdminWebTenantRiskAfterSaleItemResponse(
        out_trade_no=item.out_trade_no,
        buyer_telegram_user_id=item.buyer_telegram_user_id,
        source_type=item.source_type,
        order_status=item.order_status,
        amount=item.amount,
        currency=item.currency,
        case_type=item.case_type,
        status=item.status,
        requested_amount=item.requested_amount,
        refunded_amount=item.refunded_amount,
        reason=item.reason,
        resolution=item.resolution,
        created_at=item.created_at.isoformat(),
        updated_at=item.updated_at.isoformat(),
    )


def _safe_finance_error_detail(exc: ValueError) -> str:
    text = str(exc)
    if any(keyword in text.lower() for keyword in ("address", "地址", "token", "secret", "credential")):
        return "财务请求参数无效"
    return text or "财务请求参数无效"


def _safe_admin_web_api_key_error_detail(exc: ValueError) -> str:
    text = str(exc)
    lowered = text.lower()
    if any(
        keyword in lowered
        for keyword in (
            "api_key=",
            "authorization",
            "credential",
            "plain_key",
            "secret",
            "token",
        )
    ):
        return "API Key 参数无效"
    return text or "API Key 参数无效"


def _tenant_payment_configs_response(
    configs: AdminWebTenantPaymentProviderConfigsPage,
) -> AdminWebTenantPaymentProviderConfigsResponse:
    return AdminWebTenantPaymentProviderConfigsResponse(
        providers=[_tenant_payment_config_response(config) for config in configs.providers],
    )


def _tenant_payment_config_response(
    config: AdminWebTenantPaymentProviderConfigItem,
) -> AdminWebTenantPaymentProviderConfigItemResponse:
    return AdminWebTenantPaymentProviderConfigItemResponse(
        provider=config.provider,
        display_name=config.display_name,
        enabled=config.enabled,
        scope_type=config.scope_type,
        gateway_url=config.gateway_url,
        merchant_id_masked=config.merchant_id_masked,
        asset=config.asset,
        network=config.network,
        payment_type=config.payment_type,
        device=config.device,
        return_url_configured=config.return_url_configured,
        subject=config.subject,
        key_configured=config.key_configured,
        create_payment_available=config.create_payment_available,
        callback_available=config.callback_available,
        query_order_available=config.query_order_available,
        reconcile_available=config.reconcile_available,
        production_ready=config.production_ready,
        staging_verified=config.staging_verified,
        offline_only=config.offline_only,
    )


def _business_plugin_capabilities_response(
    summary: AdminWebBusinessPluginCapabilitiesSummary,
) -> AdminWebBusinessPluginCapabilitiesResponse:
    return AdminWebBusinessPluginCapabilitiesResponse(
        workspace=_workspace_response(summary.workspace) if summary.workspace is not None else None,
        workspace_id=summary.workspace_id,
        workspace_kind=summary.workspace_kind,
        dynamic_loading_enabled=summary.dynamic_loading_enabled,
        remote_code_enabled=summary.remote_code_enabled,
        real_external_integration_enabled=summary.real_external_integration_enabled,
        plugins=[_business_plugin_capability_response(plugin) for plugin in summary.plugins],
    )


def _business_plugin_capability_response(
    plugin: AdminWebBusinessPluginCapabilityItem,
) -> AdminWebBusinessPluginCapabilityItemResponse:
    return AdminWebBusinessPluginCapabilityItemResponse(
        plugin_id=plugin.plugin_id,
        provider_name=plugin.provider_name,
        kind=plugin.kind,
        name=plugin.name,
        version=plugin.version,
        contract_version=plugin.contract_version,
        capabilities=plugin.capabilities,
        production_ready=plugin.production_ready,
        staging_verified=plugin.staging_verified,
        offline_only=plugin.offline_only,
        tenant_configurable=plugin.tenant_configurable,
        platform_configurable=plugin.platform_configurable,
        requires_tenant_enablement=plugin.requires_tenant_enablement,
        workspace_configured=plugin.workspace_configured,
        workspace_enabled=plugin.workspace_enabled,
        scope_type=plugin.scope_type,
        active_connection_count=plugin.active_connection_count,
        disabled_connection_count=plugin.disabled_connection_count,
    )


def _external_source_connections_response(
    page: AdminWebExternalSourceConnectionsPage,
) -> AdminWebExternalSourceConnectionsResponse:
    return AdminWebExternalSourceConnectionsResponse(
        providers=[_external_source_provider_response(provider) for provider in page.providers],
        connections=[_external_source_connection_response(connection) for connection in page.connections],
    )


def _external_source_provider_response(
    provider: AdminWebExternalSourceProviderItem,
) -> AdminWebExternalSourceProviderItemResponse:
    return AdminWebExternalSourceProviderItemResponse(
        provider_name=provider.provider_name,
        integration_kind=provider.integration_kind,
        contract_name=provider.contract_name,
        production_ready=provider.production_ready,
        staging_verified=provider.staging_verified,
        catalog_sync_available=provider.catalog_sync_available,
        catalog_context_available=provider.catalog_context_available,
        catalog_product_available=provider.catalog_product_available,
        catalog_product_context_available=provider.catalog_product_context_available,
        order_available=provider.order_available,
        order_context_available=provider.order_context_available,
        delivery_available=provider.delivery_available,
        delivery_context_available=provider.delivery_context_available,
        auto_fulfillment_idempotent_available=provider.auto_fulfillment_idempotent_available,
    )


def _external_source_connection_response(
    connection: AdminWebExternalSourceConnectionItem,
) -> AdminWebExternalSourceConnectionItemResponse:
    return AdminWebExternalSourceConnectionItemResponse(
        connection_handle=connection.connection_handle,
        provider_name=connection.provider_name,
        source_key=connection.source_key,
        display_name=connection.display_name,
        status=connection.status,
        credential_field_count=connection.credential_field_count,
        created_at=connection.created_at.isoformat() if connection.created_at else None,
        last_used_at=connection.last_used_at.isoformat() if connection.last_used_at else None,
    )


def _external_catalog_sync_response(
    result: AdminWebExternalCatalogSyncResultItem,
) -> AdminWebExternalCatalogSyncResponse:
    return AdminWebExternalCatalogSyncResponse(
        provider_name=result.provider_name,
        source_key=result.source_key,
        created_count=result.created_count,
        updated_count=result.updated_count,
        skipped_count=result.skipped_count,
        next_cursor=result.next_cursor,
        products=[_external_catalog_sync_product_response(product) for product in result.products],
    )


def _external_catalog_sync_product_response(
    product: AdminWebExternalCatalogSyncProductItem,
) -> AdminWebSyncedExternalCatalogProductResponse:
    return AdminWebSyncedExternalCatalogProductResponse(
        product_id=product.product_id,
        action=product.action,
        status=product.status,
        skipped_reason=product.skipped_reason,
    )


def _external_source_catalog_products_response(
    page: AdminWebExternalSourceCatalogProductsPage,
) -> AdminWebExternalSourceCatalogProductsResponse:
    return AdminWebExternalSourceCatalogProductsResponse(
        connection_handle=page.connection_handle,
        provider_name=page.provider_name,
        source_key=page.source_key,
        display_name=page.display_name,
        status=page.status,
        total_count=page.total_count,
        limit=page.limit,
        offset=page.offset,
        items=[_external_source_catalog_product_response(item) for item in page.items],
    )


def _external_source_catalog_product_response(
    item: AdminWebExternalSourceCatalogProductItem,
) -> AdminWebExternalSourceCatalogProductItemResponse:
    return AdminWebExternalSourceCatalogProductItemResponse(
        product_id=item.product_id,
        name=item.name,
        category=item.category,
        status=item.status,
        delivery_type=item.delivery_type,
        price=item.price,
        currency=item.currency,
        available_count=item.available_count,
        updated_at=item.updated_at.isoformat() if item.updated_at else None,
    )


def _tenant_supply_dashboard_response(
    dashboard: AdminWebTenantSupplyDashboard,
) -> AdminWebTenantSupplyDashboardResponse:
    return AdminWebTenantSupplyDashboardResponse(
        supplier_enabled=dashboard.supplier_enabled,
        reseller_enabled=dashboard.reseller_enabled,
        limit=dashboard.limit,
        supplier_offers=[
            AdminWebSupplierOfferItemResponse(
                supplier_offer_id=item.supplier_offer_id,
                product_name=item.product_name,
                category=item.category,
                delivery_type=item.delivery_type,
                suggested_price=item.suggested_price,
                min_sale_price=item.min_sale_price,
                supplier_cost=item.supplier_cost,
                currency=item.currency,
                available_count=item.available_count,
                requires_approval=item.requires_approval,
                status=item.status,
            )
            for item in dashboard.supplier_offers
        ],
        supplier_applications=[
            AdminWebSupplierApplicationItemResponse(
                supplier_application_id=item.supplier_application_id,
                supplier_offer_id=item.supplier_offer_id,
                reseller_store_name=item.reseller_store_name,
                product_name=item.product_name,
                status=item.status,
                pricing_value=item.pricing_value,
                min_sale_price=item.min_sale_price,
                currency=item.currency,
                updated_at=item.updated_at.isoformat(),
            )
            for item in dashboard.supplier_applications
        ],
        supplier_rules=[
            AdminWebSupplierRuleItemResponse(
                supplier_rule_id=item.supplier_rule_id,
                supplier_offer_id=item.supplier_offer_id,
                reseller_store_name=item.reseller_store_name,
                product_name=item.product_name,
                status=item.status,
                pricing_value=item.pricing_value,
                min_sale_price=item.min_sale_price,
                currency=item.currency,
                updated_at=item.updated_at.isoformat(),
            )
            for item in dashboard.supplier_rules
        ],
        market_offers=[
            AdminWebSupplyMarketOfferItemResponse(
                supplier_offer_id=item.supplier_offer_id,
                product_name=item.product_name,
                category=item.category,
                delivery_type=item.delivery_type,
                suggested_price=item.suggested_price,
                min_sale_price=item.min_sale_price,
                currency=item.currency,
                available_count=item.available_count,
                requires_approval=item.requires_approval,
                reseller_rule_status=item.reseller_rule_status,
                can_create_reseller_product=item.can_create_reseller_product,
                supplier_cost=item.supplier_cost,
                effective_min_sale_price=item.effective_min_sale_price,
            )
            for item in dashboard.market_offers
        ],
        reseller_applications=[
            AdminWebResellerApplicationItemResponse(
                supplier_offer_id=item.supplier_offer_id,
                product_name=item.product_name,
                status=item.status,
                pricing_value=item.pricing_value,
                min_sale_price=item.min_sale_price,
                currency=item.currency,
                updated_at=item.updated_at.isoformat(),
            )
            for item in dashboard.reseller_applications
        ],
        reseller_products=[
            AdminWebResellerProductItemResponse(
                reseller_product_id=item.reseller_product_id,
                supplier_offer_id=item.supplier_offer_id,
                display_name=item.display_name,
                category=item.category,
                sort_order=item.sort_order,
                delivery_type=item.delivery_type,
                sale_price=item.sale_price,
                currency=item.currency,
                status=item.status,
                available_count=item.available_count,
            )
            for item in dashboard.reseller_products
        ],
    )


def _reseller_product_response(product: AdminWebResellerProductItem) -> AdminWebResellerProductItemResponse:
    return AdminWebResellerProductItemResponse(
        reseller_product_id=product.reseller_product_id,
        supplier_offer_id=product.supplier_offer_id,
        display_name=product.display_name,
        category=product.category,
        sort_order=product.sort_order,
        delivery_type=product.delivery_type,
        sale_price=product.sale_price,
        currency=product.currency,
        status=product.status,
        available_count=product.available_count,
    )


def _supplier_application_response(
    application: AdminWebSupplierApplicationItem,
) -> AdminWebSupplierApplicationItemResponse:
    return AdminWebSupplierApplicationItemResponse(
        supplier_application_id=application.supplier_application_id,
        supplier_offer_id=application.supplier_offer_id,
        reseller_store_name=application.reseller_store_name,
        product_name=application.product_name,
        status=application.status,
        pricing_value=application.pricing_value,
        min_sale_price=application.min_sale_price,
        currency=application.currency,
        updated_at=application.updated_at.isoformat(),
    )


def _supplier_rule_response(
    rule: AdminWebSupplierRuleItem,
) -> AdminWebSupplierRuleItemResponse:
    return AdminWebSupplierRuleItemResponse(
        supplier_rule_id=rule.supplier_rule_id,
        supplier_offer_id=rule.supplier_offer_id,
        reseller_store_name=rule.reseller_store_name,
        product_name=rule.product_name,
        status=rule.status,
        pricing_value=rule.pricing_value,
        min_sale_price=rule.min_sale_price,
        currency=rule.currency,
        updated_at=rule.updated_at.isoformat(),
    )


def _created_supplier_offer_response(
    offer: AdminWebCreatedSupplierOfferItem,
) -> AdminWebCreatedSupplierOfferItemResponse:
    return AdminWebCreatedSupplierOfferItemResponse(
        supplier_offer_id=offer.supplier_offer_id,
        product_name=offer.product_name,
        delivery_type=offer.delivery_type,
        suggested_price=offer.suggested_price,
        min_sale_price=offer.min_sale_price,
        supplier_cost=offer.supplier_cost,
        currency=offer.currency,
        requires_approval=offer.requires_approval,
        status=offer.status,
    )


def _supplier_offer_approval_response(
    setting: AdminWebSupplierOfferApprovalItem,
) -> AdminWebSupplierOfferApprovalItemResponse:
    return AdminWebSupplierOfferApprovalItemResponse(
        supplier_offer_id=setting.supplier_offer_id,
        requires_approval=setting.requires_approval,
        status=setting.status,
    )


def _reseller_application_response(
    application: AdminWebResellerApplicationItem,
) -> AdminWebResellerApplicationItemResponse:
    return AdminWebResellerApplicationItemResponse(
        supplier_offer_id=application.supplier_offer_id,
        product_name=application.product_name,
        status=application.status,
        pricing_value=application.pricing_value,
        min_sale_price=application.min_sale_price,
        currency=application.currency,
        updated_at=application.updated_at.isoformat(),
    )


def _created_reseller_product_response(
    product: AdminWebCreatedResellerProductItem,
) -> AdminWebCreatedResellerProductItemResponse:
    return AdminWebCreatedResellerProductItemResponse(
        reseller_product_id=product.reseller_product_id,
        supplier_offer_id=product.supplier_offer_id,
        display_name=product.display_name,
        sale_price=product.sale_price,
        currency=product.currency,
        status=product.status,
    )


__all__ = [
    "PLATFORM_WORKSPACE_ID",
    "create_admin_web_router",
]
