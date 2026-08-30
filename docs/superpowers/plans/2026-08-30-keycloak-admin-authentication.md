# Keycloak Admin Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the simulated frontend administration password with Keycloak OIDC login at `/login` and enforce the `ssf-user` role at every `/api/admin/**` endpoint.

**Architecture:** A public Keycloak client uses Authorization Code Flow plus PKCE for the React SPA. The gateway validates bearer JWTs through Keycloak discovery and JWKS before any administrative route is invoked; customer routes are unchanged.

**Tech Stack:** Keycloak 26.7.2, `keycloak-js`, React 19/TypeScript/Vitest, FastAPI, PyJWT with cryptography, pytest, Docker Compose.

**Spec:** `openspec/changes/add-keycloak-admin-authentication/{proposal.md,design.md,specs/admin-authentication/spec.md}`

## Global Constraints

- Realm is `ssf`; required realm role is exactly `ssf-user`.
- Admin entry is exactly `/login`; `/admin` and `/admin/dev` must remain unregistered.
- Client is public, uses Standard/Authorization Code Flow with PKCE S256, and has no client secret.
- Tokens remain in browser memory and are sent only to administrative API endpoints.
- Customer and QR-code flows remain unauthenticated by this change.
- Node 24 LTS is required for frontend development, CI, and the builder image;
  the Nginx runtime image remains unchanged.

---

### Task 0: Upgrade the frontend toolchain to Node 24 LTS

**Files:**
- Create: `.nvmrc`
- Modify: `services/frontend/package.json`
- Modify: `services/frontend/Dockerfile`
- Modify: `.github/workflows/code-quality.yml`
- Modify: `.github/workflows/project-report-pages.yml`
- Modify: `services/frontend/DEPLOYMENT.md`

**Interfaces:**
- Produces one declared Node runtime version (`24`) for local development, CI,
  and the frontend build stage; the final Nginx image is not changed.

- [ ] **Step 1: Reproduce the runtime incompatibility under Node 20**

Run: `npm --prefix services/frontend test -- src/core/http/__tests__/client.test.ts`

Expected: Vitest workers fail before loading tests because `jsdom@30` requires
the unavailable `util.markAsUncloneable` Node API.

- [ ] **Step 2: Declare and apply Node 24 LTS**

Add `.nvmrc` containing `24`, add `engines.node: ">=24 <25"` to the frontend
package, change the Docker builder and all frontend/report CI setup-node values
from 22 to 24, and update deployment documentation.

- [ ] **Step 3: Reinstall and verify under Node 24**

Run `npm ci` using Node 24, then run the focused frontend test from Step 1.

Expected: Vitest starts and executes the test successfully.

---

### Task 1: Provision a reproducible Keycloak client

**Files:**
- Create: `deploy/production/keycloak/ssf-realm.json`
- Modify: `deploy/production/docker-compose.production.yml`
- Modify: `deploy/production/production.env.example`

**Interfaces:**
- Produces realm `ssf`, client `ssf-frontend`, role `ssf-user`, and public configuration values consumed by Tasks 2 and 3.

- [ ] **Step 1: Add a failing deployment configuration test**

Add `tests/operations/test_keycloak_realm.py` that loads the realm JSON and asserts the observable configuration: realm name `ssf`, a client id `ssf-frontend`, `publicClient: true`, `standardFlowEnabled: true`, `implicitFlowEnabled: false`, `directAccessGrantsEnabled: false`, PKCE `S256`, exact frontend redirect URI/web origin, and a realm role named `ssf-user`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/operations/test_keycloak_realm.py -q`

Expected: FAIL because the realm export does not exist.

- [ ] **Step 3: Add the realm export and import mount**

Create the no-secret realm JSON. Mount it into Keycloak and enable startup import in the production compose service. Add public OIDC frontend variables and gateway issuer/audience/role variables to the example environment file.

- [ ] **Step 4: Run the focused test**

Run: `pytest tests/operations/test_keycloak_realm.py -q`

Expected: PASS.

### Task 2: Enforce Keycloak JWT authorization in the gateway

**Files:**
- Create: `services/api_gateway/auth.py`
- Create: `services/api_gateway/tests/test_auth.py`
- Modify: `services/api_gateway/requirements.in`
- Modify: `services/api_gateway/routes/admin.py`

**Interfaces:**
- Produces `require_ssf_user(request: Request) -> dict[str, object]`, an async FastAPI dependency that raises 401 or 403.
- Consumes `KEYCLOAK_ISSUER`, `KEYCLOAK_AUDIENCE`, and `KEYCLOAK_REQUIRED_ROLE` environment variables.

- [ ] **Step 1: Write failing gateway authorization tests**

Add tests that sign RS256 fixtures with a local private key and mock the discovery/JWKS HTTP response. Assert `/api/admin/session/history` returns 401 for no token, invalid issuer/audience/signature, 403 for a valid token without `ssf-user`, and 200 for a valid token with `realm_access.roles: ["ssf-user"]`. Assert `/api/customer/session/activate` remains reachable without a bearer token.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest services/api_gateway/tests/test_auth.py -q`

Expected: protected admin endpoint currently accepts missing credentials.

- [ ] **Step 3: Implement minimal validation dependency**

