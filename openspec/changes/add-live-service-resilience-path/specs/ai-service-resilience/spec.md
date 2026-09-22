## ADDED Requirements

### Requirement: Live AI-service calls pass through a circuit breaker
Every production request the gateway makes to the ASR, translation and TTS
services SHALL be admitted by that service's circuit breaker before it is sent,
and its outcome SHALL be recorded against the same breaker.

#### Scenario: A successful call is recorded
- **WHEN** the pipeline calls the translation service and the service answers `200`
- **THEN** the translation breaker records a success with the call's elapsed time
- **AND** `GET /circuit-breaker/health` reports a non-zero `total_requests` for `translation`

#### Scenario: A failing call is recorded
- **WHEN** the pipeline calls the ASR service and the service answers `500`
- **THEN** the ASR breaker records a failure
- **AND** the pipeline still returns its own `ASR-Fehler` result for that response

#### Scenario: The breaker opens after repeated failures
- **WHEN** three consecutive ASR calls fail
- **THEN** the ASR breaker transitions to `OPEN`
- **AND** `GET /circuit-breaker/health` reports `asr` as `open`

### Requirement: An open breaker fails the pipeline without calling the service
When a service's breaker is `OPEN`, the gateway SHALL NOT send the request, and
SHALL return the pipeline's ordinary failure result for the stage that was
blocked.

#### Scenario: Blocked before the request is sent
- **WHEN** the TTS breaker is `OPEN` and a pipeline run reaches the TTS stage
- **THEN** no HTTP request is made to the TTS service
- **AND** the result has `error: True` with `failed_stage: "tts"`

#### Scenario: The caller is told to retry
- **WHEN** a pipeline stage is blocked by an open breaker
- **THEN** the route answers `503` with a `Retry-After` header derived from the breaker's next attempt time
- **AND** the client sees the same `SYSTEM_BUSY` envelope the #190 load shedding already produces, so no client needs changing
- **AND** the telemetry code is `upstream_circuit_open`, keeping it distinct from a service that merely shed load

#### Scenario: A half-open breaker lets one request through
- **WHEN** an open breaker's recovery timeout has elapsed and a pipeline run reaches that stage
- **THEN** the breaker moves to `HALF_OPEN` and the request is sent
- **AND** a concurrent pipeline thread reaching the same stage is refused until that probe reports
- **AND** a probe that reports no outcome releases the next one only when the recovery timeout elapses again

### Requirement: Deliberate load shedding does not open a breaker
A `503` response carrying a parseable `Retry-After` header SHALL record no
outcome at all -- neither a success nor a failure -- because it is a working
service shedding load under the admission control added in #190, and no
request was served. Recording it as a success would reset the failure count of
a closed breaker and count toward the success threshold of a half-open one.

#### Scenario: Shedding is passed through, not broken on
- **WHEN** the translation service answers `503` with `Retry-After: 5`
- **THEN** the translation breaker records neither a failure nor a success
- **AND** the reply's latency does not enter the reported average
- **AND** the pipeline result keeps `error_code: "SYSTEM_BUSY"` and `retry_after_seconds: 5`

#### Scenario: A 503 without Retry-After is a fault
- **WHEN** the translation service answers `503` with no `Retry-After` header
- **THEN** the translation breaker records a failure

#### Scenario: A client error is not a service fault
- **WHEN** the TTS service answers `422`
- **THEN** the TTS breaker does not record a failure

### Requirement: The breaker is usable from a pipeline worker thread
`CircuitBreaker` SHALL expose a synchronous, thread-safe API that shares one
state machine with its existing asynchronous `call()`, so that the synchronous
pipeline functions can use it from the worker thread `PipelineAdmission` runs
them on.

#### Scenario: Used without a running event loop
- **WHEN** `guard()` and `record_failure()` are called from a thread with no event loop
- **THEN** the breaker's state advances exactly as it does through `await call()`

#### Scenario: Concurrent recording stays consistent
- **WHEN** several worker threads record outcomes against one breaker at the same time
- **THEN** the recorded request total equals the number of calls made

#### Scenario: The pipeline is not made asynchronous
- **WHEN** a route runs a pipeline through `run_pipeline`
- **THEN** the pipeline function is still synchronous and still holds one admission slot

