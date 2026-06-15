from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models.orders import Order
from app.db.models.risk import AfterSaleCase, Dispute
from app.db.models.supply import ResellerProduct, SupplierOffer
from app.db.models.tenants import AuditLog, PlatformUser, Tenant, TenantBot
from app.services.ledger import AMOUNT_QUANT, LedgerService

RESUMABLE_TENANT_STATUSES = {"trial", "active", "grace"}
AFTER_SALE_CASE_TYPES = {"refund", "complaint", "reseller_after_sale"}
DISPUTE_STATUSES = {"open", "reviewing", "resolved", "rejected", "closed"}
AFTER_SALE_STATUSES = {"open", "reviewing", "resolved", "rejected", "closed"}
RESOLVED_DISPUTE_STATUSES = {"resolved", "rejected", "closed"}
RESOLVED_AFTER_SALE_STATUSES = {"resolved", "rejected", "closed"}
ORDER_RISK_COUNTED_STATUSES = {"pending", "paid", "delivered", "completed", "partially_refunded"}
PLATFORM_BAN_SOURCE_VALUES = {"all", "manual", "auto"}
PLATFORM_BAN_AUDIT_ACTIONS = ("platform_risk.user_banned", "platform_risk.user_auto_banned")
PLATFORM_BAN_REASON_SENSITIVE_MARKERS = (
    "token",
    "secret",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "private_key",
    "payload",
    "card_secret",
    "卡密",
)


class OrderCreationRiskBlocked(ValueError):
    """订单创建被平台风控拦截。"""


@dataclass(frozen=True)
class RiskActionResult:
    target_type: str
    target_id: int
    tenant_id: Optional[int]
    previous_status: str
    new_status: str
    reason: Optional[str]
    affected_count: int = 0
    webhook_secrets: Tuple[str, ...] = ()


@dataclass(frozen=True)
class DisputeSummary:
    dispute_id: int
    tenant_id: int
    order_id: int
    out_trade_no: str
    buyer_telegram_user_id: int
    source_type: str
    order_status: str
    amount: Decimal
    currency: str
    status: str
    reason: Optional[str]
    resolution: Optional[str]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AfterSaleSummary:
    case_id: int
    tenant_id: int
    order_id: int
    out_trade_no: str
    buyer_telegram_user_id: int
    source_type: str
    order_status: str
    amount: Decimal
    currency: str
    case_type: str
    status: str
    requested_amount: Optional[Decimal]
    refunded_amount: Decimal
    refund_id: Optional[int]
    reason: Optional[str]
    resolution: Optional[str]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class PlatformRiskBannedUserSummary:
    telegram_user_id: int
    username: Optional[str]
    is_banned: bool
    ban_source: str
    latest_action: Optional[str]
    latest_action_at: Optional[datetime]
    reason: Optional[str]
    trigger_rule: Optional[str]
    blocked_count: Optional[int]
    threshold: Optional[int]
    window_seconds: Optional[int]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class PlatformRiskBanStatusSummary:
    telegram_user_id: int
    username: Optional[str]
    is_banned: bool
    ban_source: Optional[str]
    latest_action: Optional[str]
    latest_action_at: Optional[datetime]
    reason: Optional[str]
    trigger_rule: Optional[str]
    blocked_count: Optional[int]
    threshold: Optional[int]
    window_seconds: Optional[int]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


