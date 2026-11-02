# Studio Recording Administration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking. Obtain the owning repository's OpenSpec proposal approval before changing runtime behavior.

**Goal:** Deliver Studio administration and internal APIs for SSF recording policy, retention, legal wording, permissions and optional organisation-wide login MFA.

**Architecture:** Studio's SSF plugin owns recording configuration, effective defaults and tenant overrides, legal content and recording-directory production. Studio Core/IAM owns users and Keycloak realm authentication policy. SSF consumes the effective contract and retains its recording authorization, evidence, encryption and retention enforcement.

**Tech Stack:** Studio TypeScript strict mode, Zod, PostgreSQL, React, Vitest, pnpm/Nx and Keycloak; SSF Python 3.12, Pydantic, pytest and the existing Studio mock.

**Spec:** [OpenSpec design](../../../openspec/changes/add-studio-recording-administration/design.md), [producer requirements](../../../openspec/changes/add-studio-recording-administration/specs/studio-runtime-integration/spec.md), [confirmed decisions](../../meeting-notes/2026-11-02-studio-recording-settings.md).

## Global Constraints

- Recording retention defaults to 30 days (720 hours).
- A tenant override takes precedence over the installation default.
- Explicit values are integers from 1 to 8760 hours; unlimited retention is unsupported.
- Tenant recording enablement is explicit and defaults false.
- Missing or invalid Studio recording policy leaves recording unavailable in SSF.
- `auditRetentionHours >= retentionHours`; timestamp service URLs use HTTPS.
- Ordinary-login MFA is optional by default, with voluntary enrollment; organisations may require it.
- Studio configures Keycloak; users enroll their factor through Keycloak.
- Preserve sensitive-action step-up: `acr=mfa`, `auth_time` within 300 seconds, existing clock-skew checks.
- No recording grant alone gives access to archive decryption keys.
- Root and tenant administration remain separate, server-authorized scopes.
- Do not alter existing archive expiry dates or enable recording through migration.
- Newly written documentation, issues and PRs are English. Tenant legal wording remains in its authored languages.
- Use synthetic fixture wording; keep credentials, real identities and private legal payloads out of git.

## Execution status

The user approved implementation on 2026-11-02. Policy/content, identity/directory and MFA slices are implemented and have passed independent review, including correction and re-review of status reconciliation. The whole-branch review and its scoped correction review are approved. Exact-head CI remains the final repository gate; two-tenant staging and production activation remain separate release operations.

| Candidate / check | Recorded evidence |
| --- | --- |
| Studio runtime candidate | `0b695f2c2`, branch `feature/ssf-recording-administration`, based on `7e0d71a8718754859b7c4efdc8e319d41a7170f4` |
| SSF consumer/fixture candidate | `c4069f77`, branch `codex/project-steward-studio-recording-plan-20261102` |
| Schema / wire contracts | Central IAM migration 0113; SSF schema migration 0007; runtime/directory contract 2.0 |
| SSF consumer regression | 221 passed across the seven Task 8 suites; ConsentScreen cleanup separately passed 24 tests |
| Studio plugin | Initial final unit gate: 234 passed, 13 database tests skipped; all 13 passed separately against PostgreSQL. Final editor/policy fix gate: 31 passed; plugin types and lint passed |
| Core/IAM review corrections | 246 registry regressions, 18 focused completion/status tests and 3 repository tests passed; 3 real PostgreSQL tests passed with 0113 down/up and exact schema comparison |
| Authentication acceptance | Keycloak 26.7.2, real browser and access tokens: 2 tests passed in 90.27 seconds, including optional SSO, voluntary enrollment, required existing/new users, fresh MFA timestamp, tenant isolation, lost-factor reset/re-enrollment, reversal and custom-flow conflict |
| Types / runtime | Affected Core/IAM/plugin/SDK/application types passed; server-runtime gate passed; correction gates rebuilt affected packages and passed auth-runtime runtime guard |
| Verification limits | Two existing baseline module-boundary lint errors were reproduced in unmodified mainline source. The full local PR gate exposed stale DTO/mock/catalog assertions, corrected by focused coverage checks (8, 12, 45 and 11 tests). The real seed runner then passed idempotency/counts and 17 recovery/baseline/mail tests. Individual green gates do not imply a green repository-wide gate. |

Local producer output was accepted by the actual SSF models. These tests do not replace deployed two-tenant staging, minimum-privilege provisioner preflight, tenant legal-content review or the archive/key/timestamp/backup operational checks below. No tenant is enabled by this implementation or its migrations.

Implementation decisions made within the approved scope:

