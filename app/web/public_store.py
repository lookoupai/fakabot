from __future__ import annotations

import base64
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import hmac
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import Settings
from app.db.models.orders import Order
from app.db.models.tenants import PlatformUser
from app.db.repos.products import ProductRepository
from app.db.repos.tenants import TenantRepository
from app.db.session import get_session_factory
from app.services.orders import OrderService
from app.services.payments import PaymentService, PaymentUnavailableError
from app.services.risk import OrderCreationRiskBlocked
from app.services.api_security import (
    ApiIpAccessError,
    ApiRateLimitError,
    FixedWindowRateLimiter,
    RedisFixedWindowRateLimiter,
    hit_rate_limit,
    require_ip_allowed,
    resolve_client_ip,
)
from app.services.supply import SupplyService
from app.services.tenant_features import build_tenant_feature_flags
from app.services.telegram_webapp import (
    TelegramWebAppInitDataError,
    TelegramWebAppUser,
    validate_telegram_webapp_init_data,
)
from app.services.token_crypto import TokenCrypto


class PublicStoreProfile(BaseModel):
    public_id: str
    store_name: str
    welcome: str
    support: str


class PublicProduct(BaseModel):
    id: str
    source_type: Literal["self", "reseller"]
    name: str
    category: Optional[str] = None
    delivery_type: str
    price: Decimal
    currency: str
    stock_status: str
    description: Optional[str] = None


class CreatePublicOrderRequest(BaseModel):
    product_id: str = Field(min_length=1)
    source_type: Optional[Literal["self", "reseller"]] = None
    buyer_telegram_user_id: Optional[int] = Field(default=None, gt=0)
    telegram_init_data: Optional[str] = Field(default=None, min_length=1)


class PublicOrderResponse(BaseModel):
    out_trade_no: str
    amount: Decimal
    currency: str
    status: str
    expires_at: str
    paid_at: Optional[str] = None
    delivered_at: Optional[str] = None
    can_pay: bool


class PublicPaymentResponse(BaseModel):
    provider: str
    payment_url: str
    out_trade_no: str
    amount: Decimal
    currency: str


