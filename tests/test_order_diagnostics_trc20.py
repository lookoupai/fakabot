from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
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
    from app.services.order_diagnostics import OrderDiagnosticsService
    from app.web.tenant_admin import create_tenant_admin_router
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过 TRC20 订单排障测试：{exc.name}") from exc


TRC20_SAFE_FIELDS = {
    "expected",
    "transfer_count",
    "latest_match_status",
    "latest_confirmations",
    "latest_matched_at",
    "latest_amount",
}

TRC20_FORBIDDEN_FIELDS = {
    "tx_hash",
    "from_address",
    "to_address",
    "id",
    "tenant_id",
    "payment_id",
    "order_id",
    "raw_payload",
    "payload_json",
    "metadata_json",
}


class _ScalarList:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return self._values


class _Result:
    def __init__(self, *, scalar: object | None = None, values: list[object] | None = None) -> None:
        self._scalar = scalar
        self._values = values or []

    def scalar_one_or_none(self) -> object | None:
        return self._scalar

    def scalars(self) -> _ScalarList:
        return _ScalarList(self._values)

    def all(self) -> list[object]:
        return self._values


class _RoutingSession:
    def __init__(
        self,
        *,
        order: SimpleNamespace | None,
        transfer_count: int = 0,
        latest_transfer: SimpleNamespace | None = None,
    ) -> None:
        self.order = order
        self.transfer_count = transfer_count
        self.latest_transfer = latest_transfer
        self.executed_queries: list[object] = []

    async def execute(self, query: object) -> _Result:
        self.executed_queries.append(query)
        query_text = str(query).lower()
        if "trc20_direct_transfers" in query_text:
            values = [self.latest_transfer] if self.latest_transfer is not None else []
            if "count(" in query_text:
                return _Result(scalar=self.transfer_count)
            return _Result(scalar=self.latest_transfer, values=values)
        if "from orders" in query_text:
            return _Result(scalar=self.order)
        if "payment_callbacks" in query_text:
            return _Result(values=[])
        if "from payments" in query_text:
            return _Result(values=[])
        if "delivery_records" in query_text:
            return _Result(scalar=None)
        if "from products" in query_text:
            return _Result(scalar=None)
        if "external_fulfillment_attempts" in query_text and "count(" in query_text:
            return _Result(scalar=0)
        if "external_fulfillment_attempts" in query_text:
            return _Result(scalar=None)
        raise AssertionError(f"未预期的查询：{query}")


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
        scopes_json=scopes or ["orders:read"],
        ip_allowlist_json=[],
    )


def _authenticate(api_key: object):
    async def authenticate(self: ApiKeyService, session: object, plain_key: str) -> object | None:
        return api_key

    return authenticate


class OrderDiagnosticsTrc20ServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_get_summary_returns_safe_trc20_direct_aggregate_for_direct_order(self) -> None:
        now = datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc)
        session = _RoutingSession(
            order=_order(now=now, payment_provider="usdt_trc20_direct"),
            transfer_count=2,
            latest_transfer=_trc20_transfer(now=now),
        )

        summary = await OrderDiagnosticsService().get_summary(
            session,
            tenant_id=7,
            out_trade_no=" ORD_TRX ",
        )

        self.assertIsNotNone(summary)
        assert summary is not None
        trc20_direct = getattr(summary, "trc20_direct", None)
        self.assertIsNotNone(trc20_direct)
        aggregate = _public_mapping(trc20_direct)
        self.assertEqual(TRC20_SAFE_FIELDS, set(aggregate))
        self.assertTrue(aggregate["expected"])
        self.assertEqual(2, aggregate["transfer_count"])
        self.assertEqual("matched", aggregate["latest_match_status"])
        self.assertEqual(36, aggregate["latest_confirmations"])
        self.assertEqual(now, aggregate["latest_matched_at"])
        self.assertEqual(Decimal("10.00000000"), aggregate["latest_amount"])

        rendered = repr(trc20_direct).lower()
        for marker in TRC20_FORBIDDEN_FIELDS | {"plain-token", "plain-secret", "tfrom", "tto"}:
            self.assertNotIn(marker, rendered)

        trc20_queries = [str(query) for query in session.executed_queries if "trc20_direct_transfers" in str(query)]
        self.assertGreaterEqual(len(trc20_queries), 1)
        query_text = "\n".join(trc20_queries)
        self.assertIn("trc20_direct_transfers.tenant_id", query_text)
        self.assertIn("trc20_direct_transfers.order_id", query_text)
        self.assertIn("trc20_direct_transfers.out_trade_no", query_text)

    async def test_get_summary_returns_empty_trc20_direct_aggregate_without_latest_transfer(self) -> None:
        now = datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc)
        session = _RoutingSession(
            order=_order(now=now, payment_provider="usdt_trc20_direct"),
            transfer_count=0,
            latest_transfer=None,
        )

        summary = await OrderDiagnosticsService().get_summary(
            session,
            tenant_id=7,
            out_trade_no="ORD_TRX",
        )

        self.assertIsNotNone(summary)
        assert summary is not None
        trc20_direct = getattr(summary, "trc20_direct", None)
        self.assertIsNotNone(trc20_direct)
        aggregate = _public_mapping(trc20_direct)
        self.assertEqual(TRC20_SAFE_FIELDS, set(aggregate))
        self.assertTrue(aggregate["expected"])
        self.assertEqual(0, aggregate["transfer_count"])
        self.assertIsNone(aggregate["latest_match_status"])
        self.assertIsNone(aggregate["latest_confirmations"])
        self.assertIsNone(aggregate["latest_matched_at"])
        self.assertIsNone(aggregate["latest_amount"])


