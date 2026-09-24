## Context

The gateway is currently tenant-aware. It has `TenantSessionKey`, a tenant Redis session store, Studio runtime resolution, a fail-closed runtime policy, consent-gated persistence, admission control, live resilience, feedback services, and telemetry. Several collaborators already live on `app.state` and are constructed in FastAPI lifespan.

The same gateway retains global `session_manager`, `conversation_service`, and `realtime_ticket_store` instances, zero-argument `lru_cache` factories, and route-to-service imports. `SessionManager` retains legacy and tenant modes. Thus, the old architecture proposal is correct in direction but stale as an execution baseline.

## Goals / Non-Goals

### Goals

- Preserve delivered tenant, runtime, privacy, resilience, admission, feedback, and telemetry behavior.
- Move production collaborator ownership to one lifespan-owned dependency container and FastAPI providers.
- Split session/message/pipeline and realtime/polling/monitoring responsibilities behind typed boundaries.
- Characterize compatibility before each migration slice and clean up compatibility facades only after callers move.

### Non-Goals

- Change external REST, WebSocket, polling, OpenAPI, Redis, or pipeline-metadata contracts.
- Change tenant or authorization semantics.
- Add Redis Pub/Sub or multi-replica behavior (#227).
- Refactor AI service internals (#225).
- Delete legacy state without an approved and evidence-backed cutover decision.

## Decisions

### Decision: Current behavior is the characterization baseline

All migration slices first characterize the present admin/customer tenant flows, Studio runtime failures, consent/persistence gates, pipeline metadata, realtime tickets, polling, and lifespan shutdown. Existing public semantics control when an old plan statement conflicts with implemented behavior.

### Decision: Lifespan-owned composition root

`GatewayDependencies` holds all request-facing collaborators, created in `lifespan` and stored in `app.state`. Providers retrieve explicit collaborators; test overrides replace providers. New production code must not instantiate or replace module globals, or use zero-argument cached factories for injectable services.

Existing app-state services migrate into the container without behavioral changes. Global objects remain temporary adapters until consumers are migrated.

#### Dependency ownership

`create_app()` in `app.py` builds one app. Its lifespan builds that app's `GatewayDependencies` (`services/api_gateway/dependencies.py`), keeps it at `app.state.dependencies`, and sets that to `None` on shutdown. `app = create_app()` stays the module attribute uvicorn and the Dockerfile target.

| Collaborator | Constructed by | Provider | Status |
| --- | --- | --- | --- |
| Tenant session manager (`TenantSessionManager`) | `build_gateway_dependencies`, on a `RedisTenantSessionStore` over the lifespan's verified Redis connection, or a `MemoryTenantSessionStore` without `REDIS_URL`, with this app's tickets, polling store, persistence gate and pseudonymizer. The lifespan rehydrates it before startup continues | `get_session_manager` | container |
| Runtime policy gate | lifespan (`_build_runtime_policy`), handed to `build_gateway_dependencies`, which gives it to the session manager; shutdown clears it there | none; message persistence reads `TenantSessionManager.runtime_policy` | container |
| Realtime ticket store | `build_gateway_dependencies`, on the lifespan's verified Redis client and namespace, or in memory without `REDIS_URL` | `get_realtime_ticket_store` | container |
| Polling store | `build_gateway_dependencies` | `get_polling_store` | container |
| WebSocket manager | `build_gateway_dependencies` | `get_websocket_manager` | container |
| Conversation service (`ConversationService`) | `build_gateway_dependencies`, with this app's session manager and WebSocket manager | `get_conversation_service` | container |
| Session lifecycle service (`SessionLifecycleService`) | `build_gateway_dependencies`, with this app's session manager | `get_session_lifecycle` | container |
| Studio runtime flow | lifespan (`runtime_flow_from_environment`), which also binds the persistence gate with it | `get_studio_runtime_flow`; `None` when Studio is unconfigured | container |
| Studio login directory service | `build_gateway_dependencies` (`login_directory_from_environment`) | `get_login_directory`; `get_studio_login_directory_service` and `get_auth_login_directory_provider` turn `None` into 503 | container |
| Pipeline admission | lifespan | `get_pipeline_admission` (`pipeline_admission.py`) | container |
| Quality telemetry and its exporter | lifespan | `get_quality_telemetry` | container |
| Feedback repositories and services | lifespan, retried by `feedback_connect_task` | `get_feedback_service`, `get_feedback_read_service` (`routes/feedback.py`) | container |
| `circuit_breaker_client` | module instance | `get_circuit_breaker_client` | adapter until PR5 |
| `service_health_manager`, `graceful_degradation_manager` | module instances, reached only through `circuit_breaker_client` and `ai_service_client` | none | adapter until PR5 |
| `translation_refiner` and its candidate executor | module instances | none; the lifespan attaches telemetry through the container | adapter until PR5 |
| `fallback_manager` | module instance | none; its background task reads the container | adapter until PR6 |
| WebSocket monitor (`websocket_monitor.websocket_monitor`) | `initialize_websocket_monitor` in `app.py`, rebinding the module global | `get_connection_monitor` | adapter until PR6 |
| Session pseudonymizer | the WebSocket monitor (`SessionPseudonymizer.from_environment`); `build_gateway_dependencies` takes the monitor's | none; injected into the session manager, the feedback service and feedback maintenance, and read by the session access guards through the manager | shared with the WebSocket monitor until PR6 |
| Prometheus registry and metric objects | `app.py` and `audio_storage.py` at import, attached by `create_app()` | `get_prometheus_registry` | adapter until PR7 |
| OIDC key cache (`auth._key_cache`) | module instance | `get_oidc_key_cache` | adapter until PR7 |
| Latest rate-limit middleware (`rate_limiter.LATEST_RATE_LIMIT_MIDDLEWARE`) | the middleware, rebinding the module global when it is built | none | adapter until PR7 |

Rules:

- `services/api_gateway` adds no module-level collaborator instance. A new collaborator is constructed in `build_gateway_dependencies` or the lifespan and reached through a provider.
- No zero-argument cached factory (`lru_cache`, `cache`) builds an injectable service.
- A provider takes only the `HTTPConnection`, so it serves HTTP and WebSocket routes alike and adds nothing to the OpenAPI document.
- Route handlers reach collaborators only through `Depends(provider)`.
- Tests replace a collaborator with `app.dependency_overrides[provider]`, or build their own app with `create_app()` and run its lifespan. Suites that drive the shared app without its lifespan get a fresh container per test from `tests/conftest.py`. Tests do not mutate module state.
- `tests/test_gateway_dependency_ownership.py` enforces the first two rules and lists every remaining adapter with the PR that removes it. Its second list names the module globals still rebound through a `global` statement (the WebSocket monitor global, `LATEST_RATE_LIMIT_MIDDLEWARE`). Both lists only shrink.
- Until the PR named in the table, two apps in one process share the remaining adapters. Each app owns its session manager, so termination revokes that app's tickets and notifies that app's pollers and sockets.

### Decision: Preserve tenant-aware state

Session and message boundaries preserve `TenantSessionKey`, tenant Redis keys and join index, consent-gated storage, runtime snapshots, and pipeline metadata. The session compatibility gate records whether legacy mode can be deleted after cutover proof or must be isolated behind a typed adapter. No code slice assumes legacy state is absent merely because the target architecture does.

### Decision: Legacy session path is isolated behind a typed compatibility adapter

Decided on 2026-09-24. `SessionManager` keeps its legacy `str`-keyed path, but the path moves behind a typed compatibility adapter. Tenant-aware code then depends only on the typed `TenantSessionKey` contract, and the legacy path keeps working until a later removal. The adapter is built in the session-boundary slice (task 2.1).

This isolates the legacy path; it does not approve deleting it. Removal still needs the recorded cutover decision and operational evidence that the "Legacy session path decision" scenario requires.

#### Session manager split (PR4a)

- `TenantSessionManager` (`session_manager.py`) is the production path. Every public method takes a `TenantSessionKey`, it has no mode flag, and it requires its store at construction. `session_manager.py` is off the mypy ignore list, so the contract is checked.
- `LegacySessionManager` (`legacy_session_manager.py`) is the compatibility adapter: the `str`-keyed path and its own Redis persistence, moved unchanged. Only tests and the unregistered `services/api_gateway/session.py` construct it, the latter through a dependency no app provides. `test_only_the_legacy_adapter_reaches_the_legacy_session_manager` fails if any other gateway module imports it.
- Both managers share `Session`, `SessionMessage`, the helpers, and `SessionManagerBase[KeyT]`: the session cache, lifecycle telemetry and the content sweep.

No single Protocol covers both managers. Their key types differ, so every key-taking method on such a Protocol would need `Any` or a `Union`. Where a consumer does serve both, it gets a Protocol limited to what it calls:

- `SessionRegistry[KeyT]` in `session_manager.py`, generic in the key, for the WebSocket manager: `register_websocket_manager`, `get_session`, `add_websocket_connection`, `remove_websocket_connection`. `TenantSessionManager` is a `SessionRegistry[TenantSessionKey]` and `LegacySessionManager` a `SessionRegistry[str]`. The WebSocket manager takes `SessionRegistry[Any]` because its own session identifiers are still untyped; PR6 narrows it with the realtime boundary.
- `FeedbackSessions` in `feedback/service.py`: `resolve_customer_session`, `resolve_ended_session` and `has_unscoped_session`, all keyed by the bare id a browser sends. A tenant session is never stored under a bare id, so `TenantSessionManager.has_unscoped_session` is always false.

### Decision: Separate transport responsibilities

Route adapters call application services; application services depend on typed ports.

#### Message processing (PR4b)

- `message_models.py` holds the message request, response and error models, the error envelope (`create_error_response`) and `SUPPORTED_LANGUAGES`.
- `message_processing.py` holds the pipeline steps: parsing, validation, the pipeline-metadata transform, busy and error mapping, audio artefact storage, persistence authorization, response building and the differentiated broadcast.
- `ConversationService` is its only production entry point. The admin and customer message routes call `process` through `get_conversation_service` and pass only the key, the server-assigned role and the request.
- `routes/session.py` keeps `GET /languages/supported` and the unregistered leftovers PR7 removes. It re-exports nothing that moved.
- Rules, enforced by `tests/test_gateway_import_direction.py`: no gateway module outside `routes/` imports from `routes/`, at module level, inside a function or under `TYPE_CHECKING`. `app.py` is the one exception, because it registers the routers. Only `conversation_service.py` imports `message_processing`.
- `SessionLifecycleService` (`session_lifecycle.py`) decides create, current, terminate, history and activation: the frozen runtime snapshot, consent resolution and the live policy read, the idempotent and language-switch paths. `TenantSessionManager.create_admin_session` still ends the tenant's previous session. The routes keep authentication, key resolution, logging of the request itself, and the mapping of results and `SessionNotFoundError`, `NoActiveSessionError`, `SessionTerminatedError` and `TenantConflictError` to status codes and bodies. The Studio runtime flow reaches `activate` per call from `get_studio_runtime_flow`, the provider `require_validated_runtime_configuration` also reads, so one app never holds two flows.
- Still read through the request: the pipeline admission gate (`run_pipeline`) and quality telemetry. The lifespan builds both after the container and releases them on shutdown, and the upload and pipeline routes share the admission gate. They are read from the request's own app container, not from a module global. PR5 moves them behind the pipeline adapter. Speech HTTP access, validation/conversion/storage are infrastructure adapters. The realtime ticket backend exposes `consume`, `put_if_absent`, and `get` domain operations rather than Redis eval details. Realtime registry, dispatch, heartbeat, polling, and monitoring have focused interfaces. #348 decides the supported tenant-safe monitoring API surface.

### Decision: Four delivery slices

1. Characterization and composition root.
2. Session/message/pipeline boundaries.
3. Realtime/polling/monitoring boundaries.
4. First-party migration, compatibility cleanup, and verification.

Each slice must be independently releasable and preserve public contract behavior.

## Risks / Trade-offs

- Contract drift: characterize public contracts before migrations and require API and realtime tests per slice.
- Tenant privacy regression: include tenant-isolation and cross-tenant negative tests in every affected slice.
- Legacy cleanup error: require a hard decision gate and explicit consumer inventory.
- Global-to-provider migration test fragility: override dependency providers and use test app instances rather than mutating module state.
- Competing scopes: explicitly exclude #225, #227, and #348.

## Migration Plan

1. Rebase planning artifacts only in this PR; do not change runtime code.
2. Implement phase 1 only after approved tasks and a characterized baseline.
3. Implement later phases in focused PRs that reference #228 and the phase.
4. Remove facades only after full compatibility verification.

## Rollback Plan

This PR changes no runtime code. A later implementation slice rolls back only that slice while preserving the characterization tests.
