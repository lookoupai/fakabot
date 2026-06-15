from __future__ import annotations

import unittest
import warnings
from unittest.mock import patch

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.web.health import router
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过健康检查测试：{exc.name}") from exc


class _FakeSession:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.execute_count = 0

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    async def execute(self, _query: object) -> None:
        self.execute_count += 1
        if self.fail:
            raise RuntimeError("db down")


class _FakeRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.ping_count = 0

    async def ping(self) -> bool:
        self.ping_count += 1
        if self.fail:
            raise RuntimeError("redis down")
        return True


class _FakeSettings:
    def __init__(self, *, workers_enabled: bool) -> None:
        self.workers_enabled = workers_enabled


class _FakeWorkerManager:
    def __init__(self, *, ready: bool = True) -> None:
        self.ready = ready
        self.is_ready_count = 0

    def is_ready(self) -> bool:
        self.is_ready_count += 1
        return self.ready


def _session_factory(session: _FakeSession):
    def factory() -> _FakeSession:
        return session

    return factory


def _client(
    redis: object | None,
    *,
    settings: object | None = None,
    worker_manager: object | None = None,
) -> TestClient:
    app = FastAPI()
    app.state.redis = redis
    if settings is not None:
        app.state.settings = settings
    if worker_manager is not None:
        app.state.worker_manager = worker_manager
    app.include_router(router)
    return TestClient(app)


class HealthReadinessTest(unittest.TestCase):
    def test_health_returns_ok_without_dependencies(self) -> None:
        response = _client(None).get("/health")

        self.assertEqual(200, response.status_code)
        self.assertEqual({"status": "ok"}, response.json())

    def test_ready_returns_ok_when_database_and_redis_are_available(self) -> None:
        session = _FakeSession()
        redis = _FakeRedis()

        with patch("app.web.health.get_session_factory", return_value=_session_factory(session)):
            response = _client(redis).get("/ready")

        self.assertEqual(200, response.status_code)
        self.assertEqual({"status": "ok"}, response.json())
        self.assertEqual(1, session.execute_count)
        self.assertEqual(1, redis.ping_count)

    def test_ready_returns_503_when_database_is_unavailable(self) -> None:
        session = _FakeSession(fail=True)
        redis = _FakeRedis()

        with patch("app.web.health.get_session_factory", return_value=_session_factory(session)):
            response = _client(redis).get("/ready")

        self.assertEqual(503, response.status_code)
        self.assertEqual("database_unavailable", response.json()["detail"])
        self.assertEqual(0, redis.ping_count)

    def test_ready_returns_503_when_redis_is_missing_or_unavailable(self) -> None:
        for redis in [None, _FakeRedis(fail=True)]:
            with self.subTest(redis=redis):
                session = _FakeSession()
                with patch("app.web.health.get_session_factory", return_value=_session_factory(session)):
                    response = _client(redis).get("/ready")

                self.assertEqual(503, response.status_code)
                self.assertEqual("redis_unavailable", response.json()["detail"])

    def test_ready_checks_worker_manager_when_workers_are_enabled(self) -> None:
        session = _FakeSession()
        redis = _FakeRedis()
        worker_manager = _FakeWorkerManager(ready=True)

        with patch("app.web.health.get_session_factory", return_value=_session_factory(session)):
            response = _client(
                redis,
                settings=_FakeSettings(workers_enabled=True),
                worker_manager=worker_manager,
            ).get("/ready")

        self.assertEqual(200, response.status_code)
        self.assertEqual({"status": "ok"}, response.json())
        self.assertEqual(1, worker_manager.is_ready_count)

    def test_ready_rejects_missing_or_unready_worker_manager_when_workers_are_enabled(self) -> None:
        for worker_manager in [None, object(), _FakeWorkerManager(ready=False)]:
            with self.subTest(worker_manager=worker_manager):
                session = _FakeSession()
                redis = _FakeRedis()

                with patch("app.web.health.get_session_factory", return_value=_session_factory(session)):
                    response = _client(
                        redis,
                        settings=_FakeSettings(workers_enabled=True),
                        worker_manager=worker_manager,
                    ).get("/ready")

                self.assertEqual(503, response.status_code)
                self.assertEqual("worker_unavailable", response.json()["detail"])

    def test_ready_ignores_worker_manager_when_workers_are_disabled(self) -> None:
        session = _FakeSession()
        redis = _FakeRedis()

        with patch("app.web.health.get_session_factory", return_value=_session_factory(session)):
            response = _client(
                redis,
                settings=_FakeSettings(workers_enabled=False),
                worker_manager=_FakeWorkerManager(ready=False),
            ).get("/ready")

        self.assertEqual(200, response.status_code)
        self.assertEqual({"status": "ok"}, response.json())


if __name__ == "__main__":
    unittest.main()
