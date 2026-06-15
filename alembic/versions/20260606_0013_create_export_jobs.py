from __future__ import annotations

"""create export jobs

Revision ID: 20260606_0013
Revises: 20260606_0012
Create Date: 2026-06-06
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260606_0013"
down_revision: Optional[str] = "20260606_0012"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.create_table(
        "export_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("requested_by_user_id", sa.BigInteger(), sa.ForeignKey("platform_users.id"), nullable=True),
        sa.Column("report_type", sa.String(length=32), nullable=False),
        sa.Column("scope_type", sa.String(length=32), nullable=False, server_default="tenant"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("download_token", sa.String(length=128), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_export_jobs_tenant_status_created_at",
        "export_jobs",
        ["tenant_id", "status", "created_at"],
    )
    op.create_index(
        "ix_export_jobs_requested_by_status_created_at",
        "export_jobs",
        ["requested_by_user_id", "status", "created_at"],
    )
    op.create_index("ix_export_jobs_download_token", "export_jobs", ["download_token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_export_jobs_download_token", table_name="export_jobs")
    op.drop_index("ix_export_jobs_requested_by_status_created_at", table_name="export_jobs")
    op.drop_index("ix_export_jobs_tenant_status_created_at", table_name="export_jobs")
    op.drop_table("export_jobs")
