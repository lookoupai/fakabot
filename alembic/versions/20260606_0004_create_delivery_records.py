from __future__ import annotations

"""create delivery records

Revision ID: 20260606_0004
Revises: 20260606_0003
Create Date: 2026-06-06
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260606_0004"
down_revision: Optional[str] = "20260606_0003"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.create_table(
        "delivery_records",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("order_id", sa.BigInteger(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("buyer_telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("delivery_type", sa.String(length=32), nullable=False),
        sa.Column("inventory_item_id", sa.BigInteger(), sa.ForeignKey("inventory_items.id"), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("order_id", name="uq_delivery_records_order_id"),
    )
    op.create_index("ix_delivery_records_tenant_status", "delivery_records", ["tenant_id", "status"])
    op.create_index(
        "ix_delivery_records_buyer_created_at",
        "delivery_records",
        ["buyer_telegram_user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_delivery_records_buyer_created_at", table_name="delivery_records")
    op.drop_index("ix_delivery_records_tenant_status", table_name="delivery_records")
    op.drop_table("delivery_records")
