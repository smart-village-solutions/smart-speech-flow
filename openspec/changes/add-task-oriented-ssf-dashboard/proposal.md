# Change: Add a task-oriented SSF dashboard and personal account navigation

## Why

Conversation history, encrypted recordings and review assignments already exist,
but staff must find them through separate menu entries. The Figma concept groups
these tasks around a table and keeps organisation administration in Studio.

## What Changes

- Add a shared dashboard table with separate conversation and review views,
  independent local filters and sorting, explicit row actions and useful empty
  states. All admitted users retain ordinary conversation access; users with
  `ssf.recording.review` additionally receive the review view.
- Add a gateway-composed conversation overview that safely relates retained
  session metadata and accessible recordings, without exposing owner references
  or session pseudonyms. Preserve encrypted language metadata.
- Add metadata-only details for unrecorded conversations and a result-only
  summary for a reviewer's completed decisions without restoring recording access.
- Integrate existing conversation, archive and review components, including
  return navigation through personal-access unlocking.
- Group personal access management under **Mein Konto**, retaining the current
  passphrase workflow and optional passphrase TXT policy. Link organisation
  administration to Studio. Coordinate removal of legacy recovery navigation
  with the separately approved key-lifecycle change.
- Preserve existing conversation-minute reporting, ownership, content retention
  and cryptographic checks. Figma guides user tasks rather than pixel geometry.

## Impact

- New capability: `task-oriented-ssf-dashboard`.
- Existing capabilities remain authoritative: `admin-session-ownership`,
  `conversation-persistence`, `recording-key-convenience`,
  `conversation-usage-reporting` and `conversation-access`.
- SSF frontend: dashboard, router, shared staff header/menu, account and existing
  archive/review entry points; domain repositories, types and fixtures.
- SSF gateway: overview aggregation and a restricted review-result endpoint.
- Companion change: `update-recording-key-lifecycle` owns personal key versions,
  organisation recipients, access-transfer authorization and replacement of
  threshold recovery. This proposal consumes those contracts rather than
  redefining them.
- Existing recordings and assignments are disposable test data. Historical data
  migration is not a delivery requirement; this statement does not authorize any
  deletion or reset operation.
- Status: approved by the user on 2026-11-18; implementation is tracked in this change.

## Sources

- [Figma concept](https://www.figma.com/design/AijYIt1PwwrUOqDWhd8IpL/SSF-Dashboard-and-Key-Management-Concept).
- [Decision record](../../../docs/meeting-notes/2026-11-18-ssf-dashboard-and-key-management.md).
- Subsequent user clarification: personal **Zugangsschlüssel** means the
  passphrase, distinct from the login password; encrypted personal private-key
  blobs remain server-side.
- Subsequent user decisions: reviewers retain ordinary conversation capability;
  existing recordings and assignments do not require historical migration.

## Approval

Approved by the user in the development conversation on 2026-11-18. Implementation is authorized; deployment and test-data reset remain separate operator actions.

## Subsequent authentication policy

The additionally approved `remove-sensitive-action-reauthentication` change supersedes all action-specific fresh-MFA requirements in this proposal and its design/tasks. A valid authenticated user session is sufficient regardless of optional MFA claims or original login age. Identity, tenant, permissions, session expiry, local key passphrases, replacement email confirmation and actual cryptographic preparation expiry remain enforced. Historical acceptance evidence is not rewritten.
