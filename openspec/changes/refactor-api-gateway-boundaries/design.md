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
| Tenant session manager (`TenantSessionManager`) | `build_gateway_dependencies`, on a `RedisTenantSessionStore` over the lifespan's verified Redis connection, or a `MemoryTenantSessionStore` without `REDIS_URL`, with this app's tickets, polling store, persistence gate, pseudonymizer and audio store. The lifespan rehydrates it before startup continues | `get_session_manager` | container |
| Runtime policy gate | lifespan (`_build_runtime_policy`), handed to `build_gateway_dependencies`, which gives it to the session manager; shutdown clears it there | none; message persistence reads `TenantSessionManager.runtime_policy` | container |
| Realtime ticket store | `build_gateway_dependencies`, on the lifespan's verified Redis client and namespace, or in memory without `REDIS_URL` | `get_realtime_ticket_store` | container |
| Polling store | `build_gateway_dependencies` | `get_polling_store` | container |
| WebSocket manager | `build_gateway_dependencies` | `get_websocket_manager` | container |
| Conversation service (`ConversationService`) | `build_gateway_dependencies`, with this app's session manager, speech pipeline, audio store, pipeline admission, quality telemetry and WebSocket manager | `get_conversation_service` | container |
| Session lifecycle service (`SessionLifecycleService`) | `build_gateway_dependencies`, with this app's session manager | `get_session_lifecycle` | container |
| Studio runtime flow | lifespan (`runtime_flow_from_environment`), which also binds the persistence gate with it | `get_studio_runtime_flow`; `None` when Studio is unconfigured | container |
| Studio login directory service | `build_gateway_dependencies` (`login_directory_from_environment`) | `get_login_directory`; `get_studio_login_directory_service` and `get_auth_login_directory_provider` turn `None` into 503 | container |
| Pipeline admission | lifespan, before the container, which hands it to the conversation service | `get_pipeline_admission`, for `POST /pipeline` and `POST /upload` | container |
| Quality telemetry and its exporter | lifespan, before the container, which hands the telemetry to the conversation service | `get_quality_telemetry` | container |
| Feedback repositories and services | lifespan, retried by `feedback_connect_task` | `get_feedback_service`, `get_feedback_read_service` (`routes/feedback.py`) | container |
| Service health manager (`ServiceHealthManager`), its circuit breakers and its `GracefulDegradationManager` | `build_gateway_dependencies`; the manager builds its own breakers and degradation manager. The lifespan starts and stops its health polling, and the aiohttp session that polling opens, through the circuit breaker client | none; reached through the circuit breaker client and the speech pipeline | container |
| Circuit breaker client (`CircuitBreakerServiceClient`) | `build_gateway_dependencies`, over this app's health manager | `get_circuit_breaker_client`, for `/api/health/*` and `/api/admin/circuit-breakers/*` | container |
| Speech pipeline (`SpeechPipeline`: `HttpSpeechServices` over this app's breakers, the translation refiner and the audio validator) | `build_gateway_dependencies` | `get_speech_pipeline`, for `POST /pipeline` and `POST /upload`; the conversation service by constructor | container |
| Audio validator (`WavAudioValidator`) | `build_gateway_dependencies` | none; `SpeechPipeline.validator` | container |
| Audio store (`AudioStore`) | `build_gateway_dependencies` (`AudioStore.from_environment()`, which reads `SSF_AUDIO_BASE_DIR` as it runs) | none; the conversation service and the session manager by constructor, `audio_cleanup_task` from the lifespan's container | container |
| Translation refiner and its candidate executor | lifespan (`get_translation_refiner`), first, so a malformed `LLM_REFINEMENT_*` setting refuses startup before anything connects. The shadow-compare refiner owns its executor, and the lifespan shuts it down | none; `SpeechPipeline.refiner`, to which the lifespan attaches telemetry and metrics | container |
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
- PR4b left the pipeline admission gate and quality telemetry read through the request; PR5a injects them (below).

#### Speech services (PR5a)

- `SpeechServices` (`speech_services.py`) is the port the pipeline calls: `transcribe`, `translate` and `synthesize`. They return the upstream reply unclassified, because the pipeline's stage helpers already classify it into results, failed stages and taxonomy codes. `HttpSpeechServices` is the adapter: each method is the POST it always was, through `call_ai_service` and that service's breaker. The service URLs and `requests` as the transport stay.
- `call_ai_service` takes its breaker. Each app's `ServiceHealthManager` builds its breakers directly rather than from the process-wide `CircuitBreakerFactory`, so two apps share none; the status routes read them through the circuit breaker client.
- `process_wav` and `process_text_pipeline` take `speech` and `refiner` as required keyword arguments. `SpeechPipeline` bundles the two for one app; the conversation service and the `/pipeline` and `/upload` routes hold that one object.
- `run_pipeline` takes the admission gate instead of the request. The lifespan builds the refiner first, then the admission gate and quality telemetry, then the container, which hands the gate and the telemetry to `ConversationService` by constructor. Shutdown still clears `pipeline_admission` and the exporter, detaches telemetry and metrics from the refiner, and then shuts the refiner down.
- Audio validation, conversion and storage are PR5b's infrastructure adapters. The realtime ticket backend exposes `consume`, `put_if_absent`, and `get` domain operations rather than Redis eval details. Realtime registry, dispatch, heartbeat, polling, and monitoring have focused interfaces. #348 decides the supported tenant-safe monitoring API surface.

#### Audio adapters (PR5b)

- `audio_processing.py` holds the WAV validation and conversion, moved unchanged from `pipeline_logic.py`, which re-exports none of it. It is the only production module that imports `audioop`, which Python 3.13 removes, so replacing `audioop` touches this one adapter. `tests/test_audio_processing_boundary.py` follows the imports from `app.py`, function-local ones included, and fails if another reachable module imports it.
- `AudioValidator` is the port: `validate(audio_bytes, *, normalize) -> AudioValidationResult`. `WavAudioValidator` is the adapter over `validate_audio_input`. `SpeechPipeline.validator` carries one per app, and `process_wav` takes it as a required keyword next to `speech` and `refiner`.
- The message path validates once: `_validate_audio_payload` calls the pipeline's validator, and `process_wav` then runs with `validate_audio=False`. `POST /pipeline` and `POST /upload` validate inside `process_wav`, which records the `Audio_Validation` step.
- `AudioStore` (`audio_storage.py`) holds its `base_dir` and offers `path`, `save`, `delete`, `cleanup_expired` and `disk_usage` over the v2 functions. Those functions take `base_dir` as a required keyword, so no production path can fall back to the directory read at import. `AudioStore.from_environment()` reads `SSF_AUDIO_BASE_DIR` when it is called.
- `build_gateway_dependencies` builds one store per app (a caller may pass its own, as tests do) and keeps it at `GatewayDependencies.audio_store`. `ConversationService` writes both audio variants and serves `audio()` through it, `TenantSessionManager` deletes settled audio through it at termination and in the content sweep, and the lifespan hands it to `audio_cleanup_task`. No route handler reaches it directly, so it has no provider.
- `AUDIO_BASE_DIR`, `ORIGINAL_AUDIO_DIR` and `TRANSLATED_AUDIO_DIR` are still read at import, for the legacy functions with no production caller that task 4.2 inventories.
- `LegacySessionManager` gets no audio store. Deleting settled audio is a `SessionManagerBase._delete_settled_audio` hook that raises `NotImplementedError`, and only `TenantSessionManager` overrides it. The legacy manager cannot reach the hook: its sessions carry no tenant, `_settle_refused_content` returns nothing to delete for such a session, and a tenant session in the legacy manager fails its sweep write-back before any deletion. A store for it would need either a module-level instance, which the ownership rules forbid, or a constructor argument that no caller could use. If a legacy path ever reached the hook, the sweep would log `content_sweep_failed` instead of deleting from a directory no one configured.

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
