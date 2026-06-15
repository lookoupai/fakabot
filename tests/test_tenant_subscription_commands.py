from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

try:
    from app.bots.context import TenantContext
    from app.bots.routers.tenant import renew_subscription, subscription
    from app.config import Settings
    from app.services.payments import PaymentUnavailableError
    from app.services.subscriptions import SubscriptionOrder, SubscriptionStatus
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过租户订阅命令测试：{exc.name}") from exc


class _FakeSession:
    def __init__(self) -> None:
        self.commit = AsyncMock()

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


def _session_factory(session: _FakeSession):
    def factory() -> _FakeSession:
        return session

    return factory


def _tenant_context() -> TenantContext:
    return TenantContext(
        tenant_id=7,
        tenant_public_id="tn_demo",
        tenant_bot_id=12,
        owner_user_id=3,
        owner_telegram_user_id=42,
        store_name="演示店铺",
        bot_username="demo_bot",
    )


def _message(*, telegram_user_id: int = 42) -> SimpleNamespace:
    return SimpleNamespace(
        from_user=SimpleNamespace(id=telegram_user_id),
        chat=SimpleNamespace(type="private"),
        answer=AsyncMock(),
    )


class TenantSubscriptionCommandTest(unittest.TestCase):
    def test_suspended_owner_can_view_subscription_status(self) -> None:
        message = _message()
        session = _FakeSession()
        status = SubscriptionStatus(
            tenant_id=7,
            status="suspended",
            plan_code="default_monthly",
            trial_ends_at=None,
            subscription_ends_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        )

        with patch("app.bots.routers.tenant.TenantRepository") as repo_class:
            repo = repo_class.return_value
            repo.has_permission = AsyncMock(return_value=True)
            with patch("app.bots.routers.tenant.SubscriptionService") as service_class:
                service = service_class.return_value
                service.get_status = AsyncMock(return_value=status)

                asyncio.run(
                    subscription(
                        message=message,
                        settings=Settings(subscription_monthly_price=Decimal("10")),
                        session_factory=_session_factory(session),
                        tenant_context=_tenant_context(),
                    )
                )

        reply = message.answer.await_args.args[0]
        self.assertIn("订阅状态", reply)
        self.assertIn("租户状态：suspended", reply)
        self.assertIn("套餐：default_monthly", reply)
        self.assertIn("当前月费：10 USDT", reply)
        self.assertIn("续费：/renew_subscription 月数", reply)
        repo.has_permission.assert_awaited_once()
        service.get_status.assert_awaited_once_with(session, 7)
        session.commit.assert_not_awaited()

    def test_non_subscription_admin_cannot_view_subscription_status(self) -> None:
        message = _message(telegram_user_id=99)
        session = _FakeSession()

        with patch("app.bots.routers.tenant.TenantRepository") as repo_class:
            repo = repo_class.return_value
            repo.has_permission = AsyncMock(return_value=False)
            with patch("app.bots.routers.tenant.SubscriptionService") as service_class:
                asyncio.run(
                    subscription(
                        message=message,
                        settings=Settings(subscription_monthly_price=Decimal("10")),
                        session_factory=_session_factory(session),
                        tenant_context=_tenant_context(),
                    )
                )

        message.answer.assert_awaited_once_with("无权限。需要权限：订阅续费。")
        repo.has_permission.assert_awaited_once()
        service_class.return_value.get_status.assert_not_called()
        session.commit.assert_not_awaited()

    def test_non_subscription_admin_cannot_create_renewal_order(self) -> None:
        message = _message(telegram_user_id=99)
        session = _FakeSession()

        with patch("app.bots.routers.tenant.TenantRepository") as repo_class:
            repo = repo_class.return_value
            repo.has_permission = AsyncMock(return_value=False)
            with patch("app.bots.routers.tenant.SubscriptionService") as subscription_service:
                with patch("app.bots.routers.tenant.PaymentService") as payment_service:
                    asyncio.run(
                        renew_subscription(
                            message=message,
                            command=SimpleNamespace(args="1"),
                            settings=Settings(),
                            session_factory=_session_factory(session),
                            tenant_context=_tenant_context(),
                        )
                    )

        message.answer.assert_awaited_once_with("无权限。需要权限：订阅续费。")
        repo.has_permission.assert_awaited_once()
        subscription_service.return_value.create_renewal_order.assert_not_called()
        payment_service.return_value.create_payment_for_order.assert_not_called()
        session.commit.assert_not_awaited()

    def test_invalid_renewal_months_does_not_open_order_or_payment_flow(self) -> None:
        message = _message()
        session = _FakeSession()

        with patch("app.bots.routers.tenant.TenantRepository") as repo_class:
            repo = repo_class.return_value
            repo.has_permission = AsyncMock(return_value=True)
            with patch("app.bots.routers.tenant.SubscriptionService") as subscription_service:
                with patch("app.bots.routers.tenant.PaymentService") as payment_service:
                    asyncio.run(
                        renew_subscription(
                            message=message,
                            command=SimpleNamespace(args="0"),
                            settings=Settings(),
                            session_factory=_session_factory(session),
                            tenant_context=_tenant_context(),
                        )
                    )

        message.answer.assert_awaited_once_with("续费月数范围为 1-24。")
        repo.has_permission.assert_awaited_once()
        subscription_service.return_value.create_renewal_order.assert_not_called()
        payment_service.return_value.create_payment_for_order.assert_not_called()
        session.commit.assert_not_awaited()

    def test_suspended_owner_can_create_renewal_order_and_payment_link(self) -> None:
        message = _message()
        session = _FakeSession()
        expires_at = datetime(2026, 6, 8, 12, 30, tzinfo=timezone.utc)
        renewal_order = SubscriptionOrder(
            order_id=1001,
            out_trade_no="SUB202606080001",
            amount=Decimal("20.00"),
            currency="USDT",
            months=2,
            expires_at=expires_at,
        )
        payment = SimpleNamespace(
            out_trade_no=renewal_order.out_trade_no,
            amount=renewal_order.amount,
            currency=renewal_order.currency,
            payment_url="https://pay.example/SUB202606080001",
        )

        with patch("app.bots.routers.tenant.TenantRepository") as repo_class:
            repo = repo_class.return_value
            repo.has_permission = AsyncMock(return_value=True)
            with patch("app.bots.routers.tenant.SubscriptionService") as subscription_service:
                subscription_service.return_value.create_renewal_order = AsyncMock(return_value=renewal_order)
                with patch("app.bots.routers.tenant.PaymentService") as payment_service:
                    payment_service.return_value.create_payment_for_order = AsyncMock(return_value=payment)

                    asyncio.run(
                        renew_subscription(
                            message=message,
                            command=SimpleNamespace(args="2"),
                            settings=Settings(subscription_monthly_price=Decimal("10")),
                            session_factory=_session_factory(session),
                            tenant_context=_tenant_context(),
                        )
                    )

        subscription_service.return_value.create_renewal_order.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            buyer_telegram_user_id=42,
            months=2,
            monthly_price=Decimal("10"),
        )
        payment_service.return_value.create_payment_for_order.assert_awaited_once_with(session, 1001)
        self.assertEqual(2, session.commit.await_count)
        reply = message.answer.await_args.args[0]
        self.assertIn("续费订单已创建", reply)
        self.assertIn("订单号：SUB202606080001", reply)
        self.assertIn("月数：2", reply)
        self.assertIn("支付链接：https://pay.example/SUB202606080001", reply)

    def test_renewal_order_survives_when_payment_config_is_unavailable(self) -> None:
        message = _message()
        session = _FakeSession()
        renewal_order = SubscriptionOrder(
            order_id=1002,
            out_trade_no="SUB202606080002",
            amount=Decimal("10.00"),
            currency="USDT",
            months=1,
            expires_at=datetime(2026, 6, 8, 12, 30, tzinfo=timezone.utc),
        )

        with patch("app.bots.routers.tenant.TenantRepository") as repo_class:
            repo = repo_class.return_value
            repo.has_permission = AsyncMock(return_value=True)
            with patch("app.bots.routers.tenant.SubscriptionService") as subscription_service:
                subscription_service.return_value.create_renewal_order = AsyncMock(return_value=renewal_order)
                with patch("app.bots.routers.tenant.PaymentService") as payment_service:
                    payment_service.return_value.create_payment_for_order = AsyncMock(
                        side_effect=PaymentUnavailableError("未配置支付")
                    )

                    asyncio.run(
                        renew_subscription(
                            message=message,
                            command=SimpleNamespace(args="1"),
                            settings=Settings(subscription_monthly_price=Decimal("10")),
                            session_factory=_session_factory(session),
                            tenant_context=_tenant_context(),
                        )
                    )

        self.assertEqual(1, session.commit.await_count)
        reply = message.answer.await_args.args[0]
        self.assertIn("续费订单已创建，但当前未启用 epusdt 支付配置", reply)
        self.assertIn("订单号：SUB202606080002", reply)
        self.assertIn("金额：10.00 USDT", reply)


if __name__ == "__main__":
    unittest.main()
