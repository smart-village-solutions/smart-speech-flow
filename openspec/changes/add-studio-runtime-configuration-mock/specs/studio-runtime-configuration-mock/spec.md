## ADDED Requirements

### Requirement: Contract-faithful opt-in runtime configuration mock

The system SHALL provide an opt-in service implementing
`GET /internal/plugins/ssf/v1/runtime-configuration` for Studio--SSF Runtime
Configuration Contract V1 development and tests.

#### Scenario: Tenant configuration is returned

- **WHEN** a request presents a supported `X-Tenant-Id` header or `tenantId`
  query parameter
- **THEN** the service returns a Contract V1 configuration for that tenant

#### Scenario: Browser query parameter conflicts with header

- **WHEN** a request presents different tenant IDs in `X-Tenant-Id` and
  `tenantId`
- **THEN** the service returns a `400` error envelope

### Requirement: Deterministic storage-policy and error testing

The mock SHALL provide two tenant configurations with `ask` and `disabled`
conversation-content storage policies and the documented error envelopes.

#### Scenario: Tenant is not ready

- **WHEN** a request selects the mock not-ready scenario
- **THEN** the service returns a `409` error envelope without tenant content

### Requirement: Explicitly enabled HTTP exposure

The mock MUST publish `http://<host-ip>:8010` on all host network interfaces
only when an operator explicitly enables its `studio-mock` Compose profile.
The mock MUST NOT require authentication because it serves only fixed,
non-sensitive test data.

#### Scenario: Explicit profile startup

- **WHEN** an operator starts Docker Compose with the `studio-mock` profile
- **THEN** a network client can request the mock through the host IP and port
  8010 without authentication
