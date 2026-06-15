from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.tenants import AuditLog
from app.services.external_sources.identifiers import normalize_external_identifier


EXTERNAL_FULFILLMENT_FAILED_ACTION = "external_fulfillment.failed"
EXTERNAL_FULFILLMENT_FAILURE_TARGET_TYPE = "order"
SENSITIVE_FAILURE_VALUE_MARKERS = (
    "api_key",
    "authorization",
    "card_secret",
    "cookie",
    "credential",
    "password",
    "payload",
    "plain_key",
    "secret",
    "storage_key",
    "token",
)


@dataclass(frozen=True)
class ExternalFulfillmentFailureSummary:
    audit_log_id: int
    created_at: datetime
    order_id: Optional[int]
    out_trade_no: Optional[str]
    product_id: Optional[int]
    provider_name: str
    source_key: str
    external_product_id: Optional[str]
    connection_id: Optional[int]
    external_order_id: Optional[str]
    failure_reason: str
    failure_stage: str
    failure_category: str
    failure_retryable: bool
    upstream_status_code: Optional[int]
    failure_fingerprint: Optional[str]


class ExternalFulfillmentFailureLogService:
    async def list_failures(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        out_trade_no: Optional[str] = None,
        provider_name: Optional[str] = None,
        source_key: Optional[str] = None,
        failure_stage: Optional[str] = None,
        failure_category: Optional[str] = None,
        failure_retryable: Optional[bool] = None,
        limit: int = 20,
    ) -> list[ExternalFulfillmentFailureSummary]:
        normalized_limit = self._normalize_limit(limit)
        normalized_out_trade_no = self._normalize_optional_out_trade_no(out_trade_no)
        normalized_provider = self._normalize_optional_identifier(provider_name, "provider_name", allow_empty=False)
        normalized_source_key = self._normalize_optional_identifier(source_key, "source_key", allow_empty=True)
        normalized_stage = self._normalize_optional_identifier(failure_stage, "failure_stage", allow_empty=False)
        normalized_category = self._normalize_optional_identifier(
            failure_category,
            "failure_category",
            allow_empty=False,
        )
        normalized_retryable = self._normalize_optional_bool(failure_retryable, "failure_retryable")
        query = (
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id)
            .where(AuditLog.action == EXTERNAL_FULFILLMENT_FAILED_ACTION)
            .where(AuditLog.target_type == EXTERNAL_FULFILLMENT_FAILURE_TARGET_TYPE)
        )
        if normalized_out_trade_no is not None:
            query = query.where(AuditLog.metadata_json.contains({"out_trade_no": normalized_out_trade_no}))
        if normalized_provider is not None:
            query = query.where(AuditLog.metadata_json.contains({"provider_name": normalized_provider}))
        if normalized_source_key is not None:
            query = query.where(AuditLog.metadata_json.contains({"source": normalized_source_key}))
        if normalized_stage is not None:
            query = query.where(AuditLog.metadata_json.contains({"failure_stage": normalized_stage}))
        if normalized_category is not None:
            query = query.where(AuditLog.metadata_json.contains({"failure_category": normalized_category}))
        if normalized_retryable is not None:
            query = query.where(AuditLog.metadata_json.contains({"failure_retryable": normalized_retryable}))
        result = await session.execute(
            query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(normalized_limit)
        )
        logs = list(result.scalars().all())
        summaries = [
            self._to_summary(log)
            for log in logs
            if self._matches_filters(
                log,
                out_trade_no=normalized_out_trade_no,
                provider_name=normalized_provider,
                source_key=normalized_source_key,
                failure_stage=normalized_stage,
                failure_category=normalized_category,
                failure_retryable=normalized_retryable,
            )
        ]
        return summaries[:normalized_limit]

    @staticmethod
    def _normalize_optional_identifier(value: Optional[str], field_name: str, *, allow_empty: bool) -> Optional[str]:
        if value is None:
            return None
        return normalize_external_identifier(value, field_name, allow_empty=allow_empty)

    @staticmethod
    def _normalize_optional_out_trade_no(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("out_trade_no 必须是字符串")
        normalized = value.strip()
        if not normalized:
            raise ValueError("out_trade_no 不能为空")
        if len(normalized) > 96:
            raise ValueError("out_trade_no 长度不能超过 96")
        if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
            raise ValueError("out_trade_no 不能包含控制字符")
        return normalized

    @staticmethod
    def _normalize_optional_bool(value: Optional[bool], field_name: str) -> Optional[bool]:
        if value is None:
            return None
        if not isinstance(value, bool):
            raise ValueError(f"{field_name} 必须是布尔值")
        return value

    @staticmethod
    def _normalize_limit(limit: int) -> int:
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("limit 必须是整数")
        return min(max(limit, 1), 100)

    def _matches_filters(
        self,
        log: AuditLog,
        *,
        out_trade_no: Optional[str],
        provider_name: Optional[str],
        source_key: Optional[str],
        failure_stage: Optional[str],
        failure_category: Optional[str],
        failure_retryable: Optional[bool],
    ) -> bool:
        metadata = log.metadata_json or {}
        if out_trade_no is not None and self._safe_text(metadata.get("out_trade_no"), max_length=96) != out_trade_no:
            return False
        if provider_name is not None and self._safe_text(metadata.get("provider_name"), max_length=64) != provider_name:
            return False
        if source_key is not None and self._safe_text(metadata.get("source"), max_length=128) != source_key:
            return False
        if failure_stage is not None and self._safe_text(metadata.get("failure_stage"), max_length=64) != failure_stage:
            return False
        if (
            failure_category is not None
            and self._safe_text(metadata.get("failure_category"), max_length=64) != failure_category
        ):
            return False
        if failure_retryable is not None and bool(metadata.get("failure_retryable")) != failure_retryable:
            return False
        return True

    def _to_summary(self, log: AuditLog) -> ExternalFulfillmentFailureSummary:
        metadata = log.metadata_json or {}
        return ExternalFulfillmentFailureSummary(
            audit_log_id=int(log.id),
            created_at=log.created_at,
            order_id=self._optional_int(metadata.get("order_id")),
            out_trade_no=self._safe_text(metadata.get("out_trade_no"), max_length=96),
            product_id=self._optional_int(metadata.get("product_id")),
            provider_name=self._safe_text(metadata.get("provider_name"), max_length=64) or "",
            source_key=self._safe_text(metadata.get("source"), max_length=128) or "",
            external_product_id=self._safe_text(metadata.get("external_product_id"), max_length=128),
            connection_id=self._optional_int(metadata.get("connection_id")),
            external_order_id=self._safe_text(metadata.get("external_order_id"), max_length=128),
            failure_reason=self._safe_failure_reason(metadata.get("failure_reason")),
            failure_stage=self._safe_text(metadata.get("failure_stage"), max_length=64) or "unknown",
            failure_category=self._safe_text(metadata.get("failure_category"), max_length=64) or "unknown",
            failure_retryable=bool(metadata.get("failure_retryable")),
            upstream_status_code=self._optional_int(metadata.get("upstream_status_code")),
            failure_fingerprint=self._safe_text(metadata.get("failure_fingerprint"), max_length=64),
        )

    @staticmethod
    def _optional_int(value: object) -> Optional[int]:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        return None

    @staticmethod
    def _safe_text(value: object, *, max_length: int) -> Optional[str]:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized[:max_length]

    def _safe_failure_reason(self, value: object) -> str:
        reason = self._safe_text(value, max_length=300) or "外部履约失败"
        normalized = reason.lower()
        if any(marker in normalized for marker in SENSITIVE_FAILURE_VALUE_MARKERS):
            return "外部履约失败"
        return reason
