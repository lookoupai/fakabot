from __future__ import annotations

import unittest
import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

try:
    from app.bots.routers.tenant import (
        _format_api_keys,
        _parse_create_api_key_args,
        _send_product_manage,
    )
    from app.services.api_keys import TenantApiKeySummary
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过租户 Bot API Key 契约测试：{exc.name}") from exc


class _FakeMessage:
    def __init__(self) -> None:
        self.answers: list[str] = []

    async def answer(self, text: str, **_: object) -> None:
        self.answers.append(text)


class TenantBotApiKeyContractTest(unittest.TestCase):
    def test_parse_create_api_key_args_uses_default_name_and_scope_for_blank_args(self) -> None:
        name, scopes, ip_allowlist = _parse_create_api_key_args("")

        self.assertEqual("default", name)
        self.assertIsNone(scopes)
        self.assertIsNone(ip_allowlist)

    def test_parse_create_api_key_args_keeps_default_scope(self) -> None:
        name, scopes, ip_allowlist = _parse_create_api_key_args("worker")

        self.assertEqual("worker", name)
        self.assertIsNone(scopes)
        self.assertIsNone(ip_allowlist)

    def test_parse_create_api_key_args_accepts_explicit_scopes(self) -> None:
        name, scopes, ip_allowlist = _parse_create_api_key_args("worker | orders:read, payments:read, products:read")

        self.assertEqual("worker", name)
        self.assertEqual(["orders:read", "payments:read", "products:read"], scopes)
        self.assertIsNone(ip_allowlist)

    def test_parse_create_api_key_args_accepts_finance_scopes(self) -> None:
        name, scopes, ip_allowlist = _parse_create_api_key_args("finance-worker | finance:write, finance:read")

        self.assertEqual("finance-worker", name)
        self.assertEqual(["finance:read", "finance:write"], scopes)
        self.assertIsNone(ip_allowlist)

    def test_parse_create_api_key_args_accepts_ip_allowlist(self) -> None:
        name, scopes, ip_allowlist = _parse_create_api_key_args(
            "worker | orders:read | 203.0.113.0/24, 198.51.100.10"
        )

        self.assertEqual("worker", name)
        self.assertEqual(["orders:read"], scopes)
        self.assertEqual(["203.0.113.0/24", "198.51.100.10"], ip_allowlist)

    def test_parse_create_api_key_args_rejects_unsupported_scopes(self) -> None:
        with self.assertRaisesRegex(ValueError, "scope 不支持"):
            _parse_create_api_key_args("worker | orders:write")

    def test_parse_create_api_key_args_rejects_wildcard_mixed_with_other_scopes(self) -> None:
        with self.assertRaisesRegex(ValueError, "通配 scope"):
            _parse_create_api_key_args("worker | tenant_admin:*, orders:read")

    def test_parse_create_api_key_args_rejects_invalid_ip_allowlist(self) -> None:
        with self.assertRaisesRegex(ValueError, "IP 白名单"):
            _parse_create_api_key_args("worker | orders:read | not-an-ip")

    def test_format_api_keys_empty_state_mentions_full_create_syntax(self) -> None:
        payload = _format_api_keys([])

        self.assertIn("暂无 API Key", payload)
        self.assertIn("/create_api_key 名称 | scope1,scope2 | IP或CIDR", payload)

    def test_format_api_keys_shows_scopes_without_plain_key(self) -> None:
        payload = _format_api_keys(
            [
                TenantApiKeySummary(
                    api_key_id=7,
                    name="worker",
                    key_prefix="fk_live_abc",
                    status="active",
                    scopes=["finance:read", "finance:write", "orders:read"],
                    ip_allowlist=["203.0.113.0/24"],
                    created_at=datetime(2026, 6, 7, tzinfo=timezone.utc),
                    last_used_at=None,
                )
            ]
        )

        self.assertIn("权限：finance:read, finance:write, orders:read", payload)
        self.assertIn("IP白名单：203.0.113.0/24", payload)
        self.assertIn("撤销：/revoke_api_key 7", payload)
        self.assertIn("/create_api_key 名称 | scope1,scope2 | IP或CIDR", payload)
        self.assertNotIn("plain_key", payload)

    def test_format_api_keys_escapes_display_fields(self) -> None:
        payload = _format_api_keys(
            [
                TenantApiKeySummary(
                    api_key_id=8,
                    name="<worker>",
                    key_prefix="fk_live_<abc>",
                    status="active",
                    scopes=["tenant_admin:*"],
                    ip_allowlist=[],
                    created_at=datetime(2026, 6, 7, tzinfo=timezone.utc),
                    last_used_at=datetime(2026, 6, 8, tzinfo=timezone.utc),
                )
            ]
        )

        self.assertIn("&lt;worker&gt;", payload)
        self.assertIn("fk_live_&lt;abc&gt;", payload)
        self.assertIn("IP白名单：不限制", payload)
        self.assertNotIn("<worker>", payload)
        self.assertNotIn("fk_live_<abc>", payload)

    def test_product_management_prompt_mentions_api_key_create_and_revoke_syntax(self) -> None:
        async def noop_send_product_list(*_: object, **__: object) -> None:
            return None

        message = _FakeMessage()
        with patch("app.bots.routers.tenant._send_product_list", noop_send_product_list):
            asyncio.run(_send_product_manage(message, object(), object()))

        self.assertTrue(message.answers)
        prompt = message.answers[0]
        self.assertIn("API Key：/api_keys [数量]", prompt)
        self.assertIn("创建 API Key：/create_api_key 名称 | scope1,scope2 | IP或CIDR", prompt)
        self.assertIn("撤销 API Key：/revoke_api_key KeyID", prompt)


if __name__ == "__main__":
    unittest.main()
