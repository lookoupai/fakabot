from __future__ import annotations

import html
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bots.context import TenantContext
from app.bots.filters import BotRoleFilter
from app.bots.middlewares.tenant_user_ban import TenantUserBanMiddleware
from app.config import Settings
from app.db.models.tenants import AuditLog
from app.db.repos.products import ALLOWED_DELIVERY_TYPES, ProductRepository
from app.db.repos.tenants import TenantRepository
from app.services.audit import AuditLogService, AuditLogSummary
from app.services.admin_web import AdminWebBindingCodeError, AdminWebBindingCodeStore
from app.services.api_keys import ApiKeyService, TenantApiKeySummary
from app.services.delivery import send_delivery_instruction
from app.services.file_inspection import FileInspectionService
from app.services.files import FileStorageService
from app.services.ledger import LedgerService, WithdrawalSummary
from app.services.notifications import NotificationService
from app.services.orders import ACTIVE_TENANT_STATUSES, OrderService
from app.services.payments import PaymentConfigService, PaymentService, PaymentUnavailableError
from app.services.reports import ExportJobSummary, ReportExportService
from app.services.risk import OrderCreationRiskBlocked
from app.services.subscriptions import SubscriptionService
from app.services.supply import SupplyService
from app.services.tenant_features import (
    DEFAULT_TENANT_FEATURE_FLAGS,
    tenant_feature_disabled_message,
    tenant_feature_enabled,
)
from app.services.token_crypto import TokenCrypto

router = Router(name="tenant")
router.message.filter(BotRoleFilter("tenant"))
router.callback_query.filter(BotRoleFilter("tenant"))
router.message.middleware(TenantUserBanMiddleware())
router.callback_query.middleware(TenantUserBanMiddleware())

PERMISSION_LABELS = {
    "settings": "店铺设置",
    "products": "商品和库存",
    "orders": "订单和发货",
    "payments": "支付配置",
    "finance": "账本提现",
    "supply": "供货代理",
    "api_keys": "API Key",
    "subscription": "订阅续费",
    "reports": "报表导出",
}


@router.message(Command("start"))
async def tenant_start(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
    tenant_settings: Optional[Dict[str, Dict[str, Any]]] = None,
) -> None:
    if tenant_context is None:
        await message.answer("店铺暂不可用，请稍后再试。")
        return

    store_name, settings = await _load_profile(session_factory, tenant_context, tenant_settings)
    welcome = _setting_text(settings, "welcome", "欢迎光临，本店铺正在配置中。")
    can_manage = await _can_manage(session_factory, tenant_context, message.from_user.id if message.from_user else 0)

    await message.answer(
        f"{html.escape(store_name)}\n\n{html.escape(welcome)}",
        reply_markup=_store_keyboard(can_manage),
    )


@router.message(Command("products"))
async def products_list(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
    tenant_feature_flags: Optional[Dict[str, bool]] = None,
) -> None:
    if tenant_context is None:
        await message.answer("店铺暂不可用，请稍后再试。")
        return
    await _send_public_product_list(message, session_factory, tenant_context, tenant_feature_flags)


