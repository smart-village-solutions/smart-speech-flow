# Recording key lifecycle and shared Studio contract

## Scope and ownership

Gateway owns public key versions, authorization, encrypted personal key blobs,
recording recipients, transfer preparation/commit and append-only audit. Studio
owns organisation key generation/export/import and browser-side rewrapping.
SSF owns personal passphrase entry and its tab-local version-aware vault.
Neither application server receives the organisation private key, personal
passphrase, plaintext content keys or a decrypted possession challenge.

The existing P-256, HKDF-SHA256, AES-256-GCM and canonical length-prefixed `enc`
primitives are reused. No cryptography framework is added. This is a new
recording protocol generation, not a reinterpretation of legacy signed fields.

## Personal keys and ongoing work

Keep personal ECDH/ECDSA key pairs and passphrase-encrypted server blobs.
`user_keys` remains keyed by tenant, user and positive version. Replace the
overloaded retirement lifecycle with states `active`, `superseded`, `revoked`
and `left`; exactly one active version exists per user. Superseded versions
retain their encrypted blobs and access; revoked/left versions cannot be used.
Public signing keys remain available to verify historical decisions.

New user wraps include recipient user and key version/fingerprint. Their unique
identity includes the recipient version, allowing more than one version for the
same content key and user. Explicit access grants carry reasons, including
owner, organisation transfer and review assignment. Closing an assignment
removes its grant and any wrap no remaining grant needs; it does not remove an
independent owner/transfer grant for that version.

Normal re-enrolment keeps fresh MFA and E-Mail confirmation. Confirmation
atomically supersedes the active version and activates the pending version;
it does not delete existing wraps/blobs or withdraw reviews. An ordinary
replacement is not a lost-key revocation. Actual revocation and leaving remain
explicit destructive access operations with separate authorization and audit.

`GET /api/admin/recording/v2/keys/me` returns
`{activeVersion,versions:[{version,state,fingerprint,encPub,sigPub,createdAt}]}`.
`GET /api/admin/recording/v2/keys/me/{version}` returns the caller's corresponding
encrypted `blob` and public metadata for active or superseded versions, with the
existing blob-read audit/rate limits. Other users and revoked/left versions are
not served. The existing initial-enrolment, re-enrolment and confirmation routes
retain their URLs and adopt these lifecycle semantics after cutover.

The SSF vault holds a map keyed by `(tenantId,userSub,version,fingerprint)` and
keeps only non-extractable unlocked keys in current-tab memory. Unlocking one
version does not unlock others; its personal passphrase file contains only the
passphrase, not a private key. Reload, logout, tenant/account change, expiry and
explicit lock clear the map. Ordinary supersession does not clear still-valid
historical keys. In-flight work checks the vault generation and target version.

This supersedes the normal replacement invalidation and "current enrolled keys"
restriction in the completed but unarchived `add-recording-key-convenience`
proposal. Its passphrase-file policy and other invalidation conditions remain
applicable; actual revocation still invalidates the affected version.

Archive access returns `requiredKeyVersions` and a versioned wrap for each
accessible content key. Review records return `reviewerKeyVersion` and the
corresponding fingerprint. A decision is verified against that still-usable
assigned version rather than whichever version is active today. New review
assignments and new recording windows select the current active version.
A recording window pins its initial employee/organisation recipients. Later
rotation does not alter that window; a subsequent window selects current keys.
Crypto operations pin their input versions and reject an actual revocation.

Initial personal enrolment is required before an employee can request a
recording. Both personal enrolment and active organisation-key readiness are
checked before recording starts. Ordinary conversations have neither prerequisite.

## Authentication and permissions

All APIs below use the existing Gateway tenant-realm user bearer validation and
configured `KEYCLOAK_AUDIENCE`, effective `ssf_permissions`, validated tenant
context and user `sub`. Organisation-key lifecycle mutations require
`ssf.configuration.tenant.manage`; transfers require the distinct individual
`ssf.recording.access.transfer`. Organisation administration alone never grants
recording content access. Preparation and commit both require existing fresh
MFA (`acr` and original `auth_time`) and recheck effective permission/tenant
membership. Current target identity and key bindings are rechecked at commit.
Studio exposes transfer as an individually assigned permission, excluded from
automatic `system_admin` inheritance. Candidate reads require transfer permission;
organisation public-key metadata requires management or transfer permission.
Transfer preparation/commit check current transfer permission and target
membership through the authenticated Studio directory rather than relying only
on a potentially stale token snapshot.

