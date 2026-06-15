from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Protocol, cast

from app.services.external_sources.base import (
    ExternalAuthenticatedOperationContext,
    ExternalDelivery,
    ExternalDeliveryProviderWithContext,
    ExternalOrder,
    ExternalOrderProviderWithContext,
    ExternalOrderRequest,
    ExternalSourceOperationContext,
)
from app.services.external_sources.identifiers import normalize_external_identifier


class ExternalProviderIdempotencyProbeProvider(
    ExternalOrderProviderWithContext,
    ExternalDeliveryProviderWithContext,
    Protocol,
):
    pass


@dataclass(frozen=True)
class ExternalProviderOfflineIdempotencyProof:
    provider_name: str
    source_key: str
    connection_id: Optional[int]
    out_trade_no: str
    external_product_id: str
    external_order_id: str
    duplicate_external_order_id: str
    query_status: Optional[str]
    delivery_ready: bool
    delivery_item_count: int

    @property
    def idempotent(self) -> bool:
        return self.external_order_id == self.duplicate_external_order_id


class ExternalProviderOfflineIdempotencyProbe:
    """Probe fixture-backed provider idempotency without enabling auto fulfillment."""

    async def prove(
        self,
        *,
        provider: ExternalProviderIdempotencyProbeProvider,
        tenant_id: int,
        request: ExternalOrderRequest,
        source_key: str = "",
        connection_id: Optional[int] = None,
        runtime_auth: object | None = None,
    ) -> ExternalProviderOfflineIdempotencyProof:
        _validate_tenant_id(tenant_id)
        _validate_connection_id(connection_id)
        normalized_provider = normalize_external_identifier(
            getattr(provider, "provider", None),
            "provider",
            allow_empty=False,
        )
        normalized_source_key = _normalize_source_key(source_key)
        normalized_request = _normalize_request(request)
        context = _operation_context(
            tenant_id=tenant_id,
            provider_name=normalized_provider,
            source_key=normalized_source_key,
            connection_id=connection_id,
            runtime_auth=runtime_auth,
        )
        context_provider = cast(ExternalProviderIdempotencyProbeProvider, provider)
        first_order = await context_provider.create_order_with_context(context=context, request=normalized_request)
        duplicate_order = await context_provider.create_order_with_context(context=context, request=normalized_request)
        _validate_duplicate_order(first_order, duplicate_order)
        query_order = await context_provider.query_order_with_context(
            context=context,
            external_order_id=first_order.external_order_id,
        )
        if query_order is not None:
            _validate_query_order(first_order, query_order)
        delivery = await context_provider.fetch_delivery_with_context(
            context=context,
            external_order_id=first_order.external_order_id,
        )
        _validate_delivery(first_order, delivery)
        return ExternalProviderOfflineIdempotencyProof(
            provider_name=normalized_provider,
            source_key=normalized_source_key,
            connection_id=connection_id,
            out_trade_no=normalized_request.out_trade_no or "",
            external_product_id=first_order.external_product_id,
            external_order_id=first_order.external_order_id,
            duplicate_external_order_id=duplicate_order.external_order_id,
            query_status=query_order.status if query_order is not None else None,
            delivery_ready=delivery is not None,
            delivery_item_count=len(delivery.items) if delivery is not None else 0,
        )


def _operation_context(
    *,
    tenant_id: int,
    provider_name: str,
    source_key: str,
    connection_id: Optional[int],
    runtime_auth: object | None,
) -> ExternalSourceOperationContext:
    if runtime_auth is None:
        return ExternalSourceOperationContext(
            tenant_id=tenant_id,
            provider_name=provider_name,
            source_key=source_key,
            connection_id=connection_id,
        )
    return ExternalAuthenticatedOperationContext(
        tenant_id=tenant_id,
        provider_name=provider_name,
        source_key=source_key,
        connection_id=connection_id,
        runtime_auth=runtime_auth,
    )


