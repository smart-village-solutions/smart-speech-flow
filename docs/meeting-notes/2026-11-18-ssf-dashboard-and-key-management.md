# Decisions: SSF dashboard, task profiles and key management

- Date: 2026-11-18
- Source: decisions explicitly confirmed in the development conversation.
- Status: agreed target concept; not a description of deployed functionality.

## Decisions

### Task profiles and application boundaries

Design for three internal task profiles: conversation staff, reviewers and
organisation managers. Usually these are separate people, but overlapping
responsibilities are common. Keep individual permissions; the profiles guide UX
and do not replace fine-grained authorization or introduce a role switch.

| Profile | Functions | Location |
| --- | --- | --- |
| Conversation staff | Start and resume conversations; find previous conversations with or without recordings; open and work with recordings; assign reviews and read results | SSF dashboard and conversation details |
| Reviewers | Find assigned reviews; accept or decline work; inspect recordings; record findings and submit a signed decision | SSF dashboard and review details |
| Organisation managers | Manage users, permissions, reviewer qualifications, organisation settings, recording policy and retention; set up the organisation key; restore or transfer access to selected recordings | Studio |

Every action remains conditional on its effective permissions. Organisation
administration alone does not provide cryptographic access to recordings.

The follow-up clarification preserves ordinary conversation access for all
admitted staff, including reviewers. Recording and review permissions remain
independent. Review-capable staff therefore have both dashboard views; a missing
recording permission must not hide ordinary conversations or their start action.

The central SSF dashboard element is a table. Reuse its structure for
**Meine Gespräche** and **Meine Prüfungen**, with view-specific columns, filters,
sorting and actions. Conversation status, recording status and review status are
distinct. Show tabs when both views are available; omit a redundant tab bar when
only one is available. Preserve filters and sorting separately for each view.
Place the start-conversation action in the conversation context.

Do not add SSF dashboard tabs for organisational recovery or exceptional access.
Those operations belong in Studio. Use the SSF conversation viewer to read
recordings after access has been transferred.

The SSF user menu contains **Mein Konto**, **Organisation verwalten** when
authorized, and **Abmelden**. Personal key management, including generating a
new key, is available under **Mein Konto → Schlüssel**. The organisation entry
opens Studio.

### Organisation key and recovery

During tenant setup, generate an organisation key pair locally. Store the public
key with the tenant. Export the private key without uploading or storing it on
SSF servers. The organisation is responsible for its custody, backup and
availability; it may use a password manager, an external system or a paper copy
kept in a physical safe. SSF does not operate or control that custody process.

Enable encrypted recordings only after organisation-key setup is complete.
Ordinary conversations are independent of this prerequisite. Automatically
protect each recording's content keys for both the recording employee and the
organisation's public key. Employees do not supply the organisation key.

In Studio, an authorized person can locally supply the private organisation key
to recover the selected content keys and protect them for a target user's public
key. This supports reassignment and recovery after personal key loss without
re-encrypting the recording contents. It does not require displaying those
contents. The organisation private key must not be uploaded to SSF servers.

This replaces the previous target of shared recovery-key ceremonies,
cryptographic approval shares and threshold approval workflows. Their existing
implementation is not evidence that the new model is already available.

Possession of the organisation private key, together with the corresponding
encrypted recordings and protected content keys, enables access independently
of the original employee. SSF cannot replace a lost organisation private key.

### Personal keys and review access

The user clarified that the personal UI term **Zugangsschlüssel** means the
existing passphrase, distinguished from the account login password. Conversation
staff and reviewers enter that passphrase or import its optional backup file.
The existing model remains: private key pairs are generated in the browser,
stored on the server only as encrypted blobs, and unlocked locally. A personal
backup file contains the passphrase, not an exported raw private key. Keep the
tenant-controlled file policy and tab-local, memory-only unlock lifetime.

Both profiles can generate a new personal key pair through the user menu's key
page. On activation, use the new public key for future recordings and future
access assignments, including review assignments. Existing recordings and
existing assignments remain protected for the previous key until access is
explicitly transferred. Keep their key-version associations; generating a new
key must not invalidate existing access with the old key.

Retain the encrypted blobs for older usable personal key versions. Users need
the corresponding previous passphrase for access protected for an older version.
If it has been lost, direct them to their organisation manager, who can use the
organisation key to transfer access to the new personal key. Do not present a
separate employee-facing recovery-approval workflow. Ordinary key supersession
must remain distinct from revocation or a staff member leaving.

