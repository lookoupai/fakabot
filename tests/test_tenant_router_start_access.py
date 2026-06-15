from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

try:
    from app.bots.context import TenantContext
    from app.bots.routers.tenant import callback_home, callback_manage, manage_menu, tenant_start
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过租户 Bot 首页和访问控制测试：{exc.name}") from exc


class _FakeSession:
    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


def _session_factory() -> _FakeSession:
    return _FakeSession()


def _tenant_context() -> TenantContext:
    return TenantContext(
        tenant_id=7,
        tenant_public_id="tn_demo",
        tenant_bot_id=12,
        owner_user_id=3,
        owner_telegram_user_id=42,
        store_name="缓存店铺",
        bot_username="demo_bot",
    )


def _message(*, telegram_user_id: int = 99, chat_type: str = "private") -> SimpleNamespace:
    return SimpleNamespace(
        from_user=SimpleNamespace(id=telegram_user_id),
        chat=SimpleNamespace(type=chat_type),
        answer=AsyncMock(),
    )


def _callback(*, telegram_user_id: int = 99, chat_type: str = "private") -> SimpleNamespace:
    return SimpleNamespace(
        from_user=SimpleNamespace(id=telegram_user_id),
        message=_message(telegram_user_id=telegram_user_id, chat_type=chat_type),
        answer=AsyncMock(),
    )


class TenantRouterStartAccessTest(unittest.TestCase):
    def test_start_without_tenant_context_returns_unavailable_without_repo_lookup(self) -> None:
        message = _message(telegram_user_id=99)

        with patch("app.bots.routers.tenant.TenantRepository") as repo_class:
            asyncio.run(tenant_start(message, _session_factory, None))

        message.answer.assert_awaited_once_with("店铺暂不可用，请稍后再试。")
        repo_class.assert_not_called()

    def test_home_callback_without_tenant_context_acknowledges_and_does_not_render(self) -> None:
        callback = _callback(telegram_user_id=99)

        with patch("app.bots.routers.tenant.TenantRepository") as repo_class:
            asyncio.run(callback_home(callback, _session_factory, None))

        callback.answer.assert_awaited_once()
        callback.message.answer.assert_not_awaited()
        repo_class.assert_not_called()

    def test_start_empty_store_uses_tenant_context_and_hides_manage_for_buyer(self) -> None:
        message = _message(telegram_user_id=99)

        with patch("app.bots.routers.tenant.TenantRepository") as repo_class:
            repo = repo_class.return_value
            repo.get_tenant = AsyncMock(return_value=None)
            repo.get_settings = AsyncMock(return_value={})
            repo.can_manage_settings = AsyncMock(return_value=False)

            asyncio.run(tenant_start(message, _session_factory, _tenant_context()))

        text = message.answer.await_args.args[0]
        reply_markup = message.answer.await_args.kwargs["reply_markup"]

        self.assertIn("缓存店铺", text)
        self.assertIn("欢迎光临，本店铺正在配置中。", text)
        self.assertEqual(
            {"tenant:products", "tenant:orders", "tenant:support"},
            _callback_data_set(reply_markup),
        )
        repo.get_tenant.assert_awaited_once()
        repo.get_settings.assert_awaited_once()
        repo.can_manage_settings.assert_awaited_once()

    def test_start_shows_manage_button_for_authorized_manager(self) -> None:
        message = _message(telegram_user_id=42)

        with patch("app.bots.routers.tenant.TenantRepository") as repo_class:
            repo = repo_class.return_value
            repo.get_tenant = AsyncMock(return_value=SimpleNamespace(store_name="数据库店铺"))
            repo.get_settings = AsyncMock(return_value={"welcome": {"text": "欢迎回来"}})
            repo.can_manage_settings = AsyncMock(return_value=True)

            asyncio.run(tenant_start(message, _session_factory, _tenant_context()))

        text = message.answer.await_args.args[0]
        reply_markup = message.answer.await_args.kwargs["reply_markup"]

        self.assertIn("数据库店铺", text)
        self.assertIn("欢迎回来", text)
        self.assertIn("tenant:manage", _callback_data_set(reply_markup))

    def test_manage_command_rejects_non_manager_without_rendering_menu(self) -> None:
        message = _message(telegram_user_id=99)

        with patch("app.bots.routers.tenant.TenantRepository") as repo_class:
            repo = repo_class.return_value
            repo.can_manage_settings = AsyncMock(return_value=False)

            asyncio.run(manage_menu(message, _session_factory, _tenant_context()))

        message.answer.assert_awaited_once_with("无权限。只有租户 owner 或 admin 可以管理店铺。")
        repo.can_manage_settings.assert_awaited_once()

    def test_manage_callback_rejects_non_manager_after_acknowledging_callback(self) -> None:
        callback = _callback(telegram_user_id=99)

        with patch("app.bots.routers.tenant.TenantRepository") as repo_class:
            repo = repo_class.return_value
            repo.can_manage_settings = AsyncMock(return_value=False)

            asyncio.run(callback_manage(callback, _session_factory, _tenant_context()))

        callback.answer.assert_awaited_once()
        callback.message.answer.assert_awaited_once_with("无权限。只有租户 owner 或 admin 可以管理店铺。")
        repo.can_manage_settings.assert_awaited_once()


def _callback_data_set(reply_markup: object) -> set[str]:
    return {
        button.callback_data
        for row in getattr(reply_markup, "inline_keyboard", [])
        for button in row
        if getattr(button, "callback_data", None)
    }


if __name__ == "__main__":
    unittest.main()
