# Change: Put the live AI-service calls behind the circuit breaker

Tracks: #219

## Why

The gateway's resilience stack has no production callers on the path that
matters. `CircuitBreakerServiceClient.call_asr_service`,
`call_translation_service` and `call_tts_service`
(`services/api_gateway/circuit_breaker_client.py:63,137,226`) are imported
nowhere outside their own module and the tests. The pipeline reaches ASR,
translation and TTS through five bare `requests.post` calls
(`services/api_gateway/pipeline_logic.py:532,630,641,1501,1568`), none of which
consults a breaker or reports an outcome to one.

Breaker state is therefore driven only by the 30-second `/health` poll in
`ServiceHealthManager._check_service_health`. `/circuit-breaker/health` can
report every service CLOSED and healthy while every real request is failing,
because a `/health` ping and an inference request fail for different reasons and
only the ping is measured.

Two things stop the dead client from simply being wired in.

**It cannot serve the pipeline as written.** `_service_url`
(`circuit_breaker_client.py:31`) hardcodes `http://<service>:8000`, ignoring the
`DOCKER_COMPOSE=0` mapping to `localhost:8001-8003` that `pipeline_logic.py:36`
honours. It returns `translated_text` where the pipeline reads `translations`;
it sends `voice_id` where the pipeline sends `session_id` and `tts_text`; it
reads `audio_url` from JSON where the pipeline requires `audio/wav` bytes. And
the breaker bounds each call with `CircuitBreakerConfig.timeout`, which
`register_service` sets from the *health endpoint* budget — 8 to 10 seconds —
against pipeline timeouts of 60s for ASR, 30s for translation and 45s for TTS.

**Its failure path fabricates results.** `handle_service_failure` tries
`ALTERNATIVE_SERVICE` before `DEGRADED_QUALITY`, and
`_try_alternative_service` (`graceful_degradation.py:261`) returns
`{"success": True, "message": "Processed by alternative service: asr-backup"}`
without calling anything — `asr-backup`, `asr-simple`, `translation-basic` and
`tts-simple` do not exist in `docker-compose.yml` or anywhere else in the
repository. Behind it, `_try_degraded_quality` returns the ASR text
`"Vereinfachte Spracherkennung aktiv"` and a translation of
`f"[Basis-Übersetzung]: {source_text}"` — the untranslated source, labelled as a
translation, with `success: True`. Wiring that in would hand a user a fabricated
transcript in place of an error.

## What Changes

- Add a thread-safe synchronous API to `CircuitBreaker` — `guard()`,
  `record_success()`, `record_failure()` — sharing one state machine with the
  existing `async call()`. The pipeline runs on a worker thread under
  `PipelineAdmission`, so it has no event loop of its own to await on.
- Add `ai_service_client.call_ai_service(service, url, **kwargs)`: the single
  path every AI-service call takes. It keeps `requests` as the transport, so the
  URLs, payloads, per-stage timeouts and the `requests.Response` contract the
  pipeline is built on are unchanged.
- Route all five pipeline call sites through it.
- Define the failure policy explicitly. A transport error or a 5xx is a breaker
  failure. A 4xx is not — the service is healthy and rejecting a bad request. A
  `503` carrying `Retry-After` is not either: since #190 that is deliberate load
  shedding by a working service, and breaking on it converts a queue into an
  outage while the client already has its retry signal.
- **BREAKING (internal):** add `QualityErrorCode.UPSTREAM_CIRCUIT_OPEN`. An open
  breaker becomes an ordinary pipeline failure — `_pipeline_error_result` with
  the failed stage, a `503`, and a `Retry-After` taken from the breaker's own
  next-attempt time. No fabricated output ever reaches a user.
- Drive the degradation mode from live breaker transitions, so
  `/circuit-breaker/degradation-status` reports real traffic.
- Retire the dead and dangerous code: `call_asr_service`,
  `call_translation_service`, `call_tts_service` and their `_perform_*` helpers;
  `_try_alternative_service`, `_try_degraded_quality`, the
  `alternative_services` configuration and the response cache that only those
  paths ever read or wrote.

## Impact

- Affected specs: `ai-service-resilience` (new capability)
- Affected code: `circuit_breaker.py`, new `ai_service_client.py`,
  `pipeline_logic.py` (five call sites and two failure handlers),
  `quality_telemetry.py` (one new enum member), `graceful_degradation.py`,
  `circuit_breaker_client.py`, `service_health.py`
- Affected API: `POST /upload` and `POST /api/session/{id}/message` gain one
  new failure mode — a `503` with `Retry-After` and the existing
  `error_code: "SYSTEM_BUSY"` envelope, because `_pipeline_error_result`
  reuses #190's shape. `upstream_circuit_open` appears only in the debug and
  telemetry payloads, where it stays distinct from ordinary load shedding.
  Clients that already handle the `SYSTEM_BUSY` 503 from #191 need no change;
  `AppError.ts` maps by status code and already renders it as `errors.server`.
  `POST /pipeline` is the exception: it maps every pipeline error to a `400`
  and reads neither field, so a refusal looks permanent there. That predates
  this change and is not fixed here.
- Affected telemetry: `upstream_circuit_open` is a new value in the ClickHouse
  `error_code` column. Values are additive; no existing row changes meaning.
- Not affected: `PipelineAdmission`. `process_wav` and `process_text_pipeline`
  stay synchronous, so the GPU bound from #191 is untouched.
- Not affected: `translation_refiner.py:257`, the Ollama call. It has no breaker
  either, but #219 names ASR, translation and TTS. Worth its own issue.

## Open question for review

`failure_threshold=3` and `recovery_timeout=45` come from `register_service`
and were chosen for health polling, not for inference. Three consecutive real
failures will now open a breaker for 45 seconds. That is the intended behaviour,
but the figures have never been exercised by live traffic, so they are the first
thing to revisit once this ships.
