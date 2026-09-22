## MODIFIED Requirements

### Requirement: Tenant-selected administrative OIDC login

The system SHALL authenticate administrative staff through the selected
Studio-allowlisted tenant realm and the public OIDC client `ssf-frontend` using
Authorization Code Flow with PKCE S256.

#### Scenario: Unauthenticated staff member opens the login route

- **WHEN** an unauthenticated browser selects a tenant at `/login`
- **THEN** the frontend resolves the tenant's realm only from the validated
  Studio directory and starts that realm's Keycloak login flow
- **AND THEN** Keycloak returns it to `/login/:tenantId` after authentication

#### Scenario: Staff member already has a realm session

- **WHEN** a staff member selects a tenant for which the browser has a usable
  Keycloak session
- **THEN** the frontend opens that tenant's conversation dashboard without
  displaying another credentials form

#### Scenario: Unknown tenant route is requested

- **WHEN** a browser requests `/login/:tenantId` for an ID absent from the
  validated Studio directory
- **THEN** the frontend refuses to initialize Keycloak for any realm

#### Scenario: Retired administrative route is requested

- **WHEN** a browser requests `/admin` or `/admin/dev`
- **THEN** the frontend returns the normal not-found response
- **AND THEN** it neither offers a password form nor initializes Keycloak

#### Scenario: Staff member chooses an administrative entrypoint

- **WHEN** a browser opens the application start page
- **THEN** it provides one text link named `Login` to `/login`
- **AND THEN** it does not advertise `/admin` or the SVA Studio operator login

### Requirement: Gateway enforcement of administrative authorization

The API gateway SHALL require a valid bearer token issued by a tenant realm in
the currently validated Studio directory for every endpoint under
`/api/admin/**`, and SHALL validate its signature, issuer, audience, expiry,
`ssf-user` role, and matching signed Studio tenant context before processing the
request.

#### Scenario: Request has no usable credentials

- **WHEN** a request to `/api/admin/**` has no bearer token, an expired token,
  an invalid signature, a stale or unexpected issuer, an unexpected audience,
  or a tenant claim that does not match the issuer realm
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

## REMOVED Requirements

### Requirement: Temporary legacy administrative access

**Reason**: Tenant-aware Keycloak login is verified in production (#216). The
password was embedded in the browser bundle and was never a security control.

**Migration**: Staff use `/login` and send tenant-bound bearer tokens. Operators
may delete `SSF_ENABLE_LEGACY_ADMIN_ACCESS`, `SSF_LEGACY_ADMIN_ACCESS_CODE` and
`FRONTEND_DEMO_PASSWORD` from existing environment files; they are ignored.
