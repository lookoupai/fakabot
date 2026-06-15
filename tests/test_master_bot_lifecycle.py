from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

try:
    from cryptography.fernet import Fernet
    from pydantic import SecretStr

    from app.bots.routers.master import (
        TENANT_WEBHOOK_ALLOWED_UPDATES,
        admin_web_code,
        _parse_tenant_bot_id,
        bind_token,
        deactivate_bot,
        reset_webhook,
    )
    from app.config import Settings
    from app.services.admin_web import AdminWebWorkspaceSummary
    from app.services.token_crypto import TokenCrypto
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过母 Bot 生命周期测试：{exc.name}") from exc


class MasterBotLifecycleCommandTest(unittest.TestCase):
    def test_parse_tenant_bot_id_rejects_invalid_values(self) -> None:
        self.assertEqual(12, _parse_tenant_bot_id("12", "/reset_webhook 12"))
        with self.assertRaisesRegex(ValueError, "请提供 Bot ID"):
            _parse_tenant_bot_id("", "/reset_webhook 1")
        with self.assertRaisesRegex(ValueError, "必须是整数"):
            _parse_tenant_bot_id("abc", "/reset_webhook 1")
        with self.assertRaisesRegex(ValueError, "必须大于 0"):
            _parse_tenant_bot_id("0", "/reset_webhook 1")

    def test_admin_web_code_rejects_missing_redis_without_workspace_lookup(self) -> None:
        settings, _, _ = _settings_with_token()
        session = _FakeSession()
        message = _message()

        with patch("app.bots.routers.master.TenantRepository") as repo_class:
            with patch("app.bots.routers.master.AdminWebService.list_workspaces", new=AsyncMock()) as list_workspaces:
                asyncio.run(admin_web_code(message, SimpleNamespace(args=""), settings, _session_factory(session)))

        message.answer.assert_awaited_once_with("绑定码服务暂不可用，请稍后再试。")
        repo_class.assert_not_called()
        list_workspaces.assert_not_called()
        session.commit.assert_not_awaited()

    def test_admin_web_code_uses_first_accessible_workspace_without_leaking_internal_ids(self) -> None:
        settings, _, _ = _settings_with_token()
        session = _FakeSession()
        message = _message()
        redis = _FakeRedis()
        repo = _FakeTenantRepository(_tenant_bot(encrypted_token="encrypted-token"))
        workspaces = (
            AdminWebWorkspaceSummary(
                workspace_id="tn_demo",
                kind="tenant",
                role="owner",
                title="演示店铺",
                tenant_public_id="tn_demo",
                bot_username="demo_bot",
            ),
        )

        with patch("app.bots.routers.master.TenantRepository", return_value=repo):
            with patch("app.bots.routers.master.AdminWebService.list_workspaces", new=AsyncMock(return_value=workspaces)):
                asyncio.run(
                    admin_web_code(
                        message,
                        SimpleNamespace(args=""),
                        settings,
                        _session_factory(session),
                        redis_client=redis,
                    )
                )

        session.commit.assert_awaited_once()
        self.assertEqual(1, len(redis.values))
        payload = next(iter(redis.values.values()))
        self.assertIn('"current_workspace_id":"tn_demo"', payload)
        self.assertIn('"telegram_user_id":123', payload)
        reply = message.answer.await_args.args[0]
        self.assertIn("网页管理后台一次性绑定码", reply)
        self.assertIn("工作区：演示店铺", reply)
        self.assertNotIn("tenant_id", reply.lower())
        self.assertNotIn("encrypted-token", reply)

    def test_admin_web_code_with_bot_id_uses_owner_bot_public_workspace(self) -> None:
        settings, _, _ = _settings_with_token()
        session = _FakeSession()
        message = _message()
        redis = _FakeRedis()
        tenant_bot = _tenant_bot(encrypted_token="encrypted-token", public_id="tn_owner_bot", store_name="Owner Store")
        repo = _FakeTenantRepository(tenant_bot)

        with patch("app.bots.routers.master.TenantRepository", return_value=repo):
            with patch("app.bots.routers.master.AdminWebService.list_workspaces", new=AsyncMock()) as list_workspaces:
                asyncio.run(
                    admin_web_code(
                        message,
                        SimpleNamespace(args="9"),
                        settings,
                        _session_factory(session),
                        redis_client=redis,
                    )
                )

        list_workspaces.assert_not_called()
        session.commit.assert_awaited_once()
        payload = next(iter(redis.values.values()))
        self.assertIn('"current_workspace_id":"tn_owner_bot"', payload)
        reply = message.answer.await_args.args[0]
        self.assertIn("工作区：Owner Store", reply)
        self.assertNotIn("tenant_id", reply.lower())

    def test_reset_webhook_rotates_secret_and_does_not_expose_token(self) -> None:
        settings, raw_token, encrypted_token = _settings_with_token()
        tenant_bot = _tenant_bot(encrypted_token=encrypted_token)
        repo = _FakeTenantRepository(tenant_bot)
        session = _FakeSession()
        telegram_bot = _FakeTelegramBot()
        cache_delete = AsyncMock()
        message = _message()

        with patch("app.bots.routers.master.TenantRepository", return_value=repo):
            with patch("app.bots.routers.master.create_bot", return_value=telegram_bot) as create_bot:
                with patch("app.bots.routers.master.generate_webhook_secret", return_value="new-secret"):
                    with patch("app.bots.routers.master._delete_tenant_webhook_cache", cache_delete):
                        asyncio.run(
                            reset_webhook(
                                message,
                                SimpleNamespace(args="9"),
                                settings,
                                _session_factory(session),
                            )
                        )

        create_bot.assert_called_once_with(raw_token)
        telegram_bot.set_webhook.assert_awaited_once_with(
            "https://store.example/telegram/webhook/new-secret",
            allowed_updates=["message", "callback_query"],
            drop_pending_updates=True,
        )
        telegram_bot.session.close.assert_awaited_once()
        session.commit.assert_awaited_once()
        cache_delete.assert_awaited_once_with(settings, "old-secret", "new-secret")
        message.answer.assert_awaited_once_with("Webhook 已重置：Bot ID 9。")
        self.assertNotIn(raw_token, message.answer.await_args.args[0])
        self.assertEqual("new-secret", tenant_bot.webhook_secret)

    def test_deactivate_bot_deletes_webhook_and_does_not_expose_token(self) -> None:
        settings, raw_token, encrypted_token = _settings_with_token()
        tenant_bot = _tenant_bot(encrypted_token=encrypted_token)
        repo = _FakeTenantRepository(tenant_bot)
        session = _FakeSession()
        telegram_bot = _FakeTelegramBot()
        cache_delete = AsyncMock()
        message = _message()

        with patch("app.bots.routers.master.TenantRepository", return_value=repo):
            with patch("app.bots.routers.master.create_bot", return_value=telegram_bot) as create_bot:
                with patch("app.bots.routers.master._delete_tenant_webhook_cache", cache_delete):
                    asyncio.run(
                        deactivate_bot(
                            message,
                            SimpleNamespace(args="9"),
                            settings,
                            _session_factory(session),
                        )
                    )

        create_bot.assert_called_once_with(raw_token)
        telegram_bot.delete_webhook.assert_awaited_once_with(drop_pending_updates=True)
        telegram_bot.session.close.assert_awaited_once()
        session.commit.assert_awaited_once()
        cache_delete.assert_awaited_once_with(settings, "old-secret")
        message.answer.assert_awaited_once_with("Bot 已停用：Bot ID 9。")
        self.assertNotIn(raw_token, message.answer.await_args.args[0])
        self.assertEqual("disabled", tenant_bot.status)

    def test_bind_token_success_encrypts_token_sets_webhook_and_redacts_reply(self) -> None:
        settings, raw_token, _ = _settings_with_token()
        message = _bind_message(raw_token)
        master_bot = _MasterReplyBot()
        candidate_bot = _CandidateTenantBot()
        repo = _BindTenantRepository(token_exists=False)
        session = _FakeSession()
        bootstrap_subscription = AsyncMock()

        with patch("app.bots.routers.master.TenantRepository", return_value=repo), patch(
            "app.bots.routers.master.create_bot", return_value=candidate_bot
        ) as create_bot, patch(
            "app.bots.routers.master.generate_webhook_secret", return_value="fixed-webhook-secret"
        ), patch(
            "app.bots.routers.master.SubscriptionService"
        ) as subscription_service:
            subscription_service.return_value.bootstrap_tenant_subscription = bootstrap_subscription
            asyncio.run(bind_token(message, master_bot, settings, _session_factory(session)))

        create_bot.assert_called_once_with(raw_token)
        message.delete.assert_awaited_once()
        candidate_bot.get_me.assert_awaited_once()
        candidate_bot.set_webhook.assert_awaited_once_with(
            "https://store.example/telegram/webhook/fixed-webhook-secret",
            allowed_updates=TENANT_WEBHOOK_ALLOWED_UPDATES,
            drop_pending_updates=True,
        )
        candidate_bot.session.close.assert_awaited_once()
        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()
        bootstrap_subscription.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            monthly_price=settings.subscription_monthly_price,
        )
        self.assertEqual(42, repo.owner.id)
        self.assertEqual(999001, repo.created_kwargs["bot_user_id"])
        self.assertEqual("tenant_demo_bot", repo.created_kwargs["bot_username"])
        self.assertEqual("fixed-webhook-secret", repo.created_kwargs["webhook_secret"])
        self.assertEqual(TokenCrypto(settings).token_hash(raw_token), repo.created_kwargs["token_hash"])
        encrypted_token = repo.created_kwargs["encrypted_token"]
        token_hash = repo.created_kwargs["token_hash"]
        self.assertNotEqual(raw_token, encrypted_token)
        self.assertEqual(raw_token, TokenCrypto(settings).decrypt_token(encrypted_token))

        reply_text = master_bot.sent_messages[0][1]
        self.assertIn("绑定成功", reply_text)
        for secret_value in (raw_token, encrypted_token, token_hash, "fixed-webhook-secret"):
            self.assertNotIn(secret_value, reply_text)
        self.assertNotIn(raw_token, candidate_bot.set_webhook.await_args.args[0])

    def test_bind_token_duplicate_rolls_back_without_setting_webhook_or_leaking_token(self) -> None:
        settings, raw_token, _ = _settings_with_token()
        message = _bind_message(raw_token)
        master_bot = _MasterReplyBot()
        candidate_bot = _CandidateTenantBot()
        repo = _BindTenantRepository(token_exists=True)
        session = _FakeSession()

        with patch("app.bots.routers.master.TenantRepository", return_value=repo), patch(
            "app.bots.routers.master.create_bot", return_value=candidate_bot
        ), patch("app.bots.routers.master.SubscriptionService") as subscription_service:
            asyncio.run(bind_token(message, master_bot, settings, _session_factory(session)))

        message.delete.assert_awaited_once()
        candidate_bot.get_me.assert_awaited_once()
        candidate_bot.set_webhook.assert_not_awaited()
        candidate_bot.session.close.assert_awaited_once()
        self.assertEqual(0, repo.create_count)
        subscription_service.return_value.bootstrap_tenant_subscription.assert_not_called()
        session.rollback.assert_awaited_once()
        session.commit.assert_not_awaited()
        reply_text = master_bot.sent_messages[0][1]
        self.assertEqual("这个 Bot Token 已经绑定过。", reply_text)
        self.assertNotIn(raw_token, reply_text)

    def test_bind_token_set_webhook_failure_redacts_token_and_closes_candidate_bot(self) -> None:
        settings, raw_token, _ = _settings_with_token()
        message = _bind_message(raw_token)
        master_bot = _MasterReplyBot()
        candidate_bot = _CandidateTenantBot(set_webhook_error=RuntimeError("webhook failed with token"))
        repo = _BindTenantRepository(token_exists=False)
        session = _FakeSession()

        with patch("app.bots.routers.master.TenantRepository", return_value=repo), patch(
            "app.bots.routers.master.create_bot", return_value=candidate_bot
        ), patch("app.bots.routers.master.generate_webhook_secret", return_value="fixed-webhook-secret"), patch(
            "app.bots.routers.master.SubscriptionService"
        ) as subscription_service:
            subscription_service.return_value.bootstrap_tenant_subscription = AsyncMock()
            asyncio.run(bind_token(message, master_bot, settings, _session_factory(session)))

        message.delete.assert_awaited_once()
        candidate_bot.get_me.assert_awaited_once()
        candidate_bot.set_webhook.assert_awaited_once()
        candidate_bot.session.close.assert_awaited_once()
        session.commit.assert_not_awaited()
        reply_text = master_bot.sent_messages[0][1]
        self.assertEqual("绑定失败：RuntimeError", reply_text)
        encrypted_token = repo.created_kwargs["encrypted_token"]
        token_hash = repo.created_kwargs["token_hash"]
        for secret_value in (raw_token, encrypted_token, token_hash, "fixed-webhook-secret"):
            self.assertNotIn(secret_value, reply_text)


