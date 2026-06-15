from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.config import Settings
from app.db.models.orders import Order
from app.db.models.tenants import TenantApiKey
from app.db.repos.products import ProductRepository
from app.db.session import get_session_factory
from app.services.audit import AuditLogService, AuditLogSummary
from app.services.api_keys import ApiKeyService, CreatedTenantApiKey, TenantApiKeySummary
from app.services.api_security import (
    ApiIpAccessError,
    ApiRateLimitError,
    ApiSignatureError,
    FixedWindowRateLimiter,
    RedisFixedWindowRateLimiter,
    hit_rate_limit,
    require_ip_allowed,
    resolve_client_ip,
    verify_request_signature,
)
from app.services.external_sources import (
    ExternalAutoFulfillmentAttemptResult,
    ExternalAutoFulfillmentService,
    ExternalCatalogSyncService,
    ExternalDelivery,
    ExternalDeliveryImportService,
    ExternalFulfillmentAttemptLogService,
    ExternalFulfillmentAttemptSummary,
    ExternalFulfillmentFailureLogService,
    ExternalFulfillmentFailureSummary,
    ExternalOrder,
    ExternalOrderOperationService,
    ExternalOrderRequest,
    ExternalProviderNotRegisteredError,
    ExternalProviderSummary,
    ExternalSourceError,
    list_provider_summaries,
)
from app.services.external_sources.connections import (
    ExternalSourceConnectionService,
    ExternalSourceConnectionSummary,
    ExternalSourceRuntimeCredentials,
)
from app.services.external_sources.identifiers import normalize_external_identifier as _normalize_service_external_identifier
from app.services.external_sources.sync import ExternalCatalogSyncResult
from app.services.ledger import LedgerBalance, LedgerBalanceAudit, LedgerService, WithdrawalSummary
from app.services.order_diagnostics import (
    OrderDeliveryDiagnostic,
    OrderDiagnosticsService,
    OrderDiagnosticsSummary,
    OrderExternalFulfillmentDiagnostic,
    OrderPaymentCallbackDiagnostic,
    OrderPaymentDiagnostic,
    OrderTrc20DirectDiagnostic,
)
from app.services.payments import (
    PaymentCallbackFailureLogService,
    PaymentCallbackFailureSummary,
    PaymentCallbackRejectionAuditService,
    PaymentCallbackRejectionSummary,
    PaymentService,
    PaymentUnavailableError,
    Trc20DirectTransferObservationService,
    Trc20DirectTransferSummary,
)
from app.services.payments.configs import (
    EPAY_COMPATIBLE_PROVIDER,
    EPUSDT_PROVIDER,
    LEMZF_PROVIDER,
    TOKEN188_PROVIDER,
    EpusdtConfigStatus,
    PaymentConfigService,
    PaymentProviderSummary,
    TenantPaymentConfigStatus,
    normalize_epusdt_base_url,
    normalize_payment_provider,
    validate_payment_provider_config_payload,
)
from app.services.reports import ExportJobSummary, ReportExportService
from app.services.risk import AfterSaleSummary, DisputeSummary, RiskControlService
from app.services.subscriptions import (
    SubscriptionInvoiceSummary,
    SubscriptionService,
    TenantSubscriptionSummary,
)
from app.services.supply import (
    CreatedSupplierOffer,
    CreatedResellerProduct,
    ResellerApplicationSummary,
    ResellerProductSummary,
    SupplierApprovalSetting,
    SupplierOwnOfferSummary,
    SupplierOfferSummary,
    SupplyService,
)
from app.services.tenant_features import (
    load_tenant_feature_flags,
    tenant_feature_disabled_message,
    tenant_feature_enabled,
)
from app.services.token_crypto import TokenCrypto

REPORT_EXPORT_JOB_STATUS_VALUES = {"pending", "running", "completed", "failed", "expired"}
REPORT_EXPORT_JOB_TYPES = {"orders", "payments", "inventory", "ledger"}

REPORT_FAILURE_SENSITIVE_VALUE_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "download_token",
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

RISK_RESPONSE_SENSITIVE_VALUE_MARKERS = (
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
)

RISK_STATUS_VALUES = {"open", "reviewing", "resolved", "rejected", "closed"}


async def _require_tenant_admin_feature(session: Any, tenant_id: int, feature: str) -> None:
    feature_flags = await load_tenant_feature_flags(session, tenant_id)
    if not tenant_feature_enabled(feature_flags, feature):
        raise HTTPException(status_code=403, detail=tenant_feature_disabled_message(feature))


class AdminProduct(BaseModel):
    id: int
    external_source: Optional[str] = None
    source_key: str = ""
    external_id: Optional[str] = None
    name: str
    category: Optional[str] = None
    sort_order: int = 0
    status: str
    delivery_type: str
    price: Decimal
    currency: str
    available_count: int


class CreateAdminProductRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    price: Decimal = Field(gt=0)
    delivery_type: str
    description: Optional[str] = None
    category: Optional[str] = Field(default=None, max_length=128)


class UpdateProductMetadataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Optional[str] = Field(default=None, max_length=128)
    sort_order: Optional[int] = Field(default=None, ge=-100000, le=100000)


class ImportInventoryRequest(BaseModel):
    items: List[str] = Field(min_length=1, max_length=1000)


class ImportInventoryResponse(BaseModel):
    product_id: int
    added_count: int
    existing_count: int
    input_duplicate_count: int


class InventorySummaryResponse(BaseModel):
    product_id: int
    available_count: int
    locked_count: int
    used_count: int
    total_count: int


class SyncProductItem(BaseModel):
    product_id: Optional[int] = Field(default=None, gt=0)
    external_source: Optional[str] = Field(default=None, max_length=64)
    source_key: Optional[str] = Field(default=None, max_length=128)
    external_id: Optional[str] = Field(default=None, max_length=128)
    name: str = Field(min_length=2, max_length=255)
    price: Decimal = Field(gt=0)
    delivery_type: str
    description: Optional[str] = None
    category: Optional[str] = Field(default=None, max_length=128)
    status: Optional[str] = None


class SyncProductsRequest(BaseModel):
    products: List[SyncProductItem] = Field(min_length=1, max_length=100)


class SyncedProductItem(BaseModel):
    product_id: int
    external_source: Optional[str] = None
    source_key: str = ""
    external_id: Optional[str] = None
    action: str
    status: str


class SyncProductsResponse(BaseModel):
    created_count: int
    updated_count: int
    products: List[SyncedProductItem]


class SyncExternalCatalogRequest(BaseModel):
    connection_id: Optional[int] = Field(default=None, gt=0)
    source_key: str = Field(default="", max_length=128)
    cursor: Optional[str] = Field(default=None, max_length=512)
    limit: int = Field(default=50, ge=1, le=100)
    max_pages: int = Field(default=1, ge=1, le=20)


class SyncExternalCatalogProductRequest(BaseModel):
    external_product_id: str = Field(min_length=1, max_length=128)
    connection_id: Optional[int] = Field(default=None, gt=0)
    source_key: str = Field(default="", max_length=128)


class CreateExternalOrderRequest(BaseModel):
    external_product_id: str = Field(min_length=1, max_length=128)
    quantity: int = Field(default=1, ge=1, le=1000)
    out_trade_no: Optional[str] = Field(default=None, max_length=96)
    buyer_reference: Optional[str] = Field(default=None, max_length=128)
    buyer_contact: Optional[str] = Field(default=None, max_length=256)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    connection_id: Optional[int] = Field(default=None, gt=0)
    source_key: str = Field(default="", max_length=128)


class ExternalOrderResponse(BaseModel):
    provider_name: str
    source_key: str
    connection_id: Optional[int] = None
    external_order_id: str
    external_product_id: str
    status: str
    quantity: int
    amount: Decimal
    currency: str
    delivery_ready: bool


class ExternalDeliveryResponse(BaseModel):
    provider_name: str
    source_key: str
    connection_id: Optional[int] = None
    external_order_id: str
    delivery_type: str
    items: List[str]
    message: Optional[str] = None


class ImportExternalDeliveryRequest(BaseModel):
    provider_name: str = Field(min_length=1, max_length=64)
    external_order_id: str = Field(min_length=1, max_length=128)
    connection_id: Optional[int] = Field(default=None, gt=0)
    source_key: str = Field(default="", max_length=128)
    dry_run: bool = False


class ImportExternalDeliveryResponse(BaseModel):
    out_trade_no: str
    order_status: str
    delivery_record_id: Optional[int] = None
    item_count: int
    imported: bool
    dry_run: bool = False


class RetryExternalFulfillmentResponse(BaseModel):
    out_trade_no: str
    provider_name: str
    source_key: str
    external_order_id: Optional[str] = None
    delivery_record_id: Optional[int] = None
    item_count: int
    imported: bool
    attempt_status: str
    failure_stage: Optional[str] = None
    failure_category: Optional[str] = None
    failure_retryable: Optional[bool] = None
    upstream_status_code: Optional[int] = None
    failure_recorded: bool = False


class SyncedExternalCatalogProduct(BaseModel):
    product_id: Optional[int] = None
    external_source: str
    source_key: str
    external_id: str
    action: str
    status: str
    skipped_reason: Optional[str] = None


class SyncExternalCatalogResponse(BaseModel):
    provider_name: str
    source_key: str
    connection_id: Optional[int] = None
    created_count: int
    updated_count: int
    skipped_count: int
    next_cursor: Optional[str] = None
    products: List[SyncedExternalCatalogProduct]


class ExternalSourceProviderItem(BaseModel):
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


class ListExternalSourceProvidersResponse(BaseModel):
    providers: List[ExternalSourceProviderItem]


class ExternalSourceConnectionItem(BaseModel):
    connection_id: int
    provider_name: str
    source_key: str
    display_name: str
    status: str
    credential_fields: List[str]
    created_at: Optional[str] = None
    last_used_at: Optional[str] = None


class ListExternalSourceConnectionsResponse(BaseModel):
    connections: List[ExternalSourceConnectionItem]


class ExternalFulfillmentAttemptItem(BaseModel):
    attempt_id: int
    created_at: str
    started_at: str
    finished_at: str
    order_id: int
    out_trade_no: str
    product_id: int
    provider_name: str
    source_key: str
    external_product_id: str
    connection_id: Optional[int] = None
    external_order_id: Optional[str] = None
    delivery_record_id: Optional[int] = None
    attempt_source: str
    status: str
    imported: bool
    item_count: int
    failure_reason: Optional[str] = None
    failure_stage: Optional[str] = None
    failure_category: Optional[str] = None
    failure_retryable: Optional[bool] = None
    upstream_status_code: Optional[int] = None
    failure_fingerprint: Optional[str] = None


class ListExternalFulfillmentAttemptsResponse(BaseModel):
    attempts: List[ExternalFulfillmentAttemptItem]


class ExternalFulfillmentFailureItem(BaseModel):
    audit_log_id: int
    created_at: str
    order_id: Optional[int] = None
    out_trade_no: Optional[str] = None
    product_id: Optional[int] = None
    provider_name: str
    source_key: str
    external_product_id: Optional[str] = None
    connection_id: Optional[int] = None
    external_order_id: Optional[str] = None
    failure_reason: str
    failure_stage: str
    failure_category: str
    failure_retryable: bool
    upstream_status_code: Optional[int] = None
    failure_fingerprint: Optional[str] = None


class ListExternalFulfillmentFailuresResponse(BaseModel):
    failures: List[ExternalFulfillmentFailureItem]


