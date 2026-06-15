from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.orders import PaymentProviderConfig
from app.services.payments.epay_compatible import (
    EPAY_COMPATIBLE_PROVIDER,
    LEMZF_PROVIDER,
    EpayCompatibleConfig,
    normalize_epay_gateway_url,
)
from app.services.payments.epusdt import EpusdtGmpayConfig
from app.services.payments.token188 import TOKEN188_PROVIDER, Token188Config, normalize_token188_gateway_url
from app.services.payments.trc20_direct import (
    TRON_BASE58_ALPHABET,
    TRON_BASE58_CHARS,
    TRON_BASE58_CHECK_VERSION,
    decode_base58 as _decode_base58,
    normalize_tron_address as _normalize_tron_address,
)
from app.services.token_crypto import TokenCrypto

EPUSDT_PROVIDER = "epusdt_gmpay"
USDT_TRC20_DIRECT_PROVIDER = "usdt_trc20_direct"
UNSUPPORTED_TRC20_DIRECT_CONFIG_FIELDS = {
    "gateway_url",
    "base_url",
    "merchant_id",
    "pid",
    "key",
    "secret_key",
    "return_url",
    "payment_type",
    "device",
    "subject",
    "chain_type",
    "tron_api_key",
    "tron_api_keys",
    "confirmations",
    "start_block",
    "max_blocks_per_scan",
}
TRC20_DIRECT_CONFIG_FIELDS = {
    "monitor_address",
    "token",
    "network",
    "cny_per_usdt",
    "min_usdt_amount",
    "timeout_seconds",
}
SUPPORTED_TENANT_PAYMENT_PROVIDERS = (
    EPUSDT_PROVIDER,
    TOKEN188_PROVIDER,
    EPAY_COMPATIBLE_PROVIDER,
    LEMZF_PROVIDER,
    USDT_TRC20_DIRECT_PROVIDER,
)
TENANT_DIRECT_PAYMENT_PROVIDER_PRIORITY = (
    EPUSDT_PROVIDER,
    TOKEN188_PROVIDER,
    EPAY_COMPATIBLE_PROVIDER,
    LEMZF_PROVIDER,
)


@dataclass
class EpusdtConfigStatus:
    enabled: bool
    scope_type: str
    base_url: Optional[str] = None
    pid: Optional[str] = None
    token: Optional[str] = None
    network: Optional[str] = None
    secret_configured: bool = False


@dataclass
class TenantPaymentConfigStatus:
    provider: str
    enabled: bool
    scope_type: str
    gateway_url: Optional[str] = None
    merchant_id: Optional[str] = None
    asset: Optional[str] = None
    network: Optional[str] = None
    chain_type: Optional[str] = None
    monitor_address: Optional[str] = None
    payment_type: Optional[str] = None
    device: Optional[str] = None
    subject: Optional[str] = None
    return_url: Optional[str] = None
    cny_per_usdt: Optional[str] = None
    min_usdt_amount: Optional[str] = None
    timeout_seconds: Optional[int] = None
    key_configured: bool = False


@dataclass(frozen=True)
class PaymentProviderSummary:
    provider_name: str
    display_name: str
    integration_kind: str
    contract_name: str
    production_ready: bool
    staging_verified: bool
    tenant_configurable: bool
    platform_configurable: bool
    create_payment_available: bool
    callback_available: bool
    query_order_available: bool
    reconcile_available: bool
    offline_only: bool
    supported_assets: tuple[str, ...] = ()
    supported_networks: tuple[str, ...] = ()


@dataclass(frozen=True)
class Trc20DirectConfig:
    monitor_address: str
    asset: str = "USDT"
    network: str = "TRC20"
    cny_per_usdt: Decimal = Decimal("7.00")
    min_usdt_amount: Decimal = Decimal("1.00")
    timeout_seconds: int = 3600


@dataclass
class ResolvedEpusdtConfig:
    scope_type: str
    config: EpusdtGmpayConfig


@dataclass
class ResolvedPaymentConfig:
    provider: str
    scope_type: str
    config: EpusdtGmpayConfig | Token188Config | EpayCompatibleConfig | Trc20DirectConfig


