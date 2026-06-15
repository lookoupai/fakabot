from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.external_sources import ExternalFulfillmentAttempt
from app.db.models.orders import DeliveryRecord, Order
from app.db.models.products import Product
from app.db.models.tenants import AuditLog
from app.services.external_sources.base import ExternalOrderRequest, ExternalSourceError
from app.services.external_sources.connections import ExternalSourceConnectionService
from app.services.external_sources.fulfillment import (
    ExternalDeliveryImportService,
    uses_external_text_fulfillment,
)
from app.services.external_sources.http import HTTP_ERROR_CATEGORY_UNKNOWN
from app.services.external_sources.orders import ExternalOrderOperationService
from app.services.external_sources.registry import is_provider_auto_fulfillment_available


EXTERNAL_FULFILLMENT_ATTEMPT_STATUSES = frozenset(
    ("started", "running", "succeeded", "already_delivered", "failed", "imported")
)
EXTERNAL_FULFILLMENT_ATTEMPT_WRITE_STATUSES = frozenset(
    ("started", "running", "succeeded", "already_delivered", "failed")
)


@dataclass(frozen=True)
class ExternalAutoFulfillmentResult:
    out_trade_no: str
    provider_name: str
    source_key: str
    external_order_id: Optional[str]
    delivery_record_id: Optional[int]
    item_count: int
    imported: bool


@dataclass(frozen=True)
class ExternalAutoFulfillmentBatchResult:
    checked_count: int
    imported_count: int
    failed_count: int
    delivery_record_ids: list[int]


@dataclass(frozen=True)
class ExternalAutoFulfillmentAttemptResult:
    out_trade_no: str
    provider_name: str
    source_key: str
    external_order_id: Optional[str]
    delivery_record_id: Optional[int]
    item_count: int
    imported: bool
    attempt_status: str
    failure_stage: Optional[str] = None
    failure_category: Optional[str] = None
    failure_retryable: Optional[bool] = None
    upstream_status_code: Optional[int] = None
    failure_recorded: bool = False


