from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.external_sources import ExternalSourceConnection
from app.services.external_sources.identifiers import normalize_external_identifier
from app.services.external_sources.registry import get_provider
from app.services.token_crypto import TokenCrypto


class ExternalSourceRuntimeCredentials:
    __slots__ = (
        "connection_id",
        "tenant_id",
        "provider_name",
        "source_key",
        "_credential_fields",
        "_credentials",
    )

    def __init__(
        self,
        *,
        connection_id: int,
        tenant_id: int,
        provider_name: str,
        source_key: str,
        credential_fields: list[str],
        credentials: dict[str, str],
    ) -> None:
        self.connection_id = connection_id
        self.tenant_id = tenant_id
        self.provider_name = provider_name
        self.source_key = source_key
        self._credential_fields = list(credential_fields)
        self._credentials = dict(credentials)

    @property
    def credential_fields(self) -> list[str]:
        return list(self._credential_fields)

    @property
    def credentials(self) -> dict[str, str]:
        return dict(self._credentials)

    def __repr__(self) -> str:
        return (
            "ExternalSourceRuntimeCredentials("
            f"connection_id={self.connection_id!r}, "
            f"tenant_id={self.tenant_id!r}, "
            f"provider_name={self.provider_name!r}, "
            f"source_key={self.source_key!r}, "
            f"credential_field_count={len(self._credential_fields)!r}, "
            "credentials='***'"
            ")"
        )

    __str__ = __repr__


@dataclass(frozen=True)
class ExternalSourceConnectionSummary:
    connection_id: int
    provider_name: str
    source_key: str
    display_name: str
    status: str
    credential_fields: list[str]
    created_at: Optional[datetime]
    last_used_at: Optional[datetime]


