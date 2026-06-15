export type AdminWebWorkspace = {
  workspace_id: string
  kind: string
  role: string
  title: string
  tenant_public_id?: string | null
  bot_username?: string | null
  tenant_status?: string | null
  bot_status?: string | null
  supplier_enabled: boolean
  reseller_enabled: boolean
}

export type AdminWebUser = {
  telegram_user_id: number
  username?: string | null
  first_name?: string | null
  is_platform_admin: boolean
}

export type AdminWebSession = {
  user: AdminWebUser
  workspaces: AdminWebWorkspace[]
  current_workspace_id?: string | null
}

export type AdminWebTenantOverview = {
  workspace: AdminWebWorkspace
  tenant_public_id: string
  store_name: string
  tenant_status: string
  bot_username?: string | null
  bot_status?: string | null
  products: {
    total_count: number
    published_count: number
    available_inventory_count: number
  }
  orders: {
    total_count: number
    pending_count: number
    paid_count: number
    delivered_count: number
  }
  payments: {
    total_count: number
    enabled_count: number
    providers: AdminWebTenantPaymentProviderOverview[]
  }
  subscription: {
    status?: string | null
    plan_code?: string | null
    current_period_ends_at?: string | null
  }
  finance: {
    currency: string
    pending_balance: string
    available_balance: string
    frozen_balance: string
    pending_withdrawal_count: number
  }
  supply: {
    supplier_enabled: boolean
    reseller_enabled: boolean
    supplier_offer_count: number
    reseller_product_count: number
  }
}

export type AdminWebTenantStoreSettings = {
  store_name: string
  welcome_text: string
  support_text: string
  order_timeout_minutes: number
  self_sale_enabled: boolean
  supplier_enabled: boolean
  reseller_enabled: boolean
}

export type AdminWebTenantStoreSettingsPayload = {
  store_name?: string
  welcome_text?: string
  support_text?: string
  order_timeout_minutes?: number
  self_sale_enabled?: boolean
  supplier_enabled?: boolean
  reseller_enabled?: boolean
}

export type AdminWebTenantPaymentProviderOverview = {
  provider_name: string
  display_name: string
  enabled: boolean
  scope_type: string
  key_configured: boolean
  create_payment_available: boolean
}

export type AdminWebPaymentProviderName = "epusdt_gmpay" | "epay_compatible"

export type AdminWebTenantPaymentProviderConfig = {
  provider: AdminWebPaymentProviderName
  display_name: string
  enabled: boolean
  scope_type: string
  gateway_url?: string | null
  merchant_id_masked?: string | null
  asset?: string | null
  network?: string | null
  payment_type?: string | null
  device?: string | null
  return_url_configured: boolean
  subject?: string | null
  key_configured: boolean
  create_payment_available: boolean
  callback_available: boolean
  query_order_available: boolean
  reconcile_available: boolean
  production_ready: boolean
  staging_verified: boolean
  offline_only: boolean
}

export type AdminWebTenantPaymentProviderConfigsResponse = {
  providers: AdminWebTenantPaymentProviderConfig[]
}

export type AdminWebBusinessPluginKind =
  | "payment"
  | "external_source"
  | "bot_feature"
  | "admin_web_panel"
  | "background_job"
  | "webhook_handler"
  | "tenant_tool"

export type AdminWebBusinessPluginCapability = {
  plugin_id: string
  provider_name?: string | null
  kind: AdminWebBusinessPluginKind
  name: string
  version: string
  contract_version: string
  capabilities: Record<string, boolean>
  production_ready: boolean
  staging_verified: boolean
  offline_only: boolean
  tenant_configurable: boolean
  platform_configurable: boolean
  requires_tenant_enablement: boolean
  workspace_configured?: boolean | null
  workspace_enabled?: boolean | null
  scope_type?: string | null
  active_connection_count: number
  disabled_connection_count: number
}

export type AdminWebBusinessPluginCapabilitiesResponse = {
  workspace?: AdminWebWorkspace | null
  workspace_id: string
  workspace_kind: string
  dynamic_loading_enabled: boolean
  remote_code_enabled: boolean
  real_external_integration_enabled: boolean
  plugins: AdminWebBusinessPluginCapability[]
}

export type AdminWebExternalSourceProvider = {
  provider_name: string
  integration_kind: string
  contract_name?: string | null
  production_ready: boolean
  staging_verified: boolean
  catalog_sync_available: boolean
  catalog_context_available: boolean
  catalog_product_available: boolean
  catalog_product_context_available: boolean
  order_available: boolean
  order_context_available: boolean
  delivery_available: boolean
  delivery_context_available: boolean
  auto_fulfillment_idempotent_available: boolean
}

export type AdminWebExternalSourceConnection = {
  connection_handle: string
  provider_name: string
  source_key: string
  display_name: string
  status: "active" | "disabled" | string
  credential_field_count: number
  created_at?: string | null
  last_used_at?: string | null
}

export type AdminWebExternalSourceConnectionsResponse = {
  providers: AdminWebExternalSourceProvider[]
  connections: AdminWebExternalSourceConnection[]
}

export type AdminWebCreateExternalSourceConnectionPayload = {
  provider_name: string
  source_key?: string
  display_name: string
  credentials: Record<string, string>
}

export type AdminWebSyncExternalCatalogPayload = {
  connection_handle: string
  cursor?: string
  limit?: number
  max_pages?: number
}

export type AdminWebSyncedExternalCatalogProduct = {
  product_id?: number | null
  action: string
  status: string
  skipped_reason?: string | null
}

export type AdminWebExternalCatalogSyncResponse = {
  provider_name: string
  source_key: string
  created_count: number
  updated_count: number
  skipped_count: number
  next_cursor?: string | null
  products: AdminWebSyncedExternalCatalogProduct[]
}

export type AdminWebExternalSourceCatalogProduct = {
  product_id: number
  name: string
  category?: string | null
  status: string
  delivery_type: string
  price: string
  currency: string
  available_count: number
  updated_at?: string | null
}

export type AdminWebExternalSourceCatalogProductsResponse = {
  connection_handle: string
  provider_name: string
  source_key: string
  display_name: string
  status: string
  total_count: number
  limit: number
  offset: number
  items: AdminWebExternalSourceCatalogProduct[]
}

export type AdminWebPaymentProviderConfigPayload = {
  gateway_url?: string
  base_url?: string
  merchant_id?: string
  pid?: string
  key?: string
  secret_key?: string
  token?: string
  network?: string
  payment_type?: string
  device?: string
  return_url?: string
  subject?: string
}

export type AdminWebTenantProduct = {
  product_id: number
  name: string
  category?: string | null
  sort_order: number
  status: string
  delivery_type: string
  price: string
  currency: string
  available_count: number
}

export type AdminWebProductDeliveryType = "card_pool" | "card_fixed" | "telegram_invite" | "file_download"

export type AdminWebCreateProductPayload = {
  name: string
  price: string
  delivery_type: AdminWebProductDeliveryType
  description?: string
  category?: string | null
}

