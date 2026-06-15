from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.orders import Order, Payment, Trc20DirectTransfer
from app.services.payments.configs import USDT_TRC20_DIRECT_PROVIDER
from app.services.payments.trc20_direct import (
    TronUsdtPaymentCandidate,
    TronUsdtTransfer,
    match_tron_usdt_transfer,
    normalize_tron_tx_hash,
    trc20_usdt_amount_to_raw,
)


TRC20_DIRECT_RECONCILE_UNMATCHED_STATUSES = (
    "not_confirmed",
    "no_candidate",
    "address_mismatch",
    "amount_mismatch",
    "outside_time_window",
    "ambiguous",
    "invalid",
)


@dataclass(frozen=True)
class Trc20DirectReconcileResult:
    tx_hash: str
    match_status: str
    confirmations: int
    out_trade_no: Optional[str] = None
    order_id: Optional[int] = None
    payment_id: Optional[int] = None


@dataclass(frozen=True)
class _PendingCandidate:
    candidate: TronUsdtPaymentCandidate
    payment: Any
    order: Any


class Trc20DirectReconcileService:
    async def record_transfer(
        self,
        session: AsyncSession,
        transfer: TronUsdtTransfer,
        *,
        tenant_id: Optional[int] = None,
        latest_block_number: int,
        required_confirmations: int = 1,
        candidates: Optional[Iterable[Any]] = None,
    ) -> Trc20DirectTransfer | Trc20DirectReconcileResult:
        return await self.record_and_match_transfer(
            session,
            transfer,
            tenant_id=tenant_id,
            latest_block_number=latest_block_number,
            required_confirmations=required_confirmations,
            candidates=candidates,
        )

    async def reconcile_transfer(
        self,
        session: AsyncSession,
        transfer: TronUsdtTransfer,
        *,
        tenant_id: Optional[int] = None,
        latest_block_number: int,
        required_confirmations: int = 1,
        candidates: Optional[Iterable[Any]] = None,
    ) -> Trc20DirectTransfer | Trc20DirectReconcileResult:
        return await self.record_and_match_transfer(
            session,
            transfer,
            tenant_id=tenant_id,
            latest_block_number=latest_block_number,
            required_confirmations=required_confirmations,
            candidates=candidates,
        )

    async def match_pending_payment(
        self,
        session: AsyncSession,
        transfer: TronUsdtTransfer,
        *,
        tenant_id: Optional[int] = None,
        latest_block_number: int,
        required_confirmations: int = 1,
        candidates: Optional[Iterable[Any]] = None,
    ) -> Trc20DirectTransfer | Trc20DirectReconcileResult:
        return await self.record_and_match_transfer(
            session,
            transfer,
            tenant_id=tenant_id,
            latest_block_number=latest_block_number,
            required_confirmations=required_confirmations,
            candidates=candidates,
        )

    async def record_and_match_transfer(
        self,
        session: AsyncSession,
        transfer: TronUsdtTransfer,
        *,
        tenant_id: Optional[int] = None,
        latest_block_number: int,
        required_confirmations: int = 1,
        candidates: Optional[Iterable[Any]] = None,
    ) -> Trc20DirectTransfer | Trc20DirectReconcileResult:
        transfer = _require_transfer(transfer)
        tx_hash = normalize_tron_tx_hash(transfer.tx_hash)
        if tx_hash != transfer.tx_hash:
            transfer = replace(transfer, tx_hash=tx_hash)

        existing = await self._get_existing_transfer(session, tx_hash)
        confirmations = max(0, latest_block_number - transfer.block_number)
        if existing is not None:
            return Trc20DirectReconcileResult(
                tx_hash=tx_hash,
                match_status="duplicate_tx",
                confirmations=confirmations,
                out_trade_no=getattr(existing, "out_trade_no", None),
                order_id=getattr(existing, "order_id", None),
                payment_id=getattr(existing, "payment_id", None),
            )

        pending_candidates = await self._load_pending_candidates(
            session,
            transfer,
            tenant_id=tenant_id,
            candidate_rows=candidates,
        )
        effective_tenant_id = _resolve_tenant_id(tenant_id, pending_candidates)
        decision = match_tron_usdt_transfer(
            transfer,
            [pending.candidate for pending in pending_candidates],
            latest_block_number=latest_block_number,
            required_confirmations=required_confirmations,
        )

        now = datetime.now(timezone.utc)
        transfer_row = Trc20DirectTransfer(
            tenant_id=effective_tenant_id,
            tx_hash=tx_hash,
            block_number=transfer.block_number,
            timestamp_ms=transfer.timestamp_ms,
            block_timestamp=_datetime_from_ms(transfer.timestamp_ms),
            from_address=transfer.from_address,
            to_address=transfer.to_address,
            contract_address=transfer.contract_address,
            raw_amount=transfer.raw_amount,
            amount=transfer.amount,
            confirmations=decision.confirmations,
            match_status=decision.reason,
            failure_reason=None if decision.matched else decision.reason,
        )

        if decision.matched and decision.out_trade_no is not None:
            matched = _find_pending_candidate(pending_candidates, decision.out_trade_no)
            if matched is not None:
                self._mark_paid(matched.payment, matched.order, tx_hash, now)
                transfer_row.order_id = getattr(matched.order, "id", None)
                transfer_row.payment_id = getattr(matched.payment, "id", None)
                transfer_row.out_trade_no = decision.out_trade_no
                transfer_row.matched_at = now
                transfer_row.failure_reason = None

        session.add(transfer_row)
        await session.flush()
        return transfer_row

    async def _get_existing_transfer(self, session: AsyncSession, tx_hash: str) -> Any:
        result = await session.execute(select(Trc20DirectTransfer).where(Trc20DirectTransfer.tx_hash == tx_hash))
        return result.scalar_one_or_none()

    async def _load_pending_candidates(
        self,
        session: AsyncSession,
        transfer: TronUsdtTransfer,
        *,
        tenant_id: Optional[int],
        candidate_rows: Optional[Iterable[Any]],
    ) -> list[_PendingCandidate]:
        rows = list(candidate_rows) if candidate_rows is not None else await self._query_pending_candidate_rows(
            session,
            transfer,
            tenant_id=tenant_id,
        )
        candidates: list[_PendingCandidate] = []
        for row in rows:
            pending = _pending_candidate_from_row(row, transfer)
            if pending is None:
                continue
            if tenant_id is not None and getattr(pending.order, "tenant_id", getattr(pending.payment, "tenant_id", None)) != tenant_id:
                continue
            candidates.append(pending)
        return candidates

    async def _query_pending_candidate_rows(
        self,
        session: AsyncSession,
        transfer: TronUsdtTransfer,
        *,
        tenant_id: Optional[int],
    ) -> list[Any]:
        query = (
            select(Payment, Order)
            .join(Order, Payment.order_id == Order.id)
            .where(Payment.provider == USDT_TRC20_DIRECT_PROVIDER)
            .where(Payment.status == "pending")
            .where(Order.status == "pending")
            .where(Payment.currency == "USDT")
            .where(Payment.amount == transfer.amount)
        )
        if tenant_id is not None:
            query = query.where(Order.tenant_id == tenant_id)
        result = await session.execute(query)
        return list(result.all())

    @staticmethod
    def _mark_paid(payment: Any, order: Any, tx_hash: str, now: datetime) -> None:
        payment.status = "paid"
        payment.provider = USDT_TRC20_DIRECT_PROVIDER
        payment.provider_trade_no = tx_hash
        payment.paid_at = getattr(payment, "paid_at", None) or now
        order.status = "paid"
        order.payment_provider = USDT_TRC20_DIRECT_PROVIDER
        order.payment_mode = "tenant_direct"
        order.paid_at = getattr(order, "paid_at", None) or now


