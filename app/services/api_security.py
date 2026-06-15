from __future__ import annotations

import hashlib
import hmac
import ipaddress
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional


class ApiSignatureError(ValueError):
    pass


class ApiRateLimitError(ValueError):
    pass


class ApiRateLimitBackendError(RuntimeError):
    pass


class ApiIpAccessError(ValueError):
    pass


def body_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def signature_payload(method: str, path: str, query_string: str, request_body_hash: str, timestamp: str) -> str:
    return "\n".join(
        [
            method.upper(),
            path,
            query_string,
            request_body_hash,
            timestamp,
        ]
    )


def sign_request(
    api_key: str,
    *,
    method: str,
    path: str,
    query_string: str,
    body: bytes,
    timestamp: str,
) -> str:
    payload = signature_payload(method, path, query_string, body_hash(body), timestamp)
    return hmac.new(api_key.encode(), payload.encode(), hashlib.sha256).hexdigest()


def verify_request_signature(
    api_key: str,
    *,
    method: str,
    path: str,
    query_string: str,
    body: bytes,
    timestamp: str,
    signature: str,
    max_skew_seconds: int,
    now: int | None = None,
) -> None:
    try:
        request_time = int(timestamp)
    except (TypeError, ValueError):
        raise ApiSignatureError("签名时间戳必须是 Unix 秒级时间")
    current_time = int(time.time()) if now is None else now
    if abs(current_time - request_time) > max_skew_seconds:
        raise ApiSignatureError("签名时间戳超出允许偏差")
    expected = sign_request(
        api_key,
        method=method,
        path=path,
        query_string=query_string,
        body=body,
        timestamp=timestamp,
    )
    if not hmac.compare_digest(expected, signature):
        raise ApiSignatureError("请求签名无效")


def resolve_client_ip(
    direct_client_host: Optional[str],
    forwarded_for: Optional[str],
    trusted_proxy_ips: Iterable[str],
) -> str:
    direct_host = (direct_client_host or "unknown").strip()
    if not forwarded_for or not _ip_matches_rules(direct_host, trusted_proxy_ips):
        return direct_host
    forwarded_host = forwarded_for.split(",", 1)[0].strip()
    return forwarded_host or direct_host


def require_ip_allowed(client_ip: str, allowlist: Iterable[str], resource_name: str = "API") -> None:
    if not is_ip_allowed(client_ip, allowlist):
        raise ApiIpAccessError(f"当前 IP 不允许访问 {resource_name}")


def is_ip_allowed(client_ip: str, allowlist: Iterable[str]) -> bool:
    rules = [rule.strip() for rule in allowlist if rule and rule.strip()]
    if not rules:
        return True
    return _ip_matches_rules(client_ip, rules)


def _ip_matches_rules(client_ip: str, rules: Iterable[str]) -> bool:
    normalized_rules = [rule.strip() for rule in rules if rule and rule.strip()]
    if not normalized_rules:
        return False
    try:
        parsed_ip = ipaddress.ip_address(client_ip.strip())
    except ValueError:
        return False
    for rule in normalized_rules:
        try:
            if parsed_ip in ipaddress.ip_network(rule, strict=False):
                return True
        except ValueError:
            continue
    return False


@dataclass
class FixedWindowRateLimiter:
    limit: int
    window_seconds: int = 60
    _counters: Dict[str, tuple[int, int]] = field(default_factory=dict)

    def hit(self, key: str, now: int | None = None) -> None:
        if self.limit <= 0:
            return
        current_time = int(time.time()) if now is None else now
        window = current_time // self.window_seconds
        count, stored_window = self._counters.get(key, (0, window))
        if stored_window != window:
            count = 0
            stored_window = window
        count += 1
        self._counters[key] = (count, stored_window)
        if count > self.limit:
            raise ApiRateLimitError("请求过于频繁，请稍后再试")


@dataclass
class RedisFixedWindowRateLimiter:
    limit: int
    window_seconds: int = 60
    key_prefix: str = "fakabot:rate"

    async def hit(self, redis_client: Any, key: str, now: int | None = None) -> None:
        if self.limit <= 0:
            return
        current_time = int(time.time()) if now is None else now
        window = current_time // self.window_seconds
        redis_key = f"{self.key_prefix}:{key}:{window}"
        try:
            count = int(await redis_client.incr(redis_key))
            if count == 1:
                await redis_client.expire(redis_key, self.window_seconds * 2)
        except Exception as exc:
            raise ApiRateLimitBackendError("限流服务不可用") from exc
        if count > self.limit:
            raise ApiRateLimitError("请求过于频繁，请稍后再试")


async def hit_rate_limit(
    *,
    redis_client: Any,
    redis_limiter: RedisFixedWindowRateLimiter,
    local_limiter: FixedWindowRateLimiter,
    key: str,
) -> None:
    if redis_client is None:
        local_limiter.hit(key)
        return
    try:
        await redis_limiter.hit(redis_client, key)
    except ApiRateLimitBackendError:
        local_limiter.hit(key)
