# Tenant Login Directory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let staff select an alphabetically sorted Studio tenant at `/login`, authenticate against that tenant's Keycloak realm, and enter its conversation dashboard with a cryptographically validated Studio tenant context.

**Architecture:** The gateway consumes and caches Studio's tenant-unbound login-directory contract and exposes a sanitized anonymous read endpoint to the SPA. The SPA routes by immutable Studio tenant ID, resolves the realm only from that directory, and initializes one in-memory `keycloak-js` client for the selected realm. The gateway admits JWT issuers only when they match the trusted Keycloak base URL and a currently validated Studio directory entry, then checks the signed tenant ID against that realm mapping.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, aiohttp, PyJWT, pytest, React 19, TypeScript 6, React Router 7, TanStack Query 5, keycloak-js 26, Vitest, Testing Library, MSW, Docker Compose

**Spec:** `docs/superpowers/specs/2026-09-10-tenant-login-directory-design.md`

## Global Constraints

- Preserve all pre-existing uncommitted frontend work; inspect and merge with it rather than replacing it.
- All new or modified project documentation, test names, comments, and identifiers are English.
- The only start-page staff entry is a text link named `Login` targeting `/login`; do not advertise `/admin` or SVA Studio.
- `/admin` retains only its separately switched legacy behavior during migration and is otherwise reserved for a future capability.
- The browser never receives a Studio service token and never selects a realm outside a validated Studio directory response.
- The Studio contract is `GET /internal/plugins/ssf/v1/admin-login-tenants` with `Authorization` and `X-Correlation-Id`, but no tenant selector header.
- Directory entries use exactly `id`, `displayName`, and `realm`; the response uses `contractVersion: "1.0"` and a lowercase SHA-256 `directoryRevision`.
- One SSF installation trusts exactly one Keycloak base URL and one public client ID across all tenant realms.
- OIDC uses Authorization Code Flow with PKCE S256; access and refresh tokens remain in memory.
- Signed `studio_tenant_id` and `ssf_authorization_revision` claims remain the only tenant trust boundary.
- The login change establishes and verifies the trusted tenant context but does not implement tenant-partitioned session persistence. Production enablement is blocked until `add-multi-tenant-operations` proves conversation and session isolation using that context.
- Python checks run under Python 3.12; frontend checks run under Node 24.

---

### Task 1: Implement the Studio login-directory contract client and mock

**Files:**
- Create: `services/api_gateway/studio_login_directory_client.py`
- Create: `tests/test_studio_login_directory_client.py`
- Modify: `services/studio_mock/app.py`
- Modify: `tests/test_studio_runtime_configuration_mock.py`

**Interfaces:**
- Consumes: `StudioRuntimeTokenProvider.get_token() -> Awaitable[str]` from `services/api_gateway/studio_runtime_token.py`.
- Produces: `DIRECTORY_PATH`, `StudioLoginTenant`, `StudioLoginDirectory`, `DirectoryHttpResponse`, `StudioLoginDirectoryClient.fetch(correlation_id)`, and `StudioLoginDirectoryClientError`.

- [ ] **Step 1: Write failing client contract tests**

Create `tests/test_studio_login_directory_client.py` with fixtures for this exact valid payload and a transport spy:

```python
REVISION = f"sha256:{'a' * 64}"


def valid_directory() -> dict[str, object]:
    return {
        "contractVersion": "1.0",
        "directoryRevision": REVISION,
        "tenants": [
            {
                "id": "tenant-kassel",
                "displayName": "Stadt Kassel",
                "realm": "kassel-ssf-2025",
            }
        ],
    }
```

Test that `fetch("correlation-1")` calls exactly
`https://studio.test/internal/plugins/ssf/v1/admin-login-tenants` with:

```python
{
    "Authorization": "Bearer service-token",
    "X-Correlation-Id": "correlation-1",
}
```

Also test an empty tenant array and unknown optional V1 fields.

- [ ] **Step 2: Run the new tests and verify the missing-module failure**

Run:

```bash
pytest -q tests/test_studio_login_directory_client.py
```

Expected: collection fails because `studio_login_directory_client` does not exist.

- [ ] **Step 3: Implement strict models and the success path**

Create the module with these public shapes:

```python
DIRECTORY_PATH = "/internal/plugins/ssf/v1/admin-login-tenants"
TENANT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
REALM_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
REVISION_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class StudioLoginTenant(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True, populate_by_name=True)
    id: str
    display_name: str = Field(alias="displayName", min_length=1, max_length=200)
    realm: str


class StudioLoginDirectory(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True, populate_by_name=True)
    contract_version: str = Field(alias="contractVersion", pattern=r"^1[.]0$")
    directory_revision: str = Field(alias="directoryRevision")
    tenants: list[StudioLoginTenant] = Field(max_length=10_000)
```

Add validators for the ID, realm, revision, duplicate tenant IDs, and duplicate realms. Follow the transport/error structure already used by `StudioRuntimeClient`, but send no `X-Studio-Tenant-Id` header.

- [ ] **Step 4: Add failing negative-path tests**

Parameterize mutations for unsupported contract version, malformed revision, invalid ID, unsafe realm, duplicate ID, duplicate realm, blank display name, non-object payload, and control characters in the correlation ID. Add stable error-envelope cases for:

```python
[
    (401, "service_authentication_invalid", False),
    (403, "service_action_forbidden", False),
    (503, "admin_login_directory_unavailable", True),
]
```

Assert that unexpected statuses and malformed error bodies expose only stable local error codes, never Studio response content.

- [ ] **Step 5: Implement fail-closed error handling**

Use this exception contract:

```python
class StudioLoginDirectoryClientError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool, status: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.status = status
```

Validate printable ASCII for the service token and correlation ID before transport. Map network errors to `studio_login_directory_network_error`; reject all invalid success bodies as `studio_login_directory_response_invalid`.

- [ ] **Step 6: Extend the Studio mock and its tests**

Add `GET /internal/plugins/ssf/v1/admin-login-tenants` to `services/studio_mock/app.py`. Return Kassel and Fulda entries with deterministic `directoryRevision`; reuse the mock's authorized, unauthorized, forbidden, and unavailable token/scenario behavior. Assert the endpoint requires `Authorization` and `X-Correlation-Id`, rejects tenant selector headers, and publishes its schemas in OpenAPI.

- [ ] **Step 7: Run focused tests**

Run:

```bash
pytest -q tests/test_studio_login_directory_client.py tests/test_studio_runtime_configuration_mock.py
```

Expected: all tests pass.

- [ ] **Step 8: Commit the contract client**

```bash
git add services/api_gateway/studio_login_directory_client.py services/studio_mock/app.py tests/test_studio_login_directory_client.py tests/test_studio_runtime_configuration_mock.py
git commit -m "feat(studio): consume admin login tenant directory"
```

---

### Task 2: Add bounded directory caching and the public gateway facade

**Files:**
- Create: `services/api_gateway/studio_login_directory.py`
- Create: `services/api_gateway/routes/login.py`
- Create: `tests/test_studio_login_directory.py`
- Create: `tests/test_login_directory_route.py`
- Modify: `services/api_gateway/app.py`

**Interfaces:**
- Consumes: `StudioLoginDirectoryClient.fetch(correlation_id) -> StudioLoginDirectory`.
- Produces: `StudioLoginDirectoryService.get(correlation_id)`, `get_studio_login_directory_service()`, and anonymous `GET /api/login/tenants`.

- [ ] **Step 1: Write failing cache behavior tests**

Use an injected monotonic clock and stub client. Cover first fetch, reuse within TTL, one refresh for concurrent callers, refresh after TTL, valid empty responses, and failure after expiry. Assert that a fetch failure does not extend the lifetime of stale data.

The service result remains the immutable validated model:

```python
class StudioLoginDirectoryService:
    async def get(self, correlation_id: str) -> StudioLoginDirectory:
        raise NotImplementedError
```

- [ ] **Step 2: Run cache tests and verify failure**

```bash
pytest -q tests/test_studio_login_directory.py
```

Expected: collection fails because `studio_login_directory` does not exist.

- [ ] **Step 3: Implement the cache and dependency factory**

Implement one `asyncio.Lock`, `expires_at`, and cached directory. Read:

```text
STUDIO_RUNTIME_CONFIGURATION_BASE_URL
STUDIO_LOGIN_DIRECTORY_CACHE_SECONDS (default 60, allowed 1..300)
STUDIO_LOGIN_DIRECTORY_TIMEOUT_SECONDS (default 5, allowed >0..30)
```

