from __future__ import annotations

from typing import Any, Type


SENSITIVE_RAW_PAYLOAD_KEYWORDS = {
    "apikey",
    "authorization",
    "authkey",
    "cardsecret",
    "cookie",
    "credential",
    "password",
    "passwd",
    "plainkey",
    "secret",
    "session",
    "storagekey",
    "token",
}


def reject_sensitive_raw_payload_keys(
    raw_payload: dict[str, Any],
    result_label: str,
    *,
    error_type: Type[Exception] = ValueError,
    message: str | None = None,
) -> None:
    if _contains_sensitive_key(raw_payload):
        raise error_type(message or f"外部发卡源返回{result_label}原始载荷包含敏感字段")


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested_value in value.items():
            if _is_sensitive_raw_payload_key(key) or _contains_sensitive_key(nested_value):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def _is_sensitive_raw_payload_key(key: Any) -> bool:
    normalized = "".join(char for char in str(key).lower() if char.isalnum())
    return any(keyword in normalized for keyword in SENSITIVE_RAW_PAYLOAD_KEYWORDS)
