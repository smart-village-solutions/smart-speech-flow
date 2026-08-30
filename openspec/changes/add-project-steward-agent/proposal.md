# Change: Add an autonomous project stewardship agent

## Why

The delivery plan, GitHub issues, pull requests, and OpenSpec changes need a
single, evidence-based stewardship workflow. The team also needs project minutes
that turn decisions into traceable, prioritized follow-up work.

## What Changes

- Add a repository-versioned Codex `project-steward` plugin/skill.
- Give the steward governed GitHub issue maintenance and pull-request reading
  workflows through the authenticated GitHub CLI.
- Add evidence-based delivery-plan reconciliation and next-priority ranking.
- Add English, privacy-minimizing meeting minutes under `docs/meeting-notes/`.
- Require all local stewardship changes to use a dedicated branch and a
  reviewable pull request; prohibit deletion, issue closure, and pull-request
  merging.

## Impact

- Affected specs: `project-steward-agent` (new capability).
- Affected code: new plugin and helper scripts; project-status synchronization;
  documentation and validation tests.
- External dependency: authenticated GitHub CLI with existing repository and
  project scopes.
