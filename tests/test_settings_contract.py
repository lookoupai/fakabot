from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

try:
    from pydantic import ValidationError

    from app.config import Settings
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过配置契约测试：{exc.name}") from exc


class SettingsContractTest(unittest.TestCase):
    def test_env_example_declares_every_settings_field(self) -> None:
        env_example = Path(".env.example").read_text(encoding="utf-8")
        declared_keys = {
            line.split("=", 1)[0].strip()
            for line in env_example.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        expected_keys = {field_name.upper() for field_name in Settings.model_fields}

        self.assertFalse(expected_keys - declared_keys)

    def test_ip_rule_fields_parse_comma_separated_values(self) -> None:
        settings = Settings(
            tenant_admin_ip_allowlist="203.0.113.10, 198.51.100.0/24",
            trusted_proxy_ips="10.0.0.0/24",
            public_store_write_ip_allowlist="192.0.2.0/24",
        )

        self.assertEqual({"203.0.113.10", "198.51.100.0/24"}, settings.tenant_admin_ip_allowlist)
        self.assertEqual({"10.0.0.0/24"}, settings.trusted_proxy_ips)
        self.assertEqual({"192.0.2.0/24"}, settings.public_store_write_ip_allowlist)
        self.assertEqual("fakabot:rate_limit", settings.rate_limit_key_prefix)
        self.assertEqual(60, settings.rate_limit_window_seconds)
        self.assertEqual(120, settings.external_fulfillment_interval_seconds)
        self.assertEqual(30, settings.delivery_dispatch_interval_seconds)
        self.assertEqual(300, settings.delivery_sending_timeout_seconds)
        self.assertEqual(60, settings.order_risk_recent_window_seconds)
        self.assertEqual(5, settings.order_risk_max_buyer_orders_per_window)
        self.assertEqual(86400, settings.order_risk_daily_window_seconds)
        self.assertEqual(Decimal("500"), settings.order_risk_max_buyer_amount_per_day)
        self.assertFalse(settings.order_risk_auto_ban_enabled)
        self.assertEqual(86400, settings.order_risk_auto_ban_window_seconds)
        self.assertEqual(3, settings.order_risk_auto_ban_blocked_count_threshold)
        self.assertFalse(settings.telegram_webapp_require_init_data)
        self.assertEqual(86400, settings.telegram_webapp_init_data_max_age_seconds)
        self.assertEqual(86400, settings.admin_web_session_max_age_seconds)
        self.assertEqual(300, settings.admin_web_binding_code_ttl_seconds)
        self.assertEqual(10, settings.admin_web_binding_code_rate_limit_per_minute)

    def test_admin_web_allowed_origins_parse_and_normalize_values(self) -> None:
        settings = Settings(admin_web_allowed_origins="https://admin.example, https://panel.example/")

        self.assertEqual({"https://admin.example", "https://panel.example"}, settings.admin_web_allowed_origins)

    def test_ip_rule_fields_reject_invalid_values(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(tenant_admin_ip_allowlist="not-an-ip")

    def test_rate_limit_window_seconds_must_be_positive(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(rate_limit_window_seconds=0)

    def test_delivery_sending_timeout_seconds_must_be_positive(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(delivery_sending_timeout_seconds=0)

    def test_order_risk_thresholds_must_be_positive(self) -> None:
        invalid_values = {
            "order_risk_recent_window_seconds": 0,
            "order_risk_max_buyer_orders_per_window": 0,
            "order_risk_daily_window_seconds": 0,
            "order_risk_max_buyer_amount_per_day": Decimal("0"),
            "order_risk_auto_ban_window_seconds": 0,
            "order_risk_auto_ban_blocked_count_threshold": 0,
        }
        for field_name, value in invalid_values.items():
            with self.subTest(field_name=field_name):
                with self.assertRaises(ValidationError):
                    Settings(**{field_name: value})

    def test_telegram_webapp_init_data_max_age_seconds_must_be_positive(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(telegram_webapp_init_data_max_age_seconds=0)

    def test_admin_web_settings_reject_invalid_values(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(admin_web_session_max_age_seconds=0)
        with self.assertRaises(ValidationError):
            Settings(admin_web_binding_code_ttl_seconds=0)
        with self.assertRaises(ValidationError):
            Settings(admin_web_binding_code_rate_limit_per_minute=0)
        with self.assertRaises(ValidationError):
            Settings(admin_web_allowed_origins="https://admin.example/path")
        with self.assertRaises(ValidationError):
            Settings(admin_web_allowed_origins="ftp://admin.example")


if __name__ == "__main__":
    unittest.main()
