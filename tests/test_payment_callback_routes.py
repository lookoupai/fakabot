from __future__ import annotations

import logging
from types import SimpleNamespace
import unittest
import warnings
from unittest.mock import AsyncMock, patch

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)
logging.getLogger("httpx").setLevel(logging.WARNING)

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.services.payments import PaymentUnavailableError
    from app.services.payments.epay_compatible import EPAY_COMPATIBLE_PROVIDER, LEMZF_PROVIDER
    from app.services.payments.token188 import TOKEN188_PROVIDER
    from app.web.payments import (
        MAX_PAYMENT_CALLBACK_BODY_BYTES,
        MAX_PAYMENT_CALLBACK_FIELD_COUNT,
        MAX_PAYMENT_CALLBACK_KEY_LENGTH,
        MAX_PAYMENT_CALLBACK_QUERY_BYTES,
        MAX_PAYMENT_CALLBACK_VALUE_LENGTH,
        create_payment_router,
    )
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过支付回调路由测试：{exc.name}") from exc


OFFLINE_CALLBACK_TEST_PATHS = (
    "/payments/callback/token188",
    "/payments/callback/epay_compatible",
    "/payments/callback/lemzf",
)


class _FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    async def commit(self) -> None:
        self.commit_count += 1


def _session_factory(session: _FakeSession):
    def factory() -> _FakeSession:
        return session

    return factory


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(create_payment_router(Settings(public_base_url="https://store.example")))
    return TestClient(app)


