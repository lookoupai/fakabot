from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

try:
    from app.bots.routers.master import (
        _run_subscription_days_grant,
        _run_subscription_until_update,
        grant_tenant_subscription_days,
        _parse_grant_subscription_days_args,
        _parse_set_subscription_until_args,
        set_tenant_subscription_until,
    )
    from app.services.subscriptions import SubscriptionAdjustmentResult
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过母 Bot 订阅命令测试：{exc.name}") from exc


class _FakeMessage:
    def __init__(self, *, user_id: int | None = 1001) -> None:
        self.from_user = SimpleNamespace(id=user_id) if user_id is not None else None
        self.answers: list[str] = []

    async def answer(self, text: str) -> None:
        self.answers.append(text)


class _FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0
        self.enter_count = 0
        self.exit_count = 0

    async def __aenter__(self) -> "_FakeSession":
        self.enter_count += 1
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.exit_count += 1

    async def commit(self) -> None:
        self.commit_count += 1


class _SessionFactory:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session
        self.call_count = 0

    def __call__(self) -> _FakeSession:
        self.call_count += 1
        return self.session


class MasterSubscriptionCommandParseTest(unittest.TestCase):
    def test_parse_grant_subscription_days_args(self) -> None:
        tenant_id, days, reason = _parse_grant_subscription_days_args("12 | 30 | 活动赠送")

        self.assertEqual(12, tenant_id)
        self.assertEqual(30, days)
        self.assertEqual("活动赠送", reason)

    def test_parse_set_subscription_until_args_with_full_datetime(self) -> None:
        tenant_id, period_ends_at, reason = _parse_set_subscription_until_args(
            "12 | 2026-08-31 23:59:59 | 手动调整"
        )

        self.assertEqual(12, tenant_id)
        self.assertEqual(datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc), period_ends_at)
        self.assertEqual("手动调整", reason)

    def test_parse_set_subscription_until_args_with_date_uses_end_of_day(self) -> None:
        tenant_id, period_ends_at, reason = _parse_set_subscription_until_args("12 | 2026-08-31")

        self.assertEqual(12, tenant_id)
        self.assertEqual(datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc), period_ends_at)
        self.assertIsNone(reason)

    def test_rejects_invalid_grant_days(self) -> None:
        with self.assertRaises(ValueError):
            _parse_grant_subscription_days_args("12 | 0 | bad")


class MasterSubscriptionCommandHandlerTest(unittest.TestCase):
    def test_grant_days_rejects_non_platform_admin(self) -> None:
        message = _FakeMessage(user_id=1001)
        settings = SimpleNamespace(platform_admin_ids=[2002])

        with patch("app.bots.routers.master._run_subscription_days_grant", new=AsyncMock()) as helper:
            asyncio.run(
                grant_tenant_subscription_days(
                    message=message,
                    command=SimpleNamespace(args="12 | 30 | 活动赠送"),
                    settings=settings,
                    session_factory=object(),
                )
            )

        helper.assert_not_awaited()
        self.assertEqual(["无权限。只有平台管理员可以调整租户订阅。"], message.answers)

    def test_set_until_rejects_missing_user(self) -> None:
        message = _FakeMessage(user_id=None)
        settings = SimpleNamespace(platform_admin_ids=[1001])

        with patch("app.bots.routers.master._run_subscription_until_update", new=AsyncMock()) as helper:
            asyncio.run(
                set_tenant_subscription_until(
                    message=message,
                    command=SimpleNamespace(args="12 | 2026-08-31"),
                    settings=settings,
                    session_factory=object(),
                )
            )

        helper.assert_not_awaited()
        self.assertEqual(["无权限。只有平台管理员可以调整租户订阅。"], message.answers)


