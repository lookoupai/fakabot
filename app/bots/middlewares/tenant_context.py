from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Dict, Optional

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bots.context import TenantContext
from app.db.repos.tenants import TenantRepository
from app.services.tenant_features import build_tenant_feature_flags as _build_tenant_feature_flags


class TenantContextMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        data.setdefault("tenant_context", None)
        data.setdefault("bot_role", None)
        tenant_context = data.get("tenant_context")
        session_factory = data.get("session_factory")
        if isinstance(tenant_context, TenantContext) and session_factory is not None:
            tenant_settings, tenant_feature_flags = await load_tenant_runtime_data(
                session_factory,
                tenant_context,
            )
            data.setdefault("tenant_settings", tenant_settings)
            data.setdefault("tenant_feature_flags", tenant_feature_flags)
        return await handler(event, data)


async def load_tenant_runtime_data(
    session_factory: async_sessionmaker[AsyncSession],
    tenant_context: TenantContext,
) -> tuple[Dict[str, Dict[str, Any]], Dict[str, bool]]:
    repo = TenantRepository()
    async with session_factory() as session:
        tenant = await repo.get_tenant(session, tenant_context.tenant_id)
        tenant_settings = await repo.get_settings(session, tenant_context.tenant_id)
    return tenant_settings, build_tenant_feature_flags(tenant, tenant_settings)


def build_tenant_feature_flags(
    tenant: Optional[Any],
    tenant_settings: Dict[str, Dict[str, Any]],
) -> Dict[str, bool]:
    return _build_tenant_feature_flags(tenant, tenant_settings)