_PAYMENT_PROVIDER_METADATA = {
    EPUSDT_PROVIDER: PaymentProviderSummary(
        provider_name=EPUSDT_PROVIDER,
        display_name="epusdt GMPay",
        integration_kind="self_hosted_gateway",
        contract_name="epusdt_gmpay_v1",
        production_ready=False,
        staging_verified=False,
        tenant_configurable=True,
        platform_configurable=True,
        create_payment_available=True,
        callback_available=True,
        query_order_available=True,
        reconcile_available=True,
        offline_only=False,
        supported_assets=("USDT",),
        supported_networks=("TRC20",),
    ),
    TOKEN188_PROVIDER: PaymentProviderSummary(
        provider_name=TOKEN188_PROVIDER,
        display_name="TOKEN188",
        integration_kind="offline_payment_page",
        contract_name="token188_offline_page_v1",
        production_ready=False,
        staging_verified=False,
        tenant_configurable=True,
        platform_configurable=False,
        create_payment_available=True,
        callback_available=True,
        query_order_available=False,
        reconcile_available=False,
        offline_only=True,
        supported_assets=("USDT",),
        supported_networks=("TRX",),
    ),
    EPAY_COMPATIBLE_PROVIDER: PaymentProviderSummary(
        provider_name=EPAY_COMPATIBLE_PROVIDER,
        display_name="易支付兼容",
        integration_kind="offline_payment_page",
        contract_name="epay_compatible_offline_page_v1",
        production_ready=False,
        staging_verified=False,
        tenant_configurable=True,
        platform_configurable=False,
        create_payment_available=True,
        callback_available=True,
        query_order_available=False,
        reconcile_available=False,
        offline_only=True,
        supported_assets=("CNY", "USDT"),
        supported_networks=(),
    ),
    LEMZF_PROVIDER: PaymentProviderSummary(
        provider_name=LEMZF_PROVIDER,
        display_name="柠檬支付",
        integration_kind="offline_payment_page",
        contract_name="lemzf_offline_page_v1",
        production_ready=False,
        staging_verified=False,
        tenant_configurable=True,
        platform_configurable=False,
        create_payment_available=True,
        callback_available=True,
        query_order_available=False,
        reconcile_available=False,
        offline_only=True,
        supported_assets=("CNY", "USDT"),
        supported_networks=(),
    ),
    USDT_TRC20_DIRECT_PROVIDER: PaymentProviderSummary(
        provider_name=USDT_TRC20_DIRECT_PROVIDER,
        display_name="TRC20-USDT 直付",
        integration_kind="offline_direct_chain_config",
        contract_name="usdt_trc20_direct_offline_config_v1",
        production_ready=False,
        staging_verified=False,
        tenant_configurable=True,
        platform_configurable=False,
        create_payment_available=True,
        callback_available=False,
        query_order_available=False,
        reconcile_available=False,
        offline_only=True,
        supported_assets=("USDT",),
        supported_networks=("TRC20",),
    ),
}


