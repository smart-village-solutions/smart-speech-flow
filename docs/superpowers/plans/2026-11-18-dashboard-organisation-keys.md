# Dashboard and organisation keys implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Execute the approved work packages below with focused test-first cycles and coordinator review.

**Goal:** Deliver the approved SSF dashboard, version-preserving personal access and Studio organisation-key administration.

**Architecture:** Gateway owns public key state and access grants. Studio performs organisation private-key operations locally. SSF reuses existing conversation/archive/review flows and unlocks personal versioned server blobs with local passphrases.

**Tech Stack:** Python/FastAPI/Postgres, React/TypeScript/WebCrypto, Studio/Nx/Keycloak.

**Spec:** `openspec/changes/add-task-oriented-ssf-dashboard/` and `openspec/changes/update-recording-key-lifecycle/`; Studio companion `/root/projects/studio-key-convenience/openspec/changes/add-ssf-organisation-key-management/`.

## Additional approved scope

The user requested implementing `remove-sensitive-action-reauthentication` alongside this work. Its spec is authoritative over earlier action-specific fresh-MFA text. Gateway, SSF and Studio workers own their respective code/tests; the coordinator reconciles documentation. Keep login policy MFA, verified authentication, session expiry, effective rights, local passphrase unlock, email-confirmed key replacement and possession preparation expiry.

## Global Constraints

- User approved all three proposals in this conversation on 2026-11-18.
- Personal Zugangsschlüssel means passphrase; optional personal TXT policy remains.
- Reviewers retain ordinary conversations. No role switch or new conversation admission.
- Existing data is disposable, but do not execute resets, deployments or deletions.
- Preserve historical versions across ordinary supersession; distinguish actual revocation.
- Private organisation keys remain local. Use the exact approved versioned contracts.
- Preserve encrypted language metadata, existing retention and tenant/owner boundaries.
- English SSF documentation; Studio follows its own German documentation rules.
- Do not overwrite unrelated changes. Separate worker-owned paths and commits.

### Task 1: Gateway contracts and key lifecycle

**Files:** Gateway recording/routes/services, recording SQL migrations, associated Python tests and shared crypto fixtures; both approved SSF change task lists for backend items.
**Consumes:** Both approved proposal designs and exact API contracts.
**Produces:** `/api/admin/dashboard/conversations`, completed-review result endpoint and `/api/admin/recording/v2` contracts, version-aware archive/review DTOs and published vectors for frontend/Studio.

- [ ] Verify baseline recording tests; add and run focused failing tests for version-preserving key supersession and isolation.
- [ ] Implement additive version/grant/preparation persistence and lifecycle using the approved design, then verify those tests.
- [ ] Add failing preparation/activation/transfer tests; implement possession transcripts, expiry/CAS/replay/atomic grants and verify.
- [ ] Add overview/result tests; implement safe server joins, metadata privacy and bound pagination and verify.
- [ ] Integrate recording recipients, archive versions and assigned-version decisions. Supply operator-only cutover tooling without running it.
- [ ] Run meaningful affected unit/integration checks, self-review, commit owned files and write report.

### Task 2: SSF dashboard, account and version-aware keys

**Files:** `services/frontend/src` and frontend tests only; dashboard and lifecycle frontend task items.
**Consumes:** Task 1 exact HTTP/crypto fixtures and approved designs. Gateway response fields must be matched, not guessed.
**Produces:** Task-oriented dashboard, account entry, metadata-only details, result-only review summary, multi-version in-memory vault and unchanged personal passphrase file flow.

- [ ] Verify baseline affected tests; add failing behavioral tests for role views and independent filters/return targets.
- [ ] Implement shared tables, paginated overview repository, honest local filtering and existing viewer integration, then verify.
- [ ] Add failing historical unlock/rotation and review-version tests; implement version-aware repositories, vault and signing without losing old access.
- [ ] Implement account/menu and coordinated recovery navigation replacement; preserve existing live conversation and usage functions.
- [ ] Run affected frontend tests, build and lint, self-review, commit owned files and write report.

### Task 3: Studio organisation key and access transfer

**Files:** Studio `packages/plugin-ssf`, narrowly required auth-runtime/plugin-sdk and Keycloak provisioning; Studio proposal task list.
**Consumes:** Task 1 exact DTOs, canonical transcripts, crypto formats and vectors.
**Produces:** Local key generation/save/activation/replacement and exact-scope local transfer with authenticated server forwarding.

- [ ] Verify Studio baseline and read applicable rules; add failing auth/permission tests before runtime changes.
- [ ] Implement scoped user-token exchange with explicit same-realm provisioning and original MFA preservation; verify real boundaries.
- [ ] Add failing local file/possession/activation tests; implement local key pages with guarded routes and existing design system.
- [ ] Add failing exact-scope recipient/rewrap tests; implement transfer pages and matching Gateway client.
- [ ] Verify secret-free requests, cancellation, concurrency and historical keys; run Nx checks and server-runtime gate, update required architecture docs, commit owned files and write report.

### Task 4: Coordinator integration and independent review

- [ ] Compare exact DTOs, auth claims, cryptographic vectors and lifecycle semantics across packages.
- [ ] Review each worker diff for approved requirements and code quality; route concrete fixes back to its owner.
- [ ] Run final focused Gateway/Postgres, frontend build/lint/test, Studio Nx/runtime and cross-package checks feasible in the local environment.
- [ ] Mark only verified proposal tasks complete. Report actual checks and explicit environmental limits; do not deploy or reset data.
