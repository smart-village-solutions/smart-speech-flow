## ADDED Requirements

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
