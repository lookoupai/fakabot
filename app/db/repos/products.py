from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.products import FileArchiveEntry, FileProcessingJob, InventoryItem, Product, ProductVariant, UploadedFile

ALLOWED_DELIVERY_TYPES = {"card_pool", "card_fixed", "telegram_invite", "file_download"}
PRODUCT_STATUSES = {"draft", "on", "off"}
_CATEGORY_UNSET = object()


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class ProductRepository:
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
        if delivery_type not in ALLOWED_DELIVERY_TYPES:
            raise ValueError("不支持的发货类型")
        await self._ensure_external_ref_available(session, tenant_id, external_source, source_key, external_id)

        product = Product(
            tenant_id=tenant_id,
            product_type="self",
            external_source=external_source,
            source_key=source_key,
            external_id=external_id,
            name=name,
            category=self._normalize_category(category),
            description=description,
            status="draft",
            review_status="none",
            suggested_price=price,
            currency="USDT",
            delivery_type=delivery_type,
            file_size_limit=5 * 1024 * 1024 if delivery_type == "file_download" else None,
        )
        session.add(product)
        await session.flush()

        session.add(
            ProductVariant(
                tenant_id=tenant_id,
                product_id=product.id,
                name="默认档位",
                price=price,
                currency="USDT",
                status="on",
            )
        )
        await session.flush()
        return product

    async def update_self_product(
        self,
        session: AsyncSession,
        tenant_id: int,
        product_id: int,
        *,
        name: Optional[str] = None,
        price: Optional[Decimal] = None,
        description: Optional[str] = None,
        category: object = _CATEGORY_UNSET,
        status: Optional[str] = None,
        delivery_type: Optional[str] = None,
        external_source: Optional[str] = None,
        source_key: str = "",
        external_id: Optional[str] = None,
    ) -> Product:
        product, variant = await self.get_product_with_default_variant(session, tenant_id, product_id)
        if product is None or variant is None:
            raise ValueError("商品不存在或无权限")
        if product.product_type != "self":
            raise ValueError("只能同步自营商品")
        if delivery_type is not None and delivery_type != product.delivery_type:
            raise ValueError("已有商品不能通过同步接口修改发货类型")
        if status is not None:
            await self.set_product_status(session, tenant_id, product_id, status)
        if name is not None:
            product.name = name
            variant.name = "默认档位"
        if description is not None:
            product.description = description
        if category is not _CATEGORY_UNSET:
            product.category = self._normalize_category(category)
        if price is not None:
            product.suggested_price = price
            variant.price = price
        if external_source is not None or external_id is not None:
            if not external_source or not external_id:
                raise ValueError("外部商品映射需要同时提供 external_source 和 external_id")
            await self._ensure_external_ref_available(
                session,
                tenant_id,
                external_source,
                source_key,
                external_id,
                product_id=product.id,
            )
            product.external_source = external_source
            product.source_key = source_key
            product.external_id = external_id
        await session.flush()
        return product

    async def get_self_product_by_external_ref(
        self,
        session: AsyncSession,
        tenant_id: int,
        external_source: str,
        source_key: str,
        external_id: str,
    ) -> Tuple[Optional[Product], Optional[ProductVariant]]:
        result = await session.execute(
            select(Product, ProductVariant)
            .outerjoin(
                ProductVariant,
                (ProductVariant.product_id == Product.id)
                & (ProductVariant.tenant_id == tenant_id)
                & (ProductVariant.sort_order == 0),
            )
            .where(Product.tenant_id == tenant_id)
            .where(Product.external_source == external_source)
            .where(Product.source_key == source_key)
            .where(Product.external_id == external_id)
            .where(Product.product_type == "self")
            .where(Product.status != "deleted")
            .limit(1)
        )
        row = result.first()
        if row is None:
            return None, None
        return row[0], row[1]

    async def list_products(
        self,
        session: AsyncSession,
        tenant_id: int,
        limit: Optional[int] = None,
        offset: int = 0,
        search_query: Optional[str] = None,
        status: Optional[str] = None,
        delivery_type: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[Tuple[Product, Optional[ProductVariant], int]]:
        conditions = self._list_product_conditions(
            tenant_id=tenant_id,
            search_query=search_query,
            status=status,
            delivery_type=delivery_type,
            category=category,
        )
        inventory_count_subquery = (
            select(
                InventoryItem.product_id.label("product_id"),
                func.count(InventoryItem.id).label("available_count"),
            )
            .where(InventoryItem.tenant_id == tenant_id)
            .where(InventoryItem.status == "available")
            .group_by(InventoryItem.product_id)
            .subquery()
        )
        query = (
            select(Product, ProductVariant, func.coalesce(inventory_count_subquery.c.available_count, 0))
            .outerjoin(
                ProductVariant,
                (ProductVariant.product_id == Product.id)
                & (ProductVariant.tenant_id == tenant_id)
                & (ProductVariant.sort_order == 0),
            )
            .outerjoin(inventory_count_subquery, inventory_count_subquery.c.product_id == Product.id)
            .where(*conditions)
            .order_by(Product.sort_order.asc(), Product.created_at.desc())
        )
        if limit is not None:
            query = query.limit(limit)
        if offset > 0:
            query = query.offset(offset)
        result = await session.execute(query)
        return [(row[0], row[1], int(row[2] or 0)) for row in result.all()]

    async def count_products(
        self,
        session: AsyncSession,
        tenant_id: int,
        search_query: Optional[str] = None,
        status: Optional[str] = None,
        delivery_type: Optional[str] = None,
        category: Optional[str] = None,
    ) -> int:
        result = await session.execute(
            select(func.count(Product.id)).where(
                *self._list_product_conditions(
                    tenant_id=tenant_id,
                    search_query=search_query,
                    status=status,
                    delivery_type=delivery_type,
                    category=category,
                )
            )
        )
        return int(result.scalar_one() or 0)

    def _list_product_conditions(
        self,
        *,
        tenant_id: int,
        search_query: Optional[str],
        status: Optional[str],
        delivery_type: Optional[str],
        category: Optional[str],
    ) -> list[object]:
        conditions: list[object] = [
            Product.tenant_id == tenant_id,
            Product.status != "deleted",
        ]
        normalized_query = (search_query or "").strip()
        if normalized_query:
            pattern = f"%{_escape_like(normalized_query)}%"
            conditions.append(
                or_(
                    Product.name.ilike(pattern, escape="\\"),
                    Product.category.ilike(pattern, escape="\\"),
                )
            )
        if status:
            if status not in PRODUCT_STATUSES:
                raise ValueError("不支持的商品状态")
            conditions.append(Product.status == status)
        if delivery_type:
            if delivery_type not in ALLOWED_DELIVERY_TYPES:
                raise ValueError("不支持的发货类型")
            conditions.append(Product.delivery_type == delivery_type)
        normalized_category = (category or "").strip()
        if normalized_category:
            conditions.append(Product.category == normalized_category)
        return conditions

    async def list_public_products(
        self,
        session: AsyncSession,
        tenant_id: int,
    ) -> List[Tuple[Product, Optional[ProductVariant], int]]:
        products = await self.list_products(session, tenant_id)
        return [
            (product, variant, available_count)
            for product, variant, available_count in products
            if product.status == "on" and (variant is None or variant.status == "on")
        ]

    async def set_product_status(
        self,
        session: AsyncSession,
        tenant_id: int,
        product_id: int,
        status: str,
    ) -> bool:
        if status not in PRODUCT_STATUSES:
            raise ValueError("不支持的商品状态")
        result = await session.execute(
            select(Product)
            .where(Product.id == product_id)
            .where(Product.tenant_id == tenant_id)
            .where(Product.status != "deleted")
        )
        product = result.scalar_one_or_none()
        if product is None:
            return False
        if status == "on" and product.delivery_type == "file_download" and product.delivery_file_id is None:
            raise ValueError("文件商品需要先上传并绑定文件")
        if status == "on" and product.delivery_type == "telegram_invite" and product.telegram_chat_id is None:
            raise ValueError("群邀请商品需要先绑定群 ID")
        product.status = status
        return True

    async def set_product_sort_order(
        self,
        session: AsyncSession,
        tenant_id: int,
        product_id: int,
        sort_order: int,
    ) -> bool:
        if not isinstance(sort_order, int) or isinstance(sort_order, bool):
            raise ValueError("排序值必须是整数")
        if sort_order < -100000 or sort_order > 100000:
            raise ValueError("排序值范围为 -100000 到 100000")
        result = await session.execute(
            select(Product)
            .where(Product.id == product_id)
            .where(Product.tenant_id == tenant_id)
            .where(Product.status != "deleted")
        )
        product = result.scalar_one_or_none()
        if product is None:
            return False
        product.sort_order = sort_order
        await session.flush()
        return True

    async def set_product_category(
        self,
        session: AsyncSession,
        tenant_id: int,
        product_id: int,
        category: Optional[str],
    ) -> bool:
        normalized_category = self._normalize_category(category)
        result = await session.execute(
            select(Product)
            .where(Product.id == product_id)
            .where(Product.tenant_id == tenant_id)
            .where(Product.status != "deleted")
        )
        product = result.scalar_one_or_none()
        if product is None:
            return False
        product.category = normalized_category
        await session.flush()
        return True

    async def create_uploaded_file(
        self,
        session: AsyncSession,
        tenant_id: int,
        storage_key: str,
        original_filename: str,
        content_type: Optional[str],
        size_bytes: int,
        sha256: str,
        purpose: str = "product_file",
        owner_user_id: Optional[int] = None,
    ) -> UploadedFile:
        uploaded_file = UploadedFile(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            storage_key=storage_key,
            original_filename=original_filename,
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=sha256,
            purpose=purpose,
            status="active",
        )
        session.add(uploaded_file)
        await session.flush()
        return uploaded_file

    async def bind_delivery_file(
        self,
        session: AsyncSession,
        tenant_id: int,
        product_id: int,
        uploaded_file_id: int,
    ) -> Product:
        product = await self._get_product(session, tenant_id, product_id)
        if product is None:
            raise ValueError("商品不存在或无权限")
        if product.delivery_type != "file_download":
            raise ValueError("只有 file_download 商品可以绑定文件")

        uploaded_file = await session.get(UploadedFile, uploaded_file_id)
        if uploaded_file is None or uploaded_file.tenant_id != tenant_id or uploaded_file.status != "active":
            raise ValueError("文件不存在或无权限")
        if product.file_size_limit is not None and uploaded_file.size_bytes > product.file_size_limit:
            raise ValueError("文件大小超过商品限制")

        product.delivery_file_id = uploaded_file.id
        await session.flush()
        return product

    @staticmethod
    def _normalize_category(category: object) -> Optional[str]:
        if category is None:
            return None
        if not isinstance(category, str):
            raise ValueError("商品分类必须是字符串")
        normalized = category.strip()
        if not normalized or normalized == "-":
            return None
        if len(normalized) > 128:
            raise ValueError("商品分类不能超过 128 个字符")
        if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
            raise ValueError("商品分类不能包含控制字符")
        return normalized

    async def bind_telegram_invite_group(
        self,
        session: AsyncSession,
        tenant_id: int,
        product_id: int,
        telegram_chat_id: int,
    ) -> Product:
        product = await self._get_product(session, tenant_id, product_id)
        if product is None:
            raise ValueError("商品不存在或无权限")
        if product.delivery_type != "telegram_invite":
            raise ValueError("只有 telegram_invite 商品可以绑定群 ID")
        product.telegram_chat_id = telegram_chat_id
        await session.flush()
        return product

    async def get_delivery_file_summary(
        self,
        session: AsyncSession,
        tenant_id: int,
        product_id: int,
    ) -> Optional[Tuple[Product, UploadedFile, Optional[FileProcessingJob], Dict[str, int]]]:
        product = await self._get_product(session, tenant_id, product_id)
        if product is None or product.delivery_file_id is None:
            return None
        uploaded_file = await session.get(UploadedFile, product.delivery_file_id)
        if uploaded_file is None or uploaded_file.tenant_id != tenant_id:
            return None

        job_result = await session.execute(
            select(FileProcessingJob)
            .where(FileProcessingJob.tenant_id == tenant_id)
            .where(FileProcessingJob.source_file_id == uploaded_file.id)
            .order_by(FileProcessingJob.created_at.desc())
            .limit(1)
        )
        latest_job = job_result.scalar_one_or_none()

        risk_result = await session.execute(
            select(FileArchiveEntry.risk_level, func.count(FileArchiveEntry.id))
            .where(FileArchiveEntry.tenant_id == tenant_id)
            .where(FileArchiveEntry.uploaded_file_id == uploaded_file.id)
            .group_by(FileArchiveEntry.risk_level)
        )
        risk_counts = {str(risk_level): int(count) for risk_level, count in risk_result.all()}
        return product, uploaded_file, latest_job, risk_counts

    async def get_product_with_default_variant(
        self,
        session: AsyncSession,
        tenant_id: int,
        product_id: int,
    ) -> Tuple[Optional[Product], Optional[ProductVariant]]:
        result = await session.execute(
            select(Product, ProductVariant)
            .outerjoin(
                ProductVariant,
                (ProductVariant.product_id == Product.id)
                & (ProductVariant.tenant_id == tenant_id)
                & (ProductVariant.sort_order == 0),
            )
            .where(Product.id == product_id)
            .where(Product.tenant_id == tenant_id)
            .where(Product.status != "deleted")
        )
        row = result.first()
        if row is None:
            return None, None
        return row[0], row[1]

    async def _get_product(self, session: AsyncSession, tenant_id: int, product_id: int) -> Optional[Product]:
        result = await session.execute(
            select(Product)
            .where(Product.id == product_id)
            .where(Product.tenant_id == tenant_id)
            .where(Product.status != "deleted")
        )
        return result.scalar_one_or_none()

    async def _ensure_external_ref_available(
        self,
        session: AsyncSession,
        tenant_id: int,
        external_source: Optional[str],
        source_key: str,
        external_id: Optional[str],
        product_id: Optional[int] = None,
    ) -> None:
        source_key = source_key or ""
        if external_source is None and external_id is None:
            if source_key:
                raise ValueError("source_key 只能与 external_source 和 external_id 一起提供")
            return
        if not external_source or not external_id:
            raise ValueError("外部商品映射需要同时提供 external_source 和 external_id")
        result = await session.execute(
            select(Product)
            .where(Product.tenant_id == tenant_id)
            .where(Product.external_source == external_source)
            .where(Product.source_key == source_key)
            .where(Product.external_id == external_id)
            .where(Product.status != "deleted")
            .limit(1)
        )
        product = result.scalar_one_or_none()
        if product is not None and product.id != product_id:
            raise ValueError("外部商品映射已绑定到其他商品")

    async def add_inventory_items(
        self,
        session: AsyncSession,
        tenant_id: int,
        product_id: int,
        encrypted_items: List[Tuple[str, str]],
    ) -> Tuple[int, int]:
        product, variant = await self.get_product_with_default_variant(session, tenant_id, product_id)
        if product is None or variant is None:
            raise ValueError("商品不存在或缺少默认档位")
        if product.product_type != "self":
            raise ValueError("只能为自营商品导入库存")
        if product.delivery_type not in {"card_pool", "card_fixed"}:
            raise ValueError("当前只支持为 card_pool/card_fixed 商品导入文本库存")

        content_hashes = [content_hash for _, content_hash in encrypted_items]
        existing_result = await session.execute(
            select(InventoryItem.content_hash)
            .where(InventoryItem.tenant_id == tenant_id)
            .where(InventoryItem.product_id == product_id)
            .where(InventoryItem.variant_id == variant.id)
            .where(InventoryItem.content_hash.in_(content_hashes))
        )
        existing_hashes = set(existing_result.scalars().all())
        new_items = [
            InventoryItem(
                tenant_id=tenant_id,
                product_id=product_id,
                variant_id=variant.id,
                content_encrypted=encrypted_content,
                content_hash=content_hash,
                status="available",
            )
            for encrypted_content, content_hash in encrypted_items
            if content_hash not in existing_hashes
        ]
        session.add_all(new_items)
        return len(new_items), len(encrypted_items) - len(new_items)

    async def inventory_summary(
        self,
        session: AsyncSession,
        tenant_id: int,
        product_id: Optional[int] = None,
    ) -> Dict[int, Dict[str, int]]:
        query = (
            select(InventoryItem.product_id, InventoryItem.status, func.count(InventoryItem.id))
            .where(InventoryItem.tenant_id == tenant_id)
            .group_by(InventoryItem.product_id, InventoryItem.status)
        )
        if product_id is not None:
            query = query.where(InventoryItem.product_id == product_id)
        result = await session.execute(query)
        summary: Dict[int, Dict[str, int]] = {}
        for item_product_id, status, count in result.all():
            summary.setdefault(int(item_product_id), {})[str(status)] = int(count)
        return summary

    async def export_available_inventory_items(
        self,
        session: AsyncSession,
        tenant_id: int,
        product_id: int,
        limit: int = 1000,
    ) -> Tuple[Product, List[InventoryItem]]:
        if limit < 1 or limit > 5000:
            raise ValueError("单次导出数量范围为 1-5000")
        product, variant = await self.get_product_with_default_variant(session, tenant_id, product_id)
        if product is None or variant is None:
            raise ValueError("商品不存在或缺少默认档位")
        if product.delivery_type not in {"card_pool", "card_fixed"}:
            raise ValueError("当前只支持导出 card_pool/card_fixed 商品库存")

        result = await session.execute(
            select(InventoryItem)
            .where(InventoryItem.tenant_id == tenant_id)
            .where(InventoryItem.product_id == product_id)
            .where(InventoryItem.variant_id == variant.id)
            .where(InventoryItem.status == "available")
            .order_by(InventoryItem.id.asc())
            .limit(limit)
        )
        return product, list(result.scalars().all())
