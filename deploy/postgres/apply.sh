#!/bin/sh
# Applies the SSF migrations to $POSTGRES_DB, in filename order.
#
# Runs in two contexts, both from inside the container:
#   - automatically, as /docker-entrypoint-initdb.d/apply.sh on a fresh volume
#   - by hand on an existing volume (production, after a pg_dump; see
#     docs/operations/runbooks/feedback-database-deployment.md):
#       production_compose exec -T ssf-postgres /docker-entrypoint-initdb.d/apply.sh
#
# Every statement is IF NOT EXISTS, so re-running is safe.
set -eu

: "${POSTGRES_DB:?POSTGRES_DB must be set}"
: "${POSTGRES_USER:?POSTGRES_USER must be set}"
# 002 sets these on the two application roles. Required rather than defaulted:
# a role created with a guessable password is worse than a failed start.
: "${SSF_FEEDBACK_APP_PASSWORD:?SSF_FEEDBACK_APP_PASSWORD must be set}"
: "${SSF_FEEDBACK_MAINTENANCE_PASSWORD:?SSF_FEEDBACK_MAINTENANCE_PASSWORD must be set}"
# 003 sets this on the authorised read role that serves Studio.
: "${SSF_FEEDBACK_READER_PASSWORD:?SSF_FEEDBACK_READER_PASSWORD must be set}"

migrations="$(dirname "$0")/migrations"

for migration in "$migrations"/*.sql; do
    echo "apply.sh: applying $migration to $POSTGRES_DB"
    # The passwords reach SQL as psql variables, quoted at the point of use as
    # :'app_password'. Never interpolated into the file, which would put them
    # in the image layer and in any error the statement raises.
    psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
         --set ON_ERROR_STOP=1 \
         --set database="$POSTGRES_DB" \
         --set app_password="$SSF_FEEDBACK_APP_PASSWORD" \
         --set maintenance_password="$SSF_FEEDBACK_MAINTENANCE_PASSWORD" \
         --set reader_password="$SSF_FEEDBACK_READER_PASSWORD" \
         --file "$migration"
done

# The recording archive has a database of its own (#614), so its dumps can
# keep a retention of their own. Skipped, not failed, while its password is
# unset: a host that has not rolled recording out yet keeps starting.
recording_db="ssf_recording"
if [ -n "${SSF_RECORDING_APP_PASSWORD:-}" ]; then
    echo "apply.sh: ensuring database $recording_db"
    psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
         --set ON_ERROR_STOP=1 \
         --set recording_db="$recording_db" <<'SQL'
SELECT format('CREATE DATABASE %I', :'recording_db')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'recording_db')\gexec
SQL
    for migration in "$(dirname "$0")"/recording/migrations/*.sql; do
        echo "apply.sh: applying $migration to $recording_db"
        psql --username "$POSTGRES_USER" --dbname "$recording_db" \
             --set ON_ERROR_STOP=1 \
             --set database="$recording_db" \
             --set app_password="$SSF_RECORDING_APP_PASSWORD" \
             --set retention_password="${SSF_RECORDING_RETENTION_PASSWORD:-}" \
             --set replica_password="${SSF_RECORDING_REPLICA_PASSWORD:-}" \
             --file "$migration"
    done
else
    echo "apply.sh: SSF_RECORDING_APP_PASSWORD is unset; skipping $recording_db"
fi

echo "apply.sh: done"
