from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.services.external_sources.auto_fulfillment import ExternalAutoFulfillmentService


async def process_paid_external_orders_once(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    limit: int = 500,
) -> int:
    async with session_factory() as session:
        result = await ExternalAutoFulfillmentService().process_paid_external_orders(
            session,
            settings=settings,
            limit=limit,
        )
        await session.commit()
        return result.imported_count + result.failed_count
