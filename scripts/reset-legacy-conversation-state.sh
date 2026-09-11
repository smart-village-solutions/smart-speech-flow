#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/production-common.sh"

if [[ "${1:-}" != "--destructive-reset-production" || "$#" -ne 1 ]]; then
  log_error "Usage: $0 --destructive-reset-production"
  exit 2
fi

running_services="$(production_compose ps --status running --services)"
if grep -qx 'api_gateway' <<<"$running_services"; then
  log_error "Refusing cutover: api_gateway is still running"
  exit 1
fi
if grep -qx 'frontend' <<<"$running_services"; then
  log_error "Refusing cutover: frontend is still running"
  exit 1
fi

production_compose run --rm --no-deps api_gateway \
  python -m services.api_gateway.tenant_cutover \
  --apply --confirm-empty-production
