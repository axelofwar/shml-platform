#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

MODE="${1:-check}"
INTERVAL_SECONDS="${2:-120}"
PLATFORM_PREFIX="${PLATFORM_PREFIX:-shml}"
MIN_MEM_MB="${MIN_MEM_MB:-2048}"
MIN_BUILD_MEM_MB="${MIN_BUILD_MEM_MB:-3072}"
RESTART_COOLDOWN_SECONDS="${RESTART_COOLDOWN_SECONDS:-90}"
TRAINING_GPU="${TRAINING_GPU:-0}"
TRAINING_SENSITIVE_SERVICES="${TRAINING_SENSITIVE_SERVICES:-ray-head,ray-compute-api,mlflow-server,postgres,redis,inference-gateway}"
CONFIG_WATCH_MAP="${CONFIG_WATCH_MAP:-deploy/compose/docker-compose.infra.yml:gitlab;mlflow-server/docker-compose.yml:mlflow-server}"
LOG_DIR="${LOG_DIR:-$ROOT_DIR/logs}"
LOG_FILE="${LOG_FILE:-$LOG_DIR/autonomous_guard.log}"
STATE_DIR="${STATE_DIR:-$LOG_DIR/.autonomous_guard_state}"

mkdir -p "$LOG_DIR"
mkdir -p "$STATE_DIR"

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

is_training_active() {
  local gpu_active=0
  local ray_active=0

  if command -v nvidia-smi >/dev/null 2>&1; then
    if nvidia-smi --id="$TRAINING_GPU" --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -q '[0-9]'; then
      gpu_active=1
    fi
  fi

  if docker inspect -f '{{.State.Running}}' ray-head 2>/dev/null | grep -q true; then
    local running_jobs
    running_jobs=$(docker exec ray-head sh -lc "curl -sf --max-time 4 http://127.0.0.1:8265/api/jobs/ | jq '[.[] | select(.status == \"RUNNING\" or .status == \"PENDING\")] | length'" 2>/dev/null || echo "0")
    if [[ "$running_jobs" =~ ^[0-9]+$ ]] && [[ "$running_jobs" -gt 0 ]]; then
      ray_active=1
    fi
  fi

  [[ "$gpu_active" -eq 1 || "$ray_active" -eq 1 ]]
}

is_training_sensitive_service() {
  local service="$1"
  IFS=',' read -ra protected <<< "$TRAINING_SENSITIVE_SERVICES"
  for item in "${protected[@]}"; do
    local target
    target="$(echo "$item" | xargs)"
    [[ -z "$target" ]] && continue
    if [[ "$service" == "$target" || "$service" == "${PLATFORM_PREFIX}-$target" ]]; then
      return 0
    fi
  done
  return 1
}

state_file_for_path() {
  local file_path="$1"
  local key
  key="$(echo "$file_path" | tr '/:' '__')"
  echo "$STATE_DIR/${key}.sha256"
}

restart_state_file_for_target() {
  local compose_file="$1"
  local service="$2"
  local key
  key="$(echo "${compose_file}:${service}" | tr '/:' '__')"
  echo "$STATE_DIR/restart_${key}.last"
}

is_within_restart_cooldown() {
  local compose_file="$1"
  local service="$2"
  local state_file
  state_file="$(restart_state_file_for_target "$compose_file" "$service")"

  [[ -f "$state_file" ]] || return 1

  local now_epoch
  now_epoch="$(date +%s)"
  local last_epoch
  last_epoch="$(cat "$state_file" 2>/dev/null || echo 0)"

  if [[ ! "$last_epoch" =~ ^[0-9]+$ ]]; then
    return 1
  fi

  local elapsed=$((now_epoch - last_epoch))
  [[ "$elapsed" -lt "$RESTART_COOLDOWN_SECONDS" ]]
}

mark_restart_timestamp() {
  local compose_file="$1"
  local service="$2"
  local state_file
  state_file="$(restart_state_file_for_target "$compose_file" "$service")"
  date +%s > "$state_file"
}

check_config_changes() {
  IFS=';' read -ra watches <<< "$CONFIG_WATCH_MAP"

  for watch in "${watches[@]}"; do
    [[ -z "$watch" ]] && continue
    local compose_file="${watch%%:*}"
    local services_csv="${watch#*:}"

    [[ -f "$compose_file" ]] || continue

    local current_hash
    current_hash="$(sha256sum "$compose_file" | awk '{print $1}')"

    local state_file
    state_file="$(state_file_for_path "$compose_file")"

    if [[ ! -f "$state_file" ]]; then
      echo "$current_hash" > "$state_file"
      continue
    fi

    local previous_hash
    previous_hash="$(cat "$state_file")"

    if [[ "$previous_hash" != "$current_hash" ]]; then
      log "INFO" "Detected config change in $compose_file; reconciling services: $services_csv"
      IFS=',' read -ra services <<< "$services_csv"
      for service in "${services[@]}"; do
        local trimmed_service
        trimmed_service="$(echo "$service" | xargs)"
        [[ -z "$trimmed_service" ]] && continue
        restart_service "$compose_file" "$trimmed_service" || true
      done
      echo "$current_hash" > "$state_file"
    fi
  done
}

