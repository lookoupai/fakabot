from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

try:
    from app.bots.context import TenantContext
    from app.bots.middlewares.tenant_context import (
        TenantContextMiddleware,
        build_tenant_feature_flags,
    )
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过租户上下文中间件测试：{exc.name}") from exc


class _FakeSession:
    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


def _fake_session_factory() -> _FakeSession:
    return _FakeSession()


class TenantContextMiddlewareTest(unittest.TestCase):
    def test_master_update_keeps_default_context_without_loading_tenant_data(self) -> None:
        middleware = TenantContextMiddleware()
        seen_data: dict[str, object] = {}

        async def handler(event: object, data: dict[str, object]) -> str:
            seen_data.update(data)
            return "ok"

        with patch("app.bots.middlewares.tenant_context.TenantRepository") as repo:
            result = asyncio.run(middleware(handler, SimpleNamespace(), {"bot_role": "master"}))

        self.assertEqual("ok", result)
        self.assertEqual("master", seen_data["bot_role"])
        self.assertIsNone(seen_data["tenant_context"])
        self.assertNotIn("tenant_settings", seen_data)
        repo.assert_not_called()

    def test_tenant_update_injects_settings_and_feature_flags(self) -> None:
        middleware = TenantContextMiddleware()
        tenant_context = TenantContext(
            tenant_id=7,
            tenant_public_id="tn_demo",
            tenant_bot_id=12,
            owner_user_id=3,
            owner_telegram_user_id=42,
            store_name="测试店铺",
            bot_username="demo_bot",
        )
        tenant = SimpleNamespace(
            self_sale_enabled=False,
            supplier_enabled=True,
            reseller_enabled=False,
        )
        tenant_settings = {
            "welcome": {"text": "欢迎"},
            "feature_flags": {"reseller": True},
        }
        seen_data: dict[str, object] = {}

        async def handler(event: object, data: dict[str, object]) -> str:
            seen_data.update(data)
            return "ok"

        with patch("app.bots.middlewares.tenant_context.TenantRepository") as repo_class:
            repo = repo_class.return_value
            repo.get_tenant = AsyncMock(return_value=tenant)
            repo.get_settings = AsyncMock(return_value=tenant_settings)

            result = asyncio.run(
                middleware(
                    handler,
                    SimpleNamespace(),
                    {
                        "bot_role": "tenant",
                        "tenant_context": tenant_context,
                        "session_factory": _fake_session_factory,
                    },
                )
            )

        self.assertEqual("ok", result)
        self.assertEqual(tenant_settings, seen_data["tenant_settings"])
        self.assertEqual(
            {"self_sale": False, "supplier": True, "reseller": True},
            seen_data["tenant_feature_flags"],
        )
        self.assertEqual(1, repo.get_tenant.await_count)
        self.assertEqual(1, repo.get_settings.await_count)

    def test_tenant_update_without_session_factory_does_not_load_tenant_data(self) -> None:
        middleware = TenantContextMiddleware()
        tenant_context = TenantContext(
            tenant_id=7,
            tenant_public_id="tn_demo",
            tenant_bot_id=12,
            owner_user_id=3,
            owner_telegram_user_id=42,
            store_name="测试店铺",
            bot_username="demo_bot",
        )
        seen_data: dict[str, object] = {}

        async def handler(event: object, data: dict[str, object]) -> str:
            seen_data.update(data)
            return "ok"

        with patch("app.bots.middlewares.tenant_context.TenantRepository") as repo:
            result = asyncio.run(
                middleware(
                    handler,
                    SimpleNamespace(),
                    {"bot_role": "tenant", "tenant_context": tenant_context},
                )
            )

        self.assertEqual("ok", result)
        self.assertNotIn("tenant_settings", seen_data)
        self.assertNotIn("tenant_feature_flags", seen_data)
        repo.assert_not_called()

    def test_feature_flags_fall_back_to_defaults_without_tenant_or_settings(self) -> None:
        self.assertEqual(
            {"self_sale": True, "supplier": False, "reseller": False},
            build_tenant_feature_flags(None, {}),
        )


if __name__ == "__main__":
    unittest.main()
