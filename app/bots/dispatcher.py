from aiogram import Dispatcher

from app.bots.middlewares.tenant_context import TenantContextMiddleware
from app.bots.routers.master import router as master_router
from app.bots.routers.tenant import router as tenant_router
from app.config import Settings
from app.db.session import get_session_factory


def create_dispatcher(settings: Settings) -> Dispatcher:
    dispatcher = Dispatcher(
        settings=settings,
        session_factory=get_session_factory(),
    )
    dispatcher.update.middleware(TenantContextMiddleware())
    dispatcher.include_router(master_router)
    dispatcher.include_router(tenant_router)
    return dispatcher

