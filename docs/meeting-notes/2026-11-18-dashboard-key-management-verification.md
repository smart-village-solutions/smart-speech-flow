# Dashboard and key management verification

## Delivered scope

The approved dashboard, recording-key lifecycle and Studio organisation-key
changes were implemented together. The additional
`remove-sensitive-action-reauthentication` change supersedes earlier
action-specific MFA requirements. The ordinary tenant login policy, verified
user identity, session expiry and effective permissions remain enforced.

SSF presents conversations and reviews as additive tasks, with independent
filters, bounded loading, protected metadata and existing conversation-minute
reporting. Account navigation preserves a running conversation. Personal
Zugangsschlüssel remain passphrases used locally to unlock encrypted personal
key blobs, including usable historical versions. Ordinary replacement retains
historical access; explicit revocation and leaving remain separate operations.

Studio generates and uses organisation private keys locally. Activation and
exact-scope access transfers use the shared Gateway contracts, canonical
cryptographic vectors and possession proofs. A scoped same-realm user-token
exchange forwards the authenticated actor. Organisation management does not
implicitly grant transfer or recording-content access.

## Verification boundaries

The acceptance combines real PostgreSQL lifecycle/authorization tests, SSF
component and Chromium tests, and a two-tenant Studio–Keycloak–Gateway journey.
The latter uses real Chromium login, optional password-only and mandatory MFA
login policy, standard token exchange, signed-token/JWKS validation, HTTPS
Gateway requests and isolated PostgreSQL. It exercises organisation setup,
replacement, historical transfer, idempotent receipts and permission denial.

The older-session journey waited more than 300 seconds, observed bearer-token
expiry, refreshed the genuine session and completed the actions. Terminating
the session denied further refresh and exchange. Missing optional authentication
context claims are covered at the verified-token boundary. Own-key tests use
the actual Argon2id/WebCrypto implementation, versioned encrypted blobs and
tab-local vault, including incorrect passphrases, lock and reload.

The Studio journey injects test session/configuration lookup, a synthetic
directory and seed recordings; local organisation operations use the production
WebCrypto implementation in Node. React page tests use jsdom. SSF Chromium tests
use HTTP/WebSocket fixtures. These checks do not constitute a complete deployed
ASR/TTS/audio-storage acceptance or a production rollout. External SMTP/Mailpit
cases require their separately configured service.

Reproducible entry points are `tests/integration/recording_browser_gateway.py`
and Studio's `packages/plugin-ssf/tests/recording-gateway-journey.ts`, driven by
`packages/auth-runtime/src/keycloak-admin-client/login-mfa.keycloak.integration.test.ts`.
Shared contracts and known answers are
`tests/fixtures/recording/studio_gateway_v2.openapi.json` and
`tests/fixtures/recording/lifecycle_v2.json`. SSF's Playwright scenarios and
personal-key continuity tests cover the separate browser integration.

Independent reviews cover Gateway lifecycle/authorization, SSF behavior/privacy,
Studio custody/exchange/UI and cross-repository integration. Regression tests
cover the review findings, including retained-session metadata during storage
reconnection, historical-only leavers, mixed-generation retention, partial
transfer coverage and responses arriving after a preparation deadline.

## Operational handoff

Implementation lives in isolated branches `feat/dashboard-organisation-keys`
(SSF) and `feat/recording-key-convenience` (Studio). Deploy the coordinated Studio,
Gateway and Keycloak provider versions using the existing rollout process, with
same-realm exchange configuration and the shared deployment secret described in
the runbooks. Login MFA remains the tenant's policy.

No deployment, push, merge or reset of existing data was performed. The
[v2 cutover runbook](../operations/runbooks/recording-key-v2-test-cutover.md)
provides an explicit dry-run inventory and separately confirmed operator reset.
Disposable test data removes the migration requirement; it does not authorize
deleting an existing installation's data.
