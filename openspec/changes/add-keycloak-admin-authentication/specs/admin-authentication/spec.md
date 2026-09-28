## ADDED Requirements

### Requirement: Studio-controlled tenant login directory

The system SHALL obtain available administrative tenants from Studio's
tenant-unbound `GET /internal/plugins/ssf/v1/admin-login-tenants` endpoint with
its service identity, SHALL strictly validate the V1 response, and SHALL expose
only the canonical tenant ID, public display name, and realm needed by the
public login chooser through `GET /api/login/tenants`.

#### Scenario: Available tenants are returned

- **WHEN** Studio returns a valid directory containing ready SSF tenants
- **THEN** `/login` presents those tenants by public display name in German
  locale-aware alphabetical order
- **AND THEN** equal display names are ordered deterministically by tenant ID

#### Scenario: No tenant is available

- **WHEN** Studio returns a valid empty directory
- **THEN** `/login` states that no organisations are currently available
- **AND THEN** it does not offer an arbitrary or configured default realm

#### Scenario: Directory cannot be trusted

- **WHEN** Studio is unavailable beyond the bounded cache lifetime or returns
  an unsupported, malformed, duplicate, or unsafe directory
- **THEN** the system fails closed and offers a retry action without exposing
  internal response details

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

#### Scenario: Legacy administrative route is requested

- **WHEN** a browser requests `/admin` or `/admin/dev` during the transition
- **THEN** `/admin` provides the explicitly enabled temporary legacy password gate
- **AND THEN** `/admin/dev` returns the normal not-found response

#### Scenario: Staff member chooses an administrative entrypoint

- **WHEN** a browser opens the application start page
- **THEN** it provides one text link named `Login` to `/login`
- **AND THEN** it does not advertise `/admin` or the SVA Studio operator login

### Requirement: Temporary legacy administrative access

The system SHALL support the legacy `/admin` password gate and
`X-SSF-Legacy-Access` header only while `SSF_ENABLE_LEGACY_ADMIN_ACCESS` is
explicitly set to `true`; this is a temporary migration mechanism and SHALL
not replace Keycloak authentication.

#### Scenario: Legacy transition is enabled

- **WHEN** `SSF_ENABLE_LEGACY_ADMIN_ACCESS` is `true` and an administrative
  request contains the configured legacy access value
- **THEN** the gateway processes the administrative operation

#### Scenario: Legacy transition is disabled

- **WHEN** `SSF_ENABLE_LEGACY_ADMIN_ACCESS` is absent or not `true`
- **THEN** a request using only `X-SSF-Legacy-Access` receives HTTP 401

### Requirement: Studio-provisioned tenant identity baseline

The system SHALL authorize conversation access for active regular users with a
valid token from a listed tenant realm and the expected audience, without
requiring `ssf-user`, `studio_tenant_id`, or `ssf_authorization_revision`.
Studio SHALL own the tenant realm and identity lifecycle.

#### Scenario: Operator grants staff access

- **WHEN** Studio admits a tenant realm and an active regular user authenticates
- **THEN** that user can obtain a token with the required audience and access
  only that tenant's conversations

#### Scenario: Tenant is not ready

- **WHEN** the realm, public client, or tenant runtime baseline is incomplete
  or the tenant is suspended
- **THEN** Studio omits that tenant from the login directory

### Requirement: Gateway enforcement of administrative authorization

The API gateway SHALL require a valid bearer token issued by a tenant realm in
the currently validated Studio directory for every endpoint under
`/api/admin/**`, and SHALL validate its signature, issuer, audience, expiry,
and non-empty subject. It SHALL derive the tenant from the verified issuer's unique
directory entry before processing a conversation request. Non-conversation
administrative privileges SHALL remain separately authorized.

#### Scenario: Request has no usable credentials

- **WHEN** a request to `/api/admin/**` has no bearer token, an expired token,
  an invalid signature, a stale or unexpected issuer, an unexpected audience,
  or an issuer without a unique directory tenant
- **THEN** the gateway returns HTTP 401
- **AND THEN** it does not invoke the administrative operation

#### Scenario: Authenticated user lacks legacy staff role

- **WHEN** a conversation request has a valid token without `ssf-user`
- **THEN** the gateway permits tenant-scoped conversation operations but
  denies separately privileged operations

#### Scenario: Authorized conversation request

- **WHEN** a request to a conversation endpoint has a valid token from an
  admitted tenant realm
- **THEN** the gateway processes the request within that tenant

### Requirement: Token handling and logout

The frontend SHALL keep Keycloak access and refresh tokens in memory only,
refresh an access token before an administrative API request when necessary,
and return to the application start page after logout or unrecoverable refresh
failure.

#### Scenario: Administrative API call requires token refresh

- **WHEN** an authenticated user starts an administrative API request with an
  access token near expiry
- **THEN** the frontend refreshes the token before sending the request
- **AND THEN** includes the current token in the Authorization header

#### Scenario: Refresh can no longer establish a session

- **WHEN** token refresh fails because the Keycloak session is unavailable or
  expired
- **THEN** the frontend clears its in-memory authentication state
- **AND THEN** returns the user to `/login`

### Requirement: Customer-flow isolation

The system SHALL leave customer, QR-code, session activation, conversation,
and their supporting API routes unauthenticated by the administrative Keycloak
integration.

#### Scenario: Customer uses a QR join link

- **WHEN** a customer opens a valid `/join/:sessionId` link without a Keycloak
  session
- **THEN** the application continues into the existing customer language and
  activation flow without an administrative login redirect