class CreateExternalSourceConnectionRequest(BaseModel):
    provider_name: str = Field(min_length=1, max_length=64)
    source_key: str = Field(default="", max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    credentials: Dict[str, str] = Field(min_length=1)


class DisableExternalSourceConnectionResponse(BaseModel):
    connection_id: int
    disabled: bool


class TenantEpusdtConfigResponse(BaseModel):
    provider: str
    enabled: bool
    scope_type: str
    base_url: Optional[str] = None
    pid_masked: Optional[str] = None
    asset: Optional[str] = None
    network: Optional[str] = None
    key_configured: bool


class UpdateTenantEpusdtConfigRequest(BaseModel):
    base_url: str
    pid: str
    secret_key: str
    token: Optional[str] = None
    network: Optional[str] = None


class DisableTenantEpusdtConfigResponse(BaseModel):
    provider: str
    disabled: bool


class TenantPaymentProviderConfigResponse(BaseModel):
    provider: str
    enabled: bool
    scope_type: str
    gateway_url: Optional[str] = None
    merchant_id_masked: Optional[str] = None
    monitor_address_masked: Optional[str] = None
    asset: Optional[str] = None
    network: Optional[str] = None
    chain_type: Optional[str] = None
    payment_type: Optional[str] = None
    device: Optional[str] = None
    return_url_configured: bool = False
    subject: Optional[str] = None
    cny_per_usdt: Optional[str] = None
    min_usdt_amount: Optional[str] = None
    timeout_seconds: Optional[int] = None
    key_configured: bool


class UpdateTenantPaymentProviderConfigRequest(BaseModel):
    model_config = ConfigDict(extra="allow", json_schema_extra={"additionalProperties": False})

    gateway_url: Optional[str] = None
    base_url: Optional[str] = None
    merchant_id: Optional[str] = None
    pid: Optional[str] = None
    key: Optional[str] = None
    secret_key: Optional[str] = None
    monitor_address: Optional[str] = None
    token: Optional[str] = None
    network: Optional[str] = None
    chain_type: Optional[str] = None
    payment_type: Optional[str] = None
    device: Optional[str] = None
    return_url: Optional[str] = None
    subject: Optional[str] = None
    cny_per_usdt: Optional[str] = None
    min_usdt_amount: Optional[str] = None
    timeout_seconds: Optional[int] = None


class DisableTenantPaymentProviderConfigResponse(BaseModel):
    provider: str
    disabled: bool


class TenantPaymentProviderItem(BaseModel):
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
    supported_assets: List[str]
    supported_networks: List[str]


class ListTenantPaymentProvidersResponse(BaseModel):
    providers: List[TenantPaymentProviderItem]


class TenantPaymentCallbackFailureItem(BaseModel):
    callback_id: int
    created_at: str
    processed_at: Optional[str] = None
    order_id: int
    out_trade_no: str
    order_status: str
    provider: str
    process_status: str
    failure_reason: str


class ListTenantPaymentCallbackFailuresResponse(BaseModel):
    failures: List[TenantPaymentCallbackFailureItem]


class TenantPaymentCallbackRejectionItem(BaseModel):
    audit_log_id: int
    created_at: str
    provider: str
    reason_category: str
    failure_reason: str
    http_status: int
    out_trade_no: Optional[str] = None
    order_id: Optional[int] = None
    order_status: Optional[str] = None
    payload_field_count: int


class ListTenantPaymentCallbackRejectionsResponse(BaseModel):
    rejections: List[TenantPaymentCallbackRejectionItem]


class TenantTrc20DirectTransferItem(BaseModel):
    tx_hash: str
    block_number: int
    timestamp_ms: int
    block_timestamp: Optional[str] = None
    from_address_masked: str
    to_address_masked: str
    contract_address: str
    amount: Decimal
    confirmations: int
    match_status: str
    out_trade_no: Optional[str] = None
    matched_at: Optional[str] = None
    created_at: str


class TenantTrc20DirectTransferListResponse(BaseModel):
    transfers: List[TenantTrc20DirectTransferItem]


class CreateTenantApiKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    scopes: Optional[List[str]] = None
    ip_allowlist: Optional[List[str]] = None


class TenantApiKeyItem(BaseModel):
    api_key_id: int
    name: str
    key_prefix: str
    status: str
    scopes: List[str]
    ip_allowlist: List[str]
    created_at: Optional[str] = None
    last_used_at: Optional[str] = None


class CreatedTenantApiKeyResponse(TenantApiKeyItem):
    plain_key: str


class RevokeTenantApiKeyResponse(BaseModel):
    api_key_id: int
    revoked: bool


class TenantAuditLogItem(BaseModel):
    audit_log_id: int
    created_at: str
    actor_telegram_user_id: Optional[int] = None
    actor_username: Optional[str] = None
    action: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    metadata: Dict[str, Any]


class ListTenantAuditLogsResponse(BaseModel):
    audit_logs: List[TenantAuditLogItem]


class TenantRiskDisputeItem(BaseModel):
    dispute_id: int
    order_id: int
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


class ListTenantRiskDisputesResponse(BaseModel):
    disputes: List[TenantRiskDisputeItem]


class TenantRiskAfterSaleItem(BaseModel):
    case_id: int
    order_id: int
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


class ListTenantRiskAfterSalesResponse(BaseModel):
    after_sales: List[TenantRiskAfterSaleItem]


class TenantReportExportJobItem(BaseModel):
    export_job_id: int
    report_type: str
    scope_type: str
    status: str
    row_count: int
    download_available: bool
    failure_reason: Optional[str] = None
    expires_at: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class ListTenantReportExportJobsResponse(BaseModel):
    export_jobs: List[TenantReportExportJobItem]


class CreateTenantReportExportJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_type: str = Field(min_length=1, max_length=32)


class TenantSubscriptionResponse(BaseModel):
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
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TenantSubscriptionInvoiceItem(BaseModel):
    out_trade_no: str
    amount: Decimal
    currency: str
    status: str
    paid_at: Optional[str] = None
    created_at: str


class ListTenantSubscriptionInvoicesResponse(BaseModel):
    invoices: List[TenantSubscriptionInvoiceItem]


class CreateTenantSubscriptionRenewalOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    months: int = Field(ge=1, le=24)


class TenantSubscriptionRenewalOrderResponse(BaseModel):
    out_trade_no: str
    amount: Decimal
    currency: str
    months: int
    expires_at: str
    payment_available: bool
    payment_provider: Optional[str] = None
    payment_url: Optional[str] = None
    payment_failure_reason: Optional[str] = None


class TenantSupplierOfferItem(BaseModel):
    supplier_offer_id: int
    product_name: str
    delivery_type: str
    suggested_price: Decimal
    min_sale_price: Optional[Decimal] = None
    supplier_cost: Decimal
    currency: str
    available_count: int
    requires_approval: bool
    status: str


class ListTenantSupplierOffersResponse(BaseModel):
    offers: List[TenantSupplierOfferItem]


class CreateTenantSupplierOfferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int = Field(gt=0)
    suggested_price: Decimal = Field(gt=0)
    min_sale_price: Optional[Decimal] = Field(default=None, ge=0)
    requires_approval: bool = False


class TenantCreatedSupplierOfferItem(BaseModel):
    supplier_offer_id: int
    product_name: str
    delivery_type: str
    suggested_price: Decimal
    min_sale_price: Optional[Decimal] = None
    supplier_cost: Decimal
    currency: str
    requires_approval: bool
    status: str


class UpdateTenantSupplierOfferApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requires_approval: bool


class TenantSupplierOfferApprovalItem(BaseModel):
    supplier_offer_id: int
    requires_approval: bool
    status: str


class TenantSupplierApplicationItem(BaseModel):
    supplier_offer_id: int
    reseller_tenant_id: int
    reseller_store_name: str
    product_name: str
    status: str
    pricing_value: Decimal
    min_sale_price: Optional[Decimal] = None
    currency: str
    updated_at: str


class ListTenantSupplierApplicationsResponse(BaseModel):
    applications: List[TenantSupplierApplicationItem]


class ApproveTenantSupplierApplicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_offer_id: int = Field(gt=0)
    reseller_tenant_id: int = Field(gt=0)


class RejectTenantSupplierApplicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_offer_id: int = Field(gt=0)
    reseller_tenant_id: int = Field(gt=0)
    reason: Optional[str] = Field(default=None, max_length=255)


class SetTenantSupplierRuleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_offer_id: int = Field(gt=0)
    reseller_tenant_id: int = Field(gt=0)
    pricing_value: Decimal = Field(gt=0)
    min_sale_price: Optional[Decimal] = Field(default=None, ge=0)


class TenantSupplyMarketOfferItem(BaseModel):
    supplier_offer_id: int
    product_name: str
    delivery_type: str
    suggested_price: Decimal
    min_sale_price: Optional[Decimal] = None
    currency: str
    available_count: int
    description: Optional[str] = None
    requires_approval: bool
    reseller_rule_status: Optional[str] = None
    can_create_reseller_product: bool
    supplier_cost: Decimal
    effective_min_sale_price: Optional[Decimal] = None


class ListTenantSupplyMarketOffersResponse(BaseModel):
    offers: List[TenantSupplyMarketOfferItem]


class CreateTenantResellerApplicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_offer_id: int = Field(gt=0)


class TenantResellerApplicationItem(BaseModel):
    supplier_offer_id: int
    product_name: str
    status: str
    pricing_value: Decimal
    min_sale_price: Optional[Decimal] = None
    currency: str
    updated_at: str


class ListTenantResellerApplicationsResponse(BaseModel):
    applications: List[TenantResellerApplicationItem]


class CreateTenantResellerProductRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_offer_id: int = Field(gt=0)
    sale_price: Decimal = Field(gt=0)
    display_name: Optional[str] = Field(default=None, max_length=255)


class TenantCreatedResellerProductItem(BaseModel):
    reseller_product_id: int
    supplier_offer_id: int
    display_name: str
    sale_price: Decimal
    currency: str
    status: str


class TenantResellerProductItem(BaseModel):
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


class ListTenantResellerProductsResponse(BaseModel):
    products: List[TenantResellerProductItem]


class AdminOrder(BaseModel):
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


class OrderPaymentDiagnosticItem(BaseModel):
    payment_id: int
    provider: str
    status: str
    amount: Decimal
    currency: str
    has_payment_url: bool
    created_at: str
    paid_at: Optional[str] = None


class OrderPaymentCallbackDiagnosticItem(BaseModel):
    callback_id: int
    provider: str
    process_status: str
    failure_reason: str
    created_at: str
    processed_at: Optional[str] = None


class OrderDeliveryDiagnosticItem(BaseModel):
    delivery_record_id: int
    delivery_type: str
    status: str
    failure_reason: Optional[str] = None
    has_inventory_item: bool
    has_uploaded_file: bool
    has_telegram_chat: bool
    created_at: str
    updated_at: str
    sent_at: Optional[str] = None


class OrderExternalFulfillmentDiagnosticItem(BaseModel):
    expected: bool
    attempt_count: int = 0
    latest_attempt_status: Optional[str] = None
    latest_attempt_source: Optional[str] = None
    latest_attempt_at: Optional[str] = None
    latest_failure_stage: Optional[str] = None
    latest_failure_category: Optional[str] = None
    latest_failure_retryable: Optional[bool] = None
    latest_upstream_status_code: Optional[int] = None
    latest_item_count: int = 0
    latest_delivery_record_linked: bool = False


class OrderTrc20DirectDiagnosticItem(BaseModel):
    expected: bool
    transfer_count: int = 0
    latest_match_status: Optional[str] = None
    latest_confirmations: Optional[int] = None
    latest_matched_at: Optional[str] = None
    latest_amount: Optional[Decimal] = None


class OrderDiagnosticsResponse(BaseModel):
    order_id: int
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
    callback_status_counts: Dict[str, int]
    payments: List[OrderPaymentDiagnosticItem]
    callbacks: List[OrderPaymentCallbackDiagnosticItem]
    delivery: Optional[OrderDeliveryDiagnosticItem] = None
    external_fulfillment: OrderExternalFulfillmentDiagnosticItem
    trc20_direct: OrderTrc20DirectDiagnosticItem


class TenantLedgerBalanceResponse(BaseModel):
    account_type: str
    currency: str
    pending_balance: Decimal
    available_balance: Decimal
    frozen_balance: Decimal


class TenantLedgerBalanceAuditResponse(BaseModel):
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


class TenantWithdrawalItem(BaseModel):
    withdrawal_id: int
    amount: Decimal
    currency: str
    network: str
    address_masked: str
    status: str
    requested_at: str
    payout_reference: Optional[str] = None
    payout_proof_url: Optional[str] = None
    reviewed_at: Optional[str] = None
    completed_at: Optional[str] = None


class ListTenantWithdrawalsResponse(BaseModel):
    withdrawals: List[TenantWithdrawalItem]


class CreateTenantWithdrawalRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    network: str = Field(min_length=2, max_length=32)
    address: str = Field(min_length=8, max_length=256)
    currency: str = Field(default="USDT", min_length=1, max_length=16)


def create_tenant_admin_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1/tenant", tags=["tenant-admin"])
    local_rate_limiter = FixedWindowRateLimiter(
        settings.tenant_admin_rate_limit_per_minute,
        window_seconds=settings.rate_limit_window_seconds,
    )
    redis_rate_limiter = RedisFixedWindowRateLimiter(
        settings.tenant_admin_rate_limit_per_minute,
        window_seconds=settings.rate_limit_window_seconds,
        key_prefix=f"{settings.rate_limit_key_prefix}:tenant-admin",
    )

    async def require_api_key(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
        x_faka_timestamp: Optional[str] = Header(default=None, alias="X-Faka-Timestamp"),
        x_faka_signature: Optional[str] = Header(default=None, alias="X-Faka-Signature"),
        x_forwarded_for: Optional[str] = Header(default=None, alias="X-Forwarded-For"),
    ) -> TenantApiKey:
        try:
            client_ip = resolve_client_ip(
                request.client.host if request.client is not None else None,
                x_forwarded_for,
                settings.trusted_proxy_ips,
            )
            require_ip_allowed(client_ip, settings.tenant_admin_ip_allowlist, "Tenant Admin API")
        except ApiIpAccessError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        plain_key = _extract_api_key(authorization, x_api_key)
        if plain_key is None:
            raise HTTPException(status_code=401, detail="缺少 API Key")
        try:
            async with get_session_factory()() as session:
                api_key = await ApiKeyService(settings).authenticate(session, plain_key)
                if api_key is None:
                    raise HTTPException(status_code=401, detail="API Key 无效")
                try:
                    require_ip_allowed(client_ip, api_key.ip_allowlist_json or [], "Tenant Admin API Key")
                except ApiIpAccessError as exc:
                    raise HTTPException(status_code=403, detail=str(exc))
                try:
                    await hit_rate_limit(
                        redis_client=getattr(request.app.state, "redis", None),
                        redis_limiter=redis_rate_limiter,
                        local_limiter=local_rate_limiter,
                        key=f"{api_key.id}:{request.method}:{request.url.path}",
                    )
                    if settings.tenant_admin_require_signature:
                        if not x_faka_timestamp or not x_faka_signature:
                            raise ApiSignatureError("缺少请求签名")
                        await _verify_signed_request(
                            request=request,
                            api_key=plain_key,
                            timestamp=x_faka_timestamp,
                            signature=x_faka_signature,
                            max_skew_seconds=settings.tenant_admin_signature_max_skew_seconds,
                        )
                except ApiRateLimitError as exc:
                    raise HTTPException(status_code=429, detail=str(exc))
                except ApiSignatureError as exc:
                    raise HTTPException(status_code=401, detail=str(exc))
                await session.commit()
                return api_key
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc))

    def require_scope(required_scope: str):
        async def dependency(api_key: TenantApiKey = Depends(require_api_key)) -> TenantApiKey:
            if not ApiKeyService.has_scope(api_key.scopes_json, required_scope):
                raise HTTPException(status_code=403, detail="API Key 权限不足")
            return api_key

        return dependency

    @router.get("/api-keys", response_model=List[TenantApiKeyItem])
    async def list_api_keys(
        limit: int = 20,
        api_key: TenantApiKey = Depends(require_scope("api_keys:read")),
    ) -> List[TenantApiKeyItem]:
        async with get_session_factory()() as session:
            keys = await ApiKeyService(settings).list_tenant_api_keys(
                session=session,
                tenant_id=api_key.tenant_id,
                limit=limit,
            )
        return [_api_key_response(key) for key in keys]

    @router.post("/api-keys", response_model=CreatedTenantApiKeyResponse)
    async def create_api_key(
        payload: CreateTenantApiKeyRequest,
        api_key: TenantApiKey = Depends(require_scope("api_keys:write")),
    ) -> CreatedTenantApiKeyResponse:
        try:
            requested_scopes = ApiKeyService.normalize_scopes(payload.scopes)
            requested_ip_allowlist = ApiKeyService.normalize_ip_allowlist(payload.ip_allowlist)
            if not ApiKeyService.can_issue_scopes(api_key.scopes_json, requested_scopes):
                raise HTTPException(status_code=403, detail="不能创建超出当前 API Key 权限的 scope")
            if not ApiKeyService.can_issue_ip_allowlist(api_key.ip_allowlist_json, requested_ip_allowlist):
                raise HTTPException(status_code=403, detail="不能创建超出当前 API Key IP 白名单范围的 Key")
            async with get_session_factory()() as session:
                created = await ApiKeyService(settings).create_tenant_api_key(
                    session=session,
                    tenant_id=api_key.tenant_id,
                    name=payload.name,
                    created_by_user_id=None,
                    scopes=requested_scopes,
                    ip_allowlist=requested_ip_allowlist,
                )
                await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return _created_api_key_response(created)

    @router.delete("/api-keys/{api_key_id}", response_model=RevokeTenantApiKeyResponse)
    async def revoke_api_key(
        api_key_id: int,
        api_key: TenantApiKey = Depends(require_scope("api_keys:write")),
    ) -> RevokeTenantApiKeyResponse:
        async with get_session_factory()() as session:
            revoked = await ApiKeyService(settings).revoke_tenant_api_key(
                session=session,
                tenant_id=api_key.tenant_id,
                api_key_id=api_key_id,
                revoked_by_user_id=None,
            )
            await session.commit()
        if not revoked:
            raise HTTPException(status_code=404, detail="API Key 不存在")
        return RevokeTenantApiKeyResponse(api_key_id=api_key_id, revoked=True)

    @router.get("/audit-logs", response_model=ListTenantAuditLogsResponse)
    async def list_audit_logs(
        action: Optional[str] = Query(default=None, max_length=128),
        target_type: Optional[str] = Query(default=None, max_length=64),
        limit: int = Query(default=20, ge=1, le=100),
        api_key: TenantApiKey = Depends(require_scope("audit_logs:read")),
    ) -> ListTenantAuditLogsResponse:
        try:
            async with get_session_factory()() as session:
                logs = await AuditLogService().list_tenant_audit_logs(
                    session=session,
                    tenant_id=api_key.tenant_id,
                    limit=limit,
                    action=action,
                    target_type=target_type,
                )
        except ValueError:
            raise HTTPException(status_code=400, detail="审计日志查询参数无效")
        service = AuditLogService()
        return ListTenantAuditLogsResponse(
            audit_logs=[_tenant_audit_log_response(service, log) for log in logs]
        )

    @router.get("/risk/disputes", response_model=ListTenantRiskDisputesResponse)
    async def list_risk_disputes(
        status: str = Query(default="open", max_length=32),
        limit: int = Query(default=20, ge=1, le=100),
        api_key: TenantApiKey = Depends(require_scope("risk:read")),
    ) -> ListTenantRiskDisputesResponse:
        try:
            normalized_status = _normalize_risk_status(status)
            async with get_session_factory()() as session:
                disputes = await RiskControlService().list_disputes(
                    session=session,
                    tenant_id=api_key.tenant_id,
                    status=normalized_status,
                    limit=limit,
                )
        except ValueError:
            raise HTTPException(status_code=400, detail="风控查询参数无效")
        return ListTenantRiskDisputesResponse(
            disputes=[_risk_dispute_response(dispute) for dispute in disputes]
        )

    @router.get("/risk/after-sales", response_model=ListTenantRiskAfterSalesResponse)
    async def list_risk_after_sales(
        status: str = Query(default="open", max_length=32),
        limit: int = Query(default=20, ge=1, le=100),
        api_key: TenantApiKey = Depends(require_scope("risk:read")),
    ) -> ListTenantRiskAfterSalesResponse:
        try:
            normalized_status = _normalize_risk_status(status)
            async with get_session_factory()() as session:
                after_sales = await RiskControlService().list_after_sales(
                    session=session,
                    tenant_id=api_key.tenant_id,
                    status=normalized_status,
                    limit=limit,
                )
        except ValueError:
            raise HTTPException(status_code=400, detail="风控查询参数无效")
        return ListTenantRiskAfterSalesResponse(
            after_sales=[_risk_after_sale_response(after_sale) for after_sale in after_sales]
        )

    @router.get("/reports/export-jobs", response_model=ListTenantReportExportJobsResponse)
    async def list_report_export_jobs(
        status: Optional[str] = Query(default=None, max_length=32),
        report_type: Optional[str] = Query(default=None, max_length=32),
        limit: int = Query(default=20, ge=1, le=100),
        api_key: TenantApiKey = Depends(require_scope("reports:read")),
    ) -> ListTenantReportExportJobsResponse:
        try:
            normalized_status = _normalize_report_export_status(status)
            normalized_report_type = _normalize_report_export_type(report_type)
            async with get_session_factory()() as session:
                jobs = await ReportExportService().list_export_jobs(
                    session=session,
                    settings=settings,
                    tenant_id=api_key.tenant_id,
                    status=normalized_status,
                    report_type=normalized_report_type,
                    limit=limit,
                )
        except ValueError:
            raise HTTPException(status_code=400, detail="报表任务查询参数无效")
        return ListTenantReportExportJobsResponse(
            export_jobs=[_report_export_job_response(job) for job in jobs]
        )

    @router.post("/reports/export-jobs", response_model=TenantReportExportJobItem)
    async def create_report_export_job(
        payload: CreateTenantReportExportJobRequest,
        api_key: TenantApiKey = Depends(require_scope("reports:write")),
    ) -> TenantReportExportJobItem:
        try:
            report_type = _normalize_required_report_export_type(payload.report_type)
            async with get_session_factory()() as session:
                job = await ReportExportService().create_export_job(
                    session=session,
                    settings=settings,
                    report_type=report_type,
                    actor_user_id=None,
                    tenant_id=api_key.tenant_id,
                    scope_type="tenant",
                )
                await session.commit()
        except ValueError:
            raise HTTPException(status_code=400, detail="报表任务参数无效")
        return _report_export_job_response(job)

    @router.get("/subscription/status", response_model=TenantSubscriptionResponse)
    async def get_subscription_status(
        api_key: TenantApiKey = Depends(require_scope("subscriptions:read")),
    ) -> TenantSubscriptionResponse:
        async with get_session_factory()() as session:
            summary = await SubscriptionService().get_tenant_subscription_summary(
                session,
                tenant_id=api_key.tenant_id,
            )
        if summary is None:
            raise HTTPException(status_code=404, detail="订阅不存在")
        return _tenant_subscription_response(summary)

    @router.get("/subscription/invoices", response_model=ListTenantSubscriptionInvoicesResponse)
    async def list_subscription_invoices(
        status: Optional[str] = Query(default=None, max_length=32),
        limit: int = Query(default=20, ge=1, le=100),
        api_key: TenantApiKey = Depends(require_scope("subscriptions:read")),
    ) -> ListTenantSubscriptionInvoicesResponse:
        try:
            async with get_session_factory()() as session:
                invoices = await SubscriptionService().list_tenant_subscription_invoices(
                    session,
                    tenant_id=api_key.tenant_id,
                    status=status,
                    limit=limit,
                )
        except ValueError:
            raise HTTPException(status_code=400, detail="订阅账单查询参数无效")
        return ListTenantSubscriptionInvoicesResponse(
            invoices=[_tenant_subscription_invoice_response(invoice) for invoice in invoices]
        )

    @router.post("/subscription/renewal-orders", response_model=TenantSubscriptionRenewalOrderResponse)
    async def create_subscription_renewal_order(
        payload: CreateTenantSubscriptionRenewalOrderRequest,
        api_key: TenantApiKey = Depends(require_scope("subscriptions:write")),
    ) -> TenantSubscriptionRenewalOrderResponse:
        try:
            async with get_session_factory()() as session:
                renewal_order = await SubscriptionService().create_renewal_order(
                    session=session,
                    tenant_id=api_key.tenant_id,
                    buyer_telegram_user_id=0,
                    months=payload.months,
                    monthly_price=settings.subscription_monthly_price,
                )
                await session.commit()
        except ValueError:
            raise HTTPException(status_code=400, detail="订阅续费参数无效")

        payment_available = False
        payment_provider: Optional[str] = None
        payment_url: Optional[str] = None
        payment_failure_reason: Optional[str] = None
        try:
            async with get_session_factory()() as session:
                payment = await PaymentService(settings).create_payment_for_order(
                    session,
                    renewal_order.order_id,
                )
                await session.commit()
            payment_available = True
            payment_provider = payment.provider
            payment_url = payment.payment_url
        except PaymentUnavailableError:
            payment_failure_reason = "支付配置暂不可用"
        except Exception:
            payment_failure_reason = "支付链接创建失败"

        return TenantSubscriptionRenewalOrderResponse(
            out_trade_no=renewal_order.out_trade_no,
            amount=renewal_order.amount,
            currency=renewal_order.currency,
            months=renewal_order.months,
            expires_at=renewal_order.expires_at.isoformat(),
            payment_available=payment_available,
            payment_provider=payment_provider,
            payment_url=payment_url,
            payment_failure_reason=payment_failure_reason,
        )

    @router.get("/supply/supplier-offers", response_model=ListTenantSupplierOffersResponse)
    async def list_supplier_offers(
        limit: int = Query(default=20, ge=1, le=100),
        api_key: TenantApiKey = Depends(require_scope("supply:read")),
    ) -> ListTenantSupplierOffersResponse:
        async with get_session_factory()() as session:
            await _require_tenant_admin_feature(session, api_key.tenant_id, "supplier")
            offers = await SupplyService().list_supplier_offers(
                session=session,
                supplier_tenant_id=api_key.tenant_id,
                limit=limit,
            )
        return ListTenantSupplierOffersResponse(
            offers=[_tenant_supplier_offer_response(offer) for offer in offers]
        )

    @router.post("/supply/supplier-offers", response_model=TenantCreatedSupplierOfferItem)
    async def create_supplier_offer(
        payload: CreateTenantSupplierOfferRequest,
        api_key: TenantApiKey = Depends(require_scope("supply:write")),
    ) -> TenantCreatedSupplierOfferItem:
        try:
            async with get_session_factory()() as session:
                await _require_tenant_admin_feature(session, api_key.tenant_id, "supplier")
                offer = await SupplyService().create_supplier_offer(
                    session=session,
                    supplier_tenant_id=api_key.tenant_id,
                    product_id=payload.product_id,
                    suggested_price=payload.suggested_price,
                    min_sale_price=payload.min_sale_price,
                    requires_approval=payload.requires_approval,
                )
                await session.commit()
        except ValueError:
            raise HTTPException(status_code=400, detail="供货商品参数无效")
        return _created_supplier_offer_response(offer)

    @router.patch("/supply/supplier-offers/{supplier_offer_id}/approval", response_model=TenantSupplierOfferApprovalItem)
    async def update_supplier_offer_approval(
        supplier_offer_id: int,
        payload: UpdateTenantSupplierOfferApprovalRequest,
        api_key: TenantApiKey = Depends(require_scope("supply:write")),
    ) -> TenantSupplierOfferApprovalItem:
        try:
            async with get_session_factory()() as session:
                await _require_tenant_admin_feature(session, api_key.tenant_id, "supplier")
                setting = await SupplyService().set_supplier_offer_approval(
                    session=session,
                    supplier_tenant_id=api_key.tenant_id,
                    supplier_offer_id=supplier_offer_id,
                    requires_approval=payload.requires_approval,
                    actor_user_id=None,
                )
                await session.commit()
        except ValueError:
            raise HTTPException(status_code=400, detail="供货审批参数无效")
        return _supplier_offer_approval_response(setting)

    @router.get("/supply/supplier-applications", response_model=ListTenantSupplierApplicationsResponse)
    async def list_supplier_applications(
        limit: int = Query(default=20, ge=1, le=100),
        api_key: TenantApiKey = Depends(require_scope("supply:read")),
    ) -> ListTenantSupplierApplicationsResponse:
        async with get_session_factory()() as session:
            await _require_tenant_admin_feature(session, api_key.tenant_id, "supplier")
            applications = await SupplyService().list_reseller_applications(
                session=session,
                supplier_tenant_id=api_key.tenant_id,
                limit=limit,
            )
        return ListTenantSupplierApplicationsResponse(
            applications=[_supplier_application_response(application) for application in applications]
        )

    @router.post("/supply/supplier-applications/approve", response_model=TenantSupplierApplicationItem)
    async def approve_supplier_application(
        payload: ApproveTenantSupplierApplicationRequest,
        api_key: TenantApiKey = Depends(require_scope("supply:write")),
    ) -> TenantSupplierApplicationItem:
        try:
            async with get_session_factory()() as session:
                await _require_tenant_admin_feature(session, api_key.tenant_id, "supplier")
                application = await SupplyService().approve_reseller_application(
                    session=session,
                    supplier_tenant_id=api_key.tenant_id,
                    supplier_offer_id=payload.supplier_offer_id,
                    reseller_tenant_id=payload.reseller_tenant_id,
                    actor_user_id=None,
                )
                await session.commit()
        except ValueError:
            raise HTTPException(status_code=400, detail="代理审批参数无效")
        return _supplier_application_response(application)

    @router.post("/supply/supplier-applications/reject", response_model=TenantSupplierApplicationItem)
    async def reject_supplier_application(
        payload: RejectTenantSupplierApplicationRequest,
        api_key: TenantApiKey = Depends(require_scope("supply:write")),
    ) -> TenantSupplierApplicationItem:
        try:
            async with get_session_factory()() as session:
                await _require_tenant_admin_feature(session, api_key.tenant_id, "supplier")
                application = await SupplyService().reject_reseller_application(
                    session=session,
                    supplier_tenant_id=api_key.tenant_id,
                    supplier_offer_id=payload.supplier_offer_id,
                    reseller_tenant_id=payload.reseller_tenant_id,
                    actor_user_id=None,
                    reason=payload.reason,
                )
                await session.commit()
        except ValueError:
            raise HTTPException(status_code=400, detail="代理拒绝参数无效")
        return _supplier_application_response(application)

    @router.post("/supply/supplier-rules", response_model=TenantSupplierApplicationItem)
    async def set_supplier_reseller_rule(
        payload: SetTenantSupplierRuleRequest,
        api_key: TenantApiKey = Depends(require_scope("supply:write")),
    ) -> TenantSupplierApplicationItem:
        try:
            async with get_session_factory()() as session:
                await _require_tenant_admin_feature(session, api_key.tenant_id, "supplier")
                application = await SupplyService().set_existing_reseller_rule(
                    session=session,
                    supplier_tenant_id=api_key.tenant_id,
                    supplier_offer_id=payload.supplier_offer_id,
                    reseller_tenant_id=payload.reseller_tenant_id,
                    actor_user_id=None,
                    pricing_value=payload.pricing_value,
                    min_sale_price=payload.min_sale_price,
                )
                await session.commit()
        except ValueError:
            raise HTTPException(status_code=400, detail="代理规则参数无效")
        return _supplier_application_response(application)

    @router.get("/supply/market-offers", response_model=ListTenantSupplyMarketOffersResponse)
    async def list_supply_market(
        limit: int = Query(default=20, ge=1, le=100),
        api_key: TenantApiKey = Depends(require_scope("supply:read")),
    ) -> ListTenantSupplyMarketOffersResponse:
        async with get_session_factory()() as session:
            await _require_tenant_admin_feature(session, api_key.tenant_id, "reseller")
            offers = await SupplyService().list_market_offers(
                session=session,
                reseller_tenant_id=api_key.tenant_id,
                limit=limit,
            )
        return ListTenantSupplyMarketOffersResponse(
            offers=[_supply_market_offer_response(offer) for offer in offers]
        )

    @router.get("/supply/applications", response_model=ListTenantResellerApplicationsResponse)
    async def list_my_reseller_applications(
        limit: int = Query(default=20, ge=1, le=100),
        api_key: TenantApiKey = Depends(require_scope("supply:read")),
    ) -> ListTenantResellerApplicationsResponse:
        async with get_session_factory()() as session:
            await _require_tenant_admin_feature(session, api_key.tenant_id, "reseller")
            applications = await SupplyService().list_my_reseller_applications(
                session=session,
                reseller_tenant_id=api_key.tenant_id,
                limit=limit,
            )
        return ListTenantResellerApplicationsResponse(
            applications=[_reseller_application_response(application) for application in applications]
        )

    @router.post("/supply/applications", response_model=TenantResellerApplicationItem)
    async def create_reseller_application(
        payload: CreateTenantResellerApplicationRequest,
        api_key: TenantApiKey = Depends(require_scope("supply:write")),
    ) -> TenantResellerApplicationItem:
        try:
            async with get_session_factory()() as session:
                await _require_tenant_admin_feature(session, api_key.tenant_id, "reseller")
                application = await SupplyService().apply_reseller(
                    session=session,
                    reseller_tenant_id=api_key.tenant_id,
                    supplier_offer_id=payload.supplier_offer_id,
                    requested_by_user_id=None,
                )
                await session.commit()
        except ValueError:
            raise HTTPException(status_code=400, detail="供货代理申请参数无效")
        return _reseller_application_response(application)

    @router.get("/supply/reseller-products", response_model=ListTenantResellerProductsResponse)
    async def list_reseller_products(
        limit: int = Query(default=20, ge=1, le=100),
        api_key: TenantApiKey = Depends(require_scope("supply:read")),
    ) -> ListTenantResellerProductsResponse:
        async with get_session_factory()() as session:
            await _require_tenant_admin_feature(session, api_key.tenant_id, "reseller")
            products = await SupplyService().list_reseller_products(
                session=session,
                reseller_tenant_id=api_key.tenant_id,
                limit=limit,
            )
        return ListTenantResellerProductsResponse(
            products=[_reseller_product_response(product) for product in products]
        )

    @router.post("/supply/reseller-products", response_model=TenantCreatedResellerProductItem)
    async def create_reseller_product(
        payload: CreateTenantResellerProductRequest,
        api_key: TenantApiKey = Depends(require_scope("supply:write")),
    ) -> TenantCreatedResellerProductItem:
        try:
            async with get_session_factory()() as session:
                await _require_tenant_admin_feature(session, api_key.tenant_id, "reseller")
                product = await SupplyService().create_reseller_product(
                    session=session,
                    reseller_tenant_id=api_key.tenant_id,
                    supplier_offer_id=payload.supplier_offer_id,
                    sale_price=payload.sale_price,
                    display_name=payload.display_name,
                )
                await session.commit()
        except ValueError:
            raise HTTPException(status_code=400, detail="代理商品参数无效")
        return _created_reseller_product_response(product)

    @router.get("/products", response_model=List[AdminProduct])
    async def list_products(api_key: TenantApiKey = Depends(require_scope("products:read"))) -> List[AdminProduct]:
        async with get_session_factory()() as session:
            products = await ProductRepository().list_products(session, api_key.tenant_id)
        return [
            _admin_product_response(product, variant, available_count)
            for product, variant, available_count in products
        ]

    @router.post("/products", response_model=AdminProduct)
    async def create_product(
        payload: CreateAdminProductRequest,
        api_key: TenantApiKey = Depends(require_scope("products:write")),
    ) -> AdminProduct:
        try:
            async with get_session_factory()() as session:
                product = await ProductRepository().create_self_product(
                    session=session,
                    tenant_id=api_key.tenant_id,
                    name=payload.name,
                    price=payload.price,
                    delivery_type=payload.delivery_type,
                    description=payload.description,
                    category=payload.category,
                )
                await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return _admin_product_response(product, None, 0)

    @router.patch("/products/{product_id}/metadata", response_model=AdminProduct)
    async def update_product_metadata(
        product_id: int,
        payload: UpdateProductMetadataRequest,
        api_key: TenantApiKey = Depends(require_scope("products:write")),
    ) -> AdminProduct:
        requested_fields = payload.model_fields_set
        if "category" not in requested_fields and "sort_order" not in requested_fields:
            raise HTTPException(status_code=400, detail="商品元数据参数无效")

        repo = ProductRepository()
        try:
            async with get_session_factory()() as session:
                if "category" in requested_fields:
                    changed = await repo.set_product_category(
                        session=session,
                        tenant_id=api_key.tenant_id,
                        product_id=product_id,
                        category=payload.category,
                    )
                    if not changed:
                        raise HTTPException(status_code=404, detail="商品不存在或无权限")
                if "sort_order" in requested_fields:
                    if payload.sort_order is None:
                        raise ValueError("排序值必须是整数")
                    changed = await repo.set_product_sort_order(
                        session=session,
                        tenant_id=api_key.tenant_id,
                        product_id=product_id,
                        sort_order=payload.sort_order,
                    )
                    if not changed:
                        raise HTTPException(status_code=404, detail="商品不存在或无权限")

                product, variant = await repo.get_product_with_default_variant(
                    session,
                    tenant_id=api_key.tenant_id,
                    product_id=product_id,
                )
                if product is None:
                    raise HTTPException(status_code=404, detail="商品不存在或无权限")
                inventory = await repo.inventory_summary(
                    session,
                    tenant_id=api_key.tenant_id,
                    product_id=product_id,
                )
                await session.commit()
        except HTTPException:
            raise
        except ValueError:
            raise HTTPException(status_code=400, detail="商品元数据参数无效")

        available_count = int((inventory.get(product.id) or {}).get("available", 0))
        return _admin_product_response(product, variant, available_count)

    @router.post("/products/sync", response_model=SyncProductsResponse)
    async def sync_products(
        payload: SyncProductsRequest,
        api_key: TenantApiKey = Depends(require_scope("products:write")),
    ) -> SyncProductsResponse:
        try:
            _ensure_unique_sync_product_ids(payload.products)
            _ensure_unique_sync_external_refs(payload.products)
            _validate_sync_products(payload.products)
            repo = ProductRepository()
            synced: List[SyncedProductItem] = []
            created_count = 0
            updated_count = 0
            async with get_session_factory()() as session:
                for item in payload.products:
                    external_source, source_key, external_id = _sync_external_ref(item)
                    if item.product_id is None and external_source is not None and external_id is not None:
                        product, _ = await repo.get_self_product_by_external_ref(
                            session,
                            tenant_id=api_key.tenant_id,
                            external_source=external_source,
                            source_key=source_key,
                            external_id=external_id,
                        )
                        if product is None:
                            product = await repo.create_self_product(
                                session=session,
                                tenant_id=api_key.tenant_id,
                                name=item.name,
                                price=item.price,
                                delivery_type=item.delivery_type,
                                description=item.description,
                                category=item.category,
                                external_source=external_source,
                                source_key=source_key,
                                external_id=external_id,
                            )
                            if item.status is not None and item.status != "draft":
                                await repo.set_product_status(session, api_key.tenant_id, product.id, item.status)
                            action = "created"
                            created_count += 1
                        else:
                            product = await repo.update_self_product(
                                session=session,
                                tenant_id=api_key.tenant_id,
                                product_id=product.id,
                                name=item.name,
                                price=item.price,
                                description=item.description,
                                category=item.category,
                                status=item.status,
                                delivery_type=item.delivery_type,
                                external_source=external_source,
                                source_key=source_key,
                                external_id=external_id,
                            )
                            action = "updated"
                            updated_count += 1
                    elif item.product_id is None:
                        product = await repo.create_self_product(
                            session=session,
                            tenant_id=api_key.tenant_id,
                            name=item.name,
                            price=item.price,
                            delivery_type=item.delivery_type,
                            description=item.description,
                            category=item.category,
                            external_source=external_source,
                            source_key=source_key,
                            external_id=external_id,
                        )
                        if item.status is not None and item.status != "draft":
                            await repo.set_product_status(session, api_key.tenant_id, product.id, item.status)
                        action = "created"
                        created_count += 1
                    else:
                        product = await repo.update_self_product(
                            session=session,
                            tenant_id=api_key.tenant_id,
                            product_id=item.product_id,
                            name=item.name,
                            price=item.price,
                            description=item.description,
                            category=item.category,
                            status=item.status,
                            delivery_type=item.delivery_type,
                            external_source=external_source,
                            source_key=source_key,
                            external_id=external_id,
                        )
                        action = "updated"
                        updated_count += 1
                    synced.append(
                        SyncedProductItem(
                            product_id=product.id,
                            external_source=product.external_source,
                            source_key=product.source_key,
                            external_id=product.external_id,
                            action=action,
                            status=product.status,
                        )
                    )
                await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return SyncProductsResponse(created_count=created_count, updated_count=updated_count, products=synced)

    @router.get("/external-sources", response_model=ListExternalSourceProvidersResponse)
    async def list_external_sources(
        api_key: TenantApiKey = Depends(require_scope("products:read")),
    ) -> ListExternalSourceProvidersResponse:
        return ListExternalSourceProvidersResponse(
            providers=[
                _external_source_provider_response(summary)
                for summary in list_provider_summaries()
            ]
        )

    @router.get("/external-source-connections", response_model=ListExternalSourceConnectionsResponse)
    async def list_external_source_connections(
        provider_name: Optional[str] = None,
        api_key: TenantApiKey = Depends(require_scope("external_sources:read")),
    ) -> ListExternalSourceConnectionsResponse:
        try:
            async with get_session_factory()() as session:
                connections = await ExternalSourceConnectionService().list_connections(
                    session=session,
                    tenant_id=api_key.tenant_id,
                    provider_name=provider_name,
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return ListExternalSourceConnectionsResponse(
            connections=[_external_source_connection_response(connection) for connection in connections]
        )

    @router.post("/external-source-connections", response_model=ExternalSourceConnectionItem)
    async def create_external_source_connection(
        payload: CreateExternalSourceConnectionRequest,
        api_key: TenantApiKey = Depends(require_scope("external_sources:write")),
    ) -> ExternalSourceConnectionItem:
        try:
            async with get_session_factory()() as session:
                connection = await ExternalSourceConnectionService().create_connection(
                    session=session,
                    tenant_id=api_key.tenant_id,
                    provider_name=payload.provider_name,
                    source_key=payload.source_key,
                    display_name=payload.display_name,
                    credentials=payload.credentials,
                    settings=settings,
                    created_by_user_id=None,
                )
                await session.commit()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return _external_source_connection_response(connection)

    @router.get("/external-source-connections/{connection_id}", response_model=ExternalSourceConnectionItem)
    async def get_external_source_connection(
        connection_id: int,
        api_key: TenantApiKey = Depends(require_scope("external_sources:read")),
    ) -> ExternalSourceConnectionItem:
        async with get_session_factory()() as session:
            connection = await ExternalSourceConnectionService().get_connection(
                session=session,
                tenant_id=api_key.tenant_id,
                connection_id=connection_id,
            )
        if connection is None:
            raise HTTPException(status_code=404, detail="外部源连接不存在")
        return _external_source_connection_response(connection)

    @router.delete(
        "/external-source-connections/{connection_id}",
        response_model=DisableExternalSourceConnectionResponse,
    )
    async def disable_external_source_connection(
        connection_id: int,
        api_key: TenantApiKey = Depends(require_scope("external_sources:write")),
    ) -> DisableExternalSourceConnectionResponse:
        async with get_session_factory()() as session:
            disabled = await ExternalSourceConnectionService().disable_connection(
                session=session,
                tenant_id=api_key.tenant_id,
                connection_id=connection_id,
            )
            await session.commit()
        if not disabled:
            raise HTTPException(status_code=404, detail="外部源连接不存在")
        return DisableExternalSourceConnectionResponse(connection_id=connection_id, disabled=True)

    @router.get(
        "/external-fulfillment/attempts",
        response_model=ListExternalFulfillmentAttemptsResponse,
    )
    async def list_external_fulfillment_attempts(
        out_trade_no: Optional[str] = None,
        provider_name: Optional[str] = None,
        source_key: Optional[str] = None,
        external_order_id: Optional[str] = None,
        attempt_source: Optional[str] = None,
        status: Optional[str] = None,
        failure_stage: Optional[str] = None,
        failure_category: Optional[str] = None,
        failure_retryable: Optional[bool] = None,
        limit: int = Query(default=20, ge=1, le=100),
        api_key: TenantApiKey = Depends(require_scope("external_sources:read")),
    ) -> ListExternalFulfillmentAttemptsResponse:
        try:
            async with get_session_factory()() as session:
                attempts = await ExternalFulfillmentAttemptLogService().list_attempts(
                    session=session,
                    tenant_id=api_key.tenant_id,
                    out_trade_no=out_trade_no,
                    provider_name=provider_name,
                    source_key=source_key,
                    external_order_id=external_order_id,
                    attempt_source=attempt_source,
                    status=status,
                    failure_stage=failure_stage,
                    failure_category=failure_category,
                    failure_retryable=failure_retryable,
                    limit=limit,
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="外部履约尝试查询参数无效") from exc
        return ListExternalFulfillmentAttemptsResponse(
            attempts=[_external_fulfillment_attempt_response(attempt) for attempt in attempts]
        )

    @router.get(
        "/external-fulfillment/failures",
        response_model=ListExternalFulfillmentFailuresResponse,
    )
    async def list_external_fulfillment_failures(
        out_trade_no: Optional[str] = None,
        provider_name: Optional[str] = None,
        source_key: Optional[str] = None,
        failure_stage: Optional[str] = None,
        failure_category: Optional[str] = None,
        failure_retryable: Optional[bool] = None,
        limit: int = Query(default=20, ge=1, le=100),
        api_key: TenantApiKey = Depends(require_scope("external_sources:read")),
    ) -> ListExternalFulfillmentFailuresResponse:
        try:
            async with get_session_factory()() as session:
                failures = await ExternalFulfillmentFailureLogService().list_failures(
                    session=session,
                    tenant_id=api_key.tenant_id,
                    out_trade_no=out_trade_no,
                    provider_name=provider_name,
                    source_key=source_key,
                    failure_stage=failure_stage,
                    failure_category=failure_category,
                    failure_retryable=failure_retryable,
                    limit=limit,
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return ListExternalFulfillmentFailuresResponse(
            failures=[_external_fulfillment_failure_response(failure) for failure in failures]
        )

    @router.get("/payments/epusdt/config", response_model=TenantEpusdtConfigResponse)
    async def get_epusdt_config(
        api_key: TenantApiKey = Depends(require_scope("payments:read")),
    ) -> TenantEpusdtConfigResponse:
        try:
            async with get_session_factory()() as session:
                status = await PaymentConfigService().get_tenant_epusdt_status(
                    session,
                    settings,
                    api_key.tenant_id,
                )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="支付配置暂不可用") from exc
        except ValueError:
            raise HTTPException(status_code=400, detail="支付配置读取失败")
        return _epusdt_config_response(status)

    @router.put("/payments/epusdt/config", response_model=TenantEpusdtConfigResponse)
    async def update_epusdt_config(
        payload: UpdateTenantEpusdtConfigRequest,
        api_key: TenantApiKey = Depends(require_scope("payments:write")),
    ) -> TenantEpusdtConfigResponse:
        try:
            base_url = _normalize_epusdt_base_url(payload.base_url)
            pid = _normalize_payment_config_text(payload.pid, "pid", max_length=128)
            secret_key = _normalize_payment_config_text(payload.secret_key, "secret_key", max_length=512)
            token = _normalize_optional_payment_config_text(payload.token, "token", max_length=32)
            network = _normalize_optional_payment_config_text(payload.network, "network", max_length=32)
            async with get_session_factory()() as session:
                await PaymentConfigService().upsert_tenant_epusdt_config(
                    session=session,
                    settings=settings,
                    tenant_id=api_key.tenant_id,
                    base_url=base_url,
                    pid=pid,
                    secret_key=secret_key,
                    token=token,
                    network=network,
                )
                await session.commit()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="支付配置暂不可用") from exc
        except ValueError:
            raise HTTPException(status_code=400, detail="支付配置参数无效")
        return TenantEpusdtConfigResponse(
            provider=EPUSDT_PROVIDER,
            enabled=True,
            scope_type="tenant",
            base_url=base_url.rstrip("/"),
            pid_masked=_mask_config_value(pid),
            asset=token or settings.epusdt_token,
            network=network or settings.epusdt_network,
            key_configured=True,
        )

    @router.delete("/payments/epusdt/config", response_model=DisableTenantEpusdtConfigResponse)
    async def disable_epusdt_config(
        api_key: TenantApiKey = Depends(require_scope("payments:write")),
    ) -> DisableTenantEpusdtConfigResponse:
        async with get_session_factory()() as session:
            disabled = await PaymentConfigService().disable_tenant_epusdt_config(session, api_key.tenant_id)
            await session.commit()
        if not disabled:
            raise HTTPException(status_code=404, detail="租户 epusdt 配置不存在")
        return DisableTenantEpusdtConfigResponse(provider=EPUSDT_PROVIDER, disabled=True)

    @router.get("/payments/providers", response_model=ListTenantPaymentProvidersResponse)
    async def list_payment_providers(
        api_key: TenantApiKey = Depends(require_scope("payments:read")),
    ) -> ListTenantPaymentProvidersResponse:
        summaries = await PaymentConfigService().list_tenant_payment_provider_summaries()
        return ListTenantPaymentProvidersResponse(
            providers=[_payment_provider_summary_response(summary) for summary in summaries]
        )

    @router.get("/payments/callback-failures", response_model=ListTenantPaymentCallbackFailuresResponse)
    async def list_payment_callback_failures(
        provider: Optional[str] = None,
        process_status: str = "failed",
        out_trade_no: Optional[str] = None,
        limit: int = Query(default=20, ge=1, le=100),
        api_key: TenantApiKey = Depends(require_scope("payments:read")),
    ) -> ListTenantPaymentCallbackFailuresResponse:
        try:
            async with get_session_factory()() as session:
                failures = await PaymentCallbackFailureLogService().list_failures(
                    session,
                    tenant_id=api_key.tenant_id,
                    provider=provider,
                    process_status=process_status,
                    out_trade_no=out_trade_no,
                    limit=limit,
                )
        except ValueError:
            raise HTTPException(status_code=400, detail="支付回调查询参数无效")
        return ListTenantPaymentCallbackFailuresResponse(
            failures=[_payment_callback_failure_response(failure) for failure in failures]
        )

    @router.get("/payments/callback-rejections", response_model=ListTenantPaymentCallbackRejectionsResponse)
    async def list_payment_callback_rejections(
        provider: Optional[str] = None,
        reason_category: Optional[str] = None,
        out_trade_no: Optional[str] = None,
        limit: int = Query(default=20, ge=1, le=100),
        api_key: TenantApiKey = Depends(require_scope("payments:read")),
    ) -> ListTenantPaymentCallbackRejectionsResponse:
        try:
            async with get_session_factory()() as session:
                rejections = await PaymentCallbackRejectionAuditService().list_rejections(
                    session,
                    tenant_id=api_key.tenant_id,
                    provider=provider,
                    reason_category=reason_category,
                    out_trade_no=out_trade_no,
                    limit=limit,
                )
        except ValueError:
            raise HTTPException(status_code=400, detail="支付回调查询参数无效")
        return ListTenantPaymentCallbackRejectionsResponse(
            rejections=[_payment_callback_rejection_response(rejection) for rejection in rejections]
        )

    @router.get(
        "/payments/trc20-direct/transfers",
        response_model=TenantTrc20DirectTransferListResponse,
    )
    async def list_trc20_direct_transfers(
        match_status: Optional[str] = Query(default=None, max_length=32),
        out_trade_no: Optional[str] = Query(default=None, max_length=96),
        tx_hash: Optional[str] = Query(default=None, max_length=66),
        limit: int = Query(default=20, ge=1, le=100),
        api_key: TenantApiKey = Depends(require_scope("payments:read")),
    ) -> TenantTrc20DirectTransferListResponse:
        try:
            async with get_session_factory()() as session:
                transfers = await Trc20DirectTransferObservationService().list_tenant_transfers(
                    session,
                    tenant_id=api_key.tenant_id,
                    match_status=match_status,
                    out_trade_no=out_trade_no,
                    tx_hash=tx_hash,
                    limit=limit,
                )
        except ValueError:
            raise HTTPException(status_code=400, detail="TRC20 直付转账查询参数无效")
        return TenantTrc20DirectTransferListResponse(
            transfers=[_trc20_direct_transfer_response(transfer) for transfer in transfers]
        )

    @router.get("/payments/{provider_name}/config", response_model=TenantPaymentProviderConfigResponse)
    async def get_payment_provider_config(
        provider_name: str,
        api_key: TenantApiKey = Depends(require_scope("payments:read")),
    ) -> TenantPaymentProviderConfigResponse:
        try:
            provider = normalize_payment_provider(provider_name)
            async with get_session_factory()() as session:
                status = await PaymentConfigService().get_tenant_payment_config_status(
                    session,
                    settings,
                    api_key.tenant_id,
                    provider,
                )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="支付配置暂不可用") from exc
        except ValueError:
            raise HTTPException(status_code=400, detail="支付配置参数无效")
        return _payment_provider_config_response(status)

    @router.put("/payments/{provider_name}/config", response_model=TenantPaymentProviderConfigResponse)
    async def update_payment_provider_config(
        provider_name: str,
        payload: UpdateTenantPaymentProviderConfigRequest,
        api_key: TenantApiKey = Depends(require_scope("payments:write")),
    ) -> TenantPaymentProviderConfigResponse:
        try:
            provider = normalize_payment_provider(provider_name)
            payload_data = payload.model_dump(exclude_none=True)
            validate_payment_provider_config_payload(provider, payload_data)
            async with get_session_factory()() as session:
                status = await PaymentConfigService().upsert_tenant_payment_config(
                    session=session,
                    settings=settings,
                    tenant_id=api_key.tenant_id,
                    provider=provider,
                    config_payload=payload_data,
                )
                await session.commit()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="支付配置暂不可用") from exc
        except ValueError:
            raise HTTPException(status_code=400, detail="支付配置参数无效")
        return _payment_provider_config_response(status)

    @router.delete("/payments/{provider_name}/config", response_model=DisableTenantPaymentProviderConfigResponse)
    async def disable_payment_provider_config(
        provider_name: str,
        api_key: TenantApiKey = Depends(require_scope("payments:write")),
    ) -> DisableTenantPaymentProviderConfigResponse:
        try:
            provider = normalize_payment_provider(provider_name)
        except ValueError:
            raise HTTPException(status_code=400, detail="支付配置参数无效")
        async with get_session_factory()() as session:
            disabled = await PaymentConfigService().disable_tenant_payment_config(session, api_key.tenant_id, provider)
            await session.commit()
        if not disabled:
            raise HTTPException(status_code=404, detail="租户支付配置不存在")
        return DisableTenantPaymentProviderConfigResponse(provider=provider, disabled=True)

    @router.get("/finance/balance", response_model=TenantLedgerBalanceResponse)
    async def finance_balance(
        api_key: TenantApiKey = Depends(require_scope("finance:read")),
    ) -> TenantLedgerBalanceResponse:
        async with get_session_factory()() as session:
            balance = await LedgerService().get_balance(session, api_key.tenant_id)
            await session.commit()
        return _ledger_balance_response(balance)

    @router.get("/finance/ledger/audit", response_model=TenantLedgerBalanceAuditResponse)
    async def finance_ledger_audit(
        api_key: TenantApiKey = Depends(require_scope("finance:read")),
    ) -> TenantLedgerBalanceAuditResponse:
        async with get_session_factory()() as session:
            audit = await LedgerService().audit_account_balance(session, api_key.tenant_id)
        return _ledger_balance_audit_response(audit)

    @router.get("/finance/withdrawals", response_model=ListTenantWithdrawalsResponse)
    async def list_withdrawals(
        limit: int = 20,
        api_key: TenantApiKey = Depends(require_scope("finance:read")),
    ) -> ListTenantWithdrawalsResponse:
        normalized_limit = min(max(limit, 1), 100)
        async with get_session_factory()() as session:
            withdrawals = await LedgerService().list_withdrawals(
                session,
                tenant_id=api_key.tenant_id,
                limit=normalized_limit,
            )
        return ListTenantWithdrawalsResponse(
            withdrawals=[_withdrawal_response(withdrawal) for withdrawal in withdrawals]
        )

    @router.get("/finance/withdrawals/{withdrawal_id}", response_model=TenantWithdrawalItem)
    async def get_withdrawal(
        withdrawal_id: int,
        api_key: TenantApiKey = Depends(require_scope("finance:read")),
    ) -> TenantWithdrawalItem:
        async with get_session_factory()() as session:
            withdrawal = await LedgerService().get_withdrawal(
                session,
                tenant_id=api_key.tenant_id,
                withdrawal_id=withdrawal_id,
            )
        if withdrawal is None:
            raise HTTPException(status_code=404, detail="提现申请不存在")
        return _withdrawal_response(withdrawal)

    @router.post("/finance/withdrawals", response_model=TenantWithdrawalItem)
    async def create_withdrawal(
        payload: CreateTenantWithdrawalRequest,
        api_key: TenantApiKey = Depends(require_scope("finance:write")),
    ) -> TenantWithdrawalItem:
        try:
            network = _normalize_finance_text(payload.network, "提现网络", max_length=32).upper()
            address = _normalize_finance_text(payload.address, "提现地址", max_length=256)
            currency = _normalize_finance_text(payload.currency, "提现币种", max_length=16).upper()
            _validate_withdrawal_amount(payload.amount)
            async with get_session_factory()() as session:
                withdrawal = await LedgerService().create_withdrawal_request(
                    session=session,
                    tenant_id=api_key.tenant_id,
                    amount=payload.amount,
                    network=network,
                    address=address,
                    currency=currency,
                    actor_user_id=None,
                )
                await session.commit()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="提现服务暂不可用") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_finance_error_detail(exc))
        return _withdrawal_response(
            WithdrawalSummary(
                withdrawal_id=withdrawal.id,
                tenant_id=withdrawal.tenant_id,
                amount=withdrawal.amount,
                currency=withdrawal.currency,
                network=withdrawal.network,
                address=withdrawal.address,
                status=withdrawal.status,
                requested_at=withdrawal.requested_at,
                payout_reference=withdrawal.payout_reference,
                payout_proof_url=withdrawal.payout_proof_url,
            )
        )

    @router.post(
        "/external-sources/{provider_name}/catalog/sync",
        response_model=SyncExternalCatalogResponse,
    )
    async def sync_external_catalog(
        provider_name: str,
        payload: SyncExternalCatalogRequest,
        api_key: TenantApiKey = Depends(require_scope("products:write")),
    ) -> SyncExternalCatalogResponse:
        try:
            normalized_provider_name = _normalize_external_identifier(
                provider_name,
                "provider_name",
                allow_empty=False,
            )
            sync_source_key = payload.source_key
            connection_id = payload.connection_id
            runtime_auth: Optional[ExternalSourceRuntimeCredentials] = None
            async with get_session_factory()() as session:
                connection_service = ExternalSourceConnectionService()
                if payload.connection_id is not None:
                    connection = await connection_service.get_connection(
                        session=session,
                        tenant_id=api_key.tenant_id,
                        connection_id=payload.connection_id,
                    )
                    if connection is None:
                        raise HTTPException(status_code=404, detail="外部源连接不存在")
                    sync_source_key, connection_id = _external_catalog_sync_source_from_connection(
                        normalized_provider_name or "",
                        payload.source_key,
                        connection,
                    )
                    runtime_auth = await connection_service.load_runtime_credentials(
                        session=session,
                        tenant_id=api_key.tenant_id,
                        connection_id=connection_id,
                        settings=settings,
                    )
                    if runtime_auth is None:
                        raise HTTPException(status_code=404, detail="外部源连接不存在")
                result = await ExternalCatalogSyncService().sync_registered_catalog(
                    session=session,
                    tenant_id=api_key.tenant_id,
                    provider_name=normalized_provider_name or "",
                    source_key=sync_source_key,
                    connection_id=connection_id,
                    cursor=payload.cursor,
                    limit=payload.limit,
                    max_pages=payload.max_pages,
                    runtime_auth=runtime_auth,
                )
                await session.commit()
        except ExternalProviderNotRegisteredError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ExternalSourceError:
            raise _external_source_bad_gateway()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return _external_catalog_sync_response(
            normalized_provider_name or "",
            sync_source_key,
            result,
            connection_id=connection_id,
        )

    @router.post(
        "/external-sources/{provider_name}/catalog/products/sync",
        response_model=SyncExternalCatalogResponse,
    )
    async def sync_external_catalog_product(
        provider_name: str,
        payload: SyncExternalCatalogProductRequest,
        api_key: TenantApiKey = Depends(require_scope("products:write")),
    ) -> SyncExternalCatalogResponse:
        try:
            normalized_provider_name = _normalize_external_identifier(
                provider_name,
                "provider_name",
                allow_empty=False,
            )
            sync_source_key = payload.source_key
            connection_id = payload.connection_id
            runtime_auth: Optional[ExternalSourceRuntimeCredentials] = None
            async with get_session_factory()() as session:
                connection_service = ExternalSourceConnectionService()
                if payload.connection_id is not None:
                    connection = await connection_service.get_connection(
                        session=session,
                        tenant_id=api_key.tenant_id,
                        connection_id=payload.connection_id,
                    )
                    if connection is None:
                        raise HTTPException(status_code=404, detail="外部源连接不存在")
                    sync_source_key, connection_id = _external_catalog_sync_source_from_connection(
                        normalized_provider_name or "",
                        payload.source_key,
                        connection,
                    )
                    runtime_auth = await connection_service.load_runtime_credentials(
                        session=session,
                        tenant_id=api_key.tenant_id,
                        connection_id=connection_id,
                        settings=settings,
                    )
                    if runtime_auth is None:
                        raise HTTPException(status_code=404, detail="外部源连接不存在")
                result = await ExternalCatalogSyncService().sync_registered_product(
                    session=session,
                    tenant_id=api_key.tenant_id,
                    provider_name=normalized_provider_name or "",
                    external_product_id=payload.external_product_id,
                    source_key=sync_source_key,
                    connection_id=connection_id,
                    runtime_auth=runtime_auth,
                )
                await session.commit()
        except ExternalProviderNotRegisteredError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ExternalSourceError:
            raise _external_source_bad_gateway()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return _external_catalog_sync_response(
            normalized_provider_name or "",
            sync_source_key,
            result,
            connection_id=connection_id,
        )

    @router.post(
        "/external-sources/{provider_name}/orders",
        response_model=ExternalOrderResponse,
    )
    async def create_external_order(
        provider_name: str,
        payload: CreateExternalOrderRequest,
        api_key: TenantApiKey = Depends(require_scope("external_sources:write")),
    ) -> ExternalOrderResponse:
        try:
            normalized_provider_name = _normalize_external_identifier(
                provider_name,
                "provider_name",
                allow_empty=False,
            )
            operation_source_key = payload.source_key
            connection_id = payload.connection_id
            runtime_auth: Optional[ExternalSourceRuntimeCredentials] = None
            async with get_session_factory()() as session:
                operation_source_key, connection_id, runtime_auth = await _external_operation_auth_from_connection(
                    session=session,
                    tenant_id=api_key.tenant_id,
                    provider_name=normalized_provider_name or "",
                    source_key=payload.source_key,
                    connection_id=payload.connection_id,
                    settings=settings,
                )
                external_order = await ExternalOrderOperationService().create_registered_order(
                    tenant_id=api_key.tenant_id,
                    provider_name=normalized_provider_name or "",
                    source_key=operation_source_key,
                    connection_id=connection_id,
                    runtime_auth=runtime_auth,
                    request=ExternalOrderRequest(
                        external_product_id=payload.external_product_id,
                        quantity=payload.quantity,
                        out_trade_no=payload.out_trade_no,
                        buyer_reference=payload.buyer_reference,
                        buyer_contact=payload.buyer_contact,
                        metadata=payload.metadata,
                    ),
                )
        except ExternalProviderNotRegisteredError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ExternalSourceError:
            raise _external_source_bad_gateway()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return _external_order_response(
            normalized_provider_name or "",
            operation_source_key,
            external_order,
            connection_id=connection_id,
        )

    @router.get(
        "/external-sources/{provider_name}/orders/{external_order_id}",
        response_model=ExternalOrderResponse,
    )
    async def query_external_order(
        provider_name: str,
        external_order_id: str,
        connection_id: Optional[int] = None,
        source_key: str = "",
        api_key: TenantApiKey = Depends(require_scope("external_sources:read")),
    ) -> ExternalOrderResponse:
        try:
            normalized_provider_name = _normalize_external_identifier(
                provider_name,
                "provider_name",
                allow_empty=False,
            )
            operation_source_key = source_key
            runtime_auth: Optional[ExternalSourceRuntimeCredentials] = None
            async with get_session_factory()() as session:
                operation_source_key, connection_id, runtime_auth = await _external_operation_auth_from_connection(
                    session=session,
                    tenant_id=api_key.tenant_id,
                    provider_name=normalized_provider_name or "",
                    source_key=source_key,
                    connection_id=connection_id,
                    settings=settings,
                )
                external_order = await ExternalOrderOperationService().query_registered_order(
                    tenant_id=api_key.tenant_id,
                    provider_name=normalized_provider_name or "",
                    external_order_id=external_order_id,
                    source_key=operation_source_key,
                    connection_id=connection_id,
                    runtime_auth=runtime_auth,
                )
        except ExternalProviderNotRegisteredError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ExternalSourceError:
            raise _external_source_bad_gateway()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if external_order is None:
            raise HTTPException(status_code=404, detail="外部订单不存在")
        return _external_order_response(
            normalized_provider_name or "",
            operation_source_key,
            external_order,
            connection_id=connection_id,
        )

    @router.get(
        "/external-sources/{provider_name}/orders/{external_order_id}/delivery",
        response_model=ExternalDeliveryResponse,
    )
    async def fetch_external_delivery(
        provider_name: str,
        external_order_id: str,
        connection_id: Optional[int] = None,
        source_key: str = "",
        api_key: TenantApiKey = Depends(require_scope("external_sources:read")),
    ) -> ExternalDeliveryResponse:
        try:
            normalized_provider_name = _normalize_external_identifier(
                provider_name,
                "provider_name",
                allow_empty=False,
            )
            operation_source_key = source_key
            runtime_auth: Optional[ExternalSourceRuntimeCredentials] = None
            async with get_session_factory()() as session:
                operation_source_key, connection_id, runtime_auth = await _external_operation_auth_from_connection(
                    session=session,
                    tenant_id=api_key.tenant_id,
                    provider_name=normalized_provider_name or "",
                    source_key=source_key,
                    connection_id=connection_id,
                    settings=settings,
                )
                delivery = await ExternalOrderOperationService().fetch_registered_delivery(
                    tenant_id=api_key.tenant_id,
                    provider_name=normalized_provider_name or "",
                    external_order_id=external_order_id,
                    source_key=operation_source_key,
                    connection_id=connection_id,
                    runtime_auth=runtime_auth,
                )
        except ExternalProviderNotRegisteredError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ExternalSourceError:
            raise _external_source_bad_gateway()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if delivery is None:
            raise HTTPException(status_code=404, detail="外部发货不存在")
        return _external_delivery_response(
            normalized_provider_name or "",
            operation_source_key,
            delivery,
            connection_id=connection_id,
        )

    @router.post("/products/{product_id}/inventory/import", response_model=ImportInventoryResponse)
    async def import_inventory(
        product_id: int,
        payload: ImportInventoryRequest,
        api_key: TenantApiKey = Depends(require_scope("inventory:write")),
    ) -> ImportInventoryResponse:
        try:
            items, input_duplicate_count = _normalize_inventory_items(payload.items)
            crypto = TokenCrypto(settings)
            encrypted_items = [(crypto.encrypt_token(item), crypto.token_hash(item)) for item in items]
            async with get_session_factory()() as session:
                added_count, existing_count = await ProductRepository().add_inventory_items(
                    session=session,
                    tenant_id=api_key.tenant_id,
                    product_id=product_id,
                    encrypted_items=encrypted_items,
                )
                await session.commit()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return ImportInventoryResponse(
            product_id=product_id,
            added_count=added_count,
            existing_count=existing_count,
            input_duplicate_count=input_duplicate_count,
        )

    @router.get("/products/{product_id}/inventory", response_model=InventorySummaryResponse)
    async def inventory_summary(
        product_id: int,
        api_key: TenantApiKey = Depends(require_scope("inventory:read")),
    ) -> InventorySummaryResponse:
        async with get_session_factory()() as session:
            product, _ = await ProductRepository().get_product_with_default_variant(
                session,
                tenant_id=api_key.tenant_id,
                product_id=product_id,
            )
            if product is None:
                raise HTTPException(status_code=404, detail="商品不存在")
            summary = await ProductRepository().inventory_summary(session, api_key.tenant_id, product_id)
        return _inventory_summary_response(product_id, summary.get(product_id, {}))

    @router.get("/orders", response_model=List[AdminOrder])
    async def list_orders(
        limit: int = 50,
        api_key: TenantApiKey = Depends(require_scope("orders:read")),
    ) -> List[AdminOrder]:
        normalized_limit = min(max(limit, 1), 100)
        async with get_session_factory()() as session:
            result = await session.execute(
                select(Order)
                .where(Order.tenant_id == api_key.tenant_id)
                .order_by(Order.created_at.desc())
                .limit(normalized_limit)
            )
            orders = list(result.scalars().all())
        return [_order_response(order) for order in orders]

    @router.get("/orders/{out_trade_no}", response_model=AdminOrder)
    async def order_detail(
        out_trade_no: str,
        api_key: TenantApiKey = Depends(require_scope("orders:read")),
    ) -> AdminOrder:
        async with get_session_factory()() as session:
            result = await session.execute(
                select(Order)
                .where(Order.tenant_id == api_key.tenant_id)
                .where(Order.out_trade_no == out_trade_no)
                .limit(1)
            )
            order = result.scalar_one_or_none()
        if order is None:
            raise HTTPException(status_code=404, detail="订单不存在")
        return _order_response(order)

    @router.get("/orders/{out_trade_no}/diagnostics", response_model=OrderDiagnosticsResponse)
    async def order_diagnostics(
        out_trade_no: str,
        api_key: TenantApiKey = Depends(require_scope("orders:read")),
    ) -> OrderDiagnosticsResponse:
        try:
            async with get_session_factory()() as session:
                summary = await OrderDiagnosticsService().get_summary(
                    session,
                    tenant_id=api_key.tenant_id,
                    out_trade_no=out_trade_no,
                )
        except ValueError:
            raise HTTPException(status_code=400, detail="订单查询参数无效")
        if summary is None:
            raise HTTPException(status_code=404, detail="订单不存在")
        return _order_diagnostics_response(summary)

    @router.post(
        "/orders/{out_trade_no}/external-fulfillment/retry",
        response_model=RetryExternalFulfillmentResponse,
    )
    async def retry_external_fulfillment(
        out_trade_no: str,
        api_key: TenantApiKey = Depends(require_scope("external_sources:write")),
    ) -> RetryExternalFulfillmentResponse:
        try:
            async with get_session_factory()() as session:
                result = await ExternalAutoFulfillmentService().fulfill_tenant_paid_order(
                    session,
                    tenant_id=api_key.tenant_id,
                    out_trade_no=out_trade_no,
                    settings=settings,
                )
                if result is None:
                    raise HTTPException(status_code=404, detail="订单不存在")
                await session.commit()
        except HTTPException:
            raise
        except ValueError:
            raise HTTPException(status_code=400, detail="订单当前不能外部履约")
        return _external_fulfillment_retry_response(result)

    @router.post(
        "/orders/{out_trade_no}/external-delivery/import",
        response_model=ImportExternalDeliveryResponse,
    )
    async def import_external_delivery(
        out_trade_no: str,
        payload: ImportExternalDeliveryRequest,
        api_key: TenantApiKey = Depends(require_scope("external_sources:write")),
    ) -> ImportExternalDeliveryResponse:
        try:
            normalized_provider_name = _normalize_external_identifier(
                payload.provider_name,
                "provider_name",
                allow_empty=False,
            )
            operation_source_key = payload.source_key
            connection_id = payload.connection_id
            runtime_auth: Optional[ExternalSourceRuntimeCredentials] = None
            async with get_session_factory()() as session:
                operation_source_key, connection_id, runtime_auth = await _external_operation_auth_from_connection(
                    session=session,
                    tenant_id=api_key.tenant_id,
                    provider_name=normalized_provider_name or "",
                    source_key=payload.source_key,
                    connection_id=payload.connection_id,
                    settings=settings,
                )
                delivery = await ExternalOrderOperationService().fetch_registered_delivery(
                    tenant_id=api_key.tenant_id,
                    provider_name=normalized_provider_name or "",
                    external_order_id=payload.external_order_id,
                    source_key=operation_source_key,
                    connection_id=connection_id,
                    runtime_auth=runtime_auth,
                )
                if delivery is None:
                    raise HTTPException(status_code=404, detail="外部发货不存在")
                result = await ExternalDeliveryImportService().import_delivery(
                    session=session,
                    tenant_id=api_key.tenant_id,
                    out_trade_no=out_trade_no,
                    provider_name=normalized_provider_name or "",
                    source_key=operation_source_key,
                    delivery=delivery,
                    settings=settings,
                    dry_run=payload.dry_run,
                )
                await session.commit()
        except HTTPException:
            raise
        except ExternalProviderNotRegisteredError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ExternalSourceError:
            raise HTTPException(status_code=502, detail="外部发货获取失败")
        except ValueError as exc:
            if str(exc) == "订单不存在":
                raise HTTPException(status_code=404, detail=str(exc))
            raise HTTPException(status_code=400, detail=str(exc))
        return ImportExternalDeliveryResponse(
            out_trade_no=result.out_trade_no,
            order_status=result.order_status,
            delivery_record_id=result.delivery_record_id,
            item_count=result.item_count,
            imported=result.imported,
            dry_run=result.dry_run,
        )

    return router


