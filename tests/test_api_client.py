import logging
import sys
import unittest
from pathlib import Path

import httpx

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from api_client import AnswerSuccess, APIClient, HealthSuccess
from config import ConfigurationError, load_config
from validation import ValidationError, validate_question


def mock_client(handler):
    transport = httpx.MockTransport(handler)
    return APIClient(
        base_url="http://127.0.0.1:8000",
        timeout_seconds=1,
        transport=transport,
    )


class TestInputAndConfiguration(unittest.TestCase):
    def test_empty_question_is_invalid(self):
        with self.assertRaises(ValidationError):
            validate_question("")

    def test_whitespace_question_is_invalid(self):
        with self.assertRaises(ValidationError):
            validate_question("   ")

    def test_non_string_question_is_invalid(self):
        for value in (None, 42, [], {}):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    validate_question(value)

    def test_500_character_boundary_is_valid(self):
        self.assertEqual(validate_question("x" * 500), "x" * 500)

    def test_501_characters_is_invalid(self):
        with self.assertRaises(ValidationError):
            validate_question("x" * 501)

    def test_invalid_timeout_values_are_rejected(self):
        for value in ("", "zero", "0", "-1"):
            with self.subTest(value=value):
                with self.assertRaises(ConfigurationError):
                    load_config(
                        {
                            "API_BASE_URL": "http://127.0.0.1:8000",
                            "API_TIMEOUT_SECONDS": value,
                        }
                    )

    def test_missing_and_invalid_base_urls_are_rejected(self):
        invalid_values = ("", "localhost:8000", "ftp://example.com", "http://")
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ConfigurationError):
                    load_config(
                        {
                            "API_BASE_URL": value,
                            "API_TIMEOUT_SECONDS": "5",
                        }
                    )


class TestRequestsAndSuccess(unittest.TestCase):
    def test_health_request_method_and_url_are_correct(self):
        def handler(request):
            self.assertEqual(request.method, "GET")
            self.assertEqual(str(request.url), "http://127.0.0.1:8000/health")
            return httpx.Response(200, json={"status": "ok"})

        with mock_client(handler) as client:
            result = client.health()
        self.assertIsInstance(result, HealthSuccess)

    def test_answer_request_method_url_and_body_are_correct(self):
        def handler(request):
            self.assertEqual(request.method, "POST")
            self.assertEqual(str(request.url), "http://127.0.0.1:8000/ask")
            import json
            self.assertEqual(json.loads(request.content), {"question": "What is Python?"})
            return httpx.Response(
                200,
                json={"answer": "A programming language.", "source": "mock"},
            )

        with mock_client(handler) as client:
            result = client.ask("  What is Python?  ")
        self.assertIsInstance(result, AnswerSuccess)
        self.assertEqual(result.answer, "A programming language.")

    def test_invalid_input_makes_no_request(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={"answer": "bad", "source": "mock"})

        with mock_client(handler) as client:
            result = client.ask("   ")
        self.assertEqual(result.category, "VALIDATION_ERROR")
        self.assertEqual(calls, [])

    def test_valid_health_contract(self):
        with mock_client(
            lambda request: httpx.Response(200, json={"status": "ok"})
        ) as client:
            result = client.health()
        self.assertIsInstance(result, HealthSuccess)
        self.assertEqual(result.status, "ok")
        self.assertTrue(result.request_id)

    def test_valid_answer_and_source_contract(self):
        with mock_client(
            lambda request: httpx.Response(
                200,
                json={"answer": "Fixed answer", "source": "mock", "extra": True},
            )
        ) as client:
            result = client.ask("What is Python?")
        self.assertIsInstance(result, AnswerSuccess)
        self.assertEqual(result.source, "mock")

    def test_multiple_sequential_requests(self):
        def handler(request):
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ok"})
            return httpx.Response(
                200,
                json={"answer": "Fixed answer", "source": "mock"},
            )

        with mock_client(handler) as client:
            health = client.health()
            first = client.ask("What is Python?")
            second = client.ask("What is JSON?")
        self.assertIsInstance(health, HealthSuccess)
        self.assertIsInstance(first, AnswerSuccess)
        self.assertIsInstance(second, AnswerSuccess)


