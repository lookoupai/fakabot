from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class PlatformUser(TimestampMixin, Base):
    __tablename__ = "platform_users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(64))
    first_name: Mapped[Optional[str]] = mapped_column(String(128))
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="zh")
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Tenant(TimestampMixin, Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("platform_users.id"), nullable=False)
    source_tenant_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tenants.id"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="trial")
    store_name: Mapped[str] = mapped_column(String(128), nullable=False)
    plan_code: Mapped[Optional[str]] = mapped_column(String(64))
    trial_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    subscription_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    clone_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    self_sale_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    supplier_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reseller_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    suspended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    data_retention_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    owner: Mapped[PlatformUser] = relationship()


class TenantBot(TimestampMixin, Base):
    __tablename__ = "tenant_bots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    bot_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bot_username: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    webhook_secret: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    last_health_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    tenant: Mapped[Tenant] = relationship()


class TenantSetting(Base):
    __tablename__ = "tenant_settings"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_tenant_settings_tenant_key"),)

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value_json: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TenantMember(TimestampMixin, Base):
    __tablename__ = "tenant_members"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_tenant_members_tenant_user"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("platform_users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("platform_users.id"))


class TenantRolePermission(TimestampMixin, Base):
    __tablename__ = "tenant_role_permissions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "role", "permission", name="uq_tenant_role_permissions_role_permission"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    permission: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class TenantApiKey(TimestampMixin, Base):
    __tablename__ = "tenant_api_keys"
    __table_args__ = (
        UniqueConstraint("key_hash", name="uq_tenant_api_keys_key_hash"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    scopes_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=lambda: ["tenant_admin:*"])
    ip_allowlist_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("platform_users.id"))
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tenants.id"))
    actor_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("platform_users.id"))
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    target_type: Mapped[Optional[str]] = mapped_column(String(64))
    target_id: Mapped[Optional[str]] = mapped_column(String(64))
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


Index("ix_platform_users_is_platform_admin", PlatformUser.is_platform_admin)
Index("ix_platform_users_is_banned", PlatformUser.is_banned)
Index("ix_tenants_owner_user_id", Tenant.owner_user_id)
Index("ix_tenants_source_tenant_id", Tenant.source_tenant_id)
Index("ix_tenants_status", Tenant.status)
Index("ix_tenants_subscription_ends_at", Tenant.subscription_ends_at)
Index("ix_tenant_bots_tenant_id", TenantBot.tenant_id)
Index("ix_tenant_bots_status", TenantBot.status)
Index("ix_tenant_members_tenant_id", TenantMember.tenant_id)
Index("ix_tenant_api_keys_tenant_status", TenantApiKey.tenant_id, TenantApiKey.status)
Index("ix_audit_logs_tenant_id", AuditLog.tenant_id)
Index("ix_audit_logs_actor_user_id", AuditLog.actor_user_id)
