from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.products import InventoryItem


@dataclass
class LockedInventory:
    inventory_item_id: int
    tenant_id: int
    product_id: int
    variant_id: Optional[int]
    encrypted_content: str
    locked_until: datetime


class InventoryService:
    async def lock_one_available_item(
        self,
        session: AsyncSession,
        tenant_id: int,
        product_id: int,
        order_id: int,
        lock_minutes: int,
    ) -> Optional[LockedInventory]:
        if lock_minutes <= 0:
            raise ValueError("lock_minutes 必须大于 0")

        locked_until = datetime.now(timezone.utc) + timedelta(minutes=lock_minutes)
        result = await session.execute(
            select(InventoryItem)
            .where(InventoryItem.tenant_id == tenant_id)
            .where(InventoryItem.product_id == product_id)
            .where(InventoryItem.status == "available")
            .order_by(InventoryItem.id.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        item = result.scalar_one_or_none()
        if item is None:
            return None

        item.status = "locked"
        item.locked_by_order_id = order_id
        item.locked_until = locked_until
        await session.flush()
        return LockedInventory(
            inventory_item_id=item.id,
            tenant_id=item.tenant_id,
            product_id=item.product_id,
            variant_id=item.variant_id,
            encrypted_content=item.content_encrypted,
            locked_until=locked_until,
        )

    async def mark_locked_item_used(
        self,
        session: AsyncSession,
        tenant_id: int,
        inventory_item_id: int,
        order_id: int,
    ) -> bool:
        result = await session.execute(
            select(InventoryItem)
            .where(InventoryItem.id == inventory_item_id)
            .where(InventoryItem.tenant_id == tenant_id)
            .with_for_update()
        )
        item = result.scalar_one_or_none()
        if item is None:
            return False
        if item.status == "used" and item.used_by_order_id == order_id:
            return True
        if item.status != "locked" or item.locked_by_order_id != order_id:
            return False

        item.status = "used"
        item.used_by_order_id = order_id
        item.used_at = datetime.now(timezone.utc)
        item.locked_until = None
        await session.flush()
        return True

    async def release_order_locks(
        self,
        session: AsyncSession,
        tenant_id: int,
        order_id: int,
    ) -> int:
        result = await session.execute(
            select(InventoryItem)
            .where(InventoryItem.tenant_id == tenant_id)
            .where(InventoryItem.locked_by_order_id == order_id)
            .where(InventoryItem.status == "locked")
            .with_for_update(skip_locked=True)
        )
        items = list(result.scalars().all())
        for item in items:
            item.status = "available"
            item.locked_by_order_id = None
            item.locked_until = None
        await session.flush()
        return len(items)

    async def release_expired_locks(
        self,
        session: AsyncSession,
        limit: int = 500,
        now: Optional[datetime] = None,
    ) -> int:
        current_time = now or datetime.now(timezone.utc)
        result = await session.execute(
            select(InventoryItem)
            .where(InventoryItem.status == "locked")
            .where(InventoryItem.locked_until <= current_time)
            .order_by(InventoryItem.locked_until.asc())
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        items = list(result.scalars().all())
        for item in items:
            item.status = "available"
            item.locked_by_order_id = None
            item.locked_until = None
        await session.flush()
        return len(items)