class RiskControlService:
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    async def ensure_order_creation_allowed(
        self,
        session: AsyncSession,
        buyer_telegram_user_id: int,
        amount: Decimal,
        currency: str,
        tenant_id: Optional[int] = None,
        source_type: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> None:
        normalized_buyer_id = self._normalize_telegram_user_id(buyer_telegram_user_id)
        normalized_amount = self._normalize_required_amount(amount, "订单金额")
        normalized_currency = self._normalize_currency(currency)
        current_time = now or datetime.now(timezone.utc)

        recent_count = await self._buyer_order_count_since(
            session=session,
            buyer_telegram_user_id=normalized_buyer_id,
            since=current_time - timedelta(seconds=self.settings.order_risk_recent_window_seconds),
        )
        if recent_count >= self.settings.order_risk_max_buyer_orders_per_window:
            self._add_order_risk_audit(
                session=session,
                tenant_id=tenant_id,
                buyer_telegram_user_id=normalized_buyer_id,
                rule="recent_order_count",
                source_type=source_type,
                amount=normalized_amount,
                currency=normalized_currency,
                recent_count=recent_count,
                daily_amount=None,
            )
            await self._maybe_auto_ban_after_order_risk_block(
                session=session,
                buyer_telegram_user_id=normalized_buyer_id,
                rule="recent_order_count",
                tenant_id=tenant_id,
                source_type=source_type,
                current_time=current_time,
            )
            raise OrderCreationRiskBlocked("下单过于频繁，请稍后再试")

        daily_amount = await self._buyer_order_amount_since(
            session=session,
            buyer_telegram_user_id=normalized_buyer_id,
            currency=normalized_currency,
            since=current_time - timedelta(seconds=self.settings.order_risk_daily_window_seconds),
        )
        if daily_amount + normalized_amount > self.settings.order_risk_max_buyer_amount_per_day:
            self._add_order_risk_audit(
                session=session,
                tenant_id=tenant_id,
                buyer_telegram_user_id=normalized_buyer_id,
                rule="daily_amount",
                source_type=source_type,
                amount=normalized_amount,
                currency=normalized_currency,
                recent_count=recent_count,
                daily_amount=daily_amount,
            )
            await self._maybe_auto_ban_after_order_risk_block(
                session=session,
                buyer_telegram_user_id=normalized_buyer_id,
                rule="daily_amount",
                tenant_id=tenant_id,
                source_type=source_type,
                current_time=current_time,
            )
            raise OrderCreationRiskBlocked("下单金额触发平台风控，请稍后再试")

    async def disable_supplier_offer(
        self,
        session: AsyncSession,
        supplier_offer_id: int,
        actor_user_id: int,
        reason: Optional[str] = None,
    ) -> RiskActionResult:
        normalized_reason = self._normalize_reason(reason)
        offer = await self._get_supplier_offer_for_update(session, supplier_offer_id)
        if offer is None:
            raise ValueError("供货商品不存在")
        if offer.status == "deleted":
            raise ValueError("供货商品已删除")

        previous_status = offer.status
        offer.status = "disabled"
        affected_count = await self._count_active_reseller_products(session, offer.id)
        session.add(
            AuditLog(
                tenant_id=offer.supplier_tenant_id,
                actor_user_id=actor_user_id,
                action="platform_risk.supplier_offer_disabled",
                target_type="supplier_offer",
                target_id=str(offer.id),
                metadata_json={
                    "previous_status": previous_status,
                    "new_status": offer.status,
                    "reason": normalized_reason,
                    "affected_reseller_products": affected_count,
                },
            )
        )
        await session.flush()
        return RiskActionResult(
            target_type="supplier_offer",
            target_id=offer.id,
            tenant_id=offer.supplier_tenant_id,
            previous_status=previous_status,
            new_status=offer.status,
            reason=normalized_reason,
            affected_count=affected_count,
        )

    async def disable_reseller_product(
        self,
        session: AsyncSession,
        reseller_product_id: int,
        actor_user_id: int,
        reason: Optional[str] = None,
    ) -> RiskActionResult:
        normalized_reason = self._normalize_reason(reason)
        reseller_product = await self._get_reseller_product_for_update(session, reseller_product_id)
        if reseller_product is None:
            raise ValueError("代理商品不存在")

        previous_status = reseller_product.status
        reseller_product.status = "disabled"
        session.add(
            AuditLog(
                tenant_id=reseller_product.reseller_tenant_id,
                actor_user_id=actor_user_id,
                action="platform_risk.reseller_product_disabled",
                target_type="reseller_product",
                target_id=str(reseller_product.id),
                metadata_json={
                    "supplier_tenant_id": reseller_product.supplier_tenant_id,
                    "supplier_offer_id": reseller_product.supplier_offer_id,
                    "previous_status": previous_status,
                    "new_status": reseller_product.status,
                    "reason": normalized_reason,
                },
            )
        )
        await session.flush()
        return RiskActionResult(
            target_type="reseller_product",
            target_id=reseller_product.id,
            tenant_id=reseller_product.reseller_tenant_id,
            previous_status=previous_status,
            new_status=reseller_product.status,
            reason=normalized_reason,
        )

    async def suspend_tenant(
        self,
        session: AsyncSession,
        tenant_id: int,
        actor_user_id: Optional[int],
        reason: Optional[str] = None,
    ) -> RiskActionResult:
        normalized_reason = self._sanitize_platform_ban_reason(self._normalize_reason(reason))
        tenant = await self._get_tenant_for_update(session, tenant_id)
        if tenant is None:
            raise ValueError("租户不存在")
        if tenant.status == "suspended":
            raise ValueError("租户已冻结")

        previous_status = tenant.status
        tenant.status = "suspended"
        tenant.suspended_at = tenant.suspended_at or datetime.now(timezone.utc)
        webhook_secrets = await self._tenant_webhook_secrets(session, tenant.id)
        session.add(
            AuditLog(
                tenant_id=tenant.id,
                actor_user_id=actor_user_id,
                action="platform_risk.tenant_suspended",
                target_type="tenant",
                target_id=str(tenant.id),
                metadata_json={
                    "previous_status": previous_status,
                    "new_status": tenant.status,
                    "reason": normalized_reason,
                },
            )
        )
        await session.flush()
        return RiskActionResult(
            target_type="tenant",
            target_id=tenant.id,
            tenant_id=tenant.id,
            previous_status=previous_status,
            new_status=tenant.status,
            reason=normalized_reason,
            webhook_secrets=webhook_secrets,
        )

    async def resume_tenant(
        self,
        session: AsyncSession,
        tenant_id: int,
        actor_user_id: Optional[int],
        reason: Optional[str] = None,
    ) -> RiskActionResult:
        normalized_reason = self._sanitize_platform_ban_reason(self._normalize_reason(reason))
        tenant = await self._get_tenant_for_update(session, tenant_id)
        if tenant is None:
            raise ValueError("租户不存在")
        if tenant.status != "suspended":
            raise ValueError("租户当前未冻结")

        previous_status = tenant.status
        restored_status = await self._last_status_before_suspension(session, tenant.id)
        tenant.status = restored_status
        tenant.suspended_at = None
        webhook_secrets = await self._tenant_webhook_secrets(session, tenant.id)
        session.add(
            AuditLog(
                tenant_id=tenant.id,
                actor_user_id=actor_user_id,
                action="platform_risk.tenant_resumed",
                target_type="tenant",
                target_id=str(tenant.id),
                metadata_json={
                    "previous_status": previous_status,
                    "new_status": tenant.status,
                    "reason": normalized_reason,
                },
            )
        )
        await session.flush()
        return RiskActionResult(
            target_type="tenant",
            target_id=tenant.id,
            tenant_id=tenant.id,
            previous_status=previous_status,
            new_status=tenant.status,
            reason=normalized_reason,
            webhook_secrets=webhook_secrets,
        )

    async def ban_platform_user(
        self,
        session: AsyncSession,
        telegram_user_id: int,
        actor_user_id: Optional[int],
        reason: Optional[str] = None,
    ) -> RiskActionResult:
        normalized_telegram_user_id = self._normalize_telegram_user_id(telegram_user_id)
        normalized_reason = self._sanitize_platform_ban_reason(self._normalize_reason(reason))
        user = await self._get_or_create_platform_user_for_update(session, normalized_telegram_user_id)
        if user.is_banned:
            raise ValueError("用户已封禁")

        previous_status = "banned" if user.is_banned else "active"
        user.is_banned = True
        await session.flush()
        self._add_platform_user_audit(
            session=session,
            user=user,
            actor_user_id=actor_user_id,
            action="platform_risk.user_banned",
            previous_status=previous_status,
            new_status="banned",
            reason=normalized_reason,
        )
        await session.flush()
        return RiskActionResult(
            target_type="platform_user",
            target_id=user.id,
            tenant_id=None,
            previous_status=previous_status,
            new_status="banned",
            reason=normalized_reason,
        )

    async def unban_platform_user(
        self,
        session: AsyncSession,
        telegram_user_id: int,
        actor_user_id: Optional[int],
        reason: Optional[str] = None,
    ) -> RiskActionResult:
        normalized_telegram_user_id = self._normalize_telegram_user_id(telegram_user_id)
        normalized_reason = self._sanitize_platform_ban_reason(self._normalize_reason(reason))
        user = await self._get_platform_user_for_update(session, normalized_telegram_user_id)
        if user is None:
            raise ValueError("用户不存在")
        if not user.is_banned:
            raise ValueError("用户未封禁")

        user.is_banned = False
        self._add_platform_user_audit(
            session=session,
            user=user,
            actor_user_id=actor_user_id,
            action="platform_risk.user_unbanned",
            previous_status="banned",
            new_status="active",
            reason=normalized_reason,
        )
        await session.flush()
        return RiskActionResult(
            target_type="platform_user",
            target_id=user.id,
            tenant_id=None,
            previous_status="banned",
            new_status="active",
            reason=normalized_reason,
        )

    async def list_banned_platform_users(
        self,
        session: AsyncSession,
        source: str = "all",
        telegram_user_id: Optional[int] = None,
        limit: int = 20,
    ) -> List[PlatformRiskBannedUserSummary]:
        normalized_source = self._normalize_platform_ban_source(source)
        normalized_limit = self._normalize_limit(limit)
        normalized_telegram_user_id = (
            None if telegram_user_id is None else self._normalize_telegram_user_id(telegram_user_id)
        )
        query_limit = normalized_limit if normalized_source == "all" or normalized_telegram_user_id is not None else 100
        users = await self._list_banned_platform_user_rows(
            session,
            telegram_user_id=normalized_telegram_user_id,
            limit=query_limit,
        )
        summaries: list[PlatformRiskBannedUserSummary] = []
        for user in users:
            audit = await self._latest_platform_user_ban_audit(session, user.id)
            summary = self._platform_user_ban_summary(user, audit)
            if normalized_source != "all" and summary.ban_source != normalized_source:
                continue
            summaries.append(summary)
            if len(summaries) >= normalized_limit:
                break
        return summaries

    async def get_platform_user_ban_status(
        self,
        session: AsyncSession,
        telegram_user_id: int,
    ) -> Optional[PlatformRiskBanStatusSummary]:
        normalized_telegram_user_id = self._normalize_telegram_user_id(telegram_user_id)
        user = await self._get_platform_user_by_telegram_user_id(session, normalized_telegram_user_id)
        if user is None:
            return None
        latest_status_audit = await self._latest_platform_user_status_audit(session, user.id)
        latest_ban_audit = await self._latest_platform_user_ban_audit(session, user.id) if user.is_banned else None
        return self._platform_user_ban_status_summary(user, latest_status_audit, latest_ban_audit)

    async def open_dispute(
        self,
        session: AsyncSession,
        out_trade_no: str,
        actor_user_id: int,
        reason: Optional[str] = None,
    ) -> DisputeSummary:
        normalized_reason = self._normalize_reason(reason)
        order = await self._get_order_for_update(session, out_trade_no)
        if order is None:
            raise ValueError("订单不存在")
        if order.source_type not in {"self", "reseller"}:
            raise ValueError("当前订单类型不支持争议处理")

        dispute = await self._get_latest_order_dispute(session, order.id, for_update=True)
        if dispute is None:
            dispute = Dispute(
                tenant_id=order.tenant_id,
                order_id=order.id,
                buyer_telegram_user_id=order.buyer_telegram_user_id,
                status="open",
                reason=normalized_reason,
            )
            session.add(dispute)
            action = "platform_risk.dispute_opened"
        elif dispute.status in RESOLVED_DISPUTE_STATUSES:
            dispute.status = "open"
            dispute.reason = normalized_reason or dispute.reason
            dispute.resolution = None
            action = "platform_risk.dispute_reopened"
        else:
            if normalized_reason:
                dispute.reason = normalized_reason
            action = "platform_risk.dispute_updated"

        await session.flush()
        self._add_dispute_audit(session, dispute, actor_user_id, action, order, normalized_reason)
        await session.flush()
        return self._dispute_summary(dispute, order)

    async def review_dispute(
        self,
        session: AsyncSession,
        dispute_id: int,
        actor_user_id: int,
        note: Optional[str] = None,
    ) -> DisputeSummary:
        normalized_note = self._normalize_reason(note)
        dispute, order = await self._get_dispute_with_order_for_update(session, dispute_id)
        if dispute is None or order is None:
            raise ValueError("争议不存在")
        if dispute.status in RESOLVED_DISPUTE_STATUSES:
            raise ValueError("争议已结束，不能进入处理中")

        dispute.status = "reviewing"
        if normalized_note:
            dispute.resolution = normalized_note
        self._add_dispute_audit(session, dispute, actor_user_id, "platform_risk.dispute_reviewing", order, normalized_note)
        await session.flush()
        return self._dispute_summary(dispute, order)

    async def close_dispute(
        self,
        session: AsyncSession,
        dispute_id: int,
        actor_user_id: int,
        status: str,
        resolution: Optional[str] = None,
    ) -> DisputeSummary:
        if status not in RESOLVED_DISPUTE_STATUSES:
            raise ValueError("争议结论必须是 resolved、rejected 或 closed")
        normalized_resolution = self._normalize_required_text(resolution, "处理结论")
        dispute, order = await self._get_dispute_with_order_for_update(session, dispute_id)
        if dispute is None or order is None:
            raise ValueError("争议不存在")
        if dispute.status in RESOLVED_DISPUTE_STATUSES:
            raise ValueError("争议已结束")

        dispute.status = status
        dispute.resolution = normalized_resolution
        self._add_dispute_audit(
            session,
            dispute,
            actor_user_id,
            "platform_risk.dispute_closed",
            order,
            normalized_resolution,
        )
        await session.flush()
        return self._dispute_summary(dispute, order)

    async def list_disputes(
        self,
        session: AsyncSession,
        tenant_id: Optional[int] = None,
        status: Optional[str] = "open",
        limit: int = 20,
    ) -> List[DisputeSummary]:
        if status is not None and status not in DISPUTE_STATUSES:
            raise ValueError("争议状态必须是 open、reviewing、resolved、rejected、closed 或 all")
        query = (
            select(Dispute, Order)
            .join(Order, Order.id == Dispute.order_id)
            .order_by(Dispute.created_at.desc(), Dispute.id.desc())
            .limit(self._normalize_limit(limit))
        )
        if tenant_id is not None:
            query = query.where(Dispute.tenant_id == tenant_id)
        if status is not None:
            query = query.where(Dispute.status == status)
        result = await session.execute(query)
        return [self._dispute_summary(dispute, order) for dispute, order in result.all()]

    async def open_after_sale(
        self,
        session: AsyncSession,
        out_trade_no: str,
        actor_user_id: int,
        case_type: str,
        requested_amount: Optional[Decimal],
        reason: Optional[str] = None,
    ) -> AfterSaleSummary:
        normalized_case_type = self._normalize_after_sale_case_type(case_type)
        normalized_reason = self._normalize_reason(reason)
        order = await self._get_order_for_update(session, out_trade_no)
        if order is None:
            raise ValueError("订单不存在")
        if order.source_type not in {"self", "reseller"}:
            raise ValueError("当前订单类型不支持售后处理")
        normalized_amount = self._normalize_optional_amount(requested_amount, "售后申请金额")
        if normalized_amount is not None and normalized_amount > order.amount:
            raise ValueError("售后申请金额不能超过订单金额")

        after_sale = AfterSaleCase(
            tenant_id=order.tenant_id,
            order_id=order.id,
            buyer_telegram_user_id=order.buyer_telegram_user_id,
            case_type=normalized_case_type,
            status="open",
            requested_amount=normalized_amount,
            refunded_amount=Decimal("0"),
            reason=normalized_reason,
        )
        session.add(after_sale)
        await session.flush()
        self._add_after_sale_audit(
            session,
            after_sale,
            actor_user_id,
            "platform_risk.after_sale_opened",
            order,
            normalized_reason,
        )
        await session.flush()
        return self._after_sale_summary(after_sale, order)

    async def review_after_sale(
        self,
        session: AsyncSession,
        case_id: int,
        actor_user_id: int,
        note: Optional[str] = None,
    ) -> AfterSaleSummary:
        normalized_note = self._normalize_reason(note)
        after_sale, order = await self._get_after_sale_with_order_for_update(session, case_id)
        if after_sale is None or order is None:
            raise ValueError("售后工单不存在")
        if after_sale.status in RESOLVED_AFTER_SALE_STATUSES:
            raise ValueError("售后工单已结束，不能进入处理中")

        after_sale.status = "reviewing"
        if normalized_note:
            after_sale.resolution = normalized_note
        self._add_after_sale_audit(
            session,
            after_sale,
            actor_user_id,
            "platform_risk.after_sale_reviewing",
            order,
            normalized_note,
        )
        await session.flush()
        return self._after_sale_summary(after_sale, order)

    async def refund_after_sale(
        self,
        session: AsyncSession,
        case_id: int,
        actor_user_id: int,
        amount: Decimal,
        note: Optional[str] = None,
    ) -> AfterSaleSummary:
        normalized_note = self._normalize_reason(note)
        refund_amount = self._normalize_required_amount(amount, "退款金额")
        after_sale, order = await self._get_after_sale_with_order_for_update(session, case_id)
        if after_sale is None or order is None:
            raise ValueError("售后工单不存在")
        if after_sale.status in RESOLVED_AFTER_SALE_STATUSES:
            raise ValueError("售后工单已结束，不能退款")
        if after_sale.requested_amount is not None and refund_amount > after_sale.requested_amount:
            raise ValueError("退款金额不能超过售后申请金额")

        if after_sale.refund_id is not None:
            return self._after_sale_summary(after_sale, order)

        refund = await LedgerService().refund_platform_order(
            session=session,
            out_trade_no=order.out_trade_no,
            reason=normalized_note or after_sale.reason,
            amount=refund_amount,
            idempotency_key=f"after_sale:{after_sale.id}:refund",
        )
        after_sale.refund_id = refund.refund_id
        after_sale.refunded_amount = refund.amount
        after_sale.status = "resolved"
        after_sale.resolution = normalized_note or f"已退款 {refund.amount} {refund.currency}"
        self._add_after_sale_audit(
            session,
            after_sale,
            actor_user_id,
            "platform_risk.after_sale_refunded",
            order,
            normalized_note,
            refund_id=refund.refund_id,
            refund_amount=refund.amount,
        )
        await session.flush()
        return self._after_sale_summary(after_sale, order)

    async def close_after_sale(
        self,
        session: AsyncSession,
        case_id: int,
        actor_user_id: int,
        status: str,
        resolution: Optional[str] = None,
    ) -> AfterSaleSummary:
        if status not in RESOLVED_AFTER_SALE_STATUSES:
            raise ValueError("售后结论必须是 resolved、rejected 或 closed")
        normalized_resolution = self._normalize_required_text(resolution, "处理结论")
        after_sale, order = await self._get_after_sale_with_order_for_update(session, case_id)
        if after_sale is None or order is None:
            raise ValueError("售后工单不存在")
        if after_sale.status in RESOLVED_AFTER_SALE_STATUSES:
            raise ValueError("售后工单已结束")

        after_sale.status = status
        after_sale.resolution = normalized_resolution
        self._add_after_sale_audit(
            session,
            after_sale,
            actor_user_id,
            "platform_risk.after_sale_closed",
            order,
            normalized_resolution,
        )
        await session.flush()
        return self._after_sale_summary(after_sale, order)

    async def list_after_sales(
        self,
        session: AsyncSession,
        tenant_id: Optional[int] = None,
        status: Optional[str] = "open",
        limit: int = 20,
    ) -> List[AfterSaleSummary]:
        if status is not None and status not in AFTER_SALE_STATUSES:
            raise ValueError("售后状态必须是 open、reviewing、resolved、rejected、closed 或 all")
        query = (
            select(AfterSaleCase, Order)
            .join(Order, Order.id == AfterSaleCase.order_id)
            .order_by(AfterSaleCase.created_at.desc(), AfterSaleCase.id.desc())
            .limit(self._normalize_limit(limit))
        )
        if tenant_id is not None:
            query = query.where(AfterSaleCase.tenant_id == tenant_id)
        if status is not None:
            query = query.where(AfterSaleCase.status == status)
        result = await session.execute(query)
        return [self._after_sale_summary(after_sale, order) for after_sale, order in result.all()]

    async def _get_supplier_offer_for_update(
        self,
        session: AsyncSession,
        supplier_offer_id: int,
    ) -> Optional[SupplierOffer]:
        result = await session.execute(
            select(SupplierOffer)
            .where(SupplierOffer.id == supplier_offer_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def _get_reseller_product_for_update(
        self,
        session: AsyncSession,
        reseller_product_id: int,
    ) -> Optional[ResellerProduct]:
        result = await session.execute(
            select(ResellerProduct)
            .where(ResellerProduct.id == reseller_product_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def _get_tenant_for_update(self, session: AsyncSession, tenant_id: int) -> Optional[Tenant]:
        result = await session.execute(
            select(Tenant)
            .where(Tenant.id == tenant_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def _get_platform_user_for_update(
        self,
        session: AsyncSession,
        telegram_user_id: int,
    ) -> Optional[PlatformUser]:
        result = await session.execute(
            select(PlatformUser)
            .where(PlatformUser.telegram_user_id == telegram_user_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def _get_or_create_platform_user_for_update(
        self,
        session: AsyncSession,
        telegram_user_id: int,
    ) -> PlatformUser:
        user = await self._get_platform_user_for_update(session, telegram_user_id)
        if user is not None:
            return user
        user = PlatformUser(
            telegram_user_id=telegram_user_id,
            language="zh",
            is_platform_admin=False,
            is_banned=False,
        )
        session.add(user)
        await session.flush()
        return user

    async def _get_order_for_update(self, session: AsyncSession, out_trade_no: str) -> Optional[Order]:
        result = await session.execute(
            select(Order)
            .where(Order.out_trade_no == out_trade_no)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def _get_latest_order_dispute(
        self,
        session: AsyncSession,
        order_id: int,
        for_update: bool = False,
    ) -> Optional[Dispute]:
        query = (
            select(Dispute)
            .where(Dispute.order_id == order_id)
            .order_by(Dispute.created_at.desc(), Dispute.id.desc())
            .limit(1)
        )
        if for_update:
            query = query.with_for_update()
        result = await session.execute(query)
        return result.scalar_one_or_none()

    async def _get_dispute_with_order_for_update(
        self,
        session: AsyncSession,
        dispute_id: int,
    ) -> tuple[Optional[Dispute], Optional[Order]]:
        result = await session.execute(
            select(Dispute, Order)
            .join(Order, Order.id == Dispute.order_id)
            .where(Dispute.id == dispute_id)
            .with_for_update()
        )
        row = result.first()
        if row is None:
            return None, None
        return row[0], row[1]

    async def _get_after_sale_with_order_for_update(
        self,
        session: AsyncSession,
        case_id: int,
    ) -> tuple[Optional[AfterSaleCase], Optional[Order]]:
        result = await session.execute(
            select(AfterSaleCase, Order)
            .join(Order, Order.id == AfterSaleCase.order_id)
            .where(AfterSaleCase.id == case_id)
            .with_for_update()
        )
        row = result.first()
        if row is None:
            return None, None
        return row[0], row[1]

    async def _count_active_reseller_products(self, session: AsyncSession, supplier_offer_id: int) -> int:
        result = await session.execute(
            select(func.count(ResellerProduct.id))
            .where(ResellerProduct.supplier_offer_id == supplier_offer_id)
            .where(ResellerProduct.status == "on")
        )
        return int(result.scalar_one() or 0)

    async def _buyer_order_count_since(
        self,
        session: AsyncSession,
        buyer_telegram_user_id: int,
        since: datetime,
    ) -> int:
        result = await session.execute(
            select(func.count(Order.id))
            .where(Order.buyer_telegram_user_id == buyer_telegram_user_id)
            .where(Order.status.in_(ORDER_RISK_COUNTED_STATUSES))
            .where(Order.created_at >= since)
        )
        return int(result.scalar_one() or 0)

    async def _buyer_order_amount_since(
        self,
        session: AsyncSession,
        buyer_telegram_user_id: int,
        currency: str,
        since: datetime,
    ) -> Decimal:
        result = await session.execute(
            select(func.coalesce(func.sum(Order.amount), 0))
            .where(Order.buyer_telegram_user_id == buyer_telegram_user_id)
            .where(Order.currency == currency)
            .where(Order.status.in_(ORDER_RISK_COUNTED_STATUSES))
            .where(Order.created_at >= since)
        )
        value = result.scalar_one() or Decimal("0")
        return value if isinstance(value, Decimal) else Decimal(str(value))

    async def _list_banned_platform_user_rows(
        self,
        session: AsyncSession,
        *,
        telegram_user_id: Optional[int],
        limit: int,
    ) -> list[PlatformUser]:
        query = select(PlatformUser).where(PlatformUser.is_banned.is_(True))
        if telegram_user_id is not None:
            query = query.where(PlatformUser.telegram_user_id == telegram_user_id)
        result = await session.execute(query.order_by(PlatformUser.updated_at.desc(), PlatformUser.id.desc()).limit(limit))
        return list(result.scalars().all())

    async def _get_platform_user_by_telegram_user_id(
        self,
        session: AsyncSession,
        telegram_user_id: int,
    ) -> Optional[PlatformUser]:
        result = await session.execute(
            select(PlatformUser).where(PlatformUser.telegram_user_id == telegram_user_id).limit(1)
        )
        return result.scalar_one_or_none()

    async def _latest_platform_user_ban_audit(self, session: AsyncSession, platform_user_id: int) -> Optional[AuditLog]:
        result = await session.execute(
            select(AuditLog)
            .where(AuditLog.tenant_id.is_(None))
            .where(AuditLog.target_type == "platform_user")
            .where(AuditLog.target_id == str(platform_user_id))
            .where(AuditLog.action.in_(PLATFORM_BAN_AUDIT_ACTIONS))
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _latest_platform_user_status_audit(self, session: AsyncSession, platform_user_id: int) -> Optional[AuditLog]:
        result = await session.execute(
            select(AuditLog)
            .where(AuditLog.tenant_id.is_(None))
            .where(AuditLog.target_type == "platform_user")
            .where(AuditLog.target_id == str(platform_user_id))
            .where(
                AuditLog.action.in_(
                    (
                        "platform_risk.user_banned",
                        "platform_risk.user_auto_banned",
                        "platform_risk.user_unbanned",
                    )
                )
            )
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _maybe_auto_ban_after_order_risk_block(
        self,
        *,
        session: AsyncSession,
        buyer_telegram_user_id: int,
        rule: str,
        tenant_id: Optional[int],
        source_type: Optional[str],
        current_time: datetime,
    ) -> None:
        if not self.settings.order_risk_auto_ban_enabled:
            return
        await session.flush()
        blocked_count = await self._order_risk_block_count_since(
            session=session,
            buyer_telegram_user_id=buyer_telegram_user_id,
            since=current_time - timedelta(seconds=self.settings.order_risk_auto_ban_window_seconds),
        )
        if blocked_count < self.settings.order_risk_auto_ban_blocked_count_threshold:
            return

        user = await self._get_or_create_platform_user_for_update(session, buyer_telegram_user_id)
        if user.is_banned:
            return
        if (
            bool(getattr(user, "is_platform_admin", False))
            or getattr(user, "telegram_user_id", buyer_telegram_user_id) in self.settings.platform_admin_ids
        ):
            return

        user.is_banned = True
        await session.flush()
        session.add(
            AuditLog(
                tenant_id=None,
                actor_user_id=None,
                action="platform_risk.user_auto_banned",
                target_type="platform_user",
                target_id=str(user.id),
                metadata_json={
                    "telegram_user_id": buyer_telegram_user_id,
                    "previous_status": "active",
                    "new_status": "banned",
                    "reason": "order_creation_risk_repeated_blocks",
                    "trigger_action": "platform_risk.order_creation_blocked",
                    "trigger_rule": rule,
                    "trigger_tenant_id": tenant_id,
                    "trigger_source_type": source_type,
                    "blocked_count": blocked_count,
                    "threshold": self.settings.order_risk_auto_ban_blocked_count_threshold,
                    "window_seconds": self.settings.order_risk_auto_ban_window_seconds,
                    "auto": True,
                },
            )
        )
        await session.flush()

    async def _order_risk_block_count_since(
        self,
        *,
        session: AsyncSession,
        buyer_telegram_user_id: int,
        since: datetime,
    ) -> int:
        result = await session.execute(
            select(func.count(AuditLog.id))
            .where(AuditLog.action == "platform_risk.order_creation_blocked")
            .where(AuditLog.target_type == "order_creation")
            .where(AuditLog.target_id == str(buyer_telegram_user_id))
            .where(AuditLog.created_at >= since)
        )
        return int(result.scalar_one() or 0)

    def _add_order_risk_audit(
        self,
        *,
        session: AsyncSession,
        tenant_id: Optional[int],
        buyer_telegram_user_id: int,
        rule: str,
        source_type: Optional[str],
        amount: Decimal,
        currency: str,
        recent_count: int,
        daily_amount: Optional[Decimal],
    ) -> None:
        metadata = {
            "rule": rule,
            "buyer_telegram_user_id": buyer_telegram_user_id,
            "source_type": source_type,
            "amount": str(amount),
            "currency": currency,
            "recent_count": recent_count,
            "recent_window_seconds": self.settings.order_risk_recent_window_seconds,
            "recent_limit": self.settings.order_risk_max_buyer_orders_per_window,
            "daily_window_seconds": self.settings.order_risk_daily_window_seconds,
            "daily_limit": str(self.settings.order_risk_max_buyer_amount_per_day),
        }
        if daily_amount is not None:
            metadata["daily_amount"] = str(daily_amount)
            metadata["daily_amount_with_current"] = str(daily_amount + amount)
        session.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_user_id=None,
                action="platform_risk.order_creation_blocked",
                target_type="order_creation",
                target_id=str(buyer_telegram_user_id),
                metadata_json=metadata,
            )
        )

    async def _tenant_webhook_secrets(self, session: AsyncSession, tenant_id: int) -> Tuple[str, ...]:
        result = await session.execute(
            select(TenantBot.webhook_secret)
            .where(TenantBot.tenant_id == tenant_id)
        )
        return tuple(result.scalars().all())

    async def _last_status_before_suspension(self, session: AsyncSession, tenant_id: int) -> str:
        result = await session.execute(
            select(AuditLog.metadata_json)
            .where(AuditLog.tenant_id == tenant_id)
            .where(AuditLog.action == "platform_risk.tenant_suspended")
            .where(AuditLog.target_type == "tenant")
            .where(AuditLog.target_id == str(tenant_id))
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(1)
        )
        metadata = result.scalar_one_or_none() or {}
        previous_status = metadata.get("previous_status")
        if previous_status in RESUMABLE_TENANT_STATUSES:
            return str(previous_status)
        return "active"

    def _add_dispute_audit(
        self,
        session: AsyncSession,
        dispute: Dispute,
        actor_user_id: int,
        action: str,
        order: Order,
        note: Optional[str],
    ) -> None:
        session.add(
            AuditLog(
                tenant_id=dispute.tenant_id,
                actor_user_id=actor_user_id,
                action=action,
                target_type="dispute",
                target_id=str(dispute.id),
                metadata_json={
                    "out_trade_no": order.out_trade_no,
                    "order_id": order.id,
                    "status": dispute.status,
                    "reason": note,
                },
            )
        )

    def _add_after_sale_audit(
        self,
        session: AsyncSession,
        after_sale: AfterSaleCase,
        actor_user_id: int,
        action: str,
        order: Order,
        note: Optional[str],
        refund_id: Optional[int] = None,
        refund_amount: Optional[Decimal] = None,
    ) -> None:
        metadata = {
            "out_trade_no": order.out_trade_no,
            "order_id": order.id,
            "case_type": after_sale.case_type,
            "status": after_sale.status,
            "reason": note,
        }
        if after_sale.requested_amount is not None:
            metadata["requested_amount"] = str(after_sale.requested_amount)
        if refund_id is not None:
            metadata["refund_id"] = refund_id
        if refund_amount is not None:
            metadata["refund_amount"] = str(refund_amount)
        session.add(
            AuditLog(
                tenant_id=after_sale.tenant_id,
                actor_user_id=actor_user_id,
                action=action,
                target_type="after_sale_case",
                target_id=str(after_sale.id),
                metadata_json=metadata,
            )
        )

    @staticmethod
    def _add_platform_user_audit(
        *,
        session: AsyncSession,
        user: PlatformUser,
        actor_user_id: Optional[int],
        action: str,
        previous_status: str,
        new_status: str,
        reason: Optional[str],
    ) -> None:
        session.add(
            AuditLog(
                tenant_id=None,
                actor_user_id=actor_user_id,
                action=action,
                target_type="platform_user",
                target_id=str(user.id),
                metadata_json={
                    "telegram_user_id": user.telegram_user_id,
                    "previous_status": previous_status,
                    "new_status": new_status,
                    "reason": reason,
                },
            )
        )

    @staticmethod
    def _dispute_summary(dispute: Dispute, order: Order) -> DisputeSummary:
        return DisputeSummary(
            dispute_id=dispute.id,
            tenant_id=dispute.tenant_id,
            order_id=order.id,
            out_trade_no=order.out_trade_no,
            buyer_telegram_user_id=dispute.buyer_telegram_user_id,
            source_type=order.source_type,
            order_status=order.status,
            amount=order.amount,
            currency=order.currency,
            status=dispute.status,
            reason=dispute.reason,
            resolution=dispute.resolution,
            created_at=dispute.created_at,
            updated_at=dispute.updated_at,
        )

    @staticmethod
    def _after_sale_summary(after_sale: AfterSaleCase, order: Order) -> AfterSaleSummary:
        return AfterSaleSummary(
            case_id=after_sale.id,
            tenant_id=after_sale.tenant_id,
            order_id=order.id,
            out_trade_no=order.out_trade_no,
            buyer_telegram_user_id=after_sale.buyer_telegram_user_id,
            source_type=order.source_type,
            order_status=order.status,
            amount=order.amount,
            currency=order.currency,
            case_type=after_sale.case_type,
            status=after_sale.status,
            requested_amount=after_sale.requested_amount,
            refunded_amount=after_sale.refunded_amount,
            refund_id=after_sale.refund_id,
            reason=after_sale.reason,
            resolution=after_sale.resolution,
            created_at=after_sale.created_at,
            updated_at=after_sale.updated_at,
        )

    @staticmethod
    def _normalize_reason(reason: Optional[str]) -> Optional[str]:
        if reason is None:
            return None
        normalized = reason.strip()
        if not normalized:
            return None
        if len(normalized) > 500:
            raise ValueError("原因不能超过 500 个字符")
        return normalized

    @staticmethod
    def _normalize_platform_ban_source(source: Optional[str]) -> str:
        if source is None:
            return "all"
        if not isinstance(source, str):
            raise ValueError("封禁来源必须是字符串")
        normalized = source.strip().lower()
        if not normalized:
            return "all"
        if normalized not in PLATFORM_BAN_SOURCE_VALUES:
            raise ValueError("封禁来源必须是 all/manual/auto")
        return normalized

    def _platform_user_ban_summary(
        self,
        user: PlatformUser,
        audit: Optional[AuditLog],
    ) -> PlatformRiskBannedUserSummary:
        metadata = audit.metadata_json if audit is not None and isinstance(audit.metadata_json, dict) else {}
        latest_action = audit.action if audit is not None else None
        ban_source = self._platform_ban_source_from_action(latest_action)
        return PlatformRiskBannedUserSummary(
            telegram_user_id=user.telegram_user_id,
            username=user.username,
            is_banned=bool(user.is_banned),
            ban_source=ban_source,
            latest_action=latest_action,
            latest_action_at=audit.created_at if audit is not None else None,
            reason=self._sanitize_platform_ban_reason(metadata.get("reason")),
            trigger_rule=self._sanitize_platform_ban_short_text(metadata.get("trigger_rule")),
            blocked_count=self._safe_optional_int(metadata.get("blocked_count")),
            threshold=self._safe_optional_int(metadata.get("threshold")),
            window_seconds=self._safe_optional_int(metadata.get("window_seconds")),
            created_at=user.created_at,
            updated_at=user.updated_at,
        )

    def _platform_user_ban_status_summary(
        self,
        user: PlatformUser,
        latest_status_audit: Optional[AuditLog],
        latest_ban_audit: Optional[AuditLog],
    ) -> PlatformRiskBanStatusSummary:
        status_metadata = (
            latest_status_audit.metadata_json
            if latest_status_audit is not None and isinstance(latest_status_audit.metadata_json, dict)
            else {}
        )
        ban_metadata = (
            latest_ban_audit.metadata_json
            if latest_ban_audit is not None and isinstance(latest_ban_audit.metadata_json, dict)
            else {}
        )
        latest_action = latest_status_audit.action if latest_status_audit is not None else None
        ban_source = self._platform_ban_source_from_action(latest_ban_audit.action) if latest_ban_audit is not None else "unknown"
        return PlatformRiskBanStatusSummary(
            telegram_user_id=user.telegram_user_id,
            username=user.username,
            is_banned=bool(user.is_banned),
            ban_source=ban_source if bool(user.is_banned) else None,
            latest_action=latest_action,
            latest_action_at=latest_status_audit.created_at if latest_status_audit is not None else None,
            reason=self._sanitize_platform_ban_reason(status_metadata.get("reason")),
            trigger_rule=self._sanitize_platform_ban_short_text(ban_metadata.get("trigger_rule")),
            blocked_count=self._safe_optional_int(ban_metadata.get("blocked_count")),
            threshold=self._safe_optional_int(ban_metadata.get("threshold")),
            window_seconds=self._safe_optional_int(ban_metadata.get("window_seconds")),
            created_at=user.created_at,
            updated_at=user.updated_at,
        )

    @staticmethod
    def _platform_ban_source_from_action(action: Optional[str]) -> str:
        if action == "platform_risk.user_banned":
            return "manual"
        if action == "platform_risk.user_auto_banned":
            return "auto"
        return "unknown"

    @classmethod
    def _sanitize_platform_ban_reason(cls, value: Any) -> Optional[str]:
        return cls._sanitize_platform_ban_text(value, max_length=160)

    @classmethod
    def _sanitize_platform_ban_short_text(cls, value: Any) -> Optional[str]:
        return cls._sanitize_platform_ban_text(value, max_length=128)

    @staticmethod
    def _sanitize_platform_ban_text(value: Any, *, max_length: int) -> Optional[str]:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        lowered = normalized.lower()
        if "http://" in lowered or "https://" in lowered:
            return "内容已隐藏"
        if any(marker in lowered for marker in PLATFORM_BAN_REASON_SENSITIVE_MARKERS):
            return "内容已隐藏"
        return normalized[:max_length]

    @staticmethod
    def _safe_optional_int(value: Any) -> Optional[int]:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        return None

    @staticmethod
    def _normalize_telegram_user_id(telegram_user_id: int) -> int:
        if not isinstance(telegram_user_id, int) or isinstance(telegram_user_id, bool) or telegram_user_id <= 0:
            raise ValueError("Telegram 用户 ID 必须是正整数")
        return telegram_user_id

    def _normalize_required_text(self, value: Optional[str], label: str) -> str:
        normalized = self._normalize_reason(value)
        if normalized is None:
            raise ValueError(f"{label}不能为空")
        return normalized

    @staticmethod
    def _normalize_after_sale_case_type(case_type: str) -> str:
        if not isinstance(case_type, str):
            raise ValueError("售后类型必须是字符串")
        normalized = case_type.strip().lower()
        if normalized not in AFTER_SALE_CASE_TYPES:
            raise ValueError("售后类型必须是 refund、complaint 或 reseller_after_sale")
        return normalized

    def _normalize_required_amount(self, amount: Decimal, label: str) -> Decimal:
        normalized = self._normalize_optional_amount(amount, label)
        if normalized is None:
            raise ValueError(f"{label}不能为空")
        return normalized

    @staticmethod
    def _normalize_currency(currency: str) -> str:
        if not isinstance(currency, str):
            raise ValueError("币种必须是字符串")
        normalized = currency.strip().upper()
        if not normalized:
            raise ValueError("币种不能为空")
        if len(normalized) > 16:
            raise ValueError("币种长度不能超过 16 个字符")
        return normalized

    @staticmethod
    def _normalize_optional_amount(amount: Optional[Decimal], label: str) -> Optional[Decimal]:
        if amount is None:
            return None
        if not isinstance(amount, Decimal):
            raise ValueError(f"{label}必须是 Decimal")
        if not amount.is_finite():
            raise ValueError(f"{label}必须是有限数")
        normalized = amount.quantize(AMOUNT_QUANT, rounding=ROUND_DOWN)
        if normalized <= 0:
            raise ValueError(f"{label}必须大于 0")
        return normalized

    @staticmethod
    def _normalize_limit(limit: int) -> int:
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("查询数量必须是整数")
        return min(max(limit, 1), 100)
