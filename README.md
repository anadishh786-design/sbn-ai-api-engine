# SBN AI API Communication Engine - Stage 1 and Stage 2

Student: Ann

This repository contains Ann's local simulated API and a reusable HTTPX client.
The server has no AI model behind it: it returns fixed answers or a clear
simulated fallback. Stage 2 consumes that API without inventing answers or
embedding HTTP logic in the terminal interface.

Stage 1 base commit: `de1a669 Harden Stage 1 API and request validation`

## Stage 2 setup

Use Python 3.11 or newer. From the repository root:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` if desired. `.env` is not loaded automatically;
set environment variables in PowerShell with:

```powershell
$env:API_BASE_URL="http://127.0.0.1:8000"
$env:API_TIMEOUT_SECONDS="5"
```

The default base URL is exactly `http://127.0.0.1:8000`. The timeout defaults
to 5 seconds and must be a positive number. No credentials are required.

## Start the local server

In one terminal:

```powershell
python simulated_api.py
```

Then, in another terminal:

```powershell
python main.py
```

The terminal supports `health`, `ask`, and `exit`. A question is 1-500
characters after outer whitespace is removed. The answer is display-only data
and is never interpreted as a command.

## Run tests

Run the complete suite:

```powershell
python -m unittest discover -s tests -v
```

The suite retains all ten Stage 1 tests, adds HTTPX MockTransport contract
tests, and starts the real local server on an ephemeral port for integration
tests. Parameterized subtests cover repeated status and malformed-response
cases; each subtest is one independent assertion set.

## Test categories

- Local Stage 1 server tests
- Input and configuration tests
- Request method, URL, JSON body, and sequential request tests
- HTTP 400/413/401/403/404/429/500/503 tests
- Connect and timeout failures
- Invalid JSON and response-schema failures
- Secret/prompt/answer logging safety
- Real local health, known answer, fallback, and 400 integration checks

## Project structure

| File | Responsibility |
|---|---|
| `simulated_api.py` | Approved Stage 1 server |
| `validation.py` | Question validation |
| `config.py` | Environment configuration |
| `api_client.py` | HTTPX transport, status parsing, schema validation |
| `main.py` | Terminal interface |
| `tests/test_simulated_api.py` | Stage 1 regression suite |
| `tests/test_api_client.py` | MockTransport contract suite |
| `tests/test_client_integration.py` | Ephemeral-port local integration suite |
| `docs/stage2_decisions.md` | Architecture and design decisions |
| `docs/stage2_ai_engineering_note.md` | AI interface and safety research |

## Failure handling

The client returns separate success and failure dataclasses. HTTP 200 is not
enough: JSON must have the expected object shape and non-blank answer/source
fields. `POST /ask` has no automatic retry because a timed-out or retried paid
request can complete or duplicate remotely. The only retry metadata is advisory
`Retry-After`; Stage 2 never sleeps for it.

Result metadata includes elapsed monotonic duration and a local request ID.
Logs may include operation, category, duration, and request ID. Questions,
answer text, tokens, credentials, and response bodies are not logged.

## Known limitations

- No live AI provider or authentication is implemented.
- There is no automatic retry for `/ask`.
- HTTPX exception subclasses are distinguished between timeout and network
  errors, but DNS and connection failures share `NETWORK_ERROR`.
- `Retry-After` HTTP-date values are treated as advisory metadata and not
  converted to sleep behavior.

## API endpoints

| Method | Endpoint | Success response |
|---|---|---|
| GET | `/health` | `200 {"status":"ok"}` |
| POST | `/ask` | `200 {"answer":"...","source":"mock"}` |

The `/ask` body must be a JSON object containing a non-empty string named `question`.
Request bodies are limited to 1 MiB (1,048,576 bytes). This is generous for a
short question and its JSON metadata while bounding memory use for concurrent
requests; larger requests are rejected with HTTP 413 before the body is read.

## Run

From this repository root:

```powershell
python simulated_api.py
```

The server listens at `http://127.0.0.1:8000`.

## Stage 1 HTTP interactions

Open a second terminal and run:

```powershell
curl.exe http://127.0.0.1:8000/health

$body = @{ question = "What is Python?" } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri http://127.0.0.1:8000/ask `
  -Method Post -ContentType "application/json" -Body $body

curl.exe -X POST http://127.0.0.1:8000/ask `
  -H "Content-Type: application/json" `
  --data-raw '{not valid json'

curl.exe http://127.0.0.1:8000/unknown
```

PowerShell uses backticks for line continuation. `curl.exe --data-raw '{not valid json'` sends a POST request with raw malformed JSON and is useful for this HTTP laboratory.

## Run tests

From this repository root:

```powershell
python -m unittest discover -s tests -v
```

## Concepts

- **GET** requests information from a server and has no request body in this application.
- **POST** submits a request body. `/ask` uses POST so the question can be sent as JSON.
- **JSON** is a structured text format. `Content-Type: application/json` tells the server how to interpret the body.
- **HTTP status codes** summarize request outcomes. `200` means success, `400` means malformed or invalid input, `404` means an unknown route, and `405` means an unsupported HTTP method.

## Evidence

Typical results are:

```text
GET /health -> HTTP 200
{"status":"ok"}

POST /ask -> HTTP 200
{"answer":"Python is a programming language.","source":"mock"}

POST /ask with malformed JSON -> HTTP 400
{"error":"Malformed JSON"}

GET /unknown -> HTTP 404
{"error":"Unknown endpoint"}
```
