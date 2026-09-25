# API Gateway Service

## Studio-backed login directory

`GET /api/login/tenants` is an anonymous, read-only facade over Studio's
validated login directory. Studio is the source of truth for ready tenant
realms. The gateway uses one trusted `KEYCLOAK_BASE_URL`, admits only issuers
derived from current directory entries, and binds a validated token to its
signed `studio_tenant_id` and `ssf_authorization_revision` claims.

The tenant-login production rollout requires these settings:

```text
KEYCLOAK_BASE_URL=https://auth.dialog.kassel.de
KEYCLOAK_AUDIENCE=ssf-frontend
KEYCLOAK_REQUIRED_ROLE=ssf-user
STUDIO_RUNTIME_CONFIGURATION_BASE_URL=https://studio.dialog.kassel.de
STUDIO_RUNTIME_TOKEN_URL=<OAuth2 token endpoint>
STUDIO_RUNTIME_CLIENT_ID=ssf-runtime
STUDIO_RUNTIME_AUDIENCE=sva-studio-ssf-runtime
STUDIO_RUNTIME_CLIENT_SECRET=<deployment secret>
STUDIO_LOGIN_DIRECTORY_CACHE_SECONDS=60
STUDIO_RUNTIME_CONFIGURATION_TIMEOUT_SECONDS=5.0
SSF_CONTENT_RETENTION_HOURS=24
```

`STUDIO_RUNTIME_CONFIGURATION_TIMEOUT_SECONDS` bounds one live policy read and
must be greater than 0 and at most 30. `SSF_CONTENT_RETENTION_HOURS` is how
long consented conversation content is kept; `0` disables automatic deletion so
an operator removes it by hand. Neither ever retains content a guest declined
or a tenant policy disabled: that is removed when the conversation ends, and at
the latest when the session passes `SSF_SESSION_MAX_HOURS`.

Retention is applied two ways, because the two stores differ. Audio files are
swept hourly by age. A session record is immutable once terminated, so its
expiry is set on the record at the moment it terminates; changing the setting
later does not retime records that already terminated. The join tombstone
deliberately outlives the record -- it holds no conversation content and is
what stops a session identifier being reused.

The client secret must come from the deployment environment or secret store;
it must never be embedded in an image, browser bundle, or checked-in file.
Studio owns production realm provisioning once the tenant-login rollout is
activated. Until compatible gateway and frontend images are built, verified,
and pinned atomically, the canonical production Compose file remains on the
legacy single-realm contract. Do not combine its legacy application image pins
with the settings above.

## Multi-tenant rollout gate

Directory-based login establishes a trusted tenant identity, but it does not
make conversation persistence tenant-isolated. Before exposing real
conversations through multi-realm login, operators must complete all of the
following:

1. Confirm the Studio directory returns at least two ready tenant entries.
2. Confirm every listed realm has the common public client, PKCE S256, the
   exact application origin and `/login/*` redirects, the configured audience
   and role, and signed tenant-ID and authorization-revision claims. For the
   frontend's Account settings link, the realm's `account-console` client must
   be enabled and every administrator must hold `default-roles-<realm>` (or
   `account`/`manage-account`); users imported from JSON with an explicit
   `realmRoles` list do not get it automatically.
3. Complete the separate OpenSpec change `add-multi-tenant-operations` and pass
   its isolation tests for session creation, history, lookup, termination,
   messages, audio, and customer joins. This is an independent release gate,
   not part of the tenant-login-directory implementation.
4. Manually verify login, existing SSO, logout, unknown-tenant handling, a
   Studio outage after cache expiry, and cross-tenant negative paths in the
   deployed environment.

If any gate is incomplete, keep real multi-tenant conversations disabled. A
healthy directory or successful login alone is not production approval.

## What the gateway does

The API gateway is the single entry point of Smart Speech Flow. It connects the
ASR, translation and TTS services to the tenant-scoped admin and customer
conversations in the frontend: session lifecycle, text and audio messages,
realtime delivery over WebSockets and the polling fallback, persistence with
consent and retention, and health, resilience and metrics.

## Routes

