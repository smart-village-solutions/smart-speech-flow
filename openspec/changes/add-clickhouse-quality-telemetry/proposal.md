# Change: Add ClickHouse Quality Telemetry

## Why

SSF needs durable, privacy-aware analytical records to calculate the
conversation-quality KPIs, identify reliability and latency regressions, and
compare releases and model configurations. Prometheus remains the operational
metrics system; ClickHouse is the analytical event store.

## What Changes

- Add an allowlisted, versioned quality-event contract and ClickHouse schema.
- Add a bounded, asynchronous telemetry writer that cannot delay or fail the
  message and session paths.
- Record pseudonymised session, pipeline, delivery, failure, and release/model
  metadata with idempotent event delivery.
- Add retention, aggregates, dashboards, operational metrics, and tests.
- Record only opaque content references and consent snapshots; do not store
  text, transcripts, translations, recordings, audio URLs, IP addresses, or
  free-form errors in ClickHouse.

## Impact

- Affected capability: quality-telemetry.
- Affected code: API Gateway lifecycle and pipeline hooks, telemetry module,
  deployment schema assets, Grafana dashboards, and tests.
- Dependency: the internal ClickHouse service is installed separately.
- Dependency: consent-governed content storage is a separate future capability.
- GitHub issue: https://github.com/smart-village-solutions/smart-speech-flow/issues/199

## Non-Goals

- Implementing the separate transactional content database or encrypted object
  store.
- Capturing content without granular, purpose-specific, withdrawable consent.
- Replacing Prometheus or changing public API contracts.
