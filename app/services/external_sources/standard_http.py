from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping, Optional

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
    is_sensitive_http_header_name,
    normalize_external_http_headers,
    normalize_external_http_timeout,
    validate_external_http_public_base_url,
)
from app.services.external_sources.limits import (
    MAX_EXTERNAL_CATALOG_PRODUCTS_PER_PAGE,
    MAX_EXTERNAL_DELIVERY_ITEM_LENGTH,
    MAX_EXTERNAL_DELIVERY_ITEMS,
    MAX_EXTERNAL_DELIVERY_MESSAGE_LENGTH,
)
from app.services.external_sources.raw_payload import reject_sensitive_raw_payload_keys

STANDARD_HTTP_PROVIDER = "standard_http"
STANDARD_HTTP_CONTRACT = "standard_http_json_v1"
DEFAULT_CATALOG_PATH = "catalog"
DEFAULT_PRODUCT_PATH = "catalog/{external_product_id}"
DEFAULT_CREATE_ORDER_PATH = "orders"
DEFAULT_QUERY_ORDER_PATH = "orders/{external_order_id}"
DEFAULT_DELIVERY_PATH = "deliveries/{external_order_id}"
ALLOWED_PATH_TEMPLATE_VARIABLES = {"external_product_id", "external_order_id"}
ALLOWED_STANDARD_HTTP_CREDENTIAL_FIELDS = {
    "base_url",
    "api_key",
    "api_key_header",
    "timeout_seconds",
    "catalog_path",
    "product_path",
    "create_order_path",
    "query_order_path",
    "delivery_path",
}


@dataclass(frozen=True)
class StandardHttpCredentials:
    base_url: str
    api_key: str = field(repr=False)
    api_key_header: str = "X-API-Key"
    timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS
    catalog_path: str = DEFAULT_CATALOG_PATH
    product_path: str = DEFAULT_PRODUCT_PATH
    create_order_path: str = DEFAULT_CREATE_ORDER_PATH
    query_order_path: str = DEFAULT_QUERY_ORDER_PATH
    delivery_path: str = DEFAULT_DELIVERY_PATH


class StandardHttpExternalSourceProvider:
    provider = STANDARD_HTTP_PROVIDER
    integration_kind = "generic_http_json"
    contract_name = STANDARD_HTTP_CONTRACT
    production_ready = False
    staging_verified = False
    auto_fulfillment_idempotent = False

    def __init__(self, client: Optional[ExternalHttpClient] = None) -> None:
        self.client = client or ExternalHttpClient(ExternalHttpxTransport())

    def validate_connection_credentials(self, credentials: Mapping[str, str]) -> None:
        validate_standard_http_credentials(credentials)

    async def list_products(
        self,
        tenant_id: int,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> ExternalProductPage:
        raise ExternalSourceError("standard_http provider 需要 runtime_auth")

    async def get_product(self, tenant_id: int, external_product_id: str) -> Optional[ExternalProduct]:
        raise ExternalSourceError("standard_http provider 需要 runtime_auth")

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
                    path_segments=_path_segments(credentials.catalog_path),
                    query={"cursor": cursor, "limit": limit},
                ),
                headers=_headers(credentials, context.source_key),
                timeout_seconds=credentials.timeout_seconds,
            )
        )
        data = _dict_payload(payload, "目录响应")
        products = _list_payload(
            data.get("products"),
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
                    path_segments=_path_segments(
                        credentials.product_path,
                        external_product_id=external_product_id,
                    ),
                ),
                headers=_headers(credentials, context.source_key),
                timeout_seconds=credentials.timeout_seconds,
            )
        )
        if payload is None:
            return None
        return _product_from_payload(_dict_payload(payload, "商品响应"))

    async def create_order(self, tenant_id: int, request: ExternalOrderRequest) -> ExternalOrder:
        raise ExternalSourceError("standard_http provider 需要 runtime_auth")

    async def query_order(self, tenant_id: int, external_order_id: str) -> Optional[ExternalOrder]:
        raise ExternalSourceError("standard_http provider 需要 runtime_auth")

    async def fetch_delivery(self, tenant_id: int, external_order_id: str) -> Optional[ExternalDelivery]:
        raise ExternalSourceError("standard_http provider 需要 runtime_auth")

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
                    path_segments=_path_segments(credentials.create_order_path),
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
                    path_segments=_path_segments(
                        credentials.query_order_path,
                        external_order_id=external_order_id,
                    ),
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
                    path_segments=_path_segments(
                        credentials.delivery_path,
                        external_order_id=external_order_id,
                    ),
                ),
                headers=_headers(credentials, context.source_key),
                timeout_seconds=credentials.timeout_seconds,
            )
        )
        if payload is None:
            return None
        return _delivery_from_payload(_dict_payload(payload, "发货响应"))