class ExternalSourceConnectionService:
    async def list_connections(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        provider_name: Optional[str] = None,
    ) -> list[ExternalSourceConnectionSummary]:
        normalized_provider = (
            normalize_external_identifier(provider_name, "provider_name", allow_empty=False)
            if provider_name is not None
            else None
        )
        query = (
            select(ExternalSourceConnection)
            .where(ExternalSourceConnection.tenant_id == tenant_id)
            .where(ExternalSourceConnection.status != "deleted")
            .order_by(ExternalSourceConnection.provider_name.asc(), ExternalSourceConnection.source_key.asc())
        )
        if normalized_provider is not None:
            query = query.where(ExternalSourceConnection.provider_name == normalized_provider)
        result = await session.execute(query)
        return [_connection_summary(connection) for connection in result.scalars().all()]

    async def create_connection(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        provider_name: str,
        source_key: str,
        display_name: str,
        credentials: dict[str, str],
        settings: Settings,
        created_by_user_id: Optional[int] = None,
    ) -> ExternalSourceConnectionSummary:
        normalized_provider = normalize_external_identifier(provider_name, "provider_name", allow_empty=False)
        normalized_source_key = normalize_external_identifier(source_key, "source_key", allow_empty=True) or ""
        provider = get_provider(normalized_provider)
        if provider is None:
            raise ValueError("外部发卡源 provider 未注册")
        normalized_display_name = display_name.strip()
        if not 1 <= len(normalized_display_name) <= 128:
            raise ValueError("连接名称长度范围为 1-128")
        normalized_credentials = normalize_credentials(credentials)
        normalized_credentials = _validate_provider_credentials(provider, normalized_credentials)

        existing = await self._get_connection(
            session,
            tenant_id=tenant_id,
            provider_name=normalized_provider,
            source_key=normalized_source_key,
        )
        encrypted = TokenCrypto(settings).encrypt_token(
            json.dumps(normalized_credentials, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        if existing is not None:
            if existing.status != "deleted":
                raise ValueError("外部源连接已存在")
            existing.display_name = normalized_display_name
            existing.status = "active"
            existing.credentials_encrypted = encrypted
            existing.credentials_hint_json = build_credentials_hint(normalized_credentials)
            existing.created_by_user_id = created_by_user_id
            existing.last_used_at = None
            await session.flush()
            return _connection_summary(existing)

        connection = ExternalSourceConnection(
            tenant_id=tenant_id,
            provider_name=normalized_provider,
            source_key=normalized_source_key,
            display_name=normalized_display_name,
            status="active",
            credentials_encrypted=encrypted,
            credentials_hint_json=build_credentials_hint(normalized_credentials),
            created_by_user_id=created_by_user_id,
        )
        session.add(connection)
        await session.flush()
        return _connection_summary(connection)

    async def disable_connection(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        connection_id: int,
    ) -> bool:
        connection = await session.get(ExternalSourceConnection, connection_id)
        if connection is None or connection.tenant_id != tenant_id or connection.status == "deleted":
            return False
        connection.status = "disabled"
        await session.flush()
        return True

    async def get_connection(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        connection_id: int,
    ) -> Optional[ExternalSourceConnectionSummary]:
        connection = await session.get(ExternalSourceConnection, connection_id)
        if connection is None or connection.tenant_id != tenant_id or connection.status == "deleted":
            return None
        return _connection_summary(connection)

    async def load_runtime_credentials(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        connection_id: int,
        settings: Settings,
    ) -> Optional[ExternalSourceRuntimeCredentials]:
        connection = await session.get(ExternalSourceConnection, connection_id)
        if connection is None or connection.tenant_id != tenant_id or connection.status == "deleted":
            return None
        if connection.status != "active":
            raise ValueError("外部源连接未启用")

        decrypted = TokenCrypto(settings).decrypt_token(connection.credentials_encrypted)
        payload = json.loads(decrypted)
        if not isinstance(payload, dict):
            raise ValueError("外部源凭据格式无效")
        credentials = normalize_credentials(payload)
        credential_fields = list((connection.credentials_hint_json or {}).get("fields", []))
        return ExternalSourceRuntimeCredentials(
            connection_id=connection.id,
            tenant_id=connection.tenant_id,
            provider_name=connection.provider_name,
            source_key=connection.source_key,
            credential_fields=credential_fields,
            credentials=credentials,
        )

    async def load_runtime_credentials_for_source(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        provider_name: str,
        source_key: str,
        settings: Settings,
    ) -> Optional[ExternalSourceRuntimeCredentials]:
        normalized_provider = normalize_external_identifier(provider_name, "provider_name", allow_empty=False)
        normalized_source_key = normalize_external_identifier(source_key, "source_key", allow_empty=True) or ""
        connection = await self._get_connection(
            session,
            tenant_id=tenant_id,
            provider_name=normalized_provider,
            source_key=normalized_source_key,
        )
        if connection is None or connection.status == "deleted":
            return None
        if connection.status != "active":
            raise ValueError("外部源连接未启用")
        return await self.load_runtime_credentials(
            session,
            tenant_id=tenant_id,
            connection_id=connection.id,
            settings=settings,
        )

    async def _get_connection(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        provider_name: str,
        source_key: str,
    ) -> Optional[ExternalSourceConnection]:
        result = await session.execute(
            select(ExternalSourceConnection)
            .where(ExternalSourceConnection.tenant_id == tenant_id)
            .where(ExternalSourceConnection.provider_name == provider_name)
            .where(ExternalSourceConnection.source_key == source_key)
            .limit(1)
        )
        return result.scalar_one_or_none()


def normalize_credentials(credentials: dict[str, str]) -> dict[str, str]:
    if not isinstance(credentials, dict):
        raise ValueError("外部源凭据格式无效")
    normalized: dict[str, str] = {}
    for key, value in credentials.items():
        if not isinstance(key, str):
            raise ValueError("凭据字段名必须是字符串")
        normalized_key = key.strip()
        if not normalized_key:
            raise ValueError("凭据字段名不能为空")
        if normalized_key in normalized:
            raise ValueError("凭据字段名重复")
        if not isinstance(value, str):
            raise ValueError("凭据字段值必须是字符串")
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("凭据字段值不能为空")
        normalized[normalized_key] = normalized_value
    if not normalized:
        raise ValueError("外部源凭据不能为空")
    return normalized


def build_credentials_hint(credentials: dict[str, str]) -> dict[str, list[str]]:
    return {"fields": [f"sensitive_{index}" for index, _ in enumerate(sorted(credentials.keys()), start=1)]}


def _validate_provider_credentials(provider: object, credentials: dict[str, str]) -> dict[str, str]:
    validator = getattr(provider, "validate_connection_credentials", None)
    if validator is None:
        return credentials
    validator(credentials)
    return credentials


def _connection_summary(connection: ExternalSourceConnection) -> ExternalSourceConnectionSummary:
    return ExternalSourceConnectionSummary(
        connection_id=connection.id,
        provider_name=connection.provider_name,
        source_key=connection.source_key,
        display_name=connection.display_name,
        status=connection.status,
        credential_fields=list((connection.credentials_hint_json or {}).get("fields", [])),
        created_at=connection.created_at,
        last_used_at=connection.last_used_at,
    )
