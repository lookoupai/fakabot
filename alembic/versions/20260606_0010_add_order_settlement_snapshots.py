from __future__ import annotations

"""add order settlement snapshots

Revision ID: 20260606_0010
Revises: 20260606_0009
Create Date: 2026-06-06
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260606_0010"
down_revision: Optional[str] = "20260606_0009"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("supplier_settlement_amount", sa.Numeric(20, 8), nullable=True))
    op.add_column("orders", sa.Column("reseller_settlement_amount", sa.Numeric(20, 8), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "reseller_settlement_amount")
    op.drop_column("orders", "supplier_settlement_amount")
