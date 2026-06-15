from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest

from app.services.payments.trc20_observability import Trc20DirectTransferObservationService


class _ScalarRows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class _FakeResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> _ScalarRows:
        return _ScalarRows(self._rows)


class _FakeSession:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.executed_queries: list[object] = []

    async def execute(self, query: object) -> _FakeResult:
        self.executed_queries.append(query)
        return _FakeResult(self.rows)


class Trc20DirectTransferObservationServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_list_tenant_transfers_returns_safe_masked_summary(self) -> None:
        now = datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc)
        service = Trc20DirectTransferObservationService()
        session = _FakeSession(
            [
                SimpleNamespace(
                    id=1,
                    tenant_id=7,
                    order_id=10,
                    payment_id=20,
                    tx_hash="a" * 64,
                    block_number=123,
                    timestamp_ms=1_780_000_000_000,
                    block_timestamp=now,
                    from_address="TJRabPrwbZy45sbavfcjinPJC18kjpRTv8",
                    to_address="T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
                    contract_address="TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
                    amount=Decimal("1.23000000"),
                    confirmations=12,
                    match_status="matched",
                    out_trade_no="ORD-1",
                    matched_at=now,
                    created_at=now,
                    raw_payload={"token": "plain-secret"},
                )
            ]
        )

        summaries = await service.list_tenant_transfers(
            session,
            tenant_id=7,
            match_status=" matched ",
            tx_hash=f"0x{'a' * 64}",
            limit=500,
        )

        self.assertEqual(1, len(summaries))
        summary = summaries[0]
        self.assertEqual("a" * 64, summary.tx_hash)
        self.assertEqual("matched", summary.match_status)
        self.assertEqual("TJRabP***jpRTv8", summary.from_address_masked)
        self.assertEqual("T9yD14***HxuWwb", summary.to_address_masked)
        rendered = repr(summary).lower()
        for forbidden in (
            "tenant_id",
            "payment_id",
            "order_id",
            "raw_payload",
            "payload_json",
            "metadata_json",
            "plain-secret",
        ):
            self.assertNotIn(forbidden, rendered)
        query_text = str(session.executed_queries[0])
        self.assertIn("trc20_direct_transfers.tenant_id", query_text)

    async def test_list_tenant_transfers_rejects_invalid_filters_before_query(self) -> None:
        service = Trc20DirectTransferObservationService()
        session = _FakeSession([])

        with self.assertRaises(ValueError):
            await service.list_tenant_transfers(session, tenant_id=7, match_status="raw_payload")

        with self.assertRaises(ValueError):
            await service.list_tenant_transfers(session, tenant_id=7, tx_hash="not-a-tx")

        self.assertEqual([], session.executed_queries)


if __name__ == "__main__":
    unittest.main()
