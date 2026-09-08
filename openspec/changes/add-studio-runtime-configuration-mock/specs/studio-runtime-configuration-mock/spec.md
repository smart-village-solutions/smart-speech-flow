## ADDED Requirements

### Requirement: Contract-faithful local runtime configuration mock

The system SHALL provide an opt-in local service implementing
`GET /internal/plugins/ssf/v1/runtime-configuration` for Studio--SSF Runtime
Configuration Contract V1 development and tests.

#### Scenario: Tenant configuration is returned

- **WHEN** a request presents a valid mock service token and a supported
  `X-Tenant-Id`
- **THEN** the service returns a Contract V1 configuration for that tenant

### Requirement: Deterministic storage-policy and error testing

The mock SHALL provide two tenant configurations with `ask` and `disabled`
conversation-content storage policies and the documented error envelopes.

#### Scenario: Tenant is not ready

- **WHEN** a request selects the mock not-ready scenario
- **THEN** the service returns a `409` error envelope without tenant content

### Requirement: Production exclusion

The mock MUST NOT start or be reachable from the production Compose topology
unless an operator explicitly enables its local development profile.

#### Scenario: Default Compose startup

- **WHEN** Docker Compose starts without the mock profile
- **THEN** no Studio mock container is started