export type AdminWebProductMetadataPayload = {
  category?: string | null
  sort_order?: number
}

export type AdminWebProductSalesPayload = {
  price?: string
  status?: "draft" | "on" | "off"
}

export type AdminWebProductBatchStatusPayload = {
  product_ids: number[]
  status: "on" | "off"
}

export type AdminWebProductBatchStatusResult = {
  status: "on" | "off" | string
  updated_count: number
  products: AdminWebTenantProduct[]
}

export type AdminWebProductInventoryImportPayload = {
  items: string[]
}

export type AdminWebProductInventoryImportResult = {
  product_id: number
  added_count: number
  existing_count: number
  input_duplicate_count: number
  available_count: number
}

export type AdminWebProductDeliveryFileResult = {
  product_id: number
  filename: string
  size_bytes: number
  content_type?: string | null
  risk_level: string
  scan_message: string
  bound: boolean
}

export type AdminWebTenantProductsResponse = {
  total_count: number
  limit: number
  offset: number
  items: AdminWebTenantProduct[]
}

export type AdminWebProductStatusFilter = "all" | "draft" | "on" | "off"

export type AdminWebTenantProductFilters = {
  limit?: number
  offset?: number
  query?: string
  status?: AdminWebProductStatusFilter
  delivery_type?: "all" | AdminWebProductDeliveryType
  category?: string
}

export type AdminWebTenantOrder = {
  out_trade_no: string
  source_type: string
  amount: string
  currency: string
  status: string
  payment_mode: string
  buyer_telegram_user_id: number
  created_at: string
  expires_at: string
  paid_at?: string | null
  delivered_at?: string | null
}

export type AdminWebTenantOrdersResponse = {
  total_count: number
  limit: number
  offset: number
  items: AdminWebTenantOrder[]
}

export type AdminWebOrderStatusFilter =
  | "all"
  | "pending"
  | "paid"
  | "delivered"
  | "expired"
  | "completed"
  | "refunded"
  | "partially_refunded"

export type AdminWebOrderSourceTypeFilter = "all" | "self" | "reseller" | "subscription"

export type AdminWebOrderPaymentModeFilter =
  | "all"
  | "tenant_direct"
  | "platform_escrow"
  | "platform_subscription"

export type AdminWebTenantOrderFilters = {
  limit?: number
  offset?: number
  out_trade_no?: string
  status?: AdminWebOrderStatusFilter
  source_type?: AdminWebOrderSourceTypeFilter
  payment_mode?: AdminWebOrderPaymentModeFilter
}

export type AdminWebOrderPaymentDiagnostic = {
  provider: string
  status: string
  amount: string
  currency: string
  has_payment_url: boolean
  created_at: string
  paid_at?: string | null
}

export type AdminWebOrderPaymentCallbackDiagnostic = {
  provider: string
  process_status: string
  failure_reason: string
  created_at: string
  processed_at?: string | null
}

export type AdminWebOrderDeliveryDiagnostic = {
  delivery_type: string
  status: string
  failure_reason?: string | null
  has_inventory_item: boolean
  has_uploaded_file: boolean
  has_telegram_chat: boolean
  created_at: string
  updated_at: string
  sent_at?: string | null
}

export type AdminWebOrderExternalFulfillmentDiagnostic = {
  expected: boolean
  attempt_count: number
  latest_attempt_status?: string | null
  latest_attempt_trigger?: string | null
  latest_attempt_at?: string | null
  latest_failure_stage?: string | null
  latest_failure_category?: string | null
  latest_failure_retryable?: boolean | null
  latest_upstream_status_code?: number | null
  latest_item_count: number
  latest_delivery_record_linked: boolean
}

export type AdminWebOrderTrc20DirectDiagnostic = {
  expected: boolean
  transfer_count: number
  latest_match_status?: string | null
  latest_confirmations?: number | null
  latest_matched_at?: string | null
  latest_amount?: string | null
}

export type AdminWebTenantOrderDiagnostics = {
  out_trade_no: string
  source_type: string
  status: string
  payment_mode: string
  payment_provider?: string | null
  amount: string
  currency: string
  created_at: string
  expires_at: string
  paid_at?: string | null
  delivered_at?: string | null
  payment_count: number
  callback_count: number
  callback_status_counts: Record<string, number>
  payments: AdminWebOrderPaymentDiagnostic[]
  callbacks: AdminWebOrderPaymentCallbackDiagnostic[]
  delivery?: AdminWebOrderDeliveryDiagnostic | null
  external_fulfillment: AdminWebOrderExternalFulfillmentDiagnostic
  trc20_direct: AdminWebOrderTrc20DirectDiagnostic
}

export type AdminWebPaymentCallbackFailureObservation = {
  created_at: string
  processed_at?: string | null
  out_trade_no: string
  order_status: string
  provider: string
  process_status: string
  failure_reason: string
}

export type AdminWebPaymentCallbackRejectionObservation = {
  created_at: string
  provider: string
  reason_category: string
  failure_reason: string
  http_status: number
  out_trade_no?: string | null
  order_status?: string | null
  payload_field_count: number
}

export type AdminWebExternalFulfillmentAttemptObservation = {
  created_at: string
  started_at: string
  finished_at: string
  out_trade_no: string
  provider_name: string
  source_key: string
  attempt_source: string
  status: string
  imported: boolean
  item_count: number
  failure_reason?: string | null
  failure_stage?: string | null
  failure_category?: string | null
  failure_retryable?: boolean | null
  upstream_status_code?: number | null
}

export type AdminWebTenantOrderObservability = {
  limit: number
  callback_failures: AdminWebPaymentCallbackFailureObservation[]
  callback_rejections: AdminWebPaymentCallbackRejectionObservation[]
  external_fulfillment_attempts: AdminWebExternalFulfillmentAttemptObservation[]
}

export type AdminWebTenantOrderObservabilityFilters = {
  limit?: number
  out_trade_no?: string
}

export type AdminWebTenantSubscriptionInvoice = {
  out_trade_no: string
  amount: string
  currency: string
  status: string
  paid_at?: string | null
  created_at: string
}

export type AdminWebTenantSubscriptionDashboard = {
  status: string
  plan_code?: string | null
  plan_name?: string | null
  monthly_price?: string | null
  currency?: string | null
  trial_days?: number | null
  grace_days?: number | null
  trial_ends_at?: string | null
  current_period_ends_at?: string | null
  subscription_ends_at?: string | null
  grace_ends_at?: string | null
  suspended_at?: string | null
  data_retention_until?: string | null
  invoices: AdminWebTenantSubscriptionInvoice[]
}

export type AdminWebCreateTenantSubscriptionRenewalOrderPayload = {
  months: number
}

export type AdminWebTenantSubscriptionRenewalOrder = {
  out_trade_no: string
  amount: string
  currency: string
  months: number
  expires_at: string
  payment_available: boolean
  payment_provider?: string | null
  payment_url?: string | null
  payment_failure_reason?: string | null
}

export type AdminWebTenantFinanceBalance = {
  account_type: string
  currency: string
  pending_balance: string
  available_balance: string
  frozen_balance: string
}

