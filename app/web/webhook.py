from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import APIRouter, HTTPException, Request
from redis.asyncio import Redis

from app.bots.context import TenantContext
from app.bots.factory import create_bot
from app.config import Settings
from app.db.repos.tenants import TenantRepository
from app.db.session import get_session_factory
from app.services.token_crypto import TokenCrypto

_TENANT_WEBHOOK_CACHE_TTL_SECONDS = 300
_TENANT_WEBHOOK_CACHE_KEYS = {
    "tenant_id",
    "tenant_public_id",
    "tenant_bot_id",
    "owner_user_id",
    "owner_telegram_user_id",
    "store_name",
    "bot_username",
    "encrypted_token",
}


def create_webhook_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix=settings.webhook_base_path, tags=["telegram"])

    @router.post("/{webhook_secret}")
    async def telegram_webhook(webhook_secret: str, request: Request) -> Dict[str, bool]:
        dispatcher: Dispatcher = request.app.state.dispatcher
        if dispatcher is None:
            raise HTTPException(status_code=503, detail="应用尚未完成初始化")
        bot, workflow_data = await _resolve_bot(webhook_secret, settings, request.app.state.redis)
        try:
            payload = await request.json()
            update = Update.model_validate(payload, context={"bot": bot})
            await dispatcher.feed_update(bot, update, redis_client=request.app.state.redis, **workflow_data)
            return {"ok": True}
        finally:
            await bot.session.close()

    return router


async def _resolve_bot(webhook_secret: str, settings: Settings, redis_client: Redis) -> Tuple[Bot, Dict[str, Any]]:
    if webhook_secret == settings.master_webhook_secret:
        if settings.master_bot_token is None:
            raise HTTPException(status_code=503, detail="MASTER_BOT_TOKEN 未配置")
        return create_bot(settings.master_bot_token.get_secret_value()), {"bot_role": "master"}

    tenant_context, encrypted_token = await _resolve_tenant_context(webhook_secret, redis_client)
    if tenant_context is None or encrypted_token is None:
        raise HTTPException(status_code=404, detail="未知 Webhook")

    token = TokenCrypto(settings).decrypt_token(encrypted_token)
    return create_bot(token), {"bot_role": "tenant", "tenant_context": tenant_context}


async def _resolve_tenant_context(
    webhook_secret: str,
    redis_client: Redis,
) -> Tuple[Optional[TenantContext], Optional[str]]:
    cache_key = f"tenant_webhook:{webhook_secret}"
    cached = await redis_client.get(cache_key)
    if cached:
        data = _load_cached_tenant_webhook(cached)
        if data is not None:
            tenant_bot = await _load_active_tenant_bot(webhook_secret)
            if tenant_bot is None:
                await redis_client.delete(cache_key)
                return None, None
            return _tenant_context_from_cache_data(data), data["encrypted_token"]
        await redis_client.delete(cache_key)

    tenant_bot = await _load_active_tenant_bot(webhook_secret)
    if tenant_bot is None:
        return None, None
    data = _tenant_webhook_cache_data(tenant_bot)

    await redis_client.set(cache_key, json.dumps(data), ex=_TENANT_WEBHOOK_CACHE_TTL_SECONDS)
    return _tenant_context_from_cache_data(data), data["encrypted_token"]


def _load_cached_tenant_webhook(raw_value: str) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(raw_value)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if not _TENANT_WEBHOOK_CACHE_KEYS.issubset(data):
        return None
    return data


async def _load_active_tenant_bot(webhook_secret: str) -> Any:
    repo = TenantRepository()
    async with get_session_factory()() as session:
        return await repo.get_active_bot_by_secret(session, webhook_secret)


def _tenant_webhook_cache_data(tenant_bot: Any) -> Dict[str, Any]:
    return {
        "tenant_id": tenant_bot.tenant_id,
        "tenant_public_id": tenant_bot.tenant.public_id,
        "tenant_bot_id": tenant_bot.id,
        "owner_user_id": tenant_bot.tenant.owner_user_id,
        "owner_telegram_user_id": tenant_bot.tenant.owner.telegram_user_id,
        "store_name": tenant_bot.tenant.store_name,
        "bot_username": tenant_bot.bot_username,
        "encrypted_token": tenant_bot.encrypted_token,
    }


def _tenant_context_from_cache_data(data: Dict[str, Any]) -> TenantContext:
    return TenantContext(
        tenant_id=data["tenant_id"],
        tenant_public_id=data["tenant_public_id"],
        tenant_bot_id=data["tenant_bot_id"],
        owner_user_id=data["owner_user_id"],
        owner_telegram_user_id=data["owner_telegram_user_id"],
        store_name=data["store_name"],
        bot_username=data["bot_username"],
    )
