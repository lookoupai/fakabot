from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional

import httpx

from app.services.payments.base import PaymentCallbackResult, PaymentCreateResult, PaymentOrderRequest, PaymentQueryResult
from app.services.payments.safety import sanitize_payment_callback_payload


@dataclass
class EpusdtGmpayConfig:
    base_url: str
    pid: str
    secret_key: str
    token: str = "USDT"
    network: str = "TRC20"
    timeout_seconds: float = 10.0


class EpusdtGmpayProvider:
    provider = "epusdt_gmpay"

    def __init__(self, config: EpusdtGmpayConfig) -> None:
        self._config = config

    async def create_order(self, request: PaymentOrderRequest) -> PaymentCreateResult:
        payload: Dict[str, Any] = {
            "pid": self._config.pid,
            "order_id": request.out_trade_no,
            "currency": request.currency,
            "token": self._config.token,
            "network": self._config.network,
            "amount": _format_decimal(request.amount),
            "notify_url": request.notify_url,
        }
        payload["signature"] = sign_payload(payload, self._config.secret_key)
        url = f"{self._config.base_url.rstrip('/')}/payments/gmpay/v1/order/create-transaction"

        async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        response_data = _response_data(data)
        return PaymentCreateResult(
            provider=self.provider,
            out_trade_no=request.out_trade_no,
            provider_trade_no=_optional_str(
                response_data.get("trade_id") or response_data.get("trade_no") or response_data.get("transaction_id")
            ),
            payment_url=_optional_str(response_data.get("payment_url")),
            raw_response=data,
        )

    def verify_callback(self, payload: Dict[str, Any]) -> PaymentCallbackResult:
        received_signature = str(payload.get("signature") or "")
        expected_signature = sign_payload(payload, self._config.secret_key)
        if not received_signature or received_signature.lower() != expected_signature:
            raise ValueError("epusdt 回调签名无效")

        status = str(payload.get("status") or payload.get("trade_status") or "").lower()
        paid = status in {"2", "paid", "success", "completed", "confirmed"}
        out_trade_no = _optional_str(payload.get("order_id") or payload.get("out_trade_no"))
        if not out_trade_no:
            raise ValueError("epusdt 回调缺少订单号")

        return PaymentCallbackResult(
            provider=self.provider,
            out_trade_no=out_trade_no,
            provider_trade_no=_optional_str(
                payload.get("trade_id") or payload.get("trade_no") or payload.get("transaction_id")
            ),
            paid=paid,
            payload_hash=payload_hash(payload),
            raw_payload=sanitize_payment_callback_payload(payload),
        )

    async def query_order(self, provider_trade_no: str) -> PaymentQueryResult:
        url = f"{self._config.base_url.rstrip('/')}/pay/check-status/{provider_trade_no}"
        async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

        response_data = _response_data(data)
        status = str(response_data.get("status") or "")
        return PaymentQueryResult(
            provider=self.provider,
            provider_trade_no=provider_trade_no,
            paid=status == "2",
            expired=status == "3",
            status=status,
            raw_response=data,
        )


def sign_payload(payload: Dict[str, Any], secret_key: str) -> str:
    filtered_items = [
        (str(key), str(value))
        for key, value in payload.items()
        if key != "signature" and value is not None and str(value) != ""
    ]
    signing_text = "&".join(f"{key}={value}" for key, value in sorted(filtered_items, key=lambda item: item[0]))
    signing_text = f"{signing_text}{secret_key}"
    return hashlib.md5(signing_text.encode()).hexdigest()


def payload_hash(payload: Dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _format_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _response_data(payload: Dict[str, Any]) -> Dict[str, Any]:
    nested = payload.get("data")
    return nested if isinstance(nested, dict) else payload
