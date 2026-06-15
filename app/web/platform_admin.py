from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.config import PLATFORM_ADMIN_SCOPE_VALUES, Settings
from app.db.session import get_session_factory
from app.services.api_security import (
    ApiIpAccessError,
    ApiRateLimitError,
    ApiSignatureError,
    FixedWindowRateLimiter,
    RedisFixedWindowRateLimiter,
    hit_rate_limit,
    require_ip_allowed,
    resolve_client_ip,
    verify_request_signature,
)
from app.services.audit import AuditLogService, PlatformRiskAuditLogSummary
from app.services.ledger import LedgerService, WithdrawalSummary
from app.services.risk import PlatformRiskBannedUserSummary, PlatformRiskBanStatusSummary, RiskControlService
from app.services.subscriptions import PlatformSubscriptionPlanSummary, SubscriptionService
from app.services.supply import PlatformSupplierOfferSummary, SupplyService

logger = logging.getLogger(__name__)

PLATFORM_RISK_READ_SCOPE = "platform_risk:read"
PLATFORM_RISK_WRITE_SCOPE = "platform_risk:write"
PLATFORM_FINANCE_READ_SCOPE = "platform_finance:read"
PLATFORM_FINANCE_WRITE_SCOPE = "platform_finance:write"
PLATFORM_SUBSCRIPTIONS_READ_SCOPE = "platform_subscriptions:read"
PLATFORM_SUBSCRIPTIONS_WRITE_SCOPE = "platform_subscriptions:write"
PLATFORM_SUPPLY_READ_SCOPE = "platform_supply:read"
PLATFORM_SUPPLY_WRITE_SCOPE = "platform_supply:write"
PLATFORM_ADMIN_SCOPES = set(PLATFORM_ADMIN_SCOPE_VALUES)
PLATFORM_ADMIN_ERROR_SENSITIVE_MARKERS = (
    "token",
    "secret",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "private_key",
    "payload",
)


@dataclass(frozen=True)
class PlatformAdminPrincipal:
    key_hash: str
    scopes: frozenset[str]


class PlatformRiskBannedUserItem(BaseModel):
    telegram_user_id: int
    username: Optional[str] = None
    is_banned: bool
    ban_source: Optional[str] = None
    latest_action: Optional[str] = None
    latest_action_at: Optional[str] = None
    reason: Optional[str] = None
    trigger_rule: Optional[str] = None
    blocked_count: Optional[int] = None
    threshold: Optional[int] = None
    window_seconds: Optional[int] = None
    created_at: str
    updated_at: str


class ListPlatformRiskBannedUsersResponse(BaseModel):
    users: List[PlatformRiskBannedUserItem]


class PlatformRiskAuditLogItem(BaseModel):
    created_at: str
    action: str
    target_type: Optional[str] = None
    actor_telegram_user_id: Optional[int] = None
    actor_username: Optional[str] = None
    target_telegram_user_id: Optional[int] = None
    previous_status: Optional[str] = None
    new_status: Optional[str] = None
    reason: Optional[str] = None
    risk_rule: Optional[str] = None
    blocked_count: Optional[int] = None
    threshold: Optional[int] = None
    window_seconds: Optional[int] = None


class ListPlatformRiskAuditLogsResponse(BaseModel):
    audit_logs: List[PlatformRiskAuditLogItem]


class PlatformRiskBanStatusResponse(BaseModel):
    telegram_user_id: int
    username: Optional[str] = None
    is_banned: bool
    ban_source: Optional[str] = None
    latest_action: Optional[str] = None
    latest_action_at: Optional[str] = None
    reason: Optional[str] = None
    trigger_rule: Optional[str] = None
    blocked_count: Optional[int] = None
    threshold: Optional[int] = None
    window_seconds: Optional[int] = None
    created_at: str
    updated_at: str


class PlatformRiskBanStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(min_length=1, max_length=32)
    reason: Optional[str] = Field(default=None, max_length=500)


class PlatformTenantSuspensionStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(min_length=1, max_length=32)
    reason: Optional[str] = Field(default=None, max_length=500)


class PlatformTenantSuspensionStatusResponse(BaseModel):
    tenant_id: int
    previous_status: str
    status: str
    reason: Optional[str] = None


class PlatformWithdrawalItem(BaseModel):
    withdrawal_id: int
    tenant_id: int
    amount: Decimal
    currency: str
    network: str
    address_masked: str
    status: str
    requested_at: str