def create_standard_http_provider(transport: Optional[ExternalHttpTransport] = None) -> StandardHttpExternalSourceProvider:
    client = ExternalHttpClient(transport or ExternalHttpxTransport())
    return StandardHttpExternalSourceProvider(client)


def validate_standard_http_credentials(credentials: Mapping[str, str]) -> StandardHttpCredentials:
    try:
        _reject_unknown_credential_fields(credentials)
        return _credentials_from_mapping(credentials)
    except (ExternalSourceError, ValueError) as exc:
        raise ValueError("standard_http 凭据无效") from exc


def _credentials_from_context(context: object) -> StandardHttpCredentials:
    runtime_auth = getattr(context, "runtime_auth", None)
    credentials = getattr(runtime_auth, "credentials", None) if runtime_auth is not None else None
    if not isinstance(credentials, Mapping):
        raise ExternalSourceError("standard_http provider 缺少运行时凭据")
    try:
        _reject_unknown_credential_fields(credentials)
        return _credentials_from_mapping(credentials)
    except (ExternalSourceError, ValueError) as exc:
        raise ExternalSourceError("standard_http provider 凭据无效") from exc


def _credentials_from_mapping(credentials: Mapping[str, Any]) -> StandardHttpCredentials:
    base_url = validate_external_http_public_base_url(
        _required_text(credentials.get("base_url"), "base_url", max_length=2048)
    )
    api_key = _required_text(credentials.get("api_key"), "api_key", max_length=4096)
    api_key_header = _optional_text(credentials.get("api_key_header"), "api_key_header", max_length=128)
    if api_key_header is not None and not is_sensitive_http_header_name(api_key_header):
        raise ValueError("api_key_header 必须是敏感认证头")
    timeout_seconds = _optional_timeout(credentials.get("timeout_seconds"))
    return StandardHttpCredentials(
        base_url=base_url,
        api_key=api_key,
        api_key_header=api_key_header or "X-API-Key",
        timeout_seconds=timeout_seconds,
        catalog_path=_path_template(
            credentials.get("catalog_path"),
            DEFAULT_CATALOG_PATH,
            "catalog_path",
            required_variables=set(),
        ),
        product_path=_path_template(
            credentials.get("product_path"),
            DEFAULT_PRODUCT_PATH,
            "product_path",
            required_variables={"external_product_id"},
        ),
        create_order_path=_path_template(
            credentials.get("create_order_path"),
            DEFAULT_CREATE_ORDER_PATH,
            "create_order_path",
            required_variables=set(),
        ),
        query_order_path=_path_template(
            credentials.get("query_order_path"),
            DEFAULT_QUERY_ORDER_PATH,
            "query_order_path",
            required_variables={"external_order_id"},
        ),
        delivery_path=_path_template(
            credentials.get("delivery_path"),
            DEFAULT_DELIVERY_PATH,
            "delivery_path",
            required_variables={"external_order_id"},
        ),
    )


def _headers(credentials: StandardHttpCredentials, source_key: str) -> dict[str, str]:
    values = {credentials.api_key_header: credentials.api_key}
    if source_key:
        values["X-Source-Key"] = source_key
    return normalize_external_http_headers(values)


