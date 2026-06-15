from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.tenants import TimestampMixin


class SubscriptionPlan(TimestampMixin, Base):
    __tablename__ = "subscription_plans"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    monthly_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False, default="USDT")
    trial_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    grace_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class TenantSubscription(TimestampMixin, Base):
    __tablename__ = "tenant_subscriptions"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_tenant_subscriptions_tenant_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    plan_id: Mapped[int] = mapped_column(ForeignKey("subscription_plans.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="trial")
    trial_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    current_period_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    grace_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    plan: Mapped[SubscriptionPlan] = relationship()


class SubscriptionInvoice(TimestampMixin, Base):
    __tablename__ = "subscription_invoices"
    __table_args__ = (UniqueConstraint("out_trade_no", name="uq_subscription_invoices_out_trade_no"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("tenant_subscriptions.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False, default="USDT")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    out_trade_no: Mapped[str] = mapped_column(String(96), nullable=False)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    subscription: Mapped[TenantSubscription] = relationship()


Index("ix_subscription_plans_enabled", SubscriptionPlan.enabled)
Index("ix_tenant_subscriptions_status_period_end", TenantSubscription.status, TenantSubscription.current_period_ends_at)
Index("ix_subscription_invoices_tenant_status_created_at", SubscriptionInvoice.tenant_id, SubscriptionInvoice.status, SubscriptionInvoice.created_at)
