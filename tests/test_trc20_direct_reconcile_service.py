from __future__ import annotations

import unittest

from tests.test_trc20_direct_reconcile import (
    TX_HASH,
    Trc20DirectReconcileService,
    _FakeSession,
    _added_transfers,
    _assert_safe_summary,
    _candidate_row,
    _pending_payment_order,
    _status,
    _stored_transfer,
    _transfer,
)


class Trc20DirectReconcileServiceContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_record_transfer_persists_offline_transfer_without_network_or_env(self) -> None:
        service = Trc20DirectReconcileService()
        session = _FakeSession(candidate_rows=[])

        result = await service.record_transfer(
            session,
            _transfer(block_number=100),
            tenant_id=7,
            latest_block_number=105,
            required_confirmations=5,
        )

        self.assertEqual("no_candidate", _status(result))
        self.assertEqual(1, len(_added_transfers(session)))
        self.assertEqual(TX_HASH, _added_transfers(session)[0].tx_hash)
        _assert_safe_summary(result)

    async def test_record_transfer_rejects_duplicate_tx_hash_before_matching(self) -> None:
        payment, order = _pending_payment_order()
        service = Trc20DirectReconcileService()
        session = _FakeSession(
            existing_transfer=_stored_transfer(match_status="matched", out_trade_no=order.out_trade_no),
            candidate_rows=[_candidate_row(payment, order)],
        )

        result = await service.record_transfer(
            session,
            _transfer(block_number=100),
            latest_block_number=105,
            required_confirmations=5,
        )

        self.assertEqual("duplicate_tx", _status(result))
        self.assertEqual("pending", payment.status)
        self.assertEqual("pending", order.status)
        self.assertEqual([], session.added)
        self.assertEqual(0, session.flush_count)

    async def test_match_pending_payment_marks_not_confirmed_without_updating_order(self) -> None:
        payment, order = _pending_payment_order()
        service = Trc20DirectReconcileService()
        session = _FakeSession(candidate_rows=[_candidate_row(payment, order)])

        result = await service.match_pending_payment(
            session,
            _transfer(block_number=100),
            latest_block_number=104,
            required_confirmations=5,
        )

        self.assertEqual("not_confirmed", _status(result))
        self.assertEqual("pending", payment.status)
        self.assertEqual("pending", order.status)

    async def test_match_pending_payment_rejects_ambiguous_candidates(self) -> None:
        payment_one, order_one = _pending_payment_order(order_id=1, out_trade_no="ORD-1")
        payment_two, order_two = _pending_payment_order(order_id=2, out_trade_no="ORD-2")
        service = Trc20DirectReconcileService()
        session = _FakeSession(
            candidate_rows=[
                _candidate_row(payment_one, order_one),
                _candidate_row(payment_two, order_two),
            ]
        )

        result = await service.match_pending_payment(
            session,
            _transfer(block_number=100),
            latest_block_number=105,
            required_confirmations=5,
        )

        self.assertEqual("ambiguous", _status(result))
        self.assertEqual("pending", payment_one.status)
        self.assertEqual("pending", order_one.status)
        self.assertEqual("pending", payment_two.status)
        self.assertEqual("pending", order_two.status)

    async def test_match_pending_payment_marks_payment_and_order_matched(self) -> None:
        payment, order = _pending_payment_order()
        service = Trc20DirectReconcileService()
        session = _FakeSession(candidate_rows=[_candidate_row(payment, order)])

        result = await service.match_pending_payment(
            session,
            _transfer(block_number=100),
            latest_block_number=105,
            required_confirmations=5,
        )

        self.assertEqual("matched", _status(result))
        self.assertEqual("paid", payment.status)
        self.assertEqual("paid", order.status)
        self.assertEqual(TX_HASH, payment.provider_trade_no)

    async def test_match_pending_payment_is_tenant_scoped(self) -> None:
        other_payment, other_order = _pending_payment_order(order_id=1, tenant_id=8, out_trade_no="ORD-8")
        payment, order = _pending_payment_order(order_id=2, tenant_id=7, out_trade_no="ORD-7")
        service = Trc20DirectReconcileService()
        session = _FakeSession(
            candidate_rows=[
                _candidate_row(other_payment, other_order),
                _candidate_row(payment, order),
            ]
        )

        result = await service.match_pending_payment(
            session,
            _transfer(block_number=100),
            tenant_id=7,
            latest_block_number=105,
            required_confirmations=5,
        )

        self.assertEqual("matched", _status(result))
        self.assertEqual("pending", other_payment.status)
        self.assertEqual("pending", other_order.status)
        self.assertEqual("paid", payment.status)
        self.assertEqual("paid", order.status)

    async def test_match_pending_payment_does_not_expose_raw_payload_or_secret(self) -> None:
        service = Trc20DirectReconcileService()
        session = _FakeSession(candidate_rows=[])

        with self.assertRaisesRegex(ValueError, "TronUsdtTransfer"):
            await service.match_pending_payment(
                session,
                {"txID": TX_HASH, "raw_payload": {"token": "plain-secret"}},
                tenant_id=7,
                latest_block_number=105,
                required_confirmations=5,
            )

        self.assertEqual(0, session.execute_count)
        self.assertEqual([], session.added)


if __name__ == "__main__":
    unittest.main()
