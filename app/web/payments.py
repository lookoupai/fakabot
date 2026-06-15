from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from html import escape
from typing import Any, Dict
from urllib.parse import parse_qsl

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from app.bots.factory import create_bot
from app.config import Settings
from app.db.repos.tenants import TenantRepository
from app.db.session import get_session_factory
from app.services.delivery import send_delivery_instruction
from app.services.payments import PaymentService, PaymentUnavailableError
from app.services.payments.failures import PaymentCallbackRejectionAuditService
from app.services.payments.trc20_direct import normalize_tron_address
from app.services.token_crypto import TokenCrypto


OFFLINE_PAYMENT_CALLBACK_PATHS = (
    "/callback/token188",
    "/callback/epay_compatible",
    "/callback/lemzf",
)
MAX_PAYMENT_CALLBACK_BODY_BYTES = 64 * 1024
MAX_PAYMENT_CALLBACK_QUERY_BYTES = 8 * 1024
MAX_PAYMENT_CALLBACK_FIELD_COUNT = 64
MAX_PAYMENT_CALLBACK_KEY_LENGTH = 128
MAX_PAYMENT_CALLBACK_VALUE_LENGTH = 4096


class _DuplicateCallbackFieldError(ValueError):
    pass


def create_payment_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/payments", tags=["payments"])

    @router.post("/callback/epusdt_gmpay")
    async def epusdt_callback(request: Request) -> PlainTextResponse:
        return await _handle_payment_callback(settings, "epusdt_gmpay", request, epusdt_compat=True)

    @router.post("/callback/{provider_name}")
    async def payment_callback_post(provider_name: str, request: Request) -> PlainTextResponse:
        return await _handle_payment_callback(settings, provider_name, request)

    @router.get("/callback/{provider_name}")
    async def payment_callback_get(provider_name: str, request: Request) -> PlainTextResponse:
        return await _handle_payment_callback(settings, provider_name, request)

    @router.get("/trc20-direct/{out_trade_no}", response_class=HTMLResponse)
    async def trc20_direct_payment_instruction(out_trade_no: str, request: Request) -> HTMLResponse:
        address = _safe_trc20_instruction_address(request.query_params.get("address"))
        amount = _safe_trc20_instruction_amount(request.query_params.get("amount"))
        asset = _safe_fixed_instruction_value(request.query_params.get("asset") or "USDT", "USDT")
        network = _safe_fixed_instruction_value(request.query_params.get("network") or "TRC20", "TRC20")
        order_no = _safe_instruction_text(out_trade_no, max_length=96)
        return HTMLResponse(
            _render_trc20_direct_instruction_html(
                out_trade_no=order_no,
                address=address,
                amount=amount,
                asset=asset,
                network=network,
            )
        )

    return router


async def _handle_payment_callback(
    settings: Settings,
    provider_name: str,
    request: Request,
    *,
    epusdt_compat: bool = False,
) -> PlainTextResponse:
    try:
        payload = await _read_callback_payload(request)
    except HTTPException as exc:
        await _record_callback_rejection(
            provider_name=provider_name,
            payload=None,
            reason_category="payload_malformed",
            http_status=exc.status_code,
        )
        raise

    service = PaymentService(settings)
    try:
        async with get_session_factory()() as session:
            if epusdt_compat:
                result = await service.process_epusdt_callback(session, payload)
            else:
                result = await service.process_payment_callback(session, provider_name, payload)
            await session.commit()
    except PaymentUnavailableError as exc:
        await _record_callback_rejection(
            provider_name=provider_name,
            payload=payload,
            reason_category="payment_unavailable",
            http_status=503,
        )
        raise HTTPException(status_code=503, detail="支付配置暂不可用") from exc
    except ValueError as exc:
        await _record_callback_rejection(
            provider_name=provider_name,
            payload=payload,
            reason_category="invalid_callback",
            http_status=400,
        )
        raise HTTPException(status_code=400, detail="支付回调参数无效") from exc

    if result.delivery_record_id is not None:
        await _deliver_pending_record(settings, service, result.delivery_record_id)
    return PlainTextResponse("ok")


