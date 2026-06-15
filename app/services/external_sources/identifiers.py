from __future__ import annotations

import re


_EXTERNAL_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9_-]+$")


def normalize_external_identifier(value: object, field_name: str, *, allow_empty: bool) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} 必须是字符串")
    normalized = value.strip()
    if not normalized:
        if allow_empty:
            return ""
        raise ValueError(f"{field_name} 不能为空")
    if not _EXTERNAL_IDENTIFIER_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field_name} 仅支持小写字母、数字、下划线和短横线")
    return normalized


def normalize_provider_name(value: object, field_name: str) -> str:
    return normalize_external_identifier(value, field_name, allow_empty=False)
