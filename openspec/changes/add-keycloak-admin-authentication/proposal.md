# Change: Add Keycloak authentication for administrative access

Tracks: #204

## Why

The current administrative entry is a client-side password comparison whose
value is included in the frontend bundle. It does not authenticate a user and
the administrative API is currently reachable without authorization. The
running Keycloak service must become the identity provider for administrative
staff while the public customer and QR-code flows remain unchanged.

## What Changes

- Integrate Studio's authoritative SSF tenant-login directory and provision the
  public SPA client `ssf-frontend` plus realm role `ssf-user` consistently in
  every listed tenant realm.
- Replace the frontend's simulated login with an alphabetically sorted tenant
  chooser at `/login` and a tenant-selected Keycloak OIDC Authorization Code
  flow with PKCE.
- Retain `/admin` and its legacy password gate temporarily behind an explicit
  deployment switch without linking it from the start page; reserve the route
  for separate future functionality after that transition.
- Require a valid bearer token from a Studio-allowlisted tenant realm, with the
  `ssf-user` role and matching signed Studio tenant context, for every
  `/api/admin/**` endpoint.
- Remove the development login bypass and `/admin/dev`; retain the bundle-visible
  legacy password and `/admin` only for the explicitly enabled transition.
- Upgrade the frontend build, CI, and development toolchain from Node 22/20 to
  Node 24 LTS so its test runtime is supported.
- Keep user creation, password management, role assignment, and optional MFA
  administration in Studio's tenant IAM flows. MFA is not required for this
  release.

## Impact

- Affected specs: `admin-authentication` (new capability)
- Affected Studio integration: tenant-unbound login-directory client and
  readiness contract.
- Affected frontend: route configuration, runtime configuration, HTTP client,
  login/session state, tests, and obsolete simulated-login assets.
- Affected API gateway: token-validation dependency, protected admin routers,
  configuration, and tests.
- Affected deployment: Keycloak realm provisioning and non-secret frontend and
  gateway configuration, plus the Node 24 frontend builder image and CI setup.
- **BREAKING (after transition):** the legacy password gate and access header
  are removed. Staff select their tenant at `/login` and send tenant-bound
  bearer tokens to the API; `/admin` is not assigned by this change.