class MasterSubscriptionCommandHelperTest(unittest.TestCase):
    def test_run_subscription_days_grant_commits_and_passes_service_arguments(self) -> None:
        message = _FakeMessage(user_id=1001)
        settings = SimpleNamespace(subscription_monthly_price=Decimal("10.00"))
        session = _FakeSession()
        session_factory = _SessionFactory(session)
        actor = SimpleNamespace(id=501)
        expected = _adjustment_result()
        repo = SimpleNamespace(get_or_create_platform_user=AsyncMock(return_value=actor))
        service = SimpleNamespace(grant_days=AsyncMock(return_value=expected))

        with patch("app.bots.routers.master.TenantRepository", return_value=repo), patch(
            "app.bots.routers.master.SubscriptionService",
            return_value=service,
        ):
            result = asyncio.run(
                _run_subscription_days_grant(
                    message=message,
                    settings=settings,
                    session_factory=session_factory,
                    tenant_id=12,
                    days=30,
                    reason="活动赠送",
                )
            )

        self.assertIs(expected, result)
        repo.get_or_create_platform_user.assert_awaited_once_with(session, message.from_user, settings)
        service.grant_days.assert_awaited_once_with(
            session=session,
            tenant_id=12,
            actor_user_id=501,
            days=30,
            monthly_price=Decimal("10.00"),
            reason="活动赠送",
        )
        self.assertEqual(1, session_factory.call_count)
        self.assertEqual(1, session.enter_count)
        self.assertEqual(1, session.exit_count)
        self.assertEqual(1, session.commit_count)

    def test_run_subscription_until_update_commits_and_passes_service_arguments(self) -> None:
        message = _FakeMessage(user_id=1001)
        settings = SimpleNamespace(subscription_monthly_price=Decimal("10.00"))
        session = _FakeSession()
        session_factory = _SessionFactory(session)
        actor = SimpleNamespace(id=501)
        period_ends_at = datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)
        expected = _adjustment_result(new_period_ends_at=period_ends_at)
        repo = SimpleNamespace(get_or_create_platform_user=AsyncMock(return_value=actor))
        service = SimpleNamespace(set_period_end=AsyncMock(return_value=expected))

        with patch("app.bots.routers.master.TenantRepository", return_value=repo), patch(
            "app.bots.routers.master.SubscriptionService",
            return_value=service,
        ):
            result = asyncio.run(
                _run_subscription_until_update(
                    message=message,
                    settings=settings,
                    session_factory=session_factory,
                    tenant_id=12,
                    period_ends_at=period_ends_at,
                    reason="手动调整",
                )
            )

        self.assertIs(expected, result)
        repo.get_or_create_platform_user.assert_awaited_once_with(session, message.from_user, settings)
        service.set_period_end.assert_awaited_once_with(
            session=session,
            tenant_id=12,
            actor_user_id=501,
            period_ends_at=period_ends_at,
            monthly_price=Decimal("10.00"),
            reason="手动调整",
        )
        self.assertEqual(1, session.commit_count)

    def test_run_subscription_days_grant_without_user_does_not_open_transaction(self) -> None:
        session = _FakeSession()
        session_factory = _SessionFactory(session)

        with self.assertRaisesRegex(ValueError, "无法识别当前用户"):
            asyncio.run(
                _run_subscription_days_grant(
                    message=_FakeMessage(user_id=None),
                    settings=SimpleNamespace(subscription_monthly_price=Decimal("10.00")),
                    session_factory=session_factory,
                    tenant_id=12,
                    days=30,
                    reason=None,
                )
            )

        self.assertEqual(0, session_factory.call_count)
        self.assertEqual(0, session.commit_count)

    def test_run_subscription_days_grant_service_error_does_not_commit(self) -> None:
        message = _FakeMessage(user_id=1001)
        settings = SimpleNamespace(subscription_monthly_price=Decimal("10.00"))
        session = _FakeSession()
        session_factory = _SessionFactory(session)
        repo = SimpleNamespace(get_or_create_platform_user=AsyncMock(return_value=SimpleNamespace(id=501)))
        service = SimpleNamespace(grant_days=AsyncMock(side_effect=ValueError("租户不存在")))

        with patch("app.bots.routers.master.TenantRepository", return_value=repo), patch(
            "app.bots.routers.master.SubscriptionService",
            return_value=service,
        ):
            with self.assertRaisesRegex(ValueError, "租户不存在"):
                asyncio.run(
                    _run_subscription_days_grant(
                        message=message,
                        settings=settings,
                        session_factory=session_factory,
                        tenant_id=12,
                        days=30,
                        reason=None,
                    )
                )

        self.assertEqual(1, session_factory.call_count)
        self.assertEqual(1, session.enter_count)
        self.assertEqual(1, session.exit_count)
        self.assertEqual(0, session.commit_count)


def _adjustment_result(
    *,
    new_period_ends_at: datetime | None = None,
) -> SubscriptionAdjustmentResult:
    return SubscriptionAdjustmentResult(
        tenant_id=12,
        status="active",
        previous_period_ends_at=datetime(2026, 7, 31, 23, 59, 59, tzinfo=timezone.utc),
        new_period_ends_at=new_period_ends_at or datetime(2026, 8, 30, 23, 59, 59, tzinfo=timezone.utc),
        action="subscription.admin_days_granted",
    )


if __name__ == "__main__":
    unittest.main()
