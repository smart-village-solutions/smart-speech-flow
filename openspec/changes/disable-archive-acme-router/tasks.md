## 1. Production topology

- [x] 1.1 Remove the retired archive frontend from the production Compose overlay.
- [x] 1.2 Add a regression test for its absence from production and retention in development.

## 2. ACME deployment guard

- [x] 2.1 Add failing tests for local-only and DNS-unresolvable ACME router hosts.
- [x] 2.2 Validate rendered ACME router hosts before `production_compose up -d`.
- [x] 2.3 Add a passing resolving-host test and retain existing guard coverage.

## 3. Verification

- [x] 3.1 Run the focused Traefik and production-script tests.
- [x] 3.2 Validate the OpenSpec change strictly.