export type AdminWebTenantFinanceAudit = {
  account_type: string
  currency: string
  stored_pending_balance: string
  stored_available_balance: string
  stored_frozen_balance: string
  computed_pending_balance: string
  computed_available_balance: string
  computed_frozen_balance: string
  pending_difference: string
  available_difference: string
  frozen_difference: string
  is_balanced: boolean
}

export type AdminWebTenantWithdrawal = {
  amount: string
  currency: string
  network: string
  address_masked: string
  status: string
  requested_at: string
  reviewed_at?: string | null
  completed_at?: string | null
}

export type AdminWebCreateTenantWithdrawalPayload = {
  amount: string
  network: string
  address: string
  currency?: string
}

export type AdminWebTenantFinanceDashboard = {
  balance: AdminWebTenantFinanceBalance
  audit: AdminWebTenantFinanceAudit
  withdrawals: AdminWebTenantWithdrawal[]
}

export type AdminWebTenantAuditLog = {
  created_at: string
  actor_telegram_user_id?: number | null
  actor_username?: string | null
  action: string
  target_type?: string | null
  metadata: Record<string, unknown>
}

export type AdminWebTenantAuditLogsResponse = {
  limit: number
  items: AdminWebTenantAuditLog[]
}

export type AdminWebTenantAuditLogFilters = {
  limit?: number
  action?: string
  target_type?: string
}

export type AdminWebTenantApiKey = {
  credential_handle: string
  name: string
  key_prefix: string
  status: string
  scopes: string[]
  ip_allowlist: string[]
  created_at?: string | null
  last_used_at?: string | null
}

export type AdminWebTenantApiKeysResponse = {
  limit: number
  keys: AdminWebTenantApiKey[]
}

export type AdminWebCreateTenantApiKeyPayload = {
  name: string
  scopes?: string[]
  ip_allowlist?: string[]
}

export type AdminWebCreatedTenantApiKey = AdminWebTenantApiKey & {
  plain_key: string
}

export type AdminWebTenantApiKeyRevokePayload = {
  credential_handle: string
}

export type AdminWebTenantApiKeyRevokeResult = {
  credential_handle: string
  revoked: boolean
}

export type AdminWebTenantReportType = "orders" | "payments" | "inventory" | "ledger"

export type AdminWebTenantReportTypeFilter = "all" | AdminWebTenantReportType

export type AdminWebTenantReportStatusFilter =
  | "all"
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "expired"

export type AdminWebTenantReportExportJob = {
  report_type: AdminWebTenantReportType
  scope_type: string
  status: AdminWebTenantReportStatusFilter
  row_count: number
  download_available: boolean
  download_handle?: string | null
  failure_reason?: string | null
  expires_at?: string | null
  created_at: string
  started_at?: string | null
  finished_at?: string | null
}

export type AdminWebTenantReportExportJobsResponse = {
  status: AdminWebTenantReportStatusFilter
  report_type: AdminWebTenantReportTypeFilter
  limit: number
  export_jobs: AdminWebTenantReportExportJob[]
}

export type AdminWebTenantReportExportJobFilters = {
  status?: AdminWebTenantReportStatusFilter
  report_type?: AdminWebTenantReportTypeFilter
  limit?: number
}

export type AdminWebCreateTenantReportExportJobPayload = {
  report_type: AdminWebTenantReportType
}

export type AdminWebTenantReportDownloadFile = {
  blob: Blob
  filename: string
}

export type AdminWebTenantRiskStatusFilter = "all" | "open" | "reviewing" | "resolved" | "rejected" | "closed"

export type AdminWebTenantRiskDispute = {
  out_trade_no: string
  buyer_telegram_user_id: number
  source_type: string
  order_status: string
  amount: string
  currency: string
  status: string
  reason?: string | null
  resolution?: string | null
  created_at: string
  updated_at: string
}

export type AdminWebTenantRiskAfterSale = {
  out_trade_no: string
  buyer_telegram_user_id: number
  source_type: string
  order_status: string
  amount: string
  currency: string
  case_type: string
  status: string
  requested_amount?: string | null
  refunded_amount: string
  reason?: string | null
  resolution?: string | null
  created_at: string
  updated_at: string
}

export type AdminWebTenantRiskDashboard = {
  status: AdminWebTenantRiskStatusFilter
  limit: number
  disputes: AdminWebTenantRiskDispute[]
  after_sales: AdminWebTenantRiskAfterSale[]
}

export type AdminWebTenantRiskFilters = {
  status?: AdminWebTenantRiskStatusFilter
  limit?: number
}

export type AdminWebSupplierOffer = {
  supplier_offer_id: number
  product_name: string
  delivery_type: string
  suggested_price: string
  min_sale_price?: string | null
  supplier_cost: string
  currency: string
  available_count: number
  requires_approval: boolean
  status: string
}

export type AdminWebSupplyMarketOffer = {
  supplier_offer_id: number
  product_name: string
  category?: string | null
  delivery_type: string
  suggested_price: string
  min_sale_price?: string | null
  currency: string
  available_count: number
  requires_approval: boolean
  reseller_rule_status?: string | null
  can_create_reseller_product: boolean
  supplier_cost: string
  effective_min_sale_price?: string | null
}

export type AdminWebSupplierApplication = {
  supplier_application_id: string
  supplier_offer_id: number
  reseller_store_name: string
  product_name: string
  status: string
  pricing_value: string
  min_sale_price?: string | null
  currency: string
  updated_at: string
}

export type AdminWebSupplierRule = {
  supplier_rule_id: string
  supplier_offer_id: number
  reseller_store_name: string
  product_name: string
  status: string
  pricing_value: string
  min_sale_price?: string | null
  currency: string
  updated_at: string
}

export type AdminWebResellerApplication = {
  supplier_offer_id: number
  product_name: string
  status: string
  pricing_value: string
  min_sale_price?: string | null
  currency: string
  updated_at: string
}

export type AdminWebResellerProduct = {
  reseller_product_id: number
  supplier_offer_id: number
  display_name: string
  category?: string | null
  sort_order: number
  delivery_type: string
  sale_price: string
  currency: string
  status: string
  available_count: number
}

export type AdminWebSupplyDashboard = {
  supplier_enabled: boolean
  reseller_enabled: boolean
  limit: number
  supplier_offers: AdminWebSupplierOffer[]
  supplier_applications: AdminWebSupplierApplication[]
  supplier_rules: AdminWebSupplierRule[]
  market_offers: AdminWebSupplyMarketOffer[]
  reseller_applications: AdminWebResellerApplication[]
  reseller_products: AdminWebResellerProduct[]
}

export type AdminWebSupplyDashboardFilters = {
  market_query?: string
  market_delivery_type?: "all" | "card_pool" | "card_fixed" | "file_download"
  market_access?: "all" | "ready" | "open" | "approval_required" | "pending" | "active" | "rejected"
  market_min_price?: string
  market_max_price?: string
  market_stock?: "all" | "available" | "empty"
  market_category?: string
}

