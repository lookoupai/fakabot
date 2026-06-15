from __future__ import annotations

import math
from decimal import Decimal
from typing import Any, Awaitable, Optional, TypeVar, cast

from app.services.external_sources.base import (
    ExternalAuthenticatedOperationContext,
    ExternalDelivery,
    ExternalDeliveryProvider,
    ExternalDeliveryProviderWithContext,
    ExternalOrder,
    ExternalOrderProvider,
    ExternalOrderProviderWithContext,
    ExternalOrderRequest,
    ExternalProviderNotRegisteredError,
    ExternalSourceError,
    ExternalSourceOperationContext,
)
from app.services.external_sources.connections import normalize_external_identifier
from app.services.external_sources.limits import (
    MAX_EXTERNAL_DELIVERY_ITEM_LENGTH,
    MAX_EXTERNAL_DELIVERY_ITEMS,
    MAX_EXTERNAL_DELIVERY_MESSAGE_LENGTH,
)
from app.services.external_sources.raw_payload import reject_sensitive_raw_payload_keys
from app.services.external_sources.registry import get_provider


T = TypeVar("T")


class ExternalOrderOperationService:
    async def create_registered_order(
        self,
        *,
        tenant_id: int,
        provider_name: str,
        request: ExternalOrderRequest,
        source_key: str = "",
        connection_id: Optional[int] = None,
        runtime_auth: object | None = None,
    ) -> ExternalOrder:
        _validate_tenant_id(tenant_id)
        _validate_connection_id(connection_id)
        request = _normalize_order_request(request)
        _validate_source_key(source_key)
        provider = _get_registered_provider(provider_name)
        context = _operation_context(
            tenant_id=tenant_id,
            provider_name=provider.provider,
            source_key=source_key,
            connection_id=connection_id,
            runtime_auth=runtime_auth,
        )
        if hasattr(provider, "create_order_with_context"):
            context_provider = cast(ExternalOrderProviderWithContext, provider)
            order = await _call_provider_operation(
                context_provider.create_order_with_context(context=context, request=request),
                "外部发卡源创建订单失败",
            )
            return _validate_external_order_result(
                order,
                expected_provider_name=context.provider_name,
                expected_external_product_id=request.external_product_id.strip(),
                expected_quantity=request.quantity,
            )
        if not hasattr(provider, "create_order"):
            raise ExternalSourceError("外部发卡源 provider 不支持创建订单")
        order_provider = cast(ExternalOrderProvider, provider)
        order = await _call_provider_operation(
            order_provider.create_order(tenant_id=tenant_id, request=request),
            "外部发卡源创建订单失败",
        )
        return _validate_external_order_result(
            order,
            expected_provider_name=context.provider_name,
            expected_external_product_id=request.external_product_id.strip(),
            expected_quantity=request.quantity,
        )

    async def query_registered_order(
        self,
        *,
        tenant_id: int,
        provider_name: str,
        external_order_id: str,
        source_key: str = "",
        connection_id: Optional[int] = None,
        runtime_auth: object | None = None,
    ) -> Optional[ExternalOrder]:
        _validate_tenant_id(tenant_id)
        _validate_connection_id(connection_id)
        external_order_id = _normalize_external_order_id(external_order_id)
        _validate_source_key(source_key)
        provider = _get_registered_provider(provider_name)
        context = _operation_context(
            tenant_id=tenant_id,
            provider_name=provider.provider,
            source_key=source_key,
            connection_id=connection_id,
            runtime_auth=runtime_auth,
        )
        if hasattr(provider, "query_order_with_context"):
            context_provider = cast(ExternalOrderProviderWithContext, provider)
            order = await _call_provider_operation(
                context_provider.query_order_with_context(
                    context=context,
                    external_order_id=external_order_id,
                ),
                "外部发卡源查询订单失败",
            )
            return _validate_optional_external_order_result(
                order,
                expected_provider_name=context.provider_name,
                expected_external_order_id=external_order_id,
            )
        if not hasattr(provider, "query_order"):
            raise ExternalSourceError("外部发卡源 provider 不支持查询订单")
        order_provider = cast(ExternalOrderProvider, provider)
        order = await _call_provider_operation(
            order_provider.query_order(tenant_id=tenant_id, external_order_id=external_order_id),
            "外部发卡源查询订单失败",
        )
        return _validate_optional_external_order_result(
            order,
            expected_provider_name=context.provider_name,
            expected_external_order_id=external_order_id,
        )

    async def fetch_registered_delivery(
        self,
        *,
        tenant_id: int,
        provider_name: str,
        external_order_id: str,
        source_key: str = "",
        connection_id: Optional[int] = None,
        runtime_auth: object | None = None,
    ) -> Optional[ExternalDelivery]:
        _validate_tenant_id(tenant_id)
        _validate_connection_id(connection_id)
        external_order_id = _normalize_external_order_id(external_order_id)
        _validate_source_key(source_key)
        provider = _get_registered_provider(provider_name)
        context = _operation_context(
            tenant_id=tenant_id,
            provider_name=provider.provider,
            source_key=source_key,
            connection_id=connection_id,
            runtime_auth=runtime_auth,
        )
        if hasattr(provider, "fetch_delivery_with_context"):
            context_provider = cast(ExternalDeliveryProviderWithContext, provider)
            delivery = await _call_provider_operation(
                context_provider.fetch_delivery_with_context(
                    context=context,
                    external_order_id=external_order_id,
                ),
                "外部发卡源获取发货失败",
            )
            return _validate_optional_external_delivery_result(
                delivery,
                expected_provider_name=context.provider_name,
                expected_external_order_id=external_order_id,
            )
        if not hasattr(provider, "fetch_delivery"):
            raise ExternalSourceError("外部发卡源 provider 不支持获取发货")
        delivery_provider = cast(ExternalDeliveryProvider, provider)
        delivery = await _call_provider_operation(
            delivery_provider.fetch_delivery(tenant_id=tenant_id, external_order_id=external_order_id),
            "外部发卡源获取发货失败",
        )
        return _validate_optional_external_delivery_result(
            delivery,
            expected_provider_name=context.provider_name,
            expected_external_order_id=external_order_id,
        )


