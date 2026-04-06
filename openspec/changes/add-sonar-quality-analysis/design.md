## Context

The project already contains a dedicated GitHub Actions workflow for code quality checks. Sonar should complement that pipeline by adding maintainability and quality-gate visibility without creating redundant or conflicting checks.

The repository is primarily Python-based, with a smaller TypeScript frontend. The initial Sonar integration should focus on practical value and low operational friction.

## Goals / Non-Goals

- Goals:
  - Add centralized quality analysis and PR feedback
  - Preserve the current quality toolchain
  - Minimize CI duplication and maintenance overhead
  - Support future expansion to coverage and multi-language analysis
- Non-Goals:
  - Replace existing lint/security jobs
  - Enforce every Sonar rule from day one
  - Build a self-hosted Sonar platform in this change

## Decisions

- Decision: Use **SonarCloud** as the default target.
  - Why: best fit with the existing GitHub Actions setup, lower operational overhead, easier PR integration.

- Decision: Keep existing CI jobs and add Sonar as an additional analysis stage.
  - Why: Sonar adds value on top of current tooling but does not replace formatting, security, or type checks.

- Decision: Start with repository-level analysis and a conservative quality gate.
  - Why: avoids blocking adoption with a large backlog of legacy findings.

- Decision: Scope the first rollout to active source directories and explicitly exclude generated, archived, and operational data paths.
  - Why: prevents noisy results and keeps analysis relevant.

## Alternatives Considered

- Self-hosted SonarQube first:
  - rejected as default because it adds infrastructure and credential management complexity immediately.

- Replacing existing checks with Sonar only:
  - rejected because Sonar is not a drop-in replacement for formatting, Bandit, or pip-audit.

- Frontend-only or backend-only rollout:
  - rejected because both areas contribute to code health, even if Python remains the main focus.

## Risks / Trade-offs

- Risk: Sonar introduces noisy findings on legacy code.
  - Mitigation: start with a conservative gate and document remediation phases.

- Risk: CI runtime increases.
  - Mitigation: add Sonar as a distinct analysis job and reuse existing pipeline outputs where possible.

- Risk: Secret/configuration drift.
  - Mitigation: document required secrets, project key, organization, and onboarding steps.

- Risk: Hosted-service acceptance may be blocked by policy.
  - Mitigation: keep configuration portable enough that a later move to SonarQube remains possible.

## Migration Plan

1. Add proposal-approved Sonar configuration
2. Add Sonar job to GitHub Actions
3. Configure repository secret(s) and project binding
4. Run non-blocking validation on a PR
5. Enable the agreed quality gate behavior
6. Document onboarding and operational ownership

## Open Questions

- Which Sonar organization/project key should be used?
- Should the initial quality gate be blocking on pull requests immediately, or only after baseline cleanup?
- Should test coverage be uploaded in the first rollout or as a follow-up?
