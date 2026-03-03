#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

LOG_DIR="${LOG_DIR:-$ROOT_DIR/.openclaw/logs}"
LOG_FILE="${LOG_FILE:-$LOG_DIR/autonomous-manager.log}"
STATE_FILE="${STATE_FILE:-$LOG_DIR/autonomous-manager.state}"
OPENCLAW_BIN="${OPENCLAW_BIN:-$HOME/.nvm/versions/node/v22.22.0/bin/openclaw}"
GUARD_SCRIPT="${GUARD_SCRIPT:-$ROOT_DIR/scripts/monitoring/autonomous_service_guard.sh}"
NEMOTRON_HEALTH_URL="${NEMOTRON_HEALTH_URL:-http://localhost:8010/health}"
NEMOTRON_HEALTH_TIMEOUT_SECONDS="${NEMOTRON_HEALTH_TIMEOUT_SECONDS:-8}"
MAX_NEMOTRON_HEALTH_LATENCY_MS="${MAX_NEMOTRON_HEALTH_LATENCY_MS:-2500}"
CONSECUTIVE_DEGRADE_THRESHOLD="${CONSECUTIVE_DEGRADE_THRESHOLD:-2}"

LOCAL_MODEL="nemotron-local/nemotron-coding"
REMOTE_BALANCED="github-copilot/claude-sonnet-4.6"
REMOTE_EFFICIENT="github-copilot/gpt-4o"

mkdir -p "$LOG_DIR"

degrade_count=0

log() {
  local level="$1"
  local message="$2"
  local ts
  ts="$(date '+%Y-%m-%d %H:%M:%S')"
  echo "[$ts] [$level] $message" | tee -a "$LOG_FILE"
}

require_openclaw() {
  if ! command -v "$OPENCLAW_BIN" >/dev/null 2>&1; then
    log "ERROR" "OpenClaw binary not found at $OPENCLAW_BIN"
    exit 1
  fi
}

training_active_on_gpu0() {
  local gpu0_uuid
  gpu0_uuid="$(nvidia-smi --query-gpu=index,uuid --format=csv,noheader 2>/dev/null | awk -F', ' '$1==0{print $2; exit}')"
  if [[ -z "$gpu0_uuid" ]]; then
    return 1
  fi

  nvidia-smi --query-compute-apps=gpu_uuid,process_name --format=csv,noheader 2>/dev/null \
    | awk -F', ' -v gpu0="$gpu0_uuid" '$1==gpu0 && $2!="llama-server" {found=1} END {exit found ? 0 : 1}'
}

nemotron_available() {
  curl -fsS --max-time "$NEMOTRON_HEALTH_TIMEOUT_SECONDS" "$NEMOTRON_HEALTH_URL" >/dev/null 2>&1
}

load_state() {
  if [[ -f "$STATE_FILE" ]]; then
    source "$STATE_FILE" || true
  fi

  if ! [[ "${degrade_count:-0}" =~ ^[0-9]+$ ]]; then
    degrade_count=0
  fi
}

save_state() {
  printf 'degrade_count=%s\n' "$degrade_count" > "$STATE_FILE"
}

nemotron_health_latency_ms() {
  local result
  result="$(curl -sS -o /dev/null --max-time "$NEMOTRON_HEALTH_TIMEOUT_SECONDS" -w '%{http_code} %{time_total}' "$NEMOTRON_HEALTH_URL" 2>/dev/null || true)"
  local code
  local time_sec
  code="$(awk '{print $1}' <<< "$result")"
  time_sec="$(awk '{print $2}' <<< "$result")"

  if [[ "$code" != "200" || -z "$time_sec" ]]; then
    echo "-1"
    return
  fi

  python3 - <<'PY' "$time_sec"
import sys
print(int(float(sys.argv[1]) * 1000))
PY
}

