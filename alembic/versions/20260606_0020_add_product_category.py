from __future__ import annotations

"""add product category

Revision ID: 20260606_0020
Revises: 20260606_0019
Create Date: 2026-06-06
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260606_0020"
down_revision: Optional[str] = "20260606_0019"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("category", sa.String(length=128), nullable=True))
    op.create_index(
        "ix_products_tenant_category_sort",
        "products",
        ["tenant_id", "category", "sort_order"],
    )


def downgrade() -> None:
    op.drop_index("ix_products_tenant_category_sort", table_name="products")
    op.drop_column("products", "category")
