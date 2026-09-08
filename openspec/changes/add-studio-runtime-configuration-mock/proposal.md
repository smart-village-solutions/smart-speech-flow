# Change: Add Studio runtime configuration mock

## Why

The SSF implementation and tester-release verification need a contract-faithful
Studio Runtime Configuration V1 dependency before the deployed Studio endpoint
is available in every developer environment.

## What Changes

- Add a local-only FastAPI mock for the Studio Runtime Configuration V1 read API.
- Serve deterministic configurations for two tenants and the `ask` and
  `disabled` conversation-storage policies.
- Provide deterministic `401`, `403`, `404`, `409`, and `503` error envelopes.
- Package the mock in a dedicated Docker Compose profile that production
  deployments do not enable.

## Impact

- Affected capability: Studio--SSF runtime configuration integration.
- Affected code: local development Compose configuration, mock service, and
  contract tests.
- No production authentication, tenant isolation, or persistence path changes.
