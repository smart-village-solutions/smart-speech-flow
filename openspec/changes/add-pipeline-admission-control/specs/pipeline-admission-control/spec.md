## ADDED Requirements

### Requirement: Bounded concurrent pipeline work

The API gateway SHALL limit the number of translation pipelines executing
concurrently to a configured maximum, and SHALL apply that limit only around
GPU pipeline work.

#### Scenario: Requests arrive within the limit

- **WHEN** fewer pipelines are in flight than the configured maximum
- **THEN** the gateway admits the request immediately
- **AND THEN** the pipelines execute concurrently

#### Scenario: A slot frees while a request is queued

- **WHEN** a request is waiting and an in-flight pipeline completes
- **THEN** the waiting request is admitted with the freed slot

#### Scenario: The limit is disabled

- **WHEN** `MAX_CONCURRENT_PIPELINES` is `0`
- **THEN** the gateway admits every request without bounding concurrency

#### Scenario: A pipeline fails inside its slot

- **WHEN** the pipeline raises an exception while holding a slot
- **THEN** the gateway returns the slot before propagating the error

### Requirement: Every slot is returned exactly once

A slot SHALL be returned exactly once, whether or not the request that acquired
it was cancelled, and SHALL NOT be returned while the work holding it is still
running. Cancellation is the only case where ownership is ambiguous: a queued
worker item is cancelled with the request, but one that has already started
cannot be interrupted.

#### Scenario: A request is cancelled after its work started

- **WHEN** a client disconnects while its pipeline is executing on a worker thread
- **THEN** the slot stays held until that thread finishes
- **AND THEN** the slot is returned exactly once

#### Scenario: A request is cancelled before its work started

- **WHEN** a client disconnects while its work is still queued for a worker thread
- **THEN** the slot is returned immediately
- **AND THEN** the work is abandoned rather than executed without a slot

### Requirement: SYSTEM_BUSY rejection contract

The API gateway SHALL reject a request with HTTP `503`, a `Retry-After` header
and the error code `SYSTEM_BUSY` when no pipeline slot becomes available within
the configured wait period. The response SHALL use the same error envelope as
the endpoint's other failures.

#### Scenario: No slot frees within the wait period

- **WHEN** every slot is held for longer than `PIPELINE_QUEUE_WAIT_SECONDS`
- **THEN** `POST /api/session/{session_id}/message` responds with status `503`
- **AND THEN** the body carries `error_code` `SYSTEM_BUSY`
- **AND THEN** the response carries a `Retry-After` header of at least `1` second

#### Scenario: Rejection is not reported as an internal error

- **WHEN** the unified message endpoint rejects a request for capacity
- **THEN** the response status is `503` and not `500`

#### Scenario: An upstream service sheds the request instead

- **WHEN** the translation service answers a pipeline step with `503`
- **THEN** the audio endpoint responds `503` with `error_code` `SYSTEM_BUSY`, not `500`
- **AND THEN** the text endpoint responds `503` with `error_code` `SYSTEM_BUSY`, not `400`
- **AND THEN** the response carries a `Retry-After` header derived from the
  upstream's own, so the client is not advised to retry sooner than the service asked

#### Scenario: A legacy pipeline route is saturated

- **WHEN** `POST /pipeline` or `POST /upload` finds no slot available
- **THEN** the route responds with status `503` and a `Retry-After` header

### Requirement: Non-pipeline endpoints stay responsive

The API gateway SHALL serve health, session-management and WebSocket traffic
without acquiring a pipeline slot, so saturation of the pipeline never blocks
them.

#### Scenario: Session management during saturation

- **WHEN** every pipeline slot is held
- **THEN** `GET /api/session/{session_id}` and `GET /api/sessions/active`
  respond normally

#### Scenario: Health checks during saturation

- **WHEN** every pipeline slot is held
- **THEN** `GET /health` responds normally

### Requirement: Admission configuration

The gateway SHALL read the concurrency limit and queue wait from typed,
documented configuration, and SHALL start with documented defaults when the
environment does not supply them.

#### Scenario: Configuration is absent

- **WHEN** neither `MAX_CONCURRENT_PIPELINES` nor `PIPELINE_QUEUE_WAIT_SECONDS`
  is set
- **THEN** the limit is `2` and the queue wait is `10.0` seconds

#### Scenario: Configuration cannot be parsed

- **WHEN** an admission environment variable holds a non-numeric value
- **THEN** the gateway logs a warning, applies the documented default, and starts

#### Scenario: The queue wait is a negative value

