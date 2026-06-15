from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class Product(TimestampMixin, Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    product_type: Mapped[str] = mapped_column(String(32), nullable=False, default="self")
    external_source: Mapped[Optional[str]] = mapped_column(String(64))
    source_key: Mapped[str] = mapped_column(String(128), nullable=False, default="", server_default="")
    external_id: Mapped[Optional[str]] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(128))
    description: Mapped[Optional[str]] = mapped_column(Text)
    cover_url: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    suggested_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(16), nullable=False, default="USDT")
    delivery_type: Mapped[str] = mapped_column(String(32), nullable=False)
    delivery_file_id: Mapped[Optional[int]] = mapped_column(ForeignKey("uploaded_files.id"))
    telegram_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    file_size_limit: Mapped[Optional[int]] = mapped_column(BigInteger)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ProductVariant(TimestampMixin, Base):
    __tablename__ = "product_variants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False, default="USDT")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="on")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class InventoryItem(TimestampMixin, Base):
    __tablename__ = "inventory_items"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "product_id",
            "variant_id",
            "content_hash",
            name="uq_inventory_items_tenant_product_variant_hash",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    variant_id: Mapped[Optional[int]] = mapped_column(ForeignKey("product_variants.id"))
    content_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="available")
    locked_by_order_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    used_by_order_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class UploadedFile(TimestampMixin, Base):
    __tablename__ = "uploaded_files"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    owner_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("platform_users.id"))
    storage_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[Optional[str]] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")


class FileProcessingJob(TimestampMixin, Base):
    __tablename__ = "file_processing_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    requested_by_user_id: Mapped[int] = mapped_column(ForeignKey("platform_users.id"), nullable=False)
    source_file_id: Mapped[Optional[int]] = mapped_column(ForeignKey("uploaded_files.id"))
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_file_id: Mapped[Optional[int]] = mapped_column(ForeignKey("uploaded_files.id"))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class FileArchiveEntry(Base):
    __tablename__ = "file_archive_entries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    uploaded_file_id: Mapped[int] = mapped_column(ForeignKey("uploaded_files.id"), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[Optional[str]] = mapped_column(String(64))
    detected_type: Mapped[Optional[str]] = mapped_column(String(128))
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


Index("ix_products_tenant_status_sort", Product.tenant_id, Product.status, Product.sort_order)
Index("ix_products_tenant_category_sort", Product.tenant_id, Product.category, Product.sort_order)
Index("ix_products_tenant_delivery_type", Product.tenant_id, Product.delivery_type)
Index("ix_products_tenant_review_status", Product.tenant_id, Product.review_status)
Index("ix_products_tenant_external_source", Product.tenant_id, Product.external_source)
Index(
    "uq_products_tenant_external_identity",
    Product.tenant_id,
    Product.external_source,
    Product.source_key,
    Product.external_id,
    unique=True,
    postgresql_where=Product.external_source.is_not(None) & Product.external_id.is_not(None),
)
Index("ix_products_delivery_file_id", Product.delivery_file_id)
Index("ix_products_telegram_chat_id", Product.telegram_chat_id)
Index("ix_product_variants_tenant_product_status_sort", ProductVariant.tenant_id, ProductVariant.product_id, ProductVariant.status, ProductVariant.sort_order)
Index("ix_inventory_items_tenant_product_variant_status", InventoryItem.tenant_id, InventoryItem.product_id, InventoryItem.variant_id, InventoryItem.status)
Index("ix_inventory_items_locked_by_order_id", InventoryItem.locked_by_order_id)
Index("ix_inventory_items_used_by_order_id", InventoryItem.used_by_order_id)
Index("ix_uploaded_files_tenant_purpose_status", UploadedFile.tenant_id, UploadedFile.purpose, UploadedFile.status)
Index("ix_uploaded_files_sha256", UploadedFile.sha256)
Index("ix_file_processing_jobs_tenant_status", FileProcessingJob.tenant_id, FileProcessingJob.status)
Index("ix_file_processing_jobs_requested_by_status", FileProcessingJob.requested_by_user_id, FileProcessingJob.status)
Index("ix_file_archive_entries_tenant_uploaded_file", FileArchiveEntry.tenant_id, FileArchiveEntry.uploaded_file_id)
Index("ix_file_archive_entries_risk_level", FileArchiveEntry.risk_level)
