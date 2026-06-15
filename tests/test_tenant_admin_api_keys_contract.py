from __future__ import annotations

import unittest
from datetime import datetime, timezone

try:
    from pydantic import ValidationError

    from app.services.api_keys import CreatedTenantApiKey, TenantApiKeySummary
    from app.web.tenant_admin import (
        _api_key_response,
        _created_api_key_response,
        _extract_api_key,
        _inventory_summary_response,
        _ensure_unique_sync_external_refs,
        _ensure_unique_sync_product_ids,
        _validate_sync_products,
        _sync_external_ref,
        _external_catalog_sync_source_from_connection,
        _external_catalog_sync_response,
        _external_source_connection_response,
        _external_source_provider_response,
        _normalize_external_identifier,
        _normalize_inventory_items,
        AdminProduct,
        CreateExternalSourceConnectionRequest,
        ListExternalSourceProvidersResponse,
        SyncExternalCatalogProductRequest,
        SyncExternalCatalogRequest,
        SyncedProductItem,
        SyncProductItem,
    )
    from app.services.external_sources.sync import ExternalCatalogSyncResult, SyncedExternalProduct
    from app.services.external_sources.connections import ExternalSourceConnectionSummary
    from app.services.external_sources.registry import ExternalProviderCapabilities, ExternalProviderSummary
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过 Tenant Admin API Key 契约测试：{exc.name}") from exc


