#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
UNIT_SOURCE="$PROJECT_ROOT/deploy/systemd"

if [[ "${EUID}" -ne 0 ]]; then
  printf 'Run this installer as root.\n' >&2
  exit 2
fi

install -m 0644 "$UNIT_SOURCE"/ssf-*.service "$UNIT_SOURCE"/ssf-*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable ssf-production.service ssf-production-health.timer \
  ssf-backup-daily.timer ssf-backup-weekly.timer ssf-backup-monthly.timer
printf 'Systemd units installed. Start ssf-production.service only after controlled activation.\n'