Review assignment is a separate operation: an already authorized user can
protect the relevant content keys for a reviewer's public key after recording.
The reviewer need not be named when the recording is created. At review
completion, remove the reviewer's server-side access and protected key copies.
This cannot revoke contents or keys the reviewer has already downloaded.

### Agreed German UI copy

Project documentation is English. The following German product strings retain
the role-specific intent of the earlier agreement, with the personal-secret
term corrected to **Zugangsschlüssel** by the subsequent passphrase clarification.
Select the generation notice from effective conversation-recording and review
capabilities, including the combined case, rather than from an exclusive role.

**Unlocking access — all profiles**

> Falls Sie Ihren Zugangsschlüssel verloren haben, wenden Sie sich an Ihre organisationsverantwortliche Person.

**Generating a key — conversation staff only**

> Der neue Zugangsschlüssel wird für neue Aufzeichnungen verwendet. Für bisherige Aufzeichnungen benötigen Sie weiterhin Ihren bisherigen Zugangsschlüssel. Falls Sie diesen verloren haben, wenden Sie sich an Ihre organisationsverantwortliche Person.

**Generating a key — reviewers only**

> Der neue Zugangsschlüssel wird für künftig zugewiesene Prüfaufträge verwendet. Für bereits zugewiesene Prüfaufträge benötigen Sie weiterhin Ihren bisherigen Zugangsschlüssel. Falls Sie diesen verloren haben, wenden Sie sich an Ihre organisationsverantwortliche Person.

**Generating a key — conversation staff and reviewers**

> Der neue Zugangsschlüssel wird für neue Aufzeichnungen und künftig zugewiesene Prüfaufträge verwendet. Für bisherige Aufzeichnungen und bereits zugewiesene Prüfaufträge benötigen Sie weiterhin Ihren bisherigen Zugangsschlüssel. Falls Sie diesen verloren haben, wenden Sie sich an Ihre organisationsverantwortliche Person.

### Existing test data and cutover

The user confirmed that existing recordings and review assignments are disposable
test data. The implementation does not need a migration from the threshold
recovery model. Plan an explicit operator-controlled test-data reset and clean
cutover before using the new recording/key schema; do not silently reinterpret
old key envelopes. This decision does not execute or authorize immediate data
deletion. Recordings created after cutover must retain access across subsequent
personal and organisation key changes as described above.

## Actions

- Prepare SSF and Studio implementation proposals covering navigation, personal
  passphrase handling, local organisation-private-key handling, personal key
  versions and access transfer. Owner: Not specified. Due: Not specified.
- Define an explicit clean-start procedure for disposable test recording and
  recovery data before replacing the threshold model. Owner: Not specified.
  Due: Not specified.
- Preserve the existing personal-passphrase-backup model; specify the separate
  organisation-private-key export/import format. Owner: Not specified.
  Due: Not specified.

No runtime code, existing OpenSpec requirements, GitHub issues or delivery-plan
statuses are changed by this decision record.

## Risks and remaining design work

- Specify organisation-key versioning and replacement, including access to older
  recordings and handling loss or compromise. Existing recordings continue to
  depend on the key for which their content keys were protected until migrated.
- Define the organisation-private-key export format and optional export
  protection. Personal access continues to use the existing passphrase model
  and tab-local unlock lifetime.
- Define and verify the public-key identity binding used for tenant setup and
  later recipient assignment.
- Key custody belongs to the organisation; correct generation, export, recipient
  selection and local use remain implementation responsibilities.

## Sources

- Development conversation on 2026-11-18, including explicit confirmation of
  the three profiles, application boundaries, organisation-key custody and
  role-specific personal-key notices; subsequent clarifications preserve the
  personal passphrase model and ordinary conversation access for reviewers,
  and identify the existing recordings/reviews as disposable test data.
- [Existing Studio administration design](../superpowers/specs/2026-11-11-studio-ssf-administration-design.md)
  — earlier navigation scope; this decision adds key-management responsibilities
  that need a separate implementation proposal.
- [Earlier recording-key convenience proposal](../../openspec/changes/add-recording-key-convenience/proposal.md)
  — the personal-passphrase backup and tab-local unlock model remains applicable.
- [Current personal-key and recording permissions](../../services/api_gateway/recording/permissions.py).
- [Current recovery implementation](../../services/frontend/src/features/recovery/steps.ts).
- [Current recovery ceremony](../../services/frontend/src/features/ceremony/StartForm.tsx).
