from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DockerignoreContractTest(unittest.TestCase):
    def test_local_runtime_and_secret_artifacts_are_excluded_from_image_context(self) -> None:
        dockerignore = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        patterns = {line.strip() for line in dockerignore if line.strip() and not line.startswith("#")}

        expected_patterns = {
            ".env",
            ".env.*",
            ".venv/",
            "venv/",
            "env/",
            "node_modules/",
            "package-lock.json",
            "package.json",
            "data/",
            "storage/",
            "*.db",
            "*.sqlite",
            "*.sqlite3",
            "logs/",
        }

        self.assertTrue(expected_patterns.issubset(patterns))


if __name__ == "__main__":
    unittest.main()
