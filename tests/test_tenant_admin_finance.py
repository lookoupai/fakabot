from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import logging
from types import SimpleNamespace
import unittest
import warnings
from unittest.mock import AsyncMock, patch

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)
logging.getLogger("httpx").setLevel(logging.WARNING)

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.services.api_keys import ApiKeyService
    from app.services.ledger import LedgerBalance, LedgerBalanceAudit, WithdrawalSummary
    from app.web.tenant_admin import create_tenant_admin_router
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过 Tenant Admin 财务测试：{exc.name}") from exc


class _FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    async def commit(self) -> None:
        self.commit_count += 1


def _session_factory(session: _FakeSession):
    def factory() -> _FakeSession:
        return session

    return factory


def _client(settings: Settings) -> TestClient:
    app = FastAPI()
    app.state.redis = None
    app.include_router(create_tenant_admin_router(settings))
    return TestClient(app)


def _api_key(*, tenant_id: int = 7, scopes: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        tenant_id=tenant_id,
        scopes_json=scopes or ["finance:read", "finance:write"],
        ip_allowlist_json=[],
    )


def _authenticate(api_key: object):
    async def authenticate(self: ApiKeyService, session: object, plain_key: str) -> object | None:
        return api_key

    return authenticate


class TenantAdminFinanceRouteTest(unittest.TestCase):
    def test_get_finance_balance_requires_finance_read_scope_before_service(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["finance:write"]))):
                with patch("app.web.tenant_admin.LedgerService") as service:
                    response = client.get(
                        "/api/v1/tenant/finance/balance",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        service.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_get_finance_balance_is_tenant_scoped_and_safe(self) -> None:
        session = _FakeSession()
        get_balance = AsyncMock(
            return_value=LedgerBalance(
                tenant_id=7,
                account_type="main",
                currency="USDT",
                pending_balance=Decimal("1.00000000"),
                available_balance=Decimal("2.50000000"),
                frozen_balance=Decimal("3.25000000"),
            )
        )
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["finance:read"]))):
                with patch("app.web.tenant_admin.LedgerService") as service:
                    service.return_value.get_balance = get_balance
                    response = client.get(
                        "/api/v1/tenant/finance/balance",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("main", payload["account_type"])
        self.assertEqual("USDT", payload["currency"])
        self.assertEqual("1.00000000", payload["pending_balance"])
        self.assertEqual("2.50000000", payload["available_balance"])
        self.assertEqual("3.25000000", payload["frozen_balance"])
        self.assertNotIn("tenant_id", payload)
        self.assertEqual(2, session.commit_count)
        get_balance.assert_awaited_once_with(session, 7)

    def test_get_finance_ledger_audit_requires_finance_read_scope_before_service(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["finance:write"]))):
                with patch("app.web.tenant_admin.LedgerService") as service:
                    response = client.get(
                        "/api/v1/tenant/finance/ledger/audit",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        service.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_get_finance_ledger_audit_is_tenant_scoped_and_safe(self) -> None:
        session = _FakeSession()
        audit_account_balance = AsyncMock(
            return_value=LedgerBalanceAudit(
                tenant_id=7,
                account_id=55,
                account_type="main",
                currency="USDT",
                stored_pending_balance=Decimal("10.00000000"),
                stored_available_balance=Decimal("20.00000000"),
                stored_frozen_balance=Decimal("5.00000000"),
                computed_pending_balance=Decimal("10.00000000"),
                computed_available_balance=Decimal("18.00000000"),
                computed_frozen_balance=Decimal("7.00000000"),
            )
        )
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["finance:read"]))):
                with patch("app.web.tenant_admin.LedgerService") as service:
                    service.return_value.audit_account_balance = audit_account_balance
                    response = client.get(
                        "/api/v1/tenant/finance/ledger/audit",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("main", payload["account_type"])
        self.assertEqual("USDT", payload["currency"])
        self.assertEqual("10.00000000", payload["stored_pending_balance"])
        self.assertEqual("20.00000000", payload["stored_available_balance"])
        self.assertEqual("5.00000000", payload["stored_frozen_balance"])
        self.assertEqual("10.00000000", payload["computed_pending_balance"])
        self.assertEqual("18.00000000", payload["computed_available_balance"])
        self.assertEqual("7.00000000", payload["computed_frozen_balance"])
        self.assertEqual("0E-8", payload["pending_difference"])
        self.assertEqual("-2.00000000", payload["available_difference"])
        self.assertEqual("2.00000000", payload["frozen_difference"])
        self.assertFalse(payload["is_balanced"])
        self.assertNotIn("tenant_id", payload)
        self.assertNotIn("account_id", payload)
        self.assertEqual(1, session.commit_count)
        audit_account_balance.assert_awaited_once_with(session, 7)

    def test_list_withdrawals_requires_finance_read_scope_before_service(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["finance:write"]))):
                with patch("app.web.tenant_admin.LedgerService") as service:
                    response = client.get(
                        "/api/v1/tenant/finance/withdrawals",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        service.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_list_withdrawals_is_tenant_scoped_and_redacted(self) -> None:
        session = _FakeSession()
        raw_address = "T1234567890abcdef"
        list_withdrawals = AsyncMock(
            return_value=[
                WithdrawalSummary(
                    withdrawal_id=11,
                    tenant_id=7,
                    amount=Decimal("9.00000000"),
                    currency="USDT",
                    network="TRC20",
                    address=raw_address,
                    status="pending",
                    requested_at=datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc),
                    payout_reference="PAYOUT-1",
                    payout_proof_url="https://proof.example/1",
                )
            ]
        )
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["finance:read"]))):
                with patch("app.web.tenant_admin.LedgerService") as service:
                    service.return_value.list_withdrawals = list_withdrawals
                    response = client.get(
                        "/api/v1/tenant/finance/withdrawals?limit=500",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(1, len(payload["withdrawals"]))
        item = payload["withdrawals"][0]
        self.assertEqual(11, item["withdrawal_id"])
        self.assertEqual("9.00000000", item["amount"])
        self.assertEqual("USDT", item["currency"])
        self.assertEqual("TRC20", item["network"])
        self.assertEqual("T12345***abcdef", item["address_masked"])
        self.assertEqual("pending", item["status"])
        self.assertEqual("PAYOUT-1", item["payout_reference"])
        self.assertEqual("https://proof.example/1", item["payout_proof_url"])
        self.assertNotIn("tenant_id", item)
        self.assertNotIn("address", item)
        self.assertNotIn(raw_address, response.text)
        self.assertEqual(1, session.commit_count)
        list_withdrawals.assert_awaited_once_with(session, tenant_id=7, limit=100)

    def test_get_withdrawal_requires_finance_read_scope_before_service(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["finance:write"]))):
                with patch("app.web.tenant_admin.LedgerService") as service:
                    response = client.get(
                        "/api/v1/tenant/finance/withdrawals/11",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        service.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_get_withdrawal_is_tenant_scoped_and_redacted(self) -> None:
        session = _FakeSession()
        raw_address = "T1234567890abcdef"
        get_withdrawal = AsyncMock(
            return_value=WithdrawalSummary(
                withdrawal_id=11,
                tenant_id=7,
                amount=Decimal("9.00000000"),
                currency="USDT",
                network="TRC20",
                address=raw_address,
                status="completed",
                requested_at=datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc),
                payout_reference="PAYOUT-1",
                payout_proof_url="https://proof.example/1",
                reviewed_at=datetime(2026, 6, 8, 13, 0, tzinfo=timezone.utc),
                completed_at=datetime(2026, 6, 8, 13, 30, tzinfo=timezone.utc),
            )
        )
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["finance:read"]))):
                with patch("app.web.tenant_admin.LedgerService") as service:
                    service.return_value.get_withdrawal = get_withdrawal
                    response = client.get(
                        "/api/v1/tenant/finance/withdrawals/11",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(11, payload["withdrawal_id"])
        self.assertEqual("9.00000000", payload["amount"])
        self.assertEqual("USDT", payload["currency"])
        self.assertEqual("TRC20", payload["network"])
        self.assertEqual("T12345***abcdef", payload["address_masked"])
        self.assertEqual("completed", payload["status"])
        self.assertEqual("PAYOUT-1", payload["payout_reference"])
        self.assertEqual("https://proof.example/1", payload["payout_proof_url"])
        self.assertEqual("2026-06-08T13:00:00+00:00", payload["reviewed_at"])
        self.assertEqual("2026-06-08T13:30:00+00:00", payload["completed_at"])
        self.assertNotIn("tenant_id", payload)
        self.assertNotIn("address", payload)
        self.assertNotIn("admin_note", payload)
        self.assertNotIn(raw_address, response.text)
        self.assertEqual(1, session.commit_count)
        get_withdrawal.assert_awaited_once_with(session, tenant_id=7, withdrawal_id=11)

    def test_get_withdrawal_returns_404_for_missing_or_cross_tenant(self) -> None:
        session = _FakeSession()
        get_withdrawal = AsyncMock(return_value=None)
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["finance:read"]))):
                with patch("app.web.tenant_admin.LedgerService") as service:
                    service.return_value.get_withdrawal = get_withdrawal
                    response = client.get(
                        "/api/v1/tenant/finance/withdrawals/99",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(404, response.status_code)
        self.assertEqual("提现申请不存在", response.json()["detail"])
        self.assertEqual(1, session.commit_count)
        get_withdrawal.assert_awaited_once_with(session, tenant_id=7, withdrawal_id=99)

    def test_create_withdrawal_requires_finance_write_scope_before_service(self) -> None:
        session = _FakeSession()
        client = _client(Settings())
        raw_address = "T1234567890abcdef"

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["finance:read"]))):
                with patch("app.web.tenant_admin.LedgerService") as service:
                    response = client.post(
                        "/api/v1/tenant/finance/withdrawals",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"amount": "5.00000000", "network": "TRC20", "address": raw_address},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        self.assertNotIn(raw_address, response.text)
        service.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_create_withdrawal_commits_and_returns_masked_address(self) -> None:
        session = _FakeSession()
        raw_address = "T1234567890abcdef"
        create_withdrawal_request = AsyncMock(
            return_value=SimpleNamespace(
                id=12,
                tenant_id=7,
                amount=Decimal("5.00000000"),
                currency="USDT",
                network="TRC20",
                address=raw_address,
                status="pending",
                requested_at=datetime(2026, 6, 8, 12, 30, tzinfo=timezone.utc),
                payout_reference=None,
                payout_proof_url=None,
            )
        )
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["finance:write"]))):
                with patch("app.web.tenant_admin.LedgerService") as service:
                    service.return_value.create_withdrawal_request = create_withdrawal_request
                    response = client.post(
                        "/api/v1/tenant/finance/withdrawals",
                        headers={"X-API-Key": "fk_live_test"},
                        json={
                            "amount": "5.00000000",
                            "network": " trc20 ",
                            "address": f" {raw_address} ",
                            "currency": " usdt ",
                        },
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(12, payload["withdrawal_id"])
        self.assertEqual("5.00000000", payload["amount"])
        self.assertEqual("USDT", payload["currency"])
        self.assertEqual("TRC20", payload["network"])
        self.assertEqual("T12345***abcdef", payload["address_masked"])
        self.assertEqual("pending", payload["status"])
        self.assertNotIn("tenant_id", payload)
        self.assertNotIn("address", payload)
        self.assertNotIn(raw_address, response.text)
        self.assertEqual(2, session.commit_count)
        create_withdrawal_request.assert_awaited_once()
        kwargs = create_withdrawal_request.await_args.kwargs
        self.assertIs(session, kwargs["session"])
        self.assertEqual(7, kwargs["tenant_id"])
        self.assertEqual(Decimal("5.00000000"), kwargs["amount"])
        self.assertEqual("TRC20", kwargs["network"])
        self.assertEqual(raw_address, kwargs["address"])
        self.assertEqual("USDT", kwargs["currency"])
        self.assertIsNone(kwargs["actor_user_id"])

    def test_create_withdrawal_value_error_returns_400_and_redacts_address(self) -> None:
        session = _FakeSession()
        raw_address = "T1234567890abcdef"
        create_withdrawal_request = AsyncMock(side_effect=ValueError(f"address={raw_address} 可用余额不足"))
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["finance:write"]))):
                with patch("app.web.tenant_admin.LedgerService") as service:
                    service.return_value.create_withdrawal_request = create_withdrawal_request
                    response = client.post(
                        "/api/v1/tenant/finance/withdrawals",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"amount": "5.00000000", "network": "TRC20", "address": raw_address},
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("财务请求参数无效", response.json()["detail"])
        self.assertNotIn(raw_address, response.text)
        self.assertNotIn("address=", response.text)
        self.assertEqual(1, session.commit_count)

    def test_create_withdrawal_runtime_error_returns_503_and_redacts_secret(self) -> None:
        session = _FakeSession()
        raw_address = "T1234567890abcdef"
        create_withdrawal_request = AsyncMock(
            side_effect=RuntimeError(f"withdrawal secret=plain-secret address={raw_address}")
        )
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["finance:write"]))):
                with patch("app.web.tenant_admin.LedgerService") as service:
                    service.return_value.create_withdrawal_request = create_withdrawal_request
                    response = client.post(
                        "/api/v1/tenant/finance/withdrawals",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"amount": "5.00000000", "network": "TRC20", "address": raw_address},
                    )

        self.assertEqual(503, response.status_code)
        self.assertEqual("提现服务暂不可用", response.json()["detail"])
        self.assertNotIn(raw_address, response.text)
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("secret=", response.text)
        self.assertEqual(1, session.commit_count)

    def test_create_withdrawal_rejects_invalid_amount_precision_before_service(self) -> None:
        session = _FakeSession()
        raw_address = "T1234567890abcdef"
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["finance:write"]))):
                with patch("app.web.tenant_admin.LedgerService") as service:
                    response = client.post(
                        "/api/v1/tenant/finance/withdrawals",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"amount": "5.000000001", "network": "TRC20", "address": raw_address},
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("提现金额最多支持 8 位小数", response.json()["detail"])
        self.assertNotIn(raw_address, response.text)
        service.return_value.create_withdrawal_request.assert_not_called()
        self.assertEqual(1, session.commit_count)


if __name__ == "__main__":
    unittest.main()