class PlatformWithdrawalDetailItem(PlatformWithdrawalItem):
    reviewed_at: Optional[str] = None
    completed_at: Optional[str] = None


class ListPlatformWithdrawalsResponse(BaseModel):
    withdrawals: List[PlatformWithdrawalItem]


class CompletePlatformWithdrawalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    admin_note: Optional[str] = Field(default=None, max_length=500)
    payout_reference: Optional[str] = Field(default=None, max_length=128)
    payout_proof_url: Optional[str] = Field(default=None, max_length=1000)


class RejectPlatformWithdrawalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    admin_note: Optional[str] = Field(default=None, max_length=500)


class PlatformSubscriptionPlanItem(BaseModel):
    code: str
    name: str
    monthly_price: Decimal
    currency: str
    trial_days: int
    grace_days: int
    enabled: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ListPlatformSubscriptionPlansResponse(BaseModel):
    plans: List[PlatformSubscriptionPlanItem]


class CreatePlatformSubscriptionPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    monthly_price: Decimal = Field(ge=0)
    currency: str = Field(default="USDT", min_length=1, max_length=16)
    trial_days: int = Field(default=30, ge=0, le=3650)
    grace_days: int = Field(default=0, ge=0, le=365)
    enabled: bool = True
    reason: Optional[str] = Field(default=None, max_length=500)


class UpdatePlatformSubscriptionPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    monthly_price: Optional[Decimal] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, min_length=1, max_length=16)
    trial_days: Optional[int] = Field(default=None, ge=0, le=3650)
    grace_days: Optional[int] = Field(default=None, ge=0, le=365)
    reason: Optional[str] = Field(default=None, max_length=500)


class UpdatePlatformSubscriptionPlanStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    reason: Optional[str] = Field(default=None, max_length=500)


class PlatformSupplierOfferItem(BaseModel):
    supplier_offer_id: int
    supplier_tenant_id: int
    supplier_store_name: str
    product_name: str
    delivery_type: str
    suggested_price: Decimal
    min_sale_price: Optional[Decimal] = None
    supplier_cost: Decimal
    currency: str
    available_count: int
    requires_approval: bool
    status: str
    created_at: str
    updated_at: str


class ListPlatformSupplierOffersResponse(BaseModel):
    offers: List[PlatformSupplierOfferItem]


class UpdatePlatformSupplierOfferStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(min_length=1, max_length=32)
    reason: Optional[str] = Field(default=None, max_length=255)