export type AdminWebSupplyApplicationPayload = {
  supplier_offer_id: number
}

export type AdminWebCreateResellerProductPayload = {
  supplier_offer_id: number
  sale_price: string
  display_name?: string
}

export type AdminWebResellerProductMetadataPayload = {
  category?: string | null
  sort_order?: number
}

export type AdminWebResellerProductSalesPayload = {
  display_name?: string | null
  sale_price?: string
}

export type AdminWebSupplierApplicationReviewPayload = {
  supplier_application_id: string
  action: "approve" | "reject"
}

export type AdminWebCreateSupplierOfferPayload = {
  product_id: number
  suggested_price: string
  min_sale_price?: string
  requires_approval: boolean
}

export type AdminWebCreatedSupplierOffer = {
  supplier_offer_id: number
  product_name: string
  delivery_type: string
  suggested_price: string
  min_sale_price?: string | null
  supplier_cost: string
  currency: string
  requires_approval: boolean
  status: string
}

export type AdminWebSupplierOfferApprovalPayload = {
  requires_approval: boolean
}

export type AdminWebSupplierOfferApproval = {
  supplier_offer_id: number
  requires_approval: boolean
  status: string
}

export type AdminWebSupplierRulePayload = {
  supplier_rule_id: string
  pricing_value: string
  min_sale_price?: string
}

export type AdminWebSupplierRuleUpdate = AdminWebSupplierRule

export type AdminWebCreatedResellerProduct = {
  reseller_product_id: number
  supplier_offer_id: number
  display_name: string
  sale_price: string
  currency: string
  status: string
}

export type AdminWebPlatformTenantBot = {
  tenant_public_id: string
  store_name: string
  tenant_status: string
  bot_username?: string | null
  bot_status?: string | null
  webhook_status: string
  webhook_reset_available: boolean
  owner_telegram_user_id: number
  owner_username?: string | null
  subscription_status?: string | null
  plan_code?: string | null
  plan_name?: string | null
  current_period_ends_at?: string | null
  trial_ends_at?: string | null
  subscription_ends_at?: string | null
  last_health_checked_at?: string | null
  has_last_error: boolean
  created_at: string
}

export type AdminWebPlatformStats = {
  tenant_count: number
  active_tenant_count: number
  suspended_tenant_count: number
  trial_subscription_count: number
  active_subscription_count: number
  grace_subscription_count: number
  suspended_subscription_count: number
  retention_expired_subscription_count: number
  active_bot_count: number
  pending_withdrawal_count: number
  banned_user_count: number
  disabled_supplier_offer_count: number
}

export type AdminWebPlatformPaymentProvider = {
  provider_name: string
  display_name: string
  integration_kind: string
  contract_name: string
  production_ready: boolean
  staging_verified: boolean
  tenant_configurable: boolean
  platform_configurable: boolean
  create_payment_available: boolean
  callback_available: boolean
  query_order_available: boolean
  reconcile_available: boolean
  offline_only: boolean
  supported_assets: string[]
  supported_networks: string[]
  configured_tenant_count: number
  enabled_tenant_count: number
  missing_config_tenant_count: number
  platform_configured: boolean
  platform_enabled: boolean
}

export type AdminWebPlatformWithdrawal = {
  withdrawal_id: number
  tenant_public_id?: string | null
  store_name?: string | null
  amount: string
  currency: string
  network: string
  address_masked: string
  status: string
  requested_at: string
  reviewed_at?: string | null
  completed_at?: string | null
}

export type AdminWebPlatformSubscriptionPlan = {
  code: string
  name: string
  monthly_price: string
  currency: string
  trial_days: number
  grace_days: number
  enabled: boolean
  created_at?: string | null
  updated_at?: string | null
}

export type AdminWebPlatformSubscriptionAttentionItem = {
  tenant_public_id: string
  store_name: string
  owner_telegram_user_id: number
  owner_username?: string | null
  tenant_status: string
  subscription_status: string
  plan_code?: string | null
  plan_name?: string | null
  attention_reason: string
  trial_ends_at?: string | null
  current_period_ends_at?: string | null
  subscription_ends_at?: string | null
  grace_ends_at?: string | null
  suspended_at?: string | null
  data_retention_until?: string | null
}

export type AdminWebPlatformTenantSubscriptionGrantDaysPayload = {
  days: number
  reason?: string
}

export type AdminWebPlatformTenantSubscriptionSetPeriodEndPayload = {
  period_ends_at: string
  reason?: string
}

export type AdminWebPlatformTenantSubscriptionAdjustment = {
  tenant_public_id: string
  status: string
  previous_period_ends_at?: string | null
  new_period_ends_at: string
  action: string
}

export type AdminWebPlatformRiskBannedUser = {
  telegram_user_id: number
  username?: string | null
  is_banned: boolean
  ban_source?: string | null
  latest_action?: string | null
  latest_action_at?: string | null
  reason?: string | null
  trigger_rule?: string | null
  blocked_count?: number | null
  threshold?: number | null
  window_seconds?: number | null
  created_at?: string | null
  updated_at?: string | null
}

export type AdminWebPlatformRiskAuditLog = {
  created_at: string
  action: string
  target_type?: string | null
  actor_telegram_user_id?: number | null
  actor_username?: string | null
  target_telegram_user_id?: number | null
  previous_status?: string | null
  new_status?: string | null
  reason?: string | null
  risk_rule?: string | null
  blocked_count?: number | null
  threshold?: number | null
  window_seconds?: number | null
}

export type AdminWebPlatformSupplierOffer = {
  supplier_offer_id: number
  supplier_store_name: string
  product_name: string
  delivery_type: string
  suggested_price: string
  min_sale_price?: string | null
  supplier_cost: string
  currency: string
  available_count: number
  requires_approval: boolean
  status: string
  created_at: string
  updated_at: string
}

export type AdminWebPlatformDashboard = {
  stats: AdminWebPlatformStats
  tenants: AdminWebPlatformTenantBot[]
  payment_providers: AdminWebPlatformPaymentProvider[]
  withdrawals: AdminWebPlatformWithdrawal[]
  subscription_plans: AdminWebPlatformSubscriptionPlan[]
  subscription_attention: AdminWebPlatformSubscriptionAttentionItem[]
  banned_users: AdminWebPlatformRiskBannedUser[]
  risk_audit_logs: AdminWebPlatformRiskAuditLog[]
  supplier_offers: AdminWebPlatformSupplierOffer[]
}

export type AdminWebPlatformDashboardFilters = {
  tenant_limit?: number
  tenant_offset?: number
  tenant_query?: string
  tenant_status?: "all" | "trial" | "active" | "grace" | "suspended" | "retention_expired"
  bot_status?: "all" | "active" | "disabled" | "missing"
  subscription_status?: "all" | "trial" | "active" | "grace" | "suspended" | "retention_expired"
}

export type AdminWebPlatformBotStatusPayload = {
  status: "active" | "disabled"
  reason?: string
}

