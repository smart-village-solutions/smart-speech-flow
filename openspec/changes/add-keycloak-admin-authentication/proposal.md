# Change: Add Keycloak authentication for administrative access

Tracks: #204

## Why

The current administrative entry is a client-side password comparison whose
value is included in the frontend bundle. It does not authenticate a user and
the administrative API is currently reachable without authorization. The
running Keycloak service must become the identity provider for administrative
staff while the public customer and QR-code flows remain unchanged.

## What Changes

- Add a reproducible Keycloak realm `ssf`, public SPA client `ssf-frontend`,
  and realm role `ssf-user`.
- Replace the frontend's simulated login and `/admin` entry with a Keycloak
  OIDC Authorization Code flow with PKCE at `/login`.
- Retain `/admin` and its legacy password gate temporarily behind an explicit
  deployment switch; it is removed after the transition.
- Require a valid Keycloak bearer token with the `ssf-user` role for every
  `/api/admin/**` endpoint.
- Remove the development login bypass and `/admin/dev`; retain the bundle-visible
  legacy password and `/admin` only for the explicitly enabled transition.
- Upgrade the frontend build, CI, and development toolchain from Node 22/20 to
  Node 24 LTS so its test runtime is supported.
- Keep user creation, password management, role assignment, and optional MFA
  administration manual in Keycloak. MFA is not required for this release.

## Impact

- Affected specs: `admin-authentication` (new capability)
- Affected frontend: route configuration, runtime configuration, HTTP client,
  login/session state, tests, and obsolete simulated-login assets.
- Affected API gateway: token-validation dependency, protected admin routers,
  configuration, and tests.
- Affected deployment: Keycloak realm provisioning and non-secret frontend and
  gateway configuration, plus the Node 24 frontend builder image and CI setup.
- **BREAKING (after transition):** `/admin` and its legacy access header are
  removed. New administrative callers authenticate at `/login` and send bearer
  tokens to the API.