class TenantAdminOrderDiagnosticsTrc20RouteTest(unittest.TestCase):
    def test_order_diagnostics_returns_safe_trc20_direct_aggregate_only(self) -> None:
        now = datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc)
        session = _FakeSession()
        get_summary = AsyncMock(return_value=_diagnostics_summary(now=now))
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7))):
                with patch("app.web.tenant_admin.OrderDiagnosticsService") as diagnostics_service:
                    diagnostics_service.return_value.get_summary = get_summary
                    response = client.get(
                        "/api/v1/tenant/orders/ORD_TRX/diagnostics",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertIn("trc20_direct", payload)
        trc20_direct = payload["trc20_direct"]
        self.assertEqual(TRC20_SAFE_FIELDS, set(trc20_direct))
        self.assertTrue(trc20_direct["expected"])
        self.assertEqual(2, trc20_direct["transfer_count"])
        self.assertEqual("matched", trc20_direct["latest_match_status"])
        self.assertEqual(36, trc20_direct["latest_confirmations"])
        self.assertEqual(now.isoformat(), trc20_direct["latest_matched_at"])
        self.assertEqual("10.00000000", trc20_direct["latest_amount"])

        for field_name in TRC20_FORBIDDEN_FIELDS:
            self.assertNotIn(field_name, trc20_direct)
        response_text = response.text
        for marker in (
            "a" * 64,
            "TFromAddress1234567890abcdef",
            "TToAddress1234567890abcdef",
            "plain-token",
            "plain-secret",
            "raw_payload",
            "payload_json",
            "metadata_json",
        ):
            self.assertNotIn(marker, response_text)
        get_summary.assert_awaited_once_with(session, tenant_id=7, out_trade_no="ORD_TRX")


def _public_mapping(value: object) -> dict[str, object]:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "__dict__"):
        return {key: item for key, item in vars(value).items() if not key.startswith("_")}
    raise AssertionError(f"无法读取公开字段：{value!r}")


def _order(*, now: datetime, payment_provider: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=55,
        tenant_id=7,
        buyer_telegram_user_id=42,
        source_type="self",
        self_product_id=None,
        supplier_tenant_id=None,
        amount=Decimal("10.00"),
        currency="USDT",
        status="pending",
        payment_mode="tenant_direct",
        payment_provider=payment_provider,
        out_trade_no="ORD_TRX",
        locked_inventory_item_id=None,
        created_at=now,
        expires_at=now + timedelta(minutes=30),
        paid_at=None,
        delivered_at=None,
    )


def _trc20_transfer(*, now: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        id=301,
        tenant_id=7,
        order_id=55,
        payment_id=91,
        tx_hash="a" * 64,
        block_number=64200000,
        timestamp_ms=1_781_000_000_000,
        block_timestamp=now,
        from_address="TFromAddress1234567890abcdef",
        to_address="TToAddress1234567890abcdef",
        contract_address="TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        raw_amount=10_000_000,
        amount=Decimal("10.00000000"),
        confirmations=36,
        match_status="matched",
        out_trade_no="ORD_TRX",
        matched_at=now,
        created_at=now,
        raw_payload={"token": "plain-token"},
        payload_json={"secret": "plain-secret"},
        metadata_json={"tx_hash": "a" * 64},
    )


def _diagnostics_summary(*, now: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        order_id=55,
        out_trade_no="ORD_TRX",
        source_type="self",
        status="pending",
        payment_mode="tenant_direct",
        payment_provider="usdt_trc20_direct",
        amount=Decimal("10.00"),
        currency="USDT",
        created_at=now,
        expires_at=now + timedelta(minutes=30),
        paid_at=None,
        delivered_at=None,
        payment_count=1,
        callback_count=0,
        callback_status_counts={},
        payments=[],
        callbacks=[],
        delivery=None,
        external_fulfillment=SimpleNamespace(
            expected=False,
            attempt_count=0,
            latest_attempt_status=None,
            latest_attempt_source=None,
            latest_attempt_at=None,
            latest_failure_stage=None,
            latest_failure_category=None,
            latest_failure_retryable=None,
            latest_upstream_status_code=None,
            latest_item_count=0,
            latest_delivery_record_linked=False,
        ),
        trc20_direct=SimpleNamespace(
            expected=True,
            transfer_count=2,
            latest_match_status="matched",
            latest_confirmations=36,
            latest_matched_at=now,
            latest_amount=Decimal("10.00000000"),
            tx_hash="a" * 64,
            from_address="TFromAddress1234567890abcdef",
            to_address="TToAddress1234567890abcdef",
            id=301,
            tenant_id=7,
            payment_id=91,
            order_id=55,
            raw_payload={"token": "plain-token"},
            payload_json={"secret": "plain-secret"},
            metadata_json={"tx_hash": "a" * 64},
        ),
    )


if __name__ == "__main__":
    unittest.main()