def _settings_with_token() -> tuple[Settings, str, str]:
    settings = Settings(
        public_base_url="https://store.example",
        token_encryption_key=SecretStr(Fernet.generate_key().decode()),
    )
    raw_token = "123456789:AAExampleTelegramBotTokenSecretValue12345"
    return settings, raw_token, TokenCrypto(settings).encrypt_token(raw_token)


def _tenant_bot(
    *,
    encrypted_token: str,
    public_id: str = "tn_demo",
    store_name: str = "Demo Store",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=9,
        tenant_id=7,
        bot_username="tenant_bot",
        encrypted_token=encrypted_token,
        webhook_secret="old-secret",
        status="active",
        tenant=SimpleNamespace(public_id=public_id, store_name=store_name),
    )


def _message() -> SimpleNamespace:
    return SimpleNamespace(
        from_user=SimpleNamespace(id=123, username="owner", first_name="Owner", language_code="zh"),
        answer=AsyncMock(),
    )


def _session_factory(session: object) -> object:
    def factory() -> _SessionContext:
        return _SessionContext(session)

    return factory


class _SessionContext:
    def __init__(self, session: object) -> None:
        self._session = session

    async def __aenter__(self) -> object:
        return self._session

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class _FakeSession:
    def __init__(self) -> None:
        self.commit = AsyncMock()
        self.rollback = AsyncMock()


