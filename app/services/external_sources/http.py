from __future__ import annotations

import ipaddress
import json
import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping, Optional, Protocol, Sequence
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import httpx

from app.services.external_sources.base import ExternalSourceError
from app.services.external_sources.limits import (
    MAX_EXTERNAL_HTTP_JSON_ARRAY_ITEMS,
    MAX_EXTERNAL_HTTP_JSON_DEPTH,
    MAX_EXTERNAL_HTTP_JSON_FIELDS,
    MAX_EXTERNAL_HTTP_JSON_STRING_LENGTH,
    MAX_EXTERNAL_HTTP_RESPONSE_BODY_BYTES,
)


SENSITIVE_HTTP_HEADER_KEYWORDS = {
    "apikey",
    "authorization",
    "authkey",
    "cookie",
    "credential",
    "password",
    "secret",
    "session",
    "token",
}

ALLOWED_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
DEFAULT_HTTP_TIMEOUT_SECONDS = 10.0
MAX_HTTP_TIMEOUT_SECONDS = 60.0
MAX_HTTP_PATH_SEGMENT_LENGTH = 256
MAX_HTTP_QUERY_KEY_LENGTH = 128
MAX_HTTP_QUERY_VALUE_LENGTH = 4096
UNSAFE_HTTP_HOSTS = {"localhost", "local", "internal"}
UNSAFE_HTTP_HOST_SUFFIXES = (".localhost", ".local", ".internal")
HTTP_ERROR_CATEGORY_REDIRECT = "redirect"
HTTP_ERROR_CATEGORY_CREDENTIAL = "credential"
HTTP_ERROR_CATEGORY_NOT_FOUND = "not_found"
HTTP_ERROR_CATEGORY_RATE_LIMITED = "rate_limited"
HTTP_ERROR_CATEGORY_CLIENT_ERROR = "client_error"
HTTP_ERROR_CATEGORY_UPSTREAM_ERROR = "upstream_error"
HTTP_ERROR_CATEGORY_NETWORK_ERROR = "network_error"
HTTP_ERROR_CATEGORY_PROTOCOL_ERROR = "protocol_error"
HTTP_ERROR_CATEGORY_UNKNOWN = "unknown"


class ExternalHttpError(ExternalSourceError):
    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        category: str = HTTP_ERROR_CATEGORY_UNKNOWN,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.category = category
        self.retryable = retryable


@dataclass(frozen=True)
class ExternalHttpRequest:
    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    json_payload: Optional[Any] = None
    body: Optional[str] = None
    timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        method = normalize_external_http_method(self.method)
        url = normalize_external_http_url(self.url)
        headers = normalize_external_http_headers(self.headers)
        timeout_seconds = normalize_external_http_timeout(self.timeout_seconds)
        if self.json_payload is not None and self.body is not None:
            raise ValueError("json_payload 和 body 不能同时提供")
        if self.body is not None and not isinstance(self.body, str):
            raise ValueError("body 必须是字符串")
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "url", url)
        object.__setattr__(self, "headers", headers)
        object.__setattr__(self, "timeout_seconds", timeout_seconds)

    def __repr__(self) -> str:
        return (
            "ExternalHttpRequest("
            f"method={self.method!r}, "
            f"url={redact_external_http_url(self.url)!r}, "
            f"headers={redact_external_http_headers(self.headers)!r}, "
            f"json_payload={'***' if self.json_payload is not None else None!r}, "
            f"body={'***' if self.body is not None else None!r}, "
            f"timeout_seconds={self.timeout_seconds!r}"
            ")"
        )


@dataclass(frozen=True)
class ExternalHttpResponse:
    status_code: int
    headers: Mapping[str, str] = field(default_factory=dict)
    json_payload: Optional[Any] = None
    text: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.status_code, int) or isinstance(self.status_code, bool):
            raise ValueError("status_code 必须是整数")
        if not 100 <= self.status_code <= 599:
            raise ValueError("status_code 必须是有效 HTTP 状态码")
        if self.text is not None and not isinstance(self.text, str):
            raise ValueError("text 必须是字符串")
        object.__setattr__(self, "headers", normalize_external_http_headers(self.headers))

    def __repr__(self) -> str:
        return (
            "ExternalHttpResponse("
            f"status_code={self.status_code!r}, "
            f"headers={redact_external_http_headers(self.headers)!r}, "
            f"json_payload={'***' if self.json_payload is not None else None!r}, "
            f"text={'***' if self.text is not None else None!r}"
            ")"
        )