class TenantAdminApiKeyContractTest(unittest.TestCase):
    def test_extract_api_key_prefers_header_key_and_accepts_bearer(self) -> None:
        self.assertEqual("fk_live_header", _extract_api_key("Bearer fk_live_bearer", " fk_live_header "))
        self.assertEqual("fk_live_bearer", _extract_api_key("Bearer fk_live_bearer", None))
        self.assertIsNone(_extract_api_key("Basic fk_live_bearer", None))

    def test_api_key_response_does_not_expose_hash_or_plain_key(self) -> None:
        summary = TenantApiKeySummary(
            api_key_id=1,
            name="worker",
            key_prefix="fk_live_abc",
            status="active",
            scopes=["orders:read"],
            ip_allowlist=["203.0.113.0/24"],
            created_at=datetime(2026, 6, 7, tzinfo=timezone.utc),
            last_used_at=None,
        )

        payload = _api_key_response(summary).model_dump()

        self.assertEqual(1, payload["api_key_id"])
        self.assertEqual("fk_live_abc", payload["key_prefix"])
        self.assertEqual(["orders:read"], payload["scopes"])
        self.assertEqual(["203.0.113.0/24"], payload["ip_allowlist"])
        self.assertNotIn("key_hash", payload)
        self.assertNotIn("plain_key", payload)

    def test_created_api_key_response_exposes_plain_key_once(self) -> None:
        created = CreatedTenantApiKey(
            api_key_id=2,
            name="new-worker",
            key_prefix="fk_live_xyz",
            plain_key="fk_live_secret",
            status="active",
            scopes=["tenant_admin:*"],
            ip_allowlist=[],
        )

        payload = _created_api_key_response(created).model_dump()

        self.assertEqual("fk_live_secret", payload["plain_key"])
        self.assertEqual(["tenant_admin:*"], payload["scopes"])
        self.assertEqual([], payload["ip_allowlist"])
        self.assertNotIn("key_hash", payload)

    def test_normalize_inventory_items_deduplicates_and_rejects_empty_payload(self) -> None:
        items, duplicated_count = _normalize_inventory_items([" card-a ", "card-b", "card-a", ""])

        self.assertEqual(["card-a", "card-b"], items)
        self.assertEqual(1, duplicated_count)
        with self.assertRaises(ValueError):
            _normalize_inventory_items([" ", ""])

    def test_inventory_summary_response_does_not_expose_inventory_content(self) -> None:
        payload = _inventory_summary_response(
            7,
            {
                "available": 3,
                "locked": 2,
                "used": 1,
                "failed": 4,
            },
        ).model_dump()

        self.assertEqual(7, payload["product_id"])
        self.assertEqual(3, payload["available_count"])
        self.assertEqual(2, payload["locked_count"])
        self.assertEqual(1, payload["used_count"])
        self.assertEqual(10, payload["total_count"])
        self.assertNotIn("items", payload)
        self.assertNotIn("content", payload)

    def test_sync_product_ids_must_be_unique_when_present(self) -> None:
        with self.assertRaises(ValueError):
            _ensure_unique_sync_product_ids(
                [
                    SyncProductItem(product_id=1, name="Product A", price="1", delivery_type="card_pool"),
                    SyncProductItem(product_id=1, name="Product B", price="2", delivery_type="card_pool"),
                ]
            )
        _ensure_unique_sync_product_ids(
            [
                SyncProductItem(product_id=1, name="Product A", price="1", delivery_type="card_pool"),
                SyncProductItem(name="Product B", price="2", delivery_type="card_pool"),
            ]
        )

    def test_sync_external_refs_must_be_unique_when_present(self) -> None:
        with self.assertRaises(ValueError):
            _ensure_unique_sync_external_refs(
                [
                    SyncProductItem(
                        external_source="acg",
                        source_key="shop-a",
                        external_id="sku-1",
                        name="Product A",
                        price="1",
                        delivery_type="card_pool",
                    ),
                    SyncProductItem(
                        external_source="acg",
                        source_key="shop-a",
                        external_id="sku-1",
                        name="Product B",
                        price="2",
                        delivery_type="card_pool",
                    ),
                ]
            )
        _ensure_unique_sync_external_refs(
            [
                SyncProductItem(
                    external_source="acg",
                    source_key="shop-a",
                    external_id="sku-1",
                    name="Product A",
                    price="1",
                    delivery_type="card_pool",
                ),
                SyncProductItem(
                    external_source="acg",
                    source_key="shop-b",
                    external_id="sku-1",
                    name="Product B",
                    price="2",
                    delivery_type="card_pool",
                ),
            ]
        )

    def test_sync_external_ref_defaults_and_normalizes_source_key(self) -> None:
        self.assertEqual(
            ("acg", "", "sku-1"),
            _sync_external_ref(
                SyncProductItem(
                    external_source=" acg ",
                    external_id=" sku-1 ",
                    name="Product A",
                    price="1",
                    delivery_type="card_pool",
                )
            ),
        )
        self.assertEqual(
            ("acg", "shop-a", "sku-1"),
            _sync_external_ref(
                SyncProductItem(
                    external_source="acg",
                    source_key=" shop-a ",
                    external_id="sku-1",
                    name="Product A",
                    price="1",
                    delivery_type="card_pool",
                )
            ),
        )
        with self.assertRaises(ValueError):
            _sync_external_ref(
                SyncProductItem(
                    external_source="ACG",
                    external_id="sku-1",
                    name="Product A",
                    price="1",
                    delivery_type="card_pool",
                )
            )

    def test_validate_sync_products_rejects_unsupported_status_and_delivery_type(self) -> None:
        with self.assertRaises(ValueError):
            _validate_sync_products(
                [SyncProductItem(name="Product A", price="1", delivery_type="unknown")]
            )
        with self.assertRaises(ValueError):
            _validate_sync_products(
                [SyncProductItem(name="Product A", price="1", delivery_type="card_pool", status="deleted")]
            )
        _validate_sync_products(
            [SyncProductItem(name="Product A", price="1", delivery_type="card_pool", status="draft")]
        )

    def test_validate_sync_products_requires_complete_external_ref(self) -> None:
        with self.assertRaises(ValueError):
            _validate_sync_products(
                [
                    SyncProductItem(
                        external_source="acg",
                        name="Product A",
                        price="1",
                        delivery_type="card_pool",
                    )
                ]
            )
        with self.assertRaises(ValueError):
            _validate_sync_products(
                [
                    SyncProductItem(
                        source_key="shop-a",
                        name="Product A",
                        price="1",
                        delivery_type="card_pool",
                    )
                ]
            )
        _validate_sync_products(
            [
                SyncProductItem(
                    external_source="acg",
                    source_key="shop-a",
                    external_id="sku-1",
                    name="Product A",
                    price="1",
                    delivery_type="card_pool",
                )
            ]
        )

    def test_product_contracts_include_external_mapping_without_sensitive_fields(self) -> None:
        admin_product = AdminProduct(
            id=1,
            external_source="acg",
            source_key="shop-a",
            external_id="sku-1",
            name="Product A",
            status="on",
            delivery_type="card_pool",
            price="1",
            currency="USDT",
            available_count=3,
        ).model_dump()
        synced_product = SyncedProductItem(
            product_id=1,
            external_source="acg",
            source_key="shop-a",
            external_id="sku-1",
            action="updated",
            status="on",
        ).model_dump()

        self.assertEqual("acg", admin_product["external_source"])
        self.assertEqual("shop-a", admin_product["source_key"])
        self.assertEqual("sku-1", admin_product["external_id"])
        self.assertEqual("acg", synced_product["external_source"])
        self.assertEqual("shop-a", synced_product["source_key"])
        self.assertEqual("sku-1", synced_product["external_id"])
        self.assertNotIn("content", admin_product)
        self.assertNotIn("key_hash", synced_product)

    def test_external_catalog_sync_response_exposes_summary_without_sensitive_fields(self) -> None:
        response = _external_catalog_sync_response(
            " acg ",
            " shop-a ",
            ExternalCatalogSyncResult(
                created_count=1,
                updated_count=2,
                skipped_count=1,
                next_cursor="next-page",
                products=[
                    SyncedExternalProduct(
                        product_id=7,
                        external_source="acg",
                        source_key="shop-a",
                        external_id="sku-1",
                        action="created",
                        status="draft",
                    ),
                    SyncedExternalProduct(
                        product_id=None,
                        external_source="acg",
                        source_key="shop-a",
                        external_id="sku-2",
                        action="skipped",
                        status="skipped",
                        skipped_reason="外部商品发货类型不受支持",
                    ),
                ],
            ),
            connection_id=7,
        ).model_dump()

        self.assertEqual("acg", response["provider_name"])
        self.assertEqual("shop-a", response["source_key"])
        self.assertEqual(7, response["connection_id"])
        self.assertEqual(1, response["created_count"])
        self.assertEqual(2, response["updated_count"])
        self.assertEqual(1, response["skipped_count"])
        self.assertEqual("next-page", response["next_cursor"])
        self.assertEqual("sku-1", response["products"][0]["external_id"])
        self.assertEqual("外部商品发货类型不受支持", response["products"][1]["skipped_reason"])
        self.assertNotIn("credentials", response)
        self.assertNotIn("credentials_encrypted", response)
        self.assertNotIn("secret", response)
        self.assertNotIn("token", response)
        self.assertNotIn("raw_payload", response["products"][0])
        self.assertNotIn("content", response["products"][0])
        self.assertNotIn("key_hash", response["products"][0])

    def test_external_catalog_sync_request_defaults_and_identifier_validation(self) -> None:
        request = SyncExternalCatalogRequest()

        self.assertIsNone(request.connection_id)
        self.assertEqual("", request.source_key)
        self.assertIsNone(request.cursor)
        self.assertEqual(50, request.limit)
        self.assertEqual(1, request.max_pages)
        self.assertEqual(7, SyncExternalCatalogRequest(connection_id=7).connection_id)
        with self.assertRaises(ValidationError):
            SyncExternalCatalogRequest(connection_id=0)
        self.assertIsNone(_normalize_external_identifier(None, "provider_name", allow_empty=False))
        self.assertIsNone(_normalize_external_identifier(" ", "provider_name", allow_empty=False))
        self.assertEqual("", _normalize_external_identifier(None, "source_key", allow_empty=True))
        self.assertEqual("provider-a", _normalize_external_identifier(" provider-a ", "provider_name", allow_empty=False))
        self.assertEqual("shop_a", _normalize_external_identifier(" shop_a ", "source_key", allow_empty=True))
        with self.assertRaises(ValueError):
            _normalize_external_identifier("ProviderA", "provider_name", allow_empty=False)
        with self.assertRaises(ValueError):
            _normalize_external_identifier("shop a", "source_key", allow_empty=True)

    def test_external_catalog_product_sync_request_fields(self) -> None:
        request = SyncExternalCatalogProductRequest(external_product_id=" sku-1 ")

        self.assertEqual(" sku-1 ", request.external_product_id)
        self.assertIsNone(request.connection_id)
        self.assertEqual("", request.source_key)
        self.assertEqual(7, SyncExternalCatalogProductRequest(external_product_id="sku-1", connection_id=7).connection_id)
        with self.assertRaises(ValidationError):
            SyncExternalCatalogProductRequest(external_product_id="")
        with self.assertRaises(ValidationError):
            SyncExternalCatalogProductRequest(external_product_id="x" * 129)
        with self.assertRaises(ValidationError):
            SyncExternalCatalogProductRequest(external_product_id="sku-1", connection_id=0)
        with self.assertRaises(ValidationError):
            SyncExternalCatalogProductRequest(external_product_id="sku-1", source_key="x" * 129)

    def test_external_catalog_sync_connection_source_resolution(self) -> None:
        connection = ExternalSourceConnectionSummary(
            connection_id=7,
            provider_name="acg",
            source_key="shop-a",
            display_name="ACG 店铺",
            status="active",
            credential_fields=["sensitive_1"],
            created_at=datetime(2026, 6, 7, tzinfo=timezone.utc),
            last_used_at=None,
        )

        source_key, connection_id = _external_catalog_sync_source_from_connection(
            "acg",
            "",
            connection,
        )

        self.assertEqual("shop-a", source_key)
        self.assertEqual(7, connection_id)

    def test_external_catalog_sync_connection_rejects_mismatched_source_or_provider(self) -> None:
        connection = ExternalSourceConnectionSummary(
            connection_id=7,
            provider_name="acg",
            source_key="shop-a",
            display_name="ACG 店铺",
            status="active",
            credential_fields=["sensitive_1"],
            created_at=None,
            last_used_at=None,
        )

        with self.assertRaises(ValueError):
            _external_catalog_sync_source_from_connection(
                "mcy",
                "",
                connection,
            )
        with self.assertRaises(ValueError):
            _external_catalog_sync_source_from_connection(
                "acg",
                "shop-b",
                connection,
            )

    def test_external_catalog_sync_connection_rejects_disabled_connection(self) -> None:
        connection = ExternalSourceConnectionSummary(
            connection_id=7,
            provider_name="acg",
            source_key="shop-a",
            display_name="ACG 店铺",
            status="disabled",
            credential_fields=["sensitive_1"],
            created_at=None,
            last_used_at=None,
        )

        with self.assertRaises(ValueError):
            _external_catalog_sync_source_from_connection(
                "acg",
                "",
                connection,
            )

    def test_external_source_provider_list_response_exposes_auto_fulfillment_capability_without_credentials(
        self,
    ) -> None:
        empty_response = ListExternalSourceProvidersResponse(providers=[]).model_dump()
        provider_response = ListExternalSourceProvidersResponse(
            providers=[
                _external_source_provider_response(
                    ExternalProviderSummary(
                        provider_name="acg",
                        capabilities=ExternalProviderCapabilities(
                            catalog_sync_available=True,
                            catalog_context_available=True,
                            catalog_product_available=True,
                            catalog_product_context_available=True,
                            order_available=True,
                            order_context_available=True,
                            delivery_available=True,
                            delivery_context_available=True,
                        ),
                    )
                )
            ]
        ).model_dump()

        self.assertEqual([], empty_response["providers"])
        self.assertEqual("acg", provider_response["providers"][0]["provider_name"])
        self.assertEqual("custom", provider_response["providers"][0]["integration_kind"])
        self.assertIsNone(provider_response["providers"][0]["contract_name"])
        self.assertFalse(provider_response["providers"][0]["production_ready"])
        self.assertFalse(provider_response["providers"][0]["staging_verified"])
        self.assertTrue(provider_response["providers"][0]["catalog_sync_available"])
        self.assertTrue(provider_response["providers"][0]["catalog_context_available"])
        self.assertTrue(provider_response["providers"][0]["catalog_product_available"])
        self.assertTrue(provider_response["providers"][0]["catalog_product_context_available"])
        self.assertTrue(provider_response["providers"][0]["order_available"])
        self.assertTrue(provider_response["providers"][0]["order_context_available"])
        self.assertTrue(provider_response["providers"][0]["delivery_available"])
        self.assertTrue(provider_response["providers"][0]["delivery_context_available"])
        self.assertFalse(provider_response["providers"][0]["auto_fulfillment_idempotent_available"])
        self.assertNotIn("credentials", provider_response["providers"][0])
        self.assertNotIn("credentials_encrypted", provider_response["providers"][0])
        self.assertNotIn("connection_id", provider_response["providers"][0])
        self.assertNotIn("api_key", provider_response["providers"][0])
        self.assertNotIn("password", provider_response["providers"][0])
        self.assertNotIn("secret", provider_response["providers"][0])
        self.assertNotIn("token", provider_response["providers"][0])
        self.assertNotIn("source_key", provider_response["providers"][0])

    def test_external_source_connection_response_does_not_expose_credentials(self) -> None:
        request = CreateExternalSourceConnectionRequest(
            provider_name="acg",
            source_key="shop-a",
            display_name="ACG Shop",
            credentials={"api_key": "secret-value"},
        ).model_dump()
        response = _external_source_connection_response(
            ExternalSourceConnectionSummary(
                connection_id=1,
                provider_name="acg",
                source_key="shop-a",
                display_name="ACG Shop",
                status="active",
                credential_fields=["sensitive_1"],
                created_at=None,
                last_used_at=None,
            )
        ).model_dump()

        self.assertIn("credentials", request)
        self.assertEqual(["sensitive_1"], response["credential_fields"])
        self.assertNotIn("credentials", response)
        self.assertNotIn("credentials_encrypted", response)
        self.assertNotIn("secret-value", str(response))
        self.assertNotIn("api_key", str(response))


if __name__ == "__main__":
    unittest.main()
