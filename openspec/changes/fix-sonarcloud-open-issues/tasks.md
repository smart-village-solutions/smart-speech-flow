# Implementation Tasks — Eliminate the Current SonarCloud Backlog

## 0. Coordination and Baseline

- [x] 0.1 Confirm implementation approval and focused-PR strategy.
- [x] 0.2 Refresh the live `main` analysis and record its immutable baseline.
- [x] 0.3 Create an isolated worktree from `origin/main`.
- [x] 0.4 Install CI-equivalent development and gateway dependencies.
- [x] 0.5 Run the hermetic backend baseline: 1,853 passed, 25 skipped, 16 deselected.
- [x] 0.6 Validate this re-baselined OpenSpec change with strict validation.
- [x] 0.7 Commit the reviewed re-baseline before implementation starts (`f6455da`).

## 1. PR-1 — Container Supply Chain (5 Findings)

- [x] 1.1 Export the five issue keys and confirm their current lines.
- [x] 1.2 Use the existing SonarCloud findings as analyzer RED evidence and verify behavior through real image builds and smokes.
- [x] 1.3 Implement exact wheel acquisition/build and binary-only runtime installation for all five images.
- [x] 1.4 Run Dockerfile tests, dependency analysis, five image builds, five import/health smokes, and CUDA checks.
- [x] 1.5 Complete independent review, push, and open the focused PR.
- [x] 1.6 Record SonarCloud PR analysis: [PR #367](https://github.com/smart-village-solutions/smart-speech-flow/pull/367) reports zero open PR issues, an `OK` Quality Gate, A/A/A new-code ratings, and 0.0% new duplication.

## 2. PR-2 — Frontend and Token Checks (14 Findings)

- [ ] 2.1 Export the fourteen issue keys and confirm their current lines.
- [ ] 2.2 Add focused tests where regex, semantics, or accessibility behavior changes.
- [ ] 2.3 Fix all frontend TypeScript, JavaScript, HTML, and shell findings without changing user flows.
- [ ] 2.4 Run clean install, tests, lint, build, and token checks.
- [ ] 2.5 Review, resolve findings, push, and open the focused PR.
- [ ] 2.6 Record SonarCloud PR analysis and PR URL.

## 3. PR-3 — Gateway Routes and Authentication (19 Findings)

- [ ] 3.1 Export the nineteen issue keys and confirm their current lines.
- [ ] 3.2 Add characterization tests for behavior-sensitive route or application changes.
- [ ] 3.3 Fix the application, realtime-ticket, route, and Studio login directory findings.
- [ ] 3.4 Run targeted application, route, authentication, and OpenAPI tests plus Python quality checks.
- [ ] 3.5 Review, resolve findings, push, and open the focused PR.
- [ ] 3.6 Record SonarCloud PR analysis and PR URL.

## 4. PR-4 — Telemetry, Feedback, and Pipeline (27 Findings)

- [ ] 4.1 Export the twenty-seven issue keys and confirm their current lines.
- [ ] 4.2 Add characterization tests for exception hierarchy, telemetry taxonomy, and type-sensitive paths.
- [ ] 4.3 Fix feedback, telemetry, pipeline-admission, runtime-policy, and translation findings.
- [ ] 4.4 Run targeted feedback, telemetry, pipeline, runtime-policy, and translation tests plus Python quality checks.
- [ ] 4.5 Review, resolve findings, push, and open the focused PR.
- [ ] 4.6 Record SonarCloud PR analysis and PR URL.

## 5. PR-5 — Session State (13 Findings)

- [ ] 5.1 Export the thirteen issue keys and confirm their current lines.
- [ ] 5.2 Add characterization tests for every affected session-manager and session-store branch.
- [ ] 5.3 Refactor cognitive complexity and resolve duplication or redundant-expression findings.
- [ ] 5.4 Run session manager, store, persistence, lifecycle, and tenant-isolation tests plus Python quality checks.
- [ ] 5.5 Review, resolve findings, push, and open the focused PR.
- [ ] 5.6 Record SonarCloud PR analysis and PR URL.

## 6. PR-6 — Realtime Transport (22 Findings)

- [ ] 6.1 Export the twenty-two issue keys and confirm their current lines.
- [ ] 6.2 Add characterization tests for public query parameters, async boundaries, and WebSocket behavior.
- [ ] 6.3 Fix session-route, WebSocket, monitor, and polling findings while preserving protocol contracts.
- [ ] 6.4 Run route, WebSocket, polling, monitoring, OpenAPI, and tenant-isolation tests plus Python quality checks.
- [ ] 6.5 Review, resolve findings, push, and open the focused PR.
- [ ] 6.6 Record SonarCloud PR analysis and PR URL.

## 7. PR-7 — Feedback Test Quality (28 Findings)

- [ ] 7.1 Export the twenty-eight issue keys and confirm their current lines.
- [ ] 7.2 Restrict exception assertions, use pytest state-management fixtures, and split assertions without weakening checks.
- [ ] 7.3 Run every modified feedback test module and the related production suite.
- [ ] 7.4 Review, resolve findings, push, and open the focused PR.
- [ ] 7.5 Record SonarCloud PR analysis and PR URL.

## 8. PR-8 — Remaining Test Quality (35 Findings)

- [ ] 8.1 Export the thirty-five issue keys and confirm their current lines.
- [ ] 8.2 Correct exception assertions, temporary state, and composite assertions without reducing coverage.
- [ ] 8.3 Run every modified test module and related production suites.
- [ ] 8.4 Review, resolve findings, push, and open the focused PR.
- [ ] 8.5 Record SonarCloud PR analysis and PR URL.

## 9. Final Integration Evidence

- [ ] 9.1 Confirm all eight PRs are merged into `main` or record the packages still awaiting merge.
- [ ] 9.2 Run the hermetic backend suite with coverage at or above 80%.
- [ ] 9.3 Run frontend clean install, tests, lint, build, and token checks.
- [ ] 9.4 Validate this OpenSpec change with `openspec validate fix-sonarcloud-open-issues --strict`.
- [ ] 9.5 Run a fresh SonarCloud analysis on the integrated revision.
- [ ] 9.6 Confirm zero open issues, an `OK` Quality Gate, A ratings, and required coverage/duplication thresholds.
- [ ] 9.7 Record final analysis ID, revision, timestamp, test evidence, and any controlled-environment skips.
- [ ] 9.8 Mark every task complete only after its evidence exists.