class PaymentConfigService:
    async def get_epusdt_config_for_tenant(
        self,
        session: AsyncSession,
        settings: Settings,
        tenant_id: int,
    ) -> Optional[EpusdtGmpayConfig]:
        resolved = await self.resolve_epusdt_config_for_tenant(session, settings, tenant_id)
        return resolved.config if resolved is not None else None

    async def resolve_epusdt_config_for_tenant(
        self,
        session: AsyncSession,
        settings: Settings,
        tenant_id: int,
    ) -> Optional[ResolvedEpusdtConfig]:
        tenant_config = await self._get_config(session, tenant_id)
        if tenant_config is not None and tenant_config.enabled:
            data = self._decrypt_config(settings, tenant_config.config_encrypted)
            return ResolvedEpusdtConfig(
                scope_type="tenant",
                config=EpusdtGmpayConfig(
                    base_url=str(data["base_url"]),
                    pid=str(data["pid"]),
                    secret_key=str(data["secret_key"]),
                    token=str(data.get("token") or settings.epusdt_token),
                    network=str(data.get("network") or settings.epusdt_network),
                ),
            )

        if settings.epusdt_base_url and settings.epusdt_pid and settings.epusdt_secret_key:
            return ResolvedEpusdtConfig(
                scope_type="platform",
                config=EpusdtGmpayConfig(
                    base_url=settings.epusdt_base_url,
                    pid=settings.epusdt_pid,
                    secret_key=settings.epusdt_secret_key.get_secret_value(),
                    token=settings.epusdt_token,
                    network=settings.epusdt_network,
                ),
            )
        return None

    async def resolve_platform_epusdt_config(
        self,
        settings: Settings,
    ) -> Optional[ResolvedEpusdtConfig]:
        if settings.epusdt_base_url and settings.epusdt_pid and settings.epusdt_secret_key:
            return ResolvedEpusdtConfig(
                scope_type="platform",
                config=EpusdtGmpayConfig(
                    base_url=settings.epusdt_base_url,
                    pid=settings.epusdt_pid,
                    secret_key=settings.epusdt_secret_key.get_secret_value(),
                    token=settings.epusdt_token,
                    network=settings.epusdt_network,
                ),
            )
        return None

    async def resolve_tenant_payment_config_for_provider(
        self,
        session: AsyncSession,
        settings: Settings,
        tenant_id: int,
        provider: str,
    ) -> Optional[ResolvedPaymentConfig]:
        provider = normalize_payment_provider(provider)
        config = await self._get_config(session, tenant_id, provider)
        if config is None or not config.enabled:
            return None
        data = self._decrypt_config(settings, config.config_encrypted)
        return ResolvedPaymentConfig(
            provider=provider,
            scope_type="tenant",
            config=self._provider_config_from_payload(settings, provider, data),
        )

    async def resolve_first_tenant_payment_config(
        self,
        session: AsyncSession,
        settings: Settings,
        tenant_id: int,
    ) -> Optional[ResolvedPaymentConfig]:
        for provider in TENANT_DIRECT_PAYMENT_PROVIDER_PRIORITY:
            resolved = await self.resolve_tenant_payment_config_for_provider(
                session,
                settings,
                tenant_id,
                provider,
            )
            if resolved is not None:
                return resolved
        return None

    async def upsert_tenant_epusdt_config(
        self,
        session: AsyncSession,
        settings: Settings,
        tenant_id: int,
        base_url: str,
        pid: str,
        secret_key: str,
        token: Optional[str] = None,
        network: Optional[str] = None,
    ) -> None:
        payload = {
            "base_url": normalize_epusdt_base_url(base_url),
            "pid": pid,
            "secret_key": secret_key,
            "token": token or settings.epusdt_token,
            "network": network or settings.epusdt_network,
        }
        encrypted = TokenCrypto(settings).encrypt_token(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        config = await self._get_config(session, tenant_id)
        if config is None:
            session.add(
                PaymentProviderConfig(
                    scope_type="tenant",
                    tenant_id=tenant_id,
                    provider=EPUSDT_PROVIDER,
                    config_encrypted=encrypted,
                    enabled=True,
                )
            )
            await session.flush()
            return
        config.config_encrypted = encrypted
        config.enabled = True
        await session.flush()

    async def upsert_tenant_payment_config(
        self,
        session: AsyncSession,
        settings: Settings,
        tenant_id: int,
        provider: str,
        config_payload: Mapping[str, Any],
    ) -> TenantPaymentConfigStatus:
        provider = normalize_payment_provider(provider)
        payload = self._normalize_config_payload(settings, provider, config_payload)
        encrypted = TokenCrypto(settings).encrypt_token(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        config = await self._get_config(session, tenant_id, provider)
        if config is None:
            session.add(
                PaymentProviderConfig(
                    scope_type="tenant",
                    tenant_id=tenant_id,
                    provider=provider,
                    config_encrypted=encrypted,
                    enabled=True,
                )
            )
            await session.flush()
            return self._status_from_payload(provider, "tenant", True, payload)
        config.config_encrypted = encrypted
        config.enabled = True
        await session.flush()
        return self._status_from_payload(provider, "tenant", True, payload)

    async def disable_tenant_epusdt_config(self, session: AsyncSession, tenant_id: int) -> bool:
        config = await self._get_config(session, tenant_id)
        if config is None:
            return False
        config.enabled = False
        await session.flush()
        return True

    async def disable_tenant_payment_config(self, session: AsyncSession, tenant_id: int, provider: str) -> bool:
        provider = normalize_payment_provider(provider)
        config = await self._get_config(session, tenant_id, provider)
        if config is None:
            return False
        config.enabled = False
        await session.flush()
        return True

    async def get_tenant_epusdt_status(
        self,
        session: AsyncSession,
        settings: Settings,
        tenant_id: int,
    ) -> EpusdtConfigStatus:
        config = await self._get_config(session, tenant_id)
        if config is not None:
            data = self._decrypt_config(settings, config.config_encrypted)
            return EpusdtConfigStatus(
                enabled=config.enabled,
                scope_type="tenant",
                base_url=str(data.get("base_url") or ""),
                pid=str(data.get("pid") or ""),
                token=str(data.get("token") or ""),
                network=str(data.get("network") or ""),
                secret_configured=bool(data.get("secret_key")),
            )
        return EpusdtConfigStatus(
            enabled=bool(settings.epusdt_base_url and settings.epusdt_pid and settings.epusdt_secret_key),
            scope_type="platform",
            base_url=settings.epusdt_base_url,
            pid=settings.epusdt_pid,
            token=settings.epusdt_token,
            network=settings.epusdt_network,
            secret_configured=bool(settings.epusdt_secret_key),
        )

    async def get_tenant_payment_config_status(
        self,
        session: AsyncSession,
        settings: Settings,
        tenant_id: int,
        provider: str,
    ) -> TenantPaymentConfigStatus:
        provider = normalize_payment_provider(provider)
        if provider == EPUSDT_PROVIDER:
            status = await self.get_tenant_epusdt_status(session, settings, tenant_id)
            return TenantPaymentConfigStatus(
                provider=EPUSDT_PROVIDER,
                enabled=status.enabled,
                scope_type=status.scope_type,
                gateway_url=status.base_url,
                merchant_id=status.pid,
                asset=status.token,
                network=status.network,
                key_configured=status.secret_configured,
            )

        config = await self._get_config(session, tenant_id, provider)
        if config is None:
            return TenantPaymentConfigStatus(provider=provider, enabled=False, scope_type="tenant")
        data = self._decrypt_config(settings, config.config_encrypted)
        return self._status_from_payload(provider, "tenant", config.enabled, data)

    async def list_tenant_payment_provider_summaries(
        self,
    ) -> list[PaymentProviderSummary]:
        return list_payment_provider_summaries()

    async def _get_config(
        self,
        session: AsyncSession,
        tenant_id: int,
        provider: str = EPUSDT_PROVIDER,
    ) -> Optional[PaymentProviderConfig]:
        provider = normalize_payment_provider(provider)
        result = await session.execute(
            select(PaymentProviderConfig)
            .where(PaymentProviderConfig.scope_type == "tenant")
            .where(PaymentProviderConfig.tenant_id == tenant_id)
            .where(PaymentProviderConfig.provider == provider)
        )
        return result.scalar_one_or_none()

    def _decrypt_config(self, settings: Settings, encrypted: str) -> dict:
        return json.loads(TokenCrypto(settings).decrypt_token(encrypted))

    def _normalize_config_payload(
        self,
        settings: Settings,
        provider: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise ValueError("支付配置必须是对象")
        if provider == EPUSDT_PROVIDER:
            return {
                "base_url": normalize_payment_gateway_url(provider, _config_value(payload, "base_url", "gateway_url")),
                "pid": _required_config_text(_config_value(payload, "pid", "merchant_id"), "pid", max_length=128),
                "secret_key": _required_config_text(
                    _config_value(payload, "secret_key", "key"),
                    "secret_key",
                    max_length=512,
                ),
                "token": _optional_config_text(payload.get("token") or settings.epusdt_token, "token", max_length=32),
                "network": _optional_config_text(
                    payload.get("network") or settings.epusdt_network,
                    "network",
                    max_length=32,
                ),
            }
        if provider == TOKEN188_PROVIDER:
            return {
                "gateway_url": normalize_payment_gateway_url(provider, _config_value(payload, "gateway_url")),
                "merchant_id": _required_config_text(payload.get("merchant_id"), "merchant_id", max_length=128),
                "key": _required_config_text(payload.get("key"), "key", max_length=512),
                "monitor_address": _required_config_text(
                    payload.get("monitor_address"),
                    "monitor_address",
                    max_length=256,
                ),
                "chain_type": _optional_config_text(payload.get("chain_type") or "TRX", "chain_type", max_length=32),
                "return_url": _normalize_optional_public_url(payload.get("return_url"), "return_url"),
            }
        if provider in {EPAY_COMPATIBLE_PROVIDER, LEMZF_PROVIDER}:
            return {
                "gateway_url": normalize_payment_gateway_url(provider, _config_value(payload, "gateway_url")),
                "merchant_id": _required_config_text(payload.get("merchant_id"), "merchant_id", max_length=128),
                "key": _required_config_text(payload.get("key"), "key", max_length=512),
                "payment_type": _optional_config_text(
                    payload.get("payment_type") or "alipay",
                    "payment_type",
                    max_length=32,
                ),
                "device": _optional_config_text(payload.get("device") or "mobile", "device", max_length=32),
                "subject": _optional_config_text(
                    payload.get("subject") or "FakaBot Order",
                    "subject",
                    max_length=128,
                ),
                "return_url": _normalize_optional_public_url(payload.get("return_url"), "return_url"),
                "provider_name": provider,
            }
        if provider == USDT_TRC20_DIRECT_PROVIDER:
            _reject_unknown_config_fields(payload, TRC20_DIRECT_CONFIG_FIELDS)
            _reject_config_fields(payload, UNSUPPORTED_TRC20_DIRECT_CONFIG_FIELDS)
            return {
                "monitor_address": _normalize_tron_address(payload.get("monitor_address")),
                "token": _normalize_fixed_choice(payload.get("token") or "USDT", "token", {"USDT"}),
                "network": _normalize_fixed_choice(payload.get("network") or "TRC20", "network", {"TRC20"}),
                "cny_per_usdt": _normalize_decimal_config(
                    _config_value_or_default(payload, "cny_per_usdt", default="7.00"),
                    "cny_per_usdt",
                    min_value=Decimal("0.01"),
                    max_value=Decimal("1000000"),
                ),
                "min_usdt_amount": _normalize_decimal_config(
                    _config_value_or_default(payload, "min_usdt_amount", default="1.00"),
                    "min_usdt_amount",
                    min_value=Decimal("0.01"),
                    max_value=Decimal("1000000"),
                ),
                "timeout_seconds": _normalize_int_config(
                    _config_value_or_default(payload, "timeout_seconds", default=3600),
                    "timeout_seconds",
                    min_value=60,
                    max_value=86400,
                ),
            }
        raise ValueError("支付 provider 不支持")

    def _provider_config_from_payload(
        self,
        settings: Settings,
        provider: str,
        payload: Mapping[str, Any],
    ) -> EpusdtGmpayConfig | Token188Config | EpayCompatibleConfig | Trc20DirectConfig:
        data = self._normalize_config_payload(settings, provider, payload)
        if provider == EPUSDT_PROVIDER:
            return EpusdtGmpayConfig(
                base_url=str(data["base_url"]),
                pid=str(data["pid"]),
                secret_key=str(data["secret_key"]),
                token=str(data.get("token") or settings.epusdt_token),
                network=str(data.get("network") or settings.epusdt_network),
            )
        if provider == TOKEN188_PROVIDER:
            return Token188Config(
                merchant_id=str(data["merchant_id"]),
                key=str(data["key"]),
                monitor_address=str(data["monitor_address"]),
                gateway_url=str(data["gateway_url"]),
                chain_type=str(data.get("chain_type") or "TRX"),
                return_url=data.get("return_url") or None,
            )
        if provider == USDT_TRC20_DIRECT_PROVIDER:
            return Trc20DirectConfig(
                monitor_address=str(data["monitor_address"]),
                asset=str(data.get("token") or "USDT"),
                network=str(data.get("network") or "TRC20"),
                cny_per_usdt=Decimal(str(data.get("cny_per_usdt") or "7.00")),
                min_usdt_amount=Decimal(str(data.get("min_usdt_amount") or "1.00")),
                timeout_seconds=int(data.get("timeout_seconds") or 3600),
            )
        return EpayCompatibleConfig(
            merchant_id=str(data["merchant_id"]),
            key=str(data["key"]),
            gateway_url=str(data["gateway_url"]),
            payment_type=str(data.get("payment_type") or "alipay"),
            device=str(data.get("device") or "mobile"),
            return_url=data.get("return_url") or None,
            provider_name=provider,
            subject=str(data.get("subject") or "FakaBot Order"),
        )

    def _status_from_payload(
        self,
        provider: str,
        scope_type: str,
        enabled: bool,
        payload: Mapping[str, Any],
    ) -> TenantPaymentConfigStatus:
        if provider == EPUSDT_PROVIDER:
            return TenantPaymentConfigStatus(
                provider=provider,
                enabled=enabled,
                scope_type=scope_type,
                gateway_url=str(payload.get("base_url") or ""),
                merchant_id=str(payload.get("pid") or ""),
                asset=str(payload.get("token") or ""),
                network=str(payload.get("network") or ""),
                key_configured=bool(payload.get("secret_key")),
            )
        if provider == TOKEN188_PROVIDER:
            return TenantPaymentConfigStatus(
                provider=provider,
                enabled=enabled,
                scope_type=scope_type,
                gateway_url=str(payload.get("gateway_url") or ""),
                merchant_id=str(payload.get("merchant_id") or ""),
                chain_type=str(payload.get("chain_type") or ""),
                monitor_address=str(payload.get("monitor_address") or ""),
                return_url=payload.get("return_url") or None,
                key_configured=bool(payload.get("key")),
            )
        if provider == USDT_TRC20_DIRECT_PROVIDER:
            return TenantPaymentConfigStatus(
                provider=provider,
                enabled=enabled,
                scope_type=scope_type,
                asset=str(payload.get("token") or "USDT"),
                network=str(payload.get("network") or "TRC20"),
                monitor_address=str(payload.get("monitor_address") or ""),
                cny_per_usdt=str(payload.get("cny_per_usdt") or "7.00"),
                min_usdt_amount=str(payload.get("min_usdt_amount") or "1.00"),
                timeout_seconds=int(payload.get("timeout_seconds") or 3600),
                key_configured=False,
            )
        return TenantPaymentConfigStatus(
            provider=provider,
            enabled=enabled,
            scope_type=scope_type,
            gateway_url=str(payload.get("gateway_url") or ""),
            merchant_id=str(payload.get("merchant_id") or ""),
            payment_type=str(payload.get("payment_type") or ""),
            device=str(payload.get("device") or ""),
            subject=str(payload.get("subject") or ""),
            return_url=payload.get("return_url") or None,
            key_configured=bool(payload.get("key")),
        )


def normalize_epusdt_base_url(value: str) -> str:
    text = str(value).strip().rstrip("/")
    if not text:
        raise ValueError("base_url 不能为空")
    if len(text) > 512:
        raise ValueError("base_url 长度不能超过 512")
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ValueError("base_url 不能包含控制字符")
    parsed = urlsplit(text)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
        raise ValueError("base_url 必须是 http 或 https URL")
    if parsed.username or parsed.password:
        raise ValueError("base_url 不能包含用户信息")
    if parsed.query:
        raise ValueError("base_url 不能包含 query")
    if parsed.fragment:
        raise ValueError("base_url 不能包含 fragment")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", ""))


def normalize_payment_provider(provider: str) -> str:
    text = str(provider).strip().lower()
    if text == "epusdt":
        text = EPUSDT_PROVIDER
    if text not in SUPPORTED_TENANT_PAYMENT_PROVIDERS:
        raise ValueError("支付 provider 不支持")
    return text


def list_payment_provider_summaries() -> list[PaymentProviderSummary]:
    return [payment_provider_summary(provider) for provider in SUPPORTED_TENANT_PAYMENT_PROVIDERS]


def payment_provider_summary(provider: str) -> PaymentProviderSummary:
    provider = normalize_payment_provider(provider)
    return _PAYMENT_PROVIDER_METADATA[provider]


def validate_payment_provider_config_payload(provider: str, payload: Mapping[str, Any]) -> None:
    provider = normalize_payment_provider(provider)
    gateway_value = payload.get("base_url") if provider == EPUSDT_PROVIDER else payload.get("gateway_url")
    if gateway_value is not None:
        normalize_payment_gateway_url(provider, gateway_value)
    if provider == USDT_TRC20_DIRECT_PROVIDER:
        _reject_unknown_config_fields(payload, TRC20_DIRECT_CONFIG_FIELDS)
        _reject_config_fields(payload, UNSUPPORTED_TRC20_DIRECT_CONFIG_FIELDS)


def normalize_payment_gateway_url(provider: str, value: Any) -> str:
    provider = normalize_payment_provider(provider)
    if provider == EPUSDT_PROVIDER:
        return normalize_epusdt_base_url(str(value))
    if provider == TOKEN188_PROVIDER:
        normalized = normalize_token188_gateway_url(str(value)).rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.query:
            raise ValueError("TOKEN188 gateway URL 不能包含 query")
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/") or "/", "", ""))
    if provider in {EPAY_COMPATIBLE_PROVIDER, LEMZF_PROVIDER}:
        normalized = normalize_epay_gateway_url(str(value)).rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.query:
            raise ValueError("易支付 gateway URL 不能包含 query")
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/") or "/", "", ""))
    if provider == USDT_TRC20_DIRECT_PROVIDER:
        raise ValueError("TRC20 直付不使用 gateway URL")
    raise ValueError("支付 provider 不支持")


def _config_value(payload: Mapping[str, Any], *field_names: str) -> Any:
    for field_name in field_names:
        value = payload.get(field_name)
        if value is not None:
            return value
    return None


def _config_value_or_default(payload: Mapping[str, Any], field_name: str, *, default: Any) -> Any:
    value = payload.get(field_name)
    return default if value is None else value


def _reject_config_fields(payload: Mapping[str, Any], field_names: set[str]) -> None:
    present = sorted(field_name for field_name in field_names if payload.get(field_name) is not None)
    if present:
        raise ValueError(f"字段不支持: {', '.join(present)}")


def _reject_unknown_config_fields(payload: Mapping[str, Any], allowed_field_names: set[str]) -> None:
    present = sorted(
        str(field_name)
        for field_name, value in payload.items()
        if value is not None and field_name not in allowed_field_names
    )
    if present:
        raise ValueError(f"字段不支持: {', '.join(present)}")


def _required_config_text(value: Any, field_name: str, *, max_length: int) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise ValueError(f"{field_name} 不能为空")
    if len(text) > max_length:
        raise ValueError(f"{field_name} 长度不能超过 {max_length}")
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ValueError(f"{field_name} 不能包含控制字符")
    return text


def _optional_config_text(value: Any, field_name: str, *, max_length: int) -> Optional[str]:
    if value is None:
        return None
    return _required_config_text(value, field_name, max_length=max_length)


def _normalize_fixed_choice(value: Any, field_name: str, allowed_values: set[str]) -> str:
    text = _required_config_text(value, field_name, max_length=32).upper()
    if text not in allowed_values:
        raise ValueError(f"{field_name} 不支持")
    return text


def _normalize_decimal_config(
    value: Any,
    field_name: str,
    *,
    min_value: Decimal,
    max_value: Decimal,
) -> str:
    text = _required_config_text(value, field_name, max_length=64)
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} 必须是数字") from exc
    if not number.is_finite():
        raise ValueError(f"{field_name} 必须是有限数字")
    if number < min_value or number > max_value:
        raise ValueError(f"{field_name} 超出范围")
    return format(number.quantize(Decimal("0.01")), "f")


def _normalize_int_config(value: Any, field_name: str, *, min_value: int, max_value: int) -> int:
    text = _required_config_text(value, field_name, max_length=16)
    if not text.isdigit():
        raise ValueError(f"{field_name} 必须是整数")
    number = int(text)
    if number < min_value or number > max_value:
        raise ValueError(f"{field_name} 超出范围")
    return number


def _normalize_optional_public_url(value: Any, field_name: str) -> Optional[str]:
    if value is None:
        return None
    text = _required_config_text(value, field_name, max_length=512)
    parsed = urlsplit(text)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
        raise ValueError(f"{field_name} 必须是 http 或 https URL")
    if parsed.username or parsed.password:
        raise ValueError(f"{field_name} 不能包含用户信息")
    if parsed.query:
        raise ValueError(f"{field_name} 不能包含 query")
    if parsed.fragment:
        raise ValueError(f"{field_name} 不能包含 fragment")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/") or "/", "", ""))
