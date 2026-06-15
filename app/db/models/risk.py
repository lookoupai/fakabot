from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class Dispute(TimestampMixin, Base):
    __tablename__ = "disputes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    buyer_telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    reason: Mapped[Optional[str]] = mapped_column(Text)
    resolution: Mapped[Optional[str]] = mapped_column(Text)


class AfterSaleCase(TimestampMixin, Base):
    __tablename__ = "after_sale_cases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    buyer_telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    case_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    requested_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8))
    refunded_amount: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=0)
    refund_id: Mapped[Optional[int]] = mapped_column(ForeignKey("refunds.id"))
    reason: Mapped[Optional[str]] = mapped_column(Text)
    resolution: Mapped[Optional[str]] = mapped_column(Text)


Index("ix_disputes_tenant_status_created_at", Dispute.tenant_id, Dispute.status, Dispute.created_at)
Index("ix_disputes_order_id", Dispute.order_id)
Index("ix_disputes_buyer_telegram_user_id", Dispute.buyer_telegram_user_id)
Index("ix_after_sale_cases_tenant_status_created_at", AfterSaleCase.tenant_id, AfterSaleCase.status, AfterSaleCase.created_at)
Index("ix_after_sale_cases_order_id", AfterSaleCase.order_id)
Index("ix_after_sale_cases_buyer_telegram_user_id", AfterSaleCase.buyer_telegram_user_id)
