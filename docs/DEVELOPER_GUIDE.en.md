# English Developer Guide

This guide is the English technical entry point for Smart Speech Flow Backend. It covers local setup, the service boundaries, the session API, WebSocket integration, testing, and development operations.

## Repository orientation

| Path | Purpose |
| --- | --- |
| `services/api_gateway/` | FastAPI gateway, session API, WebSockets, and pipeline orchestration |
| `services/asr/` | Speech-to-text service |
| `services/translation/` | M2M100 translation service |
| `services/tts/` | Speech synthesis service |
| `services/frontend/` | React frontend served by the compose stack |
| `tests/` | Unit, integration, load, and API-contract tests |
| `monitoring/` | Prometheus, Grafana, Loki, and provisioning configuration |
| `scripts/` | Quality, dependency, backup, and manual diagnostic scripts |

The API gateway is the integration boundary. The individual ML services communicate over the Docker network; do not couple external clients directly to their development ports.

## Local environment

### Full container stack

```bash
git clone https://github.com/smart-village-solutions/smart-speech-flow.git
cd smart-speech-flow
cp .env.example .env
docker compose up -d traefik redis ollama api_gateway asr translation tts frontend
curl http://localhost:8000/health
```

The compose definition includes an archived frontend with `../ssf-frontend` as its build context. If the sibling repository is unavailable, start the services you need explicitly, for example:

```bash
docker compose up -d traefik redis ollama api_gateway asr translation tts frontend
```

### Local Python development

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -r services/api_gateway/requirements.txt
```

Run a service from its own package or through its configured Compose service. The gateway expects Redis and the model services to be available when its corresponding flows are exercised.

### Configuration

`.env.example` documents the supported environment variables. Keep real values in `.env`, which is ignored by Git. Important groups are:

- `REDIS_URL` and `REDIS_NAMESPACE` for session storage.
- `CLIENT_BASE_URL` and `DEVELOPMENT_CORS_ORIGINS` for client integration.
- `LLM_REFINEMENT_*` for optional Ollama refinement.
- `AUDIO_*` for the storage path, retention, and cleanup process.
- `GLOBAL_RATE_*` and `MESSAGE_RATE_*` for gateway throttling.
- `GRAFANA_ADMIN_*` and `FRONTEND_DEMO_PASSWORD` for local monitoring and demo access.

Pull the optional refinement model after the stack starts:

```bash
docker compose exec ollama ollama pull gpt-oss:20b
```

## Architecture and request flow

The standard conversation flow is session-based:

1. The admin client creates a pending session.
2. The customer opens the session link and activates it with a selected language.
3. Admin and customer connect to the session WebSocket.
4. Either client submits text or audio through the unified message endpoint.
5. The gateway validates the request, persists message state, orchestrates ASR, translation, optional refinement, and TTS as needed, then broadcasts the result.

Redis stores sessions, messages, and timeout metadata. Audio is written to the named `audio-data` volume and is subject to the configured retention period. Prometheus collects metrics; Grafana and Loki provide monitoring and logs.

## REST API essentials

Use the gateway base URL `http://localhost:8000` in local development.

### Create an admin session

```bash
curl -X POST http://localhost:8000/api/admin/session/create \
  -H 'Content-Type: application/json' \
  -d '{"admin_language":"de","customer_language":"en"}'
```

Persist the returned session ID and provide it to the customer flow.

### Activate a customer session

```bash
curl -X POST http://localhost:8000/api/customer/session/activate \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"ABC12345","customer_language":"en"}'
```

Activation is idempotent while the session is active. A missing or expired session returns `404`; a terminated session returns `400`.

### Read session state and available languages

```bash
curl http://localhost:8000/api/customer/session/ABC12345/status
curl http://localhost:8000/api/languages/supported
```

The status response exposes `status`, `is_active`, `can_send_messages`, and connection flags. Frontends should use the language endpoint rather than maintaining a separate language list.

### Submit a message

Use the unified endpoint for both text and audio:

```bash
curl -X POST http://localhost:8000/api/session/ABC12345/message \
  -H 'Content-Type: application/json' \
  -d '{"text":"Hello","source_lang":"en","target_lang":"de","client_type":"admin"}'

curl -X POST http://localhost:8000/api/session/ABC12345/message \
  -F 'file=@sample.wav' \
  -F 'source_lang=en' \
  -F 'target_lang=de' \
  -F 'client_type=admin'
```

Retrieve history with `GET /api/session/{session_id}/messages`. The OpenAPI specification in `docs/openapi.yaml` is the source of truth for endpoint schemas and response fields.

## WebSocket integration

Connect each participant to:

```text
ws://localhost:8000/ws/{session_id}/{client_type}
```

`client_type` is `admin` or `customer`. Use `wss://` behind HTTPS in deployed environments. A connection receives `connection_ack`, periodic `heartbeat` events, `message` broadcasts, `client_joined`, and `session_terminated` events.

Client behavior should be straightforward:

1. Connect after session creation or activation.
2. Keep the connection alive by responding to heartbeat handling in the client implementation.
3. Reconnect with bounded backoff after an unexpected close.
4. Re-fetch history after reconnecting to close any delivery gap.
5. Treat message delivery as asynchronous; use the REST response and broadcast event together rather than assuming a synchronous translation result.

## Pipeline services

The gateway can call three local services:

- ASR: `POST /transcribe` accepts multipart audio and returns recognized text.
- Translation: `POST /translate` accepts text, `source_lang`, and `target_lang`.
- TTS: `POST /synthesize` accepts text and `lang` and returns WAV audio.

Each service exposes `/health` and `/metrics`. Read the English service documents before changing a model, language mapping, or fallback strategy:

- [ASR](../services/asr/README.en.md)
- [Translation](../services/translation/README.en.md)
- [TTS](../services/tts/README.en.md)

## Testing and quality checks

Run focused tests while developing and the project suite before requesting review:

```bash
pytest tests/test_admin_routes.py
pytest tests/integration/
pytest
```

Integration and load tests may require running services or models. CI deliberately runs a hermetic subset:

```bash
pytest tests/ -q \
  -m 'not integration and not real_system' \
  --ignore=tests/integration \
  --ignore=tests/load \
  --ignore=tests/integration_test_audio_validation.py
```

Before opening a pull request:

```bash
pre-commit install
pre-commit run --all-files
./scripts/quality-check.sh
```

See [English code-quality standards](testing/code-quality.en.md) for formatter, linter, security, type-checking, SonarCloud, and Fallow expectations.

## Development operations

Useful commands while working against the development stack:

```bash
docker compose ps
docker compose logs -f api_gateway
docker compose logs -f asr translation tts
curl http://localhost:8000/health
curl http://localhost:8000/metrics
```

Do not use backup, rollback, or production operations scripts as part of ordinary feature development. Use the operations documentation only when assigned an operational task.
