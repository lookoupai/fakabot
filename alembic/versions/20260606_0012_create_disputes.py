from __future__ import annotations

"""create disputes

Revision ID: 20260606_0012
Revises: 20260606_0011
Create Date: 2026-06-06
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260606_0012"
down_revision: Optional[str] = "20260606_0011"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.create_table(
        "disputes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("order_id", sa.BigInteger(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("buyer_telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_disputes_tenant_status_created_at",
        "disputes",
        ["tenant_id", "status", "created_at"],
    )
    op.create_index("ix_disputes_order_id", "disputes", ["order_id"])
    op.create_index("ix_disputes_buyer_telegram_user_id", "disputes", ["buyer_telegram_user_id"])
    op.create_table(
        "after_sale_cases",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("order_id", sa.BigInteger(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("buyer_telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("case_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("requested_amount", sa.Numeric(20, 8), nullable=True),
        sa.Column("refunded_amount", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("refund_id", sa.BigInteger(), sa.ForeignKey("refunds.id"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_after_sale_cases_tenant_status_created_at",
        "after_sale_cases",
        ["tenant_id", "status", "created_at"],
    )
    op.create_index("ix_after_sale_cases_order_id", "after_sale_cases", ["order_id"])
    op.create_index(
        "ix_after_sale_cases_buyer_telegram_user_id",
        "after_sale_cases",
        ["buyer_telegram_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_after_sale_cases_buyer_telegram_user_id", table_name="after_sale_cases")
    op.drop_index("ix_after_sale_cases_order_id", table_name="after_sale_cases")
    op.drop_index("ix_after_sale_cases_tenant_status_created_at", table_name="after_sale_cases")
    op.drop_table("after_sale_cases")
    op.drop_index("ix_disputes_buyer_telegram_user_id", table_name="disputes")
    op.drop_index("ix_disputes_order_id", table_name="disputes")
    op.drop_index("ix_disputes_tenant_status_created_at", table_name="disputes")
    op.drop_table("disputes")
