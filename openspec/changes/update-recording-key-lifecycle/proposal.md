# Change: Version personal recording access and replace threshold recovery

## Why

Personal key replacement currently removes existing access and withdraws open
reviews. Organisation recovery depends on shared-key ceremonies. The agreed
dashboard concept instead requires existing personal access to survive ordinary
key replacement, and Studio-managed access transfer using a locally held
organisation private key.

The product term "Zugangsschlüssel" means the personal passphrase, not a raw
private key. Personal private keys remain encrypted in server-side blobs.

## What Changes

- Add version-aware personal recipients, historical encrypted key retrieval and
  separate supersession and revocation lifecycles.
- Preserve existing recording access and review assignments on supersession;
  future recordings and assignments use the new active version.
- Make Gateway the single authoritative store of versioned organisation public
  keys, while Studio generates, exports and uses private keys locally.
- Add authenticated organisation-key preparation/activation and exact-scope
  access-transfer APIs with cryptographic proof of local key possession.
- Require personal enrolment and an active organisation key before recording;
  ordinary conversations remain available independently.
- Introduce the explicit individual `ssf.recording.access.transfer` permission.
- **BREAKING:** introduce a new recording protocol generation and explicit
  operator-controlled clean-start cutover for disposable recording/recovery test
  data. No legacy migration is required. This proposal does not authorize data
  deletion, reset production stores or silently reinterpret old envelopes.
- Replace employee-facing threshold-recovery workflows only after the new
  Studio flow passes integration acceptance.

## Impact

- New capability: `recording-key-lifecycle`.
- Gateway: recording keys, archive recipients/access, verification decisions,
  permissions, wiring, routes and recording Postgres schema.
- SSF: version-aware in-memory key vault and account/recording/review adapters;
  dashboard presentation is owned by `add-task-oriented-ssf-dashboard`.
- Studio: consumes this contract through `add-ssf-organisation-key-management`;
  organisation private-key handling stays in its browser.
- Infrastructure: a configured Keycloak standard token-exchange client policy
  allows Studio's server-held user token to obtain the existing Gateway
  audience, with original identity and MFA context preserved.
- Existing personal passphrase file policy remains unchanged. Existing signed
  content is neither reinterpreted nor migrated by this change.

## Status

Approved by the user on 2026-11-18; implementation is tracked in this change. The user confirmed that
existing recording/recovery data is disposable test data and did not authorize
its deletion. Reset remains a separate, explicit operator action.

## Approval

Approved by the user in the development conversation on 2026-11-18. Implementation is authorized; deployment and test-data reset remain separate operator actions.

## Subsequent authentication policy

The additionally approved `remove-sensitive-action-reauthentication` change supersedes all action-specific fresh-MFA requirements in this proposal and its design/tasks. A valid authenticated user session is sufficient regardless of optional MFA claims or original login age. Identity, tenant, permissions, session expiry, local key passphrases, replacement email confirmation and actual cryptographic preparation expiry remain enforced. Historical acceptance evidence is not rewritten.