class ExternalAutoFulfillmentError(ValueError):
    def __init__(
        self,
        reason: str,
        *,
        stage: str,
        category: str = HTTP_ERROR_CATEGORY_UNKNOWN,
        retryable: bool = False,
        status_code: int | None = None,
        external_order_id: str | None = None,
        connection_id: int | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.stage = stage
        self.category = category
        self.retryable = retryable
        self.status_code = status_code
        self.external_order_id = external_order_id
        self.connection_id = connection_id


class ExternalAutoFulfillmentService:
    def __init__(
        self,
        *,
        connection_service: ExternalSourceConnectionService | None = None,
        operation_service: ExternalOrderOperationService | None = None,
        import_service: ExternalDeliveryImportService | None = None,
    ) -> None:
        self._connection_service = connection_service or ExternalSourceConnectionService()
        self._operation_service = operation_service or ExternalOrderOperationService()
        self._import_service = import_service or ExternalDeliveryImportService()

    async def fulfill_paid_order(
        self,
        session: AsyncSession,
        *,
        order: Order,
        product: Product,
        settings: Settings,
        attempt_source: str = "auto",
    ) -> ExternalAutoFulfillmentResult:
        self._validate_order_product(order, product)
        normalized_attempt_source = _normalize_attempt_source(attempt_source)
        provider_name = str(product.external_source or "").strip()
        source_key = str(product.source_key or "").strip()

        existing_delivery = await self._get_delivery_record(session, order.id)
        if existing_delivery is not None:
            attempt = _add_attempt_record(
                session,
                order,
                product,
                attempt_source=normalized_attempt_source,
                status="started",
            )
            _mark_attempt_record(
                attempt,
                order,
                product,
                status="already_delivered",
                delivery_record_id=existing_delivery.id,
            )
            return ExternalAutoFulfillmentResult(
                out_trade_no=order.out_trade_no,
                provider_name=provider_name,
                source_key=source_key,
                external_order_id=None,
                delivery_record_id=existing_delivery.id,
                item_count=0,
                imported=False,
            )

        attempt = _add_attempt_record(
            session,
            order,
            product,
            attempt_source=normalized_attempt_source,
            status="started",
        )
        try:
            if not is_provider_auto_fulfillment_available(provider_name):
                raise ExternalAutoFulfillmentError(
                    "外部源未声明按 out_trade_no 幂等自动履约",
                    stage="provider_capability",
                    category="auto_fulfillment_not_enabled",
                )
            _mark_attempt_record(attempt, order, product, status="running")
            try:
                runtime_auth = await self._connection_service.load_runtime_credentials_for_source(
                    session,
                    tenant_id=order.tenant_id,
                    provider_name=provider_name,
                    source_key=source_key,
                    settings=settings,
                )
            except ValueError as exc:
                raise ExternalAutoFulfillmentError(
                    "外部源运行时凭据加载失败",
                    stage="load_credentials",
                    category="credentials_load_failed",
                ) from exc
            if runtime_auth is None:
                raise ExternalAutoFulfillmentError(
                    "外部源连接不可用",
                    stage="load_credentials",
                    category="connection_missing",
                )
            connection_id = getattr(runtime_auth, "connection_id", None) if runtime_auth is not None else None
            _mark_attempt_record(attempt, order, product, status="running", connection_id=connection_id)

            try:
                external_order = await self._operation_service.create_registered_order(
                    tenant_id=order.tenant_id,
                    provider_name=provider_name,
                    source_key=source_key,
                    connection_id=connection_id,
                    runtime_auth=runtime_auth,
                    request=ExternalOrderRequest(
                        external_product_id=str(product.external_id or "").strip(),
                        quantity=1,
                        out_trade_no=order.out_trade_no,
                    ),
                )
            except ExternalSourceError as exc:
                raise _fulfillment_error_from_external_source(
                    exc,
                    stage="create_order",
                    connection_id=connection_id,
                ) from exc
            _mark_attempt_record(
                attempt,
                order,
                product,
                status="running",
                connection_id=connection_id,
                external_order_id=external_order.external_order_id,
            )

            try:
                delivery = await self._operation_service.fetch_registered_delivery(
                    tenant_id=order.tenant_id,
                    provider_name=provider_name,
                    source_key=source_key,
                    connection_id=connection_id,
                    runtime_auth=runtime_auth,
                    external_order_id=external_order.external_order_id,
                )
            except ExternalSourceError as exc:
                raise _fulfillment_error_from_external_source(
                    exc,
                    stage="fetch_delivery",
                    external_order_id=external_order.external_order_id,
                    connection_id=connection_id,
                ) from exc

            if delivery is None:
                raise ExternalAutoFulfillmentError(
                    "外部发货尚未就绪",
                    stage="delivery_pending",
                    category="delivery_pending",
                    retryable=True,
                    external_order_id=external_order.external_order_id,
                    connection_id=connection_id,
                )

            try:
                imported = await self._import_service.import_delivery(
                    session,
                    tenant_id=order.tenant_id,
                    out_trade_no=order.out_trade_no,
                    provider_name=provider_name,
                    source_key=source_key,
                    delivery=delivery,
                    settings=settings,
                )
            except ValueError as exc:
                raise ExternalAutoFulfillmentError(
                    "外部发货导入失败",
                    stage="import_delivery",
                    category="import_failed",
                    external_order_id=external_order.external_order_id,
                    connection_id=connection_id,
                ) from exc
        except ValueError as exc:
            _mark_attempt_record(attempt, order, product, status="failed", exc=exc)
            setattr(exc, "attempt_recorded", True)
            raise
        _mark_attempt_record(
            attempt,
            order,
            product,
            status="succeeded" if imported.imported else "already_delivered",
            connection_id=connection_id,
            external_order_id=external_order.external_order_id,
            delivery_record_id=imported.delivery_record_id,
            item_count=imported.item_count,
            imported=imported.imported,
        )
        return ExternalAutoFulfillmentResult(
            out_trade_no=order.out_trade_no,
            provider_name=provider_name,
            source_key=source_key,
            external_order_id=external_order.external_order_id,
            delivery_record_id=imported.delivery_record_id,
            item_count=imported.item_count,
            imported=imported.imported,
        )

    async def fulfill_tenant_paid_order(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        out_trade_no: str,
        settings: Settings,
    ) -> ExternalAutoFulfillmentAttemptResult | None:
        _validate_tenant_id(tenant_id)
        normalized_out_trade_no = _normalize_out_trade_no(out_trade_no)
        result = await session.execute(
            select(Order, Product)
            .join(Product, Product.id == Order.self_product_id)
            .where(Order.tenant_id == tenant_id)
            .where(Order.out_trade_no == normalized_out_trade_no)
            .with_for_update(of=Order)
            .limit(1)
        )
        row = result.first()
        if row is None:
            return None
        order, product = row
        provider_name = str(getattr(product, "external_source", "") or "").strip()
        source_key = str(getattr(product, "source_key", "") or "").strip()
        try:
            fulfillment = await self.fulfill_paid_order(
                session,
                order=order,
                product=product,
                settings=settings,
                attempt_source="manual",
            )
            return ExternalAutoFulfillmentAttemptResult(
                out_trade_no=fulfillment.out_trade_no,
                provider_name=fulfillment.provider_name,
                source_key=fulfillment.source_key,
                external_order_id=fulfillment.external_order_id,
                delivery_record_id=fulfillment.delivery_record_id,
                item_count=fulfillment.item_count,
                imported=fulfillment.imported,
                attempt_status=_manual_attempt_status(fulfillment),
            )
        except ValueError as exc:
            if not getattr(exc, "attempt_recorded", False):
                _add_attempt_record(
                    session,
                    order,
                    product,
                    attempt_source="manual",
                    status="failed",
                    exc=exc,
                )
            failure_recorded = await self._add_failure_audit(session, order, product, exc, auto=False)
            await session.flush()
            return ExternalAutoFulfillmentAttemptResult(
                out_trade_no=order.out_trade_no,
                provider_name=provider_name,
                source_key=source_key,
                external_order_id=_safe_optional_text(getattr(exc, "external_order_id", None), max_length=128),
                delivery_record_id=None,
                item_count=0,
                imported=False,
                attempt_status="failed",
                failure_stage=_safe_optional_text(getattr(exc, "stage", None), max_length=64) or "unknown",
                failure_category=_safe_optional_text(getattr(exc, "category", None), max_length=64)
                or HTTP_ERROR_CATEGORY_UNKNOWN,
                failure_retryable=bool(getattr(exc, "retryable", False)),
                upstream_status_code=_safe_optional_status_code(getattr(exc, "status_code", None)),
                failure_recorded=failure_recorded,
            )

    async def process_paid_external_orders(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        limit: int = 500,
    ) -> ExternalAutoFulfillmentBatchResult:
        if limit <= 0:
            raise ValueError("limit 必须大于 0")
        result = await session.execute(
            select(Order, Product)
            .join(Product, Product.id == Order.self_product_id)
            .outerjoin(DeliveryRecord, DeliveryRecord.order_id == Order.id)
            .where(Order.status == "paid")
            .where(Order.source_type == "self")
            .where(Order.locked_inventory_item_id.is_(None))
            .where(Product.external_source.is_not(None))
            .where(Product.external_id.is_not(None))
            .where(Product.delivery_type.in_(("card_pool", "card_fixed")))
            .where(DeliveryRecord.id.is_(None))
            .order_by(Order.paid_at.asc(), Order.created_at.asc())
            .with_for_update(of=Order, skip_locked=True)
            .limit(limit)
        )
        rows = list(result.all())
        imported_count = 0
        failed_count = 0
        checked_count = 0
        seen_order_ids: set[int] = set()
        delivery_record_ids: list[int] = []
        for order, product in rows:
            if order.id in seen_order_ids:
                continue
            seen_order_ids.add(order.id)
            checked_count += 1
            try:
                fulfillment = await self.fulfill_paid_order(
                    session,
                    order=order,
                    product=product,
                    settings=settings,
                )
            except ValueError as exc:
                failed_count += 1
                if not getattr(exc, "attempt_recorded", False):
                    _add_attempt_record(
                        session,
                        order,
                        product,
                        attempt_source="auto",
                        status="failed",
                        exc=exc,
                    )
                await self._add_failure_audit(session, order, product, exc)
                continue
            if fulfillment.delivery_record_id is not None:
                delivery_record_ids.append(fulfillment.delivery_record_id)
            if fulfillment.imported:
                imported_count += 1
        await session.flush()
        return ExternalAutoFulfillmentBatchResult(
            checked_count=checked_count,
            imported_count=imported_count,
            failed_count=failed_count,
            delivery_record_ids=delivery_record_ids,
        )

    @staticmethod
    async def _get_delivery_record(session: AsyncSession, order_id: int) -> DeliveryRecord | None:
        result = await session.execute(
            select(DeliveryRecord)
            .where(DeliveryRecord.order_id == order_id)
            .with_for_update()
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _validate_order_product(order: Order, product: Product) -> None:
        if order.status != "paid":
            raise ValueError("订单当前状态不能自动外部履约")
        if order.source_type != "self" or order.self_product_id is None:
            raise ValueError("仅支持自营订单自动外部履约")
        if order.self_product_id != product.id or product.tenant_id != order.tenant_id:
            raise ValueError("订单商品不存在或无权限")
        if order.locked_inventory_item_id is not None:
            raise ValueError("已有本地锁定库存的订单不能自动外部履约")
        if not uses_external_text_fulfillment(product):
            raise ValueError("订单商品不需要自动外部履约")

    @staticmethod
    async def _add_failure_audit(
        session: AsyncSession,
        order: Order,
        product: Product,
        exc: ValueError,
        *,
        auto: bool = True,
    ) -> bool:
        metadata = _failure_audit_metadata(order, product, exc, auto=auto)
        if await _has_same_latest_failure_fingerprint(session, order, metadata):
            return False
        session.add(
            AuditLog(
                tenant_id=order.tenant_id,
                actor_user_id=None,
                action="external_fulfillment.failed",
                target_type="order",
                target_id=str(order.id),
                metadata_json=metadata,
            )
        )
        return True


async def _has_same_latest_failure_fingerprint(
    session: AsyncSession,
    order: Order,
    metadata: dict[str, object],
) -> bool:
    fingerprint = metadata.get("failure_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        return False
    result = await session.execute(
        select(AuditLog)
        .where(AuditLog.tenant_id == order.tenant_id)
        .where(AuditLog.action == "external_fulfillment.failed")
        .where(AuditLog.target_type == "order")
        .where(AuditLog.target_id == str(order.id))
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(1)
    )
    latest = result.scalar_one_or_none()
    if latest is None:
        return False
    latest_metadata = latest.metadata_json or {}
    return latest_metadata.get("failure_fingerprint") == fingerprint


def _add_attempt_record(
    session: AsyncSession,
    order: Order,
    product: Product,
    *,
    attempt_source: str,
    status: str,
    connection_id: int | None = None,
    external_order_id: str | None = None,
    delivery_record_id: int | None = None,
    item_count: int = 0,
    imported: bool = False,
    exc: ValueError | None = None,
) -> ExternalFulfillmentAttempt:
    normalized_source = _normalize_attempt_source(attempt_source)
    if status not in EXTERNAL_FULFILLMENT_ATTEMPT_WRITE_STATUSES:
        raise ValueError("外部履约 attempt 状态无效")
    metadata = _failure_audit_metadata(order, product, exc, auto=normalized_source == "auto") if exc is not None else {}
    now = datetime.now(timezone.utc)
    attempt = ExternalFulfillmentAttempt(
        tenant_id=order.tenant_id,
        order_id=order.id,
        product_id=product.id,
        connection_id=None,
        delivery_record_id=None,
        out_trade_no=order.out_trade_no,
        provider_name=str(getattr(product, "external_source", "") or "").strip()[:64],
        source_key=str(getattr(product, "source_key", "") or "").strip()[:128],
        external_product_id=str(getattr(product, "external_id", "") or "").strip()[:128],
        external_order_id=None,
        attempt_source=normalized_source,
        status="started",
        imported=False,
        item_count=0,
        started_at=now,
        finished_at=now,
    )
    _mark_attempt_record(
        attempt,
        order,
        product,
        status=status,
        connection_id=connection_id or metadata.get("connection_id"),
        external_order_id=external_order_id or metadata.get("external_order_id"),
        delivery_record_id=delivery_record_id,
        item_count=item_count,
        imported=imported,
        exc=exc,
    )
    session.add(attempt)
    return attempt


def _mark_attempt_record(
    attempt: ExternalFulfillmentAttempt,
    order: Order,
    product: Product,
    *,
    status: str,
    connection_id: int | object | None = None,
    external_order_id: str | object | None = None,
    delivery_record_id: int | object | None = None,
    item_count: int = 0,
    imported: bool = False,
    exc: ValueError | None = None,
) -> None:
    if status not in EXTERNAL_FULFILLMENT_ATTEMPT_WRITE_STATUSES:
        raise ValueError("外部履约 attempt 状态无效")
    metadata = _failure_audit_metadata(order, product, exc, auto=attempt.attempt_source == "auto") if exc is not None else {}
    now = datetime.now(timezone.utc)
    attempt.status = status
    attempt.connection_id = _positive_int_or_none(connection_id or metadata.get("connection_id")) or attempt.connection_id
    attempt.external_order_id = (
        _safe_optional_text(external_order_id or metadata.get("external_order_id"), max_length=128)
        or attempt.external_order_id
    )
    attempt.delivery_record_id = _positive_int_or_none(delivery_record_id) or attempt.delivery_record_id
    attempt.imported = bool(imported)
    attempt.item_count = max(_positive_int_or_none(item_count) or 0, 0)
    if exc is not None:
        attempt.failure_reason = _safe_attempt_failure_reason(metadata.get("failure_reason"))
        attempt.failure_stage = _safe_optional_text(metadata.get("failure_stage"), max_length=64)
        attempt.failure_category = _safe_optional_text(metadata.get("failure_category"), max_length=64)
        attempt.failure_retryable = bool(metadata.get("failure_retryable"))
        attempt.upstream_status_code = _safe_optional_status_code(metadata.get("upstream_status_code"))
        attempt.failure_fingerprint = _safe_optional_text(metadata.get("failure_fingerprint"), max_length=64)
    elif status in {"succeeded", "already_delivered", "running"}:
        attempt.failure_reason = None
        attempt.failure_stage = None
        attempt.failure_category = None
        attempt.failure_retryable = None
        attempt.upstream_status_code = None
        attempt.failure_fingerprint = None
    if status in {"succeeded", "already_delivered", "failed"}:
        attempt.finished_at = now


def _fulfillment_error_from_external_source(
    exc: ExternalSourceError,
    *,
    stage: str,
    external_order_id: str | None = None,
    connection_id: int | None = None,
) -> ExternalAutoFulfillmentError:
    return ExternalAutoFulfillmentError(
        "外部履约失败",
        stage=stage,
        category=str(getattr(exc, "category", None) or HTTP_ERROR_CATEGORY_UNKNOWN),
        retryable=bool(getattr(exc, "retryable", False)),
        status_code=getattr(exc, "status_code", None),
        external_order_id=external_order_id,
        connection_id=connection_id,
    )


def _failure_audit_metadata(
    order: Order,
    product: Product,
    exc: ValueError,
    *,
    auto: bool = True,
) -> dict[str, object]:
    stage = getattr(exc, "stage", "unknown")
    category = getattr(exc, "category", HTTP_ERROR_CATEGORY_UNKNOWN)
    retryable = bool(getattr(exc, "retryable", False))
    status_code = getattr(exc, "status_code", None)
    external_order_id = getattr(exc, "external_order_id", None)
    connection_id = getattr(exc, "connection_id", None)
    reason = getattr(exc, "reason", "外部履约失败")
    external_product_id = str(getattr(product, "external_id", "") or "").strip()
    fingerprint_source = "|".join(
        [
            str(order.id),
            str(product.id),
            str(product.external_source or "").strip(),
            str(product.source_key or "").strip(),
            external_product_id,
            str(connection_id or ""),
            str(stage),
            str(category),
            str(status_code or ""),
            str(external_order_id or ""),
            "auto" if auto else "manual",
        ]
    )
    metadata: dict[str, object] = {
        "order_id": order.id,
        "out_trade_no": order.out_trade_no,
        "product_id": product.id,
        "provider_name": str(product.external_source or "").strip(),
        "source": str(product.source_key or "").strip(),
        "external_product_id": external_product_id[:128],
        "failure_reason": str(reason)[:300],
        "failure_stage": str(stage),
        "failure_category": str(category),
        "failure_retryable": retryable,
        "failure_fingerprint": hashlib.sha256(fingerprint_source.encode()).hexdigest(),
        "auto": auto,
    }
    if not auto:
        metadata["manual"] = True
    if isinstance(connection_id, int) and connection_id > 0:
        metadata["connection_id"] = connection_id
    if isinstance(status_code, int):
        metadata["upstream_status_code"] = status_code
    if external_order_id:
        metadata["external_order_id"] = str(external_order_id)[:128]
    return metadata


def _validate_tenant_id(tenant_id: int) -> None:
    if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id <= 0:
        raise ValueError("tenant_id 必须为正整数")


def _normalize_out_trade_no(out_trade_no: str) -> str:
    if not isinstance(out_trade_no, str):
        raise ValueError("out_trade_no 必须是字符串")
    normalized = out_trade_no.strip()
    if not normalized:
        raise ValueError("out_trade_no 不能为空")
    if len(normalized) > 96:
        raise ValueError("out_trade_no 长度不能超过 96")
    if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
        raise ValueError("out_trade_no 不能包含控制字符")
    return normalized


def _normalize_attempt_source(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("attempt_source 必须是字符串")
    normalized = value.strip()
    if normalized not in {"auto", "manual"}:
        raise ValueError("attempt_source 只支持 auto 或 manual")
    return normalized


def _manual_attempt_status(result: ExternalAutoFulfillmentResult) -> str:
    if result.imported:
        return "succeeded"
    if result.delivery_record_id is not None:
        return "already_delivered"
    return "failed"


def _safe_optional_text(value: object, *, max_length: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
        return None
    return normalized[:max_length]


def _safe_optional_status_code(value: object) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        status_code = int(value)
    except (TypeError, ValueError):
        return None
    return status_code if 100 <= status_code <= 599 else None


def _positive_int_or_none(value: object) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _safe_attempt_failure_reason(value: object) -> Optional[str]:
    reason = _safe_optional_text(value, max_length=300)
    if reason is None:
        return None
    lowered = reason.lower()
    if any(marker in lowered for marker in ("api_key", "authorization", "cookie", "credential", "password", "payload", "secret", "token")):
        return "外部履约失败"
    return reason
