# Change: Disable the retired archive ACME router

## Why

The retired archive hostname has no DNS record but is still configured as a production
Traefik TLS router. This creates invalid ACME attempts and obscures meaningful routing
errors.

## What Changes

- Remove the archive frontend and its TLS router from the canonical production Compose
  configuration.
- Guard production deployments against local-only and unresolvable ACME hostnames.
- Add regression coverage for the retired route and deployment validation.

## Impact

- Affected capability: production deployment
- Affected code: production Compose overlay, deployment guard, operations tests
- External systems: no DNS or Studio mutation
