# Gateway Characterization Inventory (task 1.1)

This is the compatibility checklist for every later #228 slice. A slice is compatible when
`pytest tests/gateway_contract` and the existing suites named below pass unchanged. The
exception is `tests/gateway_contract/conftest.py`, which is the one place that reaches
module-level globals and is expected to be repointed when they move.

Inventoried against `origin/main` at `d8aa98b`.

Tests under `tests/integration/` never run in CI. Both CI pytest jobs pass
`--ignore=tests/integration`. That includes `test_tenant_isolation_matrix.py`, even though
`tests/conftest.py` lists it as hermetic. Where the matrix was the only cross-tenant proof,
the gap is filled below.

| Area | Existing coverage (public surface, runs in CI) | Gap filled by (`tests/gateway_contract/`) |
| --- | --- | --- |
| Tenant-scoped admin REST | `test_tenant_session_access.py::test_http_admin_cannot_observe_another_tenant` (status, terminate), `::test_current_session_cross_tenant_lookup_uses_the_neutral_error_contract`, `::test_http_create_freezes_each_tenants_own_runtime_configuration`; `services/api_gateway/tests/test_admin.py::TestAdminRoutes::*`; `test_admin_realtime_ticket_route.py::*`; `test_tenant_message_routes.py::test_audio_lookup_requires_message_ownership`, `::test_terminal_session_denies_all_admin_audio_variants`, `::test_history_audio_urls_are_scoped_to_requesting_role`; `test_auth.py::*` (history only); `test_quality_telemetry_endpoint.py::*` | `test_contract_admin_rest.py`: create response fields and join link; replacement ends only the signed tenant's session; full `SessionStatusResponse`; current with and without an id; terminate and repeated terminate bodies; history fields and tenant filter; cross-tenant 404 for messages, message, both audio variants; 401 on every admin route family; 400 for tenant selectors in query, header, cookie and JSON body |
| Tenant-scoped customer REST | `services/api_gateway/tests/test_customer.py::*`; `test_customer_activation_consent.py::*`; `test_tenant_session_access.py::test_http_customer_bearer_cannot_downgrade_to_anonymous_capability`, `::test_http_customer_rejects_a_malformed_supplied_bearer` (status only); `test_correlation_id_validation.py::*` | `test_contract_customer_rest.py`: activation fields (first, repeated, language switch); unknown session 404; 422 body validation; customer status fields before and after activation; foreign bearer 404 on messages, message, audio and activate; malformed bearer 401; ended session 404 across the customer routes; customer audio 404 and 422; the three language lists agree |
| Studio runtime failure mapping | `test_customer_activation_consent.py::test_conflict_refuses_activation` (status only), `::test_failed_read_leaves_pending_and_still_activates`; `test_login_directory_route.py::*`. `test_studio_runtime_flow.py` exercises the class and a throwaway app, not the gateway route | `test_contract_studio_runtime.py`: session create resolves the signed tenant with the caller's correlation id; retryable failure 503 and non-retryable 502 with `{"detail": code}`, and no session left behind; tenant mismatch and revision mismatch 502; unconfigured Studio 502; malformed correlation id 400 before any fetch; activation 409 body for all three tenant-conflict codes, retryable or not; activation proceeds when the policy read fails or Studio is unconfigured |
| Consent-gated persistence | `test_customer_activation_consent.py::*` (HTTP in, internal state asserted). `test_persistence_gate.py`, `test_refused_content_removal.py`, `test_runtime_policy.py` and `test_session_message_public_shape.py` are unit tests | `test_contract_consent_persistence.py`: activate, send, terminate, then read history. Granted consent in ask mode retains the message. Declined, unanswered, storage disabled, a Studio failure at write time and an unbound gate each discard it. Consent and authorization fields never reach a client |
| Pipeline metadata and failure mapping | `test_pipeline_admission.py::TestEndToEndOverTheWire::test_saturated_gateway_answers_503_with_retry_after`; `test_rate_limiting.py::test_session_message_rate_limit`; `test_correlation_id_validation.py::test_a_message_refuses_a_malformed_correlation_id`. Everything else calls handlers or `process_wav` directly | `test_contract_pipeline.py`: `MessageResponse` fields and `pipeline_metadata` for text and audio input, including the step order and role-scoped audio URLs; history and audio served per role; customer attribution; an upstream shedding load is 503 `SYSTEM_BUSY` with `Retry-After` on both paths; a failed audio stage is 500 `PIPELINE_ERROR`; a pending session is 400 `SESSION_NOT_ACTIVE` for both roles; `UNSUPPORTED_CONTENT_TYPE`, `INVALID_JSON`, `VALIDATION_ERROR`, `UNSUPPORTED_LANGUAGE` and `MISSING_FIELDS` envelopes. The speech services are replaced at their HTTP boundary |
| Speech-service failures, circuit breakers and refinement | `test_contract_pipeline.py` (a shedding TTS is 503 on both paths; a failed audio stage is 500 `PIPELINE_ERROR`); `test_pipeline_failure_stage_and_code.py`, `test_pipeline_circuit_breaker.py`, `test_ai_service_client.py`, `test_circuit_breaker*.py`, `test_degradation_mode_follows_breakers.py` and `test_translation_refiner.py` call `process_wav`, `call_ai_service` or the classes directly | `test_contract_speech_failures.py`, passing unchanged at `b2266c4`: on the audio path each failed stage (ASR, translation, TTS) is 500 `PIPELINE_ERROR` with the stage's message prefix, `failed_stage`, the `upstream_error` code, the transcript and translation already produced, and no stored message; TTS answering 200 without audio is `upstream_malformed_response`; a 4xx is `upstream_rejected`; a refused connection or timeout reaches the client only as `Pipeline-Fehler: <code>`, never the service host, on both paths; a shedding stage is 503 `SYSTEM_BUSY` with the upstream's own `Retry-After` for every stage on both paths, and a 503 without one gets 5 seconds; three failures open a stage's breaker (`/api/health/circuit-breakers`: state, failure count, 45-second recovery), after which that stage is 503 `SYSTEM_BUSY` with a `Retry-After` inside the window, is not called, and stores nothing, on both paths; `/api/health/summary` raises a `circuit_open` alert and the operator reset closes it; TTS without audio counts toward its breaker, a load shed or a 4xx does not; refinement applied, unchanged, failed, empty and skipped by target language, as the translated text, the `refinement` step, its comparison status and the text sent to TTS; a changed refinement drops the translation service's `tts_text`; `POST /pipeline` and `POST /upload` success, and `/pipeline` running the refiner. The speech services and the refiner are replaced at their HTTP boundary. Half-open probing and the recovery clock, and the degradation mode following breaker transitions, stay unit-tested: the first needs a clock, and without the lifespan no loop is bound, so the contract harness drops the transition callbacks |
| Audio validation, conversion and storage | `test_contract_pipeline.py` (a valid 16 kHz mono message succeeds, and its translated audio is served as a WAV); `test_audio_validation.py`, `test_tenant_audio_storage.py` and `test_audio_service_behavior.py` call `validate_audio_input`, `process_wav` or the storage functions directly. No test sent an invalid or convertible recording over HTTP | `test_contract_audio.py`, passing unchanged at `1d1b42e` (PR5b): a non-WAV body, a WAV under 0.1 s and a body one byte over 32 MB are 400 on the admin and customer message routes with the validator's code (`INVALID_WAV_FORMAT`, `INVALID_AUDIO_SPECS`, `FILE_TOO_LARGE`), message and `validation_details`, before any speech service is called and with nothing stored; audio is checked after the session-language match and before the supported-language check; `POST /pipeline` answers the same inputs with 400 and its single `Audio_Validation` step, `POST /upload` with its 400 page; a 44.1 kHz stereo WAV reaches ASR as 16 kHz mono 16-bit on all three routes, and `/pipeline` reports the conversion in its validation step; the message metadata has no validation step; message audio is stored at `v2/<tenant_ref>/<session_id>/<variant>/<message_id>.wav` under `SSF_AUDIO_BASE_DIR`, the original as uploaded, and both roles are served exactly those bytes. The message path validates once: `_validate_audio_payload`, then `process_wav` with `validate_audio=False` (`tests/test_audio_adapters.py` pins the single call) |
| Realtime-ticket issue and consume | `test_admin_realtime_ticket_route.py::*` (issue, cross-tenant issue 404); `test_tenant_polling.py::test_ticket_issued_before_termination_cannot_activate_polling`; `test_tenant_websocket.py::test_admin_websocket_rejects_invalid_ticket_before_accept`. `test_realtime_ticket.py` tests the store class directly | `test_contract_realtime_tickets.py`: issue body and 60-second expiry; 422 outside the transport literal; single use over WebSocket and over polling; expiry for both transports; transport binding; a rejected ticket is spent; termination revokes WebSocket tickets; a foreign tenant cannot activate polling with the ticket and does not spend it; an unavailable store gives 503, close 1013 and 503 |
| WebSocket connect, frames, close codes | `services/api_gateway/tests/test_tenant_realtime_integration_contract.py::test_admin_can_observe_only_its_session_realtime_connection`; `test_tenant_websocket.py::test_customer_websocket_still_accepts_an_anonymous_capability`, `::test_customer_websocket_rejects_a_cross_tenant_supplied_bearer_before_accept`, `::test_customer_websocket_rejects_a_malformed_supplied_bearer_before_accept`, `::test_legacy_client_selected_websocket_route_is_absent`. Frame and close behaviour beyond the ack is unit-tested on `WebSocketManager` only | `test_contract_websocket.py`: `connection_ack` fields; missing ticket 1008; missing or foreign origin 1008 for both roles; unknown or ended session denied with 404 before accept; `client_joined`, relayed `message` without echo, `typing_indicator` and `client_left` between two live sockets; malformed frames answered with `error` while the socket stays open; termination sends `session_terminated` then closes 1000; tenant-wide and per-session connection listings are tenant-scoped |
| HTTP message delivery to live WebSockets | None end to end. `test_contract_websocket.py` relays frames one socket sends; `test_contract_pipeline.py` checks the HTTP response only; `broadcast_message_to_session` and `WebSocketManager.broadcast_with_differentiated_content` are unit-tested with doubles. Found in PR4b: building `ConversationService` without its WebSocket manager failed no contract test | `test_contract_message_delivery.py`, added in PR4b and passing unchanged at `2847140`: for admin-to-customer and customer-to-admin, text and audio input, with both parties on WebSockets, `POST /api/<role>/session/{id}/message` gives the receiver a `receiver_message` frame with the translated text, the translated and original audio URLs and the pipeline metadata scoped to its own role, and gives the sender a `sender_confirmation` frame with its original text, no translated audio URL and its own role's URLs; the HTTP response fields are unchanged |
| Polling fallback | `test_tenant_polling.py::*`; `test_sonar_realtime_contracts.py::test_polling_timeout_openapi_and_request_contract`, `::test_admin_activation_documents_its_actual_not_found_response` | `test_contract_polling.py`: activation body for both roles; 422 ticket validation; customer activation needs a live session and a matching bearer; 429 at ten pollers per role; send delivers an exact envelope to the other role and not back to the sender; 422 envelope validation; a polled send reaches a live WebSocket; cross-tenant poll, send, recover and delete 404; role binding; status, recover and disconnect bodies; an admin poller gets `session_terminated` and is then removed |
| Lifespan startup and shutdown | `test_tenant_persistence_lifespan.py::*`; `test_runtime_policy_lifespan.py::*`; `test_quality_telemetry_lifespan.py::*`; `test_pipeline_admission.py::TestLifespanOwnership::test_lifespan_publishes_admission_on_app_state`; `test_feedback_connection_wiring.py::TestTheLifespanWiresTheAppItWasGiven::*`; `test_sonar_route_auth_contracts.py::test_lifespan_reports_a_background_task_failure_during_shutdown` | `test_contract_lifespan.py`: the `app.state` collaborators present after startup, in disabled and probe telemetry modes, while a request is served; everything acquired is `None` after shutdown; each lifespan builds its own admission gate |
| OpenAPI | Presence checks only, for example `test_tenant_polling.py::test_generic_client_controlled_polling_routes_are_absent` and `test_sonar_route_auth_contracts.py::test_affected_routes_keep_their_response_schemas_and_query_contracts` | `test_contract_openapi_snapshot.py` against `snapshots/openapi.json`, the full `app.openapi()` document. Regenerate on purpose with `SSF_UPDATE_OPENAPI_SNAPSHOT=1 pytest tests/gateway_contract/test_contract_openapi_snapshot.py` and review the diff |

