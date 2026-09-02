## 1. Schema and Contract

- [ ] 1.1 Define versioned, typed allowlisted event models and stable error taxonomy.
- [ ] 1.2 Create ClickHouse schema migrations for raw session and translation quality records.
- [ ] 1.3 Add monthly partitioning, event_id deduplication, 30-day raw-data TTL, and 13-month daily aggregate TTL.

## 2. Writer and Gateway Integration

- [ ] 2.1 Implement a bounded asynchronous writer with batched, acknowledged inserts and operational metrics.
- [ ] 2.2 Implement retry and idempotency behavior keyed by event_id.
- [ ] 2.3 Emit allowed lifecycle, pipeline, delivery, and terminal-outcome metadata from API Gateway hooks.
- [ ] 2.4 Ensure unavailable ClickHouse never changes message, session, or WebSocket outcomes.

## 3. Privacy and Operations

- [ ] 3.1 Redact content-bearing pipeline metadata through an explicit allowlist.
- [ ] 3.2 Persist only opaque content references and consent snapshots; do not implement content storage here.
- [ ] 3.3 Add dashboards, writer-health alerts, retention verification, and operational runbook updates.

## 4. Verification

- [ ] 4.1 Add unit tests for allowlisting, redaction, and stable error classification.
- [ ] 4.2 Add tests for duplicate event delivery and retry idempotency.
- [ ] 4.3 Add tests proving a ClickHouse outage does not affect successful or failed message processing.
- [ ] 4.4 Add integration tests for schema, TTL configuration, and aggregate correctness.

## 5. Probe (issue #199)

Issue #199 is deliberately scoped to a single transport probe, not to the
capability above. It is tracked separately so the checkboxes in sections 1-4
keep meaning what they say: none of them is satisfied by one probe event.

- [x] 5.1 Typed, immutable probe event with a fail-closed two-key attribute allowlist.
- [x] 5.2 Emitter that never changes its caller's outcome, with per-outcome counters.
- [x] 5.3 OTLP/HTTP adapter as the only module importing the OTel SDK.
- [x] 5.4 Gateway wiring: mode enum with a safe fallback, lifespan build and teardown, admin probe endpoint.
- [x] 5.5 Internal-only collector service with a fail-closed logs pipeline.
- [x] 5.6 Bronze and silver DDL owned by the repository and applied on first boot.
- [x] 5.7 End-to-end proof through the gateway's own startup path, plus a rogue-sender privacy test.
- [x] 5.8 Probe enabled by default for local and dev, explicitly disabled in production.
- [x] 5.9 Observed insertion, querying, failure and operational behaviour written up in
      `docs/operations/clickhouse-telemetry-probe-findings.md`.

### Explicitly not delivered by #199

- No error taxonomy exists (1.1). The probe has no failure classification.
- No session or translation quality records (1.2). One probe table only.
- No gold tier and no 13-month aggregate TTL (1.3) — deferred by design.
- No bounded acknowledged writer (2.1). Delivery is lossy by design: the OTel
  SDK's `BatchLogRecordProcessor` drops on overflow without surfacing it in
  `ssf_quality_telemetry_events_total`.
- No pipeline hooks (2.3). Telemetry is reachable only from the admin probe
  endpoint, so 2.4 is untested against real message or WebSocket paths.
- No consent snapshots or content references (3.2).
- No dashboards or writer-health alerts (3.3). Runbook and findings write-up only.
- Production is `disabled` explicitly in
  `deploy/production/docker-compose.production.yml`, so merging changes nothing
  there. The `otel-collector` service is defined and digest-pinned, but starting
  it, pre-pulling the image and applying the schema are host-side steps that
  cannot be committed — the ordered procedure is in the runbook under Quality
  Telemetry -> Enabling in production.
- The OTLP instrumentation-scope namespace is not allowlisted in the collector.
  No SSF code path can write content into it; a security review judged the residual
  exposure non-actionable. Tracked in the findings write-up.
