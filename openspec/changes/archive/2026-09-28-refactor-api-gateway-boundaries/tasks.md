## 1. Characterization and Composition Root

- [x] 1.1 Characterize current tenant-scoped admin/customer REST, Studio-runtime failure, consent/persistence, pipeline-metadata, realtime-ticket, polling, and lifespan contracts.
- [x] 1.2 Define dependency ownership and no-new-global rules, including provider override patterns for tests.
- [x] 1.3 Introduce a lifespan-owned `GatewayDependencies` container and dependency providers without changing public behavior.
- [x] 1.4 Migrate existing app-state collaborators and global adapters incrementally; add tests that isolated app instances do not share injected dependencies.
  - No adapter is left: PR7b deleted `fallback_manager` with `websocket_fallback.py`, which nothing reached since PR6b. PR4a moved the session manager, the runtime policy gate and the session pseudonymizer into the container; PR5a moved the service health manager, its breakers and degradation manager, the circuit breaker client and the translation refiner; PR6b the WebSocket monitor. PR7a moved the last process-wide state into each app: `create_app()` builds the Prometheus registry and every metric object (`GatewayMetrics`) and the rate limits (`RateLimits`), and `build_gateway_dependencies` the OIDC key cache. No gateway module rebinds a global. `tests/test_gateway_app_isolation.py` shows two apps share none of them.
  - #347 §4's "`tenant_persistence.py` no longer reassigns module globals" is complete: it verifies and returns the Redis connection, and `build_gateway_dependencies` builds both stores on it.

## 2. Session, Message, and Pipeline Boundaries

- [x] 2.1 Record the legacy session cutover decision and operational evidence; either plan deletion or define a typed compatibility adapter.
  - Decision (2026-09-24): keep the legacy path behind `LegacySessionManager`, the typed compatibility adapter in `legacy_session_manager.py`. See design.md.
  - Evidence: the legacy mode is not reachable in any running app. Before PR4a the module-level manager was always built with a `MemoryTenantSessionStore` and `tenant_persistence.py` swapped in the Redis store, so tenant mode was on in every app; now `build_gateway_dependencies` builds only a `TenantSessionManager`.
  - Evidence: the unregistered `services/api_gateway/session.py` is the only production-tree consumer of the `str`-keyed path. `app.py` registers `routes/session.py` instead, none of its routes is in `app.openapi()`, and no production module imports it.
  - PR7b deleted that module, so the adapter's only consumers are its tests (design.md lists them), and the guard allows no gateway module to import it.
- [x] 2.2a Define typed tenant session contracts: `TenantSessionKey` on every public `TenantSessionManager` method, with `TenantSessionKey`, join-index, Redis, consent, and runtime-snapshot semantics retained.
- [x] 2.2b Decide the async persistence port for the tenant session store.
  - Decision: its own change, not part of this one. PR4a assessed it at roughly 600–900 lines: the realtime ticket store shares the Redis connection and must move with it, and the synchronous session access guards would move from the thread pool onto the event loop. #428 tracks it, with a `redis.asyncio` port for both stores or an interim `asyncio.to_thread` adapter as the options. See design.md.
- [x] 2.3 Extract application services for session lifecycle and message processing; migrate routes without public contract drift.
  - Message processing (PR4b): `message_models.py` and `message_processing.py`, entered only through `ConversationService`; nothing outside `routes/` imports from `routes/` (`tests/test_gateway_import_direction.py`).
  - Session lifecycle (PR4b): `SessionLifecycleService` in `session_lifecycle.py`; the admin create, current, terminate and history handlers and the customer activation handler map its results onto HTTP.
  - `routes/session.py` held unregistered leftovers, which PR7b deleted; it keeps `GET /api/languages/supported`.