def create_public_store_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1/store", tags=["public-store"])
    local_write_rate_limiter = FixedWindowRateLimiter(
        settings.public_store_write_rate_limit_per_minute,
        window_seconds=settings.rate_limit_window_seconds,
    )
    redis_write_rate_limiter = RedisFixedWindowRateLimiter(
        settings.public_store_write_rate_limit_per_minute,
        window_seconds=settings.rate_limit_window_seconds,
        key_prefix=f"{settings.rate_limit_key_prefix}:public-store",
    )

    @router.get("/{tenant_public_id}/profile", response_model=PublicStoreProfile)
    async def store_profile(tenant_public_id: str) -> PublicStoreProfile:
        tenant, tenant_settings = await _load_tenant(tenant_public_id)
        return PublicStoreProfile(
            public_id=tenant.public_id,
            store_name=tenant.store_name,
            welcome=_setting_text(tenant_settings, "welcome", "欢迎光临，本店铺正在配置中。"),
            support=_setting_text(tenant_settings, "support", "暂未配置客服联系方式。"),
        )

    @router.get("/{tenant_public_id}/products", response_model=List[PublicProduct])
    async def store_products(tenant_public_id: str) -> List[PublicProduct]:
        tenant, tenant_settings = await _load_tenant(tenant_public_id)
        return await _list_public_products(tenant.id, settings=settings, tenant=tenant, tenant_settings=tenant_settings)

    @router.get("/{tenant_public_id}/products/{public_product_id}", response_model=PublicProduct)
    async def store_product_detail(tenant_public_id: str, public_product_id: str) -> PublicProduct:
        tenant, tenant_settings = await _load_tenant(tenant_public_id)
        products = await _list_public_products(tenant.id, settings=settings, tenant=tenant, tenant_settings=tenant_settings)
        for product in products:
            if product.id == public_product_id:
                return product
        raise HTTPException(status_code=404, detail="商品不存在")

    @router.post("/{tenant_public_id}/orders", response_model=PublicOrderResponse)
    async def create_order(
        tenant_public_id: str,
        payload: CreatePublicOrderRequest,
        request: Request,
    ) -> PublicOrderResponse:
        await _hit_public_store_write_rate_limit(
            redis_write_rate_limiter,
            local_write_rate_limiter,
            request,
            tenant_public_id,
            "create_order",
            None,
            settings.trusted_proxy_ips,
            settings.public_store_write_ip_allowlist,
        )
        tenant, tenant_settings = await _load_tenant(tenant_public_id)
        verified_user = await _verify_public_store_webapp_user(settings, tenant.id, request, payload.telegram_init_data)
        buyer_telegram_user_id = _buyer_telegram_user_id(payload, verified_user, settings.telegram_webapp_require_init_data)
        await _hit_public_store_write_rate_limit(
            redis_write_rate_limiter,
            local_write_rate_limiter,
            request,
            tenant_public_id,
            "create_order",
            f"buyer:{buyer_telegram_user_id}",
            settings.trusted_proxy_ips,
            settings.public_store_write_ip_allowlist,
            count_client=False,
        )
        await _ensure_buyer_not_banned(buyer_telegram_user_id)
        order_timeout_minutes = _order_timeout_minutes(tenant_settings)
        order_service = OrderService()
        source_type, product_id = _resolve_public_product_id(
            payload.product_id,
            payload.source_type,
            tenant_id=tenant.id,
            settings=settings,
        )
        feature_flags = build_tenant_feature_flags(tenant, tenant_settings)
        if source_type == "self" and not feature_flags["self_sale"]:
            raise HTTPException(status_code=400, detail="自营商品售卖功能已关闭")
        if source_type == "reseller" and not feature_flags["reseller"]:
            raise HTTPException(status_code=400, detail="代理售卖功能已关闭")
        async with get_session_factory()() as session:
            try:
                if source_type == "self":
                    created = await order_service.create_self_order(
                        session=session,
                        tenant_id=tenant.id,
                        buyer_telegram_user_id=buyer_telegram_user_id,
                        product_id=product_id,
                        order_timeout_minutes=order_timeout_minutes,
                    )
                else:
                    created = await order_service.create_reseller_order(
                        session=session,
                        tenant_id=tenant.id,
                        buyer_telegram_user_id=buyer_telegram_user_id,
                        reseller_product_id=product_id,
                        order_timeout_minutes=order_timeout_minutes,
                    )
                await session.commit()
            except OrderCreationRiskBlocked as exc:
                await session.commit()
                raise HTTPException(status_code=400, detail=str(exc))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
        return PublicOrderResponse(
            out_trade_no=created.out_trade_no,
            amount=created.amount,
            currency=created.currency,
            status="pending",
            expires_at=created.expires_at.isoformat(),
            can_pay=True,
        )

    @router.get("/{tenant_public_id}/orders/{out_trade_no}", response_model=PublicOrderResponse)
    async def order_detail(tenant_public_id: str, out_trade_no: str, request: Request) -> PublicOrderResponse:
        tenant, _ = await _load_tenant(tenant_public_id)
        verified_user = await _verify_public_store_webapp_user(settings, tenant.id, request)
        order = await _get_tenant_order(tenant.id, out_trade_no)
        _ensure_verified_order_owner(order, verified_user)
        await _ensure_buyer_not_banned(order.buyer_telegram_user_id)
        return _order_response(order)

    @router.post("/{tenant_public_id}/orders/{out_trade_no}/payment", response_model=PublicPaymentResponse)
    async def create_payment(tenant_public_id: str, out_trade_no: str, request: Request) -> PublicPaymentResponse:
        await _hit_public_store_write_rate_limit(
            redis_write_rate_limiter,
            local_write_rate_limiter,
            request,
            tenant_public_id,
            "create_payment",
            None,
            settings.trusted_proxy_ips,
            settings.public_store_write_ip_allowlist,
        )
        tenant, _ = await _load_tenant(tenant_public_id)
        verified_user = await _verify_public_store_webapp_user(settings, tenant.id, request)
        order = await _get_tenant_order(tenant.id, out_trade_no)
        _ensure_verified_order_owner(order, verified_user)
        await _ensure_buyer_not_banned(order.buyer_telegram_user_id)
        await _hit_public_store_write_rate_limit(
            redis_write_rate_limiter,
            local_write_rate_limiter,
            request,
            tenant_public_id,
            "create_payment",
            f"order:{out_trade_no}",
            settings.trusted_proxy_ips,
            settings.public_store_write_ip_allowlist,
            count_client=False,
        )
        try:
            async with get_session_factory()() as session:
                payment = await PaymentService(settings).create_payment_for_order(session, order.id)
                await session.commit()
        except PaymentUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return PublicPaymentResponse(
            provider=payment.provider,
            payment_url=payment.payment_url,
            out_trade_no=payment.out_trade_no,
            amount=payment.amount,
            currency=payment.currency,
        )

    return router


