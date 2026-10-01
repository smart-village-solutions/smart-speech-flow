## 1. Implementation

- [x] 1.1 Deny a non-owner on every admin route that names a session, with the unknown-session `404`.
- [x] 1.2 Return a named `/current` session only to its owner.
- [x] 1.3 Scope the session history and the tenant realtime connections to the requesting admin.
- [x] 1.4 Release check: read every tester's live sessions in the preflight, and prove the colleague denial in each tenant.

## 2. Verification

- [x] 2.1 Two-admin tests for each route, each proven to fail when its rule is removed.
- [x] 2.2 Full suite on a merge with `origin/main`; contract suite; tenant-isolation matrix.
- [ ] 2.3 Deploy to production and verify the two-admin denial there with the release check.
