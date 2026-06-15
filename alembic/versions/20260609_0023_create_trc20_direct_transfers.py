from __future__ import annotations

"""create trc20 direct transfers

Revision ID: 20260609_0023
Revises: 20260609_0022
Create Date: 2026-06-09
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260609_0023"
down_revision: Optional[str] = "20260609_0022"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.create_table(
        "trc20_direct_transfers",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=True),
        sa.Column("payment_id", sa.BigInteger(), nullable=True),
        sa.Column("out_trade_no", sa.String(length=96), nullable=True),
        sa.Column("tx_hash", sa.String(length=64), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("timestamp_ms", sa.BigInteger(), nullable=False),
        sa.Column("block_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("from_address", sa.String(length=64), nullable=False),
        sa.Column("to_address", sa.String(length=64), nullable=False),
        sa.Column("contract_address", sa.String(length=64), nullable=False),
        sa.Column("raw_amount", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.Numeric(20, 8), nullable=False),
        sa.Column("confirmations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("match_status", sa.String(length=32), nullable=False, server_default="recorded"),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"]),
        sa.UniqueConstraint("tx_hash", name="uq_trc20_direct_transfers_tx_hash"),
        sa.CheckConstraint(
            "match_status IN ('recorded', 'not_confirmed', 'duplicate_tx', 'no_candidate', "
            "'address_mismatch', 'amount_mismatch', 'outside_time_window', 'ambiguous', 'matched', 'invalid')",
            name="ck_trc20_direct_transfers_match_status",
        ),
        sa.CheckConstraint("raw_amount > 0", name="ck_trc20_direct_transfers_raw_amount_positive"),
        sa.CheckConstraint("amount > 0", name="ck_trc20_direct_transfers_amount_positive"),
        sa.CheckConstraint("confirmations >= 0", name="ck_trc20_direct_transfers_confirmations_nonnegative"),
    )
    op.create_index(
        "ix_trc20_direct_transfers_tenant_match_status",
        "trc20_direct_transfers",
        ["tenant_id", "match_status"],
    )
    op.create_index(
        "ix_trc20_direct_transfers_tenant_order",
        "trc20_direct_transfers",
        ["tenant_id", "order_id"],
    )
    op.create_index(
        "ix_trc20_direct_transfers_tenant_payment",
        "trc20_direct_transfers",
        ["tenant_id", "payment_id"],
    )
    op.create_index(
        "ix_trc20_direct_transfers_to_address_status",
        "trc20_direct_transfers",
        ["to_address", "match_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_trc20_direct_transfers_to_address_status", table_name="trc20_direct_transfers")
    op.drop_index("ix_trc20_direct_transfers_tenant_payment", table_name="trc20_direct_transfers")
    op.drop_index("ix_trc20_direct_transfers_tenant_order", table_name="trc20_direct_transfers")
    op.drop_index("ix_trc20_direct_transfers_tenant_match_status", table_name="trc20_direct_transfers")
    op.drop_table("trc20_direct_transfers")
