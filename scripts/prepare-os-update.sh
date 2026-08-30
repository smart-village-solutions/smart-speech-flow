#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -ne 0 ]]; then
  printf 'Usage: %s\n' "$0" >&2
  exit 2
fi

"$SCRIPT_DIR/backup-production.sh" --tier daily
backup_dir="$(readlink -f "$SSF_PROJECT_ROOT/backups/daily/latest")"
"$SCRIPT_DIR/verify-production-backup.sh" "$backup_dir"
"$SCRIPT_DIR/production-health-check.sh" --timeout-seconds 300

apt-get update
apt-get -s upgrade
printf 'OS update preflight passed. Apply the simulated updates explicitly with apt-get upgrade.\n'
