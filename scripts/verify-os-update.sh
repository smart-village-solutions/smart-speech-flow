#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

nvidia-smi -L
"$SCRIPT_DIR/production-health-check.sh" --timeout-seconds 300
simulation="$(apt-get -s upgrade)"
printf '%s\n' "$simulation"
if ! grep -q '^0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded\.$' <<<"$simulation"; then
  printf 'Operating-system updates remain after the requested upgrade.\n' >&2
  exit 1
fi
printf 'OS update verification passed.\n'
