from __future__ import annotations

"""create tenant core

Revision ID: 20260606_0001
Revises:
Create Date: 2026-06-06
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260606_0001"
down_revision: Optional[str] = None
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.create_table(
        "platform_users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("first_name", sa.String(length=128), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=False, server_default="zh"),
        sa.Column("is_platform_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_banned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_platform_users_is_platform_admin", "platform_users", ["is_platform_admin"])
    op.create_index("ix_platform_users_is_banned", "platform_users", ["is_banned"])

    op.create_table(
        "tenants",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("public_id", sa.String(length=32), nullable=False, unique=True),
        sa.Column("owner_user_id", sa.BigInteger(), sa.ForeignKey("platform_users.id"), nullable=False),
        sa.Column("source_tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="trial"),
        sa.Column("store_name", sa.String(length=128), nullable=False),
        sa.Column("plan_code", sa.String(length=64), nullable=True),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("subscription_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("clone_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("self_sale_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("supplier_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reseller_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("data_retention_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_tenants_owner_user_id", "tenants", ["owner_user_id"])
    op.create_index("ix_tenants_source_tenant_id", "tenants", ["source_tenant_id"])
    op.create_index("ix_tenants_status", "tenants", ["status"])
    op.create_index("ix_tenants_subscription_ends_at", "tenants", ["subscription_ends_at"])

    op.create_table(
        "tenant_bots",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("bot_user_id", sa.BigInteger(), nullable=False),
        sa.Column("bot_username", sa.String(length=64), nullable=False),
        sa.Column("encrypted_token", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False, unique=True),
        sa.Column("webhook_secret", sa.String(length=128), nullable=False, unique=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_health_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_tenant_bots_tenant_id", "tenant_bots", ["tenant_id"])
    op.create_index("ix_tenant_bots_status", "tenant_bots", ["status"])

    op.create_table(
        "tenant_settings",
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("value_json", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "key", name="uq_tenant_settings_tenant_key"),
    )

    op.create_table(
        "tenant_members",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("platform_users.id"), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_by_user_id", sa.BigInteger(), sa.ForeignKey("platform_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_tenant_members_tenant_user"),
    )
    op.create_index("ix_tenant_members_tenant_id", "tenant_members", ["tenant_id"])

    op.create_table(
        "tenant_role_permissions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("permission", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "role", "permission", name="uq_tenant_role_permissions_role_permission"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("actor_user_id", sa.BigInteger(), sa.ForeignKey("platform_users.id"), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"])
    op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_actor_user_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_tenant_id", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("tenant_role_permissions")
    op.drop_index("ix_tenant_members_tenant_id", table_name="tenant_members")
    op.drop_table("tenant_members")
    op.drop_table("tenant_settings")
    op.drop_index("ix_tenant_bots_status", table_name="tenant_bots")
    op.drop_index("ix_tenant_bots_tenant_id", table_name="tenant_bots")
    op.drop_table("tenant_bots")
    op.drop_index("ix_tenants_subscription_ends_at", table_name="tenants")
    op.drop_index("ix_tenants_status", table_name="tenants")
    op.drop_index("ix_tenants_source_tenant_id", table_name="tenants")
    op.drop_index("ix_tenants_owner_user_id", table_name="tenants")
    op.drop_table("tenants")
    op.drop_index("ix_platform_users_is_banned", table_name="platform_users")
    op.drop_index("ix_platform_users_is_platform_admin", table_name="platform_users")
    op.drop_table("platform_users")