Build the client with the existing `StudioTokenConfig.from_env()` and
`StudioRuntimeTokenProvider.get_token`. Use `functools.lru_cache` only for the dependency factory; tests override the dependency rather than mutate the production singleton.

- [ ] **Step 4: Write failing public-route tests**

Create a minimal FastAPI test app with the login router and dependency override. Assert that the success response is exactly:

```json
{
  "tenants": [
    {
      "id": "tenant-kassel",
      "displayName": "Stadt Kassel",
      "realm": "kassel-ssf-2025"
    }
  ]
}
```

Assert no browser Authorization header is required, the incoming or generated correlation ID is passed to the service, an empty list returns 200, and every client/cache failure becomes a neutral 503 body.

- [ ] **Step 5: Implement and register the route**

Define response-only Pydantic models and the route:

```python
router = APIRouter(prefix="/api/login", tags=["login"])


@router.get("/tenants", response_model=LoginTenantDirectoryResponse)
async def list_login_tenants(
    request: Request,
    directory: Annotated[
        StudioLoginDirectoryService,
        Depends(get_studio_login_directory_service),
    ],
) -> LoginTenantDirectoryResponse:
    correlation_id = request.headers.get("X-Correlation-Id") or str(uuid4())
    result = await directory.get(correlation_id)
    return LoginTenantDirectoryResponse(tenants=result.tenants)
```

Catch only classified directory/token/configuration failures and return `HTTPException(503, "The login directory is temporarily unavailable")`. Register `login.router` in `services/api_gateway/app.py` outside the authenticated admin router.

- [ ] **Step 6: Run route and app-registration tests**

```bash
pytest -q tests/test_studio_login_directory.py tests/test_login_directory_route.py services/api_gateway/tests/test_endpoints.py
```

Expected: all tests pass and `/api/login/tenants` appears in OpenAPI without an admin auth dependency.

- [ ] **Step 7: Commit the gateway facade**

```bash
git add services/api_gateway/studio_login_directory.py services/api_gateway/routes/login.py services/api_gateway/app.py tests/test_studio_login_directory.py tests/test_login_directory_route.py
git commit -m "feat(api): expose validated login tenant directory"
```

---

### Task 3: Replace fixed-issuer validation with a Studio-allowlisted realm verifier

**Files:**
- Modify: `services/api_gateway/auth.py`
- Modify: `services/api_gateway/tenant_context.py`
- Modify: `tests/test_auth.py`
- Modify: `tests/test_tenant_context.py`

**Interfaces:**
- Consumes: `StudioLoginDirectoryService.get(correlation_id)` and each entry's `id`/`realm` mapping.
- Produces: async `require_ssf_user(request, directory) -> dict[str, Any]`; `KeycloakSettings.base_url`; unchanged `require_studio_tenant_context` contract for downstream routes.

- [ ] **Step 1: Rewrite auth fixtures for two tenant realms**

Define:

```python
BASE_URL = "https://auth.example.test"
KASSEL_ISSUER = f"{BASE_URL}/realms/kassel-ssf-2025"
FULDA_ISSUER = f"{BASE_URL}/realms/fulda-ssf-2025"
REVISION = f"sha256:{'a' * 64}"
```

Make token fixtures include `studio_tenant_id` and `ssf_authorization_revision`. Override `get_studio_login_directory_service` with a fake directory containing both mappings. Preserve tests for the temporary legacy header at the `require_ssf_user` boundary.

- [ ] **Step 2: Add failing allowlist and tenant-binding tests**

Cover valid Kassel and Fulda tokens, unknown realm issuer, lookalike issuer host, wrong base path, mismatched signed tenant ID, missing tenant claim, invalid signature, wrong audience, expired token, missing role, and expired/unavailable directory. Assert no HTTP discovery request occurs for every issuer rejected before cryptographic verification.

- [ ] **Step 3: Run auth tests and verify they fail under fixed issuer logic**

```bash
pytest -q tests/test_auth.py tests/test_tenant_context.py
```

Expected: the two-realm and mapping assertions fail.

- [ ] **Step 4: Implement exact issuer admission before network access**