class PaymentCallbackRouteTest(unittest.TestCase):
    def test_trc20_direct_instruction_page_renders_payment_details_without_secrets(self) -> None:
        client = _client()

        response = client.get(
            "/payments/trc20-direct/ORD123"
            "?address=T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb"
            "&amount=10.25"
            "&asset=USDT"
            "&network=TRC20"
            "&token=plain-secret"
        )

        self.assertEqual(200, response.status_code)
        self.assertIn("TRC20-USDT 付款说明", response.text)
        self.assertIn("ORD123", response.text)
        self.assertIn("10.25 USDT", response.text)
        self.assertIn("T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb", response.text)
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("token", response.text.lower())

    def test_trc20_direct_instruction_page_rejects_invalid_address_without_secret_leak(self) -> None:
        client = _client()

        response = client.get(
            "/payments/trc20-direct/ORD123?address=invalid&amount=10&asset=USDT&network=TRC20&secret=plain"
        )

        self.assertEqual(400, response.status_code)
        self.assertEqual("TRC20 直付参数无效", response.json()["detail"])
        self.assertNotIn("plain", response.text)
        self.assertNotIn("invalid", response.text)

    def _assert_payload_gate_rejects_before_payment_service(
        self,
        *,
        method: str,
        path: str,
        provider_name: str,
        expected_status: int,
        expected_detail: str,
        forbidden_texts: tuple[str, ...] = (),
        **request_kwargs: object,
    ) -> None:
        session = _FakeSession()
        record_rejection = AsyncMock()
        client = _client()

        with patch("app.web.payments.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.payments.PaymentCallbackRejectionAuditService") as audit_service:
                audit_service.return_value.record_rejection = record_rejection
                with patch("app.web.payments.PaymentService") as service:
                    response = getattr(client, method)(path, **request_kwargs)

        self.assertEqual(expected_status, response.status_code)
        self.assertEqual(expected_detail, response.json()["detail"])
        for text in forbidden_texts:
            self.assertNotIn(text, response.text)
        service.assert_not_called()
        record_rejection.assert_awaited_once_with(
            session,
            provider_name=provider_name,
            payload=None,
            reason_category="payload_malformed",
            http_status=expected_status,
        )

    def test_offline_provider_callback_routes_delegate_to_generic_service_without_network(self) -> None:
        for provider_name, payload in [
            (TOKEN188_PROVIDER, {"orderNo": "ORD123"}),
            (EPAY_COMPATIBLE_PROVIDER, {"out_trade_no": "ORD123"}),
            (LEMZF_PROVIDER, {"out_trade_no": "ORD123"}),
        ]:
            with self.subTest(provider=provider_name):
                session = _FakeSession()
                process_callback = AsyncMock(return_value=SimpleNamespace(delivery_record_id=None))
                client = _client()

                with patch("app.web.payments.get_session_factory", return_value=_session_factory(session)):
                    with patch("app.web.payments.PaymentService") as service:
                        service.return_value.process_payment_callback = process_callback
                        response = client.post(f"/payments/callback/{provider_name}", json=payload)

                self.assertEqual(200, response.status_code)
                self.assertEqual("ok", response.text)
                self.assertEqual(1, session.commit_count)
                process_callback.assert_awaited_once_with(session, provider_name, payload)

    def test_callback_route_reads_form_urlencoded_payload(self) -> None:
        session = _FakeSession()
        process_callback = AsyncMock(return_value=SimpleNamespace(delivery_record_id=None))
        client = _client()

        with patch("app.web.payments.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.payments.PaymentService") as service:
                service.return_value.process_payment_callback = process_callback
                response = client.post(
                    f"/payments/callback/{EPAY_COMPATIBLE_PROVIDER}",
                    content="out_trade_no=ORD123&trade_status=TRADE_SUCCESS",
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )

        self.assertEqual(200, response.status_code)
        process_callback.assert_awaited_once_with(
            session,
            EPAY_COMPATIBLE_PROVIDER,
            {"out_trade_no": "ORD123", "trade_status": "TRADE_SUCCESS"},
        )

    def test_callback_route_reads_get_query_payload(self) -> None:
        session = _FakeSession()
        process_callback = AsyncMock(return_value=SimpleNamespace(delivery_record_id=None))
        client = _client()

        with patch("app.web.payments.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.payments.PaymentService") as service:
                service.return_value.process_payment_callback = process_callback
                response = client.get(f"/payments/callback/{LEMZF_PROVIDER}?out_trade_no=ORD123&trade_status=SUCCESS")

        self.assertEqual(200, response.status_code)
        process_callback.assert_awaited_once_with(
            session,
            LEMZF_PROVIDER,
            {"out_trade_no": "ORD123", "trade_status": "SUCCESS"},
        )

    def test_callback_route_accepts_nested_json_payload_without_rewriting_fields(self) -> None:
        session = _FakeSession()
        process_callback = AsyncMock(return_value=SimpleNamespace(delivery_record_id=None))
        client = _client()
        payload = {
            "orderNo": "ORD123",
            "headers": {"Authorization": "Bearer plain-secret", "Trace-ID": "TRACE-1"},
            "events": [{"X-Request-ID": "REQ-1", "status": "paid"}],
        }

        with patch("app.web.payments.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.payments.PaymentService") as service:
                service.return_value.process_payment_callback = process_callback
                response = client.post(f"/payments/callback/{TOKEN188_PROVIDER}", json=payload)

        self.assertEqual(200, response.status_code)
        process_callback.assert_awaited_once_with(session, TOKEN188_PROVIDER, payload)

    def test_callback_route_error_response_does_not_echo_provider_secret(self) -> None:
        session = _FakeSession()
        process_callback = AsyncMock(side_effect=ValueError("key=plain-secret"))
        client = _client()

        with patch("app.web.payments.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.payments.PaymentService") as service:
                service.return_value.process_payment_callback = process_callback
                response = client.post(
                    f"/payments/callback/{TOKEN188_PROVIDER}",
                    json={"orderNo": "ORD123", "key": "plain-secret"},
                )

        self.assertEqual(400, response.status_code)
        self.assertEqual("支付回调参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("key=", response.text)

    def test_callback_route_records_invalid_callback_rejection_without_echoing_secret(self) -> None:
        session = _FakeSession()
        process_callback = AsyncMock(side_effect=ValueError("sign=plain-secret"))
        record_rejection = AsyncMock()
        client = _client()

        with patch("app.web.payments.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.payments.PaymentCallbackRejectionAuditService") as audit_service:
                audit_service.return_value.record_rejection = record_rejection
                with patch("app.web.payments.PaymentService") as service:
                    service.return_value.process_payment_callback = process_callback
                    response = client.post(
                        f"/payments/callback/{TOKEN188_PROVIDER}",
                        json={"orderNo": "ORD123", "key": "plain-secret", "sign": "secret-signature"},
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("支付回调参数无效", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("secret-signature", response.text)
        record_rejection.assert_awaited_once_with(
            session,
            provider_name=TOKEN188_PROVIDER,
            payload={"orderNo": "ORD123", "key": "plain-secret", "sign": "secret-signature"},
            reason_category="invalid_callback",
            http_status=400,
        )

    def test_callback_route_payment_unavailable_response_is_generic_and_records_rejection(self) -> None:
        session = _FakeSession()
        process_callback = AsyncMock(side_effect=PaymentUnavailableError("secret_key=plain-secret"))
        record_rejection = AsyncMock()
        client = _client()

        with patch("app.web.payments.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.payments.PaymentCallbackRejectionAuditService") as audit_service:
                audit_service.return_value.record_rejection = record_rejection
                with patch("app.web.payments.PaymentService") as service:
                    service.return_value.process_payment_callback = process_callback
                    response = client.post(
                        f"/payments/callback/{TOKEN188_PROVIDER}",
                        json={"orderNo": "ORD123", "secret_key": "plain-secret"},
                    )

        self.assertEqual(503, response.status_code)
        self.assertEqual("支付配置暂不可用", response.json()["detail"])
        self.assertNotIn("plain-secret", response.text)
        self.assertNotIn("secret_key", response.text)
        record_rejection.assert_awaited_once_with(
            session,
            provider_name=TOKEN188_PROVIDER,
            payload={"orderNo": "ORD123", "secret_key": "plain-secret"},
            reason_category="payment_unavailable",
            http_status=503,
        )

    def test_callback_route_records_malformed_payload_rejection_before_payment_service(self) -> None:
        session = _FakeSession()
        record_rejection = AsyncMock()
        client = _client()

        with patch("app.web.payments.get_session_factory", return_value=_session_factory(session)):
            with patch("app.web.payments.PaymentCallbackRejectionAuditService") as audit_service:
                audit_service.return_value.record_rejection = record_rejection
                with patch("app.web.payments.PaymentService") as service:
                    response = client.post(
                        f"/payments/callback/{LEMZF_PROVIDER}",
                        content="[1,2,3]",
                        headers={"Content-Type": "application/json"},
                    )

        self.assertEqual(400, response.status_code)
        self.assertEqual("回调 JSON 必须是对象", response.json()["detail"])
        service.assert_not_called()
        record_rejection.assert_awaited_once_with(
            session,
            provider_name=LEMZF_PROVIDER,
            payload=None,
            reason_category="payload_malformed",
            http_status=400,
        )

    def test_callback_route_rejects_body_over_size_limit_before_payment_service(self) -> None:
        self._assert_payload_gate_rejects_before_payment_service(
            method="post",
            path=f"/payments/callback/{TOKEN188_PROVIDER}",
            provider_name=TOKEN188_PROVIDER,
            expected_status=413,
            expected_detail="支付回调 payload 过大",
            content="x" * (MAX_PAYMENT_CALLBACK_BODY_BYTES + 1),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    def test_callback_route_rejects_query_over_size_limit_before_payment_service(self) -> None:
        self._assert_payload_gate_rejects_before_payment_service(
            method="get",
            path=f"/payments/callback/{LEMZF_PROVIDER}?note={'x' * (MAX_PAYMENT_CALLBACK_QUERY_BYTES + 1)}",
            provider_name=LEMZF_PROVIDER,
            expected_status=413,
            expected_detail="支付回调 payload 过大",
        )

    def test_callback_route_rejects_too_many_json_fields_before_payment_service(self) -> None:
        payload = {f"field_{index}": "ok" for index in range(MAX_PAYMENT_CALLBACK_FIELD_COUNT + 1)}

        self._assert_payload_gate_rejects_before_payment_service(
            method="post",
            path=f"/payments/callback/{EPAY_COMPATIBLE_PROVIDER}",
            provider_name=EPAY_COMPATIBLE_PROVIDER,
            expected_status=400,
            expected_detail="回调 payload 字段过多",
            json=payload,
        )

    def test_callback_route_rejects_oversized_key_or_value_before_payment_service(self) -> None:
        cases = [
            ({"k" * (MAX_PAYMENT_CALLBACK_KEY_LENGTH + 1): "ok"}, "回调 payload 字段无效", ()),
            (
                {"orderNo": "ORD123", "note": "plain-secret" + "x" * MAX_PAYMENT_CALLBACK_VALUE_LENGTH},
                "回调 payload 字段值过长",
                ("plain-secret",),
            ),
        ]
        for payload, expected_detail, forbidden_texts in cases:
            with self.subTest(detail=expected_detail):
                self._assert_payload_gate_rejects_before_payment_service(
                    method="post",
                    path=f"/payments/callback/{TOKEN188_PROVIDER}",
                    provider_name=TOKEN188_PROVIDER,
                    expected_status=400,
                    expected_detail=expected_detail,
                    forbidden_texts=forbidden_texts,
                    json=payload,
                )

    def test_callback_route_rejects_duplicate_json_keys_before_payment_service(self) -> None:
        self._assert_payload_gate_rejects_before_payment_service(
            method="post",
            path=f"/payments/callback/{TOKEN188_PROVIDER}",
            provider_name=TOKEN188_PROVIDER,
            expected_status=400,
            expected_detail="回调 payload 包含重复字段",
            content='{"orderNo":"ORD123","orderNo":"ORD456","sign":"secret-signature"}',
            headers={"Content-Type": "application/json"},
            forbidden_texts=("ORD456", "secret-signature"),
        )

    def test_callback_route_rejects_duplicate_form_fields_before_payment_service(self) -> None:
        self._assert_payload_gate_rejects_before_payment_service(
            method="post",
            path=f"/payments/callback/{EPAY_COMPATIBLE_PROVIDER}",
            provider_name=EPAY_COMPATIBLE_PROVIDER,
            expected_status=400,
            expected_detail="回调 payload 包含重复字段",
            content="out_trade_no=ORD123&out_trade_no=ORD456&key=plain-secret",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            forbidden_texts=("ORD456", "plain-secret"),
        )

    def test_callback_route_rejects_duplicate_query_fields_before_payment_service(self) -> None:
        self._assert_payload_gate_rejects_before_payment_service(
            method="get",
            path=f"/payments/callback/{LEMZF_PROVIDER}?out_trade_no=ORD123&out_trade_no=ORD456&key=plain-secret",
            provider_name=LEMZF_PROVIDER,
            expected_status=400,
            expected_detail="回调 payload 包含重复字段",
            forbidden_texts=("ORD456", "plain-secret"),
        )

    def test_callback_route_payload_gate_errors_are_generic_and_audited_without_payload(self) -> None:
        self._assert_payload_gate_rejects_before_payment_service(
            method="post",
            path=f"/payments/callback/{TOKEN188_PROVIDER}",
            provider_name=TOKEN188_PROVIDER,
            expected_status=400,
            expected_detail="回调 payload 字段值无效",
            json={"orderNo": "ORD123", "note": "plain-secret\nsignature=secret-signature"},
            forbidden_texts=("plain-secret", "secret-signature"),
        )


if __name__ == "__main__":
    unittest.main()
