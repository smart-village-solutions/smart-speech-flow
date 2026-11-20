## ADDED Requirements

### Requirement: Additive task views preserve conversation admission

SSF SHALL offer **Meine Gespräche** and ordinary conversation creation to every
user admitted by the existing realm-derived conversation-access rules. Users
with effective `ssf.recording.review` permission SHALL additionally receive
**Meine Prüfungen** and a tab bar. A single available view SHALL omit redundant
tabs. Recording-request permission SHALL NOT be used as ordinary conversation
admission. View selection SHALL NOT grant authorization.

#### Scenario: Admitted user without recording permissions

- **WHEN** an admitted user has no recording permissions
- **THEN** the conversation dashboard and ordinary start action remain available
- **AND** no redundant task tab bar or review actions appear

#### Scenario: Reviewer retains conversation capability

- **WHEN** an admitted user has review permission
- **THEN** the dashboard offers both conversation and review views
- **AND** switching views does not alter permissions or create an exclusive role

#### Scenario: Review permission is removed

- **WHEN** the authenticated tab observes loss of review permission
- **THEN** SSF stops review queries and removes review task state and actions
- **AND** ordinary conversation access continues under its existing rules

### Requirement: Safe combined conversation overview

The gateway SHALL provide an authenticated conversation overview containing only
owned retained sessions and recordings currently listable by the caller's
archive access, including transferred recordings. It SHALL relate and
deduplicate sources internally and SHALL NOT expose owner references, session
pseudonyms or raw private keys. Linked rows SHALL retain distinct conversation,
recording and verification states. Missing or failed sources SHALL NOT be
represented as successful proof that no recording exists. Action endpoints
SHALL re-check current authorization independently of navigation hints.

#### Scenario: Session has an accessible recording

- **WHEN** an owned session and an accessible archive record describe the same conversation
- **THEN** the overview returns one row with a permitted recording reference
- **AND** the browser does not join sources by pseudonym, owner reference or timestamps

#### Scenario: Session metadata expires before the recording

- **WHEN** a recording remains listable after its transient session metadata expires
- **THEN** the recording remains available as an archive-only overview row
- **AND** no session content or retention period is extended for the dashboard

#### Scenario: Source cannot be queried

- **WHEN** a source necessary to determine recording availability fails
- **THEN** the overview reports unavailability
- **AND** SSF does not label affected conversations as unrecorded

#### Scenario: Another user's ordinary session

- **WHEN** a caller requests overview or details for a colleague's session without archive access
- **THEN** no colleague session metadata is disclosed
- **AND** an explicit unauthorized session lookup behaves like an unknown session

### Requirement: Encrypted language metadata remains protected

Overview and review tables SHALL NOT expose encrypted archive language metadata
through joins with session metadata. Such rows SHALL have explicit unknown or
encrypted language state. SSF SHALL NOT bulk-open recordings to populate a
table or language filter. Clear language already permitted for an unrecorded
retained session MAY be displayed. Content decrypted after opening an individual
recording SHALL remain confined to its existing authorized detail lifetime.

#### Scenario: Locked recorded conversation

- **WHEN** the overview contains a recording whose language is encrypted
- **THEN** its language is labelled unknown or locked even if a linked session carries language metadata
- **AND** rendering and filtering do not request or decrypt its content

#### Scenario: Language-specific filtering

- **WHEN** a language filter is selected and loaded rows include encrypted or unknown languages
- **THEN** SSF explains those rows cannot be classified by that language
- **AND** users can explicitly select the unknown/locked group

### Requirement: Honest local filters and pagination

SSF SHALL preserve independent language, status and sort choices for each task
view across same-tab task, detail and account navigation. The conversation
overview SHALL support bounded pages and opaque tenant/user-bound cursors.
Local filtering and sorting SHALL identify their scope as loaded entries, show
matching and loaded counts and preserve load-more when further pages exist.
SSF SHALL NOT present a no-match loaded subset as an exhaustive empty result.
Refresh SHALL reset source pagination coherently without discarding filter
choices. Logout, account and tenant changes SHALL clear table state.

#### Scenario: Return from a review

- **WHEN** a user returns from review details to a filtered review table
- **THEN** its previous filters and sorting remain selected
- **AND** the independent conversation table settings remain unchanged

#### Scenario: First page has no local matches

