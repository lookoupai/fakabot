from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
DEFAULT_SQL_OUTPUT = Path("/tmp/fakabot_alembic_head.sql")
SAFE_OFFLINE_DATABASE_URL = "postgresql+asyncpg://fakabot:fakabot@postgres:5432/fakabot"
EXPECTED_HEAD = "20260610_0024"
EXPECTED_ROOT = "20260606_0001"
EXPECTED_TABLES = {
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


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify Alembic migrations without connecting to or mutating a database.",
    )
    parser.add_argument(
        "--sql-output",
        default=str(DEFAULT_SQL_OUTPUT),
        help="Path for generated offline SQL. Default: /tmp/fakabot_alembic_head.sql",
    )
    args = parser.parse_args(argv)

    sql_output = Path(args.sql_output)
    try:
        metadata_count = verify_model_metadata()
        root, head, revision_count = verify_revision_chain()
        heads_output = run_alembic_heads()
        sql_lines = generate_offline_sql(sql_output)
    except Exception as exc:
        print(f"migration verification failed: {exc}", file=sys.stderr)
        return 1

    print("[OK] alembic config: alembic.ini")
    print(f"[OK] revisions: files={revision_count} base={root} head={head}")
    print(f"[OK] metadata: tables={metadata_count}")
    print("[OK] alembic env imports aggregate models package")
    print(f"[OK] alembic heads: {heads_output}")
    print(f"[OK] offline sql generated: path={sql_output} lines={sql_lines}")
    print("[OK] online_upgrade_executed=false")
    print("[OK] migration verification completed")
    return 0


def verify_model_metadata() -> int:
    from app.db.base import Base
    import app.db.models  # noqa: F401

    tables = set(Base.metadata.tables)
    missing = sorted(EXPECTED_TABLES - tables)
    if missing:
        raise RuntimeError(f"missing metadata tables: {', '.join(missing)}")
    return len(tables)


def verify_revision_chain() -> tuple[str, str, int]:
    revisions = {}
    down_revisions = {}
    for path in sorted((PROJECT_ROOT / "alembic" / "versions").glob("*.py")):
        module = _load_revision_module(path)
        revisions[module.revision] = path.name
        down_revisions[module.revision] = module.down_revision

    roots = sorted(revision for revision, down_revision in down_revisions.items() if down_revision is None)
    if roots != [EXPECTED_ROOT]:
        raise RuntimeError(f"unexpected revision roots: {roots}")
    for revision, down_revision in down_revisions.items():
        if down_revision is None:
            continue
        if not isinstance(down_revision, str):
            raise RuntimeError(f"non-linear down_revision for {revision}: {down_revision}")
        if down_revision not in revisions:
            raise RuntimeError(f"missing down_revision target for {revision}: {down_revision}")
    referenced = {down_revision for down_revision in down_revisions.values() if down_revision is not None}
    heads = sorted(set(revisions) - referenced)
    if heads != [EXPECTED_HEAD]:
        raise RuntimeError(f"unexpected revision heads: {heads}")
    return roots[0], heads[0], len(revisions)


def run_alembic_heads() -> str:
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=PROJECT_ROOT,
        env=_offline_env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "alembic heads failed")
    output = completed.stdout.strip()
    if EXPECTED_HEAD not in output:
        raise RuntimeError(f"unexpected alembic heads output: {output}")
    return output


def generate_offline_sql(output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as stdout_file:
        completed = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
            cwd=PROJECT_ROOT,
            env=_offline_env(),
            text=True,
            stdout=stdout_file,
            stderr=subprocess.PIPE,
            check=False,
        )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "alembic offline SQL generation failed")
    return sum(1 for _ in output_path.open("r", encoding="utf-8"))


def _offline_env() -> dict[str, str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = SAFE_OFFLINE_DATABASE_URL
    return env


def _load_revision_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load migration file: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    raise SystemExit(main())
