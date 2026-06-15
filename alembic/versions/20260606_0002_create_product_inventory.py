from __future__ import annotations

"""create product inventory

Revision ID: 20260606_0002
Revises: 20260606_0001
Create Date: 2026-06-06
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260606_0002"
down_revision: Optional[str] = "20260606_0001"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("product_type", sa.String(length=32), nullable=False, server_default="self"),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("cover_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("review_status", sa.String(length=32), nullable=False, server_default="none"),
        sa.Column("suggested_price", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=16), nullable=False, server_default="USDT"),
        sa.Column("delivery_type", sa.String(length=32), nullable=False),
        sa.Column("file_size_limit", sa.BigInteger(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_products_tenant_status_sort", "products", ["tenant_id", "status", "sort_order"])
    op.create_index("ix_products_tenant_delivery_type", "products", ["tenant_id", "delivery_type"])
    op.create_index("ix_products_tenant_review_status", "products", ["tenant_id", "review_status"])

    op.create_table(
        "product_variants",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("product_id", sa.BigInteger(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("price", sa.Numeric(20, 8), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False, server_default="USDT"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="on"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_product_variants_tenant_product_status_sort",
        "product_variants",
        ["tenant_id", "product_id", "status", "sort_order"],
    )

    op.create_table(
        "inventory_items",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("product_id", sa.BigInteger(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("variant_id", sa.BigInteger(), sa.ForeignKey("product_variants.id"), nullable=True),
        sa.Column("content_encrypted", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="available"),
        sa.Column("locked_by_order_id", sa.BigInteger(), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_by_order_id", sa.BigInteger(), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "tenant_id",
            "product_id",
            "variant_id",
            "content_hash",
            name="uq_inventory_items_tenant_product_variant_hash",
        ),
    )
    op.create_index(
        "ix_inventory_items_tenant_product_variant_status",
        "inventory_items",
        ["tenant_id", "product_id", "variant_id", "status"],
    )
    op.create_index("ix_inventory_items_locked_by_order_id", "inventory_items", ["locked_by_order_id"])
    op.create_index("ix_inventory_items_used_by_order_id", "inventory_items", ["used_by_order_id"])

    op.create_table(
        "uploaded_files",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("owner_user_id", sa.BigInteger(), sa.ForeignKey("platform_users.id"), nullable=True),
        sa.Column("storage_key", sa.Text(), nullable=False, unique=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_uploaded_files_tenant_purpose_status", "uploaded_files", ["tenant_id", "purpose", "status"])
    op.create_index("ix_uploaded_files_sha256", "uploaded_files", ["sha256"])

    op.create_table(
        "file_processing_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("requested_by_user_id", sa.BigInteger(), sa.ForeignKey("platform_users.id"), nullable=False),
        sa.Column("source_file_id", sa.BigInteger(), sa.ForeignKey("uploaded_files.id"), nullable=True),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_file_id", sa.BigInteger(), sa.ForeignKey("uploaded_files.id"), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_file_processing_jobs_tenant_status", "file_processing_jobs", ["tenant_id", "status"])
    op.create_index(
        "ix_file_processing_jobs_requested_by_status",
        "file_processing_jobs",
        ["requested_by_user_id", "status"],
    )

    op.create_table(
        "file_archive_entries",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("uploaded_file_id", sa.BigInteger(), sa.ForeignKey("uploaded_files.id"), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("detected_type", sa.String(length=128), nullable=True),
        sa.Column("risk_level", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_file_archive_entries_tenant_uploaded_file",
        "file_archive_entries",
        ["tenant_id", "uploaded_file_id"],
    )
    op.create_index("ix_file_archive_entries_risk_level", "file_archive_entries", ["risk_level"])


def downgrade() -> None:
    op.drop_index("ix_file_archive_entries_risk_level", table_name="file_archive_entries")
    op.drop_index("ix_file_archive_entries_tenant_uploaded_file", table_name="file_archive_entries")
    op.drop_table("file_archive_entries")
    op.drop_index("ix_file_processing_jobs_requested_by_status", table_name="file_processing_jobs")
    op.drop_index("ix_file_processing_jobs_tenant_status", table_name="file_processing_jobs")
    op.drop_table("file_processing_jobs")
    op.drop_index("ix_uploaded_files_sha256", table_name="uploaded_files")
    op.drop_index("ix_uploaded_files_tenant_purpose_status", table_name="uploaded_files")
    op.drop_table("uploaded_files")
    op.drop_index("ix_inventory_items_used_by_order_id", table_name="inventory_items")
    op.drop_index("ix_inventory_items_locked_by_order_id", table_name="inventory_items")
    op.drop_index("ix_inventory_items_tenant_product_variant_status", table_name="inventory_items")
    op.drop_table("inventory_items")
    op.drop_index("ix_product_variants_tenant_product_status_sort", table_name="product_variants")
    op.drop_table("product_variants")
    op.drop_index("ix_products_tenant_review_status", table_name="products")
    op.drop_index("ix_products_tenant_delivery_type", table_name="products")
    op.drop_index("ix_products_tenant_status_sort", table_name="products")
    op.drop_table("products")
