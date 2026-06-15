from __future__ import annotations

import json
import logging
from types import SimpleNamespace
import unittest
import warnings
from unittest.mock import AsyncMock, patch

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)
logging.getLogger("httpx").setLevel(logging.WARNING)

try:
    from cryptography.fernet import Fernet
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from pydantic import SecretStr

    from app.bots.middlewares.tenant_context import TenantContextMiddleware
    from app.config import Settings
    from app.services.token_crypto import TokenCrypto
    from app.web.health import router as health_router
    from app.web.webhook import create_webhook_router
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过平台运行时 smoke 测试：{exc.name}") from exc


class _FakeRedis:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(values or {})
        self.get_calls: list[str] = []
        self.ping_count = 0

    async def get(self, key: str) -> str | None:
        self.get_calls.append(key)
        return self.values.get(key)

    async def ping(self) -> bool:
        self.ping_count += 1
        return True


class _ReadySession:
    def __init__(self) -> None:
        self.execute_count = 0

    async def __aenter__(self) -> "_ReadySession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    async def execute(self, query: object) -> None:
        self.execute_count += 1


class _TenantRuntimeSession:
    async def __aenter__(self) -> "_TenantRuntimeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class _FakeBot:
    def __init__(self) -> None:
        self.session = SimpleNamespace(close=AsyncMock())


class _MiddlewareDispatcher:
    def __init__(self, session_factory: object) -> None:
        self.session_factory = session_factory
        self.feed_update = AsyncMock(side_effect=self._feed_update)
        self.seen_data: dict[str, object] = {}

    async def _feed_update(self, bot: object, update: object, **workflow_data: object) -> None:
        middleware = TenantContextMiddleware()

        async def handler(event: object, data: dict[str, object]) -> None:
            self.seen_data = dict(data)
            return None

        data = dict(workflow_data)
        data["session_factory"] = self.session_factory
        await middleware(handler, update, data)


def _session_factory(session: object):
    def factory() -> object:
        return session

    return factory


def _client(settings: Settings, redis: _FakeRedis, dispatcher: object) -> TestClient:
    app = FastAPI()
    app.state.redis = redis
    app.state.dispatcher = dispatcher
    app.include_router(health_router)
    app.include_router(create_webhook_router(settings))
    return TestClient(app)


class PlatformRuntimeE2ESmokeTest(unittest.TestCase):
    def test_ready_and_tenant_webhook_inject_runtime_context_without_leaking_token(self) -> None:
        settings = Settings(
            token_encryption_key=SecretStr(Fernet.generate_key().decode()),
            webhook_base_path="/telegram/webhook",
        )
        raw_tenant_token = "123456:tenant-secret-token"
        encrypted_token = TokenCrypto(settings).encrypt_token(raw_tenant_token)
        redis = _FakeRedis(
            {
                "tenant_webhook:tenant-secret": json.dumps(
                    {
                        "tenant_id": 7,
                        "tenant_public_id": "tn_demo",
                        "tenant_bot_id": 12,
                        "owner_user_id": 3,
                        "owner_telegram_user_id": 42,
                        "store_name": "测试店铺",
                        "bot_username": "demo_bot",
                        "encrypted_token": encrypted_token,
                    }
                )
            }
        )
        ready_session = _ReadySession()
        runtime_session = _TenantRuntimeSession()
        dispatcher = _MiddlewareDispatcher(_session_factory(runtime_session))
        client = _client(settings, redis, dispatcher)
        fake_bot = _FakeBot()
        tenant_bot = SimpleNamespace(
            id=12,
            tenant_id=7,
            bot_username="demo_bot",
            encrypted_token=encrypted_token,
            tenant=SimpleNamespace(
                public_id="tn_demo",
                owner_user_id=3,
                store_name="测试店铺",
                owner=SimpleNamespace(telegram_user_id=42),
            ),
        )
        tenant = SimpleNamespace(self_sale_enabled=True, supplier_enabled=True, reseller_enabled=False)
        tenant_settings = {
            "welcome": {"text": "欢迎光临"},
            "feature_flags": {"reseller": True},
        }

        with patch("app.web.health.get_session_factory", return_value=_session_factory(ready_session)):
            health_response = client.get("/health")
            ready_response = client.get("/ready")

        with patch("app.web.webhook.create_bot", return_value=fake_bot) as create_bot:
            with patch("app.web.webhook.get_session_factory", return_value=_session_factory(runtime_session)):
                with patch("app.web.webhook.TenantRepository") as webhook_repo_class:
                    webhook_repo = webhook_repo_class.return_value
                    webhook_repo.get_active_bot_by_secret = AsyncMock(return_value=tenant_bot)
                    with patch("app.bots.middlewares.tenant_context.TenantRepository") as repo_class:
                        repo = repo_class.return_value
                        repo.get_tenant = AsyncMock(return_value=tenant)
                        repo.get_settings = AsyncMock(return_value=tenant_settings)
                        webhook_response = client.post(
                            "/telegram/webhook/tenant-secret",
                            json={"update_id": 1001},
                        )

        self.assertEqual(200, health_response.status_code)
        self.assertEqual({"status": "ok"}, health_response.json())
        self.assertEqual(200, ready_response.status_code)
        self.assertEqual({"status": "ok"}, ready_response.json())
        self.assertEqual(1, ready_session.execute_count)
        self.assertEqual(1, redis.ping_count)

        self.assertEqual(200, webhook_response.status_code)
        self.assertEqual({"ok": True}, webhook_response.json())
        create_bot.assert_called_once_with(raw_tenant_token)
        self.assertNotIn(raw_tenant_token, webhook_response.text)
        self.assertNotIn(encrypted_token, webhook_response.text)
        self.assertEqual(["tenant_webhook:tenant-secret"], redis.get_calls)
        webhook_repo.get_active_bot_by_secret.assert_awaited_once()
        self.assertEqual(1, dispatcher.feed_update.await_count)
        self.assertEqual(1, fake_bot.session.close.await_count)
        self.assertEqual("tenant", dispatcher.seen_data["bot_role"])
        tenant_context = dispatcher.seen_data["tenant_context"]
        self.assertEqual(7, tenant_context.tenant_id)
        self.assertEqual("tn_demo", tenant_context.tenant_public_id)
        self.assertEqual(12, tenant_context.tenant_bot_id)
        self.assertEqual(42, tenant_context.owner_telegram_user_id)
        self.assertEqual(tenant_settings, dispatcher.seen_data["tenant_settings"])
        self.assertEqual(
            {"self_sale": True, "supplier": True, "reseller": True},
            dispatcher.seen_data["tenant_feature_flags"],
        )
        repo.get_tenant.assert_awaited_once_with(runtime_session, 7)
        repo.get_settings.assert_awaited_once_with(runtime_session, 7)


if __name__ == "__main__":
    unittest.main()
