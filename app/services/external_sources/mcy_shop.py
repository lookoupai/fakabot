from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from ipaddress import ip_address
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

from app.services.external_sources.base import (
    ExternalCatalogSyncContext,
    ExternalDelivery,
    ExternalOrder,
    ExternalOrderRequest,
    ExternalProduct,
    ExternalProductPage,
    ExternalSourceError,
    ExternalSourceOperationContext,
)
from app.services.external_sources.http import (
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    ExternalHttpClient,
    ExternalHttpRequest,
    ExternalHttpTransport,
    ExternalHttpxTransport,
    build_external_http_url,
    normalize_external_http_headers,
    normalize_external_http_timeout,
)
from app.services.external_sources.limits import (
    MAX_EXTERNAL_CATALOG_PRODUCTS_PER_PAGE,
    MAX_EXTERNAL_DELIVERY_ITEM_LENGTH,
    MAX_EXTERNAL_DELIVERY_ITEMS,
    MAX_EXTERNAL_DELIVERY_MESSAGE_LENGTH,
)
from app.services.external_sources.raw_payload import reject_sensitive_raw_payload_keys


MCY_SHOP_PROVIDER = "mcy_shop"
MCY_SHOP_OFFLINE_FIXTURE_CONTRACT = "mcy_shop_offline_fixture_v1"
ALLOWED_MCY_SHOP_CREDENTIAL_FIELDS = {
    "base_url",
    "api_key",
    "timeout_seconds",
}
MCY_SHOP_OFFLINE_FIXTURE_ALLOWED_HOSTS = {"localhost"}
MCY_SHOP_OFFLINE_FIXTURE_ALLOWED_HOST_SUFFIXES = (".localhost", ".test", ".example", ".invalid")


@dataclass(frozen=True)
class McyShopCredentials:
    base_url: str
    api_key: str = field(repr=False)
    timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS


class McyShopExternalSourceProvider:
    provider = MCY_SHOP_PROVIDER
    integration_kind = "offline_fixture"
    contract_name = MCY_SHOP_OFFLINE_FIXTURE_CONTRACT
    production_ready = False
    staging_verified = False
    auto_fulfillment_idempotent = False

    def __init__(self, client: Optional[ExternalHttpClient] = None) -> None:
        self.client = client or ExternalHttpClient(ExternalHttpxTransport())

    def validate_connection_credentials(self, credentials: Mapping[str, str]) -> None:
        validate_mcy_shop_credentials(credentials)

    async def list_products(
        self,
        tenant_id: int,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> ExternalProductPage:
        raise ExternalSourceError("mcy_shop provider 需要 runtime_auth；当前仅提供离线 fixture 合同")

    async def get_product(self, tenant_id: int, external_product_id: str) -> Optional[ExternalProduct]:
        raise ExternalSourceError("mcy_shop provider 需要 runtime_auth；当前仅提供离线 fixture 合同")

    async def list_products_with_context(
        self,
        context: ExternalCatalogSyncContext,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> ExternalProductPage:
        credentials = _credentials_from_context(context)
        payload = await self.client.request_json(
            ExternalHttpRequest(
                method="GET",
                url=build_external_http_url(
                    credentials.base_url,
                    path_segments=("mcy-shop-fixture", "products"),
                    query={"cursor": cursor, "limit": limit},
                ),
                headers=_headers(credentials, context.source_key),
                timeout_seconds=credentials.timeout_seconds,
            )
        )
        data = _dict_payload(payload, "目录响应")
        products = _list_payload(
            data.get("items") or data.get("products"),
            "目录商品列表",
            max_items=MAX_EXTERNAL_CATALOG_PRODUCTS_PER_PAGE,
        )
        next_cursor = _optional_text(data.get("next_cursor"), "next_cursor", max_length=512)
        return ExternalProductPage(
            products=[_product_from_payload(product) for product in products],
            next_cursor=next_cursor,
        )

    async def get_product_with_context(
        self,
        context: ExternalCatalogSyncContext,
        external_product_id: str,
    ) -> Optional[ExternalProduct]:
        credentials = _credentials_from_context(context)
        payload = await self.client.request_json(
            ExternalHttpRequest(
                method="GET",
                url=build_external_http_url(
                    credentials.base_url,
                    path_segments=("mcy-shop-fixture", "products", external_product_id),
                ),
                headers=_headers(credentials, context.source_key),
                timeout_seconds=credentials.timeout_seconds,
            )
        )
        if payload is None:
            return None
        return _product_from_payload(_dict_payload(payload, "商品响应"))

    async def create_order(self, tenant_id: int, request: ExternalOrderRequest) -> ExternalOrder:
        raise ExternalSourceError("mcy_shop provider 需要 runtime_auth；当前仅提供离线 fixture 合同")

    async def query_order(self, tenant_id: int, external_order_id: str) -> Optional[ExternalOrder]:
        raise ExternalSourceError("mcy_shop provider 需要 runtime_auth；当前仅提供离线 fixture 合同")

    async def fetch_delivery(self, tenant_id: int, external_order_id: str) -> Optional[ExternalDelivery]:
        raise ExternalSourceError("mcy_shop provider 需要 runtime_auth；当前仅提供离线 fixture 合同")

    async def create_order_with_context(
        self,
        context: ExternalSourceOperationContext,
        request: ExternalOrderRequest,
    ) -> ExternalOrder:
        credentials = _credentials_from_context(context)
        payload = await self.client.request_json(
            ExternalHttpRequest(
                method="POST",
                url=build_external_http_url(
                    credentials.base_url,
                    path_segments=("mcy-shop-fixture", "orders"),
                ),
                headers=_headers(credentials, context.source_key),
                json_payload={
                    "external_product_id": request.external_product_id,
                    "quantity": request.quantity,
                    "out_trade_no": request.out_trade_no,
                    "buyer_reference": request.buyer_reference,
                    "buyer_contact": request.buyer_contact,
                    "metadata": request.metadata,
                },
                timeout_seconds=credentials.timeout_seconds,
            )
        )
        return _order_from_payload(_dict_payload(payload, "建单响应"))

    async def query_order_with_context(
        self,
        context: ExternalSourceOperationContext,
        external_order_id: str,
    ) -> Optional[ExternalOrder]:
        credentials = _credentials_from_context(context)
        payload = await self.client.request_json(
            ExternalHttpRequest(
                method="GET",
                url=build_external_http_url(
                    credentials.base_url,
                    path_segments=("mcy-shop-fixture", "orders", external_order_id),
                ),
                headers=_headers(credentials, context.source_key),
                timeout_seconds=credentials.timeout_seconds,
            )
        )
        if payload is None:
            return None
        return _order_from_payload(_dict_payload(payload, "查单响应"))

    async def fetch_delivery_with_context(
        self,
        context: ExternalSourceOperationContext,
        external_order_id: str,
    ) -> Optional[ExternalDelivery]:
        credentials = _credentials_from_context(context)
        payload = await self.client.request_json(
            ExternalHttpRequest(
                method="GET",
                url=build_external_http_url(
                    credentials.base_url,
                    path_segments=("mcy-shop-fixture", "deliveries", external_order_id),
                ),
                headers=_headers(credentials, context.source_key),
                timeout_seconds=credentials.timeout_seconds,
            )
        )
        if payload is None:
            return None
        return _delivery_from_payload(_dict_payload(payload, "发货响应"))


def create_mcy_shop_provider(transport: Optional[ExternalHttpTransport] = None) -> McyShopExternalSourceProvider:
    client = ExternalHttpClient(transport or ExternalHttpxTransport())
    return McyShopExternalSourceProvider(client)


def validate_mcy_shop_credentials(credentials: Mapping[str, str]) -> McyShopCredentials:
    try:
        _reject_unknown_credential_fields(credentials)
        parsed = _credentials_from_mapping(credentials)
        _ensure_mcy_shop_fixture_base_url(parsed.base_url)
        return parsed
    except (ExternalSourceError, ValueError) as exc:
        raise ValueError("mcy_shop 凭据无效") from exc


def _credentials_from_context(context: object) -> McyShopCredentials:
    runtime_auth = getattr(context, "runtime_auth", None)
    credentials = getattr(runtime_auth, "credentials", None) if runtime_auth is not None else None
    if not isinstance(credentials, Mapping):
        raise ExternalSourceError("mcy_shop provider 缺少运行时凭据")
    try:
        _reject_unknown_credential_fields(credentials)
        parsed = _credentials_from_mapping(credentials)
        _ensure_mcy_shop_fixture_base_url(parsed.base_url)
        return parsed
    except (ExternalSourceError, ValueError) as exc:
        raise ExternalSourceError("mcy_shop provider 凭据无效") from exc


def _credentials_from_mapping(credentials: Mapping[str, Any]) -> McyShopCredentials:
    return McyShopCredentials(
        base_url=_required_text(credentials.get("base_url"), "base_url", max_length=2048),
        api_key=_required_text(credentials.get("api_key"), "api_key", max_length=4096),
        timeout_seconds=_optional_timeout(credentials.get("timeout_seconds")),
    )


def _headers(credentials: McyShopCredentials, source_key: str) -> dict[str, str]:
    values = {
        "X-API-Key": credentials.api_key,
        "X-Fakabot-External-Contract": MCY_SHOP_OFFLINE_FIXTURE_CONTRACT,
    }
    if source_key:
        values["X-Source-Key"] = source_key
    return normalize_external_http_headers(values)


def _reject_unknown_credential_fields(credentials: Mapping[str, Any]) -> None:
    unknown_fields = set(credentials) - ALLOWED_MCY_SHOP_CREDENTIAL_FIELDS
    if unknown_fields:
        raise ValueError("mcy_shop 凭据字段不支持")


def _ensure_mcy_shop_fixture_base_url(base_url: str) -> None:
    normalized_url = build_external_http_url(base_url)
    host = (urlsplit(normalized_url).hostname or "").lower()
    if _is_mcy_shop_fixture_host(host):
        return
    raise ValueError("mcy_shop 离线 fixture 只允许本地或保留测试主机")


def _is_mcy_shop_fixture_host(host: str) -> bool:
    if host in MCY_SHOP_OFFLINE_FIXTURE_ALLOWED_HOSTS:
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        pass
    return host.endswith(MCY_SHOP_OFFLINE_FIXTURE_ALLOWED_HOST_SUFFIXES)


def _product_from_payload(payload: Mapping[str, Any]) -> ExternalProduct:
    reject_sensitive_raw_payload_keys(dict(payload), "mcy_shop 商品", error_type=ExternalSourceError)
    external_id = _required_text(
        _first_present(payload, "external_product_id", "product_id", "id"),
        "商品 ID",
        max_length=128,
    )
    status = _optional_text(_first_present(payload, "status", "state"), "商品状态", max_length=32) or "on"
    return ExternalProduct(
        provider=MCY_SHOP_PROVIDER,
        external_product_id=external_id,
        name=_required_text(_first_present(payload, "name", "title"), "商品名称", max_length=255),
        price=_required_decimal(_first_present(payload, "price", "unit_price"), "商品价格"),
        currency=_optional_text(payload.get("currency"), "币种", max_length=16) or "USDT",
        status=status,
        delivery_type=_optional_text(
            _first_present(payload, "delivery_type", "delivery_kind"),
            "发货类型",
            max_length=32,
        )
        or "card_pool",
        stock_count=_optional_int(_first_present(payload, "stock_count", "inventory"), "库存数量"),
        description=_optional_text(_first_present(payload, "description", "summary"), "商品描述", max_length=1000),
        category=_optional_text(_first_present(payload, "category", "group"), "商品分类", max_length=128),
        raw_payload={
            "mcy_shop": {
                "external_product_id": external_id,
                "status": status,
                "contract": MCY_SHOP_OFFLINE_FIXTURE_CONTRACT,
            }
        },
    )


def _order_from_payload(payload: Mapping[str, Any]) -> ExternalOrder:
    reject_sensitive_raw_payload_keys(dict(payload), "mcy_shop 订单", error_type=ExternalSourceError)
    order_id = _required_text(_first_present(payload, "external_order_id", "order_id", "trade_id"), "订单 ID", max_length=128)
    external_product_id = _required_text(
        _first_present(payload, "external_product_id", "product_id"),
        "外部商品 ID",
        max_length=128,
    )
    status = _required_text(_first_present(payload, "status", "state"), "订单状态", max_length=32)
    return ExternalOrder(
        provider=MCY_SHOP_PROVIDER,
        external_order_id=order_id,
        external_product_id=external_product_id,
        status=status,
        quantity=_required_int(payload.get("quantity"), "订单数量"),
        amount=_required_decimal(_first_present(payload, "amount", "total_amount"), "订单金额"),
        currency=_optional_text(payload.get("currency"), "币种", max_length=16) or "USDT",
        delivery_ready=_bool_value(payload.get("delivery_ready")),
        raw_payload={
            "mcy_shop": {
                "external_order_id": order_id,
                "status": status,
                "contract": MCY_SHOP_OFFLINE_FIXTURE_CONTRACT,
            }
        },
    )


def _delivery_from_payload(payload: Mapping[str, Any]) -> ExternalDelivery:
    reject_sensitive_raw_payload_keys(dict(payload), "mcy_shop 发货", error_type=ExternalSourceError)
    order_id = _required_text(_first_present(payload, "external_order_id", "order_id", "trade_id"), "订单 ID", max_length=128)
    items = _string_tuple(_first_present(payload, "items", "cards"), "发货条目")
    return ExternalDelivery(
        provider=MCY_SHOP_PROVIDER,
        external_order_id=order_id,
        delivery_type=_required_text(
            _first_present(payload, "delivery_type", "delivery_kind"),
            "发货类型",
            max_length=32,
        ),
        items=items,
        message=_optional_text(payload.get("message"), "发货消息", max_length=MAX_EXTERNAL_DELIVERY_MESSAGE_LENGTH),
        raw_payload={
            "mcy_shop": {
                "external_order_id": order_id,
                "item_count": len(items),
                "contract": MCY_SHOP_OFFLINE_FIXTURE_CONTRACT,
            }
        },
    )


def _dict_payload(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ExternalSourceError(f"mcy_shop provider {label}格式无效")
    return value


def _list_payload(value: Any, label: str, *, max_items: int) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise ExternalSourceError(f"mcy_shop provider {label}格式无效")
    if len(value) > max_items:
        raise ExternalSourceError(f"mcy_shop provider {label}数量不能超过 {max_items}")
    return [_dict_payload(item, label) for item in value]


def _first_present(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _required_text(value: Any, label: str, *, max_length: int) -> str:
    text = _optional_text(value, label, max_length=max_length)
    if text is None:
        raise ExternalSourceError(f"mcy_shop provider {label}缺失")
    return text


def _optional_text(value: Any, label: str, *, max_length: int) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ExternalSourceError(f"mcy_shop provider {label}必须是字符串")
    text = value.strip()
    if not text:
        return None
    if len(text) > max_length:
        raise ExternalSourceError(f"mcy_shop provider {label}过长")
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ExternalSourceError(f"mcy_shop provider {label}不能包含控制字符")
    return text


def _required_decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ExternalSourceError(f"mcy_shop provider {label}缺失")
    try:
        amount = Decimal(str(value).strip())
    except Exception as exc:
        raise ExternalSourceError(f"mcy_shop provider {label}无效") from exc
    if not amount.is_finite():
        raise ExternalSourceError(f"mcy_shop provider {label}无效")
    return amount


def _required_int(value: Any, label: str) -> int:
    amount = _optional_int(value, label)
    if amount is None:
        raise ExternalSourceError(f"mcy_shop provider {label}缺失")
    return amount


def _optional_int(value: Any, label: str) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExternalSourceError(f"mcy_shop provider {label}必须是整数")
    if value < 0:
        raise ExternalSourceError(f"mcy_shop provider {label}不能为负数")
    return value


def _bool_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    raise ExternalSourceError("mcy_shop provider delivery_ready 必须是布尔值")


def _string_tuple(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ExternalSourceError(f"mcy_shop provider {label}必须是列表")
    if len(value) > MAX_EXTERNAL_DELIVERY_ITEMS:
        raise ExternalSourceError(f"mcy_shop provider {label}数量不能超过 {MAX_EXTERNAL_DELIVERY_ITEMS}")
    items = tuple(_required_text(item, label, max_length=MAX_EXTERNAL_DELIVERY_ITEM_LENGTH) for item in value)
    if not items:
        raise ExternalSourceError(f"mcy_shop provider {label}不能为空")
    return items


def _optional_timeout(value: Any) -> float:
    if value is None:
        return DEFAULT_HTTP_TIMEOUT_SECONDS
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return DEFAULT_HTTP_TIMEOUT_SECONDS
        value = float(text)
    return normalize_external_http_timeout(value)