def _extract_api_key(authorization: Optional[str], x_api_key: Optional[str]) -> Optional[str]:
    if x_api_key:
        return x_api_key.strip()
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def _admin_product_response(product: object, variant: object | None, available_count: int) -> AdminProduct:
    return AdminProduct(
        id=getattr(product, "id"),
        external_source=getattr(product, "external_source", None),
        source_key=getattr(product, "source_key", "") or "",
        external_id=getattr(product, "external_id", None),
        name=getattr(product, "name"),
        category=getattr(product, "category", None),
        sort_order=int(getattr(product, "sort_order", 0) or 0),
        status=getattr(product, "status"),
        delivery_type=getattr(product, "delivery_type"),
        price=getattr(variant, "price") if variant else getattr(product, "suggested_price"),
        currency=getattr(variant, "currency") if variant else getattr(product, "currency"),
        available_count=available_count,
    )


def _api_key_response(api_key: TenantApiKeySummary) -> TenantApiKeyItem:
    return TenantApiKeyItem(
        api_key_id=api_key.api_key_id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        status=api_key.status,
        scopes=api_key.scopes,
        ip_allowlist=api_key.ip_allowlist,
        created_at=api_key.created_at.isoformat(),
        last_used_at=api_key.last_used_at.isoformat() if api_key.last_used_at else None,
    )


