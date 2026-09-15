## 1. Tenant authorization context

- [x] 1.1 Require and validate `ssf_authorization_revision` alongside the
  canonical signed tenant claim.
- [x] 1.2 Extend focused tenant-context tests for valid, missing, malformed,
  and conflicting authorization-revision claims.

## 2. Runtime-flow integration

- [x] 2.1 Add a small service that composes the existing token provider and
  Runtime Configuration V1 client without changing either component.
- [x] 2.2 Forward or generate correlation IDs and return one validated result
  type for downstream dependencies.
- [x] 2.3 Reject authorization-revision mismatches and all upstream failures
  without fallback configuration.

## 3. Gateway dependency and proof

- [x] 3.1 Expose the runtime-flow result through an authenticated FastAPI
  dependency suitable for later session/persistence routes.
- [x] 3.2 Add mock-backed positive, cross-tenant, revision-mismatch, missing
  revision, correlation, and upstream-failure tests.
- [x] 3.3 Validate this OpenSpec change and the focused gateway test scope.
