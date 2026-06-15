from __future__ import annotations

from typing import Any, Optional

from aiogram.filters import Filter


class BotRoleFilter(Filter):
    def __init__(self, role: str) -> None:
        self._role = role

    async def __call__(self, event: Any, bot_role: Optional[str] = None) -> bool:
        return bot_role == self._role