def _created_api_key_response(api_key: CreatedTenantApiKey) -> CreatedTenantApiKeyResponse:
    return CreatedTenantApiKeyResponse(
        api_key_id=api_key.api_key_id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        status=api_key.status,
        scopes=api_key.scopes,
        ip_allowlist=api_key.ip_allowlist,
        created_at=None,
        last_used_at=None,
        plain_key=api_key.plain_key,
    )


def _tenant_audit_log_response(service: AuditLogService, log: AuditLogSummary) -> TenantAuditLogItem:
    return TenantAuditLogItem(
        audit_log_id=log.audit_log_id,
        created_at=log.created_at.isoformat(),
        actor_telegram_user_id=log.actor_telegram_user_id,
        actor_username=log.actor_username,
        action=log.action,
        target_type=log.target_type,
        target_id=log.target_id,
        metadata=service.safe_metadata_for_tenant_api(log.metadata_json),
    )


def _risk_dispute_response(dispute: DisputeSummary) -> TenantRiskDisputeItem:
    return TenantRiskDisputeItem(
        dispute_id=dispute.dispute_id,
        order_id=dispute.order_id,
        out_trade_no=dispute.out_trade_no,
        buyer_telegram_user_id=dispute.buyer_telegram_user_id,
        source_type=dispute.source_type,
        order_status=dispute.order_status,
        amount=dispute.amount,
        currency=dispute.currency,
        status=dispute.status,
        reason=_safe_risk_text(dispute.reason),
        resolution=_safe_risk_text(dispute.resolution),
        created_at=dispute.created_at.isoformat(),
        updated_at=dispute.updated_at.isoformat(),
    )


