from __future__ import annotations

import unittest

try:
    from app.services.external_sources import (
        describe_provider,
        get_provider,
        get_provider_summary,
        list_providers,
        register_provider,
    )
    import app.services.external_sources.registry as provider_registry
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过外部 provider registry 测试：{exc.name}") from exc


class FullContextProvider:
    provider = "full"

    async def list_products(self, tenant_id, cursor=None, limit=50):
        raise AssertionError("capability inspection must not call provider methods")

    async def list_products_with_context(self, context, cursor=None, limit=50):
        raise AssertionError("capability inspection must not call provider methods")

    async def get_product(self, tenant_id, external_product_id):
        raise AssertionError("capability inspection must not call provider methods")

    async def get_product_with_context(self, context, external_product_id):
        raise AssertionError("capability inspection must not call provider methods")

    async def create_order(self, tenant_id, request):
        raise AssertionError("capability inspection must not call provider methods")

    async def create_order_with_context(self, context, request):
        raise AssertionError("capability inspection must not call provider methods")

    async def query_order(self, tenant_id, external_order_id):
        raise AssertionError("capability inspection must not call provider methods")

    async def query_order_with_context(self, context, external_order_id):
        raise AssertionError("capability inspection must not call provider methods")

    async def fetch_delivery(self, tenant_id, external_order_id):
        raise AssertionError("capability inspection must not call provider methods")

    async def fetch_delivery_with_context(self, context, external_order_id):
        raise AssertionError("capability inspection must not call provider methods")


class IdempotentContextProvider(FullContextProvider):
    provider = "idempotent"
    auto_fulfillment_idempotent = True


class MetadataProvider(FullContextProvider):
    provider = "metadata"
    integration_kind = "offline_fixture"
    contract_name = "metadata_contract_v1"
    production_ready = True
    staging_verified = True


class TruthyMetadataProvider(FullContextProvider):
    provider = "truthy-metadata"
    production_ready = "true"
    staging_verified = 1


class TruthyOptInContextProvider(FullContextProvider):
    provider = "truthy"
    auto_fulfillment_idempotent = "true"


class LegacyProvider:
    provider = "legacy"

    async def list_products(self, tenant_id, cursor=None, limit=50):
        raise AssertionError("capability inspection must not call provider methods")

    async def get_product(self, tenant_id, external_product_id):
        raise AssertionError("capability inspection must not call provider methods")

    async def create_order(self, tenant_id, request):
        raise AssertionError("capability inspection must not call provider methods")

    async def query_order(self, tenant_id, external_order_id):
        raise AssertionError("capability inspection must not call provider methods")

    async def fetch_delivery(self, tenant_id, external_order_id):
        raise AssertionError("capability inspection must not call provider methods")


class IdempotentLegacyProvider(LegacyProvider):
    provider = "legacy-idempotent"
    auto_fulfillment_idempotent = True


class ListOnlyCatalogProvider:
    provider = "list-only"

    async def list_products(self, tenant_id, cursor=None, limit=50):
        raise AssertionError("capability inspection must not call provider methods")


class PartialOrderProvider:
    provider = "partial"

    async def create_order(self, tenant_id, request):
        raise AssertionError("capability inspection must not call provider methods")


class ProbeOnlyProvider:
    provider = "probe"

    async def health_check(self):
        raise AssertionError("capability inspection must not call health_check")

    async def probe(self):
        raise AssertionError("capability inspection must not call probe")


class InvalidNameProvider:
    def __init__(self, provider) -> None:
        self.provider = provider


