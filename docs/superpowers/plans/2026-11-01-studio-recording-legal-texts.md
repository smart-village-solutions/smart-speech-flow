# Studio Recording Legal Texts Implementation Plan

> **For agentic workers:** Use executing-plans to implement these tasks sequentially. The user authorized the existing recording flow integration.

**Goal:** Show Studio's documentation consent, bilateral releases and recording status in the existing conversation recording flow.

**Architecture:** Extend optional runtime content and existing recording evidence. Preserve fail-closed recording policy checks. Require a fresh employee release for each section; guest evidence remains bound to served HTML.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, React, TypeScript, Zod, pytest, Vitest.

**Spec:** `openspec/changes/integrate-studio-recording-legal-texts/design.md`.

## Global Constraints

- Documentation and PRs are English; counsel wording is private tenant content.
- No quality mode, automatic translations, policy enablement or retention changes.
- Source-language fallback must carry its real language; preserve statutory notices.
- Missing legal content preserves existing behavior.

## Task 1: Runtime legal content

Files: new `services/api_gateway/studio_legal.py`; modify `studio_v2.py`, `studio_content.py`, `content_responses.py`; test `tests/test_studio_recording_legal_texts.py`.

- [ ] Write parser, source-locale, sanitizer, tenant isolation and content-route tests using synthetic wording; observe failure.
- [ ] Implement optional validated legal groups, sanitization, locale resolution and display status responses.
- [ ] Run focused runtime/content tests and inspect results.

## Task 2: Recording evidence

Files: `recording/consent_text.py`, `recording/session_state.py`, `recording/session_service.py`, `recording/consent_evidence.py`, `routes/recording_session.py`; test `tests/test_studio_recording_legal_texts.py` and existing recording suites.

- [ ] Add tests for documentation consent versus quality wording, resumed release, employee text mismatches, edits during open requests, refusal and archived evidence; observe failure.
- [ ] Implement source-versioned guest wording and employee request digest validation, persisted release evidence and live revalidation.
- [ ] Run recording consent/state/store/route suites.

## Task 3: Conversation UI

Files: content and recording domain types/mappers/repositories; recording dialogs/hooks/indicator; admin conversation screen; focused existing frontend tests.

- [ ] Write tests for complete Studio wording/choice labels, source-language identification, resumed employee dialog, cancellation, status/liveness and absent-block behavior; observe failure.
- [ ] Render safe rich text, forward employee release digest, and add status wording without hiding stop/liveness information.
- [ ] Run focused frontend tests, TypeScript build, lint and full frontend tests if practical.

## Task 4: Verification and publication

- [ ] Run changed backend typing/formatting/lint, focused integration tests and OpenSpec validation.
- [ ] Review the final diff and resolve findings.
- [ ] Update completed tasks, commit, push and create an English PR under existing user authorization.
- [ ] Observe required checks, merge if allowed, and follow the existing rollout process if the exact candidate and runtime prerequisites permit it. Report any real deployment boundary precisely.
