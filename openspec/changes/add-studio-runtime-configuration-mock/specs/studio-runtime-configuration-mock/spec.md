## ADDED Requirements

### Requirement: Contract-faithful opt-in runtime configuration mock

The system SHALL provide an opt-in service implementing
`GET /internal/plugins/ssf/v1/runtime-configuration` for Studio--SSF Runtime
Configuration Contract V1 development and tests.

#### Scenario: Tenant configuration is returned

- **WHEN** a request presents an authorized bearer service token,
  `X-Studio-Tenant-Id`, and `X-Correlation-Id`
- **THEN** the service returns a Contract V1 configuration whose `tenant.id`
  exactly matches `X-Studio-Tenant-Id`

#### Scenario: Competing tenant selector is rejected

- **WHEN** a request presents `X-Studio-Instance-Id`, `X-Tenant-Id`, or any
  query selector, with or without the canonical tenant header
- **THEN** the service returns the stable `404 tenant_not_found` envelope

#### Scenario: Service token lacks permission

- **WHEN** a request uses the known mock service token without
  `ssf.runtime-configuration.read`
- **THEN** the service returns a `403` error envelope

### Requirement: Deterministic storage-policy and error testing

The mock SHALL provide two tenant configurations with `ask` and `disabled`
conversation-content storage policies and the documented error envelopes.

#### Scenario: Tenant or plugin is not ready

- **WHEN** a request selects suspended, plugin-inactive, or tenant-not-ready
- **THEN** the service returns the exact documented `409` envelope and
  retryability for that scenario without tenant content

#### Scenario: Runtime configuration is unavailable

- **WHEN** a request selects the unavailable scenario
- **THEN** the service returns the stable retryable `503` envelope

### Requirement: Protected internal mock exposure

The mock MUST publish `http://127.0.0.1:8010` only when an operator explicitly
enables its `studio-mock` Compose profile. It MUST NOT publish a Traefik route
or accept an unauthenticated runtime-configuration request.

#### Scenario: Explicit profile startup

- **WHEN** an operator starts Docker Compose with the `studio-mock` profile
- **THEN** an internal caller can request the mock through loopback port 8010
  with the required V1 request headers
