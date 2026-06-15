from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Optional, Protocol

from app.services.payments.base import PaymentQueryResult
from app.services.payments.configs import EPUSDT_PROVIDER, USDT_TRC20_DIRECT_PROVIDER, normalize_payment_provider
from app.services.payments.epay_compatible import (
    EPAY_COMPATIBLE_PROVIDER,
    LEMZF_PROVIDER,
    EpayCompatibleConfig,
    build_epay_offline_query_contract_request,
    normalize_epay_offline_query_response,
)
from app.services.payments.token188 import (
    TOKEN188_PROVIDER,
    Token188Config,
    build_token188_offline_query_contract_request,
    normalize_token188_offline_query_response,
)


class OfflinePaymentQueryTransport(Protocol):
    def send(self, request: Mapping[str, object]) -> Mapping[str, Any]:
        ...


@dataclass(frozen=True)
class OfflinePaymentQueryDryRunResult:
    provider: str
    request_payload: dict[str, str]
    query_result: PaymentQueryResult


class OfflinePaymentQueryDryRunService:
    """Run fixture-backed payment query normalization without enabling real provider queries."""

    def run(
        self,
        *,
        provider: str,
        config: Token188Config | EpayCompatibleConfig,
        out_trade_no: str,
        provider_trade_no: Optional[str] = None,
        expected_amount: Optional[Decimal] = None,
        response_payload: Optional[Mapping[str, Any]] = None,
        transport: Optional[OfflinePaymentQueryTransport] = None,
    ) -> OfflinePaymentQueryDryRunResult:
        normalized_provider = normalize_payment_provider(provider)
        if response_payload is not None and transport is not None:
            raise ValueError("离线查单 dry-run 不能同时提供响应和 transport")
        if response_payload is None and transport is None:
            raise ValueError("离线查单 dry-run 必须提供离线响应或离线 transport")

        request_payload = self._build_request(
            provider=normalized_provider,
            config=config,
            out_trade_no=out_trade_no,
            provider_trade_no=provider_trade_no,
        )
        raw_response = dict(transport.send(request_payload) if transport is not None else response_payload or {})
        query_result = self._normalize_response(
            provider=normalized_provider,
            config=config,
            response_payload=raw_response,
            out_trade_no=out_trade_no,
            expected_amount=expected_amount,
        )
        return OfflinePaymentQueryDryRunResult(
            provider=normalized_provider,
            request_payload=request_payload,
            query_result=query_result,
        )

    @staticmethod
    def _build_request(
        *,
        provider: str,
        config: Token188Config | EpayCompatibleConfig,
        out_trade_no: str,
        provider_trade_no: Optional[str],
    ) -> dict[str, str]:
        if provider == TOKEN188_PROVIDER:
            if not isinstance(config, Token188Config):
                raise ValueError("TOKEN188 离线查单配置无效")
            return build_token188_offline_query_contract_request(
                config,
                out_trade_no=out_trade_no,
                provider_trade_no=provider_trade_no,
            )
        if provider in {EPAY_COMPATIBLE_PROVIDER, LEMZF_PROVIDER}:
            if not isinstance(config, EpayCompatibleConfig) or config.provider_name != provider:
                raise ValueError("易支付离线查单配置无效")
            return build_epay_offline_query_contract_request(
                config,
                out_trade_no=out_trade_no,
                provider_trade_no=provider_trade_no,
            )
        if provider in {EPUSDT_PROVIDER, USDT_TRC20_DIRECT_PROVIDER}:
            raise ValueError("该支付 provider 不支持离线查单 dry-run")
        raise ValueError("支付 provider 不支持")

    @staticmethod
    def _normalize_response(
        *,
        provider: str,
        config: Token188Config | EpayCompatibleConfig,
        response_payload: Mapping[str, Any],
        out_trade_no: str,
        expected_amount: Optional[Decimal],
    ) -> PaymentQueryResult:
        if provider == TOKEN188_PROVIDER:
            if not isinstance(config, Token188Config):
                raise ValueError("TOKEN188 离线查单配置无效")
            return normalize_token188_offline_query_response(
                response_payload,
                config,
                expected_out_trade_no=out_trade_no,
                expected_amount=expected_amount,
            )
        if provider in {EPAY_COMPATIBLE_PROVIDER, LEMZF_PROVIDER}:
            if not isinstance(config, EpayCompatibleConfig) or config.provider_name != provider:
                raise ValueError("易支付离线查单配置无效")
            return normalize_epay_offline_query_response(
                response_payload,
                config,
                expected_out_trade_no=out_trade_no,
                expected_amount=expected_amount,
            )
        raise ValueError("支付 provider 不支持")
