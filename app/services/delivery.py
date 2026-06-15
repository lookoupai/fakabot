from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from typing import Any

from aiogram import Bot

from app.config import Settings
from app.services.files import DownloadTokenService
from app.services.payments import DeliveryInstruction
from app.services.token_crypto import TokenCrypto


async def send_delivery_instruction(
    bot: Bot,
    settings: Settings,
    crypto: TokenCrypto,
    instruction: DeliveryInstruction,
) -> None:
    text = await build_delivery_text(bot, settings, crypto, instruction)
    await bot.send_message(
        instruction.buyer_telegram_user_id,
        text,
        parse_mode="HTML",
    )


async def build_delivery_text(
    bot: Any,
    settings: Settings,
    crypto: TokenCrypto,
    instruction: DeliveryInstruction,
) -> str:
    if instruction.delivery_type in {"card_pool", "card_fixed"}:
        if instruction.encrypted_content is None:
            raise ValueError("缺少卡密内容")
        content = crypto.decrypt_token(instruction.encrypted_content)
        return (
            "支付成功，已自动发货。\n\n"
            f"订单号：{html.escape(instruction.out_trade_no)}\n"
            f"卡密：<code>{html.escape(content)}</code>"
        )
    if instruction.delivery_type == "file_download":
        if instruction.uploaded_file_id is None:
            raise ValueError("缺少文件 ID")
        token = DownloadTokenService(settings).create_token(
            tenant_id=instruction.uploaded_file_tenant_id or instruction.tenant_id,
            uploaded_file_id=instruction.uploaded_file_id,
            order_id=instruction.order_id,
        )
        download_url = f"{settings.public_base_url}/files/download/{token}"
        return (
            "支付成功，文件下载链接已生成。\n\n"
            f"订单号：{html.escape(instruction.out_trade_no)}\n"
            "有效期：1 小时\n"
            f"下载链接：{html.escape(download_url)}"
        )
    if instruction.delivery_type == "telegram_invite":
        if instruction.telegram_chat_id is None:
            raise ValueError("缺少群 ID")
        invite_link = await bot.create_chat_invite_link(
            chat_id=instruction.telegram_chat_id,
            expire_date=datetime.now(timezone.utc) + timedelta(hours=1),
            member_limit=1,
        )
        return (
            "支付成功，群邀请链接已生成。\n\n"
            f"订单号：{html.escape(instruction.out_trade_no)}\n"
            "有效期：1 小时｜限 1 人加入\n"
            f"邀请链接：{html.escape(invite_link.invite_link)}"
        )
    raise ValueError("不支持的发货类型")
