from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.tenants import AuditLog, Tenant, TenantApiKey

ACTIVE_TENANT_STATUSES = ("trial", "active", "grace")
DEFAULT_API_KEY_SCOPES = ("tenant_admin:*",)
SUPPORTED_API_KEY_SCOPES = {
    "tenant_admin:*",
    "api_keys:read",
    "api_keys:write",
    "audit_logs:read",
    "products:read",
    "products:write",
    "external_sources:read",
    "external_sources:write",
    "finance:read",
    "finance:write",
    "inventory:read",
    "inventory:write",
    "orders:read",
    "payments:read",
    "payments:write",
    "reports:read",
    "reports:write",
    "risk:read",
    "subscriptions:read",
    "subscriptions:write",
    "supply:read",
    "supply:write",
}


@dataclass(frozen=True)
class CreatedTenantApiKey:
    api_key_id: int
    name: str
    key_prefix: str
    plain_key: str
    status: str
    scopes: List[str]
    ip_allowlist: List[str]


@dataclass(frozen=True)
class TenantApiKeySummary:
    api_key_id: int
    name: str
    key_prefix: str
    status: str
    scopes: List[str]
    ip_allowlist: List[str]
    created_at: datetime
    last_used_at: Optional[datetime]


class ApiKeyService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def create_tenant_api_key(
        self,
        session: AsyncSession,
        tenant_id: int,
        name: str,
        created_by_user_id: Optional[int],
        scopes: Optional[List[str]] = None,
        ip_allowlist: Optional[Iterable[str]] = None,
    ) -> CreatedTenantApiKey:
        normalized_name = name.strip()
        if not 1 <= len(normalized_name) <= 128:
            raise ValueError("API Key 名称长度应为 1-128 个字符")
        normalized_scopes = self.normalize_scopes(scopes)
        normalized_ip_allowlist = self.normalize_ip_allowlist(ip_allowlist)
        plain_key = "fk_live_" + secrets.token_urlsafe(32)
        key_prefix = plain_key[:12]
        api_key = TenantApiKey(
            tenant_id=tenant_id,
            name=normalized_name,
            key_prefix=key_prefix,
            key_hash=self._hash_key(plain_key),
            status="active",
            scopes_json=normalized_scopes,
            ip_allowlist_json=normalized_ip_allowlist,
            created_by_user_id=created_by_user_id,
        )
        session.add(api_key)
        await session.flush()
        session.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_user_id=created_by_user_id,
                action="tenant_api_key.created",
                target_type="tenant_api_key",
                target_id=str(api_key.id),
                metadata_json={
                    "name": normalized_name,
                    "key_prefix": key_prefix,
                    "scopes": normalized_scopes,
                    "ip_allowlist": normalized_ip_allowlist,
                },
            )
        )
        await session.flush()
        return CreatedTenantApiKey(
            api_key_id=api_key.id,
            name=api_key.name,
            key_prefix=api_key.key_prefix,
            plain_key=plain_key,
            status=api_key.status,
            scopes=list(api_key.scopes_json or DEFAULT_API_KEY_SCOPES),
            ip_allowlist=list(api_key.ip_allowlist_json or []),
        )

    async def list_tenant_api_keys(
        self,
        session: AsyncSession,
        tenant_id: int,
        limit: int = 20,
    ) -> List[TenantApiKeySummary]:
        result = await session.execute(
            select(TenantApiKey)
            .where(TenantApiKey.tenant_id == tenant_id)
            .order_by(TenantApiKey.created_at.desc())
            .limit(min(max(limit, 1), 100))
        )
        return [
            TenantApiKeySummary(
                api_key_id=api_key.id,
                name=api_key.name,
                key_prefix=api_key.key_prefix,
                status=api_key.status,
                scopes=list(api_key.scopes_json or DEFAULT_API_KEY_SCOPES),
                ip_allowlist=list(api_key.ip_allowlist_json or []),
                created_at=api_key.created_at,
                last_used_at=api_key.last_used_at,
            )
            for api_key in result.scalars().all()
        ]

    async def revoke_tenant_api_key(
        self,
        session: AsyncSession,
        tenant_id: int,
        api_key_id: int,
        revoked_by_user_id: Optional[int],
    ) -> bool:
        api_key = await session.get(TenantApiKey, api_key_id)
        if api_key is None or api_key.tenant_id != tenant_id:
            return False
        if api_key.status == "revoked":
            return True
        api_key.status = "revoked"
        session.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_user_id=revoked_by_user_id,
                action="tenant_api_key.revoked",
                target_type="tenant_api_key",
                target_id=str(api_key.id),
                metadata_json={
                    "name": api_key.name,
                    "key_prefix": api_key.key_prefix,
                    "scopes": list(api_key.scopes_json or DEFAULT_API_KEY_SCOPES),
                    "ip_allowlist": list(api_key.ip_allowlist_json or []),
                },
            )
        )
        await session.flush()
        return True

    async def authenticate(self, session: AsyncSession, plain_key: str) -> Optional[TenantApiKey]:
        key_hash = self._hash_key(plain_key.strip())
        result = await session.execute(
            select(TenantApiKey)
            .join(Tenant, Tenant.id == TenantApiKey.tenant_id)
            .where(TenantApiKey.key_hash == key_hash)
            .where(TenantApiKey.status == "active")
            .where(Tenant.status.in_(ACTIVE_TENANT_STATUSES))
            .limit(1)
        )
        api_key = result.scalar_one_or_none()
        if api_key is None:
            return None
        api_key.last_used_at = datetime.now(timezone.utc)
        await session.flush()
        return api_key

    @classmethod
    def normalize_scopes(cls, scopes: Optional[List[str]]) -> List[str]:
        if not scopes:
            return list(DEFAULT_API_KEY_SCOPES)
        normalized = sorted({scope.strip() for scope in scopes if scope and scope.strip()})
        if not normalized:
            return list(DEFAULT_API_KEY_SCOPES)
        unsupported = [scope for scope in normalized if scope not in SUPPORTED_API_KEY_SCOPES]
        if unsupported:
            raise ValueError(f"API Key scope 不支持：{', '.join(unsupported)}")
        if "tenant_admin:*" in normalized and len(normalized) > 1:
            raise ValueError("通配 scope tenant_admin:* 不能和其他 scope 同时使用")
        return normalized

    @staticmethod
    def has_scope(scopes: Optional[List[str]], required_scope: str) -> bool:
        normalized_scopes = scopes or list(DEFAULT_API_KEY_SCOPES)
        return "tenant_admin:*" in normalized_scopes or required_scope in normalized_scopes

    @classmethod
    def can_issue_scopes(cls, issuer_scopes: Optional[List[str]], requested_scopes: Optional[List[str]]) -> bool:
        normalized_requested = cls.normalize_scopes(requested_scopes)
        return all(cls.has_scope(issuer_scopes, scope) for scope in normalized_requested)

    @classmethod
    def can_issue_ip_allowlist(
        cls,
        issuer_rules: Optional[Iterable[str]],
        requested_rules: Optional[Iterable[str]],
    ) -> bool:
        normalized_issuer = cls.normalize_ip_allowlist(issuer_rules)
        normalized_requested = cls.normalize_ip_allowlist(requested_rules)
        if not normalized_issuer:
            return True
        if not normalized_requested:
            return False
        issuer_networks = [ipaddress.ip_network(rule, strict=False) for rule in normalized_issuer]
        requested_networks = [ipaddress.ip_network(rule, strict=False) for rule in normalized_requested]
        for requested in requested_networks:
            if not any(
                requested.version == issuer.version and requested.subnet_of(issuer)
                for issuer in issuer_networks
            ):
                return False
        return True

    @staticmethod
    def normalize_ip_allowlist(rules: Optional[Iterable[str]]) -> List[str]:
        if not rules:
            return []
        normalized: List[str] = []
        seen: set[str] = set()
        for rule in rules:
            value = str(rule).strip()
            if not value or value in seen:
                continue
            try:
                ipaddress.ip_network(value, strict=False)
            except ValueError as exc:
                raise ValueError("API Key IP 白名单必须是合法 IP 或 CIDR") from exc
            normalized.append(value)
            seen.add(value)
        return normalized

    def _hash_key(self, plain_key: str) -> str:
        if self._settings.token_encryption_key is None:
            raise RuntimeError("缺少 TOKEN_ENCRYPTION_KEY，不能使用租户 API Key")
        secret = self._settings.token_encryption_key.get_secret_value().encode()
        return hmac.new(secret, plain_key.encode(), hashlib.sha256).hexdigest()