- [x] 2.4 Extract speech HTTP, validation/conversion, and audio-storage adapters behind typed ports; preserve pipeline metadata and failure mapping.
  - Speech HTTP (PR5a): the `SpeechServices` port and its `HttpSpeechServices` adapter in `speech_services.py`, built per app with its breakers; the pipeline, the conversation service and the `/pipeline` and `/upload` routes receive it and the refiner explicitly. `test_contract_speech_failures.py` pins the failure mapping.
  - Audio validation and conversion (PR5b): moved unchanged into `audio_processing.py`, the only production module that imports `audioop` (`tests/test_audio_processing_boundary.py`); the `AudioValidator` port and its `WavAudioValidator` adapter ride on `SpeechPipeline`, and the message path, `POST /pipeline` and `POST /upload` validate with that one object (`tests/test_audio_adapters.py`).
  - Audio storage (PR5b): `AudioStore`, built per app by `build_gateway_dependencies` from `SSF_AUDIO_BASE_DIR` as it runs, is injected into `ConversationService`, `TenantSessionManager` and `audio_cleanup_task`; the v2 storage functions no longer default to the directory read at import. The suites that patched `audio_storage.save_audio`, `delete_message_audio` or `conversation_service.audio_path` build their service or manager with a recording, refusing or undeletable store instead.
  - Public behaviour unchanged: `test_contract_audio.py` passes unchanged at `1d1b42e` and after the change, and the OpenAPI snapshot is untouched.
