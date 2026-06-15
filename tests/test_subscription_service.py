from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

try:
    from app.db.models.orders import Order
    from app.db.models.subscriptions import SubscriptionInvoice, SubscriptionPlan, TenantSubscription
    from app.db.models.tenants import AuditLog, PlatformUser, Tenant
    from app.services.subscriptions import SubscriptionService
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过订阅服务测试：{exc.name}") from exc


class _ScalarList:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return self._values


class _ExecuteResult:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object | None:
        return self._value

    def all(self) -> list[object]:
        if isinstance(self._value, list):
            return self._value
        return []

    def scalars(self) -> _ScalarList:
        if isinstance(self._value, list):
            return _ScalarList(self._value)
        if self._value is None:
            return _ScalarList([])
        return _ScalarList([self._value])


class _FakeSession:
    def __init__(self, *, tenant: Tenant | None = None, execute_values: list[object | None] | None = None) -> None:
        self.tenant = tenant
        self.execute_values = list(execute_values or [])
        self.executed_queries: list[object] = []
        self.added: list[object] = []
        self.flush_count = 0
        self._next_id = 1000

    async def get(self, model: type[object], item_id: int) -> object | None:
        if model is Tenant and self.tenant is not None and self.tenant.id == item_id:
            return self.tenant
        return None

    async def execute(self, query: object) -> _ExecuteResult:
        self.executed_queries.append(query)
        if not self.execute_values:
            raise AssertionError("未预期的 session.execute 调用")
        return _ExecuteResult(self.execute_values.pop(0))

    def add(self, item: object) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        self.flush_count += 1
        for item in self.added:
            if getattr(item, "id", None) is None:
                setattr(item, "id", self._next_id)
                self._next_id += 1


class SubscriptionServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.service = SubscriptionService()

    async def test_create_renewal_order_creates_order_and_invoice(self) -> None:
        tenant = _tenant()
        plan = _plan()
        subscription = _subscription(plan_id=plan.id)
        session = _FakeSession(tenant=tenant, execute_values=[plan, subscription])

        created = await self.service.create_renewal_order(
            session=session,
            tenant_id=7,
            buyer_telegram_user_id=42,
            months=3,
            monthly_price=Decimal("10.00"),
        )

        orders = [item for item in session.added if isinstance(item, Order)]
        invoices = [item for item in session.added if isinstance(item, SubscriptionInvoice)]
        self.assertEqual(1, len(orders))
        self.assertEqual(1, len(invoices))

        order = orders[0]
        invoice = invoices[0]
        self.assertEqual("subscription", order.source_type)
        self.assertEqual(3, order.subscription_months)
        self.assertEqual(Decimal("30.00"), order.amount)
        self.assertEqual("USDT", order.currency)
        self.assertEqual("pending_payment", order.payment_mode)
        self.assertEqual("pending", order.status)
        self.assertEqual(order.out_trade_no, invoice.out_trade_no)
        self.assertEqual(subscription.id, invoice.subscription_id)
        self.assertEqual(Decimal("30.00"), invoice.amount)
        self.assertEqual("pending", invoice.status)
        self.assertEqual(order.id, created.order_id)
        self.assertEqual(order.out_trade_no, created.out_trade_no)
        self.assertEqual(order.amount, created.amount)
        self.assertEqual(order.currency, created.currency)
        self.assertEqual(3, created.months)
        self.assertIsNotNone(order.id)
        self.assertIsNotNone(invoice.id)

    async def test_get_tenant_subscription_summary_returns_plan_and_period_without_internal_ids(self) -> None:
        now = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
        tenant = _tenant(
            status="grace",
            subscription_ends_at=now + timedelta(days=1),
            suspended_at=None,
            data_retention_until=now + timedelta(days=30),
        )
        tenant.trial_ends_at = now - timedelta(days=30)
        plan = _plan(grace_days=3)
        subscription = _subscription(
            plan_id=plan.id,
            status="grace",
            current_period_ends_at=now + timedelta(days=1),
        )
        subscription.plan = plan
        subscription.trial_ends_at = tenant.trial_ends_at
        subscription.grace_ends_at = now + timedelta(days=4)
        subscription.created_at = now - timedelta(days=60)
        subscription.updated_at = now
        session = _FakeSession(tenant=tenant, execute_values=[subscription])

        summary = await self.service.get_tenant_subscription_summary(session, tenant_id=7)

        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual("grace", summary.status)
        self.assertEqual("default_monthly", summary.plan_code)
        self.assertEqual("默认月付套餐", summary.plan_name)
        self.assertEqual(Decimal("10.00"), summary.monthly_price)
        self.assertEqual("USDT", summary.currency)
        self.assertEqual(30, summary.trial_days)
        self.assertEqual(3, summary.grace_days)
        self.assertEqual(subscription.trial_ends_at, summary.trial_ends_at)
        self.assertEqual(subscription.current_period_ends_at, summary.current_period_ends_at)
        self.assertEqual(tenant.subscription_ends_at, summary.subscription_ends_at)
        self.assertEqual(subscription.grace_ends_at, summary.grace_ends_at)
        self.assertEqual(tenant.data_retention_until, summary.data_retention_until)
        self.assertEqual(subscription.created_at, summary.created_at)
        self.assertEqual(subscription.updated_at, summary.updated_at)
        self.assertNotIn("tenant_id", repr(summary))
        self.assertNotIn("subscription_id", repr(summary))
        self.assertNotIn("plan_id", repr(summary))

    async def test_get_tenant_subscription_summary_returns_none_for_missing_tenant(self) -> None:
        session = _FakeSession(tenant=None, execute_values=[])

        summary = await self.service.get_tenant_subscription_summary(session, tenant_id=404)

        self.assertIsNone(summary)

    async def test_list_tenant_subscription_invoices_returns_tenant_scoped_safe_summaries(self) -> None:
        now = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
        invoice = _invoice(out_trade_no="SUB123", subscription_id=23)
        invoice.status = "paid"
        invoice.paid_at = now
        invoice.created_at = now - timedelta(minutes=5)
        session = _FakeSession(execute_values=[[invoice]])

        invoices = await self.service.list_tenant_subscription_invoices(
            session,
            tenant_id=7,
            status=" paid ",
            limit=20,
        )

        self.assertEqual(1, len(invoices))
        summary = invoices[0]
        self.assertEqual("SUB123", summary.out_trade_no)
        self.assertEqual(Decimal("10.00"), summary.amount)
        self.assertEqual("USDT", summary.currency)
        self.assertEqual("paid", summary.status)
        self.assertEqual(now, summary.paid_at)
        self.assertEqual(now - timedelta(minutes=5), summary.created_at)
        self.assertNotIn("tenant_id", repr(summary))
        self.assertNotIn("invoice_id", repr(summary))
        self.assertNotIn("subscription_id", repr(summary))

    async def test_list_tenant_subscription_invoices_clamps_limit_and_orders_by_created_at_id(self) -> None:
        session = _FakeSession(execute_values=[[]])

        await self.service.list_tenant_subscription_invoices(session, tenant_id=7, limit=999)

        self.assertEqual(1, len(session.executed_queries))
        query_text = str(session.executed_queries[0])
        self.assertIn("subscription_invoices.tenant_id", query_text)
        self.assertIn("ORDER BY", query_text)
        self.assertIn("subscription_invoices.created_at", query_text)
        self.assertIn("subscription_invoices.id", query_text)

    async def test_list_tenant_subscription_invoices_rejects_invalid_status_and_limit(self) -> None:
        session = _FakeSession(execute_values=[])

        with self.assertRaisesRegex(ValueError, "limit"):
            await self.service.list_tenant_subscription_invoices(session, tenant_id=7, limit=True)
        with self.assertRaisesRegex(ValueError, "status"):
            await self.service.list_tenant_subscription_invoices(session, tenant_id=7, status="failed")

    async def test_apply_paid_subscription_order_updates_period_invoice_and_order(self) -> None:
        period_start = datetime.now(timezone.utc) + timedelta(days=10)
        tenant = _tenant(status="active", subscription_ends_at=period_start)
        plan = _plan()
        subscription = _subscription(plan_id=plan.id, current_period_ends_at=period_start)
        invoice = _invoice(out_trade_no="SUB123", subscription_id=subscription.id)
        order = _subscription_order(out_trade_no="SUB123", months=2, paid_at=datetime.now(timezone.utc))
        session = _FakeSession(tenant=tenant, execute_values=[plan, subscription, invoice])

        await self.service.apply_paid_order(session, order)

        expected_period_end = period_start + timedelta(days=60)
        self.assertEqual(expected_period_end, tenant.subscription_ends_at)
        self.assertEqual("active", tenant.status)
        self.assertEqual("default_monthly", tenant.plan_code)
        self.assertEqual("active", subscription.status)
        self.assertEqual(expected_period_end, subscription.current_period_ends_at)
        self.assertIsNone(subscription.grace_ends_at)
        self.assertEqual("paid", invoice.status)
        self.assertEqual(order.paid_at, invoice.paid_at)
        self.assertEqual("completed", order.status)
        self.assertIsNotNone(order.delivered_at)
        self.assertGreaterEqual(session.flush_count, 1)

    async def test_apply_paid_subscription_order_uses_latest_subscription_period_end(self) -> None:
        tenant_period_end = datetime.now(timezone.utc) + timedelta(days=10)
        subscription_period_end = tenant_period_end + timedelta(days=20)
        tenant = _tenant(status="active", subscription_ends_at=tenant_period_end)
        plan = _plan()
        subscription = _subscription(plan_id=plan.id, current_period_ends_at=subscription_period_end)
        invoice = _invoice(out_trade_no="SUBSYNC", subscription_id=subscription.id)
        order = _subscription_order(out_trade_no="SUBSYNC", months=1)
        session = _FakeSession(tenant=tenant, execute_values=[plan, subscription, invoice])

        await self.service.apply_paid_order(session, order)

        expected_period_end = subscription_period_end + timedelta(days=30)
        self.assertEqual(expected_period_end, tenant.subscription_ends_at)
        self.assertEqual(expected_period_end, subscription.current_period_ends_at)
        self.assertEqual("paid", invoice.status)
        self.assertEqual("completed", order.status)

    async def test_apply_paid_subscription_order_restores_subscription_suspension_only(self) -> None:
        now = datetime.now(timezone.utc)
        tenant = _tenant(
            status="suspended",
            subscription_ends_at=now - timedelta(days=3),
            suspended_at=now - timedelta(days=1),
            data_retention_until=now + timedelta(days=30),
        )
        plan = _plan()
        subscription = _subscription(plan_id=plan.id, status="suspended", current_period_ends_at=tenant.subscription_ends_at)
        invoice = _invoice(out_trade_no="SUB456", subscription_id=subscription.id)
        order = _subscription_order(out_trade_no="SUB456", months=1, paid_at=None)
        session = _FakeSession(tenant=tenant, execute_values=[plan, subscription, invoice])

        await self.service.apply_paid_order(session, order)

        self.assertEqual("active", tenant.status)
        self.assertIsNone(tenant.suspended_at)
        self.assertIsNone(tenant.data_retention_until)
        self.assertEqual("active", subscription.status)
        self.assertEqual("paid", invoice.status)
        self.assertIsNotNone(invoice.paid_at)
        self.assertEqual("completed", order.status)

    async def test_apply_paid_subscription_order_does_not_restore_risk_suspension(self) -> None:
        now = datetime.now(timezone.utc)
        tenant = _tenant(
            status="suspended",
            subscription_ends_at=now + timedelta(days=1),
            suspended_at=now - timedelta(days=1),
            data_retention_until=None,
        )
        plan = _plan()
        subscription = _subscription(plan_id=plan.id, status="suspended", current_period_ends_at=tenant.subscription_ends_at)
        invoice = _invoice(out_trade_no="SUB789", subscription_id=subscription.id)
        order = _subscription_order(out_trade_no="SUB789", months=1)
        session = _FakeSession(tenant=tenant, execute_values=[plan, subscription, invoice])

        await self.service.apply_paid_order(session, order)

        self.assertEqual("suspended", tenant.status)
        self.assertIsNotNone(tenant.suspended_at)
        self.assertEqual("suspended", subscription.status)
        self.assertEqual("paid", invoice.status)
        self.assertEqual("completed", order.status)

    async def test_process_lifecycle_writes_expiry_reminder_once(self) -> None:
        now = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
        tenant = _tenant(status="active", subscription_ends_at=now + timedelta(days=2))
        plan = _plan()
        subscription = _subscription(plan_id=plan.id, current_period_ends_at=tenant.subscription_ends_at)
        subscription.plan = plan
        session = _FakeSession(tenant=tenant, execute_values=[[(subscription, tenant)], []])

        result = await self.service.process_lifecycle(session, now=now, reminder_days=3)

        audits = [item for item in session.added if isinstance(item, AuditLog)]
        self.assertEqual(1, result.reminded_count)
        self.assertEqual(1, len(result.expiry_reminders))
        self.assertEqual(1, len(audits))
        self.assertEqual("subscription.expiry_reminder", audits[0].action)
        self.assertEqual(str(subscription.id), audits[0].target_id)
        self.assertEqual("active", tenant.status)
        self.assertEqual(1, session.flush_count)

        duplicate_session = _FakeSession(
            tenant=tenant,
            execute_values=[
                [(subscription, tenant)],
                [{"period_ends_at": tenant.subscription_ends_at.isoformat()}],
            ],
        )
        duplicate_result = await self.service.process_lifecycle(duplicate_session, now=now, reminder_days=3)

        duplicate_audits = [item for item in duplicate_session.added if isinstance(item, AuditLog)]
        self.assertEqual(0, duplicate_result.reminded_count)
        self.assertEqual([], duplicate_audits)

    async def test_process_lifecycle_moves_expired_subscription_to_grace(self) -> None:
        now = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
        period_end = now - timedelta(days=1)
        tenant = _tenant(status="active", subscription_ends_at=period_end)
        plan = _plan(grace_days=3)
        subscription = _subscription(plan_id=plan.id, current_period_ends_at=period_end)
        subscription.plan = plan
        session = _FakeSession(tenant=tenant, execute_values=[[(subscription, tenant)]])

        result = await self.service.process_lifecycle(session, now=now, retention_days=30)

        audits = [item for item in session.added if isinstance(item, AuditLog)]
        self.assertEqual(1, result.grace_started_count)
        self.assertEqual("grace", tenant.status)
        self.assertEqual("grace", subscription.status)
        self.assertEqual(period_end + timedelta(days=3), subscription.grace_ends_at)
        self.assertEqual(1, len(audits))
        self.assertEqual("subscription.grace_started", audits[0].action)

    async def test_process_lifecycle_suspends_after_grace_expires(self) -> None:
        now = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
        tenant = _tenant(status="grace", subscription_ends_at=now - timedelta(days=5))
        plan = _plan(grace_days=3)
        subscription = _subscription(
            plan_id=plan.id,
            status="grace",
            current_period_ends_at=tenant.subscription_ends_at,
        )
        subscription.plan = plan
        subscription.grace_ends_at = now - timedelta(days=1)
        session = _FakeSession(tenant=tenant, execute_values=[[(subscription, tenant)]])

        result = await self.service.process_lifecycle(session, now=now, retention_days=30)

        audits = [item for item in session.added if isinstance(item, AuditLog)]
        self.assertEqual(1, result.suspended_count)
        self.assertEqual("suspended", tenant.status)
        self.assertEqual(now, tenant.suspended_at)
        self.assertEqual(now + timedelta(days=30), tenant.data_retention_until)
        self.assertEqual("suspended", subscription.status)
        self.assertEqual(1, len(audits))
        self.assertEqual("subscription.suspended", audits[0].action)

    async def test_process_lifecycle_marks_retention_expired_without_deleting_data(self) -> None:
        now = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
        tenant = _tenant(
            status="suspended",
            subscription_ends_at=now - timedelta(days=40),
            suspended_at=now - timedelta(days=30),
            data_retention_until=now,
        )
        plan = _plan()
        subscription = _subscription(
            plan_id=plan.id,
            status="suspended",
            current_period_ends_at=tenant.subscription_ends_at,
        )
        subscription.plan = plan
        session = _FakeSession(tenant=tenant, execute_values=[[(subscription, tenant)]])

        result = await self.service.process_lifecycle(session, now=now)

        audits = [item for item in session.added if isinstance(item, AuditLog)]
        self.assertEqual(1, result.retention_expired_count)
        self.assertEqual("retention_expired", tenant.status)
        self.assertEqual("retention_expired", subscription.status)
        self.assertEqual(1, len(audits))
        self.assertEqual("subscription.retention_expired", audits[0].action)
        self.assertEqual("pending_admin_archive", audits[0].metadata_json["next_step"])

    async def test_list_platform_subscription_attention_returns_sorted_safe_read_only_queue(self) -> None:
        now = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
        plan = _plan(grace_days=3)
        expiring_tenant = _tenant(
            public_id="tn_expiring",
            store_name="即将到期店铺",
            subscription_ends_at=now + timedelta(days=2),
        )
        expiring_subscription = _subscription(
            plan_id=plan.id,
            current_period_ends_at=expiring_tenant.subscription_ends_at,
        )
        suspended_tenant = _tenant(
            public_id="tn_suspended",
            store_name="暂停店铺",
            status="suspended",
            subscription_ends_at=now - timedelta(days=5),
            suspended_at=now - timedelta(days=1),
            data_retention_until=now + timedelta(days=10),
        )
        suspended_subscription = _subscription(
            plan_id=plan.id,
            status="active",
            current_period_ends_at=suspended_tenant.subscription_ends_at,
        )
        retention_tenant = _tenant(
            public_id="tn_retention",
            store_name="保留过期店铺",
            status="suspended",
            subscription_ends_at=now - timedelta(days=40),
            suspended_at=now - timedelta(days=30),
            data_retention_until=now,
        )
        retention_subscription = _subscription(
            plan_id=plan.id,
            status="suspended",
            current_period_ends_at=retention_tenant.subscription_ends_at,
        )
        owner = _platform_user()
        session = _FakeSession(
            execute_values=[
                [
                    (expiring_tenant, owner, expiring_subscription, plan),
                    (suspended_tenant, owner, suspended_subscription, plan),
                    (retention_tenant, owner, retention_subscription, plan),
                ]
            ]
        )

        queue = await self.service.list_platform_subscription_attention(
            session,
            limit=10,
            now=now,
            reminder_days=7,
        )

        self.assertEqual(["tn_retention", "tn_suspended", "tn_expiring"], [item.tenant_public_id for item in queue])
        self.assertEqual(["retention_expired", "suspended", "expiring_soon"], [item.attention_reason for item in queue])
        self.assertEqual("suspended", queue[1].tenant_status)
        self.assertEqual("suspended", queue[1].subscription_status)
        self.assertEqual(9001, queue[0].owner_telegram_user_id)
        self.assertEqual("owner", queue[0].owner_username)
        self.assertEqual(0, session.flush_count)
        self.assertEqual([], session.added)
        self.assertFalse(hasattr(queue[0], "tenant_id"))
        self.assertFalse(hasattr(queue[0], "subscription_id"))
        self.assertFalse(hasattr(queue[0], "owner_user_id"))

    async def test_grant_days_uses_latest_period_end_when_subscription_fields_drift(self) -> None:
        now = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
        subscription_period_end = now + timedelta(days=5)
        tenant_period_end = now + timedelta(days=20)
        tenant = _tenant(status="active", subscription_ends_at=tenant_period_end)
        plan = _plan()
        subscription = _subscription(plan_id=plan.id, current_period_ends_at=subscription_period_end)
        session = _FakeSession(tenant=tenant, execute_values=[plan, subscription])

        result = await self.service.grant_days(
            session=session,
            tenant_id=tenant.id,
            actor_user_id=99,
            days=7,
            monthly_price=Decimal("10.00"),
            reason="手动补偿",
            now=now,
        )

        expected_period_end = tenant_period_end + timedelta(days=7)
        audits = [item for item in session.added if isinstance(item, AuditLog)]
        self.assertEqual(tenant_period_end, result.previous_period_ends_at)
        self.assertEqual(expected_period_end, result.new_period_ends_at)
        self.assertEqual(expected_period_end, tenant.subscription_ends_at)
        self.assertEqual(expected_period_end, subscription.current_period_ends_at)
        self.assertEqual(1, len(audits))
        self.assertEqual("subscription.admin_days_granted", audits[0].action)
        self.assertEqual(tenant_period_end.isoformat(), audits[0].metadata_json["previous_period_ends_at"])
        self.assertEqual(expected_period_end.isoformat(), audits[0].metadata_json["new_period_ends_at"])

    async def test_list_platform_subscription_plans_filters_enabled_and_returns_safe_summaries(self) -> None:
        plan = _plan(monthly_price=Decimal("12.00"), grace_days=3)
        session = _FakeSession(execute_values=[[plan]])

        summaries = await self.service.list_platform_subscription_plans(session, enabled=True, limit=999)

        self.assertEqual(1, len(summaries))
        summary = summaries[0]
        self.assertEqual("default_monthly", summary.code)
        self.assertEqual("默认月付套餐", summary.name)
        self.assertEqual(Decimal("12.00"), summary.monthly_price)
        self.assertEqual("USDT", summary.currency)
        self.assertEqual(30, summary.trial_days)
        self.assertEqual(3, summary.grace_days)
        self.assertTrue(summary.enabled)
        self.assertNotIn("plan_id", repr(summary))
        self.assertIn("LIMIT", str(session.executed_queries[0]))

    async def test_get_platform_subscription_plan_returns_none_for_missing_plan(self) -> None:
        session = _FakeSession(execute_values=[None])

        summary = await self.service.get_platform_subscription_plan(session, code="missing")

        self.assertIsNone(summary)

    async def test_create_platform_subscription_plan_adds_plan_and_platform_audit(self) -> None:
        session = _FakeSession(execute_values=[None])

        summary = await self.service.create_platform_subscription_plan(
            session,
            code=" premium_monthly ",
            name=" 高级月付套餐 ",
            monthly_price=Decimal("29.90"),
            currency="usdt",
            trial_days=7,
            grace_days=2,
            enabled=False,
            reason=" launch ",
        )

        plans = [item for item in session.added if isinstance(item, SubscriptionPlan)]
        audits = [item for item in session.added if isinstance(item, AuditLog)]
        self.assertEqual(1, len(plans))
        self.assertEqual(1, len(audits))
        self.assertEqual("premium_monthly", plans[0].code)
        self.assertEqual("高级月付套餐", plans[0].name)
        self.assertEqual(Decimal("29.90"), plans[0].monthly_price)
        self.assertEqual("USDT", plans[0].currency)
        self.assertFalse(plans[0].enabled)
        self.assertEqual("premium_monthly", summary.code)
        self.assertEqual("subscription.plan_created", audits[0].action)
        self.assertIsNone(audits[0].tenant_id)
        self.assertIsNone(audits[0].actor_user_id)
        self.assertEqual("subscription_plan", audits[0].target_type)
        self.assertEqual("premium_monthly", audits[0].target_id)
        self.assertEqual("launch", audits[0].metadata_json["reason"])
        self.assertEqual(2, session.flush_count)

    async def test_create_platform_subscription_plan_rejects_path_unsafe_code(self) -> None:
        session = _FakeSession(execute_values=[])

        for code in ("basic/v1", "basic plan", "_basic", "basic?debug", "basic#frag"):
            with self.subTest(code=code):
                with self.assertRaisesRegex(ValueError, "订阅计划 code"):
                    await self.service.create_platform_subscription_plan(
                        session,
                        code=code,
                        name="基础套餐",
                        monthly_price=Decimal("10.00"),
                    )

    async def test_update_platform_subscription_plan_changes_only_plan_fields_and_audits(self) -> None:
        plan = _plan()
        session = _FakeSession(execute_values=[plan])

        summary = await self.service.update_platform_subscription_plan(
            session,
            code="default_monthly",
            name="标准月付",
            monthly_price=Decimal("15.00"),
            currency="usdt",
            trial_days=14,
            grace_days=5,
            reason="price update",
        )

        audits = [item for item in session.added if isinstance(item, AuditLog)]
        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual("default_monthly", plan.code)
        self.assertEqual("标准月付", plan.name)
        self.assertEqual(Decimal("15.00"), plan.monthly_price)
        self.assertEqual("USDT", plan.currency)
        self.assertEqual(14, plan.trial_days)
        self.assertEqual(5, plan.grace_days)
        self.assertEqual("default_monthly", summary.code)
        self.assertEqual(1, len(audits))
        self.assertEqual("subscription.plan_updated", audits[0].action)
        self.assertEqual("price update", audits[0].metadata_json["reason"])

    async def test_set_platform_subscription_plan_enabled_soft_disables_without_tenant_changes(self) -> None:
        tenant = _tenant(status="active")
        plan = _plan(enabled=True)
        session = _FakeSession(tenant=tenant, execute_values=[plan])

        summary = await self.service.set_platform_subscription_plan_enabled(
            session,
            code="default_monthly",
            enabled=False,
            reason="maintenance",
        )

        audits = [item for item in session.added if isinstance(item, AuditLog)]
        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertFalse(plan.enabled)
        self.assertFalse(summary.enabled)
        self.assertEqual("active", tenant.status)
        self.assertEqual(1, len(audits))
        self.assertEqual("subscription.plan_status_updated", audits[0].action)
        self.assertEqual("maintenance", audits[0].metadata_json["reason"])

    async def test_create_renewal_order_uses_current_plan_price_for_future_orders(self) -> None:
        tenant = _tenant()
        plan = _plan(monthly_price=Decimal("12.00"))
        subscription = _subscription(plan_id=plan.id)
        session = _FakeSession(tenant=tenant, execute_values=[plan, subscription])

        created = await self.service.create_renewal_order(
            session=session,
            tenant_id=7,
            buyer_telegram_user_id=42,
            months=2,
            monthly_price=Decimal("10.00"),
        )

        orders = [item for item in session.added if isinstance(item, Order)]
        invoices = [item for item in session.added if isinstance(item, SubscriptionInvoice)]
        self.assertEqual(1, len(orders))
        self.assertEqual(1, len(invoices))
        self.assertEqual(Decimal("24.00"), orders[0].amount)
        self.assertEqual(Decimal("24.00"), invoices[0].amount)
        self.assertEqual(Decimal("24.00"), created.amount)
        self.assertEqual("USDT", created.currency)


