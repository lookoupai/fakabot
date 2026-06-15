from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

try:
    from app.bots.context import TenantContext
    from app.bots.routers.tenant import _load_profile
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过租户 Bot profile 测试：{exc.name}") from exc


class _FakeSession:
    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


def _fake_session_factory() -> _FakeSession:
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


class TenantRouterProfileTest(unittest.TestCase):
    def test_load_profile_uses_injected_settings_without_requerying_settings(self) -> None:
        injected_settings = {"welcome": {"text": "来自中间件"}}

        with patch("app.bots.routers.tenant.TenantRepository") as repo_class:
            repo = repo_class.return_value
            repo.get_tenant = AsyncMock(return_value=SimpleNamespace(store_name="数据库店铺"))
            repo.get_settings = AsyncMock(side_effect=AssertionError("不应重复查询租户设置"))

            store_name, settings = asyncio.run(
                _load_profile(_fake_session_factory, _tenant_context(), injected_settings)
            )

        self.assertEqual("数据库店铺", store_name)
        self.assertEqual(injected_settings, settings)
        self.assertEqual(1, repo.get_tenant.await_count)
        repo.get_settings.assert_not_called()

    def test_load_profile_falls_back_to_context_store_name_when_tenant_missing(self) -> None:
        with patch("app.bots.routers.tenant.TenantRepository") as repo_class:
            repo = repo_class.return_value
            repo.get_tenant = AsyncMock(return_value=None)
            repo.get_settings = AsyncMock(return_value={"welcome": {"text": "默认欢迎"}})

            store_name, settings = asyncio.run(_load_profile(_fake_session_factory, _tenant_context()))

        self.assertEqual("缓存店铺", store_name)
        self.assertEqual({"welcome": {"text": "默认欢迎"}}, settings)


if __name__ == "__main__":
    unittest.main()
