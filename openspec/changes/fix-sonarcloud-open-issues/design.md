## Context

The live backlog is large in count but narrow in root causes. Five disjoint implementation streams account for all 101 findings. Parallel work is safe only when every agent owns a fixed production and test file set. Container dependency remediation is the critical path because CUDA and Python wheel compatibility require real image builds.

Several active OpenSpec changes overlap with code quality. This change remains the single source of truth for SonarCloud remediation. Broader policy consolidation and archival of obsolete changes are handled separately and MUST NOT be mixed into remediation PRs.

## Goals / Non-Goals

### Goals

- Close every finding in the fixed baseline without changing documented product behavior.
- Remove the security findings that make the current Quality Gate fail.
- Let agents implement independent work packages without write conflicts.
- Preserve public HTTP, WebSocket, and OpenAPI contracts.
- Improve tests before relying on them as the regression gate.
- Establish reproducible runtime dependency installation for all Python images.

### Non-Goals

- Product feature development
- API or protocol redesign
- General cleanup outside the baseline
- Scanner suppression as a substitute for remediation
- Changing production GPU requirements without explicit review

## Issue Ledger

| Work package | Owner | Findings | Rules | Owned production files |
|---|---|---:|---|---|
| WP-A Backend routes | Agent A | 20 | `python:S8572`, `pythonsecurity:S5145`, `python:S1192` | `services/api_gateway/routes/{admin,circuit_breaker,customer,session}.py`, `services/api_gateway/app.py` |
| WP-B Backend core | Agent B | 25 | `python:S8572`, `pythonsecurity:S5145`, `python:S7483` | API gateway WebSocket, storage, validation, monitoring, fallback, health, and circuit-breaker core files listed in `tasks.md` |
| WP-C Frontend | Agent C | 32 | `tssecurity:S5145`, `tssecurity:S7044`, `tssecurity:S8476`, `tssecurity:S8480`, `typescript:S7754`, `typescript:S9011` | `services/frontend` |
| WP-D Containers | Agent D | 16 | `docker:S8541`, `docker:S8544` | four service Dockerfiles and Python dependency lock files |
| WP-E Tests | Agent E | 8 | `python:S2187`, `python:S5778`, `python:S5779`, `python:S5958`, `python:S8714` | four test files listed in `tasks.md` |

Expected issue counts after the recommended merge order are `101 -> 93 -> 61 -> 41 -> 16 -> 0`. A deviation means the coordinator MUST refresh the ledger before the next merge.

## Agent Contract

- Each agent SHALL claim exactly one work package and edit only its owned files.
- Shared files such as workflow configuration, `pyproject.toml`, and `sonar-project.properties` belong to the coordinator unless explicitly assigned. Frontend package manifests and their lock file belong to WP-C.
- If a fix requires an unowned file, the agent SHALL stop that part, report the dependency, and continue with non-blocked owned work.
- Agents SHALL report changed files, tests executed, results, remaining risks, and the expected Sonar issue reduction.
- Agents SHALL not change Quality Profiles, exclusions, issue status, or gate thresholds.
- Agents SHALL not use `NOSONAR`. A suspected false positive requires coordinator review and documented evidence.
- Every PR SHALL be rebased on the latest `main` and receive its own SonarCloud PR analysis.

## Decisions

### Decision: Validate at trust boundaries

Frontend session identifiers and connection inputs will be validated before URL or WebSocket construction. Allowed WebSocket protocols are `ws` and `wss`; URL path segments are encoded only after validation. Logs will contain safe state, counts, or generated correlation identifiers instead of raw user-controlled values.

### Decision: Use exception logging only in active exception handlers

The 41 `python:S8572` findings will be fixed with `logger.exception()` inside the corresponding `except` blocks. Messages will not interpolate exception text or user input. Where traceback text may itself contain sensitive input, the code will log a safe message and structured non-sensitive metadata.

### Decision: Preserve the polling API contract

The Python parameter that conflicts with timeout-context semantics may be renamed internally, but the HTTP query parameter remains `timeout` through an explicit FastAPI alias. OpenAPI and request behavior must remain unchanged.

### Decision: Build wheels before runtime installation

Runtime images will install exact, reviewed dependencies from a controlled wheel set. The preferred sequence is:

1. Resolve exact versions into service-specific lock files.
2. Download available wheels and build unavoidable source distributions in a builder stage.
3. Install into the runtime image with `--no-index` and `--only-binary=:all:` from the controlled wheel directory.
4. Pin direct installations such as pip, torch, torchvision, and torchaudio and align their CUDA wheel index with the base image.

If a required package has no compatible Python 3.12 wheel, the builder stage may create it. Source build execution in the runtime stage is not acceptable.

### Decision: Fix the load-test classification explicitly

`tests/load/test_production_load.py` must either expose a collectable `@pytest.mark.load` test with assertions or move to a script location. Broad Sonar exclusions are not acceptable. The selected treatment must keep documented load-test commands accurate.

### Decision: Raise coverage after code stabilization

Coverage work starts only after all five remediation packages are merged. It targets approximately 351 additional covered lines, prioritizing circuit-breaker routes, enhanced audio validation, WebSocket polling, and WebSocket management. Coverage tests must assert behavior and may not execute lines solely to increase the metric.

## Merge Strategy

Implementation may run in parallel. Merge order is:

1. WP-E Tests
2. WP-C Frontend
3. WP-A Backend routes
4. WP-B Backend core
5. WP-D Containers after all image checks pass
6. Coverage wave
7. Coordinator validation and CI enforcement

The container package may begin immediately but merges last because failed GPU imports or health checks are release blockers.

## Risks / Trade-offs

- `logger.exception()` can increase log volume and expose exception text.
  - Mitigation: use safe static messages, avoid interpolating exception values, and add log-capture tests for sensitive fields.
- URL validation can accidentally reject existing valid identifiers.
  - Mitigation: derive validation from backend contracts and test valid, boundary, and injection cases.
- CUDA and PyTorch wheel versions may be incompatible with the current CUDA 13 base images.
  - Mitigation: document and test the supported matrix before merge; do not silently downgrade GPU behavior.
- Existing circuit-breaker tests use real threads, fixed ports, and timing windows.
  - Mitigation: use dynamic ports, guaranteed cleanup, and repeat the targeted suite three times.
- A Sonar analyzer update may add findings during the work.
  - Mitigation: preserve the immutable baseline for accountability, add new findings to the ledger, and require zero open issues at completion.
- Parallel agents may edit shared tests or configuration.
  - Mitigation: enforce the ownership table and reserve shared configuration for the coordinator.

## Rollback Plan

- Each work package is delivered as an independent PR and commit series.
- Revert only the failing package if a regression appears.
- Do not revert or weaken the Quality Gate to unblock a merge.
- Container changes require retention of the last known-good image tags until production smoke checks pass.

## Completion Evidence

The coordinator records the following in `tasks.md` before marking the change complete:

- final Sonar analysis ID, commit, and timestamp
- final issue totals and ratings
- backend test and coverage summary
- frontend lint, build, test, audit, and Fallow summary
- four container build and health-smoke results
- any false-positive decisions with evidence and owner approval
