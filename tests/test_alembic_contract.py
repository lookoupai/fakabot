from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AlembicContractTest(unittest.TestCase):
    def test_alembic_env_imports_aggregate_models_package(self) -> None:
        env_source = (PROJECT_ROOT / "alembic" / "env.py").read_text(encoding="utf-8")

        self.assertIn("from app.db import models", env_source)

    def test_model_package_registers_all_current_tables(self) -> None:
        from app.db.base import Base
        import app.db.models  # noqa: F401

        expected_tables = {
            "after_sale_cases",
            "audit_logs",
            "delivery_records",
            "disputes",
            "export_jobs",
            "external_fulfillment_attempts",
            "external_source_connections",
            "file_archive_entries",
            "file_processing_jobs",
            "inventory_items",
            "ledger_accounts",
            "ledger_entries",
            "orders",
            "payment_callbacks",
            "payment_provider_configs",
            "payments",
            "platform_users",
            "product_variants",
            "products",
            "refunds",
            "reseller_products",
            "settlement_policies",
            "subscription_invoices",
            "subscription_plans",
            "supplier_offers",
            "supplier_reseller_rules",
            "tenant_api_keys",
            "tenant_bots",
            "tenant_members",
            "tenant_role_permissions",
            "tenant_settings",
            "tenant_subscriptions",
            "tenants",
            "trc20_direct_transfers",
            "uploaded_files",
            "withdrawal_requests",
        }

        self.assertTrue(expected_tables.issubset(set(Base.metadata.tables)))

    def test_model_metadata_registers_trc20_direct_transfers_table_with_safe_columns(self) -> None:
        from app.db.base import Base
        import app.db.models  # noqa: F401

        self.assertIn("trc20_direct_transfers", Base.metadata.tables)
        table = Base.metadata.tables["trc20_direct_transfers"]

        column_names = set(table.columns.keys())
        self.assertTrue(
            {
                "tenant_id",
                "order_id",
                "payment_id",
                "tx_hash",
                "block_number",
                "timestamp_ms",
                "from_address",
                "to_address",
                "contract_address",
                "raw_amount",
                "amount",
                "confirmations",
                "match_status",
                "matched_at",
                "failure_reason",
            }.issubset(column_names)
        )
        for forbidden in ("raw_payload", "payload_json", "metadata_json"):
            self.assertNotIn(forbidden, table.columns)

    def test_alembic_revisions_are_single_linear_chain(self) -> None:
        revisions = {}
        down_revisions = {}
        for path in sorted((PROJECT_ROOT / "alembic" / "versions").glob("*.py")):
            module = _load_revision_module(path)
            revisions[module.revision] = path.name
            down_revisions[module.revision] = module.down_revision

        roots = [revision for revision, down_revision in down_revisions.items() if down_revision is None]
        self.assertEqual(["20260606_0001"], roots)
        for revision, down_revision in down_revisions.items():
            if down_revision is None:
                continue
            self.assertIsInstance(down_revision, str, revision)
            self.assertIn(down_revision, revisions, revision)
        referenced = {down_revision for down_revision in down_revisions.values() if down_revision is not None}
        heads = sorted(set(revisions) - referenced)
        self.assertEqual(["20260610_0024"], heads)
        self.assertEqual(24, len(revisions))

    def test_external_fulfillment_attempt_migration_contains_required_columns_constraints_and_indexes(self) -> None:
        source = (
            PROJECT_ROOT
            / "alembic"
            / "versions"
            / "20260606_0021_create_external_fulfillment_attempts.py"
        ).read_text(encoding="utf-8")

        for marker in [
            'revision: str = "20260606_0021"',
            'down_revision: Optional[str] = "20260606_0020"',
            '"external_fulfillment_attempts"',
            '"tenant_id"',
            '"order_id"',
            '"product_id"',
            '"connection_id"',
            '"delivery_record_id"',
            '"out_trade_no"',
            '"provider_name"',
            '"source_key"',
            '"external_product_id"',
            '"external_order_id"',
            '"attempt_source"',
            '"status"',
            '"imported"',
            '"item_count"',
            '"failure_reason"',
            '"failure_stage"',
            '"failure_category"',
            '"failure_retryable"',
            '"upstream_status_code"',
            '"failure_fingerprint"',
            '"started_at"',
            '"finished_at"',
            'sa.ForeignKeyConstraint(["delivery_record_id"], ["delivery_records.id"])',
            '"ck_external_fulfillment_attempts_attempt_source"',
            '"ck_external_fulfillment_attempts_status"',
            '"ck_external_fulfillment_attempts_item_count_nonnegative"',
            '"ck_external_fulfillment_attempts_upstream_status_code"',
            '"ix_external_fulfillment_attempts_tenant_status_created"',
            '"ix_external_fulfillment_attempts_tenant_order_created"',
            '"ix_external_fulfillment_attempts_provider_status"',
        ]:
            self.assertIn(marker, source)

    def test_external_fulfillment_attempt_lifecycle_migration_updates_status_constraint(self) -> None:
        source = (
            PROJECT_ROOT
            / "alembic"
            / "versions"
            / "20260609_0022_external_fulfillment_attempt_lifecycle_statuses.py"
        ).read_text(encoding="utf-8")

        for marker in [
            'revision: str = "20260609_0022"',
            'down_revision: Optional[str] = "20260606_0021"',
            '"external_fulfillment_attempts"',
            '"ck_external_fulfillment_attempts_status"',
            "'started'",
            "'running'",
            "'succeeded'",
            "'already_delivered'",
            "'failed'",
            "'imported'",
        ]:
            self.assertIn(marker, source)

    def test_trc20_direct_transfer_migration_contains_required_columns_constraints_and_indexes(self) -> None:
        source = _read_single_revision_source("20260609_0023*.py")

        for marker in [
            'revision: str = "20260609_0023"',
            'down_revision: Optional[str] = "20260609_0022"',
            '"trc20_direct_transfers"',
            '"tenant_id"',
            '"order_id"',
            '"payment_id"',
            '"tx_hash"',
            '"block_number"',
            '"timestamp_ms"',
            '"from_address"',
            '"to_address"',
            '"contract_address"',
            '"raw_amount"',
            '"amount"',
            '"confirmations"',
            '"match_status"',
            '"matched_at"',
            '"failure_reason"',
            'sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"])',
            'sa.ForeignKeyConstraint(["order_id"], ["orders.id"])',
            'sa.ForeignKeyConstraint(["payment_id"], ["payments.id"])',
            '"uq_trc20_direct_transfers_tx_hash"',
            '"ck_trc20_direct_transfers_match_status"',
            '"ck_trc20_direct_transfers_raw_amount_positive"',
            '"ck_trc20_direct_transfers_amount_positive"',
            '"ck_trc20_direct_transfers_confirmations_nonnegative"',
            '"ix_trc20_direct_transfers_tenant_match_status"',
            '"ix_trc20_direct_transfers_tenant_order"',
            '"ix_trc20_direct_transfers_tenant_payment"',
            '"ix_trc20_direct_transfers_to_address_status"',
        ]:
            self.assertIn(marker, source)
        for forbidden in ('"raw_payload"', '"payload_json"', '"metadata_json"'):
            self.assertNotIn(forbidden, source)


def _load_revision_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载迁移文件：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_single_revision_source(pattern: str) -> str:
    paths = sorted((PROJECT_ROOT / "alembic" / "versions").glob(pattern))
    if len(paths) != 1:
        raise AssertionError(f"迁移文件数量不符合预期：pattern={pattern} count={len(paths)}")
    return paths[0].read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