class ExternalHttpTransport(Protocol):
    async def request(self, request: ExternalHttpRequest) -> ExternalHttpResponse:
        ...


class ExternalHttpxTransport:
    def __init__(self, client: Optional[httpx.AsyncClient] = None) -> None:
        self.client = client

    async def request(self, request: ExternalHttpRequest) -> ExternalHttpResponse:
        if not isinstance(request, ExternalHttpRequest):
            raise ValueError("request 必须是 ExternalHttpRequest")
        if self.client is not None:
            response = await self._send(self.client, request)
        else:
            async with httpx.AsyncClient(follow_redirects=False) as client:
                response = await self._send(client, request)
        return self._to_external_response(response)

    async def _send(self, client: httpx.AsyncClient, request: ExternalHttpRequest) -> httpx.Response:
        return await client.request(
            request.method,
            request.url,
            headers=dict(request.headers),
            json=request.json_payload,
            content=request.body,
            timeout=request.timeout_seconds,
            follow_redirects=False,
        )

    def _to_external_response(self, response: httpx.Response) -> ExternalHttpResponse:
        json_payload: Optional[Any] = None
        text: Optional[str] = None
        if response.content:
            if len(response.content) > MAX_EXTERNAL_HTTP_RESPONSE_BODY_BYTES:
                raise ExternalHttpError(
                    "外部发卡源 HTTP 响应体过大",
                    status_code=response.status_code,
                    category=HTTP_ERROR_CATEGORY_PROTOCOL_ERROR,
                )
            try:
                json_payload = response.json()
            except ValueError:
                text = response.text
        return ExternalHttpResponse(
            status_code=response.status_code,
            headers=dict(response.headers),
            json_payload=json_payload,
            text=text,
        )


class ExternalHttpClient:
    def __init__(self, transport: ExternalHttpTransport) -> None:
        self.transport = transport

    async def request(self, request: ExternalHttpRequest) -> ExternalHttpResponse:
        if not isinstance(request, ExternalHttpRequest):
            raise ValueError("request 必须是 ExternalHttpRequest")
        try:
            response = await self.transport.request(request)
        except ExternalHttpError:
            raise
        except Exception as exc:
            raise ExternalHttpError(
                "外部发卡源 HTTP 请求失败",
                category=HTTP_ERROR_CATEGORY_NETWORK_ERROR,
                retryable=True,
            ) from exc
        if not isinstance(response, ExternalHttpResponse):
            raise ExternalHttpError(
                "外部发卡源 HTTP 响应无效",
                category=HTTP_ERROR_CATEGORY_PROTOCOL_ERROR,
            )
        _validate_external_http_response_size(response)
        if not 200 <= response.status_code <= 299:
            raise ExternalHttpError(
                f"外部发卡源 HTTP 状态异常：{response.status_code}",
                status_code=response.status_code,
                category=categorize_external_http_status(response.status_code),
                retryable=is_external_http_status_retryable(response.status_code),
            )
        return response

    async def request_json(self, request: ExternalHttpRequest) -> Any:
        response = await self.request(request)
        if response.json_payload is None:
            raise ExternalHttpError(
                "外部发卡源 HTTP 响应不是 JSON",
                status_code=response.status_code,
                category=HTTP_ERROR_CATEGORY_PROTOCOL_ERROR,
            )
        if not isinstance(response.json_payload, (Mapping, list)):
            raise ExternalHttpError(
                "外部发卡源 HTTP JSON 顶层必须是对象或数组",
                status_code=response.status_code,
                category=HTTP_ERROR_CATEGORY_PROTOCOL_ERROR,
            )
        _validate_external_http_json_shape(response.json_payload, status_code=response.status_code)
        return response.json_payload


def normalize_external_http_method(method: str) -> str:
    if not isinstance(method, str):
        raise ValueError("HTTP method 必须是字符串")
    normalized = method.strip().upper()
    if normalized not in ALLOWED_HTTP_METHODS:
        raise ValueError("HTTP method 不支持")
    return normalized


