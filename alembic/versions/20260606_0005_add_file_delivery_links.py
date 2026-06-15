from __future__ import annotations

"""add file delivery links

Revision ID: 20260606_0005
Revises: 20260606_0004
Create Date: 2026-06-06
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260606_0005"
down_revision: Optional[str] = "20260606_0004"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("delivery_file_id", sa.BigInteger(), sa.ForeignKey("uploaded_files.id"), nullable=True),
    )
    op.add_column(
        "delivery_records",
        sa.Column("uploaded_file_id", sa.BigInteger(), sa.ForeignKey("uploaded_files.id"), nullable=True),
    )
    op.create_index("ix_products_delivery_file_id", "products", ["delivery_file_id"])
    op.create_index("ix_delivery_records_uploaded_file_id", "delivery_records", ["uploaded_file_id"])


def downgrade() -> None:
    op.drop_index("ix_delivery_records_uploaded_file_id", table_name="delivery_records")
    op.drop_index("ix_products_delivery_file_id", table_name="products")
    op.drop_column("delivery_records", "uploaded_file_id")
    op.drop_column("products", "delivery_file_id")