class ExternalProviderRegistryTest(unittest.TestCase):
    def test_describe_provider_reports_capabilities_without_calling_provider(self) -> None:
        summary = describe_provider(FullContextProvider())

        self.assertEqual("full", summary.provider_name)
        self.assertTrue(summary.capabilities.catalog_sync_available)
        self.assertTrue(summary.capabilities.catalog_context_available)
        self.assertTrue(summary.capabilities.catalog_product_available)
        self.assertTrue(summary.capabilities.catalog_product_context_available)
        self.assertTrue(summary.capabilities.order_available)
        self.assertTrue(summary.capabilities.order_context_available)
        self.assertTrue(summary.capabilities.delivery_available)
        self.assertTrue(summary.capabilities.delivery_context_available)
        self.assertFalse(summary.capabilities.auto_fulfillment_idempotent_available)

    def test_auto_fulfillment_capability_defaults_to_false(self) -> None:
        legacy_summary = describe_provider(LegacyProvider())
        context_summary = describe_provider(FullContextProvider())
        probe_summary = describe_provider(ProbeOnlyProvider())

        self.assertFalse(legacy_summary.capabilities.auto_fulfillment_idempotent_available)
        self.assertFalse(context_summary.capabilities.auto_fulfillment_idempotent_available)
        self.assertFalse(probe_summary.capabilities.auto_fulfillment_idempotent_available)

    def test_describe_provider_reports_safe_integration_metadata(self) -> None:
        default_summary = describe_provider(FullContextProvider())
        metadata_summary = describe_provider(MetadataProvider())

        self.assertEqual("custom", default_summary.integration_kind)
        self.assertIsNone(default_summary.contract_name)
        self.assertFalse(default_summary.production_ready)
        self.assertFalse(default_summary.staging_verified)
        self.assertEqual("offline_fixture", metadata_summary.integration_kind)
        self.assertEqual("metadata_contract_v1", metadata_summary.contract_name)
        self.assertTrue(metadata_summary.production_ready)
        self.assertTrue(metadata_summary.staging_verified)

    def test_production_and_staging_flags_require_strict_bool_true(self) -> None:
        summary = describe_provider(TruthyMetadataProvider())

        self.assertFalse(summary.production_ready)
        self.assertFalse(summary.staging_verified)

    def test_auto_fulfillment_capability_requires_idempotent_out_trade_no_opt_in_and_context_methods(self) -> None:
        summary = describe_provider(IdempotentContextProvider())

        self.assertEqual("idempotent", summary.provider_name)
        self.assertTrue(summary.capabilities.order_context_available)
        self.assertTrue(summary.capabilities.delivery_context_available)
        self.assertTrue(summary.capabilities.auto_fulfillment_idempotent_available)

    def test_auto_fulfillment_capability_rejects_truthy_non_bool_or_legacy_provider(self) -> None:
        truthy_summary = describe_provider(TruthyOptInContextProvider())
        legacy_summary = describe_provider(IdempotentLegacyProvider())

        self.assertFalse(truthy_summary.capabilities.auto_fulfillment_idempotent_available)
        self.assertTrue(legacy_summary.capabilities.order_available)
        self.assertTrue(legacy_summary.capabilities.delivery_available)
        self.assertFalse(legacy_summary.capabilities.order_context_available)
        self.assertFalse(legacy_summary.capabilities.delivery_context_available)
        self.assertFalse(legacy_summary.capabilities.auto_fulfillment_idempotent_available)

    def test_describe_provider_keeps_legacy_capabilities_without_context(self) -> None:
        summary = describe_provider(LegacyProvider())

        self.assertEqual("legacy", summary.provider_name)
        self.assertTrue(summary.capabilities.catalog_sync_available)
        self.assertFalse(summary.capabilities.catalog_context_available)
        self.assertTrue(summary.capabilities.catalog_product_available)
        self.assertFalse(summary.capabilities.catalog_product_context_available)
        self.assertTrue(summary.capabilities.order_available)
        self.assertFalse(summary.capabilities.order_context_available)
        self.assertTrue(summary.capabilities.delivery_available)
        self.assertFalse(summary.capabilities.delivery_context_available)
        self.assertFalse(summary.capabilities.auto_fulfillment_idempotent_available)

    def test_catalog_list_and_product_capabilities_are_independent(self) -> None:
        summary = describe_provider(ListOnlyCatalogProvider())

        self.assertEqual("list-only", summary.provider_name)
        self.assertTrue(summary.capabilities.catalog_sync_available)
        self.assertFalse(summary.capabilities.catalog_context_available)
        self.assertFalse(summary.capabilities.catalog_product_available)
        self.assertFalse(summary.capabilities.catalog_product_context_available)

    def test_describe_provider_rejects_partial_order_capability(self) -> None:
        summary = describe_provider(PartialOrderProvider())

        self.assertFalse(summary.capabilities.order_available)
        self.assertFalse(summary.capabilities.order_context_available)

    def test_describe_provider_does_not_call_health_or_probe_methods(self) -> None:
        summary = describe_provider(ProbeOnlyProvider())

        self.assertEqual("probe", summary.provider_name)
        self.assertFalse(summary.capabilities.catalog_sync_available)
        self.assertFalse(summary.capabilities.catalog_product_available)
        self.assertFalse(summary.capabilities.order_available)
        self.assertFalse(summary.capabilities.delivery_available)
        self.assertFalse(summary.capabilities.auto_fulfillment_idempotent_available)

    def test_provider_name_validation_rejects_invalid_values_without_attribute_error(self) -> None:
        invalid_names = (None, 123, "", " ", "ACG", "bad name", "bad.name", "中文", "acg/shop", "acg:shop")
        for provider_name in invalid_names:
            with self.subTest(provider_name=provider_name):
                with self.assertRaisesRegex(ValueError, "provider"):
                    describe_provider(InvalidNameProvider(provider_name))
                with self.assertRaisesRegex(ValueError, "provider"):
                    register_provider(InvalidNameProvider(provider_name))
                with self.assertRaisesRegex(ValueError, "provider_name"):
                    get_provider(provider_name)
                with self.assertRaisesRegex(ValueError, "provider_name"):
                    get_provider_summary(provider_name)

    def test_register_and_get_provider_normalize_name_and_reject_duplicates(self) -> None:
        previous_providers = dict(provider_registry._providers)
        provider_registry._providers.clear()
        provider = InvalidNameProvider(" demo ")
        duplicate = InvalidNameProvider("demo")
        try:
            register_provider(provider)

            self.assertEqual(["demo"], list_providers())
            self.assertIs(provider, get_provider(" demo "))
            self.assertEqual("demo", describe_provider(provider).provider_name)
            with self.assertRaisesRegex(ValueError, "已注册"):
                register_provider(duplicate)
        finally:
            provider_registry._providers.clear()
            provider_registry._providers.update(previous_providers)


if __name__ == "__main__":
    unittest.main()
