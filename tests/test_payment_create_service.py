from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

try:
    from app.db.models.orders import Payment
    from app.db.models.tenants import Tenant
    from app.services.payments.base import PaymentCreateResult, PaymentOrderRequest
    from app.services.payments.configs import ResolvedPaymentConfig, Trc20DirectConfig, USDT_TRC20_DIRECT_PROVIDER
    from app.services.payments.epusdt import EpusdtGmpayConfig
    from app.services.payments.token188 import TOKEN188_PROVIDER, Token188Config
    from app.services.payments.epay_compatible import EPAY_COMPATIBLE_PROVIDER, LEMZF_PROVIDER
    from app.services.payments.service import PaymentService, PaymentUnavailableError, ResolvedPaymentProvider
    from app.services.payments.trc20_direct import Trc20DirectPaymentProvider
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过支付创建服务测试：{exc.name}") from exc


class _ScalarResult:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object | None:
        return self._value


class _FakeSession:
    def __init__(self, *, order: object, tenant: object | None = None) -> None:
        self.order = order
        self.tenant = tenant
        self.added: list[object] = []
        self.flush_count = 0
        self.get_count = 0

    async def execute(self, query: object) -> _ScalarResult:
        return _ScalarResult(self.order)

    async def get(self, model: object, item_id: int) -> object | None:
        self.get_count += 1
        if model is Tenant and self.tenant is not None and self.tenant.id == item_id:
            return self.tenant
        return None

    def add(self, item: object) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        self.flush_count += 1


class _FakeProvider:
    def __init__(self, provider: str = "epusdt_gmpay") -> None:
        self.provider = provider
        self.requests: list[PaymentOrderRequest] = []

    async def create_order(self, request: PaymentOrderRequest) -> PaymentCreateResult:
        self.requests.append(request)
        return PaymentCreateResult(
            provider=self.provider,
            out_trade_no=request.out_trade_no,
            provider_trade_no="UPSTREAM-1",
            payment_url=f"https://pay.example/{request.out_trade_no}",
            raw_response={"ok": True},
        )


class _TestPaymentService(PaymentService):
    def __init__(
        self,
        provider: object | None = None,
        *,
        scope_type: str = "platform",
        existing_payment: object | None = None,
    ) -> None:
        super().__init__(SimpleNamespace(public_base_url="https://store.example"))
        self.provider = provider
        self.scope_type = scope_type
        self.existing_payment = existing_payment
        self.resolve_count = 0

    async def _resolve_epusdt_provider(self, session: object, order: object) -> ResolvedPaymentProvider | None:
        self.resolve_count += 1
        if self.provider is None:
            return None
        return ResolvedPaymentProvider(scope_type=self.scope_type, provider=self.provider)

    async def _resolve_payment_provider(
        self,
        session: object,
        order: object,
        provider_name: str | None = None,
    ) -> ResolvedPaymentProvider | None:
        return await self._resolve_epusdt_provider(session, order)

    async def _get_payment(
        self,
        session: object,
        order_id: int,
        provider: str,
        for_update: bool = False,
    ) -> object | None:
        return self.existing_payment


