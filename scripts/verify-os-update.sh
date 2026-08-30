#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

nvidia-smi -L
"$SCRIPT_DIR/production-health-check.sh" --timeout-seconds 300
printf 'OS update verification passed.\n'