The frontends use the tenant-scoped routes. An admin route requires a signed
tenant bearer token; a customer route accepts the session's anonymous
capability or a bearer token of the same tenant.

- Admin sessions: `POST /api/admin/session/create`, `GET /api/admin/session/current`,
  `GET /api/admin/session/history`, and below `/api/admin/session/{session_id}`:
  `status`, `terminate` (DELETE), `message` (POST), `messages`,
  `audio/{message_id}/{variant}.wav`, `realtime-ticket` (POST) and
  `realtime/connections`; `GET /api/admin/realtime/connections` for the tenant.
- Customer sessions: `POST /api/customer/session/activate`,
  `GET /api/customer/session/{session_id}`, and below it `message` (POST),
  `messages` and `audio/{message_id}/{variant}.wav`;
  `GET /api/customer/languages/supported`.
- Realtime: `WS /ws/admin/{session_id}?ticket=...` with a single-use ticket from
  `realtime-ticket`, and `WS /ws/customer/{session_id}`. The polling fallback
  lives below `/api/{admin|customer}/session/{session_id}/polling`: `activate`,
  then `{polling_id}` (GET polls, DELETE disconnects), `send`, `recover` and
  `status`.
- Login and feedback: `GET /api/login/tenants`, `POST /api/feedback`,
  `GET /api/feedback`, `GET /api/feedback/{feedback_id}`.
- Health and operations: `GET /health`, `GET /metrics`, `/api/health/*`,
  `/api/admin/circuit-breakers/*`, `POST /api/admin/telemetry/probe` and
  `GET /api/websocket/monitoring/health`.
- Language lists: `GET /api/languages/supported` and its alias `GET /languages`.
- Direct pipeline: `POST /pipeline` and `POST /upload` run ASR, translation and
  TTS on one upload outside any session. They are for service tests and
  technical integrations, not the frontend workflow.

`tests/gateway_contract/snapshots/openapi.json` is the complete, pinned
OpenAPI document.

## Internal structure

### Composition root

`create_app()` in `app.py` builds one app. It keeps two collaborators that
outlive a lifespan: the app's Prometheus registry and metric objects
(`GatewayMetrics`, at `app.state.gateway_metrics`) and its rate limits
(`RateLimits`, handed to `RateLimitMiddleware`). `app = create_app()` is the
module attribute uvicorn and the Dockerfile start.

The lifespan builds everything else, in this order: the translation refiner
(a malformed `LLM_REFINEMENT_*` setting refuses startup here), the verified
Redis connection (`configure_tenant_persistence`; production without
`REDIS_URL` refuses startup), the Studio runtime flow and its runtime policy,
the pipeline admission gate and quality telemetry, and then the app's
`GatewayDependencies` (`build_gateway_dependencies` in `dependencies.py`). It
rehydrates the tenant sessions from Redis, keeps the container at
`app.state.dependencies`, wires feedback persistence, and starts the
background tasks: session timeouts, health polling, the WebSocket monitor,
audio retention and feedback maintenance. Shutdown stops those tasks and the
heartbeat, releases the refiner, telemetry, Redis and feedback pools, and sets
`app.state.dependencies` to `None`.

### Providers

Route handlers reach collaborators only through `Depends(provider)`. Every
provider in `dependencies.py` takes the `HTTPConnection` and reads the app's
container, so it serves HTTP and WebSocket routes alike and adds nothing to the
OpenAPI document: `get_session_manager`, `get_realtime_ticket_store`,
`get_polling_store`, `get_websocket_manager`, `get_conversation_service`,
`get_session_lifecycle`, `get_studio_runtime_flow`, `get_login_directory`,
`get_circuit_breaker_client`, `get_speech_pipeline`, `get_pipeline_admission`,
`get_connection_monitor`, `get_prometheus_registry`, `get_oidc_key_cache` and
`get_quality_telemetry`. A test replaces one with
`app.dependency_overrides[provider]`, or builds its own app with
`create_app()` and runs its lifespan.

### Application services

- `SessionLifecycleService` (`session_lifecycle.py`) decides create, current,
  terminate, history and activation; the routes map its results and errors
  onto HTTP.
