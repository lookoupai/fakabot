from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any, Mapping, Optional
from urllib.parse import urlencode, urlsplit, urlunsplit

from app.services.payments.base import PaymentCallbackResult, PaymentCreateResult, PaymentOrderRequest, PaymentQueryResult
from app.services.payments.epusdt import payload_hash
from app.services.payments.safety import sanitize_payment_callback_payload


EPAY_COMPATIBLE_PROVIDER = "epay_compatible"
LEMZF_PROVIDER = "lemzf"
DEFAULT_EPAY_GATEWAY_URL = "https://a1004a.lempay.com/submit.php"
EPAY_OFFLINE_QUERY_CONTRACT = "epay_compatible_offline_query_v1"


@dataclass(frozen=True)
class EpayCompatibleConfig:
    merchant_id: str
    key: str
    gateway_url: str = DEFAULT_EPAY_GATEWAY_URL
    payment_type: str = "alipay"
    device: str = "mobile"
    return_url: Optional[str] = None
    provider_name: str = EPAY_COMPATIBLE_PROVIDER
    subject: str = "FakaBot Order"


class EpayCompatibleProvider:
    provider = EPAY_COMPATIBLE_PROVIDER

    def __init__(self, config: EpayCompatibleConfig) -> None:
        self._config = _normalize_config(config)
        self.provider = self._config.provider_name

    async def create_order(self, request: PaymentOrderRequest) -> PaymentCreateResult:
        params = build_epay_page_payment_params(self._config, request)
        payment_url = build_epay_page_payment_url(self._config.gateway_url, params)
        return PaymentCreateResult(
            provider=self.provider,
            out_trade_no=request.out_trade_no,
            provider_trade_no=None,
            payment_url=payment_url,
            raw_response={
                "gateway_url": normalize_epay_gateway_url(self._config.gateway_url),
                "merchant_id": self._config.merchant_id,
                "type": params["type"],
                "out_trade_no": request.out_trade_no,
                "money": params["money"],
            },
        )

    def verify_callback(self, payload: dict[str, Any]) -> PaymentCallbackResult:
        return verify_epay_callback(payload, self._config)

    async def query_order(self, provider_trade_no: str) -> PaymentQueryResult:
        raise NotImplementedError("易支付兼容通道暂未提供离线对账查询适配")


class LemzfProvider(EpayCompatibleProvider):
    provider = LEMZF_PROVIDER

    def __init__(self, config: EpayCompatibleConfig) -> None:
        normalized = _normalize_config(config)
        super().__init__(
            EpayCompatibleConfig(
                merchant_id=normalized.merchant_id,
                key=normalized.key,
                gateway_url=normalized.gateway_url,
                payment_type=normalized.payment_type,
                device=normalized.device,
                return_url=normalized.return_url,
                provider_name=LEMZF_PROVIDER,
                subject=normalized.subject,
            )
        )


def normalize_epay_query_payload(
    payload: Mapping[str, Any],
    config: EpayCompatibleConfig,
    *,
    expected_out_trade_no: str,
    expected_amount: Optional[Decimal] = None,
) -> PaymentQueryResult:
    return normalize_epay_offline_query_response(
        payload,
        config,
        expected_out_trade_no=expected_out_trade_no,
        expected_amount=expected_amount,
    )


def build_epay_offline_query_contract_request(
    config: EpayCompatibleConfig,
    *,
    out_trade_no: str,
    provider_trade_no: Optional[str] = None,
) -> dict[str, str]:
    normalized_config = _normalize_config(config)
    payload = {
        "contract": EPAY_OFFLINE_QUERY_CONTRACT,
        "pid": normalized_config.merchant_id,
        "out_trade_no": _required_text(out_trade_no, "易支付查单订单号不能为空"),
    }
    if provider_trade_no:
        payload["trade_no"] = _required_text(provider_trade_no, "易支付查单上游流水号不能为空")
    payload["sign"] = sign_epay_payload(payload, normalized_config.key)
    payload["sign_type"] = "MD5"
    return payload


