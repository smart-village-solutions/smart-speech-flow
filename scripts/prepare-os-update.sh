#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

backup_dir="${1:-}"
if [[ $# -ne 1 ]]; then
  printf 'Usage: %s <concrete-verified-backup-directory>\n' "$0" >&2
  exit 2
fi

"$SCRIPT_DIR/verify-production-backup.sh" "$backup_dir"
"$SCRIPT_DIR/production-health-check.sh" --timeout-seconds 300

apt-get update
apt list --upgradable
printf 'OS update preflight passed. Apply updates explicitly with apt-get upgrade.\n'