def _risk_after_sale_response(after_sale: AfterSaleSummary) -> TenantRiskAfterSaleItem:
    return TenantRiskAfterSaleItem(
        case_id=after_sale.case_id,
        order_id=after_sale.order_id,
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
        reason=_safe_risk_text(after_sale.reason),
        resolution=_safe_risk_text(after_sale.resolution),
        created_at=after_sale.created_at.isoformat(),
        updated_at=after_sale.updated_at.isoformat(),
    )


def _report_export_job_response(job: ExportJobSummary) -> TenantReportExportJobItem:
    return TenantReportExportJobItem(
        export_job_id=job.export_job_id,
        report_type=job.report_type,
        scope_type=job.scope_type,
        status=job.status,
        row_count=job.row_count,
        download_available=_report_download_available(job),
        failure_reason=_safe_report_failure_text(job.error_message),
        expires_at=job.expires_at.isoformat() if job.expires_at else None,
        created_at=job.created_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at else None,
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
    )


def _normalize_report_export_status(status: Optional[str]) -> Optional[str]:
    if status is None:
        return None
    normalized = status.strip().lower()
    if not normalized or normalized == "all":
        return None
    if normalized not in REPORT_EXPORT_JOB_STATUS_VALUES:
        raise ValueError("报表任务状态无效")
    return normalized


