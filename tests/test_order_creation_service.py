from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

try:
    from app.db.models.orders import Order
    from app.db.models.tenants import Tenant
    from app.services.orders import OrderService
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过订单创建服务测试：{exc.name}") from exc


class _FirstResult:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def first(self) -> object | None:
        return self._value


class _SettingsResult:
    def __init__(self, settings: dict[str, dict[str, object]]) -> None:
        self._settings = settings

    def scalars(self) -> "_SettingsResult":
        return self

    def all(self) -> list[object]:
        return [
            SimpleNamespace(key=key, value_json=value)
            for key, value in self._settings.items()
        ]


class _FakeSession:
    def __init__(
        self,
        *,
        tenant: SimpleNamespace | None,
        reseller_row: tuple[object, object, object, object, object | None] | None = None,
        settings: dict[str, dict[str, object]] | None = None,
        related_tenants: dict[int, SimpleNamespace] | None = None,
    ) -> None:
        self.tenant = tenant
        self.reseller_row = reseller_row
        self.settings = settings or {}
        self.related_tenants = related_tenants or {}
        self.added: list[object] = []
        self.flush_count = 0
        self.next_order_id = 1001

    async def get(self, model: object, item_id: int) -> object | None:
        if model is Tenant and self.tenant is not None and self.tenant.id == item_id:
            return self.tenant
        if model is Tenant and item_id in self.related_tenants:
            return self.related_tenants[item_id]
        if model is Tenant and item_id > 0:
            return _tenant(status="active", tenant_id=item_id)
        return None

    async def execute(self, query: object) -> object:
        query_text = str(query)
        if "reseller_products" in query_text and "supplier_offers" in query_text:
            return _FirstResult(self.reseller_row)
        return _SettingsResult(self.settings)

    def add(self, item: object) -> None:
        if isinstance(item, Order):
            item.id = self.next_order_id
            self.next_order_id += 1
        self.added.append(item)

    async def flush(self) -> None:
        self.flush_count += 1


