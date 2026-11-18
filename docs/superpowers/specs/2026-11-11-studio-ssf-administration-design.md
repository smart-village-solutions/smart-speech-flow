# SSF Studio administration: navigation and page design

## Status and ownership

Design for review, dated 2026-11-11. The user requested this specification
after agreeing the direction below. This document does not authorize runtime
implementation or claim that the proposed UI is available in production.

The implementation belongs primarily to the Studio repository. This SSF-side
document records the agreed cross-repository design. Before implementation,
Studio must carry the owning OpenSpec proposal and obtain its approval. The
existing recording-administration change is context, not approval for this
navigation and editor restructuring.

## Objective and decisions

Make existing SSF administration understandable to an organisation administrator
without adding business capabilities.

- Use the same pages and actions for initial setup and recurring administration.
- Keep Studio's Applications and System sidebar sections.
- Use the existing application branding: Smart Speech Flow or KasselDIALOG.
- Remove the Data management section from the SSF presentation only when it has
  no required entries; preserve unrelated modules and their navigation.
- Separate installation/root administration from tenant administration.
- Reorganise existing fields; reuse Studio UI components and existing authority.
- Remove legacy administration rather than retaining a compatibility editor.
- Give multilingual editors one consistent language-selection pattern.
- Keep one editing location for each field in each scope.

There is no setup wizard, separate onboarding checklist, publication workflow,
new preview, translation service, readiness monitor, reporting UI, archive UI,
or key-management UI in this change. Overview pages only present existing
configuration and links. Their summaries are a presentation change, not a new
source of operational status.

## Evidence and limitations

The inspected Studio source is the local `studio-recording` worktree at
`26592bc4f`. It is an inspection baseline, not evidence of deployed state.
Recheck its successor before implementation.

Relevant Studio paths, relative to that repository:

| Source | Existing responsibility |
| --- | --- |
| `packages/plugin-ssf/src/admin.tenant-page.tsx`, `admin.system-page.tsx` | Current/legacy page tabs and access composition |
| `packages/plugin-ssf/src/admin.content-v2-tenant-page.tsx`, `admin.content-v2-page.tsx` | Loading, editing, validating and saving content |
| `packages/plugin-ssf/src/admin.content-v2-runtime-fields.tsx` | Staff, guest-language and recording fields |
| `packages/plugin-ssf/src/admin.content-v2-fields.tsx` | Branding, installation content and feedback editors |
| `packages/plugin-ssf/src/admin.content-v2-legal-fields.tsx` | Legal source locale, version and localisations |
| `packages/plugin-ssf/src/content-v2-admin-contracts.ts`, `admin-api.ts` | Existing aggregate read/write contracts |
| `packages/plugin-ssf/src/content-v2-overrides.ts` | Effective values and tenant override comparison |
| `packages/plugin-ssf/src/descriptor.ts` | Scope-bound routes, permissions and plugin navigation |
| `apps/sva-studio-react/src/components/sidebar-primary-items.tsx` | Plugin navigation composition and branding |
| `packages/studio-ui-react/src/studio-page-templates.tsx` | Existing overview/detail templates and form actions |

Related SSF documents:

- [Control-plane boundaries](../../architecture/sva-studio-control-plane.md).
- [Recording administration plan](../plans/2026-11-02-studio-recording-settings.md).
- [Recording producer obligations](../../../openspec/changes/add-studio-recording-administration/specs/studio-runtime-integration/spec.md).
- [Legal wording consumer behaviour](../../guides/studio-recording-legal-texts.md).

## Navigation and scope

Tenant sidebar, with translated labels:

```text
Overview
Applications
  Smart Speech Flow / KasselDIALOG
    Overview
    Appearance and content
    Languages
    Recordings
    Feedback
System
  Existing authorised tenant administration entries
```

Root sidebar:

```text
Overview
Applications
  Smart Speech Flow / KasselDIALOG
    Installation overview
    Default configuration
    Default content
System
  Tenants and existing authorised root administration entries
```

The application label comes from existing branding, not a new editable name.
Preserve the Studio overview and its existing functions. The SSF overview is
application-specific; this change does not merge or replace the Studio homepage.

Users, roles/groups and authentication settings remain in their existing Studio
locations and retain existing permissions. Link to them where useful and
authorised; do not create duplicate SSF editors or assume they all already have
standalone routes named exactly as this conceptual grouping.

