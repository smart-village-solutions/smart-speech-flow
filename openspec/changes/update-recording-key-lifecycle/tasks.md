## 1. Contract and cryptographic vectors

- [ ] 1.1 Implement strict DTOs and coded errors for the exact APIs in `design.md`; publish corresponding Studio-facing schema fixtures and keep base path `/api/admin/recording/v2` consistent.
- [ ] 1.2 Extend `recording/crypto/{tags,ecies,signatures,encoding}.py` and browser crypto primitives for the new possession and V2 wrap domains without changing legacy canonical fields.
- [ ] 1.3 Add shared Python/TypeScript known-answer vectors for org fingerprints, activation/transfer transcripts, source-scope/result digests, ECIES challenge open, HMAC and content-key rewrap. Test changed actor, target, version, scope, nonce and ciphertext failures.

## 2. Versioned persistence and personal lifecycle

- [ ] 2.1 Add the next recording Postgres migration for protocol generation, personal key states, versioned recipients/grants, standalone organisation keys, encrypted short-lived preparation secrets and committed receipts. Preserve RLS, one-active-key invariants and existing audit integrity.
- [ ] 2.2 Update `recording/{repository,keys,reenrolment_repository,key_retirement,key_confirmation_repository}.py` and `routes/recording.py` to distinguish supersession from revocation/leaving and expose the versioned personal-key list/blob APIs. Keep MFA, verified E-Mail and delayed activation.
- [ ] 2.3 Add lifecycle unit and real Postgres tests: replacement preserves old encrypted blobs/wraps/assignments, new grants use active version, revoked/left versions are denied, concurrent confirmations cannot create two active versions, blob reads remain audited.

## 3. Organisation lifecycle and actor authorization

- [ ] 3.1 Create focused `recording/organisation_keys.py`, its repository, strict models and `routes/recording_organisation_keys.py` for list/preparation/activation/cancel; wire using existing dependency/container conventions.
- [ ] 3.2 Enforce tenant-manager permission and fresh MFA at preparation/activation; implement public-key point checks, encrypted nonce storage, fingerprint computation, expected-active CAS, secret-free errors and receipt retries.
- [ ] 3.3 Coordinate Studio's scoped session-token capability and RFC 8693 adapter with explicit tenant Keycloak audience/claim/exchange-policy configuration. Add integration tests proving original sub/tenant/MFA preservation and rejection of client credentials, raw actor headers, wrong audience, stale MFA and missing effective permissions.
- [ ] 3.4 Add tests for first setup, abandoned replacement, old-key metadata retention, expired/changing/replayed activation and concurrent activation.

## 4. Exact-scope organisation transfer

- [ ] 4.1 Add `ssf.recording.access.transfer` in `recording/permissions.py` and coordinate its Studio permission definition/assignment. Do not make organisation management imply transfer or content access.
- [ ] 4.2 Create focused `recording/access_transfer.py`, repository/models and `routes/recording_access_transfer.py`; implement paginated authorized candidates and bounded exact-scope preparations tied to one organisation-key version and one active target version.
- [ ] 4.3 Implement HMAC possession verification from server-owned transcripts, strict complete target-wrap validation, Gateway V2 signatures and atomic grant/audit commit. Enforce consistent row-lock order with retention/archive writers and idempotent receipt behavior.
- [ ] 4.4 Test cross-tenant IDs, foreign actors, no possession, malformed keys, changed source wraps/content-key inventory, target key rotation, permission removal, expired/deleted recordings, scope omission/duplicates/additions, five failed proofs and concurrent/retried commits. Verify no partial grants.
- [ ] 4.5 With Studio's client, test local rewrap against shared vectors and inspect outgoing requests/logs to establish no private file, decrypted challenge, personal passphrase, plaintext content key or recording content crosses the server boundary.

## 5. Recording, archive, reviews and SSF account integration

- [ ] 5.1 Update `recording/{archive_service,conversation_keys,session_service,wiring}.py` to require personal enrolment and active org key before recording and pin recipient versions per recording window. Ordinary conversation operations must remain independent.
- [ ] 5.2 Update `recording/archive_access*.py`, archive DTOs and grants to return required personal versions and version-bound wraps; preserve historical Gateway signer discovery.
- [ ] 5.3 Update `recording/verification*.py` and review routes to verify existing assignments/decisions against assigned usable versions, issue new assignments to the active recipient, and release only assignment-dependent grants on completion/return.
- [ ] 5.4 SSF agent: update `src/core/crypto/{key-vault,archive-crypto.port,web-archive-crypto}.ts`, personal key repositories/hooks and account screen to select/unlock required versions locally while preserving existing passphrase TXT policy and tab-only lifetime. Coordinate screen ownership with `add-task-oriented-ssf-dashboard` before editing shared files.
- [ ] 5.5 SSF agent: propagate `requiredKeyVersions` and assigned reviewer version to archive/review opening and signing; make rotation during an open recording window deterministic and show personal-enrolment prerequisite before recording.
- [ ] 5.6 Test V1 recording and assignment, V2 activation, V1 unlock/read/decision, new V2 recording/assignment, explicit lock/logout/reload and delayed async unlock invalidation. Independently test actual revocation still blocks access.

## 6. Explicit clean-start cutover and acceptance

- [ ] 6.1 Add protocol-generation detection that rejects incompatible recording/recovery stores without deleting or silently reinterpreting them; verify ordinary conversations continue.
- [ ] 6.2 Prepare an operator-only reset tool and English runbook with explicit target, dry-run inventory, confirmation, recording-object/database dependencies and preservation of unrelated data. Do not execute reset under this proposal or infer deletion authorization from disposable data.
- [ ] 6.3 Complete two-tenant Studio/Gateway/SSF acceptance using isolated new test stores: setup/export, activation, recording prerequisites, old/new personal versions, organisation replacement, transfer, recording viewing, review completion and permission revocation.
- [ ] 6.4 Remove user-facing legacy threshold ceremony/recovery entry points and public routes only after replacement acceptance. Verify no old UI links or missing recovery services remain; preserve required historical audit/verifier material.
- [ ] 6.5 Run focused Gateway pytest, Postgres integration and SSF frontend suites plus shared vectors; record evidence and coordinated release ordering. Keep this proposal pending until approved.
