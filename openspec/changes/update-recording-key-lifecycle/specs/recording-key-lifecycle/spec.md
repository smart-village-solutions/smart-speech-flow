## ADDED Requirements

### Requirement: Versioned personal access survives ordinary replacement
The system SHALL retain passphrase-encrypted personal private-key blobs and
version-bound recording grants for superseded keys. Ordinary confirmed key
replacement SHALL select a new active version for future recordings and
assignments without removing previous grants or withdrawing open reviews.
Revocation and leaving SHALL remain separate blocking operations. Historical
signing public keys SHALL remain available to verify existing decisions.

#### Scenario: Existing recording after replacement
- **WHEN** a user confirms personal version 2 after receiving a recording under version 1
- **THEN** version 1 remains retrievable as an encrypted blob and opens that recording after local passphrase unlock
- **AND** new recording windows and new assignments use version 2

#### Scenario: Existing reviewer completes after replacement
- **WHEN** a reviewer activates version 2 while a version-1 assignment is open
- **THEN** the assignment remains available and its signed decision is verified against the still-usable assigned version 1

#### Scenario: Explicit revocation
- **WHEN** a formerly usable personal version is explicitly revoked or its user leaves
- **THEN** the version cannot authorize new archive reads or decisions
- **AND** ordinary supersession is not treated as that revocation

### Requirement: Personal passphrases and tab-local version unlock
SSF SHALL describe the personal passphrase as a user-facing access key distinct
from the login password. Personal passphrases SHALL never be sent to servers;
optional TXT import/export SHALL preserve the existing effective tenant policy.
The vault SHALL hold non-extractable unlocked keys by tenant, user, version and
fingerprint only in the current tab's memory. Supersession SHALL preserve usable
older unlocks; explicit lock, logout, detected session expiry, account/tenant
change and reload SHALL invalidate them, including delayed operations.

#### Scenario: Required historical version
- **WHEN** a recording needs version 1 but only version 2 is unlocked
- **THEN** SSF requests local unlocking of version 1 without presenting a raw-private-key import
- **AND** unlocking one version does not automatically unlock another

#### Scenario: Logout during unlock
- **WHEN** the user logs out while a historical unlock is pending
- **THEN** the completion cannot repopulate the cleared vault

### Requirement: Authoritative organisation public-key lifecycle
Gateway SHALL be the single authoritative store of organisation public-key
versions. Studio SHALL generate the P-256 organisation private key locally and
provide an explicitly labelled unencrypted export/import in the versioned format
specified in the design. Private organisation keys SHALL never be uploaded.
Preparation SHALL not activate a key; activation SHALL require a saved-key
confirmation, fresh MFA, manager permission, cryptographic possession proof and
an expected-active-key comparison. Replacement SHALL affect new recording
windows while retaining older public metadata and associations.

#### Scenario: Cancel before activation
- **WHEN** a manager prepares a replacement and then cancels or lets it expire
- **THEN** the currently active organisation key remains active

#### Scenario: Replace organisation key
- **WHEN** a manager proves possession and activates a saved replacement
- **THEN** subsequent recording windows use it
- **AND** older recordings continue to require their previous organisation-key version until explicitly transferred

### Requirement: Ordinary conversations remain independent of key setup
The system SHALL require an active personal employee key and organisation key
before starting a recording. It SHALL pin their versions for that recording
window. Ordinary conversations SHALL remain available without either setup,
including for admitted users who also hold reviewer permissions.

#### Scenario: No organisation key
- **WHEN** an admitted user starts an ordinary conversation without an organisation key
- **THEN** the conversation works
- **AND** a recording request fails with an explicit organisation-key prerequisite

#### Scenario: No personal enrolment
- **WHEN** organisation setup exists but the employee has not enrolled a personal key
- **THEN** recording cannot start until personal enrolment completes
- **AND** the ordinary conversation remains usable

#### Scenario: Rotation during recording
- **WHEN** a personal or organisation key is superseded during a recording window
- **THEN** that window retains its pinned recipients
- **AND** the next window selects the current active versions

### Requirement: Individually authorized exact-scope access transfer
Gateway SHALL require the explicit `ssf.recording.access.transfer` permission,
fresh MFA and current tenant membership for transfer preparation and commit.
Studio SHALL load the matching organisation key locally, verify signed source
wraps and rewrap only selected content keys for a server-resolved active target
key. Gateway SHALL bind commit to the exact prepared actor, tenant, source
version, content-key scope, target identity/version/fingerprint, reason and
submitted envelopes. It SHALL atomically recheck changing inputs, grant access
and audit without downloading recording contents or removing independent
existing grants.

