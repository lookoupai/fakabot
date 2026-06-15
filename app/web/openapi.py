from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

TENANT_ADMIN_PATH_PREFIX = "/api/v1/tenant"
PLATFORM_ADMIN_PATH_PREFIX = "/api/v1/platform"
PLATFORM_ADMIN_REQUIRED_SCOPES = {
    ("get", "/api/v1/platform/finance/withdrawals"): "platform_finance:read",
    ("get", "/api/v1/platform/finance/withdrawals/{withdrawal_id}"): "platform_finance:read",
    ("post", "/api/v1/platform/finance/withdrawals/{withdrawal_id}/complete"): "platform_finance:write",
    ("post", "/api/v1/platform/finance/withdrawals/{withdrawal_id}/reject"): "platform_finance:write",
    ("get", "/api/v1/platform/risk/audit-logs"): "platform_risk:read",
    ("get", "/api/v1/platform/risk/banned-users"): "platform_risk:read",
    ("get", "/api/v1/platform/risk/users/{telegram_user_id}/ban-status"): "platform_risk:read",
    ("patch", "/api/v1/platform/risk/tenants/{tenant_id}/suspension-status"): "platform_risk:write",
    ("patch", "/api/v1/platform/risk/users/{telegram_user_id}/ban-status"): "platform_risk:write",
    ("get", "/api/v1/platform/subscription/plans"): "platform_subscriptions:read",
    ("post", "/api/v1/platform/subscription/plans"): "platform_subscriptions:write",
    ("get", "/api/v1/platform/subscription/plans/{plan_code}"): "platform_subscriptions:read",
    ("patch", "/api/v1/platform/subscription/plans/{plan_code}"): "platform_subscriptions:write",
    ("patch", "/api/v1/platform/subscription/plans/{plan_code}/status"): "platform_subscriptions:write",
    ("get", "/api/v1/platform/supply/supplier-offers"): "platform_supply:read",
    ("patch", "/api/v1/platform/supply/supplier-offers/{supplier_offer_id}/status"): "platform_supply:write",
}


def install_openapi_security(application: FastAPI) -> None:
    def custom_openapi() -> dict[str, Any]:
        if application.openapi_schema:
            return application.openapi_schema
        schema = get_openapi(
            title=application.title,
            version=application.version,
            description=application.description,
            routes=application.routes,
        )
        _install_tenant_admin_security(schema)
        _install_platform_admin_security(schema)
        application.openapi_schema = schema
        return schema

    application.openapi = custom_openapi  # type: ignore[method-assign]


def _install_tenant_admin_security(schema: dict[str, Any]) -> None:
    components = schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    security_schemes.update(
        {
            "TenantAdminBearer": {
                "type": "http",
                "scheme": "bearer",
                "description": "租户 Admin API Key。格式：Authorization: Bearer fk_live_xxx",
            },
            "TenantAdminApiKeyHeader": {
                "type": "apiKey",
                "in": "header",
                "name": "X-API-Key",
                "description": "租户 Admin API Key。与 Bearer 二选一。",
            },
        }
    )

    for path, path_item in schema.get("paths", {}).items():
        if not path.startswith(TENANT_ADMIN_PATH_PREFIX):
            continue
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            operation["security"] = [
                {"TenantAdminBearer": []},
                {"TenantAdminApiKeyHeader": []},
            ]
            operation["parameters"] = _with_signature_headers(operation.get("parameters", []))
            operation["x-fakabot-signature"] = {
                "requiredByConfig": "TENANT_ADMIN_REQUIRE_SIGNATURE",
                "payload": "METHOD + PATH + QUERY + BODY_SHA256 + TIMESTAMP",
                "algorithm": "HMAC-SHA256",
            }


def _install_platform_admin_security(schema: dict[str, Any]) -> None:
    components = schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    security_schemes.update(
        {
            "PlatformAdminBearer": {
                "type": "http",
                "scheme": "bearer",
                "description": "平台 Admin API Key。格式：Authorization: Bearer pak_live_xxx",
            },
            "PlatformAdminApiKeyHeader": {
                "type": "apiKey",
                "in": "header",
                "name": "X-Platform-API-Key",
                "description": "平台 Admin API Key。与 Bearer 二选一。",
            },
        }
    )

    for path, path_item in schema.get("paths", {}).items():
        if not path.startswith(PLATFORM_ADMIN_PATH_PREFIX):
            continue
        for method, operation in path_item.items():
            if not isinstance(operation, dict):
                continue
            operation["security"] = [
                {"PlatformAdminBearer": []},
                {"PlatformAdminApiKeyHeader": []},
            ]
            operation["parameters"] = _with_signature_headers(operation.get("parameters", []))
            operation["x-fakabot-signature"] = {
                "requiredByConfig": "PLATFORM_ADMIN_REQUIRE_SIGNATURE",
                "payload": "METHOD + PATH + QUERY + BODY_SHA256 + TIMESTAMP",
                "algorithm": "HMAC-SHA256",
            }
            required_scope = PLATFORM_ADMIN_REQUIRED_SCOPES.get((method, path))
            if required_scope:
                operation["x-fakabot-required-scope"] = required_scope


def _with_signature_headers(parameters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing = {(parameter.get("in"), parameter.get("name")) for parameter in parameters}
    signature_headers = [
        {
            "name": "X-Faka-Timestamp",
            "in": "header",
            "required": False,
            "schema": {"type": "string"},
            "description": "启用签名校验时必填，Unix 秒级时间戳。",
        },
        {
            "name": "X-Faka-Signature",
            "in": "header",
            "required": False,
            "schema": {"type": "string"},
            "description": "启用签名校验时必填，使用 API Key 明文对规范 payload 做 HMAC-SHA256。",
        },
    ]
    missing = [header for header in signature_headers if ("header", header["name"]) not in existing]
    return [*parameters, *missing]