def _get_registered_provider(provider_name: str):
    normalized_provider_name = normalize_external_identifier(provider_name, "provider_name", allow_empty=False)
    provider = get_provider(normalized_provider_name or "")
    if provider is None:
        raise ExternalProviderNotRegisteredError("外部发卡源 provider 未注册")
    return provider


async def _call_provider_operation(awaitable: Awaitable[T], failure_message: str) -> T:
    try:
        return await awaitable
    except ExternalSourceError:
        raise
    except Exception as exc:
        raise ExternalSourceError(failure_message) from exc


def _validate_tenant_id(tenant_id: int) -> None:
    if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id <= 0:
        raise ValueError("tenant_id 必须为正整数")


def _validate_connection_id(connection_id: Optional[int]) -> None:
    if connection_id is not None and (
        not isinstance(connection_id, int) or isinstance(connection_id, bool) or connection_id <= 0
    ):
        raise ValueError("connection_id 必须为正整数")


def _normalize_order_request(request: ExternalOrderRequest) -> ExternalOrderRequest:
    if not isinstance(request, ExternalOrderRequest):
        raise ValueError("request 必须是 ExternalOrderRequest")
    if not isinstance(request.external_product_id, str):
        raise ValueError("external_product_id 必须是字符串")
    external_product_id = request.external_product_id.strip()
    if not external_product_id:
        raise ValueError("external_product_id 不能为空")
    if len(external_product_id) > 128:
        raise ValueError("external_product_id 长度不能超过 128")
    if _contains_control_character(external_product_id):
        raise ValueError("external_product_id 不能包含控制字符")
    if not isinstance(request.quantity, int) or isinstance(request.quantity, bool) or request.quantity <= 0:
        raise ValueError("quantity 必须为正整数")
    return ExternalOrderRequest(
        external_product_id=external_product_id,
        quantity=request.quantity,
        out_trade_no=_normalize_optional_request_text(request.out_trade_no, "out_trade_no", max_length=96),
        buyer_reference=_normalize_optional_request_text(
            request.buyer_reference,
            "buyer_reference",
            max_length=128,
        ),
        buyer_contact=_normalize_optional_request_text(request.buyer_contact, "buyer_contact", max_length=256),
        metadata=_normalize_request_metadata(request.metadata),
    )


