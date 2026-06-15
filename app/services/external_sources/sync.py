from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, Protocol, Tuple, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.products import Product, ProductVariant
from app.db.repos.products import ALLOWED_DELIVERY_TYPES, PRODUCT_STATUSES, ProductRepository
from app.services.external_sources.base import (
    ExternalAuthenticatedCatalogSyncContext,
    ExternalCatalogProvider,
    ExternalCatalogProviderWithContext,
    ExternalCatalogSyncContext,
    ExternalProviderNotRegisteredError,
    ExternalProduct,
    ExternalProductPage,
    ExternalSourceError,
)
from app.services.external_sources.identifiers import normalize_external_identifier as _normalize_external_identifier
from app.services.external_sources.limits import MAX_EXTERNAL_CATALOG_PRODUCTS_PER_PAGE
from app.services.external_sources.raw_payload import reject_sensitive_raw_payload_keys
from app.services.external_sources.registry import get_provider


@dataclass(frozen=True)
class SyncedExternalProduct:
    product_id: Optional[int]
    external_source: str
    source_key: str
    external_id: str
    action: str
    status: str
    skipped_reason: Optional[str] = None


@dataclass
class ExternalCatalogSyncResult:
    created_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    next_cursor: Optional[str] = None
    products: list[SyncedExternalProduct] = field(default_factory=list)


class CatalogProductRepository(Protocol):
    async def get_self_product_by_external_ref(
        self,
        session: AsyncSession,
        tenant_id: int,
        external_source: str,
        source_key: str,
        external_id: str,
    ) -> Tuple[Optional[Product], Optional[ProductVariant]]:
        ...

    async def create_self_product(
        self,
        session: AsyncSession,
        tenant_id: int,
        name: str,
        price: Decimal,
        delivery_type: str,
        description: Optional[str] = None,
        category: Optional[str] = None,
        external_source: Optional[str] = None,
        source_key: str = "",
        external_id: Optional[str] = None,
    ) -> Product:
        ...

    async def update_self_product(
        self,
        session: AsyncSession,
        tenant_id: int,
        product_id: int,
        *,
        name: Optional[str] = None,
        price: Optional[Decimal] = None,
        description: Optional[str] = None,
        category: object = None,
        status: Optional[str] = None,
        delivery_type: Optional[str] = None,
        external_source: Optional[str] = None,
        source_key: str = "",
        external_id: Optional[str] = None,
    ) -> Product:
        ...

    async def set_product_status(
        self,
        session: AsyncSession,
        tenant_id: int,
        product_id: int,
        status: str,
    ) -> bool:
        ...


