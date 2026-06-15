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

    from app.config import Settings
    from app.services.token_crypto import TokenCrypto
    from app.web.webhook import create_webhook_router, _resolve_tenant_context
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过 Webhook 运行时测试：{exc.name}") from exc


class _FakeRedis:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(values or {})
        self.get_calls: list[str] = []
        self.set_calls: list[tuple[str, str, int | None]] = []
        self.deleted: list[str] = []

    async def get(self, key: str) -> str | None:
        self.get_calls.append(key)
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.set_calls.append((key, value, ex))
        self.values[key] = value

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.values.pop(key, None)


class _FakeBot:
    def __init__(self) -> None:
        self.session = SimpleNamespace(close=AsyncMock())


class _FakeSession:
    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


def _fake_session_factory() -> _FakeSession:
    return _FakeSession()


def _client(
    settings: Settings,
    redis: _FakeRedis,
    dispatcher: object,
    *,
    raise_server_exceptions: bool = True,
) -> TestClient:
    app = FastAPI()
    app.state.dispatcher = dispatcher
    app.state.redis = redis
    app.include_router(create_webhook_router(settings))
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


class WebhookRuntimeTest(unittest.TestCase):
    def test_dispatcher_missing_returns_503_without_creating_bot(self) -> None:
        settings = Settings(master_bot_token=SecretStr("123456:master"), master_webhook_secret="master")
        redis = _FakeRedis()

        with patch("app.web.webhook.create_bot") as create_bot:
            response = _client(settings, redis, None).post(
                "/telegram/webhook/master",
                json={"update_id": 1},
            )

        self.assertEqual(503, response.status_code)
        self.assertEqual({"detail": "应用尚未完成初始化"}, response.json())
        create_bot.assert_not_called()
        self.assertEqual([], redis.get_calls)

    def test_master_secret_without_token_returns_503_without_creating_bot(self) -> None:
        settings = Settings(master_webhook_secret="master")
        redis = _FakeRedis()
        dispatcher = SimpleNamespace(feed_update=AsyncMock())

        with patch("app.web.webhook.create_bot") as create_bot:
            response = _client(settings, redis, dispatcher).post(
                "/telegram/webhook/master",
                json={"update_id": 1},
            )

        self.assertEqual(503, response.status_code)
        self.assertEqual({"detail": "MASTER_BOT_TOKEN 未配置"}, response.json())
        create_bot.assert_not_called()
        self.assertEqual([], redis.get_calls)
        self.assertEqual(0, dispatcher.feed_update.await_count)

    def test_master_secret_dispatches_master_role_without_redis_lookup(self) -> None:
        settings = Settings(master_bot_token=SecretStr("123456:master"), master_webhook_secret="master")
        redis = _FakeRedis()
        dispatcher = SimpleNamespace(feed_update=AsyncMock())
        bot = _FakeBot()

        with patch("app.web.webhook.create_bot", return_value=bot) as create_bot:
            response = _client(settings, redis, dispatcher).post(
                "/telegram/webhook/master",
                json={"update_id": 1},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual({"ok": True}, response.json())
        create_bot.assert_called_once_with("123456:master")
        self.assertEqual([], redis.get_calls)
        self.assertEqual(1, dispatcher.feed_update.await_count)
        self.assertEqual({"bot_role": "master", "redis_client": redis}, dispatcher.feed_update.await_args.kwargs)
        self.assertEqual(1, bot.session.close.await_count)

    def test_unknown_tenant_secret_returns_404_without_creating_bot_or_leaking_secret(self) -> None:
        settings = Settings()
        redis = _FakeRedis()
        dispatcher = SimpleNamespace(feed_update=AsyncMock())

        with patch("app.web.webhook.create_bot") as create_bot:
            with patch("app.web.webhook.get_session_factory", return_value=_fake_session_factory):
                with patch("app.web.webhook.TenantRepository") as repo_class:
                    repo = repo_class.return_value
                    repo.get_active_bot_by_secret = AsyncMock(return_value=None)
                    response = _client(settings, redis, dispatcher).post(
                        "/telegram/webhook/unknown-secret",
                        json={"update_id": 2},
                    )

        self.assertEqual(404, response.status_code)
        self.assertEqual({"detail": "未知 Webhook"}, response.json())
        self.assertNotIn("unknown-secret", response.text)
        create_bot.assert_not_called()
        repo.get_active_bot_by_secret.assert_awaited_once()
        self.assertEqual(["tenant_webhook:unknown-secret"], redis.get_calls)
        self.assertEqual([], redis.set_calls)
        self.assertEqual(0, dispatcher.feed_update.await_count)

    def test_tenant_secret_uses_redis_cache_and_dispatches_tenant_context(self) -> None:
        settings = Settings(token_encryption_key=SecretStr(Fernet.generate_key().decode()))
        encrypted_token = TokenCrypto(settings).encrypt_token("123456:tenant")
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
        dispatcher = SimpleNamespace(feed_update=AsyncMock())
        bot = _FakeBot()
        tenant_bot = _tenant_bot(
            tenant_bot_id=12,
            tenant_id=7,
            bot_username="demo_bot",
            encrypted_token=encrypted_token,
            owner_user_id=3,
            owner_telegram_user_id=42,
            store_name="测试店铺",
        )

        with patch("app.web.webhook.create_bot", return_value=bot) as create_bot:
            with patch("app.web.webhook.get_session_factory", return_value=_fake_session_factory):
                with patch("app.web.webhook.TenantRepository") as repo_class:
                    repo = repo_class.return_value
                    repo.get_active_bot_by_secret = AsyncMock(return_value=tenant_bot)
                    response = _client(settings, redis, dispatcher).post(
                        "/telegram/webhook/tenant-secret",
                        json={"update_id": 2},
                    )

        self.assertEqual(200, response.status_code)
        create_bot.assert_called_once_with("123456:tenant")
        repo.get_active_bot_by_secret.assert_awaited_once()
        self.assertEqual(["tenant_webhook:tenant-secret"], redis.get_calls)
        self.assertEqual([], redis.set_calls)
        kwargs = dispatcher.feed_update.await_args.kwargs
        self.assertEqual("tenant", kwargs["bot_role"])
        self.assertIs(redis, kwargs["redis_client"])
        self.assertEqual(7, kwargs["tenant_context"].tenant_id)
        self.assertEqual("tn_demo", kwargs["tenant_context"].tenant_public_id)
        self.assertEqual(12, kwargs["tenant_context"].tenant_bot_id)
        self.assertEqual(42, kwargs["tenant_context"].owner_telegram_user_id)
        self.assertEqual(1, bot.session.close.await_count)

    def test_stale_cached_tenant_secret_is_deleted_and_not_dispatched_when_db_no_longer_active(self) -> None:
        settings = Settings(token_encryption_key=SecretStr(Fernet.generate_key().decode()))
        encrypted_token = TokenCrypto(settings).encrypt_token("123456:stale")
        redis = _FakeRedis(
            {
                "tenant_webhook:stale-secret": json.dumps(
                    {
                        "tenant_id": 7,
                        "tenant_public_id": "tn_demo",
                        "tenant_bot_id": 12,
                        "owner_user_id": 3,
                        "owner_telegram_user_id": 42,
                        "store_name": "残留缓存店铺",
                        "bot_username": "stale_bot",
                        "encrypted_token": encrypted_token,
                    }
                )
            }
        )
        dispatcher = SimpleNamespace(feed_update=AsyncMock())

        with patch("app.web.webhook.create_bot") as create_bot:
            with patch("app.web.webhook.get_session_factory", return_value=_fake_session_factory):
                with patch("app.web.webhook.TenantRepository") as repo_class:
                    repo = repo_class.return_value
                    repo.get_active_bot_by_secret = AsyncMock(return_value=None)
                    response = _client(settings, redis, dispatcher).post(
                        "/telegram/webhook/stale-secret",
                        json={"update_id": 20},
                    )

        self.assertEqual(404, response.status_code)
        self.assertEqual({"detail": "未知 Webhook"}, response.json())
        self.assertNotIn("stale-secret", response.text)
        self.assertNotIn(encrypted_token, response.text)
        create_bot.assert_not_called()
        repo.get_active_bot_by_secret.assert_awaited_once()
        self.assertEqual(["tenant_webhook:stale-secret"], redis.get_calls)
        self.assertEqual(["tenant_webhook:stale-secret"], redis.deleted)
        self.assertEqual(0, dispatcher.feed_update.await_count)

    def test_tenant_secret_redis_miss_loads_db_recaches_and_dispatches_without_leaking_token(self) -> None:
        settings = Settings(token_encryption_key=SecretStr(Fernet.generate_key().decode()))
        raw_token = "123456:tenant-db-token"
        encrypted_token = TokenCrypto(settings).encrypt_token(raw_token)
        redis = _FakeRedis()
        dispatcher = SimpleNamespace(feed_update=AsyncMock())
        bot = _FakeBot()
        tenant_bot = _tenant_bot(
            tenant_bot_id=21,
            tenant_id=34,
            bot_username="db_bot",
            encrypted_token=encrypted_token,
            owner_user_id=55,
            owner_telegram_user_id=89,
            store_name="DB 店铺",
        )

        with patch("app.web.webhook.create_bot", return_value=bot) as create_bot:
            with patch("app.web.webhook.get_session_factory", return_value=_fake_session_factory):
                with patch("app.web.webhook.TenantRepository") as repo_class:
                    repo = repo_class.return_value
                    repo.get_active_bot_by_secret = AsyncMock(return_value=tenant_bot)
                    response = _client(settings, redis, dispatcher).post(
                        "/telegram/webhook/db-secret",
                        json={"update_id": 3},
                    )

        self.assertEqual(200, response.status_code)
        self.assertEqual({"ok": True}, response.json())
        self.assertNotIn(raw_token, response.text)
        self.assertNotIn(encrypted_token, response.text)
        self.assertNotIn("db-secret", response.text)
        create_bot.assert_called_once_with(raw_token)
        repo.get_active_bot_by_secret.assert_awaited_once()
        self.assertEqual(["tenant_webhook:db-secret"], redis.get_calls)
        self.assertEqual(1, len(redis.set_calls))
        cache_key, cached_value, ttl = redis.set_calls[0]
        self.assertEqual("tenant_webhook:db-secret", cache_key)
        self.assertEqual(300, ttl)
        cached = json.loads(cached_value)
        self.assertEqual(34, cached["tenant_id"])
        self.assertEqual("tn_demo", cached["tenant_public_id"])
        self.assertEqual(21, cached["tenant_bot_id"])
        self.assertEqual(55, cached["owner_user_id"])
        self.assertEqual(89, cached["owner_telegram_user_id"])
        self.assertEqual("DB 店铺", cached["store_name"])
        self.assertEqual("db_bot", cached["bot_username"])
        self.assertEqual(encrypted_token, cached["encrypted_token"])
        kwargs = dispatcher.feed_update.await_args.kwargs
        self.assertEqual("tenant", kwargs["bot_role"])
        self.assertEqual(34, kwargs["tenant_context"].tenant_id)
        self.assertEqual("tn_demo", kwargs["tenant_context"].tenant_public_id)
        self.assertEqual(21, kwargs["tenant_context"].tenant_bot_id)
        self.assertEqual(89, kwargs["tenant_context"].owner_telegram_user_id)
        self.assertEqual(1, bot.session.close.await_count)

    def test_dispatch_failure_closes_bot_session_and_does_not_leak_token(self) -> None:
        settings = Settings(token_encryption_key=SecretStr(Fernet.generate_key().decode()))
        raw_token = "123456:tenant-error-token"
        encrypted_token = TokenCrypto(settings).encrypt_token(raw_token)
        redis = _FakeRedis(
            {
                "tenant_webhook:error-secret": json.dumps(
                    {
                        "tenant_id": 7,
                        "tenant_public_id": "tn_demo",
                        "tenant_bot_id": 12,
                        "owner_user_id": 3,
                        "owner_telegram_user_id": 42,
                        "store_name": "异常店铺",
                        "bot_username": "error_bot",
                        "encrypted_token": encrypted_token,
                    }
                )
            }
        )
        dispatcher = SimpleNamespace(feed_update=AsyncMock(side_effect=RuntimeError("dispatch failed")))
        bot = _FakeBot()
        tenant_bot = _tenant_bot(
            tenant_bot_id=12,
            tenant_id=7,
            bot_username="error_bot",
            encrypted_token=encrypted_token,
            owner_user_id=3,
            owner_telegram_user_id=42,
            store_name="异常店铺",
        )

        with patch("app.web.webhook.create_bot", return_value=bot) as create_bot:
            with patch("app.web.webhook.get_session_factory", return_value=_fake_session_factory):
                with patch("app.web.webhook.TenantRepository") as repo_class:
                    repo = repo_class.return_value
                    repo.get_active_bot_by_secret = AsyncMock(return_value=tenant_bot)
                    response = _client(
                        settings,
                        redis,
                        dispatcher,
                        raise_server_exceptions=False,
                    ).post(
                        "/telegram/webhook/error-secret",
                        json={"update_id": 4},
                    )

        self.assertEqual(500, response.status_code)
        self.assertNotIn(raw_token, response.text)
        self.assertNotIn(encrypted_token, response.text)
        self.assertNotIn("error-secret", response.text)
        create_bot.assert_called_once_with(raw_token)
        repo.get_active_bot_by_secret.assert_awaited_once()
        self.assertEqual(1, dispatcher.feed_update.await_count)
        self.assertEqual(1, bot.session.close.await_count)

    def test_old_redis_cache_is_deleted_and_db_result_is_recached(self) -> None:
        redis = _FakeRedis(
            {
                "tenant_webhook:old-secret": json.dumps(
                    {
                        "tenant_id": 7,
                        "tenant_bot_id": 12,
                        "owner_user_id": 3,
                        "store_name": "旧缓存",
                        "bot_username": "old_bot",
                        "encrypted_token": "encrypted-old",
                    }
                )
            }
        )
        tenant_bot = _tenant_bot(
            tenant_bot_id=13,
            tenant_id=8,
            bot_username="new_bot",
            encrypted_token="encrypted-new",
            owner_user_id=4,
            owner_telegram_user_id=99,
            store_name="新店铺",
        )

        async def run_case() -> tuple[object, object]:
            with patch("app.web.webhook.get_session_factory", return_value=_fake_session_factory):
                with patch("app.web.webhook.TenantRepository") as repo_class:
                    repo = repo_class.return_value
                    repo.get_active_bot_by_secret = AsyncMock(return_value=tenant_bot)
                    return await _resolve_tenant_context("old-secret", redis)

        tenant_context, encrypted_token = _run_async(run_case())

        self.assertEqual(["tenant_webhook:old-secret"], redis.deleted)
        self.assertEqual(1, len(redis.set_calls))
        cache_key, cached_value, ttl = redis.set_calls[0]
        self.assertEqual("tenant_webhook:old-secret", cache_key)
        self.assertEqual(300, ttl)
        cached = json.loads(cached_value)
        self.assertEqual(99, cached["owner_telegram_user_id"])
        self.assertEqual("tn_demo", cached["tenant_public_id"])
        self.assertEqual("encrypted-new", encrypted_token)
        self.assertEqual(8, tenant_context.tenant_id)
        self.assertEqual("tn_demo", tenant_context.tenant_public_id)
        self.assertEqual(13, tenant_context.tenant_bot_id)
        self.assertEqual(4, tenant_context.owner_user_id)
        self.assertEqual(99, tenant_context.owner_telegram_user_id)
        self.assertEqual("新店铺", tenant_context.store_name)
        self.assertEqual("new_bot", tenant_context.bot_username)


def _tenant_bot(
    *,
    tenant_bot_id: int,
    tenant_id: int,
    bot_username: str,
    encrypted_token: str,
    owner_user_id: int,
    owner_telegram_user_id: int,
    store_name: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=tenant_bot_id,
        tenant_id=tenant_id,
        bot_username=bot_username,
        encrypted_token=encrypted_token,
        tenant=SimpleNamespace(
            public_id="tn_demo",
            owner_user_id=owner_user_id,
            store_name=store_name,
            owner=SimpleNamespace(telegram_user_id=owner_telegram_user_id),
        ),
    )


def _run_async(coro):
    import asyncio

    return asyncio.run(coro)


if __name__ == "__main__":
    unittest.main()
