# Task-oriented SSF dashboard design

## Decisions and boundaries

The default view is **Meine Gespräche** for every admitted realm user. A user
with `ssf.recording.review` additionally sees **Meine Prüfungen** and a tab bar.
There is no exclusive role switch and no new permission for ordinary
conversations. `ssf.recording.request` controls recording requests only. A change
to effective review permission removes inaccessible task state and stops its
queries without ending the user's ordinary conversation capability.

Keep `AdminSessionScreen`, `ConversationViewer`, `ReviewScreen` and existing
review editing, signatures and access checks. Extract table and navigation
composition around them; do not recreate the underlying live or review flow.
Conversation state, recording availability/access and review summary remain
separate fields, even when the layout displays compact labels.

The account entry becomes an internal SSF account view. It contains personal
access management and the existing external Keycloak account-settings link.
Studio remains an external administration entry subject to the current tenant
and permission checks. Login credentials continue to belong to Keycloak.

## Overview contract

Add `GET /api/admin/dashboard/conversations?cursor=<opaque>&limit=50`.
The gateway derives tenant and owner from authentication. It returns
`{ items, next_cursor }`, with newest-first ordering by `started_at`, then a
stable opaque row identifier. Limit is bounded to 1–100; cursors are opaque,
tenant/user-bound and do not contain externally readable owner references or
session pseudonyms. Invalid or mismatched cursors are rejected.

Each item contains:

| Field | Meaning |
| --- | --- |
| `id` | Opaque stable dashboard row identifier |
| `session_id` | Owned retained session ID, otherwise null |
| `recording_id` | Accessible recording ID, otherwise null |
| `origin` | `own` or `transferred` |
| `started_at`, `ended_at` | Retained session times when available; recording times for archive-only rows; end nullable for ongoing rows |
| `conversation_status` | `pending`, `active` or `ended` |
| `recording_status` | `none`, `available`, `incomplete` or `unavailable` |
| `recording_access` | `none`, `unlock_required`, `available` or `transfer_required`; an availability hint, not authorization |
| `customer_language` | Allowed existing clear session metadata, or null when unknown/encrypted |
| `language_visibility` | `clear`, `encrypted` or `unknown` |
| `verification` | Existing aggregate review summary, or null |
| `actions` | Authorized navigation hints from `resume`, `open_recording`, `open_details` |

`recording_access` is resolved against enrolled key-version access and updated
with tab-local unlock state by the frontend; the gateway cannot assert whether
the browser currently holds an unlocked key. In the wire response `available`
means an enrolled version has a usable grant, and the frontend still requires
local unlock before opening contents.

Aggregate only owned retained sessions and recordings which current archive
authorization permits the caller to list, including transferred access after
the companion lifecycle change. Use the existing internal session reference to
join sources inside the gateway. Never emit it, substitute a client-provided
owner or join rows in the browser by timestamps. Deduplicate linked rows.
Archive-only rows remain visible after transient session metadata expires.

Recorded-row language remains encrypted even if an internal join finds clear
session metadata. The overview must not turn that join into a language leak.
Ordinary unrecorded rows may retain the language already permitted by the
session history contract. No retention period is extended and no content is
retained to support the dashboard.

The aggregator supports incomplete availability explicitly: a required source
failure returns an unavailable response, rather than asserting that recordings
are absent. An expired/deleted recording is not represented as an available
recording. Existing access routes re-check authorization on every action.

## Filtering and pagination

Both views keep independent language/status/sort state in the authenticated tab
only. Preserve that state across tab changes, details, account and unlock
navigation. Clear it on logout, tenant or account change. No persistence across
reload is required, and no passphrase or decrypted metadata is stored for it.

Conversation pages use server newest-first ordering; the local controls operate
only on accumulated loaded rows. The interface states **Filter und Sortierung
gelten für geladene Einträge**, reports matches among loaded rows and retains a
**Weitere laden** action whenever `next_cursor` exists, including when the
current filter has no matches. It must not claim globally empty search results
until there is no next page. Changing a local filter does not change cursor
meaning. Reload/refresh resets source pagination coherently while preserving
chosen filters. Review rows currently arrive as a complete inbox; if pagination
is added later, the same completeness rule applies.

