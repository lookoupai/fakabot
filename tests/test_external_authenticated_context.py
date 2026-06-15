from __future__ import annotations

import unittest
from types import SimpleNamespace

try:
    from app.services.external_sources.base import (
        ExternalAuthenticatedCatalogSyncContext,
        ExternalAuthenticatedOperationContext,
    )
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过外部源认证上下文测试：{exc.name}") from exc


class ExternalAuthenticatedContextTest(unittest.TestCase):
    def test_operation_context_keeps_runtime_auth_required_and_repr_redacted(self) -> None:
        runtime_auth = SimpleNamespace(connection_id=1, api_key="plain-secret")

        context = ExternalAuthenticatedOperationContext(
            tenant_id=7,
            provider_name="demo",
            source_key="main",
            connection_id=1,
            runtime_auth=runtime_auth,
        )

        self.assertIs(runtime_auth, context.runtime_auth)
        self.assertNotIn("plain-secret", repr(context))
        self.assertIn("runtime_auth='***'", repr(context))

    def test_catalog_context_keeps_runtime_auth_required_and_repr_redacted(self) -> None:
        runtime_auth = SimpleNamespace(connection_id=2, token="plain-token")

        context = ExternalAuthenticatedCatalogSyncContext(
            tenant_id=7,
            provider_name="demo",
            source_key="main",
            connection_id=2,
            runtime_auth=runtime_auth,
        )

        self.assertIs(runtime_auth, context.runtime_auth)
        self.assertNotIn("plain-token", repr(context))
        self.assertIn("runtime_auth='***'", repr(context))


if __name__ == "__main__":
    unittest.main()
