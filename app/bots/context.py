from dataclasses import dataclass


@dataclass
class TenantContext:
    tenant_id: int
    tenant_public_id: str
    tenant_bot_id: int
    owner_user_id: int
    owner_telegram_user_id: int
    store_name: str
    bot_username: str
