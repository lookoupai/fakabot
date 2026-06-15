import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";

import {
  buildClientConfig,
  handleRequest,
  publicApiProxyHeaders,
  shouldPollPublicOrder,
} from "../src/worker.mjs";

test("health endpoint returns ok json", async () => {
  const response = await handleRequest(new Request("https://shop.example/health"));

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("Content-Type"), "application/json; charset=utf-8");
  assert.deepEqual(await response.json(), { status: "ok" });
});

test("storefront page injects tenant config without exposing backend api url", async () => {
  const response = await handleRequest(
    new Request("https://shop.example/demo-store"),
    {
      PUBLIC_STORE_API_BASE_URL: "https://api.internal.example",
      DEFAULT_STORE_TITLE: "演示店铺",
    },
  );
  const html = await response.text();

  assert.equal(response.status, 200);
  assert.match(response.headers.get("Content-Security-Policy"), /default-src 'none'/);
  assert.match(response.headers.get("Content-Security-Policy"), /connect-src 'self' https:\/\/shop\.example/);
  assert.match(html, /"apiBaseUrl":"https:\/\/shop\.example"/);
  assert.match(html, /"tenantPublicId":"demo-store"/);
  assert.doesNotMatch(html, /api\.internal\.example/);
  assert.match(html, /演示店铺/);
});