def _report_download_available(job: ExportJobSummary) -> bool:
    return bool(
        job.status == "completed"
        and job.download_url
        and job.expires_at is not None
        and job.expires_at > datetime.now(timezone.utc)
    )


def _normalize_report_export_type(report_type: Optional[str]) -> Optional[str]:
    if report_type is None:
        return None
    normalized = report_type.strip().lower()
    if not normalized or normalized == "all":
        return None
    if normalized not in REPORT_EXPORT_JOB_TYPES:
        raise ValueError("报表类型无效")
    return normalized


def _normalize_required_report_export_type(report_type: str) -> str:
    normalized = report_type.strip().lower()
    if not normalized or normalized == "all" or normalized not in REPORT_EXPORT_JOB_TYPES:
        raise ValueError("报表类型无效")
    return normalized


def _safe_report_failure_text(value: Optional[str]) -> Optional[str]:
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
    if any(marker in lowered for marker in REPORT_FAILURE_SENSITIVE_VALUE_MARKERS):
        return "报表导出失败"
    return normalized[:300]


def _normalize_risk_status(status: Optional[str]) -> Optional[str]:
    if status is None:
        return "open"
    normalized = status.strip().lower()
    if normalized == "all":
        return None
    if normalized not in RISK_STATUS_VALUES:
        raise ValueError("风控状态无效")
    return normalized


