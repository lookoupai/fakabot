from __future__ import annotations

"""create subscription tables

Revision ID: 20260606_0014
Revises: 20260606_0013
Create Date: 2026-06-06
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260606_0014"
down_revision: Optional[str] = "20260606_0013"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.create_table(
        "subscription_plans",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False, unique=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("monthly_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False, server_default="USDT"),
        sa.Column("trial_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("grace_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_subscription_plans_enabled", "subscription_plans", ["enabled"])

    op.create_table(
        "tenant_subscriptions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("plan_id", sa.BigInteger(), sa.ForeignKey("subscription_plans.id"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="trial"),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grace_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", name="uq_tenant_subscriptions_tenant_id"),
    )
    op.create_index(
        "ix_tenant_subscriptions_status_period_end",
        "tenant_subscriptions",
        ["status", "current_period_ends_at"],
    )

    op.create_table(
        "subscription_invoices",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("subscription_id", sa.BigInteger(), sa.ForeignKey("tenant_subscriptions.id"), nullable=False),
        sa.Column("amount", sa.Numeric(20, 8), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False, server_default="USDT"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("out_trade_no", sa.String(length=96), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("out_trade_no", name="uq_subscription_invoices_out_trade_no"),
    )
    op.create_index(
        "ix_subscription_invoices_tenant_status_created_at",
        "subscription_invoices",
        ["tenant_id", "status", "created_at"],
    )

    op.execute(
        sa.text(
            """
            INSERT INTO subscription_plans (code, name, monthly_price, currency, trial_days, grace_days, enabled, created_at, updated_at)
            VALUES ('default_monthly', '默认月付套餐', 10, 'USDT', 30, 0, true, now(), now())
            ON CONFLICT (code) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_subscription_invoices_tenant_status_created_at", table_name="subscription_invoices")
    op.drop_table("subscription_invoices")
    op.drop_index("ix_tenant_subscriptions_status_period_end", table_name="tenant_subscriptions")
    op.drop_table("tenant_subscriptions")
    op.drop_index("ix_subscription_plans_enabled", table_name="subscription_plans")
    op.drop_table("subscription_plans")
