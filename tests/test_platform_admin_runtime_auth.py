from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import logging
import unittest
import warnings
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)
logging.getLogger("httpx").setLevel(logging.WARNING)

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from pydantic import ValidationError

    from app.config import Settings
    from app.services.api_keys import ApiKeyService
    from app.services.audit import PlatformRiskAuditLogSummary
    from app.services.ledger import WithdrawalSummary
    from app.services.risk import PlatformRiskBannedUserSummary, PlatformRiskBanStatusSummary, RiskActionResult
    from app.services.subscriptions import PlatformSubscriptionPlanSummary
    from app.services.supply import PlatformSupplierOfferSummary
    from app.web.platform_admin import create_platform_admin_router
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过 Platform Admin 运行时测试：{exc.name}") from exc


class _FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    async def commit(self) -> None:
        self.commit_count += 1


class _FakeRedis:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, ...]] = []

    async def delete(self, *keys: str) -> int:
        self.deleted.append(tuple(keys))
        return len(keys)


def _session_factory(session: _FakeSession):
    def factory() -> _FakeSession:
        return session

    return factory


def _client(settings: Settings, redis_client: object = None) -> TestClient:
    app = FastAPI()
    app.state.redis = redis_client
    app.include_router(create_platform_admin_router(settings))
    return TestClient(app)


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class PlatformAdminRuntimeAuthTest(unittest.TestCase):
    def test_platform_admin_api_key_scope_config_parses_env_shorthand(self) -> None:
        read_only_hash = _hash_key("pak_env_read_only")
        write_hash = _hash_key("pak_env_write")

        with patch.dict(
            "os.environ",
            {
                "PLATFORM_ADMIN_API_KEY_HASHES": f"{read_only_hash},{write_hash}",
                "PLATFORM_ADMIN_API_KEY_SCOPES": (
                    f"{read_only_hash}=platform_risk:read,platform_finance:read;"
                    f"{write_hash}=platform_supply:write"
                ),
            },
            clear=True,
        ):
            settings = Settings(_env_file=None)

        self.assertEqual({read_only_hash, write_hash}, settings.platform_admin_api_key_hashes)
        self.assertEqual(
            {"platform_risk:read", "platform_finance:read"},
            settings.platform_admin_api_key_scopes[read_only_hash],
        )
        self.assertEqual({"platform_supply:write"}, settings.platform_admin_api_key_scopes[write_hash])

    def test_comma_separated_set_config_parses_from_env(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "PLATFORM_ADMIN_IDS": "1001,1002",
                "TENANT_ADMIN_IP_ALLOWLIST": "10.0.0.0/8,192.0.2.10",
                "PLATFORM_ADMIN_IP_ALLOWLIST": "203.0.113.0/24",
                "TRUSTED_PROXY_IPS": "127.0.0.1,10.0.0.0/8",
                "PUBLIC_STORE_WRITE_IP_ALLOWLIST": "198.51.100.5",
            },
            clear=True,
        ):
            settings = Settings(_env_file=None)

        self.assertEqual({1001, 1002}, settings.platform_admin_ids)
        self.assertEqual({"10.0.0.0/8", "192.0.2.10"}, settings.tenant_admin_ip_allowlist)
        self.assertEqual({"203.0.113.0/24"}, settings.platform_admin_ip_allowlist)
        self.assertEqual({"127.0.0.1", "10.0.0.0/8"}, settings.trusted_proxy_ips)
        self.assertEqual({"198.51.100.5"}, settings.public_store_write_ip_allowlist)

    def test_platform_admin_api_key_scope_config_parses_per_hash_scopes(self) -> None:
        key_hash = _hash_key("pak_read_only")

        settings = Settings(
            platform_admin_api_key_hashes={key_hash},
            platform_admin_api_key_scopes=f"{key_hash}=platform_risk:read,platform_finance:read",
        )

        self.assertEqual(
            {"platform_risk:read", "platform_finance:read"},
            settings.platform_admin_api_key_scopes[key_hash],
        )

    def test_platform_admin_api_key_scope_config_rejects_unknown_or_orphan_scopes(self) -> None:
        key_hash = _hash_key("pak_read_only")
        orphan_hash = _hash_key("pak_orphan")

        with self.assertRaises(ValidationError):
            Settings(
                platform_admin_api_key_hashes={key_hash},
                platform_admin_api_key_scopes={key_hash: {"platform_risk:delete"}},
            )
        with self.assertRaises(ValidationError):
            Settings(
                platform_admin_api_key_hashes={key_hash},
                platform_admin_api_key_scopes={orphan_hash: {"platform_risk:read"}},
            )

    def test_platform_admin_missing_config_fails_closed_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes=set()))

        with patch("app.web.platform_admin.RiskControlService") as service:
            response = client.get(
                "/api/v1/platform/risk/banned-users",
                headers={"X-Platform-API-Key": "pak_live_test"},
            )

        self.assertEqual(503, response.status_code)
        self.assertEqual("Platform Admin API 未启用", response.json()["detail"])
        service.assert_not_called()

    def test_tenant_api_key_cannot_access_platform_risk_observability(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch.object(ApiKeyService, "authenticate", new_callable=AsyncMock) as authenticate:
            with patch("app.web.platform_admin.RiskControlService") as service:
                response = client.get(
                    "/api/v1/platform/risk/banned-users",
                    headers={"X-API-Key": "fk_live_tenant_key"},
                )

        self.assertEqual(401, response.status_code)
        self.assertEqual("缺少 Platform Admin API Key", response.json()["detail"])
        authenticate.assert_not_called()
        service.assert_not_called()

    def test_blank_platform_api_key_is_treated_as_missing_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("")}))

        with patch("app.web.platform_admin.RiskControlService") as service:
            response = client.get(
                "/api/v1/platform/risk/banned-users",
                headers={"X-Platform-API-Key": "   "},
            )

        self.assertEqual(401, response.status_code)
        self.assertEqual("缺少 Platform Admin API Key", response.json()["detail"])
        service.assert_not_called()

    def test_list_banned_users_requires_valid_platform_key_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.RiskControlService") as service:
            response = client.get(
                "/api/v1/platform/risk/banned-users",
                headers={"X-Platform-API-Key": "wrong"},
            )

        self.assertEqual(401, response.status_code)
        self.assertEqual("Platform Admin API Key 无效", response.json()["detail"])
        service.assert_not_called()

    def test_scoped_platform_admin_key_can_read_but_cannot_write(self) -> None:
        key_hash = _hash_key("pak_read_only")
        session = _FakeSession()
        list_banned_platform_users = AsyncMock(return_value=[])
        client = _client(
            Settings(
                platform_admin_api_key_hashes={key_hash},
                platform_admin_api_key_scopes={key_hash: {"platform_risk:read"}},
            )
        )

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.RiskControlService") as service:
                service.return_value.list_banned_platform_users = list_banned_platform_users
                read_response = client.get(
                    "/api/v1/platform/risk/banned-users",
                    headers={"X-Platform-API-Key": "pak_read_only"},
                )

        with patch("app.web.platform_admin.RiskControlService") as service:
            write_response = client.patch(
                "/api/v1/platform/risk/users/123456/ban-status",
                headers={"X-Platform-API-Key": "pak_read_only"},
                json={"status": "banned", "reason": "manual"},
            )

        self.assertEqual(200, read_response.status_code)
        self.assertEqual({"users": []}, read_response.json())
        list_banned_platform_users.assert_awaited_once()
        self.assertEqual(403, write_response.status_code)
        self.assertEqual("Platform Admin API Key 权限不足", write_response.json()["detail"])
        service.assert_not_called()

    def test_platform_admin_key_not_listed_in_scope_map_has_no_implicit_full_access(self) -> None:
        scoped_hash = _hash_key("pak_read_only")
        unlisted_hash = _hash_key("pak_unlisted")
        client = _client(
            Settings(
                platform_admin_api_key_hashes={scoped_hash, unlisted_hash},
                platform_admin_api_key_scopes={scoped_hash: {"platform_risk:read"}},
            )
        )

        with patch("app.web.platform_admin.RiskControlService") as service:
            response = client.get(
                "/api/v1/platform/risk/banned-users",
                headers={"X-Platform-API-Key": "pak_unlisted"},
            )

        self.assertEqual(403, response.status_code)
        self.assertEqual("Platform Admin API Key 权限不足", response.json()["detail"])
        service.assert_not_called()

    def test_list_banned_users_returns_safe_payload_only(self) -> None:
        session = _FakeSession()
        now = datetime(2026, 6, 9, 9, 0, tzinfo=timezone.utc)
        list_banned_platform_users = AsyncMock(
            return_value=[
                PlatformRiskBannedUserSummary(
                    telegram_user_id=123456,
                    username="buyer",
                    is_banned=True,
                    ban_source="auto",
                    latest_action="platform_risk.user_auto_banned",
                    latest_action_at=now,
                    reason="order_creation_risk_repeated_blocks",
                    trigger_rule="recent_order_count",
                    blocked_count=3,
                    threshold=3,
                    window_seconds=3600,
                    created_at=now,
                    updated_at=now,
                )
            ]
        )
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.RiskControlService") as service:
                service.return_value.list_banned_platform_users = list_banned_platform_users
                response = client.get(
                    "/api/v1/platform/risk/banned-users?source=auto&telegram_user_id=123456&limit=500",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual({"users"}, set(payload))
        item = payload["users"][0]
        self.assertEqual(
            {
                "telegram_user_id",
                "username",
                "is_banned",
                "ban_source",
                "latest_action",
                "latest_action_at",
                "reason",
                "trigger_rule",
                "blocked_count",
                "threshold",
                "window_seconds",
                "created_at",
                "updated_at",
            },
            set(item),
        )
        self.assertEqual(123456, item["telegram_user_id"])
        self.assertEqual("auto", item["ban_source"])
        self.assertNotIn("tenant_id", item)
        self.assertNotIn("platform_user_id", item)
        self.assertNotIn("actor_user_id", item)
        self.assertNotIn("audit_log_id", item)
        self.assertNotIn("metadata_json", item)
        list_banned_platform_users.assert_awaited_once_with(
            session,
            source="auto",
            telegram_user_id=123456,
            limit=500,
        )

    def test_list_banned_users_value_error_returns_400_without_secret(self) -> None:
        session = _FakeSession()
        list_banned_platform_users = AsyncMock(side_effect=ValueError("封禁来源无效 token=plain-secret"))
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.RiskControlService") as service:
                service.return_value.list_banned_platform_users = list_banned_platform_users
                response = client.get(
                    "/api/v1/platform/risk/banned-users?source=bad",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                )

        self.assertEqual(400, response.status_code)
        self.assertEqual("平台风控查询参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("token=", response.text)

    def test_get_ban_status_missing_config_fails_closed_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes=set()))

        with patch("app.web.platform_admin.RiskControlService") as service:
            response = client.get(
                "/api/v1/platform/risk/users/123456/ban-status",
                headers={"X-Platform-API-Key": "pak_live_test"},
            )

        self.assertEqual(503, response.status_code)
        self.assertEqual("Platform Admin API 未启用", response.json()["detail"])
        service.assert_not_called()

    def test_get_ban_status_rejects_tenant_api_key_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch.object(ApiKeyService, "authenticate", new_callable=AsyncMock) as authenticate:
            with patch("app.web.platform_admin.RiskControlService") as service:
                response = client.get(
                    "/api/v1/platform/risk/users/123456/ban-status",
                    headers={"X-API-Key": "fk_live_tenant_key"},
                )

        self.assertEqual(401, response.status_code)
        self.assertEqual("缺少 Platform Admin API Key", response.json()["detail"])
        authenticate.assert_not_called()
        service.assert_not_called()

    def test_get_ban_status_requires_valid_platform_key_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.RiskControlService") as service:
            response = client.get(
                "/api/v1/platform/risk/users/123456/ban-status",
                headers={"X-Platform-API-Key": "wrong"},
            )

        self.assertEqual(401, response.status_code)
        self.assertEqual("Platform Admin API Key 无效", response.json()["detail"])
        service.assert_not_called()

    def test_get_ban_status_returns_safe_payload_only(self) -> None:
        session = _FakeSession()
        now = datetime(2026, 6, 9, 9, 0, tzinfo=timezone.utc)
        get_platform_user_ban_status = AsyncMock(
            return_value=PlatformRiskBanStatusSummary(
                telegram_user_id=123456,
                username="buyer",
                is_banned=False,
                ban_source=None,
                latest_action="platform_risk.user_unbanned",
                latest_action_at=now,
                reason="appeal accepted",
                trigger_rule=None,
                blocked_count=None,
                threshold=None,
                window_seconds=None,
                created_at=now,
                updated_at=now,
            )
        )
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.RiskControlService") as service:
                service.return_value.get_platform_user_ban_status = get_platform_user_ban_status
                response = client.get(
                    "/api/v1/platform/risk/users/123456/ban-status",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(
            {
                "telegram_user_id",
                "username",
                "is_banned",
                "ban_source",
                "latest_action",
                "latest_action_at",
                "reason",
                "trigger_rule",
                "blocked_count",
                "threshold",
                "window_seconds",
                "created_at",
                "updated_at",
            },
            set(payload),
        )
        self.assertEqual(123456, payload["telegram_user_id"])
        self.assertFalse(payload["is_banned"])
        self.assertIsNone(payload["ban_source"])
        self.assertEqual("platform_risk.user_unbanned", payload["latest_action"])
        self.assertNotIn("tenant_id", payload)
        self.assertNotIn("platform_user_id", payload)
        self.assertNotIn("actor_user_id", payload)
        self.assertNotIn("audit_log_id", payload)
        self.assertNotIn("metadata_json", payload)
        get_platform_user_ban_status.assert_awaited_once_with(session, telegram_user_id=123456)

    def test_get_ban_status_returns_404_for_missing_platform_user(self) -> None:
        session = _FakeSession()
        get_platform_user_ban_status = AsyncMock(return_value=None)
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.RiskControlService") as service:
                service.return_value.get_platform_user_ban_status = get_platform_user_ban_status
                response = client.get(
                    "/api/v1/platform/risk/users/123456/ban-status",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                )

        self.assertEqual(404, response.status_code)
        self.assertEqual("平台用户不存在", response.json()["detail"])
        get_platform_user_ban_status.assert_awaited_once_with(session, telegram_user_id=123456)

    def test_get_ban_status_value_error_returns_400_without_secret(self) -> None:
        session = _FakeSession()
        get_platform_user_ban_status = AsyncMock(side_effect=ValueError("Telegram 用户 ID 无效 token=plain-secret"))
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.RiskControlService") as service:
                service.return_value.get_platform_user_ban_status = get_platform_user_ban_status
                response = client.get(
                    "/api/v1/platform/risk/users/123456/ban-status",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                )

        self.assertEqual(400, response.status_code)
        self.assertEqual("平台风控查询参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("token=", response.text)

    def test_platform_risk_ban_status_update_rejects_tenant_api_key_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch.object(ApiKeyService, "authenticate", new_callable=AsyncMock) as authenticate:
            with patch("app.web.platform_admin.RiskControlService") as service:
                response = client.patch(
                    "/api/v1/platform/risk/users/123456/ban-status",
                    headers={"X-API-Key": "fk_live_tenant_key"},
                    json={"status": "banned"},
                )

        self.assertEqual(401, response.status_code)
        self.assertEqual("缺少 Platform Admin API Key", response.json()["detail"])
        authenticate.assert_not_called()
        service.assert_not_called()

    def test_platform_risk_ban_status_update_requires_platform_risk_write_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.PLATFORM_ADMIN_SCOPES", {"platform_risk:read"}):
            with patch("app.web.platform_admin.RiskControlService") as service:
                response = client.patch(
                    "/api/v1/platform/risk/users/123456/ban-status",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                    json={"status": "banned"},
                )

        self.assertEqual(403, response.status_code)
        self.assertEqual("Platform Admin API Key 权限不足", response.json()["detail"])
        service.assert_not_called()

    def test_platform_risk_ban_status_update_requires_signature_before_service(self) -> None:
        client = _client(
            Settings(
                platform_admin_api_key_hashes={_hash_key("pak_live_test")},
                platform_admin_require_signature=True,
            )
        )

        with patch("app.web.platform_admin.RiskControlService") as service:
            response = client.patch(
                "/api/v1/platform/risk/users/123456/ban-status",
                headers={"X-Platform-API-Key": "pak_live_test"},
                json={"status": "banned"},
            )

        self.assertEqual(401, response.status_code)
        self.assertEqual("缺少请求签名", response.json()["detail"])
        service.assert_not_called()

    def test_platform_risk_ban_status_update_rejects_extra_fields_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.RiskControlService") as service:
            response = client.patch(
                "/api/v1/platform/risk/users/123456/ban-status",
                headers={"X-Platform-API-Key": "pak_live_test"},
                json={"status": "banned", "tenant_id": 7, "metadata_json": {"token": "plain-secret"}},
            )

        self.assertEqual(422, response.status_code)
        service.assert_not_called()

    def test_platform_risk_ban_status_update_rejects_invalid_status_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.RiskControlService") as service:
            response = client.patch(
                "/api/v1/platform/risk/users/123456/ban-status",
                headers={"X-Platform-API-Key": "pak_live_test"},
                json={"status": "disabled"},
            )

        self.assertEqual(400, response.status_code)
        self.assertEqual("封禁状态必须是 banned 或 active", response.json()["detail"])
        service.assert_not_called()

    def test_platform_risk_ban_status_update_value_error_returns_400_without_secret(self) -> None:
        session = _FakeSession()
        ban_platform_user = AsyncMock(side_effect=ValueError("token=plain-secret"))
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.RiskControlService") as service:
                service.return_value.ban_platform_user = ban_platform_user
                response = client.patch(
                    "/api/v1/platform/risk/users/123456/ban-status",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                    json={"status": "banned"},
                )

        self.assertEqual(400, response.status_code)
        self.assertEqual("平台风控查询参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("token=", response.text)
        self.assertEqual(0, session.commit_count)

    def test_platform_risk_ban_status_update_is_platform_scoped_and_redacted(self) -> None:
        session = _FakeSession()
        now = datetime(2026, 6, 9, 9, 0, tzinfo=timezone.utc)
        ban_platform_user = AsyncMock()
        unban_platform_user = AsyncMock()
        get_platform_user_ban_status = AsyncMock(
            return_value=PlatformRiskBanStatusSummary(
                telegram_user_id=123456,
                username="buyer",
                is_banned=True,
                ban_source="manual",
                latest_action="platform_risk.user_banned",
                latest_action_at=now,
                reason="内容已隐藏",
                trigger_rule=None,
                blocked_count=None,
                threshold=None,
                window_seconds=None,
                created_at=now,
                updated_at=now,
            )
        )
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.RiskControlService") as service:
                service.return_value.ban_platform_user = ban_platform_user
                service.return_value.unban_platform_user = unban_platform_user
                service.return_value.get_platform_user_ban_status = get_platform_user_ban_status
                response = client.patch(
                    "/api/v1/platform/risk/users/123456/ban-status",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                    json={"status": "banned", "reason": "token=plain-secret"},
                )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(
            {
                "telegram_user_id",
                "username",
                "is_banned",
                "ban_source",
                "latest_action",
                "latest_action_at",
                "reason",
                "trigger_rule",
                "blocked_count",
                "threshold",
                "window_seconds",
                "created_at",
                "updated_at",
            },
            set(payload),
        )
        self.assertTrue(payload["is_banned"])
        self.assertEqual("manual", payload["ban_source"])
        for forbidden in (
            "platform_user_id",
            "tenant_id",
            "actor_user_id",
            "audit_log_id",
            "target_id",
            "metadata_json",
            "token",
            "secret",
            "api_key",
            "payload",
            "raw_payload",
        ):
            self.assertNotIn(forbidden, payload)
        self.assertEqual(1, session.commit_count)
        ban_platform_user.assert_awaited_once_with(
            session,
            telegram_user_id=123456,
            actor_user_id=None,
            reason="token=plain-secret",
        )
        unban_platform_user.assert_not_awaited()
        get_platform_user_ban_status.assert_awaited_once_with(session, telegram_user_id=123456)

    def test_platform_risk_ban_status_update_unbans_when_status_active(self) -> None:
        session = _FakeSession()
        now = datetime(2026, 6, 9, 9, 0, tzinfo=timezone.utc)
        ban_platform_user = AsyncMock()
        unban_platform_user = AsyncMock()
        get_platform_user_ban_status = AsyncMock(
            return_value=PlatformRiskBanStatusSummary(
                telegram_user_id=123456,
                username="buyer",
                is_banned=False,
                ban_source=None,
                latest_action="platform_risk.user_unbanned",
                latest_action_at=now,
                reason="appeal",
                trigger_rule=None,
                blocked_count=None,
                threshold=None,
                window_seconds=None,
                created_at=now,
                updated_at=now,
            )
        )
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.RiskControlService") as service:
                service.return_value.ban_platform_user = ban_platform_user
                service.return_value.unban_platform_user = unban_platform_user
                service.return_value.get_platform_user_ban_status = get_platform_user_ban_status
                response = client.patch(
                    "/api/v1/platform/risk/users/123456/ban-status",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                    json={"status": "active", "reason": "appeal"},
                )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertFalse(payload["is_banned"])
        self.assertIsNone(payload["ban_source"])
        self.assertEqual(1, session.commit_count)
        ban_platform_user.assert_not_awaited()
        unban_platform_user.assert_awaited_once_with(
            session,
            telegram_user_id=123456,
            actor_user_id=None,
            reason="appeal",
        )
        get_platform_user_ban_status.assert_awaited_once_with(session, telegram_user_id=123456)

    def test_platform_tenant_suspension_update_rejects_tenant_api_key_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch.object(ApiKeyService, "authenticate", new_callable=AsyncMock) as authenticate:
            with patch("app.web.platform_admin.RiskControlService") as service:
                response = client.patch(
                    "/api/v1/platform/risk/tenants/7/suspension-status",
                    headers={"X-API-Key": "fk_live_tenant_key"},
                    json={"status": "suspended"},
                )

        self.assertEqual(401, response.status_code)
        self.assertEqual("缺少 Platform Admin API Key", response.json()["detail"])
        authenticate.assert_not_called()
        service.assert_not_called()

    def test_platform_tenant_suspension_update_requires_platform_risk_write_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.PLATFORM_ADMIN_SCOPES", {"platform_risk:read"}):
            with patch("app.web.platform_admin.RiskControlService") as service:
                response = client.patch(
                    "/api/v1/platform/risk/tenants/7/suspension-status",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                    json={"status": "suspended"},
                )

        self.assertEqual(403, response.status_code)
        self.assertEqual("Platform Admin API Key 权限不足", response.json()["detail"])
        service.assert_not_called()

    def test_platform_tenant_suspension_update_rejects_extra_fields_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.RiskControlService") as service:
            response = client.patch(
                "/api/v1/platform/risk/tenants/7/suspension-status",
                headers={"X-Platform-API-Key": "pak_live_test"},
                json={"status": "suspended", "actor_user_id": 99, "metadata_json": {"token": "plain-secret"}},
            )

        self.assertEqual(422, response.status_code)
        service.assert_not_called()

    def test_platform_tenant_suspension_update_rejects_invalid_status_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.RiskControlService") as service:
            response = client.patch(
                "/api/v1/platform/risk/tenants/7/suspension-status",
                headers={"X-Platform-API-Key": "pak_live_test"},
                json={"status": "disabled"},
            )

        self.assertEqual(400, response.status_code)
        self.assertEqual("租户冻结状态必须是 suspended 或 active", response.json()["detail"])
        service.assert_not_called()

    def test_platform_tenant_suspension_update_value_error_returns_400_without_secret(self) -> None:
        session = _FakeSession()
        suspend_tenant = AsyncMock(side_effect=ValueError("token=plain-secret"))
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.RiskControlService") as service:
                service.return_value.suspend_tenant = suspend_tenant
                response = client.patch(
                    "/api/v1/platform/risk/tenants/7/suspension-status",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                    json={"status": "suspended"},
                )

        self.assertEqual(400, response.status_code)
        self.assertEqual("平台风控查询参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("token=", response.text)
        self.assertEqual(0, session.commit_count)

    def test_platform_tenant_suspension_update_suspends_and_clears_webhook_cache_without_secret(self) -> None:
        session = _FakeSession()
        redis_client = _FakeRedis()
        suspend_tenant = AsyncMock(
            return_value=RiskActionResult(
                target_type="tenant",
                target_id=7,
                tenant_id=7,
                previous_status="active",
                new_status="suspended",
                reason="内容已隐藏",
                webhook_secrets=("secret-one", "secret-two"),
            )
        )
        resume_tenant = AsyncMock()
        client = _client(
            Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}),
            redis_client=redis_client,
        )

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.RiskControlService") as service:
                service.return_value.suspend_tenant = suspend_tenant
                service.return_value.resume_tenant = resume_tenant
                response = client.patch(
                    "/api/v1/platform/risk/tenants/7/suspension-status",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                    json={"status": "suspended", "reason": "token=plain-secret"},
                )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual({"tenant_id", "previous_status", "status", "reason"}, set(payload))
        self.assertEqual(7, payload["tenant_id"])
        self.assertEqual("active", payload["previous_status"])
        self.assertEqual("suspended", payload["status"])
        self.assertEqual("内容已隐藏", payload["reason"])
        self.assertNotIn("secret-one", response.text)
        self.assertNotIn("secret-two", response.text)
        for forbidden in ("webhook_secret", "metadata_json", "actor_user_id", "token", "secret", "payload", "raw_payload"):
            self.assertNotIn(forbidden, payload)
        self.assertEqual(1, session.commit_count)
        self.assertEqual([("tenant_webhook:secret-one", "tenant_webhook:secret-two")], redis_client.deleted)
        suspend_tenant.assert_awaited_once_with(
            session,
            tenant_id=7,
            actor_user_id=None,
            reason="token=plain-secret",
        )
        resume_tenant.assert_not_awaited()

    def test_platform_tenant_suspension_update_resumes_when_status_active(self) -> None:
        session = _FakeSession()
        suspend_tenant = AsyncMock()
        resume_tenant = AsyncMock(
            return_value=RiskActionResult(
                target_type="tenant",
                target_id=7,
                tenant_id=7,
                previous_status="suspended",
                new_status="grace",
                reason="appeal",
            )
        )
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.RiskControlService") as service:
                service.return_value.suspend_tenant = suspend_tenant
                service.return_value.resume_tenant = resume_tenant
                response = client.patch(
                    "/api/v1/platform/risk/tenants/7/suspension-status",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                    json={"status": "active", "reason": "appeal"},
                )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("suspended", payload["previous_status"])
        self.assertEqual("grace", payload["status"])
        self.assertEqual(1, session.commit_count)
        suspend_tenant.assert_not_awaited()
        resume_tenant.assert_awaited_once_with(
            session,
            tenant_id=7,
            actor_user_id=None,
            reason="appeal",
        )

    def test_list_platform_risk_audit_logs_missing_config_fails_closed_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes=set()))

        with patch("app.web.platform_admin.AuditLogService", create=True) as service:
            response = client.get(
                "/api/v1/platform/risk/audit-logs",
                headers={"X-Platform-API-Key": "pak_live_test"},
            )

        self.assertEqual(503, response.status_code)
        self.assertEqual("Platform Admin API 未启用", response.json()["detail"])
        service.assert_not_called()

    def test_list_platform_risk_audit_logs_rejects_tenant_api_key_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch.object(ApiKeyService, "authenticate", new_callable=AsyncMock) as authenticate:
            with patch("app.web.platform_admin.AuditLogService", create=True) as service:
                response = client.get(
                    "/api/v1/platform/risk/audit-logs",
                    headers={"X-API-Key": "fk_live_tenant_key"},
                )

        self.assertEqual(401, response.status_code)
        self.assertEqual("缺少 Platform Admin API Key", response.json()["detail"])
        authenticate.assert_not_called()
        service.assert_not_called()

    def test_list_platform_risk_audit_logs_requires_valid_platform_key_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.AuditLogService", create=True) as service:
            response = client.get(
                "/api/v1/platform/risk/audit-logs",
                headers={"X-Platform-API-Key": "wrong"},
            )

        self.assertEqual(401, response.status_code)
        self.assertEqual("Platform Admin API Key 无效", response.json()["detail"])
        service.assert_not_called()

    def test_list_platform_risk_audit_logs_returns_safe_payload_only(self) -> None:
        session = _FakeSession()
        now = datetime(2026, 6, 9, 9, 0, tzinfo=timezone.utc)
        list_platform_risk_audit_logs = AsyncMock(
            return_value=[
                PlatformRiskAuditLogSummary(
                    created_at=now,
                    action="platform_risk.user_auto_banned",
                    target_type="platform_user",
                    actor_telegram_user_id=987654,
                    actor_username="platform_admin",
                    target_telegram_user_id=123456,
                    previous_status="active",
                    new_status="banned",
                    reason="order_creation_risk_repeated_blocks",
                    risk_rule="recent_order_count",
                    blocked_count=3,
                    threshold=3,
                    window_seconds=3600,
                )
            ]
        )
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.AuditLogService", create=True) as service:
                service.return_value.list_platform_risk_audit_logs = list_platform_risk_audit_logs
                response = client.get(
                    (
                        "/api/v1/platform/risk/audit-logs"
                        "?action=platform_risk.user_auto_banned&telegram_user_id=123456&limit=5"
                    ),
                    headers={"X-Platform-API-Key": "pak_live_test"},
                )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual({"audit_logs"}, set(payload))
        item = payload["audit_logs"][0]
        self.assertEqual(
            {
                "created_at",
                "action",
                "target_type",
                "actor_telegram_user_id",
                "actor_username",
                "target_telegram_user_id",
                "previous_status",
                "new_status",
                "reason",
                "risk_rule",
                "blocked_count",
                "threshold",
                "window_seconds",
            },
            set(item),
        )
        self.assertEqual("platform_risk.user_auto_banned", item["action"])
        self.assertEqual(987654, item["actor_telegram_user_id"])
        self.assertEqual(123456, item["target_telegram_user_id"])
        for forbidden in (
            "platform_user_id",
            "tenant_id",
            "trigger_tenant_id",
            "actor_user_id",
            "audit_log_id",
            "target_id",
            "metadata_json",
            "raw_metadata",
            "token",
            "secret",
            "api_key",
            "authorization",
            "cookie",
            "password",
            "private_key",
            "payload",
            "payment_url",
            "provider_trade_no",
            "raw_payload",
        ):
            self.assertNotIn(forbidden, item)
        list_platform_risk_audit_logs.assert_awaited_once_with(
            session,
            action="platform_risk.user_auto_banned",
            telegram_user_id=123456,
            limit=5,
        )

    def test_list_platform_risk_audit_logs_value_error_returns_400_without_secret(self) -> None:
        session = _FakeSession()
        list_platform_risk_audit_logs = AsyncMock(side_effect=ValueError("审计 action 无效 token=plain-secret"))
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.AuditLogService", create=True) as service:
                service.return_value.list_platform_risk_audit_logs = list_platform_risk_audit_logs
                response = client.get(
                    "/api/v1/platform/risk/audit-logs?action=bad",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                )

        self.assertEqual(400, response.status_code)
        self.assertEqual("平台风控查询参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("token=", response.text)

    def test_platform_finance_withdrawals_rejects_tenant_api_key_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch.object(ApiKeyService, "authenticate", new_callable=AsyncMock) as authenticate:
            with patch("app.web.platform_admin.LedgerService") as service:
                response = client.get(
                    "/api/v1/platform/finance/withdrawals",
                    headers={"X-API-Key": "fk_live_tenant_key"},
                )

        self.assertEqual(401, response.status_code)
        self.assertEqual("缺少 Platform Admin API Key", response.json()["detail"])
        authenticate.assert_not_called()
        service.assert_not_called()

    def test_platform_finance_withdrawals_missing_config_fails_closed_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes=set()))

        with patch("app.web.platform_admin.LedgerService") as service:
            response = client.get(
                "/api/v1/platform/finance/withdrawals",
                headers={"X-Platform-API-Key": "pak_live_test"},
            )

        self.assertEqual(503, response.status_code)
        self.assertEqual("Platform Admin API 未启用", response.json()["detail"])
        service.assert_not_called()

    def test_platform_finance_withdrawals_requires_valid_platform_key_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.LedgerService") as service:
            response = client.get(
                "/api/v1/platform/finance/withdrawals",
                headers={"X-Platform-API-Key": "wrong"},
            )

        self.assertEqual(401, response.status_code)
        self.assertEqual("Platform Admin API Key 无效", response.json()["detail"])
        service.assert_not_called()

    def test_platform_finance_withdrawals_requires_platform_finance_read_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))
        required_scope = "platform_finance:read"
        scopes_without_finance = {"platform_risk:read"}
        self.assertNotIn(required_scope, scopes_without_finance)

        with patch("app.web.platform_admin.PLATFORM_ADMIN_SCOPES", scopes_without_finance):
            with patch("app.web.platform_admin.LedgerService") as service:
                response = client.get(
                    "/api/v1/platform/finance/withdrawals",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                )

        self.assertEqual(403, response.status_code)
        self.assertEqual("Platform Admin API Key 权限不足", response.json()["detail"])
        service.assert_not_called()

    def test_platform_finance_withdrawals_requires_signature_before_service(self) -> None:
        client = _client(
            Settings(
                platform_admin_api_key_hashes={_hash_key("pak_live_test")},
                platform_admin_require_signature=True,
            )
        )

        with patch("app.web.platform_admin.LedgerService") as service:
            response = client.get(
                "/api/v1/platform/finance/withdrawals",
                headers={"X-Platform-API-Key": "pak_live_test"},
            )

        self.assertEqual(401, response.status_code)
        self.assertEqual("缺少请求签名", response.json()["detail"])
        service.assert_not_called()

    def test_platform_finance_withdrawals_value_error_returns_400_without_secret(self) -> None:
        session = _FakeSession()
        list_pending_withdrawals = AsyncMock(side_effect=ValueError("提现参数包含 token=plain-secret"))
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.LedgerService") as service:
                service.return_value.list_pending_withdrawals = list_pending_withdrawals
                response = client.get(
                    "/api/v1/platform/finance/withdrawals",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                )

        self.assertEqual(400, response.status_code)
        self.assertEqual("平台财务查询参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("token=", response.text)

    def test_platform_finance_withdrawals_returns_pending_masked_payload_only(self) -> None:
        session = _FakeSession()
        raw_address = "T1234567890abcdef"
        list_pending_withdrawals = AsyncMock(
            return_value=[
                WithdrawalSummary(
                    withdrawal_id=11,
                    tenant_id=7,
                    amount=Decimal("9.00000000"),
                    currency="USDT",
                    network="TRC20",
                    address=raw_address,
                    status="pending",
                    requested_at=datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc),
                    payout_reference="PAYOUT-SHOULD-NOT-LEAK",
                    payout_proof_url="https://proof.example/secret",
                    reviewed_at=datetime(2026, 6, 8, 13, 0, tzinfo=timezone.utc),
                    completed_at=datetime(2026, 6, 8, 13, 30, tzinfo=timezone.utc),
                )
            ]
        )
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.LedgerService") as service:
                service.return_value.list_pending_withdrawals = list_pending_withdrawals
                response = client.get(
                    "/api/v1/platform/finance/withdrawals?limit=500",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual({"withdrawals"}, set(payload))
        item = payload["withdrawals"][0]
        self.assertEqual(
            {
                "withdrawal_id",
                "tenant_id",
                "amount",
                "currency",
                "network",
                "address_masked",
                "status",
                "requested_at",
            },
            set(item),
        )
        self.assertEqual(11, item["withdrawal_id"])
        self.assertEqual(7, item["tenant_id"])
        self.assertEqual("9.00000000", item["amount"])
        self.assertEqual("USDT", item["currency"])
        self.assertEqual("TRC20", item["network"])
        self.assertEqual("T12345***abcdef", item["address_masked"])
        self.assertEqual("pending", item["status"])
        self.assertNotIn("address", item)
        self.assertNotIn("admin_note", item)
        self.assertNotIn("payout_reference", item)
        self.assertNotIn("payout_proof_url", item)
        self.assertNotIn("reviewed_at", item)
        self.assertNotIn("completed_at", item)
        self.assertNotIn(raw_address, response.text)
        self.assertNotIn("PAYOUT-SHOULD-NOT-LEAK", response.text)
        self.assertNotIn("proof.example", response.text)
        list_pending_withdrawals.assert_awaited_once_with(session, limit=100)

    def test_platform_finance_withdrawal_detail_rejects_tenant_api_key_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch.object(ApiKeyService, "authenticate", new_callable=AsyncMock) as authenticate:
            with patch("app.web.platform_admin.LedgerService") as service:
                response = client.get(
                    "/api/v1/platform/finance/withdrawals/11",
                    headers={"X-API-Key": "fk_live_tenant_key"},
                )

        self.assertEqual(401, response.status_code)
        self.assertEqual("缺少 Platform Admin API Key", response.json()["detail"])
        authenticate.assert_not_called()
        service.assert_not_called()

    def test_platform_finance_withdrawal_detail_missing_config_fails_closed_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes=set()))

        with patch("app.web.platform_admin.LedgerService") as service:
            response = client.get(
                "/api/v1/platform/finance/withdrawals/11",
                headers={"X-Platform-API-Key": "pak_live_test"},
            )

        self.assertEqual(503, response.status_code)
        self.assertEqual("Platform Admin API 未启用", response.json()["detail"])
        service.assert_not_called()

    def test_platform_finance_withdrawal_detail_requires_valid_platform_key_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.LedgerService") as service:
            response = client.get(
                "/api/v1/platform/finance/withdrawals/11",
                headers={"X-Platform-API-Key": "wrong"},
            )

        self.assertEqual(401, response.status_code)
        self.assertEqual("Platform Admin API Key 无效", response.json()["detail"])
        service.assert_not_called()

    def test_platform_finance_withdrawal_detail_requires_platform_finance_read_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))
        required_scope = "platform_finance:read"
        scopes_without_finance = {"platform_risk:read"}
        self.assertNotIn(required_scope, scopes_without_finance)

        with patch("app.web.platform_admin.PLATFORM_ADMIN_SCOPES", scopes_without_finance):
            with patch("app.web.platform_admin.LedgerService") as service:
                response = client.get(
                    "/api/v1/platform/finance/withdrawals/11",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                )

        self.assertEqual(403, response.status_code)
        self.assertEqual("Platform Admin API Key 权限不足", response.json()["detail"])
        service.assert_not_called()

    def test_platform_finance_withdrawal_detail_requires_signature_before_service(self) -> None:
        client = _client(
            Settings(
                platform_admin_api_key_hashes={_hash_key("pak_live_test")},
                platform_admin_require_signature=True,
            )
        )

        with patch("app.web.platform_admin.LedgerService") as service:
            response = client.get(
                "/api/v1/platform/finance/withdrawals/11",
                headers={"X-Platform-API-Key": "pak_live_test"},
            )

        self.assertEqual(401, response.status_code)
        self.assertEqual("缺少请求签名", response.json()["detail"])
        service.assert_not_called()

    def test_platform_finance_withdrawal_detail_returns_404_when_missing(self) -> None:
        session = _FakeSession()
        get_platform_withdrawal = AsyncMock(return_value=None)
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.LedgerService") as service:
                service.return_value.get_platform_withdrawal = get_platform_withdrawal
                response = client.get(
                    "/api/v1/platform/finance/withdrawals/404",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                )

        self.assertEqual(404, response.status_code)
        self.assertEqual("提现申请不存在", response.json()["detail"])
        get_platform_withdrawal.assert_awaited_once_with(session, withdrawal_id=404)

    def test_platform_finance_withdrawal_detail_value_error_returns_400_without_secret(self) -> None:
        session = _FakeSession()
        get_platform_withdrawal = AsyncMock(side_effect=ValueError("提现参数包含 token=plain-secret"))
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.LedgerService") as service:
                service.return_value.get_platform_withdrawal = get_platform_withdrawal
                response = client.get(
                    "/api/v1/platform/finance/withdrawals/11",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                )

        self.assertEqual(400, response.status_code)
        self.assertEqual("平台财务查询参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("token=", response.text)

    def test_platform_finance_withdrawal_detail_returns_masked_payload_only(self) -> None:
        session = _FakeSession()
        raw_address = "T1234567890abcdef"
        get_platform_withdrawal = AsyncMock(
            return_value=WithdrawalSummary(
                withdrawal_id=11,
                tenant_id=7,
                amount=Decimal("9.00000000"),
                currency="USDT",
                network="TRC20",
                address=raw_address,
                status="completed",
                requested_at=datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc),
                payout_reference="PAYOUT-SHOULD-NOT-LEAK",
                payout_proof_url="https://proof.example/secret",
                reviewed_at=datetime(2026, 6, 8, 13, 0, tzinfo=timezone.utc),
                completed_at=datetime(2026, 6, 8, 13, 30, tzinfo=timezone.utc),
            )
        )
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.LedgerService") as service:
                service.return_value.get_platform_withdrawal = get_platform_withdrawal
                response = client.get(
                    "/api/v1/platform/finance/withdrawals/11",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                )

        self.assertEqual(200, response.status_code)
        item = response.json()
        self.assertEqual(
            {
                "withdrawal_id",
                "tenant_id",
                "amount",
                "currency",
                "network",
                "address_masked",
                "status",
                "requested_at",
                "reviewed_at",
                "completed_at",
            },
            set(item),
        )
        self.assertEqual(11, item["withdrawal_id"])
        self.assertEqual(7, item["tenant_id"])
        self.assertEqual("9.00000000", item["amount"])
        self.assertEqual("USDT", item["currency"])
        self.assertEqual("TRC20", item["network"])
        self.assertEqual("T12345***abcdef", item["address_masked"])
        self.assertEqual("completed", item["status"])
        self.assertEqual("2026-06-08T13:00:00+00:00", item["reviewed_at"])
        self.assertEqual("2026-06-08T13:30:00+00:00", item["completed_at"])
        self.assertNotIn("address", item)
        self.assertNotIn("admin_note", item)
        self.assertNotIn("payout_reference", item)
        self.assertNotIn("payout_proof_url", item)
        self.assertNotIn(raw_address, response.text)
        self.assertNotIn("PAYOUT-SHOULD-NOT-LEAK", response.text)
        self.assertNotIn("proof.example", response.text)
        get_platform_withdrawal.assert_awaited_once_with(session, withdrawal_id=11)

    def test_platform_finance_withdrawal_complete_rejects_tenant_api_key_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch.object(ApiKeyService, "authenticate", new_callable=AsyncMock) as authenticate:
            with patch("app.web.platform_admin.LedgerService") as service:
                response = client.post(
                    "/api/v1/platform/finance/withdrawals/11/complete",
                    headers={"X-API-Key": "fk_live_tenant_key"},
                    json={"admin_note": "paid offline"},
                )

        self.assertEqual(401, response.status_code)
        self.assertEqual("缺少 Platform Admin API Key", response.json()["detail"])
        authenticate.assert_not_called()
        service.assert_not_called()

    def test_platform_finance_withdrawal_complete_missing_config_fails_closed_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes=set()))

        with patch("app.web.platform_admin.LedgerService") as service:
            response = client.post(
                "/api/v1/platform/finance/withdrawals/11/complete",
                headers={"X-Platform-API-Key": "pak_live_test"},
                json={"admin_note": "paid offline"},
            )

        self.assertEqual(503, response.status_code)
        self.assertEqual("Platform Admin API 未启用", response.json()["detail"])
        service.assert_not_called()

    def test_platform_finance_withdrawal_complete_requires_valid_platform_key_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.LedgerService") as service:
            response = client.post(
                "/api/v1/platform/finance/withdrawals/11/complete",
                headers={"X-Platform-API-Key": "wrong"},
                json={"admin_note": "paid offline"},
            )

        self.assertEqual(401, response.status_code)
        self.assertEqual("Platform Admin API Key 无效", response.json()["detail"])
        service.assert_not_called()

    def test_platform_finance_withdrawal_complete_requires_platform_finance_write_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))
        required_scope = "platform_finance:write"
        scopes_without_write = {"platform_finance:read"}
        self.assertNotIn(required_scope, scopes_without_write)

        with patch("app.web.platform_admin.PLATFORM_ADMIN_SCOPES", scopes_without_write):
            with patch("app.web.platform_admin.LedgerService") as service:
                response = client.post(
                    "/api/v1/platform/finance/withdrawals/11/complete",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                    json={"admin_note": "paid offline"},
                )

        self.assertEqual(403, response.status_code)
        self.assertEqual("Platform Admin API Key 权限不足", response.json()["detail"])
        service.assert_not_called()

    def test_platform_finance_withdrawal_complete_requires_signature_before_service(self) -> None:
        client = _client(
            Settings(
                platform_admin_api_key_hashes={_hash_key("pak_live_test")},
                platform_admin_require_signature=True,
            )
        )

        with patch("app.web.platform_admin.LedgerService") as service:
            response = client.post(
                "/api/v1/platform/finance/withdrawals/11/complete",
                headers={"X-Platform-API-Key": "pak_live_test"},
                json={"admin_note": "paid offline"},
            )

        self.assertEqual(401, response.status_code)
        self.assertEqual("缺少请求签名", response.json()["detail"])
        service.assert_not_called()

    def test_platform_finance_withdrawal_complete_returns_masked_payload_only(self) -> None:
        session = _FakeSession()
        raw_address = "T1234567890abcdef"
        withdrawal = SimpleNamespace(
            id=11,
            tenant_id=7,
            amount=Decimal("9.00000000"),
            currency="USDT",
            network="TRC20",
            address=raw_address,
            status="completed",
            requested_at=datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc),
            payout_reference="PAYOUT-SHOULD-NOT-LEAK",
            payout_proof_url="https://proof.example/secret",
            reviewed_at=datetime(2026, 6, 8, 13, 0, tzinfo=timezone.utc),
            completed_at=datetime(2026, 6, 8, 13, 30, tzinfo=timezone.utc),
        )
        complete_withdrawal = AsyncMock(return_value=withdrawal)
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.LedgerService") as service:
                service.return_value.complete_withdrawal = complete_withdrawal
                response = client.post(
                    "/api/v1/platform/finance/withdrawals/11/complete",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                    json={
                        "admin_note": "paid offline",
                        "payout_reference": "txid:abc",
                        "payout_proof_url": "https://proof.example/public",
                    },
                )

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, session.commit_count)
        item = response.json()
        self.assertEqual(
            {
                "withdrawal_id",
                "tenant_id",
                "amount",
                "currency",
                "network",
                "address_masked",
                "status",
                "requested_at",
                "reviewed_at",
                "completed_at",
            },
            set(item),
        )
        self.assertEqual("completed", item["status"])
        self.assertEqual("T12345***abcdef", item["address_masked"])
        self.assertNotIn("address", item)
        self.assertNotIn("admin_note", item)
        self.assertNotIn("payout_reference", item)
        self.assertNotIn("payout_proof_url", item)
        self.assertNotIn(raw_address, response.text)
        self.assertNotIn("PAYOUT-SHOULD-NOT-LEAK", response.text)
        self.assertNotIn("proof.example", response.text)
        complete_withdrawal.assert_awaited_once_with(
            session,
            11,
            "paid offline",
            actor_user_id=None,
            payout_reference="txid:abc",
            payout_proof_url="https://proof.example/public",
        )

    def test_platform_finance_withdrawal_complete_value_error_returns_400_without_secret(self) -> None:
        session = _FakeSession()
        complete_withdrawal = AsyncMock(side_effect=ValueError("冻结余额不足 token=plain-secret"))
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.LedgerService") as service:
                service.return_value.complete_withdrawal = complete_withdrawal
                response = client.post(
                    "/api/v1/platform/finance/withdrawals/11/complete",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                    json={"admin_note": "paid offline"},
                )

        self.assertEqual(400, response.status_code)
        self.assertEqual("平台财务操作参数无效", response.json()["detail"])
        self.assertEqual(0, session.commit_count)
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("token=", response.text)

    def test_platform_finance_withdrawal_reject_requires_platform_finance_write_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))
        scopes_without_write = {"platform_finance:read"}

        with patch("app.web.platform_admin.PLATFORM_ADMIN_SCOPES", scopes_without_write):
            with patch("app.web.platform_admin.LedgerService") as service:
                response = client.post(
                    "/api/v1/platform/finance/withdrawals/11/reject",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                    json={"admin_note": "invalid request"},
                )

        self.assertEqual(403, response.status_code)
        self.assertEqual("Platform Admin API Key 权限不足", response.json()["detail"])
        service.assert_not_called()

    def test_platform_finance_withdrawal_reject_rejects_extra_payout_fields_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.LedgerService") as service:
            response = client.post(
                "/api/v1/platform/finance/withdrawals/11/reject",
                headers={"X-Platform-API-Key": "pak_live_test"},
                json={"admin_note": "invalid request", "payout_reference": "must-not-be-accepted"},
            )

        self.assertEqual(422, response.status_code)
        service.assert_not_called()

    def test_platform_finance_withdrawal_reject_returns_masked_payload_only(self) -> None:
        session = _FakeSession()
        raw_address = "T1234567890abcdef"
        withdrawal = SimpleNamespace(
            id=11,
            tenant_id=7,
            amount=Decimal("9.00000000"),
            currency="USDT",
            network="TRC20",
            address=raw_address,
            status="rejected",
            requested_at=datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc),
            payout_reference=None,
            payout_proof_url=None,
            reviewed_at=datetime(2026, 6, 8, 13, 0, tzinfo=timezone.utc),
            completed_at=None,
        )
        reject_withdrawal = AsyncMock(return_value=withdrawal)
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.LedgerService") as service:
                service.return_value.reject_withdrawal = reject_withdrawal
                response = client.post(
                    "/api/v1/platform/finance/withdrawals/11/reject",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                    json={"admin_note": "invalid request"},
                )

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, session.commit_count)
        item = response.json()
        self.assertEqual("rejected", item["status"])
        self.assertEqual("T12345***abcdef", item["address_masked"])
        self.assertNotIn("address", item)
        self.assertNotIn("admin_note", item)
        self.assertNotIn("payout_reference", item)
        self.assertNotIn("payout_proof_url", item)
        self.assertNotIn(raw_address, response.text)
        reject_withdrawal.assert_awaited_once_with(
            session,
            11,
            "invalid request",
            actor_user_id=None,
        )

    def test_platform_subscription_plans_rejects_tenant_api_key_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch.object(ApiKeyService, "authenticate", new_callable=AsyncMock) as authenticate:
            with patch("app.web.platform_admin.SubscriptionService") as service:
                response = client.get(
                    "/api/v1/platform/subscription/plans",
                    headers={"X-API-Key": "fk_live_tenant_key"},
                )

        self.assertEqual(401, response.status_code)
        self.assertEqual("缺少 Platform Admin API Key", response.json()["detail"])
        authenticate.assert_not_called()
        service.assert_not_called()

    def test_platform_subscription_plans_missing_config_fails_closed_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes=set()))

        with patch("app.web.platform_admin.SubscriptionService") as service:
            response = client.get(
                "/api/v1/platform/subscription/plans",
                headers={"X-Platform-API-Key": "pak_live_test"},
            )

        self.assertEqual(503, response.status_code)
        self.assertEqual("Platform Admin API 未启用", response.json()["detail"])
        service.assert_not_called()

    def test_platform_subscription_plans_requires_platform_subscriptions_read_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))
        scopes_without_read = {"platform_subscriptions:write"}

        with patch("app.web.platform_admin.PLATFORM_ADMIN_SCOPES", scopes_without_read):
            with patch("app.web.platform_admin.SubscriptionService") as service:
                response = client.get(
                    "/api/v1/platform/subscription/plans",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                )

        self.assertEqual(403, response.status_code)
        self.assertEqual("Platform Admin API Key 权限不足", response.json()["detail"])
        service.assert_not_called()

    def test_platform_subscription_plans_requires_signature_before_service(self) -> None:
        client = _client(
            Settings(
                platform_admin_api_key_hashes={_hash_key("pak_live_test")},
                platform_admin_require_signature=True,
            )
        )

        with patch("app.web.platform_admin.SubscriptionService") as service:
            response = client.get(
                "/api/v1/platform/subscription/plans",
                headers={"X-Platform-API-Key": "pak_live_test"},
            )

        self.assertEqual(401, response.status_code)
        self.assertEqual("缺少请求签名", response.json()["detail"])
        service.assert_not_called()

    def test_platform_subscription_plans_returns_safe_payload_only(self) -> None:
        session = _FakeSession()
        now = datetime(2026, 6, 9, 9, 0, tzinfo=timezone.utc)
        list_platform_subscription_plans = AsyncMock(
            return_value=[
                PlatformSubscriptionPlanSummary(
                    code="default_monthly",
                    name="默认月付套餐",
                    monthly_price=Decimal("10.00000000"),
                    currency="USDT",
                    trial_days=30,
                    grace_days=0,
                    enabled=True,
                    created_at=now,
                    updated_at=now,
                )
            ]
        )
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.SubscriptionService") as service:
                service.return_value.list_platform_subscription_plans = list_platform_subscription_plans
                response = client.get(
                    "/api/v1/platform/subscription/plans?enabled=true&limit=500",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual({"plans"}, set(payload))
        item = payload["plans"][0]
        self.assertEqual(
            {
                "code",
                "name",
                "monthly_price",
                "currency",
                "trial_days",
                "grace_days",
                "enabled",
                "created_at",
                "updated_at",
            },
            set(item),
        )
        self.assertEqual("default_monthly", item["code"])
        self.assertEqual("10.00000000", item["monthly_price"])
        for forbidden in ("plan_id", "tenant_id", "subscription_id", "invoice_id", "payment_id", "metadata_json"):
            self.assertNotIn(forbidden, item)
        list_platform_subscription_plans.assert_awaited_once_with(session, enabled=True, limit=100)

    def test_get_platform_subscription_plan_returns_safe_payload_only(self) -> None:
        session = _FakeSession()
        now = datetime(2026, 6, 9, 9, 0, tzinfo=timezone.utc)
        get_platform_subscription_plan = AsyncMock(
            return_value=PlatformSubscriptionPlanSummary(
                code="default_monthly",
                name="默认月付套餐",
                monthly_price=Decimal("10.00000000"),
                currency="USDT",
                trial_days=30,
                grace_days=0,
                enabled=True,
                created_at=now,
                updated_at=now,
            )
        )
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.SubscriptionService") as service:
                service.return_value.get_platform_subscription_plan = get_platform_subscription_plan
                response = client.get(
                    "/api/v1/platform/subscription/plans/default_monthly",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                )

        self.assertEqual(200, response.status_code)
        item = response.json()
        self.assertEqual(
            {
                "code",
                "name",
                "monthly_price",
                "currency",
                "trial_days",
                "grace_days",
                "enabled",
                "created_at",
                "updated_at",
            },
            set(item),
        )
        self.assertEqual("default_monthly", item["code"])
        for forbidden in ("plan_id", "tenant_id", "subscription_id", "invoice_id", "payment_id", "metadata_json"):
            self.assertNotIn(forbidden, item)
        get_platform_subscription_plan.assert_awaited_once_with(session, code="default_monthly")

    def test_get_platform_subscription_plan_requires_platform_subscriptions_read_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))
        scopes_without_read = {"platform_subscriptions:write"}

        with patch("app.web.platform_admin.PLATFORM_ADMIN_SCOPES", scopes_without_read):
            with patch("app.web.platform_admin.SubscriptionService") as service:
                response = client.get(
                    "/api/v1/platform/subscription/plans/default_monthly",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                )

        self.assertEqual(403, response.status_code)
        self.assertEqual("Platform Admin API Key 权限不足", response.json()["detail"])
        service.assert_not_called()

    def test_get_platform_subscription_plan_returns_404_when_missing(self) -> None:
        session = _FakeSession()
        get_platform_subscription_plan = AsyncMock(return_value=None)
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.SubscriptionService") as service:
                service.return_value.get_platform_subscription_plan = get_platform_subscription_plan
                response = client.get(
                    "/api/v1/platform/subscription/plans/missing",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                )

        self.assertEqual(404, response.status_code)
        self.assertEqual("订阅计划不存在", response.json()["detail"])
        self.assertEqual(0, session.commit_count)
        get_platform_subscription_plan.assert_awaited_once_with(session, code="missing")

    def test_create_platform_subscription_plan_requires_write_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))
        scopes_without_write = {"platform_subscriptions:read"}

        with patch("app.web.platform_admin.PLATFORM_ADMIN_SCOPES", scopes_without_write):
            with patch("app.web.platform_admin.SubscriptionService") as service:
                response = client.post(
                    "/api/v1/platform/subscription/plans",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                    json={
                        "code": "default_monthly",
                        "name": "默认月付套餐",
                        "monthly_price": "10.00",
                    },
                )

        self.assertEqual(403, response.status_code)
        self.assertEqual("Platform Admin API Key 权限不足", response.json()["detail"])
        service.assert_not_called()

    def test_create_platform_subscription_plan_rejects_extra_fields_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.SubscriptionService") as service:
            response = client.post(
                "/api/v1/platform/subscription/plans",
                headers={"X-Platform-API-Key": "pak_live_test"},
                json={
                    "code": "default_monthly",
                    "name": "默认月付套餐",
                    "monthly_price": "10.00",
                    "tenant_id": 7,
                },
            )

        self.assertEqual(422, response.status_code)
        service.assert_not_called()

    def test_create_platform_subscription_plan_commits_and_returns_safe_payload(self) -> None:
        session = _FakeSession()
        now = datetime(2026, 6, 9, 9, 0, tzinfo=timezone.utc)
        create_platform_subscription_plan = AsyncMock(
            return_value=PlatformSubscriptionPlanSummary(
                code="default_monthly",
                name="默认月付套餐",
                monthly_price=Decimal("10.00000000"),
                currency="USDT",
                trial_days=30,
                grace_days=0,
                enabled=True,
                created_at=now,
                updated_at=now,
            )
        )
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.SubscriptionService") as service:
                service.return_value.create_platform_subscription_plan = create_platform_subscription_plan
                response = client.post(
                    "/api/v1/platform/subscription/plans",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                    json={
                        "code": "default_monthly",
                        "name": "默认月付套餐",
                        "monthly_price": "10.00",
                        "currency": "USDT",
                        "trial_days": 30,
                        "grace_days": 0,
                        "enabled": True,
                        "reason": "initial setup",
                    },
                )

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, session.commit_count)
        item = response.json()
        self.assertEqual("default_monthly", item["code"])
        self.assertNotIn("plan_id", item)
        self.assertNotIn("metadata_json", item)
        create_platform_subscription_plan.assert_awaited_once_with(
            session,
            code="default_monthly",
            name="默认月付套餐",
            monthly_price=Decimal("10.00"),
            currency="USDT",
            trial_days=30,
            grace_days=0,
            enabled=True,
            reason="initial setup",
        )

    def test_update_platform_subscription_plan_returns_404_without_commit_when_missing(self) -> None:
        session = _FakeSession()
        update_platform_subscription_plan = AsyncMock(return_value=None)
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.SubscriptionService") as service:
                service.return_value.update_platform_subscription_plan = update_platform_subscription_plan
                response = client.patch(
                    "/api/v1/platform/subscription/plans/missing",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                    json={"monthly_price": "12.00"},
                )

        self.assertEqual(404, response.status_code)
        self.assertEqual("订阅计划不存在", response.json()["detail"])
        self.assertEqual(0, session.commit_count)
        update_platform_subscription_plan.assert_awaited_once_with(
            session,
            code="missing",
            name=None,
            monthly_price=Decimal("12.00"),
            currency=None,
            trial_days=None,
            grace_days=None,
            reason=None,
        )

    def test_update_platform_subscription_plan_requires_write_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))
        scopes_without_write = {"platform_subscriptions:read"}

        with patch("app.web.platform_admin.PLATFORM_ADMIN_SCOPES", scopes_without_write):
            with patch("app.web.platform_admin.SubscriptionService") as service:
                response = client.patch(
                    "/api/v1/platform/subscription/plans/default_monthly",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                    json={"monthly_price": "12.00"},
                )

        self.assertEqual(403, response.status_code)
        self.assertEqual("Platform Admin API Key 权限不足", response.json()["detail"])
        service.assert_not_called()

    def test_update_platform_subscription_plan_commits_and_returns_safe_payload(self) -> None:
        session = _FakeSession()
        now = datetime(2026, 6, 9, 9, 0, tzinfo=timezone.utc)
        update_platform_subscription_plan = AsyncMock(
            return_value=PlatformSubscriptionPlanSummary(
                code="default_monthly",
                name="标准月付",
                monthly_price=Decimal("12.00000000"),
                currency="USDT",
                trial_days=14,
                grace_days=3,
                enabled=True,
                created_at=now,
                updated_at=now,
            )
        )
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.SubscriptionService") as service:
                service.return_value.update_platform_subscription_plan = update_platform_subscription_plan
                response = client.patch(
                    "/api/v1/platform/subscription/plans/default_monthly",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                    json={
                        "name": "标准月付",
                        "monthly_price": "12.00",
                        "currency": "USDT",
                        "trial_days": 14,
                        "grace_days": 3,
                        "reason": "price update",
                    },
                )

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, session.commit_count)
        item = response.json()
        self.assertEqual("default_monthly", item["code"])
        self.assertEqual("标准月付", item["name"])
        self.assertEqual("12.00000000", item["monthly_price"])
        self.assertNotIn("tenant_id", item)
        self.assertNotIn("plan_id", item)
        self.assertNotIn("metadata_json", item)
        update_platform_subscription_plan.assert_awaited_once_with(
            session,
            code="default_monthly",
            name="标准月付",
            monthly_price=Decimal("12.00"),
            currency="USDT",
            trial_days=14,
            grace_days=3,
            reason="price update",
        )

    def test_update_platform_subscription_plan_status_commits_and_returns_safe_payload(self) -> None:
        session = _FakeSession()
        now = datetime(2026, 6, 9, 9, 0, tzinfo=timezone.utc)
        set_platform_subscription_plan_enabled = AsyncMock(
            return_value=PlatformSubscriptionPlanSummary(
                code="default_monthly",
                name="默认月付套餐",
                monthly_price=Decimal("10.00000000"),
                currency="USDT",
                trial_days=30,
                grace_days=3,
                enabled=False,
                created_at=now,
                updated_at=now,
            )
        )
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.SubscriptionService") as service:
                service.return_value.set_platform_subscription_plan_enabled = set_platform_subscription_plan_enabled
                response = client.patch(
                    "/api/v1/platform/subscription/plans/default_monthly/status",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                    json={"enabled": False, "reason": "maintenance"},
                )

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, session.commit_count)
        item = response.json()
        self.assertFalse(item["enabled"])
        self.assertNotIn("tenant_id", item)
        set_platform_subscription_plan_enabled.assert_awaited_once_with(
            session,
            code="default_monthly",
            enabled=False,
            reason="maintenance",
        )

    def test_platform_subscription_plan_value_error_returns_400_without_secret(self) -> None:
        session = _FakeSession()
        create_platform_subscription_plan = AsyncMock(side_effect=ValueError("订阅计划 code 无效 token=plain-secret"))
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.SubscriptionService") as service:
                service.return_value.create_platform_subscription_plan = create_platform_subscription_plan
                response = client.post(
                    "/api/v1/platform/subscription/plans",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                    json={
                        "code": "bad",
                        "name": "默认月付套餐",
                        "monthly_price": "10.00",
                    },
                )

        self.assertEqual(400, response.status_code)
        self.assertEqual("平台订阅计划参数无效", response.json()["detail"])
        self.assertEqual(0, session.commit_count)
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("token=", response.text)

    def test_platform_supply_supplier_offers_rejects_tenant_api_key_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch.object(ApiKeyService, "authenticate", new_callable=AsyncMock) as authenticate:
            with patch("app.web.platform_admin.SupplyService") as service:
                response = client.get(
                    "/api/v1/platform/supply/supplier-offers",
                    headers={"X-API-Key": "fk_live_tenant_key"},
                )

        self.assertEqual(401, response.status_code)
        self.assertEqual("缺少 Platform Admin API Key", response.json()["detail"])
        authenticate.assert_not_called()
        service.assert_not_called()

    def test_platform_supply_supplier_offers_requires_valid_platform_key_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.SupplyService") as service:
            response = client.get(
                "/api/v1/platform/supply/supplier-offers",
                headers={"X-Platform-API-Key": "wrong"},
            )

        self.assertEqual(401, response.status_code)
        self.assertEqual("Platform Admin API Key 无效", response.json()["detail"])
        service.assert_not_called()

    def test_platform_supply_supplier_offers_returns_safe_payload_only(self) -> None:
        session = _FakeSession()
        now = datetime(2026, 6, 9, 9, 0, tzinfo=timezone.utc)
        list_platform_supplier_offers = AsyncMock(
            return_value=[
                PlatformSupplierOfferSummary(
                    supplier_offer_id=91,
                    supplier_tenant_id=7,
                    supplier_store_name="供货商",
                    product_name="卡密",
                    delivery_type="card_pool",
                    suggested_price=Decimal("12.00"),
                    min_sale_price=Decimal("10.00"),
                    supplier_cost=Decimal("8.50"),
                    currency="USDT",
                    available_count=5,
                    requires_approval=True,
                    status="on",
                    created_at=now,
                    updated_at=now,
                )
            ]
        )
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.SupplyService") as service:
                service.return_value.list_platform_supplier_offers = list_platform_supplier_offers
                response = client.get(
                    "/api/v1/platform/supply/supplier-offers?status=on&supplier_tenant_id=7&limit=10",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual({"offers"}, set(payload))
        item = payload["offers"][0]
        self.assertEqual(
            {
                "supplier_offer_id",
                "supplier_tenant_id",
                "supplier_store_name",
                "product_name",
                "delivery_type",
                "suggested_price",
                "min_sale_price",
                "supplier_cost",
                "currency",
                "available_count",
                "requires_approval",
                "status",
                "created_at",
                "updated_at",
            },
            set(item),
        )
        self.assertEqual(91, item["supplier_offer_id"])
        self.assertEqual(7, item["supplier_tenant_id"])
        for forbidden in (
            "tenant_id",
            "product_id",
            "variant_id",
            "rule_id",
            "reseller_tenant_id",
            "pricing_value",
            "credentials",
            "token",
            "secret",
            "api_key",
            "storage_key",
            "content",
            "raw_payload",
            "metadata_json",
        ):
            self.assertNotIn(forbidden, item)
        list_platform_supplier_offers.assert_awaited_once_with(
            session,
            status="on",
            supplier_tenant_id=7,
            limit=10,
        )

    def test_platform_supply_supplier_offer_status_requires_platform_supply_write_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.PLATFORM_ADMIN_SCOPES", {"platform_supply:read"}):
            with patch("app.web.platform_admin.SupplyService") as service:
                response = client.patch(
                    "/api/v1/platform/supply/supplier-offers/91/status",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                    json={"status": "disabled"},
                )

        self.assertEqual(403, response.status_code)
        self.assertEqual("Platform Admin API Key 权限不足", response.json()["detail"])
        service.assert_not_called()

    def test_platform_supply_supplier_offer_status_requires_signature_before_service(self) -> None:
        client = _client(
            Settings(
                platform_admin_api_key_hashes={_hash_key("pak_live_test")},
                platform_admin_require_signature=True,
            )
        )

        with patch("app.web.platform_admin.SupplyService") as service:
            response = client.patch(
                "/api/v1/platform/supply/supplier-offers/91/status",
                headers={"X-Platform-API-Key": "pak_live_test"},
                json={"status": "disabled"},
            )

        self.assertEqual(401, response.status_code)
        self.assertEqual("缺少请求签名", response.json()["detail"])
        service.assert_not_called()

    def test_platform_supply_supplier_offer_status_rejects_extra_fields_before_service(self) -> None:
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.SupplyService") as service:
            response = client.patch(
                "/api/v1/platform/supply/supplier-offers/91/status",
                headers={"X-Platform-API-Key": "pak_live_test"},
                json={"status": "disabled", "rule_id": 123, "token": "plain-secret"},
            )

        self.assertEqual(422, response.status_code)
        service.assert_not_called()

    def test_platform_supply_supplier_offer_status_value_error_returns_400_without_secret(self) -> None:
        session = _FakeSession()
        set_platform_supplier_offer_status = AsyncMock(side_effect=ValueError("token=plain-secret"))
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.SupplyService") as service:
                service.return_value.set_platform_supplier_offer_status = set_platform_supplier_offer_status
                response = client.patch(
                    "/api/v1/platform/supply/supplier-offers/91/status",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                    json={"status": "disabled"},
                )

        self.assertEqual(400, response.status_code)
        self.assertEqual("平台供货管控参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("token=", response.text)
        self.assertEqual(0, session.commit_count)

    def test_platform_supply_supplier_offer_status_is_platform_scoped_and_redacted(self) -> None:
        session = _FakeSession()
        now = datetime(2026, 6, 9, 9, 0, tzinfo=timezone.utc)
        set_platform_supplier_offer_status = AsyncMock(
            return_value=PlatformSupplierOfferSummary(
                supplier_offer_id=91,
                supplier_tenant_id=7,
                supplier_store_name="供货商",
                product_name="卡密",
                delivery_type="card_pool",
                suggested_price=Decimal("12.00"),
                min_sale_price=Decimal("10.00"),
                supplier_cost=Decimal("8.50"),
                currency="USDT",
                available_count=5,
                requires_approval=True,
                status="disabled",
                created_at=now,
                updated_at=now,
            )
        )
        client = _client(Settings(platform_admin_api_key_hashes={_hash_key("pak_live_test")}))

        with patch("app.web.platform_admin.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.platform_admin.SupplyService") as service:
                service.return_value.set_platform_supplier_offer_status = set_platform_supplier_offer_status
                response = client.patch(
                    "/api/v1/platform/supply/supplier-offers/91/status",
                    headers={"X-Platform-API-Key": "pak_live_test"},
                    json={"status": "disabled", "reason": "违规 token=plain-secret"},
                )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(
            {
                "supplier_offer_id",
                "supplier_tenant_id",
                "supplier_store_name",
                "product_name",
                "delivery_type",
                "suggested_price",
                "min_sale_price",
                "supplier_cost",
                "currency",
                "available_count",
                "requires_approval",
                "status",
                "created_at",
                "updated_at",
            },
            set(payload),
        )
        self.assertEqual("disabled", payload["status"])
        self.assertNotIn("product_id", payload)
        self.assertNotIn("variant_id", payload)
        self.assertNotIn("rule_id", payload)
        self.assertNotIn("token", payload)
        self.assertNotIn("secret", payload)
        self.assertEqual(1, session.commit_count)
        set_platform_supplier_offer_status.assert_awaited_once_with(
            session,
            supplier_offer_id=91,
            status="disabled",
            reason="违规 token=plain-secret",
        )


if __name__ == "__main__":
    unittest.main()
