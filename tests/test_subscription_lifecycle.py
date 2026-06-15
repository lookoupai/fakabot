from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

try:
    from app.services.subscriptions import SubscriptionService
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过订阅生命周期测试：{exc.name}") from exc


class SubscriptionLifecycleDecisionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = SubscriptionService()
        self.now = datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc)

    def test_active_subscription_near_expiry_should_remind(self) -> None:
        decision = self.service.evaluate_lifecycle(
            tenant_status="active",
            period_ends_at=self.now + timedelta(days=2),
            grace_ends_at=None,
            data_retention_until=None,
            plan_grace_days=3,
            now=self.now,
            reminder_days=3,
            retention_days=30,
        )

        self.assertTrue(decision.should_remind)
        self.assertIsNone(decision.next_status)

    def test_expired_active_subscription_enters_grace_when_grace_remains(self) -> None:
        period_ends_at = self.now - timedelta(days=1)

        decision = self.service.evaluate_lifecycle(
            tenant_status="active",
            period_ends_at=period_ends_at,
            grace_ends_at=None,
            data_retention_until=None,
            plan_grace_days=3,
            now=self.now,
            reminder_days=3,
            retention_days=30,
        )

        self.assertFalse(decision.should_remind)
        self.assertEqual("grace", decision.next_status)
        self.assertEqual(period_ends_at + timedelta(days=3), decision.grace_ends_at)

    def test_expired_active_subscription_without_grace_is_suspended(self) -> None:
        decision = self.service.evaluate_lifecycle(
            tenant_status="trial",
            period_ends_at=self.now - timedelta(seconds=1),
            grace_ends_at=None,
            data_retention_until=None,
            plan_grace_days=0,
            now=self.now,
            reminder_days=3,
            retention_days=30,
        )

        self.assertEqual("suspended", decision.next_status)
        self.assertEqual(self.now, decision.suspended_at)
        self.assertEqual(self.now + timedelta(days=30), decision.data_retention_until)

    def test_expired_grace_subscription_is_suspended(self) -> None:
        decision = self.service.evaluate_lifecycle(
            tenant_status="grace",
            period_ends_at=self.now - timedelta(days=4),
            grace_ends_at=self.now,
            data_retention_until=None,
            plan_grace_days=3,
            now=self.now,
            reminder_days=3,
            retention_days=30,
        )

        self.assertEqual("suspended", decision.next_status)
        self.assertEqual(self.now + timedelta(days=30), decision.data_retention_until)

    def test_suspended_risk_tenant_without_retention_is_ignored(self) -> None:
        decision = self.service.evaluate_lifecycle(
            tenant_status="suspended",
            period_ends_at=self.now - timedelta(days=10),
            grace_ends_at=None,
            data_retention_until=None,
            plan_grace_days=0,
            now=self.now,
            reminder_days=3,
            retention_days=30,
        )

        self.assertFalse(decision.should_remind)
        self.assertIsNone(decision.next_status)

    def test_subscription_suspension_after_retention_enters_admin_archive_state(self) -> None:
        decision = self.service.evaluate_lifecycle(
            tenant_status="suspended",
            period_ends_at=self.now - timedelta(days=40),
            grace_ends_at=None,
            data_retention_until=self.now,
            plan_grace_days=0,
            now=self.now,
            reminder_days=3,
            retention_days=30,
        )

        self.assertEqual("retention_expired", decision.next_status)

    def test_admin_adjustment_restores_subscription_suspension(self) -> None:
        decision = self.service.evaluate_admin_period_adjustment(
            tenant_status="suspended",
            data_retention_until=self.now + timedelta(days=10),
        )

        self.assertEqual("active", decision.status)
        self.assertTrue(decision.should_clear_suspension)

    def test_admin_adjustment_does_not_restore_risk_suspension(self) -> None:
        decision = self.service.evaluate_admin_period_adjustment(
            tenant_status="suspended",
            data_retention_until=None,
        )

        self.assertEqual("suspended", decision.status)
        self.assertFalse(decision.should_clear_suspension)

    def test_admin_adjustment_restores_grace_and_retention_expired(self) -> None:
        grace_decision = self.service.evaluate_admin_period_adjustment(
            tenant_status="grace",
            data_retention_until=None,
        )
        retention_decision = self.service.evaluate_admin_period_adjustment(
            tenant_status="retention_expired",
            data_retention_until=self.now,
        )

        self.assertEqual("active", grace_decision.status)
        self.assertFalse(grace_decision.should_clear_suspension)
        self.assertEqual("active", retention_decision.status)
        self.assertTrue(retention_decision.should_clear_suspension)


if __name__ == "__main__":
    unittest.main()
