## 1. Keycloak and deployment configuration

- [ ] 1.1 Add a versioned realm provisioning artifact for realm `ssf`, client
  `ssf-frontend`, and role `ssf-user` without users or secrets.
- [ ] 1.2 Configure the client as public with Standard Flow and PKCE S256;
  restrict redirect URI and web origin to the frontend production origin; keep
  implicit flow and direct-access grants disabled.
- [x] 1.3 Add documented, non-secret frontend and gateway OIDC environment
  configuration and document the temporary legacy frontend password configuration.
- [ ] 1.4 Manually create a rollout administrator with the `ssf-user` role and
  record a non-secret production verification procedure.

## 1a. Node 24 LTS toolchain

- [ ] 1a.1 Declare Node 24 LTS as the frontend development requirement.
- [ ] 1a.2 Upgrade the frontend Docker builder and relevant CI jobs to Node 24.
- [ ] 1a.3 Reinstall dependencies and verify the frontend test suite under
  Node 24.

## 2. API gateway authorization

- [ ] 2.1 Add a typed Keycloak/OIDC configuration model for issuer, audience,
  role, discovery, and JWKS cache settings.
- [ ] 2.2 Implement a reusable FastAPI dependency that validates bearer-JWT
  signature, issuer, audience, expiry, and the `ssf-user` realm role.
- [ ] 2.3 Apply the dependency to every `/api/admin/**` operation without
  changing customer-facing routes.
- [ ] 2.4 Add unit and integration tests for 401 missing/invalid credentials,
  403 missing role, and successful authorized access.

## 3. Frontend OIDC integration

- [ ] 3.1 Add and configure `keycloak-js` before React Router initialization.
- [x] 3.2 Add an in-memory Keycloak session integration at `/login` while
  retaining `AdminLoginScreen` and `useAdminAuth` at `/admin` for the transition.
- [x] 3.3 Attach refreshed access tokens to administrative API requests; handle
  refresh failure, logout, and return to the start page.
- [x] 3.4 Remove `VITE_ADMIN_DEV_ENTRY` and `/admin/dev`; retain the simulated
  legacy login and `VITE_APP_PASSWORD` only for the explicitly enabled transition.
- [x] 3.5 Add frontend tests for the legacy transition, authorized admin access,
  logout handling, and 404 for `/admin/dev`.

## 4. Verification and documentation

- [ ] 4.1 Run frontend lint, type checks, and focused frontend tests.
- [ ] 4.2 Run gateway formatting/type checks and focused authorization tests.
- [ ] 4.3 Verify production-like login, logout, authorized and denied admin
  requests, and unchanged customer/QR-code flow.
- [ ] 4.4 Update operator documentation for manually managing `ssf-user`
  accounts and testing the authentication rollout.