def _require_transfer(transfer: TronUsdtTransfer) -> TronUsdtTransfer:
    if not isinstance(transfer, TronUsdtTransfer):
        raise ValueError("transfer 必须是 TronUsdtTransfer")
    return transfer


def _pending_candidate_from_row(row: Any, transfer: TronUsdtTransfer) -> Optional[_PendingCandidate]:
    payment = _row_value(row, "payment", 0)
    order = _row_value(row, "order", 1)
    if payment is None or order is None:
        return None

    out_trade_no = _row_value(row, "out_trade_no", None) or getattr(order, "out_trade_no", None)
    monitor_address = _row_value(row, "monitor_address", 2) or getattr(payment, "monitor_address", None) or transfer.to_address
    expected_raw_amount = _row_value(row, "expected_raw_amount", None)
    if expected_raw_amount is None:
        expected_raw_amount = trc20_usdt_amount_to_raw(getattr(payment, "amount", getattr(order, "amount", Decimal("0"))))
    created_at_ms = _row_value(row, "created_at_ms", None)
    if created_at_ms is None:
        created_at_ms = _datetime_to_ms(getattr(order, "created_at", None))
    expires_at_ms = _row_value(row, "expires_at_ms", None)
    if expires_at_ms is None:
        expires_at_ms = _datetime_to_ms(getattr(order, "expires_at", None))
    return _PendingCandidate(
        candidate=TronUsdtPaymentCandidate(
            out_trade_no=out_trade_no,
            monitor_address=monitor_address,
            expected_raw_amount=expected_raw_amount,
            created_at_ms=created_at_ms,
            expires_at_ms=expires_at_ms,
        ),
        payment=payment,
        order=order,
    )


def _row_value(row: Any, attr_name: str, index: Optional[int]) -> Any:
    value = getattr(row, attr_name, None)
    if value is not None:
        return value
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        for key in (attr_name, attr_name.capitalize()):
            if key in mapping:
                return mapping[key]
    if index is None:
        return None
    try:
        return row[index]
    except (IndexError, KeyError, TypeError):
        return None


def _resolve_tenant_id(tenant_id: Optional[int], candidates: list[_PendingCandidate]) -> int:
    if tenant_id is not None:
        return tenant_id
    for pending in candidates:
        resolved = getattr(pending.order, "tenant_id", None) or getattr(pending.payment, "tenant_id", None)
        if resolved is not None:
            return int(resolved)
    raise ValueError("tenant_id 不能为空")


def _find_pending_candidate(candidates: list[_PendingCandidate], out_trade_no: str) -> Optional[_PendingCandidate]:
    for pending in candidates:
        if pending.candidate.out_trade_no == out_trade_no:
            return pending
    return None


def _datetime_to_ms(value: Any) -> int:
    if value is None:
        return 0
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1000)


def _datetime_from_ms(timestamp_ms: int) -> datetime:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