| Decision | Reason / cost if wrong |
| --- | --- |
| Treat the implementation request as approval of the matching Studio proposal and cross-repository work | Delivers the requested producer behavior; a scope correction would require reverting the isolated branches, with production unaffected. |
| Group policy/editor/legacy cleanup and execute identity and MFA slices sequentially | Shared resolver/editor and IAM files require coordinated ownership; regrouping would change commit boundaries rather than product behavior. |
| Add managed `competenceLanguages` to IAM accounts, separate from UI language | No existing authoritative competence field exists; choosing a different source later requires data migration and projection updates. |
| Add generic tenant `iam.authenticationPolicy.manage` permission | Existing root provisioning rights do not authorize tenant-local security settings; a different authorization policy requires catalog/grant changes. |
| Preserve existing administrator permission exclusions through SDK and both host bootstrap paths | Otherwise all new recording permissions are automatically granted to tenant administrators; any alternative must retain that isolation invariant. |

## Evidence and scope

Evidence checked on 2026-11-02:

| Source | Finding | Planning consequence |
| --- | --- | --- |
| [SSF #612](https://github.com/smart-village-solutions/smart-speech-flow/issues/612), open | Contract, permissions and directory are tracked; Studio administration screens explicitly excluded from that issue | Keep contract acceptance linked; include administration as additional Studio delivery scope |
| [SSF #615](https://github.com/smart-village-solutions/smart-speech-flow/issues/615), closed | Recording and retirement of the old storage choice have consumer implementation | Reuse SSF flow; plan producer cleanup rather than rebuilding recording |
| [Studio PR #2011](https://github.com/smart-village-solutions/sva-studio/pull/2011), merged | Separate consent and release text administration exists | Extend existing legal editor; avoid a duplicate text subsystem |
| [Studio PR #2012](https://github.com/smart-village-solutions/sva-studio/pull/2012), merged | Distribution build isolation fixed after legal-text work | Base implementation on a revision including both changes |
| SSF `ac7ab1d6` | Recording policy parser, directory client and MFA step-up checks exist | Treat current consumers as the compatibility baseline |
| Studio local legal-text worktree `234eeff76` | Plugin paths below exist; recording permission allowlist still contains configuration permissions only | Recheck current main and extend the projection rather than create a second IAM source |
| Studio main `7e0d71a8718754859b7c4efdc8e319d41a7170f4`, checked through GitHub | Descriptor, merge, projection runtime, server factory and realm execution plan match the inspected source; repository validation-fixture bytes differ | Anchor structural decisions to main and implement on a clean checkout of its successor |

The older `/root/projects/sva-studio` checkout does not contain the same plugin baseline and contains unrelated uncommitted architecture work. Do not modify that work. The path `/root/projects/sva-studio-legal-texts` is a source-inspection reference, not a required execution destination. Start implementation in a clean Studio worktree based on current main.

The live project-steward report was refreshed. This plan does not reclassify work packages or resolve unrelated report conflicts. Relevant delivery alignment is WP-015 (tenant isolation), WP-021 (contracts) and WP-013 (legal content); individual owners and dates are not assigned here.

This is a coordinated handoff with three independently reviewable slices: policy/content (Tasks 1–3), identity/directory (Tasks 4–5), and authentication (Task 6). They converge for cleanup and acceptance (Tasks 7–8). No new quality-session runtime, archive UI, crypto algorithm, storage backend or translation engine is included.

## Ownership and order

| Order | Deliverable | Responsible team | Depends on | Why now |
| --- | --- | --- | --- | --- |
| 1 | Approved producer contract and executable examples | Studio plugin + SSF | Confirmed decisions | Prevent field-name and inheritance mismatches |
| 2 | Effective recording policy and administration | Studio plugin | Task 1 | Makes the 30-day default and tenant overrides usable |
| 3 | Recording IAM, languages and live directory | Studio IAM + plugin | Task 1 | Supplies authorization and recovery prerequisites |
| 4 | Optional/required ordinary MFA and step-up compatibility | Studio Core/IAM | Task 1 | Makes authentication policy operational |
| 5 | Legacy cleanup and two-tenant acceptance | Studio + SSF + operations | Tasks 2–6 | Establishes release readiness before tenant enablement |

## File and interface map

Paths in this table are relative to the **Studio** repository unless prefixed `SSF:`. New files are proposed; existing paths were inspected. Follow the owning repository's AGENTS instructions and recheck file locations after rebasing.

| Files | Responsibility |
| --- | --- |
| `packages/plugin-ssf/src/content-v2-recording.ts` (new) | Recording schema and retention resolution |
| `packages/plugin-ssf/src/content-v2-contracts.ts`, `content-v2-overrides.ts`, `content-v2.ts` | Optional recording block, effective tenant merge and revision generation |
| `packages/plugin-ssf/src/content-v2-repository.ts`, `server/content-v2-admin.ts` | Validated storage in existing template/override JSON and authorized reads/writes |
| `packages/plugin-ssf/src/admin.content-v2-recording-fields.tsx` (new), `admin.content-v2-runtime-fields.tsx`, `plugin.translations.ts` | Recording controls, inherited values and localized labels |
| `packages/plugin-ssf/src/admin.content-v2-legal-fields.tsx`, `content-v2-contracts.ts` | Existing separate legal consent/release editor and validation |
| `packages/plugin-ssf/src/authorization-projection.ts`, `keycloak-authorization-projection-contract.ts`, `keycloak-authorization-projection-target.ts` | Recording permission IDs, effective grants, language claim mapper |
| `packages/plugin-ssf/src/descriptor.ts`, `constants.ts` | Register recording permissions, deliberately scoped role baseline and directory service endpoint |
| `packages/plugin-sdk/src/plugin-registry-types.ts`, `plugin-iam-definitions.ts`, `plugin-registry-content.ts`; `apps/sva-studio-react/src/lib/plugins.ts`; `packages/studio-module-iam/src/ssf-module-iam-contract.ts` | Preserve the existing Core administrator-exclusion semantics through plugin metadata and both host bootstrap paths |
| `packages/iam-admin/src/user-detail-query.ts`, `user-detail-query.types.ts` | Extend existing authorized user attributes for reviewer language administration |
| `packages/auth-runtime/src/iam-authorization/tenant-permission-projection.ts`, `permission-store.queries.ts`, `server.ts` | Extend the current authoritative IAM read with directory subjects and export the host-owned reader |
| `packages/plugin-ssf/src/recording-directory.ts`, `server/recording-directory.ts` (new), `server/index.ts` | Directory model, capability contract and handler registration in the exported `./server` entry point |
| `apps/sva-studio-react/src/lib/plugin-server-runtime.server.ts`, `ssf-authorization-projection-runtime.server.ts` | Compose host IAM reads into SSF server capabilities and include reviewer languages in the existing projection source |
| `packages/instance-registry/src/keycloak-mfa-policy.ts` (new), `service-keycloak-reconcile-helpers.ts`, `service-keycloak-execution-plan.ts`, `service-keycloak-run-steps.ts` | Generic realm MFA desired state, reconciliation and verification |
| `docs/api/ssf-runtime-configuration-v2.schema.json`, `ssf-runtime-configuration-v2.example.json`, `ssf-recording-directory-v2.schema.json` (new), `ssf-recording-directory-v2.example.json` (new) | Producer contract and synthetic examples |
| `SSF: services/api_gateway/studio_v2.py`, `studio_recording_directory_client.py`, `recording/permissions.py` | Existing consumer compatibility references; change only for a demonstrated incompatibility |
| `SSF: services/studio_mock/fixtures/runtime-tenant-kassel.json`, `runtime-tenant-marburg.json`, `runtime-tenant-fulda.json`, `recording-directory.json`, `services/studio_mock/contract_fixtures.py` | Updated defaults and deliberate compatibility/failure scenarios |

No database migration is necessary merely to add optional fields to existing runtime JSON. If the MFA owner has no generic tenant authentication-policy storage, add it in Core/IAM's existing migration sequence after checking its current numbering; never put generic realm policy in the SSF content blob. Task 6 requires a reviewed storage/API design before that schema change.

## Studio integration boundaries

- Studio currently identifies the tenant boundary as `instanceId` in the plugin execution context and as `instance_id` in `ssf.tenant_settings`. Map that canonical value to SSF's `tenantId`; an installation default is the deployment's singleton `ssf.server_settings`, not another tenant or a new instance selector. Organisation-level records within a tenant do not create additional SSF tenants.
- `mergeSsfContentV2` reserves `enabled` for content-node suppression and strips that property from merged objects. Do not pass the policy subtree through that generic merge. `effectiveSsfRuntimeFieldsV2` must extract `recording`, merge the remaining content as before, resolve recording through the dedicated policy function, then validate and revise the combined result. Tenant `recording.enabled` is never inherited from the installation template.
- Register a directory handler in both `descriptor.ts` and `server/index.ts`. `src/server.ts` currently provides lifecycle job handlers; the package's `./server` export resolves to `dist/server/index.js`. Adding an ordinary request handler only to the lifecycle file does not expose the endpoint.
- The SSF plugin must not import IAM repositories or connect to IAM tables. Supply its source through the existing host server-factory capability pattern, already used for `waste-management`. Extend that existing composition point for SSF rather than building another plugin loader or a general capability framework.
- `readTenantPermissionProjectionSubjects` currently supplies only Keycloak subject, role names and permission IDs. Display names and reviewer languages need an explicit authoritative read; they cannot be reconstructed from the projection cache, an arbitrary staff token or an assumed field on the current return type.

## Task 1: Freeze the producer contract

**Owner:** Studio plugin + SSF teams. **Consumes:** confirmed decisions and current SSF models. **Produces:** approved Studio OpenSpec delta and schema/examples accepted by SSF.

**Files:** Studio API files above and its matching OpenSpec change; SSF `tests/test_studio_recording_policy.py`, `tests/test_studio_recording_directory_client.py` as acceptance references.

- [x] Bring the proposed producer requirements into Studio OpenSpec and obtain review before runtime implementation. Include Core/IAM ownership and administration UI, which #612 currently excludes.
- [x] Document these exact policy fields and values:

| Field | Contract |
| --- | --- |
| `enabled` | boolean, explicit tenant enablement, initially false |
| `legalBasis` | `consent` or `statutory` |
| `signature`, `idCheck` | `off`, `optional`, `required` |
| `retentionHours` | effective integer 1..8760; fallback 720 |
| `verificationRequired` | boolean |
| `recoveryMode` | `standard` or `enhanced` |
| `timestampAuthorityUrl` | HTTPS URL |
| `auditRetentionHours` | integer at least `retentionHours` |
| `texts` | optional array of `{locale, consentHtml, resumePromptHtml}` |

- [x] Keep the recovery threshold `k` in the existing SSF key ceremony; do not add an unconsumed policy field. Record mode/ceremony compatibility in acceptance.
- [x] Specify the directory envelope as `{contractVersion: '2.0', tenantId, directoryRevision, users}`; each user has `{sub, displayName, permissions, languages}`. Revision is `sha256:` plus 64 lowercase hexadecimal characters. Reject duplicate subjects and malformed language tags.
- [x] Document the existing service bearer identity, `X-Studio-Tenant-Id`, correlation header and required runtime-read permission. Match directory errors to the SSF client: 400 malformed request, 401 authentication invalid, 403 forbidden, 404 tenant missing, 409 suspended/inactive/not-ready, 503 directory unavailable.
- [x] Feed the synthetic Studio examples through `parse_runtime_configuration_v2` and `RecordingDirectory.model_validate`; assert 720-hour policy and expected reviewer/custodian entries. Observe failure before implementing producer support, then commit contract and tests together after acceptance.

## Task 2: Implement retention and effective policy

**Owner:** Studio plugin team. **Depends on:** Task 1. **Files:** recording module, contracts, overrides, resolver and repository from the map; new `packages/plugin-ssf/tests/content-v2-recording.test.ts`; existing content/database tests.

**Interface:** new exported `resolveRecordingRetentionHours(installationHours?: number | null, tenantHours?: number | null): number`. Null or absent tenant value means inherit. Invalid explicit values are rejected, never silently replaced.

- [x] Write failing Vitest cases using this contract:

```ts
expect(resolveRecordingRetentionHours()).toBe(720);
expect(resolveRecordingRetentionHours(1440)).toBe(1440);
expect(resolveRecordingRetentionHours(1440, 240)).toBe(240);
expect(resolveRecordingRetentionHours(1440, null)).toBe(1440);
expect(resolveRecordingRetentionHours(8760)).toBe(8760);
for (const invalid of [0, -1, 8761, 1.5]) {
  expect(() => resolveRecordingRetentionHours(invalid)).toThrow();
  expect(() => resolveRecordingRetentionHours(720, invalid)).toThrow();
}
```

- [x] Run `pnpm nx run plugin-ssf:test:unit --testFiles=tests/content-v2-recording.test.ts` and confirm the new cases fail for the missing implementation.
- [x] Implement the resolver and schema using the following behavior, with `.js` runtime imports:

```ts
const hours = z.number().int().min(1).max(8760);
export const resolveRecordingRetentionHours = (
  installationHours?: number | null,
  tenantHours?: number | null,
): number => {
  if (installationHours != null) hours.parse(installationHours);
  if (tenantHours != null) hours.parse(tenantHours);
  return tenantHours ?? installationHours ?? 720;
};
```

- [x] Add proposed `resolveSsfRecordingPolicy(installation: unknown, tenant: unknown): RecordingPolicy | undefined` in `content-v2-recording.ts`; `RecordingPolicy` is the inferred type of its new complete output schema. Validate sparse administrative inputs separately from complete enabled output. If both inputs are absent return `undefined`; if configured but no tenant enablement is true, resolve a disabled policy or omit an incomplete disabled draft. Reject publishing an incomplete enabled policy. Resolve retention with the function above; resolve other configurable policy fields from explicit tenant value then installation value. Set `enabled` solely from the tenant's explicit boolean, default false.
- [x] In `effectiveSsfRuntimeFieldsV2`, validate/extract each input's `recording` subtree before calling the existing content merge, omit that subtree from both content inputs, and attach the separately resolved policy afterward. Preserve current content-array suppression behavior. Missing, null and false must not be collapsed by truthiness: deleting/resetting the tenant retention override inherits, `enabled: false` disables, and a null whole tenant policy is rejected in favor of explicit reset or disable operations.
- [x] Add regression cases: tenant `enabled: true` survives serialization; false survives and disables; template `enabled: true` with no explicit tenant enable remains off; absent template recording plus a complete tenant policy is accepted; content entries with `enabled: false` are still suppressed. Test the actual editor diff/reset round trip through `diffSsfContentV2`, persistence and runtime serialization, not just the retention helper.
- [x] Resolve the effective block before canonical revision generation. An installation default change affects inheriting tenants' revisions; overridden tenants keep their effective duration. Add no default enablement through normalization or migration.
- [x] Add repository integration cases: two tenants with different overrides, override removal, invalid write rollback, no cross-tenant writes, preservation of existing explicit recording values. Do not read legacy storage retention into the new block.
- [x] Test audit retention conflicts on both tenant writes and installation-default changes. Reject a change that would publish an invalid inheriting policy; report affected tenants so the administrator can adjust audit retention first.
- [x] Rerun the focused test and `pnpm nx run plugin-ssf:test:integration`; run the plugin type target. Commit as `feat(ssf): resolve recording retention defaults and overrides` only after the affected checks pass.

## Task 3: Expose recording and legal administration

**Owner:** Studio plugin team. **Depends on:** Task 2. **Files:** recording UI, runtime fields, translations, existing legal editor, admin handler and repository. Tests: new `tests/admin.content-v2-recording.test.tsx`, existing `tests/content-v2-admin.test.ts`, `tests/admin.content-v2-page.test.tsx`, `tests/content-v2-legal.test.ts` under the plugin.

**Consumes:** effective policy and existing legal-text schema. **Produces:** authorized installation defaults, tenant overrides and versioned consent/release edits through existing admin APIs.

- [x] Write UI/API tests before controls: root can change installation retention; a tenant admin can change only its own tenant; read-only users cannot write; tenant admin cannot change installation defaults. An inherited value displays its source, and reset-to-inherit removes the override.
- [x] Add all policy controls from Task 1 and an effective-retention preview. Keep stored/API hours; if displaying days, convert explicitly and never round away an existing hourly value. Show a validation error rather than truncating out-of-range values.
- [x] Integrate with the existing `legalTexts` editor for consent, guest release, employee release and status text. Retain separate quality-mode wording without adding a quality runtime. Add recording resume wording through `recording.texts` where used by the consumer.
- [x] Test missing organization texts, exact locale and language matches, source-language fallback indication, sanitizer behavior and revision changes after edits. Preserve SSF stale-text digest rejection. Do not invent automatic legal translations.
- [x] Test that supplying texts or changing default retention never enables recording. Require an explicit tenant enable action after a complete valid policy is present.
- [x] Run the focused UI, legal and admin tests, plugin type/lint targets and database integration checks for persisted overrides. Commit as `feat(ssf): administer recording settings and inherited retention`.

## Task 4: Deliver permissions and reviewer languages

**Owner:** Studio IAM + plugin teams. **Depends on:** Task 1. **Files:** `packages/plugin-ssf/src/descriptor.ts`, existing authorization-projection and Keycloak target files, `apps/sva-studio-react/src/lib/ssf-authorization-projection-runtime.server.ts`, authorized user attributes and existing tenant user editor; tests in `packages/plugin-ssf/tests/authorization-projection.test.ts`, `plugin.test.ts`, `keycloak-authorization-projection-target.test.ts` and the IAM user tests.

**Consumes:** effective IAM roles/groups/permissions and tenant-scoped user attributes. **Produces:** `ssf_permissions` and `ssf_languages` claims for the intended SSF staff client, plus a shared authoritative input for Task 5.

- [x] Write failing projection tests for these exact IDs: `ssf.recording.request`, `ssf.recording.review`, `ssf.recording.review.sworn`, `ssf.recording.supervise`, `ssf.recording.recovery.custodian`.
- [x] Register the five permission definitions in `descriptor.ts` and the module's `moduleIam.permissionIds`, then extend the projection allowlist. The descriptor currently derives the `system_admin` role's grants from all plugin permissions; replace that derivation with the explicit existing configuration-management grants before appending recording permissions. Assert that reconciliation does not grant request/review/sworn/supervision/custodian permissions to existing or new tenant admins automatically. Verify explicit role/group grants and revocation of the last effective grant.
- [x] Preserve `systemAdminPermissionExclusions` through the SDK contract, normalizer, generated registry and host `createStudioModuleIamContracts` mapping, and add the same recording exclusions to the SSF distribution's module contract. Execution inspection found that Core's bootstrap resolver otherwise derives administrator grants from all module permission IDs even when the descriptor lists narrower `systemRoles`. Test the real descriptor-to-host-to-bootstrap path and validate that exclusions reference declared module permissions; keep other modules' existing behavior unchanged.
- [x] Add reviewer language editing through the tenant's existing authorized user management. Validate at most 40 supported language tags using the consumer-compatible form. Store and project the normalized list as `ssf_languages`; use the sworn-review permission for sworn status, with no parallel boolean authority.
- [x] Extend the existing Keycloak mapper and reconciler, preserving client/audience scoping. Test changes for one realm cannot modify another and that newly issued tokens reflect the current permissions and language list.
- [x] Extend the source DTO, normalized projection comparison and Keycloak read-back to carry `languages`; currently the host mapping drops every field except subject, roles and permissions. Test that a language-only edit triggers reconciliation and appears in a newly issued `ssf_languages` claim. Keep the contract revision semantics distinct from a per-user data change.
- [x] Document existing token-lifetime behavior: a live directory revocation does not itself revoke already-issued access tokens. Do not claim instant actor-token revocation without separate implemented evidence.
- [x] Run focused plugin/IAM tests, affected type and server-runtime checks; commit as `feat(iam): project recording grants and reviewer languages`.

## Task 5: Supply the live recording directory

**Owner:** Studio plugin + IAM teams. **Depends on:** Task 4. **Files:** new directory model and server handler; `packages/plugin-ssf/src/constants.ts`, `descriptor.ts`, `server/index.ts`; host/auth-runtime paths from the map; new `packages/plugin-ssf/tests/recording-directory.test.ts`, `tests/recording-directory-server.test.ts`; existing host `plugin-server-runtime.server.test.ts`; update API schema/examples.

**Consumes:** current tenant-bound effective IAM grants and reviewer languages. **Produces:** `GET /internal/plugins/ssf/v2/recording-directory` with the Task 1 envelope; no caller-provided tenant identity bypasses host authorization.

**Proposed source interface:** add a generic host-owned `readTenantPermissionDirectorySubjects` export next to the current projection reader. Its inputs and returned fields are explicit; its implementation owns IAM profile access/decryption and uses the same effective-grant semantics as authorization.

```ts
type PermissionDirectorySubject = Readonly<{
  keycloakSubject: string;
  displayName: string;
  permissionIds: readonly string[];
  languages: readonly string[];
}>;
type ReadPermissionDirectorySubjects = (input: Readonly<{
  instanceId: string;
  permissionIds: readonly string[];
}>) => Promise<readonly PermissionDirectorySubject[]>;
type SsfPluginServerCapabilities = Readonly<{
  readPermissionDirectorySubjects: ReadPermissionDirectorySubjects;
}>;
```

The plugin owns the structural capability type, not an import of the Core/IAM implementation. Extend `createPluginServerHandlers` in `server/index.ts` to accept optional `SsfPluginServerCapabilities` without breaking the existing no-argument contract; missing capabilities bind an unavailable directory handler. At the host's existing capability-composition branch in `plugin-server-runtime.server.ts`, supply this reader for SSF, analogous to its current waste-management composition. Keep workspace and installed-package entry points equivalent; pass the reader on the server only.

- [x] Test an authenticated service read with tenant A's reviewer and custodians, and a separate tenant B user that must never appear.
- [x] Test no token, wrong audience/permission, mismatched tenant context, suspended tenant, inactive plugin and unavailable IAM authority with the documented error envelopes.
- [x] Extend the authoritative IAM query in a tenant-scoped transaction to return active subjects, their effective grants, display names and managed competence languages. Reuse existing permission calculation and profile decoding; do not interpret a user's UI language as competence. Test time-bounded assignments, group grants and inactive accounts. Expose the generic reader through auth-runtime's server entry point and inject it as described above; no plugin query may read `iam.*` tables.
- [x] Add constants for path `/internal/plugins/ssf/v2/recording-directory` and proposed handler ID `ssf.recording-directory-v2`. Declare it in `descriptor.ts` as GET with action `ssf.runtime-configuration.read`, service `ssf-runtime` and the existing tenant-header binding. Bind the exact same ID in `server/index.ts` and check the generated registry. No new browser route, navigation item or service-token permission is needed for this read.
- [x] In the handler, require `context.scope === 'service'` and use only `context.tenant.instanceId` for the IAM call. Supply the five known permission IDs from the plugin constants and map host `keycloakSubject` to response `sub`; map the canonical context value to `tenantId`. Enumerate all matching users; do not silently truncate a paginated result. Return only active eligible users and only recording permissions, using the existing SSF error envelope.
- [x] Build deterministic `directoryRevision` from the normalized directory content. Test that a change in permissions, languages or membership changes the revision and that a repeated unchanged read is stable.
- [x] Test grant removal followed immediately by another read, without restart or token refresh. Resolve grants live; do not cache a successful directory or turn an authority failure into an empty list.
- [x] Add host-loader tests for capability injection, missing-source unavailability, workspace/installed server entry parity and tenant binding. Assert that `server.ts` lifecycle job handlers still load and a directory request does not run a reconcile job.
- [x] Pass the JSON response to SSF's `RecordingDirectory.model_validate`; run Studio handler tests and SSF `tests/test_studio_recording_directory_client.py`. Commit as `feat(ssf): serve the live tenant recording directory`.

## Task 6: Configure optional and required MFA in Keycloak

**Owner:** Studio Core/IAM team. **Depends on:** Task 1; independent of recording-policy storage. **Files:** generic realm MFA module, provisioning/reconciliation files from the map, existing tenant security UI/API; new `packages/instance-registry/src/keycloak-mfa-policy.test.ts`; existing realm execution tests and guide `docs/guides/keycloak-tenant-realm-bootstrap.md`.

**Interface:** tenant ordinary-login policy `optional | required`, desired/applied status and an idempotent reconciliation result. This is a proposed Core/IAM extension, not an already available Studio setting or a new SSF runtime field. Inspection of the current realm execution plan found no implemented optional/required MFA setting. Use the tenant realm identified by the existing instance registry; do not treat tenant-local organisation records as separate realms.

**Required Core/IAM contract:** extend the existing tenant/instance management DTO and its authorized mutation path with this proposed representation, storing desired state in Core/IAM and reporting actual verified state separately:

```ts
type LoginMfaMode = 'optional' | 'required';
type LoginMfaPolicyState = Readonly<{
  desiredMode: LoginMfaMode;
  appliedMode: LoginMfaMode | null;
  status: 'pending' | 'applied' | 'failed';
}>;
```

Absent desired configuration resolves to optional; absent verification is `appliedMode: null`, never proof of an applied setting. A successful write persists desired state and schedules the existing realm provisioning/reconciliation job, returning pending state. Only a verified read-back sets `appliedMode` and `status: applied`; a failed run keeps the last verified applied mode and reports failed. Use existing run IDs and diagnostic errors rather than duplicating another job state machine.

The implementation must extend the existing tenant-authorized management path to let the organisation's tenant administrator select its policy; root provisioning authority must not implicitly confer tenant-local administration. Define the generic IAM authorization requirement in the owning proposal and test both scopes server-side. Reuse the existing settings page/API and audit mechanism, adding no SSF-specific Core permission or separate security service.

- [x] Add failing cases for default optional, organisation-required MFA, tenant-scoped writes, repeated reconciliation and Keycloak failure. Require a failed reconciliation to preserve a visible pending/error state rather than falsely claim that mandatory MFA is applied.
- [x] Confirm the existing Core/IAM persistence owner and add the desired policy field there, with a migration only if required. Update `docs/development/studio-db-schema-final.sql` and `studio-db-schema.md` for any schema change. Extend authorized read/write DTOs, validation, audit event data, existing tenant management UI and DE/EN translation resources together. Never store this state in plugin runtime content or use raw Keycloak access from the UI.
- [x] Review the existing realm and client flow bindings before changing them. Build the desired Keycloak configuration using OTP for this first slice; no new factor engine or external authenticator is needed.
- [x] Extend the existing realm execution plan, reconciler and run steps with MFA application and read-back. Compare owned flow bindings, required actions and ACR mapping; preserve unrelated realm configuration and make retries idempotent. Test a pre-existing custom flow: update only declared managed bindings or return a visible conflict, rather than overwrite administrator-managed authentication.
- [x] Provision voluntary OTP enrollment and conditional ordinary-login challenges for optional mode. In required mode enforce enrollment and a factor challenge for both existing and new staff. Returning to optional does not delete enrolled factors.
- [x] Preserve the SSF step-up mapping `pwd -> 1`, `mfa -> 2`, accurate `acr` and `auth_time`. A requested fresh step-up must actually challenge the user; merely reusing an old SSO cookie must not produce fresh MFA evidence.
- [x] Run the following real-realm acceptance matrix for both Studio and SSF clients, including existing SSO sessions:

| Tenant policy | User state/action | Expected result |
| --- | --- | --- |
| optional | no factor, ordinary login | password login succeeds; token does not assert MFA |
| optional | voluntarily enrolled OTP, ordinary login | OTP is requested |
| required | no factor, ordinary login | enrollment and second factor are required |
| required | enrolled OTP, ordinary login | OTP is required |
| either | sensitive recording action with password-only or stale token | SSF requests fresh step-up |
| either | freshly completed MFA step-up | `acr=mfa` and recent `auth_time` satisfy existing checks |
| required -> optional | existing enrolled account | factor remains enrolled and voluntary-MFA login continues |
| either | reconcile same desired state twice | no duplicate flow or mapper; same applied configuration |

- [x] Verify account factor replacement/recovery through the existing Keycloak process, tenant realm isolation and provisioning retry behavior. Document administrative recovery without disabling SSF verification.
- [x] Run focused Core/IAM tests and affected type/runtime checks, then SSF `tests/test_recording_permissions.py`; commit as `feat(iam): manage tenant login MFA policy in Keycloak`.

Keycloak reference: [authentication flows and OTP administration](https://www.keycloak.org/docs/26.7.0/server_admin/index.html). Verify against the deployed Keycloak version when executing; test actual token claims instead of relying on console configuration labels.

## Task 7: Retire legacy controls and guest promises

**Owner:** Studio plugin team; SSF owns mock consistency. **Depends on:** Tasks 2–3. **Files:** runtime fields/overrides/schema and API examples; SSF mock files from the map. Tests: existing Studio content/UI suites; SSF mock and v2 contract suites.

- [x] Add tests that the old “store conversation?” setting is absent from active administration and cannot be reactivated by a tenant override or imported template.
- [x] Remove its editing controls. Normalize legacy compatibility output to `conversationContentStorage: {mode: 'disabled', retentionHours: null}` and null `storageQuestionHtml` while current producer schemas require those fields. Do not remove them from a versioned contract without a coordinated compatibility change.
- [x] Search active templates, examples, translations and guest explanation/consent content for `180`, `4320`, `storageQuestionHtml` and translated storage promises. Distinguish obsolete promises from deliberate historical/negative-test fixtures. Replace active wording with reviewed policy-correct wording; do not promise universal 30-day storage for unrecorded conversations.
- [x] Make the ordinary synthetic recording example use 720 hours and keep recording-disabled/missing-policy cases. Keep explicit non-default durations only in named override/boundary tests. Preserve any legacy `ask` input fixture solely as a clearly named ignored-input regression test.
- [x] Test inherited and tenant-overridden numeric durations and bundled/example recording wording.
- [ ] Obtain a human content review for free-form consent wording before publication: correct inconsistent duration promises rather than silently rewriting organisation-authored legal text. Automated tests cannot establish legal-text consistency for arbitrary authored prose.
- [x] Run focused Studio content/UI tests and SSF mock/contract tests; commit as `fix(ssf): retire legacy storage settings and guest promises`.

## Task 8: Integrate, accept and roll out

**Owner:** Studio + SSF teams with operations. **Depends on:** Tasks 2–7. **Files:** existing API/architecture docs and the SSF recording deployment runbooks; update task checklists only after corresponding work is verified.

- [x] Record Studio and SSF candidate revisions, schema revisions, test commands and results; validate locally generated Studio responses with the actual SSF models.
- [ ] Recheck the current SSF parser against the real deployed Studio staging response with synthetic tenant data.
- [x] Run the focused SSF suites from the SSF repository:

```bash
python -m pytest -q tests/test_studio_recording_policy.py tests/test_studio_recording_directory_client.py tests/test_recording_permissions.py tests/test_studio_recording_legal_texts.py tests/test_studio_mock_client_contract.py tests/test_studio_mock_fixtures.py tests/test_studio_v2_contract.py
openspec validate add-studio-recording-administration --strict
```

- [x] Run the Studio plugin gates from its repository, plus the actually affected Core/IAM targets:

```bash
pnpm nx run plugin-ssf:test:unit
pnpm nx run plugin-ssf:test:types
pnpm nx run plugin-ssf:lint
pnpm nx run plugin-ssf:test:integration
pnpm check:server-runtime
pnpm nx show projects --affected --withTarget=test:unit --base=origin/main
```

Use Studio's measured affected-scope rules before broader runs and its PR/release gates. These commands are execution instructions; they are not claims that future implementation tests have already passed.

- [ ] Perform two-tenant acceptance: A inherits 720 hours; B overrides to 240; change installation default to 1440; A follows and B stays 240; resetting B makes it inherit. Invalid writes leave the prior policy intact. Policy/text-only updates never enable recording automatically.
- [ ] Test missing, disabled, invalid and unavailable recording policies: recording remains unavailable while ordinary conversations follow their existing availability rules. Verify live permission revocation, reviewer language/sworn display, text-change rejection and the Task 6 login matrix.
- [ ] Verify archive storage, signing/blob secrets, enrolled personal keys, active tenant recovery key, compatible threshold, working timestamp service, retention worker and backups before any tenant enablement. Reuse the existing key, recording cutover and retention deployment runbooks.
- [x] Update Studio API documentation and arc42 sections 04, 05, 06 and 08; document the IAM change in an ADR referenced from section 09. Include the host capability, tenant/installation identifier mapping, desired/applied MFA status and rollback procedure. Cross-link SSF #612 without marking it complete based solely on documentation.
- [x] Review and commit independently testable changes.
- [ ] Promote through Studio's canonical `Build -> Dev -> Staging -> Production` process with the same image digest and existing SSF deployment procedures. Do not introduce direct production realm edits as a competing rollout path.
- [ ] Enable one prepared tenant explicitly and record smoke-test evidence. Rollback means disabling new recording or reverting the reviewed producer candidate while preserving archives, keys and existing expiry dates. Release approval follows the owning repositories' existing process.

## Completion criteria

The Studio handoff is delivered only when an administrator can manage every requested setting, the tenant receives its effective retention and legal content, SSF can read live eligible users with the exact recording permissions/languages, optional and required MFA work in Keycloak, and legacy storage choices/promises are absent. Completion additionally requires passing cross-repository contract tests and recorded two-tenant staging acceptance. A completed plan or merged contract document alone does not establish these outcomes.
