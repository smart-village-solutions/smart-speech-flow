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

## Incident Response

| Symptom | Immediate action |
| --- | --- |
| Container is unhealthy | Inspect docker compose logs --tail=100 clickhouse; verify disk space and credentials; do not expose port 8123. |
| Authentication fails | Confirm the .env user, database, and password match initial deployment; rotate credentials through reviewed maintenance. |
| Disk pressure | Stop future telemetry ingestion, take a backup, inspect system.parts, and follow the approved retention policy. |
| Suspected content or credential exposure | Stop the affected writer, preserve audit evidence, rotate credentials, and follow the SSF security incident procedure. |
| Failed upgrade | Roll back to the previous pinned image after a successful backup; retain the named volume for diagnosis and restore. |

## References

- [ClickHouse Docker installation](https://clickhouse.com/docs/install/docker)
- [ClickHouse HTTP interface](https://clickhouse.com/docs/concepts/features/interfaces/http)
- [SSF Conversation Quality KPI Catalogue](../conversation-quality-kpis.en.md)
