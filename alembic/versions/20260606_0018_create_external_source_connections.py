from __future__ import annotations

"""create external source connections

Revision ID: 20260606_0018
Revises: 20260606_0017
Create Date: 2026-06-06
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260606_0018"
down_revision: Optional[str] = "20260606_0017"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.create_table(
        "external_source_connections",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("source_key", sa.String(length=128), server_default="", nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("credentials_encrypted", sa.Text(), nullable=False),
        sa.Column(
            "credentials_hint_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("""'{"fields":[]}'::jsonb"""),
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["platform_users.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.UniqueConstraint(
            "tenant_id",
            "provider_name",
            "source_key",
            name="uq_external_source_connections_tenant_provider_source",
        ),
    )
    op.create_index(
        "ix_external_source_connections_tenant_provider_status",
        "external_source_connections",
        ["tenant_id", "provider_name", "status"],
    )
    op.create_index(
        "ix_external_source_connections_tenant_status",
        "external_source_connections",
        ["tenant_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_external_source_connections_tenant_status", table_name="external_source_connections")
    op.drop_index("ix_external_source_connections_tenant_provider_status", table_name="external_source_connections")
    op.drop_table("external_source_connections")