- **WHEN** a queue-wait variable is negative
- **THEN** the service logs a warning and applies the documented default

#### Scenario: Queueing is disabled

- **WHEN** a queue-wait variable is exactly `0`
- **THEN** a request is admitted immediately if a slot is free
- **AND THEN** a request is rejected immediately, without waiting, if none is

### Requirement: Admission metrics

The gateway SHALL expose in-flight, queue-wait and rejection metrics for the
pipeline bound so capacity can be tuned from load tests.

#### Scenario: A pipeline occupies a slot

- **WHEN** a pipeline holds a slot and then releases it
- **THEN** `gateway_pipeline_in_flight` rises and falls accordingly
- **AND THEN** `gateway_pipeline_queue_wait_seconds` records the wait

#### Scenario: A request is rejected

- **WHEN** the gateway rejects a request for capacity
- **THEN** `gateway_pipeline_rejected_total` increases

### Requirement: Lifespan ownership

The admission component SHALL be created by the application lifespan and
published on application state, not constructed at module import.

#### Scenario: The application starts

- **WHEN** the gateway completes lifespan startup
- **THEN** `app.state.pipeline_admission` holds the admission component

#### Scenario: A route runs without a started lifespan

- **WHEN** a pipeline route is reached with no admission component available
- **THEN** the route executes the pipeline unbounded rather than failing

### Requirement: Translation inference leaves its event loop free

The translation service SHALL execute M2M100 inference off its event loop, so
operational probes and further requests are served while a beam search runs.

#### Scenario: A probe arrives during inference

- **WHEN** `POST /translate` is executing `m2m_model.generate()`
- **THEN** `GET /health` and `GET /metrics` respond normally

#### Scenario: Two translations arrive together

- **WHEN** two requests reach `POST /translate` within the configured limit
- **THEN** both inferences make progress concurrently rather than serialising on
  the event loop

### Requirement: Bounded concurrent translation inference

The translation service SHALL limit concurrent inference to a configured maximum,
so the shared M2M100 instance and the GPU it sits on are not oversubscribed once
inference no longer serialises on the event loop. The gateway bound remains the
system-level capacity boundary.

#### Scenario: Inference is bounded

- **WHEN** more requests are in flight than `MAX_CONCURRENT_TRANSLATIONS`
- **THEN** no more than that many inferences execute at once

#### Scenario: The limit is disabled

- **WHEN** `MAX_CONCURRENT_TRANSLATIONS` is `0`
- **THEN** inference still runs off the event loop, without a bound

#### Scenario: A negative limit is configured

- **WHEN** `MAX_CONCURRENT_TRANSLATIONS` is negative
- **THEN** the service logs a warning and applies the documented default rather
  than running unbounded

#### Scenario: An admission setting cannot be parsed

- **WHEN** `MAX_CONCURRENT_TRANSLATIONS` or `TRANSLATION_QUEUE_WAIT_SECONDS`
  holds a non-numeric value
- **THEN** the service logs a warning, applies the documented default and starts,
  rather than raising before the server binds and crash-looping the container

#### Scenario: An inference slot's owner is cancelled

- **WHEN** a caller disconnects while its inference is running on a worker thread
- **THEN** the slot stays held until that thread finishes
- **WHEN** a caller disconnects while its inference is still queued
- **THEN** the slot is returned immediately and the inference is abandoned

#### Scenario: No inference slot frees within the wait period

- **WHEN** every slot is held for longer than `TRANSLATION_QUEUE_WAIT_SECONDS`
- **THEN** `POST /translate` responds with status `503`
- **AND THEN** the response carries a `Retry-After` header of at least `1` second
- **AND THEN** the status is `503` and not `500`, despite the handler's broad
  exception path

### Requirement: Tokenizer safety under concurrency

The translation service SHALL serialise the mutation of the tokenizer's
`src_lang` and the encoding that depends on it, because the tokenizer is shared
mutable state once inference runs on worker threads.

#### Scenario: Two threads encode at once

- **WHEN** two inferences run concurrently
- **THEN** only one is inside the tokenizer's encode step at any moment

### Requirement: Translation admission metrics

The translation service SHALL expose in-flight, queue-wait and rejection metrics
so its limit can be tuned from load tests.

#### Scenario: A rejection occurs

- **WHEN** a request is rejected for capacity
- **THEN** `translation_rejected_total` increases
- **AND THEN** `translation_queue_wait_seconds` records the wait it spent queued,
  so the histogram is not blind at saturation
