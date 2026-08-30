#!/usr/bin/env bash

set -o pipefail

SSF_PROJECT_ROOT="${SSF_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
SSF_COMPOSE_FILE="${SSF_COMPOSE_FILE:-$SSF_PROJECT_ROOT/deploy/production/docker-compose.production.yml}"
SSF_PROJECT_NAME="${SSF_PROJECT_NAME:-ssf-backend}"

log_error() {
  printf '%s\n' "$*" >&2
}

production_compose() {
  docker compose \
    --project-name "$SSF_PROJECT_NAME" \
    --env-file "$SSF_PROJECT_ROOT/.env" \
    --file "$SSF_COMPOSE_FILE" \
    "$@"
}

is_positive_integer() {
  [[ "$1" =~ ^[1-9][0-9]*$ ]]
}
