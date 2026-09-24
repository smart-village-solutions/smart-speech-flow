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
| Realtime ticket store | `build_gateway_dependencies`, on the lifespan's verified Redis client and namespace, or in memory without `REDIS_URL` | `get_realtime_ticket_store` | container |
| Polling store | `build_gateway_dependencies` | `get_polling_store` | container |
| WebSocket manager | `build_gateway_dependencies` | `get_websocket_manager` | container |
| Conversation service | `build_gateway_dependencies` | `get_conversation_service` | container |
| Studio runtime flow | lifespan (`runtime_flow_from_environment`), which also binds the persistence gate with it | `get_studio_runtime_flow`; `None` when Studio is unconfigured | container |
| Studio login directory service | `build_gateway_dependencies` (`login_directory_from_environment`) | `get_login_directory`; `get_studio_login_directory_service` and `get_auth_login_directory_provider` turn `None` into 503 | container |
| Pipeline admission | lifespan | `get_pipeline_admission` (`pipeline_admission.py`) | container |
| Quality telemetry and its exporter | lifespan | `get_quality_telemetry` | container |
| Feedback repositories and services | lifespan, retried by `feedback_connect_task` | `get_feedback_service`, `get_feedback_read_service` (`routes/feedback.py`) | container |
| `session_manager` | module instance | `get_session_manager` | adapter until PR4 |
| Runtime policy gate (`runtime_policy._GATE`) | lifespan, rebinding the module global through `bind_runtime_policy` | none; `current_runtime_policy()` | adapter until PR4 |
| Session pseudonymizer (`session_pseudonym._process_pseudonymizer`) | first use, rebinding the module global | none | adapter until PR4 |
| `circuit_breaker_client` | module instance | `get_circuit_breaker_client` | adapter until PR5 |
| `service_health_manager`, `graceful_degradation_manager` | module instances, reached only through `circuit_breaker_client` and `ai_service_client` | none | adapter until PR5 |
| `translation_refiner` and its candidate executor | module instances | none; the lifespan attaches telemetry through the container | adapter until PR5 |
| `fallback_manager` | module instance | none; its background task reads the container | adapter until PR6 |
| WebSocket monitor (`websocket_monitor.websocket_monitor`) | `initialize_websocket_monitor` in `app.py`, rebinding the module global | `get_connection_monitor` | adapter until PR6 |
| Prometheus registry and metric objects | `app.py` and `audio_storage.py` at import, attached by `create_app()` | `get_prometheus_registry` | adapter until PR7 |
| OIDC key cache (`auth._key_cache`) | module instance | `get_oidc_key_cache` | adapter until PR7 |
| Latest rate-limit middleware (`rate_limiter.LATEST_RATE_LIMIT_MIDDLEWARE`) | the middleware, rebinding the module global when it is built | none | adapter until PR7 |

Rules:

- `services/api_gateway` adds no module-level collaborator instance. A new collaborator is constructed in `build_gateway_dependencies` or the lifespan and reached through a provider.
- No zero-argument cached factory (`lru_cache`, `cache`) builds an injectable service.
- A provider takes only the `HTTPConnection`, so it serves HTTP and WebSocket routes alike and adds nothing to the OpenAPI document.
- Route handlers reach collaborators only through `Depends(provider)`.
- Tests replace a collaborator with `app.dependency_overrides[provider]`, or build their own app with `create_app()` and run its lifespan. Suites that drive the shared app without its lifespan get a fresh container per test from `tests/conftest.py`. Tests do not mutate module state.
- `tests/test_gateway_dependency_ownership.py` enforces the first two rules and lists every remaining adapter with the PR that removes it. The list only shrinks. It sees module-level constructions only: the four objects above that are rebound through `global` statements (`_GATE`, `_process_pseudonymizer`, the WebSocket monitor global, `LATEST_RATE_LIMIT_MIDDLEWARE`) are tracked by this table alone.
- Until PR4, two apps in one process share the adapters. The session manager then follows the most recently built container for its WebSocket manager, ticket revocation and polling notifications.

### Decision: Preserve tenant-aware state

Session and message boundaries preserve `TenantSessionKey`, tenant Redis keys and join index, consent-gated storage, runtime snapshots, and pipeline metadata. The session compatibility gate records whether legacy mode can be deleted after cutover proof or must be isolated behind a typed adapter. No code slice assumes legacy state is absent merely because the target architecture does.

### Decision: Legacy session path is isolated behind a typed compatibility adapter

Decided on 2026-09-24. `SessionManager` keeps its legacy `str`-keyed path, but the path moves behind a typed compatibility adapter. Tenant-aware code then depends only on the typed `TenantSessionKey` contract, and the legacy path keeps working until a later removal. The adapter is built in the session-boundary slice (task 2.1).

This isolates the legacy path; it does not approve deleting it. Removal still needs the recorded cutover decision and operational evidence that the "Legacy session path decision" scenario requires.

### Decision: Separate transport responsibilities

Route adapters call application services; application services depend on typed ports. Speech HTTP access, validation/conversion/storage are infrastructure adapters. The realtime ticket backend exposes `consume`, `put_if_absent`, and `get` domain operations rather than Redis eval details. Realtime registry, dispatch, heartbeat, polling, and monitoring have focused interfaces. #348 decides the supported tenant-safe monitoring API surface.

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
