from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

try:
    from app.bots.routers.tenant import (
        _ensure_can_manage_callback,
        _ensure_owner_message,
        _ensure_permission_message,
    )
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过租户管理私聊边界测试：{exc.name}") from exc


class TenantAdminPrivateBoundaryTest(unittest.TestCase):
    def test_permission_message_rejects_group_before_permission_lookup(self) -> None:
        message = _message(chat_type="group")

        with patch("app.bots.routers.tenant._has_permission", AsyncMock(side_effect=AssertionError("不应查询权限"))):
            allowed = asyncio.run(
                _ensure_permission_message(
                    message,
                    _session_factory,
                    SimpleNamespace(tenant_id=7),
                    "products",
                )
            )

        self.assertFalse(allowed)
        message.answer.assert_awaited_once_with("管理功能请在私聊中使用。")

    def test_owner_message_allows_private_permission_lookup(self) -> None:
        message = _message(chat_type="private")

        with patch("app.bots.routers.tenant._is_owner", AsyncMock(return_value=True)) as is_owner:
            allowed = asyncio.run(
                _ensure_owner_message(
                    message,
                    _session_factory,
                    SimpleNamespace(tenant_id=7),
                )
            )

        self.assertTrue(allowed)
        is_owner.assert_awaited_once()
        message.answer.assert_not_awaited()

    def test_manage_callback_rejects_group_before_permission_lookup(self) -> None:
        callback = SimpleNamespace(
            from_user=SimpleNamespace(id=123),
            message=_message(chat_type="supergroup"),
        )

        with patch("app.bots.routers.tenant._can_manage", AsyncMock(side_effect=AssertionError("不应查询权限"))):
            allowed = asyncio.run(
                _ensure_can_manage_callback(
                    callback,
                    _session_factory,
                    SimpleNamespace(tenant_id=7),
                )
            )

        self.assertFalse(allowed)
        callback.message.answer.assert_awaited_once_with("管理功能请在私聊中使用。")


def _message(*, chat_type: str) -> SimpleNamespace:
    return SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        chat=SimpleNamespace(type=chat_type),
        answer=AsyncMock(),
    )


def _session_factory() -> object:
    raise AssertionError("不应打开数据库会话")


if __name__ == "__main__":
    unittest.main()
