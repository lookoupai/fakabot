from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest

try:
    from app.config import Settings
    from app.db.models.orders import DeliveryRecord, Order
    from app.db.models.products import InventoryItem, UploadedFile
    from app.services.payments.service import PaymentService
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过发货领取服务测试：{exc.name}") from exc


class _ScalarResult:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object | None:
        return self._value


class _ScalarListResult:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def scalars(self) -> "_ScalarListResult":
        return self

    def all(self) -> list[object]:
        return self._values


class _ListSession:
    def __init__(self, values: list[object]) -> None:
        self.values = values
        self.flush_count = 0

    async def execute(self, query: object) -> _ScalarListResult:
        return _ScalarListResult(self.values)

    async def flush(self) -> None:
        self.flush_count += 1


class _FakeSession:
    def __init__(
        self,
        *,
        delivery: SimpleNamespace,
        order: SimpleNamespace | None = None,
        inventory_item: SimpleNamespace | None = None,
        uploaded_file: SimpleNamespace | None = None,
    ) -> None:
        self.delivery = delivery
        self.order = order
        self.inventory_item = inventory_item
        self.uploaded_file = uploaded_file
        self.flush_count = 0

    async def execute(self, query: object) -> _ScalarResult:
        if self.delivery.status in {"pending", "failed"}:
            return _ScalarResult(self.delivery)
        return _ScalarResult(None)

    async def get(self, model: object, item_id: int) -> object | None:
        if model is DeliveryRecord and self.delivery.id == item_id:
            return self.delivery
        if model is Order and self.order is not None and self.order.id == item_id:
            return self.order
        if model is InventoryItem and self.inventory_item is not None and self.inventory_item.id == item_id:
            return self.inventory_item
        if model is UploadedFile and self.uploaded_file is not None and self.uploaded_file.id == item_id:
            return self.uploaded_file
        return None

    async def flush(self) -> None:
        self.flush_count += 1