class PaymentCreateServiceTest(unittest.TestCase):
    def test_non_subscription_order_rejects_suspended_tenant_before_provider_resolution(self) -> None:
        order = _order(source_type="self")
        session = _FakeSession(order=order, tenant=SimpleNamespace(id=7, status="suspended"))
        service = _TestPaymentService(_FakeProvider())

        with self.assertRaisesRegex(ValueError, "店铺当前不可支付"):
            asyncio.run(service.create_payment_for_order(session, order.id))

        self.assertEqual(1, session.get_count)
        self.assertEqual(0, service.resolve_count)
        self.assertEqual([], session.added)
        self.assertEqual(0, session.flush_count)
        self.assertEqual("pending", order.status)

    def test_non_subscription_order_rejects_retention_expired_tenant_before_provider_resolution(self) -> None:
        order = _order(source_type="self")
        session = _FakeSession(order=order, tenant=SimpleNamespace(id=7, status="retention_expired"))
        service = _TestPaymentService(_FakeProvider())

        with self.assertRaisesRegex(ValueError, "店铺当前不可支付"):
            asyncio.run(service.create_payment_for_order(session, order.id))

        self.assertEqual(1, session.get_count)
        self.assertEqual(0, service.resolve_count)
        self.assertEqual([], session.added)
        self.assertEqual(0, session.flush_count)

    def test_non_subscription_order_allows_grace_tenant_payment_creation(self) -> None:
        order = _order(source_type="self")
        session = _FakeSession(order=order, tenant=SimpleNamespace(id=7, status="grace"))
        provider = _FakeProvider()
        service = _TestPaymentService(provider)

        created = asyncio.run(service.create_payment_for_order(session, order.id))

        self.assertEqual("https://pay.example/ORD123", created.payment_url)
        self.assertEqual(1, session.get_count)
        self.assertEqual(1, service.resolve_count)
        self.assertEqual(1, len(provider.requests))
        self.assertEqual(1, len(session.added))
        self.assertIsInstance(session.added[0], Payment)
        self.assertEqual(1, session.flush_count)
        self.assertEqual("epusdt_gmpay", order.payment_provider)

    def test_create_payment_for_order_wires_offline_tenant_providers_without_network(self) -> None:
        for provider_name in (TOKEN188_PROVIDER, EPAY_COMPATIBLE_PROVIDER, LEMZF_PROVIDER):
            with self.subTest(provider=provider_name):
                order = _order(source_type="self")
                session = _FakeSession(order=order, tenant=SimpleNamespace(id=7, status="active"))
                provider = _FakeProvider(provider_name)
                service = _TestPaymentService(provider, scope_type="tenant")

                created = asyncio.run(service.create_payment_for_order(session, order.id))

                self.assertEqual(provider_name, created.provider)
                self.assertEqual(provider_name, order.payment_provider)
                self.assertEqual("tenant_direct", order.payment_mode)
                self.assertEqual(1, len(provider.requests))
                self.assertEqual(
                    f"https://store.example/payments/callback/{provider_name}",
                    provider.requests[0].notify_url,
                )
                self.assertEqual(1, len(session.added))
                self.assertIsInstance(session.added[0], Payment)
                self.assertEqual(provider_name, session.added[0].provider)
                self.assertEqual(f"{provider_name}:ORD123", session.added[0].idempotency_key)
                self.assertEqual("pending", session.added[0].status)

    def test_create_payment_for_order_creates_trc20_direct_offline_intent_without_network(self) -> None:
        order = _order(source_type="self")
        session = _FakeSession(order=order, tenant=SimpleNamespace(id=7, status="active"))
        provider = Trc20DirectPaymentProvider(
            Trc20DirectConfig(
                monitor_address="T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
                min_usdt_amount=Decimal("1.00"),
            ),
            public_base_url="https://store.example",
        )
        service = _TestPaymentService(provider, scope_type="tenant")

        created = asyncio.run(
            service.create_payment_for_order(
                session,
                order.id,
                provider_name=USDT_TRC20_DIRECT_PROVIDER,
            )
        )

        self.assertEqual(USDT_TRC20_DIRECT_PROVIDER, created.provider)
        self.assertEqual("ORD123", created.out_trade_no)
        self.assertEqual(Decimal("10.00"), created.amount)
        self.assertEqual("USDT", created.currency)
        self.assertIn("/payments/trc20-direct/ORD123", created.payment_url)
        self.assertIn("address=T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb", created.payment_url)
        self.assertEqual(USDT_TRC20_DIRECT_PROVIDER, order.payment_provider)
        self.assertEqual("tenant_direct", order.payment_mode)
        self.assertEqual(1, len(session.added))
        self.assertIsInstance(session.added[0], Payment)
        self.assertEqual(USDT_TRC20_DIRECT_PROVIDER, session.added[0].provider)
        self.assertEqual(Decimal("10.00"), session.added[0].amount)
        self.assertEqual("USDT", session.added[0].currency)
        self.assertEqual("pending", session.added[0].status)
        self.assertEqual(f"{USDT_TRC20_DIRECT_PROVIDER}:ORD123", session.added[0].idempotency_key)
        self.assertEqual(1, session.flush_count)

    def test_create_payment_for_order_reuses_existing_trc20_direct_intent(self) -> None:
        order = _order(source_type="self")
        session = _FakeSession(order=order, tenant=SimpleNamespace(id=7, status="active"))
        existing_payment = SimpleNamespace(
            provider=USDT_TRC20_DIRECT_PROVIDER,
            amount=Decimal("10.00"),
            currency="USDT",
            payment_url="https://store.example/payments/trc20-direct/ORD123?address=T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb&amount=10&asset=USDT&network=TRC20",
        )
        provider = Trc20DirectPaymentProvider(
            Trc20DirectConfig(monitor_address="T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb"),
            public_base_url="https://store.example",
        )
        service = _TestPaymentService(provider, scope_type="tenant", existing_payment=existing_payment)

        created = asyncio.run(
            service.create_payment_for_order(
                session,
                order.id,
                provider_name=USDT_TRC20_DIRECT_PROVIDER,
            )
        )

        self.assertEqual(existing_payment.payment_url, created.payment_url)
        self.assertEqual(USDT_TRC20_DIRECT_PROVIDER, order.payment_provider)
        self.assertEqual("tenant_direct", order.payment_mode)
        self.assertEqual([], session.added)
        self.assertEqual(1, session.flush_count)

    def test_provider_factory_creates_trc20_direct_offline_provider(self) -> None:
        resolved = ResolvedPaymentConfig(
            provider=USDT_TRC20_DIRECT_PROVIDER,
            scope_type="tenant",
            config=Trc20DirectConfig(monitor_address="T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb"),
        )
        service = PaymentService(SimpleNamespace(public_base_url="https://store.example"))

        provider = service._provider_from_resolved_config(resolved)

        self.assertIsNotNone(provider)
        self.assertEqual("tenant", provider.scope_type)
        self.assertIsInstance(provider.provider, Trc20DirectPaymentProvider)

    def test_real_resolver_for_self_order_accepts_explicit_trc20_direct_provider(self) -> None:
        service = PaymentService(SimpleNamespace(public_base_url="https://store.example"))
        resolved_config = ResolvedPaymentConfig(
            provider=USDT_TRC20_DIRECT_PROVIDER,
            scope_type="tenant",
            config=Trc20DirectConfig(monitor_address="T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb"),
        )

        with patch("app.services.payments.service.PaymentConfigService") as config_service:
            config_service.return_value.resolve_tenant_payment_config_for_provider = AsyncMock(return_value=resolved_config)
            resolved = asyncio.run(
                service._resolve_payment_provider(
                    object(),
                    SimpleNamespace(source_type="self", tenant_id=7),
                    provider_name=USDT_TRC20_DIRECT_PROVIDER,
                )
            )

        self.assertIsNotNone(resolved)
        self.assertEqual("tenant", resolved.scope_type)
        self.assertEqual(USDT_TRC20_DIRECT_PROVIDER, resolved.provider.provider)

    def test_subscription_order_allows_suspended_tenant_and_uses_platform_payment_mode(self) -> None:
        order = _order(source_type="subscription")
        session = _FakeSession(order=order, tenant=SimpleNamespace(id=7, status="suspended"))
        provider = _FakeProvider()
        service = _TestPaymentService(provider)

        created = asyncio.run(service.create_payment_for_order(session, order.id))

        self.assertEqual("https://pay.example/ORD123", created.payment_url)
        self.assertEqual("epusdt_gmpay", order.payment_provider)
        self.assertEqual("platform_escrow", order.payment_mode)
        self.assertEqual(0, session.get_count)
        self.assertEqual(1, service.resolve_count)
        self.assertEqual(1, len(provider.requests))
        self.assertEqual(1, len(session.added))
        self.assertIsInstance(session.added[0], Payment)
        self.assertEqual("pending", session.added[0].status)
        self.assertEqual(1, session.flush_count)

    def test_real_resolver_for_subscription_order_uses_platform_provider(self) -> None:
        service = PaymentService(SimpleNamespace(public_base_url="https://store.example"))
        service._create_epusdt_provider = AsyncMock(side_effect=AssertionError("不应使用租户自收款配置"))
        resolved_config = SimpleNamespace(
            scope_type="platform",
            config=EpusdtGmpayConfig(
                base_url="https://pay.example",
                pid="platform",
                secret_key="secret",
            ),
        )

        with patch("app.services.payments.service.PaymentConfigService") as config_service:
            config_service.return_value.resolve_platform_epusdt_config = AsyncMock(return_value=resolved_config)
            resolved = asyncio.run(
                service._resolve_epusdt_provider(
                    object(),
                    SimpleNamespace(source_type="subscription", tenant_id=7),
                )
            )

        self.assertIsNotNone(resolved)
        self.assertEqual("platform", resolved.scope_type)
        self.assertEqual("epusdt_gmpay", resolved.provider.provider)
        service._create_epusdt_provider.assert_not_awaited()

    def test_real_resolver_for_self_order_uses_tenant_provider_before_epusdt_fallback(self) -> None:
        service = PaymentService(SimpleNamespace(public_base_url="https://store.example"))
        resolved_config = ResolvedPaymentConfig(
            provider=TOKEN188_PROVIDER,
            scope_type="tenant",
            config=Token188Config(
                merchant_id="merchant-1",
                key="secret-key",
                monitor_address="T123",
                gateway_url="https://pay.example/",
            ),
        )

        with patch("app.services.payments.service.PaymentConfigService") as config_service:
            config_service.return_value.resolve_first_tenant_payment_config = AsyncMock(return_value=resolved_config)
            service._resolve_epusdt_provider = AsyncMock(side_effect=AssertionError("不应回落 epusdt"))
            resolved = asyncio.run(
                service._resolve_payment_provider(
                    object(),
                    SimpleNamespace(source_type="self", tenant_id=7),
                )
            )

        self.assertIsNotNone(resolved)
        self.assertEqual("tenant", resolved.scope_type)
        self.assertEqual(TOKEN188_PROVIDER, resolved.provider.provider)
        service._resolve_epusdt_provider.assert_not_awaited()


def _order(source_type: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=55,
        tenant_id=7,
        source_type=source_type,
        status="pending",
        out_trade_no="ORD123",
        amount=Decimal("10.00"),
        currency="USDT",
        payment_mode="pending_payment",
        payment_provider=None,
        locked_inventory_item_id=None,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )


if __name__ == "__main__":
    unittest.main()
