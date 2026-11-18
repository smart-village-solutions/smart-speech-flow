# Recording Key Convenience Implementation Plan

> **For agentic workers:** Use subagent-driven-development for parallel Studio and SSF implementation, with independent review before completion.

**Goal:** Offer Studio-configured local passphrase TXT backup/import and retain unlocked keys only in the existing authenticated SSF tab.

**Architecture:** Studio resolves `recording.passphraseFileEnabled` from tenant override, installation default, then false. SSF validates the policy, exposes its effective flag to authenticated staff, and offers entirely local file processing. The existing in-memory key vault remains tab-local and is invalidated on authentication and identity changes.

**Tech Stack:** TypeScript, React, Web Crypto, Python/FastAPI, Studio plugin-ssf, Vitest, pytest.

**Spec:** `openspec/changes/add-recording-key-convenience/design.md`

## Global Constraints

- No passphrase or unlocked-key persistence, cross-tab key sharing, or server transmission of passphrases.
- Existing tab navigation preserves unlock; reload and new tabs require unlock.
- Export/import are optional and default to disabled, with installation defaults and tenant overrides in Studio.
- Existing user changes in the original workspaces remain untouched.
- User authorized implementation in both repositories on 2026-11-18.

## Task 1: Studio configuration producer

Worktree: `/root/projects/studio-key-convenience`.
Files: existing `packages/plugin-ssf` recording schemas, normalization, template/tenant configuration UI, runtime serialization and their tests; relevant Studio documentation.
Interface produced: effective strict boolean `recording.passphraseFileEnabled`, optional input for backwards compatibility, fallback false; effective changes alter configuration revision.

- [x] Read Studio AGENTS, development rules and applicable skills; inspect existing recording retention inheritance and UI.
- [x] Add failing tests for disabled fallback, installation default, tenant true/false override, reset, invalid input and revision changes.
- [x] Implement through existing recording configuration paths, including localized installation and tenant controls.
- [x] Run focused tests, type checks and required runtime checks; update documentation and record exact results.

## Task 2: SSF runtime policy consumer and tab lifecycle

Worktree: `/root/projects/ssf-key-convenience`.
Files: `services/api_gateway/studio_v2.py`, existing authenticated recording routes and tests; `services/frontend/src/app/auth`, router/providers, key-vault and key hooks/tests.
Interface produced: authenticated `GET /api/admin/recording/key-policy` returns `{passphrase_file_enabled: boolean}`; missing Studio policy returns false. Frontend identity changes and logout invalidate pending key holds.

- [x] Add failing gateway tests for policy true, false, missing and authenticated access.
- [x] Add optional strict boolean Studio policy field and expose effective flag through the staff recording route without weakening existing authorization.
- [x] Add failing lifecycle tests for detected expiry, identity change and unlock completing after invalidation.
- [x] Preserve tab-local memory only, connect all lifecycle invalidations and prevent stale async holds.
- [x] Run focused pytest and Vitest checks and report files and results.

## Task 3: SSF local TXT workflow

Files: `services/frontend/src/domain/recording` repository/types, `features/keys` forms and local file utilities, `i18n/locales/{de,en}.json`, focused tests.
Interface consumed: key-policy endpoint above. File format: versioned application header and JSON-encoded passphrase in TXT, preserving Unicode and whitespace; bounded local import.

- [x] Add failing unit tests for file round trips, malformed/oversized imports and explicit download URL cleanup.
- [x] Implement local file utilities without network calls.
- [x] Add repository and UI tests for disabled policy, export after successful key creation/unlock, no export after failure and file-assisted unlock.
- [x] Implement localized controls and explicit plaintext-file guidance. Keep passphrase only in transient UI memory, clear on completion/unmount, and require re-entry for later export.
- [x] Run focused tests, lint and frontend build.

## Task 4: Integration and review

- [x] Review both diffs against the spec and verify the same field name and false fallback end to end.
- [x] Independently review implementation and fix material findings.
- [x] Run relevant regression suites, OpenSpec strict validation and required repository checks.
- [x] Update task status and user documentation with verified outcomes and material limitations.

## Execution notes

Changes remain on isolated `feat/recording-key-convenience` branches. SSF starts
from `f6b544dd`; Studio starts from `45c99cefa` (existing recording administration,
not old main). No deployment, push or merge is part of this implementation.

Real-browser coverage uses `e2e/recording-passphrase.spec.ts` for local TXT
processing. Tab lifecycle is validated through shared hooks, actual auth-module
callbacks and vault regressions; no live Keycloak browser environment was used.
The independent review's shared-key-observation finding was fixed and re-reviewed.
