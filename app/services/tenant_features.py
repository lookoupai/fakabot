from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repos.tenants import TenantRepository


DEFAULT_TENANT_FEATURE_FLAGS = {
    "self_sale": True,
    "supplier": False,
    "reseller": False,
}

TENANT_FEATURE_DISABLED_MESSAGES = {
    "self_sale": "自营商品售卖功能已关闭",
    "supplier": "供货功能已关闭",
    "reseller": "代理售卖功能已关闭",
}


def build_tenant_feature_flags(
    tenant: Optional[Any],
    tenant_settings: Dict[str, Dict[str, Any]],
) -> Dict[str, bool]:
    flags = dict(DEFAULT_TENANT_FEATURE_FLAGS)
    if tenant is not None:
        flags.update(
            {
                "self_sale": bool(getattr(tenant, "self_sale_enabled", flags["self_sale"])),
                "supplier": bool(getattr(tenant, "supplier_enabled", flags["supplier"])),
                "reseller": bool(getattr(tenant, "reseller_enabled", flags["reseller"])),
            }
        )
    configured_flags = tenant_settings.get("feature_flags", {})
    if isinstance(configured_flags, dict):
        for key in DEFAULT_TENANT_FEATURE_FLAGS:
            if key in configured_flags:
                flags[key] = bool(configured_flags[key])
    return flags


async def load_tenant_feature_flags(
    session: AsyncSession,
    tenant_id: int,
    *,
    tenant: Optional[Any] = None,
    tenant_settings: Optional[Dict[str, Dict[str, Any]]] = None,
    repo: Optional[TenantRepository] = None,
) -> Dict[str, bool]:
    tenant_repo = repo or TenantRepository()
    loaded_tenant = tenant if tenant is not None else await tenant_repo.get_tenant(session, tenant_id)
    loaded_settings = (
        tenant_settings
        if tenant_settings is not None
        else await tenant_repo.get_settings(session, tenant_id)
    )
    return build_tenant_feature_flags(loaded_tenant, loaded_settings)


def tenant_feature_enabled(feature_flags: Dict[str, bool], feature: str) -> bool:
    if feature not in DEFAULT_TENANT_FEATURE_FLAGS:
        raise ValueError("租户功能开关无效")
    return bool(feature_flags.get(feature, DEFAULT_TENANT_FEATURE_FLAGS[feature]))


def tenant_feature_disabled_message(feature: str) -> str:
    if feature not in TENANT_FEATURE_DISABLED_MESSAGES:
        raise ValueError("租户功能开关无效")
    return TENANT_FEATURE_DISABLED_MESSAGES[feature]


def require_tenant_feature(feature_flags: Dict[str, bool], feature: str) -> None:
    if not tenant_feature_enabled(feature_flags, feature):
        raise ValueError(tenant_feature_disabled_message(feature))
