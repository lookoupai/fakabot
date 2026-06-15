"""
支付回调失败重试 Worker

定期重试失败的支付回调：
- 查询 24小时内失败的回调
- 指数退避重试（1min、5min、30min）
- 最多重试 3 次
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import get_settings
from app.db.models.orders import PaymentCallback
from app.db.session import get_session_factory
from app.services.payment_providers import EpayCompatibleProvider, EpusdtGmpayProvider
from workers.base import BaseWorker

logger = logging.getLogger(__name__)


# 重试退避时间表（秒）
RETRY_BACKOFF_SECONDS = {
    1: 60,      # 第1次重试：1分钟后
    2: 300,     # 第2次重试：5分钟后
    3: 1800,    # 第3次重试：30分钟后
}
MAX_RETRY_COUNT = 3
MAX_RETRY_AGE_HOURS = 24


class PaymentRetryWorker(BaseWorker):
    """支付回调重试 Worker"""

    def __init__(self, redis_client=None):
        super().__init__(
            name="payment-retry-worker",
            interval_seconds=300,  # 每5分钟检查一次
            redis_client=redis_client,
        )
        self.settings = get_settings()
        # 注意：实际使用时需要从配置加载 Provider 配置
        # 这里只是框架代码，真实环境需要提供配置

    async def process(self):
        """处理失败回调重试"""
        async with get_session_factory()() as session:
            retry_count = await self._retry_failed_callbacks(session)
            await session.commit()

            if retry_count > 0:
                logger.info(f"Retried {retry_count} failed payment callback(s)")

    async def _retry_failed_callbacks(self, session) -> int:
        """重试失败的回调"""
        now = datetime.now(timezone.utc)
        cutoff_time = now - timedelta(hours=MAX_RETRY_AGE_HOURS)

        # 查询需要重试的回调
        result = await session.execute(
            select(PaymentCallback)
            .where(PaymentCallback.process_status == "failed")
            .where(PaymentCallback.created_at > cutoff_time)
            .where(PaymentCallback.retry_count < MAX_RETRY_COUNT)
            .order_by(PaymentCallback.created_at.asc())
            .with_for_update(skip_locked=True)
            .limit(20)
        )

        callbacks = list(result.scalars().all())
        count = 0

        for callback in callbacks:
            # 检查是否应该重试
            next_retry_count = (callback.retry_count or 0) + 1
            backoff_seconds = RETRY_BACKOFF_SECONDS.get(next_retry_count, 1800)

            # 如果有上次重试时间，检查退避时间
            if callback.last_retry_at:
                next_retry_time = callback.last_retry_at + timedelta(seconds=backoff_seconds)
                if now < next_retry_time:
                    continue  # 还没到重试时间

            # 执行重试
            try:
                logger.info(
                    f"Retrying payment callback {callback.id}, "
                    f"attempt {next_retry_count}/{MAX_RETRY_COUNT}"
                )

                # 从 payload_json 恢复原始数据
                provider = callback.provider
                payload = callback.payload_json

                # 调用对应 provider 的回调处理
                await self._process_provider_callback(session, callback, provider, payload)

                # 标记为成功
                callback.process_status = "success"
                callback.processed_at = now
                callback.retry_count = next_retry_count

                logger.info(f"Payment callback {callback.id} retry succeeded")
                count += 1

            except Exception as e:
                logger.error(
                    f"Payment callback {callback.id} retry failed: {e}",
                    exc_info=True,
                )
                # 更新重试信息
                callback.retry_count = next_retry_count
                callback.last_retry_at = now
                callback.failure_reason = str(e)[:500]

        return count

    async def _process_provider_callback(
        self,
        session,
        callback: PaymentCallback,
        provider: str,
        payload: dict,
    ):
        """
        处理 Provider 回调

        Args:
            session: 数据库会话
            callback: 回调记录
            provider: Provider 类型
            payload: 回调数据

        Raises:
            Exception: 处理失败
        """
        if provider == "epusdt_gmpay":
            await self._process_epusdt_callback(session, callback, payload)
        elif provider == "epay_compatible":
            await self._process_epay_callback(session, callback, payload)
        else:
            logger.warning(f"Unknown provider: {provider}")
            raise ValueError(f"不支持的 Provider: {provider}")

    async def _process_epusdt_callback(
        self,
        session,
        callback: PaymentCallback,
        payload: dict,
    ):
        """
        处理 EPUSDT 回调

        注意：实际使用需要：
        1. 从配置加载 Provider 配置
        2. 查询订单并更新状态
        3. 记录审计日志
        """
        # 注意：这里需要实际的 Provider 配置
        # 由于是框架代码，暂时使用 Mock 逻辑
        logger.info(f"Processing EPUSDT callback for order {callback.out_trade_no}")

        # 实际实现示例：
        # provider = EpusdtGmpayProvider(config)
        # result = await provider.process_callback(payload)
        #
        # # 查询订单
        # order = await session.get(Order, ...)
        # # 更新订单状态
        # order.status = "paid"
        # # 记录审计日志

    async def _process_epay_callback(
        self,
        session,
        callback: PaymentCallback,
        payload: dict,
    ):
        """
        处理易支付回调

        注意：实际使用需要：
        1. 从配置加载 Provider 配置
        2. 查询订单并更新状态
        3. 记录审计日志
        """
        logger.info(f"Processing Epay callback for order {callback.out_trade_no}")

        # 实际实现示例：
        # provider = EpayCompatibleProvider(config)
        # result = await provider.process_callback(payload)
        #
        # # 查询订单
        # order = await session.get(Order, ...)
        # # 更新订单状态
        # # 记录审计日志


async def main():
    """启动支付重试 Worker"""
    redis_client = None

    worker = PaymentRetryWorker(redis_client=redis_client)
    logger.info("Starting payment retry worker...")

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