def create_platform_admin_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1/platform", tags=["platform-admin"])
    local_rate_limiter = FixedWindowRateLimiter(
        settings.platform_admin_rate_limit_per_minute,
        window_seconds=settings.rate_limit_window_seconds,
    )
    redis_rate_limiter = RedisFixedWindowRateLimiter(
        settings.platform_admin_rate_limit_per_minute,
        window_seconds=settings.rate_limit_window_seconds,
        key_prefix=f"{settings.rate_limit_key_prefix}:platform-admin",
    )

    async def require_platform_api_key(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_platform_api_key: Optional[str] = Header(default=None, alias="X-Platform-API-Key"),
        x_faka_timestamp: Optional[str] = Header(default=None, alias="X-Faka-Timestamp"),
        x_faka_signature: Optional[str] = Header(default=None, alias="X-Faka-Signature"),
        x_forwarded_for: Optional[str] = Header(default=None, alias="X-Forwarded-For"),
    ) -> PlatformAdminPrincipal:
        if not settings.platform_admin_api_key_hashes:
            raise HTTPException(status_code=503, detail="Platform Admin API 未启用")
        try:
            client_ip = resolve_client_ip(
                request.client.host if request.client is not None else None,
                x_forwarded_for,
                settings.trusted_proxy_ips,
            )
            require_ip_allowed(client_ip, settings.platform_admin_ip_allowlist, "Platform Admin API")
        except ApiIpAccessError as exc:
            raise HTTPException(status_code=403, detail=str(exc))

        plain_key = _extract_platform_api_key(authorization, x_platform_api_key)
        if plain_key is None:
            raise HTTPException(status_code=401, detail="缺少 Platform Admin API Key")
        key_hash = _sha256_hex(plain_key)
        if not _is_allowed_platform_key_hash(key_hash, settings.platform_admin_api_key_hashes):
            raise HTTPException(status_code=401, detail="Platform Admin API Key 无效")

        try:
            await hit_rate_limit(
                redis_client=getattr(request.app.state, "redis", None),
                redis_limiter=redis_rate_limiter,
                local_limiter=local_rate_limiter,
                key=f"{key_hash[:16]}:{request.method}:{request.url.path}",
            )
            if settings.platform_admin_require_signature:
                if not x_faka_timestamp or not x_faka_signature:
                    raise ApiSignatureError("缺少请求签名")
                await _verify_signed_platform_request(
                    request=request,
                    api_key=plain_key,
                    timestamp=x_faka_timestamp,
                    signature=x_faka_signature,
                    max_skew_seconds=settings.platform_admin_signature_max_skew_seconds,
                )
        except ApiRateLimitError as exc:
            raise HTTPException(status_code=429, detail=str(exc))
        except ApiSignatureError as exc:
            raise HTTPException(status_code=401, detail=str(exc))

        return PlatformAdminPrincipal(
            key_hash=key_hash,
            scopes=_platform_admin_key_scopes(key_hash, settings),
        )

    def require_platform_scope(required_scope: str):
        async def dependency(principal: PlatformAdminPrincipal = Depends(require_platform_api_key)) -> PlatformAdminPrincipal:
            if required_scope not in principal.scopes:
                raise HTTPException(status_code=403, detail="Platform Admin API Key 权限不足")
            return principal

        return dependency

    @router.get("/supply/supplier-offers", response_model=ListPlatformSupplierOffersResponse)
    async def list_platform_supplier_offers(
        status: Optional[str] = Query(default=None, max_length=32),
        supplier_tenant_id: Optional[int] = Query(default=None),
        limit: int = Query(default=20, ge=1, le=100),
        principal: PlatformAdminPrincipal = Depends(require_platform_scope("platform_supply:read")),
    ) -> ListPlatformSupplierOffersResponse:
        del principal
        try:
            async with get_session_factory()() as session:
                offers = await SupplyService().list_platform_supplier_offers(
                    session,
                    status=status,
                    supplier_tenant_id=supplier_tenant_id,
                    limit=limit,
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_platform_supply_error_detail(exc))
        return ListPlatformSupplierOffersResponse(
            offers=[_platform_supplier_offer_response(offer) for offer in offers]
        )

    @router.patch("/supply/supplier-offers/{supplier_offer_id}/status", response_model=PlatformSupplierOfferItem)
    async def update_platform_supplier_offer_status(
        supplier_offer_id: int,
        payload: UpdatePlatformSupplierOfferStatusRequest,
        principal: PlatformAdminPrincipal = Depends(require_platform_scope("platform_supply:write")),
    ) -> PlatformSupplierOfferItem:
        del principal
        try:
            async with get_session_factory()() as session:
                offer = await SupplyService().set_platform_supplier_offer_status(
                    session,
                    supplier_offer_id=supplier_offer_id,
                    status=payload.status,
                    reason=payload.reason,
                )
                await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_platform_supply_error_detail(exc))
        return _platform_supplier_offer_response(offer)

    @router.get("/risk/banned-users", response_model=ListPlatformRiskBannedUsersResponse)
    async def list_banned_users(
        source: str = Query(default="all"),
        telegram_user_id: Optional[int] = Query(default=None),
        limit: int = Query(default=20),
        principal: PlatformAdminPrincipal = Depends(require_platform_scope("platform_risk:read")),
    ) -> ListPlatformRiskBannedUsersResponse:
        del principal
        try:
            async with get_session_factory()() as session:
                users = await RiskControlService(settings).list_banned_platform_users(
                    session,
                    source=source,
                    telegram_user_id=telegram_user_id,
                    limit=limit,
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_platform_error_detail(exc))
        return ListPlatformRiskBannedUsersResponse(
            users=[_platform_risk_banned_user_response(user) for user in users]
        )

    @router.get("/risk/audit-logs", response_model=ListPlatformRiskAuditLogsResponse)
    async def list_platform_risk_audit_logs(
        action: Optional[str] = Query(default=None),
        telegram_user_id: Optional[int] = Query(default=None),
        limit: int = Query(default=20),
        principal: PlatformAdminPrincipal = Depends(require_platform_scope("platform_risk:read")),
    ) -> ListPlatformRiskAuditLogsResponse:
        del principal
        try:
            async with get_session_factory()() as session:
                audit_logs = await AuditLogService().list_platform_risk_audit_logs(
                    session,
                    action=action,
                    telegram_user_id=telegram_user_id,
                    limit=limit,
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_platform_error_detail(exc))
        return ListPlatformRiskAuditLogsResponse(
            audit_logs=[_platform_risk_audit_log_response(audit_log) for audit_log in audit_logs]
        )

    @router.get("/risk/users/{telegram_user_id}/ban-status", response_model=PlatformRiskBanStatusResponse)
    async def get_user_ban_status(
        telegram_user_id: int,
        principal: PlatformAdminPrincipal = Depends(require_platform_scope("platform_risk:read")),
    ) -> PlatformRiskBanStatusResponse:
        del principal
        try:
            async with get_session_factory()() as session:
                summary = await RiskControlService(settings).get_platform_user_ban_status(
                    session,
                    telegram_user_id=telegram_user_id,
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_platform_error_detail(exc))
        if summary is None:
            raise HTTPException(status_code=404, detail="平台用户不存在")
        return _platform_risk_ban_status_response(summary)

    @router.patch("/risk/users/{telegram_user_id}/ban-status", response_model=PlatformRiskBanStatusResponse)
    async def update_user_ban_status(
        telegram_user_id: int,
        payload: PlatformRiskBanStatusUpdateRequest,
        principal: PlatformAdminPrincipal = Depends(require_platform_scope("platform_risk:write")),
    ) -> PlatformRiskBanStatusResponse:
        del principal
        try:
            normalized_status = _normalize_platform_risk_ban_status(payload.status)
            async with get_session_factory()() as session:
                risk_service = RiskControlService(settings)
                if normalized_status == "banned":
                    await risk_service.ban_platform_user(
                        session,
                        telegram_user_id=telegram_user_id,
                        actor_user_id=None,
                        reason=payload.reason,
                    )
                else:
                    await risk_service.unban_platform_user(
                        session,
                        telegram_user_id=telegram_user_id,
                        actor_user_id=None,
                        reason=payload.reason,
                    )
                summary = await risk_service.get_platform_user_ban_status(
                    session,
                    telegram_user_id=telegram_user_id,
                )
                if summary is None:
                    raise HTTPException(status_code=404, detail="平台用户不存在")
                await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_platform_error_detail(exc))
        return _platform_risk_ban_status_response(summary)

    @router.patch("/risk/tenants/{tenant_id}/suspension-status", response_model=PlatformTenantSuspensionStatusResponse)
    async def update_tenant_suspension_status(
        tenant_id: int,
        payload: PlatformTenantSuspensionStatusUpdateRequest,
        request: Request,
        principal: PlatformAdminPrincipal = Depends(require_platform_scope("platform_risk:write")),
    ) -> PlatformTenantSuspensionStatusResponse:
        del principal
        try:
            normalized_status = _normalize_platform_tenant_suspension_status(payload.status)
            async with get_session_factory()() as session:
                risk_service = RiskControlService(settings)
                if normalized_status == "suspended":
                    result = await risk_service.suspend_tenant(
                        session,
                        tenant_id=tenant_id,
                        actor_user_id=None,
                        reason=payload.reason,
                    )
                else:
                    result = await risk_service.resume_tenant(
                        session,
                        tenant_id=tenant_id,
                        actor_user_id=None,
                        reason=payload.reason,
                    )
                await session.commit()
            await _clear_tenant_webhook_cache(request, result.webhook_secrets)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_platform_error_detail(exc))
        return _platform_tenant_suspension_status_response(result)

    @router.get("/finance/withdrawals", response_model=ListPlatformWithdrawalsResponse)
    async def list_pending_withdrawals(
        limit: int = Query(default=20),
        principal: PlatformAdminPrincipal = Depends(require_platform_scope("platform_finance:read")),
    ) -> ListPlatformWithdrawalsResponse:
        del principal
        try:
            normalized_limit = min(max(limit, 1), 100)
            async with get_session_factory()() as session:
                withdrawals = await LedgerService().list_pending_withdrawals(
                    session,
                    limit=normalized_limit,
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_platform_finance_error_detail(exc))
        return ListPlatformWithdrawalsResponse(
            withdrawals=[_platform_withdrawal_response(withdrawal) for withdrawal in withdrawals]
        )

    @router.get("/finance/withdrawals/{withdrawal_id}", response_model=PlatformWithdrawalDetailItem)
    async def get_platform_withdrawal(
        withdrawal_id: int,
        principal: PlatformAdminPrincipal = Depends(require_platform_scope("platform_finance:read")),
    ) -> PlatformWithdrawalDetailItem:
        del principal
        try:
            async with get_session_factory()() as session:
                withdrawal = await LedgerService().get_platform_withdrawal(
                    session,
                    withdrawal_id=withdrawal_id,
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_platform_finance_error_detail(exc))
        if withdrawal is None:
            raise HTTPException(status_code=404, detail="提现申请不存在")
        return _platform_withdrawal_detail_response(withdrawal)

    @router.post("/finance/withdrawals/{withdrawal_id}/complete", response_model=PlatformWithdrawalDetailItem)
    async def complete_platform_withdrawal(
        withdrawal_id: int,
        payload: CompletePlatformWithdrawalRequest,
        principal: PlatformAdminPrincipal = Depends(require_platform_scope("platform_finance:write")),
    ) -> PlatformWithdrawalDetailItem:
        del principal
        try:
            async with get_session_factory()() as session:
                withdrawal = await LedgerService().complete_withdrawal(
                    session,
                    withdrawal_id,
                    payload.admin_note,
                    actor_user_id=None,
                    payout_reference=payload.payout_reference,
                    payout_proof_url=payload.payout_proof_url,
                )
                await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_platform_finance_action_error_detail(exc))
        return _platform_withdrawal_detail_response(_platform_withdrawal_summary_from_model(withdrawal))

    @router.post("/finance/withdrawals/{withdrawal_id}/reject", response_model=PlatformWithdrawalDetailItem)
    async def reject_platform_withdrawal(
        withdrawal_id: int,
        payload: RejectPlatformWithdrawalRequest,
        principal: PlatformAdminPrincipal = Depends(require_platform_scope("platform_finance:write")),
    ) -> PlatformWithdrawalDetailItem:
        del principal
        try:
            async with get_session_factory()() as session:
                withdrawal = await LedgerService().reject_withdrawal(
                    session,
                    withdrawal_id,
                    payload.admin_note,
                    actor_user_id=None,
                )
                await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_platform_finance_action_error_detail(exc))
        return _platform_withdrawal_detail_response(_platform_withdrawal_summary_from_model(withdrawal))

    @router.get("/subscription/plans", response_model=ListPlatformSubscriptionPlansResponse)
    async def list_platform_subscription_plans(
        enabled: Optional[bool] = Query(default=None),
        limit: int = Query(default=20, ge=1),
        principal: PlatformAdminPrincipal = Depends(require_platform_scope("platform_subscriptions:read")),
    ) -> ListPlatformSubscriptionPlansResponse:
        del principal
        normalized_limit = min(limit, 100)
        try:
            async with get_session_factory()() as session:
                plans = await SubscriptionService().list_platform_subscription_plans(
                    session,
                    enabled=enabled,
                    limit=normalized_limit,
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_platform_subscription_error_detail(exc))
        return ListPlatformSubscriptionPlansResponse(
            plans=[_platform_subscription_plan_response(plan) for plan in plans]
        )

    @router.get("/subscription/plans/{plan_code}", response_model=PlatformSubscriptionPlanItem)
    async def get_platform_subscription_plan(
        plan_code: str,
        principal: PlatformAdminPrincipal = Depends(require_platform_scope("platform_subscriptions:read")),
    ) -> PlatformSubscriptionPlanItem:
        del principal
        try:
            async with get_session_factory()() as session:
                plan = await SubscriptionService().get_platform_subscription_plan(
                    session,
                    code=plan_code,
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_platform_subscription_error_detail(exc))
        if plan is None:
            raise HTTPException(status_code=404, detail="订阅计划不存在")
        return _platform_subscription_plan_response(plan)

    @router.post("/subscription/plans", response_model=PlatformSubscriptionPlanItem)
    async def create_platform_subscription_plan(
        payload: CreatePlatformSubscriptionPlanRequest,
        principal: PlatformAdminPrincipal = Depends(require_platform_scope("platform_subscriptions:write")),
    ) -> PlatformSubscriptionPlanItem:
        del principal
        try:
            async with get_session_factory()() as session:
                plan = await SubscriptionService().create_platform_subscription_plan(
                    session,
                    code=payload.code,
                    name=payload.name,
                    monthly_price=payload.monthly_price,
                    currency=payload.currency,
                    trial_days=payload.trial_days,
                    grace_days=payload.grace_days,
                    enabled=payload.enabled,
                    reason=payload.reason,
                )
                await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_platform_subscription_error_detail(exc))
        return _platform_subscription_plan_response(plan)

    @router.patch("/subscription/plans/{plan_code}", response_model=PlatformSubscriptionPlanItem)
    async def update_platform_subscription_plan(
        plan_code: str,
        payload: UpdatePlatformSubscriptionPlanRequest,
        principal: PlatformAdminPrincipal = Depends(require_platform_scope("platform_subscriptions:write")),
    ) -> PlatformSubscriptionPlanItem:
        del principal
        try:
            async with get_session_factory()() as session:
                plan = await SubscriptionService().update_platform_subscription_plan(
                    session,
                    code=plan_code,
                    name=payload.name,
                    monthly_price=payload.monthly_price,
                    currency=payload.currency,
                    trial_days=payload.trial_days,
                    grace_days=payload.grace_days,
                    reason=payload.reason,
                )
                if plan is not None:
                    await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_platform_subscription_error_detail(exc))
        if plan is None:
            raise HTTPException(status_code=404, detail="订阅计划不存在")
        return _platform_subscription_plan_response(plan)

    @router.patch("/subscription/plans/{plan_code}/status", response_model=PlatformSubscriptionPlanItem)
    async def update_platform_subscription_plan_status(
        plan_code: str,
        payload: UpdatePlatformSubscriptionPlanStatusRequest,
        principal: PlatformAdminPrincipal = Depends(require_platform_scope("platform_subscriptions:write")),
    ) -> PlatformSubscriptionPlanItem:
        del principal
        try:
            async with get_session_factory()() as session:
                plan = await SubscriptionService().set_platform_subscription_plan_enabled(
                    session,
                    code=plan_code,
                    enabled=payload.enabled,
                    reason=payload.reason,
                )
                if plan is not None:
                    await session.commit()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_platform_subscription_error_detail(exc))
        if plan is None:
            raise HTTPException(status_code=404, detail="订阅计划不存在")
        return _platform_subscription_plan_response(plan)

    return router