Root permissions do not confer tenant rights. Tenant configuration rights do
not confer recording, reviewer or recovery-custodian rights. The active host
context supplies the tenant; no additional SSF tenant selector is introduced.

Nested application navigation is the target presentation. Verify SDK and shell
support before selecting route IDs. If insufficient, extend the generic plugin
navigation contract and shell together in the Studio proposal; do not hardcode
SSF children into the shell. Every page must have an addressable route, active
navigation indication and the existing server-side access checks.

## Shared page layout

Reuse `StudioOverviewPageTemplate` or `StudioDetailPageTemplate`, `StudioSection`,
`StudioField`, the existing rich-text editor, tabs, buttons, loading/error states,
form summaries and action bars from `studio-ui-react`.

Each editable page has a title, short purpose, named sections, applicable
language selection and its own Save / Discard changes actions. Preserve
read-only access for users who can read but cannot manage configuration.
Retain existing validation limits and allowed values. Navigation names must
describe user tasks; wire-contract names such as V1, V2 and runtimeTemplate
are not regular UI labels.

Use tabs for the groups below, and the existing collapsible sections for long
question/text groups. Language selection uses one consistently labelled select
per multilingual editor rather than nested language-tab strips. Use existing
spacing, typography, focus states and error styling. Do not encode state only
by colour.

## Tenant pages and field ownership

The paths below refer to the effective current runtime content model. Root
template editing uses the same paths inside `runtimeTemplate`.

### Overview

Read-only sections link to the four editing pages. Show existing branding,
staff locale, configured guest locales, recording enablement/retention and
existing feedback forms by audience. Derive these from the same saved values
used by the editors. Do not copy configuration into a separate overview store.

Recording enablement means configured enablement, not verified archive/key or
runtime availability. Missing configuration is labelled not configured; a read
failure is an error with retry, not an empty or healthy configuration. Do not
add readiness badges, missing-translation scores or administrative approvals.

### Appearance and content

| Tab | Fields owned here |
| --- | --- |
| Appearance | `branding.logo`, `branding.icon`: URL and alternative text |
| Staff | `staff.dashboard.headline`, `explanationHtml`, `callToAction`; `staff.dashboard.load.headline`, `green`, `yellow`, `red`; `staff.newConversation.headline`, `descriptionHtml` |
| Guests | `guestLanguages[locale].guest.explanationHtml`, selected by existing guest locale |

Do not duplicate staff locale, guest activation, legal wording or feedback
editing here. Tenant users do not gain installation legal-link or public
start/login editing rights.

### Languages

| Section | Fields and actions owned here |
| --- | --- |
| Staff language | `staff.locale`, using the existing supported-language catalogue and restrictions |
| Guest languages | Existing template language activation/deactivation |
| Selected guest language | `nativeName`, `staffName`, `icon.url`, `icon.alternativeText` |

Preserve current limits, at-least-one-language rules and staff/guest exclusions.
Tenant activation remains constrained by existing template capabilities; the
page does not introduce arbitrary new tenant languages. Explain this as SSF
language/content configuration, not a control over installed translation models.

### Recordings

| Tab | Fields owned here |
| --- | --- |
| Settings | `recording.enabled`, `legalBasis`, `signature`, `idCheck`, `verificationRequired`, `recoveryMode` |
| Retention and technical settings | `recording.retentionHours`, effective retention and existing reset action; `auditRetentionHours`, `timestampAuthorityUrl` |
| Consent and releases | Existing `recording.texts` entries (`locale`, `consentHtml`, `resumePromptHtml`); the separate `legalTexts` editor |

Keep technical fields editable wherever current permissions allow them. Moving
them to root-only administration would be an authority change outside scope.
Keep current retention units and numeric constraints; a days/hours conversion
editor is not required. Defaults never enable tenant recording.

Within Consent and releases, distinguish the two existing contract groups:

- Recording wording: existing locale entries and add/remove actions.
- Legal wording: `sourceLocale`, `version`, localisations and their existing
  `mode2Consent`, `mode3Consent`, `guestRecordingRelease`,
  `staffRecordingRelease`, and `recordingStatus` groups. Choice groups retain
  headline, body and affirmative/refusal labels; status retains its four texts.

