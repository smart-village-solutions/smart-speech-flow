## MODIFIED Requirements

### Requirement: Studio-provisioned tenant identity baseline

The system SHALL authorize administrative access only for users in a listed
tenant realm with the realm role `ssf-user`, expected audience, and signed
`ssf_authorization_revision`; Studio SHALL own the tenant realm and identity
lifecycle. The tenant is identified by the realm that issued the token.

#### Scenario: Operator grants staff access

- **WHEN** Studio completes tenant provisioning and assigns `ssf-user` to an
  administrative user
- **THEN** that user can authenticate and obtain a token containing the
  required audience, role, and authorization revision

#### Scenario: Tenant is not ready

- **WHEN** the realm, public client, claims, roles, or SSF tenant baseline is
  incomplete or the tenant is suspended
- **THEN** Studio omits that tenant from the login directory

### Requirement: Gateway enforcement of administrative authorization

The API gateway SHALL require a valid bearer token issued by a tenant realm in
the currently validated Studio directory for every endpoint under
`/api/admin/**`, and SHALL validate its signature, issuer, audience, expiry,
`ssf-user` role, and signed authorization revision before processing the
request.

#### Scenario: Request has no usable credentials

- **WHEN** a request to `/api/admin/**` has no bearer token, an expired token,
  an invalid signature, a stale or unexpected issuer, an unexpected audience,
  a missing or malformed authorization revision, or a tenant claim that
  disagrees with the issuer realm
- **THEN** the gateway returns HTTP 401
- **AND THEN** it does not invoke the administrative operation

#### Scenario: Request carries only the retired legacy header

- **WHEN** a request to `/api/admin/**` carries `X-SSF-Legacy-Access` and no
  valid bearer token, whether or not the retired
  `SSF_ENABLE_LEGACY_ADMIN_ACCESS` variables are still set
- **THEN** the gateway returns HTTP 401
- **AND THEN** it does not invoke the administrative operation

#### Scenario: Authenticated user lacks staff role

- **WHEN** a request to `/api/admin/**` has a valid token without `ssf-user`
- **THEN** the gateway returns HTTP 403
- **AND THEN** it does not invoke the administrative operation

#### Scenario: Authorized staff request

- **WHEN** a request to `/api/admin/**` has a valid token containing
  `ssf-user`
- **THEN** the gateway processes the requested administrative operation

## ADDED Requirements

### Requirement: Token-safe rejection reason codes

The API gateway SHALL record every rejected bearer token server-side with
exactly one structured log entry carrying a reason code from a closed set, the
HTTP status and the request correlation ID, and SHALL count it by reason. It
SHALL NOT log token contents or claims, and SHALL NOT change the client
response.

#### Scenario: Token lacks the authorization revision

- **WHEN** a token from a listed realm has no `ssf_authorization_revision`
- **THEN** the client receives the neutral HTTP 401 body
- **AND THEN** the gateway logs reason `revision_missing` with the correlation
  ID and increments `gateway_auth_rejections_total{reason="revision_missing"}`

#### Scenario: Caller supplies a correlation ID

- **WHEN** a rejected request carries a well-formed `X-Correlation-Id`
- **THEN** the log entry carries that correlation ID
- **AND THEN** a malformed `X-Correlation-Id` is replaced by a generated one
  without changing the response status

### Requirement: Reviewed SSF realm contract

The repository SHALL contain a reviewed realm artifact stating what a tenant
realm must provide for the gateway: a public PKCE `ssf-frontend` client with
`/login/*` redirects, the `ssf-frontend` audience, an access-token
`ssf_authorization_revision` claim, the `ssf-user` realm role, and a
user-profile declaration of `ssf_authorization_revision` that only
administrators may view or edit. A test SHALL fail when any of these is
missing. Production realms are provisioned by Studio and verified by a
read-only audit that judges only what would break SSF: the login client and the
tokens of users holding the required role.

#### Scenario: A required element is removed

- **WHEN** the audience mapper, the revision mapper, the `ssf-user` role, the
  `/login/*` redirect, or the admin-only revision attribute is removed from the
  artifact
- **THEN** the guard test fails naming that element

#### Scenario: A user tries to set their own revision

- **WHEN** a realm built from the artifact receives an account-console update of
  `ssf_authorization_revision` from the user
- **THEN** Keycloak rejects it and the administrator-set value is unchanged