- `ConversationService` (`conversation_service.py`) is the only entry point to
  message processing (`message_processing.py`): parsing, validation, the
  pipeline, audio storage, persistence authorization and the differentiated
  broadcast.
- `TenantSessionManager` (`session_manager.py`) holds the sessions, keyed by
  `TenantSessionKey` on every public method.

No module outside `routes/` imports from `routes/`, except `app.py`, which
registers the routers.

### Ports and adapters

| Port | Adapters | Module |
| --- | --- | --- |
| `TenantSessionStore` | `RedisTenantSessionStore`, `MemoryTenantSessionStore` | `session_store.py` |
| `RealtimeTicketBackend` | `RedisRealtimeTicketBackend` (the only code that runs the consume Lua), `MemoryRealtimeTicketBackend` | `realtime_ticket.py` |
| `SpeechServices` | `HttpSpeechServices`, each call through its service's circuit breaker | `speech_services.py` |
| `AudioValidator` | `WavAudioValidator`; the only production module that imports `audioop` | `audio_processing.py` |
| `SessionRegistry[KeyT]`, `SessionSockets[KeyT]` | `TenantSessionManager` and `WebSocketManager`, each on `TenantSessionKey` | `session_manager.py` |
| `FeedbackSessions` | `TenantSessionManager` | `feedback/service.py` |

`AudioStore` (`audio_storage.py`) is built per app from `SSF_AUDIO_BASE_DIR`
and stores the v2 layout,
`v2/<tenant_ref>/<session_id>/<original|translated>/<message_id>.wav`.

Without `REDIS_URL`, as in local development and most tests, the container
uses the memory adapters. A production process never does.

### Realtime collaborators

`WebSocketManager` (`websocket.py`) is a facade over four collaborators, each
given its dependencies by constructor:

| Collaborator | Module | Owns |
| --- | --- | --- |
| `ConnectionRegistry` | `realtime_registry.py` | the session pools keyed by `TenantSessionKey` and the app-wide connection map |
| `BroadcastDispatcher` | `realtime_dispatch.py` | broadcasts, the differentiated message and delivery to pollers |
| `Heartbeat` | `realtime_heartbeat.py` | pings, pong latency and closing a silent socket |
| `ClientStatusHandler` | `realtime_client_status.py` | tab, battery and network reports and the adaptive polling interval |

`realtime_protocol.py` builds every server frame. The polling fallback is the
`TenantPollingStore` and routes in `websocket_polling_routes.py`, which receive
the same broadcasts. `WebSocketMonitor` (`websocket_monitor.py`) keeps the
connection records and counts into the app's `WebSocketMetrics`.

### Per app and process-wide

Everything above is built per app, and every lifespan builds a fresh container,
except the metrics and rate limits `create_app()` keeps. Two apps in one
process share no collaborator (`tests/test_gateway_app_isolation.py`).

What stays process-wide is the module attribute `app` and configuration read
at import: the speech-service URLs and schemes (`DOCKER_COMPOSE`,
`SERVICE_SCHEME`, `LOCAL_SERVICE_SCHEME`). No gateway module adds a
module-level collaborator or rebinds a global
(`tests/test_gateway_dependency_ownership.py`).

The str-keyed `LegacySessionManager` (`legacy_session_manager.py`) is a
compatibility adapter no app builds; only its tests use it, and no gateway
module may import it. The OpenSpec change `refactor-api-gateway-boundaries`
records the decision and the full ownership table.

## Local development

```bash
python3.12 -m venv .venv
source .venv/bin/activate
# Separate calls: the gateway's requirements are hash-pinned.
pip install -r requirements-dev.txt
pip install -r services/api_gateway/requirements.txt
uvicorn services.api_gateway.app:app --reload --port 8000
```

## Docker

The service starts from the repository's `docker-compose.yml`:

```bash
docker compose up -d api_gateway
```

## Tests

```bash
PYTHONPATH=. pytest tests/gateway_contract
PYTHONPATH=. pytest services/api_gateway/tests
```

`tests/gateway_contract` pins the public REST, WebSocket, polling, OpenAPI and
metrics behaviour of the gateway.