export type AdminWebPlatformBotStatus = {
  tenant_public_id: string
  bot_username: string
  previous_status: string
  status: string
  reason?: string | null
  webhook_reset_available: boolean
}

export type AdminWebPlatformBotWebhookResetPayload = {
  reason?: string
}

export type AdminWebPlatformBotWebhookReset = {
  tenant_public_id: string
  bot_username: string
  status: string
  webhook_status: string
  reason?: string | null
  telegram_webhook_called: boolean
}

export type AdminWebPlatformTenantSuspensionStatusPayload = {
  status: "active" | "suspended"
  reason?: string
}

export type AdminWebPlatformTenantSuspensionStatus = {
  tenant_public_id: string
  previous_status: string
  status: string
  reason?: string | null
}

export type AdminWebPlatformRiskBanStatusPayload = {
  status: "active" | "banned"
  reason?: string
}

export type AdminWebPlatformWithdrawalCompletePayload = {
  admin_note?: string
  payout_reference?: string
  payout_proof_url?: string
}

export type AdminWebPlatformWithdrawalRejectPayload = {
  admin_note?: string
}

export type AdminWebPlatformSubscriptionPlanCreatePayload = {
  code: string
  name: string
  monthly_price: string
  currency?: string
  trial_days?: number
  grace_days?: number
  enabled?: boolean
  reason?: string
}

export type AdminWebPlatformSubscriptionPlanUpdatePayload = {
  name?: string
  monthly_price?: string
  currency?: string
  trial_days?: number
  grace_days?: number
  reason?: string
}

export type AdminWebPlatformSubscriptionPlanStatusPayload = {
  enabled: boolean
  reason?: string
}

export type AdminWebPlatformSupplierOfferStatusPayload = {
  status: "on" | "disabled"
  reason?: string
}

export type TelegramAdminWebSessionPayload = {
  init_data: string
  entrypoint: "master" | "tenant"
  tenant_public_id?: string
}

export type BindingCodeAdminWebSessionPayload = {
  code: string
}

export class AdminWebApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = "AdminWebApiError"
    this.status = status
  }
}

const ADMIN_WEB_API_BASE = "/api/v1/admin-web"

export async function getAdminWebSession(): Promise<AdminWebSession> {
  return adminWebRequest<AdminWebSession>("/session")
}

export async function getAdminWebWorkspaces(): Promise<AdminWebWorkspace[]> {
  return adminWebRequest<AdminWebWorkspace[]>("/workspaces")
}

export async function getAdminWebTenantOverview(): Promise<AdminWebTenantOverview> {
  return adminWebRequest<AdminWebTenantOverview>("/tenant/overview")
}

export async function getAdminWebTenantStoreSettings(): Promise<AdminWebTenantStoreSettings> {
  return adminWebRequest<AdminWebTenantStoreSettings>("/tenant/settings")
}

export async function updateAdminWebTenantStoreSettings(
  payload: AdminWebTenantStoreSettingsPayload,
): Promise<AdminWebTenantStoreSettings> {
  return adminWebRequest<AdminWebTenantStoreSettings>("/tenant/settings", {
    method: "PATCH",
    body: payload,
  })
}

export async function getAdminWebTenantProducts(
  options: number | AdminWebTenantProductFilters = 10,
): Promise<AdminWebTenantProductsResponse> {
  const filters = typeof options === "number" ? { limit: options } : options
  const params = buildAdminWebQueryParams({
    limit: filters.limit ?? 10,
    offset: filters.offset ?? 0,
    query: filters.query,
    status: filters.status === "all" ? undefined : filters.status,
    delivery_type: filters.delivery_type === "all" ? undefined : filters.delivery_type,
    category: filters.category,
  })
  return adminWebRequest<AdminWebTenantProductsResponse>(`/tenant/products?${params}`)
}

export async function createAdminWebTenantProduct(
  payload: AdminWebCreateProductPayload,
): Promise<AdminWebTenantProduct> {
  return adminWebRequest<AdminWebTenantProduct>("/tenant/products", {
    method: "POST",
    body: payload,
  })
}

export async function updateAdminWebProductMetadata(
  productId: number,
  payload: AdminWebProductMetadataPayload,
): Promise<AdminWebTenantProduct> {
  return adminWebRequest<AdminWebTenantProduct>(`/tenant/products/${productId}/metadata`, {
    method: "PATCH",
    body: payload,
  })
}

export async function updateAdminWebProductSales(
  productId: number,
  payload: AdminWebProductSalesPayload,
): Promise<AdminWebTenantProduct> {
  return adminWebRequest<AdminWebTenantProduct>(`/tenant/products/${productId}/sales`, {
    method: "PATCH",
    body: payload,
  })
}

export async function batchUpdateAdminWebProductStatus(
  payload: AdminWebProductBatchStatusPayload,
): Promise<AdminWebProductBatchStatusResult> {
  return adminWebRequest<AdminWebProductBatchStatusResult>("/tenant/products/status", {
    method: "PATCH",
    body: payload,
  })
}

export async function importAdminWebProductInventory(
  productId: number,
  payload: AdminWebProductInventoryImportPayload,
): Promise<AdminWebProductInventoryImportResult> {
  return adminWebRequest<AdminWebProductInventoryImportResult>(
    `/tenant/products/${productId}/inventory/import`,
    {
      method: "POST",
      body: payload,
    },
  )
}

export async function uploadAdminWebProductDeliveryFile(
  productId: number,
  file: File,
): Promise<AdminWebProductDeliveryFileResult> {
  const body = new FormData()
  body.set("file", file)
  return adminWebRequest<AdminWebProductDeliveryFileResult>(
    `/tenant/products/${productId}/delivery-file`,
    {
      method: "POST",
      body,
    },
  )
}

export async function getAdminWebTenantOrders(
  options: number | AdminWebTenantOrderFilters = 10,
): Promise<AdminWebTenantOrdersResponse> {
  const filters = typeof options === "number" ? { limit: options } : options
  const params = buildAdminWebQueryParams({
    limit: filters.limit ?? 10,
    offset: filters.offset ?? 0,
    out_trade_no: filters.out_trade_no,
    status: filters.status === "all" ? undefined : filters.status,
    source_type: filters.source_type === "all" ? undefined : filters.source_type,
    payment_mode: filters.payment_mode === "all" ? undefined : filters.payment_mode,
  })
  return adminWebRequest<AdminWebTenantOrdersResponse>(`/tenant/orders?${params}`)
}

export async function getAdminWebTenantOrderDiagnostics(
  outTradeNo: string,
): Promise<AdminWebTenantOrderDiagnostics> {
  return adminWebRequest<AdminWebTenantOrderDiagnostics>(
    `/tenant/orders/${encodeURIComponent(outTradeNo)}/diagnostics`,
  )
}

export async function getAdminWebTenantOrderObservability(
  filters: AdminWebTenantOrderObservabilityFilters = {},
): Promise<AdminWebTenantOrderObservability> {
  const params = buildAdminWebQueryParams({
    limit: filters.limit ?? 8,
    out_trade_no: filters.out_trade_no,
  })
  return adminWebRequest<AdminWebTenantOrderObservability>(`/tenant/orders/observability?${params}`)
}

