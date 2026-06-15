from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import hmac
import json
import logging
import time
from types import SimpleNamespace
import unittest
import warnings
from urllib.parse import urlencode
from unittest.mock import AsyncMock, patch

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)
logging.getLogger("httpx").setLevel(logging.WARNING)

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.services.risk import OrderCreationRiskBlocked
    from app.services.telegram_webapp import TelegramWebAppUser
    from app.web.public_store import PublicProduct, create_public_store_router, _public_product_id
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过 Public Store 运行时身份测试：{exc.name}") from exc


def _client(settings: Settings) -> TestClient:
    app = FastAPI()
    app.state.redis = None
    app.include_router(create_public_store_router(settings))
    return TestClient(app)


async def _fake_load_tenant(public_id: str) -> tuple[object, dict[str, object]]:
    return (
        SimpleNamespace(
            id=7,
            public_id=public_id,
            store_name="测试店铺",
            self_sale_enabled=True,
            supplier_enabled=False,
            reseller_enabled=True,
        ),
        {},
    )


async def _fake_load_tenant_with_timeout(public_id: str) -> tuple[object, dict[str, object]]:
    return (
        SimpleNamespace(
            id=7,
            public_id=public_id,
            store_name="测试店铺",
            self_sale_enabled=True,
            supplier_enabled=False,
            reseller_enabled=True,
        ),
        {"order_timeout_minutes": {"value": 30}},
    )


class _CommitSession:
    def __init__(self) -> None:
        self.commit_count = 0

    async def __aenter__(self) -> "_CommitSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    async def commit(self) -> None:
        self.commit_count += 1


def _session_factory(session: _CommitSession):
    def factory() -> _CommitSession:
        return session

    return factory


@contextmanager
def _public_get_read_guard():
    with patch(
        "app.web.public_store._hit_public_store_write_rate_limit",
        AsyncMock(side_effect=AssertionError("公开 GET 不应触发写限流")),
    ), patch(
        "app.web.public_store._tenant_bot_token",
        AsyncMock(side_effect=AssertionError("公开 GET 不应校验 Telegram Bot Token")),
    ), patch(
        "app.web.public_store._ensure_buyer_not_banned",
        AsyncMock(side_effect=AssertionError("公开 GET 不应检查买家封禁")),
    ):
        yield


