## Context

Keycloak 26.7.2 is already deployed at `https://auth.kassel.smartspeechflow.de`.
The frontend is served at `https://translate.smart-village.solutions` and the
API gateway at `https://ssf.smart-village.solutions`. The frontend currently
uses a build-time password and `sessionStorage` only as an administrative gate;
the gateway accepts unauthenticated `/api/admin/**` requests.

## Goals / Non-Goals

### Goals

- Authenticate administrative staff through Keycloak and authorize them with
  the `ssf-user` realm role.
- Protect all REST endpoints under `/api/admin/**` at the gateway.
- Use a browser-safe OIDC flow and avoid persisting access or refresh tokens.
- Preserve every customer, QR-code, session, and conversation flow.
- Make Keycloak client and role configuration reproducible in deployment.

### Non-Goals

- Self-service registration, password reset customization, or in-product user
  management.
- Mandatory multi-factor authentication in this release.
- Protecting customer-facing API routes or WebSocket endpoints.
- Introducing a backend-for-frontend or cookie session architecture.

## Decisions

### OIDC client and browser flow

Create realm `ssf` with a public client `ssf-frontend`. Configure Authorization
Code Flow with PKCE S256, disable implicit flow and direct-access grants, and
allow only the exact production redirect URI and web origin for
`https://translate.smart-village.solutions`. The React app uses `keycloak-js`;
tokens remain in memory, are refreshed before protected calls, and are attached
as bearer tokens by the shared HTTP client.

`/login` initializes the login-required flow and becomes the only staff entry.
The application returns to `/login` after authentication. `/admin` and
`/admin/dev` are deleted rather than redirected.

### Authorization at the gateway

Implement a reusable FastAPI dependency that extracts the bearer token, obtains
the issuer metadata and JWKS from Keycloak with bounded caching, validates
signature, issuer, audience, expiry, and required realm role `ssf-user`.
Apply it to every router operation under `/api/admin/**`. Missing or invalid
credentials return 401; a valid token without `ssf-user` returns 403.

The frontend role check is only a UX aid. Gateway validation is the
authoritative authorization decision.

### Identity administration

Administrators manually create users and assign `ssf-user` in the Keycloak
Admin Console. No Keycloak administrator credentials, frontend client secrets,
or user credentials are stored in application configuration. MFA remains
optional at the Keycloak policy level and is not enabled as a release
requirement.

### Provisioning and rollout

Store a versioned Keycloak realm import/export containing the realm, client,
role, flows, redirect URI, and web-origin configuration. It contains no users
or secrets. Deployment config supplies only public OIDC values to the frontend
and expected issuer, audience/client ID, and role to the gateway.

Before rollout, an operator creates and tests at least one `ssf-user` account.
Deploy gateway authorization before the frontend release and verify login,
authorized admin calls, rejected unauthorized calls, logout, and unaffected
customer access. Rollback restores the previously deployed frontend and gateway
images together; Keycloak realm configuration is retained because it is
additive and inert to the old software.

## Risks / Trade-offs

- A pure SPA holds tokens in memory. This avoids persistent-token exposure but
  requires a Keycloak redirect after a full page reload when no SSO session is
  usable.
- Keycloak availability becomes a dependency for starting a new admin session.
  Cached JWKS lets already issued tokens be verified during a short discovery
  outage, subject to their expiry.
- API clients that formerly called `/api/admin/**` without credentials will be
  rejected. This is an intentional security change.

## Open Questions

None.
