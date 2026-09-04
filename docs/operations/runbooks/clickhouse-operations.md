# ClickHouse Operations Runbook

## Scope and Security Boundary

ClickHouse is SSF's internal analytical database. It is reachable only through
the Docker Compose network at clickhouse:8123. It has no host port, Traefik
route, or public SQL UI. Do not add ports, Traefik labels, or the insecure
CLICKHOUSE_SKIP_USER_SETUP setting.

ClickHouse now holds the quality telemetry schema: three medallion tiers
(`otel_logs`, `quality_events`, `quality_events_daily`), owned by
`deploy/clickhouse/` and described under Quality Telemetry below. They are
included in the backup procedure. Whether the gateway *sends* events depends on
`SSF_QUALITY_TELEMETRY_MODE`, which is `disabled` in production until an
operator completes the enablement steps.

ClickHouse must contain only pseudonymised quality metadata, never recordings,
source text, transcripts, translations, IP addresses, or raw error messages.

## Prerequisites

Set these untracked .env values before the first start:

    CLICKHOUSE_DB=ssf_analytics
    CLICKHOUSE_USER=ssf_telemetry
    CLICKHOUSE_PASSWORD=use_a_unique_strong_password

Generate a password without adding it to a tracked file:

    openssl rand -base64 32

## Start and Verify

Start only ClickHouse. This does not recreate SSF application services:

    docker compose up -d clickhouse
    docker compose ps clickhouse

Wait for the service to become healthy, then verify HTTP health and authenticated
database access. The shell expands credentials inside the container, so they do
not appear in the host command or shell history:

    docker compose exec -T clickhouse wget -qO- http://localhost:8123/ping
    docker compose exec -T clickhouse sh -ec 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --query "SELECT version()"'

Expected output is Ok. for the health check and one ClickHouse version. For
diagnostics, use:

    docker compose logs --tail=100 clickhouse
    docker compose exec -T clickhouse sh -ec 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --query "SELECT name FROM system.databases"'

Confirm that no host port is published:

    docker inspect "$(docker compose ps -q clickhouse)" --format '{{json .HostConfig.PortBindings}}'

The command must return `{}`, which proves that Docker has no host-port binding.

## Backup and Restore

Take a logical backup before every ClickHouse upgrade and include the encrypted
archive in the existing SSF backup rotation. This infrastructure change creates
no table, so these instructions apply only after a later schema change.

Export an approved analytical table in Native format. Set backup_database and
backup_table to the approved schema values and use a UTC timestamp:

    backup_database=ssf_analytics
    backup_table=quality_events
    backup_timestamp=$(date -u +%Y%m%dT%H%M%SZ)
    mkdir -p "backups/clickhouse/$backup_timestamp"
    docker compose exec -T clickhouse sh -ec 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --query "SELECT * FROM '$backup_database.$backup_table' FORMAT Native"' | gzip > "backups/clickhouse/$backup_timestamp/$backup_table.native.gz"

Record the image version, database, table, UTC timestamp, checksum, and
successful restore-verification result with the archive. Restrict backup access
and retain it only according to the approved policy.

Never restore directly over production. Restore into a temporary database,
compare the row count with the source, then delete the temporary database after
verification:

    restore_database=ssf_restore_check
    gzip -dc "backups/clickhouse/<timestamp>/$backup_table.native.gz" | docker compose exec -T clickhouse sh -ec 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --query "INSERT INTO '$restore_database.$backup_table' FORMAT Native"'
    docker compose exec -T clickhouse sh -ec 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --query "SELECT count() FROM '$restore_database.$backup_table'"'
    docker compose exec -T clickhouse sh -ec 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --query "DROP DATABASE IF EXISTS '$restore_database'"'

## Upgrade and Rollback

1. Confirm a successful backup and restore verification.
2. Review the desired fixed image tag and the ClickHouse release notes.
3. Update the pinned image tag in docker-compose.yml through a reviewed change.
4. Apply only ClickHouse and verify health and authenticated SQL:

       docker compose pull clickhouse
       docker compose up -d --no-deps clickhouse
       docker compose ps clickhouse

5. If verification fails, restore the previous pinned image and recreate only
   ClickHouse. Do not run docker compose down -v and do not remove the
   clickhouse-data volume:

       docker compose up -d --no-deps --force-recreate clickhouse

## Quality Telemetry

The API Gateway emits allowlisted quality events over OTLP/HTTP to an
internal-only `otel-collector` service, which writes them into ClickHouse. See
`openspec/changes/add-clickhouse-quality-telemetry/design.md` for the full
design.

