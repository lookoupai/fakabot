from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from math import isfinite
from typing import Any


SENSITIVE_PAYMENT_PAYLOAD_KEYWORDS = {
    "apikey",
    "authorization",
    "authkey",
    "cardsecret",
    "cookie",
    "credential",
    "password",
    "plainkey",
    "secret",
    "session",
    "storagekey",
    "token",
}

SENSITIVE_PAYMENT_PAYLOAD_EXACT_KEYS = {"key"}
MAX_PAYMENT_PAYLOAD_DEPTH = 6
MAX_PAYMENT_PAYLOAD_SEQUENCE_ITEMS = 100
REDACTED_PAYMENT_PAYLOAD_VALUE = "***"


def sanitize_payment_callback_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    safe_payload = _sanitize_mapping(payload, depth=0)
    json.dumps(safe_payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return safe_payload


def _sanitize_mapping(payload: Mapping[Any, Any], *, depth: int) -> dict[str, Any]:
    if depth >= MAX_PAYMENT_PAYLOAD_DEPTH:
        return {}
    safe_payload: dict[str, Any] = {}
    for key, value in payload.items():
        key_text = str(key)
        if _is_sensitive_payment_payload_key(key_text):
            safe_payload[key_text] = REDACTED_PAYMENT_PAYLOAD_VALUE
            continue
        safe_payload[key_text] = _sanitize_value(value, depth=depth + 1)
    return safe_payload


def _sanitize_value(value: Any, *, depth: int) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if isfinite(value) else str(value)
    if isinstance(value, Decimal):
        return str(value)
    if depth >= MAX_PAYMENT_PAYLOAD_DEPTH:
        return str(value) if isinstance(value, (str, int, float, bool, Decimal)) else type(value).__name__
    if isinstance(value, Mapping):
        return _sanitize_mapping(value, depth=depth)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            _sanitize_value(item, depth=depth + 1)
            for item in list(value)[:MAX_PAYMENT_PAYLOAD_SEQUENCE_ITEMS]
        ]
    return type(value).__name__


def _is_sensitive_payment_payload_key(key: str) -> bool:
    normalized = key.strip().lower()
    if normalized in SENSITIVE_PAYMENT_PAYLOAD_EXACT_KEYS:
        return True
    compact = "".join(char for char in normalized if char.isalnum())
    return any(keyword in compact for keyword in SENSITIVE_PAYMENT_PAYLOAD_KEYWORDS)
