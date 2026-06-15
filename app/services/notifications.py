from __future__ import annotations

import html
import logging
from datetime import datetime

from sqlalchemy import select

from app.bots.factory import create_bot
from app.config import Settings
from app.db.models.tenants import PlatformUser
from app.db.repos.tenants import TenantRepository
from app.db.session import get_session_factory
from app.services.ledger import WithdrawalSummary
from app.services.supply import ResellerApplicationSummary
from app.services.token_crypto import TokenCrypto

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def notify_subscription_expiring(self, tenant_id: int, period_ends_at: datetime) -> None:
        text = (
            "订阅即将到期\n\n"
            f"到期时间：{period_ends_at:%Y-%m-%d %H:%M:%S %Z}\n\n"
            "续费：/renew_subscription 1"
        )
        await self._send_tenant_owner_message(
            tenant_id=tenant_id,
            text=text,
            log_label="subscription expiry notification",
        )

    async def notify_withdrawal_requested(self, withdrawal: WithdrawalSummary) -> None:
        if self._settings.master_bot_token is None or not self._settings.platform_admin_ids:
            return
        text = (
            "新的提现申请\n\n"
            f"提现 ID：#{withdrawal.withdrawal_id}\n"
            f"租户 ID：{withdrawal.tenant_id}\n"
            f"金额：{withdrawal.amount} {withdrawal.currency}\n"
            f"网络：{html.escape(withdrawal.network)}\n"
            f"地址：{html.escape(_mask_address(withdrawal.address))}\n\n"
            f"完成：/complete_withdrawal {withdrawal.withdrawal_id} | 打款流水 | 凭证链接或 - | 备注\n"
            f"拒绝：/reject_withdrawal {withdrawal.withdrawal_id} | 备注"
        )
        bot = create_bot(self._settings.master_bot_token.get_secret_value())
        try:
            for admin_id in self._settings.platform_admin_ids:
                await bot.send_message(admin_id, text)
        except Exception:
            logger.exception("withdrawal request notification failed")
        finally:
            await bot.session.close()

    async def notify_withdrawal_reviewed(self, withdrawal: WithdrawalSummary) -> None:
        try:
            async with get_session_factory()() as session:
                tenant = await TenantRepository().get_tenant(session, withdrawal.tenant_id)
                tenant_bot = await TenantRepository().get_active_bot_by_tenant_id(session, withdrawal.tenant_id)
                owner_telegram_user_id = None
                if tenant is not None:
                    owner_telegram_user_id = await session.scalar(
                        select(PlatformUser.telegram_user_id).where(PlatformUser.id == tenant.owner_user_id)
                    )
            if tenant is None or tenant_bot is None:
                return
            token = TokenCrypto(self._settings).decrypt_token(tenant_bot.encrypted_token)
        except Exception:
            logger.exception("withdrawal review notification setup failed")
            return

        status_text = "已完成" if withdrawal.status == "completed" else "已拒绝"
        text = (
            f"提现审核{status_text}\n\n"
            f"提现 ID：#{withdrawal.withdrawal_id}\n"
            f"金额：{withdrawal.amount} {withdrawal.currency}\n"
            f"网络：{html.escape(withdrawal.network)}\n"
            f"地址：{html.escape(_mask_address(withdrawal.address))}"
        )
        if withdrawal.payout_reference:
            text += f"\n打款流水：{html.escape(withdrawal.payout_reference)}"
        if withdrawal.payout_proof_url:
            text += f"\n凭证链接：{html.escape(withdrawal.payout_proof_url)}"
        bot = create_bot(token)
        try:
            if owner_telegram_user_id is not None:
                await bot.send_message(owner_telegram_user_id, text)
        except Exception:
            logger.exception("withdrawal review notification failed")
        finally:
            await bot.session.close()

    async def notify_reseller_application_requested(self, application: ResellerApplicationSummary) -> None:
        text = (
            "新的代理申请\n\n"
            f"供货 ID：#{application.supplier_offer_id}\n"
            f"商品：{html.escape(application.product_name)}\n"
            f"代理租户：#{application.reseller_tenant_id} {html.escape(application.reseller_store_name)}\n"
            f"默认成本：{application.pricing_value} {application.currency}\n"
            f"最低售价：{application.min_sale_price if application.min_sale_price is not None else '不限'}\n\n"
            f"通过：/approve_reseller {application.supplier_offer_id} | {application.reseller_tenant_id}\n"
            f"设置独立成本：/set_reseller_rule {application.supplier_offer_id} | "
            f"{application.reseller_tenant_id} | 成本 | 最低售价\n"
            f"拒绝：/reject_reseller {application.supplier_offer_id} | {application.reseller_tenant_id} | 原因"
        )
        await self._send_tenant_owner_message(
            tenant_id=application.supplier_tenant_id,
            text=text,
            log_label="reseller application notification",
        )

    async def notify_reseller_application_reviewed(self, application: ResellerApplicationSummary) -> None:
        status_labels = {
            "active": "已通过",
            "rejected": "已拒绝",
            "pending": "待审核",
        }
        text = (
            f"代理申请{status_labels.get(application.status, application.status)}\n\n"
            f"供货 ID：#{application.supplier_offer_id}\n"
            f"商品：{html.escape(application.product_name)}\n"
            f"供应商：#{application.supplier_tenant_id} {html.escape(application.supplier_store_name)}\n"
            f"供应商成本：{application.pricing_value} {application.currency}\n"
            f"最低售价：{application.min_sale_price if application.min_sale_price is not None else '不限'}"
        )
        if application.status == "active":
            text += f"\n\n上架：/resell_offer {application.supplier_offer_id} | 售价 | 展示名"
        await self._send_tenant_owner_message(
            tenant_id=application.reseller_tenant_id,
            text=text,
            log_label="reseller application review notification",
        )

    async def _send_tenant_owner_message(self, tenant_id: int, text: str, log_label: str) -> None:
        try:
            async with get_session_factory()() as session:
                tenant = await TenantRepository().get_tenant(session, tenant_id)
                tenant_bot = await TenantRepository().get_active_bot_by_tenant_id(session, tenant_id)
                owner_telegram_user_id = None
                if tenant is not None:
                    owner_telegram_user_id = await session.scalar(
                        select(PlatformUser.telegram_user_id).where(PlatformUser.id == tenant.owner_user_id)
                    )
            if tenant is None or tenant_bot is None or owner_telegram_user_id is None:
                return
            token = TokenCrypto(self._settings).decrypt_token(tenant_bot.encrypted_token)
        except Exception:
            logger.exception("%s setup failed", log_label)
            return

        bot = create_bot(token)
        try:
            await bot.send_message(owner_telegram_user_id, text)
        except Exception:
            logger.exception("%s failed", log_label)
        finally:
            await bot.session.close()


def _mask_address(value: str) -> str:
    if len(value) <= 12:
        return "***"
    return f"{value[:6]}***{value[-6:]}"
