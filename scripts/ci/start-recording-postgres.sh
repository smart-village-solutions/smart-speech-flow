#!/bin/sh
# Starts ssf-postgres for CI the way Compose starts it, mounting deploy/postgres
# so the real apply.sh runs the real migrations, and writes every role's URL
# and password to $GITHUB_ENV. A `services:` container cannot do that -- it
# starts before the checkout exists -- and the roles the migrations create are
# what the database tests are about.
#
#   GITHUB_ENV=<file> scripts/ci/start-recording-postgres.sh
#
# SSF_CI_POSTGRES_NAME and SSF_CI_POSTGRES_PORT (default ssf-postgres-ci, 5432)
# let it run beside another database locally.
set -eu

: "${GITHUB_ENV:?GITHUB_ENV names the file the URLs and passwords are written to}"
name="${SSF_CI_POSTGRES_NAME:-ssf-postgres-ci}"
port="${SSF_CI_POSTGRES_PORT:-5432}"
repo="$(cd "$(dirname "$0")/../.." && pwd)"

# Generated, never written into a file in the repository: a literal beside a
# PASSWORD name is a credential to a secret scanner, fake or not. The /+=@ are
# the characters that break a connection URL, which the tests keep fixed.
generated() { printf '%s/+=@' "$(openssl rand -hex 16)"; }
app_password="$(generated)"
maintenance_password="$(generated)"
reader_password="$(generated)"
recording_password="$(generated)"
retention_password="$(generated)"
replica_password="$(generated)"
owner_password="$(openssl rand -hex 16)"

host="127.0.0.1:$port"
{
  echo "SSF_FEEDBACK_DATABASE_URL=postgresql://ssf_feedback_app@$host/ssf"
  echo "SSF_FEEDBACK_DATABASE_PASSWORD=$app_password"
  echo "SSF_FEEDBACK_MAINTENANCE_DATABASE_URL=postgresql://ssf_feedback_maintenance@$host/ssf"
  echo "SSF_FEEDBACK_MAINTENANCE_DATABASE_PASSWORD=$maintenance_password"
  echo "SSF_FEEDBACK_READER_DATABASE_URL=postgresql://ssf_feedback_reader@$host/ssf"
  echo "SSF_FEEDBACK_READER_DATABASE_PASSWORD=$reader_password"
  echo "SSF_FEEDBACK_OWNER_DATABASE_URL=postgresql://ssf@$host/ssf"
  echo "SSF_FEEDBACK_OWNER_DATABASE_PASSWORD=$owner_password"
  echo "SSF_RECORDING_DATABASE_URL=postgresql://ssf_recording_app@$host/ssf_recording"
  echo "SSF_RECORDING_DATABASE_PASSWORD=$recording_password"
  echo "SSF_RECORDING_OWNER_DATABASE_URL=postgresql://ssf@$host/ssf_recording"
  echo "SSF_RECORDING_OWNER_DATABASE_PASSWORD=$owner_password"
  echo "SSF_RECORDING_RETENTION_DATABASE_URL=postgresql://ssf_recording_retention@$host/ssf_recording"
  echo "SSF_RECORDING_RETENTION_DATABASE_PASSWORD=$retention_password"
  echo "SSF_RECORDING_REPLICA_DATABASE_URL=postgresql://ssf_recording_replica@$host/ssf_recording"
  echo "SSF_RECORDING_REPLICA_DATABASE_PASSWORD=$replica_password"
} >> "$GITHUB_ENV"

docker run -d --name "$name" \
  -e POSTGRES_DB=ssf \
  -e POSTGRES_USER=ssf \
  -e POSTGRES_PASSWORD="$owner_password" \
  -e SSF_FEEDBACK_APP_PASSWORD="$app_password" \
  -e SSF_FEEDBACK_MAINTENANCE_PASSWORD="$maintenance_password" \
  -e SSF_FEEDBACK_READER_PASSWORD="$reader_password" \
  -e SSF_RECORDING_APP_PASSWORD="$recording_password" \
  -e SSF_RECORDING_RETENTION_PASSWORD="$retention_password" \
  -e SSF_RECORDING_REPLICA_PASSWORD="$replica_password" \
  -p "$host:5432" \
  -v "$repo/deploy/postgres:/docker-entrypoint-initdb.d:ro" \
  postgres:17.7-alpine >/dev/null

# TCP, not the socket: during the first start the image runs a temporary
# socket-only server while the migrations execute, so a socket probe reports
# ready before the roles exist.
ready=no
for _ in $(seq 1 60); do
  if docker exec "$name" pg_isready -h 127.0.0.1 -U ssf -d ssf >/dev/null 2>&1; then
    ready=yes
    break
  fi
  sleep 2
done
if [ "$ready" != yes ]; then
  echo "start-recording-postgres.sh: the database never accepted TCP connections" >&2
  docker logs "$name" >&2
  exit 1
fi

for migration in migrations/001_feedback.sql migrations/002_feedback_roles.sql \
  migrations/003_feedback_reader.sql migrations/004_feedback_dynamic.sql \
  recording/migrations/001_recording_keys.sql recording/migrations/002_recovery_ceremony.sql \
  recording/migrations/003_recording_archive.sql recording/migrations/004_recording_retention.sql \
  recording/migrations/005_recording_archive_access.sql \
  recording/migrations/006_recording_recovery_requests.sql \
  recording/migrations/007_recording_key_recovery.sql \
  recording/migrations/008_recording_resharing.sql; do
  if ! docker logs "$name" 2>&1 | grep -q "apply.sh: applying .*$migration"; then
    echo "start-recording-postgres.sh: $migration did not run" >&2
    docker logs "$name" >&2
    exit 1
  fi
done
echo "start-recording-postgres.sh: $name ready on $host"