Do not merge these storage models or infer that quality-mode wording implements
a quality-session runtime. Preserve the existing source-locale and localisation
creation/removal constraints. Keep all text fields editable when recording is
disabled so administrators can prepare configuration.

### Feedback

Staff and Guests tabs edit `staff.feedback` and
`guestLanguages[locale].feedback`, respectively. The Guests tab selects an
existing guest language. The form contains its existing headline, supported
question text/headline, required flag, applicable scale labels, free-text
placeholder/maximum length, `noticeHtml` and button label.

Reuse the existing supported question IDs and controls. Do not add question
creation, deletion, reordering, new types or response analytics. Preserve fields
that the current editor cannot edit when saving the surrounding form.

## Root pages and field ownership

### Installation overview

Summarise existing `installation` and `runtimeTemplate` configuration and link
to the two root editing pages. Present installation branding/locale, template
languages and retention as configuration facts. Tenant lifecycle, provisioning
jobs and plugin activation remain in their existing System/tenant-detail views.

### Default configuration

Edit the behavioural parts of `runtimeTemplate`:

- Languages: `staff.locale`; existing guest-language add/remove controls;
  guest `nativeName`, `staffName` and `icon`.
- Recording settings: the same settings as the tenant page except tenant
  activation, which has no root-template activation control.
- Retention and technical settings: `retentionHours`, `auditRetentionHours`,
  `timestampAuthorityUrl` and existing validation/conflict handling.

Root language add/remove uses the existing catalogue and actions; removing an
entry keeps the existing semantics for its dependent content. This is not a
new independent language catalogue. Do not alter existing archive expiry dates.

### Default content

Two top-level tabs separate the existing persistence scopes:

| Tab | Sections and field ownership |
| --- | --- |
| Installation | `installation.branding`; `legal.imprintUrl`, `privacyPolicyUrl`, `accessibilityStatementUrl`; `localization.locale`, `startpage.enterCode`, `send`, `login`; `localization.login.headline`, `descriptionHtml`; `localization.feedback` |
| Tenant template | `runtimeTemplate.branding`; staff dashboard/new-conversation texts; guest explanation texts; recording/legal wording; staff and guest feedback forms |

Use the same named sections and field components as tenant editing. Template
staff locale and guest-language membership are edited only in Default
configuration. Installation locale stays here because it belongs to the
installation's single localisation object. Installation and template branding
remain separate values, labelled by their actual scope.

## Language switching

Studio UI locale, selected content locale and SSF configured languages are
separate concepts. Changing content locale changes only the displayed editor.

1. Place a labelled Language version selector above each multilingual group.
2. List actual entries using human-readable names and locale codes. Preserve
   an existing locale in the selector even if the current catalogue lacks it.
3. Switch all fields in the selected group together, keyed by locale rather
   than array position. Reordering must not attach a draft to another language.
4. Keep all language drafts in memory until the page is saved or discarded.
5. Save includes every edited language on that page, including hidden ones.
   Validation errors identify their language and expose the relevant editor.
6. Discard resets the entire page, including every language and tab.
7. On initial load select the legal source locale for legal wording; for other
   collections select the first available entry. Retain the selection while it
   exists during editing; after removal select the source/first remaining entry.

There is no global cross-page content-language setting. Guest content,
recording wording and legal localisations have independent memberships. A
runtime fallback must never be displayed as an authored translation. Existing
source-language behaviour stays unchanged.

Staff content and installation localisation currently each have one configured
locale, not a collection of translations. Show that locale; do not add a
multilingual switch that implies otherwise. Selecting another configured locale
does not translate the existing text. Locale fields themselves keep their
existing editing locations and semantics.

Adding/removing recording wording remains available as today. Its locale-entry
field remains editable; the selector navigates existing entries and must still
allow selection of an unfinished entry with a missing locale so it can be fixed.

## Drafts, persistence and conflicts

The UI is split into pages; the existing content aggregates are not split into
new databases or domain services. Existing endpoints remain the initial reuse
target:

- `/api/v1/plugins/ssf/content-v2/tenant` for template/overrides reads and
  tenant override writes.
- `/api/v1/plugins/ssf/content-v2/system` for installation/template operations.

Each editing page owns a defined projection of the aggregate. Save and Discard
apply to that whole page, including its tabs and languages. Moving between its
tabs/languages does not save, reload or reset the draft. Overview shows saved
values only. No cross-page draft workspace or autosave is introduced.

