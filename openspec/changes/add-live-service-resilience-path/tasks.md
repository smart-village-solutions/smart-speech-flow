## 1. A breaker usable from a worker thread

- [x] 1.1 Write failing tests: `guard()` raises `CircuitBreakerOpenError` when OPEN, passes when CLOSED, and moves an expired OPEN to HALF_OPEN
- [x] 1.2 Write failing tests: `record_success` / `record_failure` advance state identically to `await call()`, including the HALF_OPEN → OPEN and success-threshold → CLOSED transitions
- [x] 1.3 Write a failing test: N threads recording concurrently leave `total_requests == N`
- [x] 1.4 Move the state transitions into synchronous methods under a `threading.Lock`; keep `async call()` behaviour byte-identical from the outside
- [x] 1.5 Add `guard()`, `record_success()`, `record_failure()`
- [x] 1.6 Dispatch `on_state_change` across threads; fall back to a log line when no loop is running
- [x] 1.7 Prove the guard: reintroduce an unlocked transition and watch 1.3 fail

## 2. Test isolation, before anything can trip a breaker

- [x] 2.1 Add an autouse `CircuitBreakerFactory.reset_all()` fixture to `tests/conftest.py` and `services/api_gateway/tests/conftest.py`
- [x] 2.2 Prove it: leave a breaker OPEN in one test, confirm the next test is unaffected

## 3. The single AI-service call path

- [x] 3.1 Write failing tests for `call_ai_service`: success recorded, 5xx recorded as failure, 4xx not recorded, transport error recorded, open breaker raises without sending
- [x] 3.2 Write failing tests for the shedding rule: `503` + `Retry-After` is not a failure; `503` without one is
- [x] 3.3 Implement `services/api_gateway/ai_service_client.py`
- [x] 3.4 Confirm the breaker's health-check timeout is not applied to the call

## 4. Route the pipeline through it

- [x] 4.1 Add `QualityErrorCode.UPSTREAM_CIRCUIT_OPEN`
- [x] 4.2 Write failing tests: each of ASR, translation and TTS blocked by an open breaker yields `error: True`, the right `failed_stage`, `upstream_circuit_open`, a 503 and a `Retry-After`
- [x] 4.3 Move the five call sites in `pipeline_logic.py` (532, 630, 641, 1501, 1568) to `call_ai_service`
- [x] 4.4 Catch `CircuitBreakerOpenError` per stage in `process_wav` and `process_text_pipeline`
- [x] 4.5 Confirm the existing pipeline suites still pass unchanged — they patch `requests.post`, which the new path still reaches
- [x] 4.6 Confirm `PipelineAdmission` is untouched: `tests/test_pipeline_admission.py` and `tests/test_gateway_event_loop_non_blocking.py` green

## 5. Status endpoints that report live traffic

- [x] 5.1 Write a failing test: a breaker opened by pipeline traffic changes `/circuit-breaker/degradation-status` away from `full`, and closing restores it
- [x] 5.2 Wire live breaker transitions into the degradation mode
- [x] 5.3 Write a failing test: `/circuit-breaker/health` shows request counts that only real traffic could have produced

## 6. Retire the fabricating fallbacks

- [x] 6.1 Delete `_try_alternative_service`, `_try_degraded_quality`, `_setup_service_alternatives` and `alternative_services`
- [x] 6.2 Delete the response cache, the request queue and the fallback dispatch, all
      unreachable once 7.1 removed their last caller. `/api/health/cache` and
      `DELETE /api/admin/cache/clear` go with them: both reported on a cache nothing
      writes to, and no dashboard, frontend or deployment config referenced either.
- [x] 6.3 Remove the `FallbackStrategy` members that no longer have an implementation
- [x] 6.4 Update or delete the tests that asserted the fabricated shapes
- [x] 6.5 Confirm `/circuit-breaker/degradation-status` and the cache-stats route still answer

## 7. Retire the unreachable async client

- [x] 7.1 Delete `call_asr_service`, `call_translation_service`, `call_tts_service` and `_perform_asr_request`, `_perform_translation_request`, `_perform_tts_request`
- [x] 7.2 Delete `_service_url`, which only those helpers used
- [x] 7.3 Update `tests/test_service_app_helpers.py`, `tests/test_circuit_breaker_integration.py`, `tests/test_sonar_new_coverage_circuit.py`
- [x] 7.4 Confirm `start_health_monitoring`, `stop_health_monitoring` and the status methods still back `/circuit-breaker/*`

## 8. Verification

- [x] 8.1 Full backend suite green, and say which commit it ran against
- [x] 8.2 Prove every new guard by reintroducing what it forbids, then reverting
- [x] 8.3 Live speech flow: full audio and text round trip against the real services
- [x] 8.4 Live failure path: stop a service, watch the breaker open, watch the 503, watch it close on recovery
- [x] 8.5 `flake8`, `black --check`, `isort --check`, `mypy` clean on the changed files
