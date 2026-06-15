from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import patch

try:
    from app.config import Settings
    from app.services.api_keys import ApiKeyService

    from tests.test_tenant_admin_runtime_auth import (
        _FakeSession,
        _api_key,
        _authenticate,
        _client,
        _session_factory,
    )
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过 Tenant Admin 商品元数据测试：{exc.name}") from exc


class _RecordingProductRepository:
    def __init__(self, *, mode: str = "success") -> None:
        self.mode = mode
        self.calls: list[dict[str, object]] = []
        self.product = SimpleNamespace(
            id=12,
            external_source=None,
            source_key="",
            external_id=None,
            name="商品 A",
            category="原分类",
            sort_order=0,
            status="draft",
            delivery_type="card_pool",
            suggested_price=Decimal("9.90"),
            currency="USDT",
            storage_key="private/card.txt",
        )
        self.metadata_updated = False

    async def update_product_metadata(self, *args: object, **kwargs: object) -> object | None:
        session, tenant_id, product_id = self._extract_identity(args, kwargs)
        category = kwargs.get("category")
        sort_order = kwargs.get("sort_order")
        if len(args) >= 4:
            category = args[3]
        if len(args) >= 5:
            sort_order = args[4]
        self.calls.append(
            {
                "method": "update_product_metadata",
                "session": session,
                "tenant_id": tenant_id,
                "product_id": product_id,
                "category": category,
                "sort_order": sort_order,
            }
        )
        self._raise_value_error_if_needed()
        if self.mode == "missing":
            return None
        self._apply_metadata(category=category, sort_order=sort_order)
        return self.product

    async def update_self_product(self, *args: object, **kwargs: object) -> object | None:
        session, tenant_id, product_id = self._extract_identity(args, kwargs)
        category = kwargs.get("category")
        sort_order = kwargs.get("sort_order")
        self.calls.append(
            {
                "method": "update_self_product",
                "session": session,
                "tenant_id": tenant_id,
                "product_id": product_id,
                "category": category,
                "sort_order": sort_order,
            }
        )
        self._raise_value_error_if_needed()
        if self.mode == "missing":
            return None
        self._apply_metadata(category=category, sort_order=sort_order)
        return self.product

    async def set_product_category(self, *args: object, **kwargs: object) -> bool:
        session, tenant_id, product_id = self._extract_identity(args, kwargs)
        category = kwargs.get("category")
        if len(args) >= 4:
            category = args[3]
        self.calls.append(
            {
                "method": "set_product_category",
                "session": session,
                "tenant_id": tenant_id,
                "product_id": product_id,
                "category": category,
            }
        )
        self._raise_value_error_if_needed()
        if self.mode == "missing":
            return False
        self._apply_metadata(category=category, sort_order=None)
        return True

    async def set_product_sort_order(self, *args: object, **kwargs: object) -> bool:
        session, tenant_id, product_id = self._extract_identity(args, kwargs)
        sort_order = kwargs.get("sort_order")
        if len(args) >= 4:
            sort_order = args[3]
        self.calls.append(
            {
                "method": "set_product_sort_order",
                "session": session,
                "tenant_id": tenant_id,
                "product_id": product_id,
                "sort_order": sort_order,
            }
        )
        self._raise_value_error_if_needed()
        if self.mode == "missing":
            return False
        self._apply_metadata(category=None, sort_order=sort_order)
        return True

    async def get_product_with_default_variant(self, *args: object, **kwargs: object) -> tuple[object | None, object | None]:
        session, tenant_id, product_id = self._extract_identity(args, kwargs)
        self.calls.append(
            {
                "method": "get_product_with_default_variant",
                "session": session,
                "tenant_id": tenant_id,
                "product_id": product_id,
            }
        )
        if self.mode == "missing":
            return None, None
        return self.product, None

    async def inventory_summary(self, *args: object, **kwargs: object) -> dict[int, dict[str, int]]:
        session, tenant_id, product_id = self._extract_inventory_identity(args, kwargs)
        self.calls.append(
            {
                "method": "inventory_summary",
                "session": session,
                "tenant_id": tenant_id,
                "product_id": product_id,
            }
        )
        return {12: {"available": 3}}

    def _raise_value_error_if_needed(self) -> None:
        if self.mode == "value_error":
            raise ValueError("排序值非法 token=fk_live_test secret=super_secret")

    def _apply_metadata(self, *, category: object, sort_order: object) -> None:
        if category is not None:
            self.product.category = category
            self.metadata_updated = True
        if sort_order is not None:
            self.product.sort_order = sort_order
            self.metadata_updated = True

    @staticmethod
    def _extract_identity(args: tuple[object, ...], kwargs: dict[str, object]) -> tuple[object, int, int]:
        session = kwargs.get("session", args[0] if len(args) >= 1 else None)
        tenant_id = kwargs.get("tenant_id", args[1] if len(args) >= 2 else None)
        product_id = kwargs.get("product_id", args[2] if len(args) >= 3 else None)
        if not isinstance(tenant_id, int) or not isinstance(product_id, int):
            raise AssertionError(f"ProductRepository 调用缺少 tenant_id/product_id：{args!r} {kwargs!r}")
        return session, tenant_id, product_id

    @staticmethod
    def _extract_inventory_identity(args: tuple[object, ...], kwargs: dict[str, object]) -> tuple[object, int, int | None]:
        session = kwargs.get("session", args[0] if len(args) >= 1 else None)
        tenant_id = kwargs.get("tenant_id", args[1] if len(args) >= 2 else None)
        product_id = kwargs.get("product_id", args[2] if len(args) >= 3 else None)
        if not isinstance(tenant_id, int):
            raise AssertionError(f"ProductRepository 调用缺少 tenant_id：{args!r} {kwargs!r}")
        if product_id is not None and not isinstance(product_id, int):
            raise AssertionError(f"ProductRepository 调用 product_id 非法：{args!r} {kwargs!r}")
        return session, tenant_id, product_id