test("storefront page keeps payment page and polls order status", async () => {
  const response = await handleRequest(new Request("https://shop.example/demo-store"));
  const html = await response.text();

  assert.match(html, /function startOrderPolling\(\)/);
  assert.match(html, /function refreshOrderStatus/);
  assert.match(html, /function shouldPollOrder/);
  assert.match(html, /function restoreOrderSnapshot/);
  assert.match(html, /window\.sessionStorage/);
  assert.match(html, /data-payment-link/);
  assert.match(html, /telegram\.openLink\(safeUrl\)/);
  assert.match(html, /window\.open\(safeUrl, "_blank"/);
  assert.doesNotMatch(html, /window\.location\.assign\(payment\.payment_url\)/);
});

test("storefront browser script completes order payment and polling flow offline", async () => {
  const response = await handleRequest(new Request("https://shop.example/demo-store"), {
    DEFAULT_STORE_TITLE: "演示店铺",
  });
  const html = await response.text();
  const config = extractStorefrontConfig(html);
  const script = extractStorefrontRuntimeScript(html);
  const document = new FakeDocument();
  const sessionStorage = new FakeSessionStorage();
  const fetchCalls = [];
  const openedLinks = [];
  const intervals = [];
  let orderStatusFetchCount = 0;

  const context = vm.createContext({
    Headers,
    Response,
    URL,
    console,
    document,
    fetch: async (url, init = {}) => {
      const headers = new Headers(init.headers || {});
      fetchCalls.push({ url: String(url), init, headers });
      return publicStoreApiResponse(String(url), init, () => {
        orderStatusFetchCount += 1;
        return orderStatusFetchCount === 1 ? pendingPaidOrder() : deliveredOrder();
      });
    },
    window: {
      __FAKABOT_STORE__: config,
      Telegram: {
        WebApp: {
          initData: "telegram-init-data-secret",
          initDataUnsafe: { user: { id: 998877 } },
          readyCalled: false,
          expandCalled: false,
          ready() {
            this.readyCalled = true;
          },
          expand() {
            this.expandCalled = true;
          },
          openLink(url) {
            openedLinks.push(url);
          },
        },
      },
      sessionStorage,
      open() {
        throw new Error("payment should use Telegram openLink in WebApp context");
      },
      location: {
        assign() {
          throw new Error("storefront must not navigate away after payment creation");
        },
      },
      setInterval(callback, delay) {
        const id = intervals.length + 1;
        intervals.push({ id, callback, delay, active: true });
        return id;
      },
      clearInterval(id) {
        const interval = intervals.find((item) => item.id === id);
        if (interval) interval.active = false;
      },
    },
  });

  vm.runInContext(script, context);

  await waitFor(() => document.title === "演示店铺" && document.querySelector("[data-create-order]"));

  assert.equal(context.window.Telegram.WebApp.readyCalled, true);
  assert.equal(context.window.Telegram.WebApp.expandCalled, true);
  assert.equal(document.querySelector("[data-store-name]").textContent, "演示店铺");
  assert.equal(document.querySelector("[data-telegram-state]").textContent, "Telegram");
  assert.equal(fetchCalls[0].headers.get("X-Telegram-Init-Data"), "telegram-init-data-secret");
  assert.equal(fetchCalls[1].headers.get("X-Telegram-Init-Data"), "telegram-init-data-secret");

  await document.querySelector("[data-create-order]").click();
  await waitFor(() => document.querySelector("[data-create-payment]"));

  const orderRequest = fetchCalls.find((call) => call.url.endsWith("/orders") && call.init.method === "POST");
  assert.ok(orderRequest);
  assert.equal(orderRequest.headers.get("Content-Type"), "application/json");
  assert.equal(orderRequest.headers.get("X-Telegram-Init-Data"), "telegram-init-data-secret");
  assert.deepEqual(JSON.parse(orderRequest.init.body), {
    product_id: "signed-product-1",
    source_type: "self",
    buyer_telegram_user_id: 998877,
    telegram_init_data: "telegram-init-data-secret",
  });

  const snapshotAfterOrder = JSON.parse(sessionStorage.getItem("fakabot:storefront:order:demo-store"));
  assert.equal(snapshotAfterOrder.out_trade_no, "ORD_PUBLIC_1");
  assert.equal(snapshotAfterOrder.status, "pending");
  assert.doesNotMatch(JSON.stringify(snapshotAfterOrder), /pay\.example|telegram-init-data-secret|secret/i);

  await document.querySelector("[data-create-payment]").click();
  await waitFor(() => openedLinks.length === 1 && document.querySelector("[data-payment-link]"));

  assert.equal(openedLinks[0], "https://pay.example/checkout/ORD_PUBLIC_1?token=provider-secret");
  assert.equal(document.querySelector("[data-payment-link]").getAttribute("href"), openedLinks[0]);
  assert.equal(intervals.length, 1);
  assert.equal(intervals[0].delay, 5000);
  assert.equal(intervals[0].active, true);

  await intervals[0].callback();
  assert.equal(intervals[0].active, true);
  await intervals[0].callback();
  await waitFor(() => !intervals[0].active);

  const statusRequest = fetchCalls.find((call) => call.url.endsWith("/orders/ORD_PUBLIC_1") && !call.init.method);
  assert.ok(statusRequest);
  assert.equal(statusRequest.headers.get("X-Telegram-Init-Data"), "telegram-init-data-secret");
  assert.match(document.querySelector("[data-order]").innerHTML, /已发货/);

  const finalSnapshot = JSON.parse(sessionStorage.getItem("fakabot:storefront:order:demo-store"));
  assert.equal(finalSnapshot.status, "delivered");
  assert.equal(finalSnapshot.delivered_at, "2026-06-08T10:03:00Z");
  assert.doesNotMatch(JSON.stringify(finalSnapshot), /pay\.example|telegram-init-data-secret|provider-secret/i);
});

test("storefront browser script refreshes restored order when page returns to foreground", async () => {
  const response = await handleRequest(new Request("https://shop.example/demo-store"), {
    DEFAULT_STORE_TITLE: "演示店铺",
  });
  const html = await response.text();
  const config = extractStorefrontConfig(html);
  const script = extractStorefrontRuntimeScript(html);
  const document = new FakeDocument();
  const sessionStorage = new FakeSessionStorage();
  const fetchCalls = [];
  const intervals = [];
  const windowListeners = new Map();
  sessionStorage.setItem(
    "fakabot:storefront:order:demo-store",
    JSON.stringify({
      tenantPublicId: "demo-store",
      out_trade_no: "ORD_PUBLIC_1",
      amount: "9.90",
      currency: "USDT",
      status: "paid",
      expires_at: "2026-06-08T10:30:00Z",
      paid_at: "2026-06-08T10:02:00Z",
      delivered_at: null,
      can_pay: false,
    }),
  );

  const context = vm.createContext({
    Headers,
    Response,
    URL,
    console,
    document,
    fetch: async (url, init = {}) => {
      fetchCalls.push({ url: String(url), init });
      return publicStoreApiResponse(String(url), init, deliveredOrder);
    },
    window: {
      __FAKABOT_STORE__: config,
      Telegram: {
        WebApp: {
          initData: "telegram-init-data-secret",
          initDataUnsafe: { user: { id: 998877 } },
          ready() {},
          expand() {},
          openLink() {},
        },
      },
      sessionStorage,
      open() {
        throw new Error("payment should not open during foreground refresh");
      },
      setInterval(callback, delay) {
        const id = intervals.length + 1;
        intervals.push({ id, callback, delay, active: true });
        return id;
      },
      clearInterval(id) {
        const interval = intervals.find((item) => item.id === id);
        if (interval) interval.active = false;
      },
      addEventListener(name, listener) {
        windowListeners.set(name, listener);
      },
    },
  });

  vm.runInContext(script, context);

  await waitFor(() => document.querySelector("[data-order]").innerHTML.includes("ORD_PUBLIC_1"));
  assert.equal(intervals.length, 1);
  assert.equal(intervals[0].active, true);
  assert.equal(fetchCalls.filter((call) => call.url.endsWith("/orders/ORD_PUBLIC_1")).length, 0);

  windowListeners.get("focus")();
  await waitFor(() => document.querySelector("[data-order]").innerHTML.includes("已发货"));

  assert.equal(intervals[0].active, false);
  assert.equal(fetchCalls.filter((call) => call.url.endsWith("/orders/ORD_PUBLIC_1")).length, 1);
  const snapshot = JSON.parse(sessionStorage.getItem("fakabot:storefront:order:demo-store"));
  assert.equal(snapshot.status, "delivered");
  assert.equal(snapshot.delivered_at, "2026-06-08T10:03:00Z");
});

test("storefront browser script rejects unsafe payment urls before opening or rendering", async () => {
  const response = await handleRequest(new Request("https://shop.example/demo-store"), {
    DEFAULT_STORE_TITLE: "演示店铺",
  });
  const html = await response.text();
  const config = extractStorefrontConfig(html);
  const script = extractStorefrontRuntimeScript(html);
  const document = new FakeDocument();
  const sessionStorage = new FakeSessionStorage();
  const openedLinks = [];

  const context = vm.createContext({
    Headers,
    Response,
    URL,
    console,
    document,
    fetch: async (url, init = {}) => {
      const parsed = new URL(String(url));
      const method = init.method || "GET";
      if (method === "GET" && parsed.pathname.endsWith("/profile")) {
        return jsonApiResponse({
          public_id: "demo-store",
          store_name: "演示店铺",
          welcome: "欢迎测试",
          support: "@support",
        });
      }
      if (method === "GET" && parsed.pathname.endsWith("/products")) {
        return jsonApiResponse([
          {
            id: "signed-product-1",
            source_type: "self",
            name: "测试卡密",
            price: "9.90",
            currency: "USDT",
            delivery_type: "card_pool",
            stock_status: "available",
          },
        ]);
      }
      if (method === "POST" && parsed.pathname.endsWith("/orders")) {
        return jsonApiResponse(pendingOrder());
      }
      if (method === "POST" && parsed.pathname.endsWith("/orders/ORD_PUBLIC_1/payment")) {
        return jsonApiResponse({ payment_url: "javascript:alert('secret')" });
      }
      return jsonApiResponse({ detail: "not found" }, { status: 404 });
    },
    window: {
      __FAKABOT_STORE__: config,
      Telegram: {
        WebApp: {
          initData: "telegram-init-data-secret",
          initDataUnsafe: { user: { id: 998877 } },
          ready() {},
          expand() {},
          openLink(url) {
            openedLinks.push(url);
          },
        },
      },
      sessionStorage,
      open(url) {
        openedLinks.push(url);
        return true;
      },
      setInterval() {
        throw new Error("unsafe payment url must not start polling");
      },
      clearInterval() {},
    },
  });

  vm.runInContext(script, context);

  await waitFor(() => document.querySelector("[data-create-order]"));
  await document.querySelector("[data-create-order]").click();
  await waitFor(() => document.querySelector("[data-create-payment]"));
  await document.querySelector("[data-create-payment]").click();
  await waitFor(() => document.querySelector("[data-order]").innerHTML.includes("支付链接无效"));

  assert.deepEqual(openedLinks, []);
  assert.equal(document.querySelector("[data-payment-link]"), null);
  assert.doesNotMatch(document.querySelector("[data-order]").innerHTML, /javascript:alert|secret/);
  assert.doesNotMatch(JSON.stringify(sessionStorage.getItem("fakabot:storefront:order:demo-store")), /javascript|secret/i);
});

test("storefront browser script shows safe payment unavailable message without leaking backend detail", async () => {
  const response = await handleRequest(new Request("https://shop.example/demo-store"), {
    DEFAULT_STORE_TITLE: "演示店铺",
  });
  const html = await response.text();
  const config = extractStorefrontConfig(html);
  const script = extractStorefrontRuntimeScript(html);
  const document = new FakeDocument();
  const sessionStorage = new FakeSessionStorage();
  const openedLinks = [];

  const context = vm.createContext({
    Headers,
    Response,
    URL,
    console,
    document,
    fetch: async (url, init = {}) => {
      const parsed = new URL(String(url));
      const method = init.method || "GET";
      if (method === "GET" && parsed.pathname.endsWith("/profile")) {
        return jsonApiResponse({ public_id: "demo-store", store_name: "演示店铺", welcome: "欢迎测试" });
      }
      if (method === "GET" && parsed.pathname.endsWith("/products")) {
        return jsonApiResponse([
          {
            id: "signed-product-1",
            source_type: "self",
            name: "测试卡密",
            price: "9.90",
            currency: "USDT",
            delivery_type: "card_pool",
            stock_status: "available",
          },
        ]);
      }
      if (method === "POST" && parsed.pathname.endsWith("/orders")) {
        return jsonApiResponse(pendingOrder());
      }
      if (method === "POST" && parsed.pathname.endsWith("/orders/ORD_PUBLIC_1/payment")) {
        return jsonApiResponse(
          { detail: "payment_url=https://pay.example/checkout?token=provider-secret" },
          { status: 503 },
        );
      }
      return jsonApiResponse({ detail: "not found" }, { status: 404 });
    },
    window: {
      __FAKABOT_STORE__: config,
      Telegram: {
        WebApp: {
          initData: "telegram-init-data-secret",
          initDataUnsafe: { user: { id: 998877 } },
          ready() {},
          expand() {},
          openLink(url) {
            openedLinks.push(url);
          },
        },
      },
      sessionStorage,
      open(url) {
        openedLinks.push(url);
        return true;
      },
      setInterval() {
        throw new Error("failed payment must not start polling");
      },
      clearInterval() {},
    },
  });

  vm.runInContext(script, context);

  await waitFor(() => document.querySelector("[data-create-order]"));
  await document.querySelector("[data-create-order]").click();
  await waitFor(() => document.querySelector("[data-create-payment]"));
  await document.querySelector("[data-create-payment]").click();
  await waitFor(() => document.querySelector("[data-order]").innerHTML.includes("服务暂不可用"));

  assert.deepEqual(openedLinks, []);
  assert.equal(document.querySelector("[data-payment-link]"), null);
  assert.doesNotMatch(document.querySelector("[data-order]").innerHTML, /payment_url|provider-secret|pay\.example|token/i);
  assert.doesNotMatch(JSON.stringify(sessionStorage.getItem("fakabot:storefront:order:demo-store")), /provider-secret|payment_url|pay\.example|token/i);
});

test("storefront browser script shows safe order refresh rate-limit message without leaking detail", async () => {
  const response = await handleRequest(new Request("https://shop.example/demo-store"), {
    DEFAULT_STORE_TITLE: "演示店铺",
  });
  const html = await response.text();
  const config = extractStorefrontConfig(html);
  const script = extractStorefrontRuntimeScript(html);
  const document = new FakeDocument();
  const sessionStorage = new FakeSessionStorage();

  const context = vm.createContext({
    Headers,
    Response,
    URL,
    console,
    document,
    fetch: async (url, init = {}) => {
      const parsed = new URL(String(url));
      const method = init.method || "GET";
      if (method === "GET" && parsed.pathname.endsWith("/profile")) {
        return jsonApiResponse({ public_id: "demo-store", store_name: "演示店铺", welcome: "欢迎测试" });
      }
      if (method === "GET" && parsed.pathname.endsWith("/products")) {
        return jsonApiResponse([
          {
            id: "signed-product-1",
            source_type: "self",
            name: "测试卡密",
            price: "9.90",
            currency: "USDT",
            delivery_type: "card_pool",
            stock_status: "available",
          },
        ]);
      }
      if (method === "POST" && parsed.pathname.endsWith("/orders")) {
        return jsonApiResponse(pendingOrder());
      }
      if (method === "GET" && parsed.pathname.endsWith("/orders/ORD_PUBLIC_1")) {
        return jsonApiResponse(
          { detail: "too many refreshes token=refresh-secret" },
          { status: 429 },
        );
      }
      return jsonApiResponse({ detail: "not found" }, { status: 404 });
    },
    window: {
      __FAKABOT_STORE__: config,
      Telegram: {
        WebApp: {
          initData: "telegram-init-data-secret",
          initDataUnsafe: { user: { id: 998877 } },
          ready() {},
          expand() {},
          openLink() {},
        },
      },
      sessionStorage,
      open() {
        throw new Error("refresh must not open payment");
      },
      setInterval() {
        throw new Error("manual refresh before payment must not start polling");
      },
      clearInterval() {},
    },
  });

  vm.runInContext(script, context);

  await waitFor(() => document.querySelector("[data-create-order]"));
  await document.querySelector("[data-create-order]").click();
  await waitFor(() => document.querySelector("[data-refresh-order]"));
  await document.querySelector("[data-refresh-order]").click();
  await waitFor(() => document.querySelector("[data-order]").innerHTML.includes("请求过于频繁"));

  assert.doesNotMatch(document.querySelector("[data-order]").innerHTML, /refresh-secret|token/i);
  assert.doesNotMatch(JSON.stringify(sessionStorage.getItem("fakabot:storefront:order:demo-store")), /refresh-secret|token/i);
});

test("storefront browser script handles polling refresh failure with warning and stops polling", async () => {
  const response = await handleRequest(new Request("https://shop.example/demo-store"), {
    DEFAULT_STORE_TITLE: "演示店铺",
  });
  const html = await response.text();
  const config = extractStorefrontConfig(html);
  const script = extractStorefrontRuntimeScript(html);
  const document = new FakeDocument();
  const sessionStorage = new FakeSessionStorage();
  const openedLinks = [];
  const intervals = [];

  const context = vm.createContext({
    Headers,
    Response,
    URL,
    console,
    document,
    fetch: async (url, init = {}) => {
      const parsed = new URL(String(url));
      const method = init.method || "GET";
      if (method === "GET" && parsed.pathname.endsWith("/profile")) {
        return jsonApiResponse({ public_id: "demo-store", store_name: "演示店铺", welcome: "欢迎测试" });
      }
      if (method === "GET" && parsed.pathname.endsWith("/products")) {
        return jsonApiResponse([
          {
            id: "signed-product-1",
            source_type: "self",
            name: "测试卡密",
            price: "9.90",
            currency: "USDT",
            delivery_type: "card_pool",
            stock_status: "available",
          },
        ]);
      }
      if (method === "POST" && parsed.pathname.endsWith("/orders")) {
        return jsonApiResponse(pendingOrder());
      }
      if (method === "POST" && parsed.pathname.endsWith("/orders/ORD_PUBLIC_1/payment")) {
        return jsonApiResponse({ payment_url: "https://pay.example/checkout/ORD_PUBLIC_1?token=provider-secret" });
      }
      if (method === "GET" && parsed.pathname.endsWith("/orders/ORD_PUBLIC_1")) {
        return jsonApiResponse(
          { detail: "raw_response=https://internal-api.example/orders/ORD_PUBLIC_1?token=polling-refresh-secret storage_key=file-secret" },
          { status: 503 },
        );
      }
      return jsonApiResponse({ detail: "not found" }, { status: 404 });
    },
    window: {
      __FAKABOT_STORE__: config,
      Telegram: {
        WebApp: {
          initData: "telegram-init-data-secret",
          initDataUnsafe: { user: { id: 998877 } },
          ready() {},
          expand() {},
          openLink(url) {
            openedLinks.push(url);
          },
        },
      },
      sessionStorage,
      open() {
        throw new Error("polling refresh must not use window.open");
      },
      setInterval(callback, delay) {
        const id = intervals.length + 1;
        intervals.push({ id, callback, delay, active: true });
        return id;
      },
      clearInterval(id) {
        const interval = intervals.find((item) => item.id === id);
        if (interval) interval.active = false;
      },
    },
  });

  vm.runInContext(script, context);

  await waitFor(() => document.querySelector("[data-create-order]"));
  await document.querySelector("[data-create-order]").click();
  await waitFor(() => document.querySelector("[data-create-payment]"));
  const snapshotBeforePolling = sessionStorage.getItem("fakabot:storefront:order:demo-store");
  await document.querySelector("[data-create-payment]").click();
  await waitFor(() => openedLinks.length === 1 && intervals.length === 1);

  assert.equal(intervals[0].active, true);
  assert.equal(intervals[0].delay, 5000);
  await intervals[0].callback();
  await waitFor(() => document.querySelector("[data-order]").innerHTML.includes("订单状态暂时无法刷新"));

  assert.equal(intervals[0].active, false);
  assert.equal(openedLinks.length, 1);
  assert.match(document.querySelector("[data-order]").innerHTML, /message warning/);
  assert.match(document.querySelector("[data-order]").innerHTML, /待支付|订单状态暂时无法刷新/);
  assert.doesNotMatch(document.querySelector("[data-order]").innerHTML, /polling-refresh-secret|storage_key|internal-api\.example|raw_response/i);
  assert.equal(sessionStorage.getItem("fakabot:storefront:order:demo-store"), snapshotBeforePolling);
  assert.doesNotMatch(sessionStorage.getItem("fakabot:storefront:order:demo-store"), /polling-refresh-secret|storage_key|internal-api\.example|raw_response|telegram-init-data-secret/i);
});

test("storefront page does not expose unrelated secret env values", async () => {
  const response = await handleRequest(
    new Request("https://shop.example/demo-store"),
    {
      PUBLIC_STORE_API_BASE_URL: "https://api.example",
      TENANT_ADMIN_API_KEY: "fk_live_should_not_render",
      BOT_TOKEN: "123456:bot-token-secret",
      PAYMENT_SECRET: "payment-secret",
    },
  );
  const html = await response.text();

  assert.doesNotMatch(html, /fk_live_should_not_render/);
  assert.doesNotMatch(html, /123456:bot-token-secret/);
  assert.doesNotMatch(html, /payment-secret/);
});

test("public order polling decision waits for delivery after payment", () => {
  assert.equal(shouldPollPublicOrder({ status: "pending", can_pay: true }), true);
  assert.equal(shouldPollPublicOrder({ status: "pending", can_pay: false }), false);
  assert.equal(
    shouldPollPublicOrder({ status: "paid", paid_at: "2026-06-08T10:00:00Z", delivered_at: null, can_pay: false }),
    true,
  );
  assert.equal(shouldPollPublicOrder({ status: "delivered", delivered_at: "2026-06-08T10:01:00Z" }), false);
  assert.equal(shouldPollPublicOrder({ status: "completed" }), false);
  assert.equal(shouldPollPublicOrder({ status: "expired" }), false);
  assert.equal(shouldPollPublicOrder({ status: "cancelled" }), false);
  assert.equal(shouldPollPublicOrder({ status: "refunded" }), false);
  assert.equal(shouldPollPublicOrder({ status: "pending", can_pay: true }, 60), false);
});

test("tenant id from default env supports root storefront path", () => {
  const config = buildClientConfig(
    new Request("https://shop.example/"),
    {
      DEFAULT_TENANT_PUBLIC_ID: "default-store",
      PUBLIC_STORE_BROWSER_API_BASE_URL: "https://store-api.example",
    },
    "default-store",
  );

  assert.equal(config.tenantPublicId, "default-store");
  assert.equal(config.apiBaseUrl, "https://store-api.example");
});

test("invalid browser api base url falls back to worker origin", () => {
  const config = buildClientConfig(
    new Request("https://shop.example/demo"),
    { PUBLIC_STORE_BROWSER_API_BASE_URL: "file:///tmp/secret" },
    "demo",
  );

  assert.equal(config.apiBaseUrl, "https://shop.example");
});

test("unsafe browser api base url parts fall back to worker origin without rendering secrets", async () => {
  for (const baseUrl of [
    "https://user:secret@store-api.example",
    "https://store-api.example/base?token=secret",
    "https://store-api.example/base#secret",
  ]) {
    const response = await handleRequest(
      new Request("https://shop.example/demo"),
      { PUBLIC_STORE_BROWSER_API_BASE_URL: baseUrl },
    );
    const html = await response.text();
    const config = extractStorefrontConfig(html);

    assert.equal(config.apiBaseUrl, "https://shop.example");
    assert.doesNotMatch(html, /store-api\.example|user:secret|token=secret|#secret/);
  }
});

test("invalid tenant id returns 404", async () => {
  const response = await handleRequest(new Request("https://shop.example/bad%20tenant"));

  assert.equal(response.status, 404);
});

test("non page post returns 405", async () => {
  const response = await handleRequest(new Request("https://shop.example/demo-store", { method: "POST" }));

  assert.equal(response.status, 405);
  assert.equal(response.headers.get("Allow"), "GET, HEAD");
});

test("public store api proxy forwards only public request context", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init, headers: new Headers(init.headers) });
    return new Response(JSON.stringify({ public_id: "demo-store" }), {
      status: 200,
      headers: {
        "Content-Type": "application/json",
        "Set-Cookie": "should-not-forward=true",
      },
    });
  };

  try {
    const response = await handleRequest(
      new Request("https://shop.example/api/v1/store/demo-store/profile?lang=zh", {
        headers: {
          "Authorization": "Bearer admin-secret",
          "X-API-Key": "fk_live_secret",
          "X-Faka-Signature": "tenant-admin-signature",
          "X-Faka-Timestamp": "2026-06-08T00:00:00Z",
          "X-Fakabot-Signature": "signature",
          "Cookie": "session=secret",
          "BOT_TOKEN": "123456:secret",
          "X-Telegram-Init-Data": "telegram-init-data",
          "CF-Connecting-IP": "203.0.113.9",
        },
      }),
      { PUBLIC_STORE_API_BASE_URL: "https://api.example/base/" },
    );

    assert.equal(response.status, 200);
    assert.equal(response.headers.get("Content-Type"), "application/json");
    assert.equal(response.headers.get("Set-Cookie"), null);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "https://api.example/base/api/v1/store/demo-store/profile?lang=zh");
    assert.equal(calls[0].init.method, "GET");
    assert.equal(calls[0].headers.get("Authorization"), null);
    assert.equal(calls[0].headers.get("X-API-Key"), null);
    assert.equal(calls[0].headers.get("X-Faka-Signature"), null);
    assert.equal(calls[0].headers.get("X-Faka-Timestamp"), null);
    assert.equal(calls[0].headers.get("X-Fakabot-Signature"), null);
    assert.equal(calls[0].headers.get("Cookie"), null);
    assert.equal(calls[0].headers.get("BOT_TOKEN"), null);
    assert.equal(calls[0].headers.get("X-Telegram-Init-Data"), "telegram-init-data");
    assert.equal(calls[0].headers.get("X-Forwarded-For"), "203.0.113.9");
    assert.equal(calls[0].headers.get("X-Fakabot-Storefront"), "cloudflare-worker");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("public store api proxy rejects unsupported methods without backend fetch", async () => {
  const originalFetch = globalThis.fetch;
  let called = false;
  globalThis.fetch = async () => {
    called = true;
    return new Response("unexpected");
  };

  try {
    const response = await handleRequest(
      new Request("https://shop.example/api/v1/store/demo-store/profile", { method: "DELETE" }),
      { PUBLIC_STORE_API_BASE_URL: "https://api.example" },
    );

    assert.equal(response.status, 405);
    assert.equal(response.headers.get("Allow"), "GET, HEAD, POST");
    assert.equal(called, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("public store api proxy forwards post body to backend", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({
      url,
      method: init.method,
      contentType: new Headers(init.headers).get("Content-Type"),
      body: await new Response(init.body).text(),
    });
    return new Response(JSON.stringify({ ok: true }), {
      headers: { "Content-Type": "application/json" },
    });
  };

  try {
    const response = await handleRequest(
      new Request("https://shop.example/api/v1/store/demo-store/orders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ product_id: "signed-product-1" }),
      }),
      { PUBLIC_STORE_API_BASE_URL: "https://api.example/base" },
    );

    assert.equal(response.status, 200);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "https://api.example/base/api/v1/store/demo-store/orders");
    assert.equal(calls[0].method, "POST");
    assert.equal(calls[0].contentType, "application/json");
    assert.equal(calls[0].body, "{\"product_id\":\"signed-product-1\"}");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("public store api proxy preserves public response headers and strips cookies", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response("rate limited", {
    status: 429,
    statusText: "Too Many Requests",
    headers: {
      "Content-Type": "text/plain",
      "Cache-Control": "max-age=60",
      "Location": "https://pay.example/checkout/ORD_PUBLIC_1",
      "Set-Cookie": "session=secret",
    },
  });

  try {
    const response = await handleRequest(
      new Request("https://shop.example/api/v1/store/demo-store/orders/ORD_PUBLIC_1/payment", { method: "POST" }),
      { PUBLIC_STORE_API_BASE_URL: "https://api.example" },
    );

    assert.equal(response.status, 429);
    assert.equal(response.statusText, "Too Many Requests");
    assert.equal(response.headers.get("Content-Type"), "text/plain");
    assert.equal(response.headers.get("Cache-Control"), "max-age=60");
    assert.equal(response.headers.get("Location"), "https://pay.example/checkout/ORD_PUBLIC_1");
    assert.equal(response.headers.get("X-Content-Type-Options"), "nosniff");
    assert.equal(response.headers.get("Set-Cookie"), null);
    assert.equal(await response.text(), "rate limited");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("public api proxy headers use an allowlist", () => {
  const headers = publicApiProxyHeaders(
    new Headers({
      "Accept": "application/json",
      "Content-Type": "application/json",
      "X-Telegram-Init-Data": "telegram-init-data",
      "Authorization": "Bearer admin-secret",
      "X-API-Key": "fk_live_secret",
      "X-Faka-Signature": "tenant-admin-signature",
      "Cookie": "session=secret",
      "Payment-Secret": "secret",
      "CF-Connecting-IP": "203.0.113.10",
    }),
  );

  assert.equal(headers.get("Accept"), "application/json");
  assert.equal(headers.get("Content-Type"), "application/json");
  assert.equal(headers.get("X-Telegram-Init-Data"), "telegram-init-data");
  assert.equal(headers.get("X-Forwarded-For"), "203.0.113.10");
  assert.equal(headers.get("X-Fakabot-Storefront"), "cloudflare-worker");
  assert.equal(headers.get("Authorization"), null);
  assert.equal(headers.get("X-API-Key"), null);
  assert.equal(headers.get("X-Faka-Signature"), null);
  assert.equal(headers.get("Cookie"), null);
  assert.equal(headers.get("Payment-Secret"), null);
});

test("public store api proxy requires backend api url", async () => {
  const response = await handleRequest(
    new Request("https://shop.example/api/v1/store/demo-store/profile"),
    { PUBLIC_STORE_API_BASE_URL: "file:///tmp/secret" },
  );

  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), { detail: "Public Store API 未配置" });
});

test("public store api proxy rejects backend api urls with credentials query or fragment", async () => {
  const originalFetch = globalThis.fetch;
  let called = false;
  globalThis.fetch = async () => {
    called = true;
    return new Response("unexpected");
  };

  try {
    for (const baseUrl of [
      "https://user:secret@api.example",
      "https://api.example/base?token=secret",
      "https://api.example/base#secret",
    ]) {
      const response = await handleRequest(
        new Request("https://shop.example/api/v1/store/demo-store/profile"),
        { PUBLIC_STORE_API_BASE_URL: baseUrl },
      );

      assert.equal(response.status, 503);
      assert.deepEqual(await response.json(), { detail: "Public Store API 未配置" });
    }
    assert.equal(called, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

function extractStorefrontConfig(html) {
  const match = html.match(/window\.__FAKABOT_STORE__ = (\{.*?\});<\/script>/s);
  assert.ok(match, "storefront config script must exist");
  return JSON.parse(match[1]);
}

function extractStorefrontRuntimeScript(html) {
  const scripts = Array.from(html.matchAll(/<script nonce="[^"]*">([\s\S]*?)<\/script>/g)).map((match) => match[1]);
  const script = scripts.find((content) => content.includes("const state =") && content.includes("loadStore();"));
  assert.ok(script, "storefront runtime script must exist");
  return script;
}

function publicStoreApiResponse(url, init, nextOrderStatus) {
  const parsed = new URL(url);
  const path = parsed.pathname;
  const method = init.method || "GET";
  if (method === "GET" && path.endsWith("/profile")) {
    return jsonApiResponse({
      public_id: "demo-store",
      store_name: "演示店铺",
      welcome: "欢迎测试",
      support: "客服 @support",
    });
  }
  if (method === "GET" && path.endsWith("/products")) {
    return jsonApiResponse([
      {
        id: "signed-product-1",
        source_type: "self",
        name: "测试卡密",
        description: "离线测试商品",
        price: "9.90",
        currency: "USDT",
        delivery_type: "card_pool",
        stock_status: "available",
      },
    ]);
  }
  if (method === "POST" && path.endsWith("/orders")) {
    return jsonApiResponse(pendingOrder());
  }
  if (method === "POST" && path.endsWith("/orders/ORD_PUBLIC_1/payment")) {
    return jsonApiResponse({
      payment_url: "https://pay.example/checkout/ORD_PUBLIC_1?token=provider-secret",
    });
  }
  if (method === "GET" && path.endsWith("/orders/ORD_PUBLIC_1")) {
    return jsonApiResponse(nextOrderStatus());
  }
  return jsonApiResponse({ detail: "not found" }, { status: 404 });
}

function pendingOrder() {
  return {
    out_trade_no: "ORD_PUBLIC_1",
    amount: "9.90",
    currency: "USDT",
    status: "pending",
    expires_at: "2026-06-08T10:30:00Z",
    paid_at: null,
    delivered_at: null,
    can_pay: true,
  };
}

function pendingPaidOrder() {
  return {
    ...pendingOrder(),
    status: "paid",
    paid_at: "2026-06-08T10:02:00Z",
    can_pay: false,
  };
}

function deliveredOrder() {
  return {
    ...pendingPaidOrder(),
    status: "delivered",
    delivered_at: "2026-06-08T10:03:00Z",
  };
}

function jsonApiResponse(payload, init = {}) {
  return new Response(JSON.stringify(payload), {
    status: init.status || 200,
    headers: { "Content-Type": "application/json" },
  });
}

async function waitFor(predicate, attempts = 20) {
  for (let index = 0; index < attempts; index += 1) {
    if (predicate()) return;
    await Promise.resolve();
  }
  assert.equal(predicate(), true);
}

class FakeSessionStorage {
  constructor() {
    this.items = new Map();
  }

  getItem(key) {
    return this.items.has(key) ? this.items.get(key) : null;
  }

  setItem(key, value) {
    this.items.set(String(key), String(value));
  }

  removeItem(key) {
    this.items.delete(key);
  }
}

class FakeDocument {
  constructor() {
    this.title = "";
    this.elements = new Map();
    this.listeners = new Map();
    this.visibilityState = "visible";
    for (const selector of [
      "[data-store-name]",
      "[data-support]",
      "[data-telegram-state]",
      "[data-welcome]",
      "[data-products]",
      "[data-detail]",
      "[data-order]",
    ]) {
      this.elements.set(selector, new FakeElement(this));
    }
    this.viewButtons = [
      new FakeElement(this, { dataset: { view: "grid" } }),
      new FakeElement(this, { dataset: { view: "compact" } }),
    ];
  }

  querySelector(selector) {
    if (selector === "[data-buyer-id]") {
      return this.elements.get(selector) || null;
    }
    return this.elements.get(selector) || null;
  }

  querySelectorAll(selector) {
    if (selector === "[data-view]") {
      return this.viewButtons;
    }
    if (selector === "[data-product-id]") {
      return Array.from(this.elements.values()).filter((element) => element.dataset.productId);
    }
    return [];
  }

  addEventListener(name, listener) {
    this.listeners.set(name, listener);
  }

  trigger(name) {
    const listener = this.listeners.get(name);
    if (listener) listener();
  }

  register(selector, element) {
    this.elements.set(selector, element);
  }
}

class FakeElement {
  constructor(document, options = {}) {
    this.document = document;
    this.dataset = options.dataset || {};
    this.attributes = new Map();
    this.listeners = new Map();
    this.classes = new Set();
    this.classList = {
      toggle: (name, force) => {
        if (force) {
          this.classes.add(name);
          return true;
        }
        this.classes.delete(name);
        return false;
      },
    };
    this.textContent = "";
    this.value = "";
    this._innerHTML = "";
  }

  get innerHTML() {
    return this._innerHTML;
  }

  set innerHTML(value) {
    this._innerHTML = String(value);
    this.registerKnownChildren(this._innerHTML);
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }

  addEventListener(name, listener) {
    this.listeners.set(name, listener);
  }

  async click() {
    const listener = this.listeners.get("click");
    if (listener) {
      await listener();
    }
  }

  querySelector(selector) {
    return this.document.querySelector(selector);
  }

  querySelectorAll(selector) {
    return this.document.querySelectorAll(selector);
  }

  registerKnownChildren(html) {
    for (const match of html.matchAll(/data-product-id="([^"]+)"/g)) {
      const element = new FakeElement(this.document, { dataset: { productId: unescapeHtml(match[1]) } });
      this.document.register(`[data-product-id="${match[1]}"]`, element);
    }
    if (html.includes("data-create-order")) {
      this.document.register("[data-create-order]", new FakeElement(this.document));
    }
    if (html.includes("data-create-payment")) {
      this.document.register("[data-create-payment]", new FakeElement(this.document));
    }
    if (html.includes("data-refresh-order")) {
      this.document.register("[data-refresh-order]", new FakeElement(this.document));
    }
    if (html.includes("data-buyer-id")) {
      this.document.register("[data-buyer-id]", new FakeElement(this.document));
    }
    const paymentLink = html.match(/data-payment-link href="([^"]+)"/);
    if (paymentLink) {
      const element = new FakeElement(this.document);
      element.setAttribute("href", unescapeHtml(paymentLink[1]));
      this.document.register("[data-payment-link]", element);
    }
  }
}

function unescapeHtml(value) {
  return String(value)
    .replace(/&quot;/g, "\"")
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");
}
