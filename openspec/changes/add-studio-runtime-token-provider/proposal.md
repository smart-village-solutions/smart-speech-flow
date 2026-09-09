# Change: Add the Studio runtime token provider

## Why

SSF needs a bounded, fail-safe way to authenticate technical requests to the
Studio runtime API without persisting bearer tokens.

## What Changes

- Add OAuth2 Client Credentials token acquisition with the agreed client and audience defaults.
- Cache tokens only in memory and renew them before expiry.
- Classify failures without exposing credentials or bearer tokens.
- Allow a fixed token only through explicit local and test configuration.

## Impact

- Affected specs: `studio-runtime-integration` (new)
- Affected code: API Gateway Studio integration module and focused unit tests
