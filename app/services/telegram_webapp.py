from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qsl


MAX_INIT_DATA_BYTES = 8 * 1024
MAX_INIT_DATA_FIELDS = 32
MAX_INIT_DATA_FIELD_KEY_LENGTH = 64
MAX_INIT_DATA_FIELD_VALUE_LENGTH = 4096
MAX_AUTH_DATE_FUTURE_SKEW_SECONDS = 60


class TelegramWebAppInitDataError(ValueError):
    pass


@dataclass(frozen=True)
class TelegramWebAppUser:
    id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    language_code: Optional[str] = None


def validate_telegram_webapp_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int,
    now: int | None = None,
) -> TelegramWebAppUser:
    if not isinstance(init_data, str) or not init_data:
        raise TelegramWebAppInitDataError("initData 无效")
    if len(init_data.encode("utf-8")) > MAX_INIT_DATA_BYTES:
        raise TelegramWebAppInitDataError("initData 长度超限")
    pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    if len(pairs) > MAX_INIT_DATA_FIELDS:
        raise TelegramWebAppInitDataError("initData 字段过多")
    data: dict[str, str] = {}
    for key, value in pairs:
        _validate_init_data_field(key, value)
        if key in data:
            raise TelegramWebAppInitDataError("initData 包含重复字段")
        data[key] = value
    provided_hash = data.pop("hash", None)
    if not provided_hash:
        raise TelegramWebAppInitDataError("initData 缺少 hash")
    auth_date = _parse_auth_date(data.get("auth_date"))
    current_time = int(time.time()) if now is None else now
    if auth_date > current_time + MAX_AUTH_DATE_FUTURE_SKEW_SECONDS:
        raise TelegramWebAppInitDataError("initData auth_date 来自未来")
    if auth_date + max_age_seconds < current_time:
        raise TelegramWebAppInitDataError("initData 已过期")
    data_check_string = "\n".join(f"{key}={data[key]}" for key in sorted(data))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, provided_hash):
        raise TelegramWebAppInitDataError("initData 签名无效")
    return _parse_user(data.get("user"))


def _validate_init_data_field(key: str, value: str) -> None:
    if not key or len(key) > MAX_INIT_DATA_FIELD_KEY_LENGTH:
        raise TelegramWebAppInitDataError("initData 字段无效")
    if len(value) > MAX_INIT_DATA_FIELD_VALUE_LENGTH:
        raise TelegramWebAppInitDataError("initData 字段值超限")


def _parse_auth_date(value: Optional[str]) -> int:
    try:
        auth_date = int(value or "")
    except ValueError:
        raise TelegramWebAppInitDataError("initData auth_date 无效")
    if auth_date <= 0:
        raise TelegramWebAppInitDataError("initData auth_date 无效")
    return auth_date


def _parse_user(value: Optional[str]) -> TelegramWebAppUser:
    if not value:
        raise TelegramWebAppInitDataError("initData 缺少 user")
    try:
        user = json.loads(value)
    except json.JSONDecodeError as exc:
        raise TelegramWebAppInitDataError("initData user 无效") from exc
    if not isinstance(user, dict):
        raise TelegramWebAppInitDataError("initData user 无效")
    try:
        user_id = int(user["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TelegramWebAppInitDataError("initData user.id 无效") from exc
    if isinstance(user.get("id"), bool):
        raise TelegramWebAppInitDataError("initData user.id 无效")
    if user_id <= 0:
        raise TelegramWebAppInitDataError("initData user.id 无效")
    return TelegramWebAppUser(
        id=user_id,
        username=_optional_user_text(user, "username"),
        first_name=_optional_user_text(user, "first_name"),
        language_code=_optional_user_text(user, "language_code"),
    )


def _optional_user_text(user: dict[str, object], field_name: str) -> Optional[str]:
    value = user.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TelegramWebAppInitDataError(f"initData user.{field_name} 无效")
    return value