class TestHTTPAndNetworkFailures(unittest.TestCase):
    def test_http_error_statuses_are_classified(self):
        cases = [
            (400, "HTTP_CLIENT_ERROR"),
            (413, "HTTP_CLIENT_ERROR"),
            (401, "AUTH_ERROR"),
            (403, "AUTH_ERROR"),
            (404, "HTTP_CLIENT_ERROR"),
            (500, "SERVER_ERROR"),
        ]
        for status, category in cases:
            with self.subTest(status=status):
                with mock_client(
                    lambda request, status=status: httpx.Response(
                        status,
                        json={"error": "safe server message"},
                    )
                ) as client:
                    result = client.ask("Question")
                self.assertEqual(result.category, category)
                self.assertEqual(result.http_status, status)
                self.assertIsNone(getattr(result, "answer", None))

    def test_rate_limit_exposes_retry_after_without_sleeping(self):
        with mock_client(
            lambda request: httpx.Response(
                429,
                json={"error": "slow down"},
                headers={"Retry-After": "17"},
            )
        ) as client:
            result = client.ask("Question")
        self.assertEqual(result.category, "RATE_LIMIT")
        self.assertTrue(result.retryable)
        self.assertEqual(result.retry_after_seconds, 17.0)

    def test_service_unavailable_is_retryable_metadata(self):
        with mock_client(
            lambda request: httpx.Response(
                503,
                json={"error": "try later"},
                headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"},
            )
        ) as client:
            result = client.ask("Question")
        self.assertEqual(result.category, "SERVICE_UNAVAILABLE")
        self.assertTrue(result.retryable)
        self.assertIsNone(result.retry_after_seconds)

    def test_connect_failure_is_network_error(self):
        def handler(request):
            raise httpx.ConnectError("DNS failure")

        with mock_client(handler) as client:
            result = client.ask("Question")
        self.assertEqual(result.category, "NETWORK_ERROR")
        self.assertFalse(result.retryable)

    def test_request_timeout_is_timeout_error(self):
        def handler(request):
            raise httpx.ReadTimeout("read timed out")

        with mock_client(handler) as client:
            result = client.ask("Question")
        self.assertEqual(result.category, "TIMEOUT")
        self.assertFalse(result.retryable)

    def test_health_timeout_may_be_considered_retryable(self):
        def handler(request):
            raise httpx.ConnectTimeout("connect timed out")

        with mock_client(handler) as client:
            result = client.health()
        self.assertEqual(result.category, "TIMEOUT")
        self.assertTrue(result.retryable)


class TestMalformedResponses(unittest.TestCase):
    def test_invalid_json_is_format_error(self):
        with mock_client(
            lambda request: httpx.Response(
                200,
                content=b"<html>bad gateway</html>",
                headers={"Content-Type": "text/html"},
            )
        ) as client:
            result = client.ask("Question")
        self.assertEqual(result.category, "RESPONSE_FORMAT_ERROR")

    def test_json_array_is_schema_error(self):
        with mock_client(
            lambda request: httpx.Response(200, json=[{"answer": "wrong"}])
        ) as client:
            result = client.ask("Question")
        self.assertEqual(result.category, "RESPONSE_SCHEMA_ERROR")

    def test_missing_answer_is_schema_error(self):
        with mock_client(
            lambda request: httpx.Response(200, json={"source": "mock"})
        ) as client:
            result = client.ask("Question")
        self.assertEqual(result.category, "RESPONSE_SCHEMA_ERROR")

    def test_null_answer_is_schema_error(self):
        with mock_client(
            lambda request: httpx.Response(
                200,
                json={"answer": None, "source": "mock"},
            )
        ) as client:
            result = client.ask("Question")
        self.assertEqual(result.category, "RESPONSE_SCHEMA_ERROR")

    def test_whitespace_answer_is_schema_error(self):
        with mock_client(
            lambda request: httpx.Response(
                200,
                json={"answer": "   ", "source": "mock"},
            )
        ) as client:
            result = client.ask("Question")
        self.assertEqual(result.category, "RESPONSE_SCHEMA_ERROR")

    def test_missing_or_blank_source_is_schema_error(self):
        for payload in (
            {"answer": "A valid answer"},
            {"answer": "A valid answer", "source": " "},
        ):
            with self.subTest(payload=payload):
                with mock_client(
                    lambda request, payload=payload: httpx.Response(
                        200,
                        json=payload,
                    )
                ) as client:
                    result = client.ask("Question")
                self.assertEqual(result.category, "RESPONSE_SCHEMA_ERROR")

    def test_malformed_health_response_is_schema_error(self):
        with mock_client(
            lambda request: httpx.Response(200, json={"status": "down"})
        ) as client:
            result = client.health()
        self.assertEqual(result.category, "RESPONSE_SCHEMA_ERROR")


class TestSafetyAndMetadata(unittest.TestCase):
    def test_error_never_contains_secret_or_answer(self):
        secret = "sk-test-never-log"

        with mock_client(
            lambda request: httpx.Response(
                401,
                json={"error": "denied", "message": secret},
            )
        ) as client:
            result = client.ask("private question")
        self.assertNotIn(secret, result.message)
        self.assertNotIn("answer", result.__dict__)

    def test_logs_exclude_question_and_answer(self):
        records = []

        class RecordingHandler(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        logger = logging.getLogger("stage2-test-" + str(id(self)))
        logger.handlers = [RecordingHandler()]
        logger.setLevel(logging.INFO)

        def handler(request):
            return httpx.Response(
                200,
                json={"answer": "PRIVATE GENERATED ANSWER", "source": "mock"},
            )

        with mock_client(handler) as client:
            client._logger = logger
            result = client.ask("PRIVATE PROMPT")
        output = "\n".join(records)
        self.assertIn("request_id=", output)
        self.assertIn("duration_ms=", output)
        self.assertNotIn("PRIVATE PROMPT", output)
        self.assertNotIn("PRIVATE GENERATED ANSWER", output)
        self.assertIsInstance(result, AnswerSuccess)

    def test_request_id_and_elapsed_duration_are_present(self):
        with mock_client(
            lambda request: httpx.Response(
                200,
                json={"answer": "answer", "source": "mock"},
            )
        ) as client:
            result = client.ask("Question")
        self.assertTrue(result.request_id)
        self.assertIsInstance(result.elapsed_ms, float)


if __name__ == "__main__":
    unittest.main()
