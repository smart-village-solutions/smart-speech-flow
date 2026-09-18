## ADDED Requirements

### Requirement: Consent resolution at session activation

SSF SHALL resolve the guest's conversation-content consent when a pending
session is first activated, using a live Studio runtime-configuration read taken
at that moment, and SHALL store the outcome as a content-free status on the
session.

The activation request MAY carry the guest's answer. An absent answer is not an
answer and MUST NOT resolve to consent.

This read SHALL NOT be performed through the persistence policy gate, because no
conversation-content write occurs at activation.

#### Scenario: Storage disabled for the tenant

- **WHEN** the effective storage mode is `disabled`
- **THEN** SSF records the consent status `policy_disabled`
- **AND THEN** it asks the guest nothing
- **AND THEN** the session activates and permits transient live translation

#### Scenario: Guest agrees

- **WHEN** the effective storage mode is `ask` and the activation request
  carries an affirmative answer
- **THEN** SSF records the consent status `granted`

#### Scenario: Guest does not agree

- **WHEN** the effective storage mode is `ask` and the activation request
  carries a negative answer
- **THEN** SSF records the consent status `declined`
- **AND THEN** the session activates and permits transient live translation

#### Scenario: No answer supplied

- **WHEN** the effective storage mode is `ask` and the activation request
  carries no answer
- **THEN** SSF records the consent status `declined`

#### Scenario: Policy read fails at activation

- **WHEN** the live runtime-configuration read fails for any reason other than a
  tenant-availability conflict
- **THEN** SSF leaves the consent status `pending`
- **AND THEN** the session activates and permits transient live translation
- **AND THEN** no conversation content is persisted for that session

### Requirement: Consent is resolved once per session

SSF SHALL resolve consent only on the activation that moves a session out of the
pending state. A repeated activation of an already-active session, including one
that changes the customer language, SHALL NOT re-resolve consent and SHALL NOT
alter the stored status.

#### Scenario: Language changed during an active conversation

- **WHEN** an already-active session is activated again with a different
  customer language
- **THEN** the customer language is updated
- **AND THEN** the stored consent status is unchanged

#### Scenario: Repeat activation carrying no answer

- **WHEN** an already-active session with consent status `granted` is activated
  again with no consent answer
- **THEN** the stored consent status remains `granted`

### Requirement: Consent status carries no conversation content

The stored consent status SHALL be one of `pending`, `granted`, `declined` and
`policy_disabled`, and SHALL carry no conversation content, no free text and no
guest identifier.

A status restored from a record written before consent existed SHALL resolve to
`pending`, which permits no persistence.

#### Scenario: Status is a bare value

- **WHEN** a session record is serialized
- **THEN** its consent status is one of the four defined values
- **AND THEN** the record contains no consent-related free text

#### Scenario: Record predating consent

- **WHEN** a session record written before this change is restored
- **THEN** its consent status is `pending`
- **AND THEN** no conversation content may be persisted for that session

### Requirement: Tenant unavailability refuses a new session

When the live runtime-configuration read performed to activate a pending session
returns a tenant availability conflict, SSF SHALL NOT activate the session and
SHALL create no session state for it.

This SHALL NOT apply to a repeated activation of an already-active session,
which performs no such read.

#### Scenario: Tenant suspended, plugin inactive, or tenant not ready

- **WHEN** activating a pending session and the runtime-configuration read
  returns `409` with any of `tenant_suspended`, `ssf_plugin_inactive` or
  `ssf_tenant_not_ready`
- **THEN** SSF refuses the activation
- **AND THEN** no session is activated and no consent status is recorded

#### Scenario: Conflict during an active conversation

- **WHEN** a `409` occurs at a policy read while a conversation is already
  active
- **THEN** the conversation continues with transient processing only
- **AND THEN** no conversation content is retained from that point

#### Scenario: Language change during tenant unavailability

- **WHEN** an already-active session changes its customer language while the
  tenant is unavailable
- **THEN** the language change succeeds, because no activation read is performed