def _normalize_request(request: ExternalOrderRequest) -> ExternalOrderRequest:
    if not isinstance(request, ExternalOrderRequest):
        raise ValueError("request 必须是 ExternalOrderRequest")
    external_product_id = _required_text(request.external_product_id, "external_product_id", max_length=128)
    out_trade_no = _required_text(request.out_trade_no, "out_trade_no", max_length=96)
    if not isinstance(request.quantity, int) or isinstance(request.quantity, bool) or request.quantity <= 0:
        raise ValueError("quantity 必须为正整数")
    if request.quantity != 1:
        raise ValueError("离线幂等证明只支持单件外部文本商品订单")
    return ExternalOrderRequest(
        external_product_id=external_product_id,
        quantity=request.quantity,
        out_trade_no=out_trade_no,
        buyer_reference=_optional_text(request.buyer_reference, "buyer_reference", max_length=128),
        buyer_contact=_optional_text(request.buyer_contact, "buyer_contact", max_length=128),
        metadata=dict(request.metadata or {}),
    )


def _validate_duplicate_order(first_order: ExternalOrder, duplicate_order: ExternalOrder) -> None:
    _validate_order(first_order)
    _validate_order(duplicate_order)
    compared_fields = (
        "provider",
        "external_order_id",
        "external_product_id",
        "quantity",
        "amount",
        "currency",
    )
    for field_name in compared_fields:
        if getattr(first_order, field_name) != getattr(duplicate_order, field_name):
            raise ValueError("外部源重复建单未证明按 out_trade_no 幂等")


def _validate_query_order(first_order: ExternalOrder, query_order: ExternalOrder) -> None:
    _validate_order(query_order)
    if query_order.provider != first_order.provider or query_order.external_order_id != first_order.external_order_id:
        raise ValueError("外部源查单结果与建单结果不一致")
    if query_order.external_product_id != first_order.external_product_id:
        raise ValueError("外部源查单商品与建单商品不一致")


def _validate_delivery(first_order: ExternalOrder, delivery: ExternalDelivery | None) -> None:
    if delivery is None:
        return
    if delivery.provider != first_order.provider or delivery.external_order_id != first_order.external_order_id:
        raise ValueError("外部源发货结果与建单结果不一致")


def _validate_order(order: ExternalOrder) -> None:
    if not isinstance(order, ExternalOrder):
        raise ValueError("外部源订单结果无效")
    _required_text(order.provider, "provider", max_length=64)
    _required_text(order.external_order_id, "external_order_id", max_length=128)
    _required_text(order.external_product_id, "external_product_id", max_length=128)
    if not isinstance(order.quantity, int) or isinstance(order.quantity, bool) or order.quantity <= 0:
        raise ValueError("外部源订单数量无效")
    if not isinstance(order.amount, Decimal) or not order.amount.is_finite() or order.amount <= 0:
        raise ValueError("外部源订单金额无效")
    _required_text(order.currency, "currency", max_length=16)


def _validate_tenant_id(tenant_id: int) -> None:
    if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id <= 0:
        raise ValueError("tenant_id 必须为正整数")


def _validate_connection_id(connection_id: Optional[int]) -> None:
    if connection_id is not None and (
        not isinstance(connection_id, int) or isinstance(connection_id, bool) or connection_id <= 0
    ):
        raise ValueError("connection_id 必须为正整数")


def _normalize_source_key(value: str) -> str:
    return _optional_text(value, "source_key", max_length=128) or ""


def _required_text(value: object, field_name: str, *, max_length: int) -> str:
    normalized = _optional_text(value, field_name, max_length=max_length)
    if normalized is None:
        raise ValueError(f"{field_name} 不能为空")
    return normalized


def _optional_text(value: object, field_name: str, *, max_length: int) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} 必须是字符串")
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} 长度不能超过 {max_length}")
    if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
        raise ValueError(f"{field_name} 不能包含控制字符")
    return normalized
