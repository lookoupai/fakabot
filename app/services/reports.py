from __future__ import annotations

import csv
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.ledger import LedgerEntry
from app.db.models.orders import Order, Payment
from app.db.models.products import InventoryItem, Product, ProductVariant
from app.db.models.reports import ExportJob
from app.db.models.tenants import AuditLog, Tenant
from app.services.files import FileStorageService

SUPPORTED_REPORT_TYPES = {"orders", "payments", "inventory", "ledger", "products"}
SUPPORTED_SCOPE_TYPES = {"tenant", "platform"}
SUPPORTED_EXPORT_JOB_STATUSES = {"pending", "running", "completed", "failed", "expired"}
EXPORT_DOWNLOAD_TTL_HOURS = 24


@dataclass(frozen=True)
class ExportJobSummary:
    export_job_id: int
    tenant_id: Optional[int]
    requested_by_user_id: Optional[int]
    report_type: str
    scope_type: str
    status: str
    filename: Optional[str]
    row_count: int
    error_message: Optional[str]
    expires_at: Optional[datetime]
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    download_url: Optional[str]


class ReportExportService:
    async def create_export_job(
        self,
        session: AsyncSession,
        settings: Settings,
        report_type: str,
        actor_user_id: Optional[int],
        tenant_id: Optional[int],
        scope_type: str = "tenant",
    ) -> ExportJobSummary:
        report_type = report_type.strip().lower()
        scope_type = scope_type.strip().lower()
        self._validate_report_type(report_type)
        await self._validate_scope(session, tenant_id, scope_type)

        job = ExportJob(
            tenant_id=tenant_id,
            requested_by_user_id=actor_user_id,
            report_type=report_type,
            scope_type=scope_type,
            status="pending",
            row_count=0,
        )
        session.add(job)
        await session.flush()
        session.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                action="report.export_requested",
                target_type="export_job",
                target_id=str(job.id),
                metadata_json={"report_type": report_type, "scope_type": scope_type},
            )
        )
        await session.flush()
        return self._to_summary(job, settings)

    async def list_export_jobs(
        self,
        session: AsyncSession,
        settings: Settings,
        tenant_id: Optional[int] = None,
        requested_by_user_id: Optional[int] = None,
        status: Optional[str] = None,
        report_type: Optional[str] = None,
        limit: int = 20,
        include_all_tenants: bool = False,
    ) -> list[ExportJobSummary]:
        normalized_status = self._normalize_optional_status(status)
        normalized_report_type = self._normalize_optional_report_type(report_type)
        query = select(ExportJob).order_by(ExportJob.created_at.desc(), ExportJob.id.desc()).limit(self._normalize_limit(limit))
        if tenant_id is not None:
            query = query.where(ExportJob.tenant_id == tenant_id)
        elif not include_all_tenants:
            query = query.where(ExportJob.tenant_id.is_(None))
        if requested_by_user_id is not None:
            query = query.where(ExportJob.requested_by_user_id == requested_by_user_id)
        if normalized_status is not None:
            query = query.where(ExportJob.status == normalized_status)
        if normalized_report_type is not None:
            query = query.where(ExportJob.report_type == normalized_report_type)

        result = await session.execute(query)
        return [self._to_summary(job, settings) for job in result.scalars().all()]

    async def process_pending_exports(
        self,
        session: AsyncSession,
        settings: Settings,
        limit: int = 10,
    ) -> int:
        processed_count = await self._expire_completed_exports(session, limit=limit)
        result = await session.execute(
            select(ExportJob)
            .where(ExportJob.status == "pending")
            .order_by(ExportJob.created_at.asc(), ExportJob.id.asc())
            .with_for_update(skip_locked=True)
            .limit(self._normalize_limit(limit))
        )
        jobs = list(result.scalars().all())
        for job in jobs:
            await self._process_job(session, settings, job)
            processed_count += 1
        await session.flush()
        return processed_count

    async def get_export_by_token(
        self,
        session: AsyncSession,
        token: str,
    ) -> Optional[ExportJob]:
        if not token:
            return None
        result = await session.execute(select(ExportJob).where(ExportJob.download_token == token).limit(1))
        return result.scalar_one_or_none()

    async def get_downloadable_export(
        self,
        session: AsyncSession,
        token: str,
    ) -> Optional[ExportJob]:
        job = await self.get_export_by_token(session, token)
        if job is None:
            return None
        if job.status == "completed" and job.expires_at is not None and job.expires_at <= datetime.now(timezone.utc):
            await self._mark_expired(session, job)
            raise ValueError("报表下载链接已过期")
        if job.status != "completed":
            raise ValueError("报表尚未生成完成")
        if not job.storage_key:
            raise ValueError("报表文件不存在")
        return job

    async def get_downloadable_tenant_export(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        export_job_id: int,
    ) -> Optional[ExportJob]:
        if tenant_id <= 0 or export_job_id <= 0:
            return None
        result = await session.execute(
            select(ExportJob)
            .where(ExportJob.id == export_job_id)
            .where(ExportJob.tenant_id == tenant_id)
            .where(ExportJob.scope_type == "tenant")
            .limit(1)
        )
        job = result.scalar_one_or_none()
        if job is None:
            return None
        if job.status == "completed" and job.expires_at is not None and job.expires_at <= datetime.now(timezone.utc):
            await self._mark_expired(session, job)
            raise ValueError("报表下载链接已过期")
        if job.status != "completed":
            raise ValueError("报表尚未生成完成")
        if not job.storage_key:
            raise ValueError("报表文件不存在")
        return job

    async def _process_job(
        self,
        session: AsyncSession,
        settings: Settings,
        job: ExportJob,
    ) -> None:
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        await session.flush()
        try:
            row_count, storage_key, filename = await self._write_export_csv(session, settings, job)
            job.storage_key = storage_key
            job.filename = filename
            job.row_count = row_count
            job.download_token = secrets.token_urlsafe(32)
            job.expires_at = datetime.now(timezone.utc) + timedelta(hours=EXPORT_DOWNLOAD_TTL_HOURS)
            job.status = "completed"
            job.finished_at = datetime.now(timezone.utc)
            job.error_message = None
            session.add(
                AuditLog(
                    tenant_id=job.tenant_id,
                    actor_user_id=job.requested_by_user_id,
                    action="report.export_completed",
                    target_type="export_job",
                    target_id=str(job.id),
                    metadata_json={
                        "report_type": job.report_type,
                        "scope_type": job.scope_type,
                        "row_count": row_count,
                        "filename": filename,
                    },
                )
            )
        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)[:1000]
            job.finished_at = datetime.now(timezone.utc)
            session.add(
                AuditLog(
                    tenant_id=job.tenant_id,
                    actor_user_id=job.requested_by_user_id,
                    action="report.export_failed",
                    target_type="export_job",
                    target_id=str(job.id),
                    metadata_json={
                        "report_type": job.report_type,
                        "scope_type": job.scope_type,
                        "error": type(exc).__name__,
                    },
                )
            )

    async def _write_export_csv(
        self,
        session: AsyncSession,
        settings: Settings,
        job: ExportJob,
    ) -> tuple[int, str, str]:
        storage_key, filename = self._build_storage_key(job)
        target_path = FileStorageService(settings).resolve_storage_key(storage_key)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.with_suffix(target_path.suffix + ".tmp")

        row_count = 0
        with temp_path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.writer(file)
            if job.report_type == "orders":
                row_count = await self._write_orders(session, job, writer)
            elif job.report_type == "payments":
                row_count = await self._write_payments(session, job, writer)
            elif job.report_type == "inventory":
                row_count = await self._write_inventory(session, job, writer)
            elif job.report_type == "ledger":
                row_count = await self._write_ledger(session, job, writer)
            elif job.report_type == "products":
                row_count = await self._write_products(session, job, writer)
            else:
                raise ValueError("不支持的报表类型")
        os.replace(temp_path, target_path)
        return row_count, storage_key, filename

    async def _write_orders(self, session: AsyncSession, job: ExportJob, writer: Any) -> int:
        writer.writerow(
            [
                "order_id",
                "out_trade_no",
                "tenant_id",
                "buyer_telegram_user_id",
                "source_type",
                "amount",
                "currency",
                "display_amount",
                "display_currency",
                "payment_mode",
                "payment_provider",
                "status",
                "self_product_id",
                "reseller_product_id",
                "supplier_tenant_id",
                "created_at",
                "paid_at",
                "delivered_at",
                "expires_at",
            ]
        )
        query = select(Order).order_by(Order.created_at.asc(), Order.id.asc())
        if job.tenant_id is not None:
            query = query.where(Order.tenant_id == job.tenant_id)
        result = await session.execute(query)
        count = 0
        for order in result.scalars().all():
            writer.writerow(
                self._csv_row(
                    [
                        order.id,
                        order.out_trade_no,
                        order.tenant_id,
                        order.buyer_telegram_user_id,
                        order.source_type,
                        order.amount,
                        order.currency,
                        order.display_amount,
                        order.display_currency,
                        order.payment_mode,
                        order.payment_provider,
                        order.status,
                        order.self_product_id,
                        order.reseller_product_id,
                        order.supplier_tenant_id,
                        order.created_at,
                        order.paid_at,
                        order.delivered_at,
                        order.expires_at,
                    ]
                )
            )
            count += 1
        return count

    async def _write_payments(self, session: AsyncSession, job: ExportJob, writer: Any) -> int:
        writer.writerow(
            [
                "payment_id",
                "order_id",
                "out_trade_no",
                "tenant_id",
                "provider",
                "provider_trade_no",
                "amount",
                "currency",
                "status",
                "available_at",
                "paid_at",
                "created_at",
            ]
        )
        query = (
            select(Payment, Order.out_trade_no)
            .join(Order, Order.id == Payment.order_id)
            .order_by(Payment.created_at.asc(), Payment.id.asc())
        )
        if job.tenant_id is not None:
            query = query.where(Payment.tenant_id == job.tenant_id)
        result = await session.execute(query)
        count = 0
        for payment, out_trade_no in result.all():
            writer.writerow(
                self._csv_row(
                    [
                        payment.id,
                        payment.order_id,
                        out_trade_no,
                        payment.tenant_id,
                        payment.provider,
                        payment.provider_trade_no,
                        payment.amount,
                        payment.currency,
                        payment.status,
                        payment.available_at,
                        payment.paid_at,
                        payment.created_at,
                    ]
                )
            )
            count += 1
        return count

    async def _write_inventory(self, session: AsyncSession, job: ExportJob, writer: Any) -> int:
        writer.writerow(
            [
                "tenant_id",
                "product_id",
                "product_name",
                "delivery_type",
                "product_status",
                "variant_id",
                "variant_name",
                "variant_status",
                "inventory_status",
                "item_count",
            ]
        )
        query = (
            select(
                Product.tenant_id,
                Product.id,
                Product.name,
                Product.delivery_type,
                Product.status,
                ProductVariant.id,
                ProductVariant.name,
                ProductVariant.status,
                InventoryItem.status,
                func.count(InventoryItem.id),
            )
            .outerjoin(
                ProductVariant,
                (ProductVariant.product_id == Product.id) & (ProductVariant.tenant_id == Product.tenant_id),
            )
            .outerjoin(
                InventoryItem,
                (InventoryItem.product_id == Product.id)
                & (InventoryItem.variant_id == ProductVariant.id)
                & (InventoryItem.tenant_id == Product.tenant_id),
            )
            .where(Product.status != "deleted")
            .group_by(
                Product.tenant_id,
                Product.id,
                Product.name,
                Product.delivery_type,
                Product.status,
                ProductVariant.id,
                ProductVariant.name,
                ProductVariant.status,
                InventoryItem.status,
            )
            .order_by(Product.tenant_id.asc(), Product.id.asc(), ProductVariant.id.asc(), InventoryItem.status.asc())
        )
        if job.tenant_id is not None:
            query = query.where(Product.tenant_id == job.tenant_id)
        result = await session.execute(query)
        count = 0
        for row in result.all():
            item_count = int(row[9] or 0)
            writer.writerow(self._csv_row([*row[:8], row[8] or "none", item_count]))
            count += 1
        return count

    async def _write_ledger(self, session: AsyncSession, job: ExportJob, writer: Any) -> int:
        writer.writerow(
            [
                "ledger_entry_id",
                "account_id",
                "tenant_id",
                "entry_type",
                "direction",
                "amount",
                "currency",
                "status",
                "order_id",
                "withdrawal_id",
                "available_at",
                "created_at",
            ]
        )
        query = select(LedgerEntry).order_by(LedgerEntry.created_at.asc(), LedgerEntry.id.asc())
        if job.tenant_id is not None:
            query = query.where(LedgerEntry.tenant_id == job.tenant_id)
        result = await session.execute(query)
        count = 0
        for entry in result.scalars().all():
            writer.writerow(
                self._csv_row(
                    [
                        entry.id,
                        entry.account_id,
                        entry.tenant_id,
                        entry.entry_type,
                        entry.direction,
                        entry.amount,
                        entry.currency,
                        entry.status,
                        entry.order_id,
                        entry.withdrawal_id,
                        entry.available_at,
                        entry.created_at,
                    ]
                )
            )
            count += 1
        return count

    async def _write_products(self, session: AsyncSession, job: ExportJob, writer: Any) -> int:
        """
        写入商品报表

        导出字段：商品ID、名称、分类、排序、状态、发货类型、价格、币种、可用库存、创建时间、更新时间
        安全边界：不导出库存明文、文件storage key、外部映射、供应商/代理商信息
        """
        writer.writerow(
            [
                "商品ID",
                "商品名称",
                "分类",
                "排序",
                "状态",
                "发货类型",
                "价格",
                "币种",
                "可用库存",
                "创建时间",
                "更新时间",
            ]
        )

        # 查询商品和库存统计
        query = (
            select(
                Product.id,
                Product.name,
                Product.category,
                Product.sort_order,
                Product.status,
                Product.delivery_type,
                ProductVariant.price,
                ProductVariant.currency,
                func.count(InventoryItem.id).filter(InventoryItem.status == "available"),
                Product.created_at,
                Product.updated_at,
            )
            .outerjoin(
                ProductVariant,
                (ProductVariant.product_id == Product.id)
                & (ProductVariant.tenant_id == Product.tenant_id)
                & (ProductVariant.is_default == True),
            )
            .outerjoin(
                InventoryItem,
                (InventoryItem.product_id == Product.id)
                & (InventoryItem.variant_id == ProductVariant.id)
                & (InventoryItem.tenant_id == Product.tenant_id),
            )
            .where(Product.status != "deleted")
            .group_by(
                Product.id,
                Product.name,
                Product.category,
                Product.sort_order,
                Product.status,
                Product.delivery_type,
                ProductVariant.price,
                ProductVariant.currency,
                Product.created_at,
                Product.updated_at,
            )
            .order_by(Product.id.asc())
        )

        if job.tenant_id is not None:
            query = query.where(Product.tenant_id == job.tenant_id)

        result = await session.execute(query)
        count = 0
        for row in result.all():
            product_id, name, category, sort_order, status, delivery_type, price, currency, available_count, created_at, updated_at = row
            writer.writerow(
                self._csv_row(
                    [
                        product_id,
                        name,
                        category or "",
                        sort_order,
                        status,
                        delivery_type,
                        price or Decimal("0"),
                        currency or "USDT",
                        int(available_count or 0),
                        created_at,
                        updated_at,
                    ]
                )
            )
            count += 1
        return count

    async def _expire_completed_exports(self, session: AsyncSession, limit: int) -> int:
        result = await session.execute(
            select(ExportJob)
            .where(ExportJob.status == "completed")
            .where(ExportJob.expires_at.is_not(None))
            .where(ExportJob.expires_at <= datetime.now(timezone.utc))
            .order_by(ExportJob.expires_at.asc(), ExportJob.id.asc())
            .with_for_update(skip_locked=True)
            .limit(self._normalize_limit(limit))
        )
        jobs = list(result.scalars().all())
        for job in jobs:
            await self._mark_expired(session, job)
        return len(jobs)

    async def _mark_expired(self, session: AsyncSession, job: ExportJob) -> None:
        if job.status != "expired":
            job.status = "expired"
            session.add(
                AuditLog(
                    tenant_id=job.tenant_id,
                    actor_user_id=job.requested_by_user_id,
                    action="report.export_expired",
                    target_type="export_job",
                    target_id=str(job.id),
                    metadata_json={"report_type": job.report_type, "scope_type": job.scope_type},
                )
            )
            await session.flush()

    async def _validate_scope(self, session: AsyncSession, tenant_id: Optional[int], scope_type: str) -> None:
        if scope_type not in SUPPORTED_SCOPE_TYPES:
            raise ValueError("导出范围必须是 tenant 或 platform")
        if scope_type == "tenant":
            if tenant_id is None or tenant_id <= 0:
                raise ValueError("租户报表必须指定租户 ID")
            tenant = await session.get(Tenant, tenant_id)
            if tenant is None:
                raise ValueError("租户不存在")
            return
        if tenant_id is not None:
            raise ValueError("平台范围报表不能指定租户 ID")

    def _build_storage_key(self, job: ExportJob) -> tuple[str, str]:
        scope = f"tenant_{job.tenant_id}" if job.scope_type == "tenant" else "platform"
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        filename = self._safe_filename(f"{job.report_type}_{scope}_{timestamp}.csv")
        return f"exports/{scope}/{job.id}_{filename}", filename

    def _to_summary(self, job: ExportJob, settings: Settings) -> ExportJobSummary:
        download_url = None
        if job.status == "completed" and job.download_token:
            download_url = f"{settings.public_base_url}/exports/download/{job.download_token}"
        return ExportJobSummary(
            export_job_id=job.id,
            tenant_id=job.tenant_id,
            requested_by_user_id=job.requested_by_user_id,
            report_type=job.report_type,
            scope_type=job.scope_type,
            status=job.status,
            filename=job.filename,
            row_count=job.row_count,
            error_message=job.error_message,
            expires_at=job.expires_at,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            download_url=download_url,
        )

    def _validate_report_type(self, report_type: str) -> None:
        if report_type not in SUPPORTED_REPORT_TYPES:
            raise ValueError(f"报表类型不支持，可选：{', '.join(sorted(SUPPORTED_REPORT_TYPES))}")

    @staticmethod
    def _normalize_optional_report_type(report_type: Optional[str]) -> Optional[str]:
        if report_type is None:
            return None
        normalized = report_type.strip().lower()
        if not normalized or normalized == "all":
            return None
        if normalized not in SUPPORTED_REPORT_TYPES:
            raise ValueError("报表类型必须是 orders、payments、inventory、ledger、products 或 all")
        return normalized

    @staticmethod
    def _normalize_optional_status(status: Optional[str]) -> Optional[str]:
        if status is None:
            return None
        normalized = status.strip().lower()
        if not normalized or normalized == "all":
            return None
        if normalized not in SUPPORTED_EXPORT_JOB_STATUSES:
            raise ValueError("报表任务状态必须是 pending、running、completed、failed、expired 或 all")
        return normalized

    def _csv_row(self, values: list[Any]) -> list[str]:
        return [self._format_csv_value(value) for value in values]

    @staticmethod
    def _format_csv_value(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Decimal):
            return format(value.normalize(), "f")
        return str(value)

    @staticmethod
    def _normalize_limit(limit: int) -> int:
        return min(max(limit, 1), 100)

    @staticmethod
    def _safe_filename(filename: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "_", filename)[:180]
