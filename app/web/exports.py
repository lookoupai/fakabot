from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import Settings
from app.db.session import get_session_factory
from app.services.files import FileStorageService
from app.services.reports import ReportExportService


def create_export_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/exports", tags=["exports"])

    @router.get("/download/{token}")
    async def download_export(token: str) -> FileResponse:
        async with get_session_factory()() as session:
            try:
                job = await ReportExportService().get_downloadable_export(session, token)
                await session.commit()
            except ValueError as exc:
                await session.commit()
                raise HTTPException(status_code=403, detail=str(exc))

        if job is None:
            raise HTTPException(status_code=404, detail="报表不存在")

        path = FileStorageService(settings).resolve_storage_key(job.storage_key or "")
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="报表文件不存在")
        return FileResponse(path, media_type="text/csv; charset=utf-8", filename=job.filename or "export.csv")

    return router
