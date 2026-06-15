from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DockerComposeContractTest(unittest.TestCase):
    def test_app_healthcheck_uses_ready_endpoint(self) -> None:
        compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("http://127.0.0.1:58001/ready", compose)
        self.assertNotIn("http://127.0.0.1:58001/health\", timeout=3", compose)


if __name__ == "__main__":
    unittest.main()
