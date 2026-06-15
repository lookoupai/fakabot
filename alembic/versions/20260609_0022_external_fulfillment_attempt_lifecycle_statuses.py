from __future__ import annotations

"""external fulfillment attempt lifecycle statuses

Revision ID: 20260609_0022
Revises: 20260606_0021
Create Date: 2026-06-09
"""

from collections.abc import Sequence
from typing import Optional, Union

from alembic import op

revision: str = "20260609_0022"
down_revision: Optional[str] = "20260606_0021"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


NEW_STATUS_CHECK = "status IN ('started', 'running', 'succeeded', 'already_delivered', 'failed', 'imported')"
OLD_STATUS_CHECK = "status IN ('imported', 'already_delivered', 'failed')"


def upgrade() -> None:
    op.drop_constraint("ck_external_fulfillment_attempts_status", "external_fulfillment_attempts", type_="check")
    op.create_check_constraint(
        "ck_external_fulfillment_attempts_status",
        "external_fulfillment_attempts",
        NEW_STATUS_CHECK,
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE external_fulfillment_attempts
        SET status = CASE
            WHEN status = 'succeeded' THEN 'imported'
            WHEN status IN ('started', 'running') THEN 'failed'
            ELSE status
        END
        """
    )
    op.drop_constraint("ck_external_fulfillment_attempts_status", "external_fulfillment_attempts", type_="check")
    op.create_check_constraint(
        "ck_external_fulfillment_attempts_status",
        "external_fulfillment_attempts",
        OLD_STATUS_CHECK,
    )
