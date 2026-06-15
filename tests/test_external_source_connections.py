from __future__ import annotations

import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

try:
    from cryptography.fernet import Fernet
    from pydantic import SecretStr

    from app.config import Settings
    from app.services.external_sources.connections import (
        ExternalSourceConnectionService,
        build_credentials_hint,
        normalize_credentials,
        normalize_external_identifier,
    )
    from app.services.external_sources.mcy_shop import MCY_SHOP_PROVIDER, create_mcy_shop_provider
    from app.services.external_sources.standard_http import STANDARD_HTTP_PROVIDER
    from app.services.external_sources.standard_http import create_standard_http_provider
    from app.services.token_crypto import TokenCrypto
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过外部源连接测试：{exc.name}") from exc


class FakeSession:
    def __init__(self, connection: SimpleNamespace | None) -> None:
        self.connection = connection

    async def get(self, model: object, connection_id: int) -> SimpleNamespace | None:
        if self.connection is None or self.connection.id != connection_id:
            return None
        return self.connection

    async def execute(self, query: object) -> "_ScalarResult":
        return _ScalarResult(self.connection)


class _ScalarResult:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object | None:
        return self._value


class CreateConnectionFakeSession:
    def __init__(self, existing: SimpleNamespace | None) -> None:
        self.existing = existing
        self.added: list[object] = []
        self.flush_count = 0

    async def execute(self, query: object) -> _ScalarResult:
        return _ScalarResult(self.existing)

    def add(self, item: object) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        self.flush_count += 1
        for item in self.added:
            if getattr(item, "id", None) is None:
                setattr(item, "id", 1000 + len(self.added))


class _ValidatingProvider:
    provider = "validating"

    def __init__(self) -> None:
        self.validated_credentials: list[dict[str, str]] = []

    def validate_connection_credentials(self, credentials: dict[str, str]) -> None:
        self.validated_credentials.append(dict(credentials))
        if credentials.get("api_key") == "bad-secret":
            raise ValueError("provider 凭据无效")


class ExternalSourceConnectionTest(unittest.TestCase):
    def test_credentials_hint_contains_only_redacted_field_placeholders(self) -> None:
        credentials = normalize_credentials(
            {
                " api_key ": " secret-value ",
                "password": "pass-value",
                "username": "merchant",
            }
        )
        hint = build_credentials_hint(credentials)

        self.assertEqual({"fields": ["sensitive_1", "sensitive_2", "sensitive_3"]}, hint)
        self.assertNotIn("secret-value", str(hint))
        self.assertNotIn("pass-value", str(hint))
        self.assertNotIn("merchant", str(hint))
        self.assertNotIn("api_key", str(hint))
        self.assertNotIn("password", str(hint))
        self.assertNotIn("username", str(hint))

    def test_credentials_reject_empty_keys_and_values(self) -> None:
        for credentials in (None, [], "secret"):
            with self.subTest(credentials=credentials):
                with self.assertRaisesRegex(ValueError, "凭据格式"):
                    normalize_credentials(credentials)
        with self.assertRaises(ValueError):
            normalize_credentials({"": "value"})
        for key in (None, 123):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, "字段名必须是字符串"):
                    normalize_credentials({key: "value"})
        for value in (None, 123, True, [], {}):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "字段值必须是字符串"):
                    normalize_credentials({"api_key": value})
        with self.assertRaisesRegex(ValueError, "字段名重复"):
            normalize_credentials({" api_key ": "one", "api_key": "two"})
        with self.assertRaises(ValueError):
            normalize_credentials({"api_key": " "})
        with self.assertRaises(ValueError):
            normalize_credentials({})

    def test_external_identifier_validation(self) -> None:
        self.assertEqual("acg", normalize_external_identifier(" acg ", "provider_name", allow_empty=False))
        self.assertEqual("", normalize_external_identifier(" ", "source_key", allow_empty=True))
        with self.assertRaises(ValueError):
            normalize_external_identifier("ACG", "provider_name", allow_empty=False)
        for value in (None, 123, []):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "必须是字符串"):
                    normalize_external_identifier(value, "provider_name", allow_empty=False)


class ExternalSourceRuntimeCredentialsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.settings = Settings(token_encryption_key=SecretStr(Fernet.generate_key().decode()))
        self.crypto = TokenCrypto(self.settings)
        self.service = ExternalSourceConnectionService()

    async def test_load_runtime_credentials_decrypts_active_connection(self) -> None:
        encrypted = self.crypto.encrypt_token(
            json.dumps(
                {
                    "api_key": "secret-value",
                    "password": "pass-value",
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        connection = SimpleNamespace(
            id=12,
            tenant_id=7,
            provider_name="demo",
            source_key="main",
            status="active",
            credentials_encrypted=encrypted,
            credentials_hint_json={"fields": ["sensitive_1", "sensitive_2"]},
        )

        runtime = await self.service.load_runtime_credentials(
            FakeSession(connection),
            tenant_id=7,
            connection_id=12,
            settings=self.settings,
        )

        self.assertIsNotNone(runtime)
        assert runtime is not None
        self.assertEqual(12, runtime.connection_id)
        self.assertEqual(7, runtime.tenant_id)
        self.assertEqual("demo", runtime.provider_name)
        self.assertEqual("main", runtime.source_key)
        self.assertEqual(["sensitive_1", "sensitive_2"], runtime.credential_fields)
        self.assertEqual({"api_key": "secret-value", "password": "pass-value"}, runtime.credentials)

        credentials = runtime.credentials
        credentials["api_key"] = "mutated"
        self.assertEqual({"api_key": "secret-value", "password": "pass-value"}, runtime.credentials)

    async def test_runtime_credentials_string_output_is_redacted(self) -> None:
        encrypted = self.crypto.encrypt_token(
            json.dumps({"api_key": "secret-value", "password": "pass-value"}, separators=(",", ":"))
        )
        connection = SimpleNamespace(
            id=12,
            tenant_id=7,
            provider_name="demo",
            source_key="main",
            status="active",
            credentials_encrypted=encrypted,
            credentials_hint_json={"fields": ["sensitive_1", "sensitive_2"]},
        )

        runtime = await self.service.load_runtime_credentials(
            FakeSession(connection),
            tenant_id=7,
            connection_id=12,
            settings=self.settings,
        )

        self.assertIsNotNone(runtime)
        rendered = f"{runtime!r} {runtime!s}"
        self.assertIn("credentials='***'", rendered)
        self.assertNotIn("secret-value", rendered)
        self.assertNotIn("pass-value", rendered)
        self.assertNotIn("api_key", rendered)
        self.assertNotIn("password", rendered)
        self.assertNotIn(encrypted, rendered)

    async def test_load_runtime_credentials_returns_none_for_missing_cross_tenant_or_deleted(self) -> None:
        active = SimpleNamespace(
            id=12,
            tenant_id=7,
            provider_name="demo",
            source_key="main",
            status="active",
            credentials_encrypted=self.crypto.encrypt_token(json.dumps({"api_key": "secret-value"})),
            credentials_hint_json={"fields": ["sensitive_1"]},
        )
        deleted = SimpleNamespace(
            id=13,
            tenant_id=7,
            provider_name="demo",
            source_key="main",
            status="deleted",
            credentials_encrypted=active.credentials_encrypted,
            credentials_hint_json={"fields": ["sensitive_1"]},
        )

        missing = await self.service.load_runtime_credentials(
            FakeSession(None),
            tenant_id=7,
            connection_id=12,
            settings=self.settings,
        )
        cross_tenant = await self.service.load_runtime_credentials(
            FakeSession(active),
            tenant_id=8,
            connection_id=12,
            settings=self.settings,
        )
        deleted_result = await self.service.load_runtime_credentials(
            FakeSession(deleted),
            tenant_id=7,
            connection_id=13,
            settings=self.settings,
        )

        self.assertIsNone(missing)
        self.assertIsNone(cross_tenant)
        self.assertIsNone(deleted_result)

    async def test_load_runtime_credentials_rejects_disabled_connection(self) -> None:
        connection = SimpleNamespace(
            id=12,
            tenant_id=7,
            provider_name="demo",
            source_key="main",
            status="disabled",
            credentials_encrypted=self.crypto.encrypt_token(json.dumps({"api_key": "secret-value"})),
            credentials_hint_json={"fields": ["sensitive_1"]},
        )

        with self.assertRaisesRegex(ValueError, "外部源连接未启用"):
            await self.service.load_runtime_credentials(
                FakeSession(connection),
                tenant_id=7,
                connection_id=12,
                settings=self.settings,
            )

    async def test_load_runtime_credentials_for_source_uses_active_tenant_source_connection(self) -> None:
        encrypted = self.crypto.encrypt_token(json.dumps({"api_key": "secret-value"}))
        connection = SimpleNamespace(
            id=12,
            tenant_id=7,
            provider_name="acg",
            source_key="main",
            status="active",
            credentials_encrypted=encrypted,
            credentials_hint_json={"fields": ["sensitive_1"]},
        )

        runtime = await self.service.load_runtime_credentials_for_source(
            FakeSession(connection),
            tenant_id=7,
            provider_name=" acg ",
            source_key=" main ",
            settings=self.settings,
        )

        self.assertIsNotNone(runtime)
        assert runtime is not None
        self.assertEqual(12, runtime.connection_id)
        self.assertEqual("acg", runtime.provider_name)
        self.assertEqual("main", runtime.source_key)
        self.assertEqual({"api_key": "secret-value"}, runtime.credentials)

    async def test_create_connection_reactivates_deleted_row_instead_of_inserting_duplicate(self) -> None:
        deleted = SimpleNamespace(
            id=12,
            tenant_id=7,
            provider_name="acg",
            source_key="main",
            display_name="旧连接",
            status="deleted",
            credentials_encrypted=self.crypto.encrypt_token(json.dumps({"api_key": "old-secret"})),
            credentials_hint_json={"fields": ["sensitive_1"]},
            created_by_user_id=1,
            created_at=None,
            last_used_at=object(),
        )
        session = CreateConnectionFakeSession(deleted)

        with patch("app.services.external_sources.connections.get_provider", return_value=object()):
            summary = await self.service.create_connection(
                session,
                tenant_id=7,
                provider_name=" acg ",
                source_key=" main ",
                display_name=" 新连接 ",
                credentials={" api_key ": " new-secret "},
                settings=self.settings,
                created_by_user_id=99,
            )

        self.assertEqual(12, summary.connection_id)
        self.assertEqual("acg", summary.provider_name)
        self.assertEqual("main", summary.source_key)
        self.assertEqual("新连接", summary.display_name)
        self.assertEqual("active", summary.status)
        self.assertEqual(["sensitive_1"], summary.credential_fields)
        self.assertEqual("active", deleted.status)
        self.assertEqual("新连接", deleted.display_name)
        self.assertEqual(99, deleted.created_by_user_id)
        self.assertIsNone(deleted.last_used_at)
        self.assertEqual([], session.added)
        self.assertEqual(1, session.flush_count)
        decrypted = json.loads(self.crypto.decrypt_token(deleted.credentials_encrypted))
        self.assertEqual({"api_key": "new-secret"}, decrypted)

    async def test_create_standard_http_connection_validates_and_encrypts_safe_credentials(self) -> None:
        session = CreateConnectionFakeSession(existing=None)
        credentials = {
            " base_url ": " https://upstream.example/api ",
            " api_key ": " provider-secret ",
            " catalog_path ": " v1/products ",
            " product_path ": " v1/products/{external_product_id} ",
            " create_order_path ": " v1/purchase ",
            " query_order_path ": " v1/purchase/{external_order_id} ",
            " delivery_path ": " v1/purchase/{external_order_id}/cards ",
        }

        with patch("app.services.external_sources.connections.get_provider", return_value=create_standard_http_provider()):
            summary = await self.service.create_connection(
                session,
                tenant_id=7,
                provider_name=STANDARD_HTTP_PROVIDER,
                source_key=" shop-a ",
                display_name=" 上游 HTTP ",
                credentials=credentials,
                settings=self.settings,
                created_by_user_id=99,
            )

        self.assertEqual(1001, summary.connection_id)
        self.assertEqual(STANDARD_HTTP_PROVIDER, summary.provider_name)
        self.assertEqual("shop-a", summary.source_key)
        self.assertEqual("上游 HTTP", summary.display_name)
        self.assertEqual("active", summary.status)
        self.assertEqual(1, session.flush_count)
        self.assertEqual(1, len(session.added))
        connection = session.added[0]
        self.assertNotIn("provider-secret", str(connection.credentials_hint_json))
        decrypted = json.loads(self.crypto.decrypt_token(connection.credentials_encrypted))
        self.assertEqual("https://upstream.example/api", decrypted["base_url"])
        self.assertEqual("provider-secret", decrypted["api_key"])
        self.assertEqual("v1/products/{external_product_id}", decrypted["product_path"])

    async def test_create_standard_http_connection_rejects_unsafe_credentials_before_encrypting(self) -> None:
        invalid_credentials = (
            {"base_url": "https://upstream.example/api", "api_key": "provider-secret", "catalog_path": "../catalog"},
            {"base_url": "https://upstream.example/api", "api_key": "provider-secret", "api_key_header": "X-Key"},
            {"base_url": "https://upstream.example/api", "api_key": "provider-secret", "token": "secret-token"},
            {"base_url": "http://127.0.0.1/api", "api_key": "provider-secret"},
            {"base_url": "http://169.254.169.254/latest", "api_key": "provider-secret"},
            {"base_url": "http://localhost/api", "api_key": "provider-secret"},
            {"base_url": "http://service.internal/api", "api_key": "provider-secret"},
            {"base_url": "https://upstream.example/api?token=provider-secret", "api_key": "provider-secret"},
            {"api_key": "provider-secret"},
            {
                "base_url": "https://upstream.example/api",
                "api_key": "provider-secret",
                "query_order_path": "orders",
            },
        )
        for credentials in invalid_credentials:
            with self.subTest(credentials=credentials):
                session = CreateConnectionFakeSession(existing=None)
                with patch("app.services.external_sources.connections.get_provider", return_value=create_standard_http_provider()):
                    with self.assertRaisesRegex(ValueError, "standard_http 凭据无效") as caught:
                        await self.service.create_connection(
                            session,
                            tenant_id=7,
                            provider_name=STANDARD_HTTP_PROVIDER,
                            source_key="shop-a",
                            display_name="上游 HTTP",
                            credentials=credentials,
                            settings=self.settings,
                            created_by_user_id=99,
                        )

                self.assertNotIn("provider-secret", str(caught.exception))
                self.assertEqual([], session.added)
                self.assertEqual(0, session.flush_count)

    async def test_create_mcy_shop_connection_rejects_non_fixture_base_url_before_encrypting(self) -> None:
        invalid_credentials = (
            {"base_url": "https://api.mcy-shop.example.com/fixture", "api_key": "provider-secret"},
            {"base_url": "https://mcy-shop.internal/fixture", "api_key": "provider-secret"},
            {"base_url": "http://8.8.8.8/fixture", "api_key": "provider-secret"},
            {"base_url": "https://localhost.evil.com/fixture", "api_key": "provider-secret"},
            {"base_url": "https://mcy-fixture.test.evil.com/fixture", "api_key": "provider-secret"},
        )
        for credentials in invalid_credentials:
            with self.subTest(credentials=credentials):
                session = CreateConnectionFakeSession(existing=None)
                with patch("app.services.external_sources.connections.get_provider", return_value=create_mcy_shop_provider()):
                    with self.assertRaisesRegex(ValueError, "mcy_shop 凭据无效") as caught:
                        await self.service.create_connection(
                            session,
                            tenant_id=7,
                            provider_name=MCY_SHOP_PROVIDER,
                            source_key="shop-a",
                            display_name="mcy fixture",
                            credentials=credentials,
                            settings=self.settings,
                            created_by_user_id=99,
                        )

                self.assertNotIn("provider-secret", str(caught.exception))
                self.assertEqual([], session.added)
                self.assertEqual(0, session.flush_count)

    async def test_create_connection_uses_provider_validator_without_knowing_specific_provider(self) -> None:
        session = CreateConnectionFakeSession(existing=None)
        provider = _ValidatingProvider()

        with patch("app.services.external_sources.connections.get_provider", return_value=provider):
            summary = await self.service.create_connection(
                session,
                tenant_id=7,
                provider_name="validating",
                source_key="main",
                display_name="校验 provider",
                credentials={" api_key ": " good-secret "},
                settings=self.settings,
                created_by_user_id=99,
            )

        self.assertEqual(1001, summary.connection_id)
        self.assertEqual([{"api_key": "good-secret"}], provider.validated_credentials)
        self.assertEqual(1, session.flush_count)

    async def test_create_connection_provider_validation_error_happens_before_flush(self) -> None:
        session = CreateConnectionFakeSession(existing=None)
        provider = _ValidatingProvider()

        with patch("app.services.external_sources.connections.get_provider", return_value=provider):
            with self.assertRaisesRegex(ValueError, "provider 凭据无效"):
                await self.service.create_connection(
                    session,
                    tenant_id=7,
                    provider_name="validating",
                    source_key="main",
                    display_name="校验 provider",
                    credentials={"api_key": "bad-secret"},
                    settings=self.settings,
                    created_by_user_id=99,
                )

        self.assertEqual([{"api_key": "bad-secret"}], provider.validated_credentials)
        self.assertEqual([], session.added)
        self.assertEqual(0, session.flush_count)


if __name__ == "__main__":
    unittest.main()