class DeliveryClaimServiceTest(unittest.TestCase):
    def test_list_pending_delivery_record_ids_returns_int_ids(self) -> None:
        service = PaymentService(Settings())

        delivery_ids = asyncio.run(service.list_pending_delivery_record_ids(_ListSession([11, "12"]), limit=2))

        self.assertEqual([11, 12], delivery_ids)

    def test_list_pending_delivery_record_ids_rejects_invalid_limit(self) -> None:
        service = PaymentService(Settings())

        with self.assertRaisesRegex(ValueError, "limit"):
            asyncio.run(service.list_pending_delivery_record_ids(_ListSession([]), limit=0))

    def test_recover_stale_sending_deliveries_marks_failed(self) -> None:
        service = PaymentService(Settings())
        delivery = _card_delivery(status="sending", error_message=None)
        session = _ListSession([delivery])

        recovered_count = asyncio.run(
            service.recover_stale_sending_deliveries(session, timeout_seconds=300, limit=10)
        )

        self.assertEqual(1, recovered_count)
        self.assertEqual("failed", delivery.status)
        self.assertEqual("发货发送超时，已标记为可手动重试", delivery.error_message)
        self.assertEqual(1, session.flush_count)

    def test_recover_stale_sending_deliveries_without_matches_does_not_flush(self) -> None:
        service = PaymentService(Settings())
        session = _ListSession([])

        recovered_count = asyncio.run(
            service.recover_stale_sending_deliveries(session, timeout_seconds=300, limit=10)
        )

        self.assertEqual(0, recovered_count)
        self.assertEqual(0, session.flush_count)

    def test_recover_stale_sending_deliveries_rejects_invalid_arguments(self) -> None:
        service = PaymentService(Settings())

        with self.assertRaisesRegex(ValueError, "timeout_seconds"):
            asyncio.run(service.recover_stale_sending_deliveries(_ListSession([]), timeout_seconds=0))
        with self.assertRaisesRegex(ValueError, "limit"):
            asyncio.run(service.recover_stale_sending_deliveries(_ListSession([]), timeout_seconds=300, limit=0))

    def test_pending_card_delivery_claim_sets_sending_and_returns_instruction(self) -> None:
        delivery = _card_delivery(status="pending")
        order = _order()
        inventory_item = SimpleNamespace(id=5, tenant_id=7, content_encrypted="encrypted-card")
        session = _FakeSession(delivery=delivery, order=order, inventory_item=inventory_item)
        service = PaymentService(Settings())

        instruction = asyncio.run(service.claim_delivery(session, delivery.id))
        second_claim = asyncio.run(service.claim_delivery(session, delivery.id))

        self.assertIsNotNone(instruction)
        assert instruction is not None
        self.assertEqual("sending", delivery.status)
        self.assertIsNone(delivery.error_message)
        self.assertEqual(99, instruction.delivery_record_id)
        self.assertEqual(12, instruction.order_id)
        self.assertEqual(7, instruction.tenant_id)
        self.assertEqual(42, instruction.buyer_telegram_user_id)
        self.assertEqual("card_pool", instruction.delivery_type)
        self.assertEqual("ORD123", instruction.out_trade_no)
        self.assertEqual("encrypted-card", instruction.encrypted_content)
        self.assertIsNone(second_claim)
        self.assertEqual(1, session.flush_count)

    def test_failed_delivery_can_be_claimed_again(self) -> None:
        delivery = _card_delivery(status="failed", error_message="上次失败")
        order = _order()
        inventory_item = SimpleNamespace(id=5, tenant_id=7, content_encrypted="encrypted-card")
        session = _FakeSession(delivery=delivery, order=order, inventory_item=inventory_item)
        service = PaymentService(Settings())

        instruction = asyncio.run(service.claim_delivery(session, delivery.id))

        self.assertIsNotNone(instruction)
        self.assertEqual("sending", delivery.status)
        self.assertIsNone(delivery.error_message)
        self.assertEqual(1, session.flush_count)

    def test_sent_delivery_is_not_claimed_again(self) -> None:
        delivery = _card_delivery(status="sent")
        session = _FakeSession(delivery=delivery, order=_order())
        service = PaymentService(Settings())

        instruction = asyncio.run(service.claim_delivery(session, delivery.id))

        self.assertIsNone(instruction)
        self.assertEqual("sent", delivery.status)
        self.assertEqual(0, session.flush_count)

    def test_inventory_tenant_mismatch_marks_delivery_failed(self) -> None:
        delivery = _card_delivery(status="pending")
        order = _order()
        inventory_item = SimpleNamespace(id=5, tenant_id=8, content_encrypted="encrypted-card")
        session = _FakeSession(delivery=delivery, order=order, inventory_item=inventory_item)
        service = PaymentService(Settings())

        instruction = asyncio.run(service.claim_delivery(session, delivery.id))

        self.assertIsNone(instruction)
        self.assertEqual("failed", delivery.status)
        self.assertEqual("发货库存租户不匹配", delivery.error_message)
        self.assertEqual(1, session.flush_count)

    def test_file_delivery_without_uploaded_file_id_marks_failed(self) -> None:
        delivery = _file_delivery(status="pending", uploaded_file_id=None)
        session = _FakeSession(delivery=delivery, order=_order())
        service = PaymentService(Settings())

        instruction = asyncio.run(service.claim_delivery(session, delivery.id))

        self.assertIsNone(instruction)
        self.assertEqual("failed", delivery.status)
        self.assertEqual("发货文件不存在", delivery.error_message)
        self.assertEqual(1, session.flush_count)

    def test_file_delivery_missing_uploaded_file_marks_failed(self) -> None:
        delivery = _file_delivery(status="pending", uploaded_file_id=77)
        session = _FakeSession(delivery=delivery, order=_order(), uploaded_file=None)
        service = PaymentService(Settings())

        instruction = asyncio.run(service.claim_delivery(session, delivery.id))

        self.assertIsNone(instruction)
        self.assertEqual("failed", delivery.status)
        self.assertEqual("发货文件不存在", delivery.error_message)
        self.assertEqual(1, session.flush_count)

    def test_file_delivery_blocked_uploaded_file_marks_failed(self) -> None:
        delivery = _file_delivery(status="pending", uploaded_file_id=77)
        uploaded_file = SimpleNamespace(id=77, tenant_id=7, status="blocked")
        session = _FakeSession(delivery=delivery, order=_order(), uploaded_file=uploaded_file)
        service = PaymentService(Settings())

        instruction = asyncio.run(service.claim_delivery(session, delivery.id))

        self.assertIsNone(instruction)
        self.assertEqual("failed", delivery.status)
        self.assertEqual("发货文件不存在", delivery.error_message)
        self.assertEqual(1, session.flush_count)

    def test_file_delivery_active_uploaded_file_returns_safe_instruction(self) -> None:
        delivery = _file_delivery(status="pending", uploaded_file_id=77)
        uploaded_file = SimpleNamespace(
            id=77,
            tenant_id=9,
            status="active",
            storage_key="tenants/9/files/private.zip",
        )
        session = _FakeSession(delivery=delivery, order=_order(), uploaded_file=uploaded_file)
        service = PaymentService(Settings())

        instruction = asyncio.run(service.claim_delivery(session, delivery.id))

        self.assertIsNotNone(instruction)
        assert instruction is not None
        self.assertEqual("sending", delivery.status)
        self.assertIsNone(delivery.error_message)
        self.assertEqual("file_download", instruction.delivery_type)
        self.assertEqual(77, instruction.uploaded_file_id)
        self.assertEqual(9, instruction.uploaded_file_tenant_id)
        self.assertIsNone(instruction.encrypted_content)
        self.assertEqual(1, session.flush_count)

    def test_mark_delivery_sent_marks_order_delivered(self) -> None:
        delivery = _card_delivery(status="sending", error_message="发送中断")
        order = _order()
        order.status = "paid"
        order.delivered_at = None
        session = _FakeSession(delivery=delivery, order=order)
        service = PaymentService(Settings())

        asyncio.run(service.mark_delivery_sent(session, delivery.id))

        self.assertEqual("sent", delivery.status)
        self.assertIsNone(delivery.error_message)
        self.assertIsNotNone(delivery.sent_at)
        self.assertEqual("delivered", order.status)
        self.assertIsNotNone(order.delivered_at)
        self.assertEqual(1, session.flush_count)

    def test_mark_delivery_failed_records_truncated_error(self) -> None:
        delivery = _card_delivery(status="sending")
        session = _FakeSession(delivery=delivery, order=_order())
        service = PaymentService(Settings())

        asyncio.run(service.mark_delivery_failed(session, delivery.id, "x" * 1200))

        self.assertEqual("failed", delivery.status)
        self.assertEqual(1000, len(delivery.error_message))
        self.assertEqual(1, session.flush_count)


def _order() -> SimpleNamespace:
    return SimpleNamespace(
        id=12,
        tenant_id=7,
        source_type="self",
        supplier_tenant_id=None,
        out_trade_no="ORD123",
    )


def _card_delivery(*, status: str, error_message: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=99,
        order_id=12,
        tenant_id=7,
        buyer_telegram_user_id=42,
        delivery_type="card_pool",
        inventory_item_id=5,
        uploaded_file_id=None,
        telegram_chat_id=None,
        status=status,
        error_message=error_message,
    )


def _file_delivery(
    *,
    status: str,
    uploaded_file_id: int | None,
    error_message: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=99,
        order_id=12,
        tenant_id=7,
        buyer_telegram_user_id=42,
        delivery_type="file_download",
        inventory_item_id=None,
        uploaded_file_id=uploaded_file_id,
        telegram_chat_id=None,
        status=status,
        error_message=error_message,
    )


if __name__ == "__main__":
    unittest.main()
