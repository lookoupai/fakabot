from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import logging
import time
from types import SimpleNamespace
import unittest
import warnings
from unittest.mock import AsyncMock, patch

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)
logging.getLogger("httpx").setLevel(logging.WARNING)

try:
    from cryptography.fernet import Fernet
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from pydantic import SecretStr

    from app.config import Settings
    from app.services.audit import AuditLogSummary
    from app.services.api_security import ApiRateLimitError
    from app.services.api_keys import ApiKeyService
    from app.services.external_sources import STANDARD_HTTP_PROVIDER, create_standard_http_provider
    from app.services.order_diagnostics import (
        OrderDeliveryDiagnostic,
        OrderDiagnosticsSummary,
        OrderExternalFulfillmentDiagnostic,
        OrderPaymentCallbackDiagnostic,
        OrderPaymentDiagnostic,
    )
    from app.services.reports import ExportJobSummary
    from app.services.risk import AfterSaleSummary, DisputeSummary
    from app.services.payments import PaymentUnavailableError
    from app.services.subscriptions import SubscriptionInvoiceSummary, SubscriptionOrder, TenantSubscriptionSummary
    from app.services.supply import (
        CreatedResellerProduct,
        CreatedSupplierOffer,
        ResellerApplicationSummary,
        ResellerProductSummary,
        SupplierApprovalSetting,
        SupplierOwnOfferSummary,
        SupplierOfferSummary,
    )
    import app.services.external_sources.registry as provider_registry
    from app.web.tenant_admin import create_tenant_admin_router
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过 Tenant Admin 运行时鉴权测试：{exc.name}") from exc


class _ScalarList:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return self._values


class _Result:
    def __init__(self, *, values: list[object] | None = None, scalar: object | None = None) -> None:
        self._values = values or []
        self._scalar = scalar

    def scalars(self) -> _ScalarList:
        return _ScalarList(self._values)

    def scalar_one_or_none(self) -> object | None:
        return self._scalar


class _FakeSession:
    def __init__(
        self,
        execute_results: list[_Result] | None = None,
        *,
        tenant_id: int = 7,
        feature_flags: dict[str, bool] | None = None,
    ) -> None:
        self.execute_results = list(execute_results or [])
        self.executed_queries: list[object] = []
        self.commit_count = 0
        self.tenant_id = tenant_id
        self.feature_flags = feature_flags or {"self_sale": True, "supplier": True, "reseller": True}

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    async def execute(self, query: object) -> _Result:
        self.executed_queries.append(query)
        query_text = str(query)
        if "FROM tenants" in query_text and "tenant_settings" not in query_text:
            return _Result(
                scalar=SimpleNamespace(
                    id=self.tenant_id,
                    self_sale_enabled=self.feature_flags["self_sale"],
                    supplier_enabled=self.feature_flags["supplier"],
                    reseller_enabled=self.feature_flags["reseller"],
                )
            )
        if "FROM tenant_settings" in query_text:
            return _Result(values=[])
        if not self.execute_results:
            raise AssertionError("未预期的 session.execute 调用")
        return self.execute_results.pop(0)

    async def commit(self) -> None:
        self.commit_count += 1


def _fake_session_factory() -> _FakeSession:
    return _FakeSession()


def _session_factory(session: _FakeSession):
    def factory() -> _FakeSession:
        return session

    return factory


def _client(settings: Settings, *, client_host: str = "testclient") -> TestClient:
    app = FastAPI()
    app.state.redis = None
    app.include_router(create_tenant_admin_router(settings))
    return TestClient(app, client=(client_host, 50000))


def _api_key(*, tenant_id: int = 7, scopes: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        tenant_id=tenant_id,
        scopes_json=scopes or ["orders:read"],
        ip_allowlist_json=[],
    )


def _authenticate(api_key: object):
    async def authenticate(self: ApiKeyService, session: object, plain_key: str) -> object | None:
        return api_key

    return authenticate


def _assert_json_keys_absent(test_case: unittest.TestCase, value: object, forbidden_keys: set[str]) -> None:
    if isinstance(value, dict):
        for key, nested_value in value.items():
            test_case.assertNotIn(key, forbidden_keys)
            _assert_json_keys_absent(test_case, nested_value, forbidden_keys)
    elif isinstance(value, list):
        for item in value:
            _assert_json_keys_absent(test_case, item, forbidden_keys)


def _settings_with_crypto() -> Settings:
    return Settings(token_encryption_key=SecretStr(Fernet.generate_key().decode()))


def _product(
    *,
    product_id: int,
    name: str,
    status: str,
    delivery_type: str,
    suggested_price: Decimal,
    currency: str = "USDT",
    category: str | None = None,
    sort_order: int = 0,
    external_source: str | None = None,
    source_key: str = "",
    external_id: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=product_id,
        external_source=external_source,
        source_key=source_key,
        external_id=external_id,
        name=name,
        category=category,
        sort_order=sort_order,
        status=status,
        delivery_type=delivery_type,
        suggested_price=suggested_price,
        currency=currency,
        storage_key="private/file.zip",
    )


