from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class ExternalSourceConnection(TimestampMixin, Base):
    __tablename__ = "external_source_connections"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "provider_name",
            "source_key",
            name="uq_external_source_connections_tenant_provider_source",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    source_key: Mapped[str] = mapped_column(String(128), nullable=False, default="", server_default="")
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    credentials_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    credentials_hint_json: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("platform_users.id"))
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ExternalFulfillmentAttempt(TimestampMixin, Base):
    __tablename__ = "external_fulfillment_attempts"
    __table_args__ = (
        CheckConstraint(
            "attempt_source IN ('auto', 'manual')",
            name="ck_external_fulfillment_attempts_attempt_source",
        ),
        CheckConstraint(
            "status IN ('started', 'running', 'succeeded', 'already_delivered', 'failed', 'imported')",
            name="ck_external_fulfillment_attempts_status",
        ),
        CheckConstraint(
            "item_count >= 0",
            name="ck_external_fulfillment_attempts_item_count_nonnegative",
        ),
        CheckConstraint(
            "upstream_status_code IS NULL OR (upstream_status_code >= 100 AND upstream_status_code <= 599)",
            name="ck_external_fulfillment_attempts_upstream_status_code",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    connection_id: Mapped[Optional[int]] = mapped_column(ForeignKey("external_source_connections.id"))
    delivery_record_id: Mapped[Optional[int]] = mapped_column(ForeignKey("delivery_records.id"))
    out_trade_no: Mapped[str] = mapped_column(String(96), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    source_key: Mapped[str] = mapped_column(String(128), nullable=False, default="", server_default="")
    external_product_id: Mapped[str] = mapped_column(String(128), nullable=False)
    external_order_id: Mapped[Optional[str]] = mapped_column(String(128))
    attempt_source: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    imported: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failure_reason: Mapped[Optional[str]] = mapped_column(Text)
    failure_stage: Mapped[Optional[str]] = mapped_column(String(64))
    failure_category: Mapped[Optional[str]] = mapped_column(String(64))
    failure_retryable: Mapped[Optional[bool]] = mapped_column(Boolean)
    upstream_status_code: Mapped[Optional[int]] = mapped_column(Integer)
    failure_fingerprint: Mapped[Optional[str]] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


Index(
    "ix_external_source_connections_tenant_provider_status",
    ExternalSourceConnection.tenant_id,
    ExternalSourceConnection.provider_name,
    ExternalSourceConnection.status,
)
Index(
    "ix_external_source_connections_tenant_status",
    ExternalSourceConnection.tenant_id,
    ExternalSourceConnection.status,
)
Index(
    "ix_external_fulfillment_attempts_tenant_status_created",
    ExternalFulfillmentAttempt.tenant_id,
    ExternalFulfillmentAttempt.status,
    ExternalFulfillmentAttempt.created_at,
)
Index(
    "ix_external_fulfillment_attempts_tenant_order_created",
    ExternalFulfillmentAttempt.tenant_id,
    ExternalFulfillmentAttempt.order_id,
    ExternalFulfillmentAttempt.created_at,
)
Index(
    "ix_external_fulfillment_attempts_provider_status",
    ExternalFulfillmentAttempt.provider_name,
    ExternalFulfillmentAttempt.status,
)
