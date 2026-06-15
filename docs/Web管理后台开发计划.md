# Web 管理后台开发计划

## 1. 当前决策

本阶段新增 Web 管理后台，使用 `shadcn/ui` 构建管理端界面。`shadcn` skill 已通过 `npx skills add shadcn/ui` 安装到项目内的 `.agents/skills/shadcn`，后续创建或调整组件时应按该 skill 的规则先查组件文档和现有组件，再组合页面。

支付系统近期只重点推进两类主线通道的配置入口、离线合同和 staging 验证路径，不能把当前能力摘要理解为生产可用：

- `epusdt_gmpay`：平台收款、订阅续费、代理订单平台托管收款的优先推进通道。
- `epay_compatible`：作为易支付兼容通道，用于租户自营订单的第二优先推进通道。

其他支付系统暂不作为近期开发主线。`token188`、`lemzf`、`usdt_trc20_direct` 和其他后续渠道只保留现有离线合同、配置骨架或后置扩展入口，不要求近期完成真实网关联调、查单、对账或生产验证。

业务插件能力已列为后续扩展方向，详见 `docs/业务插件架构方案.md`。长期目标接近 WordPress 插件式业务扩展，但当前阶段只落地受控 `payment` / `external_source` 适配器和最小 manifest 合同。Web 管理后台目标态可增加插件能力摘要和租户级插件启停/配置入口，用于外部货源连接、目录同步和商品上架；当前阶段只展示插件能力摘要/连接摘要，不展示真实上游联通状态，不加载远程前端代码，不展示上游 API Key 明文、外部订单 ID、发货内容、raw payload 或 storage key。

插件范围决策已固定：现在不建设 WordPress 式通用插件运行时，不做在线安装/升级、动态前端面板、动态 Bot handler、任意后台任务或插件自带迁移。当前 Web 后台只围绕受控适配器推进，即支付配置使用支付 provider/manifest，外部货源使用外部源连接、签名 `connection_handle`、目录同步和后续按需采购 BFF。这样后续接 acg-faka、mcy-shop 或新增支付通道时，只新增 provider/manifest 和安全 BFF，不改核心订单、商品、租户、账本流程。

Admin Web 外部源目录同步合同已接入：`POST /api/v1/admin-web/tenant/external-sources/catalog/sync` 请求仅允许 `connection_handle`、`cursor`、`limit`、`max_pages`，服务端从 cookie 当前工作区和签名 `connection_handle` 解析租户、provider、source 和连接，再受控加载 runtime credentials 调用既有 `ExternalCatalogSyncService`。响应只返回 provider/source、同步计数、next cursor 和本地商品安全摘要，不返回 `tenant_id`、`connection_id`、`external_id`、`raw_payload`、`credentials`、`token`、`secret`、`storage_key` 或 `delivery`。`web/admin` 的“外部源连接”行已提供“同步目录”按钮，成功后刷新外部源连接、插件能力和当前克隆 Bot 商品摘要；该能力仍不代表真实 acg-faka/mcy-shop 联调完成。

Admin Web 外部源已同步商品列表已接入：`GET /api/v1/admin-web/tenant/external-sources/catalog/products` 请求仅允许 `connection_handle`、`limit`、`offset`，只从 cookie 当前工作区和签名连接 handle 解析租户与连接，只读取已经通过目录同步落到本地 `products` 表的商品摘要。该接口不读取或解密外部源凭据，不调用 provider 目录/下单/发货方法，不触发真实上游联调，响应只返回本地 `product_id/name/category/status/delivery_type/price/currency/available_count/updated_at` 和连接展示摘要，不返回 `tenant_id`、`connection_id`、`external_id`、`external_source`、raw payload、凭据、库存项、文件 storage key 或发货内容。`web/admin` 外部源连接行已提供“查看已同步商品”只读入口，并在切换工作区时清空已展开列表。

Admin Web 订单观测 BFF 已接入：`GET /api/v1/admin-web/tenant/orders/observability` 只从 cookie 当前克隆 Bot 工作区解析租户，读操作不要求 Origin 门禁，不读取或暴露 Tenant Admin API Key，不要求 HMAC 签名。该接口复用支付回调失败、回调拒绝审计和外部履约 attempt 只读日志服务，支持 `limit` 和可选 `out_trade_no`，响应只返回支付回调失败、回调拒绝和外部履约 attempts 的安全观测摘要；不返回 `tenant_id`、`order_id`、`callback_id`、`audit_log_id`、`attempt_id`、`product_id`、`connection_id`、外部商品/订单 ID、`failure_fingerprint`、payload/raw、凭据、发货内容或 storage key。`web/admin` 的最近订单区域已新增“订单观测”面板，展示支付回调失败、回调拒绝、外部履约 attempts 的空态、错误态和独立刷新态；该能力不触发真实支付回调重放、不重试真实外部履约、不读取发货内容。

## 2. 产品边界

Web 管理后台分为两个工作区。

### 2.1 主 Bot 管理

主 Bot 管理面向平台运营者和有平台权限的管理员，负责跨租户能力：

- 租户和克隆 Bot 列表、状态、到期时间、绑定状态。
- 克隆 Bot Webhook 重置、停用、恢复前的状态确认。
- 平台订阅计划、租户订阅调整和欠费状态观测。
- 平台提现待审核列表、单笔提现详情和人工审核入口。
- 平台风控：封禁用户、租户冻结恢复、平台风控审计日志。
- 平台供货商品状态管控：只做软下架和恢复，不删除数据、不触发真实分账。
- 支付 provider 能力摘要和配置缺口观测，不在页面暴露密钥或原始凭据。

主 Bot 管理不直接替代 Telegram 母 Bot 的绑定流程。第一期可以复用现有母 Bot 绑定 Token、重置 Webhook 和停用 Bot 的服务能力，再补 Web 入口。

Admin Web 平台 Bot Webhook 重置入口已接入：`POST /api/v1/admin-web/platform/bots/{tenant_public_id}/webhook/reset` 使用 httpOnly Admin Web 会话和平台管理员身份，写操作必须通过 Origin 门禁；请求仅允许 `reason`，服务端只按 `tenant_public_id` 定位 active 克隆 Bot，不接受内部 `tenant_id` 或 `tenant_bot_id`。该入口会解密当前 Bot Token、调用 Telegram setWebhook、轮换 Webhook secret、清理旧/新 Redis Webhook 缓存并写审计；响应只返回 `tenant_public_id`、`bot_username`、状态、Webhook 状态、原因和 `telegram_webhook_called`，不返回 Bot Token、Webhook secret 或 raw payload，也不返回加密 token 或 Telegram 原始响应。本地测试只使用 fake Bot 验证调用参数和失败回滚；真实点击该入口属于真实 Telegram 操作，进入第五阶段前需用户明确确认。