ensure_model_stack() {
  local desired_default="$1"
  shift
  local desired_fallbacks=("$@")

  local status_json
  status_json="$($OPENCLAW_BIN models status --json 2>/dev/null || true)"

  if [[ -z "$status_json" ]]; then
    log "WARN" "Unable to read OpenClaw model status; forcing desired model stack."
    $OPENCLAW_BIN models set "$desired_default" >/dev/null
    $OPENCLAW_BIN models fallbacks clear >/dev/null
    for model in "${desired_fallbacks[@]}"; do
      $OPENCLAW_BIN models fallbacks add "$model" >/dev/null
    done
    return
  fi

  local changed
  changed="$(STATUS_JSON="$status_json" python3 - "$desired_default" "${desired_fallbacks[*]}" <<'PY'
import json
import os
import sys

wanted_default = sys.argv[1]
wanted_fallbacks = [m for m in sys.argv[2].split(' ') if m]
raw = os.environ.get('STATUS_JSON', '').strip()
if not raw:
    print('1')
    raise SystemExit(0)

data = json.loads(raw)
current_default = data.get('defaultModel')
current_fallbacks = data.get('fallbacks', [])
print('1' if (current_default != wanted_default or current_fallbacks != wanted_fallbacks) else '0')
PY
)"

  if [[ "$changed" == "0" ]]; then
    log "OK" "Model routing already aligned: default=$desired_default"
    return
  fi

  log "INFO" "Updating model routing: default=$desired_default fallbacks=${desired_fallbacks[*]}"
  $OPENCLAW_BIN models set "$desired_default" >/dev/null
  $OPENCLAW_BIN models fallbacks clear >/dev/null
  for model in "${desired_fallbacks[@]}"; do
    $OPENCLAW_BIN models fallbacks add "$model" >/dev/null
  done
}

main() {
  require_openclaw
  load_state

  if ! $OPENCLAW_BIN health >/dev/null 2>&1; then
    log "WARN" "OpenClaw gateway health check failed, restarting gateway."
    $OPENCLAW_BIN gateway restart >/dev/null 2>&1 || true
    sleep 2
  fi

  if [[ -x "$GUARD_SCRIPT" ]]; then
    "$GUARD_SCRIPT" remediate >/dev/null 2>&1 || true
  else
    log "WARN" "Guard script missing or not executable: $GUARD_SCRIPT"
  fi

  if training_active_on_gpu0; then
    log "INFO" "Detected GPU0 training/compute contention; preferring Copilot balanced tier."
    ensure_model_stack "$REMOTE_BALANCED" "$REMOTE_EFFICIENT" "$LOCAL_MODEL"
    degrade_count=0
    save_state
    exit 0
  fi

  local latency_ms
  latency_ms="$(nemotron_health_latency_ms)"

  if [[ "$latency_ms" -ge 0 && "$latency_ms" -le "$MAX_NEMOTRON_HEALTH_LATENCY_MS" ]]; then
    degrade_count=0
    save_state
    log "INFO" "Nemotron healthy (${latency_ms}ms <= ${MAX_NEMOTRON_HEALTH_LATENCY_MS}ms); preferring local model first."
    ensure_model_stack "$LOCAL_MODEL" "$REMOTE_BALANCED" "$REMOTE_EFFICIENT"
  else
    degrade_count=$((degrade_count + 1))
    save_state
    if [[ "$latency_ms" -lt 0 ]]; then
      log "WARN" "Nemotron health unavailable; consecutive_degraded_polls=${degrade_count}/${CONSECUTIVE_DEGRADE_THRESHOLD}."
    else
      log "WARN" "Nemotron degraded (${latency_ms}ms > ${MAX_NEMOTRON_HEALTH_LATENCY_MS}ms); consecutive_degraded_polls=${degrade_count}/${CONSECUTIVE_DEGRADE_THRESHOLD}."
    fi

    if [[ "$degrade_count" -ge "$CONSECUTIVE_DEGRADE_THRESHOLD" ]]; then
      log "INFO" "Demotion threshold reached; using Copilot balanced fallback stack."
      ensure_model_stack "$REMOTE_BALANCED" "$REMOTE_EFFICIENT" "$LOCAL_MODEL"
    else
      log "INFO" "Threshold not reached yet; retaining local-first routing for this poll."
      ensure_model_stack "$LOCAL_MODEL" "$REMOTE_BALANCED" "$REMOTE_EFFICIENT"
    fi
  fi
}

main "$@"
