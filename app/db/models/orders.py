from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


TRC20_DIRECT_TRANSFER_MATCH_STATUSES = (
    'recorded',
    'not_confirmed',
    'duplicate_tx',
    'no_candidate',
    'address_mismatch',
    'amount_mismatch',
    'outside_time_window',
    'ambiguous',
    'matched',
    'invalid',
)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class Order(TimestampMixin, Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    buyer_telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="self")
    self_product_id: Mapped[Optional[int]] = mapped_column(ForeignKey("products.id"))
    subscription_months: Mapped[Optional[int]] = mapped_column(Integer)
    product_variant_id: Mapped[Optional[int]] = mapped_column(ForeignKey("product_variants.id"))
    locked_inventory_item_id: Mapped[Optional[int]] = mapped_column(ForeignKey("inventory_items.id"))
    reseller_product_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    supplier_tenant_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tenants.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False, default="USDT")
    display_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8))
    display_currency: Mapped[Optional[str]] = mapped_column(String(16))
    fx_rate_snapshot: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8))
    supplier_settlement_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8))
    reseller_settlement_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8))
    payment_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    payment_provider: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    out_trade_no: Mapped[str] = mapped_column(String(96), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    settlement_available_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_trade_no: Mapped[Optional[str]] = mapped_column(String(128))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    available_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    payment_url: Mapped[Optional[str]] = mapped_column(Text)
    raw_request_hash: Mapped[Optional[str]] = mapped_column(String(64))
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class PaymentCallback(Base):
    __tablename__ = "payment_callbacks"
    __table_args__ = (UniqueConstraint("provider", "payload_hash", name="uq_payment_callbacks_provider_payload_hash"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    out_trade_no: Mapped[str] = mapped_column(String(96), nullable=False)
    provider_trade_no: Mapped[Optional[str]] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    process_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Trc20DirectTransfer(TimestampMixin, Base):
    __tablename__ = "trc20_direct_transfers"
    __table_args__ = (
        UniqueConstraint("tx_hash", name="uq_trc20_direct_transfers_tx_hash"),
        CheckConstraint(
            "match_status IN ('recorded', 'not_confirmed', 'duplicate_tx', 'no_candidate', "
            "'address_mismatch', 'amount_mismatch', 'outside_time_window', 'ambiguous', 'matched', 'invalid')",
            name="ck_trc20_direct_transfers_match_status",
        ),
        CheckConstraint("raw_amount > 0", name="ck_trc20_direct_transfers_raw_amount_positive"),
        CheckConstraint("amount > 0", name="ck_trc20_direct_transfers_amount_positive"),
        CheckConstraint("confirmations >= 0", name="ck_trc20_direct_transfers_confirmations_nonnegative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orders.id"))
    payment_id: Mapped[Optional[int]] = mapped_column(ForeignKey("payments.id"))
    out_trade_no: Mapped[Optional[str]] = mapped_column(String(96))
    tx_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    timestamp_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    block_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    from_address: Mapped[str] = mapped_column(String(64), nullable=False)
    to_address: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_address: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    confirmations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    match_status: Mapped[str] = mapped_column(String(32), nullable=False, default="recorded")
    matched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[Optional[str]] = mapped_column(String(128))


class PaymentProviderConfig(TimestampMixin, Base):
    __tablename__ = "payment_provider_configs"
    __table_args__ = (
        UniqueConstraint("scope_type", "tenant_id", "provider", name="uq_payment_provider_configs_scope_tenant_provider"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    tenant_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tenants.id"))
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    config_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class DeliveryRecord(TimestampMixin, Base):
    __tablename__ = "delivery_records"
    __table_args__ = (UniqueConstraint("order_id", name="uq_delivery_records_order_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    buyer_telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    delivery_type: Mapped[str] = mapped_column(String(32), nullable=False)
    inventory_item_id: Mapped[Optional[int]] = mapped_column(ForeignKey("inventory_items.id"))
    uploaded_file_id: Mapped[Optional[int]] = mapped_column(ForeignKey("uploaded_files.id"))
    telegram_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


Index("ix_orders_tenant_status_created_at", Order.tenant_id, Order.status, Order.created_at)
Index("ix_orders_buyer_created_at", Order.buyer_telegram_user_id, Order.created_at)
Index("ix_orders_supplier_tenant_id", Order.supplier_tenant_id)
Index("ix_orders_expires_at", Order.expires_at)
Index("ix_payments_order_id", Payment.order_id)
Index("ix_payments_tenant_status", Payment.tenant_id, Payment.status)
Index("ix_payment_callbacks_out_trade_no", PaymentCallback.out_trade_no)
Index("ix_payment_callbacks_process_status", PaymentCallback.process_status)
Index("ix_trc20_direct_transfers_tenant_match_status", Trc20DirectTransfer.tenant_id, Trc20DirectTransfer.match_status)
Index("ix_trc20_direct_transfers_tenant_order", Trc20DirectTransfer.tenant_id, Trc20DirectTransfer.order_id)
Index("ix_trc20_direct_transfers_tenant_payment", Trc20DirectTransfer.tenant_id, Trc20DirectTransfer.payment_id)
Index("ix_trc20_direct_transfers_to_address_status", Trc20DirectTransfer.to_address, Trc20DirectTransfer.match_status)
Index("ix_delivery_records_tenant_status", DeliveryRecord.tenant_id, DeliveryRecord.status)
Index("ix_delivery_records_buyer_created_at", DeliveryRecord.buyer_telegram_user_id, DeliveryRecord.created_at)
Index("ix_delivery_records_uploaded_file_id", DeliveryRecord.uploaded_file_id)
Index("ix_delivery_records_telegram_chat_id", DeliveryRecord.telegram_chat_id)
