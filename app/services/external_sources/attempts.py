from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.external_sources import ExternalFulfillmentAttempt
from app.services.external_sources.failures import SENSITIVE_FAILURE_VALUE_MARKERS
from app.services.external_sources.identifiers import normalize_external_identifier


SENSITIVE_ATTEMPT_VALUE_MARKERS = SENSITIVE_FAILURE_VALUE_MARKERS
EXTERNAL_FULFILLMENT_ATTEMPT_STATUSES = frozenset(
    ("started", "running", "succeeded", "already_delivered", "failed", "imported")
)


@dataclass(frozen=True)
class ExternalFulfillmentAttemptSummary:
    attempt_id: int
    created_at: datetime
    started_at: datetime
    finished_at: datetime
    order_id: int
    out_trade_no: str
    product_id: int
    provider_name: str
    source_key: str
    external_product_id: str
    connection_id: Optional[int]
    external_order_id: Optional[str]
    delivery_record_id: Optional[int]
    attempt_source: str
    status: str
    imported: bool
    item_count: int
    failure_reason: Optional[str]
    failure_stage: Optional[str]
    failure_category: Optional[str]
    failure_retryable: Optional[bool]
    upstream_status_code: Optional[int]
    failure_fingerprint: Optional[str]


class ExternalFulfillmentAttemptLogService:
    async def list_attempts(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        out_trade_no: Optional[str] = None,
        provider_name: Optional[str] = None,
        source_key: Optional[str] = None,
        external_order_id: Optional[str] = None,
        attempt_source: Optional[str] = None,
        status: Optional[str] = None,
        failure_stage: Optional[str] = None,
        failure_category: Optional[str] = None,
        failure_retryable: Optional[bool] = None,
        limit: int = 20,
    ) -> list[ExternalFulfillmentAttemptSummary]:
        normalized_limit = self._normalize_limit(limit)
        normalized_out_trade_no = self._normalize_optional_out_trade_no(out_trade_no)
        normalized_provider = self._normalize_optional_identifier(provider_name, "provider_name", allow_empty=False)
        normalized_source_key = self._normalize_optional_identifier(source_key, "source_key", allow_empty=True)
        normalized_external_order_id = self._normalize_optional_external_text(
            external_order_id,
            "external_order_id",
            max_length=128,
        )
        normalized_attempt_source = self._normalize_optional_choice(
            attempt_source,
            "attempt_source",
            allowed={"auto", "manual"},
        )
        normalized_status = self._normalize_optional_choice(
            status,
            "status",
            allowed=set(EXTERNAL_FULFILLMENT_ATTEMPT_STATUSES),
        )
        normalized_stage = self._normalize_optional_identifier(failure_stage, "failure_stage", allow_empty=False)
        normalized_category = self._normalize_optional_identifier(
            failure_category,
            "failure_category",
            allow_empty=False,
        )
        normalized_retryable = self._normalize_optional_bool(failure_retryable, "failure_retryable")
        query = select(ExternalFulfillmentAttempt).where(ExternalFulfillmentAttempt.tenant_id == tenant_id)
        if normalized_out_trade_no is not None:
            query = query.where(ExternalFulfillmentAttempt.out_trade_no == normalized_out_trade_no)
        if normalized_provider is not None:
            query = query.where(ExternalFulfillmentAttempt.provider_name == normalized_provider)
        if normalized_source_key is not None:
            query = query.where(ExternalFulfillmentAttempt.source_key == normalized_source_key)
        if normalized_external_order_id is not None:
            query = query.where(ExternalFulfillmentAttempt.external_order_id == normalized_external_order_id)
        if normalized_attempt_source is not None:
            query = query.where(ExternalFulfillmentAttempt.attempt_source == normalized_attempt_source)
        if normalized_status is not None:
            query = query.where(ExternalFulfillmentAttempt.status == normalized_status)
        if normalized_stage is not None:
            query = query.where(ExternalFulfillmentAttempt.failure_stage == normalized_stage)
        if normalized_category is not None:
            query = query.where(ExternalFulfillmentAttempt.failure_category == normalized_category)
        if normalized_retryable is not None:
            query = query.where(ExternalFulfillmentAttempt.failure_retryable == normalized_retryable)
        result = await session.execute(
            query.order_by(
                ExternalFulfillmentAttempt.created_at.desc(),
                ExternalFulfillmentAttempt.id.desc(),
            ).limit(normalized_limit)
        )
        attempts = list(result.scalars().all())
        summaries = [
            self._to_summary(attempt)
            for attempt in attempts
            if self._matches_filters(
                attempt,
                out_trade_no=normalized_out_trade_no,
                provider_name=normalized_provider,
                source_key=normalized_source_key,
                external_order_id=normalized_external_order_id,
                attempt_source=normalized_attempt_source,
                status=normalized_status,
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
    def _normalize_optional_choice(value: Optional[str], field_name: str, *, allowed: set[str]) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"{field_name} 必须是字符串")
        normalized = value.strip()
        if normalized not in allowed:
            raise ValueError(f"{field_name} 无效")
        return normalized

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
    def _normalize_optional_external_text(
        value: Optional[str],
        field_name: str,
        *,
        max_length: int,
    ) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"{field_name} 必须是字符串")
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} 不能为空")
        if len(normalized) > max_length:
            raise ValueError(f"{field_name} 长度不能超过 {max_length}")
        if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
            raise ValueError(f"{field_name} 不能包含控制字符")
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
        attempt: ExternalFulfillmentAttempt,
        *,
        out_trade_no: Optional[str],
        provider_name: Optional[str],
        source_key: Optional[str],
        external_order_id: Optional[str],
        attempt_source: Optional[str],
        status: Optional[str],
        failure_stage: Optional[str],
        failure_category: Optional[str],
        failure_retryable: Optional[bool],
    ) -> bool:
        if out_trade_no is not None and attempt.out_trade_no != out_trade_no:
            return False
        if provider_name is not None and attempt.provider_name != provider_name:
            return False
        if source_key is not None and attempt.source_key != source_key:
            return False
        if external_order_id is not None and attempt.external_order_id != external_order_id:
            return False
        if attempt_source is not None and attempt.attempt_source != attempt_source:
            return False
        if status is not None and attempt.status != status:
            return False
        if failure_stage is not None and attempt.failure_stage != failure_stage:
            return False
        if failure_category is not None and attempt.failure_category != failure_category:
            return False
        if failure_retryable is not None and bool(attempt.failure_retryable) != failure_retryable:
            return False
        return True

    def _to_summary(self, attempt: ExternalFulfillmentAttempt) -> ExternalFulfillmentAttemptSummary:
        return ExternalFulfillmentAttemptSummary(
            attempt_id=int(attempt.id),
            created_at=attempt.created_at,
            started_at=attempt.started_at,
            finished_at=attempt.finished_at,
            order_id=int(attempt.order_id),
            out_trade_no=attempt.out_trade_no,
            product_id=int(attempt.product_id),
            provider_name=attempt.provider_name,
            source_key=attempt.source_key,
            external_product_id=attempt.external_product_id,
            connection_id=self._optional_int(attempt.connection_id),
            external_order_id=self._safe_text(attempt.external_order_id, max_length=128),
            delivery_record_id=self._optional_int(attempt.delivery_record_id),
            attempt_source=attempt.attempt_source,
            status=attempt.status,
            imported=bool(attempt.imported),
            item_count=max(self._optional_int(attempt.item_count) or 0, 0),
            failure_reason=self._safe_attempt_failure_reason(attempt.failure_reason),
            failure_stage=self._safe_text(attempt.failure_stage, max_length=64),
            failure_category=self._safe_text(attempt.failure_category, max_length=64),
            failure_retryable=attempt.failure_retryable if isinstance(attempt.failure_retryable, bool) else None,
            upstream_status_code=self._optional_int(attempt.upstream_status_code),
            failure_fingerprint=self._safe_text(attempt.failure_fingerprint, max_length=64),
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

    def _safe_attempt_failure_reason(self, value: object) -> Optional[str]:
        reason = self._safe_text(value, max_length=300)
        if reason is None:
            return None
        normalized = reason.lower()
        if any(marker in normalized for marker in SENSITIVE_ATTEMPT_VALUE_MARKERS):
            return "外部履约失败"
        return reason