class PublicStoreRuntimeAuthTest(unittest.TestCase):
    def test_store_profile_returns_public_settings_only(self) -> None:
        client = _client(Settings(telegram_webapp_require_init_data=True))
        load_tenant = AsyncMock(
            return_value=(
                SimpleNamespace(id=7, public_id="demo", store_name="测试店铺", encrypted_token="bot-secret"),
                {
                    "welcome": {"text": "欢迎光临"},
                    "support": {"text": "@support"},
                    "private": {"token": "secret-value"},
                },
            )
        )
        read_guard = _public_get_read_guard()

        with read_guard:
            with patch("app.web.public_store._load_tenant", load_tenant):
                response = client.get("/api/v1/store/demo/profile")

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(
            {
                "public_id": "demo",
                "store_name": "测试店铺",
                "welcome": "欢迎光临",
                "support": "@support",
            },
            payload,
        )
        self.assertNotIn("encrypted_token", response.text)
        self.assertNotIn("secret-value", response.text)
        self.assertNotIn("private", response.text)
        load_tenant.assert_awaited_once_with("demo")

    def test_store_profile_returns_404_for_missing_tenant(self) -> None:
        client = _client(Settings(telegram_webapp_require_init_data=True))
        load_tenant = AsyncMock(side_effect=HTTPException(status_code=404, detail="店铺不存在"))
        read_guard = _public_get_read_guard()

        with read_guard:
            with patch("app.web.public_store._load_tenant", load_tenant):
                response = client.get("/api/v1/store/missing/profile")

        self.assertEqual(404, response.status_code)
        self.assertEqual("店铺不存在", response.json()["detail"])
        load_tenant.assert_awaited_once_with("missing")

    def test_store_products_returns_public_product_fields_only(self) -> None:
        settings = Settings(public_base_url="https://store.example", telegram_webapp_require_init_data=True)
        client = _client(settings)
        tenant = SimpleNamespace(id=7, public_id="demo", store_name="测试店铺")
        load_tenant = AsyncMock(return_value=(tenant, {}))
        self_product_id = _public_product_id("self", 3, tenant_id=7, settings=settings)
        reseller_product_id = _public_product_id("reseller", 9, tenant_id=7, settings=settings)
        list_public_products = AsyncMock(
            return_value=[
                PublicProduct(
                    id=self_product_id,
                    source_type="self",
                    name="自营商品",
                    category="自营",
                    description="公开描述",
                    delivery_type="card_pool",
                    price=Decimal("5.00"),
                    currency="USDT",
                    stock_status="available",
                ),
                PublicProduct(
                    id=reseller_product_id,
                    source_type="reseller",
                    name="代理商品",
                    category="会员",
                    delivery_type="card_fixed",
                    price=Decimal("7.00"),
                    currency="USDT",
                    stock_status="available",
                ),
            ]
        )
        read_guard = _public_get_read_guard()

        with read_guard:
            with patch("app.web.public_store._load_tenant", load_tenant):
                with patch("app.web.public_store._list_public_products", list_public_products):
                    response = client.get("/api/v1/store/demo/products")

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(2, len(payload))
        self.assertEqual(self_product_id, payload[0]["id"])
        self.assertEqual("self", payload[0]["source_type"])
        self.assertEqual(reseller_product_id, payload[1]["id"])
        self.assertEqual("reseller", payload[1]["source_type"])
        for product in payload:
            self.assertEqual(
                {
                    "id",
                    "source_type",
                    "name",
                    "category",
                    "delivery_type",
                    "price",
                    "currency",
                    "stock_status",
                    "description",
                },
                set(product),
            )
        self.assertNotIn("external_source", response.text)
        self.assertNotIn("source_key", response.text)
        self.assertNotIn("supplier_tenant_id", response.text)
        self.assertNotIn("locked_inventory_item_id", response.text)
        load_tenant.assert_awaited_once_with("demo")
        list_public_products.assert_awaited_once_with(7, settings=settings, tenant=tenant, tenant_settings={})

    def test_store_product_detail_returns_matching_public_product(self) -> None:
        settings = Settings(public_base_url="https://store.example", telegram_webapp_require_init_data=True)
        client = _client(settings)
        tenant = SimpleNamespace(id=7, public_id="demo", store_name="测试店铺")
        load_tenant = AsyncMock(return_value=(tenant, {}))
        public_product_id = _public_product_id("reseller", 9, tenant_id=7, settings=settings)
        list_public_products = AsyncMock(
            return_value=[
                PublicProduct(
                    id=_public_product_id("self", 3, tenant_id=7, settings=settings),
                    source_type="self",
                    name="自营商品",
                    delivery_type="card_pool",
                    price=Decimal("5.00"),
                    currency="USDT",
                    stock_status="available",
                ),
                PublicProduct(
                    id=public_product_id,
                    source_type="reseller",
                    name="代理商品",
                    category="会员",
                    delivery_type="card_fixed",
                    price=Decimal("7.00"),
                    currency="USDT",
                    stock_status="available",
                ),
            ]
        )
        read_guard = _public_get_read_guard()

        with read_guard:
            with patch("app.web.public_store._load_tenant", load_tenant):
                with patch("app.web.public_store._list_public_products", list_public_products):
                    response = client.get(f"/api/v1/store/demo/products/{public_product_id}")

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(public_product_id, payload["id"])
        self.assertEqual("reseller", payload["source_type"])
        self.assertEqual("代理商品", payload["name"])
        self.assertEqual("会员", payload["category"])
        self.assertNotIn("supplier_offer_id", response.text)
        self.assertNotIn("external_id", response.text)
        list_public_products.assert_awaited_once_with(7, settings=settings, tenant=tenant, tenant_settings={})

    def test_store_product_detail_returns_404_for_missing_product(self) -> None:
        settings = Settings(public_base_url="https://store.example", telegram_webapp_require_init_data=True)
        client = _client(settings)
        tenant = SimpleNamespace(id=7, public_id="demo", store_name="测试店铺")
        load_tenant = AsyncMock(return_value=(tenant, {}))
        list_public_products = AsyncMock(return_value=[])
        read_guard = _public_get_read_guard()

        with read_guard:
            with patch("app.web.public_store._load_tenant", load_tenant):
                with patch("app.web.public_store._list_public_products", list_public_products):
                    response = client.get("/api/v1/store/demo/products/pub.v1.7.s.missing.signature")

        self.assertEqual(404, response.status_code)
        self.assertEqual("商品不存在", response.json()["detail"])
        list_public_products.assert_awaited_once_with(7, settings=settings, tenant=tenant, tenant_settings={})

    def test_create_order_with_signed_self_product_id_calls_self_order_service_and_commits(self) -> None:
        settings = Settings(public_base_url="https://store.example", telegram_webapp_require_init_data=True)
        client = _client(settings)
        session = _CommitSession()
        created_order = _created_order("ORD_SELF")
        product_id = _public_product_id("self", 3, tenant_id=7, settings=settings)
        bot_token = AsyncMock(return_value="123456:secret")
        rate_limit = AsyncMock()

        def validate_init_data(*args: object, **kwargs: object) -> TelegramWebAppUser:
            return TelegramWebAppUser(id=42)

        with patch("app.web.public_store._load_tenant", _fake_load_tenant_with_timeout):
            with patch("app.web.public_store._tenant_bot_token", bot_token):
                with patch("app.web.public_store.validate_telegram_webapp_init_data", validate_init_data):
                    with patch("app.web.public_store._hit_public_store_write_rate_limit", rate_limit):
                        with patch("app.web.public_store._ensure_buyer_not_banned", AsyncMock()):
                            with patch("app.web.public_store.get_session_factory", return_value=_session_factory(session)):
                                with patch("app.web.public_store.OrderService") as order_service:
                                    create_self_order = AsyncMock(return_value=created_order)
                                    create_reseller_order = AsyncMock()
                                    order_service.return_value.create_self_order = create_self_order
                                    order_service.return_value.create_reseller_order = create_reseller_order
                                    response = client.post(
                                        "/api/v1/store/demo/orders",
                                        json={"product_id": product_id},
                                        headers={"X-Telegram-Init-Data": "valid=fake"},
                                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("ORD_SELF", payload["out_trade_no"])
        self.assertEqual("pending", payload["status"])
        self.assertTrue(payload["can_pay"])
        self.assertNotIn("locked_inventory_item_id", payload)
        self.assertNotIn("payment_provider", payload)
        self.assertEqual(1, bot_token.await_count)
        self.assertEqual(2, rate_limit.await_count)
        first_rate_limit_call, second_rate_limit_call = rate_limit.await_args_list
        self.assertIsNone(first_rate_limit_call.args[5])
        self.assertEqual("buyer:42", second_rate_limit_call.args[5])
        self.assertFalse(second_rate_limit_call.kwargs["count_client"])
        create_self_order.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            buyer_telegram_user_id=42,
            product_id=3,
            order_timeout_minutes=30,
        )
        create_reseller_order.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_create_order_with_signed_reseller_product_id_calls_reseller_order_service_and_commits(self) -> None:
        settings = Settings(public_base_url="https://store.example", telegram_webapp_require_init_data=True)
        client = _client(settings)
        session = _CommitSession()
        created_order = _created_order("ORD_RESELLER")
        product_id = _public_product_id("reseller", 9, tenant_id=7, settings=settings)
        bot_token = AsyncMock(return_value="123456:secret")
        rate_limit = AsyncMock()

        def validate_init_data(*args: object, **kwargs: object) -> TelegramWebAppUser:
            return TelegramWebAppUser(id=42)

        with patch("app.web.public_store._load_tenant", _fake_load_tenant_with_timeout):
            with patch("app.web.public_store._tenant_bot_token", bot_token):
                with patch("app.web.public_store.validate_telegram_webapp_init_data", validate_init_data):
                    with patch("app.web.public_store._hit_public_store_write_rate_limit", rate_limit):
                        with patch("app.web.public_store._ensure_buyer_not_banned", AsyncMock()):
                            with patch("app.web.public_store.get_session_factory", return_value=_session_factory(session)):
                                with patch("app.web.public_store.OrderService") as order_service:
                                    create_self_order = AsyncMock()
                                    create_reseller_order = AsyncMock(return_value=created_order)
                                    order_service.return_value.create_self_order = create_self_order
                                    order_service.return_value.create_reseller_order = create_reseller_order
                                    response = client.post(
                                        "/api/v1/store/demo/orders",
                                        json={"product_id": product_id},
                                        headers={"X-Telegram-Init-Data": "valid=fake"},
                                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("ORD_RESELLER", payload["out_trade_no"])
        self.assertNotIn("locked_inventory_item_id", payload)
        self.assertNotIn("payment_provider", payload)
        self.assertEqual(1, bot_token.await_count)
        self.assertEqual(2, rate_limit.await_count)
        first_rate_limit_call, second_rate_limit_call = rate_limit.await_args_list
        self.assertIsNone(first_rate_limit_call.args[5])
        self.assertEqual("buyer:42", second_rate_limit_call.args[5])
        self.assertFalse(second_rate_limit_call.kwargs["count_client"])
        create_self_order.assert_not_called()
        create_reseller_order.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            buyer_telegram_user_id=42,
            reseller_product_id=9,
            order_timeout_minutes=30,
        )
        self.assertEqual(1, session.commit_count)

    def test_create_order_commits_when_order_risk_is_blocked(self) -> None:
        settings = Settings(public_base_url="https://store.example", telegram_webapp_require_init_data=True)
        client = _client(settings)
        session = _CommitSession()
        product_id = _public_product_id("self", 3, tenant_id=7, settings=settings)
        bot_token = AsyncMock(return_value="123456:secret")
        rate_limit = AsyncMock()

        def validate_init_data(*args: object, **kwargs: object) -> TelegramWebAppUser:
            return TelegramWebAppUser(id=42)

        with patch("app.web.public_store._load_tenant", _fake_load_tenant_with_timeout):
            with patch("app.web.public_store._tenant_bot_token", bot_token):
                with patch("app.web.public_store.validate_telegram_webapp_init_data", validate_init_data):
                    with patch("app.web.public_store._hit_public_store_write_rate_limit", rate_limit):
                        with patch("app.web.public_store._ensure_buyer_not_banned", AsyncMock()):
                            with patch("app.web.public_store.get_session_factory", return_value=_session_factory(session)):
                                with patch("app.web.public_store.OrderService") as order_service:
                                    create_self_order = AsyncMock(
                                        side_effect=OrderCreationRiskBlocked("下单过于频繁，请稍后再试")
                                    )
                                    order_service.return_value.create_self_order = create_self_order
                                    response = client.post(
                                        "/api/v1/store/demo/orders",
                                        json={"product_id": product_id},
                                        headers={"X-Telegram-Init-Data": "valid=fake"},
                                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("下单过于频繁，请稍后再试", response.json()["detail"])
        create_self_order.assert_awaited_once()
        self.assertEqual(1, session.commit_count)

    def test_create_order_does_not_commit_when_order_service_rejects_regular_value_error(self) -> None:
        settings = Settings(public_base_url="https://store.example", telegram_webapp_require_init_data=True)
        client = _client(settings)
        session = _CommitSession()
        product_id = _public_product_id("self", 3, tenant_id=7, settings=settings)
        bot_token = AsyncMock(return_value="123456:secret")
        rate_limit = AsyncMock()

        def validate_init_data(*args: object, **kwargs: object) -> TelegramWebAppUser:
            return TelegramWebAppUser(id=42)

        with patch("app.web.public_store._load_tenant", _fake_load_tenant_with_timeout):
            with patch("app.web.public_store._tenant_bot_token", bot_token):
                with patch("app.web.public_store.validate_telegram_webapp_init_data", validate_init_data):
                    with patch("app.web.public_store._hit_public_store_write_rate_limit", rate_limit):
                        with patch("app.web.public_store._ensure_buyer_not_banned", AsyncMock()):
                            with patch("app.web.public_store.get_session_factory", return_value=_session_factory(session)):
                                with patch("app.web.public_store.OrderService") as order_service:
                                    create_self_order = AsyncMock(side_effect=ValueError("库存不足"))
                                    order_service.return_value.create_self_order = create_self_order
                                    response = client.post(
                                        "/api/v1/store/demo/orders",
                                        json={"product_id": product_id},
                                        headers={"X-Telegram-Init-Data": "valid=fake"},
                                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("库存不足", response.json()["detail"])
        create_self_order.assert_awaited_once()
        self.assertEqual(0, session.commit_count)

    def test_create_order_rejects_disabled_self_sale_before_order_service(self) -> None:
        settings = Settings(public_base_url="https://store.example", telegram_webapp_require_init_data=True)
        client = _client(settings)
        session = _CommitSession()
        product_id = _public_product_id("self", 3, tenant_id=7, settings=settings)
        bot_token = AsyncMock(return_value="123456:secret")
        rate_limit = AsyncMock()

        async def load_tenant(public_id: str) -> tuple[object, dict[str, object]]:
            return (
                SimpleNamespace(
                    id=7,
                    public_id=public_id,
                    store_name="测试店铺",
                    self_sale_enabled=False,
                    supplier_enabled=False,
                    reseller_enabled=True,
                ),
                {},
            )

        def validate_init_data(*args: object, **kwargs: object) -> TelegramWebAppUser:
            return TelegramWebAppUser(id=42)

        with patch("app.web.public_store._load_tenant", load_tenant):
            with patch("app.web.public_store._tenant_bot_token", bot_token):
                with patch("app.web.public_store.validate_telegram_webapp_init_data", validate_init_data):
                    with patch("app.web.public_store._hit_public_store_write_rate_limit", rate_limit):
                        with patch("app.web.public_store._ensure_buyer_not_banned", AsyncMock()):
                            with patch("app.web.public_store.get_session_factory", return_value=_session_factory(session)):
                                with patch("app.web.public_store.OrderService") as order_service:
                                    response = client.post(
                                        "/api/v1/store/demo/orders",
                                        json={"product_id": product_id},
                                        headers={"X-Telegram-Init-Data": "valid=fake"},
                                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("自营商品售卖功能已关闭", response.json()["detail"])
        order_service.return_value.create_self_order.assert_not_called()
        self.assertEqual(0, session.commit_count)

    def test_create_order_requires_webapp_init_data_before_order_service(self) -> None:
        client = _client(Settings(telegram_webapp_require_init_data=True))
        rate_limit = AsyncMock()

        with patch("app.web.public_store._load_tenant", _fake_load_tenant):
            with patch("app.web.public_store._hit_public_store_write_rate_limit", rate_limit):
                with patch("app.web.public_store.OrderService") as order_service:
                    response = client.post(
                        "/api/v1/store/demo/orders",
                        json={"product_id": "self:1", "buyer_telegram_user_id": 42},
                    )

        self.assertEqual(401, response.status_code)
        self.assertEqual("缺少 Telegram WebApp initData", response.json()["detail"])
        self.assertEqual(1, rate_limit.await_count)
        self.assertIsNone(rate_limit.await_args.args[5])
        order_service.assert_not_called()

    def test_create_order_rejects_invalid_webapp_init_data_before_order_service(self) -> None:
        client = _client(Settings(telegram_webapp_require_init_data=True))
        bot_token = AsyncMock(return_value="123456:secret")
        rate_limit = AsyncMock()

        with patch("app.web.public_store._load_tenant", _fake_load_tenant):
            with patch("app.web.public_store._hit_public_store_write_rate_limit", rate_limit):
                with patch("app.web.public_store._tenant_bot_token", bot_token):
                    with patch("app.web.public_store.OrderService") as order_service:
                        response = client.post(
                            "/api/v1/store/demo/orders",
                            json={
                                "product_id": "self:1",
                                "buyer_telegram_user_id": 42,
                                "telegram_init_data": "query_id=bad&auth_date=1770000000",
                            },
                        )

        self.assertEqual(401, response.status_code)
        self.assertEqual("initData 缺少 hash", response.json()["detail"])
        self.assertEqual(1, rate_limit.await_count)
        self.assertIsNone(rate_limit.await_args.args[5])
        self.assertEqual(1, bot_token.await_count)
        self.assertEqual(7, bot_token.await_args.args[1])
        order_service.assert_not_called()

    def test_create_order_rejects_future_webapp_auth_date_before_order_service(self) -> None:
        client = _client(Settings(telegram_webapp_require_init_data=True))
        bot_token = AsyncMock(return_value="123456:secret")
        rate_limit = AsyncMock()
        init_data = _signed_init_data(
            "123456:secret",
            {
                "auth_date": str(int(time.time()) + 120),
                "user": json.dumps({"id": 42}, separators=(",", ":")),
            },
        )

        with patch("app.web.public_store._load_tenant", _fake_load_tenant):
            with patch("app.web.public_store._hit_public_store_write_rate_limit", rate_limit):
                with patch("app.web.public_store._tenant_bot_token", bot_token):
                    with patch("app.web.public_store.OrderService") as order_service:
                        response = client.post(
                            "/api/v1/store/demo/orders",
                            json={
                                "product_id": "self:1",
                                "buyer_telegram_user_id": 42,
                                "telegram_init_data": init_data,
                            },
                        )

        self.assertEqual(401, response.status_code)
        self.assertEqual("initData auth_date 来自未来", response.json()["detail"])
        self.assertEqual(1, rate_limit.await_count)
        self.assertIsNone(rate_limit.await_args.args[5])
        self.assertEqual(1, bot_token.await_count)
        self.assertEqual(7, bot_token.await_args.args[1])
        order_service.assert_not_called()

    def test_create_order_rejects_buyer_mismatch_after_verified_init_data(self) -> None:
        client = _client(Settings(telegram_webapp_require_init_data=True))
        bot_token = AsyncMock(return_value="123456:secret")
        rate_limit = AsyncMock()

        def validate_init_data(*args: object, **kwargs: object) -> TelegramWebAppUser:
            return TelegramWebAppUser(id=42)

        with patch("app.web.public_store._load_tenant", _fake_load_tenant):
            with patch("app.web.public_store._hit_public_store_write_rate_limit", rate_limit):
                with patch("app.web.public_store._tenant_bot_token", bot_token):
                    with patch("app.web.public_store.validate_telegram_webapp_init_data", validate_init_data):
                        with patch("app.web.public_store.OrderService") as order_service:
                            response = client.post(
                                "/api/v1/store/demo/orders",
                                json={
                                    "product_id": "self:1",
                                    "buyer_telegram_user_id": 7,
                                    "telegram_init_data": "valid=fake",
                                },
                            )

        self.assertEqual(401, response.status_code)
        self.assertEqual("买家身份与 Telegram WebApp initData 不一致", response.json()["detail"])
        self.assertEqual(1, rate_limit.await_count)
        self.assertIsNone(rate_limit.await_args.args[5])
        self.assertEqual(1, bot_token.await_count)
        self.assertEqual(7, bot_token.await_args.args[1])
        order_service.assert_not_called()

    def test_create_order_rejects_banned_buyer_after_identity_and_buyer_rate_limit(self) -> None:
        client = _client(Settings(telegram_webapp_require_init_data=True))
        bot_token = AsyncMock(return_value="123456:secret")
        rate_limit = AsyncMock()
        ban_check = AsyncMock(side_effect=HTTPException(status_code=403, detail="买家账号已被平台限制"))

        def validate_init_data(*args: object, **kwargs: object) -> TelegramWebAppUser:
            return TelegramWebAppUser(id=42)

        with patch("app.web.public_store._load_tenant", _fake_load_tenant):
            with patch("app.web.public_store._hit_public_store_write_rate_limit", rate_limit):
                with patch("app.web.public_store._tenant_bot_token", bot_token):
                    with patch("app.web.public_store.validate_telegram_webapp_init_data", validate_init_data):
                        with patch("app.web.public_store._ensure_buyer_not_banned", ban_check):
                            with patch("app.web.public_store.OrderService") as order_service:
                                response = client.post(
                                    "/api/v1/store/demo/orders",
                                    json={"product_id": "self:1", "telegram_init_data": "valid=fake"},
                                )

        self.assertEqual(403, response.status_code)
        self.assertEqual("买家账号已被平台限制", response.json()["detail"])
        self.assertEqual(2, rate_limit.await_count)
        self.assertEqual("buyer:42", rate_limit.await_args_list[1].args[5])
        ban_check.assert_awaited_once_with(42)
        order_service.assert_not_called()

    def test_order_detail_requires_webapp_init_data_before_order_lookup(self) -> None:
        client = _client(Settings(telegram_webapp_require_init_data=True))
        order_lookup = AsyncMock(side_effect=AssertionError("不应查询订单"))

        with patch("app.web.public_store._load_tenant", _fake_load_tenant):
            with patch("app.web.public_store._get_tenant_order", order_lookup):
                response = client.get("/api/v1/store/demo/orders/ORD123")

        self.assertEqual(401, response.status_code)
        self.assertEqual("缺少 Telegram WebApp initData", response.json()["detail"])
        order_lookup.assert_not_called()

    def test_order_detail_rejects_cross_buyer_after_verified_init_data(self) -> None:
        client = _client(Settings(telegram_webapp_require_init_data=True))
        bot_token = AsyncMock(return_value="123456:secret")
        order_lookup = AsyncMock(return_value=SimpleNamespace(buyer_telegram_user_id=7))

        def validate_init_data(*args: object, **kwargs: object) -> TelegramWebAppUser:
            return TelegramWebAppUser(id=42)

        with patch("app.web.public_store._load_tenant", _fake_load_tenant):
            with patch("app.web.public_store._tenant_bot_token", bot_token):
                with patch("app.web.public_store.validate_telegram_webapp_init_data", validate_init_data):
                    with patch("app.web.public_store._get_tenant_order", order_lookup):
                        response = client.get(
                            "/api/v1/store/demo/orders/ORD123",
                            headers={"X-Telegram-Init-Data": "valid=fake"},
                        )

        self.assertEqual(404, response.status_code)
        self.assertEqual("订单不存在", response.json()["detail"])
        self.assertEqual(1, bot_token.await_count)
        self.assertEqual(1, order_lookup.await_count)

    def test_order_detail_rejects_banned_owner_after_order_owner_check(self) -> None:
        client = _client(Settings(telegram_webapp_require_init_data=True))
        bot_token = AsyncMock(return_value="123456:secret")
        order_lookup = AsyncMock(return_value=_pending_order(order_id=55, buyer_telegram_user_id=42))
        ban_check = AsyncMock(side_effect=HTTPException(status_code=403, detail="买家账号已被平台限制"))

        def validate_init_data(*args: object, **kwargs: object) -> TelegramWebAppUser:
            return TelegramWebAppUser(id=42)

        with patch("app.web.public_store._load_tenant", _fake_load_tenant):
            with patch("app.web.public_store._tenant_bot_token", bot_token):
                with patch("app.web.public_store.validate_telegram_webapp_init_data", validate_init_data):
                    with patch("app.web.public_store._get_tenant_order", order_lookup):
                        with patch("app.web.public_store._ensure_buyer_not_banned", ban_check):
                            response = client.get(
                                "/api/v1/store/demo/orders/ORD123",
                                headers={"X-Telegram-Init-Data": "valid=fake"},
                            )

        self.assertEqual(403, response.status_code)
        self.assertEqual("买家账号已被平台限制", response.json()["detail"])
        self.assertEqual(1, order_lookup.await_count)
        ban_check.assert_awaited_once_with(42)

    def test_create_payment_requires_webapp_init_data_before_payment_flow(self) -> None:
        client = _client(Settings(telegram_webapp_require_init_data=True))
        order_lookup = AsyncMock(side_effect=AssertionError("不应查询订单"))
        rate_limit = AsyncMock()

        with patch("app.web.public_store._load_tenant", _fake_load_tenant):
            with patch("app.web.public_store._get_tenant_order", order_lookup):
                with patch("app.web.public_store._hit_public_store_write_rate_limit", rate_limit):
                    response = client.post("/api/v1/store/demo/orders/ORD123/payment")

        self.assertEqual(401, response.status_code)
        self.assertEqual("缺少 Telegram WebApp initData", response.json()["detail"])
        self.assertEqual(1, rate_limit.await_count)
        self.assertIsNone(rate_limit.await_args.args[5])
        order_lookup.assert_not_called()

    def test_create_payment_rejects_invalid_webapp_init_data_after_client_rate_limit(self) -> None:
        client = _client(Settings(telegram_webapp_require_init_data=True))
        bot_token = AsyncMock(return_value="123456:secret")
        order_lookup = AsyncMock(side_effect=AssertionError("不应查询订单"))
        rate_limit = AsyncMock()

        with patch("app.web.public_store._load_tenant", _fake_load_tenant):
            with patch("app.web.public_store._hit_public_store_write_rate_limit", rate_limit):
                with patch("app.web.public_store._tenant_bot_token", bot_token):
                    with patch("app.web.public_store._get_tenant_order", order_lookup):
                        response = client.post(
                            "/api/v1/store/demo/orders/ORD123/payment",
                            headers={"X-Telegram-Init-Data": "query_id=bad&auth_date=1770000000"},
                        )

        self.assertEqual(401, response.status_code)
        self.assertEqual("initData 缺少 hash", response.json()["detail"])
        self.assertEqual(1, rate_limit.await_count)
        self.assertIsNone(rate_limit.await_args.args[5])
        self.assertEqual(1, bot_token.await_count)
        order_lookup.assert_not_called()

    def test_public_store_write_pre_auth_rate_limit_short_circuits_validation(self) -> None:
        client = _client(Settings(telegram_webapp_require_init_data=True))
        rate_limit = AsyncMock(side_effect=HTTPException(status_code=429, detail="请求过于频繁，请稍后再试"))
        bot_token = AsyncMock(side_effect=AssertionError("不应校验 Bot Token"))
        load_tenant = AsyncMock(side_effect=AssertionError("不应查询店铺"))

        with patch("app.web.public_store._load_tenant", load_tenant):
            with patch("app.web.public_store._hit_public_store_write_rate_limit", rate_limit):
                with patch("app.web.public_store._tenant_bot_token", bot_token):
                    response = client.post(
                        "/api/v1/store/demo/orders",
                        json={"product_id": "self:1", "telegram_init_data": "valid=fake"},
                    )

        self.assertEqual(429, response.status_code)
        self.assertEqual("请求过于频繁，请稍后再试", response.json()["detail"])
        self.assertEqual(1, rate_limit.await_count)
        self.assertIsNone(rate_limit.await_args.args[5])
        load_tenant.assert_not_called()
        bot_token.assert_not_called()

    def test_public_store_payment_pre_auth_rate_limit_short_circuits_tenant_lookup(self) -> None:
        client = _client(Settings(telegram_webapp_require_init_data=True))
        rate_limit = AsyncMock(side_effect=HTTPException(status_code=429, detail="请求过于频繁，请稍后再试"))
        load_tenant = AsyncMock(side_effect=AssertionError("不应查询店铺"))
        order_lookup = AsyncMock(side_effect=AssertionError("不应查询订单"))

        with patch("app.web.public_store._load_tenant", load_tenant):
            with patch("app.web.public_store._hit_public_store_write_rate_limit", rate_limit):
                with patch("app.web.public_store._get_tenant_order", order_lookup):
                    response = client.post(
                        "/api/v1/store/missing/orders/ORD123/payment",
                        headers={"X-Telegram-Init-Data": "valid=fake"},
                    )

        self.assertEqual(429, response.status_code)
        self.assertEqual("请求过于频繁，请稍后再试", response.json()["detail"])
        self.assertEqual(1, rate_limit.await_count)
        self.assertIsNone(rate_limit.await_args.args[5])
        load_tenant.assert_not_called()
        order_lookup.assert_not_called()

    def test_public_store_write_still_returns_not_found_when_rate_limit_allows_tenant_lookup(self) -> None:
        client = _client(Settings(telegram_webapp_require_init_data=True))
        rate_limit = AsyncMock()
        load_tenant = AsyncMock(side_effect=HTTPException(status_code=404, detail="店铺不存在"))

        with patch("app.web.public_store._load_tenant", load_tenant):
            with patch("app.web.public_store._hit_public_store_write_rate_limit", rate_limit):
                response = client.post(
                    "/api/v1/store/missing/orders",
                    json={"product_id": "self:1", "telegram_init_data": "valid=fake"},
                )

        self.assertEqual(404, response.status_code)
        self.assertEqual("店铺不存在", response.json()["detail"])
        self.assertEqual(1, rate_limit.await_count)
        self.assertIsNone(rate_limit.await_args.args[5])
        self.assertEqual(1, load_tenant.await_count)

    def test_create_payment_rejects_cross_buyer_before_payment_service(self) -> None:
        client = _client(Settings(telegram_webapp_require_init_data=True))
        bot_token = AsyncMock(return_value="123456:secret")
        order_lookup = AsyncMock(return_value=SimpleNamespace(buyer_telegram_user_id=7))
        rate_limit = AsyncMock()

        def validate_init_data(*args: object, **kwargs: object) -> TelegramWebAppUser:
            return TelegramWebAppUser(id=42)

        with patch("app.web.public_store._load_tenant", _fake_load_tenant):
            with patch("app.web.public_store._tenant_bot_token", bot_token):
                with patch("app.web.public_store.validate_telegram_webapp_init_data", validate_init_data):
                    with patch("app.web.public_store._hit_public_store_write_rate_limit", rate_limit):
                        with patch("app.web.public_store._get_tenant_order", order_lookup):
                            with patch("app.web.public_store.PaymentService") as payment_service:
                                response = client.post(
                                    "/api/v1/store/demo/orders/ORD123/payment",
                                    headers={"X-Telegram-Init-Data": "valid=fake"},
                                )

        self.assertEqual(404, response.status_code)
        self.assertEqual("订单不存在", response.json()["detail"])
        self.assertEqual(1, bot_token.await_count)
        self.assertEqual(1, rate_limit.await_count)
        self.assertIsNone(rate_limit.await_args.args[5])
        self.assertEqual(1, order_lookup.await_count)
        payment_service.assert_not_called()

    def test_create_payment_rejects_banned_owner_before_order_subject_rate_limit(self) -> None:
        client = _client(Settings(telegram_webapp_require_init_data=True))
        bot_token = AsyncMock(return_value="123456:secret")
        order_lookup = AsyncMock(return_value=_pending_order(order_id=55, buyer_telegram_user_id=42))
        rate_limit = AsyncMock()
        ban_check = AsyncMock(side_effect=HTTPException(status_code=403, detail="买家账号已被平台限制"))

        def validate_init_data(*args: object, **kwargs: object) -> TelegramWebAppUser:
            return TelegramWebAppUser(id=42)

        with patch("app.web.public_store._load_tenant", _fake_load_tenant):
            with patch("app.web.public_store._tenant_bot_token", bot_token):
                with patch("app.web.public_store.validate_telegram_webapp_init_data", validate_init_data):
                    with patch("app.web.public_store._hit_public_store_write_rate_limit", rate_limit):
                        with patch("app.web.public_store._get_tenant_order", order_lookup):
                            with patch("app.web.public_store._ensure_buyer_not_banned", ban_check):
                                with patch("app.web.public_store.PaymentService") as payment_service:
                                    response = client.post(
                                        "/api/v1/store/demo/orders/ORD123/payment",
                                        headers={"X-Telegram-Init-Data": "valid=fake"},
                                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("买家账号已被平台限制", response.json()["detail"])
        self.assertEqual(1, rate_limit.await_count)
        self.assertIsNone(rate_limit.await_args.args[5])
        self.assertEqual(1, order_lookup.await_count)
        ban_check.assert_awaited_once_with(42)
        payment_service.assert_not_called()

    def test_create_payment_for_verified_owner_pending_order_commits_and_returns_safe_payload(self) -> None:
        settings = Settings(public_base_url="https://store.example", telegram_webapp_require_init_data=True)
        client = _client(settings)
        session = _CommitSession()
        bot_token = AsyncMock(return_value="123456:secret")
        rate_limit = AsyncMock()
        order = _pending_order(order_id=55, buyer_telegram_user_id=42)
        order_lookup = AsyncMock(return_value=order)
        payment = SimpleNamespace(
            provider="epusdt_gmpay",
            payment_url="https://pay.example/checkout/ORD123",
            out_trade_no="ORD123",
            amount=Decimal("10.00"),
            currency="USDT",
            provider_trade_no="UPSTREAM-1",
            idempotency_key="epusdt_gmpay:ORD123",
            raw_request_hash="private-request-hash",
            notify_url="https://store.example/payments/callback/epusdt_gmpay",
            api_key="secret-api-key",
            secret="secret-value",
            payment_provider_config_id=9,
            encrypted_config="encrypted-secret-config",
        )

        def validate_init_data(*args: object, **kwargs: object) -> TelegramWebAppUser:
            return TelegramWebAppUser(id=42)

        with patch("app.web.public_store._load_tenant", _fake_load_tenant):
            with patch("app.web.public_store._tenant_bot_token", bot_token):
                with patch("app.web.public_store.validate_telegram_webapp_init_data", validate_init_data):
                    with patch("app.web.public_store._hit_public_store_write_rate_limit", rate_limit):
                        with patch("app.web.public_store._get_tenant_order", order_lookup):
                            with patch("app.web.public_store._ensure_buyer_not_banned", AsyncMock()):
                                with patch("app.web.public_store.get_session_factory", return_value=_session_factory(session)):
                                    with patch("app.web.public_store.PaymentService") as payment_service:
                                        create_payment_for_order = AsyncMock(return_value=payment)
                                        payment_service.return_value.create_payment_for_order = create_payment_for_order
                                        response = client.post(
                                            "/api/v1/store/demo/orders/ORD123/payment",
                                            headers={"X-Telegram-Init-Data": "valid=fake"},
                                        )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(
            {"provider", "payment_url", "out_trade_no", "amount", "currency"},
            set(payload.keys()),
        )
        self.assertEqual("epusdt_gmpay", payload["provider"])
        self.assertEqual("https://pay.example/checkout/ORD123", payload["payment_url"])
        self.assertEqual("ORD123", payload["out_trade_no"])
        self.assertNotIn("provider_trade_no", payload)
        self.assertNotIn("idempotency_key", payload)
        self.assertNotIn("raw_request_hash", payload)
        self.assertNotIn("notify_url", payload)
        self.assertNotIn("api_key", payload)
        self.assertNotIn("secret", payload)
        self.assertNotIn("payment_provider_config_id", payload)
        self.assertNotIn("encrypted_config", payload)
        self.assertEqual(1, bot_token.await_count)
        self.assertEqual(2, rate_limit.await_count)
        first_rate_limit_call, second_rate_limit_call = rate_limit.await_args_list
        self.assertIsNone(first_rate_limit_call.args[5])
        self.assertEqual("order:ORD123", second_rate_limit_call.args[5])
        self.assertFalse(second_rate_limit_call.kwargs["count_client"])
        self.assertEqual(1, order_lookup.await_count)
        self.assertEqual("pending", order.status)
        self.assertGreater(order.expires_at, datetime.now(timezone.utc))
        payment_service.assert_called_once_with(settings)
        create_payment_for_order.assert_awaited_once_with(session, 55)
        self.assertEqual(1, session.commit_count)

    def test_create_payment_does_not_commit_when_payment_service_rejects_expired_order(self) -> None:
        settings = Settings(public_base_url="https://store.example", telegram_webapp_require_init_data=True)
        client = _client(settings)
        session = _CommitSession()
        bot_token = AsyncMock(return_value="123456:secret")
        rate_limit = AsyncMock()
        order = SimpleNamespace(
            id=56,
            buyer_telegram_user_id=42,
            status="pending",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        order_lookup = AsyncMock(return_value=order)

        def validate_init_data(*args: object, **kwargs: object) -> TelegramWebAppUser:
            return TelegramWebAppUser(id=42)

        with patch("app.web.public_store._load_tenant", _fake_load_tenant):
            with patch("app.web.public_store._tenant_bot_token", bot_token):
                with patch("app.web.public_store.validate_telegram_webapp_init_data", validate_init_data):
                    with patch("app.web.public_store._hit_public_store_write_rate_limit", rate_limit):
                        with patch("app.web.public_store._get_tenant_order", order_lookup):
                            with patch("app.web.public_store._ensure_buyer_not_banned", AsyncMock()):
                                with patch("app.web.public_store.get_session_factory", return_value=_session_factory(session)):
                                    with patch("app.web.public_store.PaymentService") as payment_service:
                                        create_payment_for_order = AsyncMock(side_effect=ValueError("订单已过期，不能发起支付"))
                                        payment_service.return_value.create_payment_for_order = create_payment_for_order
                                        response = client.post(
                                            "/api/v1/store/demo/orders/ORD123/payment",
                                            headers={"X-Telegram-Init-Data": "valid=fake"},
                                        )

        self.assertEqual(400, response.status_code)
        self.assertEqual("订单已过期，不能发起支付", response.json()["detail"])
        self.assertEqual(2, rate_limit.await_count)
        first_rate_limit_call, second_rate_limit_call = rate_limit.await_args_list
        self.assertIsNone(first_rate_limit_call.args[5])
        self.assertEqual("order:ORD123", second_rate_limit_call.args[5])
        self.assertFalse(second_rate_limit_call.kwargs["count_client"])
        create_payment_for_order.assert_awaited_once_with(session, 56)
        self.assertEqual(0, session.commit_count)


def _created_order(out_trade_no: str) -> SimpleNamespace:
    return SimpleNamespace(
        out_trade_no=out_trade_no,
        amount=Decimal("10.00"),
        currency="USDT",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        locked_inventory_item_id=123,
    )


def _pending_order(order_id: int, buyer_telegram_user_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=order_id,
        buyer_telegram_user_id=buyer_telegram_user_id,
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )


def _signed_init_data(bot_token: str, data: dict[str, str]) -> str:
    data_check_string = "\n".join(f"{key}={data[key]}" for key in sorted(data))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({**data, "hash": signature})


if __name__ == "__main__":
    unittest.main()