restart_service() {
  local compose_file="$1"
  local service="$2"

  if is_training_sensitive_service "$service" && is_training_active; then
    log "WARN" "Deferring restart for $service during active training on GPU $TRAINING_GPU."
    return 1
  fi

  if ! has_headroom "$MIN_MEM_MB"; then
    log "WARN" "Skipping restart for $service due to low memory ($(available_mem_mb)MB < ${MIN_MEM_MB}MB)."
    return 1
  fi

  if is_within_restart_cooldown "$compose_file" "$service"; then
    log "WARN" "Skipping restart for $service due to cooldown (${RESTART_COOLDOWN_SECONDS}s)."
    return 1
  fi

  log "INFO" "Restarting $service via $compose_file"
  docker compose --project-name "${COMPOSE_PROJECT_NAME:-shml-platform}" --env-file .env -f "$compose_file" up -d "$service" >/dev/null
  mark_restart_timestamp "$compose_file" "$service"
}

rebuild_chat_ui() {
  if ! has_headroom "$MIN_BUILD_MEM_MB"; then
    log "WARN" "Skipping chat-ui rebuild due to low memory ($(available_mem_mb)MB < ${MIN_BUILD_MEM_MB}MB)."
    return 1
  fi

  log "INFO" "Rebuilding chat-ui for base-path correction"
  docker compose --project-name "${COMPOSE_PROJECT_NAME:-shml-platform}" --env-file .env -f chat-ui-v2/docker-compose.yml up -d --build chat-ui >/dev/null
}

check_status() {
  local failures=()

  local required_containers=(
    "${PLATFORM_PREFIX}-traefik"
    "oauth2-proxy"
    "fusionauth"
    "${PLATFORM_PREFIX}-postgres"
    "${PLATFORM_PREFIX}-redis"
    "${PLATFORM_PREFIX}-gitlab"
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

  local gitlab_container
  gitlab_container="${PLATFORM_PREFIX}-gitlab"
  if docker inspect -f '{{.State.Running}}' "$gitlab_container" 2>/dev/null | grep -q true; then
    local gitlab_health
    gitlab_health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$gitlab_container" 2>/dev/null || echo "none")"
    if [[ "$gitlab_health" == "none" ]]; then
      if ! docker exec "$gitlab_container" sh -lc "curl -sf --max-time 8 http://localhost:8929/gitlab/users/sign_in" >/dev/null 2>&1; then
        failures+=("gitlab:endpoint")
      fi
    elif [[ "$gitlab_health" != "healthy" && "$gitlab_health" != "starting" ]]; then
      failures+=("gitlab:endpoint")
    fi
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
  local -A restarted_targets=()

  restart_once() {
    local compose_file="$1"
    local service="$2"
    local target_key="${compose_file}:${service}"

    if [[ -n "${restarted_targets[$target_key]:-}" ]]; then
      return 0
    fi

    restarted_targets["$target_key"]=1
    restart_service "$compose_file" "$service"
  }

  for failure in "${failures[@]}"; do
    case "$failure" in
      container:${PLATFORM_PREFIX}-traefik)
        restart_once deploy/compose/docker-compose.infra.yml traefik || true
        ;;
      container:oauth2-proxy)
        restart_once deploy/compose/docker-compose.infra.yml oauth2-proxy || true
        ;;
      container:fusionauth)
        restart_once deploy/compose/docker-compose.infra.yml fusionauth || true
        ;;
      container:${PLATFORM_PREFIX}-postgres)
        restart_once deploy/compose/docker-compose.infra.yml postgres || true
        ;;
      container:${PLATFORM_PREFIX}-redis)
        restart_once deploy/compose/docker-compose.infra.yml redis || true
        ;;
      container:homer)
        restart_once deploy/compose/docker-compose.infra.yml homer || true
        ;;
      container:${PLATFORM_PREFIX}-chat-ui)
        restart_once chat-ui-v2/docker-compose.yml chat-ui || true
        ;;
      container:${PLATFORM_PREFIX}-gitlab|gitlab:endpoint)
        restart_once deploy/compose/docker-compose.infra.yml gitlab || true
        ;;
      db:*|redis:ping)
        restart_once deploy/compose/docker-compose.infra.yml postgres || true
        restart_once deploy/compose/docker-compose.infra.yml redis || true
        ;;
      homer:icons)
        mkdir -p monitoring/homer/icons
        cp -f monitoring/homer/logo_small.png monitoring/homer/icons/apple-touch-icon.png
        cp -f monitoring/homer/logo_small.png monitoring/homer/icons/favicon.ico
        cp -f monitoring/homer/logo_small.png monitoring/homer/icons/pwa-192x192.png
        cp -f monitoring/homer/logo_small.png monitoring/homer/icons/pwa-512x512.png
        restart_once deploy/compose/docker-compose.infra.yml homer || true
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

  check_config_changes || true

  if check_status >"$output_file" 2>&1; then
    cat "$output_file"
    rm -f "$output_file"
    return 0
  fi

  cat "$output_file"

  if [[ "$MODE" == "remediate" || "$MODE" == "watch" ]]; then
    mapfile -t failure_lines < <(grep -E '^(container|db|redis|homer|chatui|gitlab):' "$output_file" || true)
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
  TRAINING_GPU=${TRAINING_GPU}
  TRAINING_SENSITIVE_SERVICES=${TRAINING_SENSITIVE_SERVICES}
  CONFIG_WATCH_MAP=${CONFIG_WATCH_MAP}
  RESTART_COOLDOWN_SECONDS=${RESTART_COOLDOWN_SECONDS}
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