class ExternalCatalogSyncService:
    def __init__(self, repository: Optional[CatalogProductRepository] = None) -> None:
        self.repository = repository or ProductRepository()

    async def sync_registered_catalog(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        provider_name: str,
        source_key: str = "",
        connection_id: Optional[int] = None,
        cursor: Optional[str] = None,
        limit: int = 50,
        max_pages: int = 1,
        runtime_auth: object | None = None,
    ) -> ExternalCatalogSyncResult:
        normalized_provider_name = _normalize_external_identifier(provider_name, "provider_name", allow_empty=False)
        provider = get_provider(normalized_provider_name or "")
        if provider is None:
            raise ExternalProviderNotRegisteredError("外部发卡源 provider 未注册")
        return await self.sync_catalog(
            session=session,
            tenant_id=tenant_id,
            provider=provider,
            source_key=source_key,
            connection_id=connection_id,
            cursor=cursor,
            limit=limit,
            max_pages=max_pages,
            runtime_auth=runtime_auth,
        )

    async def sync_registered_product(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        provider_name: str,
        external_product_id: str,
        source_key: str = "",
        connection_id: Optional[int] = None,
        runtime_auth: object | None = None,
    ) -> ExternalCatalogSyncResult:
        normalized_provider_name = _normalize_external_identifier(provider_name, "provider_name", allow_empty=False)
        provider = get_provider(normalized_provider_name or "")
        if provider is None:
            raise ExternalProviderNotRegisteredError("外部发卡源 provider 未注册")
        return await self.sync_product(
            session=session,
            tenant_id=tenant_id,
            provider=provider,
            external_product_id=external_product_id,
            source_key=source_key,
            connection_id=connection_id,
            runtime_auth=runtime_auth,
        )

    async def sync_catalog(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        provider: ExternalCatalogProvider,
        source_key: str = "",
        connection_id: Optional[int] = None,
        cursor: Optional[str] = None,
        limit: int = 50,
        max_pages: int = 1,
        runtime_auth: object | None = None,
    ) -> ExternalCatalogSyncResult:
        _validate_tenant_id(tenant_id)
        _validate_connection_id(connection_id)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("外部目录同步 limit 范围为 1-100")
        if not isinstance(max_pages, int) or isinstance(max_pages, bool) or not 1 <= max_pages <= 20:
            raise ValueError("外部目录同步 max_pages 范围为 1-20")
        if not hasattr(provider, "provider") or not hasattr(provider, "list_products"):
            raise ValueError("provider 必须实现外部目录同步协议")
        external_source = _normalize_external_identifier(provider.provider, "provider", allow_empty=False)
        normalized_source_key = _normalize_external_identifier(source_key, "source_key", allow_empty=True) or ""
        next_cursor = _normalize_optional_cursor(cursor)
        context = _catalog_context(
            tenant_id=tenant_id,
            provider_name=external_source,
            source_key=normalized_source_key,
            connection_id=connection_id,
            runtime_auth=runtime_auth,
        )

        result = ExternalCatalogSyncResult()
        for _ in range(max_pages):
            current_cursor = next_cursor
            page = await _list_provider_products(provider, context, cursor=current_cursor, limit=limit)
            page_next_cursor = page.next_cursor
            if page_next_cursor is not None and page_next_cursor == current_cursor:
                raise ExternalSourceError("外部发卡源返回目录游标未前进")
            for external_product in page.products:
                await self._sync_product(
                    session=session,
                    tenant_id=tenant_id,
                    external_source=external_source,
                    source_key=normalized_source_key,
                    external_product=external_product,
                    result=result,
                )
            next_cursor = page_next_cursor
            if next_cursor is None:
                break
        result.next_cursor = next_cursor
        return result

    async def sync_product(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        provider: ExternalCatalogProvider,
        external_product_id: str,
        source_key: str = "",
        connection_id: Optional[int] = None,
        runtime_auth: object | None = None,
    ) -> ExternalCatalogSyncResult:
        _validate_tenant_id(tenant_id)
        _validate_connection_id(connection_id)
        if not hasattr(provider, "provider") or not (
            hasattr(provider, "get_product") or hasattr(provider, "get_product_with_context")
        ):
            raise ValueError("provider 必须实现外部商品查询协议")
        external_source = _normalize_external_identifier(provider.provider, "provider", allow_empty=False)
        normalized_source_key = _normalize_external_identifier(source_key, "source_key", allow_empty=True) or ""
        normalized_external_product_id = _normalize_external_product_id(
            external_product_id,
            "external_product_id",
        )
        context = _catalog_context(
            tenant_id=tenant_id,
            provider_name=external_source,
            source_key=normalized_source_key,
            connection_id=connection_id,
            runtime_auth=runtime_auth,
        )

        result = ExternalCatalogSyncResult()
        external_product = await _get_provider_product(
            provider,
            context,
            external_product_id=normalized_external_product_id,
        )
        if external_product is None:
            result.skipped_count = 1
            result.products.append(
                SyncedExternalProduct(
                    product_id=None,
                    external_source=external_source,
                    source_key=normalized_source_key,
                    external_id=normalized_external_product_id,
                    action="skipped",
                    status="skipped",
                    skipped_reason="外部商品不存在",
                )
            )
            return result
        await self._sync_product(
            session=session,
            tenant_id=tenant_id,
            external_source=external_source,
            source_key=normalized_source_key,
            external_product=external_product,
            result=result,
        )
        return result

    async def _sync_product(
        self,
        *,
        session: AsyncSession,
        tenant_id: int,
        external_source: str,
        source_key: str,
        external_product: ExternalProduct,
        result: ExternalCatalogSyncResult,
    ) -> None:
        try:
            external_id, name, price, delivery_type, status = _normalize_external_product(
                external_product,
                expected_provider=external_source,
            )
            product, _ = await self.repository.get_self_product_by_external_ref(
                session,
                tenant_id=tenant_id,
                external_source=external_source,
                source_key=source_key,
                external_id=external_id,
            )
            if product is None:
                product = await self.repository.create_self_product(
                    session=session,
                    tenant_id=tenant_id,
                    name=name,
                    price=price,
                    delivery_type=delivery_type,
                    description=external_product.description,
                    category=external_product.category,
                    external_source=external_source,
                    source_key=source_key,
                    external_id=external_id,
                )
                if status != "draft":
                    await self.repository.set_product_status(session, tenant_id, product.id, status)
                action = "created"
                result.created_count += 1
            else:
                product = await self.repository.update_self_product(
                    session=session,
                    tenant_id=tenant_id,
                    product_id=product.id,
                    name=name,
                    price=price,
                    description=external_product.description,
                    category=external_product.category,
                    status=status,
                    delivery_type=delivery_type,
                    external_source=external_source,
                    source_key=source_key,
                    external_id=external_id,
                )
                action = "updated"
                result.updated_count += 1
            result.products.append(
                SyncedExternalProduct(
                    product_id=product.id,
                    external_source=external_source,
                    source_key=source_key,
                    external_id=external_id,
                    action=action,
                    status=product.status,
                )
            )
        except ValueError as exc:
            result.skipped_count += 1
            result.products.append(
                SyncedExternalProduct(
                    product_id=None,
                    external_source=external_source,
                    source_key=source_key,
                    external_id=_external_product_id_for_result(external_product),
                    action="skipped",
                    status="skipped",
                    skipped_reason=str(exc),
                )
            )


