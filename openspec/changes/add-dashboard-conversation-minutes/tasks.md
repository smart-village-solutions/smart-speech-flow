## 1. Lifecycle and usage persistence

- [x] 1.1 Record and restore first activation exactly once across activation,
  reactivation, language changes and gateway restarts; persist language intervals
  with their effective timestamps without creating gaps or overlaps.
- [x] 1.2 Implement durable gateway-internal usage storage with tenant and owner
  attribution, timestamps, idempotent lifecycle updates and bounded retention
  covering the reporting window and ongoing conversations.
- [x] 1.3 Preserve existing telemetry semantics and keep owner references out of
  telemetry, logs and public session responses.

## 2. Reporting API

- [x] 2.1 Add an authenticated admin endpoint deriving tenant and owner from the
  verified identity and returning personal, organisation and server totals, each
  with a breakdown by configured customer language.
- [x] 2.2 Implement rolling-window overlap, ongoing conversation accounting,
  coverage metadata and an explicit unavailable state on reporting failure.
- [x] 2.3 Verify boundary timestamps, pauses, pending-only sessions, automatic
  termination, duplicate updates, restarts and cross-tenant access isolation;
  verify language switches, both translation directions, unknown-language
  fallback and equality between unrounded language sums and scope totals.

## 3. Dashboard

- [x] 3.1 Add three localised usage figures, each with an all-languages total and
  a language breakdown labelled only with the customer language, with the
  reporting period, measurement definition,
  loading, unavailable and incomplete-coverage states.
- [x] 3.2 Refresh totals and clear cached results on identity or tenant changes.
- [x] 3.3 Run relevant gateway and frontend tests, type checks and lint checks.
