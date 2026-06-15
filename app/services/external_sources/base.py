from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Protocol, Tuple


@dataclass(frozen=True)
class ExternalProduct:
    provider: str
    external_product_id: str
    name: str
    price: Decimal
    currency: str = "USDT"
    status: str = "on"
    delivery_type: str = "unknown"
    stock_count: Optional[int] = None
    description: Optional[str] = None
    category: Optional[str] = None
    raw_payload: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExternalProductPage:
    products: List[ExternalProduct]
    next_cursor: Optional[str] = None


@dataclass(frozen=True)
class ExternalSourceOperationContext:
    tenant_id: int
    provider_name: str
    source_key: str = ""
    connection_id: Optional[int] = None


@dataclass(frozen=True, kw_only=True)
class ExternalAuthenticatedOperationContext(ExternalSourceOperationContext):
    runtime_auth: Any = field(repr=False, compare=False)

    def __repr__(self) -> str:
        return (
            "ExternalAuthenticatedOperationContext("
            f"tenant_id={self.tenant_id!r}, "
            f"provider_name={self.provider_name!r}, "
            f"source_key={self.source_key!r}, "
            f"connection_id={self.connection_id!r}, "
            "runtime_auth='***'"
            ")"
        )


@dataclass(frozen=True)
class ExternalCatalogSyncContext(ExternalSourceOperationContext):
    pass


@dataclass(frozen=True, kw_only=True)
class ExternalAuthenticatedCatalogSyncContext(ExternalCatalogSyncContext):
    runtime_auth: Any = field(repr=False, compare=False)

    def __repr__(self) -> str:
        return (
            "ExternalAuthenticatedCatalogSyncContext("
            f"tenant_id={self.tenant_id!r}, "
            f"provider_name={self.provider_name!r}, "
            f"source_key={self.source_key!r}, "
            f"connection_id={self.connection_id!r}, "
            "runtime_auth='***'"
            ")"
        )


@dataclass(frozen=True)
class ExternalOrderRequest:
    external_product_id: str
    quantity: int = 1
    out_trade_no: Optional[str] = None
    buyer_reference: Optional[str] = None
    buyer_contact: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExternalOrder:
    provider: str
    external_order_id: str
    external_product_id: str
    status: str
    quantity: int
    amount: Decimal
    currency: str = "USDT"
    delivery_ready: bool = False
    raw_payload: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExternalDelivery:
    provider: str
    external_order_id: str
    delivery_type: str
    items: Tuple[str, ...] = field(default_factory=tuple, repr=False)
    message: Optional[str] = field(default=None, repr=False)
    raw_payload: Dict[str, Any] = field(default_factory=dict)


class ExternalSourceError(Exception):
    pass


class ExternalProviderNotRegisteredError(ValueError):
    pass


class ExternalCatalogProvider(Protocol):
    provider: str

    async def list_products(
        self,
        tenant_id: int,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> ExternalProductPage:
        ...

    async def get_product(self, tenant_id: int, external_product_id: str) -> Optional[ExternalProduct]:
        ...


class ExternalCatalogProviderWithContext(ExternalCatalogProvider, Protocol):
    async def list_products_with_context(
        self,
        context: ExternalCatalogSyncContext,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> ExternalProductPage:
        ...

    async def get_product_with_context(
        self,
        context: ExternalCatalogSyncContext,
        external_product_id: str,
    ) -> Optional[ExternalProduct]:
        ...


class ExternalOrderProvider(Protocol):
    provider: str

    async def create_order(self, tenant_id: int, request: ExternalOrderRequest) -> ExternalOrder:
        ...

    async def query_order(self, tenant_id: int, external_order_id: str) -> Optional[ExternalOrder]:
        ...


class ExternalOrderProviderWithContext(ExternalOrderProvider, Protocol):
    async def create_order_with_context(
        self,
        context: ExternalSourceOperationContext,
        request: ExternalOrderRequest,
    ) -> ExternalOrder:
        ...

    async def query_order_with_context(
        self,
        context: ExternalSourceOperationContext,
        external_order_id: str,
    ) -> Optional[ExternalOrder]:
        ...


class ExternalDeliveryProvider(Protocol):
    provider: str

    async def fetch_delivery(self, tenant_id: int, external_order_id: str) -> Optional[ExternalDelivery]:
        ...


class ExternalDeliveryProviderWithContext(ExternalDeliveryProvider, Protocol):
    async def fetch_delivery_with_context(
        self,
        context: ExternalSourceOperationContext,
        external_order_id: str,
    ) -> Optional[ExternalDelivery]:
        ...


class ExternalSourceProvider(ExternalCatalogProvider, ExternalOrderProvider, ExternalDeliveryProvider, Protocol):
    pass
