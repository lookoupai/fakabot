from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.orders import DeliveryRecord, Order
from app.db.models.products import InventoryItem, Product
from app.services.external_sources.base import ExternalDelivery
from app.services.external_sources.identifiers import normalize_external_identifier
from app.services.external_sources.limits import (
    MAX_EXTERNAL_DELIVERY_CONTENT_LENGTH,
    MAX_EXTERNAL_DELIVERY_ITEM_LENGTH,
    MAX_EXTERNAL_DELIVERY_ITEMS,
    MAX_EXTERNAL_DELIVERY_MESSAGE_LENGTH,
)
from app.services.token_crypto import TokenCrypto


EXTERNAL_TEXT_DELIVERY_TYPES = frozenset({"card_pool", "card_fixed"})


@dataclass(frozen=True)
class ExternalDeliveryImportResult:
    out_trade_no: str
    order_status: str
    delivery_record_id: Optional[int]
    item_count: int
    imported: bool
    dry_run: bool = False


def uses_external_text_fulfillment(product: object) -> bool:
    return (
        getattr(product, "delivery_type", None) in EXTERNAL_TEXT_DELIVERY_TYPES
        and _has_non_empty_string(getattr(product, "external_source", None))
        and _has_non_empty_string(getattr(product, "external_id", None))
    )


class ExternalDeliveryImportService:
    async def import_delivery(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        out_trade_no: str,
        provider_name: str,
        source_key: str = "",
        delivery: ExternalDelivery,
        settings: Settings,
        dry_run: bool = False,
    ) -> ExternalDeliveryImportResult:
        _validate_tenant_id(tenant_id)
        normalized_out_trade_no = _normalize_out_trade_no(out_trade_no)
        normalized_provider_name = normalize_external_identifier(provider_name, "provider_name", allow_empty=False)
        normalized_source_key = normalize_external_identifier(source_key, "source_key", allow_empty=True) or ""
        if not isinstance(delivery, ExternalDelivery):
            raise ValueError("delivery 必须是 ExternalDelivery")
        if delivery.delivery_type not in EXTERNAL_TEXT_DELIVERY_TYPES:
            raise ValueError("外部发货导入仅支持文本卡密发货")

        result = await session.execute(
            select(Order)
            .where(Order.tenant_id == tenant_id)
            .where(Order.out_trade_no == normalized_out_trade_no)
            .with_for_update()
        )
        order = result.scalar_one_or_none()
        if order is None:
            raise ValueError("订单不存在")

        if order.source_type != "self" or order.self_product_id is None:
            raise ValueError("仅支持自营订单导入外部发货")
        product = await session.get(Product, order.self_product_id)
        if product is None or product.tenant_id != tenant_id:
            raise ValueError("订单商品不存在或无权限")
        if not product.external_source or not product.external_id:
            raise ValueError("订单商品缺少外部商品映射")
        if product.external_source != normalized_provider_name or product.source_key != normalized_source_key:
            raise ValueError("订单商品外部源与请求不一致")
        if product.delivery_type not in EXTERNAL_TEXT_DELIVERY_TYPES:
            raise ValueError("外部发货导入仅支持文本卡密商品")

        existing_delivery = await self._get_delivery_record(session, order.id)
        item_count = _external_delivery_item_count(delivery)
        if existing_delivery is not None:
            return ExternalDeliveryImportResult(
                out_trade_no=order.out_trade_no,
                order_status=order.status,
                delivery_record_id=existing_delivery.id,
                item_count=item_count,
                imported=False,
                dry_run=dry_run,
            )
        if order.status != "paid":
            raise ValueError("订单当前状态不能导入外部发货")

        content = _external_delivery_content(delivery)
        if dry_run:
            return ExternalDeliveryImportResult(
                out_trade_no=order.out_trade_no,
                order_status=order.status,
                delivery_record_id=None,
                item_count=item_count,
                imported=False,
                dry_run=True,
            )

        now = datetime.now(timezone.utc)
        crypto = TokenCrypto(settings)
        inventory_item = InventoryItem(
            tenant_id=tenant_id,
            product_id=product.id,
            variant_id=order.product_variant_id,
            content_encrypted=crypto.encrypt_token(content),
            content_hash=crypto.token_hash(
                f"external-delivery:{order.out_trade_no}:{delivery.external_order_id}:{content}"
            ),
            status="used",
            used_by_order_id=order.id,
            used_at=now,
        )
        session.add(inventory_item)
        await session.flush()

        delivery_record = DeliveryRecord(
            order_id=order.id,
            tenant_id=order.tenant_id,
            buyer_telegram_user_id=order.buyer_telegram_user_id,
            delivery_type=product.delivery_type,
            inventory_item_id=inventory_item.id,
            status="pending",
        )
        session.add(delivery_record)
        await session.flush()
        return ExternalDeliveryImportResult(
            out_trade_no=order.out_trade_no,
            order_status=order.status,
            delivery_record_id=delivery_record.id,
            item_count=item_count,
            imported=True,
            dry_run=False,
        )

    @staticmethod
    async def _get_delivery_record(session: AsyncSession, order_id: int) -> Optional[DeliveryRecord]:
        result = await session.execute(
            select(DeliveryRecord)
            .where(DeliveryRecord.order_id == order_id)
            .with_for_update()
            .limit(1)
        )
        return result.scalar_one_or_none()


def _validate_tenant_id(tenant_id: int) -> None:
    if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id <= 0:
        raise ValueError("tenant_id 必须为正整数")


def _has_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


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


def _external_delivery_item_count(delivery: ExternalDelivery) -> int:
    item_count = len(delivery.items)
    return item_count if item_count > 0 else 1


def _external_delivery_content(delivery: ExternalDelivery) -> str:
    items = [item.strip() for item in delivery.items]
    message = delivery.message.strip() if delivery.message is not None else ""
    if len(items) > MAX_EXTERNAL_DELIVERY_ITEMS:
        raise ValueError("外部发货条目数量不能超过 100")
    if any(len(item) > MAX_EXTERNAL_DELIVERY_ITEM_LENGTH for item in items):
        raise ValueError("外部发货条目长度不能超过 512")
    if len(message) > MAX_EXTERNAL_DELIVERY_MESSAGE_LENGTH:
        raise ValueError("外部发货消息长度不能超过 1024")
    parts: list[str] = []
    if message:
        parts.append(message)
    if items:
        if parts:
            parts.append("")
        parts.extend(items)
    content = "\n".join(parts).strip()
    if not content:
        raise ValueError("外部发货内容为空")
    if len(content) > MAX_EXTERNAL_DELIVERY_CONTENT_LENGTH:
        raise ValueError("外部发货内容长度不能超过 3500")
    return content
