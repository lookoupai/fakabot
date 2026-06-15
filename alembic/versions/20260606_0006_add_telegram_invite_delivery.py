from __future__ import annotations

"""add telegram invite delivery

Revision ID: 20260606_0006
Revises: 20260606_0005
Create Date: 2026-06-06
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260606_0006"
down_revision: Optional[str] = "20260606_0005"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True))
    op.add_column("delivery_records", sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True))
    op.create_index("ix_products_telegram_chat_id", "products", ["telegram_chat_id"])
    op.create_index("ix_delivery_records_telegram_chat_id", "delivery_records", ["telegram_chat_id"])


def downgrade() -> None:
    op.drop_index("ix_delivery_records_telegram_chat_id", table_name="delivery_records")
    op.drop_index("ix_products_telegram_chat_id", table_name="products")
    op.drop_column("delivery_records", "telegram_chat_id")
    op.drop_column("products", "telegram_chat_id")
