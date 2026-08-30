# Project Steward Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Build an installable, repository-versioned Codex Project Steward that ranks delivery work, governs GitHub issue and PR workflows, and records auditable meeting minutes.

**Architecture:** A repo-local marketplace exposes the `project-steward` plugin and its focused skill. A dependency-free Node helper ranks work from the existing project-status snapshot; the skill combines the report with live OpenSpec and GitHub CLI evidence before applying the defined safety rules.

**Tech Stack:** Codex plugin manifest and skill Markdown; Node.js ESM; Vitest; GitHub CLI; OpenSpec.

**Spec:** `docs/superpowers/specs/2026-08-30-project-steward-design.md`

## Global Constraints

- Use the existing authenticated GitHub CLI; do not add a connector or dependency.
- Preserve source precedence: decisions, GitHub evidence, OpenSpec, project-status snapshot, roadmap.
- Never delete content, close issues, merge PRs, change permissions, or expose secrets.
- Local outputs use a dedicated `codex/project-steward-*` branch and a reviewable PR.
- Minutes are concise, English, privacy-minimizing Markdown under `docs/meeting-notes/`.

### Task 1: Implement the deterministic priority engine

**Files:** Create `plugins/project-steward/scripts/priority-report.mjs` and `plugins/project-steward/scripts/priority-report.test.mjs`.

**Interface:** `rankWorkPackages(report, { limit, today })` returns `{ generatedAt, priorities }`. A priority has `workPackageId`, `title`, `priority`, `rationale`, `dependencyState`, and `source`.

- [x] Write a failing Vitest test that passes a minimal status snapshot and expects the unblocked, must-have package with the earliest deadline to rank first.
- [x] Run `npx vitest run plugins/project-steward/scripts/priority-report.test.mjs`; confirm it fails because the module is absent.
- [x] Implement priority-class, deadline, dependency-readiness, health-risk, and dependency-impact scoring. Provide JSON output by default and Markdown via `--format markdown`.
- [x] Add tests for incomplete dependencies, blocked work, exclusion of completed work, priority tie-breaking, and limits; rerun the test file and confirm it passes.
- [x] Commit only the helper and its tests with `feat: add project steward priority report`.

### Task 2: Package the governed Project Steward skill

**Files:** Create `.agents/plugins/marketplace.json`, `plugins/project-steward/.codex-plugin/plugin.json`, `plugins/project-steward/skills/project-steward/SKILL.md`, and `plugins/project-steward/skills/project-steward/agents/openai.yaml`.

**Interface:** The plugin exposes the `project-steward` skill, which invokes the priority report and GitHub CLI without adding credentials or dependencies.

- [x] Run `python3 /root/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py plugins/project-steward`; confirm it fails before scaffolding.
- [x] Scaffold the plugin into the repository marketplace. The skill must state project goals, evidence collection, source precedence, priority rules, safe `gh` issue and PR commands, audit records, and mutation boundaries.
- [x] Add fixture-based skill scenarios for supported issue creation, prohibited issue closure, and a priority-class conflict.
- [x] Validate with the plugin validator and `python3 /root/.codex/skills/.system/skill-creator/scripts/quick_validate.py plugins/project-steward/skills/project-steward`.
- [x] Commit the marketplace and plugin with `feat: add project steward plugin`.

### Task 3: Add minutes rendering and guidance

**Files:** Create `docs/meeting-notes/README.md` and `plugins/project-steward/skills/project-steward/references/meeting-minutes.md`; modify `priority-report.mjs` and its test.

**Interface:** `renderMeetingMinutes({ date, topic, decisions, actions, risks, sources })` returns the Markdown content for `docs/meeting-notes/YYYY-MM-DD-<topic>.md`.

- [x] Write a failing test using decisions, an owner, a deadline, sources, and a sensitive raw-note field. Expect retained decisions/actions and omission of the raw sensitive field.
- [x] Run the test file; confirm it fails because `renderMeetingMinutes` is absent.
- [x] Implement the minimal renderer. Document the required headings and data-minimization rules in the plugin reference and repository README.
- [x] Rerun tests and commit the minutes work with `docs: add project steward meeting minutes format`.

### Task 4: Verify integration and complete the proposal

**Files:** Modify `openspec/changes/add-project-steward-agent/tasks.md`; include this plan in the final documentation commit.

- [x] Run read-only `gh auth status`, `gh issue list`, `gh pr list`, and `gh project item-list 7 --owner smart-village-solutions --format json`.
- [x] Run `npm --prefix apps/project-report test`, the priority-report tests, plugin validation, skill validation, and `openspec validate add-project-steward-agent --strict`.
- [x] Mark only verified OpenSpec tasks complete, then commit the plan and task updates with `docs: complete project steward proposal`.
