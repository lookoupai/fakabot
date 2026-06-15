from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.orders import DeliveryRecord, Order, Payment, PaymentCallback
from app.db.models.products import InventoryItem, Product, UploadedFile
from app.db.models.tenants import Tenant
from app.services.external_sources.fulfillment import uses_external_text_fulfillment
from app.services.inventory import InventoryService
from app.services.ledger import LedgerService
from app.services.payments.base import PaymentOrderRequest, PaymentProvider
from app.services.payments.configs import (
    EPAY_COMPATIBLE_PROVIDER,
    EPUSDT_PROVIDER,
    LEMZF_PROVIDER,
    TOKEN188_PROVIDER,
    USDT_TRC20_DIRECT_PROVIDER,
    PaymentConfigService,
    ResolvedPaymentConfig,
    Trc20DirectConfig,
    normalize_payment_provider,
)
from app.services.payments.epay_compatible import EpayCompatibleConfig, EpayCompatibleProvider, LemzfProvider
from app.services.payments.epusdt import EpusdtGmpayProvider, payload_hash
from app.services.payments.token188 import Token188Config, Token188Provider
from app.services.payments.trc20_direct import Trc20DirectPaymentProvider


class PaymentUnavailableError(RuntimeError):
    pass


PAYMENT_ALLOWED_TENANT_STATUSES = {"trial", "active", "grace"}


@dataclass
class CreatedPayment:
    provider: str
    payment_url: str
    out_trade_no: str
    amount: Decimal
    currency: str


@dataclass
class PaymentCallbackProcessResult:
    ok: bool
    message: str
    delivery_record_id: Optional[int] = None


@dataclass
class DeliveryInstruction:
    delivery_record_id: int
    order_id: int
    tenant_id: int
    buyer_telegram_user_id: int
    delivery_type: str
    out_trade_no: str
    encrypted_content: Optional[str] = None
    uploaded_file_id: Optional[int] = None
    uploaded_file_tenant_id: Optional[int] = None
    telegram_chat_id: Optional[int] = None


@dataclass
class PaymentReconcileResult:
    checked_count: int
    changed_count: int
    delivery_record_ids: List[int]


@dataclass
class ResolvedPaymentProvider:
    scope_type: str
    provider: PaymentProvider