def _extract_platform_api_key(authorization: Optional[str], x_platform_api_key: Optional[str]) -> Optional[str]:
    if x_platform_api_key:
        stripped_api_key = x_platform_api_key.strip()
        return stripped_api_key or None
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    stripped_token = token.strip()
    return stripped_token or None


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _is_allowed_platform_key_hash(key_hash: str, allowed_hashes: set[str]) -> bool:
    return any(hmac.compare_digest(key_hash, allowed_hash) for allowed_hash in allowed_hashes)


def _platform_admin_key_scopes(key_hash: str, settings: Settings) -> frozenset[str]:
    configured_scopes = settings.platform_admin_api_key_scopes
    if not configured_scopes:
        return frozenset(PLATFORM_ADMIN_SCOPES)
    return frozenset(configured_scopes.get(key_hash, set()))


async def _verify_signed_platform_request(
    *,
    request: Request,
    api_key: str,
    timestamp: str,
    signature: str,
    max_skew_seconds: int,
) -> None:
    body = await request.body()
    verify_request_signature(
        api_key,
        method=request.method,
        path=request.url.path,
        query_string=request.url.query,
        body=body,
        timestamp=timestamp,
        signature=signature,
        max_skew_seconds=max_skew_seconds,
    )


def _platform_supplier_offer_response(summary: PlatformSupplierOfferSummary) -> PlatformSupplierOfferItem:
    return PlatformSupplierOfferItem(
        supplier_offer_id=summary.supplier_offer_id,
        supplier_tenant_id=summary.supplier_tenant_id,
        supplier_store_name=summary.supplier_store_name,
        product_name=summary.product_name,
        delivery_type=summary.delivery_type,
        suggested_price=summary.suggested_price,
        min_sale_price=summary.min_sale_price,
        supplier_cost=summary.supplier_cost,
        currency=summary.currency,
        available_count=summary.available_count,
        requires_approval=summary.requires_approval,
        status=summary.status,
        created_at=summary.created_at.isoformat(),
        updated_at=summary.updated_at.isoformat(),
    )