Add `PyJWT[crypto]` to `requirements.in`. Implement cached discovery/JWKS retrieval, bearer extraction, RS256 signature plus issuer/audience/expiry validation, and realm-role enforcement. Register it as a router-level dependency for `/api/admin`.

- [ ] **Step 4: Run focused gateway tests**

Run: `pytest services/api_gateway/tests/test_auth.py services/api_gateway/tests/test_admin.py -q`

Expected: PASS.

### Task 3: Add in-memory Keycloak authentication to the frontend

**Files:**
- Create: `services/frontend/src/app/auth/keycloak.ts`
- Create: `services/frontend/src/app/auth/AuthProvider.tsx`
- Create: `services/frontend/src/app/auth/__tests__/AuthProvider.test.tsx`
- Modify: `services/frontend/package.json`
- Modify: `services/frontend/src/app/config/env.ts`
- Modify: `services/frontend/src/app/providers/AppProviders.tsx`
- Modify: `services/frontend/src/core/http/client.ts`
- Modify: `services/frontend/src/core/http/__tests__/client.test.ts`

**Interfaces:**
- Produces `useAuth()` with `ready`, `authenticated`, `getAccessToken()`, and `logout()`.
- `createHttpClient(config, getLocale, getAdminAccessToken)` attaches the token only when `request.url` starts with `/api/admin/`.

- [ ] **Step 1: Write failing frontend tests**

Mock the external Keycloak adapter at its network boundary. Test that the provider initializes `login-required` at `/login`, does not persist tokens, redirects to logout on an explicit sign-out, and that the HTTP client sends a refreshed bearer token only on `/api/admin/**`, never on `/api/customer/**`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm --prefix services/frontend test -- src/app/auth/__tests__/AuthProvider.test.tsx src/core/http/__tests__/client.test.ts`

Expected: FAIL because no Keycloak auth provider or token-aware interceptor exists.

- [ ] **Step 3: Implement the auth boundary and interceptor**

Install `keycloak-js`, parse only non-secret OIDC settings, initialize Keycloak before routes render, retain adapter state in memory, refresh with a 30-second minimum validity, and add the Authorization header only for admin paths. On refresh failure, clear state and invoke Keycloak logout to the application origin.

- [ ] **Step 4: Run focused frontend tests**

Run: `npm --prefix services/frontend test -- src/app/auth/__tests__/AuthProvider.test.tsx src/core/http/__tests__/client.test.ts`

Expected: PASS.

### Task 4: Replace the simulated login route and assets

**Files:**
- Modify: `services/frontend/src/app/router/AppRoutes.tsx`
- Modify: `services/frontend/src/app/config/env.ts`
- Modify: `services/frontend/.env.example`
- Modify: `services/frontend/src/app/providers/services.ts`
- Modify: `services/frontend/src/domain/admin/admin.repository.ts`
- Delete: `services/frontend/src/features/admin/AdminLoginScreen.tsx`
- Delete: `services/frontend/src/features/admin/useAdminAuth.ts`
- Delete: related simulated-login tests and `services/frontend/src/ui/styles/keycloak.css`
- Modify: `services/frontend/src/ui/styles/tokens.css`
- Create: `services/frontend/src/app/router/__tests__/loginRoute.test.tsx`

**Interfaces:**
- `/login` renders the dashboard only after `useAuth().authenticated` is true.
- `/admin` and `/admin/dev` have no route and render the existing not-found page.

- [ ] **Step 1: Write failing routing tests**

Render routes with authenticated and unauthenticated auth fakes. Assert authenticated `/login` renders the dashboard, unauthenticated `/login` renders no simulated email/password form, and `/admin` renders not-found. Keep a `/join/:sessionId` assertion to prove customer routing remains available.

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm --prefix services/frontend test -- src/app/router/__tests__/loginRoute.test.tsx`

Expected: FAIL because `/login` is not registered and `/admin` still renders the former entry.

- [ ] **Step 3: Implement route and asset removal**

Replace `AdminEntry`'s password state with `useAuth`, register `/login`, remove both legacy admin routes and pseudo-login assets, remove password/dev configuration, and update comments to describe bearer authentication.

- [ ] **Step 4: Run focused frontend tests**

Run: `npm --prefix services/frontend test -- src/app/router/__tests__/loginRoute.test.tsx`

Expected: PASS.

### Task 5: Document and verify the rollout

**Files:**
- Create: `docs/operations/keycloak-admin-access.md`
- Modify: `openspec/changes/add-keycloak-admin-authentication/tasks.md`

- [ ] **Step 1: Document manual provisioning and rollout checks**

Document creation of an `ssf-user` account in Keycloak, production verification of 401/403/200 behavior, login/logout, and the unchanged QR flow. Do not record passwords or Keycloak administrator credentials.

- [ ] **Step 2: Execute final verification**

Run:

```bash
pytest tests/operations/test_keycloak_realm.py services/api_gateway/tests/test_auth.py services/api_gateway/tests/test_admin.py -q
npm --prefix services/frontend run lint
npm --prefix services/frontend run build
npm --prefix services/frontend test
openspec validate add-keycloak-admin-authentication --strict
```

- [ ] **Step 3: Update OpenSpec task checkboxes**

Mark only completed items in the change task file after the corresponding implementation and verification evidence exists.