def _reject_unknown_credential_fields(credentials: Mapping[str, Any]) -> None:
    unknown_fields = set(credentials) - ALLOWED_STANDARD_HTTP_CREDENTIAL_FIELDS
    if unknown_fields:
        raise ValueError("standard_http 凭据字段不支持")


def _path_template(
    value: Any,
    default: str,
    field_name: str,
    *,
    required_variables: set[str] | None = None,
    allowed_variables: set[str] | None = None,
) -> str:
    template = _optional_text(value, field_name, max_length=512) or default
    used_variables = _template_variables(template)
    if required_variables is not None and used_variables != required_variables:
        raise ValueError("路径模板变量不匹配")
    if allowed_variables is not None and not used_variables <= allowed_variables:
        raise ValueError("路径模板变量不支持")
    _path_segments(template)
    return template


def _template_variables(template: str) -> set[str]:
    variables: set[str] = set()
    for segment in _path_segments(template):
        if segment.startswith("{") and segment.endswith("}"):
            variables.add(segment[1:-1].strip())
    return variables


def _path_segments(template: str, **variables: str) -> tuple[str, ...]:
    if not isinstance(template, str):
        raise ValueError("路径模板必须是字符串")
    text = template.strip().strip("/")
    if not text:
        raise ValueError("路径模板不能为空")
    if "://" in text or "?" in text or "#" in text or "@" in text:
        raise ValueError("路径模板必须是相对路径")
    raw_segments = text.split("/")
    segments: list[str] = []
    for raw_segment in raw_segments:
        segment = raw_segment.strip()
        if not segment:
            raise ValueError("路径模板不能包含空 segment")
        if segment.startswith("{") or segment.endswith("}"):
            if not (segment.startswith("{") and segment.endswith("}")):
                raise ValueError("路径模板变量格式无效")
            variable_name = segment[1:-1].strip()
            if variable_name not in ALLOWED_PATH_TEMPLATE_VARIABLES:
                raise ValueError("路径模板变量不支持")
            if variable_name not in variables:
                segments.append(segment)
                continue
            segment = variables[variable_name]
        elif "{" in segment or "}" in segment:
            raise ValueError("路径模板变量必须独占 segment")
        elif segment in {".", ".."} or "\\" in segment:
            raise ValueError("路径模板 segment 不安全")
        elif len(segment) > 256:
            raise ValueError("路径模板 segment 过长")
        elif any(ord(char) < 32 or ord(char) == 127 for char in segment):
            raise ValueError("路径模板 segment 不能包含控制字符")
        segments.append(segment)
    return tuple(segments)


def _product_from_payload(payload: Mapping[str, Any]) -> ExternalProduct:
    reject_sensitive_raw_payload_keys(dict(payload), "standard_http 商品")
    external_id = _required_text(payload.get("id") or payload.get("external_product_id"), "商品 ID", max_length=128)
    status = _optional_text(payload.get("status"), "商品状态", max_length=32) or "on"
    return ExternalProduct(
        provider=STANDARD_HTTP_PROVIDER,
        external_product_id=external_id,
        name=_required_text(payload.get("name"), "商品名称", max_length=255),
        price=_required_decimal(payload.get("price"), "商品价格"),
        currency=_optional_text(payload.get("currency"), "币种", max_length=16) or "USDT",
        status=status,
        delivery_type=_optional_text(payload.get("delivery_type"), "发货类型", max_length=32) or "card_pool",
        stock_count=_optional_int(payload.get("stock_count"), "库存数量"),
        description=_optional_text(payload.get("description"), "商品描述", max_length=1000),
        category=_optional_text(payload.get("category"), "商品分类", max_length=128),
        raw_payload={"standard_http": {"external_product_id": external_id, "status": status}},
    )