Replace `issuer` with a normalized origin-only base URL:

```python
@dataclass(frozen=True)
class KeycloakSettings:
    base_url: str
    audience: str
    required_role: str

    def issuer_for(self, realm: str) -> str:
        return f"{self.base_url}/realms/{realm}"
```

Read `KEYCLOAK_BASE_URL`, not `KEYCLOAK_ISSUER`. Decode only enough unverified claims to obtain `iss`, compare that string against issuers generated for the validated Studio entries, and retain the matching tenant ID. Do not use an unverified URL for discovery.

- [ ] **Step 5: Harden OIDC discovery and complete JWT validation**

For an admitted issuer, require discovery metadata `issuer` to equal the expected issuer and `jwks_uri` to equal:

```python
f"{issuer}/protocol/openid-connect/certs"
```

Then validate RS256 signature, issuer, audience, expiry, and `ssf-user`. Finally require:

```python
claims.get("studio_tenant_id") == matched_tenant.id
```

Validate `ssf_authorization_revision` against
`^sha256:[0-9a-f]{64}$` in `auth.py` without importing `tenant_context.py`, which
would create a dependency cycle. `require_studio_tenant_context` repeats the
full typed claim conversion for tenant-bound route handlers.

- [ ] **Step 6: Keep FastAPI dependencies async-compatible**

Change `require_ssf_user` to `async def` with:

```python
directory: Annotated[
    StudioLoginDirectoryService,
    Depends(get_studio_login_directory_service),
]
```

Confirm that `require_studio_tenant_context` continues to receive the resolved claims through `Depends(require_ssf_user)`. Do not accept path, query, body, header, or cookie tenant selectors as authorization input.

- [ ] **Step 7: Run focused security tests**

```bash
pytest -q tests/test_auth.py tests/test_tenant_context.py
```

Expected: all tests pass, including the assertions that unknown issuers cause zero network calls.

- [ ] **Step 8: Commit multi-realm validation**

```bash
git add services/api_gateway/auth.py services/api_gateway/tenant_context.py tests/test_auth.py tests/test_tenant_context.py
git commit -m "feat(auth): validate Studio-allowlisted tenant realms"
```

---

### Task 4: Add the frontend tenant-directory domain adapter

**Files:**
- Create: `services/frontend/src/domain/login-tenant/loginTenant.types.ts`
- Create: `services/frontend/src/domain/login-tenant/loginTenant.mapper.ts`
- Create: `services/frontend/src/domain/login-tenant/loginTenant.repository.ts`
- Create: `services/frontend/src/domain/login-tenant/__tests__/loginTenant.test.ts`
- Modify: `services/frontend/src/app/providers/services.ts`
- Modify: `services/frontend/src/test/handlers.ts`

**Interfaces:**
- Consumes: anonymous `GET /api/login/tenants`.
- Produces: `LoginTenant`, `LoginTenantRepository.list()`, `toLoginTenants(dto)`, and `Services.loginTenant`.

- [ ] **Step 1: Write failing mapper and repository tests**

Use this public type:

```typescript
export interface LoginTenant {
  id: string;
  displayName: string;
  realm: string;
}
```

Test exact mapping of valid entries and rejection of blank/duplicate IDs, blank/duplicate realms, blank display names, invalid realm characters, non-arrays, and non-object entries. Test that the repository performs `GET /api/login/tenants` without adding an Authorization header.

- [ ] **Step 2: Run the frontend domain test and verify failure**

```bash
cd services/frontend
npx vitest run src/domain/login-tenant/__tests__/loginTenant.test.ts
```

Expected: module resolution fails for the new domain adapter.

- [ ] **Step 3: Implement DTO validation and the repository**

Define the wire DTO separately from the domain type:

```typescript
export interface LoginTenantDirectoryDto {
  tenants?: unknown;
}

export interface LoginTenantRepository {
  list(): Promise<LoginTenant[]>;
}
```

Use explicit runtime guards in `toLoginTenants`; never cast unvalidated response data. Preserve Studio order in the mapper because presentation sorting belongs to the screen. Implement `createLoginTenantRepository(http)` using the shared Axios instance.

- [ ] **Step 4: Register the repository and deterministic MSW fixture**

