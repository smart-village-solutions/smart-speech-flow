#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/production-common.sh
source "$SCRIPT_DIR/lib/production-common.sh"

tier=daily
if [[ "${1:-}" == "--tier" ]]; then
  tier="${2:-}"
  shift 2
fi
if [[ $# -ne 0 ]] || [[ ! "$tier" =~ ^(daily|weekly|monthly)$ ]]; then
  printf 'Usage: %s [--tier daily|weekly|monthly]\n' "$0" >&2
  exit 2
fi

case "$tier" in
  daily) retention_count=7 ;;
  weekly) retention_count=4 ;;
  monthly) retention_count=12 ;;
esac

backup_root="${SSF_BACKUP_ROOT:-$SSF_PROJECT_ROOT/backups/$tier}"
timestamp="$(date -u +%Y%m%d_%H%M%S)"
final_dir="$backup_root/$timestamp"
mkdir -p "$backup_root"
staging_dir="$(mktemp -d "$backup_root/.staging-${timestamp}.XXXXXX")"
required=(
  keycloak-postgres.sql.gz
  redis.rdb
  clickhouse-native-backup.zip
  configuration.tar.gz
  environment.env
  git-revision.txt
  volumes/ssf-backend_audio-data.tar.gz
  volumes/ssf-backend_clickhouse-data.tar.gz
  volumes/ssf-backend_keycloak-postgres-data.tar.gz
  volumes/ssf-backend_ollama-data.tar.gz
  volumes/ssf-backend_redis-data.tar.gz
  volumes/prometheus-data.tar.gz
)

cleanup() {
  if [[ -d "$staging_dir" ]]; then
    rm -rf -- "$staging_dir"
  fi
}
trap cleanup EXIT

mkdir -p "$staging_dir/volumes"

production_compose exec -T keycloak-postgres sh -ec \
  'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  | gzip -c > "$staging_dir/keycloak-postgres.sql.gz"

production_compose exec -T redis redis-cli --rdb /tmp/ssf-backup.rdb >/dev/null
production_compose exec -T redis cat /tmp/ssf-backup.rdb > "$staging_dir/redis.rdb"

clickhouse_database="${SSF_CLICKHOUSE_DATABASE:-$(grep '^CLICKHOUSE_DB=' "$SSF_PROJECT_ROOT/.env" | head -n 1 | cut -d= -f2-)}"
if [[ ! "$clickhouse_database" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  printf 'CLICKHOUSE_DB must be a simple SQL identifier for native backups.\n' >&2
  exit 1
fi
production_compose exec -T clickhouse clickhouse-client --query \
  "BACKUP DATABASE \`${clickhouse_database}\` TO File('/tmp/ssf-clickhouse-backup.zip')"
production_compose exec -T clickhouse cat /tmp/ssf-clickhouse-backup.zip \
  > "$staging_dir/clickhouse-native-backup.zip"

tar -C "$SSF_PROJECT_ROOT" -czf "$staging_dir/configuration.tar.gz" \
  deploy/production monitoring letsencrypt models
install -m 0600 "$SSF_PROJECT_ROOT/.env" "$staging_dir/environment.env"
git -C "$SSF_PROJECT_ROOT" rev-parse HEAD > "$staging_dir/git-revision.txt"

for volume in \
  ssf-backend_audio-data \
  ssf-backend_clickhouse-data \
  ssf-backend_keycloak-postgres-data \
  ssf-backend_ollama-data \
  ssf-backend_redis-data \
  1980baddd3a6bd8bcade314d6f81d3716e73ae9bba6655b90d4179ff7b1990a7; do
  docker volume inspect "$volume" >/dev/null
  archive_name="$volume"
  if [[ "$volume" == 1980baddd3a6bd8bcade314d6f81d3716e73ae9bba6655b90d4179ff7b1990a7 ]]; then
    archive_name=prometheus-data
  fi
  docker run --rm --pull=never \
    --volume "$volume:/source:ro" \
    --volume "$staging_dir:/backup" \
    ssf-backup-helper:prod-e409a06 \
    tar -C /source -czf "/backup/volumes/${archive_name}.tar.gz" .
done

python3 - "$staging_dir/manifest.json" "${required[@]}" <<'PY'
import json
import sys
from datetime import datetime, timezone

path, *required = sys.argv[1:]
with open(path, "w", encoding="utf-8") as handle:
    json.dump(
        {
            "format": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "required": required,
        },
        handle,
        indent=2,
        sort_keys=True,
    )
    handle.write("\n")
PY

(cd "$staging_dir" && sha256sum manifest.json > manifest.sha256)
(cd "$staging_dir" && sha256sum "${required[@]}" > checksums.sha256)

"$SCRIPT_DIR/verify-production-backup.sh" "$staging_dir"
mv -- "$staging_dir" "$final_dir"
trap - EXIT
ln -sfn "$final_dir" "$backup_root/latest"
mapfile -t completed_backups < <(
  find "$backup_root" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort -r
)
for ((index = retention_count; index < ${#completed_backups[@]}; index++)); do
  candidate="${completed_backups[$index]}"
  if [[ "$candidate" =~ ^[0-9]{8}_[0-9]{6}$ ]]; then
    rm -rf -- "$backup_root/$candidate"
  fi
done
printf 'Production backup completed: %s\n' "$final_dir"