def _normalize_optional_request_text(value: Optional[str], field_name: str, *, max_length: int) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} 必须是字符串")
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} 长度不能超过 {max_length}")
    if _contains_control_character(normalized):
        raise ValueError(f"{field_name} 不能包含控制字符")
    return normalized


def _normalize_request_metadata(metadata: dict[str, Any], *, depth: int = 0) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        raise ValueError("metadata 必须是字典")
    if depth > 4:
        raise ValueError("metadata 嵌套层级不能超过 4")
    if len(metadata) > 50:
        raise ValueError("metadata 字段数量不能超过 50")
    normalized: dict[str, Any] = {}
    for key, value in metadata.items():
        if not isinstance(key, str):
            raise ValueError("metadata 字段名必须是字符串")
        normalized_key = key.strip()
        if not normalized_key:
            raise ValueError("metadata 字段名不能为空")
        if len(normalized_key) > 128:
            raise ValueError("metadata 字段名长度不能超过 128")
        if _contains_control_character(normalized_key):
            raise ValueError("metadata 字段名不能包含控制字符")
        if normalized_key in normalized:
            raise ValueError("metadata 字段名重复")
        normalized[normalized_key] = _normalize_metadata_value(value, depth=depth + 1)
    reject_sensitive_raw_payload_keys(
        normalized,
        "订单请求 metadata",
        message="外部发卡源订单请求 metadata 包含敏感字段",
    )
    return normalized


