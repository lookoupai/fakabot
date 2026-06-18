"""支付回调失败重试后台任务。

对处理失败（process_status == 'failed'）的支付回调，按指数退避重新交由
``PaymentService.process_payment_callback`` 处理。该服务方法本身是幂等的
（已处理过的回调会直接返回 duplicate），因此重试是安全的。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models.orders import PaymentCallback
from app.services.payments.service import PaymentService

logger = logging.getLogger(__name__)

# 指数退避时间表（秒）：第 1/2/3 次重试分别等待 1 分钟 / 5 分钟 / 30 分钟
RETRY_BACKOFF_SECONDS = {1: 60, 2: 300, 3: 1800}
MAX_RETRY_COUNT = 3
MAX_RETRY_AGE_HOURS = 24
# 每轮最多处理的回调数（每条回调一个独立事务，控制开销）
RETRY_BATCH_LIMIT = 20


async def retry_failed_payment_callbacks_once(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    limit: int = RETRY_BATCH_LIMIT,
) -> int:
    """重试失败的支付回调，返回本轮成功转为 processed 的数量。"""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=MAX_RETRY_AGE_HOURS)

    # 第一步：只读查询候选回调 id（不长期持锁），释放锁后再逐条独立处理
    async with session_factory() as session:
        result = await session.execute(
            select(PaymentCallback.id)
            .where(PaymentCallback.process_status == "failed")
            .where(PaymentCallback.created_at > cutoff)
            .where(PaymentCallback.retry_count < MAX_RETRY_COUNT)
            .order_by(PaymentCallback.created_at.asc())
            .limit(limit)
        )
        candidate_ids = [row[0] for row in result.all()]

    if not candidate_ids:
        return 0

    succeeded = 0
    for callback_id in candidate_ids:
        # 每条回调使用独立事务，单条失败不影响其他回调
        async with session_factory() as session:
            callback = await session.get(PaymentCallback, callback_id, with_for_update=True)
            if callback is None or callback.process_status != "failed":
                continue

            next_retry_count = (callback.retry_count or 0) + 1
            backoff_seconds = RETRY_BACKOFF_SECONDS.get(next_retry_count, 1800)
            if callback.last_retry_at is not None:
                next_retry_time = callback.last_retry_at + timedelta(seconds=backoff_seconds)
                if now < next_retry_time:
                    continue  # 退避未到，跳过本轮

            try:
                result = await PaymentService(settings).process_payment_callback(
                    session,
                    callback.provider,
                    callback.payload_json,
                )
                # service 内部已根据结果更新 callback.process_status（processed/ignored/failed）
                callback.retry_count = next_retry_count
                callback.last_retry_at = now
                callback.failure_reason = None if result.ok else (result.message or "retry_pending")
                await session.commit()

                if result.ok:
                    succeeded += 1
                    logger.info(
                        "payment callback %s retry succeeded (attempt %s/%s)",
                        callback_id,
                        next_retry_count,
                        MAX_RETRY_COUNT,
                    )
                else:
                    logger.info(
                        "payment callback %s retry still failing: %s (attempt %s/%s)",
                        callback_id,
                        result.message,
                        next_retry_count,
                        MAX_RETRY_COUNT,
                    )
            except Exception as exc:
                logger.warning(
                    "payment callback %s retry raised: %s (attempt %s/%s)",
                    callback_id,
                    exc,
                    next_retry_count,
                    MAX_RETRY_COUNT,
                    exc_info=True,
                )
                await session.rollback()
                # 单独记录一次重试尝试（不改变 service 维护的状态字段）
                async with session_factory() as retry_session:
                    cb = await retry_session.get(PaymentCallback, callback_id)
                    if cb is not None and cb.process_status == "failed":
                        cb.retry_count = next_retry_count
                        cb.last_retry_at = now
                        cb.failure_reason = str(exc)[:500]
                        await retry_session.commit()

    return succeeded
