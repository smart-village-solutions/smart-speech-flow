## ADDED Requirements

### Requirement: Persist feedback text separately from analytics

The system SHALL persist optional feedback free text only in an encrypted,
access-controlled transactional feedback repository. It SHALL NOT place free
text in ClickHouse, OpenTelemetry records, application logs, or telemetry
attributes.

#### Scenario: User submits feedback with improvement ideas

- **WHEN** an eligible user submits valid ratings, NPS, and optional free text
- **THEN** the transactional feedback repository stores the text with an opaque
  feedback identifier
- **AND THEN** the associated analytics event contains only structured fields
  and opaque references.

### Requirement: Disclose feedback processing at submission

The system SHALL state beside the feedback submit action that submitting the
voluntary form constitutes agreement to feedback processing and twelve-month
storage, and SHALL provide a route for withdrawal.

#### Scenario: User reviews the feedback form before submitting

- **WHEN** the feedback form presents its submit action
- **THEN** the processing purpose and twelve-month storage period are visible
- **AND THEN** the user can find the withdrawal route before submitting.

### Requirement: Correlate feedback to quality telemetry pseudonymously

The system SHALL derive feedback correlation references and `session_ref` in
the Gateway and SHALL NOT trust client-provided analytical identifiers.

#### Scenario: Feedback is submitted for an existing session

- **WHEN** the Gateway accepts a feedback submission
- **THEN** it derives the pseudonymous session reference from the validated
  session identifier
- **AND THEN** it emits a `feedback_submitted` event that can be correlated
  with that session's quality telemetry without containing the raw session ID.

### Requirement: Store structured feedback in ClickHouse analytics

The system SHALL emit an allowlisted, versioned `feedback_submitted` event
containing ratings, NPS, form version, and opaque references through the
existing telemetry pipeline.

#### Scenario: Analytics transport is unavailable

- **WHEN** the transactional feedback write succeeds but telemetry emission is
  unavailable
- **THEN** the endpoint reports successful feedback acceptance
- **AND THEN** the system records the structured analytics event for idempotent
  reconciliation
- **AND THEN** no free text is included in the reconciliation record.

### Requirement: Retain feedback text for twelve months

The system SHALL assign an expiry timestamp twelve months after feedback
creation and SHALL delete the transactional feedback record at expiry while
recording a content-free deletion audit.

#### Scenario: Feedback reaches its expiry time

- **WHEN** a feedback record reaches its assigned expiry timestamp
- **THEN** the retention job deletes its encrypted text and feedback record
- **AND THEN** it records completion without retaining the deleted text.
