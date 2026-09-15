#!/bin/sh
# Applies the medallion migrations to $CLICKHOUSE_DB, in filename order.
#
# The ClickHouse image's entrypoint runs bare *.sql files through a client with
# no --database flag, so they would land in `default` while the collector writes
# to $CLICKHOUSE_DB. Hence the migrations live in a subdirectory (which the
# entrypoint ignores) and this script applies them with the database set.
#
# Runs in two contexts, both from inside the container:
#   - automatically, as /docker-entrypoint-initdb.d/apply.sh on a fresh volume
#   - by hand on an existing volume:
#       docker compose exec -T clickhouse /docker-entrypoint-initdb.d/apply.sh
#
# Every statement is IF NOT EXISTS, so re-running is safe.
set -eu

: "${CLICKHOUSE_DB:?CLICKHOUSE_DB must be set}"
: "${CLICKHOUSE_USER:?CLICKHOUSE_USER must be set}"
: "${CLICKHOUSE_PASSWORD:?CLICKHOUSE_PASSWORD must be set}"

migrations="$(dirname "$0")/migrations"

for migration in "$migrations"/*.sql; do
    echo "apply.sh: applying $migration to $CLICKHOUSE_DB"
    clickhouse-client \
        --user "$CLICKHOUSE_USER" \
        --password "$CLICKHOUSE_PASSWORD" \
        --database "$CLICKHOUSE_DB" \
        --multiquery < "$migration"
done

echo "apply.sh: done"
