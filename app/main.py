import logging

import redis.asyncio as redis
from fastapi import FastAPI

from app.bots.dispatcher import create_dispatcher
from app.config import get_settings
from app.db.session import close_db, configure_db, get_session_factory
from app.services.external_sources import register_builtin_external_providers
from app.web.admin_web import create_admin_web_router
from app.web.exports import create_export_router
from app.web.files import create_file_router
from app.web.health import router as health_router
from app.web.openapi import install_openapi_security
from app.web.payments import create_payment_router
from app.web.platform_admin import create_platform_admin_router
from app.web.public_store import create_public_store_router
from app.web.tenant_admin import create_tenant_admin_router
from app.web.webhook import create_webhook_router
from app.workers.scheduler import BackgroundWorkerManager


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    configure_db(settings.database_url)
    register_builtin_external_providers()

    application = FastAPI(title="FakaBot 多租户平台", version="0.1.0")
    application.state.settings = settings
    application.state.dispatcher = None
    application.state.redis = None
    application.state.worker_manager = None

    application.include_router(health_router)
    application.include_router(create_webhook_router(settings))
    application.include_router(create_payment_router(settings))
    application.include_router(create_file_router(settings))
    application.include_router(create_export_router(settings))
    application.include_router(create_public_store_router(settings))
    application.include_router(create_tenant_admin_router(settings))
    application.include_router(create_platform_admin_router(settings))
    application.include_router(create_admin_web_router(settings))
    install_openapi_security(application)

    @application.on_event("startup")
    async def startup() -> None:
        application.state.dispatcher = create_dispatcher(settings)
        application.state.redis = redis.from_url(settings.redis_url, decode_responses=True)
        application.state.worker_manager = BackgroundWorkerManager(settings, get_session_factory())
        application.state.worker_manager.start()

    @application.on_event("shutdown")
    async def shutdown() -> None:
        if application.state.worker_manager is not None:
            await application.state.worker_manager.stop()
        if application.state.redis is not None:
            await application.state.redis.aclose()
        await close_db()

    return application


app = create_app()
