from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Optional

from app.services.external_sources.identifiers import normalize_external_identifier

BUSINESS_PLUGIN_KIND_PAYMENT = "payment"
BUSINESS_PLUGIN_KIND_EXTERNAL_SOURCE = "external_source"
BUSINESS_PLUGIN_KIND_BOT_FEATURE = "bot_feature"
BUSINESS_PLUGIN_KIND_ADMIN_WEB_PANEL = "admin_web_panel"
BUSINESS_PLUGIN_KIND_BACKGROUND_JOB = "background_job"
BUSINESS_PLUGIN_KIND_WEBHOOK_HANDLER = "webhook_handler"
BUSINESS_PLUGIN_KIND_TENANT_TOOL = "tenant_tool"

BUSINESS_PLUGIN_KINDS = frozenset(
    {
        BUSINESS_PLUGIN_KIND_PAYMENT,
        BUSINESS_PLUGIN_KIND_EXTERNAL_SOURCE,
        BUSINESS_PLUGIN_KIND_BOT_FEATURE,
        BUSINESS_PLUGIN_KIND_ADMIN_WEB_PANEL,
        BUSINESS_PLUGIN_KIND_BACKGROUND_JOB,
        BUSINESS_PLUGIN_KIND_WEBHOOK_HANDLER,
        BUSINESS_PLUGIN_KIND_TENANT_TOOL,
    }
)

ALLOWED_PLUGIN_ENTRYPOINT_PREFIXES = (
    "app.services.",
    "fakabot_ext_",
)

_ENTRYPOINT_PATTERN = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*$"
)
_TEXT_PATTERN = re.compile(r"^[A-Za-z0-9_.:+-]+$")


@dataclass(frozen=True)
class BusinessPluginManifest:
    plugin_id: str
    name: str
    version: str
    kind: str
    contract_version: str
    capabilities: Mapping[str, bool] = field(default_factory=dict)
    entrypoint: Optional[str] = None
    production_ready: bool = False
    staging_verified: bool = False
    offline_only: bool = True
    tenant_configurable: bool = False
    platform_configurable: bool = False
    requires_tenant_enablement: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "plugin_id",
            normalize_external_identifier(self.plugin_id, "plugin_id", allow_empty=False),
        )
        object.__setattr__(self, "name", _normalize_display_text(self.name, "name", max_length=120))
        object.__setattr__(self, "version", _normalize_token_text(self.version, "version"))
        normalized_kind = normalize_external_identifier(self.kind, "kind", allow_empty=False)
        if normalized_kind not in BUSINESS_PLUGIN_KINDS:
            raise ValueError("插件 kind 不支持")
        object.__setattr__(self, "kind", normalized_kind)
        object.__setattr__(
            self,
            "contract_version",
            normalize_external_identifier(self.contract_version, "contract_version", allow_empty=False),
        )
        object.__setattr__(self, "capabilities", MappingProxyType(_normalize_capabilities(self.capabilities)))
        object.__setattr__(self, "entrypoint", _normalize_entrypoint(self.entrypoint))
        for field_name in (
            "production_ready",
            "staging_verified",
            "offline_only",
            "tenant_configurable",
            "platform_configurable",
            "requires_tenant_enablement",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, bool):
                raise ValueError(f"{field_name} 必须是布尔值")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "BusinessPluginManifest":
        if not isinstance(payload, Mapping):
            raise ValueError("插件 manifest 必须是对象")
        required_fields = {
            "plugin_id",
            "name",
            "version",
            "kind",
            "contract_version",
            "capabilities",
            "production_ready",
            "staging_verified",
        }
        missing_fields = sorted(field for field in required_fields if field not in payload)
        if missing_fields:
            raise ValueError(f"插件 manifest 缺少字段：{', '.join(missing_fields)}")
        return cls(
            plugin_id=payload["plugin_id"],
            name=payload["name"],
            version=payload["version"],
            kind=payload["kind"],
            contract_version=payload["contract_version"],
            capabilities=payload["capabilities"],
            entrypoint=payload.get("entrypoint"),
            production_ready=payload["production_ready"],
            staging_verified=payload["staging_verified"],
            offline_only=payload.get("offline_only", True),
            tenant_configurable=payload.get("tenant_configurable", False),
            platform_configurable=payload.get("platform_configurable", False),
            requires_tenant_enablement=payload.get("requires_tenant_enablement", True),
        )

    @property
    def entrypoint_allowed(self) -> bool:
        if self.entrypoint is None:
            return False
        return is_plugin_entrypoint_allowed(self.entrypoint)


class BusinessPluginRegistry:
    def __init__(self, manifests: Optional[list[BusinessPluginManifest]] = None) -> None:
        self._manifests: dict[str, BusinessPluginManifest] = {}
        for manifest in manifests or []:
            self.register(manifest)

    def register(self, manifest: BusinessPluginManifest | Mapping[str, Any]) -> None:
        normalized = (
            manifest
            if isinstance(manifest, BusinessPluginManifest)
            else BusinessPluginManifest.from_mapping(manifest)
        )
        if normalized.plugin_id in self._manifests:
            raise ValueError(f"业务插件已注册：{normalized.plugin_id}")
        self._manifests[normalized.plugin_id] = normalized

    def get(self, plugin_id: str) -> Optional[BusinessPluginManifest]:
        return self._manifests.get(normalize_external_identifier(plugin_id, "plugin_id", allow_empty=False))

    def list(self) -> list[BusinessPluginManifest]:
        return [self._manifests[plugin_id] for plugin_id in sorted(self._manifests)]