class OrderCreationServiceTest(unittest.TestCase):
    def test_create_self_card_order_locks_tenant_inventory(self) -> None:
        tenant = _tenant(status="active")
        product = _product(product_id=3, delivery_type="card_pool")
        variant = _variant(variant_id=30, price=Decimal("12.50"))
        session = _FakeSession(tenant=tenant)
        lock_inventory = AsyncMock(return_value=SimpleNamespace(inventory_item_id=555))

        with patch("app.services.orders.ProductRepository") as product_repo, patch(
            "app.services.orders.InventoryService",
        ) as inventory_service, patch("app.services.orders.RiskControlService") as risk_service:
            product_repo.return_value.get_product_with_default_variant = AsyncMock(return_value=(product, variant))
            inventory_service.return_value.lock_one_available_item = lock_inventory
            risk_check = risk_service.return_value.ensure_order_creation_allowed = AsyncMock()
            created = asyncio.run(
                OrderService().create_self_order(
                    session=session,
                    tenant_id=7,
                    buyer_telegram_user_id=42,
                    product_id=3,
                    order_timeout_minutes=15,
                )
            )

        risk_check.assert_awaited_once_with(
            session=session,
            buyer_telegram_user_id=42,
            amount=Decimal("12.50"),
            currency="USDT",
            tenant_id=7,
            source_type="self",
        )
        self.assertEqual(1001, created.order_id)
        self.assertEqual(Decimal("12.50"), created.amount)
        self.assertEqual("USDT", created.currency)
        self.assertEqual(555, created.locked_inventory_item_id)
        self.assertEqual(2, session.flush_count)
        self.assertEqual(1, len(session.added))
        order = session.added[0]
        self.assertIsInstance(order, Order)
        self.assertEqual("self", order.source_type)
        self.assertEqual(7, order.tenant_id)
        self.assertEqual(42, order.buyer_telegram_user_id)
        self.assertEqual(3, order.self_product_id)
        self.assertEqual(30, order.product_variant_id)
        self.assertEqual(555, order.locked_inventory_item_id)
        self.assertEqual("pending_payment", order.payment_mode)
        lock_inventory.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            product_id=3,
            order_id=1001,
            lock_minutes=15,
        )

    def test_create_self_external_card_order_skips_local_inventory_lock(self) -> None:
        tenant = _tenant(status="active")
        product = _product(
            product_id=31,
            delivery_type="card_pool",
            external_source="acg",
            source_key="main",
            external_id="sku-1",
        )
        variant = _variant(variant_id=310, price=Decimal("8.50"))
        session = _FakeSession(tenant=tenant)

        with patch("app.services.orders.ProductRepository") as product_repo, patch(
            "app.services.orders.InventoryService",
        ) as inventory_service, patch("app.services.orders.RiskControlService") as risk_service:
            product_repo.return_value.get_product_with_default_variant = AsyncMock(return_value=(product, variant))
            risk_check = risk_service.return_value.ensure_order_creation_allowed = AsyncMock()
            created = asyncio.run(
                OrderService().create_self_order(
                    session=session,
                    tenant_id=7,
                    buyer_telegram_user_id=42,
                    product_id=31,
                    order_timeout_minutes=15,
                )
            )

        risk_check.assert_awaited_once()
        inventory_service.assert_not_called()
        self.assertIsNone(created.locked_inventory_item_id)
        self.assertEqual(1, session.flush_count)
        self.assertEqual(1, len(session.added))
        order = session.added[0]
        self.assertEqual(31, order.self_product_id)
        self.assertIsNone(order.locked_inventory_item_id)

    def test_create_self_order_rejects_suspended_tenant_before_product_lookup(self) -> None:
        session = _FakeSession(tenant=_tenant(status="suspended"))

        with patch("app.services.orders.ProductRepository") as product_repo:
            product_lookup = AsyncMock()
            product_repo.return_value.get_product_with_default_variant = product_lookup
            with self.assertRaisesRegex(ValueError, "店铺当前不可下单"):
                asyncio.run(
                    OrderService().create_self_order(
                        session=session,
                        tenant_id=7,
                        buyer_telegram_user_id=42,
                        product_id=3,
                        order_timeout_minutes=15,
                    )
                )

        self.assertEqual(0, product_lookup.await_count)
        self.assertEqual([], session.added)
        self.assertEqual(0, session.flush_count)

    def test_create_self_order_rejects_disabled_self_sale_before_product_lookup(self) -> None:
        session = _FakeSession(tenant=_tenant(status="active", self_sale_enabled=False))

        with patch("app.services.orders.ProductRepository") as product_repo:
            product_lookup = AsyncMock()
            product_repo.return_value.get_product_with_default_variant = product_lookup
            with self.assertRaisesRegex(ValueError, "自营商品售卖功能已关闭"):
                asyncio.run(
                    OrderService().create_self_order(
                        session=session,
                        tenant_id=7,
                        buyer_telegram_user_id=42,
                        product_id=3,
                        order_timeout_minutes=15,
                    )
                )

        self.assertEqual(0, product_lookup.await_count)
        self.assertEqual([], session.added)
        self.assertEqual(0, session.flush_count)

    def test_create_self_order_rejects_retention_expired_tenant_before_product_lookup(self) -> None:
        session = _FakeSession(tenant=_tenant(status="retention_expired"))

        with patch("app.services.orders.ProductRepository") as product_repo:
            product_lookup = AsyncMock()
            product_repo.return_value.get_product_with_default_variant = product_lookup
            with self.assertRaisesRegex(ValueError, "店铺当前不可下单"):
                asyncio.run(
                    OrderService().create_self_order(
                        session=session,
                        tenant_id=7,
                        buyer_telegram_user_id=42,
                        product_id=3,
                        order_timeout_minutes=15,
                    )
                )

        self.assertEqual(0, product_lookup.await_count)
        self.assertEqual([], session.added)
        self.assertEqual(0, session.flush_count)

    def test_create_self_order_allows_grace_tenant(self) -> None:
        session = _FakeSession(tenant=_tenant(status="grace"))
        product = _product(product_id=4, delivery_type="file_download", delivery_file_id=101)
        variant = _variant(variant_id=40, price=Decimal("6.00"))

        with patch("app.services.orders.ProductRepository") as product_repo, patch(
            "app.services.orders.InventoryService",
        ) as inventory_service, patch("app.services.orders.RiskControlService") as risk_service:
            product_repo.return_value.get_product_with_default_variant = AsyncMock(return_value=(product, variant))
            risk_check = risk_service.return_value.ensure_order_creation_allowed = AsyncMock()
            created = asyncio.run(
                OrderService().create_self_order(
                    session=session,
                    tenant_id=7,
                    buyer_telegram_user_id=42,
                    product_id=4,
                    order_timeout_minutes=15,
                )
            )

        risk_check.assert_awaited_once()
        inventory_service.assert_not_called()
        self.assertEqual(1001, created.order_id)
        self.assertEqual(Decimal("6.00"), created.amount)
        self.assertIsNone(created.locked_inventory_item_id)
        self.assertEqual(1, len(session.added))
        self.assertEqual(1, session.flush_count)

    def test_create_self_file_order_requires_delivery_file(self) -> None:
        session = _FakeSession(tenant=_tenant(status="active"))
        product = _product(product_id=4, delivery_type="file_download", delivery_file_id=None)
        variant = _variant(variant_id=40)

        with patch("app.services.orders.ProductRepository") as product_repo, patch(
            "app.services.orders.InventoryService",
        ) as inventory_service, patch("app.services.orders.RiskControlService") as risk_service:
            product_repo.return_value.get_product_with_default_variant = AsyncMock(return_value=(product, variant))
            risk_service.return_value.ensure_order_creation_allowed = AsyncMock()
            with self.assertRaisesRegex(ValueError, "文件商品尚未绑定交付文件"):
                asyncio.run(
                    OrderService().create_self_order(
                        session=session,
                        tenant_id=7,
                        buyer_telegram_user_id=42,
                        product_id=4,
                        order_timeout_minutes=15,
                    )
                )

        inventory_service.assert_not_called()
        self.assertEqual([], session.added)
        self.assertEqual(0, session.flush_count)

    def test_create_self_order_rejects_risk_before_order_or_inventory_lock(self) -> None:
        session = _FakeSession(tenant=_tenant(status="active"))
        product = _product(product_id=8, delivery_type="card_pool")
        variant = _variant(variant_id=80, price=Decimal("20.00"))

        with patch("app.services.orders.ProductRepository") as product_repo, patch(
            "app.services.orders.InventoryService",
        ) as inventory_service, patch("app.services.orders.RiskControlService") as risk_service:
            product_repo.return_value.get_product_with_default_variant = AsyncMock(return_value=(product, variant))
            risk_service.return_value.ensure_order_creation_allowed = AsyncMock(
                side_effect=ValueError("下单过于频繁，请稍后再试")
            )
            with self.assertRaisesRegex(ValueError, "下单过于频繁"):
                asyncio.run(
                    OrderService().create_self_order(
                        session=session,
                        tenant_id=7,
                        buyer_telegram_user_id=42,
                        product_id=8,
                        order_timeout_minutes=15,
                    )
                )

        inventory_service.assert_not_called()
        self.assertEqual([], session.added)
        self.assertEqual(0, session.flush_count)

    def test_create_self_telegram_invite_order_requires_chat_id(self) -> None:
        session = _FakeSession(tenant=_tenant(status="active"))
        product = _product(product_id=5, delivery_type="telegram_invite", telegram_chat_id=None)
        variant = _variant(variant_id=50)

        with patch("app.services.orders.ProductRepository") as product_repo:
            product_repo.return_value.get_product_with_default_variant = AsyncMock(return_value=(product, variant))
            with self.assertRaisesRegex(ValueError, "群邀请商品尚未绑定群 ID"):
                asyncio.run(
                    OrderService().create_self_order(
                        session=session,
                        tenant_id=7,
                        buyer_telegram_user_id=42,
                        product_id=5,
                        order_timeout_minutes=15,
                    )
                )

        self.assertEqual([], session.added)
        self.assertEqual(0, session.flush_count)

    def test_create_self_card_order_rejects_inventory_shortage(self) -> None:
        tenant = _tenant(status="active")
        product = _product(product_id=6, delivery_type="card_fixed")
        variant = _variant(variant_id=60)
        session = _FakeSession(tenant=tenant)
        lock_inventory = AsyncMock(return_value=None)

        with patch("app.services.orders.ProductRepository") as product_repo, patch(
            "app.services.orders.InventoryService",
        ) as inventory_service, patch("app.services.orders.RiskControlService") as risk_service:
            product_repo.return_value.get_product_with_default_variant = AsyncMock(return_value=(product, variant))
            risk_service.return_value.ensure_order_creation_allowed = AsyncMock()
            inventory_service.return_value.lock_one_available_item = lock_inventory
            with self.assertRaisesRegex(ValueError, "库存不足"):
                asyncio.run(
                    OrderService().create_self_order(
                        session=session,
                        tenant_id=7,
                        buyer_telegram_user_id=42,
                        product_id=6,
                        order_timeout_minutes=15,
                    )
                )

        self.assertEqual(1, len(session.added))
        self.assertIsNone(session.added[0].locked_inventory_item_id)
        self.assertEqual(1, session.flush_count)

    def test_create_reseller_card_order_locks_supplier_inventory(self) -> None:
        tenant = _tenant(status="active")
        reseller_product = _reseller_product(sale_price=Decimal("15.00"))
        offer = _supplier_offer(supplier_tenant_id=88, cost=Decimal("9.00"))
        product = _product(product_id=11, delivery_type="card_pool")
        variant = _variant(variant_id=110, price=Decimal("12.00"))
        session = _FakeSession(
            tenant=tenant,
            reseller_row=(reseller_product, offer, product, variant, None),
        )
        lock_inventory = AsyncMock(return_value=SimpleNamespace(inventory_item_id=777))

        with patch("app.services.orders.InventoryService") as inventory_service, patch(
            "app.services.orders.RiskControlService"
        ) as risk_service:
            inventory_service.return_value.lock_one_available_item = lock_inventory
            risk_check = risk_service.return_value.ensure_order_creation_allowed = AsyncMock()
            created = asyncio.run(
                OrderService().create_reseller_order(
                    session=session,
                    tenant_id=7,
                    buyer_telegram_user_id=42,
                    reseller_product_id=71,
                    order_timeout_minutes=20,
                )
            )

        risk_check.assert_awaited_once_with(
            session=session,
            buyer_telegram_user_id=42,
            amount=Decimal("15.00"),
            currency="USDT",
            tenant_id=7,
            source_type="reseller",
        )
        self.assertEqual(1001, created.order_id)
        self.assertEqual(Decimal("15.00"), created.amount)
        self.assertEqual(777, created.locked_inventory_item_id)
        self.assertEqual(2, session.flush_count)
        self.assertEqual(1, len(session.added))
        order = session.added[0]
        self.assertEqual("reseller", order.source_type)
        self.assertEqual(7, order.tenant_id)
        self.assertEqual(88, order.supplier_tenant_id)
        self.assertEqual(11, order.self_product_id)
        self.assertEqual(71, order.reseller_product_id)
        self.assertEqual(Decimal("9.00"), order.supplier_settlement_amount)
        self.assertEqual(Decimal("6.00"), order.reseller_settlement_amount)
        self.assertEqual(777, order.locked_inventory_item_id)
        lock_inventory.assert_awaited_once_with(
            session=session,
            tenant_id=88,
            product_id=11,
            order_id=1001,
            lock_minutes=20,
        )

    def test_create_reseller_order_rejects_price_below_supplier_cost_before_inventory_lock(self) -> None:
        tenant = _tenant(status="active")
        reseller_product = _reseller_product(sale_price=Decimal("8.00"))
        offer = _supplier_offer(supplier_tenant_id=88, cost=Decimal("9.00"))
        product = _product(product_id=12, delivery_type="card_pool")
        variant = _variant(variant_id=120)
        session = _FakeSession(
            tenant=tenant,
            reseller_row=(reseller_product, offer, product, variant, None),
        )

        with patch("app.services.orders.InventoryService") as inventory_service:
            with self.assertRaisesRegex(ValueError, "代理商品售价低于供应商成本"):
                asyncio.run(
                    OrderService().create_reseller_order(
                        session=session,
                        tenant_id=7,
                        buyer_telegram_user_id=42,
                        reseller_product_id=71,
                        order_timeout_minutes=20,
                    )
                )

        inventory_service.assert_not_called()
        self.assertEqual([], session.added)
        self.assertEqual(0, session.flush_count)

    def test_create_reseller_order_rejects_disabled_reseller_before_offer_query(self) -> None:
        tenant = _tenant(status="active", reseller_enabled=False)
        session = _FakeSession(tenant=tenant, reseller_row=None)

        with self.assertRaisesRegex(ValueError, "代理售卖功能已关闭"):
            asyncio.run(
                OrderService().create_reseller_order(
                    session=session,
                    tenant_id=7,
                    buyer_telegram_user_id=42,
                    reseller_product_id=71,
                    order_timeout_minutes=20,
                )
            )

        self.assertEqual([], session.added)
        self.assertEqual(0, session.flush_count)

    def test_create_reseller_order_rejects_disabled_supplier_before_inventory_lock(self) -> None:
        tenant = _tenant(status="active")
        reseller_product = _reseller_product(sale_price=Decimal("15.00"))
        offer = _supplier_offer(supplier_tenant_id=88, cost=Decimal("9.00"))
        product = _product(product_id=11, delivery_type="card_pool")
        variant = _variant(variant_id=110, price=Decimal("12.00"))
        session = _FakeSession(
            tenant=tenant,
            reseller_row=(reseller_product, offer, product, variant, None),
            related_tenants={88: _tenant(status="active", tenant_id=88, supplier_enabled=False)},
        )

        with patch("app.services.orders.InventoryService") as inventory_service:
            with self.assertRaisesRegex(ValueError, "供货功能已关闭"):
                asyncio.run(
                    OrderService().create_reseller_order(
                        session=session,
                        tenant_id=7,
                        buyer_telegram_user_id=42,
                        reseller_product_id=71,
                        order_timeout_minutes=20,
                    )
                )

        inventory_service.assert_not_called()
        self.assertEqual([], session.added)
        self.assertEqual(0, session.flush_count)

    def test_create_reseller_order_rejects_risk_before_order_or_inventory_lock(self) -> None:
        tenant = _tenant(status="active")
        reseller_product = _reseller_product(sale_price=Decimal("15.00"))
        offer = _supplier_offer(supplier_tenant_id=88, cost=Decimal("9.00"))
        product = _product(product_id=14, delivery_type="card_pool")
        variant = _variant(variant_id=140)
        session = _FakeSession(
            tenant=tenant,
            reseller_row=(reseller_product, offer, product, variant, None),
        )

        with patch("app.services.orders.InventoryService") as inventory_service, patch(
            "app.services.orders.RiskControlService"
        ) as risk_service:
            risk_service.return_value.ensure_order_creation_allowed = AsyncMock(
                side_effect=ValueError("下单金额触发平台风控，请稍后再试")
            )
            with self.assertRaisesRegex(ValueError, "下单金额触发平台风控"):
                asyncio.run(
                    OrderService().create_reseller_order(
                        session=session,
                        tenant_id=7,
                        buyer_telegram_user_id=42,
                        reseller_product_id=71,
                        order_timeout_minutes=20,
                    )
                )

        inventory_service.assert_not_called()
        self.assertEqual([], session.added)
        self.assertEqual(0, session.flush_count)

    def test_create_reseller_order_rejects_unsupported_delivery_type_before_inventory_lock(self) -> None:
        tenant = _tenant(status="active")
        reseller_product = _reseller_product(sale_price=Decimal("15.00"))
        offer = _supplier_offer(supplier_tenant_id=88, cost=Decimal("9.00"))
        product = _product(product_id=13, delivery_type="telegram_invite", telegram_chat_id=-100123)
        variant = _variant(variant_id=130)
        session = _FakeSession(
            tenant=tenant,
            reseller_row=(reseller_product, offer, product, variant, None),
        )

        with patch("app.services.orders.InventoryService") as inventory_service:
            with self.assertRaisesRegex(ValueError, "当前代理下单暂不支持该发货类型"):
                asyncio.run(
                    OrderService().create_reseller_order(
                        session=session,
                        tenant_id=7,
                        buyer_telegram_user_id=42,
                        reseller_product_id=71,
                        order_timeout_minutes=20,
                    )
                )

        inventory_service.assert_not_called()
        self.assertEqual([], session.added)
        self.assertEqual(0, session.flush_count)


