from __future__ import annotations

from decimal import Decimal
import unittest

try:
    from app.services.payments.trc20_direct import (
        TRC20_TRANSFER_METHOD_ID,
        USDT_TRC20_CONTRACT_ADDRESS,
        TronUsdtPaymentCandidate,
        match_tron_usdt_transfer,
        normalize_tron_tx_hash,
        parse_tron_usdt_transfer,
        trc20_usdt_amount_to_raw,
        trc20_usdt_raw_to_decimal,
        tron_address_from_hex,
        tron_address_to_hex,
    )
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过 TRC20 直付离线核心测试：{exc.name}") from exc


MONITOR_ADDRESS = "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb"
OTHER_ADDRESS = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
TX_HASH = "a" * 64


class Trc20DirectCoreTest(unittest.TestCase):
    def test_parse_standard_trc20_usdt_transfer_without_network(self) -> None:
        transfer = parse_tron_usdt_transfer(_transaction(raw_amount=1_234_567), block_number=100)

        self.assertIsNotNone(transfer)
        assert transfer is not None
        self.assertEqual(TX_HASH, transfer.tx_hash)
        self.assertEqual(100, transfer.block_number)
        self.assertEqual(1_000, transfer.timestamp_ms)
        self.assertEqual(MONITOR_ADDRESS, transfer.from_address)
        self.assertEqual(MONITOR_ADDRESS, transfer.to_address)
        self.assertEqual(USDT_TRC20_CONTRACT_ADDRESS, transfer.contract_address)
        self.assertEqual(1_234_567, transfer.raw_amount)
        self.assertEqual(Decimal("1.234567"), transfer.amount)
        self.assertNotIn("data", repr(transfer).lower())

    def test_parse_ignores_non_matching_transactions(self) -> None:
        self.assertIsNone(parse_tron_usdt_transfer(_transaction(success=False), block_number=100))
        self.assertIsNone(parse_tron_usdt_transfer(_transaction(contract_type="TransferContract"), block_number=100))
        self.assertIsNone(parse_tron_usdt_transfer(_transaction(method_id="deadbeef"), block_number=100))
        self.assertIsNone(
            parse_tron_usdt_transfer(
                _transaction(contract_address=MONITOR_ADDRESS),
                block_number=100,
            )
        )

    def test_parse_rejects_malformed_transfer_without_raw_payload_leak(self) -> None:
        invalid_cases = (
            ("bad-tx", _transaction(tx_hash="not-a-hash"), "plain-secret"),
            ("bad-hex", _transaction(data=f"{TRC20_TRANSFER_METHOD_ID}{'z' * 128}"), "plain-secret"),
            ("short-data", _transaction(data=f"{TRC20_TRANSFER_METHOD_ID}{'0' * 12}"), "plain-secret"),
            ("zero-amount", _transaction(raw_amount=0), "plain-secret"),
        )
        for label, transaction, secret in invalid_cases:
            with self.subTest(label=label):
                with self.assertRaises(ValueError) as caught:
                    parse_tron_usdt_transfer(transaction, block_number=100)
                rendered = str(caught.exception).lower()
                self.assertNotIn(secret, rendered)
                self.assertNotIn("authorization", rendered)
                self.assertNotIn("api_key", rendered)
                self.assertNotIn("secret", rendered)

    def test_amount_conversion_uses_integer_base_units(self) -> None:
        self.assertEqual(Decimal("1.234567"), trc20_usdt_raw_to_decimal(1_234_567))
        self.assertEqual(1_234_567, trc20_usdt_amount_to_raw("1.234567"))
        self.assertEqual(1_230_000, trc20_usdt_amount_to_raw(Decimal("1.23")))
        with self.assertRaisesRegex(ValueError, "最多支持 6 位小数"):
            trc20_usdt_amount_to_raw("1.0000001")

    def test_tron_address_hex_roundtrip_and_tx_hash_normalization(self) -> None:
        address_hex = tron_address_to_hex(MONITOR_ADDRESS)

        self.assertEqual("41", address_hex[:2])
        self.assertEqual(MONITOR_ADDRESS, tron_address_from_hex(address_hex))
        self.assertEqual(MONITOR_ADDRESS, tron_address_from_hex(address_hex[2:]))
        self.assertEqual(TX_HASH, normalize_tron_tx_hash(f"0x{TX_HASH.upper()}"))

    def test_match_transfer_requires_confirmation_and_deduplicates_tx_hash(self) -> None:
        transfer = parse_tron_usdt_transfer(_transaction(raw_amount=1_234_567), block_number=100)
        assert transfer is not None
        candidate = _candidate()

        not_confirmed = match_tron_usdt_transfer(
            transfer,
            [candidate],
            latest_block_number=104,
            required_confirmations=5,
        )
        duplicate = match_tron_usdt_transfer(
            transfer,
            [candidate],
            latest_block_number=105,
            required_confirmations=5,
            seen_tx_hashes={TX_HASH.upper()},
        )
        matched = match_tron_usdt_transfer(
            transfer,
            [candidate],
            latest_block_number=105,
            required_confirmations=5,
        )

        self.assertFalse(not_confirmed.matched)
        self.assertEqual("not_confirmed", not_confirmed.reason)
        self.assertEqual(4, not_confirmed.confirmations)
        self.assertFalse(duplicate.matched)
        self.assertEqual("duplicate_tx", duplicate.reason)
        self.assertTrue(matched.matched)
        self.assertEqual("matched", matched.reason)
        self.assertEqual("ORD-1", matched.out_trade_no)
        self.assertEqual(TX_HASH, matched.tx_hash)

    def test_match_transfer_reports_safe_mismatch_reasons(self) -> None:
        transfer = parse_tron_usdt_transfer(_transaction(raw_amount=1_234_567), block_number=100)
        assert transfer is not None

        cases = (
            ("no_candidate", []),
            ("address_mismatch", [_candidate(monitor_address=OTHER_ADDRESS)]),
            ("amount_mismatch", [_candidate(expected_raw_amount=999)]),
            ("outside_time_window", [_candidate(created_at_ms=2_000, expires_at_ms=3_000)]),
        )
        for reason, candidates in cases:
            with self.subTest(reason=reason):
                decision = match_tron_usdt_transfer(
                    transfer,
                    candidates,
                    latest_block_number=105,
                    required_confirmations=5,
                )
                self.assertFalse(decision.matched)
                self.assertEqual(reason, decision.reason)
                self.assertNotIn("secret", repr(decision).lower())

    def test_match_transfer_rejects_ambiguous_candidate_window(self) -> None:
        transfer = parse_tron_usdt_transfer(_transaction(raw_amount=1_234_567), block_number=100)
        assert transfer is not None

        decision = match_tron_usdt_transfer(
            transfer,
            [_candidate(out_trade_no="ORD-1"), _candidate(out_trade_no="ORD-2")],
            latest_block_number=105,
            required_confirmations=5,
        )

        self.assertFalse(decision.matched)
        self.assertEqual("ambiguous", decision.reason)
        self.assertIsNone(decision.out_trade_no)


