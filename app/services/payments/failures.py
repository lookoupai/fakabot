from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.orders import Order, PaymentCallback
from app.db.models.tenants import AuditLog
from app.services.payments.configs import normalize_payment_provider


PAYMENT_CALLBACK_OBSERVABLE_STATUSES = ("failed", "ignored")
PAYMENT_CALLBACK_REJECTION_ACTION = "payment_callback.rejected"
PAYMENT_CALLBACK_REJECTION_REASON_CATEGORIES = (
    "payload_malformed",
    "invalid_callback",
    "payment_unavailable",
)
PAYMENT_CALLBACK_REJECTION_REASON_TEXT = {
    "payload_malformed": "支付回调 payload 无法解析",
    "invalid_callback": "支付回调参数无效",
    "payment_unavailable": "支付配置暂不可用",
}
SENSITIVE_PAYMENT_FAILURE_VALUE_MARKERS = (
    "api_key",
    "authorization",
    "cookie",
    "credential",
    "password",
    "payload",
    "plain_key",
    "provider_trade_no",
    "secret",
    "signature",
    "signing_text",
    "token",
)


@dataclass(frozen=True)
class PaymentCallbackFailureSummary:
    callback_id: int
    created_at: datetime
    processed_at: Optional[datetime]
    order_id: int
    out_trade_no: str
    order_status: str
    provider: str
    process_status: str
    failure_reason: str


@dataclass(frozen=True)
class PaymentCallbackRejectionSummary:
    audit_log_id: int
    created_at: datetime
    provider: str
    reason_category: str
    failure_reason: str
    http_status: int
    out_trade_no: Optional[str]
    order_id: Optional[int]
    order_status: Optional[str]
    payload_field_count: int