export async function getAdminWebTenantSubscriptionDashboard(
  invoiceLimit = 8,
): Promise<AdminWebTenantSubscriptionDashboard> {
  return adminWebRequest<AdminWebTenantSubscriptionDashboard>(
    `/tenant/subscription?invoice_limit=${invoiceLimit}`,
  )
}

export async function createAdminWebTenantSubscriptionRenewalOrder(
  payload: AdminWebCreateTenantSubscriptionRenewalOrderPayload,
): Promise<AdminWebTenantSubscriptionRenewalOrder> {
  return adminWebRequest<AdminWebTenantSubscriptionRenewalOrder>("/tenant/subscription/renewal-orders", {
    method: "POST",
    body: payload,
  })
}

export async function getAdminWebTenantFinanceDashboard(
  withdrawalLimit = 8,
): Promise<AdminWebTenantFinanceDashboard> {
  return adminWebRequest<AdminWebTenantFinanceDashboard>(
    `/tenant/finance?withdrawal_limit=${withdrawalLimit}`,
  )
}

export async function createAdminWebTenantWithdrawal(
  payload: AdminWebCreateTenantWithdrawalPayload,
): Promise<AdminWebTenantWithdrawal> {
  return adminWebRequest<AdminWebTenantWithdrawal>("/tenant/finance/withdrawals", {
    method: "POST",
    body: payload,
  })
}

export async function getAdminWebTenantAuditLogs(
  filters: AdminWebTenantAuditLogFilters = {},
): Promise<AdminWebTenantAuditLogsResponse> {
  const params = buildAdminWebQueryParams({
    limit: filters.limit ?? 8,
    action: filters.action,
    target_type: filters.target_type,
  })
  return adminWebRequest<AdminWebTenantAuditLogsResponse>(`/tenant/audit-logs?${params}`)
}

export async function getAdminWebTenantApiKeys(limit = 8): Promise<AdminWebTenantApiKeysResponse> {
  return adminWebRequest<AdminWebTenantApiKeysResponse>(`/tenant/api-keys?limit=${limit}`)
}

export async function createAdminWebTenantApiKey(
  payload: AdminWebCreateTenantApiKeyPayload,
): Promise<AdminWebCreatedTenantApiKey> {
  return adminWebRequest<AdminWebCreatedTenantApiKey>("/tenant/api-keys", {
    method: "POST",
    body: payload,
  })
}

export async function revokeAdminWebTenantApiKey(
  payload: AdminWebTenantApiKeyRevokePayload,
): Promise<AdminWebTenantApiKeyRevokeResult> {
  return adminWebRequest<AdminWebTenantApiKeyRevokeResult>("/tenant/api-keys/revoke", {
    method: "POST",
    body: payload,
  })
}

export async function getAdminWebTenantReportExportJobs(
  filters: AdminWebTenantReportExportJobFilters = {},
): Promise<AdminWebTenantReportExportJobsResponse> {
  const params = buildAdminWebQueryParams({
    limit: filters.limit ?? 8,
    status: filters.status === "all" ? undefined : filters.status,
    report_type: filters.report_type === "all" ? undefined : filters.report_type,
  })
  return adminWebRequest<AdminWebTenantReportExportJobsResponse>(
    `/tenant/reports/export-jobs?${params}`,
  )
}

export async function createAdminWebTenantReportExportJob(
  payload: AdminWebCreateTenantReportExportJobPayload,
): Promise<AdminWebTenantReportExportJob> {
  return adminWebRequest<AdminWebTenantReportExportJob>("/tenant/reports/export-jobs", {
    method: "POST",
    body: payload,
  })
}

export async function downloadAdminWebTenantReportExportJob(
  downloadHandle: string,
): Promise<AdminWebTenantReportDownloadFile> {
  const response = await fetch(`${ADMIN_WEB_API_BASE}/tenant/reports/export-jobs/download`, {
    method: "POST",
    credentials: "include",
    headers: buildHeaders({ download_handle: downloadHandle }),
    body: JSON.stringify({ download_handle: downloadHandle }),
  })

  if (!response.ok) {
    throw new AdminWebApiError(response.status, await readErrorDetail(response))
  }

  return {
    blob: await response.blob(),
    filename: readDownloadFilename(response.headers.get("Content-Disposition")) ?? "report.csv",
  }
}

export async function getAdminWebTenantRiskDashboard(
  filters: AdminWebTenantRiskFilters = {},
): Promise<AdminWebTenantRiskDashboard> {
  const params = buildAdminWebQueryParams({
    limit: filters.limit ?? 8,
    status: filters.status ?? "open",
  })
  return adminWebRequest<AdminWebTenantRiskDashboard>(`/tenant/risk?${params}`)
}

export async function getAdminWebTenantPaymentConfigs(): Promise<AdminWebTenantPaymentProviderConfigsResponse> {
  return adminWebRequest<AdminWebTenantPaymentProviderConfigsResponse>("/tenant/payments/configs")
}

export async function getAdminWebBusinessPluginCapabilities(): Promise<AdminWebBusinessPluginCapabilitiesResponse> {
  return adminWebRequest<AdminWebBusinessPluginCapabilitiesResponse>("/business-plugins/capabilities")
}

export async function getAdminWebExternalSourceConnections(
  providerName?: string,
): Promise<AdminWebExternalSourceConnectionsResponse> {
  const params = buildAdminWebQueryParams({ provider_name: providerName })
  return adminWebRequest<AdminWebExternalSourceConnectionsResponse>(
    `/tenant/external-source-connections${params ? `?${params}` : ""}`,
  )
}

export async function createAdminWebExternalSourceConnection(
  payload: AdminWebCreateExternalSourceConnectionPayload,
): Promise<AdminWebExternalSourceConnection> {
  return adminWebRequest<AdminWebExternalSourceConnection>("/tenant/external-source-connections", {
    method: "POST",
    body: payload,
  })
}

export async function disableAdminWebExternalSourceConnection(
  connectionHandle: string,
): Promise<AdminWebExternalSourceConnection> {
  return adminWebRequest<AdminWebExternalSourceConnection>("/tenant/external-source-connections/disable", {
    method: "POST",
    body: { connection_handle: connectionHandle },
  })
}

export async function syncAdminWebExternalCatalog(
  payload: AdminWebSyncExternalCatalogPayload,
): Promise<AdminWebExternalCatalogSyncResponse> {
  return adminWebRequest<AdminWebExternalCatalogSyncResponse>("/tenant/external-sources/catalog/sync", {
    method: "POST",
    body: payload,
  })
}

export async function getAdminWebExternalSourceCatalogProducts(
  connectionHandle: string,
  options: { limit?: number; offset?: number } = {},
): Promise<AdminWebExternalSourceCatalogProductsResponse> {
  const params = buildAdminWebQueryParams({
    connection_handle: connectionHandle,
    limit: options.limit,
    offset: options.offset,
  })
  return adminWebRequest<AdminWebExternalSourceCatalogProductsResponse>(
    `/tenant/external-sources/catalog/products?${params}`,
  )
}

