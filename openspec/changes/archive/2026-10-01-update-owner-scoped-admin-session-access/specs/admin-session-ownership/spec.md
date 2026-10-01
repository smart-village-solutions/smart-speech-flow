## MODIFIED Requirements

### Requirement: The current session is the requesting admin's

`GET /api/admin/session/current` without a `session_id` SHALL return the
requesting admin's live session. With a `session_id` it SHALL return that
session only while it is not terminated and only to the admin who created it;
for any other admin it SHALL answer as for an unknown session.

#### Scenario: Each admin sees their own

- **WHEN** two admins of a tenant each have a live session and each requests the
  current session
- **THEN** each receives their own session

#### Scenario: No session of one's own

- **WHEN** an admin without a live session requests the current session
- **THEN** SSF answers that no session is active, even if colleagues have one

#### Scenario: A colleague's session by id

- **WHEN** an admin requests the current session naming a colleague's live session
- **THEN** SSF answers `404 Session not found`

## ADDED Requirements

### Requirement: Admin session access is limited to the owner

Every admin route that names a session SHALL serve only the admin who created
it, identified by the session's owner reference. For any other admin of the
tenant, and for every admin when the session has no owner, SSF SHALL answer
exactly as for an unknown session (`404 Session not found`), whether the session
is live or terminated. This SHALL include the session's status, messages and
audio, sending a message, issuing a realtime ticket, listing its realtime
connections, terminating it and the admin polling routes. No role SHALL be
exempt.

#### Scenario: A colleague's live session

- **WHEN** an admin reads, writes into, requests a realtime ticket for or
  terminates a live session another admin of the tenant created
- **THEN** SSF answers `404 Session not found`
- **AND THEN** the session is unchanged and stays live

#### Scenario: A colleague's ended session

- **WHEN** an admin requests the status or messages of a terminated session
  another admin of the tenant created
- **THEN** SSF answers `404 Session not found`

#### Scenario: A session without an owner

- **WHEN** any admin names a session that was stored without an owner
- **THEN** SSF answers `404 Session not found`

#### Scenario: The owner

- **WHEN** the admin who created a session uses these routes
- **THEN** SSF serves them as before

### Requirement: Session listings are the requesting admin's

`GET /api/admin/session/history` SHALL list only the requesting admin's
terminated sessions and only the requesting admin's pending or active sessions,
applying `limit` after that filter. `GET /api/admin/realtime/connections` SHALL
list only connections of the requesting admin's sessions. Sessions without an
owner SHALL appear in no admin's listing.

#### Scenario: Two admins list their sessions

- **WHEN** two admins of a tenant each have a live and an ended session and each
  requests the session history
- **THEN** each receives only their own sessions

#### Scenario: A colleague is connected

- **WHEN** an admin lists the tenant's realtime connections while a colleague's
  session has connections
- **THEN** the colleague's connections are not listed
