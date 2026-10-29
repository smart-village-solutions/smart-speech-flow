#!/usr/bin/env bash
# Daily dump of ssf_recording, kept 14 days and outside the tiered backups
# (spec §16): within 14 days of an expiry no backup holds its key wraps.
# Pruning runs first, so a failing dump still prunes. Every *.sql.gz in the
# directory counts, including the dumps runbooks take before a migration.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/production-common.sh
source "$SCRIPT_DIR/lib/production-common.sh"

days="${SSF_RECORDING_BACKUP_DAYS:-14}"
if ! is_positive_integer "$days"; then
  log_error "SSF_RECORDING_BACKUP_DAYS must be a positive integer"
  exit 2
fi
backup_root="${SSF_RECORDING_BACKUP_ROOT:-$SSF_PROJECT_ROOT/backups/recording}"
umask 077
mkdir -p "$backup_root"
# An hour short of the full days, so a dump taken at the same time each day
# leaves exactly that many behind.
# A .partial left by a dump that was killed holds the same key wraps.
find "$backup_root" -maxdepth 1 -type f \( -name '*.sql.gz' -o -name '*.sql.gz.partial' \) \
  -mmin "+$((days * 1440 - 60))" -delete

exists="$(production_compose exec -T ssf-postgres sh -ec \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT 1 FROM pg_database WHERE datname = '\''ssf_recording'\''"')"
if [[ "$exists" != "1" ]]; then
  printf 'ssf_recording does not exist on this host; nothing to dump\n'
  exit 0
fi

target="$backup_root/ssf-recording-$(date -u +%Y%m%d_%H%M%S).sql.gz"
trap 'rm -f -- "$target.partial"' EXIT
production_compose exec -T ssf-postgres sh -ec 'exec pg_dump -U "$POSTGRES_USER" -d ssf_recording' \
  | gzip -c > "$target.partial"
gzip -t "$target.partial"
mv -- "$target.partial" "$target"
printf 'Recording backup completed: %s\n' "$target"