export async function updateAdminWebTenantPaymentConfig(
  providerName: AdminWebPaymentProviderName,
  payload: AdminWebPaymentProviderConfigPayload,
): Promise<AdminWebTenantPaymentProviderConfig> {
  return adminWebRequest<AdminWebTenantPaymentProviderConfig>(`/tenant/payments/${providerName}/config`, {
    method: "PUT",
    body: payload,
  })
}

export async function disableAdminWebTenantPaymentConfig(
  providerName: AdminWebPaymentProviderName,
): Promise<AdminWebTenantPaymentProviderConfig> {
  return adminWebRequest<AdminWebTenantPaymentProviderConfig>(`/tenant/payments/${providerName}/config`, {
    method: "DELETE",
  })
}

export async function getAdminWebSupplyDashboard(
  limit = 8,
  filters: AdminWebSupplyDashboardFilters = {},
): Promise<AdminWebSupplyDashboard> {
  const params = new URLSearchParams({ limit: String(limit) })
  for (const [key, value] of Object.entries(filters)) {
    const text = typeof value === "string" ? value.trim() : value
    if (typeof text === "string" && text !== "") {
      params.set(key, text)
    }
  }
  return adminWebRequest<AdminWebSupplyDashboard>(`/tenant/supply/dashboard?${params.toString()}`)
}

export async function createAdminWebSupplyApplication(
  payload: AdminWebSupplyApplicationPayload,
): Promise<AdminWebResellerApplication> {
  return adminWebRequest<AdminWebResellerApplication>("/tenant/supply/applications", {
    method: "POST",
    body: payload,
  })
}

export async function createAdminWebResellerProduct(
  payload: AdminWebCreateResellerProductPayload,
): Promise<AdminWebCreatedResellerProduct> {
  return adminWebRequest<AdminWebCreatedResellerProduct>("/tenant/supply/reseller-products", {
    method: "POST",
    body: payload,
  })
}

export async function updateAdminWebResellerProductMetadata(
  resellerProductId: number,
  payload: AdminWebResellerProductMetadataPayload,
): Promise<AdminWebResellerProduct> {
  return adminWebRequest<AdminWebResellerProduct>(
    `/tenant/supply/reseller-products/${resellerProductId}/metadata`,
    {
      method: "PATCH",
      body: payload,
    },
  )
}

export async function updateAdminWebResellerProductSales(
  resellerProductId: number,
  payload: AdminWebResellerProductSalesPayload,
): Promise<AdminWebResellerProduct> {
  return adminWebRequest<AdminWebResellerProduct>(
    `/tenant/supply/reseller-products/${resellerProductId}/sales`,
    {
      method: "PATCH",
      body: payload,
    },
  )
}

export async function reviewAdminWebSupplierApplication(
  payload: AdminWebSupplierApplicationReviewPayload,
): Promise<AdminWebSupplierApplication> {
  return adminWebRequest<AdminWebSupplierApplication>("/tenant/supply/supplier-applications/review", {
    method: "POST",
    body: payload,
  })
}

export async function createAdminWebSupplierOffer(
  payload: AdminWebCreateSupplierOfferPayload,
): Promise<AdminWebCreatedSupplierOffer> {
  return adminWebRequest<AdminWebCreatedSupplierOffer>("/tenant/supply/supplier-offers", {
    method: "POST",
    body: payload,
  })
}

export async function updateAdminWebSupplierOfferApproval(
  supplierOfferId: number,
  payload: AdminWebSupplierOfferApprovalPayload,
): Promise<AdminWebSupplierOfferApproval> {
  return adminWebRequest<AdminWebSupplierOfferApproval>(
    `/tenant/supply/supplier-offers/${supplierOfferId}/approval`,
    {
      method: "PATCH",
      body: payload,
    },
  )
}

export async function updateAdminWebSupplierRule(
  payload: AdminWebSupplierRulePayload,
): Promise<AdminWebSupplierRuleUpdate> {
  return adminWebRequest<AdminWebSupplierRuleUpdate>("/tenant/supply/supplier-rules", {
    method: "POST",
    body: payload,
  })
}

export async function getAdminWebPlatformDashboard(
  filters: AdminWebPlatformDashboardFilters = {},
): Promise<AdminWebPlatformDashboard> {
  const params = new URLSearchParams()
  if (typeof filters.tenant_limit === "number") {
    params.set("tenant_limit", String(filters.tenant_limit))
  }
  if (typeof filters.tenant_offset === "number") {
    params.set("tenant_offset", String(filters.tenant_offset))
  }
  if (filters.tenant_query?.trim()) {
    params.set("tenant_query", filters.tenant_query.trim())
  }
  if (filters.tenant_status && filters.tenant_status !== "all") {
    params.set("tenant_status", filters.tenant_status)
  }
  if (filters.bot_status && filters.bot_status !== "all") {
    params.set("bot_status", filters.bot_status)
  }
  if (filters.subscription_status && filters.subscription_status !== "all") {
    params.set("subscription_status", filters.subscription_status)
  }
  const query = params.toString()
  return adminWebRequest<AdminWebPlatformDashboard>(`/platform/dashboard${query ? `?${query}` : ""}`)
}

export async function updateAdminWebPlatformBotStatus(
  tenantPublicId: string,
  payload: AdminWebPlatformBotStatusPayload,
): Promise<AdminWebPlatformBotStatus> {
  return adminWebRequest<AdminWebPlatformBotStatus>(
    `/platform/bots/${encodeURIComponent(tenantPublicId)}/status`,
    {
      method: "PATCH",
      body: payload,
    },
  )
}

export async function resetAdminWebPlatformBotWebhook(
  tenantPublicId: string,
  payload: AdminWebPlatformBotWebhookResetPayload,
): Promise<AdminWebPlatformBotWebhookReset> {
  return adminWebRequest<AdminWebPlatformBotWebhookReset>(
    `/platform/bots/${encodeURIComponent(tenantPublicId)}/webhook/reset`,
    {
      method: "POST",
      body: payload,
    },
  )
}

export async function updateAdminWebPlatformTenantSuspensionStatus(
  tenantPublicId: string,
  payload: AdminWebPlatformTenantSuspensionStatusPayload,
): Promise<AdminWebPlatformTenantSuspensionStatus> {
  return adminWebRequest<AdminWebPlatformTenantSuspensionStatus>(
    `/platform/risk/tenants/${encodeURIComponent(tenantPublicId)}/suspension-status`,
    {
      method: "PATCH",
      body: payload,
    },
  )
}

export async function updateAdminWebPlatformUserBanStatus(
  telegramUserId: number,
  payload: AdminWebPlatformRiskBanStatusPayload,
): Promise<AdminWebPlatformRiskBannedUser> {
  return adminWebRequest<AdminWebPlatformRiskBannedUser>(
    `/platform/risk/users/${telegramUserId}/ban-status`,
    {
      method: "PATCH",
      body: payload,
    },
  )
}

