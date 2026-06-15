from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repos.tenants import TenantRepository

BANNED_USER_MESSAGE = "账号已被平台限制，暂时无法使用店铺功能。"
BANNED_USER_CALLBACK_ALERT = "账号已被平台限制。"


class TenantUserBanMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if data.get("bot_role") != "tenant":
            return await handler(event, data)

        session_factory = data.get("session_factory")
        if session_factory is None:
            return await handler(event, data)

        telegram_user_id = _event_telegram_user_id(event)
        if telegram_user_id <= 0:
            return await handler(event, data)

        if not await _is_banned(session_factory, telegram_user_id):
            return await handler(event, data)

        await _answer_banned(event)
        return None


async def _is_banned(
    session_factory: async_sessionmaker[AsyncSession],
    telegram_user_id: int,
) -> bool:
    repo = TenantRepository()
    async with session_factory() as session:
        return await repo.is_platform_user_banned(session, telegram_user_id)


def _event_telegram_user_id(event: TelegramObject) -> int:
    if isinstance(event, Message):
        return event.from_user.id if event.from_user is not None else 0
    if isinstance(event, CallbackQuery):
        return event.from_user.id
    return 0


async def _answer_banned(event: TelegramObject) -> None:
    if isinstance(event, CallbackQuery):
        await event.answer(BANNED_USER_CALLBACK_ALERT, show_alert=True)
        if event.message is not None:
            await event.message.answer(BANNED_USER_MESSAGE)
        return
    if isinstance(event, Message):
        await event.answer(BANNED_USER_MESSAGE)