def _tenant(
    *,
    public_id: str = "tenant-demo",
    store_name: str = "测试店铺",
    status: str = "active",
    subscription_ends_at: datetime | None = None,
    suspended_at: datetime | None = None,
    data_retention_until: datetime | None = None,
) -> Tenant:
    return Tenant(
        id=7,
        public_id=public_id,
        owner_user_id=1,
        status=status,
        store_name=store_name,
        plan_code=None,
        trial_ends_at=None,
        subscription_ends_at=subscription_ends_at,
        suspended_at=suspended_at,
        data_retention_until=data_retention_until,
    )


def _platform_user() -> PlatformUser:
    return PlatformUser(
        id=1,
        telegram_user_id=9001,
        username="owner",
        first_name="Owner",
        language="zh",
        is_platform_admin=False,
        is_banned=False,
    )


def _plan(
    *,
    code: str = "default_monthly",
    name: str = "默认月付套餐",
    monthly_price: Decimal = Decimal("10.00"),
    currency: str = "USDT",
    trial_days: int = 30,
    grace_days: int = 0,
    enabled: bool = True,
) -> SubscriptionPlan:
    return SubscriptionPlan(
        id=11,
        code=code,
        name=name,
        monthly_price=monthly_price,
        currency=currency,
        trial_days=trial_days,
        grace_days=grace_days,
        enabled=enabled,
    )