export async function completeAdminWebPlatformWithdrawal(
  withdrawalId: number,
  payload: AdminWebPlatformWithdrawalCompletePayload,
): Promise<AdminWebPlatformWithdrawal> {
  return adminWebRequest<AdminWebPlatformWithdrawal>(
    `/platform/finance/withdrawals/${withdrawalId}/complete`,
    {
      method: "POST",
      body: payload,
    },
  )
}

export async function getAdminWebPlatformWithdrawal(
  withdrawalId: number,
): Promise<AdminWebPlatformWithdrawal> {
  return adminWebRequest<AdminWebPlatformWithdrawal>(
    `/platform/finance/withdrawals/${withdrawalId}`,
  )
}

export async function grantAdminWebPlatformTenantSubscriptionDays(
  tenantPublicId: string,
  payload: AdminWebPlatformTenantSubscriptionGrantDaysPayload,
): Promise<AdminWebPlatformTenantSubscriptionAdjustment> {
  return adminWebRequest<AdminWebPlatformTenantSubscriptionAdjustment>(
    `/platform/tenants/${encodeURIComponent(tenantPublicId)}/subscription/grant-days`,
    {
      method: "POST",
      body: payload,
    },
  )
}

export async function setAdminWebPlatformTenantSubscriptionPeriodEnd(
  tenantPublicId: string,
  payload: AdminWebPlatformTenantSubscriptionSetPeriodEndPayload,
): Promise<AdminWebPlatformTenantSubscriptionAdjustment> {
  return adminWebRequest<AdminWebPlatformTenantSubscriptionAdjustment>(
    `/platform/tenants/${encodeURIComponent(tenantPublicId)}/subscription/period-end`,
    {
      method: "PATCH",
      body: payload,
    },
  )
}

export async function rejectAdminWebPlatformWithdrawal(
  withdrawalId: number,
  payload: AdminWebPlatformWithdrawalRejectPayload,
): Promise<AdminWebPlatformWithdrawal> {
  return adminWebRequest<AdminWebPlatformWithdrawal>(
    `/platform/finance/withdrawals/${withdrawalId}/reject`,
    {
      method: "POST",
      body: payload,
    },
  )
}

export async function createAdminWebPlatformSubscriptionPlan(
  payload: AdminWebPlatformSubscriptionPlanCreatePayload,
): Promise<AdminWebPlatformSubscriptionPlan> {
  return adminWebRequest<AdminWebPlatformSubscriptionPlan>("/platform/subscription/plans", {
    method: "POST",
    body: payload,
  })
}

export async function updateAdminWebPlatformSubscriptionPlan(
  planCode: string,
  payload: AdminWebPlatformSubscriptionPlanUpdatePayload,
): Promise<AdminWebPlatformSubscriptionPlan> {
  return adminWebRequest<AdminWebPlatformSubscriptionPlan>(
    `/platform/subscription/plans/${encodeURIComponent(planCode)}`,
    {
      method: "PATCH",
      body: payload,
    },
  )
}

export async function updateAdminWebPlatformSubscriptionPlanStatus(
  planCode: string,
  payload: AdminWebPlatformSubscriptionPlanStatusPayload,
): Promise<AdminWebPlatformSubscriptionPlan> {
  return adminWebRequest<AdminWebPlatformSubscriptionPlan>(
    `/platform/subscription/plans/${encodeURIComponent(planCode)}/status`,
    {
      method: "PATCH",
      body: payload,
    },
  )
}

export async function updateAdminWebPlatformSupplierOfferStatus(
  supplierOfferId: number,
  payload: AdminWebPlatformSupplierOfferStatusPayload,
): Promise<AdminWebPlatformSupplierOffer> {
  return adminWebRequest<AdminWebPlatformSupplierOffer>(
    `/platform/supply/supplier-offers/${supplierOfferId}/status`,
    {
      method: "PATCH",
      body: payload,
    },
  )
}

export async function createTelegramAdminWebSession(
  payload: TelegramAdminWebSessionPayload,
): Promise<AdminWebSession> {
  return adminWebRequest<AdminWebSession>("/sessions/telegram", {
    method: "POST",
    body: payload,
  })
}

export async function createBindingCodeAdminWebSession(
  payload: BindingCodeAdminWebSessionPayload,
): Promise<AdminWebSession> {
  return adminWebRequest<AdminWebSession>("/sessions/binding-code", {
    method: "POST",
    body: payload,
  })
}

export async function selectAdminWebWorkspace(
  workspaceId: string,
): Promise<AdminWebSession> {
  return adminWebRequest<AdminWebSession>("/workspaces/select", {
    method: "POST",
    body: { workspace_id: workspaceId },
  })
}

export async function logoutAdminWebSession(): Promise<void> {
  await adminWebRequest<{ ok: boolean }>("/logout", {
    method: "POST",
  })
}

type AdminWebQueryValue = string | number | undefined | null

function buildAdminWebQueryParams(params: Record<string, AdminWebQueryValue>): string {
  const searchParams = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (typeof value === "number" && Number.isFinite(value)) {
      searchParams.set(key, String(value))
      continue
    }
    if (typeof value === "string") {
      const text = value.trim()
      if (text !== "") {
        searchParams.set(key, text)
      }
    }
  }
  return searchParams.toString()
}

async function adminWebRequest<T>(
  path: string,
  options: {
    method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE"
    body?: Record<string, unknown> | FormData
  } = {},
): Promise<T> {
  const requestBody: BodyInit | undefined =
    options.body instanceof FormData
      ? options.body
      : options.body
        ? JSON.stringify(options.body)
        : undefined

  const response = await fetch(`${ADMIN_WEB_API_BASE}${path}`, {
    method: options.method ?? "GET",
    credentials: "include",
    headers: buildHeaders(options.body),
    body: requestBody,
  })

  if (!response.ok) {
    throw new AdminWebApiError(response.status, await readErrorDetail(response))
  }

  return (await response.json()) as T
}

function buildHeaders(body?: Record<string, unknown> | FormData): Headers {
  const headers = new Headers()
  if (body && !(body instanceof FormData)) {
    headers.set("Content-Type", "application/json")
  }
  return headers
}

async function readErrorDetail(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown }
    if (typeof payload.detail === "string" && payload.detail.trim()) {
      return payload.detail
    }
  } catch {
    return "管理后台请求失败"
  }
  return "管理后台请求失败"
}

function readDownloadFilename(header: string | null): string | null {
  if (!header) {
    return null
  }
  const utf8Match = /filename\*=UTF-8''([^;]+)/i.exec(header)
  if (utf8Match) {
    try {
      return decodeURIComponent(utf8Match[1]).trim() || null
    } catch {
      return null
    }
  }
  const quotedMatch = /filename="([^"]+)"/i.exec(header)
  if (quotedMatch) {
    return quotedMatch[1].trim() || null
  }
  const plainMatch = /filename=([^;]+)/i.exec(header)
  return plainMatch?.[1]?.trim() || null
}