def normalize_external_http_url(url: str) -> str:
    if not isinstance(url, str):
        raise ValueError("HTTP URL 必须是字符串")
    normalized = url.strip()
    if not normalized:
        raise ValueError("HTTP URL 不能为空")
    if _contains_control_character(normalized):
        raise ValueError("HTTP URL 不能包含控制字符")
    parts = urlsplit(normalized)
    if parts.scheme.lower() not in {"http", "https"}:
        raise ValueError("HTTP URL 只支持 http 或 https")
    if not parts.netloc:
        raise ValueError("HTTP URL 必须包含主机")
    if parts.username or parts.password:
        raise ValueError("HTTP URL 不能包含用户名或密码")
    if parts.fragment:
        raise ValueError("HTTP URL 不能包含 fragment")
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc, path, parts.query, ""))


def validate_external_http_public_base_url(url: str) -> str:
    normalized = normalize_external_http_url(url)
    parts = urlsplit(normalized)
    if parts.query:
        raise ValueError("HTTP base URL 不能包含 query")
    host = parts.hostname
    if host is None:
        raise ValueError("HTTP URL 必须包含主机")
    _validate_external_http_public_host(host)
    return normalized


def build_external_http_url(
    base_url: str,
    *,
    path_segments: Sequence[object] = (),
    query: Mapping[str, object | None] | None = None,
) -> str:
    normalized_base = normalize_external_http_url(base_url)
    parts = urlsplit(normalized_base)
    if parts.query:
        raise ValueError("HTTP base URL 不能包含 query")
    if isinstance(path_segments, (str, bytes)):
        raise ValueError("HTTP path_segments 必须是序列")
    normalized_segments = [_normalize_external_http_path_segment(segment) for segment in path_segments]
    base_path = parts.path or "/"
    if normalized_segments:
        joined_path = "/".join(
            [base_path.rstrip("/")] + [quote(segment, safe="") for segment in normalized_segments]
        )
        path = joined_path if joined_path.startswith("/") else f"/{joined_path}"
    else:
        path = base_path
    encoded_query = urlencode(_normalize_external_http_query_items(query))
    return urlunsplit((parts.scheme, parts.netloc, path or "/", encoded_query, ""))


def redact_external_http_url(url: str) -> str:
    normalized = normalize_external_http_url(url)
    parts = urlsplit(normalized)
    if not parts.query:
        return normalized
    redacted_query = urlencode([(key, "***") for key, _ in parse_qsl(parts.query, keep_blank_values=True)])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, redacted_query, ""))


def normalize_external_http_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    if headers is None:
        return {}
    if not isinstance(headers, Mapping):
        raise ValueError("HTTP headers 必须是字典")
    normalized: dict[str, str] = {}
    seen_lower_names: set[str] = set()
    for key, value in headers.items():
        if not isinstance(key, str):
            raise ValueError("HTTP header 名称必须是字符串")
        if not isinstance(value, str):
            raise ValueError("HTTP header 值必须是字符串")
        normalized_key = key.strip()
        normalized_value = value.strip()
        if not normalized_key:
            raise ValueError("HTTP header 名称不能为空")
        if not normalized_value:
            raise ValueError("HTTP header 值不能为空")
        if len(normalized_key) > 128:
            raise ValueError("HTTP header 名称长度不能超过 128")
        if len(normalized_value) > 4096:
            raise ValueError("HTTP header 值长度不能超过 4096")
        if _contains_control_character(normalized_key) or _contains_control_character(normalized_value):
            raise ValueError("HTTP header 不能包含控制字符")
        lower_name = normalized_key.lower()
        if lower_name in seen_lower_names:
            raise ValueError("HTTP header 名称重复")
        seen_lower_names.add(lower_name)
        normalized[normalized_key] = normalized_value
    return normalized


def redact_external_http_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    return {
        key: "***" if is_sensitive_http_header_name(key) else value
        for key, value in normalize_external_http_headers(headers).items()
    }


def is_sensitive_http_header_name(name: str) -> bool:
    normalized = "".join(char for char in str(name).lower() if char.isalnum())
    return any(keyword in normalized for keyword in SENSITIVE_HTTP_HEADER_KEYWORDS)


def normalize_external_http_timeout(timeout_seconds: float) -> float:
    if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool):
        raise ValueError("HTTP timeout 必须是数字")
    timeout = float(timeout_seconds)
    if not math.isfinite(timeout) or timeout <= 0 or timeout > MAX_HTTP_TIMEOUT_SECONDS:
        raise ValueError("HTTP timeout 范围为 0-60 秒")
    return timeout


