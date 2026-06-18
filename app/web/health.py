from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
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
            # 仅 SELECT 1 只能证明连接可用，空库也会通过（曾因此假阳性 30 小时）。
            # 这里额外验证核心业务表已迁移就绪。
            migrated = await session.execute(text("SELECT to_regclass('public.tenants')"))
            if migrated.scalar() is None:
                raise HTTPException(status_code=503, detail="database_not_migrated")
    except HTTPException:
        raise
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


@router.get("/health/detailed")
async def detailed_health(request: Request) -> JSONResponse:
    """
    详细健康检查，包含所有组件状态

    返回：
    - status: 总体状态 (healthy/degraded/unhealthy)
    - checks: 各组件检查结果
    - timestamp: 检查时间
    """
    checks: Dict[str, Any] = {}
    all_healthy = True

    # 1. 数据库检查
    try:
        session_factory = get_session_factory()
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = {"status": "healthy", "message": "connected"}
    except Exception as e:
        checks["database"] = {"status": "unhealthy", "message": str(e)}
        all_healthy = False

    # 2. Redis 检查
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        checks["redis"] = {"status": "unhealthy", "message": "not configured"}
        all_healthy = False
    else:
        try:
            await redis_client.ping()
            checks["redis"] = {"status": "healthy", "message": "connected"}
        except Exception as e:
            checks["redis"] = {"status": "unhealthy", "message": str(e)}
            all_healthy = False

    # 3. 后台任务检查（内置 BackgroundWorkerManager）
    settings = getattr(request.app.state, "settings", None)
    workers_enabled = bool(getattr(settings, "workers_enabled", False))
    worker_manager = getattr(request.app.state, "worker_manager", None)
    if not workers_enabled:
        checks["workers"] = {"status": "healthy", "message": "workers disabled", "tasks": {}}
    else:
        is_ready = worker_manager is not None and callable(
            getattr(worker_manager, "is_ready", None)
        ) and worker_manager.is_ready()
        task_status: Dict[str, Any] = {}
        if worker_manager is not None and hasattr(worker_manager, "task_status"):
            task_status = worker_manager.task_status()
        checks["workers"] = {
            "status": "healthy" if is_ready else "unhealthy",
            "message": "ready" if is_ready else "worker tasks not running",
            "tasks": task_status,
        }
        if not is_ready:
            all_healthy = False

    # 4. 存储目录检查
    try:
        from pathlib import Path
        from app.config import get_settings
        settings = get_settings()
        storage_root = Path(settings.storage_root)
        if storage_root.exists() and storage_root.is_dir():
            checks["storage"] = {"status": "healthy", "message": "accessible"}
        else:
            checks["storage"] = {"status": "unhealthy", "message": "directory not found"}
            all_healthy = False
    except Exception as e:
        checks["storage"] = {"status": "unhealthy", "message": str(e)}
        all_healthy = False

    status_code = 200 if all_healthy else 503
    overall_status = "healthy" if all_healthy else "unhealthy"

    return JSONResponse(
        status_code=status_code,
        content={
            "status": overall_status,
            "checks": checks,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )

