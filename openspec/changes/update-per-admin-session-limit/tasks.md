## 1. Implementation

- [x] 1.1 Derive the owner reference from the verified tenant and subject.
- [x] 1.2 Store the owner on the session, persist it, keep it out of public output.
- [x] 1.3 End only the creating admin's live sessions, reading the store.
- [x] 1.4 Scope `/api/admin/session/current` to the requesting admin.
- [x] 1.5 Warn in the admin dashboard only about the admin's own live session.

## 2. Verification

- [x] 2.1 Focused tests, each proven to fail when its rule is removed.
- [x] 2.2 Full suite on a merge with `origin/main`; tenant-isolation matrix.
- [x] 2.3 Deploy to production and verify with the #289 release check.
