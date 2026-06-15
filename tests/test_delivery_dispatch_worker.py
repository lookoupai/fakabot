from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

try:
    from cryptography.fernet import Fernet
    from pydantic import SecretStr

    from app.config import Settings
    from app.services.payments import DeliveryInstruction
    from app.services.token_crypto import TokenCrypto
    from app.workers.delivery_dispatch import dispatch_pending_deliveries_once
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过发货调度 worker 测试：{exc.name}") from exc


class _FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    async def commit(self) -> None:
        self.commit_count += 1


def _session_factory(session: _FakeSession):
    def factory() -> _FakeSession:
        return session

    return factory


class DeliveryDispatchWorkerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(token_encryption_key=SecretStr(Fernet.generate_key().decode()))
        self.encrypted_bot_token = TokenCrypto(self.settings).encrypt_token("123:telegram-token")

    def test_dispatch_pending_delivery_sends_and_marks_sent(self) -> None:
        session = _FakeSession()
        service = _service(list_pending_delivery_record_ids=AsyncMock(return_value=[99]))
        bot = SimpleNamespace(session=SimpleNamespace(close=AsyncMock()))

        with patch("app.workers.delivery_dispatch.PaymentService", return_value=service), patch(
            "app.workers.delivery_dispatch.TenantRepository"
        ) as tenant_repo, patch("app.workers.delivery_dispatch.create_bot", return_value=bot) as create_bot, patch(
            "app.workers.delivery_dispatch.send_delivery_instruction", new=AsyncMock()
        ) as send_delivery:
            tenant_repo.return_value.get_active_bot_by_tenant_id = AsyncMock(
                return_value=SimpleNamespace(encrypted_token=self.encrypted_bot_token)
            )
            sent_count = asyncio.run(
                dispatch_pending_deliveries_once(self.settings, _session_factory(session), limit=10)
            )

        self.assertEqual(1, sent_count)
        service.recover_stale_sending_deliveries.assert_awaited_once_with(
            session,
            timeout_seconds=self.settings.delivery_sending_timeout_seconds,
            limit=10,
        )
        service.list_pending_delivery_record_ids.assert_awaited_once_with(session, limit=10)
        service.claim_delivery.assert_awaited_once_with(session, 99)
        tenant_repo.return_value.get_active_bot_by_tenant_id.assert_awaited_once_with(session, 7)
        create_bot.assert_called_once_with("123:telegram-token")
        send_delivery.assert_awaited_once()
        bot.session.close.assert_awaited_once()
        service.mark_delivery_sent.assert_awaited_once_with(session, 99)
        service.mark_delivery_failed.assert_not_awaited()
        self.assertEqual(2, session.commit_count)

    def test_dispatch_pending_delivery_marks_failed_when_tenant_bot_missing(self) -> None:
        session = _FakeSession()
        service = _service(list_pending_delivery_record_ids=AsyncMock(return_value=[99]))

        with patch("app.workers.delivery_dispatch.PaymentService", return_value=service), patch(
            "app.workers.delivery_dispatch.TenantRepository"
        ) as tenant_repo, patch("app.workers.delivery_dispatch.create_bot") as create_bot, patch(
            "app.workers.delivery_dispatch.send_delivery_instruction", new=AsyncMock()
        ) as send_delivery:
            tenant_repo.return_value.get_active_bot_by_tenant_id = AsyncMock(return_value=None)
            sent_count = asyncio.run(
                dispatch_pending_deliveries_once(self.settings, _session_factory(session), limit=10)
            )

        self.assertEqual(0, sent_count)
        create_bot.assert_not_called()
        send_delivery.assert_not_awaited()
        service.mark_delivery_sent.assert_not_awaited()
        service.mark_delivery_failed.assert_awaited_once_with(session, 99, "租户 Bot 不可用，无法自动发货")
        self.assertEqual(2, session.commit_count)

    def test_dispatch_pending_delivery_send_error_closes_bot_and_marks_failed(self) -> None:
        session = _FakeSession()
        service = _service(list_pending_delivery_record_ids=AsyncMock(return_value=[99]))
        bot = SimpleNamespace(session=SimpleNamespace(close=AsyncMock()))

        with patch("app.workers.delivery_dispatch.PaymentService", return_value=service), patch(
            "app.workers.delivery_dispatch.TenantRepository"
        ) as tenant_repo, patch("app.workers.delivery_dispatch.create_bot", return_value=bot), patch(
            "app.workers.delivery_dispatch.send_delivery_instruction",
            new=AsyncMock(side_effect=RuntimeError("telegram send failed")),
        ) as send_delivery:
            tenant_repo.return_value.get_active_bot_by_tenant_id = AsyncMock(
                return_value=SimpleNamespace(encrypted_token=self.encrypted_bot_token)
            )
            sent_count = asyncio.run(
                dispatch_pending_deliveries_once(self.settings, _session_factory(session), limit=10)
            )

        self.assertEqual(0, sent_count)
        send_delivery.assert_awaited_once()
        bot.session.close.assert_awaited_once()
        service.mark_delivery_sent.assert_not_awaited()
        service.mark_delivery_failed.assert_awaited_once_with(session, 99, "telegram send failed")
        self.assertEqual(2, session.commit_count)

    def test_dispatch_pending_delivery_does_not_reclaim_sending_record(self) -> None:
        session = _FakeSession()
        service = _service(
            list_pending_delivery_record_ids=AsyncMock(return_value=[99]),
            claim_delivery=AsyncMock(return_value=None),
        )

        with patch("app.workers.delivery_dispatch.PaymentService", return_value=service), patch(
            "app.workers.delivery_dispatch.TenantRepository"
        ) as tenant_repo, patch("app.workers.delivery_dispatch.create_bot") as create_bot, patch(
            "app.workers.delivery_dispatch.send_delivery_instruction", new=AsyncMock()
        ) as send_delivery:
            sent_count = asyncio.run(
                dispatch_pending_deliveries_once(self.settings, _session_factory(session), limit=10)
            )

        self.assertEqual(0, sent_count)
        service.claim_delivery.assert_awaited_once_with(session, 99)
        tenant_repo.assert_not_called()
        create_bot.assert_not_called()
        send_delivery.assert_not_awaited()
        service.mark_delivery_sent.assert_not_awaited()
        service.mark_delivery_failed.assert_not_awaited()
        self.assertEqual(1, session.commit_count)

    def test_dispatch_recovers_stale_sending_before_listing_pending(self) -> None:
        session = _FakeSession()
        call_order: list[str] = []

        async def recover(*args: object, **kwargs: object) -> int:
            call_order.append("recover")
            return 2

        async def list_pending(*args: object, **kwargs: object) -> list[int]:
            call_order.append("list_pending")
            return []

        service = _service(
            recover_stale_sending_deliveries=AsyncMock(side_effect=recover),
            list_pending_delivery_record_ids=AsyncMock(side_effect=list_pending),
        )

        with patch("app.workers.delivery_dispatch.PaymentService", return_value=service), patch(
            "app.workers.delivery_dispatch.TenantRepository"
        ) as tenant_repo, patch("app.workers.delivery_dispatch.create_bot") as create_bot, patch(
            "app.workers.delivery_dispatch.send_delivery_instruction", new=AsyncMock()
        ) as send_delivery:
            sent_count = asyncio.run(
                dispatch_pending_deliveries_once(self.settings, _session_factory(session), limit=10)
            )

        self.assertEqual(0, sent_count)
        self.assertEqual(["recover", "list_pending"], call_order)
        service.recover_stale_sending_deliveries.assert_awaited_once_with(
            session,
            timeout_seconds=self.settings.delivery_sending_timeout_seconds,
            limit=10,
        )
        service.list_pending_delivery_record_ids.assert_awaited_once_with(session, limit=10)
        service.claim_delivery.assert_not_awaited()
        tenant_repo.assert_not_called()
        create_bot.assert_not_called()
        send_delivery.assert_not_awaited()
        self.assertEqual(1, session.commit_count)


def _instruction() -> DeliveryInstruction:
    return DeliveryInstruction(
        delivery_record_id=99,
        order_id=12,
        tenant_id=7,
        buyer_telegram_user_id=42,
        delivery_type="card_pool",
        out_trade_no="ORD123",
        encrypted_content="encrypted-card",
    )


def _service(**overrides: AsyncMock) -> SimpleNamespace:
    defaults = {
        "recover_stale_sending_deliveries": AsyncMock(return_value=0),
        "list_pending_delivery_record_ids": AsyncMock(return_value=[]),
        "claim_delivery": AsyncMock(return_value=_instruction()),
        "mark_delivery_sent": AsyncMock(),
        "mark_delivery_failed": AsyncMock(),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


if __name__ == "__main__":
    unittest.main()
