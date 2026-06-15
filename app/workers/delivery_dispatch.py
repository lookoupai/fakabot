from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bots.factory import create_bot
from app.config import Settings
from app.db.repos.tenants import TenantRepository
from app.services.delivery import send_delivery_instruction
from app.services.payments import PaymentService
from app.services.token_crypto import TokenCrypto


async def dispatch_pending_deliveries_once(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    limit: int = 100,
) -> int:
    service = PaymentService(settings)
    async with session_factory() as session:
        recovered_count = await service.recover_stale_sending_deliveries(
            session,
            timeout_seconds=settings.delivery_sending_timeout_seconds,
            limit=limit,
        )
        if recovered_count:
            await session.commit()
        delivery_record_ids = await service.list_pending_delivery_record_ids(session, limit=limit)

    sent_count = 0
    for delivery_record_id in delivery_record_ids:
        sent = await _dispatch_one_delivery(settings, session_factory, service, delivery_record_id)
        if sent:
            sent_count += 1
    return sent_count


async def _dispatch_one_delivery(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    service: PaymentService,
    delivery_record_id: int,
) -> bool:
    async with session_factory() as session:
        instruction = await service.claim_delivery(session, delivery_record_id)
        encrypted_bot_token = None
        if instruction is not None:
            tenant_bot = await TenantRepository().get_active_bot_by_tenant_id(session, instruction.tenant_id)
            encrypted_bot_token = tenant_bot.encrypted_token if tenant_bot is not None else None
        await session.commit()

    if instruction is None:
        return False
    if encrypted_bot_token is None:
        await _mark_delivery_failed(session_factory, service, delivery_record_id, "租户 Bot 不可用，无法自动发货")
        return False

    crypto = TokenCrypto(settings)
    try:
        bot_token = crypto.decrypt_token(encrypted_bot_token)
        bot = create_bot(bot_token)
        try:
            await send_delivery_instruction(bot, settings, crypto, instruction)
        finally:
            await bot.session.close()
    except Exception as exc:
        await _mark_delivery_failed(session_factory, service, delivery_record_id, str(exc))
        return False

    async with session_factory() as session:
        await service.mark_delivery_sent(session, delivery_record_id)
        await session.commit()
    return True


async def _mark_delivery_failed(
    session_factory: async_sessionmaker[AsyncSession],
    service: PaymentService,
    delivery_record_id: int,
    error_message: str,
) -> None:
    async with session_factory() as session:
        await service.mark_delivery_failed(session, delivery_record_id, error_message)
        await session.commit()
