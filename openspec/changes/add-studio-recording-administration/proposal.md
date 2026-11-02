# Change: Deliver Studio administration for recording policy and identity

## Why

SSF already consumes recording policy, legal wording and recording-directory responses, but Studio must administer and produce them. The confirmed decisions add a 30-day retention default with installation and tenant configuration and optional ordinary-login MFA managed through Studio and Keycloak.

## What Changes

- Add installation retention defaults, tenant overrides and effective runtime recording policy; retain the 8760-hour maximum.
- Administer recording settings and localized legal wording in the Studio SSF plugin, preserving disabled recording until explicitly configured and enabled.
- Extend Studio IAM projection with five recording permissions and reviewer languages, and expose a live tenant recording directory.
- Configure optional or organisation-required login MFA through Studio Core/IAM and Keycloak, preserving existing SSF sensitive-action step-up checks.
- Retire legacy conversation-storage administration and obsolete guest wording.
- Document cross-repository implementation tasks, integration acceptance and staged rollout.

## Impact

- Affected spec: studio-runtime-integration (additional producer obligations; existing historical consumer requirements are not rewritten by this proposal).
- Studio implementation: `packages/plugin-ssf`, Core/IAM realm provisioning, API documentation and tenant user management.
- SSF implementation: contract fixtures, compatibility tests and documentation; existing recording consumers are reused.
- Related issues: [#612](https://github.com/smart-village-solutions/smart-speech-flow/issues/612), [#611](https://github.com/smart-village-solutions/smart-speech-flow/issues/611).
- Studio must carry the matching approved specification in its repository before implementation. This SSF-side proposal is the handoff contract, not evidence of delivered Studio behavior.
- Implementation approved by the user on 2026-11-02. Studio work is tracked in its matching `add-ssf-recording-administration` change; the SSF changes align fixtures and consumer acceptance. Existing archives and production configuration are unchanged.