## Deliberately not characterized

Each of these looks wrong, so none is pinned by a passing test. A later slice may change
them only through its own issue.

- A polling `/send` that overflows a recipient queue answers 500. The route's
  `dict[str, str]` return annotation rejects the documented partial body, after the message
  was already enqueued.
- A non-ASCII realtime ticket is reported as a service outage: close 1013 or HTTP 503
  instead of 404/4404.
- The admin WebSocket consumes its ticket before the origin check, so a rejected origin spends
  the ticket.
- A ticket is issued for a terminated session; the revocation makes it unusable.
- Closes for a missing or terminated session use 1003 in one path and 4404 in another.
- A repeated terminate returns `already_terminated` without re-running the cleanup that
  `TenantSessionManager.terminate_session` treats as idempotent.
- On the text path, a failed upstream stage is reported as 400 `TEXT_PIPELINE_ERROR`, and the
  language-pair errors use a different error body.
- `app.state.quality_telemetry` is not released on shutdown.
- On the audio path, a failed stage's 500 envelope carries the upstream reply's own text in
  `error_message` and the whole pipeline result in `details.pipeline_result`, including the
  debug record with every step's input. The stage prefix, stage, taxonomy code and the work
  already done are pinned; the upstream text and the debug record's contents are not.
- `POST /pipeline` and `POST /upload` answer every pipeline failure with 400, a load-shedding
  upstream and an open circuit breaker included, so a transient refusal looks permanent. Only
  their success paths are pinned.
