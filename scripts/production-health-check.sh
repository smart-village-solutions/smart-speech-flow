#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/production-common.sh
source "$SCRIPT_DIR/lib/production-common.sh"

timeout_seconds=300
if [[ "${1:-}" == "--timeout-seconds" ]]; then
  timeout_seconds="${2:-}"
  shift 2
fi
if [[ $# -ne 0 ]] || ! is_positive_integer "$timeout_seconds"; then
  log_error "--timeout-seconds must be a positive integer"
  exit 2
fi

required_services=(
  traefik asr translation tts api_gateway ollama redis clickhouse
  keycloak-postgres keycloak frontend-archive frontend prometheus grafana
  dcgm_exporter cadvisor node_exporter loki promtail
)

all_containers_running() {
  local running
  running="$(docker ps --filter "label=com.docker.compose.project=$SSF_PROJECT_NAME" \
    --filter status=running --format '{{.Label "com.docker.compose.service"}}')"
  local service
  for service in "${required_services[@]}"; do
    if ! grep -Fxq "$service" <<<"$running"; then
      log_error "Container is not running: $service"
      return 1
    fi
  done
}

api_is_healthy() {
  local response
  response="$(curl --fail --silent --show-error http://127.0.0.1:8000/health)" || return 1
  jq -e '.services.ASR == "ok" and .services.Translation == "ok" and .services.TTS == "ok"' \
    >/dev/null <<<"$response"
}

platform_is_healthy() {
  nvidia-smi -L >/dev/null 2>&1 || { log_error "GPU is unavailable"; return 1; }
  all_containers_running || return 1
  api_is_healthy || { log_error "API pipeline health check failed"; return 1; }
  production_compose exec -T prometheus wget -qO- http://127.0.0.1:9090/-/healthy \
    | grep -q 'Prometheus Server is Healthy' || { log_error "Prometheus health check failed"; return 1; }
  curl --fail --silent --show-error http://127.0.0.1:3000/api/health \
    | jq -e '.database == "ok"' >/dev/null || { log_error "Grafana health check failed"; return 1; }
  production_compose exec -T keycloak bash -ec 'exec 3<>/dev/tcp/127.0.0.1/9000; printf "GET /health/ready HTTP/1.1\\r\\nHost: localhost\\r\\nConnection: close\\r\\n\\r\\n" >&3; grep -q "200 OK" <&3' \
    || { log_error "Keycloak health check failed"; return 1; }
  production_compose exec -T redis redis-cli ping | grep -qx PONG \
    || { log_error "Redis health check failed"; return 1; }
  production_compose exec -T clickhouse clickhouse-client --query 'SELECT 1' | grep -qx 1 \
    || { log_error "ClickHouse health check failed"; return 1; }
}

deadline=$((SECONDS + timeout_seconds))
while (( SECONDS < deadline )); do
  if platform_is_healthy; then
    printf 'Production health check passed.\n'
    exit 0
  fi
  sleep 2
done

log_error "Production health check did not pass within ${timeout_seconds} seconds"
exit 1
