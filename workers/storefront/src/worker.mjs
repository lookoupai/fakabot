const DEFAULT_STORE_TITLE = "发卡店铺";
const PUBLIC_STORE_API_PREFIX = "/api/v1/store/";
const ORDER_POLL_MAX_ATTEMPTS = 60;
const TENANT_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

export default {
  async fetch(request, env) {
    return handleRequest(request, env || {});
  },
};

export async function handleRequest(request, env = {}) {
  const url = new URL(request.url);
  if (url.pathname === "/health") {
    return jsonResponse({ status: "ok" });
  }
  if (isPublicStoreApiPath(url.pathname)) {
    return proxyPublicStoreApi(request, env);
  }
  if (request.method !== "GET" && request.method !== "HEAD") {
    return new Response("Method Not Allowed", {
      status: 405,
      headers: { "Allow": "GET, HEAD" },
    });
  }

  const tenantPublicId = resolveTenantPublicId(url, env);
  if (tenantPublicId && !TENANT_ID_PATTERN.test(tenantPublicId)) {
    return new Response("Not Found", { status: 404 });
  }

  const config = buildClientConfig(request, env, tenantPublicId);
  const nonce = createNonce();
  const body = renderHtml(config, nonce);
  return new Response(request.method === "HEAD" ? null : body, {
    status: 200,
    headers: pageHeaders(config.apiBaseUrl, nonce),
  });
}

export function buildClientConfig(request, env = {}, tenantPublicId = "") {
  const requestUrl = new URL(request.url);
  const configuredApiBaseUrl = normalizeAbsoluteHttpUrl(env.PUBLIC_STORE_BROWSER_API_BASE_URL);
  const apiBaseUrl = configuredApiBaseUrl || requestUrl.origin;
  return {
    apiBaseUrl,
    tenantPublicId,
    defaultStoreTitle: String(env.DEFAULT_STORE_TITLE || DEFAULT_STORE_TITLE).trim() || DEFAULT_STORE_TITLE,
    orderPollMaxAttempts: ORDER_POLL_MAX_ATTEMPTS,
  };
}

async function proxyPublicStoreApi(request, env) {
  if (!["GET", "HEAD", "POST"].includes(request.method)) {
    return jsonResponse({ detail: "Method Not Allowed" }, { status: 405, headers: { "Allow": "GET, HEAD, POST" } });
  }

  const backendBaseUrl = normalizeAbsoluteHttpUrl(env.PUBLIC_STORE_API_BASE_URL);
  if (!backendBaseUrl) {
    return jsonResponse({ detail: "Public Store API 未配置" }, { status: 503 });
  }

  const incomingUrl = new URL(request.url);
  const targetUrl = new URL(backendBaseUrl);
  targetUrl.pathname = joinPaths(targetUrl.pathname, incomingUrl.pathname);
  targetUrl.search = incomingUrl.search;

  const headers = publicApiProxyHeaders(request.headers);
  const backendResponse = await fetch(targetUrl.toString(), {
    method: request.method,
    headers,
    body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
    redirect: "manual",
  });

  return new Response(backendResponse.body, {
    status: backendResponse.status,
    statusText: backendResponse.statusText,
    headers: publicApiResponseHeaders(backendResponse.headers),
  });
}

function isPublicStoreApiPath(pathname) {
  return pathname.startsWith(PUBLIC_STORE_API_PREFIX);
}

export function publicApiProxyHeaders(inputHeaders) {
  const input = new Headers(inputHeaders);
  const headers = new Headers();
  for (const name of ["Accept", "Content-Type", "X-Telegram-Init-Data"]) {
    const value = input.get(name);
    if (value) {
      headers.set(name, value);
    }
  }
  const cfConnectingIp = input.get("CF-Connecting-IP");
  if (cfConnectingIp) {
    headers.set("X-Forwarded-For", cfConnectingIp);
  }
  headers.set("X-Fakabot-Storefront", "cloudflare-worker");
  return headers;
}

export function shouldPollPublicOrder(order, attempt = 0, maxAttempts = ORDER_POLL_MAX_ATTEMPTS) {
  if (!order || attempt >= maxAttempts) {
    return false;
  }
  const status = String(order.status || "").toLowerCase();
  if (["delivered", "completed", "expired", "cancelled", "refunded"].includes(status)) {
    return false;
  }
  if (order.delivered_at) {
    return false;
  }
  if (status === "paid" || order.paid_at) {
    return true;
  }
  if (order.can_pay === false) {
    return false;
  }
  return true;
}

