# Project Steward Design

## Context

Smart Speech Flow has several active OpenSpec changes, a GitHub delivery project,
and a repository-maintained project-status snapshot. The team needs a dedicated
Codex agent that can keep these sources aligned, determine the next operational
priorities, turn meeting notes into auditable follow-ups, and work directly with
GitHub issues and pull requests.

The agent must understand the product goal: reliable, accessible, multilingual
communication between public-administration staff and citizens. It must protect
that goal when it ranks work; work that unblocks a must-have delivery, reduces a
security, privacy, or production risk, or protects the critical conversation
flow takes precedence over unrelated improvements.

## Goals

- Provide a reusable `project-steward` Codex plugin/skill with a focused project
  governance role.
- Ground every assessment in repository plans, OpenSpec changes, GitHub issues,
  pull requests, and the GitHub Project snapshot.
- Autonomously maintain evidence-backed project-plan data and create or edit
  GitHub issues.
- Convert supplied meeting notes into versioned English Markdown minutes under
  `docs/meeting-notes/`.
- Rank the next three to five actions with a concise, evidence-backed rationale.
- Read pull-request metadata, diffs, reviews, and checks to evaluate delivery
  impact.
- Preserve normal repository governance: changes are committed on a dedicated
  branch and proposed through a pull request; the agent never merges.

## Non-Goals

- Replacing human strategic governance or silently redefining the product's
  priority classes.
- Merging pull requests, deleting GitHub content, or closing issues.
- Storing raw meeting transcripts, secrets, or unnecessary personal data.
- Introducing a separate task tracker or a duplicate priority model.

## Architecture

The implementation is a repository-versioned Codex plugin named
`project-steward`. Its central skill contains the role, source-precedence rules,
action boundaries, and repeatable workflows. Small deterministic helper scripts
collect repository and GitHub evidence and validate proposed local changes. The
skill delegates GitHub operations to the authenticated GitHub CLI already used
by the repository environment.

```text
Repository plans + GitHub evidence + supplied meeting notes
                         |
                         v
                 Project Steward skill
              /          |           \
             v           v            v
    priority recommendation  issue/plan sync  meeting minutes
             \           |            /
                         v
           dedicated branch and reviewable PR
```

### Source precedence

The steward resolves conflicting information in this order:

1. Explicit project decisions captured in approved meeting minutes or direct
   user instructions.
2. Current GitHub issue and pull-request evidence, including checks and
   reviews.
3. OpenSpec proposals and task completion state.
4. `apps/project-report/src/data/project-status.json` as the operational
   delivery-plan snapshot.
5. `ROADMAP.md` as strategic context, not as a current delivery-status source.

It must report a conflict rather than silently choosing between contradictory
sources of the same precedence.

### Priority policy

For each priority run, the steward orders actionable work using these criteria:

1. Must-have work and committed deadlines.
2. Blocking dependencies and the critical delivery path.
3. Security, data-protection, and production-operability risks.
4. Work with sufficient implementation readiness before work that remains
   materially unclear.
5. Expected delivery value relative to effort and available budget.

The steward may autonomously update the immediate work order and work-package
status when evidence supports it. A change to the strategic priority class must
include its evidence, rationale, and expected impact in the plan and minutes.
When it exposes a genuine conflict, the steward creates a decision issue instead
of silently changing the product intent.

### GitHub operations

The skill uses `gh issue list`, `gh issue view`, `gh issue create`, and
`gh issue edit` for issue work. It uses `gh pr list`, `gh pr view`, `gh pr diff`,
and `gh pr checks` to assess pull requests. Before mutating GitHub it verifies
the active account and required scopes. It follows existing issue and pull
request templates, links relevant work-package and OpenSpec identifiers, and
records the evidence it used.

The steward never deletes GitHub content, closes issues, approves or merges pull
requests, changes repository permissions, or exposes tokens and other secrets.

### Meeting minutes

For supplied notes, the steward creates
`docs/meeting-notes/YYYY-MM-DD-<topic>.md`. Each file includes the meeting
context, decisions, prioritized actions, owners, deadlines, risks, and the
resulting GitHub or plan changes. Minutes are concise, English, and minimize
personal data; raw transcripts and secrets are excluded.

### Change workflow

Local plan or minutes updates are made in a dedicated `codex/project-steward-*`
branch. The steward validates JSON and Markdown conventions, runs the relevant
status-sync validation, commits only its own files, and opens a pull request.
It does not merge that pull request.

## Workflows

### Reconcile project status

The steward gathers OpenSpec, the project-status snapshot, open GitHub issues,
and active pull requests. It reports discrepancies, updates only evidence-backed
fields, and creates missing or malformed tracking issues when required.

### Process meeting notes

The steward extracts decisions and actions from supplied notes, determines their
effect on work packages, creates or edits justified issues, updates the delivery
plan, and creates the versioned meeting minutes.

### Assess pull-request impact

The steward reads the pull request description, linked issues, diff, reviews,
and check results. It maps the work to plan items, identifies blocked or
unverified acceptance criteria, and updates the plan only when the evidence is
strong enough.

### Report next priorities

The steward produces the next three to five actions, each with its priority
rationale, source references, dependency status, owner where known, and a clear
next action. It distinguishes facts, inferences, and decisions needed.

## Risks and Mitigations

- **Plan drift caused by stale evidence**: refresh GitHub and OpenSpec evidence
  before every write and record the refresh time.
- **Overconfident reprioritization**: apply the fixed priority policy, preserve
  strategic classes unless evidence justifies a documented change, and create a
  decision issue for unresolved conflicts.
- **Unsafe autonomous mutation**: prohibit deletions, closures, merges,
  permission changes, and secret handling; route repository updates through a
  reviewable PR.
- **Sensitive meeting content**: retain only the minimum necessary decisions and
  actions in the repository minutes.

## Validation

- Validate the plugin manifest and its skill instructions.
- Test source-precedence and priority decisions with fixture data.
- Test generated minutes and project-status changes against their schemas and
  existing status-sync tests.
- Verify GitHub read commands against the current repository without mutating
  it; cover issue creation/editing with non-production fixtures or explicit
  test issues.
