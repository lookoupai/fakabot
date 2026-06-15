from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

try:
    from sqlalchemy.dialects import postgresql

    from app.config import Settings
    from app.db.models.external_sources import ExternalFulfillmentAttempt
    from app.db.models.orders import DeliveryRecord
    from app.db.models.tenants import AuditLog
    from app.services.external_sources import (
        ExternalDelivery,
        ExternalHttpError,
        ExternalOrder,
        ExternalOrderOperationService,
        ExternalOrderRequest,
        HTTP_ERROR_CATEGORY_RATE_LIMITED,
        HTTP_ERROR_CATEGORY_UPSTREAM_ERROR,
        register_provider,
    )
    import app.services.external_sources.registry as provider_registry
    from app.services.external_sources.auto_fulfillment import (
        ExternalAutoFulfillmentBatchResult,
        ExternalAutoFulfillmentError,
        ExternalAutoFulfillmentResult,
        ExternalAutoFulfillmentService,
        _failure_audit_metadata,
    )
    from app.services.external_sources.fulfillment import ExternalDeliveryImportResult
    from app.workers.external_fulfillment import process_paid_external_orders_once
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过外部自动履约测试：{exc.name}") from exc


class _ScalarResult:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object | None:
        return self._value


class _AllResult:
    def __init__(self, rows: list[tuple[object, object]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[object, object]]:
        return self._rows

    def first(self) -> tuple[object, object] | None:
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(
        self,
        *,
        scalar_values: list[object | None] | None = None,
        rows: list[tuple[object, object]] | None = None,
    ) -> None:
        self.scalar_values = list(scalar_values or [])
        self.rows = rows
        self.rows_used = False
        self.added: list[object] = []
        self.executed_queries: list[object] = []
        self.flush_count = 0
        self.commit_count = 0

    async def execute(self, query: object) -> _ScalarResult | _AllResult:
        self.executed_queries.append(query)
        if self.rows is not None and not self.rows_used:
            self.rows_used = True
            return _AllResult(self.rows)
        value = self.scalar_values.pop(0) if self.scalar_values else None
        return _ScalarResult(value)

    async def flush(self) -> None:
        self.flush_count += 1

    async def commit(self) -> None:
        self.commit_count += 1

    def add(self, item: object) -> None:
        self.added.append(item)


class ExternalAutoFulfillmentServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_fulfill_paid_order_creates_external_order_fetches_delivery_and_imports(self) -> None:
        order = _order()
        product = _product()
        runtime_auth = SimpleNamespace(connection_id=44)
        connection_service = SimpleNamespace(load_runtime_credentials_for_source=AsyncMock(return_value=runtime_auth))
        operation_service = SimpleNamespace(
            create_registered_order=AsyncMock(return_value=_external_order()),
            fetch_registered_delivery=AsyncMock(return_value=_delivery()),
        )
        import_service = SimpleNamespace(
            import_delivery=AsyncMock(
                return_value=ExternalDeliveryImportResult(
                    out_trade_no="ORD123",
                    order_status="paid",
                    delivery_record_id=88,
                    item_count=2,
                    imported=True,
                )
            )
        )
        service = ExternalAutoFulfillmentService(
            connection_service=connection_service,
            operation_service=operation_service,
            import_service=import_service,
        )
        session = _FakeSession(scalar_values=[None])
        settings = Settings()

        with patch(
            "app.services.external_sources.auto_fulfillment.is_provider_auto_fulfillment_available",
            return_value=True,
        ):
            result = await service.fulfill_paid_order(
                session,
                order=order,
                product=product,
                settings=settings,
            )

        self.assertTrue(result.imported)
        self.assertEqual("EXT-1", result.external_order_id)
        self.assertEqual(88, result.delivery_record_id)
        self.assertEqual(2, result.item_count)
        attempts = _attempts(session)
        self.assertEqual(1, len(attempts))
        self.assertEqual("auto", attempts[0].attempt_source)
        self.assertEqual("succeeded", attempts[0].status)
        self.assertEqual(44, attempts[0].connection_id)
        self.assertEqual("EXT-1", attempts[0].external_order_id)
        self.assertEqual(88, attempts[0].delivery_record_id)
        self.assertEqual(2, attempts[0].item_count)
        self.assertTrue(attempts[0].imported)
        connection_service.load_runtime_credentials_for_source.assert_awaited_once_with(
            session,
            tenant_id=7,
            provider_name="acg",
            source_key="main",
            settings=settings,
        )
        create_kwargs = operation_service.create_registered_order.await_args.kwargs
        self.assertEqual(7, create_kwargs["tenant_id"])
        self.assertEqual("acg", create_kwargs["provider_name"])
        self.assertEqual("main", create_kwargs["source_key"])
        self.assertEqual(44, create_kwargs["connection_id"])
        self.assertIs(runtime_auth, create_kwargs["runtime_auth"])
        request = create_kwargs["request"]
        self.assertEqual("sku-1", request.external_product_id)
        self.assertEqual("ORD123", request.out_trade_no)
        fetch_kwargs = operation_service.fetch_registered_delivery.await_args.kwargs
        self.assertEqual("EXT-1", fetch_kwargs["external_order_id"])
        import_service.import_delivery.assert_awaited_once_with(
            session,
            tenant_id=7,
            out_trade_no="ORD123",
            provider_name="acg",
            source_key="main",
            delivery=_delivery(),
            settings=settings,
        )

    async def test_fulfill_paid_order_transitions_attempt_to_succeeded_without_sensitive_payload(self) -> None:
        order = _order(out_trade_no="ORD-AUTO-ATTEMPT")
        product = _product()
        service = ExternalAutoFulfillmentService(
            connection_service=SimpleNamespace(
                load_runtime_credentials_for_source=AsyncMock(return_value=SimpleNamespace(connection_id=44))
            ),
            operation_service=SimpleNamespace(
                create_registered_order=AsyncMock(return_value=_external_order()),
                fetch_registered_delivery=AsyncMock(return_value=_delivery()),
            ),
            import_service=SimpleNamespace(
                import_delivery=AsyncMock(
                    return_value=ExternalDeliveryImportResult(
                        out_trade_no=order.out_trade_no,
                        order_status="paid",
                        delivery_record_id=88,
                        item_count=2,
                        imported=True,
                    )
                )
            ),
        )
        session = _FakeSession(scalar_values=[None])

        with patch(
            "app.services.external_sources.auto_fulfillment.is_provider_auto_fulfillment_available",
            return_value=True,
        ):
            await service.fulfill_paid_order(session, order=order, product=product, settings=Settings())

        attempts = _attempts(session)
        self.assertEqual(1, len(attempts))
        attempt = attempts[0]
        self.assertEqual("auto", attempt.attempt_source)
        self.assertEqual("succeeded", attempt.status)
        self.assertTrue(attempt.imported)
        self.assertEqual(order.id, attempt.order_id)
        self.assertEqual(order.out_trade_no, attempt.out_trade_no)
        self.assertEqual("acg", attempt.provider_name)
        self.assertEqual("main", attempt.source_key)
        self.assertEqual("sku-1", attempt.external_product_id)
        self.assertEqual("EXT-1", attempt.external_order_id)
        self.assertIsNotNone(attempt.started_at)
        self.assertIsNotNone(attempt.finished_at)
        self.assertGreaterEqual(attempt.finished_at, attempt.started_at)
        self.assertNotIn("card-a", str(attempt.__dict__))
        self.assertNotIn("token", str(attempt.__dict__).lower())
        self.assertNotIn("secret", str(attempt.__dict__).lower())
        self.assertNotIn("raw_payload", str(attempt.__dict__).lower())

    async def test_fulfill_paid_order_reuses_existing_delivery_without_provider_call(self) -> None:
        existing = DeliveryRecord(
            id=66,
            order_id=12,
            tenant_id=7,
            buyer_telegram_user_id=42,
            delivery_type="card_pool",
            status="pending",
        )
        operation_service = SimpleNamespace(
            create_registered_order=AsyncMock(),
            fetch_registered_delivery=AsyncMock(),
        )
        service = ExternalAutoFulfillmentService(
            connection_service=SimpleNamespace(load_runtime_credentials_for_source=AsyncMock()),
            operation_service=operation_service,
            import_service=SimpleNamespace(import_delivery=AsyncMock()),
        )

        session = _FakeSession(scalar_values=[existing])

        result = await service.fulfill_paid_order(
            session,
            order=_order(),
            product=_product(),
            settings=Settings(),
        )

        self.assertFalse(result.imported)
        self.assertEqual(66, result.delivery_record_id)
        attempts = _attempts(session)
        self.assertEqual(1, len(attempts))
        self.assertEqual("auto", attempts[0].attempt_source)
        self.assertEqual("already_delivered", attempts[0].status)
        self.assertEqual(66, attempts[0].delivery_record_id)
        self.assertEqual([], [item for item in session.added if isinstance(item, AuditLog)])
        service._connection_service.load_runtime_credentials_for_source.assert_not_awaited()
        operation_service.create_registered_order.assert_not_awaited()
        operation_service.fetch_registered_delivery.assert_not_awaited()
        service._import_service.import_delivery.assert_not_awaited()

    async def test_process_paid_external_orders_reuses_existing_delivery_record_when_replayed(self) -> None:
        order = _order(out_trade_no="ORD-REPLAY")
        product = _product()
        existing = DeliveryRecord(
            id=66,
            order_id=order.id,
            tenant_id=order.tenant_id,
            buyer_telegram_user_id=order.buyer_telegram_user_id,
            delivery_type="card_pool",
            status="pending",
        )
        connection_service = SimpleNamespace(load_runtime_credentials_for_source=AsyncMock())
        operation_service = SimpleNamespace(
            create_registered_order=AsyncMock(),
            fetch_registered_delivery=AsyncMock(),
        )
        import_service = SimpleNamespace(import_delivery=AsyncMock())
        service = ExternalAutoFulfillmentService(
            connection_service=connection_service,
            operation_service=operation_service,
            import_service=import_service,
        )
        session = _FakeSession(rows=[(order, product)], scalar_values=[existing])

        with patch(
            "app.services.external_sources.auto_fulfillment.is_provider_auto_fulfillment_available",
            side_effect=AssertionError("已有发货记录不应再检查 provider 自动履约能力"),
        ):
            result = await service.process_paid_external_orders(session, settings=Settings(), limit=10)

        self.assertEqual(1, result.checked_count)
        self.assertEqual(0, result.imported_count)
        self.assertEqual(0, result.failed_count)
        self.assertEqual([66], result.delivery_record_ids)
        connection_service.load_runtime_credentials_for_source.assert_not_awaited()
        operation_service.create_registered_order.assert_not_awaited()
        operation_service.fetch_registered_delivery.assert_not_awaited()
        import_service.import_delivery.assert_not_awaited()
        attempts = _attempts(session)
        self.assertEqual(1, len(attempts))
        self.assertEqual("auto", attempts[0].attempt_source)
        self.assertEqual("already_delivered", attempts[0].status)
        self.assertEqual(66, attempts[0].delivery_record_id)
        self.assertEqual([], [item for item in session.added if isinstance(item, AuditLog)])
        self.assertEqual(1, session.flush_count)

    async def test_fulfill_tenant_paid_order_imports_single_order_with_safe_attempt_summary(self) -> None:
        order = _order(out_trade_no="ORD-MANUAL")
        product = _product()
        runtime_auth = SimpleNamespace(connection_id=44)
        connection_service = SimpleNamespace(load_runtime_credentials_for_source=AsyncMock(return_value=runtime_auth))
        operation_service = SimpleNamespace(
            create_registered_order=AsyncMock(return_value=_external_order()),
            fetch_registered_delivery=AsyncMock(return_value=_delivery()),
        )
        import_service = SimpleNamespace(
            import_delivery=AsyncMock(
                return_value=ExternalDeliveryImportResult(
                    out_trade_no=order.out_trade_no,
                    order_status="paid",
                    delivery_record_id=88,
                    item_count=2,
                    imported=True,
                )
            )
        )
        service = ExternalAutoFulfillmentService(
            connection_service=connection_service,
            operation_service=operation_service,
            import_service=import_service,
        )
        session = _FakeSession(rows=[(order, product)], scalar_values=[None])

        with patch(
            "app.services.external_sources.auto_fulfillment.is_provider_auto_fulfillment_available",
            return_value=True,
        ):
            result = await service.fulfill_tenant_paid_order(
                session,
                tenant_id=7,
                out_trade_no=order.out_trade_no,
                settings=Settings(),
            )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual("succeeded", result.attempt_status)
        self.assertEqual(order.out_trade_no, result.out_trade_no)
        self.assertEqual("acg", result.provider_name)
        self.assertEqual("main", result.source_key)
        self.assertEqual("EXT-1", result.external_order_id)
        self.assertEqual(88, result.delivery_record_id)
        self.assertEqual(2, result.item_count)
        self.assertTrue(result.imported)
        self.assertFalse(result.failure_recorded)
        self.assertIsNone(result.failure_stage)
        attempts = _attempts(session)
        self.assertEqual(1, len(attempts))
        self.assertEqual("manual", attempts[0].attempt_source)
        self.assertEqual("succeeded", attempts[0].status)
        self.assertEqual(order.id, attempts[0].order_id)
        self.assertEqual(order.out_trade_no, attempts[0].out_trade_no)
        self.assertEqual("acg", attempts[0].provider_name)
        self.assertEqual("main", attempts[0].source_key)
        self.assertEqual("sku-1", attempts[0].external_product_id)
        self.assertEqual("EXT-1", attempts[0].external_order_id)
        self.assertEqual(88, attempts[0].delivery_record_id)
        self.assertEqual(2, attempts[0].item_count)
        self.assertTrue(attempts[0].imported)
        self.assertIsNone(attempts[0].failure_stage)
        operation_service.create_registered_order.assert_awaited_once()
        operation_service.fetch_registered_delivery.assert_awaited_once()
        import_service.import_delivery.assert_awaited_once()

    async def test_fulfill_tenant_paid_order_returns_none_for_missing_order(self) -> None:
        service = ExternalAutoFulfillmentService()
        result = await service.fulfill_tenant_paid_order(
            _FakeSession(rows=[]),
            tenant_id=7,
            out_trade_no="ORD404",
            settings=Settings(),
        )

        self.assertIsNone(result)

    async def test_fulfill_tenant_paid_order_reuses_existing_delivery_without_provider_call(self) -> None:
        order = _order(out_trade_no="ORD-MANUAL-REPLAY")
        product = _product()
        existing = DeliveryRecord(
            id=66,
            order_id=order.id,
            tenant_id=order.tenant_id,
            buyer_telegram_user_id=order.buyer_telegram_user_id,
            delivery_type="card_pool",
            status="pending",
        )
        operation_service = SimpleNamespace(
            create_registered_order=AsyncMock(),
            fetch_registered_delivery=AsyncMock(),
        )
        service = ExternalAutoFulfillmentService(
            connection_service=SimpleNamespace(load_runtime_credentials_for_source=AsyncMock()),
            operation_service=operation_service,
            import_service=SimpleNamespace(import_delivery=AsyncMock()),
        )

        session = _FakeSession(rows=[(order, product)], scalar_values=[existing])

        result = await service.fulfill_tenant_paid_order(
            session,
            tenant_id=7,
            out_trade_no=order.out_trade_no,
            settings=Settings(),
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual("already_delivered", result.attempt_status)
        self.assertEqual(66, result.delivery_record_id)
        self.assertFalse(result.imported)
        attempts = _attempts(session)
        self.assertEqual(1, len(attempts))
        self.assertEqual("manual", attempts[0].attempt_source)
        self.assertEqual("already_delivered", attempts[0].status)
        self.assertEqual(66, attempts[0].delivery_record_id)
        service._connection_service.load_runtime_credentials_for_source.assert_not_awaited()
        operation_service.create_registered_order.assert_not_awaited()
        operation_service.fetch_registered_delivery.assert_not_awaited()
        service._import_service.import_delivery.assert_not_awaited()

    async def test_fulfill_tenant_paid_order_records_safe_manual_failure_summary(self) -> None:
        order = _order(out_trade_no="ORD-MANUAL-FAIL")
        product = _product()
        connection_service = SimpleNamespace(load_runtime_credentials_for_source=AsyncMock(return_value=None))
        operation_service = SimpleNamespace(
            create_registered_order=AsyncMock(),
            fetch_registered_delivery=AsyncMock(),
        )
        service = ExternalAutoFulfillmentService(
            connection_service=connection_service,
            operation_service=operation_service,
            import_service=SimpleNamespace(import_delivery=AsyncMock()),
        )
        session = _FakeSession(rows=[(order, product)], scalar_values=[None, None])

        with patch(
            "app.services.external_sources.auto_fulfillment.is_provider_auto_fulfillment_available",
            return_value=True,
        ):
            result = await service.fulfill_tenant_paid_order(
                session,
                tenant_id=7,
                out_trade_no=order.out_trade_no,
                settings=Settings(),
            )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual("failed", result.attempt_status)
        self.assertEqual("load_credentials", result.failure_stage)
        self.assertEqual("connection_missing", result.failure_category)
        self.assertFalse(result.failure_retryable)
        self.assertTrue(result.failure_recorded)
        operation_service.create_registered_order.assert_not_awaited()
        operation_service.fetch_registered_delivery.assert_not_awaited()
        audits = [item for item in session.added if isinstance(item, AuditLog)]
        self.assertEqual(1, len(audits))
        attempts = _attempts(session)
        self.assertEqual(1, len(attempts))
        self.assertEqual("manual", attempts[0].attempt_source)
        self.assertEqual("failed", attempts[0].status)
        self.assertEqual("load_credentials", attempts[0].failure_stage)
        self.assertEqual("connection_missing", attempts[0].failure_category)
        self.assertFalse(attempts[0].failure_retryable)
        self.assertNotIn("token", str(attempts[0].__dict__).lower())
        self.assertNotIn("secret", str(attempts[0].__dict__).lower())
        self.assertNotIn("raw_payload", str(attempts[0].__dict__).lower())
        audit = audits[0]
        self.assertFalse(audit.metadata_json["auto"])
        self.assertTrue(audit.metadata_json["manual"])
        self.assertEqual("connection_missing", audit.metadata_json["failure_category"])
        self.assertNotIn("token", str(audit.metadata_json).lower())
        self.assertNotIn("secret", str(audit.metadata_json).lower())
        self.assertNotIn("raw_payload", str(audit.metadata_json).lower())
        self.assertNotIn("runtime_auth", str(audit.metadata_json).lower())

    async def test_fulfill_tenant_paid_order_repeated_same_failure_does_not_add_duplicate_audit(self) -> None:
        order = _order(out_trade_no="ORD-MANUAL-DUP")
        product = _product()
        error = ExternalAutoFulfillmentError(
            "外部源连接不可用",
            stage="load_credentials",
            category="connection_missing",
        )
        latest_audit = AuditLog(
            tenant_id=order.tenant_id,
            action="external_fulfillment.failed",
            target_type="order",
            target_id=str(order.id),
            metadata_json=_failure_audit_metadata(order, product, error, auto=False),
        )
        service = ExternalAutoFulfillmentService(
            connection_service=SimpleNamespace(load_runtime_credentials_for_source=AsyncMock(return_value=None)),
            operation_service=SimpleNamespace(
                create_registered_order=AsyncMock(),
                fetch_registered_delivery=AsyncMock(),
            ),
            import_service=SimpleNamespace(import_delivery=AsyncMock()),
        )
        session = _FakeSession(rows=[(order, product)], scalar_values=[None, latest_audit])

        with patch(
            "app.services.external_sources.auto_fulfillment.is_provider_auto_fulfillment_available",
            return_value=True,
        ):
            result = await service.fulfill_tenant_paid_order(
                session,
                tenant_id=7,
                out_trade_no=order.out_trade_no,
                settings=Settings(),
            )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual("failed", result.attempt_status)
        self.assertFalse(result.failure_recorded)
        attempts = _attempts(session)
        self.assertEqual(1, len(attempts))
        self.assertEqual("manual", attempts[0].attempt_source)
        self.assertEqual("failed", attempts[0].status)
        self.assertEqual("load_credentials", attempts[0].failure_stage)
        self.assertEqual([], [item for item in session.added if isinstance(item, AuditLog)])

    async def test_registered_idempotent_provider_replay_uses_same_out_trade_no_and_local_delivery_gate(self) -> None:
        previous_providers = dict(provider_registry._providers)
        provider_registry._providers.clear()
        provider = _ReplayIdempotentProvider()
        register_provider(provider)
        order = _order(out_trade_no="ORD-IDEMPOTENT")
        product = _product(external_source=provider.provider)
        runtime_auth = SimpleNamespace(
            tenant_id=7,
            connection_id=44,
            provider_name=provider.provider,
            source_key="main",
            credentials={"api_key": "secret-value"},
        )
        connection_service = SimpleNamespace(load_runtime_credentials_for_source=AsyncMock(return_value=runtime_auth))
        import_service = SimpleNamespace(
            import_delivery=AsyncMock(
                return_value=ExternalDeliveryImportResult(
                    out_trade_no=order.out_trade_no,
                    order_status="paid",
                    delivery_record_id=88,
                    item_count=1,
                    imported=True,
                )
            )
        )
        operation_service = ExternalOrderOperationService()
        service = ExternalAutoFulfillmentService(
            connection_service=connection_service,
            operation_service=operation_service,
            import_service=import_service,
        )
        try:
            first = await service.fulfill_paid_order(
                _FakeSession(scalar_values=[None]),
                order=order,
                product=product,
                settings=Settings(),
            )
            direct_replay = await operation_service.create_registered_order(
                tenant_id=7,
                provider_name=provider.provider,
                source_key="main",
                connection_id=44,
                runtime_auth=runtime_auth,
                request=ExternalOrderRequest(
                    external_product_id=product.external_id,
                    quantity=1,
                    out_trade_no=order.out_trade_no,
                ),
            )
            existing = DeliveryRecord(
                id=88,
                order_id=order.id,
                tenant_id=order.tenant_id,
                buyer_telegram_user_id=order.buyer_telegram_user_id,
                delivery_type="card_pool",
                status="pending",
            )
            replay = await service.fulfill_paid_order(
                _FakeSession(scalar_values=[existing]),
                order=order,
                product=product,
                settings=Settings(),
            )
        finally:
            provider_registry._providers.clear()
            provider_registry._providers.update(previous_providers)

        self.assertEqual("EXT-IDEMPOTENT", first.external_order_id)
        self.assertEqual("EXT-IDEMPOTENT", direct_replay.external_order_id)
        self.assertEqual(88, replay.delivery_record_id)
        self.assertFalse(replay.imported)
        self.assertEqual(2, provider.create_count)
        self.assertEqual(1, provider.fetch_count)
        self.assertEqual(1, connection_service.load_runtime_credentials_for_source.await_count)
        import_service.import_delivery.assert_awaited_once()

    async def test_fulfill_paid_order_requires_provider_auto_fulfillment_opt_in_before_credential_load_or_provider_call(
        self,
    ) -> None:
        connection_service = SimpleNamespace(load_runtime_credentials_for_source=AsyncMock())
        operation_service = SimpleNamespace(
            create_registered_order=AsyncMock(),
            fetch_registered_delivery=AsyncMock(),
        )
        import_service = SimpleNamespace(import_delivery=AsyncMock())
        service = ExternalAutoFulfillmentService(
            connection_service=connection_service,
            operation_service=operation_service,
            import_service=import_service,
        )

        with patch(
            "app.services.external_sources.auto_fulfillment.is_provider_auto_fulfillment_available",
            return_value=False,
        ):
            with self.assertRaisesRegex(ValueError, "未声明") as caught:
                await service.fulfill_paid_order(
                    _FakeSession(scalar_values=[None]),
                    order=_order(),
                    product=_product(),
                    settings=Settings(),
                )

        self.assertEqual("provider_capability", caught.exception.stage)
        self.assertEqual("auto_fulfillment_not_enabled", caught.exception.category)
        self.assertFalse(caught.exception.retryable)
        connection_service.load_runtime_credentials_for_source.assert_not_awaited()
        operation_service.create_registered_order.assert_not_awaited()
        operation_service.fetch_registered_delivery.assert_not_awaited()
        import_service.import_delivery.assert_not_awaited()

    async def test_process_paid_external_orders_counts_success_and_failure(self) -> None:
        order_a = _order(order_id=12, out_trade_no="ORD-A")
        order_b = _order(order_id=13, out_trade_no="ORD-B")
        product = _product()
        service = _BatchService()
        session = _FakeSession(rows=[(order_a, product), (order_b, product)])

        result = await service.process_paid_external_orders(session, settings=Settings(), limit=10)

        self.assertEqual(2, result.checked_count)
        self.assertEqual(1, result.imported_count)
        self.assertEqual(1, result.failed_count)
        self.assertEqual([501], result.delivery_record_ids)
        audits = [item for item in session.added if isinstance(item, AuditLog)]
        self.assertEqual(1, len(audits))
        audit = audits[0]
        self.assertEqual(7, audit.tenant_id)
        self.assertIsNone(audit.actor_user_id)
        self.assertEqual("external_fulfillment.failed", audit.action)
        self.assertEqual("order", audit.target_type)
        self.assertEqual("13", audit.target_id)
        self.assertEqual(13, audit.metadata_json["order_id"])
        self.assertEqual("ORD-B", audit.metadata_json["out_trade_no"])
        self.assertEqual(101, audit.metadata_json["product_id"])
        self.assertEqual("acg", audit.metadata_json["provider_name"])
        self.assertEqual("main", audit.metadata_json["source"])
        self.assertEqual("sku-1", audit.metadata_json["external_product_id"])
        self.assertEqual("外部履约失败", audit.metadata_json["failure_reason"])
        self.assertEqual("unknown", audit.metadata_json["failure_stage"])
        self.assertEqual("unknown", audit.metadata_json["failure_category"])
        self.assertFalse(audit.metadata_json["failure_retryable"])
        self.assertEqual(64, len(audit.metadata_json["failure_fingerprint"]))
        self.assertTrue(audit.metadata_json["auto"])
        self.assertNotIn("token", str(audit.metadata_json).lower())
        self.assertNotIn("secret", str(audit.metadata_json).lower())
        self.assertNotIn("payload", str(audit.metadata_json).lower())
        attempts = _attempts(session)
        self.assertEqual(1, len(attempts))
        self.assertEqual("auto", attempts[0].attempt_source)
        self.assertEqual("failed", attempts[0].status)
        self.assertEqual(order_b.id, attempts[0].order_id)
        self.assertEqual(order_b.out_trade_no, attempts[0].out_trade_no)
        self.assertEqual("unknown", attempts[0].failure_stage)
        self.assertEqual("unknown", attempts[0].failure_category)
        self.assertEqual(64, len(attempts[0].failure_fingerprint or ""))
        self.assertEqual(1, session.flush_count)

    async def test_fulfill_paid_order_records_already_delivered_attempt_when_import_service_replays(self) -> None:
        order = _order(out_trade_no="ORD-IMPORT-REPLAY")
        product = _product()
        service = ExternalAutoFulfillmentService(
            connection_service=SimpleNamespace(
                load_runtime_credentials_for_source=AsyncMock(return_value=SimpleNamespace(connection_id=44))
            ),
            operation_service=SimpleNamespace(
                create_registered_order=AsyncMock(return_value=_external_order()),
                fetch_registered_delivery=AsyncMock(return_value=_delivery()),
            ),
            import_service=SimpleNamespace(
                import_delivery=AsyncMock(
                    return_value=ExternalDeliveryImportResult(
                        out_trade_no=order.out_trade_no,
                        order_status="paid",
                        delivery_record_id=88,
                        item_count=0,
                        imported=False,
                    )
                )
            ),
        )
        session = _FakeSession(scalar_values=[None])

        with patch(
            "app.services.external_sources.auto_fulfillment.is_provider_auto_fulfillment_available",
            return_value=True,
        ):
            result = await service.fulfill_paid_order(session, order=order, product=product, settings=Settings())

        self.assertFalse(result.imported)
        self.assertEqual(88, result.delivery_record_id)
        attempts = _attempts(session)
        self.assertEqual(1, len(attempts))
        attempt = attempts[0]
        self.assertEqual("auto", attempt.attempt_source)
        self.assertEqual("already_delivered", attempt.status)
        self.assertEqual(44, attempt.connection_id)
        self.assertEqual("EXT-1", attempt.external_order_id)
        self.assertEqual(88, attempt.delivery_record_id)
        self.assertEqual(0, attempt.item_count)
        self.assertFalse(attempt.imported)

    async def test_process_paid_external_orders_locks_only_order_rows_on_postgresql(self) -> None:
        session = _FakeSession(rows=[])

        result = await ExternalAutoFulfillmentService().process_paid_external_orders(
            session,
            settings=Settings(),
            limit=10,
        )

        self.assertEqual(0, result.checked_count)
        self.assertEqual(1, len(session.executed_queries))
        sql = str(
            session.executed_queries[0].compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("FOR UPDATE OF orders SKIP LOCKED", sql)
        self.assertIn("orders.status = 'paid'", sql)
        self.assertIn("delivery_records.id IS NULL", sql)
        self.assertIn("products.delivery_type IN ('card_pool', 'card_fixed')", sql)

    async def test_fulfill_paid_order_requires_active_runtime_connection_before_provider_call(self) -> None:
        operation_service = SimpleNamespace(
            create_registered_order=AsyncMock(),
            fetch_registered_delivery=AsyncMock(),
        )
        service = ExternalAutoFulfillmentService(
            connection_service=SimpleNamespace(load_runtime_credentials_for_source=AsyncMock(return_value=None)),
            operation_service=operation_service,
            import_service=SimpleNamespace(import_delivery=AsyncMock()),
        )

        with patch(
            "app.services.external_sources.auto_fulfillment.is_provider_auto_fulfillment_available",
            return_value=True,
        ):
            with self.assertRaisesRegex(ValueError, "外部源连接不可用") as caught:
                await service.fulfill_paid_order(
                    _FakeSession(scalar_values=[None]),
                    order=_order(),
                    product=_product(),
                    settings=Settings(),
                )

        self.assertEqual("load_credentials", caught.exception.stage)
        self.assertEqual("connection_missing", caught.exception.category)
        operation_service.create_registered_order.assert_not_awaited()
        operation_service.fetch_registered_delivery.assert_not_awaited()

    async def test_process_paid_external_orders_audits_runtime_credentials_load_error_without_details(self) -> None:
        order = _order(out_trade_no="ORD-CREDENTIALS")
        product = _product()
        connection_service = SimpleNamespace(
            load_runtime_credentials_for_source=AsyncMock(
                side_effect=ValueError("外部源连接未启用 token=plain-token secret=plain-secret")
            )
        )
        operation_service = SimpleNamespace(
            create_registered_order=AsyncMock(),
            fetch_registered_delivery=AsyncMock(),
        )
        import_service = SimpleNamespace(import_delivery=AsyncMock())
        service = ExternalAutoFulfillmentService(
            connection_service=connection_service,
            operation_service=operation_service,
            import_service=import_service,
        )
        session = _FakeSession(rows=[(order, product)])

        with patch(
            "app.services.external_sources.auto_fulfillment.is_provider_auto_fulfillment_available",
            return_value=True,
        ):
            result = await service.process_paid_external_orders(session, settings=Settings(), limit=10)

        self.assertEqual(1, result.checked_count)
        self.assertEqual(0, result.imported_count)
        self.assertEqual(1, result.failed_count)
        operation_service.create_registered_order.assert_not_awaited()
        operation_service.fetch_registered_delivery.assert_not_awaited()
        import_service.import_delivery.assert_not_awaited()
        audit = next(item for item in session.added if isinstance(item, AuditLog))
        self.assertEqual("load_credentials", audit.metadata_json["failure_stage"])
        self.assertEqual("credentials_load_failed", audit.metadata_json["failure_category"])
        self.assertFalse(audit.metadata_json["failure_retryable"])
        self.assertEqual("外部源运行时凭据加载失败", audit.metadata_json["failure_reason"])
        self.assertNotIn("plain-token", str(audit.metadata_json))
        self.assertNotIn("plain-secret", str(audit.metadata_json))

    async def test_process_paid_external_orders_audits_missing_runtime_connection_without_provider_call(self) -> None:
        order = _order(out_trade_no="ORD-NO-CONNECTION")
        product = _product()
        connection_service = SimpleNamespace(
            load_runtime_credentials_for_source=AsyncMock(return_value=None)
        )
        operation_service = SimpleNamespace(
            create_registered_order=AsyncMock(),
            fetch_registered_delivery=AsyncMock(),
        )
        import_service = SimpleNamespace(import_delivery=AsyncMock())
        service = ExternalAutoFulfillmentService(
            connection_service=connection_service,
            operation_service=operation_service,
            import_service=import_service,
        )
        session = _FakeSession(rows=[(order, product)])

        with patch(
            "app.services.external_sources.auto_fulfillment.is_provider_auto_fulfillment_available",
            return_value=True,
        ):
            result = await service.process_paid_external_orders(session, settings=Settings(), limit=10)

        self.assertEqual(1, result.checked_count)
        self.assertEqual(0, result.imported_count)
        self.assertEqual(1, result.failed_count)
        connection_service.load_runtime_credentials_for_source.assert_awaited_once()
        operation_service.create_registered_order.assert_not_awaited()
        operation_service.fetch_registered_delivery.assert_not_awaited()
        import_service.import_delivery.assert_not_awaited()
        audit = next(item for item in session.added if isinstance(item, AuditLog))
        self.assertEqual("load_credentials", audit.metadata_json["failure_stage"])
        self.assertEqual("connection_missing", audit.metadata_json["failure_category"])
        self.assertFalse(audit.metadata_json["failure_retryable"])
        self.assertEqual("外部源连接不可用", audit.metadata_json["failure_reason"])
        self.assertNotIn("runtime_auth", str(audit.metadata_json).lower())
        self.assertNotIn("token", str(audit.metadata_json).lower())
        self.assertNotIn("secret", str(audit.metadata_json).lower())

    async def test_process_paid_external_orders_audits_http_error_classification_without_details(self) -> None:
        order = _order(out_trade_no="ORD-HTTP")
        product = _product()
        service = ExternalAutoFulfillmentService(
            connection_service=SimpleNamespace(
                load_runtime_credentials_for_source=AsyncMock(return_value=SimpleNamespace(connection_id=44))
            ),
            operation_service=SimpleNamespace(
                create_registered_order=AsyncMock(
                    side_effect=ExternalHttpError(
                        "provider body token=plain-token secret=plain-secret",
                        status_code=429,
                        category=HTTP_ERROR_CATEGORY_RATE_LIMITED,
                        retryable=True,
                    )
                ),
                fetch_registered_delivery=AsyncMock(),
            ),
            import_service=SimpleNamespace(import_delivery=AsyncMock()),
        )
        session = _FakeSession(rows=[(order, product)])

        with patch(
            "app.services.external_sources.auto_fulfillment.is_provider_auto_fulfillment_available",
            return_value=True,
        ):
            result = await service.process_paid_external_orders(session, settings=Settings(), limit=10)

        self.assertEqual(1, result.checked_count)
        self.assertEqual(0, result.imported_count)
        self.assertEqual(1, result.failed_count)
        audit = next(item for item in session.added if isinstance(item, AuditLog))
        self.assertEqual("12", audit.target_id)
        self.assertEqual("外部履约失败", audit.metadata_json["failure_reason"])
        self.assertEqual("create_order", audit.metadata_json["failure_stage"])
        self.assertEqual(HTTP_ERROR_CATEGORY_RATE_LIMITED, audit.metadata_json["failure_category"])
        self.assertTrue(audit.metadata_json["failure_retryable"])
        self.assertEqual(44, audit.metadata_json["connection_id"])
        self.assertEqual("sku-1", audit.metadata_json["external_product_id"])
        self.assertEqual(429, audit.metadata_json["upstream_status_code"])
        self.assertEqual(64, len(audit.metadata_json["failure_fingerprint"]))
        self.assertNotIn("plain-token", str(audit.metadata_json))
        self.assertNotIn("plain-secret", str(audit.metadata_json))

    async def test_process_paid_external_orders_audits_fetch_delivery_http_error_with_external_order_id(self) -> None:
        order = _order(out_trade_no="ORD-FETCH")
        product = _product()
        import_service = SimpleNamespace(import_delivery=AsyncMock())
        service = ExternalAutoFulfillmentService(
            connection_service=SimpleNamespace(
                load_runtime_credentials_for_source=AsyncMock(return_value=SimpleNamespace(connection_id=44))
            ),
            operation_service=SimpleNamespace(
                create_registered_order=AsyncMock(return_value=_external_order()),
                fetch_registered_delivery=AsyncMock(
                    side_effect=ExternalHttpError(
                        "fetch body token=plain-token secret=plain-secret raw_payload={}",
                        status_code=503,
                        category=HTTP_ERROR_CATEGORY_UPSTREAM_ERROR,
                        retryable=True,
                    )
                ),
            ),
            import_service=import_service,
        )
        session = _FakeSession(rows=[(order, product)])

        with patch(
            "app.services.external_sources.auto_fulfillment.is_provider_auto_fulfillment_available",
            return_value=True,
        ):
            result = await service.process_paid_external_orders(session, settings=Settings(), limit=10)

        self.assertEqual(1, result.checked_count)
        self.assertEqual(0, result.imported_count)
        self.assertEqual(1, result.failed_count)
        import_service.import_delivery.assert_not_awaited()
        audit = next(item for item in session.added if isinstance(item, AuditLog))
        self.assertEqual("fetch_delivery", audit.metadata_json["failure_stage"])
        self.assertEqual(HTTP_ERROR_CATEGORY_UPSTREAM_ERROR, audit.metadata_json["failure_category"])
        self.assertTrue(audit.metadata_json["failure_retryable"])
        self.assertEqual(44, audit.metadata_json["connection_id"])
        self.assertEqual(503, audit.metadata_json["upstream_status_code"])
        self.assertEqual("EXT-1", audit.metadata_json["external_order_id"])
        self.assertNotIn("plain-token", str(audit.metadata_json))
        self.assertNotIn("plain-secret", str(audit.metadata_json))
        self.assertNotIn("raw_payload", str(audit.metadata_json))

    async def test_process_paid_external_orders_audits_provider_without_idempotent_auto_fulfillment_opt_in(
        self,
    ) -> None:
        order = _order(out_trade_no="ORD-NO-OPT-IN")
        product = _product()
        connection_service = SimpleNamespace(load_runtime_credentials_for_source=AsyncMock())
        operation_service = SimpleNamespace(
            create_registered_order=AsyncMock(),
            fetch_registered_delivery=AsyncMock(),
        )
        import_service = SimpleNamespace(import_delivery=AsyncMock())
        service = ExternalAutoFulfillmentService(
            connection_service=connection_service,
            operation_service=operation_service,
            import_service=import_service,
        )
        session = _FakeSession(rows=[(order, product)])

        with patch(
            "app.services.external_sources.auto_fulfillment.is_provider_auto_fulfillment_available",
            return_value=False,
        ):
            result = await service.process_paid_external_orders(session, settings=Settings(), limit=10)

        self.assertEqual(1, result.checked_count)
        self.assertEqual(0, result.imported_count)
        self.assertEqual(1, result.failed_count)
        self.assertEqual([], result.delivery_record_ids)
        connection_service.load_runtime_credentials_for_source.assert_not_awaited()
        operation_service.create_registered_order.assert_not_awaited()
        operation_service.fetch_registered_delivery.assert_not_awaited()
        import_service.import_delivery.assert_not_awaited()
        audit = next(item for item in session.added if isinstance(item, AuditLog))
        self.assertEqual("external_fulfillment.failed", audit.action)
        self.assertEqual("order", audit.target_type)
        self.assertEqual(str(order.id), audit.target_id)
        self.assertEqual(order.id, audit.metadata_json["order_id"])
        self.assertEqual("ORD-NO-OPT-IN", audit.metadata_json["out_trade_no"])
        self.assertEqual("acg", audit.metadata_json["provider_name"])
        self.assertEqual("main", audit.metadata_json["source"])
        self.assertEqual("provider_capability", audit.metadata_json["failure_stage"])
        self.assertEqual("auto_fulfillment_not_enabled", audit.metadata_json["failure_category"])
        self.assertFalse(audit.metadata_json["failure_retryable"])
        self.assertEqual(64, len(audit.metadata_json["failure_fingerprint"]))
        self.assertTrue(audit.metadata_json["auto"])
        self.assertNotIn("token", str(audit.metadata_json).lower())
        self.assertNotIn("secret", str(audit.metadata_json).lower())
        self.assertNotIn("runtime_auth", str(audit.metadata_json).lower())
        self.assertNotIn("payload", str(audit.metadata_json).lower())

    async def test_process_paid_external_orders_audits_import_delivery_failure_without_delivery_content(self) -> None:
        order = _order(out_trade_no="ORD-IMPORT")
        product = _product()
        import_service = SimpleNamespace(
            import_delivery=AsyncMock(side_effect=ValueError("card-secret token=plain-token raw_payload={}"))
        )
        service = ExternalAutoFulfillmentService(
            connection_service=SimpleNamespace(
                load_runtime_credentials_for_source=AsyncMock(return_value=SimpleNamespace(connection_id=44))
            ),
            operation_service=SimpleNamespace(
                create_registered_order=AsyncMock(return_value=_external_order()),
                fetch_registered_delivery=AsyncMock(return_value=_delivery()),
            ),
            import_service=import_service,
        )
        session = _FakeSession(rows=[(order, product)])

        with patch(
            "app.services.external_sources.auto_fulfillment.is_provider_auto_fulfillment_available",
            return_value=True,
        ):
            result = await service.process_paid_external_orders(session, settings=Settings(), limit=10)

        self.assertEqual(1, result.checked_count)
        self.assertEqual(0, result.imported_count)
        self.assertEqual(1, result.failed_count)
        import_service.import_delivery.assert_awaited_once()
        audit = next(item for item in session.added if isinstance(item, AuditLog))
        self.assertEqual("import_delivery", audit.metadata_json["failure_stage"])
        self.assertEqual("import_failed", audit.metadata_json["failure_category"])
        self.assertFalse(audit.metadata_json["failure_retryable"])
        self.assertEqual(44, audit.metadata_json["connection_id"])
        self.assertEqual("外部发货导入失败", audit.metadata_json["failure_reason"])
        self.assertEqual("EXT-1", audit.metadata_json["external_order_id"])
        self.assertNotIn("card-secret", str(audit.metadata_json))
        self.assertNotIn("plain-token", str(audit.metadata_json))
        self.assertNotIn("raw_payload", str(audit.metadata_json))

    async def test_delivery_pending_audit_keeps_external_order_id_as_trace_hint(self) -> None:
        order = _order(out_trade_no="ORD-PENDING")
        product = _product()
        service = ExternalAutoFulfillmentService(
            connection_service=SimpleNamespace(
                load_runtime_credentials_for_source=AsyncMock(return_value=SimpleNamespace(connection_id=44))
            ),
            operation_service=SimpleNamespace(
                create_registered_order=AsyncMock(return_value=_external_order()),
                fetch_registered_delivery=AsyncMock(return_value=None),
            ),
            import_service=SimpleNamespace(import_delivery=AsyncMock()),
        )
        session = _FakeSession(rows=[(order, product)])

        with patch(
            "app.services.external_sources.auto_fulfillment.is_provider_auto_fulfillment_available",
            return_value=True,
        ):
            result = await service.process_paid_external_orders(session, settings=Settings(), limit=10)

        self.assertEqual(1, result.failed_count)
        audit = next(item for item in session.added if isinstance(item, AuditLog))
        self.assertEqual("delivery_pending", audit.metadata_json["failure_stage"])
        self.assertEqual("delivery_pending", audit.metadata_json["failure_category"])
        self.assertTrue(audit.metadata_json["failure_retryable"])
        self.assertEqual(44, audit.metadata_json["connection_id"])
        self.assertEqual("EXT-1", audit.metadata_json["external_order_id"])

    async def test_failure_audit_records_external_product_id_and_connection_id_without_credentials(self) -> None:
        order = _order(out_trade_no="ORD-AUDIT-TRACE")
        product = _product()
        error = ExternalAutoFulfillmentError(
            "外部履约失败",
            stage="fetch_delivery",
            category=HTTP_ERROR_CATEGORY_UPSTREAM_ERROR,
            retryable=True,
            status_code=503,
            external_order_id="EXT-1",
            connection_id=44,
        )

        metadata = _failure_audit_metadata(order, product, error)

        self.assertEqual("sku-1", metadata["external_product_id"])
        self.assertEqual(44, metadata["connection_id"])
        self.assertEqual("EXT-1", metadata["external_order_id"])
        self.assertEqual(503, metadata["upstream_status_code"])
        self.assertEqual(64, len(metadata["failure_fingerprint"]))
        self.assertNotIn("runtime_auth", str(metadata).lower())
        self.assertNotIn("token", str(metadata).lower())
        self.assertNotIn("secret", str(metadata).lower())

    async def test_process_paid_external_orders_redacts_unclassified_value_error_reason(self) -> None:
        order = _order(out_trade_no="ORD-RAW-ERROR")
        product = _product()
        service = _SensitiveFailBatchService()
        session = _FakeSession(rows=[(order, product)])

        result = await service.process_paid_external_orders(session, settings=Settings(), limit=10)

        self.assertEqual(1, result.failed_count)
        audit = next(item for item in session.added if isinstance(item, AuditLog))
        self.assertEqual("外部履约失败", audit.metadata_json["failure_reason"])
        self.assertEqual("unknown", audit.metadata_json["failure_stage"])
        self.assertEqual("unknown", audit.metadata_json["failure_category"])
        self.assertNotIn("plain-token", str(audit.metadata_json))
        self.assertNotIn("card-secret", str(audit.metadata_json))
        self.assertNotIn("raw_payload", str(audit.metadata_json))
        attempts = _attempts(session)
        self.assertEqual(1, len(attempts))
        self.assertEqual("auto", attempts[0].attempt_source)
        self.assertEqual("failed", attempts[0].status)
        self.assertEqual("外部履约失败", attempts[0].failure_reason)
        self.assertNotIn("plain-token", str(attempts[0].__dict__))
        self.assertNotIn("card-secret", str(attempts[0].__dict__))
        self.assertNotIn("raw_payload", str(attempts[0].__dict__))

    async def test_failure_fingerprint_changes_when_product_or_external_mapping_changes(self) -> None:
        order = _order(out_trade_no="ORD-FINGERPRINT")
        product = _product()
        other_product = SimpleNamespace(**{**product.__dict__, "id": 202, "source_key": "backup"})
        other_external_id = SimpleNamespace(**{**product.__dict__, "external_id": "sku-2"})
        other_connection = ExternalAutoFulfillmentError(
            "外部履约失败",
            stage="create_order",
            connection_id=45,
        )

        first = _failure_audit_metadata(order, product, ValueError("外部履约失败"))
        second = _failure_audit_metadata(order, other_product, ValueError("外部履约失败"))
        third = _failure_audit_metadata(order, other_external_id, ValueError("外部履约失败"))
        fourth = _failure_audit_metadata(order, product, other_connection)

        self.assertNotEqual(first["failure_fingerprint"], second["failure_fingerprint"])
        self.assertNotEqual(first["failure_fingerprint"], third["failure_fingerprint"])
        self.assertNotEqual(first["failure_fingerprint"], fourth["failure_fingerprint"])

    async def test_failed_audit_target_id_uses_order_id_when_out_trade_no_is_long(self) -> None:
        long_trade_no = "ORD-" + "X" * 92
        order = _order(out_trade_no=long_trade_no)
        product = _product()
        service = _AlwaysFailBatchService()
        session = _FakeSession(rows=[(order, product)])

        result = await service.process_paid_external_orders(session, settings=Settings(), limit=10)

        self.assertEqual(1, result.failed_count)
        audit = next(item for item in session.added if isinstance(item, AuditLog))
        self.assertEqual(str(order.id), audit.target_id)
        self.assertEqual(long_trade_no, audit.metadata_json["out_trade_no"])

    async def test_process_paid_external_orders_records_failed_attempt_even_when_failure_audit_is_deduped(
        self,
    ) -> None:
        order = _order(out_trade_no="ORD-RETRY")
        product = _product()
        metadata = _failure_audit_metadata(order, product, ValueError("外部履约失败"))
        latest_audit = AuditLog(
            tenant_id=order.tenant_id,
            action="external_fulfillment.failed",
            target_type="order",
            target_id=str(order.id),
            metadata_json=metadata,
        )
        service = _AlwaysFailBatchService()
        session = _FakeSession(rows=[(order, product)], scalar_values=[latest_audit])

        result = await service.process_paid_external_orders(session, settings=Settings(), limit=10)

        self.assertEqual(1, result.checked_count)
        self.assertEqual(0, result.imported_count)
        self.assertEqual(1, result.failed_count)
        attempts = _attempts(session)
        self.assertEqual(1, len(attempts))
        self.assertEqual("auto", attempts[0].attempt_source)
        self.assertEqual("failed", attempts[0].status)
        self.assertEqual("unknown", attempts[0].failure_stage)
        self.assertEqual([], [item for item in session.added if isinstance(item, AuditLog)])
        self.assertEqual(1, session.flush_count)

    async def test_different_failure_fingerprint_still_adds_audit(self) -> None:
        order = _order(out_trade_no="ORD-RETRY")
        product = _product()
        latest_audit = AuditLog(
            tenant_id=order.tenant_id,
            action="external_fulfillment.failed",
            target_type="order",
            target_id=str(order.id),
            metadata_json={"failure_fingerprint": "different"},
        )
        service = _AlwaysFailBatchService()
        session = _FakeSession(rows=[(order, product)], scalar_values=[latest_audit])

        result = await service.process_paid_external_orders(session, settings=Settings(), limit=10)

        self.assertEqual(1, result.checked_count)
        self.assertEqual(1, result.failed_count)
        audits = [item for item in session.added if isinstance(item, AuditLog)]
        self.assertEqual(1, len(audits))
        self.assertNotEqual("different", audits[0].metadata_json["failure_fingerprint"])
        self.assertEqual(1, session.flush_count)

    async def test_process_paid_external_orders_skips_duplicate_order_rows_in_same_batch(self) -> None:
        order = _order(out_trade_no="ORD-DUP")
        product = _product()
        service = _DuplicateBatchService()
        session = _FakeSession(rows=[(order, product), (order, product)])

        result = await service.process_paid_external_orders(session, settings=Settings(), limit=10)

        self.assertEqual(1, result.checked_count)
        self.assertEqual(1, result.imported_count)
        self.assertEqual(0, result.failed_count)
        self.assertEqual([777], result.delivery_record_ids)
        self.assertEqual(1, service.fulfill_count)

    async def test_process_paid_external_orders_rejects_invalid_limit(self) -> None:
        with self.assertRaisesRegex(ValueError, "limit"):
            await ExternalAutoFulfillmentService().process_paid_external_orders(
                _FakeSession(rows=[]),
                settings=Settings(),
                limit=0,
            )


class ExternalFulfillmentWorkerTest(unittest.TestCase):
    def test_worker_commits_and_returns_processed_count(self) -> None:
        session = _FakeSession()
        settings = Settings()

        with patch("app.workers.external_fulfillment.ExternalAutoFulfillmentService") as service:
            service.return_value.process_paid_external_orders = AsyncMock(
                return_value=ExternalAutoFulfillmentBatchResult(
                    checked_count=3,
                    imported_count=2,
                    failed_count=1,
                    delivery_record_ids=[11, 12],
                )
            )
            imported_count = _run(
                process_paid_external_orders_once(
                    settings,
                    _session_factory(session),
                    limit=77,
                )
            )

        self.assertEqual(3, imported_count)
        self.assertEqual(1, session.commit_count)
        service.return_value.process_paid_external_orders.assert_awaited_once_with(
            session,
            settings=settings,
            limit=77,
        )

    def test_worker_counts_failed_fulfillment_as_processed_after_commit(self) -> None:
        session = _FakeSession()
        settings = Settings()

        with patch("app.workers.external_fulfillment.ExternalAutoFulfillmentService") as service:
            service.return_value.process_paid_external_orders = AsyncMock(
                return_value=ExternalAutoFulfillmentBatchResult(
                    checked_count=2,
                    imported_count=0,
                    failed_count=2,
                    delivery_record_ids=[],
                )
            )
            processed_count = _run(
                process_paid_external_orders_once(
                    settings,
                    _session_factory(session),
                    limit=77,
                )
            )

        self.assertEqual(2, processed_count)
        self.assertEqual(1, session.commit_count)

    def test_worker_does_not_commit_when_service_raises(self) -> None:
        session = _FakeSession()
        settings = Settings()

        with patch("app.workers.external_fulfillment.ExternalAutoFulfillmentService") as service:
            service.return_value.process_paid_external_orders = AsyncMock(side_effect=RuntimeError("boom"))
            with self.assertRaisesRegex(RuntimeError, "boom"):
                _run(
                    process_paid_external_orders_once(
                        settings,
                        _session_factory(session),
                        limit=77,
                    )
                )

        self.assertEqual(0, session.commit_count)


class _BatchService(ExternalAutoFulfillmentService):
    async def fulfill_paid_order(
        self,
        session: object,
        *,
        order: object,
        product: object,
        settings: Settings,
    ) -> ExternalAutoFulfillmentResult:
        if order.out_trade_no == "ORD-B":
            raise ValueError("外部发货尚未就绪")
        return ExternalAutoFulfillmentResult(
            out_trade_no=order.out_trade_no,
            provider_name="acg",
            source_key="main",
            external_order_id="EXT-A",
            delivery_record_id=501,
            item_count=1,
            imported=True,
        )


class _AlwaysFailBatchService(ExternalAutoFulfillmentService):
    async def fulfill_paid_order(
        self,
        session: object,
        *,
        order: object,
        product: object,
        settings: Settings,
    ) -> ExternalAutoFulfillmentResult:
        raise ValueError("外部履约失败")


class _SensitiveFailBatchService(ExternalAutoFulfillmentService):
    async def fulfill_paid_order(
        self,
        session: object,
        *,
        order: object,
        product: object,
        settings: Settings,
    ) -> ExternalAutoFulfillmentResult:
        raise ValueError("token=plain-token card=card-secret raw_payload={}")


class _DuplicateBatchService(ExternalAutoFulfillmentService):
    def __init__(self) -> None:
        super().__init__()
        self.fulfill_count = 0

    async def fulfill_paid_order(
        self,
        session: object,
        *,
        order: object,
        product: object,
        settings: Settings,
    ) -> ExternalAutoFulfillmentResult:
        self.fulfill_count += 1
        return ExternalAutoFulfillmentResult(
            out_trade_no=order.out_trade_no,
            provider_name="acg",
            source_key="main",
            external_order_id="EXT-DUP",
            delivery_record_id=777,
            item_count=1,
            imported=True,
        )


class _ReplayIdempotentProvider:
    provider = "replay-idempotent"
    auto_fulfillment_idempotent = True

    def __init__(self) -> None:
        self.orders_by_trade_no: dict[str, ExternalOrder] = {}
        self.create_count = 0
        self.fetch_count = 0

    async def create_order_with_context(self, context: object, request: ExternalOrderRequest) -> ExternalOrder:
        self.create_count += 1
        out_trade_no = request.out_trade_no or ""
        if out_trade_no not in self.orders_by_trade_no:
            self.orders_by_trade_no[out_trade_no] = ExternalOrder(
                provider=self.provider,
                external_order_id=f"EXT-{out_trade_no.removeprefix('ORD-')}",
                external_product_id=request.external_product_id,
                status="paid",
                quantity=request.quantity,
                amount=Decimal("9.90"),
                currency="USDT",
                delivery_ready=True,
            )
        return self.orders_by_trade_no[out_trade_no]

    async def query_order_with_context(self, context: object, external_order_id: str) -> ExternalOrder | None:
        for order in self.orders_by_trade_no.values():
            if order.external_order_id == external_order_id:
                return order
        return None

    async def fetch_delivery_with_context(self, context: object, external_order_id: str) -> ExternalDelivery:
        self.fetch_count += 1
        return ExternalDelivery(
            provider=self.provider,
            external_order_id=external_order_id,
            delivery_type="card_pool",
            items=("card-a",),
        )


def _run(coro: object) -> object:
    import asyncio

    return asyncio.run(coro)


def _session_factory(session: _FakeSession) -> object:
    class _SessionContext:
        async def __aenter__(self) -> _FakeSession:
            return session

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

    class _Factory:
        def __call__(self) -> _SessionContext:
            return _SessionContext()

    return _Factory()


def _order(*, order_id: int = 12, out_trade_no: str = "ORD123") -> SimpleNamespace:
    return SimpleNamespace(
        id=order_id,
        tenant_id=7,
        buyer_telegram_user_id=42,
        source_type="self",
        self_product_id=101,
        locked_inventory_item_id=None,
        status="paid",
        out_trade_no=out_trade_no,
        paid_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        amount=Decimal("9.90"),
        currency="USDT",
    )


def _product(*, external_source: str = "acg") -> SimpleNamespace:
    return SimpleNamespace(
        id=101,
        tenant_id=7,
        external_source=external_source,
        source_key="main",
        external_id="sku-1",
        delivery_type="card_pool",
    )


def _external_order() -> ExternalOrder:
    return ExternalOrder(
        provider="acg",
        external_order_id="EXT-1",
        external_product_id="sku-1",
        status="paid",
        quantity=1,
        amount=Decimal("9.90"),
        currency="USDT",
        delivery_ready=True,
    )


def _delivery() -> ExternalDelivery:
    return ExternalDelivery(
        provider="acg",
        external_order_id="EXT-1",
        delivery_type="card_pool",
        items=("card-a", "card-b"),
    )


def _attempts(session: _FakeSession) -> list[ExternalFulfillmentAttempt]:
    return [item for item in session.added if isinstance(item, ExternalFulfillmentAttempt)]


if __name__ == "__main__":
    unittest.main()
