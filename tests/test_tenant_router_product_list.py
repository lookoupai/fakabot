from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

try:
    from app.bots.context import TenantContext
    from app.bots.routers.tenant import (
        _create_order_for_buyer,
        _create_reseller_order_for_buyer,
        _send_public_product_list,
    )
    from app.config import Settings
    from app.services.risk import OrderCreationRiskBlocked
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过租户商品列表测试：{exc.name}") from exc


class _FakeSession:
    def __init__(self) -> None:
        self.commit = AsyncMock()

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


def _session_factory() -> _FakeSession:
    return _FakeSession()


def _static_session_factory(session: _FakeSession):
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


class TenantRouterProductListTest(unittest.TestCase):
    def test_empty_public_product_list_shows_empty_state_and_home_only(self) -> None:
        message = SimpleNamespace(answer=AsyncMock())

        with patch("app.bots.routers.tenant.TenantRepository") as tenant_repo:
            with patch("app.bots.routers.tenant.ProductRepository") as product_repo:
                with patch("app.bots.routers.tenant.SupplyService") as supply_service:
                    tenant_repo.return_value.get_tenant = AsyncMock(return_value=SimpleNamespace(status="active"))
                    product_repo.return_value.list_public_products = AsyncMock(return_value=[])
                    supply_service.return_value.list_public_reseller_products = AsyncMock(return_value=[])

                    asyncio.run(_send_public_product_list(message, _session_factory, _tenant_context()))

        text = message.answer.await_args.args[0]
        reply_markup = message.answer.await_args.kwargs["reply_markup"]

        self.assertIn("商品列表", text)
        self.assertIn("当前店铺还没有上架商品", text)
        self.assertEqual({"tenant:home"}, _callback_data_set(reply_markup))

    def test_suspended_store_product_list_hides_buy_buttons(self) -> None:
        message = SimpleNamespace(answer=AsyncMock())

        with _patch_product_list_dependencies(tenant_status="suspended"):
            asyncio.run(_send_public_product_list(message, _session_factory, _tenant_context()))

        text = message.answer.await_args.args[0]
        reply_markup = message.answer.await_args.kwargs["reply_markup"]

        self.assertIn("店铺当前不可下单", text)
        self.assertNotIn("tenant:buy:1", _callback_data_set(reply_markup))
        self.assertIn("tenant:home", _callback_data_set(reply_markup))

    def test_active_store_product_list_exposes_buy_button(self) -> None:
        message = SimpleNamespace(answer=AsyncMock())

        with _patch_product_list_dependencies(tenant_status="active"):
            asyncio.run(_send_public_product_list(message, _session_factory, _tenant_context()))

        text = message.answer.await_args.args[0]
        reply_markup = message.answer.await_args.kwargs["reply_markup"]

        self.assertNotIn("店铺当前不可下单", text)
        self.assertIn("tenant:buy:1", _callback_data_set(reply_markup))

    def test_feature_flags_hide_self_and_reseller_products(self) -> None:
        message = SimpleNamespace(answer=AsyncMock())

        with _patch_product_list_dependencies(tenant_status="active", include_reseller=True):
            asyncio.run(
                _send_public_product_list(
                    message,
                    _session_factory,
                    _tenant_context(),
                    {"self_sale": False, "reseller": False},
                )
            )

        text = message.answer.await_args.args[0]
        reply_markup = message.answer.await_args.kwargs["reply_markup"]

        self.assertIn("当前店铺还没有上架商品", text)
        self.assertNotIn("测试商品", text)
        self.assertNotIn("代理商品", text)
        self.assertEqual({"tenant:home"}, _callback_data_set(reply_markup))

    def test_disabled_reseller_feature_blocks_direct_reseller_order_before_service(self) -> None:
        message = SimpleNamespace(answer=AsyncMock())
        session = _FakeSession()

        with patch("app.bots.routers.tenant.OrderService") as order_service:
            with patch("app.bots.routers.tenant.PaymentService") as payment_service:
                asyncio.run(
                    _create_reseller_order_for_buyer(
                        message=message,
                        settings=Settings(),
                        session_factory=_static_session_factory(session),
                        tenant_context=_tenant_context(),
                        buyer_telegram_user_id=42,
                        reseller_product_id=9,
                        tenant_feature_flags={"reseller": False},
                    )
                )

        order_service.return_value.create_reseller_order.assert_not_called()
        payment_service.return_value.create_payment_for_order.assert_not_called()
        session.commit.assert_not_awaited()
        message.answer.assert_awaited_once_with("代理售卖功能已关闭")

    def test_create_self_order_commits_when_order_risk_is_blocked(self) -> None:
        message = SimpleNamespace(answer=AsyncMock())
        session = _FakeSession()

        with patch("app.bots.routers.tenant._order_timeout_minutes", AsyncMock(return_value=15)):
            with patch("app.bots.routers.tenant.OrderService") as order_service:
                create_self_order = AsyncMock(
                    side_effect=OrderCreationRiskBlocked("下单过于频繁，请稍后再试")
                )
                order_service.return_value.create_self_order = create_self_order
                asyncio.run(
                    _create_order_for_buyer(
                        message=message,
                        settings=Settings(),
                        session_factory=_static_session_factory(session),
                        tenant_context=_tenant_context(),
                        buyer_telegram_user_id=42,
                        product_id=1,
                    )
                )

        create_self_order.assert_awaited_once()
        session.commit.assert_awaited_once()
        message.answer.assert_awaited_once_with("下单过于频繁，请稍后再试")

    def test_create_self_order_does_not_commit_regular_value_error(self) -> None:
        message = SimpleNamespace(answer=AsyncMock())
        session = _FakeSession()

        with patch("app.bots.routers.tenant._order_timeout_minutes", AsyncMock(return_value=15)):
            with patch("app.bots.routers.tenant.OrderService") as order_service:
                create_self_order = AsyncMock(side_effect=ValueError("库存不足"))
                order_service.return_value.create_self_order = create_self_order
                asyncio.run(
                    _create_order_for_buyer(
                        message=message,
                        settings=Settings(),
                        session_factory=_static_session_factory(session),
                        tenant_context=_tenant_context(),
                        buyer_telegram_user_id=42,
                        product_id=1,
                    )
                )

        create_self_order.assert_awaited_once()
        session.commit.assert_not_awaited()
        message.answer.assert_awaited_once_with("库存不足")

    def test_direct_buy_on_suspended_store_does_not_create_payment_or_commit(self) -> None:
        message = SimpleNamespace(answer=AsyncMock())
        session = _FakeSession()

        with patch("app.bots.routers.tenant._order_timeout_minutes", AsyncMock(return_value=15)):
            with patch("app.bots.routers.tenant.OrderService") as order_service:
                with patch("app.bots.routers.tenant.PaymentService") as payment_service:
                    create_self_order = AsyncMock(side_effect=ValueError("店铺当前不可下单"))
                    order_service.return_value.create_self_order = create_self_order
                    asyncio.run(
                        _create_order_for_buyer(
                            message=message,
                            settings=Settings(),
                            session_factory=_static_session_factory(session),
                            tenant_context=_tenant_context(),
                            buyer_telegram_user_id=42,
                            product_id=1,
                        )
                    )

        create_self_order.assert_awaited_once()
        payment_service.return_value.create_payment_for_order.assert_not_called()
        session.commit.assert_not_awaited()
        message.answer.assert_awaited_once_with("店铺当前不可下单")

    def test_create_reseller_order_commits_when_order_risk_is_blocked(self) -> None:
        message = SimpleNamespace(answer=AsyncMock())
        session = _FakeSession()

        with patch("app.bots.routers.tenant._order_timeout_minutes", AsyncMock(return_value=15)):
            with patch("app.bots.routers.tenant.OrderService") as order_service:
                create_reseller_order = AsyncMock(
                    side_effect=OrderCreationRiskBlocked("下单金额触发平台风控，请稍后再试")
                )
                order_service.return_value.create_reseller_order = create_reseller_order
                asyncio.run(
                    _create_reseller_order_for_buyer(
                        message=message,
                        settings=Settings(),
                        session_factory=_static_session_factory(session),
                        tenant_context=_tenant_context(),
                        buyer_telegram_user_id=42,
                        reseller_product_id=9,
                        tenant_feature_flags={"reseller": True},
                    )
                )

        create_reseller_order.assert_awaited_once()
        session.commit.assert_awaited_once()
        message.answer.assert_awaited_once_with("下单金额触发平台风控，请稍后再试")

    def test_create_reseller_order_does_not_commit_regular_value_error(self) -> None:
        message = SimpleNamespace(answer=AsyncMock())
        session = _FakeSession()

        with patch("app.bots.routers.tenant._order_timeout_minutes", AsyncMock(return_value=15)):
            with patch("app.bots.routers.tenant.OrderService") as order_service:
                create_reseller_order = AsyncMock(side_effect=ValueError("代理商品不存在或不可售"))
                order_service.return_value.create_reseller_order = create_reseller_order
                asyncio.run(
                    _create_reseller_order_for_buyer(
                        message=message,
                        settings=Settings(),
                        session_factory=_static_session_factory(session),
                        tenant_context=_tenant_context(),
                        buyer_telegram_user_id=42,
                        reseller_product_id=9,
                        tenant_feature_flags={"reseller": True},
                    )
                )

        create_reseller_order.assert_awaited_once()
        session.commit.assert_not_awaited()
        message.answer.assert_awaited_once_with("代理商品不存在或不可售")

    def test_direct_reseller_buy_on_suspended_store_does_not_create_payment_or_commit(self) -> None:
        message = SimpleNamespace(answer=AsyncMock())
        session = _FakeSession()

        with patch("app.bots.routers.tenant._order_timeout_minutes", AsyncMock(return_value=15)):
            with patch("app.bots.routers.tenant.OrderService") as order_service:
                with patch("app.bots.routers.tenant.PaymentService") as payment_service:
                    create_reseller_order = AsyncMock(side_effect=ValueError("店铺当前不可下单"))
                    order_service.return_value.create_reseller_order = create_reseller_order
                    asyncio.run(
                        _create_reseller_order_for_buyer(
                            message=message,
                            settings=Settings(),
                            session_factory=_static_session_factory(session),
                            tenant_context=_tenant_context(),
                            buyer_telegram_user_id=42,
                            reseller_product_id=9,
                            tenant_feature_flags={"reseller": True},
                        )
                    )

        create_reseller_order.assert_awaited_once()
        payment_service.return_value.create_payment_for_order.assert_not_called()
        session.commit.assert_not_awaited()
        message.answer.assert_awaited_once_with("店铺当前不可下单")