class _FakeTenantRepository:
    def __init__(self, tenant_bot: SimpleNamespace) -> None:
        self._tenant_bot = tenant_bot
        self._owner = SimpleNamespace(id=42)

    async def get_or_create_platform_user(self, session: object, telegram_user: object, settings: Settings) -> object:
        return self._owner

    async def get_owner_bot(self, session: object, owner_user_id: int, tenant_bot_id: int) -> object:
        if owner_user_id == self._owner.id and tenant_bot_id == self._tenant_bot.id:
            return self._tenant_bot
        return None

    async def rotate_owner_bot_webhook(
        self,
        session: object,
        owner_user_id: int,
        tenant_bot_id: int,
        webhook_secret: str,
    ) -> object:
        tenant_bot = await self.get_owner_bot(session, owner_user_id, tenant_bot_id)
        if tenant_bot is not None:
            tenant_bot.webhook_secret = webhook_secret
        return tenant_bot

    async def deactivate_owner_bot(self, session: object, owner_user_id: int, tenant_bot_id: int) -> object:
        tenant_bot = await self.get_owner_bot(session, owner_user_id, tenant_bot_id)
        if tenant_bot is not None:
            tenant_bot.status = "disabled"
        return tenant_bot


class _FakeTelegramBot:
    def __init__(self) -> None:
        self.set_webhook = AsyncMock()
        self.delete_webhook = AsyncMock()
        self.session = SimpleNamespace(close=AsyncMock())


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


