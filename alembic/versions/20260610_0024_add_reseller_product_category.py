from __future__ import annotations

"""add reseller product category

Revision ID: 20260610_0024
Revises: 20260609_0023
Create Date: 2026-06-10
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260610_0024"
down_revision: Optional[str] = "20260609_0023"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.add_column("reseller_products", sa.Column("category", sa.String(length=128), nullable=True))
    op.create_index(
        "ix_reseller_products_reseller_category_sort",
        "reseller_products",
        ["reseller_tenant_id", "category", "sort_order"],
    )


def downgrade() -> None:
    op.drop_index("ix_reseller_products_reseller_category_sort", table_name="reseller_products")
    op.drop_column("reseller_products", "category")