class PaymentService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def create_payment_for_order(
        self,
        session: AsyncSession,
        order_id: int,
        provider_name: Optional[str] = None,
    ) -> CreatedPayment:
        result = await session.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if order is None:
            raise ValueError("订单不存在")
        if order.status != "pending":
            raise ValueError("订单当前状态不能发起支付")
        if order.expires_at <= datetime.now(timezone.utc):
            await InventoryService().release_order_locks(session, self._inventory_tenant_id(order), order.id)
            order.status = "expired"
            order.locked_inventory_item_id = None
            await session.flush()
            raise ValueError("订单已过期，不能发起支付")
        await self._ensure_order_tenant_can_create_payment(session, order)

        resolved_provider = await self._resolve_payment_provider(session, order, provider_name=provider_name)
        if resolved_provider is None:
            raise PaymentUnavailableError(self._payment_unavailable_message(order))
        provider = resolved_provider.provider

        existing_payment = await self._get_payment(session, order.id, provider.provider)
        if existing_payment is not None and existing_payment.payment_url:
            order.payment_provider = existing_payment.provider
            order.payment_mode = self._effective_payment_mode(order, resolved_provider.scope_type)
            await session.flush()
            return CreatedPayment(
                provider=existing_payment.provider,
                payment_url=existing_payment.payment_url,
                out_trade_no=order.out_trade_no,
                amount=existing_payment.amount,
                currency=existing_payment.currency,
            )

        notify_url = f"{self._settings.public_base_url}/payments/callback/{provider.provider}"
        request = PaymentOrderRequest(
            out_trade_no=order.out_trade_no,
            amount=order.amount,
            currency=order.currency,
            notify_url=notify_url,
        )
        created = await provider.create_order(request)
        if not created.payment_url:
            raise PaymentUnavailableError("支付网关未返回支付链接")

        payment = existing_payment
        if payment is None:
            payment = Payment(
                order_id=order.id,
                tenant_id=order.tenant_id,
                provider=created.provider,
                amount=order.amount,
                currency=order.currency,
                status="pending",
                idempotency_key=f"{created.provider}:{order.out_trade_no}",
                raw_request_hash=payload_hash(
                    {
                        "out_trade_no": order.out_trade_no,
                        "amount": str(order.amount),
                        "currency": order.currency,
                        "notify_url": notify_url,
                    }
                ),
            )
            session.add(payment)

        payment.provider_trade_no = created.provider_trade_no
        payment.payment_url = created.payment_url
        order.payment_provider = created.provider
        order.payment_mode = self._payment_mode_from_scope(resolved_provider.scope_type)
        await session.flush()
        return CreatedPayment(
            provider=created.provider,
            payment_url=created.payment_url,
            out_trade_no=order.out_trade_no,
            amount=order.amount,
            currency=order.currency,
        )

    async def process_epusdt_callback(
        self,
        session: AsyncSession,
        payload: Dict[str, Any],
    ) -> PaymentCallbackProcessResult:
        return await self.process_payment_callback(session, EPUSDT_PROVIDER, payload)

    async def process_payment_callback(
        self,
        session: AsyncSession,
        provider_name: str,
        payload: Dict[str, Any],
    ) -> PaymentCallbackProcessResult:
        provider_name = normalize_payment_provider(provider_name)
        if provider_name == USDT_TRC20_DIRECT_PROVIDER:
            raise PaymentUnavailableError("TRC20 直付不支持公网回调")
        unsigned_out_trade_no = self._extract_callback_out_trade_no(provider_name, payload)
        result = await session.execute(select(Order).where(Order.out_trade_no == unsigned_out_trade_no))
        callback_order = result.scalar_one_or_none()
        if callback_order is None:
            raise ValueError("回调订单不存在")
        resolved_provider = await self._resolve_payment_provider(
            session,
            callback_order,
            provider_name=provider_name,
        )
        if resolved_provider is None:
            raise PaymentUnavailableError(self._payment_unavailable_message(callback_order))
        verified = resolved_provider.provider.verify_callback(payload)
        now = datetime.now(timezone.utc)
        result = await session.execute(
            select(Order)
            .where(Order.out_trade_no == verified.out_trade_no)
            .with_for_update()
        )
        order = result.scalar_one_or_none()
        callback = await self._get_callback(session, verified.provider, verified.payload_hash)
        if callback is not None and callback.process_status == "processed":
            await self._backfill_settlement_for_processed_callback(
                session,
                verified.out_trade_no,
                resolved_provider.scope_type,
            )
            delivery_id = await self._find_deliverable_record_id(session, verified.out_trade_no)
            return PaymentCallbackProcessResult(ok=True, message="duplicate", delivery_record_id=delivery_id)
        if callback is None:
            try:
                async with session.begin_nested():
                    callback = PaymentCallback(
                        provider=verified.provider,
                        out_trade_no=verified.out_trade_no,
                        provider_trade_no=verified.provider_trade_no,
                        payload_hash=verified.payload_hash,
                        payload_json=verified.raw_payload,
                        process_status="pending",
                    )
                    session.add(callback)
                    await session.flush()
            except IntegrityError:
                callback = await self._get_callback(session, verified.provider, verified.payload_hash)
                if callback is None:
                    raise
                if callback.process_status == "processed":
                    await self._backfill_settlement_for_processed_callback(
                        session,
                        verified.out_trade_no,
                        resolved_provider.scope_type,
                    )
                    delivery_id = await self._find_deliverable_record_id(session, verified.out_trade_no)
                    return PaymentCallbackProcessResult(ok=True, message="duplicate", delivery_record_id=delivery_id)

        if not verified.paid:
            callback.process_status = "ignored"
            callback.processed_at = now
            await session.flush()
            return PaymentCallbackProcessResult(ok=True, message="unpaid")

        if order is None:
            callback.process_status = "failed"
            callback.error_message = "订单不存在"
            callback.processed_at = now
            await session.flush()
            return PaymentCallbackProcessResult(ok=False, message="order_not_found")

        if order.status in {"expired", "cancelled", "refunded"}:
            callback.process_status = "failed"
            callback.error_message = "订单已过期或不可支付"
            callback.processed_at = now
            await session.flush()
            return PaymentCallbackProcessResult(ok=False, message="order_expired")
        if order.status == "pending" and order.expires_at <= now:
            await InventoryService().release_order_locks(session, self._inventory_tenant_id(order), order.id)
            order.status = "expired"
            order.locked_inventory_item_id = None
            callback.process_status = "failed"
            callback.error_message = "订单已过期或不可支付"
            callback.processed_at = now
            await session.flush()
            return PaymentCallbackProcessResult(ok=False, message="order_expired")

        payment = await self._get_payment(session, order.id, verified.provider, for_update=True)
        if self._order_already_paid(order, payment):
            if payment is not None and payment.status == "paid" and order.status == "pending":
                order.status = "paid"
                order.payment_provider = verified.provider
                order.paid_at = order.paid_at or getattr(payment, "paid_at", None) or now
            order.payment_mode = self._effective_payment_mode(order, resolved_provider.scope_type)
            delivery_id = await self._find_deliverable_record_id(session, verified.out_trade_no)
            if delivery_id is None and order.status == "paid":
                try:
                    await self._record_platform_settlement_if_needed(session, order)
                    delivery_id = await self._ensure_delivery_record(session, order)
                except ValueError as exc:
                    callback.process_status = "failed"
                    callback.error_message = str(exc)
                    callback.processed_at = now
                    await session.flush()
                    return PaymentCallbackProcessResult(ok=False, message="delivery_failed")
                callback.process_status = "processed"
                callback.error_message = None
                callback.processed_at = now
                await session.flush()
                return PaymentCallbackProcessResult(ok=True, message="processed", delivery_record_id=delivery_id)
            callback.process_status = "processed"
            callback.error_message = None
            callback.processed_at = now
            await session.flush()
            return PaymentCallbackProcessResult(ok=True, message="duplicate", delivery_record_id=delivery_id)

        if payment is None:
            payment = Payment(
                order_id=order.id,
                tenant_id=order.tenant_id,
                provider=verified.provider,
                provider_trade_no=verified.provider_trade_no,
                amount=order.amount,
                currency=order.currency,
                status="paid",
                idempotency_key=f"{verified.provider}:{order.out_trade_no}",
                paid_at=now,
            )
            session.add(payment)
        else:
            payment.status = "paid"
            payment.provider_trade_no = verified.provider_trade_no or payment.provider_trade_no
            payment.paid_at = payment.paid_at or now

        if order.status == "pending":
            order.status = "paid"
            order.payment_provider = verified.provider
            order.paid_at = now
        order.payment_mode = self._effective_payment_mode(order, resolved_provider.scope_type)

        try:
            await self._record_platform_settlement_if_needed(session, order)
            delivery_id = await self._ensure_delivery_record(session, order)
        except ValueError as exc:
            callback.process_status = "failed"
            callback.error_message = str(exc)
            callback.processed_at = now
            await session.flush()
            return PaymentCallbackProcessResult(ok=False, message="delivery_failed")
        callback.process_status = "processed"
        callback.error_message = None
        callback.processed_at = now
        await session.flush()
        return PaymentCallbackProcessResult(ok=True, message="processed", delivery_record_id=delivery_id)

    async def claim_delivery(self, session: AsyncSession, delivery_record_id: int) -> Optional[DeliveryInstruction]:
        result = await session.execute(
            select(DeliveryRecord)
            .where(DeliveryRecord.id == delivery_record_id)
            .where(DeliveryRecord.status.in_(("pending", "failed")))
            .with_for_update()
        )
        delivery = result.scalar_one_or_none()
        if delivery is None:
            return None

        order = await session.get(Order, delivery.order_id)
        if order is None:
            delivery.status = "failed"
            delivery.error_message = "发货订单不存在"
            await session.flush()
            return None

        encrypted_content = None
        if delivery.delivery_type in {"card_pool", "card_fixed"}:
            if delivery.inventory_item_id is None:
                delivery.status = "failed"
                delivery.error_message = "发货库存不存在"
                await session.flush()
                return None
            item = await session.get(InventoryItem, delivery.inventory_item_id)
            if item is None:
                delivery.status = "failed"
                delivery.error_message = "发货库存不存在"
                await session.flush()
                return None
            if item.tenant_id != self._inventory_tenant_id(order):
                delivery.status = "failed"
                delivery.error_message = "发货库存租户不匹配"
                await session.flush()
                return None
            encrypted_content = item.content_encrypted
        elif delivery.delivery_type == "file_download":
            if delivery.uploaded_file_id is None:
                delivery.status = "failed"
                delivery.error_message = "发货文件不存在"
                await session.flush()
                return None
            uploaded_file = await session.get(UploadedFile, delivery.uploaded_file_id)
            if uploaded_file is None or uploaded_file.status != "active":
                delivery.status = "failed"
                delivery.error_message = "发货文件不存在"
                await session.flush()
                return None
        elif delivery.delivery_type == "telegram_invite" and delivery.telegram_chat_id is None:
            delivery.status = "failed"
            delivery.error_message = "发货群不存在"
            await session.flush()
            return None

        delivery.status = "sending"
        delivery.error_message = None
        await session.flush()
        return DeliveryInstruction(
            delivery_record_id=delivery.id,
            order_id=delivery.order_id,
            tenant_id=delivery.tenant_id,
            buyer_telegram_user_id=delivery.buyer_telegram_user_id,
            delivery_type=delivery.delivery_type,
            out_trade_no=order.out_trade_no,
            encrypted_content=encrypted_content,
            uploaded_file_id=delivery.uploaded_file_id,
            uploaded_file_tenant_id=uploaded_file.tenant_id if delivery.delivery_type == "file_download" else None,
            telegram_chat_id=delivery.telegram_chat_id,
        )

    async def list_pending_delivery_record_ids(self, session: AsyncSession, limit: int = 100) -> List[int]:
        if limit <= 0:
            raise ValueError("limit 必须大于 0")
        result = await session.execute(
            select(DeliveryRecord.id)
            .where(DeliveryRecord.status == "pending")
            .order_by(DeliveryRecord.created_at.asc())
            .limit(limit)
        )
        return [int(delivery_id) for delivery_id in result.scalars().all()]

    async def recover_stale_sending_deliveries(
        self,
        session: AsyncSession,
        *,
        timeout_seconds: int,
        limit: int = 100,
        now: Optional[datetime] = None,
    ) -> int:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0")
        if limit <= 0:
            raise ValueError("limit 必须大于 0")
        current_time = now or datetime.now(timezone.utc)
        cutoff = current_time - timedelta(seconds=timeout_seconds)
        result = await session.execute(
            select(DeliveryRecord)
            .where(DeliveryRecord.status == "sending")
            .where(DeliveryRecord.updated_at <= cutoff)
            .order_by(DeliveryRecord.updated_at.asc(), DeliveryRecord.id.asc())
            .limit(limit)
            .with_for_update()
        )
        deliveries = list(result.scalars().all())
        for delivery in deliveries:
            delivery.status = "failed"
            delivery.error_message = "发货发送超时，已标记为可手动重试"
        if deliveries:
            await session.flush()
        return len(deliveries)

    async def mark_delivery_sent(self, session: AsyncSession, delivery_record_id: int) -> None:
        now = datetime.now(timezone.utc)
        delivery = await session.get(DeliveryRecord, delivery_record_id)
        if delivery is None:
            return
        order = await session.get(Order, delivery.order_id)
        delivery.status = "sent"
        delivery.error_message = None
        delivery.sent_at = now
        if order is not None and order.status in {"paid", "delivered"}:
            order.status = "delivered"
            order.delivered_at = order.delivered_at or now
        await session.flush()

    async def mark_delivery_failed(self, session: AsyncSession, delivery_record_id: int, error_message: str) -> None:
        delivery = await session.get(DeliveryRecord, delivery_record_id)
        if delivery is None:
            return
        delivery.status = "failed"
        delivery.error_message = error_message[:1000]
        await session.flush()

    async def get_retryable_delivery_id(
        self,
        session: AsyncSession,
        tenant_id: int,
        out_trade_no: str,
    ) -> Optional[int]:
        result = await session.execute(
            select(DeliveryRecord.id)
            .join(Order, Order.id == DeliveryRecord.order_id)
            .where(Order.tenant_id == tenant_id)
            .where(Order.out_trade_no == out_trade_no)
            .where(DeliveryRecord.status.in_(("pending", "failed")))
            .order_by(DeliveryRecord.created_at.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def reconcile_pending_payments(
        self,
        session: AsyncSession,
        tenant_id: Optional[int] = None,
        limit: int = 100,
    ) -> PaymentReconcileResult:
        query = (
            select(Payment, Order)
            .join(Order, Order.id == Payment.order_id)
            .where(Payment.provider == EpusdtGmpayProvider.provider)
            .where(Payment.status == "pending")
            .where(Payment.provider_trade_no.is_not(None))
            .where(Order.status == "pending")
            .order_by(Payment.created_at.asc())
            .limit(limit)
        )
        if tenant_id is not None:
            query = query.where(Order.tenant_id == tenant_id)

        rows = list((await session.execute(query)).all())
        changed_count = 0
        delivery_record_ids: List[int] = []
        now = datetime.now(timezone.utc)
        for payment, order in rows:
            resolved_provider = await self._resolve_epusdt_provider(session, order)
            if resolved_provider is None or not payment.provider_trade_no:
                continue
            query_result = await resolved_provider.provider.query_order(payment.provider_trade_no)
            if query_result.paid:
                payment.status = "paid"
                payment.paid_at = payment.paid_at or now
                order.status = "paid"
                order.payment_provider = payment.provider
                order.paid_at = order.paid_at or now
                order.payment_mode = self._effective_payment_mode(order, resolved_provider.scope_type)
                await self._record_platform_settlement_if_needed(session, order)
                delivery_id = await self._ensure_delivery_record(session, order)
                if delivery_id is not None:
                    delivery_record_ids.append(delivery_id)
                changed_count += 1
            elif query_result.expired:
                await InventoryService().release_order_locks(session, self._inventory_tenant_id(order), order.id)
                payment.status = "expired"
                order.status = "expired"
                order.locked_inventory_item_id = None
                changed_count += 1
        await session.flush()
        return PaymentReconcileResult(
            checked_count=len(rows),
            changed_count=changed_count,
            delivery_record_ids=delivery_record_ids,
        )

    async def _create_epusdt_provider(self, session: AsyncSession, tenant_id: int) -> Optional[ResolvedPaymentProvider]:
        resolved_config = await PaymentConfigService().resolve_epusdt_config_for_tenant(
            session,
            self._settings,
            tenant_id,
        )
        if resolved_config is None:
            return None
        return ResolvedPaymentProvider(
            scope_type=resolved_config.scope_type,
            provider=EpusdtGmpayProvider(resolved_config.config),
        )

    async def _resolve_payment_provider(
        self,
        session: AsyncSession,
        order: Order,
        provider_name: Optional[str] = None,
    ) -> Optional[ResolvedPaymentProvider]:
        normalized_provider = normalize_payment_provider(provider_name) if provider_name else None
        if order.source_type in {"reseller", "subscription"}:
            if normalized_provider not in {None, EPUSDT_PROVIDER}:
                return None
            return await self._resolve_epusdt_provider(session, order)

        if normalized_provider == EPUSDT_PROVIDER:
            return await self._resolve_epusdt_provider(session, order)
        if normalized_provider == USDT_TRC20_DIRECT_PROVIDER:
            resolved_config = await PaymentConfigService().resolve_tenant_payment_config_for_provider(
                session,
                self._settings,
                order.tenant_id,
                normalized_provider,
            )
            return self._provider_from_resolved_config(resolved_config)
        if normalized_provider is not None:
            resolved_config = await PaymentConfigService().resolve_tenant_payment_config_for_provider(
                session,
                self._settings,
                order.tenant_id,
                normalized_provider,
            )
            return self._provider_from_resolved_config(resolved_config)

        resolved_config = await PaymentConfigService().resolve_first_tenant_payment_config(
            session,
            self._settings,
            order.tenant_id,
        )
        resolved_provider = self._provider_from_resolved_config(resolved_config)
        if resolved_provider is not None:
            return resolved_provider
        return await self._resolve_epusdt_provider(session, order)

    async def _resolve_epusdt_provider(self, session: AsyncSession, order: Order) -> Optional[ResolvedPaymentProvider]:
        if order.source_type in {"reseller", "subscription"}:
            resolved_config = await PaymentConfigService().resolve_platform_epusdt_config(self._settings)
            if resolved_config is None:
                return None
            return ResolvedPaymentProvider(
                scope_type="platform",
                provider=EpusdtGmpayProvider(resolved_config.config),
            )
        return await self._create_epusdt_provider(session, order.tenant_id)

    def _provider_from_resolved_config(
        self,
        resolved_config: Optional[ResolvedPaymentConfig],
    ) -> Optional[ResolvedPaymentProvider]:
        if resolved_config is None:
            return None
        provider_config = resolved_config.config
        if resolved_config.provider == EPUSDT_PROVIDER:
            return ResolvedPaymentProvider(
                scope_type=resolved_config.scope_type,
                provider=EpusdtGmpayProvider(provider_config),
            )
        if resolved_config.provider == TOKEN188_PROVIDER:
            if not isinstance(provider_config, Token188Config):
                raise ValueError("TOKEN188 配置无效")
            return ResolvedPaymentProvider(
                scope_type=resolved_config.scope_type,
                provider=Token188Provider(provider_config),
            )
        if resolved_config.provider == EPAY_COMPATIBLE_PROVIDER:
            if not isinstance(provider_config, EpayCompatibleConfig):
                raise ValueError("易支付配置无效")
            return ResolvedPaymentProvider(
                scope_type=resolved_config.scope_type,
                provider=EpayCompatibleProvider(provider_config),
            )
        if resolved_config.provider == LEMZF_PROVIDER:
            if not isinstance(provider_config, EpayCompatibleConfig):
                raise ValueError("柠檬支付配置无效")
            return ResolvedPaymentProvider(
                scope_type=resolved_config.scope_type,
                provider=LemzfProvider(provider_config),
            )
        if resolved_config.provider == USDT_TRC20_DIRECT_PROVIDER:
            if not isinstance(provider_config, Trc20DirectConfig):
                raise ValueError("TRC20 直付配置无效")
            return ResolvedPaymentProvider(
                scope_type=resolved_config.scope_type,
                provider=Trc20DirectPaymentProvider(
                    provider_config,
                    public_base_url=self._settings.public_base_url,
                ),
            )
        raise ValueError("支付 provider 不支持")

    async def _record_platform_settlement_if_needed(
        self,
        session: AsyncSession,
        order: Order,
    ) -> None:
        if order.payment_mode != "platform_escrow":
            return
        if order.source_type == "self":
            await LedgerService().record_order_settlement(session, order)
            return
        if order.source_type == "reseller":
            supplier_amount, reseller_amount = self._reseller_settlement_amounts(order)
            await LedgerService().record_reseller_order_settlement(
                session=session,
                order=order,
                supplier_amount=supplier_amount,
                reseller_amount=reseller_amount,
            )

    async def _backfill_settlement_for_processed_callback(
        self,
        session: AsyncSession,
        out_trade_no: str,
        scope_type: str,
    ) -> None:
        result = await session.execute(
            select(Order)
            .where(Order.out_trade_no == out_trade_no)
            .with_for_update()
        )
        order = result.scalar_one_or_none()
        if order is None or order.status not in {"paid", "delivered", "completed", "partially_refunded"}:
            return
        order.payment_mode = self._effective_payment_mode(order, scope_type)
        await self._record_platform_settlement_if_needed(session, order)

    @staticmethod
    def _effective_payment_mode(order: Order, scope_type: str) -> str:
        if order.source_type in {"reseller", "subscription"}:
            return "platform_escrow"
        if order.payment_mode not in {"", "pending_payment"}:
            return order.payment_mode
        return PaymentService._payment_mode_from_scope(scope_type)

    @staticmethod
    def _payment_mode_from_scope(scope_type: str) -> str:
        return "platform_escrow" if scope_type == "platform" else "tenant_direct"

    @staticmethod
    def _extract_out_trade_no(payload: Dict[str, Any]) -> str:
        out_trade_no = str(payload.get("order_id") or payload.get("out_trade_no") or "").strip()
        if not out_trade_no:
            raise ValueError("epusdt 回调缺少订单号")
        return out_trade_no

    @staticmethod
    def _extract_callback_out_trade_no(provider_name: str, payload: Dict[str, Any]) -> str:
        provider_name = normalize_payment_provider(provider_name)
        if provider_name == EPUSDT_PROVIDER:
            return PaymentService._extract_out_trade_no(payload)
        if provider_name == TOKEN188_PROVIDER:
            out_trade_no = str(payload.get("orderNo") or payload.get("out_trade_no") or payload.get("order_id") or "").strip()
            if not out_trade_no:
                raise ValueError("TOKEN188 回调缺少订单号")
            return out_trade_no
        out_trade_no = str(payload.get("out_trade_no") or "").strip()
        if not out_trade_no:
            raise ValueError("易支付回调缺少订单号")
        return out_trade_no

    async def _get_payment(
        self,
        session: AsyncSession,
        order_id: int,
        provider: str,
        for_update: bool = False,
    ) -> Optional[Payment]:
        query = select(Payment).where(Payment.order_id == order_id).where(Payment.provider == provider)
        if for_update:
            query = query.with_for_update()
        result = await session.execute(query)
        return result.scalar_one_or_none()

    async def _get_callback(
        self,
        session: AsyncSession,
        provider: str,
        callback_payload_hash: str,
    ) -> Optional[PaymentCallback]:
        result = await session.execute(
            select(PaymentCallback)
            .where(PaymentCallback.provider == provider)
            .where(PaymentCallback.payload_hash == callback_payload_hash)
        )
        return result.scalar_one_or_none()

    async def _ensure_delivery_record(self, session: AsyncSession, order: Order) -> Optional[int]:
        if order.status in {"delivered", "completed", "partially_refunded"}:
            return None
        if order.source_type == "subscription":
            from app.services.subscriptions import SubscriptionService

            await SubscriptionService().apply_paid_order(session, order)
            return None
        if order.self_product_id is None:
            return None

        product = await session.get(Product, order.self_product_id)
        if product is None:
            return None
        if uses_external_text_fulfillment(product):
            return None

        if product.delivery_type == "file_download":
            if product.delivery_file_id is None:
                raise ValueError("文件商品未绑定交付文件")
            result = await session.execute(select(DeliveryRecord).where(DeliveryRecord.order_id == order.id))
            delivery = result.scalar_one_or_none()
            if delivery is None:
                delivery = DeliveryRecord(
                    order_id=order.id,
                    tenant_id=order.tenant_id,
                    buyer_telegram_user_id=order.buyer_telegram_user_id,
                    delivery_type=product.delivery_type,
                    uploaded_file_id=product.delivery_file_id,
                    status="pending",
                )
                session.add(delivery)
                await session.flush()
            return delivery.id if delivery.status != "sent" else None

        if product.delivery_type not in {"card_pool", "card_fixed"}:
            if product.delivery_type == "telegram_invite":
                if product.telegram_chat_id is None:
                    raise ValueError("群邀请商品未绑定群 ID")
                result = await session.execute(select(DeliveryRecord).where(DeliveryRecord.order_id == order.id))
                delivery = result.scalar_one_or_none()
                if delivery is None:
                    delivery = DeliveryRecord(
                        order_id=order.id,
                        tenant_id=order.tenant_id,
                        buyer_telegram_user_id=order.buyer_telegram_user_id,
                        delivery_type=product.delivery_type,
                        telegram_chat_id=product.telegram_chat_id,
                        status="pending",
                    )
                    session.add(delivery)
                    await session.flush()
                return delivery.id if delivery.status != "sent" else None
            return None
        if order.locked_inventory_item_id is None:
            raise ValueError("订单缺少锁定库存")

        inventory_used = await InventoryService().mark_locked_item_used(
            session=session,
            tenant_id=self._inventory_tenant_id(order),
            inventory_item_id=order.locked_inventory_item_id,
            order_id=order.id,
        )
        if not inventory_used:
            raise ValueError("锁定库存状态异常，不能自动发货")

        result = await session.execute(select(DeliveryRecord).where(DeliveryRecord.order_id == order.id))
        delivery = result.scalar_one_or_none()
        if delivery is None:
            delivery = DeliveryRecord(
                order_id=order.id,
                tenant_id=order.tenant_id,
                buyer_telegram_user_id=order.buyer_telegram_user_id,
                delivery_type=product.delivery_type,
                inventory_item_id=order.locked_inventory_item_id,
                status="pending",
            )
            session.add(delivery)
            await session.flush()
        return delivery.id if delivery.status != "sent" else None

    async def _find_deliverable_record_id(self, session: AsyncSession, out_trade_no: str) -> Optional[int]:
        result = await session.execute(
            select(DeliveryRecord.id)
            .join(Order, Order.id == DeliveryRecord.order_id)
            .where(Order.out_trade_no == out_trade_no)
            .where(DeliveryRecord.status.in_(("pending", "failed")))
            .order_by(DeliveryRecord.created_at.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _reseller_settlement_amounts(order: Order) -> tuple[Decimal, Decimal]:
        if order.supplier_settlement_amount is None or order.reseller_settlement_amount is None:
            raise ValueError("代理订单缺少分账金额快照")
        return order.supplier_settlement_amount, order.reseller_settlement_amount

    @staticmethod
    def _inventory_tenant_id(order: Order) -> int:
        if order.source_type == "reseller" and order.supplier_tenant_id is not None:
            return order.supplier_tenant_id
        return order.tenant_id

    @staticmethod
    def _order_already_paid(order: Order, payment: Optional[Payment]) -> bool:
        if order.status in {"paid", "delivered", "completed", "partially_refunded"}:
            return True
        return payment is not None and payment.status == "paid"

    async def _ensure_order_tenant_can_create_payment(self, session: AsyncSession, order: Order) -> None:
        if order.source_type == "subscription":
            return
        tenant = await session.get(Tenant, order.tenant_id)
        if tenant is None:
            raise ValueError("租户不存在")
        if tenant.status not in PAYMENT_ALLOWED_TENANT_STATUSES:
            raise ValueError("店铺当前不可支付")

    @staticmethod
    def _payment_unavailable_message(order: Order) -> str:
        if order.source_type == "reseller":
            return "代理订单必须使用平台级 epusdt 支付配置"
        if order.source_type == "subscription":
            return "订阅续费必须使用平台级 epusdt 支付配置"
        return "支付配置未启用"
