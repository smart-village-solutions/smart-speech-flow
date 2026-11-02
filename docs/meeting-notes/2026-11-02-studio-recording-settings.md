# Decisions: Studio requirements for recording modes

- Date: 2026-11-02
- Source: requirements and explicit confirmations in the development conversation.

## Decisions

- These are SSF development requirements for Studio. Studio owns administration; SSF consumes the effective policy and enforces recording behavior.
- Recording stays disabled without a valid Studio recording policy. Supplying legal wording alone does not enable recording.
- Recording retention defaults to 30 days (720 hours). A tenant override takes precedence over the installation default. The current maximum remains 365 days (8760 hours).
- MFA is voluntary for ordinary login unless the organisation makes it mandatory. Studio manages that policy in Keycloak; users enroll their personal factor in Keycloak.
- Organisations can supply localized consent texts; missing configuration preserves SSF's bundled draft wording and existing localization fallback behavior.
- Studio supplies recording permissions, reviewer languages and sworn status, and a live directory of permission holders.
- Retire the old conversation-storage setting and obsolete guest promises of storage for up to 180 days.

## Implementation finding

SSF already requires fresh MFA for sensitive recording-key actions (`acr=mfa`, `auth_time` within 300 seconds). The ordinary-login decision does not explicitly remove these checks. The plan preserves them and includes acceptance for ordinary login, voluntary MFA, mandatory MFA and sensitive-action step-up separately.

## Actions

| Action | Owner | Due |
| --- | --- | --- |
| Deliver policy, retention inheritance, texts, permissions and live directory | Studio SSF plugin team | Not specified |
| Deliver optional/required realm MFA configuration and reconciliation | Studio Core/IAM team | Not specified |
| Validate producer responses against SSF consumers and test the rollout | SSF team with Studio team | Not specified |

Individual assignees and delivery dates are not specified. Work is coordinated through [SSF #612](https://github.com/smart-village-solutions/smart-speech-flow/issues/612) and [recording epic #611](https://github.com/smart-village-solutions/smart-speech-flow/issues/611); existing delivery work-package statuses are unchanged.

## Risks

- Studio and SSF must agree field names from the current consumers, rather than copying older issue prose.
- Optional ordinary MFA must not turn a password-only token into proof of MFA for sensitive actions.
- Default changes must not silently rewrite existing archive expiry dates.

## Sources

- [Implementation plan](../superpowers/plans/2026-11-02-studio-recording-settings.md).
- [Proposed contract requirements](../../openspec/changes/add-studio-recording-administration/specs/studio-runtime-integration/spec.md).
- [Existing key deployment runbook](../operations/runbooks/recording-keys-deployment.md).
