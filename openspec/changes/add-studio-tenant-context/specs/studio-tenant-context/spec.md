## ADDED Requirements

### Requirement: Verified realm-derived Studio tenant context

For tenant-bound authenticated operations, the SSF gateway SHALL create
exactly one immutable internal `tenant_id` context from the fully validated
user token issuer and its unique Studio login-directory entry.

#### Scenario: Admitted issuer is valid

- **WHEN** a validated user token's issuer maps to exactly one admitted tenant
- **THEN** the gateway creates a tenant context using that directory tenant ID

#### Scenario: Legacy tenant claim is absent or malformed

- **WHEN** an otherwise valid token has no `studio_tenant_id` or carries an
  absent, stale, or malformed legacy tenant claim
- **THEN** that field does not change the issuer-derived tenant or admission

#### Scenario: Issuer mapping is unknown or ambiguous

- **WHEN** the token issuer maps to zero or multiple directory tenants
- **THEN** the gateway rejects the tenant-bound operation

### Requirement: Browser tenant selectors are rejected

The SSF gateway SHALL reject tenant selectors supplied by a browser through
query parameters, JSON request bodies, request headers, or cookies on an
operation that derives a verified realm-based Studio tenant context.

#### Scenario: Request includes a browser-controlled tenant selector

- **WHEN** an authenticated request includes a tenant selector outside the
  validated token
- **THEN** the gateway rejects the request
- **AND THEN** it does not replace the issuer-derived tenant context
