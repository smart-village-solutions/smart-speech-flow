## 1. Contract and administration

- [ ] 1.1 Carry the reviewed producer obligations into the Studio OpenSpec change and update the API schema/examples.
- [ ] 1.2 Implement 720-hour installation retention default, tenant override and effective-policy resolution with 1..8760 validation.
- [ ] 1.3 Add recording administration with explicit tenant enablement, independent legal texts and configuration revisions.

## 2. Identity and directory

- [ ] 2.1 Add recording permission IDs and reviewer languages to IAM administration and Keycloak projection.
- [ ] 2.2 Implement the live tenant recording-directory endpoint and matching authorization/error contract.

## 3. MFA and cleanup

- [ ] 3.1 Implement optional/required ordinary-login MFA through Core/IAM realm provisioning and reconciliation.
- [ ] 3.2 Verify voluntary MFA, required enrollment and sensitive-action step-up against a real Keycloak realm.
- [ ] 3.3 Remove legacy storage editing and obsolete 180-day guest promises; preserve necessary disabled compatibility fields.

## 4. Integration and release

- [ ] 4.1 Run Studio unit, type, database and runtime checks and the focused SSF consumer suites.
- [ ] 4.2 Complete two-tenant staging acceptance, retention inheritance and permission-revocation evidence.
- [ ] 4.3 Follow existing release procedures and enable recording only after operational prerequisites are confirmed.

Execution detail and acceptance matrices: [implementation plan](../../../docs/superpowers/plans/2026-11-02-studio-recording-settings.md).
