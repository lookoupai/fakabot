from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from aiogram.types import User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.db.models.tenants import (
    AuditLog,
    PlatformUser,
    Tenant,
    TenantBot,
    TenantMember,
    TenantRolePermission,
    TenantSetting,
)


class TenantRepository:
    async def get_or_create_platform_user(
        self,
        session: AsyncSession,
        telegram_user: User,
        settings: Settings,
    ) -> PlatformUser:
        result = await session.execute(
            select(PlatformUser).where(PlatformUser.telegram_user_id == telegram_user.id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            user = PlatformUser(
                telegram_user_id=telegram_user.id,
                username=telegram_user.username,
                first_name=telegram_user.first_name,
                language=telegram_user.language_code or "zh",
                is_platform_admin=telegram_user.id in settings.platform_admin_ids,
            )
            session.add(user)
            await session.flush()
            return user

        user.username = telegram_user.username
        user.first_name = telegram_user.first_name
        user.language = telegram_user.language_code or user.language
        user.is_platform_admin = user.is_platform_admin or telegram_user.id in settings.platform_admin_ids
        return user

    async def token_hash_exists(self, session: AsyncSession, token_hash: str) -> bool:
        result = await session.execute(select(TenantBot.id).where(TenantBot.token_hash == token_hash))
        return result.scalar_one_or_none() is not None

    async def create_tenant_with_bot(
        self,
        session: AsyncSession,
        owner: PlatformUser,
        bot_user_id: int,
        bot_username: str,
        encrypted_token: str,
        token_hash: str,
        webhook_secret: str,
    ) -> TenantBot:
        tenant = Tenant(
            public_id=self._new_public_id(),
            owner_user_id=owner.id,
            status="trial",
            store_name=f"@{bot_username}",
            trial_ends_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        session.add(tenant)
        await session.flush()

        tenant_bot = TenantBot(
            tenant_id=tenant.id,
            bot_user_id=bot_user_id,
            bot_username=bot_username,
            encrypted_token=encrypted_token,
            token_hash=token_hash,
            webhook_secret=webhook_secret,
            status="active",
        )
        session.add(tenant_bot)
        session.add(TenantMember(tenant_id=tenant.id, user_id=owner.id, role="owner", created_by_user_id=owner.id))
        session.add_all(
            [
                TenantSetting(tenant_id=tenant.id, key="welcome", value_json={"text": "欢迎光临，本店铺正在配置中。"}),
                TenantSetting(tenant_id=tenant.id, key="support", value_json={"text": "暂未配置客服联系方式。"}),
                TenantSetting(tenant_id=tenant.id, key="order_timeout_minutes", value_json={"value": 15}),
                TenantSetting(
                    tenant_id=tenant.id,
                    key="feature_flags",
                    value_json={"self_sale": True, "supplier": False, "reseller": False},
                ),
            ]
        )
        session.add(
            AuditLog(
                tenant_id=tenant.id,
                actor_user_id=owner.id,
                action="tenant_bot.bound",
                target_type="tenant_bot",
                metadata_json={"bot_username": bot_username},
            )
        )
        await session.flush()
        return tenant_bot

    async def list_owner_bots(self, session: AsyncSession, owner_user_id: int) -> List[TenantBot]:
        result = await session.execute(
            select(TenantBot)
            .join(Tenant, Tenant.id == TenantBot.tenant_id)
            .where(Tenant.owner_user_id == owner_user_id)
            .order_by(TenantBot.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_owner_bot(
        self,
        session: AsyncSession,
        owner_user_id: int,
        tenant_bot_id: int,
    ) -> Optional[TenantBot]:
        result = await session.execute(
            select(TenantBot)
            .options(selectinload(TenantBot.tenant))
            .join(Tenant, Tenant.id == TenantBot.tenant_id)
            .where(Tenant.owner_user_id == owner_user_id)
            .where(TenantBot.id == tenant_bot_id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def rotate_owner_bot_webhook(
        self,
        session: AsyncSession,
        owner_user_id: int,
        tenant_bot_id: int,
        webhook_secret: str,
    ) -> Optional[TenantBot]:
        tenant_bot = await self.get_owner_bot(session, owner_user_id, tenant_bot_id)
        if tenant_bot is None:
            return None
        tenant_bot.webhook_secret = webhook_secret
        session.add(
            AuditLog(
                tenant_id=tenant_bot.tenant_id,
                actor_user_id=owner_user_id,
                action="tenant_bot.webhook_reset",
                target_type="tenant_bot",
                target_id=str(tenant_bot.id),
                metadata_json={
                    "bot_username": tenant_bot.bot_username,
                    "allowed_updates": ["message", "callback_query"],
                },
            )
        )
        await session.flush()
        return tenant_bot

    async def deactivate_owner_bot(
        self,
        session: AsyncSession,
        owner_user_id: int,
        tenant_bot_id: int,
    ) -> Optional[TenantBot]:
        tenant_bot = await self.get_owner_bot(session, owner_user_id, tenant_bot_id)
        if tenant_bot is None:
            return None
        tenant_bot.status = "disabled"
        session.add(
            AuditLog(
                tenant_id=tenant_bot.tenant_id,
                actor_user_id=owner_user_id,
                action="tenant_bot.deactivated",
                target_type="tenant_bot",
                target_id=str(tenant_bot.id),
                metadata_json={"bot_username": tenant_bot.bot_username},
            )
        )
        await session.flush()
        return tenant_bot

    async def get_active_bot_by_secret(self, session: AsyncSession, webhook_secret: str) -> Optional[TenantBot]:
        result = await session.execute(
            select(TenantBot)
            .options(selectinload(TenantBot.tenant).selectinload(Tenant.owner))
            .join(Tenant, Tenant.id == TenantBot.tenant_id)
            .where(TenantBot.webhook_secret == webhook_secret)
            .where(TenantBot.status == "active")
            .where(Tenant.status.in_(("trial", "active", "grace", "suspended")))
        )
        return result.scalar_one_or_none()

    async def get_active_bot_by_tenant_id(self, session: AsyncSession, tenant_id: int) -> Optional[TenantBot]:
        result = await session.execute(
            select(TenantBot)
            .where(TenantBot.tenant_id == tenant_id)
            .where(TenantBot.status == "active")
            .order_by(TenantBot.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_tenant(self, session: AsyncSession, tenant_id: int) -> Optional[Tenant]:
        result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        return result.scalar_one_or_none()

    async def get_active_tenant_by_public_id(self, session: AsyncSession, public_id: str) -> Optional[Tenant]:
        result = await session.execute(
            select(Tenant)
            .where(Tenant.public_id == public_id)
            .where(Tenant.status.in_(("trial", "active", "grace")))
        )
        return result.scalar_one_or_none()

    async def get_settings(self, session: AsyncSession, tenant_id: int) -> Dict[str, Dict[str, Any]]:
        result = await session.execute(select(TenantSetting).where(TenantSetting.tenant_id == tenant_id))
        return {setting.key: setting.value_json for setting in result.scalars().all()}

    async def upsert_setting(
        self,
        session: AsyncSession,
        tenant_id: int,
        key: str,
        value_json: Dict[str, Any],
    ) -> None:
        setting = await session.get(TenantSetting, {"tenant_id": tenant_id, "key": key})
        if setting is None:
            session.add(TenantSetting(tenant_id=tenant_id, key=key, value_json=value_json))
            return
        setting.value_json = value_json

    async def update_store_name(self, session: AsyncSession, tenant_id: int, store_name: str) -> None:
        tenant = await self.get_tenant(session, tenant_id)
        if tenant is None:
            raise ValueError("租户不存在")
        tenant.store_name = store_name

    async def get_member_role(
        self,
        session: AsyncSession,
        tenant_id: int,
        telegram_user_id: int,
    ) -> Optional[str]:
        result = await session.execute(
            select(TenantMember.role)
            .join(PlatformUser, PlatformUser.id == TenantMember.user_id)
            .where(TenantMember.tenant_id == tenant_id)
            .where(PlatformUser.telegram_user_id == telegram_user_id)
            .where(TenantMember.status == "active")
        )
        return result.scalar_one_or_none()

    async def list_members(self, session: AsyncSession, tenant_id: int) -> List[tuple[TenantMember, PlatformUser]]:
        result = await session.execute(
            select(TenantMember, PlatformUser)
            .join(PlatformUser, PlatformUser.id == TenantMember.user_id)
            .where(TenantMember.tenant_id == tenant_id)
            .where(TenantMember.status == "active")
            .order_by(TenantMember.created_at.asc())
        )
        return list(result.all())

    async def list_role_permissions(
        self,
        session: AsyncSession,
        tenant_id: int,
        role: str = "admin",
    ) -> Dict[str, bool]:
        result = await session.execute(
            select(TenantRolePermission)
            .where(TenantRolePermission.tenant_id == tenant_id)
            .where(TenantRolePermission.role == role)
            .order_by(TenantRolePermission.permission.asc())
        )
        return {item.permission: item.enabled for item in result.scalars().all()}

    async def set_role_permission(
        self,
        session: AsyncSession,
        tenant_id: int,
        role: str,
        permission: str,
        enabled: bool,
        actor_user_id: int,
    ) -> TenantRolePermission:
        if role != "admin":
            raise ValueError("当前版本只支持编辑 admin 角色权限")
        result = await session.execute(
            select(TenantRolePermission)
            .where(TenantRolePermission.tenant_id == tenant_id)
            .where(TenantRolePermission.role == role)
            .where(TenantRolePermission.permission == permission)
            .limit(1)
        )
        role_permission = result.scalar_one_or_none()
        if role_permission is None:
            role_permission = TenantRolePermission(
                tenant_id=tenant_id,
                role=role,
                permission=permission,
                enabled=enabled,
            )
            session.add(role_permission)
        else:
            role_permission.enabled = enabled
        session.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                action="tenant_role_permission.updated",
                target_type="tenant_role_permission",
                target_id=f"{role}:{permission}",
                metadata_json={"role": role, "permission": permission, "enabled": enabled},
            )
        )
        await session.flush()
        return role_permission

    async def add_admin_member(
        self,
        session: AsyncSession,
        tenant_id: int,
        telegram_user_id: int,
        created_by_user_id: int,
    ) -> TenantMember:
        tenant = await self.get_tenant(session, tenant_id)
        if tenant is None:
            raise ValueError("租户不存在")
        if tenant.owner_user_id == created_by_user_id and telegram_user_id <= 0:
            raise ValueError("Telegram 用户 ID 必须大于 0")

        platform_user = await self._get_or_create_user_by_telegram_id(session, telegram_user_id)
        if platform_user.id == tenant.owner_user_id:
            raise ValueError("owner 不需要重复添加为管理员")

        result = await session.execute(
            select(TenantMember)
            .where(TenantMember.tenant_id == tenant_id)
            .where(TenantMember.user_id == platform_user.id)
            .limit(1)
        )
        member = result.scalar_one_or_none()
        if member is None:
            member = TenantMember(
                tenant_id=tenant_id,
                user_id=platform_user.id,
                role="admin",
                status="active",
                created_by_user_id=created_by_user_id,
            )
            session.add(member)
        else:
            if member.role == "owner":
                raise ValueError("owner 不需要重复添加为管理员")
            member.role = "admin"
            member.status = "active"
            member.created_by_user_id = created_by_user_id

        session.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_user_id=created_by_user_id,
                action="tenant_member.admin_added",
                target_type="platform_user",
                target_id=str(platform_user.id),
                metadata_json={"telegram_user_id": telegram_user_id},
            )
        )
        await session.flush()
        return member

    async def remove_admin_member(
        self,
        session: AsyncSession,
        tenant_id: int,
        telegram_user_id: int,
        removed_by_user_id: int,
    ) -> bool:
        platform_user = await self._get_user_by_telegram_id(session, telegram_user_id)
        if platform_user is None:
            return False
        result = await session.execute(
            select(TenantMember)
            .where(TenantMember.tenant_id == tenant_id)
            .where(TenantMember.user_id == platform_user.id)
            .where(TenantMember.role == "admin")
            .limit(1)
        )
        member = result.scalar_one_or_none()
        if member is None:
            return False
        member.status = "removed"
        session.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_user_id=removed_by_user_id,
                action="tenant_member.admin_removed",
                target_type="platform_user",
                target_id=str(platform_user.id),
                metadata_json={"telegram_user_id": telegram_user_id},
            )
        )
        await session.flush()
        return True

    async def can_manage_settings(
        self,
        session: AsyncSession,
        tenant_id: int,
        telegram_user_id: int,
    ) -> bool:
        role = await self.get_member_role(session, tenant_id, telegram_user_id)
        return role in {"owner", "admin"}

    async def has_permission(
        self,
        session: AsyncSession,
        tenant_id: int,
        telegram_user_id: int,
        permission: str,
    ) -> bool:
        role = await self.get_member_role(session, tenant_id, telegram_user_id)
        if role == "owner":
            return True
        if role != "admin":
            return False
        result = await session.execute(
            select(TenantRolePermission.enabled)
            .where(TenantRolePermission.tenant_id == tenant_id)
            .where(TenantRolePermission.role == "admin")
            .where(TenantRolePermission.permission == permission)
            .limit(1)
        )
        enabled = result.scalar_one_or_none()
        return True if enabled is None else bool(enabled)

    async def is_owner(
        self,
        session: AsyncSession,
        tenant_id: int,
        telegram_user_id: int,
    ) -> bool:
        role = await self.get_member_role(session, tenant_id, telegram_user_id)
        return role == "owner"

    async def is_platform_user_banned(self, session: AsyncSession, telegram_user_id: int) -> bool:
        user = await self._get_user_by_telegram_id(session, telegram_user_id)
        return bool(user is not None and user.is_banned)

    async def _get_user_by_telegram_id(self, session: AsyncSession, telegram_user_id: int) -> Optional[PlatformUser]:
        result = await session.execute(
            select(PlatformUser).where(PlatformUser.telegram_user_id == telegram_user_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create_user_by_telegram_id(
        self,
        session: AsyncSession,
        telegram_user_id: int,
    ) -> PlatformUser:
        return await self._get_or_create_user_by_telegram_id(session, telegram_user_id)

    async def _get_or_create_user_by_telegram_id(
        self,
        session: AsyncSession,
        telegram_user_id: int,
    ) -> PlatformUser:
        user = await self._get_user_by_telegram_id(session, telegram_user_id)
        if user is not None:
            return user
        user = PlatformUser(
            telegram_user_id=telegram_user_id,
            language="zh",
        )
        session.add(user)
        await session.flush()
        return user

    @staticmethod
    def _new_public_id() -> str:
        return "tn_" + secrets.token_urlsafe(12).replace("-", "").replace("_", "")[:16]
