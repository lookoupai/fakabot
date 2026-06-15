from __future__ import annotations

import unittest
from pathlib import Path

try:
    from scripts import verify_migrations
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过迁移验证脚本测试：{exc.name}") from exc


class MigrationVerifierTest(unittest.TestCase):
    def test_revision_chain_and_metadata_checks_pass(self) -> None:
        self.assertGreaterEqual(verify_migrations.verify_model_metadata(), 36)
        root, head, revision_count = verify_migrations.verify_revision_chain()

        self.assertEqual("20260606_0001", root)
        self.assertEqual("20260610_0024", head)
        self.assertEqual(24, revision_count)

    def test_verifier_tracks_trc20_direct_transfer_revision_and_metadata_table(self) -> None:
        source = Path("scripts/verify_migrations.py").read_text(encoding="utf-8")

        self.assertEqual("20260610_0024", verify_migrations.EXPECTED_HEAD)
        self.assertIn("trc20_direct_transfers", verify_migrations.EXPECTED_TABLES)
        self.assertIn('EXPECTED_HEAD = "20260610_0024"', source)
        self.assertIn('"trc20_direct_transfers"', source)

    def test_script_defaults_to_tmp_sql_output_and_offline_generation(self) -> None:
        self.assertEqual(Path("/tmp/fakabot_alembic_head.sql"), verify_migrations.DEFAULT_SQL_OUTPUT)
        self.assertTrue(verify_migrations.SAFE_OFFLINE_DATABASE_URL.startswith("postgresql+asyncpg://"))
        source = Path("scripts/verify_migrations.py").read_text(encoding="utf-8")

        self.assertIn('"upgrade", "head", "--sql"', source)
        self.assertNotIn('"upgrade", "head"],', source)
        self.assertIn("online_upgrade_executed=false", source)


if __name__ == "__main__":
    unittest.main()
