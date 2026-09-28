## ADDED Requirements

### Requirement: Realm-derived conversation tenant

The gateway SHALL permit a user with a valid Keycloak bearer token to access
conversation operations when the token issuer maps to exactly one admitted
Studio login-directory tenant. It SHALL validate RS256 signature, issuer,
audience, expiry, and a non-empty subject. It SHALL derive tenant identity
only from that verified issuer-directory mapping, regardless of any legacy
tenant, role, or authorization-revision attributes in the user token.

#### Scenario: Attribute-free admitted user

- **WHEN** a user presents a valid token from an admitted tenant realm without
  `ssf-user`, `studio_tenant_id`, `ssf_authorization_revision`,
  `ssf_permissions`, or `ssf_roles`
- **THEN** the user can access that tenant's conversation operations

#### Scenario: Untrusted tenant selector

- **WHEN** a valid user token or request carries a tenant selector for another tenant
- **THEN** the gateway ignores a token's legacy selector and rejects a request-side selector

#### Scenario: Invalid or ambiguous identity

- **WHEN** the token is invalid, the subject is empty, or the issuer maps to
  zero or multiple admitted tenants
- **THEN** the gateway denies conversation access

### Requirement: Separate operational privileges

The gateway SHALL retain an explicit privileged-role check for feedback
reading and telemetry probing independently of conversation admission.

#### Scenario: Ordinary tenant user

- **WHEN** a valid conversation user without the privileged role requests
  feedback reads or telemetry probing
- **THEN** the gateway responds with 403

### Requirement: Runtime tenant integrity

The gateway SHALL fetch runtime configuration for the issuer-derived tenant
and SHALL reject a configuration naming a different tenant. It SHALL NOT
compare a user-token authorization revision with the configuration revision.

#### Scenario: Different historical revision

- **WHEN** the runtime configuration names the derived tenant but its
  authorization revision differs from a historical user-token value
- **THEN** the gateway may use that configuration for the conversation
