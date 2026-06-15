from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class LedgerAccount(TimestampMixin, Base):
    __tablename__ = "ledger_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "account_type", "currency", name="uq_ledger_accounts_tenant_type_currency"),
        CheckConstraint("pending_balance >= 0", name="ck_ledger_accounts_pending_nonnegative"),
        CheckConstraint("frozen_balance >= 0", name="ck_ledger_accounts_frozen_nonnegative"),
        CheckConstraint("account_type <> ''", name="ck_ledger_accounts_account_type_not_empty"),
        CheckConstraint("currency <> ''", name="ck_ledger_accounts_currency_not_empty"),
        CheckConstraint("status <> ''", name="ck_ledger_accounts_status_not_empty"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    account_type: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False, default="USDT")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    pending_balance: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=0)
    available_balance: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=0)
    frozen_balance: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=0)


class SettlementPolicy(TimestampMixin, Base):
    __tablename__ = "settlement_policies"
    __table_args__ = (
        UniqueConstraint("scope_type", "tenant_id", name="uq_settlement_policies_scope_tenant"),
        CheckConstraint("scope_type IN ('platform', 'tenant')", name="ck_settlement_policies_scope_type"),
        CheckConstraint("freeze_days >= 0", name="ck_settlement_policies_freeze_days_nonnegative"),
        CheckConstraint(
            "platform_fee_percent >= 0 AND platform_fee_percent <= 100",
            name="ck_settlement_policies_platform_fee_percent_range",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    tenant_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tenants.id"))
    freeze_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    platform_fee_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    platform_fee_percent: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=1)


class WithdrawalRequest(TimestampMixin, Base):
    __tablename__ = "withdrawal_requests"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_withdrawal_requests_amount_positive"),
        CheckConstraint("currency <> ''", name="ck_withdrawal_requests_currency_not_empty"),
        CheckConstraint("network <> ''", name="ck_withdrawal_requests_network_not_empty"),
        CheckConstraint("status IN ('pending', 'completed', 'rejected')", name="ck_withdrawal_requests_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False, default="USDT")
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    network: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    admin_note: Mapped[Optional[str]] = mapped_column(Text)
    payout_reference: Mapped[Optional[str]] = mapped_column(String(128))
    payout_proof_url: Mapped[Optional[str]] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_ledger_entries_amount_positive"),
        CheckConstraint("direction IN ('credit', 'debit')", name="ck_ledger_entries_direction"),
        CheckConstraint("entry_type <> ''", name="ck_ledger_entries_entry_type_not_empty"),
        CheckConstraint("currency <> ''", name="ck_ledger_entries_currency_not_empty"),
        CheckConstraint("status <> ''", name="ck_ledger_entries_status_not_empty"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("ledger_accounts.id"), nullable=False)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orders.id"))
    withdrawal_id: Mapped[Optional[int]] = mapped_column(ForeignKey("withdrawal_requests.id"))
    entry_type: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False, default="USDT")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    available_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Refund(TimestampMixin, Base):
    __tablename__ = "refunds"
    __table_args__ = (
        UniqueConstraint("order_id", "idempotency_key", name="uq_refunds_order_idempotency_key"),
        CheckConstraint("amount > 0", name="ck_refunds_amount_positive"),
        CheckConstraint("currency <> ''", name="ck_refunds_currency_not_empty"),
        CheckConstraint("status IN ('pending', 'completed', 'failed')", name="ck_refunds_status"),
        CheckConstraint("idempotency_key <> ''", name="ck_refunds_idempotency_key_not_empty"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False, default="USDT")
    reason: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


Index("ix_ledger_accounts_tenant_id", LedgerAccount.tenant_id)
Index(
    "uq_settlement_policies_platform_scope",
    SettlementPolicy.scope_type,
    unique=True,
    postgresql_where=(SettlementPolicy.scope_type == "platform") & SettlementPolicy.tenant_id.is_(None),
)
Index("ix_ledger_entries_tenant_status", LedgerEntry.tenant_id, LedgerEntry.status)
Index("ix_ledger_entries_order_id", LedgerEntry.order_id)
Index("ix_ledger_entries_withdrawal_id", LedgerEntry.withdrawal_id)
Index("ix_ledger_entries_available_at", LedgerEntry.available_at)
Index("ix_withdrawal_requests_tenant_status", WithdrawalRequest.tenant_id, WithdrawalRequest.status)
Index("ix_withdrawal_requests_requested_at", WithdrawalRequest.requested_at)
Index("ix_refunds_tenant_status", Refund.tenant_id, Refund.status)
Index("ix_refunds_order_id", Refund.order_id)
