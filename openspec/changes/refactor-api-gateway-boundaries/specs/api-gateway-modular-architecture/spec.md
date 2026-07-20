## ADDED Requirements

### Requirement: Layered gateway boundaries

The API gateway SHALL separate presentation, application, domain, port, infrastructure, realtime, and runtime responsibilities with dependencies directed toward domain and ports.

#### Scenario: Domain code is isolated from framework infrastructure

- **WHEN** a session or message domain type is imported
- **THEN** its module does not require FastAPI, Redis, HTTP client, WebSocket, or Prometheus dependencies

#### Scenario: Route behavior is delegated

- **WHEN** an HTTP or WebSocket request changes session or conversation state
- **THEN** the route delegates the business workflow to an application service rather than mutating persisted session state directly

### Requirement: Stable public gateway contracts

The API gateway SHALL preserve existing REST endpoints, OpenAPI schemas, WebSocket paths and frame contracts, polling fallback behavior, and `pipeline_metadata` response behavior during the boundary refactor.

#### Scenario: Existing frontend request

- **WHEN** a client calls an existing session, admin, customer, message, language, polling, or monitoring endpoint with a valid current request
- **THEN** the endpoint remains available with the current response schema and semantics

#### Scenario: Existing realtime client

- **WHEN** an existing client connects to `/ws/{sessionId}/{clientType}` and exchanges supported frames
- **THEN** the gateway accepts the connection and emits compatible frames, including heartbeat and translated-message behavior

### Requirement: Replaceable persistence and processing adapters

The application layer SHALL depend on typed ports for session persistence, speech processing, and realtime publication.

#### Scenario: Memory persistence in tests

- **WHEN** the gateway is configured without Redis
- **THEN** the memory repository provides the same session lifecycle and message-history semantics as the Redis repository

#### Scenario: Existing Redis session data

- **WHEN** the Redis repository loads a session persisted by the pre-refactor gateway
- **THEN** it restores the session, messages, statuses, and timestamps without data loss

### Requirement: Focused realtime collaboration

The gateway SHALL keep realtime protocol, connection registration, dispatch, heartbeat, polling fallback, and monitoring in distinct components coordinated through explicit interfaces.

#### Scenario: Message delivery

- **WHEN** a processed session message is persisted
- **THEN** the application service publishes it through the realtime publisher and receives a typed delivery result without importing WebSocket implementation details

#### Scenario: Connection lifecycle

- **WHEN** a WebSocket connection becomes inactive or disconnects
- **THEN** the heartbeat and registry components update connection state while preserving session lifecycle rules in the application layer

### Requirement: Centralized runtime composition

The API gateway SHALL construct dependencies during FastAPI lifespan and centrally manage periodic task startup and shutdown.

#### Scenario: Gateway startup

- **WHEN** the gateway starts
- **THEN** each application service and realtime component is composed once and background tasks are registered from the runtime layer

#### Scenario: Gateway shutdown

- **WHEN** the gateway shuts down
- **THEN** runtime tasks are cancelled and awaited without leaving service-monitoring or cleanup loops active