def _patch_product_list_dependencies(tenant_status: str, include_reseller: bool = False):
    product = SimpleNamespace(
        id=1,
        name="测试商品",
        delivery_type="card_pool",
        suggested_price=Decimal("9.90"),
        currency="USDT",
        delivery_file_id=None,
        telegram_chat_id=None,
    )
    variant = SimpleNamespace(price=Decimal("9.90"))
    reseller_product = SimpleNamespace(
        reseller_product_id=9,
        display_name="代理商品",
        delivery_type="card_pool",
        sale_price=Decimal("12.00"),
        currency="USDT",
        available_count=1,
    )

    tenant_repo_patch = patch("app.bots.routers.tenant.TenantRepository")
    product_repo_patch = patch("app.bots.routers.tenant.ProductRepository")
    supply_service_patch = patch("app.bots.routers.tenant.SupplyService")

    class _PatchContext:
        def __enter__(self) -> "_PatchContext":
            self.tenant_repo_cls = tenant_repo_patch.__enter__()
            self.product_repo_cls = product_repo_patch.__enter__()
            self.supply_service_cls = supply_service_patch.__enter__()

            self.tenant_repo_cls.return_value.get_tenant = AsyncMock(
                return_value=SimpleNamespace(status=tenant_status)
            )
            self.product_repo_cls.return_value.list_public_products = AsyncMock(
                return_value=[(product, variant, 1)]
            )
            self.supply_service_cls.return_value.list_public_reseller_products = AsyncMock(
                return_value=[reseller_product] if include_reseller else []
            )
            return self

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            supply_service_patch.__exit__(exc_type, exc, traceback)
            product_repo_patch.__exit__(exc_type, exc, traceback)
            tenant_repo_patch.__exit__(exc_type, exc, traceback)

    return _PatchContext()


def _callback_data_set(reply_markup: object) -> set[str]:
    return {
        button.callback_data
        for row in getattr(reply_markup, "inline_keyboard", [])
        for button in row
        if getattr(button, "callback_data", None)
    }


if __name__ == "__main__":
    unittest.main()