async def _read_callback_payload(request: Request) -> Dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="回调 payload 无效") from exc
        if declared_length > MAX_PAYMENT_CALLBACK_BODY_BYTES:
            raise HTTPException(status_code=413, detail="支付回调 payload 过大")
    query_bytes = request.scope.get("query_string", b"")
    if isinstance(query_bytes, bytes) and len(query_bytes) > MAX_PAYMENT_CALLBACK_QUERY_BYTES:
        raise HTTPException(status_code=413, detail="支付回调 payload 过大")
    try:
        body = await request.body()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="回调 payload 无法读取") from exc
    if len(body) > MAX_PAYMENT_CALLBACK_BODY_BYTES:
        raise HTTPException(status_code=413, detail="支付回调 payload 过大")
    if "application/json" in content_type:
        data = _read_json_object_no_duplicate_keys(body)
        _validate_callback_payload_shape(data)
        return data
    if not body and request.query_params:
        return _pairs_to_callback_payload(request.query_params.multi_items())
    try:
        pairs = parse_qsl(body.decode(), keep_blank_values=True)
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="回调表单无效") from exc
    return _pairs_to_callback_payload(pairs)


def _read_json_object_no_duplicate_keys(body: bytes) -> Dict[str, Any]:
    try:
        data = json.loads(body.decode() or "{}", object_pairs_hook=_json_object_no_duplicate_keys)
    except _DuplicateCallbackFieldError as exc:
        raise HTTPException(status_code=400, detail="回调 payload 包含重复字段") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="回调 JSON 无效") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="回调 JSON 必须是对象")
    return data


def _json_object_no_duplicate_keys(pairs: list[tuple[str, Any]]) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    for key, value in pairs:
        if key in data:
            raise _DuplicateCallbackFieldError("duplicate callback field")
        data[key] = value
    return data


