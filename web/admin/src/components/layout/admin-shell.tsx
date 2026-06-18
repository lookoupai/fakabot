import * as React from "react"
import {
  AlertTriangleIcon,
  BotIcon,
  BoxesIcon,
  Building2Icon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CheckCircle2Icon,
  CircleDollarSignIcon,
  CopyIcon,
  DownloadIcon,
  KeyRoundIcon,
  LayoutDashboardIcon,
  ListTreeIcon,
  PauseCircleIcon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
  SettingsIcon,
  ShieldCheckIcon,
  StoreIcon,
  Trash2Icon,
  UsersIcon,
  WebhookIcon,
  type LucideIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  AdminWebApiError,
  completeAdminWebPlatformWithdrawal,
  createAdminWebExternalSourceConnection,
  createAdminWebTenantApiKey,
  createAdminWebTenantReportExportJob,
  createAdminWebPlatformSubscriptionPlan,
  createAdminWebResellerProduct,
  createAdminWebSupplierOffer,
  createAdminWebTenantSubscriptionRenewalOrder,
  createAdminWebTenantProduct,
  createAdminWebTenantWithdrawal,
  createAdminWebSupplyApplication,
  createBindingCodeAdminWebSession,
  createTelegramAdminWebSession,
  disableAdminWebTenantPaymentConfig,
  disableAdminWebExternalSourceConnection,
  downloadAdminWebTenantReportExportJob,
  getAdminWebBusinessPluginCapabilities,
  getAdminWebExternalSourceConnections,
  getAdminWebExternalSourceCatalogProducts,
  getAdminWebPlatformDashboard,
  getAdminWebPlatformWithdrawal,
  getAdminWebTenantApiKeys,
  getAdminWebTenantAuditLogs,
  getAdminWebTenantFinanceDashboard,
  getAdminWebTenantOrderDiagnostics,
  getAdminWebTenantOrderObservability,
  getAdminWebTenantReportExportJobs,
  getAdminWebSession,
  getAdminWebSupplyDashboard,
  getAdminWebTenantOrders,
  getAdminWebTenantOverview,
  getAdminWebTenantPaymentConfigs,
  getAdminWebTenantProducts,
  getAdminWebTenantRiskDashboard,
  getAdminWebTenantStoreSettings,
  getAdminWebTenantSubscriptionDashboard,
  getAdminWebWorkspaces,
  grantAdminWebPlatformTenantSubscriptionDays,
  importAdminWebProductInventory,
  rejectAdminWebPlatformWithdrawal,
  resetAdminWebPlatformBotWebhook,
  revokeAdminWebTenantApiKey,
  logoutAdminWebSession,
  reviewAdminWebSupplierApplication,
  selectAdminWebWorkspace,
  syncAdminWebExternalCatalog,
  setAdminWebPlatformTenantSubscriptionPeriodEnd,
  updateAdminWebPlatformBotStatus,
  updateAdminWebPlatformSubscriptionPlan,
  updateAdminWebPlatformSubscriptionPlanStatus,
  updateAdminWebPlatformSupplierOfferStatus,
  updateAdminWebPlatformTenantSuspensionStatus,
  updateAdminWebPlatformUserBanStatus,
  batchUpdateAdminWebProductStatus,
  updateAdminWebProductMetadata,
  updateAdminWebProductSales,
  updateAdminWebResellerProductMetadata,
  updateAdminWebResellerProductSales,
  updateAdminWebSupplierOfferApproval,
  updateAdminWebSupplierRule,
  uploadAdminWebProductDeliveryFile,
  updateAdminWebTenantPaymentConfig,
  updateAdminWebTenantStoreSettings,
  type AdminWebCreateSupplierOfferPayload,
  type AdminWebCreateTenantApiKeyPayload,
  type AdminWebCreateTenantReportExportJobPayload,
  type AdminWebCreateProductPayload,
  type AdminWebCreateResellerProductPayload,
  type AdminWebCreateTenantSubscriptionRenewalOrderPayload,
  type AdminWebCreateTenantWithdrawalPayload,
  type AdminWebPlatformDashboard,
  type AdminWebPlatformDashboardFilters,
  type AdminWebPlatformPaymentProvider,
  type AdminWebPlatformRiskAuditLog,
  type AdminWebPlatformRiskBannedUser,
  type AdminWebPlatformStats,
  type AdminWebPlatformSubscriptionPlanCreatePayload,
  type AdminWebPlatformTenantSubscriptionSetPeriodEndPayload,
  type AdminWebPlatformSubscriptionPlanUpdatePayload,
  type AdminWebPlatformSupplierOffer,
  type AdminWebPlatformTenantBot,
  type AdminWebPlatformWithdrawal,
  type AdminWebPaymentProviderConfigPayload,
  type AdminWebPaymentProviderName,
  type AdminWebProductBatchStatusPayload,
  type AdminWebProductInventoryImportPayload,
  type AdminWebProductMetadataPayload,
  type AdminWebProductSalesPayload,
  type AdminWebResellerProductMetadataPayload,
  type AdminWebResellerProductSalesPayload,
  type AdminWebSession,
  type AdminWebSupplyDashboardFilters,
  type AdminWebSupplyDashboard,
  type AdminWebSupplyMarketOffer,
  type AdminWebSupplierApplication,
  type AdminWebSupplierOffer,
  type AdminWebSupplierRule,
  type AdminWebSupplierRulePayload,
  type AdminWebTenantOrder,
  type AdminWebTenantOrderDiagnostics,
  type AdminWebTenantOrderFilters,
  type AdminWebTenantOrderObservability,
  type AdminWebTenantAuditLogsResponse,
  type AdminWebCreatedTenantApiKey,
  type AdminWebBusinessPluginCapability,
  type AdminWebBusinessPluginCapabilitiesResponse,
  type AdminWebCreateExternalSourceConnectionPayload,
  type AdminWebTenantApiKey,
  type AdminWebTenantApiKeysResponse,
  type AdminWebTenantFinanceDashboard,
  type AdminWebExternalSourceConnection,
  type AdminWebExternalSourceCatalogProductsResponse,
  type AdminWebExternalSourceConnectionsResponse,
  type AdminWebTenantOrdersResponse,
  type AdminWebTenantOverview,
  type AdminWebTenantPaymentProviderConfig,
  type AdminWebTenantPaymentProviderConfigsResponse,
  type AdminWebTenantProduct,
  type AdminWebTenantProductFilters,
  type AdminWebTenantProductsResponse,
  type AdminWebTenantReportExportJob,
  type AdminWebTenantReportExportJobsResponse,
  type AdminWebTenantReportStatusFilter,
  type AdminWebTenantReportType,
  type AdminWebTenantReportTypeFilter,
  type AdminWebTenantRiskAfterSale,
  type AdminWebTenantRiskDashboard,
  type AdminWebTenantRiskDispute,
  type AdminWebTenantRiskStatusFilter,
  type AdminWebTenantStoreSettings,
  type AdminWebTenantStoreSettingsPayload,
  type AdminWebTenantSubscriptionDashboard,
  type AdminWebTenantSubscriptionRenewalOrder,
  type AdminWebTenantWithdrawal,
  type AdminWebUser,
  type AdminWebWorkspace,
  type AdminWebResellerProduct,
  type AdminWebSupplierApplicationReviewPayload,
  type AdminWebSupplierOfferApprovalPayload,
} from "@/lib/admin-web-api"
import {
  prepareTelegramWebApp,
  readTelegramLaunchContext,
} from "@/lib/telegram-webapp"
import { cn } from "@/lib/utils"

type AdminView = "总览" | "Bot工作台" | "克隆Bot" | "商户结算" | "系统设置"

type NavItem = {
  label: string
  icon: LucideIcon
  value: AdminView
  active?: boolean
}

const defaultSupplyMarketFilters: AdminWebSupplyDashboardFilters = {
  market_delivery_type: "all",
  market_access: "all",
  market_stock: "all",
}

const platformTenantPageSize = 8

const defaultPlatformDashboardFilters: AdminWebPlatformDashboardFilters = {
  tenant_limit: platformTenantPageSize,
  tenant_offset: 0,
  tenant_status: "all",
  bot_status: "all",
  subscription_status: "all",
}

const tenantListPageSize = 8

const defaultTenantProductFilters: AdminWebTenantProductFilters = {
  limit: tenantListPageSize,
  offset: 0,
  status: "all",
  delivery_type: "all",
}

const defaultTenantOrderFilters: AdminWebTenantOrderFilters = {
  limit: tenantListPageSize,
  offset: 0,
  status: "all",
  source_type: "all",
  payment_mode: "all",
}

const defaultTenantReportJobFilters = {
  limit: 8,
  status: "all" as AdminWebTenantReportStatusFilter,
  report_type: "all" as AdminWebTenantReportTypeFilter,
}

const sidebarNav: NavItem[] = [
  { label: "总览", icon: LayoutDashboardIcon, value: "总览" },
  { label: "Bot 工作台", icon: BotIcon, value: "Bot工作台" },
  { label: "克隆 Bot", icon: BoxesIcon, value: "克隆Bot" },
  { label: "商户结算", icon: CircleDollarSignIcon, value: "商户结算" },
  { label: "系统设置", icon: SettingsIcon, value: "系统设置" },
]

const viewTitles: Record<AdminView, { title: string; description: string }> = {
  "总览": { title: "总览", description: "工作区摘要与关键指标。" },
  "Bot工作台": { title: "Bot 管理台", description: "主 Bot、克隆 Bot、供应商与代理商入口。" },
  "克隆Bot": { title: "克隆 Bot 管理", description: "店铺设置、支付、商品订单与供货。" },
  "商户结算": { title: "商户结算", description: "订阅、财务与提现。" },
  "系统设置": { title: "系统设置", description: "支付通道、套餐、API Key 与店铺配置。" },
}

const partnerCards = [
  {
    title: "供应商入口",
    description: "开放商品、审核申请、设置代理成本。",
    icon: StoreIcon,
    action: "进入供应商",
  },
  {
    title: "代理商入口",
    description: "选择商品、设置售价、绑定销售 Bot。",
    icon: UsersIcon,
    action: "进入代理商",
  },
]

type SummaryItem = {
  label: string
  value: string
  detail: string
  badge: string
}

type SupplyActionResult = {
  kind: "success" | "error"
  message: string
}

type PlatformActionRunner = (
  actionId: string,
  confirmText: string,
  action: () => Promise<string>,
) => Promise<void>

type SupplyMarketDeliveryType = NonNullable<AdminWebSupplyDashboardFilters["market_delivery_type"]>
type SupplyMarketAccess = NonNullable<AdminWebSupplyDashboardFilters["market_access"]>
type SupplyMarketStock = NonNullable<AdminWebSupplyDashboardFilters["market_stock"]>

type WorkspaceSelectProps = {
  workspaces: AdminWebWorkspace[]
  currentWorkspaceId?: string | null
  isLoading: boolean
  isSelecting: boolean
  onSelect: (workspaceId: string) => void
}

function WorkspaceSelect({
  workspaces,
  currentWorkspaceId,
  isLoading,
  isSelecting,
  onSelect,
}: WorkspaceSelectProps) {
  return (
    <Select
      value={currentWorkspaceId ?? undefined}
      disabled={isLoading || isSelecting || workspaces.length === 0}
      onValueChange={onSelect}
    >
      <SelectTrigger className="w-full md:w-72">
        <SelectValue
          placeholder={
            isLoading
              ? "加载工作区"
              : workspaces.length > 0
                ? "选择 Bot 工作区"
                : "无可用工作区"
          }
        />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          <SelectLabel>Bot 工作区</SelectLabel>
          {workspaces.map((workspace) => (
            <SelectItem key={workspace.workspace_id} value={workspace.workspace_id}>
              {workspace.title}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  )
}

function Sidebar({
  currentWorkspace,
  activeView,
  onViewChange,
}: {
  currentWorkspace?: AdminWebWorkspace
  activeView: AdminView
  onViewChange: (view: AdminView) => void
}) {
  return (
    <aside className="hidden min-h-screen w-64 shrink-0 border-r bg-card md:flex md:flex-col">
      <div className="flex h-16 items-center gap-3 px-5">
        <div className="flex size-9 items-center justify-center rounded-md bg-primary text-sm font-semibold text-primary-foreground">
          FB
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">Fakabot Admin</p>
          <p className="truncate text-xs text-muted-foreground">
            {currentWorkspace?.title ?? "未选择工作区"}
          </p>
        </div>
      </div>
      <Separator />
      <nav className="flex flex-1 flex-col gap-1 p-3">
        {sidebarNav.map((item) => {
          const Icon = item.icon

          return (
            <Button
              key={item.value}
              variant={activeView === item.value ? "secondary" : "ghost"}
              className="h-10 justify-start px-3"
              onClick={() => onViewChange(item.value)}
            >
              <Icon data-icon="inline-start" />
              <span className="truncate">{item.label}</span>
            </Button>
          )
        })}
      </nav>
      <div className="flex flex-col gap-3 p-4">
        <div className="rounded-lg border bg-background p-3">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-medium">租户模式</p>
            <Badge variant="secondary">
              {currentWorkspace ? workspaceKindLabel(currentWorkspace.kind) : "工作区"}
            </Badge>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            主 Bot 与克隆 Bot 分开管理。
          </p>
        </div>
      </div>
    </aside>
  )
}

function MobileNav({
  activeView,
  onViewChange,
}: {
  activeView: AdminView
  onViewChange: (view: AdminView) => void
}) {
  return (
    <div className="flex gap-2 overflow-x-auto md:hidden">
      {sidebarNav.map((item) => {
        const Icon = item.icon

        return (
          <Button
            key={item.value}
            variant={activeView === item.value ? "secondary" : "outline"}
            size="sm"
            className="shrink-0"
            onClick={() => onViewChange(item.value)}
          >
            <Icon data-icon="inline-start" />
            {item.label}
          </Button>
        )
      })}
    </div>
  )
}

function SummaryGrid({ items }: { items: SummaryItem[] }) {
  return (
    <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => (
        <Card key={item.label}>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between gap-3">
              <CardTitle>{item.label}</CardTitle>
              <Badge variant="outline">{item.badge}</Badge>
            </div>
            <CardDescription>{item.detail}</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">{item.value}</p>
          </CardContent>
        </Card>
      ))}
    </section>
  )
}

function BotListCard({
  workspaces,
  isLoading,
}: {
  workspaces: AdminWebWorkspace[]
  isLoading: boolean
}) {
  const rows = workspaces.map((workspace) => ({
    id: workspace.workspace_id,
    name: workspace.title,
    status: workspaceStatusLabel(workspace),
    owner: workspace.kind === "platform" ? "平台" : roleLabel(workspace.role),
    subtitle:
      workspace.kind === "tenant" && workspace.bot_username
        ? `@${workspace.bot_username}`
        : workspaceKindLabel(workspace.kind),
  }))

  return (
    <Card>
      <CardHeader>
        <CardTitle>Bot 列表</CardTitle>
        <CardDescription>主 Bot 与克隆 Bot 的管理入口。</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {isLoading ? (
          <div className="rounded-md border p-3">
            <p className="text-sm font-medium">正在加载工作区</p>
            <p className="mt-1 text-xs text-muted-foreground">稍后显示可管理 Bot。</p>
          </div>
        ) : null}
        {!isLoading && rows.length === 0 ? (
          <div className="rounded-md border p-3">
            <p className="text-sm font-medium">暂无可管理 Bot</p>
            <p className="mt-1 text-xs text-muted-foreground">请先从 Telegram 完成绑定。</p>
          </div>
        ) : null}
        {rows.map((row, index) => (
          <div key={row.id} className="flex flex-col gap-4">
            <div className="flex flex-col gap-3 rounded-md border p-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{row.name}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {row.owner} · {row.subtitle}
                </p>
              </div>
              <Badge variant="secondary">{row.status}</Badge>
            </div>
            {index < rows.length - 1 ? <Separator /> : null}
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function PrimaryBotPanel({
  platformWorkspace,
  user,
  workspaces,
  view,
}: {
  platformWorkspace?: AdminWebWorkspace
  user?: AdminWebUser
  workspaces: AdminWebWorkspace[]
  view?: AdminView
}) {
  const tenantCount = workspaces.filter((workspace) => workspace.kind === "tenant").length
  const [dashboard, setDashboard] = React.useState<AdminWebPlatformDashboard | null>(null)
  const [isLoading, setIsLoading] = React.useState(false)
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null)
  const [actionId, setActionId] = React.useState<string | null>(null)
  const [actionResult, setActionResult] = React.useState<SupplyActionResult | null>(null)
  const [platformFilters, setPlatformFilters] = React.useState<AdminWebPlatformDashboardFilters>(defaultPlatformDashboardFilters)
  const canUsePlatform = Boolean(platformWorkspace && user?.is_platform_admin)

  const loadPlatformDashboard = React.useCallback(async () => {
    if (!canUsePlatform) {
      setDashboard(null)
      setErrorMessage(null)
      return
    }

    setIsLoading(true)
    setErrorMessage(null)
    try {
      setDashboard(await getAdminWebPlatformDashboard(platformFilters))
    } catch (error) {
      setDashboard(null)
      setErrorMessage(errorToMessage(error))
    } finally {
      setIsLoading(false)
    }
  }, [canUsePlatform, platformFilters])

  React.useEffect(() => {
    void loadPlatformDashboard()
  }, [loadPlatformDashboard])

  async function runPlatformAction(
    nextActionId: string,
    confirmText: string,
    action: () => Promise<string>,
  ) {
    if (!window.confirm(confirmText)) {
      return
    }

    setActionId(nextActionId)
    setActionResult(null)
    try {
      const message = await action()
      setActionResult({ kind: "success", message })
      await loadPlatformDashboard()
    } catch (error) {
      setActionResult({ kind: "error", message: errorToMessage(error) })
    } finally {
      setActionId(null)
    }
  }

  if (view && view !== "Bot工作台") {
    if (!canUsePlatform) {
      return (
        <Card>
          <CardHeader>
            <CardTitle>平台管理</CardTitle>
            <CardDescription>当前账号没有平台管理员权限。</CardDescription>
          </CardHeader>
        </Card>
      )
    }
    return (
      <div className="flex flex-col gap-4">
        {isLoading ? <StatusBlock title="正在加载平台数据" detail="读取主 Bot 管理摘要。" /> : null}
        {errorMessage ? (
          <div className="flex flex-col gap-3 rounded-md border p-3">
            <p className="text-sm font-medium">平台数据加载失败</p>
            <p className="text-xs text-muted-foreground">{errorMessage}</p>
            <Button variant="outline" size="sm" className="w-fit" onClick={loadPlatformDashboard}>
              重新加载
            </Button>
          </div>
        ) : null}
        {actionResult ? <SupplyActionNotice result={actionResult} /> : null}
        {dashboard && view === "总览" ? (
          <>
            <BotListCard workspaces={workspaces} isLoading={false} />
            <PlatformStatsGrid dashboard={dashboard} />
            <PlatformTenantSubscriptionStatusPanel
              dashboard={dashboard}
              actionId={actionId}
              onRunAction={runPlatformAction}
            />
          </>
        ) : null}
        {dashboard && view === "克隆Bot" ? (
          <PlatformTenantBotsPanel
            tenants={dashboard.tenants}
            stats={dashboard.stats}
            filters={platformFilters}
            actionId={actionId}
            onRunAction={runPlatformAction}
            onFiltersChange={setPlatformFilters}
          />
        ) : null}
        {dashboard && view === "商户结算" ? (
          <PlatformWithdrawalsPanel
            withdrawals={dashboard.withdrawals}
            actionId={actionId}
            onRunAction={runPlatformAction}
            onRefresh={loadPlatformDashboard}
          />
        ) : null}
        {dashboard && view === "系统设置" ? (
          <div className="grid gap-4 xl:grid-cols-2">
            <PlatformPaymentProvidersPanel providers={dashboard.payment_providers} />
            <PlatformSubscriptionPlansPanel
              plans={dashboard.subscription_plans}
              actionId={actionId}
              onRunAction={runPlatformAction}
            />
            <PlatformSupplyControlPanel
              offers={dashboard.supplier_offers}
              actionId={actionId}
              onRunAction={runPlatformAction}
            />
          </div>
        ) : null}
      </div>
    )
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.65fr)]">
      <div className="flex flex-col gap-4">
        <BotListCard workspaces={workspaces} isLoading={false} />
        <PlatformDashboardPanel
          dashboard={dashboard}
          isLoading={isLoading}
          errorMessage={errorMessage}
          actionId={actionId}
          actionResult={actionResult}
          canUsePlatform={canUsePlatform}
          platformFilters={platformFilters}
          onRefresh={loadPlatformDashboard}
          onRunAction={runPlatformAction}
          onPlatformFiltersChange={setPlatformFilters}
        />
      </div>
      <Card>
        <CardHeader>
          <CardTitle>主 Bot 配置</CardTitle>
          <CardDescription>
            {platformWorkspace ? platformWorkspace.title : "当前账号没有主 Bot 工作区。"}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex items-center justify-between gap-4 rounded-md border p-3">
            <span className="text-sm text-muted-foreground">平台权限</span>
            <Badge>{user?.is_platform_admin ? "已授权" : "未授权"}</Badge>
          </div>
          <div className="flex items-center justify-between gap-4 rounded-md border p-3">
            <span className="text-sm text-muted-foreground">可管理克隆 Bot</span>
            <Badge variant="secondary">{tenantCount}</Badge>
          </div>
          <div className="flex items-center justify-between gap-4 rounded-md border p-3">
            <span className="text-sm text-muted-foreground">结算</span>
            <Badge variant="outline">托管</Badge>
          </div>
        </CardContent>
        <CardFooter>
          <Button variant="outline" className="w-full" disabled={!platformWorkspace}>
            <ShieldCheckIcon data-icon="inline-start" />
            安全配置
          </Button>
        </CardFooter>
      </Card>
    </div>
  )
}

function PlatformDashboardPanel({
  dashboard,
  isLoading,
  errorMessage,
  actionId,
  actionResult,
  canUsePlatform,
  platformFilters,
  onRefresh,
  onRunAction,
  onPlatformFiltersChange,
}: {
  dashboard: AdminWebPlatformDashboard | null
  isLoading: boolean
  errorMessage: string | null
  actionId: string | null
  actionResult: SupplyActionResult | null
  canUsePlatform: boolean
  platformFilters: AdminWebPlatformDashboardFilters
  onRefresh: () => void
  onRunAction: (
    actionId: string,
    confirmText: string,
    action: () => Promise<string>,
  ) => Promise<void>
  onPlatformFiltersChange: React.Dispatch<React.SetStateAction<AdminWebPlatformDashboardFilters>>
}) {
  if (!canUsePlatform) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>平台管理</CardTitle>
          <CardDescription>当前账号没有平台管理员权限。</CardDescription>
        </CardHeader>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0">
            <CardTitle>平台工作台</CardTitle>
            <CardDescription>租户、订阅、提现、风控和供货商品状态。</CardDescription>
          </div>
          <Button variant="outline" size="sm" disabled={isLoading || actionId !== null} onClick={onRefresh}>
            <RefreshCwIcon data-icon="inline-start" />
            刷新
          </Button>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {isLoading ? <StatusBlock title="正在加载平台数据" detail="读取主 Bot 管理摘要。" /> : null}
        {errorMessage ? (
          <div className="flex flex-col gap-3 rounded-md border p-3">
            <p className="text-sm font-medium">平台数据加载失败</p>
            <p className="text-xs text-muted-foreground">{errorMessage}</p>
            <Button variant="outline" size="sm" className="w-fit" onClick={onRefresh}>
              重新加载
            </Button>
          </div>
        ) : null}
        {actionResult ? <SupplyActionNotice result={actionResult} /> : null}
        {dashboard ? (
          <>
            <PlatformStatsGrid dashboard={dashboard} />
            <PlatformTenantSubscriptionStatusPanel
              dashboard={dashboard}
              actionId={actionId}
              onRunAction={onRunAction}
            />
            <PlatformTenantBotsPanel
              tenants={dashboard.tenants}
              stats={dashboard.stats}
              filters={platformFilters}
              actionId={actionId}
              onRunAction={onRunAction}
              onFiltersChange={onPlatformFiltersChange}
            />
            <div className="grid gap-4 xl:grid-cols-2">
              <PlatformPaymentProvidersPanel providers={dashboard.payment_providers} />
              <PlatformSubscriptionPlansPanel
                plans={dashboard.subscription_plans}
                actionId={actionId}
                onRunAction={onRunAction}
              />
              <PlatformWithdrawalsPanel
                withdrawals={dashboard.withdrawals}
                actionId={actionId}
                onRunAction={onRunAction}
                onRefresh={onRefresh}
              />
              <PlatformRiskPanel
                bannedUsers={dashboard.banned_users}
                auditLogs={dashboard.risk_audit_logs}
                actionId={actionId}
                onRunAction={onRunAction}
              />
              <PlatformSupplyControlPanel
                offers={dashboard.supplier_offers}
                actionId={actionId}
                onRunAction={onRunAction}
              />
            </div>
          </>
        ) : null}
      </CardContent>
    </Card>
  )
}

function PlatformStatsGrid({ dashboard }: { dashboard: AdminWebPlatformDashboard }) {
  const stats = [
    { label: "租户", value: dashboard.stats.tenant_count, detail: "全部店铺" },
    { label: "活跃 Bot", value: dashboard.stats.active_bot_count, detail: "运行中" },
    { label: "待审提现", value: dashboard.stats.pending_withdrawal_count, detail: "人工审核" },
    { label: "风控", value: dashboard.stats.banned_user_count, detail: "封禁用户" },
  ]

  return (
    <div className="grid gap-3 md:grid-cols-4">
      {stats.map((item) => (
        <div key={item.label} className="rounded-md border p-3">
          <p className="text-xs text-muted-foreground">{item.detail}</p>
          <div className="mt-2 flex items-center justify-between gap-3">
            <p className="text-sm font-medium">{item.label}</p>
            <Badge variant="secondary">{item.value}</Badge>
          </div>
        </div>
      ))}
    </div>
  )
}

function PlatformTenantSubscriptionStatusPanel({
  dashboard,
  actionId,
  onRunAction,
}: {
  dashboard: AdminWebPlatformDashboard
  actionId: string | null
  onRunAction: PlatformActionRunner
}) {
  const statusRows = [
    { label: "试用", value: dashboard.stats.trial_subscription_count, status: "trial" },
    { label: "活跃", value: dashboard.stats.active_subscription_count, status: "active" },
    { label: "宽限", value: dashboard.stats.grace_subscription_count, status: "grace" },
    { label: "暂停", value: dashboard.stats.suspended_subscription_count, status: "suspended" },
    {
      label: "保留期过期",
      value: dashboard.stats.retention_expired_subscription_count,
      status: "retention_expired",
    },
  ]
  const observedTenants = dashboard.subscription_attention.slice(0, 6)

  return (
    <section className="flex flex-col gap-3 rounded-md border p-3">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <p className="text-sm font-medium">租户订阅状态</p>
          <p className="mt-1 text-xs text-muted-foreground">平台级只读观测，不创建续费订单或触发支付。</p>
        </div>
        <Badge variant="outline">{dashboard.stats.tenant_count}</Badge>
      </div>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
        {statusRows.map((row) => (
          <div key={row.status} className="rounded-md border p-3">
            <p className="text-xs text-muted-foreground">{row.label}</p>
            <div className="mt-2 flex items-center justify-between gap-3">
              <Badge variant={subscriptionStatusBadgeVariant(row.status)}>
                {subscriptionStatusLabel(row.status)}
              </Badge>
              <span className="text-sm font-medium">{row.value}</span>
            </div>
          </div>
        ))}
      </div>
      {observedTenants.length > 0 ? (
        <div className="grid gap-2 lg:grid-cols-2">
          {observedTenants.map((tenant) => {
            const status = tenant.subscription_status
            return (
              <div key={tenant.tenant_public_id} className="rounded-md border p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{tenant.store_name}</p>
                    <p className="mt-1 truncate text-xs text-muted-foreground">
                      {tenant.plan_name ?? tenant.plan_code ?? "未绑定套餐"} · owner {tenant.owner_telegram_user_id}
                    </p>
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-2">
                    <Badge variant={subscriptionAttentionBadgeVariant(tenant.attention_reason)}>
                      {subscriptionAttentionReasonLabel(tenant.attention_reason)}
                    </Badge>
                    <Badge variant={subscriptionStatusBadgeVariant(status)}>{subscriptionStatusLabel(status)}</Badge>
                  </div>
                </div>
                <div className="mt-3 grid gap-2">
                  <MetricLine label="周期结束" value={formatDateTime(tenant.current_period_ends_at)} />
                  <MetricLine label="宽限结束" value={formatDateTime(tenant.grace_ends_at)} />
                  <MetricLine label="保留结束" value={formatDateTime(tenant.data_retention_until)} />
                  <MetricLine label="订阅到期" value={formatDateTime(tenant.subscription_ends_at)} />
                </div>
                <PlatformTenantSubscriptionAdjustmentForm
                  tenant={tenant}
                  actionId={actionId}
                  onRunAction={onRunAction}
                />
              </div>
            )
          })}
        </div>
      ) : (
        <StatusBlock title="暂无订阅关注项" detail="当前列表中没有宽限、暂停、保留期过期或临近到期租户。" />
      )}
    </section>
  )
}

function PlatformTenantSubscriptionAdjustmentForm({
  tenant,
  actionId,
  onRunAction,
}: {
  tenant: AdminWebPlatformDashboard["subscription_attention"][number]
  actionId: string | null
  onRunAction: PlatformActionRunner
}) {
  const [periodEndsAt, setPeriodEndsAt] = React.useState("")
  const grantActionId = `subscription:grant-days:${tenant.tenant_public_id}`
  const setActionId = `subscription:set-period:${tenant.tenant_public_id}`
  const isBusy = actionId !== null
  const isGranting = actionId === grantActionId
  const isSetting = actionId === setActionId

  const handleGrantDays = () => {
    void onRunAction(
      grantActionId,
      `确认为 ${tenant.store_name} 赠送 30 天订阅？`,
      async () => {
        const result = await grantAdminWebPlatformTenantSubscriptionDays(tenant.tenant_public_id, {
          days: 30,
          reason: "Admin Web 赠送 30 天",
        })
        return `${tenant.store_name} 订阅已延长至 ${formatDateTime(result.new_period_ends_at)}。`
      },
    )
  }

  const handleSetPeriodEnd = () => {
    const payload = buildSubscriptionPeriodEndPayload(periodEndsAt)
    if (!payload) {
      return
    }
    void onRunAction(
      setActionId,
      `确认将 ${tenant.store_name} 订阅到期时间设置为 ${formatDateTime(payload.period_ends_at)}？`,
      async () => {
        const result = await setAdminWebPlatformTenantSubscriptionPeriodEnd(tenant.tenant_public_id, {
          ...payload,
          reason: "Admin Web 设置到期时间",
        })
        return `${tenant.store_name} 订阅到期时间已设置为 ${formatDateTime(result.new_period_ends_at)}。`
      },
    )
  }

  return (
    <div className="mt-3 flex flex-col gap-2 rounded-md border p-2">
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" disabled={isBusy} onClick={handleGrantDays}>
          {isGranting ? "赠送中" : "赠送 30 天"}
        </Button>
        <div className="flex min-w-0 flex-1 flex-wrap gap-2">
          <Input
            type="datetime-local"
            value={periodEndsAt}
            aria-label={`${tenant.store_name} 订阅到期时间`}
            disabled={isBusy}
            onChange={(event) => setPeriodEndsAt(event.target.value)}
          />
          <Button size="sm" variant="outline" disabled={isBusy || !periodEndsAt} onClick={handleSetPeriodEnd}>
            {isSetting ? "设置中" : "设置到期"}
          </Button>
        </div>
      </div>
    </div>
  )
}

function PlatformTenantBotsPanel({
  tenants,
  stats,
  filters,
  actionId,
  onRunAction,
  onFiltersChange,
}: {
  tenants: AdminWebPlatformTenantBot[]
  stats: AdminWebPlatformStats
  filters: AdminWebPlatformDashboardFilters
  actionId: string | null
  onRunAction: PlatformActionRunner
  onFiltersChange: React.Dispatch<React.SetStateAction<AdminWebPlatformDashboardFilters>>
}) {
  const offset = filters.tenant_offset ?? 0
  const limit = filters.tenant_limit ?? platformTenantPageSize
  const canGoPrevious = offset > 0
  const canGoNext = tenants.length >= limit && offset + limit < stats.tenant_count
  const updateFilters = (patch: Partial<AdminWebPlatformDashboardFilters>) => {
    onFiltersChange((current) => ({
      ...current,
      ...patch,
      tenant_limit: platformTenantPageSize,
      tenant_offset: patch.tenant_offset ?? 0,
    }))
  }

  return (
    <section className="flex flex-col gap-3 rounded-md border p-3">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <p className="text-sm font-medium">租户与 Bot</p>
          <p className="mt-1 text-xs text-muted-foreground">状态、到期、绑定和 Webhook 观测。</p>
        </div>
        <Badge variant="outline">{offset + 1}-{offset + tenants.length} / {stats.tenant_count}</Badge>
      </div>
      <div className="grid gap-2 lg:grid-cols-[minmax(0,1fr)_10rem_10rem_10rem_auto]">
        <Input
          value={filters.tenant_query ?? ""}
          placeholder="搜索店铺/Bot/owner"
          aria-label="搜索租户或 Bot"
          disabled={actionId !== null}
          onChange={(event) => updateFilters({ tenant_query: event.target.value || undefined })}
        />
        <Select
          value={filters.tenant_status ?? "all"}
          disabled={actionId !== null}
          onValueChange={(value) => updateFilters({ tenant_status: value as AdminWebPlatformDashboardFilters["tenant_status"] })}
        >
          <SelectTrigger aria-label="租户状态">
            <SelectValue placeholder="租户状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value="all">全部租户</SelectItem>
              <SelectItem value="trial">试用</SelectItem>
              <SelectItem value="active">活跃</SelectItem>
              <SelectItem value="grace">宽限</SelectItem>
              <SelectItem value="suspended">暂停</SelectItem>
              <SelectItem value="retention_expired">保留期过期</SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
        <Select
          value={filters.bot_status ?? "all"}
          disabled={actionId !== null}
          onValueChange={(value) => updateFilters({ bot_status: value as AdminWebPlatformDashboardFilters["bot_status"] })}
        >
          <SelectTrigger aria-label="Bot 状态">
            <SelectValue placeholder="Bot 状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value="all">全部 Bot</SelectItem>
              <SelectItem value="active">运行中</SelectItem>
              <SelectItem value="disabled">已停用</SelectItem>
              <SelectItem value="missing">未绑定</SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
        <Select
          value={filters.subscription_status ?? "all"}
          disabled={actionId !== null}
          onValueChange={(value) => updateFilters({ subscription_status: value as AdminWebPlatformDashboardFilters["subscription_status"] })}
        >
          <SelectTrigger aria-label="订阅状态">
            <SelectValue placeholder="订阅状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value="all">全部订阅</SelectItem>
              <SelectItem value="trial">试用</SelectItem>
              <SelectItem value="active">活跃</SelectItem>
              <SelectItem value="grace">宽限</SelectItem>
              <SelectItem value="suspended">暂停</SelectItem>
              <SelectItem value="retention_expired">保留期过期</SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
        <Button
          size="sm"
          variant="outline"
          disabled={actionId !== null}
          onClick={() => onFiltersChange(defaultPlatformDashboardFilters)}
        >
          重置
        </Button>
      </div>
      {tenants.length === 0 ? (
        <StatusBlock title="暂无租户" detail="当前平台没有可展示的克隆 Bot。" />
      ) : null}
      <div className="flex flex-col gap-2">
        {tenants.map((tenant) => {
          const botAction = tenant.bot_status === "active" ? "disabled" : "active"
          const tenantAction = tenant.tenant_status === "suspended" ? "active" : "suspended"
          const isBotBusy = actionId === `bot:${botAction}:${tenant.tenant_public_id}`
          const isTenantBusy = actionId === `tenant:${tenantAction}:${tenant.tenant_public_id}`

          return (
            <div key={tenant.tenant_public_id} className="rounded-md border p-3">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="truncate text-sm font-medium">{tenant.store_name}</p>
                    <Badge variant={tenant.tenant_status === "suspended" ? "destructive" : "secondary"}>
                      {tenantStatusLabel(tenant.tenant_status)}
                    </Badge>
                    <Badge variant="outline">{platformWebhookStatusLabel(tenant.webhook_status)}</Badge>
                  </div>
                  <p className="mt-1 truncate text-xs text-muted-foreground">
                    {tenant.bot_username ? `@${tenant.bot_username}` : "未绑定 Bot"} · owner {tenant.owner_telegram_user_id}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    到期 {formatDateTime(tenant.current_period_ends_at ?? tenant.subscription_ends_at)}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!tenant.bot_username || !tenant.webhook_reset_available || actionId !== null}
                    title="调用 Telegram setWebhook 并轮换 Webhook secret"
                    onClick={() =>
                      onRunAction(
                        `bot:webhook-reset:${tenant.tenant_public_id}`,
                        `确认重置 ${tenant.store_name} 的 Telegram Webhook？该操作会轮换 Webhook secret 并丢弃待处理更新。`,
                        async () => {
                          const result = await resetAdminWebPlatformBotWebhook(tenant.tenant_public_id, {
                            reason: "Admin Web 平台维护",
                          })
                          return `${result.bot_username} Webhook 已重置。`
                        },
                      )
                    }
                  >
                    <WebhookIcon data-icon="inline-start" />
                    {actionId === `bot:webhook-reset:${tenant.tenant_public_id}` ? "轮换中" : "重置"}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!tenant.bot_username || actionId !== null}
                    onClick={() =>
                      onRunAction(
                        `bot:${botAction}:${tenant.tenant_public_id}`,
                        `确认${botAction === "disabled" ? "停用" : "恢复"} ${tenant.store_name} 的克隆 Bot？`,
                        async () => {
                          const result = await updateAdminWebPlatformBotStatus(tenant.tenant_public_id, {
                            status: botAction,
                            reason: "Admin Web 平台维护",
                          })
                          return `${result.bot_username} 已${botAction === "disabled" ? "停用" : "恢复"}。`
                        },
                      )
                    }
                  >
                    {botAction === "disabled" ? <PauseCircleIcon data-icon="inline-start" /> : <CheckCircle2Icon data-icon="inline-start" />}
                    {isBotBusy ? "处理中" : botAction === "disabled" ? "停用" : "恢复"}
                  </Button>
                  <Button
                    size="sm"
                    variant={tenantAction === "suspended" ? "destructive" : "outline"}
                    disabled={actionId !== null}
                    onClick={() =>
                      onRunAction(
                        `tenant:${tenantAction}:${tenant.tenant_public_id}`,
                        `确认${tenantAction === "suspended" ? "冻结" : "恢复"}租户 ${tenant.store_name}？`,
                        async () => {
                          const result = await updateAdminWebPlatformTenantSuspensionStatus(tenant.tenant_public_id, {
                            status: tenantAction,
                            reason: "Admin Web 平台风控",
                          })
                          return `${tenant.store_name} 已${result.status === "suspended" ? "冻结" : "恢复"}。`
                        },
                      )
                    }
                  >
                    <AlertTriangleIcon data-icon="inline-start" />
                    {isTenantBusy ? "处理中" : tenantAction === "suspended" ? "冻结" : "恢复租户"}
                  </Button>
                </div>
              </div>
            </div>
          )
        })}
      </div>
      <div className="flex items-center justify-between gap-3">
        <Button
          size="sm"
          variant="outline"
          disabled={!canGoPrevious || actionId !== null}
          onClick={() => onFiltersChange((current) => ({ ...current, tenant_offset: Math.max(0, offset - limit) }))}
        >
          <ChevronLeftIcon data-icon="inline-start" />
          上一页
        </Button>
        <span className="text-xs text-muted-foreground">第 {Math.floor(offset / limit) + 1} 页</span>
        <Button
          size="sm"
          variant="outline"
          disabled={!canGoNext || actionId !== null}
          onClick={() => onFiltersChange((current) => ({ ...current, tenant_offset: offset + limit }))}
        >
          下一页
          <ChevronRightIcon data-icon="inline-end" />
        </Button>
      </div>
    </section>
  )
}

function PlatformPaymentProvidersPanel({
  providers,
}: {
  providers: AdminWebPlatformPaymentProvider[]
}) {
  const primaryProviders = providers.filter((provider) =>
    ["epusdt_gmpay", "epay_compatible"].includes(provider.provider_name),
  )
  const deferredProviders = providers.filter((provider) =>
    !["epusdt_gmpay", "epay_compatible"].includes(provider.provider_name),
  )
  const visibleProviders = [...primaryProviders, ...deferredProviders]

  return (
    <section className="flex flex-col gap-3 rounded-md border p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium">支付通道观测</p>
          <p className="mt-1 text-xs text-muted-foreground">能力摘要和租户配置缺口，不读取密钥或调用网关。</p>
        </div>
        <Badge variant="outline">{providers.length}</Badge>
      </div>
      {visibleProviders.length === 0 ? (
        <StatusBlock title="暂无支付通道" detail="当前环境没有注册可展示的支付 provider。" />
      ) : null}
      <div className="flex flex-col gap-2">
        {visibleProviders.map((provider) => (
          <PlatformPaymentProviderRow key={provider.provider_name} provider={provider} />
        ))}
      </div>
    </section>
  )
}

function PlatformPaymentProviderRow({
  provider,
}: {
  provider: AdminWebPlatformPaymentProvider
}) {
  const capabilityLabels = [
    provider.create_payment_available ? "创建支付" : null,
    provider.callback_available ? "回调" : null,
    provider.query_order_available ? "查单" : null,
    provider.reconcile_available ? "对账" : null,
  ].filter((label): label is string => Boolean(label))
  const supportedText = [
    provider.supported_assets.length > 0 ? provider.supported_assets.join("/") : null,
    provider.supported_networks.length > 0 ? provider.supported_networks.join("/") : null,
  ]
    .filter(Boolean)
    .join(" · ")

  return (
    <div className="flex flex-col gap-3 rounded-md border p-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate text-sm font-medium">{provider.display_name}</p>
            <Badge variant={provider.provider_name === "epusdt_gmpay" || provider.provider_name === "epay_compatible" ? "secondary" : "outline"}>
              {provider.provider_name === "epusdt_gmpay" || provider.provider_name === "epay_compatible" ? "近期主线" : "后置能力"}
            </Badge>
          </div>
          <p className="mt-1 truncate text-xs text-muted-foreground">
            {provider.provider_name} · {provider.contract_name}
          </p>
        </div>
        <Badge variant={provider.production_ready && provider.staging_verified ? "secondary" : "outline"}>
          {provider.production_ready && provider.staging_verified ? "生产可用" : provider.offline_only ? "离线能力" : "待联调"}
        </Badge>
      </div>
      <div className="flex flex-wrap gap-2">
        {capabilityLabels.map((label) => (
          <Badge key={label} variant="outline">
            {label}
          </Badge>
        ))}
        {supportedText ? <Badge variant="outline">{supportedText}</Badge> : null}
      </div>
      <div className="grid gap-2">
        <MetricLine label="已配置租户" value={String(provider.configured_tenant_count)} />
        <MetricLine label="已启用租户" value={String(provider.enabled_tenant_count)} />
        <MetricLine label="配置缺口" value={String(provider.missing_config_tenant_count)} />
        <MetricLine label="平台配置" value={provider.platform_enabled ? "已启用" : provider.platform_configured ? "已配置" : "-"} />
      </div>
    </div>
  )
}

type PlatformPlanFieldKey = "code" | "name" | "monthlyPrice" | "trialDays" | "graceDays"
type PlatformPlanFieldErrors = Partial<Record<PlatformPlanFieldKey, string>>
type PlatformPlanDraft = {
  code?: string
  name: string
  monthlyPrice: string
  trialDays: string
  graceDays: string
}

function PlatformSubscriptionPlansPanel({
  plans,
  actionId,
  onRunAction,
}: {
  plans: AdminWebPlatformDashboard["subscription_plans"]
  actionId: string | null
  onRunAction: PlatformActionRunner
}) {
  const enabledPlanCount = plans.filter((plan) => plan.enabled).length

  return (
    <section className="flex flex-col gap-3 rounded-md border p-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-sm font-medium">订阅计划</p>
          <p className="mt-1 text-xs text-muted-foreground">创建和编辑只更新套餐配置，不创建账单或真实支付订单。</p>
        </div>
        <Badge variant="outline">{enabledPlanCount} / {plans.length} 启用</Badge>
      </div>
      <PlatformPlanCreateForm actionId={actionId} onRunAction={onRunAction} />
      {plans.length === 0 ? <StatusBlock title="暂无订阅计划" detail="可创建第一个平台套餐。" /> : null}
      {plans.slice(0, 4).map((plan) => (
        <div key={plan.code} className="rounded-md border p-3">
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="truncate text-sm font-medium">{plan.name}</p>
                  <Badge variant={plan.enabled ? "secondary" : "outline"}>{plan.enabled ? "已启用" : "已停用"}</Badge>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {plan.code} · {plan.monthly_price} {plan.currency} · 试用 {plan.trial_days} 天 · 宽限 {plan.grace_days} 天
                </p>
              </div>
              <Button
                size="sm"
                variant="outline"
                disabled={actionId !== null}
                onClick={() =>
                  onRunAction(
                    `plan:status:${plan.code}`,
                    `确认${plan.enabled ? "停用" : "启用"}订阅计划 ${plan.name}？`,
                    async () => {
                      const nextPlan = await updateAdminWebPlatformSubscriptionPlanStatus(plan.code, {
                        enabled: !plan.enabled,
                        reason: "Admin Web 套餐管理",
                      })
                      return `${nextPlan.name} 已${nextPlan.enabled ? "启用" : "停用"}。`
                    },
                  )
                }
              >
                {actionId === `plan:status:${plan.code}` ? "处理中" : plan.enabled ? "停用" : "启用"}
              </Button>
            </div>
            <div className="grid gap-2 rounded-md bg-muted/30 p-3 sm:grid-cols-2">
              <MetricLine label="启用状态" value={plan.enabled ? "已启用" : "已停用"} />
              <MetricLine label="月费" value={`${plan.monthly_price} ${plan.currency}`} />
              <MetricLine label="试用天数" value={`${plan.trial_days} 天`} />
              <MetricLine label="宽限天数" value={`${plan.grace_days} 天`} />
              <MetricLine label="创建时间" value={formatDateTime(plan.created_at)} />
              <MetricLine label="更新时间" value={formatDateTime(plan.updated_at)} />
            </div>
            <PlatformPlanEditForm plan={plan} actionId={actionId} onRunAction={onRunAction} />
          </div>
        </div>
      ))}
    </section>
  )
}

function PlatformPlanEditForm({
  plan,
  actionId,
  onRunAction,
}: {
  plan: AdminWebPlatformDashboard["subscription_plans"][number]
  actionId: string | null
  onRunAction: PlatformActionRunner
}) {
  const [name, setName] = React.useState(plan.name)
  const [monthlyPrice, setMonthlyPrice] = React.useState(plan.monthly_price)
  const [trialDays, setTrialDays] = React.useState(String(plan.trial_days))
  const [graceDays, setGraceDays] = React.useState(String(plan.grace_days))
  const isBusy = actionId !== null
  const draft: PlatformPlanDraft = { name, monthlyPrice, trialDays, graceDays }
  const fieldErrors = validatePlatformPlanDraft(draft, { requireCode: false })
  const formErrors = platformPlanFieldErrorList(fieldErrors)
  const hasDraftChanges = hasPlatformPlanDraftChanges(plan, draft)
  const canSubmit = !isBusy && hasDraftChanges && formErrors.length === 0

  React.useEffect(() => {
    setName(plan.name)
    setMonthlyPrice(plan.monthly_price)
    setTrialDays(String(plan.trial_days))
    setGraceDays(String(plan.grace_days))
  }, [plan.code, plan.name, plan.monthly_price, plan.trial_days, plan.grace_days])

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canSubmit) {
      return
    }
    const payload: AdminWebPlatformSubscriptionPlanUpdatePayload = {
      name: name.trim(),
      monthly_price: monthlyPrice.trim(),
      currency: plan.currency,
      trial_days: Number(trialDays.trim()),
      grace_days: Number(graceDays.trim()),
      reason: "Admin Web 编辑套餐",
    }
    void onRunAction(`plan:update:${plan.code}`, `确认更新订阅计划 ${plan.name}？`, async () => {
      const nextPlan = await updateAdminWebPlatformSubscriptionPlan(plan.code, payload)
      return `${nextPlan.name} 已更新。`
    })
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={hasDraftChanges ? "secondary" : "outline"}>
          {hasDraftChanges ? "有未保存变更" : "无未保存变更"}
        </Badge>
        <span className="text-xs text-muted-foreground">代码只读，编辑仅修改名称、月费和周期参数。</span>
      </div>
      {hasDraftChanges && formErrors.length > 0 ? (
        <p className="text-xs text-destructive">{formErrors.join("；")}</p>
      ) : null}
      <form className="grid gap-2 md:grid-cols-[minmax(0,1fr)_7rem_6rem_6rem_auto]" onSubmit={handleSubmit}>
        <Input value={name} placeholder="计划名称" aria-label={`${plan.code} 计划名称`} aria-invalid={hasDraftChanges && Boolean(fieldErrors.name)} disabled={isBusy} onChange={(event) => setName(event.target.value)} />
        <Input value={monthlyPrice} inputMode="decimal" placeholder="月费" aria-label={`${plan.code} 月费`} aria-invalid={hasDraftChanges && Boolean(fieldErrors.monthlyPrice)} disabled={isBusy} onChange={(event) => setMonthlyPrice(event.target.value)} />
        <Input value={trialDays} inputMode="numeric" placeholder="试用" aria-label={`${plan.code} 试用天数`} aria-invalid={hasDraftChanges && Boolean(fieldErrors.trialDays)} disabled={isBusy} onChange={(event) => setTrialDays(event.target.value)} />
        <Input value={graceDays} inputMode="numeric" placeholder="宽限" aria-label={`${plan.code} 宽限天数`} aria-invalid={hasDraftChanges && Boolean(fieldErrors.graceDays)} disabled={isBusy} onChange={(event) => setGraceDays(event.target.value)} />
        <Button type="submit" size="sm" variant="outline" disabled={!canSubmit}>
          {actionId === `plan:update:${plan.code}` ? "保存中" : "保存"}
        </Button>
      </form>
    </div>
  )
}

function PlatformPlanCreateForm({
  actionId,
  onRunAction,
}: {
  actionId: string | null
  onRunAction: PlatformActionRunner
}) {
  const [code, setCode] = React.useState("")
  const [name, setName] = React.useState("")
  const [monthlyPrice, setMonthlyPrice] = React.useState("")
  const [trialDays, setTrialDays] = React.useState("30")
  const [graceDays, setGraceDays] = React.useState("0")
  const isBusy = actionId !== null
  const draft: PlatformPlanDraft = { code, name, monthlyPrice, trialDays, graceDays }
  const fieldErrors = validatePlatformPlanDraft(draft, { requireCode: true })
  const formErrors = platformPlanFieldErrorList(fieldErrors)
  const hasDraft = Boolean(code.trim() || name.trim() || monthlyPrice.trim() || trialDays.trim() !== "30" || graceDays.trim() !== "0")
  const canSubmit = !isBusy && formErrors.length === 0

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canSubmit) {
      return
    }
    const payload: AdminWebPlatformSubscriptionPlanCreatePayload = {
      code: code.trim(),
      name: name.trim(),
      monthly_price: monthlyPrice.trim(),
      currency: "USDT",
      trial_days: Number(trialDays.trim()),
      grace_days: Number(graceDays.trim()),
      enabled: true,
      reason: "Admin Web 创建套餐",
    }
    void onRunAction("plan:create", `确认创建订阅计划 ${payload.name}？`, async () => {
      const plan = await createAdminWebPlatformSubscriptionPlan(payload)
      setCode("")
      setName("")
      setMonthlyPrice("")
      setTrialDays("30")
      setGraceDays("0")
      return `${plan.name} 已创建。`
    })
  }

  return (
    <div className="flex flex-col gap-2 rounded-md border p-3">
      <div className="flex flex-col gap-1">
        <p className="text-sm font-medium">创建订阅计划</p>
        <p className="text-xs text-muted-foreground">默认币种 USDT，创建后仍可单独停用。</p>
      </div>
      {hasDraft && formErrors.length > 0 ? (
        <p className="text-xs text-destructive">{formErrors.join("；")}</p>
      ) : (
        <p className="text-xs text-muted-foreground">代码 1-64 位，名称 1-128 位，月费可为 0。</p>
      )}
      <form className="grid gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_7rem_6rem_6rem_auto]" onSubmit={handleSubmit}>
        <Input value={code} placeholder="计划代码" aria-label="计划代码" aria-invalid={hasDraft && Boolean(fieldErrors.code)} disabled={isBusy} onChange={(event) => setCode(event.target.value)} />
        <Input value={name} placeholder="计划名称" aria-label="计划名称" aria-invalid={hasDraft && Boolean(fieldErrors.name)} disabled={isBusy} onChange={(event) => setName(event.target.value)} />
        <Input value={monthlyPrice} inputMode="decimal" placeholder="月费" aria-label="月费" aria-invalid={hasDraft && Boolean(fieldErrors.monthlyPrice)} disabled={isBusy} onChange={(event) => setMonthlyPrice(event.target.value)} />
        <Input value={trialDays} inputMode="numeric" placeholder="试用" aria-label="试用天数" aria-invalid={hasDraft && Boolean(fieldErrors.trialDays)} disabled={isBusy} onChange={(event) => setTrialDays(event.target.value)} />
        <Input value={graceDays} inputMode="numeric" placeholder="宽限" aria-label="宽限天数" aria-invalid={hasDraft && Boolean(fieldErrors.graceDays)} disabled={isBusy} onChange={(event) => setGraceDays(event.target.value)} />
        <Button type="submit" size="sm" disabled={!canSubmit}>
          {actionId === "plan:create" ? "创建中" : "创建"}
        </Button>
      </form>
    </div>
  )
}

type PlatformWithdrawalReviewFieldKey = "rejectNote" | "completeNote" | "payoutReference" | "payoutProofUrl"
type PlatformWithdrawalReviewErrors = Partial<Record<PlatformWithdrawalReviewFieldKey, string>>
type PlatformWithdrawalReviewDraft = {
  rejectNote: string
  completeNote: string
  payoutReference: string
  payoutProofUrl: string
}

function PlatformWithdrawalsPanel({
  withdrawals,
  actionId,
  onRunAction,
  onRefresh,
}: {
  withdrawals: AdminWebPlatformWithdrawal[]
  actionId: string | null
  onRunAction: PlatformActionRunner
  onRefresh: () => Promise<void> | void
}) {
  const [expandedWithdrawalId, setExpandedWithdrawalId] = React.useState<number | null>(null)
  const [detail, setDetail] = React.useState<AdminWebPlatformWithdrawal | null>(null)
  const [detailError, setDetailError] = React.useState<string | null>(null)
  const [isDetailLoading, setIsDetailLoading] = React.useState(false)
  const [reviewDraft, setReviewDraft] = React.useState<PlatformWithdrawalReviewDraft>(() =>
    createPlatformWithdrawalReviewDraft(),
  )
  const reviewErrors = validatePlatformWithdrawalReviewDraft(reviewDraft)
  const completeReviewErrors = platformWithdrawalReviewErrorList(reviewErrors, [
    "completeNote",
    "payoutReference",
    "payoutProofUrl",
  ])
  const rejectNoteTouched = reviewDraft.rejectNote.length > 0
  const rejectReviewErrors = platformWithdrawalRejectErrorList(reviewDraft, reviewErrors)
  const pendingWithdrawalCount = withdrawals.filter(isPlatformWithdrawalPending).length

  const loadDetail = async (withdrawalId: number) => {
    if (expandedWithdrawalId === withdrawalId) {
      setExpandedWithdrawalId(null)
      setDetail(null)
      setDetailError(null)
      setReviewDraft(createPlatformWithdrawalReviewDraft())
      return
    }
    setExpandedWithdrawalId(withdrawalId)
    setDetail(null)
    setDetailError(null)
    setReviewDraft(createPlatformWithdrawalReviewDraft())
    setIsDetailLoading(true)
    try {
      setDetail(await getAdminWebPlatformWithdrawal(withdrawalId))
    } catch (error) {
      setDetailError(errorToMessage(error))
    } finally {
      setIsDetailLoading(false)
    }
  }

  return (
    <section className="flex flex-col gap-3 rounded-md border p-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-sm font-medium">提现审核</p>
          <p className="mt-1 text-xs text-muted-foreground">仅处理本地审核状态，不执行真实打款或链上查询。</p>
        </div>
        <Badge variant="outline">{pendingWithdrawalCount} / {withdrawals.length} 待审</Badge>
      </div>
      {withdrawals.length === 0 ? <StatusBlock title="暂无待审提现" detail="当前没有待审核提现申请。" /> : null}
      {withdrawals.slice(0, 5).map((withdrawal) => {
        const isExpanded = expandedWithdrawalId === withdrawal.withdrawal_id
        const currentWithdrawal =
          isExpanded && detail?.withdrawal_id === withdrawal.withdrawal_id ? detail : withdrawal
        const canReview = isPlatformWithdrawalPending(currentWithdrawal)
        const isRejecting = actionId === `withdrawal:reject:${withdrawal.withdrawal_id}`
        const isCompleting = actionId === `withdrawal:complete:${withdrawal.withdrawal_id}`
        const canReject =
          canReview && actionId === null && rejectReviewErrors.length === 0 && Boolean(reviewDraft.rejectNote.trim())
        const canComplete = canReview && actionId === null && completeReviewErrors.length === 0

        return (
          <div key={withdrawal.withdrawal_id} className="rounded-md border p-3">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-sm font-medium">{withdrawal.amount} {withdrawal.currency}</p>
                  <Badge variant={withdrawal.status === "pending" ? "secondary" : "outline"}>
                    {withdrawalStatusLabel(withdrawal.status)}
                  </Badge>
                </div>
                <p className="mt-1 truncate text-xs text-muted-foreground">
                  {withdrawal.store_name ?? "未知店铺"} · {withdrawal.network} · {withdrawal.address_masked}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">{formatDateTime(withdrawal.requested_at)}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant={isExpanded ? "secondary" : "outline"}
                  disabled={isDetailLoading || actionId !== null}
                  onClick={() => {
                    void loadDetail(withdrawal.withdrawal_id)
                  }}
                >
                  {isExpanded ? "收起" : "详情"}
                </Button>
              </div>
            </div>
            {isExpanded ? (
              <div className="mt-3 flex flex-col gap-3 rounded-md border p-3">
                {isDetailLoading ? (
                  <p className="text-xs text-muted-foreground">正在加载提现详情</p>
                ) : null}
                {detailError ? (
                  <div className="flex flex-col gap-1">
                    <p className="text-sm font-medium">提现详情加载失败</p>
                    <p className="text-xs text-muted-foreground">{detailError}</p>
                  </div>
                ) : null}
                {detail && !isDetailLoading ? (
                  <>
                    <div className="flex flex-col gap-2">
                      <div className="flex flex-col gap-1">
                        <p className="text-sm font-medium">安全摘要</p>
                        <p className="text-xs text-muted-foreground">
                          只显示脱敏地址和状态时间，不回显付款参考、凭证 URL 或审核备注。
                        </p>
                      </div>
                      <div className="grid gap-2 sm:grid-cols-2">
                        <MetricLine label="提现编号" value={String(detail.withdrawal_id)} />
                        <MetricLine label="店铺" value={detail.store_name ?? detail.tenant_public_id ?? "-"} />
                        <MetricLine label="金额" value={`${detail.amount} ${detail.currency}`} />
                        <MetricLine label="网络" value={detail.network} />
                        <MetricLine label="地址" value={detail.address_masked} />
                        <MetricLine label="状态" value={withdrawalStatusLabel(detail.status)} />
                        <MetricLine label="申请时间" value={formatDateTime(detail.requested_at)} />
                        <MetricLine label="审核时间" value={formatDateTime(detail.reviewed_at)} />
                        <MetricLine label="完成时间" value={formatDateTime(detail.completed_at)} />
                      </div>
                    </div>
                    <Separator />
                    {canReview ? (
                      <div className="flex flex-col gap-3">
                        <div className="flex flex-col gap-1">
                          <p className="text-sm font-medium">审核操作</p>
                          <p className="text-xs text-muted-foreground">
                            完成仅标记本地提现状态；真实打款、链上确认和凭证核验需在线下完成。
                          </p>
                        </div>
                        {rejectNoteTouched && rejectReviewErrors.length > 0 ? (
                          <p className="text-xs text-destructive">{rejectReviewErrors.join("；")}</p>
                        ) : null}
                        {completeReviewErrors.length > 0 ? (
                          <p className="text-xs text-destructive">{completeReviewErrors.join("；")}</p>
                        ) : null}
                        <div className="grid gap-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                          <Input
                            value={reviewDraft.rejectNote}
                            placeholder="拒绝备注，必填"
                            aria-label="拒绝提现审核备注"
                            aria-invalid={rejectNoteTouched && Boolean(reviewErrors.rejectNote)}
                            disabled={actionId !== null}
                            onChange={(event) =>
                              setReviewDraft((current) => ({ ...current, rejectNote: event.target.value }))
                            }
                          />
                          <Input
                            value={reviewDraft.completeNote}
                            placeholder="完成备注，可选"
                            aria-label="完成提现审核备注"
                            aria-invalid={Boolean(reviewErrors.completeNote)}
                            disabled={actionId !== null}
                            onChange={(event) =>
                              setReviewDraft((current) => ({ ...current, completeNote: event.target.value }))
                            }
                          />
                          <Input
                            value={reviewDraft.payoutReference}
                            placeholder="付款参考，可选"
                            aria-label="付款参考"
                            aria-invalid={Boolean(reviewErrors.payoutReference)}
                            disabled={actionId !== null}
                            onChange={(event) =>
                              setReviewDraft((current) => ({ ...current, payoutReference: event.target.value }))
                            }
                          />
                          <Input
                            value={reviewDraft.payoutProofUrl}
                            placeholder="凭证 URL，可选"
                            aria-label="付款凭证 URL"
                            aria-invalid={Boolean(reviewErrors.payoutProofUrl)}
                            disabled={actionId !== null}
                            onChange={(event) =>
                              setReviewDraft((current) => ({ ...current, payoutProofUrl: event.target.value }))
                            }
                          />
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={!canReject}
                            onClick={() =>
                              onRunAction(
                                `withdrawal:reject:${withdrawal.withdrawal_id}`,
                                `确认拒绝 ${withdrawal.amount} ${withdrawal.currency} 提现？`,
                                async () => {
                                  const result = await rejectAdminWebPlatformWithdrawal(withdrawal.withdrawal_id, {
                                    admin_note: reviewDraft.rejectNote.trim(),
                                  })
                                  await onRefresh()
                                  setExpandedWithdrawalId(null)
                                  setDetail(null)
                                  setReviewDraft(createPlatformWithdrawalReviewDraft())
                                  return `提现 ${result.withdrawal_id} 已拒绝。`
                                },
                              )
                            }
                          >
                            {isRejecting ? "拒绝中" : "拒绝"}
                          </Button>
                          <Button
                            size="sm"
                            variant="destructive"
                            disabled={!canComplete}
                            onClick={() =>
                              onRunAction(
                                `withdrawal:complete:${withdrawal.withdrawal_id}`,
                                `确认标记 ${withdrawal.amount} ${withdrawal.currency} 提现为已完成？`,
                                async () => {
                                  const result = await completeAdminWebPlatformWithdrawal(withdrawal.withdrawal_id, {
                                    admin_note: reviewDraft.completeNote.trim() || "Admin Web 人工确认",
                                    payout_reference: reviewDraft.payoutReference.trim() || undefined,
                                    payout_proof_url: reviewDraft.payoutProofUrl.trim() || undefined,
                                  })
                                  await onRefresh()
                                  setExpandedWithdrawalId(null)
                                  setDetail(null)
                                  setReviewDraft(createPlatformWithdrawalReviewDraft())
                                  return `提现 ${result.withdrawal_id} 已完成。`
                                },
                              )
                            }
                          >
                            {isCompleting ? "完成中" : "标记完成"}
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <p className="text-xs text-muted-foreground">该提现不是待审核状态，仅展示安全摘要。</p>
                    )}
                  </>
                ) : null}
              </div>
            ) : null}
          </div>
        )
      })}
    </section>
  )
}

type PlatformRiskAuditActionFilter = "all" | "user" | "tenant" | "supply" | "order" | "dispute"
type PlatformRiskAuditStatusFilter = "all" | "banned" | "active" | "suspended" | "grace" | "disabled" | "other"

function PlatformRiskPanel({
  bannedUsers,
  auditLogs,
  actionId,
  onRunAction,
}: {
  bannedUsers: AdminWebPlatformRiskBannedUser[]
  auditLogs: AdminWebPlatformRiskAuditLog[]
  actionId: string | null
  onRunAction: PlatformActionRunner
}) {
  const [auditQuery, setAuditQuery] = React.useState("")
  const [auditAction, setAuditAction] = React.useState<PlatformRiskAuditActionFilter>("all")
  const [auditStatus, setAuditStatus] = React.useState<PlatformRiskAuditStatusFilter>("all")
  const hasAuditFilters = auditQuery.trim().length > 0 || auditAction !== "all" || auditStatus !== "all"
  const filteredAuditLogs = React.useMemo(
    () =>
      auditLogs.filter((log) => {
        if (!platformRiskAuditActionMatches(log.action, auditAction)) {
          return false
        }
        if (!platformRiskAuditStatusMatches(log.new_status, auditStatus)) {
          return false
        }
        const normalizedQuery = auditQuery.trim().toLowerCase()
        if (!normalizedQuery) {
          return true
        }
        return platformRiskAuditSearchText(log).includes(normalizedQuery)
      }),
    [auditAction, auditLogs, auditQuery, auditStatus],
  )
  const displayedAuditLogs = filteredAuditLogs.slice(0, 8)

  return (
    <section className="flex flex-col gap-3 rounded-md border p-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium">平台风控</p>
        <Badge variant="outline">{bannedUsers.length} 人</Badge>
      </div>
      <PlatformUserBanForm actionId={actionId} onRunAction={onRunAction} />
      {bannedUsers.length === 0 ? <StatusBlock title="暂无封禁用户" detail="当前没有平台封禁中的 Telegram 用户。" /> : null}
      {bannedUsers.slice(0, 4).map((user) => (
        <div key={user.telegram_user_id} className="rounded-md border p-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">
                {user.username ? `@${user.username}` : user.telegram_user_id}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">{user.reason ?? user.latest_action ?? "手动封禁"}</p>
            </div>
            <Button
              size="sm"
              variant="outline"
              disabled={actionId !== null}
              onClick={() =>
                onRunAction(
                  `risk:user:active:${user.telegram_user_id}`,
                  `确认解除 ${user.telegram_user_id} 的平台封禁？`,
                  async () => {
                    await updateAdminWebPlatformUserBanStatus(user.telegram_user_id, {
                      status: "active",
                      reason: "Admin Web 解封",
                    })
                    return `${user.telegram_user_id} 已解除封禁。`
                  },
                )
              }
            >
              解封
            </Button>
          </div>
        </div>
      ))}
      <Separator />
      <div className="flex flex-col gap-2">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <p className="text-sm font-medium">审计日志</p>
            <p className="mt-1 text-xs text-muted-foreground">只读安全摘要，不展示内部 ID、raw payload 或凭据。</p>
          </div>
          <Badge variant="outline">{filteredAuditLogs.length} / {auditLogs.length}</Badge>
        </div>
        <div className="grid gap-2 lg:grid-cols-[minmax(0,1fr)_10rem_10rem_auto]">
          <Input
            value={auditQuery}
            placeholder="搜索动作/对象/TG/原因"
            aria-label="搜索平台风控审计日志"
            onChange={(event) => setAuditQuery(event.target.value)}
          />
          <Select value={auditAction} onValueChange={(value) => setAuditAction(value as PlatformRiskAuditActionFilter)}>
            <SelectTrigger aria-label="审计动作筛选">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectLabel>动作范围</SelectLabel>
                <SelectItem value="all">全部动作</SelectItem>
                <SelectItem value="user">用户风控</SelectItem>
                <SelectItem value="tenant">租户风控</SelectItem>
                <SelectItem value="supply">供货管控</SelectItem>
                <SelectItem value="order">订单拦截</SelectItem>
                <SelectItem value="dispute">售后/争议</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
          <Select value={auditStatus} onValueChange={(value) => setAuditStatus(value as PlatformRiskAuditStatusFilter)}>
            <SelectTrigger aria-label="审计状态筛选">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectLabel>状态</SelectLabel>
                <SelectItem value="all">全部状态</SelectItem>
                <SelectItem value="banned">已封禁</SelectItem>
                <SelectItem value="active">已恢复</SelectItem>
                <SelectItem value="suspended">已冻结</SelectItem>
                <SelectItem value="grace">宽限</SelectItem>
                <SelectItem value="disabled">已停用</SelectItem>
                <SelectItem value="other">其他状态</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!hasAuditFilters}
            onClick={() => {
              setAuditQuery("")
              setAuditAction("all")
              setAuditStatus("all")
            }}
          >
            重置
          </Button>
        </div>
        {auditLogs.length === 0 ? <StatusBlock title="暂无风控审计" detail="最近没有平台风控记录。" /> : null}
        {auditLogs.length > 0 && displayedAuditLogs.length === 0 ? (
          <StatusBlock title="没有匹配记录" detail="调整动作、状态或关键词后再查看审计日志。" />
        ) : null}
        {displayedAuditLogs.map((log, index) => (
          <div key={`${log.created_at}:${index}`} className="rounded-md border p-3">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{platformRiskAuditActionLabel(log.action)}</p>
                <p className="mt-1 text-xs text-muted-foreground">{formatDateTime(log.created_at)}</p>
              </div>
              <Badge variant={platformRiskAuditStatusBadgeVariant(log.new_status)}>
                {platformRiskAuditStatusLabel(log.new_status)}
              </Badge>
            </div>
            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
              <span>对象 {platformRiskAuditTargetLabel(log.target_type)}</span>
              <span>操作者 {platformRiskAuditActorLabel(log)}</span>
              {log.target_telegram_user_id ? <span>目标 TG {log.target_telegram_user_id}</span> : null}
              {log.previous_status || log.new_status ? (
                <span>
                  状态 {platformRiskAuditStatusLabel(log.previous_status)}{" -> "}
                  {platformRiskAuditStatusLabel(log.new_status)}
                </span>
              ) : null}
              {log.blocked_count !== null && log.blocked_count !== undefined ? <span>拦截 {log.blocked_count}</span> : null}
              {log.threshold !== null && log.threshold !== undefined ? <span>阈值 {log.threshold}</span> : null}
              {log.window_seconds !== null && log.window_seconds !== undefined ? <span>窗口 {log.window_seconds}s</span> : null}
            </div>
            <p className="mt-2 text-xs text-muted-foreground">{log.reason ?? "无备注"}</p>
            {log.risk_rule && log.risk_rule !== log.reason ? (
              <p className="mt-1 text-xs text-muted-foreground">规则 {log.risk_rule}</p>
            ) : null}
          </div>
        ))}
      </div>
    </section>
  )
}

function PlatformUserBanForm({
  actionId,
  onRunAction,
}: {
  actionId: string | null
  onRunAction: PlatformActionRunner
}) {
  const [telegramUserId, setTelegramUserId] = React.useState("")
  const [reason, setReason] = React.useState("")
  const isBusy = actionId !== null

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const normalizedUserId = Number(telegramUserId)
    if (!Number.isInteger(normalizedUserId) || normalizedUserId <= 0) {
      return
    }
    void onRunAction(
      `risk:user:banned:${normalizedUserId}`,
      `确认封禁 Telegram 用户 ${normalizedUserId}？`,
      async () => {
        await updateAdminWebPlatformUserBanStatus(normalizedUserId, {
          status: "banned",
          reason: reason.trim() || "Admin Web 手动封禁",
        })
        setTelegramUserId("")
        setReason("")
        return `${normalizedUserId} 已封禁。`
      },
    )
  }

  return (
    <form className="grid gap-2 rounded-md border p-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)_auto]" onSubmit={handleSubmit}>
      <Input value={telegramUserId} inputMode="numeric" placeholder="Telegram 用户 ID" aria-label="Telegram 用户 ID" disabled={isBusy} onChange={(event) => setTelegramUserId(event.target.value)} />
      <Input value={reason} placeholder="封禁原因" aria-label="封禁原因" disabled={isBusy} onChange={(event) => setReason(event.target.value)} />
      <Button type="submit" size="sm" variant="destructive" disabled={isBusy || !telegramUserId.trim()}>
        封禁
      </Button>
    </form>
  )
}

type PlatformSupplierOfferStatusFilter = "all" | "on" | "disabled"
type PlatformSupplierOfferApprovalFilter = "all" | "approval_required" | "open"
type PlatformSupplierOfferStockFilter = "all" | "available" | "empty"

function PlatformSupplyControlPanel({
  offers,
  actionId,
  onRunAction,
}: {
  offers: AdminWebPlatformSupplierOffer[]
  actionId: string | null
  onRunAction: PlatformActionRunner
}) {
  const [offerQuery, setOfferQuery] = React.useState("")
  const [statusFilter, setStatusFilter] = React.useState<PlatformSupplierOfferStatusFilter>("all")
  const [approvalFilter, setApprovalFilter] = React.useState<PlatformSupplierOfferApprovalFilter>("all")
  const [stockFilter, setStockFilter] = React.useState<PlatformSupplierOfferStockFilter>("all")
  const [actionReason, setActionReason] = React.useState("")
  const actionReasonError = platformSupplierOfferActionReasonError(actionReason)
  const hasFilters =
    offerQuery.trim().length > 0 || statusFilter !== "all" || approvalFilter !== "all" || stockFilter !== "all"
  const filteredOffers = React.useMemo(
    () =>
      offers.filter(
        (offer) =>
          platformSupplierOfferMatchesQuery(offer, offerQuery) &&
          platformSupplierOfferMatchesStatus(offer, statusFilter) &&
          platformSupplierOfferMatchesApproval(offer, approvalFilter) &&
          platformSupplierOfferMatchesStock(offer, stockFilter),
      ),
    [approvalFilter, offerQuery, offers, statusFilter, stockFilter],
  )
  const displayedOffers = filteredOffers.slice(0, 8)
  const enabledOfferCount = offers.filter((offer) => offer.status !== "disabled").length
  const disabledOfferCount = offers.filter((offer) => offer.status === "disabled").length
  const approvalRequiredCount = offers.filter((offer) => offer.requires_approval).length
  const isActionDisabled = actionId !== null || Boolean(actionReasonError)

  return (
    <section className="flex flex-col gap-3 rounded-md border p-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-sm font-medium">平台供货管控</p>
          <p className="mt-1 text-xs text-muted-foreground">只做供货商品软下架和恢复，不删除数据或触发真实分账。</p>
        </div>
        <Badge variant="outline">{filteredOffers.length} / {offers.length}</Badge>
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        <MetricLine label="可供货" value={String(enabledOfferCount)} />
        <MetricLine label="已软下架" value={String(disabledOfferCount)} />
        <MetricLine label="需审批" value={String(approvalRequiredCount)} />
      </div>
      <div className="grid gap-2 lg:grid-cols-[minmax(0,1fr)_10rem_10rem_10rem_auto]">
        <Input
          value={offerQuery}
          placeholder="搜索商品/供应商/发货"
          aria-label="搜索平台供货商品"
          onChange={(event) => setOfferQuery(event.target.value)}
        />
        <Select value={statusFilter} onValueChange={(value) => setStatusFilter(value as PlatformSupplierOfferStatusFilter)}>
          <SelectTrigger aria-label="供货商品状态筛选">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectLabel>状态</SelectLabel>
              <SelectItem value="all">全部状态</SelectItem>
              <SelectItem value="on">可供货</SelectItem>
              <SelectItem value="disabled">已软下架</SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
        <Select value={approvalFilter} onValueChange={(value) => setApprovalFilter(value as PlatformSupplierOfferApprovalFilter)}>
          <SelectTrigger aria-label="供货审批方式筛选">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectLabel>审批方式</SelectLabel>
              <SelectItem value="all">全部方式</SelectItem>
              <SelectItem value="approval_required">需审批</SelectItem>
              <SelectItem value="open">免审批</SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
        <Select value={stockFilter} onValueChange={(value) => setStockFilter(value as PlatformSupplierOfferStockFilter)}>
          <SelectTrigger aria-label="供货库存筛选">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectLabel>库存</SelectLabel>
              <SelectItem value="all">全部库存</SelectItem>
              <SelectItem value="available">有库存</SelectItem>
              <SelectItem value="empty">无库存</SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={!hasFilters}
          onClick={() => {
            setOfferQuery("")
            setStatusFilter("all")
            setApprovalFilter("all")
            setStockFilter("all")
          }}
        >
          重置
        </Button>
      </div>
      <div className="flex flex-col gap-2">
        <Input
          value={actionReason}
          placeholder="操作原因，可选，最多 255 字"
          aria-label="平台供货商品状态操作原因"
          aria-invalid={Boolean(actionReasonError)}
          disabled={actionId !== null}
          onChange={(event) => setActionReason(event.target.value)}
        />
        {actionReasonError ? <p className="text-xs text-destructive">{actionReasonError}</p> : null}
      </div>
      {offers.length === 0 ? <StatusBlock title="暂无供货商品" detail="当前没有平台可管控供货商品。" /> : null}
      {offers.length > 0 && displayedOffers.length === 0 ? (
        <StatusBlock title="没有匹配商品" detail="调整关键词、状态、审批方式或库存筛选后再查看供货商品。" />
      ) : null}
      {displayedOffers.map((offer) => {
        const nextStatus = offer.status === "disabled" ? "on" : "disabled"
        return (
          <div key={offer.supplier_offer_id} className="rounded-md border p-3">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="truncate text-sm font-medium">{offer.product_name}</p>
                  <Badge variant={offer.status === "disabled" ? "destructive" : "secondary"}>
                    {supplierOfferStatusLabel(offer.status)}
                  </Badge>
                  <Badge variant="outline">{platformSupplierOfferApprovalLabel(offer)}</Badge>
                </div>
                <p className="mt-1 truncate text-xs text-muted-foreground">
                  {offer.supplier_store_name} · {deliveryTypeLabel(offer.delivery_type)} · 库存 {offer.available_count}
                </p>
                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                  <MetricLine label="建议价" value={`${offer.suggested_price} ${offer.currency}`} />
                  <MetricLine label="最低价" value={offer.min_sale_price ? `${offer.min_sale_price} ${offer.currency}` : "-"} />
                  <MetricLine label="供货成本" value={`${offer.supplier_cost} ${offer.currency}`} />
                  <MetricLine label="更新" value={formatDateTime(offer.updated_at)} />
                </div>
              </div>
              <Button
                size="sm"
                variant={nextStatus === "disabled" ? "destructive" : "outline"}
                disabled={isActionDisabled}
                onClick={() =>
                  onRunAction(
                    `supply:${nextStatus}:${offer.supplier_offer_id}`,
                    `确认${nextStatus === "disabled" ? "软下架" : "恢复"}供货商品 ${offer.product_name}？`,
                    async () => {
                      const result = await updateAdminWebPlatformSupplierOfferStatus(offer.supplier_offer_id, {
                        status: nextStatus,
                        reason: actionReason.trim() || "Admin Web 平台供货管控",
                      })
                      setActionReason("")
                      return `${result.product_name} 已${result.status === "disabled" ? "软下架" : "恢复"}。`
                    },
                  )
                }
              >
                {nextStatus === "disabled" ? "软下架" : "恢复"}
              </Button>
            </div>
          </div>
        )
      })}
    </section>
  )
}

function CloneBotPanel({
  currentWorkspace,
  view,
}: {
  currentWorkspace?: AdminWebWorkspace
  view?: AdminView
}) {
  const isTenantWorkspace = currentWorkspace?.kind === "tenant"
  const [overview, setOverview] = React.useState<AdminWebTenantOverview | null>(null)
  const [storeSettings, setStoreSettings] = React.useState<AdminWebTenantStoreSettings | null>(null)
  const [products, setProducts] = React.useState<AdminWebTenantProductsResponse | null>(null)
  const [orders, setOrders] = React.useState<AdminWebTenantOrdersResponse | null>(null)
  const [paymentConfigs, setPaymentConfigs] = React.useState<AdminWebTenantPaymentProviderConfigsResponse | null>(null)
  const [businessPluginCapabilities, setBusinessPluginCapabilities] =
    React.useState<AdminWebBusinessPluginCapabilitiesResponse | null>(null)
  const [businessPluginCapabilitiesLoading, setBusinessPluginCapabilitiesLoading] = React.useState(false)
  const [businessPluginCapabilitiesError, setBusinessPluginCapabilitiesError] = React.useState<string | null>(null)
  const [externalSourceConnections, setExternalSourceConnections] =
    React.useState<AdminWebExternalSourceConnectionsResponse | null>(null)
  const [externalSourceConnectionsLoading, setExternalSourceConnectionsLoading] = React.useState(false)
  const [externalSourceConnectionsError, setExternalSourceConnectionsError] = React.useState<string | null>(null)
  const [externalSourceActionId, setExternalSourceActionId] = React.useState<string | null>(null)
  const [externalSourceActionResult, setExternalSourceActionResult] =
    React.useState<SupplyActionResult | null>(null)
  const [externalSourceCatalogProducts, setExternalSourceCatalogProducts] =
    React.useState<AdminWebExternalSourceCatalogProductsResponse | null>(null)
  const [externalSourceCatalogProductsHandle, setExternalSourceCatalogProductsHandle] =
    React.useState<string | null>(null)
  const [externalSourceCatalogProductsError, setExternalSourceCatalogProductsError] =
    React.useState<string | null>(null)
  const [subscriptionDashboard, setSubscriptionDashboard] =
    React.useState<AdminWebTenantSubscriptionDashboard | null>(null)
  const [financeDashboard, setFinanceDashboard] = React.useState<AdminWebTenantFinanceDashboard | null>(null)
  const [tenantAuditLogs, setTenantAuditLogs] = React.useState<AdminWebTenantAuditLogsResponse | null>(null)
  const [tenantAuditLogsLoading, setTenantAuditLogsLoading] = React.useState(false)
  const [tenantAuditLogsError, setTenantAuditLogsError] = React.useState<string | null>(null)
  const [tenantRiskDashboard, setTenantRiskDashboard] = React.useState<AdminWebTenantRiskDashboard | null>(null)
  const [tenantRiskLoading, setTenantRiskLoading] = React.useState(false)
  const [tenantRiskError, setTenantRiskError] = React.useState<string | null>(null)
  const [tenantRiskStatus, setTenantRiskStatus] = React.useState<AdminWebTenantRiskStatusFilter>("open")
  const [tenantReportJobs, setTenantReportJobs] =
    React.useState<AdminWebTenantReportExportJobsResponse | null>(null)
  const [tenantReportJobsLoading, setTenantReportJobsLoading] = React.useState(false)
  const [tenantReportJobsError, setTenantReportJobsError] = React.useState<string | null>(null)
  const [tenantReportJobStatus, setTenantReportJobStatus] =
    React.useState<AdminWebTenantReportStatusFilter>(defaultTenantReportJobFilters.status)
  const [tenantReportJobType, setTenantReportJobType] =
    React.useState<AdminWebTenantReportTypeFilter>(defaultTenantReportJobFilters.report_type)
  const [tenantReportJobActionId, setTenantReportJobActionId] = React.useState<string | null>(null)
  const [tenantReportJobActionResult, setTenantReportJobActionResult] =
    React.useState<SupplyActionResult | null>(null)
  const [tenantApiKeys, setTenantApiKeys] = React.useState<AdminWebTenantApiKeysResponse | null>(null)
  const [tenantApiKeysLoading, setTenantApiKeysLoading] = React.useState(false)
  const [tenantApiKeysError, setTenantApiKeysError] = React.useState<string | null>(null)
  const [tenantApiKeyActionId, setTenantApiKeyActionId] = React.useState<string | null>(null)
  const [tenantApiKeyActionResult, setTenantApiKeyActionResult] =
    React.useState<SupplyActionResult | null>(null)
  const [createdTenantApiKey, setCreatedTenantApiKey] =
    React.useState<AdminWebCreatedTenantApiKey | null>(null)
  const [supplyDashboard, setSupplyDashboard] = React.useState<AdminWebSupplyDashboard | null>(null)
  const [supplyActionId, setSupplyActionId] = React.useState<string | null>(null)
  const [supplyActionResult, setSupplyActionResult] = React.useState<SupplyActionResult | null>(null)
  const [storeSettingsActionId, setStoreSettingsActionId] = React.useState<string | null>(null)
  const [storeSettingsActionResult, setStoreSettingsActionResult] =
    React.useState<SupplyActionResult | null>(null)
  const [paymentActionId, setPaymentActionId] = React.useState<string | null>(null)
  const [paymentActionResult, setPaymentActionResult] = React.useState<SupplyActionResult | null>(null)
  const [subscriptionActionId, setSubscriptionActionId] = React.useState<string | null>(null)
  const [subscriptionActionResult, setSubscriptionActionResult] = React.useState<SupplyActionResult | null>(null)
  const [subscriptionRenewalOrder, setSubscriptionRenewalOrder] =
    React.useState<AdminWebTenantSubscriptionRenewalOrder | null>(null)
  const [financeActionId, setFinanceActionId] = React.useState<string | null>(null)
  const [financeActionResult, setFinanceActionResult] = React.useState<SupplyActionResult | null>(null)
  const [subscriptionFinanceLoading, setSubscriptionFinanceLoading] = React.useState(false)
  const [subscriptionFinanceError, setSubscriptionFinanceError] = React.useState<string | null>(null)
  const [supplyMarketFilters, setSupplyMarketFilters] =
    React.useState<AdminWebSupplyDashboardFilters>(defaultSupplyMarketFilters)
  const [productFilters, setProductFilters] =
    React.useState<AdminWebTenantProductFilters>(defaultTenantProductFilters)
  const [orderFilters, setOrderFilters] =
    React.useState<AdminWebTenantOrderFilters>(defaultTenantOrderFilters)
  const [selectedOrderDiagnostics, setSelectedOrderDiagnostics] =
    React.useState<AdminWebTenantOrderDiagnostics | null>(null)
  const [orderDiagnosticsActionId, setOrderDiagnosticsActionId] = React.useState<string | null>(null)
  const [orderDiagnosticsError, setOrderDiagnosticsError] = React.useState<string | null>(null)
  const [orderObservability, setOrderObservability] =
    React.useState<AdminWebTenantOrderObservability | null>(null)
  const [orderObservabilityLoading, setOrderObservabilityLoading] = React.useState(false)
  const [orderObservabilityError, setOrderObservabilityError] = React.useState<string | null>(null)
  const [orderObservabilityOutTradeNo, setOrderObservabilityOutTradeNo] = React.useState<string | null>(null)
  const [isLoading, setIsLoading] = React.useState(false)
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null)

  const loadTenantWorkspace = React.useCallback(async () => {
    if (!isTenantWorkspace) {
      setOverview(null)
      setStoreSettings(null)
      setProducts(null)
      setOrders(null)
      setPaymentConfigs(null)
      setBusinessPluginCapabilities(null)
      setBusinessPluginCapabilitiesLoading(false)
      setBusinessPluginCapabilitiesError(null)
      setExternalSourceConnections(null)
      setExternalSourceConnectionsLoading(false)
      setExternalSourceConnectionsError(null)
      setExternalSourceActionId(null)
      setExternalSourceActionResult(null)
      setExternalSourceCatalogProducts(null)
      setExternalSourceCatalogProductsHandle(null)
      setExternalSourceCatalogProductsError(null)
      setSubscriptionDashboard(null)
      setFinanceDashboard(null)
      setTenantAuditLogs(null)
      setTenantAuditLogsLoading(false)
      setTenantAuditLogsError(null)
      setTenantRiskDashboard(null)
      setTenantRiskLoading(false)
      setTenantRiskError(null)
      setTenantRiskStatus("open")
      setTenantReportJobs(null)
      setTenantReportJobsLoading(false)
      setTenantReportJobsError(null)
      setTenantReportJobStatus(defaultTenantReportJobFilters.status)
      setTenantReportJobType(defaultTenantReportJobFilters.report_type)
      setTenantReportJobActionId(null)
      setTenantReportJobActionResult(null)
      setTenantApiKeys(null)
      setTenantApiKeysLoading(false)
      setTenantApiKeysError(null)
      setTenantApiKeyActionId(null)
      setTenantApiKeyActionResult(null)
      setCreatedTenantApiKey(null)
      setSupplyDashboard(null)
      setSupplyActionId(null)
      setSupplyActionResult(null)
      setStoreSettingsActionId(null)
      setStoreSettingsActionResult(null)
      setPaymentActionId(null)
      setPaymentActionResult(null)
      setSubscriptionActionId(null)
      setSubscriptionActionResult(null)
      setSubscriptionRenewalOrder(null)
      setFinanceActionId(null)
      setFinanceActionResult(null)
      setSubscriptionFinanceLoading(false)
      setSubscriptionFinanceError(null)
      setSupplyMarketFilters(defaultSupplyMarketFilters)
      setProductFilters(defaultTenantProductFilters)
      setOrderFilters(defaultTenantOrderFilters)
      setSelectedOrderDiagnostics(null)
      setOrderDiagnosticsActionId(null)
      setOrderDiagnosticsError(null)
      setOrderObservability(null)
      setOrderObservabilityLoading(false)
      setOrderObservabilityError(null)
      setOrderObservabilityOutTradeNo(null)
      setErrorMessage(null)
      return
    }

    setIsLoading(true)
    setErrorMessage(null)
    try {
      const nextOrderObservabilityOutTradeNo =
        normalizedOrderObservationTradeNo(orderFilters.out_trade_no) ?? null
      const [nextOverview, nextStoreSettings, nextProducts, nextOrders, nextOrderObservability] = await Promise.all([
        getAdminWebTenantOverview(),
        getAdminWebTenantStoreSettings(),
        getAdminWebTenantProducts(productFilters),
        getAdminWebTenantOrders(orderFilters),
        getAdminWebTenantOrderObservability({
          limit: 8,
          out_trade_no: nextOrderObservabilityOutTradeNo ?? undefined,
        }),
      ])
      const [nextPaymentConfigs, nextSubscriptionDashboard, nextFinanceDashboard, nextSupplyDashboard] = await Promise.all([
        getAdminWebTenantPaymentConfigs(),
        getAdminWebTenantSubscriptionDashboard(8),
        getAdminWebTenantFinanceDashboard(8),
        getAdminWebSupplyDashboard(20, supplyMarketFilters),
      ])
      setOverview(nextOverview)
      setStoreSettings(nextStoreSettings)
      setProducts(nextProducts)
      setOrders(nextOrders)
      setOrderObservability(nextOrderObservability)
      setOrderObservabilityError(null)
      setOrderObservabilityOutTradeNo(nextOrderObservabilityOutTradeNo)
      setPaymentConfigs(nextPaymentConfigs)
      setSubscriptionDashboard(nextSubscriptionDashboard)
      setFinanceDashboard(nextFinanceDashboard)
      setSubscriptionFinanceError(null)
      setSupplyDashboard(nextSupplyDashboard)
      setSelectedOrderDiagnostics((current) => {
        if (!current || nextOrders.items.some((order) => order.out_trade_no === current.out_trade_no)) {
          return current
        }
        return null
      })
    } catch (error) {
      setOverview(null)
      setStoreSettings(null)
      setProducts(null)
      setOrders(null)
      setPaymentConfigs(null)
      setBusinessPluginCapabilities(null)
      setSubscriptionDashboard(null)
      setFinanceDashboard(null)
      setTenantAuditLogs(null)
      setTenantRiskDashboard(null)
      setTenantReportJobs(null)
      setTenantApiKeys(null)
      setSupplyDashboard(null)
      setSelectedOrderDiagnostics(null)
      setOrderObservability(null)
      setOrderObservabilityError(errorToMessage(error))
      setOrderObservabilityOutTradeNo(null)
      setSubscriptionFinanceError(errorToMessage(error))
      setErrorMessage(errorToMessage(error))
    } finally {
      setIsLoading(false)
    }
  }, [isTenantWorkspace, currentWorkspace?.workspace_id, supplyMarketFilters, productFilters, orderFilters])

  const loadSubscriptionFinance = React.useCallback(async () => {
    if (!isTenantWorkspace) {
      setSubscriptionDashboard(null)
      setFinanceDashboard(null)
      setSubscriptionFinanceLoading(false)
      setSubscriptionFinanceError(null)
      return
    }

    setSubscriptionFinanceLoading(true)
    setSubscriptionFinanceError(null)
    try {
      const [nextSubscriptionDashboard, nextFinanceDashboard] = await Promise.all([
        getAdminWebTenantSubscriptionDashboard(8),
        getAdminWebTenantFinanceDashboard(8),
      ])
      setSubscriptionDashboard(nextSubscriptionDashboard)
      setFinanceDashboard(nextFinanceDashboard)
    } catch (error) {
      setSubscriptionDashboard(null)
      setFinanceDashboard(null)
      setSubscriptionFinanceError(errorToMessage(error))
    } finally {
      setSubscriptionFinanceLoading(false)
    }
  }, [isTenantWorkspace, currentWorkspace?.workspace_id])

  const loadTenantOrderObservability = React.useCallback(async () => {
    if (!isTenantWorkspace) {
      setOrderObservability(null)
      setOrderObservabilityLoading(false)
      setOrderObservabilityError(null)
      setOrderObservabilityOutTradeNo(null)
      return
    }

    setOrderObservabilityLoading(true)
    setOrderObservabilityError(null)
    try {
      setOrderObservability(
        await getAdminWebTenantOrderObservability({
          limit: 8,
          out_trade_no: orderObservabilityOutTradeNo ?? undefined,
        }),
      )
    } catch (error) {
      setOrderObservability(null)
      setOrderObservabilityError(errorToMessage(error))
    } finally {
      setOrderObservabilityLoading(false)
    }
  }, [isTenantWorkspace, currentWorkspace?.workspace_id, orderObservabilityOutTradeNo])

  const loadTenantOrderObservabilityForTradeNo = React.useCallback(
    async (outTradeNo: string | null) => {
      if (!isTenantWorkspace) {
        setOrderObservability(null)
        setOrderObservabilityLoading(false)
        setOrderObservabilityError(null)
        setOrderObservabilityOutTradeNo(null)
        return
      }

      setOrderObservabilityOutTradeNo(outTradeNo)
      setOrderObservabilityLoading(true)
      setOrderObservabilityError(null)
      try {
        setOrderObservability(
          await getAdminWebTenantOrderObservability({
            limit: 8,
            out_trade_no: outTradeNo ?? undefined,
          }),
        )
      } catch (error) {
        setOrderObservability(null)
        setOrderObservabilityError(errorToMessage(error))
      } finally {
        setOrderObservabilityLoading(false)
      }
    },
    [isTenantWorkspace, currentWorkspace?.workspace_id],
  )

  const loadTenantAuditLogs = React.useCallback(async () => {
    if (!isTenantWorkspace) {
      setTenantAuditLogs(null)
      setTenantAuditLogsLoading(false)
      setTenantAuditLogsError(null)
      return
    }

    setTenantAuditLogsLoading(true)
    setTenantAuditLogsError(null)
    try {
      setTenantAuditLogs(await getAdminWebTenantAuditLogs({ limit: 8 }))
    } catch (error) {
      setTenantAuditLogs(null)
      setTenantAuditLogsError(errorToMessage(error))
    } finally {
      setTenantAuditLogsLoading(false)
    }
  }, [isTenantWorkspace, currentWorkspace?.workspace_id])

  const loadTenantRiskDashboard = React.useCallback(async () => {
    if (!isTenantWorkspace) {
      setTenantRiskDashboard(null)
      setTenantRiskLoading(false)
      setTenantRiskError(null)
      return
    }

    setTenantRiskLoading(true)
    setTenantRiskError(null)
    try {
      setTenantRiskDashboard(await getAdminWebTenantRiskDashboard({ status: tenantRiskStatus, limit: 8 }))
    } catch (error) {
      setTenantRiskDashboard(null)
      setTenantRiskError(errorToMessage(error))
    } finally {
      setTenantRiskLoading(false)
    }
  }, [isTenantWorkspace, currentWorkspace?.workspace_id, tenantRiskStatus])

  const loadTenantReportJobs = React.useCallback(async () => {
    if (!isTenantWorkspace) {
      setTenantReportJobs(null)
      setTenantReportJobsLoading(false)
      setTenantReportJobsError(null)
      return
    }

    setTenantReportJobsLoading(true)
    setTenantReportJobsError(null)
    try {
      setTenantReportJobs(
        await getAdminWebTenantReportExportJobs({
          status: tenantReportJobStatus,
          report_type: tenantReportJobType,
          limit: defaultTenantReportJobFilters.limit,
        }),
      )
    } catch (error) {
      setTenantReportJobs(null)
      setTenantReportJobsError(errorToMessage(error))
    } finally {
      setTenantReportJobsLoading(false)
    }
  }, [isTenantWorkspace, currentWorkspace?.workspace_id, tenantReportJobStatus, tenantReportJobType])

  const loadTenantApiKeys = React.useCallback(async () => {
    if (!isTenantWorkspace) {
      setTenantApiKeys(null)
      setTenantApiKeysLoading(false)
      setTenantApiKeysError(null)
      return
    }

    setTenantApiKeysLoading(true)
    setTenantApiKeysError(null)
    try {
      setTenantApiKeys(await getAdminWebTenantApiKeys(8))
    } catch (error) {
      setTenantApiKeys(null)
      setTenantApiKeysError(errorToMessage(error))
    } finally {
      setTenantApiKeysLoading(false)
    }
  }, [isTenantWorkspace, currentWorkspace?.workspace_id])

  const loadBusinessPluginCapabilities = React.useCallback(async () => {
    if (!isTenantWorkspace) {
      setBusinessPluginCapabilities(null)
      setBusinessPluginCapabilitiesLoading(false)
      setBusinessPluginCapabilitiesError(null)
      return
    }

    setBusinessPluginCapabilitiesLoading(true)
    setBusinessPluginCapabilitiesError(null)
    try {
      setBusinessPluginCapabilities(await getAdminWebBusinessPluginCapabilities())
    } catch (error) {
      setBusinessPluginCapabilities(null)
      setBusinessPluginCapabilitiesError(errorToMessage(error))
    } finally {
      setBusinessPluginCapabilitiesLoading(false)
    }
  }, [isTenantWorkspace, currentWorkspace?.workspace_id])

  const loadExternalSourceConnections = React.useCallback(async () => {
    if (!isTenantWorkspace) {
      setExternalSourceConnections(null)
      setExternalSourceConnectionsLoading(false)
      setExternalSourceConnectionsError(null)
      setExternalSourceCatalogProducts(null)
      setExternalSourceCatalogProductsHandle(null)
      setExternalSourceCatalogProductsError(null)
      return
    }

    setExternalSourceConnectionsLoading(true)
    setExternalSourceConnectionsError(null)
    try {
      setExternalSourceConnections(await getAdminWebExternalSourceConnections())
    } catch (error) {
      setExternalSourceConnections(null)
      setExternalSourceConnectionsError(errorToMessage(error))
    } finally {
      setExternalSourceConnectionsLoading(false)
    }
  }, [isTenantWorkspace, currentWorkspace?.workspace_id])

  React.useEffect(() => {
    setSupplyActionId(null)
    setSupplyActionResult(null)
    setStoreSettingsActionId(null)
    setStoreSettingsActionResult(null)
    setPaymentActionId(null)
    setPaymentActionResult(null)
    setSubscriptionActionId(null)
    setSubscriptionActionResult(null)
    setSubscriptionRenewalOrder(null)
    setFinanceActionId(null)
    setFinanceActionResult(null)
    setSubscriptionFinanceLoading(false)
    setSubscriptionFinanceError(null)
    setTenantAuditLogs(null)
    setTenantAuditLogsLoading(false)
    setTenantAuditLogsError(null)
    setTenantRiskDashboard(null)
    setTenantRiskLoading(false)
    setTenantRiskError(null)
    setTenantRiskStatus("open")
    setTenantReportJobs(null)
    setTenantReportJobsLoading(false)
    setTenantReportJobsError(null)
    setTenantReportJobStatus(defaultTenantReportJobFilters.status)
    setTenantReportJobType(defaultTenantReportJobFilters.report_type)
    setTenantReportJobActionId(null)
    setTenantReportJobActionResult(null)
    setTenantApiKeys(null)
    setTenantApiKeysLoading(false)
    setTenantApiKeysError(null)
    setTenantApiKeyActionId(null)
    setTenantApiKeyActionResult(null)
    setCreatedTenantApiKey(null)
    setBusinessPluginCapabilities(null)
    setBusinessPluginCapabilitiesLoading(false)
    setBusinessPluginCapabilitiesError(null)
    setExternalSourceConnections(null)
    setExternalSourceConnectionsLoading(false)
    setExternalSourceConnectionsError(null)
    setExternalSourceActionId(null)
    setExternalSourceActionResult(null)
    setExternalSourceCatalogProducts(null)
    setExternalSourceCatalogProductsHandle(null)
    setExternalSourceCatalogProductsError(null)
    setSupplyMarketFilters(defaultSupplyMarketFilters)
    setProductFilters(defaultTenantProductFilters)
    setOrderFilters(defaultTenantOrderFilters)
    setSelectedOrderDiagnostics(null)
    setOrderDiagnosticsActionId(null)
    setOrderDiagnosticsError(null)
    setOrderObservability(null)
    setOrderObservabilityLoading(false)
    setOrderObservabilityError(null)
    setOrderObservabilityOutTradeNo(null)
  }, [currentWorkspace?.workspace_id])

  React.useEffect(() => {
    void loadTenantWorkspace()
  }, [loadTenantWorkspace])

  React.useEffect(() => {
    void loadTenantAuditLogs()
  }, [loadTenantAuditLogs])

  React.useEffect(() => {
    void loadTenantRiskDashboard()
  }, [loadTenantRiskDashboard])

  React.useEffect(() => {
    void loadTenantReportJobs()
  }, [loadTenantReportJobs])

  React.useEffect(() => {
    void loadTenantApiKeys()
  }, [loadTenantApiKeys])

  React.useEffect(() => {
    void loadBusinessPluginCapabilities()
  }, [loadBusinessPluginCapabilities])

  React.useEffect(() => {
    void loadExternalSourceConnections()
  }, [loadExternalSourceConnections])

  const handleUpdateStoreSettings = React.useCallback(
    async (payload: AdminWebTenantStoreSettingsPayload) => {
      const storeName = payload.store_name?.trim()
      const welcomeText = payload.welcome_text?.trim()
      const supportText = payload.support_text?.trim()
      const orderTimeoutMinutes = payload.order_timeout_minutes
      if (storeName !== undefined && (storeName.length < 2 || storeName.length > 64)) {
        setStoreSettingsActionResult({ kind: "error", message: "店铺名称长度应为 2-64 个字符。" })
        return
      }
      if (welcomeText !== undefined && welcomeText.length > 500) {
        setStoreSettingsActionResult({ kind: "error", message: "欢迎语长度不能超过 500 个字符。" })
        return
      }
      if (supportText !== undefined && supportText.length > 300) {
        setStoreSettingsActionResult({ kind: "error", message: "客服信息长度不能超过 300 个字符。" })
        return
      }
      if (
        orderTimeoutMinutes !== undefined &&
        (!Number.isInteger(orderTimeoutMinutes) || orderTimeoutMinutes < 1 || orderTimeoutMinutes > 1440)
      ) {
        setStoreSettingsActionResult({ kind: "error", message: "订单超时时间范围为 1-1440 分钟。" })
        return
      }

      const normalizedPayload: AdminWebTenantStoreSettingsPayload = {}
      if (storeName !== undefined) {
        normalizedPayload.store_name = storeName
      }
      if (welcomeText !== undefined) {
        normalizedPayload.welcome_text = welcomeText
      }
      if (supportText !== undefined) {
        normalizedPayload.support_text = supportText
      }
      if (orderTimeoutMinutes !== undefined) {
        normalizedPayload.order_timeout_minutes = orderTimeoutMinutes
      }
      if (payload.self_sale_enabled !== undefined) {
        normalizedPayload.self_sale_enabled = payload.self_sale_enabled
      }
      if (payload.supplier_enabled !== undefined) {
        normalizedPayload.supplier_enabled = payload.supplier_enabled
      }
      if (payload.reseller_enabled !== undefined) {
        normalizedPayload.reseller_enabled = payload.reseller_enabled
      }

      const actionId = "store-settings:update"
      setStoreSettingsActionId(actionId)
      setStoreSettingsActionResult(null)
      try {
        const nextSettings = await updateAdminWebTenantStoreSettings(normalizedPayload)
        setStoreSettings(nextSettings)
        setStoreSettingsActionResult({
          kind: "success",
          message: "店铺设置已保存。",
        })
        await loadTenantWorkspace()
      } catch (error) {
        setStoreSettingsActionResult({ kind: "error", message: errorToMessage(error) })
      } finally {
        setStoreSettingsActionId(null)
      }
    },
    [loadTenantWorkspace],
  )

  const handleSupplyApply = React.useCallback(
    async (offer: AdminWebSupplyMarketOffer) => {
      const actionId = `apply:${offer.supplier_offer_id}`
      setSupplyActionId(actionId)
      setSupplyActionResult(null)
      try {
        const application = await createAdminWebSupplyApplication({
          supplier_offer_id: offer.supplier_offer_id,
        })
        setSupplyActionResult({
          kind: "success",
          message: `${application.product_name} 已提交代理申请，等待供应商审核。`,
        })
        await loadTenantWorkspace()
      } catch (error) {
        setSupplyActionResult({ kind: "error", message: errorToMessage(error) })
      } finally {
        setSupplyActionId(null)
      }
    },
    [loadTenantWorkspace],
  )

  const handleUpdateProductMetadata = React.useCallback(
    async (productId: number, payload: AdminWebProductMetadataPayload) => {
      const category = typeof payload.category === "string" ? payload.category.trim() : payload.category
      const sortOrder = payload.sort_order
      if (sortOrder !== undefined && (!Number.isInteger(sortOrder) || sortOrder < -100000 || sortOrder > 100000)) {
        setSupplyActionResult({ kind: "error", message: "请输入 -100000 到 100000 之间的整数排序值。" })
        return
      }

      const actionId = `product:metadata:${productId}`
      setSupplyActionId(actionId)
      setSupplyActionResult(null)
      try {
        const product = await updateAdminWebProductMetadata(productId, {
          category: category === "" ? null : category,
          sort_order: sortOrder,
        })
        setSupplyActionResult({
          kind: "success",
          message: `${product.name} 的分类和排序已保存。`,
        })
        await loadTenantWorkspace()
      } catch (error) {
        setSupplyActionResult({ kind: "error", message: errorToMessage(error) })
      } finally {
        setSupplyActionId(null)
      }
    },
    [loadTenantWorkspace],
  )

  const handleCreateProduct = React.useCallback(
    async (payload: AdminWebCreateProductPayload) => {
      const name = payload.name.trim()
      const price = payload.price.trim()
      const category = typeof payload.category === "string" ? payload.category.trim() : payload.category
      const description = typeof payload.description === "string" ? payload.description.trim() : payload.description
      if (name.length < 2) {
        setSupplyActionResult({ kind: "error", message: "请输入至少 2 个字符的商品名称。" })
        return
      }
      if (!isPositiveDecimalText(price)) {
        setSupplyActionResult({ kind: "error", message: "请输入大于 0 的商品售价。" })
        return
      }

      const actionId = "product:create"
      setSupplyActionId(actionId)
      setSupplyActionResult(null)
      try {
        const product = await createAdminWebTenantProduct({
          name,
          price,
          delivery_type: payload.delivery_type,
          category: category === "" ? null : category,
          description: description === "" ? undefined : description,
        })
        setSupplyActionResult({
          kind: "success",
          message: `${product.name} 已创建为草稿商品。`,
        })
        await loadTenantWorkspace()
      } catch (error) {
        setSupplyActionResult({ kind: "error", message: errorToMessage(error) })
      } finally {
        setSupplyActionId(null)
      }
    },
    [loadTenantWorkspace],
  )

  const handleUpdateProductSales = React.useCallback(
    async (productId: number, payload: AdminWebProductSalesPayload) => {
      const price = typeof payload.price === "string" ? payload.price.trim() : payload.price
      if (price !== undefined && !isPositiveDecimalText(price)) {
        setSupplyActionResult({ kind: "error", message: "请输入大于 0 的商品售价。" })
        return
      }

      const actionId = `product:sales:${productId}`
      setSupplyActionId(actionId)
      setSupplyActionResult(null)
      try {
        const product = await updateAdminWebProductSales(productId, {
          price,
          status: payload.status,
        })
        setSupplyActionResult({
          kind: "success",
          message: `${product.name} 的售价和状态已保存。`,
        })
        await loadTenantWorkspace()
      } catch (error) {
        setSupplyActionResult({ kind: "error", message: errorToMessage(error) })
      } finally {
        setSupplyActionId(null)
      }
    },
    [loadTenantWorkspace],
  )

  const handleBatchUpdateProductStatus = React.useCallback(
    async (payload: AdminWebProductBatchStatusPayload) => {
      const productIds = Array.from(
        new Set(
          payload.product_ids.filter((productId) => Number.isInteger(productId) && productId > 0),
        ),
      )
      if (productIds.length === 0) {
        setSupplyActionResult({ kind: "error", message: "请选择要批量操作的商品。" })
        return
      }
      if (productIds.length > 50) {
        setSupplyActionResult({ kind: "error", message: "单次最多批量操作 50 个商品。" })
        return
      }
      if (payload.status !== "on" && payload.status !== "off") {
        setSupplyActionResult({ kind: "error", message: "请选择有效的目标状态。" })
        return
      }

      const actionId = `product:batch-status:${payload.status}`
      setSupplyActionId(actionId)
      setSupplyActionResult(null)
      try {
        const result = await batchUpdateAdminWebProductStatus({
          product_ids: productIds,
          status: payload.status,
        })
        setSupplyActionResult({
          kind: "success",
          message: `已${payload.status === "on" ? "上架" : "下架"} ${result.updated_count} 个商品。`,
        })
        await loadTenantWorkspace()
      } catch (error) {
        setSupplyActionResult({ kind: "error", message: errorToMessage(error) })
      } finally {
        setSupplyActionId(null)
      }
    },
    [loadTenantWorkspace],
  )

  const handleImportProductInventory = React.useCallback(
    async (productId: number, payload: AdminWebProductInventoryImportPayload) => {
      const items = payload.items.map((item) => item.trim()).filter(Boolean)
      if (items.length === 0) {
        setSupplyActionResult({ kind: "error", message: "请输入至少一条库存内容。" })
        return false
      }
      if (items.length > 1000) {
        setSupplyActionResult({ kind: "error", message: "单次最多导入 1000 条库存。" })
        return false
      }

      const actionId = `product:inventory-import:${productId}`
      setSupplyActionId(actionId)
      setSupplyActionResult(null)
      try {
        const result = await importAdminWebProductInventory(productId, { items })
        setSupplyActionResult({
          kind: "success",
          message: `已导入 ${result.added_count} 条库存，跳过 ${result.existing_count + result.input_duplicate_count} 条重复。`,
        })
        await loadTenantWorkspace()
        return true
      } catch (error) {
        setSupplyActionResult({ kind: "error", message: errorToMessage(error) })
        return false
      } finally {
        setSupplyActionId(null)
      }
    },
    [loadTenantWorkspace],
  )

  const handleUploadProductDeliveryFile = React.useCallback(
    async (productId: number, file: File | null) => {
      if (!file) {
        setSupplyActionResult({ kind: "error", message: "请选择要绑定的文件。" })
        return false
      }

      const actionId = `product:file-bind:${productId}`
      setSupplyActionId(actionId)
      setSupplyActionResult(null)
      try {
        const result = await uploadAdminWebProductDeliveryFile(productId, file)
        setSupplyActionResult({
          kind: result.bound ? "success" : "error",
          message: result.bound
            ? `${result.filename} 已绑定，扫描风险等级 ${result.risk_level}。`
            : `${result.filename} 未绑定：${result.scan_message}`,
        })
        await loadTenantWorkspace()
        return result.bound
      } catch (error) {
        setSupplyActionResult({ kind: "error", message: errorToMessage(error) })
        return false
      } finally {
        setSupplyActionId(null)
      }
    },
    [loadTenantWorkspace],
  )

  const handleUpdatePaymentConfig = React.useCallback(
    async (providerName: AdminWebPaymentProviderName, payload: AdminWebPaymentProviderConfigPayload) => {
      const normalizedPayload = trimPaymentConfigPayload(payload)
      if (!normalizedPayload.gateway_url && !normalizedPayload.base_url) {
        setPaymentActionResult({ kind: "error", message: "请输入支付网关地址。" })
        return
      }
      if (providerName === "epusdt_gmpay" && !normalizedPayload.pid && !normalizedPayload.merchant_id) {
        setPaymentActionResult({ kind: "error", message: "请输入 EPUSDT 商户 ID。" })
        return
      }
      if (providerName === "epusdt_gmpay" && !normalizedPayload.secret_key && !normalizedPayload.key) {
        setPaymentActionResult({ kind: "error", message: "请输入 EPUSDT 密钥。" })
        return
      }
      if (providerName === "epay_compatible" && !normalizedPayload.merchant_id) {
        setPaymentActionResult({ kind: "error", message: "请输入易支付商户 ID。" })
        return
      }
      if (providerName === "epay_compatible" && !normalizedPayload.key) {
        setPaymentActionResult({ kind: "error", message: "请输入易支付密钥。" })
        return
      }

      const actionId = `payment:update:${providerName}`
      setPaymentActionId(actionId)
      setPaymentActionResult(null)
      try {
        const config = await updateAdminWebTenantPaymentConfig(providerName, normalizedPayload)
        setPaymentActionResult({
          kind: "success",
          message: `${config.display_name} 配置已保存。`,
        })
        await loadTenantWorkspace()
      } catch (error) {
        setPaymentActionResult({ kind: "error", message: errorToMessage(error) })
      } finally {
        setPaymentActionId(null)
      }
    },
    [loadTenantWorkspace],
  )

  const handleDisablePaymentConfig = React.useCallback(
    async (providerName: AdminWebPaymentProviderName) => {
      const actionId = `payment:disable:${providerName}`
      setPaymentActionId(actionId)
      setPaymentActionResult(null)
      try {
        const config = await disableAdminWebTenantPaymentConfig(providerName)
        setPaymentActionResult({
          kind: "success",
          message: `${config.display_name} 已停用。`,
        })
        await loadTenantWorkspace()
      } catch (error) {
        setPaymentActionResult({ kind: "error", message: errorToMessage(error) })
      } finally {
        setPaymentActionId(null)
      }
    },
    [loadTenantWorkspace],
  )

  const handleCreateSubscriptionRenewalOrder = React.useCallback(
    async (payload: AdminWebCreateTenantSubscriptionRenewalOrderPayload) => {
      const months = payload.months
      if (!Number.isInteger(months) || months < 1 || months > 24) {
        setSubscriptionActionResult({ kind: "error", message: "续费月数范围为 1-24。" })
        return
      }

      const actionId = "subscription:renewal-order"
      setSubscriptionActionId(actionId)
      setSubscriptionActionResult(null)
      setSubscriptionRenewalOrder(null)
      try {
        const order = await createAdminWebTenantSubscriptionRenewalOrder({ months })
        setSubscriptionRenewalOrder(order)
        setSubscriptionActionResult({
          kind: "success",
          message: order.payment_available
            ? `${order.out_trade_no} 已创建，可打开支付页。`
            : `${order.out_trade_no} 已创建，${order.payment_failure_reason ?? "支付暂不可用"}。`,
        })
        await loadSubscriptionFinance()
      } catch (error) {
        setSubscriptionActionResult({ kind: "error", message: errorToMessage(error) })
      } finally {
        setSubscriptionActionId(null)
      }
    },
    [loadSubscriptionFinance],
  )

  const handleCreateWithdrawal = React.useCallback(
    async (payload: AdminWebCreateTenantWithdrawalPayload) => {
      const amount = payload.amount.trim()
      const network = payload.network.trim().toUpperCase()
      const address = payload.address.trim()
      const currency = (payload.currency ?? "USDT").trim().toUpperCase()
      if (!isPositiveDecimalText(amount)) {
        setFinanceActionResult({ kind: "error", message: "请输入有效提现金额，最多 8 位小数。" })
        return
      }
      if (network.length < 2 || network.length > 32) {
        setFinanceActionResult({ kind: "error", message: "请输入有效提现网络。" })
        return
      }
      if (address.length < 8 || address.length > 256) {
        setFinanceActionResult({ kind: "error", message: "请输入有效提现地址。" })
        return
      }

      const actionId = "finance:withdrawal:create"
      setFinanceActionId(actionId)
      setFinanceActionResult(null)
      try {
        const withdrawal = await createAdminWebTenantWithdrawal({
          amount,
          network,
          address,
          currency,
        })
        setFinanceActionResult({
          kind: "success",
          message: `${withdrawal.amount} ${withdrawal.currency} 提现申请已提交，等待平台审核。`,
        })
        await loadSubscriptionFinance()
      } catch (error) {
        setFinanceActionResult({ kind: "error", message: errorToMessage(error) })
      } finally {
        setFinanceActionId(null)
      }
    },
    [loadSubscriptionFinance],
  )

  const handleCreateReportExportJob = React.useCallback(
    async (payload: AdminWebCreateTenantReportExportJobPayload) => {
      const reportType = normalizeTenantReportType(payload.report_type)
      const actionId = `report:create:${reportType}`
      setTenantReportJobActionId(actionId)
      setTenantReportJobActionResult(null)
      try {
        const job = await createAdminWebTenantReportExportJob({ report_type: reportType })
        setTenantReportJobActionResult({
          kind: "success",
          message: `${tenantReportTypeLabel(job.report_type)}报表任务已创建。`,
        })
        await loadTenantReportJobs()
      } catch (error) {
        setTenantReportJobActionResult({ kind: "error", message: errorToMessage(error) })
      } finally {
        setTenantReportJobActionId(null)
      }
    },
    [loadTenantReportJobs],
  )

  const handleDownloadReportExportJob = React.useCallback(async (job: AdminWebTenantReportExportJob) => {
    const downloadHandle = job.download_handle?.trim()
    if (!downloadHandle) {
      setTenantReportJobActionResult({ kind: "error", message: "该报表暂不可下载。" })
      return
    }

    const actionId = `report:download:${downloadHandle}`
    setTenantReportJobActionId(actionId)
    setTenantReportJobActionResult(null)
    try {
      const file = await downloadAdminWebTenantReportExportJob(downloadHandle)
      const url = URL.createObjectURL(file.blob)
      const link = document.createElement("a")
      link.href = url
      link.download = file.filename
      document.body.append(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
      setTenantReportJobActionResult({
        kind: "success",
        message: `${tenantReportTypeLabel(job.report_type)}报表已开始下载。`,
      })
    } catch (error) {
      setTenantReportJobActionResult({ kind: "error", message: errorToMessage(error) })
    } finally {
      setTenantReportJobActionId(null)
    }
  }, [])

  const handleCreateTenantApiKey = React.useCallback(
    async (payload: AdminWebCreateTenantApiKeyPayload) => {
      const name = payload.name.trim()
      if (!name || name.length > 128) {
        setTenantApiKeyActionResult({ kind: "error", message: "API Key 名称长度应为 1-128 个字符。" })
        return
      }

      const actionId = "api-key:create"
      setTenantApiKeyActionId(actionId)
      setTenantApiKeyActionResult(null)
      setCreatedTenantApiKey(null)
      try {
        const apiKey = await createAdminWebTenantApiKey({
          name,
          scopes: payload.scopes,
          ip_allowlist: payload.ip_allowlist,
        })
        setCreatedTenantApiKey(apiKey)
        setTenantApiKeyActionResult({
          kind: "success",
          message: `${apiKey.name} 已创建，请立即保存明文 Key。`,
        })
        await loadTenantApiKeys()
      } catch (error) {
        setTenantApiKeyActionResult({ kind: "error", message: errorToMessage(error) })
      } finally {
        setTenantApiKeyActionId(null)
      }
    },
    [loadTenantApiKeys],
  )

  const handleRevokeTenantApiKey = React.useCallback(
    async (apiKey: AdminWebTenantApiKey) => {
      if (!window.confirm(`确认吊销 ${apiKey.name}？吊销后使用该 Key 的接口请求会立即失效。`)) {
        return
      }

      const actionId = `api-key:revoke:${apiKey.credential_handle}`
      setTenantApiKeyActionId(actionId)
      setTenantApiKeyActionResult(null)
      try {
        await revokeAdminWebTenantApiKey({ credential_handle: apiKey.credential_handle })
        setTenantApiKeyActionResult({ kind: "success", message: `${apiKey.name} 已吊销。` })
        setCreatedTenantApiKey((current) =>
          current?.credential_handle === apiKey.credential_handle ? null : current,
        )
        await loadTenantApiKeys()
      } catch (error) {
        setTenantApiKeyActionResult({ kind: "error", message: errorToMessage(error) })
      } finally {
        setTenantApiKeyActionId(null)
      }
    },
    [loadTenantApiKeys],
  )

  const handleRefreshTenantApiKeys = React.useCallback(() => {
    setCreatedTenantApiKey(null)
    void loadTenantApiKeys()
  }, [loadTenantApiKeys])

  const handleCreateExternalSourceConnection = React.useCallback(
    async (payload: AdminWebCreateExternalSourceConnectionPayload) => {
      const providerName = payload.provider_name.trim()
      const sourceKey = payload.source_key?.trim() ?? ""
      const displayName = payload.display_name.trim()
      const credentials = Object.fromEntries(
        Object.entries(payload.credentials)
          .map(([key, value]) => [key.trim(), value.trim()])
          .filter(([key, value]) => key !== "" && value !== ""),
      )

      if (!providerName) {
        setExternalSourceActionResult({ kind: "error", message: "请选择外部货源插件。" })
        return false
      }
      if (!displayName || displayName.length > 128) {
        setExternalSourceActionResult({ kind: "error", message: "连接名称长度应为 1-128 个字符。" })
        return false
      }
      if (sourceKey.length > 128) {
        setExternalSourceActionResult({ kind: "error", message: "来源标识长度不能超过 128 个字符。" })
        return false
      }
      if (Object.keys(credentials).length === 0) {
        setExternalSourceActionResult({ kind: "error", message: "请输入至少一项外部源凭据。" })
        return false
      }

      const actionId = "external-source:create"
      setExternalSourceActionId(actionId)
      setExternalSourceActionResult(null)
      try {
        const connection = await createAdminWebExternalSourceConnection({
          provider_name: providerName,
          source_key: sourceKey,
          display_name: displayName,
          credentials,
        })
        setExternalSourceActionResult({
          kind: "success",
          message: `${connection.display_name} 已创建，当前状态 ${externalSourceStatusLabel(connection.status)}。`,
        })
        await Promise.all([loadExternalSourceConnections(), loadBusinessPluginCapabilities()])
        return true
      } catch (error) {
        setExternalSourceActionResult({ kind: "error", message: errorToMessage(error) })
        return false
      } finally {
        setExternalSourceActionId(null)
      }
    },
    [loadBusinessPluginCapabilities, loadExternalSourceConnections],
  )

  const handleDisableExternalSourceConnection = React.useCallback(
    async (connection: AdminWebExternalSourceConnection) => {
      if (!window.confirm(`确认停用外部源连接 ${connection.display_name}？停用后不会再作为当前 Bot 的可用上游连接。`)) {
        return
      }

      const actionId = `external-source:disable:${connection.connection_handle}`
      setExternalSourceActionId(actionId)
      setExternalSourceActionResult(null)
      try {
        const nextConnection = await disableAdminWebExternalSourceConnection(connection.connection_handle)
        setExternalSourceActionResult({
          kind: "success",
          message: `${nextConnection.display_name} 已停用。`,
        })
        await Promise.all([loadExternalSourceConnections(), loadBusinessPluginCapabilities()])
      } catch (error) {
        setExternalSourceActionResult({ kind: "error", message: errorToMessage(error) })
      } finally {
        setExternalSourceActionId(null)
      }
    },
    [loadBusinessPluginCapabilities, loadExternalSourceConnections],
  )

  const handleViewExternalSourceCatalogProducts = React.useCallback(
    async (connection: AdminWebExternalSourceConnection) => {
      const actionId = `external-source:catalog-products:${connection.connection_handle}`
      setExternalSourceActionId(actionId)
      setExternalSourceActionResult(null)
      setExternalSourceCatalogProductsHandle(connection.connection_handle)
      setExternalSourceCatalogProductsError(null)
      try {
        const page = await getAdminWebExternalSourceCatalogProducts(connection.connection_handle, {
          limit: 20,
          offset: 0,
        })
        setExternalSourceCatalogProducts(page)
      } catch (error) {
        setExternalSourceCatalogProducts(null)
        setExternalSourceCatalogProductsError(errorToMessage(error))
      } finally {
        setExternalSourceActionId(null)
      }
    },
    [],
  )

  const handleSyncExternalSourceCatalog = React.useCallback(
    async (connection: AdminWebExternalSourceConnection) => {
      if (
        !window.confirm(
          `确认从外部源连接 ${connection.display_name} 同步一页商品目录？这会创建或更新当前 Bot 的本地商品摘要。`,
        )
      ) {
        return
      }

      const actionId = `external-source:sync-catalog:${connection.connection_handle}`
      setExternalSourceActionId(actionId)
      setExternalSourceActionResult(null)
      try {
        const result = await syncAdminWebExternalCatalog({
          connection_handle: connection.connection_handle,
          limit: 20,
          max_pages: 1,
        })
        setExternalSourceActionResult({
          kind: "success",
          message: `目录同步完成：新增 ${result.created_count}，更新 ${result.updated_count}，跳过 ${result.skipped_count}。`,
        })
        await Promise.all([
          loadExternalSourceConnections(),
          loadBusinessPluginCapabilities(),
          loadTenantWorkspace(),
        ])
        if (externalSourceCatalogProducts?.connection_handle === connection.connection_handle) {
          await handleViewExternalSourceCatalogProducts(connection)
        }
      } catch (error) {
        setExternalSourceActionResult({ kind: "error", message: errorToMessage(error) })
      } finally {
        setExternalSourceActionId(null)
      }
    },
    [
      externalSourceCatalogProducts?.connection_handle,
      handleViewExternalSourceCatalogProducts,
      loadBusinessPluginCapabilities,
      loadExternalSourceConnections,
      loadTenantWorkspace,
    ],
  )

  const handleLoadOrderDiagnostics = React.useCallback(async (order: AdminWebTenantOrder) => {
    const actionId = `order:diagnostics:${order.out_trade_no}`
    setOrderDiagnosticsActionId(actionId)
    setOrderDiagnosticsError(null)
    try {
      const diagnostics = await getAdminWebTenantOrderDiagnostics(order.out_trade_no)
      setSelectedOrderDiagnostics(diagnostics)
    } catch (error) {
      setOrderDiagnosticsError(errorToMessage(error))
    } finally {
      setOrderDiagnosticsActionId(null)
    }
  }, [])

  const handleLoadOrderObservabilityForOrder = React.useCallback(
    (order: AdminWebTenantOrder) => {
      void loadTenantOrderObservabilityForTradeNo(order.out_trade_no)
    },
    [loadTenantOrderObservabilityForTradeNo],
  )

  const handleClearOrderObservabilityScope = React.useCallback(() => {
    void loadTenantOrderObservabilityForTradeNo(null)
  }, [loadTenantOrderObservabilityForTradeNo])

  const handleCreateResellerProduct = React.useCallback(
    async (payload: AdminWebCreateResellerProductPayload) => {
      const salePrice = payload.sale_price.trim()
      const displayName = payload.display_name?.trim()
      const numericSalePrice = Number(salePrice)
      if (!salePrice || !Number.isFinite(numericSalePrice) || numericSalePrice <= 0) {
        setSupplyActionResult({ kind: "error", message: "请输入有效的代理售价。" })
        return
      }

      const actionId = `create:${payload.supplier_offer_id}`
      setSupplyActionId(actionId)
      setSupplyActionResult(null)
      try {
        const product = await createAdminWebResellerProduct({
          supplier_offer_id: payload.supplier_offer_id,
          sale_price: salePrice,
          display_name: displayName || undefined,
        })
        setSupplyActionResult({
          kind: "success",
          message: `${product.display_name} 已上架到当前克隆 Bot。`,
        })
        await loadTenantWorkspace()
      } catch (error) {
        setSupplyActionResult({ kind: "error", message: errorToMessage(error) })
      } finally {
        setSupplyActionId(null)
      }
    },
    [loadTenantWorkspace],
  )

  const handleUpdateResellerProductMetadata = React.useCallback(
    async (resellerProductId: number, payload: AdminWebResellerProductMetadataPayload) => {
      const category = typeof payload.category === "string" ? payload.category.trim() : payload.category
      const sortOrder = payload.sort_order
      if (sortOrder !== undefined && (!Number.isInteger(sortOrder) || sortOrder < -100000 || sortOrder > 100000)) {
        setSupplyActionResult({ kind: "error", message: "请输入 -100000 到 100000 之间的整数排序值。" })
        return
      }

      const actionId = `reseller-product:metadata:${resellerProductId}`
      setSupplyActionId(actionId)
      setSupplyActionResult(null)
      try {
        const product = await updateAdminWebResellerProductMetadata(resellerProductId, {
          category: category === "" ? null : category,
          sort_order: sortOrder,
        })
        setSupplyActionResult({
          kind: "success",
          message: `${product.display_name} 的分类和排序已保存。`,
        })
        await loadTenantWorkspace()
      } catch (error) {
        setSupplyActionResult({ kind: "error", message: errorToMessage(error) })
      } finally {
        setSupplyActionId(null)
      }
    },
    [loadTenantWorkspace],
  )

  const handleUpdateResellerProductSales = React.useCallback(
    async (resellerProductId: number, payload: AdminWebResellerProductSalesPayload) => {
      const displayName = typeof payload.display_name === "string" ? payload.display_name.trim() : payload.display_name
      const salePrice = payload.sale_price?.trim()
      if (!displayName && !salePrice) {
        setSupplyActionResult({ kind: "error", message: "请填写代理商品展示名或售价。" })
        return
      }
      if (salePrice !== undefined && salePrice !== "" && !isPositiveDecimalText(salePrice)) {
        setSupplyActionResult({ kind: "error", message: "代理售价必须是大于 0 的金额。" })
        return
      }

      const actionId = `reseller-product:sales:${resellerProductId}`
      setSupplyActionId(actionId)
      setSupplyActionResult(null)
      try {
        const product = await updateAdminWebResellerProductSales(resellerProductId, {
          display_name: displayName === "" ? null : displayName,
          sale_price: salePrice || undefined,
        })
        setSupplyActionResult({
          kind: "success",
          message: `${product.display_name} 的展示名和售价已保存。`,
        })
        await loadTenantWorkspace()
      } catch (error) {
        setSupplyActionResult({ kind: "error", message: errorToMessage(error) })
      } finally {
        setSupplyActionId(null)
      }
    },
    [loadTenantWorkspace],
  )

  const handleReviewSupplierApplication = React.useCallback(
    async (payload: AdminWebSupplierApplicationReviewPayload) => {
      const actionId = `${payload.action}:${payload.supplier_application_id}`
      setSupplyActionId(actionId)
      setSupplyActionResult(null)
      try {
        const application = await reviewAdminWebSupplierApplication(payload)
        setSupplyActionResult({
          kind: "success",
          message: `${application.reseller_store_name} 的 ${application.product_name} 申请已${payload.action === "approve" ? "通过" : "拒绝"}。`,
        })
        await loadTenantWorkspace()
      } catch (error) {
        setSupplyActionResult({ kind: "error", message: errorToMessage(error) })
      } finally {
        setSupplyActionId(null)
      }
    },
    [loadTenantWorkspace],
  )

  const handleCreateSupplierOffer = React.useCallback(
    async (payload: AdminWebCreateSupplierOfferPayload) => {
      const suggestedPrice = payload.suggested_price.trim()
      const minSalePrice = payload.min_sale_price?.trim()
      const numericSuggestedPrice = Number(suggestedPrice)
      const numericMinSalePrice = minSalePrice ? Number(minSalePrice) : null
      if (!payload.product_id || !Number.isFinite(numericSuggestedPrice) || numericSuggestedPrice <= 0) {
        setSupplyActionResult({ kind: "error", message: "请选择商品并输入有效建议售价。" })
        return
      }
      if (numericMinSalePrice !== null && (!Number.isFinite(numericMinSalePrice) || numericMinSalePrice < 0)) {
        setSupplyActionResult({ kind: "error", message: "请输入有效最低售价。" })
        return
      }

      const actionId = `supplier-offer:create:${payload.product_id}`
      setSupplyActionId(actionId)
      setSupplyActionResult(null)
      try {
        const offer = await createAdminWebSupplierOffer({
          product_id: payload.product_id,
          suggested_price: suggestedPrice,
          min_sale_price: minSalePrice || undefined,
          requires_approval: payload.requires_approval,
        })
        setSupplyActionResult({
          kind: "success",
          message: `${offer.product_name} 已开放供货。`,
        })
        await loadTenantWorkspace()
      } catch (error) {
        setSupplyActionResult({ kind: "error", message: errorToMessage(error) })
      } finally {
        setSupplyActionId(null)
      }
    },
    [loadTenantWorkspace],
  )

  const handleSetSupplierOfferApproval = React.useCallback(
    async (supplierOfferId: number, payload: AdminWebSupplierOfferApprovalPayload) => {
      const actionId = `supplier-offer:approval:${supplierOfferId}`
      setSupplyActionId(actionId)
      setSupplyActionResult(null)
      try {
        await updateAdminWebSupplierOfferApproval(supplierOfferId, payload)
        setSupplyActionResult({
          kind: "success",
          message: `供货商品已切换为${payload.requires_approval ? "需审批" : "免审批"}。`,
        })
        await loadTenantWorkspace()
      } catch (error) {
        setSupplyActionResult({ kind: "error", message: errorToMessage(error) })
      } finally {
        setSupplyActionId(null)
      }
    },
    [loadTenantWorkspace],
  )

  const handleSetSupplierRule = React.useCallback(
    async (payload: AdminWebSupplierRulePayload) => {
      const pricingValue = payload.pricing_value.trim()
      const minSalePrice = payload.min_sale_price?.trim()
      const numericPricingValue = Number(pricingValue)
      const numericMinSalePrice = minSalePrice ? Number(minSalePrice) : null
      if (!pricingValue || !Number.isFinite(numericPricingValue) || numericPricingValue <= 0) {
        setSupplyActionResult({ kind: "error", message: "请输入有效供应商成本。" })
        return
      }
      if (numericMinSalePrice !== null && (!Number.isFinite(numericMinSalePrice) || numericMinSalePrice < 0)) {
        setSupplyActionResult({ kind: "error", message: "请输入有效最低售价。" })
        return
      }

      const actionId = `supplier-rule:${payload.supplier_rule_id}`
      setSupplyActionId(actionId)
      setSupplyActionResult(null)
      try {
        const rule = await updateAdminWebSupplierRule({
          supplier_rule_id: payload.supplier_rule_id,
          pricing_value: pricingValue,
          min_sale_price: minSalePrice || undefined,
        })
        setSupplyActionResult({
          kind: "success",
          message: `${rule.reseller_store_name} 的 ${rule.product_name} 独立规则已保存。`,
        })
        await loadTenantWorkspace()
      } catch (error) {
        setSupplyActionResult({ kind: "error", message: errorToMessage(error) })
      } finally {
        setSupplyActionId(null)
      }
    },
    [loadTenantWorkspace],
  )

  const handleApplySupplyMarketFilters = React.useCallback((filters: AdminWebSupplyDashboardFilters) => {
    const validationError = validateSupplyMarketFilters(filters)
    if (validationError) {
      setSupplyActionResult({ kind: "error", message: validationError })
      return
    }
    setSupplyActionResult(null)
    setSupplyMarketFilters(normalizeSupplyMarketFilters(filters))
  }, [])

  const handleApplyProductFilters = React.useCallback((filters: AdminWebTenantProductFilters) => {
    setSupplyActionResult(null)
    setProductFilters(normalizeTenantProductFilters(filters))
  }, [])

  const handleApplyOrderFilters = React.useCallback((filters: AdminWebTenantOrderFilters) => {
    const normalizedFilters = normalizeTenantOrderFilters(filters)
    setOrderDiagnosticsError(null)
    setOrderObservabilityError(null)
    setOrderObservabilityOutTradeNo(normalizedOrderObservationTradeNo(normalizedFilters.out_trade_no) ?? null)
    setSelectedOrderDiagnostics(null)
    setOrderFilters(normalizedFilters)
  }, [])

  const handleProductPageChange = React.useCallback((offset: number) => {
    setProductFilters((current) => normalizeTenantProductFilters({ ...current, offset }))
  }, [])

  const handleOrderPageChange = React.useCallback((offset: number) => {
    setOrderDiagnosticsError(null)
    setOrderObservabilityError(null)
    setSelectedOrderDiagnostics(null)
    setOrderFilters((current) => normalizeTenantOrderFilters({ ...current, offset }))
  }, [])

  const renderStoreSettingsForm = () =>
    storeSettings ? (
      <Card>
        <CardHeader>
          <CardTitle>店铺设置</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <CloneBotStoreSettingsForm
            settings={storeSettings}
            actionId={storeSettingsActionId}
            actionResult={storeSettingsActionResult}
            onUpdateStoreSettings={handleUpdateStoreSettings}
          />
        </CardContent>
      </Card>
    ) : null

  const renderPaymentSettings = () =>
    paymentConfigs ? (
      <Card>
        <CardHeader>
          <CardTitle>支付设置</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <CloneBotPaymentSettingsPanel
            configs={paymentConfigs.providers}
            actionId={paymentActionId}
            actionResult={paymentActionResult}
            onUpdatePaymentConfig={handleUpdatePaymentConfig}
            onDisablePaymentConfig={handleDisablePaymentConfig}
          />
        </CardContent>
      </Card>
    ) : null

  if (view && view !== "Bot工作台") {
    if (!isTenantWorkspace) {
      return (
        <Card>
          <CardHeader>
            <CardTitle>克隆 Bot</CardTitle>
            <CardDescription>请从顶部工作区选择器切换到店铺工作区。</CardDescription>
          </CardHeader>
          <CardContent>
            <StatusBlock title="未选择克隆 Bot" detail="请从顶部工作区选择器切换到店铺工作区。" />
          </CardContent>
        </Card>
      )
    }
    return (
      <div className="flex flex-col gap-4">
        {isLoading ? <StatusBlock title="正在加载" detail="正在读取店铺数据。" /> : null}
        {errorMessage ? (
          <div className="flex flex-col gap-3 rounded-md border p-3">
            <p className="text-sm font-medium">数据加载失败</p>
            <p className="text-xs text-muted-foreground">{errorMessage}</p>
            <Button variant="outline" size="sm" className="w-fit" onClick={loadTenantWorkspace}>
              重新加载
            </Button>
          </div>
        ) : null}
        {view === "总览" && overview ? (
          <Card>
            <CardHeader>
              <CardTitle>概览</CardTitle>
              <CardDescription>商品、订单、支付与供货摘要。</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <CloneBotOverviewContent overview={overview} />
            </CardContent>
          </Card>
        ) : null}
        {view === "克隆Bot" ? (
          <>
            {renderStoreSettingsForm()}
            {renderPaymentSettings()}
            {products && orders ? (
              <Card>
                <CardHeader>
                  <CardTitle>商品与订单</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-4">
                  <CloneBotRecentLists
                    products={products}
                    orders={orders}
                    productFilters={productFilters}
                    orderFilters={orderFilters}
                    isRefreshing={isLoading}
                    actionId={supplyActionId}
                    actionResult={supplyActionResult}
                    selectedOrderDiagnostics={selectedOrderDiagnostics}
                    orderDiagnosticsActionId={orderDiagnosticsActionId}
                    orderDiagnosticsError={orderDiagnosticsError}
                    orderObservability={orderObservability}
                    orderObservabilityLoading={orderObservabilityLoading}
                    orderObservabilityError={orderObservabilityError}
                    orderObservabilityOutTradeNo={orderObservabilityOutTradeNo}
                    onCreateProduct={handleCreateProduct}
                    onUpdateProductMetadata={handleUpdateProductMetadata}
                    onUpdateProductSales={handleUpdateProductSales}
                    onBatchUpdateProductStatus={handleBatchUpdateProductStatus}
                    onImportProductInventory={handleImportProductInventory}
                    onUploadProductDeliveryFile={handleUploadProductDeliveryFile}
                    onLoadOrderDiagnostics={handleLoadOrderDiagnostics}
                    onLoadOrderObservabilityForOrder={handleLoadOrderObservabilityForOrder}
                    onApplyProductFilters={handleApplyProductFilters}
                    onApplyOrderFilters={handleApplyOrderFilters}
                    onProductPageChange={handleProductPageChange}
                    onOrderPageChange={handleOrderPageChange}
                    onRefreshOrderObservability={loadTenantOrderObservability}
                    onClearOrderObservabilityScope={handleClearOrderObservabilityScope}
                    onRefresh={loadTenantWorkspace}
                  />
                </CardContent>
              </Card>
            ) : null}
            {supplyDashboard ? (
              <Card>
                <CardHeader>
                  <CardTitle>供货市场</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-4">
                  <SupplyDashboardPanel
                    dashboard={supplyDashboard}
                    currentWorkspace={currentWorkspace}
                    actionId={supplyActionId}
                    actionResult={supplyActionResult}
                    onSupplyApply={handleSupplyApply}
                    onReviewSupplierApplication={handleReviewSupplierApplication}
                    onCreateSupplierOffer={handleCreateSupplierOffer}
                    onSetSupplierOfferApproval={handleSetSupplierOfferApproval}
                    onSetSupplierRule={handleSetSupplierRule}
                    onCreateResellerProduct={handleCreateResellerProduct}
                    onUpdateResellerProductMetadata={handleUpdateResellerProductMetadata}
                    onUpdateResellerProductSales={handleUpdateResellerProductSales}
                    marketFilters={supplyMarketFilters}
                    onApplyMarketFilters={handleApplySupplyMarketFilters}
                    products={products?.items ?? []}
                  />
                </CardContent>
              </Card>
            ) : null}
          </>
        ) : null}
        {view === "商户结算" ? (
          <CloneBotSubscriptionFinancePanel
            overview={overview}
            currentWorkspace={currentWorkspace}
            subscriptionDashboard={subscriptionDashboard}
            financeDashboard={financeDashboard}
            isRefreshing={isLoading || subscriptionFinanceLoading}
            errorMessage={subscriptionFinanceError}
            actionId={subscriptionActionId}
            actionResult={subscriptionActionResult}
            renewalOrder={subscriptionRenewalOrder}
            financeActionId={financeActionId}
            financeActionResult={financeActionResult}
            onCreateRenewalOrder={handleCreateSubscriptionRenewalOrder}
            onCreateWithdrawal={handleCreateWithdrawal}
            onRefresh={loadSubscriptionFinance}
          />
        ) : null}
        {view === "系统设置" ? (
          <>
            {renderStoreSettingsForm()}
            {renderPaymentSettings()}
            <CloneBotApiKeysPanel
              currentWorkspace={currentWorkspace}
              apiKeys={tenantApiKeys}
              createdApiKey={createdTenantApiKey}
              isRefreshing={tenantApiKeysLoading}
              errorMessage={tenantApiKeysError}
              actionId={tenantApiKeyActionId}
              actionResult={tenantApiKeyActionResult}
              onCreateApiKey={handleCreateTenantApiKey}
              onRevokeApiKey={handleRevokeTenantApiKey}
              onDismissCreatedApiKey={() => setCreatedTenantApiKey(null)}
              onRefresh={handleRefreshTenantApiKeys}
            />
          </>
        ) : null}
      </div>
    )
  }

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>克隆 Bot 概览</CardTitle>
          <CardDescription>
            {isTenantWorkspace ? currentWorkspace.title : "先选择一个克隆 Bot 工作区。"}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {!isTenantWorkspace ? (
            <StatusBlock title="未选择克隆 Bot" detail="请从顶部工作区选择器切换到店铺工作区。" />
          ) : null}
          {isTenantWorkspace && isLoading ? (
            <StatusBlock title="正在加载概览" detail="正在读取商品、订单、支付、订阅和财务摘要。" />
          ) : null}
          {isTenantWorkspace && errorMessage ? (
            <div className="flex flex-col gap-3 rounded-md border p-3">
              <div className="min-w-0">
                <p className="text-sm font-medium">概览加载失败</p>
                <p className="mt-1 text-xs text-muted-foreground">{errorMessage}</p>
              </div>
              <Button variant="outline" className="w-fit" onClick={loadTenantWorkspace}>
                重新加载
              </Button>
            </div>
          ) : null}
          {overview ? <CloneBotOverviewContent overview={overview} /> : null}
          {storeSettings ? (
            <CloneBotStoreSettingsForm
              settings={storeSettings}
              actionId={storeSettingsActionId}
              actionResult={storeSettingsActionResult}
              onUpdateStoreSettings={handleUpdateStoreSettings}
            />
          ) : null}
          {paymentConfigs ? (
            <CloneBotPaymentSettingsPanel
              configs={paymentConfigs.providers}
              actionId={paymentActionId}
              actionResult={paymentActionResult}
              onUpdatePaymentConfig={handleUpdatePaymentConfig}
              onDisablePaymentConfig={handleDisablePaymentConfig}
            />
          ) : null}
          {products && orders ? (
            <CloneBotRecentLists
              products={products}
              orders={orders}
              productFilters={productFilters}
              orderFilters={orderFilters}
              isRefreshing={isLoading}
              actionId={supplyActionId}
              actionResult={supplyActionResult}
              selectedOrderDiagnostics={selectedOrderDiagnostics}
              orderDiagnosticsActionId={orderDiagnosticsActionId}
              orderDiagnosticsError={orderDiagnosticsError}
              orderObservability={orderObservability}
              orderObservabilityLoading={orderObservabilityLoading}
              orderObservabilityError={orderObservabilityError}
              orderObservabilityOutTradeNo={orderObservabilityOutTradeNo}
              onCreateProduct={handleCreateProduct}
              onUpdateProductMetadata={handleUpdateProductMetadata}
              onUpdateProductSales={handleUpdateProductSales}
              onBatchUpdateProductStatus={handleBatchUpdateProductStatus}
              onImportProductInventory={handleImportProductInventory}
              onUploadProductDeliveryFile={handleUploadProductDeliveryFile}
              onLoadOrderDiagnostics={handleLoadOrderDiagnostics}
              onLoadOrderObservabilityForOrder={handleLoadOrderObservabilityForOrder}
              onApplyProductFilters={handleApplyProductFilters}
              onApplyOrderFilters={handleApplyOrderFilters}
              onProductPageChange={handleProductPageChange}
              onOrderPageChange={handleOrderPageChange}
              onRefreshOrderObservability={loadTenantOrderObservability}
              onClearOrderObservabilityScope={handleClearOrderObservabilityScope}
              onRefresh={loadTenantWorkspace}
            />
          ) : null}
          {supplyDashboard ? (
            <SupplyDashboardPanel
              dashboard={supplyDashboard}
              currentWorkspace={currentWorkspace}
              actionId={supplyActionId}
              actionResult={supplyActionResult}
              onSupplyApply={handleSupplyApply}
              onReviewSupplierApplication={handleReviewSupplierApplication}
              onCreateSupplierOffer={handleCreateSupplierOffer}
              onSetSupplierOfferApproval={handleSetSupplierOfferApproval}
              onSetSupplierRule={handleSetSupplierRule}
              onCreateResellerProduct={handleCreateResellerProduct}
              onUpdateResellerProductMetadata={handleUpdateResellerProductMetadata}
              onUpdateResellerProductSales={handleUpdateResellerProductSales}
              marketFilters={supplyMarketFilters}
              onApplyMarketFilters={handleApplySupplyMarketFilters}
              products={products?.items ?? []}
            />
          ) : null}
        </CardContent>
      </Card>
      <div className="flex flex-col gap-4">
        <CloneBotSubscriptionFinancePanel
          overview={overview}
          currentWorkspace={currentWorkspace}
          subscriptionDashboard={subscriptionDashboard}
          financeDashboard={financeDashboard}
          isRefreshing={isLoading || subscriptionFinanceLoading}
          errorMessage={subscriptionFinanceError}
          actionId={subscriptionActionId}
          actionResult={subscriptionActionResult}
          renewalOrder={subscriptionRenewalOrder}
          financeActionId={financeActionId}
          financeActionResult={financeActionResult}
          onCreateRenewalOrder={handleCreateSubscriptionRenewalOrder}
          onCreateWithdrawal={handleCreateWithdrawal}
          onRefresh={loadSubscriptionFinance}
        />
        <CloneBotReportExportJobsPanel
          currentWorkspace={currentWorkspace}
          jobs={tenantReportJobs}
          status={tenantReportJobStatus}
          reportType={tenantReportJobType}
          isRefreshing={tenantReportJobsLoading}
          errorMessage={tenantReportJobsError}
          actionId={tenantReportJobActionId}
          actionResult={tenantReportJobActionResult}
          onStatusChange={setTenantReportJobStatus}
          onReportTypeChange={setTenantReportJobType}
          onCreateReportJob={handleCreateReportExportJob}
          onDownloadReportJob={handleDownloadReportExportJob}
          onRefresh={loadTenantReportJobs}
        />
        <CloneBotApiKeysPanel
          currentWorkspace={currentWorkspace}
          apiKeys={tenantApiKeys}
          createdApiKey={createdTenantApiKey}
          isRefreshing={tenantApiKeysLoading}
          errorMessage={tenantApiKeysError}
          actionId={tenantApiKeyActionId}
          actionResult={tenantApiKeyActionResult}
          onCreateApiKey={handleCreateTenantApiKey}
          onRevokeApiKey={handleRevokeTenantApiKey}
          onDismissCreatedApiKey={() => setCreatedTenantApiKey(null)}
          onRefresh={handleRefreshTenantApiKeys}
        />
        <CloneBotPluginCapabilitiesPanel
          currentWorkspace={currentWorkspace}
          capabilities={businessPluginCapabilities}
          externalSourceConnections={externalSourceConnections}
          isRefreshing={businessPluginCapabilitiesLoading}
          errorMessage={businessPluginCapabilitiesError}
          connectionsRefreshing={externalSourceConnectionsLoading}
          connectionsErrorMessage={externalSourceConnectionsError}
          actionId={externalSourceActionId}
          actionResult={externalSourceActionResult}
          catalogProducts={externalSourceCatalogProducts}
          catalogProductsHandle={externalSourceCatalogProductsHandle}
          catalogProductsError={externalSourceCatalogProductsError}
          onRefresh={loadBusinessPluginCapabilities}
          onRefreshConnections={loadExternalSourceConnections}
          onCreateExternalSourceConnection={handleCreateExternalSourceConnection}
          onDisableExternalSourceConnection={handleDisableExternalSourceConnection}
          onSyncExternalSourceCatalog={handleSyncExternalSourceCatalog}
          onViewExternalSourceCatalogProducts={handleViewExternalSourceCatalogProducts}
        />
        <CloneBotRiskPanel
          currentWorkspace={currentWorkspace}
          dashboard={tenantRiskDashboard}
          status={tenantRiskStatus}
          isRefreshing={tenantRiskLoading}
          errorMessage={tenantRiskError}
          onStatusChange={setTenantRiskStatus}
          onRefresh={loadTenantRiskDashboard}
        />
        <CloneBotAuditLogsPanel
          currentWorkspace={currentWorkspace}
          auditLogs={tenantAuditLogs}
          isRefreshing={tenantAuditLogsLoading}
          errorMessage={tenantAuditLogsError}
          onRefresh={loadTenantAuditLogs}
        />
      </div>
    </div>
  )
}

function CloneBotSubscriptionFinancePanel({
  overview,
  currentWorkspace,
  subscriptionDashboard,
  financeDashboard,
  isRefreshing,
  errorMessage,
  actionId,
  actionResult,
  renewalOrder,
  financeActionId,
  financeActionResult,
  onCreateRenewalOrder,
  onCreateWithdrawal,
  onRefresh,
}: {
  overview: AdminWebTenantOverview | null
  currentWorkspace?: AdminWebWorkspace
  subscriptionDashboard: AdminWebTenantSubscriptionDashboard | null
  financeDashboard: AdminWebTenantFinanceDashboard | null
  isRefreshing: boolean
  errorMessage: string | null
  actionId: string | null
  actionResult: SupplyActionResult | null
  renewalOrder: AdminWebTenantSubscriptionRenewalOrder | null
  financeActionId: string | null
  financeActionResult: SupplyActionResult | null
  onCreateRenewalOrder: (payload: AdminWebCreateTenantSubscriptionRenewalOrderPayload) => void
  onCreateWithdrawal: (payload: AdminWebCreateTenantWithdrawalPayload) => void
  onRefresh: () => void
}) {
  const [renewalMonths, setRenewalMonths] = React.useState("1")
  const isTenantWorkspace = currentWorkspace?.kind === "tenant"
  const subscriptionStatus = subscriptionDashboard?.status ?? overview?.subscription.status ?? "-"
  const planName = subscriptionDashboard?.plan_name ?? subscriptionDashboard?.plan_code ?? overview?.subscription.plan_code ?? "-"
  const periodEndsAt =
    subscriptionDashboard?.current_period_ends_at ?? overview?.subscription.current_period_ends_at ?? null
  const balance = financeDashboard?.balance
  const audit = financeDashboard?.audit
  const currency = balance?.currency ?? overview?.finance.currency ?? "USDT"
  const availableBalance = balance?.available_balance ?? overview?.finance.available_balance ?? "0"
  const pendingBalance = balance?.pending_balance ?? overview?.finance.pending_balance ?? "0"
  const frozenBalance = balance?.frozen_balance ?? overview?.finance.frozen_balance ?? "0"
  const invoices = subscriptionDashboard?.invoices ?? []
  const withdrawals = financeDashboard?.withdrawals ?? []
  const pendingWithdrawalCount =
    financeDashboard?.withdrawals.filter((withdrawal) => withdrawal.status === "pending").length ??
    overview?.finance.pending_withdrawal_count ??
    0
  const isRenewing = actionId === "subscription:renewal-order"
  const isActionDisabled = actionId !== null || isRefreshing || !isTenantWorkspace

  function handleRenewalSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onCreateRenewalOrder({ months: Number(renewalMonths) })
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle>订阅与财务</CardTitle>
            <CardDescription>当前克隆 Bot 的订阅和账务摘要。</CardDescription>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Badge variant="secondary">
              {overview?.bot_status ?? (currentWorkspace ? workspaceStatusLabel(currentWorkspace) : "未选择")}
            </Badge>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={!isTenantWorkspace || isRefreshing}
              onClick={onRefresh}
            >
              <RefreshCwIcon data-icon="inline-start" />
              {isRefreshing ? "刷新中" : "刷新"}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {!isTenantWorkspace ? (
          <StatusBlock title="未选择克隆 Bot" detail="请从顶部工作区选择器切换到店铺工作区。" />
        ) : null}
        {isTenantWorkspace ? (
          <>
            {isRefreshing ? (
              <StatusBlock title="正在刷新订阅与财务" detail="正在读取订阅账单、余额和提现摘要。" />
            ) : null}
            {errorMessage ? (
              <SupplyActionNotice result={{ kind: "error", message: errorMessage }} />
            ) : null}
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-medium">订阅状态</p>
            <Badge variant="outline">{subscriptionStatus}</Badge>
          </div>
          <MetricLine label="套餐" value={planName} />
          <MetricLine label="月费" value={subscriptionDashboard?.monthly_price ? `${subscriptionDashboard.monthly_price} ${subscriptionDashboard.currency ?? ""}` : "-"} />
          <MetricLine label="周期结束" value={formatDateTime(periodEndsAt)} />
          <MetricLine label="最近账单" value={String(invoices.length)} />
        </div>
        {!subscriptionDashboard ? (
          <StatusBlock title="订阅明细未加载" detail="可刷新后查看最近账单和续费状态。" />
        ) : null}
        <form className="flex flex-col gap-3 rounded-md border p-3" onSubmit={handleRenewalSubmit}>
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-medium">续费下单</p>
            <Badge variant="outline">1-24 月</Badge>
          </div>
          {actionResult ? <SupplyActionNotice result={actionResult} /> : null}
          <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
            <Select value={renewalMonths} disabled={isActionDisabled} onValueChange={setRenewalMonths}>
              <SelectTrigger aria-label="续费月数">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectLabel>续费月数</SelectLabel>
                  {[1, 3, 6, 12, 24].map((months) => (
                    <SelectItem key={months} value={String(months)}>
                      {months} 个月
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            <Button type="submit" size="sm" disabled={isActionDisabled}>
              {isRenewing ? "正在创建" : "续费下单"}
            </Button>
          </div>
          {renewalOrder ? (
            <div className="flex flex-col gap-2 rounded-md border p-2">
              <div className="flex items-center justify-between gap-3">
                <span className="truncate text-sm font-medium">{renewalOrder.out_trade_no}</span>
                <Badge variant={renewalOrder.payment_available ? "secondary" : "outline"}>
                  {renewalOrder.payment_available ? "可支付" : "待配置"}
                </Badge>
              </div>
              <p className="text-xs text-muted-foreground">
                {renewalOrder.amount} {renewalOrder.currency} · {renewalOrder.months} 个月 · {formatDateTime(renewalOrder.expires_at)}
              </p>
              {renewalOrder.payment_url ? (
                <Button variant="outline" size="sm" className="w-fit" asChild>
                  <a href={renewalOrder.payment_url} target="_blank" rel="noreferrer">
                    打开支付页
                  </a>
                </Button>
              ) : null}
            </div>
          ) : null}
        </form>
        <Separator />
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-medium">财务余额</p>
            <Badge variant={audit?.is_balanced === false ? "destructive" : "outline"}>
              {audit?.is_balanced === false ? "需核对" : "已核对"}
            </Badge>
          </div>
          <MetricLine label="可提现" value={`${availableBalance} ${currency}`} />
          <MetricLine label="待入账" value={`${pendingBalance} ${currency}`} />
          <MetricLine label="冻结" value={`${frozenBalance} ${currency}`} />
          <MetricLine label="待提现" value={String(pendingWithdrawalCount)} />
        </div>
        {!financeDashboard ? (
          <StatusBlock title="财务明细未加载" detail="可刷新后查看余额核对和提现记录。" />
        ) : null}
        <WithdrawalCreateForm
          currency={currency}
          availableBalance={availableBalance}
          disabled={isRefreshing || !isTenantWorkspace}
          actionId={financeActionId}
          actionResult={financeActionResult}
          onCreateWithdrawal={onCreateWithdrawal}
        />
        {subscriptionDashboard ? (
          <div className="flex flex-col gap-2">
            <p className="text-sm font-medium">最近账单</p>
            {invoices.length > 0 ? (
              invoices.slice(0, 3).map((invoice) => (
                <div key={invoice.out_trade_no} className="rounded-md border p-2">
                  <div className="flex items-center justify-between gap-3">
                    <span className="truncate text-sm font-medium">{invoice.out_trade_no}</span>
                    <Badge variant="outline">{subscriptionInvoiceStatusLabel(invoice.status)}</Badge>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {invoice.amount} {invoice.currency} · {formatDateTime(invoice.created_at)}
                  </p>
                </div>
              ))
            ) : (
              <StatusBlock title="暂无账单" detail="当前克隆 Bot 还没有订阅账单记录。" />
            )}
          </div>
        ) : null}
        {financeDashboard ? (
          <div className="flex flex-col gap-2">
            <p className="text-sm font-medium">最近提现</p>
            {withdrawals.length > 0 ? (
              withdrawals.slice(0, 3).map((withdrawal, index) => (
                <div key={`${withdrawal.requested_at}:${index}`} className="rounded-md border p-2">
                  <div className="flex items-center justify-between gap-3">
                    <span className="truncate text-sm font-medium">
                      {withdrawal.amount} {withdrawal.currency}
                    </span>
                    <Badge variant="outline">{withdrawalStatusLabel(withdrawal.status)}</Badge>
                  </div>
                  <p className="mt-1 truncate text-xs text-muted-foreground">
                    {withdrawal.network} · {withdrawal.address_masked}
                  </p>
                </div>
              ))
            ) : (
              <StatusBlock title="暂无提现" detail="当前克隆 Bot 还没有提现申请记录。" />
            )}
          </div>
        ) : null}
          </>
        ) : null}
      </CardContent>
    </Card>
  )
}

function CloneBotReportExportJobsPanel({
  currentWorkspace,
  jobs,
  status,
  reportType,
  isRefreshing,
  errorMessage,
  actionId,
  actionResult,
  onStatusChange,
  onReportTypeChange,
  onCreateReportJob,
  onDownloadReportJob,
  onRefresh,
}: {
  currentWorkspace?: AdminWebWorkspace
  jobs: AdminWebTenantReportExportJobsResponse | null
  status: AdminWebTenantReportStatusFilter
  reportType: AdminWebTenantReportTypeFilter
  isRefreshing: boolean
  errorMessage: string | null
  actionId: string | null
  actionResult: SupplyActionResult | null
  onStatusChange: (status: AdminWebTenantReportStatusFilter) => void
  onReportTypeChange: (reportType: AdminWebTenantReportTypeFilter) => void
  onCreateReportJob: (payload: AdminWebCreateTenantReportExportJobPayload) => void
  onDownloadReportJob: (job: AdminWebTenantReportExportJob) => void
  onRefresh: () => void
}) {
  const [createType, setCreateType] = React.useState<AdminWebTenantReportType>("orders")
  const isTenantWorkspace = currentWorkspace?.kind === "tenant"
  const items = jobs?.export_jobs ?? []
  const isCreating = actionId === `report:create:${createType}`
  const isActionBusy = actionId !== null || isRefreshing || !isTenantWorkspace

  function handleCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onCreateReportJob({ report_type: createType })
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle>报表任务</CardTitle>
            <CardDescription>创建和查看当前克隆 Bot 的导出任务。</CardDescription>
          </div>
          <Badge variant="outline">{items.length}</Badge>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={reportType}
            disabled={!isTenantWorkspace || isRefreshing}
            onValueChange={(value) => onReportTypeChange(normalizeTenantReportTypeFilter(value))}
          >
            <SelectTrigger className="w-[132px]">
              <SelectValue placeholder="报表" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectLabel>报表类型</SelectLabel>
                <SelectItem value="all">全部报表</SelectItem>
                <SelectItem value="orders">{tenantReportTypeLabel("orders")}</SelectItem>
                <SelectItem value="payments">{tenantReportTypeLabel("payments")}</SelectItem>
                <SelectItem value="inventory">{tenantReportTypeLabel("inventory")}</SelectItem>
                <SelectItem value="ledger">{tenantReportTypeLabel("ledger")}</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
          <Select
            value={status}
            disabled={!isTenantWorkspace || isRefreshing}
            onValueChange={(value) => onStatusChange(normalizeTenantReportStatus(value))}
          >
            <SelectTrigger className="w-[132px]">
              <SelectValue placeholder="状态" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectLabel>任务状态</SelectLabel>
                <SelectItem value="all">全部状态</SelectItem>
                <SelectItem value="pending">待生成</SelectItem>
                <SelectItem value="running">生成中</SelectItem>
                <SelectItem value="completed">已完成</SelectItem>
                <SelectItem value="failed">失败</SelectItem>
                <SelectItem value="expired">已过期</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!isTenantWorkspace || isRefreshing}
            onClick={onRefresh}
          >
            <RefreshCwIcon data-icon="inline-start" />
            {isRefreshing ? "刷新中" : "刷新"}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {!isTenantWorkspace ? (
          <StatusBlock title="未选择克隆 Bot" detail="请从顶部工作区选择器切换到店铺工作区。" />
        ) : null}
        {isTenantWorkspace && isRefreshing && !jobs ? (
          <StatusBlock title="正在读取报表任务" detail="正在加载当前 Bot 最近导出任务。" />
        ) : null}
        {isTenantWorkspace && errorMessage ? (
          <SupplyActionNotice result={{ kind: "error", message: errorMessage }} />
        ) : null}
        {isTenantWorkspace && actionResult ? <SupplyActionNotice result={actionResult} /> : null}
        {isTenantWorkspace ? (
          <form className="flex flex-col gap-2 rounded-md border p-3" onSubmit={handleCreate}>
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-medium">创建报表</p>
              <Badge variant="outline">pending</Badge>
            </div>
            <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
              <Select
                value={createType}
                disabled={isActionBusy}
                onValueChange={(value) => setCreateType(normalizeTenantReportType(value))}
              >
                <SelectTrigger aria-label="创建报表类型">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectLabel>报表类型</SelectLabel>
                    <SelectItem value="orders">{tenantReportTypeLabel("orders")}</SelectItem>
                    <SelectItem value="payments">{tenantReportTypeLabel("payments")}</SelectItem>
                    <SelectItem value="inventory">{tenantReportTypeLabel("inventory")}</SelectItem>
                    <SelectItem value="ledger">{tenantReportTypeLabel("ledger")}</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
              <Button type="submit" size="sm" disabled={isActionBusy}>
                <PlusIcon data-icon="inline-start" />
                {isCreating ? "创建中" : "创建报表"}
              </Button>
            </div>
          </form>
        ) : null}
        {isTenantWorkspace && jobs && items.length === 0 ? (
          <StatusBlock title="暂无报表任务" detail="当前筛选下还没有导出任务。" />
        ) : null}
        {isTenantWorkspace && items.length > 0 ? (
          <div className="flex flex-col gap-2">
            {items.map((job) => (
              <TenantReportExportJobRow
                key={`${job.report_type}:${job.status}:${job.created_at}`}
                job={job}
                isBusy={actionId !== null}
                isDownloading={Boolean(job.download_handle && actionId === `report:download:${job.download_handle}`)}
                onDownload={onDownloadReportJob}
              />
            ))}
          </div>
        ) : null}
        {isTenantWorkspace && !jobs && !isRefreshing && !errorMessage ? (
          <StatusBlock title="报表任务未加载" detail="可刷新后查看最近导出任务。" />
        ) : null}
      </CardContent>
    </Card>
  )
}

function TenantReportExportJobRow({
  job,
  isBusy,
  isDownloading,
  onDownload,
}: {
  job: AdminWebTenantReportExportJob
  isBusy: boolean
  isDownloading: boolean
  onDownload: (job: AdminWebTenantReportExportJob) => void
}) {
  const canDownload = job.download_available && Boolean(job.download_handle)

  return (
    <div className="flex flex-col gap-3 rounded-md border p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{tenantReportTypeLabel(job.report_type)}</p>
          <p className="mt-1 truncate text-xs text-muted-foreground">
            {formatDateTime(job.created_at)} · {job.scope_type}
          </p>
        </div>
        <Badge variant={job.status === "failed" ? "destructive" : "outline"}>
          {tenantReportStatusLabel(job.status)}
        </Badge>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <MetricLine label="行数" value={String(job.row_count)} />
        <MetricLine label="下载" value={canDownload ? "可用" : "不可用"} />
        <MetricLine label="开始" value={formatDateTime(job.started_at)} />
        <MetricLine label="结束" value={formatDateTime(job.finished_at)} />
      </div>
      {job.failure_reason ? (
        <div className="flex flex-col gap-1">
          <p className="text-xs text-muted-foreground">失败原因</p>
          <p className="line-clamp-2 text-sm">{job.failure_reason}</p>
        </div>
      ) : null}
      {job.expires_at ? <MetricLine label="过期" value={formatDateTime(job.expires_at)} /> : null}
      {canDownload ? (
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="w-fit"
          disabled={isBusy}
          onClick={() => onDownload(job)}
        >
          <DownloadIcon data-icon="inline-start" />
          {isDownloading ? "下载中" : "下载报表"}
        </Button>
      ) : null}
    </div>
  )
}

function CloneBotApiKeysPanel({
  currentWorkspace,
  apiKeys,
  createdApiKey,
  isRefreshing,
  errorMessage,
  actionId,
  actionResult,
  onCreateApiKey,
  onRevokeApiKey,
  onDismissCreatedApiKey,
  onRefresh,
}: {
  currentWorkspace?: AdminWebWorkspace
  apiKeys: AdminWebTenantApiKeysResponse | null
  createdApiKey: AdminWebCreatedTenantApiKey | null
  isRefreshing: boolean
  errorMessage: string | null
  actionId: string | null
  actionResult: SupplyActionResult | null
  onCreateApiKey: (payload: AdminWebCreateTenantApiKeyPayload) => void
  onRevokeApiKey: (apiKey: AdminWebTenantApiKey) => void
  onDismissCreatedApiKey: () => void
  onRefresh: () => void
}) {
  const [name, setName] = React.useState("")
  const [scopePreset, setScopePreset] = React.useState<"readonly" | "full">("readonly")
  const [ipAllowlist, setIpAllowlist] = React.useState("")
  const isTenantWorkspace = currentWorkspace?.kind === "tenant"
  const keys = apiKeys?.keys ?? []
  const isCreating = actionId === "api-key:create"
  const isActionBusy = actionId !== null || isRefreshing || !isTenantWorkspace

  function handleCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const rules = ipAllowlist
      .split(/[\n,]+/)
      .map((rule) => rule.trim())
      .filter(Boolean)
    onCreateApiKey({
      name,
      scopes:
        scopePreset === "full"
          ? ["tenant_admin:*"]
          : [
              "audit_logs:read",
              "finance:read",
              "inventory:read",
              "orders:read",
              "payments:read",
              "products:read",
              "reports:read",
              "risk:read",
              "subscriptions:read",
              "supply:read",
            ],
      ip_allowlist: rules.length > 0 ? rules : undefined,
    })
  }

  async function handleCopyPlainKey() {
    if (!createdApiKey) {
      return
    }
    try {
      await navigator.clipboard.writeText(createdApiKey.plain_key)
    } catch {
      return
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle>API Key</CardTitle>
            <CardDescription>管理当前克隆 Bot 的 Tenant Admin API 凭据。</CardDescription>
          </div>
          <Badge variant="outline">{keys.length}</Badge>
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="w-fit"
          disabled={!isTenantWorkspace || isRefreshing}
          onClick={onRefresh}
        >
          <RefreshCwIcon data-icon="inline-start" />
          {isRefreshing ? "刷新中" : "刷新"}
        </Button>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {!isTenantWorkspace ? (
          <StatusBlock title="未选择克隆 Bot" detail="请从顶部工作区选择器切换到店铺工作区。" />
        ) : null}
        {isTenantWorkspace && isRefreshing && !apiKeys ? (
          <StatusBlock title="正在读取 API Key" detail="正在加载当前 Bot 的凭据摘要。" />
        ) : null}
        {isTenantWorkspace && errorMessage ? (
          <SupplyActionNotice result={{ kind: "error", message: errorMessage }} />
        ) : null}
        {isTenantWorkspace ? (
          <form className="flex flex-col gap-2 rounded-md border p-3" onSubmit={handleCreate}>
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-medium">创建凭据</p>
              <KeyRoundIcon className="size-4 text-muted-foreground" aria-hidden="true" />
            </div>
            {actionResult ? <SupplyActionNotice result={actionResult} /> : null}
            <Input
              value={name}
              maxLength={128}
              aria-label="API Key 名称"
              placeholder="例如：报表只读集成"
              disabled={isActionBusy}
              onChange={(event) => setName(event.target.value)}
            />
            <Select
              value={scopePreset}
              disabled={isActionBusy}
              onValueChange={(value) => setScopePreset(value === "full" ? "full" : "readonly")}
            >
              <SelectTrigger aria-label="API Key 权限预设">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectLabel>权限预设</SelectLabel>
                  <SelectItem value="readonly">只读观测</SelectItem>
                  <SelectItem value="full">完整租户管理</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
            <Input
              value={ipAllowlist}
              maxLength={512}
              aria-label="API Key IP 白名单"
              placeholder="可选，例如 203.0.113.10, 198.51.100.0/24"
              disabled={isActionBusy}
              onChange={(event) => setIpAllowlist(event.target.value)}
            />
            <Button type="submit" size="sm" disabled={isActionBusy || !name.trim()}>
              <PlusIcon data-icon="inline-start" />
              {isCreating ? "创建中" : "创建 API Key"}
            </Button>
          </form>
        ) : null}
        {createdApiKey ? (
          <div className="flex flex-col gap-2 rounded-md border p-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm font-medium">仅显示一次</p>
                <p className="mt-1 text-xs text-muted-foreground">刷新或关闭后无法再次查看明文 Key。</p>
              </div>
              <Badge variant="secondary">新建</Badge>
            </div>
            <Input readOnly value={createdApiKey.plain_key} aria-label="新创建的 API Key 明文" />
            <div className="flex flex-wrap gap-2">
              <Button type="button" size="sm" variant="outline" onClick={handleCopyPlainKey}>
                <CopyIcon data-icon="inline-start" />
                复制
              </Button>
              <Button type="button" size="sm" variant="ghost" onClick={onDismissCreatedApiKey}>
                已保存
              </Button>
            </div>
          </div>
        ) : null}
        {isTenantWorkspace && apiKeys && keys.length === 0 ? (
          <StatusBlock title="暂无 API Key" detail="当前克隆 Bot 还没有可用凭据。" />
        ) : null}
        {isTenantWorkspace && keys.length > 0 ? (
          <div className="flex flex-col gap-2">
            {keys.map((apiKey) => (
              <TenantApiKeyRow
                key={apiKey.credential_handle}
                apiKey={apiKey}
                isRevoking={actionId === `api-key:revoke:${apiKey.credential_handle}`}
                actionBusy={isActionBusy}
                onRevoke={onRevokeApiKey}
              />
            ))}
          </div>
        ) : null}
        {isTenantWorkspace && !apiKeys && !isRefreshing && !errorMessage ? (
          <StatusBlock title="API Key 未加载" detail="可刷新后查看当前 Bot 的凭据摘要。" />
        ) : null}
      </CardContent>
    </Card>
  )
}

function TenantApiKeyRow({
  apiKey,
  isRevoking,
  actionBusy,
  onRevoke,
}: {
  apiKey: AdminWebTenantApiKey
  isRevoking: boolean
  actionBusy: boolean
  onRevoke: (apiKey: AdminWebTenantApiKey) => void
}) {
  return (
    <div className="flex flex-col gap-3 rounded-md border p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{apiKey.name}</p>
          <p className="mt-1 truncate text-xs text-muted-foreground">{apiKey.key_prefix}...</p>
        </div>
        <Badge variant={apiKey.status === "active" ? "secondary" : "outline"}>
          {apiKey.status === "active" ? "可用" : "已吊销"}
        </Badge>
      </div>
      <div className="grid gap-2">
        <MetricLine label="权限" value={apiKey.scopes.includes("tenant_admin:*") ? "完整租户管理" : `${apiKey.scopes.length} 项只读`} />
        <MetricLine label="IP 白名单" value={apiKey.ip_allowlist.length > 0 ? `${apiKey.ip_allowlist.length} 条` : "不限制"} />
        <MetricLine label="创建" value={formatDateTime(apiKey.created_at)} />
        <MetricLine label="最近使用" value={formatDateTime(apiKey.last_used_at)} />
      </div>
      {apiKey.status === "active" ? (
        <Button
          type="button"
          size="sm"
          variant="destructive"
          disabled={actionBusy}
          onClick={() => onRevoke(apiKey)}
        >
          <Trash2Icon data-icon="inline-start" />
          {isRevoking ? "吊销中" : "吊销"}
        </Button>
      ) : null}
    </div>
  )
}

function CloneBotPluginCapabilitiesPanel({
  currentWorkspace,
  capabilities,
  externalSourceConnections,
  isRefreshing,
  errorMessage,
  connectionsRefreshing,
  connectionsErrorMessage,
  actionId,
  actionResult,
  catalogProducts,
  catalogProductsHandle,
  catalogProductsError,
  onRefresh,
  onRefreshConnections,
  onCreateExternalSourceConnection,
  onDisableExternalSourceConnection,
  onSyncExternalSourceCatalog,
  onViewExternalSourceCatalogProducts,
}: {
  currentWorkspace?: AdminWebWorkspace
  capabilities: AdminWebBusinessPluginCapabilitiesResponse | null
  externalSourceConnections: AdminWebExternalSourceConnectionsResponse | null
  isRefreshing: boolean
  errorMessage: string | null
  connectionsRefreshing: boolean
  connectionsErrorMessage: string | null
  actionId: string | null
  actionResult: SupplyActionResult | null
  catalogProducts: AdminWebExternalSourceCatalogProductsResponse | null
  catalogProductsHandle: string | null
  catalogProductsError: string | null
  onRefresh: () => void
  onRefreshConnections: () => void
  onCreateExternalSourceConnection: (payload: AdminWebCreateExternalSourceConnectionPayload) => Promise<boolean>
  onDisableExternalSourceConnection: (connection: AdminWebExternalSourceConnection) => void
  onSyncExternalSourceCatalog: (connection: AdminWebExternalSourceConnection) => void
  onViewExternalSourceCatalogProducts: (connection: AdminWebExternalSourceConnection) => void
}) {
  const isTenantWorkspace = currentWorkspace?.kind === "tenant"
  const plugins = capabilities?.plugins ?? []
  const paymentPlugins = plugins.filter((plugin) => plugin.kind === "payment")
  const externalSourcePlugins = plugins.filter((plugin) => plugin.kind === "external_source")
  const verifiedCount = plugins.filter((plugin) => plugin.production_ready && plugin.staging_verified).length

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle>插件能力</CardTitle>
            <CardDescription>当前工作区可观测的支付、外部货源和扩展能力摘要。</CardDescription>
          </div>
          <Badge variant="outline">{plugins.length}</Badge>
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="w-fit"
          disabled={!isTenantWorkspace || isRefreshing}
          onClick={onRefresh}
        >
          <RefreshCwIcon data-icon="inline-start" />
          {isRefreshing ? "刷新中" : "刷新"}
        </Button>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {!isTenantWorkspace ? (
          <StatusBlock title="未选择克隆 Bot" detail="请从顶部工作区选择器切换到店铺工作区。" />
        ) : null}
        {isTenantWorkspace && isRefreshing && !capabilities ? (
          <StatusBlock title="正在加载插件能力" detail="正在读取当前工作区的静态插件摘要。" />
        ) : null}
        {isTenantWorkspace && errorMessage ? (
          <SupplyActionNotice result={{ kind: "error", message: errorMessage }} />
        ) : null}
        {isTenantWorkspace && capabilities ? (
          <>
            <div className="grid gap-2">
              <MetricLine label="支付插件" value={String(paymentPlugins.length)} />
              <MetricLine label="外部货源" value={String(externalSourcePlugins.length)} />
              <MetricLine label="生产验证" value={`${verifiedCount}/${plugins.length}`} />
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge variant={capabilities.dynamic_loading_enabled ? "secondary" : "outline"}>
                动态加载 {capabilities.dynamic_loading_enabled ? "开启" : "关闭"}
              </Badge>
              <Badge variant={capabilities.remote_code_enabled ? "secondary" : "outline"}>
                远程代码 {capabilities.remote_code_enabled ? "开启" : "关闭"}
              </Badge>
              <Badge variant={capabilities.real_external_integration_enabled ? "secondary" : "outline"}>
                真实联调 {capabilities.real_external_integration_enabled ? "开启" : "关闭"}
              </Badge>
            </div>
            <Separator />
            {externalSourcePlugins.length > 0 ? (
              <div className="flex flex-col gap-2">
                {externalSourcePlugins.map((plugin) => (
                  <PluginCapabilityRow key={plugin.plugin_id} plugin={plugin} />
                ))}
              </div>
            ) : (
              <StatusBlock title="暂无外部货源插件" detail="当前环境没有注册可展示的外部货源插件。" />
            )}
            <ExternalSourceConnectionsManager
              connections={externalSourceConnections}
              isRefreshing={connectionsRefreshing}
              errorMessage={connectionsErrorMessage}
              actionId={actionId}
              actionResult={actionResult}
              catalogProducts={catalogProducts}
              catalogProductsHandle={catalogProductsHandle}
              catalogProductsError={catalogProductsError}
              onRefresh={onRefreshConnections}
              onCreate={onCreateExternalSourceConnection}
              onDisable={onDisableExternalSourceConnection}
              onSyncCatalog={onSyncExternalSourceCatalog}
              onViewCatalogProducts={onViewExternalSourceCatalogProducts}
            />
            {paymentPlugins.length > 0 ? (
              <div className="flex flex-col gap-2">
                {paymentPlugins.map((plugin) => (
                  <PluginCapabilityRow key={plugin.plugin_id} plugin={plugin} compact />
                ))}
              </div>
            ) : null}
          </>
        ) : null}
        {isTenantWorkspace && !capabilities && !isRefreshing && !errorMessage ? (
          <StatusBlock title="插件能力未加载" detail="可刷新后查看当前工作区的插件能力摘要。" />
        ) : null}
      </CardContent>
    </Card>
  )
}

function ExternalSourceConnectionsManager({
  connections,
  isRefreshing,
  errorMessage,
  actionId,
  actionResult,
  catalogProducts,
  catalogProductsHandle,
  catalogProductsError,
  onRefresh,
  onCreate,
  onDisable,
  onSyncCatalog,
  onViewCatalogProducts,
}: {
  connections: AdminWebExternalSourceConnectionsResponse | null
  isRefreshing: boolean
  errorMessage: string | null
  actionId: string | null
  actionResult: SupplyActionResult | null
  catalogProducts: AdminWebExternalSourceCatalogProductsResponse | null
  catalogProductsHandle: string | null
  catalogProductsError: string | null
  onRefresh: () => void
  onCreate: (payload: AdminWebCreateExternalSourceConnectionPayload) => Promise<boolean>
  onDisable: (connection: AdminWebExternalSourceConnection) => void
  onSyncCatalog: (connection: AdminWebExternalSourceConnection) => void
  onViewCatalogProducts: (connection: AdminWebExternalSourceConnection) => void
}) {
  const providers = connections?.providers ?? []
  const activeCount = connections?.connections.filter((connection) => connection.status === "active").length ?? 0
  const catalogSyncProviderNames = new Set(
    providers.filter((provider) => provider.catalog_sync_available).map((provider) => provider.provider_name),
  )

  return (
    <div className="flex flex-col gap-3 rounded-md border p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium">外部源连接</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {connections ? `${activeCount}/${connections.connections.length} 个连接可用` : "连接摘要未加载"}
          </p>
        </div>
        <Button type="button" size="sm" variant="outline" disabled={isRefreshing} onClick={onRefresh}>
          <RefreshCwIcon data-icon="inline-start" />
          {isRefreshing ? "刷新中" : "刷新连接"}
        </Button>
      </div>
      {errorMessage ? <SupplyActionNotice result={{ kind: "error", message: errorMessage }} /> : null}
      {actionResult ? <SupplyActionNotice result={actionResult} /> : null}
      {isRefreshing && !connections ? (
        <StatusBlock title="正在读取外部源连接" detail="正在加载当前 Bot 的外部源连接摘要。" />
      ) : null}
      {connections ? (
        <>
          <ExternalSourceConnectionCreateForm
            providers={providers}
            isBusy={actionId !== null}
            isSubmitting={actionId === "external-source:create"}
            onCreate={onCreate}
          />
          {connections.connections.length > 0 ? (
            <div className="flex flex-col gap-2">
              {connections.connections.map((connection) => (
                <ExternalSourceConnectionRow
                  key={connection.connection_handle}
                  connection={connection}
                  isBusy={actionId !== null}
                  isDisabling={actionId === `external-source:disable:${connection.connection_handle}`}
                  isSyncingCatalog={actionId === `external-source:sync-catalog:${connection.connection_handle}`}
                  isLoadingCatalogProducts={actionId === `external-source:catalog-products:${connection.connection_handle}`}
                  catalogProducts={
                    catalogProducts?.connection_handle === connection.connection_handle ? catalogProducts : null
                  }
                  catalogProductsError={
                    catalogProductsHandle === connection.connection_handle ? catalogProductsError : null
                  }
                  canSyncCatalog={catalogSyncProviderNames.has(connection.provider_name)}
                  onDisable={onDisable}
                  onSyncCatalog={onSyncCatalog}
                  onViewCatalogProducts={onViewCatalogProducts}
                />
              ))}
            </div>
          ) : (
            <StatusBlock title="暂无外部源连接" detail="当前克隆 Bot 还没有保存外部货源连接。" />
          )}
        </>
      ) : null}
      {!connections && !isRefreshing && !errorMessage ? (
        <StatusBlock title="连接摘要未加载" detail="可刷新后查看当前 Bot 的外部源连接。" />
      ) : null}
    </div>
  )
}

function ExternalSourceConnectionCreateForm({
  providers,
  isBusy,
  isSubmitting,
  onCreate,
}: {
  providers: AdminWebExternalSourceConnectionsResponse["providers"]
  isBusy: boolean
  isSubmitting: boolean
  onCreate: (payload: AdminWebCreateExternalSourceConnectionPayload) => Promise<boolean>
}) {
  const [providerName, setProviderName] = React.useState("")
  const [sourceKey, setSourceKey] = React.useState("")
  const [displayName, setDisplayName] = React.useState("")
  const [credentialText, setCredentialText] = React.useState("")
  const [localError, setLocalError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (providers.length === 0) {
      setProviderName("")
      return
    }
    if (!providerName || !providers.some((provider) => provider.provider_name === providerName)) {
      setProviderName(providers[0].provider_name)
    }
  }, [providerName, providers])

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setLocalError(null)
    let credentials: Record<string, string>
    try {
      credentials = parseExternalSourceCredentials(credentialText)
    } catch (error) {
      setLocalError(errorToMessage(error))
      return
    }

    const created = await onCreate({
      provider_name: providerName,
      source_key: sourceKey,
      display_name: displayName,
      credentials,
    })
    if (created) {
      setSourceKey("")
      setDisplayName("")
      setCredentialText("")
    }
  }

  return (
    <form className="flex flex-col gap-2" onSubmit={handleSubmit}>
      <div className="grid gap-2 sm:grid-cols-3">
        <Select value={providerName} disabled={isBusy || providers.length === 0} onValueChange={setProviderName}>
          <SelectTrigger aria-label="外部源插件">
            <SelectValue placeholder="选择插件" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectLabel>外部源插件</SelectLabel>
              {providers.map((provider) => (
                <SelectItem key={provider.provider_name} value={provider.provider_name}>
                  {provider.provider_name}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <Input
          value={sourceKey}
          aria-label="来源标识"
          placeholder="来源标识"
          maxLength={128}
          disabled={isBusy}
          onChange={(event) => setSourceKey(event.target.value)}
        />
        <Input
          value={displayName}
          aria-label="连接名称"
          placeholder="连接名称"
          maxLength={128}
          disabled={isBusy}
          onChange={(event) => setDisplayName(event.target.value)}
        />
      </div>
      <textarea
        value={credentialText}
        aria-label="外部源凭据"
        placeholder={'每行 key=value，或 JSON 对象，例如 {"base_url":"https://example.test"}'}
        disabled={isBusy}
        className="min-h-24 resize-y rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm outline-none placeholder:text-muted-foreground focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
        onChange={(event) => setCredentialText(event.target.value)}
      />
      {localError ? <SupplyActionNotice result={{ kind: "error", message: localError }} /> : null}
      <Button
        type="submit"
        size="sm"
        variant="outline"
        className="w-fit"
        disabled={isBusy || providers.length === 0 || credentialText.trim() === ""}
      >
        <PlusIcon data-icon="inline-start" />
        {isSubmitting ? "创建中" : "创建连接"}
      </Button>
    </form>
  )
}

function ExternalSourceConnectionRow({
  connection,
  isBusy,
  isDisabling,
  isSyncingCatalog,
  isLoadingCatalogProducts,
  catalogProducts,
  catalogProductsError,
  canSyncCatalog,
  onDisable,
  onSyncCatalog,
  onViewCatalogProducts,
}: {
  connection: AdminWebExternalSourceConnection
  isBusy: boolean
  isDisabling: boolean
  isSyncingCatalog: boolean
  isLoadingCatalogProducts: boolean
  catalogProducts: AdminWebExternalSourceCatalogProductsResponse | null
  catalogProductsError: string | null
  canSyncCatalog: boolean
  onDisable: (connection: AdminWebExternalSourceConnection) => void
  onSyncCatalog: (connection: AdminWebExternalSourceConnection) => void
  onViewCatalogProducts: (connection: AdminWebExternalSourceConnection) => void
}) {
  const isActive = connection.status === "active"

  return (
    <div className="flex flex-col gap-3 rounded-md border p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{connection.display_name}</p>
          <p className="mt-1 truncate text-xs text-muted-foreground">
            {connection.provider_name} · {connection.source_key || "默认源"}
          </p>
        </div>
        <Badge variant={isActive ? "secondary" : "outline"}>{externalSourceStatusLabel(connection.status)}</Badge>
      </div>
      <div className="grid gap-2">
        <MetricLine label="凭据字段" value={String(connection.credential_field_count)} />
        <MetricLine label="创建" value={formatDateTime(connection.created_at)} />
        <MetricLine label="最近使用" value={formatDateTime(connection.last_used_at)} />
      </div>
      {isActive ? (
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={isBusy}
            onClick={() => onViewCatalogProducts(connection)}
          >
            <ListTreeIcon data-icon="inline-start" />
            {isLoadingCatalogProducts ? "读取中" : "查看已同步商品"}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={isBusy || !canSyncCatalog}
            onClick={() => onSyncCatalog(connection)}
          >
            <RefreshCwIcon data-icon="inline-start" />
            {isSyncingCatalog ? "同步中" : "同步目录"}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="destructive"
            disabled={isBusy}
            onClick={() => onDisable(connection)}
          >
            <Trash2Icon data-icon="inline-start" />
            {isDisabling ? "停用中" : "停用连接"}
          </Button>
        </div>
      ) : null}
      {catalogProductsError ? <SupplyActionNotice result={{ kind: "error", message: catalogProductsError }} /> : null}
      {catalogProducts ? <ExternalSourceCatalogProductsList page={catalogProducts} /> : null}
    </div>
  )
}

function ExternalSourceCatalogProductsList({
  page,
}: {
  page: AdminWebExternalSourceCatalogProductsResponse
}) {
  return (
    <div className="flex flex-col gap-2 rounded-md bg-muted/40 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium">已同步商品</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {page.display_name} · 共 {page.total_count} 个
          </p>
        </div>
        <Badge variant="outline">{page.items.length}/{page.total_count}</Badge>
      </div>
      {page.items.length > 0 ? (
        <div className="flex flex-col gap-2">
          {page.items.map((item) => (
            <div key={item.product_id} className="rounded-md border bg-background p-2">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{item.name}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {item.category || "未分类"} · {deliveryTypeLabel(item.delivery_type)}
                  </p>
                </div>
                <Badge variant={item.status === "on" ? "secondary" : "outline"}>
                  {productStatusLabel(item.status)}
                </Badge>
              </div>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                <MetricLine label="售价" value={`${item.price} ${item.currency}`} />
                <MetricLine label="可用库存" value={String(item.available_count)} />
                <MetricLine label="更新" value={formatDateTime(item.updated_at)} />
              </div>
            </div>
          ))}
        </div>
      ) : (
        <StatusBlock title="暂无已同步商品" detail="可先同步目录，成功后这里会展示本地商品摘要。" />
      )}
    </div>
  )
}

function PluginCapabilityRow({
  plugin,
  compact = false,
}: {
  plugin: AdminWebBusinessPluginCapability
  compact?: boolean
}) {
  const enabledCapabilities = Object.entries(plugin.capabilities)
    .filter(([, enabled]) => enabled)
    .map(([capability]) => capability)
  const visibleCapabilities = compact ? enabledCapabilities.slice(0, 3) : enabledCapabilities.slice(0, 5)

  return (
    <div className="flex flex-col gap-2 rounded-md border p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{plugin.name}</p>
          <p className="mt-1 truncate text-xs text-muted-foreground">{plugin.contract_version}</p>
        </div>
        <Badge variant={plugin.workspace_enabled ? "secondary" : "outline"}>
          {plugin.workspace_enabled ? "已启用" : plugin.workspace_configured ? "已配置" : "未配置"}
        </Badge>
      </div>
      <div className="flex flex-wrap gap-2">
        <Badge variant={plugin.production_ready && plugin.staging_verified ? "secondary" : "outline"}>
          {plugin.production_ready && plugin.staging_verified ? "生产可用" : "未验证"}
        </Badge>
        {plugin.offline_only ? <Badge variant="outline">离线能力</Badge> : null}
        {plugin.requires_tenant_enablement ? <Badge variant="outline">需租户启用</Badge> : null}
      </div>
      {visibleCapabilities.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {visibleCapabilities.map((capability) => (
            <Badge key={capability} variant="outline">
              {formatPluginCapabilityName(capability)}
            </Badge>
          ))}
        </div>
      ) : null}
      {plugin.kind === "external_source" ? (
        <div className="grid gap-2">
          <MetricLine label="活动连接" value={String(plugin.active_connection_count)} />
          <MetricLine label="停用连接" value={String(plugin.disabled_connection_count)} />
        </div>
      ) : null}
    </div>
  )
}

function formatPluginCapabilityName(capability: string) {
  const labels: Record<string, string> = {
    auto_fulfillment_idempotent: "幂等自动履约",
    callback: "回调",
    catalog_context: "目录上下文",
    catalog_product: "单品目录",
    catalog_product_context: "单品上下文",
    catalog_sync: "目录同步",
    create_payment: "创建支付",
    delivery: "拉取发货",
    delivery_context: "发货上下文",
    order: "下单",
    order_context: "下单上下文",
    query_order: "查单",
    reconcile: "对账",
  }
  return labels[capability] ?? capability
}

function CloneBotRiskPanel({
  currentWorkspace,
  dashboard,
  status,
  isRefreshing,
  errorMessage,
  onStatusChange,
  onRefresh,
}: {
  currentWorkspace?: AdminWebWorkspace
  dashboard: AdminWebTenantRiskDashboard | null
  status: AdminWebTenantRiskStatusFilter
  isRefreshing: boolean
  errorMessage: string | null
  onStatusChange: (status: AdminWebTenantRiskStatusFilter) => void
  onRefresh: () => void
}) {
  const isTenantWorkspace = currentWorkspace?.kind === "tenant"
  const disputes = dashboard?.disputes ?? []
  const afterSales = dashboard?.after_sales ?? []
  const itemCount = disputes.length + afterSales.length

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle>风控与售后</CardTitle>
            <CardDescription>当前克隆 Bot 的争议和售后工单摘要。</CardDescription>
          </div>
          <Badge variant="outline">{itemCount}</Badge>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={status}
            disabled={!isTenantWorkspace || isRefreshing}
            onValueChange={(value) => onStatusChange(normalizeTenantRiskStatus(value))}
          >
            <SelectTrigger className="w-[132px]">
              <SelectValue placeholder="状态" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectLabel>状态</SelectLabel>
                <SelectItem value="open">待处理</SelectItem>
                <SelectItem value="reviewing">处理中</SelectItem>
                <SelectItem value="resolved">已解决</SelectItem>
                <SelectItem value="rejected">已拒绝</SelectItem>
                <SelectItem value="closed">已关闭</SelectItem>
                <SelectItem value="all">全部</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!isTenantWorkspace || isRefreshing}
            onClick={onRefresh}
          >
            <RefreshCwIcon data-icon="inline-start" />
            {isRefreshing ? "刷新中" : "刷新"}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {!isTenantWorkspace ? (
          <StatusBlock title="未选择克隆 Bot" detail="请从顶部工作区选择器切换到店铺工作区。" />
        ) : null}
        {isTenantWorkspace && isRefreshing && !dashboard ? (
          <StatusBlock title="正在读取风控事项" detail="正在加载当前 Bot 的争议和售后摘要。" />
        ) : null}
        {isTenantWorkspace && errorMessage ? (
          <SupplyActionNotice result={{ kind: "error", message: errorMessage }} />
        ) : null}
        {isTenantWorkspace && dashboard && itemCount === 0 ? (
          <StatusBlock title="暂无风控事项" detail="当前状态下没有争议或售后工单。" />
        ) : null}
        {isTenantWorkspace && disputes.length > 0 ? (
          <div className="flex flex-col gap-2">
            <p className="text-sm font-medium">争议</p>
            {disputes.map((item) => (
              <TenantRiskDisputeRow key={`dispute:${item.out_trade_no}:${item.updated_at}`} item={item} />
            ))}
          </div>
        ) : null}
        {isTenantWorkspace && afterSales.length > 0 ? (
          <div className="flex flex-col gap-2">
            <p className="text-sm font-medium">售后</p>
            {afterSales.map((item) => (
              <TenantRiskAfterSaleRow key={`after-sale:${item.out_trade_no}:${item.updated_at}`} item={item} />
            ))}
          </div>
        ) : null}
        {isTenantWorkspace && !dashboard && !isRefreshing && !errorMessage ? (
          <StatusBlock title="风控事项未加载" detail="可刷新后查看当前 Bot 的争议和售后摘要。" />
        ) : null}
      </CardContent>
    </Card>
  )
}

function TenantRiskDisputeRow({ item }: { item: AdminWebTenantRiskDispute }) {
  return (
    <div className="flex flex-col gap-3 rounded-md border p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{item.out_trade_no}</p>
          <p className="mt-1 truncate text-xs text-muted-foreground">
            买家 {item.buyer_telegram_user_id} · {sourceTypeLabel(item.source_type)} · {orderStatusLabel(item.order_status)}
          </p>
        </div>
        <Badge variant="outline">{riskStatusLabel(item.status)}</Badge>
      </div>
      <div className="grid gap-2">
        <MetricLine label="金额" value={`${item.amount} ${item.currency}`} />
        <MetricLine label="创建" value={formatDateTime(item.created_at)} />
      </div>
      <RiskTextBlock title="原因" value={item.reason} />
      <RiskTextBlock title="处理" value={item.resolution} />
    </div>
  )
}

function TenantRiskAfterSaleRow({ item }: { item: AdminWebTenantRiskAfterSale }) {
  return (
    <div className="flex flex-col gap-3 rounded-md border p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{item.out_trade_no}</p>
          <p className="mt-1 truncate text-xs text-muted-foreground">
            {afterSaleCaseTypeLabel(item.case_type)} · 买家 {item.buyer_telegram_user_id}
          </p>
        </div>
        <Badge variant="outline">{riskStatusLabel(item.status)}</Badge>
      </div>
      <div className="grid gap-2">
        <MetricLine label="订单金额" value={`${item.amount} ${item.currency}`} />
        <MetricLine label="申请金额" value={item.requested_amount ? `${item.requested_amount} ${item.currency}` : "-"} />
        <MetricLine label="已退金额" value={`${item.refunded_amount} ${item.currency}`} />
        <MetricLine label="更新" value={formatDateTime(item.updated_at)} />
      </div>
      <RiskTextBlock title="原因" value={item.reason} />
      <RiskTextBlock title="处理" value={item.resolution} />
    </div>
  )
}

function RiskTextBlock({ title, value }: { title: string; value?: string | null }) {
  return (
    <div className="flex flex-col gap-1">
      <p className="text-xs text-muted-foreground">{title}</p>
      <p className="line-clamp-2 text-sm">{value || "-"}</p>
    </div>
  )
}

function CloneBotAuditLogsPanel({
  currentWorkspace,
  auditLogs,
  isRefreshing,
  errorMessage,
  onRefresh,
}: {
  currentWorkspace?: AdminWebWorkspace
  auditLogs: AdminWebTenantAuditLogsResponse | null
  isRefreshing: boolean
  errorMessage: string | null
  onRefresh: () => void
}) {
  const isTenantWorkspace = currentWorkspace?.kind === "tenant"
  const items = auditLogs?.items ?? []

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle>操作审计</CardTitle>
            <CardDescription>当前克隆 Bot 最近管理操作记录。</CardDescription>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Badge variant="outline">{items.length}</Badge>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={!isTenantWorkspace || isRefreshing}
              onClick={onRefresh}
            >
              <RefreshCwIcon data-icon="inline-start" />
              {isRefreshing ? "刷新中" : "刷新"}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {!isTenantWorkspace ? (
          <StatusBlock title="未选择克隆 Bot" detail="请从顶部工作区选择器切换到店铺工作区。" />
        ) : null}
        {isTenantWorkspace && isRefreshing && !auditLogs ? (
          <StatusBlock title="正在读取审计日志" detail="正在加载当前 Bot 最近管理操作。" />
        ) : null}
        {isTenantWorkspace && errorMessage ? (
          <SupplyActionNotice result={{ kind: "error", message: errorMessage }} />
        ) : null}
        {isTenantWorkspace && auditLogs && items.length === 0 ? (
          <StatusBlock title="暂无审计日志" detail="当前克隆 Bot 还没有管理操作记录。" />
        ) : null}
        {isTenantWorkspace && auditLogs && items.length > 0
          ? items.map((item) => (
              <TenantAuditLogRow
                key={`${item.created_at}:${item.action}:${item.actor_telegram_user_id ?? "system"}`}
                item={item}
              />
            ))
          : null}
        {isTenantWorkspace && !auditLogs && !isRefreshing && !errorMessage ? (
          <StatusBlock title="审计日志未加载" detail="可刷新后查看当前 Bot 最近管理操作。" />
        ) : null}
      </CardContent>
    </Card>
  )
}

function TenantAuditLogRow({
  item,
}: {
  item: AdminWebTenantAuditLogsResponse["items"][number]
}) {
  const metadataEntries = Object.entries(item.metadata).slice(0, 4)

  return (
    <div className="flex flex-col gap-2 rounded-md border p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{item.action}</p>
          <p className="mt-1 truncate text-xs text-muted-foreground">
            {item.target_type ?? "通用"} · {auditActorLabel(item)}
          </p>
        </div>
        <Badge variant="outline">{formatDateTime(item.created_at)}</Badge>
      </div>
      {metadataEntries.length > 0 ? (
        <div className="flex flex-col gap-1">
          {metadataEntries.map(([key, value]) => (
            <p key={key} className="truncate text-xs text-muted-foreground">
              {key}: {formatAuditMetadataValue(value)}
            </p>
          ))}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">无附加摘要</p>
      )}
    </div>
  )
}

function CloneBotPaymentSettingsPanel({
  configs,
  actionId,
  actionResult,
  onUpdatePaymentConfig,
  onDisablePaymentConfig,
}: {
  configs: AdminWebTenantPaymentProviderConfig[]
  actionId: string | null
  actionResult: SupplyActionResult | null
  onUpdatePaymentConfig: (providerName: AdminWebPaymentProviderName, payload: AdminWebPaymentProviderConfigPayload) => void
  onDisablePaymentConfig: (providerName: AdminWebPaymentProviderName) => void
}) {
  const epusdtConfig = configs.find((config) => config.provider === "epusdt_gmpay")
  const epayConfig = configs.find((config) => config.provider === "epay_compatible")

  return (
    <div className="flex flex-col gap-3 rounded-md border p-3">
      <div className="flex flex-col gap-1">
        <p className="text-sm font-medium">支付设置</p>
        <p className="text-xs text-muted-foreground">
          仅开放 EPUSDT 和易支付兼容近期主通道；保存配置不会触发真实支付跳转、查单或回调联调。
        </p>
      </div>
      {actionResult ? <SupplyActionNotice result={actionResult} /> : null}
      <div className="grid gap-3 xl:grid-cols-2">
        {epusdtConfig ? (
          <PaymentConfigForm
            config={epusdtConfig}
            actionId={actionId}
            onUpdatePaymentConfig={onUpdatePaymentConfig}
            onDisablePaymentConfig={onDisablePaymentConfig}
          />
        ) : (
          <PaymentConfigUnavailableBlock displayName="EPUSDT" />
        )}
        {epayConfig ? (
          <PaymentConfigForm
            config={epayConfig}
            actionId={actionId}
            onUpdatePaymentConfig={onUpdatePaymentConfig}
            onDisablePaymentConfig={onDisablePaymentConfig}
          />
        ) : (
          <PaymentConfigUnavailableBlock displayName="易支付兼容" />
        )}
      </div>
    </div>
  )
}

function PaymentConfigUnavailableBlock({ displayName }: { displayName: string }) {
  return (
    <div className="flex flex-col gap-2 rounded-md border p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{displayName}</p>
          <p className="mt-1 text-xs text-muted-foreground">当前后台未返回该主线通道配置摘要。</p>
        </div>
        <Badge variant="outline">不可用</Badge>
      </div>
      <p className="text-xs text-muted-foreground">
        请先确认平台 payment provider 清单；页面不会展示或要求任何上游密钥明文。
      </p>
    </div>
  )
}

function WithdrawalCreateForm({
  currency,
  availableBalance,
  disabled,
  actionId,
  actionResult,
  onCreateWithdrawal,
}: {
  currency: string
  availableBalance: string
  disabled: boolean
  actionId: string | null
  actionResult: SupplyActionResult | null
  onCreateWithdrawal: (payload: AdminWebCreateTenantWithdrawalPayload) => void
}) {
  const [amount, setAmount] = React.useState("")
  const [network, setNetwork] = React.useState("TRC20")
  const [address, setAddress] = React.useState("")
  const isBusy = actionId !== null || disabled
  const isCreating = actionId === "finance:withdrawal:create"

  React.useEffect(() => {
    setAmount("")
    setAddress("")
  }, [currency])

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onCreateWithdrawal({
      amount,
      network,
      address,
      currency,
    })
  }

  React.useEffect(() => {
    if (actionResult?.kind === "success") {
      setAmount("")
      setAddress("")
    }
  }, [actionResult?.kind, actionResult?.message])

  return (
    <form className="flex flex-col gap-3 rounded-md border p-3" onSubmit={handleSubmit}>
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium">提现申请</p>
          <p className="mt-1 text-xs text-muted-foreground">可提现 {availableBalance} {currency}</p>
        </div>
        <Badge variant="outline">人工审核</Badge>
      </div>
      {actionResult ? <SupplyActionNotice result={actionResult} /> : null}
      <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_7rem]">
        <Input
          value={amount}
          inputMode="decimal"
          aria-label="提现金额"
          placeholder="提现金额"
          disabled={isBusy}
          onChange={(event) => setAmount(event.target.value)}
        />
        <Select value={network} disabled={isBusy} onValueChange={setNetwork}>
          <SelectTrigger aria-label="提现网络">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectLabel>提现网络</SelectLabel>
              <SelectItem value="TRC20">TRC20</SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>
      <Input
        value={address}
        aria-label="提现地址"
        placeholder="提现地址"
        disabled={isBusy}
        onChange={(event) => setAddress(event.target.value)}
      />
      <Button type="submit" size="sm" variant="outline" disabled={isBusy}>
        {isCreating ? "正在提交" : "提交提现"}
      </Button>
    </form>
  )
}

function PaymentConfigForm({
  config,
  actionId,
  onUpdatePaymentConfig,
  onDisablePaymentConfig,
}: {
  config: AdminWebTenantPaymentProviderConfig
  actionId: string | null
  onUpdatePaymentConfig: (providerName: AdminWebPaymentProviderName, payload: AdminWebPaymentProviderConfigPayload) => void
  onDisablePaymentConfig: (providerName: AdminWebPaymentProviderName) => void
}) {
  const isEpusdt = config.provider === "epusdt_gmpay"
  const [gatewayUrl, setGatewayUrl] = React.useState(config.gateway_url ?? "")
  const [merchantId, setMerchantId] = React.useState("")
  const [secret, setSecret] = React.useState("")
  const [token, setToken] = React.useState(config.asset ?? (isEpusdt ? "USDT" : ""))
  const [network, setNetwork] = React.useState(config.network ?? (isEpusdt ? "TRC20" : ""))
  const [paymentType, setPaymentType] = React.useState(config.payment_type ?? "alipay")
  const [device, setDevice] = React.useState(config.device ?? "mobile")
  const [subject, setSubject] = React.useState(config.subject ?? "FakaBot Order")
  const [returnUrl, setReturnUrl] = React.useState("")
  const updateActionId = `payment:update:${config.provider}`
  const disableActionId = `payment:disable:${config.provider}`
  const isBusy = actionId !== null
  const isUpdating = actionId === updateActionId
  const isDisabling = actionId === disableActionId

  React.useEffect(() => {
    setGatewayUrl(config.gateway_url ?? "")
    setMerchantId("")
    setSecret("")
    setToken(config.asset ?? (config.provider === "epusdt_gmpay" ? "USDT" : ""))
    setNetwork(config.network ?? (config.provider === "epusdt_gmpay" ? "TRC20" : ""))
    setPaymentType(config.payment_type ?? "alipay")
    setDevice(config.device ?? "mobile")
    setSubject(config.subject ?? "FakaBot Order")
    setReturnUrl("")
  }, [
    config.provider,
    config.gateway_url,
    config.asset,
    config.network,
    config.payment_type,
    config.device,
    config.subject,
    config.enabled,
  ])

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (isEpusdt) {
      onUpdatePaymentConfig(config.provider, {
        base_url: gatewayUrl,
        pid: merchantId,
        secret_key: secret,
        token,
        network,
      })
      return
    }
    onUpdatePaymentConfig(config.provider, {
      gateway_url: gatewayUrl,
      merchant_id: merchantId,
      key: secret,
      payment_type: paymentType,
      device,
      subject,
      return_url: returnUrl,
    })
  }

  return (
    <form className="flex flex-col gap-3 rounded-md border p-3" onSubmit={handleSubmit}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{config.display_name}</p>
          <p className="mt-1 truncate text-xs text-muted-foreground">
            {config.scope_type === "platform" ? "平台配置" : "当前 Bot 配置"} ·{" "}
            {config.key_configured ? "密钥已配置" : "密钥未配置"}
          </p>
        </div>
        <Badge variant={config.enabled ? "secondary" : "outline"}>{config.enabled ? "已启用" : "未启用"}</Badge>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <MetricLine label="商户" value={config.merchant_id_masked ?? "-"} />
        <MetricLine label="建链" value={config.create_payment_available ? "可用" : "不可用"} />
        <MetricLine label="作用域" value={config.scope_type === "platform" ? "平台继承" : "当前 Bot"} />
        <MetricLine label="密钥" value={config.key_configured ? "已配置" : "未配置"} />
      </div>
      <div className="flex flex-col gap-1 text-xs text-muted-foreground">
        {config.scope_type === "platform" ? (
          <p>当前继承平台配置；保存后会创建当前 Bot 配置，停用只适用于当前 Bot 配置。</p>
        ) : null}
        {config.key_configured ? (
          <p>密钥已保存但不会回显；再次保存此表单时仍需输入密钥以重写配置。</p>
        ) : (
          <p>密钥未配置，保存前需填写商户密钥。</p>
        )}
        {!config.create_payment_available ? (
          <p>建链不可用时，新订单会保留本地记录并返回泛化失败原因。</p>
        ) : null}
      </div>
      <Input
        value={gatewayUrl}
        aria-label={`${config.display_name} 网关地址`}
        placeholder={isEpusdt ? "EPUSDT 网关地址" : "易支付网关地址"}
        disabled={isBusy}
        onChange={(event) => setGatewayUrl(event.target.value)}
      />
      <Input
        value={merchantId}
        aria-label={`${config.display_name} 商户 ID`}
        placeholder={isEpusdt ? "商户 PID" : "商户 ID"}
        disabled={isBusy}
        onChange={(event) => setMerchantId(event.target.value)}
      />
      <Input
        value={secret}
        type="password"
        aria-label={`${config.display_name} 密钥`}
        placeholder={config.key_configured ? "输入新密钥后覆盖" : "密钥"}
        disabled={isBusy}
        onChange={(event) => setSecret(event.target.value)}
      />
      {isEpusdt ? (
        <div className="grid gap-2 sm:grid-cols-2">
          <Input
            value={token}
            aria-label="EPUSDT 资产"
            placeholder="USDT"
            disabled={isBusy}
            onChange={(event) => setToken(event.target.value)}
          />
          <Input
            value={network}
            aria-label="EPUSDT 网络"
            placeholder="TRC20"
            disabled={isBusy}
            onChange={(event) => setNetwork(event.target.value)}
          />
        </div>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          <Select value={paymentType} disabled={isBusy} onValueChange={setPaymentType}>
            <SelectTrigger aria-label="易支付支付类型">
              <SelectValue placeholder="支付类型" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectLabel>支付类型</SelectLabel>
                <SelectItem value="alipay">alipay</SelectItem>
                <SelectItem value="wxpay">wxpay</SelectItem>
                <SelectItem value="usdt">usdt</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
          <Input
            value={device}
            aria-label="易支付设备"
            placeholder="mobile"
            disabled={isBusy}
            onChange={(event) => setDevice(event.target.value)}
          />
          <Input
            value={subject}
            aria-label="易支付订单标题"
            placeholder="FakaBot Order"
            disabled={isBusy}
            onChange={(event) => setSubject(event.target.value)}
          />
          <Input
            value={returnUrl}
            aria-label="易支付返回地址"
            placeholder="返回地址"
            disabled={isBusy}
            onChange={(event) => setReturnUrl(event.target.value)}
          />
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" size="sm" disabled={isBusy}>
          {isUpdating ? "正在保存" : "保存配置"}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={isBusy || !config.enabled || config.scope_type !== "tenant"}
          onClick={() => onDisablePaymentConfig(config.provider)}
        >
          {isDisabling ? "正在停用" : "停用"}
        </Button>
      </div>
    </form>
  )
}

function SupplyDashboardPanel({
  dashboard,
  currentWorkspace,
  products,
  actionId,
  actionResult,
  onSupplyApply,
  onReviewSupplierApplication,
  onCreateSupplierOffer,
  onSetSupplierOfferApproval,
  onSetSupplierRule,
  onCreateResellerProduct,
  onUpdateResellerProductMetadata,
  onUpdateResellerProductSales,
  marketFilters,
  onApplyMarketFilters,
}: {
  dashboard: AdminWebSupplyDashboard
  currentWorkspace?: AdminWebWorkspace
  products: AdminWebTenantProduct[]
  actionId: string | null
  actionResult: SupplyActionResult | null
  onSupplyApply: (offer: AdminWebSupplyMarketOffer) => void
  onReviewSupplierApplication: (payload: AdminWebSupplierApplicationReviewPayload) => void
  onCreateSupplierOffer: (payload: AdminWebCreateSupplierOfferPayload) => void
  onSetSupplierOfferApproval: (supplierOfferId: number, payload: AdminWebSupplierOfferApprovalPayload) => void
  onSetSupplierRule: (payload: AdminWebSupplierRulePayload) => void
  onCreateResellerProduct: (payload: AdminWebCreateResellerProductPayload) => void
  onUpdateResellerProductMetadata: (
    resellerProductId: number,
    payload: AdminWebResellerProductMetadataPayload,
  ) => void
  onUpdateResellerProductSales: (
    resellerProductId: number,
    payload: AdminWebResellerProductSalesPayload,
  ) => void
  marketFilters: AdminWebSupplyDashboardFilters
  onApplyMarketFilters: (filters: AdminWebSupplyDashboardFilters) => void
}) {
  const supplierCount = dashboard.supplier_offers.length
  const pendingSupplierApplicationCount = dashboard.supplier_applications.filter(
    (application) => application.status === "pending",
  ).length
  const supplierApplications = React.useMemo(
    () =>
      [...dashboard.supplier_applications].sort((left, right) => {
        const leftRank = left.status === "pending" ? 0 : 1
        const rightRank = right.status === "pending" ? 0 : 1
        if (leftRank !== rightRank) {
          return leftRank - rightRank
        }
        return right.updated_at.localeCompare(left.updated_at)
      }),
    [dashboard.supplier_applications],
  )
  const marketCount = dashboard.market_offers.length
  const resellerApplicationCount = dashboard.reseller_applications.length
  const resellerProductCount = dashboard.reseller_products.length
  const supplierActionsDisabled = !dashboard.supplier_enabled
  const resellerActionsDisabled = !dashboard.reseller_enabled

  return (
    <div className="flex flex-col gap-3">
      {actionResult ? <SupplyActionNotice result={actionResult} /> : null}
      <div className="grid gap-3 xl:grid-cols-2">
        <PreviewPanel
          title="供应商工作台"
          totalCount={supplierCount + dashboard.supplier_applications.length + dashboard.supplier_rules.length}
          itemCount={Math.max(supplierCount, dashboard.supplier_applications.length, dashboard.supplier_rules.length)}
          emptyTitle="暂无供货数据"
          emptyDetail="当前 Bot 尚未开放供货商品或收到代理申请。"
          alwaysShowChildren
        >
          <div className="grid gap-2 sm:grid-cols-3">
            <MetricLine label="能力" value={dashboard.supplier_enabled ? "已开启" : "未开启"} />
            <MetricLine label="供货商品" value={String(supplierCount)} />
            <MetricLine label="待审申请" value={String(pendingSupplierApplicationCount)} />
          </div>
          {supplierActionsDisabled ? (
            <SupplyFeatureNotice
              title="供应商能力未开启"
              detail="当前仅展示供货安全摘要；创建供货、审批申请和独立规则编辑已禁用。"
            />
          ) : null}
          <SupplierOfferCreateForm
            products={products}
            actionId={actionId}
            disabled={supplierActionsDisabled}
            onCreateSupplierOffer={onCreateSupplierOffer}
          />
          {dashboard.supplier_offers.slice(0, 3).map((offer) => (
            <SupplierOfferPreviewRow
              key={offer.supplier_offer_id}
              offer={offer}
              actionId={actionId}
              disabled={supplierActionsDisabled}
              onSetApproval={onSetSupplierOfferApproval}
            />
          ))}
          {dashboard.supplier_rules.length > 0 ? (
            <SupplierRulesPreview
              rules={dashboard.supplier_rules}
              actionId={actionId}
              disabled={supplierActionsDisabled}
              onSetSupplierRule={onSetSupplierRule}
            />
          ) : null}
          <SupplierApplicationsPreview
            applications={supplierApplications}
            actionId={actionId}
            disabled={supplierActionsDisabled}
            onReview={onReviewSupplierApplication}
          />
        </PreviewPanel>
        <PreviewPanel
          title="代理商工作台"
          totalCount={marketCount + resellerApplicationCount + resellerProductCount}
          itemCount={1}
          emptyTitle="暂无代理数据"
          emptyDetail="当前 Bot 尚未选择可代理商品。"
        >
          <div className="grid gap-2 sm:grid-cols-4">
            <MetricLine label="能力" value={dashboard.reseller_enabled ? "已开启" : "未开启"} />
            <MetricLine label="可选商品" value={String(marketCount)} />
            <MetricLine label="我的申请" value={String(resellerApplicationCount)} />
            <MetricLine label="已代理" value={String(resellerProductCount)} />
          </div>
          {resellerActionsDisabled ? (
            <SupplyFeatureNotice
              title="代理商能力未开启"
              detail="供货市场筛选和安全摘要仍可查看；代理申请、上架和代理商品维护已禁用。"
            />
          ) : null}
          {currentWorkspace ? <ResellerTargetWorkspace workspace={currentWorkspace} /> : null}
          <ResellerMarketWorkbench
            offers={dashboard.market_offers}
            actionId={actionId}
            actionsDisabled={resellerActionsDisabled}
            filters={marketFilters}
            onSupplyApply={onSupplyApply}
            onCreateResellerProduct={onCreateResellerProduct}
            onApplyMarketFilters={onApplyMarketFilters}
          />
          {dashboard.reseller_applications.length > 0 ? (
            <ResellerApplicationsPreview applications={dashboard.reseller_applications} />
          ) : null}
          {dashboard.reseller_products.length > 0 ? (
            <ResellerProductsPreview
              products={dashboard.reseller_products}
              actionId={actionId}
              disabled={resellerActionsDisabled}
              onUpdateResellerProductMetadata={onUpdateResellerProductMetadata}
              onUpdateResellerProductSales={onUpdateResellerProductSales}
            />
          ) : null}
        </PreviewPanel>
      </div>
    </div>
  )
}

function SupplyFeatureNotice({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="rounded-md border bg-muted/30 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium">{title}</p>
          <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
        </div>
        <Badge variant="outline">只读</Badge>
      </div>
    </div>
  )
}

function SupplyActionNotice({ result }: { result: SupplyActionResult }) {
  return (
    <div
      className={cn(
        "rounded-md border p-3",
        result.kind === "error" ? "border-destructive/40" : "bg-accent/40",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium">
          {result.kind === "error" ? "操作失败" : "操作完成"}
        </p>
        <Badge variant={result.kind === "error" ? "destructive" : "secondary"}>
          {result.kind === "error" ? "错误" : "成功"}
        </Badge>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">{result.message}</p>
    </div>
  )
}

function ResellerTargetWorkspace({ workspace }: { workspace: AdminWebWorkspace }) {
  return (
    <div className="rounded-md border bg-muted/40 p-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <p className="text-sm font-medium">目标克隆 Bot</p>
          <p className="mt-1 truncate text-xs text-muted-foreground">
            {workspace.title}
          </p>
        </div>
        <Badge variant="secondary">
          {workspace.bot_username ? `@${workspace.bot_username}` : "当前工作区"}
        </Badge>
      </div>
    </div>
  )
}

function ResellerMarketWorkbench({
  offers,
  actionId,
  actionsDisabled,
  filters,
  onSupplyApply,
  onCreateResellerProduct,
  onApplyMarketFilters,
}: {
  offers: AdminWebSupplyMarketOffer[]
  actionId: string | null
  actionsDisabled: boolean
  filters: AdminWebSupplyDashboardFilters
  onSupplyApply: (offer: AdminWebSupplyMarketOffer) => void
  onCreateResellerProduct: (payload: AdminWebCreateResellerProductPayload) => void
  onApplyMarketFilters: (filters: AdminWebSupplyDashboardFilters) => void
}) {
  const [query, setQuery] = React.useState(filters.market_query ?? "")
  const [category, setCategory] = React.useState(filters.market_category ?? "")
  const [deliveryType, setDeliveryType] = React.useState<SupplyMarketDeliveryType>(
    filters.market_delivery_type ?? "all",
  )
  const [access, setAccess] = React.useState<SupplyMarketAccess>(filters.market_access ?? "all")
  const [minPrice, setMinPrice] = React.useState(filters.market_min_price ?? "")
  const [maxPrice, setMaxPrice] = React.useState(filters.market_max_price ?? "")
  const [stock, setStock] = React.useState<SupplyMarketStock>(filters.market_stock ?? "all")

  React.useEffect(() => {
    setQuery(filters.market_query ?? "")
    setCategory(filters.market_category ?? "")
    setDeliveryType(filters.market_delivery_type ?? "all")
    setAccess(filters.market_access ?? "all")
    setMinPrice(filters.market_min_price ?? "")
    setMaxPrice(filters.market_max_price ?? "")
    setStock(filters.market_stock ?? "all")
  }, [
    filters.market_access,
    filters.market_category,
    filters.market_delivery_type,
    filters.market_max_price,
    filters.market_min_price,
    filters.market_query,
    filters.market_stock,
  ])

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onApplyMarketFilters({
      market_query: query,
      market_category: category,
      market_delivery_type: deliveryType as AdminWebSupplyDashboardFilters["market_delivery_type"],
      market_access: access as AdminWebSupplyDashboardFilters["market_access"],
      market_min_price: minPrice,
      market_max_price: maxPrice,
      market_stock: stock as AdminWebSupplyDashboardFilters["market_stock"],
    })
  }

  function handleReset() {
    onApplyMarketFilters(defaultSupplyMarketFilters)
  }

  return (
    <div className="flex flex-col gap-3">
      <form className="flex flex-col gap-3 rounded-md border p-3" onSubmit={handleSubmit}>
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm font-medium">供货市场选品</p>
          <Badge variant="outline">{offers.length}</Badge>
        </div>
        <div className="grid gap-2 md:grid-cols-2">
          <Input
            value={query}
            aria-label="供货商品名称"
            placeholder="商品名称"
            onChange={(event) => setQuery(event.target.value)}
          />
          <Input
            value={category}
            aria-label="供货商品分类"
            placeholder="分类"
            onChange={(event) => setCategory(event.target.value)}
          />
        </div>
        <div className="grid gap-2 md:grid-cols-3">
          <Select
            value={deliveryType}
            onValueChange={(value) => setDeliveryType(value as SupplyMarketDeliveryType)}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectLabel>发货类型</SelectLabel>
                <SelectItem value="all">全部发货</SelectItem>
                <SelectItem value="card_pool">{deliveryTypeLabel("card_pool")}</SelectItem>
                <SelectItem value="card_fixed">{deliveryTypeLabel("card_fixed")}</SelectItem>
                <SelectItem value="file_download">{deliveryTypeLabel("file_download")}</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
          <Select
            value={access}
            onValueChange={(value) => setAccess(value as SupplyMarketAccess)}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectLabel>代理状态</SelectLabel>
                <SelectItem value="all">全部状态</SelectItem>
                <SelectItem value="ready">可上架</SelectItem>
                <SelectItem value="open">免审批</SelectItem>
                <SelectItem value="approval_required">需审批</SelectItem>
                <SelectItem value="pending">待审核</SelectItem>
                <SelectItem value="active">已通过</SelectItem>
                <SelectItem value="rejected">已拒绝</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
          <Select
            value={stock}
            onValueChange={(value) => setStock(value as SupplyMarketStock)}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectLabel>库存状态</SelectLabel>
                <SelectItem value="all">全部库存</SelectItem>
                <SelectItem value="available">有库存</SelectItem>
                <SelectItem value="empty">无库存</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>
        <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto]">
          <Input
            value={minPrice}
            inputMode="decimal"
            aria-label="最低售价下限"
            placeholder="最低价"
            onChange={(event) => setMinPrice(event.target.value)}
          />
          <Input
            value={maxPrice}
            inputMode="decimal"
            aria-label="最高售价上限"
            placeholder="最高价"
            onChange={(event) => setMaxPrice(event.target.value)}
          />
          <Button type="submit" size="sm">
            筛选
          </Button>
          <Button type="button" size="sm" variant="outline" onClick={handleReset}>
            重置
          </Button>
        </div>
      </form>
      {offers.length > 0 ? (
        offers.map((offer) => (
          <MarketOfferPreviewRow
            key={offer.supplier_offer_id}
            offer={offer}
            actionId={actionId}
            disabled={actionsDisabled}
            onSupplyApply={onSupplyApply}
            onCreateResellerProduct={onCreateResellerProduct}
          />
        ))
      ) : (
        <StatusBlock title="没有匹配商品" detail="请调整筛选条件或等待供应商开放更多商品。" />
      )}
    </div>
  )
}

function ResellerApplicationsPreview({
  applications,
}: {
  applications: AdminWebSupplyDashboard["reseller_applications"]
}) {
  return (
    <div className="flex flex-col gap-2">
      <Separator />
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium">我的代理申请</p>
        <Badge variant="outline">{applications.length}</Badge>
      </div>
      {applications.slice(0, 3).map((application) => (
        <div
          key={`${application.supplier_offer_id}:${application.status}:${application.updated_at}`}
          className="flex items-center justify-between gap-3 rounded-md border p-3"
        >
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{application.product_name}</p>
            <p className="mt-1 truncate text-xs text-muted-foreground">
              成本 {application.pricing_value} {application.currency}
            </p>
          </div>
          <Badge variant={application.status === "active" ? "secondary" : "outline"}>
            {resellerRuleStatusLabel(application.status)}
          </Badge>
        </div>
      ))}
    </div>
  )
}

function ResellerProductsPreview({
  products,
  actionId,
  disabled,
  onUpdateResellerProductMetadata,
  onUpdateResellerProductSales,
}: {
  products: AdminWebResellerProduct[]
  actionId: string | null
  disabled: boolean
  onUpdateResellerProductMetadata: (
    resellerProductId: number,
    payload: AdminWebResellerProductMetadataPayload,
  ) => void
  onUpdateResellerProductSales: (
    resellerProductId: number,
    payload: AdminWebResellerProductSalesPayload,
  ) => void
}) {
  return (
    <div className="flex flex-col gap-2">
      <Separator />
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium">已上架代理商品</p>
        <Badge variant="outline">{products.length}</Badge>
      </div>
      {products.slice(0, 3).map((product) => (
        <ResellerProductPreviewRow
          key={product.reseller_product_id}
          product={product}
          actionId={actionId}
          disabled={disabled}
          onUpdateResellerProductMetadata={onUpdateResellerProductMetadata}
          onUpdateResellerProductSales={onUpdateResellerProductSales}
        />
      ))}
    </div>
  )
}

function CloneBotRecentLists({
  products,
  orders,
  productFilters,
  orderFilters,
  isRefreshing,
  actionId,
  actionResult,
  selectedOrderDiagnostics,
  orderDiagnosticsActionId,
  orderDiagnosticsError,
  orderObservability,
  orderObservabilityLoading,
  orderObservabilityError,
  orderObservabilityOutTradeNo,
  onCreateProduct,
  onUpdateProductMetadata,
  onUpdateProductSales,
  onBatchUpdateProductStatus,
  onImportProductInventory,
  onUploadProductDeliveryFile,
  onLoadOrderDiagnostics,
  onLoadOrderObservabilityForOrder,
  onApplyProductFilters,
  onApplyOrderFilters,
  onProductPageChange,
  onOrderPageChange,
  onRefreshOrderObservability,
  onClearOrderObservabilityScope,
  onRefresh,
}: {
  products: AdminWebTenantProductsResponse
  orders: AdminWebTenantOrdersResponse
  productFilters: AdminWebTenantProductFilters
  orderFilters: AdminWebTenantOrderFilters
  isRefreshing: boolean
  actionId: string | null
  actionResult: SupplyActionResult | null
  selectedOrderDiagnostics: AdminWebTenantOrderDiagnostics | null
  orderDiagnosticsActionId: string | null
  orderDiagnosticsError: string | null
  orderObservability: AdminWebTenantOrderObservability | null
  orderObservabilityLoading: boolean
  orderObservabilityError: string | null
  orderObservabilityOutTradeNo: string | null
  onCreateProduct: (payload: AdminWebCreateProductPayload) => void
  onUpdateProductMetadata: (productId: number, payload: AdminWebProductMetadataPayload) => void
  onUpdateProductSales: (productId: number, payload: AdminWebProductSalesPayload) => void
  onBatchUpdateProductStatus: (payload: AdminWebProductBatchStatusPayload) => void
  onImportProductInventory: (productId: number, payload: AdminWebProductInventoryImportPayload) => Promise<boolean>
  onUploadProductDeliveryFile: (productId: number, file: File | null) => Promise<boolean>
  onLoadOrderDiagnostics: (order: AdminWebTenantOrder) => void
  onLoadOrderObservabilityForOrder: (order: AdminWebTenantOrder) => void
  onApplyProductFilters: (filters: AdminWebTenantProductFilters) => void
  onApplyOrderFilters: (filters: AdminWebTenantOrderFilters) => void
  onProductPageChange: (offset: number) => void
  onOrderPageChange: (offset: number) => void
  onRefreshOrderObservability: () => void
  onClearOrderObservabilityScope: () => void
  onRefresh: () => void
}) {
  const [selectedProductIds, setSelectedProductIds] = React.useState<number[]>([])
  const currentPageProductIds = React.useMemo(
    () => products.items.map((product) => product.product_id),
    [products.items],
  )
  const selectedCurrentPageProductIds = React.useMemo(
    () => selectedProductIds.filter((productId) => currentPageProductIds.includes(productId)),
    [currentPageProductIds, selectedProductIds],
  )
  const allCurrentPageSelected =
    currentPageProductIds.length > 0 && selectedCurrentPageProductIds.length === currentPageProductIds.length
  const bulkStatusAction = actionId?.startsWith("product:batch-status:") ? actionId : null

  React.useEffect(() => {
    setSelectedProductIds((current) =>
      current.filter((productId) => currentPageProductIds.includes(productId)),
    )
  }, [currentPageProductIds])

  function handleToggleAllCurrentPage(checked: boolean) {
    setSelectedProductIds(checked ? currentPageProductIds : [])
  }

  function handleToggleProduct(productId: number, checked: boolean) {
    setSelectedProductIds((current) => {
      if (checked) {
        return current.includes(productId) ? current : [...current, productId]
      }
      return current.filter((item) => item !== productId)
    })
  }

  function handleBatchStatus(status: "on" | "off") {
    const productCount = selectedCurrentPageProductIds.length
    if (productCount === 0) {
      return
    }
    const actionText = status === "on" ? "上架" : "下架"
    if (!window.confirm(`确认批量${actionText}当前页选中的 ${productCount} 个商品？`)) {
      return
    }
    onBatchUpdateProductStatus({
      product_ids: selectedCurrentPageProductIds,
      status,
    })
  }

  return (
    <div className="grid gap-3 xl:grid-cols-2">
      <PreviewPanel
        title="最近商品"
        totalCount={products.total_count}
        itemCount={products.items.length}
        emptyTitle="暂无商品"
        emptyDetail="当前 Bot 还没有可管理商品。"
        alwaysShowChildren
      >
        {actionResult ? <SupplyActionNotice result={actionResult} /> : null}
        <TenantProductFiltersForm
          filters={productFilters}
          disabled={isRefreshing || actionId !== null}
          onApply={onApplyProductFilters}
          onRefresh={onRefresh}
        />
        <CreateProductForm
          actionId={actionId}
          onCreateProduct={onCreateProduct}
        />
        <ProductBatchStatusToolbar
          products={products.items}
          selectedProductIds={selectedCurrentPageProductIds}
          allSelected={allCurrentPageSelected}
          disabled={isRefreshing || actionId !== null}
          actionId={bulkStatusAction}
          onToggleAll={handleToggleAllCurrentPage}
          onBatchStatus={handleBatchStatus}
        />
        {products.items.map((product) => (
          <ProductPreviewRow
            key={product.product_id}
            product={product}
            actionId={actionId}
            selected={selectedCurrentPageProductIds.includes(product.product_id)}
            onSelect={(checked) => handleToggleProduct(product.product_id, checked)}
            onUpdateProductMetadata={onUpdateProductMetadata}
            onUpdateProductSales={onUpdateProductSales}
            onImportProductInventory={onImportProductInventory}
            onUploadProductDeliveryFile={onUploadProductDeliveryFile}
          />
        ))}
        <TenantListPagination
          totalCount={products.total_count}
          limit={products.limit}
          offset={products.offset}
          itemCount={products.items.length}
          disabled={isRefreshing || actionId !== null}
          onPageChange={onProductPageChange}
        />
      </PreviewPanel>
      <PreviewPanel
        title="最近订单"
        totalCount={orders.total_count}
        itemCount={orders.items.length}
        emptyTitle="暂无订单"
        emptyDetail="当前 Bot 还没有订单记录。"
        alwaysShowChildren
      >
        {orderDiagnosticsError ? (
          <SupplyActionNotice result={{ kind: "error", message: orderDiagnosticsError }} />
        ) : null}
        <TenantOrderFiltersForm
          filters={orderFilters}
          disabled={isRefreshing}
          onApply={onApplyOrderFilters}
          onRefresh={onRefresh}
        />
        <OrderObservabilityPanel
          observability={orderObservability}
          isLoading={orderObservabilityLoading}
          errorMessage={orderObservabilityError}
          outTradeNo={orderObservabilityOutTradeNo}
          onRefresh={onRefreshOrderObservability}
          onClearScope={onClearOrderObservabilityScope}
        />
        {orders.items.map((order) => (
          <OrderPreviewRow
            key={order.out_trade_no}
            order={order}
            isDiagnosticsLoading={orderDiagnosticsActionId === `order:diagnostics:${order.out_trade_no}`}
            isDiagnosticsSelected={selectedOrderDiagnostics?.out_trade_no === order.out_trade_no}
            isObservabilityLoading={
              orderObservabilityLoading && orderObservabilityOutTradeNo === order.out_trade_no
            }
            isObservabilitySelected={orderObservabilityOutTradeNo === order.out_trade_no}
            onLoadOrderDiagnostics={onLoadOrderDiagnostics}
            onLoadOrderObservabilityForOrder={onLoadOrderObservabilityForOrder}
          />
        ))}
        <TenantListPagination
          totalCount={orders.total_count}
          limit={orders.limit}
          offset={orders.offset}
          itemCount={orders.items.length}
          disabled={isRefreshing}
          onPageChange={onOrderPageChange}
        />
        {selectedOrderDiagnostics ? <OrderDiagnosticsPanel diagnostics={selectedOrderDiagnostics} /> : null}
      </PreviewPanel>
    </div>
  )
}

function TenantProductFiltersForm({
  filters,
  disabled,
  onApply,
  onRefresh,
}: {
  filters: AdminWebTenantProductFilters
  disabled: boolean
  onApply: (filters: AdminWebTenantProductFilters) => void
  onRefresh: () => void
}) {
  const [query, setQuery] = React.useState(filters.query ?? "")
  const [category, setCategory] = React.useState(filters.category ?? "")
  const [status, setStatus] = React.useState(filters.status ?? "all")
  const [deliveryType, setDeliveryType] = React.useState(filters.delivery_type ?? "all")

  React.useEffect(() => {
    setQuery(filters.query ?? "")
    setCategory(filters.category ?? "")
    setStatus(filters.status ?? "all")
    setDeliveryType(filters.delivery_type ?? "all")
  }, [filters.query, filters.category, filters.status, filters.delivery_type])

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onApply({
      ...filters,
      offset: 0,
      query,
      category,
      status: normalizeProductStatusFilter(status),
      delivery_type: normalizeProductDeliveryTypeFilter(deliveryType),
    })
  }

  return (
    <form className="flex flex-col gap-2 rounded-md border p-3" onSubmit={handleSubmit}>
      <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,0.8fr)]">
        <Input
          value={query}
          aria-label="搜索商品名称或分类"
          placeholder="搜索名称/分类"
          disabled={disabled}
          onChange={(event) => setQuery(event.target.value)}
        />
        <Input
          value={category}
          aria-label="筛选商品分类"
          placeholder="分类"
          disabled={disabled}
          onChange={(event) => setCategory(event.target.value)}
        />
      </div>
      <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto]">
        <Select
          value={status}
          disabled={disabled}
          onValueChange={(value) => setStatus(normalizeProductStatusFilter(value))}
        >
          <SelectTrigger aria-label="筛选商品状态">
            <SelectValue placeholder="商品状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectLabel>商品状态</SelectLabel>
              <SelectItem value="all">全部状态</SelectItem>
              <SelectItem value="draft">草稿</SelectItem>
              <SelectItem value="on">上架</SelectItem>
              <SelectItem value="off">下架</SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
        <Select
          value={deliveryType}
          disabled={disabled}
          onValueChange={(value) => setDeliveryType(normalizeProductDeliveryTypeFilter(value))}
        >
          <SelectTrigger aria-label="筛选商品发货类型">
            <SelectValue placeholder="发货类型" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectLabel>发货类型</SelectLabel>
              <SelectItem value="all">全部发货</SelectItem>
              <SelectItem value="card_pool">{deliveryTypeLabel("card_pool")}</SelectItem>
              <SelectItem value="card_fixed">{deliveryTypeLabel("card_fixed")}</SelectItem>
              <SelectItem value="file_download">{deliveryTypeLabel("file_download")}</SelectItem>
              <SelectItem value="telegram_invite">{deliveryTypeLabel("telegram_invite")}</SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
        <Button type="submit" size="sm" variant="outline" disabled={disabled}>
          <SearchIcon data-icon="inline-start" />
          筛选
        </Button>
        <Button type="button" size="sm" variant="outline" disabled={disabled} onClick={onRefresh}>
          <RefreshCwIcon data-icon="inline-start" />
          刷新
        </Button>
      </div>
    </form>
  )
}

function TenantOrderFiltersForm({
  filters,
  disabled,
  onApply,
  onRefresh,
}: {
  filters: AdminWebTenantOrderFilters
  disabled: boolean
  onApply: (filters: AdminWebTenantOrderFilters) => void
  onRefresh: () => void
}) {
  const [outTradeNo, setOutTradeNo] = React.useState(filters.out_trade_no ?? "")
  const [status, setStatus] = React.useState(filters.status ?? "all")
  const [sourceType, setSourceType] = React.useState(filters.source_type ?? "all")
  const [paymentMode, setPaymentMode] = React.useState(filters.payment_mode ?? "all")

  React.useEffect(() => {
    setOutTradeNo(filters.out_trade_no ?? "")
    setStatus(filters.status ?? "all")
    setSourceType(filters.source_type ?? "all")
    setPaymentMode(filters.payment_mode ?? "all")
  }, [filters.out_trade_no, filters.status, filters.source_type, filters.payment_mode])

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onApply({
      ...filters,
      offset: 0,
      out_trade_no: outTradeNo,
      status: normalizeOrderStatusFilter(status),
      source_type: normalizeOrderSourceTypeFilter(sourceType),
      payment_mode: normalizeOrderPaymentModeFilter(paymentMode),
    })
  }

  return (
    <form className="flex flex-col gap-2 rounded-md border p-3" onSubmit={handleSubmit}>
      <Input
        value={outTradeNo}
        aria-label="搜索订单号"
        placeholder="搜索订单号"
        disabled={disabled}
        onChange={(event) => setOutTradeNo(event.target.value)}
      />
      <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_auto_auto]">
        <Select
          value={status}
          disabled={disabled}
          onValueChange={(value) => setStatus(normalizeOrderStatusFilter(value))}
        >
          <SelectTrigger aria-label="筛选订单状态">
            <SelectValue placeholder="订单状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectLabel>订单状态</SelectLabel>
              <SelectItem value="all">全部状态</SelectItem>
              <SelectItem value="pending">待支付</SelectItem>
              <SelectItem value="paid">已支付</SelectItem>
              <SelectItem value="delivered">已发货</SelectItem>
              <SelectItem value="expired">已超时</SelectItem>
              <SelectItem value="completed">已完成</SelectItem>
              <SelectItem value="refunded">已退款</SelectItem>
              <SelectItem value="partially_refunded">部分退款</SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
        <Select
          value={sourceType}
          disabled={disabled}
          onValueChange={(value) => setSourceType(normalizeOrderSourceTypeFilter(value))}
        >
          <SelectTrigger aria-label="筛选订单来源">
            <SelectValue placeholder="订单来源" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectLabel>订单来源</SelectLabel>
              <SelectItem value="all">全部来源</SelectItem>
              <SelectItem value="self">自营</SelectItem>
              <SelectItem value="reseller">代理</SelectItem>
              <SelectItem value="subscription">订阅</SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
        <Select
          value={paymentMode}
          disabled={disabled}
          onValueChange={(value) => setPaymentMode(normalizeOrderPaymentModeFilter(value))}
        >
          <SelectTrigger aria-label="筛选支付模式">
            <SelectValue placeholder="支付模式" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectLabel>支付模式</SelectLabel>
              <SelectItem value="all">全部支付</SelectItem>
              <SelectItem value="tenant_direct">租户直收</SelectItem>
              <SelectItem value="platform_escrow">平台托管</SelectItem>
              <SelectItem value="platform_subscription">平台订阅</SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
        <Button type="submit" size="sm" variant="outline" disabled={disabled}>
          <SearchIcon data-icon="inline-start" />
          筛选
        </Button>
        <Button type="button" size="sm" variant="outline" disabled={disabled} onClick={onRefresh}>
          <RefreshCwIcon data-icon="inline-start" />
          刷新
        </Button>
      </div>
    </form>
  )
}

function TenantListPagination({
  totalCount,
  limit,
  offset,
  itemCount,
  disabled,
  onPageChange,
}: {
  totalCount: number
  limit: number
  offset: number
  itemCount: number
  disabled: boolean
  onPageChange: (offset: number) => void
}) {
  if (totalCount <= limit && offset === 0) {
    return null
  }
  const previousOffset = Math.max(0, offset - limit)
  const nextOffset = offset + limit
  const hasPrevious = offset > 0
  const hasNext = nextOffset < totalCount
  const start = totalCount === 0 ? 0 : offset + 1
  const end = Math.min(offset + itemCount, totalCount)

  return (
    <div className="flex flex-col gap-2 rounded-md border p-3 sm:flex-row sm:items-center sm:justify-between">
      <p className="text-xs text-muted-foreground">
        {start}-{end} / {totalCount}
      </p>
      <div className="flex gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={disabled || !hasPrevious}
          onClick={() => onPageChange(previousOffset)}
        >
          <ChevronLeftIcon data-icon="inline-start" />
          上一页
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={disabled || !hasNext}
          onClick={() => onPageChange(nextOffset)}
        >
          下一页
          <ChevronRightIcon data-icon="inline-end" />
        </Button>
      </div>
    </div>
  )
}

function PreviewPanel({
  title,
  totalCount,
  itemCount,
  emptyTitle,
  emptyDetail,
  alwaysShowChildren = false,
  children,
}: {
  title: string
  totalCount: number
  itemCount: number
  emptyTitle: string
  emptyDetail: string
  alwaysShowChildren?: boolean
  children: React.ReactNode
}) {
  return (
    <div className="rounded-md border p-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium">{title}</p>
        <Badge variant="outline">{totalCount}</Badge>
      </div>
      <div className="mt-3 flex flex-col gap-2">
        {itemCount > 0 || alwaysShowChildren ? children : null}
        {itemCount === 0 ? <StatusBlock title={emptyTitle} detail={emptyDetail} /> : null}
      </div>
    </div>
  )
}

function SupplierOfferCreateForm({
  products,
  actionId,
  disabled,
  onCreateSupplierOffer,
}: {
  products: AdminWebTenantProduct[]
  actionId: string | null
  disabled: boolean
  onCreateSupplierOffer: (payload: AdminWebCreateSupplierOfferPayload) => void
}) {
  const availableProducts = products.filter((product) => product.status === "on")
  const [productId, setProductId] = React.useState("")
  const [suggestedPrice, setSuggestedPrice] = React.useState("")
  const [minSalePrice, setMinSalePrice] = React.useState("")
  const [requiresApproval, setRequiresApproval] = React.useState(true)
  const isActionBusy = actionId !== null || disabled
  const selectedProduct = availableProducts.find((product) => String(product.product_id) === productId)
  const isCreating = selectedProduct ? actionId === `supplier-offer:create:${selectedProduct.product_id}` : false

  React.useEffect(() => {
    if (!selectedProduct) {
      return
    }
    setSuggestedPrice(selectedProduct.price)
    setMinSalePrice(selectedProduct.price)
  }, [selectedProduct?.product_id])

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedProduct) {
      return
    }
    onCreateSupplierOffer({
      product_id: selectedProduct.product_id,
      suggested_price: suggestedPrice,
      min_sale_price: minSalePrice,
      requires_approval: requiresApproval,
    })
  }

  if (availableProducts.length === 0) {
    return <StatusBlock title="暂无可供货商品" detail="请先上架自营商品，再开放给代理商选择。" />
  }

  return (
    <form className="flex flex-col gap-3 rounded-md border p-3" onSubmit={handleSubmit}>
      <div className="flex flex-col gap-2 sm:flex-row">
        <Select value={productId} disabled={isActionBusy} onValueChange={setProductId}>
          <SelectTrigger className="sm:flex-1">
            <SelectValue placeholder="选择自营商品" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectLabel>自营商品</SelectLabel>
              {availableProducts.map((product) => (
                <SelectItem key={product.product_id} value={String(product.product_id)}>
                  {product.name}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <Select
          value={requiresApproval ? "approval" : "open"}
          disabled={isActionBusy}
          onValueChange={(value) => setRequiresApproval(value === "approval")}
        >
          <SelectTrigger className="sm:w-36">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectLabel>代理审核</SelectLabel>
              <SelectItem value="approval">需审批</SelectItem>
              <SelectItem value="open">免审批</SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <Input
          value={suggestedPrice}
          inputMode="decimal"
          aria-label="供货建议售价"
          placeholder="建议售价"
          disabled={isActionBusy}
          onChange={(event) => setSuggestedPrice(event.target.value)}
        />
        <Input
          value={minSalePrice}
          inputMode="decimal"
          aria-label="供货最低售价"
          placeholder="最低售价"
          disabled={isActionBusy}
          onChange={(event) => setMinSalePrice(event.target.value)}
        />
      </div>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-xs text-muted-foreground">
          供货成本使用该商品当前默认售价，库存仍由当前 Bot 管理。
        </p>
        <Button type="submit" size="sm" disabled={isActionBusy || !selectedProduct}>
          <PlusIcon data-icon="inline-start" />
          {isCreating ? "正在开放" : "开放供货"}
        </Button>
      </div>
    </form>
  )
}

function SupplierOfferPreviewRow({
  offer,
  actionId,
  disabled,
  onSetApproval,
}: {
  offer: AdminWebSupplierOffer
  actionId: string | null
  disabled: boolean
  onSetApproval: (supplierOfferId: number, payload: AdminWebSupplierOfferApprovalPayload) => void
}) {
  const actionKey = `supplier-offer:approval:${offer.supplier_offer_id}`
  const isActionBusy = actionId !== null || disabled
  const isUpdating = actionId === actionKey

  return (
    <div className="flex flex-col gap-2 rounded-md border p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{offer.product_name}</p>
          <p className="mt-1 truncate text-xs text-muted-foreground">
            成本 {offer.supplier_cost} {offer.currency} · 库存 {offer.available_count}
          </p>
        </div>
        <Badge variant={offer.status === "on" ? "secondary" : "outline"}>
          {offer.requires_approval ? "需审批" : "免审批"}
        </Badge>
      </div>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-xs text-muted-foreground">
          建议 {offer.suggested_price} {offer.currency} · 最低 {offer.min_sale_price ?? "-"}
        </p>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={isActionBusy || offer.status !== "on"}
          onClick={() =>
            onSetApproval(offer.supplier_offer_id, {
              requires_approval: !offer.requires_approval,
            })
          }
        >
          {isUpdating ? "正在切换" : offer.requires_approval ? "改为免审批" : "改为需审批"}
        </Button>
      </div>
    </div>
  )
}

function SupplierApplicationsPreview({
  applications,
  actionId,
  disabled,
  onReview,
}: {
  applications: AdminWebSupplierApplication[]
  actionId: string | null
  disabled: boolean
  onReview: (payload: AdminWebSupplierApplicationReviewPayload) => void
}) {
  const pendingCount = applications.filter((application) => application.status === "pending").length

  return (
    <div className="flex flex-col gap-2">
      <Separator />
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium">代理申请审核</p>
          <p className="mt-1 text-xs text-muted-foreground">待审申请优先显示。</p>
        </div>
        <Badge variant={pendingCount > 0 ? "secondary" : "outline"}>待审 {pendingCount}</Badge>
      </div>
      {applications.length > 0 ? (
        applications.slice(0, 4).map((application) => (
          <SupplierApplicationPreviewRow
            key={application.supplier_application_id}
            application={application}
            actionId={actionId}
            disabled={disabled}
            onReview={onReview}
          />
        ))
      ) : (
        <StatusBlock title="暂无代理申请" detail="有代理商提交申请后会出现在这里。" />
      )}
    </div>
  )
}

function SupplierApplicationPreviewRow({
  application,
  actionId,
  disabled,
  onReview,
}: {
  application: AdminWebSupplierApplication
  actionId: string | null
  disabled: boolean
  onReview: (payload: AdminWebSupplierApplicationReviewPayload) => void
}) {
  const canReview = application.status === "pending"
  const approveActionId = `approve:${application.supplier_application_id}`
  const rejectActionId = `reject:${application.supplier_application_id}`
  const isActionBusy = actionId !== null || disabled

  return (
    <div className="flex flex-col gap-3 rounded-md border p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{application.product_name}</p>
          <p className="mt-1 truncate text-xs text-muted-foreground">
            {application.reseller_store_name} · {application.pricing_value} {application.currency}
          </p>
        </div>
        <Badge variant={application.status === "active" ? "secondary" : "outline"}>
          {resellerRuleStatusLabel(application.status)}
        </Badge>
      </div>
      {canReview ? (
        <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
          <Button
            type="button"
            size="sm"
            variant="secondary"
            disabled={isActionBusy}
            onClick={() =>
              onReview({
                supplier_application_id: application.supplier_application_id,
                action: "approve",
              })
            }
          >
            {actionId === approveActionId ? "正在通过" : "通过申请"}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={isActionBusy}
            onClick={() =>
              onReview({
                supplier_application_id: application.supplier_application_id,
                action: "reject",
              })
            }
          >
            {actionId === rejectActionId ? "正在拒绝" : "拒绝"}
          </Button>
        </div>
      ) : null}
    </div>
  )
}


function SupplierRulesPreview({
  rules,
  actionId,
  disabled,
  onSetSupplierRule,
}: {
  rules: AdminWebSupplierRule[]
  actionId: string | null
  disabled: boolean
  onSetSupplierRule: (payload: AdminWebSupplierRulePayload) => void
}) {
  return (
    <div className="flex flex-col gap-2">
      <Separator />
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium">独立代理规则</p>
        <Badge variant="outline">{rules.length}</Badge>
      </div>
      {rules.slice(0, 4).map((rule) => (
        <SupplierRuleEditor
          key={rule.supplier_rule_id}
          rule={rule}
          actionId={actionId}
          disabled={disabled}
          onSetSupplierRule={onSetSupplierRule}
        />
      ))}
    </div>
  )
}

function SupplierRuleEditor({
  rule,
  actionId,
  disabled,
  onSetSupplierRule,
}: {
  rule: AdminWebSupplierRule
  actionId: string | null
  disabled: boolean
  onSetSupplierRule: (payload: AdminWebSupplierRulePayload) => void
}) {
  const [pricingValue, setPricingValue] = React.useState(rule.pricing_value)
  const [minSalePrice, setMinSalePrice] = React.useState(rule.min_sale_price ?? "")
  const actionKey = `supplier-rule:${rule.supplier_rule_id}`
  const isActionBusy = actionId !== null || disabled
  const isUpdating = actionId === actionKey
  const canEdit = !disabled && (rule.status === "pending" || rule.status === "active")

  React.useEffect(() => {
    setPricingValue(rule.pricing_value)
    setMinSalePrice(rule.min_sale_price ?? "")
  }, [rule.supplier_rule_id, rule.pricing_value, rule.min_sale_price])

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canEdit) {
      return
    }
    onSetSupplierRule({
      supplier_rule_id: rule.supplier_rule_id,
      pricing_value: pricingValue,
      min_sale_price: minSalePrice,
    })
  }

  return (
    <form className="flex flex-col gap-3 rounded-md border p-3" onSubmit={handleSubmit}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{rule.product_name}</p>
          <p className="mt-1 truncate text-xs text-muted-foreground">
            {rule.reseller_store_name} · {rule.currency}
          </p>
        </div>
        <Badge variant={rule.status === "active" ? "secondary" : "outline"}>
          {resellerRuleStatusLabel(rule.status)}
        </Badge>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <Input
          value={pricingValue}
          inputMode="decimal"
          aria-label="独立供应商成本"
          placeholder="供应商成本"
          disabled={isActionBusy || !canEdit}
          onChange={(event) => setPricingValue(event.target.value)}
        />
        <Input
          value={minSalePrice}
          inputMode="decimal"
          aria-label="独立最低售价"
          placeholder="最低售价"
          disabled={isActionBusy || !canEdit}
          onChange={(event) => setMinSalePrice(event.target.value)}
        />
      </div>
      <div className="flex justify-end">
        <Button type="submit" size="sm" variant="outline" disabled={isActionBusy || !canEdit}>
          {isUpdating ? "正在保存" : "保存规则"}
        </Button>
      </div>
    </form>
  )
}

function MarketOfferPreviewRow({
  offer,
  actionId,
  disabled,
  onSupplyApply,
  onCreateResellerProduct,
}: {
  offer: AdminWebSupplyMarketOffer
  actionId: string | null
  disabled: boolean
  onSupplyApply: (offer: AdminWebSupplyMarketOffer) => void
  onCreateResellerProduct: (payload: AdminWebCreateResellerProductPayload) => void
}) {
  const suggestedSalePrice = offer.effective_min_sale_price ?? offer.suggested_price
  const [salePrice, setSalePrice] = React.useState(suggestedSalePrice)
  const [displayName, setDisplayName] = React.useState(offer.product_name)
  const applyActionId = `apply:${offer.supplier_offer_id}`
  const createActionId = `create:${offer.supplier_offer_id}`
  const isActionBusy = actionId !== null || disabled
  const isApplying = actionId === applyActionId
  const isCreating = actionId === createActionId
  const canRequestApproval =
    !disabled && offer.requires_approval && offer.reseller_rule_status !== "pending" && !offer.can_create_reseller_product

  React.useEffect(() => {
    setSalePrice(suggestedSalePrice)
    setDisplayName(offer.product_name)
  }, [offer.supplier_offer_id, offer.product_name, suggestedSalePrice])

  function handleCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onCreateResellerProduct({
      supplier_offer_id: offer.supplier_offer_id,
      sale_price: salePrice,
      display_name: displayName,
    })
  }

  return (
    <div className="flex flex-col gap-2 rounded-md border p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{offer.product_name}</p>
          <p className="mt-1 truncate text-xs text-muted-foreground">
            {offer.category || "未分类"} · 成本 {offer.supplier_cost} {offer.currency} · 建议 {offer.suggested_price}
          </p>
        </div>
        <Badge variant={offer.can_create_reseller_product ? "secondary" : "outline"}>
          {marketOfferAccessLabel(offer)}
        </Badge>
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        <MetricLine label="库存" value={String(offer.available_count)} />
        <MetricLine label="最低售价" value={marketOfferMinSaleText(offer)} />
        <MetricLine label="发货" value={deliveryTypeLabel(offer.delivery_type)} />
      </div>
      {offer.can_create_reseller_product ? (
        <form className="flex flex-col gap-3" onSubmit={handleCreate}>
          <div className="grid gap-2 sm:grid-cols-2">
            <Input
              value={salePrice}
              inputMode="decimal"
              aria-label={`${offer.product_name} 代理售价`}
              placeholder="代理售价"
              disabled={isActionBusy}
              onChange={(event) => setSalePrice(event.target.value)}
            />
            <Input
              value={displayName}
              aria-label={`${offer.product_name} 展示名`}
              placeholder="代理商品展示名"
              maxLength={255}
              disabled={isActionBusy}
              onChange={(event) => setDisplayName(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-muted-foreground">
              {disabled ? "代理商能力未开启，暂不能上架到当前 Bot。" : "上架到当前 Bot 后，买家侧只看到代理店铺商品。"}
            </p>
            <Button type="submit" size="sm" disabled={isActionBusy || !salePrice.trim()}>
              <PlusIcon data-icon="inline-start" />
              {isCreating ? "正在上架" : "上架到当前 Bot"}
            </Button>
          </div>
        </form>
      ) : (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-muted-foreground">
            {disabled
              ? "代理商能力未开启，暂不能提交代理申请。"
              : offer.reseller_rule_status === "pending"
              ? "申请已提交，等待供应商审核。"
              : "该商品需要供应商审批后才能设置售价并上架。"}
          </p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={isActionBusy || !canRequestApproval}
            onClick={() => onSupplyApply(offer)}
          >
            <ChevronRightIcon data-icon="inline-start" />
            {isApplying ? "正在申请" : "申请代理"}
          </Button>
        </div>
      )}
    </div>
  )
}

function ResellerProductPreviewRow({
  product,
  actionId,
  disabled,
  onUpdateResellerProductMetadata,
  onUpdateResellerProductSales,
}: {
  product: AdminWebResellerProduct
  actionId: string | null
  disabled: boolean
  onUpdateResellerProductMetadata: (
    resellerProductId: number,
    payload: AdminWebResellerProductMetadataPayload,
  ) => void
  onUpdateResellerProductSales: (
    resellerProductId: number,
    payload: AdminWebResellerProductSalesPayload,
  ) => void
}) {
  const [displayName, setDisplayName] = React.useState(product.display_name)
  const [salePrice, setSalePrice] = React.useState(product.sale_price)
  const [category, setCategory] = React.useState(product.category ?? "")
  const [sortOrder, setSortOrder] = React.useState(String(product.sort_order))
  const salesActionKey = `reseller-product:sales:${product.reseller_product_id}`
  const metadataActionKey = `reseller-product:metadata:${product.reseller_product_id}`
  const isActionBusy = actionId !== null || disabled
  const isUpdatingSales = actionId === salesActionKey
  const isUpdatingMetadata = actionId === metadataActionKey

  React.useEffect(() => {
    setDisplayName(product.display_name)
    setSalePrice(product.sale_price)
    setCategory(product.category ?? "")
    setSortOrder(String(product.sort_order))
  }, [product.reseller_product_id, product.display_name, product.sale_price, product.category, product.sort_order])

  function handleSalesSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onUpdateResellerProductSales(product.reseller_product_id, {
      display_name: displayName,
      sale_price: salePrice,
    })
  }

  function handleMetadataSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const parsedSortOrder = Number(sortOrder)
    onUpdateResellerProductMetadata(product.reseller_product_id, {
      category,
      sort_order: Number.isInteger(parsedSortOrder) ? parsedSortOrder : Number.NaN,
    })
  }

  return (
    <div className="flex flex-col gap-3 rounded-md border p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{product.display_name}</p>
          <p className="mt-1 truncate text-xs text-muted-foreground">
            {product.category || "未分类"} · {deliveryTypeLabel(product.delivery_type)}
          </p>
        </div>
        <Badge variant={product.status === "on" ? "secondary" : "outline"}>
          {productStatusLabel(product.status)}
        </Badge>
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        <MetricLine label="售价" value={`${product.sale_price} ${product.currency}`} />
        <MetricLine label="库存" value={String(product.available_count)} />
        <MetricLine label="排序" value={String(product.sort_order)} />
      </div>
      <form className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_8rem_auto]" onSubmit={handleSalesSubmit}>
        <Input
          value={displayName}
          aria-label="代理商品展示名"
          placeholder="展示名"
          disabled={isActionBusy}
          onChange={(event) => setDisplayName(event.target.value)}
        />
        <Input
          value={salePrice}
          inputMode="decimal"
          aria-label="代理商品售价"
          placeholder="售价"
          disabled={isActionBusy}
          onChange={(event) => setSalePrice(event.target.value)}
        />
        <Button type="submit" size="sm" variant="outline" disabled={isActionBusy}>
          {isUpdatingSales ? "正在保存" : "保存展示/售价"}
        </Button>
      </form>
      <form className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_7rem_auto]" onSubmit={handleMetadataSubmit}>
        <Input
          value={category}
          aria-label="代理商品分类"
          placeholder="分类"
          disabled={isActionBusy}
          onChange={(event) => setCategory(event.target.value)}
        />
        <Input
          value={sortOrder}
          inputMode="numeric"
          aria-label="代理商品排序"
          placeholder="排序"
          disabled={isActionBusy}
          onChange={(event) => setSortOrder(event.target.value)}
        />
        <Button type="submit" size="sm" variant="outline" disabled={isActionBusy}>
          {isUpdatingMetadata ? "正在保存" : "保存分类/排序"}
        </Button>
      </form>
    </div>
  )
}

function CreateProductForm({
  actionId,
  onCreateProduct,
}: {
  actionId: string | null
  onCreateProduct: (payload: AdminWebCreateProductPayload) => void
}) {
  const [name, setName] = React.useState("")
  const [price, setPrice] = React.useState("")
  const [deliveryType, setDeliveryType] = React.useState<AdminWebCreateProductPayload["delivery_type"]>("card_pool")
  const [category, setCategory] = React.useState("")
  const [description, setDescription] = React.useState("")
  const isActionBusy = actionId !== null
  const isCreating = actionId === "product:create"

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onCreateProduct({
      name,
      price,
      delivery_type: deliveryType,
      category,
      description,
    })
  }

  return (
    <form className="flex flex-col gap-2 rounded-md border p-3" onSubmit={handleSubmit}>
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium">新建商品</p>
        <Badge variant="outline">草稿</Badge>
      </div>
      <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_8rem]">
        <Input
          value={name}
          aria-label="新建商品名称"
          placeholder="商品名称"
          disabled={isActionBusy}
          onChange={(event) => setName(event.target.value)}
        />
        <Input
          value={price}
          inputMode="decimal"
          aria-label="新建商品售价"
          placeholder="售价"
          disabled={isActionBusy}
          onChange={(event) => setPrice(event.target.value)}
        />
      </div>
      <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Select
          value={deliveryType}
          disabled={isActionBusy}
          onValueChange={(value) => setDeliveryType(normalizeDeliveryType(value))}
        >
          <SelectTrigger aria-label="新建商品发货类型">
            <SelectValue placeholder="发货类型" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectLabel>发货类型</SelectLabel>
              <SelectItem value="card_pool">{deliveryTypeLabel("card_pool")}</SelectItem>
              <SelectItem value="card_fixed">{deliveryTypeLabel("card_fixed")}</SelectItem>
              <SelectItem value="file_download">{deliveryTypeLabel("file_download")}</SelectItem>
              <SelectItem value="telegram_invite">{deliveryTypeLabel("telegram_invite")}</SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
        <Input
          value={category}
          aria-label="新建商品分类"
          placeholder="分类"
          disabled={isActionBusy}
          onChange={(event) => setCategory(event.target.value)}
        />
      </div>
      <Input
        value={description}
        aria-label="新建商品描述"
        placeholder="描述"
        disabled={isActionBusy}
        onChange={(event) => setDescription(event.target.value)}
      />
      <Button type="submit" size="sm" variant="outline" disabled={isActionBusy}>
        {isCreating ? "正在创建" : "创建商品"}
      </Button>
    </form>
  )
}

function ProductBatchStatusToolbar({
  products,
  selectedProductIds,
  allSelected,
  disabled,
  actionId,
  onToggleAll,
  onBatchStatus,
}: {
  products: AdminWebTenantProduct[]
  selectedProductIds: number[]
  allSelected: boolean
  disabled: boolean
  actionId: string | null
  onToggleAll: (checked: boolean) => void
  onBatchStatus: (status: "on" | "off") => void
}) {
  if (products.length === 0) {
    return null
  }
  const selectedCount = selectedProductIds.length
  const isPublishing = actionId === "product:batch-status:on"
  const isUnpublishing = actionId === "product:batch-status:off"

  return (
    <div className="flex flex-col gap-3 rounded-md border p-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <label className="flex items-center gap-2 text-sm">
          <Checkbox
            checked={allSelected ? true : selectedCount > 0 ? "indeterminate" : false}
            disabled={disabled}
            aria-label="选择当前页全部商品"
            onCheckedChange={(checked) => onToggleAll(checked === true)}
          />
          当前页全选
        </label>
        <p className="mt-1 text-xs text-muted-foreground">
          仅操作当前页 {products.length} 个商品，单次最多 50 个。
        </p>
      </div>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <Badge variant="outline">已选 {selectedCount}</Badge>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={disabled || selectedCount === 0}
          onClick={() => onBatchStatus("on")}
        >
          <CheckCircle2Icon data-icon="inline-start" />
          {isPublishing ? "正在上架" : "批量上架"}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={disabled || selectedCount === 0}
          onClick={() => onBatchStatus("off")}
        >
          <PauseCircleIcon data-icon="inline-start" />
          {isUnpublishing ? "正在下架" : "批量下架"}
        </Button>
      </div>
    </div>
  )
}

function ProductPreviewRow({
  product,
  actionId,
  selected,
  onSelect,
  onUpdateProductMetadata,
  onUpdateProductSales,
  onImportProductInventory,
  onUploadProductDeliveryFile,
}: {
  product: AdminWebTenantProduct
  actionId: string | null
  selected: boolean
  onSelect: (checked: boolean) => void
  onUpdateProductMetadata: (productId: number, payload: AdminWebProductMetadataPayload) => void
  onUpdateProductSales: (productId: number, payload: AdminWebProductSalesPayload) => void
  onImportProductInventory: (productId: number, payload: AdminWebProductInventoryImportPayload) => Promise<boolean>
  onUploadProductDeliveryFile: (productId: number, file: File | null) => Promise<boolean>
}) {
  const [category, setCategory] = React.useState(product.category ?? "")
  const [sortOrder, setSortOrder] = React.useState(String(product.sort_order))
  const [price, setPrice] = React.useState(product.price)
  const [inventoryText, setInventoryText] = React.useState("")
  const [deliveryFile, setDeliveryFile] = React.useState<File | null>(null)
  const [status, setStatus] = React.useState<AdminWebProductSalesPayload["status"]>(
    normalizeProductStatus(product.status),
  )
  const metadataActionKey = `product:metadata:${product.product_id}`
  const salesActionKey = `product:sales:${product.product_id}`
  const inventoryActionKey = `product:inventory-import:${product.product_id}`
  const deliveryFileActionKey = `product:file-bind:${product.product_id}`
  const canImportInventory = product.delivery_type === "card_pool" || product.delivery_type === "card_fixed"
  const canBindDeliveryFile = product.delivery_type === "file_download"
  const isActionBusy = actionId !== null
  const isUpdatingMetadata = actionId === metadataActionKey
  const isUpdatingSales = actionId === salesActionKey
  const isImportingInventory = actionId === inventoryActionKey
  const isBindingDeliveryFile = actionId === deliveryFileActionKey

  React.useEffect(() => {
    setCategory(product.category ?? "")
    setSortOrder(String(product.sort_order))
    setPrice(product.price)
    setStatus(normalizeProductStatus(product.status))
  }, [product.product_id, product.category, product.sort_order, product.price, product.status])

  function handleMetadataSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const parsedSortOrder = Number(sortOrder)
    onUpdateProductMetadata(product.product_id, {
      category,
      sort_order: Number.isInteger(parsedSortOrder) ? parsedSortOrder : Number.NaN,
    })
  }

  function handleSalesSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onUpdateProductSales(product.product_id, { price, status })
  }

  async function handleInventorySubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const items = inventoryText.split(/\r?\n/)
    const imported = await onImportProductInventory(product.product_id, { items })
    if (imported) {
      setInventoryText("")
    }
  }

  async function handleDeliveryFileSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const bound = await onUploadProductDeliveryFile(product.product_id, deliveryFile)
    if (bound) {
      setDeliveryFile(null)
      event.currentTarget.reset()
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-md border p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2">
          <Checkbox
            checked={selected}
            disabled={isActionBusy}
            aria-label={`选择商品 ${product.name}`}
            onCheckedChange={(checked) => onSelect(checked === true)}
          />
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{product.name}</p>
            <p className="mt-1 truncate text-xs text-muted-foreground">
              {product.category || "未分类"} · {deliveryTypeLabel(product.delivery_type)}
            </p>
          </div>
        </div>
        <Badge variant={product.status === "on" ? "secondary" : "outline"}>
          {productStatusLabel(product.status)}
        </Badge>
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        <MetricLine label="售价" value={`${product.price} ${product.currency}`} />
        <MetricLine label="库存" value={String(product.available_count)} />
        <MetricLine label="排序" value={String(product.sort_order)} />
      </div>
      <form className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_7rem_auto]" onSubmit={handleMetadataSubmit}>
        <Input
          value={category}
          aria-label="商品分类"
          placeholder="分类"
          disabled={isActionBusy}
          onChange={(event) => setCategory(event.target.value)}
        />
        <Input
          value={sortOrder}
          inputMode="numeric"
          aria-label="商品排序"
          placeholder="排序"
          disabled={isActionBusy}
          onChange={(event) => setSortOrder(event.target.value)}
        />
        <Button type="submit" size="sm" variant="outline" disabled={isActionBusy}>
          {isUpdatingMetadata ? "正在保存" : "保存分类"}
        </Button>
      </form>
      <form className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_8rem_auto]" onSubmit={handleSalesSubmit}>
        <Input
          value={price}
          inputMode="decimal"
          aria-label="商品售价"
          placeholder="售价"
          disabled={isActionBusy}
          onChange={(event) => setPrice(event.target.value)}
        />
        <Select
          value={status}
          disabled={isActionBusy}
          onValueChange={(value) => setStatus(normalizeProductStatus(value))}
        >
          <SelectTrigger aria-label="商品状态">
            <SelectValue placeholder="状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectLabel>商品状态</SelectLabel>
              <SelectItem value="draft">草稿</SelectItem>
              <SelectItem value="on">上架</SelectItem>
              <SelectItem value="off">下架</SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
        <Button type="submit" size="sm" variant="outline" disabled={isActionBusy}>
          {isUpdatingSales ? "正在保存" : "保存售价"}
        </Button>
      </form>
      {canImportInventory ? (
        <form className="flex flex-col gap-2" onSubmit={handleInventorySubmit}>
          <textarea
            value={inventoryText}
            aria-label="商品库存内容"
            placeholder="每行一条库存内容"
            disabled={isActionBusy}
            className="min-h-24 resize-y rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm outline-none placeholder:text-muted-foreground focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
            onChange={(event) => setInventoryText(event.target.value)}
          />
          <Button type="submit" size="sm" variant="outline" disabled={isActionBusy || inventoryText.trim() === ""}>
            {isImportingInventory ? "正在导入" : "导入库存"}
          </Button>
        </form>
      ) : null}
      {canBindDeliveryFile ? (
        <form className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]" onSubmit={handleDeliveryFileSubmit}>
          <Input
            type="file"
            accept=".zip,.rar,.7z,application/zip,application/vnd.rar,application/x-rar,application/x-7z-compressed"
            aria-label="商品交付文件"
            disabled={isActionBusy}
            onChange={(event) => setDeliveryFile(event.target.files?.item(0) ?? null)}
          />
          <Button type="submit" size="sm" variant="outline" disabled={isActionBusy || !deliveryFile}>
            {isBindingDeliveryFile ? "正在绑定" : "绑定文件"}
          </Button>
        </form>
      ) : null}
    </div>
  )
}

function OrderPreviewRow({
  order,
  isDiagnosticsLoading,
  isDiagnosticsSelected,
  isObservabilityLoading,
  isObservabilitySelected,
  onLoadOrderDiagnostics,
  onLoadOrderObservabilityForOrder,
}: {
  order: AdminWebTenantOrder
  isDiagnosticsLoading: boolean
  isDiagnosticsSelected: boolean
  isObservabilityLoading: boolean
  isObservabilitySelected: boolean
  onLoadOrderDiagnostics: (order: AdminWebTenantOrder) => void
  onLoadOrderObservabilityForOrder: (order: AdminWebTenantOrder) => void
}) {
  return (
    <div className="flex flex-col gap-2 rounded-md border p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{order.out_trade_no}</p>
          <p className="mt-1 truncate text-xs text-muted-foreground">
            买家 {order.buyer_telegram_user_id} · {sourceTypeLabel(order.source_type)}
          </p>
        </div>
        <Badge variant={order.status === "delivered" ? "secondary" : "outline"}>
          {orderStatusLabel(order.status)}
        </Badge>
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        <MetricLine label="金额" value={`${order.amount} ${order.currency}`} />
        <MetricLine label="支付" value={paymentModeLabel(order.payment_mode)} />
        <MetricLine label="创建" value={formatDateTime(order.created_at)} />
      </div>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          variant={isDiagnosticsSelected ? "secondary" : "outline"}
          disabled={isDiagnosticsLoading}
          onClick={() => onLoadOrderDiagnostics(order)}
        >
          {isDiagnosticsLoading ? "正在读取" : isDiagnosticsSelected ? "已打开排障" : "订单排障"}
        </Button>
        <Button
          type="button"
          size="sm"
          variant={isObservabilitySelected ? "secondary" : "outline"}
          disabled={isObservabilityLoading}
          onClick={() => onLoadOrderObservabilityForOrder(order)}
        >
          <ListTreeIcon data-icon="inline-start" />
          {isObservabilityLoading ? "观测中" : isObservabilitySelected ? "已观测此单" : "观测此单"}
        </Button>
      </div>
    </div>
  )
}

function OrderObservabilityPanel({
  observability,
  isLoading,
  errorMessage,
  outTradeNo,
  onRefresh,
  onClearScope,
}: {
  observability: AdminWebTenantOrderObservability | null
  isLoading: boolean
  errorMessage: string | null
  outTradeNo: string | null
  onRefresh: () => void
  onClearScope: () => void
}) {
  const hasItems = Boolean(
    observability &&
      (
        observability.callback_failures.length > 0 ||
        observability.callback_rejections.length > 0 ||
        observability.external_fulfillment_attempts.length > 0
      ),
  )

  return (
    <div className="flex flex-col gap-3 rounded-md border bg-muted/30 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">订单观测</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {outTradeNo ? "当前仅展示指定订单的安全观测摘要。" : "最近支付回调异常与外部履约尝试。"}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-2">
          {outTradeNo ? (
            <Button type="button" size="sm" variant="outline" disabled={isLoading} onClick={onClearScope}>
              查看全部
            </Button>
          ) : null}
          <Button type="button" size="sm" variant="outline" disabled={isLoading} onClick={onRefresh}>
            <RefreshCwIcon data-icon="inline-start" />
            {isLoading ? "刷新中" : "刷新"}
          </Button>
        </div>
      </div>
      {outTradeNo ? (
        <Badge variant="outline" className="w-fit max-w-full truncate">
          订单 {outTradeNo}
        </Badge>
      ) : null}
      {errorMessage ? <SupplyActionNotice result={{ kind: "error", message: errorMessage }} /> : null}
      {!observability && !isLoading && !errorMessage ? (
        <StatusBlock title="暂无观测数据" detail="刷新后可查看最近的支付回调和外部履约记录。" />
      ) : null}
      {observability && !hasItems ? (
        <StatusBlock title="暂无异常记录" detail="当前筛选范围内没有失败回调、拒绝回调或外部履约尝试。" />
      ) : null}
      {observability ? (
        <div className="grid gap-3 xl:grid-cols-3">
          <DiagnosticSection title="回调失败">
            {observability.callback_failures.length > 0 ? (
              observability.callback_failures.map((item, index) => (
                <div key={`${item.out_trade_no}:${item.created_at}:${index}`} className="rounded-md border p-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-medium">{item.out_trade_no}</span>
                    <Badge variant="outline">{callbackStatusLabel(item.process_status)}</Badge>
                  </div>
                  <div className="mt-2 flex flex-col gap-1">
                    <MetricLine label="通道" value={item.provider} />
                    <MetricLine label="订单状态" value={orderStatusLabel(item.order_status)} />
                    <MetricLine label="创建" value={formatDateTime(item.created_at)} />
                    <MetricLine label="处理" value={item.processed_at ? formatDateTime(item.processed_at) : "-"} />
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">{item.failure_reason}</p>
                </div>
              ))
            ) : (
              <StatusBlock title="暂无失败回调" detail="没有最近处理失败的支付回调。" />
            )}
          </DiagnosticSection>
          <DiagnosticSection title="回调拒绝">
            {observability.callback_rejections.length > 0 ? (
              observability.callback_rejections.map((item, index) => (
                <div key={`${item.provider}:${item.created_at}:${index}`} className="rounded-md border p-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-medium">{item.out_trade_no ?? "未关联订单"}</span>
                    <Badge variant="outline">{item.http_status}</Badge>
                  </div>
                  <div className="mt-2 flex flex-col gap-1">
                    <MetricLine label="通道" value={item.provider} />
                    <MetricLine label="原因" value={paymentCallbackRejectionLabel(item.reason_category)} />
                    <MetricLine label="字段数" value={String(item.payload_field_count)} />
                    <MetricLine label="创建" value={formatDateTime(item.created_at)} />
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">{item.failure_reason}</p>
                </div>
              ))
            ) : (
              <StatusBlock title="暂无拒绝回调" detail="没有最近被拒绝的支付回调。" />
            )}
          </DiagnosticSection>
          <DiagnosticSection title="外部履约">
            {observability.external_fulfillment_attempts.length > 0 ? (
              observability.external_fulfillment_attempts.map((item, index) => (
                <div key={`${item.out_trade_no}:${item.created_at}:${index}`} className="rounded-md border p-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-medium">{item.out_trade_no}</span>
                    <Badge variant={item.status === "succeeded" || item.status === "imported" ? "secondary" : "outline"}>
                      {externalFulfillmentAttemptStatusLabel(item.status)}
                    </Badge>
                  </div>
                  <div className="mt-2 flex flex-col gap-1">
                    <MetricLine label="来源" value={`${item.provider_name}/${item.source_key || "-"}`} />
                    <MetricLine label="触发" value={externalFulfillmentAttemptSourceLabel(item.attempt_source)} />
                    <MetricLine label="导入" value={item.imported ? "已导入" : "未导入"} />
                    <MetricLine label="条目" value={String(item.item_count)} />
                    <MetricLine label="上游状态" value={item.upstream_status_code?.toString() ?? "-"} />
                    <MetricLine label="完成" value={formatDateTime(item.finished_at)} />
                  </div>
                  {item.failure_reason ? (
                    <p className="mt-2 text-xs text-muted-foreground">{item.failure_reason}</p>
                  ) : null}
                </div>
              ))
            ) : (
              <StatusBlock title="暂无履约尝试" detail="没有最近的外部货源履约尝试。" />
            )}
          </DiagnosticSection>
        </div>
      ) : null}
    </div>
  )
}

function OrderDiagnosticsPanel({ diagnostics }: { diagnostics: AdminWebTenantOrderDiagnostics }) {
  const callbackEntries = Object.entries(diagnostics.callback_status_counts)

  return (
    <div className="flex flex-col gap-3 rounded-md border bg-muted/30 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">订单排障</p>
          <p className="mt-1 truncate text-xs text-muted-foreground">{diagnostics.out_trade_no}</p>
        </div>
        <Badge variant={diagnostics.status === "delivered" ? "secondary" : "outline"}>
          {orderStatusLabel(diagnostics.status)}
        </Badge>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <MetricLine label="金额" value={`${diagnostics.amount} ${diagnostics.currency}`} />
        <MetricLine label="来源" value={sourceTypeLabel(diagnostics.source_type)} />
        <MetricLine label="支付模式" value={paymentModeLabel(diagnostics.payment_mode)} />
        <MetricLine label="支付通道" value={diagnostics.payment_provider ?? "-"} />
        <MetricLine label="创建" value={formatDateTime(diagnostics.created_at)} />
        <MetricLine label="过期" value={formatDateTime(diagnostics.expires_at)} />
      </div>
      <Separator />
      <div className="grid gap-3 lg:grid-cols-2">
        <DiagnosticSection title="支付记录">
          <MetricLine label="记录数" value={String(diagnostics.payment_count)} />
          {diagnostics.payments.length > 0 ? (
            diagnostics.payments.map((payment, index) => (
              <div key={`${payment.provider}:${payment.created_at}:${index}`} className="rounded-md border p-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium">{payment.provider}</span>
                  <Badge variant={payment.status === "paid" ? "secondary" : "outline"}>
                    {orderPaymentStatusLabel(payment.status)}
                  </Badge>
                </div>
                <div className="mt-2 flex flex-col gap-1">
                  <MetricLine label="金额" value={`${payment.amount} ${payment.currency}`} />
                  <MetricLine label="支付页" value={payment.has_payment_url ? "已生成" : "未生成"} />
                  <MetricLine label="创建" value={formatDateTime(payment.created_at)} />
                </div>
              </div>
            ))
          ) : (
            <StatusBlock title="暂无支付记录" detail="该订单还没有支付建链记录。" />
          )}
        </DiagnosticSection>
        <DiagnosticSection title="回调记录">
          <MetricLine label="记录数" value={String(diagnostics.callback_count)} />
          {callbackEntries.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {callbackEntries.map(([status, count]) => (
                <Badge key={status} variant="outline">
                  {callbackStatusLabel(status)} {count}
                </Badge>
              ))}
            </div>
          ) : null}
          {diagnostics.callbacks.length > 0 ? (
            diagnostics.callbacks.map((callback, index) => (
              <div key={`${callback.provider}:${callback.created_at}:${index}`} className="rounded-md border p-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium">{callback.provider}</span>
                  <Badge variant={callback.process_status === "processed" ? "secondary" : "outline"}>
                    {callbackStatusLabel(callback.process_status)}
                  </Badge>
                </div>
                <p className="mt-2 text-xs text-muted-foreground">{callback.failure_reason}</p>
                <div className="mt-2 flex flex-col gap-1">
                  <MetricLine label="创建" value={formatDateTime(callback.created_at)} />
                  <MetricLine label="处理" value={callback.processed_at ? formatDateTime(callback.processed_at) : "-"} />
                </div>
              </div>
            ))
          ) : (
            <StatusBlock title="暂无回调记录" detail="支付通道还没有回调到该订单。" />
          )}
        </DiagnosticSection>
      </div>
      <div className="grid gap-3 lg:grid-cols-3">
        <DiagnosticSection title="发货">
          {diagnostics.delivery ? (
            <>
              <MetricLine label="类型" value={deliveryTypeLabel(diagnostics.delivery.delivery_type)} />
              <MetricLine label="状态" value={deliveryStatusLabel(diagnostics.delivery.status)} />
              <MetricLine label="库存" value={diagnostics.delivery.has_inventory_item ? "已关联" : "未关联"} />
              <MetricLine label="文件" value={diagnostics.delivery.has_uploaded_file ? "已关联" : "未关联"} />
              <MetricLine label="群组" value={diagnostics.delivery.has_telegram_chat ? "已关联" : "未关联"} />
              <MetricLine label="更新" value={formatDateTime(diagnostics.delivery.updated_at)} />
              {diagnostics.delivery.failure_reason ? (
                <p className="text-xs text-muted-foreground">{diagnostics.delivery.failure_reason}</p>
              ) : null}
            </>
          ) : (
            <StatusBlock title="暂无发货记录" detail="该订单还没有创建发货记录。" />
          )}
        </DiagnosticSection>
        <DiagnosticSection title="外部履约">
          <MetricLine label="需要履约" value={diagnostics.external_fulfillment.expected ? "是" : "否"} />
          <MetricLine label="尝试次数" value={String(diagnostics.external_fulfillment.attempt_count)} />
          <MetricLine label="最近状态" value={diagnostics.external_fulfillment.latest_attempt_status ?? "-"} />
          <MetricLine label="触发" value={diagnostics.external_fulfillment.latest_attempt_trigger ?? "-"} />
          <MetricLine label="上游状态" value={diagnostics.external_fulfillment.latest_upstream_status_code?.toString() ?? "-"} />
          <MetricLine label="返回条目" value={String(diagnostics.external_fulfillment.latest_item_count)} />
          <MetricLine label="已连发货" value={diagnostics.external_fulfillment.latest_delivery_record_linked ? "是" : "否"} />
        </DiagnosticSection>
        <DiagnosticSection title="TRC20 直付">
          <MetricLine label="需要匹配" value={diagnostics.trc20_direct.expected ? "是" : "否"} />
          <MetricLine label="转账数" value={String(diagnostics.trc20_direct.transfer_count)} />
          <MetricLine label="最近匹配" value={diagnostics.trc20_direct.latest_match_status ?? "-"} />
          <MetricLine label="确认数" value={diagnostics.trc20_direct.latest_confirmations?.toString() ?? "-"} />
          <MetricLine label="金额" value={diagnostics.trc20_direct.latest_amount ? `${diagnostics.trc20_direct.latest_amount} ${diagnostics.currency}` : "-"} />
          <MetricLine label="匹配时间" value={diagnostics.trc20_direct.latest_matched_at ? formatDateTime(diagnostics.trc20_direct.latest_matched_at) : "-"} />
        </DiagnosticSection>
      </div>
    </div>
  )
}

function DiagnosticSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2 rounded-md border bg-background p-3">
      <p className="text-sm font-medium">{title}</p>
      {children}
    </div>
  )
}

function CloneBotOverviewContent({ overview }: { overview: AdminWebTenantOverview }) {
  const metrics = [
    {
      label: "商品",
      value: String(overview.products.total_count),
      detail: `上架 ${overview.products.published_count} · 库存 ${overview.products.available_inventory_count}`,
    },
    {
      label: "订单",
      value: String(overview.orders.total_count),
      detail: `待付 ${overview.orders.pending_count} · 已付 ${overview.orders.paid_count}`,
    },
    {
      label: "支付",
      value: `${overview.payments.enabled_count}/${overview.payments.total_count}`,
      detail: "EPUSDT / 易支付兼容",
    },
    {
      label: "供货代理",
      value: `${overview.supply.supplier_offer_count}/${overview.supply.reseller_product_count}`,
      detail: "供货商品 / 代理商品",
    },
  ]

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {metrics.map((metric) => (
          <div key={metric.label} className="rounded-md border p-3">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-medium">{metric.label}</p>
              <Badge variant="outline">{metric.value}</Badge>
            </div>
            <p className="mt-2 truncate text-xs text-muted-foreground">{metric.detail}</p>
          </div>
        ))}
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-md border p-3">
          <p className="text-sm font-medium">近期主支付通道</p>
          <div className="mt-3 flex flex-col gap-2">
            {overview.payments.providers.map((provider) => (
              <div
                key={provider.provider_name}
                className="flex items-center justify-between gap-3"
              >
                <span className="truncate text-sm text-muted-foreground">
                  {provider.display_name}
                </span>
                <Badge variant={provider.enabled ? "secondary" : "outline"}>
                  {provider.enabled ? "已启用" : "未启用"}
                </Badge>
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-md border p-3">
          <p className="text-sm font-medium">店铺能力</p>
          <div className="mt-3 flex flex-col gap-2">
            <MetricLine label="供应商" value={overview.supply.supplier_enabled ? "开启" : "关闭"} />
            <MetricLine label="代理商" value={overview.supply.reseller_enabled ? "开启" : "关闭"} />
            <MetricLine label="套餐" value={overview.subscription.plan_code ?? "-"} />
          </div>
        </div>
      </div>
    </div>
  )
}

function CloneBotStoreSettingsForm({
  settings,
  actionId,
  actionResult,
  onUpdateStoreSettings,
}: {
  settings: AdminWebTenantStoreSettings
  actionId: string | null
  actionResult: SupplyActionResult | null
  onUpdateStoreSettings: (payload: AdminWebTenantStoreSettingsPayload) => void
}) {
  const [storeName, setStoreName] = React.useState(settings.store_name)
  const [welcomeText, setWelcomeText] = React.useState(settings.welcome_text)
  const [supportText, setSupportText] = React.useState(settings.support_text)
  const [orderTimeoutMinutes, setOrderTimeoutMinutes] = React.useState(
    String(settings.order_timeout_minutes),
  )
  const [selfSaleEnabled, setSelfSaleEnabled] = React.useState(settings.self_sale_enabled)
  const [supplierEnabled, setSupplierEnabled] = React.useState(settings.supplier_enabled)
  const [resellerEnabled, setResellerEnabled] = React.useState(settings.reseller_enabled)
  const isBusy = actionId === "store-settings:update"

  React.useEffect(() => {
    setStoreName(settings.store_name)
    setWelcomeText(settings.welcome_text)
    setSupportText(settings.support_text)
    setOrderTimeoutMinutes(String(settings.order_timeout_minutes))
    setSelfSaleEnabled(settings.self_sale_enabled)
    setSupplierEnabled(settings.supplier_enabled)
    setResellerEnabled(settings.reseller_enabled)
  }, [settings])

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onUpdateStoreSettings({
      store_name: storeName,
      welcome_text: welcomeText,
      support_text: supportText,
      order_timeout_minutes: Number(orderTimeoutMinutes),
      self_sale_enabled: selfSaleEnabled,
      supplier_enabled: supplierEnabled,
      reseller_enabled: resellerEnabled,
    })
  }

  return (
    <form className="flex flex-col gap-3 rounded-md border p-3" onSubmit={handleSubmit}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-sm font-medium">店铺设置</p>
          <p className="mt-1 text-xs text-muted-foreground">
            管理当前克隆 Bot 的基础信息、店铺功能开关和订单超时。
          </p>
        </div>
        <Badge variant="outline">{settings.order_timeout_minutes} 分钟</Badge>
      </div>
      {actionResult ? <SupplyActionNotice result={actionResult} /> : null}
      <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_12rem]">
        <Input
          value={storeName}
          aria-label="店铺名称"
          placeholder="店铺名称"
          disabled={isBusy}
          maxLength={64}
          onChange={(event) => setStoreName(event.target.value)}
        />
        <Input
          value={orderTimeoutMinutes}
          aria-label="订单超时分钟"
          placeholder="订单超时分钟"
          inputMode="numeric"
          disabled={isBusy}
          onChange={(event) => setOrderTimeoutMinutes(event.target.value)}
        />
      </div>
      <div className="grid gap-2 md:grid-cols-2">
        <textarea
          value={welcomeText}
          aria-label="欢迎语"
          placeholder="欢迎语"
          className="min-h-24 rounded-md border bg-background px-3 py-2 text-sm outline-none ring-offset-background placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={isBusy}
          maxLength={500}
          onChange={(event) => setWelcomeText(event.target.value)}
        />
        <textarea
          value={supportText}
          aria-label="客服信息"
          placeholder="客服信息"
          className="min-h-24 rounded-md border bg-background px-3 py-2 text-sm outline-none ring-offset-background placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={isBusy}
          maxLength={300}
          onChange={(event) => setSupportText(event.target.value)}
        />
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        <FeatureFlagToggle
          label="自营"
          description="允许销售本店自营商品"
          enabled={selfSaleEnabled}
          disabled={isBusy}
          onToggle={() => setSelfSaleEnabled((current) => !current)}
        />
        <FeatureFlagToggle
          label="供货"
          description="允许把自营商品开放给代理商"
          enabled={supplierEnabled}
          disabled={isBusy}
          onToggle={() => setSupplierEnabled((current) => !current)}
        />
        <FeatureFlagToggle
          label="代理"
          description="允许从供货市场选择商品并销售"
          enabled={resellerEnabled}
          disabled={isBusy}
          onToggle={() => setResellerEnabled((current) => !current)}
        />
      </div>
      <div className="flex justify-end">
        <Button type="submit" size="sm" disabled={isBusy}>
          {isBusy ? "正在保存" : "保存店铺设置"}
        </Button>
      </div>
    </form>
  )
}

function FeatureFlagToggle({
  label,
  description,
  enabled,
  disabled,
  onToggle,
}: {
  label: string
  description: string
  enabled: boolean
  disabled: boolean
  onToggle: () => void
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border p-3">
      <div className="min-w-0">
        <p className="text-sm font-medium">{label}</p>
        <p className="mt-1 text-xs text-muted-foreground">{description}</p>
      </div>
      <Button
        type="button"
        size="sm"
        variant={enabled ? "secondary" : "outline"}
        disabled={disabled}
        aria-pressed={enabled}
        onClick={onToggle}
      >
        {enabled ? "已开启" : "已关闭"}
      </Button>
    </div>
  )
}

function StatusBlock({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="rounded-md border p-3">
      <p className="text-sm font-medium">{title}</p>
      <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
    </div>
  )
}

function MetricLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="max-w-40 truncate text-sm font-medium">{value}</span>
    </div>
  )
}

function PartnerEntrances({
  currentWorkspace,
}: {
  currentWorkspace?: AdminWebWorkspace
}) {
  const isTenantWorkspace = currentWorkspace?.kind === "tenant"

  return (
    <section className="grid gap-4 lg:grid-cols-2">
      {partnerCards.map((item) => {
        const Icon = item.icon

        return (
          <Card key={item.title}>
            <CardHeader>
              <div className="flex items-start justify-between gap-4">
                <div className="flex flex-col gap-1.5">
                  <CardTitle>{item.title}</CardTitle>
                  <CardDescription>{item.description}</CardDescription>
                </div>
                <div className="flex size-10 items-center justify-center rounded-md bg-accent text-accent-foreground">
                  <Icon />
                </div>
              </div>
            </CardHeader>
            <CardFooter>
              <Button variant="outline" disabled={!isTenantWorkspace}>
                {item.action}
                <ChevronRightIcon data-icon="inline-end" />
              </Button>
            </CardFooter>
          </Card>
        )
      })}
    </section>
  )
}

export function AdminShell() {
  const [session, setSession] = React.useState<AdminWebSession | null>(null)
  const [isLoading, setIsLoading] = React.useState(true)
  const [isSelecting, setIsSelecting] = React.useState(false)
  const [isBindingCodeSubmitting, setIsBindingCodeSubmitting] = React.useState(false)
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null)
  const [bindingCodeError, setBindingCodeError] = React.useState<string | null>(null)
  const [activeView, setActiveView] = React.useState<AdminView>("Bot工作台")

  const loadSession = React.useCallback(async () => {
    setIsLoading(true)
    setErrorMessage(null)

    try {
      const nextSession = await getAdminWebSession()
      const workspaces = await getAdminWebWorkspaces()
      setSession({ ...nextSession, workspaces })
    } catch (error) {
      if (error instanceof AdminWebApiError && error.status === 401) {
        const launchContext = readTelegramLaunchContext()
        if (!launchContext) {
          setSession(null)
          return
        }

        try {
          const nextSession = await createTelegramAdminWebSession(launchContext)
          setSession(nextSession)
          return
        } catch (loginError) {
          setSession(null)
          setErrorMessage(errorToMessage(loginError))
          return
        }
      }

      setSession(null)
      setErrorMessage(errorToMessage(error))
    } finally {
      setIsLoading(false)
    }
  }, [])

  React.useEffect(() => {
    prepareTelegramWebApp()
    void loadSession()
  }, [loadSession])

  const workspaces = session?.workspaces ?? []
  const currentWorkspace = workspaces.find(
    (workspace) => workspace.workspace_id === session?.current_workspace_id,
  )
  const platformWorkspace = workspaces.find((workspace) => workspace.kind === "platform")
  const summaryItems = buildSummaryItems(workspaces)

  async function handleSelectWorkspace(workspaceId: string) {
    if (workspaceId === session?.current_workspace_id) {
      return
    }

    setIsSelecting(true)
    setErrorMessage(null)
    try {
      const nextSession = await selectAdminWebWorkspace(workspaceId)
      setSession(nextSession)
      setActiveView("Bot工作台")
    } catch (error) {
      setErrorMessage(errorToMessage(error))
    } finally {
      setIsSelecting(false)
    }
  }

  async function handleLogout() {
    setIsSelecting(true)
    setErrorMessage(null)
    try {
      await logoutAdminWebSession()
      setSession(null)
    } catch (error) {
      setErrorMessage(errorToMessage(error))
    } finally {
      setIsSelecting(false)
    }
  }

  async function handleBindingCodeLogin(code: string) {
    setIsBindingCodeSubmitting(true)
    setBindingCodeError(null)
    setErrorMessage(null)
    try {
      const nextSession = await createBindingCodeAdminWebSession({ code })
      setSession(nextSession)
    } catch (error) {
      setSession(null)
      setBindingCodeError(errorToMessage(error))
    } finally {
      setIsBindingCodeSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="flex min-h-screen">
        <Sidebar
          currentWorkspace={currentWorkspace}
          activeView={activeView}
          onViewChange={setActiveView}
        />
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="border-b bg-background">
            <div className="flex min-h-16 flex-col gap-3 px-4 py-3 md:flex-row md:items-center md:justify-between md:px-6">
              <div className="flex min-w-0 flex-col gap-1">
                <p className="truncate text-sm font-medium">当前 Bot 工作区</p>
                <p className="truncate text-xs text-muted-foreground">
                  主 Bot 与克隆 Bot 管理
                </p>
              </div>
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <WorkspaceSelect
                  workspaces={workspaces}
                  currentWorkspaceId={session?.current_workspace_id}
                  isLoading={isLoading}
                  isSelecting={isSelecting}
                  onSelect={handleSelectWorkspace}
                />
                <Button variant="outline" disabled={!session || isSelecting} onClick={handleLogout}>
                  退出登录
                </Button>
                <Button disabled={!session || isSelecting}>
                  <PlusIcon data-icon="inline-start" />
                  绑定 Bot
                </Button>
              </div>
            </div>
          </header>

          <main className="flex-1">
            <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 p-4 md:p-6 lg:p-8">
              <MobileNav activeView={activeView} onViewChange={setActiveView} />

              {errorMessage ? <ErrorCard message={errorMessage} onRetry={loadSession} /> : null}

              {!isLoading && !session && !errorMessage ? (
                <UnauthenticatedCard
                  isSubmitting={isBindingCodeSubmitting}
                  errorMessage={bindingCodeError}
                  onSubmitCode={handleBindingCodeLogin}
                  onRetry={loadSession}
                />
              ) : null}

              <section className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
                <div className="flex max-w-3xl flex-col gap-2">
                  <Badge variant="outline" className="w-fit">
                    {currentWorkspace
                      ? workspaceKindLabel(currentWorkspace.kind)
                      : "管理后台"}
                  </Badge>
                  <h1 className="text-2xl font-semibold md:text-3xl">
                    {viewTitles[activeView].title}
                  </h1>
                  <p className="text-sm text-muted-foreground">
                    {viewTitles[activeView].description}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button variant="outline">
                    <WebhookIcon data-icon="inline-start" />
                    接口状态
                  </Button>
                  <Button variant="secondary" disabled={!platformWorkspace}>
                    <Building2Icon data-icon="inline-start" />
                    租户列表
                  </Button>
                </div>
              </section>

              <SummaryGrid items={summaryItems} />

              {activeView === "Bot工作台" ? (
                <Tabs defaultValue="primary" className="flex flex-col gap-4">
                  <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                    <TabsList>
                      <TabsTrigger value="primary">主 Bot</TabsTrigger>
                      <TabsTrigger value="clone">克隆 Bot</TabsTrigger>
                    </TabsList>
                    <Badge variant="secondary" className="w-fit">
                      工作区隔离
                    </Badge>
                  </div>
                  <TabsContent value="primary">
                    <PrimaryBotPanel
                      platformWorkspace={platformWorkspace}
                      user={session?.user}
                      workspaces={workspaces}
                    />
                  </TabsContent>
                  <TabsContent value="clone">
                    <CloneBotPanel currentWorkspace={currentWorkspace} />
                  </TabsContent>
                </Tabs>
              ) : currentWorkspace?.kind === "platform" ? (
                <PrimaryBotPanel
                  platformWorkspace={platformWorkspace}
                  user={session?.user}
                  workspaces={workspaces}
                  view={activeView}
                />
              ) : currentWorkspace?.kind === "tenant" ? (
                <CloneBotPanel currentWorkspace={currentWorkspace} view={activeView} />
              ) : (
                <Card>
                  <CardHeader>
                    <CardTitle>请先选择工作区</CardTitle>
                    <CardDescription>
                      从顶部工作区选择器切换到平台或店铺工作区后再查看该页面。
                    </CardDescription>
                  </CardHeader>
                </Card>
              )}

              <PartnerEntrances currentWorkspace={currentWorkspace} />
            </div>
          </main>
        </div>
      </div>
    </div>
  )
}

function ErrorCard({
  message,
  onRetry,
}: {
  message: string
  onRetry: () => void
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>请求失败</CardTitle>
        <CardDescription>{message}</CardDescription>
      </CardHeader>
      <CardFooter>
        <Button variant="outline" onClick={onRetry}>
          重新加载
        </Button>
      </CardFooter>
    </Card>
  )
}

function UnauthenticatedCard({
  isSubmitting,
  errorMessage,
  onSubmitCode,
  onRetry,
}: {
  isSubmitting: boolean
  errorMessage: string | null
  onSubmitCode: (code: string) => void
  onRetry: () => void
}) {
  const [code, setCode] = React.useState("")

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const normalizedCode = code.trim()
    if (!normalizedCode) {
      return
    }
    onSubmitCode(normalizedCode)
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>使用一次性绑定码登录</CardTitle>
        <CardDescription>
          请从 Telegram 主 Bot 或克隆 Bot 打开管理后台。
        </CardDescription>
      </CardHeader>
      <form onSubmit={handleSubmit}>
        <CardContent className="flex flex-col gap-3">
          <Input
            value={code}
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={16}
            aria-label="一次性绑定码"
            placeholder="输入绑定码"
            disabled={isSubmitting}
            onChange={(event) => setCode(event.target.value)}
          />
          {errorMessage ? (
            <p className="text-sm text-muted-foreground">{errorMessage}</p>
          ) : null}
        </CardContent>
        <CardFooter className="flex flex-col gap-2 sm:flex-row">
          <Button type="submit" disabled={isSubmitting || !code.trim()}>
            {isSubmitting ? "正在登录" : "登录"}
          </Button>
          <Button type="button" variant="outline" disabled={isSubmitting} onClick={onRetry}>
            重新检测
          </Button>
        </CardFooter>
      </form>
    </Card>
  )
}

function buildSummaryItems(workspaces: AdminWebWorkspace[]): SummaryItem[] {
  const tenantWorkspaces = workspaces.filter((workspace) => workspace.kind === "tenant")

  return [
    {
      label: "主 Bot",
      value: String(workspaces.filter((workspace) => workspace.kind === "platform").length),
      detail: "平台管理",
      badge: "平台",
    },
    {
      label: "克隆 Bot",
      value: String(tenantWorkspaces.length),
      detail: "店铺工作区",
      badge: "店铺",
    },
    {
      label: "供应商",
      value: String(tenantWorkspaces.filter((workspace) => workspace.supplier_enabled).length),
      detail: "供货店铺",
      badge: "供货",
    },
    {
      label: "代理商",
      value: String(tenantWorkspaces.filter((workspace) => workspace.reseller_enabled).length),
      detail: "代理店铺",
      badge: "代理",
    },
  ]
}

function workspaceKindLabel(kind: string): string {
  if (kind === "platform") {
    return "主 Bot"
  }
  if (kind === "tenant") {
    return "克隆 Bot"
  }
  return "工作区"
}

function workspaceStatusLabel(workspace: AdminWebWorkspace): string {
  if (workspace.kind === "platform") {
    return "可管理"
  }
  return workspace.bot_status ?? workspace.tenant_status ?? "未知"
}

function roleLabel(role: string): string {
  if (role === "owner") {
    return "Owner"
  }
  if (role === "admin") {
    return "Admin"
  }
  if (role === "platform_admin") {
    return "平台管理员"
  }
  return role
}

function normalizeTenantProductFilters(filters: AdminWebTenantProductFilters): AdminWebTenantProductFilters {
  return {
    limit: tenantListPageSize,
    offset: normalizeListOffset(filters.offset),
    query: normalizeOptionalText(filters.query),
    category: normalizeOptionalText(filters.category),
    status: normalizeProductStatusFilter(filters.status),
    delivery_type: normalizeProductDeliveryTypeFilter(filters.delivery_type),
  }
}

function normalizeTenantOrderFilters(filters: AdminWebTenantOrderFilters): AdminWebTenantOrderFilters {
  return {
    limit: tenantListPageSize,
    offset: normalizeListOffset(filters.offset),
    out_trade_no: normalizeOptionalText(filters.out_trade_no),
    status: normalizeOrderStatusFilter(filters.status),
    source_type: normalizeOrderSourceTypeFilter(filters.source_type),
    payment_mode: normalizeOrderPaymentModeFilter(filters.payment_mode),
  }
}

function normalizedOrderObservationTradeNo(value: string | undefined): string | undefined {
  return normalizeOptionalText(value)
}

function normalizeListOffset(offset: number | undefined): number {
  const numericOffset = Number(offset ?? 0)
  if (!Number.isFinite(numericOffset)) {
    return 0
  }
  return Math.max(0, Math.floor(numericOffset))
}

function normalizeOptionalText(value: string | undefined): string | undefined {
  const text = value?.trim()
  return text ? text : undefined
}

function normalizeProductStatusFilter(status: string | undefined): NonNullable<AdminWebTenantProductFilters["status"]> {
  if (status === "draft" || status === "on" || status === "off") {
    return status
  }
  return "all"
}

function normalizeProductDeliveryTypeFilter(
  deliveryType: string | undefined,
): NonNullable<AdminWebTenantProductFilters["delivery_type"]> {
  if (
    deliveryType === "card_pool" ||
    deliveryType === "card_fixed" ||
    deliveryType === "telegram_invite" ||
    deliveryType === "file_download"
  ) {
    return deliveryType
  }
  return "all"
}

function normalizeOrderStatusFilter(status: string | undefined): NonNullable<AdminWebTenantOrderFilters["status"]> {
  if (
    status === "pending" ||
    status === "paid" ||
    status === "delivered" ||
    status === "expired" ||
    status === "completed" ||
    status === "refunded" ||
    status === "partially_refunded"
  ) {
    return status
  }
  return "all"
}

function normalizeOrderSourceTypeFilter(
  sourceType: string | undefined,
): NonNullable<AdminWebTenantOrderFilters["source_type"]> {
  if (sourceType === "self" || sourceType === "reseller" || sourceType === "subscription") {
    return sourceType
  }
  return "all"
}

function normalizeOrderPaymentModeFilter(
  paymentMode: string | undefined,
): NonNullable<AdminWebTenantOrderFilters["payment_mode"]> {
  if (
    paymentMode === "tenant_direct" ||
    paymentMode === "platform_escrow" ||
    paymentMode === "platform_subscription"
  ) {
    return paymentMode
  }
  return "all"
}

function productStatusLabel(status: string): string {
  if (status === "on") {
    return "上架"
  }
  if (status === "off") {
    return "下架"
  }
  if (status === "draft") {
    return "草稿"
  }
  return status
}

function normalizeProductStatus(status: string): AdminWebProductSalesPayload["status"] {
  if (status === "on" || status === "off" || status === "draft") {
    return status
  }
  return "draft"
}

function validatePlatformPlanDraft(
  draft: PlatformPlanDraft,
  options: { requireCode: boolean },
): PlatformPlanFieldErrors {
  const errors: PlatformPlanFieldErrors = {}
  const code = draft.code?.trim() ?? ""
  const name = draft.name.trim()
  const monthlyPrice = draft.monthlyPrice.trim()

  if (options.requireCode) {
    if (!code) {
      errors.code = "计划代码必填"
    } else if (code.length > 64) {
      errors.code = "计划代码最多 64 位"
    }
  }

  if (!name) {
    errors.name = "计划名称必填"
  } else if (name.length > 128) {
    errors.name = "计划名称最多 128 位"
  }

  if (!monthlyPrice) {
    errors.monthlyPrice = "月费必填"
  } else if (!isNonNegativeDecimalText(monthlyPrice)) {
    errors.monthlyPrice = "月费必须是非负金额，最多 8 位小数"
  }

  const trialDaysError = platformPlanIntegerFieldError(draft.trialDays, "试用天数", 3650)
  if (trialDaysError) {
    errors.trialDays = trialDaysError
  }
  const graceDaysError = platformPlanIntegerFieldError(draft.graceDays, "宽限天数", 365)
  if (graceDaysError) {
    errors.graceDays = graceDaysError
  }

  return errors
}

function platformPlanFieldErrorList(errors: PlatformPlanFieldErrors): string[] {
  const fields: PlatformPlanFieldKey[] = ["code", "name", "monthlyPrice", "trialDays", "graceDays"]
  return fields
    .map((field) => errors[field])
    .filter((error): error is string => Boolean(error))
}

function platformPlanIntegerFieldError(value: string, label: string, max: number): string | null {
  const normalized = value.trim()
  if (!normalized) {
    return `${label}必填`
  }
  if (!/^\d+$/.test(normalized)) {
    return `${label}必须是整数`
  }
  const numericValue = Number(normalized)
  if (!Number.isSafeInteger(numericValue) || numericValue > max) {
    return `${label}范围为 0-${max}`
  }
  return null
}

function hasPlatformPlanDraftChanges(
  plan: AdminWebPlatformDashboard["subscription_plans"][number],
  draft: PlatformPlanDraft,
): boolean {
  return (
    draft.name.trim() !== plan.name ||
    draft.monthlyPrice.trim() !== plan.monthly_price ||
    draft.trialDays.trim() !== String(plan.trial_days) ||
    draft.graceDays.trim() !== String(plan.grace_days)
  )
}

function createPlatformWithdrawalReviewDraft(): PlatformWithdrawalReviewDraft {
  return {
    rejectNote: "",
    completeNote: "",
    payoutReference: "",
    payoutProofUrl: "",
  }
}

function validatePlatformWithdrawalReviewDraft(
  draft: PlatformWithdrawalReviewDraft,
): PlatformWithdrawalReviewErrors {
  const errors: PlatformWithdrawalReviewErrors = {}
  if (draft.rejectNote.length > 500) {
    errors.rejectNote = "拒绝备注最多 500 字"
  }
  if (draft.completeNote.length > 500) {
    errors.completeNote = "完成备注最多 500 字"
  }
  if (draft.payoutReference.length > 128) {
    errors.payoutReference = "付款参考最多 128 字"
  }
  if (draft.payoutProofUrl.length > 1000) {
    errors.payoutProofUrl = "凭证 URL 最多 1000 字"
  }
  return errors
}

function platformWithdrawalReviewErrorList(
  errors: PlatformWithdrawalReviewErrors,
  fields: PlatformWithdrawalReviewFieldKey[],
): string[] {
  return fields
    .map((field) => errors[field])
    .filter((error): error is string => Boolean(error))
}

function platformWithdrawalRejectErrorList(
  draft: PlatformWithdrawalReviewDraft,
  errors: PlatformWithdrawalReviewErrors,
): string[] {
  const result = platformWithdrawalReviewErrorList(errors, ["rejectNote"])
  if (!draft.rejectNote.trim()) {
    result.unshift("拒绝备注必填")
  }
  return result
}

function isPlatformWithdrawalPending(withdrawal: AdminWebPlatformWithdrawal): boolean {
  return withdrawal.status === "pending"
}

function platformSupplierOfferMatchesQuery(offer: AdminWebPlatformSupplierOffer, query: string): boolean {
  const normalizedQuery = query.trim().toLowerCase()
  if (!normalizedQuery) {
    return true
  }
  return [
    offer.product_name,
    offer.supplier_store_name,
    offer.delivery_type,
    deliveryTypeLabel(offer.delivery_type),
    offer.status,
    supplierOfferStatusLabel(offer.status),
    platformSupplierOfferApprovalLabel(offer),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase()
    .includes(normalizedQuery)
}

function platformSupplierOfferMatchesStatus(
  offer: AdminWebPlatformSupplierOffer,
  filter: PlatformSupplierOfferStatusFilter,
): boolean {
  if (filter === "all") {
    return true
  }
  return offer.status === filter
}

function platformSupplierOfferMatchesApproval(
  offer: AdminWebPlatformSupplierOffer,
  filter: PlatformSupplierOfferApprovalFilter,
): boolean {
  if (filter === "all") {
    return true
  }
  if (filter === "approval_required") {
    return offer.requires_approval
  }
  return !offer.requires_approval
}

function platformSupplierOfferMatchesStock(
  offer: AdminWebPlatformSupplierOffer,
  filter: PlatformSupplierOfferStockFilter,
): boolean {
  if (filter === "all") {
    return true
  }
  if (filter === "available") {
    return offer.available_count > 0
  }
  return offer.available_count <= 0
}

function platformSupplierOfferApprovalLabel(offer: AdminWebPlatformSupplierOffer): string {
  return offer.requires_approval ? "需审批" : "免审批"
}

function platformSupplierOfferActionReasonError(reason: string): string | null {
  return reason.length > 255 ? "操作原因最多 255 字" : null
}

function isPositiveDecimalText(value: string | undefined): boolean {
  if (value === undefined) {
    return true
  }
  const normalized = value.trim()
  if (!/^(?:0|[1-9]\d*)(?:\.\d{1,8})?$/.test(normalized)) {
    return false
  }
  return !/^0(?:\.0{1,8})?$/.test(normalized)
}

function isNonNegativeDecimalText(value: string | undefined): boolean {
  if (value === undefined) {
    return true
  }
  const normalized = value.trim()
  return /^(?:0|[1-9]\d*)(?:\.\d{1,8})?$/.test(normalized)
}

function parseExternalSourceCredentials(value: string): Record<string, string> {
  const text = value.trim()
  if (!text) {
    throw new Error("请输入至少一项外部源凭据。")
  }

  if (text.startsWith("{")) {
    let parsed: unknown
    try {
      parsed = JSON.parse(text)
    } catch {
      throw new Error("凭据 JSON 格式无效。")
    }
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
      throw new Error("凭据 JSON 必须是对象。")
    }
    const credentials = Object.fromEntries(
      Object.entries(parsed)
        .map(([key, rawValue]) => [key.trim(), normalizeCredentialValue(rawValue)])
        .filter(([key, credentialValue]) => key !== "" && credentialValue !== ""),
    )
    if (Object.keys(credentials).length === 0) {
      throw new Error("请输入至少一项外部源凭据。")
    }
    if (Object.keys(credentials).length > 32) {
      throw new Error("外部源凭据最多 32 项。")
    }
    return credentials
  }

  const credentials: Record<string, string> = {}
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line) {
      continue
    }
    const delimiterIndex = line.indexOf("=")
    if (delimiterIndex <= 0) {
      throw new Error("凭据应使用 key=value，每行一项。")
    }
    const key = line.slice(0, delimiterIndex).trim()
    const credentialValue = line.slice(delimiterIndex + 1).trim()
    if (!key || !credentialValue) {
      throw new Error("凭据键和值不能为空。")
    }
    if (credentials[key] !== undefined) {
      throw new Error("凭据键不能重复。")
    }
    credentials[key] = credentialValue
  }
  if (Object.keys(credentials).length === 0) {
    throw new Error("请输入至少一项外部源凭据。")
  }
  if (Object.keys(credentials).length > 32) {
    throw new Error("外部源凭据最多 32 项。")
  }
  return credentials
}

function normalizeCredentialValue(value: unknown): string {
  if (typeof value === "string") {
    return value.trim()
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value)
  }
  if (value === null || value === undefined) {
    return ""
  }
  throw new Error("凭据 JSON 只支持字符串、数字或布尔值。")
}

function tenantStatusLabel(status: string): string {
  if (status === "trial") {
    return "试用"
  }
  if (status === "active") {
    return "活跃"
  }
  if (status === "grace") {
    return "宽限"
  }
  if (status === "suspended") {
    return "冻结"
  }
  if (status === "retention_expired") {
    return "保留期过期"
  }
  return status
}

function subscriptionStatusLabel(status: string): string {
  if (status === "suspended") {
    return "暂停"
  }
  return tenantStatusLabel(status)
}

function subscriptionStatusBadgeVariant(
  status?: string | null,
): "default" | "secondary" | "destructive" | "outline" {
  if (status === "active") {
    return "secondary"
  }
  if (status === "suspended" || status === "retention_expired") {
    return "destructive"
  }
  return "outline"
}

function subscriptionAttentionReasonLabel(reason: string): string {
  if (reason === "retention_expired") {
    return "保留期过期"
  }
  if (reason === "suspended") {
    return "已暂停"
  }
  if (reason === "grace_expired") {
    return "宽限已过"
  }
  if (reason === "grace") {
    return "宽限中"
  }
  if (reason === "expired") {
    return "已到期"
  }
  if (reason === "expiring_soon") {
    return "即将到期"
  }
  return reason
}

function subscriptionAttentionBadgeVariant(
  reason?: string | null,
): "default" | "secondary" | "destructive" | "outline" {
  if (reason === "retention_expired" || reason === "suspended" || reason === "grace_expired") {
    return "destructive"
  }
  if (reason === "expired" || reason === "grace") {
    return "default"
  }
  if (reason === "expiring_soon") {
    return "secondary"
  }
  return "outline"
}

function platformWebhookStatusLabel(status: string): string {
  if (status === "healthy") {
    return "Webhook 正常"
  }
  if (status === "unknown") {
    return "Webhook 未检查"
  }
  if (status === "error") {
    return "Webhook 异常"
  }
  if (status === "unbound") {
    return "未绑定"
  }
  if (status === "disabled") {
    return "已停用"
  }
  return status
}

function platformRiskAuditActionMatches(action: string, filter: PlatformRiskAuditActionFilter): boolean {
  if (filter === "all") {
    return true
  }
  if (filter === "user") {
    return action.includes(".user_")
  }
  if (filter === "tenant") {
    return action.includes(".tenant_")
  }
  if (filter === "supply") {
    return action.includes(".supplier_offer_") || action.includes(".reseller_product_")
  }
  if (filter === "order") {
    return action.includes(".order_")
  }
  return action.includes(".dispute_") || action.includes(".after_sale_")
}

function platformRiskAuditStatusMatches(
  status: string | null | undefined,
  filter: PlatformRiskAuditStatusFilter,
): boolean {
  if (filter === "all") {
    return true
  }
  const normalizedStatus = status ?? ""
  if (filter === "other") {
    return !["banned", "active", "suspended", "grace", "disabled"].includes(normalizedStatus)
  }
  return normalizedStatus === filter
}

function platformRiskAuditSearchText(log: AdminWebPlatformRiskAuditLog): string {
  return [
    log.action,
    platformRiskAuditActionLabel(log.action),
    log.target_type,
    platformRiskAuditTargetLabel(log.target_type),
    log.actor_username,
    log.actor_telegram_user_id ? `tg ${log.actor_telegram_user_id}` : "",
    log.target_telegram_user_id ? `tg ${log.target_telegram_user_id}` : "",
    log.previous_status,
    platformRiskAuditStatusLabel(log.previous_status),
    log.new_status,
    platformRiskAuditStatusLabel(log.new_status),
    log.reason,
    log.risk_rule,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase()
}

function platformRiskAuditActionLabel(action: string): string {
  if (action === "platform_risk.user_banned") {
    return "手动封禁用户"
  }
  if (action === "platform_risk.user_auto_banned") {
    return "自动封禁用户"
  }
  if (action === "platform_risk.user_unbanned") {
    return "解除用户封禁"
  }
  if (action === "platform_risk.tenant_suspended") {
    return "冻结租户"
  }
  if (action === "platform_risk.tenant_resumed") {
    return "恢复租户"
  }
  if (action === "platform_risk.supplier_offer_disabled") {
    return "供货商品软下架"
  }
  if (action === "platform_risk.reseller_product_disabled") {
    return "代理商品停用"
  }
  if (action === "platform_risk.order_creation_blocked") {
    return "订单创建拦截"
  }
  if (action.startsWith("platform_risk.dispute_")) {
    return "争议风控"
  }
  if (action.startsWith("platform_risk.after_sale_")) {
    return "售后风控"
  }
  return action.startsWith("platform_risk.") ? action.slice("platform_risk.".length) : action
}

function platformRiskAuditTargetLabel(targetType?: string | null): string {
  if (!targetType) {
    return "平台"
  }
  if (targetType === "telegram_user" || targetType === "user") {
    return "Telegram 用户"
  }
  if (targetType === "tenant") {
    return "租户"
  }
  if (targetType === "supplier_offer") {
    return "供货商品"
  }
  if (targetType === "reseller_product") {
    return "代理商品"
  }
  if (targetType === "order") {
    return "订单"
  }
  if (targetType === "dispute") {
    return "争议"
  }
  if (targetType === "after_sale") {
    return "售后"
  }
  return targetType
}

function platformRiskAuditActorLabel(log: AdminWebPlatformRiskAuditLog): string {
  if (log.actor_username) {
    return `@${log.actor_username}`
  }
  if (log.actor_telegram_user_id) {
    return `TG ${log.actor_telegram_user_id}`
  }
  return "系统"
}

function platformRiskAuditStatusLabel(status?: string | null): string {
  if (!status) {
    return "-"
  }
  if (status === "banned") {
    return "已封禁"
  }
  if (status === "active") {
    return "已恢复"
  }
  if (status === "suspended") {
    return "已冻结"
  }
  if (status === "disabled") {
    return "已停用"
  }
  if (status === "grace") {
    return "宽限"
  }
  if (status === "on") {
    return "可用"
  }
  if (status === "pending") {
    return "待处理"
  }
  if (status === "reviewing") {
    return "处理中"
  }
  if (status === "closed") {
    return "已关闭"
  }
  if (status === "refunded") {
    return "已退款"
  }
  return status
}

function platformRiskAuditStatusBadgeVariant(
  status?: string | null,
): "default" | "secondary" | "destructive" | "outline" {
  if (status === "banned" || status === "suspended" || status === "disabled") {
    return "destructive"
  }
  if (status === "active" || status === "grace" || status === "on" || status === "closed" || status === "refunded") {
    return "secondary"
  }
  return "outline"
}

function withdrawalStatusLabel(status: string): string {
  if (status === "pending") {
    return "待审核"
  }
  if (status === "completed") {
    return "已完成"
  }
  if (status === "rejected") {
    return "已拒绝"
  }
  return status
}

function subscriptionInvoiceStatusLabel(status: string): string {
  if (status === "pending") {
    return "待支付"
  }
  if (status === "paid") {
    return "已支付"
  }
  if (status === "failed") {
    return "失败"
  }
  if (status === "expired") {
    return "已超时"
  }
  return status
}

function supplierOfferStatusLabel(status: string): string {
  if (status === "on") {
    return "可供货"
  }
  if (status === "disabled") {
    return "已软下架"
  }
  return status
}

function externalSourceStatusLabel(status: string): string {
  if (status === "active") {
    return "可用"
  }
  if (status === "disabled") {
    return "已停用"
  }
  if (status === "deleted") {
    return "已删除"
  }
  return status
}

function orderStatusLabel(status: string): string {
  if (status === "pending") {
    return "待支付"
  }
  if (status === "paid") {
    return "已支付"
  }
  if (status === "delivered") {
    return "已发货"
  }
  if (status === "completed") {
    return "已完成"
  }
  if (status === "expired") {
    return "已超时"
  }
  if (status === "refunded") {
    return "已退款"
  }
  if (status === "partially_refunded") {
    return "部分退款"
  }
  return status
}

function normalizeTenantRiskStatus(value: string): AdminWebTenantRiskStatusFilter {
  if (
    value === "all" ||
    value === "open" ||
    value === "reviewing" ||
    value === "resolved" ||
    value === "rejected" ||
    value === "closed"
  ) {
    return value
  }
  return "open"
}

function normalizeTenantReportStatus(value: string): AdminWebTenantReportStatusFilter {
  if (
    value === "all" ||
    value === "pending" ||
    value === "running" ||
    value === "completed" ||
    value === "failed" ||
    value === "expired"
  ) {
    return value
  }
  return "all"
}

function normalizeTenantReportTypeFilter(value: string): AdminWebTenantReportTypeFilter {
  if (value === "all") {
    return value
  }
  return normalizeTenantReportType(value)
}

function normalizeTenantReportType(value: string): AdminWebTenantReportType {
  if (value === "payments" || value === "inventory" || value === "ledger") {
    return value
  }
  return "orders"
}

function tenantReportTypeLabel(reportType: string): string {
  if (reportType === "orders") {
    return "订单"
  }
  if (reportType === "payments") {
    return "支付"
  }
  if (reportType === "inventory") {
    return "库存"
  }
  if (reportType === "ledger") {
    return "账务"
  }
  if (reportType === "all") {
    return "全部"
  }
  return reportType
}

function tenantReportStatusLabel(status: string): string {
  if (status === "pending") {
    return "待生成"
  }
  if (status === "running") {
    return "生成中"
  }
  if (status === "completed") {
    return "已完成"
  }
  if (status === "failed") {
    return "失败"
  }
  if (status === "expired") {
    return "已过期"
  }
  if (status === "all") {
    return "全部"
  }
  return status
}

function riskStatusLabel(status: string): string {
  if (status === "open") {
    return "待处理"
  }
  if (status === "reviewing") {
    return "处理中"
  }
  if (status === "resolved") {
    return "已解决"
  }
  if (status === "rejected") {
    return "已拒绝"
  }
  if (status === "closed") {
    return "已关闭"
  }
  if (status === "all") {
    return "全部"
  }
  return status
}

function afterSaleCaseTypeLabel(caseType: string): string {
  if (caseType === "refund") {
    return "退款"
  }
  if (caseType === "complaint") {
    return "投诉"
  }
  if (caseType === "reseller_after_sale") {
    return "代理售后"
  }
  return caseType
}

function orderPaymentStatusLabel(status: string): string {
  if (status === "created") {
    return "已创建"
  }
  if (status === "pending") {
    return "待支付"
  }
  if (status === "paid") {
    return "已支付"
  }
  if (status === "failed") {
    return "失败"
  }
  if (status === "expired") {
    return "已超时"
  }
  return status
}

function callbackStatusLabel(status: string): string {
  if (status === "processed") {
    return "已处理"
  }
  if (status === "failed") {
    return "失败"
  }
  if (status === "rejected") {
    return "已拒绝"
  }
  if (status === "duplicate") {
    return "重复"
  }
  if (status === "pending") {
    return "待处理"
  }
  return status
}

function paymentCallbackRejectionLabel(reasonCategory: string): string {
  if (reasonCategory === "payload_malformed") {
    return "格式异常"
  }
  if (reasonCategory === "invalid_callback") {
    return "参数无效"
  }
  if (reasonCategory === "payment_unavailable") {
    return "支付不可用"
  }
  return reasonCategory
}

function externalFulfillmentAttemptStatusLabel(status: string): string {
  if (status === "started") {
    return "已开始"
  }
  if (status === "running") {
    return "执行中"
  }
  if (status === "succeeded") {
    return "已成功"
  }
  if (status === "already_delivered") {
    return "已发货"
  }
  if (status === "failed") {
    return "失败"
  }
  if (status === "imported") {
    return "已导入"
  }
  return status
}

function externalFulfillmentAttemptSourceLabel(source: string): string {
  if (source === "auto") {
    return "自动"
  }
  if (source === "manual") {
    return "手动"
  }
  return source
}

function deliveryStatusLabel(status: string): string {
  if (status === "pending") {
    return "待发货"
  }
  if (status === "sent") {
    return "已发送"
  }
  if (status === "failed") {
    return "失败"
  }
  if (status === "skipped") {
    return "已跳过"
  }
  return status
}

function deliveryTypeLabel(deliveryType: string): string {
  if (deliveryType === "card_pool") {
    return "卡密库存"
  }
  if (deliveryType === "card_fixed") {
    return "固定文本"
  }
  if (deliveryType === "telegram_invite") {
    return "群邀请"
  }
  if (deliveryType === "file_download") {
    return "文件商品"
  }
  return deliveryType
}

function normalizeDeliveryType(value: string): AdminWebCreateProductPayload["delivery_type"] {
  if (value === "card_pool" || value === "card_fixed" || value === "telegram_invite" || value === "file_download") {
    return value
  }
  return "card_pool"
}

function sourceTypeLabel(sourceType: string): string {
  if (sourceType === "self") {
    return "自营"
  }
  if (sourceType === "reseller") {
    return "代理"
  }
  if (sourceType === "subscription") {
    return "订阅"
  }
  return sourceType
}

function paymentModeLabel(paymentMode: string): string {
  if (paymentMode === "tenant_direct") {
    return "租户直收"
  }
  if (paymentMode === "platform_escrow") {
    return "平台托管"
  }
  if (paymentMode === "platform_subscription") {
    return "平台订阅"
  }
  return paymentMode
}

function trimPaymentConfigPayload(
  payload: AdminWebPaymentProviderConfigPayload,
): AdminWebPaymentProviderConfigPayload {
  const normalized: AdminWebPaymentProviderConfigPayload = {}
  for (const [key, value] of Object.entries(payload)) {
    const text = typeof value === "string" ? value.trim() : value
    if (typeof text === "string" && text !== "") {
      normalized[key as keyof AdminWebPaymentProviderConfigPayload] = text
    }
  }
  return normalized
}

function normalizeSupplyMarketFilters(filters: AdminWebSupplyDashboardFilters): AdminWebSupplyDashboardFilters {
  return {
    market_query: filters.market_query?.trim() || undefined,
    market_category: filters.market_category?.trim() || undefined,
    market_delivery_type: filters.market_delivery_type ?? "all",
    market_access: filters.market_access ?? "all",
    market_min_price: filters.market_min_price?.trim() || undefined,
    market_max_price: filters.market_max_price?.trim() || undefined,
    market_stock: filters.market_stock ?? "all",
  }
}

function validateSupplyMarketFilters(filters: AdminWebSupplyDashboardFilters): string | null {
  const minPrice = filters.market_min_price?.trim()
  const maxPrice = filters.market_max_price?.trim()
  const numericMinPrice = minPrice ? Number(minPrice) : null
  const numericMaxPrice = maxPrice ? Number(maxPrice) : null
  if (numericMinPrice !== null && (!Number.isFinite(numericMinPrice) || numericMinPrice < 0)) {
    return "请输入有效的最低价。"
  }
  if (numericMaxPrice !== null && (!Number.isFinite(numericMaxPrice) || numericMaxPrice < 0)) {
    return "请输入有效的最高价。"
  }
  if (numericMinPrice !== null && numericMaxPrice !== null && numericMinPrice > numericMaxPrice) {
    return "最低价不能高于最高价。"
  }
  return null
}

function marketOfferAccessLabel(offer: AdminWebSupplyMarketOffer): string {
  if (offer.can_create_reseller_product) {
    return "可上架"
  }
  if (offer.reseller_rule_status === "pending") {
    return "待审核"
  }
  if (offer.reseller_rule_status === "rejected") {
    return "已拒绝"
  }
  if (offer.requires_approval) {
    return "需申请"
  }
  return "不可上架"
}

function marketOfferMinSaleText(offer: AdminWebSupplyMarketOffer): string {
  const minSalePrice = offer.effective_min_sale_price ?? offer.min_sale_price
  if (minSalePrice) {
    return `${minSalePrice} ${offer.currency}`
  }
  return `${offer.supplier_cost} ${offer.currency}`
}

function resellerRuleStatusLabel(status: string): string {
  if (status === "pending") {
    return "待审核"
  }
  if (status === "active") {
    return "已通过"
  }
  if (status === "rejected") {
    return "已拒绝"
  }
  return status
}

function auditActorLabel(item: AdminWebTenantAuditLogsResponse["items"][number]): string {
  if (item.actor_username) {
    return `@${item.actor_username}`
  }
  if (item.actor_telegram_user_id) {
    return `TG ${item.actor_telegram_user_id}`
  }
  return "系统"
}

function formatAuditMetadataValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "-"
  }
  if (typeof value === "string") {
    return value.length > 80 ? `${value.slice(0, 80)}...` : value
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value)
  }
  if (Array.isArray(value)) {
    return `列表 ${value.length}`
  }
  if (typeof value === "object") {
    return "对象"
  }
  return String(value)
}

function formatDateTime(value?: string | null): string {
  if (!value) {
    return "-"
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function buildSubscriptionPeriodEndPayload(
  value: string,
): AdminWebPlatformTenantSubscriptionSetPeriodEndPayload | null {
  if (!value) {
    return null
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return null
  }
  return { period_ends_at: date.toISOString() }
}

function errorToMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message
  }
  return "管理后台请求失败"
}