### What leaves the gateway

No source text, transcript, translation, audio, audio URL, IP address, session
id, raw error, or debug payload is among the declared values. The envelope, on
every event:

| Field | Carried as |
| --- | --- |
| Event type | top-level OTLP `event_name` |
| Event id | log attribute `ssf.quality.event_id` |
| Schema version | log attribute `ssf.quality.schema_version` |
| Service name | resource attribute `service.name` |
| Service version | resource attribute `service.version` |
| Deployment environment | resource attribute `deployment.environment.name` |

And on `refinement_attempt` (mode `enabled` only), eight more — every one a
number or a closed enum except `model_ref`, which is operator-set configuration
constrained to a label charset with no whitespace:

| Field | Carried as | Shape |
| --- | --- | --- |
| Refiner role | `ssf.quality.refiner_role` | enum: primary (in-path), candidate (shadow) |
| Model | `ssf.quality.model_ref` | label token, max 64 chars |
| Outcome | `ssf.quality.refinement_outcome` | enum: success, error, skipped_overload, submission_failed |
| Latency | `ssf.quality.refinement_latency_ms` | integer |
| Changed | `ssf.quality.refinement_changed` | enum: true, false |
| Source language | `ssf.quality.source_lang` | language code, else `und` |
| Target language | `ssf.quality.target_lang` | language code, else `und` |
| Error | `ssf.quality.error_code` | enum from the error taxonomy |

And on `translation_message` (mode `enabled` only), one row per processed
message, thirteen more. Every one is a number, a closed enum or an opaque
reference — there is no `model_ref` equivalent here, because nothing on a
message row is operator-set configuration:

| Field | Carried as | Shape |
| --- | --- | --- |
| Session reference | `ssf.quality.session_ref` | 32 hex chars, keyed HMAC (see below) |
| Direction | `ssf.quality.direction` | enum: admin_to_customer, customer_to_admin, unknown |
| Input mode | `ssf.quality.input_mode` | enum: audio, text, unknown |
| Source language | `ssf.quality.source_lang` | language code, else `und` |
| Target language | `ssf.quality.target_lang` | language code, else `und` |
| Terminal outcome | `ssf.quality.terminal_outcome` | enum: success, failure |
| Failed stage | `ssf.quality.failed_stage` | enum: none, admission, validation, asr, translation, refinement, tts, delivery, unknown |
| Error | `ssf.quality.error_code` | enum from the error taxonomy |
| Total duration | `ssf.quality.total_duration_ms` | integer, whole request |
| ASR duration | `ssf.quality.asr_duration_ms` | integer, 0 on the text path |
| Translation duration | `ssf.quality.translation_duration_ms` | integer |
| Refinement duration | `ssf.quality.refinement_duration_ms` | integer, 0 when refinement is off |
| TTS duration | `ssf.quality.tts_duration_ms` | integer |

`session_ref` is an **HMAC-SHA256 keyed by
`SSF_QUALITY_TELEMETRY_SESSION_KEY`**, truncated to 128 bits. It is deliberately
not the `sha256(session_id)[:12]` the gateway logs use: session ids are 32-bit,
so an unkeyed digest of one is reversible by enumerating the id space in
milliseconds, which is an encoding rather than a pseudonymisation. Rows that
carry no session id store 32 zeros, a value no HMAC produces.

Leaving the key unset does not fail: the gateway generates one per process and
logs a warning. The rows stay one-way, but they no longer group by session
across gateway restarts or replicas, so set it in production.

A message request that never became a message — an unknown session, an inactive
one, an unsupported content type — emits **nothing**. Counting those would put
requests the gateway declined into the denominator of every success ratio built
on this event.

And on `session_lifecycle` (mode `enabled` only), one row per session
transition, four more. Every field already exists on the `Session` dataclass:

| Field | Carried as | Shape |
| --- | --- | --- |
| Session reference | `ssf.quality.session_ref` | the same keyed HMAC as the message event |
| Phase | `ssf.quality.lifecycle_phase` | enum: created, activated, terminated |
| Termination reason | `ssf.quality.termination_reason` | enum: none, manual_admin_termination, manual_termination, new_session_created, session_timeout, system_cleanup, other |
| Session duration | `ssf.quality.session_duration_ms` | integer, 0 until the session ends |
| Messages carried | `ssf.quality.message_count` | integer — a count, never the messages |

`SessionManager.terminate_session` takes its `reason` as a free-form `str`, so
anything the gateway does not already name lands as `other`. It is never stored
verbatim; that is what keeps the reason from becoming a free-text channel into
a store with no free-text kind.

