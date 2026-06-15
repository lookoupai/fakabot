from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.products import InventoryItem, Product, ProductVariant
from app.db.models.supply import ResellerProduct, SupplierOffer, SupplierResellerRule
from app.db.models.tenants import AuditLog, Tenant

SUPPORTED_RESELLER_DELIVERY_TYPES = {"card_pool", "card_fixed", "file_download"}
ACTIVE_TENANT_STATUSES = ("trial", "active", "grace")


@dataclass(frozen=True)
class CreatedSupplierOffer:
    offer_id: int
    product_id: int
    variant_id: int
    product_name: str
    delivery_type: str
    suggested_price: Decimal
    min_sale_price: Optional[Decimal]
    supplier_cost: Decimal
    currency: str
    requires_approval: bool
    status: str


@dataclass(frozen=True)
class SupplierOwnOfferSummary:
    offer_id: int
    product_name: str
    category: Optional[str]
    delivery_type: str
    suggested_price: Decimal
    min_sale_price: Optional[Decimal]
    supplier_cost: Decimal
    currency: str
    available_count: int
    requires_approval: bool
    status: str


@dataclass(frozen=True)
class PlatformSupplierOfferSummary:
    supplier_offer_id: int
    supplier_tenant_id: int
    supplier_store_name: str
    product_name: str
    delivery_type: str
    suggested_price: Decimal
    min_sale_price: Optional[Decimal]
    supplier_cost: Decimal
    currency: str
    available_count: int
    requires_approval: bool
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class SupplierOfferSummary:
    offer_id: int
    product_name: str
    category: Optional[str]
    delivery_type: str
    suggested_price: Decimal
    min_sale_price: Optional[Decimal]
    currency: str
    available_count: int
    description: Optional[str]
    requires_approval: bool
    reseller_rule_status: Optional[str]
    supplier_cost: Decimal
    effective_min_sale_price: Optional[Decimal]


@dataclass(frozen=True)
class CreatedResellerProduct:
    reseller_product_id: int
    supplier_offer_id: int
    display_name: str
    sale_price: Decimal
    currency: str
    status: str


@dataclass(frozen=True)
class ResellerProductSummary:
    reseller_product_id: int
    supplier_offer_id: int
    display_name: str
    category: Optional[str]
    sort_order: int
    delivery_type: str
    sale_price: Decimal
    currency: str
    status: str
    available_count: int


@dataclass(frozen=True)
class PublicResellerProductSummary:
    reseller_product_id: int
    display_name: str
    category: Optional[str]
    delivery_type: str
    sale_price: Decimal
    currency: str
    available_count: int


@dataclass(frozen=True)
class SupplierApprovalSetting:
    offer_id: int
    requires_approval: bool
    status: str


@dataclass(frozen=True)
class ResellerApplicationSummary:
    rule_id: int
    supplier_offer_id: int
    supplier_tenant_id: int
    supplier_store_name: str
    reseller_tenant_id: int
    reseller_store_name: str
    product_name: str
    status: str
    pricing_value: Decimal
    min_sale_price: Optional[Decimal]
    currency: str
    updated_at: datetime


