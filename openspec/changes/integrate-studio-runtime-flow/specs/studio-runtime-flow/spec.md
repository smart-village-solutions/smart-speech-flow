## ADDED Requirements

### Requirement: Tenant-bound runtime authorization gate

For an authenticated tenant-bound runtime operation, SSF SHALL derive
`tenant_id` from the fully validated token issuer and unique Studio login
directory entry, fetch the configuration through the existing V1 client, and
return it only when its `tenant.id` matches that trusted tenant. Runtime
authorization and configuration revisions remain service-contract metadata,
not user-token admission criteria.

#### Scenario: Matching tenant

- **WHEN** a valid user token maps to a tenant and Studio returns matching V1
  configuration
- **THEN** SSF returns one validated runtime configuration bound to that tenant

#### Scenario: Legacy user revision is absent or stale

- **WHEN** the token has no `ssf_authorization_revision` or its value differs
  from Studio's runtime `authorizationRevision`
- **THEN** that user-token field does not block a matching-tenant configuration

#### Scenario: Cross-tenant response

- **WHEN** Studio returns a configuration whose `tenant.id` differs from the
  issuer-derived tenant
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
