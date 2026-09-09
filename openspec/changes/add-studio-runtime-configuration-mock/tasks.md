## 1. Mock API

- [x] 1.1 Define deterministic tenant configuration fixtures and error envelopes.
- [x] 1.2 Implement the V1 runtime-configuration endpoint with fixed mock
  service-token authorization.
- [x] 1.3 Add endpoint contract tests for success, storage policies, and errors.

## 2. Local operation

- [x] 2.1 Add a Docker image and an opt-in Compose profile for the mock.
- [x] 2.2 Document profile-gated startup and the fixed mock-data scope.
- [x] 2.3 Verify the mock is reachable only when its profile is enabled.

## 3. V1 contract correction

- [x] 3.1 Require Studio instance and correlation headers, and model service
  token authorization.
- [x] 3.2 Align authorization and locale response fields with Contract V1.
- [x] 3.3 Restore loopback-only operation and document the swappable endpoint.

## 4. Canonical tenant boundary

- [x] 4.1 Replace `X-Studio-Instance-Id` with `X-Studio-Tenant-Id` and return
  the selected value unchanged as `tenant.id`.
- [x] 4.2 Reject legacy headers and query selectors without aliases.
- [x] 4.3 Align stable error codes, statuses, messages, and retryability with
  the frozen Studio V1 contract.
- [x] 4.4 Replace the authorization-pending scenario with suspended,
  plugin-inactive, tenant-not-ready, and unavailable scenarios.
- [x] 4.5 Update focused tests, OpenAPI, operations, and architecture docs.