def _bind_message(raw_token: str) -> SimpleNamespace:
    return SimpleNamespace(
        text=raw_token,
        from_user=SimpleNamespace(id=123, username="owner", first_name="Owner", language_code="zh"),
        chat=SimpleNamespace(id=555),
        delete=AsyncMock(),
        answer=AsyncMock(),
    )


class _MasterReplyBot:
    def __init__(self) -> None:
        self.sent_messages: list[tuple[int, str]] = []
        self.send_message = AsyncMock(side_effect=self._send_message)

    async def _send_message(self, chat_id: int, text: str) -> None:
        self.sent_messages.append((chat_id, text))


class _CandidateTenantBot:
    def __init__(self, *, set_webhook_error: Exception | None = None) -> None:
        self.get_me = AsyncMock(return_value=SimpleNamespace(id=999001, username="tenant_demo_bot"))
        if set_webhook_error is None:
            self.set_webhook = AsyncMock()
        else:
            self.set_webhook = AsyncMock(side_effect=set_webhook_error)
        self.session = SimpleNamespace(close=AsyncMock())


class _BindTenantRepository:
    def __init__(self, *, token_exists: bool) -> None:
        self.token_exists = token_exists
        self.owner = SimpleNamespace(id=42)
        self.created_kwargs: dict[str, object] = {}
        self.create_count = 0

    async def get_or_create_platform_user(self, session: object, telegram_user: object, settings: Settings) -> object:
        return self.owner

    async def token_hash_exists(self, session: object, token_hash: str) -> bool:
        return self.token_exists

    async def create_tenant_with_bot(self, **kwargs: object) -> SimpleNamespace:
        self.create_count += 1
        self.created_kwargs = dict(kwargs)
        return SimpleNamespace(id=88, tenant_id=7)


if __name__ == "__main__":
    unittest.main()
