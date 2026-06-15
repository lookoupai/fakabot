from __future__ import annotations

"""add tenant api key scopes

Revision ID: 20260606_0015
Revises: 20260606_0014
Create Date: 2026-06-06
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260606_0015"
down_revision: Optional[str] = "20260606_0014"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.add_column(
        "tenant_api_keys",
        sa.Column(
            "scopes_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[\"tenant_admin:*\"]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tenant_api_keys", "scopes_json")