async def _hit_public_store_write_rate_limit(
    redis_limiter: RedisFixedWindowRateLimiter,
    local_limiter: FixedWindowRateLimiter,
    request: Request,
    tenant_public_id: str,
    action: str,
    subject: Optional[str],
    trusted_proxy_ips: set[str],
    ip_allowlist: set[str],
    count_client: bool = True,
) -> None:
    try:
        client_ip = resolve_client_ip(
            request.client.host if request.client is not None else None,
            _forwarded_for_header(request),
            trusted_proxy_ips,
        )
        require_ip_allowed(client_ip, ip_allowlist, "Public Store API")
        redis_client = getattr(request.app.state, "redis", None)
        if count_client:
            await hit_rate_limit(
                redis_client=redis_client,
                redis_limiter=redis_limiter,
                local_limiter=local_limiter,
                key=_public_store_rate_limit_key(tenant_public_id, action, "client", client_ip),
            )
        if subject is not None:
            await hit_rate_limit(
                redis_client=redis_client,
                redis_limiter=redis_limiter,
                local_limiter=local_limiter,
                key=_public_store_subject_rate_limit_key(tenant_public_id, action, subject),
            )
    except ApiIpAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ApiRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc))


def _public_store_rate_limit_key(tenant_public_id: str, action: str, subject_type: str, client_ip: str) -> str:
    return f"public-store:{tenant_public_id.strip()}:{action}:{subject_type}:{client_ip}"


def _public_store_subject_rate_limit_key(tenant_public_id: str, action: str, subject: str) -> str:
    return f"public-store:{tenant_public_id.strip()}:{action}:{subject.strip()}"


def _forwarded_for_header(request: Request) -> Optional[str]:
    headers = getattr(request, "headers", None)
    return headers.get("X-Forwarded-For") if headers is not None else None


async def _verify_public_store_webapp_user(
    settings: Settings,
    tenant_id: int,
    request: Request,
    fallback_init_data: Optional[str] = None,
) -> Optional[TelegramWebAppUser]:
    init_data = _telegram_init_data(request, fallback_init_data)
    if not init_data:
        if settings.telegram_webapp_require_init_data:
            raise HTTPException(status_code=401, detail="缺少 Telegram WebApp initData")
        return None
    try:
        bot_token = await _tenant_bot_token(settings, tenant_id)
        return validate_telegram_webapp_init_data(
            init_data,
            bot_token,
            max_age_seconds=settings.telegram_webapp_init_data_max_age_seconds,
        )
    except TelegramWebAppInitDataError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


def _telegram_init_data(request: Request, fallback_init_data: Optional[str]) -> Optional[str]:
    headers = getattr(request, "headers", None)
    header_value = headers.get("X-Telegram-Init-Data") if headers is not None else None
    return (header_value or fallback_init_data or "").strip() or None


async def _tenant_bot_token(settings: Settings, tenant_id: int) -> str:
    async with get_session_factory()() as session:
        tenant_bot = await TenantRepository().get_active_bot_by_tenant_id(session, tenant_id)
    if tenant_bot is None:
        raise RuntimeError("租户未绑定可用 Bot，无法校验 WebApp initData")
    return TokenCrypto(settings).decrypt_token(tenant_bot.encrypted_token)


def _buyer_telegram_user_id(
    payload: CreatePublicOrderRequest,
    verified_user: Optional[TelegramWebAppUser],
    require_init_data: bool,
) -> int:
    if verified_user is not None:
        if payload.buyer_telegram_user_id is not None and payload.buyer_telegram_user_id != verified_user.id:
            raise HTTPException(status_code=401, detail="买家身份与 Telegram WebApp initData 不一致")
        return verified_user.id
    if require_init_data:
        raise HTTPException(status_code=401, detail="缺少 Telegram WebApp initData")
    if payload.buyer_telegram_user_id is None:
        raise HTTPException(status_code=400, detail="缺少买家 Telegram 用户 ID")
    return payload.buyer_telegram_user_id