- The audio path never forwards the translation service's `tts_text` to TTS; the text path does.
- `POST /api/admin/circuit-breakers/{service}/reset` and `/reset-all` have no authentication of
  their own. The contract suite pins their response body, not their access control.
- `GET /api/websocket/monitoring/health` has no authentication and no tenant scope. Its status
  also depends on the WebSocketMonitor heartbeat accounting, which a separate fix owns.
- WebSocketMonitor disconnect metrics and heartbeat-timeout accounting.
- The message path validates only an `UploadFile`. Any other object with a `read` method
  skips validation, and `process_wav` runs with `validate_audio=False`, so it would reach ASR
  unvalidated. Over HTTP every file part is an `UploadFile` and anything else is refused as
  `INVALID_FILE`, so no request reaches that branch (found in PR5b).
- `validation_time_ms` is a timing, so only its presence and type are pinned.
- Every route reads the whole upload into memory before the 32 MB check refuses it. No
  response shows the difference.

## Pinned as found

Surprising, but pinned by `test_contract_audio.py` as they behave (found in PR5b). Changing
one changes a contract test and needs its own issue.

- A body one byte over the 32 MB limit is refused as `Audio file too large: 32.0MB. Maximum
  allowed: 32.0MB`: the size is rounded to one decimal for display.
