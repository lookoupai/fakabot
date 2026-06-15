from __future__ import annotations

from types import SimpleNamespace
import unittest

try:
    from app.bots.routers.tenant import _parse_product_sort_args
    from app.db.repos.products import ProductRepository
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过商品排序测试：{exc.name}") from exc


class _ScalarResult:
    def __init__(self, value: object | None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object | None:
        return self.value


class _FakeSession:
    def __init__(self, product: object | None) -> None:
        self.product = product
        self.flush_count = 0

    async def execute(self, _query: object) -> _ScalarResult:
        return _ScalarResult(self.product)

    async def flush(self) -> None:
        self.flush_count += 1


class TenantProductSortParserTest(unittest.TestCase):
    def test_parse_product_sort_accepts_pipe_or_space_separator(self) -> None:
        self.assertEqual((12, -10), _parse_product_sort_args("12 | -10"))
        self.assertEqual((12, 20), _parse_product_sort_args("12 20"))

    def test_parse_product_sort_rejects_invalid_values(self) -> None:
        invalid_values = ["", "abc", "0 1", "12 abc", "12 100001", "12 1 extra"]
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _parse_product_sort_args(value)


class ProductRepositorySortOrderTest(unittest.IsolatedAsyncioTestCase):
    async def test_set_product_sort_order_updates_existing_product(self) -> None:
        product = SimpleNamespace(id=12, tenant_id=7, sort_order=0)
        session = _FakeSession(product)

        changed = await ProductRepository().set_product_sort_order(session, 7, 12, -5)

        self.assertTrue(changed)
        self.assertEqual(-5, product.sort_order)
        self.assertEqual(1, session.flush_count)

    async def test_set_product_sort_order_returns_false_for_missing_product(self) -> None:
        session = _FakeSession(None)

        changed = await ProductRepository().set_product_sort_order(session, 7, 12, 5)

        self.assertFalse(changed)
        self.assertEqual(0, session.flush_count)

    async def test_set_product_sort_order_rejects_out_of_range_value_before_query(self) -> None:
        session = _FakeSession(SimpleNamespace(id=12, sort_order=0))

        with self.assertRaises(ValueError):
            await ProductRepository().set_product_sort_order(session, 7, 12, 100001)

        self.assertEqual(0, session.flush_count)


if __name__ == "__main__":
    unittest.main()
