from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

try:
    from app.config import Settings
    from app.services.risk import OrderCreationRiskBlocked, RiskControlService
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过风控规则测试：{exc.name}") from exc


class RiskControlRulesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = RiskControlService()

    def test_after_sale_case_type_rejects_non_string_values(self) -> None:
        for value in (None, 123, True, [], {}):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "售后类型必须是字符串"):
                    self.service._normalize_after_sale_case_type(value)

    def test_after_sale_case_type_normalizes_known_values(self) -> None:
        self.assertEqual("refund", self.service._normalize_after_sale_case_type(" Refund "))
        self.assertEqual("complaint", self.service._normalize_after_sale_case_type("COMPLAINT"))

    def test_optional_amount_rejects_non_decimal_or_non_finite_values(self) -> None:
        for value in ("1.00", 1, 1.0, True):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "售后申请金额必须是 Decimal"):
                    self.service._normalize_optional_amount(value, "售后申请金额")
        for value in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "售后申请金额必须是有限数"):
                    self.service._normalize_optional_amount(value, "售后申请金额")

    def test_optional_amount_quantizes_down_and_rejects_non_positive_values(self) -> None:
        self.assertEqual(Decimal("1.23900000"), self.service._normalize_optional_amount(Decimal("1.239"), "售后申请金额"))
        for value in (Decimal("0"), Decimal("-1")):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "售后申请金额必须大于 0"):
                    self.service._normalize_optional_amount(value, "售后申请金额")

    def test_limit_rejects_non_integer_values_and_clamps_range(self) -> None:
        for value in (None, "20", Decimal("20"), True, False):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "查询数量必须是整数"):
                    self.service._normalize_limit(value)

        self.assertEqual(1, self.service._normalize_limit(0))
        self.assertEqual(20, self.service._normalize_limit(20))
        self.assertEqual(100, self.service._normalize_limit(999))

    def test_telegram_user_id_rejects_invalid_values(self) -> None:
        for value in (None, "42", Decimal("42"), True, False, 0, -1):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "Telegram 用户 ID 必须是正整数"):
                    self.service._normalize_telegram_user_id(value)

    def test_currency_normalization(self) -> None:
        self.assertEqual("USDT", self.service._normalize_currency(" usdt "))
        for value in (None, 123, True):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "币种必须是字符串"):
                    self.service._normalize_currency(value)
        with self.assertRaisesRegex(ValueError, "币种不能为空"):
            self.service._normalize_currency(" ")
        with self.assertRaisesRegex(ValueError, "币种长度不能超过 16 个字符"):
            self.service._normalize_currency("X" * 17)


class RiskControlListValidationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.service = RiskControlService()

    async def test_list_disputes_rejects_invalid_status_before_query(self) -> None:
        session = _FakeSession()

        with self.assertRaisesRegex(ValueError, "争议状态必须是"):
            await self.service.list_disputes(session, tenant_id=7, status="bad-status")

        self.assertEqual([], session.added)
        self.assertEqual(0, session.flush_count)


class RiskControlOrderCreationRulesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.service = RiskControlService()

    async def test_order_creation_risk_allows_under_thresholds(self) -> None:
        self.service._buyer_order_count_since = _async_return(4)
        self.service._buyer_order_amount_since = _async_return(Decimal("490.00"))
        session = _FakeSession()

        await self.service.ensure_order_creation_allowed(
            session,
            buyer_telegram_user_id=123456,
            amount=Decimal("10.00"),
            currency="usdt",
        )
        self.assertEqual([], session.added)

    async def test_order_creation_risk_rejects_recent_order_count(self) -> None:
        self.service._buyer_order_count_since = _async_return(5)
        self.service._buyer_order_amount_since = _async_return(Decimal("0"))
        session = _FakeSession()

        with self.assertRaisesRegex(OrderCreationRiskBlocked, "下单过于频繁"):
            await self.service.ensure_order_creation_allowed(
                session,
                buyer_telegram_user_id=123456,
                amount=Decimal("1.00"),
                currency="USDT",
                tenant_id=7,
                source_type="self",
            )
        audit = _single_order_creation_audit(session)
        self.assertEqual(7, audit.tenant_id)
        self.assertIsNone(audit.actor_user_id)
        self.assertEqual("platform_risk.order_creation_blocked", audit.action)
        self.assertEqual("order_creation", audit.target_type)
        self.assertEqual("123456", audit.target_id)
        self.assertEqual("recent_order_count", audit.metadata_json["rule"])
        self.assertEqual(123456, audit.metadata_json["buyer_telegram_user_id"])
        self.assertEqual("self", audit.metadata_json["source_type"])
        self.assertEqual("1.00000000", audit.metadata_json["amount"])
        self.assertEqual("USDT", audit.metadata_json["currency"])
        self.assertEqual(5, audit.metadata_json["recent_count"])
        self.assertEqual(60, audit.metadata_json["recent_window_seconds"])
        self.assertEqual(5, audit.metadata_json["recent_limit"])
        self.assertEqual(86400, audit.metadata_json["daily_window_seconds"])
        self.assertEqual("500", audit.metadata_json["daily_limit"])
        self.assertNotIn("daily_amount", audit.metadata_json)
        self.assertFalse(_contains_sensitive_key(audit.metadata_json))

    async def test_order_creation_risk_rejects_daily_amount_with_current_order(self) -> None:
        self.service._buyer_order_count_since = _async_return(0)
        self.service._buyer_order_amount_since = _async_return(Decimal("490.01"))
        session = _FakeSession()

        with self.assertRaisesRegex(OrderCreationRiskBlocked, "下单金额触发平台风控"):
            await self.service.ensure_order_creation_allowed(
                session,
                buyer_telegram_user_id=123456,
                amount=Decimal("10.00"),
                currency="usdt",
                tenant_id=7,
                source_type="reseller",
            )
        audit = _single_order_creation_audit(session)
        self.assertEqual(7, audit.tenant_id)
        self.assertEqual("daily_amount", audit.metadata_json["rule"])
        self.assertEqual("reseller", audit.metadata_json["source_type"])
        self.assertEqual("10.00000000", audit.metadata_json["amount"])
        self.assertEqual("USDT", audit.metadata_json["currency"])
        self.assertEqual("490.01", audit.metadata_json["daily_amount"])
        self.assertEqual("500.01000000", audit.metadata_json["daily_amount_with_current"])
        self.assertFalse(_contains_sensitive_key(audit.metadata_json))

    async def test_order_creation_risk_rejects_invalid_inputs(self) -> None:
        self.service._buyer_order_count_since = _async_return(0)
        self.service._buyer_order_amount_since = _async_return(Decimal("0"))
        session = _FakeSession()

        with self.assertRaisesRegex(ValueError, "Telegram 用户 ID 必须是正整数"):
            await self.service.ensure_order_creation_allowed(session, 0, Decimal("1.00"), "USDT")
        with self.assertRaisesRegex(ValueError, "订单金额必须是 Decimal"):
            await self.service.ensure_order_creation_allowed(session, 123456, "1.00", "USDT")
        with self.assertRaisesRegex(ValueError, "订单金额必须是有限数"):
            await self.service.ensure_order_creation_allowed(session, 123456, Decimal("NaN"), "USDT")
        with self.assertRaisesRegex(ValueError, "订单金额必须大于 0"):
            await self.service.ensure_order_creation_allowed(session, 123456, Decimal("0"), "USDT")
        self.assertEqual([], session.added)

    async def test_order_creation_risk_uses_custom_count_threshold(self) -> None:
        service = RiskControlService(Settings(order_risk_max_buyer_orders_per_window=2))
        service._buyer_order_count_since = _async_return(2)
        service._buyer_order_amount_since = _async_return(Decimal("0"))

        with self.assertRaisesRegex(ValueError, "下单过于频繁"):
            await service.ensure_order_creation_allowed(
                _FakeSession(),
                buyer_telegram_user_id=123456,
                amount=Decimal("1.00"),
                currency="USDT",
            )

    async def test_order_creation_risk_uses_custom_amount_threshold(self) -> None:
        service = RiskControlService(Settings(order_risk_max_buyer_amount_per_day=Decimal("100.00")))
        service._buyer_order_count_since = _async_return(0)
        service._buyer_order_amount_since = _async_return(Decimal("95.00"))

        with self.assertRaisesRegex(ValueError, "下单金额触发平台风控"):
            await service.ensure_order_creation_allowed(
                _FakeSession(),
                buyer_telegram_user_id=123456,
                amount=Decimal("5.01"),
                currency="USDT",
            )

    async def test_order_creation_risk_auto_ban_is_disabled_by_default(self) -> None:
        self.service._buyer_order_count_since = _async_return(5)
        self.service._buyer_order_amount_since = _async_return(Decimal("0"))
        session = _FakeSession()

        async def _unexpected_count(*args: object, **kwargs: object) -> int:
            raise AssertionError("自动处置关闭时不应统计风控拦截次数")

        self.service._order_risk_block_count_since = _unexpected_count

        with self.assertRaisesRegex(OrderCreationRiskBlocked, "下单过于频繁"):
            await self.service.ensure_order_creation_allowed(
                session,
                buyer_telegram_user_id=123456,
                amount=Decimal("1.00"),
                currency="USDT",
                tenant_id=7,
                source_type="self",
            )

        self.assertEqual(1, len(_audits_by_action(session, "platform_risk.order_creation_blocked")))
        self.assertEqual([], _audits_by_action(session, "platform_risk.user_auto_banned"))

    async def test_order_creation_risk_auto_ban_does_not_fire_below_threshold(self) -> None:
        service = RiskControlService(
            Settings(
                order_risk_auto_ban_enabled=True,
                order_risk_auto_ban_blocked_count_threshold=3,
            )
        )
        service._buyer_order_count_since = _async_return(5)
        service._buyer_order_amount_since = _async_return(Decimal("0"))
        service._order_risk_block_count_since = _async_return(2)
        session = _FakeSession()

        async def _unexpected_get_user(*args: object, **kwargs: object) -> object:
            raise AssertionError("未达阈值时不应锁定平台用户")

        service._get_or_create_platform_user_for_update = _unexpected_get_user

        with self.assertRaisesRegex(OrderCreationRiskBlocked, "下单过于频繁"):
            await service.ensure_order_creation_allowed(
                session,
                buyer_telegram_user_id=123456,
                amount=Decimal("1.00"),
                currency="USDT",
                tenant_id=7,
                source_type="self",
            )

        self.assertEqual(1, len(_audits_by_action(session, "platform_risk.order_creation_blocked")))
        self.assertEqual([], _audits_by_action(session, "platform_risk.user_auto_banned"))
        self.assertEqual(1, session.flush_count)

    async def test_order_creation_risk_auto_bans_user_at_threshold(self) -> None:
        service = RiskControlService(
            Settings(
                order_risk_auto_ban_enabled=True,
                order_risk_auto_ban_window_seconds=3600,
                order_risk_auto_ban_blocked_count_threshold=3,
            )
        )
        service._buyer_order_count_since = _async_return(5)
        service._buyer_order_amount_since = _async_return(Decimal("0"))
        service._order_risk_block_count_since = _async_return(3)
        user = SimpleNamespace(id=51, telegram_user_id=123456, is_banned=False)
        service._get_or_create_platform_user_for_update = _async_return(user)
        session = _FakeSession()

        with self.assertRaisesRegex(OrderCreationRiskBlocked, "下单过于频繁"):
            await service.ensure_order_creation_allowed(
                session,
                buyer_telegram_user_id=123456,
                amount=Decimal("1.00"),
                currency="USDT",
                tenant_id=7,
                source_type="self",
            )

        self.assertTrue(user.is_banned)
        self.assertEqual(1, len(_audits_by_action(session, "platform_risk.order_creation_blocked")))
        auto_ban_audits = _audits_by_action(session, "platform_risk.user_auto_banned")
        self.assertEqual(1, len(auto_ban_audits))
        audit = auto_ban_audits[0]
        self.assertIsNone(audit.tenant_id)
        self.assertIsNone(audit.actor_user_id)
        self.assertEqual("platform_user", audit.target_type)
        self.assertEqual("51", audit.target_id)
        self.assertEqual(123456, audit.metadata_json["telegram_user_id"])
        self.assertEqual("active", audit.metadata_json["previous_status"])
        self.assertEqual("banned", audit.metadata_json["new_status"])
        self.assertEqual("order_creation_risk_repeated_blocks", audit.metadata_json["reason"])
        self.assertEqual("platform_risk.order_creation_blocked", audit.metadata_json["trigger_action"])
        self.assertEqual("recent_order_count", audit.metadata_json["trigger_rule"])
        self.assertEqual(7, audit.metadata_json["trigger_tenant_id"])
        self.assertEqual("self", audit.metadata_json["trigger_source_type"])
        self.assertEqual(3, audit.metadata_json["blocked_count"])
        self.assertEqual(3, audit.metadata_json["threshold"])
        self.assertEqual(3600, audit.metadata_json["window_seconds"])
        self.assertTrue(audit.metadata_json["auto"])
        self.assertFalse(_contains_sensitive_key(audit.metadata_json))
        self.assertEqual(3, session.flush_count)

    async def test_order_creation_risk_auto_ban_skips_platform_admins(self) -> None:
        service = RiskControlService(
            Settings(
                platform_admin_ids={123456},
                order_risk_auto_ban_enabled=True,
                order_risk_auto_ban_blocked_count_threshold=3,
            )
        )
        service._buyer_order_count_since = _async_return(5)
        service._buyer_order_amount_since = _async_return(Decimal("0"))
        service._order_risk_block_count_since = _async_return(3)
        user = SimpleNamespace(
            id=51,
            telegram_user_id=123456,
            is_platform_admin=True,
            is_banned=False,
        )
        service._get_or_create_platform_user_for_update = _async_return(user)
        session = _FakeSession()

        with self.assertRaisesRegex(OrderCreationRiskBlocked, "下单过于频繁"):
            await service.ensure_order_creation_allowed(
                session,
                buyer_telegram_user_id=123456,
                amount=Decimal("1.00"),
                currency="USDT",
                tenant_id=7,
                source_type="self",
            )

        self.assertFalse(user.is_banned)
        self.assertEqual(1, len(_audits_by_action(session, "platform_risk.order_creation_blocked")))
        self.assertEqual([], _audits_by_action(session, "platform_risk.user_auto_banned"))

    async def test_order_creation_risk_auto_ban_does_not_duplicate_existing_ban(self) -> None:
        service = RiskControlService(
            Settings(
                order_risk_auto_ban_enabled=True,
                order_risk_auto_ban_blocked_count_threshold=3,
            )
        )
        service._buyer_order_count_since = _async_return(5)
        service._buyer_order_amount_since = _async_return(Decimal("0"))
        service._order_risk_block_count_since = _async_return(3)
        user = SimpleNamespace(id=51, telegram_user_id=123456, is_banned=True)
        service._get_or_create_platform_user_for_update = _async_return(user)
        session = _FakeSession()

        with self.assertRaisesRegex(OrderCreationRiskBlocked, "下单过于频繁"):
            await service.ensure_order_creation_allowed(
                session,
                buyer_telegram_user_id=123456,
                amount=Decimal("1.00"),
                currency="USDT",
                tenant_id=7,
                source_type="self",
            )

        self.assertTrue(user.is_banned)
        self.assertEqual(1, len(_audits_by_action(session, "platform_risk.order_creation_blocked")))
        self.assertEqual([], _audits_by_action(session, "platform_risk.user_auto_banned"))


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flush_count = 0

    def add(self, item: object) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        self.flush_count += 1


