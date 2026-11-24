# Stage 2 AI Engineering Readiness Note

## Provider differences

The Stage 1 protocol is intentionally small: health is
`{"status":"ok"}`, and ask is `{"answer":"...","source":"mock"}`. Commercial
providers commonly use different request objects, response envelopes, output
items, usage metadata, error objects, and authentication conventions. They may
also expose multiple output modalities and finish reasons.

The Stage 2 boundary is therefore the provider adapter. Its only job would be
to translate a provider-specific response into the stable `AnswerSuccess`,
`HealthSuccess`, or `ClientFailure` contract. The CLI and its local input
validation should not need provider response knowledge. Stage 3 would select a
provider adapter without rewriting terminal behavior.

## Structured outputs

Shape validation proves that a value is parseable JSON and has the required
types and non-empty fields. It does not prove factual correctness, relevance,
policy compliance, or absence of hallucination. A schema can conform while
still returning a false or unsafe statement, so domain validation and quality
evaluation remain necessary [R1].

## Rate limits and billing

HTTP 429 means the provider has throttled the request. 503 means the service is
temporarily unavailable. `Retry-After` may advise when the client may try
again, but the header can be missing or be a date rather than seconds.

Blind POST retries are risky for a paid AI API. A timeout may occur after the
provider accepted or completed work, and repeating the operation can create
duplicate cost or side effects. Stage 2 does not retry `/ask`; if provider
support is added later, retries must be bounded and use provider-safe request
semantics.

## Unsafe model output

A successful HTTP response is not authorization to execute returned content.
Model text must be treated as untrusted data, never as a shell command, SQL,
privileged instruction, or path to a code interpreter [R4]. This client only
prints text and never dispatches it to system actions.

## Quality measurement

Useful metrics include success and failure rate, latency, HTTP and transport
categories, malformed-response rate, and schema-validation failure rate.
Aggregate them by operation and status code. Avoid storing complete prompts,
generated answers, API keys, or personal identifiers in default telemetry [R5].
Stable request IDs join related events without exposing content.

## Request evolution

The stable Stage 2 surfaces should remain the question input, health/ask
operations, success/failure result types, and CLI behavior. Changeable provider
details should remain below an adapter: endpoint construction, authentication,
response decoding, finish/usage metadata, error mapping, and retry semantics.
The Responses API or a later provider contract should require a separate
adapter and reviewed tests rather than rewriting `main.py` [R6].

## References

- [R1] OpenAI, Structured model outputs:
  https://developers.openai.com/api/docs/guides/structured-outputs
- [R2] OpenAI, Deployment checklist and rate limits:
  https://developers.openai.com/api/docs/guides/deployment-checklist
- [R3] HTTPX, timeouts and transport injection:
  https://www.python-httpx.org/advanced/timeouts/
- [R3b] HTTPX, transports:
  https://www.python-httpx.org/advanced/transports/
- [R4] OWASP, LLM Prompt Injection Prevention:
  https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html
- [R5] NIST, AI Risk Management Framework:
  https://www.nist.gov/itl/ai-risk-management-framework
- [R6] OpenAI, Responses API migration:
  https://developers.openai.com/api/docs/guides/migrate-to-responses
