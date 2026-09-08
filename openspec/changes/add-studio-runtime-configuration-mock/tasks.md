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

## 4. Studio tenant naming correction

- [x] 4.1 Replace the mock tenant selector with `X-Studio-Tenant-Id` and use
  `tenant_id` for the mock's SSF-internal revision input.
- [x] 4.2 Remove legacy headers, uppercase error codes, and the
  `authorization-pending` scenario; model the four explicit scenarios.
- [x] 4.3 Update the OpenAPI, operational runbook, architecture documentation,
  and contract tests for the V1 Studio tenant boundary.
