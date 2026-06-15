from __future__ import annotations

from decimal import Decimal
import unittest

try:
    from app.services.payments.base import PaymentOrderRequest
    from app.services.payments.epusdt import EpusdtGmpayConfig, EpusdtGmpayProvider, payload_hash, sign_payload
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过 epusdt 支付测试：{exc.name}") from exc


class EpusdtPaymentContractTest(unittest.TestCase):
    def test_sign_payload_ignores_empty_values_and_existing_signature(self) -> None:
        payload = {
            "pid": "merchant",
            "order_id": "ORD123",
            "amount": "10.50",
            "empty": "",
            "none": None,
            "signature": "wrong",
        }

        signature = sign_payload(payload, "secret")

        self.assertEqual(signature, sign_payload({**payload, "signature": signature}, "secret"))
        self.assertEqual(64, len(payload_hash(payload)))

    def test_verify_callback_accepts_signed_success_payload(self) -> None:
        provider = EpusdtGmpayProvider(_config(secret_key="plain-secret"))
        payload = {
            "pid": "merchant",
            "order_id": "ORD123",
            "trade_id": "TX123",
            "amount": "9.90",
            "status": "paid",
        }
        payload["signature"] = sign_payload(payload, "plain-secret")

        result = provider.verify_callback(payload)

        self.assertEqual("epusdt_gmpay", result.provider)
        self.assertEqual("ORD123", result.out_trade_no)
        self.assertEqual("TX123", result.provider_trade_no)
        self.assertTrue(result.paid)
        self.assertEqual(payload, result.raw_payload)
        self.assertEqual(payload_hash(payload), result.payload_hash)
        self.assertEqual(64, len(result.payload_hash))
        self.assertNotIn("plain-secret", repr(result))

    def test_verify_callback_redacts_nested_sensitive_payload_fields(self) -> None:
        provider = EpusdtGmpayProvider(_config(secret_key="plain-secret"))
        payload = {
            "pid": "merchant",
            "order_id": "ORD123",
            "trade_id": "TX123",
            "amount": "9.90",
            "status": "paid",
            "token": "upstream-token",
            "headers": {
                "Authorization": "Bearer upstream-secret",
                "Trace-ID": "trace-1",
            },
            "events": [
                {"cookie": "session=secret-cookie", "status": "confirmed"},
                {"credential": "raw-credential", "status": "paid"},
            ],
        }
        payload["signature"] = sign_payload(payload, "plain-secret")

        result = provider.verify_callback(payload)

        self.assertEqual("ORD123", result.raw_payload["order_id"])
        self.assertEqual("TX123", result.raw_payload["trade_id"])
        self.assertEqual("***", result.raw_payload["token"])
        self.assertEqual("***", result.raw_payload["headers"]["Authorization"])
        self.assertEqual("trace-1", result.raw_payload["headers"]["Trace-ID"])
        self.assertEqual("***", result.raw_payload["events"][0]["cookie"])
        self.assertEqual("confirmed", result.raw_payload["events"][0]["status"])
        self.assertEqual("***", result.raw_payload["events"][1]["credential"])
        self.assertEqual(payload_hash(payload), result.payload_hash)
        self.assertNotIn("upstream-token", repr(result.raw_payload))
        self.assertNotIn("upstream-secret", repr(result.raw_payload))
        self.assertNotIn("secret-cookie", repr(result.raw_payload))

    def test_verify_callback_valid_signature_non_success_status_is_unpaid(self) -> None:
        provider = EpusdtGmpayProvider(_config())
        payload = {
            "pid": "merchant",
            "order_id": "ORD123",
            "trade_id": "TX123",
            "amount": "9.90",
            "status": "pending",
        }
        payload["signature"] = sign_payload(payload, "secret")

        result = provider.verify_callback(payload)

        self.assertFalse(result.paid)
        self.assertEqual("ORD123", result.out_trade_no)

    def test_verify_callback_rejects_invalid_signature_or_missing_order_number(self) -> None:
        provider = EpusdtGmpayProvider(_config())
        payload = {
            "pid": "merchant",
            "order_id": "ORD123",
            "trade_id": "TX123",
            "amount": "9.90",
            "status": "paid",
        }
        payload["signature"] = sign_payload(payload, "secret")

        with self.assertRaisesRegex(ValueError, "签名无效"):
            provider.verify_callback({**payload, "signature": "bad"})

        missing_order = {**payload, "order_id": "", "out_trade_no": ""}
        missing_order["signature"] = sign_payload(missing_order, "secret")
        with self.assertRaisesRegex(ValueError, "缺少订单号"):
            provider.verify_callback(missing_order)

    def test_create_order_payload_hash_helpers_do_not_require_network(self) -> None:
        request = PaymentOrderRequest(
            out_trade_no="ORD123",
            amount=Decimal("9.90"),
            currency="USDT",
            notify_url="https://store.example/payments/callback/epusdt_gmpay",
        )

        self.assertEqual("ORD123", request.out_trade_no)
        self.assertEqual("9.90", format(request.amount, "f"))


def _config(secret_key: str = "secret") -> EpusdtGmpayConfig:
    return EpusdtGmpayConfig(
        base_url="https://pay.example",
        pid="merchant",
        secret_key=secret_key,
    )


if __name__ == "__main__":
    unittest.main()
