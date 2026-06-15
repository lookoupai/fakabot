from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.services.notifications import NotificationService
from app.services.subscriptions import SubscriptionService


async def process_subscription_lifecycle_once(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    limit: int = 500,
) -> int:
    async with session_factory() as session:
        result = await SubscriptionService().process_lifecycle(
            session,
            reminder_days=settings.subscription_expiry_reminder_days,
            retention_days=settings.subscription_data_retention_days,
            limit=limit,
        )
        await session.commit()

    notification_service = NotificationService(settings)
    for reminder in result.expiry_reminders:
        await notification_service.notify_subscription_expiring(
            tenant_id=reminder.tenant_id,
            period_ends_at=reminder.period_ends_at,
        )
    return result.changed_count