@router.message(Command("orders"))
async def orders_list(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if tenant_context is None or message.from_user is None:
        await message.answer("店铺暂不可用，请稍后再试。")
        return
    await _send_buyer_orders(message, session_factory, tenant_context, message.from_user.id)


@router.message(Command("buy_product"))
async def buy_product(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
    tenant_feature_flags: Optional[Dict[str, bool]] = None,
) -> None:
    if tenant_context is None or message.from_user is None:
        await message.answer("店铺暂不可用，请稍后再试。")
        return
    try:
        product_id = int((command.args or "").strip())
    except ValueError:
        await message.answer("请提供商品 ID。示例：/buy_product 1")
        return
    await _create_order_for_buyer(
        message,
        settings,
        session_factory,
        tenant_context,
        message.from_user.id,
        product_id,
        tenant_feature_flags,
    )


@router.message(Command("buy_reseller_product"))
async def buy_reseller_product(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
    tenant_feature_flags: Optional[Dict[str, bool]] = None,
) -> None:
    if tenant_context is None or message.from_user is None:
        await message.answer("店铺暂不可用，请稍后再试。")
        return
    try:
        reseller_product_id = int((command.args or "").strip())
    except ValueError:
        await message.answer("请提供代理商品 ID。示例：/buy_reseller_product 1")
        return
    await _create_reseller_order_for_buyer(
        message,
        settings,
        session_factory,
        tenant_context,
        message.from_user.id,
        reseller_product_id,
        tenant_feature_flags,
    )


@router.message(Command("support"))
async def support_info(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
    tenant_settings: Optional[Dict[str, Dict[str, Any]]] = None,
) -> None:
    if tenant_context is None:
        await message.answer("店铺暂不可用，请稍后再试。")
        return
    _, settings = await _load_profile(session_factory, tenant_context, tenant_settings)
    await message.answer(f"联系客服\n\n{html.escape(_setting_text(settings, 'support', '暂未配置客服联系方式。'))}")


@router.message(Command("manage"))
async def manage_menu(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_can_manage_message(message, session_factory, tenant_context):
        return
    await message.answer("商家管理\n\n请选择要管理的项目。", reply_markup=_manage_keyboard())


@router.message(Command("admin_web_code"))
async def admin_web_code(
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
    redis_client: object | None = None,
) -> None:
    if message.from_user is None:
        await message.answer("无法识别当前用户。")
        return
    if tenant_context is None:
        await message.answer("店铺暂不可用，请稍后再试。")
        return
    if not await _ensure_can_manage_message(message, session_factory, tenant_context):
        return
    if redis_client is None:
        await message.answer("绑定码服务暂不可用，请稍后再试。")
        return
    if not tenant_context.tenant_public_id:
        await message.answer("当前店铺缺少网页工作区标识。")
        return

    try:
        grant = await AdminWebBindingCodeStore(settings, redis_client).issue_code(
            telegram_user_id=message.from_user.id,
            current_workspace_id=tenant_context.tenant_public_id,
        )
    except AdminWebBindingCodeError as exc:
        await message.answer(str(exc))
        return

    await message.answer(
        _format_admin_web_binding_code(
            grant.code,
            grant.expires_in_seconds,
            tenant_context.store_name,
            tenant_context.bot_username,
        )
    )


@router.message(Command("settings"))
async def settings_view(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
    tenant_settings: Optional[Dict[str, Dict[str, Any]]] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "settings"):
        return
    store_name, settings = await _load_profile(session_factory, tenant_context, tenant_settings)
    await message.answer(_settings_text(store_name, settings))


@router.message(Command("admins"))
async def admins_list(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_owner_message(message, session_factory, tenant_context):
        return
    await _send_admins(message, session_factory, tenant_context)


@router.message(Command("add_admin"))
async def add_admin(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_owner_message(message, session_factory, tenant_context):
        return
    try:
        telegram_user_id = _parse_telegram_user_id(command.args or "", "/add_admin 123456789")
        repo = TenantRepository()
        async with session_factory() as session:
            member = await repo.add_admin_member(
                session=session,
                tenant_id=tenant_context.tenant_id,
                telegram_user_id=telegram_user_id,
                created_by_user_id=tenant_context.owner_user_id,
            )
            await session.commit()
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await message.answer(
        "管理员已添加。\n\n"
        f"成员 ID：#{member.id}\n"
        f"Telegram 用户 ID：{telegram_user_id}\n"
        "该用户现在可以使用商家管理功能，但不能增删管理员。"
    )


@router.message(Command("remove_admin"))
async def remove_admin(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_owner_message(message, session_factory, tenant_context):
        return
    try:
        telegram_user_id = _parse_telegram_user_id(command.args or "", "/remove_admin 123456789")
        repo = TenantRepository()
        async with session_factory() as session:
            removed = await repo.remove_admin_member(
                session=session,
                tenant_id=tenant_context.tenant_id,
                telegram_user_id=telegram_user_id,
                removed_by_user_id=tenant_context.owner_user_id,
            )
            await session.commit()
    except ValueError as exc:
        await message.answer(str(exc))
        return
    if not removed:
        await message.answer("没有找到该管理员。")
        return
    await message.answer(f"管理员已移除：{telegram_user_id}")


@router.message(Command("permissions"))
async def permissions(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_owner_message(message, session_factory, tenant_context):
        return
    async with session_factory() as session:
        permissions_map = await TenantRepository().list_role_permissions(
            session,
            tenant_id=tenant_context.tenant_id,
            role="admin",
        )
    await message.answer(_format_permissions(permissions_map))


@router.message(Command("audit_logs"))
async def audit_logs(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_owner_message(message, session_factory, tenant_context):
        return
    try:
        limit = _parse_list_limit(command.args or "", "/audit_logs 20")
    except ValueError as exc:
        await message.answer(str(exc))
        return
    async with session_factory() as session:
        logs = await AuditLogService().list_tenant_audit_logs(
            session,
            tenant_id=tenant_context.tenant_id,
            limit=limit,
        )
    await message.answer(_format_audit_logs(logs, "管理员操作审计"))


@router.message(Command("set_permission"))
async def set_permission(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_owner_message(message, session_factory, tenant_context):
        return
    try:
        permission, enabled = _parse_permission_args(command.args or "")
        async with session_factory() as session:
            role_permission = await TenantRepository().set_role_permission(
                session=session,
                tenant_id=tenant_context.tenant_id,
                role="admin",
                permission=permission,
                enabled=enabled,
                actor_user_id=tenant_context.owner_user_id,
            )
            await session.commit()
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await message.answer(
        "管理员权限已更新\n\n"
        f"权限：{PERMISSION_LABELS[role_permission.permission]}\n"
        f"状态：{'开启' if role_permission.enabled else '关闭'}"
    )


@router.message(Command("api_keys"))
async def api_keys(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "api_keys"):
        return
    try:
        limit = _parse_list_limit(command.args or "", "/api_keys 20")
        async with session_factory() as session:
            keys = await ApiKeyService(settings).list_tenant_api_keys(session, tenant_context.tenant_id, limit)
    except RuntimeError as exc:
        await message.answer(str(exc))
        return
    await message.answer(_format_api_keys(keys))


@router.message(Command("create_api_key"))
async def create_api_key(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "api_keys"):
        return
    try:
        name, scopes, ip_allowlist = _parse_create_api_key_args(command.args or "")
        async with session_factory() as session:
            actor = await TenantRepository().get_or_create_user_by_telegram_id(
                session,
                message.from_user.id,
            )
            created = await ApiKeyService(settings).create_tenant_api_key(
                session=session,
                tenant_id=tenant_context.tenant_id,
                name=name,
                created_by_user_id=actor.id,
                scopes=scopes,
                ip_allowlist=ip_allowlist,
            )
            await session.commit()
    except (RuntimeError, ValueError) as exc:
        await message.answer(str(exc))
        return
    await message.answer(
        "API Key 已创建，请立即复制保存，之后不会再次显示明文。\n\n"
        f"Key ID：#{created.api_key_id}\n"
        f"名称：{html.escape(created.name)}\n"
        f"前缀：{html.escape(created.key_prefix)}\n"
        f"权限：{html.escape(_format_api_key_scopes(created.scopes))}\n"
        f"IP白名单：{html.escape(_format_api_key_ip_allowlist(created.ip_allowlist))}\n"
        f"明文：<code>{html.escape(created.plain_key)}</code>\n\n"
        "撤销：/revoke_api_key KeyID"
    )


@router.message(Command("revoke_api_key"))
async def revoke_api_key(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "api_keys"):
        return
    try:
        api_key_id = _parse_positive_int((command.args or "").strip(), "API Key ID")
        async with session_factory() as session:
            actor = await TenantRepository().get_or_create_user_by_telegram_id(
                session,
                message.from_user.id,
            )
            revoked = await ApiKeyService(settings).revoke_tenant_api_key(
                session=session,
                tenant_id=tenant_context.tenant_id,
                api_key_id=api_key_id,
                revoked_by_user_id=actor.id,
            )
            await session.commit()
    except (RuntimeError, ValueError) as exc:
        await message.answer(str(exc))
        return
    await message.answer("API Key 已撤销。" if revoked else "API Key 不存在或无权限。")


@router.message(Command("set_store_name"))
async def set_store_name(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "settings"):
        return
    value = (command.args or "").strip()
    if not 2 <= len(value) <= 64:
        await message.answer("店铺名称长度应为 2-64 个字符。示例：/set_store_name 我的店铺")
        return

    repo = TenantRepository()
    async with session_factory() as session:
        await repo.update_store_name(session, tenant_context.tenant_id, value)
        await session.commit()
    await message.answer(f"店铺名称已更新为：{html.escape(value)}")


@router.message(Command("set_welcome"))
async def set_welcome(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    await _set_text_setting(
        message=message,
        command=command,
        session_factory=session_factory,
        tenant_context=tenant_context,
        key="welcome",
        label="欢迎语",
        max_length=500,
    )


@router.message(Command("set_support"))
async def set_support(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    await _set_text_setting(
        message=message,
        command=command,
        session_factory=session_factory,
        tenant_context=tenant_context,
        key="support",
        label="客服信息",
        max_length=300,
    )


@router.message(Command("set_order_timeout"))
async def set_order_timeout(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "settings"):
        return
    raw_value = (command.args or "").strip()
    try:
        minutes = int(raw_value)
    except ValueError:
        await message.answer("订单超时时间必须是分钟数。示例：/set_order_timeout 15")
        return
    if not 1 <= minutes <= 1440:
        await message.answer("订单超时时间范围为 1-1440 分钟。")
        return

    repo = TenantRepository()
    async with session_factory() as session:
        await repo.upsert_setting(session, tenant_context.tenant_id, "order_timeout_minutes", {"value": minutes})
        await session.commit()
    await message.answer(f"订单超时时间已更新为 {minutes} 分钟。")


@router.message(Command("add_product"))
async def add_product(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "products"):
        return

    try:
        name, price, delivery_type, description = _parse_add_product_args(command.args or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return

    repo = ProductRepository()
    async with session_factory() as session:
        product = await repo.create_self_product(
            session=session,
            tenant_id=tenant_context.tenant_id,
            name=name,
            price=price,
            delivery_type=delivery_type,
            description=description,
        )
        await session.commit()

    await message.answer(
        f"商品已创建为草稿：#{product.id} {html.escape(product.name)}\n"
        "确认无误后使用 /publish_product 商品ID 上架。"
    )


@router.message(Command("list_products"))
async def list_products(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "products"):
        return
    await _send_product_list(message, session_factory, tenant_context)


@router.message(Command("publish_product"))
async def publish_product(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    await _set_product_status_command(message, command, session_factory, tenant_context, "on", "上架")


@router.message(Command("hide_product"))
async def hide_product(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    await _set_product_status_command(message, command, session_factory, tenant_context, "off", "下架")


@router.message(Command("set_product_sort"))
async def set_product_sort(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "products"):
        return
    try:
        product_id, sort_order = _parse_product_sort_args(command.args or "")
        async with session_factory() as session:
            changed = await ProductRepository().set_product_sort_order(
                session,
                tenant_context.tenant_id,
                product_id,
                sort_order,
            )
            if changed:
                await session.commit()
    except ValueError as exc:
        await message.answer(str(exc))
        return
    if not changed:
        await message.answer("商品不存在或无权限。")
        return
    await message.answer(f"商品 #{product_id} 排序值已更新为 {sort_order}。")


@router.message(Command("set_product_category"))
async def set_product_category(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "products"):
        return
    try:
        product_id, category = _parse_product_category_args(command.args or "")
        async with session_factory() as session:
            changed = await ProductRepository().set_product_category(
                session,
                tenant_context.tenant_id,
                product_id,
                category,
            )
            if changed:
                await session.commit()
    except ValueError as exc:
        await message.answer(str(exc))
        return
    if not changed:
        await message.answer("商品不存在或无权限。")
        return
    category_text = category or "未分类"
    await message.answer(f"商品 #{product_id} 分类已更新为：{html.escape(category_text)}。")


@router.message(Command("add_inventory"))
async def add_inventory(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "products"):
        return

    try:
        product_id, items, duplicated_input_count = _parse_inventory_args(command.args or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return

    try:
        crypto = TokenCrypto(settings)
    except RuntimeError:
        await message.answer("缺少 TOKEN_ENCRYPTION_KEY，不能导入敏感库存。")
        return

    encrypted_items = [(crypto.encrypt_token(item), crypto.token_hash(item)) for item in items]
    repo = ProductRepository()
    try:
        async with session_factory() as session:
            added_count, existing_count = await repo.add_inventory_items(
                session=session,
                tenant_id=tenant_context.tenant_id,
                product_id=product_id,
                encrypted_items=encrypted_items,
            )
            await session.commit()
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(
        f"库存导入完成：新增 {added_count} 条，已存在 {existing_count} 条，输入内重复 {duplicated_input_count} 条。"
    )


@router.message(Command("inventory_status"))
async def inventory_status(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "products"):
        return
    product_id = _parse_optional_product_id(command.args or "")
    await _send_inventory_status(message, session_factory, tenant_context, product_id)


@router.message(Command("export_inventory"))
async def export_inventory(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if message.chat.type != "private":
        await message.answer("为避免卡密泄露，请在私聊中导出库存。")
        return
    if not await _ensure_permission_message(message, session_factory, tenant_context, "products"):
        return
    try:
        product_id, limit = _parse_inventory_export_args(command.args or "")
        crypto = TokenCrypto(settings)
    except RuntimeError:
        await message.answer("缺少 TOKEN_ENCRYPTION_KEY，不能导出敏感库存。")
        return
    except ValueError as exc:
        await message.answer(str(exc))
        return

    repo = ProductRepository()
    try:
        async with session_factory() as session:
            product, items = await repo.export_available_inventory_items(
                session=session,
                tenant_id=tenant_context.tenant_id,
                product_id=product_id,
                limit=limit,
            )
            if not items:
                await message.answer("没有可导出的可用库存。")
                return
            lines = [crypto.decrypt_token(item.content_encrypted) for item in items]
            actor = None
            if message.from_user is not None:
                actor = await TenantRepository().get_or_create_platform_user(session, message.from_user, settings)
            session.add(
                AuditLog(
                    tenant_id=tenant_context.tenant_id,
                    actor_user_id=actor.id if actor is not None else None,
                    action="inventory.available_exported",
                    target_type="product",
                    target_id=str(product.id),
                    metadata_json={
                        "product_id": product.id,
                        "exported_count": len(items),
                    },
                )
            )
            await session.commit()
    except ValueError as exc:
        await message.answer(str(exc))
        return

    filename = f"inventory-{product.id}-{datetime.now(timezone.utc):%Y%m%d%H%M%S}.txt"
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    await message.answer_document(
        BufferedInputFile(payload, filename=filename),
        caption=f"商品 #{product.id} 可用库存导出：{len(lines)} 条。",
    )


@router.message(Command("upload_file"))
async def upload_file(
    message: Message,
    command: CommandObject,
    bot: Bot,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "products"):
        return
    if message.document is None:
        await message.answer("请发送文件，并把文件说明/caption 设置为：/upload_file 商品ID")
        return

    try:
        product_id = int((command.args or "").strip())
    except ValueError:
        await message.answer("请提供文件商品 ID。示例：发送文件时 caption 填 /upload_file 1")
        return

    repo = ProductRepository()
    async with session_factory() as session:
        product, _ = await repo.get_product_with_default_variant(session, tenant_context.tenant_id, product_id)
    if product is None:
        await message.answer("商品不存在或无权限。")
        return
    if product.delivery_type != "file_download":
        await message.answer("只有 file_download 商品可以上传交付文件。")
        return
    if message.document.file_size is None:
        await message.answer("无法获取文件大小，已拒绝上传。")
        return
    if product.file_size_limit is not None and message.document.file_size > product.file_size_limit:
        await message.answer(f"文件超过限制，当前商品最大允许 {product.file_size_limit} 字节。")
        return

    try:
        file_storage = FileStorageService(settings)
        stored_file = await file_storage.store_telegram_document(
            bot=bot,
            document=message.document,
            tenant_id=tenant_context.tenant_id,
        )
        async with session_factory() as session:
            uploaded_file = await repo.create_uploaded_file(
                session=session,
                tenant_id=tenant_context.tenant_id,
                storage_key=stored_file.storage_key,
                original_filename=stored_file.original_filename,
                content_type=stored_file.content_type,
                size_bytes=stored_file.size_bytes,
                sha256=stored_file.sha256,
            )
            inspection = await FileInspectionService().inspect_uploaded_file(
                session=session,
                tenant_id=tenant_context.tenant_id,
                uploaded_file_id=uploaded_file.id,
                file_path=file_storage.resolve_storage_key(stored_file.storage_key),
                requested_by_user_id=tenant_context.owner_user_id,
            )
            if inspection.blocked:
                await session.commit()
                await message.answer(
                    "文件已上传但未绑定商品。\n\n"
                    f"扫描结果：{inspection.message}\n"
                    f"风险等级：{inspection.risk_level}"
                )
                return
            await repo.bind_delivery_file(session, tenant_context.tenant_id, product_id, uploaded_file.id)
            await session.commit()
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(
        f"文件已绑定到商品 #{product_id}。\n"
        f"文件名：{html.escape(stored_file.original_filename)}\n"
        f"大小：{stored_file.size_bytes} 字节\n\n"
        f"扫描结果：{inspection.message}\n"
        f"风险等级：{inspection.risk_level}\n\n"
        "确认无误后可使用 /publish_product 商品ID 上架。"
    )


@router.message(Command("file_status"))
async def file_status(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "products"):
        return
    try:
        product_id = int((command.args or "").strip())
    except ValueError:
        await message.answer("请提供商品 ID。示例：/file_status 1")
        return

    repo = ProductRepository()
    async with session_factory() as session:
        summary = await repo.get_delivery_file_summary(session, tenant_context.tenant_id, product_id)
    if summary is None:
        await message.answer("商品未绑定文件或无权限。")
        return

    product, uploaded_file, latest_job, risk_counts = summary
    job_status = latest_job.status if latest_job is not None else "none"
    error_message = latest_job.error_message if latest_job is not None and latest_job.error_message else "-"
    await message.answer(
        "文件扫描状态\n\n"
        f"商品：#{product.id} {html.escape(product.name)}\n"
        f"文件：{html.escape(uploaded_file.original_filename)}\n"
        f"状态：{uploaded_file.status}\n"
        f"大小：{uploaded_file.size_bytes} 字节\n"
        f"扫描任务：{job_status}\n"
        f"风险统计：low={risk_counts.get('low', 0)}，medium={risk_counts.get('medium', 0)}，high={risk_counts.get('high', 0)}\n"
        f"错误：{html.escape(error_message)}"
    )


@router.message(Command("set_invite_group"))
async def set_invite_group(
    message: Message,
    command: CommandObject,
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "products"):
        return

    try:
        product_id, chat_id = _parse_invite_group_args(command.args or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return

    repo = ProductRepository()
    async with session_factory() as session:
        product, _ = await repo.get_product_with_default_variant(session, tenant_context.tenant_id, product_id)
    if product is None:
        await message.answer("商品不存在或无权限。")
        return
    if product.delivery_type != "telegram_invite":
        await message.answer("只有 telegram_invite 商品可以绑定群 ID。")
        return

    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id, me.id)
    except Exception:
        await message.answer("无法验证群权限。请确认当前 Bot 已加入该群，并且群 ID 正确。")
        return

    raw_status = getattr(member, "status", "")
    status = str(getattr(raw_status, "value", raw_status)).lower()
    can_invite = status == "creator" or bool(getattr(member, "can_invite_users", False))
    if status not in {"administrator", "creator"}:
        await message.answer("当前 Bot 不是群管理员，不能生成邀请链接。")
        return
    if not can_invite:
        await message.answer("当前 Bot 缺少邀请用户权限，不能生成邀请链接。")
        return

    async with session_factory() as session:
        await repo.bind_telegram_invite_group(session, tenant_context.tenant_id, product_id, chat_id)
        await session.commit()
    await message.answer(f"群邀请商品 #{product_id} 已绑定群 ID：{chat_id}")


@router.message(Command("retry_delivery"))
async def retry_delivery(
    message: Message,
    command: CommandObject,
    bot: Bot,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "orders"):
        return

    out_trade_no = (command.args or "").strip()
    if not out_trade_no:
        await message.answer("请提供订单号。示例：/retry_delivery ORDxxxx")
        return

    service = PaymentService(settings)
    async with session_factory() as session:
        delivery_record_id = await service.get_retryable_delivery_id(
            session=session,
            tenant_id=tenant_context.tenant_id,
            out_trade_no=out_trade_no,
        )
        if delivery_record_id is None:
            await message.answer("没有找到可重试的发货记录。仅 pending/failed 状态可重试。")
            return
    error_message = await _send_delivery_record(bot, settings, session_factory, service, delivery_record_id)
    if error_message is not None:
        await message.answer(f"发货重试失败：{html.escape(error_message)}")
        return
    await message.answer(f"订单 {html.escape(out_trade_no)} 已重新发货。")


@router.message(Command("subscription"))
async def subscription(
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "subscription"):
        return
    async with session_factory() as session:
        status = await SubscriptionService().get_status(session, tenant_context.tenant_id)
    await message.answer(
        "订阅状态\n\n"
        f"租户状态：{status.status}\n"
        f"套餐：{status.plan_code or '-'}\n"
        f"试用到期：{_format_optional_datetime(status.trial_ends_at)}\n"
        f"订阅到期：{_format_optional_datetime(status.subscription_ends_at)}\n"
        f"当前月费：{settings.subscription_monthly_price} USDT\n\n"
        "续费：/renew_subscription 月数"
    )


@router.message(Command("renew_subscription"))
async def renew_subscription(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "subscription"):
        return
    try:
        months = _parse_subscription_months(command.args or "")
        async with session_factory() as session:
            subscription_order = await SubscriptionService().create_renewal_order(
                session=session,
                tenant_id=tenant_context.tenant_id,
                buyer_telegram_user_id=message.from_user.id if message.from_user else 0,
                months=months,
                monthly_price=settings.subscription_monthly_price,
            )
            await session.commit()
    except ValueError as exc:
        await message.answer(str(exc))
        return

    try:
        async with session_factory() as session:
            payment = await PaymentService(settings).create_payment_for_order(session, subscription_order.order_id)
            await session.commit()
    except PaymentUnavailableError:
        await message.answer(
            "续费订单已创建，但当前未启用 epusdt 支付配置。\n\n"
            f"订单号：{subscription_order.out_trade_no}\n"
            f"金额：{subscription_order.amount} {subscription_order.currency}"
        )
        return
    except Exception:
        await message.answer(
            "续费订单已创建，但支付链接创建失败。\n\n"
            f"订单号：{subscription_order.out_trade_no}"
        )
        return

    await message.answer(
        "续费订单已创建\n\n"
        f"订单号：{payment.out_trade_no}\n"
        f"月数：{subscription_order.months}\n"
        f"金额：{payment.amount} {payment.currency}\n"
        f"过期时间：{subscription_order.expires_at:%Y-%m-%d %H:%M:%S %Z}\n\n"
        f"支付链接：{payment.payment_url}"
    )


@router.message(Command("reconcile_payments"))
async def reconcile_payments(
    message: Message,
    command: CommandObject,
    bot: Bot,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "orders"):
        return
    try:
        limit = _parse_reconcile_limit(command.args or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return
    service = PaymentService(settings)
    try:
        async with session_factory() as session:
            result = await service.reconcile_pending_payments(
                session=session,
                tenant_id=tenant_context.tenant_id,
                limit=limit,
            )
            await session.commit()
    except Exception as exc:
        await message.answer(f"支付补偿查询失败：{html.escape(str(exc))}")
        return

    delivered_count = 0
    failed_count = 0
    for delivery_record_id in result.delivery_record_ids:
        error_message = await _send_delivery_record(bot, settings, session_factory, service, delivery_record_id)
        if error_message is None:
            delivered_count += 1
        else:
            failed_count += 1

    await message.answer(
        "支付补偿查询完成\n\n"
        f"检查：{result.checked_count} 笔\n"
        f"状态变更：{result.changed_count} 笔\n"
        f"已补发：{delivered_count} 笔\n"
        f"补发失败：{failed_count} 笔"
    )


@router.message(Command("payment_config"))
async def payment_config(
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "payments"):
        return
    try:
        async with session_factory() as session:
            status = await PaymentConfigService().get_tenant_epusdt_status(
                session,
                settings,
                tenant_context.tenant_id,
            )
    except RuntimeError as exc:
        await message.answer(str(exc))
        return

    await message.answer(
        "支付配置\n\n"
        f"作用域：{status.scope_type}\n"
        f"状态：{'启用' if status.enabled else '未启用'}\n"
        f"Base URL：{html.escape(status.base_url or '-')}\n"
        f"PID：{html.escape(_mask_value(status.pid or '-'))}\n"
        f"Token：{html.escape(status.token or '-')}\n"
        f"Network：{html.escape(status.network or '-')}\n\n"
        "设置租户 epusdt：/set_epusdt_config base_url | pid | secret_key\n"
        "停用租户 epusdt：/disable_epusdt_config"
    )


@router.message(Command("set_epusdt_config"))
async def set_epusdt_config(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "payments"):
        return
    try:
        base_url, pid, secret_key = _parse_epusdt_config_args(command.args or "")
        async with session_factory() as session:
            await PaymentConfigService().upsert_tenant_epusdt_config(
                session=session,
                settings=settings,
                tenant_id=tenant_context.tenant_id,
                base_url=base_url,
                pid=pid,
                secret_key=secret_key,
            )
            await session.commit()
    except (RuntimeError, ValueError) as exc:
        await message.answer(str(exc))
        return
    await message.answer("租户 epusdt 配置已保存并启用。密钥已加密保存，不会回显。")


@router.message(Command("disable_epusdt_config"))
async def disable_epusdt_config(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "payments"):
        return
    async with session_factory() as session:
        changed = await PaymentConfigService().disable_tenant_epusdt_config(session, tenant_context.tenant_id)
        await session.commit()
    await message.answer("租户 epusdt 配置已停用。" if changed else "当前没有租户 epusdt 配置。")


@router.message(Command("balance"))
async def balance(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "finance"):
        return
    await _send_wallet_status(message, session_factory, tenant_context)


@router.message(Command("withdraw"))
async def withdraw(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "finance"):
        return

    try:
        amount, network, address = _parse_withdraw_args(command.args or "")
        async with session_factory() as session:
            actor = None
            if message.from_user is not None:
                actor = await TenantRepository().get_or_create_platform_user(session, message.from_user, settings)
            withdrawal = await LedgerService().create_withdrawal_request(
                session=session,
                tenant_id=tenant_context.tenant_id,
                amount=amount,
                network=network,
                address=address,
                actor_user_id=actor.id if actor is not None else None,
            )
            await session.commit()
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(
        "提现申请已提交，等待平台人工审核。\n\n"
        f"提现 ID：#{withdrawal.id}\n"
        f"金额：{_format_decimal(withdrawal.amount)} {withdrawal.currency}\n"
        f"网络：{html.escape(withdrawal.network)}\n"
        f"地址：{html.escape(_mask_address(withdrawal.address))}\n\n"
        "冻结金额会在审核完成后扣除；若拒绝，会退回可用余额。"
    )
    await NotificationService(settings).notify_withdrawal_requested(
        WithdrawalSummary(
            withdrawal_id=withdrawal.id,
            tenant_id=withdrawal.tenant_id,
            amount=withdrawal.amount,
            currency=withdrawal.currency,
            network=withdrawal.network,
            address=withdrawal.address,
            status=withdrawal.status,
            requested_at=withdrawal.requested_at,
        )
    )


@router.message(Command("withdrawals"))
async def withdrawals(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "finance"):
        return
    try:
        limit = _parse_list_limit(command.args or "", "/withdrawals 20")
    except ValueError as exc:
        await message.answer(str(exc))
        return
    async with session_factory() as session:
        withdrawals = await LedgerService().list_withdrawals(
            session,
            tenant_id=tenant_context.tenant_id,
            limit=limit,
        )
    if not withdrawals:
        await message.answer("提现记录\n\n暂无提现记录。")
        return
    await message.answer(_format_withdrawals(withdrawals, include_tenant=False))


@router.message(Command("export_report"))
async def export_report(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "reports"):
        return
    if message.from_user is None:
        await message.answer("无法识别当前用户。")
        return
    try:
        report_type = _parse_report_type(command.args or "")
        async with session_factory() as session:
            actor = await TenantRepository().get_or_create_user_by_telegram_id(session, message.from_user.id)
            job = await ReportExportService().create_export_job(
                session=session,
                settings=settings,
                report_type=report_type,
                actor_user_id=actor.id,
                tenant_id=tenant_context.tenant_id,
                scope_type="tenant",
            )
            await session.commit()
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await message.answer(_format_export_job_created(job))


@router.message(Command("export_jobs"))
async def export_jobs(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "reports"):
        return
    try:
        limit = _parse_list_limit(command.args or "", "/export_jobs 20")
        async with session_factory() as session:
            jobs = await ReportExportService().list_export_jobs(
                session=session,
                settings=settings,
                tenant_id=tenant_context.tenant_id,
                limit=limit,
            )
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await message.answer(_format_export_jobs(jobs, include_tenant=False))


@router.message(Command("open_supply"))
async def open_supply(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
    tenant_feature_flags: Optional[Dict[str, bool]] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "supply"):
        return
    if not await _ensure_tenant_feature_message(message, tenant_feature_flags, "supplier"):
        return

    try:
        product_id, suggested_price, min_sale_price, requires_approval = _parse_open_supply_args(command.args or "")
        async with session_factory() as session:
            offer = await SupplyService().create_supplier_offer(
                session=session,
                supplier_tenant_id=tenant_context.tenant_id,
                product_id=product_id,
                suggested_price=suggested_price,
                min_sale_price=min_sale_price,
                requires_approval=requires_approval,
            )
            await session.commit()
    except ValueError as exc:
        await message.answer(str(exc))
        return

    min_price_text = _format_decimal(offer.min_sale_price) if offer.min_sale_price is not None else "不限"
    await message.answer(
        "供货商品已开放\n\n"
        f"供货 ID：#{offer.offer_id}\n"
        f"商品 ID：#{offer.product_id}\n"
        f"建议价：{_format_decimal(offer.suggested_price)} USDT\n"
        f"最低售价：{min_price_text}\n"
        f"代理审批：{'需要' if offer.requires_approval else '不需要'}\n\n"
        "代理商可在供货市场选择上架；需要审批时需先提交申请。"
    )


@router.message(Command("set_supply_approval"))
async def set_supply_approval(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
    tenant_feature_flags: Optional[Dict[str, bool]] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "supply"):
        return
    if not await _ensure_tenant_feature_message(message, tenant_feature_flags, "supplier"):
        return
    try:
        supplier_offer_id, requires_approval = _parse_supply_approval_args(command.args or "")
        async with session_factory() as session:
            actor = await TenantRepository().get_or_create_user_by_telegram_id(session, message.from_user.id)
            setting = await SupplyService().set_supplier_offer_approval(
                session=session,
                supplier_tenant_id=tenant_context.tenant_id,
                supplier_offer_id=supplier_offer_id,
                requires_approval=requires_approval,
                actor_user_id=actor.id,
            )
            await session.commit()
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await message.answer(
        "供货审批设置已更新\n\n"
        f"供货 ID：#{setting.offer_id}\n"
        f"代理审批：{'需要' if setting.requires_approval else '不需要'}"
    )


@router.message(Command("supply_market"))
async def supply_market(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
    tenant_feature_flags: Optional[Dict[str, bool]] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "supply"):
        return
    if not await _ensure_tenant_feature_message(message, tenant_feature_flags, "reseller"):
        return
    try:
        limit = _parse_list_limit(command.args or "", "/supply_market 20")
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await _send_supply_market(message, session_factory, tenant_context, limit, tenant_feature_flags)


@router.message(Command("apply_reseller"))
async def apply_reseller(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
    tenant_feature_flags: Optional[Dict[str, bool]] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "supply"):
        return
    if not await _ensure_tenant_feature_message(message, tenant_feature_flags, "reseller"):
        return
    try:
        supplier_offer_id = _parse_positive_int((command.args or "").strip(), "供货 ID")
        async with session_factory() as session:
            actor = await TenantRepository().get_or_create_user_by_telegram_id(session, message.from_user.id)
            application = await SupplyService().apply_reseller(
                session=session,
                reseller_tenant_id=tenant_context.tenant_id,
                supplier_offer_id=supplier_offer_id,
                requested_by_user_id=actor.id,
            )
            await session.commit()
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await message.answer(
        "代理申请已提交\n\n"
        f"供货 ID：#{application.supplier_offer_id}\n"
        f"商品：{html.escape(application.product_name)}\n"
        f"供应商：#{application.supplier_tenant_id} {html.escape(application.supplier_store_name)}\n"
        f"状态：{_reseller_rule_status_label(application.status)}\n\n"
        "供应商审核后会通知本店 owner。"
    )
    await NotificationService(settings).notify_reseller_application_requested(application)


@router.message(Command("reseller_applications"))
async def reseller_applications(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
    tenant_feature_flags: Optional[Dict[str, bool]] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "supply"):
        return
    if not await _ensure_tenant_feature_message(message, tenant_feature_flags, "supplier"):
        return
    try:
        limit = _parse_list_limit(command.args or "", "/reseller_applications 20")
    except ValueError as exc:
        await message.answer(str(exc))
        return
    async with session_factory() as session:
        applications = await SupplyService().list_reseller_applications(
            session,
            supplier_tenant_id=tenant_context.tenant_id,
            limit=limit,
        )
    await message.answer(_format_reseller_applications(applications, "待审核代理申请", supplier_view=True))


@router.message(Command("my_reseller_applications"))
async def my_reseller_applications(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
    tenant_feature_flags: Optional[Dict[str, bool]] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "supply"):
        return
    if not await _ensure_tenant_feature_message(message, tenant_feature_flags, "reseller"):
        return
    try:
        limit = _parse_list_limit(command.args or "", "/my_reseller_applications 20")
    except ValueError as exc:
        await message.answer(str(exc))
        return
    async with session_factory() as session:
        applications = await SupplyService().list_my_reseller_applications(
            session,
            reseller_tenant_id=tenant_context.tenant_id,
            limit=limit,
        )
    await message.answer(_format_reseller_applications(applications, "我的代理申请", supplier_view=False))


@router.message(Command("approve_reseller"))
async def approve_reseller(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
    tenant_feature_flags: Optional[Dict[str, bool]] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "supply"):
        return
    if not await _ensure_tenant_feature_message(message, tenant_feature_flags, "supplier"):
        return
    try:
        supplier_offer_id, reseller_tenant_id = _parse_reseller_review_args(command.args or "", "/approve_reseller 供货ID | 代理租户ID")
        async with session_factory() as session:
            actor = await TenantRepository().get_or_create_user_by_telegram_id(session, message.from_user.id)
            application = await SupplyService().approve_reseller(
                session=session,
                supplier_tenant_id=tenant_context.tenant_id,
                supplier_offer_id=supplier_offer_id,
                reseller_tenant_id=reseller_tenant_id,
                actor_user_id=actor.id,
            )
            await session.commit()
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await message.answer(_format_reseller_review_result(application, "代理申请已通过"))
    await NotificationService(settings).notify_reseller_application_reviewed(application)


@router.message(Command("reject_reseller"))
async def reject_reseller(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
    tenant_feature_flags: Optional[Dict[str, bool]] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "supply"):
        return
    if not await _ensure_tenant_feature_message(message, tenant_feature_flags, "supplier"):
        return
    try:
        supplier_offer_id, reseller_tenant_id, reason = _parse_reseller_reject_args(command.args or "")
        async with session_factory() as session:
            actor = await TenantRepository().get_or_create_user_by_telegram_id(session, message.from_user.id)
            application = await SupplyService().reject_reseller(
                session=session,
                supplier_tenant_id=tenant_context.tenant_id,
                supplier_offer_id=supplier_offer_id,
                reseller_tenant_id=reseller_tenant_id,
                actor_user_id=actor.id,
                reason=reason,
            )
            await session.commit()
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await message.answer(_format_reseller_review_result(application, "代理申请已拒绝"))
    await NotificationService(settings).notify_reseller_application_reviewed(application)


@router.message(Command("set_reseller_rule"))
async def set_reseller_rule(
    message: Message,
    command: CommandObject,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
    tenant_feature_flags: Optional[Dict[str, bool]] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "supply"):
        return
    if not await _ensure_tenant_feature_message(message, tenant_feature_flags, "supplier"):
        return
    try:
        supplier_offer_id, reseller_tenant_id, pricing_value, min_sale_price = _parse_reseller_rule_args(command.args or "")
        async with session_factory() as session:
            actor = await TenantRepository().get_or_create_user_by_telegram_id(session, message.from_user.id)
            application = await SupplyService().set_reseller_rule(
                session=session,
                supplier_tenant_id=tenant_context.tenant_id,
                supplier_offer_id=supplier_offer_id,
                reseller_tenant_id=reseller_tenant_id,
                actor_user_id=actor.id,
                pricing_value=pricing_value,
                min_sale_price=min_sale_price,
            )
            await session.commit()
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await message.answer(_format_reseller_review_result(application, "代理独立定价已更新"))
    await NotificationService(settings).notify_reseller_application_reviewed(application)


@router.message(Command("resell_offer"))
async def resell_offer(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
    tenant_feature_flags: Optional[Dict[str, bool]] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "supply"):
        return
    if not await _ensure_tenant_feature_message(message, tenant_feature_flags, "reseller"):
        return

    try:
        supplier_offer_id, sale_price, display_name = _parse_resell_offer_args(command.args or "")
        async with session_factory() as session:
            reseller_product = await SupplyService().create_reseller_product(
                session=session,
                reseller_tenant_id=tenant_context.tenant_id,
                supplier_offer_id=supplier_offer_id,
                sale_price=sale_price,
                display_name=display_name,
            )
            await session.commit()
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(
        "代理商品已上架\n\n"
        f"代理商品 ID：#{reseller_product.reseller_product_id}\n"
        f"供货 ID：#{reseller_product.supplier_offer_id}\n"
        f"展示名：{html.escape(reseller_product.display_name)}\n"
        f"售价：{_format_decimal(reseller_product.sale_price)} {reseller_product.currency}\n\n"
        "已上架代理商品会展示在买家 /products 列表。"
    )


@router.message(Command("reseller_products"))
async def reseller_products(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
    tenant_feature_flags: Optional[Dict[str, bool]] = None,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "supply"):
        return
    if not await _ensure_tenant_feature_message(message, tenant_feature_flags, "reseller"):
        return
    try:
        limit = _parse_list_limit(command.args or "", "/reseller_products 20")
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await _send_reseller_products(message, session_factory, tenant_context, limit, tenant_feature_flags)


@router.callback_query(F.data == "tenant:home")
async def callback_home(
    callback: CallbackQuery,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    await callback.answer()
    if callback.message is None or tenant_context is None:
        return
    store_name, settings = await _load_profile(session_factory, tenant_context)
    welcome = _setting_text(settings, "welcome", "欢迎光临，本店铺正在配置中。")
    can_manage = await _can_manage(session_factory, tenant_context, callback.from_user.id)
    await callback.message.answer(
        f"{html.escape(store_name)}\n\n{html.escape(welcome)}",
        reply_markup=_store_keyboard(can_manage),
    )


@router.callback_query(F.data == "tenant:products")
async def callback_products(
    callback: CallbackQuery,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
    tenant_feature_flags: Optional[Dict[str, bool]] = None,
) -> None:
    await callback.answer()
    if callback.message is None or tenant_context is None:
        return
    await _send_public_product_list(callback.message, session_factory, tenant_context, tenant_feature_flags)


@router.callback_query(F.data.startswith("tenant:buy:"))
async def callback_buy_product(
    callback: CallbackQuery,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
    tenant_feature_flags: Optional[Dict[str, bool]] = None,
) -> None:
    await callback.answer()
    if callback.message is None or tenant_context is None:
        return
    try:
        product_id = int(str(callback.data).split(":")[-1])
    except ValueError:
        await callback.message.answer("商品 ID 无效。")
        return
    await _create_order_for_buyer(
        callback.message,
        settings,
        session_factory,
        tenant_context,
        callback.from_user.id,
        product_id,
        tenant_feature_flags,
    )


@router.callback_query(F.data.startswith("tenant:buy_reseller:"))
async def callback_buy_reseller_product(
    callback: CallbackQuery,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
    tenant_feature_flags: Optional[Dict[str, bool]] = None,
) -> None:
    await callback.answer()
    if callback.message is None or tenant_context is None:
        return
    try:
        reseller_product_id = int(str(callback.data).split(":")[-1])
    except ValueError:
        await callback.message.answer("代理商品 ID 无效。")
        return
    await _create_reseller_order_for_buyer(
        callback.message,
        settings,
        session_factory,
        tenant_context,
        callback.from_user.id,
        reseller_product_id,
        tenant_feature_flags,
    )


@router.callback_query(F.data == "tenant:orders")
async def callback_orders(
    callback: CallbackQuery,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    await callback.answer()
    if callback.message is None or tenant_context is None:
        return
    await _send_buyer_orders(callback.message, session_factory, tenant_context, callback.from_user.id)


@router.callback_query(F.data == "tenant:support")
async def callback_support(
    callback: CallbackQuery,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    await callback.answer()
    if callback.message is None or tenant_context is None:
        return
    _, settings = await _load_profile(session_factory, tenant_context)
    await callback.message.answer(
        f"联系客服\n\n{html.escape(_setting_text(settings, 'support', '暂未配置客服联系方式。'))}",
        reply_markup=_back_home_keyboard(),
    )


@router.callback_query(F.data == "tenant:manage")
async def callback_manage(
    callback: CallbackQuery,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    await callback.answer()
    if callback.message is None or not await _ensure_can_manage_callback(callback, session_factory, tenant_context):
        return
    await callback.message.answer("商家管理\n\n请选择要管理的项目。", reply_markup=_manage_keyboard())


@router.callback_query(F.data == "tenant:settings")
async def callback_settings(
    callback: CallbackQuery,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    await callback.answer()
    if callback.message is None or not await _ensure_permission_callback(callback, session_factory, tenant_context, "settings"):
        return
    store_name, settings = await _load_profile(session_factory, tenant_context)
    await callback.message.answer(_settings_text(store_name, settings), reply_markup=_manage_keyboard())


@router.callback_query(F.data == "tenant:product_manage")
async def callback_product_manage(
    callback: CallbackQuery,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    await callback.answer()
    if callback.message is None or not await _ensure_permission_callback(callback, session_factory, tenant_context, "products"):
        return
    await _send_product_manage(callback.message, session_factory, tenant_context)


@router.callback_query(F.data == "tenant:admins")
async def callback_admins(
    callback: CallbackQuery,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    await callback.answer()
    if callback.message is None or not await _ensure_owner_callback(callback, session_factory, tenant_context):
        return
    await _send_admins(callback.message, session_factory, tenant_context)


@router.callback_query(F.data == "tenant:payments")
async def callback_payments(
    callback: CallbackQuery,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    await callback.answer()
    if callback.message is None or not await _ensure_permission_callback(callback, session_factory, tenant_context, "payments"):
        return
    await callback.message.answer(
        "支付设置\n\n"
        "租户配置优先，未配置时使用平台级 epusdt 默认配置。\n\n"
        "查看：/payment_config\n"
        "设置：/set_epusdt_config base_url | pid | secret_key\n"
        "停用：/disable_epusdt_config"
    )


@router.callback_query(F.data == "tenant:wallet")
async def callback_wallet(
    callback: CallbackQuery,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    await callback.answer()
    if callback.message is None or not await _ensure_permission_callback(callback, session_factory, tenant_context, "finance"):
        return
    await _send_wallet_status(callback.message, session_factory, tenant_context)


@router.callback_query(F.data == "tenant:supply")
async def callback_supply(
    callback: CallbackQuery,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
    tenant_feature_flags: Optional[Dict[str, bool]] = None,
) -> None:
    await callback.answer()
    if callback.message is None or not await _ensure_permission_callback(callback, session_factory, tenant_context, "supply"):
        return
    await _send_supply_manage(callback.message, session_factory, tenant_context, tenant_feature_flags)


@router.callback_query(F.data == "tenant:reports")
async def callback_reports(
    callback: CallbackQuery,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext] = None,
) -> None:
    await callback.answer()
    if callback.message is None or not await _ensure_permission_callback(callback, session_factory, tenant_context, "reports"):
        return
    await _send_reports_manage(callback.message)


async def _set_text_setting(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext],
    key: str,
    label: str,
    max_length: int,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "settings"):
        return
    value = (command.args or "").strip()
    if not value:
        await message.answer(f"{label}不能为空。示例：/{command.command} 这里填写{label}")
        return
    if len(value) > max_length:
        await message.answer(f"{label}不能超过 {max_length} 个字符。")
        return

    repo = TenantRepository()
    async with session_factory() as session:
        await repo.upsert_setting(session, tenant_context.tenant_id, key, {"text": value})
        await session.commit()
    await message.answer(f"{label}已更新。")


async def _send_product_manage(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: TenantContext,
) -> None:
    await message.answer(
        "商品管理\n\n"
        "新增商品：\n"
        "/add_product 商品名 | 价格 | 发货类型 | 描述\n\n"
        f"发货类型：{', '.join(sorted(ALLOWED_DELIVERY_TYPES))}\n"
        "查看商品：/list_products\n"
        "上架商品：/publish_product 商品ID\n"
        "下架商品：/hide_product 商品ID\n\n"
        "设置排序：/set_product_sort 商品ID | 排序值\n\n"
        "设置分类：/set_product_category 商品ID | 分类，使用 - 清空\n\n"
        "导入库存：\n"
        "/add_inventory 商品ID | 卡密1 | 卡密2\n"
        "或：/add_inventory 商品ID 后换行逐条填写\n"
        "查看库存：/inventory_status [商品ID]\n\n"
        "导出可用卡密：/export_inventory 商品ID [数量]\n\n"
        "上传文件商品：发送文件时将 caption 设置为 /upload_file 商品ID\n"
        "查看文件扫描：/file_status 商品ID\n\n"
        "绑定群邀请：/set_invite_group 商品ID | 群ID\n"
        "重试发货：/retry_delivery 订单号\n\n"
        "查看支付配置：/payment_config\n"
        "设置 epusdt：/set_epusdt_config base_url | pid | secret_key\n"
        "支付补偿查询：/reconcile_payments [数量]\n\n"
        "API Key：/api_keys [数量]\n"
        "创建 API Key：/create_api_key 名称 | scope1,scope2 | IP或CIDR\n"
        "撤销 API Key：/revoke_api_key KeyID\n\n"
        "网页后台绑定码：/admin_web_code\n\n"
        "订阅状态：/subscription\n"
        "续费订阅：/renew_subscription 月数"
    )
    await _send_product_list(message, session_factory, tenant_context)


async def _send_wallet_status(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: TenantContext,
) -> None:
    async with session_factory() as session:
        balance = await LedgerService().get_balance(session, tenant_context.tenant_id)
        await session.commit()
    await message.answer(
        "账本余额\n\n"
        f"待结算：{_format_decimal(balance.pending_balance)} {balance.currency}\n"
        f"可提现：{_format_decimal(balance.available_balance)} {balance.currency}\n"
        f"冻结中：{_format_decimal(balance.frozen_balance)} {balance.currency}\n\n"
        "发起提现：/withdraw 金额 | 网络 | 地址\n"
        "提现记录：/withdrawals [数量]"
    )


async def _send_reports_manage(message: Message) -> None:
    await message.answer(
        "报表导出\n\n"
        "创建导出任务：/export_report orders|payments|inventory|ledger\n"
        "查看导出任务：/export_jobs [数量]\n\n"
        "报表由后台异步生成。完成后会显示 24 小时有效下载链接。"
    )


async def _send_admins(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: TenantContext,
) -> None:
    repo = TenantRepository()
    async with session_factory() as session:
        members = await repo.list_members(session, tenant_context.tenant_id)
    lines = [
        "管理员和权限",
        "owner 可以增删管理员；admin 可以使用商家管理功能，但不能增删管理员。",
    ]
    for member, user in members:
        username = f"@{user.username}" if user.username else "-"
        lines.append(
            f"{member.role}｜Telegram ID：{user.telegram_user_id}｜用户名：{html.escape(username)}"
        )
    lines.append("添加：admin：/add_admin Telegram用户ID")
    lines.append("移除：admin：/remove_admin Telegram用户ID")
    lines.append("权限：/permissions")
    lines.append("审计：/audit_logs [数量]")
    await message.answer("\n\n".join(lines))


async def _send_supply_manage(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: TenantContext,
    tenant_feature_flags: Optional[Dict[str, bool]] = None,
) -> None:
    await message.answer(
        "供货代理\n\n"
        "开放自营商品：/open_supply 商品ID | 建议价 | 最低售价 | 是否审批\n"
        "设置审批：/set_supply_approval 供货ID | on/off\n"
        "浏览供货市场：/supply_market [数量]\n"
        "申请代理：/apply_reseller 供货ID\n"
        "待审申请：/reseller_applications [数量]\n"
        "我的申请：/my_reseller_applications [数量]\n"
        "审批代理：/approve_reseller 供货ID | 代理租户ID\n"
        "独立定价：/set_reseller_rule 供货ID | 代理租户ID | 成本 | 最低售价\n"
        "上架代理商品：/resell_offer 供货ID | 售价 | 展示名\n"
        "查看代理商品：/reseller_products [数量]\n\n"
        "已上架代理商品会出现在买家 /products 列表；代理订单统一使用平台托管收款并自动分账。"
    )
    await _send_supply_market(message, session_factory, tenant_context, 10, tenant_feature_flags)


async def _send_supply_market(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: TenantContext,
    limit: int,
    tenant_feature_flags: Optional[Dict[str, bool]] = None,
) -> None:
    if not _tenant_feature_enabled(tenant_feature_flags, "reseller"):
        await message.answer(tenant_feature_disabled_message("reseller"))
        return
    async with session_factory() as session:
        offers = await SupplyService().list_market_offers(session, tenant_context.tenant_id, limit)
    if not offers:
        await message.answer("供货市场\n\n暂无可代理商品。")
        return
    await message.answer(_format_supply_market(offers))


async def _send_reseller_products(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: TenantContext,
    limit: int,
    tenant_feature_flags: Optional[Dict[str, bool]] = None,
) -> None:
    if not _tenant_feature_enabled(tenant_feature_flags, "reseller"):
        await message.answer(tenant_feature_disabled_message("reseller"))
        return
    async with session_factory() as session:
        products = await SupplyService().list_reseller_products(session, tenant_context.tenant_id, limit)
    if not products:
        await message.answer("我的代理商品\n\n暂无已上架代理商品。")
        return
    await message.answer(_format_reseller_products(products))


async def _send_product_list(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: TenantContext,
) -> None:
    repo = ProductRepository()
    async with session_factory() as session:
        products = await repo.list_products(session, tenant_context.tenant_id)
    if not products:
        await message.answer("当前还没有商品。")
        return
    await message.answer(_format_product_list(products))


async def _set_product_status_command(
    message: Message,
    command: CommandObject,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext],
    status: str,
    action_label: str,
) -> None:
    if not await _ensure_permission_message(message, session_factory, tenant_context, "products"):
        return
    try:
        product_id = int((command.args or "").strip())
    except ValueError:
        await message.answer(f"请提供商品 ID。示例：/{command.command} 1")
        return

    repo = ProductRepository()
    try:
        async with session_factory() as session:
            changed = await repo.set_product_status(session, tenant_context.tenant_id, product_id, status)
            await session.commit()
    except ValueError as exc:
        await message.answer(str(exc))
        return
    if not changed:
        await message.answer("商品不存在或无权限。")
        return
    await message.answer(f"商品 #{product_id} 已{action_label}。")


async def _send_inventory_status(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: TenantContext,
    product_id: Optional[int] = None,
) -> None:
    repo = ProductRepository()
    async with session_factory() as session:
        products = await repo.list_products(session, tenant_context.tenant_id)
        summary = await repo.inventory_summary(session, tenant_context.tenant_id, product_id)

    product_map = {product.id: product for product, _, _ in products}
    if product_id is not None:
        product_map = {key: value for key, value in product_map.items() if key == product_id}
    if not product_map:
        await message.answer("商品不存在或无权限。")
        return

    lines = ["库存统计"]
    for item_product_id, product in product_map.items():
        status_counts = summary.get(item_product_id, {})
        lines.append(
            f"#{item_product_id} {html.escape(product.name)}\n"
            f"available：{status_counts.get('available', 0)}｜"
            f"locked：{status_counts.get('locked', 0)}｜"
            f"used：{status_counts.get('used', 0)}"
        )
    await message.answer("\n\n".join(lines))


async def _send_public_product_list(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: TenantContext,
    tenant_feature_flags: Optional[Dict[str, bool]] = None,
) -> None:
    feature_flags = _normalized_tenant_feature_flags(tenant_feature_flags)
    repo = ProductRepository()
    async with session_factory() as session:
        tenant = await TenantRepository().get_tenant(session, tenant_context.tenant_id)
        products = (
            await repo.list_public_products(session, tenant_context.tenant_id)
            if feature_flags["self_sale"]
            else []
        )
        reseller_products = (
            await SupplyService().list_public_reseller_products(session, tenant_context.tenant_id)
            if feature_flags["reseller"]
            else []
        )
    if not products and not reseller_products:
        await message.answer("商品列表\n\n当前店铺还没有上架商品。", reply_markup=_back_home_keyboard())
        return

    lines = ["商品列表"]
    buttons = []
    can_accept_orders = tenant is not None and tenant.status in ACTIVE_TENANT_STATUSES
    if not can_accept_orders:
        lines.append("店铺当前不可下单。")
    for product, variant, available_count in products:
        price = variant.price if variant else product.suggested_price
        stock_text = "可购买"
        if product.delivery_type in {"card_pool", "card_fixed"} and available_count <= 0:
            stock_text = "缺货"
        if product.delivery_type == "file_download" and product.delivery_file_id is None:
            stock_text = "未绑定文件"
        if product.delivery_type == "telegram_invite" and product.telegram_chat_id is None:
            stock_text = "未绑定群"
        lines.append(
            f"#{product.id} {html.escape(product.name)}\n"
            f"价格：{price} {product.currency}｜发货：{product.delivery_type}｜{stock_text}"
        )
        if stock_text == "可购买" and can_accept_orders:
            buttons.append([InlineKeyboardButton(text=f"购买 #{product.id}", callback_data=f"tenant:buy:{product.id}")])
    for reseller_product in reseller_products:
        stock_text = _public_reseller_stock_label(reseller_product.delivery_type, reseller_product.available_count)
        lines.append(
            f"代理商品 #{reseller_product.reseller_product_id} {html.escape(reseller_product.display_name)}\n"
            f"价格：{_format_decimal(reseller_product.sale_price)} {reseller_product.currency}｜"
            f"发货：{reseller_product.delivery_type}｜{stock_text}"
        )
        if stock_text == "可购买" and can_accept_orders:
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"购买代理 #{reseller_product.reseller_product_id}",
                        callback_data=f"tenant:buy_reseller:{reseller_product.reseller_product_id}",
                    )
                ]
            )
    buttons.append([InlineKeyboardButton(text="返回首页", callback_data="tenant:home")])
    await message.answer("\n\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


async def _send_buyer_orders(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: TenantContext,
    buyer_telegram_user_id: int,
) -> None:
    async with session_factory() as session:
        orders = await OrderService().list_buyer_orders(
            session=session,
            tenant_id=tenant_context.tenant_id,
            buyer_telegram_user_id=buyer_telegram_user_id,
        )
    if not orders:
        await message.answer("我的订单\n\n暂无订单。", reply_markup=_back_home_keyboard())
        return

    status_labels = {
        "pending": "待支付",
        "paid": "已支付",
        "delivered": "已发货",
        "completed": "已完成",
        "cancelled": "已取消",
        "expired": "已过期",
        "partially_refunded": "部分退款",
        "refunded": "已退款",
    }
    lines = ["我的订单"]
    for order in orders:
        lines.append(
            f"{html.escape(order.product_name)}\n"
            f"订单号：{html.escape(order.out_trade_no)}\n"
            f"金额：{order.amount} {order.currency}｜状态：{status_labels.get(order.status, order.status)}\n"
            f"过期时间：{order.expires_at:%Y-%m-%d %H:%M:%S %Z}"
        )
    await message.answer("\n\n".join(lines), reply_markup=_back_home_keyboard())


async def _create_order_for_buyer(
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: TenantContext,
    buyer_telegram_user_id: int,
    product_id: int,
    tenant_feature_flags: Optional[Dict[str, bool]] = None,
) -> None:
    if not _tenant_feature_enabled(tenant_feature_flags, "self_sale"):
        await message.answer(tenant_feature_disabled_message("self_sale"))
        return
    order_timeout_minutes = await _order_timeout_minutes(session_factory, tenant_context)
    async with session_factory() as session:
        try:
            created_order = await OrderService().create_self_order(
                session=session,
                tenant_id=tenant_context.tenant_id,
                buyer_telegram_user_id=buyer_telegram_user_id,
                product_id=product_id,
                order_timeout_minutes=order_timeout_minutes,
            )
            await session.commit()
        except OrderCreationRiskBlocked as exc:
            await session.commit()
            await message.answer(str(exc))
            return
        except ValueError as exc:
            await message.answer(str(exc))
            return

    try:
        async with session_factory() as session:
            payment = await PaymentService(settings).create_payment_for_order(session, created_order.order_id)
            await session.commit()
    except PaymentUnavailableError:
        await message.answer(
            "订单已创建\n\n"
            f"订单号：{created_order.out_trade_no}\n"
            f"金额：{created_order.amount} {created_order.currency}\n"
            f"过期时间：{created_order.expires_at:%Y-%m-%d %H:%M:%S %Z}\n\n"
            "当前未启用 epusdt 支付配置，订单会在超时后自动释放库存。"
        )
        return
    except Exception:
        await message.answer(
            "订单已创建，但支付链接创建失败。\n\n"
            f"订单号：{created_order.out_trade_no}\n"
            "请稍后重试或联系客服，未支付订单会在超时后自动释放库存。"
        )
        return

    await message.answer(
        "订单已创建\n\n"
        f"订单号：{payment.out_trade_no}\n"
        f"金额：{payment.amount} {payment.currency}\n"
        f"过期时间：{created_order.expires_at:%Y-%m-%d %H:%M:%S %Z}\n\n"
        f"支付链接：{payment.payment_url}"
    )


async def _create_reseller_order_for_buyer(
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: TenantContext,
    buyer_telegram_user_id: int,
    reseller_product_id: int,
    tenant_feature_flags: Optional[Dict[str, bool]] = None,
) -> None:
    if not _tenant_feature_enabled(tenant_feature_flags, "reseller"):
        await message.answer(tenant_feature_disabled_message("reseller"))
        return
    order_timeout_minutes = await _order_timeout_minutes(session_factory, tenant_context)
    async with session_factory() as session:
        try:
            created_order = await OrderService().create_reseller_order(
                session=session,
                tenant_id=tenant_context.tenant_id,
                buyer_telegram_user_id=buyer_telegram_user_id,
                reseller_product_id=reseller_product_id,
                order_timeout_minutes=order_timeout_minutes,
            )
            await session.commit()
        except OrderCreationRiskBlocked as exc:
            await session.commit()
            await message.answer(str(exc))
            return
        except ValueError as exc:
            await message.answer(str(exc))
            return

    try:
        async with session_factory() as session:
            payment = await PaymentService(settings).create_payment_for_order(session, created_order.order_id)
            await session.commit()
    except PaymentUnavailableError as exc:
        await message.answer(
            "代理订单已创建\n\n"
            f"订单号：{created_order.out_trade_no}\n"
            f"金额：{created_order.amount} {created_order.currency}\n"
            f"过期时间：{created_order.expires_at:%Y-%m-%d %H:%M:%S %Z}\n\n"
            f"{str(exc)}，订单会在超时后自动释放库存。"
        )
        return
    except Exception:
        await message.answer(
            "代理订单已创建，但支付链接创建失败。\n\n"
            f"订单号：{created_order.out_trade_no}\n"
            "请稍后重试或联系客服，未支付订单会在超时后自动释放库存。"
        )
        return

    await message.answer(
        "代理订单已创建\n\n"
        f"订单号：{payment.out_trade_no}\n"
        f"金额：{payment.amount} {payment.currency}\n"
        f"过期时间：{created_order.expires_at:%Y-%m-%d %H:%M:%S %Z}\n\n"
        f"支付链接：{payment.payment_url}"
    )


async def _send_delivery_record(
    bot: Bot,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    service: PaymentService,
    delivery_record_id: int,
) -> Optional[str]:
    async with session_factory() as session:
        instruction = await service.claim_delivery(session, delivery_record_id)
        await session.commit()
    if instruction is None:
        return "发货记录当前不可重试，可能已被其他任务处理。"

    try:
        crypto = TokenCrypto(settings)
        await send_delivery_instruction(bot, settings, crypto, instruction)
    except Exception as exc:
        async with session_factory() as session:
            await service.mark_delivery_failed(session, instruction.delivery_record_id, str(exc))
            await session.commit()
        return str(exc)

    async with session_factory() as session:
        await service.mark_delivery_sent(session, instruction.delivery_record_id)
        await session.commit()
    return None


def _normalized_tenant_feature_flags(tenant_feature_flags: Optional[Dict[str, bool]]) -> Dict[str, bool]:
    flags = dict(DEFAULT_TENANT_FEATURE_FLAGS)
    if tenant_feature_flags is not None:
        for key in DEFAULT_TENANT_FEATURE_FLAGS:
            if key in tenant_feature_flags:
                flags[key] = bool(tenant_feature_flags[key])
    return flags


def _tenant_feature_enabled(tenant_feature_flags: Optional[Dict[str, bool]], feature: str) -> bool:
    return tenant_feature_enabled(_normalized_tenant_feature_flags(tenant_feature_flags), feature)


async def _ensure_tenant_feature_message(
    message: Message,
    tenant_feature_flags: Optional[Dict[str, bool]],
    feature: str,
) -> bool:
    if _tenant_feature_enabled(tenant_feature_flags, feature):
        return True
    await message.answer(tenant_feature_disabled_message(feature))
    return False


async def _order_timeout_minutes(
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: TenantContext,
) -> int:
    _, settings = await _load_profile(session_factory, tenant_context)
    value = settings.get("order_timeout_minutes", {}).get("value", 15)
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        return 15
    return min(max(timeout, 1), 1440)


async def _load_profile(
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: TenantContext,
    tenant_settings: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[str, Dict[str, Dict[str, Any]]]:
    repo = TenantRepository()
    async with session_factory() as session:
        tenant = await repo.get_tenant(session, tenant_context.tenant_id)
        settings = (
            tenant_settings
            if tenant_settings is not None
            else await repo.get_settings(session, tenant_context.tenant_id)
        )
    store_name = tenant.store_name if tenant is not None else tenant_context.store_name
    return store_name, settings


async def _can_manage(
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext],
    telegram_user_id: int,
) -> bool:
    if tenant_context is None or telegram_user_id <= 0:
        return False
    repo = TenantRepository()
    async with session_factory() as session:
        return await repo.can_manage_settings(session, tenant_context.tenant_id, telegram_user_id)


async def _has_permission(
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext],
    telegram_user_id: int,
    permission: str,
) -> bool:
    if tenant_context is None or telegram_user_id <= 0:
        return False
    repo = TenantRepository()
    async with session_factory() as session:
        return await repo.has_permission(session, tenant_context.tenant_id, telegram_user_id, permission)


async def _is_owner(
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext],
    telegram_user_id: int,
) -> bool:
    if tenant_context is None or telegram_user_id <= 0:
        return False
    repo = TenantRepository()
    async with session_factory() as session:
        return await repo.is_owner(session, tenant_context.tenant_id, telegram_user_id)


async def _ensure_can_manage_message(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext],
) -> bool:
    if not await _ensure_private_admin_message(message):
        return False
    telegram_user_id = message.from_user.id if message.from_user else 0
    if await _can_manage(session_factory, tenant_context, telegram_user_id):
        return True
    await message.answer("无权限。只有租户 owner 或 admin 可以管理店铺。")
    return False


async def _ensure_permission_message(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext],
    permission: str,
) -> bool:
    if not await _ensure_private_admin_message(message):
        return False
    telegram_user_id = message.from_user.id if message.from_user else 0
    if await _has_permission(session_factory, tenant_context, telegram_user_id, permission):
        return True
    await message.answer(f"无权限。需要权限：{PERMISSION_LABELS.get(permission, permission)}。")
    return False


async def _ensure_owner_message(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext],
) -> bool:
    if not await _ensure_private_admin_message(message):
        return False
    telegram_user_id = message.from_user.id if message.from_user else 0
    if await _is_owner(session_factory, tenant_context, telegram_user_id):
        return True
    await message.answer("无权限。只有租户 owner 可以管理管理员。")
    return False


async def _ensure_can_manage_callback(
    callback: CallbackQuery,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext],
) -> bool:
    if not await _ensure_private_admin_callback(callback):
        return False
    if await _can_manage(session_factory, tenant_context, callback.from_user.id):
        return True
    if callback.message:
        await callback.message.answer("无权限。只有租户 owner 或 admin 可以管理店铺。")
    return False


async def _ensure_owner_callback(
    callback: CallbackQuery,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext],
) -> bool:
    if not await _ensure_private_admin_callback(callback):
        return False
    if await _is_owner(session_factory, tenant_context, callback.from_user.id):
        return True
    if callback.message:
        await callback.message.answer("无权限。只有租户 owner 可以管理管理员和权限。")
    return False


async def _ensure_permission_callback(
    callback: CallbackQuery,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: Optional[TenantContext],
    permission: str,
) -> bool:
    if not await _ensure_private_admin_callback(callback):
        return False
    if await _has_permission(session_factory, tenant_context, callback.from_user.id, permission):
        return True
    if callback.message:
        await callback.message.answer(f"无权限。需要权限：{PERMISSION_LABELS.get(permission, permission)}。")
    return False


async def _ensure_private_admin_message(message: Message) -> bool:
    if _message_chat_type(message) == "private":
        return True
    await message.answer("管理功能请在私聊中使用。")
    return False


async def _ensure_private_admin_callback(callback: CallbackQuery) -> bool:
    if callback.message is not None and _message_chat_type(callback.message) == "private":
        return True
    if callback.message:
        await callback.message.answer("管理功能请在私聊中使用。")
    return False


def _message_chat_type(message: Message) -> str:
    return str(getattr(getattr(message, "chat", None), "type", "private"))


def _setting_text(settings: Dict[str, Dict[str, Any]], key: str, default: str) -> str:
    value = settings.get(key, {})
    return str(value.get("text") or default)


def _settings_text(store_name: str, settings: Dict[str, Dict[str, Any]]) -> str:
    timeout = settings.get("order_timeout_minutes", {}).get("value", 15)
    feature_flags = settings.get("feature_flags", {})
    return (
        "店铺设置\n\n"
        f"店铺名称：{html.escape(store_name)}\n"
        f"欢迎语：{html.escape(_setting_text(settings, 'welcome', '欢迎光临，本店铺正在配置中。'))}\n"
        f"客服信息：{html.escape(_setting_text(settings, 'support', '暂未配置客服联系方式。'))}\n"
        f"订单超时：{timeout} 分钟\n"
        f"自营：{'开启' if feature_flags.get('self_sale', True) else '关闭'}\n"
        f"供货：{'开启' if feature_flags.get('supplier', False) else '关闭'}\n"
        f"代理：{'开启' if feature_flags.get('reseller', False) else '关闭'}\n\n"
        "可用命令：\n"
        "/set_store_name 店铺名称\n"
        "/set_welcome 欢迎语\n"
        "/set_support 客服信息\n"
        "/set_order_timeout 分钟数"
    )


def _store_keyboard(can_manage: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="商品列表", callback_data="tenant:products"),
            InlineKeyboardButton(text="我的订单", callback_data="tenant:orders"),
        ],
        [InlineKeyboardButton(text="联系客服", callback_data="tenant:support")],
    ]
    if can_manage:
        rows.append([InlineKeyboardButton(text="商家管理", callback_data="tenant:manage")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _manage_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="店铺设置", callback_data="tenant:settings")],
            [InlineKeyboardButton(text="商品管理", callback_data="tenant:product_manage")],
            [InlineKeyboardButton(text="供货代理", callback_data="tenant:supply")],
            [
                InlineKeyboardButton(text="账本提现", callback_data="tenant:wallet"),
                InlineKeyboardButton(text="报表导出", callback_data="tenant:reports"),
            ],
            [
                InlineKeyboardButton(text="管理员和权限", callback_data="tenant:admins"),
                InlineKeyboardButton(text="支付设置", callback_data="tenant:payments"),
            ],
            [InlineKeyboardButton(text="返回首页", callback_data="tenant:home")],
        ]
    )


def _back_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="返回首页", callback_data="tenant:home")]]
    )


def _parse_add_product_args(raw_args: str) -> Tuple[str, Decimal, str, Optional[str]]:
    parts = [part.strip() for part in raw_args.split("|")]
    if len(parts) < 3:
        raise ValueError(
            "格式错误。示例：\n"
            "/add_product 测试卡密 | 9.9 | card_pool | 自动发货测试商品"
        )

    name = parts[0]
    if not 2 <= len(name) <= 255:
        raise ValueError("商品名长度应为 2-255 个字符。")

    try:
        price = Decimal(parts[1])
    except (InvalidOperation, ValueError):
        raise ValueError("价格格式错误。示例：9.9")
    if price <= 0:
        raise ValueError("价格必须大于 0。")

    delivery_type = parts[2]
    if delivery_type not in ALLOWED_DELIVERY_TYPES:
        raise ValueError(f"发货类型不支持，可选：{', '.join(sorted(ALLOWED_DELIVERY_TYPES))}")

    description = parts[3] if len(parts) >= 4 and parts[3] else None
    return name, price, delivery_type, description


def _parse_inventory_args(raw_args: str) -> Tuple[int, List[str], int]:
    raw_value = raw_args.strip()
    if not raw_value:
        raise ValueError(
            "格式错误。示例：\n"
            "/add_inventory 1 | card-a | card-b\n"
            "或：/add_inventory 1 后换行逐条填写库存"
        )

    if "\n" in raw_value:
        lines = [line.strip() for line in raw_value.splitlines() if line.strip()]
        product_id_text = lines[0]
        raw_items = lines[1:]
    else:
        parts = [part.strip() for part in raw_value.split("|") if part.strip()]
        product_id_text = parts[0] if parts else ""
        raw_items = parts[1:]

    try:
        product_id = int(product_id_text)
    except ValueError:
        raise ValueError("商品 ID 必须是数字。")
    if product_id <= 0:
        raise ValueError("商品 ID 必须大于 0。")

    seen = set()
    items = []
    duplicated_input_count = 0
    for item in raw_items:
        if item in seen:
            duplicated_input_count += 1
            continue
        seen.add(item)
        items.append(item)

    if not items:
        raise ValueError("没有可导入的库存内容。")
    if len(items) > 500:
        raise ValueError("单次最多导入 500 条库存。")
    return product_id, items, duplicated_input_count


def _parse_product_sort_args(raw_args: str) -> Tuple[int, int]:
    parts = [part.strip() for part in raw_args.replace("|", " ").split() if part.strip()]
    if len(parts) != 2:
        raise ValueError("格式错误。示例：/set_product_sort 商品ID | 排序值")
    try:
        product_id = int(parts[0])
        sort_order = int(parts[1])
    except ValueError:
        raise ValueError("商品 ID 和排序值必须是整数。")
    if product_id <= 0:
        raise ValueError("商品 ID 必须大于 0。")
    if sort_order < -100000 or sort_order > 100000:
        raise ValueError("排序值范围为 -100000 到 100000。")
    return product_id, sort_order


def _parse_product_category_args(raw_args: str) -> Tuple[int, Optional[str]]:
    parts = [part.strip() for part in raw_args.split("|", 1)]
    if len(parts) != 2 or not parts[0]:
        raise ValueError("格式错误。示例：/set_product_category 商品ID | 分类，使用 - 清空")
    try:
        product_id = int(parts[0])
    except ValueError:
        raise ValueError("商品 ID 必须是数字。")
    if product_id <= 0:
        raise ValueError("商品 ID 必须大于 0。")
    category = parts[1].strip()
    if not category or category == "-":
        return product_id, None
    if len(category) > 128:
        raise ValueError("商品分类不能超过 128 个字符。")
    if any(ord(char) < 32 or ord(char) == 127 for char in category):
        raise ValueError("商品分类不能包含控制字符。")
    return product_id, category


def _parse_inventory_export_args(raw_args: str) -> Tuple[int, int]:
    parts = [part.strip() for part in raw_args.replace("|", " ").split() if part.strip()]
    if not parts:
        raise ValueError("格式错误。示例：/export_inventory 商品ID [数量]")
    try:
        product_id = int(parts[0])
    except ValueError:
        raise ValueError("商品 ID 必须是数字。")
    if product_id <= 0:
        raise ValueError("商品 ID 必须大于 0。")
    limit = 1000
    if len(parts) >= 2:
        try:
            limit = int(parts[1])
        except ValueError:
            raise ValueError("导出数量必须是数字。")
    if len(parts) > 2:
        raise ValueError("格式错误。示例：/export_inventory 商品ID [数量]")
    if limit < 1 or limit > 5000:
        raise ValueError("单次导出数量范围为 1-5000。")
    return product_id, limit


def _parse_optional_product_id(raw_args: str) -> Optional[int]:
    value = raw_args.strip()
    if not value:
        return None
    try:
        product_id = int(value)
    except ValueError:
        return None
    return product_id if product_id > 0 else None


def _parse_invite_group_args(raw_args: str) -> Tuple[int, int]:
    parts = [part.strip() for part in raw_args.split("|") if part.strip()]
    if len(parts) != 2:
        raise ValueError("格式错误。示例：/set_invite_group 1 | -1001234567890")
    try:
        product_id = int(parts[0])
        chat_id = int(parts[1])
    except ValueError:
        raise ValueError("商品 ID 和群 ID 必须是数字。")
    if product_id <= 0:
        raise ValueError("商品 ID 必须大于 0。")
    return product_id, chat_id


def _parse_permission_args(raw_args: str) -> Tuple[str, bool]:
    parts = [part.strip() for part in raw_args.split("|")]
    if len(parts) != 2 or not all(parts):
        raise ValueError("格式错误。示例：/set_permission products | off")
    permission = parts[0]
    if permission not in PERMISSION_LABELS:
        raise ValueError(f"权限不存在，可选：{', '.join(PERMISSION_LABELS.keys())}")
    return permission, _parse_bool(parts[1])


def _parse_open_supply_args(raw_args: str) -> Tuple[int, Decimal, Optional[Decimal], Optional[bool]]:
    parts = [part.strip() for part in raw_args.split("|")]
    if len(parts) not in {2, 3, 4} or not parts[0] or not parts[1]:
        raise ValueError("格式错误。示例：/open_supply 1 | 19.9 | 15 | on")

    product_id = _parse_positive_int(parts[0], "商品 ID")
    suggested_price = _parse_money(parts[1], "建议价")
    min_sale_price = None
    if len(parts) == 3 and parts[2]:
        min_sale_price = _parse_money(parts[2], "最低售价", allow_zero=True)
    if len(parts) == 4 and parts[2]:
        min_sale_price = _parse_money(parts[2], "最低售价", allow_zero=True)
    requires_approval = _parse_optional_bool(parts[3]) if len(parts) == 4 and parts[3] else None
    return product_id, suggested_price, min_sale_price, requires_approval


def _parse_supply_approval_args(raw_args: str) -> Tuple[int, bool]:
    parts = [part.strip() for part in raw_args.split("|")]
    if len(parts) != 2 or not all(parts):
        raise ValueError("格式错误。示例：/set_supply_approval 供货ID | on")
    return _parse_positive_int(parts[0], "供货 ID"), _parse_bool(parts[1])


def _parse_reseller_review_args(raw_args: str, example: str) -> Tuple[int, int]:
    parts = [part.strip() for part in raw_args.split("|")]
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"格式错误。示例：{example}")
    return _parse_positive_int(parts[0], "供货 ID"), _parse_positive_int(parts[1], "代理租户 ID")


def _parse_reseller_reject_args(raw_args: str) -> Tuple[int, int, Optional[str]]:
    parts = [part.strip() for part in raw_args.split("|")]
    if len(parts) not in {2, 3} or not parts[0] or not parts[1]:
        raise ValueError("格式错误。示例：/reject_reseller 供货ID | 代理租户ID | 原因")
    reason = parts[2] if len(parts) == 3 and parts[2] else None
    if reason is not None and len(reason) > 255:
        raise ValueError("拒绝原因不能超过 255 个字符。")
    return _parse_positive_int(parts[0], "供货 ID"), _parse_positive_int(parts[1], "代理租户 ID"), reason


def _parse_reseller_rule_args(raw_args: str) -> Tuple[int, int, Decimal, Optional[Decimal]]:
    parts = [part.strip() for part in raw_args.split("|")]
    if len(parts) not in {3, 4} or not parts[0] or not parts[1] or not parts[2]:
        raise ValueError("格式错误。示例：/set_reseller_rule 供货ID | 代理租户ID | 8.8 | 12")
    supplier_offer_id = _parse_positive_int(parts[0], "供货 ID")
    reseller_tenant_id = _parse_positive_int(parts[1], "代理租户 ID")
    pricing_value = _parse_money(parts[2], "供应商成本")
    min_sale_price = None
    if len(parts) == 4 and parts[3]:
        min_sale_price = _parse_money(parts[3], "最低售价", allow_zero=True)
    return supplier_offer_id, reseller_tenant_id, pricing_value, min_sale_price


def _parse_resell_offer_args(raw_args: str) -> Tuple[int, Decimal, Optional[str]]:
    parts = [part.strip() for part in raw_args.split("|")]
    if len(parts) not in {2, 3} or not parts[0] or not parts[1]:
        raise ValueError("格式错误。示例：/resell_offer 供货ID | 29.9 | 展示名")

    supplier_offer_id = _parse_positive_int(parts[0], "供货 ID")
    sale_price = _parse_money(parts[1], "代理售价")
    display_name = parts[2] if len(parts) == 3 and parts[2] else None
    if display_name is not None and len(display_name) > 255:
        raise ValueError("展示名不能超过 255 个字符。")
    return supplier_offer_id, sale_price, display_name


def _parse_epusdt_config_args(raw_args: str) -> Tuple[str, str, str]:
    parts = [part.strip() for part in raw_args.split("|")]
    if len(parts) != 3 or not all(parts):
        raise ValueError("格式错误。示例：/set_epusdt_config https://pay.example.com | pid | secret_key")
    base_url, pid, secret_key = parts
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("base_url 必须以 http:// 或 https:// 开头。")
    if len(pid) > 128 or len(secret_key) > 256:
        raise ValueError("PID 或 secret_key 长度异常。")
    return base_url.rstrip("/"), pid, secret_key


def _parse_reconcile_limit(raw_args: str) -> int:
    value = raw_args.strip()
    if not value:
        return 20
    try:
        limit = int(value)
    except ValueError:
        raise ValueError("数量必须是数字。示例：/reconcile_payments 20")
    return min(max(limit, 1), 100)


def _parse_list_limit(raw_args: str, example: str) -> int:
    value = raw_args.strip()
    if not value:
        return 20
    try:
        limit = int(value)
    except ValueError:
        raise ValueError(f"数量必须是数字。示例：{example}")
    return min(max(limit, 1), 50)


def _parse_report_type(raw_args: str) -> str:
    report_type = raw_args.strip().lower()
    if report_type not in {"orders", "payments", "inventory", "ledger"}:
        raise ValueError("报表类型不支持。示例：/export_report orders，可选：orders、payments、inventory、ledger")
    return report_type


def _parse_subscription_months(raw_args: str) -> int:
    try:
        months = int(raw_args.strip())
    except ValueError:
        raise ValueError("续费月数必须是数字。示例：/renew_subscription 1")
    if not 1 <= months <= 24:
        raise ValueError("续费月数范围为 1-24。")
    return months


def _parse_withdraw_args(raw_args: str) -> Tuple[Decimal, str, str]:
    parts = [part.strip() for part in raw_args.split("|")]
    if len(parts) != 3 or not all(parts):
        raise ValueError("格式错误。示例：/withdraw 10 | TRC20 | Txxxxxxxxxxxxxxxx")

    try:
        amount = Decimal(parts[0])
    except (InvalidOperation, ValueError):
        raise ValueError("提现金额格式错误。示例：10")
    if amount <= 0:
        raise ValueError("提现金额必须大于 0。")
    if amount.as_tuple().exponent < -8:
        raise ValueError("提现金额最多支持 8 位小数。")

    network = parts[1].upper()
    address = parts[2]
    if not 2 <= len(network) <= 32:
        raise ValueError("提现网络长度应为 2-32 个字符。")
    if not 8 <= len(address) <= 256:
        raise ValueError("提现地址长度应为 8-256 个字符。")
    return amount, network, address


def _parse_positive_int(value: str, label: str) -> int:
    try:
        parsed_value = int(value)
    except ValueError:
        raise ValueError(f"{label}必须是数字。")
    if parsed_value <= 0:
        raise ValueError(f"{label}必须大于 0。")
    return parsed_value


def _parse_telegram_user_id(raw_args: str, example: str) -> int:
    value = raw_args.strip()
    if not value:
        raise ValueError(f"请提供 Telegram 用户 ID。示例：{example}")
    try:
        telegram_user_id = int(value)
    except ValueError:
        raise ValueError("Telegram 用户 ID 必须是数字。")
    if telegram_user_id <= 0:
        raise ValueError("Telegram 用户 ID 必须大于 0。")
    return telegram_user_id


def _parse_money(value: str, label: str, allow_zero: bool = False) -> Decimal:
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ValueError(f"{label}格式错误。示例：9.9")
    if not amount.is_finite():
        raise ValueError(f"{label}格式错误。")
    if allow_zero:
        if amount < 0:
            raise ValueError(f"{label}不能小于 0。")
    elif amount <= 0:
        raise ValueError(f"{label}必须大于 0。")
    if amount.as_tuple().exponent < -8:
        raise ValueError(f"{label}最多支持 8 位小数。")
    return amount


def _parse_optional_bool(value: str) -> Optional[bool]:
    if not value.strip():
        return None
    return _parse_bool(value)


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on", "开启", "是", "需要"}:
        return True
    if normalized in {"0", "false", "no", "n", "off", "关闭", "否", "不需要"}:
        return False
    raise ValueError("布尔值格式错误，可用 on/off。")


def _format_optional_datetime(value: Optional[Any]) -> str:
    if value is None:
        return "-"
    return f"{value:%Y-%m-%d %H:%M:%S %Z}"


def _format_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _format_admin_web_binding_code(
    code: str,
    expires_in_seconds: int,
    store_name: str,
    bot_username: str,
) -> str:
    return (
        "网页管理后台一次性绑定码\n\n"
        f"绑定码：<code>{html.escape(code)}</code>\n"
        f"工作区：{html.escape(store_name)}\n"
        f"Bot：@{html.escape(bot_username)}\n"
        f"有效期：{expires_in_seconds} 秒\n\n"
        "请在 Web 管理后台输入该绑定码。绑定码只能使用一次。"
    )


def _mask_address(value: str) -> str:
    if len(value) <= 12:
        return "***"
    return f"{value[:6]}***{value[-6:]}"


def _mask_value(value: str) -> str:
    if len(value) <= 6:
        return "***"
    return f"{value[:3]}***{value[-3:]}"


def _format_product_list(products: Any) -> str:
    lines = ["商品列表"]
    for product, variant, available_count in products:
        price = variant.price if variant else product.suggested_price
        stock_label = f"可用库存：{available_count}"
        if product.delivery_type == "file_download":
            stock_label = "文件：已绑定" if product.delivery_file_id else "文件：未绑定"
        if product.delivery_type == "telegram_invite":
            stock_label = "群：已绑定" if product.telegram_chat_id else "群：未绑定"
        category = getattr(product, "category", None) or "未分类"
        lines.append(
            f"#{product.id} {html.escape(product.name)}\n"
            f"分类：{html.escape(category)}｜状态：{product.status}｜发货：{product.delivery_type}｜"
            f"价格：{price} {product.currency}｜{stock_label}"
        )
    return "\n\n".join(lines)


def _format_permissions(permissions_map: Dict[str, bool]) -> str:
    lines = ["管理员权限", "owner 始终拥有全部权限；这里仅控制 admin 角色。"]
    for permission, label in PERMISSION_LABELS.items():
        enabled = permissions_map.get(permission, True)
        lines.append(f"{permission}｜{label}：{'开启' if enabled else '关闭'}")
    lines.append("修改：/set_permission 权限 | on/off")
    return "\n\n".join(lines)


def _format_audit_logs(logs: List[AuditLogSummary], title: str) -> str:
    if not logs:
        return f"{title}\n\n暂无审计记录。"
    lines = [title]
    for log in logs:
        actor = _format_audit_actor(log)
        target = _format_audit_target(log)
        metadata = _format_audit_metadata(log.metadata_json)
        lines.append(
            f"#{log.audit_log_id}｜{log.created_at:%Y-%m-%d %H:%M:%S %Z}\n"
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


def _format_audit_metadata(metadata: Dict[str, Any]) -> str:
    if not metadata:
        return "-"
    parts = []
    for key, value in list(metadata.items())[:8]:
        parts.append(f"{html.escape(str(key))}={html.escape(str(value))}")
    return "；".join(parts)


def _format_supply_market(offers: Any) -> str:
    lines = ["供货市场"]
    for offer in offers:
        min_price_text = _format_decimal(offer.effective_min_sale_price) if offer.effective_min_sale_price is not None else "不限"
        approval_text = "需审批" if offer.requires_approval else "免审批"
        rule_status_text = _reseller_rule_status_label(offer.reseller_rule_status)
        stock_label = _supply_stock_label(offer.delivery_type, offer.available_count)
        next_action = f"上架：/resell_offer {offer.offer_id} | 售价 | 展示名"
        if offer.requires_approval and offer.reseller_rule_status != "active":
            next_action = f"申请：/apply_reseller {offer.offer_id}"
        lines.append(
            f"供货 #{offer.offer_id} {html.escape(offer.product_name)}\n"
            f"建议价：{_format_decimal(offer.suggested_price)} {offer.currency}｜"
            f"成本：{_format_decimal(offer.supplier_cost)} {offer.currency}｜最低售价：{min_price_text}\n"
            f"审批：{approval_text}｜申请状态：{rule_status_text}｜发货：{offer.delivery_type}｜{stock_label}\n"
            f"{next_action}"
        )
    return "\n\n".join(lines)


def _format_reseller_applications(applications: Any, title: str, supplier_view: bool) -> str:
    if not applications:
        return f"{title}\n\n暂无记录。"
    lines = [title]
    for application in applications:
        tenant_text = (
            f"代理租户：#{application.reseller_tenant_id} {html.escape(application.reseller_store_name)}"
            if supplier_view
            else f"供应商：#{application.supplier_tenant_id} {html.escape(application.supplier_store_name)}"
        )
        action_text = (
            f"通过：/approve_reseller {application.supplier_offer_id} | {application.reseller_tenant_id}\n"
            f"独立定价：/set_reseller_rule {application.supplier_offer_id} | {application.reseller_tenant_id} | 成本 | 最低售价\n"
            f"拒绝：/reject_reseller {application.supplier_offer_id} | {application.reseller_tenant_id} | 原因"
            if supplier_view and application.status == "pending"
            else (
                f"上架：/resell_offer {application.supplier_offer_id} | 售价 | 展示名"
                if not supplier_view and application.status == "active"
                else ""
            )
        )
        lines.append(
            f"供货 #{application.supplier_offer_id} {html.escape(application.product_name)}\n"
            f"{tenant_text}\n"
            f"状态：{_reseller_rule_status_label(application.status)}｜"
            f"成本：{_format_decimal(application.pricing_value)} {application.currency}｜"
            f"最低售价：{_format_decimal(application.min_sale_price) if application.min_sale_price is not None else '不限'}\n"
            f"{action_text}".rstrip()
        )
    return "\n\n".join(lines)


def _format_reseller_review_result(application: Any, title: str) -> str:
    return (
        f"{title}\n\n"
        f"供货 ID：#{application.supplier_offer_id}\n"
        f"商品：{html.escape(application.product_name)}\n"
        f"代理租户：#{application.reseller_tenant_id} {html.escape(application.reseller_store_name)}\n"
        f"状态：{_reseller_rule_status_label(application.status)}\n"
        f"供应商成本：{_format_decimal(application.pricing_value)} {application.currency}\n"
        f"最低售价：{_format_decimal(application.min_sale_price) if application.min_sale_price is not None else '不限'}"
    )


def _format_reseller_products(products: Any) -> str:
    lines = ["我的代理商品"]
    for product in products:
        stock_label = _supply_stock_label(product.delivery_type, product.available_count)
        lines.append(
            f"代理 #{product.reseller_product_id} {html.escape(product.display_name)}\n"
            f"供货：#{product.supplier_offer_id}｜状态：{product.status}｜"
            f"售价：{_format_decimal(product.sale_price)} {product.currency}｜发货：{product.delivery_type}｜{stock_label}"
        )
    return "\n\n".join(lines)


def _reseller_rule_status_label(status: Optional[str]) -> str:
    labels = {
        None: "无",
        "pending": "待审核",
        "active": "已通过",
        "rejected": "已拒绝",
        "disabled": "已停用",
    }
    return labels.get(status, status or "无")


def _format_withdrawals(withdrawals: List[WithdrawalSummary], include_tenant: bool) -> str:
    status_labels = {
        "pending": "待审核",
        "completed": "已完成",
        "rejected": "已拒绝",
    }
    lines = ["提现记录"]
    for withdrawal in withdrawals:
        tenant_text = f"租户：{withdrawal.tenant_id}｜" if include_tenant else ""
        lines.append(
            f"#{withdrawal.withdrawal_id}｜{tenant_text}状态：{status_labels.get(withdrawal.status, withdrawal.status)}\n"
            f"金额：{_format_decimal(withdrawal.amount)} {withdrawal.currency}｜网络：{html.escape(withdrawal.network)}\n"
            f"地址：{html.escape(_mask_address(withdrawal.address))}\n"
            f"申请时间：{withdrawal.requested_at:%Y-%m-%d %H:%M:%S %Z}"
        )
    return "\n\n".join(lines)


def _format_export_job_created(job: ExportJobSummary) -> str:
    return (
        "报表导出任务已创建\n\n"
        f"任务 ID：#{job.export_job_id}\n"
        f"类型：{html.escape(job.report_type)}\n"
        f"状态：{_export_status_label(job.status)}\n\n"
        "后台 worker 会异步生成 CSV；完成后使用 /export_jobs 查看下载链接。"
    )


def _format_export_jobs(jobs: List[ExportJobSummary], include_tenant: bool) -> str:
    if not jobs:
        return "报表导出任务\n\n暂无记录。"
    lines = ["报表导出任务"]
    for job in jobs:
        tenant_text = f"租户：{job.tenant_id or '-'}｜" if include_tenant else ""
        download_text = f"\n下载：{html.escape(job.download_url)}" if job.download_url else ""
        error_text = f"\n错误：{html.escape(job.error_message)}" if job.error_message else ""
        lines.append(
            f"#{job.export_job_id}｜{tenant_text}{html.escape(job.report_type)}｜{_export_status_label(job.status)}\n"
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


def _format_api_keys(keys: List[TenantApiKeySummary]) -> str:
    if not keys:
        return "API Key\n\n暂无 API Key。\n\n创建：/create_api_key 名称 | scope1,scope2 | IP或CIDR"
    lines = ["API Key"]
    for api_key in keys:
        lines.append(
            f"#{api_key.api_key_id} {html.escape(api_key.name)}\n"
            f"前缀：{html.escape(api_key.key_prefix)}｜状态：{api_key.status}\n"
            f"权限：{html.escape(_format_api_key_scopes(api_key.scopes))}\n"
            f"IP白名单：{html.escape(_format_api_key_ip_allowlist(api_key.ip_allowlist))}\n"
            f"创建：{api_key.created_at:%Y-%m-%d %H:%M:%S %Z}｜"
            f"最后使用：{_format_optional_datetime(api_key.last_used_at)}\n"
            f"撤销：/revoke_api_key {api_key.api_key_id}"
        )
    lines.append("创建新 Key：/create_api_key 名称 | scope1,scope2 | IP或CIDR")
    return "\n\n".join(lines)


def _parse_create_api_key_args(args: str) -> tuple[str, Optional[List[str]], Optional[List[str]]]:
    parts = [part.strip() for part in args.split("|")]
    name = parts[0] if parts and parts[0] else "default"
    if len(parts) == 1:
        return name, None, None
    scopes = [scope.strip() for scope in parts[1].split(",") if scope.strip()]
    ip_allowlist = None
    if len(parts) >= 3:
        ip_allowlist = ApiKeyService.normalize_ip_allowlist(
            [rule.strip() for rule in parts[2].split(",") if rule.strip()]
        )
    return name, ApiKeyService.normalize_scopes(scopes), ip_allowlist


def _format_api_key_scopes(scopes: List[str]) -> str:
    return ", ".join(scopes)


def _format_api_key_ip_allowlist(ip_allowlist: List[str]) -> str:
    return ", ".join(ip_allowlist) if ip_allowlist else "不限制"


def _supply_stock_label(delivery_type: str, available_count: int) -> str:
    if delivery_type in {"card_pool", "card_fixed"}:
        return f"可用库存：{available_count}"
    return "按供应商配置发货"


def _public_reseller_stock_label(delivery_type: str, available_count: int) -> str:
    if delivery_type in {"card_pool", "card_fixed"} and available_count <= 0:
        return "缺货"
    return "可购买"