Admin Web 平台订阅计划编辑已接入：`PATCH /api/v1/admin-web/platform/subscription/plans/{plan_code}` 使用 httpOnly Admin Web 会话和平台管理员身份，写操作必须通过 Origin 门禁；请求仅允许 `name`、`monthly_price`、`currency`、`trial_days`、`grace_days` 和 `reason`，不接受内部套餐 ID、租户 ID、订阅 ID、账单 ID、订单 ID、支付字段或 raw payload。`web/admin` 主 Bot 平台“订阅计划”卡片已提供创建、编辑、启用/停用入口，编辑成功后刷新平台 dashboard；响应只返回套餐代码、名称、月费、币种、试用/宽限天数、启用状态和时间字段，不返回内部 ID 或历史账单数据。

Admin Web 平台 Bot 状态和平台供货商品状态写操作安全合同已继续补齐：`PATCH /api/v1/admin-web/platform/bots/{tenant_public_id}/status` 只停用/恢复本地克隆 Bot 状态、写审计、清理本地 Webhook 缓存，不调用真实 Telegram；请求仅允许 `status/reason`，响应不返回 Bot Token、Webhook secret、内部 Bot ID 或 raw payload。`PATCH /api/v1/admin-web/platform/supply/supplier-offers/{supplier_offer_id}/status` 只做供货商品软下架/恢复，复用平台供货服务，不删除商品、不触发真实分账、不暴露供应商租户 ID、底层商品 ID、库存项、文件 storage key、凭据或发货内容。两类接口均要求 httpOnly Admin Web 会话、平台管理员身份和 Origin 门禁，并已补 OpenAPI schema 白名单与路由级离线测试。

Admin Web 剩余平台写接口安全合同已继续补齐：用户封禁/解封、租户冻结/恢复、平台提现完成/拒绝、订阅计划创建和订阅计划启停均已断言不声明 Tenant/Platform API Key 或 HMAC 头，不接受额外请求字段，路径参数只使用公开 ID 或业务 code，响应 schema 不暴露内部租户、Bot、账本、套餐、订阅、订单、支付、凭据、raw payload 或完整提现地址字段。用户封禁/解封、租户冻结/恢复、平台提现完成/拒绝、订阅计划创建和订阅计划启停已补 route 级离线测试，覆盖 Origin 门禁、平台管理员鉴权、服务层参数透传、事务提交、额外字段前置拒绝和响应脱敏。

Admin Web 路由已统一使用安全校验错误响应：请求体或查询参数触发 FastAPI/Pydantic 422 时，响应保留错误类型、位置和消息，剥离 `input`、`ctx` 和文档 URL，避免额外字段中携带的 token、secret、raw payload、提现地址或外部源凭据被校验错误原样回显到浏览器。

Admin Web 平台提现单笔详情已接入：`GET /api/v1/admin-web/platform/finance/withdrawals/{withdrawal_id}` 使用 httpOnly Admin Web 会话和平台管理员身份，只按路径中的提现业务 ID 查询，不使用 Platform Admin API Key/HMAC，不触发完成、拒绝或真实打款。响应复用平台提现安全 DTO，仅返回店铺公开摘要、金额、币种、网络、脱敏地址、状态和时间字段，不返回内部租户/账本 ID、完整地址、打款流水、凭证链接、审核备注、actor、raw payload 或凭据。`web/admin` 主 Bot “提现审核”卡片已提供行内“详情”入口，成功完成/拒绝后会刷新平台 dashboard。

Admin Web 平台租户/Bot 列表服务端分页筛选已接入：`GET /api/v1/admin-web/platform/dashboard` 复用平台 dashboard BFF，新增 `tenant_limit`、`tenant_offset`、`tenant_query`、`tenant_status`、`bot_status` 和 `subscription_status` 查询参数。后端只返回安全租户/Bot 摘要，不返回内部租户 ID、Bot ID、Bot Token、Webhook secret、订阅内部 ID 或 raw payload；前端主 Bot “租户与 Bot”面板已接入店铺/Bot/owner 搜索、租户状态、Bot 状态、订阅状态筛选和上一页/下一页分页。

### 2.2 克隆 Bot 管理设置

克隆 Bot 管理面向租户 owner 和租户管理员，所有操作必须落到一个明确的租户 Bot 上：

- 店铺设置：店铺名、欢迎语、客服、功能开关。
- 商品和库存：自营商品、分类排序、卡密导入、文件商品状态。
- 订单和发货：订单列表、订单排障详情、支付回调失败观测、外部履约 attempt 观测。
- 支付设置：优先支持 `epusdt_gmpay` 和 `epay_compatible`/易支付兼容配置；其他通道显示为后置或离线能力，不作为近期主配置流程。
- 插件和外部货源：展示受控适配器能力摘要、生产/联调状态、当前工作区支付配置启用状态和外部源连接摘要；目录同步入口必须从当前工作区和签名连接 handle 解析租户/连接，不能让浏览器传内部租户或连接 ID。acg-faka/mcy-shop 等候选外部货源先走离线合同和 fixture，不代表已安装真实插件、租户级插件启停或生产连接，不做真实联调。
- 订阅和账单：状态、账单摘要、续费订单。
- 财务和提现：余额、流水重算审计、提现申请和提现记录。
- 供应商功能：开放供货商品、设置成本/最低售价/审批策略、审核代理申请、设置单代理规则。
- 代理商功能：浏览供货市场、申请代理、选择商品、设置代理售价和展示名、上架到当前克隆 Bot。
- API Key、审计日志、报表和风控/售后只读观测。

## 3. 绑定机器人与工作区选择

Web 后台必须先确定当前操作属于哪个 Bot，否则代理商品无法准确上架到指定发卡 Bot。

推荐第一期绑定模型：

1. 从母 Bot 打开 Web 管理后台时，服务端使用 `MASTER_BOT_TOKEN` 校验 Telegram WebApp `initData`，识别 Telegram 用户。
2. 服务端按该 Telegram 用户查询其拥有或可管理的租户 Bot，返回工作区列表。
3. 从克隆 Bot 打开 Web 管理后台时，URL 携带安全的 `tenant_public_id` 或 `bot_public_id`，服务端用对应克隆 Bot Token 校验 `initData`，再校验该用户是否为 owner 或 tenant member。
4. 用户必须在页面顶部选择一个当前克隆 Bot。所有租户级写操作都使用该 Bot 对应的 `tenant_id`，不允许请求体覆盖 `tenant_id`。
5. 对于普通浏览器入口，使用一次性绑定码：用户在母 Bot 或克隆 Bot 中通过 `/admin_web_code` 生成短期 code，Web 端提交 code 后换取 httpOnly session cookie。code 只在签发时返回一次，Redis key 使用会话密钥 HMAC 派生，payload 设置短 TTL，消费使用 `GETDEL` 一次性删除，消费接口按来源 IP 限流，不落库保存明文。

安全边界：

- 浏览器端不保存 Tenant Admin API Key、Bot Token、支付密钥或外部源凭据。
- Web session 使用 httpOnly cookie 或等价服务端会话，权限由服务端按 Telegram 用户、平台管理员和租户成员关系计算。
- 工作区切换只改变 session 中的当前工作区，不允许客户端自行传内部 `tenant_id` 越权。
- 所有响应沿用现有安全 DTO，不返回供应商/代理商内部租户 ID、库存项、文件存储键、卡密、密钥或 raw payload。

