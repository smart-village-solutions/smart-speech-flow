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
