from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class ExportJob(TimestampMixin, Base):
    __tablename__ = "export_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tenants.id"))
    requested_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("platform_users.id"))
    report_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False, default="tenant")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    storage_key: Mapped[Optional[str]] = mapped_column(Text)
    download_token: Mapped[Optional[str]] = mapped_column(String(128))
    filename: Mapped[Optional[str]] = mapped_column(String(255))
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


Index("ix_export_jobs_tenant_status_created_at", ExportJob.tenant_id, ExportJob.status, ExportJob.created_at)
Index(
    "ix_export_jobs_requested_by_status_created_at",
    ExportJob.requested_by_user_id,
    ExportJob.status,
    ExportJob.created_at,
)
Index("ix_export_jobs_download_token", ExportJob.download_token, unique=True)
