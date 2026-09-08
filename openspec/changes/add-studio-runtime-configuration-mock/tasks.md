## 1. Mock API

- [x] 1.1 Define deterministic tenant configuration fixtures and error envelopes.
- [x] 1.2 Implement the unauthenticated V1 runtime-configuration endpoint.
- [x] 1.3 Add endpoint contract tests for success, storage policies, and errors.

## 2. Local operation

- [x] 2.1 Add a Docker image and an opt-in Compose profile for the mock.
- [x] 2.2 Document profile-gated startup and the fixed mock-data scope.
- [x] 2.3 Verify the mock is reachable only when its profile is enabled.

## 3. External HTTP test access

- [x] 3.1 Publish the opt-in mock port on all host network interfaces.
- [x] 3.2 Document the unauthenticated HTTP-by-IP URL and mock-data scope.
- [x] 3.3 Add and run a Compose regression test for the external port binding.