function publicApiResponseHeaders(inputHeaders) {
  const headers = new Headers();
  for (const name of ["Content-Type", "Cache-Control", "Location"]) {
    const value = inputHeaders.get(name);
    if (value) {
      headers.set(name, value);
    }
  }
  if (!headers.has("Cache-Control")) {
    headers.set("Cache-Control", "no-store");
  }
  headers.set("X-Content-Type-Options", "nosniff");
  return headers;
}

function resolveTenantPublicId(url, env) {
  const firstSegment = url.pathname.split("/").filter(Boolean)[0] || "";
  if (firstSegment && firstSegment !== "index.html") {
    return firstSegment;
  }
  return String(env.DEFAULT_TENANT_PUBLIC_ID || "").trim();
}

function renderHtml(config, nonce) {
  const serializedConfig = safeJson(config);
  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>${escapeHtml(config.defaultStoreTitle)}</title>
  <style nonce="${nonce}">
    :root {
      --bg: #f6f7f9;
      --surface: #ffffff;
      --surface-soft: #eef2f6;
      --text: #19202a;
      --muted: #687386;
      --line: #dce2ea;
      --line-strong: #c6ceda;
      --accent: #126c5c;
      --accent-strong: #0b4f43;
      --accent-soft: #e1f3ef;
      --danger: #b42318;
      --warning: #9a5b00;
      --success: #067647;
      --shadow: 0 16px 42px rgba(25, 32, 42, 0.08);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      letter-spacing: 0;
    }

    button, input {
      font: inherit;
    }

    button {
      border: 0;
      cursor: pointer;
    }

    button:disabled {
      cursor: not-allowed;
      opacity: .55;
    }

    .shell {
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr;
    }

    .topbar {
      position: sticky;
      top: 0;
      z-index: 4;
      background: rgba(246, 247, 249, .92);
      backdrop-filter: blur(14px);
      border-bottom: 1px solid var(--line);
    }

    .topbar-inner {
      width: min(1180px, calc(100% - 32px));
      min-height: 66px;
      margin: 0 auto;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
    }

    .brand {
      min-width: 0;
      display: grid;
      gap: 3px;
    }

    .brand-title {
      margin: 0;
      font-size: 20px;
      font-weight: 720;
      line-height: 1.25;
    }

    .brand-support {
      margin: 0;
      max-width: 58ch;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.4;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .status-pill {
      min-height: 34px;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 0 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }

    .layout {
      width: min(1180px, calc(100% - 32px));
      margin: 22px auto 36px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) 360px;
      gap: 18px;
      align-items: start;
    }

    .main {
      min-width: 0;
      display: grid;
      gap: 14px;
    }

    .welcome {
      min-height: 96px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      padding: 18px;
      box-shadow: 0 1px 0 rgba(25, 32, 42, .03);
    }

    .welcome p {
      margin: 0;
      color: var(--muted);
      font-size: 15px;
      line-height: 1.65;
      overflow-wrap: anywhere;
    }

    .toolbar {
      min-height: 48px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }

    .section-title {
      margin: 0;
      font-size: 17px;
      font-weight: 700;
    }

    .segmented {
      min-height: 38px;
      display: inline-flex;
      align-items: center;
      padding: 3px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface-soft);
    }

    .segmented button {
      min-width: 62px;
      height: 30px;
      border-radius: 6px;
      background: transparent;
      color: var(--muted);
      font-size: 13px;
    }

    .segmented button[aria-pressed="true"] {
      background: var(--surface);
      color: var(--text);
      box-shadow: 0 1px 2px rgba(25, 32, 42, .08);
    }

    .product-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
      gap: 12px;
    }

    .product-grid.compact {
      grid-template-columns: 1fr;
    }

    .product-card {
      min-height: 172px;
      display: grid;
      grid-template-rows: auto 1fr auto;
      gap: 12px;
      padding: 15px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      box-shadow: 0 1px 0 rgba(25, 32, 42, .03);
      transition: border-color .16s ease, transform .16s ease, box-shadow .16s ease;
    }

    .product-card:hover {
      border-color: var(--line-strong);
      box-shadow: var(--shadow);
      transform: translateY(-1px);
    }

    .product-meta {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }

    .type-chip, .stock-chip {
      max-width: 150px;
      min-height: 26px;
      display: inline-flex;
      align-items: center;
      padding: 0 9px;
      border-radius: 999px;
      font-size: 12px;
      line-height: 1;
      white-space: nowrap;
    }

    .type-chip {
      background: var(--surface-soft);
      color: var(--muted);
    }

    .stock-chip {
      background: var(--accent-soft);
      color: var(--accent-strong);
    }

    .stock-chip.empty {
      background: #f4e9e7;
      color: var(--danger);
    }

    .product-name {
      margin: 0;
      font-size: 16px;
      font-weight: 700;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }

    .product-desc {
      margin: 7px 0 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.55;
      display: -webkit-box;
      -webkit-line-clamp: 3;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }

    .product-foot {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 12px;
    }

    .price {
      font-size: 20px;
      font-weight: 760;
      line-height: 1;
      white-space: nowrap;
    }

    .price span {
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
      margin-left: 4px;
    }

    .primary-btn, .secondary-btn {
      min-height: 38px;
      border-radius: 8px;
      padding: 0 14px;
      font-size: 14px;
      font-weight: 650;
      white-space: nowrap;
    }

    .primary-btn {
      background: var(--accent);
      color: #fff;
    }

    .primary-btn:hover:not(:disabled) {
      background: var(--accent-strong);
    }

    .secondary-btn {
      border: 1px solid var(--line);
      background: var(--surface);
      color: var(--text);
    }

    .side {
      position: sticky;
      top: 86px;
      display: grid;
      gap: 12px;
    }

    .panel {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      box-shadow: 0 1px 0 rgba(25, 32, 42, .03);
    }

    .panel-header {
      padding: 15px 15px 0;
      display: flex;
      align-items: start;
      justify-content: space-between;
      gap: 12px;
    }

    .panel-title {
      margin: 0;
      font-size: 15px;
      font-weight: 720;
    }

    .panel-body {
      display: grid;
      gap: 12px;
      padding: 15px;
    }

    .detail-line {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      color: var(--muted);
      font-size: 13px;
    }

    .detail-line strong {
      color: var(--text);
      font-weight: 680;
      text-align: right;
      overflow-wrap: anywhere;
    }

    .buyer-field {
      display: grid;
      gap: 6px;
    }

    .buyer-field label {
      color: var(--muted);
      font-size: 13px;
      font-weight: 620;
    }

    .buyer-field input {
      width: 100%;
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 0 11px;
      background: var(--surface);
      color: var(--text);
      outline: none;
    }

    .buyer-field input:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(18, 108, 92, .14);
    }

    .message {
      border-radius: 8px;
      padding: 11px 12px;
      font-size: 13px;
      line-height: 1.5;
      overflow-wrap: anywhere;
    }

    .message.info {
      background: var(--surface-soft);
      color: var(--muted);
    }

    .message.error {
      background: #fcebea;
      color: var(--danger);
    }

    .message.warning {
      background: #fff4df;
      color: var(--warning);
    }

    .message.success {
      background: #e8f4ee;
      color: var(--success);
    }

    .order-code {
      padding: 10px 11px;
      border-radius: 8px;
      background: var(--surface-soft);
      font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
      font-size: 13px;
      overflow-wrap: anywhere;
    }

    .button-row {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }

    .button-row .primary-btn,
    .button-row .secondary-btn {
      flex: 1 1 130px;
    }

    .payment-link {
      min-height: 38px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 0 14px;
      color: var(--accent-strong);
      background: var(--accent-soft);
      font-size: 14px;
      font-weight: 650;
      text-decoration: none;
      white-space: nowrap;
    }

    .skeleton {
      min-height: 172px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: linear-gradient(90deg, #ffffff 0%, #eef2f6 50%, #ffffff 100%);
      background-size: 220% 100%;
      animation: pulse 1.2s ease-in-out infinite;
    }

    @keyframes pulse {
      from { background-position: 100% 0; }
      to { background-position: -100% 0; }
    }

    @media (max-width: 860px) {
      .topbar-inner, .layout {
        width: min(100% - 24px, 640px);
      }

      .topbar-inner {
        min-height: 72px;
        align-items: start;
        flex-direction: column;
        justify-content: center;
        gap: 8px;
      }

      .brand-support {
        white-space: normal;
      }

      .layout {
        grid-template-columns: 1fr;
        margin-top: 14px;
      }

      .side {
        position: static;
      }

      .toolbar {
        align-items: stretch;
        flex-direction: column;
      }

      .segmented {
        width: 100%;
      }

      .segmented button {
        flex: 1;
      }
    }

    @media (max-width: 460px) {
      .product-grid {
        grid-template-columns: 1fr;
      }

      .product-foot {
        align-items: stretch;
        flex-direction: column;
      }

      .primary-btn, .secondary-btn {
        width: 100%;
      }
    }
  </style>
</head>
<body>
  <div id="app" class="shell">
    <header class="topbar">
      <div class="topbar-inner">
        <div class="brand">
          <h1 class="brand-title" data-store-name>${escapeHtml(config.defaultStoreTitle)}</h1>
          <p class="brand-support" data-support>正在加载店铺资料</p>
        </div>
        <div class="status-pill" data-telegram-state>Web</div>
      </div>
    </header>

    <main class="layout">
      <section class="main">
        <div class="welcome"><p data-welcome>正在加载</p></div>
        <div class="toolbar">
          <h2 class="section-title">商品</h2>
          <div class="segmented" aria-label="商品视图">
            <button type="button" data-view="grid" aria-pressed="true">网格</button>
            <button type="button" data-view="compact" aria-pressed="false">列表</button>
          </div>
        </div>
        <div class="product-grid" data-products>
          <div class="skeleton"></div>
          <div class="skeleton"></div>
          <div class="skeleton"></div>
        </div>
      </section>

      <aside class="side">
        <section class="panel" data-detail-panel>
          <div class="panel-header">
            <h2 class="panel-title">商品详情</h2>
          </div>
          <div class="panel-body" data-detail>
            <div class="message info">请选择商品</div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-header">
            <h2 class="panel-title">订单</h2>
          </div>
          <div class="panel-body" data-order>
            <div class="message info">暂无订单</div>
          </div>
        </section>
      </aside>
    </main>
  </div>

  <script nonce="${nonce}" src="https://telegram.org/js/telegram-web-app.js"></script>
  <script nonce="${nonce}">window.__FAKABOT_STORE__ = ${serializedConfig};</script>
  <script nonce="${nonce}">
(() => {
  const config = window.__FAKABOT_STORE__;
  const telegram = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  const state = {
    profile: null,
    products: [],
    selectedProduct: null,
    order: null,
    paymentUrl: null,
    pollTimer: null,
    pollAttempt: 0,
    view: "grid",
    loadingOrder: false,
    loadingPayment: false,
    refreshingOrder: false,
  };

  const nodes = {
    storeName: document.querySelector("[data-store-name]"),
    support: document.querySelector("[data-support]"),
    telegramState: document.querySelector("[data-telegram-state]"),
    welcome: document.querySelector("[data-welcome]"),
    products: document.querySelector("[data-products]"),
    detail: document.querySelector("[data-detail]"),
    order: document.querySelector("[data-order]"),
    viewButtons: Array.from(document.querySelectorAll("[data-view]")),
  };

  function initTelegram() {
    if (!telegram) {
      nodes.telegramState.textContent = "Web";
      return;
    }
    telegram.ready();
    telegram.expand();
    nodes.telegramState.textContent = telegram.initDataUnsafe && telegram.initDataUnsafe.user ? "Telegram" : "WebApp";
  }

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    headers.set("Accept", "application/json");
    if (options.body && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    if (telegram && telegram.initData) {
      headers.set("X-Telegram-Init-Data", telegram.initData);
    }
    const response = await fetch(config.apiBaseUrl + path, { ...options, headers });
    const payload = await readJson(response);
    if (!response.ok) {
      throw apiError(response.status, payload && payload.detail);
    }
    return payload;
  }

  function apiError(status, detail) {
    const error = new Error(apiErrorMessage(status, detail));
    error.status = status;
    return error;
  }

  function apiErrorMessage(status, detail) {
    if (status === 429) return "请求过于频繁，请稍后再试";
    if (status === 503) return "服务暂不可用，请稍后重试";
    if (status === 401) return "身份校验失败，请在 Telegram 内重新打开";
    if (status === 403) return "当前无法完成操作";
    if (status === 404) return "内容不存在或已失效";
    if (status >= 500) return "服务暂时异常，请稍后重试";
    return safeErrorDetail(detail) || "请求失败";
  }

  function safeErrorDetail(detail) {
    const value = String(detail || "").trim();
    if (!value) return "";
    const lowered = value.toLowerCase();
    if (value.length > 120) return "";
    if (/[\\r\\n\\t]/.test(value)) return "";
    if (lowered.includes("http://") || lowered.includes("https://")) return "";
    if (/[\\\\/]/.test(value)) return "";
    if ([
      "api_key",
      "apikey",
      "authorization",
      "cookie",
      "credential",
      "download_token",
      "payment_url",
      "payload",
      "plain_key",
      "provider_trade_no",
      "raw_request",
      "raw_response",
      "secret",
      "signature",
      "signing_text",
      "storage_key",
      "token",
    ].some((marker) => lowered.includes(marker))) {
      return "";
    }
    return value;
  }

  async function readJson(response) {
    const text = await response.text();
    if (!text) return null;
    try {
      return JSON.parse(text);
    } catch (error) {
      return null;
    }
  }

  function storePath(path) {
    return "/api/v1/store/" + encodeURIComponent(config.tenantPublicId || "") + path;
  }

  async function loadStore() {
    if (!config.tenantPublicId) {
      renderFatal("缺少店铺标识");
      return;
    }
    try {
      const [profile, products] = await Promise.all([
        api(storePath("/profile")),
        api(storePath("/products")),
      ]);
      state.profile = profile;
      state.products = products;
      state.selectedProduct = products[0] || null;
      renderProfile();
      renderProducts();
      renderDetail();
      restoreOrderSnapshot();
    } catch (error) {
      renderFatal(error.message || "店铺加载失败");
    }
  }

  function renderProfile() {
    const profile = state.profile;
    document.title = profile.store_name;
    nodes.storeName.textContent = profile.store_name;
    nodes.support.textContent = profile.support || "暂未配置客服联系方式";
    nodes.welcome.textContent = profile.welcome || "欢迎光临";
  }

  function renderProducts() {
    nodes.products.classList.toggle("compact", state.view === "compact");
    if (!state.products.length) {
      nodes.products.innerHTML = '<div class="message info">暂无商品</div>';
      return;
    }
    nodes.products.innerHTML = state.products.map((product) => productCard(product)).join("");
    for (const button of nodes.products.querySelectorAll("[data-product-id]")) {
      button.addEventListener("click", () => {
        state.selectedProduct = state.products.find((item) => item.id === button.dataset.productId) || null;
        renderDetail();
      });
    }
  }

  function productCard(product) {
    const selected = state.selectedProduct && state.selectedProduct.id === product.id;
    const stockEmpty = product.stock_status === "empty" || product.stock_status === "sold_out";
    return '<article class="product-card">' +
      '<div class="product-meta">' +
        '<span class="type-chip">' + escapeHtml(deliveryTypeLabel(product.delivery_type)) + '</span>' +
        '<span class="stock-chip ' + (stockEmpty ? "empty" : "") + '">' + escapeHtml(stockLabel(product.stock_status)) + '</span>' +
      '</div>' +
      '<div>' +
        '<h3 class="product-name">' + escapeHtml(product.name) + '</h3>' +
        (product.description ? '<p class="product-desc">' + escapeHtml(product.description) + '</p>' : '') +
      '</div>' +
      '<div class="product-foot">' +
        '<div class="price">' + escapeHtml(formatPrice(product.price)) + '<span>' + escapeHtml(product.currency) + '</span></div>' +
        '<button class="' + (selected ? "secondary-btn" : "primary-btn") + '" type="button" data-product-id="' + escapeHtml(product.id) + '">' + (selected ? "已选择" : "选择") + '</button>' +
      '</div>' +
    '</article>';
  }

  function renderDetail(message) {
    const product = state.selectedProduct;
    if (!product) {
      nodes.detail.innerHTML = '<div class="message info">请选择商品</div>';
      return;
    }
    const telegramUser = telegram && telegram.initDataUnsafe && telegram.initDataUnsafe.user ? telegram.initDataUnsafe.user : null;
    nodes.detail.innerHTML =
      (message ? '<div class="message ' + escapeHtml(message.type) + '">' + escapeHtml(message.text) + '</div>' : '') +
      '<div class="detail-line"><span>商品</span><strong>' + escapeHtml(product.name) + '</strong></div>' +
      '<div class="detail-line"><span>发货</span><strong>' + escapeHtml(deliveryTypeLabel(product.delivery_type)) + '</strong></div>' +
      '<div class="detail-line"><span>库存</span><strong>' + escapeHtml(stockLabel(product.stock_status)) + '</strong></div>' +
      '<div class="detail-line"><span>金额</span><strong>' + escapeHtml(formatPrice(product.price) + " " + product.currency) + '</strong></div>' +
      (!telegramUser ? '<div class="buyer-field"><label for="buyer-id">Telegram 用户 ID</label><input id="buyer-id" data-buyer-id inputmode="numeric" autocomplete="off"></div>' : '') +
      '<button class="primary-btn" type="button" data-create-order ' + (state.loadingOrder ? "disabled" : "") + '>下单</button>';
    const button = nodes.detail.querySelector("[data-create-order]");
    if (button) button.addEventListener("click", createOrder);
  }

  function renderOrder(message) {
    const order = state.order;
    if (!order) {
      nodes.order.innerHTML = message ? '<div class="message ' + escapeHtml(message.type) + '">' + escapeHtml(message.text) + '</div>' : '<div class="message info">暂无订单</div>';
      return;
    }
    nodes.order.innerHTML =
      (message ? '<div class="message ' + escapeHtml(message.type) + '">' + escapeHtml(message.text) + '</div>' : '') +
      '<div class="order-code">' + escapeHtml(order.out_trade_no) + '</div>' +
      '<div class="detail-line"><span>状态</span><strong>' + escapeHtml(orderStatusLabel(order.status)) + '</strong></div>' +
      '<div class="detail-line"><span>金额</span><strong>' + escapeHtml(formatPrice(order.amount) + " " + order.currency) + '</strong></div>' +
      '<div class="detail-line"><span>有效期</span><strong>' + escapeHtml(formatDateTime(order.expires_at)) + '</strong></div>' +
      (order.paid_at ? '<div class="detail-line"><span>支付时间</span><strong>' + escapeHtml(formatDateTime(order.paid_at)) + '</strong></div>' : '') +
      (order.delivered_at ? '<div class="detail-line"><span>发货时间</span><strong>' + escapeHtml(formatDateTime(order.delivered_at)) + '</strong></div>' : '') +
      (state.paymentUrl ? '<a class="payment-link" data-payment-link href="' + escapeHtml(state.paymentUrl) + '" target="_blank" rel="noopener noreferrer">打开支付页</a>' : '') +
      '<div class="button-row">' +
        '<button class="primary-btn" type="button" data-create-payment ' + (!order.can_pay || state.loadingPayment ? "disabled" : "") + '>支付</button>' +
        '<button class="secondary-btn" type="button" data-refresh-order ' + (state.refreshingOrder ? "disabled" : "") + '>刷新</button>' +
      '</div>';
    const paymentButton = nodes.order.querySelector("[data-create-payment]");
    const refreshButton = nodes.order.querySelector("[data-refresh-order]");
    if (paymentButton) paymentButton.addEventListener("click", createPayment);
    if (refreshButton) refreshButton.addEventListener("click", () => refreshOrderStatus({ silent: false }));
  }

  async function createOrder() {
    if (!state.selectedProduct || state.loadingOrder) return;
    const telegramUser = telegram && telegram.initDataUnsafe && telegram.initDataUnsafe.user ? telegram.initDataUnsafe.user : null;
    const buyerInput = document.querySelector("[data-buyer-id]");
    const buyerId = telegramUser ? telegramUser.id : Number((buyerInput && buyerInput.value || "").trim());
    if (!buyerId || buyerId <= 0) {
      renderDetail({ type: "error", text: "请填写 Telegram 用户 ID" });
      return;
    }
    state.loadingOrder = true;
    renderDetail();
    try {
      stopOrderPolling();
      state.paymentUrl = null;
      const order = await api(storePath("/orders"), {
        method: "POST",
        body: JSON.stringify({
          product_id: state.selectedProduct.id,
          source_type: state.selectedProduct.source_type,
          buyer_telegram_user_id: buyerId,
          telegram_init_data: telegram ? telegram.initData : undefined,
        }),
      });
      state.order = order;
      saveOrderSnapshot(order);
      renderOrder({ type: "success", text: "订单已创建" });
    } catch (error) {
      renderDetail({ type: "error", text: error.message || "下单失败" });
    } finally {
      state.loadingOrder = false;
      renderDetail();
    }
  }

  async function createPayment() {
    if (!state.order || state.loadingPayment) return;
    state.loadingPayment = true;
    renderOrder();
    try {
      const payment = await api(storePath("/orders/" + encodeURIComponent(state.order.out_trade_no) + "/payment"), {
        method: "POST",
      });
      const paymentUrl = normalizePaymentUrl(payment && payment.payment_url);
      if (!paymentUrl) {
        throw new Error("支付链接无效，请联系商家");
      }
      state.paymentUrl = paymentUrl;
      state.loadingPayment = false;
      const opened = openPaymentUrl(paymentUrl);
      startOrderPolling();
      renderOrder({
        type: opened ? "success" : "info",
        text: opened ? "支付页已打开，正在刷新订单状态" : "支付页未自动打开，请使用下方链接",
      });
    } catch (error) {
      state.loadingPayment = false;
      renderOrder({ type: "error", text: error.message || "支付创建失败" });
    }
  }

  async function refreshOrderStatus({ silent } = { silent: true }) {
    if (!state.order || state.refreshingOrder) return;
    state.refreshingOrder = true;
    if (!silent) renderOrder();
    try {
      const order = await api(storePath("/orders/" + encodeURIComponent(state.order.out_trade_no)));
      state.order = order;
      saveOrderSnapshot(order);
      if (!shouldPollOrder(order)) {
        stopOrderPolling();
      }
      state.refreshingOrder = false;
      if (!silent) {
        renderOrder({ type: "success", text: "订单状态已刷新" });
      } else {
        renderOrder();
      }
    } catch (error) {
      stopOrderPolling();
      state.refreshingOrder = false;
      if (!silent) {
        renderOrder({ type: "error", text: error.message || "订单刷新失败" });
      } else {
        renderOrder({ type: "warning", text: "订单状态暂时无法刷新，可稍后手动刷新" });
      }
    } finally {
      state.refreshingOrder = false;
    }
  }

  function startOrderPolling() {
    stopOrderPolling();
    if (!shouldPollOrder(state.order)) return;
    state.pollAttempt = 0;
    state.pollTimer = window.setInterval(async () => {
      state.pollAttempt += 1;
      if (!shouldPollOrder(state.order, state.pollAttempt)) {
        stopOrderPolling();
        return;
      }
      await refreshOrderStatus({ silent: true });
    }, 5000);
  }

  function stopOrderPolling() {
    if (state.pollTimer) {
      window.clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
    state.pollAttempt = 0;
  }

  function shouldPollOrder(order, attempt) {
    if (!order) return false;
    if ((attempt || 0) >= config.orderPollMaxAttempts) return false;
    const status = String(order.status || "").toLowerCase();
    if (["delivered", "completed", "expired", "cancelled", "refunded"].includes(status)) return false;
    if (order.delivered_at) return false;
    if (status === "paid" || order.paid_at) return true;
    if (order.can_pay === false) return false;
    return true;
  }

  function openPaymentUrl(paymentUrl) {
    const safeUrl = normalizePaymentUrl(paymentUrl);
    if (!safeUrl) return false;
    try {
      if (telegram && typeof telegram.openLink === "function") {
        telegram.openLink(safeUrl);
        return true;
      }
      const opened = window.open(safeUrl, "_blank", "noopener,noreferrer");
      return Boolean(opened);
    } catch (error) {
      return false;
    }
  }

  function normalizePaymentUrl(value) {
    const rawValue = String(value || "").trim();
    if (!rawValue) return "";
    try {
      const url = new URL(rawValue);
      if (url.protocol !== "http:" && url.protocol !== "https:") return "";
      if (url.username || url.password) return "";
      return url.toString();
    } catch (error) {
      return "";
    }
  }

  function saveOrderSnapshot(order) {
    const storage = safeSessionStorage();
    if (!storage || !order || !order.out_trade_no) return;
    const snapshot = {
      tenantPublicId: config.tenantPublicId,
      out_trade_no: order.out_trade_no,
      amount: order.amount,
      currency: order.currency,
      status: order.status,
      expires_at: order.expires_at,
      paid_at: order.paid_at || null,
      delivered_at: order.delivered_at || null,
      can_pay: Boolean(order.can_pay),
    };
    storage.setItem(orderSnapshotKey(), JSON.stringify(snapshot));
  }

  function restoreOrderSnapshot() {
    const storage = safeSessionStorage();
    if (!storage) return;
    const rawSnapshot = storage.getItem(orderSnapshotKey());
    if (!rawSnapshot) return;
    try {
      const snapshot = JSON.parse(rawSnapshot);
      if (!snapshot || snapshot.tenantPublicId !== config.tenantPublicId || !snapshot.out_trade_no) return;
      state.order = {
        out_trade_no: snapshot.out_trade_no,
        amount: snapshot.amount,
        currency: snapshot.currency,
        status: snapshot.status,
        expires_at: snapshot.expires_at,
        paid_at: snapshot.paid_at || null,
        delivered_at: snapshot.delivered_at || null,
        can_pay: Boolean(snapshot.can_pay),
      };
      state.paymentUrl = null;
      renderOrder();
      if (shouldPollOrder(state.order)) {
        startOrderPolling();
      }
    } catch (error) {
      storage.removeItem(orderSnapshotKey());
    }
  }

  function registerForegroundRefresh() {
    const refresh = () => {
      if (document.visibilityState && document.visibilityState !== "visible") return;
      if (!shouldPollOrder(state.order) || state.refreshingOrder) return;
      refreshOrderStatus({ silent: true });
      if (!state.pollTimer && shouldPollOrder(state.order)) {
        startOrderPolling();
      }
    };
    if (typeof document.addEventListener === "function") {
      document.addEventListener("visibilitychange", refresh);
    }
    if (typeof window.addEventListener === "function") {
      window.addEventListener("focus", refresh);
      window.addEventListener("pageshow", refresh);
    }
  }

  function orderSnapshotKey() {
    return "fakabot:storefront:order:" + config.tenantPublicId;
  }

  function safeSessionStorage() {
    try {
      return window.sessionStorage || null;
    } catch (error) {
      return null;
    }
  }

  function renderFatal(message) {
    stopOrderPolling();
    nodes.welcome.textContent = message;
    nodes.products.innerHTML = '<div class="message error">' + escapeHtml(message) + '</div>';
    nodes.detail.innerHTML = '<div class="message error">' + escapeHtml(message) + '</div>';
    nodes.order.innerHTML = '<div class="message info">暂无订单</div>';
  }

  function deliveryTypeLabel(value) {
    return {
      card_pool: "卡密",
      card_fixed: "文本",
      telegram_invite: "群邀请",
      file_download: "文件",
    }[value] || value || "商品";
  }

  function stockLabel(value) {
    return {
      available: "有货",
      in_stock: "有货",
      unlimited: "可售",
      low: "库存紧张",
      empty: "售罄",
      sold_out: "售罄",
    }[value] || value || "可售";
  }

  function orderStatusLabel(value) {
    return {
      pending: "待支付",
      paid: "已支付",
      delivered: "已发货",
      expired: "已过期",
      cancelled: "已取消",
    }[value] || value || "未知";
  }

  function formatPrice(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return String(value);
    return number.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 8 });
  }

  function formatDateTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value || "";
    return date.toLocaleString("zh-CN", { hour12: false });
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  for (const button of nodes.viewButtons) {
    button.addEventListener("click", () => {
      state.view = button.dataset.view;
      for (const candidate of nodes.viewButtons) {
        candidate.setAttribute("aria-pressed", candidate === button ? "true" : "false");
      }
      renderProducts();
    });
  }

  initTelegram();
  registerForegroundRefresh();
  loadStore();
})();
  </script>
