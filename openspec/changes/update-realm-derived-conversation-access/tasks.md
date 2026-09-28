## 1. Gateway consumer

- [x] 1.1 Admit valid users via verified issuer and unique Studio directory entry.
- [x] 1.2 Derive tenant context and session checks without legacy user claims.
- [x] 1.3 Remove user-token revision comparison while preserving runtime tenant match.
- [x] 1.4 Keep feedback read and telemetry probe role checks separate.

## 2. Verification and rollout

- [x] 2.1 Update automated tests for both realms, malformed tokens, tenant isolation, and privileged operations.
- [x] 2.2 Update operations and architecture documentation.
- [x] 2.2a Reconcile adjacent GitHub issues, active OpenSpec contracts, and rollout documents with #438.
- [x] 2.3 Deploy gateway before changing token production (production image `prod-4447d3c`, 2026-09-27).
- [ ] 2.4 Verify fresh attribute-free tokens in two real realms and record evidence before closing rollout issues.
