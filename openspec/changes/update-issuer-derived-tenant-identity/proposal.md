# Change: Derive the tenant from the validated issuer

Tracks: #363

## Why

Tenant realms map one-to-one to Studio tenants. The gateway already resolves
the tenant from the token issuer against the published login directory before
it verifies the token, yet it also demands a duplicate `studio_tenant_id` claim
and rejects every token without one. Production tokens from realm `smartcity`
carry no such claim, and every rejection returns the same neutral 401 with no
server-side trace. Philipp's decision on #363 (2026-09-20, 2026-09-22,
2026-09-23): the validated issuer, matched against the directory, is the
authoritative tenant context; the authorization revision and role contract stay
in force; rejected tokens get server-side reason codes.

## What Changes

- The gateway takes the tenant from the directory entry whose realm issued the
  token. A token without `studio_tenant_id` is accepted; a token whose
  `studio_tenant_id` disagrees with the matched tenant, or is not a string, is
  rejected.
- The authenticated principal carries the matched tenant; no downstream code
  reads the tenant from the token.
- Every rejected token produces one structured log line with a closed reason
  code and the correlation ID, and increments
  `gateway_auth_rejections_total{reason}`. Client responses are unchanged.
- `deploy/production/keycloak/ssf-realm.json` becomes the reviewed SSF realm
  contract: `/login/*` redirects, audience, revision claim, `ssf-user`, no
  tenant-ID mapper. A guard test enforces it.
- The tenant-isolation smoke test fails with specific messages for tokens
  missing the revision or role; a read-only audit reports per tenant and user
  whether tokens would pass; a runbook covers onboarding verification and
  diagnosis.

Out of scope: Studio's IAM projection and directory publication (sva-studio
#1325, #1480, #1350), any Keycloak write, a repair mode that writes user
attributes, client-ID or permission-contract migration.

## Impact

- Affected specs: `studio-tenant-context` (from unarchived
  `add-studio-tenant-context`), `admin-authentication` (from unarchived
  `add-keycloak-admin-authentication`, as modified by
  `remove-legacy-admin-access`); archive those changes first.
- Affected code: `services/api_gateway/auth.py`, `auth_rejections.py` (new),
  `correlation_id.py` (new), `tenant_context.py`, `session_access.py`,
  `websocket_polling_routes.py`, `routes/feedback.py`, `routes/customer.py`,
  `routes/login.py`, `studio_runtime_flow.py`, `app.py`;
  `scripts/tenant-isolation-smoke.py`, `scripts/tenant-auth-audit.py` (new),
  `scripts/lib/ssf_auth_contract.py` (new); `deploy/production/keycloak/`.
- Production is **not** unblocked by this change alone: tokens also lack the
  revision and the `ssf-user` role, which only the Studio projection supplies.
