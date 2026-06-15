from __future__ import annotations

import tempfile
import unittest
import zipfile
from decimal import Decimal
from pathlib import Path

try:
    from cryptography.fernet import Fernet
    from pydantic import SecretStr

    from app.config import Settings
    from app.services.audit import AuditLogService
    from app.services.file_inspection import FileInspectionService, _entry_risk, _overall_risk
    from app.services.payments.epusdt import payload_hash, sign_payload
    from app.services.token_crypto import TokenCrypto, mask_token
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过 smoke 测试：{exc.name}") from exc


class TokenCryptoSmokeTest(unittest.TestCase):
    def test_encrypt_decrypt_hash_and_mask_token(self) -> None:
        settings = Settings(
            token_encryption_key=SecretStr(Fernet.generate_key().decode()),
        )
        crypto = TokenCrypto(settings)
        token = "123456789:AAExampleTelegramBotTokenSecret"

        encrypted = crypto.encrypt_token(token)

        self.assertNotEqual(token, encrypted)
        self.assertEqual(token, crypto.decrypt_token(encrypted))
        self.assertEqual(64, len(crypto.token_hash(token)))
        self.assertEqual(crypto.token_hash(token), crypto.token_hash(token))
        self.assertEqual("1234***:AAEx***cret", mask_token(token))
        self.assertEqual("***", mask_token("invalid-token"))

    def test_missing_encryption_key_fails_fast(self) -> None:
        settings = Settings(token_encryption_key=None)

        with self.assertRaises(RuntimeError):
            TokenCrypto(settings)


class AuditRedactionSmokeTest(unittest.TestCase):
    def test_redacts_nested_sensitive_metadata(self) -> None:
        metadata = {
            "token": "raw-token",
            "nested": {"secret_key": "raw-secret", "safe": "visible"},
            "items": [{"plain_key": "raw-key", "name": "kept"}],
            "amount": "10.00",
        }

        redacted = AuditLogService()._redact_metadata(metadata)

        self.assertEqual("***", redacted["token"])
        self.assertEqual("***", redacted["nested"]["secret_key"])
        self.assertEqual("visible", redacted["nested"]["safe"])
        self.assertEqual("***", redacted["items"][0]["plain_key"])
        self.assertEqual("kept", redacted["items"][0]["name"])
        self.assertEqual("10.00", redacted["amount"])


class EpusdtSmokeTest(unittest.TestCase):
    def test_signature_ignores_empty_values_and_existing_signature(self) -> None:
        payload = {
            "pid": "merchant",
            "order_id": "ORD123",
            "amount": "10.50",
            "empty": "",
            "none": None,
            "signature": "wrong",
        }

        signature = sign_payload(payload, "secret")

        self.assertEqual(signature, sign_payload({**payload, "signature": signature}, "secret"))
        self.assertEqual(64, len(payload_hash(payload)))


class FileInspectionSmokeTest(unittest.TestCase):
    def test_zip_path_traversal_is_high_risk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "bad.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../escape.txt", "blocked")

            entries = FileInspectionService()._inspect_file(archive_path)

        self.assertEqual("high", _overall_risk(entries))
        self.assertTrue(any(entry.path == "../escape.txt" and entry.risk_level == "high" for entry in entries))

    def test_archive_entry_risk_rules(self) -> None:
        self.assertEqual("high", _entry_risk("/absolute/path.txt", 1, False))
        self.assertEqual("high", _entry_risk("tdata/config", 1, False))
        self.assertEqual("high", _entry_risk("account.session", 1, False))
        self.assertEqual("medium", _entry_risk("safe.txt", 1, True))
        self.assertEqual("low", _entry_risk("safe.txt", 1, False))


if __name__ == "__main__":
    unittest.main()