For navigation away from an unsaved page, use an existing Studio unsaved-change
guard if available. Otherwise add the minimal shared Save/Discard/Stay guard
needed for the new page boundaries, including context changes; do not silently
discard work. This is editor integrity, not a new business workflow.

Save must preserve unrelated content, unknown supported fields, template
inheritance and tenant overrides. Editing a guest collection on one page must
not replace its explanation/feedback values from an old snapshot. Restore the
draft from the successful server response; preserve it after a failed write.
Existing tenant-invalidating template conflicts must remain visible.

The inspected DTOs expose aggregate writes without an explicit concurrency
precondition. A client-only read/merge/write cannot guarantee protection from
concurrent updates. Before implementation, the owning proposal must verify
server transaction/concurrency semantics and select either an existing atomic
update mechanism or the smallest required revision-precondition/section-update
extension. Stale conflicting writes must be rejected without losing the draft;
unrelated fields must not be overwritten. Do not claim this guarantee from a
fresh client read alone.

## Legacy retirement

Remove V1/V2 selection, legacy tabs, legacy editors and their exclusive UI
translations, browser API helpers and admin handlers after dependency review.
Do not provide a hidden compatibility editor.

Before removing storage or an endpoint, identify its active writers and readers.
If legacy-only values are still used, map them explicitly into the current model
with documented precedence and an idempotent migration. Preserve authored texts
and tenant-specific choices; surface an unmappable conflict rather than silently
discard it. If no live dependency exists, remove the obsolete path directly.

Retirement of a browser administration API is distinct from retirement of an
SSF service runtime API. Keep a service endpoint or compatibility field while a
supported consumer requires it. In particular, retired conversation-storage
controls must not be restored, and required disabled compatibility output must
remain valid. No runtime API removal is implied by removal of its editor.

## Acceptance criteria

1. Tenant and root navigation use the agreed Applications/System structure and
   existing branding. Unrelated module navigation still works.
2. Direct routes, active navigation, refresh and keyboard navigation work;
   server authorization rejects wrong-scope access regardless of visibility.
3. Every current editable field has exactly one editing location per scope,
   as mapped above. No legacy editor or version-selection tab remains.
4. No configuration right automatically grants recording or key access.
5. Existing valid configuration renders and round-trips without changing runtime
   responses, except for deliberate administrator edits.
6. Every page can save independently without changing fields owned elsewhere;
   concurrent stale writes cannot silently overwrite another editor's changes.
7. Switching language/tab preserves drafts. Save covers hidden language edits;
   Discard resets all page edits; errors expose the affected language/group.
8. Legal source locale/version and independent language collections retain
   current semantics. Missing translations are never invented or mislabelled.
9. Existing defaults, override/reset actions, explicit tenant recording
   enablement, retention limits and template-conflict rejection still work.
10. Feedback editing retains current supported controls and preserves other
    form data. No general question builder or analytics is introduced.
11. Overview values match saved configuration and make no operational-readiness
    or legal-approval claims. Read failures remain distinguishable from absence.
12. Legacy removal has consumer/dependency evidence; any required data migration
    preserves values, is repeatable and has a documented rollback approach.
13. Loading, retry, validation, read-only and saving states use Studio patterns;
    controls have accessible labels and keyboard/focus behaviour.
14. New UI labels use existing DE/EN translation infrastructure. This design and
    implementation documentation remain English.

Validate with focused Studio UI, navigation/access, override/persistence and
affected type/runtime tests, plus SSF contract regression where producer output
or legacy compatibility is touched. No production enablement is part of design
acceptance.

## Implementation-entry checks

Resolve these technical checks in the Studio proposal before changing code:

| Check | Required outcome |
| --- | --- |
| Navigation depth | Confirm supported SDK contract or specify a generic extension |
| Field audit | Reconcile this mapping against the chosen current Studio revision |
| Persistence | Demonstrate safe section ownership and concurrency handling |
| Leaving an edited page | Locate the shared guard or specify the minimal common guard |
| Legacy dependencies | Record consumer inventory and any migration/retention requirements |

These are implementation-entry checks, not additional product features. Review
this design before producing the implementation plan; retain a separate approval
step for the owning OpenSpec change.
