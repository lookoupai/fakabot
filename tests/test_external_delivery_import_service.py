from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest

try:
    from cryptography.fernet import Fernet
    from pydantic import SecretStr

    from app.config import Settings
    from app.db.models.orders import DeliveryRecord
    from app.db.models.products import InventoryItem, Product
    from app.services.external_sources import ExternalDelivery
    from app.services.external_sources.fulfillment import ExternalDeliveryImportService
    from app.services.token_crypto import TokenCrypto
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过外部发货导入测试：{exc.name}") from exc


class _ScalarResult:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object | None:
        return self._value


class _FakeSession:
    def __init__(
        self,
        *,
        order: object | None,
        product: object | None = None,
        delivery_record: DeliveryRecord | None = None,
    ) -> None:
        self.order = order
        self.product = product
        self.delivery_record = delivery_record
        self.added: list[object] = []
        self.flush_count = 0
        self._next_id = 1000

    async def execute(self, query: object) -> _ScalarResult:
        if self.order is not None:
            order = self.order
            self.order = None
            return _ScalarResult(order)
        return _ScalarResult(self.delivery_record)

    async def get(self, model: object, item_id: int) -> object | None:
        if model is Product and self.product is not None and self.product.id == item_id:
            return self.product
        return None

    def add(self, item: object) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        self.flush_count += 1
        for item in self.added:
            if getattr(item, "id", None) is None:
                setattr(item, "id", self._next_id)
                self._next_id += 1


class ExternalDeliveryImportServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.settings = Settings(token_encryption_key=SecretStr(Fernet.generate_key().decode()))
        self.crypto = TokenCrypto(self.settings)
        self.service = ExternalDeliveryImportService()

    async def test_import_delivery_creates_used_inventory_and_pending_delivery_record(self) -> None:
        order = _order()
        product = _product()
        delivery = _delivery(items=(" card-a ", "card-b"), message=" 已发货 ")
        session = _FakeSession(order=order, product=product)

        result = await self.service.import_delivery(
            session,
            tenant_id=7,
            out_trade_no=" ORD123 ",
            provider_name=" acg ",
            source_key=" main ",
            delivery=delivery,
            settings=self.settings,
        )

        inventory_items = [item for item in session.added if isinstance(item, InventoryItem)]
        delivery_records = [item for item in session.added if isinstance(item, DeliveryRecord)]
        self.assertTrue(result.imported)
        self.assertFalse(result.dry_run)
        self.assertEqual("ORD123", result.out_trade_no)
        self.assertEqual("paid", result.order_status)
        self.assertEqual(2, result.item_count)
        self.assertEqual(1, len(inventory_items))
        inventory_item = inventory_items[0]
        self.assertEqual(7, inventory_item.tenant_id)
        self.assertEqual(product.id, inventory_item.product_id)
        self.assertEqual(order.product_variant_id, inventory_item.variant_id)
        self.assertEqual("used", inventory_item.status)
        self.assertEqual(order.id, inventory_item.used_by_order_id)
        self.assertIsNotNone(inventory_item.used_at)
        self.assertNotIn("card-a", inventory_item.content_encrypted)
        self.assertEqual("已发货\n\ncard-a\ncard-b", self.crypto.decrypt_token(inventory_item.content_encrypted))
        expected_hash = self.crypto.token_hash(
            "external-delivery:ORD123:EXT-1:已发货\n\ncard-a\ncard-b"
        )
        self.assertEqual(expected_hash, inventory_item.content_hash)
        self.assertEqual(1, len(delivery_records))
        delivery_record = delivery_records[0]
        self.assertEqual(delivery_record.id, result.delivery_record_id)
        self.assertEqual(order.id, delivery_record.order_id)
        self.assertEqual(order.tenant_id, delivery_record.tenant_id)
        self.assertEqual(order.buyer_telegram_user_id, delivery_record.buyer_telegram_user_id)
        self.assertEqual(product.delivery_type, delivery_record.delivery_type)
        self.assertEqual(inventory_item.id, delivery_record.inventory_item_id)
        self.assertEqual("pending", delivery_record.status)
        self.assertEqual(2, session.flush_count)
        rendered = f"{result!r}"
        self.assertNotIn("card-a", rendered)
        self.assertNotIn("已发货", rendered)
        self.assertNotIn("raw_payload", rendered)

    async def test_import_delivery_dry_run_validates_without_writing(self) -> None:
        session = _FakeSession(order=_order(), product=_product())

        result = await self.service.import_delivery(
            session,
            tenant_id=7,
            out_trade_no="ORD123",
            provider_name="acg",
            source_key="main",
            delivery=_delivery(items=("card-a", "card-b", "card-c")),
            settings=self.settings,
            dry_run=True,
        )

        self.assertFalse(result.imported)
        self.assertTrue(result.dry_run)
        self.assertIsNone(result.delivery_record_id)
        self.assertEqual(3, result.item_count)
        self.assertEqual([], session.added)
        self.assertEqual(0, session.flush_count)

    async def test_import_delivery_reuses_existing_delivery_record_without_new_inventory(self) -> None:
        existing = DeliveryRecord(
            id=55,
            order_id=12,
            tenant_id=7,
            buyer_telegram_user_id=42,
            delivery_type="card_pool",
            inventory_item_id=77,
            status="sent",
        )
        session = _FakeSession(order=_order(status="delivered"), product=_product(), delivery_record=existing)

        result = await self.service.import_delivery(
            session,
            tenant_id=7,
            out_trade_no="ORD123",
            provider_name="acg",
            source_key="main",
            delivery=_delivery(),
            settings=self.settings,
        )

        self.assertFalse(result.imported)
        self.assertFalse(result.dry_run)
        self.assertEqual(55, result.delivery_record_id)
        self.assertEqual("delivered", result.order_status)
        self.assertEqual([], session.added)
        self.assertEqual(0, session.flush_count)

    async def test_import_delivery_dry_run_reuses_existing_delivery_record_without_writing(self) -> None:
        existing = DeliveryRecord(
            id=55,
            order_id=12,
            tenant_id=7,
            buyer_telegram_user_id=42,
            delivery_type="card_pool",
            inventory_item_id=77,
            status="sent",
        )
        session = _FakeSession(order=_order(status="delivered"), product=_product(), delivery_record=existing)

        result = await self.service.import_delivery(
            session,
            tenant_id=7,
            out_trade_no="ORD123",
            provider_name="acg",
            source_key="main",
            delivery=_delivery(items=("card-a", "card-b")),
            settings=self.settings,
            dry_run=True,
        )

        self.assertFalse(result.imported)
        self.assertTrue(result.dry_run)
        self.assertEqual(55, result.delivery_record_id)
        self.assertEqual("delivered", result.order_status)
        self.assertEqual(2, result.item_count)
        self.assertEqual([], session.added)
        self.assertEqual(0, session.flush_count)

    async def test_import_delivery_existing_record_rejects_mismatched_external_mapping(self) -> None:
        existing = DeliveryRecord(
            id=55,
            order_id=12,
            tenant_id=7,
            buyer_telegram_user_id=42,
            delivery_type="card_pool",
            inventory_item_id=77,
            status="sent",
        )
        session = _FakeSession(
            order=_order(status="delivered"),
            product=_product(external_source="other"),
            delivery_record=existing,
        )

        with self.assertRaisesRegex(ValueError, "外部源与请求不一致"):
            await self.service.import_delivery(
                session,
                tenant_id=7,
                out_trade_no="ORD123",
                provider_name="acg",
                source_key="main",
                delivery=_delivery(),
                settings=self.settings,
            )

        self.assertEqual([], session.added)
        self.assertEqual(0, session.flush_count)

    async def test_import_delivery_dry_run_rejects_invalid_content_without_writing(self) -> None:
        session = _FakeSession(order=_order(), product=_product())

        with self.assertRaisesRegex(ValueError, "内容为空"):
            await self.service.import_delivery(
                session,
                tenant_id=7,
                out_trade_no="ORD123",
                provider_name="acg",
                source_key="main",
                delivery=_delivery(items=(), message=""),
                settings=self.settings,
                dry_run=True,
            )

        self.assertEqual([], session.added)
        self.assertEqual(0, session.flush_count)

    async def test_import_delivery_rejects_unpaid_order(self) -> None:
        session = _FakeSession(order=_order(status="pending"), product=_product())

        with self.assertRaisesRegex(ValueError, "订单当前状态"):
            await self.service.import_delivery(
                session,
                tenant_id=7,
                out_trade_no="ORD123",
                provider_name="acg",
                source_key="main",
                delivery=_delivery(),
                settings=self.settings,
            )

        self.assertEqual([], session.added)

    async def test_import_delivery_requires_matching_external_product_mapping(self) -> None:
        cases = [
            (_product(external_source=None), "缺少外部商品映射"),
            (_product(external_source="other"), "外部源与请求不一致"),
            (_product(source_key="other"), "外部源与请求不一致"),
            (_product(delivery_type="file_download"), "文本卡密商品"),
        ]

        for product, pattern in cases:
            with self.subTest(pattern=pattern):
                session = _FakeSession(order=_order(), product=product)
                with self.assertRaisesRegex(ValueError, pattern):
                    await self.service.import_delivery(
                        session,
                        tenant_id=7,
                        out_trade_no="ORD123",
                        provider_name="acg",
                        source_key="main",
                        delivery=_delivery(),
                        settings=self.settings,
                    )
                self.assertEqual([], session.added)

    async def test_import_delivery_rejects_non_text_external_delivery_type(self) -> None:
        session = _FakeSession(order=_order(), product=_product())

        with self.assertRaisesRegex(ValueError, "文本卡密发货"):
            await self.service.import_delivery(
                session,
                tenant_id=7,
                out_trade_no="ORD123",
                provider_name="acg",
                source_key="main",
                delivery=_delivery(delivery_type="file_download"),
                settings=self.settings,
            )


def _order(*, status: str = "paid") -> object:
    return SimpleNamespace(
        id=12,
        tenant_id=7,
        buyer_telegram_user_id=42,
        source_type="self",
        self_product_id=101,
        product_variant_id=201,
        status=status,
        out_trade_no="ORD123",
        amount=Decimal("9.90"),
        currency="USDT",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )


def _product(
    *,
    external_source: str | None = "acg",
    source_key: str = "main",
    external_id: str | None = "sku-1",
    delivery_type: str = "card_pool",
) -> object:
    return SimpleNamespace(
        id=101,
        tenant_id=7,
        external_source=external_source,
        source_key=source_key,
        external_id=external_id,
        delivery_type=delivery_type,
    )


def _delivery(
    *,
    delivery_type: str = "card_pool",
    items: tuple[str, ...] = ("card-a",),
    message: str | None = None,
) -> ExternalDelivery:
    return ExternalDelivery(
        provider="acg",
        external_order_id="EXT-1",
        delivery_type=delivery_type,
        items=items,
        message=message,
        raw_payload={"result": "ok"},
    )


if __name__ == "__main__":
    unittest.main()
