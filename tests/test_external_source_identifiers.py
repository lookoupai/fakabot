from __future__ import annotations

import unittest

try:
    from app.services.external_sources.identifiers import normalize_external_identifier, normalize_provider_name
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过外部源标识符测试：{exc.name}") from exc


class ExternalSourceIdentifierTest(unittest.TestCase):
    def test_normalize_external_identifier_trims_valid_values(self) -> None:
        self.assertEqual(
            "provider-a",
            normalize_external_identifier(" provider-a ", "provider_name", allow_empty=False),
        )
        self.assertEqual(
            "shop_a",
            normalize_external_identifier(" shop_a ", "source_key", allow_empty=True),
        )

    def test_normalize_external_identifier_handles_empty_values_by_policy(self) -> None:
        self.assertEqual("", normalize_external_identifier("", "source_key", allow_empty=True))
        self.assertEqual("", normalize_external_identifier(" ", "source_key", allow_empty=True))

        for value in ("", " "):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "不能为空"):
                    normalize_external_identifier(value, "provider_name", allow_empty=False)

    def test_normalize_external_identifier_rejects_non_string_values(self) -> None:
        for value in (None, 123, True, [], {}):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "必须是字符串"):
                    normalize_external_identifier(value, "provider_name", allow_empty=False)

    def test_normalize_external_identifier_rejects_invalid_characters(self) -> None:
        invalid_values = ("ProviderA", "shop a", "bad.name", "acg/shop", "acg:shop", "中文")
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "仅支持小写字母、数字、下划线和短横线"):
                    normalize_external_identifier(value, "provider_name", allow_empty=False)

    def test_normalize_provider_name_uses_required_identifier_policy(self) -> None:
        self.assertEqual("acg", normalize_provider_name(" acg ", "provider"))
        with self.assertRaisesRegex(ValueError, "provider 不能为空"):
            normalize_provider_name(" ", "provider")


if __name__ == "__main__":
    unittest.main()
