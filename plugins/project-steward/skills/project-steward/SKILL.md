---
name: project-steward
description: Use when prioritizing Smart Speech Flow delivery work, reconciling its plan with GitHub and OpenSpec, reviewing a PR's delivery impact, or turning supplied meeting notes into follow-up actions.
---

# Project Steward

Keep Smart Speech Flow moving toward reliable, accessible multilingual
communication for public-administration staff and citizens. Ground every plan
change in evidence; distinguish facts, inferences, and decisions needed.

## Establish the current picture

Read `AGENTS.md`, `openspec/project.md`, active OpenSpec changes,
`apps/project-report/src/data/project-status.json`, `ROADMAP.md`, and relevant
repository documentation. Refresh GitHub evidence before a write:

```bash
gh auth status
gh issue list --state open --limit 100
gh pr list --state open --limit 100
gh project item-list 7 --owner smart-village-solutions --limit 100 --format json
node plugins/project-steward/scripts/priority-report.mjs --format markdown
```

Resolve sources in this order: documented project decisions, current GitHub
issues and PRs, OpenSpec state, project-status snapshot, then roadmap. Report a
same-precedence conflict; do not silently choose a status.

## Define the next priorities

Use the priority report as a starting point, then account for current GitHub
evidence. Rank the next three to five actionable items by: must-have commitment
and deadline; blocking dependency; security, privacy, and production risk;
implementation readiness; then delivery value relative to effort and budget.

For every item, state its work-package ID, evidence, dependency state, owner if
known, next action, and why it comes now. You may update immediate work order
and evidence-backed status. A strategic priority-class change needs its
evidence, rationale, and delivery impact in both plan and minutes. Create a
decision issue for an unresolved conflict.

## GitHub workflows

Read a pull request with `gh pr view <number>`, `gh pr diff <number>`, and
`gh pr checks <number>`. Map findings to work packages, acceptance criteria,
dependencies, and unresolved risks before changing plan status.

Use `.github/ISSUE_TEMPLATE/` before `gh issue create`; link each issue to its
work package and OpenSpec change. Use `gh issue edit` only for evidence-backed
title, body, label, or tracking updates. Record the issue URL and evidence in
the plan or meeting minutes.

## Meeting minutes

When supplied notes contain decisions or actions, read
`references/meeting-minutes.md`. Create a concise English document at
`docs/meeting-notes/YYYY-MM-DD-<topic>.md`. Retain decisions, actions, owners,
deadlines, risks, and resulting GitHub/plan changes; omit raw transcripts,
secrets, and unnecessary personal data.

## Safe autonomy

You may create and edit justified issues and update evidence-backed plan data.
For local changes, create a dedicated `codex/project-steward-*` branch, validate
the affected JSON/Markdown, commit only your files, and open a PR. Never delete
content, close issues, merge or approve PRs, change permissions, or expose
credentials. If GitHub authentication or the evidence is insufficient, stop and
report the missing condition.
