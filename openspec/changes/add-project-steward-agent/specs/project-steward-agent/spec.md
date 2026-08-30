## ADDED Requirements

### Requirement: Project-goal-grounded stewardship

The system SHALL provide a reusable Project Steward agent that evaluates work
against Smart Speech Flow's goal of reliable, accessible, multilingual
communication for public-administration staff and citizens.

#### Scenario: Assessing a proposed task

- **WHEN** the steward assesses a task or pull request
- **THEN** it SHALL state how the work supports, blocks, or risks a project goal
  and cite the evidence used

### Requirement: Evidence-based source reconciliation

The steward SHALL reconcile project information using explicit decisions,
GitHub evidence, OpenSpec state, the project-status snapshot, and the roadmap in
that order of precedence.

#### Scenario: Conflicting current-status sources

- **WHEN** sources of equal precedence contradict each other
- **THEN** the steward SHALL report the conflict and SHALL NOT silently choose a
  status

### Requirement: Autonomous next-priority definition

The steward SHALL autonomously define and maintain the immediate work order
using must-have commitments and deadlines, dependencies, security/privacy and
operability risk, implementation readiness, and value relative to effort and
budget.

#### Scenario: Priority report

- **WHEN** the steward runs a priority assessment
- **THEN** it SHALL identify the next three to five actions with rationale,
  evidence, dependencies, and any required decision

#### Scenario: Strategic priority-class change

- **WHEN** evidence warrants changing a work package's strategic priority class
- **THEN** the steward SHALL record the evidence, rationale, and impact in the
  delivery plan and meeting minutes

### Requirement: Governed GitHub issue and pull-request workflow

The steward SHALL read pull-request metadata, diffs, reviews, and checks, and
SHALL create or edit GitHub issues when supported by evidence and existing
repository conventions.

#### Scenario: Missing follow-up work

- **WHEN** a meeting decision or pull-request finding requires untracked work
- **THEN** the steward SHALL create a linked issue with the appropriate template
  content and plan references

#### Scenario: Pull-request plan impact

- **WHEN** the steward evaluates a pull request
- **THEN** it SHALL identify affected work packages, dependencies, acceptance
  criteria, and unverified risks before updating plan status

### Requirement: Auditable repository meeting minutes

The steward SHALL convert supplied meeting notes into concise, English,
privacy-minimizing Markdown minutes under `docs/meeting-notes/`.

#### Scenario: Recording a meeting

- **WHEN** meeting notes contain decisions or actions
- **THEN** the steward SHALL record decisions, prioritized actions, owners,
  deadlines, risks, and resulting plan or GitHub changes without retaining raw
  transcripts, secrets, or unnecessary personal data

### Requirement: Safe autonomous mutations

The steward SHALL make local plan and minutes changes on a dedicated branch and
through a reviewable pull request. It SHALL NOT delete content, close issues,
merge pull requests, change repository permissions, or expose secrets.

#### Scenario: Updating a project-plan snapshot

- **WHEN** evidence supports a project-plan update
- **THEN** the steward SHALL validate the update, commit only its own changes on
  a dedicated branch, and open a pull request without merging it
