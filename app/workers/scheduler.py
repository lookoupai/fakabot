from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, List

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.workers.delivery_dispatch import dispatch_pending_deliveries_once
from app.workers.export_jobs import process_pending_export_jobs_once
from app.workers.external_fulfillment import process_paid_external_orders_once
from app.workers.inventory_unlock import release_expired_inventory_locks_once
from app.workers.ledger_settlement import release_available_settlements_once
from app.workers.order_expire import expire_pending_orders_once
from app.workers.payment_reconcile import reconcile_pending_payments_once
from app.workers.subscription_lifecycle import process_subscription_lifecycle_once

logger = logging.getLogger(__name__)


class BackgroundWorkerManager:
    def __init__(self, settings: Settings, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._tasks: List[asyncio.Task] = []

    def start(self) -> None:
        if not self._settings.workers_enabled:
            logger.info("后台 worker 已禁用")
            return
        if self._tasks:
            return

        self._tasks = [
            asyncio.create_task(
                self._run_loop(
                    name="order_expire",
                    interval_seconds=self._settings.order_expire_interval_seconds,
                    runner=self._expire_pending_orders,
                ),
                name="fakabot:order_expire",
            ),
            asyncio.create_task(
                self._run_loop(
                    name="inventory_unlock",
                    interval_seconds=self._settings.inventory_unlock_interval_seconds,
                    runner=self._release_expired_inventory_locks,
                ),
                name="fakabot:inventory_unlock",
            ),
            asyncio.create_task(
                self._run_loop(
                    name="payment_reconcile",
                    interval_seconds=self._settings.payment_reconcile_interval_seconds,
                    runner=self._reconcile_pending_payments,
                ),
                name="fakabot:payment_reconcile",
            ),
            asyncio.create_task(
                self._run_loop(
                    name="external_fulfillment",
                    interval_seconds=self._settings.external_fulfillment_interval_seconds,
                    runner=self._process_paid_external_orders,
                ),
                name="fakabot:external_fulfillment",
            ),
            asyncio.create_task(
                self._run_loop(
                    name="delivery_dispatch",
                    interval_seconds=self._settings.delivery_dispatch_interval_seconds,
                    runner=self._dispatch_pending_deliveries,
                ),
                name="fakabot:delivery_dispatch",
            ),
            asyncio.create_task(
                self._run_loop(
                    name="ledger_settlement",
                    interval_seconds=self._settings.ledger_settlement_interval_seconds,
                    runner=self._release_available_settlements,
                ),
                name="fakabot:ledger_settlement",
            ),
            asyncio.create_task(
                self._run_loop(
                    name="export_jobs",
                    interval_seconds=self._settings.export_job_interval_seconds,
                    runner=self._process_pending_export_jobs,
                ),
                name="fakabot:export_jobs",
            ),
            asyncio.create_task(
                self._run_loop(
                    name="subscription_lifecycle",
                    interval_seconds=self._settings.subscription_lifecycle_interval_seconds,
                    runner=self._process_subscription_lifecycle,
                ),
                name="fakabot:subscription_lifecycle",
            ),
        ]
        logger.info("后台 worker 已启动")

    def is_ready(self) -> bool:
        if not self._settings.workers_enabled:
            return True
        return bool(self._tasks) and all(not task.done() for task in self._tasks)

    async def stop(self) -> None:
        if not self._tasks:
            return
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        logger.info("后台 worker 已停止")

    async def _run_loop(
        self,
        name: str,
        interval_seconds: int,
        runner: Callable[[], Awaitable[int]],
    ) -> None:
        while True:
            try:
                processed_count = await runner()
                if processed_count:
                    logger.info("%s processed %s records", name, processed_count)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("%s failed", name)
            await asyncio.sleep(interval_seconds)

    async def _expire_pending_orders(self) -> int:
        return await expire_pending_orders_once(
            self._session_factory,
            limit=self._settings.worker_batch_limit,
        )

    async def _release_expired_inventory_locks(self) -> int:
        return await release_expired_inventory_locks_once(
            self._session_factory,
            limit=self._settings.worker_batch_limit,
        )

    async def _reconcile_pending_payments(self) -> int:
        return await reconcile_pending_payments_once(
            self._settings,
            self._session_factory,
            limit=self._settings.worker_batch_limit,
        )

    async def _process_paid_external_orders(self) -> int:
        return await process_paid_external_orders_once(
            self._settings,
            self._session_factory,
            limit=self._settings.worker_batch_limit,
        )

    async def _dispatch_pending_deliveries(self) -> int:
        return await dispatch_pending_deliveries_once(
            self._settings,
            self._session_factory,
            limit=self._settings.worker_batch_limit,
        )

    async def _release_available_settlements(self) -> int:
        return await release_available_settlements_once(
            self._session_factory,
            limit=self._settings.worker_batch_limit,
        )

    async def _process_pending_export_jobs(self) -> int:
        return await process_pending_export_jobs_once(
            self._settings,
            self._session_factory,
            limit=self._settings.worker_batch_limit,
        )

    async def _process_subscription_lifecycle(self) -> int:
        return await process_subscription_lifecycle_once(
            self._settings,
            self._session_factory,
            limit=self._settings.worker_batch_limit,
        )
