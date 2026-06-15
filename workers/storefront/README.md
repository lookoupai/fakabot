# Public Store Cloudflare Worker

这是 Public Store 的最小 Cloudflare Workers 前端。它只消费后端公开接口 `/api/v1/store/{tenant_public_id}`，不使用 Tenant Admin API Key，不接触 Bot Token、支付密钥、卡密或租户内部 ID。

## 路由

- `GET /health`：Worker 健康检查。
- `GET /{tenant_public_id}`：店铺页面。
- `GET /`：使用 `DEFAULT_TENANT_PUBLIC_ID` 时的默认店铺页面。
- `/api/v1/store/*`：同源代理到后端 Public Store API。

同源代理用于避开浏览器跨域依赖。浏览器只访问 Worker 域名，Worker 通过 `PUBLIC_STORE_API_BASE_URL` 转发到 FastAPI 后端公开接口。代理使用请求头白名单，只转发 `Accept`、`Content-Type`、`X-Telegram-Init-Data` 和 Worker 自己设置的来源标记，避免 Tenant Admin API Key、签名、Cookie、Bot Token 或支付密钥进入公开后端链路。

支付创建成功后，前端会先校验支付链接只允许 `http/https`，再优先使用 Telegram WebApp `openLink()` 打开支付页；普通浏览器会尝试新窗口打开，并保留订单面板里的支付链接。打开失败时不会把订单流程判定为失败，页面会保留可手动打开的安全支付链接。页面不会在创建支付后直接跳离，因此可以继续轮询 `GET /orders/{out_trade_no}`，直到订单已支付、已发货、过期、取消或轮询达到上限。

前端会把公开订单快照保存到 `sessionStorage`，用于页面刷新或 WebApp 回到前台后继续查询订单状态。页面在 `visibilitychange`、`focus` 和 `pageshow` 回到前台时，会对仍需轮询的订单立即刷新一次并恢复轮询。快照只包含 `tenantPublicId`、`out_trade_no`、金额、币种、状态、过期时间、支付/发货时间和 `can_pay`，不保存支付链接、Telegram initData、API Key、Bot Token 或支付密钥。

## 配置

复制 `wrangler.toml.example` 为部署配置后按环境调整：

- `PUBLIC_STORE_API_BASE_URL`：后端 FastAPI 公开地址，用于 Worker 代理；只允许不带 userinfo、query 或 fragment 的 `http/https` base URL。
- `DEFAULT_TENANT_PUBLIC_ID`：可选，访问根路径 `/` 时使用的店铺 public id。
- `DEFAULT_STORE_TITLE`：页面加载店铺资料前显示的默认标题。
- `PUBLIC_STORE_BROWSER_API_BASE_URL`：可选，浏览器直连 API 的 base URL。默认不设置，前端使用 Worker 同源代理；只允许不带 userinfo、query 或 fragment 的 `http/https` base URL。

不要把 Tenant Admin API Key、支付密钥、Bot Token 或数据库连接串放进 Worker 配置。

## 离线验证

测试会覆盖 Worker 响应、同源代理白名单、POST body 转发、响应头过滤，以及通过 fake DOM 执行浏览器内联脚本的店铺加载、下单、创建支付、支付链接保留和订单轮询流程。

```bash
node --test "workers/storefront/test/*.test.mjs"
```
