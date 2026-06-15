from __future__ import annotations

import hashlib
import html
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Tuple

import redis.asyncio as redis
from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bots.filters import BotRoleFilter
from app.bots.factory import create_bot
from app.config import Settings
from app.db.repos.tenants import TenantRepository
from app.services.audit import AuditLogService, AuditLogSummary
from app.services.admin_web import AdminWebBindingCodeError, AdminWebBindingCodeStore, AdminWebService
from app.services.ledger import LedgerService, RefundResult, SettlementPolicySummary, WithdrawalSummary
from app.services.notifications import NotificationService
from app.services.reports import ExportJobSummary, ReportExportService
from app.services.risk import AfterSaleSummary, DisputeSummary, RiskActionResult, RiskControlService
from app.services.subscriptions import SubscriptionAdjustmentResult, SubscriptionService
from app.services.token_crypto import TokenCrypto, generate_webhook_secret

router = Router(name="master")
router.message.filter(BotRoleFilter("master"))
logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"^\d{8,12}:[A-Za-z0-9_-]{35,}$")
TENANT_WEBHOOK_ALLOWED_UPDATES = ["message", "callback_query"]


@router.message(Command("start"))
async def master_start(message: Message) -> None:
    await message.answer(
        "多租户发卡平台\n\n"
        "发送你从 @BotFather 获取的 Bot Token，我会验证 Token、加密保存并设置 Webhook。\n"
        "绑定成功后首月免费，后续订阅规则以平台配置为准。\n\n"
        "命令：\n"
        "/mybots 查看已绑定机器人\n"
        "/admin_web_code 生成网页管理后台一次性绑定码\n"
        "/reset_webhook BotID 重置租户 Bot Webhook\n"
        "/deactivate_bot BotID 停用租户 Bot"
    )


@router.message(Command("mybots"))
async def my_bots(message: Message, settings: Settings, session_factory: async_sessionmaker[AsyncSession]) -> None:
    if message.from_user is None:
        await message.answer("无法识别当前用户。")
        return

    repo = TenantRepository()
    async with session_factory() as session:
        user = await repo.get_or_create_platform_user(session, message.from_user, settings)
        bots = await repo.list_owner_bots(session, user.id)
        await session.commit()

    if not bots:
        await message.answer("你还没有绑定机器人。发送 Bot Token 即可创建。")
        return

    lines = ["已绑定机器人："]
    lines.extend(f"- ID {bot.id}｜@{bot.bot_username}：{bot.status}" for bot in bots)
    lines.append("\n网页后台：/admin_web_code BotID")
    lines.append("维护：/reset_webhook BotID 或 /deactivate_bot BotID")
    await message.answer("\n".join(lines))


@router.message(Command("admin_web_code"))
async def admin_web_code(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: object | None = None,
) -> None:
    if message.from_user is None:
        await message.answer("无法识别当前用户。")
        return
    if redis_client is None:
        await message.answer("绑定码服务暂不可用，请稍后再试。")
        return

    tenant_bot_id = _parse_optional_tenant_bot_id(command.args or "")
    repo = TenantRepository()
    current_workspace_id: Optional[str] = None
    workspace_title: Optional[str] = None
    async with session_factory() as session:
        owner = await repo.get_or_create_platform_user(session, message.from_user, settings)
        if tenant_bot_id is not None:
            tenant_bot = await repo.get_owner_bot(session, owner.id, tenant_bot_id)
            if tenant_bot is None:
                await message.answer("没有找到该 Bot，或你不是它的 owner。")
                return
            current_workspace_id = tenant_bot.tenant.public_id if getattr(tenant_bot, "tenant", None) else None
            if not current_workspace_id:
                await message.answer("该 Bot 缺少网页工作区标识。")
                return
            workspace_title = tenant_bot.tenant.store_name if getattr(tenant_bot, "tenant", None) else None
            if not workspace_title:
                workspace_title = f"@{tenant_bot.bot_username}"
        else:
            workspaces = await AdminWebService().list_workspaces(session, message.from_user.id)
            if not workspaces:
                await message.answer("当前账号没有可进入的网页管理工作区。")
                return
            selected_workspace = workspaces[0]
            current_workspace_id = selected_workspace.workspace_id
            workspace_title = selected_workspace.title
        await session.commit()

    try:
        grant = await AdminWebBindingCodeStore(settings, redis_client).issue_code(
            telegram_user_id=message.from_user.id,
            current_workspace_id=current_workspace_id,
        )
    except AdminWebBindingCodeError as exc:
        await message.answer(str(exc))
        return

    await message.answer(
        _format_admin_web_binding_code(
            grant.code,
            grant.expires_in_seconds,
            workspace_title or "当前工作区",
        )
    )


