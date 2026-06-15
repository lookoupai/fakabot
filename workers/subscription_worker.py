"""
订阅生命周期 Worker

定期检查订阅状态，自动处理生命周期事件：
- 试用期到期 → 检查付款 → 转活跃/宽限
- 当前周期结束 → 检查续费 → 转活跃/宽限
- 宽限期到期 → 暂停服务
- 保留期到期 → 标记待清理
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import get_settings
from app.db.models.subscriptions import TenantSubscription
from app.db.models.tenants import AuditLog, Tenant
from app.db.session import get_session_factory
from app.services.telegram_notifications import TelegramNotificationService
from workers.base import BaseWorker

logger = logging.getLogger(__name__)


class SubscriptionWorker(BaseWorker):
    """订阅生命周期 Worker"""

    def __init__(self, redis_client=None):
        super().__init__(
            name="subscription-worker",
            interval_seconds=3600,  # 每小时检查一次
            redis_client=redis_client,
        )
        self.settings = get_settings()
        # 初始化 Telegram 通知服务
        bot_token = None
        if self.settings.master_bot_token:
            bot_token = self.settings.master_bot_token.get_secret_value()
        self.notification_service = TelegramNotificationService(bot_token=bot_token)

    async def process(self):
        """处理订阅生命周期事件"""
        async with get_session_factory()() as session:
            # 1. 处理试用期到期
            trial_ended = await self._process_trial_ended(session)

            # 2. 处理当前周期结束
            period_ended = await self._process_period_ended(session)

            # 3. 处理宽限期到期
            grace_ended = await self._process_grace_ended(session)

            # 4. 处理保留期到期（每天一次）
            retention_ended = await self._process_retention_ended(session)

            await session.commit()

            total_processed = trial_ended + period_ended + grace_ended + retention_ended
            if total_processed > 0:
                logger.info(
                    f"Processed subscription lifecycle: "
                    f"trial_ended={trial_ended}, period_ended={period_ended}, "
                    f"grace_ended={grace_ended}, retention_ended={retention_ended}"
                )

    async def _process_trial_ended(self, session) -> int:
        """处理试用期到期"""
        now = datetime.now(timezone.utc)

        # 查询试用期已到期但状态仍为 trial 的订阅
        result = await session.execute(
            select(TenantSubscription, Tenant)
            .join(Tenant, Tenant.id == TenantSubscription.tenant_id)
            .where(TenantSubscription.status == "trial")
            .where(TenantSubscription.trial_ends_at.is_not(None))
            .where(TenantSubscription.trial_ends_at <= now)
            .with_for_update(skip_locked=True)
            .limit(100)
        )

        count = 0
        for subscription, tenant in result.all():
            # 检查是否有付款
            # TODO: 实际应该检查是否有已支付的续费订单
            # 这里简化处理：直接进入宽限期
            subscription.status = "grace"
            subscription.grace_ends_at = now + timedelta(days=subscription.grace_days or 7)

            session.add(
                AuditLog(
                    tenant_id=subscription.tenant_id,
                    action="subscription.trial_ended",
                    target_type="subscription",
                    target_id=str(subscription.id),
                    metadata_json={
                        "previous_status": "trial",
                        "new_status": "grace",
                        "trial_ends_at": subscription.trial_ends_at.isoformat() if subscription.trial_ends_at else None,
                        "grace_ends_at": subscription.grace_ends_at.isoformat() if subscription.grace_ends_at else None,
                    },
                )
            )

            # 发送 Telegram 通知
            if tenant.owner_telegram_user_id:
                try:
                    await self.notification_service.send_period_ending_reminder(
                        telegram_user_id=tenant.owner_telegram_user_id,
                        tenant_name=tenant.store_name or "您的店铺",
                        plan_name=subscription.plan_code or "当前套餐",
                        days_remaining=1,
                        renew_url=None,  # TODO: 生成续费链接
                    )
                except Exception as e:
                    logger.warning(f"Failed to send period ending notice to tenant {subscription.tenant_id}: {e}")
            logger.info(
                f"Trial ended for tenant {subscription.tenant_id}, "
                f"moved to grace period until {subscription.grace_ends_at}"
            )
            count += 1

        return count

    async def _process_period_ended(self, session) -> int:
        """处理当前周期结束"""
        now = datetime.now(timezone.utc)

        # 查询当前周期已结束但状态仍为 active 的订阅
        result = await session.execute(
            select(TenantSubscription, Tenant)
            .join(Tenant, Tenant.id == TenantSubscription.tenant_id)
            .where(TenantSubscription.status == "active")
            .where(TenantSubscription.current_period_ends_at.is_not(None))
            .where(TenantSubscription.current_period_ends_at <= now)
            .with_for_update(skip_locked=True)
            .limit(100)
        )

        count = 0
        for subscription, tenant in result.all():
            # 检查是否有续费订单
            # TODO: 实际应该检查是否有已支付的续费订单
            # 这里简化处理：直接进入宽限期
            subscription.status = "grace"
            subscription.grace_ends_at = now + timedelta(days=subscription.grace_days or 7)

            session.add(
                AuditLog(
                    tenant_id=subscription.tenant_id,
                    action="subscription.period_ended",
                    target_type="subscription",
                    target_id=str(subscription.id),
                    metadata_json={
                        "previous_status": "active",
                        "new_status": "grace",
                        "period_ends_at": subscription.current_period_ends_at.isoformat() if subscription.current_period_ends_at else None,
                        "grace_ends_at": subscription.grace_ends_at.isoformat() if subscription.grace_ends_at else None,
                    },
                )
            )

            # 发送 Telegram 通知
            if tenant.owner_telegram_user_id:
                try:
                    await self.notification_service.send_period_ending_reminder(
                        telegram_user_id=tenant.owner_telegram_user_id,
                        tenant_name=tenant.store_name or "您的店铺",
                        plan_name=subscription.plan_code or "当前套餐",
                        days_remaining=1,
                        renew_url=None,  # TODO: 生成续费链接
                    )
                except Exception as e:
                    logger.warning(f"Failed to send period ending notice to tenant {subscription.tenant_id}: {e}")
            logger.info(
                f"Period ended for tenant {subscription.tenant_id}, "
                f"moved to grace period until {subscription.grace_ends_at}"
            )
            count += 1

        return count

    async def _process_grace_ended(self, session) -> int:
        """处理宽限期到期"""
        now = datetime.now(timezone.utc)

        # 查询宽限期已到期但状态仍为 grace 的订阅
        result = await session.execute(
            select(TenantSubscription, Tenant)
            .join(Tenant, Tenant.id == TenantSubscription.tenant_id)
            .where(TenantSubscription.status == "grace")
            .where(TenantSubscription.grace_ends_at.is_not(None))
            .where(TenantSubscription.grace_ends_at <= now)
            .with_for_update(skip_locked=True)
            .limit(100)
        )

        count = 0
        for subscription, tenant in result.all():
            # 暂停服务
            subscription.status = "suspended"
            subscription.suspended_at = now
            subscription.data_retention_until = now + timedelta(days=30)

            # 同步更新租户状态
            tenant.status = "suspended"

            session.add(
                AuditLog(
                    tenant_id=subscription.tenant_id,
                    action="subscription.grace_ended",
                    target_type="subscription",
                    target_id=str(subscription.id),
                    metadata_json={
                        "previous_status": "grace",
                        "new_status": "suspended",
                        "grace_ends_at": subscription.grace_ends_at.isoformat() if subscription.grace_ends_at else None,
                        "suspended_at": subscription.suspended_at.isoformat() if subscription.suspended_at else None,
                        "data_retention_until": subscription.data_retention_until.isoformat() if subscription.data_retention_until else None,
                    },
                )
            )

            # TODO: 清理 Webhook 缓存
            # 发送 Telegram 通知
            if tenant.owner_telegram_user_id:
                try:
                    await self.notification_service.send_service_suspended_notice(
                        telegram_user_id=tenant.owner_telegram_user_id,
                        tenant_name=tenant.store_name or "您的店铺",
                        retention_days=30,
                        renew_url=None,  # TODO: 生成续费链接
                    )
                except Exception as e:
                    logger.warning(f"Failed to send suspended notice to tenant {subscription.tenant_id}: {e}")
            logger.warning(
                f"Grace period ended for tenant {subscription.tenant_id}, "
                f"service suspended, data retention until {subscription.data_retention_until}"
            )
            count += 1

        return count

    async def _process_retention_ended(self, session) -> int:
        """处理保留期到期（标记待清理，不实际删除）"""
        now = datetime.now(timezone.utc)

        # 查询保留期已到期的订阅
        result = await session.execute(
            select(TenantSubscription, Tenant)
            .join(Tenant, Tenant.id == TenantSubscription.tenant_id)
            .where(TenantSubscription.status == "suspended")
            .where(TenantSubscription.data_retention_until.is_not(None))
            .where(TenantSubscription.data_retention_until <= now)
            .with_for_update(skip_locked=True)
            .limit(50)
        )

        count = 0
        for subscription, tenant in result.all():
            # 只记录审计日志，不实际删除数据
            session.add(
                AuditLog(
                    tenant_id=subscription.tenant_id,
                    action="subscription.retention_ended",
                    target_type="subscription",
                    target_id=str(subscription.id),
                    metadata_json={
                        "status": "suspended",
                        "data_retention_until": subscription.data_retention_until.isoformat() if subscription.data_retention_until else None,
                        "note": "数据保留期已到期，标记待清理",
                    },
                )
            )

            # 发送最后通知
            if tenant.owner_telegram_user_id:
                try:
                    await self.notification_service.send_retention_ending_notice(
                        telegram_user_id=tenant.owner_telegram_user_id,
                        tenant_name=tenant.store_name or "您的店铺",
                        days_remaining=7,
                        renew_url=None,  # TODO: 生成续费链接
                    )
                except Exception as e:
                    logger.warning(f"Failed to send retention ending notice to tenant {subscription.tenant_id}: {e}")
            logger.warning(
                f"Retention period ended for tenant {subscription.tenant_id}, "
                f"marked for cleanup (data not deleted)"
            )
            count += 1

        return count


async def main():
    """启动订阅生命周期 Worker"""
    redis_client = None

    worker = SubscriptionWorker(redis_client=redis_client)
    logger.info("Starting subscription worker...")

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
