from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Iterable, Mapping
import unittest

from app.services.payments.configs import USDT_TRC20_DIRECT_PROVIDER
from app.services.payments.trc20_direct import (
    USDT_TRC20_CONTRACT_ADDRESS,
    TronUsdtTransfer,
)

try:
    from app.services.payments.trc20_reconcile import Trc20DirectReconcileService
except ModuleNotFoundError:
    from app.services.payments.trc20_direct import Trc20DirectReconcileService  # type: ignore[attr-defined]

try:
    from app.db.models.orders import Trc20DirectTransfer
except ImportError:
    from app.db.models.payments import Trc20DirectTransfer  # type: ignore[no-redef]


MONITOR_ADDRESS = "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb"
SENDER_ADDRESS = "TJRabPrwbZy45sbavfcjinPJC18kjpRTv8"
TX_HASH = "b" * 64


class _ScalarRows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class _FakeResult:
    def __init__(self, *, scalar: object | None = None, rows: list[object] | None = None) -> None:
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self) -> object | None:
        return self._scalar

    def scalars(self) -> _ScalarRows:
        if self._rows:
            return _ScalarRows(self._rows)
        if self._scalar is None:
            return _ScalarRows([])
        return _ScalarRows([self._scalar])

    def all(self) -> list[object]:
        return self._rows


class _FakeSession:
    def __init__(
        self,
        *,
        existing_transfer: object | None = None,
        candidate_rows: list[object] | None = None,
    ) -> None:
        self.existing_transfer = existing_transfer
        self.candidate_rows = candidate_rows or []
        self.added: list[object] = []
        self.flush_count = 0
        self.execute_count = 0
        self.executed_queries: list[object] = []

    async def execute(self, query: object) -> _FakeResult:
        self.execute_count += 1
        self.executed_queries.append(query)
        query_text = str(query).lower()
        if "trc20" in query_text and "transfer" in query_text:
            return _FakeResult(scalar=self.existing_transfer)
        return _FakeResult(rows=self.candidate_rows)

    def add(self, item: object) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        self.flush_count += 1


class _CandidateRow(SimpleNamespace):
    def __iter__(self) -> Iterable[object]:
        yield self.payment
        yield self.order
        yield self.monitor_address


