from __future__ import annotations

"""create external fulfillment attempts

Revision ID: 20260606_0021
Revises: 20260606_0020
Create Date: 2026-06-06
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260606_0021"
down_revision: Optional[str] = "20260606_0020"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.create_table(
        "external_fulfillment_attempts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("connection_id", sa.BigInteger(), nullable=True),
        sa.Column("delivery_record_id", sa.BigInteger(), nullable=True),
        sa.Column("out_trade_no", sa.String(length=96), nullable=False),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("source_key", sa.String(length=128), server_default="", nullable=False),
        sa.Column("external_product_id", sa.String(length=128), nullable=False),
        sa.Column("external_order_id", sa.String(length=128), nullable=True),
        sa.Column("attempt_source", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("imported", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("item_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("failure_stage", sa.String(length=64), nullable=True),
        sa.Column("failure_category", sa.String(length=64), nullable=True),
        sa.Column("failure_retryable", sa.Boolean(), nullable=True),
        sa.Column("upstream_status_code", sa.Integer(), nullable=True),
        sa.Column("failure_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["connection_id"], ["external_source_connections.id"]),
        sa.ForeignKeyConstraint(["delivery_record_id"], ["delivery_records.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    op.create_check_constraint(
        "ck_external_fulfillment_attempts_attempt_source",
        "external_fulfillment_attempts",
        "attempt_source IN ('auto', 'manual')",
    )
    op.create_check_constraint(
        "ck_external_fulfillment_attempts_status",
        "external_fulfillment_attempts",
        "status IN ('imported', 'already_delivered', 'failed')",
    )
    op.create_check_constraint(
        "ck_external_fulfillment_attempts_item_count_nonnegative",
        "external_fulfillment_attempts",
        "item_count >= 0",
    )
    op.create_check_constraint(
        "ck_external_fulfillment_attempts_upstream_status_code",
        "external_fulfillment_attempts",
        "upstream_status_code IS NULL OR (upstream_status_code >= 100 AND upstream_status_code <= 599)",
    )
    op.create_index(
        "ix_external_fulfillment_attempts_tenant_status_created",
        "external_fulfillment_attempts",
        ["tenant_id", "status", "created_at"],
    )
    op.create_index(
        "ix_external_fulfillment_attempts_tenant_order_created",
        "external_fulfillment_attempts",
        ["tenant_id", "order_id", "created_at"],
    )
    op.create_index(
        "ix_external_fulfillment_attempts_provider_status",
        "external_fulfillment_attempts",
        ["provider_name", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_external_fulfillment_attempts_provider_status", table_name="external_fulfillment_attempts")
    op.drop_index("ix_external_fulfillment_attempts_tenant_order_created", table_name="external_fulfillment_attempts")
    op.drop_index("ix_external_fulfillment_attempts_tenant_status_created", table_name="external_fulfillment_attempts")
    op.drop_constraint(
        "ck_external_fulfillment_attempts_upstream_status_code",
        "external_fulfillment_attempts",
        type_="check",
    )
    op.drop_constraint(
        "ck_external_fulfillment_attempts_item_count_nonnegative",
        "external_fulfillment_attempts",
        type_="check",
    )
    op.drop_constraint("ck_external_fulfillment_attempts_status", "external_fulfillment_attempts", type_="check")
    op.drop_constraint(
        "ck_external_fulfillment_attempts_attempt_source",
        "external_fulfillment_attempts",
        type_="check",
    )
    op.drop_table("external_fulfillment_attempts")
