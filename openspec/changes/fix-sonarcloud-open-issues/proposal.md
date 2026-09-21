# Change: Eliminate the Current SonarCloud Backlog

## Why

The SonarCloud analysis of `main` at commit `114574a` on 2026-09-18 reports a
failed Quality Gate and 163 open issues. The previous 101-issue remediation
baseline has been overtaken by subsequent feature delivery and analyzer
updates, so its completed work packages no longer describe the current
backlog.

The live backlog now contains 5 vulnerabilities and 158 code smells across
container builds, frontend code, API gateway production code, and tests. The
five vulnerabilities keep the security rating below A and require an explicit
binary-only dependency-installation decision for every Python runtime image.

## What Changes

- Re-baseline remediation against all 163 open issues from the 2026-09-18
  `main` analysis.
- Resolve every finding through eight file-disjoint implementation packages.
- Preserve public HTTP, WebSocket, OpenAPI, authentication, and persistence
  behavior while simplifying implementation details.
- Correct test constructs without weakening their assertions or excluding
  code from analysis.
- Require focused tests and SonarCloud PR analysis for every package.
- Record final evidence only after all packages have landed on `main` and a
  fresh branch analysis reports the result.

## Success Criteria

- SonarCloud reports zero open issues on `main` after a fresh analysis.
- The Quality Gate reports `OK`.
- Security, reliability, and maintainability ratings are A.
- Overall coverage remains at or above 80%.
- New-code coverage remains at or above the configured Quality Gate threshold.
- New-code duplication remains at or below 3%.
- Backend tests, frontend tests/lint/build, shell checks, and container smoke
  checks pass for their affected packages.
- No issue is hidden with `NOSONAR`, broad exclusions, disabled rules, or a
  weakened Quality Profile.

## Impact

- Affected specs: `code-quality`
- Affected code:
  - five Python service Dockerfiles
  - `services/frontend`
  - `services/api_gateway`
  - `services/translation/app.py`
  - targeted Python tests under `tests` and `services/api_gateway/tests`
- Operational impact:
  - runtime dependency installation becomes binary-only or uses a controlled
    builder stage
  - internal functions and tests are simplified without contract changes
  - eight focused PRs replace one repository-wide remediation PR

## Non-Goals

- Redesigning product APIs, session behavior, authentication, or deployment
  topology
- Addressing unrelated lint, type, dependency, or architecture debt
- Changing Quality Profiles, scanner scope, or Quality Gate thresholds
- Merging or closing unrelated active changes or pull requests

## Immutable Baseline

- Project: `smart-village-solutions_smart-speech-flow`
- Branch and revision: `main` at
  `114574a9789256b8bbc06640af962b769285ca70`
- Analysis ID: `e648dbdd-4091-461b-99e9-684d785faf62`
- Analysis timestamp: 2026-09-18 08:16:39 UTC
- Open issues: 163
- Vulnerabilities: 5
- Bugs: 0
- Code smells: 158
- Severity: 25 critical, 104 major, 34 minor
- Overall coverage: 88.1%
- New-code coverage: 91.40%
- Overall duplication: 0.9%
- New-code duplication: 0.58%
- Quality Gate: `ERROR`

This baseline is immutable for accountability. New findings discovered by PR
or branch analyses are added to the package that introduced or owns the
affected file, but they do not rewrite the baseline count.
