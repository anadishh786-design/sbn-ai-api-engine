import json
import time
import uuid
from dataclasses import dataclass
from typing import Optional, Union

import httpx

from config import (
    ConfigurationError,
    DEFAULT_API_BASE_URL,
    DEFAULT_API_TIMEOUT_SECONDS,
    validate_base_url,
    validate_timeout,
)
from validation import ValidationError, validate_question


@dataclass(frozen=True)
class HealthSuccess:
    status: str
    request_id: str
    elapsed_ms: float


@dataclass(frozen=True)
class AnswerSuccess:
    answer: str
    source: str
    request_id: str
    elapsed_ms: float


@dataclass(frozen=True)
class ClientFailure:
    category: str
    message: str
    request_id: str
    elapsed_ms: float
    http_status: Optional[int] = None
    retryable: bool = False
    retry_after_seconds: Optional[float] = None


HealthResult = Union[HealthSuccess, ClientFailure]
AnswerResult = Union[AnswerSuccess, ClientFailure]


class APIClient:
    def __init__(
        self,
        base_url=DEFAULT_API_BASE_URL,
        timeout_seconds=DEFAULT_API_TIMEOUT_SECONDS,
        transport=None,
        client=None,
        logger=None,
    ):
        if client is not None and transport is not None:
            raise ConfigurationError("Do not inject both an HTTPX client and a transport.")

        self._client_was_injected = client is not None
        self._owns_client = not self._client_was_injected

        try:
            self.base_url = validate_base_url(base_url)
            self.timeout_seconds = validate_timeout(timeout_seconds)
        except ConfigurationError:
            self.base_url = None
            self.timeout_seconds = None

        if client is not None:
            self._http = client
        elif base_url is not None and timeout_seconds is not None:
            http_timeout = httpx.Timeout(self.timeout_seconds)
            if transport is not None:
                self._http = httpx.Client(
                    timeout=http_timeout,
                    transport=transport,
                )
            else:
                self._http = httpx.Client(timeout=http_timeout)
        else:
            self._http = None

        self._logger = logger

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        if self._owns_client and self._http is not None:
            self._http.close()
            self._http = None

    def _request_id(self):
        return uuid.uuid4().hex

    def _elapsed_ms(self, start):
        return round((time.monotonic() - start) * 1000.0, 3)

    def _failure(
        self,
        operation,
        request_id,
        start,
        category,
        message,
        http_status=None,
        retryable=False,
        retry_after_seconds=None,
    ):
        elapsed_ms = self._elapsed_ms(start)
        failure = ClientFailure(
            category=category,
            message=message,
            request_id=request_id,
            elapsed_ms=elapsed_ms,
            http_status=http_status,
            retryable=retryable,
            retry_after_seconds=retry_after_seconds,
        )
        if self._logger is not None:
            self._logger.info(
                "operation=%s status=%s request_id=%s duration_ms=%.3f",
                operation,
                category,
                request_id,
                elapsed_ms,
            )
        return failure

    def _validate_configuration(self, operation, request_id, start):
        if self.base_url is None or self.timeout_seconds is None:
            return self._failure(
                operation,
                request_id,
                start,
                "CONFIGURATION_ERROR",
                "The API configuration is invalid. Check API_BASE_URL and API_TIMEOUT_SECONDS.",
            )
        return None

    def _parse_retry_after(self, response):
        value = response.headers.get("Retry-After")
        if value is None:
            return None
        try:
            seconds = float(value.strip())
            if seconds < 0:
                return None
            return seconds
        except (TypeError, ValueError):
            return None

    def _failure_for_status(self, operation, request_id, start, response):
        status = response.status_code
        retry_after = self._parse_retry_after(response)

        if status in (400, 413):
            return self._failure(
                operation,
                request_id,
                start,
                "HTTP_CLIENT_ERROR",
                "The API rejected the request.",
                http_status=status,
            )
        if status in (401, 403):
            return self._failure(
                operation,
                request_id,
                start,
                "AUTH_ERROR",
                "The API rejected authentication or authorization.",
                http_status=status,
            )
        if status == 404:
            return self._failure(
                operation,
                request_id,
                start,
                "HTTP_CLIENT_ERROR",
                "The API endpoint was not found.",
                http_status=status,
            )
        if status == 429:
            return self._failure(
                operation,
                request_id,
                start,
                "RATE_LIMIT",
                "The API rate limit was reached.",
                http_status=status,
                retryable=True,
                retry_after_seconds=retry_after,
            )
        if status == 503:
            return self._failure(
                operation,
                request_id,
                start,
                "SERVICE_UNAVAILABLE",
                "The API is temporarily unavailable.",
                http_status=status,
                retryable=True,
                retry_after_seconds=retry_after,
            )
        if status >= 500:
            return self._failure(
                operation,
                request_id,
                start,
                "SERVER_ERROR",
                "The API returned an unexpected server error.",
                http_status=status,
                retryable=True,
            )
        if 400 <= status < 500:
            return self._failure(
                operation,
                request_id,
                start,
                "HTTP_CLIENT_ERROR",
                "The API rejected the request.",
                http_status=status,
            )
        return self._failure(
            operation,
            request_id,
            start,
            "HTTP_CLIENT_ERROR",
            "The API returned an unexpected HTTP status.",
            http_status=status,
        )

    def _classify_transport_error(self, operation, request_id, start, error):
        if isinstance(error, httpx.TimeoutException):
            return self._failure(
                operation,
                request_id,
                start,
                "TIMEOUT",
                "The API did not respond before the configured timeout.",
                retryable=operation == "health",
            )
        return self._failure(
            operation,
            request_id,
            start,
            "NETWORK_ERROR",
            "Could not connect to the API.",
        )

    def health(self):
        operation = "health"
        request_id = self._request_id()
        start = time.monotonic()

        config_failure = self._validate_configuration(operation, request_id, start)
        if config_failure is not None:
            return config_failure

        try:
            response = self._http.get(self.base_url + "/health")
        except httpx.TimeoutException as error:
            return self._classify_transport_error(
                operation,
                request_id,
                start,
                error,
            )
        except httpx.TransportError as error:
            return self._classify_transport_error(
                operation,
                request_id,
                start,
                error,
            )

        if response.status_code != 200:
            return self._failure_for_status(
                operation,
                request_id,
                start,
                response,
            )

        try:
            payload = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._failure(
                operation,
                request_id,
                start,
                "RESPONSE_FORMAT_ERROR",
                "The API returned invalid JSON.",
                http_status=200,
            )

        if not isinstance(payload, dict):
            return self._failure(
                operation,
                request_id,
                start,
                "RESPONSE_SCHEMA_ERROR",
                "The API health response has an invalid shape.",
                http_status=200,
            )
        status = payload.get("status")
        if not isinstance(status, str) or not status.strip():
            return self._failure(
                operation,
                request_id,
                start,
                "RESPONSE_SCHEMA_ERROR",
                "The API health response is missing a valid status.",
                http_status=200,
            )
        if status.strip() != "ok":
            return self._failure(
                operation,
                request_id,
                start,
                "RESPONSE_SCHEMA_ERROR",
                "The API reported an unhealthy status.",
                http_status=200,
            )

        elapsed_ms = self._elapsed_ms(start)
        result = HealthSuccess(
            status="ok",
            request_id=request_id,
            elapsed_ms=elapsed_ms,
        )
        if self._logger is not None:
            self._logger.info(
                "operation=health status=success request_id=%s duration_ms=%.3f",
                request_id,
                elapsed_ms,
            )
        return result

    def ask(self, question):
        operation = "ask"
        request_id = self._request_id()
        start = time.monotonic()

        try:
            trimmed_question = validate_question(question)
        except ValidationError as error:
            return self._failure(
                operation,
                request_id,
                start,
                "VALIDATION_ERROR",
                str(error),
            )

        config_failure = self._validate_configuration(operation, request_id, start)
        if config_failure is not None:
            return config_failure

        try:
            response = self._http.post(
                self.base_url + "/ask",
                json={"question": trimmed_question},
            )
        except httpx.TimeoutException as error:
            return self._classify_transport_error(
                operation,
                request_id,
                start,
                error,
            )
        except httpx.TransportError as error:
            return self._classify_transport_error(
                operation,
                request_id,
                start,
                error,
            )

        if response.status_code != 200:
            return self._failure_for_status(
                operation,
                request_id,
                start,
                response,
            )

        try:
            payload = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._failure(
                operation,
                request_id,
                start,
                "RESPONSE_FORMAT_ERROR",
                "The API returned invalid JSON.",
                http_status=200,
            )

        if not isinstance(payload, dict):
            return self._failure(
                operation,
                request_id,
                start,
                "RESPONSE_SCHEMA_ERROR",
                "The API answer response has an invalid shape.",
                http_status=200,
            )

        answer = payload.get("answer")
        source = payload.get("source")
        if not isinstance(answer, str) or not answer.strip():
            return self._failure(
                operation,
                request_id,
                start,
                "RESPONSE_SCHEMA_ERROR",
                "The API returned an empty or invalid answer.",
                http_status=200,
            )
        if not isinstance(source, str) or not source.strip():
            return self._failure(
                operation,
                request_id,
                start,
                "RESPONSE_SCHEMA_ERROR",
                "The API returned an invalid source.",
                http_status=200,
            )

        elapsed_ms = self._elapsed_ms(start)
        result = AnswerSuccess(
            answer=answer.strip(),
            source=source.strip(),
            request_id=request_id,
            elapsed_ms=elapsed_ms,
        )
        if self._logger is not None:
            self._logger.info(
                "operation=ask status=success request_id=%s duration_ms=%.3f",
                request_id,
                elapsed_ms,
            )
        return result
