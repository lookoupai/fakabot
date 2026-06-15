from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

try:
    from app.config import Settings
    from app.db.models.orders import DeliveryRecord
    from app.db.models.products import Product
    from app.services.payments.service import PaymentService
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过发货记录创建服务测试：{exc.name}") from exc


class _ScalarResult:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object | None:
        return self._value


class _FakeSession:
    def __init__(
        self,
        *,
        product: SimpleNamespace | None,
        delivery: DeliveryRecord | None = None,
    ) -> None:
        self.product = product
        self.delivery = delivery
        self.added_deliveries: list[DeliveryRecord] = []
        self.flush_count = 0
        self.next_delivery_id = 501

    async def get(self, model: object, item_id: int) -> object | None:
        if model is Product and self.product is not None and self.product.id == item_id:
            return self.product
        return None

    async def execute(self, query: object) -> _ScalarResult:
        return _ScalarResult(self.delivery)

    def add(self, obj: object) -> None:
        if isinstance(obj, DeliveryRecord):
            obj.id = self.next_delivery_id
            self.next_delivery_id += 1
            self.delivery = obj
            self.added_deliveries.append(obj)

    async def flush(self) -> None:
        self.flush_count += 1


class DeliveryRecordEnsureServiceTest(unittest.TestCase):
    def test_card_pool_creates_delivery_record_and_marks_inventory_used(self) -> None:
        order = _order(self_product_id=101, locked_inventory_item_id=301)
        session = _FakeSession(product=_product(product_id=101, delivery_type="card_pool"))
        service = PaymentService(Settings())
        mark_used = AsyncMock(return_value=True)

        with patch("app.services.payments.service.InventoryService") as inventory_service:
            inventory_service.return_value.mark_locked_item_used = mark_used
            delivery_id = asyncio.run(service._ensure_delivery_record(session, order))

        self.assertEqual(501, delivery_id)
        mark_used.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            inventory_item_id=301,
            order_id=12,
        )
        self.assertEqual(1, len(session.added_deliveries))
        delivery = session.added_deliveries[0]
        self.assertEqual(12, delivery.order_id)
        self.assertEqual(7, delivery.tenant_id)
        self.assertEqual(42, delivery.buyer_telegram_user_id)
        self.assertEqual("card_pool", delivery.delivery_type)
        self.assertEqual(301, delivery.inventory_item_id)
        self.assertEqual("pending", delivery.status)
        self.assertEqual(1, session.flush_count)

    def test_card_fixed_reuses_pending_delivery_record(self) -> None:
        order = _order(self_product_id=102, locked_inventory_item_id=302)
        existing_delivery = _delivery(delivery_id=99, delivery_type="card_fixed", status="pending")
        session = _FakeSession(
            product=_product(product_id=102, delivery_type="card_fixed"),
            delivery=existing_delivery,
        )
        service = PaymentService(Settings())
        mark_used = AsyncMock(return_value=True)

        with patch("app.services.payments.service.InventoryService") as inventory_service:
            inventory_service.return_value.mark_locked_item_used = mark_used
            delivery_id = asyncio.run(service._ensure_delivery_record(session, order))

        self.assertEqual(99, delivery_id)
        self.assertEqual([], session.added_deliveries)
        mark_used.assert_awaited_once()
        self.assertEqual(0, session.flush_count)

    def test_card_pool_sent_delivery_returns_none_without_new_record(self) -> None:
        order = _order(self_product_id=103, locked_inventory_item_id=303)
        existing_delivery = _delivery(delivery_id=100, delivery_type="card_pool", status="sent")
        session = _FakeSession(
            product=_product(product_id=103, delivery_type="card_pool"),
            delivery=existing_delivery,
        )
        service = PaymentService(Settings())
        mark_used = AsyncMock(return_value=True)

        with patch("app.services.payments.service.InventoryService") as inventory_service:
            inventory_service.return_value.mark_locked_item_used = mark_used
            delivery_id = asyncio.run(service._ensure_delivery_record(session, order))

        self.assertIsNone(delivery_id)
        self.assertEqual([], session.added_deliveries)
        mark_used.assert_awaited_once()
        self.assertEqual(0, session.flush_count)

    def test_card_inventory_failure_raises_without_delivery_record(self) -> None:
        order = _order(self_product_id=104, locked_inventory_item_id=304)
        session = _FakeSession(product=_product(product_id=104, delivery_type="card_pool"))
        service = PaymentService(Settings())
        mark_used = AsyncMock(return_value=False)

        with patch("app.services.payments.service.InventoryService") as inventory_service:
            inventory_service.return_value.mark_locked_item_used = mark_used
            with self.assertRaisesRegex(ValueError, "锁定库存状态异常"):
                asyncio.run(service._ensure_delivery_record(session, order))

        self.assertEqual([], session.added_deliveries)
        self.assertEqual(0, session.flush_count)

    def test_external_card_order_defers_delivery_to_external_worker(self) -> None:
        order = _order(self_product_id=105, locked_inventory_item_id=None)
        session = _FakeSession(
            product=_product(
                product_id=105,
                delivery_type="card_pool",
                external_source="acg",
                source_key="main",
                external_id="sku-1",
            )
        )
        service = PaymentService(Settings())

        with patch("app.services.payments.service.InventoryService") as inventory_service:
            delivery_id = asyncio.run(service._ensure_delivery_record(session, order))

        self.assertIsNone(delivery_id)
        inventory_service.assert_not_called()
        self.assertEqual([], session.added_deliveries)
        self.assertEqual(0, session.flush_count)

    def test_file_download_creates_then_reuses_existing_delivery_record(self) -> None:
        order = _order(self_product_id=201, locked_inventory_item_id=None)
        session = _FakeSession(
            product=_product(product_id=201, delivery_type="file_download", delivery_file_id=801),
        )
        service = PaymentService(Settings())

        first_delivery_id = asyncio.run(service._ensure_delivery_record(session, order))
        second_delivery_id = asyncio.run(service._ensure_delivery_record(session, order))

        self.assertEqual(501, first_delivery_id)
        self.assertEqual(501, second_delivery_id)
        self.assertEqual(1, len(session.added_deliveries))
        delivery = session.added_deliveries[0]
        self.assertEqual("file_download", delivery.delivery_type)
        self.assertEqual(801, delivery.uploaded_file_id)
        self.assertEqual("pending", delivery.status)
        self.assertEqual(1, session.flush_count)

    def test_file_download_sent_delivery_returns_none(self) -> None:
        order = _order(self_product_id=202, locked_inventory_item_id=None)
        session = _FakeSession(
            product=_product(product_id=202, delivery_type="file_download", delivery_file_id=802),
            delivery=_delivery(delivery_id=101, delivery_type="file_download", status="sent", uploaded_file_id=802),
        )
        service = PaymentService(Settings())

        delivery_id = asyncio.run(service._ensure_delivery_record(session, order))

        self.assertIsNone(delivery_id)
        self.assertEqual([], session.added_deliveries)

    def test_file_download_missing_file_raises(self) -> None:
        order = _order(self_product_id=203, locked_inventory_item_id=None)
        session = _FakeSession(product=_product(product_id=203, delivery_type="file_download"))
        service = PaymentService(Settings())

        with self.assertRaisesRegex(ValueError, "文件商品未绑定交付文件"):
            asyncio.run(service._ensure_delivery_record(session, order))

    def test_telegram_invite_creates_then_reuses_existing_delivery_record(self) -> None:
        order = _order(self_product_id=301, locked_inventory_item_id=None)
        session = _FakeSession(
            product=_product(product_id=301, delivery_type="telegram_invite", telegram_chat_id=-100123456789),
        )
        service = PaymentService(Settings())

        first_delivery_id = asyncio.run(service._ensure_delivery_record(session, order))
        second_delivery_id = asyncio.run(service._ensure_delivery_record(session, order))

        self.assertEqual(501, first_delivery_id)
        self.assertEqual(501, second_delivery_id)
        self.assertEqual(1, len(session.added_deliveries))
        delivery = session.added_deliveries[0]
        self.assertEqual("telegram_invite", delivery.delivery_type)
        self.assertEqual(-100123456789, delivery.telegram_chat_id)
        self.assertEqual("pending", delivery.status)
        self.assertEqual(1, session.flush_count)

    def test_telegram_invite_missing_chat_raises(self) -> None:
        order = _order(self_product_id=302, locked_inventory_item_id=None)
        session = _FakeSession(product=_product(product_id=302, delivery_type="telegram_invite"))
        service = PaymentService(Settings())

        with self.assertRaisesRegex(ValueError, "群邀请商品未绑定群 ID"):
            asyncio.run(service._ensure_delivery_record(session, order))


