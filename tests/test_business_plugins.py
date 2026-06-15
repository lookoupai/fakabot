from __future__ import annotations

import unittest

try:
    from app.services.business_plugins import (
        BUSINESS_PLUGIN_KIND_EXTERNAL_SOURCE,
        BUSINESS_PLUGIN_KIND_PAYMENT,
        BusinessPluginManifest,
        BusinessPluginRegistry,
        external_source_summary_to_plugin_manifest,
        is_plugin_entrypoint_allowed,
        payment_summary_to_plugin_manifest,
    )
    from app.services.external_sources.registry import ExternalProviderCapabilities, ExternalProviderSummary
    from app.services.payments.configs import PaymentProviderSummary
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过业务插件合同测试：{exc.name}") from exc


class BusinessPluginManifestTest(unittest.TestCase):
    def test_manifest_from_mapping_normalizes_safe_fields(self) -> None:
        manifest = BusinessPluginManifest.from_mapping(
            {
                "plugin_id": " trx_swap ",
                "name": "TRX 兑换",
                "version": "0.1.0",
                "kind": "tenant_tool",
                "entrypoint": "fakabot_ext_trx_swap:create_plugin",
                "contract_version": "tenant_tool_v1",
                "capabilities": {"quote": True, "swap": False},
                "production_ready": False,
                "staging_verified": False,
                "offline_only": True,
                "tenant_configurable": True,
                "platform_configurable": False,
            }
        )

        self.assertEqual("trx_swap", manifest.plugin_id)
        self.assertEqual("TRX 兑换", manifest.name)
        self.assertEqual("tenant_tool", manifest.kind)
        self.assertEqual({"quote": True, "swap": False}, dict(manifest.capabilities))
        self.assertTrue(manifest.entrypoint_allowed)
        self.assertTrue(manifest.requires_tenant_enablement)

    def test_manifest_requires_explicit_production_and_staging_flags(self) -> None:
        payload = {
            "plugin_id": "demo",
            "name": "Demo",
            "version": "0.1.0",
            "kind": "payment",
            "contract_version": "payment_v1",
            "capabilities": {},
        }

        with self.assertRaisesRegex(ValueError, "缺少字段"):
            BusinessPluginManifest.from_mapping(payload)

    def test_manifest_rejects_invalid_identity_and_truthy_booleans(self) -> None:
        valid_payload = {
            "plugin_id": "demo",
            "name": "Demo",
            "version": "0.1.0",
            "kind": "payment",
            "contract_version": "payment_v1",
            "capabilities": {},
            "production_ready": False,
            "staging_verified": False,
        }

        for field_name, value in (
            ("plugin_id", "Bad Plugin"),
            ("kind", "unknown"),
            ("contract_version", "payment v1"),
            ("production_ready", "false"),
            ("staging_verified", 0),
            ("offline_only", "true"),
        ):
            payload = dict(valid_payload)
            payload[field_name] = value
            with self.subTest(field_name=field_name):
                with self.assertRaises(ValueError):
                    BusinessPluginManifest.from_mapping(payload)

    def test_capabilities_require_boolean_values_and_safe_names(self) -> None:
        base_payload = {
            "plugin_id": "demo",
            "name": "Demo",
            "version": "0.1.0",
            "kind": "payment",
            "contract_version": "payment_v1",
            "production_ready": False,
            "staging_verified": False,
        }

        for capabilities in ({"bad name": True}, {"ok": "true"}, []):
            payload = dict(base_payload)
            payload["capabilities"] = capabilities
            with self.subTest(capabilities=capabilities):
                with self.assertRaises(ValueError):
                    BusinessPluginManifest.from_mapping(payload)

    def test_entrypoint_is_validated_but_not_executed(self) -> None:
        manifest = BusinessPluginManifest(
            plugin_id="demo",
            name="Demo",
            version="0.1.0",
            kind="payment",
            entrypoint="os:system",
            contract_version="payment_v1",
            capabilities={},
            production_ready=False,
            staging_verified=False,
        )

        self.assertFalse(manifest.entrypoint_allowed)
        self.assertFalse(is_plugin_entrypoint_allowed("os:system"))
        self.assertTrue(is_plugin_entrypoint_allowed("app.services.payments.configs:payment_provider_summary"))
        self.assertTrue(is_plugin_entrypoint_allowed("fakabot_ext_demo:create_plugin"))

    def test_registry_rejects_duplicate_plugins(self) -> None:
        registry = BusinessPluginRegistry()
        manifest = BusinessPluginManifest(
            plugin_id="demo",
            name="Demo",
            version="0.1.0",
            kind="payment",
            contract_version="payment_v1",
            capabilities={},
            production_ready=False,
            staging_verified=False,
        )

        registry.register(manifest)

        self.assertIs(manifest, registry.get(" demo "))
        self.assertEqual([manifest], registry.list())
        with self.assertRaisesRegex(ValueError, "已注册"):
            registry.register(manifest)


class BusinessPluginProviderSummaryTest(unittest.TestCase):
    def test_payment_summary_converts_to_plugin_manifest_without_secrets(self) -> None:
        manifest = payment_summary_to_plugin_manifest(
            PaymentProviderSummary(
                provider_name="epay_compatible",
                display_name="易支付兼容",
                integration_kind="offline_payment_page",
                contract_name="epay_compatible_offline_page_v1",
                production_ready=False,
                staging_verified=False,
                tenant_configurable=True,
                platform_configurable=False,
                create_payment_available=True,
                callback_available=True,
                query_order_available=False,
                reconcile_available=False,
                offline_only=True,
                supported_assets=("CNY", "USDT"),
                supported_networks=(),
            )
        )

        self.assertEqual("payment_epay_compatible", manifest.plugin_id)
        self.assertEqual(BUSINESS_PLUGIN_KIND_PAYMENT, manifest.kind)
        self.assertEqual("epay_compatible_offline_page_v1", manifest.contract_version)
        self.assertEqual(
            {
                "create_payment": True,
                "callback": True,
                "query_order": False,
                "reconcile": False,
            },
            dict(manifest.capabilities),
        )
        self.assertTrue(manifest.offline_only)
        self.assertNotIn("secret", repr(manifest).lower())

    def test_external_source_summary_converts_to_plugin_manifest(self) -> None:
        manifest = external_source_summary_to_plugin_manifest(
            ExternalProviderSummary(
                provider_name="mcy_shop",
                integration_kind="offline_fixture",
                contract_name="mcy_shop_offline_fixture_v1",
                production_ready=False,
                staging_verified=False,
                capabilities=ExternalProviderCapabilities(
                    catalog_sync_available=True,
                    catalog_context_available=True,
                    catalog_product_available=True,
                    catalog_product_context_available=True,
                    order_available=True,
                    order_context_available=True,
                    delivery_available=True,
                    delivery_context_available=True,
                    auto_fulfillment_idempotent_available=False,
                ),
            )
        )

        self.assertEqual("external_source_mcy_shop", manifest.plugin_id)
        self.assertEqual(BUSINESS_PLUGIN_KIND_EXTERNAL_SOURCE, manifest.kind)
        self.assertEqual("mcy_shop_offline_fixture_v1", manifest.contract_version)
        self.assertTrue(manifest.capabilities["catalog_sync"])
        self.assertTrue(manifest.capabilities["delivery_context"])
        self.assertFalse(manifest.capabilities["auto_fulfillment_idempotent"])
        self.assertTrue(manifest.offline_only)


if __name__ == "__main__":
    unittest.main()
