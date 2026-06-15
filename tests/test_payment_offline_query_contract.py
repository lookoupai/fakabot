from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping
import unittest

try:
    from app.services.payments.epay_compatible import (
        EPAY_OFFLINE_QUERY_CONTRACT,
        LEMZF_PROVIDER,
        EpayCompatibleConfig,
        build_epay_offline_query_contract_request,
        normalize_epay_offline_query_response,
        sign_epay_payload,
    )
    from app.services.payments.token188 import (
        TOKEN188_OFFLINE_QUERY_CONTRACT,
        TOKEN188_PROVIDER,
        Token188Config,
        build_token188_offline_query_contract_request,
        normalize_token188_offline_query_response,
        sign_token188_callback_payload,
    )
    from app.services.payments.offline_query import OfflinePaymentQueryDryRunService
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过支付离线查单合同测试：{exc.name}") from exc


@dataclass
class FakeOfflineQueryTransport:
    response: dict[str, object]
    seen_request: dict[str, object] | None = None

    def send(self, request: Mapping[str, object]) -> dict[str, object]:
        self.seen_request = dict(request)
        return dict(self.response)


class PaymentOfflineQueryContractTest(unittest.TestCase):
    def test_token188_offline_query_normalizer_accepts_signed_paid_fixture_without_network(self) -> None:
        config = _token188_config(key="plain-secret")
        transport = FakeOfflineQueryTransport(_signed_token188_response(config, status="paid"))
        request = build_token188_offline_query_contract_request(
            config,
            out_trade_no="ORD123",
            provider_trade_no="TX123",
        )

        response = transport.send(request)
        result = normalize_token188_offline_query_response(
            response,
            config,
            expected_out_trade_no="ORD123",
            expected_amount=Decimal("9.90"),
        )

        self.assertEqual(TOKEN188_OFFLINE_QUERY_CONTRACT, transport.seen_request["contract"])
        self.assertNotIn("plain-secret", repr(transport.seen_request))
        self.assertEqual(TOKEN188_PROVIDER, result.provider)
        self.assertEqual("TX123", result.provider_trade_no)
        self.assertTrue(result.paid)
        self.assertFalse(result.expired)
        self.assertEqual("***", result.raw_response["secret_key"])
        self.assertNotIn("plain-secret", repr(result.raw_response))
        self.assertNotIn("upstream-secret", repr(result.raw_response))

    def test_token188_offline_query_normalizer_maps_pending_and_expired_fixture_statuses(self) -> None:
        config = _token188_config()
        cases = [
            ("pending", False, False),
            ("expired", False, True),
        ]

        for status, paid, expired in cases:
            with self.subTest(status=status):
                result = normalize_token188_offline_query_response(
                    _signed_token188_response(config, status=status),
                    config,
                    expected_out_trade_no="ORD123",
                )

                self.assertEqual(paid, result.paid)
                self.assertEqual(expired, result.expired)

    def test_token188_offline_query_normalizer_rejects_mismatched_order_or_signature(self) -> None:
        config = _token188_config()
        valid = _signed_token188_response(config)
        cases = [
            ({**valid, "sign": "bad"}, "签名无效"),
            (_signed_token188_response(config, orderNo="OTHER"), "订单号不匹配"),
            ({**valid, "contract": "other"}, "离线合同不匹配"),
        ]

        for payload, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    normalize_token188_offline_query_response(
                        payload,
                        config,
                        expected_out_trade_no="ORD123",
                    )

    def test_epay_offline_query_normalizer_accepts_signed_success_fixture_without_network(self) -> None:
        config = _epay_config(key="plain-secret")
        transport = FakeOfflineQueryTransport(_signed_epay_response(config, status="paid"))
        request = build_epay_offline_query_contract_request(
            config,
            out_trade_no="ORD123",
            provider_trade_no="UP-1",
        )

        response = transport.send(request)
        result = normalize_epay_offline_query_response(
            response,
            config,
            expected_out_trade_no="ORD123",
            expected_amount=Decimal("9.90"),
        )

        self.assertEqual(EPAY_OFFLINE_QUERY_CONTRACT, transport.seen_request["contract"])
        self.assertNotIn("plain-secret", repr(transport.seen_request))
        self.assertEqual("epay_compatible", result.provider)
        self.assertEqual("UP-1", result.provider_trade_no)
        self.assertTrue(result.paid)
        self.assertFalse(result.expired)
        self.assertEqual("***", result.raw_response["api_key"])
        self.assertNotIn("plain-secret", repr(result.raw_response))
        self.assertNotIn("upstream-api-key", repr(result.raw_response))

    def test_epay_offline_query_normalizer_maps_pending_and_expired_fixture_statuses(self) -> None:
        config = _epay_config()
        cases = [
            ("pending", False, False),
            ("expired", False, True),
        ]

        for status, paid, expired in cases:
            with self.subTest(status=status):
                result = normalize_epay_offline_query_response(
                    _signed_epay_response(config, status=status),
                    config,
                    expected_out_trade_no="ORD123",
                )

                self.assertEqual(paid, result.paid)
                self.assertEqual(expired, result.expired)

    def test_epay_offline_query_normalizer_rejects_mismatched_pid_order_or_signature(self) -> None:
        config = _epay_config()
        valid = _signed_epay_response(config)
        cases = [
            ({**valid, "sign": "bad"}, "签名无效"),
            (_signed_epay_response(config, pid="other"), "商户不匹配"),
            (_signed_epay_response(config, out_trade_no="OTHER"), "订单号不匹配"),
            ({**valid, "contract": "other"}, "离线合同不匹配"),
        ]

        for payload, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    normalize_epay_offline_query_response(
                        payload,
                        config,
                        expected_out_trade_no="ORD123",
                    )

    def test_lemzf_offline_query_normalizer_keeps_lemzf_provider_name(self) -> None:
        config = _epay_config(provider_name=LEMZF_PROVIDER)
        payload = _signed_epay_response(config, trade_no="LEMZF-UP-1")

        result = normalize_epay_offline_query_response(payload, config, expected_out_trade_no="ORD123")

        self.assertEqual(LEMZF_PROVIDER, result.provider)
        self.assertEqual("LEMZF-UP-1", result.provider_trade_no)

    def test_offline_query_dry_run_builds_token188_contract_and_normalizes_response_without_network(self) -> None:
        config = _token188_config(key="plain-secret")
        transport = FakeOfflineQueryTransport(_signed_token188_response(config, status="paid"))

        result = OfflinePaymentQueryDryRunService().run(
            provider=TOKEN188_PROVIDER,
            config=config,
            out_trade_no="ORD123",
            provider_trade_no="TX123",
            expected_amount=Decimal("9.90"),
            transport=transport,
        )

        self.assertEqual(TOKEN188_PROVIDER, result.provider)
        self.assertEqual(TOKEN188_OFFLINE_QUERY_CONTRACT, result.request_payload["contract"])
        self.assertEqual("ORD123", result.request_payload["orderNo"])
        self.assertEqual("TX123", result.request_payload["transactionId"])
        self.assertEqual(result.request_payload, transport.seen_request)
        self.assertTrue(result.query_result.paid)
        self.assertEqual("TX123", result.query_result.provider_trade_no)
        self.assertNotIn("plain-secret", repr(result.request_payload))
        self.assertNotIn("plain-secret", repr(result.query_result.raw_response))
        self.assertNotIn("upstream-secret", repr(result.query_result.raw_response))

    def test_offline_query_dry_run_builds_lemzf_contract_and_accepts_direct_response(self) -> None:
        config = _epay_config(key="plain-secret", provider_name=LEMZF_PROVIDER)
        payload = _signed_epay_response(config, status="TRADE_SUCCESS", trade_no="LEMZF-UP-1")

        result = OfflinePaymentQueryDryRunService().run(
            provider=LEMZF_PROVIDER,
            config=config,
            out_trade_no="ORD123",
            provider_trade_no="LEMZF-UP-1",
            expected_amount=Decimal("9.90"),
            response_payload=payload,
        )

        self.assertEqual(LEMZF_PROVIDER, result.provider)
        self.assertEqual(EPAY_OFFLINE_QUERY_CONTRACT, result.request_payload["contract"])
        self.assertEqual("ORD123", result.request_payload["out_trade_no"])
        self.assertEqual("LEMZF-UP-1", result.request_payload["trade_no"])
        self.assertEqual(LEMZF_PROVIDER, result.query_result.provider)
        self.assertTrue(result.query_result.paid)
        self.assertFalse(result.query_result.expired)
        self.assertNotIn("plain-secret", repr(result.request_payload))
        self.assertNotIn("plain-secret", repr(result.query_result.raw_response))

    def test_offline_query_dry_run_rejects_ambiguous_or_unsupported_inputs(self) -> None:
        service = OfflinePaymentQueryDryRunService()
        config = _token188_config()
        payload = _signed_token188_response(config)
        transport = FakeOfflineQueryTransport(payload)

        with self.assertRaisesRegex(ValueError, "必须提供离线响应或离线 transport"):
            service.run(provider=TOKEN188_PROVIDER, config=config, out_trade_no="ORD123")
        with self.assertRaisesRegex(ValueError, "不能同时提供响应和 transport"):
            service.run(
                provider=TOKEN188_PROVIDER,
                config=config,
                out_trade_no="ORD123",
                response_payload=payload,
                transport=transport,
            )
        with self.assertRaisesRegex(ValueError, "不支持离线查单 dry-run"):
            service.run(
                provider="epusdt_gmpay",
                config=config,
                out_trade_no="ORD123",
                response_payload=payload,
            )
        with self.assertRaisesRegex(ValueError, "易支付离线查单配置无效"):
            service.run(
                provider=LEMZF_PROVIDER,
                config=_epay_config(),
                out_trade_no="ORD123",
                response_payload=_signed_epay_response(_epay_config()),
            )


def _token188_config(key: str = "secret") -> Token188Config:
    return Token188Config(
        merchant_id="MERCHANT1",
        key=key,
        monitor_address="TADDR",
        gateway_url="https://payweb.188pay.net/",
    )


def _epay_config(key: str = "secret", provider_name: str = "epay_compatible") -> EpayCompatibleConfig:
    return EpayCompatibleConfig(
        merchant_id="1001",
        key=key,
        gateway_url="https://pay.example/submit.php",
        provider_name=provider_name,
    )


def _signed_token188_response(
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


def _signed_epay_response(
    config: EpayCompatibleConfig,
    *,
    status: str = "paid",
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "contract": EPAY_OFFLINE_QUERY_CONTRACT,
        "pid": config.merchant_id,
        "trade_no": "UP-1",
        "out_trade_no": "ORD123",
        "money": "9.90",
        "status": status,
        "api_key": "upstream-api-key",
    }
    payload.update(overrides)
    payload["sign"] = sign_epay_payload(payload, config.key)
    payload["sign_type"] = "MD5"
    return payload


if __name__ == "__main__":
    unittest.main()
