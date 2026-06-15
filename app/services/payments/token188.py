from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any, Mapping, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.services.payments.base import PaymentCallbackResult, PaymentCreateResult, PaymentOrderRequest, PaymentQueryResult
from app.services.payments.epusdt import payload_hash
from app.services.payments.safety import sanitize_payment_callback_payload


TOKEN188_PROVIDER = "token188"
DEFAULT_TOKEN188_GATEWAY_URL = "https://payweb.188pay.net/"
TOKEN188_OFFLINE_QUERY_CONTRACT = "token188_offline_query_v1"


@dataclass(frozen=True)
class Token188Config:
    merchant_id: str
    key: str
    monitor_address: str
    gateway_url: str = DEFAULT_TOKEN188_GATEWAY_URL
    chain_type: str = "TRX"
    return_url: Optional[str] = None


class Token188Provider:
    provider = TOKEN188_PROVIDER

    def __init__(self, config: Token188Config) -> None:
        self._config = _normalize_config(config)

    async def create_order(self, request: PaymentOrderRequest) -> PaymentCreateResult:
        params = build_token188_payment_params(self._config, request)
        payment_url = build_token188_payment_url(self._config.gateway_url, params)
        return PaymentCreateResult(
            provider=self.provider,
            out_trade_no=request.out_trade_no,
            provider_trade_no=None,
            payment_url=payment_url,
            raw_response={
                "gateway_url": normalize_token188_gateway_url(self._config.gateway_url),
                "merchant_id": self._config.merchant_id,
                "chain_type": self._config.chain_type,
                "order_no": request.out_trade_no,
                "amount": params["amount"],
            },
        )

    def verify_callback(self, payload: dict[str, Any]) -> PaymentCallbackResult:
        return verify_token188_callback(payload, self._config)

    async def query_order(self, provider_trade_no: str) -> PaymentQueryResult:
        raise NotImplementedError("TOKEN188 暂未提供离线对账查询适配")


def normalize_token188_query_payload(
    payload: Mapping[str, Any],
    config: Token188Config,
    *,
    expected_out_trade_no: str,
    expected_amount: Optional[Decimal] = None,
) -> PaymentQueryResult:
    return normalize_token188_offline_query_response(
        payload,
        config,
        expected_out_trade_no=expected_out_trade_no,
        expected_amount=expected_amount,
    )


def build_token188_offline_query_contract_request(
    config: Token188Config,
    *,
    out_trade_no: str,
    provider_trade_no: Optional[str] = None,
) -> dict[str, str]:
    normalized_config = _normalize_config(config)
    payload = {
        "contract": TOKEN188_OFFLINE_QUERY_CONTRACT,
        "merchantId": normalized_config.merchant_id,
        "orderNo": _required_text(out_trade_no, "TOKEN188 查单订单号不能为空"),
    }
    if provider_trade_no:
        payload["transactionId"] = _required_text(provider_trade_no, "TOKEN188 查单上游流水号不能为空")
    payload["sign"] = sign_token188_callback_payload(payload, normalized_config.key)
    return payload


def normalize_token188_offline_query_response(
    payload: Mapping[str, Any],
    config: Token188Config,
    *,
    expected_out_trade_no: str,
    expected_amount: Optional[Decimal] = None,
) -> PaymentQueryResult:
    """Normalize a FakaBot offline TOKEN188 query fixture without enabling real query support."""

    if not isinstance(payload, Mapping):
        raise ValueError("TOKEN188 查单响应必须是对象")
    normalized_config = _normalize_config(config)
    if _required_text(payload.get("contract"), "TOKEN188 查单响应缺少离线合同") != TOKEN188_OFFLINE_QUERY_CONTRACT:
        raise ValueError("TOKEN188 查单响应离线合同不匹配")
    received_sign = _required_text(payload.get("sign"), "TOKEN188 查单响应缺少签名")
    expected_sign = sign_token188_callback_payload(payload, normalized_config.key)
    if received_sign.upper() != expected_sign:
        raise ValueError("TOKEN188 查单响应签名无效")
    if _required_text(payload.get("merchantId"), "TOKEN188 查单响应缺少商户号") != normalized_config.merchant_id:
        raise ValueError("TOKEN188 查单响应商户不匹配")
    if _required_text(payload.get("to"), "TOKEN188 查单响应缺少收款地址") != normalized_config.monitor_address:
        raise ValueError("TOKEN188 查单响应收款地址不匹配")

    out_trade_no = _required_text(
        payload.get("orderNo") or payload.get("out_trade_no") or payload.get("order_id"),
        "TOKEN188 查单响应缺少订单号",
    )
    expected_order = _required_text(expected_out_trade_no, "TOKEN188 期望订单号不能为空")
    if out_trade_no != expected_order:
        raise ValueError("TOKEN188 查单响应订单号不匹配")
    if expected_amount is not None:
        _validate_query_amount(payload.get("amount"), expected_amount, "TOKEN188 查单响应金额不匹配")

    status = _required_text(
        payload.get("status") or payload.get("trade_status") or payload.get("state"),
        "TOKEN188 查单响应缺少状态",
    )
    paid, expired, normalized_status = _normalize_query_status(status, "TOKEN188")
    provider_trade_no = _optional_text(
        payload.get("transactionId") or payload.get("trade_no") or payload.get("provider_trade_no")
    )
    return PaymentQueryResult(
        provider=TOKEN188_PROVIDER,
        provider_trade_no=provider_trade_no or out_trade_no,
        paid=paid,
        expired=expired,
        status=normalized_status,
        raw_response=_safe_callback_payload(payload),
    )


