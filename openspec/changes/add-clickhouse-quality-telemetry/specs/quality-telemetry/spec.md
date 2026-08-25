## ADDED Requirements

### Requirement: Versioned privacy-aware quality events

The system SHALL emit quality telemetry through a versioned, allowlisted event
contract. Every event SHALL include a unique event_id, schema_version, UTC
timestamp, pseudonymised identifiers where necessary, and no content-bearing
field.

#### Scenario: Content-bearing metadata is received

- **WHEN** an event source includes text, an audio URL, raw error text, audio
  bytes, an IP address, or a debug payload
- **THEN** the telemetry payload excludes those values and retains only
  approved metadata

#### Scenario: Consented content exists

- **WHEN** a message has valid consented content in the separate content store
- **THEN** ClickHouse records at most an opaque content_record_id_hash and
  consent metadata

### Requirement: Non-blocking idempotent telemetry delivery

The system SHALL batch telemetry delivery asynchronously and deduplicate
retries by event_id. Telemetry delivery SHALL not change message, session, or
delivery outcomes.

#### Scenario: ClickHouse is unavailable

- **WHEN** the telemetry writer cannot insert a batch
- **THEN** the message pipeline completes independently and the failed batch is
  observable without content leakage

#### Scenario: An event is retried

- **WHEN** the writer delivers the same event_id more than once
- **THEN** the analytical record is counted once

### Requirement: Retention and analytical comparability

The system SHALL retain raw pseudonymised quality metadata for 30 days and
pseudonymised daily aggregates for 13 months. Quality records SHALL retain
effective release, pipeline, provider, model, and configuration comparison
metadata.

#### Scenario: Raw-event retention expires

- **WHEN** a raw quality record reaches 30 days of age
- **THEN** ClickHouse removes it according to the configured TTL while
  preserving eligible daily aggregates

#### Scenario: Model comparison is requested

- **WHEN** an operator queries quality results by model or release
- **THEN** the results can be segmented by the recorded comparison metadata