Add `loginTenant: LoginTenantRepository` to `Services` and initialize it in `createServices`. Add an intentionally unsorted MSW response:

```typescript
http.get('*/api/login/tenants', () =>
  HttpResponse.json({
    tenants: [
      { id: 'tenant-fulda', displayName: 'Amt Fulda', realm: 'fulda-ssf-2025' },
      { id: 'tenant-kassel', displayName: 'Stadt Kassel', realm: 'kassel-ssf-2025' },
    ],
  })
)
```

- [ ] **Step 5: Run domain and provider tests**

```bash
cd services/frontend
npx vitest run src/domain/login-tenant/__tests__/loginTenant.test.ts src/app/providers/__tests__/AppProvidersInner.test.tsx
```

Expected: all tests pass.

- [ ] **Step 6: Commit the frontend adapter**

```bash
git add services/frontend/src/domain/login-tenant services/frontend/src/app/providers/services.ts services/frontend/src/test/handlers.ts
git commit -m "feat(frontend): add login tenant directory adapter"
```

---

### Task 5: Build the `/login` tenant chooser and replace the start-page links

**Files:**
- Create: `services/frontend/src/features/login/TenantLoginScreen.tsx`
- Create: `services/frontend/src/features/login/__tests__/TenantLoginScreen.test.tsx`
- Modify: `services/frontend/src/features/access-code/AccessCodeScreen.tsx`
- Modify: `services/frontend/src/features/admin/__tests__/adminEntryLink.test.tsx`
- Modify: `services/frontend/src/i18n/locales/de.json`
- Modify: `services/frontend/src/i18n/locales/en.json`

**Interfaces:**
- Consumes: `Services.loginTenant.list() -> Promise<LoginTenant[]>`.
- Produces: `TenantLoginScreen` with links to `/login/:tenantId`.

- [ ] **Step 1: Write failing chooser behavior tests**

Cover loading, empty, failure with retry, and an unsorted list containing `Ämter`, `Amt Fulda`, and `Stadt Kassel`. Assert German `Intl.Collator('de')` order with tenant ID tie-breaks, accessible tenant links, existing header/footer, and no displayed realm or tenant ID.

The required German copy is:

```json
{
  "title": "Login",
  "instruction": "Bitte wählen Sie Ihre Abteilung oder Organisation aus der Liste aus.",
  "empty": "Derzeit sind keine Organisationen verfügbar.",
  "unavailable": "Die Liste der Organisationen ist derzeit nicht verfügbar.",
  "retry": "Erneut versuchen"
}
```

- [ ] **Step 2: Run the chooser test and verify failure**

```bash
cd services/frontend
npx vitest run src/features/login/__tests__/TenantLoginScreen.test.tsx
```

Expected: import fails because `TenantLoginScreen` does not exist.

- [ ] **Step 3: Implement the chooser using existing layout patterns**

Use `ScreenShell`, `AppHeader`, the existing footer path supplied by the shell, and `useQuery`. Sort a copied array:

```typescript
const collator = new Intl.Collator('de', { sensitivity: 'base' });
const ordered = [...tenants].sort(
  (left, right) =>
    collator.compare(left.displayName, right.displayName) || left.id.localeCompare(right.id)
);
```

Render semantic links with URL-encoded tenant IDs. Keep the page functional at narrow mobile widths and retain visible focus states.

- [ ] **Step 4: Rewrite the start-page link test first**

Change `adminEntryLink.test.tsx` to assert exactly one staff link named `Login` with `href="/login"`, and assert there is no `/admin` link, `Admin-Login`, `Neuer Admin-Login`, or Studio URL.

- [ ] **Step 5: Implement the single start-page Login link**

Merge with the existing uncommitted `AccessCodeScreen.tsx` work. Change only the staff-entry link and its translation key; preserve all unrelated layout and branding edits.

- [ ] **Step 6: Run UI-focused tests**

```bash
cd services/frontend
npx vitest run src/features/login/__tests__/TenantLoginScreen.test.tsx src/features/admin/__tests__/adminEntryLink.test.tsx src/features/access-code/__tests__/AccessCodeScreen.test.tsx src/i18n/__tests__/catalogues.test.ts
```

Expected: all tests pass.

- [ ] **Step 7: Commit the chooser UI**