def is_plugin_entrypoint_allowed(entrypoint: str) -> bool:
    normalized = _normalize_entrypoint(entrypoint)
    if normalized is None:
        return False
    module_name, _, _callable_name = normalized.partition(":")
    return any(module_name.startswith(prefix) for prefix in ALLOWED_PLUGIN_ENTRYPOINT_PREFIXES)


def payment_summary_to_plugin_manifest(summary: Any) -> BusinessPluginManifest:
    provider_name = normalize_external_identifier(summary.provider_name, "provider_name", allow_empty=False)
    return BusinessPluginManifest(
        plugin_id=f"payment_{provider_name}",
        name=f"{summary.display_name} 支付插件",
        version="builtin",
        kind=BUSINESS_PLUGIN_KIND_PAYMENT,
        contract_version=summary.contract_name,
        capabilities={
            "create_payment": bool(summary.create_payment_available),
            "callback": bool(summary.callback_available),
            "query_order": bool(summary.query_order_available),
            "reconcile": bool(summary.reconcile_available),
        },
        production_ready=summary.production_ready,
        staging_verified=summary.staging_verified,
        offline_only=summary.offline_only,
        tenant_configurable=summary.tenant_configurable,
        platform_configurable=summary.platform_configurable,
        requires_tenant_enablement=True,
    )


def external_source_summary_to_plugin_manifest(summary: Any) -> BusinessPluginManifest:
    provider_name = normalize_external_identifier(summary.provider_name, "provider_name", allow_empty=False)
    contract_version = summary.contract_name or "external_source_provider_v1"
    capabilities = summary.capabilities
    return BusinessPluginManifest(
        plugin_id=f"external_source_{provider_name}",
        name=f"{provider_name} 外部货源插件",
        version="builtin",
        kind=BUSINESS_PLUGIN_KIND_EXTERNAL_SOURCE,
        contract_version=contract_version,
        capabilities={
            "catalog_sync": bool(capabilities.catalog_sync_available),
            "catalog_context": bool(capabilities.catalog_context_available),
            "catalog_product": bool(capabilities.catalog_product_available),
            "catalog_product_context": bool(capabilities.catalog_product_context_available),
            "order": bool(capabilities.order_available),
            "order_context": bool(capabilities.order_context_available),
            "delivery": bool(capabilities.delivery_available),
            "delivery_context": bool(capabilities.delivery_context_available),
            "auto_fulfillment_idempotent": bool(capabilities.auto_fulfillment_idempotent_available),
        },
        production_ready=summary.production_ready,
        staging_verified=summary.staging_verified,
        offline_only=not (summary.production_ready and summary.staging_verified),
        tenant_configurable=True,
        platform_configurable=False,
        requires_tenant_enablement=True,
    )


def list_current_business_plugin_manifests() -> list[BusinessPluginManifest]:
    from app.services.external_sources.registry import list_provider_summaries
    from app.services.payments.configs import list_payment_provider_summaries

    registry = BusinessPluginRegistry()
    for summary in list_payment_provider_summaries():
        registry.register(payment_summary_to_plugin_manifest(summary))
    for summary in list_provider_summaries():
        registry.register(external_source_summary_to_plugin_manifest(summary))
    return registry.list()


def _normalize_capabilities(value: Mapping[str, bool]) -> dict[str, bool]:
    if not isinstance(value, Mapping):
        raise ValueError("capabilities 必须是对象")
    normalized: dict[str, bool] = {}
    for key, enabled in value.items():
        capability = normalize_external_identifier(key, "capability", allow_empty=False)
        if not isinstance(enabled, bool):
            raise ValueError("capability 值必须是布尔值")
        if capability in normalized:
            raise ValueError("capability 不能重复")
        normalized[capability] = enabled
    return normalized


def _normalize_entrypoint(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = _normalize_token_text(value, "entrypoint", max_length=256)
    if not _ENTRYPOINT_PATTERN.fullmatch(text):
        raise ValueError("entrypoint 必须是 module:function 格式")
    return text


def _normalize_display_text(value: object, field_name: str, *, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} 必须是字符串")
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} 不能为空")
    if len(text) > max_length:
        raise ValueError(f"{field_name} 长度不能超过 {max_length}")
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ValueError(f"{field_name} 不能包含控制字符")
    return text


def _normalize_token_text(value: object, field_name: str, *, max_length: int = 64) -> str:
    text = _normalize_display_text(value, field_name, max_length=max_length)
    if not _TEXT_PATTERN.fullmatch(text):
        raise ValueError(f"{field_name} 包含非法字符")
    return text
