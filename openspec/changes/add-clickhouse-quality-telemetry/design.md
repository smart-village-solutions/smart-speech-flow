## Context

The installed internal ClickHouse service is ready for analytical data but has
no telemetry schema. The KPI catalogue defines two durable quality records,
session_quality and translation_quality, and requires a strict separation
between analytical metadata and consented content.

## Decisions

- Every event has a UUID event_id and integer schema_version.
- Writers use a bounded in-memory queue and asynchronous batches. Insertion
  retries preserve event_id so duplicate deliveries count once.
- A ClickHouse failure is observable through an operational metric and
  structured, content-free log but never delays, cancels, or fails a message.
- Raw metadata expires after 30 days. Pseudonymised daily aggregates expire
  after 13 months.
- The event allowlist excludes source text, ASR text, translations, TTS text,
  audio bytes, audio URLs, IP addresses, full user agents, raw errors, and
  debug payloads. It permits only content_record_id_hash and consent metadata.
- Text and consent-ledger data require a separate transactional content system;
  audio requires an encrypted, tenant-isolated object store.

## Risks

- Small event inserts can create excessive parts. Use batching or ClickHouse
  asynchronous inserts with durable acknowledgement.
- Retry ambiguity can duplicate analytics. Deduplicate by event_id.
- Pipeline metadata can contain content. Convert it through explicit typed
  allowlists rather than serialising source dictionaries.
- Consent withdrawal must stop future content capture and trigger deletion in
  the separate content store; ClickHouse holds only an opaque reference.
