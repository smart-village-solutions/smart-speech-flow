# Change: Add Studio runtime configuration mock

## Why

The SSF implementation and tester-release verification need a contract-faithful
Studio Runtime Configuration V1 dependency before the deployed Studio endpoint
is available in every developer environment.

## What Changes

- Add an opt-in FastAPI mock for the Studio Runtime Configuration V1 read API.
- Serve deterministic configurations for two tenants and the `ask` and
  `disabled` conversation-storage policies.
- Provide deterministic V1 error envelopes using only the seven stable
  lowercase snake_case error codes.
- Package the mock in a dedicated Docker Compose profile with loopback-only
  HTTP exposure.

## Impact

- Affected capability: Studio--SSF runtime configuration integration.
- Affected code: Compose configuration, mock service documentation, and
  contract tests.
- No production authentication, tenant isolation, or persistence path changes.
  The mock models fixed service-token authorization without real credential
  validation.