def _platform_risk_banned_user_response(
    summary: PlatformRiskBannedUserSummary | PlatformRiskBanStatusSummary,
) -> PlatformRiskBannedUserItem:
    return PlatformRiskBannedUserItem(
        telegram_user_id=summary.telegram_user_id,
        username=summary.username,
        is_banned=summary.is_banned,
        ban_source=summary.ban_source,
        latest_action=summary.latest_action,
        latest_action_at=summary.latest_action_at.isoformat() if summary.latest_action_at else None,
        reason=summary.reason,
        trigger_rule=summary.trigger_rule,
        blocked_count=summary.blocked_count,
        threshold=summary.threshold,
        window_seconds=summary.window_seconds,
        created_at=summary.created_at.isoformat(),
        updated_at=summary.updated_at.isoformat(),
    )


def _platform_risk_audit_log_response(summary: PlatformRiskAuditLogSummary) -> PlatformRiskAuditLogItem:
    return PlatformRiskAuditLogItem(
        created_at=summary.created_at.isoformat(),
        action=summary.action,
        target_type=summary.target_type,
        actor_telegram_user_id=summary.actor_telegram_user_id,
        actor_username=summary.actor_username,
        target_telegram_user_id=summary.target_telegram_user_id,
        previous_status=summary.previous_status,
        new_status=summary.new_status,
        reason=summary.reason,
        risk_rule=summary.risk_rule,
        blocked_count=summary.blocked_count,
        threshold=summary.threshold,
        window_seconds=summary.window_seconds,
    )


