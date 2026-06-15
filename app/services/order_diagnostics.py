from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.external_sources import ExternalFulfillmentAttempt
from app.db.models.orders import DeliveryRecord, Order, Payment, PaymentCallback, Trc20DirectTransfer
from app.db.models.products import Product
from app.services.external_sources.failures import SENSITIVE_FAILURE_VALUE_MARKERS
from app.services.payments.configs import USDT_TRC20_DIRECT_PROVIDER
from app.services.payments.failures import SENSITIVE_PAYMENT_FAILURE_VALUE_MARKERS


MAX_DIAGNOSTIC_PAYMENTS = 10
MAX_DIAGNOSTIC_CALLBACKS = 10


@dataclass(frozen=True)
class OrderPaymentDiagnostic:
    payment_id: int
    provider: str
    status: str
    amount: Decimal
    currency: str
    has_payment_url: bool
    created_at: datetime
    paid_at: Optional[datetime]


@dataclass(frozen=True)
class OrderPaymentCallbackDiagnostic:
    callback_id: int
    provider: str
    process_status: str
    failure_reason: str
    created_at: datetime
    processed_at: Optional[datetime]


@dataclass(frozen=True)
class OrderDeliveryDiagnostic:
    delivery_record_id: int
    delivery_type: str
    status: str
    failure_reason: Optional[str]
    has_inventory_item: bool
    has_uploaded_file: bool
    has_telegram_chat: bool
    created_at: datetime
    updated_at: datetime
    sent_at: Optional[datetime]


@dataclass(frozen=True)
class OrderExternalFulfillmentDiagnostic:
    expected: bool
    attempt_count: int = 0
    latest_attempt_status: Optional[str] = None
    latest_attempt_source: Optional[str] = None
    latest_attempt_at: Optional[datetime] = None
    latest_failure_stage: Optional[str] = None
    latest_failure_category: Optional[str] = None
    latest_failure_retryable: Optional[bool] = None
    latest_upstream_status_code: Optional[int] = None
    latest_item_count: int = 0
    latest_delivery_record_linked: bool = False


@dataclass(frozen=True)
class OrderTrc20DirectDiagnostic:
    expected: bool
    transfer_count: int = 0
    latest_match_status: Optional[str] = None
    latest_confirmations: Optional[int] = None
    latest_matched_at: Optional[datetime] = None
    latest_amount: Optional[Decimal] = None


@dataclass(frozen=True)
class OrderDiagnosticsSummary:
    order_id: int
    out_trade_no: str
    source_type: str
    status: str
    payment_mode: str
    payment_provider: Optional[str]
    amount: Decimal
    currency: str
    created_at: datetime
    expires_at: datetime
    paid_at: Optional[datetime]
    delivered_at: Optional[datetime]
    payment_count: int
    callback_count: int
    callback_status_counts: dict[str, int]
    payments: list[OrderPaymentDiagnostic]
    callbacks: list[OrderPaymentCallbackDiagnostic]
    delivery: Optional[OrderDeliveryDiagnostic]
    external_fulfillment: OrderExternalFulfillmentDiagnostic
    trc20_direct: OrderTrc20DirectDiagnostic = field(
        default_factory=lambda: OrderTrc20DirectDiagnostic(expected=False)
    )


