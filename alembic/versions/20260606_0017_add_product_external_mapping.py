from __future__ import annotations

"""add product external mapping

Revision ID: 20260606_0017
Revises: 20260606_0016
Create Date: 2026-06-06
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260606_0017"
down_revision: Optional[str] = "20260606_0016"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("external_source", sa.String(length=64), nullable=True))
    op.add_column(
        "products",
        sa.Column("source_key", sa.String(length=128), server_default="", nullable=False),
    )
    op.add_column("products", sa.Column("external_id", sa.String(length=128), nullable=True))
    op.create_index(
        "uq_products_tenant_external_identity",
        "products",
        ["tenant_id", "external_source", "source_key", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_source IS NOT NULL AND external_id IS NOT NULL"),
    )
    op.create_index("ix_products_tenant_external_source", "products", ["tenant_id", "external_source"])


def downgrade() -> None:
    op.drop_index("ix_products_tenant_external_source", table_name="products")
    op.drop_index("uq_products_tenant_external_identity", table_name="products")
    op.drop_column("products", "external_id")
    op.drop_column("products", "source_key")
    op.drop_column("products", "external_source")
