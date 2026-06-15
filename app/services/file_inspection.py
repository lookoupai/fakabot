from __future__ import annotations

import asyncio
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import List, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.products import FileArchiveEntry, FileProcessingJob, UploadedFile

ARCHIVE_SUFFIXES = {".zip", ".rar", ".7z"}
BLOCKED_ARCHIVE_SUFFIXES = {".session", ".session-journal"}
BLOCKED_ARCHIVE_NAMES = {
    ".env",
    ".netrc",
    "auth_key",
    "cookies.txt",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "key_data",
}
BLOCKED_ARCHIVE_PARTS = {"tdata"}
SENSITIVE_CREDENTIAL_PATHS = {
    (".aws", "credentials"),
    (".config", "gcloud", "application_default_credentials.json"),
}
MAX_ZIP_ENTRIES = 1000
MAX_ZIP_ENTRY_BYTES = 50 * 1024 * 1024
MAX_ZIP_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_ZIP_NESTING_DEPTH = 12
MAX_OPAQUE_ARCHIVE_BYTES = 100 * 1024 * 1024
MIN_OPAQUE_ARCHIVE_BYTES = 32
FILE_INSPECTION_TIMEOUT_SECONDS = 30.0
OPAQUE_ARCHIVE_OVERSIZED_TYPES = {"rar": "rar_oversized", "7z": "7z_oversized"}
OPAQUE_ARCHIVE_TOO_SMALL_TYPES = {"rar": "rar_too_small", "7z": "7z_too_small"}


@dataclass
class InspectionResult:
    job_id: int
    risk_level: str
    entry_count: int
    blocked: bool
    message: str


@dataclass
class ArchiveEntryRisk:
    path: str
    size_bytes: int
    detected_type: str
    risk_level: str


