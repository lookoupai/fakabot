from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.services.reports import ReportExportService


async def process_pending_export_jobs_once(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    limit: int = 500,
) -> int:
    async with session_factory() as session:
        processed_count = await ReportExportService().process_pending_exports(session, settings, limit=limit)
        await session.commit()
        return processed_count