def categorize_external_http_status(status_code: int) -> str:
    if 300 <= status_code <= 399:
        return HTTP_ERROR_CATEGORY_REDIRECT
    if status_code in {401, 403}:
        return HTTP_ERROR_CATEGORY_CREDENTIAL
    if status_code == 404:
        return HTTP_ERROR_CATEGORY_NOT_FOUND
    if status_code == 429:
        return HTTP_ERROR_CATEGORY_RATE_LIMITED
    if 400 <= status_code <= 499:
        return HTTP_ERROR_CATEGORY_CLIENT_ERROR
    if 500 <= status_code <= 599:
        return HTTP_ERROR_CATEGORY_UPSTREAM_ERROR
    return HTTP_ERROR_CATEGORY_UNKNOWN


def is_external_http_status_retryable(status_code: int) -> bool:
    return status_code in {408, 425, 429} or 500 <= status_code <= 599


def _validate_external_http_response_size(response: ExternalHttpResponse) -> None:
    if response.text is not None and len(response.text.encode("utf-8")) > MAX_EXTERNAL_HTTP_RESPONSE_BODY_BYTES:
        raise ExternalHttpError(
            "外部发卡源 HTTP 响应体过大",
            status_code=response.status_code,
            category=HTTP_ERROR_CATEGORY_PROTOCOL_ERROR,
        )
    if response.json_payload is None:
        return
    try:
        payload_size = len(
            json.dumps(response.json_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
    except (RecursionError, TypeError, ValueError) as exc:
        raise ExternalHttpError(
            "外部发卡源 HTTP JSON 响应不可序列化",
            status_code=response.status_code,
            category=HTTP_ERROR_CATEGORY_PROTOCOL_ERROR,
        ) from exc
    if payload_size > MAX_EXTERNAL_HTTP_RESPONSE_BODY_BYTES:
        raise ExternalHttpError(
            "外部发卡源 HTTP 响应体过大",
            status_code=response.status_code,
            category=HTTP_ERROR_CATEGORY_PROTOCOL_ERROR,
        )


def _validate_external_http_json_shape(payload: Any, *, status_code: int) -> None:
    total_fields = 0

    def visit(value: Any, *, depth: int) -> None:
        nonlocal total_fields
        if depth > MAX_EXTERNAL_HTTP_JSON_DEPTH:
            raise ExternalHttpError(
                "外部发卡源 HTTP JSON 响应嵌套过深",
                status_code=status_code,
                category=HTTP_ERROR_CATEGORY_PROTOCOL_ERROR,
            )
        if isinstance(value, Mapping):
            if len(value) > MAX_EXTERNAL_HTTP_JSON_FIELDS:
                raise ExternalHttpError(
                    "外部发卡源 HTTP JSON 对象字段过多",
                    status_code=status_code,
                    category=HTTP_ERROR_CATEGORY_PROTOCOL_ERROR,
                )
            total_fields += len(value)
            if total_fields > MAX_EXTERNAL_HTTP_JSON_FIELDS:
                raise ExternalHttpError(
                    "外部发卡源 HTTP JSON 对象字段过多",
                    status_code=status_code,
                    category=HTTP_ERROR_CATEGORY_PROTOCOL_ERROR,
                )
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ExternalHttpError(
                        "外部发卡源 HTTP JSON 对象字段名无效",
                        status_code=status_code,
                        category=HTTP_ERROR_CATEGORY_PROTOCOL_ERROR,
                    )
                if len(key) > MAX_EXTERNAL_HTTP_JSON_STRING_LENGTH:
                    raise ExternalHttpError(
                        "外部发卡源 HTTP JSON 对象字段名过长",
                        status_code=status_code,
                        category=HTTP_ERROR_CATEGORY_PROTOCOL_ERROR,
                    )
                visit(item, depth=depth + 1)
            return
        if isinstance(value, list):
            if len(value) > MAX_EXTERNAL_HTTP_JSON_ARRAY_ITEMS:
                raise ExternalHttpError(
                    "外部发卡源 HTTP JSON 数组过长",
                    status_code=status_code,
                    category=HTTP_ERROR_CATEGORY_PROTOCOL_ERROR,
                )
            for item in value:
                visit(item, depth=depth + 1)
            return
        if isinstance(value, str) and len(value) > MAX_EXTERNAL_HTTP_JSON_STRING_LENGTH:
            raise ExternalHttpError(
                "外部发卡源 HTTP JSON 字符串过长",
                status_code=status_code,
                category=HTTP_ERROR_CATEGORY_PROTOCOL_ERROR,
            )

    visit(payload, depth=1)


def _normalize_external_http_path_segment(segment: object) -> str:
    if isinstance(segment, bool) or not isinstance(segment, (str, int, Decimal)):
        raise ValueError("HTTP path segment 必须是字符串或数字")
    if isinstance(segment, Decimal):
        if not segment.is_finite():
            raise ValueError("HTTP path segment 数字必须是有限值")
        value = str(segment)
    else:
        value = str(segment)
    normalized = value.strip()
    if not normalized:
        raise ValueError("HTTP path segment 不能为空")
    if len(normalized) > MAX_HTTP_PATH_SEGMENT_LENGTH:
        raise ValueError("HTTP path segment 长度不能超过 256")
    if _contains_control_character(normalized):
        raise ValueError("HTTP path segment 不能包含控制字符")
    if normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
        raise ValueError("HTTP path segment 不能包含路径分隔符或上级目录")
    return normalized


def _normalize_external_http_query_items(query: Mapping[str, object | None] | None) -> list[tuple[str, str]]:
    if query is None:
        return []
    if not isinstance(query, Mapping):
        raise ValueError("HTTP query 必须是字典")
    normalized: list[tuple[str, str]] = []
    seen_keys: set[str] = set()
    for key, value in query.items():
        if not isinstance(key, str):
            raise ValueError("HTTP query key 必须是字符串")
        normalized_key = key.strip()
        if not normalized_key:
            raise ValueError("HTTP query key 不能为空")
        if len(normalized_key) > MAX_HTTP_QUERY_KEY_LENGTH:
            raise ValueError("HTTP query key 长度不能超过 128")
        if _contains_control_character(normalized_key):
            raise ValueError("HTTP query key 不能包含控制字符")
        if normalized_key in seen_keys:
            raise ValueError("HTTP query key 重复")
        seen_keys.add(normalized_key)
        if value is None:
            continue
        normalized.append((normalized_key, _normalize_external_http_query_value(value)))
    return normalized


def _normalize_external_http_query_value(value: object) -> str:
    if isinstance(value, bool):
        normalized = "true" if value else "false"
    elif isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("HTTP query value 数字必须是有限值")
        normalized = str(value)
    elif isinstance(value, int):
        normalized = str(value)
    elif isinstance(value, str):
        normalized = value.strip()
    else:
        raise ValueError("HTTP query value 必须是字符串、数字、布尔值或 None")
    if len(normalized) > MAX_HTTP_QUERY_VALUE_LENGTH:
        raise ValueError("HTTP query value 长度不能超过 4096")
    if _contains_control_character(normalized):
        raise ValueError("HTTP query value 不能包含控制字符")
    return normalized


def _validate_external_http_public_host(host: str) -> None:
    normalized = host.strip().strip(".").lower()
    if not normalized:
        raise ValueError("HTTP URL 主机不能为空")
    if _contains_control_character(normalized) or "%" in normalized:
        raise ValueError("HTTP URL 主机无效")
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        _validate_external_http_public_domain(normalized)
        return
    if not address.is_global:
        raise ValueError("HTTP URL 主机不能指向内网、环回、链路本地或保留地址")


def _validate_external_http_public_domain(host: str) -> None:
    if host in UNSAFE_HTTP_HOSTS or any(host.endswith(suffix) for suffix in UNSAFE_HTTP_HOST_SUFFIXES):
        raise ValueError("HTTP URL 主机不能使用本机或内部域名")
    if host.isdigit():
        raise ValueError("HTTP URL 主机无效")
    labels = host.split(".")
    if any(not label for label in labels):
        raise ValueError("HTTP URL 主机无效")
    for label in labels:
        if len(label) > 63:
            raise ValueError("HTTP URL 主机 label 过长")
        if label.startswith("-") or label.endswith("-"):
            raise ValueError("HTTP URL 主机 label 无效")
        if not all(char.isalnum() or char == "-" for char in label):
            raise ValueError("HTTP URL 主机只支持 ASCII 域名或 IP")


def _contains_control_character(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)