def _safe_risk_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    lowered = normalized.lower()
    if "http://" in lowered or "https://" in lowered:
        return "内容已隐藏"
    if any(marker in lowered for marker in RISK_RESPONSE_SENSITIVE_VALUE_MARKERS):
        return "内容已隐藏"
    return normalized[:300]


def _normalize_inventory_items(items: List[str]) -> tuple[List[str], int]:
    normalized: List[str] = []
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
    return normalized, duplicated_count


def _inventory_summary_response(product_id: int, summary: Dict[str, int]) -> InventorySummaryResponse:
    available_count = int(summary.get("available", 0))
    locked_count = int(summary.get("locked", 0))
    used_count = int(summary.get("used", 0))
    return InventorySummaryResponse(
        product_id=product_id,
        available_count=available_count,
        locked_count=locked_count,
        used_count=used_count,
        total_count=sum(int(count) for count in summary.values()),
    )


def _external_catalog_sync_response(
    provider_name: str,
    source_key: str,
    result: ExternalCatalogSyncResult,
    *,
    connection_id: Optional[int] = None,
) -> SyncExternalCatalogResponse:
    normalized_source_key = result.products[0].source_key if result.products else source_key.strip()
    return SyncExternalCatalogResponse(
        provider_name=provider_name.strip(),
        source_key=normalized_source_key,
        connection_id=connection_id,
        created_count=result.created_count,
        updated_count=result.updated_count,
        skipped_count=result.skipped_count,
        next_cursor=result.next_cursor,
        products=[
            SyncedExternalCatalogProduct(
                product_id=product.product_id,
                external_source=product.external_source,
                source_key=product.source_key,
                external_id=product.external_id,
                action=product.action,
                status=product.status,
                skipped_reason=product.skipped_reason,
            )
            for product in result.products
        ],
    )


def _external_order_response(
    provider_name: str,
    source_key: str,
    order: ExternalOrder,
    *,
    connection_id: Optional[int] = None,
) -> ExternalOrderResponse:
    return ExternalOrderResponse(
        provider_name=provider_name.strip(),
        source_key=source_key.strip(),
        connection_id=connection_id,
        external_order_id=order.external_order_id,
        external_product_id=order.external_product_id,
        status=order.status,
        quantity=order.quantity,
        amount=order.amount,
        currency=order.currency,
        delivery_ready=order.delivery_ready,
    )


def _external_delivery_response(
    provider_name: str,
    source_key: str,
    delivery: ExternalDelivery,
    *,
    connection_id: Optional[int] = None,
) -> ExternalDeliveryResponse:
    return ExternalDeliveryResponse(
        provider_name=provider_name.strip(),
        source_key=source_key.strip(),
        connection_id=connection_id,
        external_order_id=delivery.external_order_id,
        delivery_type=delivery.delivery_type,
        items=list(delivery.items),
        message=delivery.message,
    )


def _external_fulfillment_retry_response(
    result: ExternalAutoFulfillmentAttemptResult,
) -> RetryExternalFulfillmentResponse:
    return RetryExternalFulfillmentResponse(
        out_trade_no=result.out_trade_no,
        provider_name=result.provider_name,
        source_key=result.source_key,
        external_order_id=result.external_order_id,
        delivery_record_id=result.delivery_record_id,
        item_count=result.item_count,
        imported=result.imported,
        attempt_status=result.attempt_status,
        failure_stage=result.failure_stage,
        failure_category=result.failure_category,
        failure_retryable=result.failure_retryable,
        upstream_status_code=result.upstream_status_code,
        failure_recorded=result.failure_recorded,
    )


async def _external_operation_auth_from_connection(
    *,
    session: object,
    tenant_id: int,
    provider_name: str,
    source_key: str,
    connection_id: Optional[int],
    settings: Settings,
) -> tuple[str, Optional[int], Optional[ExternalSourceRuntimeCredentials]]:
    if connection_id is None:
        return source_key, None, None
    connection_service = ExternalSourceConnectionService()
    connection = await connection_service.get_connection(
        session=session,
        tenant_id=tenant_id,
        connection_id=connection_id,
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="外部源连接不存在")
    operation_source_key, resolved_connection_id = _external_catalog_sync_source_from_connection(
        provider_name,
        source_key,
        connection,
    )
    runtime_auth = await connection_service.load_runtime_credentials(
        session=session,
        tenant_id=tenant_id,
        connection_id=resolved_connection_id,
        settings=settings,
    )
    if runtime_auth is None:
        raise HTTPException(status_code=404, detail="外部源连接不存在")
    return operation_source_key, resolved_connection_id, runtime_auth


def _external_catalog_sync_source_from_connection(
    provider_name: str,
    source_key: str,
    connection: ExternalSourceConnectionSummary,
) -> tuple[str, int]:
    if connection.status != "active":
        raise ValueError("外部源连接未启用")
    if connection.provider_name != provider_name:
        raise ValueError("外部源连接 provider 与路径不一致")
    requested_source_key = _normalize_external_identifier(source_key, "source_key", allow_empty=True) or ""
    if requested_source_key and requested_source_key != connection.source_key:
        raise ValueError("请求 source_key 与外部源连接不一致")
    return connection.source_key, connection.connection_id


def _external_source_bad_gateway() -> HTTPException:
    return HTTPException(status_code=502, detail="外部发卡源暂时不可用")


def _external_source_connection_response(
    connection: ExternalSourceConnectionSummary,
) -> ExternalSourceConnectionItem:
    return ExternalSourceConnectionItem(
        connection_id=connection.connection_id,
        provider_name=connection.provider_name,
        source_key=connection.source_key,
        display_name=connection.display_name,
        status=connection.status,
        credential_fields=connection.credential_fields,
        created_at=connection.created_at.isoformat() if connection.created_at else None,
        last_used_at=connection.last_used_at.isoformat() if connection.last_used_at else None,
    )


def _external_source_provider_response(summary: ExternalProviderSummary) -> ExternalSourceProviderItem:
    return ExternalSourceProviderItem(
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


def _external_fulfillment_failure_response(
    failure: ExternalFulfillmentFailureSummary,
) -> ExternalFulfillmentFailureItem:
    return ExternalFulfillmentFailureItem(
        audit_log_id=failure.audit_log_id,
        created_at=failure.created_at.isoformat(),
        order_id=failure.order_id,
        out_trade_no=failure.out_trade_no,
        product_id=failure.product_id,
        provider_name=failure.provider_name,
        source_key=failure.source_key,
        external_product_id=failure.external_product_id,
        connection_id=failure.connection_id,
        external_order_id=failure.external_order_id,
        failure_reason=failure.failure_reason,
        failure_stage=failure.failure_stage,
        failure_category=failure.failure_category,
        failure_retryable=failure.failure_retryable,
        upstream_status_code=failure.upstream_status_code,
        failure_fingerprint=failure.failure_fingerprint,
    )


def _external_fulfillment_attempt_response(
    attempt: ExternalFulfillmentAttemptSummary,
) -> ExternalFulfillmentAttemptItem:
    return ExternalFulfillmentAttemptItem(
        attempt_id=attempt.attempt_id,
        created_at=attempt.created_at.isoformat(),
        started_at=attempt.started_at.isoformat(),
        finished_at=attempt.finished_at.isoformat(),
        order_id=attempt.order_id,
        out_trade_no=attempt.out_trade_no,
        product_id=attempt.product_id,
        provider_name=attempt.provider_name,
        source_key=attempt.source_key,
        external_product_id=attempt.external_product_id,
        connection_id=attempt.connection_id,
        external_order_id=attempt.external_order_id,
        delivery_record_id=attempt.delivery_record_id,
        attempt_source=attempt.attempt_source,
        status=attempt.status,
        imported=attempt.imported,
        item_count=attempt.item_count,
        failure_reason=attempt.failure_reason,
        failure_stage=attempt.failure_stage,
        failure_category=attempt.failure_category,
        failure_retryable=attempt.failure_retryable,
        upstream_status_code=attempt.upstream_status_code,
        failure_fingerprint=attempt.failure_fingerprint,
    )


def _epusdt_config_response(status: EpusdtConfigStatus) -> TenantEpusdtConfigResponse:
    return TenantEpusdtConfigResponse(
        provider=EPUSDT_PROVIDER,
        enabled=status.enabled,
        scope_type=status.scope_type,
        base_url=status.base_url or None,
        pid_masked=_mask_config_value(status.pid),
        asset=status.token or None,
        network=status.network or None,
        key_configured=status.secret_configured,
    )


def _payment_provider_config_response(status: TenantPaymentConfigStatus) -> TenantPaymentProviderConfigResponse:
    return TenantPaymentProviderConfigResponse(
        provider=status.provider,
        enabled=status.enabled,
        scope_type=status.scope_type,
        gateway_url=status.gateway_url or None,
        merchant_id_masked=_mask_config_value(status.merchant_id),
        monitor_address_masked=_mask_config_value(status.monitor_address),
        asset=status.asset or None,
        network=status.network or None,
        chain_type=status.chain_type or None,
        payment_type=status.payment_type or None,
        device=status.device or None,
        return_url_configured=bool(status.return_url),
        subject=status.subject or None,
        cny_per_usdt=getattr(status, "cny_per_usdt", None) or None,
        min_usdt_amount=getattr(status, "min_usdt_amount", None) or None,
        timeout_seconds=getattr(status, "timeout_seconds", None),
        key_configured=status.key_configured,
    )


def _payment_provider_summary_response(summary: PaymentProviderSummary) -> TenantPaymentProviderItem:
    return TenantPaymentProviderItem(
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
    )


def _payment_callback_failure_response(summary: PaymentCallbackFailureSummary) -> TenantPaymentCallbackFailureItem:
    return TenantPaymentCallbackFailureItem(
        callback_id=summary.callback_id,
        created_at=summary.created_at.isoformat(),
        processed_at=summary.processed_at.isoformat() if summary.processed_at is not None else None,
        order_id=summary.order_id,
        out_trade_no=summary.out_trade_no,
        order_status=summary.order_status,
        provider=summary.provider,
        process_status=summary.process_status,
        failure_reason=summary.failure_reason,
    )


def _payment_callback_rejection_response(
    summary: PaymentCallbackRejectionSummary,
) -> TenantPaymentCallbackRejectionItem:
    return TenantPaymentCallbackRejectionItem(
        audit_log_id=summary.audit_log_id,
        created_at=summary.created_at.isoformat(),
        provider=summary.provider,
        reason_category=summary.reason_category,
        failure_reason=summary.failure_reason,
        http_status=summary.http_status,
        out_trade_no=summary.out_trade_no,
        order_id=summary.order_id,
        order_status=summary.order_status,
        payload_field_count=summary.payload_field_count,
    )


def _trc20_direct_transfer_response(
    summary: Trc20DirectTransferSummary,
) -> TenantTrc20DirectTransferItem:
    return TenantTrc20DirectTransferItem(
        tx_hash=summary.tx_hash,
        block_number=summary.block_number,
        timestamp_ms=summary.timestamp_ms,
        block_timestamp=summary.block_timestamp.isoformat() if summary.block_timestamp is not None else None,
        from_address_masked=summary.from_address_masked,
        to_address_masked=summary.to_address_masked,
        contract_address=summary.contract_address,
        amount=summary.amount,
        confirmations=summary.confirmations,
        match_status=summary.match_status,
        out_trade_no=summary.out_trade_no,
        matched_at=summary.matched_at.isoformat() if summary.matched_at is not None else None,
        created_at=summary.created_at.isoformat(),
    )


def _mask_config_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) <= 4:
        return "*" * len(text)
    return f"{text[:2]}***{text[-2:]}"