def normalize_epay_offline_query_response(
    payload: Mapping[str, Any],
    config: EpayCompatibleConfig,
    *,
    expected_out_trade_no: str,
    expected_amount: Optional[Decimal] = None,
) -> PaymentQueryResult:
    """Normalize a FakaBot offline epay-compatible query fixture without enabling real reconciliation."""

    if not isinstance(payload, Mapping):
        raise ValueError("易支付查单响应必须是对象")
    normalized_config = _normalize_config(config)
    if _required_text(payload.get("contract"), "易支付查单响应缺少离线合同") != EPAY_OFFLINE_QUERY_CONTRACT:
        raise ValueError("易支付查单响应离线合同不匹配")
    received_sign = _required_text(payload.get("sign"), "易支付查单响应缺少签名")
    expected_sign = sign_epay_payload(payload, normalized_config.key)
    if received_sign.lower() != expected_sign:
        raise ValueError("易支付查单响应签名无效")
    if _required_text(payload.get("pid"), "易支付查单响应缺少商户号") != normalized_config.merchant_id:
        raise ValueError("易支付查单响应商户不匹配")

    out_trade_no = _required_text(payload.get("out_trade_no"), "易支付查单响应缺少订单号")
    expected_order = _required_text(expected_out_trade_no, "易支付期望订单号不能为空")
    if out_trade_no != expected_order:
        raise ValueError("易支付查单响应订单号不匹配")
    if expected_amount is not None:
        _validate_query_amount(payload.get("money"), expected_amount, "易支付查单响应金额不匹配")

    status = _required_text(
        payload.get("trade_status") or payload.get("status") or payload.get("state"),
        "易支付查单响应缺少状态",
    )
    paid, expired, normalized_status = _normalize_query_status(status, "易支付")
    provider_trade_no = _optional_text(payload.get("trade_no") or payload.get("provider_trade_no"))
    return PaymentQueryResult(
        provider=normalized_config.provider_name,
        provider_trade_no=provider_trade_no or out_trade_no,
        paid=paid,
        expired=expired,
        status=normalized_status,
        raw_response=_safe_callback_payload(payload),
    )


def build_epay_page_payment_params(config: EpayCompatibleConfig, request: PaymentOrderRequest) -> dict[str, str]:
    normalized_config = _normalize_config(config)
    params = {
        "pid": normalized_config.merchant_id,
        "type": normalized_config.payment_type,
        "out_trade_no": _required_text(request.out_trade_no, "易支付订单号不能为空"),
        "notify_url": _required_text(request.notify_url, "易支付回调地址不能为空"),
        "name": normalized_config.subject,
        "money": _format_epay_amount(request.amount),
        "device": normalized_config.device,
    }
    if normalized_config.return_url:
        params["return_url"] = normalized_config.return_url
    params["sign"] = sign_epay_payload(params, normalized_config.key)
    params["sign_type"] = "MD5"
    return params


def build_epay_page_payment_url(gateway_url: str, params: Mapping[str, object]) -> str:
    normalized_gateway = normalize_epay_gateway_url(gateway_url)
    parts = urlsplit(normalized_gateway)
    if parts.query:
        raise ValueError("易支付 gateway URL 不能包含 query")
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", urlencode(_normalize_query_items(params)), ""))


def verify_epay_callback(payload: dict[str, Any], config: EpayCompatibleConfig) -> PaymentCallbackResult:
    if not isinstance(payload, dict):
        raise ValueError("易支付回调必须是对象")
    normalized_config = _normalize_config(config)
    received_sign = _optional_text(payload.get("sign"))
    if not received_sign:
        raise ValueError("易支付回调缺少签名")
    expected_sign = sign_epay_payload(payload, normalized_config.key)
    if received_sign.lower() != expected_sign:
        raise ValueError("易支付回调签名无效")
    if _optional_text(payload.get("pid")) != normalized_config.merchant_id:
        raise ValueError("易支付回调商户不匹配")

    out_trade_no = _optional_text(payload.get("out_trade_no"))
    if not out_trade_no:
        raise ValueError("易支付回调缺少订单号")
    status = (_optional_text(payload.get("trade_status")) or "").upper()
    paid = status in {"TRADE_SUCCESS", "TRADE_FINISHED", "SUCCESS", "PAID"}
    return PaymentCallbackResult(
        provider=normalized_config.provider_name,
        out_trade_no=out_trade_no,
        provider_trade_no=_optional_text(payload.get("trade_no")),
        paid=paid,
        payload_hash=payload_hash(payload),
        raw_payload=_safe_callback_payload(payload),
    )


def sign_epay_payload(payload: Mapping[str, object], key: str) -> str:
    secret_key = _required_text(key, "易支付 key 不能为空")
    items = []
    for item_key, item_value in payload.items():
        key_text = str(item_key)
        if key_text in {"sign", "sign_type"}:
            continue
        if item_value is None or item_value == "" or item_value == 0 or str(item_value) == "0":
            continue
        items.append((key_text, str(item_value).strip()))
    signing_text = "&".join(f"{item_key}={item_value}" for item_key, item_value in sorted(items))
    return hashlib.md5(f"{signing_text}{secret_key}".encode("utf-8")).hexdigest().lower()


