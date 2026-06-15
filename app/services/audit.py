from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.tenants import AuditLog, PlatformUser

SENSITIVE_METADATA_KEYS = {
    "address",
    "api_key",
    "authorization",
    "card",
    "card_secret",
    "content",
    "cookie",
    "credential",
    "encrypted_token",
    "header",
    "key",
    "password",
    "payload",
    "plain_key",
    "provider_trade_no",
    "payment_url",
    "raw_request",
    "raw_response",
    "sign",
    "signature",
    "signing_text",
    "secret",
    "secret_key",
    "storage_key",
    "token",
}
PLATFORM_RISK_ACTION_PREFIX = "platform_risk."
PLATFORM_AUDIT_REASON_SENSITIVE_MARKERS = (
    "token",
    "secret",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "private_key",
    "payload",
    "card_secret",
    "卡密",
)


@dataclass(frozen=True)
class AuditLogSummary:
    audit_log_id: int
    tenant_id: Optional[int]
    actor_user_id: Optional[int]
    actor_telegram_user_id: Optional[int]
    actor_username: Optional[str]
    action: str
    target_type: Optional[str]
    target_id: Optional[str]
    metadata_json: Dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class PlatformRiskAuditLogSummary:
    created_at: datetime
    action: str
    target_type: Optional[str]
    actor_telegram_user_id: Optional[int]
    actor_username: Optional[str]
    target_telegram_user_id: Optional[int]
    previous_status: Optional[str]
    new_status: Optional[str]
    reason: Optional[str]
    risk_rule: Optional[str]
    blocked_count: Optional[int]
    threshold: Optional[int]
    window_seconds: Optional[int]


