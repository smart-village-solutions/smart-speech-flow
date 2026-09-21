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

- [x] 2.1 Export the fourteen issue keys and confirm their current lines.
- [x] 2.2 Add focused tests where regex, semantics, or accessibility behavior changes.
- [x] 2.3 Fix all frontend TypeScript, JavaScript, HTML, and shell findings without changing user flows.
- [x] 2.4 Run clean install, tests, lint, build, and token checks.
- [x] 2.5 Review, resolve findings, push, and open the focused PR.
- [x] 2.6 Record SonarCloud PR analysis and PR URL.

## 3. PR-3 — Gateway Routes and Authentication (19 Findings)

- [x] 3.1 Export the nineteen issue keys and confirm their current lines.
- [x] 3.2 Add characterization tests for behavior-sensitive route or application changes.
- [x] 3.3 Fix the application, realtime-ticket, route, and Studio login directory findings.
- [x] 3.4 Run targeted application, route, authentication, and OpenAPI tests plus Python quality checks.
- [x] 3.5 Review, resolve findings, push, and open the focused PR.
- [x] 3.6 Record SonarCloud PR analysis and PR URL.

## 4. PR-4 — Telemetry, Feedback, and Pipeline (27 Findings)

- [x] 4.1 Export the twenty-seven issue keys and confirm their current lines.
- [x] 4.2 Add characterization tests for exception hierarchy, telemetry taxonomy, and type-sensitive paths.
- [x] 4.3 Fix feedback, telemetry, pipeline-admission, runtime-policy, and translation findings.
- [x] 4.4 Run targeted feedback, telemetry, pipeline, runtime-policy, and translation tests plus Python quality checks.
- [x] 4.5 Review, resolve findings, push, and open the focused PR.
- [x] 4.6 Record SonarCloud PR analysis and PR URL.

## 5. PR-5 — Session State (13 Findings)

- [x] 5.1 Export the thirteen issue keys and confirm their current lines.
- [x] 5.2 Add characterization tests for every affected session-manager and session-store branch.
- [x] 5.3 Refactor cognitive complexity and resolve duplication or redundant-expression findings.
- [x] 5.4 Run session manager, store, persistence, lifecycle, and tenant-isolation tests plus Python quality checks.
- [x] 5.5 Review, resolve findings, push, and open the focused PR.
- [x] 5.6 Record SonarCloud PR analysis and PR URL.

## 6. PR-6 — Realtime Transport (22 Findings)

- [x] 6.1 Export the twenty-two issue keys and confirm their current lines.
- [x] 6.2 Add characterization tests for public query parameters, async boundaries, and WebSocket behavior.
- [x] 6.3 Fix session-route, WebSocket, monitor, and polling findings while preserving protocol contracts.
- [x] 6.4 Run route, WebSocket, polling, monitoring, OpenAPI, and tenant-isolation tests plus Python quality checks.
- [x] 6.5 Review, resolve findings, push, and open the focused PR.
- [x] 6.6 Record SonarCloud PR analysis and PR URL.

## 7. PR-7 — Feedback Test Quality (28 Findings)

- [x] 7.1 Export the twenty-eight issue keys and confirm their current lines.
- [x] 7.2 Restrict exception assertions, use pytest state-management fixtures, and split assertions without weakening checks.
- [x] 7.3 Run every modified feedback test module and the related production suite.
- [x] 7.4 Review, resolve findings, push, and open the focused PR.
- [x] 7.5 Record SonarCloud PR analysis and PR URL.

## 8. PR-8 — Remaining Test Quality (35 Findings)

- [x] 8.1 Export the thirty-five issue keys and confirm their current lines.
- [x] 8.2 Correct exception assertions, temporary state, and composite assertions without reducing coverage.
- [x] 8.3 Run every modified test module and related production suites.
- [x] 8.4 Review, resolve findings, push, and open the focused PR.
- [x] 8.5 Record SonarCloud PR analysis and PR URL.

## Recorded Package Evidence — 2026-09-20