def _platform_risk_ban_status_response(summary: PlatformRiskBanStatusSummary) -> PlatformRiskBanStatusResponse:
    return PlatformRiskBanStatusResponse(
        telegram_user_id=summary.telegram_user_id,
        username=summary.username,
        is_banned=summary.is_banned,
        ban_source=summary.ban_source,
        latest_action=summary.latest_action,
        latest_action_at=summary.latest_action_at.isoformat() if summary.latest_action_at else None,
        reason=summary.reason,
        trigger_rule=summary.trigger_rule,
        blocked_count=summary.blocked_count,
        threshold=summary.threshold,
        window_seconds=summary.window_seconds,
        created_at=summary.created_at.isoformat(),
        updated_at=summary.updated_at.isoformat(),
    )


def _platform_tenant_suspension_status_response(result: object) -> PlatformTenantSuspensionStatusResponse:
    return PlatformTenantSuspensionStatusResponse(
        tenant_id=result.tenant_id or result.target_id,
        previous_status=result.previous_status,
        status=result.new_status,
        reason=result.reason,
    )


def _platform_withdrawal_response(withdrawal: WithdrawalSummary) -> PlatformWithdrawalItem:
    return PlatformWithdrawalItem(
        withdrawal_id=withdrawal.withdrawal_id,
        tenant_id=withdrawal.tenant_id,
        amount=withdrawal.amount,
        currency=withdrawal.currency,
        network=withdrawal.network,
        address_masked=_mask_finance_address(withdrawal.address),
        status=withdrawal.status,
        requested_at=withdrawal.requested_at.isoformat(),
    )


