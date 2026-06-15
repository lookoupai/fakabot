from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, patch

try:
    from app.bots.middlewares.tenant_user_ban import (
        BANNED_USER_CALLBACK_ALERT,
        BANNED_USER_MESSAGE,
        TenantUserBanMiddleware,
    )
    from aiogram.types import CallbackQuery, Chat, Message, User
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过租户用户封禁中间件测试：{exc.name}") from exc


class TenantUserBanMiddlewareTest(unittest.TestCase):
    def test_master_update_does_not_query_ban_status(self) -> None:
        middleware = TenantUserBanMiddleware()
        handler = AsyncMock(return_value="ok")

        with patch("app.bots.middlewares.tenant_user_ban.TenantRepository") as repo_class:
            result = asyncio.run(middleware(handler, _message(42), {"bot_role": "master"}))

        self.assertEqual("ok", result)
        handler.assert_awaited_once()
        repo_class.assert_not_called()

    def test_tenant_message_without_session_factory_is_passed_through(self) -> None:
        middleware = TenantUserBanMiddleware()
        handler = AsyncMock(return_value="ok")

        result = asyncio.run(middleware(handler, _message(42), {"bot_role": "tenant"}))

        self.assertEqual("ok", result)
        handler.assert_awaited_once()

    def test_tenant_message_without_platform_user_record_is_passed_through(self) -> None:
        middleware = TenantUserBanMiddleware()
        handler = AsyncMock(return_value="ok")
        message = _message(42)

        with patch("app.bots.middlewares.tenant_user_ban.TenantRepository") as repo_class:
            repo_class.return_value.is_platform_user_banned = AsyncMock(return_value=False)
            result = asyncio.run(
                middleware(handler, message, {"bot_role": "tenant", "session_factory": _session_factory()})
            )

        self.assertEqual("ok", result)
        handler.assert_awaited_once()

    def test_tenant_message_banned_user_is_rejected(self) -> None:
        middleware = TenantUserBanMiddleware()
        handler = AsyncMock(return_value="ok")
        message = _message(42)

        with patch("app.bots.middlewares.tenant_user_ban.TenantRepository") as repo_class:
            repo_class.return_value.is_platform_user_banned = AsyncMock(return_value=True)
            with patch.object(Message, "answer", new_callable=AsyncMock) as answer:
                result = asyncio.run(
                    middleware(handler, message, {"bot_role": "tenant", "session_factory": _session_factory()})
                )

        self.assertIsNone(result)
        handler.assert_not_awaited()
        answer.assert_awaited_once_with(BANNED_USER_MESSAGE)

    def test_tenant_callback_banned_user_is_rejected_and_answered(self) -> None:
        middleware = TenantUserBanMiddleware()
        handler = AsyncMock(return_value="ok")
        callback = _callback(42)

        with patch("app.bots.middlewares.tenant_user_ban.TenantRepository") as repo_class:
            repo_class.return_value.is_platform_user_banned = AsyncMock(return_value=True)
            with patch.object(CallbackQuery, "answer", new_callable=AsyncMock) as callback_answer:
                with patch.object(Message, "answer", new_callable=AsyncMock) as message_answer:
                    result = asyncio.run(
                        middleware(handler, callback, {"bot_role": "tenant", "session_factory": _session_factory()})
                    )

        self.assertIsNone(result)
        handler.assert_not_awaited()
        callback_answer.assert_awaited_once_with(BANNED_USER_CALLBACK_ALERT, show_alert=True)
        message_answer.assert_awaited_once_with(BANNED_USER_MESSAGE)

    def test_tenant_event_without_user_is_passed_through(self) -> None:
        middleware = TenantUserBanMiddleware()
        handler = AsyncMock(return_value="ok")
        message = _message(None)

        with patch("app.bots.middlewares.tenant_user_ban.TenantRepository") as repo_class:
            result = asyncio.run(
                middleware(handler, message, {"bot_role": "tenant", "session_factory": _session_factory()})
            )

        self.assertEqual("ok", result)
        handler.assert_awaited_once()
        repo_class.assert_not_called()


def _message(user_id: int | None) -> Message:
    return Message(
        message_id=1,
        date=datetime.now(timezone.utc),
        chat=Chat(id=100, type="private"),
        from_user=None if user_id is None else User(id=user_id, is_bot=False, first_name="User"),
        text="/start",
    )


def _callback(user_id: int) -> CallbackQuery:
    return CallbackQuery(
        id="callback-id",
        from_user=User(id=user_id, is_bot=False, first_name="User"),
        chat_instance="chat-instance",
        message=_message(user_id),
        data="tenant:home",
    )


def _session_factory() -> object:
    def factory() -> _SessionContext:
        return _SessionContext()

    return factory


class _SessionContext:
    async def __aenter__(self) -> "_SessionContext":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
