from __future__ import annotations

import unittest
from decimal import Decimal
from types import SimpleNamespace
from typing import Optional
from unittest.mock import patch

try:
    from app.services.external_sources import (
        ExternalAuthenticatedCatalogSyncContext,
        ExternalCatalogSyncContext,
        ExternalProduct,
        ExternalProductPage,
        ExternalSourceRuntimeCredentials,
        ExternalSourceError,
    )
    from app.services.external_sources.sync import ExternalCatalogSyncService
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过外部目录同步测试：{exc.name}") from exc


class FakeCatalogProvider:
    provider = "acg"

    def __init__(self, pages: dict[Optional[str], object], products: dict[str, object] | None = None) -> None:
        self.pages = pages
        self.products = products or {}
        self.calls: list[tuple[int, Optional[str], int]] = []
        self.product_calls: list[tuple[int, str]] = []

    async def list_products(
        self,
        tenant_id: int,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> ExternalProductPage:
        self.calls.append((tenant_id, cursor, limit))
        page = self.pages.get(cursor, ExternalProductPage(products=[]))
        if isinstance(page, Exception):
            raise page
        return page

    async def get_product(self, tenant_id: int, external_product_id: str) -> Optional[ExternalProduct]:
        self.product_calls.append((tenant_id, external_product_id))
        product = self.products.get(external_product_id)
        if isinstance(product, Exception):
            raise product
        return product


class FakeContextCatalogProvider:
    provider = "acg"

    def __init__(self, page: ExternalProductPage, products: dict[str, object] | None = None) -> None:
        self.page = page
        self.products = products or {}
        self.context_calls: list[tuple[ExternalCatalogSyncContext, Optional[str], int]] = []
        self.product_context_calls: list[tuple[ExternalCatalogSyncContext, str]] = []

    async def list_products(
        self,
        tenant_id: int,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> ExternalProductPage:
        raise AssertionError("context-aware provider should receive list_products_with_context")

    async def list_products_with_context(
        self,
        context: ExternalCatalogSyncContext,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> ExternalProductPage:
        self.context_calls.append((context, cursor, limit))
        return self.page

    async def get_product_with_context(
        self,
        context: ExternalCatalogSyncContext,
        external_product_id: str,
    ) -> Optional[ExternalProduct]:
        self.product_context_calls.append((context, external_product_id))
        product = self.products.get(external_product_id)
        if isinstance(product, Exception):
            raise product
        return product


class FakeFailingCatalogProvider:
    provider = "acg"

    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls: list[tuple[int, Optional[str], int]] = []

    async def list_products(
        self,
        tenant_id: int,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> ExternalProductPage:
        self.calls.append((tenant_id, cursor, limit))
        raise self.exc


class FakeFailingContextCatalogProvider:
    provider = "acg"

    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.context_calls: list[tuple[ExternalCatalogSyncContext, Optional[str], int]] = []

    async def list_products(
        self,
        tenant_id: int,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> ExternalProductPage:
        raise AssertionError("context-aware provider should receive list_products_with_context")

    async def list_products_with_context(
        self,
        context: ExternalCatalogSyncContext,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> ExternalProductPage:
        self.context_calls.append((context, cursor, limit))
        raise self.exc


class FakeProductRepository:
    def __init__(self) -> None:
        self.products: dict[tuple[int, str, str, str], SimpleNamespace] = {}
        self.next_id = 1
        self.created_count = 0
        self.updated_count = 0

    async def get_self_product_by_external_ref(
        self,
        session,
        tenant_id: int,
        external_source: str,
        source_key: str,
        external_id: str,
    ):
        return self.products.get((tenant_id, external_source, source_key, external_id)), None

    async def create_self_product(
        self,
        session,
        tenant_id: int,
        name: str,
        price: Decimal,
        delivery_type: str,
        description: Optional[str] = None,
        category: Optional[str] = None,
        external_source: Optional[str] = None,
        source_key: str = "",
        external_id: Optional[str] = None,
    ):
        product = SimpleNamespace(
            id=self.next_id,
            tenant_id=tenant_id,
            name=name,
            suggested_price=price,
            delivery_type=delivery_type,
            description=description,
            category=category,
            external_source=external_source,
            source_key=source_key,
            external_id=external_id,
            status="draft",
        )
        self.next_id += 1
        self.created_count += 1
        self.products[(tenant_id, external_source, source_key, external_id)] = product
        return product

    async def update_self_product(
        self,
        session,
        tenant_id: int,
        product_id: int,
        *,
        name: Optional[str] = None,
        price: Optional[Decimal] = None,
        description: Optional[str] = None,
        category: Optional[str] = None,
        status: Optional[str] = None,
        delivery_type: Optional[str] = None,
        external_source: Optional[str] = None,
        source_key: str = "",
        external_id: Optional[str] = None,
    ):
        product = self.products[(tenant_id, external_source, source_key, external_id)]
        if delivery_type is not None and delivery_type != product.delivery_type:
            raise ValueError("已有商品不能通过同步接口修改发货类型")
        if name is not None:
            product.name = name
        if price is not None:
            product.suggested_price = price
        if description is not None:
            product.description = description
        if category is not None:
            product.category = category
        if status is not None:
            product.status = status
        self.updated_count += 1
        return product

    async def set_product_status(self, session, tenant_id: int, product_id: int, status: str) -> bool:
        for product in self.products.values():
            if product.tenant_id == tenant_id and product.id == product_id:
                product.status = status
                return True
        return False


def _runtime_auth(
    *,
    tenant_id: int = 7,
    connection_id: int = 11,
    provider_name: str = "acg",
    source_key: str = "shop-a",
) -> ExternalSourceRuntimeCredentials:
    return ExternalSourceRuntimeCredentials(
        connection_id=connection_id,
        tenant_id=tenant_id,
        provider_name=provider_name,
        source_key=source_key,
        credential_fields=["sensitive_1"],
        credentials={"api_key": "secret-value"},
    )


def _external_product(
    external_id: object,
    *,
    provider: object = "acg",
    name: object = "外部商品",
    price: object = "1.00",
    delivery_type: object = "card_pool",
    status: object = "on",
    currency: object = "USDT",
    description: object | None = None,
    category: object | None = None,
    stock_count: object | None = None,
    raw_payload: object | None = None,
) -> ExternalProduct:
    normalized_price = Decimal(price) if isinstance(price, str) else price
    return ExternalProduct(
        provider=provider,
        external_product_id=external_id,
        name=name,
        price=normalized_price,
        currency=currency,
        delivery_type=delivery_type,
        status=status,
        description=description,
        category=category,
        stock_count=stock_count,
        raw_payload={} if raw_payload is None else raw_payload,
    )


class ExternalCatalogSyncServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_sync_catalog_creates_then_updates_by_external_identity(self) -> None:
        provider = FakeCatalogProvider(
            {
                None: ExternalProductPage(
                    products=[_external_product("sku-1", name="外部商品A", price="1.00")]
                )
            }
        )
        repo = FakeProductRepository()
        service = ExternalCatalogSyncService(repository=repo)

        created = await service.sync_catalog(
            object(),
            tenant_id=1,
            provider=provider,
            source_key="shop-a",
        )
        updated = await service.sync_catalog(
            object(),
            tenant_id=1,
            provider=FakeCatalogProvider(
                {
                    None: ExternalProductPage(
                        products=[_external_product("sku-1", name="外部商品A改名", price="2.00")]
                    )
                }
            ),
            source_key="shop-a",
        )

        self.assertEqual(1, created.created_count)
        self.assertEqual(0, created.updated_count)
        self.assertEqual(0, updated.created_count)
        self.assertEqual(1, updated.updated_count)
        self.assertEqual(1, repo.created_count)
        self.assertEqual(1, repo.updated_count)
        product = repo.products[(1, "acg", "shop-a", "sku-1")]
        self.assertEqual("外部商品A改名", product.name)
        self.assertEqual(Decimal("2.00"), product.suggested_price)
        self.assertEqual("on", product.status)

    async def test_source_key_partitions_same_external_product_id(self) -> None:
        repo = FakeProductRepository()
        service = ExternalCatalogSyncService(repository=repo)
        page = ExternalProductPage(products=[_external_product("sku-1")])

        await service.sync_catalog(object(), tenant_id=1, provider=FakeCatalogProvider({None: page}), source_key="shop-a")
        await service.sync_catalog(object(), tenant_id=1, provider=FakeCatalogProvider({None: page}), source_key="shop-b")

        self.assertIn((1, "acg", "shop-a", "sku-1"), repo.products)
        self.assertIn((1, "acg", "shop-b", "sku-1"), repo.products)
        self.assertEqual(2, repo.created_count)

    async def test_sync_product_fetches_single_external_product_without_listing_catalog(self) -> None:
        provider = FakeCatalogProvider(
            {},
            products={"sku-1": _external_product("sku-1", name="单品同步", price="1.50")},
        )
        repo = FakeProductRepository()
        service = ExternalCatalogSyncService(repository=repo)

        created = await service.sync_product(
            object(),
            tenant_id=7,
            provider=provider,
            external_product_id=" sku-1 ",
            source_key="shop-a",
        )
        updated = await service.sync_product(
            object(),
            tenant_id=7,
            provider=FakeCatalogProvider(
                {},
                products={"sku-1": _external_product("sku-1", name="单品同步改名", price="2.00")},
            ),
            external_product_id="sku-1",
            source_key="shop-a",
        )

        self.assertEqual(1, created.created_count)
        self.assertEqual(0, created.updated_count)
        self.assertEqual(0, updated.created_count)
        self.assertEqual(1, updated.updated_count)
        self.assertEqual([(7, "sku-1")], provider.product_calls)
        self.assertEqual([], provider.calls)
        product = repo.products[(7, "acg", "shop-a", "sku-1")]
        self.assertEqual("单品同步改名", product.name)
        self.assertEqual(Decimal("2.00"), product.suggested_price)

    async def test_sync_product_uses_context_provider_without_credentials(self) -> None:
        provider = FakeContextCatalogProvider(
            ExternalProductPage(products=[]),
            products={"sku-1": _external_product("sku-1")},
        )
        service = ExternalCatalogSyncService(repository=FakeProductRepository())

        result = await service.sync_product(
            object(),
            tenant_id=7,
            provider=provider,
            external_product_id="sku-1",
            source_key="shop-a",
            connection_id=11,
        )

        self.assertEqual(1, result.created_count)
        self.assertEqual(1, len(provider.product_context_calls))
        context, external_product_id = provider.product_context_calls[0]
        payload = context.__dict__
        self.assertEqual("sku-1", external_product_id)
        self.assertEqual(7, context.tenant_id)
        self.assertEqual("acg", context.provider_name)
        self.assertEqual("shop-a", context.source_key)
        self.assertEqual(11, context.connection_id)
        self.assertNotIn("credentials", payload)
        self.assertNotIn("credentials_encrypted", payload)
        self.assertNotIn("token", payload)
        self.assertNotIn("secret", payload)
        self.assertNotIn("api_key", payload)
        self.assertNotIn("password", payload)

    async def test_sync_product_passes_runtime_auth_as_redacted_authenticated_context(self) -> None:
        provider = FakeContextCatalogProvider(
            ExternalProductPage(products=[]),
            products={"sku-1": _external_product("sku-1")},
        )
        runtime_auth = _runtime_auth()
        service = ExternalCatalogSyncService(repository=FakeProductRepository())

        result = await service.sync_product(
            object(),
            tenant_id=7,
            provider=provider,
            external_product_id="sku-1",
            source_key="shop-a",
            connection_id=11,
            runtime_auth=runtime_auth,
        )

        self.assertEqual(1, result.created_count)
        context, _ = provider.product_context_calls[0]
        self.assertIsInstance(context, ExternalAuthenticatedCatalogSyncContext)
        self.assertIs(runtime_auth, context.runtime_auth)
        rendered = f"{context!r} {context.__dict__!r}"
        self.assertIn("runtime_auth='***'", repr(context))
        self.assertNotIn("secret-value", rendered)
        self.assertNotIn("api_key", rendered)
        self.assertNotIn("credentials_encrypted", rendered)

    async def test_sync_product_returns_skipped_when_external_product_missing(self) -> None:
        repo = FakeProductRepository()
        service = ExternalCatalogSyncService(repository=repo)

        result = await service.sync_product(
            object(),
            tenant_id=7,
            provider=FakeCatalogProvider({}, products={}),
            external_product_id="sku-missing",
            source_key="shop-a",
        )

        self.assertEqual(0, result.created_count)
        self.assertEqual(0, result.updated_count)
        self.assertEqual(1, result.skipped_count)
        self.assertEqual("sku-missing", result.products[0].external_id)
        self.assertEqual("外部商品不存在", result.products[0].skipped_reason)
        self.assertEqual({}, repo.products)

    async def test_sync_product_rejects_invalid_parameters_before_provider_call(self) -> None:
        service = ExternalCatalogSyncService(repository=FakeProductRepository())
        provider = FakeCatalogProvider({}, products={"sku-1": _external_product("sku-1")})

        invalid_calls = [
            ({"tenant_id": 0, "provider": provider, "external_product_id": "sku-1"}, "tenant_id"),
            ({"tenant_id": True, "provider": provider, "external_product_id": "sku-1"}, "tenant_id"),
            ({"tenant_id": "7", "provider": provider, "external_product_id": "sku-1"}, "tenant_id"),
            (
                {"tenant_id": 7, "provider": provider, "external_product_id": "sku-1", "connection_id": 0},
                "connection_id",
            ),
            (
                {"tenant_id": 7, "provider": provider, "external_product_id": "sku-1", "source_key": "Shop A"},
                "source_key",
            ),
            ({"tenant_id": 7, "provider": provider, "external_product_id": None}, "external_product_id"),
            ({"tenant_id": 7, "provider": provider, "external_product_id": 123}, "external_product_id"),
            ({"tenant_id": 7, "provider": provider, "external_product_id": " "}, "external_product_id"),
            ({"tenant_id": 7, "provider": provider, "external_product_id": "x" * 129}, "external_product_id"),
            ({"tenant_id": 7, "provider": object(), "external_product_id": "sku-1"}, "provider"),
        ]
        for kwargs, error_pattern in invalid_calls:
            with self.subTest(error_pattern=error_pattern, kwargs=kwargs):
                with self.assertRaisesRegex(ValueError, error_pattern):
                    await service.sync_product(object(), **kwargs)

        self.assertEqual([], provider.product_calls)

    async def test_sync_registered_product_rejects_invalid_provider_name_before_lookup(self) -> None:
        service = ExternalCatalogSyncService(repository=FakeProductRepository())

        for provider_name in (None, 123, "", "ACG"):
            with self.subTest(provider_name=provider_name):
                with patch("app.services.external_sources.sync.get_provider") as get_provider:
                    with self.assertRaisesRegex(ValueError, "provider_name"):
                        await service.sync_registered_product(
                            object(),
                            tenant_id=7,
                            provider_name=provider_name,
                            external_product_id="sku-1",
                        )
                get_provider.assert_not_called()

    async def test_sync_registered_product_rejects_unknown_provider(self) -> None:
        service = ExternalCatalogSyncService(repository=FakeProductRepository())

        with patch("app.services.external_sources.sync.get_provider", return_value=None):
            with self.assertRaisesRegex(Exception, "provider 未注册"):
                await service.sync_registered_product(
                    object(),
                    tenant_id=7,
                    provider_name="missing",
                    external_product_id="sku-1",
                )

    async def test_sync_product_wraps_provider_errors_and_validates_result_type(self) -> None:
        service = ExternalCatalogSyncService(repository=FakeProductRepository())

        with self.assertRaisesRegex(ExternalSourceError, "商品结果无效"):
            await service.sync_product(
                object(),
                tenant_id=7,
                provider=FakeCatalogProvider({}, products={"sku-1": object()}),
                external_product_id="sku-1",
            )
        with self.assertRaisesRegex(ExternalSourceError, "商品获取失败") as caught:
            await service.sync_product(
                object(),
                tenant_id=7,
                provider=FakeCatalogProvider({}, products={"sku-1": RuntimeError("boom")}),
                external_product_id="sku-1",
            )
        self.assertIsInstance(caught.exception.__cause__, RuntimeError)
        source_error = ExternalSourceError("主动失败")
        with self.assertRaises(ExternalSourceError) as direct:
            await service.sync_product(
                object(),
                tenant_id=7,
                provider=FakeCatalogProvider({}, products={"sku-1": source_error}),
                external_product_id="sku-1",
            )
        self.assertIs(source_error, direct.exception)

    async def test_sync_catalog_paginates_until_max_pages_or_empty_cursor(self) -> None:
        provider = FakeCatalogProvider(
            {
                None: ExternalProductPage(products=[_external_product("sku-1")], next_cursor="page-2"),
                "page-2": ExternalProductPage(products=[_external_product("sku-2")]),
            }
        )
        service = ExternalCatalogSyncService(repository=FakeProductRepository())

        result = await service.sync_catalog(object(), tenant_id=7, provider=provider, limit=10, max_pages=2)

        self.assertEqual(2, result.created_count)
        self.assertEqual([(7, None, 10), (7, "page-2", 10)], provider.calls)
        self.assertIsNone(result.next_cursor)

    async def test_sync_catalog_passes_non_sensitive_context_to_context_provider(self) -> None:
        provider = FakeContextCatalogProvider(ExternalProductPage(products=[_external_product("sku-1")]))
        service = ExternalCatalogSyncService(repository=FakeProductRepository())

        result = await service.sync_catalog(
            object(),
            tenant_id=7,
            provider=provider,
            source_key="shop-a",
            connection_id=11,
            limit=10,
        )

        self.assertEqual(1, result.created_count)
        self.assertEqual(1, len(provider.context_calls))
        context, cursor, limit = provider.context_calls[0]
        payload = context.__dict__
        self.assertEqual(7, context.tenant_id)
        self.assertEqual("acg", context.provider_name)
        self.assertEqual("shop-a", context.source_key)
        self.assertEqual(11, context.connection_id)
        self.assertIsNone(cursor)
        self.assertEqual(10, limit)
        self.assertNotIn("credentials", payload)
        self.assertNotIn("credentials_encrypted", payload)
        self.assertNotIn("token", payload)
        self.assertNotIn("secret", payload)
        self.assertNotIn("api_key", payload)
        self.assertNotIn("password", payload)

    async def test_sync_catalog_passes_runtime_auth_as_redacted_authenticated_context(self) -> None:
        provider = FakeContextCatalogProvider(ExternalProductPage(products=[_external_product("sku-1")]))
        runtime_auth = _runtime_auth()
        service = ExternalCatalogSyncService(repository=FakeProductRepository())

        result = await service.sync_catalog(
            object(),
            tenant_id=7,
            provider=provider,
            source_key="shop-a",
            connection_id=11,
            limit=10,
            runtime_auth=runtime_auth,
        )

        self.assertEqual(1, result.created_count)
        context, _, _ = provider.context_calls[0]
        self.assertIsInstance(context, ExternalAuthenticatedCatalogSyncContext)
        self.assertIs(runtime_auth, context.runtime_auth)
        rendered = f"{context!r} {context.__dict__!r}"
        self.assertNotIn("secret-value", rendered)
        self.assertNotIn("api_key", rendered)
        self.assertNotIn("credentials_encrypted", rendered)

    async def test_sync_catalog_rejects_runtime_auth_mismatch_before_provider_call(self) -> None:
        provider = FakeContextCatalogProvider(ExternalProductPage(products=[_external_product("sku-1")]))
        service = ExternalCatalogSyncService(repository=FakeProductRepository())

        invalid_runtime_auth = _runtime_auth(provider_name="other")

        with self.assertRaisesRegex(ValueError, "runtime_auth provider_name"):
            await service.sync_catalog(
                object(),
                tenant_id=7,
                provider=provider,
                source_key="shop-a",
                connection_id=11,
                runtime_auth=invalid_runtime_auth,
            )

        self.assertEqual([], provider.context_calls)

    async def test_sync_catalog_rejects_invalid_entry_parameters_before_provider_call(self) -> None:
        service = ExternalCatalogSyncService(repository=FakeProductRepository())
        provider = FakeCatalogProvider({None: ExternalProductPage(products=[_external_product("sku-1")])})

        invalid_calls = [
            ({"tenant_id": 0, "provider": provider}, "tenant_id"),
            ({"tenant_id": True, "provider": provider}, "tenant_id"),
            ({"tenant_id": "7", "provider": provider}, "tenant_id"),
            ({"tenant_id": 7, "provider": provider, "connection_id": 0}, "connection_id"),
            ({"tenant_id": 7, "provider": provider, "connection_id": True}, "connection_id"),
            ({"tenant_id": 7, "provider": provider, "connection_id": "11"}, "connection_id"),
            ({"tenant_id": 7, "provider": provider, "source_key": "Shop A"}, "source_key"),
            ({"tenant_id": 7, "provider": provider, "source_key": None}, "source_key"),
            ({"tenant_id": 7, "provider": provider, "source_key": 123}, "source_key"),
            ({"tenant_id": 7, "provider": provider, "cursor": ""}, "cursor"),
            ({"tenant_id": 7, "provider": provider, "cursor": 123}, "cursor"),
            ({"tenant_id": 7, "provider": provider, "cursor": "x" * 513}, "cursor"),
            ({"tenant_id": 7, "provider": provider, "limit": 0}, "limit"),
            ({"tenant_id": 7, "provider": provider, "limit": True}, "limit"),
            ({"tenant_id": 7, "provider": provider, "limit": "10"}, "limit"),
            ({"tenant_id": 7, "provider": provider, "max_pages": 0}, "max_pages"),
            ({"tenant_id": 7, "provider": provider, "max_pages": True}, "max_pages"),
            ({"tenant_id": 7, "provider": provider, "max_pages": "2"}, "max_pages"),
            ({"tenant_id": 7, "provider": object()}, "provider"),
        ]
        for kwargs, error_pattern in invalid_calls:
            with self.subTest(error_pattern=error_pattern, kwargs=kwargs):
                with self.assertRaisesRegex(ValueError, error_pattern):
                    await service.sync_catalog(object(), **kwargs)

        invalid_provider = FakeCatalogProvider({None: ExternalProductPage(products=[])})
        invalid_provider.provider = 123
        with self.assertRaisesRegex(ValueError, "provider"):
            await service.sync_catalog(object(), tenant_id=7, provider=invalid_provider)

        self.assertEqual([], provider.calls)
        self.assertEqual([], invalid_provider.calls)

    async def test_sync_registered_catalog_rejects_invalid_provider_name_before_lookup(self) -> None:
        service = ExternalCatalogSyncService(repository=FakeProductRepository())

        for provider_name in (None, 123, "", "ACG"):
            with self.subTest(provider_name=provider_name):
                with patch("app.services.external_sources.sync.get_provider") as get_provider:
                    with self.assertRaisesRegex(ValueError, "provider_name"):
                        await service.sync_registered_catalog(
                            object(),
                            tenant_id=7,
                            provider_name=provider_name,
                        )
                get_provider.assert_not_called()

    async def test_sync_catalog_skips_unsupported_products_without_writing(self) -> None:
        provider = FakeCatalogProvider(
            {
                None: ExternalProductPage(
                    products=[
                        _external_product("sku-1", delivery_type="unknown"),
                        _external_product("sku-2", currency="CNY"),
                    ]
                )
            }
        )
        repo = FakeProductRepository()
        service = ExternalCatalogSyncService(repository=repo)

        result = await service.sync_catalog(object(), tenant_id=1, provider=provider)

        self.assertEqual(0, result.created_count)
        self.assertEqual(0, result.updated_count)
        self.assertEqual(2, result.skipped_count)
        self.assertEqual(0, repo.created_count)
        self.assertEqual(["skipped", "skipped"], [product.action for product in result.products])

    async def test_sync_catalog_skips_products_with_sensitive_raw_payload_without_writing(self) -> None:
        provider = FakeCatalogProvider(
            {
                None: ExternalProductPage(
                    products=[
                        _external_product("sku-1", raw_payload={"meta": {"secret_key": "secret"}}),
                        _external_product("sku-2", raw_payload=[]),
                    ]
                )
            }
        )
        repo = FakeProductRepository()
        service = ExternalCatalogSyncService(repository=repo)

        result = await service.sync_catalog(object(), tenant_id=1, provider=provider)

        self.assertEqual(0, result.created_count)
        self.assertEqual(0, result.updated_count)
        self.assertEqual(2, result.skipped_count)
        self.assertEqual(0, repo.created_count)
        self.assertIn("敏感字段", result.products[0].skipped_reason or "")
        self.assertIn("原始载荷", result.products[1].skipped_reason or "")

    async def test_sync_catalog_rejects_product_provider_contract_errors_without_writing(self) -> None:
        invalid_products = [
            _external_product("sku-1", provider="other"),
            _external_product("sku-2", provider="ACG"),
            _external_product("sku-3", provider=None),
        ]
        for product in invalid_products:
            with self.subTest(provider=product.provider):
                repo = FakeProductRepository()
                service = ExternalCatalogSyncService(repository=repo)

                with self.assertRaisesRegex(ExternalSourceError, "provider"):
                    await service.sync_catalog(
                        object(),
                        tenant_id=1,
                        provider=FakeCatalogProvider({None: ExternalProductPage(products=[product])}),
                    )

                self.assertEqual(0, repo.created_count)
                self.assertEqual(0, repo.updated_count)

    async def test_sync_catalog_rejects_product_runtime_contract_errors_without_writing(self) -> None:
        invalid_products = [
            (_external_product(123), "ID 无效"),
            (_external_product("sku-price-string", price=object()), "价格无效"),
            (_external_product("sku-price-nan", price=Decimal("NaN")), "价格无效"),
            (_external_product("sku-price-inf", price=Decimal("Infinity")), "价格无效"),
            (_external_product("sku-name", name=object()), "名称无效"),
            (_external_product("sku-currency", currency=None), "币种无效"),
            (_external_product("sku-delivery", delivery_type=[]), "发货类型无效"),
            (_external_product("sku-status", status=[]), "状态无效"),
            (_external_product("sku-description", description=object()), "描述无效"),
            (_external_product("sku-category", category=object()), "分类无效"),
            (_external_product("sku-stock-type", stock_count=object()), "库存数量无效"),
            (_external_product("sku-stock-negative", stock_count=-1), "库存数量无效"),
        ]
        for product, error_pattern in invalid_products:
            with self.subTest(error_pattern=error_pattern):
                repo = FakeProductRepository()
                service = ExternalCatalogSyncService(repository=repo)

                with self.assertRaisesRegex(ExternalSourceError, error_pattern):
                    await service.sync_catalog(
                        object(),
                        tenant_id=1,
                        provider=FakeCatalogProvider({None: ExternalProductPage(products=[product])}),
                    )

                self.assertEqual(0, repo.created_count)
                self.assertEqual(0, repo.updated_count)

    async def test_sync_catalog_allows_non_sensitive_raw_payload(self) -> None:
        provider = FakeCatalogProvider(
            {
                None: ExternalProductPage(
                    products=[
                        _external_product(
                            "sku-1",
                            raw_payload={"result": {"external_id": "sku-1", "status": "ok"}},
                        )
                    ]
                )
            }
        )
        repo = FakeProductRepository()
        service = ExternalCatalogSyncService(repository=repo)

        result = await service.sync_catalog(object(), tenant_id=1, provider=provider)

        self.assertEqual(1, result.created_count)
        self.assertEqual(0, result.skipped_count)
        self.assertIn((1, "acg", "", "sku-1"), repo.products)

    async def test_sync_catalog_rejects_invalid_provider_page_without_writing(self) -> None:
        repo = FakeProductRepository()
        service = ExternalCatalogSyncService(repository=repo)

        with self.assertRaisesRegex(ExternalSourceError, "分页结果无效"):
            await service.sync_catalog(
                object(),
                tenant_id=1,
                provider=FakeCatalogProvider({None: object()}),
            )

        self.assertEqual(0, repo.created_count)
        self.assertEqual(0, repo.updated_count)

    async def test_sync_catalog_rejects_invalid_provider_page_products_without_writing(self) -> None:
        repo = FakeProductRepository()
        service = ExternalCatalogSyncService(repository=repo)

        with self.assertRaisesRegex(ExternalSourceError, "商品列表无效"):
            await service.sync_catalog(
                object(),
                tenant_id=1,
                provider=FakeCatalogProvider({None: ExternalProductPage(products=(_external_product("sku-1"),))}),
            )

        self.assertEqual(0, repo.created_count)
        self.assertEqual(0, repo.updated_count)

    async def test_sync_catalog_rejects_invalid_provider_page_product_item_without_writing(self) -> None:
        repo = FakeProductRepository()
        service = ExternalCatalogSyncService(repository=repo)

        with self.assertRaisesRegex(ExternalSourceError, "商品结果无效"):
            await service.sync_catalog(
                object(),
                tenant_id=1,
                provider=FakeCatalogProvider({None: ExternalProductPage(products=[object()])}),
            )

        self.assertEqual(0, repo.created_count)
        self.assertEqual(0, repo.updated_count)

    async def test_sync_catalog_rejects_invalid_provider_next_cursor_without_writing(self) -> None:
        repo = FakeProductRepository()
        service = ExternalCatalogSyncService(repository=repo)

        invalid_pages = [
            ExternalProductPage(products=[_external_product("sku-1")], next_cursor=123),
            ExternalProductPage(products=[_external_product("sku-1")], next_cursor=""),
            ExternalProductPage(products=[_external_product("sku-1")], next_cursor="x" * 513),
        ]
        for page in invalid_pages:
            with self.subTest(next_cursor=page.next_cursor):
                with self.assertRaises(ExternalSourceError):
                    await service.sync_catalog(
                        object(),
                        tenant_id=1,
                        provider=FakeCatalogProvider({None: page}),
                    )

        self.assertEqual(0, repo.created_count)
        self.assertEqual(0, repo.updated_count)

    async def test_sync_catalog_stops_when_later_provider_page_is_invalid(self) -> None:
        repo = FakeProductRepository()
        provider = FakeCatalogProvider(
            {
                None: ExternalProductPage(products=[_external_product("sku-1")], next_cursor="page-2"),
                "page-2": object(),
            }
        )
        service = ExternalCatalogSyncService(repository=repo)

        with self.assertRaisesRegex(ExternalSourceError, "分页结果无效"):
            await service.sync_catalog(object(), tenant_id=1, provider=provider, max_pages=3)

        self.assertEqual([(1, None, 50), (1, "page-2", 50)], provider.calls)
        self.assertEqual(1, repo.created_count)
        self.assertIn((1, "acg", "", "sku-1"), repo.products)

    async def test_sync_catalog_rejects_repeated_next_cursor_before_writing_page(self) -> None:
        repo = FakeProductRepository()
        provider = FakeCatalogProvider(
            {
                None: ExternalProductPage(products=[_external_product("sku-1")], next_cursor="page-1"),
                "page-1": ExternalProductPage(products=[_external_product("sku-2")], next_cursor="page-1"),
            }
        )
        service = ExternalCatalogSyncService(repository=repo)

        with self.assertRaisesRegex(ExternalSourceError, "游标未前进"):
            await service.sync_catalog(object(), tenant_id=1, provider=provider, max_pages=3)

        self.assertEqual([(1, None, 50), (1, "page-1", 50)], provider.calls)
        self.assertEqual(1, repo.created_count)
        self.assertIn((1, "acg", "", "sku-1"), repo.products)
        self.assertNotIn((1, "acg", "", "sku-2"), repo.products)

    async def test_sync_catalog_wraps_provider_list_errors_without_writing(self) -> None:
        repo = FakeProductRepository()
        provider_error = ValueError("provider parse failed")
        provider = FakeFailingCatalogProvider(provider_error)
        service = ExternalCatalogSyncService(repository=repo)

        with self.assertRaisesRegex(ExternalSourceError, "目录获取失败") as caught:
            await service.sync_catalog(object(), tenant_id=7, provider=provider, limit=10)

        self.assertIs(provider_error, caught.exception.__cause__)
        self.assertEqual([(7, None, 10)], provider.calls)
        self.assertEqual(0, repo.created_count)
        self.assertEqual(0, repo.updated_count)

    async def test_sync_catalog_wraps_context_provider_list_errors_without_writing(self) -> None:
        repo = FakeProductRepository()
        provider_error = RuntimeError("upstream unavailable")
        provider = FakeFailingContextCatalogProvider(provider_error)
        service = ExternalCatalogSyncService(repository=repo)

        with self.assertRaisesRegex(ExternalSourceError, "目录获取失败") as caught:
            await service.sync_catalog(
                object(),
                tenant_id=7,
                provider=provider,
                source_key="shop-a",
                connection_id=11,
                limit=10,
            )

        self.assertIs(provider_error, caught.exception.__cause__)
        self.assertEqual(1, len(provider.context_calls))
        context, cursor, limit = provider.context_calls[0]
        self.assertEqual(7, context.tenant_id)
        self.assertEqual("shop-a", context.source_key)
        self.assertEqual(11, context.connection_id)
        self.assertIsNone(cursor)
        self.assertEqual(10, limit)
        self.assertEqual(0, repo.created_count)
        self.assertEqual(0, repo.updated_count)

    async def test_sync_catalog_stops_when_later_provider_call_fails(self) -> None:
        repo = FakeProductRepository()
        provider_error = RuntimeError("second page failed")
        provider = FakeCatalogProvider(
            {
                None: ExternalProductPage(products=[_external_product("sku-1")], next_cursor="page-2"),
                "page-2": provider_error,
            }
        )
        service = ExternalCatalogSyncService(repository=repo)

        with self.assertRaisesRegex(ExternalSourceError, "目录获取失败") as caught:
            await service.sync_catalog(object(), tenant_id=1, provider=provider, max_pages=3)

        self.assertIs(provider_error, caught.exception.__cause__)
        self.assertEqual([(1, None, 50), (1, "page-2", 50)], provider.calls)
        self.assertEqual(1, repo.created_count)
        self.assertIn((1, "acg", "", "sku-1"), repo.products)

    async def test_sync_catalog_preserves_provider_external_source_error(self) -> None:
        repo = FakeProductRepository()
        provider = FakeFailingCatalogProvider(ExternalSourceError("外部发卡源认证失败"))
        service = ExternalCatalogSyncService(repository=repo)

        with self.assertRaisesRegex(ExternalSourceError, "认证失败"):
            await service.sync_catalog(object(), tenant_id=7, provider=provider)

        self.assertEqual(0, repo.created_count)
        self.assertEqual(0, repo.updated_count)

    async def test_sync_registered_catalog_rejects_unknown_provider(self) -> None:
        service = ExternalCatalogSyncService(repository=FakeProductRepository())

        with self.assertRaises(ValueError):
            await service.sync_registered_catalog(object(), tenant_id=1, provider_name="missing")


if __name__ == "__main__":
    unittest.main()