def _candidate(
    *,
    out_trade_no: str = "ORD-1",
    monitor_address: str = MONITOR_ADDRESS,
    expected_raw_amount: int = 1_234_567,
    created_at_ms: int = 0,
    expires_at_ms: int = 2_000,
) -> TronUsdtPaymentCandidate:
    return TronUsdtPaymentCandidate(
        out_trade_no=out_trade_no,
        monitor_address=monitor_address,
        expected_raw_amount=expected_raw_amount,
        created_at_ms=created_at_ms,
        expires_at_ms=expires_at_ms,
    )


def _transaction(
    *,
    tx_hash: str = TX_HASH,
    success: bool = True,
    contract_type: str = "TriggerSmartContract",
    contract_address: str = USDT_TRC20_CONTRACT_ADDRESS,
    method_id: str = TRC20_TRANSFER_METHOD_ID,
    to_address: str = MONITOR_ADDRESS,
    raw_amount: int = 1_234_567,
    data: str | None = None,
) -> dict[str, object]:
    calldata = data if data is not None else _transfer_calldata(method_id, to_address, raw_amount)
    return {
        "txID": tx_hash,
        "ret": [{"contractRet": "SUCCESS" if success else "REVERT"}],
        "raw_data": {
            "timestamp": 1_000,
            "contract": [
                {
                    "type": contract_type,
                    "parameter": {
                        "value": {
                            "owner_address": tron_address_to_hex(MONITOR_ADDRESS),
                            "contract_address": tron_address_to_hex(contract_address),
                            "data": calldata,
                        }
                    },
                }
            ],
        },
    }


def _transfer_calldata(method_id: str, to_address: str, raw_amount: int) -> str:
    recipient = tron_address_to_hex(to_address)[2:]
    return f"{method_id}{recipient:0>64}{raw_amount:064x}"


if __name__ == "__main__":
    unittest.main()
