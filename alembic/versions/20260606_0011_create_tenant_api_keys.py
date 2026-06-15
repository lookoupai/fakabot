from __future__ import annotations

"""create tenant api keys

Revision ID: 20260606_0011
Revises: 20260606_0010
Create Date: 2026-06-06
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260606_0011"
down_revision: Optional[str] = "20260606_0010"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.create_table(
        "tenant_api_keys",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("key_prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_by_user_id", sa.BigInteger(), sa.ForeignKey("platform_users.id"), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("key_hash", name="uq_tenant_api_keys_key_hash"),
    )
    op.create_index("ix_tenant_api_keys_tenant_status", "tenant_api_keys", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_tenant_api_keys_tenant_status", table_name="tenant_api_keys")
    op.drop_table("tenant_api_keys")