class AuditLogService:
    async def list_tenant_audit_logs(
        self,
        session: AsyncSession,
        tenant_id: int,
        limit: int = 20,
        action: Optional[str] = None,
        target_type: Optional[str] = None,
    ) -> List[AuditLogSummary]:
        query = (
            select(AuditLog, PlatformUser)
            .outerjoin(PlatformUser, PlatformUser.id == AuditLog.actor_user_id)
            .where(AuditLog.tenant_id == tenant_id)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(self._normalize_limit(limit))
        )
        normalized_action = self._normalize_optional_filter(action, "action", max_length=128)
        normalized_target_type = self._normalize_optional_filter(target_type, "target_type", max_length=64)
        if normalized_action is not None:
            query = query.where(AuditLog.action == normalized_action)
        if normalized_target_type is not None:
            query = query.where(AuditLog.target_type == normalized_target_type)
        result = await session.execute(query)
        return [self._to_summary(log, actor) for log, actor in result.all()]

    async def list_platform_risk_audit_logs(
        self,
        session: AsyncSession,
        *,
        action: Optional[str] = None,
        telegram_user_id: Optional[int] = None,
        limit: int = 20,
    ) -> List[PlatformRiskAuditLogSummary]:
        normalized_limit = self._normalize_limit(limit)
        normalized_action = self._normalize_platform_risk_action(action)
        normalized_telegram_user_id = self._normalize_optional_telegram_user_id(telegram_user_id)
        query_limit = 100 if normalized_telegram_user_id is not None else normalized_limit
        query = (
            select(AuditLog, PlatformUser)
            .outerjoin(PlatformUser, PlatformUser.id == AuditLog.actor_user_id)
            .where(AuditLog.tenant_id.is_(None))
            .where(AuditLog.action.like(f"{PLATFORM_RISK_ACTION_PREFIX}%"))
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(query_limit)
        )
        if normalized_action is not None:
            query = query.where(AuditLog.action == normalized_action)
        result = await session.execute(query)
        summaries: list[PlatformRiskAuditLogSummary] = []
        for log, actor in result.all():
            summary = self._to_platform_risk_summary(log, actor)
            if normalized_telegram_user_id is not None and summary.target_telegram_user_id != normalized_telegram_user_id:
                continue
            summaries.append(summary)
            if len(summaries) >= normalized_limit:
                break
        return summaries

    async def list_platform_audit_logs(
        self,
        session: AsyncSession,
        tenant_id: Optional[int] = None,
        limit: int = 20,
    ) -> List[AuditLogSummary]:
        query = (
            select(AuditLog, PlatformUser)
            .outerjoin(PlatformUser, PlatformUser.id == AuditLog.actor_user_id)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(self._normalize_limit(limit))
        )
        if tenant_id is not None:
            query = query.where(AuditLog.tenant_id == tenant_id)
        result = await session.execute(query)
        return [self._to_summary(log, actor) for log, actor in result.all()]

    def _to_summary(self, log: AuditLog, actor: Optional[PlatformUser]) -> AuditLogSummary:
        return AuditLogSummary(
            audit_log_id=log.id,
            tenant_id=log.tenant_id,
            actor_user_id=log.actor_user_id,
            actor_telegram_user_id=actor.telegram_user_id if actor is not None else None,
            actor_username=actor.username if actor is not None else None,
            action=log.action,
            target_type=log.target_type,
            target_id=log.target_id,
            metadata_json=self._redact_metadata(log.metadata_json or {}),
            created_at=log.created_at,
        )

    def _to_platform_risk_summary(
        self,
        log: AuditLog,
        actor: Optional[PlatformUser],
    ) -> PlatformRiskAuditLogSummary:
        metadata = log.metadata_json if isinstance(log.metadata_json, dict) else {}
        return PlatformRiskAuditLogSummary(
            created_at=log.created_at,
            action=log.action,
            target_type=log.target_type,
            actor_telegram_user_id=actor.telegram_user_id if actor is not None else None,
            actor_username=actor.username if actor is not None else None,
            target_telegram_user_id=self._target_telegram_user_id_from_metadata(metadata),
            previous_status=self._safe_platform_audit_text(metadata.get("previous_status"), max_length=64),
            new_status=self._safe_platform_audit_text(metadata.get("new_status"), max_length=64),
            reason=self._safe_platform_audit_text(metadata.get("reason"), max_length=160),
            risk_rule=self._safe_platform_audit_text(metadata.get("trigger_rule", metadata.get("rule")), max_length=128),
            blocked_count=self._safe_optional_int(metadata.get("blocked_count", metadata.get("recent_count"))),
            threshold=self._safe_optional_int(metadata.get("threshold", metadata.get("recent_limit"))),
            window_seconds=self._safe_optional_int(
                metadata.get("window_seconds", metadata.get("recent_window_seconds"))
            ),
        )

    def _redact_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        redacted: Dict[str, Any] = {}
        for key, value in metadata.items():
            normalized_key = key.lower()
            if any(sensitive_key in normalized_key for sensitive_key in SENSITIVE_METADATA_KEYS):
                redacted[key] = "***"
            elif isinstance(value, dict):
                redacted[key] = self._redact_metadata(value)
            elif isinstance(value, list):
                redacted[key] = [self._redact_list_item(item) for item in value[:10]]
            else:
                redacted[key] = value
        return redacted

    def _redact_list_item(self, item: Any) -> Any:
        if isinstance(item, dict):
            return self._redact_metadata(item)
        return item

    def safe_metadata_for_tenant_api(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        safe: Dict[str, Any] = {}
        for key, value in list((metadata or {}).items())[:50]:
            key_text = str(key)
            if self._is_sensitive_metadata_key(key_text):
                continue
            safe[key_text[:128]] = self._safe_metadata_value(value, depth=0)
        return safe

    def _safe_metadata_value(self, value: Any, *, depth: int) -> Any:
        if value is None or isinstance(value, (str, int, bool)):
            return value
        if isinstance(value, float):
            return value
        if depth >= 4:
            return type(value).__name__
        if isinstance(value, dict):
            safe: Dict[str, Any] = {}
            for key, item in list(value.items())[:50]:
                key_text = str(key)
                if self._is_sensitive_metadata_key(key_text):
                    continue
                safe[key_text[:128]] = self._safe_metadata_value(item, depth=depth + 1)
            return safe
        if isinstance(value, list):
            return [self._safe_metadata_value(item, depth=depth + 1) for item in value[:10]]
        return str(value)[:300]

    @staticmethod
    def _normalize_limit(limit: int) -> int:
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("查询数量必须是整数")
        return min(max(limit, 1), 100)

    @staticmethod
    def _normalize_optional_telegram_user_id(telegram_user_id: Optional[int]) -> Optional[int]:
        if telegram_user_id is None:
            return None
        if not isinstance(telegram_user_id, int) or isinstance(telegram_user_id, bool) or telegram_user_id <= 0:
            raise ValueError("Telegram 用户 ID 必须是正整数")
        return telegram_user_id

    @classmethod
    def _normalize_platform_risk_action(cls, action: Optional[str]) -> Optional[str]:
        normalized = cls._normalize_optional_filter(action, "action", max_length=128)
        if normalized is None:
            return None
        if not normalized.startswith(PLATFORM_RISK_ACTION_PREFIX):
            raise ValueError("平台风控审计 action 无效")
        return normalized

    @staticmethod
    def _normalize_optional_filter(value: Optional[str], name: str, *, max_length: int) -> Optional[str]:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        if len(normalized) > max_length:
            raise ValueError(f"{name} 长度不能超过 {max_length}")
        if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
            raise ValueError(f"{name} 不能包含控制字符")
        return normalized

    @staticmethod
    def _is_sensitive_metadata_key(key: str) -> bool:
        normalized_key = key.lower()
        return any(sensitive_key in normalized_key for sensitive_key in SENSITIVE_METADATA_KEYS)

    @staticmethod
    def _target_telegram_user_id_from_metadata(metadata: Dict[str, Any]) -> Optional[int]:
        for key in ("telegram_user_id", "buyer_telegram_user_id"):
            value = metadata.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                return value
        return None

    @staticmethod
    def _safe_optional_int(value: Any) -> Optional[int]:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        return None

    @staticmethod
    def _safe_platform_audit_text(value: Any, *, max_length: int) -> Optional[str]:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        lowered = normalized.lower()
        if "http://" in lowered or "https://" in lowered:
            return "内容已隐藏"
        if any(marker in lowered for marker in PLATFORM_AUDIT_REASON_SENSITIVE_MARKERS):
            return "内容已隐藏"
        return normalized[:max_length]
