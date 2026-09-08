# Smart Speech Flow Delivery Roadmap

This roadmap provides strategic context for the 2026 delivery programme. The
operational source of truth for work-package status is the GitHub Project and
its repository snapshot in
[`apps/project-report/src/data/project-status.json`](apps/project-report/src/data/project-status.json).

**Last reconciled:** 3 September 2026

**Status source:** GitHub Project #7 (Smart Speech Flow Delivery)

**Scope:** Reliable, accessible multilingual communication for public-administration staff and citizens.

## Current delivery position

Milestones M1 to M3 are past their committed dates. M4 is due today. The
delivery plan therefore prioritises work that removes blockers from the
conversation flow, legal review, core-module maintainability, and required
language coverage.

| Milestone | Committed date | Current position |
| --- | --- | --- |
| M1 — Foundations and UI prototype | 13 August 2026 | Four packages complete; legal review (WP-013) remains in implementation. |
| M2 — Conversation and audio flow | 20 August 2026 | Conversation flow (WP-004) and accessible conversation surfaces (WP-019) are complete; WP-005 status is disputed (`Done` / `Planned`) pending #273, while required language profiles remain planned. |
| M3 — Complete most refactoring | 27 August 2026 | Four packages remain planned; WP-022 status is disputed (`Done` / `Planned`) pending #273. |
| M4 — Internal optimisation round | 3 September 2026 | Four packages remain planned. |
| M5 — Complete internal optimisation | 10 September 2026 | Training, usage, and handover materials (WP-025) are in implementation; four packages remain planned. |
| M6 — Public optimisation and rollout preparation | Mid-September 2026 | Planned; public optimisation (WP-011) needs attention. |
| M7 — Regular operation | October 2026 | Planned. |

## Immediate work order

1. **WP-013 — Legal review:** obtain the commissioned review's concrete remit
   and results, document obligations, and unblock WP-014 and WP-015.
2. **WP-007 — Maintainable core modules:** prioritise the linked gateway
   boundary work and resolve the related issues #225, #228, #229, and #230.
3. **WP-020 — Required language and use profiles:** complete after WP-005
   provides robust audio processing.
4. **WP-006 — Status, error handling, and transparency:** resume after WP-005
   and complete the resilience paths represented by issues #219 and #220.
5. **WP-015 — Tenant model and data isolation:** prepare the design once
   WP-013 provides the legal constraints; issue #232 tracks the work.

## Delivery risks and dependencies

- WP-005 blocks WP-006 and WP-020; its GitHub evidence currently contains
  conflicting `Done` and `Planned` statuses.
- WP-022 depends on the completed conversation flow plus WP-005, WP-007, and
  WP-016; its GitHub evidence also contains conflicting `Done` and `Planned`
  statuses.
- The plan preserves the current statuses of WP-005 and WP-022 until the
  conflicts are decided in [decision issue #273](https://github.com/smart-village-solutions/smart-speech-flow/issues/273).
  No strategic-priority class has changed.
- The M1–M4 date slippage requires explicit delivery decisions before treating
  later milestones as forecast commitments.

## Recently completed delivery evidence

- Pipeline admission control was deployed on 1 September 2026.
- Keycloak infrastructure foundation was merged on 1 September 2026.
- ClickHouse quality telemetry probe via OpenTelemetry was merged on
  3 September 2026.

These changes improve operational readiness, but they do not by themselves
prove all acceptance criteria of the affected work packages.

## Governance

- GitHub Project #7 is the current delivery-status source.
- OpenSpec changes record approved intended work and task progress.
- The repository status snapshot supports the project report.
- This roadmap provides prioritisation and context; it does not override
  current GitHub evidence or approved project decisions.
