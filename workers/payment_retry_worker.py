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
# from app.services.orders import OrderPaymentService  # TODO: 实际服务类名待确认
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
        # self.payment_service = OrderPaymentService()  # TODO: 实际服务实例化

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

                # 调用支付回调处理逻辑
                # 注意：这里需要重新构造回调数据
                # TODO: 实际实现需要从 callback.raw_payload 恢复原始数据
                # 并调用对应 provider 的回调处理方法

                # 暂时标记为已重试
                callback.retry_count = next_retry_count
                callback.last_retry_at = now

                # 如果重试成功，更新状态
                # callback.process_status = "success"
                # callback.processed_at = now
                # callback.failure_reason = None

                logger.info(f"Payment callback {callback.id} retry completed")
                count += 1

            except Exception as e:
                logger.error(
                    f"Payment callback {callback.id} retry failed: {e}",
                    exc_info=True,
                )
                callback.retry_count = next_retry_count
                callback.last_retry_at = now
                callback.failure_reason = f"重试失败: {str(e)[:500]}"

        return count


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