def _tenant(
    *,
    status: str,
    tenant_id: int = 7,
    self_sale_enabled: bool = True,
    supplier_enabled: bool = True,
    reseller_enabled: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=tenant_id,
        status=status,
        self_sale_enabled=self_sale_enabled,
        supplier_enabled=supplier_enabled,
        reseller_enabled=reseller_enabled,
    )


def _product(
    *,
    product_id: int,
    delivery_type: str,
    status: str = "on",
    delivery_file_id: int | None = None,
    telegram_chat_id: int | None = None,
    external_source: str | None = None,
    source_key: str = "",
    external_id: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=product_id,
        status=status,
        delivery_type=delivery_type,
        delivery_file_id=delivery_file_id,
        telegram_chat_id=telegram_chat_id,
        external_source=external_source,
        source_key=source_key,
        external_id=external_id,
    )


def _variant(
    *,
    variant_id: int,
    price: Decimal = Decimal("10.00"),
    status: str = "on",
) -> SimpleNamespace:
    return SimpleNamespace(id=variant_id, price=price, currency="USDT", status=status)


def _reseller_product(*, sale_price: Decimal) -> SimpleNamespace:
    return SimpleNamespace(
        id=71,
        reseller_tenant_id=7,
        supplier_tenant_id=88,
        supplier_offer_id=91,
        sale_price=sale_price,
    )


def _supplier_offer(*, supplier_tenant_id: int, cost: Decimal) -> SimpleNamespace:
    return SimpleNamespace(
        id=91,
        supplier_tenant_id=supplier_tenant_id,
        default_pricing_mode="fixed_cost",
        default_pricing_value=cost,
        min_sale_price=None,
    )


if __name__ == "__main__":
    unittest.main()