def normalize_epay_gateway_url(url: str) -> str:
    normalized = _required_text(url, "易支付 gateway URL 不能为空")
    if _contains_control_character(normalized):
        raise ValueError("易支付 gateway URL 不能包含控制字符")
    parts = urlsplit(normalized)
    if parts.scheme.lower() not in {"http", "https"}:
        raise ValueError("易支付 gateway URL 只支持 http 或 https")
    if not parts.netloc:
        raise ValueError("易支付 gateway URL 必须包含主机")
    if parts.username or parts.password:
        raise ValueError("易支付 gateway URL 不能包含用户名或密码")
    if parts.fragment:
        raise ValueError("易支付 gateway URL 不能包含 fragment")
    return urlunsplit((parts.scheme.lower(), parts.netloc, parts.path or "/", parts.query, ""))


def _normalize_config(config: EpayCompatibleConfig) -> EpayCompatibleConfig:
    if not isinstance(config, EpayCompatibleConfig):
        raise ValueError("易支付配置无效")
    provider_name = _required_text(config.provider_name, "易支付 provider_name 不能为空")
    if provider_name not in {EPAY_COMPATIBLE_PROVIDER, LEMZF_PROVIDER}:
        raise ValueError("易支付 provider_name 不支持")
    return EpayCompatibleConfig(
        merchant_id=_required_text(config.merchant_id, "易支付 merchant_id 不能为空"),
        key=_required_text(config.key, "易支付 key 不能为空"),
        gateway_url=normalize_epay_gateway_url(config.gateway_url),
        payment_type=_required_text(config.payment_type, "易支付 type 不能为空"),
        device=_required_text(config.device, "易支付 device 不能为空"),
        return_url=_optional_text(config.return_url),
        provider_name=provider_name,
        subject=_required_text(config.subject, "易支付 subject 不能为空"),
    )


def _normalize_query_items(params: Mapping[str, object]) -> list[tuple[str, str]]:
    if not isinstance(params, Mapping):
        raise ValueError("易支付 query 参数必须是字典")
    items: list[tuple[str, str]] = []
    seen_keys: set[str] = set()
    for key, value in params.items():
        normalized_key = _required_text(str(key), "易支付 query key 不能为空")
        if normalized_key in seen_keys:
            raise ValueError("易支付 query key 重复")
        seen_keys.add(normalized_key)
        if value is None:
            continue
        normalized_value = str(value).strip()
        if _contains_control_character(normalized_key) or _contains_control_character(normalized_value):
            raise ValueError("易支付 query 不能包含控制字符")
        items.append((normalized_key, normalized_value))
    return items


def _format_epay_amount(amount: Decimal) -> str:
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))
    if not amount.is_finite() or amount <= 0:
        raise ValueError("易支付金额必须大于 0")
    normalized_amount = amount.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    if normalized_amount <= 0:
        raise ValueError("易支付金额不能小于 0.01")
    return format(normalized_amount, "f")


def _validate_query_amount(value: object, expected_amount: Decimal, message: str) -> None:
    amount_text = _required_text(value, message)
    try:
        actual = Decimal(amount_text).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    except Exception as exc:
        raise ValueError(message) from exc
    expected = Decimal(_format_epay_amount(expected_amount))
    if actual != expected:
        raise ValueError(message)


def _normalize_query_status(status: str, provider_label: str) -> tuple[bool, bool, str]:
    normalized = status.strip().lower()
    paid_statuses = {"2", "paid", "success", "completed", "confirmed", "trade_success", "trade_finished"}
    pending_statuses = {"0", "1", "pending", "unpaid", "waiting", "wait_buyer_pay", "created"}
    expired_statuses = {"3", "expired", "closed", "timeout", "trade_closed", "cancelled", "canceled"}
    failed_statuses = {"failed", "fail", "error", "refunded", "refund", "rejected"}
    if normalized in paid_statuses:
        return True, False, normalized
    if normalized in pending_statuses:
        return False, False, normalized
    if normalized in expired_statuses:
        return False, True, normalized
    if normalized in failed_statuses:
        return False, False, normalized
    raise ValueError(f"{provider_label} 查单响应状态不支持")


def _safe_callback_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return sanitize_payment_callback_payload(payload)


def _required_text(value: object, message: str) -> str:
    if value is None:
        raise ValueError(message)
    text = str(value).strip()
    if not text:
        raise ValueError(message)
    if _contains_control_character(text):
        raise ValueError(message)
    return text


def _optional_text(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if _contains_control_character(text):
        raise ValueError("易支付文本不能包含控制字符")
    return text


def _contains_control_character(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)
