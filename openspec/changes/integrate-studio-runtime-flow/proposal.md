# Change: Integrate the tenant-bound Studio runtime flow

## Why

SSF has the separate tenant-context, service-token, and Runtime Configuration
V1 client foundations, but no composition boundary verifies that a validated
user's authorization revision authorizes the returned tenant configuration.

## What Changes

- Extend the trusted tenant context with the signed
  `ssf_authorization_revision` claim.
- Add a small runtime-flow service that composes the existing token provider
  and Runtime Configuration V1 client.
- Forward or generate a correlation ID and compare configuration and token
  authorization revisions before returning a validated result.
- Expose that result via an authenticated FastAPI dependency for later session
  and persistence work.
- Add mock-backed positive and cross-tenant/authorization-revision negative
  tests.

## Impact

- Affected specs: `studio-runtime-flow`, `studio-tenant-context`.
- Affected code: API Gateway tenant context and a new runtime-flow module.
- Existing `studio_runtime_token.py` and `studio_runtime_client.py` are
  consumed unchanged.