def _normalize_external_product_id(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} 必须是字符串")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} 不能为空")
    if len(normalized) > 128:
        raise ValueError(f"{field_name} 长度不能超过 128")
    return normalized


def _validate_tenant_id(tenant_id: int) -> None:
    if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id <= 0:
        raise ValueError("tenant_id 必须为正整数")


def _validate_connection_id(connection_id: Optional[int]) -> None:
    if connection_id is not None and (
        not isinstance(connection_id, int) or isinstance(connection_id, bool) or connection_id <= 0
    ):
        raise ValueError("connection_id 必须为正整数")


def _catalog_context(
    *,
    tenant_id: int,
    provider_name: str,
    source_key: str,
    connection_id: Optional[int],
    runtime_auth: object | None,
) -> ExternalCatalogSyncContext:
    if runtime_auth is None:
        return ExternalCatalogSyncContext(
            tenant_id=tenant_id,
            provider_name=provider_name,
            source_key=source_key,
            connection_id=connection_id,
        )
    _validate_runtime_auth(
        runtime_auth,
        tenant_id=tenant_id,
        provider_name=provider_name,
        source_key=source_key,
        connection_id=connection_id,
    )
    return ExternalAuthenticatedCatalogSyncContext(
        tenant_id=tenant_id,
        provider_name=provider_name,
        source_key=source_key,
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


def _normalize_optional_cursor(cursor: Optional[str]) -> Optional[str]:
    if cursor is None:
        return None
    if not isinstance(cursor, str):
        raise ValueError("cursor 必须是字符串")
    normalized = cursor.strip()
    if not normalized:
        raise ValueError("cursor 不能为空")
    if len(normalized) > 512:
        raise ValueError("cursor 长度不能超过 512")
    return normalized


def _normalize_external_product(
    product: ExternalProduct,
    *,
    expected_provider: str,
) -> tuple[str, str, Decimal, str, str]:
    if not isinstance(product.provider, str):
        raise ExternalSourceError("外部发卡源返回商品 provider 无效")
    try:
        product_provider = _normalize_external_identifier(product.provider, "product.provider", allow_empty=False)
    except ValueError as exc:
        raise ExternalSourceError("外部发卡源返回商品 provider 无效") from exc
    if product_provider != expected_provider:
        raise ExternalSourceError("外部发卡源返回商品 provider 不匹配")
    if not isinstance(product.external_product_id, str):
        raise ExternalSourceError("外部发卡源返回商品 ID 无效")
    external_id = product.external_product_id.strip()
    if not external_id:
        raise ValueError("外部商品 ID 不能为空")
    if len(external_id) > 128:
        raise ValueError("外部商品 ID 长度不能超过 128")
    if not isinstance(product.name, str):
        raise ExternalSourceError("外部发卡源返回商品名称无效")
    name = product.name.strip()
    if len(name) < 2:
        raise ValueError("外部商品名称至少 2 个字符")
    if not isinstance(product.currency, str):
        raise ExternalSourceError("外部发卡源返回商品币种无效")
    if product.currency != "USDT":
        raise ValueError("外部目录同步当前仅支持 USDT 商品")
    if not isinstance(product.price, Decimal) or not product.price.is_finite():
        raise ExternalSourceError("外部发卡源返回商品价格无效")
    if product.price <= Decimal("0"):
        raise ValueError("外部商品价格必须大于 0")
    if not isinstance(product.delivery_type, str):
        raise ExternalSourceError("外部发卡源返回商品发货类型无效")
    if product.delivery_type not in ALLOWED_DELIVERY_TYPES:
        raise ValueError("外部商品发货类型不受支持")
    if not isinstance(product.status, str):
        raise ExternalSourceError("外部发卡源返回商品状态无效")
    if product.description is not None and not isinstance(product.description, str):
        raise ExternalSourceError("外部发卡源返回商品描述无效")
    if product.category is not None and not isinstance(product.category, str):
        raise ExternalSourceError("外部发卡源返回商品分类无效")
    if product.stock_count is not None:
        if not isinstance(product.stock_count, int) or product.stock_count < 0:
            raise ExternalSourceError("外部发卡源返回商品库存数量无效")
    if not isinstance(product.raw_payload, dict):
        raise ValueError("外部商品原始载荷无效")
    reject_sensitive_raw_payload_keys(product.raw_payload, "商品")
    status = product.status if product.status in PRODUCT_STATUSES else "draft"
    if product.delivery_type in {"file_download", "telegram_invite"} and status == "on":
        status = "draft"
    return external_id, name, product.price, product.delivery_type, status


def _external_product_id_for_result(product: ExternalProduct) -> str:
    if isinstance(product.external_product_id, str):
        return product.external_product_id.strip()
    return ""


async def _list_provider_products(
    provider: ExternalCatalogProvider,
    context: ExternalCatalogSyncContext,
    *,
    cursor: Optional[str],
    limit: int,
) -> ExternalProductPage:
    try:
        if hasattr(provider, "list_products_with_context"):
            context_provider = cast(ExternalCatalogProviderWithContext, provider)
            page = await context_provider.list_products_with_context(context=context, cursor=cursor, limit=limit)
        else:
            page = await provider.list_products(tenant_id=context.tenant_id, cursor=cursor, limit=limit)
    except ExternalSourceError:
        raise
    except Exception as exc:
        raise ExternalSourceError("外部发卡源目录获取失败") from exc
    return _validate_provider_product_page(page)


async def _get_provider_product(
    provider: ExternalCatalogProvider,
    context: ExternalCatalogSyncContext,
    *,
    external_product_id: str,
) -> Optional[ExternalProduct]:
    try:
        if hasattr(provider, "get_product_with_context"):
            context_provider = cast(ExternalCatalogProviderWithContext, provider)
            product = await context_provider.get_product_with_context(
                context=context,
                external_product_id=external_product_id,
            )
        else:
            product = await provider.get_product(
                tenant_id=context.tenant_id,
                external_product_id=external_product_id,
            )
    except ExternalSourceError:
        raise
    except Exception as exc:
        raise ExternalSourceError("外部发卡源商品获取失败") from exc
    if product is None:
        return None
    if not isinstance(product, ExternalProduct):
        raise ExternalSourceError("外部发卡源返回商品结果无效")
    return product


def _validate_provider_product_page(page: object) -> ExternalProductPage:
    if not isinstance(page, ExternalProductPage):
        raise ExternalSourceError("外部发卡源返回目录分页结果无效")
    if not isinstance(page.products, list):
        raise ExternalSourceError("外部发卡源返回目录商品列表无效")
    if len(page.products) > MAX_EXTERNAL_CATALOG_PRODUCTS_PER_PAGE:
        raise ExternalSourceError("外部发卡源返回目录商品列表过大")
    for product in page.products:
        if not isinstance(product, ExternalProduct):
            raise ExternalSourceError("外部发卡源返回目录商品结果无效")
    if page.next_cursor is not None:
        if not isinstance(page.next_cursor, str):
            raise ExternalSourceError("外部发卡源返回目录游标无效")
        if not page.next_cursor.strip():
            raise ExternalSourceError("外部发卡源返回目录游标为空")
        if len(page.next_cursor) > 512:
            raise ExternalSourceError("外部发卡源返回目录游标过长")
    return page
