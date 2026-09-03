# ClickHouse Operations Runbook

## Scope and Security Boundary

ClickHouse is SSF's internal analytical database. It is reachable only through
the Docker Compose network at clickhouse:8123. It has no host port, Traefik
route, or public SQL UI. Do not add ports, Traefik labels, or the insecure
CLICKHOUSE_SKIP_USER_SETUP setting.

This infrastructure installation creates no analytical tables and sends no SSF
events to ClickHouse. A later approved change owns telemetry schemas and the
event writer. ClickHouse must contain only pseudonymised quality metadata, never
recordings, source text, transcripts, translations, IP addresses, or raw error
messages.

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

The API Gateway emits one allowlisted probe event over OTLP/HTTP to an
internal-only `otel-collector` service, which writes it into ClickHouse. See
`openspec/changes/add-clickhouse-quality-telemetry/design.md` for the full
design.

### What leaves the gateway

Six values are *declared* by the gateway. No source text, transcript,
translation, audio, audio URL, IP address, session id, raw error, or debug
payload is among them:

| Field | Carried as |
| --- | --- |
| Event type | top-level OTLP `event_name` (`telemetry_probe`) |
| Event id | log attribute `ssf.quality.event_id` |
| Schema version | log attribute `ssf.quality.schema_version` |
| Service name | resource attribute `service.name` |
| Service version | resource attribute `service.version` |
| Deployment environment | resource attribute `deployment.environment.name` |

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

`SSF_QUALITY_TELEMETRY_MODE` accepts exactly `disabled` (the default) or
`probe`. When disabled, no SDK provider is built, no event is constructed, and
no export is attempted.

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
    SSF_RELEASE_VERSION=<deployed git sha>
    SSF_DEPLOYMENT_ENV=production

`SSF_RELEASE_VERSION` lands in `quality_events.service_version`; use the same
sha as the deployed `prod-<sha>` image tags or the column is useless.

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

Expect exactly `otel_logs`, `quality_events`, `quality_events_mv`. Do not
continue if any is missing.

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

#### Rolling back

Set `SSF_QUALITY_TELEMETRY_MODE=disabled`, recreate `api_gateway`, and the
gateway stops constructing an SDK provider entirely. Then `$PC stop
otel-collector` if you want the service down. The tables can stay; bronze
expires after 7 days and silver after 30, and neither is read by anything else.

### Retention

Bronze `otel_logs` keeps 7 days, silver `quality_events` keeps 30 days. Both
TTLs live in `deploy/clickhouse/`. ClickHouse fixes TTL at table-creation time,
so a TTL added to the DDL later does not reach an existing table — check and
retrofit:

    docker compose exec -T clickhouse sh -ec 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --database "$CLICKHOUSE_DB" --query "SHOW CREATE TABLE otel_logs"'
    docker compose exec -T clickhouse sh -ec 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --database "$CLICKHOUSE_DB" --query "ALTER TABLE otel_logs MODIFY TTL toDateTime(Timestamp) + INTERVAL 7 DAY"'

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
