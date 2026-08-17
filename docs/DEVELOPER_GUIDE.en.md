# Developer Guide and Guidelines

This guide is the English technical entry point for Smart Speech Flow Backend. It covers local setup, the service boundaries, the session API, WebSocket integration, testing, and development operations.

## Start Here

This guide assumes familiarity with Python services, Docker Compose, and API-based systems. Use Python 3.12 for local development. The model-service containers are configured to request NVIDIA GPU access, so a compatible Docker and GPU setup is needed when running the full stack.

1. Create `.env` from `.env.example`, start the required containers, and verify the gateway with `/health`.
2. Read [Repository Orientation](#3-repository-orientation) before changing a service or an integration boundary.
3. For backend changes, continue with [Working Practices](#4-working-practices), [Code Standards](#5-code-standards), and [Testing](#6-testing).
4. For REST, WebSocket, or client work, read [API, WebSocket, and Data Conventions](#7-api-websocket-and-data-conventions).
5. For configuration, production-facing behaviour, or incident-related work, read [Configuration and Secrets](#8-configuration-and-secrets) and [Observability and Operations](#10-observability-and-operations).
6. Before requesting review, complete the [Definition of Done](#13-definition-of-done).

## 1. Purpose and Scope

These guidelines define the shared expectations for developing and maintaining Smart Speech Flow. They help contributors make changes that support the product's purpose: reliable, privacy-conscious, multilingual real-time communication in operational settings.

They apply to all repository changes, including application code, service integrations, APIs, tests, infrastructure, configuration, and documentation. They complement—not replace—the detailed guidance in `CONTRIBUTING.md`, the architecture documentation, API conventions, testing guides, operational runbooks, and architecture decision records.

Use these guidelines as the default decision framework. When a change affects an established interface, security or privacy, operational behaviour, or documented architectural decisions, follow the more specific documentation and update it where necessary.

## 2. Quick Start

### Full Container Stack

```bash
git clone https://github.com/smart-village-solutions/smart-speech-flow.git
cd smart-speech-flow
cp .env.example .env
docker compose up -d traefik redis ollama api_gateway asr translation tts frontend
curl http://localhost:8000/health
```

The Compose definition also contains the optional `frontend-archive` service, which uses `../ssf-frontend` as its build context. It is not part of the command above; the maintained `frontend` service is built from `services/frontend`.

### Local Python Development

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -r services/api_gateway/requirements.txt
```

Run a service from its own package or through its configured Compose service. The gateway expects Redis and the model services to be available when its corresponding flows are exercised.

## 3. Repository Orientation

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

### Architecture and Request Flow

The standard conversation flow is session-based:

1. The admin client creates a pending session.
2. The customer opens the session link and activates it with a selected language.
3. Admin and customer connect to the session WebSocket.
4. Either client submits text or audio through the unified message endpoint.
5. The gateway validates the request, persists message state, orchestrates ASR, translation, optional refinement, and TTS as needed, then broadcasts the result.

When Redis is available, it persists sessions, messages, and timeout metadata; the gateway falls back to in-memory session storage if Redis cannot be reached. Audio is written to the named `audio-data` volume and is subject to the current 24-hour retention policy. Prometheus collects metrics; Grafana and Loki provide monitoring and logs.

### Pipeline Services

The gateway can call three local services:

- ASR: `POST /transcribe` accepts multipart audio and returns recognized text.
- Translation: `POST /translate` accepts text, `source_lang`, and `target_lang`.
- TTS: `POST /synthesize` accepts text and `lang` and returns WAV audio.

Each service exposes `/health` and `/metrics`. Read the English service documents before changing a model, language mapping, or fallback strategy:

- [ASR](../services/asr/README.en.md)
- [Translation](../services/translation/README.en.md)
- [TTS](../services/tts/README.en.md)

## 4. Working Practices

Keep changes focused, reviewable, and traceable. A change should address one clear outcome and avoid unrelated refactoring.

- Create a dedicated branch from the current main branch for each change.
- Read the relevant architecture, API, testing, and operations documentation before changing an established interface or workflow.
- Discuss and document significant changes—new capabilities, breaking API changes, architectural decisions, or security-sensitive behaviour—before implementation. Record durable architectural decisions as ADRs.
- Keep commits small and use Conventional Commit prefixes such as `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `perf:`, and `chore:`.
- Prepare pull requests with a clear description, the reason for the change, relevant test evidence, and any required documentation or operational follow-up.
- Address review feedback with the same care as the original change. Do not merge changes with unresolved questions about correctness, security, privacy, or operational impact.

See [`CONTRIBUTING.md`](../CONTRIBUTING.md) for the contribution and pull-request workflow. Code-quality and test requirements are specified in the following chapters.

## 5. Code Standards

Write code that is clear, focused, and maintainable. Follow the conventions of the component you change and keep public interfaces explicit and documented.

- Format, lint, and analyse changed code with the project's configured tools.
- Add type annotations to new or modified Python code where the project's type checking applies.
- Keep functions and modules focused; avoid unrelated refactoring and duplicated logic.
- Validate all external input at service and API boundaries, and use structured logging and error handling that preserve useful operational context.
- Update API contracts, configuration documentation, and tests when a code change affects them.
- Apply the frontend quality checks when changing `services/frontend`.

Before opening a pull request:

```bash
pre-commit install
pre-commit run --all-files
./scripts/quality-check.sh
```

See [English code-quality standards](testing/code-quality.en.md) for the authoritative formatter, linter, security, type-checking, SonarCloud, and Fallow requirements.

## 6. Testing

Tests are required for every behaviour change. Choose the smallest test scope that provides confidence while covering the affected contract and relevant failure paths.

- Add or update unit tests for isolated business logic, validation, and error handling.
- Add integration tests when a change crosses service, storage, API, or WebSocket boundaries.
- Add a regression test for every bug fix when the previous failure can be reproduced automatically.
- Update API-contract tests and OpenAPI documentation when request or response behaviour changes.
- Use fixtures and mocks to keep tests deterministic. Never use production credentials, personal data, or customer audio as test data.
- Run load or real-system tests for changes that can affect latency, throughput, resource use, or real-time conversation behaviour.
- Record the relevant local or CI test results in the pull request. Clearly identify checks that were not run and why.

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

See the [Testing Guide](testing/TESTING_GUIDE.md) for test categories, fixtures, manual checks, and troubleshooting.

## 7. API, WebSocket, and Data Conventions

### Contract and Compatibility

The [OpenAPI specification](openapi.yaml) is the source of truth for REST schemas, response fields, and status codes. Keep it aligned with the running implementation and update contract tests whenever an API contract changes.

Preserve established endpoints, field names, event types, and response semantics unless a change has been discussed, documented, and communicated to affected consumers. Use `customer` for the end user and reserve `client` for technical HTTP or WebSocket clients. Consult the [API conventions](guides/api-conventions.md) before introducing new terminology or public fields.

### REST API Essentials

Use the gateway base URL `http://localhost:8000` in local development.

#### Create an Admin Session

```bash
curl -X POST http://localhost:8000/api/admin/session/create \
  -H 'Accept: application/json'
```

Persist the returned session ID and provide it to the customer flow.

#### Activate a Customer Session

```bash
curl -X POST http://localhost:8000/api/customer/session/activate \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"ABC12345","customer_language":"en"}'
```

Activation is idempotent while the session is active. A missing or expired session returns `404`; a terminated session returns `400`.

#### Read Session State and Available Languages

```bash
curl http://localhost:8000/api/customer/session/ABC12345/status
curl http://localhost:8000/api/languages/supported
```

The status response exposes `status`, `is_active`, `can_send_messages`, and connection flags. Frontends should use the language endpoint rather than maintaining a separate language list.

#### Submit a Message

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

Retrieve history with `GET /api/session/{session_id}/messages`.

### WebSocket Integration

Connect each participant to:

```text
ws://localhost:8000/ws/{session_id}/{client_type}
```

`client_type` is `admin` or `customer`. Use `wss://` behind HTTPS in deployed environments. A connection receives `connection_ack`, periodic `heartbeat_ping` events, `message` broadcasts, `client_joined`, and `session_terminated` events.

Client behavior should be straightforward:

1. Connect after session creation or activation.
2. Keep the connection alive by responding to each `heartbeat_ping` with a `heartbeat_pong` message.
3. Reconnect with bounded backoff after an unexpected close.
4. Re-fetch history after reconnecting to close any delivery gap.
5. Treat message delivery as asynchronous; use the REST response and broadcast event together rather than assuming a synchronous translation result.

### Data Conventions

- Use the supported-language endpoint rather than maintaining a separate language list.
- Keep session, message, and connection identifiers opaque; consumers must not infer meaning from their format.
- Use ISO 639-1 language codes and ISO 8601 timestamps where these fields are exposed.
- Treat message text, audio, and session metadata as sensitive operational data. Do not add fields or logs that expose more data than the interaction requires.
- Document externally observable message fields and WebSocket events in the OpenAPI specification or the appropriate integration guide.

See the [frontend integration guide](guides/frontend-integration.md) for client behaviour and integration examples.

## 8. Configuration and Secrets

Use `.env.example` as the documented reference for Compose configuration. Keep environment-specific values in `.env` or another ignored `.env.*` file; never commit real credentials, tokens, private endpoints, or other secrets.

- Keep secrets out of source code, documentation examples, test fixtures, logs, commits, and AI prompts.
- Use the least-privileged credentials and rotate them promptly if they are exposed or suspected to be exposed.
- Change placeholder and default passwords before any non-development deployment.
- When adding or changing an environment variable, document its purpose, expected format, safe default, and affected service in `.env.example` and the relevant operational documentation.
- Keep development-only settings, such as `DEVELOPMENT_CORS_ORIGINS`, scoped to the development environment. Do not copy permissive local settings into deployed environments.
- Review the resolved Compose configuration after changing environment variables:

  ```bash
  docker compose config
  ```

Variable groups currently interpolated by Compose include:

- `LLM_REFINEMENT_*` for optional Ollama refinement.
- `GLOBAL_RATE_*` and `MESSAGE_RATE_*` for gateway throttling.
- `ENVIRONMENT` and `DEVELOPMENT_CORS_ORIGINS` for environment-specific CORS behaviour.
- `GRAFANA_ADMIN_*` and `FRONTEND_DEMO_PASSWORD` for local monitoring and demo access.

In the current Compose stack, `REDIS_URL`, `REDIS_NAMESPACE`, and `CLIENT_BASE_URL` are assigned in `docker-compose.yml` rather than interpolated from `.env`. The `AUDIO_*` variables are likewise documented and passed by Compose, but the gateway currently reads only `SSF_AUDIO_BASE_DIR`; it uses a fixed 24-hour retention period and an hourly cleanup interval. Do not rely on `.env` changes to the `AUDIO_*` variables to change runtime audio-storage behaviour. The following values document those fixed settings:

- `REDIS_URL` and `REDIS_NAMESPACE` for session storage.
- `CLIENT_BASE_URL` for generated customer links.

Pull the optional refinement model after the stack starts:

```bash
docker compose exec ollama ollama pull gpt-oss:20b
```

See the [deployment security guide](deployment/SECURITY.md) for production credential, network-isolation, and monitoring-security requirements.

## 9. Security and Privacy

Treat security and privacy as functional requirements, not as a later review step. Assess the effect on access control, data exposure, retention, logging, and operational monitoring whenever a change handles session, message, audio, identity, or configuration data.

- Validate untrusted input at every HTTP, WebSocket, and service boundary. Reject invalid, oversized, or unauthorised requests without exposing internal implementation details.
- Enforce authentication, authorisation, and scope checks on the server. User-interface restrictions are not a security boundary.
- Apply least privilege and tenant isolation to every new data access path. Do not trust a tenant, role, or ownership identifier supplied by a client without server-side verification.
- Collect, retain, and expose only the data required for the documented purpose. Do not put message content, raw audio, credentials, or personal data in logs, metrics, traces, error reports, or metric labels.
- Keep operational telemetry pseudonymised and aggregate wherever possible. Storage of conversation content or free-text feedback requires a documented purpose, an appropriate opt-in where required, a defined retention period, and verifiable deletion.
- Original and translated audio are currently subject to the managed 24-hour cleanup policy. Any change to audio storage, retention, backups, or retrieval must include a privacy and security review and updates to the relevant documentation and tests.
- Review dependency, configuration, and deployment changes for known vulnerabilities, insecure defaults, unnecessary network exposure, and secret handling.
- Add or update tests for security-relevant behaviour, including validation failures, authorisation boundaries, retention, and deletion where applicable.

The current session workflow distinguishes only `admin` and `customer`. The [roles and permissions model](architecture/roles-and-permissions.md) describes the intended tenant-aware authorisation model; do not represent its future roles or capabilities as already implemented.

See the [deployment security guide](deployment/SECURITY.md) for production controls and the [conversation quality KPI catalog](operations/conversation-quality-kpis.md) for privacy-aware telemetry and consent requirements.

## 10. Observability and Operations

Every production-relevant change must remain observable and operable. Treat health checks, logs, metrics, alerts, and runbooks as part of the service contract, especially for the real-time conversation path.

- Preserve health and metrics endpoints for services that are started or changed. A health check must reflect whether the service can safely perform its declared role.
- Instrument significant outcomes, latency, retries, fallbacks, and failures with stable metric names and bounded label values. Do not use session IDs, user identifiers, message content, raw errors, or other high-cardinality or sensitive data as metric labels. Legacy WebSocket metrics currently include session IDs; do not extend this pattern and treat its removal as security and privacy work.
- Log actionable context for failures without recording credentials, message content, raw audio, or personal data. Prefer stable error categories and codes that support aggregation and alerting.
- Update dashboards, alert rules, and runbooks when a change introduces, removes, or materially changes an operational signal, failure mode, recovery path, or dependency.
- Validate relevant health checks, logs, and metrics during local integration testing. For changes affecting message delivery or WebSocket behaviour, also verify the associated conversation-quality and broadcast signals.
- Treat production operations, backups, rollbacks, and recovery actions as assigned operational work. Do not execute them as part of ordinary feature development.

Useful commands while working against the development stack:

```bash
docker compose ps
docker compose logs -f api_gateway
docker compose logs -f asr translation tts
curl http://localhost:8000/health
curl http://localhost:8000/metrics
```

See the [conversation quality KPI catalog](operations/conversation-quality-kpis.md) for telemetry requirements, the [WebSocket production checklist](operations/WEBSOCKET_PRODUCTION_CHECKLIST.md) for deployment validation, and the [WebSocket broadcast-failure runbook](operations/runbooks/websocket-broadcast-failures.md) for incident response.

## 11. Documentation Responsibilities

Documentation is part of the change, not post-release cleanup. Update the documentation in the same pull request whenever behaviour, interfaces, configuration, operations, or developer workflow changes.

- Keep the [OpenAPI specification](openapi.yaml) and API examples aligned with externally observable REST contracts.
- Update WebSocket event, session-flow, and frontend-integration documentation when client-visible real-time behaviour changes.
- Update `.env.example`, deployment guidance, and runbooks when configuration, secrets, dependencies, monitoring, or recovery procedures change.
- Record durable architectural decisions, alternatives, and consequences in an ADR when a change establishes or alters a long-lived technical direction.
- Place new documents in the appropriate `docs/` area and add them to the [documentation index](README.md) when they are a maintained entry point.
- Keep examples executable, use relative links, and remove or correct superseded instructions rather than leaving conflicting guidance behind.
- State limitations, compatibility requirements, migration steps, and operational follow-up where they affect consumers or operators.

See the [documentation index](README.md) for the project documentation structure and the [contribution guide](../CONTRIBUTING.md) for pull-request expectations.

## 12. AI-Assisted Development

AI tools may support research, drafting, implementation, testing, refactoring, and documentation, but they do not replace accountable engineering judgement. The contributor who submits a change remains responsible for its correctness, security, privacy impact, maintainability, and licensing.

- Do not include credentials, tokens, private endpoints, personal data, customer audio, conversation content, or other confidential operational information in AI prompts or uploads.
- Review and understand AI-generated code before using it. Verify API names, assumptions, edge cases, dependencies, and compatibility with the current repository rather than accepting generated output verbatim.
- Apply the same testing, security review, documentation, and quality checks to AI-assisted changes as to any other change. Give additional scrutiny to authentication, authorisation, input handling, data retention, and performance-sensitive paths.
- Check generated code and text for inaccurate claims, insecure patterns, copied material, and licence or attribution concerns before committing it.
- Mention material AI assistance in the pull request when it helps reviewers understand how the change was produced or where additional review is warranted.
- Use AI output as a starting point, not evidence. Tests, documentation, source code, specifications, and review provide the evidence for a change.

See [AI-Assisted Development](../AI_DEVELOPMENT.md) for the project's detailed principles, approved practices, and limitations.

## 13. Definition of Done

A change is ready for review only when its intended behaviour, impact, and evidence are clear. It is done when all applicable items below are complete:

- The change is focused, reviewed by its author, and has no known unresolved correctness, security, privacy, or operational issue.
- Relevant unit, integration, contract, load, or manual tests have been added or updated and their results are recorded in the pull request. Any check not run is identified with a reason.
- Applicable formatting, linting, type-checking, security, and dependency checks have been run.
- Public APIs, WebSocket events, configuration, data handling, and operational behaviour remain compatible, or the breaking change, migration, and consumer impact are explicitly documented.
- Documentation, examples, OpenAPI contracts, runbooks, dashboards, alerts, and configuration templates have been updated where the change affects them.
- Secrets and sensitive data are absent from code, fixtures, logs, commits, documentation, and external tool prompts.
- Recovery, rollback, retention, and monitoring implications have been considered for changes that affect deployed services or stored data.
- The pull request contains a clear description, test evidence, relevant follow-up work, and enough context for an effective reviewer decision.

All required review feedback and CI checks must be resolved before merging.
