from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, patch

try:
    from app.bots.routers.master import _parse_platform_user_risk_args, ban_user, unban_user
    from app.config import Settings
    from app.services.risk import RiskActionResult
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过母 Bot 风控命令测试：{exc.name}") from exc


class MasterRiskCommandTest(unittest.TestCase):
    def test_parse_platform_user_risk_args_accepts_reason(self) -> None:
        telegram_user_id, reason = _parse_platform_user_risk_args("123456 | 风控命中", "ban_user")

        self.assertEqual(123456, telegram_user_id)
        self.assertEqual("风控命中", reason)

    def test_parse_platform_user_risk_args_accepts_empty_reason(self) -> None:
        telegram_user_id, reason = _parse_platform_user_risk_args("123456", "unban_user")

        self.assertEqual(123456, telegram_user_id)
        self.assertIsNone(reason)

    def test_parse_platform_user_risk_args_rejects_invalid_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "请提供 Telegram 用户 ID"):
            _parse_platform_user_risk_args("", "ban_user")
        with self.assertRaisesRegex(ValueError, "Telegram 用户 ID 必须是数字"):
            _parse_platform_user_risk_args("abc", "ban_user")
        with self.assertRaisesRegex(ValueError, "Telegram 用户 ID 必须大于 0"):
            _parse_platform_user_risk_args("0", "ban_user")
        with self.assertRaisesRegex(ValueError, "原因不能超过 500 个字符"):
            _parse_platform_user_risk_args(f"123456 | {'x' * 501}", "ban_user")

    def test_ban_user_requires_platform_admin(self) -> None:
        message = _message(user_id=456)
        settings = Settings(platform_admin_ids={123})
        run_action = AsyncMock()

        with patch("app.bots.routers.master._run_risk_action", run_action):
            asyncio.run(ban_user(message, SimpleNamespace(args="123456 | bad"), settings, object()))

        message.answer.assert_awaited_once_with("无权限。只有平台管理员可以封禁平台用户。")
        run_action.assert_not_awaited()

    def test_ban_user_runs_risk_action(self) -> None:
        message = _message(user_id=123)
        settings = Settings(platform_admin_ids={123})
        result = RiskActionResult(
            target_type="platform_user",
            target_id=7,
            tenant_id=None,
            previous_status="active",
            new_status="banned",
            reason="风控命中",
        )
        run_action = AsyncMock(return_value=result)

        with patch("app.bots.routers.master._run_risk_action", run_action):
            asyncio.run(ban_user(message, SimpleNamespace(args="123456 | 风控命中"), settings, object()))

        run_action.assert_awaited_once_with(
            message=message,
            settings=settings,
            session_factory=ANY,
            action_name="ban_platform_user",
            target_id=123456,
            reason="风控命中",
        )
        answer = message.answer.await_args.args[0]
        self.assertIn("平台用户已封禁", answer)
        self.assertIn("目标：platform_user #7", answer)
        self.assertIn("租户 ID：-", answer)

    def test_unban_user_runs_risk_action(self) -> None:
        message = _message(user_id=123)
        settings = Settings(platform_admin_ids={123})
        result = RiskActionResult(
            target_type="platform_user",
            target_id=7,
            tenant_id=None,
            previous_status="banned",
            new_status="active",
            reason="误封恢复",
        )
        run_action = AsyncMock(return_value=result)

        with patch("app.bots.routers.master._run_risk_action", run_action):
            asyncio.run(unban_user(message, SimpleNamespace(args="123456 | 误封恢复"), settings, object()))

        run_action.assert_awaited_once_with(
            message=message,
            settings=settings,
            session_factory=ANY,
            action_name="unban_platform_user",
            target_id=123456,
            reason="误封恢复",
        )
        answer = message.answer.await_args.args[0]
        self.assertIn("平台用户已解封", answer)
        self.assertIn("状态：banned → active", answer)


def _message(user_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        from_user=SimpleNamespace(id=user_id, username="admin", first_name="Admin", language_code="zh"),
        answer=AsyncMock(),
    )


if __name__ == "__main__":
    unittest.main()