Encrypted and unknown language have an explicit **Unbekannt / gesperrt** filter
value. A language-specific filter cannot pretend an unknown row matches or
does not contain that language; explain that those rows are excluded because
their language is not available. Do not open all recordings to populate a
language filter. Opening one recording may display its decrypted language in
its detail view, without expanding dashboard metadata or persisting it.

## Details, unlock and completed review results

Unrecorded details show only available time, language, duration and conversation
status, with an explicit notice that no recording exists. They offer no content,
reconstruction, review or archive-fetch action. They use retained overview data
or an owner-checked metadata lookup and handle expiry while navigating.

Opening a locked recording/review records a return target containing only the
view and opaque recording/assignment identifier. After account unlock, return
to that target, re-check current access and keep filters. Cancelling returns to
the originating table. Ordinary login after actual session expiry preserves
this intent without putting passphrases or plaintext into URLs/storage.
Authenticated actions do not trigger a second password/MFA challenge.

Add `GET /api/admin/recording/verifications/{verification_id}/result` for an
authenticated reviewer with current review permission reading their own
completed decision. Return assignment ID, decision status/outcome, requested
and decided times and optional requester display name. Do not return recording
contents, encrypted or plaintext findings/overall notes, content keys, wraps,
download tickets or object URLs. Results remain readable only while the
verification metadata is retained. Treat another user's/missing result as
not found; revoked permission remains forbidden. This is the limited
**Ergebnis ansehen** action, not reopening the review editor or restoring access.
Existing employee-side detailed verification results remain in the authorized
recording viewer.

## Personal access and legacy navigation

Retain local passphrase entry, optional TXT import/export governed by Studio
policy, non-extractable tab-local keys, explicit lock and E-Mail-confirmed key
replacement. **Zugangsschlüssel** is product vocabulary for the passphrase; do
not introduce personal raw private-key input. Detailed historical-key unlock
and replacement rules belong to `update-recording-key-lifecycle`.

Display role-appropriate recording/review replacement notices from effective
capabilities, with combined wording when both apply. Replace employee-facing
threshold recovery with an instruction to contact organisation administration
only when the companion Studio/Gateway flow is ready. Do not remove the old
access route before its replacement is deployed; the coordinated final state
contains no SSF ceremony, exceptional-access or approval menu entries.

## Implementation ownership

The SSF frontend worker owns `services/frontend/src/features/dashboard/*`
(new), account composition, existing admin/archive/review entry adapters,
`app/router/AppRoutes.tsx`, staff headers/menu, domain DTOs and localized copy.
The gateway worker owns the overview service/route and result-only service/route,
their repositories and authorization tests. The key-lifecycle worker owns key
version APIs and changes in `core/crypto/key-vault.ts`; the dashboard worker
consumes that interface. Studio work remains in its repository. The coordinator
reviews shared interfaces before workers edit shared files.

## Validation

Use existing frontend test patterns and gateway fixtures. Cover admitted users
without recording permissions, reviewers with both tabs, permission changes,
independent table state, coherent refresh/pagination, duplicate source rows,
cross-owner/tenant isolation, unknown encrypted language, retained archive-only
rows, unavailable sources, metadata expiry and unlock return. Verify result-only
reads cannot obtain content/key material or reopen completed reviews. Preserve
existing archive integrity, review signature/access-release and conversation
minute reporting checks. Run focused tests, frontend build and lint for changed
files; run the relevant gateway subset for new routes and authorization.

## Rollout

Land contracts before frontend consumers. Keep legacy navigation reachable until
the separately approved organisation-key replacement path is operational; switch
to the final menu with the coordinated release. Test data can be recreated for
acceptance testing, but this proposal authorizes no destructive environment
operation. No production historical migration is required by the user.
