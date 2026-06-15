from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from aiogram import Bot
from aiogram.types import Document

from app.config import Settings

BLOCKED_SUFFIXES = {".session", ".session-journal"}
GENERIC_MIME_TYPES = {"application/octet-stream", "binary/octet-stream"}
ARCHIVE_MIME_TYPES = {
    ".zip": {"application/zip", "application/x-zip-compressed", "multipart/x-zip"},
    ".rar": {"application/vnd.rar", "application/x-rar", "application/x-rar-compressed"},
    ".7z": {"application/x-7z-compressed"},
}
ARCHIVE_SUFFIX_BY_MIME = {
    mime_type: suffix for suffix, mime_types in ARCHIVE_MIME_TYPES.items() for mime_type in mime_types
}
ALLOWED_UPLOAD_SUFFIXES = set(ARCHIVE_MIME_TYPES)


@dataclass
class StoredTelegramFile:
    storage_key: str
    original_filename: str
    content_type: Optional[str]
    size_bytes: int
    sha256: str


@dataclass
class DownloadTokenPayload:
    tenant_id: int
    uploaded_file_id: int
    order_id: int
    expires_at: int


class FileStorageService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def store_telegram_document(
        self,
        bot: Bot,
        document: Document,
        tenant_id: int,
    ) -> StoredTelegramFile:
        original_filename = _safe_filename(document.file_name or "file.bin")
        _validate_document_file_identity(original_filename, document.mime_type)

        storage_key = f"tenants/{tenant_id}/files/{secrets.token_urlsafe(18)}_{original_filename}"
        target_path = self.resolve_storage_key(storage_key)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.with_suffix(target_path.suffix + ".tmp")

        try:
            telegram_file = await bot.get_file(document.file_id)
            if not telegram_file.file_path:
                raise ValueError("无法获取 Telegram 文件路径")
            await bot.download_file(telegram_file.file_path, destination=temp_path)
            os.replace(temp_path, target_path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

        return StoredTelegramFile(
            storage_key=storage_key,
            original_filename=original_filename,
            content_type=document.mime_type,
            size_bytes=target_path.stat().st_size,
            sha256=_sha256_file(target_path),
        )

    def store_upload_file(
        self,
        *,
        filename: str,
        content_type: Optional[str],
        payload: bytes,
        tenant_id: int,
    ) -> StoredTelegramFile:
        original_filename = _safe_filename(filename or "file.bin")
        _validate_document_file_identity(original_filename, content_type)

        storage_key = f"tenants/{tenant_id}/files/{secrets.token_urlsafe(18)}_{original_filename}"
        target_path = self.resolve_storage_key(storage_key)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.with_suffix(target_path.suffix + ".tmp")
        try:
            temp_path.write_bytes(payload)
            os.replace(temp_path, target_path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

        return StoredTelegramFile(
            storage_key=storage_key,
            original_filename=original_filename,
            content_type=content_type,
            size_bytes=target_path.stat().st_size,
            sha256=_sha256_file(target_path),
        )

    def resolve_storage_key(self, storage_key: str) -> Path:
        storage_root = Path(self._settings.storage_root).resolve()
        path = (storage_root / storage_key).resolve()
        if storage_root not in path.parents and path != storage_root:
            raise ValueError("非法文件路径")
        return path


class DownloadTokenService:
    def __init__(self, settings: Settings) -> None:
        if settings.token_encryption_key is None:
            raise RuntimeError("缺少 TOKEN_ENCRYPTION_KEY，不能生成下载链接")
        self._secret = settings.token_encryption_key.get_secret_value().encode()

    def create_token(
        self,
        tenant_id: int,
        uploaded_file_id: int,
        order_id: int,
        ttl_seconds: int = 3600,
    ) -> str:
        payload = {
            "tenant_id": tenant_id,
            "uploaded_file_id": uploaded_file_id,
            "order_id": order_id,
            "expires_at": int(time.time()) + ttl_seconds,
        }
        payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        signature = hmac.new(self._secret, payload_bytes, hashlib.sha256).digest()
        return f"{_b64encode(payload_bytes)}.{_b64encode(signature)}"

    def verify_token(self, token: str) -> DownloadTokenPayload:
        try:
            payload_text, signature_text = token.split(".", 1)
            payload_bytes = _b64decode(payload_text)
            signature = _b64decode(signature_text)
        except ValueError:
            raise ValueError("下载链接无效")

        expected_signature = hmac.new(self._secret, payload_bytes, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected_signature):
            raise ValueError("下载链接签名无效")

        data: Dict[str, Any] = json.loads(payload_bytes.decode())
        expires_at = int(data["expires_at"])
        if expires_at < int(time.time()):
            raise ValueError("下载链接已过期")
        return DownloadTokenPayload(
            tenant_id=int(data["tenant_id"]),
            uploaded_file_id=int(data["uploaded_file_id"]),
            order_id=int(data["order_id"]),
            expires_at=expires_at,
        )


def _safe_filename(filename: str) -> str:
    base_name = Path(filename).name.strip() or "file.bin"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", base_name)[:120]


def _validate_document_file_identity(filename: str, mime_type: Optional[str]) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix in BLOCKED_SUFFIXES:
        raise ValueError("不支持上传 Telegram 会话类文件")

    normalized_mime_type = _normalize_mime_type(mime_type)
    expected_suffix = ARCHIVE_SUFFIX_BY_MIME.get(normalized_mime_type)
    if expected_suffix is not None and suffix != expected_suffix:
        raise ValueError(f"Telegram MIME 类型显示这是 {expected_suffix} 压缩包，请使用匹配的文件后缀。")
    if suffix not in ALLOWED_UPLOAD_SUFFIXES:
        raise ValueError("文件商品只支持 zip/rar/7z 压缩包。")
    if normalized_mime_type is None or normalized_mime_type in GENERIC_MIME_TYPES:
        return

    if normalized_mime_type not in ARCHIVE_MIME_TYPES[suffix]:
        raise ValueError("文件扩展名与 Telegram MIME 类型不一致，请检查后重新上传。")


def _normalize_mime_type(mime_type: Optional[str]) -> Optional[str]:
    if mime_type is None:
        return None
    value = mime_type.split(";", 1)[0].strip().lower()
    return value or None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode())
