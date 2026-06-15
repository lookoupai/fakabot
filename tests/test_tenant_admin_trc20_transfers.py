from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import logging
from types import SimpleNamespace
import unittest
import warnings
from unittest.mock import patch

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
    from app.web.tenant_admin import create_tenant_admin_router
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过 Tenant Admin TRC20 转账观测测试：{exc.name}") from exc


class _ScalarList:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return self._values


class _Result:
    def __init__(self, values: list[object] | None = None) -> None:
        self._values = values or []

    def scalars(self) -> _ScalarList:
        return _ScalarList(self._values)

    def all(self) -> list[object]:
        return self._values


class _FakeSession:
    def __init__(self, execute_results: list[_Result] | None = None) -> None:
        self.execute_results = list(execute_results or [])
        self.executed_queries: list[object] = []
        self.commit_count = 0

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    async def execute(self, query: object) -> _Result:
        self.executed_queries.append(query)
        if not self.execute_results:
            raise AssertionError("未预期的 session.execute 调用")
        return self.execute_results.pop(0)

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
        scopes_json=scopes or ["payments:read"],
        ip_allowlist_json=[],
    )


def _authenticate(api_key: object):
    async def authenticate(self: ApiKeyService, session: object, plain_key: str) -> object | None:
        return api_key

    return authenticate


def _transfer_summary() -> SimpleNamespace:
    return SimpleNamespace(
        id=99,
        tenant_id=7,
        order_id=55,
        payment_id=66,
        tx_hash="a" * 64,
        block_number=64200000,
        timestamp_ms=1781000000000,
        block_timestamp=datetime(2026, 6, 9, 10, 0, tzinfo=timezone.utc),
        from_address="TFromAddress1234567890abcdef",
        to_address="TToAddress1234567890abcdef",
        contract_address="TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj",
        raw_amount=12345678,
        amount=Decimal("12.34567800"),
        confirmations=20,
        match_status="matched",
        out_trade_no="ORD123",
        matched_at=datetime(2026, 6, 9, 10, 1, tzinfo=timezone.utc),
        created_at=datetime(2026, 6, 9, 10, 2, tzinfo=timezone.utc),
        raw_payload={"token": "plain-token"},
        payload_json={"secret": "plain-secret"},
        metadata_json={"from_address": "TFromAddress1234567890abcdef"},
    )


class TenantAdminTrc20DirectTransferRouteTest(unittest.TestCase):
    def test_list_trc20_direct_transfers_requires_payments_read_scope_before_query(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["payments:write"]))):
                response = client.get(
                    "/api/v1/tenant/payments/trc20-direct/transfers",
                    headers={"X-API-Key": "fk_live_test"},
                )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        self.assertEqual([], session.executed_queries)

    def test_list_trc20_direct_transfers_is_tenant_scoped_and_returns_safe_summary(self) -> None:
        transfer = _transfer_summary()
        session = _FakeSession([_Result(values=[transfer])])
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["payments:read"]))):
                response = client.get(
                    "/api/v1/tenant/payments/trc20-direct/transfers?limit=5",
                    headers={"X-API-Key": "fk_live_test"},
                )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(1, len(payload["transfers"]))
        item = payload["transfers"][0]

        safe_fields = {
            "tx_hash",
            "block_number",
            "timestamp_ms",
            "block_timestamp",
            "from_address_masked",
            "to_address_masked",
            "contract_address",
            "amount",
            "confirmations",
            "match_status",
            "out_trade_no",
            "matched_at",
            "created_at",
        }
        required_fields = safe_fields - {"timestamp_ms", "block_timestamp"}
        self.assertTrue(required_fields.issubset(item.keys()))
        self.assertTrue({"timestamp_ms", "block_timestamp"} & item.keys())
        self.assertTrue(set(item).issubset(safe_fields))
        self.assertEqual("a" * 64, item["tx_hash"])
        self.assertEqual(64200000, item["block_number"])
        self.assertEqual("TFromA***abcdef", item["from_address_masked"])
        self.assertEqual("TToAdd***abcdef", item["to_address_masked"])
        self.assertEqual("TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj", item["contract_address"])
        self.assertEqual("12.34567800", item["amount"])
        self.assertEqual(20, item["confirmations"])
        self.assertEqual("matched", item["match_status"])
        self.assertEqual("ORD123", item["out_trade_no"])

        response_text = response.text
        forbidden_fields = {
            "id",
            "tenant_id",
            "payment_id",
            "order_id",
            "raw_payload",
            "payload_json",
            "metadata_json",
            "from_address",
            "to_address",
        }
        for field_name in forbidden_fields:
            self.assertNotIn(field_name, item)
        self.assertNotIn("TFromAddress1234567890abcdef", response_text)
        self.assertNotIn("TToAddress1234567890abcdef", response_text)
        self.assertNotIn("plain-token", response_text)
        self.assertNotIn("plain-secret", response_text)
        self.assertNotIn("token", response_text.lower())
        self.assertNotIn("secret", response_text.lower())

        self.assertGreaterEqual(len(session.executed_queries), 1)
        query_text = "\n".join(str(query) for query in session.executed_queries)
        self.assertIn("trc20_direct_transfers.tenant_id", query_text)


if __name__ == "__main__":
    unittest.main()
