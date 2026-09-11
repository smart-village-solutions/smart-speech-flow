## ADDED Requirements

### Requirement: Signed Studio tenant context

For tenant-bound authenticated operations, the SSF gateway SHALL create
exactly one immutable internal `tenant_id` context from the canonical
`studio_tenant_id` claim of a fully validated Studio-issued user token.

#### Scenario: Canonical tenant claim is valid

- **WHEN** a validated user token contains one well-formed `studio_tenant_id`
- **THEN** the gateway creates a tenant context with the same value as its
  internal `tenant_id`

#### Scenario: Canonical tenant claim is absent or malformed

- **WHEN** a validated user token has no `studio_tenant_id` or its value is not
  a supported tenant identifier
- **THEN** the gateway rejects the tenant-bound operation

#### Scenario: Legacy or conflicting tenant claim is present

- **WHEN** a validated user token contains a legacy tenant-claim alias, with or
  without the canonical claim
- **THEN** the gateway rejects the tenant-bound operation

### Requirement: Browser tenant selectors are rejected

The SSF gateway SHALL reject tenant selectors supplied by a browser through
query parameters, JSON request bodies, request headers, or cookies on an
operation that derives a signed Studio tenant context.

#### Scenario: Request includes a browser-controlled tenant selector

- **WHEN** an authenticated request includes a tenant selector outside the
  validated token
- **THEN** the gateway rejects the request
- **AND THEN** it does not replace the signed tenant context
