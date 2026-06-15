from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.ledger import LedgerAccount, WithdrawalRequest
from app.db.models.orders import Order, PaymentProviderConfig
from app.db.models.products import InventoryItem, Product, ProductVariant
from app.db.repos.products import ProductRepository
from app.db.repos.tenants import TenantRepository
from app.db.models.subscriptions import SubscriptionPlan, TenantSubscription
from app.db.models.supply import ResellerProduct, SupplierOffer, SupplierResellerRule
from app.db.models.tenants import PlatformUser, Tenant, TenantBot, TenantMember
from app.services.api_keys import ApiKeyService, CreatedTenantApiKey, TenantApiKeySummary
from app.services.audit import AuditLogService, AuditLogSummary
from app.services.business_plugins import (
    BUSINESS_PLUGIN_KIND_EXTERNAL_SOURCE,
    BUSINESS_PLUGIN_KIND_PAYMENT,
    BusinessPluginManifest,
    list_current_business_plugin_manifests,
)
from app.services.external_sources.connections import ExternalSourceConnectionService
from app.services.external_sources.connections import ExternalSourceConnectionSummary
from app.services.external_sources.attempts import ExternalFulfillmentAttemptLogService
from app.services.external_sources.sync import ExternalCatalogSyncService, SyncedExternalProduct
from app.services.external_sources.sync import ExternalCatalogSyncResult
from app.services.external_sources.registry import ExternalProviderSummary, list_provider_summaries
from app.services.file_inspection import FileInspectionService
from app.services.files import FileStorageService
from app.services.payments.configs import EPAY_COMPATIBLE_PROVIDER, EPUSDT_PROVIDER, PaymentConfigService
from app.services.payments.failures import PaymentCallbackFailureLogService, PaymentCallbackRejectionAuditService
from app.services.payments.service import PaymentService, PaymentUnavailableError
from app.services.ledger import LedgerBalanceAudit, LedgerService, WithdrawalSummary
from app.services.order_diagnostics import OrderDiagnosticsService, OrderDiagnosticsSummary
from app.services.risk import AfterSaleSummary, DisputeSummary, RiskControlService
from app.services.reports import (
    SUPPORTED_EXPORT_JOB_STATUSES,
    SUPPORTED_REPORT_TYPES,
    ExportJobSummary,
    ReportExportService,
)
from app.services.subscriptions import (
    SubscriptionInvoiceSummary,
    SubscriptionOrder,
    SubscriptionService,
    TenantSubscriptionSummary,
)
from app.services.supply import (
    CreatedResellerProduct,
    CreatedSupplierOffer,
    ResellerApplicationSummary,
    ResellerProductSummary,
    SupplierApprovalSetting,
    SupplierOfferSummary,
    SupplierOwnOfferSummary,
    SupplyService,
)
from app.services.tenant_features import (
    build_tenant_feature_flags,
    load_tenant_feature_flags,
    require_tenant_feature,
)
from app.services.telegram_webapp import TelegramWebAppUser
from app.services.token_crypto import TokenCrypto


ADMIN_WEB_SESSION_COOKIE_NAME = "fakabot_admin_session"
ADMIN_WEB_BINDING_CODE_PREFIX = "fakabot:admin_web:binding_code:"
PLATFORM_WORKSPACE_ID = "platform"
ADMIN_WEB_PAYMENT_PROVIDERS = (EPUSDT_PROVIDER, EPAY_COMPATIBLE_PROVIDER)


class AdminWebSessionError(ValueError):
    pass


class AdminWebBindingCodeError(ValueError):
    pass


@dataclass(frozen=True)
class AdminWebSessionClaims:
    telegram_user_id: int
    current_workspace_id: Optional[str]
    issued_at: int
    expires_at: int


@dataclass(frozen=True)
class AdminWebUserSummary:
    telegram_user_id: int
    username: Optional[str]
    first_name: Optional[str]
    is_platform_admin: bool


@dataclass(frozen=True)
class AdminWebWorkspaceSummary:
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


@dataclass(frozen=True)
class AdminWebSessionSummary:
    user: AdminWebUserSummary
    workspaces: tuple[AdminWebWorkspaceSummary, ...]
    current_workspace_id: Optional[str]


@dataclass(frozen=True)
class AdminWebTenantPaymentProviderOverview:
    provider_name: str
    display_name: str
    enabled: bool
    scope_type: str
    key_configured: bool
    create_payment_available: bool


@dataclass(frozen=True)
class AdminWebTenantPaymentProviderConfigItem:
    provider: str
    display_name: str
    enabled: bool
    scope_type: str
    gateway_url: Optional[str]
    merchant_id_masked: Optional[str]
    asset: Optional[str]
    network: Optional[str]
    payment_type: Optional[str]
    device: Optional[str]
    return_url_configured: bool
    subject: Optional[str]
    key_configured: bool
    create_payment_available: bool
    callback_available: bool
    query_order_available: bool
    reconcile_available: bool
    production_ready: bool
    staging_verified: bool
    offline_only: bool


@dataclass(frozen=True)
class AdminWebTenantPaymentProviderConfigsPage:
    providers: tuple[AdminWebTenantPaymentProviderConfigItem, ...]


@dataclass(frozen=True)
class AdminWebBusinessPluginCapabilityItem:
    plugin_id: str
    provider_name: Optional[str]
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
    workspace_configured: Optional[bool]
    workspace_enabled: Optional[bool]
    scope_type: Optional[str]
    active_connection_count: int = 0
    disabled_connection_count: int = 0


@dataclass(frozen=True)
class AdminWebBusinessPluginCapabilitiesSummary:
    workspace: Optional[AdminWebWorkspaceSummary]
    workspace_id: str
    workspace_kind: str
    dynamic_loading_enabled: bool
    remote_code_enabled: bool
    real_external_integration_enabled: bool
    plugins: tuple[AdminWebBusinessPluginCapabilityItem, ...]


@dataclass(frozen=True)
class AdminWebExternalSourceProviderItem:
    provider_name: str
    integration_kind: str
    contract_name: Optional[str]
    production_ready: bool
    staging_verified: bool
    catalog_sync_available: bool
    catalog_context_available: bool
    catalog_product_available: bool
    catalog_product_context_available: bool
    order_available: bool
    order_context_available: bool
    delivery_available: bool
    delivery_context_available: bool
    auto_fulfillment_idempotent_available: bool


@dataclass(frozen=True)
class AdminWebExternalSourceConnectionItem:
    connection_handle: str
    provider_name: str
    source_key: str
    display_name: str
    status: str
    credential_field_count: int
    created_at: Optional[datetime]
    last_used_at: Optional[datetime]


@dataclass(frozen=True)
class AdminWebExternalSourceConnectionsPage:
    providers: tuple[AdminWebExternalSourceProviderItem, ...]
    connections: tuple[AdminWebExternalSourceConnectionItem, ...]


@dataclass(frozen=True)
class AdminWebExternalCatalogSyncProductItem:
    product_id: Optional[int]
    action: str
    status: str
    skipped_reason: Optional[str] = None


@dataclass(frozen=True)
class AdminWebExternalCatalogSyncResultItem:
    provider_name: str
    source_key: str
    created_count: int
    updated_count: int
    skipped_count: int
    next_cursor: Optional[str]
    products: tuple[AdminWebExternalCatalogSyncProductItem, ...]


@dataclass(frozen=True)
class AdminWebExternalSourceCatalogProductItem:
    product_id: int
    name: str
    category: Optional[str]
    status: str
    delivery_type: str
    price: Decimal
    currency: str
    available_count: int
    updated_at: Optional[datetime]


@dataclass(frozen=True)
class AdminWebExternalSourceCatalogProductsPage:
    connection_handle: str
    provider_name: str
    source_key: str
    display_name: str
    status: str
    total_count: int
    limit: int
    offset: int
    items: tuple[AdminWebExternalSourceCatalogProductItem, ...]


@dataclass(frozen=True)
class AdminWebTenantOverview:
    workspace: AdminWebWorkspaceSummary
    tenant_public_id: str
    store_name: str
    tenant_status: str
    bot_username: Optional[str]
    bot_status: Optional[str]
    product_count: int
    published_product_count: int
    available_inventory_count: int
    order_count: int
    pending_order_count: int
    paid_order_count: int
    delivered_order_count: int
    payment_provider_count: int
    enabled_payment_provider_count: int
    payment_providers: tuple[AdminWebTenantPaymentProviderOverview, ...]
    subscription_status: Optional[str]
    subscription_plan_code: Optional[str]
    subscription_period_ends_at: Optional[datetime]
    ledger_currency: str
    ledger_pending_balance: Decimal
    ledger_available_balance: Decimal
    ledger_frozen_balance: Decimal
    pending_withdrawal_count: int
    supplier_enabled: bool
    reseller_enabled: bool
    supplier_offer_count: int
    reseller_product_count: int


@dataclass(frozen=True)
class AdminWebTenantStoreSettings:
    store_name: str
    welcome_text: str
    support_text: str
    order_timeout_minutes: int
    self_sale_enabled: bool
    supplier_enabled: bool
    reseller_enabled: bool


@dataclass(frozen=True)
class AdminWebTenantApiKeyItem:
    credential_handle: str
    name: str
    key_prefix: str
    status: str
    scopes: tuple[str, ...]
    ip_allowlist: tuple[str, ...]
    created_at: Optional[datetime]
    last_used_at: Optional[datetime]


@dataclass(frozen=True)
class AdminWebTenantApiKeysPage:
    limit: int
    keys: tuple[AdminWebTenantApiKeyItem, ...]


@dataclass(frozen=True)
class AdminWebCreatedTenantApiKeyItem(AdminWebTenantApiKeyItem):
    plain_key: str


@dataclass(frozen=True)
class AdminWebTenantApiKeyRevokeResult:
    credential_handle: str
    revoked: bool


@dataclass(frozen=True)
class AdminWebTenantProductItem:
    product_id: int
    name: str
    category: Optional[str]
    sort_order: int
    status: str
    delivery_type: str
    price: Decimal
    currency: str
    available_count: int


@dataclass(frozen=True)
class AdminWebTenantProductBatchStatusUpdate:
    status: str
    updated_count: int
    products: tuple[AdminWebTenantProductItem, ...]


@dataclass(frozen=True)
class AdminWebInventoryImportResult:
    product_id: int
    added_count: int
    existing_count: int
    input_duplicate_count: int
    available_count: int


@dataclass(frozen=True)
class AdminWebProductDeliveryFileResult:
    product_id: int
    filename: str
    size_bytes: int
    content_type: Optional[str]
    risk_level: str
    scan_message: str
    bound: bool


@dataclass(frozen=True)
class AdminWebTenantProductsPage:
    total_count: int
    limit: int
    offset: int
    items: tuple[AdminWebTenantProductItem, ...]


@dataclass(frozen=True)
class AdminWebTenantOrderItem:
    out_trade_no: str
    source_type: str
    amount: Decimal
    currency: str
    status: str
    payment_mode: str
    buyer_telegram_user_id: int
    created_at: datetime
    expires_at: datetime
    paid_at: Optional[datetime]
    delivered_at: Optional[datetime]


@dataclass(frozen=True)
class AdminWebTenantOrdersPage:
    total_count: int
    limit: int
    offset: int
    items: tuple[AdminWebTenantOrderItem, ...]


@dataclass(frozen=True)
class AdminWebOrderPaymentDiagnosticItem:
    provider: str
    status: str
    amount: Decimal
    currency: str
    has_payment_url: bool
    created_at: datetime
    paid_at: Optional[datetime]


@dataclass(frozen=True)
class AdminWebOrderPaymentCallbackDiagnosticItem:
    provider: str
    process_status: str
    failure_reason: str
    created_at: datetime
    processed_at: Optional[datetime]


@dataclass(frozen=True)
class AdminWebOrderDeliveryDiagnosticItem:
    delivery_type: str
    status: str
    failure_reason: Optional[str]
    has_inventory_item: bool
    has_uploaded_file: bool
    has_telegram_chat: bool
    created_at: datetime
    updated_at: datetime
    sent_at: Optional[datetime]


@dataclass(frozen=True)
class AdminWebOrderExternalFulfillmentDiagnosticItem:
    expected: bool
    attempt_count: int
    latest_attempt_status: Optional[str]
    latest_attempt_trigger: Optional[str]
    latest_attempt_at: Optional[datetime]
    latest_failure_stage: Optional[str]
    latest_failure_category: Optional[str]
    latest_failure_retryable: Optional[bool]
    latest_upstream_status_code: Optional[int]
    latest_item_count: int
    latest_delivery_record_linked: bool


@dataclass(frozen=True)
class AdminWebOrderTrc20DirectDiagnosticItem:
    expected: bool
    transfer_count: int
    latest_match_status: Optional[str]
    latest_confirmations: Optional[int]
    latest_matched_at: Optional[datetime]
    latest_amount: Optional[Decimal]


@dataclass(frozen=True)
class AdminWebTenantOrderDiagnostics:
    out_trade_no: str
    source_type: str
    status: str
    payment_mode: str
    payment_provider: Optional[str]
    amount: Decimal
    currency: str
    created_at: datetime
    expires_at: datetime
    paid_at: Optional[datetime]
    delivered_at: Optional[datetime]
    payment_count: int
    callback_count: int
    callback_status_counts: dict[str, int]
    payments: tuple[AdminWebOrderPaymentDiagnosticItem, ...]
    callbacks: tuple[AdminWebOrderPaymentCallbackDiagnosticItem, ...]
    delivery: Optional[AdminWebOrderDeliveryDiagnosticItem]
    external_fulfillment: AdminWebOrderExternalFulfillmentDiagnosticItem
    trc20_direct: AdminWebOrderTrc20DirectDiagnosticItem


@dataclass(frozen=True)
class AdminWebPaymentCallbackFailureItem:
    created_at: datetime
    processed_at: Optional[datetime]
    out_trade_no: str
    order_status: str
    provider: str
    process_status: str
    failure_reason: str


@dataclass(frozen=True)
class AdminWebPaymentCallbackRejectionItem:
    created_at: datetime
    provider: str
    reason_category: str
    failure_reason: str
    http_status: int
    out_trade_no: Optional[str]
    order_status: Optional[str]
    payload_field_count: int


@dataclass(frozen=True)
class AdminWebExternalFulfillmentAttemptItem:
    created_at: datetime
    started_at: datetime
    finished_at: datetime
    out_trade_no: str
    provider_name: str
    source_key: str
    attempt_source: str
    status: str
    imported: bool
    item_count: int
    failure_reason: Optional[str]
    failure_stage: Optional[str]
    failure_category: Optional[str]
    failure_retryable: Optional[bool]
    upstream_status_code: Optional[int]


@dataclass(frozen=True)
class AdminWebTenantOrderObservability:
    limit: int
    callback_failures: tuple[AdminWebPaymentCallbackFailureItem, ...]
    callback_rejections: tuple[AdminWebPaymentCallbackRejectionItem, ...]
    external_fulfillment_attempts: tuple[AdminWebExternalFulfillmentAttemptItem, ...]


@dataclass(frozen=True)
class AdminWebTenantSubscriptionInvoiceItem:
    out_trade_no: str
    amount: Decimal
    currency: str
    status: str
    paid_at: Optional[datetime]
    created_at: datetime


@dataclass(frozen=True)
class AdminWebTenantSubscriptionDashboard:
    status: str
    plan_code: Optional[str]
    plan_name: Optional[str]
    monthly_price: Optional[Decimal]
    currency: Optional[str]
    trial_days: Optional[int]
    grace_days: Optional[int]
    trial_ends_at: Optional[datetime]
    current_period_ends_at: Optional[datetime]
    subscription_ends_at: Optional[datetime]
    grace_ends_at: Optional[datetime]
    suspended_at: Optional[datetime]
    data_retention_until: Optional[datetime]
    invoices: tuple[AdminWebTenantSubscriptionInvoiceItem, ...]


@dataclass(frozen=True)
class AdminWebSubscriptionRenewalOrder:
    out_trade_no: str
    amount: Decimal
    currency: str
    months: int
    expires_at: datetime
    payment_available: bool
    payment_provider: Optional[str]
    payment_url: Optional[str]
    payment_failure_reason: Optional[str]


