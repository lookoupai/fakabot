from __future__ import annotations

import hashlib
import hmac
import json
import unittest
from urllib.parse import urlencode

try:
    from app.services.telegram_webapp import (
        MAX_INIT_DATA_FIELDS,
        MAX_INIT_DATA_FIELD_VALUE_LENGTH,
        TelegramWebAppInitDataError,
        validate_telegram_webapp_init_data,
    )
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过 Telegram WebApp 测试：{exc.name}") from exc


class TelegramWebAppInitDataTest(unittest.TestCase):
    def test_valid_init_data_returns_verified_user(self) -> None:
        init_data = _signed_init_data(
            "123456:ABC",
            {
                "auth_date": "1770000000",
                "query_id": "AAEAAAE",
                "user": json.dumps({"id": 42, "username": "buyer", "first_name": "Buyer"}, separators=(",", ":")),
            },
        )

        user = validate_telegram_webapp_init_data(
            init_data,
            "123456:ABC",
            max_age_seconds=300,
            now=1770000100,
        )

        self.assertEqual(42, user.id)
        self.assertEqual("buyer", user.username)

    def test_rejects_tampered_hash_and_expired_auth_date(self) -> None:
        init_data = _signed_init_data(
            "123456:ABC",
            {
                "auth_date": "1770000000",
                "user": json.dumps({"id": 42}, separators=(",", ":")),
            },
        )

        with self.assertRaises(TelegramWebAppInitDataError):
            validate_telegram_webapp_init_data(
                init_data.replace("id%22%3A42", "id%22%3A43"),
                "123456:ABC",
                max_age_seconds=300,
                now=1770000100,
            )
        with self.assertRaises(TelegramWebAppInitDataError):
            validate_telegram_webapp_init_data(
                init_data,
                "123456:ABC",
                max_age_seconds=300,
                now=1770001000,
            )

    def test_rejects_missing_user(self) -> None:
        init_data = _signed_init_data("123456:ABC", {"auth_date": "1770000000"})

        with self.assertRaises(TelegramWebAppInitDataError):
            validate_telegram_webapp_init_data(
                init_data,
                "123456:ABC",
                max_age_seconds=300,
                now=1770000000,
            )

    def test_rejects_future_auth_date_beyond_small_clock_skew(self) -> None:
        init_data = _signed_init_data(
            "123456:ABC",
            {
                "auth_date": "1770000061",
                "user": json.dumps({"id": 42}, separators=(",", ":")),
            },
        )

        with self.assertRaisesRegex(TelegramWebAppInitDataError, "来自未来"):
            validate_telegram_webapp_init_data(
                init_data,
                "123456:ABC",
                max_age_seconds=300,
                now=1770000000,
            )

    def test_rejects_oversized_or_too_many_init_data_fields(self) -> None:
        too_many_fields = {f"k{i}": "v" for i in range(MAX_INIT_DATA_FIELDS)}
        too_many_fields.update(
            {
                "auth_date": "1770000000",
                "user": json.dumps({"id": 42}, separators=(",", ":")),
            }
        )
        too_many_init_data = _signed_init_data("123456:ABC", too_many_fields)
        oversized_value = _signed_init_data(
            "123456:ABC",
            {
                "auth_date": "1770000000",
                "query_id": "q" * (MAX_INIT_DATA_FIELD_VALUE_LENGTH + 1),
                "user": json.dumps({"id": 42}, separators=(",", ":")),
            },
        )

        with self.assertRaisesRegex(TelegramWebAppInitDataError, "字段过多"):
            validate_telegram_webapp_init_data(
                too_many_init_data,
                "123456:ABC",
                max_age_seconds=300,
                now=1770000000,
            )
        with self.assertRaisesRegex(TelegramWebAppInitDataError, "字段值超限"):
            validate_telegram_webapp_init_data(
                oversized_value,
                "123456:ABC",
                max_age_seconds=300,
                now=1770000000,
            )

    def test_rejects_invalid_user_json_shapes_and_optional_field_types(self) -> None:
        invalid_cases = [
            ([], "user 无效"),
            ({"id": True}, "user.id 无效"),
            ({"id": 42, "username": 123}, "user.username 无效"),
            ({"id": 42, "first_name": ["Buyer"]}, "user.first_name 无效"),
            ({"id": 42, "language_code": {"code": "zh"}}, "user.language_code 无效"),
        ]

        for user_payload, message in invalid_cases:
            with self.subTest(message=message):
                init_data = _signed_init_data(
                    "123456:ABC",
                    {
                        "auth_date": "1770000000",
                        "user": json.dumps(user_payload, separators=(",", ":")),
                    },
                )

                with self.assertRaisesRegex(TelegramWebAppInitDataError, message):
                    validate_telegram_webapp_init_data(
                        init_data,
                        "123456:ABC",
                        max_age_seconds=300,
                        now=1770000000,
                    )


def _signed_init_data(bot_token: str, data: dict[str, str]) -> str:
    data_check_string = "\n".join(f"{key}={data[key]}" for key in sorted(data))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({**data, "hash": signature})


if __name__ == "__main__":
    unittest.main()
