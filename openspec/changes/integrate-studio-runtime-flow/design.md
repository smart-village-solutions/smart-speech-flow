## Context

`StudioTenantContext`, `StudioRuntimeTokenProvider`, and
`StudioRuntimeClient` already provide validated tenant identity, service-token
acquisition, and a strict V1 client. This change establishes their single
composition boundary.

## Goals / Non-Goals

- Goals: fail-closed authorization-revision verification, canonical tenant
  propagation, correlation handling, and a reusable authenticated dependency.
- Non-Goals: changing token caching, client schema validation, conversation
  persistence, guest resolution, configuration caching, or a new public API.

## Decisions

- Add `authorization_revision` to the frozen tenant context and require a
  valid `ssf_authorization_revision` claim for runtime-bound requests.
- A `StudioRuntimeFlow` calls the existing client and uses
  `hmac.compare_digest` to compare authorization revisions.
- The dependency preserves a printable `X-Correlation-Id` or generates a UUID
  when absent; invalid supplied values are rejected before upstream access.
- The returned `ValidatedRuntimeConfiguration` carries only the trusted
  context, correlation ID, and existing validated configuration model.

## Risks / Trade-offs

- Requiring the new signed claim means tokens issued before the mapper update
  cannot use tenant-bound operations; this is intentional fail-closed
  behavior.
- The dependency is introduced without attaching it to session endpoints, so
  this change proves the boundary without expanding session scope.
