## 1. Review
- [x] 1.1 Approve the configuration semantics and tab-local memory-only unlock design.
- [x] 1.2 Review existing tab-local vault lifecycle and authentication invalidation boundaries.

## 2. Studio configuration
- [x] 2.1 Add installation default and tenant override administration and effective runtime output.
- [x] 2.2 Verify inheritance, reset, validation and configuration revision changes.

## 3. SSF passphrase files
- [x] 3.1 Consume the effective setting with disabled fallback.
- [x] 3.2 Add explicit local TXT export after successful entry and local file import with clear storage guidance.
- [x] 3.3 Verify format round trips, input bounds and transient secret cleanup.

## 4. Tab-local unlock
- [x] 4.1 Preserve the in-memory vault across application navigation within the existing tab.
- [x] 4.2 Close lifecycle invalidation gaps and prevent in-flight unlocks from restoring invalidated keys.
- [x] 4.3 Verify navigation, refresh, logout, expiry and identity changes; reloads and new tabs require unlocking.
- [x] 4.4 Verify passphrases and unlocked keys are never persisted to browser storage or shared between tabs.

## 5. Completion
- [x] 5.1 Review security implications, run relevant regressions and document user-visible behavior.

## Validation record

- User approved SSF and Studio implementation on 2026-11-18, with tab-local unlock.
- Studio implemented in `/root/projects/studio-key-convenience`, based on the
  existing recording administration branch; independent review found no defect.
- SSF independent review found a shared own-key observation gap; fixed with a
  regression test outside the keys screen and successfully re-reviewed.
- Full SSF frontend unit suite: 1,834 passed across 196 files.
- Gateway policy/key tests: 40 passed; the broader recording/permission subset
  also passed 65 tests during implementation.
- Frontend lint/build, gateway MyPy (`--ignore-missing-imports`, 215 files),
  Black/isort, OpenSpec strict validation and diff whitespace checks passed.
- Studio plugin tests: 251 passed, 13 skipped; plugin types and server-runtime
  checks passed.
- Chromium TXT download/import checks: 2 passed.
- Chromium exercises actual local TXT download/readback and invalid-file
  rejection. Authentication/reload/new-tab lifecycle is covered by frontend
  regressions, not a live Keycloak browser environment.
- Studio plugin unit tests, types, lint, server runtime and file placement checks
  passed; its repository-wide browser suite was not run.
