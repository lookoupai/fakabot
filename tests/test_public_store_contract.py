from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

try:
    from fastapi import HTTPException

    from app.config import Settings
    from app.services.api_security import FixedWindowRateLimiter, RedisFixedWindowRateLimiter
    from app.services.telegram_webapp import TelegramWebAppUser
    from app.web.public_store import (
        CreatePublicOrderRequest,
        _buyer_telegram_user_id,
        _decode_public_product_id,
        _ensure_buyer_not_banned,
        _ensure_verified_order_owner,
        _hit_public_store_write_rate_limit,
        _list_public_products,
        _order_response,
        _order_timeout_minutes,
        _parse_public_product_id,
        _public_product_id,
        _public_store_rate_limit_key,
        _public_store_subject_rate_limit_key,
        _resolve_public_product_id,
    )
    from unittest.mock import patch
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过公开店铺 API 契约测试：{exc.name}") from exc


class _FakeSession:
    def __init__(self, scalar_value: object = None) -> None:
        self.scalar_value = scalar_value
        self.execute_count = 0

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    async def execute(self, query: object) -> object:
        self.execute_count += 1
        return _ScalarResult(self.scalar_value)


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value


def _fake_session_factory(scalar_value: object = None):
    session = _FakeSession(scalar_value)

    def factory() -> _FakeSession:
        return session

    return factory


