from __future__ import annotations

"""create supply reseller

Revision ID: 20260606_0009
Revises: 20260606_0008
Create Date: 2026-06-06
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260606_0009"
down_revision: Optional[str] = "20260606_0008"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.create_table(
        "supplier_offers",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("supplier_tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("product_id", sa.BigInteger(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("variant_id", sa.BigInteger(), sa.ForeignKey("product_variants.id"), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="on"),
        sa.Column("suggested_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("min_sale_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("default_pricing_mode", sa.String(length=32), nullable=False),
        sa.Column("default_pricing_value", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("hidden_supplier_allowed", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_supplier_offers_supplier_status", "supplier_offers", ["supplier_tenant_id", "status"])
    op.create_index("ix_supplier_offers_product_id", "supplier_offers", ["product_id"])

    op.create_table(
        "supplier_reseller_rules",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("supplier_offer_id", sa.BigInteger(), sa.ForeignKey("supplier_offers.id"), nullable=False),
        sa.Column("reseller_tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("pricing_mode", sa.String(length=32), nullable=False),
        sa.Column("pricing_value", sa.Numeric(20, 8), nullable=False),
        sa.Column("min_sale_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("supplier_offer_id", "reseller_tenant_id", name="uq_supplier_rules_offer_reseller"),
    )
    op.create_index("ix_supplier_rules_reseller_status", "supplier_reseller_rules", ["reseller_tenant_id", "status"])

    op.create_table(
        "reseller_products",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("reseller_tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("supplier_tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("supplier_offer_id", sa.BigInteger(), sa.ForeignKey("supplier_offers.id"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="on"),
        sa.Column("sale_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("display_description", sa.Text(), nullable=True),
        sa.Column("hide_supplier", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("reseller_tenant_id", "supplier_offer_id", name="uq_reseller_products_reseller_offer"),
    )
    op.create_index("ix_reseller_products_reseller_status_sort", "reseller_products", ["reseller_tenant_id", "status", "sort_order"])
    op.create_index("ix_reseller_products_supplier_tenant_id", "reseller_products", ["supplier_tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_reseller_products_supplier_tenant_id", table_name="reseller_products")
    op.drop_index("ix_reseller_products_reseller_status_sort", table_name="reseller_products")
    op.drop_table("reseller_products")
    op.drop_index("ix_supplier_rules_reseller_status", table_name="supplier_reseller_rules")
    op.drop_table("supplier_reseller_rules")
    op.drop_index("ix_supplier_offers_product_id", table_name="supplier_offers")
    op.drop_index("ix_supplier_offers_supplier_status", table_name="supplier_offers")
    op.drop_table("supplier_offers")
