from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

try:
    from pydantic import SecretStr

    from app.bots.routers.tenant import upload_file
    from app.config import Settings
    from app.services.delivery import build_delivery_text
    from app.services.files import DownloadTokenService, FileStorageService
    from app.services.payments import DeliveryInstruction
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过文件交付契约测试：{exc.name}") from exc


class FileDeliveryContractTest(unittest.TestCase):
    def test_download_token_rejects_expired_token(self) -> None:
        service = DownloadTokenService(_settings())
        token = service.create_token(
            tenant_id=7,
            uploaded_file_id=77,
            order_id=12,
            ttl_seconds=-1,
        )

        with self.assertRaisesRegex(ValueError, "下载链接已过期"):
            service.verify_token(token)

    def test_storage_key_traversal_error_does_not_leak_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = FileStorageService(_settings(storage_root=directory))

            with self.assertRaises(ValueError) as context:
                service.resolve_storage_key("../outside/private.zip")

        message = str(context.exception)
        self.assertEqual("非法文件路径", message)
        self.assertNotIn("outside/private.zip", message)
        self.assertNotIn(directory, message)

    def test_file_delivery_text_uses_token_url_without_storage_path(self) -> None:
        settings = _settings(
            public_base_url="https://store.example",
            storage_root="/srv/private/storage",
        )
        instruction = DeliveryInstruction(
            delivery_record_id=99,
            order_id=12,
            tenant_id=7,
            buyer_telegram_user_id=42,
            delivery_type="file_download",
            out_trade_no="ORD<123>",
            uploaded_file_id=77,
            uploaded_file_tenant_id=9,
        )

        text = asyncio.run(build_delivery_text(SimpleNamespace(), settings, SimpleNamespace(), instruction))

        self.assertIn("https://store.example/files/download/", text)
        self.assertIn("有效期：1 小时", text)
        self.assertIn("ORD&lt;123&gt;", text)
        self.assertNotIn("/srv/private/storage", text)
        self.assertNotIn("tenants/9/files", text)
        self.assertNotIn("storage_key", text)
        token = text.rsplit("/files/download/", 1)[1]
        payload = DownloadTokenService(settings).verify_token(token)
        self.assertEqual(9, payload.tenant_id)
        self.assertEqual(77, payload.uploaded_file_id)
        self.assertEqual(12, payload.order_id)

    def test_upload_file_without_file_size_returns_actionable_prompt(self) -> None:
        message = _message(_document(file_size=None, file_name="payload.zip"))

        asyncio.run(_run_upload_file(message, product=_product(file_size_limit=1024)))

        message.answer.assert_awaited_once_with("无法获取文件大小，已拒绝上传。")

    def test_upload_file_over_size_limit_returns_limit_prompt(self) -> None:
        message = _message(_document(file_size=2048, file_name="payload.zip"))

        asyncio.run(_run_upload_file(message, product=_product(file_size_limit=1024)))

        message.answer.assert_awaited_once_with("文件超过限制，当前商品最大允许 1024 字节。")

    def test_upload_file_blocked_suffix_returns_type_prompt(self) -> None:
        message = _message(_document(file_size=512, file_name="account.session"))

        async def store_telegram_document(self: object, **kwargs: object) -> object:
            raise ValueError("不支持上传 Telegram 会话类文件")

        with patch(
            "app.bots.routers.tenant.FileStorageService.store_telegram_document",
            store_telegram_document,
        ):
            asyncio.run(_run_upload_file(message, product=_product(file_size_limit=1024)))

        message.answer.assert_awaited_once_with("不支持上传 Telegram 会话类文件")

    def test_upload_file_mime_mismatch_returns_identity_prompt(self) -> None:
        message = _message(_document(file_size=512, file_name="payload.zip", mime_type="text/plain"))
        prompt = "文件扩展名与 Telegram MIME 类型不一致，请检查后重新上传。"

        async def store_telegram_document(self: object, **kwargs: object) -> object:
            raise ValueError(prompt)

        with patch(
            "app.bots.routers.tenant.FileStorageService.store_telegram_document",
            store_telegram_document,
        ):
            asyncio.run(_run_upload_file(message, product=_product(file_size_limit=1024)))

        message.answer.assert_awaited_once_with(prompt)

    def test_store_rejects_archive_extension_with_mismatched_mime_before_download(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = FileStorageService(_settings(storage_root=directory))
            bot = SimpleNamespace(get_file=AsyncMock(), download_file=AsyncMock())
            document = _document(file_size=512, file_name="payload.zip", mime_type="text/plain")

            with self.assertRaisesRegex(ValueError, "文件扩展名与 Telegram MIME 类型不一致"):
                asyncio.run(service.store_telegram_document(bot, document, tenant_id=7))

        bot.get_file.assert_not_awaited()
        bot.download_file.assert_not_awaited()

    def test_store_rejects_archive_mime_without_matching_suffix_before_download(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = FileStorageService(_settings(storage_root=directory))
            bot = SimpleNamespace(get_file=AsyncMock(), download_file=AsyncMock())
            document = _document(file_size=512, file_name="payload.txt", mime_type="application/zip")

            with self.assertRaisesRegex(ValueError, "请使用匹配的文件后缀"):
                asyncio.run(service.store_telegram_document(bot, document, tenant_id=7))

        bot.get_file.assert_not_awaited()
        bot.download_file.assert_not_awaited()

    def test_store_rejects_non_archive_extension_before_download(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = FileStorageService(_settings(storage_root=directory))
            bot = SimpleNamespace(get_file=AsyncMock(), download_file=AsyncMock())
            document = _document(file_size=512, file_name="payload.txt", mime_type="text/plain")

            with self.assertRaisesRegex(ValueError, "只支持 zip/rar/7z"):
                asyncio.run(service.store_telegram_document(bot, document, tenant_id=7))

        bot.get_file.assert_not_awaited()
        bot.download_file.assert_not_awaited()

    def test_store_rejects_non_archive_with_generic_mime_before_download(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = FileStorageService(_settings(storage_root=directory))
            bot = SimpleNamespace(get_file=AsyncMock(), download_file=AsyncMock())
            document = _document(file_size=512, file_name="payload.exe", mime_type="application/octet-stream")

            with self.assertRaisesRegex(ValueError, "只支持 zip/rar/7z"):
                asyncio.run(service.store_telegram_document(bot, document, tenant_id=7))

        bot.get_file.assert_not_awaited()
        bot.download_file.assert_not_awaited()

    def test_store_rejects_top_level_session_journal_before_download(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = FileStorageService(_settings(storage_root=directory))
            bot = SimpleNamespace(get_file=AsyncMock(), download_file=AsyncMock())
            document = _document(file_size=512, file_name="account.session-journal")

            with self.assertRaisesRegex(ValueError, "不支持上传 Telegram 会话类文件"):
                asyncio.run(service.store_telegram_document(bot, document, tenant_id=7))

        bot.get_file.assert_not_awaited()
        bot.download_file.assert_not_awaited()

    def test_store_allows_archive_with_generic_mime_and_persists_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = FileStorageService(_settings(storage_root=directory))
            bot = _FakeDownloadBot(b"PK\x03\x04payload")
            document = _document(
                file_size=11,
                file_name="payload.zip",
                mime_type="application/octet-stream",
            )

            stored_file = asyncio.run(service.store_telegram_document(bot, document, tenant_id=7))
            stored_path = service.resolve_storage_key(stored_file.storage_key)

            self.assertEqual("payload.zip", stored_file.original_filename)
            self.assertEqual("application/octet-stream", stored_file.content_type)
            self.assertEqual(11, stored_file.size_bytes)
            self.assertEqual(b"PK\x03\x04payload", stored_path.read_bytes())
            self.assertTrue(stored_file.storage_key.startswith("tenants/7/files/"))

    def test_store_allows_archive_with_missing_mime_and_persists_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = FileStorageService(_settings(storage_root=directory))
            bot = _FakeDownloadBot(b"PK\x03\x04payload")
            document = _document(file_size=11, file_name="payload.zip", mime_type=None)

            stored_file = asyncio.run(service.store_telegram_document(bot, document, tenant_id=7))
            stored_path = service.resolve_storage_key(stored_file.storage_key)

            self.assertIsNone(stored_file.content_type)
            self.assertEqual(b"PK\x03\x04payload", stored_path.read_bytes())
            self.assertTrue(stored_file.storage_key.startswith("tenants/7/files/"))

    def test_store_allows_archive_mime_with_case_and_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = FileStorageService(_settings(storage_root=directory))
            bot = _FakeDownloadBot(b"PK\x03\x04payload")
            document = _document(
                file_size=11,
                file_name="payload.zip",
                mime_type=" Application/ZIP ; charset=binary ",
            )

            stored_file = asyncio.run(service.store_telegram_document(bot, document, tenant_id=7))
            stored_path = service.resolve_storage_key(stored_file.storage_key)

            self.assertEqual(" Application/ZIP ; charset=binary ", stored_file.content_type)
            self.assertEqual(b"PK\x03\x04payload", stored_path.read_bytes())
            self.assertEqual(1, bot.get_file_calls)
            self.assertEqual(1, bot.download_file_calls)

    def test_store_cleans_temp_file_when_download_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = FileStorageService(_settings(storage_root=directory))
            bot = _FailingDownloadBot()
            document = _document(
                file_size=11,
                file_name="payload.zip",
                mime_type="application/zip",
            )

            with self.assertRaisesRegex(RuntimeError, "download failed"):
                asyncio.run(service.store_telegram_document(bot, document, tenant_id=7))

            files = [path for path in Path(directory).rglob("*") if path.is_file()]

        self.assertEqual([], files)
        self.assertEqual(1, bot.get_file_calls)
        self.assertEqual(1, bot.download_file_calls)


async def _run_upload_file(message: object, *, product: object) -> None:
    async def get_product_with_default_variant(
        self: object,
        session: object,
        tenant_id: int,
        product_id: int,
    ) -> tuple[object, object | None]:
        assert tenant_id == 7
        assert product_id == 1
        return product, None

    with patch("app.bots.routers.tenant._ensure_permission_message", AsyncMock(return_value=True)):
        with patch(
            "app.bots.routers.tenant.ProductRepository.get_product_with_default_variant",
            get_product_with_default_variant,
        ):
            await upload_file(
                message,
                SimpleNamespace(args="1"),
                bot=SimpleNamespace(),
                settings=_settings(),
                session_factory=_session_factory,
                tenant_context=SimpleNamespace(tenant_id=7, owner_user_id=42),
            )


def _settings(
    *,
    public_base_url: str = "https://example.com",
    storage_root: str = "/tmp/fakabot-tests",
) -> Settings:
    return Settings(
        public_base_url=public_base_url,
        storage_root=storage_root,
        token_encryption_key=SecretStr("download-token-secret"),
    )


def _message(document: object) -> SimpleNamespace:
    return SimpleNamespace(document=document, answer=AsyncMock())


def _document(
    *,
    file_size: int | None,
    file_name: str,
    mime_type: str | None = "application/octet-stream",
) -> SimpleNamespace:
    return SimpleNamespace(
        file_id="telegram-file-id",
        file_size=file_size,
        file_name=file_name,
        mime_type=mime_type,
    )


def _product(*, file_size_limit: int | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        delivery_type="file_download",
        file_size_limit=file_size_limit,
    )


def _session_factory() -> _SessionContext:
    return _SessionContext()


class _SessionContext:
    async def __aenter__(self) -> object:
        return SimpleNamespace()

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class _FakeDownloadBot:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.get_file_calls = 0
        self.download_file_calls = 0

    async def get_file(self, file_id: str) -> SimpleNamespace:
        self.get_file_calls += 1
        return SimpleNamespace(file_path=f"documents/{file_id}")

    async def download_file(self, file_path: str, destination: object) -> None:
        self.download_file_calls += 1
        destination.write_bytes(self._payload)


class _FailingDownloadBot:
    def __init__(self) -> None:
        self.get_file_calls = 0
        self.download_file_calls = 0

    async def get_file(self, file_id: str) -> SimpleNamespace:
        self.get_file_calls += 1
        return SimpleNamespace(file_path=f"documents/{file_id}")

    async def download_file(self, file_path: str, destination: object) -> None:
        self.download_file_calls += 1
        destination.write_bytes(b"partial")
        raise RuntimeError("download failed")


if __name__ == "__main__":
    unittest.main()
