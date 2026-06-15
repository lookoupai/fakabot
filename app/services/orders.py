from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.orders import Order
from app.db.models.products import Product, ProductVariant
from app.db.models.supply import ResellerProduct, SupplierOffer, SupplierResellerRule
from app.db.models.tenants import Tenant
from app.db.repos.products import ProductRepository
from app.services.external_sources.fulfillment import uses_external_text_fulfillment
from app.services.inventory import InventoryService
from app.services.risk import RiskControlService
from app.services.supply import SUPPORTED_RESELLER_DELIVERY_TYPES
from app.services.tenant_features import load_tenant_feature_flags, require_tenant_feature

ACTIVE_TENANT_STATUSES = ("trial", "active", "grace")


@dataclass
class CreatedOrder:
    order_id: int
    out_trade_no: str
    amount: Decimal
    currency: str
    expires_at: datetime
    locked_inventory_item_id: Optional[int]


@dataclass
class BuyerOrderSummary:
    out_trade_no: str
    product_name: str
    amount: Decimal
    currency: str
    status: str
    created_at: datetime
    expires_at: datetime
    paid_at: Optional[datetime]
    delivered_at: Optional[datetime]


class OrderService:
    async def create_self_order(
        self,
        session: AsyncSession,
        tenant_id: int,
        buyer_telegram_user_id: int,
        product_id: int,
        order_timeout_minutes: int,
    ) -> CreatedOrder:
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise ValueError("租户不存在")
        self._ensure_tenant_can_accept_orders(tenant)
        require_tenant_feature(await load_tenant_feature_flags(session, tenant_id, tenant=tenant), "self_sale")
        product_repo = ProductRepository()
        product, variant = await product_repo.get_product_with_default_variant(session, tenant_id, product_id)
        if product is None or variant is None:
            raise ValueError("商品不存在")
        if product.status != "on":
            raise ValueError("商品未上架")
        if variant.status != "on":
            raise ValueError("商品档位不可售")
        if product.delivery_type == "file_download" and product.delivery_file_id is None:
            raise ValueError("文件商品尚未绑定交付文件")
        if product.delivery_type == "telegram_invite" and product.telegram_chat_id is None:
            raise ValueError("群邀请商品尚未绑定群 ID")
        await RiskControlService().ensure_order_creation_allowed(
            session=session,
            buyer_telegram_user_id=buyer_telegram_user_id,
            amount=variant.price,
            currency=variant.currency,
            tenant_id=tenant_id,
            source_type="self",
        )

        expires_at = datetime.now(timezone.utc) + timedelta(minutes=order_timeout_minutes)
        order = Order(
            tenant_id=tenant_id,
            buyer_telegram_user_id=buyer_telegram_user_id,
            source_type="self",
            self_product_id=product.id,
            product_variant_id=variant.id,
            amount=variant.price,
            currency=variant.currency,
            display_amount=variant.price,
            display_currency=variant.currency,
            payment_mode="pending_payment",
            status="pending",
            out_trade_no=self._new_out_trade_no(),
            expires_at=expires_at,
        )
        session.add(order)
        await session.flush()

        locked_inventory_item_id: Optional[int] = None
        if product.delivery_type in {"card_pool", "card_fixed"} and not uses_external_text_fulfillment(product):
            locked_inventory = await InventoryService().lock_one_available_item(
                session=session,
                tenant_id=tenant_id,
                product_id=product.id,
                order_id=order.id,
                lock_minutes=order_timeout_minutes,
            )
            if locked_inventory is None:
                raise ValueError("库存不足")
            locked_inventory_item_id = locked_inventory.inventory_item_id
            order.locked_inventory_item_id = locked_inventory_item_id
            await session.flush()

        return CreatedOrder(
            order_id=order.id,
            out_trade_no=order.out_trade_no,
            amount=order.amount,
            currency=order.currency,
            expires_at=order.expires_at,
            locked_inventory_item_id=locked_inventory_item_id,
        )

    async def create_reseller_order(
        self,
        session: AsyncSession,
        tenant_id: int,
        buyer_telegram_user_id: int,
        reseller_product_id: int,
        order_timeout_minutes: int,
    ) -> CreatedOrder:
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise ValueError("租户不存在")
        self._ensure_tenant_can_accept_orders(tenant)
        require_tenant_feature(await load_tenant_feature_flags(session, tenant_id, tenant=tenant), "reseller")
        result = await session.execute(
            select(ResellerProduct, SupplierOffer, Product, ProductVariant, SupplierResellerRule)
            .join(SupplierOffer, SupplierOffer.id == ResellerProduct.supplier_offer_id)
            .join(Product, Product.id == SupplierOffer.product_id)
            .join(ProductVariant, ProductVariant.id == SupplierOffer.variant_id)
            .join(Tenant, Tenant.id == SupplierOffer.supplier_tenant_id)
            .outerjoin(
                SupplierResellerRule,
                and_(
                    SupplierResellerRule.supplier_offer_id == SupplierOffer.id,
                    SupplierResellerRule.reseller_tenant_id == ResellerProduct.reseller_tenant_id,
                ),
            )
            .where(ResellerProduct.id == reseller_product_id)
            .where(ResellerProduct.reseller_tenant_id == tenant_id)
            .where(ResellerProduct.status == "on")
            .where(ResellerProduct.hide_supplier.is_(True))
            .where(SupplierOffer.status == "on")
            .where(or_(SupplierOffer.requires_approval.is_(False), SupplierResellerRule.status == "active"))
            .where(SupplierOffer.hidden_supplier_allowed.is_(True))
            .where(Tenant.status.in_(ACTIVE_TENANT_STATUSES))
            .where(Product.status == "on")
            .where(ProductVariant.status == "on")
        )
        row = result.first()
        if row is None:
            raise ValueError("代理商品不存在或不可售")

        reseller_product, offer, product, variant, rule = row
        supplier_tenant = await session.get(Tenant, offer.supplier_tenant_id)
        if supplier_tenant is None:
            raise ValueError("供应商店铺不可用")
        require_tenant_feature(
            await load_tenant_feature_flags(session, offer.supplier_tenant_id, tenant=supplier_tenant),
            "supplier",
        )
        if product.delivery_type not in SUPPORTED_RESELLER_DELIVERY_TYPES:
            raise ValueError("当前代理下单暂不支持该发货类型")
        if product.delivery_type == "file_download" and product.delivery_file_id is None:
            raise ValueError("文件商品尚未绑定交付文件")
        supplier_cost = self._effective_supplier_cost(offer, rule)
        min_sale_price = self._effective_min_sale_price(offer, rule)
        if reseller_product.sale_price < supplier_cost:
            raise ValueError("代理商品售价低于供应商成本，不能下单")
        if min_sale_price is not None and reseller_product.sale_price < min_sale_price:
            raise ValueError("代理商品售价低于供应商最低售价，不能下单")
        reseller_profit = reseller_product.sale_price - supplier_cost
        await RiskControlService().ensure_order_creation_allowed(
            session=session,
            buyer_telegram_user_id=buyer_telegram_user_id,
            amount=reseller_product.sale_price,
            currency=variant.currency,
            tenant_id=tenant_id,
            source_type="reseller",
        )

        expires_at = datetime.now(timezone.utc) + timedelta(minutes=order_timeout_minutes)
        order = Order(
            tenant_id=tenant_id,
            buyer_telegram_user_id=buyer_telegram_user_id,
            source_type="reseller",
            self_product_id=product.id,
            product_variant_id=variant.id,
            reseller_product_id=reseller_product.id,
            supplier_tenant_id=offer.supplier_tenant_id,
            amount=reseller_product.sale_price,
            currency=variant.currency,
            display_amount=reseller_product.sale_price,
            display_currency=variant.currency,
            supplier_settlement_amount=supplier_cost,
            reseller_settlement_amount=reseller_profit,
            payment_mode="pending_payment",
            status="pending",
            out_trade_no=self._new_out_trade_no(),
            expires_at=expires_at,
        )
        session.add(order)
        await session.flush()

        locked_inventory_item_id: Optional[int] = None
        if product.delivery_type in {"card_pool", "card_fixed"}:
            locked_inventory = await InventoryService().lock_one_available_item(
                session=session,
                tenant_id=offer.supplier_tenant_id,
                product_id=product.id,
                order_id=order.id,
                lock_minutes=order_timeout_minutes,
            )
            if locked_inventory is None:
                raise ValueError("库存不足")
            locked_inventory_item_id = locked_inventory.inventory_item_id
            order.locked_inventory_item_id = locked_inventory_item_id
            await session.flush()

        return CreatedOrder(
            order_id=order.id,
            out_trade_no=order.out_trade_no,
            amount=order.amount,
            currency=order.currency,
            expires_at=order.expires_at,
            locked_inventory_item_id=locked_inventory_item_id,
        )

    @staticmethod
    def _new_out_trade_no() -> str:
        return "ORD" + secrets.token_urlsafe(18).replace("-", "").replace("_", "")[:24]

    async def expire_pending_orders(
        self,
        session: AsyncSession,
        tenant_id: Optional[int] = None,
        limit: int = 500,
        now: Optional[datetime] = None,
    ) -> int:
        current_time = now or datetime.now(timezone.utc)
        query = (
            select(Order)
            .where(Order.status == "pending")
            .where(Order.expires_at <= current_time)
            .order_by(Order.expires_at.asc())
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        if tenant_id is not None:
            query = query.where(Order.tenant_id == tenant_id)

        result = await session.execute(query)
        orders = list(result.scalars().all())
        inventory_service = InventoryService()
        for order in orders:
            await inventory_service.release_order_locks(
                session=session,
                tenant_id=self._inventory_tenant_id(order),
                order_id=order.id,
            )
            order.status = "expired"
            order.locked_inventory_item_id = None
        await session.flush()
        return len(orders)

    async def list_buyer_orders(
        self,
        session: AsyncSession,
        tenant_id: int,
        buyer_telegram_user_id: int,
        limit: int = 10,
    ) -> List[BuyerOrderSummary]:
        result = await session.execute(
            select(Order, Product.name, ResellerProduct.display_name)
            .outerjoin(Product, Product.id == Order.self_product_id)
            .outerjoin(ResellerProduct, ResellerProduct.id == Order.reseller_product_id)
            .where(Order.tenant_id == tenant_id)
            .where(Order.buyer_telegram_user_id == buyer_telegram_user_id)
            .order_by(Order.created_at.desc())
            .limit(limit)
        )
        return [
            BuyerOrderSummary(
                out_trade_no=order.out_trade_no,
                product_name=reseller_display_name if order.source_type == "reseller" and reseller_display_name else product_name or "商品",
                amount=order.amount,
                currency=order.currency,
                status=order.status,
                created_at=order.created_at,
                expires_at=order.expires_at,
                paid_at=order.paid_at,
                delivered_at=order.delivered_at,
            )
            for order, product_name, reseller_display_name in result.all()
        ]

    @staticmethod
    def _inventory_tenant_id(order: Order) -> int:
        if order.source_type == "reseller" and order.supplier_tenant_id is not None:
            return order.supplier_tenant_id
        return order.tenant_id

    @staticmethod
    def _ensure_tenant_can_accept_orders(tenant: Tenant) -> None:
        if tenant.status not in ACTIVE_TENANT_STATUSES:
            raise ValueError("店铺当前不可下单")

    @staticmethod
    def _fixed_supplier_cost(offer: SupplierOffer) -> Decimal:
        if offer.default_pricing_mode != "fixed_cost":
            raise ValueError("当前版本仅支持固定供应商成本")
        if offer.default_pricing_value <= 0:
            raise ValueError("供应商成本必须大于 0")
        return offer.default_pricing_value

    def _effective_supplier_cost(
        self,
        offer: SupplierOffer,
        rule: Optional[SupplierResellerRule],
    ) -> Decimal:
        if rule is not None and rule.status == "active":
            if rule.pricing_mode != "fixed_cost":
                raise ValueError("当前版本仅支持固定供应商成本")
            if rule.pricing_value <= 0:
                raise ValueError("供应商成本必须大于 0")
            return rule.pricing_value
        return self._fixed_supplier_cost(offer)

    @staticmethod
    def _effective_min_sale_price(
        offer: SupplierOffer,
        rule: Optional[SupplierResellerRule],
    ) -> Optional[Decimal]:
        if rule is not None and rule.status == "active" and rule.min_sale_price is not None:
            return rule.min_sale_price
        return offer.min_sale_price
