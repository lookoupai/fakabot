from __future__ import annotations

from decimal import Decimal
import unittest

try:
    import httpx

    from app.services.external_sources.http import (
        ExternalHttpClient,
        ExternalHttpError,
        ExternalHttpRequest,
        ExternalHttpResponse,
        ExternalHttpxTransport,
        HTTP_ERROR_CATEGORY_CLIENT_ERROR,
        HTTP_ERROR_CATEGORY_CREDENTIAL,
        HTTP_ERROR_CATEGORY_NETWORK_ERROR,
        HTTP_ERROR_CATEGORY_NOT_FOUND,
        HTTP_ERROR_CATEGORY_PROTOCOL_ERROR,
        HTTP_ERROR_CATEGORY_RATE_LIMITED,
        HTTP_ERROR_CATEGORY_REDIRECT,
        HTTP_ERROR_CATEGORY_UPSTREAM_ERROR,
        MAX_EXTERNAL_HTTP_JSON_DEPTH,
        MAX_EXTERNAL_HTTP_RESPONSE_BODY_BYTES,
        build_external_http_url,
        categorize_external_http_status,
        is_external_http_status_retryable,
        is_sensitive_http_header_name,
        normalize_external_http_headers,
        normalize_external_http_timeout,
        normalize_external_http_url,
        redact_external_http_headers,
        redact_external_http_url,
        validate_external_http_public_base_url,
    )
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"缺少项目依赖，跳过外部源 HTTP 契约测试：{exc.name}") from exc