```bash
git add services/frontend/src/features/login services/frontend/src/features/access-code/AccessCodeScreen.tsx services/frontend/src/features/admin/__tests__/adminEntryLink.test.tsx services/frontend/src/i18n/locales/de.json services/frontend/src/i18n/locales/en.json
git commit -m "feat(frontend): add tenant login chooser"
```

---

### Task 6: Make Keycloak initialization tenant-aware and route authenticated staff

**Files:**
- Modify: `services/frontend/src/app/auth/keycloak.ts`
- Create: `services/frontend/src/app/auth/__tests__/keycloak.test.ts`
- Modify: `services/frontend/src/app/config/env.ts`
- Modify: `services/frontend/src/app/config/__tests__/env.test.ts`
- Modify: `services/frontend/src/app/router/AppRoutes.tsx`
- Modify: `services/frontend/src/app/router/__tests__/AppRoutes.test.tsx`
- Modify: `services/frontend/src/features/admin/__tests__/adminSessionFlow.test.tsx`
- Modify: `services/frontend/src/core/http/__tests__/client.test.ts`

**Interfaces:**
- Consumes: selected `LoginTenant`, `AppConfig.keycloakUrl`, and `AppConfig.keycloakClientId`.
- Produces: `requireKeycloakLogin(config, tenant)`, `getAdminAccessToken()`, `logoutFromKeycloak()`, `/login`, and `/login/:tenantId` behavior.

- [ ] **Step 1: Write failing configuration tests**

Assert `readConfig` exposes `keycloakUrl` and `keycloakClientId` but no `keycloakRealm`. Require `VITE_KEYCLOAK_URL` to be an HTTP(S) origin without credentials, path, query, or fragment. Keep `VITE_KEYCLOAK_CLIENT_ID` non-empty.

- [ ] **Step 2: Remove fixed-realm frontend configuration**

Delete `VITE_KEYCLOAK_REALM` from the schema and `keycloakRealm` from `AppConfig`. Normalize the Keycloak URL by removing one trailing slash only after validating it as an origin.

- [ ] **Step 3: Write failing tenant-aware Keycloak adapter tests**

Mock the `Keycloak` constructor and assert selection creates it with:

```typescript
{
  url: 'https://auth.dialog.kassel.de',
  realm: 'kassel-ssf-2025',
  clientId: 'ssf-frontend',
}
```

Assert `init` uses `login-required`, `pkceMethod: 'S256'`, and the exact callback `/login/tenant-kassel`. Assert repeated calls for the same tenant reuse the client, a different tenant cannot silently reuse the first client, tokens remain in memory, refresh occurs before admin calls, and logout redirects to `/login`.

- [ ] **Step 4: Implement one active tenant-realm client**

Use an explicit active session record:

```typescript
interface ActiveKeycloakSession {
  tenantId: string;
  realm: string;
  client: Keycloak;
  initialized: boolean;
}
```

Accept the full validated `LoginTenant`; do not accept a raw realm string from the router. If a different tenant is selected in the same page lifetime, clear the old in-memory client before constructing the new one. Do not use localStorage or sessionStorage for tokens.

- [ ] **Step 5: Write failing router tests**

Assert `/login` renders the chooser. For `/login/tenant-kassel`, fake `loginTenant.list()` and the Keycloak adapter to cover:

- existing SSO session renders `AdminDashboardScreen`;
- unauthenticated initialization performs the Keycloak redirect and renders no dashboard first;
- callback remains tenant-qualified;
- unknown tenant renders a neutral unavailable/not-found state and never initializes Keycloak;
- logout returns to `/login`;
- `/admin` retains only the existing separately switched legacy screen and receives no redirect from `/login`.

- [ ] **Step 6: Implement chooser and tenant-entry routes**

Keep the route responsibilities separate:

```tsx
<Route path="/login" element={<TenantLoginScreen />} />
<Route path="/login/:tenantId" element={<TenantLoginEntry />} />
<Route path="/admin" element={<LegacyAdminEntry />} />
```

`TenantLoginEntry` loads the directory, resolves `tenantId`, calls `requireKeycloakLogin(config, tenant)`, and renders the existing dashboard/session state only after successful authentication. URL-decode once through React Router and compare exact IDs.

- [ ] **Step 7: Keep the legacy fallback isolated from tenant login**

