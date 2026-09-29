## ADDED Requirements

### Requirement: One live conversation per admin

SSF SHALL record, for every admin session it creates, the admin who created it,
identified by a one-way reference derived from the issuer-derived tenant and the
verified token subject. Unless parallel sessions are explicitly enabled, creating
a session SHALL end only the pending or active sessions of the same admin in the
same tenant, with the termination reason `new_session_created`. Sessions of other
admins in the tenant SHALL remain untouched. A session stored without an owner
belongs to no admin and SHALL NOT be ended by any new session.

#### Scenario: Two admins of one tenant

- **WHEN** two admins of the same tenant each create a session
- **THEN** both sessions remain live

#### Scenario: One admin starts again

- **WHEN** an admin who has a live session creates another one
- **THEN** the earlier session ends with the reason `new_session_created`
- **AND THEN** the sessions of other admins in the tenant are unaffected

#### Scenario: After a gateway restart

- **WHEN** the gateway restarts and an admin then creates a session
- **THEN** the admin's session from before the restart ends

#### Scenario: Session stored before owners existed

- **WHEN** an admin creates a session while an owner-less session is live
- **THEN** the owner-less session remains live

### Requirement: The current session is the requesting admin's

`GET /api/admin/session/current` without a `session_id` SHALL return the
requesting admin's live session. With a `session_id` it SHALL return that
session of the tenant while it is not terminated, whichever admin created it.

#### Scenario: Each admin sees their own

- **WHEN** two admins of a tenant each have a live session and each requests the
  current session
- **THEN** each receives their own session

#### Scenario: No session of one's own

- **WHEN** an admin without a live session requests the current session
- **THEN** SSF answers that no session is active, even if colleagues have one

### Requirement: The owner stays internal

The owner reference SHALL be persisted with the session and SHALL NOT appear in
any API response, log line or telemetry.

#### Scenario: Session listings

- **WHEN** the session history or the active sessions are requested
- **THEN** no entry carries the owner reference
