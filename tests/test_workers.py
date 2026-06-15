"""
Workers 测试
"""
from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.config import get_settings
from app.db.models.reports import ExportJob
from app.db.models.subscriptions import SubscriptionPlan, TenantSubscription
from app.db.models.tenants import Tenant
from app.db.session import get_session_factory
from app.services.reports import ReportExportService
from workers.report_worker import ReportWorker
from workers.subscription_worker import SubscriptionWorker


class TestReportWorker(unittest.IsolatedAsyncioTestCase):
    """报表 Worker 测试"""

    async def asyncSetUp(self):
        self.settings = get_settings()
        self.service = ReportExportService()

    async def test_create_products_export_job(self):
        """测试创建商品报表任务"""
        async with get_session_factory()() as session:
            # 创建测试租户
            tenant = Tenant(
                public_id="test_tenant_001",
                store_name="测试店铺",
                status="active",
            )
            session.add(tenant)
            await session.flush()

            # 创建报表任务
            job = await self.service.create_export_job(
                session,
                self.settings,
                report_type="products",
                actor_user_id=None,
                tenant_id=tenant.id,
                scope_type="tenant",
            )

            self.assertEqual(job.report_type, "products")
            self.assertEqual(job.status, "pending")
            self.assertEqual(job.tenant_id, tenant.id)

            await session.rollback()

    async def test_report_worker_process(self):
        """测试报表 Worker 处理逻辑"""
        async with get_session_factory()() as session:
            # 创建测试租户
            tenant = Tenant(
                public_id="test_tenant_002",
                store_name="测试店铺2",
                status="active",
            )
            session.add(tenant)
            await session.flush()

            # 创建 pending 报表任务
            job = ExportJob(
                tenant_id=tenant.id,
                report_type="products",
                scope_type="tenant",
                status="pending",
                row_count=0,
            )
            session.add(job)
            await session.commit()

            # 执行 Worker 处理
            processed = await self.service.process_pending_exports(
                session,
                self.settings,
                limit=10,
            )

            self.assertGreaterEqual(processed, 1)

            # 验证任务状态更新
            await session.refresh(job)
            self.assertIn(job.status, ["completed", "running"])

            await session.rollback()


class TestSubscriptionWorker(unittest.IsolatedAsyncioTestCase):
    """订阅 Worker 测试"""

    async def asyncSetUp(self):
        self.settings = get_settings()

    async def test_trial_ended_transition(self):
        """测试试用期结束转换"""
        async with get_session_factory()() as session:
            # 创建测试租户
            tenant = Tenant(
                public_id="test_tenant_sub_001",
                store_name="订阅测试店铺",
                status="trial",
            )
            session.add(tenant)
            await session.flush()

            # 创建已过期的试用订阅
            subscription = TenantSubscription(
                tenant_id=tenant.id,
                plan_code="basic",
                status="trial",
                trial_days=7,
                grace_days=7,
                trial_ends_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
            session.add(subscription)
            await session.commit()

            # 执行 Worker 处理
            worker = SubscriptionWorker()
            await worker._process_trial_ended(session)
            await session.commit()

            # 验证状态转换
            await session.refresh(subscription)
            self.assertEqual(subscription.status, "grace")
            self.assertIsNotNone(subscription.grace_ends_at)

            await session.rollback()


if __name__ == "__main__":
    unittest.main()