class TenantAdminRuntimeAuthTest(unittest.TestCase):
    def test_missing_api_key_returns_401_without_database(self) -> None:
        settings = Settings()
        client = _client(settings)

        response = client.get("/api/v1/tenant/products")

        self.assertEqual(401, response.status_code)
        self.assertEqual("缺少 API Key", response.json()["detail"])

    def test_global_ip_allowlist_rejects_before_api_key_lookup(self) -> None:
        client = _client(Settings(tenant_admin_ip_allowlist={"203.0.113.0/24"}))

        response = client.get("/api/v1/tenant/products", headers={"X-API-Key": "fk_live_test"})

        self.assertEqual(403, response.status_code)
        self.assertIn("当前 IP 不允许访问 Tenant Admin API", response.json()["detail"])

    def test_invalid_api_key_returns_401(self) -> None:
        async def authenticate(self: ApiKeyService, session: object, plain_key: str) -> object | None:
            return None

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_fake_session_factory):
            with patch.object(ApiKeyService, "authenticate", authenticate):
                response = client.get("/api/v1/tenant/products", headers={"X-API-Key": "fk_live_test"})

        self.assertEqual(401, response.status_code)
        self.assertEqual("API Key 无效", response.json()["detail"])

    def test_api_key_ip_allowlist_rejects_after_authentication(self) -> None:
        api_key = SimpleNamespace(
            id=1,
            tenant_id=7,
            scopes_json=["products:read"],
            ip_allowlist_json=["203.0.113.0/24"],
        )

        async def authenticate(self: ApiKeyService, session: object, plain_key: str) -> object | None:
            return api_key

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_fake_session_factory):
            with patch.object(ApiKeyService, "authenticate", authenticate):
                response = client.get("/api/v1/tenant/products", headers={"X-API-Key": "fk_live_test"})

        self.assertEqual(403, response.status_code)
        self.assertIn("当前 IP 不允许访问 Tenant Admin API Key", response.json()["detail"])

    def test_allowlists_use_forwarded_for_from_trusted_proxy(self) -> None:
        api_key = SimpleNamespace(
            id=1,
            tenant_id=7,
            scopes_json=["products:read"],
            ip_allowlist_json=["203.0.113.10"],
        )
        session = _FakeSession()

        client = _client(
            Settings(
                tenant_admin_ip_allowlist={"203.0.113.0/24"},
                trusted_proxy_ips={"10.0.0.0/24"},
            ),
            client_host="10.0.0.2",
        )
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                response = client.get(
                    "/api/v1/tenant/external-sources",
                    headers={
                        "X-API-Key": "fk_live_test",
                        "X-Forwarded-For": "203.0.113.10, 198.51.100.20",
                    },
                )

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, session.commit_count)

    def test_scope_shortage_returns_403_before_route_body_runs(self) -> None:
        api_key = SimpleNamespace(
            id=1,
            tenant_id=7,
            scopes_json=["products:read"],
            ip_allowlist_json=[],
        )

        async def authenticate(self: ApiKeyService, session: object, plain_key: str) -> object | None:
            return api_key

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_fake_session_factory):
            with patch.object(ApiKeyService, "authenticate", authenticate):
                response = client.post(
                    "/api/v1/tenant/products",
                    headers={"X-API-Key": "fk_live_test"},
                    json={"name": "测试商品", "price": "1.00", "delivery_type": "card_fixed"},
                )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])

    def test_missing_required_signature_returns_401_after_authentication(self) -> None:
        api_key = SimpleNamespace(
            id=1,
            tenant_id=7,
            scopes_json=["products:read"],
            ip_allowlist_json=[],
        )

        async def authenticate(self: ApiKeyService, session: object, plain_key: str) -> object | None:
            return api_key

        client = _client(Settings(tenant_admin_require_signature=True))
        with patch("app.web.tenant_admin.get_session_factory", return_value=_fake_session_factory):
            with patch.object(ApiKeyService, "authenticate", authenticate):
                response = client.get("/api/v1/tenant/products", headers={"X-API-Key": "fk_live_test"})

        self.assertEqual(401, response.status_code)
        self.assertEqual("缺少请求签名", response.json()["detail"])

    def test_invalid_signature_returns_401_after_authentication(self) -> None:
        api_key = SimpleNamespace(
            id=1,
            tenant_id=7,
            scopes_json=["products:read"],
            ip_allowlist_json=[],
        )

        async def authenticate(self: ApiKeyService, session: object, plain_key: str) -> object | None:
            return api_key

        client = _client(Settings(tenant_admin_require_signature=True))
        with patch("app.web.tenant_admin.get_session_factory", return_value=_fake_session_factory):
            with patch.object(ApiKeyService, "authenticate", authenticate):
                response = client.get(
                    "/api/v1/tenant/products",
                    headers={
                        "X-API-Key": "fk_live_test",
                        "X-Faka-Timestamp": str(int(time.time())),
                        "X-Faka-Signature": "bad-signature",
                    },
                )

        self.assertEqual(401, response.status_code)
        self.assertEqual("请求签名无效", response.json()["detail"])

    def test_expired_signature_returns_401_after_authentication(self) -> None:
        api_key = SimpleNamespace(
            id=1,
            tenant_id=7,
            scopes_json=["products:read"],
            ip_allowlist_json=[],
        )

        async def authenticate(self: ApiKeyService, session: object, plain_key: str) -> object | None:
            return api_key

        client = _client(Settings(tenant_admin_require_signature=True))
        with patch("app.web.tenant_admin.get_session_factory", return_value=_fake_session_factory):
            with patch.object(ApiKeyService, "authenticate", authenticate):
                response = client.get(
                    "/api/v1/tenant/products",
                    headers={
                        "X-API-Key": "fk_live_test",
                        "X-Faka-Timestamp": "1",
                        "X-Faka-Signature": "bad-signature",
                    },
                )

        self.assertEqual(401, response.status_code)
        self.assertEqual("签名时间戳超出允许偏差", response.json()["detail"])

    def test_rate_limit_error_returns_429_after_authentication(self) -> None:
        api_key = SimpleNamespace(
            id=1,
            tenant_id=7,
            scopes_json=["products:read"],
            ip_allowlist_json=[],
        )

        async def authenticate(self: ApiKeyService, session: object, plain_key: str) -> object | None:
            return api_key

        async def reject_rate_limit(**kwargs: object) -> None:
            raise ApiRateLimitError("请求过于频繁，请稍后再试")

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_fake_session_factory):
            with patch.object(ApiKeyService, "authenticate", authenticate):
                with patch("app.web.tenant_admin.hit_rate_limit", reject_rate_limit):
                    response = client.get("/api/v1/tenant/products", headers={"X-API-Key": "fk_live_test"})

        self.assertEqual(429, response.status_code)
        self.assertEqual("请求过于频繁，请稍后再试", response.json()["detail"])

    def test_rate_limit_falls_back_to_local_limiter_when_redis_is_missing(self) -> None:
        api_key = SimpleNamespace(
            id=1,
            tenant_id=7,
            scopes_json=["products:read"],
            ip_allowlist_json=[],
        )
        session = _FakeSession()

        client = _client(Settings(tenant_admin_rate_limit_per_minute=1))
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                first_response = client.get("/api/v1/tenant/external-sources", headers={"X-API-Key": "fk_live_test"})
                second_response = client.get("/api/v1/tenant/external-sources", headers={"X-API-Key": "fk_live_test"})

        self.assertEqual(200, first_response.status_code)
        self.assertEqual(429, second_response.status_code)
        self.assertEqual("请求过于频繁，请稍后再试", second_response.json()["detail"])
        self.assertEqual(1, session.commit_count)

    def test_list_products_requires_products_read_scope_before_service(self) -> None:
        api_key = _api_key(scopes=["orders:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.ProductRepository") as product_repo:
                    response = client.get("/api/v1/tenant/products", headers={"X-API-Key": "fk_live_test"})

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        product_repo.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_list_products_is_tenant_scoped_and_redacted(self) -> None:
        session = _FakeSession()
        product = _product(
            product_id=12,
            external_source="acg",
            source_key="main",
            external_id="sku-1",
            name="商品 A",
            category="账号",
            status="on",
            delivery_type="card_pool",
            suggested_price=Decimal("9.90"),
            sort_order=-10,
        )
        no_variant_product = _product(
            product_id=13,
            name="商品 B",
            status="draft",
            delivery_type="file_download",
            suggested_price=Decimal("19.90"),
            currency="CNY",
        )
        variant = SimpleNamespace(price=Decimal("8.80"), currency="USDT")
        list_products = AsyncMock(return_value=[(product, variant, 3), (no_variant_product, None, 0)])

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["products:read"]))):
                with patch("app.web.tenant_admin.ProductRepository") as product_repo:
                    product_repo.return_value.list_products = list_products
                    response = client.get("/api/v1/tenant/products", headers={"X-API-Key": "fk_live_test"})

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(2, len(payload))
        self.assertEqual(
            {
                "id",
                "external_source",
                "source_key",
                "external_id",
                "name",
                "category",
                "sort_order",
                "status",
                "delivery_type",
                "price",
                "currency",
                "available_count",
            },
            set(payload[0]),
        )
        self.assertEqual(12, payload[0]["id"])
        self.assertEqual("acg", payload[0]["external_source"])
        self.assertEqual("main", payload[0]["source_key"])
        self.assertEqual("sku-1", payload[0]["external_id"])
        self.assertEqual(-10, payload[0]["sort_order"])
        self.assertEqual("8.80", payload[0]["price"])
        self.assertEqual(13, payload[1]["id"])
        self.assertIsNone(payload[1]["external_source"])
        self.assertEqual("", payload[1]["source_key"])
        self.assertIsNone(payload[1]["external_id"])
        self.assertEqual(0, payload[1]["sort_order"])
        self.assertEqual("19.90", payload[1]["price"])
        self.assertEqual("CNY", payload[1]["currency"])
        self.assertNotIn("description", response.text)
        self.assertNotIn("cover_url", response.text)
        self.assertNotIn("tenant_id", response.text)
        self.assertNotIn("storage_key", response.text)
        self.assertNotIn("private/file.zip", response.text)
        self.assertNotIn("encrypted_token", response.text)
        list_products.assert_awaited_once_with(session, 7)
        self.assertEqual(1, session.commit_count)

    def test_create_product_requires_products_write_scope_before_service(self) -> None:
        api_key = _api_key(scopes=["products:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.ProductRepository") as product_repo:
                    response = client.post(
                        "/api/v1/tenant/products",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"name": "商品 A", "price": "9.90", "delivery_type": "card_pool"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        product_repo.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_create_product_commits_and_returns_safe_payload(self) -> None:
        session = _FakeSession()
        product = _product(
            product_id=12,
            name="商品 A",
            category="账号",
            status="draft",
            delivery_type="card_pool",
            suggested_price=Decimal("9.90"),
            currency="USDT",
        )
        create_self_product = AsyncMock(return_value=product)

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["products:write"]))):
                with patch("app.web.tenant_admin.ProductRepository") as product_repo:
                    product_repo.return_value.create_self_product = create_self_product
                    response = client.post(
                        "/api/v1/tenant/products",
                        headers={"X-API-Key": "fk_live_test"},
                        json={
                            "name": "商品 A",
                            "price": "9.90",
                            "delivery_type": "card_pool",
                            "description": "内部描述",
                            "category": "账号",
                        },
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(12, payload["id"])
        self.assertEqual("商品 A", payload["name"])
        self.assertEqual("账号", payload["category"])
        self.assertEqual(0, payload["sort_order"])
        self.assertEqual("9.90", payload["price"])
        self.assertEqual(0, payload["available_count"])
        self.assertNotIn("description", payload)
        self.assertNotIn("storage_key", response.text)
        self.assertEqual(2, session.commit_count)
        create_self_product.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            name="商品 A",
            price=Decimal("9.90"),
            delivery_type="card_pool",
            description="内部描述",
            category="账号",
        )

    def test_create_product_value_error_returns_400_without_route_commit(self) -> None:
        session = _FakeSession()
        create_self_product = AsyncMock(side_effect=ValueError("发货类型不支持"))

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["products:write"]))):
                with patch("app.web.tenant_admin.ProductRepository") as product_repo:
                    product_repo.return_value.create_self_product = create_self_product
                    response = client.post(
                        "/api/v1/tenant/products",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"name": "商品 A", "price": "9.90", "delivery_type": "unknown"},
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("发货类型不支持", response.json()["detail"])
        self.assertEqual(1, session.commit_count)
        create_self_product.assert_awaited_once()

    def test_sync_products_requires_products_write_scope_before_service(self) -> None:
        api_key = _api_key(scopes=["products:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.ProductRepository") as product_repo:
                    response = client.post(
                        "/api/v1/tenant/products/sync",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"products": [{"name": "商品 A", "price": "9.90", "delivery_type": "card_pool"}]},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        product_repo.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_sync_products_rejects_duplicate_product_ids_before_service(self) -> None:
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["products:write"]))):
                with patch("app.web.tenant_admin.ProductRepository") as product_repo:
                    response = client.post(
                        "/api/v1/tenant/products/sync",
                        headers={"X-API-Key": "fk_live_test"},
                        json={
                            "products": [
                                {"product_id": 12, "name": "商品 A", "price": "9.90", "delivery_type": "card_pool"},
                                {"product_id": 12, "name": "商品 B", "price": "8.80", "delivery_type": "card_pool"},
                            ]
                        },
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("同步列表内 product_id 不能重复", response.json()["detail"])
        product_repo.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_sync_products_rejects_invalid_payload_before_service(self) -> None:
        cases = [
            (
                "duplicate_external_ref",
                {
                    "products": [
                        {
                            "external_source": "acg",
                            "source_key": "main",
                            "external_id": "sku-1",
                            "name": "商品 A",
                            "price": "9.90",
                            "delivery_type": "card_pool",
                        },
                        {
                            "external_source": "acg",
                            "source_key": "main",
                            "external_id": "sku-1",
                            "name": "商品 B",
                            "price": "8.80",
                            "delivery_type": "card_pool",
                        },
                    ]
                },
                "同步列表内 external_source、source_key 和 external_id 组合不能重复",
            ),
            (
                "partial_external_ref",
                {
                    "products": [
                        {
                            "external_source": "acg",
                            "name": "商品 A",
                            "price": "9.90",
                            "delivery_type": "card_pool",
                        }
                    ]
                },
                "外部商品映射需要同时提供 external_source 和 external_id",
            ),
            (
                "invalid_status",
                {
                    "products": [
                        {
                            "name": "商品 A",
                            "price": "9.90",
                            "delivery_type": "card_pool",
                            "status": "deleted",
                        }
                    ]
                },
                "不支持的商品状态",
            ),
        ]

        for label, payload, expected_detail in cases:
            with self.subTest(label=label):
                session = _FakeSession()
                client = _client(Settings())
                with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
                    with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["products:write"]))):
                        with patch("app.web.tenant_admin.ProductRepository") as product_repo:
                            response = client.post(
                                "/api/v1/tenant/products/sync",
                                headers={"X-API-Key": "fk_live_test"},
                                json=payload,
                            )

                self.assertEqual(400, response.status_code)
                self.assertEqual(expected_detail, response.json()["detail"])
                product_repo.assert_not_called()
                self.assertEqual(1, session.commit_count)

    def test_get_subscription_status_requires_subscriptions_read_scope_before_service(self) -> None:
        api_key = _api_key(scopes=["orders:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.SubscriptionService") as subscription_service:
                    response = client.get(
                        "/api/v1/tenant/subscription/status",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        subscription_service.assert_not_called()

    def test_get_subscription_status_returns_safe_tenant_scoped_payload(self) -> None:
        session = _FakeSession()
        now = datetime.now(timezone.utc)
        summary = TenantSubscriptionSummary(
            status="active",
            plan_code="default_monthly",
            plan_name="默认月付套餐",
            monthly_price=Decimal("10.00"),
            currency="USDT",
            trial_days=30,
            grace_days=3,
            trial_ends_at=now - timedelta(days=30),
            current_period_ends_at=now + timedelta(days=10),
            subscription_ends_at=now + timedelta(days=10),
            grace_ends_at=None,
            suspended_at=None,
            data_retention_until=None,
            created_at=now - timedelta(days=60),
            updated_at=now,
        )
        get_summary = AsyncMock(return_value=summary)

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["subscriptions:read"]))):
                with patch("app.web.tenant_admin.SubscriptionService") as subscription_service:
                    subscription_service.return_value.get_tenant_subscription_summary = get_summary
                    response = client.get(
                        "/api/v1/tenant/subscription/status",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(
            {
                "status",
                "plan_code",
                "plan_name",
                "monthly_price",
                "currency",
                "trial_days",
                "grace_days",
                "trial_ends_at",
                "current_period_ends_at",
                "subscription_ends_at",
                "grace_ends_at",
                "suspended_at",
                "data_retention_until",
                "created_at",
                "updated_at",
            },
            set(payload),
        )
        self.assertEqual("active", payload["status"])
        self.assertEqual("default_monthly", payload["plan_code"])
        self.assertEqual("默认月付套餐", payload["plan_name"])
        self.assertEqual("10.00", payload["monthly_price"])
        self.assertEqual("USDT", payload["currency"])
        self.assertEqual(30, payload["trial_days"])
        self.assertEqual(3, payload["grace_days"])
        self.assertIsNotNone(payload["current_period_ends_at"])
        for marker in (
            "tenant_id",
            "owner_user_id",
            "subscription_id",
            "plan_id",
            "invoice_id",
            "payment_url",
            "provider_trade_no",
            "payload_json",
            "metadata_json",
            "token",
            "secret",
            "api_key",
        ):
            self.assertNotIn(marker, response.text)
        get_summary.assert_awaited_once_with(session, tenant_id=7)

    def test_get_subscription_status_returns_404_for_missing_tenant(self) -> None:
        session = _FakeSession()
        get_summary = AsyncMock(return_value=None)

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["subscriptions:read"]))):
                with patch("app.web.tenant_admin.SubscriptionService") as subscription_service:
                    subscription_service.return_value.get_tenant_subscription_summary = get_summary
                    response = client.get(
                        "/api/v1/tenant/subscription/status",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(404, response.status_code)
        self.assertEqual("订阅不存在", response.json()["detail"])
        get_summary.assert_awaited_once_with(session, tenant_id=7)

    def test_list_subscription_invoices_requires_subscriptions_read_scope_before_service(self) -> None:
        api_key = _api_key(scopes=["orders:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.SubscriptionService") as subscription_service:
                    response = client.get(
                        "/api/v1/tenant/subscription/invoices",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        subscription_service.assert_not_called()

    def test_list_subscription_invoices_returns_safe_tenant_scoped_payload(self) -> None:
        session = _FakeSession()
        now = datetime.now(timezone.utc)
        invoice = SubscriptionInvoiceSummary(
            out_trade_no="SUB_123",
            amount=Decimal("10.00"),
            currency="USDT",
            status="paid",
            paid_at=now,
            created_at=now - timedelta(minutes=10),
        )
        list_invoices = AsyncMock(return_value=[invoice])

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["subscriptions:read"]))):
                with patch("app.web.tenant_admin.SubscriptionService") as subscription_service:
                    subscription_service.return_value.list_tenant_subscription_invoices = list_invoices
                    response = client.get(
                        "/api/v1/tenant/subscription/invoices?status=paid&limit=50",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual({"invoices"}, set(payload))
        self.assertEqual(1, len(payload["invoices"]))
        item = payload["invoices"][0]
        self.assertEqual(
            {"out_trade_no", "amount", "currency", "status", "paid_at", "created_at"},
            set(item),
        )
        self.assertEqual("SUB_123", item["out_trade_no"])
        self.assertEqual("10.00", item["amount"])
        self.assertEqual("USDT", item["currency"])
        self.assertEqual("paid", item["status"])
        for marker in (
            "tenant_id",
            "subscription_id",
            "plan_id",
            "invoice_id",
            "order_id",
            "payment_id",
            "payment_url",
            "provider_trade_no",
            "payload_json",
            "metadata_json",
            "token",
            "secret",
            "api_key",
        ):
            self.assertNotIn(marker, response.text)
        list_invoices.assert_awaited_once_with(session, tenant_id=7, status="paid", limit=50)

    def test_list_subscription_invoices_value_error_returns_400_without_secret(self) -> None:
        session = _FakeSession()
        list_invoices = AsyncMock(side_effect=ValueError("secret=plain-secret"))

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["subscriptions:read"]))):
                with patch("app.web.tenant_admin.SubscriptionService") as subscription_service:
                    subscription_service.return_value.list_tenant_subscription_invoices = list_invoices
                    response = client.get(
                        "/api/v1/tenant/subscription/invoices?status=bad",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("订阅账单查询参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)

    def test_create_subscription_renewal_order_requires_subscriptions_write_before_service(self) -> None:
        api_key = _api_key(scopes=["subscriptions:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.SubscriptionService") as subscription_service:
                    with patch("app.web.tenant_admin.PaymentService") as payment_service:
                        response = client.post(
                            "/api/v1/tenant/subscription/renewal-orders",
                            headers={"X-API-Key": "fk_live_test"},
                            json={"months": 1},
                        )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        subscription_service.assert_not_called()
        payment_service.assert_not_called()

    def test_create_subscription_renewal_order_rejects_extra_fields_before_service(self) -> None:
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["subscriptions:write"]))):
                with patch("app.web.tenant_admin.SubscriptionService") as subscription_service:
                    with patch("app.web.tenant_admin.PaymentService") as payment_service:
                        response = client.post(
                            "/api/v1/tenant/subscription/renewal-orders",
                            headers={"X-API-Key": "fk_live_test"},
                            json={"months": 1, "payment_provider": "usdt_trc20_direct"},
                        )

        self.assertEqual(422, response.status_code)
        subscription_service.assert_not_called()
        payment_service.assert_not_called()

    def test_create_subscription_renewal_order_is_tenant_scoped_and_returns_payment_link(self) -> None:
        session = _FakeSession()
        now = datetime.now(timezone.utc)
        renewal_order = SubscriptionOrder(
            order_id=81,
            out_trade_no="SUB_123",
            amount=Decimal("20.00"),
            currency="USDT",
            months=2,
            expires_at=now + timedelta(minutes=30),
        )
        create_renewal_order = AsyncMock(return_value=renewal_order)
        create_payment = AsyncMock(
            return_value=SimpleNamespace(
                provider="epusdt_gmpay",
                payment_url="https://pay.example.test/pay/SUB_123",
                out_trade_no=renewal_order.out_trade_no,
                amount=renewal_order.amount,
                currency=renewal_order.currency,
            )
        )
        settings = Settings(subscription_monthly_price=Decimal("10.00"))
        client = _client(settings)

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["subscriptions:write"]))):
                with patch("app.web.tenant_admin.SubscriptionService") as subscription_service:
                    with patch("app.web.tenant_admin.PaymentService") as payment_service:
                        subscription_service.return_value.create_renewal_order = create_renewal_order
                        payment_service.return_value.create_payment_for_order = create_payment
                        response = client.post(
                            "/api/v1/tenant/subscription/renewal-orders",
                            headers={"X-API-Key": "fk_live_test"},
                            json={"months": 2},
                        )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(
            {
                "out_trade_no",
                "amount",
                "currency",
                "months",
                "expires_at",
                "payment_available",
                "payment_provider",
                "payment_url",
                "payment_failure_reason",
            },
            set(payload),
        )
        self.assertEqual("SUB_123", payload["out_trade_no"])
        self.assertEqual("20.00", payload["amount"])
        self.assertEqual("USDT", payload["currency"])
        self.assertEqual(2, payload["months"])
        self.assertTrue(payload["payment_available"])
        self.assertEqual("epusdt_gmpay", payload["payment_provider"])
        self.assertEqual("https://pay.example.test/pay/SUB_123", payload["payment_url"])
        self.assertIsNone(payload["payment_failure_reason"])
        for marker in (
            "tenant_id",
            "subscription_id",
            "plan_id",
            "invoice_id",
            "order_id",
            "payment_id",
            "provider_trade_no",
            "payload_json",
            "metadata_json",
            "token",
            "secret",
            "api_key",
        ):
            self.assertNotIn(marker, response.text)
        create_renewal_order.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            buyer_telegram_user_id=0,
            months=2,
            monthly_price=settings.subscription_monthly_price,
        )
        create_payment.assert_awaited_once_with(session, renewal_order.order_id)
        self.assertEqual(3, session.commit_count)

    def test_create_subscription_renewal_order_keeps_order_when_payment_unavailable(self) -> None:
        session = _FakeSession()
        renewal_order = SubscriptionOrder(
            order_id=81,
            out_trade_no="SUB_123",
            amount=Decimal("10.00"),
            currency="USDT",
            months=1,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        create_renewal_order = AsyncMock(return_value=renewal_order)
        create_payment = AsyncMock(side_effect=PaymentUnavailableError("secret_key=plain-secret"))

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["subscriptions:write"]))):
                with patch("app.web.tenant_admin.SubscriptionService") as subscription_service:
                    with patch("app.web.tenant_admin.PaymentService") as payment_service:
                        subscription_service.return_value.create_renewal_order = create_renewal_order
                        payment_service.return_value.create_payment_for_order = create_payment
                        response = client.post(
                            "/api/v1/tenant/subscription/renewal-orders",
                            headers={"X-API-Key": "fk_live_test"},
                            json={"months": 1},
                        )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("SUB_123", payload["out_trade_no"])
        self.assertFalse(payload["payment_available"])
        self.assertIsNone(payload["payment_provider"])
        self.assertIsNone(payload["payment_url"])
        self.assertEqual("支付配置暂不可用", payload["payment_failure_reason"])
        self.assertNotIn("plain-secret", response.text)
        create_renewal_order.assert_awaited_once()
        create_payment.assert_awaited_once_with(session, renewal_order.order_id)
        self.assertEqual(2, session.commit_count)

    def test_list_supplier_offers_requires_supply_read_scope_before_service(self) -> None:
        api_key = _api_key(scopes=["products:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    response = client.get(
                        "/api/v1/tenant/supply/supplier-offers",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        supply_service.assert_not_called()

    def test_supplier_supply_routes_reject_disabled_supplier_feature_before_service(self) -> None:
        cases = (
            ("GET", "/api/v1/tenant/supply/supplier-offers", None),
            ("POST", "/api/v1/tenant/supply/supplier-offers", {"product_id": 21, "suggested_price": "12.00"}),
            ("PATCH", "/api/v1/tenant/supply/supplier-offers/91/approval", {"requires_approval": False}),
            ("GET", "/api/v1/tenant/supply/supplier-applications", None),
            (
                "POST",
                "/api/v1/tenant/supply/supplier-applications/approve",
                {"supplier_offer_id": 91, "reseller_tenant_id": 88},
            ),
            (
                "POST",
                "/api/v1/tenant/supply/supplier-applications/reject",
                {"supplier_offer_id": 91, "reseller_tenant_id": 88},
            ),
            (
                "POST",
                "/api/v1/tenant/supply/supplier-rules",
                {"supplier_offer_id": 91, "reseller_tenant_id": 88, "pricing_value": "8.50"},
            ),
        )

        for method, path, payload in cases:
            with self.subTest(path=path):
                session = _FakeSession(feature_flags={"self_sale": True, "supplier": False, "reseller": True})
                client = _client(Settings())
                with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
                    with patch.object(
                        ApiKeyService,
                        "authenticate",
                        _authenticate(_api_key(tenant_id=7, scopes=["supply:read", "supply:write"])),
                    ):
                        with patch("app.web.tenant_admin.SupplyService") as supply_service:
                            response = client.request(
                                method,
                                path,
                                headers={"X-API-Key": "fk_live_test"},
                                json=payload,
                            )

                self.assertEqual(403, response.status_code)
                self.assertEqual("供货功能已关闭", response.json()["detail"])
                self.assertNotIn("tenant_id", response.text)
                self.assertEqual(1, session.commit_count)
                supply_service.assert_not_called()

    def test_list_supplier_offers_is_tenant_scoped_and_redacted(self) -> None:
        session = _FakeSession()
        offer = SupplierOwnOfferSummary(
            offer_id=91,
            product_name="供货卡密",
            category="会员",
            delivery_type="card_pool",
            suggested_price=Decimal("12.00"),
            min_sale_price=Decimal("11.00"),
            supplier_cost=Decimal("9.00"),
            currency="USDT",
            available_count=8,
            requires_approval=True,
            status="on",
        )
        list_offers = AsyncMock(return_value=[offer])

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["supply:read"]))):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    supply_service.return_value.list_supplier_offers = list_offers
                    response = client.get(
                        "/api/v1/tenant/supply/supplier-offers?limit=50",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual({"offers"}, set(payload))
        self.assertEqual(1, len(payload["offers"]))
        item = payload["offers"][0]
        self.assertEqual(
            {
                "supplier_offer_id",
                "product_name",
                "delivery_type",
                "suggested_price",
                "min_sale_price",
                "supplier_cost",
                "currency",
                "available_count",
                "requires_approval",
                "status",
            },
            set(item),
        )
        self.assertEqual(91, item["supplier_offer_id"])
        _assert_json_keys_absent(
            self,
            payload,
            {
                "tenant_id",
                "supplier_tenant_id",
                "product_id",
                "variant_id",
                "default_pricing_mode",
                "default_pricing_value",
                "hidden_supplier_allowed",
                "storage_key",
                "token",
                "secret",
                "api_key",
            },
        )
        list_offers.assert_awaited_once_with(session=session, supplier_tenant_id=7, limit=50)

    def test_create_supplier_offer_requires_supply_write_before_service(self) -> None:
        api_key = _api_key(scopes=["supply:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    response = client.post(
                        "/api/v1/tenant/supply/supplier-offers",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"product_id": 21, "suggested_price": "12.00"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        supply_service.assert_not_called()

    def test_create_supplier_offer_rejects_extra_fields_before_service(self) -> None:
        session = _FakeSession()
        forbidden_fields = (
            "tenant_id",
            "supplier_tenant_id",
            "reseller_tenant_id",
            "variant_id",
            "rule_id",
            "default_pricing_value",
            "hidden_supplier_allowed",
            "storage_key",
            "token",
            "secret",
            "api_key",
        )

        for field in forbidden_fields:
            with self.subTest(field=field):
                client = _client(Settings())
                with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
                    with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["supply:write"]))):
                        with patch("app.web.tenant_admin.SupplyService") as supply_service:
                            response = client.post(
                                "/api/v1/tenant/supply/supplier-offers",
                                headers={"X-API-Key": "fk_live_test"},
                                json={"product_id": 21, "suggested_price": "12.00", field: "forbidden"},
                            )

                self.assertEqual(422, response.status_code)
                supply_service.assert_not_called()

    def test_create_supplier_offer_is_tenant_scoped_and_redacted(self) -> None:
        session = _FakeSession()
        offer = CreatedSupplierOffer(
            offer_id=91,
            product_id=21,
            variant_id=22,
            product_name="供货卡密",
            delivery_type="card_pool",
            suggested_price=Decimal("12.00"),
            min_sale_price=Decimal("11.00"),
            supplier_cost=Decimal("9.00"),
            currency="USDT",
            requires_approval=True,
            status="on",
        )
        create_offer = AsyncMock(return_value=offer)

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["supply:write"]))):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    supply_service.return_value.create_supplier_offer = create_offer
                    response = client.post(
                        "/api/v1/tenant/supply/supplier-offers",
                        headers={"X-API-Key": "fk_live_test"},
                        json={
                            "product_id": 21,
                            "suggested_price": "12.00",
                            "min_sale_price": "11.00",
                            "requires_approval": True,
                        },
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(
            {
                "supplier_offer_id",
                "product_name",
                "delivery_type",
                "suggested_price",
                "min_sale_price",
                "supplier_cost",
                "currency",
                "requires_approval",
                "status",
            },
            set(payload),
        )
        _assert_json_keys_absent(
            self,
            payload,
            {
                "tenant_id",
                "supplier_tenant_id",
                "product_id",
                "variant_id",
                "default_pricing_value",
                "hidden_supplier_allowed",
                "storage_key",
                "token",
                "secret",
                "api_key",
            },
        )
        create_offer.assert_awaited_once_with(
            session=session,
            supplier_tenant_id=7,
            product_id=21,
            suggested_price=Decimal("12.00"),
            min_sale_price=Decimal("11.00"),
            requires_approval=True,
        )
        self.assertEqual(2, session.commit_count)

    def test_create_supplier_offer_value_error_returns_400_without_secret(self) -> None:
        session = _FakeSession()
        create_offer = AsyncMock(side_effect=ValueError("secret=plain-secret"))

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["supply:write"]))):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    supply_service.return_value.create_supplier_offer = create_offer
                    response = client.post(
                        "/api/v1/tenant/supply/supplier-offers",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"product_id": 21, "suggested_price": "12.00"},
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("供货商品参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertEqual(1, session.commit_count)

    def test_update_supplier_offer_approval_is_tenant_scoped_and_redacted(self) -> None:
        session = _FakeSession()
        setting = SupplierApprovalSetting(offer_id=91, requires_approval=False, status="on")
        set_approval = AsyncMock(return_value=setting)

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["supply:write"]))):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    supply_service.return_value.set_supplier_offer_approval = set_approval
                    response = client.patch(
                        "/api/v1/tenant/supply/supplier-offers/91/approval",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"requires_approval": False},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual({"supplier_offer_id", "requires_approval", "status"}, set(payload))
        _assert_json_keys_absent(self, payload, {"tenant_id", "supplier_tenant_id", "actor_user_id", "token", "secret"})
        set_approval.assert_awaited_once_with(
            session=session,
            supplier_tenant_id=7,
            supplier_offer_id=91,
            requires_approval=False,
            actor_user_id=None,
        )
        self.assertEqual(2, session.commit_count)

    def test_update_supplier_offer_approval_requires_supply_write_before_service(self) -> None:
        api_key = _api_key(scopes=["supply:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    response = client.patch(
                        "/api/v1/tenant/supply/supplier-offers/91/approval",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"requires_approval": False},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        supply_service.assert_not_called()

    def test_update_supplier_offer_approval_rejects_extra_fields_before_service(self) -> None:
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["supply:write"]))):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    response = client.patch(
                        "/api/v1/tenant/supply/supplier-offers/91/approval",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"requires_approval": False, "supplier_tenant_id": 7},
                    )

        self.assertEqual(422, response.status_code)
        supply_service.assert_not_called()

    def test_update_supplier_offer_approval_value_error_returns_400_without_secret(self) -> None:
        session = _FakeSession()
        set_approval = AsyncMock(side_effect=ValueError("secret=plain-secret"))

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["supply:write"]))):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    supply_service.return_value.set_supplier_offer_approval = set_approval
                    response = client.patch(
                        "/api/v1/tenant/supply/supplier-offers/91/approval",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"requires_approval": False},
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("供货审批参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertEqual(1, session.commit_count)

    def test_list_supplier_applications_requires_supply_read_scope_before_service(self) -> None:
        api_key = _api_key(scopes=["products:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    response = client.get(
                        "/api/v1/tenant/supply/supplier-applications",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        supply_service.assert_not_called()

    def test_list_supplier_applications_is_tenant_scoped_and_redacted(self) -> None:
        session = _FakeSession()
        now = datetime.now(timezone.utc)
        application = ResellerApplicationSummary(
            rule_id=31,
            supplier_offer_id=91,
            supplier_tenant_id=7,
            supplier_store_name="供应商",
            reseller_tenant_id=88,
            reseller_store_name="代理商",
            product_name="供货卡密",
            status="pending",
            pricing_value=Decimal("9.00"),
            min_sale_price=Decimal("10.00"),
            currency="USDT",
            updated_at=now,
        )
        list_applications = AsyncMock(return_value=[application])

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["supply:read"]))):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    supply_service.return_value.list_reseller_applications = list_applications
                    response = client.get(
                        "/api/v1/tenant/supply/supplier-applications?limit=50",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual({"applications"}, set(payload))
        item = payload["applications"][0]
        self.assertEqual(
            {
                "supplier_offer_id",
                "reseller_tenant_id",
                "reseller_store_name",
                "product_name",
                "status",
                "pricing_value",
                "min_sale_price",
                "currency",
                "updated_at",
            },
            set(item),
        )
        self.assertEqual(88, item["reseller_tenant_id"])
        self.assertEqual("代理商", item["reseller_store_name"])
        _assert_json_keys_absent(
            self,
            payload,
            {"rule_id", "supplier_tenant_id", "supplier_store_name", "product_id", "variant_id", "token", "secret"},
        )
        self.assertNotIn("供应商", response.text)
        list_applications.assert_awaited_once_with(session=session, supplier_tenant_id=7, limit=50)

    def test_approve_supplier_application_requires_supply_write_before_service(self) -> None:
        api_key = _api_key(scopes=["supply:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    response = client.post(
                        "/api/v1/tenant/supply/supplier-applications/approve",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"supplier_offer_id": 91, "reseller_tenant_id": 88},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        supply_service.assert_not_called()

    def test_approve_supplier_application_rejects_extra_fields_before_service(self) -> None:
        session = _FakeSession()
        forbidden_fields = (
            "tenant_id",
            "supplier_tenant_id",
            "product_id",
            "variant_id",
            "rule_id",
            "pricing_mode",
            "pricing_value",
            "min_sale_price",
            "default_pricing_value",
            "storage_key",
            "token",
            "secret",
            "api_key",
        )

        for field in forbidden_fields:
            with self.subTest(field=field):
                client = _client(Settings())
                with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
                    with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["supply:write"]))):
                        with patch("app.web.tenant_admin.SupplyService") as supply_service:
                            response = client.post(
                                "/api/v1/tenant/supply/supplier-applications/approve",
                                headers={"X-API-Key": "fk_live_test"},
                                json={"supplier_offer_id": 91, "reseller_tenant_id": 88, field: "forbidden"},
                            )

                self.assertEqual(422, response.status_code)
                supply_service.assert_not_called()

    def test_approve_supplier_application_is_tenant_scoped_and_redacted(self) -> None:
        session = _FakeSession()
        now = datetime.now(timezone.utc)
        application = ResellerApplicationSummary(
            rule_id=31,
            supplier_offer_id=91,
            supplier_tenant_id=7,
            supplier_store_name="供应商",
            reseller_tenant_id=88,
            reseller_store_name="代理商",
            product_name="供货卡密",
            status="active",
            pricing_value=Decimal("8.50"),
            min_sale_price=Decimal("10.00"),
            currency="USDT",
            updated_at=now,
        )
        approve_reseller = AsyncMock(return_value=application)

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["supply:write"]))):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    supply_service.return_value.approve_reseller_application = approve_reseller
                    response = client.post(
                        "/api/v1/tenant/supply/supplier-applications/approve",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"supplier_offer_id": 91, "reseller_tenant_id": 88},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(88, payload["reseller_tenant_id"])
        self.assertEqual("代理商", payload["reseller_store_name"])
        _assert_json_keys_absent(
            self,
            payload,
            {"rule_id", "supplier_tenant_id", "supplier_store_name", "product_id", "variant_id", "token", "secret"},
        )
        approve_reseller.assert_awaited_once_with(
            session=session,
            supplier_tenant_id=7,
            supplier_offer_id=91,
            reseller_tenant_id=88,
            actor_user_id=None,
        )
        self.assertEqual(2, session.commit_count)

    def test_approve_supplier_application_value_error_returns_400_without_secret(self) -> None:
        session = _FakeSession()
        approve_reseller = AsyncMock(side_effect=ValueError("token=plain-secret"))

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["supply:write"]))):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    supply_service.return_value.approve_reseller_application = approve_reseller
                    response = client.post(
                        "/api/v1/tenant/supply/supplier-applications/approve",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"supplier_offer_id": 91, "reseller_tenant_id": 88},
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("代理审批参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertEqual(1, session.commit_count)

    def test_reject_supplier_application_requires_supply_write_before_service(self) -> None:
        api_key = _api_key(scopes=["supply:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    response = client.post(
                        "/api/v1/tenant/supply/supplier-applications/reject",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"supplier_offer_id": 91, "reseller_tenant_id": 88},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        supply_service.assert_not_called()

    def test_reject_supplier_application_is_tenant_scoped_and_redacted(self) -> None:
        session = _FakeSession()
        now = datetime.now(timezone.utc)
        application = ResellerApplicationSummary(
            rule_id=31,
            supplier_offer_id=91,
            supplier_tenant_id=7,
            supplier_store_name="供应商",
            reseller_tenant_id=88,
            reseller_store_name="代理商",
            product_name="供货卡密",
            status="rejected",
            pricing_value=Decimal("9.00"),
            min_sale_price=Decimal("10.00"),
            currency="USDT",
            updated_at=now,
        )
        reject_reseller = AsyncMock(return_value=application)

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["supply:write"]))):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    supply_service.return_value.reject_reseller_application = reject_reseller
                    response = client.post(
                        "/api/v1/tenant/supply/supplier-applications/reject",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"supplier_offer_id": 91, "reseller_tenant_id": 88, "reason": "资料不完整"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("rejected", payload["status"])
        _assert_json_keys_absent(
            self,
            payload,
            {"rule_id", "supplier_tenant_id", "supplier_store_name", "product_id", "variant_id", "token", "secret"},
        )
        reject_reseller.assert_awaited_once_with(
            session=session,
            supplier_tenant_id=7,
            supplier_offer_id=91,
            reseller_tenant_id=88,
            actor_user_id=None,
            reason="资料不完整",
        )
        self.assertEqual(2, session.commit_count)

    def test_reject_supplier_application_value_error_returns_400_without_secret(self) -> None:
        session = _FakeSession()
        reject_reseller = AsyncMock(side_effect=ValueError("api_key=plain-secret"))

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["supply:write"]))):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    supply_service.return_value.reject_reseller_application = reject_reseller
                    response = client.post(
                        "/api/v1/tenant/supply/supplier-applications/reject",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"supplier_offer_id": 91, "reseller_tenant_id": 88},
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("代理拒绝参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertEqual(1, session.commit_count)

    def test_set_supplier_rule_requires_supply_write_before_service(self) -> None:
        api_key = _api_key(scopes=["supply:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    response = client.post(
                        "/api/v1/tenant/supply/supplier-rules",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"supplier_offer_id": 91, "reseller_tenant_id": 88, "pricing_value": "8.50"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        supply_service.assert_not_called()

    def test_set_supplier_rule_rejects_extra_fields_before_service(self) -> None:
        session = _FakeSession()
        forbidden_fields = (
            "tenant_id",
            "supplier_tenant_id",
            "supplier_store_name",
            "product_id",
            "variant_id",
            "rule_id",
            "status",
            "pricing_mode",
            "default_pricing_mode",
            "default_pricing_value",
            "hidden_supplier_allowed",
            "hide_supplier",
            "actor_user_id",
            "supplier_cost",
            "inventory_id",
            "inventory_item_id",
            "content",
            "content_encrypted",
            "credentials",
            "credentials_encrypted",
            "storage_key",
            "token",
            "secret",
            "api_key",
            "password",
            "private_key",
            "raw_payload",
            "raw_request",
            "raw_response",
            "metadata_json",
        )

        for field in forbidden_fields:
            with self.subTest(field=field):
                client = _client(Settings())
                with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
                    with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["supply:write"]))):
                        with patch("app.web.tenant_admin.SupplyService") as supply_service:
                            response = client.post(
                                "/api/v1/tenant/supply/supplier-rules",
                                headers={"X-API-Key": "fk_live_test"},
                                json={
                                    "supplier_offer_id": 91,
                                    "reseller_tenant_id": 88,
                                    "pricing_value": "8.50",
                                    field: "forbidden",
                                },
                            )

                self.assertEqual(422, response.status_code)
                supply_service.assert_not_called()

    def test_set_supplier_rule_rejects_invalid_schema_before_service(self) -> None:
        session = _FakeSession()
        invalid_payloads = (
            {"supplier_offer_id": 0, "reseller_tenant_id": 88, "pricing_value": "8.50"},
            {"supplier_offer_id": 91, "reseller_tenant_id": 0, "pricing_value": "8.50"},
            {"supplier_offer_id": 91, "reseller_tenant_id": 88, "pricing_value": "0"},
            {"supplier_offer_id": 91, "reseller_tenant_id": 88, "pricing_value": "-1"},
            {
                "supplier_offer_id": 91,
                "reseller_tenant_id": 88,
                "pricing_value": "8.50",
                "min_sale_price": "-0.01",
            },
            {"reseller_tenant_id": 88, "pricing_value": "8.50"},
            {"supplier_offer_id": 91, "pricing_value": "8.50"},
            {"supplier_offer_id": 91, "reseller_tenant_id": 88},
            {"supplier_offer_id": 91, "reseller_tenant_id": 88, "pricing_value": "not-a-decimal"},
        )

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                client = _client(Settings())
                with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
                    with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["supply:write"]))):
                        with patch("app.web.tenant_admin.SupplyService") as supply_service:
                            response = client.post(
                                "/api/v1/tenant/supply/supplier-rules",
                                headers={"X-API-Key": "fk_live_test"},
                                json=payload,
                            )

                self.assertEqual(422, response.status_code)
                supply_service.assert_not_called()

    def test_set_supplier_rule_requires_signature_before_service(self) -> None:
        session = _FakeSession()

        client = _client(Settings(tenant_admin_require_signature=True))
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["supply:write"]))):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    response = client.post(
                        "/api/v1/tenant/supply/supplier-rules",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"supplier_offer_id": 91, "reseller_tenant_id": 88, "pricing_value": "8.50"},
                    )

        self.assertEqual(401, response.status_code)
        self.assertEqual("缺少请求签名", response.json()["detail"])
        supply_service.assert_not_called()

    def test_set_supplier_rule_is_tenant_scoped_and_redacted(self) -> None:
        session = _FakeSession()
        now = datetime.now(timezone.utc)
        application = ResellerApplicationSummary(
            rule_id=31,
            supplier_offer_id=91,
            supplier_tenant_id=7,
            supplier_store_name="供应商",
            reseller_tenant_id=88,
            reseller_store_name="代理商",
            product_name="供货卡密",
            status="active",
            pricing_value=Decimal("8.50"),
            min_sale_price=Decimal("10.00"),
            currency="USDT",
            updated_at=now,
        )
        set_rule = AsyncMock(return_value=application)

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["supply:write"]))):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    supply_service.return_value.set_existing_reseller_rule = set_rule
                    response = client.post(
                        "/api/v1/tenant/supply/supplier-rules",
                        headers={"X-API-Key": "fk_live_test"},
                        json={
                            "supplier_offer_id": 91,
                            "reseller_tenant_id": 88,
                            "pricing_value": "8.50",
                            "min_sale_price": "10.00",
                        },
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(
            {
                "supplier_offer_id",
                "reseller_tenant_id",
                "reseller_store_name",
                "product_name",
                "status",
                "pricing_value",
                "min_sale_price",
                "currency",
                "updated_at",
            },
            set(payload),
        )
        self.assertEqual(88, payload["reseller_tenant_id"])
        self.assertEqual("代理商", payload["reseller_store_name"])
        _assert_json_keys_absent(
            self,
            payload,
            {
                "rule_id",
                "tenant_id",
                "supplier_tenant_id",
                "supplier_store_name",
                "product_id",
                "variant_id",
                "pricing_mode",
                "default_pricing_mode",
                "default_pricing_value",
                "hidden_supplier_allowed",
                "hide_supplier",
                "inventory_id",
                "inventory_item_id",
                "storage_key",
                "content",
                "content_encrypted",
                "credentials",
                "credentials_encrypted",
                "token",
                "secret",
                "api_key",
                "password",
                "private_key",
                "raw_payload",
                "raw_request",
                "raw_response",
                "metadata_json",
            },
        )
        set_rule.assert_awaited_once_with(
            session=session,
            supplier_tenant_id=7,
            supplier_offer_id=91,
            reseller_tenant_id=88,
            actor_user_id=None,
            pricing_value=Decimal("8.50"),
            min_sale_price=Decimal("10.00"),
        )
        self.assertEqual(2, session.commit_count)

    def test_set_supplier_rule_value_error_returns_400_without_secret(self) -> None:
        session = _FakeSession()
        set_rule = AsyncMock(side_effect=ValueError("secret=plain-secret"))

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["supply:write"]))):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    supply_service.return_value.set_existing_reseller_rule = set_rule
                    response = client.post(
                        "/api/v1/tenant/supply/supplier-rules",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"supplier_offer_id": 91, "reseller_tenant_id": 88, "pricing_value": "8.50"},
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("代理规则参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertEqual(1, session.commit_count)

    def test_list_supply_market_requires_supply_read_scope_before_service(self) -> None:
        api_key = _api_key(scopes=["products:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    response = client.get(
                        "/api/v1/tenant/supply/market-offers",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        supply_service.assert_not_called()

    def test_reseller_supply_routes_reject_disabled_reseller_feature_before_service(self) -> None:
        cases = (
            ("GET", "/api/v1/tenant/supply/market-offers", None),
            ("GET", "/api/v1/tenant/supply/applications", None),
            ("POST", "/api/v1/tenant/supply/applications", {"supplier_offer_id": 91}),
            ("GET", "/api/v1/tenant/supply/reseller-products", None),
            ("POST", "/api/v1/tenant/supply/reseller-products", {"supplier_offer_id": 91, "sale_price": "13.00"}),
        )

        for method, path, payload in cases:
            with self.subTest(path=path):
                session = _FakeSession(feature_flags={"self_sale": True, "supplier": True, "reseller": False})
                client = _client(Settings())
                with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
                    with patch.object(
                        ApiKeyService,
                        "authenticate",
                        _authenticate(_api_key(tenant_id=7, scopes=["supply:read", "supply:write"])),
                    ):
                        with patch("app.web.tenant_admin.SupplyService") as supply_service:
                            response = client.request(
                                method,
                                path,
                                headers={"X-API-Key": "fk_live_test"},
                                json=payload,
                            )

                self.assertEqual(403, response.status_code)
                self.assertEqual("代理售卖功能已关闭", response.json()["detail"])
                self.assertNotIn("tenant_id", response.text)
                self.assertEqual(1, session.commit_count)
                supply_service.assert_not_called()

    def test_list_supply_market_is_tenant_scoped_and_redacted(self) -> None:
        session = _FakeSession()
        offer = SupplierOfferSummary(
            offer_id=91,
            product_name="供货卡密",
            category="会员",
            delivery_type="card_pool",
            suggested_price=Decimal("12.00"),
            min_sale_price=Decimal("11.00"),
            currency="USDT",
            available_count=8,
            description="公开描述",
            requires_approval=True,
            reseller_rule_status="active",
            supplier_cost=Decimal("9.00"),
            effective_min_sale_price=Decimal("10.00"),
        )
        list_market = AsyncMock(return_value=[offer])

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["supply:read"]))):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    supply_service.return_value.list_market_offers = list_market
                    response = client.get(
                        "/api/v1/tenant/supply/market-offers?limit=50",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual({"offers"}, set(payload))
        self.assertEqual(1, len(payload["offers"]))
        item = payload["offers"][0]
        self.assertEqual(
            {
                "supplier_offer_id",
                "product_name",
                "delivery_type",
                "suggested_price",
                "min_sale_price",
                "currency",
                "available_count",
                "description",
                "requires_approval",
                "reseller_rule_status",
                "can_create_reseller_product",
                "supplier_cost",
                "effective_min_sale_price",
            },
            set(item),
        )
        self.assertEqual(91, item["supplier_offer_id"])
        self.assertTrue(item["can_create_reseller_product"])
        for marker in (
            "supplier_tenant_id",
            "reseller_tenant_id",
            "product_id",
            "variant_id",
            "rule_id",
            "default_pricing_value",
            "hidden_supplier_allowed",
            "inventory_item_id",
            "storage_key",
            "telegram_chat_id",
            "token",
            "secret",
            "api_key",
        ):
            self.assertNotIn(marker, response.text)
        list_market.assert_awaited_once_with(session=session, reseller_tenant_id=7, limit=50)
        self.assertEqual(1, session.commit_count)

    def test_list_reseller_applications_requires_supply_read_scope_before_service(self) -> None:
        api_key = _api_key(scopes=["products:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    response = client.get(
                        "/api/v1/tenant/supply/applications",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        supply_service.assert_not_called()

    def test_list_reseller_applications_is_tenant_scoped_and_redacted(self) -> None:
        session = _FakeSession()
        now = datetime.now(timezone.utc)
        application = ResellerApplicationSummary(
            rule_id=31,
            supplier_offer_id=91,
            supplier_tenant_id=99,
            supplier_store_name="供应商",
            reseller_tenant_id=7,
            reseller_store_name="代理商",
            product_name="供货卡密",
            status="pending",
            pricing_value=Decimal("9.00"),
            min_sale_price=Decimal("10.00"),
            currency="USDT",
            updated_at=now,
        )
        list_applications = AsyncMock(return_value=[application])

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["supply:read"]))):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    supply_service.return_value.list_my_reseller_applications = list_applications
                    response = client.get(
                        "/api/v1/tenant/supply/applications?limit=50",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual({"applications"}, set(payload))
        self.assertEqual(1, len(payload["applications"]))
        item = payload["applications"][0]
        self.assertEqual(
            {"supplier_offer_id", "product_name", "status", "pricing_value", "min_sale_price", "currency", "updated_at"},
            set(item),
        )
        for marker in (
            "rule_id",
            "supplier_tenant_id",
            "supplier_store_name",
            "reseller_tenant_id",
            "reseller_store_name",
            "token",
            "secret",
            "api_key",
        ):
            self.assertNotIn(marker, response.text)
        self.assertNotIn("供应商", response.text)
        self.assertNotIn("代理商", response.text)
        list_applications.assert_awaited_once_with(session=session, reseller_tenant_id=7, limit=50)
        self.assertEqual(1, session.commit_count)

    def test_create_reseller_application_requires_supply_write_before_service(self) -> None:
        api_key = _api_key(scopes=["supply:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    response = client.post(
                        "/api/v1/tenant/supply/applications",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"supplier_offer_id": 91},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        supply_service.assert_not_called()

    def test_create_reseller_application_rejects_extra_fields_before_service(self) -> None:
        session = _FakeSession()

        forbidden_fields = (
            "supplier_tenant_id",
            "reseller_tenant_id",
            "product_id",
            "variant_id",
            "rule_id",
            "pricing_mode",
            "default_pricing_value",
            "hide_supplier",
            "storage_key",
            "token",
            "secret",
            "api_key",
        )
        for field in forbidden_fields:
            with self.subTest(field=field):
                client = _client(Settings())
                with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
                    with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["supply:write"]))):
                        with patch("app.web.tenant_admin.SupplyService") as supply_service:
                            response = client.post(
                                "/api/v1/tenant/supply/applications",
                                headers={"X-API-Key": "fk_live_test"},
                                json={"supplier_offer_id": 91, field: "forbidden"},
                            )

                self.assertEqual(422, response.status_code)
                supply_service.assert_not_called()

    def test_create_reseller_application_is_tenant_scoped_and_redacted(self) -> None:
        session = _FakeSession()
        now = datetime.now(timezone.utc)
        application = ResellerApplicationSummary(
            rule_id=31,
            supplier_offer_id=91,
            supplier_tenant_id=99,
            supplier_store_name="供应商",
            reseller_tenant_id=7,
            reseller_store_name="代理商",
            product_name="供货卡密",
            status="pending",
            pricing_value=Decimal("9.00"),
            min_sale_price=Decimal("10.00"),
            currency="USDT",
            updated_at=now,
        )
        apply_reseller = AsyncMock(return_value=application)

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["supply:write"]))):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    supply_service.return_value.apply_reseller = apply_reseller
                    response = client.post(
                        "/api/v1/tenant/supply/applications",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"supplier_offer_id": 91},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(
            {
                "supplier_offer_id",
                "product_name",
                "status",
                "pricing_value",
                "min_sale_price",
                "currency",
                "updated_at",
            },
            set(payload),
        )
        self.assertEqual(91, payload["supplier_offer_id"])
        self.assertEqual("pending", payload["status"])
        for marker in (
            "rule_id",
            "supplier_tenant_id",
            "supplier_store_name",
            "reseller_tenant_id",
            "reseller_store_name",
            "token",
            "secret",
            "api_key",
        ):
            self.assertNotIn(marker, response.text)
        self.assertNotIn("供应商", response.text)
        self.assertNotIn("代理商", response.text)
        apply_reseller.assert_awaited_once_with(
            session=session,
            reseller_tenant_id=7,
            supplier_offer_id=91,
            requested_by_user_id=None,
        )
        self.assertEqual(2, session.commit_count)

    def test_create_reseller_application_value_error_returns_400_without_secret(self) -> None:
        session = _FakeSession()
        apply_reseller = AsyncMock(side_effect=ValueError("secret=plain-secret"))

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["supply:write"]))):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    supply_service.return_value.apply_reseller = apply_reseller
                    response = client.post(
                        "/api/v1/tenant/supply/applications",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"supplier_offer_id": 91},
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("供货代理申请参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertEqual(1, session.commit_count)

    def test_list_reseller_products_requires_supply_read_scope_before_service(self) -> None:
        api_key = _api_key(scopes=["products:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    response = client.get(
                        "/api/v1/tenant/supply/reseller-products",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        supply_service.assert_not_called()

    def test_list_reseller_products_is_tenant_scoped_and_redacted(self) -> None:
        session = _FakeSession()
        product = ResellerProductSummary(
            reseller_product_id=201,
            supplier_offer_id=91,
            display_name="代理卡密",
            category="会员",
            sort_order=9,
            delivery_type="card_pool",
            sale_price=Decimal("13.00"),
            currency="USDT",
            status="on",
            available_count=8,
        )
        list_products = AsyncMock(return_value=[product])

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["supply:read"]))):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    supply_service.return_value.list_reseller_products = list_products
                    response = client.get(
                        "/api/v1/tenant/supply/reseller-products?limit=50",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual({"products"}, set(payload))
        self.assertEqual(1, len(payload["products"]))
        item = payload["products"][0]
        self.assertEqual(
            {
                "reseller_product_id",
                "supplier_offer_id",
                "display_name",
                "category",
                "sort_order",
                "delivery_type",
                "sale_price",
                "currency",
                "status",
                "available_count",
            },
            set(item),
        )
        self.assertEqual(201, item["reseller_product_id"])
        self.assertEqual("会员", item["category"])
        self.assertEqual(9, item["sort_order"])
        _assert_json_keys_absent(
            self,
            payload,
            {
                "supplier_tenant_id",
                "reseller_tenant_id",
                "product_id",
                "variant_id",
                "hide_supplier",
                "storage_key",
                "token",
                "secret",
                "api_key",
            },
        )
        for marker in ("storage_key", "token", "secret", "api_key"):
            self.assertNotIn(marker, response.text)
        list_products.assert_awaited_once_with(session=session, reseller_tenant_id=7, limit=50)

    def test_create_reseller_product_requires_supply_write_before_service(self) -> None:
        api_key = _api_key(scopes=["supply:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    response = client.post(
                        "/api/v1/tenant/supply/reseller-products",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"supplier_offer_id": 91, "sale_price": "13.00"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        supply_service.assert_not_called()

    def test_create_reseller_product_rejects_extra_fields_before_service(self) -> None:
        session = _FakeSession()

        forbidden_fields = (
            "supplier_tenant_id",
            "reseller_tenant_id",
            "product_id",
            "variant_id",
            "rule_id",
            "pricing_mode",
            "default_pricing_value",
            "hide_supplier",
            "storage_key",
            "token",
            "secret",
            "api_key",
        )
        for field in forbidden_fields:
            with self.subTest(field=field):
                client = _client(Settings())
                with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
                    with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["supply:write"]))):
                        with patch("app.web.tenant_admin.SupplyService") as supply_service:
                            response = client.post(
                                "/api/v1/tenant/supply/reseller-products",
                                headers={"X-API-Key": "fk_live_test"},
                                json={"supplier_offer_id": 91, "sale_price": "13.00", field: "forbidden"},
                            )

                self.assertEqual(422, response.status_code)
                supply_service.assert_not_called()

    def test_create_reseller_product_is_tenant_scoped_and_redacted(self) -> None:
        session = _FakeSession()
        product = CreatedResellerProduct(
            reseller_product_id=201,
            supplier_offer_id=91,
            display_name="代理卡密",
            sale_price=Decimal("13.00"),
            currency="USDT",
            status="on",
        )
        create_product = AsyncMock(return_value=product)

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["supply:write"]))):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    supply_service.return_value.create_reseller_product = create_product
                    response = client.post(
                        "/api/v1/tenant/supply/reseller-products",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"supplier_offer_id": 91, "sale_price": "13.00", "display_name": "代理卡密"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(
            {
                "reseller_product_id",
                "supplier_offer_id",
                "display_name",
                "sale_price",
                "currency",
                "status",
            },
            set(payload),
        )
        self.assertEqual(201, payload["reseller_product_id"])
        self.assertEqual("13.00", payload["sale_price"])
        _assert_json_keys_absent(
            self,
            payload,
            {
                "supplier_tenant_id",
                "reseller_tenant_id",
                "product_id",
                "variant_id",
                "hide_supplier",
                "sort_order",
                "token",
                "secret",
                "api_key",
            },
        )
        for marker in ("token", "secret", "api_key"):
            self.assertNotIn(marker, response.text)
        create_product.assert_awaited_once_with(
            session=session,
            reseller_tenant_id=7,
            supplier_offer_id=91,
            sale_price=Decimal("13.00"),
            display_name="代理卡密",
        )
        self.assertEqual(2, session.commit_count)

    def test_create_reseller_product_value_error_returns_400_without_secret(self) -> None:
        session = _FakeSession()
        create_product = AsyncMock(side_effect=ValueError("token=plain-secret"))

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["supply:write"]))):
                with patch("app.web.tenant_admin.SupplyService") as supply_service:
                    supply_service.return_value.create_reseller_product = create_product
                    response = client.post(
                        "/api/v1/tenant/supply/reseller-products",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"supplier_offer_id": 91, "sale_price": "13.00"},
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("代理商品参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertEqual(1, session.commit_count)

    def test_sync_products_creates_and_updates_products_in_one_transaction(self) -> None:
        session = _FakeSession()
        created_product = _product(
            product_id=21,
            name="外部商品",
            status="on",
            delivery_type="card_pool",
            suggested_price=Decimal("6.60"),
            external_source="acg",
            source_key="main",
            external_id="sku-1",
        )
        updated_product = _product(
            product_id=31,
            name="已更新商品",
            status="on",
            delivery_type="card_fixed",
            suggested_price=Decimal("7.70"),
        )
        get_by_external_ref = AsyncMock(return_value=(None, None))
        create_self_product = AsyncMock(return_value=created_product)
        update_self_product = AsyncMock(return_value=updated_product)
        set_product_status = AsyncMock()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["products:write"]))):
                with patch("app.web.tenant_admin.ProductRepository") as product_repo:
                    product_repo.return_value.get_self_product_by_external_ref = get_by_external_ref
                    product_repo.return_value.create_self_product = create_self_product
                    product_repo.return_value.update_self_product = update_self_product
                    product_repo.return_value.set_product_status = set_product_status
                    response = client.post(
                        "/api/v1/tenant/products/sync",
                        headers={"X-API-Key": "fk_live_test"},
                        json={
                            "products": [
                                {
                                    "external_source": "acg",
                                    "source_key": "main",
                                    "external_id": "sku-1",
                                    "name": "外部商品",
                                    "price": "6.60",
                                    "delivery_type": "card_pool",
                                    "status": "on",
                                },
                                {
                                    "product_id": 31,
                                    "name": "已更新商品",
                                    "price": "7.70",
                                    "delivery_type": "card_fixed",
                                    "status": "on",
                                },
                            ]
                        },
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(1, payload["created_count"])
        self.assertEqual(1, payload["updated_count"])
        self.assertEqual("created", payload["products"][0]["action"])
        self.assertEqual("updated", payload["products"][1]["action"])
        self.assertEqual("acg", payload["products"][0]["external_source"])
        self.assertEqual("main", payload["products"][0]["source_key"])
        self.assertEqual("sku-1", payload["products"][0]["external_id"])
        self.assertEqual("on", payload["products"][0]["status"])
        self.assertEqual(31, payload["products"][1]["product_id"])
        self.assertEqual("on", payload["products"][1]["status"])
        self.assertNotIn("description", response.text)
        self.assertEqual(2, session.commit_count)
        get_by_external_ref.assert_awaited_once_with(
            session,
            tenant_id=7,
            external_source="acg",
            source_key="main",
            external_id="sku-1",
        )
        create_self_product.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            name="外部商品",
            price=Decimal("6.60"),
            delivery_type="card_pool",
            description=None,
            category=None,
            external_source="acg",
            source_key="main",
            external_id="sku-1",
        )
        update_self_product.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            product_id=31,
            name="已更新商品",
            price=Decimal("7.70"),
            description=None,
            category=None,
            status="on",
            delivery_type="card_fixed",
            external_source=None,
            source_key="",
            external_id=None,
        )
        set_product_status.assert_awaited_once_with(session, 7, 21, "on")

    def test_sync_products_updates_existing_external_ref_without_creating(self) -> None:
        session = _FakeSession()
        existing_product = _product(
            product_id=44,
            name="旧外部商品",
            status="draft",
            delivery_type="card_pool",
            suggested_price=Decimal("5.00"),
            external_source="acg",
            source_key="main",
            external_id="sku-2",
        )
        updated_product = _product(
            product_id=44,
            name="新外部商品",
            status="off",
            delivery_type="card_pool",
            suggested_price=Decimal("8.80"),
            external_source="acg",
            source_key="main",
            external_id="sku-2",
        )
        get_by_external_ref = AsyncMock(return_value=(existing_product, None))
        create_self_product = AsyncMock()
        update_self_product = AsyncMock(return_value=updated_product)

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["products:write"]))):
                with patch("app.web.tenant_admin.ProductRepository") as product_repo:
                    product_repo.return_value.get_self_product_by_external_ref = get_by_external_ref
                    product_repo.return_value.create_self_product = create_self_product
                    product_repo.return_value.update_self_product = update_self_product
                    response = client.post(
                        "/api/v1/tenant/products/sync",
                        headers={"X-API-Key": "fk_live_test"},
                        json={
                            "products": [
                                {
                                    "external_source": "acg",
                                    "source_key": "main",
                                    "external_id": "sku-2",
                                    "name": "新外部商品",
                                    "price": "8.80",
                                    "delivery_type": "card_pool",
                                    "status": "off",
                                    "category": "会员",
                                }
                            ]
                        },
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(0, payload["created_count"])
        self.assertEqual(1, payload["updated_count"])
        self.assertEqual(44, payload["products"][0]["product_id"])
        self.assertEqual("updated", payload["products"][0]["action"])
        self.assertEqual("off", payload["products"][0]["status"])
        create_self_product.assert_not_awaited()
        get_by_external_ref.assert_awaited_once_with(
            session,
            tenant_id=7,
            external_source="acg",
            source_key="main",
            external_id="sku-2",
        )
        update_self_product.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            product_id=44,
            name="新外部商品",
            price=Decimal("8.80"),
            description=None,
            category="会员",
            status="off",
            delivery_type="card_pool",
            external_source="acg",
            source_key="main",
            external_id="sku-2",
        )
        self.assertEqual(2, session.commit_count)

    def test_sync_products_value_error_returns_400_without_route_commit(self) -> None:
        session = _FakeSession()
        update_self_product = AsyncMock(side_effect=ValueError("商品不存在"))

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["products:write"]))):
                with patch("app.web.tenant_admin.ProductRepository") as product_repo:
                    product_repo.return_value.update_self_product = update_self_product
                    response = client.post(
                        "/api/v1/tenant/products/sync",
                        headers={"X-API-Key": "fk_live_test"},
                        json={
                            "products": [
                                {
                                    "product_id": 404,
                                    "name": "缺失商品",
                                    "price": "9.90",
                                    "delivery_type": "card_pool",
                                }
                            ]
                        },
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("商品不存在", response.json()["detail"])
        self.assertEqual(1, session.commit_count)
        update_self_product.assert_awaited_once()

    def test_import_inventory_requires_write_scope_before_service(self) -> None:
        api_key = _api_key(scopes=["inventory:read"])
        session = _FakeSession()

        client = _client(_settings_with_crypto())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.ProductRepository") as product_repo:
                    response = client.post(
                        "/api/v1/tenant/products/12/inventory/import",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"items": ["card-a"]},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        product_repo.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_import_inventory_encrypts_items_commits_and_redacts_response(self) -> None:
        session = _FakeSession()
        add_inventory_items = AsyncMock(return_value=(2, 1))

        client = _client(_settings_with_crypto())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["inventory:write"]))):
                with patch("app.web.tenant_admin.ProductRepository") as product_repo:
                    product_repo.return_value.add_inventory_items = add_inventory_items
                    response = client.post(
                        "/api/v1/tenant/products/12/inventory/import",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"items": [" card-a ", "card-b", "card-a"]},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(
            {
                "product_id": 12,
                "added_count": 2,
                "existing_count": 1,
                "input_duplicate_count": 1,
            },
            payload,
        )
        self.assertNotIn("card-a", response.text)
        self.assertNotIn("card-b", response.text)
        self.assertEqual(2, session.commit_count)
        add_inventory_items.assert_awaited_once()
        kwargs = add_inventory_items.await_args.kwargs
        self.assertIs(session, kwargs["session"])
        self.assertEqual(7, kwargs["tenant_id"])
        self.assertEqual(12, kwargs["product_id"])
        encrypted_items = kwargs["encrypted_items"]
        self.assertEqual(2, len(encrypted_items))
        self.assertNotIn("card-a", str(encrypted_items))
        self.assertNotIn("card-b", str(encrypted_items))

    def test_import_inventory_without_crypto_key_returns_503_before_service(self) -> None:
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["inventory:write"]))):
                with patch("app.web.tenant_admin.ProductRepository") as product_repo:
                    response = client.post(
                        "/api/v1/tenant/products/12/inventory/import",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"items": ["card-a"]},
                    )

        self.assertEqual(503, response.status_code)
        self.assertEqual("缺少 TOKEN_ENCRYPTION_KEY，无法处理 Bot Token", response.json()["detail"])
        product_repo.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_import_inventory_value_error_returns_400_without_route_commit(self) -> None:
        session = _FakeSession()
        add_inventory_items = AsyncMock(side_effect=ValueError("商品不存在"))

        client = _client(_settings_with_crypto())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["inventory:write"]))):
                with patch("app.web.tenant_admin.ProductRepository") as product_repo:
                    product_repo.return_value.add_inventory_items = add_inventory_items
                    response = client.post(
                        "/api/v1/tenant/products/12/inventory/import",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"items": ["card-a"]},
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("商品不存在", response.json()["detail"])
        self.assertEqual(1, session.commit_count)
        add_inventory_items.assert_awaited_once()

    def test_inventory_summary_requires_read_scope_before_service(self) -> None:
        api_key = _api_key(scopes=["inventory:write"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.ProductRepository") as product_repo:
                    response = client.get(
                        "/api/v1/tenant/products/12/inventory",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        product_repo.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_inventory_summary_is_tenant_scoped_and_redacted(self) -> None:
        session = _FakeSession()
        product = SimpleNamespace(id=12, tenant_id=7, storage_key="private.zip")
        get_product = AsyncMock(return_value=(product, SimpleNamespace(id=5)))
        inventory_summary = AsyncMock(return_value={12: {"available": 3, "locked": 2, "used": 1}})

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["inventory:read"]))):
                with patch("app.web.tenant_admin.ProductRepository") as product_repo:
                    product_repo.return_value.get_product_with_default_variant = get_product
                    product_repo.return_value.inventory_summary = inventory_summary
                    response = client.get(
                        "/api/v1/tenant/products/12/inventory",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {
                "product_id": 12,
                "available_count": 3,
                "locked_count": 2,
                "used_count": 1,
                "total_count": 6,
            },
            response.json(),
        )
        self.assertNotIn("storage_key", response.text)
        self.assertNotIn("private.zip", response.text)
        self.assertEqual(1, session.commit_count)
        get_product.assert_awaited_once_with(session, tenant_id=7, product_id=12)
        inventory_summary.assert_awaited_once_with(session, 7, 12)

    def test_inventory_summary_returns_404_for_missing_or_cross_tenant_product(self) -> None:
        session = _FakeSession()
        get_product = AsyncMock(return_value=(None, None))

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["inventory:read"]))):
                with patch("app.web.tenant_admin.ProductRepository") as product_repo:
                    product_repo.return_value.get_product_with_default_variant = get_product
                    response = client.get(
                        "/api/v1/tenant/products/12/inventory",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(404, response.status_code)
        self.assertEqual("商品不存在", response.json()["detail"])
        self.assertEqual(1, session.commit_count)
        get_product.assert_awaited_once_with(session, tenant_id=7, product_id=12)
        product_repo.return_value.inventory_summary.assert_not_called()

    def test_list_orders_requires_orders_read_scope_before_query(self) -> None:
        api_key = _api_key(scopes=["products:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                response = client.get("/api/v1/tenant/orders", headers={"X-API-Key": "fk_live_test"})

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        self.assertEqual([], session.executed_queries)

    def test_list_orders_is_scoped_to_authenticated_tenant(self) -> None:
        order = _order(out_trade_no="ORD_TENANT_7", tenant_id=7)
        session = _FakeSession([_Result(values=[order])])

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7))):
                response = client.get("/api/v1/tenant/orders?limit=500", headers={"X-API-Key": "fk_live_test"})

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(1, len(payload))
        self.assertEqual("ORD_TENANT_7", payload[0]["out_trade_no"])
        self.assertEqual("pending", payload[0]["status"])
        self.assertNotIn("locked_inventory_item_id", payload[0])
        self.assertNotIn("payment_provider", payload[0])
        self.assertEqual(1, len(session.executed_queries))
        self.assertIn("orders.tenant_id", str(session.executed_queries[0]))

    def test_order_detail_is_scoped_to_authenticated_tenant(self) -> None:
        order = _order(out_trade_no="ORD_DETAIL", tenant_id=7)
        session = _FakeSession([_Result(scalar=order)])

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7))):
                response = client.get("/api/v1/tenant/orders/ORD_DETAIL", headers={"X-API-Key": "fk_live_test"})

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("ORD_DETAIL", payload["out_trade_no"])
        self.assertEqual("self", payload["source_type"])
        self.assertNotIn("locked_inventory_item_id", payload)
        self.assertEqual(1, len(session.executed_queries))
        query_text = str(session.executed_queries[0])
        self.assertIn("orders.tenant_id", query_text)
        self.assertIn("orders.out_trade_no", query_text)

    def test_order_detail_returns_404_for_cross_tenant_or_missing_order(self) -> None:
        session = _FakeSession([_Result(scalar=None)])

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7))):
                response = client.get("/api/v1/tenant/orders/ORD_OTHER", headers={"X-API-Key": "fk_live_test"})

        self.assertEqual(404, response.status_code)
        self.assertEqual("订单不存在", response.json()["detail"])
        query_text = str(session.executed_queries[0])
        self.assertIn("orders.tenant_id", query_text)
        self.assertIn("orders.out_trade_no", query_text)

    def test_order_diagnostics_requires_orders_read_scope_before_service(self) -> None:
        api_key = _api_key(scopes=["payments:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.OrderDiagnosticsService") as diagnostics_service:
                    response = client.get(
                        "/api/v1/tenant/orders/ORD_DETAIL/diagnostics",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        diagnostics_service.assert_not_called()

    def test_order_diagnostics_returns_safe_tenant_scoped_summary(self) -> None:
        session = _FakeSession()
        get_summary = AsyncMock(return_value=_diagnostics_summary())

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7))):
                with patch("app.web.tenant_admin.OrderDiagnosticsService") as diagnostics_service:
                    diagnostics_service.return_value.get_summary = get_summary
                    response = client.get(
                        "/api/v1/tenant/orders/ORD_DETAIL/diagnostics",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(55, payload["order_id"])
        self.assertEqual("ORD_DETAIL", payload["out_trade_no"])
        self.assertEqual("paid", payload["status"])
        self.assertEqual("tenant_direct", payload["payment_mode"])
        self.assertEqual("token188", payload["payment_provider"])
        self.assertEqual(1, payload["payment_count"])
        self.assertEqual(1, payload["callback_count"])
        self.assertEqual({"processed": 1}, payload["callback_status_counts"])
        self.assertEqual(1, len(payload["payments"]))
        self.assertTrue(payload["payments"][0]["has_payment_url"])
        self.assertEqual(1, len(payload["callbacks"]))
        self.assertEqual("processed", payload["callbacks"][0]["process_status"])
        self.assertEqual("sent", payload["delivery"]["status"])
        self.assertTrue(payload["delivery"]["has_inventory_item"])
        self.assertTrue(payload["external_fulfillment"]["expected"])
        self.assertEqual(
            {
                "expected",
                "attempt_count",
                "latest_attempt_status",
                "latest_attempt_source",
                "latest_attempt_at",
                "latest_failure_stage",
                "latest_failure_category",
                "latest_failure_retryable",
                "latest_upstream_status_code",
                "latest_item_count",
                "latest_delivery_record_linked",
            },
            set(payload["external_fulfillment"]),
        )
        self.assertEqual(1, payload["external_fulfillment"]["attempt_count"])
        self.assertEqual("failed", payload["external_fulfillment"]["latest_attempt_status"])
        self.assertEqual("auto", payload["external_fulfillment"]["latest_attempt_source"])
        self.assertIsNotNone(payload["external_fulfillment"]["latest_attempt_at"])
        self.assertEqual("fetch_delivery", payload["external_fulfillment"]["latest_failure_stage"])
        self.assertEqual("upstream_error", payload["external_fulfillment"]["latest_failure_category"])
        self.assertTrue(payload["external_fulfillment"]["latest_failure_retryable"])
        self.assertEqual(503, payload["external_fulfillment"]["latest_upstream_status_code"])
        self.assertEqual(2, payload["external_fulfillment"]["latest_item_count"])
        self.assertFalse(payload["external_fulfillment"]["latest_delivery_record_linked"])
        for marker in (
            "attempt_id",
            "provider_name",
            "source_key",
            "external_product_id",
            "external_order_id",
            "connection_id",
            "delivery_record_id",
            "failure_reason",
            "failure_fingerprint",
            "raw_payload",
            "items",
            "message",
            "credentials",
            "token",
            "secret",
            "api_key",
        ):
            self.assertNotIn(marker, payload["external_fulfillment"])
        forbidden = (
            '"payment_url"',
            "provider_trade_no",
            "payload_json",
            "payload_hash",
            "raw_payload",
            "secret",
            "api_key",
            "storage_key",
            "inventory_item_id",
            "uploaded_file_id",
            "telegram_chat_id",
            "supplier_tenant_id",
            "supplier_settlement_amount",
            "external_product_id",
            "source_key",
            "connection_id",
            "external_order_id",
        )
        for marker in forbidden:
            self.assertNotIn(marker, response.text)
        get_summary.assert_awaited_once_with(session, tenant_id=7, out_trade_no="ORD_DETAIL")

    def test_order_diagnostics_returns_404_for_cross_tenant_or_missing_order(self) -> None:
        session = _FakeSession()
        get_summary = AsyncMock(return_value=None)

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7))):
                with patch("app.web.tenant_admin.OrderDiagnosticsService") as diagnostics_service:
                    diagnostics_service.return_value.get_summary = get_summary
                    response = client.get(
                        "/api/v1/tenant/orders/ORD_OTHER/diagnostics",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(404, response.status_code)
        self.assertEqual("订单不存在", response.json()["detail"])
        get_summary.assert_awaited_once_with(session, tenant_id=7, out_trade_no="ORD_OTHER")

    def test_order_diagnostics_value_error_returns_400_without_secret(self) -> None:
        session = _FakeSession()
        get_summary = AsyncMock(side_effect=ValueError("secret=plain-secret"))

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7))):
                with patch("app.web.tenant_admin.OrderDiagnosticsService") as diagnostics_service:
                    diagnostics_service.return_value.get_summary = get_summary
                    response = client.get(
                        "/api/v1/tenant/orders/ORD_DETAIL/diagnostics",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("订单查询参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)

    def test_list_audit_logs_requires_audit_logs_read_scope_before_service(self) -> None:
        api_key = _api_key(scopes=["orders:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.AuditLogService") as audit_service:
                    response = client.get(
                        "/api/v1/tenant/audit-logs",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        audit_service.assert_not_called()

    def test_list_audit_logs_returns_safe_tenant_scoped_payload(self) -> None:
        session = _FakeSession()
        now = datetime.now(timezone.utc)
        logs = [
            AuditLogSummary(
                audit_log_id=9,
                tenant_id=7,
                actor_user_id=12,
                actor_telegram_user_id=123456,
                actor_username="owner",
                action="tenant_api_key.created",
                target_type="tenant_api_key",
                target_id="44",
                metadata_json={
                    "name": "worker",
                    "token": "***",
                    "secret_key": "***",
                    "payload_json": "***",
                    "payment_url": "***",
                    "provider_trade_no": "***",
                    "nested": {"plain_key": "***", "safe": "visible"},
                    "items": [{"api_key": "***", "name": "kept"}],
                },
                created_at=now,
            )
        ]
        list_logs = AsyncMock(return_value=logs)
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["audit_logs:read"]))):
                with patch("app.web.tenant_admin.AuditLogService") as audit_service:
                    audit_service.return_value.list_tenant_audit_logs = list_logs
                    audit_service.return_value.safe_metadata_for_tenant_api.return_value = {
                        "name": "worker",
                        "nested": {"safe": "visible"},
                        "items": [{"name": "kept"}],
                    }
                    response = client.get(
                        "/api/v1/tenant/audit-logs?action=tenant_api_key.created&target_type=tenant_api_key&limit=5",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(1, len(payload["audit_logs"]))
        item = payload["audit_logs"][0]
        self.assertEqual(9, item["audit_log_id"])
        self.assertEqual(123456, item["actor_telegram_user_id"])
        self.assertEqual("owner", item["actor_username"])
        self.assertEqual("tenant_api_key.created", item["action"])
        self.assertEqual("tenant_api_key", item["target_type"])
        self.assertEqual("44", item["target_id"])
        self.assertEqual("worker", item["metadata"]["name"])
        self.assertNotIn("tenant_id", item)
        self.assertNotIn("actor_user_id", item)
        self.assertNotIn("metadata_json", item)
        for forbidden_field in (
            "token",
            "secret",
            "secret_key",
            "api_key",
            "password",
            "payload",
            "payload_json",
            "plain_key",
            "payment_url",
            "provider_trade_no",
            "signature",
            "signing_text",
        ):
            self.assertNotIn(f'"{forbidden_field}"', response.text)
        for forbidden_value in ("plain-secret", "raw-token", "raw-key"):
            self.assertNotIn(forbidden_value, response.text)
        list_logs.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            limit=5,
            action="tenant_api_key.created",
            target_type="tenant_api_key",
        )

    def test_list_audit_logs_value_error_returns_400_without_secret(self) -> None:
        session = _FakeSession()
        list_logs = AsyncMock(side_effect=ValueError("secret=plain-secret"))

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["audit_logs:read"]))):
                with patch("app.web.tenant_admin.AuditLogService") as audit_service:
                    audit_service.return_value.list_tenant_audit_logs = list_logs
                    response = client.get(
                        "/api/v1/tenant/audit-logs?action=bad",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("审计日志查询参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)

    def test_list_risk_disputes_requires_risk_read_scope_before_service(self) -> None:
        api_key = _api_key(scopes=["orders:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.RiskControlService") as risk_service:
                    response = client.get(
                        "/api/v1/tenant/risk/disputes",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        risk_service.assert_not_called()

    def test_list_risk_disputes_is_tenant_scoped_and_sanitizes_text(self) -> None:
        session = _FakeSession()
        now = datetime.now(timezone.utc)
        disputes = [
            DisputeSummary(
                dispute_id=31,
                tenant_id=7,
                order_id=44,
                out_trade_no="ORD_RISK",
                buyer_telegram_user_id=123456,
                source_type="self",
                order_status="paid",
                amount=Decimal("12.50"),
                currency="USDT",
                status="reviewing",
                reason=" 买家重复投诉 ",
                resolution="https://pay.example/proof?token=plain-secret",
                created_at=now,
                updated_at=now,
            )
        ]
        list_disputes = AsyncMock(return_value=disputes)
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["risk:read"]))):
                with patch("app.web.tenant_admin.RiskControlService") as risk_service:
                    risk_service.return_value.list_disputes = list_disputes
                    response = client.get(
                        "/api/v1/tenant/risk/disputes?status=all&limit=5",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(1, len(payload["disputes"]))
        item = payload["disputes"][0]
        self.assertEqual(31, item["dispute_id"])
        self.assertEqual("ORD_RISK", item["out_trade_no"])
        self.assertEqual("买家重复投诉", item["reason"])
        self.assertEqual("内容已隐藏", item["resolution"])
        self.assertNotIn("tenant_id", item)
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("token", response.text)
        list_disputes.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            status=None,
            limit=5,
        )

    def test_list_risk_after_sales_is_tenant_scoped_and_omits_refund_id(self) -> None:
        session = _FakeSession()
        now = datetime.now(timezone.utc)
        after_sales = [
            AfterSaleSummary(
                case_id=51,
                tenant_id=7,
                order_id=44,
                out_trade_no="ORD_AFTER",
                buyer_telegram_user_id=123456,
                source_type="reseller",
                order_status="paid",
                amount=Decimal("18.00"),
                currency="USDT",
                case_type="refund",
                status="open",
                requested_amount=Decimal("5.00"),
                refunded_amount=Decimal("0"),
                refund_id=88,
                reason="卡密不可用",
                resolution="authorization bearer plain-secret",
                created_at=now,
                updated_at=now,
            )
        ]
        list_after_sales = AsyncMock(return_value=after_sales)
        client = _client(Settings())

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["risk:read"]))):
                with patch("app.web.tenant_admin.RiskControlService") as risk_service:
                    risk_service.return_value.list_after_sales = list_after_sales
                    response = client.get(
                        "/api/v1/tenant/risk/after-sales?status=open&limit=10",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(1, len(payload["after_sales"]))
        item = payload["after_sales"][0]
        self.assertEqual(51, item["case_id"])
        self.assertEqual("refund", item["case_type"])
        self.assertEqual("5.00", item["requested_amount"])
        self.assertEqual("卡密不可用", item["reason"])
        self.assertEqual("内容已隐藏", item["resolution"])
        self.assertNotIn("tenant_id", item)
        self.assertNotIn("refund_id", item)
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("authorization", response.text)
        list_after_sales.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            status="open",
            limit=10,
        )

    def test_list_risk_cases_value_error_returns_400_without_secret(self) -> None:
        session = _FakeSession()
        list_disputes = AsyncMock(side_effect=ValueError("secret=plain-secret"))

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["risk:read"]))):
                with patch("app.web.tenant_admin.RiskControlService") as risk_service:
                    risk_service.return_value.list_disputes = list_disputes
                    response = client.get(
                        "/api/v1/tenant/risk/disputes?status=open",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("风控查询参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)

    def test_list_report_export_jobs_requires_reports_read_scope_before_service(self) -> None:
        api_key = _api_key(scopes=["orders:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.ReportExportService") as report_service:
                    response = client.get(
                        "/api/v1/tenant/reports/export-jobs",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        report_service.assert_not_called()

    def test_list_report_export_jobs_is_tenant_scoped_and_redacted(self) -> None:
        session = _FakeSession()
        now = datetime.now(timezone.utc)
        jobs = [
            ExportJobSummary(
                export_job_id=71,
                tenant_id=7,
                requested_by_user_id=12,
                report_type="orders",
                scope_type="tenant",
                status="completed",
                filename="orders.csv",
                row_count=23,
                error_message=None,
                expires_at=now + timedelta(hours=1),
                created_at=now,
                started_at=now,
                finished_at=now,
                download_url="https://example.test/exports/download/raw-download-token",
            ),
            ExportJobSummary(
                export_job_id=72,
                tenant_id=7,
                requested_by_user_id=12,
                report_type="payments",
                scope_type="tenant",
                status="failed",
                filename=None,
                row_count=0,
                error_message="storage_key=/exports/tenant_7/private.csv token=plain-secret",
                expires_at=None,
                created_at=now,
                started_at=now,
                finished_at=now,
                download_url=None,
            ),
        ]
        list_jobs = AsyncMock(return_value=jobs)
        settings = Settings()
        client = _client(settings)

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["reports:read"]))):
                with patch("app.web.tenant_admin.ReportExportService") as report_service:
                    report_service.return_value.list_export_jobs = list_jobs
                    response = client.get(
                        "/api/v1/tenant/reports/export-jobs?status=all&report_type=orders&limit=5",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(2, len(payload["export_jobs"]))
        completed = payload["export_jobs"][0]
        failed = payload["export_jobs"][1]
        self.assertEqual(71, completed["export_job_id"])
        self.assertEqual("orders", completed["report_type"])
        self.assertTrue(completed["download_available"])
        self.assertNotIn("tenant_id", completed)
        self.assertNotIn("requested_by_user_id", completed)
        self.assertNotIn("filename", completed)
        self.assertNotIn("download_url", completed)
        self.assertNotIn("download_token", completed)
        self.assertNotIn("storage_key", completed)
        self.assertEqual("报表导出失败", failed["failure_reason"])
        for forbidden in (
            "raw-download-token",
            "plain-secret",
            "storage_key",
            "download_url",
            "download_token",
            "requested_by_user_id",
        ):
            self.assertNotIn(forbidden, response.text)
        list_jobs.assert_awaited_once_with(
            session=session,
            settings=settings,
            tenant_id=7,
            status=None,
            report_type="orders",
            limit=5,
        )

    def test_list_report_export_jobs_value_error_returns_400_without_secret(self) -> None:
        session = _FakeSession()
        list_jobs = AsyncMock(side_effect=ValueError("secret=plain-secret"))

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["reports:read"]))):
                with patch("app.web.tenant_admin.ReportExportService") as report_service:
                    report_service.return_value.list_export_jobs = list_jobs
                    response = client.get(
                        "/api/v1/tenant/reports/export-jobs?status=completed",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("报表任务查询参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)

    def test_create_report_export_job_requires_reports_write_scope_before_service(self) -> None:
        api_key = _api_key(scopes=["reports:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.ReportExportService") as report_service:
                    response = client.post(
                        "/api/v1/tenant/reports/export-jobs",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"report_type": "orders"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        report_service.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_create_report_export_job_rejects_extra_payload_fields_before_service(self) -> None:
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["reports:write"]))):
                with patch("app.web.tenant_admin.ReportExportService") as report_service:
                    response = client.post(
                        "/api/v1/tenant/reports/export-jobs",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"report_type": "orders", "scope_type": "platform"},
                    )

        self.assertEqual(422, response.status_code)
        report_service.assert_not_called()
        self.assertEqual(1, session.commit_count)

    def test_create_report_export_job_is_tenant_scoped_pending_and_redacted(self) -> None:
        session = _FakeSession()
        now = datetime.now(timezone.utc)
        summary = ExportJobSummary(
            export_job_id=81,
            tenant_id=7,
            requested_by_user_id=None,
            report_type="orders",
            scope_type="tenant",
            status="pending",
            filename=None,
            row_count=0,
            error_message=None,
            expires_at=None,
            created_at=now,
            started_at=None,
            finished_at=None,
            download_url=None,
        )
        create_job = AsyncMock(return_value=summary)
        settings = Settings()
        client = _client(settings)

        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["reports:write"]))):
                with patch("app.web.tenant_admin.ReportExportService") as report_service:
                    report_service.return_value.create_export_job = create_job
                    response = client.post(
                        "/api/v1/tenant/reports/export-jobs",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"report_type": "orders"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(81, payload["export_job_id"])
        self.assertEqual("orders", payload["report_type"])
        self.assertEqual("tenant", payload["scope_type"])
        self.assertEqual("pending", payload["status"])
        self.assertEqual(0, payload["row_count"])
        self.assertFalse(payload["download_available"])
        self.assertIsNone(payload["failure_reason"])
        self.assertNotIn("tenant_id", payload)
        self.assertNotIn("requested_by_user_id", payload)
        self.assertNotIn("filename", payload)
        self.assertNotIn("download_url", payload)
        self.assertNotIn("download_token", payload)
        self.assertNotIn("storage_key", payload)
        self.assertNotIn("path", payload)
        create_job.assert_awaited_once_with(
            session=session,
            settings=settings,
            report_type="orders",
            tenant_id=7,
            actor_user_id=None,
            scope_type="tenant",
        )
        self.assertEqual(2, session.commit_count)

    def test_create_report_export_job_value_error_returns_400_without_secret(self) -> None:
        session = _FakeSession()
        create_job = AsyncMock(side_effect=ValueError("token=plain-secret"))

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(tenant_id=7, scopes=["reports:write"]))):
                with patch("app.web.tenant_admin.ReportExportService") as report_service:
                    report_service.return_value.create_export_job = create_job
                    response = client.post(
                        "/api/v1/tenant/reports/export-jobs",
                        headers={"X-API-Key": "fk_live_test"},
                        json={"report_type": "unknown"},
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("报表任务参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertEqual(1, session.commit_count)

    def test_list_external_source_connections_requires_read_scope_before_service(self) -> None:
        api_key = _api_key(scopes=["products:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.ExternalSourceConnectionService") as connection_service:
                    response = client.get(
                        "/api/v1/tenant/external-source-connections",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        connection_service.assert_not_called()

    def test_list_external_source_connections_is_tenant_scoped_and_redacted(self) -> None:
        session = _FakeSession()
        list_connections = AsyncMock(return_value=[_connection_summary()])

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["external_sources:read"]))):
                with patch("app.web.tenant_admin.ExternalSourceConnectionService") as connection_service:
                    connection_service.return_value.list_connections = list_connections
                    response = client.get(
                        "/api/v1/tenant/external-source-connections?provider_name=acg",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(1, len(payload["connections"]))
        item = payload["connections"][0]
        self.assertEqual(12, item["connection_id"])
        self.assertEqual("acg", item["provider_name"])
        self.assertEqual(["sensitive_1"], item["credential_fields"])
        self.assertNotIn("credentials", item)
        self.assertNotIn("credentials_encrypted", item)
        self.assertNotIn("api_key", str(item))
        list_connections.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            provider_name="acg",
        )

    def test_create_external_source_connection_is_tenant_scoped_commits_and_redacts(self) -> None:
        session = _FakeSession()
        create_connection = AsyncMock(return_value=_connection_summary())

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["external_sources:write"]))):
                with patch("app.web.tenant_admin.ExternalSourceConnectionService") as connection_service:
                    connection_service.return_value.create_connection = create_connection
                    response = client.post(
                        "/api/v1/tenant/external-source-connections",
                        headers={"X-API-Key": "fk_live_test"},
                        json={
                            "provider_name": "acg",
                            "source_key": "main",
                            "display_name": "ACG 主连接",
                            "credentials": {"api_key": "plain-secret"},
                        },
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(12, payload["connection_id"])
        self.assertEqual(["sensitive_1"], payload["credential_fields"])
        self.assertNotIn("credentials", payload)
        self.assertNotIn("credentials_encrypted", payload)
        self.assertNotIn("plain-secret", str(payload))
        self.assertEqual(2, session.commit_count)
        create_connection.assert_awaited_once()
        kwargs = create_connection.await_args.kwargs
        self.assertEqual(session, kwargs["session"])
        self.assertEqual(7, kwargs["tenant_id"])
        self.assertEqual("acg", kwargs["provider_name"])
        self.assertEqual("main", kwargs["source_key"])
        self.assertEqual({"api_key": "plain-secret"}, kwargs["credentials"])

    def test_create_external_source_connection_value_error_returns_400_and_redacts(self) -> None:
        session = _FakeSession()
        create_connection = AsyncMock(side_effect=ValueError("凭据字段值必须是字符串"))

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["external_sources:write"]))):
                with patch("app.web.tenant_admin.ExternalSourceConnectionService") as connection_service:
                    connection_service.return_value.create_connection = create_connection
                    response = client.post(
                        "/api/v1/tenant/external-source-connections",
                        headers={"X-API-Key": "fk_live_test"},
                        json={
                            "provider_name": "acg",
                            "source_key": "main",
                            "display_name": "ACG 主连接",
                            "credentials": {"api_key": "plain-secret"},
                        },
                    )

        self.assertEqual(400, response.status_code)
        payload = response.json()
        self.assertEqual("凭据字段值必须是字符串", payload["detail"])
        self.assertNotIn("plain-secret", str(payload))
        self.assertNotIn("credentials", str(payload))
        self.assertNotIn("credentials_encrypted", str(payload))
        self.assertEqual(1, session.commit_count)
        create_connection.assert_awaited_once()

    def test_create_standard_http_external_source_connection_invalid_credentials_returns_400_and_redacts(self) -> None:
        previous_providers = dict(provider_registry._providers)
        provider_registry._providers.clear()
        provider_registry._providers[STANDARD_HTTP_PROVIDER] = create_standard_http_provider()
        session = _FakeSession()

        client = _client(Settings())
        try:
            with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
                with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["external_sources:write"]))):
                    response = client.post(
                        "/api/v1/tenant/external-source-connections",
                        headers={"X-API-Key": "fk_live_test"},
                        json={
                            "provider_name": STANDARD_HTTP_PROVIDER,
                            "source_key": "main",
                            "display_name": "HTTP 上游",
                            "credentials": {
                                "base_url": "https://upstream.example/api",
                                "api_key": "plain-secret",
                                "catalog_path": "catalog?api_key=plain-secret",
                            },
                        },
                    )
        finally:
            provider_registry._providers.clear()
            provider_registry._providers.update(previous_providers)

        self.assertEqual(400, response.status_code)
        self.assertEqual("standard_http 凭据无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("catalog?api_key", response.text)
        self.assertNotIn("credentials_encrypted", response.text)
        self.assertEqual([], session.executed_queries)
        self.assertEqual(1, session.commit_count)

    def test_create_external_source_connection_requires_write_scope_before_service(self) -> None:
        api_key = _api_key(scopes=["external_sources:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.ExternalSourceConnectionService") as connection_service:
                    response = client.post(
                        "/api/v1/tenant/external-source-connections",
                        headers={"X-API-Key": "fk_live_test"},
                        json={
                            "provider_name": "acg",
                            "source_key": "main",
                            "display_name": "ACG 主连接",
                            "credentials": {"api_key": "plain-secret"},
                        },
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        connection_service.assert_not_called()

    def test_get_external_source_connection_requires_read_scope_before_service(self) -> None:
        api_key = _api_key(scopes=["products:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.ExternalSourceConnectionService") as connection_service:
                    response = client.get(
                        "/api/v1/tenant/external-source-connections/12",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        connection_service.assert_not_called()

    def test_get_external_source_connection_is_tenant_scoped_and_redacted(self) -> None:
        session = _FakeSession()
        get_connection = AsyncMock(return_value=_connection_summary())

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["external_sources:read"]))):
                with patch("app.web.tenant_admin.ExternalSourceConnectionService") as connection_service:
                    connection_service.return_value.get_connection = get_connection
                    response = client.get(
                        "/api/v1/tenant/external-source-connections/12",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(12, payload["connection_id"])
        self.assertEqual("acg", payload["provider_name"])
        self.assertEqual("main", payload["source_key"])
        self.assertEqual("active", payload["status"])
        self.assertEqual(["sensitive_1"], payload["credential_fields"])
        self.assertNotIn("credentials", payload)
        self.assertNotIn("credentials_encrypted", payload)
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("api_key", response.text)
        get_connection.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            connection_id=12,
        )

    def test_get_external_source_connection_returns_404_for_missing_or_cross_tenant_connection(self) -> None:
        session = _FakeSession()
        get_connection = AsyncMock(return_value=None)

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["external_sources:read"]))):
                with patch("app.web.tenant_admin.ExternalSourceConnectionService") as connection_service:
                    connection_service.return_value.get_connection = get_connection
                    response = client.get(
                        "/api/v1/tenant/external-source-connections/12",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(404, response.status_code)
        self.assertEqual("外部源连接不存在", response.json()["detail"])
        self.assertNotIn("credentials", response.text)
        self.assertNotIn("plain-secret", response.text)
        get_connection.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            connection_id=12,
        )

    def test_disable_external_source_connection_is_tenant_scoped_and_commits(self) -> None:
        session = _FakeSession()
        disable_connection = AsyncMock(return_value=True)

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["external_sources:write"]))):
                with patch("app.web.tenant_admin.ExternalSourceConnectionService") as connection_service:
                    connection_service.return_value.disable_connection = disable_connection
                    response = client.delete(
                        "/api/v1/tenant/external-source-connections/12",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(200, response.status_code)
        self.assertEqual({"connection_id": 12, "disabled": True}, response.json())
        self.assertEqual(2, session.commit_count)
        disable_connection.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            connection_id=12,
        )

    def test_disable_external_source_connection_requires_write_scope_before_service(self) -> None:
        api_key = _api_key(scopes=["external_sources:read"])
        session = _FakeSession()

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(api_key)):
                with patch("app.web.tenant_admin.ExternalSourceConnectionService") as connection_service:
                    response = client.delete(
                        "/api/v1/tenant/external-source-connections/12",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(403, response.status_code)
        self.assertEqual("API Key 权限不足", response.json()["detail"])
        connection_service.assert_not_called()

    def test_disable_external_source_connection_returns_404_for_missing_or_cross_tenant_connection(self) -> None:
        session = _FakeSession()
        disable_connection = AsyncMock(return_value=False)

        client = _client(Settings())
        with patch("app.web.tenant_admin.get_session_factory", return_value=_session_factory(session)):
            with patch.object(ApiKeyService, "authenticate", _authenticate(_api_key(scopes=["external_sources:write"]))):
                with patch("app.web.tenant_admin.ExternalSourceConnectionService") as connection_service:
                    connection_service.return_value.disable_connection = disable_connection
                    response = client.delete(
                        "/api/v1/tenant/external-source-connections/12",
                        headers={"X-API-Key": "fk_live_test"},
                    )

        self.assertEqual(404, response.status_code)
        self.assertEqual("外部源连接不存在", response.json()["detail"])
        self.assertEqual(2, session.commit_count)
        disable_connection.assert_awaited_once_with(
            session=session,
            tenant_id=7,
            connection_id=12,
        )


def _order(*, out_trade_no: str, tenant_id: int) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        out_trade_no=out_trade_no,
        source_type="self",
        amount=Decimal("10.00"),
        currency="USDT",
        status="pending",
        payment_mode="pending_payment",
        payment_provider="epusdt_gmpay",
        buyer_telegram_user_id=42,
        tenant_id=tenant_id,
        locked_inventory_item_id=123,
        created_at=now,
        expires_at=now + timedelta(minutes=15),
        paid_at=None,
        delivered_at=None,
    )