class FileInspectionService:
    def __init__(self, inspection_timeout_seconds: float = FILE_INSPECTION_TIMEOUT_SECONDS) -> None:
        self._inspection_timeout_seconds = inspection_timeout_seconds

    async def inspect_uploaded_file(
        self,
        session: AsyncSession,
        tenant_id: int,
        uploaded_file_id: int,
        file_path: Path,
        requested_by_user_id: int,
    ) -> InspectionResult:
        uploaded_file = await session.get(UploadedFile, uploaded_file_id)
        if uploaded_file is None or uploaded_file.tenant_id != tenant_id:
            raise ValueError("文件不存在或无权限")

        now = datetime.now(timezone.utc)
        job = FileProcessingJob(
            tenant_id=tenant_id,
            requested_by_user_id=requested_by_user_id,
            source_file_id=uploaded_file_id,
            job_type="archive_scan",
            status="running",
            progress_percent=0,
            started_at=now,
        )
        session.add(job)
        await session.flush()

        try:
            result = await self._inspect_file_with_timeout(file_path)
        except asyncio.TimeoutError:
            job.status = "failed"
            job.error_message = "文件扫描超时"
            job.finished_at = datetime.now(timezone.utc)
            uploaded_file.status = "blocked"
            await session.flush()
            return InspectionResult(
                job_id=job.id,
                risk_level="high",
                entry_count=0,
                blocked=True,
                message="文件扫描超时，已阻断绑定",
            )
        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)[:1000]
            job.finished_at = datetime.now(timezone.utc)
            uploaded_file.status = "blocked"
            await session.flush()
            return InspectionResult(
                job_id=job.id,
                risk_level="high",
                entry_count=0,
                blocked=True,
                message="文件扫描失败，已阻断绑定",
            )

        for entry in result:
            session.add(
                FileArchiveEntry(
                    tenant_id=tenant_id,
                    uploaded_file_id=uploaded_file_id,
                    path=entry.path,
                    size_bytes=entry.size_bytes,
                    detected_type=entry.detected_type,
                    risk_level=entry.risk_level,
                )
            )

        risk_level = _overall_risk(result)
        blocked = risk_level == "high"
        uploaded_file.status = "blocked" if blocked else "active"
        job.status = "completed"
        job.progress_percent = 100
        job.finished_at = datetime.now(timezone.utc)
        await session.flush()
        return InspectionResult(
            job_id=job.id,
            risk_level=risk_level,
            entry_count=len(result),
            blocked=blocked,
            message=_inspection_message(file_path, risk_level, len(result), blocked),
        )

    async def _inspect_file_with_timeout(self, file_path: Path) -> List[ArchiveEntryRisk]:
        return await asyncio.wait_for(
            asyncio.to_thread(self._inspect_file, file_path),
            timeout=self._inspection_timeout_seconds,
        )

    def _inspect_file(self, file_path: Path) -> List[ArchiveEntryRisk]:
        suffix = file_path.suffix.lower()
        if suffix == ".zip":
            return self._inspect_zip(file_path)
        if suffix == ".rar":
            return [_inspect_opaque_archive(file_path, "rar", (b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00"))]
        if suffix == ".7z":
            return [_inspect_opaque_archive(file_path, "7z", (b"7z\xbc\xaf\x27\x1c",))]
        return [
            ArchiveEntryRisk(
                path=file_path.name,
                size_bytes=file_path.stat().st_size,
                detected_type=suffix.lstrip(".") or "file",
                risk_level="low",
            )
        ]

    def _inspect_zip(self, file_path: Path) -> List[ArchiveEntryRisk]:
        entries: List[ArchiveEntryRisk] = []
        total_size = 0
        with zipfile.ZipFile(file_path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                entries.append(
                    ArchiveEntryRisk(
                        path=file_path.name,
                        size_bytes=file_path.stat().st_size,
                        detected_type="zip",
                        risk_level="high",
                    )
                )
            for info in infos:
                total_size += int(info.file_size)
                risk_level = _entry_risk(info.filename, int(info.file_size), bool(info.flag_bits & 0x1))
                entries.append(
                    ArchiveEntryRisk(
                        path=info.filename[:1000],
                        size_bytes=int(info.file_size),
                        detected_type=Path(info.filename).suffix.lower().lstrip(".") or "file",
                        risk_level=risk_level,
                    )
                )
        if total_size > MAX_ZIP_UNCOMPRESSED_BYTES:
            entries.append(
                ArchiveEntryRisk(
                    path=file_path.name,
                    size_bytes=total_size,
                    detected_type="zip_total_uncompressed",
                    risk_level="high",
                )
            )
        return entries


def _entry_risk(path: str, size_bytes: int, encrypted: bool) -> str:
    normalized = PurePosixPath(path.replace("\\", "/"))
    parts = tuple(part.lower() for part in normalized.parts if part not in {"", "."})
    part_set = set(parts)
    name = normalized.name.lower()
    suffixes = {Path(part).suffix.lower() for part in parts}
    if normalized.is_absolute() or _is_windows_absolute_path(parts) or ".." in normalized.parts:
        return "high"
    if (
        part_set & BLOCKED_ARCHIVE_PARTS
        or suffixes & BLOCKED_ARCHIVE_SUFFIXES
        or name in BLOCKED_ARCHIVE_NAMES
        or name.startswith(".env.")
        or _is_sensitive_credential_path(parts)
    ):
        return "high"
    if size_bytes > MAX_ZIP_ENTRY_BYTES:
        return "high"
    if _zip_nesting_depth(parts) > MAX_ZIP_NESTING_DEPTH:
        return "high"
    if encrypted:
        return "medium"
    return "low"


def _zip_nesting_depth(parts: Tuple[str, ...]) -> int:
    if not parts:
        return 0
    return max(len(parts) - 1, 0)


def _is_windows_absolute_path(parts: Tuple[str, ...]) -> bool:
    if not parts:
        return False
    first = parts[0]
    return len(first) == 2 and first[0].isalpha() and first[1] == ":"


def _is_sensitive_credential_path(parts: Tuple[str, ...]) -> bool:
    return any(_contains_subsequence(parts, sensitive_path) for sensitive_path in SENSITIVE_CREDENTIAL_PATHS)


def _contains_subsequence(parts: Tuple[str, ...], pattern: Tuple[str, ...]) -> bool:
    if len(pattern) > len(parts):
        return False
    return any(parts[index : index + len(pattern)] == pattern for index in range(len(parts) - len(pattern) + 1))


def _inspect_opaque_archive(file_path: Path, detected_type: str, signatures: Tuple[bytes, ...]) -> ArchiveEntryRisk:
    size_bytes = file_path.stat().st_size
    if size_bytes > MAX_OPAQUE_ARCHIVE_BYTES:
        return ArchiveEntryRisk(
            path=file_path.name,
            size_bytes=size_bytes,
            detected_type=OPAQUE_ARCHIVE_OVERSIZED_TYPES[detected_type],
            risk_level="high",
        )
    if size_bytes < MIN_OPAQUE_ARCHIVE_BYTES:
        return ArchiveEntryRisk(
            path=file_path.name,
            size_bytes=size_bytes,
            detected_type=OPAQUE_ARCHIVE_TOO_SMALL_TYPES[detected_type],
            risk_level="high",
        )
    if _opaque_archive_outer_name_is_sensitive(file_path.name):
        return ArchiveEntryRisk(
            path=file_path.name,
            size_bytes=size_bytes,
            detected_type=f"{detected_type}_name_risk",
            risk_level="high",
        )
    with file_path.open("rb") as file:
        header = file.read(8)
    risk_level = "medium" if any(header.startswith(signature) for signature in signatures) else "high"
    return ArchiveEntryRisk(
        path=file_path.name,
        size_bytes=size_bytes,
        detected_type=detected_type,
        risk_level=risk_level,
    )


def _opaque_archive_outer_name_is_sensitive(filename: str) -> bool:
    name = Path(filename).name.lower()
    archive_suffix = Path(name).suffix.lower()
    inner_name = name[: -len(archive_suffix)] if archive_suffix in {".rar", ".7z"} else name
    if not inner_name:
        return False
    inner_suffixes = {Path(part).suffix.lower() for part in inner_name.split(".") if part}
    if (
        inner_name in BLOCKED_ARCHIVE_NAMES
        or inner_name.startswith(".env")
        or Path(inner_name).suffix.lower() in BLOCKED_ARCHIVE_SUFFIXES
        or inner_suffixes & BLOCKED_ARCHIVE_SUFFIXES
    ):
        return True
    normalized = inner_name.replace("-", ".").replace("_", ".")
    parts = {part for part in normalized.split(".") if part}
    if parts & BLOCKED_ARCHIVE_PARTS:
        return True
    return any(blocked_name.replace("_", ".") in normalized for blocked_name in BLOCKED_ARCHIVE_NAMES)


def _overall_risk(entries: List[ArchiveEntryRisk]) -> str:
    if any(entry.risk_level == "high" for entry in entries):
        return "high"
    if any(entry.risk_level == "medium" for entry in entries):
        return "medium"
    return "low"


def _inspection_message(file_path: Path, risk_level: str, entry_count: int, blocked: bool) -> str:
    if blocked:
        return "文件扫描发现高风险内容，已阻断绑定"
    if file_path.suffix.lower() in {".rar", ".7z"} and risk_level == "medium":
        return "文件头和大小校验通过，RAR/7Z 内容待后续深度扫描"
    if file_path.suffix.lower() in ARCHIVE_SUFFIXES:
        return f"压缩包扫描完成，条目数：{entry_count}"
    return "普通文件基础校验通过"