Preserve the existing legacy-header fallback only when no in-memory Keycloak
token exists so the separately switched `/admin` migration path still works.
Assert that an authenticated `/login/:tenantId` session sends only its bearer
token, while `/api/login/tenants` carries neither bearer nor legacy credentials.

- [ ] **Step 8: Run auth and routing tests**

```bash
cd services/frontend
npx vitest run src/app/auth/__tests__/keycloak.test.ts src/app/config/__tests__/env.test.ts src/app/router/__tests__/AppRoutes.test.tsx src/features/admin/__tests__/adminSessionFlow.test.tsx src/core/http/__tests__/client.test.ts
```

Expected: all tests pass.

- [ ] **Step 9: Commit tenant-aware browser authentication**

```bash
git add services/frontend/src/app/auth services/frontend/src/app/config services/frontend/src/app/router services/frontend/src/features/admin/__tests__/adminSessionFlow.test.tsx services/frontend/src/core/http/__tests__/client.test.ts
git commit -m "feat(frontend): authenticate selected tenant realms"
```

---

### Task 7: Align production configuration, operations tests, and rollout documentation

**Files:**
- Modify: `deploy/production/production.env.example`
- Modify: `deploy/production/docker-compose.production.yml`
- Modify: `docker-compose.yml`
- Modify: `services/frontend/Dockerfile`
- Modify: `tests/operations/test_production_compose.py`
- Modify: `tests/operations/test_keycloak_realm.py`
- Modify: `services/frontend/DEPLOYMENT.md`
- Modify: `services/api_gateway/README.md`

**Interfaces:**
- Consumes: backend and frontend environment names established in Tasks 2, 3, and 6.
- Produces: reproducible deployment configuration and an explicit Studio/multi-tenant rollout gate.

- [ ] **Step 1: Write failing operations tests for the new configuration boundary**

Assert production compose provides:

```text
KEYCLOAK_BASE_URL
KEYCLOAK_AUDIENCE
KEYCLOAK_REQUIRED_ROLE
STUDIO_RUNTIME_CONFIGURATION_BASE_URL
STUDIO_RUNTIME_TOKEN_URL
STUDIO_RUNTIME_CLIENT_ID
STUDIO_RUNTIME_AUDIENCE
STUDIO_RUNTIME_CLIENT_SECRET
STUDIO_LOGIN_DIRECTORY_CACHE_SECONDS
```

Assert it no longer provides `KEYCLOAK_ISSUER`, the frontend image receives `VITE_KEYCLOAK_URL` and `VITE_KEYCLOAK_CLIENT_ID`, and no fixed frontend realm is supplied.

- [ ] **Step 2: Run operations tests and verify failure**

```bash
pytest -q tests/operations/test_production_compose.py tests/operations/test_keycloak_realm.py tests/test_keycloak_compose_configuration.py
```

Expected: assertions fail on the old fixed issuer/realm and missing Studio directory configuration.

- [ ] **Step 3: Update compose and example environment files**

Set production examples to the actual origins:

```text
KEYCLOAK_BASE_URL=https://auth.dialog.kassel.de
KEYCLOAK_AUDIENCE=ssf-frontend
KEYCLOAK_REQUIRED_ROLE=ssf-user
STUDIO_RUNTIME_CONFIGURATION_BASE_URL=https://studio.dialog.kassel.de
STUDIO_RUNTIME_CLIENT_ID=ssf-runtime
STUDIO_RUNTIME_AUDIENCE=sva-studio-ssf-runtime
STUDIO_LOGIN_DIRECTORY_CACHE_SECONDS=60
```

Keep the Studio client secret empty in the checked-in example and interpolate it as a required deployment secret. Do not add real credentials. Pass the frontend Keycloak base URL and public client ID as build args.

- [ ] **Step 4: Reframe the local Keycloak realm artifact as development-only**

Update `tests/operations/test_keycloak_realm.py` so it verifies only the local/development fixture. Production tenant realms are Studio-owned and are verified through the directory readiness contract, not by importing one fixed `ssf` realm. Keep PKCE, audience, role, and no-secret assertions for the local fixture.

- [ ] **Step 5: Document the rollout dependency and smoke procedure**

Document these gates in English:

1. Studio directory returns at least two ready tenant entries.
2. Each realm has the common public client, exact `/login/*` redirect, audience, role, tenant ID, and authorization-revision claims.
3. `SSF_ENABLE_LEGACY_ADMIN_ACCESS=false` before multi-realm production enablement.
4. `add-multi-tenant-operations` isolation tests pass before real conversations are exposed.
5. Login, existing SSO, logout, unknown tenant, Studio outage, and cross-tenant negative paths are manually verified.

- [ ] **Step 6: Run operations tests again**

```bash
pytest -q tests/operations/test_production_compose.py tests/operations/test_keycloak_realm.py tests/test_keycloak_compose_configuration.py
```

Expected: all tests pass.

- [ ] **Step 7: Commit deployment alignment**

```bash
git add deploy/production/production.env.example deploy/production/docker-compose.production.yml docker-compose.yml services/frontend/Dockerfile tests/operations/test_production_compose.py tests/operations/test_keycloak_realm.py services/frontend/DEPLOYMENT.md services/api_gateway/README.md
git commit -m "chore: configure Studio-backed tenant login"
```

---

### Task 8: Verify the complete feature and close the OpenSpec implementation checklist

**Files:**
- Modify: `openspec/changes/add-keycloak-admin-authentication/tasks.md`
- Modify only if verification exposes a documentation mismatch: `docs/superpowers/specs/2026-09-10-tenant-login-directory-design.md`

**Interfaces:**
- Consumes: every deliverable from Tasks 1–7.
- Produces: verified build/test evidence and an accurate OpenSpec checklist.

- [ ] **Step 1: Run the complete focused backend suite**

```bash
pytest -q tests/test_studio_login_directory_client.py tests/test_studio_login_directory.py tests/test_login_directory_route.py tests/test_auth.py tests/test_tenant_context.py tests/test_studio_runtime_client.py tests/test_studio_runtime_flow.py services/api_gateway/tests/test_admin.py services/api_gateway/tests/test_customer.py
```

Expected: all tests pass.

- [ ] **Step 2: Run Python quality checks on changed modules**

```bash
black --check services/api_gateway/studio_login_directory_client.py services/api_gateway/studio_login_directory.py services/api_gateway/routes/login.py services/api_gateway/auth.py tests/test_studio_login_directory_client.py tests/test_studio_login_directory.py tests/test_login_directory_route.py tests/test_auth.py
isort --check-only services/api_gateway/studio_login_directory_client.py services/api_gateway/studio_login_directory.py services/api_gateway/routes/login.py services/api_gateway/auth.py tests/test_studio_login_directory_client.py tests/test_studio_login_directory.py tests/test_login_directory_route.py tests/test_auth.py
mypy services.api_gateway.studio_login_directory_client services.api_gateway.studio_login_directory services.api_gateway.auth
```

Expected: every command exits zero.

- [ ] **Step 3: Run the complete frontend verification**

```bash
cd services/frontend
npm test
npm run lint
npm run build
npm run fallow:audit
```

Expected: every command exits zero under Node 24.

- [ ] **Step 4: Run operations and OpenSpec validation**

```bash
cd /root/projects/ssf-backend
pytest -q tests/operations/test_production_compose.py tests/operations/test_keycloak_realm.py tests/test_keycloak_compose_configuration.py
openspec validate add-keycloak-admin-authentication --strict
git diff --check
```

Expected: every command exits zero.

- [ ] **Step 5: Verify the multi-tenant release gate without claiming it is implemented here**

Run the tests delivered by `add-multi-tenant-operations` for tenant-partitioned session creation, history, lookup, termination, messages, audio, and customer joins. If that change is not yet complete, record production rollout as blocked and do not mark cross-tenant production verification complete.

- [ ] **Step 6: Update OpenSpec task statuses from evidence**

Mark only tasks with passing implementation evidence as `[x]` in
`openspec/changes/add-keycloak-admin-authentication/tasks.md`. Leave Studio provisioning and production-like two-realm checks unchecked until they have been run against the deployed systems.

- [ ] **Step 7: Commit verification metadata**

```bash
git add openspec/changes/add-keycloak-admin-authentication/tasks.md docs/superpowers/specs/2026-09-10-tenant-login-directory-design.md
git commit -m "docs: record tenant login verification status"
```
