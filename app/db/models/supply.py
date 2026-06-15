from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class SupplierOffer(TimestampMixin, Base):
    __tablename__ = "supplier_offers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    supplier_tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    variant_id: Mapped[Optional[int]] = mapped_column(ForeignKey("product_variants.id"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="on")
    suggested_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    min_sale_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8))
    default_pricing_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    default_pricing_value: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=0)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hidden_supplier_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SupplierResellerRule(TimestampMixin, Base):
    __tablename__ = "supplier_reseller_rules"
    __table_args__ = (
        UniqueConstraint("supplier_offer_id", "reseller_tenant_id", name="uq_supplier_rules_offer_reseller"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    supplier_offer_id: Mapped[int] = mapped_column(ForeignKey("supplier_offers.id"), nullable=False)
    reseller_tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    pricing_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    pricing_value: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    min_sale_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")


class ResellerProduct(TimestampMixin, Base):
    __tablename__ = "reseller_products"
    __table_args__ = (
        UniqueConstraint("reseller_tenant_id", "supplier_offer_id", name="uq_reseller_products_reseller_offer"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    reseller_tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    supplier_tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    supplier_offer_id: Mapped[int] = mapped_column(ForeignKey("supplier_offers.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="on")
    sale_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(255))
    display_description: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(String(128))
    hide_supplier: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


Index("ix_supplier_offers_supplier_status", SupplierOffer.supplier_tenant_id, SupplierOffer.status)
Index("ix_supplier_offers_product_id", SupplierOffer.product_id)
Index("ix_supplier_rules_reseller_status", SupplierResellerRule.reseller_tenant_id, SupplierResellerRule.status)
Index("ix_reseller_products_reseller_status_sort", ResellerProduct.reseller_tenant_id, ResellerProduct.status, ResellerProduct.sort_order)
Index("ix_reseller_products_reseller_category_sort", ResellerProduct.reseller_tenant_id, ResellerProduct.category, ResellerProduct.sort_order)
Index("ix_reseller_products_supplier_tenant_id", ResellerProduct.supplier_tenant_id)