#### Scenario: Possession alone is insufficient
- **WHEN** a caller has a matching organisation private key but lacks the individual transfer permission
- **THEN** preparation and commit are denied

#### Scenario: Target rotates before commit
- **WHEN** a target activates a different personal key after transfer preview
- **THEN** commit is rejected with a version conflict and creates no partial grants
- **AND** Studio must obtain a fresh preview and confirmation

#### Scenario: Scope changes
- **WHEN** a commit omits, duplicates or adds a prepared content key or a selected recording is deleted
- **THEN** the complete commit is rejected without granting a partial scope

### Requirement: Replay-resistant proof of local organisation-key possession
Gateway SHALL issue actor/tenant-bound five-minute single-use challenges encrypted
to the selected organisation public key and verify HMAC-SHA256 over the canonical
complete activation/transfer transcript in the design. The challenge nonce SHALL
never be returned plaintext or persisted plaintext. Gateway SHALL reconstruct the
transcript from authoritative state, recheck authorization and atomically consume
the preparation. Identical authorized commit retries SHALL return the stored
receipt; changed replay payloads SHALL be rejected. Proof SHALL establish
possession and submitted-scope authorization, not claim plaintext-equivalence
proof of rewrapped content keys.

#### Scenario: Missing private key
- **WHEN** a caller cannot decrypt the possession challenge
- **THEN** it cannot produce a valid commit proof

#### Scenario: Changed target or envelopes
- **WHEN** a valid proof is reused with a different target, scope or envelope bytes
- **THEN** verification fails and no grant is created

#### Scenario: Lost response
- **WHEN** an authenticated still-authorized caller repeats the identical successful commit after losing its response
- **THEN** Gateway returns the original receipt without duplicating grants or audit events

### Requirement: Verified Studio actor delegation
Studio SHALL obtain a Gateway-audience tenant-realm user bearer through its scoped
server session capability and configured RFC 8693 token exchange. Gateway SHALL
validate signature, issuer, configured audience, subject, tenant and permission
claims using existing user authentication and SHALL retain original MFA age.
Neither raw actor headers nor a client-credentials token SHALL substitute for the
user authority. Token exchange configuration and cross-application tests SHALL
be delivered before enabling this flow.

#### Scenario: Exchange does not refresh MFA
- **WHEN** a Studio user exchanges a token whose original MFA is too old
- **THEN** Gateway requires a new step-up rather than treating exchange time as authentication time

#### Scenario: Service credential without user
- **WHEN** a service credential or unverified actor header calls organisation or transfer APIs
- **THEN** Gateway denies the operation without granting administrative user authority

### Requirement: Explicit clean-start protocol cutover
The new recording protocol SHALL use explicit new envelope domains and
version-bound recipients without reinterpreting existing signatures. The system
SHALL detect incompatible legacy recording/recovery state and block affected
recording operations with a protocol-upgrade error while ordinary conversations
continue. Disposable legacy test data SHALL not be silently deleted. Reset SHALL
require a separately invoked operator tool with explicit target, dry run and
confirmation, preserving unrelated data. Legacy threshold recovery SHALL not
remain a substitute for the accepted new Studio flow after cutover.

#### Scenario: Legacy state at startup
- **WHEN** the new runtime encounters incompatible legacy recording state
- **THEN** it reports the required recording protocol upgrade without deleting data or showing a fabricated empty history
- **AND** ordinary conversations continue

#### Scenario: Proposal preparation
- **WHEN** this proposal is written or validated
- **THEN** no recording reset, deletion or runtime cutover occurs

### Requirement: Secret-free recording administration observability
Gateway and Studio SHALL exclude private key files, personal passphrases,
decrypted possession nonces, plaintext content keys, proof values and encrypted
personal blobs from logs, traces, telemetry and validation errors. Audits SHALL
record actor, purpose, scope references, key versions, outcome and commit receipt
without those secrets. Shared Python/TypeScript vectors SHALL verify exact
canonical encoding and correct local rewrapping.

#### Scenario: Invalid import or proof
- **WHEN** file parsing or proof validation fails
- **THEN** the user receives a coded value-free error
- **AND** logs and network requests do not expose the private key, passphrase or decrypted challenge