class Trc20DirectReconcileServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_tx_does_not_match_or_add_second_transfer(self) -> None:
        payment, order = _pending_payment_order()
        session = _FakeSession(
            existing_transfer=_stored_transfer(match_status="matched", out_trade_no=order.out_trade_no),
            candidate_rows=[_candidate_row(payment, order)],
        )

        result = await _record_and_match(
            Trc20DirectReconcileService(),
            session,
            _transfer(),
            latest_block_number=105,
            required_confirmations=5,
        )

        self.assertIn(_status(result), {"duplicate_tx", "duplicate"})
        self.assertEqual([], session.added)
        self.assertEqual("pending", payment.status)
        self.assertEqual("pending", order.status)
        self.assertEqual(0, session.flush_count)
        _assert_safe_summary(result)

    async def test_not_confirmed_transfer_is_recorded_without_updating_payment_or_order(self) -> None:
        payment, order = _pending_payment_order()
        session = _FakeSession(candidate_rows=[_candidate_row(payment, order)])

        result = await _record_and_match(
            Trc20DirectReconcileService(),
            session,
            _transfer(block_number=100),
            latest_block_number=104,
            required_confirmations=5,
        )

        self.assertEqual("not_confirmed", _status(result))
        self.assertEqual("pending", payment.status)
        self.assertEqual("pending", order.status)
        self.assertIsNone(payment.paid_at)
        self.assertIsNone(order.paid_at)
        transfer_rows = _added_transfers(session)
        self.assertEqual(1, len(transfer_rows))
        self.assertEqual(TX_HASH, transfer_rows[0].tx_hash)
        self.assertEqual("not_confirmed", _status(transfer_rows[0]))
        self.assertEqual(4, getattr(transfer_rows[0], "confirmations", 4))
        self.assertGreaterEqual(session.flush_count, 1)
        _assert_safe_summary(result)

    async def test_single_candidate_match_records_transfer_and_marks_payment_order_paid(self) -> None:
        payment, order = _pending_payment_order()
        session = _FakeSession(candidate_rows=[_candidate_row(payment, order)])

        result = await _record_and_match(
            Trc20DirectReconcileService(),
            session,
            _transfer(block_number=100),
            latest_block_number=105,
            required_confirmations=5,
        )

        self.assertIn(_status(result), {"matched", "paid", "succeeded"})
        self.assertEqual("paid", payment.status)
        self.assertEqual("paid", order.status)
        self.assertEqual(TX_HASH, payment.provider_trade_no)
        self.assertEqual(USDT_TRC20_DIRECT_PROVIDER, payment.provider)
        self.assertEqual(USDT_TRC20_DIRECT_PROVIDER, order.payment_provider)
        self.assertEqual("tenant_direct", order.payment_mode)
        self.assertIsNotNone(payment.paid_at)
        self.assertIsNotNone(order.paid_at)
        transfer_rows = _added_transfers(session)
        self.assertEqual(1, len(transfer_rows))
        transfer_row = transfer_rows[0]
        self.assertEqual(TX_HASH, transfer_row.tx_hash)
        self.assertEqual(order.out_trade_no, getattr(transfer_row, "out_trade_no", order.out_trade_no))
        self.assertEqual(order.id, getattr(transfer_row, "order_id", order.id))
        self.assertEqual(payment.id, getattr(transfer_row, "payment_id", payment.id))
        self.assertIn(_status(transfer_row), {"matched", "paid", "succeeded"})
        self.assertGreaterEqual(session.flush_count, 1)
        _assert_safe_summary(result)
        _assert_safe_summary(transfer_row)

    async def test_ambiguous_candidates_record_transfer_without_payment_or_order_update(self) -> None:
        payment_one, order_one = _pending_payment_order(order_id=1, out_trade_no="ORD-1")
        payment_two, order_two = _pending_payment_order(order_id=2, out_trade_no="ORD-2")
        session = _FakeSession(
            candidate_rows=[
                _candidate_row(payment_one, order_one),
                _candidate_row(payment_two, order_two),
            ]
        )

        result = await _record_and_match(
            Trc20DirectReconcileService(),
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
        transfer_rows = _added_transfers(session)
        self.assertEqual(1, len(transfer_rows))
        self.assertEqual("ambiguous", _status(transfer_rows[0]))
        self.assertIsNone(getattr(transfer_rows[0], "out_trade_no", None))
        self.assertGreaterEqual(session.flush_count, 1)
        _assert_safe_summary(result)

    async def test_service_rejects_raw_dict_before_query_or_payload_summary(self) -> None:
        session = _FakeSession(candidate_rows=[])

        with self.assertRaisesRegex(ValueError, "TronUsdtTransfer"):
            await _record_and_match(
                Trc20DirectReconcileService(),
                session,
                {
                    "txID": TX_HASH,
                    "raw_payload": {"token": "plain-secret"},
                },
                latest_block_number=105,
                required_confirmations=5,
            )

        self.assertEqual(0, session.execute_count)
        self.assertEqual([], session.added)
        self.assertEqual(0, session.flush_count)


async def _record_and_match(
    service: object,
    session: _FakeSession,
    transfer: object,
    *,
    latest_block_number: int,
    required_confirmations: int,
) -> object:
    for method_name in (
        "record_and_match_transfer",
        "reconcile_transfer",
        "record_transfer",
    ):
        method = getattr(service, method_name, None)
        if method is not None:
            return await method(
                session,
                transfer,
                latest_block_number=latest_block_number,
                required_confirmations=required_confirmations,
            )
    raise AssertionError("Trc20DirectReconcileService 缺少 record_and_match_transfer/reconcile_transfer/record_transfer")


def _transfer(*, tx_hash: str = TX_HASH, block_number: int = 100) -> TronUsdtTransfer:
    return TronUsdtTransfer(
        tx_hash=tx_hash,
        block_number=block_number,
        timestamp_ms=1_000,
        from_address=SENDER_ADDRESS,
        to_address=MONITOR_ADDRESS,
        contract_address=USDT_TRC20_CONTRACT_ADDRESS,
        raw_amount=1_234_567,
        amount=Decimal("1.234567"),
    )


def _pending_payment_order(
    *,
    order_id: int = 1,
    tenant_id: int = 7,
    out_trade_no: str = "ORD-1",
) -> tuple[SimpleNamespace, SimpleNamespace]:
    now = datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc)
    order = SimpleNamespace(
        id=order_id,
        tenant_id=tenant_id,
        out_trade_no=out_trade_no,
        amount=Decimal("1.234567"),
        currency="USDT",
        status="pending",
        payment_provider=USDT_TRC20_DIRECT_PROVIDER,
        payment_mode="tenant_direct",
        created_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(seconds=1),
        paid_at=None,
    )
    payment = SimpleNamespace(
        id=order_id + 100,
        order_id=order_id,
        tenant_id=tenant_id,
        provider=USDT_TRC20_DIRECT_PROVIDER,
        provider_trade_no=None,
        amount=Decimal("1.234567"),
        currency="USDT",
        status="pending",
        paid_at=None,
        monitor_address=MONITOR_ADDRESS,
    )
    return payment, order


def _candidate_row(payment: SimpleNamespace, order: SimpleNamespace) -> object:
    return _CandidateRow(
        payment=payment,
        order=order,
        monitor_address=MONITOR_ADDRESS,
        out_trade_no=order.out_trade_no,
        expected_raw_amount=1_234_567,
        created_at_ms=0,
        expires_at_ms=2_000,
    )


def _stored_transfer(
    *,
    match_status: str,
    out_trade_no: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        tx_hash=TX_HASH,
        block_number=100,
        timestamp_ms=1_000,
        from_address=SENDER_ADDRESS,
        to_address=MONITOR_ADDRESS,
        contract_address=USDT_TRC20_CONTRACT_ADDRESS,
        raw_amount=1_234_567,
        amount=Decimal("1.234567"),
        confirmations=5,
        match_status=match_status,
        out_trade_no=out_trade_no,
    )


def _added_transfers(session: _FakeSession) -> list[object]:
    return [item for item in session.added if isinstance(item, Trc20DirectTransfer)]


def _status(value: object) -> str | None:
    if isinstance(value, Mapping):
        for key in ("status", "match_status", "reason", "decision_status"):
            status = value.get(key)
            if isinstance(status, str):
                return status
    for attr in ("status", "match_status", "reason", "decision_status"):
        status = getattr(value, attr, None)
        if isinstance(status, str):
            return status
    return None


def _assert_safe_summary(value: object) -> None:
    rendered = repr(value).lower()
    forbidden_names: Iterable[str] = (
        "raw_payload",
        "raw_transaction",
        "payload_json",
        "authorization",
        "api_key",
        "secret",
        "token",
        "plain-secret",
    )
    for field_name in forbidden_names:
        if field_name in rendered or hasattr(value, field_name):
            raise AssertionError(f"TRC20 直付摘要不应暴露 {field_name}")


if __name__ == "__main__":
    unittest.main()
