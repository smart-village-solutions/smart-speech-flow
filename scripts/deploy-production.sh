#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/production-common.sh
source "$SCRIPT_DIR/lib/production-common.sh"

usage() {
  log_error "Usage: deploy-production.sh [--check|--apply]"
}

acme_router_hosts() {
  awk '
    function router_name(line, suffix, name) {
      name = line
      sub(/^"?traefik\.http\.routers\./, "", name)
      sub(suffix ".*$", "", name)
      return name
    }
    {
      line = $0
      sub(/^[[:space:]-]+/, "", line)

      if (line ~ /^"?traefik\.http\.routers\.[^.]+\.tls\.certresolver[=:][[:space:]]*"?le"?/) {
        acme[router_name(line, "\\.tls\\.certresolver[=:]")] = 1
      }
      if (line ~ /^"?traefik\.http\.routers\.[^.]+\.rule[=:]/) {
        name = router_name(line, "\\.rule[=:]")
        while (match(line, /Host\(`[^`]+`\)/)) {
          hostname = substr(line, RSTART, RLENGTH)
          sub(/^Host\(`/, "", hostname)
          sub(/`\)$/, "", hostname)
          hosts[name] = hosts[name] hostname "\n"
          line = substr(line, RSTART + RLENGTH)
        }
      }
    }
    END {
      for (name in acme) {
        count = split(hosts[name], values, "\n")
        for (position = 1; position <= count; position++) {
          if (values[position] != "") print values[position]
        }
      }
    }
  ' <<<"$1" | sort -u
}

validate_acme_router_hosts() {
  local rendered="$1"
  local hostname

  while IFS= read -r hostname; do
    [[ "$hostname" != "localhost" && "$hostname" != *.localhost ]] || {
      log_error "ACME router hostname is local-only: $hostname"
      return 1
    }
    getent ahosts "$hostname" >/dev/null || {
      log_error "ACME router hostname cannot be resolved: $hostname"
      return 1
    }
  done < <(acme_router_hosts "$rendered")
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
  validate_acme_router_hosts "$rendered"
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