`session_ref` is derived identically on both events, which is what makes
"messages per session" and "sessions that carried no message" computable
without a join key the pipeline would otherwise have to invent.

`ALLOWED_ATTRIBUTES` in `services/api_gateway/quality_telemetry.py` is the
single manifest. It declares a *value shape* per key, not just a key, and there
is deliberately no free-text kind to declare — so an `error_code` carrying a
raw upstream message is rejected as firmly as an unknown key would be. Widening
it means opening six places that must agree; the tests fail until they do.

OTLP also carries protocol fields the gateway does not choose: the record
`Timestamp` (set from the event's own emission time), `ScopeName`
(`ssf.quality`), and empty trace/span/severity fields. They are stored in the
bronze table's typed columns.

OTLP has **three** independent attribute namespaces -- resource, instrumentation
scope, and log record -- and a `keep_keys` on one does nothing for the others.
Two of them are allowlisted, in two independent places:

- The gateway builds its resource with `Resource(attributes=...)`, **not**
  `Resource.create(...)`. The latter merges `OTEL_RESOURCE_ATTRIBUTES` and
  `OTEL_SERVICE_NAME` from the environment and adds `telemetry.sdk.*` plus a
  per-process `service.instance.id` — none of which the collector's log
  allowlist would filter, because resource attributes are a separate namespace.
- The collector's `transform/allowlist` empties the body and applies
  `keep_keys` to the log and resource namespaces, and `filter/quality_only`
  drops any record that carries no `ssf.quality.event_id` rather than rewriting
  it.

The scope namespace is **not** filtered: `ScopeAttributes`, `ScopeVersion` and
the `*SchemaUrl` columns are stored as received. SSF's own code cannot put
content there -- the scope is set once, to the literal `ssf.quality` -- so this
affects only a rogue sender that already has a foothold on the docker network,
writing into a table nothing reads. It is tracked as an open item in
[the probe findings](../clickhouse-telemetry-probe-findings.md).

`error_mode` on both processors must stay `propagate`. With `ignore`, a failing
statement is skipped and the record continues **with its original body and
attributes** — the guard becomes a no-op exactly when it matters.

`tests/integration/test_quality_telemetry_end_to_end.py` posts raw OTLP
carrying a body plus content-bearing log and resource attributes, and asserts
none of it is stored.

### Kill switch

`SSF_QUALITY_TELEMETRY_MODE` accepts exactly `disabled` (the default), `probe`
or `enabled`. When disabled, no SDK provider is built, no event is constructed,
and no export is attempted.

| Mode | SDK provider | Admin probe | Pipeline events |
| --- | --- | --- | --- |
| `disabled` | not built | reports `disabled` | none |
| `probe` | built | emits | **none** |
| `enabled` | built | emits | `refinement_attempt`, `translation_message`, `session_lifecycle` |

`probe` deliberately emits no pipeline events. It is a pure transport check, so
an operator can prove the path end to end without switching on production event
volume — and so a deployment already running `probe` does not silently start
emitting real events merely by being upgraded.

Any other value logs a warning and falls back to `disabled`. It never stops the
gateway from serving translations — telemetry is optional, the gateway is not.

The same applies to the SDK's own `OTEL_EXPORTER_OTLP_*` variables, which the
exporter parses itself and rejects strictly: `OTEL_EXPORTER_OTLP_TIMEOUT=10s` is
a `ValueError`, because it wants bare seconds. Rather than crashloop the
gateway, exporter setup failure logs
`Quality telemetry disabled: exporter setup failed (...)` to stderr and reports
`disabled` — so an operator who expected `probe` and sees `"mode": "disabled"`
from the probe endpoint should read `docker compose logs api_gateway` for that
line before suspecting the collector.

### Applying the schema

`deploy/clickhouse/` owns **both** medallion tiers, and the collector runs with
`create_schema: false`. Applying them is not optional: without it
`quality_events` does not exist and every query below fails.

- **Fresh volume:** the `clickhouse` service mounts `deploy/clickhouse` at
  `/docker-entrypoint-initdb.d`, so `apply.sh` runs on first initialisation,
  before the collector's first export.
- **Existing volume:** `/docker-entrypoint-initdb.d` runs *only* when the data
  directory is empty, so apply them by hand after any upgrade that adds a
  migration:

      docker compose exec -T clickhouse /docker-entrypoint-initdb.d/apply.sh

  Every statement is `IF NOT EXISTS`, so re-running is safe. The materialized
  view is not `POPULATE`: it projects only rows inserted after it exists. Rows
  already in bronze need a manual backfill (`INSERT INTO quality_events SELECT
  ... FROM otel_logs`) using the view's own SELECT.

The migrations live in `deploy/clickhouse/migrations/`, not at the top of the
mount, and `apply.sh` is what runs them. This is load-bearing: the image's
entrypoint pipes bare `*.sql` files through a client with **no `--database`
flag**, so migrations placed at the top level are created in `default` while
the collector writes to `$CLICKHOUSE_DB` — the tables exist, and every export
fails with `UNKNOWN_TABLE`.

**On a collector image bump**, diff `deploy/clickhouse/migrations/000_otel_logs.sql`
against a `create_schema: true` scratch stack's `SHOW CREATE TABLE otel_logs`.
Every column the exporter names in its INSERT must exist, or all exports fail.
`tests/integration/test_quality_events_schema_apply.py` pins that column list.

### Enabling in production

Production runs `docker compose` on the host from a git checkout, so the config
files below arrive with `git pull`. The repository already contains everything
that can be committed:

- the `otel-collector` service in `deploy/production/docker-compose.production.yml`,
  digest-pinned with `pull_policy: never` like every other production service
- `../../deploy/clickhouse` mounted at `/docker-entrypoint-initdb.d` on `clickhouse`
- `'9000'` added to `clickhouse`'s `expose` list, the port the collector uses
- every required variable documented in `deploy/production/production.env.example`

`SSF_QUALITY_TELEMETRY_MODE` defaults to `disabled`, so **merging changes nothing
in production**. The steps below are what turns it on, and they must run in this
order: the collector exporting before the schema exists produces
`UNKNOWN_TABLE`, retries for 300s, then drops the events.

All commands run on the production host from the repository root. `PC` is the
project's own compose invocation (see `scripts/lib/production-common.sh`):

    PC="docker compose --project-name ssf-backend --env-file .env \
        --file deploy/production/docker-compose.production.yml"

**1. Pull the deployment configuration.**

    git pull --ff-only

Nothing works before this: the collector's config and the migrations are
bind-mounted from the checkout.

**2. Pre-load the collector image.** `pull_policy: never` means a missing image
fails the service rather than downloading it.

    docker pull otel/opentelemetry-collector-contrib@sha256:1f2c54a30e713fac6b3ae77a1ec84010c2007e29ced8ec666214fc2f6739c1cc

**3. Check the environment.** `CLICKHOUSE_DB`, `CLICKHOUSE_USER` and
`CLICKHOUSE_PASSWORD` are already required by the running stack. Add the
telemetry variables, leaving the mode off for now:

    SSF_QUALITY_TELEMETRY_MODE=disabled
    SSF_OTLP_LOGS_ENDPOINT=http://otel-collector:4318/v1/logs
    SSF_QUALITY_TELEMETRY_SESSION_KEY=<openssl rand -hex 32>
    SSF_RELEASE_VERSION=<deployed git sha>
    SSF_DEPLOYMENT_ENV=production

`SSF_RELEASE_VERSION` lands in `quality_events.service_version`; use the same
sha as the deployed `prod-<sha>` image tags or the column is useless.

`SSF_QUALITY_TELEMETRY_SESSION_KEY` keys the HMAC behind `session_ref`. Generate
it once and keep it: **changing it re-pseudonymises every future row**, so
sessions before and after the change never group together. Treat it as a
secret — it is what stops a 32-bit session id space being enumerated against
the stored references. It has no effect while the mode is `disabled` or
`probe`, so setting it now costs nothing.

**4. Recreate ClickHouse** to pick up the new mount and exposed port. The named
volume is untouched, so no data is lost.

    $PC up -d --no-deps --force-recreate clickhouse
    $PC exec -T clickhouse wget -qO- http://localhost:8123/ping

**5. Apply the migrations.** `/docker-entrypoint-initdb.d` runs **only** on an
empty data directory, and production's volume already has data — so this step
is mandatory and will not happen on its own:

    $PC exec -T clickhouse /docker-entrypoint-initdb.d/apply.sh

Every statement is `IF NOT EXISTS`; re-running is safe.

**6. Confirm both tiers exist** before anything exports:

    $PC exec -T clickhouse sh -ec 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --database "$CLICKHOUSE_DB" --query "SELECT name FROM system.tables WHERE database = currentDatabase() ORDER BY name"'

Expect exactly `otel_logs`, `quality_events`, `quality_events_daily`,
`quality_events_daily_mv`, `quality_events_mv`. Do not continue if any is
missing.

**7. Start the collector** and confirm it came up clean:

    $PC up -d otel-collector
    $PC logs --tail=50 otel-collector
    $PC exec -T api_gateway python -c "import urllib.request; print(urllib.request.urlopen('http://otel-collector:13133/', timeout=5).status)"

Expect `200`. A collector that keeps restarting means the config, not the
pipeline — it exits on a bad config and `restart: unless-stopped` loops it.

**8. Turn the probe on.** Set `SSF_QUALITY_TELEMETRY_MODE=probe` in `.env`, then:

    $PC up -d --no-deps --force-recreate api_gateway
    $PC logs --tail=20 api_gateway | grep "Quality telemetry ready"

Expect `Quality telemetry ready (mode=probe)`.

**9. Verify end to end.** Call the probe with an admin token, then read the row
back after ~10s (two batch stages in series: the gateway SDK's 1s log batch
delay, then the collector's 5s `batch` timeout, so ~6s worst case for a single
event — ~10s is the safe wait):

    curl -s -X POST https://ssf.smart-village.solutions/api/admin/telemetry/probe \
      -H "Authorization: Bearer <admin token>"

    $PC exec -T clickhouse sh -ec 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --database "$CLICKHOUSE_DB" --query "SELECT event_id, service_version, deployment_env, emitted_at_utc FROM quality_events FINAL ORDER BY emitted_at_utc DESC LIMIT 3"'

`outcome: "emitted"` alone is **not** proof — it means queued in-process. The
row is the proof. If it never arrives, check
`$PC logs api_gateway | grep -i transient` for an SDK export warning.

**10. Update the audit record.** `deploy/production/known-good-images.lock` is
captured from the running containers, so refresh it after the deploy and commit
the result — it should now list `otel-collector`.

**11. Turn real pipeline events on (optional, and separate).** Steps 1-10 leave
the gateway on `probe`, which emits no pipeline events. Before switching to
`enabled`, confirm migrations `002`, `003` and `004` have been applied — they
are what give `quality_events` its typed columns, and `initdb` does **not**
re-run on a volume that already has data:

    $PC exec -T clickhouse sh -ec 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --database "$CLICKHOUSE_DB" --query "SELECT name FROM system.tables WHERE database = currentDatabase() ORDER BY name"'

Expect `otel_logs`, `quality_events`, `quality_events_daily`,
`quality_events_daily_mv`, `quality_events_mv`. If the gold tier is missing,
re-run `apply.sh` (step 5) — it is idempotent.

The table list does not distinguish `002` from `003` and `004`, because those
two only add columns. Check them directly:

    $PC exec -T clickhouse sh -ec 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --database "$CLICKHOUSE_DB" --query "SELECT count() FROM system.columns WHERE database = currentDatabase() AND table = '"'"'quality_events'"'"'"'

Expect `30`. Fewer means a migration has not been applied; re-run `apply.sh`.

**Order matters.** Emitting events while any of `002`-`004` is unapplied writes rows
whose typed columns are all defaults, and those rows cannot be repaired: the
attributes were dropped at projection time and bronze expires after 7 days. The
dashboard's `Rows Missing Typed Fields` panel exists to catch exactly this and
should read zero.

Then:

    SSF_QUALITY_TELEMETRY_MODE=enabled
    $PC up -d --no-deps --force-recreate api_gateway
    $PC logs --tail=20 api_gateway | grep "Quality telemetry ready"

Expect `Quality telemetry ready (mode=enabled)`.

`refinement_attempt` is emitted from the **in-path** refiner, so production's
default `LLM_REFINEMENT_MODE=primary_only` produces rows with
`refiner_role=primary`. Rows only stop entirely at
`LLM_REFINEMENT_MODE=disabled`, where no refinement happens and there is no
attempt to record. `shadow_compare` additionally produces
`refiner_role=candidate` rows, which is what makes the `Latency p95 by Model`
panel show two series instead of one.

`session_lifecycle` is emitted from the session manager, so it appears as soon
as an admin opens a session — before any message exists. It is the first
evidence that `enabled` took effect.

`translation_message` is emitted once per processed message regardless of
refinement configuration, so it is the next to appear and the one to check if
the message panels stay empty. **Expect roughly one row per message** —
the volume is the message rate, not a multiple of it. At the rates this
deployment sees that is negligible against the 30-day silver TTL, but it is the
first event whose volume scales with traffic rather than with operator action,
so watch `Rows Missing Typed Fields` and the writer-health panels for the first
day.

#### Rolling back

Set `SSF_QUALITY_TELEMETRY_MODE=disabled`, recreate `api_gateway`, and the
gateway stops constructing an SDK provider entirely. Then `$PC stop
otel-collector` if you want the service down. The tables can stay; bronze
expires after 7 days and silver after 30, and neither is read by anything else.

### Retention

Bronze `otel_logs` keeps 7 days, silver `quality_events` keeps 30 days, and gold
`quality_events_daily` keeps 13 months. All three TTLs live in
`deploy/clickhouse/`. ClickHouse fixes TTL at table-creation time, so a TTL
added to the DDL later does not reach an existing table — check and retrofit:

    docker compose exec -T clickhouse sh -ec 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --database "$CLICKHOUSE_DB" --query "SHOW CREATE TABLE otel_logs"'
    docker compose exec -T clickhouse sh -ec 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --database "$CLICKHOUSE_DB" --query "ALTER TABLE otel_logs MODIFY TTL toDateTime(Timestamp) + INTERVAL 7 DAY"'

#### Verifying retention is actually running

A TTL in the DDL is a claim; the oldest surviving row is the evidence. The
`Retention Verification` panel on the SSF Telemetry dashboard shows this, and
the same query by hand:

    docker compose exec -T clickhouse sh -ec 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --database "$CLICKHOUSE_DB" --query "
      SELECT '\''quality_events'\'' AS tier, min(emitted_at_utc) AS oldest, dateDiff('\''day'\'', min(emitted_at_utc), now()) AS age_days FROM quality_events FINAL
      UNION ALL
      SELECT '\''quality_events_daily'\'', toDateTime(min(event_date)), dateDiff('\''day'\'', toDateTime(min(event_date)), now()) FROM quality_events_daily"'

`age_days` materially above the tier's window means expiry is not running.
Confirm the TTL is on the table at all before anything else — a tier created
without one cannot be given one, only recreated:

    docker compose exec -T clickhouse sh -ec 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --database "$CLICKHOUSE_DB" --query "SHOW CREATE TABLE quality_events_daily"' | grep -i ttl

Expect `toIntervalMonth(13)`. TTL removal happens during background merges, so
a recently-expired partition can survive briefly; `OPTIMIZE TABLE ... FINAL`
forces it if you need a definitive answer.

### Writer-health alerts

`monitoring/alert_rules.yml` group `ssf-quality-telemetry`. Every rule is a
**warning** by design: telemetry is optional and a dead collector cannot affect
translation, sessions or WebSocket delivery, so none of this should page anyone.

The alerts read two sources, because neither alone can see the whole path:

- `ssf_quality_telemetry_events_total` from the gateway — what was *queued*.
- `otelcol_*` from the collector's own `:8888` endpoint — what *arrived*.

`QualityTelemetryEventsLostBeforeCollector` is the difference between them, and
it exists because the OTel SDK's `BatchLogRecordProcessor` drops on queue
overflow and reports that **nowhere** — not in the gateway's counter, not as an
`export_failed` outcome. The gap is the only measurement of it. Record the
observed rate before deciding whether a bounded acknowledged writer (task 2.1)
is real work: if it stays at zero at production volume, the SDK's 2048-event
queue is adequate and that is a finding, not a gap.

`QualityTelemetryAttributeRejected` is different in kind from the rest. It fires
without a delay because it means the six places that must agree about a field
have diverged, which loses data silently — a code defect, not a transient.

The collector's internal metrics are bound to `0.0.0.0:8888` in
`monitoring/otel-collector-config.yaml`; the default binds localhost, which no
other container can reach. The port is `expose`d, never published.

### Verifying the pipeline

`POST /api/admin/telemetry/probe` returns an `outcome` field. **Neither the
`event_id` nor `outcome: "emitted"` proves a row exists.** `emitted` means the
record was accepted into the SDK's in-process queue; the HTTP export happens
later on a background thread. A probe returns `emitted` even with
`otel-collector` stopped.

The only proof is a query against `quality_events`, after both batch windows
have elapsed (allow ~10s). If a row never appears, look for an SDK export
warning in `docker compose logs api_gateway` — a collector or ClickHouse outage
surfaces there, **not** as `outcome: "export_failed"`, which fires only when the
emit call itself raises. Short outages recover on their own: the exporter
retries with backoff and the row lands late.

Read what actually arrived — `FINAL` is required, since `ReplacingMergeTree`
collapses duplicates only at merge time:

    docker compose exec -T clickhouse sh -ec 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --database "$CLICKHOUSE_DB" --query "SELECT event_id, event_type, service_name, emitted_at_utc FROM quality_events FINAL ORDER BY emitted_at_utc DESC LIMIT 10"'

Per-outcome counters are on the gateway's metrics endpoint as
`ssf_quality_telemetry_events_total{outcome=...}`, with one series per outcome:
`emitted`, `export_failed`, `dropped_disallowed`, and `disabled`. Every probe
increments exactly one of them, `disabled` included — a scrape showing no
series at all means the endpoint has never been called, not that telemetry
is off.

### Collector health

The collector image is distroless, so a compose `healthcheck` cannot run a
probe inside the container and there is none. The `health_check` extension on
port 13133 is the health signal; query it from another container on the network:

    docker compose exec -T api_gateway python -c "import urllib.request; print(urllib.request.urlopen('http://otel-collector:13133/', timeout=5).status)"

`docker compose logs otel-collector` is the other signal. A mis-configured
collector fails at startup and `restart: always` will loop it, so a container
that keeps restarting means the config, not the pipeline.

### Grafana Dashboard

Grafana reaches ClickHouse over the compose network only — `clickhouse:9000`,
native protocol — never through a host port or Traefik route. The
`grafana-clickhouse-datasource` plugin is installed at container start via
`GF_INSTALL_PLUGINS`, so it is not baked into the pinned image and requires
outbound internet access from the Grafana container the first time it starts
(or after the plugin volume is cleared).

The plugin version is pinned in both Compose files — `GF_INSTALL_PLUGINS=grafana-clickhouse-datasource 4.21.2`.
Grafana's entrypoint word-splits the value into `grafana cli plugins install
<id> <version>`, so the separator is a space, not a colon or an `@`. Pinning
matters because every production image is pinned by digest; an unpinned plugin
would let a restart install a version the dashboard was never verified against.
To upgrade, change the version in both files, clear
`monitoring/grafana/plugins/grafana-clickhouse-datasource`, recreate the
container, and confirm the startup log reports the version you asked for.

Open the dashboard at `http://localhost:3000` locally, or
`https://grafana-ssf.smart-village.solutions` in production, folder **SSF**,
dashboard **SSF Telemetry**. The datasource is provisioned as **ClickHouse**
(`uid: clickhouse-ssf`); `Save & test` on it must return `Data source is
working`.

**What it shows, and what fills it.** Three event types exist, and each fills a
different part of the dashboard:

| Event | Panels | Emitted when |
| --- | --- | --- |
| `telemetry_probe` | none — it is a transport check | `POST /api/admin/telemetry/probe`, in `probe` or `enabled` |
| `session_lifecycle` | the top four stats and the three panels below them | a session is created, activated or terminated, in `enabled` |
| `translation_message` | the next four stats and the four panels below those | every processed message, in `enabled` |
| `refinement_attempt` | `Refinement Attempts` through `Failures by Error Code`, and the gold-tier panel | every LLM refinement, in `enabled` |

The remaining panels — `Writer Health by Outcome`, `Events Lost Before The
Collector`, `Retention Verification` and `Rows Missing Typed Fields` — are about
the pipeline itself and fill in every mode.

ClickHouse panels query `quality_events FINAL` (required — see "Verifying the
pipeline" above) filtered with `$__timeFilter(emitted_at_utc)`, so the time
picker controls them. The gold-tier panel is the exception: it reads
`quality_events_daily`, which is keyed on a `Date`, so it takes
`$__dateFilter(event_date)` instead.

**An empty dashboard almost always means the mode, not the dashboard.** In
order:

1. `SSF_QUALITY_TELEMETRY_MODE` must be `enabled`. On `probe` every ClickHouse
   panel is correctly empty, because `probe` emits no pipeline events.
2. Check the time range. Probe and refinement events are sparse; message events
   follow real traffic, so an idle window is genuinely empty.
3. If `translation_message` rows exist but refinement panels are empty, that is
   `LLM_REFINEMENT_MODE=disabled` and not a fault.
4. `session_lifecycle` rows appear the moment an admin opens a session, before
   any message exists — so an empty session funnel with populated message
   panels means the gateway was restarted mid-session, not that sessions are
   uncounted.
5. Only then work backwards through "Verifying the pipeline" above.

**Gold-tier panels must filter on `event_type`.** The gold tier's latency
aggregates are the refinement attempt's; a `translation_message` row reaching it
contributes a correct daily count and a zero to every latency state. A gold
query without that filter averages a real population against a column of zeros.
`tests/test_grafana_clickhouse_datasource_configuration.py` enforces this.

Message stage latencies come from silver only, and read
`nullIf(<stage>_duration_ms, 0)`: a text message has no ASR stage and a run with
refinement off has no refinement stage, and both store `0`. Averaging those in
reports every stage as faster than it is.

Session duration and message count are read only from `lifecycle_phase =
'terminated'` rows, for the same reason: a `created` or `activated` row reports
zero because the session has not ended yet, not because it was empty. The
`Sessions That Carried No Message` panel is the one that counts genuinely empty
sessions — an admin opened one, a customer joined, and nothing was translated —
which nothing could measure before this event existed.

#### Enabling the dashboard in production

Merging is not enough. No new `.env` variables are needed — `CLICKHOUSE_DB`,
`CLICKHOUSE_USER` and `CLICKHOUSE_PASSWORD` are already required by the running
`clickhouse` and `otel-collector` services, and Grafana's provisioning
substitutes the same three. But the plugin and the datasource are read only at
Grafana startup, so the container must be recreated.

The dashboard JSON is the exception: the provider re-reads
`/var/lib/grafana/dashboards` every 30s (`updateIntervalSeconds: 30`), so
`ssf-telemetry.json` appears within half a minute of `git pull` on its own.

Using the same `PC` invocation as "Enabling in production" above:

**1. Pull, then recreate Grafana.**

    git pull --ff-only
    $PC up -d --no-deps --force-recreate grafana

**2. Confirm the pinned plugin installed.** This step needs outbound access to
grafana.com from the Grafana container — the plugin is not in the pinned image:

    $PC logs grafana | grep -i clickhouse-datasource

Expect `Downloaded and extracted grafana-clickhouse-datasource v4.21.2` on the
first start, then `Plugin registered`. On later starts the download is skipped
because the plugin is already on the bind mount.

**If egress is blocked**, install it without the network. `monitoring/grafana`
is a bind mount from the checkout, so the host filesystem *is* Grafana's plugin
directory:

    curl -L -o /tmp/ch.zip \
      https://grafana.com/api/plugins/grafana-clickhouse-datasource/versions/4.21.2/download
    unzip -q -d monitoring/grafana/plugins /tmp/ch.zip
    chown -R 472:472 monitoring/grafana/plugins/grafana-clickhouse-datasource
    $PC up -d --no-deps --force-recreate grafana

The archive unpacks to a single `grafana-clickhouse-datasource/` directory and
is about 75 MB (it ships binaries for every platform). Use `curl -L` with `GET`
— that endpoint rejects `HEAD`, so a `curl -I` probe returns 405 and tells you
nothing.

Grafana runs as uid 472; a plugin directory it cannot read is silently ignored.

**3. Confirm the datasource provisioned.**

    $PC logs grafana | grep "inserting datasource"

Expect `name=ClickHouse uid=clickhouse-ssf`. A `plugin not found` error here
means step 2 did not actually succeed.

**4. Confirm Grafana can reach ClickHouse** over the compose network:

    $PC exec -T grafana wget -qO- http://clickhouse:8123/ping

Expect `Ok.` This uses 8123 only as a reachability check; the datasource itself
uses the native protocol on 9000.

**5. Open the dashboard** and confirm a panel returns data. The schema must
already exist — steps 5 and 6 of "Enabling in production" above. A panel error
mentioning `UNKNOWN_TABLE` means the migrations were never applied.

## Incident Response

| Symptom | Immediate action |
| --- | --- |
| Container is unhealthy | Inspect docker compose logs --tail=100 clickhouse; verify disk space and credentials; do not expose port 8123. |
| Authentication fails | Confirm the .env user, database, and password match initial deployment; rotate credentials through reviewed maintenance. |
| Disk pressure | Stop future telemetry ingestion, take a backup, inspect system.parts, and follow the approved retention policy. |
| Suspected content or credential exposure | Stop the affected writer, preserve audit evidence, rotate credentials, and follow the SSF security incident procedure. |
| Failed upgrade | Roll back to the previous pinned image after a successful backup; retain the named volume for diagnosis and restore. |
| Collector unhealthy | Query the health_check endpoint and inspect docker compose logs --tail=100 otel-collector; telemetry loss does not affect translation; set SSF_QUALITY_TELEMETRY_MODE=disabled to stop emission. |

## References

- [ClickHouse Docker installation](https://clickhouse.com/docs/install/docker)
- [ClickHouse HTTP interface](https://clickhouse.com/docs/concepts/features/interfaces/http)
- [SSF Conversation Quality KPI Catalogue](../conversation-quality-kpis.en.md)
