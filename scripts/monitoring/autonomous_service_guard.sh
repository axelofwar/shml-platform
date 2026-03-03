#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

MODE="${1:-check}"
INTERVAL_SECONDS="${2:-120}"
PLATFORM_PREFIX="${PLATFORM_PREFIX:-shml}"
MIN_MEM_MB="${MIN_MEM_MB:-2048}"
MIN_BUILD_MEM_MB="${MIN_BUILD_MEM_MB:-3072}"
LOG_DIR="${LOG_DIR:-$ROOT_DIR/logs}"
LOG_FILE="${LOG_FILE:-$LOG_DIR/autonomous_guard.log}"

mkdir -p "$LOG_DIR"

log() {
  local level="$1"
  local message="$2"
  local ts
  ts="$(date '+%Y-%m-%d %H:%M:%S')"
  echo "[$ts] [$level] $message" | tee -a "$LOG_FILE"
}

available_mem_mb() {
  awk '/MemAvailable:/ {printf "%d", $2/1024}' /proc/meminfo
}

has_headroom() {
  local required_mb="$1"
  local current_mb
  current_mb="$(available_mem_mb)"
  [[ "$current_mb" -ge "$required_mb" ]]
}

restart_service() {
  local compose_file="$1"
  local service="$2"

  if ! has_headroom "$MIN_MEM_MB"; then
    log "WARN" "Skipping restart for $service due to low memory ($(available_mem_mb)MB < ${MIN_MEM_MB}MB)."
    return 1
  fi

  log "INFO" "Restarting $service via $compose_file"
  docker compose --env-file .env -f "$compose_file" up -d "$service" >/dev/null
}

rebuild_chat_ui() {
  if ! has_headroom "$MIN_BUILD_MEM_MB"; then
    log "WARN" "Skipping chat-ui rebuild due to low memory ($(available_mem_mb)MB < ${MIN_BUILD_MEM_MB}MB)."
    return 1
  fi

  log "INFO" "Rebuilding chat-ui for base-path correction"
  docker compose --env-file .env -f chat-ui-v2/docker-compose.yml up -d --build chat-ui >/dev/null
}

check_status() {
  local failures=()

  local required_containers=(
    "${PLATFORM_PREFIX}-traefik"
    "oauth2-proxy"
    "fusionauth"
    "${PLATFORM_PREFIX}-postgres"
    "${PLATFORM_PREFIX}-redis"
    "homer"
    "${PLATFORM_PREFIX}-chat-ui"
  )

  for container in "${required_containers[@]}"; do
    if ! docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null | grep -q true; then
      failures+=("container:$container")
    fi
  done

  for db_name in mlflow_db ray_compute fusionauth inference; do
    if ! docker exec "${PLATFORM_PREFIX}-postgres" psql -U postgres -d "$db_name" -c "SELECT 1" >/dev/null 2>&1; then
      failures+=("db:$db_name")
    fi
  done

  if ! docker exec "${PLATFORM_PREFIX}-redis" redis-cli PING >/dev/null 2>&1; then
    failures+=("redis:ping")
  fi

  if ! curl -s -o /dev/null -w '%{http_code}' http://localhost/assets/icons/favicon.ico | grep -q '^200$'; then
    failures+=("homer:icons")
  fi

  if ! docker exec "${PLATFORM_PREFIX}-chat-ui" sh -lc "grep -q '/chat-ui/assets/' /usr/share/nginx/html/index.html" >/dev/null 2>&1; then
    failures+=("chatui:basepath")
  fi

  if [[ ${#failures[@]} -eq 0 ]]; then
    log "OK" "All guard checks passed."
    return 0
  fi

  log "WARN" "Detected ${#failures[@]} issue(s): ${failures[*]}"
  printf '%s\n' "${failures[@]}"
  return 2
}

remediate_failures() {
  local failures=("$@")

  for failure in "${failures[@]}"; do
    case "$failure" in
      container:${PLATFORM_PREFIX}-traefik)
        restart_service docker-compose.infra.yml traefik || true
        ;;
      container:oauth2-proxy)
        restart_service docker-compose.infra.yml oauth2-proxy || true
        ;;
      container:fusionauth)
        restart_service docker-compose.infra.yml fusionauth || true
        ;;
      container:${PLATFORM_PREFIX}-postgres)
        restart_service docker-compose.infra.yml postgres || true
        ;;
      container:${PLATFORM_PREFIX}-redis)
        restart_service docker-compose.infra.yml redis || true
        ;;
      container:homer)
        restart_service docker-compose.infra.yml homer || true
        ;;
      container:${PLATFORM_PREFIX}-chat-ui)
        restart_service chat-ui-v2/docker-compose.yml chat-ui || true
        ;;
      db:*|redis:ping)
        restart_service docker-compose.infra.yml postgres || true
        restart_service docker-compose.infra.yml redis || true
        ;;
      homer:icons)
        mkdir -p monitoring/homer/icons
        cp -f monitoring/homer/logo_small.png monitoring/homer/icons/apple-touch-icon.png
        cp -f monitoring/homer/logo_small.png monitoring/homer/icons/favicon.ico
        cp -f monitoring/homer/logo_small.png monitoring/homer/icons/pwa-192x192.png
        cp -f monitoring/homer/logo_small.png monitoring/homer/icons/pwa-512x512.png
        restart_service docker-compose.infra.yml homer || true
        ;;
      chatui:basepath)
        rebuild_chat_ui || true
        ;;
      *)
        log "WARN" "No remediation mapping for $failure"
        ;;
    esac
  done
}

run_once() {
  local output_file
  output_file="$(mktemp)"

  if check_status >"$output_file" 2>&1; then
    cat "$output_file"
    rm -f "$output_file"
    return 0
  fi

  cat "$output_file"

  if [[ "$MODE" == "remediate" || "$MODE" == "watch" ]]; then
    mapfile -t failure_lines < <(grep -E '^(container|db|redis|homer|chatui):' "$output_file" || true)
    remediate_failures "${failure_lines[@]}"
    check_status || true
  fi

  rm -f "$output_file"
  return 1
}

usage() {
  cat <<EOF
Usage:
  ./scripts/monitoring/autonomous_service_guard.sh check
  ./scripts/monitoring/autonomous_service_guard.sh remediate
  ./scripts/monitoring/autonomous_service_guard.sh watch [interval_seconds]

Environment overrides:
  PLATFORM_PREFIX=${PLATFORM_PREFIX}
  MIN_MEM_MB=${MIN_MEM_MB}
  MIN_BUILD_MEM_MB=${MIN_BUILD_MEM_MB}
  LOG_FILE=${LOG_FILE}
EOF
}

case "$MODE" in
  check)
    run_once
    ;;
  remediate)
    run_once
    ;;
  watch)
    log "INFO" "Starting watch loop (interval=${INTERVAL_SECONDS}s)"
    while true; do
      run_once || true
      sleep "$INTERVAL_SECONDS"
    done
    ;;
  *)
    usage
    exit 1
    ;;
esac
