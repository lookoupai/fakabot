from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

try:
    from pydantic import SecretStr

    from app.config import Settings
    from app.db.models.tenants import AuditLog, TenantApiKey
    from app.services.api_keys import ApiKeyService
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过 API Key 生命周期测试：{exc.name}") from exc


class _Result:
    def __init__(self, scalar: object | None = None) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self) -> object | None:
        return self._scalar


class _FakeSession:
    def __init__(self, *, execute_scalar: object | None = None, get_result: object | None = None) -> None:
        self.added: list[object] = []
        self.executed_queries: list[object] = []
        self.flush_count = 0
        self.get_calls: list[tuple[type[object], int]] = []
        self._execute_scalar = execute_scalar
        self._get_result = get_result
        self._next_id = 1

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        self.flush_count += 1
        for instance in self.added:
            if getattr(instance, "id", None) is None:
                setattr(instance, "id", self._next_id)
                self._next_id += 1

    async def get(self, model: type[object], key: int) -> object | None:
        self.get_calls.append((model, key))
        return self._get_result

    async def execute(self, query: object) -> _Result:
        self.executed_queries.append(query)
        return _Result(self._execute_scalar)


def _settings() -> Settings:
    return Settings(token_encryption_key=SecretStr("test-api-key-hmac-secret"))


def _tenant_api_key(**overrides: Any) -> TenantApiKey:
    defaults: dict[str, Any] = {
        "tenant_id": 7,
        "name": "worker",
        "key_prefix": "fk_live_pref",
        "key_hash": "hash",
        "status": "active",
        "scopes_json": ["orders:read"],
        "ip_allowlist_json": ["203.0.113.0/24"],
        "created_by_user_id": 1001,
    }
    defaults.update(overrides)
    api_key = TenantApiKey(**defaults)
    api_key.id = overrides.get("id", 12)
    return api_key


class ApiKeyLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_hashes_key_and_never_persists_plain_key(self) -> None:
        service = ApiKeyService(_settings())
        session = _FakeSession()

        with patch("app.services.api_keys.secrets.token_urlsafe", return_value="deterministic-token"):
            created = await service.create_tenant_api_key(
                session=session,
                tenant_id=7,
                name=" worker ",
                created_by_user_id=1001,
                scopes=["orders:read", " api_keys:write ", "orders:read"],
                ip_allowlist=["203.0.113.10", " 198.51.100.0/24 ", "203.0.113.10"],
            )

        rows = [item for item in session.added if isinstance(item, TenantApiKey)]
        audits = [item for item in session.added if isinstance(item, AuditLog)]
        self.assertEqual(1, len(rows))
        self.assertEqual(1, len(audits))

        row = rows[0]
        self.assertEqual("worker", row.name)
        self.assertEqual(7, row.tenant_id)
        self.assertEqual("active", row.status)
        self.assertEqual(["api_keys:write", "orders:read"], row.scopes_json)
        self.assertEqual(["203.0.113.10", "198.51.100.0/24"], row.ip_allowlist_json)
        self.assertEqual(created.plain_key[:12], row.key_prefix)
        self.assertEqual(service._hash_key(created.plain_key), row.key_hash)
        self.assertNotEqual(created.plain_key, row.key_hash)
        self.assertFalse(hasattr(row, "plain_key"))
        self.assertNotIn(created.plain_key, str(row.__dict__))

        self.assertEqual(created.api_key_id, row.id)
        self.assertEqual(created.plain_key, "fk_live_deterministic-token")
        self.assertEqual(created.key_prefix, row.key_prefix)
        self.assertEqual(created.scopes, row.scopes_json)
        self.assertEqual(created.ip_allowlist, row.ip_allowlist_json)

        audit = audits[0]
        self.assertEqual("tenant_api_key.created", audit.action)
        self.assertEqual(str(row.id), audit.target_id)
        self.assertEqual(row.key_prefix, audit.metadata_json["key_prefix"])
        self.assertNotIn("plain_key", audit.metadata_json)
        self.assertNotIn("key_hash", audit.metadata_json)
        self.assertNotIn(created.plain_key, str(audit.metadata_json))

    async def test_authenticate_returns_active_key_and_updates_last_used_at(self) -> None:
        service = ApiKeyService(_settings())
        api_key = _tenant_api_key(last_used_at=None)
        session = _FakeSession(execute_scalar=api_key)

        result = await service.authenticate(session, "  fk_live_raw_secret  ")

        self.assertIs(api_key, result)
        self.assertIsNotNone(api_key.last_used_at)
        self.assertEqual(1, session.flush_count)
        self.assertEqual(1, len(session.executed_queries))
        query_text = str(session.executed_queries[0])
        self.assertIn("tenant_api_keys.key_hash", query_text)
        self.assertIn("tenant_api_keys.status", query_text)
        self.assertIn("tenants.status", query_text)
        self.assertNotIn("fk_live_raw_secret", query_text)

    async def test_authenticate_missing_key_does_not_flush(self) -> None:
        service = ApiKeyService(_settings())
        session = _FakeSession(execute_scalar=None)

        result = await service.authenticate(session, "fk_live_missing")

        self.assertIsNone(result)
        self.assertEqual(0, session.flush_count)

    async def test_revoke_is_tenant_scoped_and_writes_redacted_audit(self) -> None:
        service = ApiKeyService(_settings())
        api_key = _tenant_api_key(id=23, tenant_id=7, status="active")
        session = _FakeSession(get_result=api_key)

        revoked = await service.revoke_tenant_api_key(
            session=session,
            tenant_id=7,
            api_key_id=23,
            revoked_by_user_id=1001,
        )

        self.assertTrue(revoked)
        self.assertEqual("revoked", api_key.status)
        self.assertEqual([(TenantApiKey, 23)], session.get_calls)
        self.assertEqual(1, session.flush_count)
        audits = [item for item in session.added if isinstance(item, AuditLog)]
        self.assertEqual(1, len(audits))
        self.assertEqual("tenant_api_key.revoked", audits[0].action)
        self.assertEqual("fk_live_pref", audits[0].metadata_json["key_prefix"])
        self.assertNotIn("plain_key", audits[0].metadata_json)
        self.assertNotIn("key_hash", audits[0].metadata_json)

    async def test_revoke_rejects_cross_tenant_key_without_audit_or_flush(self) -> None:
        service = ApiKeyService(_settings())
        session = _FakeSession(get_result=_tenant_api_key(id=23, tenant_id=8, status="active"))

        revoked = await service.revoke_tenant_api_key(
            session=session,
            tenant_id=7,
            api_key_id=23,
            revoked_by_user_id=1001,
        )

        self.assertFalse(revoked)
        self.assertEqual([], session.added)
        self.assertEqual(0, session.flush_count)


if __name__ == "__main__":
    unittest.main()
