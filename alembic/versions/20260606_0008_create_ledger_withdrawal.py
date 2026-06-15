from __future__ import annotations

"""create ledger withdrawal

Revision ID: 20260606_0008
Revises: 20260606_0007
Create Date: 2026-06-06
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260606_0008"
down_revision: Optional[str] = "20260606_0007"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.create_table(
        "ledger_accounts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("account_type", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False, server_default="USDT"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("pending_balance", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("available_balance", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("frozen_balance", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "account_type", "currency", name="uq_ledger_accounts_tenant_type_currency"),
    )
    op.create_index("ix_ledger_accounts_tenant_id", "ledger_accounts", ["tenant_id"])

    op.create_table(
        "settlement_policies",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("freeze_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("platform_fee_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("platform_fee_percent", sa.Numeric(8, 4), nullable=False, server_default="1.0000"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("scope_type", "tenant_id", name="uq_settlement_policies_scope_tenant"),
    )
    op.create_index(
        "uq_settlement_policies_platform_scope",
        "settlement_policies",
        ["scope_type"],
        unique=True,
        postgresql_where=sa.text("scope_type = 'platform' AND tenant_id IS NULL"),
    )

    op.create_table(
        "withdrawal_requests",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False, server_default="USDT"),
        sa.Column("amount", sa.Numeric(20, 8), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("network", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_withdrawal_requests_tenant_status", "withdrawal_requests", ["tenant_id", "status"])
    op.create_index("ix_withdrawal_requests_requested_at", "withdrawal_requests", ["requested_at"])

    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("account_id", sa.BigInteger(), sa.ForeignKey("ledger_accounts.id"), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("order_id", sa.BigInteger(), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("withdrawal_id", sa.BigInteger(), sa.ForeignKey("withdrawal_requests.id"), nullable=True),
        sa.Column("entry_type", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Numeric(20, 8), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False, server_default="USDT"),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_ledger_entries_tenant_status", "ledger_entries", ["tenant_id", "status"])
    op.create_index("ix_ledger_entries_order_id", "ledger_entries", ["order_id"])
    op.create_index("ix_ledger_entries_withdrawal_id", "ledger_entries", ["withdrawal_id"])
    op.create_index("ix_ledger_entries_available_at", "ledger_entries", ["available_at"])

    op.create_table(
        "refunds",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("order_id", sa.BigInteger(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("amount", sa.Numeric(20, 8), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False, server_default="USDT"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("order_id", "idempotency_key", name="uq_refunds_order_idempotency_key"),
    )
    op.create_index("ix_refunds_tenant_status", "refunds", ["tenant_id", "status"])
    op.create_index("ix_refunds_order_id", "refunds", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_refunds_order_id", table_name="refunds")
    op.drop_index("ix_refunds_tenant_status", table_name="refunds")
    op.drop_table("refunds")
    op.drop_index("ix_ledger_entries_available_at", table_name="ledger_entries")
    op.drop_index("ix_ledger_entries_withdrawal_id", table_name="ledger_entries")
    op.drop_index("ix_ledger_entries_order_id", table_name="ledger_entries")
    op.drop_index("ix_ledger_entries_tenant_status", table_name="ledger_entries")
    op.drop_table("ledger_entries")
    op.drop_index("ix_withdrawal_requests_requested_at", table_name="withdrawal_requests")
    op.drop_index("ix_withdrawal_requests_tenant_status", table_name="withdrawal_requests")
    op.drop_table("withdrawal_requests")
    op.drop_index("uq_settlement_policies_platform_scope", table_name="settlement_policies")
    op.drop_table("settlement_policies")
    op.drop_index("ix_ledger_accounts_tenant_id", table_name="ledger_accounts")
    op.drop_table("ledger_accounts")