Studio implements a scoped server host capability resolving its authenticated
handler's session ID to the server-held `Session.accessToken`. Its confidential
client calls the tenant Keycloak token endpoint using RFC 8693:
`grant_type=urn:ietf:params:oauth:grant-type:token-exchange`,
`subject_token_type=urn:ietf:params:oauth:token-type:access_token`,
`requested_token_type=urn:ietf:params:oauth:token-type:access_token`,
`subject_token=<server-held user token>`, and
`audience=<configured Gateway KEYCLOAK_AUDIENCE>`.
Keycloak client policy and audience/permission/tenant mappers are explicit
implementation deliverables. Exchanged tokens preserve original `sub`, tenant,
`acr` and `auth_time`; exchange cannot renew MFA. The scoped capability sends
the bearer only to the configured Gateway; neither plugins nor browsers receive
it. No client-credentials or raw actor-header fallback is allowed. Unsupported
exchange or missing claims returns a safe unavailable/step-up result. Tests
must prove the configured issuer supports this flow before release.

Keycloak standard token exchange V2 is same-realm: Studio's session, confidential
exchange client and Gateway-accepted user issuer must belong to the same selected
tenant realm. Provision that session/client path if the existing Studio login
uses a central realm; do not attempt an assumed cross-realm exchange. Requested
audience cannot add scopes absent from the subject token, so provision the
Gateway audience and required claims/scopes on that user session. Test this
deployment prerequisite against the actual configured realm and Keycloak
version. References: [Keycloak token exchange](https://www.keycloak.org/securing-apps/token-exchange)
and [RFC 8693](https://www.rfc-editor.org/rfc/rfc8693.html).

## Shared organisation key APIs

Base path: `/api/admin/recording/v2`. JSON field names are camelCase. Binary
fields use unpadded base64url. Generated protocol entity IDs are canonical
lowercase UUID strings; tenant IDs and user subjects retain their existing
opaque identifiers. Versions are positive integers; timestamps are UTC RFC 3339.
Personal enrolment/replacement retains existing personal recording-key
permissions, fresh MFA and verified E-Mail; it does not require tenant management.

An `OrganisationKey` is
`{keyId,version,publicKey,fingerprint,state,createdAt,activatedAt}` where state
is `prepared`, `active` or `superseded`. P-256 public keys use 65-byte SEC1
uncompressed encoding. Fingerprint is
`SHA256(enc("SSF-ORG-KEY-V1",tenantId,keyId,version,publicKeyBytes))`.
Gateway is the sole authoritative store; Studio does not mirror a mutable key
registry into configuration documents.

- `GET /organisation-keys` returns `{activeKeyId,keys:OrganisationKey[]}`.
- `POST /organisation-keys/preparations` takes
  `{publicKey,expectedActiveKeyId}` (null for first setup), allocates the ID and
  version, and returns
  `{preparationId,keyId,version,fingerprint,expiresAt,challengeEnvelope}`.
- `POST /organisation-keys/preparations/{id}/activate` takes
  `{proof,savedConfirmation:true}` and atomically returns active key metadata.
  Previous active key ID is compare-and-swapped. Preparation does not change
  the active key. Old public metadata and older-recording associations survive.
- `DELETE /organisation-keys/preparations/{id}` abandons an uncommitted
  preparation; no active-key change or key-file destruction occurs.

The browser creates an extractable ECDH P-256 private key locally for export,
then retains an imported non-extractable operational key only in memory. Its
download is UTF-8 JSON:
`{format:"ssf-organisation-key",formatVersion:1,tenantId,keyId,version,publicKey,fingerprint,privateKeyPkcs8}`.
PKCS#8 and public binary values use base64url. It is an explicitly labelled
unencrypted private-key file. Export protection is outside this version;
custody may use the organisation's password manager or physical safe. A print
view contains the same complete base64url file value and custody notice.
Imports are explicit, bounded to 64 KiB, strict-schema validated, check P-256
private/public consistency, tenant/ID/version/fingerprint and chosen scope;
an employee passphrase TXT file is rejected. Browser memory is cleared on
cancel, navigation away, logout, tenant change and completion.

## Exact-scope access transfer

- `GET /access-transfer/candidates?employeeSub=<sub>&cursor=<opaque>` returns
  `{items:[{conversationId,employeeSub,startedAt,endedAt,keyIds,organisationKeyIds}],nextCursor}`.
  It exposes authorized metadata only, no names/languages decrypted from
  content. Each page contains at most 50 items.
- `POST /access-transfer/preparations` takes
  `{conversationIds,organisationKeyId,targetUserSub,expectedTargetKeyVersion,expectedTargetFingerprint,reason}`.
  The selection is 1–100 distinct conversations and reason is 1–1000 characters.
  Preparation covers at most 1000 content keys; larger scope receives
  `TRANSFER_SCOPE_TOO_LARGE`. The authenticated source tenant is implicit.
- Preparation returns
  `{transferId,scopeDigest,expiresAt,organisationKey,targetKey,challengeEnvelope,keys}`,
  where `targetKey={userSub,version,fingerprint,encPub,sigPub}` and each key is
  `{conversationId,keyId,epoch,sourceWrap,sourceSigner}`. The source wrap is
  signed for the selected organisation-key version; signer metadata includes
  its trusted public verification key and ID. The server-resolved target
  identity is displayed for confirmation before committing.
- `POST /access-transfer/preparations/{id}/commit` takes
  `{proof,wraps:[{conversationId,keyId,envelope}]}` and returns
  `{transferId,status:"committed",targetUserSub,targetKeyVersion,scopeDigest,grantedKeyIds,committedAt}`.
  Scope is exactly the prepared keys: no omissions, duplicates or extras.

Each preparation uses one organisation-key version. If selected conversations
require different versions, Studio groups them into separately confirmed
preparations, requiring the relevant historical key files. Missing wraps or
keys cannot be bypassed. Ordinary transfer adds a target grant and does not
silently remove existing grants. Review assignment remains a separate operation.

Studio verifies source-wrap Gateway signatures/context, decrypts only the
selected content keys and locally wraps each to the exact target version. It
does not download or decrypt recording contents. The commit transaction locks
the organisation-key row, target key, conversations and preparation in a
documented consistent order and rechecks target active version/fingerprint,
membership, permissions, retention/deletion, selected source wraps and complete
key inventory. Changed input returns 409 and requires a fresh preview. No partial
grants are committed.

## Possession proof and versioned cryptographic envelopes

Every preparation contains a cryptographically random 32-byte secret nonce N,
a random UUID, actor, tenant, purpose, immutable scope snapshot and an expiry
five minutes after creation. Gateway encrypts N to the proposed/selected org
public key using the existing ECIES primitives with the new type tag
`SSF-ORG-POSSESSION-V1` and context
`enc(tenantId,actorSub,preparationId,purpose,keyId,version,expiresAt)`.
The envelope wire representation remains the existing ECIES object
`{v:1,t,R,nonce,ct}`; a new tag is explicitly registered in both runtimes.
N is never returned plaintext, persisted plaintext or included in logs/errors.
The server stores N encrypted under its configured server-layer key for the
short preparation lifetime; the browser decrypts N locally.
The at-rest envelope uses dedicated associated data binding tenant, preparation
ID and purpose. A missing server-layer key fails preparation closed.

`enc` is the existing encoding of two-byte length-prefixed fields, UTF-8
strings, decimal-ASCII unsigned integers and raw bytes. Hashes below are raw
32-byte SHA-256, with list elements sorted lexicographically by canonical IDs.

For activation, the canonical transcript is:

`enc("SSF-ORG-ACTIVATE-V1",tenantId,actorSub,preparationId,keyId,version,publicKeyBytes,fingerprintBytes,expectedActiveKeyIdOrEmpty,expiresAt,"saved")`.

For transfer, each scope member digest is:

`SHA256(enc(conversationId,keyId,epoch,organisationKeyId,organisationVersion,SHA256(canonicalSourceEnvelope)))`.

`scopeDigest=SHA256(enc("SSF-TRANSFER-SCOPE-V1",memberDigest1,...))`.
An envelope's canonical bytes are
`enc(v,t,RBytes,nonceBytes,ciphertextBytes)`; the submitted result digest is
`SHA256(enc("SSF-TRANSFER-WRAPS-V1",enc(conversationId,keyId,SHA256(canonicalTargetEnvelope)),...))`.

The transfer transcript is:

`enc("SSF-ACCESS-TRANSFER-V1",tenantId,actorSub,transferId,organisationKeyId,organisationVersion,organisationFingerprintBytes,targetUserSub,targetKeyVersion,targetFingerprintBytes,scopeDigestBytes,SHA256(UTF8(reason)),resultDigestBytes,expiresAt)`.

`proof=HMAC-SHA256(key=N,message=transcript)`; compare constant-time. No endpoint
returns N, accepts a plaintext decrypted challenge or accepts an arbitrary
transcript supplied by the client. Gateway reconstructs transcripts from its
snapshot and strict validated submitted envelopes. A possession proof authorizes
an exact submitted transfer; it is **not** a zero-knowledge proof that submitted
wraps contain the same plaintext keys. Correct rewrapping is the authenticated
client's responsibility, covered by shared Python/TypeScript known-answer tests.

New content-key wrap type `SSF-CK-WRAP-V2` binds
`enc(tenantId,conversationId,keyId,recipientKind,recipientRef,recipientVersion,recipientFingerprintBytes)`
as ECIES context; kinds are `user` and `organisation`. Gateway signs
`enc("SSF-CK-WRAP-SIG-V2",contextBytes,canonicalEnvelopeBytes)` after validating
the transfer proof and before storing the target grant. Gateway signing key ID
and authenticated actor/audit receipt remain available to readers. All wrap
readers explicitly dispatch on protocol generation/tag; legacy signatures are
never checked against changed fields.

A preparation is actor/tenant-bound and single-use. Identical validated commit
retries return the stored receipt after normal authentication and permission
checks; a different payload/proof after commit returns `PREPARATION_USED`.
Activation has the same behavior: an identical successful retry returns its
stored activation result without reactivating that key, even if another key has
since superseded it. Studio then reconciles current state using GET. The stored
receipt includes a digest of the canonical request, not the secret nonce.
Expired/abandoned preparations cannot commit; the nonce is deleted on completion
or expiry. After five invalid proofs the preparation is cancelled. Request
bodies, proof values, key files, encrypted private blobs and decrypted N are
excluded from logs, traces, analytics and validation errors. Standard
value-free validation/rate-limiting patterns apply.

## Errors and deployment

Use existing coded envelopes: 403 `PERMISSION_REQUIRED` or `STEP_UP_REQUIRED`,
404 `PREPARATION_NOT_FOUND`, 409 `KEY_VERSION_CHANGED`, `SCOPE_CHANGED`,
`PREPARATION_USED`, 410 `PREPARATION_EXPIRED`, 422 `INVALID_KEY`,
`INVALID_PROOF`, `TRANSFER_SCOPE_TOO_LARGE`, 503 `RECORDING_UNAVAILABLE`.
Unknown cross-tenant IDs return the same 404 as unknown IDs. No response leaks
secret validation values. A forbidden/missing recording prerequisite returns
`PERSONAL_KEY_MISSING` or `ORGANISATION_KEY_MISSING` before recording starts.

Existing recording/recovery rows belong to the legacy generation. A new
generation marker rejects incompatible recording operations with
`RECORDING_PROTOCOL_UPGRADE_REQUIRED`; ordinary conversations still work.
No automatic destructive startup migration or silent empty-history substitution
is allowed. Supply a later operator-invoked reset tool/runbook with explicit
tenant/database/storage target, dry run, affected-resource inventory and explicit
confirmation; preserve unrelated ordinary conversations, feedback and usage data.
Only after the authorized clean start may the new protocol become active.
Disposable test content does not require a legacy data migration. Remove public
legacy ceremony/recovery routes and UI after the new end-to-end acceptance
passes; retain audit/public verifier material as required and do not repurpose
old cryptographic identifiers.

## Verification boundaries

Gateway tests own authorization, CAS, expiry/replay, schema and grant lifecycle.
Shared vectors own canonical transcripts, fingerprints, ECIES, HMAC and wraps.
Studio tests own file handling and secret-free HTTP requests. SSF tests own
multi-version unlocking, preserved old reviews and recording prerequisites.
Real Postgres integration tests verify transaction atomicity and grant cleanup;
two-tenant integration covers token exchange, cross-tenant rejection, org-key
setup, recording, rotation, transfer and a final signed review.