@dataclass(frozen=True)
class AdminWebTenantFinanceBalanceItem:
    account_type: str
    currency: str
    pending_balance: Decimal
    available_balance: Decimal
    frozen_balance: Decimal


@dataclass(frozen=True)
class AdminWebTenantFinanceAuditItem:
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


@dataclass(frozen=True)
class AdminWebTenantWithdrawalItem:
    amount: Decimal
    currency: str
    network: str
    address_masked: str
    status: str
    requested_at: datetime
    reviewed_at: Optional[datetime]
    completed_at: Optional[datetime]


@dataclass(frozen=True)
class AdminWebTenantFinanceDashboard:
    balance: AdminWebTenantFinanceBalanceItem
    audit: AdminWebTenantFinanceAuditItem
    withdrawals: tuple[AdminWebTenantWithdrawalItem, ...]


@dataclass(frozen=True)
class AdminWebTenantAuditLogItem:
    created_at: datetime
    actor_telegram_user_id: Optional[int]
    actor_username: Optional[str]
    action: str
    target_type: Optional[str]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class AdminWebTenantAuditLogsPage:
    limit: int
    items: tuple[AdminWebTenantAuditLogItem, ...]


@dataclass(frozen=True)
class AdminWebTenantRiskDisputeItem:
    out_trade_no: str
    buyer_telegram_user_id: int
    source_type: str
    order_status: str
    amount: Decimal
    currency: str
    status: str
    reason: Optional[str]
    resolution: Optional[str]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AdminWebTenantRiskAfterSaleItem:
    out_trade_no: str
    buyer_telegram_user_id: int
    source_type: str
    order_status: str
    amount: Decimal
    currency: str
    case_type: str
    status: str
    requested_amount: Optional[Decimal]
    refunded_amount: Decimal
    reason: Optional[str]
    resolution: Optional[str]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AdminWebTenantRiskDashboard:
    status: Optional[str]
    limit: int
    disputes: tuple[AdminWebTenantRiskDisputeItem, ...]
    after_sales: tuple[AdminWebTenantRiskAfterSaleItem, ...]


@dataclass(frozen=True)
class AdminWebTenantReportExportJobItem:
    report_type: str
    scope_type: str
    status: str
    row_count: int
    download_available: bool
    download_handle: Optional[str]
    failure_reason: Optional[str]
    expires_at: Optional[datetime]
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]


@dataclass(frozen=True)
class AdminWebTenantReportExportJobsPage:
    status: Optional[str]
    report_type: Optional[str]
    limit: int
    export_jobs: tuple[AdminWebTenantReportExportJobItem, ...]


@dataclass(frozen=True)
class AdminWebTenantReportExportDownloadFile:
    storage_key: str
    filename: str


@dataclass(frozen=True)
class AdminWebSupplierOfferItem:
    supplier_offer_id: int
    product_name: str
    category: Optional[str]
    delivery_type: str
    suggested_price: Decimal
    min_sale_price: Optional[Decimal]
    supplier_cost: Decimal
    currency: str
    available_count: int
    requires_approval: bool
    status: str


@dataclass(frozen=True)
class AdminWebCreatedSupplierOfferItem:
    supplier_offer_id: int
    product_name: str
    delivery_type: str
    suggested_price: Decimal
    min_sale_price: Optional[Decimal]
    supplier_cost: Decimal
    currency: str
    requires_approval: bool
    status: str


@dataclass(frozen=True)
class AdminWebSupplierOfferApprovalItem:
    supplier_offer_id: int
    requires_approval: bool
    status: str


@dataclass(frozen=True)
class AdminWebSupplyMarketOfferItem:
    supplier_offer_id: int
    product_name: str
    category: Optional[str]
    delivery_type: str
    suggested_price: Decimal
    min_sale_price: Optional[Decimal]
    currency: str
    available_count: int
    requires_approval: bool
    reseller_rule_status: Optional[str]
    can_create_reseller_product: bool
    supplier_cost: Decimal
    effective_min_sale_price: Optional[Decimal]


@dataclass(frozen=True)
class AdminWebSupplierApplicationItem:
    supplier_application_id: str
    supplier_offer_id: int
    reseller_store_name: str
    product_name: str
    status: str
    pricing_value: Decimal
    min_sale_price: Optional[Decimal]
    currency: str
    updated_at: datetime


@dataclass(frozen=True)
class AdminWebSupplierRuleItem:
    supplier_rule_id: str
    supplier_offer_id: int
    reseller_store_name: str
    product_name: str
    status: str
    pricing_value: Decimal
    min_sale_price: Optional[Decimal]
    currency: str
    updated_at: datetime


@dataclass(frozen=True)
class AdminWebResellerApplicationItem:
    supplier_offer_id: int
    product_name: str
    status: str
    pricing_value: Decimal
    min_sale_price: Optional[Decimal]
    currency: str
    updated_at: datetime


@dataclass(frozen=True)
class AdminWebResellerProductItem:
    reseller_product_id: int
    supplier_offer_id: int
    display_name: str
    category: Optional[str]
    sort_order: int
    delivery_type: str
    sale_price: Decimal
    currency: str
    status: str
    available_count: int


@dataclass(frozen=True)
class AdminWebTenantSupplyDashboard:
    supplier_enabled: bool
    reseller_enabled: bool
    limit: int
    supplier_offers: tuple[AdminWebSupplierOfferItem, ...]
    supplier_applications: tuple[AdminWebSupplierApplicationItem, ...]
    supplier_rules: tuple[AdminWebSupplierRuleItem, ...]
    market_offers: tuple[AdminWebSupplyMarketOfferItem, ...]
    reseller_applications: tuple[AdminWebResellerApplicationItem, ...]
    reseller_products: tuple[AdminWebResellerProductItem, ...]


@dataclass(frozen=True)
class AdminWebCreatedResellerProductItem:
    reseller_product_id: int
    supplier_offer_id: int
    display_name: str
    sale_price: Decimal
    currency: str
    status: str


@dataclass(frozen=True)
class AdminWebBindingCodeGrant:
    code: str
    expires_in_seconds: int


@dataclass(frozen=True)
class AdminWebBindingCodeClaims:
    telegram_user_id: int
    current_workspace_id: Optional[str]


@dataclass(frozen=True)
class AdminWebApplicationHandleClaims:
    supplier_offer_id: int
    reseller_tenant_id: int


@dataclass(frozen=True)
class AdminWebTenantApiKeyHandleClaims:
    api_key_id: int


@dataclass(frozen=True)
class AdminWebExternalSourceConnectionHandleClaims:
    connection_id: int


@dataclass(frozen=True)
class AdminWebReportExportDownloadHandleClaims:
    export_job_id: int


