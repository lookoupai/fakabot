from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

try:
    from app.bots.context import TenantContext
    from app.bots.routers.tenant import admin_web_code
    from app.config import Settings
    from app.services.admin_web import AdminWebBindingCodeError
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过租户 Bot Web 绑定码测试：{exc.name}") from exc


class _FakeSession:
    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


def _session_factory() -> _FakeSession:
    return _FakeSession()


def _tenant_context(*, tenant_public_id: str = "tn_demo") -> TenantContext:
    return TenantContext(
        tenant_id=7,
        tenant_public_id=tenant_public_id,
        tenant_bot_id=12,
        owner_user_id=3,
        owner_telegram_user_id=42,
        store_name="演示店铺",
        bot_username="demo_bot",
    )


def _message(*, telegram_user_id: int = 42, chat_type: str = "private") -> SimpleNamespace:
    return SimpleNamespace(
        from_user=SimpleNamespace(id=telegram_user_id),
        chat=SimpleNamespace(type=chat_type),
        answer=AsyncMock(),
    )


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expires: dict[str, int] = {}

    async def set(self, key: str, value: str, *, ex: int, nx: bool = False) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.expires[key] = ex
        return True


class TenantAdminWebCodeCommandTest(unittest.TestCase):
    def test_owner_can_generate_binding_code_for_current_clone_bot(self) -> None:
        message = _message(telegram_user_id=42)
        redis = _FakeRedis()

        with patch("app.bots.routers.tenant.TenantRepository") as repo_class:
            repo_class.return_value.can_manage_settings = AsyncMock(return_value=True)
            asyncio.run(
                admin_web_code(
                    message=message,
                    settings=Settings(token_encryption_key="test-session-secret"),
                    session_factory=_session_factory,
                    tenant_context=_tenant_context(),
                    redis_client=redis,
                )
            )

        repo_class.return_value.can_manage_settings.assert_awaited_once()
        self.assertEqual(1, len(redis.values))
        payload = next(iter(redis.values.values()))
        self.assertIn('"current_workspace_id":"tn_demo"', payload)
        self.assertIn('"telegram_user_id":42', payload)
        reply = message.answer.await_args.args[0]
        self.assertIn("网页管理后台一次性绑定码", reply)
        self.assertIn("工作区：演示店铺", reply)
        self.assertIn("Bot：@demo_bot", reply)
        self.assertIn("有效期：300 秒", reply)
        self.assertNotIn("tenant_id", reply.lower())
        self.assertNotIn("test-session-secret", reply)

    def test_admin_can_generate_binding_code_for_current_clone_bot(self) -> None:
        message = _message(telegram_user_id=88)
        redis = _FakeRedis()

        with patch("app.bots.routers.tenant.TenantRepository") as repo_class:
            repo_class.return_value.can_manage_settings = AsyncMock(return_value=True)
            asyncio.run(
                admin_web_code(
                    message=message,
                    settings=Settings(token_encryption_key="test-session-secret"),
                    session_factory=_session_factory,
                    tenant_context=_tenant_context(),
                    redis_client=redis,
                )
            )

        payload = next(iter(redis.values.values()))
        self.assertIn('"telegram_user_id":88', payload)
        self.assertIn('"current_workspace_id":"tn_demo"', payload)
        self.assertIn("绑定码：<code>", message.answer.await_args.args[0])

    def test_non_manager_is_rejected_without_issuing_code(self) -> None:
        message = _message(telegram_user_id=99)
        redis = _FakeRedis()

        with patch("app.bots.routers.tenant.TenantRepository") as repo_class:
            repo_class.return_value.can_manage_settings = AsyncMock(return_value=False)
            asyncio.run(
                admin_web_code(
                    message=message,
                    settings=Settings(token_encryption_key="test-session-secret"),
                    session_factory=_session_factory,
                    tenant_context=_tenant_context(),
                    redis_client=redis,
                )
            )

        message.answer.assert_awaited_once_with("无权限。只有租户 owner 或 admin 可以管理店铺。")
        self.assertEqual({}, redis.values)

    def test_group_chat_is_rejected_before_permission_lookup_or_code_issue(self) -> None:
        message = _message(telegram_user_id=42, chat_type="group")
        redis = _FakeRedis()

        with patch("app.bots.routers.tenant.TenantRepository") as repo_class:
            asyncio.run(
                admin_web_code(
                    message=message,
                    settings=Settings(token_encryption_key="test-session-secret"),
                    session_factory=_session_factory,
                    tenant_context=_tenant_context(),
                    redis_client=redis,
                )
            )

        message.answer.assert_awaited_once_with("管理功能请在私聊中使用。")
        repo_class.assert_not_called()
        self.assertEqual({}, redis.values)

    def test_missing_redis_is_rejected_after_permission_check(self) -> None:
        message = _message(telegram_user_id=42)

        with patch("app.bots.routers.tenant.TenantRepository") as repo_class:
            repo_class.return_value.can_manage_settings = AsyncMock(return_value=True)
            asyncio.run(
                admin_web_code(
                    message=message,
                    settings=Settings(token_encryption_key="test-session-secret"),
                    session_factory=_session_factory,
                    tenant_context=_tenant_context(),
                    redis_client=None,
                )
            )

        message.answer.assert_awaited_once_with("绑定码服务暂不可用，请稍后再试。")

    def test_binding_code_store_error_is_reported_without_sensitive_details(self) -> None:
        message = _message(telegram_user_id=42)
        redis = _FakeRedis()

        with patch("app.bots.routers.tenant.TenantRepository") as repo_class:
            repo_class.return_value.can_manage_settings = AsyncMock(return_value=True)
            with patch(
                "app.bots.routers.tenant.AdminWebBindingCodeStore.issue_code",
                new=AsyncMock(side_effect=AdminWebBindingCodeError("绑定码服务密钥未配置")),
            ):
                asyncio.run(
                    admin_web_code(
                        message=message,
                        settings=Settings(),
                        session_factory=_session_factory,
                        tenant_context=_tenant_context(),
                        redis_client=redis,
                    )
                )

        message.answer.assert_awaited_once_with("绑定码服务密钥未配置")
        self.assertEqual({}, redis.values)


if __name__ == "__main__":
    unittest.main()