def _diagnostics_summary() -> OrderDiagnosticsSummary:
    now = datetime.now(timezone.utc)
    return OrderDiagnosticsSummary(
        order_id=55,
        out_trade_no="ORD_DETAIL",
        source_type="self",
        status="paid",
        payment_mode="tenant_direct",
        payment_provider="token188",
        amount=Decimal("10.00"),
        currency="USDT",
        created_at=now,
        expires_at=now + timedelta(minutes=30),
        paid_at=now,
        delivered_at=now,
        payment_count=1,
        callback_count=1,
        callback_status_counts={"processed": 1},
        payments=[
            OrderPaymentDiagnostic(
                payment_id=91,
                provider="token188",
                status="paid",
                amount=Decimal("10.00"),
                currency="USDT",
                has_payment_url=True,
                created_at=now,
                paid_at=now,
            )
        ],
        callbacks=[
            OrderPaymentCallbackDiagnostic(
                callback_id=81,
                provider="token188",
                process_status="processed",
                failure_reason="未失败",
                created_at=now,
                processed_at=now,
            )
        ],
        delivery=OrderDeliveryDiagnostic(
            delivery_record_id=71,
            delivery_type="card_pool",
            status="sent",
            failure_reason=None,
            has_inventory_item=True,
            has_uploaded_file=False,
            has_telegram_chat=False,
            created_at=now,
            updated_at=now,
            sent_at=now,
        ),
        external_fulfillment=OrderExternalFulfillmentDiagnostic(
            expected=True,
            attempt_count=1,
            latest_attempt_status="failed",
            latest_attempt_source="auto",
            latest_attempt_at=now,
            latest_failure_stage="fetch_delivery",
            latest_failure_category="upstream_error",
            latest_failure_retryable=True,
            latest_upstream_status_code=503,
            latest_item_count=2,
            latest_delivery_record_linked=False,
        ),
    )


def _connection_summary() -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        connection_id=12,
        provider_name="acg",
        source_key="main",
        display_name="ACG 主连接",
        status="active",
        credential_fields=["sensitive_1"],
        credentials={"api_key": "plain-secret"},
        credentials_encrypted="encrypted-secret",
        created_at=now,
        last_used_at=None,
    )


if __name__ == "__main__":
    unittest.main()
