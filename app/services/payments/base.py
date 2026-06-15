from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional, Protocol


@dataclass
class PaymentOrderRequest:
    out_trade_no: str
    amount: Decimal
    currency: str
    notify_url: str


@dataclass
class PaymentCreateResult:
    provider: str
    out_trade_no: str
    provider_trade_no: Optional[str]
    payment_url: Optional[str]
    raw_response: Dict[str, Any]


@dataclass
class PaymentCallbackResult:
    provider: str
    out_trade_no: str
    provider_trade_no: Optional[str]
    paid: bool
    payload_hash: str
    raw_payload: Dict[str, Any]


@dataclass
class PaymentQueryResult:
    provider: str
    provider_trade_no: str
    paid: bool
    expired: bool
    status: str
    raw_response: Dict[str, Any]


class PaymentProvider(Protocol):
    provider: str

    async def create_order(self, request: PaymentOrderRequest) -> PaymentCreateResult:
        ...

    def verify_callback(self, payload: Dict[str, Any]) -> PaymentCallbackResult:
        ...

    async def query_order(self, provider_trade_no: str) -> PaymentQueryResult:
        ...