def _ensure_verified_order_owner(order: Order, verified_user: Optional[TelegramWebAppUser]) -> None:
    if verified_user is not None and order.buyer_telegram_user_id != verified_user.id:
        raise HTTPException(status_code=404, detail="订单不存在")


async def _ensure_buyer_not_banned(buyer_telegram_user_id: int) -> None:
    async with get_session_factory()() as session:
        result = await session.execute(
            select(PlatformUser.is_banned).where(PlatformUser.telegram_user_id == buyer_telegram_user_id)
        )
        is_banned = result.scalar_one_or_none()
    if is_banned:
        raise HTTPException(status_code=403, detail="买家账号已被平台限制")


async def _load_tenant(public_id: str):
    repo = TenantRepository()
    async with get_session_factory()() as session:
        tenant = await repo.get_active_tenant_by_public_id(session, public_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail="店铺不存在")
        tenant_settings = await repo.get_settings(session, tenant.id)
    return tenant, tenant_settings


async def _list_public_products(
    tenant_id: int,
    settings: Optional[Settings] = None,
    *,
    tenant: Optional[object] = None,
    tenant_settings: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[PublicProduct]:
    repo = ProductRepository()
    feature_flags = build_tenant_feature_flags(tenant, tenant_settings or {})
    async with get_session_factory()() as session:
        products = await repo.list_public_products(session, tenant_id) if feature_flags["self_sale"] else []
        reseller_products = (
            await SupplyService().list_public_reseller_products(session, tenant_id)
            if feature_flags["reseller"]
            else []
        )
    items: List[PublicProduct] = []
    for product, variant, available_count in products:
        price = variant.price if variant else product.suggested_price
        items.append(
            PublicProduct(
                id=_public_product_id("self", product.id, tenant_id=tenant_id, settings=settings),
                source_type="self",
                name=product.name,
                description=product.description,
                delivery_type=product.delivery_type,
                price=price,
                currency=product.currency,
                stock_status=_stock_status(product.delivery_type, available_count),
            )
        )
    for reseller_product in reseller_products:
        items.append(
            PublicProduct(
                id=_public_product_id(
                    "reseller",
                    reseller_product.reseller_product_id,
                    tenant_id=tenant_id,
                    settings=settings,
                ),
                source_type="reseller",
                name=reseller_product.display_name,
                category=reseller_product.category,
                delivery_type=reseller_product.delivery_type,
                price=reseller_product.sale_price,
                currency=reseller_product.currency,
                stock_status=_stock_status(reseller_product.delivery_type, reseller_product.available_count),
            )
        )
    return items


def _public_product_id(
    source_type: Literal["self", "reseller"],
    local_id: int,
    *,
    tenant_id: int,
    settings: Optional[Settings],
) -> str:
    if settings is None:
        return f"{source_type}:{local_id}"
    source_code = _public_product_source_code(source_type)
    masked_id = local_id ^ _public_product_id_mask(settings, tenant_id, source_code)
    payload = f"v1.{tenant_id}.{source_code}.{_to_base36(masked_id)}"
    signature = _public_product_signature(settings, payload)
    return f"pub.{payload}.{signature}"


def _resolve_public_product_id(
    value: str,
    fallback_source_type: Optional[Literal["self", "reseller"]],
    *,
    tenant_id: int,
    settings: Settings,
) -> tuple[Literal["self", "reseller"], int]:
    if value.strip().startswith("pub."):
        return _decode_public_product_id(value, tenant_id=tenant_id, settings=settings)
    return _parse_public_product_id(value, fallback_source_type)


async def _get_tenant_order(tenant_id: int, out_trade_no: str) -> Order:
    async with get_session_factory()() as session:
        result = await session.execute(
            select(Order)
            .where(Order.tenant_id == tenant_id)
            .where(Order.out_trade_no == out_trade_no)
            .limit(1)
        )
        order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    return order


def _order_response(order: Order) -> PublicOrderResponse:
    return PublicOrderResponse(
        out_trade_no=order.out_trade_no,
        amount=order.amount,
        currency=order.currency,
        status=order.status,
        expires_at=order.expires_at.isoformat(),
        paid_at=order.paid_at.isoformat() if order.paid_at else None,
        delivered_at=order.delivered_at.isoformat() if order.delivered_at else None,
        can_pay=order.status == "pending" and order.expires_at > datetime.now(timezone.utc),
    )


def _parse_public_product_id(
    value: str,
    fallback_source_type: Optional[Literal["self", "reseller"]],
) -> tuple[Literal["self", "reseller"], int]:
    raw_value = value.strip()
    if ":" in raw_value:
        prefix, raw_id = raw_value.split(":", 1)
        if prefix not in {"self", "reseller"}:
            raise HTTPException(status_code=400, detail="商品 ID 前缀无效")
        source_type: Literal["self", "reseller"] = prefix  # type: ignore[assignment]
    else:
        raw_id = raw_value
        source_type = fallback_source_type or "self"
    try:
        product_id = int(raw_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="商品 ID 必须是数字或 self:ID/reseller:ID")
    if product_id <= 0:
        raise HTTPException(status_code=400, detail="商品 ID 必须大于 0")
    return source_type, product_id


def _decode_public_product_id(
    value: str,
    *,
    tenant_id: int,
    settings: Settings,
) -> tuple[Literal["self", "reseller"], int]:
    parts = value.strip().split(".")
    if len(parts) != 6 or parts[0] != "pub" or parts[1] != "v1":
        raise HTTPException(status_code=400, detail="公开商品 ID 格式无效")
    _, version, raw_tenant_id, source_code, raw_masked_id, signature = parts
    payload = f"{version}.{raw_tenant_id}.{source_code}.{raw_masked_id}"
    if not hmac.compare_digest(signature, _public_product_signature(settings, payload)):
        raise HTTPException(status_code=400, detail="公开商品 ID 签名无效")
    try:
        decoded_tenant_id = int(raw_tenant_id)
        masked_id = _from_base36(raw_masked_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="公开商品 ID 格式无效")
    if decoded_tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="商品不存在")
    source_type = _public_product_source_type(source_code)
    local_id = masked_id ^ _public_product_id_mask(settings, tenant_id, source_code)
    if local_id <= 0:
        raise HTTPException(status_code=400, detail="公开商品 ID 格式无效")
    return source_type, local_id