- The stored and served original is the recording as uploaded, not the 16 kHz mono audio
  ASR received.
- `POST /pipeline` returns its debug record, including the `Audio_Validation` step, whether
  or not `debug=true` was sent. The record also carries host CPU and RAM figures, which are
  not pinned.

## Accepted divergences
Changes a later slice made on purpose, where the output differs from what came before.

- Each app reads `SSF_AUDIO_BASE_DIR` when `build_gateway_dependencies` builds its audio
  store, not when `audio_storage` is imported (PR5b). Production sets the variable in the
  container environment before the process starts and never changes it, so both readings
  give the same directory. Only a process that changes the variable between import and
  startup, which only tests do, sees a different one.

- Message listings take audio availability from the markers the writer records instead of
  checking the disk (task 5.1). The hourly retention cleanup deletes files by age, and the
  content sweep that runs after it skips terminated sessions. So after that cleanup, a
  terminated session's history can list audio links whose files are gone. This is accepted
  because `audio()` already answers 404 for every audio request on a terminated session:
  those links were never fetchable, and no reachable behaviour changes. Hiding the
  unfetchable links on terminated sessions would change the history contract, so it belongs
  in its own issue.
- Message processing logs under `services.api_gateway.message_processing` instead of
  `services.api_gateway.routes.session`, because the code moved there (PR4b). The messages
  and their fields are unchanged.
