"""
报表生成 Worker

定期处理 pending 状态的报表任务，生成 CSV 文件。
支持报表类型：orders、payments、inventory、ledger、products
"""
from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.db.session import get_session_factory
from app.services.reports import ReportExportService
from workers.base import BaseWorker

logger = logging.getLogger(__name__)


class ReportWorker(BaseWorker):
    """报表生成 Worker"""

    def __init__(self, redis_client=None):
        super().__init__(
            name="report-worker",
            interval_seconds=30,  # 每30秒检查一次
            redis_client=redis_client,
        )
        self.settings = get_settings()
        self.service = ReportExportService()

    async def process(self):
        """处理 pending 报表任务"""
        async with get_session_factory()() as session:
            processed_count = await self.service.process_pending_exports(
                session,
                self.settings,
                limit=5,  # 每次最多处理5个任务
            )
            await session.commit()

            if processed_count > 0:
                logger.info(f"Processed {processed_count} export job(s)")


async def main():
    """启动报表 Worker"""
    # 可选：初始化 Redis 客户端用于心跳
    # redis_client = await create_redis_client()
    redis_client = None

    worker = ReportWorker(redis_client=redis_client)
    logger.info("Starting report worker...")

    try:
        await worker.start()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    finally:
        await worker.stop()
        if redis_client:
            await redis_client.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(main())