## 4. 供应商和代理商 Web 流程

### 4.1 供应商流程

供应商进入当前克隆 Bot 工作区后：

1. 从本租户自营商品中选择可供货商品。
2. 设置供货成本、建议零售价、最低售价和是否需要审批。
3. 查看代理申请列表，按申请方店铺摘要审核通过或拒绝。
4. 对单个代理商设置独立成本和最低售价。
5. 查看供货商品状态、代理销售情况和账本摘要。

供应商侧允许展示申请方店铺摘要用于审核，但不得暴露代理商内部敏感信息。

### 4.2 代理商流程

代理商必须先选择要代理售卖的克隆 Bot 工作区，然后：

1. 浏览供货市场，支持搜索、分类、价格区间、库存状态和是否需要审批筛选。
2. 查看供货商品安全摘要和代理成本，不展示供应商内部商品 ID、库存项或凭据。
3. 提交代理申请；无需审批的商品可直接进入定价上架步骤。
4. 设置代理商品展示名、售价、分类、排序和是否隐藏供应商。
5. 上架到当前选中的克隆 Bot。买家侧只看到代理商店铺和代理商品，不暴露供应商身份。

若用户管理多个克隆 Bot，页面必须在代理申请和上架前要求确认目标 Bot，避免商品被挂到错误店铺。

### 4.3 本轮工作台体验补齐需求

本轮继续推进供应商/代理商 Web 工作台静态体验，不进入真实结算、真实外部货源履约或真实支付联调。需求边界如下：

- 供应商能力关闭时，供货商品创建、审批开关、代理申请审核和独立代理规则编辑仍可展示安全摘要，但所有写操作必须在前端明确禁用，并提示需先在店铺设置中开启供应商能力。
- 代理商能力关闭时，供货市场筛选仍可查看当前工作区安全摘要，但代理申请、免审批上架和已代理商品维护必须禁用，并提示需先开启代理商能力。
- 供应商/代理商共享的操作结果应在供货工作台顶部展示，避免供应商操作反馈落到代理商面板造成误读。
- 供应商申请审核列表应优先展示待审申请；无待审申请时给出明确空态，历史申请只展示店铺摘要、商品名、状态、价格摘要和更新时间。
- 继续保持安全 DTO 边界：前端不得展示供应商/代理商内部租户 ID、底层商品 ID、库存项、文件 storage key、发货内容、凭据、raw payload 或外部订单 ID。

开发方案：只调整 `web/admin` 前端工作台组合和文档说明，复用现有 `GET /api/v1/admin-web/tenant/supply/dashboard`、申请审核、供货商品、代理商品 BFF；不新增后端字段，不改变签名句柄合同，不触发真实上游联调。

### 4.4 本轮平台工作台体验补齐需求

本轮继续推进主 Bot 平台工作台静态体验，不启动真实服务，不进入 Telegram、支付、迁移或第三方外部源联调。需求边界如下：

- 平台风控审计日志先补前端本地筛选能力，支持按动作范围、状态和关键词过滤当前 dashboard 已返回的安全摘要，不新增 BFF 查询字段。
- 平台风控审计日志必须展示筛选结果数量、空态和重置入口，避免管理员只能看到固定前 5 条记录。
- 审计日志行只展示动作、对象类型、操作者 Telegram 摘要、目标 Telegram 用户、状态变化、原因/规则、拦截次数和阈值等安全字段。
- 继续禁止展示平台内部租户 ID、底层 Bot ID、订单内部 ID、支付/外部流水、raw payload、metadata 原文、凭据、Token、secret 或发货内容。
- 用户封禁/解封仍保持浏览器二次确认；本轮不改变风控写接口，不触发 Telegram、支付、外部源或真实迁移动作。

开发方案：只调整 `web/admin` 平台风控面板和文档说明，复用现有 `GET /api/v1/admin-web/platform/dashboard` 返回的 `banned_users` 与 `risk_audit_logs`；筛选在浏览器内完成，不新增后端参数，不扩大 Admin Web 安全 DTO。

### 4.5 本轮平台订阅计划体验补齐需求

本轮继续推进主 Bot 平台订阅计划静态体验，不接真实支付、不创建真实续费订单、不跑迁移、不启动服务。需求边界如下：

- 订阅计划创建和编辑表单必须在浏览器端前置校验后端合同边界：计划代码 1-64 位、名称 1-128 位、月费为非负金额、试用天数 0-3650、宽限天数 0-365。
- 表单提交按钮应在字段非法时禁用，并在表单内给出简短错误摘要，避免管理员点击后只得到后端 400。
- 订阅计划列表需要展示只读摘要：启用状态、费用、试用/宽限、创建/更新时间和当前编辑草稿是否有未保存变更。
- 订阅计划启用/停用仍使用现有二次确认；本轮不修改订阅服务、不触发真实支付、不新增账单、订单或迁移逻辑。
- 继续保持安全 DTO 边界：前端不得展示内部套餐 ID、订阅 ID、账单 ID、订单 ID、支付流水、raw payload 或凭据。

开发方案：只调整 `web/admin` 订阅计划面板和文档说明，复用现有 `GET /api/v1/admin-web/platform/dashboard`、`POST /api/v1/admin-web/platform/subscription/plans`、`PATCH /api/v1/admin-web/platform/subscription/plans/{plan_code}` 和启停接口；新增浏览器端纯函数校验与只读摘要，不新增后端字段，不改变 Admin Web 安全 DTO。

### 4.6 本轮平台提现审核体验补齐需求

本轮继续推进主 Bot 平台提现审核静态体验，不接真实打款、不调用链上或支付网关、不跑迁移、不启动服务。需求边界如下：

- 平台提现列表需要更明确区分待审数量和总返回数量，并展示脱敏只读摘要：店铺、金额、币种、网络、脱敏地址、状态、申请/审核/完成时间。
- 单笔详情展开后应提供本地审核表单：拒绝需要填写审核备注；完成可填写审核备注、付款参考和凭证 URL，并在前端校验后端字段长度。
- 审核按钮必须保持浏览器二次确认；完成/拒绝只调用现有 Admin Web 审核接口，不触发真实打款、查链、支付网关或外部通知。
- 审核完成后刷新平台 dashboard，并清理当前行本地输入，避免误把上一笔提现的审核草稿带到下一笔。
- 继续保持安全 DTO 边界：页面不展示完整提现地址、付款参考、凭证 URL、审核备注、actor、内部租户 ID、账本 ID、raw payload、API Key、Token 或 secret；用户刚输入的字段只作为提交草稿存在，响应不回显。

开发方案：只调整 `web/admin` 提现审核面板和文档说明，复用现有 `GET /api/v1/admin-web/platform/dashboard`、`GET /api/v1/admin-web/platform/finance/withdrawals/{withdrawal_id}`、完成和拒绝接口；新增浏览器端审核草稿状态、长度校验、详情安全摘要和操作边界提示，不新增后端字段，不改变 Admin Web 安全 DTO。

### 4.7 本轮平台供货管控体验补齐需求