def build_token188_payment_params(config: Token188Config, request: PaymentOrderRequest) -> dict[str, str]:
    normalized_config = _normalize_config(config)
    amount = _format_token188_amount(request.amount)
    params = {
        "merchantId": normalized_config.merchant_id,
        "amount": amount,
        "chainType": normalized_config.chain_type,
        "to": normalized_config.monitor_address,
        "orderNo": _required_text(request.out_trade_no, "TOKEN188 订单号不能为空"),
        "notifyUrl": _required_text(request.notify_url, "TOKEN188 回调地址不能为空"),
        "returnUrl": normalized_config.return_url or _derive_return_url(request.notify_url),
        "remark": _required_text(request.out_trade_no, "TOKEN188 备注不能为空"),
    }
    params["sign"] = sign_token188_gateway_payload(params, normalized_config.key)
    return params


def build_token188_payment_url(gateway_url: str, params: Mapping[str, object]) -> str:
    normalized_gateway = normalize_token188_gateway_url(gateway_url)
    parts = urlsplit(normalized_gateway)
    if parts.query:
        raise ValueError("TOKEN188 gateway URL 不能包含 query")
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", urlencode(_normalize_query_items(params)), ""))


def verify_token188_callback(payload: dict[str, Any], config: Token188Config) -> PaymentCallbackResult:
    if not isinstance(payload, dict):
        raise ValueError("TOKEN188 回调必须是对象")
    normalized_config = _normalize_config(config)
    required_fields = ("amount", "merchantId", "to", "transactionId", "sign")
    missing = [field for field in required_fields if not _optional_text(payload.get(field))]
    if missing:
        raise ValueError("TOKEN188 回调缺少必要字段")
    if _optional_text(payload.get("merchantId")) != normalized_config.merchant_id:
        raise ValueError("TOKEN188 回调商户不匹配")
    if _optional_text(payload.get("to")) != normalized_config.monitor_address:
        raise ValueError("TOKEN188 回调收款地址不匹配")
    received_sign = _optional_text(payload.get("sign")) or ""
    expected_sign = sign_token188_callback_payload(payload, normalized_config.key)
    if received_sign.upper() != expected_sign:
        raise ValueError("TOKEN188 回调签名无效")

    out_trade_no = _optional_text(payload.get("orderNo") or payload.get("out_trade_no") or payload.get("order_id"))
    if not out_trade_no:
        raise ValueError("TOKEN188 回调缺少订单号")
    provider_trade_no = _optional_text(payload.get("transactionId"))
    return PaymentCallbackResult(
        provider=TOKEN188_PROVIDER,
        out_trade_no=out_trade_no or "",
        provider_trade_no=provider_trade_no,
        paid=True,
        payload_hash=payload_hash(payload),
        raw_payload=_safe_callback_payload(payload),
    )


def sign_token188_payload(payload: Mapping[str, object], key: str) -> str:
    return sign_token188_callback_payload(payload, key)


def sign_token188_gateway_payload(payload: Mapping[str, object], key: str) -> str:
    return _sign_token188_payload(payload, key, key_prefix="", skip_empty=False)


