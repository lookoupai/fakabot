from __future__ import annotations

import unittest

try:
    from app.services.payments.configs import (
        list_payment_provider_summaries,
        normalize_epusdt_base_url,
        normalize_payment_gateway_url,
        normalize_payment_provider,
        PaymentConfigService,
        TENANT_DIRECT_PAYMENT_PROVIDER_PRIORITY,
        USDT_TRC20_DIRECT_PROVIDER,
    )
    from app.services.payments.epay_compatible import EPAY_COMPATIBLE_PROVIDER, LEMZF_PROVIDER
    from app.services.payments.token188 import TOKEN188_PROVIDER
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过支付配置服务测试：{exc.name}") from exc


class PaymentConfigServiceContractTest(unittest.TestCase):
    def test_normalize_epusdt_base_url_keeps_safe_gateway_without_trailing_slash(self) -> None:
        self.assertEqual(
            "https://pay.example/path",
            normalize_epusdt_base_url(" HTTPS://PAY.EXAMPLE/path/ "),
        )

    def test_normalize_epusdt_base_url_rejects_embedded_credentials_and_query(self) -> None:
        invalid_urls = [
            "ftp://pay.example",
            "https://user:pass@pay.example",
            "https://pay.example?token=plain",
            "https://pay.example#fragment",
            "https://pay.example/\ncallback",
            "",
        ]

        for url in invalid_urls:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    normalize_epusdt_base_url(url)

    def test_normalize_payment_provider_accepts_epusdt_alias_and_supported_providers(self) -> None:
        self.assertEqual("epusdt_gmpay", normalize_payment_provider("epusdt"))
        self.assertEqual(TOKEN188_PROVIDER, normalize_payment_provider(TOKEN188_PROVIDER))
        self.assertEqual(EPAY_COMPATIBLE_PROVIDER, normalize_payment_provider(EPAY_COMPATIBLE_PROVIDER))
        self.assertEqual(LEMZF_PROVIDER, normalize_payment_provider(LEMZF_PROVIDER))
        self.assertEqual(USDT_TRC20_DIRECT_PROVIDER, normalize_payment_provider(USDT_TRC20_DIRECT_PROVIDER))
        with self.assertRaises(ValueError):
            normalize_payment_provider("unknown")

    def test_normalize_payment_gateway_url_rejects_userinfo_query_fragment(self) -> None:
        for provider in (TOKEN188_PROVIDER, EPAY_COMPATIBLE_PROVIDER, LEMZF_PROVIDER):
            with self.subTest(provider=provider):
                self.assertEqual(
                    "https://pay.example/submit.php",
                    normalize_payment_gateway_url(provider, " HTTPS://PAY.EXAMPLE/submit.php/ "),
                )
                for url in (
                    "https://user:pass@pay.example/submit.php",
                    "https://pay.example/submit.php?key=plain-secret",
                    "https://pay.example/submit.php#fragment",
                    "https://pay.example/\nsubmit.php",
                ):
                    with self.subTest(url=url):
                        with self.assertRaises(ValueError):
                            normalize_payment_gateway_url(provider, url)

    def test_list_payment_provider_summaries_exposes_safe_static_capabilities(self) -> None:
        summaries = {summary.provider_name: summary for summary in list_payment_provider_summaries()}

        self.assertEqual(
            {"epusdt_gmpay", TOKEN188_PROVIDER, EPAY_COMPATIBLE_PROVIDER, LEMZF_PROVIDER, USDT_TRC20_DIRECT_PROVIDER},
            set(summaries),
        )
        self.assertTrue(summaries["epusdt_gmpay"].query_order_available)
        self.assertTrue(summaries["epusdt_gmpay"].reconcile_available)
        self.assertFalse(summaries["epusdt_gmpay"].offline_only)
        for provider in (TOKEN188_PROVIDER, EPAY_COMPATIBLE_PROVIDER, LEMZF_PROVIDER):
            with self.subTest(provider=provider):
                summary = summaries[provider]
                self.assertEqual("offline_payment_page", summary.integration_kind)
                self.assertFalse(summary.production_ready)
                self.assertFalse(summary.staging_verified)
                self.assertTrue(summary.offline_only)
                self.assertFalse(summary.query_order_available)
                self.assertFalse(summary.reconcile_available)
                self.assertTrue(summary.create_payment_available)
                self.assertTrue(summary.callback_available)
                self.assertNotIn("secret", repr(summary).lower())
                self.assertNotIn("gateway_url", repr(summary))
        direct = summaries[USDT_TRC20_DIRECT_PROVIDER]
        self.assertEqual("offline_direct_chain_config", direct.integration_kind)
        self.assertEqual("usdt_trc20_direct_offline_config_v1", direct.contract_name)
        self.assertTrue(direct.offline_only)
        self.assertTrue(direct.create_payment_available)
        self.assertFalse(direct.callback_available)
        self.assertFalse(direct.query_order_available)
        self.assertFalse(direct.reconcile_available)
        self.assertEqual(("USDT",), direct.supported_assets)
        self.assertEqual(("TRC20",), direct.supported_networks)
        self.assertNotIn(USDT_TRC20_DIRECT_PROVIDER, TENANT_DIRECT_PAYMENT_PROVIDER_PRIORITY)

    def test_payment_provider_summaries_do_not_claim_real_staging_or_unsupported_capabilities(self) -> None:
        summaries = {summary.provider_name: summary for summary in list_payment_provider_summaries()}

        for summary in summaries.values():
            with self.subTest(provider=summary.provider_name):
                self.assertFalse(summary.production_ready)
                self.assertFalse(summary.staging_verified)
        for provider in (TOKEN188_PROVIDER, EPAY_COMPATIBLE_PROVIDER, LEMZF_PROVIDER):
            with self.subTest(provider=provider):
                summary = summaries[provider]
                self.assertTrue(summary.offline_only)
                self.assertTrue(summary.create_payment_available)
                self.assertTrue(summary.callback_available)
                self.assertFalse(summary.query_order_available)
                self.assertFalse(summary.reconcile_available)
        direct = summaries[USDT_TRC20_DIRECT_PROVIDER]
        self.assertTrue(direct.offline_only)
        self.assertTrue(direct.create_payment_available)
        self.assertFalse(direct.callback_available)
        self.assertFalse(direct.query_order_available)
        self.assertFalse(direct.reconcile_available)
        self.assertNotIn(USDT_TRC20_DIRECT_PROVIDER, TENANT_DIRECT_PAYMENT_PROVIDER_PRIORITY)

    def test_trc20_direct_config_normalization_is_offline_only_and_rejects_unsafe_values(self) -> None:
        service = PaymentConfigService()

        safe_tron_address = "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb"
        payload = service._normalize_config_payload(
            settings=object(),
            provider=USDT_TRC20_DIRECT_PROVIDER,
            payload={
                "monitor_address": f" {safe_tron_address} ",
                "token": " usdt ",
                "network": " trc20 ",
                "cny_per_usdt": " 7.25 ",
                "min_usdt_amount": " 2.50 ",
                "timeout_seconds": 7200,
            },
        )

        self.assertEqual(
            {
                "monitor_address": safe_tron_address,
                "token": "USDT",
                "network": "TRC20",
                "cny_per_usdt": "7.25",
                "min_usdt_amount": "2.50",
                "timeout_seconds": 7200,
            },
            payload,
        )
        status = service._status_from_payload(USDT_TRC20_DIRECT_PROVIDER, "tenant", True, payload)
        self.assertEqual(USDT_TRC20_DIRECT_PROVIDER, status.provider)
        self.assertTrue(status.enabled)
        self.assertEqual("USDT", status.asset)
        self.assertEqual("TRC20", status.network)
        self.assertEqual(safe_tron_address, status.monitor_address)
        self.assertEqual("7.25", status.cny_per_usdt)
        self.assertEqual("2.50", status.min_usdt_amount)
        self.assertEqual(7200, status.timeout_seconds)
        self.assertFalse(status.key_configured)

        invalid_checksum_address = "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwc"
        for invalid_payload in (
            {"monitor_address": "https://pay.example?token=plain-secret", "token": "USDT", "network": "TRC20"},
            {"monitor_address": invalid_checksum_address, "token": "USDT", "network": "TRC20"},
            {"monitor_address": safe_tron_address, "token": "BTC", "network": "TRC20"},
            {"monitor_address": safe_tron_address, "token": "USDT", "network": "TRX"},
            {"monitor_address": safe_tron_address, "token": "USDT", "network": "TRC20", "timeout_seconds": 30},
            {"monitor_address": safe_tron_address, "token": "USDT", "network": "TRC20", "cny_per_usdt": "0"},
            {"monitor_address": safe_tron_address, "token": "USDT", "network": "TRC20", "gateway_url": "https://pay.example"},
            {"monitor_address": safe_tron_address, "token": "USDT", "network": "TRC20", "tron_api_key": "plain-secret"},
        ):
            with self.subTest(payload=invalid_payload):
                with self.assertRaises(ValueError):
                    service._normalize_config_payload(object(), USDT_TRC20_DIRECT_PROVIDER, invalid_payload)

        with self.assertRaisesRegex(ValueError, "TRC20 直付不使用 gateway URL"):
            normalize_payment_gateway_url(USDT_TRC20_DIRECT_PROVIDER, "https://pay.example")


if __name__ == "__main__":
    unittest.main()