class PublicStoreContractTest(unittest.TestCase):
    def test_parse_public_product_id_supports_explicit_prefix(self) -> None:
        self.assertEqual(("self", 12), _parse_public_product_id("self:12", None))
        self.assertEqual(("reseller", 7), _parse_public_product_id("reseller:7", None))

    def test_public_product_id_is_signed_and_resolves_to_local_identity(self) -> None:
        settings = Settings(public_base_url="https://store.example")

        public_id = _public_product_id("self", 12, tenant_id=7, settings=settings)

        self.assertTrue(public_id.startswith("pub.v1.7.s."))
        self.assertNotEqual("self:12", public_id)
        self.assertEqual(("self", 12), _resolve_public_product_id(public_id, None, tenant_id=7, settings=settings))

    def test_public_product_id_rejects_tamper_and_cross_tenant_use(self) -> None:
        settings = Settings(public_base_url="https://store.example")
        public_id = _public_product_id("reseller", 9, tenant_id=7, settings=settings)
        tampered = f"{public_id[:-1]}{'a' if public_id[-1] != 'a' else 'b'}"

        with self.assertRaises(HTTPException) as tampered_context:
            _decode_public_product_id(tampered, tenant_id=7, settings=settings)
        with self.assertRaises(HTTPException) as tenant_context:
            _decode_public_product_id(public_id, tenant_id=8, settings=settings)

        self.assertEqual(400, tampered_context.exception.status_code)
        self.assertEqual(404, tenant_context.exception.status_code)

    def test_order_timeout_minutes_is_clamped(self) -> None:
        self.assertEqual(15, _order_timeout_minutes({}))
        self.assertEqual(1, _order_timeout_minutes({"order_timeout_minutes": {"value": 0}}))
        self.assertEqual(1440, _order_timeout_minutes({"order_timeout_minutes": {"value": 9999}}))

    def test_order_response_exposes_safe_payment_state_only(self) -> None:
        order = SimpleNamespace(
            out_trade_no="ORD123",
            amount=Decimal("10"),
            currency="USDT",
            status="pending",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            paid_at=None,
            delivered_at=None,
            payment_provider="epusdt_gmpay",
            locked_inventory_item_id=123,
        )

        response = _order_response(order)
        payload = response.model_dump()

        self.assertTrue(payload["can_pay"])
        self.assertNotIn("payment_provider", payload)
        self.assertNotIn("locked_inventory_item_id", payload)

    def test_order_response_marks_expired_pending_order_as_not_payable(self) -> None:
        order = SimpleNamespace(
            out_trade_no="ORD123",
            amount=Decimal("10"),
            currency="USDT",
            status="pending",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            paid_at=None,
            delivered_at=None,
        )

        self.assertFalse(_order_response(order).can_pay)

    def test_public_store_rate_limit_key_uses_client_host(self) -> None:
        key = _public_store_rate_limit_key(" demo-store ", "create_order", "client", "203.0.113.10")

        self.assertEqual("public-store:demo-store:create_order:client:203.0.113.10", key)

    def test_public_store_subject_rate_limit_key_is_tenant_scoped(self) -> None:
        key = _public_store_subject_rate_limit_key(" demo-store ", "create_payment", " order:ORD123 ")

        self.assertEqual("public-store:demo-store:create_payment:order:ORD123", key)

    def test_public_store_write_rate_limit_returns_429(self) -> None:
        request = _request("203.0.113.10")
        redis_limiter = RedisFixedWindowRateLimiter(limit=1)
        local_limiter = FixedWindowRateLimiter(limit=1)

        asyncio.run(
            _hit_public_store_write_rate_limit(
                redis_limiter,
                local_limiter,
                request,
                "demo-store",
                "create_order",
                "buyer:42",
                set(),
                set(),
            )
        )
        with self.assertRaises(HTTPException) as context:
            asyncio.run(
                _hit_public_store_write_rate_limit(
                    redis_limiter,
                    local_limiter,
                    request,
                    "demo-store",
                    "create_order",
                    "buyer:42",
                    set(),
                    set(),
                )
            )

        self.assertEqual(429, context.exception.status_code)

    def test_public_store_write_rate_limit_is_tenant_scoped(self) -> None:
        request = _request("203.0.113.10")
        redis_limiter = RedisFixedWindowRateLimiter(limit=1)
        local_limiter = FixedWindowRateLimiter(limit=1)

        asyncio.run(
            _hit_public_store_write_rate_limit(
                redis_limiter,
                local_limiter,
                request,
                "store-a",
                "create_order",
                "buyer:42",
                set(),
                set(),
            )
        )
        asyncio.run(
            _hit_public_store_write_rate_limit(
                redis_limiter,
                local_limiter,
                request,
                "store-b",
                "create_order",
                "buyer:42",
                set(),
                set(),
            )
        )

    def test_public_store_write_rate_limit_subject_applies_across_clients(self) -> None:
        first_request = _request("203.0.113.10")
        second_request = _request("203.0.113.11")
        redis_limiter = RedisFixedWindowRateLimiter(limit=1)
        local_limiter = FixedWindowRateLimiter(limit=1)

        asyncio.run(
            _hit_public_store_write_rate_limit(
                redis_limiter,
                local_limiter,
                first_request,
                "demo-store",
                "create_payment",
                "order:ORD123",
                set(),
                set(),
            )
        )
        with self.assertRaises(HTTPException) as context:
            asyncio.run(
                _hit_public_store_write_rate_limit(
                    redis_limiter,
                    local_limiter,
                    second_request,
                    "demo-store",
                    "create_payment",
                    "order:ORD123",
                    set(),
                    set(),
                )
            )

        self.assertEqual(429, context.exception.status_code)

    def test_public_store_write_rate_limit_keeps_different_buyers_separate(self) -> None:
        request = _request("203.0.113.10")
        redis_limiter = RedisFixedWindowRateLimiter(limit=2)
        local_limiter = FixedWindowRateLimiter(limit=2)

        asyncio.run(
            _hit_public_store_write_rate_limit(
                redis_limiter,
                local_limiter,
                request,
                "demo-store",
                "create_order",
                "buyer:42",
                set(),
                set(),
            )
        )
        asyncio.run(
            _hit_public_store_write_rate_limit(
                redis_limiter,
                local_limiter,
                request,
                "demo-store",
                "create_order",
                "buyer:43",
                set(),
                set(),
            )
        )

        self.assertIn("public-store:demo-store:create_order:buyer:42", local_limiter._counters)
        self.assertIn("public-store:demo-store:create_order:buyer:43", local_limiter._counters)

    def test_public_store_write_rate_limit_keeps_different_orders_separate(self) -> None:
        request = _request("203.0.113.10")
        redis_limiter = RedisFixedWindowRateLimiter(limit=2)
        local_limiter = FixedWindowRateLimiter(limit=2)

        asyncio.run(
            _hit_public_store_write_rate_limit(
                redis_limiter,
                local_limiter,
                request,
                "demo-store",
                "create_payment",
                "order:ORD-A",
                set(),
                set(),
            )
        )
        asyncio.run(
            _hit_public_store_write_rate_limit(
                redis_limiter,
                local_limiter,
                request,
                "demo-store",
                "create_payment",
                "order:ORD-B",
                set(),
                set(),
            )
        )

        self.assertIn("public-store:demo-store:create_payment:order:ORD-A", local_limiter._counters)
        self.assertIn("public-store:demo-store:create_payment:order:ORD-B", local_limiter._counters)

    def test_public_store_write_rate_limit_keeps_different_actions_separate(self) -> None:
        request = _request("203.0.113.10")
        redis_limiter = RedisFixedWindowRateLimiter(limit=1)
        local_limiter = FixedWindowRateLimiter(limit=1)

        asyncio.run(
            _hit_public_store_write_rate_limit(
                redis_limiter,
                local_limiter,
                request,
                "demo-store",
                "create_order",
                "buyer:42",
                set(),
                set(),
            )
        )
        asyncio.run(
            _hit_public_store_write_rate_limit(
                redis_limiter,
                local_limiter,
                request,
                "demo-store",
                "create_payment",
                "order:ORD123",
                set(),
                set(),
            )
        )

    def test_public_store_write_rate_limit_can_count_subject_without_recounting_client(self) -> None:
        request = _request("203.0.113.10")
        redis_limiter = RedisFixedWindowRateLimiter(limit=1)
        local_limiter = FixedWindowRateLimiter(limit=1)

        asyncio.run(
            _hit_public_store_write_rate_limit(
                redis_limiter,
                local_limiter,
                request,
                "demo-store",
                "create_payment",
                None,
                set(),
                set(),
            )
        )
        asyncio.run(
            _hit_public_store_write_rate_limit(
                redis_limiter,
                local_limiter,
                request,
                "demo-store",
                "create_payment",
                "order:ORD123",
                set(),
                set(),
                count_client=False,
            )
        )

        self.assertEqual(1, local_limiter._counters["public-store:demo-store:create_payment:client:203.0.113.10"][0])
        self.assertEqual(1, local_limiter._counters["public-store:demo-store:create_payment:order:ORD123"][0])

    def test_public_store_write_ip_allowlist_returns_403(self) -> None:
        request = _request("198.51.100.10")
        redis_limiter = RedisFixedWindowRateLimiter(limit=10)
        local_limiter = FixedWindowRateLimiter(limit=10)

        with self.assertRaises(HTTPException) as context:
            asyncio.run(
                _hit_public_store_write_rate_limit(
                    redis_limiter,
                    local_limiter,
                    request,
                    "demo-store",
                    "create_order",
                    "buyer:42",
                    set(),
                    {"203.0.113.0/24"},
                )
            )

        self.assertEqual(403, context.exception.status_code)

    def test_public_store_write_rate_limit_uses_resolved_client_ip(self) -> None:
        request = _request("10.0.0.2", {"X-Forwarded-For": "203.0.113.10"})
        redis_limiter = RedisFixedWindowRateLimiter(limit=1)
        local_limiter = FixedWindowRateLimiter(limit=1)

        asyncio.run(
            _hit_public_store_write_rate_limit(
                redis_limiter,
                local_limiter,
                request,
                "demo-store",
                "create_order",
                "buyer:42",
                {"10.0.0.0/24"},
                set(),
            )
        )

        self.assertIn("public-store:demo-store:create_order:client:203.0.113.10", local_limiter._counters)

    def test_public_store_write_rate_limit_falls_back_to_local_when_redis_backend_fails(self) -> None:
        request = _request("203.0.113.10", redis=_FailingRedis())
        redis_limiter = RedisFixedWindowRateLimiter(limit=10)
        local_limiter = FixedWindowRateLimiter(limit=1)

        asyncio.run(
            _hit_public_store_write_rate_limit(
                redis_limiter,
                local_limiter,
                request,
                "demo-store",
                "create_order",
                "buyer:42",
                set(),
                set(),
            )
        )
        with self.assertRaises(HTTPException) as context:
            asyncio.run(
                _hit_public_store_write_rate_limit(
                    redis_limiter,
                    local_limiter,
                    request,
                    "demo-store",
                    "create_order",
                    "buyer:42",
                    set(),
                    set(),
                )
            )

        self.assertEqual(429, context.exception.status_code)

    def test_buyer_id_uses_verified_webapp_user(self) -> None:
        payload = CreatePublicOrderRequest(product_id="self:1", buyer_telegram_user_id=42)
        verified_user = TelegramWebAppUser(id=42)

        self.assertEqual(42, _buyer_telegram_user_id(payload, verified_user, True))

    def test_buyer_id_rejects_mismatch_with_verified_webapp_user(self) -> None:
        payload = CreatePublicOrderRequest(product_id="self:1", buyer_telegram_user_id=7)
        verified_user = TelegramWebAppUser(id=42)

        with self.assertRaises(HTTPException) as context:
            _buyer_telegram_user_id(payload, verified_user, True)

        self.assertEqual(401, context.exception.status_code)

    def test_buyer_id_requires_identity_when_init_data_is_required(self) -> None:
        payload = CreatePublicOrderRequest(product_id="self:1")

        with self.assertRaises(HTTPException) as context:
            _buyer_telegram_user_id(payload, None, True)

        self.assertEqual(401, context.exception.status_code)

    def test_verified_order_owner_blocks_cross_buyer_access(self) -> None:
        order = SimpleNamespace(buyer_telegram_user_id=7)

        with self.assertRaises(HTTPException) as context:
            _ensure_verified_order_owner(order, TelegramWebAppUser(id=42))

        self.assertEqual(404, context.exception.status_code)

    def test_buyer_ban_check_allows_missing_or_unbanned_user(self) -> None:
        missing_factory = _fake_session_factory(None)
        with patch("app.web.public_store.get_session_factory", return_value=missing_factory):
            asyncio.run(_ensure_buyer_not_banned(42))

        unbanned_factory = _fake_session_factory(False)
        with patch("app.web.public_store.get_session_factory", return_value=unbanned_factory):
            asyncio.run(_ensure_buyer_not_banned(42))

    def test_buyer_ban_check_rejects_banned_user(self) -> None:
        with patch("app.web.public_store.get_session_factory", return_value=_fake_session_factory(True)):
            with self.assertRaises(HTTPException) as context:
                asyncio.run(_ensure_buyer_not_banned(42))

        self.assertEqual(403, context.exception.status_code)
        self.assertEqual("买家账号已被平台限制", context.exception.detail)

    def test_list_public_products_strips_internal_product_and_supplier_fields(self) -> None:
        product = SimpleNamespace(
            id=3,
            name="自营商品",
            description="公开描述",
            delivery_type="card_pool",
            suggested_price=Decimal("99.00"),
            currency="USDT",
            supplier_tenant_id=88,
            external_source="acg",
            source_key="upstream",
            external_id="sku-1",
            locked_inventory_item_id=123,
            storage_key="private/file.zip",
        )
        variant = SimpleNamespace(price=Decimal("5.00"))
        reseller_product = SimpleNamespace(
            reseller_product_id=9,
            display_name="代理商品",
            category="会员",
            delivery_type="card_fixed",
            sale_price=Decimal("7.00"),
            currency="USDT",
            available_count=2,
            supplier_tenant_id=88,
            supplier_offer_id=12,
            external_source="acg",
            source_key="upstream",
            external_id="sku-2",
        )
        test_case = self

        async def list_public_products(self: object, session: object, tenant_id: int) -> list[tuple[object, object, int]]:
            test_case.assertEqual(7, tenant_id)
            return [(product, variant, 3)]

        async def list_public_reseller_products(self: object, session: object, tenant_id: int) -> list[object]:
            test_case.assertEqual(7, tenant_id)
            return [reseller_product]

        with patch("app.web.public_store.get_session_factory", return_value=_fake_session_factory()):
            with patch("app.web.public_store.ProductRepository.list_public_products", list_public_products):
                with patch("app.web.public_store.SupplyService.list_public_reseller_products", list_public_reseller_products):
                    items = asyncio.run(
                        _list_public_products(
                            7,
                            settings=Settings(public_base_url="https://store.example"),
                            tenant=SimpleNamespace(
                                self_sale_enabled=True,
                                supplier_enabled=False,
                                reseller_enabled=True,
                            ),
                        )
                    )

        payloads = [item.model_dump() for item in items]
        self.assertTrue(payloads[0]["id"].startswith("pub.v1.7.s."))
        self.assertTrue(payloads[1]["id"].startswith("pub.v1.7.r."))
        self.assertNotEqual("self:3", payloads[0]["id"])
        self.assertNotEqual("reseller:9", payloads[1]["id"])
        self.assertEqual(
            ("self", 3),
            _resolve_public_product_id(
                payloads[0]["id"],
                None,
                tenant_id=7,
                settings=Settings(public_base_url="https://store.example"),
            ),
        )
        self.assertEqual(
            ("reseller", 9),
            _resolve_public_product_id(
                payloads[1]["id"],
                None,
                tenant_id=7,
                settings=Settings(public_base_url="https://store.example"),
            ),
        )
        for payload in payloads:
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
                set(payload.keys()),
            )
            self.assertNotIn("supplier_tenant_id", payload)
            self.assertNotIn("supplier_offer_id", payload)
            self.assertNotIn("external_source", payload)
            self.assertNotIn("source_key", payload)
            self.assertNotIn("external_id", payload)
            self.assertNotIn("locked_inventory_item_id", payload)
            self.assertNotIn("storage_key", payload)

    def test_list_public_products_honors_feature_flags_before_reseller_lookup(self) -> None:
        product = SimpleNamespace(
            id=3,
            name="自营商品",
            description=None,
            delivery_type="card_pool",
            suggested_price=Decimal("99.00"),
            currency="USDT",
            delivery_file_id=None,
            telegram_chat_id=None,
        )
        variant = SimpleNamespace(price=Decimal("5.00"))

        async def list_public_products(self: object, session: object, tenant_id: int) -> list[tuple[object, object, int]]:
            return [(product, variant, 3)]

        async def list_public_reseller_products(self: object, session: object, tenant_id: int) -> list[object]:
            raise AssertionError("代理功能关闭时不应查询代理商品")

        with patch("app.web.public_store.get_session_factory", return_value=_fake_session_factory()):
            with patch("app.web.public_store.ProductRepository.list_public_products", list_public_products):
                with patch("app.web.public_store.SupplyService.list_public_reseller_products", list_public_reseller_products):
                    items = asyncio.run(
                        _list_public_products(
                            7,
                            settings=Settings(public_base_url="https://store.example"),
                            tenant=SimpleNamespace(
                                self_sale_enabled=True,
                                supplier_enabled=False,
                                reseller_enabled=False,
                            ),
                        )
                    )

        self.assertEqual(1, len(items))
        self.assertEqual("self", items[0].source_type)


def _request(client_host: str, headers: dict[str, str] | None = None, redis: object | None = None):
    return SimpleNamespace(
        client=SimpleNamespace(host=client_host),
        headers=headers or {},
        app=SimpleNamespace(state=SimpleNamespace(redis=redis)),
    )


class _FailingRedis:
    async def incr(self, key: str) -> int:
        raise RuntimeError("redis unavailable")


if __name__ == "__main__":
    unittest.main()
