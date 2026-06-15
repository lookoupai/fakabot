from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.orders import TRC20_DIRECT_TRANSFER_MATCH_STATUSES, Trc20DirectTransfer
from app.services.payments.trc20_direct import normalize_tron_tx_hash


@dataclass(frozen=True)
class Trc20DirectTransferSummary:
    tx_hash: str
    block_number: int
    timestamp_ms: int
    block_timestamp: Optional[datetime]
    from_address_masked: str
    to_address_masked: str
    contract_address: str
    amount: Decimal
    confirmations: int
    match_status: str
    out_trade_no: Optional[str]
    matched_at: Optional[datetime]
    created_at: datetime


class Trc20DirectTransferObservationService:
    async def list_tenant_transfers(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        match_status: Optional[str] = None,
        out_trade_no: Optional[str] = None,
        tx_hash: Optional[str] = None,
        limit: int = 20,
    ) -> list[Trc20DirectTransferSummary]:
        normalized_status = self._normalize_match_status(match_status)
        normalized_out_trade_no = self._normalize_optional_text(out_trade_no, "out_trade_no", max_length=96)
        normalized_tx_hash = normalize_tron_tx_hash(tx_hash) if tx_hash else None
        normalized_limit = self._normalize_limit(limit)

        query = (
            select(Trc20DirectTransfer)
            .where(Trc20DirectTransfer.tenant_id == tenant_id)
            .order_by(Trc20DirectTransfer.created_at.desc(), Trc20DirectTransfer.id.desc())
            .limit(normalized_limit)
        )
        if normalized_status is not None:
            query = query.where(Trc20DirectTransfer.match_status == normalized_status)
        if normalized_out_trade_no is not None:
            query = query.where(Trc20DirectTransfer.out_trade_no == normalized_out_trade_no)
        if normalized_tx_hash is not None:
            query = query.where(Trc20DirectTransfer.tx_hash == normalized_tx_hash)

        result = await session.execute(query)
        return [self._to_summary(row) for row in result.scalars().all()]

    def _to_summary(self, transfer: Trc20DirectTransfer) -> Trc20DirectTransferSummary:
        return Trc20DirectTransferSummary(
            tx_hash=transfer.tx_hash,
            block_number=transfer.block_number,
            timestamp_ms=transfer.timestamp_ms,
            block_timestamp=transfer.block_timestamp,
            from_address_masked=self._mask_address(transfer.from_address),
            to_address_masked=self._mask_address(transfer.to_address),
            contract_address=transfer.contract_address,
            amount=transfer.amount,
            confirmations=transfer.confirmations,
            match_status=transfer.match_status,
            out_trade_no=transfer.out_trade_no,
            matched_at=transfer.matched_at,
            created_at=transfer.created_at,
        )

    @staticmethod
    def _normalize_match_status(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized not in TRC20_DIRECT_TRANSFER_MATCH_STATUSES:
            raise ValueError("TRC20 直付匹配状态无效")
        return normalized

    @staticmethod
    def _normalize_optional_text(value: Optional[str], field_name: str, *, max_length: int) -> Optional[str]:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        if len(normalized) > max_length:
            raise ValueError(f"{field_name} 不能超过 {max_length} 个字符")
        if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
            raise ValueError(f"{field_name} 不能包含控制字符")
        return normalized

    @staticmethod
    def _normalize_limit(limit: int) -> int:
        if limit < 1:
            return 1
        return min(limit, 100)

    @staticmethod
    def _mask_address(value: str) -> str:
        if len(value) <= 12:
            return "***"
        return f"{value[:6]}***{value[-6:]}"
