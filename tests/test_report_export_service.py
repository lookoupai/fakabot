from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

try:
    from app.config import Settings
    from app.services.reports import ReportExportService
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过报表导出服务测试：{exc.name}") from exc


class _FakeSession:
    def __init__(self) -> None:
        self.executed_queries: list[object] = []
        self.added_objects: list[object] = []
        self.flush_count = 0

    async def execute(self, query: object) -> object:
        self.executed_queries.append(query)
        raise AssertionError("非法参数应在查询前被拒绝")

    def add(self, instance: object) -> None:
        self.added_objects.append(instance)
        raise AssertionError("非法参数应在写入前被拒绝")

    async def flush(self) -> None:
        self.flush_count += 1
        raise AssertionError("非法参数应在 flush 前被拒绝")


class _FakeScalarResult:
    def __init__(self, item: object) -> None:
        self._item = item

    def scalar_one_or_none(self) -> object:
        return self._item


class _FakeReportSession:
    def __init__(self, item: object) -> None:
        self.item = item
        self.executed_queries: list[object] = []
        self.added_objects: list[object] = []
        self.flush_count = 0

    async def execute(self, query: object) -> _FakeScalarResult:
        self.executed_queries.append(query)
        return _FakeScalarResult(self.item)

    def add(self, instance: object) -> None:
        self.added_objects.append(instance)

    async def flush(self) -> None:
        self.flush_count += 1


class ReportExportServiceValidationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.service = ReportExportService()
        self.settings = Settings()

    async def test_list_export_jobs_rejects_invalid_status_before_query(self) -> None:
        session = _FakeSession()

        with self.assertRaisesRegex(ValueError, "报表任务状态必须是"):
            await self.service.list_export_jobs(
                session=session,
                settings=self.settings,
                tenant_id=7,
                status="bad-status",
            )

        self.assertEqual([], session.executed_queries)

    async def test_list_export_jobs_rejects_invalid_report_type_before_query(self) -> None:
        session = _FakeSession()

        with self.assertRaisesRegex(ValueError, "报表类型必须是"):
            await self.service.list_export_jobs(
                session=session,
                settings=self.settings,
                tenant_id=7,
                report_type="cards",
            )

        self.assertEqual([], session.executed_queries)

    async def test_create_export_job_rejects_invalid_report_type_before_insert(self) -> None:
        session = _FakeSession()

        with self.assertRaisesRegex(ValueError, "报表类型不支持"):
            await self.service.create_export_job(
                session=session,
                settings=self.settings,
                report_type="cards",
                actor_user_id=None,
                tenant_id=7,
                scope_type="tenant",
            )

        self.assertEqual([], session.executed_queries)
        self.assertEqual([], session.added_objects)
        self.assertEqual(0, session.flush_count)

    async def test_get_downloadable_tenant_export_rejects_invalid_identity_before_query(self) -> None:
        session = _FakeSession()

        result = await self.service.get_downloadable_tenant_export(
            session=session,
            tenant_id=0,
            export_job_id=81,
        )

        self.assertIsNone(result)
        self.assertEqual([], session.executed_queries)

    async def test_get_downloadable_tenant_export_returns_none_for_missing_or_cross_tenant_job(self) -> None:
        session = _FakeReportSession(None)

        result = await self.service.get_downloadable_tenant_export(
            session=session,
            tenant_id=7,
            export_job_id=81,
        )

        self.assertIsNone(result)
        self.assertEqual(1, len(session.executed_queries))

    async def test_get_downloadable_tenant_export_marks_expired_without_storage_leak(self) -> None:
        job = SimpleNamespace(
            id=81,
            tenant_id=7,
            requested_by_user_id=3,
            report_type="orders",
            scope_type="tenant",
            status="completed",
            storage_key="exports/tenant_7/private.csv",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        session = _FakeReportSession(job)

        with self.assertRaisesRegex(ValueError, "报表下载链接已过期"):
            await self.service.get_downloadable_tenant_export(
                session=session,
                tenant_id=7,
                export_job_id=81,
            )

        self.assertEqual("expired", job.status)
        self.assertEqual(1, session.flush_count)
        self.assertEqual(1, len(session.added_objects))


if __name__ == "__main__":
    unittest.main()
