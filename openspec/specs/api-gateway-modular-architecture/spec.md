# api-gateway-modular-architecture Specification

## Purpose
Define how the API gateway is composed internally: collaborators built per application in the lifespan and reached through replaceable providers, application services and ports that keep routes thin, and realtime, speech, audio and persistence adapters behind typed boundaries. Tenant isolation and the public REST, WebSocket, polling and OpenAPI contracts are preserved throughout.

## Requirements

### Requirement: Tenant-aware gateway dependency composition

The API gateway SHALL construct request-facing collaborators in FastAPI lifespan, retain them in a dependency container owned by application state, and expose them through replaceable dependency providers.

#### Scenario: Isolated test application

- **WHEN** a test creates an application instance and overrides a gateway dependency provider
- **THEN** only that application instance uses the replacement and module-level mutable state does not determine the collaborator

#### Scenario: Tenant runtime resolution

- **WHEN** a tenant-scoped admin or customer operation resolves runtime configuration
- **THEN** the provider preserves the validated tenant context, correlation identifier, and fail-closed policy

### Requirement: Characterized compatibility during boundary migration

The API gateway SHALL characterize and preserve existing public REST, WebSocket, polling, OpenAPI, Redis-session, and pipeline-metadata behavior before moving a responsibility across boundaries.

#### Scenario: Existing tenant-scoped API client

- **WHEN** a valid current client performs an existing admin or customer session operation during a migration slice
- **THEN** the route path, authorization semantics, response schema, and tenant isolation behavior remain compatible

#### Scenario: Existing realtime client

- **WHEN** an existing client uses a supported realtime ticket, WebSocket frame, or polling fallback
- **THEN** the gateway preserves compatible connection, message, heartbeat, and failure behavior

### Requirement: Tenant-aware session and message boundaries

The gateway application layer SHALL preserve `TenantSessionKey`, tenant-scoped persistence, join-index resolution, consent-gated storage, runtime snapshots, and emitted pipeline metadata while separating session and message workflows from transport code.

#### Scenario: Cross-tenant session access

- **WHEN** a principal attempts to access a session belonging to another tenant
- **THEN** the separated application workflow fails closed without exposing the other tenant's session data

#### Scenario: Legacy session path decision

- **WHEN** implementation reaches legacy session-manager cleanup
- **THEN** a recorded cutover decision and operational evidence determine whether the legacy path is removed or isolated behind a typed compatibility adapter

### Requirement: Focused realtime collaboration

The gateway SHALL express realtime ticket consumption, registry ownership, dispatch, heartbeat, polling fallback, and monitoring through focused interfaces that do not expose Redis wire details to application code.

#### Scenario: Single-use realtime ticket

- **WHEN** a realtime ticket is consumed
- **THEN** the ticket backend performs a single domain consume operation and the memory and Redis implementations preserve the same single-use result

#### Scenario: Tenant-safe monitoring

- **WHEN** an authenticated caller requests supported realtime connection information
- **THEN** the route applies tenant authorization and does not disclose another tenant's connection metadata

### Requirement: Compatibility-gated cleanup

The gateway SHALL remove a compatibility facade or duplicate module only after first-party consumers have migrated and the relevant compatibility contract tests pass.

#### Scenario: Facade removal

- **WHEN** a compatibility module has no remaining production consumers
- **THEN** its removal is verified by consumer search and the applicable gateway contract, tenant-isolation, and realtime tests

### Requirement: No legacy one-shot routes

The gateway SHALL NOT serve the legacy `POST /pipeline`, `POST /upload` or `GET /` routes. Speech processing SHALL be reachable only through the tenant-aware session message routes.

#### Scenario: Legacy route requested

- **WHEN** a client calls `POST /pipeline`, `POST /upload` or `GET /`
- **THEN** the gateway answers 404 and runs no pipeline

### Requirement: One translation tail for audio and text

Audio and text messages SHALL pass through one shared translation, refinement and TTS implementation, differing only in how the source text is produced.

#### Scenario: Refinement fails for either mode

- **WHEN** refinement fails for an audio or a text message
- **THEN** both keep the unrefined translation and continue to TTS with the same payload shape

#### Scenario: Empty transcript

- **WHEN** ASR returns a transcript that is empty after stripping whitespace
- **THEN** the message route answers 422 with error code `NO_SPEECH_RECOGNIZED`, and no message is created, stored or broadcast

### Requirement: Unhandled-error policy

The gateway SHALL answer an unhandled HTTP exception with a JSON 500 that carries CORS headers, and SHALL log its stack frames and exception type without the exception message. A broad exception handler SHALL exist only where it implements a fallback, a boundary guard or bookkeeping before re-raising.

#### Scenario: Unhandled exception in a route

- **WHEN** a route raises an unexpected exception before its response starts
- **THEN** the client receives `500 {"detail": "Internal server error"}` with CORS headers, and the log carries the stack frames and the original exception type but not the exception message

#### Scenario: New broad handler

- **WHEN** a production module gains a broad exception handler that is not in the inventory
- **THEN** the hermetic test suite fails and names its module and function

### Requirement: Gateway module size budget

No production module in `services/api_gateway` SHALL exceed 800 lines.

#### Scenario: Module grows past the budget

- **WHEN** a gateway production module exceeds 800 lines
- **THEN** the hermetic test suite fails and names the module
