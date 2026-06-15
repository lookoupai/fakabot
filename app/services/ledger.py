from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models.ledger import LedgerAccount, LedgerEntry, Refund, SettlementPolicy, WithdrawalRequest
from app.db.models.orders import Order, Payment
from app.db.models.tenants import AuditLog, Tenant

AMOUNT_QUANT = Decimal("0.00000001")
PERCENT_QUANT = Decimal("0.0001")


@dataclass
class LedgerBalance:
    tenant_id: int
    account_type: str
    currency: str
    pending_balance: Decimal
    available_balance: Decimal
    frozen_balance: Decimal


@dataclass
class LedgerBalanceAudit:
    tenant_id: int
    account_id: Optional[int]
    account_type: str
    currency: str
    stored_pending_balance: Decimal
    stored_available_balance: Decimal
    stored_frozen_balance: Decimal
    computed_pending_balance: Decimal
    computed_available_balance: Decimal
    computed_frozen_balance: Decimal

    @property
    def pending_difference(self) -> Decimal:
        return self.computed_pending_balance - self.stored_pending_balance

    @property
    def available_difference(self) -> Decimal:
        return self.computed_available_balance - self.stored_available_balance

    @property
    def frozen_difference(self) -> Decimal:
        return self.computed_frozen_balance - self.stored_frozen_balance

    @property
    def is_balanced(self) -> bool:
        return (
            self.pending_difference == 0
            and self.available_difference == 0
            and self.frozen_difference == 0
        )


@dataclass
class WithdrawalSummary:
    withdrawal_id: int
    tenant_id: int
    amount: Decimal
    currency: str
    network: str
    address: str
    status: str
    requested_at: datetime
    payout_reference: Optional[str] = None
    payout_proof_url: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class LedgerSettlementResult:
    created: bool
    available_at: datetime
    platform_fee_amount: Decimal = Decimal("0")


@dataclass
class RefundResult:
    created: bool
    refund_id: int
    out_trade_no: str
    amount: Decimal
    currency: str
    reversed_entry_count: int


@dataclass
class SettlementPolicySummary:
    scope_type: str
    tenant_id: Optional[int]
    freeze_days: int
    platform_fee_enabled: bool
    platform_fee_percent: Decimal


