## Context

Keycloak is deployed behind one trusted public base URL, while each Studio
tenant has its own realm. The frontend is served at `https://dialog.kassel.de`.
It currently uses a build-time password and `sessionStorage` only as an
administrative gate; the gateway accepts unauthenticated `/api/admin/**`
requests. SVA Studio is the authoritative control plane for tenant identity,
realm provisioning, and readiness.

## Goals / Non-Goals

### Goals

- Authenticate administrative staff through Keycloak and authorize them with
  the `ssf-user` realm role.
- Let staff select an available organisation at `/login` before starting the
  correct tenant-realm login.
- Protect all REST endpoints under `/api/admin/**` at the gateway.
- Use a browser-safe OIDC flow and avoid persisting access or refresh tokens.
- Preserve every customer, QR-code, session, and conversation flow.
- Make Keycloak client and role configuration reproducible in deployment.
- Bind every authenticated operation to the canonical Studio tenant ID.

### Non-Goals

- Self-service registration, password reset customization, or in-product user
  management.
- Mandatory multi-factor authentication in this release.
- Protecting customer-facing API routes or WebSocket endpoints.
- Introducing a backend-for-frontend or cookie session architecture.
- Defining the future behavior of `/admin` or exposing the SVA Studio operator
  login on the SSF start page.

## Decisions

### Studio tenant-login directory

The gateway calls
`GET /internal/plugins/ssf/v1/admin-login-tenants` with its service token and a
correlation ID. Studio returns contract version `1.0`, a SHA-256 directory
revision, and entries containing the immutable Studio tenant ID, public display
name, and provisioned realm. Studio includes only non-root, SSF-ready tenants.
The gateway strictly validates the complete response and exposes only validated
directory fields through `GET /api/login/tenants` to the public `/login` page.
Credentials remain server-side.

### OIDC client and browser flow

Studio provisions the public client `ssf-frontend` and realm role `ssf-user` in
every listed tenant realm. Configure Authorization Code Flow with PKCE S256,
disable implicit flow and direct-access grants, and allow only the exact
production web origin and required `/login/*` redirects for
`https://dialog.kassel.de`. Tokens include the signed canonical
`studio_tenant_id` and `ssf_authorization_revision` claims.

`/login` becomes the only visible staff entry and shows the tenant directory in
German locale-aware alphabetical order. Selection navigates through the stable
Studio tenant ID at `/login/:tenantId`; the application resolves the associated
realm only from the validated directory and initializes `keycloak-js`. A usable
realm session opens the conversation dashboard directly, otherwise Keycloak
prompts for login and returns to the tenant-qualified route. Tokens remain in
memory and are attached as bearer tokens only to administrative requests.

`/admin` receives no start-page link and remains only as the explicitly enabled
temporary legacy gate. Its future replacement is outside this change.

### Authorization at the gateway

Implement a reusable FastAPI dependency that extracts the bearer token and
admits an issuer only when it exactly matches the trusted Keycloak base URL plus
a realm in a currently validated Studio directory. Only then obtain discovery
metadata and JWKS with bounded caching and validate signature, issuer, audience,
expiry, and required realm role `ssf-user`. The signed `studio_tenant_id` must
match the Studio tenant mapped to the issuer realm. Apply this dependency to
every router operation under `/api/admin/**`. Missing, invalid, stale-directory,
or tenant-mismatched credentials return 401; a valid token without `ssf-user`
returns 403.

The frontend role check is only a UX aid. Gateway validation is the
authoritative authorization decision.

### Identity administration

Tenant administrators manage users and assignments through Studio's tenant IAM
flow. No Keycloak administrator credentials, frontend client secrets, or user
credentials are stored in SSF configuration. MFA remains optional at the
Keycloak policy level and is not enabled as a release requirement.

### Provisioning and rollout

Studio owns reproducible per-tenant provisioning of realm, client, role, claims,
redirects, and web origin without sharing users or secrets with SSF. SSF
deployment config supplies the trusted Keycloak base URL, audience/client ID,
role, Studio base URL, and service-token settings.

Before rollout, Studio provisions and tests at least two tenant realms and staff
accounts. Deploy the Studio directory and gateway multi-realm authorization
before the frontend release. Verify both tenant logins, tenant isolation,
authorized and rejected calls, logout, and unaffected customer access. Rollback
restores the previous frontend and gateway images; additive Studio and Keycloak
configuration is retained.

## Risks / Trade-offs

- A pure SPA holds tokens in memory. This avoids persistent-token exposure but
  requires a Keycloak redirect after a full page reload when no SSO session is
  usable.
- Keycloak availability becomes a dependency for starting a new admin session.
  Cached JWKS lets already issued tokens be verified during a short discovery
  outage, subject to their expiry.
- Studio directory availability becomes a dependency for selecting a tenant and
  admitting a realm issuer. A bounded cache supports short outages and then
  fails closed.
- API clients that formerly called `/api/admin/**` without credentials will be
  rejected. This is an intentional security change.

## Open Questions

None.
