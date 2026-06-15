from __future__ import annotations

"""add tenant api key ip allowlist

Revision ID: 20260606_0016
Revises: 20260606_0015
Create Date: 2026-06-06
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260606_0016"
down_revision: Optional[str] = "20260606_0015"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.add_column(
        "tenant_api_keys",
        sa.Column(
            "ip_allowlist_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tenant_api_keys", "ip_allowlist_json")