def _subscription(
    *,
    plan_id: int,
    status: str = "active",
    current_period_ends_at: datetime | None = None,
) -> TenantSubscription:
    return TenantSubscription(
        id=23,
        tenant_id=7,
        plan_id=plan_id,
        status=status,
        trial_ends_at=None,
        current_period_ends_at=current_period_ends_at,
        grace_ends_at=None,
    )


def _invoice(*, out_trade_no: str, subscription_id: int) -> SubscriptionInvoice:
    return SubscriptionInvoice(
        id=31,
        tenant_id=7,
        subscription_id=subscription_id,
        amount=Decimal("10.00"),
        currency="USDT",
        status="pending",
        out_trade_no=out_trade_no,
        paid_at=None,
    )


def _subscription_order(
    *,
    out_trade_no: str,
    months: int,
    paid_at: datetime | None = None,
) -> Order:
    return Order(
        id=41,
        tenant_id=7,
        buyer_telegram_user_id=42,
        source_type="subscription",
        subscription_months=months,
        amount=Decimal("10.00") * Decimal(months),
        currency="USDT",
        display_amount=Decimal("10.00") * Decimal(months),
        display_currency="USDT",
        payment_mode="pending_payment",
        status="paid",
        out_trade_no=out_trade_no,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        paid_at=paid_at,
    )


if __name__ == "__main__":
    unittest.main()
