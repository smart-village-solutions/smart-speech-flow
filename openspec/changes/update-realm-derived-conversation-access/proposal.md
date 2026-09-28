# Change: Derive conversation tenancy from the verified realm

## Why

Active users in admitted Studio tenant realms can be blocked by obsolete SSF
token attributes and roles. Issue smart-speech-flow#438 approves replacing
those user-token requirements with verified issuer and directory admission.
Related tracking and production acceptance: smart-speech-flow#363/#266 and
sva-studio#1480/#1350. Older claim-required criteria in these issues are
superseded for conversation admission, not for distinct administrative rights.

## What Changes

- **BREAKING**: Conversation access no longer requires `ssf-user`,
  `studio_tenant_id`, `ssf_authorization_revision`, `ssf_permissions`, or
  `ssf_roles` in the user token.
- Derive the tenant exclusively from the verified issuer and one admitted
  Studio login-directory entry; never use legacy claims as selectors.
- Stop comparing the user-token authorization revision with Runtime
  Configuration V1; retain runtime tenant matching.
- Keep feedback reading and telemetry probing behind their separate role
  checks, and retain tenant isolation across HTTP, polling, and WebSocket.

## Impact

- Affected specs: conversation access, tenant isolation
- Affected code: API gateway auth, tenant context, runtime flow, session
  access, feedback reads, telemetry probe, tests, and operations documentation
- Rollout: deploy the compatible gateway consumer before removing legacy
  attributes from token production; verify live fresh tokens in two realms.