def _order_from_payload(payload: Mapping[str, Any]) -> ExternalOrder:
    reject_sensitive_raw_payload_keys(dict(payload), "standard_http 订单")
    order_id = _required_text(payload.get("order_id") or payload.get("external_order_id"), "订单 ID", max_length=128)
    external_product_id = _required_text(payload.get("external_product_id"), "外部商品 ID", max_length=128)
    status = _required_text(payload.get("status"), "订单状态", max_length=32)
    return ExternalOrder(
        provider=STANDARD_HTTP_PROVIDER,
        external_order_id=order_id,
        external_product_id=external_product_id,
        status=status,
        quantity=_required_int(payload.get("quantity"), "订单数量"),
        amount=_required_decimal(payload.get("amount"), "订单金额"),
        currency=_optional_text(payload.get("currency"), "币种", max_length=16) or "USDT",
        delivery_ready=_bool_value(payload.get("delivery_ready")),
        raw_payload={"standard_http": {"external_order_id": order_id, "status": status}},
    )


def _delivery_from_payload(payload: Mapping[str, Any]) -> ExternalDelivery:
    reject_sensitive_raw_payload_keys(dict(payload), "standard_http 发货")
    order_id = _required_text(payload.get("order_id") or payload.get("external_order_id"), "订单 ID", max_length=128)
    items = _string_tuple(payload.get("items"), "发货条目")
    return ExternalDelivery(
        provider=STANDARD_HTTP_PROVIDER,
        external_order_id=order_id,
        delivery_type=_required_text(payload.get("delivery_type"), "发货类型", max_length=32),
        items=items,
        message=_optional_text(payload.get("message"), "发货消息", max_length=MAX_EXTERNAL_DELIVERY_MESSAGE_LENGTH),
        raw_payload={"standard_http": {"external_order_id": order_id, "item_count": len(items)}},
    )


def _dict_payload(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ExternalSourceError(f"standard_http provider {label}格式无效")
    return value


def _list_payload(value: Any, label: str, *, max_items: int) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise ExternalSourceError(f"standard_http provider {label}格式无效")
    if len(value) > max_items:
        raise ExternalSourceError(f"standard_http provider {label}数量不能超过 {max_items}")
    return [_dict_payload(item, label) for item in value]


def _required_text(value: Any, label: str, *, max_length: int) -> str:
    text = _optional_text(value, label, max_length=max_length)
    if text is None:
        raise ExternalSourceError(f"standard_http provider {label}缺失")
    return text


def _optional_text(value: Any, label: str, *, max_length: int) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ExternalSourceError(f"standard_http provider {label}必须是字符串")
    text = value.strip()
    if not text:
        return None
    if len(text) > max_length:
        raise ExternalSourceError(f"standard_http provider {label}过长")
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ExternalSourceError(f"standard_http provider {label}不能包含控制字符")
    return text


def _required_decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ExternalSourceError(f"standard_http provider {label}缺失")
    try:
        amount = Decimal(str(value).strip())
    except Exception as exc:
        raise ExternalSourceError(f"standard_http provider {label}无效") from exc
    if not amount.is_finite():
        raise ExternalSourceError(f"standard_http provider {label}无效")
    return amount


def _required_int(value: Any, label: str) -> int:
    amount = _optional_int(value, label)
    if amount is None:
        raise ExternalSourceError(f"standard_http provider {label}缺失")
    return amount


def _optional_int(value: Any, label: str) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExternalSourceError(f"standard_http provider {label}必须是整数")
    if value < 0:
        raise ExternalSourceError(f"standard_http provider {label}不能为负数")
    return value


def _bool_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    raise ExternalSourceError("standard_http provider delivery_ready 必须是布尔值")


def _string_tuple(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ExternalSourceError(f"standard_http provider {label}必须是列表")
    if len(value) > MAX_EXTERNAL_DELIVERY_ITEMS:
        raise ExternalSourceError(f"standard_http provider {label}数量不能超过 {MAX_EXTERNAL_DELIVERY_ITEMS}")
    items = tuple(_required_text(item, label, max_length=MAX_EXTERNAL_DELIVERY_ITEM_LENGTH) for item in value)
    if not items:
        raise ExternalSourceError(f"standard_http provider {label}不能为空")
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
