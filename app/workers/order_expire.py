from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.orders import OrderService


async def expire_pending_orders_once(
    session_factory: async_sessionmaker[AsyncSession],
    limit: int = 500,
) -> int:
    async with session_factory() as session:
        expired_count = await OrderService().expire_pending_orders(session, limit=limit)
        await session.commit()
        return expired_count
