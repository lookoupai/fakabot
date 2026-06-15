from __future__ import annotations

import unittest

try:
    from app.bots.routers.master import _parse_complete_withdrawal_args
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过母 Bot 提现命令测试：{exc.name}") from exc


class MasterWithdrawalCommandParserTest(unittest.TestCase):
    def test_parse_complete_withdrawal_keeps_legacy_note_format(self) -> None:
        withdrawal_id, payout_reference, payout_proof_url, note = _parse_complete_withdrawal_args("12 | 已人工打款")

        self.assertEqual(12, withdrawal_id)
        self.assertIsNone(payout_reference)
        self.assertIsNone(payout_proof_url)
        self.assertEqual("已人工打款", note)

    def test_parse_complete_withdrawal_accepts_payout_reference_and_proof_url(self) -> None:
        withdrawal_id, payout_reference, payout_proof_url, note = _parse_complete_withdrawal_args(
            "12 | txid-abc | https://example.com/proof/abc | 已确认"
        )

        self.assertEqual(12, withdrawal_id)
        self.assertEqual("txid-abc", payout_reference)
        self.assertEqual("https://example.com/proof/abc", payout_proof_url)
        self.assertEqual("已确认", note)

    def test_parse_complete_withdrawal_accepts_reference_without_proof_url(self) -> None:
        withdrawal_id, payout_reference, payout_proof_url, note = _parse_complete_withdrawal_args(
            "12 | txid-abc | 已确认"
        )

        self.assertEqual(12, withdrawal_id)
        self.assertEqual("txid-abc", payout_reference)
        self.assertIsNone(payout_proof_url)
        self.assertEqual("已确认", note)

    def test_parse_complete_withdrawal_rejects_long_reference(self) -> None:
        with self.assertRaises(ValueError):
            _parse_complete_withdrawal_args(f"12 | {'x' * 129} | 已确认")


if __name__ == "__main__":
    unittest.main()
