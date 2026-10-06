# Smart Speech Flow Delivery Roadmap

This roadmap sets the immediate delivery order for reliable, accessible
multilingual communication in public administration. [GitHub Project #7](https://github.com/orgs/smart-village-solutions/projects/7)
is the operational status source; the [project report snapshot](apps/project-report/src/data/project-status.json)
records reconciled work-package statuses. Approved decisions take precedence
over individual Project cards, and unresolved conflicts do not change status.

**Last reconciled:** 6 October 2026

**Strategic priority classes:** unchanged

**Schedule:** the August and September milestone dates have passed. The
October regular-operation target remains a planning target, not a confirmed
forecast or release approval.

## Current delivery position

The reconciled snapshot has 8 of 27 work packages `Done`, 2 in
`Implementation`, and 17 `Planned`. WP-006 and WP-008 moved to `Done` because
their primary GitHub Project items are uncontested and marked `Done`. These
statuses describe the Project's delivery classification; a completed linked
issue alone does not prove every work-package acceptance criterion.

| Milestone | Original date | Position on 6 October |
| --- | --- | --- |
| M1 — Foundations and UI prototype | 13 August | Four done; legal review WP-013 remains in implementation. |
| M2 — Conversation and audio flow | 20 August | WP-004 and WP-019 done; WP-005 and WP-020 remain planned. |
| M3 — Most refactoring | 27 August | WP-006 done; WP-007, WP-015, WP-021, and WP-022 planned. |
| M4 — Internal optimisation | 3 September | WP-008 done; WP-014, WP-016, and WP-023 planned. |
| M5 — Complete internal optimisation | 10 September | WP-025 in implementation; four other packages planned. |
| M6 — Public optimisation and rollout preparation | Mid-September | WP-011 and WP-026 planned. |
| M7 — Regular operation | October | WP-012 and WP-027 planned; no confirmed start date. |

## Immediate work order

1. **WP-013 — Legal review (owner not recorded; ready):** obtain the
   commissioned review's scope, results, and obligations. Its Project card is
   still `Implementation`, and it blocks WP-014 and WP-015. The original M1
   deadline has passed.
2. **WP-005 — Robust audio processing (owner not recorded; ready for
   reassessment):** review malformed and oversized audio, pipeline failures,
   network interruption, and end-to-end evidence against the package criteria.
   [#219](https://github.com/smart-village-solutions/smart-speech-flow/issues/219)
   has closed and its primary Project item says `Done`, but the documented
   [#273 decision](https://github.com/smart-village-solutions/smart-speech-flow/issues/273#issuecomment-5774554018)
   keeps the package `Planned` pending a full delivery review. Record a new
   decision before changing its status; WP-020 depends on it.
3. **WP-007 — Maintainable core modules (owners not assigned to remaining
   issues; ready):** complete the open service-core
   [#225](https://github.com/smart-village-solutions/smart-speech-flow/issues/225)
   and shared-module
   [#229](https://github.com/smart-village-solutions/smart-speech-flow/issues/229)
   work. Gateway boundary and legacy-consolidation contributions are done
   ([#228](https://github.com/smart-village-solutions/smart-speech-flow/issues/228),
   [#230](https://github.com/smart-village-solutions/smart-speech-flow/issues/230),
   [PR #530](https://github.com/smart-village-solutions/smart-speech-flow/pull/530)).
   WP-021, WP-016, and WP-022 depend on this package.
4. **WP-020 — Required language and use profiles (owner not recorded; blocked
   by WP-005):** after the WP-005 decision, test German, English, Arabic,
   Turkish, Italian, Persian, Russian, and Ukrainian and document the supported
   profiles. Its Project card remains `Planned`.
5. **WP-015 — Tenant model and data isolation (tracked by
   [#232](https://github.com/smart-village-solutions/smart-speech-flow/issues/232),
   assigned to Philipp Wilimzig; blocked by WP-013):** prepare the remaining
   isolation and provisioning design against the legal findings. The baseline
   two-realm conversation-access acceptance is complete
   ([#438](https://github.com/smart-village-solutions/smart-speech-flow/issues/438));
   that result does not complete the broader tenant model or WP-016.

WP-021's versioned API contracts and documentation remain planned after
WP-007 ([#226](https://github.com/smart-village-solutions/smart-speech-flow/issues/226),
[#231](https://github.com/smart-village-solutions/smart-speech-flow/issues/231)).
WP-025 training and handover materials remain in implementation. Related
[#238](https://github.com/smart-village-solutions/smart-speech-flow/issues/238)
is assigned to Philipp Wilimzig; external release still needs confirmed production,
privacy, language, device, and support guidance.

## Decisions, conflicts, and rollout dependencies

- The [WP-005/WP-022 decision](https://github.com/smart-village-solutions/smart-speech-flow/issues/273#issuecomment-5774554018)
  remains authoritative. Both stay `Planned` pending review against their full
  acceptance criteria. WP-022 still needs scale-out work in
  [#227](https://github.com/smart-village-solutions/smart-speech-flow/issues/227),
  load evidence for at least 250 concurrent accesses, and documented capacity
  planning. Closed contributions do not establish package completion.
- WP-010 has primary Project items at `Done` and `Implementation`. WP-023 has
  completed security contributions while its linked documentation and
  operational evidence remain open. Keep both `Planned` in the snapshot until
  the owner resolves their full criteria and Project status in
  [decision issue #538](https://github.com/smart-village-solutions/smart-speech-flow/issues/538).
- The compatible tenant conversation gateway passed fresh, attribute-free
  two-realm live acceptance on 28 September, including cross-tenant HTTP,
  polling, and WebSocket denial
  ([#438](https://github.com/smart-village-solutions/smart-speech-flow/issues/438)).
  The operational admission decision does not establish complete tenant
  provisioning, privacy evidence, or multi-organisation pilot readiness.
- [PR #537](https://github.com/smart-village-solutions/smart-speech-flow/pull/537)
  merged the tenant-safe WebSocket monitoring contract on 6 October;
  [PR #533](https://github.com/smart-village-solutions/smart-speech-flow/pull/533)
  records a production rollout earlier that day. A merge after that rollout
  is not, by itself, deployment evidence for the later PR.
- M5 pilot work, M6 public optimisation and rollout preparation, and M7
  regular operation still depend on unfinished language, tenant, evidence,
  and pilot packages. Delivery owners need to reforecast the passed milestone
  dates before using them as commitments.

## Governance

- GitHub Project #7 supplies current delivery classifications; documented
  project decisions supersede individual card statuses.
- OpenSpec records intended changes and task progress. It does not, by itself,
  approve a rollout or complete a whole work package.
- The project report snapshot preserves unresolved status conflicts until a
  documented delivery decision resolves them.
