from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

try:
    from app.db.models.tenants import AuditLog
    from app.services.supply import SupplyService
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过供货服务测试：{exc.name}") from exc


class _NoQuerySession:
    def __init__(self) -> None:
        self.execute_count = 0
        self.get_count = 0
        self.add_count = 0
        self.flush_count = 0
        self.scalar_count = 0

    async def execute(self, query: object) -> object:
        self.execute_count += 1
        raise AssertionError("非法参数应在查询前被拒绝")

    async def get(self, model: type[object], item_id: int) -> object | None:
        self.get_count += 1
        raise AssertionError("非法参数应在查询前被拒绝")

    def add(self, item: object) -> None:
        self.add_count += 1
        raise AssertionError("非法参数应在写入前被拒绝")

    async def flush(self) -> None:
        self.flush_count += 1
        raise AssertionError("非法参数应在 flush 前被拒绝")

    async def scalar(self, query: object) -> object | None:
        self.scalar_count += 1
        raise AssertionError("非法参数应在查询前被拒绝")


class _WriteSession:
    def __init__(self) -> None:
        self.added_objects: list[object] = []
        self.flush_count = 0

    def add(self, item: object) -> None:
        self.added_objects.append(item)

    async def flush(self) -> None:
        self.flush_count += 1


class SupplyServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.service = SupplyService()

    async def test_create_supplier_offer_rejects_invalid_price_before_query(self) -> None:
        session = _NoQuerySession()

        with self.assertRaises(ValueError):
            await self.service.create_supplier_offer(
                session=session,
                supplier_tenant_id=7,
                product_id=21,
                suggested_price=Decimal("0"),
                min_sale_price=None,
            )

        self.assertEqual(0, session.execute_count)
        self.assertEqual(0, session.get_count)
        self.assertEqual(0, session.add_count)
        self.assertEqual(0, session.flush_count)
        self.assertEqual(0, session.scalar_count)

    async def test_create_reseller_product_rejects_invalid_sale_price_before_query(self) -> None:
        invalid_prices = (
            Decimal("0"),
            Decimal("NaN"),
            Decimal("Infinity"),
            Decimal("12.123456789"),
        )

        for sale_price in invalid_prices:
            with self.subTest(sale_price=sale_price):
                session = _NoQuerySession()

                with self.assertRaises(ValueError):
                    await self.service.create_reseller_product(
                        session=session,
                        reseller_tenant_id=7,
                        supplier_offer_id=91,
                        sale_price=sale_price,
                        display_name="代理卡密",
                    )

                self.assertEqual(0, session.execute_count)
                self.assertEqual(0, session.get_count)
                self.assertEqual(0, session.add_count)
                self.assertEqual(0, session.flush_count)
                self.assertEqual(0, session.scalar_count)

    async def test_update_reseller_product_metadata_rejects_invalid_payload_before_query(self) -> None:
        invalid_cases = (
            {
                "reseller_product_id": 0,
                "category": "会员",
                "category_provided": True,
                "sort_order": 1,
            },
            {
                "reseller_product_id": 201,
                "category": None,
                "category_provided": False,
                "sort_order": None,
            },
            {
                "reseller_product_id": 201,
                "category": "bad\x00category",
                "category_provided": True,
                "sort_order": None,
            },
            {
                "reseller_product_id": 201,
                "category": "x" * 129,
                "category_provided": True,
                "sort_order": None,
            },
            {
                "reseller_product_id": 201,
                "category": None,
                "category_provided": False,
                "sort_order": 100001,
            },
        )

        for case in invalid_cases:
            with self.subTest(case=case):
                session = _NoQuerySession()
                with self.assertRaises(ValueError):
                    await self.service.update_reseller_product_metadata(
                        session=session,
                        reseller_tenant_id=7,
                        reseller_product_id=case["reseller_product_id"],
                        category=case["category"],
                        category_provided=case["category_provided"],
                        sort_order=case["sort_order"],
                    )

                self.assertEqual(0, session.execute_count)
                self.assertEqual(0, session.get_count)
                self.assertEqual(0, session.add_count)
                self.assertEqual(0, session.flush_count)
                self.assertEqual(0, session.scalar_count)

    async def test_update_reseller_product_sales_rejects_invalid_payload_before_query(self) -> None:
        invalid_cases = (
            {
                "reseller_product_id": 0,
                "sale_price": Decimal("12.00"),
                "display_name": "代理卡密",
                "display_name_provided": True,
            },
            {
                "reseller_product_id": 201,
                "sale_price": None,
                "display_name": None,
                "display_name_provided": False,
            },
            {
                "reseller_product_id": 201,
                "sale_price": Decimal("0"),
                "display_name": None,
                "display_name_provided": False,
            },
            {
                "reseller_product_id": 201,
                "sale_price": Decimal("NaN"),
                "display_name": None,
                "display_name_provided": False,
            },
            {
                "reseller_product_id": 201,
                "sale_price": Decimal("Infinity"),
                "display_name": None,
                "display_name_provided": False,
            },
            {
                "reseller_product_id": 201,
                "sale_price": Decimal("12.123456789"),
                "display_name": None,
                "display_name_provided": False,
            },
            {
                "reseller_product_id": 201,
                "sale_price": None,
                "display_name": "x" * 256,
                "display_name_provided": True,
            },
        )

        for case in invalid_cases:
            with self.subTest(case=case):
                session = _NoQuerySession()
                with self.assertRaises(ValueError):
                    await self.service.update_reseller_product_sales(
                        session=session,
                        reseller_tenant_id=7,
                        reseller_product_id=case["reseller_product_id"],
                        sale_price=case["sale_price"],
                        display_name=case["display_name"],
                        display_name_provided=case["display_name_provided"],
                    )

                self.assertEqual(0, session.execute_count)
                self.assertEqual(0, session.get_count)
                self.assertEqual(0, session.add_count)
                self.assertEqual(0, session.flush_count)
                self.assertEqual(0, session.scalar_count)

    async def test_list_market_offers_rejects_invalid_filters_before_query(self) -> None:
        invalid_filter_cases = (
            {"query": "bad\x00name"},
            {"query": "x" * 65},
            {"category": "bad\x00category"},
            {"category": "x" * 129},
            {"delivery_type": "telegram_invite"},
            {"access": "unknown"},
            {"stock": "low"},
            {"min_price": Decimal("-1")},
            {"max_price": Decimal("NaN")},
            {"min_price": Decimal("20"), "max_price": Decimal("10")},
        )

        for filters in invalid_filter_cases:
            with self.subTest(filters=filters):
                session = _NoQuerySession()
                with self.assertRaises(ValueError):
                    await self.service.list_market_offers(
                        session=session,
                        reseller_tenant_id=7,
                        **filters,
                    )
                self.assertEqual(0, session.execute_count)
                self.assertEqual(0, session.get_count)

    async def test_create_supplier_offer_rejects_unsupported_delivery_type_before_offer_query(self) -> None:
        session = _NoQuerySession()
        product = SimpleNamespace(
            id=21,
            product_type="self",
            status="on",
            delivery_type="telegram_invite",
            delivery_file_id=None,
            telegram_chat_id=123,
        )
        variant = SimpleNamespace(id=22, status="on", price=Decimal("9.00"), currency="USDT")

        with patch.object(self.service, "_get_supplier_product", AsyncMock(return_value=(product, variant))):
            with self.assertRaises(ValueError):
                await self.service.create_supplier_offer(
                    session=session,
                    supplier_tenant_id=7,
                    product_id=21,
                    suggested_price=Decimal("12.00"),
                    min_sale_price=None,
                )

        self.assertEqual(0, session.execute_count)
        self.assertEqual(0, session.add_count)
        self.assertEqual(0, session.flush_count)

    async def test_approve_reseller_application_requires_existing_pending_rule_before_approval(self) -> None:
        session = _NoQuerySession()
        with patch.object(
            self.service,
            "_require_pending_reseller_application",
            AsyncMock(side_effect=ValueError("代理申请不存在或不可审批")),
        ) as require_pending:
            with patch.object(self.service, "approve_reseller", AsyncMock()) as approve_reseller:
                with self.assertRaises(ValueError):
                    await self.service.approve_reseller_application(
                        session=session,
                        supplier_tenant_id=7,
                        supplier_offer_id=91,
                        reseller_tenant_id=88,
                        actor_user_id=None,
                    )

        require_pending.assert_awaited_once_with(
            session=session,
            supplier_tenant_id=7,
            supplier_offer_id=91,
            reseller_tenant_id=88,
        )
        approve_reseller.assert_not_awaited()

    async def test_reject_reseller_application_requires_existing_pending_rule_before_rejection(self) -> None:
        session = _NoQuerySession()
        with patch.object(
            self.service,
            "_require_pending_reseller_application",
            AsyncMock(side_effect=ValueError("代理申请不存在或不可审批")),
        ) as require_pending:
            with patch.object(self.service, "reject_reseller", AsyncMock()) as reject_reseller:
                with self.assertRaises(ValueError):
                    await self.service.reject_reseller_application(
                        session=session,
                        supplier_tenant_id=7,
                        supplier_offer_id=91,
                        reseller_tenant_id=88,
                        actor_user_id=None,
                        reason="资料不完整",
                    )

        require_pending.assert_awaited_once_with(
            session=session,
            supplier_tenant_id=7,
            supplier_offer_id=91,
            reseller_tenant_id=88,
        )
        reject_reseller.assert_not_awaited()

    async def test_set_existing_reseller_rule_rejects_invalid_price_before_query(self) -> None:
        invalid_cases = (
            {"pricing_value": Decimal("0"), "min_sale_price": None},
            {"pricing_value": Decimal("1.123456789"), "min_sale_price": None},
            {"pricing_value": Decimal("1.00"), "min_sale_price": Decimal("-0.01")},
            {"pricing_value": Decimal("1.00"), "min_sale_price": Decimal("2.123456789")},
        )

        for case in invalid_cases:
            with self.subTest(case=case):
                session = _NoQuerySession()

                with self.assertRaises(ValueError):
                    await self.service.set_existing_reseller_rule(
                        session=session,
                        supplier_tenant_id=7,
                        supplier_offer_id=91,
                        reseller_tenant_id=88,
                        actor_user_id=None,
                        pricing_value=case["pricing_value"],
                        min_sale_price=case["min_sale_price"],
                    )

                self.assertEqual(0, session.execute_count)
                self.assertEqual(0, session.get_count)
                self.assertEqual(0, session.add_count)
                self.assertEqual(0, session.flush_count)
                self.assertEqual(0, session.scalar_count)

    async def test_set_existing_reseller_rule_requires_existing_pending_or_active_rule_before_write(self) -> None:
        offer = SimpleNamespace(id=91, supplier_tenant_id=7)
        product = SimpleNamespace(id=21)
        variant = SimpleNamespace(id=22)

        for rule in (None, SimpleNamespace(status="rejected"), SimpleNamespace(status="disabled")):
            with self.subTest(rule_status=getattr(rule, "status", None)):
                session = _NoQuerySession()
                with patch.object(
                    self.service,
                    "_get_supplier_offer_details",
                    AsyncMock(return_value=(offer, product, variant)),
                ) as get_offer:
                    with patch.object(self.service, "_get_reseller_rule", AsyncMock(return_value=rule)) as get_rule:
                        with patch.object(self.service, "approve_reseller", AsyncMock()) as approve_reseller:
                            with self.assertRaises(ValueError):
                                await self.service.set_existing_reseller_rule(
                                    session=session,
                                    supplier_tenant_id=7,
                                    supplier_offer_id=91,
                                    reseller_tenant_id=88,
                                    actor_user_id=None,
                                    pricing_value=Decimal("8.50"),
                                    min_sale_price=Decimal("10.00"),
                                )

                get_offer.assert_awaited_once_with(session, 7, 91)
                get_rule.assert_awaited_once_with(session, 91, 88)
                approve_reseller.assert_not_awaited()

    async def test_set_existing_reseller_rule_delegates_with_actor_none_for_existing_rule(self) -> None:
        offer = SimpleNamespace(id=91, supplier_tenant_id=7)
        product = SimpleNamespace(id=21)
        variant = SimpleNamespace(id=22)
        expected_summary = SimpleNamespace(status="active")

        for status in ("pending", "active"):
            with self.subTest(status=status):
                session = _NoQuerySession()
                rule = SimpleNamespace(status=status)
                with patch.object(
                    self.service,
                    "_get_supplier_offer_details",
                    AsyncMock(return_value=(offer, product, variant)),
                ) as get_offer:
                    with patch.object(self.service, "_get_reseller_rule", AsyncMock(return_value=rule)) as get_rule:
                        with patch.object(
                            self.service,
                            "approve_reseller",
                            AsyncMock(return_value=expected_summary),
                        ) as approve_reseller:
                            result = await self.service.set_existing_reseller_rule(
                                session=session,
                                supplier_tenant_id=7,
                                supplier_offer_id=91,
                                reseller_tenant_id=88,
                                actor_user_id=None,
                                pricing_value=Decimal("8.50"),
                                min_sale_price=Decimal("10.00"),
                            )

                self.assertIs(expected_summary, result)
                get_offer.assert_awaited_once_with(session, 7, 91)
                get_rule.assert_awaited_once_with(session, 91, 88)
                approve_reseller.assert_awaited_once_with(
                    session=session,
                    supplier_tenant_id=7,
                    supplier_offer_id=91,
                    reseller_tenant_id=88,
                    actor_user_id=None,
                    pricing_value=Decimal("8.50"),
                    min_sale_price=Decimal("10.00"),
                )

    async def test_list_platform_supplier_offers_rejects_invalid_status_before_query(self) -> None:
        session = _NoQuerySession()

        with self.assertRaises(ValueError):
            await self.service.list_platform_supplier_offers(session=session, status="taken_down")

        self.assertEqual(0, session.execute_count)
        self.assertEqual(0, session.get_count)
        self.assertEqual(0, session.add_count)
        self.assertEqual(0, session.flush_count)
        self.assertEqual(0, session.scalar_count)

    async def test_set_platform_supplier_offer_status_rejects_invalid_status_before_query(self) -> None:
        session = _NoQuerySession()

        with self.assertRaises(ValueError):
            await self.service.set_platform_supplier_offer_status(
                session=session,
                supplier_offer_id=91,
                status="taken_down",
            )

        self.assertEqual(0, session.execute_count)
        self.assertEqual(0, session.get_count)
        self.assertEqual(0, session.add_count)
        self.assertEqual(0, session.flush_count)
        self.assertEqual(0, session.scalar_count)

    async def test_set_platform_supplier_offer_status_changes_only_offer_status_and_audits(self) -> None:
        session = _WriteSession()
        now = datetime(2026, 6, 9, 9, 0, tzinfo=timezone.utc)
        offer = SimpleNamespace(
            id=91,
            supplier_tenant_id=7,
            status="on",
            suggested_price=Decimal("12.00"),
            min_sale_price=Decimal("10.00"),
            default_pricing_value=Decimal("8.50"),
            requires_approval=True,
            created_at=now,
            updated_at=now,
        )
        tenant = SimpleNamespace(id=7, store_name="供货商")
        product = SimpleNamespace(id=21, name="卡密", delivery_type="card_pool")
        variant = SimpleNamespace(id=22, currency="USDT")

        with patch.object(
            self.service,
            "_get_platform_supplier_offer_details",
            AsyncMock(return_value=(offer, tenant, product, variant, 5)),
        ) as get_offer:
            result = await self.service.set_platform_supplier_offer_status(
                session=session,
                supplier_offer_id=91,
                status="disabled",
                reason="违规 token=plain-secret",
            )

        self.assertEqual("disabled", offer.status)
        self.assertEqual("disabled", result.status)
        self.assertEqual(91, result.supplier_offer_id)
        self.assertEqual(1, session.flush_count)
        self.assertEqual(1, len(session.added_objects))
        audit_log = session.added_objects[0]
        self.assertIsInstance(audit_log, AuditLog)
        self.assertIsNone(audit_log.tenant_id)
        self.assertIsNone(audit_log.actor_user_id)
        self.assertEqual("platform_supply.supplier_offer_status_updated", audit_log.action)
        self.assertEqual("supplier_offer", audit_log.target_type)
        self.assertEqual("91", audit_log.target_id)
        self.assertEqual(
            {
                "supplier_tenant_id": 7,
                "previous_status": "on",
                "new_status": "disabled",
                "reason": "内容已隐藏",
            },
            audit_log.metadata_json,
        )
        get_offer.assert_awaited_once_with(session, 91)

    async def test_set_platform_supplier_offer_status_is_idempotent_when_already_disabled(self) -> None:
        session = _WriteSession()
        now = datetime(2026, 6, 9, 9, 0, tzinfo=timezone.utc)
        offer = SimpleNamespace(
            id=91,
            supplier_tenant_id=7,
            status="disabled",
            suggested_price=Decimal("12.00"),
            min_sale_price=Decimal("10.00"),
            default_pricing_value=Decimal("8.50"),
            requires_approval=True,
            created_at=now,
            updated_at=now,
        )
        tenant = SimpleNamespace(id=7, store_name="供货商")
        product = SimpleNamespace(id=21, name="卡密", delivery_type="card_pool")
        variant = SimpleNamespace(id=22, currency="USDT")

        with patch.object(
            self.service,
            "_get_platform_supplier_offer_details",
            AsyncMock(return_value=(offer, tenant, product, variant, 5)),
        ) as get_offer:
            result = await self.service.set_platform_supplier_offer_status(
                session=session,
                supplier_offer_id=91,
                status="disabled",
                reason="重复下架",
            )

        self.assertEqual("disabled", result.status)
        self.assertEqual([], session.added_objects)
        self.assertEqual(1, session.flush_count)
        get_offer.assert_awaited_once_with(session, 91)


if __name__ == "__main__":
    unittest.main()
