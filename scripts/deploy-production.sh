#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/production-common.sh
source "$SCRIPT_DIR/lib/production-common.sh"

usage() {
  log_error "Usage: deploy-production.sh [--check|--apply]"
}

validate_production_config() {
  local rendered
  rendered="$(production_compose config)" || {
    log_error "Production Compose configuration is invalid"
    return 1
  }

  grep -Fq 'Host(`auth.dialog.kassel.de`)' <<<"$rendered" || {
    log_error "Production Keycloak router must target auth.dialog.kassel.de"
    return 1
  }
  grep -Fq 'KC_HOSTNAME: https://auth.dialog.kassel.de' <<<"$rendered" || {
    log_error "Production Keycloak hostname must target auth.dialog.kassel.de"
    return 1
  }
  for variable in STUDIO_RUNTIME_TOKEN_URL STUDIO_RUNTIME_CLIENT_SECRET; do
    grep -Fq "$variable:" <<<"$rendered" || {
      log_error "Production Compose configuration is missing $variable"
      return 1
    }
  done
}

case "${1:---check}" in
  --check)
    validate_production_config
    ;;
  --apply)
    validate_production_config
    production_compose up -d
    ;;
  *)
    usage
    exit 2
    ;;
esac