class _FakeTransport:
    def __init__(self, response: object = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.requests: list[ExternalHttpRequest] = []

    async def request(self, request: ExternalHttpRequest) -> object:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.response


class ExternalSourceHttpContractTest(unittest.TestCase):
    def test_safe_url_builder_is_exported_from_external_sources_package(self) -> None:
        from app.services.external_sources import build_external_http_url as exported_builder

        self.assertIs(build_external_http_url, exported_builder)

    def test_request_normalizes_method_url_headers_and_timeout(self) -> None:
        request = ExternalHttpRequest(
            method=" post ",
            url=" HTTPS://api.example.com/order ",
            headers={" Authorization ": " Bearer secret ", "Accept": " application/json "},
            json_payload={"order_id": "ORD123"},
            timeout_seconds=5,
        )

        self.assertEqual("POST", request.method)
        self.assertEqual("https://api.example.com/order", request.url)
        self.assertEqual({"Authorization": "Bearer secret", "Accept": "application/json"}, request.headers)
        self.assertEqual(5.0, request.timeout_seconds)

    def test_request_repr_redacts_headers_url_query_and_body(self) -> None:
        request = ExternalHttpRequest(
            method="GET",
            url="https://api.example.com/orders?token=plain-token&order_id=ORD123",
            headers={"X-API-Key": "plain-api-key", "Trace-Id": "trace-1"},
            body="card-secret-content",
        )
        rendered = repr(request)

        self.assertIn("token=%2A%2A%2A", rendered)
        self.assertIn("'X-API-Key': '***'", rendered)
        self.assertIn("'Trace-Id': 'trace-1'", rendered)
        self.assertIn("body='***'", rendered)
        self.assertNotIn("plain-token", rendered)
        self.assertNotIn("plain-api-key", rendered)
        self.assertNotIn("card-secret-content", rendered)

    def test_response_repr_redacts_headers_and_payload(self) -> None:
        response = ExternalHttpResponse(
            status_code=200,
            headers={"Set-Cookie": "session=secret", "Content-Type": "application/json"},
            json_payload={"token": "provider-token"},
            text="raw body with secret",
        )
        rendered = repr(response)

        self.assertIn("'Set-Cookie': '***'", rendered)
        self.assertIn("'Content-Type': 'application/json'", rendered)
        self.assertIn("json_payload='***'", rendered)
        self.assertIn("text='***'", rendered)
        self.assertNotIn("provider-token", rendered)
        self.assertNotIn("raw body with secret", rendered)

    def test_normalize_external_http_url_rejects_unsafe_urls(self) -> None:
        invalid_urls = [
            "ftp://api.example.com",
            "https://user:pass@api.example.com",
            "https://api.example.com/path#fragment",
            "https://api.example.com/\npath",
            "https://",
            "",
        ]

        for url in invalid_urls:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    normalize_external_http_url(url)

    def test_validate_external_http_public_base_url_rejects_ssrf_targets(self) -> None:
        invalid_urls = [
            "http://127.0.0.1/api",
            "http://[::1]/api",
            "http://10.0.0.1/api",
            "http://172.16.0.1/api",
            "http://192.168.1.1/api",
            "http://169.254.169.254/latest/meta-data",
            "http://0.0.0.0/api",
            "http://localhost/api",
            "http://admin.localhost/api",
            "http://metadata.google.internal/api",
            "http://service.local/api",
            "https://api.example.com/base?token=plain-token",
        ]

        for url in invalid_urls:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    validate_external_http_public_base_url(url)

        self.assertEqual(
            "https://api.example.com/base",
            validate_external_http_public_base_url(" HTTPS://api.example.com/base "),
        )

    def test_normalize_external_http_headers_rejects_invalid_or_duplicate_headers(self) -> None:
        invalid_headers = [
            {"X-Test": ""},
            {"X-Test": "value\nnext"},
            {"X-Test": "ok", "x-test": "duplicate"},
            {"": "value"},
            {1: "value"},
            {"X-Test": 1},
        ]

        for headers in invalid_headers:
            with self.subTest(headers=headers):
                with self.assertRaises(ValueError):
                    normalize_external_http_headers(headers)  # type: ignore[arg-type]

    def test_redact_external_http_headers_masks_sensitive_names_only(self) -> None:
        redacted = redact_external_http_headers(
            {
                "Authorization": "Bearer secret",
                "X-Api-Key": "plain-key",
                "Cookie": "session=secret",
                "Trace-Id": "trace-1",
            }
        )

        self.assertEqual("***", redacted["Authorization"])
        self.assertEqual("***", redacted["X-Api-Key"])
        self.assertEqual("***", redacted["Cookie"])
        self.assertEqual("trace-1", redacted["Trace-Id"])
        self.assertTrue(is_sensitive_http_header_name("X-Provider-Token"))
        self.assertFalse(is_sensitive_http_header_name("Trace-Id"))

    def test_url_query_redaction_keeps_keys_and_masks_values(self) -> None:
        redacted = redact_external_http_url("https://api.example.com/path?api_key=secret&order_id=ORD123")

        self.assertEqual("https://api.example.com/path?api_key=%2A%2A%2A&order_id=%2A%2A%2A", redacted)

    def test_build_external_http_url_joins_path_segments_and_encodes_query(self) -> None:
        url = build_external_http_url(
            " HTTPS://api.example.com/base/ ",
            path_segments=("orders", "ORD 1", 7, Decimal("1.25")),
            query={
                "api_key": "plain secret",
                "include_paid": True,
                "empty": None,
            },
        )

        self.assertEqual(
            "https://api.example.com/base/orders/ORD%201/7/1.25?api_key=plain+secret&include_paid=true",
            url,
        )
        redacted = redact_external_http_url(url)
        self.assertIn("api_key=%2A%2A%2A", redacted)
        self.assertIn("include_paid=%2A%2A%2A", redacted)
        self.assertNotIn("plain secret", redacted)

    def test_build_external_http_url_rejects_ambiguous_base_query(self) -> None:
        with self.assertRaisesRegex(ValueError, "base URL 不能包含 query"):
            build_external_http_url(
                "https://api.example.com/base?token=plain-token",
                path_segments=("orders",),
            )

    def test_build_external_http_url_rejects_unsafe_path_segments(self) -> None:
        invalid_segments = ["", "   ", "../x", "a/b", "a\\b", "..", ".", "line\nbreak", True]

        for segment in invalid_segments:
            with self.subTest(segment=segment):
                with self.assertRaises(ValueError):
                    build_external_http_url(
                        "https://api.example.com/base",
                        path_segments=("orders", segment),
                    )

        with self.assertRaisesRegex(ValueError, "path_segments"):
            build_external_http_url(
                "https://api.example.com/base",
                path_segments="orders",  # type: ignore[arg-type]
            )

    def test_build_external_http_url_rejects_invalid_or_duplicate_query_keys(self) -> None:
        invalid_queries = [
            {"": "value"},
            {" token ": "a", "token": "b"},
            {"line\nbreak": "value"},
            {1: "value"},
        ]

        for query in invalid_queries:
            with self.subTest(query=query):
                with self.assertRaises(ValueError):
                    build_external_http_url("https://api.example.com/base", query=query)  # type: ignore[arg-type]

    def test_build_external_http_url_rejects_invalid_query_values(self) -> None:
        invalid_queries = [
            {"token": "line\nbreak"},
            {"price": Decimal("NaN")},
            {"items": ["a", "b"]},
        ]

        for query in invalid_queries:
            with self.subTest(query=query):
                with self.assertRaises(ValueError):
                    build_external_http_url("https://api.example.com/base", query=query)  # type: ignore[arg-type]

    def test_timeout_and_payload_contracts_are_strict(self) -> None:
        for timeout in (0, -1, 61, float("inf"), True):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    normalize_external_http_timeout(timeout)  # type: ignore[arg-type]

        with self.assertRaisesRegex(ValueError, "不能同时提供"):
            ExternalHttpRequest(
                method="POST",
                url="https://api.example.com/orders",
                json_payload={"id": "1"},
                body="payload",
            )

    def test_client_uses_fake_transport_and_returns_json_payload(self) -> None:
        transport = _FakeTransport(ExternalHttpResponse(status_code=200, json_payload={"ok": True}))
        client = ExternalHttpClient(transport)  # type: ignore[arg-type]
        request = ExternalHttpRequest(
            method="post",
            url="https://api.example.com/orders?token=plain-token",
            headers={"Authorization": "Bearer plain-secret"},
            json_payload={"id": "ORD123"},
        )

        payload = self.async_run(client.request_json(request))

        self.assertEqual({"ok": True}, payload)
        self.assertEqual(1, len(transport.requests))
        self.assertEqual("POST", transport.requests[0].method)
        self.assertNotIn("plain-token", repr(transport.requests[0]))
        self.assertNotIn("plain-secret", repr(transport.requests[0]))

    def test_client_rejects_non_success_status_without_sensitive_text(self) -> None:
        transport = _FakeTransport(
            ExternalHttpResponse(
                status_code=500,
                headers={"Authorization": "Bearer plain-secret"},
                text="upstream body token=plain-token",
            )
        )
        client = ExternalHttpClient(transport)  # type: ignore[arg-type]

        with self.assertRaises(ExternalHttpError) as caught:
            self.async_run(
                client.request(
                    ExternalHttpRequest(
                        method="GET",
                        url="https://api.example.com/orders?token=plain-token",
                        headers={"X-API-Key": "plain-api-key"},
                    )
                )
            )

        message = str(caught.exception)
        self.assertEqual("外部发卡源 HTTP 状态异常：500", message)
        self.assertEqual(500, caught.exception.status_code)
        self.assertEqual(HTTP_ERROR_CATEGORY_UPSTREAM_ERROR, caught.exception.category)
        self.assertTrue(caught.exception.retryable)
        self.assertNotIn("plain-token", message)
        self.assertNotIn("plain-api-key", message)
        self.assertNotIn("plain-secret", message)

    def test_client_wraps_transport_errors_without_leaking_details(self) -> None:
        transport = _FakeTransport(error=RuntimeError("timeout token=plain-token secret=plain-secret"))
        client = ExternalHttpClient(transport)  # type: ignore[arg-type]

        with self.assertRaises(ExternalHttpError) as caught:
            self.async_run(
                client.request(
                    ExternalHttpRequest(
                        method="GET",
                        url="https://api.example.com/orders?api_key=plain-key",
                        headers={"Cookie": "session=secret"},
                    )
                )
            )

        message = str(caught.exception)
        self.assertEqual("外部发卡源 HTTP 请求失败", message)
        self.assertIsNone(caught.exception.status_code)
        self.assertEqual(HTTP_ERROR_CATEGORY_NETWORK_ERROR, caught.exception.category)
        self.assertTrue(caught.exception.retryable)
        self.assertIsNotNone(caught.exception.__cause__)
        self.assertNotIn("plain-token", message)
        self.assertNotIn("plain-secret", message)
        self.assertNotIn("plain-key", message)
        self.assertNotIn("session=secret", message)

    def test_client_rejects_invalid_response_and_missing_json_payload(self) -> None:
        invalid_client = ExternalHttpClient(_FakeTransport(response={"status_code": 200}))  # type: ignore[arg-type]
        with self.assertRaisesRegex(ExternalHttpError, "响应无效") as invalid_caught:
            self.async_run(invalid_client.request(ExternalHttpRequest(method="GET", url="https://api.example.com")))
        self.assertIsNone(invalid_caught.exception.status_code)
        self.assertEqual(HTTP_ERROR_CATEGORY_PROTOCOL_ERROR, invalid_caught.exception.category)
        self.assertFalse(invalid_caught.exception.retryable)

        text_client = ExternalHttpClient(_FakeTransport(response=ExternalHttpResponse(status_code=200, text="ok")))  # type: ignore[arg-type]
        with self.assertRaisesRegex(ExternalHttpError, "不是 JSON") as json_caught:
            self.async_run(text_client.request_json(ExternalHttpRequest(method="GET", url="https://api.example.com")))
        self.assertEqual(200, json_caught.exception.status_code)
        self.assertEqual(HTTP_ERROR_CATEGORY_PROTOCOL_ERROR, json_caught.exception.category)
        self.assertFalse(json_caught.exception.retryable)

    def test_client_rejects_oversized_response_body_without_details(self) -> None:
        client = ExternalHttpClient(
            _FakeTransport(
                response=ExternalHttpResponse(
                    status_code=200,
                    text="x" * (MAX_EXTERNAL_HTTP_RESPONSE_BODY_BYTES + 1),
                )
            )
        )

        with self.assertRaisesRegex(ExternalHttpError, "响应体过大") as caught:
            self.async_run(client.request(ExternalHttpRequest(method="GET", url="https://api.example.com")))

        self.assertEqual(200, caught.exception.status_code)
        self.assertEqual(HTTP_ERROR_CATEGORY_PROTOCOL_ERROR, caught.exception.category)
        self.assertFalse(caught.exception.retryable)
        self.assertNotIn("xxx", str(caught.exception))

    def test_client_rejects_scalar_json_top_level_as_protocol_error(self) -> None:
        client = ExternalHttpClient(
            _FakeTransport(response=ExternalHttpResponse(status_code=200, json_payload="ok"))
        )

        with self.assertRaisesRegex(ExternalHttpError, "JSON 顶层") as caught:
            self.async_run(client.request_json(ExternalHttpRequest(method="GET", url="https://api.example.com")))

        self.assertEqual(200, caught.exception.status_code)
        self.assertEqual(HTTP_ERROR_CATEGORY_PROTOCOL_ERROR, caught.exception.category)
        self.assertFalse(caught.exception.retryable)

    def test_client_rejects_overly_complex_json_payload(self) -> None:
        payload: object = {"leaf": "ok"}
        for _ in range(MAX_EXTERNAL_HTTP_JSON_DEPTH + 1):
            payload = {"nested": payload}
        client = ExternalHttpClient(_FakeTransport(response=ExternalHttpResponse(status_code=200, json_payload=payload)))

        with self.assertRaisesRegex(ExternalHttpError, "嵌套过深") as caught:
            self.async_run(client.request_json(ExternalHttpRequest(method="GET", url="https://api.example.com")))

        self.assertEqual(200, caught.exception.status_code)
        self.assertEqual(HTTP_ERROR_CATEGORY_PROTOCOL_ERROR, caught.exception.category)
        self.assertFalse(caught.exception.retryable)

    def test_client_rejects_non_http_request_before_transport(self) -> None:
        transport = _FakeTransport(ExternalHttpResponse(status_code=200, json_payload={"ok": True}))
        client = ExternalHttpClient(transport)  # type: ignore[arg-type]

        with self.assertRaisesRegex(ValueError, "ExternalHttpRequest"):
            self.async_run(client.request(object()))  # type: ignore[arg-type]
        self.assertEqual([], transport.requests)

    def test_httpx_transport_sends_request_and_parses_json_without_leaking_response(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            captured["authorization"] = request.headers.get("Authorization")
            captured["content"] = request.content
            return httpx.Response(
                200,
                headers={"Set-Cookie": "session=provider-secret"},
                json={"ok": True, "order_id": "ORD123"},
            )

        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as async_client:
                transport = ExternalHttpxTransport(async_client)
                response = await transport.request(
                    ExternalHttpRequest(
                        method="post",
                        url="https://api.example.com/orders",
                        headers={"Authorization": "Bearer provider-secret"},
                        json_payload={"order_id": "ORD123"},
                    )
                )
                return response

        response = self.async_run(run())

        self.assertEqual("POST", captured["method"])
        self.assertEqual("https://api.example.com/orders", captured["url"])
        self.assertEqual("Bearer provider-secret", captured["authorization"])
        self.assertIn(b"ORD123", captured["content"])
        self.assertEqual({"ok": True, "order_id": "ORD123"}, response.json_payload)
        rendered = repr(response)
        self.assertIn("'set-cookie': '***'", rendered)
        self.assertNotIn("provider-secret", rendered)

    def test_httpx_transport_keeps_non_json_response_as_text(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="plain upstream body")

        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as async_client:
                transport = ExternalHttpxTransport(async_client)
                return await transport.request(
                    ExternalHttpRequest(method="GET", url="https://api.example.com/status")
                )

        response = self.async_run(run())

        self.assertIsNone(response.json_payload)
        self.assertEqual("plain upstream body", response.text)

    def test_httpx_transport_rejects_oversized_response_before_json_parse(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"x" * (MAX_EXTERNAL_HTTP_RESPONSE_BODY_BYTES + 1))

        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as async_client:
                client = ExternalHttpClient(ExternalHttpxTransport(async_client))
                await client.request(ExternalHttpRequest(method="GET", url="https://api.example.com/catalog"))

        with self.assertRaisesRegex(ExternalHttpError, "响应体过大") as caught:
            self.async_run(run())

        self.assertEqual(200, caught.exception.status_code)
        self.assertEqual(HTTP_ERROR_CATEGORY_PROTOCOL_ERROR, caught.exception.category)
        self.assertFalse(caught.exception.retryable)

    def test_httpx_transport_does_not_follow_redirects_or_expose_location_secret(self) -> None:
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(
                302,
                headers={"Location": "https://api.example.com/redirect?token=plain-token"},
            )

        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as async_client:
                client = ExternalHttpClient(ExternalHttpxTransport(async_client))
                await client.request(ExternalHttpRequest(method="GET", url="https://api.example.com/orders"))

        with self.assertRaises(ExternalHttpError) as caught:
            self.async_run(run())

        self.assertEqual(1, call_count)
        message = str(caught.exception)
        self.assertEqual("外部发卡源 HTTP 状态异常：302", message)
        self.assertEqual(302, caught.exception.status_code)
        self.assertEqual(HTTP_ERROR_CATEGORY_REDIRECT, caught.exception.category)
        self.assertFalse(caught.exception.retryable)
        self.assertNotIn("plain-token", message)

    def test_httpx_transport_errors_are_wrapped_by_client_without_details(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connect failed token=plain-token secret=plain-secret")

        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as async_client:
                client = ExternalHttpClient(ExternalHttpxTransport(async_client))
                await client.request(
                    ExternalHttpRequest(
                        method="GET",
                        url="https://api.example.com/orders?api_key=plain-key",
                    )
                )

        with self.assertRaises(ExternalHttpError) as caught:
            self.async_run(run())

        message = str(caught.exception)
        self.assertEqual("外部发卡源 HTTP 请求失败", message)
        self.assertIsNone(caught.exception.status_code)
        self.assertEqual(HTTP_ERROR_CATEGORY_NETWORK_ERROR, caught.exception.category)
        self.assertTrue(caught.exception.retryable)
        self.assertNotIn("plain-token", message)
        self.assertNotIn("plain-secret", message)
        self.assertNotIn("plain-key", message)

    def test_http_status_helpers_classify_provider_failures(self) -> None:
        cases = [
            (302, HTTP_ERROR_CATEGORY_REDIRECT, False),
            (401, HTTP_ERROR_CATEGORY_CREDENTIAL, False),
            (403, HTTP_ERROR_CATEGORY_CREDENTIAL, False),
            (404, HTTP_ERROR_CATEGORY_NOT_FOUND, False),
            (408, HTTP_ERROR_CATEGORY_CLIENT_ERROR, True),
            (429, HTTP_ERROR_CATEGORY_RATE_LIMITED, True),
            (500, HTTP_ERROR_CATEGORY_UPSTREAM_ERROR, True),
            (503, HTTP_ERROR_CATEGORY_UPSTREAM_ERROR, True),
        ]

        for status_code, category, retryable in cases:
            with self.subTest(status_code=status_code):
                self.assertEqual(category, categorize_external_http_status(status_code))
                self.assertEqual(retryable, is_external_http_status_retryable(status_code))

    def async_run(self, awaitable):
        import asyncio

        return asyncio.run(awaitable)


if __name__ == "__main__":
    unittest.main()