def _platform_withdrawal_detail_response(withdrawal: WithdrawalSummary) -> PlatformWithdrawalDetailItem:
    item = _platform_withdrawal_response(withdrawal)
    return PlatformWithdrawalDetailItem(
        **item.model_dump(),
        reviewed_at=withdrawal.reviewed_at.isoformat() if withdrawal.reviewed_at is not None else None,
        completed_at=withdrawal.completed_at.isoformat() if withdrawal.completed_at is not None else None,
    )


def _platform_withdrawal_summary_from_model(withdrawal: object) -> WithdrawalSummary:
    return WithdrawalSummary(
        withdrawal_id=getattr(withdrawal, "id"),
        tenant_id=getattr(withdrawal, "tenant_id"),
        amount=getattr(withdrawal, "amount"),
        currency=getattr(withdrawal, "currency"),
        network=getattr(withdrawal, "network"),
        address=getattr(withdrawal, "address"),
        status=getattr(withdrawal, "status"),
        requested_at=getattr(withdrawal, "requested_at"),
        payout_reference=getattr(withdrawal, "payout_reference", None),
        payout_proof_url=getattr(withdrawal, "payout_proof_url", None),
        reviewed_at=getattr(withdrawal, "reviewed_at", None),
        completed_at=getattr(withdrawal, "completed_at", None),
    )