class TenantAdminProductMetadataRuntimeTest(unittest.TestCase):
    def test_update_product_metadata_requires_products_write_before_repo(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["products:read"]))):
                with patch("app.web.tenant_admin.ProductRepository") as product_repo:
                    response = client.patch(
                        "/api/v1/tenant/products/12/metadata",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"category": "点卡", "sort_order": -20},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        product_repo.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_update_product_metadata_rejects_extra_payload_fields_before_repo(self) -> None:
        session = _FakeSession()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["products:write"]))):
                with patch("app.web.tenant_admin.ProductRepository") as product_repo:
                    response = client.patch(
                        "/api/v1/tenant/products/12/metadata",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"category": "点卡", "sort_order": -20, "price": "1.00"},
                    )

        self.assertEqual(422, response.status_code)
        product_repo.assert_not_called()

    def test_update_product_metadata_commits_and_returns_sort_order_and_category(self) -> None:
        session = _FakeSession()
        repo = _RecordingProductRepository()
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["products:write"]))):
                with patch("app.web.tenant_admin.ProductRepository", return_value=repo):
                    response = client.patch(
                        "/api/v1/tenant/products/12/metadata",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"category": "点卡", "sort_order": -20},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(12, payload["id"])
        self.assertEqual("点卡", payload["category"])
        self.assertEqual(-20, payload["sort_order"])
        self.assertEqual("9.90", payload["price"])
        self.assertEqual(3, payload["available_count"])
        self.assertNotIn("storage_key", response.text)
        self.assertNotIn("token", response.text.lower())
        self.assertTrue(repo.metadata_updated, repo.calls)
        self.assertTrue(
            any(call["tenant_id"] == 7 and call["product_id"] == 12 for call in repo.calls),
            repo.calls,
        )
        self.assertEqual(2, session.commit_count)

    def test_update_product_metadata_returns_404_for_missing_product(self) -> None:
        session = _FakeSession()
        repo = _RecordingProductRepository(mode="missing")
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["products:write"]))):
                with patch("app.web.tenant_admin.ProductRepository", return_value=repo):
                    response = client.patch(
                        "/api/v1/tenant/products/12/metadata",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"category": "点卡", "sort_order": -20},
                    )

        self.assertEqual(404, response.status_code)
        self.assertTrue(
            any(call["tenant_id"] == 7 and call["product_id"] == 12 for call in repo.calls),
            repo.calls,
        )

    def test_update_product_metadata_value_error_returns_400_without_secret_leak(self) -> None:
        session = _FakeSession()
        repo = _RecordingProductRepository(mode="value_error")
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["products:write"]))):
                with patch("app.web.tenant_admin.ProductRepository", return_value=repo):
                    response = client.patch(
                        "/api/v1/tenant/products/12/metadata",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"category": "点卡", "sort_order": -20},
                    )

        self.assertEqual(400, response.status_code)
        response_text = response.text.lower()
        self.assertNotIn("fk_live_test", response_text)
        self.assertNotIn("super_secret", response_text)
        self.assertNotIn("token=", response_text)
        self.assertNotIn("secret=", response_text)
        self.assertTrue(repo.calls)


if __name__ == "__main__":
    unittest.main()
