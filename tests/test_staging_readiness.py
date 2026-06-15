from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import staging_readiness


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StagingReadinessTest(unittest.TestCase):
    def test_current_project_has_no_failed_readiness_checks(self) -> None:
        checks = staging_readiness.run_checks(PROJECT_ROOT)

        failed = [check for check in checks if check.status == staging_readiness.FAIL]

        self.assertEqual([], failed)
        self.assertTrue(any(check.status == staging_readiness.WARN for check in checks))

    def test_missing_required_files_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            checks = staging_readiness.run_checks(Path(tmp_dir))

        failed_names = {check.name for check in checks if check.status == staging_readiness.FAIL}

        self.assertIn("required_file:app/main.py", failed_names)
        self.assertIn("env_example_contract", failed_names)
        self.assertIn("fastapi_route_mounts", failed_names)

    def test_main_json_output_is_parseable(self) -> None:
        with patch("builtins.print") as mocked_print:
            exit_code = staging_readiness.main(["--json", "--project-root", str(PROJECT_ROOT)])

        self.assertEqual(0, exit_code)
        printed_payload = mocked_print.call_args.args[0]
        payload = json.loads(printed_payload)
        self.assertIsInstance(payload, list)
        self.assertTrue(all("name" in item and "status" in item and "detail" in item for item in payload))

    def test_strict_mode_fails_on_warnings(self) -> None:
        with patch("builtins.print"):
            exit_code = staging_readiness.main(["--strict", "--project-root", str(PROJECT_ROOT)])

        self.assertEqual(1, exit_code)

    def test_env_example_contract_requires_workers_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / ".env.example").write_text(
                "\n".join(
                    f"{key}=" for key in sorted(staging_readiness.REQUIRED_ENV_KEYS - {"WORKERS_ENABLED"})
                ),
                encoding="utf-8",
            )

            check = staging_readiness._check_env_example(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("WORKERS_ENABLED", check.detail)

    def test_platform_admin_subscription_plan_contract_reports_missing_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            check = staging_readiness._check_platform_admin_subscription_plan_contract(Path(tmp_dir))

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("app/web/platform_admin.py", check.detail)
        self.assertIn("platform_subscriptions:read", check.detail)
        self.assertIn("tests/test_platform_admin_runtime_auth.py", check.detail)
        self.assertIn("docs/实施路线图.md", check.detail)

    def test_tenant_admin_product_metadata_contract_requires_route_scope_safe_schema_and_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            tenant_admin = root / "app" / "web" / "tenant_admin.py"
            tenant_admin.parent.mkdir(parents=True)
            tenant_admin.write_text(
                "\n".join(
                    [
                        "AdminProduct",
                        "sort_order",
                        "category",
                        'require_scope("products:read")',
                    ]
                ),
                encoding="utf-8",
            )
            repo = root / "app" / "db" / "repos" / "products.py"
            repo.parent.mkdir(parents=True)
            repo.write_text(
                "\n".join(
                    [
                        "async def set_product_sort_order",
                        "Product.tenant_id == tenant_id",
                    ]
                ),
                encoding="utf-8",
            )
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_openapi_security_contract.py").write_text(
                "test_product_metadata_update_operation_is_documented_as_tenant_admin\n",
                encoding="utf-8",
            )
            (tests_dir / "test_staging_readiness.py").write_text(
                "test_tenant_admin_product_metadata_contract_requires_route_scope_safe_schema_and_docs\n",
                encoding="utf-8",
            )
            docs_dir = root / "docs"
            docs_dir.mkdir()
            (docs_dir / "实施路线图.md").write_text("Tenant Admin 商品元数据更新合同\n", encoding="utf-8")
            (docs_dir / "开发交接说明.md").write_text("Tenant Admin 商品元数据更新合同\n", encoding="utf-8")
            (docs_dir / "数据库设计.md").write_text("租户内商品排序/分类管理\n", encoding="utf-8")

            check = staging_readiness._check_tenant_admin_product_metadata_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("UpdateProductMetadataRequest", check.detail)
        self.assertIn('"/products/{product_id}/metadata"', check.detail)
        self.assertIn('require_scope("products:write")', check.detail)
        self.assertIn("set_product_sort_order", check.detail)
        self.assertIn("set_product_category", check.detail)
        self.assertIn("/api/v1/tenant/products/{product_id}/metadata", check.detail)
        self.assertIn("additionalProperties", check.detail)
        self.assertIn("credentials", check.detail)
        self.assertIn("raw_payload", check.detail)
        self.assertIn("token", check.detail)
        self.assertIn("secret", check.detail)
        self.assertIn("不触发外部同步", check.detail)
        self.assertIn("不改库存", check.detail)
        self.assertIn("不暴露外部凭据", check.detail)

    def test_migration_verifier_requires_current_head_and_external_fulfillment_attempt_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            verifier = root / "scripts" / "verify_migrations.py"
            verifier.parent.mkdir(parents=True)
            verifier.write_text(
                "\n".join(
                    [
                        "EXPECTED_HEAD",
                        "EXPECTED_TABLES",
                        "online_upgrade_executed=false",
                        "--sql",
                    ]
                ),
                encoding="utf-8",
            )
            versions = root / "alembic" / "versions"
            versions.mkdir(parents=True)
            (versions / "20260606_0001_create_tenant_core.py").write_text(
                "revision = '20260606_0001'\n",
                encoding="utf-8",
            )

            check = staging_readiness._check_migration_verifier(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("20260610_0024", check.detail)
        self.assertIn("external_fulfillment_attempts", check.detail)
        self.assertIn("trc20_direct_transfers", check.detail)

    def test_external_http_contract_requires_httpx_transport_and_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            http_module = root / "app" / "services" / "external_sources" / "http.py"
            http_module.parent.mkdir(parents=True)
            http_module.write_text(
                "\n".join(
                    [
                        "ExternalHttpClient",
                        "ExternalHttpTransport",
                        "ExternalHttpRequest",
                        "ExternalHttpResponse",
                        "redact_external_http_headers",
                        "redact_external_http_url",
                        "ExternalHttpError",
                    ]
                ),
                encoding="utf-8",
            )
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_external_source_http_contract.py").write_text(
                "ExternalHttpxTransport\n",
                encoding="utf-8",
            )
            (tests_dir / "test_external_source_http_provider_contract.py").write_text(
                "fake provider contract\n",
                encoding="utf-8",
            )

            check = staging_readiness._check_external_http_adapter_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("build_external_http_url", check.detail)
        self.assertIn("path_segments", check.detail)
        self.assertIn("validate_external_http_public_base_url", check.detail)
        self.assertIn("UNSAFE_HTTP_HOST_SUFFIXES", check.detail)
        self.assertIn("ipaddress.ip_address", check.detail)
        self.assertIn("not address.is_global", check.detail)
        self.assertIn("ExternalHttpxTransport", check.detail)
        self.assertIn("MAX_EXTERNAL_HTTP_RESPONSE_BODY_BYTES", check.detail)
        self.assertIn("_validate_external_http_response_size", check.detail)
        self.assertIn("_validate_external_http_json_shape", check.detail)
        self.assertIn("MAX_EXTERNAL_HTTP_JSON_DEPTH", check.detail)
        self.assertIn("MockTransport", check.detail)
        self.assertIn("does_not_follow_redirects", check.detail)
        self.assertIn("test_client_rejects_oversized_response_body_without_details", check.detail)
        self.assertIn("test_client_rejects_overly_complex_json_payload", check.detail)
        self.assertIn("test_httpx_transport_rejects_oversized_response_before_json_parse", check.detail)
        self.assertIn("test_build_external_http_url_joins_path_segments_and_encodes_query", check.detail)
        self.assertIn("test_build_external_http_url_rejects_unsafe_path_segments", check.detail)
        self.assertIn("test_validate_external_http_public_base_url_rejects_ssrf_targets", check.detail)

    def test_standard_http_external_provider_contract_requires_registration_exports_and_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            external_dir = root / "app" / "services" / "external_sources"
            external_dir.mkdir(parents=True)
            (external_dir / "standard_http.py").write_text(
                "\n".join(
                    [
                        "STANDARD_HTTP_PROVIDER",
                        "StandardHttpExternalSourceProvider",
                        "ExternalHttpClient",
                        "build_external_http_url",
                    ]
                ),
                encoding="utf-8",
            )
            (external_dir / "__init__.py").write_text("STANDARD_HTTP_PROVIDER\n", encoding="utf-8")
            (external_dir / "builtins.py").write_text(
                "register_builtin_external_providers\n",
                encoding="utf-8",
            )
            (external_dir / "connections.py").write_text(
                "_validate_provider_credentials\n",
                encoding="utf-8",
            )
            main = root / "app" / "main.py"
            main.parent.mkdir(parents=True, exist_ok=True)
            main.write_text("create_app\n", encoding="utf-8")
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_external_source_standard_http_provider.py").write_text(
                "test_standard_http_provider_registers_as_builtin_once\n",
                encoding="utf-8",
            )
            (tests_dir / "test_tenant_admin_external_sources_provider_list.py").write_text(
                "test_list_external_sources_includes_builtin_standard_http_without_credentials\n",
                encoding="utf-8",
            )
            (tests_dir / "test_external_source_connections.py").write_text(
                "test_create_standard_http_connection_validates_and_encrypts_safe_credentials\n",
                encoding="utf-8",
            )

            check = staging_readiness._check_standard_http_external_provider_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("StandardHttpCredentials", check.detail)
        self.assertIn("STANDARD_HTTP_CONTRACT", check.detail)
        self.assertIn("integration_kind = \"generic_http_json\"", check.detail)
        self.assertIn("production_ready = False", check.detail)
        self.assertIn("staging_verified = False", check.detail)
        self.assertIn("DEFAULT_CATALOG_PATH", check.detail)
        self.assertIn("ALLOWED_PATH_TEMPLATE_VARIABLES", check.detail)
        self.assertIn("ALLOWED_STANDARD_HTTP_CREDENTIAL_FIELDS", check.detail)
        self.assertIn("validate_connection_credentials", check.detail)
        self.assertIn("ExternalHttpxTransport", check.detail)
        self.assertIn("MAX_EXTERNAL_CATALOG_PRODUCTS_PER_PAGE", check.detail)
        self.assertIn("MAX_EXTERNAL_DELIVERY_ITEMS", check.detail)
        self.assertIn("MAX_EXTERNAL_DELIVERY_ITEM_LENGTH", check.detail)
        self.assertIn("len(value) > max_items", check.detail)
        self.assertIn("外部发卡源返回目录商品列表过大", check.detail)
        self.assertIn("外部发卡源返回发货条目过多", check.detail)
        self.assertIn("validate_external_http_public_base_url", check.detail)
        self.assertIn("is_sensitive_http_header_name", check.detail)
        self.assertIn("reject_sensitive_raw_payload_keys", check.detail)
        self.assertIn("create_order_with_context", check.detail)
        self.assertIn("_path_template", check.detail)
        self.assertIn("_path_segments", check.detail)
        self.assertIn('getattr(provider, "validate_connection_credentials", None)', check.detail)
        self.assertIn("build_credentials_hint(normalized_credentials)", check.detail)
        self.assertIn("register_provider(create_standard_http_provider())", check.detail)
        self.assertIn("app/main.py:register_builtin_external_providers()", check.detail)
        self.assertIn("test_standard_http_provider_uses_configured_safe_path_templates", check.detail)
        self.assertIn("test_standard_http_provider_requires_endpoint_specific_template_variables", check.detail)
        self.assertIn("test_standard_http_provider_order_lifecycle_redacts_credentials", check.detail)
        self.assertIn("test_standard_http_provider_rejects_unsafe_base_url_before_http_call", check.detail)
        self.assertIn("test_standard_http_provider_rejects_sensitive_raw_payload", check.detail)
        self.assertIn("test_standard_http_provider_rejects_too_many_catalog_products", check.detail)
        self.assertIn("test_standard_http_provider_rejects_too_many_delivery_items", check.detail)
        self.assertIn("test_standard_http_provider_rejects_oversized_delivery_item", check.detail)
        self.assertIn("test_create_connection_uses_provider_validator_without_knowing_specific_provider", check.detail)
        self.assertIn(
            "test_create_standard_http_external_source_connection_invalid_credentials_returns_400_and_redacts",
            check.detail,
        )
        self.assertIn('"/external-source-connections/{connection_id}"', check.detail)
        self.assertIn("get_external_source_connection", check.detail)
        self.assertIn("ExternalSourceConnectionService().get_connection", check.detail)
        self.assertIn("test_get_external_source_connection_requires_read_scope_before_service", check.detail)
        self.assertIn("test_get_external_source_connection_is_tenant_scoped_and_redacted", check.detail)
        self.assertIn(
            "test_get_external_source_connection_returns_404_for_missing_or_cross_tenant_connection",
            check.detail,
        )
        self.assertIn("auto_fulfillment_idempotent_available", check.detail)
        self.assertIn("contract_name", check.detail)

    def test_mcy_shop_external_provider_contract_requires_offline_skeleton_and_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            external_dir = root / "app" / "services" / "external_sources"
            external_dir.mkdir(parents=True)
            (external_dir / "mcy_shop.py").write_text(
                "\n".join(
                    [
                        "MCY_SHOP_PROVIDER",
                        "McyShopExternalSourceProvider",
                        "ExternalHttpClient",
                    ]
                ),
                encoding="utf-8",
            )
            (external_dir / "__init__.py").write_text("MCY_SHOP_PROVIDER\n", encoding="utf-8")
            (external_dir / "builtins.py").write_text("get_provider(MCY_SHOP_PROVIDER)\n", encoding="utf-8")
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_external_source_mcy_shop_provider.py").write_text(
                "test_mcy_shop_provider_registers_as_builtin_offline_contract\n",
                encoding="utf-8",
            )
            (tests_dir / "test_tenant_admin_external_sources_provider_list.py").write_text(
                "MCY_SHOP_PROVIDER\n",
                encoding="utf-8",
            )

            check = staging_readiness._check_mcy_shop_external_provider_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("MCY_SHOP_OFFLINE_FIXTURE_CONTRACT", check.detail)
        self.assertIn("MCY_SHOP_OFFLINE_FIXTURE_ALLOWED_HOSTS", check.detail)
        self.assertIn("MCY_SHOP_OFFLINE_FIXTURE_ALLOWED_HOST_SUFFIXES", check.detail)
        self.assertIn("integration_kind = \"offline_fixture\"", check.detail)
        self.assertIn("production_ready = False", check.detail)
        self.assertIn("staging_verified = False", check.detail)
        self.assertIn("ALLOWED_MCY_SHOP_CREDENTIAL_FIELDS", check.detail)
        self.assertIn("validate_mcy_shop_credentials", check.detail)
        self.assertIn("validate_connection_credentials", check.detail)
        self.assertIn("_ensure_mcy_shop_fixture_base_url", check.detail)
        self.assertIn("_is_mcy_shop_fixture_host", check.detail)
        self.assertIn("create_mcy_shop_provider", check.detail)
        self.assertIn("ExternalHttpxTransport", check.detail)
        self.assertIn("MAX_EXTERNAL_CATALOG_PRODUCTS_PER_PAGE", check.detail)
        self.assertIn("MAX_EXTERNAL_DELIVERY_ITEMS", check.detail)
        self.assertIn("MAX_EXTERNAL_DELIVERY_ITEM_LENGTH", check.detail)
        self.assertIn("len(value) > max_items", check.detail)
        self.assertIn("build_external_http_url", check.detail)
        self.assertIn("reject_sensitive_raw_payload_keys", check.detail)
        self.assertIn("auto_fulfillment_idempotent = False", check.detail)
        self.assertIn("mcy-shop-fixture", check.detail)
        self.assertIn("register_provider(create_mcy_shop_provider())", check.detail)
        self.assertIn("test_mcy_shop_credentials_only_allow_fixture_hosts", check.detail)
        self.assertIn("test_mcy_shop_provider_order_lifecycle_redacts_credentials", check.detail)
        self.assertIn("test_mcy_shop_provider_rejects_sensitive_raw_payload", check.detail)
        self.assertIn("test_mcy_shop_provider_rejects_unsafe_credentials_before_http_call", check.detail)
        self.assertIn("test_mcy_shop_provider_rejects_too_many_catalog_items", check.detail)
        self.assertIn("test_mcy_shop_provider_rejects_too_many_delivery_items", check.detail)
        self.assertIn("test_mcy_shop_provider_rejects_oversized_delivery_item", check.detail)
        self.assertIn("auto_fulfillment_idempotent_available", check.detail)
        self.assertIn("contract_name", check.detail)

    def test_payment_adapter_contract_requires_token188_skeleton_and_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            payments_dir = root / "app" / "services" / "payments"
            payments_dir.mkdir(parents=True)
            (payments_dir / "token188.py").write_text(
                "\n".join(
                    [
                        "Token188Config",
                        "Token188Provider",
                        "sign_token188_gateway_payload",
                    ]
                ),
                encoding="utf-8",
            )
            (payments_dir / "epay_compatible.py").write_text(
                "\n".join(
                    [
                        "EpayCompatibleConfig",
                        "EpayCompatibleProvider",
                        "sign_epay_payload",
                    ]
                ),
                encoding="utf-8",
            )
            (payments_dir / "__init__.py").write_text("Token188Provider\n", encoding="utf-8")
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_payment_token188.py").write_text(
                "test_sign_token188_payloads_match_legacy_gateway_and_callback_algorithms\n",
                encoding="utf-8",
            )

            check = staging_readiness._check_payment_adapter_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("TOKEN188_OFFLINE_QUERY_CONTRACT", check.detail)
        self.assertIn("build_token188_offline_query_contract_request", check.detail)
        self.assertIn("sign_token188_callback_payload", check.detail)
        self.assertIn("verify_token188_callback", check.detail)
        self.assertIn("normalize_token188_offline_query_response", check.detail)
        self.assertIn("normalize_token188_query_payload", check.detail)
        self.assertIn("sanitize_payment_callback_payload", check.detail)
        self.assertIn("tests/test_payment_epusdt.py", check.detail)
        self.assertIn("test_verify_callback_redacts_nested_sensitive_payload_fields", check.detail)
        self.assertIn("test_verify_callback_valid_signature_non_success_status_is_unpaid", check.detail)
        self.assertIn("test_verify_callback_rejects_invalid_signature_or_missing_order_number", check.detail)
        self.assertIn("epusdt 回调缺少订单号", check.detail)
        self.assertIn("金额不能小于 0.01", check.detail)
        self.assertIn("TOKEN188 回调缺少订单号", check.detail)
        self.assertIn("test_build_payment_params_rejects_amount_truncated_to_zero", check.detail)
        self.assertIn("test_verify_callback_redacts_nested_sensitive_payload_fields", check.detail)
        self.assertIn("test_callback_requires_order_number_instead_of_amount_guessing", check.detail)
        self.assertIn("EPAY_OFFLINE_QUERY_CONTRACT", check.detail)
        self.assertIn("LEMZF_PROVIDER", check.detail)
        self.assertIn("LemzfProvider", check.detail)
        self.assertIn("build_epay_offline_query_contract_request", check.detail)
        self.assertIn("verify_epay_callback", check.detail)
        self.assertIn("normalize_epay_offline_query_response", check.detail)
        self.assertIn("易支付回调缺少订单号", check.detail)
        self.assertIn("支付配置暂不可用", check.detail)
        self.assertIn("app/services/payments/safety.py", check.detail)
        self.assertIn("tests/test_payment_epay_compatible.py", check.detail)
        self.assertIn("test_verify_callback_accepts_signed_success_payload", check.detail)
        self.assertIn("tests/test_payment_offline_query_contract.py", check.detail)
        self.assertIn("FakeOfflineQueryTransport", check.detail)
        self.assertIn(
            "test_token188_offline_query_normalizer_accepts_signed_paid_fixture_without_network",
            check.detail,
        )
        self.assertIn(
            "test_epay_offline_query_normalizer_accepts_signed_success_fixture_without_network",
            check.detail,
        )
        self.assertIn("test_lemzf_offline_query_normalizer_keeps_lemzf_provider_name", check.detail)
        self.assertIn("resolved_config.provider == USDT_TRC20_DIRECT_PROVIDER", check.detail)
        self.assertIn(
            "test_callback_route_payment_unavailable_response_is_generic_and_records_rejection",
            check.detail,
        )
        self.assertIn("PaymentUnavailableError", check.detail)

    def test_payment_adapter_contract_requires_callback_payload_gate_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            payment_router = root / "app" / "web" / "payments.py"
            payment_router.parent.mkdir(parents=True)
            payment_router.write_text(
                "\n".join(
                    [
                        '"/callback/token188"',
                        '"/callback/epay_compatible"',
                        '"/callback/lemzf"',
                        '"/callback/{provider_name}"',
                        "_read_callback_payload",
                        "_record_callback_rejection",
                        "PaymentCallbackRejectionAuditService",
                        "process_payment_callback",
                        "支付回调参数无效",
                        "支付配置暂不可用",
                    ]
                ),
                encoding="utf-8",
            )

            check = staging_readiness._check_payment_adapter_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        for marker in (
            "MAX_PAYMENT_CALLBACK_BODY_BYTES",
            "MAX_PAYMENT_CALLBACK_QUERY_BYTES",
            "MAX_PAYMENT_CALLBACK_FIELD_COUNT",
            "MAX_PAYMENT_CALLBACK_KEY_LENGTH",
            "MAX_PAYMENT_CALLBACK_VALUE_LENGTH",
            "_read_json_object_no_duplicate_keys",
            "_pairs_to_callback_payload",
            "_validate_callback_payload_shape",
            "test_callback_route_rejects_body_over_size_limit_before_payment_service",
            "test_callback_route_rejects_query_over_size_limit_before_payment_service",
            "test_callback_route_rejects_too_many_json_fields_before_payment_service",
            "test_callback_route_rejects_oversized_key_or_value_before_payment_service",
            "test_callback_route_rejects_duplicate_json_keys_before_payment_service",
            "test_callback_route_rejects_duplicate_form_fields_before_payment_service",
            "test_callback_route_rejects_duplicate_query_fields_before_payment_service",
            "test_callback_route_payload_gate_errors_are_generic_and_audited_without_payload",
            "test_record_payload_malformed_rejection_without_payload_keeps_zero_field_count",
        ):
            self.assertIn(marker, check.detail)

    def test_business_plugin_contract_requires_manifest_registry_tests_and_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            services_dir = root / "app" / "services"
            services_dir.mkdir(parents=True)
            (services_dir / "business_plugins.py").write_text(
                "\n".join(
                    [
                        "BusinessPluginManifest",
                        "BusinessPluginRegistry",
                        "BUSINESS_PLUGIN_KIND_PAYMENT",
                        "BUSINESS_PLUGIN_KIND_EXTERNAL_SOURCE",
                        "payment_summary_to_plugin_manifest",
                    ]
                ),
                encoding="utf-8",
            )
            (services_dir / "__init__.py").write_text("BusinessPluginManifest\n", encoding="utf-8")
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_business_plugins.py").write_text(
                "test_manifest_from_mapping_normalizes_safe_fields\n",
                encoding="utf-8",
            )
            docs_dir = root / "docs"
            docs_dir.mkdir()
            (docs_dir / "业务插件架构方案.md").write_text("长期目标接近 WordPress 插件\n", encoding="utf-8")
            (docs_dir / "实施路线图.md").write_text("当前阶段落地受控适配器插件\n", encoding="utf-8")
            (docs_dir / "开发交接说明.md").write_text("不导入执行第三方插件代码\n", encoding="utf-8")
            (docs_dir / "多租户发卡平台完整方案.md").write_text("不做动态 Bot router 注入\n", encoding="utf-8")
            (docs_dir / "Web管理后台开发计划.md").write_text("不做动态任务和 handler 注入\n", encoding="utf-8")

            check = staging_readiness._check_business_plugin_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("BUSINESS_PLUGIN_KIND_TENANT_TOOL", check.detail)
        self.assertIn("ALLOWED_PLUGIN_ENTRYPOINT_PREFIXES", check.detail)
        self.assertIn("is_plugin_entrypoint_allowed", check.detail)
        self.assertIn("external_source_summary_to_plugin_manifest", check.detail)
        self.assertIn("list_current_business_plugin_manifests", check.detail)
        self.assertIn("MappingProxyType", check.detail)
        self.assertIn("from_mapping", check.detail)
        self.assertIn("capability 值必须是布尔值", check.detail)
        self.assertIn("entrypoint 必须是 module:function 格式", check.detail)
        self.assertIn("BusinessPluginRegistry", check.detail)
        self.assertIn("test_manifest_requires_explicit_production_and_staging_flags", check.detail)
        self.assertIn("test_entrypoint_is_validated_but_not_executed", check.detail)
        self.assertIn("test_payment_summary_converts_to_plugin_manifest_without_secrets", check.detail)
        self.assertIn("当前阶段：业务插件 manifest 能校验", check.detail)
        self.assertIn("不做任意第三方插件热加载和远程代码执行", check.detail)
        self.assertIn("Admin Web 插件能力摘要只读 BFF", check.detail)
        self.assertIn("不执行插件 entrypoint", check.detail)
        self.assertIn("不读取或解密外部源凭据", check.detail)
        self.assertIn("不代表插件安装、租户级启停、真实 mcy-shop/acg-faka、真实支付网关或 staging 验证完成", check.detail)

    def test_admin_web_contract_requires_business_plugin_capability_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "app" / "web").mkdir(parents=True)
            (root / "app" / "services").mkdir(parents=True)
            (root / "app" / "bots" / "routers").mkdir(parents=True)
            (root / "tests").mkdir()
            (root / "docs").mkdir()
            (root / "web" / "admin" / "src" / "components" / "layout").mkdir(parents=True)
            (root / "web" / "admin" / "src" / "lib").mkdir(parents=True)
            (root / "app" / "web" / "admin_web.py").write_text("create_admin_web_router\n", encoding="utf-8")
            (root / "app" / "services" / "admin_web.py").write_text("AdminWebSessionCodec\n", encoding="utf-8")
            (root / "app" / "services" / "tenant_features.py").write_text("DEFAULT_TENANT_FEATURE_FLAGS\n", encoding="utf-8")
            (root / "app" / "config.py").write_text("admin_web_session_max_age_seconds\n", encoding="utf-8")
            (root / "tests" / "test_admin_web.py").write_text("test_tenant_payment_configs_returns_safe_current_workspace_items\n", encoding="utf-8")
            (root / "tests" / "test_openapi_security_contract.py").write_text(
                "test_admin_web_tenant_payment_config_routes_use_cookie_session_without_api_key_security\n",
                encoding="utf-8",
            )
            (root / "docs" / "Web管理后台开发计划.md").write_text("Admin Web 支付配置 BFF\n", encoding="utf-8")
            (root / "docs" / "实施路线图.md").write_text("Admin Web 支付配置 BFF\n", encoding="utf-8")
            (root / "web" / "admin" / "package.json").write_text('"vite"\n', encoding="utf-8")
            (root / "web" / "admin" / "src" / "components" / "layout" / "admin-shell.tsx").write_text(
                "CloneBotApiKeysPanel\n",
                encoding="utf-8",
            )
            (root / "web" / "admin" / "src" / "lib" / "admin-web-api.ts").write_text(
                "getAdminWebTenantPaymentConfigs\n",
                encoding="utf-8",
            )
            (root / "app" / "bots" / "routers" / "master.py").write_text('Command("admin_web_code")\n', encoding="utf-8")
            (root / "app" / "bots" / "routers" / "tenant.py").write_text('Command("admin_web_code")\n', encoding="utf-8")
            (root / "tests" / "test_tenant_admin_web_code.py").write_text("tenant_public_id\n", encoding="utf-8")
            (root / "tests" / "test_master_bot_lifecycle.py").write_text("tenant_public_id\n", encoding="utf-8")
            (root / "app" / "main.py").write_text("create_admin_web_router\n", encoding="utf-8")

            check = staging_readiness._check_admin_web_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn('"/business-plugins/capabilities"', check.detail)
        self.assertIn("AdminWebBusinessPluginCapabilityItem", check.detail)
        self.assertIn("business_plugin_capabilities", check.detail)
        self.assertIn("getAdminWebBusinessPluginCapabilities", check.detail)
        self.assertIn("CloneBotPluginCapabilitiesPanel", check.detail)
        self.assertIn("test_admin_web_business_plugin_capabilities_uses_cookie_session_and_safe_schema", check.detail)
        self.assertIn("Admin Web 插件能力摘要只读 BFF", check.detail)

    def test_admin_web_contract_requires_report_export_download_proxy_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "app" / "web").mkdir(parents=True)
            (root / "app" / "services").mkdir(parents=True)
            (root / "app" / "bots" / "routers").mkdir(parents=True)
            (root / "tests").mkdir()
            (root / "docs").mkdir()
            (root / "web" / "admin" / "src" / "components" / "layout").mkdir(parents=True)
            (root / "web" / "admin" / "src" / "lib").mkdir(parents=True)
            (root / "app" / "web" / "admin_web.py").write_text(
                'create_admin_web_router\n"/tenant/reports/export-jobs"\n',
                encoding="utf-8",
            )
            (root / "app" / "services" / "admin_web.py").write_text(
                "tenant_report_export_jobs\ntenant_create_report_export_job\n",
                encoding="utf-8",
            )
            (root / "app" / "services" / "tenant_features.py").write_text(
                "DEFAULT_TENANT_FEATURE_FLAGS\n",
                encoding="utf-8",
            )
            (root / "app" / "config.py").write_text("admin_web_session_max_age_seconds\n", encoding="utf-8")
            (root / "tests" / "test_admin_web.py").write_text(
                "test_tenant_report_export_jobs_returns_safe_current_workspace_items\n",
                encoding="utf-8",
            )
            (root / "tests" / "test_openapi_security_contract.py").write_text(
                "test_admin_web_tenant_report_export_jobs_use_cookie_session_and_safe_schema\n",
                encoding="utf-8",
            )
            (root / "docs" / "Web管理后台开发计划.md").write_text(
                "Admin Web 报表任务合同\n",
                encoding="utf-8",
            )
            (root / "docs" / "实施路线图.md").write_text("Admin Web 报表任务合同\n", encoding="utf-8")
            (root / "web" / "admin" / "package.json").write_text('"vite"\n', encoding="utf-8")
            (root / "web" / "admin" / "src" / "components" / "layout" / "admin-shell.tsx").write_text(
                "CloneBotReportExportJobsPanel\ndownload_available\n",
                encoding="utf-8",
            )
            (root / "web" / "admin" / "src" / "lib" / "admin-web-api.ts").write_text(
                "getAdminWebTenantReportExportJobs\ncreateAdminWebTenantReportExportJob\n",
                encoding="utf-8",
            )
            (root / "app" / "bots" / "routers" / "master.py").write_text('Command("admin_web_code")\n', encoding="utf-8")
            (root / "app" / "bots" / "routers" / "tenant.py").write_text('Command("admin_web_code")\n', encoding="utf-8")
            (root / "tests" / "test_tenant_admin_web_code.py").write_text("tenant_public_id\n", encoding="utf-8")
            (root / "tests" / "test_master_bot_lifecycle.py").write_text("tenant_public_id\n", encoding="utf-8")
            (root / "app" / "main.py").write_text("create_admin_web_router\n", encoding="utf-8")

            check = staging_readiness._check_admin_web_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn('"/tenant/reports/export-jobs/download"', check.detail)
        self.assertIn("AdminWebReportExportJobDownloadRequest", check.detail)
        self.assertIn("AdminWebReportExportDownloadHandleCodec", check.detail)
        self.assertIn("tenant_report_export_download_file", check.detail)
        self.assertIn("get_downloadable_tenant_export", check.detail)
        self.assertIn("downloadAdminWebTenantReportExportJob", check.detail)
        self.assertIn("AdminWebTenantReportDownloadFile", check.detail)
        self.assertIn("test_admin_web_tenant_report_export_download_uses_cookie_session_origin_and_handle_only_schema", check.detail)
        self.assertIn("只代理已完成且当前租户可下载的报表文件", check.detail)

    def test_admin_web_contract_requires_external_source_catalog_sync_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "app" / "web").mkdir(parents=True)
            (root / "app" / "services").mkdir(parents=True)
            (root / "app" / "bots" / "routers").mkdir(parents=True)
            (root / "tests").mkdir()
            (root / "docs").mkdir()
            (root / "web" / "admin" / "src" / "components" / "layout").mkdir(parents=True)
            (root / "web" / "admin" / "src" / "lib").mkdir(parents=True)
            (root / "app" / "web" / "admin_web.py").write_text(
                'create_admin_web_router\n"/tenant/external-source-connections"\n',
                encoding="utf-8",
            )
            (root / "app" / "services" / "admin_web.py").write_text(
                "AdminWebExternalSourceConnectionHandleCodec\n"
                "tenant_external_source_connections\n"
                "tenant_create_external_source_connection\n"
                "tenant_disable_external_source_connection\n",
                encoding="utf-8",
            )
            (root / "app" / "services" / "tenant_features.py").write_text(
                "DEFAULT_TENANT_FEATURE_FLAGS\n",
                encoding="utf-8",
            )
            (root / "app" / "config.py").write_text("admin_web_session_max_age_seconds\n", encoding="utf-8")
            (root / "tests" / "test_admin_web.py").write_text(
                "test_tenant_external_source_connections_returns_safe_current_workspace_payload\n",
                encoding="utf-8",
            )
            (root / "tests" / "test_openapi_security_contract.py").write_text(
                "test_admin_web_external_source_connections_use_cookie_session_and_safe_schema\n",
                encoding="utf-8",
            )
            (root / "docs" / "Web管理后台开发计划.md").write_text(
                "Admin Web 外部源连接管理合同\n",
                encoding="utf-8",
            )
            (root / "docs" / "实施路线图.md").write_text("Admin Web 外部源连接管理合同\n", encoding="utf-8")
            (root / "web" / "admin" / "package.json").write_text('"vite"\n', encoding="utf-8")
            (root / "web" / "admin" / "src" / "components" / "layout" / "admin-shell.tsx").write_text(
                "CloneBotPluginCapabilitiesPanel\n外部源连接\n",
                encoding="utf-8",
            )
            (root / "web" / "admin" / "src" / "lib" / "admin-web-api.ts").write_text(
                "getAdminWebExternalSourceConnections\ncreateAdminWebExternalSourceConnection\n"
                "disableAdminWebExternalSourceConnection\n",
                encoding="utf-8",
            )
            (root / "app" / "bots" / "routers" / "master.py").write_text('Command("admin_web_code")\n', encoding="utf-8")
            (root / "app" / "bots" / "routers" / "tenant.py").write_text('Command("admin_web_code")\n', encoding="utf-8")
            (root / "tests" / "test_tenant_admin_web_code.py").write_text("tenant_public_id\n", encoding="utf-8")
            (root / "tests" / "test_master_bot_lifecycle.py").write_text("tenant_public_id\n", encoding="utf-8")
            (root / "app" / "main.py").write_text("create_admin_web_router\n", encoding="utf-8")

            check = staging_readiness._check_admin_web_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn('"/tenant/external-sources/catalog/sync"', check.detail)
        self.assertIn("AdminWebExternalCatalogSyncRequest", check.detail)
        self.assertIn("AdminWebExternalCatalogSyncResponse", check.detail)
        self.assertIn("tenant_sync_external_catalog", check.detail)
        self.assertIn("ExternalCatalogSyncService", check.detail)
        self.assertIn("syncAdminWebExternalCatalog", check.detail)
        self.assertIn("test_admin_web_external_source_catalog_sync_uses_cookie_session_origin_and_handle_only_schema", check.detail)
        self.assertIn("Admin Web 外部源目录同步合同", check.detail)
        self.assertIn("请求仅允许 `connection_handle`、`cursor`、`limit`、`max_pages`", check.detail)

    def test_admin_web_contract_requires_order_observability_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "app" / "web").mkdir(parents=True)
            (root / "app" / "services").mkdir(parents=True)
            (root / "app" / "bots" / "routers").mkdir(parents=True)
            (root / "tests").mkdir()
            (root / "docs").mkdir()
            (root / "web" / "admin" / "src" / "components" / "layout").mkdir(parents=True)
            (root / "web" / "admin" / "src" / "lib").mkdir(parents=True)
            (root / "app" / "web" / "admin_web.py").write_text(
                'create_admin_web_router\n"/tenant/orders"\n"/tenant/orders/{out_trade_no}/diagnostics"\n',
                encoding="utf-8",
            )
            (root / "app" / "services" / "admin_web.py").write_text(
                "AdminWebTenantOrdersPage\nAdminWebTenantOrderDiagnostics\ntenant_orders\ntenant_order_diagnostics\n",
                encoding="utf-8",
            )
            (root / "app" / "services" / "tenant_features.py").write_text(
                "DEFAULT_TENANT_FEATURE_FLAGS\n",
                encoding="utf-8",
            )
            (root / "app" / "config.py").write_text("admin_web_session_max_age_seconds\n", encoding="utf-8")
            (root / "tests" / "test_admin_web.py").write_text(
                "test_tenant_orders_returns_safe_current_workspace_items\n"
                "test_tenant_order_diagnostics_returns_safe_current_workspace_summary\n",
                encoding="utf-8",
            )
            (root / "tests" / "test_openapi_security_contract.py").write_text(
                "test_admin_web_tenant_order_diagnostics_schema_exposes_safe_fields_only\n",
                encoding="utf-8",
            )
            (root / "docs" / "Web管理后台开发计划.md").write_text(
                "Admin Web 订单排障详情\n",
                encoding="utf-8",
            )
            (root / "docs" / "实施路线图.md").write_text("Admin Web 订单排障详情\n", encoding="utf-8")
            (root / "web" / "admin" / "package.json").write_text('"vite"\n', encoding="utf-8")
            (root / "web" / "admin" / "src" / "components" / "layout" / "admin-shell.tsx").write_text(
                "最近订单\n订单排障\n",
                encoding="utf-8",
            )
            (root / "web" / "admin" / "src" / "lib" / "admin-web-api.ts").write_text(
                "getAdminWebTenantOrders\ngetAdminWebTenantOrderDiagnostics\n",
                encoding="utf-8",
            )
            (root / "app" / "bots" / "routers" / "master.py").write_text('Command("admin_web_code")\n', encoding="utf-8")
            (root / "app" / "bots" / "routers" / "tenant.py").write_text('Command("admin_web_code")\n', encoding="utf-8")
            (root / "tests" / "test_tenant_admin_web_code.py").write_text("tenant_public_id\n", encoding="utf-8")
            (root / "tests" / "test_master_bot_lifecycle.py").write_text("tenant_public_id\n", encoding="utf-8")
            (root / "app" / "main.py").write_text("create_admin_web_router\n", encoding="utf-8")

            check = staging_readiness._check_admin_web_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn('"/tenant/orders/observability"', check.detail)
        self.assertIn("AdminWebTenantOrderObservabilityResponse", check.detail)
        self.assertIn("tenant_order_observability", check.detail)
        self.assertIn("PaymentCallbackFailureLogService", check.detail)
        self.assertIn("ExternalFulfillmentAttemptLogService", check.detail)
        self.assertIn("getAdminWebTenantOrderObservability", check.detail)
        self.assertIn("OrderObservabilityPanel", check.detail)
        self.assertIn("test_admin_web_tenant_order_observability_schema_exposes_safe_fields_only", check.detail)
        self.assertIn("Admin Web 订单观测 BFF", check.detail)

    def test_admin_web_contract_requires_platform_subscription_status_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "app" / "web").mkdir(parents=True)
            (root / "app" / "services").mkdir(parents=True)
            (root / "app" / "bots" / "routers").mkdir(parents=True)
            (root / "tests").mkdir()
            (root / "docs").mkdir()
            (root / "web" / "admin" / "src" / "components" / "layout").mkdir(parents=True)
            (root / "web" / "admin" / "src" / "lib").mkdir(parents=True)
            (root / "app" / "web" / "admin_web.py").write_text(
                'create_admin_web_router\n"/platform/dashboard"\n',
                encoding="utf-8",
            )
            (root / "app" / "services" / "admin_web.py").write_text("AdminWebSessionCodec\n", encoding="utf-8")
            (root / "app" / "services" / "tenant_features.py").write_text(
                "DEFAULT_TENANT_FEATURE_FLAGS\n",
                encoding="utf-8",
            )
            (root / "app" / "config.py").write_text("admin_web_session_max_age_seconds\n", encoding="utf-8")
            (root / "tests" / "test_admin_web.py").write_text(
                "test_platform_dashboard_returns_safe_summary_payload\n",
                encoding="utf-8",
            )
            (root / "tests" / "test_openapi_security_contract.py").write_text(
                "test_admin_web_business_plugin_capabilities_uses_cookie_session_and_safe_schema\n",
                encoding="utf-8",
            )
            (root / "docs" / "Web管理后台开发计划.md").write_text("主 Bot 平台管理\n", encoding="utf-8")
            (root / "docs" / "实施路线图.md").write_text("主 Bot 平台管理\n", encoding="utf-8")
            (root / "web" / "admin" / "package.json").write_text('"vite"\n', encoding="utf-8")
            (root / "web" / "admin" / "src" / "components" / "layout" / "admin-shell.tsx").write_text(
                "PlatformDashboardPanel\n",
                encoding="utf-8",
            )
            (root / "web" / "admin" / "src" / "lib" / "admin-web-api.ts").write_text(
                "AdminWebPlatformDashboard\n",
                encoding="utf-8",
            )
            (root / "app" / "bots" / "routers" / "master.py").write_text('Command("admin_web_code")\n', encoding="utf-8")
            (root / "app" / "bots" / "routers" / "tenant.py").write_text('Command("admin_web_code")\n', encoding="utf-8")
            (root / "tests" / "test_tenant_admin_web_code.py").write_text("tenant_public_id\n", encoding="utf-8")
            (root / "tests" / "test_master_bot_lifecycle.py").write_text("tenant_public_id\n", encoding="utf-8")
            (root / "app" / "main.py").write_text("create_admin_web_router\n", encoding="utf-8")

            check = staging_readiness._check_admin_web_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("trial_subscription_count", check.detail)
        self.assertIn("retention_expired_subscription_count", check.detail)
        self.assertIn("_count_effective_subscription_status", check.detail)
        self.assertIn("PlatformTenantSubscriptionStatusPanel", check.detail)
        self.assertIn("AdminWebPlatformPaymentProviderItemResponse", check.detail)
        self.assertIn("_list_platform_payment_provider_observations", check.detail)
        self.assertIn("PlatformPaymentProvidersPanel", check.detail)
        self.assertIn("payment_providers", check.detail)
        self.assertIn("test_admin_web_platform_dashboard_exposes_subscription_status_counts_safely", check.detail)
        self.assertIn("Admin Web 平台租户订阅状态观测", check.detail)
        self.assertIn("Admin Web 平台支付通道观测", check.detail)

    def test_tenant_admin_payment_config_contract_requires_routes_scopes_and_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            tenant_admin = root / "app" / "web" / "tenant_admin.py"
            tenant_admin.parent.mkdir(parents=True)
            tenant_admin.write_text(
                "\n".join(
                    [
                        "TenantEpusdtConfigResponse",
                        "PaymentConfigService",
                        '"/payments/epusdt/config"',
                    ]
                ),
                encoding="utf-8",
            )
            api_keys = root / "app" / "services" / "api_keys.py"
            api_keys.parent.mkdir(parents=True)
            api_keys.write_text('"payments:read"\n', encoding="utf-8")
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_tenant_admin_payment_config.py").write_text(
                "test_get_payment_config_requires_payments_read_scope_before_service\n",
                encoding="utf-8",
            )
            (tests_dir / "test_openapi_security_contract.py").write_text(
                "test_payment_config_operations_are_documented_as_tenant_admin\n",
                encoding="utf-8",
            )

            check = staging_readiness._check_tenant_admin_payment_config_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("UpdateTenantEpusdtConfigRequest", check.detail)
        self.assertIn("DisableTenantEpusdtConfigResponse", check.detail)
        self.assertIn("TenantPaymentProviderItem", check.detail)
        self.assertIn("ListTenantPaymentProvidersResponse", check.detail)
        self.assertIn("TenantPaymentCallbackFailureItem", check.detail)
        self.assertIn("ListTenantPaymentCallbackFailuresResponse", check.detail)
        self.assertIn("TenantPaymentCallbackRejectionItem", check.detail)
        self.assertIn("ListTenantPaymentCallbackRejectionsResponse", check.detail)
        self.assertIn('"/payments/providers"', check.detail)
        self.assertIn('"/payments/callback-failures"', check.detail)
        self.assertIn('"/payments/callback-rejections"', check.detail)
        self.assertIn('require_scope("payments:read")', check.detail)
        self.assertIn('require_scope("payments:write")', check.detail)
        self.assertIn('"payments:write"', check.detail)
        self.assertIn("pid_masked", check.detail)
        self.assertIn("key_configured", check.detail)
        self.assertIn("cny_per_usdt", check.detail)
        self.assertIn("min_usdt_amount", check.detail)
        self.assertIn("timeout_seconds", check.detail)
        self.assertIn("offline_only", check.detail)
        self.assertIn("reconcile_available", check.detail)
        self.assertIn("PaymentCallbackFailureLogService", check.detail)
        self.assertIn("_normalize_epusdt_base_url", check.detail)
        self.assertIn("test_update_payment_config_commits_and_returns_safe_payload", check.detail)
        self.assertIn("test_update_payment_config_rejects_unsafe_base_url_before_service", check.detail)
        self.assertIn("test_list_payment_providers_returns_safe_capability_summary", check.detail)
        self.assertIn("tests/test_payment_callback_failures.py", check.detail)
        self.assertIn("test_list_failures_returns_tenant_scoped_safe_summaries", check.detail)
        self.assertIn("tests/test_tenant_admin_payment_callback_failures.py", check.detail)
        self.assertIn("test_list_payment_callback_failures_returns_safe_tenant_scoped_payload", check.detail)
        self.assertIn("tests/test_payment_config_service.py", check.detail)
        self.assertIn("test_normalize_epusdt_base_url_rejects_embedded_credentials_and_query", check.detail)
        self.assertIn("test_list_payment_provider_summaries_exposes_safe_static_capabilities", check.detail)
        self.assertIn("USDT_TRC20_DIRECT_PROVIDER", check.detail)
        self.assertIn("Trc20DirectConfig", check.detail)
        self.assertIn("usdt_trc20_direct", check.detail)
        self.assertIn("usdt_trc20_direct_offline_config_v1", check.detail)
        self.assertIn("offline_direct_chain_config", check.detail)
        self.assertIn("validate_payment_provider_config_payload", check.detail)
        self.assertIn('ConfigDict(extra="allow"', check.detail)
        self.assertIn('"additionalProperties": False', check.detail)
        self.assertIn("create_payment_available=True", check.detail)
        self.assertIn("callback_available=False", check.detail)
        self.assertIn("query_order_available=False", check.detail)
        self.assertIn("reconcile_available=False", check.detail)
        self.assertIn("offline_only=True", check.detail)
        self.assertIn("TENANT_DIRECT_PAYMENT_PROVIDER_PRIORITY", check.detail)
        self.assertIn("TRON_BASE58_CHARS", check.detail)
        self.assertIn("TRON_BASE58_ALPHABET", check.detail)
        self.assertIn("TRON_BASE58_CHECK_VERSION", check.detail)
        self.assertIn("TRC20_DIRECT_CONFIG_FIELDS", check.detail)
        self.assertIn("_decode_base58", check.detail)
        self.assertIn("_reject_config_fields", check.detail)
        self.assertIn("_reject_unknown_config_fields", check.detail)
        self.assertIn("_normalize_tron_address", check.detail)
        self.assertIn("app/services/payments/trc20_direct.py", check.detail)
        self.assertIn("TronUsdtTransfer", check.detail)
        self.assertIn("TronUsdtPaymentCandidate", check.detail)
        self.assertIn("TronUsdtMatchDecision", check.detail)
        self.assertIn("parse_tron_usdt_transfer", check.detail)
        self.assertIn("match_tron_usdt_transfer", check.detail)
        self.assertIn("duplicate_tx", check.detail)
        self.assertIn("not_confirmed", check.detail)
        self.assertIn("ambiguous", check.detail)
        self.assertIn("test_trc20_direct_config_normalization_is_offline_only_and_rejects_unsafe_values", check.detail)
        self.assertIn("tests/test_trc20_direct_core.py", check.detail)
        self.assertIn("test_parse_standard_trc20_usdt_transfer_without_network", check.detail)
        self.assertIn("test_match_transfer_requires_confirmation_and_deduplicates_tx_hash", check.detail)
        self.assertIn("test_match_transfer_rejects_ambiguous_candidate_window", check.detail)
        self.assertIn("invalid_checksum_address", check.detail)
        self.assertIn("tests/test_payment_create_service.py", check.detail)
        self.assertIn("test_create_payment_for_order_creates_trc20_direct_offline_intent_without_network", check.detail)
        self.assertIn("test_create_payment_for_order_reuses_existing_trc20_direct_intent", check.detail)
        self.assertIn("test_provider_factory_creates_trc20_direct_offline_provider", check.detail)
        self.assertIn("test_get_trc20_direct_config_is_tenant_scoped_and_redacted", check.detail)
        self.assertIn("test_update_trc20_direct_config_commits_and_returns_masked_address_without_key", check.detail)
        self.assertIn(
            "test_update_trc20_direct_config_rejects_unsupported_sensitive_fields_before_service",
            check.detail,
        )
        self.assertIn("tron_api_key", check.detail)
        self.assertIn("test_payment_config_schema_exposes_safe_fields_only", check.detail)
        self.assertIn("test_payment_provider_list_schema_exposes_safe_fields_only", check.detail)
        self.assertIn("test_payment_callback_failure_schema_exposes_safe_fields_only", check.detail)
        self.assertIn("test_payment_callback_rejection_operation_is_documented_as_tenant_admin", check.detail)
        self.assertIn("test_payment_callback_rejection_schema_exposes_safe_fields_only", check.detail)

    def test_trc20_direct_reconcile_contract_requires_offline_transfer_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            models = root / "app" / "db" / "models" / "orders.py"
            models.parent.mkdir(parents=True)
            models.write_text(
                "\n".join(
                    [
                        "Trc20DirectTransfer",
                        '__tablename__ = "trc20_direct_transfers"',
                        "tenant_id",
                        "tx_hash",
                    ]
                ),
                encoding="utf-8",
            )
            trc20_core = root / "app" / "services" / "payments" / "trc20_direct.py"
            trc20_core.parent.mkdir(parents=True)
            trc20_core.write_text(
                "\n".join(
                    [
                        "TronUsdtTransfer",
                        "TronUsdtPaymentCandidate",
                        "TronUsdtMatchDecision",
                        "match_tron_usdt_transfer",
                    ]
                ),
                encoding="utf-8",
            )
            reconcile_service = root / "app" / "services" / "payments" / "trc20_reconcile.py"
            reconcile_service.write_text("Trc20DirectReconcileService\nrecord_transfer\n", encoding="utf-8")

            check = staging_readiness._check_trc20_direct_reconcile_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("app/db/models/orders.py:payment_id", check.detail)
        self.assertIn("app/db/models/orders.py:match_status", check.detail)
        self.assertIn("app/db/models/orders.py:'duplicate_tx'", check.detail)
        self.assertIn("app/db/models/__init__.py:Trc20DirectTransfer", check.detail)
        self.assertIn("app/services/payments/trc20_direct.py:duplicate_tx", check.detail)
        self.assertIn("app/services/payments/trc20_direct.py:not_confirmed", check.detail)
        self.assertIn("app/services/payments/trc20_direct.py:ambiguous", check.detail)
        self.assertIn("app/services/payments/trc20_direct.py:matched", check.detail)
        self.assertIn("app/services/payments/trc20_reconcile.py:match_pending_payment", check.detail)
        self.assertIn("app/services/payments/trc20_reconcile.py:USDT_TRC20_DIRECT_PROVIDER", check.detail)
        self.assertIn("app/services/payments/__init__.py:Trc20DirectReconcileService", check.detail)
        self.assertIn("alembic/versions/20260609_0023*.py", check.detail)
        self.assertIn("tests/test_trc20_direct_reconcile_service.py", check.detail)
        self.assertIn("test_record_transfer_persists_offline_transfer_without_network_or_env", check.detail)
        self.assertIn("test_match_pending_payment_marks_payment_and_order_matched", check.detail)

    def test_tenant_admin_trc20_direct_transfer_observation_contract_requires_safe_api_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            tenant_admin = root / "app" / "web" / "tenant_admin.py"
            tenant_admin.parent.mkdir(parents=True)
            tenant_admin.write_text(
                "\n".join(
                    [
                        "TenantTrc20DirectTransferItem",
                        '"/payments/trc20-direct/transfers"',
                    ]
                ),
                encoding="utf-8",
            )
            observation_service = root / "app" / "services" / "payments" / "trc20_observability.py"
            observation_service.parent.mkdir(parents=True)
            observation_service.write_text(
                "\n".join(
                    [
                        "Trc20DirectTransferObservationService",
                        "list_tenant_transfers",
                        "from_address_masked",
                    ]
                ),
                encoding="utf-8",
            )
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_openapi_security_contract.py").write_text(
                "test_trc20_direct_transfer_observation_operation_is_documented_as_tenant_admin\n",
                encoding="utf-8",
            )
            docs_dir = root / "docs"
            docs_dir.mkdir()
            (docs_dir / "开发交接说明.md").write_text("不扫链\n不外联\n", encoding="utf-8")
            (docs_dir / "实施路线图.md").write_text("不代表生产直付\n", encoding="utf-8")
            (docs_dir / "数据库设计.md").write_text("/payments/trc20-direct/transfers\n", encoding="utf-8")

            check = staging_readiness._check_tenant_admin_trc20_direct_transfer_observation_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("TenantTrc20DirectTransferListResponse", check.detail)
        self.assertIn('require_scope("payments:read")', check.detail)
        self.assertIn("to_address_masked", check.detail)
        self.assertIn("Trc20DirectTransfer.tenant_id == tenant_id", check.detail)
        self.assertIn("normalize_tron_tx_hash", check.detail)
        self.assertIn("test_trc20_direct_transfer_observation_schema_exposes_safe_fields_only", check.detail)
        self.assertIn("tenant_id", check.detail)
        self.assertIn("payment_id", check.detail)
        self.assertIn("order_id", check.detail)
        self.assertIn("raw_payload", check.detail)
        self.assertIn("payload_json", check.detail)
        self.assertIn("metadata_json", check.detail)
        self.assertIn("不读取 `.env`", check.detail)

    def test_tenant_admin_finance_withdrawal_contract_requires_routes_scopes_and_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            tenant_admin = root / "app" / "web" / "tenant_admin.py"
            tenant_admin.parent.mkdir(parents=True)
            tenant_admin.write_text(
                "\n".join(
                    [
                        "TenantLedgerBalanceResponse",
                        "TenantWithdrawalItem",
                        '"/finance/balance"',
                        'require_scope("finance:read")',
                        "LedgerService",
                        "address_masked",
                    ]
                ),
                encoding="utf-8",
            )
            ledger = root / "app" / "services" / "ledger.py"
            ledger.parent.mkdir(parents=True)
            ledger.write_text("async def get_withdrawal\n", encoding="utf-8")
            api_keys = root / "app" / "services" / "api_keys.py"
            api_keys.parent.mkdir(parents=True, exist_ok=True)
            api_keys.write_text('"finance:read"\n', encoding="utf-8")
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_tenant_admin_finance.py").write_text(
                "test_get_finance_balance_requires_finance_read_scope_before_service\n",
                encoding="utf-8",
            )
            (tests_dir / "test_openapi_security_contract.py").write_text(
                "test_finance_operations_are_documented_as_tenant_admin\n",
                encoding="utf-8",
            )
            (tests_dir / "test_api_key_scopes.py").write_text('"finance:read"\n', encoding="utf-8")

            check = staging_readiness._check_tenant_admin_finance_withdrawal_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("TenantLedgerBalanceAuditResponse", check.detail)
        self.assertIn("ListTenantWithdrawalsResponse", check.detail)
        self.assertIn("CreateTenantWithdrawalRequest", check.detail)
        self.assertIn('"/finance/ledger/audit"', check.detail)
        self.assertIn('"/finance/withdrawals"', check.detail)
        self.assertIn('"/finance/withdrawals/{withdrawal_id}"', check.detail)
        self.assertIn('require_scope("finance:write")', check.detail)
        self.assertIn('"finance:write"', check.detail)
        self.assertIn("audit_account_balance", check.detail)
        self.assertIn("create_withdrawal_request", check.detail)
        self.assertIn("async def audit_account_balance", check.detail)
        self.assertIn("WithdrawalRequest.tenant_id == tenant_id", check.detail)
        self.assertIn("WithdrawalRequest.id == withdrawal_id", check.detail)
        self.assertIn("_ledger_balance_audit_response", check.detail)
        self.assertIn("_mask_finance_address", check.detail)
        self.assertIn("_safe_finance_error_detail", check.detail)
        self.assertIn("test_get_finance_ledger_audit_requires_finance_read_scope_before_service", check.detail)
        self.assertIn("test_get_finance_ledger_audit_is_tenant_scoped_and_safe", check.detail)
        self.assertIn("test_list_withdrawals_requires_finance_read_scope_before_service", check.detail)
        self.assertIn("test_get_withdrawal_requires_finance_read_scope_before_service", check.detail)
        self.assertIn("test_get_withdrawal_is_tenant_scoped_and_redacted", check.detail)
        self.assertIn("test_get_withdrawal_returns_404_for_missing_or_cross_tenant", check.detail)
        self.assertIn("test_create_withdrawal_requires_finance_write_scope_before_service", check.detail)
        self.assertIn("test_create_withdrawal_commits_and_returns_masked_address", check.detail)
        self.assertIn("test_create_withdrawal_runtime_error_returns_503_and_redacts_secret", check.detail)
        self.assertIn("test_create_withdrawal_rejects_invalid_amount_precision_before_service", check.detail)
        self.assertIn("test_finance_balance_schema_exposes_safe_fields_only", check.detail)
        self.assertIn("test_finance_ledger_audit_schema_exposes_safe_fields_only", check.detail)
        self.assertIn("test_withdrawal_schema_exposes_masked_address_only", check.detail)
        self.assertIn("TenantWithdrawalItem", check.detail)
        self.assertIn("/api/v1/tenant/finance/ledger/audit", check.detail)
        self.assertIn("reviewed_at", check.detail)
        self.assertIn("completed_at", check.detail)

    def test_tenant_admin_order_diagnostics_contract_requires_attempt_overview_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            tenant_admin = root / "app" / "web" / "tenant_admin.py"
            tenant_admin.parent.mkdir(parents=True)
            tenant_admin.write_text(
                "\n".join(
                    [
                        "OrderDiagnosticsResponse",
                        "OrderPaymentDiagnosticItem",
                        "OrderPaymentCallbackDiagnosticItem",
                        "OrderDeliveryDiagnosticItem",
                        "OrderExternalFulfillmentDiagnosticItem",
                        '"/orders/{out_trade_no}/diagnostics"',
                        'require_scope("orders:read")',
                        "OrderDiagnosticsService",
                        "_order_diagnostics_response",
                        "_order_payment_diagnostic_response",
                        "_order_callback_diagnostic_response",
                        "_order_delivery_diagnostic_response",
                    ]
                ),
                encoding="utf-8",
            )
            service = root / "app" / "services" / "order_diagnostics.py"
            service.parent.mkdir(parents=True)
            service.write_text(
                "\n".join(
                    [
                        "OrderDiagnosticsService",
                        "OrderDiagnosticsSummary",
                        "OrderPaymentDiagnostic",
                        "OrderPaymentCallbackDiagnostic",
                        "OrderDeliveryDiagnostic",
                        "OrderExternalFulfillmentDiagnostic",
                        "has_payment_url",
                        "has_inventory_item",
                        "has_uploaded_file",
                        "has_telegram_chat",
                        "SENSITIVE_PAYMENT_FAILURE_VALUE_MARKERS",
                    ]
                ),
                encoding="utf-8",
            )
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_tenant_admin_runtime_auth.py").write_text(
                "\n".join(
                    [
                        "test_order_diagnostics_requires_orders_read_scope_before_service",
                        "test_order_diagnostics_returns_safe_tenant_scoped_summary",
                        "test_order_diagnostics_returns_404_for_cross_tenant_or_missing_order",
                        "test_order_diagnostics_value_error_returns_400_without_secret",
                        "provider_trade_no",
                        "payload_json",
                        "payment_url",
                        "supplier_tenant_id",
                        "external_product_id",
                    ]
                ),
                encoding="utf-8",
            )
            (tests_dir / "test_order_diagnostics_service.py").write_text(
                "\n".join(
                    [
                        "test_get_summary_returns_safe_payment_callback_delivery_and_external_mapping",
                        "test_get_summary_returns_none_for_missing_or_cross_tenant_order",
                        "test_get_summary_rejects_invalid_out_trade_no_before_query",
                        "test_get_summary_does_not_query_product_for_reseller_order",
                        "provider_trade_no",
                        "payload_json",
                        "payment_url",
                        "supplier_tenant_id",
                    ]
                ),
                encoding="utf-8",
            )
            (tests_dir / "test_openapi_security_contract.py").write_text(
                "\n".join(
                    [
                        "test_order_diagnostics_schema_exposes_safe_fields_only",
                        "OrderDiagnosticsResponse",
                        "OrderPaymentDiagnosticItem",
                        "OrderPaymentCallbackDiagnosticItem",
                        "OrderDeliveryDiagnosticItem",
                        "OrderExternalFulfillmentDiagnosticItem",
                        "/api/v1/tenant/orders/{out_trade_no}/diagnostics",
                        "provider_trade_no",
                        "payload_json",
                        "payment_url",
                        "supplier_tenant_id",
                        "external_product_id",
                    ]
                ),
                encoding="utf-8",
            )

            check = staging_readiness._check_tenant_admin_order_diagnostics_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("_order_external_fulfillment_diagnostic_response", check.detail)
        self.assertIn("ExternalFulfillmentAttempt", check.detail)
        self.assertIn("ExternalFulfillmentAttempt.tenant_id == tenant_id", check.detail)
        self.assertIn("ExternalFulfillmentAttempt.order_id == order_id", check.detail)
        self.assertIn("attempt_count", check.detail)
        self.assertIn("latest_attempt_status", check.detail)
        self.assertIn("latest_attempt_source", check.detail)
        self.assertIn("latest_attempt_at", check.detail)
        self.assertIn("latest_failure_stage", check.detail)
        self.assertIn("latest_failure_category", check.detail)
        self.assertIn("latest_failure_retryable", check.detail)
        self.assertIn("latest_upstream_status_code", check.detail)
        self.assertIn("latest_item_count", check.detail)
        self.assertIn("latest_delivery_record_linked", check.detail)
        self.assertIn(
            "test_get_summary_returns_external_fulfillment_attempt_overview_without_sensitive_identifiers",
            check.detail,
        )
        self.assertIn("test_get_summary_returns_external_attempt_zero_count_without_latest_fields", check.detail)
        self.assertIn("OrderTrc20DirectDiagnosticItem", check.detail)
        self.assertIn("_order_trc20_direct_diagnostic_response", check.detail)
        self.assertIn("OrderTrc20DirectDiagnostic", check.detail)
        self.assertIn("Trc20DirectTransfer", check.detail)
        self.assertIn("Trc20DirectTransfer.tenant_id == tenant_id", check.detail)
        self.assertIn("Trc20DirectTransfer.order_id", check.detail)
        self.assertIn("trc20_direct", check.detail)
        self.assertIn("transfer_count", check.detail)
        self.assertIn("latest_match_status", check.detail)
        self.assertIn("latest_confirmations", check.detail)
        self.assertIn("latest_matched_at", check.detail)
        self.assertIn("latest_amount", check.detail)
        self.assertIn("tx_hash", check.detail)
        self.assertIn("from_address", check.detail)
        self.assertIn("to_address", check.detail)
        self.assertIn("metadata_json", check.detail)
        self.assertIn("orders:read 安全聚合", check.detail)
        self.assertIn("完整转账摘要仍走", check.detail)
        self.assertIn("TRC20 转账观测接口", check.detail)
        self.assertIn("不读取 `.env`", check.detail)

    def test_tenant_admin_audit_log_contract_requires_scope_routes_and_safe_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            tenant_admin = root / "app" / "web" / "tenant_admin.py"
            tenant_admin.parent.mkdir(parents=True)
            tenant_admin.write_text(
                "\n".join(
                    [
                        "TenantAuditLogItem",
                        '"/audit-logs"',
                        "AuditLogService",
                    ]
                ),
                encoding="utf-8",
            )
            api_keys = root / "app" / "services" / "api_keys.py"
            api_keys.parent.mkdir(parents=True)
            api_keys.write_text('"audit_logs:read"\n', encoding="utf-8")
            audit_service = root / "app" / "services" / "audit.py"
            audit_service.write_text("list_tenant_audit_logs\n", encoding="utf-8")
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_tenant_admin_runtime_auth.py").write_text(
                "test_list_audit_logs_requires_audit_logs_read_scope_before_service\n",
                encoding="utf-8",
            )
            (tests_dir / "test_audit_log_service.py").write_text(
                "test_list_tenant_audit_logs_supports_safe_filters_and_redaction\n",
                encoding="utf-8",
            )
            (tests_dir / "test_openapi_security_contract.py").write_text(
                "test_tenant_audit_log_operation_is_documented_as_tenant_admin\n",
                encoding="utf-8",
            )
            (tests_dir / "test_api_key_scopes.py").write_text('"audit_logs:read"\n', encoding="utf-8")

            check = staging_readiness._check_tenant_admin_audit_log_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("ListTenantAuditLogsResponse", check.detail)
        self.assertIn('require_scope("audit_logs:read")', check.detail)
        self.assertIn("safe_metadata_for_tenant_api", check.detail)
        self.assertIn("_normalize_optional_filter", check.detail)
        self.assertIn("provider_trade_no", check.detail)
        self.assertIn("payment_url", check.detail)
        self.assertIn("test_list_audit_logs_returns_safe_tenant_scoped_payload", check.detail)
        self.assertIn("test_safe_metadata_for_tenant_api_removes_sensitive_keys_recursively", check.detail)
        self.assertIn("test_tenant_audit_log_schema_exposes_safe_fields_only", check.detail)
        self.assertIn('has_scope(["audit_logs:read"], "audit_logs:read")', check.detail)

    def test_tenant_admin_risk_observability_contract_requires_scope_routes_and_safe_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            tenant_admin = root / "app" / "web" / "tenant_admin.py"
            tenant_admin.parent.mkdir(parents=True)
            tenant_admin.write_text(
                "\n".join(
                    [
                        "TenantRiskDisputeItem",
                        '"/risk/disputes"',
                        "RiskControlService",
                    ]
                ),
                encoding="utf-8",
            )
            api_keys = root / "app" / "services" / "api_keys.py"
            api_keys.parent.mkdir(parents=True)
            api_keys.write_text('"risk:read"\n', encoding="utf-8")
            risk_service = root / "app" / "services" / "risk.py"
            risk_service.write_text("list_disputes\nlist_after_sales\n", encoding="utf-8")
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_tenant_admin_runtime_auth.py").write_text(
                "test_list_risk_disputes_requires_risk_read_scope_before_service\n",
                encoding="utf-8",
            )
            (tests_dir / "test_risk_control_rules.py").write_text(
                "test_list_disputes_rejects_invalid_status_before_query\n",
                encoding="utf-8",
            )
            (tests_dir / "test_openapi_security_contract.py").write_text(
                "TenantRiskDisputeItem\n",
                encoding="utf-8",
            )
            (tests_dir / "test_api_key_scopes.py").write_text('"risk:read"\n', encoding="utf-8")

            check = staging_readiness._check_tenant_admin_risk_observability_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("ListTenantRiskDisputesResponse", check.detail)
        self.assertIn("TenantRiskAfterSaleItem", check.detail)
        self.assertIn('"/risk/after-sales"', check.detail)
        self.assertIn('require_scope("risk:read")', check.detail)
        self.assertIn("_safe_risk_text", check.detail)
        self.assertIn("DISPUTE_STATUSES", check.detail)
        self.assertIn("AfterSaleCase.tenant_id == tenant_id", check.detail)
        self.assertIn("test_list_risk_disputes_is_tenant_scoped_and_sanitizes_text", check.detail)
        self.assertIn("test_tenant_risk_observability_schema_exposes_safe_fields_only", check.detail)
        self.assertIn('has_scope(["risk:read"], "risk:read")', check.detail)

    def test_platform_admin_risk_ban_observability_contract_requires_independent_auth_and_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config = root / "app" / "config.py"
            config.parent.mkdir(parents=True)
            config.write_text("platform_admin_api_key_hashes\n", encoding="utf-8")
            main_py = root / "app" / "main.py"
            main_py.write_text("create_platform_admin_router\n", encoding="utf-8")
            openapi = root / "app" / "web" / "openapi.py"
            openapi.parent.mkdir(parents=True, exist_ok=True)
            openapi.write_text("PlatformAdminBearer\n", encoding="utf-8")
            platform_admin = root / "app" / "web" / "platform_admin.py"
            platform_admin.write_text("create_platform_admin_router\n", encoding="utf-8")
            risk_service = root / "app" / "services" / "risk.py"
            risk_service.parent.mkdir(parents=True, exist_ok=True)
            risk_service.write_text("PlatformRiskBannedUserSummary\n", encoding="utf-8")
            api_keys = root / "app" / "services" / "api_keys.py"
            api_keys.write_text('"tenant_admin:*"\n"platform_risk:read"\n', encoding="utf-8")
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_platform_admin_runtime_auth.py").write_text(
                "test_platform_admin_missing_config_fails_closed_before_service\n",
                encoding="utf-8",
            )
            (tests_dir / "test_risk_control_rules.py").write_text(
                "PlatformRiskObservabilityTest\n",
                encoding="utf-8",
            )
            (tests_dir / "test_openapi_security_contract.py").write_text(
                "test_platform_admin_security_schemes_are_declared\n",
                encoding="utf-8",
            )
            (tests_dir / "test_app_runtime_smoke.py").write_text(
                "/api/v1/platform/risk/banned-users\n",
                encoding="utf-8",
            )

            check = staging_readiness._check_platform_admin_risk_ban_observability_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("platform_admin_require_signature", check.detail)
        self.assertIn("application.include_router(create_platform_admin_router(settings))", check.detail)
        self.assertIn("PlatformAdminApiKeyHeader", check.detail)
        self.assertIn("X-Platform-API-Key", check.detail)
        self.assertIn('"/risk/banned-users"', check.detail)
        self.assertIn('"/risk/users/{telegram_user_id}/ban-status"', check.detail)
        self.assertIn("PlatformRiskBanStatusResponse", check.detail)
        self.assertIn("Platform Admin API 未启用", check.detail)
        self.assertIn('require_platform_scope("platform_risk:read")', check.detail)
        self.assertIn("list_banned_platform_users", check.detail)
        self.assertIn("get_platform_user_ban_status", check.detail)
        self.assertIn("_latest_platform_user_status_audit", check.detail)
        self.assertIn("platform_risk.user_unbanned", check.detail)
        self.assertIn("PlatformUser.is_banned.is_(True)", check.detail)
        self.assertIn("app/services/api_keys.py:platform_risk:read must not be in TenantApiKey scopes", check.detail)
        self.assertIn("test_tenant_api_key_cannot_access_platform_risk_observability", check.detail)
        self.assertIn("test_get_ban_status_rejects_tenant_api_key_before_service", check.detail)
        self.assertIn("test_list_banned_platform_users_returns_manual_ban_summary", check.detail)
        self.assertIn("test_get_platform_user_ban_status_returns_manual_banned_user", check.detail)
        self.assertIn("test_get_platform_user_ban_status_returns_none_for_missing_user", check.detail)
        self.assertIn("test_all_platform_admin_operations_declare_independent_security_and_signature_contract", check.detail)
        self.assertIn("test_platform_risk_banned_user_schema_exposes_safe_fields_only", check.detail)
        self.assertIn("test_platform_risk_ban_status_schema_exposes_safe_fields_only", check.detail)

    def test_platform_admin_risk_user_ban_action_contract_requires_write_scope_and_safe_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            platform_admin = root / "app" / "web" / "platform_admin.py"
            platform_admin.parent.mkdir(parents=True)
            platform_admin.write_text(
                "\n".join(
                    [
                        "PlatformRiskBanStatusUpdateRequest",
                        '"/risk/users/{telegram_user_id}/ban-status"',
                    ]
                ),
                encoding="utf-8",
            )
            tenant_admin = root / "app" / "web" / "tenant_admin.py"
            tenant_admin.write_text("platform_risk:write\n", encoding="utf-8")
            risk_service = root / "app" / "services" / "risk.py"
            risk_service.parent.mkdir(parents=True)
            risk_service.write_text("ban_platform_user\nunban_platform_user\n", encoding="utf-8")
            api_keys = root / "app" / "services" / "api_keys.py"
            api_keys.write_text('"platform_risk:write"\n', encoding="utf-8")
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_platform_admin_runtime_auth.py").write_text(
                "test_platform_risk_ban_status_update_rejects_tenant_api_key_before_service\n",
                encoding="utf-8",
            )
            (tests_dir / "test_risk_control_rules.py").write_text(
                "test_ban_platform_user_updates_status_and_writes_audit\n",
                encoding="utf-8",
            )
            (tests_dir / "test_openapi_security_contract.py").write_text(
                "test_platform_risk_ban_status_update_operation_is_documented_as_platform_admin\n",
                encoding="utf-8",
            )
            docs_dir = root / "docs"
            docs_dir.mkdir()
            (docs_dir / "实施路线图.md").write_text(
                "Platform Admin 平台用户封禁/解封 HTTP 写入口\n",
                encoding="utf-8",
            )
            (docs_dir / "开发交接说明.md").write_text(
                "Platform Admin 平台用户封禁/解封 HTTP 写入口\n",
                encoding="utf-8",
            )
            (docs_dir / "多租户发卡平台完整方案.md").write_text(
                "Platform Admin 平台用户封禁/解封 HTTP 写入口\n",
                encoding="utf-8",
            )

            check = staging_readiness._check_platform_admin_risk_user_ban_action_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("PLATFORM_RISK_WRITE_SCOPE", check.detail)
        self.assertIn('require_platform_scope("platform_risk:write")', check.detail)
        self.assertIn("get_platform_user_ban_status", check.detail)
        self.assertIn("_normalize_platform_risk_ban_status", check.detail)
        self.assertIn("actor_user_id: Optional[int]", check.detail)
        self.assertIn("_sanitize_platform_ban_reason(self._normalize_reason(reason))", check.detail)
        self.assertIn("app/services/api_keys.py:platform_risk:write must not be in TenantApiKey scopes", check.detail)
        self.assertIn("app/web/tenant_admin.py:must not expose Platform Admin user ban actions", check.detail)
        self.assertIn("test_platform_risk_ban_status_update_requires_platform_risk_write_before_service", check.detail)
        self.assertIn("test_platform_risk_ban_status_update_rejects_extra_fields_before_service", check.detail)
        self.assertIn("test_ban_platform_user_hides_sensitive_reason_and_allows_platform_api_actor_none", check.detail)
        self.assertIn("test_platform_risk_ban_status_update_schema_exposes_safe_fields_only", check.detail)
        self.assertIn("不接受客户端传入 actor 或 metadata", check.detail)

    def test_platform_admin_risk_audit_log_contract_requires_platform_scope_and_safe_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            platform_admin = root / "app" / "web" / "platform_admin.py"
            platform_admin.parent.mkdir(parents=True)
            platform_admin.write_text(
                "\n".join(
                    [
                        '"/risk/audit-logs"',
                        "PlatformRiskAuditLogItem",
                    ]
                ),
                encoding="utf-8",
            )
            tenant_admin = root / "app" / "web" / "tenant_admin.py"
            tenant_admin.write_text('"/risk/audit-logs"\n', encoding="utf-8")
            openapi = root / "app" / "web" / "openapi.py"
            openapi.write_text("PlatformAdminBearer\n", encoding="utf-8")
            audit_service = root / "app" / "services" / "audit.py"
            audit_service.parent.mkdir(parents=True)
            audit_service.write_text(
                "\n".join(
                    [
                        "PlatformRiskAuditLogSummary",
                        "list_platform_risk_audit_logs",
                        "AuditLog.tenant_id.is_(None)",
                    ]
                ),
                encoding="utf-8",
            )
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_platform_admin_runtime_auth.py").write_text(
                "test_list_platform_risk_audit_logs_missing_config_fails_closed_before_service\n",
                encoding="utf-8",
            )
            (tests_dir / "test_audit_log_service.py").write_text(
                "test_list_platform_risk_audit_logs_filters_platform_scope_and_action_prefix\n",
                encoding="utf-8",
            )
            (tests_dir / "test_openapi_security_contract.py").write_text(
                "test_platform_risk_audit_logs_operation_is_documented_as_platform_admin\n",
                encoding="utf-8",
            )
            (tests_dir / "test_app_runtime_smoke.py").write_text("", encoding="utf-8")

            check = staging_readiness._check_platform_admin_risk_audit_log_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("ListPlatformRiskAuditLogsResponse", check.detail)
        self.assertIn("PlatformRiskAuditLogSummary", check.detail)
        self.assertIn("list_platform_risk_audit_logs", check.detail)
        self.assertIn('require_platform_scope("platform_risk:read")', check.detail)
        self.assertIn("app/web/tenant_admin.py:must not expose Platform Admin risk audit logs", check.detail)
        self.assertIn("PlatformAdminApiKeyHeader", check.detail)
        self.assertIn("X-Platform-API-Key", check.detail)
        self.assertIn("AuditLog.action.like", check.detail)
        self.assertIn("PLATFORM_RISK_ACTION_PREFIX", check.detail)
        self.assertIn("_to_platform_risk_summary", check.detail)
        self.assertIn("_safe_platform_audit_text", check.detail)
        self.assertIn("_target_telegram_user_id_from_metadata", check.detail)
        self.assertIn("test_list_platform_risk_audit_logs_rejects_tenant_api_key_before_service", check.detail)
        self.assertIn("test_list_platform_risk_audit_logs_returns_safe_payload_only", check.detail)
        self.assertIn("test_list_platform_risk_audit_logs_returns_safe_summary_fields_only", check.detail)
        self.assertIn("test_platform_risk_audit_log_schema_exposes_safe_fields_only", check.detail)
        self.assertIn("/api/v1/platform/risk/audit-logs", check.detail)

    def test_tenant_admin_report_export_jobs_contract_requires_scope_routes_and_safe_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            tenant_admin = root / "app" / "web" / "tenant_admin.py"
            tenant_admin.parent.mkdir(parents=True)
            tenant_admin.write_text(
                "\n".join(
                    [
                        "TenantReportExportJobItem",
                        '"/reports/export-jobs"',
                        "ReportExportService",
                    ]
                ),
                encoding="utf-8",
            )
            api_keys = root / "app" / "services" / "api_keys.py"
            api_keys.parent.mkdir(parents=True)
            api_keys.write_text('"reports:read"\n', encoding="utf-8")
            report_service = root / "app" / "services" / "reports.py"
            report_service.write_text("list_export_jobs\n", encoding="utf-8")
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_tenant_admin_runtime_auth.py").write_text(
                "test_list_report_export_jobs_requires_reports_read_scope_before_service\n",
                encoding="utf-8",
            )
            (tests_dir / "test_report_export_service.py").write_text(
                "test_list_export_jobs_rejects_invalid_status_before_query\n",
                encoding="utf-8",
            )
            (tests_dir / "test_openapi_security_contract.py").write_text(
                "test_report_export_jobs_operation_is_documented_as_tenant_admin\n",
                encoding="utf-8",
            )
            (tests_dir / "test_api_key_scopes.py").write_text('"reports:read"\n', encoding="utf-8")

            check = staging_readiness._check_tenant_admin_report_export_jobs_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("ListTenantReportExportJobsResponse", check.detail)
        self.assertIn("CreateTenantReportExportJobRequest", check.detail)
        self.assertIn('require_scope("reports:read")', check.detail)
        self.assertIn('require_scope("reports:write")', check.detail)
        self.assertIn("tenant_id=api_key.tenant_id", check.detail)
        self.assertIn("create_export_job", check.detail)
        self.assertIn('status="pending"', check.detail)
        self.assertIn("report.export_requested", check.detail)
        self.assertIn("_normalize_report_export_status", check.detail)
        self.assertIn("_normalize_report_export_type", check.detail)
        self.assertIn("_safe_report_failure_text", check.detail)
        self.assertIn("SUPPORTED_EXPORT_JOB_STATUSES", check.detail)
        self.assertIn("ExportJob.report_type == normalized_report_type", check.detail)
        self.assertIn("test_create_report_export_job_requires_reports_write_scope_before_service", check.detail)
        self.assertIn("test_create_export_job_rejects_invalid_report_type_before_insert", check.detail)
        self.assertIn("test_create_report_export_job_operation_is_documented_as_tenant_admin", check.detail)
        self.assertIn(
            "test_create_report_export_job_schema_accepts_report_type_only_and_returns_safe_pending_summary",
            check.detail,
        )
        self.assertIn("test_list_report_export_jobs_is_tenant_scoped_and_redacted", check.detail)
        self.assertIn("test_list_export_jobs_rejects_invalid_report_type_before_query", check.detail)
        self.assertIn("test_report_export_jobs_schema_exposes_safe_fields_only", check.detail)
        self.assertIn('has_scope(["reports:read"], "reports:read")', check.detail)
        self.assertIn('has_scope(["reports:write"], "reports:write")', check.detail)
        self.assertIn("Tenant Admin 报表任务创建 API 合同", check.detail)
        self.assertIn("不同步生成 CSV", check.detail)
        self.assertIn("不启动 worker", check.detail)
        self.assertIn("不返回下载链接", check.detail)

    def test_tenant_admin_subscription_read_contract_requires_routes_scopes_and_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            tenant_admin = root / "app" / "web" / "tenant_admin.py"
            tenant_admin.parent.mkdir(parents=True)
            tenant_admin.write_text(
                "\n".join(
                    [
                        "TenantSubscriptionResponse",
                        "TenantSubscriptionInvoiceItem",
                        '"/subscription/status"',
                        "SubscriptionService",
                    ]
                ),
                encoding="utf-8",
            )
            api_keys = root / "app" / "services" / "api_keys.py"
            api_keys.parent.mkdir(parents=True)
            api_keys.write_text('"subscriptions:read"\n', encoding="utf-8")
            subscription_service = root / "app" / "services" / "subscriptions.py"
            subscription_service.write_text("get_tenant_subscription_summary\n", encoding="utf-8")
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_tenant_admin_runtime_auth.py").write_text(
                "test_get_subscription_status_requires_subscriptions_read_scope_before_service\n",
                encoding="utf-8",
            )
            (tests_dir / "test_subscription_service.py").write_text(
                "test_get_tenant_subscription_summary_returns_none_for_missing_tenant\n",
                encoding="utf-8",
            )
            (tests_dir / "test_openapi_security_contract.py").write_text(
                "test_subscription_operations_are_documented_as_tenant_admin\n",
                encoding="utf-8",
            )
            (tests_dir / "test_api_key_scopes.py").write_text('"subscriptions:read"\n', encoding="utf-8")

            check = staging_readiness._check_tenant_admin_subscription_read_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("ListTenantSubscriptionInvoicesResponse", check.detail)
        self.assertIn('"/subscription/invoices"', check.detail)
        self.assertIn('require_scope("subscriptions:read")', check.detail)
        self.assertIn("list_tenant_subscription_invoices", check.detail)
        self.assertIn("_tenant_subscription_response", check.detail)
        self.assertIn("_tenant_subscription_invoice_response", check.detail)
        self.assertIn("TenantSubscription.tenant_id == tenant_id", check.detail)
        self.assertIn("SubscriptionInvoice.tenant_id == tenant_id", check.detail)
        self.assertIn("SubscriptionInvoice.created_at.desc()", check.detail)
        self.assertIn("SubscriptionInvoice.id.desc()", check.detail)
        self.assertIn("_normalize_invoice_limit", check.detail)
        self.assertIn("_normalize_invoice_status", check.detail)
        self.assertIn("test_get_subscription_status_returns_safe_tenant_scoped_payload", check.detail)
        self.assertIn("test_list_subscription_invoices_returns_safe_tenant_scoped_payload", check.detail)
        self.assertIn("CreateTenantSubscriptionRenewalOrderRequest", check.detail)
        self.assertIn("TenantSubscriptionRenewalOrderResponse", check.detail)
        self.assertIn('"/subscription/renewal-orders"', check.detail)
        self.assertIn('require_scope("subscriptions:write")', check.detail)
        self.assertIn("test_create_subscription_renewal_order_is_tenant_scoped_and_returns_payment_link", check.detail)
        self.assertIn("test_create_subscription_renewal_order_keeps_order_when_payment_unavailable", check.detail)
        self.assertIn("test_subscription_schema_exposes_safe_fields_only", check.detail)
        self.assertIn('has_scope(["subscriptions:read"], "subscriptions:read")', check.detail)
        self.assertIn('has_scope(["subscriptions:write"], "subscriptions:write")', check.detail)

    def test_tenant_admin_supply_reseller_contract_requires_routes_scopes_safe_schemas_and_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            tenant_admin = root / "app" / "web" / "tenant_admin.py"
            tenant_admin.parent.mkdir(parents=True)
            tenant_admin.write_text(
                "\n".join(
                    [
                        "TenantSupplyMarketOfferItem",
                        '"/supply/market-offers"',
                        "SupplyService",
                    ]
                ),
                encoding="utf-8",
            )
            api_keys = root / "app" / "services" / "api_keys.py"
            api_keys.parent.mkdir(parents=True)
            api_keys.write_text('"supply:read"\n', encoding="utf-8")
            supply_service = root / "app" / "services" / "supply.py"
            supply_service.write_text("SupplierOfferSummary\nlist_market_offers\n", encoding="utf-8")
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_tenant_admin_runtime_auth.py").write_text(
                "test_list_supply_market_requires_supply_read_scope_before_service\n",
                encoding="utf-8",
            )
            (tests_dir / "test_openapi_security_contract.py").write_text(
                "test_supply_operations_are_documented_as_tenant_admin\n",
                encoding="utf-8",
            )
            (tests_dir / "test_api_key_scopes.py").write_text('"supply:read"\n', encoding="utf-8")
            (tests_dir / "test_supply_service.py").write_text(
                "test_create_supplier_offer_rejects_invalid_price_before_query\n",
                encoding="utf-8",
            )
            docs_dir = root / "docs"
            docs_dir.mkdir()
            (docs_dir / "实施路线图.md").write_text("Tenant Admin 供货/代理商侧最小 API\n", encoding="utf-8")
            (docs_dir / "开发交接说明.md").write_text("Tenant Admin 供货/代理商侧最小 API\n", encoding="utf-8")
            (docs_dir / "多租户发卡平台完整方案.md").write_text(
                "Tenant Admin 供货/代理商侧最小 API\n",
                encoding="utf-8",
            )

            check = staging_readiness._check_tenant_admin_supply_reseller_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("ListTenantSupplyMarketOffersResponse", check.detail)
        self.assertIn("CreateTenantResellerApplicationRequest", check.detail)
        self.assertIn("CreateTenantResellerProductRequest", check.detail)
        self.assertIn('"/supply/applications"', check.detail)
        self.assertIn('"/supply/reseller-products"', check.detail)
        self.assertIn('require_scope("supply:read")', check.detail)
        self.assertIn('require_scope("supply:write")', check.detail)
        self.assertIn("_require_tenant_admin_feature", check.detail)
        self.assertIn('_require_tenant_admin_feature(session, api_key.tenant_id, "reseller")', check.detail)
        self.assertIn("reseller_tenant_id=api_key.tenant_id", check.detail)
        self.assertIn("requested_by_user_id=None", check.detail)
        self.assertIn("SupplierOffer.supplier_tenant_id != reseller_tenant_id", check.detail)
        self.assertIn("ResellerProduct.reseller_tenant_id == reseller_tenant_id", check.detail)
        self.assertIn("hide_supplier=True", check.detail)
        self.assertIn("actor_user_id: Optional[int]", check.detail)
        self.assertIn("test_reseller_supply_routes_reject_disabled_reseller_feature_before_service", check.detail)
        self.assertIn("代理售卖功能已关闭", check.detail)
        self.assertIn("test_create_reseller_application_rejects_extra_fields_before_service", check.detail)
        self.assertIn("test_create_reseller_product_is_tenant_scoped_and_redacted", check.detail)
        self.assertIn("test_create_reseller_product_rejects_invalid_sale_price_before_query", check.detail)
        self.assertIn("test_supply_schema_exposes_safe_fields_only", check.detail)
        self.assertIn("additionalProperties", check.detail)
        self.assertIn('has_scope(["supply:read"], "supply:read")', check.detail)
        self.assertIn('has_scope(["supply:write"], "supply:write")', check.detail)
        self.assertIn("不返回 `supplier_tenant_id`", check.detail)
        self.assertIn("Tenant Admin 供应商侧供货 API", check.detail)

    def test_tenant_admin_supply_supplier_contract_requires_routes_scopes_safe_schemas_and_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            tenant_admin = root / "app" / "web" / "tenant_admin.py"
            tenant_admin.parent.mkdir(parents=True)
            tenant_admin.write_text(
                "\n".join(
                    [
                        "TenantSupplierOfferItem",
                        '"/supply/supplier-offers"',
                        "create_supplier_offer",
                    ]
                ),
                encoding="utf-8",
            )
            supply_service = root / "app" / "services" / "supply.py"
            supply_service.parent.mkdir(parents=True)
            supply_service.write_text(
                "\n".join(
                    [
                        "SupplierOwnOfferSummary",
                        "create_supplier_offer",
                        "_get_supplier_product",
                    ]
                ),
                encoding="utf-8",
            )
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_tenant_admin_runtime_auth.py").write_text(
                "test_list_supplier_offers_requires_supply_read_scope_before_service\n",
                encoding="utf-8",
            )
            (tests_dir / "test_supply_service.py").write_text(
                "test_create_supplier_offer_rejects_invalid_price_before_query\n",
                encoding="utf-8",
            )
            (tests_dir / "test_openapi_security_contract.py").write_text(
                "test_supply_supplier_operations_are_documented_as_tenant_admin\n",
                encoding="utf-8",
            )
            docs_dir = root / "docs"
            docs_dir.mkdir()
            (docs_dir / "实施路线图.md").write_text("Tenant Admin 供应商侧供货 API\n", encoding="utf-8")
            (docs_dir / "开发交接说明.md").write_text("Tenant Admin 供应商侧供货 API\n", encoding="utf-8")
            (docs_dir / "多租户发卡平台完整方案.md").write_text(
                "Tenant Admin 供应商侧供货 API\n",
                encoding="utf-8",
            )

            check = staging_readiness._check_tenant_admin_supply_supplier_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("CreateTenantSupplierOfferRequest", check.detail)
        self.assertIn("UpdateTenantSupplierOfferApprovalRequest", check.detail)
        self.assertIn("ApproveTenantSupplierApplicationRequest", check.detail)
        self.assertIn("RejectTenantSupplierApplicationRequest", check.detail)
        self.assertIn('"/supply/supplier-applications/approve"', check.detail)
        self.assertIn('require_scope("supply:write")', check.detail)
        self.assertIn("_require_tenant_admin_feature", check.detail)
        self.assertIn('_require_tenant_admin_feature(session, api_key.tenant_id, "supplier")', check.detail)
        self.assertIn("supplier_tenant_id=api_key.tenant_id", check.detail)
        self.assertIn("actor_user_id=None", check.detail)
        self.assertIn("approve_reseller_application", check.detail)
        self.assertIn("reject_reseller_application", check.detail)
        self.assertIn("_require_pending_reseller_application", check.detail)
        self.assertIn("rule is None or rule.status != \"pending\"", check.detail)
        self.assertIn("product.delivery_type not in SUPPORTED_RESELLER_DELIVERY_TYPES", check.detail)
        self.assertIn("test_supplier_supply_routes_reject_disabled_supplier_feature_before_service", check.detail)
        self.assertIn("供货功能已关闭", check.detail)
        self.assertIn("test_create_supplier_offer_rejects_unsupported_delivery_type_before_offer_query", check.detail)
        self.assertIn("test_approve_reseller_application_requires_existing_pending_rule_before_approval", check.detail)
        self.assertIn("test_supply_supplier_schema_exposes_safe_fields_only", check.detail)
        self.assertIn("supplier_response_forbidden", check.detail)
        self.assertIn("只允许处理已有 `pending` 申请", check.detail)
        self.assertIn("供应商侧允许返回 `reseller_tenant_id`", check.detail)

    def test_tenant_admin_supply_supplier_rule_contract_requires_route_scope_safe_schema_and_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            tenant_admin = root / "app" / "web" / "tenant_admin.py"
            tenant_admin.parent.mkdir(parents=True)
            tenant_admin.write_text(
                "\n".join(
                    [
                        "SetTenantSupplierRuleRequest",
                        "pricing_value",
                        "min_sale_price",
                    ]
                ),
                encoding="utf-8",
            )
            supply_service = root / "app" / "services" / "supply.py"
            supply_service.parent.mkdir(parents=True)
            supply_service.write_text("set_existing_reseller_rule\n", encoding="utf-8")
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_tenant_admin_runtime_auth.py").write_text(
                "test_set_supplier_rule_requires_supply_write_before_service\n",
                encoding="utf-8",
            )
            (tests_dir / "test_supply_service.py").write_text(
                "test_set_existing_reseller_rule_rejects_invalid_price_before_query\n",
                encoding="utf-8",
            )
            (tests_dir / "test_openapi_security_contract.py").write_text(
                "test_supply_supplier_rule_operation_is_documented_as_tenant_admin\n",
                encoding="utf-8",
            )
            docs_dir = root / "docs"
            docs_dir.mkdir()
            (docs_dir / "实施路线图.md").write_text(
                "`POST /api/v1/tenant/supply/supplier-rules`\n",
                encoding="utf-8",
            )
            (docs_dir / "开发交接说明.md").write_text(
                "`POST /api/v1/tenant/supply/supplier-rules`\n",
                encoding="utf-8",
            )
            (docs_dir / "多租户发卡平台完整方案.md").write_text(
                "POST   /api/v1/tenant/supply/supplier-rules\n",
                encoding="utf-8",
            )

            check = staging_readiness._check_tenant_admin_supply_supplier_rule_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn('"/supply/supplier-rules"', check.detail)
        self.assertIn('require_scope("supply:write")', check.detail)
        self.assertIn("supplier_tenant_id=api_key.tenant_id", check.detail)
        self.assertIn("actor_user_id=None", check.detail)
        self.assertIn("代理规则参数无效", check.detail)
        self.assertIn("_validate_reseller_rule(pricing_value, min_sale_price)", check.detail)
        self.assertIn('rule is None or rule.status not in {"pending", "active"}', check.detail)
        self.assertIn("test_set_supplier_rule_rejects_extra_fields_before_service", check.detail)
        self.assertIn("test_set_supplier_rule_rejects_invalid_schema_before_service", check.detail)
        self.assertIn("test_set_supplier_rule_requires_signature_before_service", check.detail)
        self.assertIn("test_set_existing_reseller_rule_requires_existing_pending_or_active_rule_before_write", check.detail)
        self.assertIn("test_set_existing_reseller_rule_delegates_with_actor_none_for_existing_rule", check.detail)
        self.assertIn("test_supply_supplier_rule_schema_exposes_safe_fields_only", check.detail)
        self.assertIn("additionalProperties", check.detail)
        self.assertIn("不创建不存在的代理规则", check.detail)
        self.assertIn("不返回 `rule_id`", check.detail)

    def test_platform_admin_supply_offer_status_contract_requires_platform_scope_and_safe_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            platform_admin = root / "app" / "web" / "platform_admin.py"
            platform_admin.parent.mkdir(parents=True)
            platform_admin.write_text(
                "\n".join(
                    [
                        "PlatformSupplierOfferItem",
                        '"/supply/supplier-offers"',
                    ]
                ),
                encoding="utf-8",
            )
            tenant_admin = root / "app" / "web" / "tenant_admin.py"
            tenant_admin.write_text("platform_supply\n", encoding="utf-8")
            supply_service = root / "app" / "services" / "supply.py"
            supply_service.parent.mkdir(parents=True)
            supply_service.write_text("PlatformSupplierOfferSummary\n", encoding="utf-8")
            api_keys = root / "app" / "services" / "api_keys.py"
            api_keys.write_text('"platform_supply:read"\n', encoding="utf-8")
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_platform_admin_runtime_auth.py").write_text(
                "test_platform_supply_supplier_offers_rejects_tenant_api_key_before_service\n",
                encoding="utf-8",
            )
            (tests_dir / "test_supply_service.py").write_text(
                "test_list_platform_supplier_offers_rejects_invalid_status_before_query\n",
                encoding="utf-8",
            )
            (tests_dir / "test_openapi_security_contract.py").write_text(
                "test_platform_supply_operations_are_documented_as_platform_admin\n",
                encoding="utf-8",
            )
            (tests_dir / "test_app_runtime_smoke.py").write_text("", encoding="utf-8")
            docs_dir = root / "docs"
            docs_dir.mkdir()
            (docs_dir / "实施路线图.md").write_text(
                "Platform Admin 供货商品状态管控 API\n",
                encoding="utf-8",
            )
            (docs_dir / "开发交接说明.md").write_text(
                "Platform Admin 供货商品状态管控 API\n",
                encoding="utf-8",
            )
            (docs_dir / "多租户发卡平台完整方案.md").write_text(
                "Platform Admin 供货商品状态管控 API\n",
                encoding="utf-8",
            )

            check = staging_readiness._check_platform_admin_supply_offer_status_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("ListPlatformSupplierOffersResponse", check.detail)
        self.assertIn("UpdatePlatformSupplierOfferStatusRequest", check.detail)
        self.assertIn('"/supply/supplier-offers/{supplier_offer_id}/status"', check.detail)
        self.assertIn('require_platform_scope("platform_supply:read")', check.detail)
        self.assertIn('require_platform_scope("platform_supply:write")', check.detail)
        self.assertIn("_safe_platform_supply_error_detail", check.detail)
        self.assertIn("PLATFORM_SUPPLIER_OFFER_STATUSES", check.detail)
        self.assertIn('SupplierOffer.status != "deleted"', check.detail)
        self.assertIn("platform_supply.supplier_offer_status_updated", check.detail)
        self.assertIn("app/services/api_keys.py:platform_supply scopes must not be in TenantApiKey scopes", check.detail)
        self.assertIn("app/web/tenant_admin.py:must not expose Platform Admin supply controls", check.detail)
        self.assertIn("test_platform_supply_supplier_offer_status_requires_platform_supply_write_before_service", check.detail)
        self.assertIn("test_platform_supply_supplier_offer_status_rejects_extra_fields_before_service", check.detail)
        self.assertIn("test_set_platform_supplier_offer_status_changes_only_offer_status_and_audits", check.detail)
        self.assertIn("test_platform_supply_supplier_offer_schema_exposes_safe_fields_only", check.detail)
        self.assertIn("/api/v1/platform/supply/supplier-offers/{supplier_offer_id}/status", check.detail)
        self.assertIn("不复用 Tenant Admin API Key", check.detail)
        self.assertIn("状态管控最小 HTTP 切片已完成", check.detail)

    def test_public_store_contract_requires_worker_browser_flow_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            for relative_path in [
                "tests/test_telegram_webapp.py",
                "tests/test_public_store_contract.py",
                "tests/test_public_store_runtime_auth.py",
                "tests/test_openapi_security_contract.py",
                "workers/storefront/test/worker.test.mjs",
            ]:
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("placeholder\n", encoding="utf-8")

            check = staging_readiness._check_public_store_tests(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("node:vm", check.detail)
        self.assertIn("storefront browser script refreshes restored order when page returns to foreground", check.detail)
        self.assertIn("storefront browser script rejects unsafe payment urls before opening or rendering", check.detail)
        self.assertIn("FakeSessionStorage", check.detail)
        self.assertIn("X-Telegram-Init-Data", check.detail)
        self.assertIn("MAX_INIT_DATA_BYTES", check.detail)
        self.assertIn("MAX_INIT_DATA_FIELDS", check.detail)
        self.assertIn("MAX_AUTH_DATE_FUTURE_SKEW_SECONDS", check.detail)
        self.assertIn("test_rejects_future_auth_date_beyond_small_clock_skew", check.detail)
        self.assertIn("test_rejects_oversized_or_too_many_init_data_fields", check.detail)
        self.assertIn("test_rejects_invalid_user_json_shapes_and_optional_field_types", check.detail)
        self.assertIn("test_create_order_rejects_future_webapp_auth_date_before_order_service", check.detail)
        self.assertIn("unsafe browser api base url parts fall back to worker origin without rendering secrets", check.detail)
        self.assertIn("rejects backend api urls with credentials query or fragment", check.detail)

    def test_worker_storefront_error_states_contract_requires_safe_error_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            worker = root / "workers" / "storefront" / "src" / "worker.mjs"
            worker.parent.mkdir(parents=True)
            worker.write_text(
                "\n".join(
                    [
                        "apiErrorMessage",
                        "safeErrorDetail",
                        "请求过于频繁，请稍后再试",
                        "服务暂不可用，请稍后重试",
                        "normalizePaymentUrl",
                        "data-create-payment",
                        "sessionStorage",
                    ]
                ),
                encoding="utf-8",
            )
            worker_test = root / "workers" / "storefront" / "test" / "worker.test.mjs"
            worker_test.parent.mkdir(parents=True)
            worker_test.write_text(
                "\n".join(
                    [
                        "storefront browser script shows safe payment unavailable message without leaking backend detail",
                        "telegram-init-data-secret",
                    ]
                ),
                encoding="utf-8",
            )

            check = staging_readiness._check_worker_storefront_error_states_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("throw apiError(response.status, payload && payload.detail)", check.detail)
        self.assertIn("订单状态暂时无法刷新，可稍后手动刷新", check.detail)
        self.assertIn('renderOrder({ type: "warning", text: "订单状态暂时无法刷新，可稍后手动刷新" })', check.detail)
        self.assertIn("支付链接无效，请联系商家", check.detail)
        self.assertIn("state.paymentUrl = null", check.detail)
        self.assertIn("data-refresh-order", check.detail)
        self.assertIn(
            "storefront browser script shows safe order refresh rate-limit message without leaking detail",
            check.detail,
        )
        self.assertIn("provider-secret", check.detail)
        self.assertIn("refresh-secret", check.detail)
        self.assertIn(
            "storefront browser script handles polling refresh failure with warning and stops polling",
            check.detail,
        )
        self.assertIn("polling-refresh-secret", check.detail)
        self.assertIn("message warning", check.detail)
        self.assertIn("assert.equal(intervals[0].active, false)", check.detail)
        self.assertIn("snapshotBeforePolling", check.detail)
        self.assertIn("failed payment must not start polling", check.detail)

    def test_background_worker_scheduler_requires_external_fulfillment_and_delivery_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            scheduler = root / "app" / "workers" / "scheduler.py"
            scheduler.parent.mkdir(parents=True)
            scheduler.write_text(
                "\n".join(
                    [
                        "process_paid_external_orders_once",
                        "external_fulfillment_interval_seconds",
                        'name="external_fulfillment"',
                        "runner=self._process_paid_external_orders",
                        "async def _process_paid_external_orders",
                        "worker_batch_limit",
                    ]
                ),
                encoding="utf-8",
            )

            check = staging_readiness._check_background_worker_scheduler(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("dispatch_pending_deliveries_once", check.detail)
        self.assertIn("delivery_dispatch_interval_seconds", check.detail)
        self.assertIn("runner=self._dispatch_pending_deliveries", check.detail)

    def test_external_auto_fulfillment_safety_contract_requires_markers_and_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            service = root / "app" / "services" / "external_sources" / "auto_fulfillment.py"
            service.parent.mkdir(parents=True)
            service.write_text(
                "\n".join(
                    [
                        "ExternalAutoFulfillmentError",
                        "status_code",
                        "category",
                        "retryable",
                        "load_credentials",
                        "create_order",
                    ]
                ),
                encoding="utf-8",
            )
            tests = root / "tests" / "test_external_auto_fulfillment_service.py"
            tests.parent.mkdir()
            tests.write_text(
                "test_fulfill_paid_order_requires_active_runtime_connection_before_provider_call\n",
                encoding="utf-8",
            )

            check = staging_readiness._check_external_auto_fulfillment_safety_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("is_provider_auto_fulfillment_available", check.detail)
        self.assertIn("ExternalAutoFulfillmentAttemptResult", check.detail)
        self.assertIn("fulfill_tenant_paid_order", check.detail)
        self.assertIn("provider_capability", check.detail)
        self.assertIn("auto_fulfillment_not_enabled", check.detail)
        self.assertIn("credentials_load_failed", check.detail)
        self.assertIn("app/services/external_sources/registry.py", check.detail)
        self.assertIn("auto_fulfillment_idempotent_available", check.detail)
        self.assertIn("auto_fulfillment_idempotent", check.detail)
        self.assertIn("order_context_available", check.detail)
        self.assertIn("delivery_context_available", check.detail)
        self.assertIn("app/web/tenant_admin.py", check.detail)
        self.assertIn("ImportExternalDeliveryResponse", check.detail)
        self.assertIn("ExternalFulfillmentFailureItem", check.detail)
        self.assertIn("ListExternalFulfillmentFailuresResponse", check.detail)
        self.assertIn("/external-fulfillment/failures", check.detail)
        self.assertIn("ExternalFulfillmentFailureLogService", check.detail)
        self.assertIn("_external_fulfillment_failure_response", check.detail)
        self.assertIn("imported: bool", check.detail)
        self.assertIn("dry_run: bool", check.detail)
        self.assertIn("imported=result.imported", check.detail)
        self.assertIn("dry_run=result.dry_run", check.detail)
        self.assertIn("runtime_auth is None", check.detail)
        self.assertIn("connection_missing", check.detail)
        self.assertIn("target_id=str(order.id)", check.detail)
        self.assertIn("external_product_id", check.detail)
        self.assertIn("connection_id", check.detail)
        self.assertIn("failure_fingerprint", check.detail)
        self.assertIn("_has_same_latest_failure_fingerprint", check.detail)
        self.assertIn("ExternalFulfillmentAttempt", check.detail)
        self.assertIn("EXTERNAL_FULFILLMENT_ATTEMPT_STATUSES", check.detail)
        self.assertIn("attempt_source: str = \"auto\"", check.detail)
        self.assertIn("_add_attempt_record", check.detail)
        self.assertIn("_mark_attempt_record or equivalent status update helper", check.detail)
        self.assertIn("_normalize_attempt_source", check.detail)
        self.assertIn("attempt_source=\"manual\"", check.detail)
        self.assertIn("attempt_source=\"auto\"", check.detail)
        self.assertIn('"started"', check.detail)
        self.assertIn('"running"', check.detail)
        self.assertIn('"succeeded"', check.detail)
        self.assertIn("status=\"already_delivered\"", check.detail)
        self.assertIn("status=\"failed\"", check.detail)
        self.assertIn("status=\"succeeded\"", check.detail)
        self.assertIn("delivery_record_id=existing_delivery.id", check.detail)
        self.assertIn("attempt.failure_reason = _safe_attempt_failure_reason", check.detail)
        self.assertIn("upstream_status_code=_safe_optional_status_code", check.detail)
        self.assertIn("started_at=now", check.detail)
        self.assertIn("finished_at=now", check.detail)
        self.assertIn("auto=False", check.detail)
        self.assertIn('"manual"', check.detail)
        self.assertIn("with_for_update(of=Order)", check.detail)
        self.assertIn("app/db/models/external_sources.py", check.detail)
        self.assertIn("__tablename__ = \"external_fulfillment_attempts\"", check.detail)
        self.assertIn("ck_external_fulfillment_attempts_attempt_source", check.detail)
        self.assertIn("ck_external_fulfillment_attempts_status", check.detail)
        self.assertIn("ck_external_fulfillment_attempts_item_count_nonnegative", check.detail)
        self.assertIn("ck_external_fulfillment_attempts_upstream_status_code", check.detail)
        self.assertIn("ix_external_fulfillment_attempts_tenant_status_created", check.detail)
        self.assertIn("ix_external_fulfillment_attempts_tenant_order_created", check.detail)
        self.assertIn("ix_external_fulfillment_attempts_provider_status", check.detail)
        self.assertIn("alembic/versions/20260606_0021_create_external_fulfillment_attempts.py", check.detail)
        self.assertIn("alembic/versions/20260609_0022", check.detail)
        self.assertIn("20260609_0022", check.detail)
        self.assertIn("down_revision: Optional[str] = \"20260606_0021\"", check.detail)
        self.assertIn("'started'", check.detail)
        self.assertIn("'running'", check.detail)
        self.assertIn("'succeeded'", check.detail)
        self.assertIn("down_revision: Optional[str] = \"20260606_0020\"", check.detail)
        self.assertIn("sa.ForeignKeyConstraint([\"delivery_record_id\"], [\"delivery_records.id\"])", check.detail)
        self.assertIn("app/services/external_sources/failures.py", check.detail)
        self.assertIn("ExternalFulfillmentFailureSummary", check.detail)
        self.assertIn("SENSITIVE_FAILURE_VALUE_MARKERS", check.detail)
        self.assertIn("metadata_json.contains", check.detail)
        self.assertIn("_safe_failure_reason", check.detail)
        self.assertIn("_normalize_optional_out_trade_no", check.detail)
        self.assertIn("_normalize_optional_bool", check.detail)
        self.assertIn("app/services/external_sources/attempts.py", check.detail)
        self.assertIn("ExternalFulfillmentAttemptLogService", check.detail)
        self.assertIn("ExternalFulfillmentAttemptSummary", check.detail)
        self.assertIn("list_attempts", check.detail)
        self.assertIn("ExternalFulfillmentAttempt.tenant_id == tenant_id", check.detail)
        self.assertIn("ExternalFulfillmentAttempt.external_order_id", check.detail)
        self.assertIn("SENSITIVE_ATTEMPT_VALUE_MARKERS", check.detail)
        self.assertIn("_safe_attempt_failure_reason", check.detail)
        self.assertIn("with_for_update(of=Order, skip_locked=True)", check.detail)
        self.assertIn("seen_order_ids", check.detail)
        self.assertIn(
            "test_fulfill_paid_order_requires_provider_auto_fulfillment_opt_in_before_credential_load_or_provider_call",
            check.detail,
        )
        self.assertIn("test_process_paid_external_orders_locks_only_order_rows_on_postgresql", check.detail)
        self.assertIn(
            "test_process_paid_external_orders_audits_provider_without_idempotent_auto_fulfillment_opt_in",
            check.detail,
        )
        self.assertIn(
            "test_process_paid_external_orders_audits_runtime_credentials_load_error_without_details",
            check.detail,
        )
        self.assertIn(
            "test_process_paid_external_orders_audits_missing_runtime_connection_without_provider_call",
            check.detail,
        )
        self.assertIn(
            "test_process_paid_external_orders_audits_fetch_delivery_http_error_with_external_order_id",
            check.detail,
        )
        self.assertIn(
            "test_process_paid_external_orders_audits_import_delivery_failure_without_delivery_content",
            check.detail,
        )
        self.assertIn(
            "test_process_paid_external_orders_redacts_unclassified_value_error_reason",
            check.detail,
        )
        self.assertIn(
            "test_failure_audit_records_external_product_id_and_connection_id_without_credentials",
            check.detail,
        )
        self.assertIn(
            "test_failure_fingerprint_changes_when_product_or_external_mapping_changes",
            check.detail,
        )
        self.assertIn(
            "test_registered_idempotent_provider_replay_uses_same_out_trade_no_and_local_delivery_gate",
            check.detail,
        )
        self.assertIn("test_process_paid_external_orders_reuses_existing_delivery_record_when_replayed", check.detail)
        self.assertIn("tests/test_smoke_e2e_external_fulfillment.py", check.detail)
        self.assertIn("replay_fulfillment", check.detail)
        self.assertIn("已有发货记录不应再次调用 provider", check.detail)
        self.assertIn("tests/test_external_provider_registry.py", check.detail)
        self.assertIn("test_auto_fulfillment_capability_defaults_to_false", check.detail)
        self.assertIn(
            "test_auto_fulfillment_capability_requires_idempotent_out_trade_no_opt_in_and_context_methods",
            check.detail,
        )
        self.assertIn("test_auto_fulfillment_capability_rejects_truthy_non_bool_or_legacy_provider", check.detail)
        self.assertIn("tests/test_tenant_admin_api_keys_contract.py", check.detail)
        self.assertIn(
            "test_external_source_provider_list_response_exposes_auto_fulfillment_capability_without_credentials",
            check.detail,
        )
        self.assertIn("tests/test_tenant_admin_external_order_operations.py", check.detail)
        self.assertIn("RetryExternalFulfillmentResponse", check.detail)
        self.assertIn("/orders/{out_trade_no}/external-fulfillment/retry", check.detail)
        self.assertIn("retry_external_fulfillment", check.detail)
        self.assertIn("_external_fulfillment_retry_response", check.detail)
        self.assertIn("failure_recorded", check.detail)
        self.assertIn("attempt_status", check.detail)
        self.assertIn("ExternalFulfillmentAttemptItem", check.detail)
        self.assertIn("ListExternalFulfillmentAttemptsResponse", check.detail)
        self.assertIn("/external-fulfillment/attempts", check.detail)
        self.assertIn("list_external_fulfillment_attempts", check.detail)
        self.assertIn("_external_fulfillment_attempt_response", check.detail)
        self.assertIn("external_order_id=external_order_id", check.detail)
        self.assertIn("attempt_source=attempt_source", check.detail)
        self.assertIn("status=status", check.detail)
        self.assertIn("外部履约尝试查询参数无效", check.detail)
        self.assertIn(
            "test_list_external_fulfillment_attempts_requires_external_sources_read_scope",
            check.detail,
        )
        self.assertIn(
            "test_list_external_fulfillment_attempts_returns_safe_tenant_scoped_attempts_without_sensitive_payload",
            check.detail,
        )
        self.assertIn(
            "test_list_external_fulfillment_attempts_invalid_filter_returns_generic_error",
            check.detail,
        )
        self.assertIn(
            "test_list_external_fulfillment_failures_requires_external_sources_read_scope",
            check.detail,
        )
        self.assertIn(
            "test_list_external_fulfillment_failures_returns_safe_audit_metadata_without_credentials",
            check.detail,
        )
        self.assertIn(
            "test_import_external_delivery_dry_run_exposes_validation_result_without_sensitive_delivery",
            check.detail,
        )
        self.assertIn(
            "test_import_external_delivery_existing_record_response_exposes_reuse_flags",
            check.detail,
        )
        self.assertIn("test_retry_external_fulfillment_requires_write_scope_before_service", check.detail)
        self.assertIn(
            "test_retry_external_fulfillment_returns_safe_success_summary_without_delivery_content",
            check.detail,
        )
        self.assertIn(
            "test_retry_external_fulfillment_returns_safe_failed_summary_without_upstream_detail",
            check.detail,
        )
        self.assertIn("test_retry_external_fulfillment_returns_404_for_missing_order", check.detail)
        self.assertIn(
            "test_retry_external_fulfillment_error_response_is_generic_without_sensitive_detail",
            check.detail,
        )
        self.assertIn("tests/test_external_delivery_import_service.py", check.detail)
        self.assertIn("tests/test_external_fulfillment_failures.py", check.detail)
        self.assertIn("test_list_failures_returns_safe_whitelisted_summary", check.detail)
        self.assertIn("test_list_failures_filters_safe_metadata_values_and_redacts_sensitive_reason", check.detail)
        self.assertIn("test_list_failures_can_filter_non_retryable_order_failure", check.detail)
        self.assertIn("tests/test_external_fulfillment_attempts.py", check.detail)
        self.assertIn("test_list_attempts_returns_safe_whitelisted_summary", check.detail)
        self.assertIn("test_list_attempts_filters_by_status_source_order_and_retryable", check.detail)
        self.assertIn("test_list_attempts_filters_succeeded_lifecycle_status", check.detail)
        self.assertIn("test_list_attempts_accepts_running_lifecycle_status", check.detail)
        self.assertIn("test_list_attempts_clamps_limit_and_keeps_tenant_filter_in_query", check.detail)
        self.assertIn("test_list_attempts_rejects_invalid_filters_before_query", check.detail)
        self.assertIn("test_list_attempts_redacts_sensitive_failure_reason", check.detail)
        self.assertIn("tests/test_openapi_security_contract.py", check.detail)
        self.assertIn("test_external_fulfillment_failure_schema_exposes_safe_fields_only", check.detail)
        self.assertIn("test_external_fulfillment_attempt_schema_exposes_safe_fields_only", check.detail)
        self.assertIn("ListExternalFulfillmentAttemptsResponse", check.detail)
        self.assertIn("ExternalFulfillmentAttemptItem", check.detail)
        self.assertIn("RetryExternalFulfillmentResponse", check.detail)
        self.assertIn(
            "test_import_delivery_dry_run_reuses_existing_delivery_record_without_writing",
            check.detail,
        )
        self.assertIn(
            "test_import_delivery_existing_record_rejects_mismatched_external_mapping",
            check.detail,
        )
        self.assertIn(
            "test_import_delivery_dry_run_rejects_invalid_content_without_writing",
            check.detail,
        )
        self.assertIn("test_process_paid_external_orders_audits_http_error_classification_without_details", check.detail)
        self.assertIn("test_fulfill_paid_order_transitions_attempt_to_succeeded_without_sensitive_payload", check.detail)
        self.assertIn(
            "test_process_paid_external_orders_records_failed_attempt_even_when_failure_audit_is_deduped",
            check.detail,
        )
        self.assertIn("test_fulfill_tenant_paid_order_imports_single_order_with_safe_attempt_summary", check.detail)
        self.assertIn("test_fulfill_tenant_paid_order_returns_none_for_missing_order", check.detail)
        self.assertIn("test_fulfill_tenant_paid_order_reuses_existing_delivery_without_provider_call", check.detail)
        self.assertIn("test_fulfill_tenant_paid_order_records_safe_manual_failure_summary", check.detail)
        self.assertIn(
            "test_fulfill_tenant_paid_order_repeated_same_failure_does_not_add_duplicate_audit",
            check.detail,
        )

    def test_file_inspection_contract_requires_opaque_archive_shell_scan_and_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            service = root / "app" / "services" / "file_inspection.py"
            service.parent.mkdir(parents=True)
            service.write_text(
                "\n".join(
                    [
                        "_inspect_opaque_archive",
                        "MAX_OPAQUE_ARCHIVE_BYTES",
                    ]
                ),
                encoding="utf-8",
            )
            tests = root / "tests" / "test_file_inspection.py"
            tests.parent.mkdir()
            tests.write_text(
                "test_rar_and_7z_shell_scan_blocks_too_small_magic_only_files\n",
                encoding="utf-8",
            )

            check = staging_readiness._check_file_inspection_contract(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("MIN_OPAQUE_ARCHIVE_BYTES", check.detail)
        self.assertIn("_opaque_archive_outer_name_is_sensitive", check.detail)
        self.assertIn("rar_oversized", check.detail)
        self.assertIn("7z_oversized", check.detail)
        self.assertIn("rar_too_small", check.detail)
        self.assertIn("7z_too_small", check.detail)
        self.assertIn("文件头和大小校验通过", check.detail)
        self.assertIn("test_rar_and_7z_shell_scan_blocks_sensitive_outer_names", check.detail)
        self.assertIn("test_rar_and_7z_oversized_files_are_blocked_without_deep_extracting", check.detail)
        self.assertIn("test_rar_and_7z_medium_risk_message_states_only_header_and_size_check", check.detail)

    def test_health_readiness_requires_worker_manager_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            health = root / "app" / "web" / "health.py"
            health.parent.mkdir(parents=True)
            health.write_text("redis_unavailable\n", encoding="utf-8")

            check = staging_readiness._check_health_worker_readiness(root)

        self.assertEqual(staging_readiness.FAIL, check.status)
        self.assertIn("workers_enabled", check.detail)
        self.assertIn("worker_manager", check.detail)
        self.assertIn("worker_unavailable", check.detail)


if __name__ == "__main__":
    unittest.main()
