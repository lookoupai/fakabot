from __future__ import annotations

"""create order payment

Revision ID: 20260606_0003
Revises: 20260606_0002
Create Date: 2026-06-06
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260606_0003"
down_revision: Optional[str] = "20260606_0002"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("buyer_telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False, server_default="self"),
        sa.Column("self_product_id", sa.BigInteger(), sa.ForeignKey("products.id"), nullable=True),
        sa.Column("product_variant_id", sa.BigInteger(), sa.ForeignKey("product_variants.id"), nullable=True),
        sa.Column("locked_inventory_item_id", sa.BigInteger(), sa.ForeignKey("inventory_items.id"), nullable=True),
        sa.Column("reseller_product_id", sa.BigInteger(), nullable=True),
        sa.Column("supplier_tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("amount", sa.Numeric(20, 8), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False, server_default="USDT"),
        sa.Column("display_amount", sa.Numeric(20, 8), nullable=True),
        sa.Column("display_currency", sa.String(length=16), nullable=True),
        sa.Column("fx_rate_snapshot", sa.Numeric(20, 8), nullable=True),
        sa.Column("payment_mode", sa.String(length=32), nullable=False),
        sa.Column("payment_provider", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("out_trade_no", sa.String(length=96), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settlement_available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_orders_tenant_status_created_at", "orders", ["tenant_id", "status", "created_at"])
    op.create_index("ix_orders_buyer_created_at", "orders", ["buyer_telegram_user_id", "created_at"])
    op.create_index("ix_orders_supplier_tenant_id", "orders", ["supplier_tenant_id"])
    op.create_index("ix_orders_expires_at", "orders", ["expires_at"])

    op.create_table(
        "payments",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("order_id", sa.BigInteger(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_trade_no", sa.String(length=128), nullable=True),
        sa.Column("amount", sa.Numeric(20, 8), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("payment_url", sa.Text(), nullable=True),
        sa.Column("raw_request_hash", sa.String(length=64), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("provider", "provider_trade_no", name="uq_payments_provider_trade_no"),
    )
    op.create_index("ix_payments_order_id", "payments", ["order_id"])
    op.create_index("ix_payments_tenant_status", "payments", ["tenant_id", "status"])

    op.create_table(
        "payment_callbacks",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("out_trade_no", sa.String(length=96), nullable=False),
        sa.Column("provider_trade_no", sa.String(length=128), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False),
        sa.Column("process_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("provider", "payload_hash", name="uq_payment_callbacks_provider_payload_hash"),
    )
    op.create_index("ix_payment_callbacks_out_trade_no", "payment_callbacks", ["out_trade_no"])
    op.create_index("ix_payment_callbacks_process_status", "payment_callbacks", ["process_status"])

    op.create_table(
        "payment_provider_configs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("config_encrypted", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "scope_type",
            "tenant_id",
            "provider",
            name="uq_payment_provider_configs_scope_tenant_provider",
        ),
    )


def downgrade() -> None:
    op.drop_table("payment_provider_configs")
    op.drop_index("ix_payment_callbacks_process_status", table_name="payment_callbacks")
    op.drop_index("ix_payment_callbacks_out_trade_no", table_name="payment_callbacks")
    op.drop_table("payment_callbacks")
    op.drop_index("ix_payments_tenant_status", table_name="payments")
    op.drop_index("ix_payments_order_id", table_name="payments")
    op.drop_table("payments")
    op.drop_index("ix_orders_expires_at", table_name="orders")
    op.drop_index("ix_orders_supplier_tenant_id", table_name="orders")
    op.drop_index("ix_orders_buyer_created_at", table_name="orders")
    op.drop_index("ix_orders_tenant_status_created_at", table_name="orders")
    op.drop_table("orders")
