from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, call, patch

try:
    from app.services.orders import OrderService
    from app.workers.order_expire import expire_pending_orders_once
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过订单过期测试：{exc.name}") from exc


class _ScalarList:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return self._values


class _Result:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def scalars(self) -> _ScalarList:
        return _ScalarList(self._values)


class _FakeSession:
    def __init__(self, orders: list[object] | None = None) -> None:
        self.orders = orders or []
        self.flush_count = 0
        self.commit_count = 0

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    async def execute(self, query: object) -> _Result:
        return _Result(self.orders)

    async def flush(self) -> None:
        self.flush_count += 1

    async def commit(self) -> None:
        self.commit_count += 1


def _session_factory(session: _FakeSession):
    def factory() -> _FakeSession:
        return session

    return factory


class OrderExpirationTest(unittest.TestCase):
    def test_expire_pending_orders_releases_self_and_reseller_inventory_locks(self) -> None:
        self_order = _order(order_id=1, tenant_id=7, source_type="self", supplier_tenant_id=None)
        reseller_order = _order(order_id=2, tenant_id=9, source_type="reseller", supplier_tenant_id=88)
        session = _FakeSession([self_order, reseller_order])
        release_locks = AsyncMock()

        with patch("app.services.orders.InventoryService") as inventory_service:
            inventory_service.return_value.release_order_locks = release_locks
            expired_count = asyncio.run(
                OrderService().expire_pending_orders(
                    session,
                    limit=10,
                    now=datetime.now(timezone.utc),
                )
            )

        self.assertEqual(2, expired_count)
        self.assertEqual("expired", self_order.status)
        self.assertIsNone(self_order.locked_inventory_item_id)
        self.assertEqual("expired", reseller_order.status)
        self.assertIsNone(reseller_order.locked_inventory_item_id)
        self.assertEqual(1, session.flush_count)
        self.assertEqual(
            [
                call(session=session, tenant_id=7, order_id=1),
                call(session=session, tenant_id=88, order_id=2),
            ],
            release_locks.await_args_list,
        )

    def test_expire_pending_orders_with_empty_result_only_flushes(self) -> None:
        session = _FakeSession([])
        release_locks = AsyncMock()

        with patch("app.services.orders.InventoryService") as inventory_service:
            inventory_service.return_value.release_order_locks = release_locks
            expired_count = asyncio.run(OrderService().expire_pending_orders(session))

        self.assertEqual(0, expired_count)
        self.assertEqual(0, release_locks.await_count)
        self.assertEqual(1, session.flush_count)

    def test_order_expire_worker_commits_and_returns_service_count(self) -> None:
        session = _FakeSession([])
        expire_orders = AsyncMock(return_value=3)

        with patch("app.workers.order_expire.OrderService") as order_service:
            order_service.return_value.expire_pending_orders = expire_orders
            expired_count = asyncio.run(expire_pending_orders_once(_session_factory(session), limit=77))

        self.assertEqual(3, expired_count)
        self.assertEqual(1, session.commit_count)
        self.assertEqual(1, expire_orders.await_count)
        self.assertEqual(session, expire_orders.await_args.args[0])
        self.assertEqual(77, expire_orders.await_args.kwargs["limit"])


def _order(
    *,
    order_id: int,
    tenant_id: int,
    source_type: str,
    supplier_tenant_id: int | None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=order_id,
        tenant_id=tenant_id,
        source_type=source_type,
        supplier_tenant_id=supplier_tenant_id,
        status="pending",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        locked_inventory_item_id=123,
    )


if __name__ == "__main__":
    unittest.main()
