## ADDED Requirements

### Requirement: Per-write live policy authorization

SSF SHALL authorize every write of conversation content with its own live
Studio runtime-configuration read. It SHALL authorize the write only when the
live effective storage mode is `ask` and the session consent status is
`granted`. Every other outcome, including every failure, SHALL refuse.

A refused read SHALL NOT be retried in place. Exactly one read SHALL be
attempted per write.

The authorization outcome SHALL be recorded against the written artefact, so
that a later policy change cannot alter a decision already taken.

#### Scenario: Policy changes between two writes of one session

- **WHEN** the effective storage mode is `ask` for the first write and
  `disabled` for the second write of the same session
- **THEN** the first write is recorded as authorized and its content is retained
- **AND THEN** the second write is recorded as refused and its content is
  removed when the session ends

#### Scenario: Consent not granted

- **WHEN** the session consent status is `pending`, `declined` or
  `policy_disabled`
- **THEN** the write is recorded as refused whatever the live storage mode
  reports

#### Scenario: Studio unavailable

- **WHEN** the runtime-configuration read fails, times out, returns an error
  envelope, or returns a configuration for a different tenant
- **THEN** the write is recorded as refused
- **AND THEN** exactly one read was attempted
- **AND THEN** the conversation continues with transient processing only

#### Scenario: Studio recovers after an outage

- **WHEN** Studio becomes available again after refusals
- **THEN** the refused writes are not re-authorized and their content is removed
  when the session ends

#### Scenario: Unconfigured process

- **WHEN** a process has no runtime policy gate bound, including because Studio
  credentials are absent
- **THEN** the gateway starts normally
- **AND THEN** every write of conversation content is recorded as refused

### Requirement: Live delivery does not depend on persistence authorization

SSF SHALL deliver the live translation, including synthesized audio and
in-session message history, identically regardless of the consent status or the
policy decision. No policy read SHALL be awaited before the participant-visible
result is produced and broadcast.

Conversation content SHALL therefore be written before the participant-visible
result is produced, and its authorization determined afterwards. Refusing a
write SHALL NOT mean declining to write it.

The sending participant's own HTTP acknowledgement completes after that
message's policy reads, so a slow Studio delays the acknowledgement of a message
that has already been delivered. Nothing another participant receives depends on
those reads, and a Studio outage degrades to refusing persistence, never to
failing the conversation.

#### Scenario: Declined session receives the live conversation

- **WHEN** a session's consent status is `declined` or `policy_disabled`
- **THEN** the listener still receives the translated text and playable
  synthesized audio
- **AND THEN** in-session history, audio replay and reconnection work unchanged
  for the duration of the conversation

#### Scenario: Policy read never delays delivery

- **WHEN** an utterance is processed and its runtime policy read is slow
- **THEN** the translated result is broadcast to the receiving participant
  before any policy read completes
- **AND THEN** only the sender's own acknowledgement waits for those reads

#### Scenario: Audio availability is independent of the decision

- **WHEN** a write is recorded as refused
- **THEN** the message still reports its audio as available and its audio URL
  still resolves while the session is live

### Requirement: Refused content does not outlive the conversation

Conversation content whose write was recorded as refused SHALL be removed when
the session terminates, and SHALL NOT be readable afterwards. Content whose
write was recorded as authorized SHALL survive termination.

Removal of refused content SHALL NOT depend on any retention setting.

#### Scenario: Declined session after termination

- **WHEN** a session with consent status `declined` terminates
- **THEN** no audio, message, transcript or translation from that session
  remains readable

#### Scenario: Granted session after termination

- **WHEN** a session with consent status `granted` terminates
- **THEN** its authorized audio and derived content remain, together with the
  tenant identifier and the content-free consent status

#### Scenario: Mixed session after termination

- **WHEN** a session terminates in which some writes were recorded as authorized
  and others as refused
- **THEN** only the authorized content remains

#### Scenario: Session never terminated

- **WHEN** a session is abandoned and never terminated
- **THEN** its refused content is removed once the maximum session lifetime has
  elapsed, whatever the configured retention

### Requirement: Configurable retention for authorized content

SSF SHALL apply one configurable retention period to authorized conversation
content, covering both stored audio and stored message text, defaulting to 24
hours. A deployment SHALL be able to disable automatic deletion so that
authorized content is removed by an operator instead.

Disabling automatic deletion SHALL NOT retain refused content.

#### Scenario: Default retention

- **WHEN** no retention value is configured
- **THEN** authorized audio and authorized message text are deleted 24 hours
  after they were written

#### Scenario: Automatic deletion disabled

- **WHEN** a deployment disables automatic deletion
- **THEN** authorized audio and message text are retained until an operator
  removes them
- **AND THEN** refused content is still removed when its conversation ends

### Requirement: The authorization outcome is not exposed to participants

The recorded authorization outcome SHALL be server-side state. It SHALL NOT
appear in any participant-facing or operator-facing message payload.

#### Scenario: Message history response

- **WHEN** a participant or operator reads session message history
- **THEN** the response carries no field describing whether the message was
  authorized for persistence

### Requirement: No conversation content in logs, errors or audit

SSF SHALL NOT record conversation content in logs, error details, audit records
or metric labels, including when a write is refused. A refusal SHALL record only
the fact, the reason and a count.

#### Scenario: Refusal is logged

- **WHEN** a write of conversation content is refused
- **THEN** the log record names the decision and the reason
- **AND THEN** it contains no transcript, translation, audio or guest identifier

#### Scenario: Policy metrics

- **WHEN** a policy decision is recorded as a metric
- **THEN** its labels carry only the decision and the reason
- **AND THEN** no tenant identifier, session identifier or content appears

#### Scenario: Discarded-content counter reflects content only

- **WHEN** consent is resolved at session activation
- **THEN** no discarded-content metric is incremented, because no write occurred

### Requirement: Persistence authorization is structurally isolated from frozen configuration

Code that authorizes persistence SHALL NOT read the per-session frozen runtime
configuration, its presentation projection, or the session's stored
configuration attribute. A check that runs in continuous integration SHALL
enforce this and fail the build.

#### Scenario: Frozen configuration reintroduced

- **WHEN** persistence-authorizing code references the session's frozen runtime
  configuration or its presentation projection
- **THEN** the check fails in continuous integration

#### Scenario: Cross-tenant authorization

- **WHEN** a policy read is performed for one tenant
- **THEN** its decision never authorizes a write belonging to another tenant
