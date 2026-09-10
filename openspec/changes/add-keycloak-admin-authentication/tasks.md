## 1. Keycloak and deployment configuration

- [ ] 1.1 Verify Studio provisions every listed tenant realm with client
  `ssf-frontend`, role `ssf-user`, and signed tenant-context claims without
  sharing users or secrets with SSF.
- [ ] 1.2 Verify each client is public with Standard Flow and PKCE S256;
  restrict `/login/*` redirect URIs and web origin to the frontend production
  origin; keep implicit flow and direct-access grants disabled.
- [ ] 1.3 Replace the fixed-realm frontend and gateway OIDC settings with the
  trusted Keycloak base URL, public client ID, audience, role, and cache
  settings; retain the documented temporary legacy switch.
- [ ] 1.4 Provision rollout administrators in at least two tenant realms and
  record a non-secret production verification procedure.

## 1a. Studio tenant-login directory

- [ ] 1a.1 Add a strict client for
  `GET /internal/plugins/ssf/v1/admin-login-tenants` using the injected Studio
  service-token provider and correlation IDs.
- [ ] 1a.2 Validate contract version, directory revision, tenant IDs, public
  names, realm identifiers, uniqueness, and stable Studio errors.
- [ ] 1a.3 Add public read-only `GET /api/login/tenants`, returning only the
  validated directory fields and never exposing the service token.
- [ ] 1a.4 Add bounded caching and fail closed after cached directory data
  expires.

## 1b. Node 24 LTS toolchain

- [ ] 1b.1 Declare Node 24 LTS as the frontend development requirement.
- [ ] 1b.2 Upgrade the frontend Docker builder and relevant CI jobs to Node 24.
- [ ] 1b.3 Reinstall dependencies and verify the frontend test suite under
  Node 24.

## 2. API gateway authorization

- [ ] 2.1 Add typed Keycloak/OIDC configuration for the trusted base URL,
  audience, public client ID, role, discovery, JWKS, and directory cache
  settings.
- [ ] 2.2 Implement an allowlisted multi-realm FastAPI dependency that validates
  bearer-JWT signature, issuer, audience, expiry, the `ssf-user` realm role,
  and the realm-to-`studio_tenant_id` binding.
- [ ] 2.3 Apply the dependency to every `/api/admin/**` operation without
  changing customer-facing routes.
- [ ] 2.4 Add unit and integration tests for two allowed realms, unknown and
  stale issuers, tenant mismatch, 401 missing/invalid credentials, 403 missing
  role, and successful tenant-bound access.

## 3. Frontend OIDC integration

- [ ] 3.1 Refactor `keycloak-js` initialization to accept only a tenant and realm
  resolved from the validated directory while preserving in-memory tokens.
- [ ] 3.2 Add the alphabetically sorted tenant chooser at `/login` and the
  tenant-qualified login/dashboard route at `/login/:tenantId`; retain
  `AdminLoginScreen` and `useAdminAuth` at `/admin` only for the transition.
- [ ] 3.3 Attach refreshed access tokens to administrative API requests; handle
  refresh failure and realm logout, and return to `/login`.
- [x] 3.4 Remove `VITE_ADMIN_DEV_ENTRY` and `/admin/dev`; retain the simulated
  legacy login and `VITE_APP_PASSWORD` only for the explicitly enabled transition.
- [ ] 3.5 Add frontend tests for directory loading, German sorting, empty and
  retry states, tenant selection, existing realm sessions, redirects,
  callbacks, unknown tenants, logout, the legacy transition, and 404 for
  `/admin/dev`.
- [ ] 3.6 Replace the start-page administrative links with the single `Login`
  text link to `/login`; do not advertise `/admin` or SVA Studio.

## 4. Verification and documentation

- [ ] 4.1 Run frontend lint, type checks, and focused frontend tests.
- [ ] 4.2 Run gateway formatting/type checks and focused authorization tests.
- [ ] 4.3 Verify production-like login, logout, authorized and denied requests,
  cross-tenant isolation for at least two realms, and unchanged customer/QR-code
  flow.
- [ ] 4.4 Update operator documentation for Studio-managed staff identities,
  directory readiness, and authentication rollout testing.
