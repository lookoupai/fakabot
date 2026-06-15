from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

try:
    from app.config import Settings
    from app.services.subscriptions import SubscriptionExpiryReminder, SubscriptionLifecycleResult
    from app.workers.subscription_lifecycle import process_subscription_lifecycle_once
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过订阅 worker 测试：{exc.name}") from exc


class _SessionContext:
    def __init__(self, session: object) -> None:
        self._session = session

    async def __aenter__(self) -> object:
        return self._session

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class _SessionFactory:
    def __init__(self, session: object) -> None:
        self._session = session

    def __call__(self) -> _SessionContext:
        return _SessionContext(self._session)


class SubscriptionLifecycleWorkerTest(unittest.IsolatedAsyncioTestCase):
    async def test_worker_commits_before_sending_expiry_notifications(self) -> None:
        events: list[str] = []
        session = type("Session", (), {})()
        session.commit = AsyncMock(side_effect=lambda: events.append("commit"))
        period_ends_at = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
        lifecycle_result = SubscriptionLifecycleResult(
            reminded_count=1,
            grace_started_count=1,
            expiry_reminders=[
                SubscriptionExpiryReminder(tenant_id=42, period_ends_at=period_ends_at),
            ],
        )
        settings = Settings(
            subscription_expiry_reminder_days=5,
            subscription_data_retention_days=30,
        )

        with (
            patch("app.workers.subscription_lifecycle.SubscriptionService") as service_cls,
            patch("app.workers.subscription_lifecycle.NotificationService") as notification_cls,
        ):
            service = service_cls.return_value
            service.process_lifecycle = AsyncMock(return_value=lifecycle_result)
            notification = notification_cls.return_value
            notification.notify_subscription_expiring = AsyncMock(
                side_effect=lambda **_: events.append("notify")
            )

            changed_count = await process_subscription_lifecycle_once(
                settings,
                _SessionFactory(session),
                limit=123,
            )

        self.assertEqual(2, changed_count)
        service.process_lifecycle.assert_awaited_once_with(
            session,
            reminder_days=5,
            retention_days=30,
            limit=123,
        )
        session.commit.assert_awaited_once()
        notification.notify_subscription_expiring.assert_awaited_once_with(
            tenant_id=42,
            period_ends_at=period_ends_at,
        )
        self.assertEqual(["commit", "notify"], events)


if __name__ == "__main__":
    unittest.main()
