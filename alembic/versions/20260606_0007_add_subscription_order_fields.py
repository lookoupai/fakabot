from __future__ import annotations

"""add subscription order fields

Revision ID: 20260606_0007
Revises: 20260606_0006
Create Date: 2026-06-06
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260606_0007"
down_revision: Optional[str] = "20260606_0006"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("subscription_months", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "subscription_months")
