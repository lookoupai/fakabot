from __future__ import annotations

import ipaddress
import json
from functools import lru_cache
from decimal import Decimal
from typing import Annotated, Any, Optional, Set
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


PLATFORM_ADMIN_SCOPE_VALUES = frozenset(
    {
        "platform_risk:read",
        "platform_risk:write",
        "platform_finance:read",
        "platform_finance:write",
        "platform_subscriptions:read",
        "platform_subscriptions:write",
        "platform_supply:read",
        "platform_supply:write",
    }
)

EnvIntSet = Annotated[Set[int], NoDecode]
EnvStrSet = Annotated[Set[str], NoDecode]
EnvPlatformAdminScopeMap = Annotated[dict[str, Set[str]], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "development"
    public_base_url: str = "https://example.com"
    database_url: str = "postgresql+asyncpg://fakabot:fakabot@postgres:5432/fakabot"
    redis_url: str = "redis://redis:6379/0"
    master_bot_token: Optional[SecretStr] = None
    master_webhook_secret: str = "master"
    token_encryption_key: Optional[SecretStr] = None
    platform_admin_ids: EnvIntSet = Field(default_factory=set)
    platform_admin_api_key_hashes: EnvStrSet = Field(default_factory=set, repr=False)
    platform_admin_api_key_scopes: EnvPlatformAdminScopeMap = Field(default_factory=dict, repr=False)
    webhook_base_path: str = "/telegram/webhook"
    storage_root: str = "/app/storage"
    epusdt_base_url: Optional[str] = None
    epusdt_pid: Optional[str] = None
    epusdt_secret_key: Optional[SecretStr] = None
    epusdt_token: str = "USDT"
    epusdt_network: str = "TRC20"
    workers_enabled: bool = True
    order_expire_interval_seconds: int = 60
    inventory_unlock_interval_seconds: int = 60
    payment_reconcile_interval_seconds: int = 300
    payment_retry_interval_seconds: int = 300
    external_fulfillment_interval_seconds: int = 120
    delivery_dispatch_interval_seconds: int = 30
    delivery_sending_timeout_seconds: int = 300
    ledger_settlement_interval_seconds: int = 60
    export_job_interval_seconds: int = 60
    subscription_lifecycle_interval_seconds: int = 300
    worker_batch_limit: int = 500
    subscription_monthly_price: Decimal = Decimal("10")
    subscription_expiry_reminder_days: int = 3
    subscription_data_retention_days: int = 30
    tenant_admin_require_signature: bool = False
    tenant_admin_signature_max_skew_seconds: int = 300
    tenant_admin_rate_limit_per_minute: int = 120
    tenant_admin_ip_allowlist: EnvStrSet = Field(default_factory=set)
    platform_admin_require_signature: bool = False
    platform_admin_signature_max_skew_seconds: int = 300
    platform_admin_rate_limit_per_minute: int = 60
    platform_admin_ip_allowlist: EnvStrSet = Field(default_factory=set)
    trusted_proxy_ips: EnvStrSet = Field(default_factory=set)
    rate_limit_key_prefix: str = "fakabot:rate_limit"
    rate_limit_window_seconds: int = 60
    public_store_write_rate_limit_per_minute: int = 30
    public_store_write_ip_allowlist: EnvStrSet = Field(default_factory=set)
    order_risk_recent_window_seconds: int = 60
    order_risk_max_buyer_orders_per_window: int = 5
    order_risk_daily_window_seconds: int = 86400
    order_risk_max_buyer_amount_per_day: Decimal = Decimal("500")
    order_risk_auto_ban_enabled: bool = False
    order_risk_auto_ban_window_seconds: int = 86400
    order_risk_auto_ban_blocked_count_threshold: int = 3
    telegram_webapp_require_init_data: bool = False
    telegram_webapp_init_data_max_age_seconds: int = 86400
    admin_web_session_max_age_seconds: int = 86400
    admin_web_binding_code_ttl_seconds: int = 300
    admin_web_binding_code_rate_limit_per_minute: int = 10
    admin_web_allowed_origins: EnvStrSet = Field(default_factory=set)
    log_level: str = "INFO"

    @field_validator("platform_admin_ids", mode="before")
    @classmethod
    def parse_platform_admin_ids(cls, value: Any) -> Set[int]:
        if value in (None, ""):
            return set()
        if isinstance(value, set):
            return value
        if isinstance(value, (list, tuple)):
            return {int(item) for item in value if str(item).strip()}
        return {int(item.strip()) for item in str(value).split(",") if item.strip()}

    @field_validator("platform_admin_api_key_hashes", mode="before")
    @classmethod
    def parse_platform_admin_api_key_hashes(cls, value: Any) -> Set[str]:
        if value in (None, ""):
            return set()
        if isinstance(value, set):
            return {str(item).strip().lower() for item in value if str(item).strip()}
        if isinstance(value, (list, tuple)):
            return {str(item).strip().lower() for item in value if str(item).strip()}
        return {item.strip().lower() for item in str(value).split(",") if item.strip()}

    @field_validator("platform_admin_api_key_hashes")
    @classmethod
    def validate_platform_admin_api_key_hashes(cls, value: Set[str]) -> Set[str]:
        for item in value:
            if not _is_sha256_hex(item):
                raise ValueError("平台 Admin API Key hash 必须是 SHA-256 hex")
        return value

    @field_validator("platform_admin_api_key_scopes", mode="before")
    @classmethod
    def parse_platform_admin_api_key_scopes(cls, value: Any) -> dict[str, Set[str]]:
        if value in (None, ""):
            return {}
        raw_mapping: dict[Any, Any]
        if isinstance(value, dict):
            raw_mapping = value
        elif isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return {}
            if stripped.startswith("{"):
                loaded = json.loads(stripped)
                if not isinstance(loaded, dict):
                    raise ValueError("平台 Admin API Key scope 配置必须是对象")
                raw_mapping = loaded
            else:
                raw_mapping = {}
                for entry in stripped.split(";"):
                    entry = entry.strip()
                    if not entry:
                        continue
                    key_hash, separator, scopes_value = entry.partition("=")
                    if not separator:
                        raise ValueError("平台 Admin API Key scope 配置格式应为 hash=scope1,scope2")
                    raw_mapping[key_hash.strip()] = scopes_value
        else:
            raise ValueError("平台 Admin API Key scope 配置必须是字符串或对象")

        parsed: dict[str, Set[str]] = {}
        for raw_key_hash, raw_scopes in raw_mapping.items():
            key_hash = str(raw_key_hash).strip().lower()
            scopes = _parse_scope_values(raw_scopes)
            parsed[key_hash] = scopes
        return parsed

    @field_validator("platform_admin_api_key_scopes")
    @classmethod
    def validate_platform_admin_api_key_scopes(cls, value: dict[str, Set[str]]) -> dict[str, Set[str]]:
        for key_hash, scopes in value.items():
            if not _is_sha256_hex(key_hash):
                raise ValueError("平台 Admin API Key scope 配置中的 hash 必须是 SHA-256 hex")
            if not scopes:
                raise ValueError("平台 Admin API Key scope 不能为空")
            unknown_scopes = scopes - PLATFORM_ADMIN_SCOPE_VALUES
            if unknown_scopes:
                raise ValueError("平台 Admin API Key scope 包含未知权限")
        return value

    @model_validator(mode="after")
    def validate_platform_admin_api_key_scope_hashes(self) -> "Settings":
        orphan_hashes = set(self.platform_admin_api_key_scopes) - set(self.platform_admin_api_key_hashes)
        if orphan_hashes:
            raise ValueError("平台 Admin API Key scope 只能引用已配置的 API Key hash")
        return self

    @field_validator(
        "tenant_admin_ip_allowlist",
        "platform_admin_ip_allowlist",
        "trusted_proxy_ips",
        "public_store_write_ip_allowlist",
        mode="before",
    )
    @classmethod
    def parse_ip_rules(cls, value: Any) -> Set[str]:
        if value in (None, ""):
            return set()
        if isinstance(value, set):
            return {str(item).strip() for item in value if str(item).strip()}
        if isinstance(value, (list, tuple)):
            return {str(item).strip() for item in value if str(item).strip()}
        return {item.strip() for item in str(value).split(",") if item.strip()}

    @field_validator("tenant_admin_ip_allowlist", "platform_admin_ip_allowlist", "trusted_proxy_ips", "public_store_write_ip_allowlist")
    @classmethod
    def validate_ip_rules(cls, value: Set[str]) -> Set[str]:
        for item in value:
            try:
                ipaddress.ip_network(item, strict=False)
            except ValueError as exc:
                raise ValueError("必须是合法 IP 或 CIDR") from exc
        return value

    @field_validator("admin_web_allowed_origins", mode="before")
    @classmethod
    def parse_admin_web_allowed_origins(cls, value: Any) -> Set[str]:
        if value in (None, ""):
            return set()
        if isinstance(value, set):
            return {str(item).strip().rstrip("/") for item in value if str(item).strip()}
        if isinstance(value, (list, tuple)):
            return {str(item).strip().rstrip("/") for item in value if str(item).strip()}
        return {item.strip().rstrip("/") for item in str(value).split(",") if item.strip()}

    @field_validator("admin_web_allowed_origins")
    @classmethod
    def validate_admin_web_allowed_origins(cls, value: Set[str]) -> Set[str]:
        for origin in value:
            _validate_public_origin(origin)
        return value

    @field_validator("webhook_base_path")
    @classmethod
    def normalize_webhook_base_path(cls, value: str) -> str:
        normalized = "/" + value.strip("/")
        return normalized

    @field_validator("public_base_url")
    @classmethod
    def normalize_public_base_url(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("epusdt_base_url")
    @classmethod
    def normalize_epusdt_base_url(cls, value: Optional[str]) -> Optional[str]:
        return value.rstrip("/") if value else value

    @field_validator(
        "order_expire_interval_seconds",
        "inventory_unlock_interval_seconds",
        "payment_reconcile_interval_seconds",
        "external_fulfillment_interval_seconds",
        "delivery_dispatch_interval_seconds",
        "delivery_sending_timeout_seconds",
        "ledger_settlement_interval_seconds",
        "export_job_interval_seconds",
        "subscription_lifecycle_interval_seconds",
        "worker_batch_limit",
        "subscription_data_retention_days",
        "tenant_admin_signature_max_skew_seconds",
        "tenant_admin_rate_limit_per_minute",
        "platform_admin_signature_max_skew_seconds",
        "platform_admin_rate_limit_per_minute",
        "rate_limit_window_seconds",
        "public_store_write_rate_limit_per_minute",
        "order_risk_recent_window_seconds",
        "order_risk_max_buyer_orders_per_window",
        "order_risk_daily_window_seconds",
        "order_risk_auto_ban_window_seconds",
        "order_risk_auto_ban_blocked_count_threshold",
        "telegram_webapp_init_data_max_age_seconds",
        "admin_web_session_max_age_seconds",
        "admin_web_binding_code_ttl_seconds",
        "admin_web_binding_code_rate_limit_per_minute",
    )
    @classmethod
    def validate_positive_int(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("必须大于 0")
        return value

    @field_validator("subscription_expiry_reminder_days")
    @classmethod
    def validate_non_negative_int(cls, value: int) -> int:
        if value < 0:
            raise ValueError("必须大于等于 0")
        return value

    @field_validator("subscription_monthly_price", "order_risk_max_buyer_amount_per_day")
    @classmethod
    def validate_positive_decimal(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("必须大于 0")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _is_sha256_hex(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _validate_public_origin(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("管理后台允许来源必须是 http/https origin")
    if parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise ValueError("管理后台允许来源只能包含 scheme、host 和 port")


def _parse_scope_values(value: Any) -> Set[str]:
    if isinstance(value, str):
        separators_normalized = value.replace("|", ",")
        return {item.strip() for item in separators_normalized.split(",") if item.strip()}
    if isinstance(value, (set, list, tuple)):
        return {str(item).strip() for item in value if str(item).strip()}
    raise ValueError("平台 Admin API Key scope 必须是字符串或列表")