def _pairs_to_callback_payload(pairs: list[tuple[str, str]] | list[tuple[str, Any]]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise HTTPException(status_code=400, detail="回调 payload 包含重复字段")
        payload[key] = value
    _validate_callback_payload_shape(payload)
    return payload


def _validate_callback_payload_shape(payload: Dict[str, Any]) -> None:
    if len(payload) > MAX_PAYMENT_CALLBACK_FIELD_COUNT:
        raise HTTPException(status_code=400, detail="回调 payload 字段过多")
    for key, value in payload.items():
        if not isinstance(key, str) or not key:
            raise HTTPException(status_code=400, detail="回调 payload 字段无效")
        if len(key) > MAX_PAYMENT_CALLBACK_KEY_LENGTH or _has_control_character(key):
            raise HTTPException(status_code=400, detail="回调 payload 字段无效")
        if isinstance(value, str) and _has_control_character(value):
            raise HTTPException(status_code=400, detail="回调 payload 字段值无效")
        if _safe_callback_value_length(value) > MAX_PAYMENT_CALLBACK_VALUE_LENGTH:
            raise HTTPException(status_code=400, detail="回调 payload 字段值过长")


def _safe_callback_value_length(value: Any) -> int:
    if isinstance(value, str):
        return len(value)
    try:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    except (TypeError, ValueError):
        return MAX_PAYMENT_CALLBACK_VALUE_LENGTH + 1


def _has_control_character(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def _safe_trc20_instruction_address(value: str | None) -> str:
    try:
        return normalize_tron_address(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="TRC20 直付参数无效") from exc


def _safe_trc20_instruction_amount(value: str | None) -> str:
    try:
        amount = Decimal(str(value or "").strip())
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(status_code=400, detail="TRC20 直付参数无效") from exc
    if not amount.is_finite() or amount <= 0:
        raise HTTPException(status_code=400, detail="TRC20 直付参数无效")
    return format(amount.normalize(), "f")


def _safe_fixed_instruction_value(value: str, expected: str) -> str:
    normalized = _safe_instruction_text(value, max_length=32).upper()
    if normalized != expected:
        raise HTTPException(status_code=400, detail="TRC20 直付参数无效")
    return normalized


def _safe_instruction_text(value: str | None, *, max_length: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > max_length or _has_control_character(text):
        raise HTTPException(status_code=400, detail="TRC20 直付参数无效")
    return text


def _render_trc20_direct_instruction_html(
    *,
    out_trade_no: str,
    address: str,
    amount: str,
    asset: str,
    network: str,
) -> str:
    return (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>TRC20-USDT 付款说明</title>"
        "<style>body{font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
        "max-width:720px;margin:0 auto;padding:24px;line-height:1.6;color:#111827}"
        "code{display:block;word-break:break-all;background:#f3f4f6;border:1px solid #e5e7eb;"
        "border-radius:6px;padding:12px}dl{display:grid;grid-template-columns:96px 1fr;gap:8px 12px}"
        "dt{color:#6b7280}dd{margin:0;font-weight:600}.warn{color:#b45309}</style></head><body>"
        "<h1>TRC20-USDT 付款说明</h1>"
        "<p class=\"warn\">请按页面金额向下方 TRC20 地址转账。平台不会在此页面连接钱包或扫描链上交易。</p>"
        "<dl>"
        f"<dt>订单号</dt><dd>{escape(out_trade_no)}</dd>"
        f"<dt>网络</dt><dd>{escape(network)}</dd>"
        f"<dt>资产</dt><dd>{escape(asset)}</dd>"
        f"<dt>金额</dt><dd>{escape(amount)} {escape(asset)}</dd>"
        "</dl>"
        "<h2>收款地址</h2>"
        f"<code>{escape(address)}</code>"
        "<p>完成转账后，请返回店铺等待订单状态刷新。实际确认仍依赖平台后续链上记录和本地匹配。</p>"
        "</body></html>"
    )


async def _record_callback_rejection(
    *,
    provider_name: str,
    payload: Dict[str, Any] | None,
    reason_category: str,
    http_status: int,
) -> None:
    try:
        async with get_session_factory()() as session:
            await PaymentCallbackRejectionAuditService().record_rejection(
                session,
                provider_name=provider_name,
                payload=payload,
                reason_category=reason_category,
                http_status=http_status,
            )
            await session.commit()
    except Exception:
        return


async def _deliver_pending_record(settings: Settings, service: PaymentService, delivery_record_id: int) -> None:
    async with get_session_factory()() as session:
        instruction = await service.claim_delivery(session, delivery_record_id)
        encrypted_bot_token = None
        if instruction is not None:
            tenant_bot = await TenantRepository().get_active_bot_by_tenant_id(session, instruction.tenant_id)
            encrypted_bot_token = tenant_bot.encrypted_token if tenant_bot is not None else None
        await session.commit()

    if instruction is None:
        return
    if encrypted_bot_token is None:
        await _mark_delivery_failed(service, delivery_record_id, "租户 Bot 不可用，无法自动发货")
        return

    crypto = TokenCrypto(settings)
    try:
        bot_token = crypto.decrypt_token(encrypted_bot_token)
        bot = create_bot(bot_token)
        try:
            await send_delivery_instruction(bot, settings, crypto, instruction)
        finally:
            await bot.session.close()
    except Exception as exc:
        await _mark_delivery_failed(service, delivery_record_id, str(exc))
        return

    async with get_session_factory()() as session:
        await service.mark_delivery_sent(session, delivery_record_id)
        await session.commit()


async def _mark_delivery_failed(service: PaymentService, delivery_record_id: int, error_message: str) -> None:
    async with get_session_factory()() as session:
        await service.mark_delivery_failed(session, delivery_record_id, error_message)
        await session.commit()
