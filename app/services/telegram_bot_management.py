"""
Telegram Bot 管理服务

用于管理 Telegram Bot 的 Webhook、配置等。
"""
from __future__ import annotations

import logging
from typing import Optional

from aiogram import Bot
from aiogram.types import BotCommand

logger = logging.getLogger(__name__)


class TelegramBotManagementService:
    """Telegram Bot 管理服务"""

    @staticmethod
    async def set_webhook(
        bot_token: str,
        webhook_url: str,
        webhook_secret: Optional[str] = None,
        drop_pending_updates: bool = False,
    ) -> bool:
        """
        设置 Bot Webhook

        Args:
            bot_token: Bot Token
            webhook_url: Webhook URL
            webhook_secret: Webhook Secret（用于验证回调）
            drop_pending_updates: 是否丢弃待处理的更新

        Returns:
            bool: 是否设置成功

        Raises:
            Exception: 设置失败
        """
        try:
            bot = Bot(token=bot_token)

            result = await bot.set_webhook(
                url=webhook_url,
                secret_token=webhook_secret,
                drop_pending_updates=drop_pending_updates,
            )

            await bot.session.close()

            logger.info(f"Webhook set successfully: {webhook_url}")
            return result

        except Exception as e:
            logger.error(f"Failed to set webhook: {e}")
            raise

    @staticmethod
    async def delete_webhook(
        bot_token: str,
        drop_pending_updates: bool = False,
    ) -> bool:
        """
        删除 Bot Webhook

        Args:
            bot_token: Bot Token
            drop_pending_updates: 是否丢弃待处理的更新

        Returns:
            bool: 是否删除成功

        Raises:
            Exception: 删除失败
        """
        try:
            bot = Bot(token=bot_token)

            result = await bot.delete_webhook(
                drop_pending_updates=drop_pending_updates,
            )

            await bot.session.close()

            logger.info("Webhook deleted successfully")
            return result

        except Exception as e:
            logger.error(f"Failed to delete webhook: {e}")
            raise

    @staticmethod
    async def get_webhook_info(bot_token: str) -> dict:
        """
        获取 Webhook 信息

        Args:
            bot_token: Bot Token

        Returns:
            dict: Webhook 信息
                - url: Webhook URL
                - has_custom_certificate: 是否使用自定义证书
                - pending_update_count: 待处理更新数量
                - last_error_date: 最后错误时间
                - last_error_message: 最后错误信息

        Raises:
            Exception: 获取失败
        """
        try:
            bot = Bot(token=bot_token)

            info = await bot.get_webhook_info()

            await bot.session.close()

            return {
                "url": info.url,
                "has_custom_certificate": info.has_custom_certificate,
                "pending_update_count": info.pending_update_count,
                "last_error_date": info.last_error_date,
                "last_error_message": info.last_error_message,
            }

        except Exception as e:
            logger.error(f"Failed to get webhook info: {e}")
            raise

    @staticmethod
    async def set_my_commands(
        bot_token: str,
        commands: list[tuple[str, str]],
    ) -> bool:
        """
        设置 Bot 命令菜单

        Args:
            bot_token: Bot Token
            commands: 命令列表 [(command, description), ...]
                例如: [("start", "开始使用"), ("help", "帮助")]

        Returns:
            bool: 是否设置成功

        Raises:
            Exception: 设置失败
        """
        try:
            bot = Bot(token=bot_token)

            bot_commands = [
                BotCommand(command=cmd, description=desc)
                for cmd, desc in commands
            ]

            result = await bot.set_my_commands(bot_commands)

            await bot.session.close()

            logger.info(f"Bot commands set successfully: {len(commands)} commands")
            return result

        except Exception as e:
            logger.error(f"Failed to set bot commands: {e}")
            raise

    @staticmethod
    async def get_bot_info(bot_token: str) -> dict:
        """
        获取 Bot 信息

        Args:
            bot_token: Bot Token

        Returns:
            dict: Bot 信息
                - id: Bot ID
                - first_name: Bot 名称
                - username: Bot 用户名
                - can_join_groups: 是否可以加入群组
                - can_read_all_group_messages: 是否可以读取所有群消息

        Raises:
            Exception: 获取失败
        """
        try:
            bot = Bot(token=bot_token)

            me = await bot.get_me()

            await bot.session.close()

            return {
                "id": me.id,
                "first_name": me.first_name,
                "username": me.username,
                "can_join_groups": me.can_join_groups,
                "can_read_all_group_messages": me.can_read_all_group_messages,
            }

        except Exception as e:
            logger.error(f"Failed to get bot info: {e}")
            raise

    @staticmethod
    async def clear_webhook_cache(redis_client, bot_id: int):
        """
        清理 Webhook 缓存

        清理 Redis 中与该 Bot 相关的缓存数据

        Args:
            redis_client: Redis 客户端
            bot_id: Bot ID

        Returns:
            int: 清理的缓存条目数
        """
        if redis_client is None:
            logger.warning("Redis client not available, skipping cache clear")
            return 0

        try:
            # 清理可能的缓存键
            cache_patterns = [
                f"bot:{bot_id}:*",
                f"webhook:{bot_id}:*",
                f"update:{bot_id}:*",
            ]

            count = 0
            for pattern in cache_patterns:
                keys = await redis_client.keys(pattern)
                if keys:
                    count += await redis_client.delete(*keys)

            logger.info(f"Cleared {count} cache entries for bot {bot_id}")
            return count

        except Exception as e:
            logger.error(f"Failed to clear webhook cache: {e}")
            return 0
