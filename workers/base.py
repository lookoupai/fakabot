"""
Base worker class for background task processing.
"""
from __future__ import annotations

import asyncio
import logging
import signal
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class BaseWorker(ABC):
    """基础 Worker 类，所有 Worker 都继承此类"""

    def __init__(
        self,
        name: str,
        interval_seconds: int,
        redis_client: Optional[any] = None,
    ):
        """
        初始化 Worker

        Args:
            name: Worker 名称
            interval_seconds: 处理间隔（秒）
            redis_client: Redis 客户端（用于心跳）
        """
        self.name = name
        self.interval_seconds = interval_seconds
        self.redis_client = redis_client
        self.running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """启动 Worker"""
        logger.info(f"{self.name} starting...")
        self.running = True

        # 注册信号处理
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        # 启动主循环
        self._task = asyncio.create_task(self._run_loop())

        try:
            await self._task
        except asyncio.CancelledError:
            logger.info(f"{self.name} cancelled")

    async def stop(self):
        """停止 Worker"""
        logger.info(f"{self.name} stopping...")
        self.running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def _run_loop(self):
        """主循环"""
        logger.info(f"{self.name} started, interval={self.interval_seconds}s")

        while self.running:
            try:
                # 更新心跳
                await self._update_heartbeat()

                # 执行处理逻辑
                start_time = datetime.now()
                await self.process()
                duration = (datetime.now() - start_time).total_seconds()

                logger.debug(
                    f"{self.name} process completed in {duration:.2f}s"
                )

            except Exception as e:
                logger.error(f"{self.name} process error: {e}", exc_info=True)

            # 等待下一次处理
            if self.running:
                await asyncio.sleep(self.interval_seconds)

        logger.info(f"{self.name} stopped")

    async def _update_heartbeat(self):
        """更新心跳到 Redis"""
        if self.redis_client is None:
            return

        try:
            heartbeat_key = f"worker:{self.name}:heartbeat"
            # 设置心跳，有效期为间隔的3倍（容错）
            ttl = max(self.interval_seconds * 3, 300)
            await self.redis_client.setex(
                heartbeat_key,
                ttl,
                datetime.now().isoformat(),
            )
        except Exception as e:
            logger.warning(f"{self.name} update heartbeat failed: {e}")

    @abstractmethod
    async def process(self):
        """
        处理逻辑，由子类实现

        Raises:
            Exception: 处理失败时抛出异常
        """
        pass
