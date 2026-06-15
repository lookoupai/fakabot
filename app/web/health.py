from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from app.db.session import get_session_factory

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> Dict[str, str]:
    session_factory = get_session_factory()
    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database_unavailable") from exc
    if request.app.state.redis is None:
        raise HTTPException(status_code=503, detail="redis_unavailable")
    try:
        await request.app.state.redis.ping()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="redis_unavailable") from exc
    settings = getattr(request.app.state, "settings", None)
    workers_enabled = bool(getattr(settings, "workers_enabled", False))
    if workers_enabled:
        worker_manager = getattr(request.app.state, "worker_manager", None)
        is_ready = getattr(worker_manager, "is_ready", None)
        if worker_manager is None or not callable(is_ready) or not is_ready():
            raise HTTPException(status_code=503, detail="worker_unavailable")
    return {"status": "ok"}
