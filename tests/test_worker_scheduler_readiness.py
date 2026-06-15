from __future__ import annotations

import asyncio
import unittest

try:
    from app.config import Settings
    from app.workers.scheduler import BackgroundWorkerManager
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过后台调度器 readiness 测试：{exc.name}") from exc


class BackgroundWorkerManagerReadinessTest(unittest.TestCase):
    def test_disabled_workers_are_ready_without_tasks(self) -> None:
        manager = BackgroundWorkerManager(Settings(workers_enabled=False), object())  # type: ignore[arg-type]

        manager.start()

        self.assertTrue(manager.is_ready())

    def test_enabled_workers_are_not_ready_before_start(self) -> None:
        manager = BackgroundWorkerManager(Settings(workers_enabled=True), object())  # type: ignore[arg-type]

        self.assertFalse(manager.is_ready())

    def test_enabled_workers_are_ready_while_tasks_are_alive(self) -> None:
        async def run() -> None:
            manager = BackgroundWorkerManager(Settings(workers_enabled=True), object())  # type: ignore[arg-type]
            wait_forever = asyncio.Event()

            async def fake_loop(**_kwargs: object) -> None:
                await wait_forever.wait()

            manager._run_loop = fake_loop  # type: ignore[method-assign]
            manager.start()
            await asyncio.sleep(0)

            self.assertTrue(manager.is_ready())

            await manager.stop()
            self.assertFalse(manager.is_ready())

        asyncio.run(run())

    def test_enabled_workers_are_not_ready_when_any_task_exits(self) -> None:
        async def run() -> None:
            manager = BackgroundWorkerManager(Settings(workers_enabled=True), object())  # type: ignore[arg-type]

            async def finished_loop(**_kwargs: object) -> None:
                return None

            manager._run_loop = finished_loop  # type: ignore[method-assign]
            manager.start()
            await asyncio.sleep(0)

            self.assertFalse(manager.is_ready())

            await manager.stop()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
