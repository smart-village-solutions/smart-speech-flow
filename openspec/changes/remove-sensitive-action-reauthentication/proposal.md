# Change: Reuse the authenticated session for sensitive actions

## Why

A successful login, including MFA when required by the tenant's login policy,
must suffice for subsequent actions in the valid session. The current recording
flows demand fresh MFA after five minutes and can interrupt ongoing work.

## What Changes

- Remove action-specific password/MFA challenges and `acr=mfa`/`auth_time`
  freshness gates in Gateway and SSF, including legacy recording flows still
  exposed before the key-lifecycle cutover.
- Apply the same rule to the planned Studio organisation-key activation and
  access-transfer APIs. A password-only session admitted under optional login
  MFA is sufficient; mandatory login MFA remains enforced at login.
- Preserve token validation, session expiry and refresh, tenant isolation,
  effective permissions, audit, confirmations and cryptographic possession
  proofs. Within a valid session, unlocking the user's own keys depends only on
  the matching local passphrase (the personal **Zugangsschlüssel**), without a
  new account login, login-password entry, MFA or email confirmation. This applies
  to current and usable historical key versions, including after explicit lock
  or reload. Existing email confirmations apply to key replacement, not unlock.
- Remove UI prompts, redirects and computation deadlines based only on the
  five-minute MFA window. Actual preparation/challenge expiry remains enforced.
- Supersede the sensitive-action step-up clauses in
  `add-studio-recording-administration` and earlier recording plans/runbooks
  when this change is implemented. Align the pending dashboard and key-lifecycle
  proposals now; completed historical acceptance records remain historical.

## Impact

- New capability: `authenticated-action-continuity`.
- Gateway: recording permission dependencies and every route using
  `require_step_up`; authentication itself must remain mandatory.
- SSF: auth helpers, step-up prompts, recovery/ceremony/keys/archive/review flows,
  return navigation, translations and associated tests.
- Studio coordination: optional/required login MFA, organisation-key management,
  user-token exchange and access transfer.
- Operations: authentication architecture and recording deployment runbooks.
- Security trade-off: an authorized valid session can perform sensitive actions
  without a second identity challenge. Short-lived cryptographic preparations,
  authorization and content-key possession remain independent controls.

## Status

Proposed. Runtime implementation requires approval under `openspec/AGENTS.md`.
This proposal does not make sessions permanent or authorize plaintext key storage.