class SupplyService:
    PLATFORM_SUPPLIER_OFFER_STATUSES = {"on", "disabled"}

    async def create_supplier_offer(
        self,
        session: AsyncSession,
        supplier_tenant_id: int,
        product_id: int,
        suggested_price: Decimal,
        min_sale_price: Optional[Decimal] = None,
        requires_approval: Optional[bool] = None,
    ) -> CreatedSupplierOffer:
        self._validate_suggested_price(suggested_price, min_sale_price)
        product, variant = await self._get_supplier_product(session, supplier_tenant_id, product_id)
        if product is None or variant is None:
            raise ValueError("商品不存在或缺少默认档位")
        if product.product_type != "self":
            raise ValueError("只有自营商品可以开放供货")
        if product.status != "on":
            raise ValueError("商品必须先上架后才能开放供货")
        if variant.status != "on":
            raise ValueError("默认档位不可售")
        if product.delivery_type not in SUPPORTED_RESELLER_DELIVERY_TYPES:
            raise ValueError("当前代理下单暂不支持该发货类型")
        if product.delivery_type == "file_download" and product.delivery_file_id is None:
            raise ValueError("文件商品需要先绑定文件")
        if product.delivery_type == "telegram_invite" and product.telegram_chat_id is None:
            raise ValueError("群邀请商品需要先绑定群 ID")

        result = await session.execute(
            select(SupplierOffer)
            .where(SupplierOffer.supplier_tenant_id == supplier_tenant_id)
            .where(SupplierOffer.product_id == product.id)
            .where(SupplierOffer.variant_id == variant.id)
            .order_by(SupplierOffer.created_at.desc())
            .limit(1)
        )
        offer = result.scalar_one_or_none()
        if offer is None:
            offer = SupplierOffer(
                supplier_tenant_id=supplier_tenant_id,
                product_id=product.id,
                variant_id=variant.id,
                status="on",
                suggested_price=suggested_price,
                min_sale_price=min_sale_price,
                default_pricing_mode="fixed_cost",
                default_pricing_value=variant.price,
                requires_approval=bool(requires_approval),
                hidden_supplier_allowed=True,
            )
            session.add(offer)
        else:
            if offer.status == "disabled":
                raise ValueError("供货商品已被平台下架，不能重新开放")
            offer.status = "on"
            offer.suggested_price = suggested_price
            offer.min_sale_price = min_sale_price
            offer.default_pricing_mode = "fixed_cost"
            offer.default_pricing_value = variant.price
            if requires_approval is not None:
                offer.requires_approval = requires_approval
            offer.hidden_supplier_allowed = True

        await session.flush()
        return CreatedSupplierOffer(
            offer_id=offer.id,
            product_id=product.id,
            variant_id=variant.id,
            product_name=product.name,
            delivery_type=product.delivery_type,
            suggested_price=offer.suggested_price,
            min_sale_price=offer.min_sale_price,
            supplier_cost=offer.default_pricing_value,
            currency=variant.currency,
            requires_approval=offer.requires_approval,
            status=offer.status,
        )

    async def set_supplier_offer_approval(
        self,
        session: AsyncSession,
        supplier_tenant_id: int,
        supplier_offer_id: int,
        requires_approval: bool,
        actor_user_id: Optional[int],
    ) -> SupplierApprovalSetting:
        offer = await self._get_supplier_offer(session, supplier_tenant_id, supplier_offer_id)
        if offer is None:
            raise ValueError("供货商品不存在或无权限")
        offer.requires_approval = requires_approval
        session.add(
            AuditLog(
                tenant_id=supplier_tenant_id,
                actor_user_id=actor_user_id,
                action="supplier_offer.approval_updated",
                target_type="supplier_offer",
                target_id=str(offer.id),
                metadata_json={"requires_approval": requires_approval},
            )
        )
        await session.flush()
        return SupplierApprovalSetting(
            offer_id=offer.id,
            requires_approval=offer.requires_approval,
            status=offer.status,
        )

    async def list_supplier_offers(
        self,
        session: AsyncSession,
        supplier_tenant_id: int,
        limit: int = 20,
    ) -> List[SupplierOwnOfferSummary]:
        available_counts = self._available_count_subquery()
        result = await session.execute(
            select(
                SupplierOffer,
                Product,
                ProductVariant,
                func.coalesce(available_counts.c.available_count, 0),
            )
            .join(Product, Product.id == SupplierOffer.product_id)
            .join(ProductVariant, ProductVariant.id == SupplierOffer.variant_id)
            .outerjoin(
                available_counts,
                and_(
                    available_counts.c.tenant_id == SupplierOffer.supplier_tenant_id,
                    available_counts.c.product_id == SupplierOffer.product_id,
                ),
            )
            .where(SupplierOffer.supplier_tenant_id == supplier_tenant_id)
            .where(SupplierOffer.status != "deleted")
            .where(Product.status != "deleted")
            .order_by(SupplierOffer.created_at.desc(), SupplierOffer.id.desc())
            .limit(self._normalize_limit(limit))
        )
        return [
            SupplierOwnOfferSummary(
                offer_id=offer.id,
                product_name=product.name,
                category=product.category,
                delivery_type=product.delivery_type,
                suggested_price=offer.suggested_price,
                min_sale_price=offer.min_sale_price,
                supplier_cost=offer.default_pricing_value,
                currency=variant.currency,
                available_count=int(available_count or 0),
                requires_approval=offer.requires_approval,
                status=offer.status,
            )
            for offer, product, variant, available_count in result.all()
        ]

    async def list_platform_supplier_offers(
        self,
        session: AsyncSession,
        *,
        status: Optional[str] = None,
        supplier_tenant_id: Optional[int] = None,
        limit: int = 20,
    ) -> List[PlatformSupplierOfferSummary]:
        normalized_status = self._normalize_platform_supplier_offer_status(status, allow_all=True)
        normalized_supplier_tenant_id = self._normalize_optional_positive_int(
            supplier_tenant_id,
            "供应商租户 ID",
        )
        available_counts = self._available_count_subquery()
        query = (
            select(
                SupplierOffer,
                Tenant,
                Product,
                ProductVariant,
                func.coalesce(available_counts.c.available_count, 0),
            )
            .join(Tenant, Tenant.id == SupplierOffer.supplier_tenant_id)
            .join(Product, Product.id == SupplierOffer.product_id)
            .join(ProductVariant, ProductVariant.id == SupplierOffer.variant_id)
            .outerjoin(
                available_counts,
                and_(
                    available_counts.c.tenant_id == SupplierOffer.supplier_tenant_id,
                    available_counts.c.product_id == SupplierOffer.product_id,
                ),
            )
            .where(SupplierOffer.status != "deleted")
            .where(Product.status != "deleted")
            .order_by(SupplierOffer.created_at.desc(), SupplierOffer.id.desc())
            .limit(self._normalize_limit(limit))
        )
        if normalized_status is not None:
            query = query.where(SupplierOffer.status == normalized_status)
        if normalized_supplier_tenant_id is not None:
            query = query.where(SupplierOffer.supplier_tenant_id == normalized_supplier_tenant_id)
        result = await session.execute(query)
        return [
            self._platform_supplier_offer_summary(offer, tenant, product, variant, int(available_count or 0))
            for offer, tenant, product, variant, available_count in result.all()
        ]

    async def set_platform_supplier_offer_status(
        self,
        session: AsyncSession,
        *,
        supplier_offer_id: int,
        status: str,
        reason: Optional[str] = None,
    ) -> PlatformSupplierOfferSummary:
        normalized_offer_id = self._normalize_positive_int(supplier_offer_id, "供货商品 ID")
        normalized_status = self._normalize_platform_supplier_offer_status(status, allow_all=False)
        assert normalized_status is not None
        row = await self._get_platform_supplier_offer_details(session, normalized_offer_id)
        if row is None:
            raise ValueError("供货商品不存在或不可管理")
        offer, tenant, product, variant, available_count = row
        previous_status = offer.status
        if previous_status != normalized_status:
            offer.status = normalized_status
            session.add(
                AuditLog(
                    tenant_id=None,
                    actor_user_id=None,
                    action="platform_supply.supplier_offer_status_updated",
                    target_type="supplier_offer",
                    target_id=str(offer.id),
                    metadata_json={
                        "supplier_tenant_id": offer.supplier_tenant_id,
                        "previous_status": previous_status,
                        "new_status": normalized_status,
                        "reason": self._safe_platform_supply_reason(reason),
                    },
                )
            )
        await session.flush()
        return self._platform_supplier_offer_summary(offer, tenant, product, variant, available_count)

    async def list_market_offers(
        self,
        session: AsyncSession,
        reseller_tenant_id: int,
        limit: int = 20,
        query: Optional[str] = None,
        delivery_type: Optional[str] = None,
        access: Optional[str] = None,
        min_price: Optional[Decimal] = None,
        max_price: Optional[Decimal] = None,
        stock: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[SupplierOfferSummary]:
        normalized_query = self._normalize_market_query(query)
        normalized_delivery_type = self._normalize_market_delivery_type(delivery_type)
        normalized_access = self._normalize_market_access(access)
        normalized_min_price = self._normalize_optional_price(min_price, "最低售价")
        normalized_max_price = self._normalize_optional_price(max_price, "最高售价")
        if normalized_min_price is not None and normalized_max_price is not None and normalized_min_price > normalized_max_price:
            raise ValueError("最低售价不能高于最高售价")
        normalized_stock = self._normalize_market_stock(stock)
        normalized_category = self._normalize_market_category(category)
        available_counts = self._available_count_subquery()
        statement = (
            select(
                SupplierOffer,
                Product,
                ProductVariant,
                func.coalesce(available_counts.c.available_count, 0),
                SupplierResellerRule.status,
                SupplierResellerRule.pricing_value,
                SupplierResellerRule.min_sale_price,
            )
            .join(Product, Product.id == SupplierOffer.product_id)
            .join(ProductVariant, ProductVariant.id == SupplierOffer.variant_id)
            .join(Tenant, Tenant.id == SupplierOffer.supplier_tenant_id)
            .outerjoin(
                available_counts,
                and_(
                    available_counts.c.tenant_id == SupplierOffer.supplier_tenant_id,
                    available_counts.c.product_id == SupplierOffer.product_id,
                ),
            )
            .outerjoin(
                SupplierResellerRule,
                and_(
                    SupplierResellerRule.supplier_offer_id == SupplierOffer.id,
                    SupplierResellerRule.reseller_tenant_id == reseller_tenant_id,
                ),
            )
            .where(SupplierOffer.status == "on")
            .where(SupplierOffer.supplier_tenant_id != reseller_tenant_id)
            .where(SupplierOffer.hidden_supplier_allowed.is_(True))
            .where(Tenant.status.in_(ACTIVE_TENANT_STATUSES))
            .where(Product.status == "on")
            .where(Product.delivery_type.in_(SUPPORTED_RESELLER_DELIVERY_TYPES))
            .where(ProductVariant.status == "on")
        )
        if normalized_query is not None:
            statement = statement.where(Product.name.ilike(f"%{normalized_query}%"))
        if normalized_delivery_type is not None:
            statement = statement.where(Product.delivery_type == normalized_delivery_type)
        if normalized_category is not None:
            statement = statement.where(Product.category == normalized_category)
        if normalized_access == "open":
            statement = statement.where(SupplierOffer.requires_approval.is_(False))
        elif normalized_access == "approval_required":
            statement = statement.where(SupplierOffer.requires_approval.is_(True))
        elif normalized_access == "pending":
            statement = statement.where(SupplierResellerRule.status == "pending")
        elif normalized_access == "active":
            statement = statement.where(SupplierResellerRule.status == "active")
        elif normalized_access == "rejected":
            statement = statement.where(SupplierResellerRule.status == "rejected")
        elif normalized_access == "ready":
            statement = statement.where(
                or_(
                    SupplierOffer.requires_approval.is_(False),
                    SupplierResellerRule.status == "active",
                )
            )
        if normalized_stock == "available":
            statement = statement.where(func.coalesce(available_counts.c.available_count, 0) > 0)
        elif normalized_stock == "empty":
            statement = statement.where(func.coalesce(available_counts.c.available_count, 0) == 0)

        result = await session.execute(
            statement.order_by(SupplierOffer.created_at.desc(), SupplierOffer.id.desc()).limit(
                self._normalize_limit(limit)
            )
        )
        summaries = [
            SupplierOfferSummary(
                offer_id=offer.id,
                product_name=product.name,
                category=product.category,
                delivery_type=product.delivery_type,
                suggested_price=offer.suggested_price,
                min_sale_price=offer.min_sale_price,
                currency=variant.currency,
                available_count=int(available_count or 0),
                description=product.description,
                requires_approval=offer.requires_approval,
                reseller_rule_status=rule_status,
                supplier_cost=rule_pricing_value if rule_status == "active" and rule_pricing_value is not None else offer.default_pricing_value,
                effective_min_sale_price=rule_min_sale_price if rule_status == "active" and rule_min_sale_price is not None else offer.min_sale_price,
            )
            for offer, product, variant, available_count, rule_status, rule_pricing_value, rule_min_sale_price in result.all()
        ]
        if normalized_min_price is None and normalized_max_price is None:
            return summaries
        return [
            summary
            for summary in summaries
            if self._market_offer_price_in_range(
                summary,
                min_price=normalized_min_price,
                max_price=normalized_max_price,
            )
        ]

    async def apply_reseller(
        self,
        session: AsyncSession,
        reseller_tenant_id: int,
        supplier_offer_id: int,
        requested_by_user_id: Optional[int],
    ) -> ResellerApplicationSummary:
        offer, product, variant = await self._get_offer_details(session, supplier_offer_id)
        if offer is None or product is None or variant is None:
            raise ValueError("供货商品不存在或不可申请")
        if offer.supplier_tenant_id == reseller_tenant_id:
            raise ValueError("不能申请代理自己店铺的供货商品")
        if not offer.requires_approval:
            raise ValueError("该供货商品无需审批，可直接上架代理商品")
        if not offer.hidden_supplier_allowed:
            raise ValueError("当前版本仅支持隐藏供应商的代理商品")
        if product.delivery_type not in SUPPORTED_RESELLER_DELIVERY_TYPES:
            raise ValueError("当前代理下单暂不支持该发货类型")

        reseller_tenant = await session.get(Tenant, reseller_tenant_id)
        if reseller_tenant is None:
            raise ValueError("代理租户不存在")

        rule = await self._get_reseller_rule(session, offer.id, reseller_tenant_id)
        if rule is None:
            rule = SupplierResellerRule(
                supplier_offer_id=offer.id,
                reseller_tenant_id=reseller_tenant_id,
                pricing_mode="fixed_cost",
                pricing_value=self._fixed_supplier_cost(offer),
                min_sale_price=offer.min_sale_price,
                status="pending",
            )
            session.add(rule)
        elif rule.status != "active":
            rule.status = "pending"
            rule.pricing_mode = "fixed_cost"
            rule.pricing_value = self._fixed_supplier_cost(offer)
            rule.min_sale_price = offer.min_sale_price
        else:
            raise ValueError("该供货商品已审批通过，可直接上架代理商品")

        session.add(
            AuditLog(
                tenant_id=reseller_tenant_id,
                actor_user_id=requested_by_user_id,
                action="supplier_reseller_rule.requested",
                target_type="supplier_offer",
                target_id=str(offer.id),
                metadata_json={"supplier_tenant_id": offer.supplier_tenant_id},
            )
        )
        await session.flush()
        return await self._build_application_summary(session, offer, product, variant, rule)

    async def approve_reseller(
        self,
        session: AsyncSession,
        supplier_tenant_id: int,
        supplier_offer_id: int,
        reseller_tenant_id: int,
        actor_user_id: Optional[int],
        pricing_value: Optional[Decimal] = None,
        min_sale_price: Optional[Decimal] = None,
    ) -> ResellerApplicationSummary:
        offer, product, variant = await self._get_supplier_offer_details(session, supplier_tenant_id, supplier_offer_id)
        if offer is None or product is None or variant is None:
            raise ValueError("供货商品不存在或无权限")
        if offer.supplier_tenant_id == reseller_tenant_id:
            raise ValueError("不能审批自己店铺为代理商")
        reseller_tenant = await session.get(Tenant, reseller_tenant_id)
        if reseller_tenant is None:
            raise ValueError("代理租户不存在")

        effective_pricing_value = pricing_value if pricing_value is not None else self._fixed_supplier_cost(offer)
        effective_min_sale_price = min_sale_price if min_sale_price is not None else offer.min_sale_price
        self._validate_reseller_rule(effective_pricing_value, effective_min_sale_price)

        rule = await self._get_reseller_rule(session, offer.id, reseller_tenant_id)
        if rule is None:
            rule = SupplierResellerRule(
                supplier_offer_id=offer.id,
                reseller_tenant_id=reseller_tenant_id,
                pricing_mode="fixed_cost",
                pricing_value=effective_pricing_value,
                min_sale_price=effective_min_sale_price,
                status="active",
            )
            session.add(rule)
        else:
            rule.pricing_mode = "fixed_cost"
            rule.pricing_value = effective_pricing_value
            rule.min_sale_price = effective_min_sale_price
            rule.status = "active"

        await session.flush()
        session.add(
            AuditLog(
                tenant_id=supplier_tenant_id,
                actor_user_id=actor_user_id,
                action="supplier_reseller_rule.approved",
                target_type="supplier_reseller_rule",
                target_id=str(rule.id),
                metadata_json={
                    "supplier_offer_id": offer.id,
                    "reseller_tenant_id": reseller_tenant_id,
                    "pricing_mode": "fixed_cost",
                    "pricing_value": str(effective_pricing_value),
                    "min_sale_price": str(effective_min_sale_price) if effective_min_sale_price is not None else None,
                },
            )
        )
        await session.flush()
        return await self._build_application_summary(session, offer, product, variant, rule)

    async def approve_reseller_application(
        self,
        session: AsyncSession,
        supplier_tenant_id: int,
        supplier_offer_id: int,
        reseller_tenant_id: int,
        actor_user_id: Optional[int],
    ) -> ResellerApplicationSummary:
        await self._require_pending_reseller_application(
            session=session,
            supplier_tenant_id=supplier_tenant_id,
            supplier_offer_id=supplier_offer_id,
            reseller_tenant_id=reseller_tenant_id,
        )
        return await self.approve_reseller(
            session=session,
            supplier_tenant_id=supplier_tenant_id,
            supplier_offer_id=supplier_offer_id,
            reseller_tenant_id=reseller_tenant_id,
            actor_user_id=actor_user_id,
        )

    async def reject_reseller(
        self,
        session: AsyncSession,
        supplier_tenant_id: int,
        supplier_offer_id: int,
        reseller_tenant_id: int,
        actor_user_id: Optional[int],
        reason: Optional[str] = None,
    ) -> ResellerApplicationSummary:
        offer, product, variant = await self._get_supplier_offer_details(session, supplier_tenant_id, supplier_offer_id)
        if offer is None or product is None or variant is None:
            raise ValueError("供货商品不存在或无权限")
        if offer.supplier_tenant_id == reseller_tenant_id:
            raise ValueError("不能拒绝自己店铺")
        reseller_tenant = await session.get(Tenant, reseller_tenant_id)
        if reseller_tenant is None:
            raise ValueError("代理租户不存在")

        rule = await self._get_reseller_rule(session, offer.id, reseller_tenant_id)
        if rule is None:
            rule = SupplierResellerRule(
                supplier_offer_id=offer.id,
                reseller_tenant_id=reseller_tenant_id,
                pricing_mode="fixed_cost",
                pricing_value=self._fixed_supplier_cost(offer),
                min_sale_price=offer.min_sale_price,
                status="rejected",
            )
            session.add(rule)
        else:
            rule.status = "rejected"

        await session.flush()
        session.add(
            AuditLog(
                tenant_id=supplier_tenant_id,
                actor_user_id=actor_user_id,
                action="supplier_reseller_rule.rejected",
                target_type="supplier_reseller_rule",
                target_id=str(rule.id),
                metadata_json={
                    "supplier_offer_id": offer.id,
                    "reseller_tenant_id": reseller_tenant_id,
                    "reason": reason,
                },
            )
        )
        await session.flush()
        return await self._build_application_summary(session, offer, product, variant, rule)

    async def reject_reseller_application(
        self,
        session: AsyncSession,
        supplier_tenant_id: int,
        supplier_offer_id: int,
        reseller_tenant_id: int,
        actor_user_id: Optional[int],
        reason: Optional[str] = None,
    ) -> ResellerApplicationSummary:
        await self._require_pending_reseller_application(
            session=session,
            supplier_tenant_id=supplier_tenant_id,
            supplier_offer_id=supplier_offer_id,
            reseller_tenant_id=reseller_tenant_id,
        )
        return await self.reject_reseller(
            session=session,
            supplier_tenant_id=supplier_tenant_id,
            supplier_offer_id=supplier_offer_id,
            reseller_tenant_id=reseller_tenant_id,
            actor_user_id=actor_user_id,
            reason=reason,
        )

    async def set_reseller_rule(
        self,
        session: AsyncSession,
        supplier_tenant_id: int,
        supplier_offer_id: int,
        reseller_tenant_id: int,
        actor_user_id: Optional[int],
        pricing_value: Decimal,
        min_sale_price: Optional[Decimal] = None,
    ) -> ResellerApplicationSummary:
        return await self.approve_reseller(
            session=session,
            supplier_tenant_id=supplier_tenant_id,
            supplier_offer_id=supplier_offer_id,
            reseller_tenant_id=reseller_tenant_id,
            actor_user_id=actor_user_id,
            pricing_value=pricing_value,
            min_sale_price=min_sale_price,
        )

    async def set_existing_reseller_rule(
        self,
        session: AsyncSession,
        supplier_tenant_id: int,
        supplier_offer_id: int,
        reseller_tenant_id: int,
        actor_user_id: Optional[int],
        pricing_value: Decimal,
        min_sale_price: Optional[Decimal] = None,
    ) -> ResellerApplicationSummary:
        self._validate_reseller_rule(pricing_value, min_sale_price)
        offer, product, variant = await self._get_supplier_offer_details(session, supplier_tenant_id, supplier_offer_id)
        if offer is None or product is None or variant is None:
            raise ValueError("供货商品不存在或无权限")
        if offer.supplier_tenant_id == reseller_tenant_id:
            raise ValueError("不能设置自己店铺为代理商")
        rule = await self._get_reseller_rule(session, offer.id, reseller_tenant_id)
        if rule is None or rule.status not in {"pending", "active"}:
            raise ValueError("代理关系不存在或不可设置")
        return await self.approve_reseller(
            session=session,
            supplier_tenant_id=supplier_tenant_id,
            supplier_offer_id=supplier_offer_id,
            reseller_tenant_id=reseller_tenant_id,
            actor_user_id=actor_user_id,
            pricing_value=pricing_value,
            min_sale_price=min_sale_price,
        )

    async def list_reseller_applications(
        self,
        session: AsyncSession,
        supplier_tenant_id: int,
        limit: int = 20,
    ) -> List[ResellerApplicationSummary]:
        result = await session.execute(
            select(SupplierResellerRule, SupplierOffer, Product, ProductVariant)
            .join(SupplierOffer, SupplierOffer.id == SupplierResellerRule.supplier_offer_id)
            .join(Product, Product.id == SupplierOffer.product_id)
            .join(ProductVariant, ProductVariant.id == SupplierOffer.variant_id)
            .where(SupplierOffer.supplier_tenant_id == supplier_tenant_id)
            .where(SupplierResellerRule.status == "pending")
            .order_by(SupplierResellerRule.updated_at.desc())
            .limit(self._normalize_limit(limit))
        )
        return [
            await self._build_application_summary(session, offer, product, variant, rule)
            for rule, offer, product, variant in result.all()
        ]

    async def list_supplier_reseller_rules(
        self,
        session: AsyncSession,
        supplier_tenant_id: int,
        limit: int = 20,
    ) -> List[ResellerApplicationSummary]:
        result = await session.execute(
            select(SupplierResellerRule, SupplierOffer, Product, ProductVariant)
            .join(SupplierOffer, SupplierOffer.id == SupplierResellerRule.supplier_offer_id)
            .join(Product, Product.id == SupplierOffer.product_id)
            .join(ProductVariant, ProductVariant.id == SupplierOffer.variant_id)
            .where(SupplierOffer.supplier_tenant_id == supplier_tenant_id)
            .where(SupplierResellerRule.status.in_(("pending", "active")))
            .order_by(SupplierResellerRule.updated_at.desc())
            .limit(self._normalize_limit(limit))
        )
        return [
            await self._build_application_summary(session, offer, product, variant, rule)
            for rule, offer, product, variant in result.all()
        ]

    async def list_my_reseller_applications(
        self,
        session: AsyncSession,
        reseller_tenant_id: int,
        limit: int = 20,
    ) -> List[ResellerApplicationSummary]:
        result = await session.execute(
            select(SupplierResellerRule, SupplierOffer, Product, ProductVariant)
            .join(SupplierOffer, SupplierOffer.id == SupplierResellerRule.supplier_offer_id)
            .join(Product, Product.id == SupplierOffer.product_id)
            .join(ProductVariant, ProductVariant.id == SupplierOffer.variant_id)
            .where(SupplierResellerRule.reseller_tenant_id == reseller_tenant_id)
            .order_by(SupplierResellerRule.updated_at.desc())
            .limit(self._normalize_limit(limit))
        )
        return [
            await self._build_application_summary(session, offer, product, variant, rule)
            for rule, offer, product, variant in result.all()
        ]

    async def create_reseller_product(
        self,
        session: AsyncSession,
        reseller_tenant_id: int,
        supplier_offer_id: int,
        sale_price: Decimal,
        display_name: Optional[str] = None,
    ) -> CreatedResellerProduct:
        sale_price = self._validate_reseller_sale_price(sale_price)

        display_name = self._normalize_display_name(display_name)
        offer, product, variant, rule = await self._get_active_offer_details(session, supplier_offer_id, reseller_tenant_id)
        if offer is None or product is None or variant is None:
            raise ValueError("供货商品不存在或不可代理")
        if offer.supplier_tenant_id == reseller_tenant_id:
            raise ValueError("不能代理自己店铺的供货商品")
        if product.delivery_type not in SUPPORTED_RESELLER_DELIVERY_TYPES:
            raise ValueError("当前代理下单暂不支持该发货类型")
        if not offer.hidden_supplier_allowed:
            raise ValueError("当前版本仅支持隐藏供应商的代理商品")
        self._ensure_reseller_approved(offer, rule)
        supplier_cost = self._effective_supplier_cost(offer, rule)
        min_sale_price = self._effective_min_sale_price(offer, rule)
        if sale_price < supplier_cost:
            raise ValueError(f"代理售价不能低于供应商成本 {supplier_cost} {variant.currency}")
        if min_sale_price is not None and sale_price < min_sale_price:
            raise ValueError(f"代理售价不能低于最低售价 {min_sale_price} {variant.currency}")

        result = await session.execute(
            select(ResellerProduct)
            .where(ResellerProduct.reseller_tenant_id == reseller_tenant_id)
            .where(ResellerProduct.supplier_offer_id == offer.id)
            .limit(1)
        )
        reseller_product = result.scalar_one_or_none()
        if reseller_product is None:
            reseller_product = ResellerProduct(
                reseller_tenant_id=reseller_tenant_id,
                supplier_tenant_id=offer.supplier_tenant_id,
                supplier_offer_id=offer.id,
                status="on",
                sale_price=sale_price,
                display_name=display_name,
                hide_supplier=True,
            )
            session.add(reseller_product)
        else:
            if reseller_product.status == "disabled":
                raise ValueError("代理商品已被平台下架，不能重新上架")
            reseller_product.supplier_tenant_id = offer.supplier_tenant_id
            reseller_product.status = "on"
            reseller_product.sale_price = sale_price
            reseller_product.display_name = display_name
            reseller_product.hide_supplier = True

        await session.flush()
        return CreatedResellerProduct(
            reseller_product_id=reseller_product.id,
            supplier_offer_id=offer.id,
            display_name=reseller_product.display_name or product.name,
            sale_price=reseller_product.sale_price,
            currency=variant.currency,
            status=reseller_product.status,
        )

    async def list_reseller_products(
        self,
        session: AsyncSession,
        reseller_tenant_id: int,
        limit: int = 20,
    ) -> List[ResellerProductSummary]:
        available_counts = self._available_count_subquery()
        result = await session.execute(
            select(ResellerProduct, Product, ProductVariant, func.coalesce(available_counts.c.available_count, 0))
            .join(SupplierOffer, SupplierOffer.id == ResellerProduct.supplier_offer_id)
            .join(Product, Product.id == SupplierOffer.product_id)
            .join(ProductVariant, ProductVariant.id == SupplierOffer.variant_id)
            .join(Tenant, Tenant.id == SupplierOffer.supplier_tenant_id)
            .outerjoin(
                available_counts,
                and_(
                    available_counts.c.tenant_id == ResellerProduct.supplier_tenant_id,
                    available_counts.c.product_id == SupplierOffer.product_id,
                ),
            )
            .where(ResellerProduct.reseller_tenant_id == reseller_tenant_id)
            .order_by(ResellerProduct.sort_order.asc(), ResellerProduct.created_at.desc())
            .limit(self._normalize_limit(limit))
        )
        return [
            ResellerProductSummary(
                reseller_product_id=reseller_product.id,
                supplier_offer_id=reseller_product.supplier_offer_id,
                display_name=reseller_product.display_name or product.name,
                category=reseller_product.category,
                sort_order=int(reseller_product.sort_order or 0),
                delivery_type=product.delivery_type,
                sale_price=reseller_product.sale_price,
                currency=variant.currency,
                status=reseller_product.status,
                available_count=int(available_count or 0),
            )
            for reseller_product, product, variant, available_count in result.all()
        ]

    async def update_reseller_product_metadata(
        self,
        session: AsyncSession,
        reseller_tenant_id: int,
        reseller_product_id: int,
        *,
        category: Optional[str],
        category_provided: bool,
        sort_order: Optional[int],
    ) -> ResellerProductSummary:
        normalized_product_id = self._normalize_positive_int(reseller_product_id, "代理商品 ID")
        if not category_provided and sort_order is None:
            raise ValueError("代理商品元数据参数无效")
        normalized_category = (
            self._normalize_reseller_product_category(category) if category_provided else None
        )
        normalized_sort_order = (
            self._normalize_reseller_product_sort_order(sort_order) if sort_order is not None else None
        )
        result = await session.execute(
            select(ResellerProduct)
            .where(ResellerProduct.id == normalized_product_id)
            .where(ResellerProduct.reseller_tenant_id == reseller_tenant_id)
            .where(ResellerProduct.status != "deleted")
            .limit(1)
        )
        reseller_product = result.scalar_one_or_none()
        if reseller_product is None:
            raise ValueError("代理商品不存在或无权限")
        if category_provided:
            reseller_product.category = normalized_category
        if normalized_sort_order is not None:
            reseller_product.sort_order = normalized_sort_order
        await session.flush()

        summary = await self.get_reseller_product_summary(
            session=session,
            reseller_tenant_id=reseller_tenant_id,
            reseller_product_id=normalized_product_id,
        )
        if summary is None:
            raise ValueError("代理商品不存在或无权限")
        return summary

    async def update_reseller_product_sales(
        self,
        session: AsyncSession,
        reseller_tenant_id: int,
        reseller_product_id: int,
        *,
        sale_price: Optional[Decimal],
        display_name: Optional[str],
        display_name_provided: bool,
    ) -> ResellerProductSummary:
        normalized_product_id = self._normalize_positive_int(reseller_product_id, "代理商品 ID")
        if sale_price is None and not display_name_provided:
            raise ValueError("代理商品销售参数无效")
        normalized_display_name = (
            self._normalize_display_name(display_name) if display_name_provided else None
        )
        normalized_sale_price = (
            self._validate_reseller_sale_price(sale_price) if sale_price is not None else None
        )

        result = await session.execute(
            select(ResellerProduct, SupplierOffer, ProductVariant, SupplierResellerRule)
            .join(SupplierOffer, SupplierOffer.id == ResellerProduct.supplier_offer_id)
            .join(ProductVariant, ProductVariant.id == SupplierOffer.variant_id)
            .outerjoin(
                SupplierResellerRule,
                and_(
                    SupplierResellerRule.supplier_offer_id == SupplierOffer.id,
                    SupplierResellerRule.reseller_tenant_id == ResellerProduct.reseller_tenant_id,
                    SupplierResellerRule.status == "active",
                ),
            )
            .where(ResellerProduct.id == normalized_product_id)
            .where(ResellerProduct.reseller_tenant_id == reseller_tenant_id)
            .where(ResellerProduct.status != "deleted")
            .limit(1)
        )
        row = result.first()
        if row is None:
            raise ValueError("代理商品不存在或无权限")
        reseller_product, offer, variant, rule = row
        if reseller_product.status == "disabled":
            raise ValueError("代理商品已被平台下架，不能修改销售信息")
        if normalized_sale_price is not None:
            supplier_cost = self._effective_supplier_cost(offer, rule)
            min_sale_price = self._effective_min_sale_price(offer, rule)
            if normalized_sale_price < supplier_cost:
                raise ValueError(f"代理售价不能低于供应商成本 {supplier_cost} {variant.currency}")
            if min_sale_price is not None and normalized_sale_price < min_sale_price:
                raise ValueError(f"代理售价不能低于最低售价 {min_sale_price} {variant.currency}")
            reseller_product.sale_price = normalized_sale_price
        if display_name_provided:
            reseller_product.display_name = normalized_display_name
        await session.flush()

        summary = await self.get_reseller_product_summary(
            session=session,
            reseller_tenant_id=reseller_tenant_id,
            reseller_product_id=normalized_product_id,
        )
        if summary is None:
            raise ValueError("代理商品不存在或无权限")
        return summary

    async def get_reseller_product_summary(
        self,
        session: AsyncSession,
        reseller_tenant_id: int,
        reseller_product_id: int,
    ) -> Optional[ResellerProductSummary]:
        available_counts = self._available_count_subquery()
        result = await session.execute(
            select(ResellerProduct, Product, ProductVariant, func.coalesce(available_counts.c.available_count, 0))
            .join(SupplierOffer, SupplierOffer.id == ResellerProduct.supplier_offer_id)
            .join(Product, Product.id == SupplierOffer.product_id)
            .join(ProductVariant, ProductVariant.id == SupplierOffer.variant_id)
            .outerjoin(
                available_counts,
                and_(
                    available_counts.c.tenant_id == ResellerProduct.supplier_tenant_id,
                    available_counts.c.product_id == SupplierOffer.product_id,
                ),
            )
            .where(ResellerProduct.id == reseller_product_id)
            .where(ResellerProduct.reseller_tenant_id == reseller_tenant_id)
            .where(ResellerProduct.status != "deleted")
            .limit(1)
        )
        row = result.first()
        if row is None:
            return None
        reseller_product, product, variant, available_count = row
        return ResellerProductSummary(
            reseller_product_id=reseller_product.id,
            supplier_offer_id=reseller_product.supplier_offer_id,
            display_name=reseller_product.display_name or product.name,
            category=reseller_product.category,
            sort_order=int(reseller_product.sort_order or 0),
            delivery_type=product.delivery_type,
            sale_price=reseller_product.sale_price,
            currency=variant.currency,
            status=reseller_product.status,
            available_count=int(available_count or 0),
        )

    async def list_public_reseller_products(
        self,
        session: AsyncSession,
        reseller_tenant_id: int,
        limit: int = 20,
    ) -> List[PublicResellerProductSummary]:
        available_counts = self._available_count_subquery()
        result = await session.execute(
            select(ResellerProduct, Product, ProductVariant, func.coalesce(available_counts.c.available_count, 0))
            .join(SupplierOffer, SupplierOffer.id == ResellerProduct.supplier_offer_id)
            .join(Product, Product.id == SupplierOffer.product_id)
            .join(ProductVariant, ProductVariant.id == SupplierOffer.variant_id)
            .outerjoin(
                available_counts,
                and_(
                    available_counts.c.tenant_id == ResellerProduct.supplier_tenant_id,
                    available_counts.c.product_id == SupplierOffer.product_id,
                ),
            )
            .outerjoin(
                SupplierResellerRule,
                and_(
                    SupplierResellerRule.supplier_offer_id == SupplierOffer.id,
                    SupplierResellerRule.reseller_tenant_id == ResellerProduct.reseller_tenant_id,
                ),
            )
            .where(ResellerProduct.reseller_tenant_id == reseller_tenant_id)
            .where(ResellerProduct.status == "on")
            .where(ResellerProduct.hide_supplier.is_(True))
            .where(SupplierOffer.status == "on")
            .where(or_(SupplierOffer.requires_approval.is_(False), SupplierResellerRule.status == "active"))
            .where(SupplierOffer.hidden_supplier_allowed.is_(True))
            .where(Tenant.status.in_(ACTIVE_TENANT_STATUSES))
            .where(Product.status == "on")
            .where(Product.delivery_type.in_(SUPPORTED_RESELLER_DELIVERY_TYPES))
            .where(ProductVariant.status == "on")
            .order_by(ResellerProduct.sort_order.asc(), ResellerProduct.created_at.desc())
            .limit(self._normalize_limit(limit))
        )
        return [
            PublicResellerProductSummary(
                reseller_product_id=reseller_product.id,
                display_name=reseller_product.display_name or product.name,
                category=reseller_product.category,
                delivery_type=product.delivery_type,
                sale_price=reseller_product.sale_price,
                currency=variant.currency,
                available_count=int(available_count or 0),
            )
            for reseller_product, product, variant, available_count in result.all()
        ]

    async def _get_supplier_product(
        self,
        session: AsyncSession,
        supplier_tenant_id: int,
        product_id: int,
    ) -> tuple[Optional[Product], Optional[ProductVariant]]:
        result = await session.execute(
            select(Product, ProductVariant)
            .outerjoin(
                ProductVariant,
                (ProductVariant.product_id == Product.id)
                & (ProductVariant.tenant_id == supplier_tenant_id)
                & (ProductVariant.sort_order == 0),
            )
            .where(Product.id == product_id)
            .where(Product.tenant_id == supplier_tenant_id)
            .where(Product.status != "deleted")
        )
        row = result.first()
        if row is None:
            return None, None
        return row[0], row[1]

    async def _get_supplier_offer(
        self,
        session: AsyncSession,
        supplier_tenant_id: int,
        supplier_offer_id: int,
    ) -> Optional[SupplierOffer]:
        result = await session.execute(
            select(SupplierOffer)
            .where(SupplierOffer.id == supplier_offer_id)
            .where(SupplierOffer.supplier_tenant_id == supplier_tenant_id)
            .where(SupplierOffer.status != "deleted")
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _get_platform_supplier_offer_details(
        self,
        session: AsyncSession,
        supplier_offer_id: int,
    ) -> Optional[tuple[SupplierOffer, Tenant, Product, ProductVariant, int]]:
        available_counts = self._available_count_subquery()
        result = await session.execute(
            select(
                SupplierOffer,
                Tenant,
                Product,
                ProductVariant,
                func.coalesce(available_counts.c.available_count, 0),
            )
            .join(Tenant, Tenant.id == SupplierOffer.supplier_tenant_id)
            .join(Product, Product.id == SupplierOffer.product_id)
            .join(ProductVariant, ProductVariant.id == SupplierOffer.variant_id)
            .outerjoin(
                available_counts,
                and_(
                    available_counts.c.tenant_id == SupplierOffer.supplier_tenant_id,
                    available_counts.c.product_id == SupplierOffer.product_id,
                ),
            )
            .where(SupplierOffer.id == supplier_offer_id)
            .where(SupplierOffer.status != "deleted")
            .where(Product.status != "deleted")
            .limit(1)
        )
        row = result.first()
        if row is None:
            return None
        offer, tenant, product, variant, available_count = row
        return offer, tenant, product, variant, int(available_count or 0)

    async def _get_offer_details(
        self,
        session: AsyncSession,
        supplier_offer_id: int,
    ) -> tuple[Optional[SupplierOffer], Optional[Product], Optional[ProductVariant]]:
        result = await session.execute(
            select(SupplierOffer, Product, ProductVariant)
            .join(Product, Product.id == SupplierOffer.product_id)
            .join(ProductVariant, ProductVariant.id == SupplierOffer.variant_id)
            .join(Tenant, Tenant.id == SupplierOffer.supplier_tenant_id)
            .where(SupplierOffer.id == supplier_offer_id)
            .where(SupplierOffer.status == "on")
            .where(Tenant.status.in_(ACTIVE_TENANT_STATUSES))
            .where(Product.status == "on")
            .where(ProductVariant.status == "on")
            .limit(1)
        )
        row = result.first()
        if row is None:
            return None, None, None
        return row[0], row[1], row[2]

    async def _get_supplier_offer_details(
        self,
        session: AsyncSession,
        supplier_tenant_id: int,
        supplier_offer_id: int,
    ) -> tuple[Optional[SupplierOffer], Optional[Product], Optional[ProductVariant]]:
        offer, product, variant = await self._get_offer_details(session, supplier_offer_id)
        if offer is None or offer.supplier_tenant_id != supplier_tenant_id:
            return None, None, None
        return offer, product, variant

    async def _get_active_offer_details(
        self,
        session: AsyncSession,
        supplier_offer_id: int,
        reseller_tenant_id: int,
    ) -> tuple[Optional[SupplierOffer], Optional[Product], Optional[ProductVariant], Optional[SupplierResellerRule]]:
        result = await session.execute(
            select(SupplierOffer, Product, ProductVariant, SupplierResellerRule)
            .join(Product, Product.id == SupplierOffer.product_id)
            .join(ProductVariant, ProductVariant.id == SupplierOffer.variant_id)
            .join(Tenant, Tenant.id == SupplierOffer.supplier_tenant_id)
            .outerjoin(
                SupplierResellerRule,
                and_(
                    SupplierResellerRule.supplier_offer_id == SupplierOffer.id,
                    SupplierResellerRule.reseller_tenant_id == reseller_tenant_id,
                ),
            )
            .where(SupplierOffer.id == supplier_offer_id)
            .where(SupplierOffer.status == "on")
            .where(Tenant.status.in_(ACTIVE_TENANT_STATUSES))
            .where(Product.status == "on")
            .where(ProductVariant.status == "on")
            .limit(1)
        )
        row = result.first()
        if row is None:
            return None, None, None, None
        return row[0], row[1], row[2], row[3]

    async def _get_reseller_rule(
        self,
        session: AsyncSession,
        supplier_offer_id: int,
        reseller_tenant_id: int,
    ) -> Optional[SupplierResellerRule]:
        result = await session.execute(
            select(SupplierResellerRule)
            .where(SupplierResellerRule.supplier_offer_id == supplier_offer_id)
            .where(SupplierResellerRule.reseller_tenant_id == reseller_tenant_id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _require_pending_reseller_application(
        self,
        session: AsyncSession,
        supplier_tenant_id: int,
        supplier_offer_id: int,
        reseller_tenant_id: int,
    ) -> None:
        offer, product, variant = await self._get_supplier_offer_details(session, supplier_tenant_id, supplier_offer_id)
        if offer is None or product is None or variant is None:
            raise ValueError("供货商品不存在或无权限")
        if offer.supplier_tenant_id == reseller_tenant_id:
            raise ValueError("不能审批自己店铺为代理商")
        rule = await self._get_reseller_rule(session, offer.id, reseller_tenant_id)
        if rule is None or rule.status != "pending":
            raise ValueError("代理申请不存在或不可审批")

    async def _build_application_summary(
        self,
        session: AsyncSession,
        offer: SupplierOffer,
        product: Product,
        variant: ProductVariant,
        rule: SupplierResellerRule,
    ) -> ResellerApplicationSummary:
        supplier_store_name = await self._tenant_store_name(session, offer.supplier_tenant_id)
        reseller_store_name = await self._tenant_store_name(session, rule.reseller_tenant_id)
        return ResellerApplicationSummary(
            rule_id=rule.id,
            supplier_offer_id=offer.id,
            supplier_tenant_id=offer.supplier_tenant_id,
            supplier_store_name=supplier_store_name,
            reseller_tenant_id=rule.reseller_tenant_id,
            reseller_store_name=reseller_store_name,
            product_name=product.name,
            status=rule.status,
            pricing_value=rule.pricing_value,
            min_sale_price=rule.min_sale_price,
            currency=variant.currency,
            updated_at=rule.updated_at,
        )

    async def _tenant_store_name(self, session: AsyncSession, tenant_id: int) -> str:
        store_name = await session.scalar(select(Tenant.store_name).where(Tenant.id == tenant_id))
        return store_name or f"租户 {tenant_id}"

    @staticmethod
    def _platform_supplier_offer_summary(
        offer: SupplierOffer,
        tenant: Tenant,
        product: Product,
        variant: ProductVariant,
        available_count: int,
    ) -> PlatformSupplierOfferSummary:
        return PlatformSupplierOfferSummary(
            supplier_offer_id=offer.id,
            supplier_tenant_id=offer.supplier_tenant_id,
            supplier_store_name=tenant.store_name,
            product_name=product.name,
            delivery_type=product.delivery_type,
            suggested_price=offer.suggested_price,
            min_sale_price=offer.min_sale_price,
            supplier_cost=offer.default_pricing_value,
            currency=variant.currency,
            available_count=available_count,
            requires_approval=offer.requires_approval,
            status=offer.status,
            created_at=offer.created_at,
            updated_at=offer.updated_at,
        )

    @staticmethod
    def _available_count_subquery():
        return (
            select(
                InventoryItem.tenant_id.label("tenant_id"),
                InventoryItem.product_id.label("product_id"),
                func.count(InventoryItem.id).label("available_count"),
            )
            .where(InventoryItem.status == "available")
            .group_by(InventoryItem.tenant_id, InventoryItem.product_id)
            .subquery()
        )

    @staticmethod
    def _validate_suggested_price(suggested_price: Decimal, min_sale_price: Optional[Decimal]) -> None:
        if suggested_price <= 0:
            raise ValueError("建议价必须大于 0")
        if min_sale_price is None:
            return
        if min_sale_price < 0:
            raise ValueError("最低售价不能小于 0")
        if min_sale_price > suggested_price:
            raise ValueError("最低售价不能高于建议价")

    @staticmethod
    def _validate_reseller_rule(pricing_value: Decimal, min_sale_price: Optional[Decimal]) -> None:
        if pricing_value <= 0:
            raise ValueError("供应商成本必须大于 0")
        if pricing_value.as_tuple().exponent < -8:
            raise ValueError("供应商成本最多支持 8 位小数")
        if min_sale_price is None:
            return
        if min_sale_price < 0:
            raise ValueError("最低售价不能小于 0")
        if min_sale_price.as_tuple().exponent < -8:
            raise ValueError("最低售价最多支持 8 位小数")

    @staticmethod
    def _validate_reseller_sale_price(sale_price: Decimal) -> Decimal:
        if (
            not isinstance(sale_price, Decimal)
            or not sale_price.is_finite()
            or sale_price <= 0
        ):
            raise ValueError("代理售价必须大于 0")
        if sale_price.as_tuple().exponent < -8:
            raise ValueError("代理售价最多支持 8 位小数")
        return sale_price

    @staticmethod
    def _normalize_display_name(display_name: Optional[str]) -> Optional[str]:
        if display_name is None:
            return None
        normalized = display_name.strip()
        if not normalized:
            return None
        if len(normalized) > 255:
            raise ValueError("代理商品展示名不能超过 255 个字符")
        return normalized

    @staticmethod
    def _normalize_reseller_product_category(category: Optional[str]) -> Optional[str]:
        if category is None:
            return None
        if not isinstance(category, str):
            raise ValueError("代理商品分类必须是字符串")
        normalized = category.strip()
        if not normalized or normalized == "-":
            return None
        if len(normalized) > 128:
            raise ValueError("代理商品分类不能超过 128 个字符")
        if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
            raise ValueError("代理商品分类不能包含控制字符")
        return normalized

    @staticmethod
    def _normalize_reseller_product_sort_order(sort_order: Optional[int]) -> int:
        if isinstance(sort_order, bool) or not isinstance(sort_order, int):
            raise ValueError("代理商品排序必须是整数")
        if sort_order < -100000 or sort_order > 100000:
            raise ValueError("代理商品排序超出范围")
        return sort_order

    @classmethod
    def _normalize_platform_supplier_offer_status(cls, status: Optional[str], *, allow_all: bool) -> Optional[str]:
        if status is None:
            return None
        normalized = status.strip().lower()
        if allow_all and normalized in {"", "all"}:
            return None
        if normalized not in cls.PLATFORM_SUPPLIER_OFFER_STATUSES:
            raise ValueError("供货商品状态无效")
        return normalized

    @staticmethod
    def _normalize_optional_positive_int(value: Optional[int], field_name: str) -> Optional[int]:
        if value is None:
            return None
        return SupplyService._normalize_positive_int(value, field_name)

    @staticmethod
    def _normalize_positive_int(value: int, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field_name} 必须是正整数")
        return value

    @staticmethod
    def _safe_platform_supply_reason(reason: Optional[str]) -> Optional[str]:
        if reason is None:
            return None
        normalized = reason.strip()
        if not normalized:
            return None
        lowered = normalized.lower()
        sensitive_markers = (
            "token",
            "secret",
            "api_key",
            "apikey",
            "authorization",
            "cookie",
            "password",
            "private_key",
            "payload",
            "http://",
            "https://",
        )
        if any(marker in lowered for marker in sensitive_markers):
            return "内容已隐藏"
        return normalized[:255]

    @staticmethod
    def _normalize_limit(limit: int) -> int:
        return min(max(limit, 1), 50)

    @staticmethod
    def _normalize_market_query(query: Optional[str]) -> Optional[str]:
        if query is None:
            return None
        if not isinstance(query, str):
            raise ValueError("供货市场关键词无效")
        normalized = query.strip()
        if not normalized:
            return None
        if len(normalized) > 64:
            raise ValueError("供货市场关键词不能超过 64 个字符")
        if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
            raise ValueError("供货市场关键词不能包含控制字符")
        return normalized

    @staticmethod
    def _normalize_market_delivery_type(delivery_type: Optional[str]) -> Optional[str]:
        if delivery_type is None or delivery_type == "all":
            return None
        normalized = str(delivery_type).strip()
        if normalized not in SUPPORTED_RESELLER_DELIVERY_TYPES:
            raise ValueError("供货市场发货类型无效")
        return normalized

    @staticmethod
    def _normalize_market_category(category: Optional[str]) -> Optional[str]:
        if category is None:
            return None
        if not isinstance(category, str):
            raise ValueError("供货市场分类无效")
        normalized = category.strip()
        if not normalized or normalized == "all":
            return None
        if len(normalized) > 128:
            raise ValueError("供货市场分类不能超过 128 个字符")
        if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
            raise ValueError("供货市场分类不能包含控制字符")
        return normalized

    @staticmethod
    def _normalize_market_access(access: Optional[str]) -> Optional[str]:
        if access is None or access == "all":
            return None
        normalized = str(access).strip()
        allowed = {"open", "approval_required", "pending", "active", "rejected", "ready"}
        if normalized not in allowed:
            raise ValueError("供货市场审批状态无效")
        return normalized

    @staticmethod
    def _normalize_market_stock(stock: Optional[str]) -> Optional[str]:
        if stock is None or stock == "all":
            return None
        normalized = str(stock).strip()
        if normalized not in {"available", "empty"}:
            raise ValueError("供货市场库存状态无效")
        return normalized

    @staticmethod
    def _normalize_optional_price(value: Optional[Decimal], field_name: str) -> Optional[Decimal]:
        if value is None:
            return None
        if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
            raise ValueError(f"{field_name}无效")
        return value

    @staticmethod
    def _market_offer_price_in_range(
        offer: SupplierOfferSummary,
        *,
        min_price: Optional[Decimal],
        max_price: Optional[Decimal],
    ) -> bool:
        price = offer.effective_min_sale_price or offer.suggested_price
        if min_price is not None and price < min_price:
            return False
        if max_price is not None and price > max_price:
            return False
        return True

    @staticmethod
    def _fixed_supplier_cost(offer: SupplierOffer) -> Decimal:
        if offer.default_pricing_mode != "fixed_cost":
            raise ValueError("当前版本仅支持固定供应商成本")
        if offer.default_pricing_value <= 0:
            raise ValueError("供应商成本必须大于 0")
        return offer.default_pricing_value

    @staticmethod
    def _ensure_reseller_approved(offer: SupplierOffer, rule: Optional[SupplierResellerRule]) -> None:
        if not offer.requires_approval:
            return
        if rule is None:
            raise ValueError("该供货商品需要先申请并获得审批。申请：/apply_reseller 供货ID")
        if rule.status == "pending":
            raise ValueError("该供货商品正在等待供应商审批。")
        if rule.status == "rejected":
            raise ValueError("该供货商品的代理申请已被拒绝。")
        if rule.status != "active":
            raise ValueError("该供货商品的代理权限不可用。")

    def _effective_supplier_cost(self, offer: SupplierOffer, rule: Optional[SupplierResellerRule]) -> Decimal:
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