- [x] 2.5 Add parity, lifecycle, cross-tenant, persistence, and pipeline contract coverage.
  - The contract suite, `tests/gateway_contract/` (228 tests), by area:
    - Parity: `test_contract_admin_rest.py`, `test_contract_customer_rest.py`, `test_contract_openapi_snapshot.py` (the full `app.openapi()` document).
    - Lifecycle: `test_contract_lifespan.py` (the app's lifespan), `test_contract_studio_runtime.py` (session create and activation against Studio).
    - Cross-tenant: `test_contract_realtime_isolation.py`, and the cross-tenant cases in `test_contract_admin_rest.py`, `test_contract_customer_rest.py`, `test_contract_realtime_tickets.py` and `test_contract_polling.py`; beside them `tests/integration/test_tenant_isolation_matrix.py` (19 tests), which CI does not run.
    - Persistence: `test_contract_consent_persistence.py`.
    - Pipeline: `test_contract_pipeline.py`, `test_contract_speech_failures.py`.
    - Audio: `test_contract_audio.py`.
    - Realtime: `test_contract_websocket.py`, `test_contract_heartbeat.py`, `test_contract_message_delivery.py`, `test_contract_realtime_frames.py`, `test_contract_realtime_tickets.py`, `test_contract_polling.py`.
    - Metrics: `test_contract_metrics_surface.py`, `test_contract_realtime_metrics.py`.
  - Speech failures (PR5a): `test_contract_speech_failures.py` pins each stage's failure, open breakers and refinement outcomes on both message paths. Open: the text path's and `/pipeline`'s failure statuses are left unpinned on purpose (characterization.md), and half-open probing is unit-tested only.
  - Audio (PR5b): `test_contract_audio.py` pins the validator's refusals (non-WAV, too short, oversized) on the admin and customer message routes, `POST /pipeline` and `POST /upload`, with their error codes, messages, details and the `Audio_Validation` step; the check order against the language checks; 44.1 kHz stereo converted to 16 kHz mono 16-bit before ASR on all three routes; and the v2 file layout under `SSF_AUDIO_BASE_DIR`, served byte for byte to both roles.

## 3. Realtime, Polling, and Monitoring Boundaries

- [x] 3.1 Define typed realtime protocol and ticket-backend operations; migrate memory and Redis implementations without exposing Lua details.
  - Ticket backend (PR6a): the `RealtimeTicketBackend` port (`put_if_absent`, `put`, `consume`, `get`), with `RedisRealtimeTicketBackend`, the only code that runs the Lua, and a `MemoryRealtimeTicketBackend` that never sees a script. `test_realtime_ticket_redis.py` pins the semantics against a real Redis, unchanged before and after. See design.md.
  - Realtime protocol (PR6c): `realtime_protocol.py` holds `MessageType`, `ConnectionState`, and a TypedDict and builder for every server frame; every frame the sockets, the pollers and the differentiated broadcast send is built there. `test_realtime_protocol_guard.py` fails on an inline frame elsewhere (shown by adding one to `websocket.py`), and `test_contract_realtime_frames.py` pins each frame's keys and fixed values, unchanged before and after.
- [x] 3.2 Extract connection registry, dispatcher, heartbeat, polling fallback, and monitoring collaborators behind focused interfaces.
  - Monitoring (PR6b): `WebSocketMetrics` holds the process-wide series; each app's container builds its own `WebSocketMonitor` and pseudonymizer, and the WebSocket manager receives the monitor by constructor. The module global and its accessors are gone.
  - Polling fallback (PR6b): `fallback_manager` is unwired from the app and the container; PR7b deleted `websocket_fallback.py`.
  - Heartbeat (PR6b): the lifespan stops the task at shutdown.
  - Registry, dispatcher, heartbeat and client status (PR6c): `ConnectionRegistry`, `BroadcastDispatcher`, `Heartbeat` and `ClientStatusHandler`, each in its own type-checked module and given its dependencies by constructor; `WebSocketManager` is the facade that composes them (`tests/test_realtime_collaborators.py`). Mutations that make a broadcast skip pollers, stop the heartbeat timing out a silent socket, or pool two tenants' same-id sessions together each fail tests.
- [x] 3.3 Migrate WebSocket, polling, and supported monitoring routes while preserving tenant isolation, frame, and endpoint behavior.
  - PR6b: `WebSocketManager` is typed on `SessionRegistry[TenantSessionKey]` and `TenantSessionKey`; the WebSocket endpoints and polling routes reach the session manager through `get_session_manager`. `app.routes` and the OpenAPI document are unchanged, and the realtime metric names and labels are pinned (`test_contract_realtime_metrics.py`, `test_contract_heartbeat.py`).
  - PR6c: the routes run on the split collaborators through the unchanged facade. `app.routes`, the OpenAPI snapshot and the realtime metric families and labels are identical to `970ea7b`. #348 still decides the public monitoring scope; `/api/websocket/monitoring/health` is unchanged.
- [x] 3.4 Add realtime lifecycle, broadcast, heartbeat, polling, and cross-tenant denial integration coverage; coordinate public monitoring scope with #348.
  - Lifecycle, broadcast and heartbeat: `test_contract_websocket.py`, `test_contract_heartbeat.py`, `test_contract_message_delivery.py` and, from PR6c, `test_contract_realtime_frames.py`, which drives every frame over real sockets and, where the frame reaches them, pollers. PR6c also pins the 4404 close for a ticket whose session has lapsed and the value 1 of `websocket_monitor_initialized`, which no test caught before.
  - Polling: `test_contract_polling.py` and `test_contract_realtime_tickets.py`.
  - Cross-tenant denial (PR6c, `test_contract_realtime_isolation.py`): a ticket on another tenant's session, one tenant's frames reaching another's sockets or pollers, a foreign admin reading a poller's status, a foreign bearer on a customer poller, and a poller driven through another session; beside the listings in `test_contract_websocket.py` and the matrix, which passes (19 tests) but CI does not run.
  - #348 stays open. This change adds no monitoring endpoint and changes none.

## 4. Compatibility Cleanup and Verification

- [x] 4.1 Migrate first-party production imports and tests to the new boundaries; prohibit new production imports of compatibility adapters.
  - No gateway module imports `LegacySessionManager` (`LEGACY_SESSION_IMPORTERS` is empty in `tests/test_gateway_dependency_ownership.py`), builds a module-level collaborator or rebinds a global (the same file; `app` is its one permanent entry), or imports from `routes/` outside `app.py` (`tests/test_gateway_import_direction.py`). PR7b showed each guard failing on a mutation that adds such an import or instance.
  - The tests of deleted code went with it; `tests/test_audio_adapters.py` no longer reads the import-time `AUDIO_BASE_DIR`.
  - The two `real_system` tests in `tests/test_pipeline_metadata_integration.py`, broken since PR5a, now build `HttpSpeechServices` over a `ServiceHealthManager`'s breakers, refinement off and, for `process_wav`, a `WavAudioValidator`, as the app does (4.4).
- [x] 4.2 Inventory remaining facades and consumers; remove only adapters with no required consumers.
  - characterization.md, "Inventory for PR7 (task 4.2)": every item and its consumers, what PR7b deleted, and what it kept and why.
- [x] 4.3 Remove obsolete duplicate modules only after consumer search and compatibility proof.
  - PR7b deleted `websocket_fallback.py`, `enhanced_audio_validation.py`, the unregistered `services/api_gateway/session.py` and the other inventoried code after a repo-wide consumer search. `app.routes` (55 routes, both WebSocket routes included) and the OpenAPI snapshot are identical to `9f05640`; `/metrics` loses only `websocket_polling_messages_dropped_total`, which nothing counted into.
- [x] 4.4 Run the full gateway contract suite, tenant-isolation matrix, realtime integration suite, and configured real-system smoke coverage.
  - Run in PR7b, on the final tree:
    - CI's hermetic pytest (`tests/` and the four service suites, `not integration and not real_system`): 2486 passed, 31 skipped; the same in reverse file order; the same on a merge with `origin/main`.
    - `tests/gateway_contract`: 228 passed, three runs in a row (228 at `9f05640` too).
    - `tests/integration/test_tenant_isolation_matrix.py`: 19 passed.
    - `tests/integration/test_realtime_ticket_redis.py` with `--run-integration` against `redis:7.4.7-alpine`: 47 passed.
    - The feedback integration files CI runs against PostgreSQL (`test_feedback_repository.py`, `test_feedback_row_level_security.py`, `test_feedback_read_access.py`) against `postgres:17.7-alpine` with the real migrations: 48 passed.
    - A booted gateway under uvicorn: `/health` and `/metrics` answer 200; an admin socket (with a realtime ticket) and a customer socket connect, relay a message each way and disconnect; shutdown logs no "Task was destroyed". In production mode without `REDIS_URL` it exits 3.
  - Not run:
    - `tests/integration/test_websocket_integration.py` collects no tests: it is a script against a live gateway that drives `/api/websocket/polling/*` and the monitoring endpoints #348 owns, which are not registered. The realtime integration coverage is the contract suite's realtime files above.
    - The `real_system` tests against live ASR, translation and TTS services, which needs the speech stack. They now run on the per-app speech services, at URLs `SSF_REAL_SYSTEM_ASR_URL`, `SSF_REAL_SYSTEM_TRANSLATION_URL` and `SSF_REAL_SYSTEM_TTS_URL` override (default `localhost:8001` to `8003`). Proven against three local HTTP stubs answering with the contract suite's reply shapes: `pytest --run-real-system tests/test_pipeline_metadata_integration.py -m real_system` passed both, and with nothing listening both failed on `Pipeline-Fehler: upstream_unreachable` from a refused connection. CI still skips them.
- [x] 4.5 Update architecture and operations documentation with final dependency ownership and migration status.
  - `services/api_gateway/README.md` (composition root, providers, application services, ports and adapters, realtime collaborators, per app and process-wide), `docs/architecture/SYSTEM_ARCHITECTURE.md`, `websocket-architecture.md` and `session-flow.md`; design.md holds the final ownership table and decisions. The change is archived after deployment.

## 5. Consistency Items from #347

- [x] 5.1 Record audio availability on the message when it is written; listing messages performs no filesystem stat per message (#347 §6).
- [x] 5.2 Compare the Studio tenant id in constant time, matching the adjacent authorization-revision check in studio_runtime_flow.py (#347 §6).
- [x] 5.3 Normalise tenant selector names (casefold, strip "_" and "-") instead of enumerating spellings in tenant_context.py (#347 §6).
