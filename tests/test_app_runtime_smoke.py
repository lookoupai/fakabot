from __future__ import annotations

import logging
import unittest
import warnings
from unittest.mock import AsyncMock, patch

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)
warnings.simplefilter("ignore", DeprecationWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning, module="app\\.main")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="fastapi\\.applications")
logging.getLogger("httpx").setLevel(logging.WARNING)

try:
    from fastapi.testclient import TestClient
    from pydantic import SecretStr

    from app.config import Settings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from app.main import create_app as _create_app
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过 app 运行时 smoke 测试：{exc.name}") from exc


class _ReadySession:
    def __init__(self) -> None:
        self.execute_count = 0

    async def __aenter__(self) -> "_ReadySession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    async def execute(self, query: object) -> None:
        self.execute_count += 1


class _FakeRedis:
    def __init__(self) -> None:
        self.ping_count = 0
        self.aclose_count = 0

    async def ping(self) -> bool:
        self.ping_count += 1
        return True

    async def aclose(self) -> None:
        self.aclose_count += 1


class _FakeWorkerManager:
    instances: list["_FakeWorkerManager"] = []

    def __init__(self, settings: Settings, session_factory: object) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.start_count = 0
        self.stop_count = 0
        self.is_ready_count = 0
        self.ready = False
        _FakeWorkerManager.instances.append(self)

    def start(self) -> None:
        self.start_count += 1
        self.ready = True

    def is_ready(self) -> bool:
        self.is_ready_count += 1
        return self.ready

    async def stop(self) -> None:
        self.stop_count += 1
        self.ready = False


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://fake:fake@localhost/fake",
        redis_url="redis://fake-redis:6379/0",
        master_bot_token=SecretStr("123456:master-token"),
        token_encryption_key=SecretStr("0" * 44),
        workers_enabled=True,
    )


def _session_factory(session: _ReadySession):
    def factory() -> _ReadySession:
        return session

    return factory


def _create_app_silently():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return _create_app()


class AppRuntimeSmokeTest(unittest.TestCase):
    def test_create_app_mounts_core_route_subset(self) -> None:
        with patch("app.main.get_settings", return_value=_settings()), patch("app.main.configure_db"):
            app = _create_app_silently()

        paths = {route.path for route in app.routes}
        expected_paths = {
            "/health",
            "/ready",
            "/telegram/webhook/{webhook_secret}",
            "/payments/callback/epusdt_gmpay",
            "/files/download/{token}",
            "/exports/download/{token}",
            "/api/v1/store/{tenant_public_id}/products",
            "/api/v1/tenant/products",
            "/api/v1/platform/risk/banned-users",
            "/api/v1/platform/risk/users/{telegram_user_id}/ban-status",
            "/api/v1/platform/risk/tenants/{tenant_id}/suspension-status",
            "/api/v1/platform/risk/audit-logs",
            "/api/v1/platform/finance/withdrawals",
            "/api/v1/platform/finance/withdrawals/{withdrawal_id}",
            "/api/v1/platform/finance/withdrawals/{withdrawal_id}/complete",
            "/api/v1/platform/finance/withdrawals/{withdrawal_id}/reject",
            "/api/v1/platform/subscription/plans",
            "/api/v1/platform/subscription/plans/{plan_code}",
            "/api/v1/platform/subscription/plans/{plan_code}/status",
            "/api/v1/platform/supply/supplier-offers",
            "/api/v1/platform/supply/supplier-offers/{supplier_offer_id}/status",
        }

        self.assertTrue(expected_paths <= paths)

    def test_lifespan_initializes_ready_state_and_cleans_dependencies(self) -> None:
        settings = _settings()
        ready_session = _ReadySession()
        fake_redis = _FakeRedis()
        fake_dispatcher = object()
        _FakeWorkerManager.instances = []

        with patch("app.main.get_settings", return_value=settings), patch("app.main.configure_db") as configure_db, patch(
            "app.main.get_session_factory", return_value=_session_factory(ready_session)
        ) as main_session_factory, patch("app.web.health.get_session_factory", return_value=_session_factory(ready_session)), patch(
            "app.main.create_dispatcher", return_value=fake_dispatcher
        ) as create_dispatcher, patch(
            "app.main.redis.from_url", return_value=fake_redis
        ) as redis_from_url, patch(
            "app.main.BackgroundWorkerManager", _FakeWorkerManager
        ), patch(
            "app.main.close_db", new=AsyncMock()
        ) as close_db:
            app = _create_app_silently()
            with TestClient(app) as client:
                self.assertIs(app.state.dispatcher, fake_dispatcher)
                self.assertIs(app.state.redis, fake_redis)
                self.assertEqual(1, len(_FakeWorkerManager.instances))
                worker = _FakeWorkerManager.instances[0]
                self.assertEqual(1, worker.start_count)

                health_response = client.get("/health")
                ready_response = client.get("/ready")

            self.assertEqual(1, worker.stop_count)
            close_db.assert_awaited_once()

        configure_db.assert_called_once_with(settings.database_url)
        main_session_factory.assert_called_once()
        create_dispatcher.assert_called_once_with(settings)
        redis_from_url.assert_called_once_with(settings.redis_url, decode_responses=True)
        self.assertEqual(200, health_response.status_code)
        self.assertEqual({"status": "ok"}, health_response.json())
        self.assertEqual(200, ready_response.status_code)
        self.assertEqual({"status": "ok"}, ready_response.json())
        self.assertEqual(1, worker.is_ready_count)
        self.assertEqual(1, ready_session.execute_count)
        self.assertEqual(1, fake_redis.ping_count)
        self.assertEqual(1, fake_redis.aclose_count)

    def test_health_ready_openapi_are_public(self) -> None:
        with patch("app.main.get_settings", return_value=_settings()), patch("app.main.configure_db"):
            schema = _create_app_silently().openapi()

        for path in ("/health", "/ready"):
            self.assertIn(path, schema["paths"])
            operation = schema["paths"][path]["get"]
            self.assertNotIn("security", operation)
            parameters = operation.get("parameters", [])
            rendered_parameters = str(parameters)
            self.assertNotIn("X-Faka-Timestamp", rendered_parameters)
            self.assertNotIn("X-Faka-Signature", rendered_parameters)


if __name__ == "__main__":
    unittest.main()
