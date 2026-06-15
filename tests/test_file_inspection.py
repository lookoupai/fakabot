from __future__ import annotations

import asyncio
import time
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

try:
    from app.services.file_inspection import (
        MAX_OPAQUE_ARCHIVE_BYTES,
        MAX_ZIP_ENTRY_BYTES,
        MAX_ZIP_NESTING_DEPTH,
        ArchiveEntryRisk,
        FileInspectionService,
        _entry_risk,
        _inspection_message,
        _overall_risk,
    )
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过文件扫描测试：{exc.name}") from exc


class FileInspectionRiskRulesTest(unittest.TestCase):
    def test_zip_path_traversal_variants_are_high_risk(self) -> None:
        self.assertEqual("high", _entry_risk("../escape.txt", 1, False))
        self.assertEqual("high", _entry_risk("safe\\..\\escape.txt", 1, False))
        self.assertEqual("high", _entry_risk("/absolute/path.txt", 1, False))
        self.assertEqual("high", _entry_risk("C:\\Windows\\win.ini", 1, False))

    def test_zip_entry_size_and_nesting_limits_are_high_risk(self) -> None:
        nested_path = "/".join(["nested"] * (MAX_ZIP_NESTING_DEPTH + 1) + ["payload.txt"])

        self.assertEqual("high", _entry_risk("large.bin", MAX_ZIP_ENTRY_BYTES + 1, False))
        self.assertEqual("high", _entry_risk(nested_path, 1, False))
        self.assertEqual("low", _entry_risk("safe/readme.txt", MAX_ZIP_ENTRY_BYTES, False))

    def test_telegram_session_and_tdata_entries_are_high_risk(self) -> None:
        self.assertEqual("high", _entry_risk("TData/key_data", 1, False))
        self.assertEqual("high", _entry_risk("accounts/user.session", 1, False))
        self.assertEqual("high", _entry_risk("accounts/user.session-journal", 1, False))
        self.assertEqual("high", _entry_risk("nested\\tdata\\D877F783D5D3EF8C\\map0", 1, False))

    def test_sensitive_credential_paths_are_high_risk(self) -> None:
        self.assertEqual("high", _entry_risk(".env", 1, False))
        self.assertEqual("high", _entry_risk("app/.env.production", 1, False))
        self.assertEqual("high", _entry_risk("keys/id_ed25519", 1, False))
        self.assertEqual("high", _entry_risk("profile/.ssh/id_rsa", 1, False))
        self.assertEqual("high", _entry_risk("profile/.aws/credentials", 1, False))
        self.assertEqual(
            "high",
            _entry_risk("profile/.config/gcloud/application_default_credentials.json", 1, False),
        )

    def test_zip_overall_risk_reports_blocked_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "payload.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("safe/readme.txt", "ok")
                archive.writestr("profile/.aws/credentials", "secret")

            entries = FileInspectionService()._inspect_file(archive_path)

        self.assertEqual("high", _overall_risk(entries))
        self.assertTrue(any(entry.path == "profile/.aws/credentials" and entry.risk_level == "high" for entry in entries))
        self.assertTrue(any(entry.path == "safe/readme.txt" and entry.risk_level == "low" for entry in entries))

    def test_rar_and_7z_file_headers_are_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            valid_rar = directory_path / "valid.rar"
            invalid_rar = directory_path / "invalid.rar"
            valid_7z = directory_path / "valid.7z"
            invalid_7z = directory_path / "invalid.7z"
            valid_rar.write_bytes(_opaque_archive_payload(".rar"))
            invalid_rar.write_bytes(b"not-rar")
            valid_7z.write_bytes(_opaque_archive_payload(".7z"))
            invalid_7z.write_bytes(b"not-7z")

            service = FileInspectionService()
            valid_rar_entry = service._inspect_file(valid_rar)[0]
            invalid_rar_entry = service._inspect_file(invalid_rar)[0]
            valid_7z_entry = service._inspect_file(valid_7z)[0]
            invalid_7z_entry = service._inspect_file(invalid_7z)[0]

        self.assertEqual("medium", valid_rar_entry.risk_level)
        self.assertEqual("high", invalid_rar_entry.risk_level)
        self.assertEqual("medium", valid_7z_entry.risk_level)
        self.assertEqual("high", invalid_7z_entry.risk_level)

    def test_rar_and_7z_shell_scan_blocks_too_small_magic_only_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            tiny_rar = directory_path / "tiny.rar"
            tiny_7z = directory_path / "tiny.7z"
            tiny_rar.write_bytes(b"Rar!\x1a\x07\x00")
            tiny_7z.write_bytes(b"7z\xbc\xaf\x27\x1c")

            service = FileInspectionService()
            rar_entry = service._inspect_file(tiny_rar)[0]
            sevenz_entry = service._inspect_file(tiny_7z)[0]

        self.assertEqual("high", rar_entry.risk_level)
        self.assertEqual("rar_too_small", rar_entry.detected_type)
        self.assertEqual("high", sevenz_entry.risk_level)
        self.assertEqual("7z_too_small", sevenz_entry.detected_type)

    def test_rar_and_7z_shell_scan_blocks_sensitive_outer_names(self) -> None:
        risky_names = (
            "account.session.rar",
            "backup.tdata.7z",
            ".env.rar",
            "id_rsa.7z",
            "cookies.txt.rar",
            "key_data.7z",
        )
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            service = FileInspectionService()
            for name in risky_names:
                with self.subTest(name=name):
                    file_path = directory_path / name
                    file_path.write_bytes(_opaque_archive_payload(file_path.suffix))
                    entry = service._inspect_file(file_path)[0]
                    self.assertEqual("high", entry.risk_level)
                    self.assertTrue(entry.detected_type.endswith("_name_risk"))

    def test_rar_and_7z_oversized_files_are_blocked_without_deep_extracting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            oversized_rar = directory_path / "oversized.rar"
            oversized_7z = directory_path / "oversized.7z"
            oversized_rar.write_bytes(_opaque_archive_payload(".rar"))
            oversized_7z.write_bytes(_opaque_archive_payload(".7z"))
            oversized_size = MAX_OPAQUE_ARCHIVE_BYTES + 1

            original_stat = Path.stat

            def fake_stat(path: Path):
                stat_result = original_stat(path)
                if path in {oversized_rar, oversized_7z}:
                    values = list(stat_result)
                    values[6] = oversized_size
                    return type(stat_result)(values)
                return stat_result

            service = FileInspectionService()
            with unittest.mock.patch.object(Path, "stat", fake_stat):
                rar_entry = service._inspect_file(oversized_rar)[0]
                sevenz_entry = service._inspect_file(oversized_7z)[0]

        self.assertEqual("high", rar_entry.risk_level)
        self.assertEqual("rar_oversized", rar_entry.detected_type)
        self.assertEqual(oversized_size, rar_entry.size_bytes)
        self.assertEqual("high", sevenz_entry.risk_level)
        self.assertEqual("7z_oversized", sevenz_entry.detected_type)

    def test_rar_and_7z_medium_risk_message_states_only_header_and_size_check(self) -> None:
        message = _inspection_message(
            Path("payload.rar"),
            "medium",
            1,
            False,
        )

        self.assertEqual("文件头和大小校验通过，RAR/7Z 内容待后续深度扫描", message)

    def test_inspection_timeout_blocks_uploaded_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            file_path = Path(directory) / "slow.zip"
            file_path.write_bytes(b"PK\x03\x04")
            uploaded_file = SimpleNamespace(id=77, tenant_id=7, status="pending")
            session = _FakeInspectionSession(uploaded_file)
            service = FileInspectionService(inspection_timeout_seconds=0.01)

            def slow_inspection(path: Path) -> list[object]:
                time.sleep(0.05)
                return []

            service._inspect_file = slow_inspection  # type: ignore[method-assign]
            result = asyncio.run(
                service.inspect_uploaded_file(
                    session=session,  # type: ignore[arg-type]
                    tenant_id=7,
                    uploaded_file_id=77,
                    file_path=file_path,
                    requested_by_user_id=42,
                )
            )

        job = session.added[0]
        self.assertTrue(result.blocked)
        self.assertEqual("high", result.risk_level)
        self.assertEqual("文件扫描超时，已阻断绑定", result.message)
        self.assertEqual("blocked", uploaded_file.status)
        self.assertEqual("failed", job.status)
        self.assertEqual("文件扫描超时", job.error_message)


class _FakeInspectionSession:
    def __init__(self, uploaded_file: object) -> None:
        self.uploaded_file = uploaded_file
        self.added: list[object] = []

    async def get(self, model: object, item_id: int) -> object:
        return self.uploaded_file

    def add(self, item: object) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        if self.added and getattr(self.added[0], "id", None) is None:
            self.added[0].id = 1


def _opaque_archive_payload(suffix: str) -> bytes:
    if suffix == ".rar":
        return b"Rar!\x1a\x07\x00" + (b"x" * 64)
    if suffix == ".7z":
        return b"7z\xbc\xaf\x27\x1c" + (b"x" * 64)
    raise ValueError("unsupported suffix")


if __name__ == "__main__":
    unittest.main()