def sign_token188_callback_payload(payload: Mapping[str, object], key: str) -> str:
    return _sign_token188_payload(payload, key, key_prefix="&key=", skip_empty=True)


def _sign_token188_payload(
    payload: Mapping[str, object],
    key: str,
    *,
    key_prefix: str,
    skip_empty: bool,
) -> str:
    secret_key = _required_text(key, "TOKEN188 key 不能为空")
    items = [
        (str(item_key), str(item_value).strip())
        for item_key, item_value in payload.items()
        if str(item_key) != "sign"
        and item_value is not None
        and (not skip_empty or str(item_value).strip())
    ]
    signing_text = "&".join(f"{item_key}={item_value}" for item_key, item_value in sorted(items))
    signing_text = f"{signing_text}{key_prefix}{secret_key}"
    return hashlib.md5(signing_text.encode("utf-8")).hexdigest().upper()


def normalize_token188_gateway_url(url: str) -> str:
    normalized = _required_text(url, "TOKEN188 gateway URL 不能为空")
    if _contains_control_character(normalized):
        raise ValueError("TOKEN188 gateway URL 不能包含控制字符")
    parts = urlsplit(normalized)
    if parts.scheme.lower() not in {"http", "https"}:
        raise ValueError("TOKEN188 gateway URL 只支持 http 或 https")
    if not parts.netloc:
        raise ValueError("TOKEN188 gateway URL 必须包含主机")
    if parts.username or parts.password:
        raise ValueError("TOKEN188 gateway URL 不能包含用户名或密码")
    if parts.fragment:
        raise ValueError("TOKEN188 gateway URL 不能包含 fragment")
    return urlunsplit((parts.scheme.lower(), parts.netloc, parts.path or "/", parts.query, ""))


def _normalize_config(config: Token188Config) -> Token188Config:
    if not isinstance(config, Token188Config):
        raise ValueError("TOKEN188 配置无效")
    return Token188Config(
        merchant_id=_required_text(config.merchant_id, "TOKEN188 merchant_id 不能为空"),
        key=_required_text(config.key, "TOKEN188 key 不能为空"),
        monitor_address=_required_text(config.monitor_address, "TOKEN188 monitor_address 不能为空"),
        gateway_url=normalize_token188_gateway_url(config.gateway_url),
        chain_type=_required_text(config.chain_type, "TOKEN188 chain_type 不能为空"),
        return_url=_optional_text(config.return_url),
    )


def _normalize_query_items(params: Mapping[str, object]) -> list[tuple[str, str]]:
    if not isinstance(params, Mapping):
        raise ValueError("TOKEN188 query 参数必须是字典")
    items: list[tuple[str, str]] = []
    seen_keys: set[str] = set()
    for key, value in params.items():
        normalized_key = _required_text(str(key), "TOKEN188 query key 不能为空")
        if normalized_key in seen_keys:
            raise ValueError("TOKEN188 query key 重复")
        seen_keys.add(normalized_key)
        if value is None:
            continue
        normalized_value = str(value).strip()
        if _contains_control_character(normalized_key) or _contains_control_character(normalized_value):
            raise ValueError("TOKEN188 query 不能包含控制字符")
        items.append((normalized_key, normalized_value))
    return items


def _format_token188_amount(amount: Decimal) -> str:
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))
    if not amount.is_finite() or amount <= 0:
        raise ValueError("TOKEN188 金额必须大于 0")
    normalized_amount = amount.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    if normalized_amount <= 0:
        raise ValueError("TOKEN188 金额不能小于 0.01")
    return format(normalized_amount, "f")


def _validate_query_amount(value: object, expected_amount: Decimal, message: str) -> None:
    amount_text = _required_text(value, message)
    try:
        actual = Decimal(amount_text).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    except Exception as exc:
        raise ValueError(message) from exc
    expected = Decimal(_format_token188_amount(expected_amount))
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


def _derive_return_url(notify_url: str) -> str:
    normalized_notify_url = _required_text(notify_url, "TOKEN188 回调地址不能为空")
    parts = urlsplit(normalized_notify_url)
    if not parts.scheme or not parts.netloc:
        return normalized_notify_url
    return urlunsplit((parts.scheme, parts.netloc, "/", "", ""))


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
        raise ValueError("TOKEN188 文本不能包含控制字符")
    return text


def _contains_control_character(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)
