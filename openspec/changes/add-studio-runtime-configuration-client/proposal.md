# Change: Add the Studio Runtime Configuration V1 client

## Why

SSF needs a fail-closed consumer for tenant-specific runtime configuration from
Studio before the mock can be replaced by real control-plane data.

## What Changes

- Add the fixed V1 request path and required service, tenant, and correlation headers.
- Validate all required response fields, revisions, tenant binding, and semantic constraints.
- Follow the stable Studio error envelope and its `retryable` value.
- Accept optional V1 additions while strictly validating known fields.

## Impact

- Affected specs: `studio-runtime-integration` (new)
- Affected code: API Gateway Studio integration module and focused contract tests
