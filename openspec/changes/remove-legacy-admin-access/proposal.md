# Change: Remove the temporary legacy administrative access

Tracks: #216

## Why

`add-keycloak-admin-authentication` kept the `/admin` password gate and the
`X-SSF-Legacy-Access` header as a migration path. The password is embedded in
the browser bundle and is not a security control. An operational administrator
has confirmed the tenant-aware Keycloak login in production (#216, 2026-09-22),
so the migration path is no longer needed.

## What Changes

- **BREAKING:** remove the `/admin` password route; `/admin` returns the normal
  not-found page and `/login` is the only administrative entry point.
- **BREAKING:** remove the pre-revamp `/customer` page, which was reachable only
  through the legacy password flag. Customers join through `/join/:sessionId`
  and the access-code screen, which are unchanged.
- Remove the simulated password login, its hook, screen, tests and catalogue
  entries, and the legacy customer components that only `/customer` used.
- Stop allowing `X-SSF-Legacy-Access` in the gateway CORS configuration; the
  gateway already ignores the header for authorization.
- Remove `SSF_ENABLE_LEGACY_ADMIN_ACCESS`, `SSF_LEGACY_ADMIN_ACCESS_CODE`,
  `FRONTEND_DEMO_PASSWORD`, `VITE_DEMO_ACCESS_CODE` and `VITE_APP_PASSWORD` from
  the Compose files, Dockerfile, environment examples and frontend
  configuration.
- Update operator documentation.

## Impact

- Affected specs: `admin-authentication`, introduced by the unarchived
  `add-keycloak-admin-authentication`; archive that change first.
- Affected frontend: route table, runtime configuration, admin feature, legacy
  `pages/`, `components/`, `contexts/` and `services/` modules, i18n catalogues.
- Affected API gateway: CORS allow-list.
- Affected deployment: frontend build arguments and gateway environment.
  Existing environment files may keep the retired variables; they are ignored.
