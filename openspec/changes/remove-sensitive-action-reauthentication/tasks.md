## 1. Gateway policy

- [x] 1.1 Inventory every sensitive-action freshness dependency, including legacy routes; remove action freshness gates while retaining verified user authentication and permission dependencies on every route.
- [x] 1.2 Replace freshness tests with accepted password-only/older-MFA cases, including missing optional freshness claims; retain invalid-token, tenant and permission denials.
- [x] 1.3 Apply session-based authentication to organisation-key and transfer APIs when implemented, preserving possession proofs and preparation expiry.

## 2. Frontend and Studio coordination

- [x] 2.1 Remove freshness helpers, prompts, redirects, fault branches, translations and recovery computation deadlines; preserve normal refresh/session-expiry handling and local key unlocking.
- [x] 2.2 Verify keys, archive/review, retention, leaver and exposed recovery/ceremony workflows without repeat login, including work crossing the former five-minute deadline.
- [x] 2.3 Coordinate Studio login-MFA configuration and delegated APIs; prove optional password-only login, mandatory MFA at login and delegated older-session actions without step-up.
- [x] 2.4 Verify own-key unlock uses only the matching local Zugangsschlüssel within a valid session, including active/historical versions, explicit lock, reload and incorrect-passphrase errors; assert no new login, login-password, MFA or email-confirmation requirement.

## 3. Documentation and release

- [x] 3.1 Update architecture and recording deployment runbooks; reconcile earlier step-up requirements explicitly without rewriting historical acceptance evidence.
- [x] 3.2 Run focused Gateway and frontend suites plus configured-realm acceptance for normal refresh and actual session expiry; record results and coordinate deployment.

## Verification evidence

Implementation and independent review are complete. Exact test scopes and the
remaining coordinated release-acceptance boundary are recorded in
`docs/meeting-notes/2026-11-18-dashboard-key-management-verification.md`.
Deployment and any destructive cutover remain separate operator actions.