The [immutable issue ledger](issue-ledger.md) accounts for all 163 baseline keys.
The table records the analyzed remote heads: **all 15 project and required
checks passed for each PR**, while a separate non-blocking
`copilot-pull-request-reviewer` check reported failure. Each SonarCloud PR
analysis reports **0 unresolved PR issues, Quality Gate OK, A/A/A new-code
security/reliability/maintainability ratings, 0.0% new duplication, and 100%
new security hotspots reviewed**.
Coverage below is Sonar's new-code metric; an em dash means it is not reported,
not zero. These are PR results, not evidence of baseline closure on main.

| Package | PR | Verified remote head | Sonar new coverage |
| --- | --- | --- | ---: |
| PR-1 | [#367](https://github.com/smart-village-solutions/smart-speech-flow/pull/367) | `bc6b030` (verified implementation/image-build head) | — |
| PR-2 | [#368](https://github.com/smart-village-solutions/smart-speech-flow/pull/368) | `3406c13` | — |
| PR-3 | [#369](https://github.com/smart-village-solutions/smart-speech-flow/pull/369) | `a1af930` | 94.6% |
| PR-4 | [#370](https://github.com/smart-village-solutions/smart-speech-flow/pull/370) | `5cebce5` | 95.7% |
| PR-5 | [#371](https://github.com/smart-village-solutions/smart-speech-flow/pull/371) | `96e856b` | 89.7% |
| PR-6 | [#372](https://github.com/smart-village-solutions/smart-speech-flow/pull/372) | `f94d934` | 100.0% |
| PR-7 | [#373](https://github.com/smart-village-solutions/smart-speech-flow/pull/373) | `4bda684` | — |
| PR-8 | [#374](https://github.com/smart-village-solutions/smart-speech-flow/pull/374) | `04fea34` | — |

PR #367 also contains a documentation-only reconciliation follow-up. Its latest
head must have green required checks and zero SonarCloud PR issues at handoff;
read the exact current head from the PR. This condition was verified after the
first documentation push on 2026-09-20. The implementation and image-build
evidence remains anchored to `bc6b030`.
All implementation packages passed independent review; review corrections
were rechecked before the remote heads above were recorded.

- **PR-1:** 16 focused tests; five image builds and five import/health smokes;
  CUDA visible in ASR, translation, and TTS. Model weights were absent, so
  production inference and model-ready health were not exercised; degraded
  model health was expected.
- **PR-2:** clean `npm ci`; 617 tests in 86 files; lint, build, token checks,
  and Bash syntax passed. Three new regressions passed after the intended RED
  cases. Existing moderate dependency vulnerability and bundle-size warning
  remain outside this package.
- **PR-3:** final 84 focused tests; 1,864 hermetic passed, 25 skipped,
  16 deselected; 88.45% local overall coverage. Review strengthened ticket
  rejection and shutdown ordering, preserved formatter-stable maintenance
  wiring, and cleared a new S5778 test issue plus low PR coverage. The
  pre-existing admin-language assertion was corrected by its owner in PR-8.
  The 88-column hook/100-column direct formatter conflict remains baseline debt.
- **PR-4:** 210 initial focused tests and 140 after review; 1,886 hermetic
  passed, 25 skipped, 16 deselected; 88.21% overall local coverage. Review
  tightened exception scope and deferred-release detection; subsequent S8714
  and S5958 findings were fixed with concrete exception assertions. Strict
  MyPy retains the same 24 baseline errors; six clean modules pass. A raw
  discovery order reproduces baseline singleton pollution; sorted discovery
  and standard CI pass. Invalid duration keywords still raise TypeError,
  though generated error wording and signature introspection differ.
- **PR-5:** 136 focused tests; 1,870 hermetic passed, 25 skipped,
  16 deselected; 92.31% local changed-line coverage. The baseline contains six,
  not seven, session complexity findings. Strict MyPy retains the same 40
  diagnostics, and baseline reload-order failures remain. Review approved
  with a non-blocking observation: the terminal-filter test reaches memory
  store validation before directly isolating the manager predicate.
- **PR-6:** 463 focused passed, 15 skipped; 1,870 hermetic passed, 25 skipped,
  16 deselected. Review reproduced and fixed stranded presence after
  cancellation, then concurrent double deletion after thread dispatch.
  Final async handlers serialize short ownership transitions with a per-store
  lock, never held across long polls or broadcasts. Strict MyPy retains the
  same 347 baseline diagnostics. S8415 documents existing 404 responses;
  S7483 concerns async timeout parameters. The public `timeout` query and
  the `_poll(..., timeout=...)` coroutine-returning compatibility API remain.
- **PR-7:** 202 PostgreSQL/promtool tests passed with zero skips; 24 production,
  alert, and SQL-policy mutation probes detected. Without optional promtool,
  the controller recorded 150 owned-module passes/40 controlled skips and
  1,853 hermetic passes/29 skips/16 deselections. Four executable alert cases
  skip without promtool; the structured YAML contract always runs.
- **PR-8:** 228 targeted and 150 related tests; 1,853 hermetic passed,
  25 skipped, 16 deselected; 30 behavioral mutation probes detected. Review
  fixed restoration of distinct populated WebSocket manager references and
  verified both successful and failing cleanup. The 11 pipeline cases used
  their allowed validation fallback because ASR/translation/TTS were
  unreachable. Controlled successful route serialization is not live
  inference evidence.

Detailed commands, baseline diagnostics, mutation results, and local artifacts
are recorded in the execution reports; the linked PRs preserve the final
review and validation handoff. No suppression, scanner exclusion, rule change,
or main-branch issue-status manipulation was used.

## 9. Final Integration Evidence

- [x] 9.1 Merge PR-1–PR-8 in order: [#367](https://github.com/smart-village-solutions/smart-speech-flow/pull/367), [#368](https://github.com/smart-village-solutions/smart-speech-flow/pull/368), [#369](https://github.com/smart-village-solutions/smart-speech-flow/pull/369), [#370](https://github.com/smart-village-solutions/smart-speech-flow/pull/370), [#371](https://github.com/smart-village-solutions/smart-speech-flow/pull/371), [#372](https://github.com/smart-village-solutions/smart-speech-flow/pull/372), [#373](https://github.com/smart-village-solutions/smart-speech-flow/pull/373), and [#374](https://github.com/smart-village-solutions/smart-speech-flow/pull/374). Each branch was updated from the preceding integrated revision and all 15 project and required checks passed before its 2026-09-21 merge. A separate non-blocking `copilot-pull-request-reviewer` check reported failure on the final PR heads and did not gate merge.
- [x] 9.2 Run the integrated hermetic backend suite: GitHub Actions run `35583030649` reports 1,931 passed, 29 skipped, and 16 deselected; the integrated SonarCloud analysis reports 89.4% overall coverage.
- [x] 9.3 Run frontend clean install, lint, tests, build, and token checks: GitHub Actions run `35583030606` reports 86 test files and 617 tests passed, a successful production build, and `PASS: tokens present in built CSS`.
- [x] 9.4 Validate the completed change documentation with `openspec validate fix-sonarcloud-open-issues --strict` (passed 2026-09-21).
- [x] 9.5 Run a fresh SonarCloud analysis on integrated revision `cb24ed83a58e1b8e53a59a52632e1cb0db169f9f`: analysis `1a7b237f-d85f-45e1-a941-e44bb543b680` completed on 2026-09-21.
- [x] 9.6 Confirm zero open issues, an `OK` Quality Gate, A security/reliability/maintainability ratings, 92.7% new-code coverage, 0.6% new-code duplication, and 100% reviewed new-code security hotspots. Overall coverage is 89.4% and overall duplication is 0.9%.
- [x] 9.7 Record final evidence: analysis timestamp `2026-09-21T09:25:26Z`; final revision `cb24ed83a58e1b8e53a59a52632e1cb0db169f9f`; successful code-quality workflow `35583030606`; successful backend workflow `35583030649`; 1,931 hermetic tests passed with 29 controlled skips and 16 integration/real-system deselections. The Fallow audit is PR-only and therefore skipped on the final `push` workflow; the blocking frontend lint, test, build, token, SonarCloud, security, type, dependency, code-quality, and Quality Gate jobs passed.
- [x] 9.8 Mark every task complete only after the integrated evidence above exists.
