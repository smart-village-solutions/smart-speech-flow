## 1. Schema and Contract

- [x] 1.1 Define versioned, typed allowlisted event models and stable error taxonomy.
- [x] 1.2 Create ClickHouse schema migrations for raw session and translation quality records.
- [x] 1.3 Add monthly partitioning, event_id deduplication, 30-day raw-data TTL, and 13-month daily aggregate TTL.

## 2. Writer and Gateway Integration

- [ ] 2.1 Implement a bounded asynchronous writer with batched, acknowledged inserts and operational metrics.
- [ ] 2.2 Implement retry and idempotency behavior keyed by event_id.
- [ ] 2.3 Emit allowed lifecycle, pipeline, delivery, and terminal-outcome metadata from API Gateway hooks.
      Lifecycle, pipeline and terminal-outcome metadata are delivered:
      `session_lifecycle` from the session manager's three transitions,
      `translation_message` once per processed message from
      `send_unified_message`, and `refinement_attempt` from the in-path refiner
      and the shadow candidate. **Delivery** metadata is the one clause left,
      and it is deliberately blocked -- see the deferral note below.
- [x] 2.4 Ensure unavailable ClickHouse never changes message, session, or WebSocket outcomes.

## 3. Privacy and Operations

- [x] 3.1 Redact content-bearing pipeline metadata through an explicit allowlist.
- [ ] 3.2 Persist only opaque content references and consent snapshots; do not implement content storage here.
- [x] 3.3 Add dashboards, writer-health alerts, retention verification, and operational runbook updates.

## 4. Verification

- [x] 4.1 Add unit tests for allowlisting, redaction, and stable error classification.
- [ ] 4.2 Add tests for duplicate event delivery and retry idempotency.
- [x] 4.3 Add tests proving a ClickHouse outage does not affect successful or failed message processing.
- [x] 4.4 Add integration tests for schema, TTL configuration, and aggregate correctness.

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

### Explicitly not delivered

Updated as each bullet stops being true. What remains open:

- No bounded acknowledged writer (2.1). Delivery is lossy by design: the OTel
  SDK's `BatchLogRecordProcessor` drops on overflow without surfacing it in
  `ssf_quality_telemetry_events_total`. This is now **measurable** rather than
  invisible — `QualityTelemetryEventsLostBeforeCollector` compares what the
  gateway queued against what the collector received, and the gap is the drop.
  Decide 2.1 from that evidence at production volume, not on principle.
- No writer-level retry idempotency (2.2). Deduplication is at the storage
  layer: silver collapses duplicate `event_id`s and every gold counter is
  `uniqExact` over `event_id`, so a retried delivery cannot inflate a count.
  The latency aggregates have no distinct-by form and do skew; documented in
  the migration.
- Delivery metadata is not emitted (2.3), and 2.3 cannot be ticked until it is
  or until the clause is dropped from the task. `delivery_attempt` is blocked on
  three defects that would make its numbers fiction: the hardcoded WebSocket
  disconnect reason, the connection-id collision, and
  `websocket_fallback.py:320` silently dropping the oldest queued message. Fix
  those first, or decide that delivery is out of scope for this change.
- 3.2 has nothing to persist yet. Nothing any of the three events emits refers
  to content, so there is no opaque reference to store; and no consent field
  exists on the `Session` dataclass to snapshot. It stays open as a decision,
  not as unwritten code.
- 2.4 and 4.3 are now proven against the live message path: a real
  `QualityTelemetry` with a dead exporter returns the same success response and
  raises the same `HTTPException`, detail for detail, as one with telemetry off.
  The WebSocket path has no emitter yet, so it has nothing to fail; that arrives
  with `delivery_attempt`, which is deferred behind two known bugs.
- No consent snapshots or content references (3.2). Nothing emitted so far
  refers to content at all, so there is no reference to persist yet.
- The gold tier still aggregates only the refinement attempt's dimensions and
  latencies (4.4). A `translation_message` row reaching it contributes a correct
  daily count under its own `event_type` and a zero to every latency state --
  verified live -- so message latency is read from silver, which keeps 30 days.
  Extending gold means rewriting its ORDER BY, which is a table recreate, and it
  belongs with the aggregate-correctness work that will have real volume to
  verify against. Every gold-reading dashboard panel is guarded to filter on
  `event_type`. The same is true of `session_lifecycle`.
- Production remains `disabled` in
  `deploy/production/docker-compose.production.yml`, so merging changes nothing
  there. `probe` emits no pipeline events either; `enabled` is the value that
  does, and migrations `002` and `003` must both be applied before it is set.
  The ordered procedure is in the runbook under Quality Telemetry -> Enabling in
  production, step 11.
- `SSF_QUALITY_TELEMETRY_SESSION_KEY` keys the telemetry pipeline's own
  pseudonymisation. The four `sha256(session_id)[:12]` helpers in `customer.py`,
  `websocket.py`, `session.py` and `admin.py` still write unkeyed digests to the
  operational logs; converging them onto the keyed HMAC changes what appears in
  existing logs and is deliberately a separate change.
- The OTLP instrumentation-scope namespace is not allowlisted in the collector.
  No SSF code path can write content into it; a security review judged the
  residual exposure non-actionable. Tracked in the findings write-up.