@router.message(Command("reset_webhook"))
async def reset_webhook(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if message.from_user is None:
        await message.answer("无法识别当前用户。")
        return
    try:
        tenant_bot_id = _parse_tenant_bot_id(command.args or "", "/reset_webhook 1")
    except ValueError as exc:
        await message.answer(str(exc))
        return

    repo = TenantRepository()
    candidate_bot: Optional[Bot] = None
    old_webhook_secret: Optional[str] = None
    new_webhook_secret: Optional[str] = None
    try:
        async with session_factory() as session:
            owner = await repo.get_or_create_platform_user(session, message.from_user, settings)
            tenant_bot = await repo.get_owner_bot(session, owner.id, tenant_bot_id)
            if tenant_bot is None:
                await message.answer("没有找到该 Bot，或你不是它的 owner。")
                return
            if tenant_bot.status != "active":
                await message.answer("只有 active 状态的 Bot 可以重置 Webhook。")
                return

            old_webhook_secret = tenant_bot.webhook_secret
            new_webhook_secret = generate_webhook_secret()
            tenant_bot = await repo.rotate_owner_bot_webhook(
                session=session,
                owner_user_id=owner.id,
                tenant_bot_id=tenant_bot_id,
                webhook_secret=new_webhook_secret,
            )
            if tenant_bot is None:
                await message.answer("没有找到该 Bot，或你不是它的 owner。")
                return

            token = TokenCrypto(settings).decrypt_token(tenant_bot.encrypted_token)
            candidate_bot = create_bot(token)
            webhook_url = f"{settings.public_base_url}{settings.webhook_base_path}/{new_webhook_secret}"
            await candidate_bot.set_webhook(
                webhook_url,
                allowed_updates=TENANT_WEBHOOK_ALLOWED_UPDATES,
                drop_pending_updates=True,
            )
            await session.commit()
    except RuntimeError as exc:
        await message.answer(str(exc))
        return
    except Exception as exc:
        await message.answer(f"Webhook 重置失败：{type(exc).__name__}")
        return
    finally:
        if candidate_bot is not None:
            await candidate_bot.session.close()

    await _delete_tenant_webhook_cache(settings, old_webhook_secret, new_webhook_secret)
    await message.answer(f"Webhook 已重置：Bot ID {tenant_bot_id}。")


@router.message(Command("deactivate_bot"))
async def deactivate_bot(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if message.from_user is None:
        await message.answer("无法识别当前用户。")
        return
    try:
        tenant_bot_id = _parse_tenant_bot_id(command.args or "", "/deactivate_bot 1")
    except ValueError as exc:
        await message.answer(str(exc))
        return

    repo = TenantRepository()
    candidate_bot: Optional[Bot] = None
    webhook_secret: Optional[str] = None
    try:
        async with session_factory() as session:
            owner = await repo.get_or_create_platform_user(session, message.from_user, settings)
            tenant_bot = await repo.get_owner_bot(session, owner.id, tenant_bot_id)
            if tenant_bot is None:
                await message.answer("没有找到该 Bot，或你不是它的 owner。")
                return
            if tenant_bot.status != "active":
                await message.answer("该 Bot 已不是 active 状态。")
                return

            webhook_secret = tenant_bot.webhook_secret
            tenant_bot = await repo.deactivate_owner_bot(
                session=session,
                owner_user_id=owner.id,
                tenant_bot_id=tenant_bot_id,
            )
            if tenant_bot is None:
                await message.answer("没有找到该 Bot，或你不是它的 owner。")
                return

            token = TokenCrypto(settings).decrypt_token(tenant_bot.encrypted_token)
            candidate_bot = create_bot(token)
            await candidate_bot.delete_webhook(drop_pending_updates=True)
            await session.commit()
    except RuntimeError as exc:
        await message.answer(str(exc))
        return
    except Exception as exc:
        await message.answer(f"停用失败：{type(exc).__name__}")
        return
    finally:
        if candidate_bot is not None:
            await candidate_bot.session.close()

    await _delete_tenant_webhook_cache(settings, webhook_secret)
    await message.answer(f"Bot 已停用：Bot ID {tenant_bot_id}。")


@router.message(Command("pending_withdrawals"))
async def pending_withdrawals(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以查看提现申请。")
        return

    try:
        limit = _parse_limit(command.args or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return

    async with session_factory() as session:
        withdrawals = await LedgerService().list_pending_withdrawals(session, limit=limit)

    if not withdrawals:
        await message.answer("暂无待审核提现申请。")
        return

    lines = ["待审核提现申请"]
    lines.extend(_format_withdrawal_summary(withdrawal) for withdrawal in withdrawals)
    await message.answer("\n\n".join(lines))


@router.message(Command("withdrawals"))
async def withdrawals(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以查看提现记录。")
        return

    try:
        limit = _parse_limit(command.args or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return

    async with session_factory() as session:
        withdrawal_records = await LedgerService().list_withdrawals(session, limit=limit)

    if not withdrawal_records:
        await message.answer("暂无提现记录。")
        return

    lines = ["提现记录"]
    lines.extend(_format_withdrawal_audit(withdrawal) for withdrawal in withdrawal_records)
    await message.answer("\n\n".join(lines))


@router.message(Command("audit_logs"))
async def audit_logs(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以查看审计日志。")
        return
    try:
        tenant_id, limit = _parse_audit_args(command.args or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return
    async with session_factory() as session:
        logs = await AuditLogService().list_platform_audit_logs(session, tenant_id=tenant_id, limit=limit)
    title = f"平台审计日志｜租户 {tenant_id}" if tenant_id is not None else "平台审计日志"
    await message.answer(_format_audit_logs(logs, title, include_tenant=True))


@router.message(Command("platform_fee"))
async def platform_fee(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以查看平台手续费策略。")
        return

    try:
        tenant_id = _parse_optional_tenant_id(command.args or "", "platform_fee")
        async with session_factory() as session:
            policy = await LedgerService().get_effective_settlement_policy(session, tenant_id=tenant_id)
    except ValueError as exc:
        await message.answer(str(exc))
        return

    title = f"租户 {tenant_id} 有效手续费策略" if tenant_id is not None else "平台默认手续费策略"
    await message.answer(_format_settlement_policy(title, policy))


@router.message(Command("set_platform_fee"))
async def set_platform_fee(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以设置平台默认手续费。")
        return

    try:
        enabled, percent = _parse_platform_fee_args(command.args or "", "set_platform_fee")
        policy = await _run_platform_fee_update(
            message=message,
            settings=settings,
            session_factory=session_factory,
            enabled=enabled,
            percent=percent,
            tenant_id=None,
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(_format_settlement_policy("平台默认手续费已更新", policy))


@router.message(Command("set_tenant_platform_fee"))
async def set_tenant_platform_fee(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以设置租户手续费。")
        return

    try:
        tenant_id, enabled, percent = _parse_tenant_platform_fee_args(command.args or "")
        policy = await _run_platform_fee_update(
            message=message,
            settings=settings,
            session_factory=session_factory,
            enabled=enabled,
            percent=percent,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(_format_settlement_policy(f"租户 {tenant_id} 手续费已更新", policy))


@router.message(Command("grant_tenant_subscription_days"))
async def grant_tenant_subscription_days(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以调整租户订阅。")
        return

    try:
        tenant_id, days, reason = _parse_grant_subscription_days_args(command.args or "")
        result = await _run_subscription_days_grant(
            message=message,
            settings=settings,
            session_factory=session_factory,
            tenant_id=tenant_id,
            days=days,
            reason=reason,
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(_format_subscription_adjustment("租户订阅已延长", result))


@router.message(Command("set_tenant_subscription_until"))
async def set_tenant_subscription_until(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以调整租户订阅。")
        return

    try:
        tenant_id, period_ends_at, reason = _parse_set_subscription_until_args(command.args or "")
        result = await _run_subscription_until_update(
            message=message,
            settings=settings,
            session_factory=session_factory,
            tenant_id=tenant_id,
            period_ends_at=period_ends_at,
            reason=reason,
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(_format_subscription_adjustment("租户订阅到期时间已设置", result))


@router.message(Command("disable_supply_offer"))
async def disable_supply_offer(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以下架供货商品。")
        return

    try:
        supplier_offer_id, reason = _parse_target_reason_args(command.args or "", "disable_supply_offer", "供货 ID")
        result = await _run_risk_action(
            message=message,
            settings=settings,
            session_factory=session_factory,
            action_name="disable_supplier_offer",
            target_id=supplier_offer_id,
            reason=reason,
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(_format_risk_result("供货商品已下架", result))


@router.message(Command("disable_reseller_product"))
async def disable_reseller_product(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以下架代理商品。")
        return

    try:
        reseller_product_id, reason = _parse_target_reason_args(command.args or "", "disable_reseller_product", "代理商品 ID")
        result = await _run_risk_action(
            message=message,
            settings=settings,
            session_factory=session_factory,
            action_name="disable_reseller_product",
            target_id=reseller_product_id,
            reason=reason,
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(_format_risk_result("代理商品已下架", result))


@router.message(Command("ban_user"))
async def ban_user(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以封禁平台用户。")
        return

    try:
        telegram_user_id, reason = _parse_platform_user_risk_args(command.args or "", "ban_user")
        result = await _run_risk_action(
            message=message,
            settings=settings,
            session_factory=session_factory,
            action_name="ban_platform_user",
            target_id=telegram_user_id,
            reason=reason,
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(_format_risk_result("平台用户已封禁", result))


@router.message(Command("unban_user"))
async def unban_user(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以解封平台用户。")
        return

    try:
        telegram_user_id, reason = _parse_platform_user_risk_args(command.args or "", "unban_user")
        result = await _run_risk_action(
            message=message,
            settings=settings,
            session_factory=session_factory,
            action_name="unban_platform_user",
            target_id=telegram_user_id,
            reason=reason,
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(_format_risk_result("平台用户已解封", result))


@router.message(Command("suspend_tenant"))
async def suspend_tenant(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以冻结租户。")
        return

    try:
        tenant_id, reason = _parse_target_reason_args(command.args or "", "suspend_tenant", "租户 ID")
        result = await _run_risk_action(
            message=message,
            settings=settings,
            session_factory=session_factory,
            action_name="suspend_tenant",
            target_id=tenant_id,
            reason=reason,
        )
        await _clear_tenant_webhook_cache(settings, result)
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(_format_risk_result("租户已冻结", result))


@router.message(Command("resume_tenant"))
async def resume_tenant(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以恢复租户。")
        return

    try:
        tenant_id, reason = _parse_target_reason_args(command.args or "", "resume_tenant", "租户 ID")
        result = await _run_risk_action(
            message=message,
            settings=settings,
            session_factory=session_factory,
            action_name="resume_tenant",
            target_id=tenant_id,
            reason=reason,
        )
        await _clear_tenant_webhook_cache(settings, result)
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(_format_risk_result("租户已恢复", result))


@router.message(Command("open_dispute"))
async def open_dispute(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以创建订单争议。")
        return

    try:
        out_trade_no, reason = _parse_order_note_args(command.args or "", "open_dispute", "争议原因")
        dispute = await _run_dispute_action(
            message=message,
            settings=settings,
            session_factory=session_factory,
            action_name="open_dispute",
            target=out_trade_no,
            note=reason,
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(_format_dispute_result("争议已创建", dispute))


@router.message(Command("review_dispute"))
async def review_dispute(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以处理订单争议。")
        return

    try:
        dispute_id, note = _parse_dispute_note_args(command.args or "", "review_dispute", "处理备注")
        dispute = await _run_dispute_action(
            message=message,
            settings=settings,
            session_factory=session_factory,
            action_name="review_dispute",
            target=dispute_id,
            note=note,
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(_format_dispute_result("争议已进入处理中", dispute))


@router.message(Command("close_dispute"))
async def close_dispute(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以关闭订单争议。")
        return

    try:
        dispute_id, status, resolution = _parse_close_dispute_args(command.args or "")
        dispute = await _run_dispute_close_action(
            message=message,
            settings=settings,
            session_factory=session_factory,
            dispute_id=dispute_id,
            status=status,
            resolution=resolution,
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(_format_dispute_result("争议已关闭", dispute))


@router.message(Command("disputes"))
async def disputes(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以查看订单争议。")
        return

    try:
        tenant_id, status, limit = _parse_disputes_args(command.args or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return

    async with session_factory() as session:
        dispute_records = await RiskControlService().list_disputes(
            session=session,
            tenant_id=tenant_id,
            status=status,
            limit=limit,
        )

    await message.answer(_format_disputes(dispute_records, tenant_id, status))


@router.message(Command("open_after_sale"))
async def open_after_sale(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以创建售后工单。")
        return

    try:
        out_trade_no, case_type, requested_amount, reason = _parse_open_after_sale_args(command.args or "")
        after_sale = await _run_after_sale_open_action(
            message=message,
            settings=settings,
            session_factory=session_factory,
            out_trade_no=out_trade_no,
            case_type=case_type,
            requested_amount=requested_amount,
            reason=reason,
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(_format_after_sale_result("售后工单已创建", after_sale))


@router.message(Command("review_after_sale"))
async def review_after_sale(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以处理售后工单。")
        return

    try:
        case_id, note = _parse_after_sale_note_args(command.args or "", "review_after_sale", "处理备注")
        after_sale = await _run_after_sale_action(
            message=message,
            settings=settings,
            session_factory=session_factory,
            action_name="review_after_sale",
            case_id=case_id,
            note=note,
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(_format_after_sale_result("售后工单已进入处理中", after_sale))


@router.message(Command("refund_after_sale"))
async def refund_after_sale(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以执行售后退款。")
        return

    try:
        case_id, amount, note = _parse_refund_after_sale_args(command.args or "")
        after_sale = await _run_after_sale_refund_action(
            message=message,
            settings=settings,
            session_factory=session_factory,
            case_id=case_id,
            amount=amount,
            note=note,
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(_format_after_sale_result("售后退款已完成", after_sale))


@router.message(Command("close_after_sale"))
async def close_after_sale(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以关闭售后工单。")
        return

    try:
        case_id, status, resolution = _parse_close_after_sale_args(command.args or "")
        after_sale = await _run_after_sale_close_action(
            message=message,
            settings=settings,
            session_factory=session_factory,
            case_id=case_id,
            status=status,
            resolution=resolution,
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(_format_after_sale_result("售后工单已关闭", after_sale))


@router.message(Command("after_sales"))
async def after_sales(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以查看售后工单。")
        return

    try:
        tenant_id, status, limit = _parse_after_sales_args(command.args or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return

    async with session_factory() as session:
        after_sale_records = await RiskControlService().list_after_sales(
            session=session,
            tenant_id=tenant_id,
            status=status,
            limit=limit,
        )

    await message.answer(_format_after_sales(after_sale_records, tenant_id, status))


@router.message(Command("complete_withdrawal"))
async def complete_withdrawal(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以完成提现审核。")
        return

    try:
        withdrawal_id, payout_reference, payout_proof_url, note = _parse_complete_withdrawal_args(command.args or "")
        async with session_factory() as session:
            if message.from_user is None:
                raise ValueError("无法识别当前用户。")
            actor = await TenantRepository().get_or_create_platform_user(session, message.from_user, settings)
            withdrawal = await LedgerService().complete_withdrawal(
                session,
                withdrawal_id,
                note,
                actor_user_id=actor.id,
                payout_reference=payout_reference,
                payout_proof_url=payout_proof_url,
            )
            await session.commit()
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(
        "提现已标记完成。\n\n"
        f"提现 ID：#{withdrawal.id}\n"
        f"租户 ID：{withdrawal.tenant_id}\n"
        f"金额：{withdrawal.amount} {withdrawal.currency}"
    )
    await NotificationService(settings).notify_withdrawal_reviewed(_withdrawal_summary_from_model(withdrawal))


@router.message(Command("reject_withdrawal"))
async def reject_withdrawal(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以拒绝提现申请。")
        return

    try:
        withdrawal_id, note = _parse_review_args(command.args or "", "reject_withdrawal")
        async with session_factory() as session:
            if message.from_user is None:
                raise ValueError("无法识别当前用户。")
            actor = await TenantRepository().get_or_create_platform_user(session, message.from_user, settings)
            withdrawal = await LedgerService().reject_withdrawal(
                session,
                withdrawal_id,
                note,
                actor_user_id=actor.id,
            )
            await session.commit()
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(
        "提现已拒绝，冻结余额已退回可用余额。\n\n"
        f"提现 ID：#{withdrawal.id}\n"
        f"租户 ID：{withdrawal.tenant_id}\n"
        f"金额：{withdrawal.amount} {withdrawal.currency}"
    )
    await NotificationService(settings).notify_withdrawal_reviewed(_withdrawal_summary_from_model(withdrawal))


@router.message(Command("refund_order"))
async def refund_order(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以执行平台托管订单退款。")
        return

    try:
        out_trade_no, amount, reason = _parse_refund_args(command.args or "")
        async with session_factory() as session:
            refund = await LedgerService().refund_platform_order(
                session,
                out_trade_no,
                reason,
                amount=amount,
                idempotency_key=_manual_refund_key(message, out_trade_no, amount),
            )
            await session.commit()
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(_format_refund_result(refund))


@router.message(Command("export_report"))
async def export_report(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以创建报表导出任务。")
        return
    if message.from_user is None:
        await message.answer("无法识别当前用户。")
        return
    try:
        tenant_id, scope_type, report_type = _parse_master_export_report_args(command.args or "")
        async with session_factory() as session:
            actor = await TenantRepository().get_or_create_platform_user(session, message.from_user, settings)
            job = await ReportExportService().create_export_job(
                session=session,
                settings=settings,
                report_type=report_type,
                actor_user_id=actor.id,
                tenant_id=tenant_id,
                scope_type=scope_type,
            )
            await session.commit()
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await message.answer(_format_export_job_created(job, include_tenant=True))


@router.message(Command("export_jobs"))
async def export_jobs(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if not _ensure_platform_admin(message, settings):
        await message.answer("无权限。只有平台管理员可以查看报表导出任务。")
        return
    try:
        tenant_id, include_all_tenants, limit = _parse_master_export_jobs_args(command.args or "")
        async with session_factory() as session:
            jobs = await ReportExportService().list_export_jobs(
                session=session,
                settings=settings,
                tenant_id=tenant_id,
                limit=limit,
                include_all_tenants=include_all_tenants,
            )
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await message.answer(_format_export_jobs(jobs, include_tenant=True))


@router.message()
async def bind_token(
    message: Message,
    bot: Bot,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if message.from_user is None or not message.text:
        await message.answer("请发送 BotFather 提供的 Bot Token。")
        return

    raw_token = message.text.strip()
    if not _TOKEN_RE.match(raw_token):
        await message.answer("Token 格式不正确。请发送完整 Bot Token。")
        return

    try:
        await message.delete()
    except Exception:
        await message.answer("请在绑定完成后手动删除包含 Token 的消息。")

    crypto = TokenCrypto(settings)
    repo = TenantRepository()
    candidate_bot = create_bot(raw_token)
    try:
        me = await candidate_bot.get_me()
        token_hash = crypto.token_hash(raw_token)
        webhook_secret = generate_webhook_secret()
        webhook_url = f"{settings.public_base_url}{settings.webhook_base_path}/{webhook_secret}"

        async with session_factory() as session:
            owner = await repo.get_or_create_platform_user(session, message.from_user, settings)
            if await repo.token_hash_exists(session, token_hash):
                await session.rollback()
                await bot.send_message(message.chat.id, "这个 Bot Token 已经绑定过。")
                return

            tenant_bot = await repo.create_tenant_with_bot(
                session=session,
                owner=owner,
                bot_user_id=me.id,
                bot_username=me.username or str(me.id),
                encrypted_token=crypto.encrypt_token(raw_token),
                token_hash=token_hash,
                webhook_secret=webhook_secret,
            )
            await SubscriptionService().bootstrap_tenant_subscription(
                session=session,
                tenant_id=tenant_bot.tenant_id,
                monthly_price=settings.subscription_monthly_price,
            )
            await candidate_bot.set_webhook(
                webhook_url,
                allowed_updates=TENANT_WEBHOOK_ALLOWED_UPDATES,
                drop_pending_updates=True,
            )
            await session.commit()

        await bot.send_message(
            message.chat.id,
            f"绑定成功：@{me.username or me.id}\n"
            f"租户 Bot ID：{tenant_bot.id}\n"
            "现在向该机器人发送 /start 即可验证租户路由。",
        )
    except Exception as exc:
        await bot.send_message(message.chat.id, f"绑定失败：{type(exc).__name__}")
    finally:
        await candidate_bot.session.close()


def _ensure_platform_admin(message: Message, settings: Settings) -> bool:
    return message.from_user is not None and message.from_user.id in settings.platform_admin_ids


def _parse_limit(raw_args: str) -> int:
    value = raw_args.strip()
    if not value:
        return 20
    try:
        limit = int(value)
    except ValueError:
        raise ValueError("数量必须是数字。示例：/pending_withdrawals 20")
    return min(max(limit, 1), 100)


def _parse_tenant_bot_id(raw_args: str, usage: str) -> int:
    value = raw_args.strip()
    if not value:
        raise ValueError(f"请提供 Bot ID。示例：{usage}")
    try:
        tenant_bot_id = int(value)
    except ValueError as exc:
        raise ValueError(f"Bot ID 必须是整数。示例：{usage}") from exc
    if tenant_bot_id <= 0:
        raise ValueError("Bot ID 必须大于 0。")
    return tenant_bot_id


def _parse_optional_tenant_bot_id(raw_args: str) -> Optional[int]:
    value = raw_args.strip()
    if not value:
        return None
    return _parse_tenant_bot_id(value, "/admin_web_code 1")


def _parse_audit_args(raw_args: str) -> Tuple[Optional[int], int]:
    value = raw_args.strip()
    if not value:
        return None, 20
    if "|" not in value:
        try:
            limit = int(value)
        except ValueError:
            raise ValueError("格式错误。示例：/audit_logs 20 或 /audit_logs 租户ID | 20")
        return None, min(max(limit, 1), 100)
    parts = [part.strip() for part in value.split("|", 1)]
    if not parts[0]:
        raise ValueError("租户 ID 不能为空。示例：/audit_logs 1 | 20")
    try:
        tenant_id = int(parts[0])
    except ValueError:
        raise ValueError("租户 ID 必须是数字。")
    if tenant_id <= 0:
        raise ValueError("租户 ID 必须大于 0。")
    limit = _parse_limit(parts[1] if len(parts) == 2 else "")
    return tenant_id, limit


def _parse_optional_tenant_id(raw_args: str, command_name: str) -> Optional[int]:
    value = raw_args.strip()
    if not value:
        return None
    try:
        tenant_id = int(value)
    except ValueError:
        raise ValueError(f"租户 ID 必须是数字。示例：/{command_name} 或 /{command_name} 1")
    if tenant_id <= 0:
        raise ValueError("租户 ID 必须大于 0。")
    return tenant_id


def _parse_platform_fee_args(raw_args: str, command_name: str) -> Tuple[bool, Decimal]:
    parts = [part.strip() for part in raw_args.split("|", 1)]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"格式错误。示例：/{command_name} on | 1 或 /{command_name} off | 1")
    enabled = _parse_on_off(parts[0])
    return enabled, _parse_fee_percent(parts[1])


def _parse_tenant_platform_fee_args(raw_args: str) -> Tuple[int, bool, Decimal]:
    parts = [part.strip() for part in raw_args.split("|", 2)]
    if len(parts) != 3 or not parts[0] or not parts[1] or not parts[2]:
        raise ValueError("格式错误。示例：/set_tenant_platform_fee 1 | on | 1")
    try:
        tenant_id = int(parts[0])
    except ValueError:
        raise ValueError("租户 ID 必须是数字。")
    if tenant_id <= 0:
        raise ValueError("租户 ID 必须大于 0。")
    return tenant_id, _parse_on_off(parts[1]), _parse_fee_percent(parts[2])


def _parse_grant_subscription_days_args(raw_args: str) -> Tuple[int, int, Optional[str]]:
    parts = [part.strip() for part in raw_args.split("|", 2)]
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValueError("格式错误。示例：/grant_tenant_subscription_days 1 | 30 | 原因")
    tenant_id = _parse_positive_id(parts[0], "租户 ID")
    try:
        days = int(parts[1])
    except ValueError:
        raise ValueError("赠送天数必须是数字。")
    if days <= 0 or days > 3650:
        raise ValueError("赠送天数范围为 1-3650。")
    reason = parts[2] if len(parts) == 3 and parts[2] else None
    if reason is not None and len(reason) > 500:
        raise ValueError("原因不能超过 500 个字符。")
    return tenant_id, days, reason


def _parse_set_subscription_until_args(raw_args: str) -> Tuple[int, datetime, Optional[str]]:
    parts = [part.strip() for part in raw_args.split("|", 2)]
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValueError("格式错误。示例：/set_tenant_subscription_until 1 | 2026-08-31 23:59:59 | 原因")
    tenant_id = _parse_positive_id(parts[0], "租户 ID")
    period_ends_at = _parse_utc_datetime(parts[1], "订阅到期时间")
    reason = parts[2] if len(parts) == 3 and parts[2] else None
    if reason is not None and len(reason) > 500:
        raise ValueError("原因不能超过 500 个字符。")
    return tenant_id, period_ends_at, reason


def _parse_on_off(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"on", "true", "1", "yes"}:
        return True
    if normalized in {"off", "false", "0", "no"}:
        return False
    raise ValueError("开关必须是 on 或 off。")


def _parse_fee_percent(value: str) -> Decimal:
    try:
        percent = Decimal(value.strip())
    except (InvalidOperation, ValueError):
        raise ValueError("平台手续费比例必须是数字。")
    if percent < 0 or percent >= 100:
        raise ValueError("平台手续费比例必须大于等于 0 且小于 100。")
    return percent


def _parse_positive_id(value: str, label: str) -> int:
    try:
        target_id = int(value)
    except ValueError:
        raise ValueError(f"{label}必须是数字。")
    if target_id <= 0:
        raise ValueError(f"{label}必须大于 0。")
    return target_id


def _parse_utc_datetime(value: str, label: str) -> datetime:
    normalized = value.strip()
    formats = [
        ("%Y-%m-%d %H:%M:%S", None),
        ("%Y-%m-%d", (23, 59, 59)),
    ]
    for date_format, end_of_day in formats:
        try:
            parsed = datetime.strptime(normalized, date_format)
        except ValueError:
            continue
        if end_of_day is not None:
            parsed = parsed.replace(hour=end_of_day[0], minute=end_of_day[1], second=end_of_day[2])
        return parsed.replace(tzinfo=timezone.utc)
    raise ValueError(f"{label}格式错误。示例：2026-08-31 23:59:59 或 2026-08-31")


def _parse_review_args(raw_args: str, command_name: str) -> Tuple[int, Optional[str]]:
    parts = [part.strip() for part in raw_args.split("|", 1)]
    if not parts or not parts[0]:
        raise ValueError(f"请提供提现 ID。示例：/{command_name} 1 | 备注")
    try:
        withdrawal_id = int(parts[0])
    except ValueError:
        raise ValueError("提现 ID 必须是数字。")
    if withdrawal_id <= 0:
        raise ValueError("提现 ID 必须大于 0。")
    note = parts[1] if len(parts) == 2 and parts[1] else None
    if note is not None and len(note) > 500:
        raise ValueError("备注不能超过 500 个字符。")
    return withdrawal_id, note


def _parse_complete_withdrawal_args(raw_args: str) -> Tuple[int, Optional[str], Optional[str], Optional[str]]:
    parts = [part.strip() for part in raw_args.split("|", 3)]
    if not parts or not parts[0]:
        raise ValueError("请提供提现 ID。示例：/complete_withdrawal 1 | 打款流水 | 凭证链接或 - | 备注")
    try:
        withdrawal_id = int(parts[0])
    except ValueError:
        raise ValueError("提现 ID 必须是数字。")
    if withdrawal_id <= 0:
        raise ValueError("提现 ID 必须大于 0。")
    if len(parts) == 1:
        return withdrawal_id, None, None, None
    if len(parts) == 2:
        note = parts[1] or None
        _validate_optional_text_length(note, "备注", 500)
        return withdrawal_id, None, None, note
    payout_reference = parts[1] or None
    _validate_optional_text_length(payout_reference, "打款流水", 128)
    payout_proof_url = None if len(parts) < 4 or parts[2] in {"", "-"} else parts[2]
    _validate_optional_text_length(payout_proof_url, "凭证链接", 1000)
    note = parts[2] if len(parts) == 3 and parts[2] else parts[3] if len(parts) == 4 and parts[3] else None
    _validate_optional_text_length(note, "备注", 500)
    return withdrawal_id, payout_reference, payout_proof_url, note


def _validate_optional_text_length(value: Optional[str], label: str, max_length: int) -> None:
    if value is not None and len(value) > max_length:
        raise ValueError(f"{label}不能超过 {max_length} 个字符。")


def _parse_refund_args(raw_args: str) -> Tuple[str, Optional[Decimal], Optional[str]]:
    parts = [part.strip() for part in raw_args.split("|", 2)]
    if not parts or not parts[0]:
        raise ValueError("请提供订单号。示例：/refund_order ORDxxxx | 10 | 退款原因")
    out_trade_no = parts[0]
    if len(out_trade_no) > 96:
        raise ValueError("订单号长度不正确。")
    amount: Optional[Decimal] = None
    reason: Optional[str] = None
    if len(parts) == 2:
        if _looks_like_amount(parts[1]) or parts[1] == "-":
            amount = _parse_optional_amount(parts[1], "退款金额")
        else:
            reason = parts[1] or None
    elif len(parts) == 3:
        amount = _parse_optional_amount(parts[1], "退款金额")
        reason = parts[2] or None
    if reason is not None and len(reason) > 500:
        raise ValueError("退款原因不能超过 500 个字符。")
    return out_trade_no, amount, reason


def _parse_target_reason_args(raw_args: str, command_name: str, target_label: str) -> Tuple[int, Optional[str]]:
    parts = [part.strip() for part in raw_args.split("|", 1)]
    if not parts or not parts[0]:
        raise ValueError(f"请提供{target_label}。示例：/{command_name} 1 | 原因")
    try:
        target_id = int(parts[0])
    except ValueError:
        raise ValueError(f"{target_label}必须是数字。")
    if target_id <= 0:
        raise ValueError(f"{target_label}必须大于 0。")
    reason = parts[1] if len(parts) == 2 and parts[1] else None
    if reason is not None and len(reason) > 500:
        raise ValueError("原因不能超过 500 个字符。")
    return target_id, reason


def _parse_platform_user_risk_args(raw_args: str, command_name: str) -> Tuple[int, Optional[str]]:
    parts = [part.strip() for part in raw_args.split("|", 1)]
    if not parts or not parts[0]:
        raise ValueError(f"请提供 Telegram 用户 ID。示例：/{command_name} 123456 | 原因")
    try:
        telegram_user_id = int(parts[0])
    except ValueError:
        raise ValueError("Telegram 用户 ID 必须是数字。")
    if telegram_user_id <= 0:
        raise ValueError("Telegram 用户 ID 必须大于 0。")
    reason = parts[1] if len(parts) == 2 and parts[1] else None
    if reason is not None and len(reason) > 500:
        raise ValueError("原因不能超过 500 个字符。")
    return telegram_user_id, reason


def _parse_order_note_args(raw_args: str, command_name: str, note_label: str) -> Tuple[str, Optional[str]]:
    parts = [part.strip() for part in raw_args.split("|", 1)]
    if not parts or not parts[0]:
        raise ValueError(f"请提供订单号。示例：/{command_name} ORDxxxx | {note_label}")
    out_trade_no = parts[0]
    if len(out_trade_no) > 96:
        raise ValueError("订单号长度不正确。")
    note = parts[1] if len(parts) == 2 and parts[1] else None
    if note is not None and len(note) > 500:
        raise ValueError(f"{note_label}不能超过 500 个字符。")
    return out_trade_no, note


def _parse_dispute_note_args(raw_args: str, command_name: str, note_label: str) -> Tuple[int, Optional[str]]:
    dispute_id, note = _parse_target_reason_args(raw_args, command_name, "争议 ID")
    if note is not None and len(note) > 500:
        raise ValueError(f"{note_label}不能超过 500 个字符。")
    return dispute_id, note


def _parse_close_dispute_args(raw_args: str) -> Tuple[int, str, str]:
    parts = [part.strip() for part in raw_args.split("|", 2)]
    if len(parts) < 3 or not parts[0] or not parts[1] or not parts[2]:
        raise ValueError("格式错误。示例：/close_dispute 1 | resolved | 处理结论")
    try:
        dispute_id = int(parts[0])
    except ValueError:
        raise ValueError("争议 ID 必须是数字。")
    if dispute_id <= 0:
        raise ValueError("争议 ID 必须大于 0。")
    status = parts[1]
    if status not in {"resolved", "rejected", "closed"}:
        raise ValueError("争议结论必须是 resolved、rejected 或 closed。")
    resolution = parts[2]
    if len(resolution) > 500:
        raise ValueError("处理结论不能超过 500 个字符。")
    return dispute_id, status, resolution


def _parse_open_after_sale_args(raw_args: str) -> Tuple[str, str, Optional[Decimal], Optional[str]]:
    parts = [part.strip() for part in raw_args.split("|", 3)]
    if len(parts) < 3 or not parts[0] or not parts[1] or not parts[2]:
        raise ValueError("格式错误。示例：/open_after_sale ORDxxxx | refund | 10 或 - | 原因")
    out_trade_no = parts[0]
    if len(out_trade_no) > 96:
        raise ValueError("订单号长度不正确。")
    case_type = parts[1].lower()
    if case_type not in {"refund", "complaint", "reseller_after_sale"}:
        raise ValueError("售后类型必须是 refund、complaint 或 reseller_after_sale。")
    requested_amount = _parse_optional_amount(parts[2], "售后申请金额")
    reason = parts[3] if len(parts) == 4 and parts[3] else None
    if reason is not None and len(reason) > 500:
        raise ValueError("原因不能超过 500 个字符。")
    return out_trade_no, case_type, requested_amount, reason


def _parse_after_sale_note_args(raw_args: str, command_name: str, note_label: str) -> Tuple[int, Optional[str]]:
    case_id, note = _parse_target_reason_args(raw_args, command_name, "售后 ID")
    if note is not None and len(note) > 500:
        raise ValueError(f"{note_label}不能超过 500 个字符。")
    return case_id, note


def _parse_refund_after_sale_args(raw_args: str) -> Tuple[int, Decimal, Optional[str]]:
    parts = [part.strip() for part in raw_args.split("|", 2)]
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValueError("格式错误。示例：/refund_after_sale 1 | 10 | 退款备注")
    try:
        case_id = int(parts[0])
    except ValueError:
        raise ValueError("售后 ID 必须是数字。")
    if case_id <= 0:
        raise ValueError("售后 ID 必须大于 0。")
    amount = _parse_required_amount(parts[1], "退款金额")
    note = parts[2] if len(parts) == 3 and parts[2] else None
    if note is not None and len(note) > 500:
        raise ValueError("退款备注不能超过 500 个字符。")
    return case_id, amount, note


def _parse_close_after_sale_args(raw_args: str) -> Tuple[int, str, str]:
    parts = [part.strip() for part in raw_args.split("|", 2)]
    if len(parts) < 3 or not parts[0] or not parts[1] or not parts[2]:
        raise ValueError("格式错误。示例：/close_after_sale 1 | resolved | 处理结论")
    try:
        case_id = int(parts[0])
    except ValueError:
        raise ValueError("售后 ID 必须是数字。")
    if case_id <= 0:
        raise ValueError("售后 ID 必须大于 0。")
    status = parts[1]
    if status not in {"resolved", "rejected", "closed"}:
        raise ValueError("售后结论必须是 resolved、rejected 或 closed。")
    resolution = parts[2]
    if len(resolution) > 500:
        raise ValueError("处理结论不能超过 500 个字符。")
    return case_id, status, resolution


def _parse_after_sales_args(raw_args: str) -> Tuple[Optional[int], Optional[str], int]:
    value = raw_args.strip()
    if not value:
        return None, "open", 20
    parts = [part.strip() for part in value.split("|")]
    tenant_id: Optional[int] = None
    status: Optional[str] = "open"
    limit = 20
    if parts[0]:
        if parts[0] == "all":
            status = None
        elif parts[0] in {"open", "reviewing", "resolved", "rejected", "closed"}:
            status = parts[0]
        else:
            try:
                tenant_id = int(parts[0])
            except ValueError:
                raise ValueError("格式错误。示例：/after_sales、/after_sales all | 20 或 /after_sales 租户ID | open | 20")
            if tenant_id <= 0:
                raise ValueError("租户 ID 必须大于 0。")
    if len(parts) >= 2 and parts[1]:
        if parts[1] == "all":
            status = None
        elif parts[1] in {"open", "reviewing", "resolved", "rejected", "closed"}:
            status = parts[1]
        else:
            limit = _parse_limit(parts[1])
    if len(parts) >= 3 and parts[2]:
        limit = _parse_limit(parts[2])
    if len(parts) > 3:
        raise ValueError("格式错误。示例：/after_sales、/after_sales all | 20 或 /after_sales 租户ID | open | 20")
    return tenant_id, status, limit


def _parse_disputes_args(raw_args: str) -> Tuple[Optional[int], Optional[str], int]:
    value = raw_args.strip()
    if not value:
        return None, "open", 20
    parts = [part.strip() for part in value.split("|")]
    tenant_id: Optional[int] = None
    status: Optional[str] = "open"
    limit = 20
    if parts[0]:
        if parts[0] == "all":
            status = None
        elif parts[0] in {"open", "reviewing", "resolved", "rejected", "closed"}:
            status = parts[0]
        else:
            try:
                tenant_id = int(parts[0])
            except ValueError:
                raise ValueError("格式错误。示例：/disputes、/disputes all | 20 或 /disputes 租户ID | open | 20")
            if tenant_id <= 0:
                raise ValueError("租户 ID 必须大于 0。")
    if len(parts) >= 2 and parts[1]:
        if parts[1] == "all":
            status = None
        elif parts[1] in {"open", "reviewing", "resolved", "rejected", "closed"}:
            status = parts[1]
        else:
            limit = _parse_limit(parts[1])
    if len(parts) >= 3 and parts[2]:
        limit = _parse_limit(parts[2])
    if len(parts) > 3:
        raise ValueError("格式错误。示例：/disputes、/disputes all | 20 或 /disputes 租户ID | open | 20")
    return tenant_id, status, limit


def _parse_master_export_report_args(raw_args: str) -> Tuple[Optional[int], str, str]:
    parts = [part.strip() for part in raw_args.split("|", 1)]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("格式错误。示例：/export_report 租户ID | orders 或 /export_report all | ledger")
    scope = parts[0].lower()
    report_type = _parse_report_type(parts[1])
    if scope == "all":
        return None, "platform", report_type
    try:
        tenant_id = int(scope)
    except ValueError:
        raise ValueError("租户 ID 必须是数字，或使用 all 导出全平台。")
    if tenant_id <= 0:
        raise ValueError("租户 ID 必须大于 0。")
    return tenant_id, "tenant", report_type


def _parse_master_export_jobs_args(raw_args: str) -> Tuple[Optional[int], bool, int]:
    value = raw_args.strip()
    if not value:
        return None, True, 20
    if "|" not in value:
        if value.lower() == "all":
            return None, True, 20
        return None, True, _parse_limit(value)
    parts = [part.strip() for part in value.split("|", 1)]
    if not parts[0] or parts[0].lower() == "all":
        return None, True, _parse_limit(parts[1])
    try:
        tenant_id = int(parts[0])
    except ValueError:
        raise ValueError("格式错误。示例：/export_jobs all | 20 或 /export_jobs 租户ID | 20")
    if tenant_id <= 0:
        raise ValueError("租户 ID 必须大于 0。")
    return tenant_id, False, _parse_limit(parts[1])


def _parse_report_type(raw_args: str) -> str:
    report_type = raw_args.strip().lower()
    if report_type not in {"orders", "payments", "inventory", "ledger"}:
        raise ValueError("报表类型不支持，可选：orders、payments、inventory、ledger")
    return report_type


def _parse_required_amount(value: str, label: str) -> Decimal:
    amount = _parse_optional_amount(value, label)
    if amount is None:
        raise ValueError(f"{label}不能为空。")
    return amount


def _parse_optional_amount(value: str, label: str) -> Optional[Decimal]:
    normalized = value.strip()
    if normalized == "-":
        return None
    try:
        amount = Decimal(normalized)
    except (InvalidOperation, ValueError):
        raise ValueError(f"{label}必须是数字，或使用 - 表示不指定。")
    if amount <= 0:
        raise ValueError(f"{label}必须大于 0。")
    return amount


def _looks_like_amount(value: str) -> bool:
    try:
        Decimal(value.strip())
    except (InvalidOperation, ValueError):
        return False
    return True


def _manual_refund_key(message: Message, out_trade_no: str, amount: Optional[Decimal]) -> Optional[str]:
    if amount is None:
        return None
    payload = f"{message.chat.id}|{message.message_id}|{out_trade_no}|{amount}".encode()
    digest = hashlib.sha256(payload).hexdigest()[:40]
    return f"manual_refund:{digest}"


async def _run_risk_action(
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    action_name: str,
    target_id: int,
    reason: Optional[str],
) -> RiskActionResult:
    if message.from_user is None:
        raise ValueError("无法识别当前用户。")
    repo = TenantRepository()
    service = RiskControlService()
    async with session_factory() as session:
        actor = await repo.get_or_create_platform_user(session, message.from_user, settings)
        action = getattr(service, action_name)
        result = await action(session, target_id, actor.id, reason)
        await session.commit()
        return result


async def _run_dispute_action(
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    action_name: str,
    target: int | str,
    note: Optional[str],
) -> DisputeSummary:
    if message.from_user is None:
        raise ValueError("无法识别当前用户。")
    repo = TenantRepository()
    service = RiskControlService()
    async with session_factory() as session:
        actor = await repo.get_or_create_platform_user(session, message.from_user, settings)
        action = getattr(service, action_name)
        dispute = await action(session, target, actor.id, note)
        await session.commit()
        return dispute


async def _run_dispute_close_action(
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    dispute_id: int,
    status: str,
    resolution: str,
) -> DisputeSummary:
    if message.from_user is None:
        raise ValueError("无法识别当前用户。")
    repo = TenantRepository()
    async with session_factory() as session:
        actor = await repo.get_or_create_platform_user(session, message.from_user, settings)
        dispute = await RiskControlService().close_dispute(session, dispute_id, actor.id, status, resolution)
        await session.commit()
        return dispute


async def _run_after_sale_open_action(
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    out_trade_no: str,
    case_type: str,
    requested_amount: Optional[Decimal],
    reason: Optional[str],
) -> AfterSaleSummary:
    if message.from_user is None:
        raise ValueError("无法识别当前用户。")
    repo = TenantRepository()
    async with session_factory() as session:
        actor = await repo.get_or_create_platform_user(session, message.from_user, settings)
        after_sale = await RiskControlService().open_after_sale(
            session,
            out_trade_no,
            actor.id,
            case_type,
            requested_amount,
            reason,
        )
        await session.commit()
        return after_sale


async def _run_after_sale_action(
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    action_name: str,
    case_id: int,
    note: Optional[str],
) -> AfterSaleSummary:
    if message.from_user is None:
        raise ValueError("无法识别当前用户。")
    repo = TenantRepository()
    service = RiskControlService()
    async with session_factory() as session:
        actor = await repo.get_or_create_platform_user(session, message.from_user, settings)
        action = getattr(service, action_name)
        after_sale = await action(session, case_id, actor.id, note)
        await session.commit()
        return after_sale


async def _run_after_sale_refund_action(
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    case_id: int,
    amount: Decimal,
    note: Optional[str],
) -> AfterSaleSummary:
    if message.from_user is None:
        raise ValueError("无法识别当前用户。")
    repo = TenantRepository()
    async with session_factory() as session:
        actor = await repo.get_or_create_platform_user(session, message.from_user, settings)
        after_sale = await RiskControlService().refund_after_sale(session, case_id, actor.id, amount, note)
        await session.commit()
        return after_sale


async def _run_after_sale_close_action(
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    case_id: int,
    status: str,
    resolution: str,
) -> AfterSaleSummary:
    if message.from_user is None:
        raise ValueError("无法识别当前用户。")
    repo = TenantRepository()
    async with session_factory() as session:
        actor = await repo.get_or_create_platform_user(session, message.from_user, settings)
        after_sale = await RiskControlService().close_after_sale(session, case_id, actor.id, status, resolution)
        await session.commit()
        return after_sale


async def _run_platform_fee_update(
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    enabled: bool,
    percent: Decimal,
    tenant_id: Optional[int],
) -> SettlementPolicySummary:
    if message.from_user is None:
        raise ValueError("无法识别当前用户。")
    repo = TenantRepository()
    async with session_factory() as session:
        actor = await repo.get_or_create_platform_user(session, message.from_user, settings)
        policy = await LedgerService().set_platform_fee_policy(
            session=session,
            actor_user_id=actor.id,
            enabled=enabled,
            platform_fee_percent=percent,
            tenant_id=tenant_id,
        )
        await session.commit()
        return policy


async def _run_subscription_days_grant(
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: int,
    days: int,
    reason: Optional[str],
) -> SubscriptionAdjustmentResult:
    if message.from_user is None:
        raise ValueError("无法识别当前用户。")
    repo = TenantRepository()
    async with session_factory() as session:
        actor = await repo.get_or_create_platform_user(session, message.from_user, settings)
        result = await SubscriptionService().grant_days(
            session=session,
            tenant_id=tenant_id,
            actor_user_id=actor.id,
            days=days,
            monthly_price=settings.subscription_monthly_price,
            reason=reason,
        )
        await session.commit()
        return result


async def _run_subscription_until_update(
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: int,
    period_ends_at: datetime,
    reason: Optional[str],
) -> SubscriptionAdjustmentResult:
    if message.from_user is None:
        raise ValueError("无法识别当前用户。")
    repo = TenantRepository()
    async with session_factory() as session:
        actor = await repo.get_or_create_platform_user(session, message.from_user, settings)
        result = await SubscriptionService().set_period_end(
            session=session,
            tenant_id=tenant_id,
            actor_user_id=actor.id,
            period_ends_at=period_ends_at,
            monthly_price=settings.subscription_monthly_price,
            reason=reason,
        )
        await session.commit()
        return result


async def _clear_tenant_webhook_cache(settings: Settings, result: RiskActionResult) -> None:
    if not result.webhook_secrets:
        return
    await _delete_tenant_webhook_cache(settings, *result.webhook_secrets)


async def _delete_tenant_webhook_cache(settings: Settings, *webhook_secrets: Optional[str]) -> None:
    keys = [f"tenant_webhook:{secret}" for secret in webhook_secrets if secret]
    if not keys:
        return
    redis_client = None
    try:
        redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        await redis_client.delete(*keys)
    except Exception:
        logger.exception("tenant webhook cache cleanup failed")
    finally:
        if redis_client is not None:
            await redis_client.aclose()


def _format_withdrawal_summary(withdrawal: WithdrawalSummary) -> str:
    payout_text = _format_payout_proof(withdrawal)
    return (
        f"#{withdrawal.withdrawal_id}｜租户 {withdrawal.tenant_id}\n"
        f"金额：{withdrawal.amount} {withdrawal.currency}\n"
        f"网络：{html.escape(withdrawal.network)}\n"
        f"地址：{html.escape(_mask_address(withdrawal.address))}\n"
        f"申请时间：{withdrawal.requested_at:%Y-%m-%d %H:%M:%S %Z}\n"
        f"{payout_text}"
        f"完成：/complete_withdrawal {withdrawal.withdrawal_id} | 打款流水 | 凭证链接或 - | 备注\n"
        f"拒绝：/reject_withdrawal {withdrawal.withdrawal_id} | 备注"
    )


def _withdrawal_summary_from_model(withdrawal: Any) -> WithdrawalSummary:
    return WithdrawalSummary(
        withdrawal_id=withdrawal.id,
        tenant_id=withdrawal.tenant_id,
        amount=withdrawal.amount,
        currency=withdrawal.currency,
        network=withdrawal.network,
        address=withdrawal.address,
        status=withdrawal.status,
        requested_at=withdrawal.requested_at,
        payout_reference=getattr(withdrawal, "payout_reference", None),
        payout_proof_url=getattr(withdrawal, "payout_proof_url", None),
    )


def _format_withdrawal_audit(withdrawal: WithdrawalSummary) -> str:
    status_labels = {
        "pending": "待审核",
        "completed": "已完成",
        "rejected": "已拒绝",
    }
    return (
        f"#{withdrawal.withdrawal_id}｜租户 {withdrawal.tenant_id}｜状态：{status_labels.get(withdrawal.status, withdrawal.status)}\n"
        f"金额：{withdrawal.amount} {withdrawal.currency}\n"
        f"网络：{html.escape(withdrawal.network)}\n"
        f"地址：{html.escape(_mask_address(withdrawal.address))}\n"
        f"{_format_payout_proof(withdrawal)}"
        f"申请时间：{withdrawal.requested_at:%Y-%m-%d %H:%M:%S %Z}"
    )


def _format_payout_proof(withdrawal: WithdrawalSummary) -> str:
    parts = []
    if withdrawal.payout_reference:
        parts.append(f"打款流水：{html.escape(withdrawal.payout_reference)}")
    if withdrawal.payout_proof_url:
        parts.append(f"凭证链接：{html.escape(withdrawal.payout_proof_url)}")
    if not parts:
        return ""
    return "\n".join(parts) + "\n"


def _format_audit_logs(logs: list[AuditLogSummary], title: str, include_tenant: bool) -> str:
    if not logs:
        return f"{title}\n\n暂无审计记录。"
    lines = [title]
    for log in logs:
        tenant = f"租户：{log.tenant_id or '-'}｜" if include_tenant else ""
        actor = _format_audit_actor(log)
        target = _format_audit_target(log)
        metadata = _format_audit_metadata(log.metadata_json)
        lines.append(
            f"#{log.audit_log_id}｜{tenant}{log.created_at:%Y-%m-%d %H:%M:%S %Z}\n"
            f"动作：{html.escape(log.action)}\n"
            f"操作者：{actor}\n"
            f"目标：{target}\n"
            f"元数据：{metadata}"
        )
    return "\n\n".join(lines)


def _format_audit_actor(log: AuditLogSummary) -> str:
    if log.actor_telegram_user_id is None:
        return "-"
    username = f"@{log.actor_username}" if log.actor_username else "-"
    return f"{log.actor_telegram_user_id}｜{html.escape(username)}"


def _format_audit_target(log: AuditLogSummary) -> str:
    target_type = log.target_type or "-"
    target_id = log.target_id or "-"
    return f"{html.escape(target_type)}:{html.escape(target_id)}"


def _format_audit_metadata(metadata: dict[str, Any]) -> str:
    if not metadata:
        return "-"
    parts = []
    for key, value in list(metadata.items())[:8]:
        parts.append(f"{html.escape(str(key))}={html.escape(str(value))}")
    return "；".join(parts)


def _format_optional_datetime(value: Optional[Any]) -> str:
    if value is None:
        return "-"
    return f"{value:%Y-%m-%d %H:%M:%S %Z}"


def _format_settlement_policy(title: str, policy: SettlementPolicySummary) -> str:
    scope_labels = {
        "default": "系统默认",
        "platform": "平台默认",
        "tenant": "租户覆盖",
    }
    enabled_text = "开启" if policy.platform_fee_enabled else "关闭"
    tenant_text = str(policy.tenant_id) if policy.tenant_id is not None else "-"
    return (
        f"{html.escape(title)}\n\n"
        f"范围：{scope_labels.get(policy.scope_type, html.escape(policy.scope_type))}\n"
        f"租户 ID：{tenant_text}\n"
        f"冻结期：{policy.freeze_days} 天\n"
        f"平台手续费：{enabled_text}\n"
        f"手续费比例：{policy.platform_fee_percent}%"
    )


def _format_subscription_adjustment(title: str, result: SubscriptionAdjustmentResult) -> str:
    return (
        f"{html.escape(title)}\n\n"
        f"租户 ID：{result.tenant_id}\n"
        f"租户状态：{html.escape(result.status)}\n"
        f"原到期时间：{_format_optional_datetime(result.previous_period_ends_at)}\n"
        f"新到期时间：{_format_optional_datetime(result.new_period_ends_at)}"
    )


def _format_refund_result(refund: RefundResult) -> str:
    status_text = "已完成" if refund.created else "已存在"
    return (
        f"退款{status_text}\n\n"
        f"退款 ID：#{refund.refund_id}\n"
        f"订单号：{html.escape(refund.out_trade_no)}\n"
        f"金额：{refund.amount} {refund.currency}\n"
        f"冲正分录：{refund.reversed_entry_count} 条"
    )


def _format_dispute_result(title: str, dispute: DisputeSummary) -> str:
    return (
        f"{title}\n\n"
        f"争议 ID：#{dispute.dispute_id}\n"
        f"订单号：{html.escape(dispute.out_trade_no)}\n"
        f"租户 ID：{dispute.tenant_id}\n"
        f"买家：{dispute.buyer_telegram_user_id}\n"
        f"订单：{html.escape(dispute.source_type)}｜{html.escape(dispute.order_status)}｜"
        f"{dispute.amount} {dispute.currency}\n"
        f"状态：{html.escape(dispute.status)}\n"
        f"原因：{html.escape(dispute.reason) if dispute.reason else '-'}\n"
        f"结论：{html.escape(dispute.resolution) if dispute.resolution else '-'}"
    )


def _format_disputes(disputes: list[DisputeSummary], tenant_id: Optional[int], status: Optional[str]) -> str:
    status_text = status or "all"
    tenant_text = f"租户 {tenant_id}" if tenant_id is not None else "全平台"
    if not disputes:
        return f"订单争议｜{tenant_text}｜{status_text}\n\n暂无记录。"
    lines = [f"订单争议｜{tenant_text}｜{status_text}"]
    for dispute in disputes:
        lines.append(
            f"#{dispute.dispute_id}｜租户 {dispute.tenant_id}｜状态：{html.escape(dispute.status)}\n"
            f"订单号：{html.escape(dispute.out_trade_no)}｜买家：{dispute.buyer_telegram_user_id}\n"
            f"金额：{dispute.amount} {dispute.currency}｜订单状态：{html.escape(dispute.order_status)}\n"
            f"原因：{html.escape(dispute.reason) if dispute.reason else '-'}\n"
            f"处理：/review_dispute {dispute.dispute_id} | 备注\n"
            f"关闭：/close_dispute {dispute.dispute_id} | resolved | 处理结论"
        )
    return "\n\n".join(lines)


def _format_after_sale_result(title: str, after_sale: AfterSaleSummary) -> str:
    requested_amount = after_sale.requested_amount if after_sale.requested_amount is not None else "-"
    refund_id = f"#{after_sale.refund_id}" if after_sale.refund_id is not None else "-"
    return (
        f"{title}\n\n"
        f"售后 ID：#{after_sale.case_id}\n"
        f"订单号：{html.escape(after_sale.out_trade_no)}\n"
        f"租户 ID：{after_sale.tenant_id}\n"
        f"买家：{after_sale.buyer_telegram_user_id}\n"
        f"订单：{html.escape(after_sale.source_type)}｜{html.escape(after_sale.order_status)}｜"
        f"{after_sale.amount} {after_sale.currency}\n"
        f"类型：{html.escape(after_sale.case_type)}｜状态：{html.escape(after_sale.status)}\n"
        f"申请金额：{requested_amount}｜已退：{after_sale.refunded_amount} {after_sale.currency}｜退款 ID：{refund_id}\n"
        f"原因：{html.escape(after_sale.reason) if after_sale.reason else '-'}\n"
        f"结论：{html.escape(after_sale.resolution) if after_sale.resolution else '-'}"
    )


def _format_after_sales(after_sales: list[AfterSaleSummary], tenant_id: Optional[int], status: Optional[str]) -> str:
    status_text = status or "all"
    tenant_text = f"租户 {tenant_id}" if tenant_id is not None else "全平台"
    if not after_sales:
        return f"售后工单｜{tenant_text}｜{status_text}\n\n暂无记录。"
    lines = [f"售后工单｜{tenant_text}｜{status_text}"]
    for after_sale in after_sales:
        requested_amount = after_sale.requested_amount if after_sale.requested_amount is not None else "-"
        lines.append(
            f"#{after_sale.case_id}｜租户 {after_sale.tenant_id}｜{html.escape(after_sale.case_type)}｜"
            f"状态：{html.escape(after_sale.status)}\n"
            f"订单号：{html.escape(after_sale.out_trade_no)}｜买家：{after_sale.buyer_telegram_user_id}\n"
            f"订单金额：{after_sale.amount} {after_sale.currency}｜申请：{requested_amount}｜已退："
            f"{after_sale.refunded_amount} {after_sale.currency}\n"
            f"原因：{html.escape(after_sale.reason) if after_sale.reason else '-'}\n"
            f"处理：/review_after_sale {after_sale.case_id} | 备注\n"
            f"退款：/refund_after_sale {after_sale.case_id} | 金额 | 备注\n"
            f"关闭：/close_after_sale {after_sale.case_id} | resolved | 处理结论"
        )
    return "\n\n".join(lines)


def _format_export_job_created(job: ExportJobSummary, include_tenant: bool) -> str:
    tenant_text = f"租户 ID：{job.tenant_id or '-'}\n" if include_tenant else ""
    return (
        "报表导出任务已创建\n\n"
        f"任务 ID：#{job.export_job_id}\n"
        f"{tenant_text}"
        f"范围：{html.escape(job.scope_type)}\n"
        f"类型：{html.escape(job.report_type)}\n"
        f"状态：{_export_status_label(job.status)}\n\n"
        "后台 worker 会异步生成 CSV；完成后使用 /export_jobs 查看下载链接。"
    )


def _format_export_jobs(jobs: list[ExportJobSummary], include_tenant: bool) -> str:
    if not jobs:
        return "报表导出任务\n\n暂无记录。"
    lines = ["报表导出任务"]
    for job in jobs:
        tenant_text = f"租户：{job.tenant_id or '-'}｜" if include_tenant else ""
        download_text = f"\n下载：{html.escape(job.download_url)}" if job.download_url else ""
        error_text = f"\n错误：{html.escape(job.error_message)}" if job.error_message else ""
        lines.append(
            f"#{job.export_job_id}｜{tenant_text}{html.escape(job.scope_type)}｜"
            f"{html.escape(job.report_type)}｜{_export_status_label(job.status)}\n"
            f"行数：{job.row_count}｜创建：{job.created_at:%Y-%m-%d %H:%M:%S %Z}\n"
            f"过期：{_format_optional_datetime(job.expires_at)}"
            f"{download_text}{error_text}"
        )
    return "\n\n".join(lines)


def _export_status_label(status: str) -> str:
    labels = {
        "pending": "待生成",
        "running": "生成中",
        "completed": "已完成",
        "failed": "失败",
        "expired": "已过期",
    }
    return labels.get(status, status)


def _format_risk_result(title: str, result: RiskActionResult) -> str:
    lines = [
        title,
        "",
        f"目标：{html.escape(result.target_type)} #{result.target_id}",
        f"租户 ID：{result.tenant_id if result.tenant_id is not None else '-'}",
        f"状态：{html.escape(result.previous_status)} → {html.escape(result.new_status)}",
        f"原因：{html.escape(result.reason) if result.reason else '-'}",
    ]
    if result.affected_count:
        lines.append(f"影响代理商品：{result.affected_count} 个")
    return "\n".join(lines)


def _format_admin_web_binding_code(code: str, expires_in_seconds: int, workspace_title: str) -> str:
    return (
        "网页管理后台一次性绑定码\n\n"
        f"绑定码：<code>{html.escape(code)}</code>\n"
        f"工作区：{html.escape(workspace_title)}\n"
        f"有效期：{expires_in_seconds} 秒\n\n"
        "请在 Web 管理后台输入该绑定码。绑定码只能使用一次。"
    )


def _mask_address(value: str) -> str:
    if len(value) <= 12:
        return "***"
    return f"{value[:6]}***{value[-6:]}"
