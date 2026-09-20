## Context

The live SonarCloud backlog is broad in count but can be divided by file
ownership. A single repository-wide PR would mix container supply-chain risk,
behavior-preserving Python refactors, frontend semantics, and mechanical test
corrections. Independent PRs based on `origin/main` keep review and rollback
focused.

The existing `fix-sonarcloud-open-issues` change remains the source of truth.
Its former 101-issue ledger is retained in Git history; this design supersedes
that ledger with the 163-issue analysis identified in `proposal.md`.

## Goals / Non-Goals

### Goals

- Close every finding in the immutable baseline without changing documented
  product behavior.
- Prioritize the five container vulnerabilities while preserving compatible
  Python and GPU dependency installation.
- Make every implementation PR file-disjoint and independently reviewable.
- Use existing behavioral tests as characterization coverage and add focused
  regression tests where a control-flow refactor exposes an uncovered branch.
- Verify each package locally and with SonarCloud PR analysis.

### Non-Goals

- Product feature work or public contract redesign
- Opportunistic refactoring outside files with current findings
- Scanner suppression, exclusions, or rule changes
- Automatic merging of remediation PRs

## Package Ledger

| Package | Findings | Scope |
| --- | ---: | --- |
| PR-1 Containers | 5 | Five affected service Dockerfiles and dependency artifacts required for binary-only installation |
| PR-2 Frontend and token checks | 14 | `services/frontend`, including its tests and `scripts/check-tokens.sh` |
| PR-3 Gateway routes and authentication | 19 | Gateway application root, realtime ticket, admin/customer/feedback/login routes, and Studio login directory client |
| PR-4 Telemetry, feedback, and pipeline | 27 | Feedback internals, quality/message telemetry, pipeline admission, runtime policy/metrics, and translation application |
| PR-5 Session state | 13 | `session_manager.py` and `session_store.py` |
| PR-6 Realtime transport | 22 | Session routes, WebSocket manager/monitor, and polling routes |
| PR-7 Feedback tests | 28 | Feedback tests under `tests`, including integration tests |
| PR-8 Remaining tests | 35 | Remaining affected tests under `tests` and `services/api_gateway/tests` |

The package counts sum to 163. A file belongs to exactly one package. If a fix
requires a file owned by another package, it is recorded as a dependency and
implemented in the owning package instead of crossing the boundary.

## Delivery Strategy

Each package uses a dedicated branch from the latest `origin/main`, is
implemented in the isolated `.worktrees/fix-sonarcloud-backlog` workspace, and
targets `main`. Packages are opened sequentially. A later package does not
depend on an unmerged earlier package unless its PR explicitly documents that
dependency.

Subagents may implement or review one package at a time. The coordinator owns
branch transitions, verifies the diff and tests independently, resolves review
findings, pushes the branch, and opens the PR. No agent may edit files outside
the active package.

## Decisions

### Decision: Correct behavior rather than suppress findings

`NOSONAR`, broad exclusions, disabled rules, and issue-status manipulation are
not remediation. Suspected false positives require documented evidence and
maintainer review.

### Decision: Preserve external contracts

Function extraction, constants, annotations, and dependency-injection syntax
may change internals. HTTP paths, query names, response models, WebSocket
messages, authentication semantics, persistence keys, and emitted telemetry
remain stable unless an existing test proves the analyzer is identifying a
real defect in that contract.

### Decision: Treat complexity refactors as behavior-sensitive

The seven cognitive-complexity findings require characterization tests for
affected branches before extraction. Helpers remain private and are split by
one responsibility. Refactors stop if existing behavior is ambiguous rather
than choosing new behavior implicitly.

### Decision: Make test fixes semantically strict

`pytest.raises` blocks contain only the invocation expected to fail;
temporary global changes use `monkeypatch`; composite assertions are split
without dropping checks; async markers and fixtures are retained where the
test contract requires them.

### Decision: Build controlled wheels for runtime images

Runtime stages install only from an exact, controlled wheel set with
`--no-index` and `--only-binary=:all:`. If a dependency lacks a compatible
wheel, a builder stage may build it; runtime execution of package setup scripts
is not accepted. Image build and import/health smoke tests gate the container
PR.

## Verification

Every PR runs the narrowest meaningful tests plus formatting or linting for
its language. Python production refactors also run related route/service tests;
test-only changes run every modified module; frontend changes run clean install,
tests, lint, and build; container changes run builds and service-specific smoke
checks.

Before final completion, the coordinator runs the hermetic backend suite,
frontend verification, OpenSpec strict validation, and a fresh SonarCloud
analysis on the integrated `main` revision. Integration, load, GPU, or
real-system checks that cannot run locally are recorded explicitly and remain
required CI or controlled-environment evidence.

## Risks / Trade-offs

- Binary-only container installation can expose packages without compatible
  wheels. A builder stage and per-image smoke tests contain this risk.
- Complexity refactors can alter exception ordering or cleanup. Focused
  characterization tests and small commits make regressions reviewable.
- Independent PRs can conflict with unrelated feature delivery. Each branch is
  refreshed from `origin/main` immediately before final verification; no
  force-push is used without explicit authorization.
- SonarCloud may add findings during the work. New findings are tracked
  separately while the immutable baseline remains auditable.

## Rollback Plan

Each package is a separate PR and commit series. A failing package can be
reverted without reverting unrelated remediation. The Quality Gate is never
weakened to unblock a package.

## Completion Evidence

The change is complete only when `tasks.md` records all PR URLs, local and CI
test evidence, the final SonarCloud analysis ID and revision, zero open issues,
an `OK` Quality Gate, and the required ratings and coverage thresholds.
