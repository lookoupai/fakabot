from __future__ import annotations

"""harden ledger withdrawal constraints

Revision ID: 20260606_0019
Revises: 20260606_0018
Create Date: 2026-06-06
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260606_0019"
down_revision: Optional[str] = "20260606_0018"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.add_column("withdrawal_requests", sa.Column("payout_reference", sa.String(length=128), nullable=True))
    op.add_column("withdrawal_requests", sa.Column("payout_proof_url", sa.Text(), nullable=True))

    op.create_check_constraint(
        "ck_ledger_accounts_pending_nonnegative",
        "ledger_accounts",
        "pending_balance >= 0",
    )
    op.create_check_constraint(
        "ck_ledger_accounts_frozen_nonnegative",
        "ledger_accounts",
        "frozen_balance >= 0",
    )
    op.create_check_constraint(
        "ck_ledger_accounts_account_type_not_empty",
        "ledger_accounts",
        "account_type <> ''",
    )
    op.create_check_constraint(
        "ck_ledger_accounts_currency_not_empty",
        "ledger_accounts",
        "currency <> ''",
    )
    op.create_check_constraint(
        "ck_ledger_accounts_status_not_empty",
        "ledger_accounts",
        "status <> ''",
    )

    op.create_check_constraint(
        "ck_settlement_policies_scope_type",
        "settlement_policies",
        "scope_type IN ('platform', 'tenant')",
    )
    op.create_check_constraint(
        "ck_settlement_policies_freeze_days_nonnegative",
        "settlement_policies",
        "freeze_days >= 0",
    )
    op.create_check_constraint(
        "ck_settlement_policies_platform_fee_percent_range",
        "settlement_policies",
        "platform_fee_percent >= 0 AND platform_fee_percent <= 100",
    )

    op.create_check_constraint(
        "ck_withdrawal_requests_amount_positive",
        "withdrawal_requests",
        "amount > 0",
    )
    op.create_check_constraint(
        "ck_withdrawal_requests_currency_not_empty",
        "withdrawal_requests",
        "currency <> ''",
    )
    op.create_check_constraint(
        "ck_withdrawal_requests_network_not_empty",
        "withdrawal_requests",
        "network <> ''",
    )
    op.create_check_constraint(
        "ck_withdrawal_requests_status",
        "withdrawal_requests",
        "status IN ('pending', 'completed', 'rejected')",
    )

    op.create_check_constraint(
        "ck_ledger_entries_amount_positive",
        "ledger_entries",
        "amount > 0",
    )
    op.create_check_constraint(
        "ck_ledger_entries_direction",
        "ledger_entries",
        "direction IN ('credit', 'debit')",
    )
    op.create_check_constraint(
        "ck_ledger_entries_entry_type_not_empty",
        "ledger_entries",
        "entry_type <> ''",
    )
    op.create_check_constraint(
        "ck_ledger_entries_currency_not_empty",
        "ledger_entries",
        "currency <> ''",
    )
    op.create_check_constraint(
        "ck_ledger_entries_status_not_empty",
        "ledger_entries",
        "status <> ''",
    )

    op.create_check_constraint(
        "ck_refunds_amount_positive",
        "refunds",
        "amount > 0",
    )
    op.create_check_constraint(
        "ck_refunds_currency_not_empty",
        "refunds",
        "currency <> ''",
    )
    op.create_check_constraint(
        "ck_refunds_status",
        "refunds",
        "status IN ('pending', 'completed', 'failed')",
    )
    op.create_check_constraint(
        "ck_refunds_idempotency_key_not_empty",
        "refunds",
        "idempotency_key <> ''",
    )


def downgrade() -> None:
    op.drop_constraint("ck_refunds_idempotency_key_not_empty", "refunds", type_="check")
    op.drop_constraint("ck_refunds_status", "refunds", type_="check")
    op.drop_constraint("ck_refunds_currency_not_empty", "refunds", type_="check")
    op.drop_constraint("ck_refunds_amount_positive", "refunds", type_="check")

    op.drop_constraint("ck_ledger_entries_status_not_empty", "ledger_entries", type_="check")
    op.drop_constraint("ck_ledger_entries_currency_not_empty", "ledger_entries", type_="check")
    op.drop_constraint("ck_ledger_entries_entry_type_not_empty", "ledger_entries", type_="check")
    op.drop_constraint("ck_ledger_entries_direction", "ledger_entries", type_="check")
    op.drop_constraint("ck_ledger_entries_amount_positive", "ledger_entries", type_="check")

    op.drop_constraint("ck_withdrawal_requests_status", "withdrawal_requests", type_="check")
    op.drop_constraint("ck_withdrawal_requests_network_not_empty", "withdrawal_requests", type_="check")
    op.drop_constraint("ck_withdrawal_requests_currency_not_empty", "withdrawal_requests", type_="check")
    op.drop_constraint("ck_withdrawal_requests_amount_positive", "withdrawal_requests", type_="check")

    op.drop_constraint("ck_settlement_policies_platform_fee_percent_range", "settlement_policies", type_="check")
    op.drop_constraint("ck_settlement_policies_freeze_days_nonnegative", "settlement_policies", type_="check")
    op.drop_constraint("ck_settlement_policies_scope_type", "settlement_policies", type_="check")

    op.drop_constraint("ck_ledger_accounts_status_not_empty", "ledger_accounts", type_="check")
    op.drop_constraint("ck_ledger_accounts_currency_not_empty", "ledger_accounts", type_="check")
    op.drop_constraint("ck_ledger_accounts_account_type_not_empty", "ledger_accounts", type_="check")
    op.drop_constraint("ck_ledger_accounts_frozen_nonnegative", "ledger_accounts", type_="check")
    op.drop_constraint("ck_ledger_accounts_pending_nonnegative", "ledger_accounts", type_="check")

    op.drop_column("withdrawal_requests", "payout_proof_url")
    op.drop_column("withdrawal_requests", "payout_reference")
