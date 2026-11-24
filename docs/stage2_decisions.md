# Stage 2 Decisions

## Baseline

- Student: Ann
- Stage 1 base commit: `de1a669 Harden Stage 1 API and request validation`
- Stage 2 branch: `module-01-stage-02-api-client`
- Stage 1 source and tests are preserved.

## Architecture

```text
User / CLI
  |
  | health() or ask(question)
  v
Input validator
  | rejects invalid questions before HTTP
  v
APIClient
  | HTTPX session, timeout, request ID, elapsed time
  v
Stage 1 at 127.0.0.1:8000
  |
  v
Status classifier + JSON parser + response-schema validator
  |
  v
HealthSuccess / AnswerSuccess / ClientFailure
```

The CLI owns presentation only. `validation.py` owns question rules.
`config.py` owns environment configuration. `api_client.py` owns HTTP
transport, status classification, JSON parsing, and response validation.

## Proposed result contract

Success:

- `HealthSuccess(status, request_id, elapsed_ms)`
- `AnswerSuccess(answer, source, request_id, elapsed_ms)`

Failure:

- `ClientFailure(category, message, request_id, elapsed_ms, http_status=None,
  retryable=False, retry_after_seconds=None)`

Questions must be strings containing 1-500 characters after outer whitespace
is removed. Answers and sources must be non-blank strings. Extra response
fields are ignored because they do not invalidate the minimum contract.

The CLI checks whether the result is `HealthSuccess` or `AnswerSuccess`;
otherwise it prints a short `ClientFailure` message. This keeps success and
failure structurally distinct and prevents malformed or unavailable responses
from appearing as answers.

## Independent decisions

### HTTPX or basic requests

HTTPX is used because it provides a reusable client, configuration timeout,
and injectable transport. A supplied HTTPX client is externally owned. A
transport supplied alone creates an internally owned client. A client created
by `APIClient` is closed by `close()` or the context manager.

### Valid answer

A usable answer is a non-empty, non-blank string. The source must also be a
non-empty, non-blank string. The response must be a JSON object. HTTP 200 alone
is not enough. Extra fields are ignored.

### Failure model

Success and failure are separate dataclasses. Categories distinguish local
validation, configuration, network, timeout, HTTP, authentication, rate-limit,
server, JSON-format, and JSON-schema failures. HTTP status and retry metadata
remain separate from the answer.

### Safe logging

Logs contain operation, category, elapsed duration, and request ID. Complete
questions, generated answer text, credentials, environment values, and response
bodies are excluded. Request IDs allow troubleshooting without exposing user or
model content.

## Failure categories and retry policy

| Status or trigger | Category | Automatic POST `/ask` retry |
|---|---|---|
| Invalid question | `VALIDATION_ERROR` | No |
| Invalid configuration | `CONFIGURATION_ERROR` | No |
| Connection/DNS failure | `NETWORK_ERROR` | No |
| Read/connect/write timeout | `TIMEOUT` | No |
| 400 or 413 | `HTTP_CLIENT_ERROR` | No |
| 401 or 403 | `AUTH_ERROR` | No |
| 404 | `HTTP_CLIENT_ERROR` | No |
| 429 | `RATE_LIMIT` | No |
| 500 | `SERVER_ERROR` | No |
| 503 | `SERVICE_UNAVAILABLE` | No |
| 200 invalid JSON/HTML | `RESPONSE_FORMAT_ERROR` | No |
| 200 invalid shape | `RESPONSE_SCHEMA_ERROR` | No |

POST `/ask` is never retried automatically because an AI request may cost money
or may have completed remotely when a timeout occurs. Retry-After is advisory
metadata only. A future provider could add a controlled health retry, but only
as a GET and at most once.

## One unresolved question

Can `Retry-After` for a future provider use a date more often than seconds?
This implementation records unparseable date values and omits a sleep, leaving
date parsing for a separately reviewed provider adapter.