class AdminWebSessionCodec:
    def __init__(self, settings: Settings, *, now: int | None = None) -> None:
        self._settings = settings
        self._now = now

    def encode(self, claims: AdminWebSessionClaims) -> str:
        payload = {
            "telegram_user_id": claims.telegram_user_id,
            "current_workspace_id": claims.current_workspace_id,
            "iat": claims.issued_at,
            "exp": claims.expires_at,
        }
        payload_bytes = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        encoded_payload = _base64url_encode(payload_bytes)
        signature = hmac.new(self._session_secret(), encoded_payload.encode("ascii"), hashlib.sha256).hexdigest()
        return f"{encoded_payload}.{signature}"

    def decode(self, token: str) -> AdminWebSessionClaims:
        if not isinstance(token, str) or not token or len(token) > 4096:
            raise AdminWebSessionError("管理后台会话无效")
        encoded_payload, separator, signature = token.partition(".")
        if not separator or not encoded_payload or not signature:
            raise AdminWebSessionError("管理后台会话无效")
        expected_signature = hmac.new(self._session_secret(), encoded_payload.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_signature, signature):
            raise AdminWebSessionError("管理后台会话签名无效")
        try:
            payload = json.loads(_base64url_decode(encoded_payload))
        except (ValueError, json.JSONDecodeError) as exc:
            raise AdminWebSessionError("管理后台会话无效") from exc
        try:
            telegram_user_id = int(payload["telegram_user_id"])
            issued_at = int(payload["iat"])
            expires_at = int(payload["exp"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AdminWebSessionError("管理后台会话无效") from exc
        if telegram_user_id <= 0 or issued_at <= 0 or expires_at <= 0:
            raise AdminWebSessionError("管理后台会话无效")
        if expires_at < self._current_time():
            raise AdminWebSessionError("管理后台会话已过期")
        current_workspace_id = payload.get("current_workspace_id")
        if current_workspace_id is not None and not isinstance(current_workspace_id, str):
            raise AdminWebSessionError("管理后台会话无效")
        return AdminWebSessionClaims(
            telegram_user_id=telegram_user_id,
            current_workspace_id=current_workspace_id,
            issued_at=issued_at,
            expires_at=expires_at,
        )

    def new_claims(self, telegram_user_id: int, current_workspace_id: Optional[str]) -> AdminWebSessionClaims:
        issued_at = self._current_time()
        return AdminWebSessionClaims(
            telegram_user_id=telegram_user_id,
            current_workspace_id=current_workspace_id,
            issued_at=issued_at,
            expires_at=issued_at + self._settings.admin_web_session_max_age_seconds,
        )

    def refresh_workspace(
        self,
        claims: AdminWebSessionClaims,
        current_workspace_id: Optional[str],
    ) -> AdminWebSessionClaims:
        return AdminWebSessionClaims(
            telegram_user_id=claims.telegram_user_id,
            current_workspace_id=current_workspace_id,
            issued_at=claims.issued_at,
            expires_at=claims.expires_at,
        )

    def _session_secret(self) -> bytes:
        if self._settings.token_encryption_key is None:
            raise AdminWebSessionError("管理后台会话密钥未配置")
        return self._settings.token_encryption_key.get_secret_value().encode("utf-8")

    def _current_time(self) -> int:
        return int(time.time()) if self._now is None else self._now


class AdminWebBindingCodeStore:
    def __init__(self, settings: Settings, redis_client: object) -> None:
        self._settings = settings
        self._redis = redis_client

    async def issue_code(
        self,
        *,
        telegram_user_id: int,
        current_workspace_id: Optional[str],
    ) -> AdminWebBindingCodeGrant:
        if telegram_user_id <= 0:
            raise AdminWebBindingCodeError("绑定码用户无效")
        payload = json.dumps(
            {
                "telegram_user_id": telegram_user_id,
                "current_workspace_id": current_workspace_id,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        ttl = self._settings.admin_web_binding_code_ttl_seconds
        for _ in range(5):
            code = _generate_binding_code()
            stored = await self._redis.set(self._binding_code_key(code), payload, ex=ttl, nx=True)
            if stored:
                return AdminWebBindingCodeGrant(code=code, expires_in_seconds=ttl)
        raise AdminWebBindingCodeError("绑定码生成失败")

    async def consume_code(self, code: str) -> AdminWebBindingCodeClaims:
        normalized_code = _normalize_binding_code(code)
        if not normalized_code:
            raise AdminWebBindingCodeError("绑定码无效或已过期")
        payload = await self._consume_payload(self._binding_code_key(normalized_code))
        if not payload:
            raise AdminWebBindingCodeError("绑定码无效或已过期")
        try:
            data = json.loads(payload)
            telegram_user_id = int(data["telegram_user_id"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AdminWebBindingCodeError("绑定码无效或已过期") from exc
        if telegram_user_id <= 0:
            raise AdminWebBindingCodeError("绑定码无效或已过期")
        current_workspace_id = data.get("current_workspace_id")
        if current_workspace_id is not None and not isinstance(current_workspace_id, str):
            raise AdminWebBindingCodeError("绑定码无效或已过期")
        return AdminWebBindingCodeClaims(
            telegram_user_id=telegram_user_id,
            current_workspace_id=current_workspace_id,
        )

    async def _consume_payload(self, key: str) -> Optional[str]:
        try:
            payload = await self._redis.getdel(key)
        except AttributeError:
            payload = await self._redis.get(key)
            if payload is not None:
                await self._redis.delete(key)
        if isinstance(payload, bytes):
            return payload.decode("utf-8")
        return payload

    def _binding_code_key(self, code: str) -> str:
        if self._settings.token_encryption_key is None:
            raise AdminWebBindingCodeError("绑定码服务密钥未配置")
        digest = hmac.new(
            self._settings.token_encryption_key.get_secret_value().encode("utf-8"),
            code.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{ADMIN_WEB_BINDING_CODE_PREFIX}{digest}"


class AdminWebSupplierRelationHandleCodec:
    _VERSION = "v1"
    _KIND = "supplier_relation"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def encode(
        self,
        *,
        supplier_tenant_id: int,
        supplier_offer_id: int,
        reseller_tenant_id: int,
    ) -> str:
        if supplier_tenant_id <= 0 or supplier_offer_id <= 0 or reseller_tenant_id <= 0:
            raise AdminWebSessionError("供货申请句柄无效")
        payload = {
            "v": self._VERSION,
            "k": self._KIND,
            "supplier_tenant_id": supplier_tenant_id,
            "supplier_offer_id": supplier_offer_id,
            "reseller_tenant_id": reseller_tenant_id,
        }
        payload_text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return TokenCrypto(_handle_crypto_settings(self._settings)).encrypt_token(payload_text)

    def decode(self, handle: str, *, supplier_tenant_id: int) -> AdminWebApplicationHandleClaims:
        if not isinstance(handle, str) or not handle or len(handle) > 512 or not _is_canonical_handle(handle):
            raise AdminWebSessionError("供货申请句柄无效")
        try:
            payload = json.loads(TokenCrypto(_handle_crypto_settings(self._settings)).decrypt_token(handle))
            payload_supplier_tenant_id = int(payload["supplier_tenant_id"])
            supplier_offer_id = int(payload["supplier_offer_id"])
            reseller_tenant_id = int(payload["reseller_tenant_id"])
        except Exception as exc:
            raise AdminWebSessionError("供货申请句柄无效") from exc
        if payload.get("v") != self._VERSION or payload.get("k") != self._KIND:
            raise AdminWebSessionError("供货申请句柄无效")
        if payload_supplier_tenant_id != supplier_tenant_id or supplier_offer_id <= 0 or reseller_tenant_id <= 0:
            raise AdminWebSessionError("供货申请句柄无效")
        return AdminWebApplicationHandleClaims(
            supplier_offer_id=supplier_offer_id,
            reseller_tenant_id=reseller_tenant_id,
        )


class AdminWebApplicationHandleCodec(AdminWebSupplierRelationHandleCodec):
    pass


class AdminWebSupplierRuleHandleCodec(AdminWebSupplierRelationHandleCodec):
    pass


class AdminWebTenantApiKeyHandleCodec:
    _VERSION = "v1"
    _KIND = "tenant_api_key"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def encode(self, *, tenant_id: int, api_key_id: int) -> str:
        if tenant_id <= 0 or api_key_id <= 0:
            raise AdminWebSessionError("API Key 句柄无效")
        payload = {
            "v": self._VERSION,
            "k": self._KIND,
            "tenant_id": tenant_id,
            "api_key_id": api_key_id,
        }
        payload_text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return TokenCrypto(_handle_crypto_settings(self._settings)).encrypt_token(payload_text)

    def decode(self, handle: str, *, tenant_id: int) -> AdminWebTenantApiKeyHandleClaims:
        if not isinstance(handle, str) or not handle or len(handle) > 512 or not _is_canonical_handle(handle):
            raise AdminWebSessionError("API Key 句柄无效")
        try:
            payload = json.loads(TokenCrypto(_handle_crypto_settings(self._settings)).decrypt_token(handle))
            payload_tenant_id = int(payload["tenant_id"])
            api_key_id = int(payload["api_key_id"])
        except Exception as exc:
            raise AdminWebSessionError("API Key 句柄无效") from exc
        if payload.get("v") != self._VERSION or payload.get("k") != self._KIND:
            raise AdminWebSessionError("API Key 句柄无效")
        if payload_tenant_id != tenant_id or api_key_id <= 0:
            raise AdminWebSessionError("API Key 句柄无效")
        return AdminWebTenantApiKeyHandleClaims(api_key_id=api_key_id)


class AdminWebReportExportDownloadHandleCodec:
    _VERSION = "v1"
    _KIND = "report_export_download"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def encode(self, *, tenant_id: int, export_job_id: int) -> str:
        if tenant_id <= 0 or export_job_id <= 0:
            raise AdminWebSessionError("报表下载句柄无效")
        payload = {
            "v": self._VERSION,
            "k": self._KIND,
            "tenant_id": tenant_id,
            "export_job_id": export_job_id,
        }
        payload_text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return TokenCrypto(_handle_crypto_settings(self._settings)).encrypt_token(payload_text)

    def decode(self, handle: str, *, tenant_id: int) -> AdminWebReportExportDownloadHandleClaims:
        if not isinstance(handle, str) or not handle or len(handle) > 512 or not _is_canonical_handle(handle):
            raise AdminWebSessionError("报表下载句柄无效")
        try:
            payload = json.loads(TokenCrypto(_handle_crypto_settings(self._settings)).decrypt_token(handle))
            payload_tenant_id = int(payload["tenant_id"])
            export_job_id = int(payload["export_job_id"])
        except Exception as exc:
            raise AdminWebSessionError("报表下载句柄无效") from exc
        if payload.get("v") != self._VERSION or payload.get("k") != self._KIND:
            raise AdminWebSessionError("报表下载句柄无效")
        if payload_tenant_id != tenant_id or export_job_id <= 0:
            raise AdminWebSessionError("报表下载句柄无效")
        return AdminWebReportExportDownloadHandleClaims(export_job_id=export_job_id)


class AdminWebExternalSourceConnectionHandleCodec:
    _VERSION = "v1"
    _KIND = "external_source_connection"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def encode(self, *, tenant_id: int, connection_id: int) -> str:
        if tenant_id <= 0 or connection_id <= 0:
            raise AdminWebSessionError("外部源连接句柄无效")
        payload = {
            "v": self._VERSION,
            "k": self._KIND,
            "tenant_id": tenant_id,
            "connection_id": connection_id,
        }
        payload_text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return TokenCrypto(_handle_crypto_settings(self._settings)).encrypt_token(payload_text)

    def decode(self, handle: str, *, tenant_id: int) -> AdminWebExternalSourceConnectionHandleClaims:
        if not isinstance(handle, str) or not handle or len(handle) > 512 or not _is_canonical_handle(handle):
            raise AdminWebSessionError("外部源连接句柄无效")
        try:
            payload = json.loads(TokenCrypto(_handle_crypto_settings(self._settings)).decrypt_token(handle))
            payload_tenant_id = int(payload["tenant_id"])
            connection_id = int(payload["connection_id"])
        except Exception as exc:
            raise AdminWebSessionError("外部源连接句柄无效") from exc
        if payload.get("v") != self._VERSION or payload.get("k") != self._KIND:
            raise AdminWebSessionError("外部源连接句柄无效")
        if payload_tenant_id != tenant_id or connection_id <= 0:
            raise AdminWebSessionError("外部源连接句柄无效")
        return AdminWebExternalSourceConnectionHandleClaims(connection_id=connection_id)


class AdminWebService:
    async def create_or_update_webapp_user(
        self,
        session: AsyncSession,
        telegram_user: TelegramWebAppUser,
        settings: Settings,
    ) -> PlatformUser:
        result = await session.execute(
            select(PlatformUser).where(PlatformUser.telegram_user_id == telegram_user.id).limit(1)
        )
        user = result.scalar_one_or_none()
        if user is None:
            user = PlatformUser(
                telegram_user_id=telegram_user.id,
                username=telegram_user.username,
                first_name=telegram_user.first_name,
                language=telegram_user.language_code or "zh",
                is_platform_admin=telegram_user.id in settings.platform_admin_ids,
            )
            session.add(user)
            await session.flush()
            return user
        user.username = telegram_user.username
        user.first_name = telegram_user.first_name
        user.language = telegram_user.language_code or user.language
        user.is_platform_admin = user.is_platform_admin or telegram_user.id in settings.platform_admin_ids
        return user

    async def get_user_by_telegram_id(self, session: AsyncSession, telegram_user_id: int) -> Optional[PlatformUser]:
        result = await session.execute(
            select(PlatformUser).where(PlatformUser.telegram_user_id == telegram_user_id).limit(1)
        )
        return result.scalar_one_or_none()

    async def load_tenant_bot_token_for_public_id(
        self,
        session: AsyncSession,
        tenant_public_id: str,
    ) -> Optional[TenantBot]:
        result = await session.execute(
            select(TenantBot)
            .join(Tenant, Tenant.id == TenantBot.tenant_id)
            .where(Tenant.public_id == tenant_public_id)
            .where(TenantBot.status == "active")
            .order_by(TenantBot.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def ensure_workspace_access(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        workspace_id: str,
    ) -> None:
        if workspace_id == PLATFORM_WORKSPACE_ID:
            user = await self.get_user_by_telegram_id(session, telegram_user_id)
            if user is None or not user.is_platform_admin or user.is_banned:
                raise AdminWebSessionError("无权访问该管理工作区")
            return
        workspaces = await self.list_workspaces(session, telegram_user_id)
        if not any(workspace.workspace_id == workspace_id for workspace in workspaces):
            raise AdminWebSessionError("无权访问该管理工作区")

    async def session_summary(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        current_workspace_id: Optional[str],
    ) -> AdminWebSessionSummary:
        user = await self.get_user_by_telegram_id(session, telegram_user_id)
        if user is None:
            raise AdminWebSessionError("管理后台用户不存在")
        if user.is_banned:
            raise AdminWebSessionError("账号已被平台封禁")
        workspaces = await self.list_workspaces(session, telegram_user_id)
        available_ids = {workspace.workspace_id for workspace in workspaces}
        selected_workspace = current_workspace_id if current_workspace_id in available_ids else None
        return AdminWebSessionSummary(
            user=AdminWebUserSummary(
                telegram_user_id=user.telegram_user_id,
                username=user.username,
                first_name=user.first_name,
                is_platform_admin=user.is_platform_admin,
            ),
            workspaces=workspaces,
            current_workspace_id=selected_workspace,
        )

    async def list_workspaces(
        self,
        session: AsyncSession,
        telegram_user_id: int,
    ) -> tuple[AdminWebWorkspaceSummary, ...]:
        user = await self.get_user_by_telegram_id(session, telegram_user_id)
        if user is None or user.is_banned:
            return ()
        workspaces: list[AdminWebWorkspaceSummary] = []
        if user.is_platform_admin:
            workspaces.append(
                AdminWebWorkspaceSummary(
                    workspace_id=PLATFORM_WORKSPACE_ID,
                    kind="platform",
                    role="platform_admin",
                    title="主 Bot 管理",
                )
            )
        result = await session.execute(
            select(TenantBot, Tenant, TenantMember)
            .join(Tenant, Tenant.id == TenantBot.tenant_id)
            .join(TenantMember, TenantMember.tenant_id == Tenant.id)
            .where(TenantMember.user_id == user.id)
            .where(TenantMember.status == "active")
            .where(TenantMember.role.in_(("owner", "admin")))
            .order_by(TenantBot.created_at.desc())
        )
        for tenant_bot, tenant, member in result.all():
            feature_flags = await load_tenant_feature_flags(session, tenant.id, tenant=tenant)
            workspaces.append(
                AdminWebWorkspaceSummary(
                    workspace_id=tenant.public_id,
                    kind="tenant",
                    role=member.role,
                    title=tenant.store_name,
                    tenant_public_id=tenant.public_id,
                    bot_username=tenant_bot.bot_username,
                    tenant_status=tenant.status,
                    bot_status=tenant_bot.status,
                    supplier_enabled=feature_flags["supplier"],
                    reseller_enabled=feature_flags["reseller"],
                )
            )
        return tuple(workspaces)

    async def tenant_overview(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        telegram_user_id: int,
        workspace_id: str,
    ) -> AdminWebTenantOverview:
        workspace = await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        tenant_bot = await self.load_tenant_bot_token_for_public_id(session, workspace_id)
        product_count = await _count_where(
            session,
            Product.id,
            Product.tenant_id == tenant.id,
            Product.status != "deleted",
        )
        published_product_count = await _count_where(
            session,
            Product.id,
            Product.tenant_id == tenant.id,
            Product.status == "on",
        )
        available_inventory_count = await _count_where(
            session,
            InventoryItem.id,
            InventoryItem.tenant_id == tenant.id,
            InventoryItem.status == "available",
        )
        order_count = await _count_where(session, Order.id, Order.tenant_id == tenant.id)
        pending_order_count = await _count_where(
            session,
            Order.id,
            Order.tenant_id == tenant.id,
            Order.status == "pending",
        )
        paid_order_count = await _count_where(
            session,
            Order.id,
            Order.tenant_id == tenant.id,
            Order.status == "paid",
        )
        delivered_order_count = await _count_where(
            session,
            Order.id,
            Order.tenant_id == tenant.id,
            Order.status == "delivered",
        )
        payment_providers = await self._tenant_payment_provider_overviews(session, settings, tenant.id)
        subscription, plan = await self._load_tenant_subscription(session, tenant.id)
        ledger = await self._load_main_ledger(session, tenant.id)
        feature_flags = await load_tenant_feature_flags(session, tenant.id, tenant=tenant)
        pending_withdrawal_count = await _count_where(
            session,
            WithdrawalRequest.id,
            WithdrawalRequest.tenant_id == tenant.id,
            WithdrawalRequest.status == "pending",
        )
        supplier_offer_count = await _count_where(
            session,
            SupplierOffer.id,
            SupplierOffer.supplier_tenant_id == tenant.id,
            SupplierOffer.status != "deleted",
        )
        reseller_product_count = await _count_where(
            session,
            ResellerProduct.id,
            ResellerProduct.reseller_tenant_id == tenant.id,
            ResellerProduct.status != "deleted",
        )
        return AdminWebTenantOverview(
            workspace=workspace,
            tenant_public_id=tenant.public_id,
            store_name=tenant.store_name,
            tenant_status=tenant.status,
            bot_username=tenant_bot.bot_username if tenant_bot is not None else workspace.bot_username,
            bot_status=tenant_bot.status if tenant_bot is not None else workspace.bot_status,
            product_count=product_count,
            published_product_count=published_product_count,
            available_inventory_count=available_inventory_count,
            order_count=order_count,
            pending_order_count=pending_order_count,
            paid_order_count=paid_order_count,
            delivered_order_count=delivered_order_count,
            payment_provider_count=len(payment_providers),
            enabled_payment_provider_count=sum(1 for provider in payment_providers if provider.enabled),
            payment_providers=payment_providers,
            subscription_status=subscription.status if subscription is not None else tenant.status,
            subscription_plan_code=plan.code if plan is not None else tenant.plan_code,
            subscription_period_ends_at=(
                subscription.current_period_ends_at
                if subscription is not None and subscription.current_period_ends_at is not None
                else tenant.subscription_ends_at
            ),
            ledger_currency=ledger.currency if ledger is not None else "USDT",
            ledger_pending_balance=ledger.pending_balance if ledger is not None else Decimal("0"),
            ledger_available_balance=ledger.available_balance if ledger is not None else Decimal("0"),
            ledger_frozen_balance=ledger.frozen_balance if ledger is not None else Decimal("0"),
            pending_withdrawal_count=pending_withdrawal_count,
            supplier_enabled=feature_flags["supplier"],
            reseller_enabled=feature_flags["reseller"],
            supplier_offer_count=supplier_offer_count,
            reseller_product_count=reseller_product_count,
        )

    async def tenant_store_settings(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        workspace_id: str,
    ) -> AdminWebTenantStoreSettings:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        return await self._tenant_store_settings(session, tenant)

    async def tenant_api_keys(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        telegram_user_id: int,
        workspace_id: str,
        limit: int = 20,
    ) -> AdminWebTenantApiKeysPage:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        repo = TenantRepository()
        if not await repo.has_permission(session, tenant.id, telegram_user_id, "settings"):
            raise AdminWebSessionError("无权管理 API Key")
        normalized_limit = _normalize_page_limit(limit)
        summaries = await ApiKeyService(settings).list_tenant_api_keys(
            session=session,
            tenant_id=tenant.id,
            limit=normalized_limit,
        )
        return AdminWebTenantApiKeysPage(
            limit=normalized_limit,
            keys=tuple(_tenant_api_key_item(summary, settings=settings, tenant_id=tenant.id) for summary in summaries),
        )

    async def tenant_create_api_key(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        telegram_user_id: int,
        workspace_id: str,
        name: str,
        scopes: Optional[list[str]] = None,
        ip_allowlist: Optional[list[str]] = None,
    ) -> AdminWebCreatedTenantApiKeyItem:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        repo = TenantRepository()
        if not await repo.has_permission(session, tenant.id, telegram_user_id, "settings"):
            raise AdminWebSessionError("无权管理 API Key")
        user = await self.get_user_by_telegram_id(session, telegram_user_id)
        if user is None or user.is_banned:
            raise AdminWebSessionError("管理后台用户不可用")
        normalized_scopes = ApiKeyService.normalize_scopes(scopes)
        normalized_ip_allowlist = ApiKeyService.normalize_ip_allowlist(ip_allowlist)
        created = await ApiKeyService(settings).create_tenant_api_key(
            session=session,
            tenant_id=tenant.id,
            name=name,
            created_by_user_id=user.id,
            scopes=normalized_scopes,
            ip_allowlist=normalized_ip_allowlist,
        )
        return _created_tenant_api_key_item(created, settings=settings, tenant_id=tenant.id)

    async def tenant_revoke_api_key(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        telegram_user_id: int,
        workspace_id: str,
        credential_handle: str,
    ) -> AdminWebTenantApiKeyRevokeResult:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        repo = TenantRepository()
        if not await repo.has_permission(session, tenant.id, telegram_user_id, "settings"):
            raise AdminWebSessionError("无权管理 API Key")
        user = await self.get_user_by_telegram_id(session, telegram_user_id)
        if user is None or user.is_banned:
            raise AdminWebSessionError("管理后台用户不可用")
        claims = AdminWebTenantApiKeyHandleCodec(settings).decode(credential_handle, tenant_id=tenant.id)
        revoked = await ApiKeyService(settings).revoke_tenant_api_key(
            session=session,
            tenant_id=tenant.id,
            api_key_id=claims.api_key_id,
            revoked_by_user_id=user.id,
        )
        if not revoked:
            raise ValueError("API Key 不存在")
        return AdminWebTenantApiKeyRevokeResult(
            credential_handle=credential_handle,
            revoked=True,
        )

    async def tenant_update_store_settings(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        workspace_id: str,
        store_name: Optional[str] = None,
        welcome_text: Optional[str] = None,
        support_text: Optional[str] = None,
        order_timeout_minutes: Optional[int] = None,
        self_sale_enabled: Optional[bool] = None,
        supplier_enabled: Optional[bool] = None,
        reseller_enabled: Optional[bool] = None,
    ) -> AdminWebTenantStoreSettings:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        repo = TenantRepository()
        if not await repo.has_permission(session, tenant.id, telegram_user_id, "settings"):
            raise AdminWebSessionError("无权修改店铺设置")
        if store_name is not None:
            normalized_store_name = store_name.strip()
            if not 2 <= len(normalized_store_name) <= 64:
                raise ValueError("店铺名称长度应为 2-64 个字符")
            await repo.update_store_name(session, tenant.id, normalized_store_name)
            tenant.store_name = normalized_store_name
        if welcome_text is not None:
            normalized_welcome = welcome_text.strip()
            if len(normalized_welcome) > 500:
                raise ValueError("欢迎语长度不能超过 500 个字符")
            await repo.upsert_setting(session, tenant.id, "welcome", {"text": normalized_welcome})
        if support_text is not None:
            normalized_support = support_text.strip()
            if len(normalized_support) > 300:
                raise ValueError("客服信息长度不能超过 300 个字符")
            await repo.upsert_setting(session, tenant.id, "support", {"text": normalized_support})
        if order_timeout_minutes is not None:
            if not 1 <= order_timeout_minutes <= 1440:
                raise ValueError("订单超时时间范围为 1-1440 分钟")
            await repo.upsert_setting(
                session,
                tenant.id,
                "order_timeout_minutes",
                {"value": order_timeout_minutes},
            )
        if (
            self_sale_enabled is not None
            or supplier_enabled is not None
            or reseller_enabled is not None
        ):
            current_settings = await repo.get_settings(session, tenant.id)
            feature_flags = dict(current_settings.get("feature_flags", {}))
            if self_sale_enabled is not None:
                tenant.self_sale_enabled = self_sale_enabled
                feature_flags["self_sale"] = self_sale_enabled
            if supplier_enabled is not None:
                tenant.supplier_enabled = supplier_enabled
                feature_flags["supplier"] = supplier_enabled
            if reseller_enabled is not None:
                tenant.reseller_enabled = reseller_enabled
                feature_flags["reseller"] = reseller_enabled
            await repo.upsert_setting(session, tenant.id, "feature_flags", feature_flags)
        return await self._tenant_store_settings(session, tenant)

    async def tenant_products(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        workspace_id: str,
        limit: int = 50,
        offset: int = 0,
        query: Optional[str] = None,
        status: Optional[str] = None,
        delivery_type: Optional[str] = None,
        category: Optional[str] = None,
    ) -> AdminWebTenantProductsPage:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        normalized_limit = _normalize_page_limit(limit)
        normalized_offset = _normalize_page_offset(offset)
        normalized_query = _normalize_optional_filter(query)
        normalized_category = _normalize_optional_filter(category)
        repo = ProductRepository()
        total_count = await repo.count_products(
            session,
            tenant.id,
            search_query=normalized_query,
            status=status,
            delivery_type=delivery_type,
            category=normalized_category,
        )
        products = await repo.list_products(
            session,
            tenant.id,
            limit=normalized_limit,
            offset=normalized_offset,
            search_query=normalized_query,
            status=status,
            delivery_type=delivery_type,
            category=normalized_category,
        )
        items = tuple(
            AdminWebTenantProductItem(
                product_id=product.id,
                name=product.name,
                category=product.category,
                sort_order=int(product.sort_order or 0),
                status=product.status,
                delivery_type=product.delivery_type,
                price=variant.price if variant is not None else product.suggested_price,
                currency=variant.currency if variant is not None else product.currency,
                available_count=available_count,
            )
            for product, variant, available_count in products
        )
        return AdminWebTenantProductsPage(
            total_count=total_count,
            limit=normalized_limit,
            offset=normalized_offset,
            items=items,
        )

    async def tenant_create_product(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        workspace_id: str,
        name: str,
        price: Decimal,
        delivery_type: str,
        description: Optional[str] = None,
        category: Optional[str] = None,
    ) -> AdminWebTenantProductItem:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        if price <= 0:
            raise ValueError("商品售价必须大于 0")

        repo = ProductRepository()
        product = await repo.create_self_product(
            session=session,
            tenant_id=tenant.id,
            name=name,
            price=price,
            delivery_type=delivery_type,
            description=description,
            category=category,
        )
        product, variant = await repo.get_product_with_default_variant(session, tenant.id, product.id)
        if product is None:
            raise AdminWebSessionError("商品创建失败")
        return AdminWebTenantProductItem(
            product_id=product.id,
            name=product.name,
            category=product.category,
            sort_order=int(product.sort_order or 0),
            status=product.status,
            delivery_type=product.delivery_type,
            price=variant.price if variant is not None else product.suggested_price,
            currency=variant.currency if variant is not None else product.currency,
            available_count=0,
        )

    async def tenant_update_product_metadata(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        workspace_id: str,
        product_id: int,
        category: Optional[str],
        category_provided: bool,
        sort_order: Optional[int],
    ) -> AdminWebTenantProductItem:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        if product_id <= 0 or (not category_provided and sort_order is None):
            raise ValueError("商品元数据参数无效")

        repo = ProductRepository()
        if category_provided:
            changed = await repo.set_product_category(
                session=session,
                tenant_id=tenant.id,
                product_id=product_id,
                category=category,
            )
            if not changed:
                raise AdminWebSessionError("商品不存在或无权限")
        if sort_order is not None:
            changed = await repo.set_product_sort_order(
                session=session,
                tenant_id=tenant.id,
                product_id=product_id,
                sort_order=sort_order,
            )
            if not changed:
                raise AdminWebSessionError("商品不存在或无权限")

        product, variant = await repo.get_product_with_default_variant(session, tenant.id, product_id)
        if product is None:
            raise AdminWebSessionError("商品不存在或无权限")
        inventory_summary = await repo.inventory_summary(session, tenant.id, product_id)
        product_inventory = inventory_summary.get(product.id, {})
        return AdminWebTenantProductItem(
            product_id=product.id,
            name=product.name,
            category=product.category,
            sort_order=int(product.sort_order or 0),
            status=product.status,
            delivery_type=product.delivery_type,
            price=variant.price if variant is not None else product.suggested_price,
            currency=variant.currency if variant is not None else product.currency,
            available_count=int(product_inventory.get("available", 0)),
        )

    async def tenant_update_product_sales(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        workspace_id: str,
        product_id: int,
        price: Optional[Decimal],
        status: Optional[str],
    ) -> AdminWebTenantProductItem:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        if product_id <= 0 or (price is None and status is None):
            raise ValueError("商品销售参数无效")
        if price is not None and price <= 0:
            raise ValueError("商品售价必须大于 0")

        repo = ProductRepository()
        try:
            updated_product = await repo.update_self_product(
                session=session,
                tenant_id=tenant.id,
                product_id=product_id,
                price=price,
                status=status,
            )
        except ValueError as exc:
            if str(exc) in {"商品不存在或无权限", "只能同步自营商品"}:
                raise AdminWebSessionError("商品不存在或无权限") from exc
            raise
        product, variant = await repo.get_product_with_default_variant(session, tenant.id, updated_product.id)
        if product is None:
            raise AdminWebSessionError("商品不存在或无权限")
        inventory_summary = await repo.inventory_summary(session, tenant.id, product.id)
        product_inventory = inventory_summary.get(product.id, {})
        return AdminWebTenantProductItem(
            product_id=product.id,
            name=product.name,
            category=product.category,
            sort_order=int(product.sort_order or 0),
            status=product.status,
            delivery_type=product.delivery_type,
            price=variant.price if variant is not None else product.suggested_price,
            currency=variant.currency if variant is not None else product.currency,
            available_count=int(product_inventory.get("available", 0)),
        )

    async def tenant_batch_update_product_status(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        workspace_id: str,
        product_ids: list[int],
        status: str,
    ) -> AdminWebTenantProductBatchStatusUpdate:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        if status not in {"on", "off"}:
            raise ValueError("批量商品状态参数无效")
        if not product_ids or len(product_ids) > 50:
            raise ValueError("批量商品数量必须在 1 到 50 之间")
        invalid_product_id = any(
            not isinstance(product_id, int) or isinstance(product_id, bool) or product_id <= 0
            for product_id in product_ids
        )
        if invalid_product_id:
            raise ValueError("批量商品 ID 参数无效")
        if len(set(product_ids)) != len(product_ids):
            raise ValueError("批量商品 ID 不能重复")

        repo = ProductRepository()
        items: list[AdminWebTenantProductItem] = []
        for product_id in product_ids:
            try:
                updated_product = await repo.update_self_product(
                    session=session,
                    tenant_id=tenant.id,
                    product_id=product_id,
                    status=status,
                )
            except ValueError as exc:
                if str(exc) in {"商品不存在或无权限", "只能同步自营商品"}:
                    raise AdminWebSessionError("商品不存在或无权限") from exc
                raise
            product, variant = await repo.get_product_with_default_variant(session, tenant.id, updated_product.id)
            if product is None:
                raise AdminWebSessionError("商品不存在或无权限")
            inventory_summary = await repo.inventory_summary(session, tenant.id, product.id)
            product_inventory = inventory_summary.get(product.id, {})
            items.append(
                AdminWebTenantProductItem(
                    product_id=product.id,
                    name=product.name,
                    category=product.category,
                    sort_order=int(product.sort_order or 0),
                    status=product.status,
                    delivery_type=product.delivery_type,
                    price=variant.price if variant is not None else product.suggested_price,
                    currency=variant.currency if variant is not None else product.currency,
                    available_count=int(product_inventory.get("available", 0)),
                )
            )
        return AdminWebTenantProductBatchStatusUpdate(
            status=status,
            updated_count=len(items),
            products=tuple(items),
        )

    async def tenant_import_product_inventory(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        telegram_user_id: int,
        workspace_id: str,
        product_id: int,
        items: list[str],
    ) -> AdminWebInventoryImportResult:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        if product_id <= 0:
            raise ValueError("商品库存导入参数无效")

        normalized_items, input_duplicate_count = _normalize_inventory_items(items)
        crypto = TokenCrypto(settings)
        encrypted_items = [
            (crypto.encrypt_token(item), crypto.token_hash(item))
            for item in normalized_items
        ]
        repo = ProductRepository()
        try:
            added_count, existing_count = await repo.add_inventory_items(
                session=session,
                tenant_id=tenant.id,
                product_id=product_id,
                encrypted_items=encrypted_items,
            )
        except ValueError as exc:
            if str(exc) in {"商品不存在或缺少默认档位", "只能为自营商品导入库存"}:
                raise AdminWebSessionError("商品不存在或无权限") from exc
            if str(exc) == "当前只支持为 card_pool/card_fixed 商品导入文本库存":
                raise ValueError("当前只支持 card_pool/card_fixed 自营文本库存") from exc
            raise

        summary = await repo.inventory_summary(session, tenant.id, product_id)
        available_count = int((summary.get(product_id) or {}).get("available", 0))
        return AdminWebInventoryImportResult(
            product_id=product_id,
            added_count=added_count,
            existing_count=existing_count,
            input_duplicate_count=input_duplicate_count,
            available_count=available_count,
        )

    async def tenant_upload_product_delivery_file(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        telegram_user_id: int,
        workspace_id: str,
        product_id: int,
        filename: str,
        content_type: Optional[str],
        payload: bytes,
    ) -> AdminWebProductDeliveryFileResult:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        user = await self.get_user_by_telegram_id(session, telegram_user_id)
        if user is None or user.is_banned:
            raise AdminWebSessionError("管理后台用户不可用")
        if product_id <= 0 or not payload:
            raise ValueError("文件商品绑定参数无效")

        repo = ProductRepository()
        product, _ = await repo.get_product_with_default_variant(session, tenant.id, product_id)
        if product is None:
            raise AdminWebSessionError("商品不存在或无权限")
        if product.delivery_type != "file_download":
            raise ValueError("只有 file_download 商品可以绑定文件")
        if product.file_size_limit is not None and len(payload) > product.file_size_limit:
            raise ValueError("文件大小超过商品限制")

        file_storage = FileStorageService(settings)
        stored_file = file_storage.store_upload_file(
            filename=filename,
            content_type=content_type,
            payload=payload,
            tenant_id=tenant.id,
        )
        uploaded_file = await repo.create_uploaded_file(
            session=session,
            tenant_id=tenant.id,
            storage_key=stored_file.storage_key,
            original_filename=stored_file.original_filename,
            content_type=stored_file.content_type,
            size_bytes=stored_file.size_bytes,
            sha256=stored_file.sha256,
            owner_user_id=user.id,
        )
        inspection = await FileInspectionService().inspect_uploaded_file(
            session=session,
            tenant_id=tenant.id,
            uploaded_file_id=uploaded_file.id,
            file_path=file_storage.resolve_storage_key(stored_file.storage_key),
            requested_by_user_id=user.id,
        )
        bound = False
        if not inspection.blocked:
            try:
                await repo.bind_delivery_file(session, tenant.id, product_id, uploaded_file.id)
            except ValueError as exc:
                if str(exc) in {"商品不存在或无权限", "文件不存在或无权限"}:
                    raise AdminWebSessionError("商品不存在或无权限") from exc
                raise
            bound = True

        return AdminWebProductDeliveryFileResult(
            product_id=product_id,
            filename=stored_file.original_filename,
            size_bytes=stored_file.size_bytes,
            content_type=stored_file.content_type,
            risk_level=inspection.risk_level,
            scan_message=inspection.message,
            bound=bound,
        )

    async def tenant_orders(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        workspace_id: str,
        limit: int = 50,
        offset: int = 0,
        out_trade_no: Optional[str] = None,
        status: Optional[str] = None,
        source_type: Optional[str] = None,
        payment_mode: Optional[str] = None,
    ) -> AdminWebTenantOrdersPage:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        normalized_limit = _normalize_page_limit(limit)
        normalized_offset = _normalize_page_offset(offset)
        conditions = _tenant_order_conditions(
            tenant_id=tenant.id,
            out_trade_no=out_trade_no,
            status=status,
            source_type=source_type,
            payment_mode=payment_mode,
        )
        total_count = await _count_where(session, Order.id, *conditions)
        result = await session.execute(
            select(Order)
            .where(*conditions)
            .order_by(Order.created_at.desc())
            .limit(normalized_limit)
            .offset(normalized_offset)
        )
        orders = list(result.scalars().all())
        return AdminWebTenantOrdersPage(
            total_count=total_count,
            limit=normalized_limit,
            offset=normalized_offset,
            items=tuple(_tenant_order_item(order) for order in orders),
        )

    async def tenant_order_diagnostics(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        workspace_id: str,
        out_trade_no: str,
    ) -> AdminWebTenantOrderDiagnostics:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        try:
            summary = await OrderDiagnosticsService().get_summary(
                session,
                tenant_id=tenant.id,
                out_trade_no=out_trade_no,
            )
        except ValueError as exc:
            raise ValueError("订单号参数无效") from exc
        if summary is None:
            raise AdminWebSessionError("订单不存在或无权限")
        return _admin_web_order_diagnostics(summary)

    async def tenant_order_observability(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        workspace_id: str,
        limit: int = 20,
        out_trade_no: Optional[str] = None,
    ) -> AdminWebTenantOrderObservability:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        normalized_limit = _normalize_page_limit(limit)
        try:
            callback_failures = await PaymentCallbackFailureLogService().list_failures(
                session,
                tenant_id=tenant.id,
                process_status="failed",
                out_trade_no=out_trade_no,
                limit=normalized_limit,
            )
            callback_rejections = await PaymentCallbackRejectionAuditService().list_rejections(
                session,
                tenant_id=tenant.id,
                out_trade_no=out_trade_no,
                limit=normalized_limit,
            )
            fulfillment_attempts = await ExternalFulfillmentAttemptLogService().list_attempts(
                session,
                tenant_id=tenant.id,
                out_trade_no=out_trade_no,
                limit=normalized_limit,
            )
        except ValueError as exc:
            raise ValueError("订单观测查询参数无效") from exc
        return AdminWebTenantOrderObservability(
            limit=normalized_limit,
            callback_failures=tuple(_admin_web_callback_failure_item(item) for item in callback_failures),
            callback_rejections=tuple(_admin_web_callback_rejection_item(item) for item in callback_rejections),
            external_fulfillment_attempts=tuple(
                _admin_web_external_fulfillment_attempt_item(item) for item in fulfillment_attempts
            ),
        )

    async def tenant_subscription_dashboard(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        workspace_id: str,
        invoice_limit: int = 8,
    ) -> AdminWebTenantSubscriptionDashboard:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        normalized_limit = _normalize_page_limit(invoice_limit)
        service = SubscriptionService()
        summary = await service.get_tenant_subscription_summary(session, tenant.id)
        if summary is None:
            raise AdminWebSessionError("订阅状态不可用")
        invoices = await service.list_tenant_subscription_invoices(
            session,
            tenant_id=tenant.id,
            limit=normalized_limit,
        )
        return _tenant_subscription_dashboard(summary, invoices)

    async def tenant_create_subscription_renewal_order(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        telegram_user_id: int,
        workspace_id: str,
        months: int,
    ) -> AdminWebSubscriptionRenewalOrder:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        if months < 1 or months > 24:
            raise ValueError("订阅续费参数无效")

        renewal_order = await SubscriptionService().create_renewal_order(
            session=session,
            tenant_id=tenant.id,
            buyer_telegram_user_id=telegram_user_id,
            months=months,
            monthly_price=settings.subscription_monthly_price,
        )

        payment_provider: Optional[str] = None
        payment_url: Optional[str] = None
        payment_failure_reason: Optional[str] = None
        try:
            payment = await PaymentService(settings).create_payment_for_order(session, renewal_order.order_id)
            payment_provider = payment.provider
            payment_url = payment.payment_url
        except PaymentUnavailableError:
            payment_failure_reason = "支付配置暂不可用"
        except Exception:
            payment_failure_reason = "支付链接创建失败"

        return _admin_web_subscription_renewal_order(
            renewal_order,
            payment_provider=payment_provider,
            payment_url=payment_url,
            payment_failure_reason=payment_failure_reason,
        )

    async def tenant_finance_dashboard(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        workspace_id: str,
        withdrawal_limit: int = 8,
    ) -> AdminWebTenantFinanceDashboard:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        normalized_limit = _normalize_page_limit(withdrawal_limit)
        service = LedgerService()
        balance = await self._load_main_ledger(session, tenant.id)
        audit = await service.audit_account_balance(session, tenant.id)
        withdrawals = await service.list_withdrawals(
            session,
            tenant_id=tenant.id,
            limit=normalized_limit,
        )
        return AdminWebTenantFinanceDashboard(
            balance=AdminWebTenantFinanceBalanceItem(
                account_type=balance.account_type if balance is not None else "main",
                currency=balance.currency if balance is not None else "USDT",
                pending_balance=balance.pending_balance if balance is not None else Decimal("0"),
                available_balance=balance.available_balance if balance is not None else Decimal("0"),
                frozen_balance=balance.frozen_balance if balance is not None else Decimal("0"),
            ),
            audit=_tenant_finance_audit_item(audit),
            withdrawals=tuple(_tenant_finance_withdrawal_item(withdrawal) for withdrawal in withdrawals),
        )

    async def tenant_create_withdrawal_request(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        workspace_id: str,
        amount: Decimal,
        network: str,
        address: str,
        currency: str = "USDT",
    ) -> AdminWebTenantWithdrawalItem:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        _validate_withdrawal_amount(amount)
        normalized_network = _normalize_finance_text(network, "提现网络", max_length=32).upper()
        normalized_address = _normalize_finance_text(address, "提现地址", max_length=256)
        normalized_currency = _normalize_finance_text(currency, "提现币种", max_length=16).upper()
        user = await self.get_user_by_telegram_id(session, telegram_user_id)
        if user is None or user.is_banned:
            raise AdminWebSessionError("管理后台用户不可用")
        withdrawal = await LedgerService().create_withdrawal_request(
            session=session,
            tenant_id=tenant.id,
            amount=amount,
            network=normalized_network,
            address=normalized_address,
            currency=normalized_currency,
            actor_user_id=user.id,
        )
        return _tenant_finance_withdrawal_request_item(withdrawal)

    async def tenant_audit_logs(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        workspace_id: str,
        limit: int = 20,
        action: Optional[str] = None,
        target_type: Optional[str] = None,
    ) -> AdminWebTenantAuditLogsPage:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        normalized_limit = _normalize_page_limit(limit)
        audit_service = AuditLogService()
        logs = await audit_service.list_tenant_audit_logs(
            session=session,
            tenant_id=tenant.id,
            limit=normalized_limit,
            action=action,
            target_type=target_type,
        )
        return AdminWebTenantAuditLogsPage(
            limit=normalized_limit,
            items=tuple(_tenant_audit_log_item(audit_service, log) for log in logs),
        )

    async def tenant_risk_dashboard(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        workspace_id: str,
        status: Optional[str] = "open",
        limit: int = 20,
    ) -> AdminWebTenantRiskDashboard:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        normalized_status = _normalize_tenant_risk_status(status)
        normalized_limit = _normalize_page_limit(limit)
        risk_service = RiskControlService()
        disputes = await risk_service.list_disputes(
            session=session,
            tenant_id=tenant.id,
            status=normalized_status,
            limit=normalized_limit,
        )
        after_sales = await risk_service.list_after_sales(
            session=session,
            tenant_id=tenant.id,
            status=normalized_status,
            limit=normalized_limit,
        )
        return AdminWebTenantRiskDashboard(
            status=normalized_status,
            limit=normalized_limit,
            disputes=tuple(_tenant_risk_dispute_item(dispute) for dispute in disputes),
            after_sales=tuple(_tenant_risk_after_sale_item(after_sale) for after_sale in after_sales),
        )

    async def tenant_report_export_jobs(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        telegram_user_id: int,
        workspace_id: str,
        status: Optional[str] = None,
        report_type: Optional[str] = None,
        limit: int = 20,
    ) -> AdminWebTenantReportExportJobsPage:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        normalized_status = _normalize_tenant_report_export_status(status)
        normalized_report_type = _normalize_optional_tenant_report_type(report_type)
        normalized_limit = _normalize_page_limit(limit)
        jobs = await ReportExportService().list_export_jobs(
            session=session,
            settings=settings,
            tenant_id=tenant.id,
            status=normalized_status,
            report_type=normalized_report_type,
            limit=normalized_limit,
        )
        return AdminWebTenantReportExportJobsPage(
            status=normalized_status,
            report_type=normalized_report_type,
            limit=normalized_limit,
            export_jobs=tuple(
                _tenant_report_export_job_item(job, settings=settings, tenant_id=tenant.id)
                for job in jobs
            ),
        )

    async def tenant_create_report_export_job(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        telegram_user_id: int,
        workspace_id: str,
        report_type: str,
    ) -> AdminWebTenantReportExportJobItem:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        user = await self.get_user_by_telegram_id(session, telegram_user_id)
        if user is None or user.is_banned:
            raise AdminWebSessionError("管理后台用户不可用")
        normalized_report_type = _normalize_required_tenant_report_type(report_type)
        job = await ReportExportService().create_export_job(
            session=session,
            settings=settings,
            report_type=normalized_report_type,
            actor_user_id=user.id,
            tenant_id=tenant.id,
            scope_type="tenant",
        )
        return _tenant_report_export_job_item(job, settings=settings, tenant_id=tenant.id)

    async def tenant_report_export_download_file(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        telegram_user_id: int,
        workspace_id: str,
        download_handle: str,
    ) -> Optional[AdminWebTenantReportExportDownloadFile]:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        claims = AdminWebReportExportDownloadHandleCodec(settings).decode(
            download_handle,
            tenant_id=tenant.id,
        )
        job = await ReportExportService().get_downloadable_tenant_export(
            session=session,
            tenant_id=tenant.id,
            export_job_id=claims.export_job_id,
        )
        if job is None:
            return None
        return AdminWebTenantReportExportDownloadFile(
            storage_key=job.storage_key or "",
            filename=_admin_web_report_download_filename(job.report_type),
        )

    async def tenant_payment_configs(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        telegram_user_id: int,
        workspace_id: str,
    ) -> AdminWebTenantPaymentProviderConfigsPage:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        return await self._tenant_payment_configs_page(session, settings, tenant.id)

    async def business_plugin_capabilities(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        workspace_id: str,
    ) -> AdminWebBusinessPluginCapabilitiesSummary:
        workspace: Optional[AdminWebWorkspaceSummary] = None
        tenant_id: Optional[int] = None
        workspace_kind = "platform"
        if workspace_id == PLATFORM_WORKSPACE_ID:
            user = await self.get_user_by_telegram_id(session, telegram_user_id)
            if user is None or user.is_banned or not user.is_platform_admin:
                raise AdminWebSessionError("无权访问主 Bot 管理工作区")
        else:
            workspace = await self._tenant_workspace(session, telegram_user_id, workspace_id)
            tenant = await self._load_tenant_by_public_id(session, workspace_id)
            if tenant is None:
                raise AdminWebSessionError("克隆 Bot 工作区不可用")
            tenant_id = tenant.id
            workspace_kind = "tenant"
        plugins = await self._business_plugin_capability_items(session, tenant_id=tenant_id)
        return AdminWebBusinessPluginCapabilitiesSummary(
            workspace=workspace,
            workspace_id=workspace_id,
            workspace_kind=workspace_kind,
            dynamic_loading_enabled=False,
            remote_code_enabled=False,
            real_external_integration_enabled=False,
            plugins=tuple(plugins),
        )

    async def tenant_external_source_connections(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        telegram_user_id: int,
        workspace_id: str,
        provider_name: Optional[str] = None,
    ) -> AdminWebExternalSourceConnectionsPage:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        repo = TenantRepository()
        if not await repo.has_permission(session, tenant.id, telegram_user_id, "settings"):
            raise AdminWebSessionError("无权管理外部源连接")
        providers = tuple(_external_source_provider_item(summary) for summary in list_provider_summaries())
        connections = await ExternalSourceConnectionService().list_connections(
            session=session,
            tenant_id=tenant.id,
            provider_name=provider_name,
        )
        return AdminWebExternalSourceConnectionsPage(
            providers=providers,
            connections=tuple(
                _external_source_connection_item(connection, settings=settings, tenant_id=tenant.id)
                for connection in connections
            ),
        )

    async def tenant_create_external_source_connection(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        telegram_user_id: int,
        workspace_id: str,
        provider_name: str,
        source_key: str,
        display_name: str,
        credentials: dict[str, str],
    ) -> AdminWebExternalSourceConnectionItem:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        repo = TenantRepository()
        if not await repo.has_permission(session, tenant.id, telegram_user_id, "settings"):
            raise AdminWebSessionError("无权管理外部源连接")
        user = await self.get_user_by_telegram_id(session, telegram_user_id)
        if user is None or user.is_banned:
            raise AdminWebSessionError("管理后台用户不可用")
        connection = await ExternalSourceConnectionService().create_connection(
            session=session,
            tenant_id=tenant.id,
            provider_name=provider_name,
            source_key=source_key,
            display_name=display_name,
            credentials=credentials,
            settings=settings,
            created_by_user_id=user.id,
        )
        return _external_source_connection_item(connection, settings=settings, tenant_id=tenant.id)

    async def tenant_disable_external_source_connection(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        telegram_user_id: int,
        workspace_id: str,
        connection_handle: str,
    ) -> AdminWebExternalSourceConnectionItem:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        repo = TenantRepository()
        if not await repo.has_permission(session, tenant.id, telegram_user_id, "settings"):
            raise AdminWebSessionError("无权管理外部源连接")
        claims = AdminWebExternalSourceConnectionHandleCodec(settings).decode(
            connection_handle,
            tenant_id=tenant.id,
        )
        service = ExternalSourceConnectionService()
        disabled = await service.disable_connection(
            session=session,
            tenant_id=tenant.id,
            connection_id=claims.connection_id,
        )
        if not disabled:
            raise AdminWebSessionError("外部源连接不存在")
        connection = await service.get_connection(
            session=session,
            tenant_id=tenant.id,
            connection_id=claims.connection_id,
        )
        if connection is None:
            raise AdminWebSessionError("外部源连接不存在")
        return _external_source_connection_item(connection, settings=settings, tenant_id=tenant.id)

    async def tenant_sync_external_catalog(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        telegram_user_id: int,
        workspace_id: str,
        connection_handle: str,
        cursor: Optional[str] = None,
        limit: int = 20,
        max_pages: int = 1,
    ) -> AdminWebExternalCatalogSyncResultItem:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        repo = TenantRepository()
        if not await repo.has_permission(session, tenant.id, telegram_user_id, "settings"):
            raise AdminWebSessionError("无权管理外部源连接")
        claims = AdminWebExternalSourceConnectionHandleCodec(settings).decode(
            connection_handle,
            tenant_id=tenant.id,
        )
        connection_service = ExternalSourceConnectionService()
        connection = await connection_service.get_connection(
            session=session,
            tenant_id=tenant.id,
            connection_id=claims.connection_id,
        )
        if connection is None:
            raise AdminWebSessionError("外部源连接不存在")
        if connection.status != "active":
            raise ValueError("外部源连接未启用")
        runtime_auth = await connection_service.load_runtime_credentials(
            session=session,
            tenant_id=tenant.id,
            connection_id=claims.connection_id,
            settings=settings,
        )
        if runtime_auth is None:
            raise AdminWebSessionError("外部源连接不存在")
        result = await ExternalCatalogSyncService().sync_registered_catalog(
            session=session,
            tenant_id=tenant.id,
            provider_name=connection.provider_name,
            source_key=connection.source_key,
            connection_id=claims.connection_id,
            cursor=cursor,
            limit=limit,
            max_pages=max_pages,
            runtime_auth=runtime_auth,
        )
        return _external_catalog_sync_result_item(
            provider_name=connection.provider_name,
            source_key=connection.source_key,
            result=result,
        )

    async def tenant_external_source_catalog_products(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        telegram_user_id: int,
        workspace_id: str,
        connection_handle: str,
        limit: int = 20,
        offset: int = 0,
    ) -> AdminWebExternalSourceCatalogProductsPage:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        repo = TenantRepository()
        if not await repo.has_permission(session, tenant.id, telegram_user_id, "settings"):
            raise AdminWebSessionError("无权查看外部源商品")
        claims = AdminWebExternalSourceConnectionHandleCodec(settings).decode(
            connection_handle,
            tenant_id=tenant.id,
        )
        connection = await ExternalSourceConnectionService().get_connection(
            session=session,
            tenant_id=tenant.id,
            connection_id=claims.connection_id,
        )
        if connection is None:
            raise AdminWebSessionError("外部源连接不存在")
        normalized_limit = _normalize_page_limit(limit)
        normalized_offset = _normalize_page_offset(offset)
        total_count = await _count_external_source_catalog_products(
            session,
            tenant_id=tenant.id,
            provider_name=connection.provider_name,
            source_key=connection.source_key,
        )
        rows = await _list_external_source_catalog_products(
            session,
            tenant_id=tenant.id,
            provider_name=connection.provider_name,
            source_key=connection.source_key,
            limit=normalized_limit,
            offset=normalized_offset,
        )
        return AdminWebExternalSourceCatalogProductsPage(
            connection_handle=connection_handle,
            provider_name=connection.provider_name,
            source_key=connection.source_key,
            display_name=connection.display_name,
            status=connection.status,
            total_count=total_count,
            limit=normalized_limit,
            offset=normalized_offset,
            items=tuple(
                AdminWebExternalSourceCatalogProductItem(
                    product_id=product.id,
                    name=product.name,
                    category=product.category,
                    status=product.status,
                    delivery_type=product.delivery_type,
                    price=variant.price if variant is not None else product.suggested_price,
                    currency=variant.currency if variant is not None else product.currency,
                    available_count=available_count,
                    updated_at=product.updated_at,
                )
                for product, variant, available_count in rows
            ),
        )

    async def tenant_update_payment_config(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        telegram_user_id: int,
        workspace_id: str,
        provider_name: str,
        config_payload: dict[str, object],
    ) -> AdminWebTenantPaymentProviderConfigItem:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        provider = _admin_web_payment_provider(provider_name)
        status = await PaymentConfigService().upsert_tenant_payment_config(
            session=session,
            settings=settings,
            tenant_id=tenant.id,
            provider=provider,
            config_payload=config_payload,
        )
        return await self._tenant_payment_config_item(session, settings, tenant.id, provider, status=status)

    async def tenant_disable_payment_config(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        telegram_user_id: int,
        workspace_id: str,
        provider_name: str,
    ) -> AdminWebTenantPaymentProviderConfigItem:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        provider = _admin_web_payment_provider(provider_name)
        disabled = await PaymentConfigService().disable_tenant_payment_config(session, tenant.id, provider)
        if not disabled:
            raise AdminWebSessionError("租户支付配置不存在")
        return await self._tenant_payment_config_item(session, settings, tenant.id, provider)

    async def tenant_supply_dashboard(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        telegram_user_id: int,
        workspace_id: str,
        limit: int = 20,
        market_query: Optional[str] = None,
        market_delivery_type: Optional[str] = None,
        market_access: Optional[str] = None,
        market_min_price: Optional[Decimal] = None,
        market_max_price: Optional[Decimal] = None,
        market_stock: Optional[str] = None,
        market_category: Optional[str] = None,
    ) -> AdminWebTenantSupplyDashboard:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        normalized_limit = _normalize_page_limit(limit)
        feature_flags = await load_tenant_feature_flags(session, tenant.id, tenant=tenant)
        service = SupplyService()
        supplier_offers = []
        supplier_applications = []
        supplier_rules = []
        if feature_flags["supplier"]:
            supplier_offers = await service.list_supplier_offers(
                session=session,
                supplier_tenant_id=tenant.id,
                limit=normalized_limit,
            )
            supplier_applications = await service.list_reseller_applications(
                session=session,
                supplier_tenant_id=tenant.id,
                limit=normalized_limit,
            )
            supplier_rules = await service.list_supplier_reseller_rules(
                session=session,
                supplier_tenant_id=tenant.id,
                limit=normalized_limit,
            )
        market_offers = []
        reseller_applications = []
        reseller_products = []
        if feature_flags["reseller"]:
            market_offers = await service.list_market_offers(
                session=session,
                reseller_tenant_id=tenant.id,
                limit=normalized_limit,
                query=market_query,
                delivery_type=market_delivery_type,
                access=market_access,
                min_price=market_min_price,
                max_price=market_max_price,
                stock=market_stock,
                category=market_category,
            )
            reseller_applications = await service.list_my_reseller_applications(
                session=session,
                reseller_tenant_id=tenant.id,
                limit=normalized_limit,
            )
            reseller_products = await service.list_reseller_products(
                session=session,
                reseller_tenant_id=tenant.id,
                limit=normalized_limit,
            )
        return AdminWebTenantSupplyDashboard(
            supplier_enabled=feature_flags["supplier"],
            reseller_enabled=feature_flags["reseller"],
            limit=normalized_limit,
            supplier_offers=tuple(_supplier_offer_item(offer) for offer in supplier_offers),
            supplier_applications=tuple(
                _supplier_application_item(application, settings=settings) for application in supplier_applications
            ),
            supplier_rules=tuple(_supplier_rule_item(rule, settings=settings) for rule in supplier_rules),
            market_offers=tuple(_market_offer_item(offer) for offer in market_offers),
            reseller_applications=tuple(
                _reseller_application_item(application) for application in reseller_applications
            ),
            reseller_products=tuple(_reseller_product_item(product) for product in reseller_products),
        )

    async def tenant_supply_apply(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        workspace_id: str,
        supplier_offer_id: int,
    ) -> AdminWebResellerApplicationItem:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        require_tenant_feature(await load_tenant_feature_flags(session, tenant.id, tenant=tenant), "reseller")
        application = await SupplyService().apply_reseller(
            session=session,
            reseller_tenant_id=tenant.id,
            supplier_offer_id=supplier_offer_id,
            requested_by_user_id=None,
        )
        return _reseller_application_item(application)

    async def tenant_supply_review_supplier_application(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        telegram_user_id: int,
        workspace_id: str,
        supplier_application_id: str,
        action: str,
    ) -> AdminWebSupplierApplicationItem:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        require_tenant_feature(await load_tenant_feature_flags(session, tenant.id, tenant=tenant), "supplier")
        claims = AdminWebApplicationHandleCodec(settings).decode(
            supplier_application_id,
            supplier_tenant_id=tenant.id,
        )
        service = SupplyService()
        if action == "approve":
            application = await service.approve_reseller_application(
                session=session,
                supplier_tenant_id=tenant.id,
                supplier_offer_id=claims.supplier_offer_id,
                reseller_tenant_id=claims.reseller_tenant_id,
                actor_user_id=None,
            )
        elif action == "reject":
            application = await service.reject_reseller_application(
                session=session,
                supplier_tenant_id=tenant.id,
                supplier_offer_id=claims.supplier_offer_id,
                reseller_tenant_id=claims.reseller_tenant_id,
                actor_user_id=None,
            )
        else:
            raise ValueError("供货申请审核动作无效")
        return _supplier_application_item(application, settings=settings)

    async def tenant_supply_create_supplier_offer(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        workspace_id: str,
        product_id: int,
        suggested_price: Decimal,
        min_sale_price: Optional[Decimal],
        requires_approval: bool,
    ) -> AdminWebCreatedSupplierOfferItem:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        require_tenant_feature(await load_tenant_feature_flags(session, tenant.id, tenant=tenant), "supplier")
        offer = await SupplyService().create_supplier_offer(
            session=session,
            supplier_tenant_id=tenant.id,
            product_id=product_id,
            suggested_price=suggested_price,
            min_sale_price=min_sale_price,
            requires_approval=requires_approval,
        )
        return _created_supplier_offer_item(offer)

    async def tenant_supply_set_supplier_offer_approval(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        workspace_id: str,
        supplier_offer_id: int,
        requires_approval: bool,
    ) -> AdminWebSupplierOfferApprovalItem:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        require_tenant_feature(await load_tenant_feature_flags(session, tenant.id, tenant=tenant), "supplier")
        setting = await SupplyService().set_supplier_offer_approval(
            session=session,
            supplier_tenant_id=tenant.id,
            supplier_offer_id=supplier_offer_id,
            requires_approval=requires_approval,
            actor_user_id=None,
        )
        return _supplier_offer_approval_item(setting)

    async def tenant_supply_set_supplier_rule(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        telegram_user_id: int,
        workspace_id: str,
        supplier_rule_id: str,
        pricing_value: Decimal,
        min_sale_price: Optional[Decimal],
    ) -> AdminWebSupplierRuleItem:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        require_tenant_feature(await load_tenant_feature_flags(session, tenant.id, tenant=tenant), "supplier")
        claims = AdminWebSupplierRuleHandleCodec(settings).decode(
            supplier_rule_id,
            supplier_tenant_id=tenant.id,
        )
        application = await SupplyService().set_existing_reseller_rule(
            session=session,
            supplier_tenant_id=tenant.id,
            supplier_offer_id=claims.supplier_offer_id,
            reseller_tenant_id=claims.reseller_tenant_id,
            actor_user_id=None,
            pricing_value=pricing_value,
            min_sale_price=min_sale_price,
        )
        return _supplier_rule_item(application, settings=settings)

    async def tenant_supply_create_reseller_product(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        workspace_id: str,
        supplier_offer_id: int,
        sale_price: Decimal,
        display_name: Optional[str],
    ) -> AdminWebCreatedResellerProductItem:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        require_tenant_feature(await load_tenant_feature_flags(session, tenant.id, tenant=tenant), "reseller")
        product = await SupplyService().create_reseller_product(
            session=session,
            reseller_tenant_id=tenant.id,
            supplier_offer_id=supplier_offer_id,
            sale_price=sale_price,
            display_name=display_name,
        )
        return _created_reseller_product_item(product)

    async def tenant_supply_update_reseller_product_metadata(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        workspace_id: str,
        reseller_product_id: int,
        category: Optional[str],
        category_provided: bool,
        sort_order: Optional[int],
    ) -> AdminWebResellerProductItem:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        require_tenant_feature(await load_tenant_feature_flags(session, tenant.id, tenant=tenant), "reseller")
        try:
            product = await SupplyService().update_reseller_product_metadata(
                session=session,
                reseller_tenant_id=tenant.id,
                reseller_product_id=reseller_product_id,
                category=category,
                category_provided=category_provided,
                sort_order=sort_order,
            )
        except ValueError as exc:
            if str(exc) == "代理商品不存在或无权限":
                raise AdminWebSessionError("代理商品不存在或无权限") from exc
            raise
        return _reseller_product_item(product)

    async def tenant_supply_update_reseller_product_sales(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: int,
        workspace_id: str,
        reseller_product_id: int,
        sale_price: Optional[Decimal],
        display_name: Optional[str],
        display_name_provided: bool,
    ) -> AdminWebResellerProductItem:
        await self._tenant_workspace(session, telegram_user_id, workspace_id)
        tenant = await self._load_tenant_by_public_id(session, workspace_id)
        if tenant is None:
            raise AdminWebSessionError("克隆 Bot 工作区不可用")
        require_tenant_feature(await load_tenant_feature_flags(session, tenant.id, tenant=tenant), "reseller")
        try:
            product = await SupplyService().update_reseller_product_sales(
                session=session,
                reseller_tenant_id=tenant.id,
                reseller_product_id=reseller_product_id,
                sale_price=sale_price,
                display_name=display_name,
                display_name_provided=display_name_provided,
            )
        except ValueError as exc:
            if str(exc) == "代理商品不存在或无权限":
                raise AdminWebSessionError("代理商品不存在或无权限") from exc
            raise
        return _reseller_product_item(product)

    async def _tenant_workspace(
        self,
        session: AsyncSession,
        telegram_user_id: int,
        workspace_id: str,
    ) -> AdminWebWorkspaceSummary:
        if workspace_id == PLATFORM_WORKSPACE_ID:
            raise AdminWebSessionError("请选择克隆 Bot 工作区")
        workspaces = await self.list_workspaces(session, telegram_user_id)
        for workspace in workspaces:
            if workspace.workspace_id == workspace_id and workspace.kind == "tenant":
                return workspace
        raise AdminWebSessionError("无权访问该管理工作区")

    async def _load_tenant_by_public_id(self, session: AsyncSession, workspace_id: str) -> Optional[Tenant]:
        result = await session.execute(select(Tenant).where(Tenant.public_id == workspace_id).limit(1))
        return result.scalar_one_or_none()

    async def _business_plugin_capability_items(
        self,
        session: AsyncSession,
        *,
        tenant_id: Optional[int],
    ) -> list[AdminWebBusinessPluginCapabilityItem]:
        manifests = list_current_business_plugin_manifests()
        payment_states = await _load_tenant_payment_plugin_states(session, tenant_id) if tenant_id is not None else {}
        external_source_states = (
            await _load_tenant_external_source_plugin_states(session, tenant_id) if tenant_id is not None else {}
        )
        items: list[AdminWebBusinessPluginCapabilityItem] = []
        for manifest in manifests:
            provider_name = _business_plugin_provider_name(manifest)
            workspace_configured: Optional[bool] = None
            workspace_enabled: Optional[bool] = None
            scope_type: Optional[str] = None
            active_connection_count = 0
            disabled_connection_count = 0
            if manifest.kind == BUSINESS_PLUGIN_KIND_PAYMENT and provider_name is not None:
                state = payment_states.get(provider_name)
                workspace_configured = state is not None
                workspace_enabled = bool(state["enabled"]) if state is not None else False
                scope_type = str(state["scope_type"]) if state is not None else "tenant"
            elif manifest.kind == BUSINESS_PLUGIN_KIND_EXTERNAL_SOURCE and provider_name is not None:
                state = external_source_states.get(provider_name)
                active_connection_count = int(state["active"]) if state is not None else 0
                disabled_connection_count = int(state["disabled"]) if state is not None else 0
                workspace_configured = active_connection_count + disabled_connection_count > 0
                workspace_enabled = active_connection_count > 0
                scope_type = "tenant"
            items.append(
                AdminWebBusinessPluginCapabilityItem(
                    plugin_id=manifest.plugin_id,
                    provider_name=provider_name,
                    kind=manifest.kind,
                    name=manifest.name,
                    version=manifest.version,
                    contract_version=manifest.contract_version,
                    capabilities=dict(manifest.capabilities),
                    production_ready=manifest.production_ready,
                    staging_verified=manifest.staging_verified,
                    offline_only=manifest.offline_only,
                    tenant_configurable=manifest.tenant_configurable,
                    platform_configurable=manifest.platform_configurable,
                    requires_tenant_enablement=manifest.requires_tenant_enablement,
                    workspace_configured=workspace_configured,
                    workspace_enabled=workspace_enabled,
                    scope_type=scope_type,
                    active_connection_count=active_connection_count,
                    disabled_connection_count=disabled_connection_count,
                )
            )
        return items

    async def _tenant_store_settings(
        self,
        session: AsyncSession,
        tenant: Tenant,
    ) -> AdminWebTenantStoreSettings:
        settings = await TenantRepository().get_settings(session, tenant.id)
        welcome = settings.get("welcome", {})
        support = settings.get("support", {})
        timeout = settings.get("order_timeout_minutes", {}).get("value", 15)
        feature_flags = settings.get("feature_flags", {})
        try:
            timeout_minutes = int(timeout)
        except (TypeError, ValueError):
            timeout_minutes = 15
        timeout_minutes = min(max(timeout_minutes, 1), 1440)
        resolved_feature_flags = build_tenant_feature_flags(tenant, settings)
        return AdminWebTenantStoreSettings(
            store_name=tenant.store_name,
            welcome_text=str(welcome.get("text") or "欢迎光临，本店铺正在配置中。"),
            support_text=str(support.get("text") or "暂未配置客服联系方式。"),
            order_timeout_minutes=timeout_minutes,
            self_sale_enabled=resolved_feature_flags["self_sale"],
            supplier_enabled=resolved_feature_flags["supplier"],
            reseller_enabled=resolved_feature_flags["reseller"],
        )

    async def _load_tenant_subscription(
        self,
        session: AsyncSession,
        tenant_id: int,
    ) -> tuple[Optional[TenantSubscription], Optional[SubscriptionPlan]]:
        result = await session.execute(
            select(TenantSubscription, SubscriptionPlan)
            .join(SubscriptionPlan, SubscriptionPlan.id == TenantSubscription.plan_id)
            .where(TenantSubscription.tenant_id == tenant_id)
            .limit(1)
        )
        row = result.first()
        if row is None:
            return None, None
        return row[0], row[1]

    async def _load_main_ledger(self, session: AsyncSession, tenant_id: int) -> Optional[LedgerAccount]:
        result = await session.execute(
            select(LedgerAccount)
            .where(LedgerAccount.tenant_id == tenant_id)
            .where(LedgerAccount.account_type == "main")
            .where(LedgerAccount.currency == "USDT")
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _tenant_payment_provider_overviews(
        self,
        session: AsyncSession,
        settings: Settings,
        tenant_id: int,
    ) -> tuple[AdminWebTenantPaymentProviderOverview, ...]:
        service = PaymentConfigService()
        summaries = {summary.provider_name: summary for summary in await service.list_tenant_payment_provider_summaries()}
        providers: list[AdminWebTenantPaymentProviderOverview] = []
        for provider_name in (EPUSDT_PROVIDER, EPAY_COMPATIBLE_PROVIDER):
            summary = summaries[provider_name]
            status = await service.get_tenant_payment_config_status(session, settings, tenant_id, provider_name)
            providers.append(
                AdminWebTenantPaymentProviderOverview(
                    provider_name=provider_name,
                    display_name=summary.display_name,
                    enabled=status.enabled,
                    scope_type=status.scope_type,
                    key_configured=status.key_configured,
                    create_payment_available=summary.create_payment_available,
                )
            )
        return tuple(providers)

    async def _tenant_payment_configs_page(
        self,
        session: AsyncSession,
        settings: Settings,
        tenant_id: int,
    ) -> AdminWebTenantPaymentProviderConfigsPage:
        items = tuple(
            [
                await self._tenant_payment_config_item(session, settings, tenant_id, provider_name)
                for provider_name in ADMIN_WEB_PAYMENT_PROVIDERS
            ]
        )
        return AdminWebTenantPaymentProviderConfigsPage(providers=items)

    async def _tenant_payment_config_item(
        self,
        session: AsyncSession,
        settings: Settings,
        tenant_id: int,
        provider_name: str,
        *,
        status: object | None = None,
    ) -> AdminWebTenantPaymentProviderConfigItem:
        provider = _admin_web_payment_provider(provider_name)
        service = PaymentConfigService()
        summaries = {summary.provider_name: summary for summary in await service.list_tenant_payment_provider_summaries()}
        summary = summaries[provider]
        if status is None:
            status = await service.get_tenant_payment_config_status(session, settings, tenant_id, provider)
        return AdminWebTenantPaymentProviderConfigItem(
            provider=provider,
            display_name=summary.display_name,
            enabled=bool(getattr(status, "enabled")),
            scope_type=str(getattr(status, "scope_type")),
            gateway_url=getattr(status, "gateway_url", None) or None,
            merchant_id_masked=_mask_config_value(getattr(status, "merchant_id", None)),
            asset=getattr(status, "asset", None) or None,
            network=getattr(status, "network", None) or None,
            payment_type=getattr(status, "payment_type", None) or None,
            device=getattr(status, "device", None) or None,
            return_url_configured=bool(getattr(status, "return_url", None)),
            subject=getattr(status, "subject", None) or None,
            key_configured=bool(getattr(status, "key_configured")),
            create_payment_available=summary.create_payment_available,
            callback_available=summary.callback_available,
            query_order_available=summary.query_order_available,
            reconcile_available=summary.reconcile_available,
            production_ready=summary.production_ready,
            staging_verified=summary.staging_verified,
            offline_only=summary.offline_only,
        )


async def _count_where(session: AsyncSession, column: object, *conditions: object) -> int:
    result = await session.execute(select(func.count(column)).where(*conditions))
    return int(result.scalar_one() or 0)


def _normalize_page_limit(limit: int) -> int:
    return min(max(int(limit), 1), 100)


def _normalize_page_offset(offset: int) -> int:
    return min(max(int(offset), 0), 100000)


def _normalize_optional_filter(value: Optional[str]) -> Optional[str]:
    normalized = (value or "").strip()
    return normalized or None


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _tenant_order_conditions(
    *,
    tenant_id: int,
    out_trade_no: Optional[str],
    status: Optional[str],
    source_type: Optional[str],
    payment_mode: Optional[str],
) -> list[object]:
    conditions: list[object] = [Order.tenant_id == tenant_id]
    normalized_trade_no = _normalize_optional_filter(out_trade_no)
    if normalized_trade_no:
        conditions.append(Order.out_trade_no.ilike(f"%{_escape_like(normalized_trade_no)}%", escape="\\"))
    normalized_status = _normalize_optional_filter(status)
    if normalized_status:
        conditions.append(Order.status == normalized_status)
    normalized_source_type = _normalize_optional_filter(source_type)
    if normalized_source_type:
        conditions.append(Order.source_type == normalized_source_type)
    normalized_payment_mode = _normalize_optional_filter(payment_mode)
    if normalized_payment_mode:
        conditions.append(Order.payment_mode == normalized_payment_mode)
    return conditions


def _normalize_inventory_items(items: list[str]) -> tuple[list[str], int]:
    normalized: list[str] = []
    seen: set[str] = set()
    duplicated_count = 0
    for item in items:
        value = item.strip()
        if not value:
            continue
        if value in seen:
            duplicated_count += 1
            continue
        seen.add(value)
        normalized.append(value)
    if not normalized:
        raise ValueError("库存内容不能为空")
    if len(normalized) > 1000:
        raise ValueError("单次最多导入 1000 条库存")
    return normalized, duplicated_count


def _admin_web_payment_provider(provider_name: str) -> str:
    provider = str(provider_name).strip().lower()
    if provider == "epusdt":
        provider = EPUSDT_PROVIDER
    if provider not in ADMIN_WEB_PAYMENT_PROVIDERS:
        raise ValueError("Admin Web 暂只支持 EPUSDT 和易支付兼容配置")
    return provider


def _mask_config_value(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) <= 4:
        return "*" * len(text)
    return f"{text[:2]}***{text[-2:]}"


def _handle_crypto_settings(settings: Settings) -> Settings:
    if settings.token_encryption_key is None:
        raise AdminWebSessionError("供货申请句柄密钥未配置")
    digest = hashlib.sha256(settings.token_encryption_key.get_secret_value().encode("utf-8")).digest()
    return settings.model_copy(
        update={"token_encryption_key": SecretStr(_base64url_encode(digest) + "=")},
    )


def _is_canonical_handle(handle: str) -> bool:
    allowed_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_="
    if any(char not in allowed_chars for char in handle):
        return False
    first_padding = handle.find("=")
    if first_padding == -1:
        return True
    return all(char == "=" for char in handle[first_padding:])


def _tenant_order_item(order: Order) -> AdminWebTenantOrderItem:
    return AdminWebTenantOrderItem(
        out_trade_no=order.out_trade_no,
        source_type=order.source_type,
        amount=order.amount,
        currency=order.currency,
        status=order.status,
        payment_mode=order.payment_mode,
        buyer_telegram_user_id=order.buyer_telegram_user_id,
        created_at=order.created_at,
        expires_at=order.expires_at,
        paid_at=order.paid_at,
        delivered_at=order.delivered_at,
    )


def _admin_web_order_diagnostics(summary: OrderDiagnosticsSummary) -> AdminWebTenantOrderDiagnostics:
    return AdminWebTenantOrderDiagnostics(
        out_trade_no=summary.out_trade_no,
        source_type=summary.source_type,
        status=summary.status,
        payment_mode=summary.payment_mode,
        payment_provider=summary.payment_provider,
        amount=summary.amount,
        currency=summary.currency,
        created_at=summary.created_at,
        expires_at=summary.expires_at,
        paid_at=summary.paid_at,
        delivered_at=summary.delivered_at,
        payment_count=summary.payment_count,
        callback_count=summary.callback_count,
        callback_status_counts=dict(summary.callback_status_counts),
        payments=tuple(
            AdminWebOrderPaymentDiagnosticItem(
                provider=payment.provider,
                status=payment.status,
                amount=payment.amount,
                currency=payment.currency,
                has_payment_url=payment.has_payment_url,
                created_at=payment.created_at,
                paid_at=payment.paid_at,
            )
            for payment in summary.payments
        ),
        callbacks=tuple(
            AdminWebOrderPaymentCallbackDiagnosticItem(
                provider=callback.provider,
                process_status=callback.process_status,
                failure_reason=callback.failure_reason,
                created_at=callback.created_at,
                processed_at=callback.processed_at,
            )
            for callback in summary.callbacks
        ),
        delivery=(
            AdminWebOrderDeliveryDiagnosticItem(
                delivery_type=summary.delivery.delivery_type,
                status=summary.delivery.status,
                failure_reason=summary.delivery.failure_reason,
                has_inventory_item=summary.delivery.has_inventory_item,
                has_uploaded_file=summary.delivery.has_uploaded_file,
                has_telegram_chat=summary.delivery.has_telegram_chat,
                created_at=summary.delivery.created_at,
                updated_at=summary.delivery.updated_at,
                sent_at=summary.delivery.sent_at,
            )
            if summary.delivery is not None
            else None
        ),
        external_fulfillment=AdminWebOrderExternalFulfillmentDiagnosticItem(
            expected=summary.external_fulfillment.expected,
            attempt_count=summary.external_fulfillment.attempt_count,
            latest_attempt_status=summary.external_fulfillment.latest_attempt_status,
            latest_attempt_trigger=summary.external_fulfillment.latest_attempt_source,
            latest_attempt_at=summary.external_fulfillment.latest_attempt_at,
            latest_failure_stage=summary.external_fulfillment.latest_failure_stage,
            latest_failure_category=summary.external_fulfillment.latest_failure_category,
            latest_failure_retryable=summary.external_fulfillment.latest_failure_retryable,
            latest_upstream_status_code=summary.external_fulfillment.latest_upstream_status_code,
            latest_item_count=summary.external_fulfillment.latest_item_count,
            latest_delivery_record_linked=summary.external_fulfillment.latest_delivery_record_linked,
        ),
        trc20_direct=AdminWebOrderTrc20DirectDiagnosticItem(
            expected=summary.trc20_direct.expected,
            transfer_count=summary.trc20_direct.transfer_count,
            latest_match_status=summary.trc20_direct.latest_match_status,
            latest_confirmations=summary.trc20_direct.latest_confirmations,
            latest_matched_at=summary.trc20_direct.latest_matched_at,
            latest_amount=summary.trc20_direct.latest_amount,
        ),
    )


def _admin_web_callback_failure_item(summary: object) -> AdminWebPaymentCallbackFailureItem:
    return AdminWebPaymentCallbackFailureItem(
        created_at=summary.created_at,
        processed_at=summary.processed_at,
        out_trade_no=summary.out_trade_no,
        order_status=summary.order_status,
        provider=summary.provider,
        process_status=summary.process_status,
        failure_reason=summary.failure_reason,
    )


def _admin_web_callback_rejection_item(summary: object) -> AdminWebPaymentCallbackRejectionItem:
    return AdminWebPaymentCallbackRejectionItem(
        created_at=summary.created_at,
        provider=summary.provider,
        reason_category=summary.reason_category,
        failure_reason=summary.failure_reason,
        http_status=summary.http_status,
        out_trade_no=summary.out_trade_no,
        order_status=summary.order_status,
        payload_field_count=summary.payload_field_count,
    )


def _admin_web_external_fulfillment_attempt_item(summary: object) -> AdminWebExternalFulfillmentAttemptItem:
    return AdminWebExternalFulfillmentAttemptItem(
        created_at=summary.created_at,
        started_at=summary.started_at,
        finished_at=summary.finished_at,
        out_trade_no=summary.out_trade_no,
        provider_name=summary.provider_name,
        source_key=summary.source_key,
        attempt_source=summary.attempt_source,
        status=summary.status,
        imported=summary.imported,
        item_count=summary.item_count,
        failure_reason=summary.failure_reason,
        failure_stage=summary.failure_stage,
        failure_category=summary.failure_category,
        failure_retryable=summary.failure_retryable,
        upstream_status_code=summary.upstream_status_code,
    )


def _tenant_subscription_dashboard(
    summary: TenantSubscriptionSummary,
    invoices: list[SubscriptionInvoiceSummary],
) -> AdminWebTenantSubscriptionDashboard:
    return AdminWebTenantSubscriptionDashboard(
        status=summary.status,
        plan_code=summary.plan_code,
        plan_name=summary.plan_name,
        monthly_price=summary.monthly_price,
        currency=summary.currency,
        trial_days=summary.trial_days,
        grace_days=summary.grace_days,
        trial_ends_at=summary.trial_ends_at,
        current_period_ends_at=summary.current_period_ends_at,
        subscription_ends_at=summary.subscription_ends_at,
        grace_ends_at=summary.grace_ends_at,
        suspended_at=summary.suspended_at,
        data_retention_until=summary.data_retention_until,
        invoices=tuple(
            AdminWebTenantSubscriptionInvoiceItem(
                out_trade_no=invoice.out_trade_no,
                amount=invoice.amount,
                currency=invoice.currency,
                status=invoice.status,
                paid_at=invoice.paid_at,
                created_at=invoice.created_at,
            )
            for invoice in invoices
        ),
    )


def _admin_web_subscription_renewal_order(
    order: SubscriptionOrder,
    *,
    payment_provider: Optional[str],
    payment_url: Optional[str],
    payment_failure_reason: Optional[str],
) -> AdminWebSubscriptionRenewalOrder:
    return AdminWebSubscriptionRenewalOrder(
        out_trade_no=order.out_trade_no,
        amount=order.amount,
        currency=order.currency,
        months=order.months,
        expires_at=order.expires_at,
        payment_available=bool(payment_url),
        payment_provider=payment_provider,
        payment_url=payment_url,
        payment_failure_reason=payment_failure_reason,
    )


def _tenant_finance_audit_item(audit: LedgerBalanceAudit) -> AdminWebTenantFinanceAuditItem:
    return AdminWebTenantFinanceAuditItem(
        account_type=audit.account_type,
        currency=audit.currency,
        stored_pending_balance=audit.stored_pending_balance,
        stored_available_balance=audit.stored_available_balance,
        stored_frozen_balance=audit.stored_frozen_balance,
        computed_pending_balance=audit.computed_pending_balance,
        computed_available_balance=audit.computed_available_balance,
        computed_frozen_balance=audit.computed_frozen_balance,
        pending_difference=audit.pending_difference,
        available_difference=audit.available_difference,
        frozen_difference=audit.frozen_difference,
        is_balanced=audit.is_balanced,
    )


def _tenant_finance_withdrawal_item(withdrawal: WithdrawalSummary) -> AdminWebTenantWithdrawalItem:
    return AdminWebTenantWithdrawalItem(
        amount=withdrawal.amount,
        currency=withdrawal.currency,
        network=withdrawal.network,
        address_masked=_mask_finance_address(withdrawal.address),
        status=withdrawal.status,
        requested_at=withdrawal.requested_at,
        reviewed_at=withdrawal.reviewed_at,
        completed_at=withdrawal.completed_at,
    )


def _tenant_finance_withdrawal_request_item(withdrawal: WithdrawalRequest) -> AdminWebTenantWithdrawalItem:
    return AdminWebTenantWithdrawalItem(
        amount=withdrawal.amount,
        currency=withdrawal.currency,
        network=withdrawal.network,
        address_masked=_mask_finance_address(withdrawal.address),
        status=withdrawal.status,
        requested_at=withdrawal.requested_at,
        reviewed_at=withdrawal.reviewed_at,
        completed_at=withdrawal.completed_at,
    )


def _tenant_audit_log_item(
    audit_service: AuditLogService,
    log: AuditLogSummary,
) -> AdminWebTenantAuditLogItem:
    return AdminWebTenantAuditLogItem(
        created_at=log.created_at,
        actor_telegram_user_id=log.actor_telegram_user_id,
        actor_username=log.actor_username,
        action=log.action,
        target_type=log.target_type,
        metadata=_admin_web_safe_audit_metadata(audit_service.safe_metadata_for_tenant_api(log.metadata_json)),
    )


def _tenant_risk_dispute_item(dispute: DisputeSummary) -> AdminWebTenantRiskDisputeItem:
    return AdminWebTenantRiskDisputeItem(
        out_trade_no=dispute.out_trade_no,
        buyer_telegram_user_id=dispute.buyer_telegram_user_id,
        source_type=dispute.source_type,
        order_status=dispute.order_status,
        amount=dispute.amount,
        currency=dispute.currency,
        status=dispute.status,
        reason=_admin_web_safe_risk_text(dispute.reason),
        resolution=_admin_web_safe_risk_text(dispute.resolution),
        created_at=dispute.created_at,
        updated_at=dispute.updated_at,
    )


def _tenant_risk_after_sale_item(after_sale: AfterSaleSummary) -> AdminWebTenantRiskAfterSaleItem:
    return AdminWebTenantRiskAfterSaleItem(
        out_trade_no=after_sale.out_trade_no,
        buyer_telegram_user_id=after_sale.buyer_telegram_user_id,
        source_type=after_sale.source_type,
        order_status=after_sale.order_status,
        amount=after_sale.amount,
        currency=after_sale.currency,
        case_type=after_sale.case_type,
        status=after_sale.status,
        requested_amount=after_sale.requested_amount,
        refunded_amount=after_sale.refunded_amount,
        reason=_admin_web_safe_risk_text(after_sale.reason),
        resolution=_admin_web_safe_risk_text(after_sale.resolution),
        created_at=after_sale.created_at,
        updated_at=after_sale.updated_at,
    )


def _tenant_report_export_job_item(
    job: ExportJobSummary,
    *,
    settings: Settings,
    tenant_id: int,
) -> AdminWebTenantReportExportJobItem:
    download_available = _admin_web_report_download_available(job)
    return AdminWebTenantReportExportJobItem(
        report_type=job.report_type,
        scope_type=job.scope_type,
        status=job.status,
        row_count=job.row_count,
        download_available=download_available,
        download_handle=(
            AdminWebReportExportDownloadHandleCodec(settings).encode(
                tenant_id=tenant_id,
                export_job_id=job.export_job_id,
            )
            if download_available and job.tenant_id == tenant_id
            else None
        ),
        failure_reason=_admin_web_safe_report_failure_text(job.error_message),
        expires_at=job.expires_at,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def _admin_web_safe_audit_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in list((metadata or {}).items())[:50]:
        key_text = str(key)[:128]
        if _is_admin_web_internal_metadata_key(key_text):
            continue
        safe[key_text] = _admin_web_safe_audit_metadata_value(value, depth=0)
    return safe


def _admin_web_safe_audit_metadata_value(value: Any, *, depth: int) -> Any:
    if value is None or isinstance(value, (str, int, bool, float)):
        return value
    if depth >= 3:
        return type(value).__name__
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in list(value.items())[:20]:
            key_text = str(key)[:128]
            if _is_admin_web_internal_metadata_key(key_text):
                continue
            safe[key_text] = _admin_web_safe_audit_metadata_value(item, depth=depth + 1)
        return safe
    if isinstance(value, list):
        return [_admin_web_safe_audit_metadata_value(item, depth=depth + 1) for item in value[:10]]
    return str(value)[:300]


def _is_admin_web_internal_metadata_key(key: str) -> bool:
    normalized = key.lower()
    if normalized in {
        "actor_user_id",
        "api_key_id",
        "audit_log_id",
        "callback_id",
        "delivery_file_id",
        "delivery_record_id",
        "inventory_item_id",
        "invoice_id",
        "order_id",
        "payment_id",
        "plan_id",
        "product_id",
        "product_variant_id",
        "reseller_tenant_id",
        "subscription_id",
        "supplier_tenant_id",
        "tenant_id",
        "uploaded_file_id",
        "variant_id",
        "withdrawal_id",
    }:
        return True
    return normalized.endswith("_internal_id")


def _normalize_tenant_risk_status(status: Optional[str]) -> Optional[str]:
    if status is None:
        return "open"
    normalized = status.strip().lower()
    if normalized == "all":
        return None
    if normalized not in {"open", "reviewing", "resolved", "rejected", "closed"}:
        raise ValueError("风控状态无效")
    return normalized


def _admin_web_report_download_available(job: ExportJobSummary) -> bool:
    if job.status != "completed" or not job.download_url or job.expires_at is None:
        return False
    expires_at = job.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at > datetime.now(timezone.utc)


def _admin_web_report_download_filename(report_type: str) -> str:
    normalized = (report_type or "").strip().lower()
    if normalized in SUPPORTED_REPORT_TYPES:
        return f"{normalized}-report.csv"
    return "report.csv"


def _normalize_tenant_report_export_status(status: Optional[str]) -> Optional[str]:
    if status is None:
        return None
    normalized = status.strip().lower()
    if not normalized or normalized == "all":
        return None
    if normalized not in SUPPORTED_EXPORT_JOB_STATUSES:
        raise ValueError("报表任务状态无效")
    return normalized


def _normalize_optional_tenant_report_type(report_type: Optional[str]) -> Optional[str]:
    if report_type is None:
        return None
    normalized = report_type.strip().lower()
    if not normalized or normalized == "all":
        return None
    if normalized not in SUPPORTED_REPORT_TYPES:
        raise ValueError("报表类型无效")
    return normalized


def _normalize_required_tenant_report_type(report_type: str) -> str:
    normalized = report_type.strip().lower()
    if not normalized or normalized == "all" or normalized not in SUPPORTED_REPORT_TYPES:
        raise ValueError("报表类型无效")
    return normalized


def _admin_web_safe_report_failure_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    lowered = normalized.lower()
    if "http://" in lowered or "https://" in lowered:
        return "报表导出失败"
    if "/" in normalized or "\\" in normalized:
        return "报表导出失败"
    if any(marker in lowered for marker in _ADMIN_WEB_REPORT_FAILURE_SENSITIVE_MARKERS):
        return "报表导出失败"
    return normalized[:300]


def _admin_web_safe_risk_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    lowered = normalized.lower()
    if "http://" in lowered or "https://" in lowered:
        return "内容已隐藏"
    if any(marker in lowered for marker in _ADMIN_WEB_RISK_TEXT_SENSITIVE_MARKERS):
        return "内容已隐藏"
    return normalized[:300]


_ADMIN_WEB_RISK_TEXT_SENSITIVE_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "card_secret",
    "cookie",
    "credential",
    "payment_url",
    "plain_key",
    "provider_trade_no",
    "raw_payload",
    "raw_request",
    "raw_response",
    "secret",
    "signature",
    "signing_text",
    "storage_key",
    "token",
    "卡密",
)


_ADMIN_WEB_REPORT_FAILURE_SENSITIVE_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "download_token",
    "download_url",
    "error_message",
    "filename",
    "local_path",
    "payload",
    "path",
    "payment_url",
    "plain_key",
    "provider_trade_no",
    "raw_payload",
    "raw_request",
    "raw_response",
    "secret",
    "signature",
    "signing_text",
    "storage_key",
    "token",
)


def _mask_finance_address(value: str) -> str:
    if len(value) <= 12:
        return "***"
    return f"{value[:6]}***{value[-6:]}"


def _normalize_finance_text(value: str, field_name: str, *, max_length: int) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name}不能为空")
    if len(text) > max_length:
        raise ValueError(f"{field_name}不能超过 {max_length} 个字符")
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ValueError(f"{field_name}不能包含控制字符")
    return text


def _validate_withdrawal_amount(amount: Decimal) -> None:
    if amount <= 0:
        raise ValueError("提现金额必须大于 0")
    if amount.as_tuple().exponent < -8:
        raise ValueError("提现金额最多支持 8 位小数")


def _supplier_offer_item(offer: SupplierOwnOfferSummary) -> AdminWebSupplierOfferItem:
    return AdminWebSupplierOfferItem(
        supplier_offer_id=offer.offer_id,
        product_name=offer.product_name,
        category=offer.category,
        delivery_type=offer.delivery_type,
        suggested_price=offer.suggested_price,
        min_sale_price=offer.min_sale_price,
        supplier_cost=offer.supplier_cost,
        currency=offer.currency,
        available_count=offer.available_count,
        requires_approval=offer.requires_approval,
        status=offer.status,
    )


def _created_supplier_offer_item(offer: CreatedSupplierOffer) -> AdminWebCreatedSupplierOfferItem:
    return AdminWebCreatedSupplierOfferItem(
        supplier_offer_id=offer.offer_id,
        product_name=offer.product_name,
        delivery_type=offer.delivery_type,
        suggested_price=offer.suggested_price,
        min_sale_price=offer.min_sale_price,
        supplier_cost=offer.supplier_cost,
        currency=offer.currency,
        requires_approval=offer.requires_approval,
        status=offer.status,
    )


def _supplier_offer_approval_item(setting: SupplierApprovalSetting) -> AdminWebSupplierOfferApprovalItem:
    return AdminWebSupplierOfferApprovalItem(
        supplier_offer_id=setting.offer_id,
        requires_approval=setting.requires_approval,
        status=setting.status,
    )


def _tenant_api_key_item(
    api_key: TenantApiKeySummary,
    *,
    settings: Settings,
    tenant_id: int,
) -> AdminWebTenantApiKeyItem:
    return AdminWebTenantApiKeyItem(
        credential_handle=AdminWebTenantApiKeyHandleCodec(settings).encode(
            tenant_id=tenant_id,
            api_key_id=api_key.api_key_id,
        ),
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        status=api_key.status,
        scopes=tuple(api_key.scopes),
        ip_allowlist=tuple(api_key.ip_allowlist),
        created_at=api_key.created_at,
        last_used_at=api_key.last_used_at,
    )


def _created_tenant_api_key_item(
    api_key: CreatedTenantApiKey,
    *,
    settings: Settings,
    tenant_id: int,
) -> AdminWebCreatedTenantApiKeyItem:
    return AdminWebCreatedTenantApiKeyItem(
        credential_handle=AdminWebTenantApiKeyHandleCodec(settings).encode(
            tenant_id=tenant_id,
            api_key_id=api_key.api_key_id,
        ),
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        plain_key=api_key.plain_key,
        status=api_key.status,
        scopes=tuple(api_key.scopes),
        ip_allowlist=tuple(api_key.ip_allowlist),
        created_at=None,
        last_used_at=None,
    )


def _market_offer_item(offer: SupplierOfferSummary) -> AdminWebSupplyMarketOfferItem:
    return AdminWebSupplyMarketOfferItem(
        supplier_offer_id=offer.offer_id,
        product_name=offer.product_name,
        category=offer.category,
        delivery_type=offer.delivery_type,
        suggested_price=offer.suggested_price,
        min_sale_price=offer.min_sale_price,
        currency=offer.currency,
        available_count=offer.available_count,
        requires_approval=offer.requires_approval,
        reseller_rule_status=offer.reseller_rule_status,
        can_create_reseller_product=(not offer.requires_approval or offer.reseller_rule_status == "active"),
        supplier_cost=offer.supplier_cost,
        effective_min_sale_price=offer.effective_min_sale_price,
    )


def _supplier_application_item(
    application: ResellerApplicationSummary,
    *,
    settings: Settings,
) -> AdminWebSupplierApplicationItem:
    return AdminWebSupplierApplicationItem(
        supplier_application_id=AdminWebApplicationHandleCodec(settings).encode(
            supplier_tenant_id=application.supplier_tenant_id,
            supplier_offer_id=application.supplier_offer_id,
            reseller_tenant_id=application.reseller_tenant_id,
        ),
        supplier_offer_id=application.supplier_offer_id,
        reseller_store_name=application.reseller_store_name,
        product_name=application.product_name,
        status=application.status,
        pricing_value=application.pricing_value,
        min_sale_price=application.min_sale_price,
        currency=application.currency,
        updated_at=application.updated_at,
    )


def _supplier_rule_item(
    rule: ResellerApplicationSummary,
    *,
    settings: Settings,
) -> AdminWebSupplierRuleItem:
    return AdminWebSupplierRuleItem(
        supplier_rule_id=AdminWebSupplierRuleHandleCodec(settings).encode(
            supplier_tenant_id=rule.supplier_tenant_id,
            supplier_offer_id=rule.supplier_offer_id,
            reseller_tenant_id=rule.reseller_tenant_id,
        ),
        supplier_offer_id=rule.supplier_offer_id,
        reseller_store_name=rule.reseller_store_name,
        product_name=rule.product_name,
        status=rule.status,
        pricing_value=rule.pricing_value,
        min_sale_price=rule.min_sale_price,
        currency=rule.currency,
        updated_at=rule.updated_at,
    )


def _reseller_application_item(application: ResellerApplicationSummary) -> AdminWebResellerApplicationItem:
    return AdminWebResellerApplicationItem(
        supplier_offer_id=application.supplier_offer_id,
        product_name=application.product_name,
        status=application.status,
        pricing_value=application.pricing_value,
        min_sale_price=application.min_sale_price,
        currency=application.currency,
        updated_at=application.updated_at,
    )


def _reseller_product_item(product: ResellerProductSummary) -> AdminWebResellerProductItem:
    return AdminWebResellerProductItem(
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


def _created_reseller_product_item(product: CreatedResellerProduct) -> AdminWebCreatedResellerProductItem:
    return AdminWebCreatedResellerProductItem(
        reseller_product_id=product.reseller_product_id,
        supplier_offer_id=product.supplier_offer_id,
        display_name=product.display_name,
        sale_price=product.sale_price,
        currency=product.currency,
        status=product.status,
    )


async def _load_tenant_payment_plugin_states(
    session: AsyncSession,
    tenant_id: int,
) -> dict[str, dict[str, object]]:
    result = await session.execute(
        select(
            PaymentProviderConfig.provider,
            PaymentProviderConfig.enabled,
            PaymentProviderConfig.scope_type,
        )
        .where(PaymentProviderConfig.scope_type == "tenant")
        .where(PaymentProviderConfig.tenant_id == tenant_id)
    )
    states: dict[str, dict[str, object]] = {}
    for provider, enabled, scope_type in result.all():
        states[str(provider)] = {
            "enabled": bool(enabled),
            "scope_type": str(scope_type),
        }
    return states


async def _load_tenant_external_source_plugin_states(
    session: AsyncSession,
    tenant_id: int,
) -> dict[str, dict[str, int]]:
    states: dict[str, dict[str, int]] = {}
    connections = await ExternalSourceConnectionService().list_connections(session, tenant_id=tenant_id)
    for connection in connections:
        provider_state = states.setdefault(connection.provider_name, {"active": 0, "disabled": 0})
        if connection.status == "active":
            provider_state["active"] += 1
        else:
            provider_state["disabled"] += 1
    return states


async def _count_external_source_catalog_products(
    session: AsyncSession,
    *,
    tenant_id: int,
    provider_name: str,
    source_key: str,
) -> int:
    result = await session.execute(
        select(func.count(Product.id)).where(
            *_external_source_catalog_product_conditions(
                tenant_id=tenant_id,
                provider_name=provider_name,
                source_key=source_key,
            )
        )
    )
    return int(result.scalar_one() or 0)


async def _list_external_source_catalog_products(
    session: AsyncSession,
    *,
    tenant_id: int,
    provider_name: str,
    source_key: str,
    limit: int,
    offset: int,
) -> list[tuple[Product, Optional[ProductVariant], int]]:
    inventory_count_subquery = (
        select(
            InventoryItem.product_id.label("product_id"),
            func.count(InventoryItem.id).label("available_count"),
        )
        .where(InventoryItem.tenant_id == tenant_id)
        .where(InventoryItem.status == "available")
        .group_by(InventoryItem.product_id)
        .subquery()
    )
    result = await session.execute(
        select(Product, ProductVariant, func.coalesce(inventory_count_subquery.c.available_count, 0))
        .outerjoin(
            ProductVariant,
            (ProductVariant.product_id == Product.id)
            & (ProductVariant.tenant_id == tenant_id)
            & (ProductVariant.sort_order == 0),
        )
        .outerjoin(inventory_count_subquery, inventory_count_subquery.c.product_id == Product.id)
        .where(
            *_external_source_catalog_product_conditions(
                tenant_id=tenant_id,
                provider_name=provider_name,
                source_key=source_key,
            )
        )
        .order_by(Product.updated_at.desc(), Product.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [(row[0], row[1], int(row[2] or 0)) for row in result.all()]


def _external_source_catalog_product_conditions(
    *,
    tenant_id: int,
    provider_name: str,
    source_key: str,
) -> tuple[object, ...]:
    return (
        Product.tenant_id == tenant_id,
        Product.product_type == "self",
        Product.external_source == provider_name,
        Product.source_key == source_key,
        Product.external_id.is_not(None),
        Product.status != "deleted",
    )


def _business_plugin_provider_name(manifest: BusinessPluginManifest) -> Optional[str]:
    if manifest.kind == BUSINESS_PLUGIN_KIND_PAYMENT and manifest.plugin_id.startswith("payment_"):
        return manifest.plugin_id.removeprefix("payment_")
    if manifest.kind == BUSINESS_PLUGIN_KIND_EXTERNAL_SOURCE and manifest.plugin_id.startswith("external_source_"):
        return manifest.plugin_id.removeprefix("external_source_")
    return None


def _external_source_provider_item(summary: ExternalProviderSummary) -> AdminWebExternalSourceProviderItem:
    return AdminWebExternalSourceProviderItem(
        provider_name=summary.provider_name,
        integration_kind=summary.integration_kind,
        contract_name=summary.contract_name,
        production_ready=summary.production_ready,
        staging_verified=summary.staging_verified,
        catalog_sync_available=summary.capabilities.catalog_sync_available,
        catalog_context_available=summary.capabilities.catalog_context_available,
        catalog_product_available=summary.capabilities.catalog_product_available,
        catalog_product_context_available=summary.capabilities.catalog_product_context_available,
        order_available=summary.capabilities.order_available,
        order_context_available=summary.capabilities.order_context_available,
        delivery_available=summary.capabilities.delivery_available,
        delivery_context_available=summary.capabilities.delivery_context_available,
        auto_fulfillment_idempotent_available=summary.capabilities.auto_fulfillment_idempotent_available,
    )


def _external_source_connection_item(
    connection: ExternalSourceConnectionSummary,
    *,
    settings: Settings,
    tenant_id: int,
) -> AdminWebExternalSourceConnectionItem:
    return AdminWebExternalSourceConnectionItem(
        connection_handle=AdminWebExternalSourceConnectionHandleCodec(settings).encode(
            tenant_id=tenant_id,
            connection_id=connection.connection_id,
        ),
        provider_name=connection.provider_name,
        source_key=connection.source_key,
        display_name=connection.display_name,
        status=connection.status,
        credential_field_count=len(connection.credential_fields),
        created_at=connection.created_at,
        last_used_at=connection.last_used_at,
    )


def _external_catalog_sync_result_item(
    *,
    provider_name: str,
    source_key: str,
    result: ExternalCatalogSyncResult,
) -> AdminWebExternalCatalogSyncResultItem:
    return AdminWebExternalCatalogSyncResultItem(
        provider_name=provider_name,
        source_key=source_key,
        created_count=result.created_count,
        updated_count=result.updated_count,
        skipped_count=result.skipped_count,
        next_cursor=result.next_cursor,
        products=tuple(_external_catalog_sync_product_item(product) for product in result.products),
    )


def _external_catalog_sync_product_item(
    product: SyncedExternalProduct,
) -> AdminWebExternalCatalogSyncProductItem:
    return AdminWebExternalCatalogSyncProductItem(
        product_id=product.product_id,
        action=product.action,
        status=product.status,
        skipped_reason=product.skipped_reason,
    )


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii")).decode("utf-8")


def _generate_binding_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _normalize_binding_code(code: str) -> str:
    normalized = "".join(char for char in code.strip() if char.isdigit())
    if len(normalized) != 6:
        return ""
    return normalized
