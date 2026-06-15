from __future__ import annotations

import asyncio
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit
import unittest

try:
    from app.services.payments.base import PaymentOrderRequest
    from app.services.payments.token188 import (
        TOKEN188_PROVIDER,
        TOKEN188_OFFLINE_QUERY_CONTRACT,
        Token188Config,
        Token188Provider,
        build_token188_offline_query_contract_request,
        build_token188_payment_params,
        build_token188_payment_url,
        normalize_token188_offline_query_response,
        normalize_token188_query_payload,
        normalize_token188_gateway_url,
        sign_token188_callback_payload,
        sign_token188_gateway_payload,
        sign_token188_payload,
        verify_token188_callback,
    )
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过 TOKEN188 支付测试：{exc.name}") from exc


class Token188PaymentContractTest(unittest.TestCase):
    def test_sign_token188_payloads_match_legacy_gateway_and_callback_algorithms(self) -> None:
        payload = {
            "amount": "10.50",
            "merchantId": "MERCHANT1",
            "to": "TADDR",
            "transactionId": "TX123",
            "empty": "",
            "sign": "WRONG",
        }

        gateway_signature = sign_token188_gateway_payload(payload, "secret")
        callback_signature = sign_token188_callback_payload(payload, "secret")

        self.assertEqual("674218457CD29E49F8966806B17B592D", gateway_signature)
        self.assertEqual("4CF8D1051AD3006FDF2E574022088658", callback_signature)
        self.assertNotEqual(gateway_signature, callback_signature)
        self.assertEqual(callback_signature, sign_token188_payload({**payload, "sign": callback_signature}, "secret"))

    def test_build_payment_params_and_url_without_network(self) -> None:
        config = _config()
        request = PaymentOrderRequest(
            out_trade_no="ORD123",
            amount=Decimal("10.509"),
            currency="USDT",
            notify_url="https://store.example/payments/callback/token188",
        )

        params = build_token188_payment_params(config, request)
        url = build_token188_payment_url(config.gateway_url, params)
        query = parse_qs(urlsplit(url).query)

        self.assertEqual("https://payweb.188pay.net/", normalize_token188_gateway_url(config.gateway_url))
        self.assertEqual("MERCHANT1", params["merchantId"])
        self.assertEqual("10.50", params["amount"])
        self.assertEqual("TRX", params["chainType"])
        self.assertEqual("TADDR", params["to"])
        self.assertEqual("ORD123", params["orderNo"])
        self.assertEqual("https://store.example/", params["returnUrl"])
        self.assertEqual(params["sign"], sign_token188_gateway_payload(params, config.key))
        self.assertEqual(["ORD123"], query["orderNo"])
        self.assertEqual([params["sign"]], query["sign"])

    def test_build_payment_params_rejects_amount_truncated_to_zero(self) -> None:
        request = PaymentOrderRequest(
            out_trade_no="ORD123",
            amount=Decimal("0.001"),
            currency="USDT",
            notify_url="https://store.example/payments/callback/token188",
        )

        with self.assertRaisesRegex(ValueError, "不能小于 0.01"):
            build_token188_payment_params(_config(), request)

    def test_provider_create_order_returns_safe_payment_result(self) -> None:
        config = _config(key="plain-secret")
        provider = Token188Provider(config)
        request = PaymentOrderRequest(
            out_trade_no="ORD123",
            amount=Decimal("9.90"),
            currency="USDT",
            notify_url="https://store.example/payments/callback/token188",
        )

        result = asyncio.run(provider.create_order(request))

        self.assertEqual(TOKEN188_PROVIDER, result.provider)
        self.assertEqual("ORD123", result.out_trade_no)
        self.assertIsNone(result.provider_trade_no)
        self.assertIsNotNone(result.payment_url)
        self.assertIn("sign=", result.payment_url or "")
        self.assertNotIn("plain-secret", result.payment_url or "")
        self.assertNotIn("plain-secret", repr(result.raw_response))
        self.assertEqual("MERCHANT1", result.raw_response["merchant_id"])

    def test_verify_callback_accepts_signed_payload_and_does_not_include_secret(self) -> None:
        config = _config(key="plain-secret")
        payload = {
            "amount": "9.90",
            "merchantId": "MERCHANT1",
            "to": "TADDR",
            "transactionId": "TX123",
            "from": "TFROM",
            "orderNo": "ORD123",
        }
        payload["sign"] = sign_token188_callback_payload(payload, config.key)

        result = verify_token188_callback(payload, config)

        self.assertEqual(TOKEN188_PROVIDER, result.provider)
        self.assertEqual("ORD123", result.out_trade_no)
        self.assertEqual("TX123", result.provider_trade_no)
        self.assertTrue(result.paid)
        self.assertEqual(payload, result.raw_payload)
        self.assertEqual(64, len(result.payload_hash))
        self.assertNotIn("plain-secret", repr(result))

    def test_verify_callback_accepts_legacy_order_number_aliases(self) -> None:
        config = _config()
        for field_name in ("orderNo", "out_trade_no", "order_id"):
            with self.subTest(field_name=field_name):
                payload = {
                    "amount": "9.90",
                    "merchantId": "MERCHANT1",
                    "to": "TADDR",
                    "transactionId": "TX123",
                    field_name: "ORD123",
                }
                payload["sign"] = sign_token188_callback_payload(payload, config.key)

                result = verify_token188_callback(payload, config)

                self.assertEqual("ORD123", result.out_trade_no)

    def test_verify_callback_redacts_nested_sensitive_payload_fields(self) -> None:
        config = _config(key="plain-secret")
        payload = {
            "amount": "9.90",
            "merchantId": "MERCHANT1",
            "to": "TADDR",
            "transactionId": "TX123",
            "from": "TFROM",
            "orderNo": "ORD123",
            "secret_key": "upstream-secret",
            "headers": {
                "Authorization": "Bearer upstream-token",
                "Trace-ID": "trace-1",
            },
            "events": [
                {"cookie": "session=secret-cookie", "status": "paid"},
                {"credential": "raw-credential", "status": "confirmed"},
            ],
        }
        payload["sign"] = sign_token188_callback_payload(payload, config.key)

        result = verify_token188_callback(payload, config)

        self.assertEqual("ORD123", result.raw_payload["orderNo"])
        self.assertEqual("TX123", result.raw_payload["transactionId"])
        self.assertEqual("***", result.raw_payload["secret_key"])
        self.assertEqual("***", result.raw_payload["headers"]["Authorization"])
        self.assertEqual("trace-1", result.raw_payload["headers"]["Trace-ID"])
        self.assertEqual("***", result.raw_payload["events"][0]["cookie"])
        self.assertEqual("paid", result.raw_payload["events"][0]["status"])
        self.assertEqual("***", result.raw_payload["events"][1]["credential"])
        self.assertEqual(64, len(result.payload_hash))
        self.assertNotIn("upstream-secret", repr(result.raw_payload))
        self.assertNotIn("upstream-token", repr(result.raw_payload))
        self.assertNotIn("secret-cookie", repr(result.raw_payload))

    def test_verify_callback_rejects_invalid_merchant_address_or_signature(self) -> None:
        config = _config()
        payload = {
            "amount": "9.90",
            "merchantId": "MERCHANT1",
            "to": "TADDR",
            "transactionId": "TX123",
            "orderNo": "ORD123",
        }
        payload["sign"] = sign_token188_callback_payload(payload, config.key)

        invalid_cases = [
            ({**payload, "merchantId": "OTHER"}, "商户不匹配"),
            ({**payload, "to": "OTHER"}, "收款地址不匹配"),
            ({**payload, "sign": "BAD"}, "签名无效"),
        ]

        for invalid_payload, message in invalid_cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    verify_token188_callback(invalid_payload, config)

    def test_rejects_unsafe_gateway_and_missing_config_without_leaking_values(self) -> None:
        invalid_urls = [
            "ftp://pay.example",
            "https://user:pass@pay.example",
            "https://pay.example/#fragment",
            "https://pay.example/\npath",
            "",
        ]
        for url in invalid_urls:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    normalize_token188_gateway_url(url)

        with self.assertRaisesRegex(ValueError, "merchant_id"):
            Token188Provider(Token188Config(merchant_id="", key="secret", monitor_address="TADDR"))
        with self.assertRaisesRegex(ValueError, "gateway URL 不能包含 query"):
            build_token188_payment_url("https://pay.example/?token=plain", {"orderNo": "ORD123"})

    def test_callback_requires_order_number_instead_of_amount_guessing(self) -> None:
        config = _config()
        payload = {
            "amount": "9.90",
            "merchantId": "MERCHANT1",
            "to": "TADDR",
            "transactionId": "TX123",
        }
        payload["sign"] = sign_token188_callback_payload(payload, config.key)

        with self.assertRaisesRegex(ValueError, "缺少订单号"):
            verify_token188_callback(payload, config)

    def test_query_order_is_not_claimed_as_supported_before_real_integration(self) -> None:
        provider = Token188Provider(_config())

        with self.assertRaisesRegex(NotImplementedError, "暂未提供"):
            asyncio.run(provider.query_order("TX123"))

    def test_normalize_signed_query_payload_maps_statuses_without_network(self) -> None:
        config = _config(key="plain-secret")
        request_payload = build_token188_offline_query_contract_request(
            config,
            out_trade_no="ORD123",
            provider_trade_no="TX123",
        )
        cases = [
            ("paid", True, False),
            ("WAITING", False, False),
            ("expired", False, True),
            ("failed", False, False),
        ]

        for status, paid, expired in cases:
            with self.subTest(status=status):
                payload = _signed_query_payload(config, status=status)

                self.assertEqual(TOKEN188_OFFLINE_QUERY_CONTRACT, request_payload["contract"])
                self.assertEqual("ORD123", request_payload["orderNo"])
                self.assertEqual("TX123", request_payload["transactionId"])
                self.assertNotIn("plain-secret", repr(request_payload))
                result = normalize_token188_offline_query_response(
                    payload,
                    config,
                    expected_out_trade_no="ORD123",
                    expected_amount=Decimal("9.90"),
                )

                self.assertEqual(TOKEN188_PROVIDER, result.provider)
                self.assertEqual("TX123", result.provider_trade_no)
                self.assertEqual(paid, result.paid)
                self.assertEqual(expired, result.expired)
                self.assertEqual(status.lower(), result.status)
                self.assertEqual("***", result.raw_response["secret_key"])
                self.assertNotIn("plain-secret", repr(result.raw_response))
                self.assertNotIn("upstream-secret", repr(result.raw_response))

    def test_normalize_signed_query_payload_rejects_mismatched_or_unsafe_values(self) -> None:
        config = _config()
        valid_payload = _signed_query_payload(config)
        invalid_cases = [
            ({**valid_payload, "sign": "bad"}, "签名无效"),
            (_signed_query_payload(config, merchantId="OTHER"), "商户不匹配"),
            (_signed_query_payload(config, to="OTHER"), "收款地址不匹配"),
            (_signed_query_payload(config, orderNo="OTHER"), "订单号不匹配"),
            (_signed_query_payload(config, amount="8.88"), "金额不匹配"),
            (_signed_query_payload(config, status="mystery"), "状态不支持"),
        ]

        for payload, message in invalid_cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    normalize_token188_query_payload(
                        payload,
                        config,
                        expected_out_trade_no="ORD123",
                        expected_amount=Decimal("9.90"),
                    )


def _config(key: str = "secret") -> Token188Config:
    return Token188Config(
        merchant_id="MERCHANT1",
        key=key,
        monitor_address="TADDR",
        gateway_url=" HTTPS://payweb.188pay.net ",
    )


def _signed_query_payload(
    config: Token188Config,
    *,
    status: str = "paid",
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "contract": TOKEN188_OFFLINE_QUERY_CONTRACT,
        "merchantId": config.merchant_id,
        "to": config.monitor_address,
        "orderNo": "ORD123",
        "transactionId": "TX123",
        "amount": "9.90",
        "status": status,
        "secret_key": "upstream-secret",
    }
    payload.update(overrides)
    payload["sign"] = sign_token188_callback_payload(payload, config.key)
    return payload


if __name__ == "__main__":
    unittest.main()
