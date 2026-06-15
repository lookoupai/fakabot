from __future__ import annotations

from datetime import datetime, timezone
import unittest
from decimal import Decimal
from types import SimpleNamespace

try:
    from app.services.ledger import LedgerService, SettlementPolicySummary
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过账本规则测试：{exc.name}") from exc


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, item: object) -> None:
        self.added.append(item)


class _FakeAsyncSession(_FakeSession):
    def __init__(self, execute_results: list[object] | None = None) -> None:
        super().__init__()
        self.execute_results = list(execute_results or [])
        self.flush_count = 0

    async def execute(self, _query: object) -> object:
        self.last_query = _query
        return self.execute_results.pop(0)

    async def flush(self) -> None:
        self.flush_count += 1


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value


class _ScalarsResult:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def scalars(self) -> "_ScalarsResult":
        return self

    def all(self) -> list[object]:
        return self.values


class LedgerAccountingRulesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.service = LedgerService()

    def test_platform_fee_amount_is_quantized_and_disabled_fee_is_zero(self) -> None:
        enabled_policy = SettlementPolicySummary(
            scope_type="platform",
            tenant_id=None,
            freeze_days=7,
            platform_fee_enabled=True,
            platform_fee_percent=Decimal("1.2345"),
        )
        disabled_policy = SettlementPolicySummary(
            scope_type="platform",
            tenant_id=None,
            freeze_days=7,
            platform_fee_enabled=False,
            platform_fee_percent=Decimal("99"),
        )

        self.assertEqual(Decimal("1.23450000"), self.service._platform_fee_amount(Decimal("100"), enabled_policy))
        self.assertEqual(Decimal("0"), self.service._platform_fee_amount(Decimal("100"), disabled_policy))

    def test_normalize_refund_amount_rejects_over_refund(self) -> None:
        order = SimpleNamespace(amount=Decimal("10.00"))

        with self.assertRaises(ValueError):
            self.service._normalize_refund_amount(order, Decimal("6.00"), Decimal("5.01"))

    def test_normalize_refund_amount_uses_remaining_amount_for_full_refund(self) -> None:
        order = SimpleNamespace(amount=Decimal("10.00"))

        refund_amount = self.service._normalize_refund_amount(order, Decimal("6.00"), None)

        self.assertEqual(Decimal("4.00"), refund_amount)

    def test_withdrawal_audit_masks_address_and_records_actor(self) -> None:
        session = _FakeSession()
        withdrawal = SimpleNamespace(
            id=7,
            tenant_id=12,
            amount=Decimal("10.50"),
            currency="USDT",
            network="TRC20",
            address="T1234567890abcdef",
            payout_reference="txid:abc",
            payout_proof_url="https://example.com/proof/abc",
        )

        self.service._add_withdrawal_audit(
            session=session,
            withdrawal=withdrawal,
            action="ledger.withdrawal_completed",
            actor_user_id=99,
            old_status="pending",
            new_status="completed",
            note="txid:abc",
        )

        self.assertEqual(1, len(session.added))
        audit = session.added[0]
        self.assertEqual(12, audit.tenant_id)
        self.assertEqual(99, audit.actor_user_id)
        self.assertEqual("ledger.withdrawal_completed", audit.action)
        self.assertEqual("withdrawal_request", audit.target_type)
        self.assertEqual("7", audit.target_id)
        self.assertEqual("T12345***abcdef", audit.metadata_json["address"])
        self.assertEqual("pending", audit.metadata_json["old_status"])
        self.assertEqual("completed", audit.metadata_json["new_status"])
        self.assertEqual("txid:abc", audit.metadata_json["note"])
        self.assertEqual("txid:abc", audit.metadata_json["payout_reference"])
        self.assertEqual("https://example.com/proof/abc", audit.metadata_json["payout_proof_url"])

    def test_withdrawal_audit_masks_short_address_and_keeps_empty_note(self) -> None:
        session = _FakeSession()
        withdrawal = SimpleNamespace(
            id=8,
            tenant_id=12,
            amount=Decimal("1.00"),
            currency="USDT",
            network="TRC20",
            address="T123",
            payout_reference=None,
            payout_proof_url=None,
        )

        self.service._add_withdrawal_audit(
            session=session,
            withdrawal=withdrawal,
            action="ledger.withdrawal_rejected",
            actor_user_id=None,
            old_status="pending",
            new_status="rejected",
            note=None,
        )

        audit = session.added[0]
        self.assertEqual("***", audit.metadata_json["address"])
        self.assertIsNone(audit.metadata_json["note"])
        self.assertIsNone(audit.actor_user_id)

    async def test_list_pending_withdrawals_filters_pending_and_orders_by_oldest_first(self) -> None:
        requested_at = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
        withdrawal = SimpleNamespace(
            id=21,
            tenant_id=12,
            amount=Decimal("10.00"),
            currency="USDT",
            network="TRC20",
            address="T1234567890abcdef",
            status="pending",
            requested_at=requested_at,
            payout_reference=None,
            payout_proof_url=None,
            reviewed_at=None,
            completed_at=None,
        )
        session = _FakeAsyncSession(execute_results=[_ScalarsResult([withdrawal])])

        result = await self.service.list_pending_withdrawals(session, limit=20)

        self.assertEqual(1, len(result))
        self.assertEqual(21, result[0].withdrawal_id)
        self.assertEqual(12, result[0].tenant_id)
        self.assertEqual("pending", result[0].status)
        self.assertEqual(requested_at, result[0].requested_at)
        query_text = str(session.last_query)
        self.assertIn("withdrawal_requests.status", query_text)
        self.assertIn("withdrawal_requests.requested_at ASC", query_text)
        self.assertIn("withdrawal_requests.id ASC", query_text)
        self.assertIn("LIMIT", query_text)

    async def test_get_platform_withdrawal_reads_by_withdrawal_id(self) -> None:
        requested_at = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
        withdrawal = SimpleNamespace(
            id=21,
            tenant_id=12,
            amount=Decimal("10.00"),
            currency="USDT",
            network="TRC20",
            address="T1234567890abcdef",
            status="completed",
            requested_at=requested_at,
            payout_reference="txid:abc",
            payout_proof_url="https://example.com/proof/abc",
            reviewed_at=datetime(2026, 6, 8, 13, 0, tzinfo=timezone.utc),
            completed_at=datetime(2026, 6, 8, 13, 30, tzinfo=timezone.utc),
        )
        session = _FakeAsyncSession(execute_results=[_ScalarResult(withdrawal)])

        result = await self.service.get_platform_withdrawal(session, withdrawal_id=21)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(21, result.withdrawal_id)
        self.assertEqual(12, result.tenant_id)
        self.assertEqual("completed", result.status)
        self.assertEqual("txid:abc", result.payout_reference)
        query_text = str(session.last_query)
        self.assertIn("withdrawal_requests.id =", query_text)

    async def test_complete_withdrawal_records_entry_audit_and_rejects_duplicate_completion(self) -> None:
        session = _FakeAsyncSession()
        withdrawal = SimpleNamespace(
            id=21,
            tenant_id=12,
            amount=Decimal("10.00"),
            currency="USDT",
            network="TRC20",
            address="T1234567890abcdef",
            status="pending",
            admin_note=None,
            reviewed_at=None,
            completed_at=None,
            payout_reference=None,
            payout_proof_url=None,
        )
        account = SimpleNamespace(
            id=31,
            tenant_id=12,
            currency="USDT",
            frozen_balance=Decimal("10.00"),
        )

        async def _get_pending_withdrawal(_session: object, withdrawal_id: int) -> object:
            self.assertEqual(21, withdrawal_id)
            if withdrawal.status != "pending":
                raise ValueError("提现申请不存在或状态不可处理")
            return withdrawal

        async def _get_account(
            _session: object,
            tenant_id: int,
            account_type: str = "main",
            currency: str = "USDT",
            for_update: bool = False,
        ) -> object:
            self.assertEqual(12, tenant_id)
            self.assertEqual("USDT", currency)
            self.assertTrue(for_update)
            return account

        self.service._get_pending_withdrawal = _get_pending_withdrawal
        self.service.get_or_create_account = _get_account

        result = await self.service.complete_withdrawal(
            session,
            21,
            "已打款",
            actor_user_id=99,
            payout_reference=" txid:abc ",
            payout_proof_url=" https://example.com/proof/abc ",
        )

        self.assertIs(result, withdrawal)
        self.assertEqual(Decimal("0.00"), account.frozen_balance)
        self.assertEqual("completed", withdrawal.status)
        self.assertEqual("已打款", withdrawal.admin_note)
        self.assertEqual("txid:abc", withdrawal.payout_reference)
        self.assertEqual("https://example.com/proof/abc", withdrawal.payout_proof_url)
        self.assertIsNotNone(withdrawal.reviewed_at)
        self.assertIsNotNone(withdrawal.completed_at)
        entries = [item for item in session.added if item.__class__.__name__ == "LedgerEntry"]
        audits = [item for item in session.added if item.__class__.__name__ == "AuditLog"]
        self.assertEqual(1, len(entries))
        self.assertEqual("withdrawal_completed", entries[0].entry_type)
        self.assertEqual("withdrawal:21:completed", entries[0].idempotency_key)
        self.assertEqual(1, len(audits))
        self.assertEqual("ledger.withdrawal_completed", audits[0].action)
        self.assertEqual("已打款", audits[0].metadata_json["note"])
        self.assertEqual("txid:abc", audits[0].metadata_json["payout_reference"])
        self.assertEqual("https://example.com/proof/abc", audits[0].metadata_json["payout_proof_url"])

        added_count = len(session.added)
        with self.assertRaises(ValueError):
            await self.service.complete_withdrawal(session, 21, "duplicate", actor_user_id=99)
        self.assertEqual(added_count, len(session.added))

    async def test_reject_withdrawal_returns_frozen_balance_and_rejects_later_completion(self) -> None:
        session = _FakeAsyncSession()
        withdrawal = SimpleNamespace(
            id=22,
            tenant_id=12,
            amount=Decimal("7.50"),
            currency="USDT",
            network="TRC20",
            address="T123",
            status="pending",
            admin_note=None,
            reviewed_at=None,
            payout_reference=None,
            payout_proof_url=None,
        )
        account = SimpleNamespace(
            id=32,
            tenant_id=12,
            currency="USDT",
            available_balance=Decimal("1.00"),
            frozen_balance=Decimal("7.50"),
        )

        async def _get_pending_withdrawal(_session: object, withdrawal_id: int) -> object:
            self.assertEqual(22, withdrawal_id)
            if withdrawal.status != "pending":
                raise ValueError("提现申请不存在或状态不可处理")
            return withdrawal

        async def _get_account(
            _session: object,
            tenant_id: int,
            account_type: str = "main",
            currency: str = "USDT",
            for_update: bool = False,
        ) -> object:
            self.assertEqual(12, tenant_id)
            self.assertEqual("USDT", currency)
            self.assertTrue(for_update)
            return account

        self.service._get_pending_withdrawal = _get_pending_withdrawal
        self.service.get_or_create_account = _get_account

        result = await self.service.reject_withdrawal(session, 22, "  资料不完整  ", actor_user_id=99)

        self.assertIs(result, withdrawal)
        self.assertEqual(Decimal("8.50"), account.available_balance)
        self.assertEqual(Decimal("0.00"), account.frozen_balance)
        self.assertEqual("rejected", withdrawal.status)
        self.assertEqual("资料不完整", withdrawal.admin_note)
        self.assertIsNotNone(withdrawal.reviewed_at)
        entries = [item for item in session.added if item.__class__.__name__ == "LedgerEntry"]
        audits = [item for item in session.added if item.__class__.__name__ == "AuditLog"]
        self.assertEqual("withdrawal_rejected", entries[0].entry_type)
        self.assertEqual("withdrawal:22:rejected", entries[0].idempotency_key)
        self.assertEqual("ledger.withdrawal_rejected", audits[0].action)
        self.assertEqual("***", audits[0].metadata_json["address"])
        self.assertEqual("资料不完整", audits[0].metadata_json["note"])

        added_count = len(session.added)
        with self.assertRaises(ValueError):
            await self.service.reject_withdrawal(session, 22, None, actor_user_id=99)
        with self.assertRaises(ValueError):
            await self.service.complete_withdrawal(session, 22, None, actor_user_id=99)
        self.assertEqual(added_count, len(session.added))

    async def test_complete_withdrawal_rejects_invalid_payout_proof_before_state_change(self) -> None:
        session = _FakeAsyncSession()

        async def _get_pending_withdrawal(_session: object, _withdrawal_id: int) -> object:
            raise AssertionError("不应在凭证校验失败后查询提现记录")

        self.service._get_pending_withdrawal = _get_pending_withdrawal

        with self.assertRaises(ValueError):
            await self.service.complete_withdrawal(
                session,
                21,
                actor_user_id=99,
                payout_reference="x" * 129,
            )

        self.assertEqual([], session.added)

    async def test_refund_after_completed_withdrawal_creates_recovery_negative_available_balance(self) -> None:
        order = SimpleNamespace(
            id=41,
            tenant_id=12,
            out_trade_no="ORD41",
            amount=Decimal("100.00"),
            currency="USDT",
            payment_mode="platform_escrow",
            source_type="self",
            status="completed",
        )
        session = _FakeAsyncSession(
            execute_results=[
                _ScalarResult(order)
            ]
        )
        settlement_entry = SimpleNamespace(
            id=51,
            account_id=61,
            order_id=41,
            amount=Decimal("100.00"),
        )
        account = SimpleNamespace(
            id=61,
            tenant_id=12,
            currency="USDT",
            available_balance=Decimal("0.00"),
            pending_balance=Decimal("0.00"),
        )

        async def _get_refundable_settlement_entries(_session: object, order_id: int) -> list[object]:
            self.assertEqual(41, order_id)
            return [settlement_entry]

        async def _get_refund_by_key(_session: object, order_id: int, _key: str) -> None:
            self.assertEqual(41, order_id)
            return None

        async def _completed_refund_amount(_session: object, order_id: int) -> Decimal:
            self.assertEqual(41, order_id)
            return Decimal("0.00")

        async def _refund_entry_amount(
            _session: object,
            _settlement_entry: object,
            _order_amount: Decimal,
            refund_amount: Decimal,
            _full_refund: bool,
        ) -> Decimal:
            return refund_amount

        async def _get_entry_by_key(_session: object, _key: str) -> None:
            return None

        async def _get_account_for_update(_session: object, account_id: int) -> object:
            self.assertEqual(61, account_id)
            return account

        async def _settlement_entry_released(_session: object, _settlement_entry: object) -> bool:
            return True

        self.service._get_refundable_settlement_entries = _get_refundable_settlement_entries
        self.service._get_refund_by_key = _get_refund_by_key
        self.service._completed_refund_amount = _completed_refund_amount
        self.service._refund_entry_amount = _refund_entry_amount
        self.service._get_entry_by_key = _get_entry_by_key
        self.service._get_account_for_update = _get_account_for_update
        self.service._settlement_entry_released = _settlement_entry_released

        result = await self.service.refund_platform_order(session, "ORD41", amount=Decimal("30.00"))

        self.assertTrue(result.created)
        self.assertEqual(Decimal("30.00"), result.amount)
        self.assertEqual(1, result.reversed_entry_count)
        self.assertEqual("partially_refunded", order.status)
        self.assertEqual(Decimal("-30.00"), account.available_balance)
        refund_entries = [
            item
            for item in session.added
            if item.__class__.__name__ == "LedgerEntry" and item.entry_type == "refund"
        ]
        self.assertEqual(1, len(refund_entries))
        self.assertEqual("refunded_available", refund_entries[0].status)
        self.assertEqual(Decimal("30.00"), refund_entries[0].amount)

    def test_compute_balances_from_entries_covers_settlement_refund_and_withdrawal_completion(self) -> None:
        entries = [
            SimpleNamespace(
                entry_type="order_settlement",
                direction="credit",
                status="pending",
                amount=Decimal("100.00"),
            ),
            SimpleNamespace(
                entry_type="refund",
                direction="debit",
                status="refunded_pending",
                amount=Decimal("20.00"),
            ),
            SimpleNamespace(
                entry_type="settlement_available",
                direction="credit",
                status="available",
                amount=Decimal("80.00"),
            ),
            SimpleNamespace(
                entry_type="withdrawal_freeze",
                direction="debit",
                status="frozen",
                amount=Decimal("30.00"),
            ),
            SimpleNamespace(
                entry_type="withdrawal_completed",
                direction="debit",
                status="withdrawn",
                amount=Decimal("30.00"),
            ),
        ]

        pending_balance, available_balance, frozen_balance = self.service._compute_balances_from_entries(entries)

        self.assertEqual(Decimal("0.00"), pending_balance)
        self.assertEqual(Decimal("50.00"), available_balance)
        self.assertEqual(Decimal("0.00"), frozen_balance)

    def test_compute_balances_from_entries_covers_available_refund_and_withdrawal_rejection(self) -> None:
        entries = [
            SimpleNamespace(
                entry_type="order_settlement",
                direction="credit",
                status="pending",
                amount=Decimal("100.00"),
            ),
            SimpleNamespace(
                entry_type="settlement_available",
                direction="credit",
                status="available",
                amount=Decimal("100.00"),
            ),
            SimpleNamespace(
                entry_type="refund",
                direction="debit",
                status="refunded_available",
                amount=Decimal("15.00"),
            ),
            SimpleNamespace(
                entry_type="withdrawal_freeze",
                direction="debit",
                status="frozen",
                amount=Decimal("25.00"),
            ),
            SimpleNamespace(
                entry_type="withdrawal_rejected",
                direction="credit",
                status="available",
                amount=Decimal("25.00"),
            ),
        ]

        pending_balance, available_balance, frozen_balance = self.service._compute_balances_from_entries(entries)

        self.assertEqual(Decimal("0.00"), pending_balance)
        self.assertEqual(Decimal("85.00"), available_balance)
        self.assertEqual(Decimal("0.00"), frozen_balance)

    def test_compute_balances_from_entries_can_express_refund_recovery_after_completed_withdrawal(self) -> None:
        entries = [
            SimpleNamespace(
                entry_type="order_settlement",
                direction="credit",
                status="pending",
                amount=Decimal("100.00"),
            ),
            SimpleNamespace(
                entry_type="settlement_available",
                direction="credit",
                status="available",
                amount=Decimal("100.00"),
            ),
            SimpleNamespace(
                entry_type="withdrawal_freeze",
                direction="debit",
                status="frozen",
                amount=Decimal("100.00"),
            ),
            SimpleNamespace(
                entry_type="withdrawal_completed",
                direction="debit",
                status="withdrawn",
                amount=Decimal("100.00"),
            ),
            SimpleNamespace(
                entry_type="refund",
                direction="debit",
                status="refunded_available",
                amount=Decimal("30.00"),
            ),
        ]

        pending_balance, available_balance, frozen_balance = self.service._compute_balances_from_entries(entries)

        self.assertEqual(Decimal("0.00"), pending_balance)
        self.assertEqual(Decimal("-30.00"), available_balance)
        self.assertEqual(Decimal("0.00"), frozen_balance)

    def test_released_refund_allows_negative_available_balance_as_recoupment_signal(self) -> None:
        account = SimpleNamespace(available_balance=Decimal("10.00"))

        status = self.service._apply_released_refund(account, Decimal("15.00"))

        self.assertEqual("refunded_available", status)
        self.assertEqual(Decimal("-5.00"), account.available_balance)

    def test_balance_audit_reports_differences(self) -> None:
        audit = self.service._balance_audit_from_values(
            tenant_id=7,
            account_id=9,
            account_type="main",
            currency="USDT",
            stored_pending_balance=Decimal("1.00"),
            stored_available_balance=Decimal("2.00"),
            stored_frozen_balance=Decimal("3.00"),
            computed_pending_balance=Decimal("1.00"),
            computed_available_balance=Decimal("2.50"),
            computed_frozen_balance=Decimal("2.00"),
        )

        self.assertFalse(audit.is_balanced)
        self.assertEqual(Decimal("0.00"), audit.pending_difference)
        self.assertEqual(Decimal("0.50"), audit.available_difference)
        self.assertEqual(Decimal("-1.00"), audit.frozen_difference)


if __name__ == "__main__":
    unittest.main()
