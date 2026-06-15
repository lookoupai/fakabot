from __future__ import annotations

import unittest

try:
    from app.main import app
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过 OpenAPI 安全契约测试：{exc.name}") from exc


class OpenApiSecurityContractTest(unittest.TestCase):
    def test_tenant_admin_security_schemes_are_declared(self) -> None:
        schema = app.openapi()
        security_schemes = schema["components"]["securitySchemes"]

        self.assertEqual("http", security_schemes["TenantAdminBearer"]["type"])
        self.assertEqual("bearer", security_schemes["TenantAdminBearer"]["scheme"])
        self.assertEqual("apiKey", security_schemes["TenantAdminApiKeyHeader"]["type"])
        self.assertEqual("X-API-Key", security_schemes["TenantAdminApiKeyHeader"]["name"])

    def test_platform_admin_security_schemes_are_declared(self) -> None:
        schema = app.openapi()
        security_schemes = schema["components"]["securitySchemes"]

        self.assertEqual("http", security_schemes["PlatformAdminBearer"]["type"])
        self.assertEqual("bearer", security_schemes["PlatformAdminBearer"]["scheme"])
        self.assertEqual("apiKey", security_schemes["PlatformAdminApiKeyHeader"]["type"])
        self.assertEqual("X-Platform-API-Key", security_schemes["PlatformAdminApiKeyHeader"]["name"])

    def test_tenant_admin_operations_declare_security_and_signature_headers(self) -> None:
        schema = app.openapi()
        operation = schema["paths"]["/api/v1/tenant/products"]["get"]

        self.assertEqual(
            [{"TenantAdminBearer": []}, {"TenantAdminApiKeyHeader": []}],
            operation["security"],
        )
        header_names = {
            parameter["name"]
            for parameter in operation["parameters"]
            if parameter.get("in") == "header"
        }
        self.assertIn("X-Faka-Timestamp", header_names)
        self.assertIn("X-Faka-Signature", header_names)
        self.assertEqual("HMAC-SHA256", operation["x-fakabot-signature"]["algorithm"])

    def test_all_tenant_admin_operations_declare_security_and_signature_contract(self) -> None:
        schema = app.openapi()
        expected_security = [{"TenantAdminBearer": []}, {"TenantAdminApiKeyHeader": []}]
        http_methods = {"get", "post", "put", "patch", "delete"}

        checked_operations = 0
        for path, path_item in schema["paths"].items():
            if not path.startswith("/api/v1/tenant"):
                continue
            for method, operation in path_item.items():
                if method not in http_methods:
                    continue
                checked_operations += 1
                with self.subTest(method=method, path=path):
                    self.assertEqual(expected_security, operation.get("security"))
                    self.assertNotIn({"PlatformAdminBearer": []}, operation.get("security", []))
                    self.assertNotIn({"PlatformAdminApiKeyHeader": []}, operation.get("security", []))
                    header_names = {
                        parameter["name"]
                        for parameter in operation.get("parameters", [])
                        if parameter.get("in") == "header"
                    }
                    self.assertIn("X-Faka-Timestamp", header_names)
                    self.assertIn("X-Faka-Signature", header_names)
                    signature_contract = operation.get("x-fakabot-signature")
                    self.assertIsNotNone(signature_contract)
                    self.assertEqual("HMAC-SHA256", signature_contract["algorithm"])
                    self.assertEqual(
                        "TENANT_ADMIN_REQUIRE_SIGNATURE",
                        signature_contract["requiredByConfig"],
                    )

        self.assertGreaterEqual(checked_operations, 1)

    def test_all_platform_admin_operations_declare_independent_security_and_signature_contract(self) -> None:
        schema = app.openapi()
        expected_security = [{"PlatformAdminBearer": []}, {"PlatformAdminApiKeyHeader": []}]
        expected_scopes = {
            ("get", "/api/v1/platform/finance/withdrawals"): "platform_finance:read",
            ("get", "/api/v1/platform/finance/withdrawals/{withdrawal_id}"): "platform_finance:read",
            ("post", "/api/v1/platform/finance/withdrawals/{withdrawal_id}/complete"): "platform_finance:write",
            ("post", "/api/v1/platform/finance/withdrawals/{withdrawal_id}/reject"): "platform_finance:write",
            ("get", "/api/v1/platform/risk/audit-logs"): "platform_risk:read",
            ("get", "/api/v1/platform/risk/banned-users"): "platform_risk:read",
            ("get", "/api/v1/platform/risk/users/{telegram_user_id}/ban-status"): "platform_risk:read",
            ("patch", "/api/v1/platform/risk/tenants/{tenant_id}/suspension-status"): "platform_risk:write",
            ("patch", "/api/v1/platform/risk/users/{telegram_user_id}/ban-status"): "platform_risk:write",
            ("get", "/api/v1/platform/subscription/plans"): "platform_subscriptions:read",
            ("post", "/api/v1/platform/subscription/plans"): "platform_subscriptions:write",
            ("get", "/api/v1/platform/subscription/plans/{plan_code}"): "platform_subscriptions:read",
            ("patch", "/api/v1/platform/subscription/plans/{plan_code}"): "platform_subscriptions:write",
            ("patch", "/api/v1/platform/subscription/plans/{plan_code}/status"): "platform_subscriptions:write",
            ("get", "/api/v1/platform/supply/supplier-offers"): "platform_supply:read",
            ("patch", "/api/v1/platform/supply/supplier-offers/{supplier_offer_id}/status"): "platform_supply:write",
        }
        http_methods = {"get", "post", "put", "patch", "delete"}

        checked_operations = 0
        for path, path_item in schema["paths"].items():
            if not path.startswith("/api/v1/platform"):
                continue
            for method, operation in path_item.items():
                if method not in http_methods:
                    continue
                checked_operations += 1
                with self.subTest(method=method, path=path):
                    self.assertEqual(expected_security, operation.get("security"))
                    self.assertNotIn({"TenantAdminBearer": []}, operation.get("security", []))
                    self.assertNotIn({"TenantAdminApiKeyHeader": []}, operation.get("security", []))
                    header_names = {
                        parameter["name"]
                        for parameter in operation.get("parameters", [])
                        if parameter.get("in") == "header"
                    }
                    self.assertIn("X-Faka-Timestamp", header_names)
                    self.assertIn("X-Faka-Signature", header_names)
                    self.assertNotIn("X-API-Key", header_names)
                    signature_contract = operation.get("x-fakabot-signature")
                    self.assertIsNotNone(signature_contract)
                    self.assertEqual("HMAC-SHA256", signature_contract["algorithm"])
                    self.assertEqual(
                        "PLATFORM_ADMIN_REQUIRE_SIGNATURE",
                        signature_contract["requiredByConfig"],
                    )
                    self.assertEqual(expected_scopes[(method, path)], operation.get("x-fakabot-required-scope"))

        self.assertEqual(len(expected_scopes), checked_operations)

    def test_public_store_operations_do_not_inherit_tenant_admin_security(self) -> None:
        schema = app.openapi()
        operation = schema["paths"]["/api/v1/store/{tenant_public_id}/products"]["get"]

        self.assertNotIn("security", operation)

    def test_all_public_store_operations_do_not_inherit_tenant_admin_security(self) -> None:
        schema = app.openapi()
        http_methods = {"get", "post", "put", "patch", "delete"}
        forbidden_headers = {
            "authorization",
            "X-API-Key",
            "X-Platform-API-Key",
            "X-Faka-Timestamp",
            "X-Faka-Signature",
        }

        checked_operations = 0
        for path, path_item in schema["paths"].items():
            if not path.startswith("/api/v1/store"):
                continue
            for method, operation in path_item.items():
                if method not in http_methods:
                    continue
                checked_operations += 1
                with self.subTest(method=method, path=path):
                    self.assertNotIn("security", operation)
                    self.assertNotIn("x-fakabot-signature", operation)
                    header_names = {
                        parameter["name"]
                        for parameter in operation.get("parameters", [])
                        if parameter.get("in") == "header"
                    }
                    self.assertTrue(forbidden_headers.isdisjoint(header_names))

        self.assertGreaterEqual(checked_operations, 1)

    def test_admin_web_tenant_overview_uses_cookie_session_without_api_key_security(self) -> None:
        schema = app.openapi()
        operation = schema["paths"]["/api/v1/admin-web/tenant/overview"]["get"]

        self.assertNotIn("security", operation)
        self.assertNotIn("x-fakabot-signature", operation)
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertTrue(
            {
                "authorization",
                "X-API-Key",
                "X-Platform-API-Key",
                "X-Faka-Timestamp",
                "X-Faka-Signature",
            }.isdisjoint(header_names)
        )
        response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        schema_name = response_ref.rsplit("/", 1)[-1]
        response_schema_text = str(schema["components"]["schemas"][schema_name]).lower()
        for forbidden in (
            "tenant_id",
            "tenant_bot_id",
            "owner_user_id",
            "bot_user_id",
            "encrypted_token",
            "token_hash",
            "webhook_secret",
            "api_key",
            "secret",
            "payment_url",
            "storage_key",
            "raw_payload",
        ):
            self.assertNotIn(forbidden, response_schema_text)

    def test_admin_web_business_plugin_capabilities_uses_cookie_session_and_safe_schema(self) -> None:
        schema = app.openapi()
        operation = schema["paths"]["/api/v1/admin-web/business-plugins/capabilities"]["get"]

        self.assertNotIn("security", operation)
        self.assertNotIn("x-fakabot-signature", operation)
        self.assertNotIn("requestBody", operation)
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertTrue(
            {
                "authorization",
                "X-API-Key",
                "X-Platform-API-Key",
                "X-Faka-Timestamp",
                "X-Faka-Signature",
            }.isdisjoint(header_names)
        )
        response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        response_schema_name = response_ref.rsplit("/", 1)[-1]
        self.assertEqual("AdminWebBusinessPluginCapabilitiesResponse", response_schema_name)
        response_schema_text = str(schema["components"]["schemas"][response_schema_name]).lower()
        item_schema = schema["components"]["schemas"]["AdminWebBusinessPluginCapabilityItemResponse"]
        self.assertEqual(
            {
                "plugin_id",
                "provider_name",
                "kind",
                "name",
                "version",
                "contract_version",
                "capabilities",
                "production_ready",
                "staging_verified",
                "offline_only",
                "tenant_configurable",
                "platform_configurable",
                "requires_tenant_enablement",
                "workspace_configured",
                "workspace_enabled",
                "scope_type",
                "active_connection_count",
                "disabled_connection_count",
            },
            set(item_schema["properties"]),
        )
        self.assertEqual("object", item_schema["properties"]["capabilities"]["type"])
        self.assertEqual({"type": "boolean"}, item_schema["properties"]["capabilities"]["additionalProperties"])
        combined_schema_text = f"{response_schema_text} {str(item_schema).lower()}"
        for forbidden in (
            "tenant_id",
            "tenant_bot_id",
            "owner_user_id",
            "bot_user_id",
            "encrypted_token",
            "token_hash",
            "webhook_secret",
            "entrypoint",
            "api_key",
            "secret",
            "credentials",
            "private_key",
            "config_encrypted",
            "raw_payload",
            "payload_json",
            "storage_key",
            "external_order_id",
            "payment_url",
        ):
            self.assertNotIn(forbidden, combined_schema_text)

    def test_admin_web_platform_dashboard_exposes_subscription_status_counts_safely(self) -> None:
        schema = app.openapi()
        operation = schema["paths"]["/api/v1/admin-web/platform/dashboard"]["get"]

        self.assertNotIn("security", operation)
        self.assertNotIn("x-fakabot-signature", operation)
        self.assertNotIn("requestBody", operation)
        response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        response_schema_name = response_ref.rsplit("/", 1)[-1]
        self.assertEqual("AdminWebPlatformDashboardResponse", response_schema_name)
        stats_schema = schema["components"]["schemas"]["AdminWebPlatformStatsResponse"]
        self.assertTrue(
            {
                "trial_subscription_count",
                "active_subscription_count",
                "grace_subscription_count",
                "suspended_subscription_count",
                "retention_expired_subscription_count",
            }.issubset(stats_schema["properties"])
        )
        dashboard_schema = schema["components"]["schemas"][response_schema_name]
        self.assertIn("payment_providers", dashboard_schema["properties"])
        self.assertIn("subscription_attention", dashboard_schema["properties"])
        provider_schema = schema["components"]["schemas"]["AdminWebPlatformPaymentProviderItemResponse"]
        self.assertEqual(
            {
                "provider_name",
                "display_name",
                "integration_kind",
                "contract_name",
                "production_ready",
                "staging_verified",
                "tenant_configurable",
                "platform_configurable",
                "create_payment_available",
                "callback_available",
                "query_order_available",
                "reconcile_available",
                "offline_only",
                "supported_assets",
                "supported_networks",
                "configured_tenant_count",
                "enabled_tenant_count",
                "missing_config_tenant_count",
                "platform_configured",
                "platform_enabled",
            },
            set(provider_schema["properties"]),
        )
        attention_schema = schema["components"]["schemas"]["AdminWebPlatformSubscriptionAttentionItemResponse"]
        self.assertEqual(
            {
                "tenant_public_id",
                "store_name",
                "owner_telegram_user_id",
                "owner_username",
                "tenant_status",
                "subscription_status",
                "plan_code",
                "plan_name",
                "attention_reason",
                "trial_ends_at",
                "current_period_ends_at",
                "subscription_ends_at",
                "grace_ends_at",
                "suspended_at",
                "data_retention_until",
            },
            set(attention_schema["properties"]),
        )
        combined_schema_text = (
            f"{str(dashboard_schema).lower()} "
            f"{str(stats_schema).lower()}"
            f"{str(provider_schema).lower()} "
            f"{str(attention_schema).lower()}"
        )
        for forbidden in (
            "tenant_id",
            "tenant_bot_id",
            "subscription_id",
            "plan_id",
            "invoice_id",
            "order_id",
            "owner_user_id",
            "payment_id",
            "encrypted_token",
            "token_hash",
            "webhook_secret",
            "api_key",
            "secret",
            "gateway_url",
            "merchant_id",
            "pid",
            "config_encrypted",
            "payment_url",
            "provider_trade_no",
            "raw_payload",
            "payload_json",
            "credentials",
            "monitor_address",
            "return_url",
            "storage_key",
        ):
            self.assertNotIn(forbidden, combined_schema_text)

    def test_admin_web_platform_bot_webhook_reset_uses_cookie_session_origin_and_safe_schema(self) -> None:
        schema = app.openapi()
        operation = schema["paths"]["/api/v1/admin-web/platform/bots/{tenant_public_id}/webhook/reset"]["post"]

        self.assertNotIn("security", operation)
        self.assertNotIn("x-fakabot-signature", operation)
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertTrue(
            {
                "authorization",
                "X-API-Key",
                "X-Platform-API-Key",
                "X-Faka-Timestamp",
                "X-Faka-Signature",
            }.isdisjoint(header_names)
        )
        path_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "path"
        }
        self.assertEqual({"tenant_public_id"}, path_names)
        request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        request_schema_name = request_ref.rsplit("/", 1)[-1]
        self.assertEqual("AdminWebPlatformBotWebhookResetRequest", request_schema_name)
        request_schema = schema["components"]["schemas"][request_schema_name]
        self.assertFalse(request_schema.get("additionalProperties", True))
        self.assertEqual({"reason"}, set(request_schema["properties"]))
        response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        response_schema_name = response_ref.rsplit("/", 1)[-1]
        self.assertEqual("AdminWebPlatformBotWebhookResetResponse", response_schema_name)
        response_schema = schema["components"]["schemas"][response_schema_name]
        self.assertEqual(
            {
                "tenant_public_id",
                "bot_username",
                "status",
                "webhook_status",
                "reason",
                "telegram_webhook_called",
            },
            set(response_schema["properties"]),
        )
        combined_schema_text = f"{str(request_schema).lower()} {str(response_schema).lower()}"
        for forbidden in (
            "tenant_id",
            "tenant_bot_id",
            "bot_user_id",
            "encrypted_token",
            "token_hash",
            "webhook_secret",
            "api_key",
            "secret",
            "private_key",
            "raw_payload",
            "storage_key",
        ):
            self.assertNotIn(forbidden, combined_schema_text)

    def test_admin_web_platform_subscription_plan_update_uses_cookie_session_origin_and_safe_schema(self) -> None:
        schema = app.openapi()
        operation = schema["paths"]["/api/v1/admin-web/platform/subscription/plans/{plan_code}"]["patch"]

        self.assertNotIn("security", operation)
        self.assertNotIn("x-fakabot-signature", operation)
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertTrue(
            {
                "authorization",
                "X-API-Key",
                "X-Platform-API-Key",
                "X-Faka-Timestamp",
                "X-Faka-Signature",
            }.isdisjoint(header_names)
        )
        path_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "path"
        }
        self.assertEqual({"plan_code"}, path_names)
        request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        request_schema_name = request_ref.rsplit("/", 1)[-1]
        self.assertEqual("AdminWebPlatformSubscriptionPlanUpdateRequest", request_schema_name)
        request_schema = schema["components"]["schemas"][request_schema_name]
        self.assertFalse(request_schema.get("additionalProperties", True))
        self.assertEqual(
            {"name", "monthly_price", "currency", "trial_days", "grace_days", "reason"},
            set(request_schema["properties"]),
        )
        response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        response_schema_name = response_ref.rsplit("/", 1)[-1]
        self.assertEqual("AdminWebPlatformSubscriptionPlanItemResponse", response_schema_name)
        response_schema = schema["components"]["schemas"][response_schema_name]
        self.assertEqual(
            {
                "code",
                "name",
                "monthly_price",
                "currency",
                "trial_days",
                "grace_days",
                "enabled",
                "created_at",
                "updated_at",
            },
            set(response_schema["properties"]),
        )
        combined_schema_text = f"{str(request_schema).lower()} {str(response_schema).lower()}"
        for forbidden in (
            "id",
            "plan_id",
            "tenant_id",
            "subscription_id",
            "invoice_id",
            "payment_id",
            "metadata_json",
            "raw_payload",
            "token",
            "secret",
            "api_key",
            "payment_url",
        ):
            self.assertNotIn(forbidden, combined_schema_text)

    def test_admin_web_platform_bot_status_uses_cookie_session_origin_and_safe_schema(self) -> None:
        schema = app.openapi()
        operation = schema["paths"]["/api/v1/admin-web/platform/bots/{tenant_public_id}/status"]["patch"]

        self.assertNotIn("security", operation)
        self.assertNotIn("x-fakabot-signature", operation)
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertTrue(
            {
                "authorization",
                "X-API-Key",
                "X-Platform-API-Key",
                "X-Faka-Timestamp",
                "X-Faka-Signature",
            }.isdisjoint(header_names)
        )
        path_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "path"
        }
        self.assertEqual({"tenant_public_id"}, path_names)
        request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        request_schema_name = request_ref.rsplit("/", 1)[-1]
        self.assertEqual("AdminWebPlatformBotStatusUpdateRequest", request_schema_name)
        request_schema = schema["components"]["schemas"][request_schema_name]
        self.assertFalse(request_schema.get("additionalProperties", True))
        self.assertEqual({"status", "reason"}, set(request_schema["properties"]))
        response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        response_schema_name = response_ref.rsplit("/", 1)[-1]
        self.assertEqual("AdminWebPlatformBotStatusResponse", response_schema_name)
        response_schema = schema["components"]["schemas"][response_schema_name]
        self.assertEqual(
            {
                "tenant_public_id",
                "bot_username",
                "previous_status",
                "status",
                "reason",
                "webhook_reset_available",
            },
            set(response_schema["properties"]),
        )
        combined_schema_text = f"{str(request_schema).lower()} {str(response_schema).lower()}"
        for forbidden in (
            "tenant_id",
            "tenant_bot_id",
            "bot_user_id",
            "encrypted_token",
            "token_hash",
            "webhook_secret",
            "api_key",
            "token",
            "secret",
            "raw_payload",
        ):
            self.assertNotIn(forbidden, combined_schema_text)

    def test_admin_web_platform_supplier_offer_status_uses_cookie_session_origin_and_safe_schema(self) -> None:
        schema = app.openapi()
        operation = schema["paths"]["/api/v1/admin-web/platform/supply/supplier-offers/{supplier_offer_id}/status"]["patch"]

        self.assertNotIn("security", operation)
        self.assertNotIn("x-fakabot-signature", operation)
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertTrue(
            {
                "authorization",
                "X-API-Key",
                "X-Platform-API-Key",
                "X-Faka-Timestamp",
                "X-Faka-Signature",
            }.isdisjoint(header_names)
        )
        path_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "path"
        }
        self.assertEqual({"supplier_offer_id"}, path_names)
        request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        request_schema_name = request_ref.rsplit("/", 1)[-1]
        self.assertEqual("AdminWebPlatformSupplierOfferStatusUpdateRequest", request_schema_name)
        request_schema = schema["components"]["schemas"][request_schema_name]
        self.assertFalse(request_schema.get("additionalProperties", True))
        self.assertEqual({"status", "reason"}, set(request_schema["properties"]))
        response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        response_schema_name = response_ref.rsplit("/", 1)[-1]
        self.assertEqual("AdminWebPlatformSupplierOfferItemResponse", response_schema_name)
        response_schema = schema["components"]["schemas"][response_schema_name]
        self.assertEqual(
            {
                "supplier_offer_id",
                "supplier_store_name",
                "product_name",
                "delivery_type",
                "suggested_price",
                "min_sale_price",
                "supplier_cost",
                "currency",
                "available_count",
                "requires_approval",
                "status",
                "created_at",
                "updated_at",
            },
            set(response_schema["properties"]),
        )
        combined_schema_text = f"{str(request_schema).lower()} {str(response_schema).lower()}"
        for forbidden in (
            "tenant_id",
            "supplier_tenant_id",
            "product_id",
            "variant_id",
            "inventory_item_id",
            "file_id",
            "storage_key",
            "api_key",
            "token",
            "secret",
            "raw_payload",
            "delivery_content",
        ):
            self.assertNotIn(forbidden, combined_schema_text)

    def test_admin_web_platform_withdrawal_detail_uses_cookie_session_and_safe_schema(self) -> None:
        schema = app.openapi()
        operation = schema["paths"]["/api/v1/admin-web/platform/finance/withdrawals/{withdrawal_id}"]["get"]

        self.assertNotIn("security", operation)
        self.assertNotIn("x-fakabot-signature", operation)
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertTrue(
            {
                "authorization",
                "X-API-Key",
                "X-Platform-API-Key",
                "X-Faka-Timestamp",
                "X-Faka-Signature",
            }.isdisjoint(header_names)
        )
        path_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "path"
        }
        self.assertEqual({"withdrawal_id"}, path_names)
        response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        response_schema_name = response_ref.rsplit("/", 1)[-1]
        self.assertEqual("AdminWebPlatformWithdrawalItemResponse", response_schema_name)
        response_schema = schema["components"]["schemas"][response_schema_name]
        self.assertEqual(
            {
                "withdrawal_id",
                "tenant_public_id",
                "store_name",
                "amount",
                "currency",
                "network",
                "address_masked",
                "status",
                "requested_at",
                "reviewed_at",
                "completed_at",
            },
            set(response_schema["properties"]),
        )
        combined_schema_text = str(response_schema).lower()
        for forbidden in (
            "tenant_id",
            "account_id",
            "ledger_entry_id",
            "address_encrypted",
            "destination",
            "destination_encrypted",
            "payout_reference",
            "payout_proof_url",
            "admin_note",
            "actor_user_id",
            "api_key",
            "token",
            "secret",
            "raw_payload",
        ):
            self.assertNotIn(forbidden, combined_schema_text)

    def test_admin_web_remaining_platform_write_operations_use_safe_schemas(self) -> None:
        schema = app.openapi()
        forbidden_headers = {
            "authorization",
            "X-API-Key",
            "X-Platform-API-Key",
            "X-Faka-Timestamp",
            "X-Faka-Signature",
        }
        common_forbidden = {
            "authorization",
            "cookie",
            "api_key",
            "secret",
            "token",
            "password",
            "private_key",
            "encrypted_token",
            "token_hash",
            "webhook_secret",
            "credentials",
            "metadata_json",
            "raw_metadata",
            "payload_json",
            "raw_payload",
            "raw_request",
            "raw_response",
            "storage_key",
        }
        cases = [
            (
                "patch",
                "/api/v1/admin-web/platform/risk/users/{telegram_user_id}/ban-status",
                {"telegram_user_id"},
                "AdminWebPlatformRiskBanStatusUpdateRequest",
                {"status", "reason"},
                "AdminWebPlatformRiskBannedUserItemResponse",
                {
                    "telegram_user_id",
                    "username",
                    "is_banned",
                    "ban_source",
                    "latest_action",
                    "latest_action_at",
                    "reason",
                    "trigger_rule",
                    "blocked_count",
                    "threshold",
                    "window_seconds",
                    "created_at",
                    "updated_at",
                },
                common_forbidden
                | {
                    "platform_user_id",
                    "tenant_id",
                    "trigger_tenant_id",
                    "source_tenant_id",
                    "actor_user_id",
                    "audit_log_id",
                    "target_id",
                    "key_hash",
                },
            ),
            (
                "patch",
                "/api/v1/admin-web/platform/risk/tenants/{tenant_public_id}/suspension-status",
                {"tenant_public_id"},
                "AdminWebPlatformTenantSuspensionStatusUpdateRequest",
                {"status", "reason"},
                "AdminWebPlatformTenantSuspensionStatusResponse",
                {"tenant_public_id", "previous_status", "status", "reason"},
                common_forbidden
                | {
                    "platform_user_id",
                    "tenant_id",
                    "tenant_bot_id",
                    "bot_user_id",
                    "owner_user_id",
                    "actor_user_id",
                    "audit_log_id",
                    "target_id",
                    "last_error",
                    "webhook_url",
                },
            ),
            (
                "post",
                "/api/v1/admin-web/platform/tenants/{tenant_public_id}/subscription/grant-days",
                {"tenant_public_id"},
                "AdminWebPlatformTenantSubscriptionGrantDaysRequest",
                {"days", "reason"},
                "AdminWebPlatformTenantSubscriptionAdjustmentResponse",
                {
                    "tenant_public_id",
                    "status",
                    "previous_period_ends_at",
                    "new_period_ends_at",
                    "action",
                },
                common_forbidden
                | {
                    "tenant_id",
                    "subscription_id",
                    "plan_id",
                    "invoice_id",
                    "order_id",
                    "payment_url",
                    "actor_user_id",
                    "audit_log_id",
                    "target_id",
                },
            ),
            (
                "patch",
                "/api/v1/admin-web/platform/tenants/{tenant_public_id}/subscription/period-end",
                {"tenant_public_id"},
                "AdminWebPlatformTenantSubscriptionSetPeriodEndRequest",
                {"period_ends_at", "reason"},
                "AdminWebPlatformTenantSubscriptionAdjustmentResponse",
                {
                    "tenant_public_id",
                    "status",
                    "previous_period_ends_at",
                    "new_period_ends_at",
                    "action",
                },
                common_forbidden
                | {
                    "tenant_id",
                    "subscription_id",
                    "plan_id",
                    "invoice_id",
                    "order_id",
                    "payment_url",
                    "actor_user_id",
                    "audit_log_id",
                    "target_id",
                },
            ),
            (
                "post",
                "/api/v1/admin-web/platform/finance/withdrawals/{withdrawal_id}/complete",
                {"withdrawal_id"},
                "AdminWebPlatformWithdrawalCompleteRequest",
                {"admin_note", "payout_reference", "payout_proof_url"},
                "AdminWebPlatformWithdrawalItemResponse",
                {
                    "withdrawal_id",
                    "tenant_public_id",
                    "store_name",
                    "amount",
                    "currency",
                    "network",
                    "address_masked",
                    "status",
                    "requested_at",
                    "reviewed_at",
                    "completed_at",
                },
                common_forbidden
                | {
                    "tenant_id",
                    "account_id",
                    "ledger_entry_id",
                    "address_encrypted",
                    "destination",
                    "destination_encrypted",
                    "idempotency_key",
                    "actor_user_id",
                },
            ),
            (
                "post",
                "/api/v1/admin-web/platform/finance/withdrawals/{withdrawal_id}/reject",
                {"withdrawal_id"},
                "AdminWebPlatformWithdrawalRejectRequest",
                {"admin_note"},
                "AdminWebPlatformWithdrawalItemResponse",
                {
                    "withdrawal_id",
                    "tenant_public_id",
                    "store_name",
                    "amount",
                    "currency",
                    "network",
                    "address_masked",
                    "status",
                    "requested_at",
                    "reviewed_at",
                    "completed_at",
                },
                common_forbidden
                | {
                    "tenant_id",
                    "account_id",
                    "ledger_entry_id",
                    "address_encrypted",
                    "destination",
                    "destination_encrypted",
                    "idempotency_key",
                    "actor_user_id",
                },
            ),
            (
                "post",
                "/api/v1/admin-web/platform/subscription/plans",
                set(),
                "AdminWebPlatformSubscriptionPlanCreateRequest",
                {"code", "name", "monthly_price", "currency", "trial_days", "grace_days", "enabled", "reason"},
                "AdminWebPlatformSubscriptionPlanItemResponse",
                {
                    "code",
                    "name",
                    "monthly_price",
                    "currency",
                    "trial_days",
                    "grace_days",
                    "enabled",
                    "created_at",
                    "updated_at",
                },
                common_forbidden
                | {
                    "id",
                    "plan_id",
                    "tenant_id",
                    "owner_user_id",
                    "subscription_id",
                    "invoice_id",
                    "order_id",
                    "payment_id",
                    "provider_trade_no",
                    "payment_url",
                },
            ),
            (
                "patch",
                "/api/v1/admin-web/platform/subscription/plans/{plan_code}/status",
                {"plan_code"},
                "AdminWebPlatformSubscriptionPlanStatusUpdateRequest",
                {"enabled", "reason"},
                "AdminWebPlatformSubscriptionPlanItemResponse",
                {
                    "code",
                    "name",
                    "monthly_price",
                    "currency",
                    "trial_days",
                    "grace_days",
                    "enabled",
                    "created_at",
                    "updated_at",
                },
                common_forbidden
                | {
                    "id",
                    "plan_id",
                    "tenant_id",
                    "owner_user_id",
                    "subscription_id",
                    "invoice_id",
                    "order_id",
                    "payment_id",
                    "provider_trade_no",
                    "payment_url",
                },
            ),
        ]

        for (
            method,
            path,
            expected_path_names,
            expected_request_schema_name,
            expected_request_fields,
            expected_response_schema_name,
            expected_response_fields,
            forbidden_schema_words,
        ) in cases:
            with self.subTest(method=method, path=path):
                operation = schema["paths"][path][method]
                self.assertNotIn("security", operation)
                self.assertNotIn("x-fakabot-signature", operation)
                header_names = {
                    parameter["name"]
                    for parameter in operation.get("parameters", [])
                    if parameter.get("in") == "header"
                }
                self.assertTrue(forbidden_headers.isdisjoint(header_names))
                path_names = {
                    parameter["name"]
                    for parameter in operation.get("parameters", [])
                    if parameter.get("in") == "path"
                }
                self.assertEqual(expected_path_names, path_names)
                request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
                request_schema_name = request_ref.rsplit("/", 1)[-1]
                self.assertEqual(expected_request_schema_name, request_schema_name)
                request_schema = schema["components"]["schemas"][request_schema_name]
                self.assertFalse(request_schema.get("additionalProperties", True))
                self.assertEqual(expected_request_fields, set(request_schema["properties"]))
                response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
                response_schema_name = response_ref.rsplit("/", 1)[-1]
                self.assertEqual(expected_response_schema_name, response_schema_name)
                response_schema = schema["components"]["schemas"][response_schema_name]
                self.assertEqual(expected_response_fields, set(response_schema["properties"]))
                combined_schema_text = f"{str(request_schema).lower()} {str(response_schema).lower()}"
                for forbidden in forbidden_schema_words:
                    self.assertNotIn(forbidden, combined_schema_text)

    def test_admin_web_external_source_connections_use_cookie_session_and_safe_schema(self) -> None:
        schema = app.openapi()
        forbidden_headers = {
            "authorization",
            "X-API-Key",
            "X-Platform-API-Key",
            "X-Faka-Timestamp",
            "X-Faka-Signature",
        }

        for method, path in (
            ("get", "/api/v1/admin-web/tenant/external-source-connections"),
            ("post", "/api/v1/admin-web/tenant/external-source-connections"),
            ("post", "/api/v1/admin-web/tenant/external-source-connections/disable"),
        ):
            operation = schema["paths"][path][method]
            with self.subTest(method=method, path=path):
                self.assertNotIn("security", operation)
                self.assertNotIn("x-fakabot-signature", operation)
                header_names = {
                    parameter["name"]
                    for parameter in operation.get("parameters", [])
                    if parameter.get("in") == "header"
                }
                self.assertTrue(forbidden_headers.isdisjoint(header_names))

        get_operation = schema["paths"]["/api/v1/admin-web/tenant/external-source-connections"]["get"]
        self.assertNotIn("requestBody", get_operation)
        create_ref = (
            schema["paths"]["/api/v1/admin-web/tenant/external-source-connections"]["post"]
            ["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        )
        create_schema_name = create_ref.rsplit("/", 1)[-1]
        create_schema = schema["components"]["schemas"][create_schema_name]
        self.assertFalse(create_schema["additionalProperties"])
        self.assertEqual(
            {"provider_name", "source_key", "display_name", "credentials"},
            set(create_schema["properties"]),
        )
        disable_ref = (
            schema["paths"]["/api/v1/admin-web/tenant/external-source-connections/disable"]["post"]
            ["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        )
        disable_schema_name = disable_ref.rsplit("/", 1)[-1]
        disable_schema = schema["components"]["schemas"][disable_schema_name]
        self.assertFalse(disable_schema["additionalProperties"])
        self.assertEqual({"connection_handle"}, set(disable_schema["properties"]))
        item_schema = schema["components"]["schemas"]["AdminWebExternalSourceConnectionItemResponse"]
        self.assertEqual(
            {
                "connection_handle",
                "provider_name",
                "source_key",
                "display_name",
                "status",
                "credential_field_count",
                "created_at",
                "last_used_at",
            },
            set(item_schema["properties"]),
        )
        response_schema_text = (
            str(schema["components"]["schemas"]["AdminWebExternalSourceConnectionsResponse"]).lower()
            + str(schema["components"]["schemas"]["AdminWebExternalSourceConnectionItemResponse"]).lower()
            + str(schema["components"]["schemas"]["AdminWebExternalSourceProviderItemResponse"]).lower()
        )
        for forbidden in (
            "tenant_id",
            "connection_id",
            "credentials",
            "credential_fields",
            "credentials_encrypted",
            "api_key",
            "secret",
            "token",
            "private_key",
            "raw_payload",
            "storage_key",
            "external_order_id",
            "delivery_record_id",
        ):
            self.assertNotIn(forbidden, response_schema_text)

    def test_admin_web_external_source_catalog_sync_uses_cookie_session_origin_and_handle_only_schema(self) -> None:
        schema = app.openapi()
        path = "/api/v1/admin-web/tenant/external-sources/catalog/sync"
        operation = schema["paths"][path]["post"]
        self.assertNotIn("security", operation)
        self.assertNotIn("x-fakabot-signature", operation)
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertTrue(
            {
                "authorization",
                "X-API-Key",
                "X-Platform-API-Key",
                "X-Faka-Timestamp",
                "X-Faka-Signature",
            }.isdisjoint(header_names)
        )
        request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        request_schema_name = request_ref.rsplit("/", 1)[-1]
        self.assertEqual("AdminWebExternalCatalogSyncRequest", request_schema_name)
        request_schema = schema["components"]["schemas"][request_schema_name]
        self.assertFalse(request_schema["additionalProperties"])
        self.assertEqual(
            {"connection_handle", "cursor", "limit", "max_pages"},
            set(request_schema["properties"]),
        )
        response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        response_schema_name = response_ref.rsplit("/", 1)[-1]
        self.assertEqual("AdminWebExternalCatalogSyncResponse", response_schema_name)
        response_schema = schema["components"]["schemas"][response_schema_name]
        self.assertEqual(
            {
                "provider_name",
                "source_key",
                "created_count",
                "updated_count",
                "skipped_count",
                "next_cursor",
                "products",
            },
            set(response_schema["properties"]),
        )
        product_schema = schema["components"]["schemas"]["AdminWebSyncedExternalCatalogProductResponse"]
        self.assertEqual(
            {"product_id", "action", "status", "skipped_reason"},
            set(product_schema["properties"]),
        )
        combined_schema_text = f"{str(request_schema).lower()} {str(response_schema).lower()} {str(product_schema).lower()}"
        for forbidden in (
            "tenant_id",
            "connection_id",
            "external_id",
            "external_source",
            "credentials",
            "credential_fields",
            "credentials_encrypted",
            "api_key",
            "password",
            "secret",
            "token",
            "private_key",
            "raw_payload",
            "storage_key",
            "delivery",
            "delivery_record_id",
            "message",
        ):
            self.assertNotIn(forbidden, combined_schema_text)

    def test_admin_web_external_source_catalog_products_uses_cookie_session_and_safe_schema(self) -> None:
        schema = app.openapi()
        path = "/api/v1/admin-web/tenant/external-sources/catalog/products"
        operation = schema["paths"][path]["get"]
        self.assertNotIn("security", operation)
        self.assertNotIn("x-fakabot-signature", operation)
        self.assertNotIn("requestBody", operation)
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertTrue(
            {
                "authorization",
                "X-API-Key",
                "X-Platform-API-Key",
                "X-Faka-Timestamp",
                "X-Faka-Signature",
            }.isdisjoint(header_names)
        )
        query_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "query"
        }
        self.assertEqual({"connection_handle", "limit", "offset"}, query_names)
        response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        response_schema_name = response_ref.rsplit("/", 1)[-1]
        self.assertEqual("AdminWebExternalSourceCatalogProductsResponse", response_schema_name)
        response_schema = schema["components"]["schemas"][response_schema_name]
        self.assertEqual(
            {
                "connection_handle",
                "provider_name",
                "source_key",
                "display_name",
                "status",
                "total_count",
                "limit",
                "offset",
                "items",
            },
            set(response_schema["properties"]),
        )
        product_schema = schema["components"]["schemas"]["AdminWebExternalSourceCatalogProductItemResponse"]
        self.assertEqual(
            {
                "product_id",
                "name",
                "category",
                "status",
                "delivery_type",
                "price",
                "currency",
                "available_count",
                "updated_at",
            },
            set(product_schema["properties"]),
        )
        combined_schema_text = f"{str(response_schema).lower()} {str(product_schema).lower()}"
        for forbidden in (
            "tenant_id",
            "connection_id",
            "external_id",
            "external_source",
            "credentials",
            "credential_fields",
            "credentials_encrypted",
            "api_key",
            "password",
            "secret",
            "token",
            "private_key",
            "raw_payload",
            "storage_key",
            "inventory_item_id",
            "variant_id",
        ):
            self.assertNotIn(forbidden, combined_schema_text)

    def test_admin_web_tenant_products_and_orders_use_cookie_session_without_api_key_security(self) -> None:
        schema = app.openapi()

        for path in (
            "/api/v1/admin-web/tenant/settings",
            "/api/v1/admin-web/tenant/products",
            "/api/v1/admin-web/tenant/orders",
        ):
            operation = schema["paths"][path]["get"]
            with self.subTest(path=path):
                self.assertNotIn("security", operation)
                self.assertNotIn("x-fakabot-signature", operation)
                header_names = {
                    parameter["name"]
                    for parameter in operation.get("parameters", [])
                    if parameter.get("in") == "header"
                }
                self.assertTrue(
                    {
                        "authorization",
                        "X-API-Key",
                        "X-Platform-API-Key",
                        "X-Faka-Timestamp",
                        "X-Faka-Signature",
                    }.isdisjoint(header_names)
                )
                response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
                schema_name = response_ref.rsplit("/", 1)[-1]
                response_schema_text = str(schema["components"]["schemas"][schema_name]).lower()
                for forbidden in (
                    "tenant_id",
                    "tenant_bot_id",
                    "order_id",
                    "self_product_id",
                    "product_variant_id",
                    "locked_inventory_item_id",
                    "supplier_tenant_id",
                    "reseller_product_id",
                    "encrypted_token",
                    "token_hash",
                    "webhook_secret",
                    "api_key",
                    "secret",
                    "payment_url",
                    "provider_trade_no",
                    "storage_key",
                    "raw_payload",
                    "payload_json",
                ):
                    self.assertNotIn(forbidden, response_schema_text)

    def test_admin_web_tenant_settings_patch_uses_cookie_session_and_safe_schema(self) -> None:
        schema = app.openapi()
        operation = schema["paths"]["/api/v1/admin-web/tenant/settings"]["patch"]

        self.assertNotIn("security", operation)
        self.assertNotIn("x-fakabot-signature", operation)
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertTrue(
            {
                "authorization",
                "X-API-Key",
                "X-Platform-API-Key",
                "X-Faka-Timestamp",
                "X-Faka-Signature",
            }.isdisjoint(header_names)
        )
        request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        request_schema_name = request_ref.rsplit("/", 1)[-1]
        self.assertEqual("AdminWebTenantStoreSettingsRequest", request_schema_name)
        request_properties = schema["components"]["schemas"][request_schema_name]["properties"]
        self.assertEqual(
            {
                "store_name",
                "welcome_text",
                "support_text",
                "order_timeout_minutes",
                "self_sale_enabled",
                "supplier_enabled",
                "reseller_enabled",
            },
            set(request_properties),
        )
        self.assertFalse(schema["components"]["schemas"][request_schema_name]["additionalProperties"])
        for name in ("self_sale_enabled", "supplier_enabled", "reseller_enabled"):
            self.assertIn({"type": "boolean"}, request_properties[name]["anyOf"])
        response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        response_schema_name = response_ref.rsplit("/", 1)[-1]
        self.assertEqual("AdminWebTenantStoreSettingsResponse", response_schema_name)
        response_properties = schema["components"]["schemas"][response_schema_name]["properties"]
        self.assertEqual(
            {
                "store_name",
                "welcome_text",
                "support_text",
                "order_timeout_minutes",
                "self_sale_enabled",
                "supplier_enabled",
                "reseller_enabled",
            },
            set(response_properties),
        )
        for name in ("self_sale_enabled", "supplier_enabled", "reseller_enabled"):
            self.assertEqual("boolean", response_properties[name]["type"])
        for forbidden in (
            "tenant_id",
            "tenant_bot_id",
            "owner_user_id",
            "bot_user_id",
            "feature_flags",
            "clone_enabled",
            "encrypted_token",
            "token_hash",
            "webhook_secret",
            "api_key",
            "secret",
            "raw_payload",
            "payload_json",
        ):
            self.assertNotIn(forbidden, request_properties)
            self.assertNotIn(forbidden, response_properties)

    def test_admin_web_tenant_order_diagnostics_uses_cookie_session_without_api_key_security(self) -> None:
        schema = app.openapi()
        path = "/api/v1/admin-web/tenant/orders/{out_trade_no}/diagnostics"
        operation = schema["paths"][path]["get"]

        self.assertNotIn("security", operation)
        self.assertNotIn("x-fakabot-signature", operation)
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertTrue(
            {
                "authorization",
                "X-API-Key",
                "X-Platform-API-Key",
                "X-Faka-Timestamp",
                "X-Faka-Signature",
            }.isdisjoint(header_names)
        )
        path_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "path"
        }
        self.assertEqual({"out_trade_no"}, path_names)

    def test_admin_web_tenant_order_diagnostics_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        response = schema["components"]["schemas"]["AdminWebTenantOrderDiagnosticsResponse"]["properties"]
        payment = schema["components"]["schemas"]["AdminWebOrderPaymentDiagnosticItemResponse"]["properties"]
        callback = schema["components"]["schemas"]["AdminWebOrderPaymentCallbackDiagnosticItemResponse"]["properties"]
        delivery = schema["components"]["schemas"]["AdminWebOrderDeliveryDiagnosticItemResponse"]["properties"]
        external = schema["components"]["schemas"]["AdminWebOrderExternalFulfillmentDiagnosticItemResponse"]["properties"]
        trc20_direct = schema["components"]["schemas"]["AdminWebOrderTrc20DirectDiagnosticItemResponse"]["properties"]

        self.assertEqual(
            {
                "out_trade_no",
                "source_type",
                "status",
                "payment_mode",
                "payment_provider",
                "amount",
                "currency",
                "created_at",
                "expires_at",
                "paid_at",
                "delivered_at",
                "payment_count",
                "callback_count",
                "callback_status_counts",
                "payments",
                "callbacks",
                "delivery",
                "external_fulfillment",
                "trc20_direct",
            },
            set(response),
        )
        self.assertEqual(
            {"provider", "status", "amount", "currency", "has_payment_url", "created_at", "paid_at"},
            set(payment),
        )
        self.assertEqual(
            {"provider", "process_status", "failure_reason", "created_at", "processed_at"},
            set(callback),
        )
        self.assertEqual(
            {
                "delivery_type",
                "status",
                "failure_reason",
                "has_inventory_item",
                "has_uploaded_file",
                "has_telegram_chat",
                "created_at",
                "updated_at",
                "sent_at",
            },
            set(delivery),
        )
        self.assertEqual(
            {
                "expected",
                "attempt_count",
                "latest_attempt_status",
                "latest_attempt_trigger",
                "latest_attempt_at",
                "latest_failure_stage",
                "latest_failure_category",
                "latest_failure_retryable",
                "latest_upstream_status_code",
                "latest_item_count",
                "latest_delivery_record_linked",
            },
            set(external),
        )
        self.assertEqual(
            {
                "expected",
                "transfer_count",
                "latest_match_status",
                "latest_confirmations",
                "latest_matched_at",
                "latest_amount",
            },
            set(trc20_direct),
        )
        for forbidden in (
            "tenant_id",
            "order_id",
            "payment_id",
            "callback_id",
            "delivery_record_id",
            "inventory_item_id",
            "uploaded_file_id",
            "telegram_chat_id",
            "storage_key",
            "content",
            "content_hash",
            "payment_url",
            "provider_trade_no",
            "payload",
            "payload_json",
            "payload_hash",
            "raw_payload",
            "raw_request_hash",
            "idempotency_key",
            "signature",
            "signing_text",
            "credentials",
            "credentials_encrypted",
            "attempt_id",
            "external_provider",
            "external_product_id",
            "external_order_id",
            "source_key",
            "connection_id",
            "failure_fingerprint",
            "items",
            "message",
            "token",
            "secret",
            "secret_key",
            "api_key",
            "password",
            "private_key",
            "config_encrypted",
        ):
            self.assertNotIn(forbidden, response)
            self.assertNotIn(forbidden, payment)
            self.assertNotIn(forbidden, callback)
            self.assertNotIn(forbidden, delivery)
            self.assertNotIn(forbidden, external)
            self.assertNotIn(forbidden, trc20_direct)

    def test_admin_web_tenant_order_observability_uses_cookie_session_without_api_key_security(self) -> None:
        schema = app.openapi()
        path = "/api/v1/admin-web/tenant/orders/observability"
        operation = schema["paths"][path]["get"]

        self.assertNotIn("security", operation)
        self.assertNotIn("x-fakabot-signature", operation)
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertTrue(
            {
                "authorization",
                "X-API-Key",
                "X-Platform-API-Key",
                "X-Faka-Timestamp",
                "X-Faka-Signature",
            }.isdisjoint(header_names)
        )
        query_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "query"
        }
        self.assertEqual({"limit", "out_trade_no"}, query_names)

    def test_admin_web_tenant_order_observability_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        response = schema["components"]["schemas"]["AdminWebTenantOrderObservabilityResponse"]["properties"]
        callback_failure = schema["components"]["schemas"]["AdminWebPaymentCallbackFailureItemResponse"]["properties"]
        callback_rejection = schema["components"]["schemas"]["AdminWebPaymentCallbackRejectionItemResponse"][
            "properties"
        ]
        fulfillment_attempt = schema["components"]["schemas"]["AdminWebExternalFulfillmentAttemptItemResponse"][
            "properties"
        ]

        self.assertEqual(
            {"limit", "callback_failures", "callback_rejections", "external_fulfillment_attempts"},
            set(response),
        )
        self.assertEqual(
            {
                "created_at",
                "processed_at",
                "out_trade_no",
                "order_status",
                "provider",
                "process_status",
                "failure_reason",
            },
            set(callback_failure),
        )
        self.assertEqual(
            {
                "created_at",
                "provider",
                "reason_category",
                "failure_reason",
                "http_status",
                "out_trade_no",
                "order_status",
                "payload_field_count",
            },
            set(callback_rejection),
        )
        self.assertEqual(
            {
                "created_at",
                "started_at",
                "finished_at",
                "out_trade_no",
                "provider_name",
                "source_key",
                "attempt_source",
                "status",
                "imported",
                "item_count",
                "failure_reason",
                "failure_stage",
                "failure_category",
                "failure_retryable",
                "upstream_status_code",
            },
            set(fulfillment_attempt),
        )
        for forbidden in (
            "tenant_id",
            "order_id",
            "callback_id",
            "audit_log_id",
            "attempt_id",
            "product_id",
            "connection_id",
            "external_product_id",
            "external_order_id",
            "delivery_record_id",
            "failure_fingerprint",
            "payment_url",
            "provider_trade_no",
            "payload",
            "payload_json",
            "payload_hash",
            "raw_payload",
            "raw_response",
            "credentials",
            "credentials_encrypted",
            "api_key",
            "token",
            "secret",
            "storage_key",
            "items",
            "message",
        ):
            self.assertNotIn(forbidden, response)
            self.assertNotIn(forbidden, callback_failure)
            self.assertNotIn(forbidden, callback_rejection)
            self.assertNotIn(forbidden, fulfillment_attempt)

    def test_admin_web_tenant_subscription_and_finance_use_cookie_session_without_api_key_security(self) -> None:
        schema = app.openapi()

        for path in ("/api/v1/admin-web/tenant/subscription", "/api/v1/admin-web/tenant/finance"):
            operation = schema["paths"][path]["get"]
            with self.subTest(path=path):
                self.assertNotIn("security", operation)
                self.assertNotIn("x-fakabot-signature", operation)
                header_names = {
                    parameter["name"]
                    for parameter in operation.get("parameters", [])
                    if parameter.get("in") == "header"
                }
                self.assertTrue(
                    {
                        "authorization",
                        "X-API-Key",
                        "X-Platform-API-Key",
                        "X-Faka-Timestamp",
                        "X-Faka-Signature",
                    }.isdisjoint(header_names)
                )
                query_names = {
                    parameter["name"]
                    for parameter in operation.get("parameters", [])
                    if parameter.get("in") == "query"
                }
                self.assertNotIn("tenant_id", query_names)
                self.assertNotIn("workspace_id", query_names)

    def test_admin_web_tenant_subscription_and_finance_schemas_expose_safe_fields_only(self) -> None:
        schema = app.openapi()
        subscription = schema["components"]["schemas"]["AdminWebTenantSubscriptionDashboardResponse"]["properties"]
        invoice = schema["components"]["schemas"]["AdminWebTenantSubscriptionInvoiceItemResponse"]["properties"]
        finance = schema["components"]["schemas"]["AdminWebTenantFinanceDashboardResponse"]["properties"]
        balance = schema["components"]["schemas"]["AdminWebTenantFinanceBalanceResponse"]["properties"]
        audit = schema["components"]["schemas"]["AdminWebTenantFinanceAuditResponse"]["properties"]
        withdrawal = schema["components"]["schemas"]["AdminWebTenantWithdrawalItemResponse"]["properties"]

        self.assertEqual(
            {
                "status",
                "plan_code",
                "plan_name",
                "monthly_price",
                "currency",
                "trial_days",
                "grace_days",
                "trial_ends_at",
                "current_period_ends_at",
                "subscription_ends_at",
                "grace_ends_at",
                "suspended_at",
                "data_retention_until",
                "invoices",
            },
            set(subscription),
        )
        self.assertEqual({"out_trade_no", "amount", "currency", "status", "paid_at", "created_at"}, set(invoice))
        self.assertEqual({"balance", "audit", "withdrawals"}, set(finance))
        self.assertEqual({"account_type", "currency", "pending_balance", "available_balance", "frozen_balance"}, set(balance))
        self.assertEqual(
            {
                "account_type",
                "currency",
                "stored_pending_balance",
                "stored_available_balance",
                "stored_frozen_balance",
                "computed_pending_balance",
                "computed_available_balance",
                "computed_frozen_balance",
                "pending_difference",
                "available_difference",
                "frozen_difference",
                "is_balanced",
            },
            set(audit),
        )
        self.assertEqual(
            {"amount", "currency", "network", "address_masked", "status", "requested_at", "reviewed_at", "completed_at"},
            set(withdrawal),
        )
        for forbidden in (
            "tenant_id",
            "plan_id",
            "subscription_id",
            "invoice_id",
            "payment_id",
            "order_id",
            "payment_url",
            "provider_trade_no",
            "payload",
            "raw_payload",
            "metadata_json",
            "ledger_account_id",
            "account_id",
            "ledger_entry_id",
            "withdrawal_id",
            "address",
            "address_encrypted",
            "admin_note",
            "internal_note",
            "payout_reference",
            "payout_proof_url",
            "idempotency_key",
            "actor_user_id",
            "token",
            "secret",
            "api_key",
            "credentials",
        ):
            self.assertNotIn(forbidden, subscription)
            self.assertNotIn(forbidden, invoice)
            self.assertNotIn(forbidden, finance)
            self.assertNotIn(forbidden, balance)
            self.assertNotIn(forbidden, audit)
            self.assertNotIn(forbidden, withdrawal)

    def test_admin_web_tenant_subscription_renewal_order_uses_cookie_session_and_safe_schema(self) -> None:
        schema = app.openapi()
        path = "/api/v1/admin-web/tenant/subscription/renewal-orders"
        operation = schema["paths"][path]["post"]

        self.assertNotIn("security", operation)
        self.assertNotIn("x-fakabot-signature", operation)
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertTrue(
            {
                "authorization",
                "X-API-Key",
                "X-Platform-API-Key",
                "X-Faka-Timestamp",
                "X-Faka-Signature",
            }.isdisjoint(header_names)
        )
        query_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "query"
        }
        self.assertNotIn("tenant_id", query_names)
        self.assertNotIn("workspace_id", query_names)

        request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        request_schema_name = request_ref.rsplit("/", 1)[-1]
        request_schema = schema["components"]["schemas"][request_schema_name]
        request_properties = request_schema.get("properties", {})
        self.assertEqual("AdminWebSubscriptionRenewalOrderRequest", request_schema_name)
        self.assertEqual({"months"}, set(request_properties))
        self.assertFalse(request_schema.get("additionalProperties", True))
        self.assertEqual(1, request_properties["months"].get("minimum"))
        self.assertEqual(24, request_properties["months"].get("maximum"))

        response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        response_schema_name = response_ref.rsplit("/", 1)[-1]
        response_schema = schema["components"]["schemas"][response_schema_name]
        response_properties = response_schema.get("properties", {})
        self.assertEqual("AdminWebSubscriptionRenewalOrderResponse", response_schema_name)
        self.assertEqual(
            {
                "out_trade_no",
                "amount",
                "currency",
                "months",
                "expires_at",
                "payment_available",
                "payment_provider",
                "payment_url",
                "payment_failure_reason",
            },
            set(response_properties),
        )

        request_schema_text = str(request_schema).lower()
        response_schema_text = str(response_schema).lower()
        for field in (
            "tenant_id",
            "workspace_id",
            "owner_user_id",
            "subscription_id",
            "plan_id",
            "invoice_id",
            "order_id",
            "payment_id",
            "callback_id",
            "buyer_telegram_user_id",
            "created_by_user_id",
            "metadata_json",
            "payload_json",
            "payload_hash",
            "raw_payload",
            "raw_request",
            "raw_response",
            "provider_trade_no",
            "signature",
            "signing_text",
            "credentials",
            "credentials_encrypted",
            "token",
            "secret",
            "secret_key",
            "api_key",
            "password",
            "private_key",
            "config_encrypted",
        ):
            self.assertNotIn(field, request_schema_text)
            self.assertNotIn(field, response_schema_text)
        self.assertIn("payment_url", response_properties)

    def test_admin_web_tenant_withdrawal_create_uses_cookie_session_and_safe_schema(self) -> None:
        schema = app.openapi()
        path = "/api/v1/admin-web/tenant/finance/withdrawals"
        operation = schema["paths"][path]["post"]

        self.assertNotIn("security", operation)
        self.assertNotIn("x-fakabot-signature", operation)
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertTrue(
            {
                "authorization",
                "X-API-Key",
                "X-Platform-API-Key",
                "X-Faka-Timestamp",
                "X-Faka-Signature",
            }.isdisjoint(header_names)
        )
        query_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "query"
        }
        self.assertNotIn("tenant_id", query_names)
        self.assertNotIn("workspace_id", query_names)

        request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        request_schema_name = request_ref.rsplit("/", 1)[-1]
        request_schema = schema["components"]["schemas"][request_schema_name]
        request_properties = request_schema.get("properties", {})
        self.assertEqual("AdminWebWithdrawalRequest", request_schema_name)
        self.assertEqual({"amount", "network", "address", "currency"}, set(request_properties))
        self.assertFalse(request_schema.get("additionalProperties", True))
        amount_numeric_schema = next(
            item for item in request_properties["amount"].get("anyOf", ()) if item.get("type") == "number"
        )
        self.assertEqual(0, amount_numeric_schema.get("exclusiveMinimum"))
        self.assertEqual(2, request_properties["network"].get("minLength"))
        self.assertEqual(32, request_properties["network"].get("maxLength"))
        self.assertEqual(8, request_properties["address"].get("minLength"))
        self.assertEqual(256, request_properties["address"].get("maxLength"))

        response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        response_schema_name = response_ref.rsplit("/", 1)[-1]
        response_schema = schema["components"]["schemas"][response_schema_name]
        response_properties = response_schema.get("properties", {})
        self.assertEqual("AdminWebTenantWithdrawalItemResponse", response_schema_name)
        self.assertEqual(
            {"amount", "currency", "network", "address_masked", "status", "requested_at", "reviewed_at", "completed_at"},
            set(response_properties),
        )

        request_schema_text = str(request_schema).lower()
        response_schema_text = str(response_schema).lower()
        for field in (
            "tenant_id",
            "tenant_public_id",
            "workspace_id",
            "withdrawal_id",
            "account_id",
            "ledger_account_id",
            "ledger_entry_id",
            "actor_user_id",
            "status",
            "admin_note",
            "internal_note",
            "payout_reference",
            "payout_proof_url",
            "available_balance",
            "frozen_balance",
            "idempotency_key",
            "payment_url",
            "provider_trade_no",
            "metadata_json",
            "raw_payload",
            "token",
            "secret",
            "api_key",
            "credentials",
        ):
            self.assertNotIn(field, request_schema_text)
        for field in (
            "tenant_id",
            "tenant_public_id",
            "workspace_id",
            "withdrawal_id",
            "account_id",
            "ledger_account_id",
            "ledger_entry_id",
            "actor_user_id",
            "admin_note",
            "internal_note",
            "payout_reference",
            "payout_proof_url",
            "available_balance",
            "frozen_balance",
            "idempotency_key",
            "payment_url",
            "provider_trade_no",
            "metadata_json",
            "raw_payload",
            "token",
            "secret",
            "api_key",
            "credentials",
        ):
            self.assertNotIn(field, response_schema_text)

    def test_admin_web_tenant_report_export_jobs_use_cookie_session_and_safe_schema(self) -> None:
        schema = app.openapi()
        path = "/api/v1/admin-web/tenant/reports/export-jobs"
        forbidden_headers = {
            "authorization",
            "X-API-Key",
            "X-Platform-API-Key",
            "X-Faka-Timestamp",
            "X-Faka-Signature",
        }

        for method in ("get", "post"):
            operation = schema["paths"][path][method]
            with self.subTest(method=method):
                self.assertNotIn("security", operation)
                self.assertNotIn("x-fakabot-signature", operation)
                header_names = {
                    parameter["name"]
                    for parameter in operation.get("parameters", [])
                    if parameter.get("in") == "header"
                }
                self.assertTrue(forbidden_headers.isdisjoint(header_names))
                query_names = {
                    parameter["name"]
                    for parameter in operation.get("parameters", [])
                    if parameter.get("in") == "query"
                }
                self.assertNotIn("tenant_id", query_names)
                self.assertNotIn("workspace_id", query_names)

        get_operation = schema["paths"][path]["get"]
        get_response_ref = get_operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        get_response_schema_name = get_response_ref.rsplit("/", 1)[-1]
        get_response_schema = schema["components"]["schemas"][get_response_schema_name]
        get_response_properties = get_response_schema.get("properties", {})
        item_schema = schema["components"]["schemas"]["AdminWebTenantReportExportJobItemResponse"]
        item_properties = item_schema.get("properties", {})

        self.assertEqual("AdminWebTenantReportExportJobsResponse", get_response_schema_name)
        self.assertEqual({"status", "report_type", "limit", "export_jobs"}, set(get_response_properties))
        self.assertEqual(
            {
                "report_type",
                "scope_type",
                "status",
                "row_count",
                "download_available",
                "download_handle",
                "failure_reason",
                "expires_at",
                "created_at",
                "started_at",
                "finished_at",
            },
            set(item_properties),
        )

        post_operation = schema["paths"][path]["post"]
        request_ref = post_operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        request_schema_name = request_ref.rsplit("/", 1)[-1]
        request_schema = schema["components"]["schemas"][request_schema_name]
        request_properties = request_schema.get("properties", {})
        post_response_ref = post_operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        post_response_schema_name = post_response_ref.rsplit("/", 1)[-1]

        self.assertEqual("AdminWebReportExportJobCreateRequest", request_schema_name)
        self.assertEqual({"report_type"}, set(request_properties))
        self.assertFalse(request_schema.get("additionalProperties", True))
        self.assertEqual("AdminWebTenantReportExportJobItemResponse", post_response_schema_name)

        schema_text = f"{request_schema} {get_response_schema} {item_schema}".lower()
        for field in (
            "export_job_id",
            "tenant_id",
            "tenant_public_id",
            "workspace_id",
            "requested_by_user_id",
            "actor_user_id",
            "filename",
            "download_url",
            "download_token",
            "storage_key",
            "error_message",
            "local_path",
            "path",
            "payload",
            "payload_json",
            "raw_payload",
            "raw_request",
            "raw_response",
            "payment_url",
            "provider_trade_no",
            "token",
            "secret",
            "secret_key",
            "api_key",
            "authorization",
            "cookie",
            "credential",
            "credentials",
            "plain_key",
            "tenant_bot_id",
            "owner_user_id",
            "encrypted_token",
            "token_hash",
            "webhook_secret",
        ):
            self.assertNotIn(field, schema_text)

    def test_admin_web_tenant_report_export_download_uses_cookie_session_origin_and_handle_only_schema(self) -> None:
        schema = app.openapi()
        path = "/api/v1/admin-web/tenant/reports/export-jobs/download"
        operation = schema["paths"][path]["post"]
        forbidden_headers = {
            "authorization",
            "X-API-Key",
            "X-Platform-API-Key",
            "X-Faka-Timestamp",
            "X-Faka-Signature",
        }

        self.assertNotIn("security", operation)
        self.assertNotIn("x-fakabot-signature", operation)
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertTrue(forbidden_headers.isdisjoint(header_names))
        query_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "query"
        }
        self.assertNotIn("tenant_id", query_names)
        self.assertNotIn("workspace_id", query_names)

        request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        request_schema_name = request_ref.rsplit("/", 1)[-1]
        request_schema = schema["components"]["schemas"][request_schema_name]
        self.assertEqual("AdminWebReportExportJobDownloadRequest", request_schema_name)
        self.assertEqual({"download_handle"}, set(request_schema.get("properties", {})))
        self.assertFalse(request_schema.get("additionalProperties", True))

        schema_text = f"{operation} {request_schema}".lower()
        for field in (
            "export_job_id",
            "tenant_id",
            "tenant_public_id",
            "workspace_id",
            "requested_by_user_id",
            "actor_user_id",
            "filename",
            "download_url",
            "download_token",
            "storage_key",
            "local_path",
            "payload",
            "payload_json",
            "raw_payload",
            "token",
            "secret",
            "secret_key",
            "api_key",
            "authorization",
            "credential",
            "credentials",
        ):
            self.assertNotIn(field, schema_text)

    def test_admin_web_tenant_api_keys_use_cookie_session_and_safe_schema(self) -> None:
        schema = app.openapi()
        forbidden_headers = {
            "authorization",
            "X-API-Key",
            "X-Platform-API-Key",
            "X-Faka-Timestamp",
            "X-Faka-Signature",
        }

        for method, path in (
            ("get", "/api/v1/admin-web/tenant/api-keys"),
            ("post", "/api/v1/admin-web/tenant/api-keys"),
            ("post", "/api/v1/admin-web/tenant/api-keys/revoke"),
        ):
            operation = schema["paths"][path][method]
            with self.subTest(method=method, path=path):
                self.assertNotIn("security", operation)
                self.assertNotIn("x-fakabot-signature", operation)
                header_names = {
                    parameter["name"]
                    for parameter in operation.get("parameters", [])
                    if parameter.get("in") == "header"
                }
                self.assertTrue(forbidden_headers.isdisjoint(header_names))
                query_names = {
                    parameter["name"]
                    for parameter in operation.get("parameters", [])
                    if parameter.get("in") == "query"
                }
                self.assertNotIn("tenant_id", query_names)
                self.assertNotIn("workspace_id", query_names)

        list_schema = schema["components"]["schemas"]["AdminWebTenantApiKeysResponse"]
        item_schema = schema["components"]["schemas"]["AdminWebTenantApiKeyItemResponse"]
        create_request_schema = schema["components"]["schemas"]["AdminWebTenantApiKeyCreateRequest"]
        create_response_schema = schema["components"]["schemas"]["AdminWebCreatedTenantApiKeyResponse"]
        revoke_request_schema = schema["components"]["schemas"]["AdminWebTenantApiKeyRevokeRequest"]
        revoke_response_schema = schema["components"]["schemas"]["AdminWebTenantApiKeyRevokeResponse"]

        self.assertEqual({"limit", "keys"}, set(list_schema.get("properties", {})))
        self.assertEqual(
            {
                "credential_handle",
                "name",
                "key_prefix",
                "status",
                "scopes",
                "ip_allowlist",
                "created_at",
                "last_used_at",
            },
            set(item_schema.get("properties", {})),
        )
        self.assertEqual({"name", "scopes", "ip_allowlist"}, set(create_request_schema.get("properties", {})))
        self.assertFalse(create_request_schema.get("additionalProperties", True))
        self.assertEqual(
            set(item_schema.get("properties", {})) | {"plain_key"},
            set(create_response_schema.get("properties", {})),
        )
        self.assertEqual({"credential_handle"}, set(revoke_request_schema.get("properties", {})))
        self.assertFalse(revoke_request_schema.get("additionalProperties", True))
        self.assertEqual({"credential_handle", "revoked"}, set(revoke_response_schema.get("properties", {})))

        safe_schema_text = f"{list_schema} {item_schema} {revoke_request_schema} {revoke_response_schema}".lower()
        for field in (
            "api_key_id",
            "tenant_id",
            "tenant_public_id",
            "workspace_id",
            "created_by_user_id",
            "key_hash",
            "plain_key",
            "secret",
            "token",
            "authorization",
            "cookie",
            "tenant_bot_id",
            "owner_user_id",
            "encrypted_token",
            "token_hash",
            "webhook_secret",
        ):
            self.assertNotIn(field, safe_schema_text)

        create_request_text = str(create_request_schema).lower()
        for field in (
            "api_key_id",
            "tenant_id",
            "tenant_public_id",
            "workspace_id",
            "created_by_user_id",
            "key_hash",
            "plain_key",
            "secret",
            "token",
            "authorization",
            "cookie",
        ):
            self.assertNotIn(field, create_request_text)

        create_response_text = str(create_response_schema).lower()
        self.assertIn("plain_key", create_response_text)
        for field in (
            "api_key_id",
            "tenant_id",
            "tenant_public_id",
            "workspace_id",
            "created_by_user_id",
            "key_hash",
            "secret",
            "token",
            "authorization",
            "cookie",
        ):
            self.assertNotIn(field, create_response_text)

    def test_admin_web_tenant_product_metadata_uses_cookie_session_and_safe_schema(self) -> None:
        schema = app.openapi()
        path = "/api/v1/admin-web/tenant/products/{product_id}/metadata"
        operation = schema["paths"][path]["patch"]

        self.assertNotIn("security", operation)
        self.assertNotIn("x-fakabot-signature", operation)
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertTrue(
            {
                "authorization",
                "X-API-Key",
                "X-Platform-API-Key",
                "X-Faka-Timestamp",
                "X-Faka-Signature",
            }.isdisjoint(header_names)
        )

        path_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "path"
        }
        self.assertEqual({"product_id"}, path_names)

        request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        request_schema_name = request_ref.rsplit("/", 1)[-1]
        request_schema = schema["components"]["schemas"][request_schema_name]
        request_properties = request_schema.get("properties", {})
        self.assertEqual("AdminWebProductMetadataRequest", request_schema_name)
        self.assertEqual({"category", "sort_order"}, set(request_properties))
        self.assertFalse(request_schema.get("additionalProperties", True))

        response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        response_schema_name = response_ref.rsplit("/", 1)[-1]
        response_schema = schema["components"]["schemas"][response_schema_name]
        response_properties = response_schema.get("properties", {})
        self.assertEqual("AdminWebTenantProductItemResponse", response_schema_name)
        self.assertEqual(
            {
                "product_id",
                "name",
                "category",
                "sort_order",
                "status",
                "delivery_type",
                "price",
                "currency",
                "available_count",
            },
            set(response_properties),
        )

        forbidden = (
            "tenant_id",
            "tenant_bot_id",
            "workspace_id",
            "supplier_tenant_id",
            "reseller_tenant_id",
            "price",
            "sale_price",
            "delivery_type",
            "status",
            "external_source",
            "source_key",
            "external_id",
            "variant_id",
            "product_variant_id",
            "delivery_file_id",
            "storage_key",
            "credentials",
            "api_key",
            "token",
            "secret",
            "secret_key",
            "raw_payload",
            "payload_json",
            "metadata_json",
        )
        request_schema_text = str(request_schema).lower()
        for field in forbidden:
            self.assertNotIn(field, request_schema_text)

        response_schema_text = str(response_schema).lower()
        for field in (
            "tenant_id",
            "tenant_bot_id",
            "workspace_id",
            "supplier_tenant_id",
            "reseller_tenant_id",
            "variant_id",
            "product_variant_id",
            "delivery_file_id",
            "storage_key",
            "content_encrypted",
            "content_hash",
            "credentials",
            "api_key",
            "token",
            "secret",
            "secret_key",
            "raw_payload",
            "payload_json",
            "metadata_json",
        ):
            self.assertNotIn(field, response_schema_text)

    def test_admin_web_tenant_product_create_uses_cookie_session_and_safe_schema(self) -> None:
        schema = app.openapi()
        path = "/api/v1/admin-web/tenant/products"
        operation = schema["paths"][path]["post"]

        self.assertNotIn("security", operation)
        self.assertNotIn("x-fakabot-signature", operation)
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertTrue(
            {
                "authorization",
                "X-API-Key",
                "X-Platform-API-Key",
                "X-Faka-Timestamp",
                "X-Faka-Signature",
            }.isdisjoint(header_names)
        )

        path_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "path"
        }
        self.assertEqual(set(), path_names)

        request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        request_schema_name = request_ref.rsplit("/", 1)[-1]
        request_schema = schema["components"]["schemas"][request_schema_name]
        request_properties = request_schema.get("properties", {})
        self.assertEqual("AdminWebProductCreateRequest", request_schema_name)
        self.assertEqual(
            {"name", "price", "delivery_type", "description", "category"},
            set(request_properties),
        )
        self.assertFalse(request_schema.get("additionalProperties", True))

        response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        response_schema_name = response_ref.rsplit("/", 1)[-1]
        response_schema = schema["components"]["schemas"][response_schema_name]
        response_properties = response_schema.get("properties", {})
        self.assertEqual("AdminWebTenantProductItemResponse", response_schema_name)
        self.assertEqual(
            {
                "product_id",
                "name",
                "category",
                "sort_order",
                "status",
                "delivery_type",
                "price",
                "currency",
                "available_count",
            },
            set(response_properties),
        )

        request_schema_text = str(request_schema).lower()
        for field in (
            "tenant_id",
            "tenant_bot_id",
            "workspace_id",
            "supplier_tenant_id",
            "reseller_tenant_id",
            "product_type",
            "status",
            "review_status",
            "currency",
            "sort_order",
            "external_source",
            "source_key",
            "external_id",
            "variant_id",
            "product_variant_id",
            "delivery_file_id",
            "telegram_chat_id",
            "file_size_limit",
            "storage_key",
            "content_encrypted",
            "content_hash",
            "credentials",
            "api_key",
            "token",
            "secret",
            "secret_key",
            "raw_payload",
            "payload_json",
            "metadata_json",
        ):
            self.assertNotIn(field, request_schema_text)

        response_schema_text = str(response_schema).lower()
        for field in (
            "tenant_id",
            "tenant_bot_id",
            "workspace_id",
            "supplier_tenant_id",
            "reseller_tenant_id",
            "product_type",
            "external_source",
            "source_key",
            "external_id",
            "description",
            "cover_url",
            "review_status",
            "variant_id",
            "product_variant_id",
            "delivery_file_id",
            "telegram_chat_id",
            "file_size_limit",
            "storage_key",
            "content_encrypted",
            "content_hash",
            "credentials",
            "api_key",
            "token",
            "secret",
            "secret_key",
            "raw_payload",
            "payload_json",
            "metadata_json",
        ):
            self.assertNotIn(field, response_schema_text)

    def test_admin_web_tenant_product_price_status_uses_cookie_session_and_safe_schema(self) -> None:
        schema = app.openapi()
        path = "/api/v1/admin-web/tenant/products/{product_id}/sales"
        operation = schema["paths"][path]["patch"]

        self.assertNotIn("security", operation)
        self.assertNotIn("x-fakabot-signature", operation)
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertTrue(
            {
                "authorization",
                "X-API-Key",
                "X-Platform-API-Key",
                "X-Faka-Timestamp",
                "X-Faka-Signature",
            }.isdisjoint(header_names)
        )

        path_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "path"
        }
        self.assertEqual({"product_id"}, path_names)

        request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        request_schema_name = request_ref.rsplit("/", 1)[-1]
        request_schema = schema["components"]["schemas"][request_schema_name]
        request_properties = request_schema.get("properties", {})
        self.assertEqual("AdminWebProductSalesRequest", request_schema_name)
        self.assertEqual({"price", "status"}, set(request_properties))
        self.assertFalse(request_schema.get("additionalProperties", True))

        response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        response_schema_name = response_ref.rsplit("/", 1)[-1]
        response_schema = schema["components"]["schemas"][response_schema_name]
        response_properties = response_schema.get("properties", {})
        self.assertEqual("AdminWebTenantProductItemResponse", response_schema_name)
        self.assertEqual(
            {
                "product_id",
                "name",
                "category",
                "sort_order",
                "status",
                "delivery_type",
                "price",
                "currency",
                "available_count",
            },
            set(response_properties),
        )

        request_schema_text = str(request_schema).lower()
        for field in (
            "tenant_id",
            "tenant_bot_id",
            "workspace_id",
            "supplier_tenant_id",
            "reseller_tenant_id",
            "product_type",
            "delivery_type",
            "external_source",
            "source_key",
            "external_id",
            "variant_id",
            "product_variant_id",
            "delivery_file_id",
            "storage_key",
            "content",
            "credentials",
            "api_key",
            "token",
            "secret",
            "secret_key",
            "raw_payload",
            "payload_json",
            "metadata_json",
        ):
            self.assertNotIn(field, request_schema_text)

        response_schema_text = str(response_schema).lower()
        for field in (
            "tenant_id",
            "tenant_bot_id",
            "workspace_id",
            "supplier_tenant_id",
            "reseller_tenant_id",
            "product_type",
            "variant_id",
            "product_variant_id",
            "delivery_file_id",
            "storage_key",
            "content_encrypted",
            "content_hash",
            "credentials",
            "api_key",
            "token",
            "secret",
            "secret_key",
            "raw_payload",
            "payload_json",
            "metadata_json",
        ):
            self.assertNotIn(field, response_schema_text)

    def test_admin_web_tenant_product_batch_status_uses_cookie_session_and_safe_schema(self) -> None:
        schema = app.openapi()
        path = "/api/v1/admin-web/tenant/products/status"
        operation = schema["paths"][path]["patch"]

        self.assertNotIn("security", operation)
        self.assertNotIn("x-fakabot-signature", operation)
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertTrue(
            {
                "authorization",
                "X-API-Key",
                "X-Platform-API-Key",
                "X-Faka-Timestamp",
                "X-Faka-Signature",
            }.isdisjoint(header_names)
        )

        path_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "path"
        }
        self.assertEqual(set(), path_names)

        request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        request_schema_name = request_ref.rsplit("/", 1)[-1]
        request_schema = schema["components"]["schemas"][request_schema_name]
        request_properties = request_schema.get("properties", {})
        self.assertEqual("AdminWebProductBatchStatusRequest", request_schema_name)
        self.assertEqual({"product_ids", "status"}, set(request_properties))
        self.assertFalse(request_schema.get("additionalProperties", True))

        response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        response_schema_name = response_ref.rsplit("/", 1)[-1]
        response_schema = schema["components"]["schemas"][response_schema_name]
        response_properties = response_schema.get("properties", {})
        self.assertEqual("AdminWebTenantProductBatchStatusResponse", response_schema_name)
        self.assertEqual({"status", "updated_count", "products"}, set(response_properties))

        product_schema = schema["components"]["schemas"]["AdminWebTenantProductItemResponse"]
        self.assertEqual(
            {
                "product_id",
                "name",
                "category",
                "sort_order",
                "status",
                "delivery_type",
                "price",
                "currency",
                "available_count",
            },
            set(product_schema.get("properties", {})),
        )

        request_schema_text = str(request_schema).lower()
        for field in (
            "tenant_id",
            "tenant_bot_id",
            "workspace_id",
            "supplier_tenant_id",
            "reseller_tenant_id",
            "price",
            "delivery_type",
            "external_source",
            "source_key",
            "external_id",
            "variant_id",
            "product_variant_id",
            "delivery_file_id",
            "storage_key",
            "content",
            "credentials",
            "api_key",
            "token",
            "secret",
            "secret_key",
            "raw_payload",
            "payload_json",
            "metadata_json",
        ):
            self.assertNotIn(field, request_schema_text)

        response_schema_text = str(response_schema).lower()
        product_schema_text = str(product_schema).lower()
        for field in (
            "tenant_id",
            "tenant_bot_id",
            "workspace_id",
            "supplier_tenant_id",
            "reseller_tenant_id",
            "product_type",
            "variant_id",
            "product_variant_id",
            "delivery_file_id",
            "storage_key",
            "content_encrypted",
            "content_hash",
            "credentials",
            "api_key",
            "token",
            "secret",
            "secret_key",
            "raw_payload",
            "payload_json",
            "metadata_json",
        ):
            self.assertNotIn(field, response_schema_text)
            self.assertNotIn(field, product_schema_text)

    def test_admin_web_tenant_product_inventory_import_uses_cookie_session_and_safe_schema(self) -> None:
        schema = app.openapi()
        path = "/api/v1/admin-web/tenant/products/{product_id}/inventory/import"
        operation = schema["paths"][path]["post"]

        self.assertNotIn("security", operation)
        self.assertNotIn("x-fakabot-signature", operation)
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertTrue(
            {
                "authorization",
                "X-API-Key",
                "X-Platform-API-Key",
                "X-Faka-Timestamp",
                "X-Faka-Signature",
            }.isdisjoint(header_names)
        )

        path_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "path"
        }
        self.assertEqual({"product_id"}, path_names)

        request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        request_schema_name = request_ref.rsplit("/", 1)[-1]
        request_schema = schema["components"]["schemas"][request_schema_name]
        request_properties = request_schema.get("properties", {})
        self.assertEqual("AdminWebProductInventoryImportRequest", request_schema_name)
        self.assertEqual({"items"}, set(request_properties))
        self.assertFalse(request_schema.get("additionalProperties", True))

        response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        response_schema_name = response_ref.rsplit("/", 1)[-1]
        response_schema = schema["components"]["schemas"][response_schema_name]
        response_properties = response_schema.get("properties", {})
        self.assertEqual("AdminWebProductInventoryImportResponse", response_schema_name)
        self.assertEqual(
            {
                "product_id",
                "added_count",
                "existing_count",
                "input_duplicate_count",
                "available_count",
            },
            set(response_properties),
        )

        request_schema_text = str(request_schema).lower()
        for field in (
            "tenant_id",
            "tenant_bot_id",
            "workspace_id",
            "supplier_tenant_id",
            "reseller_tenant_id",
            "variant_id",
            "product_variant_id",
            "inventory_id",
            "inventory_item_id",
            "content_encrypted",
            "content_hash",
            "storage_key",
            "credentials",
            "api_key",
            "token",
            "secret",
            "secret_key",
            "raw_payload",
            "payload_json",
            "metadata_json",
        ):
            self.assertNotIn(field, request_schema_text)

        response_schema_text = str(response_schema).lower()
        for field in (
            "tenant_id",
            "tenant_bot_id",
            "workspace_id",
            "supplier_tenant_id",
            "reseller_tenant_id",
            "variant_id",
            "product_variant_id",
            "inventory_id",
            "inventory_item_id",
            "content",
            "content_encrypted",
            "content_hash",
            "storage_key",
            "credentials",
            "api_key",
            "token",
            "secret",
            "secret_key",
            "raw_payload",
            "payload_json",
            "metadata_json",
        ):
            self.assertNotIn(field, response_schema_text)

    def test_admin_web_tenant_product_delivery_file_upload_uses_cookie_session_and_safe_schema(self) -> None:
        schema = app.openapi()
        path = "/api/v1/admin-web/tenant/products/{product_id}/delivery-file"
        operation = schema["paths"][path]["post"]

        self.assertNotIn("security", operation)
        self.assertNotIn("x-fakabot-signature", operation)
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertTrue(
            {
                "authorization",
                "X-API-Key",
                "X-Platform-API-Key",
                "X-Faka-Timestamp",
                "X-Faka-Signature",
            }.isdisjoint(header_names)
        )

        path_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "path"
        }
        self.assertEqual({"product_id"}, path_names)
        query_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "query"
        }
        self.assertNotIn("tenant_id", query_names)
        self.assertNotIn("workspace_id", query_names)

        request_content = operation["requestBody"]["content"]
        self.assertEqual({"multipart/form-data"}, set(request_content))
        request_ref = request_content["multipart/form-data"]["schema"]["$ref"]
        request_schema_name = request_ref.rsplit("/", 1)[-1]
        request_schema = schema["components"]["schemas"][request_schema_name]
        request_properties = request_schema.get("properties", {})
        self.assertEqual({"file"}, set(request_properties))
        self.assertEqual(["file"], request_schema.get("required"))

        response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        response_schema_name = response_ref.rsplit("/", 1)[-1]
        response_schema = schema["components"]["schemas"][response_schema_name]
        response_properties = response_schema.get("properties", {})
        self.assertEqual("AdminWebProductDeliveryFileResponse", response_schema_name)
        self.assertEqual(
            {
                "product_id",
                "filename",
                "size_bytes",
                "content_type",
                "risk_level",
                "scan_message",
                "bound",
            },
            set(response_properties),
        )

        request_schema_text = str(request_schema).lower()
        response_schema_text = str(response_schema).lower()
        for field in (
            "tenant_id",
            "tenant_bot_id",
            "workspace_id",
            "supplier_tenant_id",
            "reseller_tenant_id",
            "delivery_file_id",
            "uploaded_file_id",
            "storage_key",
            "sha256",
            "owner_user_id",
            "status",
            "file_size_limit",
            "raw_payload",
            "payload_json",
            "credentials",
            "api_key",
            "token",
            "secret",
            "secret_key",
        ):
            self.assertNotIn(field, request_schema_text)
            self.assertNotIn(field, response_schema_text)

    def test_admin_web_tenant_payment_config_routes_use_cookie_session_without_api_key_security(self) -> None:
        schema = app.openapi()

        for method, path in (
            ("get", "/api/v1/admin-web/tenant/payments/configs"),
            ("put", "/api/v1/admin-web/tenant/payments/{provider_name}/config"),
            ("delete", "/api/v1/admin-web/tenant/payments/{provider_name}/config"),
        ):
            operation = schema["paths"][path][method]
            with self.subTest(method=method, path=path):
                self.assertNotIn("security", operation)
                self.assertNotIn("x-fakabot-signature", operation)
                header_names = {
                    parameter["name"]
                    for parameter in operation.get("parameters", [])
                    if parameter.get("in") == "header"
                }
                self.assertTrue(
                    {
                        "authorization",
                        "X-API-Key",
                        "X-Platform-API-Key",
                        "X-Faka-Timestamp",
                        "X-Faka-Signature",
                    }.isdisjoint(header_names)
                )

    def test_admin_web_tenant_payment_config_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        request_schema = schema["components"]["schemas"]["AdminWebPaymentConfigRequest"]
        request_properties = request_schema.get("properties", {})
        self.assertFalse(request_schema.get("additionalProperties", True))
        self.assertEqual(
            {
                "gateway_url",
                "base_url",
                "merchant_id",
                "pid",
                "key",
                "secret_key",
                "token",
                "network",
                "payment_type",
                "device",
                "return_url",
                "subject",
            },
            set(request_properties),
        )
        request_schema_text = str(request_schema).lower()
        for forbidden in (
            "tenant_id",
            "workspace_id",
            "scope_type",
            "enabled",
            "key_configured",
            "config_encrypted",
            "credentials",
            "credentials_encrypted",
            "payment_url",
            "provider_trade_no",
            "raw_payload",
            "payload_json",
        ):
            self.assertNotIn(forbidden, request_schema_text)

        item_schema = schema["components"]["schemas"]["AdminWebTenantPaymentProviderConfigItemResponse"]
        item_properties = item_schema.get("properties", {})
        self.assertEqual(
            {
                "provider",
                "display_name",
                "enabled",
                "scope_type",
                "gateway_url",
                "merchant_id_masked",
                "asset",
                "network",
                "payment_type",
                "device",
                "return_url_configured",
                "subject",
                "key_configured",
                "create_payment_available",
                "callback_available",
                "query_order_available",
                "reconcile_available",
                "production_ready",
                "staging_verified",
                "offline_only",
            },
            set(item_properties),
        )
        item_schema_text = str(item_schema).lower()
        self.assertNotIn("merchant_id", set(item_properties) - {"merchant_id_masked"})
        for forbidden in (
            "tenant_id",
            "workspace_id",
            "monitor_address",
            "secret_key",
            "api_key",
            "credentials",
            "credentials_encrypted",
            "config_encrypted",
            "payment_url",
            "provider_trade_no",
            "signature",
            "signing_text",
            "raw_payload",
            "payload_json",
        ):
            self.assertNotIn(forbidden, item_schema_text)

        list_schema = schema["components"]["schemas"]["AdminWebTenantPaymentProviderConfigsResponse"]
        self.assertEqual({"providers"}, set(list_schema.get("properties", {})))

    def test_admin_web_tenant_supply_routes_use_cookie_session_without_api_key_security(self) -> None:
        schema = app.openapi()

        for method, path in (
            ("get", "/api/v1/admin-web/tenant/supply/dashboard"),
            ("post", "/api/v1/admin-web/tenant/supply/applications"),
            ("post", "/api/v1/admin-web/tenant/supply/supplier-offers"),
            ("patch", "/api/v1/admin-web/tenant/supply/supplier-offers/{supplier_offer_id}/approval"),
            ("post", "/api/v1/admin-web/tenant/supply/supplier-rules"),
            ("post", "/api/v1/admin-web/tenant/supply/supplier-applications/review"),
            ("post", "/api/v1/admin-web/tenant/supply/reseller-products"),
            ("patch", "/api/v1/admin-web/tenant/supply/reseller-products/{reseller_product_id}/metadata"),
            ("patch", "/api/v1/admin-web/tenant/supply/reseller-products/{reseller_product_id}/sales"),
        ):
            operation = schema["paths"][path][method]
            with self.subTest(method=method, path=path):
                self.assertNotIn("security", operation)
                self.assertNotIn("x-fakabot-signature", operation)
                header_names = {
                    parameter["name"]
                    for parameter in operation.get("parameters", [])
                    if parameter.get("in") == "header"
                }
                self.assertTrue(
                    {
                        "authorization",
                        "X-API-Key",
                        "X-Platform-API-Key",
                        "X-Faka-Timestamp",
                        "X-Faka-Signature",
                    }.isdisjoint(header_names)
                )
                response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
                schema_name = response_ref.rsplit("/", 1)[-1]
                response_schema = schema["components"]["schemas"][schema_name]
                response_properties = response_schema.get("properties", {})
                response_schema_text = str(response_schema).lower()
                for forbidden in (
                    "tenant_id",
                    "tenant_bot_id",
                    "supplier_tenant_id",
                    "reseller_tenant_id",
                    "owner_user_id",
                    "bot_user_id",
                    "self_product_id",
                    "locked_inventory_item_id",
                    "variant_id",
                    "encrypted_token",
                    "token_hash",
                    "webhook_secret",
                    "api_key",
                    "secret",
                    "storage_key",
                    "content_hash",
                    "raw_payload",
                    "payload_json",
                ):
                    self.assertNotIn(forbidden, response_schema_text)
                self.assertNotIn("rule_id", response_properties)

                request_body = operation.get("requestBody", {})
                if request_body:
                    request_ref = request_body["content"]["application/json"]["schema"]["$ref"]
                    request_schema_name = request_ref.rsplit("/", 1)[-1]
                    request_schema = schema["components"]["schemas"][request_schema_name]
                    self.assertFalse(request_schema.get("additionalProperties", True))
                    self.assertNotIn("rule_id", request_schema.get("properties", {}))
                    request_schema_text = str(request_schema).lower()
                    for forbidden in ("tenant_id", "supplier_tenant_id", "reseller_tenant_id", "api_key", "secret"):
                        self.assertNotIn(forbidden, request_schema_text)

    def test_admin_web_tenant_supply_dashboard_filter_params_are_cookie_scoped_query_only(self) -> None:
        schema = app.openapi()
        operation = schema["paths"]["/api/v1/admin-web/tenant/supply/dashboard"]["get"]

        query_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "query"
        }
        self.assertEqual(
            {
                "limit",
                "market_query",
                "market_delivery_type",
                "market_access",
                "market_min_price",
                "market_max_price",
                "market_stock",
                "market_category",
            },
            query_names,
        )
        for forbidden in (
            "tenant_id",
            "supplier_tenant_id",
            "reseller_tenant_id",
            "product_id",
            "variant_id",
            "inventory_id",
            "inventory_item_id",
            "storage_key",
            "credentials",
            "api_key",
            "token",
            "secret",
        ):
            self.assertNotIn(forbidden, query_names)

    def test_admin_web_supply_market_offer_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        item = schema["components"]["schemas"]["AdminWebSupplyMarketOfferItemResponse"]["properties"]

        self.assertEqual(
            {
                "supplier_offer_id",
                "product_name",
                "category",
                "delivery_type",
                "suggested_price",
                "min_sale_price",
                "currency",
                "available_count",
                "requires_approval",
                "reseller_rule_status",
                "can_create_reseller_product",
                "supplier_cost",
                "effective_min_sale_price",
            },
            set(item),
        )
        for forbidden in (
            "tenant_id",
            "supplier_tenant_id",
            "reseller_tenant_id",
            "product_id",
            "variant_id",
            "inventory_id",
            "inventory_item_id",
            "storage_key",
            "content",
            "credentials",
            "api_key",
            "token",
            "secret",
            "raw_payload",
            "payload_json",
        ):
            self.assertNotIn(forbidden, item)

    def test_admin_web_reseller_product_metadata_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        path = "/api/v1/admin-web/tenant/supply/reseller-products/{reseller_product_id}/metadata"
        operation = schema["paths"][path]["patch"]

        path_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "path"
        }
        self.assertEqual({"reseller_product_id"}, path_names)

        request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        request_schema_name = request_ref.rsplit("/", 1)[-1]
        request_schema = schema["components"]["schemas"][request_schema_name]
        request_properties = request_schema.get("properties", {})
        self.assertEqual("AdminWebResellerProductMetadataRequest", request_schema_name)
        self.assertEqual({"category", "sort_order"}, set(request_properties))
        self.assertFalse(request_schema.get("additionalProperties", True))

        response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        response_schema_name = response_ref.rsplit("/", 1)[-1]
        response_schema = schema["components"]["schemas"][response_schema_name]
        response_properties = response_schema.get("properties", {})
        self.assertEqual("AdminWebResellerProductItemResponse", response_schema_name)
        self.assertEqual(
            {
                "reseller_product_id",
                "supplier_offer_id",
                "display_name",
                "category",
                "sort_order",
                "delivery_type",
                "sale_price",
                "currency",
                "status",
                "available_count",
            },
            set(response_properties),
        )

        request_schema_text = str(request_schema).lower()
        response_schema_text = str(response_schema).lower()
        self.assertNotIn("product_id", set(response_properties))
        self.assertNotIn("variant_id", set(response_properties))
        for forbidden in (
            "tenant_id",
            "supplier_tenant_id",
            "reseller_tenant_id",
            "rule_id",
            "supplier_rule_id",
            "hide_supplier",
            "hidden_supplier_allowed",
            "storage_key",
            "credentials",
            "api_key",
            "token",
            "secret",
            "raw_payload",
            "payload_json",
        ):
            self.assertNotIn(forbidden, request_schema_text)
            self.assertNotIn(forbidden, response_schema_text)

    def test_admin_web_reseller_product_sales_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        path = "/api/v1/admin-web/tenant/supply/reseller-products/{reseller_product_id}/sales"
        operation = schema["paths"][path]["patch"]

        path_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "path"
        }
        self.assertEqual({"reseller_product_id"}, path_names)

        request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        request_schema_name = request_ref.rsplit("/", 1)[-1]
        request_schema = schema["components"]["schemas"][request_schema_name]
        request_properties = request_schema.get("properties", {})
        self.assertEqual("AdminWebResellerProductSalesRequest", request_schema_name)
        self.assertEqual({"display_name", "sale_price"}, set(request_properties))
        self.assertFalse(request_schema.get("additionalProperties", True))

        response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        response_schema_name = response_ref.rsplit("/", 1)[-1]
        response_schema = schema["components"]["schemas"][response_schema_name]
        response_properties = response_schema.get("properties", {})
        self.assertEqual("AdminWebResellerProductItemResponse", response_schema_name)
        self.assertEqual(
            {
                "reseller_product_id",
                "supplier_offer_id",
                "display_name",
                "category",
                "sort_order",
                "delivery_type",
                "sale_price",
                "currency",
                "status",
                "available_count",
            },
            set(response_properties),
        )

        request_schema_text = str(request_schema).lower()
        response_schema_text = str(response_schema).lower()
        for forbidden in (
            "tenant_id",
            "supplier_tenant_id",
            "reseller_tenant_id",
            "rule_id",
            "supplier_rule_id",
            "hide_supplier",
            "hidden_supplier_allowed",
            "storage_key",
            "credentials",
            "api_key",
            "token",
            "secret",
            "raw_payload",
            "payload_json",
        ):
            self.assertNotIn(forbidden, request_schema_text)
            self.assertNotIn(forbidden, response_schema_text)

    def test_inventory_import_operation_is_documented_as_tenant_admin(self) -> None:
        schema = app.openapi()
        operation = schema["paths"]["/api/v1/tenant/products/{product_id}/inventory/import"]["post"]

        self.assertEqual(
            [{"TenantAdminBearer": []}, {"TenantAdminApiKeyHeader": []}],
            operation["security"],
        )

    def test_product_sync_operation_is_documented_as_tenant_admin(self) -> None:
        schema = app.openapi()
        operation = schema["paths"]["/api/v1/tenant/products/sync"]["post"]

        self.assertEqual(
            [{"TenantAdminBearer": []}, {"TenantAdminApiKeyHeader": []}],
            operation["security"],
        )

    def test_external_catalog_sync_operation_is_documented_as_tenant_admin(self) -> None:
        schema = app.openapi()
        operation = schema["paths"]["/api/v1/tenant/external-sources/{provider_name}/catalog/sync"]["post"]

        self.assertEqual(
            [{"TenantAdminBearer": []}, {"TenantAdminApiKeyHeader": []}],
            operation["security"],
        )
        header_names = {
            parameter["name"]
            for parameter in operation["parameters"]
            if parameter.get("in") == "header"
        }
        self.assertIn("X-Faka-Timestamp", header_names)
        self.assertIn("X-Faka-Signature", header_names)

    def test_external_catalog_product_sync_operation_is_documented_as_tenant_admin(self) -> None:
        schema = app.openapi()
        operation = schema["paths"]["/api/v1/tenant/external-sources/{provider_name}/catalog/products/sync"]["post"]

        self.assertEqual(
            [{"TenantAdminBearer": []}, {"TenantAdminApiKeyHeader": []}],
            operation["security"],
        )
        header_names = {
            parameter["name"]
            for parameter in operation["parameters"]
            if parameter.get("in") == "header"
        }
        self.assertIn("X-Faka-Timestamp", header_names)
        self.assertIn("X-Faka-Signature", header_names)
        path_names = {
            parameter["name"]
            for parameter in operation["parameters"]
            if parameter.get("in") == "path"
        }
        self.assertEqual({"provider_name"}, path_names)

    def test_external_order_operations_are_documented_as_tenant_admin(self) -> None:
        schema = app.openapi()

        for method, path in [
            ("post", "/api/v1/tenant/external-sources/{provider_name}/orders"),
            ("get", "/api/v1/tenant/external-sources/{provider_name}/orders/{external_order_id}"),
            ("get", "/api/v1/tenant/external-sources/{provider_name}/orders/{external_order_id}/delivery"),
            ("post", "/api/v1/tenant/orders/{out_trade_no}/external-delivery/import"),
            ("get", "/api/v1/tenant/orders/{out_trade_no}/diagnostics"),
            ("get", "/api/v1/tenant/audit-logs"),
            ("get", "/api/v1/tenant/risk/disputes"),
            ("get", "/api/v1/tenant/risk/after-sales"),
            ("get", "/api/v1/tenant/reports/export-jobs"),
            ("get", "/api/v1/tenant/external-fulfillment/attempts"),
            ("get", "/api/v1/tenant/external-fulfillment/failures"),
        ]:
            operation = schema["paths"][path][method]
            self.assertEqual(
                [{"TenantAdminBearer": []}, {"TenantAdminApiKeyHeader": []}],
                operation["security"],
            )
            header_names = {
                parameter["name"]
                for parameter in operation["parameters"]
                if parameter.get("in") == "header"
            }
            self.assertIn("X-Faka-Timestamp", header_names)
            self.assertIn("X-Faka-Signature", header_names)

    def test_tenant_audit_log_operation_is_documented_as_tenant_admin(self) -> None:
        schema = app.openapi()
        operation = schema["paths"]["/api/v1/tenant/audit-logs"]["get"]

        self.assertEqual(
            [{"TenantAdminBearer": []}, {"TenantAdminApiKeyHeader": []}],
            operation["security"],
        )
        header_names = {
            parameter["name"]
            for parameter in operation["parameters"]
            if parameter.get("in") == "header"
        }
        self.assertIn("X-Faka-Timestamp", header_names)
        self.assertIn("X-Faka-Signature", header_names)

    def test_report_export_jobs_operation_is_documented_as_tenant_admin(self) -> None:
        schema = app.openapi()
        operation = schema["paths"]["/api/v1/tenant/reports/export-jobs"]["get"]

        self.assertEqual(
            [{"TenantAdminBearer": []}, {"TenantAdminApiKeyHeader": []}],
            operation["security"],
        )
        header_names = {
            parameter["name"]
            for parameter in operation["parameters"]
            if parameter.get("in") == "header"
        }
        self.assertIn("X-Faka-Timestamp", header_names)
        self.assertIn("X-Faka-Signature", header_names)

    def test_create_report_export_job_operation_is_documented_as_tenant_admin(self) -> None:
        schema = app.openapi()
        path = "/api/v1/tenant/reports/export-jobs"
        operation = schema["paths"][path]["post"]
        request_schema_name = (
            operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
        )
        success_response = operation["responses"].get("200") or operation["responses"].get("201")
        self.assertIsNotNone(success_response)
        response_schema_name = (
            success_response["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
        )

        self.assertEqual(
            [{"TenantAdminBearer": []}, {"TenantAdminApiKeyHeader": []}],
            operation["security"],
        )
        header_names = {
            parameter["name"]
            for parameter in operation["parameters"]
            if parameter.get("in") == "header"
        }
        self.assertIn("X-Faka-Timestamp", header_names)
        self.assertIn("X-Faka-Signature", header_names)
        self.assertEqual("CreateTenantReportExportJobRequest", request_schema_name)
        self.assertIn(
            response_schema_name,
            {"TenantReportExportJobItem", "CreateTenantReportExportJobResponse"},
        )

    def test_external_sources_list_operation_is_documented_as_tenant_admin(self) -> None:
        schema = app.openapi()
        operation = schema["paths"]["/api/v1/tenant/external-sources"]["get"]

        self.assertEqual(
            [{"TenantAdminBearer": []}, {"TenantAdminApiKeyHeader": []}],
            operation["security"],
        )

    def test_external_source_connection_operations_are_documented_as_tenant_admin(self) -> None:
        schema = app.openapi()

        for method, path in [
            ("get", "/api/v1/tenant/external-source-connections"),
            ("post", "/api/v1/tenant/external-source-connections"),
            ("get", "/api/v1/tenant/external-source-connections/{connection_id}"),
            ("delete", "/api/v1/tenant/external-source-connections/{connection_id}"),
        ]:
            operation = schema["paths"][path][method]
            self.assertEqual(
                [{"TenantAdminBearer": []}, {"TenantAdminApiKeyHeader": []}],
                operation["security"],
            )

    def test_product_sync_schema_exposes_external_mapping_fields(self) -> None:
        schema = app.openapi()
        sync_item = schema["components"]["schemas"]["SyncProductItem"]["properties"]
        synced_item = schema["components"]["schemas"]["SyncedProductItem"]["properties"]
        admin_product = schema["components"]["schemas"]["AdminProduct"]["properties"]

        self.assertIn("external_source", sync_item)
        self.assertIn("source_key", sync_item)
        self.assertIn("external_id", sync_item)
        self.assertIn("category", sync_item)
        self.assertIn("external_source", synced_item)
        self.assertIn("source_key", synced_item)
        self.assertIn("external_id", synced_item)
        self.assertIn("external_source", admin_product)
        self.assertIn("source_key", admin_product)
        self.assertIn("external_id", admin_product)
        self.assertIn("category", admin_product)

    def test_product_metadata_update_operation_is_documented_as_tenant_admin(self) -> None:
        schema = app.openapi()
        path = "/api/v1/tenant/products/{product_id}/metadata"
        operation = schema["paths"][path]["patch"]
        request_schema_name = (
            operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
        )
        success_response = operation["responses"].get("200") or operation["responses"].get("201")
        self.assertIsNotNone(success_response)
        response_schema_name = (
            success_response["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
        )
        request_schema = schema["components"]["schemas"]["UpdateProductMetadataRequest"]
        request = request_schema["properties"]
        response = schema["components"]["schemas"][response_schema_name]["properties"]
        forbidden = {"credentials", "raw_payload", "token", "secret"}

        self.assertEqual(
            [{"TenantAdminBearer": []}, {"TenantAdminApiKeyHeader": []}],
            operation["security"],
        )
        header_names = {
            parameter["name"]
            for parameter in operation["parameters"]
            if parameter.get("in") == "header"
        }
        path_names = {
            parameter["name"]
            for parameter in operation["parameters"]
            if parameter.get("in") == "path"
        }
        self.assertIn("X-Faka-Timestamp", header_names)
        self.assertIn("X-Faka-Signature", header_names)
        self.assertEqual({"product_id"}, path_names)
        self.assertEqual("HMAC-SHA256", operation["x-fakabot-signature"]["algorithm"])
        self.assertEqual(
            "TENANT_ADMIN_REQUIRE_SIGNATURE",
            operation["x-fakabot-signature"]["requiredByConfig"],
        )
        self.assertEqual("UpdateProductMetadataRequest", request_schema_name)
        self.assertIn(response_schema_name, {"ProductMetadataResponse", "AdminProduct"})
        self.assertEqual({"category", "sort_order"}, set(request))
        self.assertFalse(request_schema.get("additionalProperties", True))
        self.assertIn("sort_order", request)
        self.assertIn("category", request)
        self.assertIn("sort_order", response)
        self.assertIn("category", response)
        self.assertTrue(forbidden.isdisjoint(request))
        self.assertTrue(forbidden.isdisjoint(response))

    def test_external_catalog_sync_schema_exposes_safe_summary_fields(self) -> None:
        schema = app.openapi()
        request = schema["components"]["schemas"]["SyncExternalCatalogRequest"]["properties"]
        response = schema["components"]["schemas"]["SyncExternalCatalogResponse"]["properties"]
        product = schema["components"]["schemas"]["SyncedExternalCatalogProduct"]["properties"]

        self.assertIn("connection_id", request)
        self.assertIn("source_key", request)
        self.assertIn("cursor", request)
        self.assertIn("limit", request)
        self.assertIn("max_pages", request)
        self.assertNotIn("credentials", request)
        self.assertNotIn("credentials_encrypted", request)
        self.assertNotIn("token", request)
        self.assertNotIn("secret", request)
        self.assertNotIn("api_key", request)
        self.assertNotIn("password", request)
        self.assertIn("provider_name", response)
        self.assertIn("connection_id", response)
        self.assertIn("created_count", response)
        self.assertIn("updated_count", response)
        self.assertIn("skipped_count", response)
        self.assertIn("next_cursor", response)
        self.assertIn("products", response)
        self.assertNotIn("credentials", response)
        self.assertNotIn("credentials_encrypted", response)
        self.assertNotIn("token", response)
        self.assertNotIn("secret", response)
        self.assertIn("product_id", product)
        self.assertIn("external_source", product)
        self.assertIn("source_key", product)
        self.assertIn("external_id", product)
        self.assertIn("action", product)
        self.assertIn("status", product)
        self.assertIn("skipped_reason", product)
        self.assertNotIn("raw_payload", product)
        self.assertNotIn("content", product)
        self.assertNotIn("key_hash", product)

    def test_external_order_operation_schemas_expose_safe_fields(self) -> None:
        schema = app.openapi()
        request = schema["components"]["schemas"]["CreateExternalOrderRequest"]["properties"]
        order = schema["components"]["schemas"]["ExternalOrderResponse"]["properties"]
        delivery = schema["components"]["schemas"]["ExternalDeliveryResponse"]["properties"]
        import_request = schema["components"]["schemas"]["ImportExternalDeliveryRequest"]["properties"]
        import_response = schema["components"]["schemas"]["ImportExternalDeliveryResponse"]["properties"]
        retry_response = schema["components"]["schemas"]["RetryExternalFulfillmentResponse"]["properties"]

        self.assertIn("external_product_id", request)
        self.assertIn("quantity", request)
        self.assertIn("connection_id", request)
        self.assertIn("source_key", request)
        self.assertIn("metadata", request)
        self.assertIn("external_order_id", order)
        self.assertIn("external_product_id", order)
        self.assertIn("delivery_ready", order)
        self.assertIn("delivery_type", delivery)
        self.assertIn("items", delivery)
        self.assertIn("provider_name", import_request)
        self.assertIn("external_order_id", import_request)
        self.assertIn("connection_id", import_request)
        self.assertIn("source_key", import_request)
        self.assertIn("dry_run", import_request)
        self.assertEqual(
            {"out_trade_no", "order_status", "delivery_record_id", "item_count", "imported", "dry_run"},
            set(import_response),
        )
        for forbidden in ("credentials", "credentials_encrypted", "token", "secret", "api_key", "password"):
            self.assertNotIn(forbidden, order)
            self.assertNotIn(forbidden, delivery)
            self.assertNotIn(forbidden, import_request)
            self.assertNotIn(forbidden, import_response)
        self.assertNotIn("raw_payload", order)
        self.assertNotIn("raw_payload", delivery)
        self.assertNotIn("content", order)
        self.assertNotIn("key_hash", order)
        for forbidden in ("items", "message", "delivery_type", "raw_payload", "content", "key_hash"):
            self.assertNotIn(forbidden, import_response)
        self.assertEqual(
            {
                "out_trade_no",
                "provider_name",
                "source_key",
                "external_order_id",
                "delivery_record_id",
                "item_count",
                "imported",
                "attempt_status",
                "failure_stage",
                "failure_category",
                "failure_retryable",
                "upstream_status_code",
                "failure_recorded",
            },
            set(retry_response),
        )
        for forbidden in (
            "credentials",
            "credentials_encrypted",
            "token",
            "secret",
            "api_key",
            "password",
            "raw_payload",
            "payload",
            "items",
            "message",
            "delivery_type",
            "content",
            "key_hash",
        ):
            self.assertNotIn(forbidden, retry_response)

    def test_external_fulfillment_failure_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        response = schema["components"]["schemas"]["ListExternalFulfillmentFailuresResponse"]["properties"]
        item = schema["components"]["schemas"]["ExternalFulfillmentFailureItem"]["properties"]

        self.assertIn("failures", response)
        expected_fields = {
            "audit_log_id",
            "created_at",
            "order_id",
            "out_trade_no",
            "product_id",
            "provider_name",
            "source_key",
            "external_product_id",
            "connection_id",
            "external_order_id",
            "failure_reason",
            "failure_stage",
            "failure_category",
            "failure_retryable",
            "upstream_status_code",
            "failure_fingerprint",
        }
        self.assertEqual(expected_fields, set(item))
        for forbidden in (
            "metadata_json",
            "credentials",
            "credentials_encrypted",
            "token",
            "secret",
            "api_key",
            "password",
            "raw_payload",
            "payload",
            "content",
            "items",
            "message",
        ):
            self.assertNotIn(forbidden, item)
            self.assertNotIn(forbidden, response)

    def test_external_fulfillment_attempt_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        response = schema["components"]["schemas"]["ListExternalFulfillmentAttemptsResponse"]["properties"]
        item = schema["components"]["schemas"]["ExternalFulfillmentAttemptItem"]["properties"]

        self.assertIn("attempts", response)
        expected_fields = {
            "attempt_id",
            "created_at",
            "started_at",
            "finished_at",
            "order_id",
            "out_trade_no",
            "product_id",
            "provider_name",
            "source_key",
            "external_product_id",
            "connection_id",
            "external_order_id",
            "delivery_record_id",
            "attempt_source",
            "status",
            "imported",
            "item_count",
            "failure_reason",
            "failure_stage",
            "failure_category",
            "failure_retryable",
            "upstream_status_code",
            "failure_fingerprint",
        }
        lifecycle_status_markers = {
            "started",
            "running",
            "succeeded",
            "already_delivered",
            "failed",
            "imported",
        }
        self.assertEqual(expected_fields, set(item))
        self.assertIn("status", item)
        self.assertIn("started_at", item)
        self.assertTrue({"started", "running", "succeeded"}.issubset(lifecycle_status_markers))
        for forbidden in (
            "tenant_id",
            "metadata_json",
            "credentials",
            "credentials_encrypted",
            "token",
            "secret",
            "api_key",
            "password",
            "authorization",
            "cookie",
            "raw_payload",
            "payload",
            "content",
            "items",
            "message",
            "delivery_type",
            "key_hash",
        ):
            self.assertNotIn(forbidden, item)
            self.assertNotIn(forbidden, response)

    def test_payment_config_operations_are_documented_as_tenant_admin(self) -> None:
        schema = app.openapi()
        expected_security = [{"TenantAdminBearer": []}, {"TenantAdminApiKeyHeader": []}]

        for path in (
            "/api/v1/tenant/payments/epusdt/config",
            "/api/v1/tenant/payments/{provider_name}/config",
        ):
            for method in ("get", "put", "delete"):
                with self.subTest(method=method, path=path):
                    operation = schema["paths"][path][method]
                    self.assertEqual(expected_security, operation["security"])
                    header_names = {
                        parameter["name"]
                        for parameter in operation.get("parameters", [])
                        if parameter.get("in") == "header"
                    }
                    self.assertIn("X-Faka-Timestamp", header_names)
                    self.assertIn("X-Faka-Signature", header_names)
                    self.assertEqual("HMAC-SHA256", operation["x-fakabot-signature"]["algorithm"])
                    self.assertEqual(
                        "TENANT_ADMIN_REQUIRE_SIGNATURE",
                        operation["x-fakabot-signature"]["requiredByConfig"],
                    )

    def test_generic_payment_provider_config_operations_are_documented_as_tenant_admin(self) -> None:
        schema = app.openapi()
        expected_security = [{"TenantAdminBearer": []}, {"TenantAdminApiKeyHeader": []}]

        for method in ("get", "put", "delete"):
            with self.subTest(method=method):
                operation = schema["paths"]["/api/v1/tenant/payments/{provider_name}/config"][method]
                self.assertEqual(expected_security, operation["security"])
                header_names = {
                    parameter["name"]
                    for parameter in operation.get("parameters", [])
                    if parameter.get("in") == "header"
                }
                self.assertIn("X-Faka-Timestamp", header_names)
                self.assertIn("X-Faka-Signature", header_names)
                self.assertEqual("HMAC-SHA256", operation["x-fakabot-signature"]["algorithm"])
                self.assertEqual(
                    "TENANT_ADMIN_REQUIRE_SIGNATURE",
                    operation["x-fakabot-signature"]["requiredByConfig"],
                )

    def test_payment_provider_list_operation_is_documented_as_tenant_admin(self) -> None:
        schema = app.openapi()
        expected_security = [{"TenantAdminBearer": []}, {"TenantAdminApiKeyHeader": []}]

        operation = schema["paths"]["/api/v1/tenant/payments/providers"]["get"]
        self.assertEqual(expected_security, operation["security"])
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertIn("X-Faka-Timestamp", header_names)
        self.assertIn("X-Faka-Signature", header_names)
        self.assertEqual("HMAC-SHA256", operation["x-fakabot-signature"]["algorithm"])
        self.assertEqual(
            "TENANT_ADMIN_REQUIRE_SIGNATURE",
            operation["x-fakabot-signature"]["requiredByConfig"],
        )

    def test_payment_callback_failure_operation_is_documented_as_tenant_admin(self) -> None:
        schema = app.openapi()
        expected_security = [{"TenantAdminBearer": []}, {"TenantAdminApiKeyHeader": []}]

        operation = schema["paths"]["/api/v1/tenant/payments/callback-failures"]["get"]
        self.assertEqual(expected_security, operation["security"])
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertIn("X-Faka-Timestamp", header_names)
        self.assertIn("X-Faka-Signature", header_names)
        self.assertEqual("HMAC-SHA256", operation["x-fakabot-signature"]["algorithm"])
        self.assertEqual(
            "TENANT_ADMIN_REQUIRE_SIGNATURE",
            operation["x-fakabot-signature"]["requiredByConfig"],
        )

    def test_payment_callback_rejection_operation_is_documented_as_tenant_admin(self) -> None:
        schema = app.openapi()
        expected_security = [{"TenantAdminBearer": []}, {"TenantAdminApiKeyHeader": []}]

        operation = schema["paths"]["/api/v1/tenant/payments/callback-rejections"]["get"]
        self.assertEqual(expected_security, operation["security"])
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertIn("X-Faka-Timestamp", header_names)
        self.assertIn("X-Faka-Signature", header_names)
        self.assertEqual("HMAC-SHA256", operation["x-fakabot-signature"]["algorithm"])
        self.assertEqual(
            "TENANT_ADMIN_REQUIRE_SIGNATURE",
            operation["x-fakabot-signature"]["requiredByConfig"],
        )

    def test_finance_operations_are_documented_as_tenant_admin(self) -> None:
        schema = app.openapi()
        expected_security = [{"TenantAdminBearer": []}, {"TenantAdminApiKeyHeader": []}]

        for method, path in [
            ("get", "/api/v1/tenant/finance/balance"),
            ("get", "/api/v1/tenant/finance/ledger/audit"),
            ("get", "/api/v1/tenant/finance/withdrawals"),
            ("get", "/api/v1/tenant/finance/withdrawals/{withdrawal_id}"),
            ("post", "/api/v1/tenant/finance/withdrawals"),
        ]:
            with self.subTest(method=method, path=path):
                operation = schema["paths"][path][method]
                self.assertEqual(expected_security, operation["security"])
                header_names = {
                    parameter["name"]
                    for parameter in operation.get("parameters", [])
                    if parameter.get("in") == "header"
                }
                self.assertIn("X-Faka-Timestamp", header_names)
                self.assertIn("X-Faka-Signature", header_names)
                self.assertEqual("HMAC-SHA256", operation["x-fakabot-signature"]["algorithm"])
                self.assertEqual(
                    "TENANT_ADMIN_REQUIRE_SIGNATURE",
                    operation["x-fakabot-signature"]["requiredByConfig"],
                )

    def test_platform_risk_banned_user_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        list_response = schema["components"]["schemas"]["ListPlatformRiskBannedUsersResponse"]["properties"]
        item = schema["components"]["schemas"]["PlatformRiskBannedUserItem"]["properties"]

        self.assertEqual({"users"}, set(list_response))
        self.assertEqual(
            "#/components/schemas/PlatformRiskBannedUserItem",
            list_response["users"]["items"]["$ref"],
        )
        self.assertEqual(
            {
                "telegram_user_id",
                "username",
                "is_banned",
                "ban_source",
                "latest_action",
                "latest_action_at",
                "reason",
                "trigger_rule",
                "blocked_count",
                "threshold",
                "window_seconds",
                "created_at",
                "updated_at",
            },
            set(item),
        )
        for forbidden in (
            "platform_user_id",
            "tenant_id",
            "trigger_tenant_id",
            "actor_user_id",
            "audit_log_id",
            "target_id",
            "metadata_json",
            "key_hash",
            "encrypted_token",
            "webhook_secret",
            "token",
            "secret",
            "api_key",
            "password",
            "private_key",
            "payment_url",
            "provider_trade_no",
            "raw_payload",
        ):
            self.assertNotIn(forbidden, item)

    def test_platform_risk_ban_status_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        response = schema["components"]["schemas"]["PlatformRiskBanStatusResponse"]["properties"]

        self.assertEqual(
            {
                "telegram_user_id",
                "username",
                "is_banned",
                "ban_source",
                "latest_action",
                "latest_action_at",
                "reason",
                "trigger_rule",
                "blocked_count",
                "threshold",
                "window_seconds",
                "created_at",
                "updated_at",
            },
            set(response),
        )
        for forbidden in (
            "exists",
            "platform_user_id",
            "tenant_id",
            "trigger_tenant_id",
            "actor_user_id",
            "audit_log_id",
            "target_id",
            "metadata_json",
            "key_hash",
            "encrypted_token",
            "webhook_secret",
            "token",
            "secret",
            "api_key",
            "password",
            "private_key",
            "payment_url",
            "provider_trade_no",
            "raw_payload",
        ):
            self.assertNotIn(forbidden, response)

    def test_platform_risk_ban_status_update_operation_is_documented_as_platform_admin(self) -> None:
        schema = app.openapi()
        operation = schema["paths"]["/api/v1/platform/risk/users/{telegram_user_id}/ban-status"]["patch"]
        request_schema_name = (
            operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
        )
        success_response = operation["responses"].get("200") or operation["responses"].get("201")
        self.assertIsNotNone(success_response)
        response_schema_name = (
            success_response["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
        )

        self.assertEqual(
            [{"PlatformAdminBearer": []}, {"PlatformAdminApiKeyHeader": []}],
            operation["security"],
        )
        self.assertNotIn({"TenantAdminBearer": []}, operation["security"])
        self.assertNotIn({"TenantAdminApiKeyHeader": []}, operation["security"])
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertIn("X-Platform-API-Key", header_names)
        self.assertIn("X-Faka-Timestamp", header_names)
        self.assertIn("X-Faka-Signature", header_names)
        self.assertNotIn("X-API-Key", header_names)
        self.assertEqual("HMAC-SHA256", operation["x-fakabot-signature"]["algorithm"])
        self.assertEqual(
            "PLATFORM_ADMIN_REQUIRE_SIGNATURE",
            operation["x-fakabot-signature"]["requiredByConfig"],
        )
        self.assertEqual("PlatformRiskBanStatusUpdateRequest", request_schema_name)
        self.assertEqual("PlatformRiskBanStatusResponse", response_schema_name)

    def test_platform_risk_ban_status_update_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        request_schema = schema["components"]["schemas"]["PlatformRiskBanStatusUpdateRequest"]
        request = request_schema["properties"]
        response = schema["components"]["schemas"]["PlatformRiskBanStatusResponse"]["properties"]

        self.assertFalse(request_schema.get("additionalProperties", True))
        self.assertEqual({"status", "reason"}, set(request))
        self.assertEqual(
            {
                "telegram_user_id",
                "username",
                "is_banned",
                "ban_source",
                "latest_action",
                "latest_action_at",
                "reason",
                "trigger_rule",
                "blocked_count",
                "threshold",
                "window_seconds",
                "created_at",
                "updated_at",
            },
            set(response),
        )
        for forbidden in (
            "platform_user_id",
            "tenant_id",
            "trigger_tenant_id",
            "actor_user_id",
            "audit_log_id",
            "target_id",
            "metadata_json",
            "raw_metadata",
            "key_hash",
            "encrypted_token",
            "webhook_secret",
            "token",
            "secret",
            "api_key",
            "authorization",
            "cookie",
            "password",
            "private_key",
            "payload",
            "payment_url",
            "provider_trade_no",
            "raw_payload",
            "raw_request",
            "raw_response",
        ):
            self.assertNotIn(forbidden, request)
            self.assertNotIn(forbidden, response)

    def test_platform_tenant_suspension_update_operation_is_documented_as_platform_admin(self) -> None:
        schema = app.openapi()
        operation = schema["paths"]["/api/v1/platform/risk/tenants/{tenant_id}/suspension-status"]["patch"]
        request_schema_name = (
            operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
        )
        success_response = operation["responses"].get("200") or operation["responses"].get("201")
        self.assertIsNotNone(success_response)
        response_schema_name = (
            success_response["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
        )

        self.assertEqual(
            [{"PlatformAdminBearer": []}, {"PlatformAdminApiKeyHeader": []}],
            operation["security"],
        )
        self.assertNotIn({"TenantAdminBearer": []}, operation["security"])
        self.assertNotIn({"TenantAdminApiKeyHeader": []}, operation["security"])
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertIn("X-Platform-API-Key", header_names)
        self.assertIn("X-Faka-Timestamp", header_names)
        self.assertIn("X-Faka-Signature", header_names)
        self.assertNotIn("X-API-Key", header_names)
        self.assertEqual("HMAC-SHA256", operation["x-fakabot-signature"]["algorithm"])
        self.assertEqual(
            "PLATFORM_ADMIN_REQUIRE_SIGNATURE",
            operation["x-fakabot-signature"]["requiredByConfig"],
        )
        self.assertEqual("PlatformTenantSuspensionStatusUpdateRequest", request_schema_name)
        self.assertEqual("PlatformTenantSuspensionStatusResponse", response_schema_name)

    def test_platform_tenant_suspension_update_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        request_schema = schema["components"]["schemas"]["PlatformTenantSuspensionStatusUpdateRequest"]
        request = request_schema["properties"]
        response = schema["components"]["schemas"]["PlatformTenantSuspensionStatusResponse"]["properties"]

        self.assertFalse(request_schema.get("additionalProperties", True))
        self.assertEqual({"status", "reason"}, set(request))
        self.assertEqual({"tenant_id", "previous_status", "status", "reason"}, set(response))
        for forbidden in (
            "owner_user_id",
            "source_tenant_id",
            "actor_user_id",
            "audit_log_id",
            "target_id",
            "metadata_json",
            "raw_metadata",
            "webhook_secret",
            "encrypted_token",
            "token",
            "secret",
            "api_key",
            "payload",
            "raw_payload",
        ):
            self.assertNotIn(forbidden, request)
            self.assertNotIn(forbidden, response)

    def test_platform_risk_audit_logs_operation_is_documented_as_platform_admin(self) -> None:
        schema = app.openapi()
        operation = schema["paths"]["/api/v1/platform/risk/audit-logs"]["get"]

        self.assertEqual(
            [{"PlatformAdminBearer": []}, {"PlatformAdminApiKeyHeader": []}],
            operation["security"],
        )
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertIn("X-Platform-API-Key", header_names)
        self.assertIn("X-Faka-Timestamp", header_names)
        self.assertIn("X-Faka-Signature", header_names)
        self.assertNotIn("X-API-Key", header_names)
        self.assertEqual("HMAC-SHA256", operation["x-fakabot-signature"]["algorithm"])
        self.assertEqual(
            "PLATFORM_ADMIN_REQUIRE_SIGNATURE",
            operation["x-fakabot-signature"]["requiredByConfig"],
        )

    def test_platform_risk_audit_log_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        list_response = schema["components"]["schemas"]["ListPlatformRiskAuditLogsResponse"]["properties"]
        item = schema["components"]["schemas"]["PlatformRiskAuditLogItem"]["properties"]

        self.assertEqual({"audit_logs"}, set(list_response))
        self.assertEqual(
            "#/components/schemas/PlatformRiskAuditLogItem",
            list_response["audit_logs"]["items"]["$ref"],
        )
        self.assertEqual(
            {
                "created_at",
                "action",
                "target_type",
                "actor_telegram_user_id",
                "actor_username",
                "target_telegram_user_id",
                "previous_status",
                "new_status",
                "reason",
                "risk_rule",
                "blocked_count",
                "threshold",
                "window_seconds",
            },
            set(item),
        )
        for forbidden in (
            "platform_user_id",
            "tenant_id",
            "trigger_tenant_id",
            "trigger_source_type",
            "actor_user_id",
            "audit_log_id",
            "target_id",
            "metadata_json",
            "raw_metadata",
            "key_hash",
            "encrypted_token",
            "webhook_secret",
            "token",
            "secret",
            "api_key",
            "authorization",
            "cookie",
            "password",
            "private_key",
            "payload",
            "payment_url",
            "provider_trade_no",
            "raw_payload",
            "raw_request",
            "raw_response",
        ):
            self.assertNotIn(forbidden, item)
            self.assertNotIn(forbidden, list_response)

    def test_platform_finance_withdrawals_operation_is_documented_as_platform_admin(self) -> None:
        schema = app.openapi()
        operation = schema["paths"]["/api/v1/platform/finance/withdrawals"]["get"]
        success_response = operation["responses"].get("200")
        self.assertIsNotNone(success_response)
        response_schema_name = (
            success_response["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
        )

        self.assertEqual(
            [{"PlatformAdminBearer": []}, {"PlatformAdminApiKeyHeader": []}],
            operation["security"],
        )
        self.assertNotIn({"TenantAdminBearer": []}, operation["security"])
        self.assertNotIn({"TenantAdminApiKeyHeader": []}, operation["security"])
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertIn("X-Platform-API-Key", header_names)
        self.assertIn("X-Faka-Timestamp", header_names)
        self.assertIn("X-Faka-Signature", header_names)
        self.assertNotIn("X-API-Key", header_names)
        self.assertEqual("HMAC-SHA256", operation["x-fakabot-signature"]["algorithm"])
        self.assertEqual(
            "PLATFORM_ADMIN_REQUIRE_SIGNATURE",
            operation["x-fakabot-signature"]["requiredByConfig"],
        )
        self.assertEqual("ListPlatformWithdrawalsResponse", response_schema_name)

    def test_platform_finance_withdrawal_detail_operation_is_documented_as_platform_admin(self) -> None:
        schema = app.openapi()
        operation = schema["paths"]["/api/v1/platform/finance/withdrawals/{withdrawal_id}"]["get"]
        success_response = operation["responses"].get("200")
        self.assertIsNotNone(success_response)
        response_schema_name = (
            success_response["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
        )

        self.assertEqual(
            [{"PlatformAdminBearer": []}, {"PlatformAdminApiKeyHeader": []}],
            operation["security"],
        )
        self.assertNotIn({"TenantAdminBearer": []}, operation["security"])
        self.assertNotIn({"TenantAdminApiKeyHeader": []}, operation["security"])
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertIn("X-Platform-API-Key", header_names)
        self.assertIn("X-Faka-Timestamp", header_names)
        self.assertIn("X-Faka-Signature", header_names)
        self.assertNotIn("X-API-Key", header_names)
        self.assertEqual("HMAC-SHA256", operation["x-fakabot-signature"]["algorithm"])
        self.assertEqual(
            "PLATFORM_ADMIN_REQUIRE_SIGNATURE",
            operation["x-fakabot-signature"]["requiredByConfig"],
        )
        self.assertEqual("PlatformWithdrawalDetailItem", response_schema_name)

    def test_platform_finance_withdrawal_review_operations_are_documented_as_platform_admin(self) -> None:
        schema = app.openapi()
        expected_security = [{"PlatformAdminBearer": []}, {"PlatformAdminApiKeyHeader": []}]

        for path, request_schema_name in (
            ("/api/v1/platform/finance/withdrawals/{withdrawal_id}/complete", "CompletePlatformWithdrawalRequest"),
            ("/api/v1/platform/finance/withdrawals/{withdrawal_id}/reject", "RejectPlatformWithdrawalRequest"),
        ):
            with self.subTest(path=path):
                operation = schema["paths"][path]["post"]
                success_response = operation["responses"].get("200")
                self.assertIsNotNone(success_response)
                response_schema_name = (
                    success_response["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
                )
                request_body_schema_name = (
                    operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
                )

                self.assertEqual(expected_security, operation["security"])
                self.assertNotIn({"TenantAdminBearer": []}, operation["security"])
                self.assertNotIn({"TenantAdminApiKeyHeader": []}, operation["security"])
                header_names = {
                    parameter["name"]
                    for parameter in operation.get("parameters", [])
                    if parameter.get("in") == "header"
                }
                self.assertIn("X-Platform-API-Key", header_names)
                self.assertIn("X-Faka-Timestamp", header_names)
                self.assertIn("X-Faka-Signature", header_names)
                self.assertNotIn("X-API-Key", header_names)
                self.assertEqual("HMAC-SHA256", operation["x-fakabot-signature"]["algorithm"])
                self.assertEqual(
                    "PLATFORM_ADMIN_REQUIRE_SIGNATURE",
                    operation["x-fakabot-signature"]["requiredByConfig"],
                )
                self.assertEqual(request_schema_name, request_body_schema_name)
                self.assertEqual("PlatformWithdrawalDetailItem", response_schema_name)

    def test_platform_finance_withdrawal_review_request_schemas_are_whitelisted(self) -> None:
        schema = app.openapi()
        complete_schema = schema["components"]["schemas"]["CompletePlatformWithdrawalRequest"]
        reject_schema = schema["components"]["schemas"]["RejectPlatformWithdrawalRequest"]

        self.assertFalse(complete_schema["additionalProperties"])
        self.assertFalse(reject_schema["additionalProperties"])
        self.assertEqual(
            {"admin_note", "payout_reference", "payout_proof_url"},
            set(complete_schema["properties"]),
        )
        self.assertEqual({"admin_note"}, set(reject_schema["properties"]))
        for forbidden in (
            "status",
            "tenant_id",
            "amount",
            "currency",
            "network",
            "address",
            "address_masked",
            "address_encrypted",
            "actor_user_id",
            "account_id",
            "ledger_entry_id",
            "idempotency_key",
            "metadata_json",
            "raw_metadata",
            "credentials",
            "credentials_encrypted",
            "token",
            "secret",
            "api_key",
            "password",
            "private_key",
            "payload",
            "raw_payload",
        ):
            self.assertNotIn(forbidden, complete_schema["properties"])
            self.assertNotIn(forbidden, reject_schema["properties"])

    def test_platform_subscription_plan_operations_are_documented_as_platform_admin(self) -> None:
        schema = app.openapi()
        expected_security = [{"PlatformAdminBearer": []}, {"PlatformAdminApiKeyHeader": []}]
        operations = [
            ("get", "/api/v1/platform/subscription/plans", None, "ListPlatformSubscriptionPlansResponse"),
            ("post", "/api/v1/platform/subscription/plans", "CreatePlatformSubscriptionPlanRequest", "PlatformSubscriptionPlanItem"),
            ("get", "/api/v1/platform/subscription/plans/{plan_code}", None, "PlatformSubscriptionPlanItem"),
            (
                "patch",
                "/api/v1/platform/subscription/plans/{plan_code}",
                "UpdatePlatformSubscriptionPlanRequest",
                "PlatformSubscriptionPlanItem",
            ),
            (
                "patch",
                "/api/v1/platform/subscription/plans/{plan_code}/status",
                "UpdatePlatformSubscriptionPlanStatusRequest",
                "PlatformSubscriptionPlanItem",
            ),
        ]

        for method, path, request_schema_name, response_schema_name in operations:
            with self.subTest(method=method, path=path):
                operation = schema["paths"][path][method]
                success_response = operation["responses"].get("200")
                self.assertIsNotNone(success_response)
                actual_response_schema_name = (
                    success_response["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
                )

                self.assertEqual(expected_security, operation["security"])
                self.assertNotIn({"TenantAdminBearer": []}, operation["security"])
                self.assertNotIn({"TenantAdminApiKeyHeader": []}, operation["security"])
                header_names = {
                    parameter["name"]
                    for parameter in operation.get("parameters", [])
                    if parameter.get("in") == "header"
                }
                self.assertIn("X-Platform-API-Key", header_names)
                self.assertIn("X-Faka-Timestamp", header_names)
                self.assertIn("X-Faka-Signature", header_names)
                self.assertNotIn("X-API-Key", header_names)
                self.assertEqual("HMAC-SHA256", operation["x-fakabot-signature"]["algorithm"])
                self.assertEqual(
                    "PLATFORM_ADMIN_REQUIRE_SIGNATURE",
                    operation["x-fakabot-signature"]["requiredByConfig"],
                )
                self.assertEqual(response_schema_name, actual_response_schema_name)
                if "{plan_code}" in path:
                    path_params = {
                        parameter["name"]
                        for parameter in operation.get("parameters", [])
                        if parameter.get("in") == "path"
                    }
                    self.assertIn("plan_code", path_params)
                if request_schema_name is None:
                    self.assertNotIn("requestBody", operation)
                else:
                    actual_request_schema_name = (
                        operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
                    )
                    self.assertEqual(request_schema_name, actual_request_schema_name)

    def test_platform_subscription_plan_schemas_are_whitelisted(self) -> None:
        schema = app.openapi()
        item = schema["components"]["schemas"]["PlatformSubscriptionPlanItem"]["properties"]
        list_response = schema["components"]["schemas"]["ListPlatformSubscriptionPlansResponse"]["properties"]
        create_schema = schema["components"]["schemas"]["CreatePlatformSubscriptionPlanRequest"]
        update_schema = schema["components"]["schemas"]["UpdatePlatformSubscriptionPlanRequest"]
        status_schema = schema["components"]["schemas"]["UpdatePlatformSubscriptionPlanStatusRequest"]

        self.assertEqual(
            {
                "code",
                "name",
                "monthly_price",
                "currency",
                "trial_days",
                "grace_days",
                "enabled",
                "created_at",
                "updated_at",
            },
            set(item),
        )
        self.assertEqual({"plans"}, set(list_response))
        self.assertEqual(
            "#/components/schemas/PlatformSubscriptionPlanItem",
            list_response["plans"]["items"]["$ref"],
        )
        self.assertFalse(create_schema["additionalProperties"])
        self.assertFalse(update_schema["additionalProperties"])
        self.assertFalse(status_schema["additionalProperties"])
        self.assertEqual(
            {"code", "name", "monthly_price", "currency", "trial_days", "grace_days", "enabled", "reason"},
            set(create_schema["properties"]),
        )
        self.assertEqual(
            {"name", "monthly_price", "currency", "trial_days", "grace_days", "reason"},
            set(update_schema["properties"]),
        )
        self.assertEqual({"enabled", "reason"}, set(status_schema["properties"]))
        forbidden_fields = (
            "id",
            "tenant_id",
            "owner_user_id",
            "subscription_id",
            "plan_id",
            "invoice_id",
            "order_id",
            "payment_id",
            "provider_trade_no",
            "payload_json",
            "metadata_json",
            "raw_payload",
            "credentials",
            "credentials_encrypted",
            "token",
            "secret",
            "api_key",
            "password",
            "private_key",
        )
        for forbidden in forbidden_fields:
            self.assertNotIn(forbidden, item)
            self.assertNotIn(forbidden, list_response)
            self.assertNotIn(forbidden, create_schema["properties"])
            self.assertNotIn(forbidden, update_schema["properties"])
            self.assertNotIn(forbidden, status_schema["properties"])

    def test_platform_finance_withdrawal_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        list_response = schema["components"]["schemas"]["ListPlatformWithdrawalsResponse"]["properties"]
        item = schema["components"]["schemas"]["PlatformWithdrawalItem"]["properties"]

        self.assertEqual({"withdrawals"}, set(list_response))
        self.assertEqual(
            "#/components/schemas/PlatformWithdrawalItem",
            list_response["withdrawals"]["items"]["$ref"],
        )
        self.assertEqual(
            {
                "withdrawal_id",
                "tenant_id",
                "amount",
                "currency",
                "network",
                "address_masked",
                "status",
                "requested_at",
            },
            set(item),
        )
        for forbidden in (
            "address",
            "address_encrypted",
            "destination",
            "destination_encrypted",
            "admin_note",
            "payout_reference",
            "payout_proof_url",
            "reviewed_at",
            "completed_at",
            "account_id",
            "ledger_entry_id",
            "idempotency_key",
            "actor_user_id",
            "metadata_json",
            "raw_metadata",
            "webhook_secret",
            "encrypted_token",
            "credentials",
            "credentials_encrypted",
            "token",
            "secret",
            "api_key",
            "password",
            "private_key",
            "payload",
            "raw_payload",
        ):
            self.assertNotIn(forbidden, item)
            self.assertNotIn(forbidden, list_response)

    def test_platform_finance_withdrawal_detail_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        item = schema["components"]["schemas"]["PlatformWithdrawalDetailItem"]["properties"]

        self.assertEqual(
            {
                "withdrawal_id",
                "tenant_id",
                "amount",
                "currency",
                "network",
                "address_masked",
                "status",
                "requested_at",
                "reviewed_at",
                "completed_at",
            },
            set(item),
        )
        for forbidden in (
            "address",
            "address_encrypted",
            "destination",
            "destination_encrypted",
            "admin_note",
            "payout_reference",
            "payout_proof_url",
            "account_id",
            "ledger_entry_id",
            "idempotency_key",
            "actor_user_id",
            "metadata_json",
            "raw_metadata",
            "webhook_secret",
            "encrypted_token",
            "credentials",
            "credentials_encrypted",
            "token",
            "secret",
            "api_key",
            "password",
            "private_key",
            "payload",
            "raw_payload",
        ):
            self.assertNotIn(forbidden, item)

    def test_platform_supply_operations_are_documented_as_platform_admin(self) -> None:
        schema = app.openapi()
        expected_security = [{"PlatformAdminBearer": []}, {"PlatformAdminApiKeyHeader": []}]

        for method, path in (
            ("get", "/api/v1/platform/supply/supplier-offers"),
            ("patch", "/api/v1/platform/supply/supplier-offers/{supplier_offer_id}/status"),
        ):
            with self.subTest(method=method, path=path):
                operation = schema["paths"][path][method]
                self.assertEqual(expected_security, operation["security"])
                self.assertNotIn({"TenantAdminBearer": []}, operation["security"])
                self.assertNotIn({"TenantAdminApiKeyHeader": []}, operation["security"])
                header_names = {
                    parameter["name"]
                    for parameter in operation.get("parameters", [])
                    if parameter.get("in") == "header"
                }
                self.assertIn("X-Platform-API-Key", header_names)
                self.assertIn("X-Faka-Timestamp", header_names)
                self.assertIn("X-Faka-Signature", header_names)
                self.assertNotIn("X-API-Key", header_names)
                self.assertEqual("HMAC-SHA256", operation["x-fakabot-signature"]["algorithm"])
                self.assertEqual(
                    "PLATFORM_ADMIN_REQUIRE_SIGNATURE",
                    operation["x-fakabot-signature"]["requiredByConfig"],
                )

    def test_platform_supply_supplier_offer_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        list_response = schema["components"]["schemas"]["ListPlatformSupplierOffersResponse"]["properties"]
        item = schema["components"]["schemas"]["PlatformSupplierOfferItem"]["properties"]
        request_schema = schema["components"]["schemas"]["UpdatePlatformSupplierOfferStatusRequest"]
        request = request_schema["properties"]

        self.assertEqual({"offers"}, set(list_response))
        self.assertEqual(
            "#/components/schemas/PlatformSupplierOfferItem",
            list_response["offers"]["items"]["$ref"],
        )
        self.assertFalse(request_schema.get("additionalProperties", True))
        self.assertEqual({"status", "reason"}, set(request))
        self.assertEqual(
            {
                "supplier_offer_id",
                "supplier_tenant_id",
                "supplier_store_name",
                "product_name",
                "delivery_type",
                "suggested_price",
                "min_sale_price",
                "supplier_cost",
                "currency",
                "available_count",
                "requires_approval",
                "status",
                "created_at",
                "updated_at",
            },
            set(item),
        )
        forbidden_fields = (
            "tenant_id",
            "product_id",
            "variant_id",
            "rule_id",
            "reseller_tenant_id",
            "pricing_value",
            "pricing_mode",
            "default_pricing_mode",
            "default_pricing_value",
            "hidden_supplier_allowed",
            "hide_supplier",
            "inventory_id",
            "inventory_item_id",
            "credentials",
            "credentials_encrypted",
            "token",
            "secret",
            "api_key",
            "password",
            "private_key",
            "storage_key",
            "content",
            "content_encrypted",
            "raw_payload",
            "raw_request",
            "raw_response",
            "metadata_json",
        )
        for forbidden in forbidden_fields:
            self.assertNotIn(forbidden, request)
            self.assertNotIn(forbidden, item)

    def test_subscription_operations_are_documented_as_tenant_admin(self) -> None:
        schema = app.openapi()
        expected_security = [{"TenantAdminBearer": []}, {"TenantAdminApiKeyHeader": []}]

        for method, path in (
            ("get", "/api/v1/tenant/subscription/status"),
            ("get", "/api/v1/tenant/subscription/invoices"),
            ("post", "/api/v1/tenant/subscription/renewal-orders"),
        ):
            operation = schema["paths"][path][method]
            self.assertEqual(expected_security, operation["security"])
            header_names = {
                parameter["name"]
                for parameter in operation.get("parameters", [])
                if parameter.get("in") == "header"
            }
            self.assertIn("X-Faka-Timestamp", header_names)
            self.assertIn("X-Faka-Signature", header_names)
            self.assertEqual("HMAC-SHA256", operation["x-fakabot-signature"]["algorithm"])
            self.assertEqual(
                "TENANT_ADMIN_REQUIRE_SIGNATURE",
                operation["x-fakabot-signature"]["requiredByConfig"],
            )

    def test_subscription_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        status_response = schema["components"]["schemas"]["TenantSubscriptionResponse"]["properties"]
        invoice_list = schema["components"]["schemas"]["ListTenantSubscriptionInvoicesResponse"]["properties"]
        invoice_item = schema["components"]["schemas"]["TenantSubscriptionInvoiceItem"]["properties"]
        renewal_request_schema = schema["components"]["schemas"]["CreateTenantSubscriptionRenewalOrderRequest"]
        renewal_request = renewal_request_schema["properties"]
        renewal_response = schema["components"]["schemas"]["TenantSubscriptionRenewalOrderResponse"]["properties"]

        self.assertEqual(
            {
                "status",
                "plan_code",
                "plan_name",
                "monthly_price",
                "currency",
                "trial_days",
                "grace_days",
                "trial_ends_at",
                "current_period_ends_at",
                "subscription_ends_at",
                "grace_ends_at",
                "suspended_at",
                "data_retention_until",
                "created_at",
                "updated_at",
            },
            set(status_response),
        )
        self.assertEqual({"invoices"}, set(invoice_list))
        self.assertEqual(
            {"out_trade_no", "amount", "currency", "status", "paid_at", "created_at"},
            set(invoice_item),
        )
        self.assertFalse(renewal_request_schema.get("additionalProperties", True))
        self.assertEqual({"months"}, set(renewal_request))
        self.assertEqual(
            {
                "out_trade_no",
                "amount",
                "currency",
                "months",
                "expires_at",
                "payment_available",
                "payment_provider",
                "payment_url",
                "payment_failure_reason",
            },
            set(renewal_response),
        )
        for forbidden in (
            "tenant_id",
            "owner_user_id",
            "subscription_id",
            "plan_id",
            "invoice_id",
            "order_id",
            "payment_id",
            "callback_id",
            "buyer_telegram_user_id",
            "created_by_user_id",
            "metadata_json",
            "payload_json",
            "payload_hash",
            "raw_payload",
            "raw_request",
            "raw_response",
            "payment_url",
            "provider_trade_no",
            "signature",
            "signing_text",
            "credentials",
            "credentials_encrypted",
            "token",
            "secret",
            "secret_key",
            "api_key",
            "password",
            "private_key",
            "config_encrypted",
            "supplier_tenant_id",
            "supplier_settlement_amount",
            "reseller_settlement_amount",
        ):
            self.assertNotIn(forbidden, status_response)
            self.assertNotIn(forbidden, invoice_list)
            self.assertNotIn(forbidden, invoice_item)
            self.assertNotIn(forbidden, renewal_request)
            if forbidden != "payment_url":
                self.assertNotIn(forbidden, renewal_response)
        for allowed in ("payment_url", "payment_available", "payment_failure_reason"):
            self.assertIn(allowed, renewal_response)

    def test_supply_operations_are_documented_as_tenant_admin(self) -> None:
        schema = app.openapi()
        expected_security = [{"TenantAdminBearer": []}, {"TenantAdminApiKeyHeader": []}]

        for method, path in (
            ("get", "/api/v1/tenant/supply/market-offers"),
            ("get", "/api/v1/tenant/supply/applications"),
            ("post", "/api/v1/tenant/supply/applications"),
            ("get", "/api/v1/tenant/supply/reseller-products"),
            ("post", "/api/v1/tenant/supply/reseller-products"),
        ):
            operation = schema["paths"][path][method]
            self.assertEqual(expected_security, operation["security"])
            header_names = {
                parameter["name"]
                for parameter in operation.get("parameters", [])
                if parameter.get("in") == "header"
            }
            self.assertIn("X-Faka-Timestamp", header_names)
            self.assertIn("X-Faka-Signature", header_names)
            self.assertEqual("HMAC-SHA256", operation["x-fakabot-signature"]["algorithm"])
            self.assertEqual(
                "TENANT_ADMIN_REQUIRE_SIGNATURE",
                operation["x-fakabot-signature"]["requiredByConfig"],
            )

    def test_supply_supplier_operations_are_documented_as_tenant_admin(self) -> None:
        schema = app.openapi()
        expected_security = [{"TenantAdminBearer": []}, {"TenantAdminApiKeyHeader": []}]

        for method, path in (
            ("get", "/api/v1/tenant/supply/supplier-offers"),
            ("post", "/api/v1/tenant/supply/supplier-offers"),
            ("patch", "/api/v1/tenant/supply/supplier-offers/{supplier_offer_id}/approval"),
            ("get", "/api/v1/tenant/supply/supplier-applications"),
            ("post", "/api/v1/tenant/supply/supplier-applications/approve"),
            ("post", "/api/v1/tenant/supply/supplier-applications/reject"),
        ):
            operation = schema["paths"][path][method]
            self.assertEqual(expected_security, operation["security"])
            header_names = {
                parameter["name"]
                for parameter in operation.get("parameters", [])
                if parameter.get("in") == "header"
            }
            self.assertIn("X-Faka-Timestamp", header_names)
            self.assertIn("X-Faka-Signature", header_names)
            self.assertEqual("HMAC-SHA256", operation["x-fakabot-signature"]["algorithm"])
            self.assertEqual(
                "TENANT_ADMIN_REQUIRE_SIGNATURE",
                operation["x-fakabot-signature"]["requiredByConfig"],
            )

    def test_supply_supplier_rule_operation_is_documented_as_tenant_admin(self) -> None:
        schema = app.openapi()
        path = "/api/v1/tenant/supply/supplier-rules"
        operation = schema["paths"][path]["post"]
        request_schema_name = (
            operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
        )
        success_response = operation["responses"].get("200") or operation["responses"].get("201")
        self.assertIsNotNone(success_response)
        response_schema_name = (
            success_response["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
        )

        self.assertEqual(
            [{"TenantAdminBearer": []}, {"TenantAdminApiKeyHeader": []}],
            operation["security"],
        )
        self.assertNotIn({"PlatformAdminBearer": []}, operation["security"])
        self.assertNotIn({"PlatformAdminApiKeyHeader": []}, operation["security"])
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertIn("X-Faka-Timestamp", header_names)
        self.assertIn("X-Faka-Signature", header_names)
        self.assertEqual("HMAC-SHA256", operation["x-fakabot-signature"]["algorithm"])
        self.assertEqual(
            "TENANT_ADMIN_REQUIRE_SIGNATURE",
            operation["x-fakabot-signature"]["requiredByConfig"],
        )
        self.assertEqual("SetTenantSupplierRuleRequest", request_schema_name)
        self.assertEqual("TenantSupplierApplicationItem", response_schema_name)

    def test_supply_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        market_list = schema["components"]["schemas"]["ListTenantSupplyMarketOffersResponse"]["properties"]
        market_offer = schema["components"]["schemas"]["TenantSupplyMarketOfferItem"]["properties"]
        application_list = schema["components"]["schemas"]["ListTenantResellerApplicationsResponse"]["properties"]
        application_request_schema = schema["components"]["schemas"]["CreateTenantResellerApplicationRequest"]
        application_request = application_request_schema["properties"]
        application = schema["components"]["schemas"]["TenantResellerApplicationItem"]["properties"]
        reseller_product_list = schema["components"]["schemas"]["ListTenantResellerProductsResponse"]["properties"]
        reseller_product_request_schema = schema["components"]["schemas"]["CreateTenantResellerProductRequest"]
        reseller_product_request = reseller_product_request_schema["properties"]
        created_reseller_product = schema["components"]["schemas"]["TenantCreatedResellerProductItem"]["properties"]
        reseller_product = schema["components"]["schemas"]["TenantResellerProductItem"]["properties"]

        self.assertEqual({"offers"}, set(market_list))
        self.assertEqual(
            {
                "supplier_offer_id",
                "product_name",
                "delivery_type",
                "suggested_price",
                "min_sale_price",
                "currency",
                "available_count",
                "description",
                "requires_approval",
                "reseller_rule_status",
                "can_create_reseller_product",
                "supplier_cost",
                "effective_min_sale_price",
            },
            set(market_offer),
        )
        self.assertFalse(application_request_schema.get("additionalProperties", True))
        self.assertEqual({"supplier_offer_id"}, set(application_request))
        self.assertEqual({"applications"}, set(application_list))
        self.assertEqual(
            {
                "supplier_offer_id",
                "product_name",
                "status",
                "pricing_value",
                "min_sale_price",
                "currency",
                "updated_at",
            },
            set(application),
        )
        self.assertFalse(reseller_product_request_schema.get("additionalProperties", True))
        self.assertEqual({"supplier_offer_id", "sale_price", "display_name"}, set(reseller_product_request))
        self.assertEqual({"products"}, set(reseller_product_list))
        self.assertEqual(
            {"reseller_product_id", "supplier_offer_id", "display_name", "sale_price", "currency", "status"},
            set(created_reseller_product),
        )
        self.assertEqual(
            {
                "reseller_product_id",
                "supplier_offer_id",
                "display_name",
                "category",
                "sort_order",
                "delivery_type",
                "sale_price",
                "currency",
                "status",
                "available_count",
            },
            set(reseller_product),
        )
        forbidden_fields = (
            "supplier_tenant_id",
            "reseller_tenant_id",
            "product_id",
            "variant_id",
            "rule_id",
            "default_pricing_mode",
            "default_pricing_value",
            "pricing_mode",
            "hidden_supplier_allowed",
            "hide_supplier",
            "inventory_id",
            "inventory_item_id",
            "locked_inventory_item_id",
            "content",
            "key_hash",
            "storage_key",
            "file_path",
            "telegram_chat_id",
            "credentials",
            "credentials_encrypted",
            "token",
            "secret",
            "api_key",
            "password",
            "raw_payload",
            "raw_request",
            "raw_response",
        )
        for forbidden in forbidden_fields:
            self.assertNotIn(forbidden, market_offer)
            self.assertNotIn(forbidden, application_request)
            self.assertNotIn(forbidden, application)
            self.assertNotIn(forbidden, reseller_product_request)
            self.assertNotIn(forbidden, created_reseller_product)
            self.assertNotIn(forbidden, reseller_product)

    def test_supply_supplier_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        supplier_offer_list = schema["components"]["schemas"]["ListTenantSupplierOffersResponse"]["properties"]
        supplier_offer = schema["components"]["schemas"]["TenantSupplierOfferItem"]["properties"]
        create_offer_schema = schema["components"]["schemas"]["CreateTenantSupplierOfferRequest"]
        create_offer = create_offer_schema["properties"]
        created_offer = schema["components"]["schemas"]["TenantCreatedSupplierOfferItem"]["properties"]
        approval_schema = schema["components"]["schemas"]["UpdateTenantSupplierOfferApprovalRequest"]
        approval_request = approval_schema["properties"]
        approval_response = schema["components"]["schemas"]["TenantSupplierOfferApprovalItem"]["properties"]
        application_list = schema["components"]["schemas"]["ListTenantSupplierApplicationsResponse"]["properties"]
        application = schema["components"]["schemas"]["TenantSupplierApplicationItem"]["properties"]
        approve_schema = schema["components"]["schemas"]["ApproveTenantSupplierApplicationRequest"]
        approve_request = approve_schema["properties"]
        reject_schema = schema["components"]["schemas"]["RejectTenantSupplierApplicationRequest"]
        reject_request = reject_schema["properties"]

        supplier_offer_fields = {
            "supplier_offer_id",
            "product_name",
            "delivery_type",
            "suggested_price",
            "min_sale_price",
            "supplier_cost",
            "currency",
            "available_count",
            "requires_approval",
            "status",
        }
        self.assertEqual({"offers"}, set(supplier_offer_list))
        self.assertEqual(supplier_offer_fields, set(supplier_offer))
        self.assertFalse(create_offer_schema.get("additionalProperties", True))
        self.assertEqual({"product_id", "suggested_price", "min_sale_price", "requires_approval"}, set(create_offer))
        self.assertEqual(supplier_offer_fields - {"available_count"}, set(created_offer))
        self.assertFalse(approval_schema.get("additionalProperties", True))
        self.assertEqual({"requires_approval"}, set(approval_request))
        self.assertEqual({"supplier_offer_id", "requires_approval", "status"}, set(approval_response))
        self.assertEqual({"applications"}, set(application_list))
        self.assertEqual(
            {
                "supplier_offer_id",
                "reseller_tenant_id",
                "reseller_store_name",
                "product_name",
                "status",
                "pricing_value",
                "min_sale_price",
                "currency",
                "updated_at",
            },
            set(application),
        )
        self.assertFalse(approve_schema.get("additionalProperties", True))
        self.assertEqual({"supplier_offer_id", "reseller_tenant_id"}, set(approve_request))
        self.assertFalse(reject_schema.get("additionalProperties", True))
        self.assertEqual({"supplier_offer_id", "reseller_tenant_id", "reason"}, set(reject_request))

        supplier_response_forbidden = (
            "tenant_id",
            "supplier_tenant_id",
            "supplier_store_name",
            "product_id",
            "variant_id",
            "rule_id",
            "default_pricing_mode",
            "default_pricing_value",
            "pricing_mode",
            "hidden_supplier_allowed",
            "hide_supplier",
            "sort_order",
            "inventory_id",
            "inventory_item_id",
            "storage_key",
            "file_path",
            "credentials",
            "credentials_encrypted",
            "token",
            "secret",
            "api_key",
            "password",
            "raw_payload",
            "raw_request",
            "raw_response",
            "metadata_json",
        )
        for forbidden in supplier_response_forbidden:
            self.assertNotIn(forbidden, supplier_offer)
            self.assertNotIn(forbidden, created_offer)
            self.assertNotIn(forbidden, approval_response)
            self.assertNotIn(forbidden, application)
        for forbidden in ("tenant_id", "supplier_tenant_id", "variant_id", "rule_id", "token", "secret", "api_key"):
            self.assertNotIn(forbidden, create_offer)
            self.assertNotIn(forbidden, approve_request)
            self.assertNotIn(forbidden, reject_request)

    def test_supply_supplier_rule_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        request_schema = schema["components"]["schemas"]["SetTenantSupplierRuleRequest"]
        request = request_schema["properties"]
        response = schema["components"]["schemas"]["TenantSupplierApplicationItem"]["properties"]

        self.assertFalse(request_schema.get("additionalProperties", True))
        self.assertEqual(
            {"supplier_offer_id", "reseller_tenant_id", "pricing_value", "min_sale_price"},
            set(request),
        )
        self.assertEqual(
            {
                "supplier_offer_id",
                "reseller_tenant_id",
                "reseller_store_name",
                "product_name",
                "status",
                "pricing_value",
                "min_sale_price",
                "currency",
                "updated_at",
            },
            set(response),
        )
        forbidden_fields = (
            "rule_id",
            "tenant_id",
            "supplier_tenant_id",
            "supplier_store_name",
            "product_id",
            "variant_id",
            "pricing_mode",
            "default_pricing_mode",
            "default_pricing_value",
            "hidden_supplier_allowed",
            "hide_supplier",
            "inventory_id",
            "inventory_item_id",
            "storage_key",
            "content",
            "content_encrypted",
            "credentials",
            "credentials_encrypted",
            "token",
            "secret",
            "api_key",
            "password",
            "private_key",
            "raw_payload",
            "raw_request",
            "raw_response",
            "metadata_json",
        )
        for forbidden in forbidden_fields:
            self.assertNotIn(forbidden, request)
            self.assertNotIn(forbidden, response)

    def test_finance_balance_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        response = schema["components"]["schemas"]["TenantLedgerBalanceResponse"]["properties"]

        self.assertEqual(
            {"account_type", "currency", "pending_balance", "available_balance", "frozen_balance"},
            set(response),
        )
        for forbidden in (
            "tenant_id",
            "ledger_account_id",
            "account_id",
            "raw_metadata",
            "credentials",
            "credentials_encrypted",
            "token",
            "secret",
            "api_key",
            "password",
            "key_hash",
        ):
            self.assertNotIn(forbidden, response)

    def test_finance_ledger_audit_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        response = schema["components"]["schemas"]["TenantLedgerBalanceAuditResponse"]["properties"]

        self.assertEqual(
            {
                "account_type",
                "currency",
                "stored_pending_balance",
                "stored_available_balance",
                "stored_frozen_balance",
                "computed_pending_balance",
                "computed_available_balance",
                "computed_frozen_balance",
                "pending_difference",
                "available_difference",
                "frozen_difference",
                "is_balanced",
            },
            set(response),
        )
        for forbidden in (
            "tenant_id",
            "ledger_account_id",
            "account_id",
            "ledger_entry_id",
            "raw_metadata",
            "metadata_json",
            "credentials",
            "credentials_encrypted",
            "token",
            "secret",
            "api_key",
            "password",
            "key_hash",
        ):
            self.assertNotIn(forbidden, response)

    def test_withdrawal_schema_exposes_masked_address_only(self) -> None:
        schema = app.openapi()
        request = schema["components"]["schemas"]["CreateTenantWithdrawalRequest"]["properties"]
        response = schema["components"]["schemas"]["TenantWithdrawalItem"]["properties"]
        list_response = schema["components"]["schemas"]["ListTenantWithdrawalsResponse"]["properties"]

        self.assertEqual({"amount", "network", "address", "currency"}, set(request))
        self.assertEqual(
            {
                "withdrawal_id",
                "amount",
                "currency",
                "network",
                "address_masked",
                "status",
                "requested_at",
                "payout_reference",
                "payout_proof_url",
                "reviewed_at",
                "completed_at",
            },
            set(response),
        )
        self.assertEqual({"withdrawals"}, set(list_response))
        self.assertEqual(
            "#/components/schemas/TenantWithdrawalItem",
            list_response["withdrawals"]["items"]["$ref"],
        )
        for forbidden in (
            "tenant_id",
            "address",
            "address_encrypted",
            "destination",
            "destination_encrypted",
            "admin_note",
            "credentials",
            "credentials_encrypted",
            "token",
            "secret",
            "secret_key",
            "api_key",
            "password",
            "private_key",
            "raw_payload",
        ):
            self.assertNotIn(forbidden, response)
            self.assertNotIn(forbidden, list_response)
        for forbidden in (
            "tenant_id",
            "address_encrypted",
            "credentials",
            "credentials_encrypted",
            "token",
            "secret",
            "api_key",
            "password",
            "private_key",
        ):
            self.assertNotIn(forbidden, request)

    def test_payment_config_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        request = schema["components"]["schemas"]["UpdateTenantEpusdtConfigRequest"]["properties"]
        response = schema["components"]["schemas"]["TenantEpusdtConfigResponse"]["properties"]
        disabled = schema["components"]["schemas"]["DisableTenantEpusdtConfigResponse"]["properties"]

        self.assertIn("base_url", request)
        self.assertIn("pid", request)
        self.assertIn("secret_key", request)
        self.assertIn("token", request)
        self.assertIn("network", request)
        self.assertEqual(
            {"provider", "enabled", "scope_type", "base_url", "pid_masked", "asset", "network", "key_configured"},
            set(response),
        )
        self.assertEqual({"provider", "disabled"}, set(disabled))
        for forbidden in (
            "credentials",
            "credentials_encrypted",
            "token",
            "secret",
            "secret_key",
            "api_key",
            "password",
            "private_key",
            "config_encrypted",
        ):
            self.assertNotIn(forbidden, response)
            self.assertNotIn(forbidden, disabled)
        for forbidden in ("config_encrypted", "credentials", "api_key", "password", "private_key"):
            self.assertNotIn(forbidden, request)

    def test_generic_payment_provider_config_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        request_schema = schema["components"]["schemas"]["UpdateTenantPaymentProviderConfigRequest"]
        request = request_schema["properties"]
        response = schema["components"]["schemas"]["TenantPaymentProviderConfigResponse"]["properties"]
        disabled = schema["components"]["schemas"]["DisableTenantPaymentProviderConfigResponse"]["properties"]

        self.assertFalse(request_schema.get("additionalProperties", True))
        self.assertIn("gateway_url", request)
        self.assertIn("merchant_id", request)
        self.assertIn("key", request)
        self.assertIn("secret_key", request)
        self.assertIn("cny_per_usdt", request)
        self.assertIn("min_usdt_amount", request)
        self.assertIn("timeout_seconds", request)
        self.assertEqual(
            {
                "provider",
                "enabled",
                "scope_type",
                "gateway_url",
                "merchant_id_masked",
                "monitor_address_masked",
                "asset",
                "network",
                "chain_type",
                "payment_type",
                "device",
                "return_url_configured",
                "subject",
                "cny_per_usdt",
                "min_usdt_amount",
                "timeout_seconds",
                "key_configured",
            },
            set(response),
        )
        self.assertEqual({"provider", "disabled"}, set(disabled))
        for forbidden in (
            "credentials",
            "credentials_encrypted",
            "token",
            "secret",
            "secret_key",
            "api_key",
            "password",
            "private_key",
            "config_encrypted",
            "raw_payload",
        ):
            self.assertNotIn(forbidden, response)
            self.assertNotIn(forbidden, disabled)

    def test_payment_provider_list_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        response = schema["components"]["schemas"]["ListTenantPaymentProvidersResponse"]["properties"]
        item = schema["components"]["schemas"]["TenantPaymentProviderItem"]["properties"]

        self.assertEqual({"providers"}, set(response))
        self.assertEqual(
            {
                "provider_name",
                "display_name",
                "integration_kind",
                "contract_name",
                "production_ready",
                "staging_verified",
                "tenant_configurable",
                "platform_configurable",
                "create_payment_available",
                "callback_available",
                "query_order_available",
                "reconcile_available",
                "offline_only",
                "supported_assets",
                "supported_networks",
            },
            set(item),
        )
        for forbidden in (
            "gateway_url",
            "return_url",
            "merchant_id",
            "pid",
            "monitor_address",
            "provider_trade_no",
            "signature",
            "signing_text",
            "credentials",
            "credentials_encrypted",
            "token",
            "secret",
            "secret_key",
            "api_key",
            "password",
            "private_key",
            "config_encrypted",
            "raw_payload",
        ):
            self.assertNotIn(forbidden, item)
            self.assertNotIn(forbidden, response)

    def test_usdt_trc20_direct_provider_remains_offline_only_without_chain_runtime_actions(self) -> None:
        from app.services.payments.configs import payment_provider_summary

        schema = app.openapi()
        provider = payment_provider_summary("usdt_trc20_direct")

        self.assertEqual("usdt_trc20_direct", provider.provider_name)
        self.assertEqual("offline_direct_chain_config", provider.integration_kind)
        self.assertEqual("usdt_trc20_direct_offline_config_v1", provider.contract_name)
        self.assertFalse(provider.production_ready)
        self.assertFalse(provider.staging_verified)
        self.assertTrue(provider.create_payment_available)
        self.assertFalse(provider.callback_available)
        self.assertFalse(provider.query_order_available)
        self.assertFalse(provider.reconcile_available)
        self.assertTrue(provider.offline_only)
        self.assertEqual(("USDT",), provider.supported_assets)
        self.assertEqual(("TRC20",), provider.supported_networks)

        schema_names = set(schema["components"]["schemas"])
        self.assertNotIn("Trc20DirectTransfer", schema_names)
        self.assertNotIn("Trc20DirectTransferItem", schema_names)
        for forbidden_path in (
            "/api/v1/tenant/payments/trc20-direct/scan",
            "/api/v1/tenant/payments/trc20-direct/reconcile",
            "/api/v1/tenant/payments/trc20-direct/callback",
            "/api/v1/tenant/payments/trc20-direct/create",
        ):
            self.assertNotIn(forbidden_path, schema["paths"])

    def test_trc20_direct_transfer_observation_operation_is_documented_as_tenant_admin(self) -> None:
        schema = app.openapi()
        expected_security = [{"TenantAdminBearer": []}, {"TenantAdminApiKeyHeader": []}]
        path = "/api/v1/tenant/payments/trc20-direct/transfers"
        operation = schema["paths"][path]["get"]

        self.assertEqual(expected_security, operation["security"])
        self.assertEqual({"get"}, {method for method in schema["paths"][path] if method in {"get", "post", "put", "patch", "delete"}})
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertIn("X-Faka-Timestamp", header_names)
        self.assertIn("X-Faka-Signature", header_names)
        self.assertEqual("HMAC-SHA256", operation["x-fakabot-signature"]["algorithm"])
        self.assertEqual(
            "TENANT_ADMIN_REQUIRE_SIGNATURE",
            operation["x-fakabot-signature"]["requiredByConfig"],
        )

    def test_trc20_direct_transfer_observation_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        response = schema["components"]["schemas"]["TenantTrc20DirectTransferListResponse"]["properties"]
        item = schema["components"]["schemas"]["TenantTrc20DirectTransferItem"]["properties"]

        self.assertEqual({"transfers"}, set(response))
        self.assertEqual(
            {
                "tx_hash",
                "block_number",
                "timestamp_ms",
                "block_timestamp",
                "from_address_masked",
                "to_address_masked",
                "contract_address",
                "amount",
                "confirmations",
                "match_status",
                "out_trade_no",
                "matched_at",
                "created_at",
            },
            set(item),
        )
        for forbidden in (
            "id",
            "tenant_id",
            "payment_id",
            "order_id",
            "raw_payload",
            "payload_json",
            "metadata_json",
            "from_address",
            "to_address",
            "provider_trade_no",
            "payment_url",
            "raw_request",
            "raw_response",
            "credentials",
            "credentials_encrypted",
            "token",
            "secret",
            "secret_key",
            "api_key",
            "password",
            "private_key",
        ):
            self.assertNotIn(forbidden, item)
            self.assertNotIn(forbidden, response)

    def test_payment_callback_failure_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        response = schema["components"]["schemas"]["ListTenantPaymentCallbackFailuresResponse"]["properties"]
        item = schema["components"]["schemas"]["TenantPaymentCallbackFailureItem"]["properties"]

        self.assertEqual({"failures"}, set(response))
        self.assertEqual(
            {
                "callback_id",
                "created_at",
                "processed_at",
                "order_id",
                "out_trade_no",
                "order_status",
                "provider",
                "process_status",
                "failure_reason",
            },
            set(item),
        )
        for forbidden in (
            "payload_json",
            "raw_payload",
            "metadata_json",
            "payload_hash",
            "provider_trade_no",
            "payment_url",
            "raw_request_hash",
            "signature",
            "signing_text",
            "credentials",
            "credentials_encrypted",
            "token",
            "secret",
            "secret_key",
            "api_key",
            "password",
            "private_key",
            "config_encrypted",
        ):
            self.assertNotIn(forbidden, item)
            self.assertNotIn(forbidden, response)

    def test_payment_callback_rejection_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        response = schema["components"]["schemas"]["ListTenantPaymentCallbackRejectionsResponse"]["properties"]
        item = schema["components"]["schemas"]["TenantPaymentCallbackRejectionItem"]["properties"]

        self.assertEqual({"rejections"}, set(response))
        self.assertEqual(
            {
                "audit_log_id",
                "created_at",
                "provider",
                "reason_category",
                "failure_reason",
                "http_status",
                "out_trade_no",
                "order_id",
                "order_status",
                "payload_field_count",
            },
            set(item),
        )
        for forbidden in (
            "payload_json",
            "metadata_json",
            "payload_hash",
            "payload",
            "provider_trade_no",
            "raw_request",
            "raw_response",
            "headers",
            "signature",
            "signing_text",
            "gateway_response",
            "gateway_url",
            "payment_url",
            "credentials",
            "credentials_encrypted",
            "token",
            "secret",
            "secret_key",
            "api_key",
            "authorization",
            "cookie",
            "password",
            "private_key",
        ):
            self.assertNotIn(forbidden, item)
            self.assertNotIn(forbidden, response)

    def test_order_diagnostics_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        response = schema["components"]["schemas"]["OrderDiagnosticsResponse"]["properties"]
        payment = schema["components"]["schemas"]["OrderPaymentDiagnosticItem"]["properties"]
        callback = schema["components"]["schemas"]["OrderPaymentCallbackDiagnosticItem"]["properties"]
        delivery = schema["components"]["schemas"]["OrderDeliveryDiagnosticItem"]["properties"]
        external = schema["components"]["schemas"]["OrderExternalFulfillmentDiagnosticItem"]["properties"]
        trc20_direct = schema["components"]["schemas"]["OrderTrc20DirectDiagnosticItem"]["properties"]

        self.assertEqual(
            {
                "order_id",
                "out_trade_no",
                "source_type",
                "status",
                "payment_mode",
                "payment_provider",
                "amount",
                "currency",
                "created_at",
                "expires_at",
                "paid_at",
                "delivered_at",
                "payment_count",
                "callback_count",
                "callback_status_counts",
                "payments",
                "callbacks",
                "delivery",
                "external_fulfillment",
                "trc20_direct",
            },
            set(response),
        )
        self.assertEqual(
            {"payment_id", "provider", "status", "amount", "currency", "has_payment_url", "created_at", "paid_at"},
            set(payment),
        )
        self.assertEqual(
            {"callback_id", "provider", "process_status", "failure_reason", "created_at", "processed_at"},
            set(callback),
        )
        self.assertEqual(
            {
                "delivery_record_id",
                "delivery_type",
                "status",
                "failure_reason",
                "has_inventory_item",
                "has_uploaded_file",
                "has_telegram_chat",
                "created_at",
                "updated_at",
                "sent_at",
            },
            set(delivery),
        )
        self.assertEqual(
            {
                "expected",
                "attempt_count",
                "latest_attempt_status",
                "latest_attempt_source",
                "latest_attempt_at",
                "latest_failure_stage",
                "latest_failure_category",
                "latest_failure_retryable",
                "latest_upstream_status_code",
                "latest_item_count",
                "latest_delivery_record_linked",
            },
            set(external),
        )
        self.assertEqual(
            {
                "expected",
                "transfer_count",
                "latest_match_status",
                "latest_confirmations",
                "latest_matched_at",
                "latest_amount",
            },
            set(trc20_direct),
        )
        for forbidden in (
            "tenant_id",
            "supplier_tenant_id",
            "supplier_settlement_amount",
            "reseller_settlement_amount",
            "locked_inventory_item_id",
            "inventory_item_id",
            "uploaded_file_id",
            "telegram_chat_id",
            "storage_key",
            "content",
            "content_hash",
            "payment_url",
            "provider_trade_no",
            "payload_json",
            "payload_hash",
            "raw_payload",
            "raw_request_hash",
            "idempotency_key",
            "signature",
            "signing_text",
            "credentials",
            "credentials_encrypted",
            "attempt_id",
            "provider_name",
            "external_product_id",
            "external_order_id",
            "source_key",
            "connection_id",
            "failure_fingerprint",
            "items",
            "message",
            "token",
            "secret",
            "secret_key",
            "api_key",
            "password",
            "private_key",
            "config_encrypted",
        ):
            self.assertNotIn(forbidden, response)
            self.assertNotIn(forbidden, payment)
            self.assertNotIn(forbidden, callback)
            self.assertNotIn(forbidden, delivery)
            self.assertNotIn(forbidden, external)
            self.assertNotIn(forbidden, trc20_direct)
        for forbidden_external in ("delivery_record_id", "failure_reason", "product_id"):
            self.assertNotIn(forbidden_external, external)
        for forbidden_trc20_direct in (
            "tx_hash",
            "from_address",
            "to_address",
            "id",
            "tenant_id",
            "payment_id",
            "order_id",
            "raw_payload",
            "payload_json",
            "metadata_json",
        ):
            self.assertNotIn(forbidden_trc20_direct, trc20_direct)

    def test_tenant_audit_log_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        response = schema["components"]["schemas"]["ListTenantAuditLogsResponse"]["properties"]
        item = schema["components"]["schemas"]["TenantAuditLogItem"]["properties"]

        self.assertEqual({"audit_logs"}, set(response))
        self.assertEqual(
            {
                "audit_log_id",
                "created_at",
                "actor_telegram_user_id",
                "actor_username",
                "action",
                "target_type",
                "target_id",
                "metadata",
            },
            set(item),
        )
        for forbidden in (
            "tenant_id",
            "actor_user_id",
            "metadata_json",
            "raw_payload",
            "payload",
            "payload_json",
            "payload_hash",
            "signature",
            "signing_text",
            "sign",
            "token",
            "encrypted_token",
            "secret",
            "secret_key",
            "api_key",
            "plain_key",
            "key_hash",
            "password",
            "authorization",
            "cookie",
            "credentials",
            "credentials_encrypted",
            "config_encrypted",
            "payment_url",
            "provider_trade_no",
            "content",
            "content_encrypted",
            "storage_key",
            "headers",
            "raw_request",
            "raw_response",
        ):
            self.assertNotIn(forbidden, item)
            self.assertNotIn(forbidden, response)

    def test_tenant_risk_observability_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        disputes_response = schema["components"]["schemas"]["ListTenantRiskDisputesResponse"]["properties"]
        dispute = schema["components"]["schemas"]["TenantRiskDisputeItem"]["properties"]
        after_sales_response = schema["components"]["schemas"]["ListTenantRiskAfterSalesResponse"]["properties"]
        after_sale = schema["components"]["schemas"]["TenantRiskAfterSaleItem"]["properties"]

        self.assertEqual({"disputes"}, set(disputes_response))
        self.assertEqual({"after_sales"}, set(after_sales_response))
        self.assertEqual(
            {
                "dispute_id",
                "order_id",
                "out_trade_no",
                "buyer_telegram_user_id",
                "source_type",
                "order_status",
                "amount",
                "currency",
                "status",
                "reason",
                "resolution",
                "created_at",
                "updated_at",
            },
            set(dispute),
        )
        self.assertEqual(
            {
                "case_id",
                "order_id",
                "out_trade_no",
                "buyer_telegram_user_id",
                "source_type",
                "order_status",
                "amount",
                "currency",
                "case_type",
                "status",
                "requested_amount",
                "refunded_amount",
                "reason",
                "resolution",
                "created_at",
                "updated_at",
            },
            set(after_sale),
        )
        for forbidden in (
            "tenant_id",
            "refund_id",
            "metadata_json",
            "payload",
            "payload_json",
            "raw_payload",
            "payment_url",
            "provider_trade_no",
            "token",
            "secret",
            "secret_key",
            "api_key",
            "authorization",
            "cookie",
            "credentials",
            "storage_key",
            "payout_reference",
            "payout_proof_url",
        ):
            self.assertNotIn(forbidden, disputes_response)
            self.assertNotIn(forbidden, dispute)
            self.assertNotIn(forbidden, after_sales_response)
            self.assertNotIn(forbidden, after_sale)

    def test_report_export_jobs_schema_exposes_safe_fields_only(self) -> None:
        schema = app.openapi()
        response = schema["components"]["schemas"]["ListTenantReportExportJobsResponse"]["properties"]
        item = schema["components"]["schemas"]["TenantReportExportJobItem"]["properties"]

        self.assertEqual({"export_jobs"}, set(response))
        self.assertEqual(
            {
                "export_job_id",
                "report_type",
                "scope_type",
                "status",
                "row_count",
                "download_available",
                "failure_reason",
                "expires_at",
                "created_at",
                "started_at",
                "finished_at",
            },
            set(item),
        )
        for forbidden in (
            "tenant_id",
            "requested_by_user_id",
            "filename",
            "storage_key",
            "download_token",
            "download_url",
            "error_message",
            "local_path",
            "payload",
            "payload_json",
            "payment_url",
            "provider_trade_no",
            "token",
            "secret",
            "api_key",
            "authorization",
            "cookie",
            "credentials",
        ):
            self.assertNotIn(forbidden, response)
            self.assertNotIn(forbidden, item)

    def test_create_report_export_job_schema_accepts_report_type_only_and_returns_safe_pending_summary(self) -> None:
        schema = app.openapi()
        operation = schema["paths"]["/api/v1/tenant/reports/export-jobs"]["post"]
        request_schema_name = (
            operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
        )
        response_schema_name = (
            operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
        )
        request_schema = schema["components"]["schemas"][request_schema_name]
        request = request_schema["properties"]
        response_schema = schema["components"]["schemas"][response_schema_name]
        response = response_schema["properties"]
        if "export_job" in response:
            item_schema_name = response["export_job"]["$ref"].rsplit("/", 1)[-1]
            item = schema["components"]["schemas"][item_schema_name]["properties"]
        else:
            item = response

        self.assertEqual("CreateTenantReportExportJobRequest", request_schema_name)
        self.assertEqual({"report_type"}, set(request))
        self.assertFalse(request_schema.get("additionalProperties", True))
        self.assertEqual(
            {
                "export_job_id",
                "report_type",
                "scope_type",
                "status",
                "row_count",
                "download_available",
                "failure_reason",
                "expires_at",
                "created_at",
                "started_at",
                "finished_at",
            },
            set(item),
        )
        self.assertIn("status", item)
        for forbidden in (
            "tenant_id",
            "requested_by_user_id",
            "filename",
            "download_url",
            "download_token",
            "storage_key",
            "path",
            "local_path",
            "raw_error",
            "error_message",
            "payload",
            "payload_json",
            "payment_url",
            "provider_trade_no",
            "token",
            "secret",
            "api_key",
            "authorization",
            "cookie",
            "credentials",
        ):
            self.assertNotIn(forbidden, request)
            self.assertNotIn(forbidden, response)
            self.assertNotIn(forbidden, item)

    def test_external_sources_list_schema_exposes_provider_names_only(self) -> None:
        schema = app.openapi()
        response = schema["components"]["schemas"]["ListExternalSourceProvidersResponse"]["properties"]
        item = schema["components"]["schemas"]["ExternalSourceProviderItem"]["properties"]

        self.assertIn("providers", response)
        self.assertIn("provider_name", item)
        self.assertIn("integration_kind", item)
        self.assertIn("contract_name", item)
        self.assertIn("production_ready", item)
        self.assertIn("staging_verified", item)
        self.assertIn("catalog_sync_available", item)
        self.assertIn("catalog_context_available", item)
        self.assertIn("catalog_product_available", item)
        self.assertIn("catalog_product_context_available", item)
        self.assertIn("order_available", item)
        self.assertIn("order_context_available", item)
        self.assertIn("delivery_available", item)
        self.assertIn("delivery_context_available", item)
        self.assertIn("auto_fulfillment_idempotent_available", item)
        self.assertNotIn("credentials", item)
        self.assertNotIn("connection_id", item)
        self.assertNotIn("source_key", item)
        self.assertNotIn("api_key", item)
        self.assertNotIn("password", item)
        self.assertNotIn("secret", item)
        self.assertNotIn("token", item)

    def test_external_catalog_product_sync_schema_exposes_safe_fields(self) -> None:
        schema = app.openapi()
        request = schema["components"]["schemas"]["SyncExternalCatalogProductRequest"]["properties"]
        response = schema["components"]["schemas"]["SyncExternalCatalogResponse"]["properties"]
        product = schema["components"]["schemas"]["SyncedExternalCatalogProduct"]["properties"]

        self.assertIn("external_product_id", request)
        self.assertIn("connection_id", request)
        self.assertIn("source_key", request)
        self.assertNotIn("cursor", request)
        self.assertNotIn("limit", request)
        self.assertNotIn("max_pages", request)
        self.assertIn("products", response)
        for forbidden in ("credentials", "credentials_encrypted", "token", "secret", "api_key", "password"):
            self.assertNotIn(forbidden, request)
            self.assertNotIn(forbidden, response)
            self.assertNotIn(forbidden, product)
        self.assertNotIn("raw_payload", product)
        self.assertNotIn("content", product)
        self.assertNotIn("key_hash", product)

    def test_external_source_connection_schema_does_not_expose_credentials(self) -> None:
        schema = app.openapi()
        request = schema["components"]["schemas"]["CreateExternalSourceConnectionRequest"]["properties"]
        item = schema["components"]["schemas"]["ExternalSourceConnectionItem"]["properties"]

        self.assertIn("credentials", request)
        self.assertIn("credential_fields", item)
        self.assertIn("provider_name", item)
        self.assertIn("source_key", item)
        self.assertNotIn("credentials", item)
        self.assertNotIn("credentials_encrypted", item)
        self.assertNotIn("token", item)
        self.assertNotIn("secret", item)

    def test_public_product_schema_does_not_expose_external_mapping_fields(self) -> None:
        schema = app.openapi()
        public_product = schema["components"]["schemas"]["PublicProduct"]["properties"]

        self.assertNotIn("external_source", public_product)
        self.assertNotIn("source_key", public_product)
        self.assertNotIn("external_id", public_product)

    def test_public_store_response_schemas_do_not_expose_internal_fields(self) -> None:
        schema = app.openapi()
        forbidden_fields = {
            "tenant_id",
            "tenant_bot_id",
            "supplier_tenant_id",
            "reseller_product_id",
            "inventory_id",
            "inventory_item_id",
            "locked_inventory_item_id",
            "payment_provider",
            "payment_provider_config",
            "payment_provider_config_id",
            "external_source",
            "source_key",
            "external_id",
            "credentials",
            "credentials_encrypted",
            "token",
            "secret",
            "api_key",
            "password",
            "key_hash",
            "content",
            "storage_key",
        }

        for schema_name in [
            "PublicStoreProfile",
            "PublicProduct",
            "PublicOrderResponse",
            "PublicPaymentResponse",
        ]:
            with self.subTest(schema_name=schema_name):
                properties = schema["components"]["schemas"][schema_name]["properties"]
                self.assertTrue(forbidden_fields.isdisjoint(properties.keys()))

    def test_public_store_order_request_schema_does_not_accept_internal_fields(self) -> None:
        schema = app.openapi()
        request = schema["components"]["schemas"]["CreatePublicOrderRequest"]["properties"]
        forbidden_fields = {
            "tenant_id",
            "tenant_bot_id",
            "supplier_tenant_id",
            "reseller_product_id",
            "inventory_id",
            "inventory_item_id",
            "locked_inventory_item_id",
            "payment_provider",
            "payment_provider_config",
            "payment_provider_config_id",
            "external_source",
            "source_key",
            "external_id",
            "credentials",
            "credentials_encrypted",
            "token",
            "secret",
            "api_key",
            "password",
            "key_hash",
            "content",
            "storage_key",
        }

        self.assertTrue(forbidden_fields.isdisjoint(request.keys()))


if __name__ == "__main__":
    unittest.main()
