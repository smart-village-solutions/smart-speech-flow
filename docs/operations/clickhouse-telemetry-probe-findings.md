# ClickHouse Quality Telemetry Probe — Observed Behaviour

Findings from the discovery task in
[issue #199](https://github.com/smart-village-solutions/smart-speech-flow/issues/199),
which asked us to send a minimal non-content event to the internal ClickHouse
instance, inspect the stored rows, and learn how the tooling behaves in the SSF
environment.

Everything below was measured against the local stack
(`clickhouse/clickhouse-server:26.3.17.110`,
`otel/opentelemetry-collector-contrib:0.159.0`, `opentelemetry-sdk==1.44.0`), not
inferred from documentation. Operational procedures live in
[the runbook](runbooks/clickhouse-operations.md); this file records what we
found, including the things that surprised us.

## The measurement

One probe through the shipped path — `POST /api/admin/telemetry/probe` on the
running gateway, no test harness:

```
{"event_id":"1cbc8ca7-c63d-410f-9cd7-b57e73331d45","mode":"probe","outcome":"emitted"}

event_id:        1cbc8ca7-c63d-410f-9cd7-b57e73331d45
schema_version:  1
emitted_at_utc:  2026-09-02 06:16:00.056
event_type:      telemetry_probe
service_name:    api_gateway
service_version: unknown          -- from SSF_RELEASE_VERSION
deployment_env:  local            -- from SSF_DEPLOYMENT_ENV
ingested_at_utc: 2026-09-02 06:16:03.375
```

## Insertion

**End-to-end latency is ~4.4 s, and it is all batching.** `emitted_at_utc` to
`ingested_at_utc` was 3.3 s. Two batch stages sit in series: the SDK's
`BatchLogRecordProcessor` (1 s default schedule delay for logs — 5 s is the
*traces* default) and the collector's `batch` processor (`timeout: 5s`). A
single event waits out both timeouts rather than filling either batch, so ~6 s
is the worst case and an event arriving mid-window sees less — which is why the
measurement above sits below it. Neither stage is a network cost. A probe is
therefore *not* observable immediately after the call returns — any check must
poll, which is why the runbook's verification step and the integration tests
both retry rather than read once.

**The write is genuinely non-blocking.** `emit_probe` returns before the SDK
thread has flushed. The HTTP response carries an `outcome` describing what
happened at the *emitter*, not at ClickHouse — `emitted` means the record was
handed to the exporter, not that a row exists.

**Small inserts do not create a part storm at this rate.** The design flagged
excessive parts as a risk. At probe volume the collector's batching collapses
everything into single small inserts per batch window; `system.parts` stayed
trivial. This says nothing about production KPI volume, which is where the risk
actually lives.

## Querying

**`FINAL` is mandatory, not a nicety.** Silver is
`ReplacingMergeTree(ingested_at_utc)` ordered on `(event_type, event_id)`.
Deduplication happens at merge time, which ClickHouse schedules when it likes.
We observed duplicate rows coexisting for minutes, then collapsing. A consumer
that forgets `FINAL` sees duplicates intermittently — the worst failure mode,
because it looks correct most of the time.

**`toUUIDOrZero` silently manufactures a valid-looking row.** A malformed
`ssf.quality.event_id` (we hit this with a literal `test-id-123` during the
spike) becomes the nil UUID. Combined with the `(event_type, event_id)` sort
key, *every* malformed event of one type then collapses onto a single row — so
bad input presents as data loss rather than as inspectable garbage. The
materialized view now filters on `toUUIDOrNull(...) IS NOT NULL` instead.

## Timestamps

**The OTel SDK sends no timestamp unless you set one.** `Logger.emit(...)`
leaves `LogRecord.timestamp` as `None` and populates only
`observed_timestamp`. Verified directly:

```
timestamp        = None
observed_ts      = 1788324629185457011
```

The ClickHouse exporter then falls back to the observed timestamp when writing
its `Timestamp` column, so rows *look* correct — but the value is the
collector's observation time, and a column named `emitted_at_utc` that actually
means "observed_at" is a trap for anyone doing latency analysis later. The
adapter now passes the event's own emission time explicitly. Bronze has no
`ObservedTimestamp` column, so the distinction is unrecoverable after the fact.

This also matters for retention: bronze partitions by `toDate(Timestamp)` with
`ttl_only_drop_parts`, so a wrong or attacker-chosen timestamp changes when a
part expires.

## Schema ownership

**`create_schema: true` cannot work with a checked-in materialized view.** The
exporter creates `otel_logs` lazily, on its first successful export. A view
selecting `FROM otel_logs` therefore cannot be applied on a fresh deploy:

```
Code: 60. DB::Exception: Unknown table expression identifier
'ssf_freshtest.otel_logs' (UNKNOWN_TABLE)
```

Worse, ClickHouse fixes TTL at creation time, so bronze's retention could never
be retrofitted by editing the collector config afterwards. The repository now
owns both tiers (`deploy/clickhouse/migrations/`) and the exporter runs with
`create_schema: false`. The standing cost is a constraint: every column the
exporter names in its INSERT must exist in `000_otel_logs.sql`, so a collector
image bump needs that DDL diffed against a `create_schema: true` scratch stack.

**The ClickHouse entrypoint ignores `CLICKHOUSE_DB` for `.sql` files.** This one
cost the most time. `/docker-entrypoint-initdb.d/*.sql` is piped through a
client built without a `--database` flag:

```sh
clickhouseclient=( clickhouse-client --multiquery --host 127.0.0.1 \
  --port "$NATIVE_PORT" -u "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" )
```

So migrations placed at the top of the mount are created in `default` while the
collector writes to `$CLICKHOUSE_DB` — the tables exist, and every export fails
with `UNKNOWN_TABLE`. The failure is invisible in the init logs, which cheerfully
report `running /docker-entrypoint-initdb.d/000_otel_logs.sql`. Migrations
consequently live in a `migrations/` subdirectory (which the entrypoint ignores)
applied by `apply.sh`, which sets the database explicitly.

Also note initdb runs **only** on an empty data directory. Every existing
deployment needs the manual apply after any migration is added.

## Privacy behaviour

**OTLP has three attribute namespaces, not two:** resource, instrumentation
scope, and log record. They are filtered independently, and a `keep_keys` on one
does nothing for the others.

**`Resource.create()` silently widens what you ship.** It merges
`OTEL_RESOURCE_ATTRIBUTES` and `OTEL_SERVICE_NAME` from the environment and adds
`telemetry.sdk.*` plus a per-process `service.instance.id`. With a hostile
environment we got content-shaped keys straight into ClickHouse, including
`net.peer.ip` — a key the log-attribute allowlist explicitly rejects:

```
OTEL_RESOURCE_ATTRIBUTES="ssf.leaked.source_text=...,net.peer.ip=10.1.2.3"
  -> net.peer.ip = 10.1.2.3
  -> ssf.leaked.source_text = Guten Tag Herr Mueller
```

The gateway now uses `Resource(attributes=...)`, which inherits nothing, and the
collector applies `keep_keys` to the resource namespace as a second line.

**`error_mode: ignore` inverts an allowlist.** A skipped OTTL statement does not
drop the record — it lets it continue with its **original** body and attributes.
A privacy processor set to `ignore` fails open precisely when it matters. Both
processors are `propagate`.

**Open item — the scope namespace is unfiltered.** `ScopeAttributes`,
`ScopeName`, `ScopeVersion` and the `*SchemaUrl` columns are neither emptied nor
key-filtered, and bronze stores them. SSF's own code cannot put content there
(the scope is set once, to the literal `ssf.quality`), and a security review
judged this non-exploitable — the data is write-only, surfaced in no dashboard
or API, absent from silver, and expires in 7 days. It is nonetheless a gap in a
control we describe as fail-closed, and closing it is a two-line OTTL change
plus a test assertion.

## Failure behaviour

**`outcome: "emitted"` does not mean delivered — it means queued.** This is the
most misleading thing we found, and we only found it by stopping the collector
mid-demo. `emit_probe` hands the record to the SDK's `BatchLogRecordProcessor`
queue, which accepts it without contacting anything. The HTTP export happens
later, on a background thread. So with `otel-collector` **stopped**, the
endpoint still answered:

```
HTTP status: 200
{"event_id":"787bce3a-...","mode":"probe","outcome":"emitted"}
```

**A collector outage does not surface as `export_failed`.** That counter label
fires only when `logger.emit()` raises synchronously — a shut-down provider or a
full queue. A network or DNS failure cannot reach it, because it happens after
`emit_probe` has already returned. The real signal is an SDK warning in the
gateway log, which is content-free:

```
WARNING Transient error HTTPConnectionPool(host='otel-collector', port=4318):
Max retries exceeded ... Failed to resolve 'otel-collector' ...
encountered while exporting logs batch, retrying in 1.20s.
```

**Short outages are recovered, not lost.** The SDK's OTLP exporter retries with
backoff. We stopped the collector, emitted a probe, restarted the collector, and
the row still landed — all four events from that sequence appear in
`quality_events`. "Lossy by design" is therefore about *sustained* failure
(retry budget exhausted, or queue overflow at 2048), not about a restart.

**An `event_id` is not evidence of a row.** The endpoint returns one on every
path except `disabled`. The only proof is a query against `quality_events`, and
only after the batch windows have elapsed.

**A signature mismatch masquerades as an export failure.** Because the emitter
catches `Exception` around the exporter call, a `TypeError` from a wrong-arity
exporter is counted as `export_failed` and logged as an export problem. We hit
this for real mid-implementation. `exc_info=True` on that warning is what makes
it diagnosable.

**A ClickHouse outage behind a healthy collector is invisible to the gateway
entirely.** The collector accepts the record, queues it (`sending_queue`,
`queue_size: 1000`) and retries for `max_elapsed_time: 300s`. Nothing about that
reaches the gateway's counter or the HTTP response.

**Overflow drops are not in our counter.** The bounded queue is the SDK's
`BatchLogRecordProcessor` (`max_queue_size`, default 2048). It drops silently on
overflow, visible only in SDK/collector internals — so
`ssf_quality_telemetry_events_total` is an emitter-side count, not a delivery
count. Telemetry is lossy by design; there is no Outbox and no acknowledged
write.

**An unparseable mode used to be fatal.** `TelemetryMode(os.environ.get(...))`
raised inside the FastAPI lifespan, so `SSF_QUALITY_TELEMETRY_MODE=enabled` — a
plausible operator guess — aborted the entire gateway's startup. Parsing now
falls back to `disabled` with a warning.

## Operational

**The collector image is distroless.** No `/bin/sh`, no `wget`, no `curl`, so a
compose `healthcheck` cannot probe it from inside the container. The
`health_check` extension on port 13133 is the only health signal, and it has to
be queried from another container on the network. A mis-configured collector
exits at startup and `restart: always` loops it, so "container restarting" means
config, not pipeline.

**`otelcol-contrib validate` is a real gate.** It parses OTTL statements and
component wiring, not just YAML — it rejects `keep_keyz`, `resource.attribute`
(singular), and pipeline references to undeclared processors. Cheaper and
stricter than asserting on the config's text.

**Unprefixed OTTL paths are silently rewritten.** `set(body, "")` is accepted
but logged as `one or more paths were modified to include their context prefix`
and rewritten to `set(log.body, "")`. The config uses the explicit prefixes.

**ClickHouse's built-in `/play` UI is the fastest way to inspect rows.** The
service publishes no host port, but the container IP is routable from a Linux
host, so no compose change is needed — see the runbook.

## What this does not tell us

- Nothing about production volume, cardinality, or cost. One event type, one
  row per deliberate call.
- Nothing about aggregate correctness or the gold tier — both deferred.
- Nothing about behaviour under sustained load or collector restart mid-batch.
- Nothing about production behaviour. The `otel-collector` service is defined
  and digest-pinned in `deploy/production/docker-compose.production.yml`, but
  the mode there is explicitly `disabled` and the service has never been
  started, so every observation above comes from the local stack only.