def _normalize_payment_config_text(value: str, field_name: str, *, max_length: int) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} 不能为空")
    if len(text) > max_length:
        raise ValueError(f"{field_name} 长度不能超过 {max_length}")
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ValueError(f"{field_name} 不能包含控制字符")
    return text


def _normalize_epusdt_base_url(value: str) -> str:
    return normalize_epusdt_base_url(value)


def _normalize_optional_payment_config_text(value: Optional[str], field_name: str, *, max_length: int) -> Optional[str]:
    if value is None:
        return None
    text = _normalize_payment_config_text(value, field_name, max_length=max_length)
    return text or None


def _ensure_unique_sync_product_ids(products: List[SyncProductItem]) -> None:
    product_ids = [item.product_id for item in products if item.product_id is not None]
    if len(product_ids) != len(set(product_ids)):
        raise ValueError("同步列表内 product_id 不能重复")


def _ensure_unique_sync_external_refs(products: List[SyncProductItem]) -> None:
    external_refs = []
    for item in products:
        external_source, source_key, external_id = _sync_external_ref(item)
        if external_source is not None or external_id is not None:
            external_refs.append((external_source, source_key, external_id))
    if len(external_refs) != len(set(external_refs)):
        raise ValueError("同步列表内 external_source、source_key 和 external_id 组合不能重复")


def _validate_sync_products(products: List[SyncProductItem]) -> None:
    for item in products:
        if item.delivery_type not in {"card_pool", "card_fixed", "telegram_invite", "file_download"}:
            raise ValueError("不支持的发货类型")
        if item.status is not None and item.status not in {"draft", "on", "off"}:
            raise ValueError("不支持的商品状态")
        external_source, source_key, external_id = _sync_external_ref(item)
        if (external_source is None) != (external_id is None):
            raise ValueError("外部商品映射需要同时提供 external_source 和 external_id")
        if source_key and external_source is None and external_id is None:
            raise ValueError("source_key 只能与 external_source 和 external_id 一起提供")


def _sync_external_ref(item: SyncProductItem) -> tuple[Optional[str], str, Optional[str]]:
    external_source = _normalize_external_identifier(item.external_source, "external_source", allow_empty=False)
    source_key = _normalize_external_identifier(item.source_key, "source_key", allow_empty=True) or ""
    external_id = item.external_id.strip() if item.external_id else None
    return external_source, source_key, external_id or None


def _normalize_external_identifier(value: Optional[str], field_name: str, *, allow_empty: bool) -> Optional[str]:
    if value is None:
        return "" if allow_empty else None
    try:
        return _normalize_service_external_identifier(value, field_name, allow_empty=allow_empty)
    except ValueError as exc:
        if not value.strip() and not allow_empty:
            return None
        raise


async def _verify_signed_request(
    *,
    request: Request,
    api_key: str,
    timestamp: str,
    signature: str,
    max_skew_seconds: int,
) -> None:
    body = await request.body()
    verify_request_signature(
        api_key,
        method=request.method,
        path=request.url.path,
        query_string=request.url.query,
        body=body,
        timestamp=timestamp,
        signature=signature,
        max_skew_seconds=max_skew_seconds,
    )


def _order_response(order: Order) -> AdminOrder:
    return AdminOrder(
        out_trade_no=order.out_trade_no,
        source_type=order.source_type,
        amount=order.amount,
        currency=order.currency,
        status=order.status,
        payment_mode=order.payment_mode,
        buyer_telegram_user_id=order.buyer_telegram_user_id,
        created_at=order.created_at.isoformat(),
        expires_at=order.expires_at.isoformat(),
        paid_at=order.paid_at.isoformat() if order.paid_at else None,
        delivered_at=order.delivered_at.isoformat() if order.delivered_at else None,
    )


def _tenant_subscription_response(summary: TenantSubscriptionSummary) -> TenantSubscriptionResponse:
    return TenantSubscriptionResponse(
        status=summary.status,
        plan_code=summary.plan_code,
        plan_name=summary.plan_name,
        monthly_price=summary.monthly_price,
        currency=summary.currency,
        trial_days=summary.trial_days,
        grace_days=summary.grace_days,
        trial_ends_at=summary.trial_ends_at.isoformat() if summary.trial_ends_at else None,
        current_period_ends_at=(
            summary.current_period_ends_at.isoformat() if summary.current_period_ends_at else None
        ),
        subscription_ends_at=summary.subscription_ends_at.isoformat() if summary.subscription_ends_at else None,
        grace_ends_at=summary.grace_ends_at.isoformat() if summary.grace_ends_at else None,
        suspended_at=summary.suspended_at.isoformat() if summary.suspended_at else None,
        data_retention_until=summary.data_retention_until.isoformat() if summary.data_retention_until else None,
        created_at=summary.created_at.isoformat() if summary.created_at else None,
        updated_at=summary.updated_at.isoformat() if summary.updated_at else None,
    )


def _tenant_subscription_invoice_response(
    invoice: SubscriptionInvoiceSummary,
) -> TenantSubscriptionInvoiceItem:
    return TenantSubscriptionInvoiceItem(
        out_trade_no=invoice.out_trade_no,
        amount=invoice.amount,
        currency=invoice.currency,
        status=invoice.status,
        paid_at=invoice.paid_at.isoformat() if invoice.paid_at else None,
        created_at=invoice.created_at.isoformat(),
    )


def _tenant_supplier_offer_response(offer: SupplierOwnOfferSummary) -> TenantSupplierOfferItem:
    return TenantSupplierOfferItem(
        supplier_offer_id=offer.offer_id,
        product_name=offer.product_name,
        delivery_type=offer.delivery_type,
        suggested_price=offer.suggested_price,
        min_sale_price=offer.min_sale_price,
        supplier_cost=offer.supplier_cost,
        currency=offer.currency,
        available_count=offer.available_count,
        requires_approval=offer.requires_approval,
        status=offer.status,
    )


def _created_supplier_offer_response(offer: CreatedSupplierOffer) -> TenantCreatedSupplierOfferItem:
    return TenantCreatedSupplierOfferItem(
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


def _supplier_offer_approval_response(setting: SupplierApprovalSetting) -> TenantSupplierOfferApprovalItem:
    return TenantSupplierOfferApprovalItem(
        supplier_offer_id=setting.offer_id,
        requires_approval=setting.requires_approval,
        status=setting.status,
    )


def _supplier_application_response(application: ResellerApplicationSummary) -> TenantSupplierApplicationItem:
    return TenantSupplierApplicationItem(
        supplier_offer_id=application.supplier_offer_id,
        reseller_tenant_id=application.reseller_tenant_id,
        reseller_store_name=application.reseller_store_name,
        product_name=application.product_name,
        status=application.status,
        pricing_value=application.pricing_value,
        min_sale_price=application.min_sale_price,
        currency=application.currency,
        updated_at=application.updated_at.isoformat(),
    )


def _supply_market_offer_response(offer: SupplierOfferSummary) -> TenantSupplyMarketOfferItem:
    return TenantSupplyMarketOfferItem(
        supplier_offer_id=offer.offer_id,
        product_name=offer.product_name,
        delivery_type=offer.delivery_type,
        suggested_price=offer.suggested_price,
        min_sale_price=offer.min_sale_price,
        currency=offer.currency,
        available_count=offer.available_count,
        description=offer.description,
        requires_approval=offer.requires_approval,
        reseller_rule_status=offer.reseller_rule_status,
        can_create_reseller_product=(not offer.requires_approval or offer.reseller_rule_status == "active"),
        supplier_cost=offer.supplier_cost,
        effective_min_sale_price=offer.effective_min_sale_price,
    )


def _reseller_application_response(application: ResellerApplicationSummary) -> TenantResellerApplicationItem:
    return TenantResellerApplicationItem(
        supplier_offer_id=application.supplier_offer_id,
        product_name=application.product_name,
        status=application.status,
        pricing_value=application.pricing_value,
        min_sale_price=application.min_sale_price,
        currency=application.currency,
        updated_at=application.updated_at.isoformat(),
    )


def _created_reseller_product_response(product: CreatedResellerProduct) -> TenantCreatedResellerProductItem:
    return TenantCreatedResellerProductItem(
        reseller_product_id=product.reseller_product_id,
        supplier_offer_id=product.supplier_offer_id,
        display_name=product.display_name,
        sale_price=product.sale_price,
        currency=product.currency,
        status=product.status,
    )


def _reseller_product_response(product: ResellerProductSummary) -> TenantResellerProductItem:
    return TenantResellerProductItem(
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


def _order_diagnostics_response(summary: OrderDiagnosticsSummary) -> OrderDiagnosticsResponse:
    return OrderDiagnosticsResponse(
        order_id=summary.order_id,
        out_trade_no=summary.out_trade_no,
        source_type=summary.source_type,
        status=summary.status,
        payment_mode=summary.payment_mode,
        payment_provider=summary.payment_provider,
        amount=summary.amount,
        currency=summary.currency,
        created_at=summary.created_at.isoformat(),
        expires_at=summary.expires_at.isoformat(),
        paid_at=summary.paid_at.isoformat() if summary.paid_at else None,
        delivered_at=summary.delivered_at.isoformat() if summary.delivered_at else None,
        payment_count=summary.payment_count,
        callback_count=summary.callback_count,
        callback_status_counts=summary.callback_status_counts,
        payments=[_order_payment_diagnostic_response(payment) for payment in summary.payments],
        callbacks=[_order_callback_diagnostic_response(callback) for callback in summary.callbacks],
        delivery=_order_delivery_diagnostic_response(summary.delivery) if summary.delivery is not None else None,
        external_fulfillment=_order_external_fulfillment_diagnostic_response(summary.external_fulfillment),
        trc20_direct=_order_trc20_direct_diagnostic_response(summary.trc20_direct),
    )


def _order_payment_diagnostic_response(summary: OrderPaymentDiagnostic) -> OrderPaymentDiagnosticItem:
    return OrderPaymentDiagnosticItem(
        payment_id=summary.payment_id,
        provider=summary.provider,
        status=summary.status,
        amount=summary.amount,
        currency=summary.currency,
        has_payment_url=summary.has_payment_url,
        created_at=summary.created_at.isoformat(),
        paid_at=summary.paid_at.isoformat() if summary.paid_at else None,
    )


def _order_callback_diagnostic_response(
    summary: OrderPaymentCallbackDiagnostic,
) -> OrderPaymentCallbackDiagnosticItem:
    return OrderPaymentCallbackDiagnosticItem(
        callback_id=summary.callback_id,
        provider=summary.provider,
        process_status=summary.process_status,
        failure_reason=summary.failure_reason,
        created_at=summary.created_at.isoformat(),
        processed_at=summary.processed_at.isoformat() if summary.processed_at else None,
    )


def _order_delivery_diagnostic_response(summary: OrderDeliveryDiagnostic) -> OrderDeliveryDiagnosticItem:
    return OrderDeliveryDiagnosticItem(
        delivery_record_id=summary.delivery_record_id,
        delivery_type=summary.delivery_type,
        status=summary.status,
        failure_reason=summary.failure_reason,
        has_inventory_item=summary.has_inventory_item,
        has_uploaded_file=summary.has_uploaded_file,
        has_telegram_chat=summary.has_telegram_chat,
        created_at=summary.created_at.isoformat(),
        updated_at=summary.updated_at.isoformat(),
        sent_at=summary.sent_at.isoformat() if summary.sent_at else None,
    )


def _order_external_fulfillment_diagnostic_response(
    summary: OrderExternalFulfillmentDiagnostic,
) -> OrderExternalFulfillmentDiagnosticItem:
    return OrderExternalFulfillmentDiagnosticItem(
        expected=summary.expected,
        attempt_count=summary.attempt_count,
        latest_attempt_status=summary.latest_attempt_status,
        latest_attempt_source=summary.latest_attempt_source,
        latest_attempt_at=summary.latest_attempt_at.isoformat() if summary.latest_attempt_at else None,
        latest_failure_stage=summary.latest_failure_stage,
        latest_failure_category=summary.latest_failure_category,
        latest_failure_retryable=summary.latest_failure_retryable,
        latest_upstream_status_code=summary.latest_upstream_status_code,
        latest_item_count=summary.latest_item_count,
        latest_delivery_record_linked=summary.latest_delivery_record_linked,
    )


def _order_trc20_direct_diagnostic_response(
    summary: OrderTrc20DirectDiagnostic,
) -> OrderTrc20DirectDiagnosticItem:
    return OrderTrc20DirectDiagnosticItem(
        expected=summary.expected,
        transfer_count=summary.transfer_count,
        latest_match_status=summary.latest_match_status,
        latest_confirmations=summary.latest_confirmations,
        latest_matched_at=summary.latest_matched_at.isoformat() if summary.latest_matched_at else None,
        latest_amount=summary.latest_amount,
    )


def _ledger_balance_response(balance: LedgerBalance) -> TenantLedgerBalanceResponse:
    return TenantLedgerBalanceResponse(
        account_type=balance.account_type,
        currency=balance.currency,
        pending_balance=balance.pending_balance,
        available_balance=balance.available_balance,
        frozen_balance=balance.frozen_balance,
    )


def _ledger_balance_audit_response(audit: LedgerBalanceAudit) -> TenantLedgerBalanceAuditResponse:
    return TenantLedgerBalanceAuditResponse(
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


def _withdrawal_response(withdrawal: WithdrawalSummary) -> TenantWithdrawalItem:
    return TenantWithdrawalItem(
        withdrawal_id=withdrawal.withdrawal_id,
        amount=withdrawal.amount,
        currency=withdrawal.currency,
        network=withdrawal.network,
        address_masked=_mask_finance_address(withdrawal.address),
        status=withdrawal.status,
        requested_at=withdrawal.requested_at.isoformat(),
        payout_reference=withdrawal.payout_reference,
        payout_proof_url=withdrawal.payout_proof_url,
        reviewed_at=withdrawal.reviewed_at.isoformat() if withdrawal.reviewed_at is not None else None,
        completed_at=withdrawal.completed_at.isoformat() if withdrawal.completed_at is not None else None,
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


def _safe_finance_error_detail(exc: ValueError) -> str:
    text = str(exc)
    if any(keyword in text.lower() for keyword in ("address", "地址", "token", "secret", "credential")):
        return "财务请求参数无效"
    return text or "财务请求参数无效"