本轮继续推进主 Bot 平台供货商品状态管控静态体验，不触发真实分账、不删除商品、不调用外部货源、不启动服务。需求边界如下：

- 平台供货商品列表需要支持浏览器端本地筛选：关键词、状态、审批方式和库存状态，筛选范围仅限当前 dashboard 已返回的安全摘要。
- 平台供货管控需要展示结果数量、状态摘要和筛选空态，避免管理员只能看到固定前 6 条商品。
- 软下架/恢复操作需要允许输入本地操作原因，前端按后端合同校验最长 255 字；未输入时使用安全默认原因。
- 软下架/恢复仍使用浏览器二次确认；该操作只调用现有平台供货状态接口，不删除数据、不触发真实分账、不触发外部货源履约。
- 继续保持安全 DTO 边界：页面不展示供应商租户 ID、底层商品 ID、库存项、文件 storage key、凭据、发货内容、raw payload 或外部订单 ID。

开发方案：只调整 `web/admin` 平台供货管控面板和文档说明，复用现有 `GET /api/v1/admin-web/platform/dashboard` 和 `PATCH /api/v1/admin-web/platform/supply/supplier-offers/{supplier_offer_id}/status`；新增浏览器端筛选、摘要、原因草稿和长度校验，不新增后端参数，不改变 Admin Web 安全 DTO。

## 5. 技术方案

前端建议新增独立目录：

```text
web/admin/
  src/
  components/
  app/
  package.json
  components.json
```

第一期使用 Vite + React + TypeScript + Tailwind + `shadcn/ui`，保持单页管理台，调用 FastAPI 管理端接口。选择 Vite 是为了减少框架复杂度；后续如果需要 SSR、复杂权限路由或多品牌部署，再评估 Next.js。

后端建议新增 Web session 适配层：

```text
POST /api/v1/admin-web/sessions/telegram
POST /api/v1/admin-web/sessions/binding-code
GET  /api/v1/admin-web/workspaces
POST /api/v1/admin-web/workspaces/select
GET  /api/v1/admin-web/session
POST /api/v1/admin-web/logout
```

租户级页面优先复用现有 service 和 Tenant Admin API 的安全 DTO，不为了 Web 后台复制一套业务逻辑。确实需要浏览器会话的接口应放在 `admin-web` 适配层，只做鉴权、工作区解析、输入白名单和 DTO 转换。

## 6. 分期实施

### 6.1 阶段 9A：后台骨架和绑定

- 创建 `web/admin` shadcn/ui 项目骨架。
- 实现登录态、Telegram WebApp initData 校验、工作区列表和当前 Bot 选择。
- 页面框架包含侧边栏、顶部 Bot 切换器、权限提示、空状态和退出登录。
- 补服务级和前端基础测试，确认非 owner/admin 不能进入租户后台。

### 6.2 阶段 9B：克隆 Bot 基础管理

- 接入店铺设置、商品列表、商品分类排序、库存统计、订单列表和订单排障详情。
- 接入支付设置页面，只把 `epusdt_gmpay` 和 `epay_compatible` 作为近期主配置项。
- 接入订阅、财务、提现、报表和风控/售后只读入口。

### 6.3 阶段 9C：供应商和代理商工作台

- 接入供货商品创建、审批开关、申请审核和独立代理规则。
- 接入供货市场浏览、代理申请、代理商品定价和上架。
- 强制所有代理上架动作绑定当前克隆 Bot 工作区。
- 补齐供应商/代理商能力开关关闭时的只读摘要、禁用态、顶部操作反馈和待审优先展示，确保关闭能力不会误导用户执行写操作。

### 6.4 阶段 9D：主 Bot 平台管理

- 接入租户/Bot 列表、Webhook 状态、停用/恢复入口、订阅计划管理。
- 接入租户订阅状态观测：统计试用、活跃、宽限、暂停和保留期过期租户，并展示需要关注的到期/异常租户。
- 接入平台提现审核、平台风控和平台供货商品状态管控。
- 补齐平台风控审计日志的本地筛选、只读摘要、筛选空态和结果数量展示，保持安全 DTO 边界。
- 补齐订阅计划创建/编辑的前端合同校验、只读摘要、未保存变更提示和禁用态，减少无效写请求。
- 补齐平台提现审核的详情安全摘要、审核草稿校验、完成/拒绝操作边界提示和刷新后草稿清理。
- 补齐平台供货商品的本地筛选、结果摘要、操作原因草稿和软下架/恢复边界提示。
- 平台写操作使用二次确认，不触发 Telegram、支付或第三方外联，除非对应功能明确要求并已完成真实联调。

### 6.5 阶段 9E：联调和验收

- 离线测试覆盖 session、工作区越权、供应商/代理商安全 DTO、支付配置脱敏。
- 前端测试覆盖多 Bot 切换、代理商品上架到指定 Bot、空状态、错误态和权限拒绝。
- 真实服务、真实 Telegram WebApp、真实支付跳转和真实回调联调单独确认后再执行。

## 7. 当前状态

