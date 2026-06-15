from __future__ import annotations

import asyncio
import unittest

try:
    from app.services.api_security import (
        ApiRateLimitError,
        ApiIpAccessError,
        ApiSignatureError,
        FixedWindowRateLimiter,
        RedisFixedWindowRateLimiter,
        body_hash,
        hit_rate_limit,
        is_ip_allowed,
        require_ip_allowed,
        resolve_client_ip,
        sign_request,
        signature_payload,
        verify_request_signature,
    )
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过 API 安全测试：{exc.name}") from exc


class ApiSignatureTest(unittest.TestCase):
    def test_signature_is_stable_for_canonical_payload(self) -> None:
        payload = signature_payload(
            "post",
            "/api/v1/tenant/products",
            "page=1",
            body_hash(b'{"name":"demo"}'),
            "1770000000",
        )

        self.assertEqual(
            "POST\n/api/v1/tenant/products\npage=1\n"
            "d7d234f759ec34fd6298b7e32318614760070aaef9f4e92ced928324b49a0602\n1770000000",
            payload,
        )

    def test_verify_request_signature_accepts_valid_signature(self) -> None:
        signature = sign_request(
            "fk_live_secret",
            method="GET",
            path="/api/v1/tenant/orders",
            query_string="limit=10",
            body=b"",
            timestamp="1770000000",
        )

        verify_request_signature(
            "fk_live_secret",
            method="GET",
            path="/api/v1/tenant/orders",
            query_string="limit=10",
            body=b"",
            timestamp="1770000000",
            signature=signature,
            max_skew_seconds=300,
            now=1770000100,
        )

    def test_verify_request_signature_rejects_replay_and_tampering(self) -> None:
        signature = sign_request(
            "fk_live_secret",
            method="GET",
            path="/api/v1/tenant/orders",
            query_string="limit=10",
            body=b"",
            timestamp="1770000000",
        )

        with self.assertRaises(ApiSignatureError):
            verify_request_signature(
                "fk_live_secret",
                method="GET",
                path="/api/v1/tenant/orders",
                query_string="limit=10",
                body=b"",
                timestamp="1770000000",
                signature=signature,
                max_skew_seconds=300,
                now=1770001000,
            )
        with self.assertRaises(ApiSignatureError):
            verify_request_signature(
                "fk_live_secret",
                method="GET",
                path="/api/v1/tenant/orders",
                query_string="limit=20",
                body=b"",
                timestamp="1770000000",
                signature=signature,
                max_skew_seconds=300,
                now=1770000000,
            )


class FixedWindowRateLimiterTest(unittest.TestCase):
    def test_limiter_rejects_after_limit_and_resets_next_window(self) -> None:
        limiter = FixedWindowRateLimiter(limit=2, window_seconds=60)

        limiter.hit("tenant-api:1", now=120)
        limiter.hit("tenant-api:1", now=130)
        with self.assertRaises(ApiRateLimitError):
            limiter.hit("tenant-api:1", now=140)

        limiter.hit("tenant-api:1", now=180)

    def test_redis_limiter_rejects_after_limit_and_sets_ttl_once(self) -> None:
        redis = FakeRedis()
        limiter = RedisFixedWindowRateLimiter(limit=2, window_seconds=60, key_prefix="test:rate")

        asyncio.run(limiter.hit(redis, "tenant-api:1", now=120))
        asyncio.run(limiter.hit(redis, "tenant-api:1", now=130))
        with self.assertRaises(ApiRateLimitError):
            asyncio.run(limiter.hit(redis, "tenant-api:1", now=140))

        self.assertEqual({"test:rate:tenant-api:1:2": 120}, redis.expirations)

    def test_hit_rate_limit_falls_back_to_local_when_redis_backend_fails(self) -> None:
        redis = FailingRedis()
        redis_limiter = RedisFixedWindowRateLimiter(limit=1, window_seconds=60, key_prefix="test:rate")
        local_limiter = FixedWindowRateLimiter(limit=1, window_seconds=60)

        asyncio.run(
            hit_rate_limit(
                redis_client=redis,
                redis_limiter=redis_limiter,
                local_limiter=local_limiter,
                key="tenant-api:1",
            )
        )
        with self.assertRaises(ApiRateLimitError):
            asyncio.run(
                hit_rate_limit(
                    redis_client=redis,
                    redis_limiter=redis_limiter,
                    local_limiter=local_limiter,
                    key="tenant-api:1",
                )
            )


class ApiIpAccessTest(unittest.TestCase):
    def test_empty_allowlist_allows_any_client_ip(self) -> None:
        self.assertTrue(is_ip_allowed("203.0.113.10", []))

    def test_ip_allowlist_supports_exact_ip_and_cidr(self) -> None:
        self.assertTrue(is_ip_allowed("203.0.113.10", ["203.0.113.10"]))
        self.assertTrue(is_ip_allowed("203.0.113.10", ["203.0.113.0/24"]))
        self.assertFalse(is_ip_allowed("198.51.100.10", ["203.0.113.0/24"]))

    def test_ip_allowlist_rejects_invalid_client_ip(self) -> None:
        self.assertFalse(is_ip_allowed("not-an-ip", ["0.0.0.0/0"]))

    def test_ip_allowlist_skips_invalid_rules_but_does_not_allow_when_all_rules_invalid(self) -> None:
        self.assertTrue(is_ip_allowed("203.0.113.10", ["bad-rule", "203.0.113.0/24"]))
        self.assertFalse(is_ip_allowed("203.0.113.10", ["bad-rule"]))

    def test_resolve_client_ip_ignores_forwarded_for_without_trusted_proxy(self) -> None:
        client_ip = resolve_client_ip("10.0.0.2", "203.0.113.10", [])

        self.assertEqual("10.0.0.2", client_ip)

    def test_resolve_client_ip_uses_forwarded_for_from_trusted_proxy(self) -> None:
        client_ip = resolve_client_ip("10.0.0.2", "203.0.113.10, 198.51.100.20", ["10.0.0.0/24"])

        self.assertEqual("203.0.113.10", client_ip)

    def test_resolve_client_ip_skips_invalid_trusted_proxy_rules(self) -> None:
        client_ip = resolve_client_ip("10.0.0.2", "203.0.113.10", ["bad-rule", "10.0.0.0/24"])

        self.assertEqual("203.0.113.10", client_ip)

    def test_require_ip_allowed_rejects_disallowed_ip(self) -> None:
        with self.assertRaises(ApiIpAccessError):
            require_ip_allowed("198.51.100.10", ["203.0.113.0/24"])


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.expirations: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key: str, seconds: int) -> None:
        self.expirations[key] = seconds


class FailingRedis:
    async def incr(self, key: str) -> int:
        raise RuntimeError("redis unavailable")


if __name__ == "__main__":
    unittest.main()