def _async_return(value: object) -> object:
    async def _inner(*args: object, **kwargs: object) -> object:
        return value

    return _inner


def _single_order_creation_audit(session: _FakeSession) -> object:
    audits = _audits_by_action(session, "platform_risk.order_creation_blocked")
    if len(audits) != 1:
        raise AssertionError(f"期望 1 条订单风控审计，实际 {len(audits)} 条")
    return audits[0]


def _audits_by_action(session: _FakeSession, action: str) -> list[object]:
    return [
        item
        for item in session.added
        if item.__class__.__name__ == "AuditLog" and getattr(item, "action", None) == action
    ]


def _contains_sensitive_key(metadata: dict[str, object]) -> bool:
    sensitive_words = ("token", "key", "secret", "payload", "card", "content")
    return any(word in key.lower() for key in metadata.keys() for word in sensitive_words)


class RiskControlPlatformUserBanTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.service = RiskControlService()

    async def test_ban_platform_user_updates_status_and_writes_audit(self) -> None:
        session = _FakeSession()
        user = SimpleNamespace(id=51, telegram_user_id=123456, is_banned=False)

        async def _get_or_create(_session: object, telegram_user_id: int) -> object:
            self.assertIs(session, _session)
            self.assertEqual(123456, telegram_user_id)
            return user

        self.service._get_or_create_platform_user_for_update = _get_or_create

        result = await self.service.ban_platform_user(
            session,
            telegram_user_id=123456,
            actor_user_id=99,
            reason=" spam ",
        )

        self.assertTrue(user.is_banned)
        self.assertEqual("platform_user", result.target_type)
        self.assertEqual(51, result.target_id)
        self.assertIsNone(result.tenant_id)
        self.assertEqual("active", result.previous_status)
        self.assertEqual("banned", result.new_status)
        self.assertEqual("spam", result.reason)
        self.assertEqual(2, session.flush_count)
        audits = [item for item in session.added if item.__class__.__name__ == "AuditLog"]
        self.assertEqual(1, len(audits))
        audit = audits[0]
        self.assertIsNone(audit.tenant_id)
        self.assertEqual(99, audit.actor_user_id)
        self.assertEqual("platform_risk.user_banned", audit.action)
        self.assertEqual("platform_user", audit.target_type)
        self.assertEqual("51", audit.target_id)
        self.assertEqual(123456, audit.metadata_json["telegram_user_id"])
        self.assertEqual("active", audit.metadata_json["previous_status"])
        self.assertEqual("banned", audit.metadata_json["new_status"])
        self.assertEqual("spam", audit.metadata_json["reason"])

    async def test_ban_platform_user_rejects_duplicate_ban_without_audit(self) -> None:
        session = _FakeSession()
        user = SimpleNamespace(id=51, telegram_user_id=123456, is_banned=True)

        async def _get_or_create(_session: object, telegram_user_id: int) -> object:
            return user

        self.service._get_or_create_platform_user_for_update = _get_or_create

        with self.assertRaisesRegex(ValueError, "用户已封禁"):
            await self.service.ban_platform_user(session, 123456, actor_user_id=99)

        self.assertEqual([], session.added)
        self.assertEqual(0, session.flush_count)

    async def test_ban_platform_user_hides_sensitive_reason_and_allows_platform_api_actor_none(self) -> None:
        session = _FakeSession()
        user = SimpleNamespace(id=51, telegram_user_id=123456, is_banned=False)

        async def _get_or_create(_session: object, telegram_user_id: int) -> object:
            return user

        self.service._get_or_create_platform_user_for_update = _get_or_create

        result = await self.service.ban_platform_user(
            session,
            telegram_user_id=123456,
            actor_user_id=None,
            reason="token=plain-secret https://callback.example",
        )

        self.assertEqual("内容已隐藏", result.reason)
        audit = session.added[0]
        self.assertIsNone(audit.actor_user_id)
        self.assertEqual("内容已隐藏", audit.metadata_json["reason"])
        self.assertNotIn("plain-secret", repr(audit.metadata_json))
        self.assertNotIn("callback.example", repr(audit.metadata_json))

    async def test_unban_platform_user_updates_status_and_writes_audit(self) -> None:
        session = _FakeSession()
        user = SimpleNamespace(id=52, telegram_user_id=654321, is_banned=True)

        async def _get_user(_session: object, telegram_user_id: int) -> object:
            self.assertIs(session, _session)
            self.assertEqual(654321, telegram_user_id)
            return user

        self.service._get_platform_user_for_update = _get_user

        result = await self.service.unban_platform_user(
            session,
            telegram_user_id=654321,
            actor_user_id=99,
            reason=" appeal accepted ",
        )

        self.assertFalse(user.is_banned)
        self.assertEqual("platform_user", result.target_type)
        self.assertEqual(52, result.target_id)
        self.assertEqual("banned", result.previous_status)
        self.assertEqual("active", result.new_status)
        self.assertEqual("appeal accepted", result.reason)
        self.assertEqual(1, session.flush_count)
        audit = session.added[0]
        self.assertEqual("platform_risk.user_unbanned", audit.action)
        self.assertEqual(654321, audit.metadata_json["telegram_user_id"])
        self.assertEqual("banned", audit.metadata_json["previous_status"])
        self.assertEqual("active", audit.metadata_json["new_status"])

    async def test_unban_platform_user_rejects_missing_or_active_user(self) -> None:
        session = _FakeSession()

        async def _missing_user(_session: object, telegram_user_id: int) -> object:
            return None

        self.service._get_platform_user_for_update = _missing_user
        with self.assertRaisesRegex(ValueError, "用户不存在"):
            await self.service.unban_platform_user(session, 654321, actor_user_id=99)

        user = SimpleNamespace(id=52, telegram_user_id=654321, is_banned=False)

        async def _active_user(_session: object, telegram_user_id: int) -> object:
            return user

        self.service._get_platform_user_for_update = _active_user
        with self.assertRaisesRegex(ValueError, "用户未封禁"):
            await self.service.unban_platform_user(session, 654321, actor_user_id=99)

        self.assertEqual([], session.added)
        self.assertEqual(0, session.flush_count)


class RiskControlTenantSuspensionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.service = RiskControlService()

    async def test_suspend_tenant_allows_platform_api_actor_none_and_hides_sensitive_reason(self) -> None:
        session = _FakeSession()
        tenant = SimpleNamespace(id=7, status="active", suspended_at=None)

        async def _get_tenant(_session: object, tenant_id: int) -> object:
            self.assertIs(session, _session)
            self.assertEqual(7, tenant_id)
            return tenant

        self.service._get_tenant_for_update = _get_tenant
        self.service._tenant_webhook_secrets = _async_return(("secret-one",))

        result = await self.service.suspend_tenant(
            session,
            tenant_id=7,
            actor_user_id=None,
            reason="token=plain-secret https://callback.example",
        )

        self.assertEqual("suspended", tenant.status)
        self.assertIsNotNone(tenant.suspended_at)
        self.assertEqual("tenant", result.target_type)
        self.assertEqual(7, result.target_id)
        self.assertEqual(7, result.tenant_id)
        self.assertEqual("active", result.previous_status)
        self.assertEqual("suspended", result.new_status)
        self.assertEqual("内容已隐藏", result.reason)
        self.assertEqual(("secret-one",), result.webhook_secrets)
        self.assertEqual(1, session.flush_count)
        audit = session.added[0]
        self.assertEqual(7, audit.tenant_id)
        self.assertIsNone(audit.actor_user_id)
        self.assertEqual("platform_risk.tenant_suspended", audit.action)
        self.assertEqual("tenant", audit.target_type)
        self.assertEqual("7", audit.target_id)
        self.assertEqual("active", audit.metadata_json["previous_status"])
        self.assertEqual("suspended", audit.metadata_json["new_status"])
        self.assertEqual("内容已隐藏", audit.metadata_json["reason"])
        self.assertNotIn("plain-secret", repr(audit.metadata_json))
        self.assertNotIn("callback.example", repr(audit.metadata_json))

    async def test_resume_tenant_allows_platform_api_actor_none_and_restores_previous_status(self) -> None:
        session = _FakeSession()
        tenant = SimpleNamespace(id=7, status="suspended", suspended_at=datetime.now(timezone.utc))

        async def _get_tenant(_session: object, tenant_id: int) -> object:
            self.assertIs(session, _session)
            self.assertEqual(7, tenant_id)
            return tenant

        self.service._get_tenant_for_update = _get_tenant
        self.service._last_status_before_suspension = _async_return("grace")
        self.service._tenant_webhook_secrets = _async_return(("secret-one",))

        result = await self.service.resume_tenant(
            session,
            tenant_id=7,
            actor_user_id=None,
            reason="appeal accepted",
        )

        self.assertEqual("grace", tenant.status)
        self.assertIsNone(tenant.suspended_at)
        self.assertEqual("suspended", result.previous_status)
        self.assertEqual("grace", result.new_status)
        self.assertEqual("appeal accepted", result.reason)
        self.assertEqual(("secret-one",), result.webhook_secrets)
        self.assertEqual(1, session.flush_count)
        audit = session.added[0]
        self.assertEqual(7, audit.tenant_id)
        self.assertIsNone(audit.actor_user_id)
        self.assertEqual("platform_risk.tenant_resumed", audit.action)
        self.assertEqual("suspended", audit.metadata_json["previous_status"])
        self.assertEqual("grace", audit.metadata_json["new_status"])
        self.assertEqual("appeal accepted", audit.metadata_json["reason"])


class PlatformRiskObservabilityTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.service = RiskControlService()

    async def test_list_banned_platform_users_returns_manual_ban_summary(self) -> None:
        now = datetime(2026, 6, 9, 8, 0, tzinfo=timezone.utc)
        user = SimpleNamespace(
            id=51,
            telegram_user_id=123456,
            username="buyer",
            is_banned=True,
            created_at=now,
            updated_at=now,
        )
        audit = SimpleNamespace(
            action="platform_risk.user_banned",
            metadata_json={"reason": " spam "},
            created_at=now,
        )
        self.service._list_banned_platform_user_rows = _async_return([user])
        self.service._latest_platform_user_ban_audit = _async_return(audit)

        summaries = await self.service.list_banned_platform_users(_FakeSession(), source="manual", limit=20)

        self.assertEqual(1, len(summaries))
        summary = summaries[0]
        self.assertEqual(123456, summary.telegram_user_id)
        self.assertEqual("buyer", summary.username)
        self.assertTrue(summary.is_banned)
        self.assertEqual("manual", summary.ban_source)
        self.assertEqual("platform_risk.user_banned", summary.latest_action)
        self.assertEqual("spam", summary.reason)
        self.assertIsNone(summary.trigger_rule)

    async def test_list_banned_platform_users_returns_auto_ban_summary(self) -> None:
        now = datetime(2026, 6, 9, 8, 0, tzinfo=timezone.utc)
        user = SimpleNamespace(
            id=52,
            telegram_user_id=654321,
            username=None,
            is_banned=True,
            created_at=now,
            updated_at=now,
        )
        audit = SimpleNamespace(
            action="platform_risk.user_auto_banned",
            metadata_json={
                "reason": "order_creation_risk_repeated_blocks",
                "trigger_rule": "recent_order_count",
                "trigger_tenant_id": 7,
                "blocked_count": 3,
                "threshold": 3,
                "window_seconds": 3600,
            },
            created_at=now,
        )
        self.service._list_banned_platform_user_rows = _async_return([user])
        self.service._latest_platform_user_ban_audit = _async_return(audit)

        summaries = await self.service.list_banned_platform_users(_FakeSession(), source="auto", limit=20)

        self.assertEqual(1, len(summaries))
        summary = summaries[0]
        self.assertEqual("auto", summary.ban_source)
        self.assertEqual("order_creation_risk_repeated_blocks", summary.reason)
        self.assertEqual("recent_order_count", summary.trigger_rule)
        self.assertEqual(3, summary.blocked_count)
        self.assertEqual(3, summary.threshold)
        self.assertEqual(3600, summary.window_seconds)
        rendered = repr(summary)
        self.assertNotIn("trigger_tenant_id", rendered)
        self.assertNotIn("tenant_id", rendered)

    async def test_list_banned_platform_users_filters_source_by_latest_action(self) -> None:
        now = datetime(2026, 6, 9, 8, 0, tzinfo=timezone.utc)
        manual_user = SimpleNamespace(id=51, telegram_user_id=111, username=None, is_banned=True, created_at=now, updated_at=now)
        auto_user = SimpleNamespace(id=52, telegram_user_id=222, username=None, is_banned=True, created_at=now, updated_at=now)
        audits = {
            51: SimpleNamespace(action="platform_risk.user_banned", metadata_json={"reason": "manual"}, created_at=now),
            52: SimpleNamespace(action="platform_risk.user_auto_banned", metadata_json={"reason": "auto"}, created_at=now),
        }
        self.service._list_banned_platform_user_rows = _async_return([manual_user, auto_user])

        async def _latest(_session: object, platform_user_id: int) -> object:
            return audits[platform_user_id]

        self.service._latest_platform_user_ban_audit = _latest

        summaries = await self.service.list_banned_platform_users(_FakeSession(), source="auto", limit=20)

        self.assertEqual([222], [summary.telegram_user_id for summary in summaries])

    async def test_list_banned_platform_users_filters_telegram_user_id_exactly(self) -> None:
        calls: list[dict[str, object]] = []

        async def _list_rows(_session: object, *, telegram_user_id: int | None, limit: int) -> list[object]:
            calls.append({"telegram_user_id": telegram_user_id, "limit": limit})
            return []

        self.service._list_banned_platform_user_rows = _list_rows

        summaries = await self.service.list_banned_platform_users(
            _FakeSession(),
            telegram_user_id=123456,
            limit=500,
        )

        self.assertEqual([], summaries)
        self.assertEqual([{"telegram_user_id": 123456, "limit": 100}], calls)

    async def test_list_banned_platform_users_sanitizes_reason_and_omits_raw_metadata(self) -> None:
        now = datetime(2026, 6, 9, 8, 0, tzinfo=timezone.utc)
        user = SimpleNamespace(id=51, telegram_user_id=123456, username=None, is_banned=True, created_at=now, updated_at=now)
        audit = SimpleNamespace(
            action="platform_risk.user_banned",
            metadata_json={
                "reason": "https://evil.example/?token=plain-secret",
                "trigger_rule": "api_key=plain-secret",
                "payload": {"token": "plain-secret"},
            },
            created_at=now,
        )
        self.service._list_banned_platform_user_rows = _async_return([user])
        self.service._latest_platform_user_ban_audit = _async_return(audit)

        summaries = await self.service.list_banned_platform_users(_FakeSession())

        summary = summaries[0]
        self.assertEqual("内容已隐藏", summary.reason)
        self.assertEqual("内容已隐藏", summary.trigger_rule)
        rendered = repr(summary)
        self.assertNotIn("plain-secret", rendered)
        self.assertNotIn("payload", rendered)
        self.assertNotIn("metadata_json", rendered)

    async def test_list_banned_platform_users_rejects_invalid_filters_before_query(self) -> None:
        async def _list_rows(*args: object, **kwargs: object) -> list[object]:
            raise AssertionError("不应在参数无效时查询")

        self.service._list_banned_platform_user_rows = _list_rows

        with self.assertRaisesRegex(ValueError, "封禁来源必须是"):
            await self.service.list_banned_platform_users(_FakeSession(), source="bad")
        with self.assertRaisesRegex(ValueError, "Telegram 用户 ID 必须是正整数"):
            await self.service.list_banned_platform_users(_FakeSession(), telegram_user_id=0)
        with self.assertRaisesRegex(ValueError, "查询数量必须是整数"):
            await self.service.list_banned_platform_users(_FakeSession(), limit=True)

    async def test_get_platform_user_ban_status_returns_manual_banned_user(self) -> None:
        now = datetime(2026, 6, 9, 8, 0, tzinfo=timezone.utc)
        user = SimpleNamespace(id=51, telegram_user_id=123456, username="buyer", is_banned=True, created_at=now, updated_at=now)
        status_audit = SimpleNamespace(action="platform_risk.user_banned", metadata_json={"reason": " spam "}, created_at=now)
        ban_audit = status_audit
        self.service._get_platform_user_by_telegram_user_id = _async_return(user)
        self.service._latest_platform_user_status_audit = _async_return(status_audit)
        self.service._latest_platform_user_ban_audit = _async_return(ban_audit)

        summary = await self.service.get_platform_user_ban_status(_FakeSession(), 123456)

        self.assertIsNotNone(summary)
        self.assertEqual(123456, summary.telegram_user_id)
        self.assertEqual("buyer", summary.username)
        self.assertTrue(summary.is_banned)
        self.assertEqual("manual", summary.ban_source)
        self.assertEqual("platform_risk.user_banned", summary.latest_action)
        self.assertEqual("spam", summary.reason)

    async def test_get_platform_user_ban_status_returns_auto_banned_user(self) -> None:
        now = datetime(2026, 6, 9, 8, 0, tzinfo=timezone.utc)
        user = SimpleNamespace(id=52, telegram_user_id=654321, username=None, is_banned=True, created_at=now, updated_at=now)
        status_audit = SimpleNamespace(
            action="platform_risk.user_auto_banned",
            metadata_json={"reason": "order_creation_risk_repeated_blocks"},
            created_at=now,
        )
        ban_audit = SimpleNamespace(
            action="platform_risk.user_auto_banned",
            metadata_json={
                "reason": "order_creation_risk_repeated_blocks",
                "trigger_rule": "recent_order_count",
                "blocked_count": 3,
                "threshold": 3,
                "window_seconds": 3600,
                "trigger_tenant_id": 7,
            },
            created_at=now,
        )
        self.service._get_platform_user_by_telegram_user_id = _async_return(user)
        self.service._latest_platform_user_status_audit = _async_return(status_audit)
        self.service._latest_platform_user_ban_audit = _async_return(ban_audit)

        summary = await self.service.get_platform_user_ban_status(_FakeSession(), 654321)

        self.assertIsNotNone(summary)
        self.assertTrue(summary.is_banned)
        self.assertEqual("auto", summary.ban_source)
        self.assertEqual("order_creation_risk_repeated_blocks", summary.reason)
        self.assertEqual("recent_order_count", summary.trigger_rule)
        self.assertEqual(3, summary.blocked_count)
        self.assertEqual(3, summary.threshold)
        self.assertEqual(3600, summary.window_seconds)
        self.assertNotIn("trigger_tenant_id", repr(summary))

    async def test_get_platform_user_ban_status_returns_unbanned_user_with_latest_unban_action(self) -> None:
        now = datetime(2026, 6, 9, 8, 0, tzinfo=timezone.utc)
        user = SimpleNamespace(id=53, telegram_user_id=777, username="ok", is_banned=False, created_at=now, updated_at=now)
        status_audit = SimpleNamespace(
            action="platform_risk.user_unbanned",
            metadata_json={"reason": " appeal accepted "},
            created_at=now,
        )
        self.service._get_platform_user_by_telegram_user_id = _async_return(user)
        self.service._latest_platform_user_status_audit = _async_return(status_audit)

        async def _latest_ban(*args: object, **kwargs: object) -> object:
            raise AssertionError("未封禁用户不需要查询最近封禁审计")

        self.service._latest_platform_user_ban_audit = _latest_ban

        summary = await self.service.get_platform_user_ban_status(_FakeSession(), 777)

        self.assertIsNotNone(summary)
        self.assertFalse(summary.is_banned)
        self.assertIsNone(summary.ban_source)
        self.assertEqual("platform_risk.user_unbanned", summary.latest_action)
        self.assertEqual("appeal accepted", summary.reason)
        self.assertIsNone(summary.trigger_rule)

    async def test_get_platform_user_ban_status_returns_none_for_missing_user(self) -> None:
        self.service._get_platform_user_by_telegram_user_id = _async_return(None)

        summary = await self.service.get_platform_user_ban_status(_FakeSession(), 123456)

        self.assertIsNone(summary)

    async def test_get_platform_user_ban_status_uses_db_ban_flag_as_source_of_truth(self) -> None:
        now = datetime(2026, 6, 9, 8, 0, tzinfo=timezone.utc)
        user = SimpleNamespace(id=54, telegram_user_id=888, username=None, is_banned=False, created_at=now, updated_at=now)
        status_audit = SimpleNamespace(
            action="platform_risk.user_banned",
            metadata_json={"reason": "old ban"},
            created_at=now,
        )
        self.service._get_platform_user_by_telegram_user_id = _async_return(user)
        self.service._latest_platform_user_status_audit = _async_return(status_audit)

        summary = await self.service.get_platform_user_ban_status(_FakeSession(), 888)

        self.assertIsNotNone(summary)
        self.assertFalse(summary.is_banned)
        self.assertIsNone(summary.ban_source)
        self.assertEqual("platform_risk.user_banned", summary.latest_action)

    async def test_get_platform_user_ban_status_sanitizes_reason_and_trigger_rule(self) -> None:
        now = datetime(2026, 6, 9, 8, 0, tzinfo=timezone.utc)
        user = SimpleNamespace(id=55, telegram_user_id=999, username=None, is_banned=True, created_at=now, updated_at=now)
        status_audit = SimpleNamespace(
            action="platform_risk.user_banned",
            metadata_json={"reason": "https://evil.example/?token=plain-secret"},
            created_at=now,
        )
        ban_audit = SimpleNamespace(
            action="platform_risk.user_banned",
            metadata_json={"trigger_rule": "api_key=plain-secret", "payload": "plain-secret"},
            created_at=now,
        )
        self.service._get_platform_user_by_telegram_user_id = _async_return(user)
        self.service._latest_platform_user_status_audit = _async_return(status_audit)
        self.service._latest_platform_user_ban_audit = _async_return(ban_audit)

        summary = await self.service.get_platform_user_ban_status(_FakeSession(), 999)

        self.assertIsNotNone(summary)
        self.assertEqual("内容已隐藏", summary.reason)
        self.assertEqual("内容已隐藏", summary.trigger_rule)
        rendered = repr(summary)
        self.assertNotIn("plain-secret", rendered)
        self.assertNotIn("payload", rendered)

    async def test_get_platform_user_ban_status_rejects_invalid_telegram_user_id_before_query(self) -> None:
        async def _get_user(*args: object, **kwargs: object) -> object:
            raise AssertionError("不应在参数无效时查询")

        self.service._get_platform_user_by_telegram_user_id = _get_user

        with self.assertRaisesRegex(ValueError, "Telegram 用户 ID 必须是正整数"):
            await self.service.get_platform_user_ban_status(_FakeSession(), 0)


if __name__ == "__main__":
    unittest.main()
