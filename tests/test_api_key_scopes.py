from __future__ import annotations

import unittest

try:
    from app.services.api_keys import ApiKeyService
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过 API Key scope 测试：{exc.name}") from exc


class ApiKeyScopeTest(unittest.TestCase):
    def test_default_scope_is_tenant_admin_wildcard(self) -> None:
        self.assertEqual(["tenant_admin:*"], ApiKeyService.normalize_scopes(None))
        self.assertEqual(["tenant_admin:*"], ApiKeyService.normalize_scopes([]))

    def test_normalize_scopes_deduplicates_and_sorts(self) -> None:
        scopes = ApiKeyService.normalize_scopes(
            [
                "orders:read",
                " external_sources:write ",
                " inventory:write ",
                " audit_logs:read ",
                "payments:read",
                "finance:write",
                "finance:read",
                "subscriptions:read",
                "risk:read",
                "reports:read",
                "reports:write",
                "orders:read",
                "subscriptions:write",
                "supply:read",
                "supply:write",
            ]
        )

        self.assertEqual(
            [
                "audit_logs:read",
                "external_sources:write",
                "finance:read",
                "finance:write",
                "inventory:write",
                "orders:read",
                "payments:read",
                "reports:read",
                "reports:write",
                "risk:read",
                "subscriptions:read",
                "subscriptions:write",
                "supply:read",
                "supply:write",
            ],
            scopes,
        )

    def test_rejects_unsupported_scope_and_mixed_wildcard(self) -> None:
        with self.assertRaises(ValueError):
            ApiKeyService.normalize_scopes(["orders:write"])
        with self.assertRaises(ValueError):
            ApiKeyService.normalize_scopes(["tenant_admin:*", "orders:read"])

    def test_has_scope_allows_wildcard_and_exact_match_only(self) -> None:
        self.assertTrue(ApiKeyService.has_scope(["tenant_admin:*"], "products:write"))
        self.assertTrue(ApiKeyService.has_scope(["external_sources:read"], "external_sources:read"))
        self.assertTrue(ApiKeyService.has_scope(["products:read"], "products:read"))
        self.assertFalse(ApiKeyService.has_scope(["products:read"], "products:write"))
        self.assertTrue(ApiKeyService.has_scope(["inventory:read"], "inventory:read"))
        self.assertTrue(ApiKeyService.has_scope(["payments:read"], "payments:read"))
        self.assertFalse(ApiKeyService.has_scope(["payments:read"], "payments:write"))
        self.assertTrue(ApiKeyService.has_scope(["finance:read"], "finance:read"))
        self.assertTrue(ApiKeyService.has_scope(["finance:write"], "finance:write"))
        self.assertFalse(ApiKeyService.has_scope(["finance:read"], "finance:write"))
        self.assertFalse(ApiKeyService.has_scope(["finance:write"], "finance:read"))
        self.assertTrue(ApiKeyService.has_scope(["audit_logs:read"], "audit_logs:read"))
        self.assertFalse(ApiKeyService.has_scope(["orders:read"], "audit_logs:read"))
        self.assertTrue(ApiKeyService.has_scope(["risk:read"], "risk:read"))
        self.assertFalse(ApiKeyService.has_scope(["orders:read"], "risk:read"))
        self.assertTrue(ApiKeyService.has_scope(["reports:read"], "reports:read"))
        self.assertTrue(ApiKeyService.has_scope(["reports:write"], "reports:write"))
        self.assertFalse(ApiKeyService.has_scope(["orders:read"], "reports:read"))
        self.assertFalse(ApiKeyService.has_scope(["reports:read"], "reports:write"))
        self.assertTrue(ApiKeyService.has_scope(["subscriptions:read"], "subscriptions:read"))
        self.assertFalse(ApiKeyService.has_scope(["orders:read"], "subscriptions:read"))
        self.assertTrue(ApiKeyService.has_scope(["subscriptions:write"], "subscriptions:write"))
        self.assertFalse(ApiKeyService.has_scope(["subscriptions:read"], "subscriptions:write"))
        self.assertTrue(ApiKeyService.has_scope(["supply:read"], "supply:read"))
        self.assertTrue(ApiKeyService.has_scope(["supply:write"], "supply:write"))
        self.assertFalse(ApiKeyService.has_scope(["products:read"], "supply:read"))
        self.assertFalse(ApiKeyService.has_scope(["supply:read"], "supply:write"))

    def test_low_privilege_key_cannot_issue_broader_scopes(self) -> None:
        self.assertTrue(ApiKeyService.can_issue_scopes(["products:read", "api_keys:write"], ["products:read"]))
        self.assertFalse(ApiKeyService.can_issue_scopes(["products:read", "api_keys:write"], ["products:write"]))
        self.assertFalse(ApiKeyService.can_issue_scopes(["products:read", "api_keys:write"], ["external_sources:write"]))
        self.assertFalse(ApiKeyService.can_issue_scopes(["products:read", "api_keys:write"], ["inventory:write"]))
        self.assertFalse(ApiKeyService.can_issue_scopes(["products:read", "api_keys:write"], ["payments:write"]))
        self.assertFalse(ApiKeyService.can_issue_scopes(["products:read", "api_keys:write"], ["finance:write"]))
        self.assertFalse(ApiKeyService.can_issue_scopes(["products:read", "api_keys:write"], ["audit_logs:read"]))
        self.assertTrue(ApiKeyService.can_issue_scopes(["audit_logs:read", "api_keys:write"], ["audit_logs:read"]))
        self.assertFalse(ApiKeyService.can_issue_scopes(["products:read", "api_keys:write"], ["risk:read"]))
        self.assertTrue(ApiKeyService.can_issue_scopes(["risk:read", "api_keys:write"], ["risk:read"]))
        self.assertFalse(ApiKeyService.can_issue_scopes(["products:read", "api_keys:write"], ["reports:read"]))
        self.assertTrue(ApiKeyService.can_issue_scopes(["reports:read", "api_keys:write"], ["reports:read"]))
        self.assertFalse(ApiKeyService.can_issue_scopes(["reports:read", "api_keys:write"], ["reports:write"]))
        self.assertTrue(ApiKeyService.can_issue_scopes(["reports:write", "api_keys:write"], ["reports:write"]))
        self.assertFalse(ApiKeyService.can_issue_scopes(["products:read", "api_keys:write"], ["subscriptions:read"]))
        self.assertTrue(
            ApiKeyService.can_issue_scopes(["subscriptions:read", "api_keys:write"], ["subscriptions:read"])
        )
        self.assertFalse(
            ApiKeyService.can_issue_scopes(["subscriptions:read", "api_keys:write"], ["subscriptions:write"])
        )
        self.assertTrue(
            ApiKeyService.can_issue_scopes(["subscriptions:write", "api_keys:write"], ["subscriptions:write"])
        )
        self.assertFalse(ApiKeyService.can_issue_scopes(["products:read", "api_keys:write"], ["supply:read"]))
        self.assertTrue(ApiKeyService.can_issue_scopes(["supply:read", "api_keys:write"], ["supply:read"]))
        self.assertFalse(ApiKeyService.can_issue_scopes(["supply:read", "api_keys:write"], ["supply:write"]))
        self.assertTrue(ApiKeyService.can_issue_scopes(["supply:write", "api_keys:write"], ["supply:write"]))
        self.assertTrue(ApiKeyService.can_issue_scopes(["payments:read", "payments:write"], ["payments:read"]))
        self.assertTrue(ApiKeyService.can_issue_scopes(["finance:read", "finance:write"], ["finance:read"]))
        self.assertFalse(ApiKeyService.can_issue_scopes(["finance:read"], ["finance:write"]))
        self.assertFalse(ApiKeyService.can_issue_scopes(["products:read", "api_keys:write"], ["tenant_admin:*"]))
        self.assertTrue(ApiKeyService.can_issue_scopes(["tenant_admin:*"], ["tenant_admin:*"]))

    def test_normalize_ip_allowlist_deduplicates_and_validates_rules(self) -> None:
        self.assertEqual(
            ["203.0.113.10", "198.51.100.0/24"],
            ApiKeyService.normalize_ip_allowlist(
                ["203.0.113.10", " 198.51.100.0/24 ", "203.0.113.10", ""]
            ),
        )
        with self.assertRaises(ValueError):
            ApiKeyService.normalize_ip_allowlist(["not-an-ip"])

    def test_restricted_key_can_only_issue_subset_ip_allowlist(self) -> None:
        self.assertTrue(ApiKeyService.can_issue_ip_allowlist([], []))
        self.assertTrue(ApiKeyService.can_issue_ip_allowlist([], ["203.0.113.0/24"]))
        self.assertTrue(ApiKeyService.can_issue_ip_allowlist(["203.0.113.0/24"], ["203.0.113.10"]))
        self.assertFalse(ApiKeyService.can_issue_ip_allowlist(["203.0.113.0/24"], []))
        self.assertFalse(ApiKeyService.can_issue_ip_allowlist(["203.0.113.0/24"], ["198.51.100.10"]))
        self.assertFalse(ApiKeyService.can_issue_ip_allowlist(["203.0.113.0/24"], ["203.0.112.0/23"]))


if __name__ == "__main__":
    unittest.main()
