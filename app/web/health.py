from __future__ import annotations

from datetime import datetime, timedelta, timezone
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

    # 3. Worker 心跳检查
    workers_status = await _check_workers_heartbeat(redis_client)
    checks["workers"] = workers_status
    if workers_status["status"] != "healthy":
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


async def _check_workers_heartbeat(redis_client) -> Dict[str, Any]:
    """检查 Worker 心跳状态"""
    if redis_client is None:
        return {
            "status": "unknown",
            "message": "redis not available",
            "workers": {}
        }

    worker_names = ["report-worker", "subscription-worker", "payment-retry-worker"]
    workers_info = {}
    any_unhealthy = False

    for worker_name in worker_names:
        heartbeat_key = f"worker:{worker_name}:heartbeat"
        try:
            heartbeat = await redis_client.get(heartbeat_key)
            if heartbeat:
                # 解析心跳时间
                try:
                    heartbeat_time = datetime.fromisoformat(heartbeat.decode() if isinstance(heartbeat, bytes) else heartbeat)
                    age_seconds = (datetime.now(timezone.utc) - heartbeat_time).total_seconds()

                    # 判断是否健康（5分钟内有心跳）
                    if age_seconds < 300:
                        workers_info[worker_name] = {
                            "status": "healthy",
                            "last_heartbeat": heartbeat_time.isoformat(),
                            "age_seconds": int(age_seconds)
                        }
                    else:
                        workers_info[worker_name] = {
                            "status": "stale",
                            "last_heartbeat": heartbeat_time.isoformat(),
                            "age_seconds": int(age_seconds)
                        }
                        any_unhealthy = True
                except (ValueError, AttributeError):
                    workers_info[worker_name] = {
                        "status": "unknown",
                        "message": "invalid heartbeat format"
                    }
                    any_unhealthy = True
            else:
                workers_info[worker_name] = {
                    "status": "missing",
                    "message": "no heartbeat found"
                }
                any_unhealthy = True
        except Exception as e:
            workers_info[worker_name] = {
                "status": "error",
                "message": str(e)
            }
            any_unhealthy = True

    overall_status = "unhealthy" if any_unhealthy else "healthy"

    return {
        "status": overall_status,
        "workers": workers_info
    }
