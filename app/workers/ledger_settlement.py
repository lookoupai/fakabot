from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.ledger import LedgerService


async def release_available_settlements_once(
    session_factory: async_sessionmaker[AsyncSession],
    limit: int = 500,
) -> int:
    async with session_factory() as session:
        released_count = await LedgerService().release_available_settlements(session, limit=limit)
        await session.commit()
        return released_count
