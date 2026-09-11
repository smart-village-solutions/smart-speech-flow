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
# 002 sets these on the two application roles. Required rather than defaulted:
# a role created with a guessable password is worse than a failed start.
: "${SSF_FEEDBACK_APP_PASSWORD:?SSF_FEEDBACK_APP_PASSWORD must be set}"
: "${SSF_FEEDBACK_MAINTENANCE_PASSWORD:?SSF_FEEDBACK_MAINTENANCE_PASSWORD must be set}"

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
         --file "$migration"
done

echo "apply.sh: done"
