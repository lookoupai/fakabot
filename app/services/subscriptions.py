from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.orders import Order
from app.db.models.subscriptions import SubscriptionInvoice, SubscriptionPlan, TenantSubscription
from app.db.models.tenants import AuditLog, PlatformUser, Tenant


@dataclass
class SubscriptionStatus:
    tenant_id: int
    status: str
    plan_code: Optional[str]
    trial_ends_at: Optional[datetime]
    subscription_ends_at: Optional[datetime]


@dataclass(frozen=True)
class TenantSubscriptionSummary:
    status: str
    plan_code: Optional[str]
    plan_name: Optional[str]
    monthly_price: Optional[Decimal]
    currency: Optional[str]
    trial_days: Optional[int]
    grace_days: Optional[int]
    trial_ends_at: Optional[datetime]
    current_period_ends_at: Optional[datetime]
    subscription_ends_at: Optional[datetime]
    grace_ends_at: Optional[datetime]
    suspended_at: Optional[datetime]
    data_retention_until: Optional[datetime]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


@dataclass(frozen=True)
class SubscriptionInvoiceSummary:
    out_trade_no: str
    amount: Decimal
    currency: str
    status: str
    paid_at: Optional[datetime]
    created_at: datetime


@dataclass(frozen=True)
class PlatformSubscriptionPlanSummary:
    code: str
    name: str
    monthly_price: Decimal
    currency: str
    trial_days: int
    grace_days: int
    enabled: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


@dataclass(frozen=True)
class PlatformSubscriptionAttentionItem:
    tenant_public_id: str
    store_name: str
    owner_telegram_user_id: int
    owner_username: Optional[str]
    tenant_status: str
    subscription_status: str
    plan_code: Optional[str]
    plan_name: Optional[str]
    attention_reason: str
    trial_ends_at: Optional[datetime]
    current_period_ends_at: Optional[datetime]
    subscription_ends_at: Optional[datetime]
    grace_ends_at: Optional[datetime]
    suspended_at: Optional[datetime]
    data_retention_until: Optional[datetime]


@dataclass
class SubscriptionOrder:
    order_id: int
    out_trade_no: str
    amount: Decimal
    currency: str
    months: int
    expires_at: datetime


@dataclass
class SubscriptionAdjustmentResult:
    tenant_id: int
    status: str
    previous_period_ends_at: Optional[datetime]
    new_period_ends_at: datetime
    action: str


@dataclass
class SubscriptionAdminStatusDecision:
    status: str
    should_clear_suspension: bool = False


@dataclass
class SubscriptionLifecycleDecision:
    should_remind: bool = False
    next_status: Optional[str] = None
    grace_ends_at: Optional[datetime] = None
    suspended_at: Optional[datetime] = None
    data_retention_until: Optional[datetime] = None


@dataclass
class SubscriptionExpiryReminder:
    tenant_id: int
    period_ends_at: datetime


@dataclass
class SubscriptionLifecycleResult:
    reminded_count: int = 0
    grace_started_count: int = 0
    suspended_count: int = 0
    retention_expired_count: int = 0
    expiry_reminders: list[SubscriptionExpiryReminder] = field(default_factory=list)

    @property
    def changed_count(self) -> int:
        return (
            self.reminded_count
            + self.grace_started_count
            + self.suspended_count
            + self.retention_expired_count
        )


