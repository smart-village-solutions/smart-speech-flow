#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/production-common.sh
source "$SCRIPT_DIR/lib/production-common.sh"

backup_dir="${1:-}"
if [[ $# -ne 1 ]]; then
  printf 'Usage: %s <concrete-verified-backup-directory>\n' "$0" >&2
  exit 2
fi
"$SCRIPT_DIR/verify-production-backup.sh" "$backup_dir"

source_database="${SSF_CLICKHOUSE_DATABASE:-$(grep '^CLICKHOUSE_DB=' "$SSF_PROJECT_ROOT/.env" | head -n 1 | cut -d= -f2-)}"
if [[ ! "$source_database" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  printf 'CLICKHOUSE_DB must be a simple SQL identifier for restore drills.\n' >&2
  exit 1
fi

drill_suffix="$(date -u +%Y%m%d%H%M%S)"
container="ssf-restore-drill-${drill_suffix}"
target_database="ssf_restore_drill_${drill_suffix}"
clickhouse_image="clickhouse/clickhouse-server@sha256:2ef11bbe2e44ab7022f37ff3019b3f2125ed09e919ea6194660be6130b7ca4b7"

cleanup() {
  docker rm --force "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run --detach --pull=never --network none --name "$container" \
  --volume "$backup_dir:/backup:ro" "$clickhouse_image" >/dev/null

for _ in $(seq 1 30); do
  if docker exec "$container" clickhouse-client --query 'SELECT 1' >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$container" clickhouse-client --query 'SELECT 1' >/dev/null
docker exec "$container" clickhouse-client --query \
  "RESTORE DATABASE \`${source_database}\` AS \`${target_database}\` FROM File('/backup/clickhouse-native-backup.zip')"
docker exec "$container" clickhouse-client --query \
  "EXISTS DATABASE \`${target_database}\`" | grep -qx 1
printf 'Isolated ClickHouse restore drill passed for %s.\n' "$backup_dir"