</body>
</html>`;
}

function pageHeaders(apiBaseUrl, nonce) {
  const connectSource = new URL(apiBaseUrl).origin;
  return {
    "Content-Type": "text/html; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": [
      "default-src 'none'",
      `script-src 'nonce-${nonce}' https://telegram.org`,
      `style-src 'nonce-${nonce}'`,
      "img-src 'self' data:",
      `connect-src 'self' ${connectSource}`,
      "font-src 'self'",
      "base-uri 'none'",
      "form-action 'none'",
      "frame-ancestors https://web.telegram.org https://*.telegram.org",
    ].join("; "),
  };
}

function jsonResponse(payload, init = {}) {
  const headers = new Headers(init.headers || {});
  headers.set("Content-Type", "application/json; charset=utf-8");
  return new Response(JSON.stringify(payload), {
    ...init,
    headers,
  });
}

function safeJson(value) {
  return JSON.stringify(value)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function trimTrailingSlash(value) {
  return value.replace(/\/+$/, "");
}

function joinPaths(basePath, incomingPath) {
  const normalizedBase = basePath && basePath !== "/" ? basePath.replace(/\/+$/, "") : "";
  return `${normalizedBase}${incomingPath}`;
}

function normalizeAbsoluteHttpUrl(value) {
  const rawValue = String(value || "").trim();
  if (!rawValue) {
    return "";
  }
  try {
    const url = new URL(rawValue);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return "";
    }
    if (url.username || url.password || url.search || url.hash) {
      return "";
    }
    return trimTrailingSlash(url.toString());
  } catch (error) {
    return "";
  }
}

function createNonce() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
    return globalThis.crypto.randomUUID().replace(/-/g, "");
  }
  return Math.random().toString(36).slice(2);
}
