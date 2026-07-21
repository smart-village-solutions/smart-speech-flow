# Change: Eliminate the SonarCloud Backlog

## Why

The SonarCloud analysis of `main` at commit `3ea99a9` on 2026-07-20 reports a failed Quality Gate and 101 open issues. The backlog contains 33 vulnerabilities, 2 bugs, and 66 code smells. The failed gate is caused by the new-code security rating of C.

The existing task list was based on an obsolete 332-issue snapshot and marks work as complete that is contradicted by the current analysis. This change re-baselines the work and provides disjoint work packages that can be implemented safely by parallel agents.

## What Changes

- Eliminate all 101 SonarCloud issues from the 2026-07-20 baseline.
- Validate user-controlled values before they reach frontend URLs, WebSocket connections, or logs.
- Replace incorrect Python exception logging without exposing exception or user data.
- Make Python container dependency installation pinned, reproducible, and binary-only at runtime.
- Correct test constructs that can hide failures or are classified incorrectly by SonarCloud.
- Raise overall backend line coverage from 73.4% to at least 80% after remediation.
- Make the SonarCloud Quality Gate and coverage threshold enforceable in CI.
- Organize implementation into disjoint agent-owned work packages with measurable issue-count reductions.

## Success Criteria

- SonarCloud reports zero open issues on `main` after a fresh analysis.
- The Quality Gate reports `OK`.
- Security, reliability, and maintainability ratings are A.
- New-code coverage remains at or above 84.8%.
- Overall backend line coverage is at least 80%.
- New-code duplication remains at or below 3%.
- All security hotspots are reviewed.
- Backend tests, frontend lint/build/tests, and all four container smoke checks pass.
- No issue is hidden with `NOSONAR`, a broad exclusion, or a weakened Quality Profile.

## Impact

- Affected specs: `code-quality`
- Affected code:
  - `services/api_gateway`
  - `services/frontend`
  - `services/api_gateway/Dockerfile`
  - `services/asr/Dockerfile`
  - `services/translation/Dockerfile`
  - `services/tts/Dockerfile`
  - service dependency lock files
  - targeted files under `tests`
  - SonarCloud and coverage CI configuration
- Operational impact:
  - container builds become stricter and may require a controlled wheel-builder stage
  - logs contain less user-controlled data
  - CI rejects regressions instead of reporting advisory warnings

## Non-Goals

- Redesigning product APIs, session behavior, or deployment topology
- Refactoring code that is unrelated to a current finding or the coverage target
- Weakening SonarCloud rules, the Quality Gate, or scanner scope to reduce the count
- Archiving unrelated OpenSpec changes as part of remediation PRs
- Solving general formatting, typing, or complexity debt not represented by this baseline

## Baseline

The implementation SHALL use this immutable planning baseline and refresh live state before each merge:

- Project: `smart-village-solutions_smart-speech-flow`
- Branch and commit: `main` at `3ea99a9`
- Analysis: 2026-07-20 18:50 UTC
- Open issues: 101
- Vulnerabilities: 33
- Bugs: 2
- Code smells: 66
- Overall coverage: 73.4% (`1,415` uncovered of `5,321` lines to cover)
- New-code coverage: 84.8%
- New-code duplication: 0.0%
