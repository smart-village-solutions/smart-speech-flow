# PR 654 Review Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Resolve the open review findings against the approved ordinary-entry behavior and make PR #654 reviewable with passing checks.

**Architecture:** The ordinary entry always renders its two localized UI paragraphs, independently of optional Studio explanations. Preserve the route-keyed read-only reference snapshot, legal wording, activation and recording workflows. Resolve source direction from explicit scripts while leaving undetermined languages automatic; qualify consent wording for supported policies.

**Tech Stack:** React, TypeScript, i18next, Vitest, OpenSpec, existing Python recording-policy contracts.

**Spec:** `openspec/changes/add-read-only-legal-information/specs/studio-content-delivery/spec.md`; user clarification on 2026-11-01: always show the UI introduction and omit Studio explanations from ordinary entry.

## Global Constraints

- Full counsel wording remains in the separate close-only reference dialog; do not restore inline documents or a new API projection.
- No production rollout, Studio mutation, recording-policy change, activation change or retention change.
- Preserve all 20 UI locales and branding nesting. New project documentation and review summaries use English.
- Test the failures before fixing them; do not suppress review findings or quality checks.

## Task 1: Source wording direction

- [x] Add failing tests for Yezidi script and undetermined source locales, including explicit-script overrides and legacy browser fallbacks.
- [x] Add the missing RTL script and avoid maximizing an undetermined language without an explicit script.
- [x] Verify direction and reference-dialog tests.

## Task 2: Authoritative ordinary introduction

- [x] Add failing ordinary-entry tests for stale/updated Studio explanations, language fallback, duplicate prevention and unchanged read-only reference behavior.
- [x] Render UI paragraphs unconditionally; remove the unused explanation selection/snapshot plumbing without changing reference stability or activation.
- [x] Update the approved spec, tests and documentation to make this narrow exception to Studio guest-copy precedence explicit.

## Task 3: Policy-compatible localized copy

- [x] Qualify documentation-consent promises consistently in all 20 catalogues; preserve section-release wording and every unrelated key.
- [x] Verify localisation and branding checks; keep legal declarations untouched.

## Task 4: Verification and review resolution

- [x] Run focused regressions, full frontend tests, lint, build, Fallow, OpenSpec and relevant legal/gateway contracts.
- [x] Review the combined diff independently and address actionable findings.
- [x] Rewrite the PR description around the final approved scope and resolve technically verified obsolete/fixed threads.
- [x] Push without merging or deploying; monitor CI and report exact outstanding merge conditions.

## Verification record

Confirmed the direction and ordinary-entry regressions before the corresponding fixes. Final local verification: 1,655 frontend tests in 177 files, 57 relevant gateway/recording contract tests, build, lint, Fallow (pass, zero dead-code/complexity findings), OpenSpec strict validation and independent review. Source changes do not modify backend content responses, recording policies, legal wording, Studio content or production. Remote checks and merge conditions are reported from the live PR rather than inferred from local results.
