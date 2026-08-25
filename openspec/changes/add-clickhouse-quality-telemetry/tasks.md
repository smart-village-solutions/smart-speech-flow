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
