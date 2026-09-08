## ADDED Requirements

### Requirement: Contract-faithful opt-in runtime configuration mock

The system SHALL provide an opt-in service implementing
`GET /internal/plugins/ssf/v1/runtime-configuration` for Studio--SSF Runtime
Configuration Contract V1 development and tests.

#### Scenario: Tenant configuration is returned

- **WHEN** a request presents an authorized bearer service token,
  `X-Studio-Tenant-Id`, and `X-Correlation-Id`
- **THEN** the service returns a Contract V1 configuration for that tenant
  whose `tenant.id` exactly equals `X-Studio-Tenant-Id`

#### Scenario: Service token lacks permission

- **WHEN** a request uses the known mock service token without
  `ssf.runtime-configuration.read`
- **THEN** the service returns `403 service_action_forbidden` with
  `retryable: false`

### Requirement: Stable runtime-configuration errors

The mock SHALL return only the seven Contract V1 stable lowercase snake_case
error codes with their assigned HTTP status and retryability.

#### Scenario: Authentication and tenant selection fail

- **WHEN** service authentication is invalid
- **THEN** the service returns `401 service_authentication_invalid` with
  `retryable: false`
- **WHEN** the Studio tenant or correlation selection is missing, invalid, or
  unknown after authentication
- **THEN** the service returns `404 tenant_not_found` with `retryable: false`

#### Scenario: Tenant and plugin access are blocked

- **WHEN** the selected mock scenario is `tenant-suspended`
- **THEN** the service returns `409 tenant_suspended` with `retryable: false`
- **WHEN** the selected mock scenario is `plugin-inactive`
- **THEN** the service returns `409 ssf_plugin_inactive` with
  `retryable: false`
- **WHEN** the selected mock scenario is `tenant-not-ready`
- **THEN** the service returns `409 ssf_tenant_not_ready` with
  `retryable: true`
- **WHEN** the selected mock scenario is `unavailable`
- **THEN** the service returns `503 runtime_configuration_unavailable` with
  `retryable: true`

### Requirement: Deterministic storage-policy and error testing

The mock SHALL provide two tenant configurations with `ask` and `disabled`
conversation-content storage policies and the documented error envelopes.

#### Scenario: Documented mock scenario has no tenant content

- **WHEN** a request selects any documented mock scenario
- **THEN** the service returns its stable V1 error envelope without tenant
  content

### Requirement: Protected internal mock exposure

The mock MUST publish `http://127.0.0.1:8010` only when an operator explicitly
enables its `studio-mock` Compose profile. It MUST NOT publish a Traefik route
or accept an unauthenticated runtime-configuration request.

#### Scenario: Explicit profile startup

- **WHEN** an operator starts Docker Compose with the `studio-mock` profile
- **THEN** an internal caller can request the mock through loopback port 8010
  with the required V1 request headers