class SubscriptionService:
    DEFAULT_PLAN_CODE = "default_monthly"
    DEFAULT_PLAN_NAME = "默认月付套餐"
    DEFAULT_TRIAL_DAYS = 30
    DEFAULT_GRACE_DAYS = 0
    DEFAULT_RETENTION_DAYS = 30
    ACTIVE_STATUSES = ("trial", "active", "grace")
    EXPIRY_REMINDER_ACTION = "subscription.expiry_reminder"
    GRACE_STARTED_ACTION = "subscription.grace_started"
    SUSPENDED_ACTION = "subscription.suspended"
    RETENTION_EXPIRED_ACTION = "subscription.retention_expired"
    ADMIN_DAYS_GRANTED_ACTION = "subscription.admin_days_granted"
    ADMIN_EXPIRY_SET_ACTION = "subscription.admin_expiry_set"
    PLATFORM_PLAN_CREATED_ACTION = "subscription.plan_created"
    PLATFORM_PLAN_UPDATED_ACTION = "subscription.plan_updated"
    PLATFORM_PLAN_STATUS_UPDATED_ACTION = "subscription.plan_status_updated"

    async def get_status(self, session: AsyncSession, tenant_id: int) -> SubscriptionStatus:
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise ValueError("租户不存在")
        subscription = await self._get_subscription(session, tenant_id)
        if subscription is None:
            return SubscriptionStatus(
                tenant_id=tenant.id,
                status=tenant.status,
                plan_code=tenant.plan_code,
                trial_ends_at=tenant.trial_ends_at,
                subscription_ends_at=tenant.subscription_ends_at,
            )
        return SubscriptionStatus(
            tenant_id=tenant.id,
            status=tenant.status,
            plan_code=subscription.plan.code if subscription.plan is not None else tenant.plan_code,
            trial_ends_at=subscription.trial_ends_at or tenant.trial_ends_at,
            subscription_ends_at=subscription.current_period_ends_at or tenant.subscription_ends_at,
        )

    async def get_tenant_subscription_summary(
        self,
        session: AsyncSession,
        tenant_id: int,
    ) -> Optional[TenantSubscriptionSummary]:
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            return None
        subscription = await self._get_subscription(session, tenant_id)
        plan = subscription.plan if subscription is not None else None
        return TenantSubscriptionSummary(
            status=tenant.status,
            plan_code=plan.code if plan is not None else tenant.plan_code,
            plan_name=plan.name if plan is not None else None,
            monthly_price=plan.monthly_price if plan is not None else None,
            currency=plan.currency if plan is not None else None,
            trial_days=plan.trial_days if plan is not None else None,
            grace_days=plan.grace_days if plan is not None else None,
            trial_ends_at=(
                subscription.trial_ends_at
                if subscription is not None and subscription.trial_ends_at is not None
                else tenant.trial_ends_at
            ),
            current_period_ends_at=(
                subscription.current_period_ends_at
                if subscription is not None and subscription.current_period_ends_at is not None
                else tenant.subscription_ends_at
            ),
            subscription_ends_at=tenant.subscription_ends_at,
            grace_ends_at=subscription.grace_ends_at if subscription is not None else None,
            suspended_at=tenant.suspended_at,
            data_retention_until=tenant.data_retention_until,
            created_at=subscription.created_at if subscription is not None else None,
            updated_at=subscription.updated_at if subscription is not None else None,
        )

    async def list_tenant_subscription_invoices(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> list[SubscriptionInvoiceSummary]:
        normalized_limit = self._normalize_invoice_limit(limit)
        normalized_status = self._normalize_invoice_status(status)
        query = select(SubscriptionInvoice).where(SubscriptionInvoice.tenant_id == tenant_id)
        if normalized_status is not None:
            query = query.where(SubscriptionInvoice.status == normalized_status)
        result = await session.execute(
            query.order_by(SubscriptionInvoice.created_at.desc(), SubscriptionInvoice.id.desc()).limit(normalized_limit)
        )
        return [
            SubscriptionInvoiceSummary(
                out_trade_no=invoice.out_trade_no,
                amount=invoice.amount,
                currency=invoice.currency,
                status=invoice.status,
                paid_at=invoice.paid_at,
                created_at=invoice.created_at,
            )
            for invoice in result.scalars().all()
        ]

    async def list_platform_subscription_plans(
        self,
        session: AsyncSession,
        *,
        enabled: Optional[bool] = None,
        limit: int = 20,
    ) -> list[PlatformSubscriptionPlanSummary]:
        normalized_limit = self._normalize_invoice_limit(limit)
        query = select(SubscriptionPlan)
        if enabled is not None:
            query = query.where(SubscriptionPlan.enabled.is_(enabled))
        result = await session.execute(
            query.order_by(SubscriptionPlan.enabled.desc(), SubscriptionPlan.code.asc()).limit(normalized_limit)
        )
        return [self._plan_summary(plan) for plan in result.scalars().all()]

    async def list_platform_subscription_attention(
        self,
        session: AsyncSession,
        *,
        limit: int = 20,
        now: Optional[datetime] = None,
        reminder_days: int = 7,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ) -> list[PlatformSubscriptionAttentionItem]:
        normalized_limit = self._normalize_invoice_limit(limit)
        current_time = _ensure_aware(now or datetime.now(timezone.utc))
        reminder_cutoff = current_time + timedelta(days=max(reminder_days, 0))
        candidate_limit = min(max(normalized_limit * 5, 50), 500)
        result = await session.execute(
            select(Tenant, PlatformUser, TenantSubscription, SubscriptionPlan)
            .join(PlatformUser, PlatformUser.id == Tenant.owner_user_id)
            .outerjoin(TenantSubscription, TenantSubscription.tenant_id == Tenant.id)
            .outerjoin(SubscriptionPlan, SubscriptionPlan.id == TenantSubscription.plan_id)
            .where(
                or_(
                    Tenant.status.in_(("grace", "suspended", "retention_expired")),
                    TenantSubscription.status.in_(("grace", "suspended", "retention_expired")),
                    and_(
                        Tenant.data_retention_until.is_not(None),
                        Tenant.data_retention_until <= current_time,
                    ),
                    and_(
                        TenantSubscription.current_period_ends_at.is_not(None),
                        TenantSubscription.current_period_ends_at <= reminder_cutoff,
                    ),
                    and_(
                        Tenant.subscription_ends_at.is_not(None),
                        Tenant.subscription_ends_at <= reminder_cutoff,
                    ),
                    and_(
                        Tenant.trial_ends_at.is_not(None),
                        Tenant.trial_ends_at <= reminder_cutoff,
                    ),
                )
            )
            .order_by(Tenant.updated_at.desc(), Tenant.id.desc())
            .limit(candidate_limit)
        )
        rows: list[tuple[int, datetime, str, PlatformSubscriptionAttentionItem]] = []
        seen_tenants: set[str] = set()
        for tenant, owner, subscription, plan in result.all():
            if tenant.public_id in seen_tenants:
                continue
            attention = self._subscription_attention_item(
                tenant=tenant,
                owner=owner,
                subscription=subscription,
                plan=plan,
                now=current_time,
                reminder_days=reminder_days,
                retention_days=retention_days,
            )
            if attention is None:
                continue
            seen_tenants.add(tenant.public_id)
            rows.append(
                (
                    self._attention_reason_priority(attention.attention_reason),
                    self._attention_sort_time(attention),
                    tenant.public_id,
                    attention,
                )
            )
        rows.sort(key=lambda row: (row[0], row[1], row[2]))
        return [row[3] for row in rows[:normalized_limit]]

    async def get_platform_subscription_plan(
        self,
        session: AsyncSession,
        *,
        code: str,
    ) -> Optional[PlatformSubscriptionPlanSummary]:
        plan = await self._get_plan_by_code(session, self._normalize_plan_code(code))
        if plan is None:
            return None
        return self._plan_summary(plan)

    async def create_platform_subscription_plan(
        self,
        session: AsyncSession,
        *,
        code: str,
        name: str,
        monthly_price: Decimal,
        currency: str = "USDT",
        trial_days: int = DEFAULT_TRIAL_DAYS,
        grace_days: int = DEFAULT_GRACE_DAYS,
        enabled: bool = True,
        reason: Optional[str] = None,
    ) -> PlatformSubscriptionPlanSummary:
        normalized_code = self._normalize_plan_code(code)
        existing = await self._get_plan_by_code(session, normalized_code)
        if existing is not None:
            raise ValueError("订阅计划已存在")
        plan = SubscriptionPlan(
            code=normalized_code,
            name=self._normalize_plan_name(name),
            monthly_price=self._normalize_monthly_price(monthly_price),
            currency=self._normalize_plan_currency(currency),
            trial_days=self._normalize_plan_days(trial_days, "试用天数", 3650),
            grace_days=self._normalize_plan_days(grace_days, "宽限天数", 365),
            enabled=bool(enabled),
        )
        session.add(plan)
        await session.flush()
        self._add_platform_plan_audit(
            session,
            plan,
            action=self.PLATFORM_PLAN_CREATED_ACTION,
            reason=reason,
        )
        await session.flush()
        return self._plan_summary(plan)

    async def update_platform_subscription_plan(
        self,
        session: AsyncSession,
        *,
        code: str,
        name: Optional[str] = None,
        monthly_price: Optional[Decimal] = None,
        currency: Optional[str] = None,
        trial_days: Optional[int] = None,
        grace_days: Optional[int] = None,
        reason: Optional[str] = None,
    ) -> Optional[PlatformSubscriptionPlanSummary]:
        plan = await self._get_plan_by_code(session, self._normalize_plan_code(code))
        if plan is None:
            return None
        if name is not None:
            plan.name = self._normalize_plan_name(name)
        if monthly_price is not None:
            plan.monthly_price = self._normalize_monthly_price(monthly_price)
        if currency is not None:
            plan.currency = self._normalize_plan_currency(currency)
        if trial_days is not None:
            plan.trial_days = self._normalize_plan_days(trial_days, "试用天数", 3650)
        if grace_days is not None:
            plan.grace_days = self._normalize_plan_days(grace_days, "宽限天数", 365)
        self._add_platform_plan_audit(
            session,
            plan,
            action=self.PLATFORM_PLAN_UPDATED_ACTION,
            reason=reason,
        )
        await session.flush()
        return self._plan_summary(plan)

    async def set_platform_subscription_plan_enabled(
        self,
        session: AsyncSession,
        *,
        code: str,
        enabled: bool,
        reason: Optional[str] = None,
    ) -> Optional[PlatformSubscriptionPlanSummary]:
        plan = await self._get_plan_by_code(session, self._normalize_plan_code(code))
        if plan is None:
            return None
        plan.enabled = bool(enabled)
        self._add_platform_plan_audit(
            session,
            plan,
            action=self.PLATFORM_PLAN_STATUS_UPDATED_ACTION,
            reason=reason,
        )
        await session.flush()
        return self._plan_summary(plan)

    async def bootstrap_tenant_subscription(
        self,
        session: AsyncSession,
        tenant_id: int,
        monthly_price: Decimal,
    ) -> None:
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise ValueError("租户不存在")
        plan = await self._ensure_default_plan(session, monthly_price)
        subscription = await self._get_subscription(session, tenant_id)
        if subscription is None:
            subscription = TenantSubscription(
                tenant_id=tenant.id,
                plan_id=plan.id,
                status=tenant.status,
                trial_ends_at=tenant.trial_ends_at,
                current_period_ends_at=tenant.trial_ends_at or tenant.subscription_ends_at,
            )
            session.add(subscription)
        else:
            subscription.plan_id = plan.id
            if subscription.trial_ends_at is None:
                subscription.trial_ends_at = tenant.trial_ends_at
            if subscription.current_period_ends_at is None:
                subscription.current_period_ends_at = tenant.trial_ends_at or tenant.subscription_ends_at
        tenant.plan_code = tenant.plan_code or plan.code
        tenant.subscription_ends_at = tenant.subscription_ends_at or tenant.trial_ends_at
        await session.flush()

    async def create_renewal_order(
        self,
        session: AsyncSession,
        tenant_id: int,
        buyer_telegram_user_id: int,
        months: int,
        monthly_price: Decimal,
    ) -> SubscriptionOrder:
        if not 1 <= months <= 24:
            raise ValueError("续费月数范围为 1-24")
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise ValueError("租户不存在")
        subscription = await self._ensure_subscription(session, tenant, monthly_price)
        plan = subscription.plan
        effective_monthly_price = plan.monthly_price if plan is not None else monthly_price
        effective_currency = plan.currency if plan is not None else "USDT"

        amount = effective_monthly_price * Decimal(months)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
        order = Order(
            tenant_id=tenant_id,
            buyer_telegram_user_id=buyer_telegram_user_id,
            source_type="subscription",
            subscription_months=months,
            amount=amount,
            currency=effective_currency,
            display_amount=amount,
            display_currency=effective_currency,
            payment_mode="pending_payment",
            status="pending",
            out_trade_no=self._new_out_trade_no(),
            expires_at=expires_at,
        )
        session.add(order)
        await session.flush()
        session.add(
            SubscriptionInvoice(
                tenant_id=tenant_id,
                subscription_id=subscription.id,
                amount=amount,
                currency=order.currency,
                status="pending",
                out_trade_no=order.out_trade_no,
            )
        )
        await session.flush()
        return SubscriptionOrder(
            order_id=order.id,
            out_trade_no=order.out_trade_no,
            amount=order.amount,
            currency=order.currency,
            months=months,
            expires_at=order.expires_at,
        )

    async def apply_paid_order(self, session: AsyncSession, order: Order) -> None:
        if order.source_type != "subscription":
            return
        if not order.subscription_months or order.subscription_months <= 0:
            raise ValueError("订阅订单缺少续费月数")
        tenant = await session.get(Tenant, order.tenant_id)
        if tenant is None:
            raise ValueError("租户不存在")

        now = datetime.now(timezone.utc)
        subscription = await self._ensure_subscription(session, tenant, order.amount / Decimal(order.subscription_months))
        current_end = self._latest_period_end(
            subscription.current_period_ends_at,
            tenant.subscription_ends_at,
            tenant.trial_ends_at,
        )
        base_time = current_end if current_end is not None and current_end > now else now
        period_end = base_time + timedelta(days=30 * order.subscription_months)
        tenant.subscription_ends_at = period_end
        is_subscription_suspension = tenant.status == "suspended" and tenant.data_retention_until is not None
        if tenant.status in self.ACTIVE_STATUSES or is_subscription_suspension:
            tenant.status = "active"
            tenant.suspended_at = None
            tenant.data_retention_until = None
        tenant.plan_code = tenant.plan_code or self.DEFAULT_PLAN_CODE
        subscription.status = tenant.status
        subscription.current_period_ends_at = period_end
        subscription.grace_ends_at = None
        invoice = await self._get_invoice_by_out_trade_no(session, order.out_trade_no)
        if invoice is not None:
            invoice.status = "paid"
            invoice.paid_at = order.paid_at or now
        order.status = "completed"
        order.delivered_at = order.delivered_at or now
        await session.flush()

    async def grant_days(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        actor_user_id: int,
        days: int,
        monthly_price: Decimal,
        reason: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> SubscriptionAdjustmentResult:
        if days <= 0 or days > 3650:
            raise ValueError("赠送天数范围为 1-3650")
        current_time = _ensure_aware(now or datetime.now(timezone.utc))
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise ValueError("租户不存在")
        subscription = await self._ensure_subscription(session, tenant, monthly_price)
        previous_period_end = self._latest_period_end(
            subscription.current_period_ends_at,
            tenant.subscription_ends_at,
            tenant.trial_ends_at,
        )
        base_time = previous_period_end if previous_period_end is not None and previous_period_end > current_time else current_time
        new_period_end = base_time + timedelta(days=days)
        return await self._apply_admin_period_adjustment(
            session=session,
            tenant=tenant,
            subscription=subscription,
            actor_user_id=actor_user_id,
            new_period_end=new_period_end,
            action=self.ADMIN_DAYS_GRANTED_ACTION,
            reason=reason,
            metadata={"days": days, "base_time": _isoformat(base_time)},
            now=current_time,
        )

    async def set_period_end(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        actor_user_id: int,
        period_ends_at: datetime,
        monthly_price: Decimal,
        reason: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> SubscriptionAdjustmentResult:
        current_time = _ensure_aware(now or datetime.now(timezone.utc))
        new_period_end = _ensure_aware(period_ends_at)
        if new_period_end is None or new_period_end <= current_time:
            raise ValueError("订阅到期时间必须晚于当前时间")
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise ValueError("租户不存在")
        subscription = await self._ensure_subscription(session, tenant, monthly_price)
        return await self._apply_admin_period_adjustment(
            session=session,
            tenant=tenant,
            subscription=subscription,
            actor_user_id=actor_user_id,
            new_period_end=new_period_end,
            action=self.ADMIN_EXPIRY_SET_ACTION,
            reason=reason,
            metadata={},
            now=current_time,
        )

    async def process_lifecycle(
        self,
        session: AsyncSession,
        *,
        now: Optional[datetime] = None,
        reminder_days: int = 3,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        limit: int = 500,
    ) -> SubscriptionLifecycleResult:
        current_time = _ensure_aware(now or datetime.now(timezone.utc))
        reminder_cutoff = current_time + timedelta(days=max(reminder_days, 0))
        result = await session.execute(
            select(TenantSubscription, Tenant)
            .join(Tenant, Tenant.id == TenantSubscription.tenant_id)
            .options(selectinload(TenantSubscription.plan))
            .where(
                or_(
                    and_(
                        Tenant.status.in_(("trial", "active")),
                        TenantSubscription.current_period_ends_at.is_not(None),
                        TenantSubscription.current_period_ends_at <= reminder_cutoff,
                    ),
                    Tenant.status == "grace",
                    and_(
                        Tenant.status == "suspended",
                        Tenant.data_retention_until.is_not(None),
                        Tenant.data_retention_until <= current_time,
                    ),
                )
            )
            .order_by(TenantSubscription.current_period_ends_at.asc(), TenantSubscription.id.asc())
            .limit(limit)
        )
        lifecycle_result = SubscriptionLifecycleResult()
        for subscription, tenant in result.all():
            plan = subscription.plan
            decision = self.evaluate_lifecycle(
                tenant_status=tenant.status,
                period_ends_at=subscription.current_period_ends_at,
                grace_ends_at=subscription.grace_ends_at,
                data_retention_until=tenant.data_retention_until,
                plan_grace_days=plan.grace_days if plan is not None else self.DEFAULT_GRACE_DAYS,
                now=current_time,
                reminder_days=reminder_days,
                retention_days=retention_days,
            )
            if decision.should_remind and subscription.current_period_ends_at is not None:
                reminded = await self._add_lifecycle_audit_once(
                    session=session,
                    tenant_id=tenant.id,
                    subscription_id=subscription.id,
                    action=self.EXPIRY_REMINDER_ACTION,
                    period_ends_at=subscription.current_period_ends_at,
                    metadata={
                        "period_ends_at": _isoformat(subscription.current_period_ends_at),
                        "tenant_status": tenant.status,
                    },
                )
                if reminded:
                    lifecycle_result.reminded_count += 1
                    lifecycle_result.expiry_reminders.append(
                        SubscriptionExpiryReminder(
                            tenant_id=tenant.id,
                            period_ends_at=subscription.current_period_ends_at,
                        )
                    )
            if decision.next_status is None:
                continue

            if decision.next_status == "grace":
                tenant.status = "grace"
                subscription.status = "grace"
                subscription.grace_ends_at = decision.grace_ends_at
                lifecycle_result.grace_started_count += 1
                session.add(
                    self._new_lifecycle_audit(
                        tenant_id=tenant.id,
                        subscription_id=subscription.id,
                        action=self.GRACE_STARTED_ACTION,
                        metadata={
                            "period_ends_at": _isoformat(subscription.current_period_ends_at),
                            "grace_ends_at": _isoformat(decision.grace_ends_at),
                        },
                    )
                )
                continue

            if decision.next_status == "suspended":
                tenant.status = "suspended"
                tenant.suspended_at = decision.suspended_at
                tenant.data_retention_until = decision.data_retention_until
                subscription.status = "suspended"
                lifecycle_result.suspended_count += 1
                session.add(
                    self._new_lifecycle_audit(
                        tenant_id=tenant.id,
                        subscription_id=subscription.id,
                        action=self.SUSPENDED_ACTION,
                        metadata={
                            "period_ends_at": _isoformat(subscription.current_period_ends_at),
                            "grace_ends_at": _isoformat(subscription.grace_ends_at),
                            "data_retention_until": _isoformat(decision.data_retention_until),
                        },
                    )
                )
                continue

            if decision.next_status == "retention_expired":
                tenant.status = "retention_expired"
                subscription.status = "retention_expired"
                lifecycle_result.retention_expired_count += 1
                session.add(
                    self._new_lifecycle_audit(
                        tenant_id=tenant.id,
                        subscription_id=subscription.id,
                        action=self.RETENTION_EXPIRED_ACTION,
                        metadata={
                            "data_retention_until": _isoformat(tenant.data_retention_until),
                            "next_step": "pending_admin_archive",
                        },
                    )
                )
        await session.flush()
        return lifecycle_result

    def evaluate_lifecycle(
        self,
        *,
        tenant_status: str,
        period_ends_at: Optional[datetime],
        grace_ends_at: Optional[datetime],
        data_retention_until: Optional[datetime],
        plan_grace_days: int,
        now: datetime,
        reminder_days: int,
        retention_days: int,
    ) -> SubscriptionLifecycleDecision:
        current_time = _ensure_aware(now)
        period_end = _ensure_aware(period_ends_at)
        grace_end = _ensure_aware(grace_ends_at)
        retention_end = _ensure_aware(data_retention_until)
        if tenant_status == "suspended":
            if retention_end is not None and retention_end <= current_time:
                return SubscriptionLifecycleDecision(next_status="retention_expired")
            return SubscriptionLifecycleDecision()
        if tenant_status not in self.ACTIVE_STATUSES or period_end is None:
            return SubscriptionLifecycleDecision()
        if tenant_status == "grace":
            effective_grace_end = grace_end or period_end + timedelta(days=max(plan_grace_days, 0))
            if effective_grace_end <= current_time:
                return self._suspension_decision(current_time, retention_days)
            return SubscriptionLifecycleDecision()
        if period_end <= current_time:
            if plan_grace_days > 0:
                effective_grace_end = period_end + timedelta(days=plan_grace_days)
                if effective_grace_end > current_time:
                    return SubscriptionLifecycleDecision(
                        next_status="grace",
                        grace_ends_at=effective_grace_end,
                    )
            return self._suspension_decision(current_time, retention_days)
        should_remind = period_end <= current_time + timedelta(days=max(reminder_days, 0))
        return SubscriptionLifecycleDecision(should_remind=should_remind)

    async def _ensure_subscription(
        self,
        session: AsyncSession,
        tenant: Tenant,
        monthly_price: Decimal,
    ) -> TenantSubscription:
        plan = await self._ensure_default_plan(session, monthly_price)
        result = await session.execute(
            select(TenantSubscription)
            .options(selectinload(TenantSubscription.plan))
            .where(TenantSubscription.tenant_id == tenant.id)
        )
        subscription = result.scalar_one_or_none()
        if subscription is not None:
            if subscription.plan is None and subscription.plan_id == plan.id:
                subscription.plan = plan
            return subscription

        subscription = TenantSubscription(
            tenant_id=tenant.id,
            plan_id=plan.id,
            status=tenant.status,
            trial_ends_at=tenant.trial_ends_at,
            current_period_ends_at=tenant.trial_ends_at or tenant.subscription_ends_at,
        )
        subscription.plan = plan
        session.add(subscription)
        await session.flush()
        return subscription

    async def _ensure_default_plan(
        self,
        session: AsyncSession,
        monthly_price: Decimal,
    ) -> SubscriptionPlan:
        result = await session.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.code == self.DEFAULT_PLAN_CODE)
        )
        plan = result.scalar_one_or_none()
        if plan is not None:
            return plan

        plan = SubscriptionPlan(
            code=self.DEFAULT_PLAN_CODE,
            name=self.DEFAULT_PLAN_NAME,
            monthly_price=monthly_price,
            currency="USDT",
            trial_days=self.DEFAULT_TRIAL_DAYS,
            grace_days=self.DEFAULT_GRACE_DAYS,
            enabled=True,
        )
        session.add(plan)
        await session.flush()
        return plan

    async def _get_subscription(
        self,
        session: AsyncSession,
        tenant_id: int,
    ) -> Optional[TenantSubscription]:
        result = await session.execute(
            select(TenantSubscription)
            .options(selectinload(TenantSubscription.plan))
            .where(TenantSubscription.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def _get_invoice_by_out_trade_no(
        self,
        session: AsyncSession,
        out_trade_no: str,
    ) -> Optional[SubscriptionInvoice]:
        result = await session.execute(
            select(SubscriptionInvoice).where(SubscriptionInvoice.out_trade_no == out_trade_no)
        )
        return result.scalar_one_or_none()

    async def _get_plan_by_code(
        self,
        session: AsyncSession,
        code: str,
    ) -> Optional[SubscriptionPlan]:
        result = await session.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.code == code)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _normalize_invoice_limit(limit: int) -> int:
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("limit 必须是整数")
        return min(max(limit, 1), 100)

    @staticmethod
    def _normalize_invoice_status(status: Optional[str]) -> Optional[str]:
        if status is None:
            return None
        if not isinstance(status, str):
            raise ValueError("status 必须是字符串")
        normalized = status.strip()
        if normalized not in {"pending", "paid"}:
            raise ValueError("status 无效")
        return normalized

    @staticmethod
    def _normalize_plan_code(code: str) -> str:
        normalized = str(code).strip()
        if not normalized:
            raise ValueError("订阅计划 code 不能为空")
        if len(normalized) > 64:
            raise ValueError("订阅计划 code 不能超过 64 个字符")
        if not normalized[0].isalnum():
            raise ValueError("订阅计划 code 必须以字母或数字开头")
        allowed_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-")
        if any(char not in allowed_chars for char in normalized):
            raise ValueError("订阅计划 code 只能包含字母、数字、下划线、点、冒号或短横线")
        return normalized

    @staticmethod
    def _normalize_plan_name(name: str) -> str:
        normalized = str(name).strip()
        if not normalized:
            raise ValueError("订阅计划名称不能为空")
        if len(normalized) > 128:
            raise ValueError("订阅计划名称不能超过 128 个字符")
        if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
            raise ValueError("订阅计划名称包含非法字符")
        return normalized

    @staticmethod
    def _normalize_plan_currency(currency: str) -> str:
        normalized = str(currency).strip().upper()
        if not normalized:
            raise ValueError("订阅计划币种不能为空")
        if len(normalized) > 16:
            raise ValueError("订阅计划币种不能超过 16 个字符")
        if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
            raise ValueError("订阅计划币种包含非法字符")
        return normalized

    @staticmethod
    def _normalize_monthly_price(monthly_price: Decimal) -> Decimal:
        if monthly_price < 0:
            raise ValueError("订阅月费不能小于 0")
        if monthly_price > Decimal("1000000"):
            raise ValueError("订阅月费不能超过 1000000")
        return monthly_price

    @staticmethod
    def _normalize_plan_days(days: int, field_name: str, max_days: int) -> int:
        if not isinstance(days, int) or isinstance(days, bool):
            raise ValueError(f"{field_name}必须是整数")
        if days < 0 or days > max_days:
            raise ValueError(f"{field_name}范围为 0-{max_days}")
        return days

    @staticmethod
    def _normalize_optional_reason(reason: Optional[str]) -> Optional[str]:
        if reason is None:
            return None
        normalized = str(reason).strip()
        if not normalized:
            return None
        if len(normalized) > 500:
            raise ValueError("调整原因不能超过 500 个字符")
        if any(ord(char) < 32 and char not in "\r\n\t" for char in normalized):
            raise ValueError("调整原因包含非法字符")
        return normalized

    @staticmethod
    def _plan_summary(plan: SubscriptionPlan) -> PlatformSubscriptionPlanSummary:
        return PlatformSubscriptionPlanSummary(
            code=plan.code,
            name=plan.name,
            monthly_price=plan.monthly_price,
            currency=plan.currency,
            trial_days=plan.trial_days,
            grace_days=plan.grace_days,
            enabled=plan.enabled,
            created_at=plan.created_at,
            updated_at=plan.updated_at,
        )

    def _subscription_attention_item(
        self,
        *,
        tenant: Tenant,
        owner: PlatformUser,
        subscription: Optional[TenantSubscription],
        plan: Optional[SubscriptionPlan],
        now: datetime,
        reminder_days: int,
        retention_days: int,
    ) -> Optional[PlatformSubscriptionAttentionItem]:
        current_time = _ensure_aware(now)
        trial_ends_at = self._latest_period_end(
            subscription.trial_ends_at if subscription is not None else None,
            tenant.trial_ends_at,
        )
        current_period_ends_at = self._latest_period_end(
            subscription.current_period_ends_at if subscription is not None else None,
            tenant.subscription_ends_at,
            tenant.trial_ends_at,
        )
        grace_ends_at = _ensure_aware(subscription.grace_ends_at if subscription is not None else None)
        data_retention_until = _ensure_aware(tenant.data_retention_until)
        subscription_status = subscription.status if subscription is not None else tenant.status
        effective_status = tenant.status
        if tenant.status in {"trial", "active"} and subscription_status in {"grace", "suspended", "retention_expired"}:
            effective_status = subscription_status
        reason = self._classify_subscription_attention(
            effective_status=effective_status,
            period_ends_at=current_period_ends_at,
            grace_ends_at=grace_ends_at,
            data_retention_until=data_retention_until,
            plan_grace_days=plan.grace_days if plan is not None else self.DEFAULT_GRACE_DAYS,
            now=current_time,
            reminder_days=reminder_days,
            retention_days=retention_days,
        )
        if reason is None:
            return None
        return PlatformSubscriptionAttentionItem(
            tenant_public_id=tenant.public_id,
            store_name=tenant.store_name,
            owner_telegram_user_id=owner.telegram_user_id,
            owner_username=owner.username,
            tenant_status=tenant.status,
            subscription_status=effective_status,
            plan_code=plan.code if plan is not None else tenant.plan_code,
            plan_name=plan.name if plan is not None else None,
            attention_reason=reason,
            trial_ends_at=trial_ends_at,
            current_period_ends_at=current_period_ends_at,
            subscription_ends_at=_ensure_aware(tenant.subscription_ends_at),
            grace_ends_at=grace_ends_at,
            suspended_at=_ensure_aware(tenant.suspended_at),
            data_retention_until=data_retention_until,
        )

    def _classify_subscription_attention(
        self,
        *,
        effective_status: str,
        period_ends_at: Optional[datetime],
        grace_ends_at: Optional[datetime],
        data_retention_until: Optional[datetime],
        plan_grace_days: int,
        now: datetime,
        reminder_days: int,
        retention_days: int,
    ) -> Optional[str]:
        current_time = _ensure_aware(now)
        period_end = _ensure_aware(period_ends_at)
        retention_end = _ensure_aware(data_retention_until)
        if effective_status == "retention_expired":
            return "retention_expired"
        if effective_status == "suspended":
            if retention_end is not None and retention_end <= current_time:
                return "retention_expired"
            return "suspended"
        if effective_status == "grace":
            decision = self.evaluate_lifecycle(
                tenant_status="grace",
                period_ends_at=period_end,
                grace_ends_at=grace_ends_at,
                data_retention_until=retention_end,
                plan_grace_days=plan_grace_days,
                now=current_time,
                reminder_days=reminder_days,
                retention_days=retention_days,
            )
            if decision.next_status == "suspended":
                return "grace_expired"
            return "grace"
        if effective_status not in {"trial", "active"} or period_end is None:
            return None
        decision = self.evaluate_lifecycle(
            tenant_status=effective_status,
            period_ends_at=period_end,
            grace_ends_at=grace_ends_at,
            data_retention_until=retention_end,
            plan_grace_days=plan_grace_days,
            now=current_time,
            reminder_days=reminder_days,
            retention_days=retention_days,
        )
        if decision.next_status == "grace":
            return "expired"
        if decision.next_status == "suspended":
            return "expired"
        if decision.should_remind:
            return "expiring_soon"
        return None

    @staticmethod
    def _attention_reason_priority(reason: str) -> int:
        priorities = {
            "retention_expired": 0,
            "suspended": 1,
            "grace_expired": 2,
            "grace": 3,
            "expired": 4,
            "expiring_soon": 5,
        }
        return priorities.get(reason, 99)

    @staticmethod
    def _attention_sort_time(item: PlatformSubscriptionAttentionItem) -> datetime:
        for value in (
            item.data_retention_until,
            item.grace_ends_at,
            item.current_period_ends_at,
            item.subscription_ends_at,
            item.trial_ends_at,
        ):
            aware_value = _ensure_aware(value)
            if aware_value is not None:
                return aware_value
        return datetime.max.replace(tzinfo=timezone.utc)

    def _add_platform_plan_audit(
        self,
        session: AsyncSession,
        plan: SubscriptionPlan,
        *,
        action: str,
        reason: Optional[str],
    ) -> None:
        session.add(
            AuditLog(
                tenant_id=None,
                actor_user_id=None,
                action=action,
                target_type="subscription_plan",
                target_id=plan.code,
                metadata_json={
                    "code": plan.code,
                    "name": plan.name,
                    "monthly_price": str(plan.monthly_price),
                    "currency": plan.currency,
                    "trial_days": plan.trial_days,
                    "grace_days": plan.grace_days,
                    "enabled": plan.enabled,
                    "reason": self._normalize_optional_reason(reason),
                },
            )
        )

    async def _apply_admin_period_adjustment(
        self,
        *,
        session: AsyncSession,
        tenant: Tenant,
        subscription: TenantSubscription,
        actor_user_id: int,
        new_period_end: datetime,
        action: str,
        reason: Optional[str],
        metadata: dict[str, object],
        now: datetime,
    ) -> SubscriptionAdjustmentResult:
        previous_period_end = self._latest_period_end(
            subscription.current_period_ends_at,
            tenant.subscription_ends_at,
            tenant.trial_ends_at,
        )
        status_decision = self.evaluate_admin_period_adjustment(
            tenant_status=tenant.status,
            data_retention_until=tenant.data_retention_until,
        )
        tenant.subscription_ends_at = new_period_end
        subscription.current_period_ends_at = new_period_end
        subscription.grace_ends_at = None

        tenant.status = status_decision.status
        if status_decision.should_clear_suspension:
            tenant.suspended_at = None
            tenant.data_retention_until = None
        if tenant.status in {"trial", "active"}:
            subscription.status = tenant.status
        elif tenant.status == "suspended":
            subscription.status = "suspended"
        else:
            subscription.status = tenant.status

        audit_metadata = {
            **metadata,
            "previous_period_ends_at": _isoformat(previous_period_end),
            "new_period_ends_at": _isoformat(new_period_end),
            "reason": reason,
            "tenant_status": tenant.status,
            "adjusted_at": _isoformat(now),
        }
        session.add(
            AuditLog(
                tenant_id=tenant.id,
                actor_user_id=actor_user_id,
                action=action,
                target_type="tenant_subscription",
                target_id=str(subscription.id),
                metadata_json=audit_metadata,
            )
        )
        await session.flush()
        return SubscriptionAdjustmentResult(
            tenant_id=tenant.id,
            status=tenant.status,
            previous_period_ends_at=previous_period_end,
            new_period_ends_at=new_period_end,
            action=action,
        )

    def evaluate_admin_period_adjustment(
        self,
        *,
        tenant_status: str,
        data_retention_until: Optional[datetime],
    ) -> SubscriptionAdminStatusDecision:
        if tenant_status == "grace":
            return SubscriptionAdminStatusDecision(status="active")
        if tenant_status == "retention_expired":
            return SubscriptionAdminStatusDecision(status="active", should_clear_suspension=True)
        if tenant_status == "suspended" and data_retention_until is not None:
            return SubscriptionAdminStatusDecision(status="active", should_clear_suspension=True)
        return SubscriptionAdminStatusDecision(status=tenant_status)

    async def _add_lifecycle_audit_once(
        self,
        *,
        session: AsyncSession,
        tenant_id: int,
        subscription_id: int,
        action: str,
        period_ends_at: datetime,
        metadata: dict[str, object],
    ) -> bool:
        period_key = _isoformat(period_ends_at)
        result = await session.execute(
            select(AuditLog.metadata_json)
            .where(AuditLog.tenant_id == tenant_id)
            .where(AuditLog.action == action)
            .where(AuditLog.target_type == "tenant_subscription")
            .where(AuditLog.target_id == str(subscription_id))
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(20)
        )
        for existing_metadata in result.scalars().all():
            if (existing_metadata or {}).get("period_ends_at") == period_key:
                return False
        session.add(
            self._new_lifecycle_audit(
                tenant_id=tenant_id,
                subscription_id=subscription_id,
                action=action,
                metadata=metadata,
            )
        )
        return True

    @staticmethod
    def _new_lifecycle_audit(
        *,
        tenant_id: int,
        subscription_id: int,
        action: str,
        metadata: dict[str, object],
    ) -> AuditLog:
        return AuditLog(
            tenant_id=tenant_id,
            actor_user_id=None,
            action=action,
            target_type="tenant_subscription",
            target_id=str(subscription_id),
            metadata_json=metadata,
        )

    @staticmethod
    def _suspension_decision(now: datetime, retention_days: int) -> SubscriptionLifecycleDecision:
        return SubscriptionLifecycleDecision(
            next_status="suspended",
            suspended_at=now,
            data_retention_until=now + timedelta(days=max(retention_days, 1)),
        )

    @staticmethod
    def _new_out_trade_no() -> str:
        return "SUB" + secrets.token_urlsafe(18).replace("-", "").replace("_", "")[:24]

    @staticmethod
    def _latest_period_end(*values: Optional[datetime]) -> Optional[datetime]:
        aware_values = [aware_value for value in values if (aware_value := _ensure_aware(value)) is not None]
        if not aware_values:
            return None
        return max(aware_values)


def _ensure_aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _isoformat(value: Optional[datetime]) -> Optional[str]:
    aware_value = _ensure_aware(value)
    return aware_value.isoformat() if aware_value is not None else None