class LedgerService:
    async def get_or_create_account(
        self,
        session: AsyncSession,
        tenant_id: int,
        account_type: str = "main",
        currency: str = "USDT",
        for_update: bool = False,
    ) -> LedgerAccount:
        query = (
            select(LedgerAccount)
            .where(LedgerAccount.tenant_id == tenant_id)
            .where(LedgerAccount.account_type == account_type)
            .where(LedgerAccount.currency == currency)
        )
        if for_update:
            query = query.with_for_update()
        account = (await session.execute(query)).scalar_one_or_none()
        if account is not None:
            return account
        account = LedgerAccount(
            tenant_id=tenant_id,
            account_type=account_type,
            currency=currency,
            status="active",
            pending_balance=Decimal("0"),
            available_balance=Decimal("0"),
            frozen_balance=Decimal("0"),
        )
        session.add(account)
        await session.flush()
        return account

    async def get_balance(
        self,
        session: AsyncSession,
        tenant_id: int,
        account_type: str = "main",
        currency: str = "USDT",
    ) -> LedgerBalance:
        account = await self.get_or_create_account(session, tenant_id, account_type, currency)
        return LedgerBalance(
            tenant_id=tenant_id,
            account_type=account.account_type,
            currency=account.currency,
            pending_balance=account.pending_balance,
            available_balance=account.available_balance,
            frozen_balance=account.frozen_balance,
        )

    async def audit_account_balance(
        self,
        session: AsyncSession,
        tenant_id: int,
        account_type: str = "main",
        currency: str = "USDT",
    ) -> LedgerBalanceAudit:
        account = (
            await session.execute(
                select(LedgerAccount)
                .where(LedgerAccount.tenant_id == tenant_id)
                .where(LedgerAccount.account_type == account_type)
                .where(LedgerAccount.currency == currency)
            )
        ).scalar_one_or_none()
        if account is None:
            return self._balance_audit_from_values(
                tenant_id=tenant_id,
                account_id=None,
                account_type=account_type,
                currency=currency,
                stored_pending_balance=Decimal("0"),
                stored_available_balance=Decimal("0"),
                stored_frozen_balance=Decimal("0"),
                computed_pending_balance=Decimal("0"),
                computed_available_balance=Decimal("0"),
                computed_frozen_balance=Decimal("0"),
            )

        entries = (
            await session.execute(
                select(LedgerEntry)
                .where(LedgerEntry.account_id == account.id)
                .order_by(LedgerEntry.id.asc())
            )
        ).scalars().all()
        pending_balance, available_balance, frozen_balance = self._compute_balances_from_entries(entries)
        return self._balance_audit_from_values(
            tenant_id=tenant_id,
            account_id=account.id,
            account_type=account.account_type,
            currency=account.currency,
            stored_pending_balance=account.pending_balance,
            stored_available_balance=account.available_balance,
            stored_frozen_balance=account.frozen_balance,
            computed_pending_balance=pending_balance,
            computed_available_balance=available_balance,
            computed_frozen_balance=frozen_balance,
        )

    async def create_withdrawal_request(
        self,
        session: AsyncSession,
        tenant_id: int,
        amount: Decimal,
        address: str,
        network: str,
        currency: str = "USDT",
        actor_user_id: Optional[int] = None,
    ) -> WithdrawalRequest:
        if amount <= 0:
            raise ValueError("提现金额必须大于 0")
        account = await self.get_or_create_account(session, tenant_id, currency=currency, for_update=True)
        if account.status != "active":
            raise ValueError("账本账户不可用")
        if account.available_balance < amount:
            raise ValueError("可用余额不足")

        account.available_balance -= amount
        account.frozen_balance += amount
        withdrawal = WithdrawalRequest(
            tenant_id=tenant_id,
            currency=currency,
            amount=amount,
            address=address,
            network=network,
            status="pending",
        )
        session.add(withdrawal)
        await session.flush()
        self._add_entry(
            session=session,
            account=account,
            withdrawal_id=withdrawal.id,
            entry_type="withdrawal_freeze",
            direction="debit",
            amount=amount,
            status="frozen",
            idempotency_key=f"withdrawal:{withdrawal.id}:freeze",
        )
        self._add_withdrawal_audit(
            session=session,
            withdrawal=withdrawal,
            action="ledger.withdrawal_requested",
            actor_user_id=actor_user_id,
            old_status=None,
            new_status="pending",
            note=None,
        )
        await session.flush()
        return withdrawal

    async def record_order_settlement(
        self,
        session: AsyncSession,
        order: Order,
    ) -> LedgerSettlementResult:
        if order.source_type != "self":
            raise ValueError("只有自营订单可以进入租户账本")
        if order.payment_mode != "platform_escrow":
            raise ValueError("只有平台托管收款订单可以进入租户账本")
        if order.amount <= 0:
            raise ValueError("订单金额必须大于 0")

        policy = await self._effective_settlement_policy(session, order.tenant_id)
        platform_fee_amount = self._platform_fee_amount(order.amount, policy)
        merchant_amount = order.amount - platform_fee_amount
        if merchant_amount <= 0:
            raise ValueError("扣除平台手续费后结算金额必须大于 0")

        account = await self.get_or_create_account(session, order.tenant_id, currency=order.currency, for_update=True)
        if account.status != "active":
            raise ValueError("账本账户不可用")

        available_at = order.settlement_available_at
        if available_at is None:
            paid_at = order.paid_at or datetime.now(timezone.utc)
            available_at = paid_at + timedelta(days=policy.freeze_days)
            order.settlement_available_at = available_at

        idempotency_key = f"order:{order.id}:tenant:{order.tenant_id}:settlement_pending"
        existing_entry = await self._get_entry_by_key(session, idempotency_key)
        if existing_entry is not None:
            return LedgerSettlementResult(created=False, available_at=available_at, platform_fee_amount=platform_fee_amount)

        account.pending_balance += merchant_amount
        self._add_entry(
            session=session,
            account=account,
            entry_type="order_settlement",
            direction="credit",
            amount=merchant_amount,
            status="pending",
            idempotency_key=idempotency_key,
            order_id=order.id,
            available_at=available_at,
        )
        self._add_platform_fee_audit(
            session=session,
            tenant_id=order.tenant_id,
            order=order,
            gross_amount=order.amount,
            platform_fee_amount=platform_fee_amount,
            policy=policy,
        )
        await session.flush()
        return LedgerSettlementResult(created=True, available_at=available_at, platform_fee_amount=platform_fee_amount)

    async def record_reseller_order_settlement(
        self,
        session: AsyncSession,
        order: Order,
        supplier_amount: Decimal,
        reseller_amount: Decimal,
    ) -> LedgerSettlementResult:
        if order.source_type != "reseller":
            raise ValueError("只有代理订单可以进入代理分账")
        if order.payment_mode != "platform_escrow":
            raise ValueError("代理订单必须使用平台托管收款")
        if order.supplier_tenant_id is None:
            raise ValueError("代理订单缺少供应商租户")
        if supplier_amount <= 0:
            raise ValueError("供应商结算金额必须大于 0")
        if reseller_amount < 0:
            raise ValueError("代理商结算金额不能小于 0")
        if supplier_amount + reseller_amount != order.amount:
            raise ValueError("代理分账金额与订单金额不一致")

        supplier_policy = await self._effective_settlement_policy(session, order.supplier_tenant_id)
        reseller_policy = await self._effective_settlement_policy(session, order.tenant_id)
        supplier_fee_amount = self._platform_fee_amount(supplier_amount, supplier_policy)
        reseller_fee_amount = self._platform_fee_amount(reseller_amount, reseller_policy) if reseller_amount > 0 else Decimal("0")
        supplier_settlement_amount = supplier_amount - supplier_fee_amount
        reseller_settlement_amount = reseller_amount - reseller_fee_amount
        if supplier_settlement_amount <= 0:
            raise ValueError("扣除平台手续费后供应商结算金额必须大于 0")
        if reseller_amount > 0 and reseller_settlement_amount <= 0:
            raise ValueError("扣除平台手续费后代理商结算金额必须大于 0")

        paid_at = order.paid_at or datetime.now(timezone.utc)
        supplier_available_at = paid_at + timedelta(days=supplier_policy.freeze_days)
        reseller_available_at = paid_at + timedelta(days=reseller_policy.freeze_days)
        available_at = max(supplier_available_at, reseller_available_at)
        if order.settlement_available_at is None:
            order.settlement_available_at = available_at

        supplier_key = f"order:{order.id}:tenant:{order.supplier_tenant_id}:supplier_settlement_pending"
        reseller_key = f"order:{order.id}:tenant:{order.tenant_id}:reseller_settlement_pending"
        created = False
        total_platform_fee_amount = Decimal("0")

        if await self._get_entry_by_key(session, supplier_key) is None:
            supplier_account = await self.get_or_create_account(
                session=session,
                tenant_id=order.supplier_tenant_id,
                currency=order.currency,
                for_update=True,
            )
            if supplier_account.status != "active":
                raise ValueError("供应商账本账户不可用")
            supplier_account.pending_balance += supplier_settlement_amount
            self._add_entry(
                session=session,
                account=supplier_account,
                entry_type="supplier_order_settlement",
                direction="credit",
                amount=supplier_settlement_amount,
                status="pending",
                idempotency_key=supplier_key,
                order_id=order.id,
                available_at=supplier_available_at,
            )
            self._add_platform_fee_audit(
                session=session,
                tenant_id=order.supplier_tenant_id,
                order=order,
                gross_amount=supplier_amount,
                platform_fee_amount=supplier_fee_amount,
                policy=supplier_policy,
            )
            total_platform_fee_amount += supplier_fee_amount
            created = True

        if reseller_settlement_amount > 0 and await self._get_entry_by_key(session, reseller_key) is None:
            reseller_account = await self.get_or_create_account(
                session=session,
                tenant_id=order.tenant_id,
                currency=order.currency,
                for_update=True,
            )
            if reseller_account.status != "active":
                raise ValueError("代理商账本账户不可用")
            reseller_account.pending_balance += reseller_settlement_amount
            self._add_entry(
                session=session,
                account=reseller_account,
                entry_type="reseller_order_settlement",
                direction="credit",
                amount=reseller_settlement_amount,
                status="pending",
                idempotency_key=reseller_key,
                order_id=order.id,
                available_at=reseller_available_at,
            )
            self._add_platform_fee_audit(
                session=session,
                tenant_id=order.tenant_id,
                order=order,
                gross_amount=reseller_amount,
                platform_fee_amount=reseller_fee_amount,
                policy=reseller_policy,
            )
            total_platform_fee_amount += reseller_fee_amount
            created = True

        await session.flush()
        return LedgerSettlementResult(
            created=created,
            available_at=available_at,
            platform_fee_amount=total_platform_fee_amount,
        )

    async def get_effective_settlement_policy(
        self,
        session: AsyncSession,
        tenant_id: Optional[int] = None,
    ) -> SettlementPolicySummary:
        if tenant_id is None:
            policy = await self._get_settlement_policy(session, "platform", None)
            if policy is None:
                return SettlementPolicySummary(
                    scope_type="platform",
                    tenant_id=None,
                    freeze_days=7,
                    platform_fee_enabled=False,
                    platform_fee_percent=Decimal("1.0000"),
                )
            return self._policy_summary(policy)
        return self._policy_summary(await self._effective_settlement_policy(session, tenant_id))

    async def set_platform_fee_policy(
        self,
        session: AsyncSession,
        actor_user_id: int,
        enabled: bool,
        platform_fee_percent: Decimal,
        tenant_id: Optional[int] = None,
    ) -> SettlementPolicySummary:
        normalized_percent = self._normalize_fee_percent(platform_fee_percent)
        scope_type = "tenant" if tenant_id is not None else "platform"
        if tenant_id is not None and await session.get(Tenant, tenant_id) is None:
            raise ValueError("租户不存在")

        policy = await self._get_settlement_policy(session, scope_type, tenant_id)
        if policy is None:
            inherited_freeze_days = 7
            if tenant_id is not None:
                inherited_freeze_days = (await self._effective_settlement_policy(session, tenant_id)).freeze_days
            policy = SettlementPolicy(
                scope_type=scope_type,
                tenant_id=tenant_id,
                freeze_days=inherited_freeze_days,
                platform_fee_enabled=enabled,
                platform_fee_percent=normalized_percent,
            )
            session.add(policy)
        else:
            policy.platform_fee_enabled = enabled
            policy.platform_fee_percent = normalized_percent

        session.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                action="settlement_policy.platform_fee_updated",
                target_type="settlement_policy",
                target_id=scope_type if tenant_id is None else f"tenant:{tenant_id}",
                metadata_json={
                    "scope_type": scope_type,
                    "tenant_id": tenant_id,
                    "platform_fee_enabled": enabled,
                    "platform_fee_percent": str(normalized_percent),
                },
            )
        )
        await session.flush()
        return self._policy_summary(policy)

    async def refund_platform_order(
        self,
        session: AsyncSession,
        out_trade_no: str,
        reason: Optional[str] = None,
        amount: Optional[Decimal] = None,
        idempotency_key: Optional[str] = None,
    ) -> RefundResult:
        result = await session.execute(
            select(Order)
            .where(Order.out_trade_no == out_trade_no)
            .with_for_update()
        )
        order = result.scalar_one_or_none()
        if order is None:
            raise ValueError("订单不存在")
        if order.payment_mode != "platform_escrow":
            raise ValueError("只有平台托管收款订单支持平台退款")
        if order.source_type not in {"self", "reseller"}:
            raise ValueError("当前订单类型不支持账本退款")
        refund_key = idempotency_key or self._refund_key(order)
        if order.status == "refunded":
            existing_refund = await self._get_refund_by_key(session, order.id, refund_key)
            if existing_refund is None:
                raise ValueError("订单已全额退款")
            return RefundResult(
                created=False,
                refund_id=existing_refund.id,
                out_trade_no=order.out_trade_no,
                amount=existing_refund.amount,
                currency=existing_refund.currency,
                reversed_entry_count=0,
            )
        if order.status not in {"paid", "delivered", "completed", "partially_refunded"}:
            raise ValueError("只有已支付、已发货或已完成订单可以退款")

        settlement_entries = await self._get_refundable_settlement_entries(session, order.id)
        if not settlement_entries:
            raise ValueError("订单没有可冲正的账本分录")

        existing_refund = await self._get_refund_by_key(session, order.id, refund_key)
        if existing_refund is not None:
            return RefundResult(
                created=False,
                refund_id=existing_refund.id,
                out_trade_no=order.out_trade_no,
                amount=existing_refund.amount,
                currency=existing_refund.currency,
                reversed_entry_count=0,
            )

        previous_refund_amount = await self._completed_refund_amount(session, order.id)
        refund_amount = self._normalize_refund_amount(order, previous_refund_amount, amount)
        full_refund = previous_refund_amount + refund_amount >= order.amount
        now = datetime.now(timezone.utc)
        refund = Refund(
            tenant_id=order.tenant_id,
            order_id=order.id,
            amount=refund_amount,
            currency=order.currency,
            reason=reason,
            status="completed",
            idempotency_key=refund_key,
            processed_at=now,
        )
        session.add(refund)
        await session.flush()

        reversed_entry_count = 0
        for settlement_entry in settlement_entries:
            if settlement_entry.amount <= 0:
                continue
            reverse_amount = await self._refund_entry_amount(
                session,
                settlement_entry,
                order.amount,
                refund_amount,
                full_refund,
            )
            if reverse_amount <= 0:
                continue
            reverse_key = f"refund:{refund.id}:ledger_entry:{settlement_entry.id}:reverse"
            if await self._get_entry_by_key(session, reverse_key) is not None:
                continue

            account = await self._get_account_for_update(session, settlement_entry.account_id)
            if account is None:
                raise ValueError("账本账户不存在")

            released = await self._settlement_entry_released(session, settlement_entry)
            if released:
                status = self._apply_released_refund(account, reverse_amount)
            else:
                if account.pending_balance < reverse_amount:
                    raise ValueError("待结算余额不足，不能退款")
                account.pending_balance -= reverse_amount
                status = "refunded_pending"

            self._add_entry(
                session=session,
                account=account,
                entry_type="refund",
                direction="debit",
                amount=reverse_amount,
                status=status,
                idempotency_key=reverse_key,
                order_id=order.id,
            )
            reversed_entry_count += 1

        if full_refund:
            payment_result = await session.execute(
                select(Payment)
                .where(Payment.order_id == order.id)
                .where(Payment.status == "paid")
                .with_for_update()
            )
            for payment in payment_result.scalars().all():
                payment.status = "refunded"
            order.status = "refunded"
        else:
            order.status = "partially_refunded"
        await session.flush()
        return RefundResult(
            created=True,
            refund_id=refund.id,
            out_trade_no=order.out_trade_no,
            amount=refund.amount,
            currency=refund.currency,
            reversed_entry_count=reversed_entry_count,
        )

    async def release_available_settlements(
        self,
        session: AsyncSession,
        limit: int = 500,
        now: Optional[datetime] = None,
    ) -> int:
        current_time = now or datetime.now(timezone.utc)
        pending_entry = aliased(LedgerEntry)
        released_entry = aliased(LedgerEntry)
        release_exists = (
            select(released_entry.id)
            .where(released_entry.idempotency_key == func.concat("ledger_entry:", pending_entry.id, ":settlement_available"))
            .exists()
        )
        result = await session.execute(
            select(pending_entry)
            .where(
                pending_entry.entry_type.in_(
                    (
                        "order_settlement",
                        "supplier_order_settlement",
                        "reseller_order_settlement",
                    )
                )
            )
            .where(pending_entry.status == "pending")
            .where(pending_entry.available_at.is_not(None))
            .where(pending_entry.available_at <= current_time)
            .where(~release_exists)
            .order_by(pending_entry.available_at.asc())
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        entries = list(result.scalars().all())
        released_count = 0
        for entry in entries:
            release_key = f"ledger_entry:{entry.id}:settlement_available"
            if await self._get_entry_by_key(session, release_key) is not None:
                continue

            account = await self._get_account_for_update(session, entry.account_id)
            if account is None:
                raise ValueError("账本账户不存在")
            refunded_amount = await self._refunded_settlement_entry_amount(session, entry)
            release_amount = max(entry.amount - refunded_amount, Decimal("0"))
            if account.pending_balance < release_amount:
                raise ValueError("待结算余额不足，不能释放")

            account.pending_balance -= release_amount
            account.available_balance += release_amount
            self._add_entry(
                session=session,
                account=account,
                entry_type="settlement_available",
                direction="credit",
                amount=release_amount,
                status="available",
                idempotency_key=release_key,
                order_id=entry.order_id,
                available_at=entry.available_at,
            )
            released_count += 1
        await session.flush()
        return released_count

    async def list_pending_withdrawals(
        self,
        session: AsyncSession,
        limit: int = 20,
    ) -> List[WithdrawalSummary]:
        result = await session.execute(
            select(WithdrawalRequest)
            .where(WithdrawalRequest.status == "pending")
            .order_by(WithdrawalRequest.requested_at.asc(), WithdrawalRequest.id.asc())
            .limit(limit)
        )
        return [self._summary(withdrawal) for withdrawal in result.scalars().all()]

    async def list_withdrawals(
        self,
        session: AsyncSession,
        tenant_id: Optional[int] = None,
        limit: int = 20,
    ) -> List[WithdrawalSummary]:
        query = select(WithdrawalRequest).order_by(WithdrawalRequest.requested_at.desc()).limit(limit)
        if tenant_id is not None:
            query = query.where(WithdrawalRequest.tenant_id == tenant_id)
        result = await session.execute(query)
        return [self._summary(withdrawal) for withdrawal in result.scalars().all()]

    async def get_withdrawal(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        withdrawal_id: int,
    ) -> Optional[WithdrawalSummary]:
        result = await session.execute(
            select(WithdrawalRequest)
            .where(WithdrawalRequest.tenant_id == tenant_id)
            .where(WithdrawalRequest.id == withdrawal_id)
        )
        withdrawal = result.scalar_one_or_none()
        if withdrawal is None:
            return None
        return self._summary(withdrawal)

    async def get_platform_withdrawal(
        self,
        session: AsyncSession,
        *,
        withdrawal_id: int,
    ) -> Optional[WithdrawalSummary]:
        result = await session.execute(
            select(WithdrawalRequest)
            .where(WithdrawalRequest.id == withdrawal_id)
        )
        withdrawal = result.scalar_one_or_none()
        if withdrawal is None:
            return None
        return self._summary(withdrawal)

    async def complete_withdrawal(
        self,
        session: AsyncSession,
        withdrawal_id: int,
        admin_note: Optional[str] = None,
        actor_user_id: Optional[int] = None,
        payout_reference: Optional[str] = None,
        payout_proof_url: Optional[str] = None,
    ) -> WithdrawalRequest:
        normalized_admin_note = self._normalize_optional_text(admin_note, "备注", max_length=500)
        normalized_payout_reference = self._normalize_optional_text(payout_reference, "打款流水", max_length=128)
        normalized_payout_proof_url = self._normalize_optional_text(payout_proof_url, "打款凭证链接", max_length=1000)
        withdrawal = await self._get_pending_withdrawal(session, withdrawal_id)
        account = await self.get_or_create_account(
            session,
            withdrawal.tenant_id,
            currency=withdrawal.currency,
            for_update=True,
        )
        if account.frozen_balance < withdrawal.amount:
            raise ValueError("冻结余额不足，不能完成提现")

        now = datetime.now(timezone.utc)
        old_status = withdrawal.status
        account.frozen_balance -= withdrawal.amount
        withdrawal.status = "completed"
        withdrawal.admin_note = normalized_admin_note
        withdrawal.payout_reference = normalized_payout_reference
        withdrawal.payout_proof_url = normalized_payout_proof_url
        withdrawal.reviewed_at = now
        withdrawal.completed_at = now
        self._add_entry(
            session=session,
            account=account,
            withdrawal_id=withdrawal.id,
            entry_type="withdrawal_completed",
            direction="debit",
            amount=withdrawal.amount,
            status="withdrawn",
            idempotency_key=f"withdrawal:{withdrawal.id}:completed",
        )
        self._add_withdrawal_audit(
            session=session,
            withdrawal=withdrawal,
            action="ledger.withdrawal_completed",
            actor_user_id=actor_user_id,
            old_status=old_status,
            new_status="completed",
            note=normalized_admin_note,
        )
        await session.flush()
        return withdrawal

    async def reject_withdrawal(
        self,
        session: AsyncSession,
        withdrawal_id: int,
        admin_note: Optional[str] = None,
        actor_user_id: Optional[int] = None,
    ) -> WithdrawalRequest:
        normalized_admin_note = self._normalize_optional_text(admin_note, "备注", max_length=500)
        withdrawal = await self._get_pending_withdrawal(session, withdrawal_id)
        account = await self.get_or_create_account(
            session,
            withdrawal.tenant_id,
            currency=withdrawal.currency,
            for_update=True,
        )
        if account.frozen_balance < withdrawal.amount:
            raise ValueError("冻结余额不足，不能拒绝提现")

        old_status = withdrawal.status
        account.frozen_balance -= withdrawal.amount
        account.available_balance += withdrawal.amount
        withdrawal.status = "rejected"
        withdrawal.admin_note = normalized_admin_note
        withdrawal.reviewed_at = datetime.now(timezone.utc)
        self._add_entry(
            session=session,
            account=account,
            withdrawal_id=withdrawal.id,
            entry_type="withdrawal_rejected",
            direction="credit",
            amount=withdrawal.amount,
            status="available",
            idempotency_key=f"withdrawal:{withdrawal.id}:rejected",
        )
        self._add_withdrawal_audit(
            session=session,
            withdrawal=withdrawal,
            action="ledger.withdrawal_rejected",
            actor_user_id=actor_user_id,
            old_status=old_status,
            new_status="rejected",
            note=normalized_admin_note,
        )
        await session.flush()
        return withdrawal

    async def _get_pending_withdrawal(self, session: AsyncSession, withdrawal_id: int) -> WithdrawalRequest:
        result = await session.execute(
            select(WithdrawalRequest)
            .where(WithdrawalRequest.id == withdrawal_id)
            .where(WithdrawalRequest.status == "pending")
            .with_for_update()
        )
        withdrawal = result.scalar_one_or_none()
        if withdrawal is None:
            raise ValueError("提现申请不存在或状态不可处理")
        return withdrawal

    def _add_entry(
        self,
        session: AsyncSession,
        account: LedgerAccount,
        entry_type: str,
        direction: str,
        amount: Decimal,
        status: str,
        idempotency_key: str,
        order_id: Optional[int] = None,
        withdrawal_id: Optional[int] = None,
        available_at: Optional[datetime] = None,
    ) -> None:
        session.add(
            LedgerEntry(
                account_id=account.id,
                tenant_id=account.tenant_id,
                order_id=order_id,
                withdrawal_id=withdrawal_id,
                entry_type=entry_type,
                direction=direction,
                amount=amount,
                currency=account.currency,
                status=status,
                available_at=available_at,
                idempotency_key=idempotency_key,
            )
        )

    def _add_withdrawal_audit(
        self,
        *,
        session: AsyncSession,
        withdrawal: WithdrawalRequest,
        action: str,
        actor_user_id: Optional[int],
        old_status: Optional[str],
        new_status: str,
        note: Optional[str],
    ) -> None:
        session.add(
            AuditLog(
                tenant_id=withdrawal.tenant_id,
                actor_user_id=actor_user_id,
                action=action,
                target_type="withdrawal_request",
                target_id=str(withdrawal.id),
                metadata_json={
                    "amount": str(withdrawal.amount),
                    "currency": withdrawal.currency,
                    "network": withdrawal.network,
                    "address": self._mask_address(withdrawal.address),
                    "old_status": old_status,
                    "new_status": new_status,
                    "note": note,
                    "payout_reference": getattr(withdrawal, "payout_reference", None),
                    "payout_proof_url": getattr(withdrawal, "payout_proof_url", None),
                },
            )
        )

    async def _settlement_freeze_days(self, session: AsyncSession, tenant_id: int) -> int:
        return (await self._effective_settlement_policy(session, tenant_id)).freeze_days

    async def _effective_settlement_policy(
        self,
        session: AsyncSession,
        tenant_id: int,
    ) -> SettlementPolicySummary:
        tenant_policy = await self._get_settlement_policy(session, "tenant", tenant_id)
        if tenant_policy is not None:
            return self._policy_summary(tenant_policy)
        platform_policy = await self._get_settlement_policy(session, "platform", None)
        if platform_policy is not None:
            return self._policy_summary(platform_policy)
        return SettlementPolicySummary(
            scope_type="default",
            tenant_id=None,
            freeze_days=7,
            platform_fee_enabled=False,
            platform_fee_percent=Decimal("1.0000"),
        )

    async def _get_settlement_policy(
        self,
        session: AsyncSession,
        scope_type: str,
        tenant_id: Optional[int],
    ) -> Optional[SettlementPolicy]:
        query = select(SettlementPolicy).where(SettlementPolicy.scope_type == scope_type)
        if tenant_id is None:
            query = query.where(SettlementPolicy.tenant_id.is_(None))
        else:
            query = query.where(SettlementPolicy.tenant_id == tenant_id)
        return (await session.execute(query)).scalar_one_or_none()

    async def _get_entry_by_key(self, session: AsyncSession, idempotency_key: str) -> Optional[LedgerEntry]:
        result = await session.execute(select(LedgerEntry).where(LedgerEntry.idempotency_key == idempotency_key))
        return result.scalar_one_or_none()

    async def _get_refund_by_key(self, session: AsyncSession, order_id: int, idempotency_key: str) -> Optional[Refund]:
        result = await session.execute(
            select(Refund)
            .where(Refund.order_id == order_id)
            .where(Refund.idempotency_key == idempotency_key)
        )
        return result.scalar_one_or_none()

    async def _get_refundable_settlement_entries(self, session: AsyncSession, order_id: int) -> List[LedgerEntry]:
        result = await session.execute(
            select(LedgerEntry)
            .where(LedgerEntry.order_id == order_id)
            .where(LedgerEntry.direction == "credit")
            .where(
                LedgerEntry.entry_type.in_(
                    (
                        "order_settlement",
                        "supplier_order_settlement",
                        "reseller_order_settlement",
                    )
                )
            )
            .order_by(LedgerEntry.id.asc())
        )
        return list(result.scalars().all())

    async def _completed_refund_amount(self, session: AsyncSession, order_id: int) -> Decimal:
        result = await session.execute(
            select(func.coalesce(func.sum(Refund.amount), 0))
            .where(Refund.order_id == order_id)
            .where(Refund.status == "completed")
        )
        return Decimal(result.scalar_one() or 0)

    async def _refund_entry_amount(
        self,
        session: AsyncSession,
        settlement_entry: LedgerEntry,
        order_amount: Decimal,
        refund_amount: Decimal,
        full_refund: bool,
    ) -> Decimal:
        refunded_amount = await self._refunded_settlement_entry_amount(session, settlement_entry)
        remaining_amount = settlement_entry.amount - refunded_amount
        if full_refund:
            return max(remaining_amount, Decimal("0"))
        target_amount = (settlement_entry.amount * refund_amount / order_amount).quantize(AMOUNT_QUANT, rounding=ROUND_DOWN)
        return min(max(target_amount, Decimal("0")), remaining_amount)

    async def _refunded_settlement_entry_amount(self, session: AsyncSession, settlement_entry: LedgerEntry) -> Decimal:
        result = await session.execute(
            select(func.coalesce(func.sum(LedgerEntry.amount), 0))
            .where(LedgerEntry.order_id == settlement_entry.order_id)
            .where(LedgerEntry.entry_type == "refund")
            .where(LedgerEntry.direction == "debit")
            .where(LedgerEntry.idempotency_key.like(f"refund:%:ledger_entry:{settlement_entry.id}:reverse"))
        )
        return Decimal(result.scalar_one() or 0)

    async def _settlement_entry_released(self, session: AsyncSession, settlement_entry: LedgerEntry) -> bool:
        release_key = f"ledger_entry:{settlement_entry.id}:settlement_available"
        return await self._get_entry_by_key(session, release_key) is not None

    async def _get_account_for_update(self, session: AsyncSession, account_id: int) -> Optional[LedgerAccount]:
        result = await session.execute(
            select(LedgerAccount)
            .where(LedgerAccount.id == account_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _refund_key(order: Order) -> str:
        return f"order:{order.id}:full_refund"

    @staticmethod
    def _normalize_refund_amount(order: Order, previous_refund_amount: Decimal, amount: Optional[Decimal]) -> Decimal:
        remaining_amount = order.amount - previous_refund_amount
        if remaining_amount <= 0:
            raise ValueError("订单已无可退款金额")
        refund_amount = remaining_amount if amount is None else amount.quantize(AMOUNT_QUANT, rounding=ROUND_DOWN)
        if refund_amount <= 0:
            raise ValueError("退款金额必须大于 0")
        if refund_amount > remaining_amount:
            raise ValueError("退款金额不能超过订单剩余可退款金额")
        return refund_amount

    @staticmethod
    def _summary(withdrawal: WithdrawalRequest) -> WithdrawalSummary:
        return WithdrawalSummary(
            withdrawal_id=withdrawal.id,
            tenant_id=withdrawal.tenant_id,
            amount=withdrawal.amount,
            currency=withdrawal.currency,
            network=withdrawal.network,
            address=withdrawal.address,
            status=withdrawal.status,
            requested_at=withdrawal.requested_at,
            payout_reference=withdrawal.payout_reference,
            payout_proof_url=withdrawal.payout_proof_url,
            reviewed_at=withdrawal.reviewed_at,
            completed_at=withdrawal.completed_at,
        )

    @staticmethod
    def _platform_fee_amount(amount: Decimal, policy: SettlementPolicySummary) -> Decimal:
        if not policy.platform_fee_enabled or amount <= 0:
            return Decimal("0")
        fee_amount = (amount * policy.platform_fee_percent / Decimal("100")).quantize(AMOUNT_QUANT, rounding=ROUND_DOWN)
        if fee_amount >= amount:
            raise ValueError("平台手续费不能大于或等于结算金额")
        return fee_amount

    @staticmethod
    def _mask_address(value: str) -> str:
        if len(value) <= 12:
            return "***"
        return f"{value[:6]}***{value[-6:]}"

    @staticmethod
    def _normalize_optional_text(value: Optional[str], label: str, *, max_length: int) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if len(normalized) > max_length:
            raise ValueError(f"{label}不能超过 {max_length} 个字符")
        if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
            raise ValueError(f"{label}不能包含控制字符")
        return normalized

    @staticmethod
    def _normalize_fee_percent(value: Decimal) -> Decimal:
        normalized = value.quantize(PERCENT_QUANT)
        if normalized < 0 or normalized >= 100:
            raise ValueError("平台手续费比例必须大于等于 0 且小于 100")
        return normalized

    @staticmethod
    def _compute_balances_from_entries(entries: List[LedgerEntry]) -> tuple[Decimal, Decimal, Decimal]:
        pending_balance = Decimal("0")
        available_balance = Decimal("0")
        frozen_balance = Decimal("0")
        for entry in entries:
            amount = Decimal(entry.amount)
            if entry.entry_type in {"order_settlement", "supplier_order_settlement", "reseller_order_settlement"}:
                if entry.direction == "credit" and entry.status == "pending":
                    pending_balance += amount
            elif entry.entry_type == "settlement_available":
                if entry.direction == "credit" and entry.status == "available":
                    pending_balance -= amount
                    available_balance += amount
            elif entry.entry_type == "refund":
                if entry.direction == "debit" and entry.status == "refunded_pending":
                    pending_balance -= amount
                elif entry.direction == "debit" and entry.status == "refunded_available":
                    available_balance -= amount
            elif entry.entry_type == "withdrawal_freeze":
                if entry.direction == "debit" and entry.status == "frozen":
                    available_balance -= amount
                    frozen_balance += amount
            elif entry.entry_type == "withdrawal_completed":
                if entry.direction == "debit" and entry.status == "withdrawn":
                    frozen_balance -= amount
            elif entry.entry_type == "withdrawal_rejected":
                if entry.direction == "credit" and entry.status == "available":
                    frozen_balance -= amount
                    available_balance += amount
        return pending_balance, available_balance, frozen_balance

    @staticmethod
    def _apply_released_refund(account: LedgerAccount, amount: Decimal) -> str:
        # 结算已释放甚至已提现后仍允许退款，负可用余额作为后续收入追偿信号。
        account.available_balance -= amount
        return "refunded_available"

    @staticmethod
    def _balance_audit_from_values(
        *,
        tenant_id: int,
        account_id: Optional[int],
        account_type: str,
        currency: str,
        stored_pending_balance: Decimal,
        stored_available_balance: Decimal,
        stored_frozen_balance: Decimal,
        computed_pending_balance: Decimal,
        computed_available_balance: Decimal,
        computed_frozen_balance: Decimal,
    ) -> LedgerBalanceAudit:
        return LedgerBalanceAudit(
            tenant_id=tenant_id,
            account_id=account_id,
            account_type=account_type,
            currency=currency,
            stored_pending_balance=stored_pending_balance,
            stored_available_balance=stored_available_balance,
            stored_frozen_balance=stored_frozen_balance,
            computed_pending_balance=computed_pending_balance,
            computed_available_balance=computed_available_balance,
            computed_frozen_balance=computed_frozen_balance,
        )

    @staticmethod
    def _policy_summary(policy: SettlementPolicy) -> SettlementPolicySummary:
        return SettlementPolicySummary(
            scope_type=policy.scope_type,
            tenant_id=policy.tenant_id,
            freeze_days=max(policy.freeze_days, 0),
            platform_fee_enabled=policy.platform_fee_enabled,
            platform_fee_percent=policy.platform_fee_percent,
        )

    def _add_platform_fee_audit(
        self,
        session: AsyncSession,
        tenant_id: int,
        order: Order,
        gross_amount: Decimal,
        platform_fee_amount: Decimal,
        policy: SettlementPolicySummary,
    ) -> None:
        if platform_fee_amount <= 0:
            return
        session.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_user_id=None,
                action="ledger.platform_fee_deducted",
                target_type="order",
                target_id=str(order.id),
                metadata_json={
                    "out_trade_no": order.out_trade_no,
                    "gross_amount": str(gross_amount),
                    "platform_fee_amount": str(platform_fee_amount),
                    "platform_fee_percent": str(policy.platform_fee_percent),
                    "policy_scope_type": policy.scope_type,
                    "policy_tenant_id": policy.tenant_id,
                },
            )
        )