class OrderDiagnosticsService:
    async def get_summary(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        out_trade_no: str,
    ) -> Optional[OrderDiagnosticsSummary]:
        normalized_out_trade_no = self._normalize_out_trade_no(out_trade_no)
        order = await self._get_order(session, tenant_id=tenant_id, out_trade_no=normalized_out_trade_no)
        if order is None:
            return None

        payments = await self._list_payments(session, tenant_id=tenant_id, order_id=int(order.id))
        callbacks = await self._list_callbacks(session, out_trade_no=order.out_trade_no)
        delivery = await self._get_delivery(session, tenant_id=tenant_id, order_id=int(order.id))
        product = await self._get_self_product(session, tenant_id=tenant_id, order=order)
        external_fulfillment = await self._external_fulfillment_summary(
            session,
            tenant_id=tenant_id,
            order=order,
            product=product,
        )
        trc20_direct = await self._trc20_direct_summary(
            session,
            tenant_id=tenant_id,
            order=order,
        )
        return OrderDiagnosticsSummary(
            order_id=int(order.id),
            out_trade_no=order.out_trade_no,
            source_type=self._safe_text(order.source_type, max_length=32) or "unknown",
            status=self._safe_text(order.status, max_length=32) or "unknown",
            payment_mode=self._safe_text(order.payment_mode, max_length=32) or "unknown",
            payment_provider=self._safe_text(order.payment_provider, max_length=64),
            amount=order.amount,
            currency=self._safe_text(order.currency, max_length=16) or "USDT",
            created_at=order.created_at,
            expires_at=order.expires_at,
            paid_at=order.paid_at,
            delivered_at=order.delivered_at,
            payment_count=len(payments),
            callback_count=len(callbacks),
            callback_status_counts=self._callback_status_counts(callbacks),
            payments=[self._payment_summary(payment) for payment in payments[:MAX_DIAGNOSTIC_PAYMENTS]],
            callbacks=[self._callback_summary(callback) for callback in callbacks[:MAX_DIAGNOSTIC_CALLBACKS]],
            delivery=self._delivery_summary(delivery) if delivery is not None else None,
            external_fulfillment=external_fulfillment,
            trc20_direct=trc20_direct,
        )

    async def _get_order(self, session: AsyncSession, *, tenant_id: int, out_trade_no: str) -> Optional[Order]:
        result = await session.execute(
            select(Order)
            .where(Order.tenant_id == tenant_id)
            .where(Order.out_trade_no == out_trade_no)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _list_payments(self, session: AsyncSession, *, tenant_id: int, order_id: int) -> list[Payment]:
        result = await session.execute(
            select(Payment)
            .where(Payment.tenant_id == tenant_id)
            .where(Payment.order_id == order_id)
            .order_by(Payment.created_at.desc(), Payment.id.desc())
            .limit(MAX_DIAGNOSTIC_PAYMENTS)
        )
        return list(result.scalars().all())

    async def _list_callbacks(self, session: AsyncSession, *, out_trade_no: str) -> list[PaymentCallback]:
        result = await session.execute(
            select(PaymentCallback)
            .where(PaymentCallback.out_trade_no == out_trade_no)
            .order_by(PaymentCallback.created_at.desc(), PaymentCallback.id.desc())
            .limit(MAX_DIAGNOSTIC_CALLBACKS)
        )
        return list(result.scalars().all())

    async def _get_delivery(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        order_id: int,
    ) -> Optional[DeliveryRecord]:
        result = await session.execute(
            select(DeliveryRecord)
            .where(DeliveryRecord.tenant_id == tenant_id)
            .where(DeliveryRecord.order_id == order_id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _get_self_product(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        order: Order,
    ) -> Optional[Product]:
        if order.source_type != "self" or order.self_product_id is None:
            return None
        result = await session.execute(
            select(Product)
            .where(Product.tenant_id == tenant_id)
            .where(Product.id == order.self_product_id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    def _payment_summary(self, payment: Payment) -> OrderPaymentDiagnostic:
        return OrderPaymentDiagnostic(
            payment_id=int(payment.id),
            provider=self._safe_text(payment.provider, max_length=64) or "unknown",
            status=self._safe_text(payment.status, max_length=32) or "unknown",
            amount=payment.amount,
            currency=self._safe_text(payment.currency, max_length=16) or "USDT",
            has_payment_url=bool(payment.payment_url),
            created_at=payment.created_at,
            paid_at=payment.paid_at,
        )

    def _callback_summary(self, callback: PaymentCallback) -> OrderPaymentCallbackDiagnostic:
        return OrderPaymentCallbackDiagnostic(
            callback_id=int(callback.id),
            provider=self._safe_text(callback.provider, max_length=64) or "unknown",
            process_status=self._safe_text(callback.process_status, max_length=32) or "unknown",
            failure_reason=self._safe_payment_failure_reason(callback.error_message),
            created_at=callback.created_at,
            processed_at=callback.processed_at,
        )

    def _delivery_summary(self, delivery: DeliveryRecord) -> OrderDeliveryDiagnostic:
        return OrderDeliveryDiagnostic(
            delivery_record_id=int(delivery.id),
            delivery_type=self._safe_text(delivery.delivery_type, max_length=32) or "unknown",
            status=self._safe_text(delivery.status, max_length=32) or "unknown",
            failure_reason=self._safe_optional_failure_reason(delivery.error_message),
            has_inventory_item=delivery.inventory_item_id is not None,
            has_uploaded_file=delivery.uploaded_file_id is not None,
            has_telegram_chat=delivery.telegram_chat_id is not None,
            created_at=delivery.created_at,
            updated_at=delivery.updated_at,
            sent_at=delivery.sent_at,
        )

    async def _external_fulfillment_summary(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        order: Order,
        product: Optional[Product],
    ) -> OrderExternalFulfillmentDiagnostic:
        if product is None or not product.external_source or not product.external_id:
            return OrderExternalFulfillmentDiagnostic(expected=False)
        attempt_count = await self._count_external_fulfillment_attempts(
            session,
            tenant_id=tenant_id,
            order_id=int(order.id),
        )
        if attempt_count <= 0:
            return OrderExternalFulfillmentDiagnostic(expected=True)
        latest_attempt = await self._get_latest_external_fulfillment_attempt(
            session,
            tenant_id=tenant_id,
            order_id=int(order.id),
        )
        if latest_attempt is None:
            return OrderExternalFulfillmentDiagnostic(expected=True, attempt_count=attempt_count)
        return OrderExternalFulfillmentDiagnostic(
            expected=True,
            attempt_count=attempt_count,
            latest_attempt_status=self._safe_attempt_choice(
                latest_attempt.status,
                allowed={"started", "running", "succeeded", "already_delivered", "failed", "imported"},
                max_length=32,
            ),
            latest_attempt_source=self._safe_attempt_choice(
                latest_attempt.attempt_source,
                allowed={"auto", "manual"},
                max_length=16,
            ),
            latest_attempt_at=latest_attempt.created_at if isinstance(latest_attempt.created_at, datetime) else None,
            latest_failure_stage=self._safe_external_attempt_text(latest_attempt.failure_stage, max_length=64),
            latest_failure_category=self._safe_external_attempt_text(latest_attempt.failure_category, max_length=64),
            latest_failure_retryable=(
                latest_attempt.failure_retryable if isinstance(latest_attempt.failure_retryable, bool) else None
            ),
            latest_upstream_status_code=self._safe_upstream_status_code(latest_attempt.upstream_status_code),
            latest_item_count=max(self._optional_int(latest_attempt.item_count) or 0, 0),
            latest_delivery_record_linked=latest_attempt.delivery_record_id is not None,
        )

    async def _trc20_direct_summary(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        order: Order,
    ) -> OrderTrc20DirectDiagnostic:
        if order.payment_provider != USDT_TRC20_DIRECT_PROVIDER:
            return OrderTrc20DirectDiagnostic(expected=False)
        transfer_count = await self._count_trc20_direct_transfers(
            session,
            tenant_id=tenant_id,
            order=order,
        )
        if transfer_count <= 0:
            return OrderTrc20DirectDiagnostic(expected=True)
        latest_transfer = await self._get_latest_trc20_direct_transfer(
            session,
            tenant_id=tenant_id,
            order=order,
        )
        if latest_transfer is None:
            return OrderTrc20DirectDiagnostic(expected=True, transfer_count=transfer_count)
        return OrderTrc20DirectDiagnostic(
            expected=True,
            transfer_count=transfer_count,
            latest_match_status=self._safe_attempt_choice(
                latest_transfer.match_status,
                allowed={
                    "recorded",
                    "not_confirmed",
                    "duplicate_tx",
                    "no_candidate",
                    "address_mismatch",
                    "amount_mismatch",
                    "outside_time_window",
                    "ambiguous",
                    "matched",
                    "invalid",
                },
                max_length=32,
            ),
            latest_confirmations=max(self._optional_int(latest_transfer.confirmations) or 0, 0),
            latest_matched_at=latest_transfer.matched_at if isinstance(latest_transfer.matched_at, datetime) else None,
            latest_amount=latest_transfer.amount if isinstance(latest_transfer.amount, Decimal) else None,
        )

    async def _count_trc20_direct_transfers(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        order: Order,
    ) -> int:
        result = await session.execute(
            select(func.count())
            .select_from(Trc20DirectTransfer)
            .where(Trc20DirectTransfer.tenant_id == tenant_id)
            .where(
                or_(
                    Trc20DirectTransfer.order_id == int(order.id),
                    Trc20DirectTransfer.out_trade_no == order.out_trade_no,
                )
            )
        )
        return max(self._optional_int(result.scalar_one_or_none()) or 0, 0)

    async def _get_latest_trc20_direct_transfer(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        order: Order,
    ) -> Optional[Trc20DirectTransfer]:
        result = await session.execute(
            select(Trc20DirectTransfer)
            .where(Trc20DirectTransfer.tenant_id == tenant_id)
            .where(
                or_(
                    Trc20DirectTransfer.order_id == int(order.id),
                    Trc20DirectTransfer.out_trade_no == order.out_trade_no,
                )
            )
            .order_by(Trc20DirectTransfer.created_at.desc(), Trc20DirectTransfer.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _count_external_fulfillment_attempts(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        order_id: int,
    ) -> int:
        result = await session.execute(
            select(func.count())
            .select_from(ExternalFulfillmentAttempt)
            .where(ExternalFulfillmentAttempt.tenant_id == tenant_id)
            .where(ExternalFulfillmentAttempt.order_id == order_id)
        )
        return max(self._optional_int(result.scalar_one_or_none()) or 0, 0)

    async def _get_latest_external_fulfillment_attempt(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        order_id: int,
    ) -> Optional[ExternalFulfillmentAttempt]:
        result = await session.execute(
            select(ExternalFulfillmentAttempt)
            .where(ExternalFulfillmentAttempt.tenant_id == tenant_id)
            .where(ExternalFulfillmentAttempt.order_id == order_id)
            .order_by(ExternalFulfillmentAttempt.created_at.desc(), ExternalFulfillmentAttempt.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    def _callback_status_counts(self, callbacks: list[PaymentCallback]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for callback in callbacks:
            status = self._safe_text(callback.process_status, max_length=32) or "unknown"
            counts[status] = counts.get(status, 0) + 1
        return counts

    @staticmethod
    def _normalize_out_trade_no(value: str) -> str:
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

    def _safe_optional_failure_reason(self, value: object) -> Optional[str]:
        if value is None:
            return None
        return self._safe_failure_reason(value)

    def _safe_failure_reason(self, value: object) -> str:
        reason = self._safe_text(value, max_length=300) or "未记录失败原因"
        normalized = reason.lower()
        if any(marker in normalized for marker in SENSITIVE_PAYMENT_FAILURE_VALUE_MARKERS):
            return "未记录失败原因"
        return reason

    def _safe_payment_failure_reason(self, value: object) -> str:
        reason = self._safe_text(value, max_length=300) or "支付回调未处理成功"
        normalized = reason.lower()
        if any(marker in normalized for marker in SENSITIVE_PAYMENT_FAILURE_VALUE_MARKERS):
            return "支付回调未处理成功"
        return reason

    def _safe_external_attempt_text(self, value: object, *, max_length: int) -> Optional[str]:
        text = self._safe_text(value, max_length=max_length)
        if text is None:
            return None
        normalized = text.lower()
        if any(marker in normalized for marker in SENSITIVE_FAILURE_VALUE_MARKERS):
            return None
        return text

    def _safe_attempt_choice(self, value: object, *, allowed: set[str], max_length: int) -> Optional[str]:
        text = self._safe_external_attempt_text(value, max_length=max_length)
        if text not in allowed:
            return None
        return text

    @staticmethod
    def _optional_int(value: object) -> Optional[int]:
        if isinstance(value, bool):
            return None
        if not isinstance(value, int):
            return None
        return value

    def _safe_upstream_status_code(self, value: object) -> Optional[int]:
        status_code = self._optional_int(value)
        if status_code is None or status_code < 100 or status_code > 599:
            return None
        return status_code

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