class PaymentCallbackFailureLogService:
    async def list_failures(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        provider: Optional[str] = None,
        process_status: str = "failed",
        out_trade_no: Optional[str] = None,
        limit: int = 20,
    ) -> list[PaymentCallbackFailureSummary]:
        normalized_limit = self._normalize_limit(limit)
        normalized_provider = normalize_payment_provider(provider) if provider is not None else None
        normalized_status = self._normalize_process_status(process_status)
        normalized_out_trade_no = self._normalize_optional_out_trade_no(out_trade_no)
        query = (
            select(PaymentCallback, Order)
            .join(Order, Order.out_trade_no == PaymentCallback.out_trade_no)
            .where(Order.tenant_id == tenant_id)
            .where(PaymentCallback.process_status == normalized_status)
        )
        if normalized_provider is not None:
            query = query.where(PaymentCallback.provider == normalized_provider)
        if normalized_out_trade_no is not None:
            query = query.where(PaymentCallback.out_trade_no == normalized_out_trade_no)
        result = await session.execute(
            query.order_by(PaymentCallback.created_at.desc(), PaymentCallback.id.desc()).limit(normalized_limit)
        )
        rows = list(result.all())
        summaries = [
            self._to_summary(callback, order)
            for callback, order in rows
            if self._matches_filters(
                callback,
                order,
                tenant_id=tenant_id,
                provider=normalized_provider,
                process_status=normalized_status,
                out_trade_no=normalized_out_trade_no,
            )
        ]
        return summaries[:normalized_limit]

    @staticmethod
    def _normalize_limit(limit: int) -> int:
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("limit 必须是整数")
        return min(max(limit, 1), 100)

    @staticmethod
    def _normalize_process_status(value: str) -> str:
        normalized = str(value).strip().lower()
        if normalized not in PAYMENT_CALLBACK_OBSERVABLE_STATUSES:
            raise ValueError("process_status 不支持")
        return normalized

    @staticmethod
    def _normalize_optional_out_trade_no(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if len(text) > 96:
            raise ValueError("out_trade_no 长度不能超过 96")
        if any(ord(char) < 32 or ord(char) == 127 for char in text):
            raise ValueError("out_trade_no 不能包含控制字符")
        return text

    def _matches_filters(
        self,
        callback: PaymentCallback,
        order: Order,
        *,
        tenant_id: int,
        provider: Optional[str],
        process_status: str,
        out_trade_no: Optional[str],
    ) -> bool:
        if int(order.tenant_id) != tenant_id:
            return False
        if str(callback.process_status) != process_status:
            return False
        if provider is not None and str(callback.provider) != provider:
            return False
        if out_trade_no is not None and str(callback.out_trade_no) != out_trade_no:
            return False
        return True

    def _to_summary(self, callback: PaymentCallback, order: Order) -> PaymentCallbackFailureSummary:
        return PaymentCallbackFailureSummary(
            callback_id=int(callback.id),
            created_at=callback.created_at,
            processed_at=callback.processed_at,
            order_id=int(order.id),
            out_trade_no=self._safe_text(callback.out_trade_no, max_length=96) or "",
            order_status=self._safe_text(order.status, max_length=32) or "unknown",
            provider=self._safe_text(callback.provider, max_length=64) or "",
            process_status=self._safe_text(callback.process_status, max_length=32) or "unknown",
            failure_reason=self._safe_failure_reason(callback.error_message),
        )

    @staticmethod
    def _safe_text(value: object, *, max_length: int) -> Optional[str]:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized[:max_length]

    def _safe_failure_reason(self, value: object) -> str:
        reason = self._safe_text(value, max_length=300) or "支付回调未处理成功"
        normalized = reason.lower()
        if any(marker in normalized for marker in SENSITIVE_PAYMENT_FAILURE_VALUE_MARKERS):
            return "支付回调未处理成功"
        return reason


class PaymentCallbackRejectionAuditService:
    async def record_rejection(
        self,
        session: AsyncSession,
        *,
        provider_name: object,
        payload: Optional[Mapping[str, Any]],
        reason_category: str,
        http_status: int,
    ) -> None:
        normalized_reason = self._normalize_reason_category(reason_category)
        safe_provider = self._safe_provider_name(provider_name)
        payload_map = dict(payload) if isinstance(payload, Mapping) else {}
        out_trade_no = self._extract_safe_out_trade_no(payload_map)
        order = await self._get_order_by_out_trade_no(session, out_trade_no)
        metadata: dict[str, Any] = {
            "provider": safe_provider,
            "reason_category": normalized_reason,
            "failure_reason": PAYMENT_CALLBACK_REJECTION_REASON_TEXT[normalized_reason],
            "http_status": self._safe_http_status(http_status),
            "payload_field_count": len(payload_map),
        }
        if out_trade_no is not None:
            metadata["out_trade_no"] = out_trade_no
        if order is not None:
            metadata["order_id"] = int(order.id)
            metadata["order_status"] = self._safe_text(order.status, max_length=32) or "unknown"

        session.add(
            AuditLog(
                tenant_id=int(order.tenant_id) if order is not None else None,
                actor_user_id=None,
                action=PAYMENT_CALLBACK_REJECTION_ACTION,
                target_type="order" if order is not None else "payment_callback",
                target_id=str(order.id) if order is not None else self._fallback_target_id(safe_provider, out_trade_no),
                metadata_json=metadata,
            )
        )
        await session.flush()

    async def list_rejections(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        provider: Optional[str] = None,
        reason_category: Optional[str] = None,
        out_trade_no: Optional[str] = None,
        limit: int = 20,
    ) -> list[PaymentCallbackRejectionSummary]:
        normalized_limit = PaymentCallbackFailureLogService._normalize_limit(limit)
        normalized_provider = normalize_payment_provider(provider) if provider is not None else None
        normalized_reason = (
            self._normalize_reason_category(reason_category) if reason_category is not None else None
        )
        normalized_out_trade_no = PaymentCallbackFailureLogService._normalize_optional_out_trade_no(out_trade_no)
        result = await session.execute(
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id)
            .where(AuditLog.action == PAYMENT_CALLBACK_REJECTION_ACTION)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(normalized_limit * 5)
        )
        logs = self._extract_audit_logs(result)
        summaries = [
            self._to_summary(log)
            for log in logs
            if self._matches_filters(
                log,
                tenant_id=tenant_id,
                provider=normalized_provider,
                reason_category=normalized_reason,
                out_trade_no=normalized_out_trade_no,
            )
        ]
        return summaries[:normalized_limit]

    async def _get_order_by_out_trade_no(self, session: AsyncSession, out_trade_no: Optional[str]) -> Optional[Order]:
        if out_trade_no is None:
            return None
        result = await session.execute(select(Order).where(Order.out_trade_no == out_trade_no))
        order = result.scalar_one_or_none()
        return order if isinstance(order, Order) or order is not None else None

    def _to_summary(self, log: AuditLog) -> PaymentCallbackRejectionSummary:
        metadata = log.metadata_json or {}
        return PaymentCallbackRejectionSummary(
            audit_log_id=int(log.id),
            created_at=log.created_at,
            provider=self._safe_text(metadata.get("provider"), max_length=64) or "unknown",
            reason_category=self._safe_reason_for_response(metadata.get("reason_category")),
            failure_reason=self._safe_failure_reason(metadata.get("failure_reason")),
            http_status=self._safe_http_status(metadata.get("http_status")),
            out_trade_no=self._safe_out_trade_no_for_response(metadata.get("out_trade_no")),
            order_id=self._safe_optional_int(metadata.get("order_id")),
            order_status=self._safe_text(metadata.get("order_status"), max_length=32),
            payload_field_count=self._safe_non_negative_int(metadata.get("payload_field_count")),
        )

    def _matches_filters(
        self,
        log: AuditLog,
        *,
        tenant_id: int,
        provider: Optional[str],
        reason_category: Optional[str],
        out_trade_no: Optional[str],
    ) -> bool:
        if int(log.tenant_id or 0) != tenant_id:
            return False
        if str(log.action) != PAYMENT_CALLBACK_REJECTION_ACTION:
            return False
        metadata = log.metadata_json or {}
        if provider is not None and self._safe_text(metadata.get("provider"), max_length=64) != provider:
            return False
        if reason_category is not None and metadata.get("reason_category") != reason_category:
            return False
        if out_trade_no is not None and metadata.get("out_trade_no") != out_trade_no:
            return False
        return True

    @staticmethod
    def _extract_audit_logs(result: object) -> list[AuditLog]:
        scalars = getattr(result, "scalars", None)
        if callable(scalars):
            scalar_result = scalars()
            all_items = getattr(scalar_result, "all", None)
            if callable(all_items):
                return list(all_items())
        all_rows = getattr(result, "all", None)
        if callable(all_rows):
            rows = all_rows()
            return [row[0] if isinstance(row, tuple) else row for row in rows]
        return []

    @staticmethod
    def _normalize_reason_category(value: object) -> str:
        normalized = str(value).strip().lower()
        if normalized not in PAYMENT_CALLBACK_REJECTION_REASON_CATEGORIES:
            raise ValueError("reason_category 不支持")
        return normalized

    def _safe_provider_name(self, value: object) -> str:
        try:
            return normalize_payment_provider(str(value))
        except ValueError:
            provider = self._safe_text(value, max_length=64)
            if provider is None:
                return "unknown"
            return provider.lower()

    @staticmethod
    def _safe_http_status(value: object) -> int:
        if isinstance(value, bool):
            return 400
        try:
            status = int(value)
        except (TypeError, ValueError):
            return 400
        return status if 100 <= status <= 599 else 400

    @staticmethod
    def _safe_optional_int(value: object) -> Optional[int]:
        if isinstance(value, bool) or value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_non_negative_int(value: object) -> int:
        if isinstance(value, bool):
            return 0
        try:
            number = int(value)
        except (TypeError, ValueError):
            return 0
        return max(number, 0)

    def _extract_safe_out_trade_no(self, payload: Mapping[str, Any]) -> Optional[str]:
        for key in ("out_trade_no", "order_id", "orderNo"):
            value = self._safe_out_trade_no_for_response(payload.get(key))
            if value is not None:
                return value
        return None

    def _safe_out_trade_no_for_response(self, value: object) -> Optional[str]:
        text = self._safe_text(value, max_length=96)
        if text is None:
            return None
        normalized = text.lower()
        if any(marker in normalized for marker in SENSITIVE_PAYMENT_FAILURE_VALUE_MARKERS):
            return None
        return text

    def _safe_failure_reason(self, value: object) -> str:
        reason = self._safe_text(value, max_length=300) or "支付回调未处理成功"
        normalized = reason.lower()
        if any(marker in normalized for marker in SENSITIVE_PAYMENT_FAILURE_VALUE_MARKERS):
            return "支付回调未处理成功"
        return reason

    def _safe_reason_for_response(self, value: object) -> str:
        try:
            return self._normalize_reason_category(value)
        except ValueError:
            return "invalid_callback"

    def _fallback_target_id(self, provider: str, out_trade_no: Optional[str]) -> str:
        target = out_trade_no or provider or "unknown"
        return target[:64] or "unknown"

    @staticmethod
    def _safe_text(value: object, *, max_length: int) -> Optional[str]:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
            return None
        return normalized[:max_length]
