## ADDED Requirements

### Requirement: Administrative OIDC login

The system SHALL authenticate administrative staff at `/login` through the
Keycloak realm `ssf` and the public OIDC client `ssf-frontend` using
Authorization Code Flow with PKCE S256.

#### Scenario: Unauthenticated staff member opens the login route

- **WHEN** an unauthenticated browser requests `/login`
- **THEN** the frontend redirects it to the configured Keycloak login flow
- **AND THEN** returns it to `/login` only after successful authentication

#### Scenario: Legacy administrative route is requested

- **WHEN** a browser requests `/admin` or `/admin/dev`
- **THEN** `/admin` provides the temporary legacy password gate
- **AND THEN** `/admin/dev` returns the normal not-found response

#### Scenario: Staff member chooses an administrative entrypoint

- **WHEN** a browser opens the application start page during the transition
- **THEN** it provides links to both `/login` and `/admin`

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

### Requirement: Manual staff identity management

The system SHALL authorize administrative access only for Keycloak users with
the realm role `ssf-user`; user lifecycle and role assignment SHALL be managed
manually in Keycloak for this release.

#### Scenario: Operator grants staff access

- **WHEN** an operator creates or updates a user in Keycloak and assigns
  `ssf-user`
- **THEN** that user can authenticate and obtain a token containing the
  required authorization role

### Requirement: Gateway enforcement of administrative authorization

The API gateway SHALL require a valid bearer token issued by the configured
Keycloak realm for every endpoint under `/api/admin/**`, and SHALL validate its
signature, issuer, audience, expiry, and `ssf-user` role before processing the
request.

#### Scenario: Request has no usable credentials

- **WHEN** a request to `/api/admin/**` has no bearer token, an expired token,
  an invalid signature, or an unexpected issuer or audience
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
- **AND THEN** returns the user to the application start page

### Requirement: Customer-flow isolation

The system SHALL leave customer, QR-code, session activation, conversation,
and their supporting API routes unauthenticated by the administrative Keycloak
integration.

#### Scenario: Customer uses a QR join link

- **WHEN** a customer opens a valid `/join/:sessionId` link without a Keycloak
  session
- **THEN** the application continues into the existing customer language and
  activation flow without an administrative login redirect
