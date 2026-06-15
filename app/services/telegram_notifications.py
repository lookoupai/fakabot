"""
Telegram 通知服务

用于发送各种业务通知到 Telegram：
- 订单状态通知
- 订阅生命周期通知
- 发货通知
- 系统提醒
"""
from __future__ import annotations

import logging
from typing import Optional

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import Settings

logger = logging.getLogger(__name__)


class TelegramNotificationService:
    """Telegram 通知服务"""

    def __init__(self, bot_token: Optional[str] = None):
        """
        初始化通知服务

        Args:
            bot_token: Bot Token，如果不提供则从环境变量读取
        """
        self.bot_token = bot_token
        self._bot: Optional[Bot] = None

    def _get_bot(self) -> Optional[Bot]:
        """获取 Bot 实例"""
        if self._bot is None and self.bot_token:
            self._bot = Bot(token=self.bot_token)
        return self._bot

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
        parse_mode: str = "HTML",
    ) -> bool:
        """
        发送消息

        Args:
            chat_id: 接收者 Telegram User ID
            text: 消息文本
            reply_markup: 内联键盘
            parse_mode: 解析模式（HTML/Markdown）

        Returns:
            是否发送成功
        """
        bot = self._get_bot()
        if bot is None:
            logger.warning("Bot token not configured, skipping notification")
            return False

        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            logger.info(f"Sent notification to {chat_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to send notification to {chat_id}: {e}")
            return False

    # ==================== 订阅通知 ====================

    async def send_trial_ending_reminder(
        self,
        telegram_user_id: int,
        tenant_name: str,
        plan_name: str,
        days_remaining: int,
        renew_url: Optional[str] = None,
    ) -> bool:
        """
        发送试用即将到期提醒

        Args:
            telegram_user_id: 用户 Telegram ID
            tenant_name: 租户名称
            plan_name: 套餐名称
            days_remaining: 剩余天数
            renew_url: 续费链接

        Returns:
            是否发送成功
        """
        text = f"""
🔔 <b>试用即将到期提醒</b>

您的租户「<b>{tenant_name}</b>」试用期将在 <b>{days_remaining}</b> 天后到期。

当前套餐：{plan_name}

为避免服务中断，请及时续费。
"""

        buttons = []
        if renew_url:
            buttons.append([
                InlineKeyboardButton(text="💳 立即续费", url=renew_url)
            ])

        reply_markup = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
        return await self.send_message(telegram_user_id, text, reply_markup)

    async def send_trial_ended_notice(
        self,
        telegram_user_id: int,
        tenant_name: str,
        grace_days: int,
        renew_url: Optional[str] = None,
    ) -> bool:
        """
        发送试用期结束通知

        Args:
            telegram_user_id: 用户 Telegram ID
            tenant_name: 租户名称
            grace_days: 宽限期天数
            renew_url: 续费链接

        Returns:
            是否发送成功
        """
        text = f"""
⏰ <b>试用期已结束</b>

您的租户「<b>{tenant_name}</b>」试用期已结束。

您有 <b>{grace_days}</b> 天的宽限期来完成续费。
宽限期内服务继续可用，宽限期结束后服务将暂停。

请尽快续费以避免服务中断。
"""

        buttons = []
        if renew_url:
            buttons.append([
                InlineKeyboardButton(text="💳 立即续费", url=renew_url)
            ])

        reply_markup = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
        return await self.send_message(telegram_user_id, text, reply_markup)

    async def send_period_ending_reminder(
        self,
        telegram_user_id: int,
        tenant_name: str,
        plan_name: str,
        days_remaining: int,
        renew_url: Optional[str] = None,
    ) -> bool:
        """
        发送当前周期即将结束提醒

        Args:
            telegram_user_id: 用户 Telegram ID
            tenant_name: 租户名称
            plan_name: 套餐名称
            days_remaining: 剩余天数
            renew_url: 续费链接

        Returns:
            是否发送成功
        """
        text = f"""
🔔 <b>订阅即将到期提醒</b>

您的租户「<b>{tenant_name}</b>」订阅将在 <b>{days_remaining}</b> 天后到期。

当前套餐：{plan_name}

为确保服务不中断，请及时续费。
"""

        buttons = []
        if renew_url:
            buttons.append([
                InlineKeyboardButton(text="💳 立即续费", url=renew_url)
            ])

        reply_markup = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
        return await self.send_message(telegram_user_id, text, reply_markup)

    async def send_grace_period_warning(
        self,
        telegram_user_id: int,
        tenant_name: str,
        days_remaining: int,
        renew_url: Optional[str] = None,
    ) -> bool:
        """
        发送宽限期警告

        Args:
            telegram_user_id: 用户 Telegram ID
            tenant_name: 租户名称
            days_remaining: 宽限期剩余天数
            renew_url: 续费链接

        Returns:
            是否发送成功
        """
        text = f"""
⚠️ <b>宽限期警告</b>

您的租户「<b>{tenant_name}</b>」已进入宽限期。

宽限期剩余：<b>{days_remaining}</b> 天

宽限期结束后，服务将被暂停，请尽快续费！
"""

        buttons = []
        if renew_url:
            buttons.append([
                InlineKeyboardButton(text="💳 立即续费", url=renew_url)
            ])

        reply_markup = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
        return await self.send_message(telegram_user_id, text, reply_markup)

    async def send_service_suspended_notice(
        self,
        telegram_user_id: int,
        tenant_name: str,
        retention_days: int,
        renew_url: Optional[str] = None,
    ) -> bool:
        """
        发送服务已暂停通知

        Args:
            telegram_user_id: 用户 Telegram ID
            tenant_name: 租户名称
            retention_days: 数据保留天数
            renew_url: 续费链接

        Returns:
            是否发送成功
        """
        text = f"""
🚫 <b>服务已暂停</b>

由于长期未续费，您的租户「<b>{tenant_name}</b>」服务已暂停。

数据保留期：<b>{retention_days}</b> 天
保留期结束后，数据将被标记为待清理。

恢复服务请续费。
"""

        buttons = []
        if renew_url:
            buttons.append([
                InlineKeyboardButton(text="💳 恢复服务", url=renew_url)
            ])

        reply_markup = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
        return await self.send_message(telegram_user_id, text, reply_markup)

    async def send_retention_ending_notice(
        self,
        telegram_user_id: int,
        tenant_name: str,
        days_remaining: int,
        renew_url: Optional[str] = None,
    ) -> bool:
        """
        发送数据保留期即将结束通知

        Args:
            telegram_user_id: 用户 Telegram ID
            tenant_name: 租户名称
            days_remaining: 保留期剩余天数
            renew_url: 续费链接

        Returns:
            是否发送成功
        """
        text = f"""
⚠️ <b>最后通知</b>

您的租户「<b>{tenant_name}</b>」数据保留期将在 <b>{days_remaining}</b> 天后结束。

保留期结束后，数据将被标记为待清理。
这是最后的恢复机会！
"""

        buttons = []
        if renew_url:
            buttons.append([
                InlineKeyboardButton(text="💳 立即恢复", url=renew_url)
            ])

        reply_markup = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
        return await self.send_message(telegram_user_id, text, reply_markup)

    # ==================== 订单通知 ====================

    async def send_payment_success(
        self,
        telegram_user_id: int,
        order_no: str,
        amount: str,
        currency: str,
        product_name: str,
    ) -> bool:
        """
        发送支付成功通知

        Args:
            telegram_user_id: 用户 Telegram ID
            order_no: 订单号
            amount: 金额
            currency: 币种
            product_name: 商品名称

        Returns:
            是否发送成功
        """
        text = f"""
✅ <b>支付成功</b>

订单号：<code>{order_no}</code>
商品：{product_name}
金额：{amount} {currency}

正在为您发货，请稍候...
"""

        return await self.send_message(telegram_user_id, text)

    async def send_delivery_completed(
        self,
        telegram_user_id: int,
        order_no: str,
        delivery_content: str,
        delivery_type: str,
    ) -> bool:
        """
        发送发货完成通知

        Args:
            telegram_user_id: 用户 Telegram ID
            order_no: 订单号
            delivery_content: 发货内容
            delivery_type: 发货类型

        Returns:
            是否发送成功
        """
        text = f"""
📦 <b>发货完成</b>

订单号：<code>{order_no}</code>

{delivery_content}

请妥善保管，如有问题请联系客服。
"""

        return await self.send_message(telegram_user_id, text)

    async def close(self):
        """关闭 Bot 会话"""
        if self._bot:
            await self._bot.session.close()
