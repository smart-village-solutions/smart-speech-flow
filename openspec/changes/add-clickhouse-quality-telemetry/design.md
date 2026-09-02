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

## Amendments (implementation, 2026-09-01)

Issue #199 implemented a minimal transport probe against this design. It does
not satisfy the task list; see `tasks.md` section 5 for what it does and does
not deliver. These points differ from the text above:

- The event type travels as OTLP's top-level `event_name` field, not as an
  attribute. The ClickHouse exporter writes it to a dedicated typed
  `EventName` column, discovered during implementation; the allowlist has no
  `event.name` entry as a result.
- Transport is the OpenTelemetry Collector (`gateway -> OTLP/HTTP ->
  otel-collector -> clickhouseexporter -> ClickHouse`), not a direct
  in-process writer. The collector is additive: one OTLP receiver, one
  ClickHouse exporter, logs pipeline only.
- Deduplication happens in the silver `quality_events` table
  (`ReplacingMergeTree`, ordered on `(event_type, event_id)`), not in the
  writer. A retried export produces duplicate bronze rows; the merge collapses
  them, and reads use `FINAL`.
- The bounded queue is the OTel Python SDK's `BatchLogRecordProcessor`
  (`max_queue_size`, default 2048). Its overflow drops are **not** surfaced in
  `ssf_quality_telemetry_events_total` — they are visible only in SDK and
  collector internals, not in this counter's `dropped_*` outcomes.

Telemetry is lossy by design and carries no durability guarantee: there is no
Outbox and no transactional write alongside business state. This is a
deliberate trade so telemetry never delays or fails a message.

### The allowlist has two namespaces, not one

Section 3.5 treats the attribute allowlist as a single manifest. OTLP has three
independent ones -- resource, instrumentation scope, and log record.
`keep_keys(log.attributes, ...)` does not touch resource attributes, and
`Resource.create(...)` silently populates them from
`OTEL_RESOURCE_ATTRIBUTES`, `OTEL_SERVICE_NAME`, `telemetry.sdk.*` and a
per-process `service.instance.id`. A "fail-closed" log allowlist beside an
open resource namespace is not fail-closed.

The resource and log namespaces are therefore allowlisted, in both places: the
gateway uses `Resource(attributes=...)` so nothing is inherited from the
environment, and the collector applies `keep_keys` to each. The scope namespace
remains unfiltered -- no SSF code path can write content into it, and a security
review judged the residual exposure non-actionable, but it is a real gap in a
control described as fail-closed and is tracked in the probe findings. A record that carries no
`ssf.quality.event_id` is dropped by `filter/quality_only` rather than
rewritten, so a future telemetry customer gets its own pipeline instead of
silently losing its body and attributes to this one.

`error_mode` must be `propagate`. `ignore` skips a failed statement and lets
the record through with its original body and attributes, which inverts the
guarantee.

### The repository owns both medallion tiers

The design implied the exporter owns bronze (`create_schema: true`). That
cannot work: the exporter creates `otel_logs` only on its first successful
export, so the silver materialized view — which selects `FROM otel_logs` —
cannot be applied on a fresh deploy, and bronze's TTL can never be retrofitted
afterwards because ClickHouse fixes TTL at creation.

`deploy/clickhouse/` therefore owns both tiers and the exporter runs with
`create_schema: false`. The cost is a standing constraint: every column the
exporter names in its INSERT must exist in `000_otel_logs.sql`, checked on each
collector image bump.

### Failure is reported, not implied

`emit_probe` returns a typed `ProbeResult` whose `outcome` doubles as the
metric's label, so a counter series that nothing can increment cannot exist.
That holds for `disabled` too, which is why the disabled branch counts before
returning: disabled is the production default, and a scrape with no series at
all cannot distinguish "off on purpose" from "never wired up".
The admin endpoint surfaces it: an `event_id` on its own does not mean a row
landed, and a probe endpoint that cannot distinguish the two is not a probe.

The mode is parsed with a fallback to `disabled` and a warning, never by
raising. An unrecognised `SSF_QUALITY_TELEMETRY_MODE` used to abort the whole
gateway's startup — an optional telemetry setting must not be able to stop
translation.

### Teardown is bounded, not best-effort

`LoggerProvider.shutdown()` joins the SDK's export thread for a default 30s
while it drains the queue. Docker's stop grace is 10s, so a collector that
accepts the connection and never answers would turn an ordinary container stop
into what looks like a hang. Teardown therefore runs on a daemon thread with a
2s budget and is abandoned if it overruns — `asyncio.to_thread` cannot be
abandoned, because the loop's own teardown joins the default executor.

The exporter is also built inside a `try`. The SDK parses
`OTEL_EXPORTER_OTLP_TIMEOUT` and `_COMPRESSION` itself and raises on a
malformed value, which would crashloop the gateway over an optional setting;
the fallback reports `disabled` rather than a probe mode that silently exports
nothing.

## Risks

- Small event inserts can create excessive parts. Use batching or ClickHouse
  asynchronous inserts with durable acknowledgement.
- Retry ambiguity can duplicate analytics. Deduplicate by event_id.
- Pipeline metadata can contain content. Convert it through explicit typed
  allowlists rather than serialising source dictionaries.
- Consent withdrawal must stop future content capture and trigger deletion in
  the separate content store; ClickHouse holds only an opaque reference.
