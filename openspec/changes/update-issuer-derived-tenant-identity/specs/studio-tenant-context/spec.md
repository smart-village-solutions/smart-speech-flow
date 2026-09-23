## MODIFIED Requirements

### Requirement: Signed Studio tenant context

For tenant-bound authenticated operations, the SSF gateway SHALL create
exactly one immutable internal `tenant_id` context from the Studio login
directory entry whose realm issued the fully validated user token. A
`studio_tenant_id` claim SHALL NOT be required and SHALL NOT be a source of the
tenant context.

#### Scenario: Token from a listed realm carries no tenant claim

- **WHEN** a validated user token was issued by the realm of directory tenant
  `tenant-kassel` and contains no `studio_tenant_id`
- **THEN** the gateway creates a tenant context with `tenant_id`
  `tenant-kassel`

#### Scenario: Tenant claim agrees with the issuer

- **WHEN** a validated user token contains `studio_tenant_id` equal to the
  directory tenant of its issuer
- **THEN** the gateway creates the tenant context of that directory tenant

#### Scenario: Tenant claim disagrees with the issuer

- **WHEN** a validated user token contains a `studio_tenant_id` that differs
  from the directory tenant of its issuer, or is not a string
- **THEN** the gateway rejects the token with HTTP 401

#### Scenario: Legacy tenant claim is present

- **WHEN** a validated user token contains a legacy tenant-claim alias
- **THEN** the gateway rejects the tenant-bound operation
