from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.config import Settings
from app.db.models.orders import DeliveryRecord
from app.db.models.products import UploadedFile
from app.db.session import get_session_factory
from app.services.files import DownloadTokenService, FileStorageService


def create_file_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/files", tags=["files"])

    @router.get("/download/{token}")
    async def download_file(token: str) -> FileResponse:
        try:
            payload = DownloadTokenService(settings).verify_token(token)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=403, detail=str(exc))

        async with get_session_factory()() as session:
            result = await session.execute(
                select(UploadedFile, DeliveryRecord)
                .join(DeliveryRecord, DeliveryRecord.uploaded_file_id == UploadedFile.id)
                .where(UploadedFile.id == payload.uploaded_file_id)
                .where(UploadedFile.tenant_id == payload.tenant_id)
                .where(UploadedFile.status == "active")
                .where(DeliveryRecord.order_id == payload.order_id)
                .where(DeliveryRecord.status.in_(("sending", "sent")))
            )
            row = result.first()

        if row is None:
            raise HTTPException(status_code=404, detail="文件不存在或无权下载")

        uploaded_file = row[0]
        path = FileStorageService(settings).resolve_storage_key(uploaded_file.storage_key)
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="文件不存在")
        return FileResponse(
            path,
            media_type=uploaded_file.content_type or "application/octet-stream",
            filename=uploaded_file.original_filename,
        )

    return router