def _normalize_metadata_value(value: Any, *, depth: int) -> Any:
    if depth > 4:
        raise ValueError("metadata 嵌套层级不能超过 4")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("metadata 数字值必须是有限数")
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if len(normalized) > 512:
            raise ValueError("metadata 字符串值长度不能超过 512")
        if _contains_control_character(normalized):
            raise ValueError("metadata 字符串值不能包含控制字符")
        return normalized
    if isinstance(value, (list, tuple)):
        if len(value) > 50:
            raise ValueError("metadata 数组长度不能超过 50")
        return [_normalize_metadata_value(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        return _normalize_request_metadata(value, depth=depth)
    raise ValueError("metadata 字段值必须是 JSON 兼容类型")


def _contains_control_character(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def _validate_source_key(source_key: str) -> None:
    normalize_external_identifier(source_key, "source_key", allow_empty=True)


def _normalize_external_order_id(external_order_id: str) -> str:
    if not isinstance(external_order_id, str):
        raise ValueError("external_order_id 必须是字符串")
    normalized = external_order_id.strip()
    if not normalized:
        raise ValueError("external_order_id 不能为空")
    if len(normalized) > 128:
        raise ValueError("external_order_id 长度不能超过 128")
    if _contains_control_character(normalized):
        raise ValueError("external_order_id 不能包含控制字符")
    return normalized


def _validate_optional_external_order_result(
    order: Optional[ExternalOrder],
    *,
    expected_provider_name: str,
    expected_external_order_id: Optional[str] = None,
) -> Optional[ExternalOrder]:
    if order is None:
        return None
    return _validate_external_order_result(
        order,
        expected_provider_name=expected_provider_name,
        expected_external_order_id=expected_external_order_id,
    )


def _validate_external_order_result(
    order: ExternalOrder,
    *,
    expected_provider_name: str,
    expected_external_product_id: Optional[str] = None,
    expected_external_order_id: Optional[str] = None,
    expected_quantity: Optional[int] = None,
) -> ExternalOrder:
    if not isinstance(order, ExternalOrder):
        raise ExternalSourceError("外部发卡源返回订单结果无效")
    if not isinstance(order.provider, str):
        raise ExternalSourceError("外部发卡源返回订单 provider 无效")
    try:
        returned_provider = normalize_external_identifier(order.provider, "provider", allow_empty=False)
    except ValueError as exc:
        raise ExternalSourceError("外部发卡源返回订单 provider 无效") from exc
    if returned_provider != expected_provider_name:
        raise ExternalSourceError("外部发卡源返回订单 provider 不匹配")
    returned_order_id = _normalize_provider_order_id(order.external_order_id)
    if expected_external_order_id is not None and returned_order_id != expected_external_order_id:
        raise ExternalSourceError("外部发卡源返回订单 ID 不匹配")
    if not isinstance(order.external_product_id, str):
        raise ExternalSourceError("外部发卡源返回商品 ID 无效")
    returned_product_id = order.external_product_id.strip()
    if not returned_product_id:
        raise ExternalSourceError("外部发卡源返回商品 ID 为空")
    if expected_external_product_id is not None and returned_product_id != expected_external_product_id:
        raise ExternalSourceError("外部发卡源返回商品 ID 不匹配")
    if not isinstance(order.status, str):
        raise ExternalSourceError("外部发卡源返回订单状态无效")
    returned_status = order.status.strip()
    if not returned_status:
        raise ExternalSourceError("外部发卡源返回订单状态为空")
    if not isinstance(order.quantity, int) or isinstance(order.quantity, bool) or order.quantity <= 0:
        raise ExternalSourceError("外部发卡源返回订单数量无效")
    if expected_quantity is not None and order.quantity != expected_quantity:
        raise ExternalSourceError("外部发卡源返回订单数量不匹配")
    if not isinstance(order.amount, Decimal) or not order.amount.is_finite() or order.amount < Decimal("0"):
        raise ExternalSourceError("外部发卡源返回订单金额无效")
    if not isinstance(order.currency, str):
        raise ExternalSourceError("外部发卡源返回订单币种无效")
    returned_currency = order.currency.strip()
    if not returned_currency:
        raise ExternalSourceError("外部发卡源返回订单币种为空")
    if not isinstance(order.delivery_ready, bool):
        raise ExternalSourceError("外部发卡源返回订单发货状态无效")
    if not isinstance(order.raw_payload, dict):
        raise ExternalSourceError("外部发卡源返回订单原始载荷无效")
    reject_sensitive_raw_payload_keys(order.raw_payload, "订单", error_type=ExternalSourceError)
    return ExternalOrder(
        provider=returned_provider,
        external_order_id=returned_order_id,
        external_product_id=returned_product_id,
        status=returned_status,
        quantity=order.quantity,
        amount=order.amount,
        currency=returned_currency,
        delivery_ready=order.delivery_ready,
        raw_payload=order.raw_payload,
    )


def _validate_optional_external_delivery_result(
    delivery: Optional[ExternalDelivery],
    *,
    expected_provider_name: str,
    expected_external_order_id: str,
) -> Optional[ExternalDelivery]:
    if delivery is None:
        return None
    if not isinstance(delivery, ExternalDelivery):
        raise ExternalSourceError("外部发卡源返回发货结果无效")
    if not isinstance(delivery.provider, str):
        raise ExternalSourceError("外部发卡源返回发货 provider 无效")
    try:
        returned_provider = normalize_external_identifier(delivery.provider, "provider", allow_empty=False)
    except ValueError as exc:
        raise ExternalSourceError("外部发卡源返回发货 provider 无效") from exc
    if returned_provider != expected_provider_name:
        raise ExternalSourceError("外部发卡源返回发货 provider 不匹配")
    returned_order_id = _normalize_provider_order_id(delivery.external_order_id)
    if returned_order_id != expected_external_order_id:
        raise ExternalSourceError("外部发卡源返回发货订单 ID 不匹配")
    if not isinstance(delivery.delivery_type, str):
        raise ExternalSourceError("外部发卡源返回发货类型无效")
    delivery_type = delivery.delivery_type.strip()
    if not delivery_type:
        raise ExternalSourceError("外部发卡源返回发货类型为空")
    if not isinstance(delivery.items, (tuple, list)):
        raise ExternalSourceError("外部发卡源返回发货条目无效")
    if delivery.message is not None and not isinstance(delivery.message, str):
        raise ExternalSourceError("外部发卡源返回发货消息无效")
    message = delivery.message.strip() if delivery.message is not None else None
    if message == "":
        message = None
    if message is not None and len(message) > MAX_EXTERNAL_DELIVERY_MESSAGE_LENGTH:
        raise ExternalSourceError("外部发卡源返回发货消息过长")
    if not delivery.items and message is None:
        raise ExternalSourceError("外部发卡源返回发货内容为空")
    if len(delivery.items) > MAX_EXTERNAL_DELIVERY_ITEMS:
        raise ExternalSourceError("外部发卡源返回发货条目过多")
    items: list[str] = []
    for item in delivery.items:
        if not isinstance(item, str):
            raise ExternalSourceError("外部发卡源返回发货条目无效")
        normalized_item = item.strip()
        if not normalized_item:
            raise ExternalSourceError("外部发卡源返回发货条目无效")
        if len(normalized_item) > MAX_EXTERNAL_DELIVERY_ITEM_LENGTH:
            raise ExternalSourceError("外部发卡源返回发货条目过长")
        items.append(normalized_item)
    if not items and message is None:
        raise ExternalSourceError("外部发卡源返回发货条目无效")
    if not isinstance(delivery.raw_payload, dict):
        raise ExternalSourceError("外部发卡源返回发货原始载荷无效")
    reject_sensitive_raw_payload_keys(delivery.raw_payload, "发货", error_type=ExternalSourceError)
    return ExternalDelivery(
        provider=returned_provider,
        external_order_id=returned_order_id,
        delivery_type=delivery_type,
        items=tuple(items),
        message=message,
        raw_payload=delivery.raw_payload,
    )


def _normalize_provider_order_id(external_order_id: str) -> str:
    if not isinstance(external_order_id, str):
        raise ExternalSourceError("外部发卡源返回订单 ID 无效")
    try:
        return _normalize_external_order_id(external_order_id)
    except ValueError as exc:
        raise ExternalSourceError("外部发卡源返回订单 ID 为空") from exc


def _operation_context(
    *,
    tenant_id: int,
    provider_name: str,
    source_key: str = "",
    connection_id: Optional[int] = None,
    runtime_auth: object | None = None,
) -> ExternalSourceOperationContext:
    normalized_provider_name = normalize_external_identifier(provider_name, "provider_name", allow_empty=False) or ""
    normalized_source_key = normalize_external_identifier(source_key, "source_key", allow_empty=True) or ""
    if runtime_auth is None:
        return ExternalSourceOperationContext(
            tenant_id=tenant_id,
            provider_name=normalized_provider_name,
            source_key=normalized_source_key,
            connection_id=connection_id,
        )
    _validate_runtime_auth(
        runtime_auth,
        tenant_id=tenant_id,
        provider_name=normalized_provider_name,
        source_key=normalized_source_key,
        connection_id=connection_id,
    )
    return ExternalAuthenticatedOperationContext(
        tenant_id=tenant_id,
        provider_name=normalized_provider_name,
        source_key=normalized_source_key,
        connection_id=connection_id,
        runtime_auth=runtime_auth,
    )


def _validate_runtime_auth(
    runtime_auth: object,
    *,
    tenant_id: int,
    provider_name: str,
    source_key: str,
    connection_id: Optional[int],
) -> None:
    if connection_id is None:
        raise ValueError("runtime_auth 需要 connection_id")
    if getattr(runtime_auth, "tenant_id", None) != tenant_id:
        raise ValueError("runtime_auth tenant_id 与请求不一致")
    if getattr(runtime_auth, "connection_id", None) != connection_id:
        raise ValueError("runtime_auth connection_id 与请求不一致")
    if getattr(runtime_auth, "provider_name", None) != provider_name:
        raise ValueError("runtime_auth provider_name 与请求不一致")
    if getattr(runtime_auth, "source_key", None) != source_key:
        raise ValueError("runtime_auth source_key 与请求不一致")
