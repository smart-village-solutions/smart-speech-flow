## Decision

Use the existing valid authenticated user session as the identity prerequisite
for sensitive actions. MFA strength is determined at login by the tenant policy.
Remove the sensitive-action freshness policy rather than increasing its timeout
or replacing it with an MFA-for-the-whole-session requirement; neither alternative
would satisfy optional-MFA password-only users.

## Gateway

Inventory every `require_step_up` consumer. Remove the freshness dependency while
ensuring each route retains `require_ssf_user` directly or through its permission
dependency. Remove unused freshness constants/helpers. Do not implement this by
making `require_step_up` return true unconditionally. Preserve domain guards,
tenant boundaries, confirmations, rate limits and audit.

The pending organisation-key and access-transfer contract adopts the same rule.
Retain actual five-minute encrypted possession challenges and their exact-scope
proofs: challenge expiry is independent of authentication age.

## Frontend

Remove proactive freshness gates and `maxAge: 0`/MFA redirects in sensitive-action
flows, plus recovery batch projections and pre-submit checks based on MFA age.
Keep ordinary auth initialization, token refresh and session-expiry handling.
Remove obsolete prompts, fault variants and translations once their callers are
gone. Preserve return targets through local key unlock and normal login when a
session actually ends. A valid login alone does not unlock encrypted private keys.
Within that valid session, the matching local Zugangsschlüssel is the sole unlock
credential for the user's active and usable historical keys, including after
explicit lock or reload. Fetch encrypted blobs through the existing authenticated
session without step-up. An incorrect passphrase produces a local unlock error,
not an account-login redirect. Email confirmation remains a key-replacement
safeguard and is not an unlock prerequisite.

## Delivery and verification

Update Gateway and SSF together so an old frontend does not keep challenging users
after Gateway's policy changes. Coordinate Studio and realm configuration so
mandatory login MFA continues to work and action-specific realm overrides do not
reintroduce challenges. Update deployment documentation without rewriting past
test evidence as if the new policy had already been tested.

Prove the policy for password-only sessions and MFA logins older than 300 seconds,
including absent optional freshness claims, through representative route tests and
audit all consumers. Preserve negative tests for invalid/expired authentication,
wrong tenant, missing permissions and expired cryptographic preparations. Verify
local unlock, recovery computation and normal refresh without step-up redirects.
Runtime implementation remains pending proposal approval.
