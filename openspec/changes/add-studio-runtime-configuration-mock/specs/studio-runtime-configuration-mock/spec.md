## ADDED Requirements

### Requirement: Contract-faithful opt-in runtime configuration mock

The system SHALL provide an opt-in service implementing
`GET /internal/plugins/ssf/v1/runtime-configuration` for Studio--SSF Runtime
Configuration Contract V1 development and tests.

#### Scenario: Tenant configuration is returned

- **WHEN** a request presents an authorized bearer service token,
  `X-Studio-Instance-Id`, and `X-Correlation-Id`
- **THEN** the service returns a Contract V1 configuration for that tenant

#### Scenario: Service token lacks permission

- **WHEN** a request uses the known mock service token without
  `ssf.runtime-configuration.read`
- **THEN** the service returns a `403` error envelope

### Requirement: Deterministic storage-policy and error testing

The mock SHALL provide two tenant configurations with `ask` and `disabled`
conversation-content storage policies and the documented error envelopes.

#### Scenario: Authorization projection is pending

- **WHEN** a request selects the mock authorization-pending scenario
- **THEN** the service returns a `409` error envelope without tenant content

### Requirement: Protected internal mock exposure

The mock MUST publish `http://127.0.0.1:8010` only when an operator explicitly
enables its `studio-mock` Compose profile. It MUST NOT publish a Traefik route
or accept an unauthenticated runtime-configuration request.

#### Scenario: Explicit profile startup

- **WHEN** an operator starts Docker Compose with the `studio-mock` profile
- **THEN** an internal caller can request the mock through loopback port 8010
  with the required V1 request headers