### Requirement: Failure responses are never fabricated
The gateway SHALL NOT return invented transcripts, translations or audio in
place of a failed service call. Any fallback that reports success without having
produced a real result is removed.

#### Scenario: No placeholder transcript
- **WHEN** the ASR service is unavailable
- **THEN** the response is a pipeline error, and no transcript text is returned

#### Scenario: No source text presented as a translation
- **WHEN** the translation service is unavailable
- **THEN** the response is a pipeline error, and the source text is not returned as `translation_text`

### Requirement: Degradation status reflects live traffic
The service mode reported by `GET /circuit-breaker/degradation-status` SHALL be
derived from live breaker transitions rather than from health polling alone.

#### Scenario: Mode follows a breaker opening
- **WHEN** the TTS breaker opens because of failing pipeline requests
- **THEN** `GET /circuit-breaker/degradation-status` no longer reports `full`

#### Scenario: Mode recovers
- **WHEN** that breaker later closes
- **THEN** the endpoint reports `full` again

## REMOVED Requirements

### Requirement: Alternative-service and degraded-quality fallbacks
**Reason**: `_try_alternative_service` returned a fabricated success for four
services that do not exist in the repository, and `_try_degraded_quality`
returned a placeholder transcript and the untranslated source text labelled as a
translation. Neither ever called a service. Both were unreachable in production
and unsafe to reach.

**Migration**: None. The code had no production callers. Service failures now
surface as pipeline errors with `upstream_circuit_open` or the existing upstream
error codes.

### Requirement: The fallback response cache and request queue
**Reason**: Both were reachable only from `handle_service_failure`, whose last
caller went with the asynchronous service-call client. Nothing wrote to the
cache, so `/api/health/cache` reported zeroes indefinitely, and
`DELETE /api/admin/cache/clear` cleared a structure that was always empty.
Request queuing was never enabled.

**Migration**: None. No dashboard, frontend or deployment configuration read
either endpoint. `GET /api/health/degradation` keeps reporting the service
mode and its history, now driven by live breaker state.

### Requirement: Asynchronous AI-service call methods on CircuitBreakerServiceClient
**Reason**: `call_asr_service`, `call_translation_service`, `call_tts_service`
and their `_perform_*` helpers had no callers outside their own tests, and could
not have served the pipeline: they hardcode `http://<service>:8000`, ignoring
the `DOCKER_COMPOSE=0` mapping, return field names the pipeline does not read,
and are bounded by the health-check timeout rather than the inference timeout.

**Migration**: Callers use `ai_service_client.call_ai_service`. The client's
health, status and monitoring methods are unchanged and still back the
`/circuit-breaker/*` routes.


### Requirement: Only served traffic closes a breaker
The health poll SHALL record a failed probe as a breaker failure and SHALL NOT
record a successful probe at all, because a service can answer `/health` while
failing every inference request. A breaker SHALL return to `CLOSED` only on
successful requests that were actually served.

#### Scenario: A reachable service that cannot do its job stays broken
- **WHEN** a service answers `/health` normally but every inference request fails
- **THEN** the breaker opens and stays open however many health probes succeed
- **AND** `/api/health/services` still reports the service reachable

#### Scenario: A service that cannot be reached at all opens its breaker
- **WHEN** the health probe raises for `failure_threshold` consecutive polls
- **THEN** the breaker opens without waiting for a pipeline request to fail

### Requirement: The reported mode counts only verified services
The degradation mode SHALL treat a service as usable only while its breaker is
`CLOSED`. A `HALF_OPEN` breaker SHALL count as unusable, because a probe that
has not reported is not evidence that the service works.

#### Scenario: A recovery probe does not report full service
- **WHEN** an open breaker's timeout elapses and a probe moves it to `HALF_OPEN`
- **THEN** `/api/health/degradation` still reports `degraded`
- **AND** it reports `full` only once a served request has closed the breaker

### Requirement: A 2xx that did not carry the work is a failure
Where a service can answer `2xx` without having done the work, the call path
SHALL judge the reply by its payload and record a breaker failure when the work
is absent. A non-2xx reply SHALL NOT be judged this way, so that malformed
client input cannot open a breaker.

#### Scenario: TTS answers 200 with a JSON error body
- **WHEN** the TTS service answers `200` with `content-type: application/json`
- **THEN** the pipeline fails the TTS stage, as it already did
- **AND** the TTS breaker records a failure rather than a success