def _public_product_source_code(source_type: Literal["self", "reseller"]) -> str:
    return "s" if source_type == "self" else "r"


def _public_product_source_type(source_code: str) -> Literal["self", "reseller"]:
    if source_code == "s":
        return "self"
    if source_code == "r":
        return "reseller"
    raise HTTPException(status_code=400, detail="公开商品 ID 格式无效")


def _public_product_signature(settings: Settings, payload: str) -> str:
    digest = hmac.new(_public_product_secret(settings), payload.encode("utf-8"), hashlib.sha256).digest()
    return _base64url(digest[:16])


def _public_product_id_mask(settings: Settings, tenant_id: int, source_code: str) -> int:
    payload = f"public-product-mask:{tenant_id}:{source_code}".encode("utf-8")
    digest = hmac.new(_public_product_secret(settings), payload, hashlib.sha256).digest()
    return int.from_bytes(digest[:8], "big")


def _public_product_secret(settings: Settings) -> bytes:
    if settings.token_encryption_key is not None:
        return settings.token_encryption_key.get_secret_value().encode("utf-8")
    if settings.master_bot_token is not None:
        return settings.master_bot_token.get_secret_value().encode("utf-8")
    return f"public-store:{settings.public_base_url}:{settings.app_env}".encode("utf-8")


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _to_base36(value: int) -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    if value == 0:
        return "0"
    chars: list[str] = []
    while value:
        value, remainder = divmod(value, 36)
        chars.append(alphabet[remainder])
    return "".join(reversed(chars))


def _from_base36(value: str) -> int:
    if not value or any(char not in "0123456789abcdefghijklmnopqrstuvwxyz" for char in value):
        raise ValueError("invalid base36 value")
    return int(value, 36)


def _stock_status(delivery_type: str, available_count: int) -> str:
    if delivery_type in {"card_pool", "card_fixed"} and available_count <= 0:
        return "sold_out"
    return "available"


def _setting_text(settings: Dict[str, Dict[str, Any]], key: str, default: str) -> str:
    value = settings.get(key, {})
    return str(value.get("text") or default)


def _order_timeout_minutes(settings: Dict[str, Dict[str, Any]]) -> int:
    value = settings.get("order_timeout_minutes", {}).get("value", 15)
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        return 15
    return min(max(timeout, 1), 1440)