- When a broadcast reports failure, the gateway now logs `WebSocket-Broadcasting
  fehlgeschlagen` with its send counts, as the code always intended (PR4b). Before, building
  that line hashed the `TenantSessionKey` instead of its session id and raised, so the handler
  logged `WebSocket-Broadcasting-Fehler` with a redacted traceback. Both lines are at ERROR
  level, and the HTTP response is unchanged. A broadcast to a session with no open WebSocket
  or polling connection reports failure, so the corrected line appears in normal operation.
- The activation log lines that sit between lifecycle decisions (ended session, idempotent
  answer, language switch, unsupported language, success) log under
  `services.api_gateway.session_lifecycle` instead of `services.api_gateway.routes.customer`
  (PR4b). Their messages, fields and order are unchanged. The request line and the
  unexpected-error line stay on the route's logger.
- The activation log lines name the customer language by looking it up among the supported
  codes (PR4b follow-up): `customer_language`, `previous_language` and `new_language` log
  the matching constant, and an unsupported or absent code is logged as `unsupported`
  instead of the value the request carried. Activation itself still accepts an unsupported
  code with its warning, and the responses are unchanged.
- Each app builds its own circuit breakers, health state and degradation mode (PR5a). They
  came from the process-wide `CircuitBreakerFactory` and two module singletons, so in a
  process running two apps, which only the test suites do, one app's failures opened the
  other's breakers. `/api/health/circuit-breakers` and the reset routes now list this app's
  breakers instead of every breaker the factory ever built; in production both are the same
  three. Each lifespan starts and stops its own health polling and aiohttp session.
- A malformed `LLM_REFINEMENT_*` setting refuses startup in the lifespan instead of at
  import (PR5a): `import services.api_gateway.app` succeeds and uvicorn reports that the
  application startup failed. The refiner is still the first thing built, so the gateway
  still stops before it connects to Redis or Studio.
- Startup logs lines that used to be lost (PR5a): the refiner's configuration line
  (`LLM translation refinement disabled`, or `... enabled with model ...`) and the health
  manager's `Graceful Degradation Manager initialisiert`, per-breaker `initialisiert` and
  `registriert`, and `Service Health Manager initialisiert`. They ran at import, before any
  logging handler existed; they now run in the lifespan.
- The startup banner prints `Pipeline admission ready` and the quality telemetry mode
  warning before `Building gateway dependencies...` (PR5a), because the container now
  receives both. The lines themselves are unchanged, and the `/health`, `/api/health/*` and
  circuit breaker reset bodies are identical to the base commit's.
- The shadow-compare refiner owns its candidate worker and the lifespan shuts it down
  without waiting (PR5a). One process-wide worker used to outlive every lifespan. A
  candidate already running or queued still finishes; one submitted after shutdown reports
  `submission_failed`, which no request can reach.
- `POST /pipeline`, `POST /upload`, `/api/health/circuit-breakers` and the circuit breaker
  reset routes resolve their collaborators through providers (PR5a). On an app whose
  lifespan has not run they now fail with `GatewayDependenciesUnavailable` instead of using
  the process-wide breakers and running unbounded. A running app always has its container.

## Inventory for PR7 (task 4.2)

Code with no production caller, found while moving the audio adapters (PR5b) and left
unchanged. `tests/test_audio_processing_boundary.py` walks every module reachable from
`app.py`; none of these is among them except `audio_storage.py` itself.

- `audio_storage.py`: `save_original_audio`, `save_translated_audio`, `get_audio_file_path`,
  `ensure_directories`, `ORIGINAL_AUDIO_DIR` and `TRANSLATED_AUDIO_DIR`, and
  `AUDIO_BASE_DIR`, which now exists only for them. Consumers: the unregistered leftovers in
  `routes/session.py` (`get_audio_file_path`), and `tests/test_sonar_new_coverage_audio.py`,
  `test_pipeline_metadata_enhancement.py`, `test_pipeline_metadata_integration.py`,
  `test_end_to_end_conversation.py` and `test_sonar_realtime_contracts.py`.
- `enhanced_audio_validation.py`, all of it. Consumers: `tests/test_audio_service_behavior.py`,
  `test_service_app_helpers.py`, `test_sonar_new_coverage_audio.py`, and the example in
  `docs/guides/audio-format-handling.md`.