- `shadcn` skill 已安装。
- 后端已有大量 Tenant Admin、Platform Admin、供货代理、支付配置和订单观测 API，可作为 Web 管理后台第一期数据来源。
- 后端已新增 `admin-web` 会话、工作区和克隆 Bot 概览/店铺设置/商品/订单/订阅/财务/报表任务/支付配置/供货代理 BFF，并补充订单排障详情 BFF：Telegram WebApp `initData` 登录、httpOnly 管理会话 cookie、工作区列表、当前工作区选择、登出、`GET /api/v1/admin-web/tenant/overview`、`GET /api/v1/admin-web/tenant/settings`、`PATCH /api/v1/admin-web/tenant/settings`、`GET /api/v1/admin-web/tenant/products`、`POST /api/v1/admin-web/tenant/products`、`PATCH /api/v1/admin-web/tenant/products/{product_id}/metadata`、`PATCH /api/v1/admin-web/tenant/products/{product_id}/sales`、`PATCH /api/v1/admin-web/tenant/products/status`、`POST /api/v1/admin-web/tenant/products/{product_id}/inventory/import`、`POST /api/v1/admin-web/tenant/products/{product_id}/delivery-file`、`GET /api/v1/admin-web/tenant/orders`、`GET /api/v1/admin-web/tenant/orders/{out_trade_no}/diagnostics`、`GET /api/v1/admin-web/tenant/subscription`、`GET /api/v1/admin-web/tenant/finance`、`POST /api/v1/admin-web/tenant/finance/withdrawals`、`GET /api/v1/admin-web/tenant/reports/export-jobs`、`POST /api/v1/admin-web/tenant/reports/export-jobs`、`GET /api/v1/admin-web/tenant/payments/configs`、`PUT /api/v1/admin-web/tenant/payments/{provider_name}/config`、`DELETE /api/v1/admin-web/tenant/payments/{provider_name}/config`、`GET /api/v1/admin-web/tenant/supply/dashboard`、`POST /api/v1/admin-web/tenant/supply/applications`、`POST /api/v1/admin-web/tenant/supply/supplier-offers`、`PATCH /api/v1/admin-web/tenant/supply/supplier-offers/{supplier_offer_id}/approval`、`POST /api/v1/admin-web/tenant/supply/supplier-rules`、`POST /api/v1/admin-web/tenant/supply/supplier-applications/review`、`POST /api/v1/admin-web/tenant/supply/reseller-products`、`PATCH /api/v1/admin-web/tenant/supply/reseller-products/{reseller_product_id}/metadata` 和 `PATCH /api/v1/admin-web/tenant/supply/reseller-products/{reseller_product_id}/sales`。这些接口只从 cookie 当前 `tenant_public_id` 工作区解析租户，重新校验 owner/admin 权限；店铺设置写入额外复用租户 `settings` 权限，只允许 `store_name`、`welcome_text`、`support_text`、`order_timeout_minutes`、`self_sale_enabled`、`supplier_enabled` 和 `reseller_enabled`，功能开关会同步租户布尔列和 `tenant_settings.feature_flags`。Admin Web 订阅只读面板只返回套餐、周期、宽限/暂停/保留时间和最近账单摘要，Admin Web 财务面板返回余额、余额重算审计摘要、脱敏提现列表，并支持发起待审核提现申请；二者不读取或暴露 Tenant Admin API Key，不要求 HMAC 签名，不接收 `tenant_id`，不返回内部 ID、完整提现地址、账本流水、payment_url、上游流水或 raw payload。商品列表、商品创建、商品元数据编辑、商品价格/状态编辑、批量状态更新、库存导入和文件商品绑定只返回当前租户商品操作句柄、名称、分类、排序、状态、发货类型、价格、库存统计和文件扫描绑定摘要，订单列表只返回 `out_trade_no`、金额、状态、买家 Telegram ID 与时间字段；Admin Web 订单排障详情复用 `OrderDiagnosticsService` 并转换为浏览器安全 DTO，只返回订单号、状态、金额、时间、支付/回调/发货/外部履约/TRC20 聚合摘要，不返回 `order_id`、`payment_id`、`callback_id`、`delivery_record_id`、支付链接、上游流水、payload/raw/credentials、卡密、文件路径、外部订单或连接 ID；支付配置只开放 `epusdt_gmpay` 和 `epay_compatible`，响应只返回 provider、启用状态、网关 URL、脱敏商户号和能力摘要；供货代理 dashboard 返回当前 Bot 的供货商品、供应商申请签名句柄、供应商独立规则签名句柄、代理市场商品、我的代理申请和已上架代理商品安全摘要；商品创建请求体只接收 `name`、`price`、`delivery_type`、`description` 和 `category`，只创建自营草稿商品，不导入库存、不绑定文件、不外部同步；库存导入请求体只接收 `items`，只支持 `card_pool` / `card_fixed` 自营文本库存，响应只返回导入数量、重复数量和可用库存数；文件商品绑定只接收浏览器上传的 `file`，低/中风险扫描通过后绑定商品文件，高风险扫描不绑定；商品元数据编辑和代理商品元数据编辑请求体都只接收 `category` 和 `sort_order`，其中代理商品分类/排序只更新 `reseller_products` 当前代理商自己的展示元数据，不改供应商原始商品；代理商品展示名/售价编辑请求体只接收 `display_name` 和 `sale_price`，只更新当前代理商自己的 `reseller_products.display_name/sale_price`，并在服务层重新校验售价为有限正数、最多 8 位小数、不得低于供应商成本或有效最低售价；商品价格/状态编辑请求体只接收 `price` 和 `status`，商品批量状态请求体只接收 `product_ids` 和目标 `status`，提现申请请求体只接收 `amount`、`network`、`address` 和 `currency`，支付配置请求体只接收对应 provider 的网关、商户号、密钥和展示配置字段，报表任务创建请求体只接收 `report_type`，供货商品创建、审批开关、独立规则、代理申请、供应商申请审核和代理商品上架请求体只接收 `product_id`、`suggested_price`、`min_sale_price`、`requires_approval`、`supplier_rule_id`、`pricing_value`、`supplier_offer_id`、`supplier_application_id`、`action`、`sale_price`、`display_name` 等业务字段，不允许浏览器传内部 `tenant_id` / `reseller_tenant_id` / `rule_id`。所有响应不返回 Bot Token、API Key、支付密钥、支付链接、库存明文、库存密文、库存 hash、库存项 ID、文件 storage key、供应商内部 ID 或 raw payload。
- Admin Web 主 Bot 平台管理 BFF 已落地：`GET /api/v1/admin-web/platform/dashboard`、`PATCH /api/v1/admin-web/platform/bots/{tenant_public_id}/status`、`PATCH /api/v1/admin-web/platform/risk/tenants/{tenant_public_id}/suspension-status`、`PATCH /api/v1/admin-web/platform/risk/users/{telegram_user_id}/ban-status`、`GET /api/v1/admin-web/platform/finance/withdrawals/{withdrawal_id}`、`POST /api/v1/admin-web/platform/finance/withdrawals/{withdrawal_id}/complete`、`POST /api/v1/admin-web/platform/finance/withdrawals/{withdrawal_id}/reject`、`POST /api/v1/admin-web/platform/tenants/{tenant_public_id}/subscription/grant-days`、`PATCH /api/v1/admin-web/platform/tenants/{tenant_public_id}/subscription/period-end`、`POST /api/v1/admin-web/platform/subscription/plans`、`PATCH /api/v1/admin-web/platform/subscription/plans/{plan_code}`、`PATCH /api/v1/admin-web/platform/subscription/plans/{plan_code}/status` 和 `PATCH /api/v1/admin-web/platform/supply/supplier-offers/{supplier_offer_id}/status`。这些接口只接受 httpOnly Admin Web 会话并要求平台管理员身份，不向浏览器暴露 Platform Admin API Key、内部 `tenant_id`、Bot Token、Webhook secret、完整提现地址、支付密钥、payload 或 raw metadata；写操作必须通过 Origin 门禁。Bot 停用/恢复只调整平台运行状态和清理本地 Webhook 缓存，不调用 Telegram `setWebhook` / `deleteWebhook`；真实 Webhook 重置仍保留为需单独确认的 Telegram 联调项。
- Admin Web 平台租户订阅状态观测和调整入口已落地：`GET /api/v1/admin-web/platform/dashboard` 的 `stats` 增加 `trial_subscription_count`、`active_subscription_count`、`grace_subscription_count`、`suspended_subscription_count` 和 `retention_expired_subscription_count`，按 `TenantSubscription.status` 优先、缺失时回退 `Tenant.status` 聚合；同一响应新增 `subscription_attention` 服务端关注队列，按保留期过期、暂停、宽限过期、宽限中、已到期、即将到期排序，只返回 `tenant_public_id`、店铺名、owner Telegram 摘要、套餐/状态和关键时间。平台管理员可通过 `POST /api/v1/admin-web/platform/tenants/{tenant_public_id}/subscription/grant-days` 赠送 1-3650 天，或通过 `PATCH /api/v1/admin-web/platform/tenants/{tenant_public_id}/subscription/period-end` 设置新的到期时间；两者都只用公开 `tenant_public_id` 定位租户并复用 `SubscriptionService.grant_days/set_period_end`，不接受内部 `tenant_id`、订阅/套餐/账单/订单 ID、payment URL 或 raw payload。该调整只改订阅周期和订阅状态审计，不调用 `process_lifecycle`，不创建续费订单，不触发支付建链、Telegram 或第三方外联。
- Admin Web 平台支付通道观测已落地：`GET /api/v1/admin-web/platform/dashboard` 返回 `payment_providers` 安全摘要，包含 provider 能力、生产/联调/离线标记、支持资产/网络、`configured_tenant_count`、`enabled_tenant_count`、`missing_config_tenant_count` 和平台配置布尔状态。聚合只读取 `payment_provider_configs` 的 provider、scope、tenant 和 enabled 计数，不读取或解密 `config_encrypted`，不返回网关 URL、商户号、密钥、收款地址、支付链接、payload 或 raw 响应，也不调用真实支付网关。
- `web/admin` 主 Bot 页已接入平台 dashboard：展示租户/Bot 列表、绑定状态、Webhook 观测状态、订阅到期、租户订阅状态观测和调整、支付通道观测、订阅计划创建/启停、平台提现待审与单笔详情/完成/拒绝、用户封禁/解封、租户冻结/恢复、平台风控审计日志和供货商品软下架/恢复入口；危险写操作在浏览器侧二次确认。前端依赖已按 `web/admin/package.json` 本地安装，`npm run typecheck` 和 `npm run build` 已通过。
- Admin Web 店铺设置合同已落地：`GET /api/v1/admin-web/tenant/settings` 和 `PATCH /api/v1/admin-web/tenant/settings` 只使用 cookie 当前工作区解析克隆 Bot 租户，写操作必须通过 Origin 门禁并校验 `settings` 权限；请求仅允许 `store_name`、`welcome_text`、`support_text`、`order_timeout_minutes`、`self_sale_enabled`、`supplier_enabled` 和 `reseller_enabled`，不接受 `tenant_id`、Bot Token、API Key、支付字段或 raw payload，不允许浏览器直接提交原始 `feature_flags` 或 `clone_enabled`。响应只返回店铺名、欢迎语、客服信息、订单超时分钟数和自营/供货/代理开关。
- 功能开关业务防线已接入：共享 `tenant_features` 解析默认值、`tenants.self_sale_enabled/supplier_enabled/reseller_enabled` 和 `tenant_settings.feature_flags` 覆盖值；Admin Web 工作区、概览、店铺设置和供货 dashboard 使用同一套解析。`supplier_enabled=false` 时 Admin Web 供货商品创建、审批开关、供应商申请审核和独立代理规则写操作会在调用供货服务前拒绝；`reseller_enabled=false` 时代理申请、代理商品上架和代理商品元数据编辑会在调用供货服务前拒绝。Public Store、租户 Bot 和订单服务也已按 `self_sale_enabled` / `reseller_enabled` 过滤商品列表和拒绝下单；代理订单还会检查供应商租户 `supplier_enabled`，避免历史链接或直连命令绕过店铺设置。
- Admin Web 商品元数据编辑合同已落地：`PATCH /api/v1/admin-web/tenant/products/{product_id}/metadata` 只使用 cookie 当前工作区解析克隆 Bot 租户，写操作必须通过 Origin 门禁，请求仅允许 `category` 和 `sort_order`，不触发外部同步、不改库存、不暴露外部凭据。
- Admin Web 代理商品元数据编辑合同已落地：`PATCH /api/v1/admin-web/tenant/supply/reseller-products/{reseller_product_id}/metadata` 只使用 cookie 当前工作区解析代理商克隆 Bot 租户，写操作必须通过 Origin 门禁，请求仅允许 `category` 和 `sort_order`；服务端按 `reseller_tenant_id` 限定只能修改当前 Bot 已上架代理商品，只更新 `reseller_products.category/sort_order`，不改供应商 `Product.category/sort_order`，不接收或返回 `tenant_id`、`supplier_tenant_id`、`reseller_tenant_id`、`rule_id`、`supplier_rule_id`、底层商品/档位 ID、库存项、文件 storage key 或凭据。
- Admin Web 代理商品销售字段编辑合同已落地：`PATCH /api/v1/admin-web/tenant/supply/reseller-products/{reseller_product_id}/sales` 只使用 cookie 当前工作区解析代理商克隆 Bot 租户，写操作必须通过 Origin 门禁，请求仅允许 `display_name` 和 `sale_price`，空请求和 `sale_price=null` 会在进入服务层前拒绝；服务端按 `reseller_tenant_id` 限定只能修改当前 Bot 已上架代理商品，只更新 `reseller_products.display_name/sale_price`，售价必须是有限正数且最多 8 位小数，并重新校验不得低于供应商成本或有效最低售价；响应不返回内部租户、供应商规则、底层商品/档位、库存项、文件 storage key 或凭据。
- Admin Web 商品创建合同已落地：`POST /api/v1/admin-web/tenant/products` 只使用 cookie 当前工作区解析克隆 Bot 租户，写操作必须通过 Origin 门禁，请求仅允许 `name`、`price`、`delivery_type`、`description` 和 `category`；创建结果固定为自营草稿商品并自动生成默认档位，不导入库存、不绑定文件、不配置群邀请、不触发外部同步，不暴露内部租户 ID、外部映射、库存内容或文件 storage key。
- Admin Web 商品价格/状态编辑合同已落地：`PATCH /api/v1/admin-web/tenant/products/{product_id}/sales` 只使用 cookie 当前工作区解析克隆 Bot 租户，写操作必须通过 Origin 门禁，请求仅允许 `price` 和 `status`，只更新自营商品默认档位价格和商品上下架状态；文件商品未绑定文件、群邀请商品未绑定群 ID 时仍拒绝上架，不触发外部同步、不导入库存、不绑定文件、不暴露库存内容或文件 storage key。
- Admin Web 商品批量状态更新合同已落地：`PATCH /api/v1/admin-web/tenant/products/status` 只使用 cookie 当前工作区解析克隆 Bot 租户，写操作必须通过 Origin 门禁，请求仅允许 `product_ids` 和目标 `status`，单次最多 50 个商品且不允许重复 ID；服务端逐个复用自营商品状态更新校验，文件商品未绑定文件或群邀请商品未绑定群 ID 时整批拒绝，不触发外部同步、不导入库存、不绑定文件、不暴露库存内容或文件 storage key。
- Admin Web 自营库存导入合同已落地：`POST /api/v1/admin-web/tenant/products/{product_id}/inventory/import` 只使用 cookie 当前工作区解析克隆 Bot 租户，写操作必须通过 Origin 门禁，请求仅允许 `items`；后端会去空行、去输入内重复、加密并哈希后复用现有库存写入能力，只支持 `card_pool` / `card_fixed` 自营文本库存，不允许浏览器提交 `tenant_id`、`variant_id`、密文、hash、storage key 或库存状态；响应只返回 `product_id`、导入数量、库内重复数量、输入重复数量和可用库存数，不返回库存明文、密文、hash、storage key 或库存项 ID。
- Admin Web 文件商品绑定合同已落地：`POST /api/v1/admin-web/tenant/products/{product_id}/delivery-file` 只使用 cookie 当前工作区解析克隆 Bot 租户，写操作必须通过 Origin 门禁，只接收浏览器上传的 `file`；后端复用文件名/MIME 校验、服务端 `storage_key` 生成、`uploaded_files` 记录和压缩包风险扫描，低/中风险扫描通过后绑定商品文件，高风险扫描不绑定。响应只返回 `product_id`、文件名、大小、MIME、风险等级、扫描消息和 `bound`，不返回 `storage_key`、`delivery_file_id`、`uploaded_file_id`、`sha256`、文件内容或压缩包条目。
- Admin Web 支付配置 BFF 已落地：`GET /api/v1/admin-web/tenant/payments/configs`、`PUT /api/v1/admin-web/tenant/payments/{provider_name}/config`、`DELETE /api/v1/admin-web/tenant/payments/{provider_name}/config` 只从 cookie 当前工作区解析租户，写操作必须通过 Origin 门禁，不读取或暴露 Tenant Admin API Key，不要求 HMAC 签名，不返回支付密钥、密文、完整收款地址、支付链接、上游流水或 raw payload，不调用真实支付网关，不做保存时连通性测试。
- Admin Web 订单排障详情已落地：`GET /api/v1/admin-web/tenant/orders/{out_trade_no}/diagnostics` 只从 cookie 当前工作区解析租户，读操作不要求 Origin 门禁，不读取或暴露 Tenant Admin API Key，不要求 HMAC 签名；前端显示“订单排障”，响应只给排障摘要，不返回内部 ID、支付链接、provider trade number、payload、raw detail、外部连接/订单 ID、库存内容、文件路径、凭据或密钥。
- Admin Web 提现申请合同已落地：`POST /api/v1/admin-web/tenant/finance/withdrawals` 只从 cookie 当前工作区解析克隆 Bot 租户，写操作必须通过 Origin 门禁，不使用 Tenant Admin API Key，不要求 HMAC 签名；请求仅允许 `amount`、`network`、`address` 和 `currency`。提现申请只创建待审核记录并冻结可用余额，不触发真实打款，不完成或拒绝提现；响应只返回脱敏地址、金额、币种、网络、状态和时间字段，不返回 `withdrawal_id`、完整提现地址、账本流水、打款流水、凭证链接、actor、payload 或凭据。
- Admin Web 报表任务合同已落地：`GET /api/v1/admin-web/tenant/reports/export-jobs`、`POST /api/v1/admin-web/tenant/reports/export-jobs` 和 `POST /api/v1/admin-web/tenant/reports/export-jobs/download` 只从 cookie 当前克隆 Bot 工作区解析租户，不使用 Tenant Admin API Key，不要求 HMAC 签名；列表支持 `status`、`report_type` 和 `limit`，创建请求仅允许 `report_type`，下载请求仅允许签名 `download_handle`。创建接口只写入 `pending` 报表任务，不同步生成 CSV、不启动 worker；列表/创建响应只返回报表类型、范围、状态、行数、是否可下载、签名下载句柄、脱敏失败原因和时间字段，不返回 `export_job_id`、`tenant_id`、`requested_by_user_id`、`filename`、`download_url`、`download_token`、`storage_key`、本地路径、原始错误、payload、token、secret 或 API Key。下载入口只代理已完成且当前租户可下载的报表文件，不暴露原始下载 token、storage key 或底层文件名；下载文件名使用 `orders-report.csv` 等泛化名称。`web/admin` 右侧“报表任务”卡片已接入类型/状态筛选、独立刷新、创建报表、已完成文件下载按钮、加载、错误和空态。
- Admin Web API Key 管理合同已落地：`GET /api/v1/admin-web/tenant/api-keys`、`POST /api/v1/admin-web/tenant/api-keys` 和 `POST /api/v1/admin-web/tenant/api-keys/revoke` 只从 cookie 当前克隆 Bot 工作区解析租户，并复用租户 `settings` 权限；写操作必须通过 Origin 门禁，不使用 Tenant Admin API Key，不要求 HMAC 签名。创建请求仅允许 `name`、`scopes` 和 `ip_allowlist`，明文 Key 只在创建响应中返回一次；列表和吊销使用签名 `credential_handle`，不返回 `api_key_id`、`tenant_id`、`key_hash`、`created_by_user_id`、内部用户 ID、Bot Token、支付密钥、payload、token 或 secret。`web/admin` 右侧“API Key”卡片已接入只读观测/完整租户管理预设、IP 白名单输入、独立刷新、创建后一次性明文展示和吊销确认。
- Admin Web 插件能力摘要只读 BFF 已落地：`GET /api/v1/admin-web/business-plugins/capabilities` 只从 httpOnly cookie 当前工作区解析平台或克隆 Bot 上下文，返回 `payment` / `external_source` 等业务插件 manifest 的浏览器安全摘要、生产/联调/离线标记、当前工作区非密文支付启用状态和外部源连接计数。该接口不使用 Tenant Admin API Key，不要求 HMAC 签名，不执行插件 entrypoint，不导入远程代码，不调用 provider 下单/目录/发货方法，不读取或解密外部源凭据，不读取支付密钥，不测试上游连通性，不返回 `tenant_id`、连接 ID、凭据字段、raw payload、外部订单 ID、发货内容或 storage key；这不代表插件安装、租户级启停、真实 mcy-shop/acg-faka、真实支付网关或 staging 验证完成。`web/admin` 右侧“插件能力”卡片已接入独立刷新、加载、错误和空态，不影响商品、订单、支付配置或供货面板。
- Admin Web 外部源连接管理合同已落地：`GET /api/v1/admin-web/tenant/external-source-connections`、`POST /api/v1/admin-web/tenant/external-source-connections` 和 `POST /api/v1/admin-web/tenant/external-source-connections/disable` 只从 httpOnly cookie 当前克隆 Bot 工作区解析租户，写操作必须通过 Origin 门禁并校验 `settings` 权限。列表响应只返回 provider 能力摘要、连接展示名、provider/source、状态、时间、`credential_field_count` 和签名 `connection_handle`，不返回 `tenant_id`、内部连接 ID、凭据字段名、明文、密文、API key、secret、token、raw payload、外部订单 ID、发货内容或 storage key；创建只做本地 provider 凭据格式校验和加密保存，停用只按 `connection_handle` 定位当前租户连接。该入口不读取或解密外部源凭据，不调用 provider 目录/下单/发货方法，不触发真实上游联调，不代表 acg-faka/mcy-shop 真实连接已认证。
- 已创建 `web/admin` Vite + React + TypeScript + Tailwind + `shadcn/ui` 前端，并接入 `admin-web` 会话、工作区和克隆 Bot 概览/列表/供货代理接口：`GET /session`、`GET /workspaces`、`POST /workspaces/select`、`POST /sessions/binding-code`、`GET /tenant/overview`、`GET /tenant/products`、`GET /tenant/orders`、`GET /tenant/orders/{out_trade_no}/diagnostics`、`GET /tenant/supply/dashboard`、Telegram WebApp `initData` 自动建会话、一次性绑定码换取 httpOnly cookie、加载态、未登录态、错误态、绑定码输入、工作区切换、克隆 Bot 概览面板、最近商品预览、最近订单预览、订单排障详情面板、供应商工作台预览和代理商工作台。
- 代理商工作台已接入 Web 供货市场选品闭环：页面明确显示当前目标克隆 Bot，供货市场支持名称/分类/发货类型/代理状态/价格区间/库存状态筛选；筛选只从 cookie 当前工作区解析目标克隆 Bot，不接受或返回 `tenant_id`、底层商品、库存项或凭据。代理商可按 `supplier_offer_id` 提交代理申请，对免审批或已通过商品填写 `sale_price` / `display_name` 并上架到当前 cookie 工作区绑定的克隆 Bot；请求体不包含 `tenant_id`、`reseller_tenant_id`、底层商品 ID 或档位 ID。
- 供应商供货商品创建和审批开关已接入，供应商独立代理规则已接入，供应商工作台已完成待审代理申请通过/拒绝、供货商品创建、审批开关和独立代理规则的最小闭环：dashboard 返回不可篡改的 `supplier_application_id` 和 `supplier_rule_id` 签名句柄，前端只提交签名句柄、审核动作、供应商成本和最低售价，后端按当前供应商工作区解析真实代理关系后调用已有 `set_existing_reseller_rule`；该接口只设置已有 `pending` 或 `active` 代理关系，不创建不存在的代理关系，不要求浏览器提交 `reseller_tenant_id` 或 `rule_id`。供应商可从当前 Bot 自营上架商品中选择商品，填写建议售价、最低售价和审批策略开放供货，并可把已有供货商品切换为需审批或免审批。
- Tenant Admin API 已同步接入功能开关业务防线：供货侧路由进入 `SupplyService` 前检查当前租户 `supplier` 开关，代理侧路由进入服务前检查 `reseller` 开关，关闭时返回 403；这与 Admin Web、Public Store、租户 Bot 和订单服务共用 `tenant_features` 解析规则。
- Admin Web 续费下单合同已落地：`POST /api/v1/admin-web/tenant/subscription/renewal-orders` 只从 cookie 当前工作区解析克隆 Bot 租户，写操作必须通过 Origin 门禁，不使用 Tenant Admin API Key，不要求 HMAC 签名；请求仅允许 `months`，范围 1-24。接口创建本租户续费订单和 invoice，并尝试创建平台支付链接；支付配置暂不可用或建链失败时保留续费订单并返回泛化失败原因。除新建订单付款所需 `payment_url` 外，不返回内部 ID、上游流水、payload 或凭据。
- `web/admin` 已接入商品创建、商品分类/排序元数据编辑、商品价格/状态编辑、当前页多选批量上架/下架、自营卡密库存导入、文件商品绑定、订单排障详情、订阅续费下单、订阅与财务面板、提现申请、报表任务、API Key 管理、供货市场筛选、已上架代理商品展示名/售价/分类/排序编辑，以及 `epusdt_gmpay` / `epay_compatible` 支付配置查看、保存和停用；商品创建目前仅创建草稿商品，库存导入和文件绑定通过独立接口处理；报表任务支持创建 pending job、查看安全摘要和通过 `download_handle` 安全下载已完成文件，但仍不生成报表、不启动 worker、不做真实环境下载联调；更深的代理批量操作、跨页管理和真实结算联调仍后置。
- Admin Web 商品/订单列表分页筛选已落地：`GET /api/v1/admin-web/tenant/products` 支持 `limit`、`offset`、`query`、`status`、`delivery_type` 和 `category`，`GET /api/v1/admin-web/tenant/orders` 支持 `limit`、`offset`、`out_trade_no`、`status`、`source_type` 和 `payment_mode`；两个接口都只从 cookie 当前克隆 Bot 工作区解析租户，响应包含 `offset` 与安全摘要，不返回内部租户 ID、库存项、文件 storage key、支付链接、上游流水或 raw payload。`web/admin` 商品和订单面板已接入搜索、筛选、分页、刷新按钮、空状态和订单排障入口，筛选值在前端和 BFF 双层白名单内归一化。
- Admin Web 订阅/财务侧栏可用性状态已补齐：未选择克隆 Bot 时不展示续费和提现表单；订阅/财务支持独立刷新，只重拉 `GET /tenant/subscription` 与 `GET /tenant/finance`，不连带刷新商品、订单或供货市场；侧栏已展示刷新态、独立错误态、订阅明细未加载、财务明细未加载、暂无账单和暂无提现空态，续费/提现成功后只做轻量刷新并保持响应脱敏。
- Admin Web 租户审计日志只读面板已落地：`GET /api/v1/admin-web/tenant/audit-logs` 只从 cookie 当前克隆 Bot 工作区解析租户，支持 `limit`、`action` 和 `target_type` 筛选；响应只返回创建时间、操作者 Telegram 摘要、action、target_type 和二次裁剪后的安全 metadata，不返回 `audit_log_id`、`tenant_id`、`actor_user_id`、`target_id`、内部数据库 ID、payload、token、secret、API Key、storage key 或原始 `metadata_json`。`web/admin` 右侧审计卡片独立刷新，错误和空态不影响商品、订单、供货、订阅或财务面板。
- Admin Web 风控/售后只读面板已落地：`GET /api/v1/admin-web/tenant/risk` 只从 cookie 当前克隆 Bot 工作区解析租户，支持 `status` 和 `limit`，复用 `RiskControlService` 查询当前租户争议与售后工单并转换为浏览器安全摘要。响应仅返回订单号、买家 Telegram ID、订单来源、订单状态、金额、工单状态、申请/退款金额、安全原因和处理摘要，不返回 `tenant_id`、`dispute_id`、`case_id`、`order_id`、`refund_id`、账本/支付/回调/发货内部 ID、payment URL、provider trade number、payload、raw request/response、API Key、token、secret、storage key 或凭据；备注中出现 URL 或敏感标记时返回 `内容已隐藏`。`web/admin` 右侧“风控与售后”卡片支持状态筛选、独立刷新、加载、错误和空态，不影响商品、订单、供货、订阅、财务或审计面板。
- 一次性绑定码消费接口和前端输入入口已实现；Redis 存储使用短 TTL、HMAC key、一次性消费和消费端限流；Telegram 母 Bot 和克隆 Bot 侧已接入 `/admin_web_code` 生成短期绑定码。母 Bot 未指定 BotID 时按当前 Telegram 用户可访问工作区选择默认工作区，指定 BotID 时只允许 owner 为该克隆 Bot 生成绑定码；克隆 Bot 侧只允许私聊中的 owner/admin 为当前 `tenant_public_id` 工作区生成绑定码。
- 尚未做真实 Telegram WebApp 管理后台联调。
