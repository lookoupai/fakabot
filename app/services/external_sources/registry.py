from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from app.services.external_sources.base import ExternalSourceProvider
from app.services.external_sources.identifiers import normalize_external_identifier, normalize_provider_name


@dataclass(frozen=True)
class ExternalProviderCapabilities:
    catalog_sync_available: bool
    catalog_context_available: bool
    catalog_product_available: bool
    catalog_product_context_available: bool
    order_available: bool
    order_context_available: bool
    delivery_available: bool
    delivery_context_available: bool
    auto_fulfillment_idempotent_available: bool = False


@dataclass(frozen=True)
class ExternalProviderSummary:
    provider_name: str
    capabilities: ExternalProviderCapabilities
    integration_kind: str = "custom"
    contract_name: Optional[str] = None
    production_ready: bool = False
    staging_verified: bool = False


_providers: Dict[str, ExternalSourceProvider] = {}


def register_provider(provider: ExternalSourceProvider) -> None:
    provider_name = normalize_provider_name(getattr(provider, "provider", None), "provider")
    if provider_name in _providers:
        raise ValueError(f"外部发卡源 provider 已注册：{provider_name}")
    _providers[provider_name] = provider


def get_provider(provider_name: str) -> Optional[ExternalSourceProvider]:
    return _providers.get(normalize_provider_name(provider_name, "provider_name"))


def list_providers() -> List[str]:
    return sorted(_providers.keys())


def get_provider_summary(provider_name: str) -> Optional[ExternalProviderSummary]:
    provider = get_provider(provider_name)
    if provider is None:
        return None
    return describe_provider(provider)


def is_provider_auto_fulfillment_available(provider_name: str) -> bool:
    summary = get_provider_summary(provider_name)
    return bool(summary and summary.capabilities.auto_fulfillment_idempotent_available)


def list_provider_summaries() -> List[ExternalProviderSummary]:
    return [describe_provider(_providers[provider_name]) for provider_name in list_providers()]


def describe_provider(provider: ExternalSourceProvider) -> ExternalProviderSummary:
    provider_name = normalize_provider_name(getattr(provider, "provider", None), "provider")
    integration_kind = normalize_external_identifier(
        getattr(provider, "integration_kind", "custom"),
        "integration_kind",
        allow_empty=False,
    )
    raw_contract_name = getattr(provider, "contract_name", None)
    contract_name = (
        normalize_external_identifier(raw_contract_name, "contract_name", allow_empty=False)
        if raw_contract_name is not None
        else None
    )
    order_available = hasattr(provider, "create_order") and hasattr(provider, "query_order")
    order_context_available = hasattr(provider, "create_order_with_context") and hasattr(
        provider, "query_order_with_context"
    )
    delivery_available = hasattr(provider, "fetch_delivery")
    delivery_context_available = hasattr(provider, "fetch_delivery_with_context")
    auto_fulfillment_opt_in = getattr(provider, "auto_fulfillment_idempotent", False) is True
    return ExternalProviderSummary(
        provider_name=provider_name,
        integration_kind=integration_kind,
        contract_name=contract_name,
        production_ready=getattr(provider, "production_ready", False) is True,
        staging_verified=getattr(provider, "staging_verified", False) is True,
        capabilities=ExternalProviderCapabilities(
            catalog_sync_available=hasattr(provider, "list_products"),
            catalog_context_available=hasattr(provider, "list_products_with_context"),
            catalog_product_available=hasattr(provider, "get_product"),
            catalog_product_context_available=hasattr(provider, "get_product_with_context"),
            order_available=order_available,
            order_context_available=order_context_available,
            delivery_available=delivery_available,
            delivery_context_available=delivery_context_available,
            auto_fulfillment_idempotent_available=auto_fulfillment_opt_in
            and order_context_available
            and delivery_context_available,
        ),
    )
