from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
import unittest

try:
    from app.bots.routers.tenant import _parse_inventory_export_args
    from app.db.repos.products import ProductRepository
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过库存导出测试：{exc.name}") from exc


class _FakeScalarResult:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return self._values


class _FakeExecuteResult:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def scalars(self) -> _FakeScalarResult:
        return _FakeScalarResult(self._values)


class _FakeSession:
    def __init__(self, values: list[object]) -> None:
        self.values = values
        self.execute_count = 0

    async def execute(self, _query: object) -> _FakeExecuteResult:
        self.execute_count += 1
        return _FakeExecuteResult(self.values)


class TenantInventoryExportParserTest(unittest.TestCase):
    def test_parse_inventory_export_uses_default_limit(self) -> None:
        self.assertEqual((12, 1000), _parse_inventory_export_args("12"))

    def test_parse_inventory_export_accepts_pipe_or_space_limit(self) -> None:
        self.assertEqual((12, 50), _parse_inventory_export_args("12 | 50"))
        self.assertEqual((12, 50), _parse_inventory_export_args("12 50"))

    def test_parse_inventory_export_rejects_invalid_values(self) -> None:
        invalid_values = ["", "abc", "0", "12 abc", "12 0", "12 5001", "12 1 extra"]
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _parse_inventory_export_args(value)


class ProductRepositoryInventoryExportTest(unittest.IsolatedAsyncioTestCase):
    async def test_export_available_inventory_items_validates_product_and_returns_items(self) -> None:
        repo = ProductRepository()
        product = SimpleNamespace(
            id=12,
            tenant_id=7,
            delivery_type="card_pool",
            name="测试卡密",
            suggested_price=Decimal("1.00"),
        )
        variant = SimpleNamespace(id=3)
        item = SimpleNamespace(id=99, content_encrypted="encrypted-card", status="available")
        session = _FakeSession([item])

        async def _get_product(_session: object, tenant_id: int, product_id: int) -> tuple[object, object]:
            self.assertEqual(7, tenant_id)
            self.assertEqual(12, product_id)
            return product, variant

        repo.get_product_with_default_variant = _get_product

        exported_product, items = await repo.export_available_inventory_items(session, 7, 12, limit=50)

        self.assertIs(product, exported_product)
        self.assertEqual([item], items)
        self.assertEqual(1, session.execute_count)

    async def test_export_available_inventory_items_rejects_non_card_products(self) -> None:
        repo = ProductRepository()
        product = SimpleNamespace(id=12, tenant_id=7, delivery_type="file_download")
        variant = SimpleNamespace(id=3)
        session = _FakeSession([])

        async def _get_product(_session: object, _tenant_id: int, _product_id: int) -> tuple[object, object]:
            return product, variant

        repo.get_product_with_default_variant = _get_product

        with self.assertRaises(ValueError):
            await repo.export_available_inventory_items(session, 7, 12)

        self.assertEqual(0, session.execute_count)


if __name__ == "__main__":
    unittest.main()