def _order(
    *,
    self_product_id: int,
    locked_inventory_item_id: int | None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=12,
        tenant_id=7,
        buyer_telegram_user_id=42,
        status="paid",
        source_type="self",
        supplier_tenant_id=None,
        self_product_id=self_product_id,
        locked_inventory_item_id=locked_inventory_item_id,
    )


def _product(
    *,
    product_id: int,
    delivery_type: str,
    delivery_file_id: int | None = None,
    telegram_chat_id: int | None = None,
    external_source: str | None = None,
    source_key: str = "",
    external_id: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=product_id,
        delivery_type=delivery_type,
        delivery_file_id=delivery_file_id,
        telegram_chat_id=telegram_chat_id,
        external_source=external_source,
        source_key=source_key,
        external_id=external_id,
    )


def _delivery(
    *,
    delivery_id: int,
    delivery_type: str,
    status: str,
    uploaded_file_id: int | None = None,
    telegram_chat_id: int | None = None,
) -> DeliveryRecord:
    return DeliveryRecord(
        id=delivery_id,
        order_id=12,
        tenant_id=7,
        buyer_telegram_user_id=42,
        delivery_type=delivery_type,
        inventory_item_id=301 if delivery_type in {"card_pool", "card_fixed"} else None,
        uploaded_file_id=uploaded_file_id,
        telegram_chat_id=telegram_chat_id,
        status=status,
    )


if __name__ == "__main__":
    unittest.main()
