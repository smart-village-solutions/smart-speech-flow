## ADDED Requirements

### Requirement: Studio-defined feedback forms

SSF SHALL present the feedback form Studio defines for the audience: the guest
form of the guest's language, the staff form, or the installation form on the
start and login pages. When Studio provides no valid form for the audience,
SSF SHALL present the bundled form, which uses the same question ids. Supported
question types are `rating`, `scale` and `longText`; a rating question SHALL
have `min` of at least 1.

#### Scenario: Guest language without a Studio form

- **WHEN** a guest using Arabic opens feedback and Studio does not provide
  Arabic
- **THEN** the bundled form is shown

#### Scenario: Required question

- **WHEN** a required question has no answer
- **THEN** the form cannot be submitted

### Requirement: Answers validated against the rendered form

SSF SHALL store feedback answers by question id together with the audience,
form source, revision, locale and a snapshot of the questions as rendered. It
SHALL validate a submission against the form of its revision, or against the
current form when that revision is no longer known, and SHALL reject it only
when the answers do not fit. Unknown ids, missing required answers, numbers
outside their range and text longer than its limit SHALL be rejected. Free-text
answers SHALL be stored encrypted, and no validation error SHALL contain
submitted text.

#### Scenario: Form changed while open

- **WHEN** Studio publishes a new revision while a form is open and the answers
  still fit the new form
- **THEN** the submission is accepted

#### Scenario: Answers no longer fit

- **WHEN** the answers do not fit the current form
- **THEN** SSF answers 409 without echoing any answer

### Requirement: Staff feedback is authenticated

SSF SHALL accept staff feedback only through `POST /api/admin/feedback` with a
valid staff token and SHALL file it under the token's tenant.

#### Scenario: Feedback from the dashboard

- **WHEN** a logged-in staff member of `tenant-kassel` submits feedback from
  the dashboard
- **THEN** the submission is stored under `tenant-kassel`

### Requirement: Per-answer analytics events

SSF SHALL emit one `feedback_submitted` event per submission and one
`feedback_answer` event per numeric answer, carrying the question id, type,
value and range and opaque references only. Event ids SHALL be derived
deterministically so reconciliation can re-emit them idempotently. Free text
SHALL NOT be emitted.

#### Scenario: Reconciliation after an analytics outage

- **WHEN** feedback was stored while analytics was unavailable and is re-emitted
- **THEN** each answer event is counted once