def _platform_subscription_plan_response(summary: PlatformSubscriptionPlanSummary) -> PlatformSubscriptionPlanItem:
    return PlatformSubscriptionPlanItem(
        code=summary.code,
        name=summary.name,
        monthly_price=summary.monthly_price,
        currency=summary.currency,
        trial_days=summary.trial_days,
        grace_days=summary.grace_days,
        enabled=summary.enabled,
        created_at=summary.created_at.isoformat() if summary.created_at is not None else None,
        updated_at=summary.updated_at.isoformat() if summary.updated_at is not None else None,
    )


def _mask_finance_address(value: str) -> str:
    if len(value) <= 12:
        return "***"
    return f"{value[:6]}***{value[-6:]}"


def _normalize_platform_risk_ban_status(status: str) -> str:
    normalized = status.strip().lower()
    if normalized not in {"banned", "active"}:
        raise ValueError("封禁状态必须是 banned 或 active")
    return normalized


def _normalize_platform_tenant_suspension_status(status: str) -> str:
    normalized = status.strip().lower()
    if normalized not in {"suspended", "active"}:
        raise ValueError("租户冻结状态必须是 suspended 或 active")
    return normalized


async def _clear_tenant_webhook_cache(request: Request, webhook_secrets: tuple[str, ...]) -> None:
    if not webhook_secrets:
        return
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        return
    keys = [f"tenant_webhook:{secret}" for secret in webhook_secrets if secret]
    if not keys:
        return
    try:
        await redis_client.delete(*keys)
    except Exception:
        logger.exception("tenant webhook cache cleanup failed")


def _safe_platform_supply_error_detail(exc: ValueError) -> str:
    message = str(exc)
    lowered = message.lower()
    if "http://" in lowered or "https://" in lowered:
        return "平台供货管控参数无效"
    if any(marker in lowered for marker in PLATFORM_ADMIN_ERROR_SENSITIVE_MARKERS):
        return "平台供货管控参数无效"
    if "供货商品" in message or "供应商租户 ID" in message:
        return message
    return "平台供货管控参数无效"


def _safe_platform_finance_error_detail(exc: ValueError) -> str:
    message = str(exc)
    lowered = message.lower()
    if "http://" in lowered or "https://" in lowered:
        return "平台财务查询参数无效"
    if any(marker in lowered for marker in PLATFORM_ADMIN_ERROR_SENSITIVE_MARKERS):
        return "平台财务查询参数无效"
    if "提现" in message or "查询数量" in message:
        return message
    return "平台财务查询参数无效"


def _safe_platform_finance_action_error_detail(exc: ValueError) -> str:
    message = str(exc)
    lowered = message.lower()
    if "http://" in lowered or "https://" in lowered:
        return "平台财务操作参数无效"
    if any(marker in lowered for marker in PLATFORM_ADMIN_ERROR_SENSITIVE_MARKERS):
        return "平台财务操作参数无效"
    if "提现" in message or "余额" in message or "备注" in message or "打款" in message or "凭证" in message:
        return message
    return "平台财务操作参数无效"


def _safe_platform_subscription_error_detail(exc: ValueError) -> str:
    message = str(exc)
    lowered = message.lower()
    if "http://" in lowered or "https://" in lowered:
        return "平台订阅计划参数无效"
    if any(marker in lowered for marker in PLATFORM_ADMIN_ERROR_SENSITIVE_MARKERS):
        return "平台订阅计划参数无效"
    if (
        "订阅计划" in message
        or "订阅月费" in message
        or "试用天数" in message
        or "宽限天数" in message
        or "调整原因" in message
        or "limit" in message
    ):
        return message
    return "平台订阅计划参数无效"


def _safe_platform_error_detail(exc: ValueError) -> str:
    message = str(exc)
    lowered = message.lower()
    if "http://" in lowered or "https://" in lowered:
        return "平台风控查询参数无效"
    if any(marker in lowered for marker in PLATFORM_ADMIN_ERROR_SENSITIVE_MARKERS):
        return "平台风控查询参数无效"
    if (
        "封禁来源" in message
        or "封禁状态" in message
        or "租户不存在" in message
        or "租户已冻结" in message
        or "租户当前未冻结" in message
        or "租户冻结状态" in message
        or "Telegram 用户 ID" in message
        or "查询数量" in message
    ):
        return message
    return "平台风控查询参数无效"
