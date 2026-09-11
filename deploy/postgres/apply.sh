#!/bin/sh
# Applies the SSF migrations to $POSTGRES_DB, in filename order.
#
# Runs in two contexts, both from inside the container:
#   - automatically, as /docker-entrypoint-initdb.d/apply.sh on a fresh volume
#   - by hand on an existing volume:
#       docker compose exec -T ssf-postgres /docker-entrypoint-initdb.d/apply.sh
#
# Every statement is IF NOT EXISTS, so re-running is safe.
set -eu

: "${POSTGRES_DB:?POSTGRES_DB must be set}"
: "${POSTGRES_USER:?POSTGRES_USER must be set}"

migrations="$(dirname "$0")/migrations"

for migration in "$migrations"/*.sql; do
    echo "apply.sh: applying $migration to $POSTGRES_DB"
    psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
         --set ON_ERROR_STOP=1 --file "$migration"
done

echo "apply.sh: done"
