from __future__ import annotations

import asyncio
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit
import unittest

try:
    from app.services.payments.base import PaymentOrderRequest
    from app.services.payments.epay_compatible import (
        EPAY_COMPATIBLE_PROVIDER,
        EPAY_OFFLINE_QUERY_CONTRACT,
        LEMZF_PROVIDER,
        EpayCompatibleConfig,
        EpayCompatibleProvider,
        LemzfProvider,
        build_epay_offline_query_contract_request,
        build_epay_page_payment_params,
        build_epay_page_payment_url,
        normalize_epay_offline_query_response,
        normalize_epay_query_payload,
        normalize_epay_gateway_url,
        sign_epay_payload,
        verify_epay_callback,
    )
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过易支付兼容测试：{exc.name}") from exc


class EpayCompatiblePaymentContractTest(unittest.TestCase):
    def test_epay_helpers_are_exported_from_payments_package(self) -> None:
        from app.services.payments import (
            EpayCompatibleProvider as exported_provider,
            sign_epay_payload as exported_sign,
            verify_epay_callback as exported_verify,
        )

        self.assertIs(EpayCompatibleProvider, exported_provider)
        self.assertIs(sign_epay_payload, exported_sign)
        self.assertIs(verify_epay_callback, exported_verify)

    def test_sign_epay_payload_matches_legacy_lemzf_algorithm(self) -> None:
        payload = {
            "pid": "1001",
            "type": "alipay",
            "out_trade_no": "ORD123",
            "notify_url": "https://store.example/callback",
            "name": "测试订单",
            "money": "10.50",
            "device": "mobile",
            "empty": "",
            "zero": 0,
            "sign": "wrong",
            "sign_type": "MD5",
        }

        signature = sign_epay_payload(payload, "secret")

        self.assertEqual("156593a6216e7a77aa9bd09295a7a26a", signature)
        self.assertEqual(signature, sign_epay_payload({**payload, "sign": signature}, "secret"))

    def test_build_page_payment_params_and_url_without_network(self) -> None:
        config = _config()
        request = PaymentOrderRequest(
            out_trade_no="ORD123",
            amount=Decimal("10.509"),
            currency="CNY",
            notify_url="https://store.example/payments/callback/epay_compatible",
        )

        params = build_epay_page_payment_params(config, request)
        url = build_epay_page_payment_url(config.gateway_url, params)
        query = parse_qs(urlsplit(url).query)

        self.assertEqual("https://pay.example/submit.php", normalize_epay_gateway_url(config.gateway_url))
        self.assertEqual("1001", params["pid"])
        self.assertEqual("alipay", params["type"])
        self.assertEqual("ORD123", params["out_trade_no"])
        self.assertEqual("测试商品", params["name"])
        self.assertEqual("10.50", params["money"])
        self.assertEqual("mobile", params["device"])
        self.assertEqual("https://store.example/return", params["return_url"])
        self.assertEqual(params["sign"], sign_epay_payload(params, config.key))
        self.assertEqual("MD5", params["sign_type"])
        self.assertEqual(["ORD123"], query["out_trade_no"])
        self.assertEqual([params["sign"]], query["sign"])

    def test_build_page_payment_params_rejects_amount_truncated_to_zero(self) -> None:
        request = PaymentOrderRequest(
            out_trade_no="ORD123",
            amount=Decimal("0.001"),
            currency="CNY",
            notify_url="https://store.example/payments/callback/epay_compatible",
        )

        with self.assertRaisesRegex(ValueError, "不能小于 0.01"):
            build_epay_page_payment_params(_config(), request)

    def test_provider_create_order_returns_safe_result(self) -> None:
        config = _config(key="plain-secret")
        provider = EpayCompatibleProvider(config)
        request = PaymentOrderRequest(
            out_trade_no="ORD123",
            amount=Decimal("9.90"),
            currency="CNY",
            notify_url="https://store.example/payments/callback/epay_compatible",
        )

        result = asyncio.run(provider.create_order(request))

        self.assertEqual(EPAY_COMPATIBLE_PROVIDER, result.provider)
        self.assertEqual("ORD123", result.out_trade_no)
        self.assertIsNone(result.provider_trade_no)
        self.assertIsNotNone(result.payment_url)
        self.assertIn("sign=", result.payment_url or "")
        self.assertNotIn("plain-secret", result.payment_url or "")
        self.assertNotIn("plain-secret", repr(result.raw_response))
        self.assertEqual("1001", result.raw_response["merchant_id"])

    def test_verify_callback_accepts_signed_success_payload(self) -> None:
        config = _config(key="plain-secret")
        payload = {
            "pid": "1001",
            "trade_no": "UP-1",
            "out_trade_no": "ORD123",
            "money": "9.90",
            "trade_status": "TRADE_SUCCESS",
        }
        payload["sign"] = sign_epay_payload(payload, config.key)
        payload["sign_type"] = "MD5"

        result = verify_epay_callback(payload, config)

        self.assertEqual(EPAY_COMPATIBLE_PROVIDER, result.provider)
        self.assertEqual("ORD123", result.out_trade_no)
        self.assertEqual("UP-1", result.provider_trade_no)
        self.assertTrue(result.paid)
        self.assertEqual(payload, result.raw_payload)
        self.assertEqual(64, len(result.payload_hash))
        self.assertNotIn("plain-secret", repr(result))

    def test_verify_callback_redacts_nested_sensitive_payload_fields(self) -> None:
        config = _config(key="plain-secret")
        payload = {
            "pid": "1001",
            "trade_no": "UP-1",
            "out_trade_no": "ORD123",
            "money": "9.90",
            "trade_status": "TRADE_SUCCESS",
            "api_key": "upstream-api-key",
            "headers": {
                "Authorization": "Bearer upstream-token",
                "X-Request-ID": "req-1",
            },
            "items": [
                {"cookie": "session=secret-cookie", "serial": "CARD-1"},
                {"plain_key": "raw-card-secret", "serial": "CARD-2"},
            ],
        }
        payload["sign"] = sign_epay_payload(payload, config.key)

        result = verify_epay_callback(payload, config)

        self.assertEqual("ORD123", result.raw_payload["out_trade_no"])
        self.assertEqual("UP-1", result.raw_payload["trade_no"])
        self.assertEqual("***", result.raw_payload["api_key"])
        self.assertEqual("***", result.raw_payload["headers"]["Authorization"])
        self.assertEqual("req-1", result.raw_payload["headers"]["X-Request-ID"])
        self.assertEqual("***", result.raw_payload["items"][0]["cookie"])
        self.assertEqual("CARD-1", result.raw_payload["items"][0]["serial"])
        self.assertEqual("***", result.raw_payload["items"][1]["plain_key"])
        self.assertEqual(64, len(result.payload_hash))
        self.assertNotIn("upstream-api-key", repr(result.raw_payload))
        self.assertNotIn("upstream-token", repr(result.raw_payload))
        self.assertNotIn("secret-cookie", repr(result.raw_payload))

    def test_verify_callback_valid_signature_non_success_status_is_unpaid(self) -> None:
        config = _config()
        payload = {
            "pid": "1001",
            "trade_no": "UP-3",
            "out_trade_no": "ORD123",
            "money": "9.90",
            "trade_status": "WAIT_BUYER_PAY",
        }
        payload["sign"] = sign_epay_payload(payload, config.key)

        result = verify_epay_callback(payload, config)

        self.assertFalse(result.paid)
        self.assertEqual("ORD123", result.out_trade_no)

    def test_verify_callback_rejects_invalid_signature_merchant_or_missing_order(self) -> None:
        config = _config()
        payload = {
            "pid": "1001",
            "trade_no": "UP-1",
            "out_trade_no": "ORD123",
            "money": "9.90",
            "trade_status": "TRADE_SUCCESS",
        }
        payload["sign"] = sign_epay_payload(payload, config.key)

        wrong_merchant = {**payload, "pid": "other"}
        wrong_merchant["sign"] = sign_epay_payload(wrong_merchant, config.key)
        missing_order = {**payload, "out_trade_no": ""}
        missing_order["sign"] = sign_epay_payload(missing_order, config.key)
        invalid_cases = [
            ({**payload, "sign": "bad"}, "签名无效"),
            (wrong_merchant, "商户不匹配"),
            (missing_order, "缺少订单号"),
        ]

        for invalid_payload, message in invalid_cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    verify_epay_callback(invalid_payload, config)

    def test_lemzf_provider_uses_lemzf_provider_name_without_network(self) -> None:
        provider = LemzfProvider(_config())
        request = PaymentOrderRequest(
            out_trade_no="ORD123",
            amount=Decimal("8.88"),
            currency="CNY",
            notify_url="https://store.example/payments/callback/lemzf",
        )

        result = asyncio.run(provider.create_order(request))

        self.assertEqual(LEMZF_PROVIDER, result.provider)
        verified_payload = {
            "pid": "1001",
            "trade_no": "UP-2",
            "out_trade_no": "ORD123",
            "money": "8.88",
            "trade_status": "TRADE_SUCCESS",
        }
        verified_payload["sign"] = sign_epay_payload(verified_payload, "secret")
        verified = provider.verify_callback(verified_payload)
        self.assertEqual(LEMZF_PROVIDER, verified.provider)
        self.assertTrue(verified.paid)

    def test_rejects_unsafe_gateway_and_unsupported_provider_name(self) -> None:
        invalid_urls = [
            "ftp://pay.example/submit.php",
            "https://user:pass@pay.example/submit.php",
            "https://pay.example/submit.php#fragment",
            "https://pay.example/\nsubmit.php",
            "",
        ]
        for url in invalid_urls:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    normalize_epay_gateway_url(url)

        with self.assertRaisesRegex(ValueError, "provider_name 不支持"):
            EpayCompatibleProvider(
                EpayCompatibleConfig(
                    merchant_id="1001",
                    key="secret",
                    provider_name="other",
                )
            )
        with self.assertRaisesRegex(ValueError, "gateway URL 不能包含 query"):
            build_epay_page_payment_url("https://pay.example/submit.php?token=plain", {"out_trade_no": "ORD123"})

    def test_query_order_is_not_claimed_as_supported_before_real_integration(self) -> None:
        provider = EpayCompatibleProvider(_config())

        with self.assertRaisesRegex(NotImplementedError, "暂未提供"):
            asyncio.run(provider.query_order("UP-1"))

    def test_normalize_signed_query_payload_maps_statuses_without_network(self) -> None:
        config = _config(key="plain-secret")
        request_payload = build_epay_offline_query_contract_request(
            config,
            out_trade_no="ORD123",
            provider_trade_no="UP-1",
        )
        cases = [
            ("TRADE_SUCCESS", True, False),
            ("WAIT_BUYER_PAY", False, False),
            ("TRADE_CLOSED", False, True),
            ("failed", False, False),
        ]

        for status, paid, expired in cases:
            with self.subTest(status=status):
                payload = _signed_query_payload(config, trade_status=status)

                self.assertEqual(EPAY_OFFLINE_QUERY_CONTRACT, request_payload["contract"])
                self.assertEqual("ORD123", request_payload["out_trade_no"])
                self.assertEqual("UP-1", request_payload["trade_no"])
                self.assertNotIn("plain-secret", repr(request_payload))
                result = normalize_epay_offline_query_response(
                    payload,
                    config,
                    expected_out_trade_no="ORD123",
                    expected_amount=Decimal("9.90"),
                )

                self.assertEqual(EPAY_COMPATIBLE_PROVIDER, result.provider)
                self.assertEqual("UP-1", result.provider_trade_no)
                self.assertEqual(paid, result.paid)
                self.assertEqual(expired, result.expired)
                self.assertEqual(status.lower(), result.status)
                self.assertEqual("***", result.raw_response["api_key"])
                self.assertNotIn("plain-secret", repr(result.raw_response))
                self.assertNotIn("upstream-api-key", repr(result.raw_response))

    def test_normalize_signed_query_payload_rejects_mismatched_or_unsafe_values(self) -> None:
        config = _config()
        valid_payload = _signed_query_payload(config)
        invalid_cases = [
            ({**valid_payload, "sign": "bad"}, "签名无效"),
            (_signed_query_payload(config, pid="other"), "商户不匹配"),
            (_signed_query_payload(config, out_trade_no="OTHER"), "订单号不匹配"),
            (_signed_query_payload(config, money="8.88"), "金额不匹配"),
            (_signed_query_payload(config, trade_status="mystery"), "状态不支持"),
        ]

        for payload, message in invalid_cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    normalize_epay_query_payload(
                        payload,
                        config,
                        expected_out_trade_no="ORD123",
                        expected_amount=Decimal("9.90"),
                    )

    def test_normalize_signed_query_payload_preserves_lemzf_provider_name(self) -> None:
        config = EpayCompatibleConfig(
            merchant_id="1001",
            key="secret",
            gateway_url="https://pay.example/submit.php",
            provider_name=LEMZF_PROVIDER,
        )
        payload = _signed_query_payload(config, trade_no="LEMZF-UP-1")

        result = normalize_epay_query_payload(payload, config, expected_out_trade_no="ORD123")

        self.assertEqual(LEMZF_PROVIDER, result.provider)
        self.assertEqual("LEMZF-UP-1", result.provider_trade_no)


def _config(key: str = "secret") -> EpayCompatibleConfig:
    return EpayCompatibleConfig(
        merchant_id="1001",
        key=key,
        gateway_url=" HTTPS://pay.example/submit.php ",
        payment_type="alipay",
        device="mobile",
        return_url="https://store.example/return",
        provider_name=EPAY_COMPATIBLE_PROVIDER,
        subject="测试商品",
    )


def _signed_query_payload(
    config: EpayCompatibleConfig,
    *,
    trade_status: str = "TRADE_SUCCESS",
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "contract": EPAY_OFFLINE_QUERY_CONTRACT,
        "pid": config.merchant_id,
        "trade_no": "UP-1",
        "out_trade_no": "ORD123",
        "money": "9.90",
        "trade_status": trade_status,
        "api_key": "upstream-api-key",
    }
    payload.update(overrides)
    payload["sign"] = sign_epay_payload(payload, config.key)
    payload["sign_type"] = "MD5"
    return payload


if __name__ == "__main__":
    unittest.main()
