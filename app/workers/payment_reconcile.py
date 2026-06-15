from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.services.payments import PaymentService


async def reconcile_pending_payments_once(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    limit: int = 500,
) -> int:
    async with session_factory() as session:
        result = await PaymentService(settings).reconcile_pending_payments(session, limit=limit)
        await session.commit()
        return result.changed_count
