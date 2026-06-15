from __future__ import annotations

from types import SimpleNamespace
import unittest

try:
    from app.bots.routers.tenant import _parse_product_category_args
    from app.db.repos.products import ProductRepository
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过商品分类测试：{exc.name}") from exc


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


class TenantProductCategoryParserTest(unittest.TestCase):
    def test_parse_product_category_accepts_category_and_clear_marker(self) -> None:
        self.assertEqual((12, "点卡"), _parse_product_category_args("12 | 点卡"))
        self.assertEqual((12, None), _parse_product_category_args("12 | -"))

    def test_parse_product_category_rejects_invalid_values(self) -> None:
        invalid_values = ["", "abc", "0 | 点卡", "12", f"12 | {'x' * 129}"]
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _parse_product_category_args(value)


class ProductRepositoryCategoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_set_product_category_updates_existing_product(self) -> None:
        product = SimpleNamespace(id=12, tenant_id=7, category=None)
        session = _FakeSession(product)

        changed = await ProductRepository().set_product_category(session, 7, 12, " 点卡 ")

        self.assertTrue(changed)
        self.assertEqual("点卡", product.category)
        self.assertEqual(1, session.flush_count)

    async def test_set_product_category_can_clear_category(self) -> None:
        product = SimpleNamespace(id=12, tenant_id=7, category="点卡")
        session = _FakeSession(product)

        changed = await ProductRepository().set_product_category(session, 7, 12, "-")

        self.assertTrue(changed)
        self.assertIsNone(product.category)
        self.assertEqual(1, session.flush_count)

    async def test_set_product_category_returns_false_for_missing_product(self) -> None:
        session = _FakeSession(None)

        changed = await ProductRepository().set_product_category(session, 7, 12, "点卡")

        self.assertFalse(changed)
        self.assertEqual(0, session.flush_count)


if __name__ == "__main__":
    unittest.main()