- **WHEN** the loaded conversation page has no matches and another cursor exists
- **THEN** SSF reports no matches among the loaded entries and keeps load-more available
- **AND** it does not claim no matching conversations exist anywhere

#### Scenario: Cursor belongs to another identity

- **WHEN** a cursor is submitted under another tenant or authenticated user
- **THEN** the gateway rejects it without exposing the original result set

### Requirement: Contextual actions reuse existing detail workflows

SSF SHALL provide explicit actions to resume eligible sessions, open accessible
recordings and inspect metadata for unrecorded retained conversations. It SHALL
reuse existing archive integrity checks, review assignment, draft, signature and
access-release behavior. Metadata-only details SHALL display no conversation
content and offer no reconstruction or recording-review action. Recording/review
unlocking SHALL preserve the originating view, filters and requested target,
re-checking access before opening it.

#### Scenario: Unrecorded ended conversation

- **WHEN** the user opens details of an owned retained conversation without a recording
- **THEN** SSF shows only available metadata and explains that no recording exists
- **AND** it does not fetch or offer conversation contents

#### Scenario: Unlock before opening an assignment

- **WHEN** a user selects a review that requires personal-access unlocking
- **THEN** successful unlocking returns to that assignment after access is rechecked
- **AND** cancelling returns to the original table with its prior settings

#### Scenario: Data expires during navigation

- **WHEN** an overview target expires or authorization is withdrawn before it is opened
- **THEN** SSF reports that the target is unavailable and permits return to the table
- **AND** stale navigation hints do not bypass access checks

### Requirement: Completed review result summaries do not reopen recordings

SSF SHALL offer an own-completed-decision summary to an authenticated user with
current review permission while that decision's metadata is retained. The
summary SHALL contain only assignment identity, outcome/status, request and
decision times and an optional requester display name. It SHALL NOT return
recording content, findings, overall notes, content keys, wraps, object URLs or
download tickets, and SHALL NOT restore recording access or editing. Other
users' or missing results SHALL be indistinguishable from not found.

#### Scenario: Reviewer inspects a completed decision

- **WHEN** the assigned reviewer opens their completed result from the dashboard
- **THEN** SSF displays the retained outcome summary without opening the recording
- **AND** no decrypted findings, keys or recording access are granted

#### Scenario: Result lookup for another reviewer

- **WHEN** a reviewer requests another user's completed-result identifier
- **THEN** the gateway answers as for a missing result

### Requirement: Personal account uses the existing passphrase model

SSF SHALL group personal access management under **Mein Konto**, retain a link
to existing Keycloak account settings and expose Studio administration only
under its existing tenant and permission rules. **Zugangsschlüssel** SHALL mean
the personal passphrase, not a raw private key or login password. Existing
server-side encrypted personal-key blobs, local passphrase processing,
policy-controlled TXT flows and tab-local unlock protections SHALL remain.
Key-version and organisation-recovery behavior SHALL follow the coordinated
key-lifecycle capability rather than introducing a second model.

#### Scenario: Personal access file import

- **WHEN** the user imports an allowed personal access backup file
- **THEN** SSF processes its passphrase locally using existing cryptographic checks
- **AND** no raw personal private-key input workflow is introduced

#### Scenario: Organisation administration is not authorized

- **WHEN** a user lacks the existing Studio tenant-management authorization
- **THEN** the account menu does not expose organisation administration
- **AND** personal access management and logout remain available

### Requirement: Legacy navigation retirement is coordinated

The final SSF menu SHALL contain account, authorized Studio administration and
logout, with conversation and review tasks accessible from the dashboard.
Organisation recovery, exceptional access and threshold-approval navigation
SHALL move out of SSF only with the separately approved replacement flow ready.
Personal key-loss guidance SHALL direct users to organisation administration in
that final state. This change SHALL NOT authorize deletion of existing test or
production data.

#### Scenario: Coordinated organisation-key release

- **WHEN** the new Studio/Gateway access-transfer flow is deployed with the approved lifecycle change
- **THEN** SSF removes legacy ceremony/recovery/approval entries and offers organisation-contact guidance
- **AND** the final menu retains only account, authorized administration and logout

#### Scenario: Replacement flow is not deployed

- **WHEN** dashboard work is released before its companion organisation-key flow
- **THEN** existing recovery routes remain reachable until the coordinated cutover
- **AND** the dashboard release does not silently remove the only working recovery path
