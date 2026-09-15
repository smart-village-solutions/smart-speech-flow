## ADDED Requirements

### Requirement: Tenant-bound runtime authorization gate

For an authenticated tenant-bound runtime operation, SSF SHALL derive both
`tenant_id` and `authorization_revision` only from the fully validated Studio
user token, fetch the configuration through the existing V1 client, and return
it only when its `tenant.id` and `authorizationRevision` match that trusted
context.

#### Scenario: Matching tenant and authorization revision

- **WHEN** a validated token contains a valid `studio_tenant_id` and
  `ssf_authorization_revision` and Studio returns matching V1 configuration
- **THEN** SSF returns one validated runtime configuration bound to that tenant

#### Scenario: Missing or mismatching authorization revision

- **WHEN** the token has no valid `ssf_authorization_revision` or Studio
  returns a different `authorizationRevision`
- **THEN** SSF rejects the runtime operation
- **AND THEN** it does not produce fallback configuration

#### Scenario: Cross-tenant response

- **WHEN** Studio returns a configuration whose `tenant.id` differs from the
  trusted token tenant
- **THEN** SSF rejects the runtime operation
- **AND THEN** it does not apply the returned configuration

### Requirement: Correlated reusable runtime dependency

SSF SHALL provide authenticated downstream code with a reusable dependency
that returns the validated runtime configuration and its correlation ID. It
MUST forward a valid incoming `X-Correlation-Id` or generate one when absent.

#### Scenario: Valid incoming correlation ID

- **WHEN** an authenticated runtime operation supplies a valid correlation ID
- **THEN** SSF forwards that value to Studio and returns it with the validated
  configuration

#### Scenario: Studio failure

- **WHEN** the token provider or Studio client fails
- **THEN** the dependency fails closed with a safe classified failure
- **AND THEN** it does not return a fallback configuration
