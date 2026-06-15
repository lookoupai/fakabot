from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.inventory import InventoryService


async def release_expired_inventory_locks_once(
    session_factory: async_sessionmaker[AsyncSession],
    limit: int = 500,
) -> int:
    async with session_factory() as session:
        released_count = await InventoryService().release_expired_locks(session, limit=limit)
        await session.commit()
        return released_count
