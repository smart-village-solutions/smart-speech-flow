# conversation-persistence Specification

## Purpose
Defines when SSF stores conversation content (message text and audio) and for how long: storage is authorised by a live read of the Studio policy for each message, and kept content follows the retention Studio reported when the guest consented.

## Requirements

### Requirement: Per-message live policy authorization

SSF SHALL authorize the persistence of each message with one live Studio
runtime-configuration read. The read's decision SHALL apply to every artefact
of that message: the message record, its original audio and its translated
audio. A write SHALL be authorized only when the live mode is `ask` and the
session consent status is `granted`; every other outcome, including every
failure, SHALL refuse. A refused read SHALL NOT be retried in place. Each
artefact SHALL record the decision taken for it.

The storage mode SHALL NOT be served from a cache.

#### Scenario: Voice message with translated audio

- **WHEN** a voice message produces a record, original audio and translated
  audio while the mode is `ask` and consent is `granted`
- **THEN** exactly one runtime-configuration read is made for the message
- **AND THEN** all three artefacts are recorded as authorized

#### Scenario: Policy changes between two messages

- **WHEN** the mode is `ask` for one message and `disabled` for the next
- **THEN** the first message's artefacts are recorded as authorized
- **AND THEN** the second message's artefacts are recorded as refused and
  removed when the session ends

#### Scenario: Studio unavailable

- **WHEN** the read fails, times out, returns an error envelope or returns
  another tenant's configuration
- **THEN** every artefact of that message is recorded as refused
- **AND THEN** the conversation continues with transient processing only

### Requirement: Tenant retention captured with consent

When activation resolves consent to `granted`, SSF SHALL store the
`retentionHours` and `configurationRevision` of that same live read on the
session. The stored retention SHALL govern that session's authorized message
text, audio and terminal record, and SHALL NOT change for the rest of the
session's life. A value of `0` SHALL disable automatic deletion for that
session. Refused content SHALL still be removed when its conversation ends.

A session without granted consent SHALL keep no conversation content after
settlement; its terminal record SHALL expire after the configured terminal
record period, 24 hours by default.

#### Scenario: Consent granted at 180 days

- **WHEN** consent is granted while Studio reports `retentionHours` 4320
- **THEN** authorized audio is deleted 4320 hours after it was written
- **AND THEN** the terminal record expires 4320 hours after the conversation
  ended

#### Scenario: Retention changes during a session

- **WHEN** Studio's `retentionHours` changes after consent was granted
- **THEN** the session keeps the value captured at consent

#### Scenario: Automatic deletion disabled by Studio

- **WHEN** consent is granted while Studio reports `retentionHours` 0
- **THEN** authorized content is kept until an operator removes it

#### Scenario: Missing audio retention marker

- **WHEN** the audio cleanup finds a session directory without a valid
  retention marker
- **THEN** it applies the short default period

### Requirement: Tenant session index stays bounded

SSF SHALL remove expired sessions from the tenant session index so that staff
session lists do not read records that no longer exist.

#### Scenario: Expired terminal record

- **WHEN** a terminal record has expired
- **THEN** its session is no longer listed in the tenant session index
