#!/bin/bash
# =============================================================================
# Self-Healing Watchdog v2 — SHML Platform
# =============================================================================
# GPU-aware, memory-safe watchdog with autonomous agent orchestration.
#
# Key properties:
#   - Uses RTX 2070 (GPU 1) memory first, then system RAM — never touches
#     GPU 0 (RTX 3090 Ti) to protect training jobs
#   - Detects and remediates memory leaks (OOM-killed containers, growing RSS)
#   - Orchestrates cross-service resolution via the agent-service API
#   - Discovers full application state: UIs, services, features, GPU allocation
#   - Audit log for every action
#   - Telegram notifications for all events
#
# Environment:
#   CHECK_INTERVAL         — seconds between checks (default: 60)
#   MAX_RESTARTS           — max restarts per container per hour (default: 3)
#   COOLDOWN_SECONDS       — backoff after max restarts reached (default: 900)
#   TRAINING_GPU           — GPU index reserved for training (default: 0)
#   WATCHDOG_GPU           — GPU index watchdog prefers (default: 1)
#   MEMORY_LEAK_THRESHOLD  — MB growth per hour to flag leak (default: 100)
#   AGENT_SERVICE_URL      — Agent service for cross-svc resolution
#   GITLAB_INTERNAL_HEALTH_URL — Internal GitLab endpoint probe URL
#   TELEGRAM_BOT_TOKEN     — Telegram bot API token
#   TELEGRAM_CHAT_ID       — Telegram chat/group ID
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
SERVICE_DISCOVERY="${PLATFORM_DIR}/scripts/platform/service_discovery.sh"

if [[ -f "$SERVICE_DISCOVERY" ]]; then
    # shellcheck disable=SC1090
    source "$SERVICE_DISCOVERY"
fi

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CHECK_INTERVAL="${CHECK_INTERVAL:-60}"
MAX_RESTARTS="${MAX_RESTARTS:-3}"
COOLDOWN_SECONDS="${COOLDOWN_SECONDS:-900}"
PLATFORM_PREFIX="${PLATFORM_PREFIX:-shml}"
PROMETHEUS_URL="${PROMETHEUS_URL:-http://global-prometheus:9090}"
AGENT_SERVICE_URL="${AGENT_SERVICE_URL:-http://agent-service:8000}"
# shl-nano Phase-1 fast diagnosis endpoint (T8.5) — leave empty to disable
NANO_SERVICE_URL="${NANO_SERVICE_URL:-}"
GITLAB_INTERNAL_HEALTH_URL="${GITLAB_INTERNAL_HEALTH_URL:-http://gitlab:8929/gitlab/users/sign_in}"

# GPU isolation — NEVER touch the training GPU
TRAINING_GPU="${TRAINING_GPU:-0}"       # RTX 3090 Ti — hands off
WATCHDOG_GPU="${WATCHDOG_GPU:-1}"       # RTX 2070 — watchdog uses this first
DISPLAY_GPU="${DISPLAY_GPU:-${WATCHDOG_GPU}}"  # GPU attached to the desktop/session
TRAINING_SENSITIVE_CONTAINERS="${TRAINING_SENSITIVE_CONTAINERS:-ray-head,ray-compute-api,mlflow-server,${PLATFORM_PREFIX}-postgres,${PLATFORM_PREFIX}-redis,inference-gateway}"

# Memory leak detection
MEMORY_LEAK_THRESHOLD_MB="${MEMORY_LEAK_THRESHOLD:-100}"  # MB growth/hour = leak
OOM_RESTART_BUDGET="${OOM_RESTART_BUDGET:-2}"             # Max OOM restarts/hour
HOST_MEMORY_SOFT_WATERMARK_PCT="${HOST_MEMORY_SOFT_WATERMARK_PCT:-85}"
HOST_MEMORY_HIGH_WATERMARK_PCT="${HOST_MEMORY_HIGH_WATERMARK_PCT:-92}"
HOST_SWAP_HIGH_WATERMARK_PCT="${HOST_SWAP_HIGH_WATERMARK_PCT:-25}"
DISPLAY_GPU_UTIL_WATERMARK_PCT="${DISPLAY_GPU_UTIL_WATERMARK_PCT:-60}"
DISPLAY_GPU_MEMORY_WATERMARK_MIB="${DISPLAY_GPU_MEMORY_WATERMARK_MIB:-2048}"
LOW_PRIORITY_CONTAINERS="${LOW_PRIORITY_CONTAINERS:-qwen3-vl-api,z-image-api,pii-blur-api,${PLATFORM_PREFIX}-fiftyone,${PLATFORM_PREFIX}-code-server,dozzle,ray-compute-ui,sba-resource-portal}"

# Pushgateway for Prometheus metrics export
PUSHGATEWAY_URL="${PUSHGATEWAY_URL:-http://${PLATFORM_PREFIX}-pushgateway:9091}"

LOG_DIR="/var/log/watchdog"
AUDIT_LOG="${LOG_DIR}/audit.log"
RESOURCE_LOG="${LOG_DIR}/resource.log"
STATE_DIR="/var/lib/watchdog"
MEMORY_DIR="${STATE_DIR}/memory"
DISCOVERY_FILE="${STATE_DIR}/platform_state.json"

mkdir -p "$LOG_DIR" "$STATE_DIR" "$MEMORY_DIR"

# ---------------------------------------------------------------------------
# Metrics counters (reset on restart, pushed to Pushgateway each cycle)
# ---------------------------------------------------------------------------
WATCHDOG_START_TIME=$(date +%s)
TOTAL_RESTARTS=0
TOTAL_ACTIONS=0
TOTAL_AGENT_ESCALATIONS=0
TOTAL_OOM_KILLS=0
TOTAL_MEMORY_LEAKS=0
TRAINING_PROTECTED=0
IS_PAUSED=0
CONTROL_FILE="${STATE_DIR}/control"

# Ensure watchdog itself doesn't use training GPU
export CUDA_VISIBLE_DEVICES="${WATCHDOG_GPU}"
export NVIDIA_VISIBLE_DEVICES="${WATCHDOG_GPU}"

# ---------------------------------------------------------------------------
# Container registry
# ---------------------------------------------------------------------------
# Critical: must be running at all times
CRITICAL_CONTAINERS=(
    "${PLATFORM_PREFIX}-traefik"
    "global-prometheus"
    "unified-grafana"
    "${PLATFORM_PREFIX}-redis"
    "${PLATFORM_PREFIX}-postgres"
    "${PLATFORM_PREFIX}-gitlab"
    "fusionauth"
    "${PLATFORM_PREFIX}-alertmanager"
    "gpu-manager"           # GPU resource management (required for training jobs)
    "gpu-control-proxy"     # GPU proxy layer
)

# Standard: tolerate brief downtime
STANDARD_CONTAINERS=(
    "mlflow-server"
    "mlflow-prometheus"
    "homer"
    "oauth2-proxy"
    "${PLATFORM_PREFIX}-code-server"
    "${PLATFORM_PREFIX}-pushgateway"
    "${PLATFORM_PREFIX}-ml-slo-exporter"
    "${PLATFORM_PREFIX}-fiftyone"
    "${PLATFORM_PREFIX}-fiftyone-mongodb"
    "${PLATFORM_PREFIX}-chat-ui"
    "${PLATFORM_PREFIX}-agent-service"
    "inference-gateway"
    "ray-head"
    "ray-compute-api"
    "${PLATFORM_PREFIX}-infisical"
    "${PLATFORM_PREFIX}-nessie"
    "${PLATFORM_PREFIX}-loki"
    "${PLATFORM_PREFIX}-embedding-service"
    "${PLATFORM_PREFIX}-role-auth"
    "${PLATFORM_PREFIX}-alertmanager-telegram"
    "${PLATFORM_PREFIX}-feature-scheduler"
    "webhook-deployer"
    "dozzle"
    # Services present in running platform but previously untracked:
    "mlflow-api"                            # MLflow enhanced API
    "mlflow-nginx"                          # MLflow reverse proxy
    "ray-compute-ui"                        # Ray dashboard UI
    "ray-prometheus"                        # Ray metrics scraper
    "${PLATFORM_PREFIX}-chat-api"           # Chat backend API
    "${PLATFORM_PREFIX}-sba-resource-portal" # SBA portal
    "${PLATFORM_PREFIX}-cadvisor"           # Container metrics exporter
    "${PLATFORM_PREFIX}-node-exporter"      # Host metrics exporter
    "dcgm-exporter"                         # GPU metrics exporter
    "postgres-backup"                       # Scheduled DB backup
    "${PLATFORM_PREFIX}-otel-collector"     # OpenTelemetry collector
    "${PLATFORM_PREFIX}-tempo"              # Distributed tracing backend
)

# Containers with known memory-growth patterns (watch closely)
MEMORY_WATCH_CONTAINERS=(
    "${PLATFORM_PREFIX}-agent-service"
    "inference-gateway"
    "${PLATFORM_PREFIX}-fiftyone"
    "${PLATFORM_PREFIX}-code-server"
    "mlflow-server"
)

# User-facing UIs (for state discovery)
UI_SERVICES=(
    "homer|/|Landing Page"
    "${PLATFORM_PREFIX}-chat-ui|/chat-ui/|AI Chat Interface"
    "unified-grafana|/grafana|Monitoring Dashboards"
    "${PLATFORM_PREFIX}-code-server|/ide|VS Code IDE"
    "ray-compute-ui|/ray/ui|Ray Compute UI"
    "dozzle|/logs|Log Viewer"
    "sba-resource-portal|/sba-portal|SBA Resource Portal"
    "${PLATFORM_PREFIX}-fiftyone|/fiftyone|Dataset Curation"
    "pii-ui|/pii|PII Blur Demo"
    "mlflow-nginx|/mlflow|ML Experiment Tracking"
    "${PLATFORM_PREFIX}-traefik|/traefik|API Gateway Dashboard"
)

# HTTP-level health probes — container|internal_health_url|display_name
# The watchdog runs on the platform network so it can resolve container names.
# Format: restart_target (container to restart)|url|human label for log/alert
#
# Probe logic:
#   - 2xx = healthy
#   - timeout (>8s) or 5xx = unhealthy → restart restart_target
#   - 401/403 = OAuth gate active = healthy (service is running)
HTTP_SERVICES=(
    "mlflow-server|http://mlflow-server:5000/health|MLflow Server"
    "mlflow-nginx|http://mlflow-nginx:80/mlflow/|MLflow Nginx"
    "homer|http://homer:8080/|Homer Dashboard"
    "${PLATFORM_PREFIX}-agent-service|http://${PLATFORM_PREFIX}-agent-service:8000/health|Agent Service"
    "inference-gateway|http://inference-gateway:8000/health|Inference Gateway"
    "${PLATFORM_PREFIX}-chat-ui|http://${PLATFORM_PREFIX}-chat-ui:80/|Chat UI"
    "${PLATFORM_PREFIX}-chat-api|http://${PLATFORM_PREFIX}-chat-api:8000/health|Chat API"
    "${PLATFORM_PREFIX}-nessie|http://${PLATFORM_PREFIX}-nessie:9000/q/health|Nessie Catalog"
    "${PLATFORM_PREFIX}-loki|http://${PLATFORM_PREFIX}-loki:3100/ready|Loki"
    "${PLATFORM_PREFIX}-infisical|http://${PLATFORM_PREFIX}-infisical:8080/api/status|Infisical"
    "${PLATFORM_PREFIX}-fiftyone|http://${PLATFORM_PREFIX}-fiftyone:5151/|FiftyOne"
    "ray-compute-ui|http://ray-compute-ui:3000/ray/ui/|Ray Compute UI"
    "dozzle|http://dozzle:8080/logs/|Dozzle Logs"
    "pii-blur-api|http://pii-blur-api:8000/health|PII Blur API"
    "audio-copyright-api|http://audio-copyright-api:8000/health|Audio Copyright API"
    "mlflow-api|http://mlflow-api:8000/health|MLflow API"
)

if [[ -n "${PROTECTED_CONTAINERS:-}" ]]; then
    IFS=',' read -ra EXTRA <<< "$PROTECTED_CONTAINERS"
    STANDARD_CONTAINERS+=("${EXTRA[@]}")
fi

EXCLUDED=()
if [[ -n "${EXCLUDED_CONTAINERS:-}" ]]; then
    IFS=',' read -ra EXCLUDED <<< "$EXCLUDED_CONTAINERS"
fi

LOW_PRIORITY=()
if [[ -n "${LOW_PRIORITY_CONTAINERS:-}" ]]; then
    IFS=',' read -ra LOW_PRIORITY <<< "$LOW_PRIORITY_CONTAINERS"
fi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] $1" | tee -a "$LOG_DIR/watchdog.log"
}

audit() {
    local action="$1" target="$2" detail="${3:-}"
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] ACTION=${action} TARGET=${target} DETAIL=${detail}" >> "$AUDIT_LOG"
}

# ---------------------------------------------------------------------------
# Telegram alert formatting helpers
# ---------------------------------------------------------------------------
_sev_icon() {
    case "${1,,}" in
        critical) echo "🔴" ;;
        warning)  echo "🟡" ;;
        info)     echo "🔵" ;;
        ok|recovered) echo "✅" ;;
        *)        echo "⚪" ;;
    esac
}

_html_escape() {
    printf '%s' "$1" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g'
}

# Low-level send — JSON body + HTML parse mode (safe with all special chars)
send_telegram() {
    local msg="$1"
    [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${TELEGRAM_CHAT_ID:-}" ]] && return 0
    local payload
    payload=$(jq -n --arg chat "${TELEGRAM_CHAT_ID}" --arg text "$msg" \
        '{chat_id: $chat, text: $text, parse_mode: "HTML"}') || return 0
    curl -sf -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -H "Content-Type: application/json" \
        -d "$payload" \
        > /dev/null 2>&1 || log "WARN: Telegram send failed"
}

# Rich structured event card — named params, 5-section layout.
# Usage: send_alert_card \
#   --container <name>  --severity <critical|warning|info|ok> \
#   --event <type>      --problem <text>  --action <text> \
#   --agent <name>      --outcome <text>  --gitlab <ref>  --learning <text>
send_alert_card() {
    local container="" severity="warning" event_type="" problem=""
    local action="" agent="shml-watchdog" outcome="" gitlab_ref="" learning=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --container) container="$2"; shift 2 ;;
            --severity)  severity="$2";  shift 2 ;;
            --event)     event_type="$2"; shift 2 ;;
            --problem)   problem="$2";   shift 2 ;;
            --action)    action="$2";    shift 2 ;;
            --agent)     agent="$2";     shift 2 ;;
            --outcome)   outcome="$2";   shift 2 ;;
            --gitlab)    gitlab_ref="$2"; shift 2 ;;
            --learning)  learning="$2";  shift 2 ;;
            *) shift ;;
        esac
    done
    local icon ts host sev_upper div
    icon=$(_sev_icon "$severity")
    ts=$(date -u '+%Y-%m-%d %H:%M UTC')
    host=$(hostname -s)
    sev_upper=$(echo "$severity" | tr '[:lower:]' '[:upper:]')
    div="──────────────────────────"

    local msg
    msg="${icon} <b>SHML PLATFORM — ${sev_upper}</b>
${div}
<b>📦 Service</b>
  Container: <code>${container:-platform}</code>
  Event:     <code>${event_type:-alert}</code>
  Host:      <code>${host}</code>  ·  ${ts}"

    if [[ -n "$problem" ]]; then
        msg+="
${div}
<b>⚠️ Problem</b>
  $(_html_escape "${problem}")"
    fi

    if [[ -n "$action" ]]; then
        msg+="
${div}
<b>🔧 Remedy</b>
  $(_html_escape "${action}")
  Agent: <code>${agent}</code>"
    fi

    if [[ -n "$outcome" ]]; then
        msg+="
${div}
<b>📊 Post-Action State</b>
  $(_html_escape "${outcome}")"
    fi

    if [[ -n "$gitlab_ref" || -n "$learning" ]]; then
        msg+="
${div}
<b>📚 Learning</b>"
        [[ -n "$gitlab_ref" ]] && msg+="
  GitLab: $(_html_escape "${gitlab_ref}")"
        [[ -n "$learning" ]] && msg+="
  $(_html_escape "${learning}")"
    fi

    send_telegram "$msg"
}

# Backwards-compat wrapper: formats old 5-arg calls as a clean HTML event card
send_telegram_event() {
    local title="$1"
    local goal="$2"
    local systems="$3"
    local details="$4"
    local next_step="${5:-Observe next watchdog cycle}"
    local ts host div
    ts=$(date -u '+%Y-%m-%d %H:%M UTC')
    host=$(hostname -s)
    div="──────────────────────────"

    local msg
    msg="🚨 <b>${title}</b>
${div}
<b>📦 Systems:</b> <code>$(_html_escape "${systems}")</code>
<b>🖥️  Host:</b>    <code>${host}</code>  ·  ${ts}
${div}
<b>🎯 Goal</b>
  $(_html_escape "${goal}")
${div}
<b>📋 Details</b>
  $(_html_escape "${details}")
${div}
<b>➡️  Next</b>
  $(_html_escape "${next_step}")
<i>GPU: train=${TRAINING_GPU} display=${DISPLAY_GPU} | Agent: shml-watchdog</i>"
    send_telegram "$msg"
}

# ---------------------------------------------------------------------------
# GitLab issue creation (idempotent — won't duplicate issues for same alert)
# ---------------------------------------------------------------------------
GITLAB_UTIL="${PLATFORM_DIR}/scripts/platform/gitlab_utils.py"
GITLAB_PROJECT_ID="${GITLAB_PROJECT_ID:-2}"
GITLAB_LAST_ISSUE_IID=""

has_gitlab_event_support() {
    if [[ ! -f "$GITLAB_UTIL" ]]; then
        return 1
    fi
    if [[ -n "${GITLAB_API_TOKEN:-}" || -n "${GITLAB_AXELOFWAR_PERSONAL_ACCESS_TOKEN:-}" ]]; then
        return 0
    fi
    [[ -f "$PLATFORM_DIR/.env" ]] && grep -qE '^GITLAB_(API_TOKEN|AXELOFWAR_PERSONAL_ACCESS_TOKEN)=' "$PLATFORM_DIR/.env"
}

create_gitlab_issue() {
    # Usage: create_gitlab_issue "title" "description" "label1,label2"
    local title="$1"
    local description="${2:-}"
    local labels="${3:-source::watchdog}"
    local ts
    local update_comment
    local issue_json

    GITLAB_LAST_ISSUE_IID=""
    if ! has_gitlab_event_support; then
        log "WARN: No GitLab PAT available — skipping issue creation"
        return 0
    fi

    if [[ ! -f "$GITLAB_UTIL" ]]; then
        log "WARN: Missing GitLab utility at ${GITLAB_UTIL} — skipping issue creation"
        return 0
    fi

    ts=$(date -u '+%Y-%m-%d %H:%M UTC')
    update_comment="**Watchdog update** (${ts}):

${description}"

    if ! issue_json=$(GITLAB_PROJECT_ID="${GITLAB_PROJECT_ID}" \
        python3 "$GITLAB_UTIL" upsert-issue "$title" \
            --title "$title" \
            --description "$description" \
            --labels "$labels" \
            --comment "$update_comment" \
            --reopen 2>/dev/null); then
        log "WARN: GitLab issue creation failed for: ${title}"
        return 0
    fi

    GITLAB_LAST_ISSUE_IID=$(printf '%s' "$issue_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("iid", ""))' 2>/dev/null || true)
    if [[ -n "$GITLAB_LAST_ISSUE_IID" ]]; then
        log "GitLab: Upserted issue #${GITLAB_LAST_ISSUE_IID} — ${title}"
    else
        log "GitLab: Upserted issue — ${title}"
    fi

    return 0
}

close_gitlab_incident() {
    # Usage: close_gitlab_incident "incident title" "resolution comment"
    local title="$1"
    local comment="${2:-Resolved automatically by watchdog at $(date -u '+%Y-%m-%d %H:%M UTC')}"
    local issue_json

    if ! has_gitlab_event_support; then
        log "WARN: No GitLab PAT available — skipping incident close"
        return 0
    fi

    if [[ ! -f "$GITLAB_UTIL" ]]; then
        log "WARN: Missing GitLab utility at ${GITLAB_UTIL} — skipping incident close"
        return 0
    fi

    if ! issue_json=$(GITLAB_PROJECT_ID="${GITLAB_PROJECT_ID}" \
        python3 "$GITLAB_UTIL" resolve-issue "$title" \
            --comment "$comment" 2>/dev/null); then
        log "WARN: GitLab incident close failed for: ${title}"
        return 0
    fi

    local resolved
    resolved=$(printf '%s' "$issue_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("resolved", False))' 2>/dev/null || echo "False")
    if [[ "$resolved" == "True" ]]; then
        local iid
        iid=$(printf '%s' "$issue_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("iid", ""))' 2>/dev/null || true)
        log "GitLab: Closed incident #${iid} — ${title}"
    else
        log "GitLab: No open incident to close for: ${title} (may already be closed)"
    fi

    return 0
}

is_excluded() {
    local name="$1"
    for excl in "${EXCLUDED[@]}"; do
        [[ "$name" == "$excl" ]] && return 0
    done
    return 1
}

is_training_active() {
    local gpu_active=0
    local ray_active=0

    if command -v nvidia-smi &>/dev/null; then
        if nvidia-smi --id="${TRAINING_GPU}" --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -q "[0-9]"; then
            gpu_active=1
        fi
    fi

    if curl -sf --max-time 4 "http://ray-head:8265/api/jobs/" >/dev/null 2>&1; then
        local running_jobs
        running_jobs=$(curl -sf --max-time 4 "http://ray-head:8265/api/jobs/" 2>/dev/null | \
            jq '[.[] | select(.status == "RUNNING" or .status == "PENDING")] | length' 2>/dev/null || echo "0")
        if [[ "$running_jobs" =~ ^[0-9]+$ ]] && (( running_jobs > 0 )); then
            ray_active=1
        fi
    fi

    if (( gpu_active == 1 || ray_active == 1 )); then
        TRAINING_PROTECTED=1
        return 0
    fi

    return 1
}

is_training_sensitive_container() {
    local container="$1"
    local short_name="${container#${PLATFORM_PREFIX}-}"
    IFS=',' read -ra protected <<< "$TRAINING_SENSITIVE_CONTAINERS"

    for entry in "${protected[@]}"; do
        local target
        target=$(echo "$entry" | xargs)
        [[ -z "$target" ]] && continue

        if [[ "$container" == "$target" || "$short_name" == "$target" ]]; then
            return 0
        fi
    done

    return 1
}

get_restart_count() {
    local container="$1"
    local state_file="${STATE_DIR}/${container}.restarts"
    if [[ -f "$state_file" ]]; then
        local ts count
        read -r ts count < "$state_file"
        local now
        now=$(date +%s)
        if (( now - ts > 3600 )); then
            echo "0"
            return
        fi
        echo "$count"
    else
        echo "0"
    fi
}

increment_restart_count() {
    local container="$1"
    local state_file="${STATE_DIR}/${container}.restarts"
    local now count
    now=$(date +%s)
    count=$(get_restart_count "$container")
    echo "$now $((count + 1))" > "$state_file"
}

cooldown_active() {
    local container="$1"
    local state_file="${STATE_DIR}/${container}.restarts"
    [[ -f "$state_file" ]] || return 1

    local ts count now
    read -r ts count < "$state_file"
    now=$(date +%s)
    (( count >= MAX_RESTARTS && now - ts < COOLDOWN_SECONDS ))
}

is_low_priority_container() {
    local container="$1"
    local short_name="${container#${PLATFORM_PREFIX}-}"
    for entry in "${LOW_PRIORITY[@]}"; do
        local target
        target=$(echo "$entry" | xargs)
        [[ -z "$target" ]] && continue
        if [[ "$container" == "$target" || "$short_name" == "$target" ]]; then
            return 0
        fi
    done
    return 1
}

record_resource_snapshot() {
    local mem_line swap_line gpu_lines loadavg
    loadavg=$(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null || echo "n/a")
    mem_line=$(awk '/MemTotal/ {t=$2} /MemAvailable/ {a=$2} END {if (t>0) printf "mem_used_pct=%.1f mem_available_mib=%.0f", (100*(t-a)/t), a/1024; else print "mem_used_pct=0 mem_available_mib=0"}' /proc/meminfo 2>/dev/null)
    swap_line=$(awk '/SwapTotal/ {t=$2} /SwapFree/ {f=$2} END {if (t>0) printf "swap_used_pct=%.1f", (100*(t-f)/t); else print "swap_used_pct=0"}' /proc/meminfo 2>/dev/null)
    gpu_lines=$(nvidia-smi --query-gpu=index,utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits 2>/dev/null | awk -F', ' '{printf "gpu%s_util=%s gpu%s_mem_used_mib=%s gpu%s_mem_total_mib=%s gpu%s_temp_c=%s ", $1,$2,$1,$3,$1,$4,$1,$5}')
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] loadavg=${loadavg} ${mem_line} ${swap_line} ${gpu_lines}" >> "$RESOURCE_LOG"
}

check_host_pressure() {
    local mem_pct=0 swap_pct=0
    mem_pct=$(awk '/MemTotal/ {t=$2} /MemAvailable/ {a=$2} END {if (t>0) printf "%.0f", (100*(t-a)/t); else print "0"}' /proc/meminfo 2>/dev/null)
    swap_pct=$(awk '/SwapTotal/ {t=$2} /SwapFree/ {f=$2} END {if (t>0) printf "%.0f", (100*(t-f)/t); else print "0"}' /proc/meminfo 2>/dev/null)

    if (( mem_pct < HOST_MEMORY_SOFT_WATERMARK_PCT && swap_pct < HOST_SWAP_HIGH_WATERMARK_PCT )); then
        return 0
    fi

    local severity="soft"
    (( mem_pct >= HOST_MEMORY_HIGH_WATERMARK_PCT )) && severity="critical"
    local stopped=""

    for container in "${LOW_PRIORITY[@]}"; do
        is_excluded "$container" && continue
        if docker inspect --format='{{.State.Status}}' "$container" 2>/dev/null | grep -q '^running$'; then
            log "PRESSURE: stopping low-priority container ${container} (mem=${mem_pct}% swap=${swap_pct}%)"
            docker stop "$container" --time 20 >/dev/null 2>&1 || true
            stopped="${stopped} ${container}"
        fi
    done

    if [[ -n "$stopped" ]]; then
        send_telegram_event \
            "Host pressure guard (${severity})" \
            "Protect the desktop session and keep face-model training alive" \
            "host memory, swap, low-priority containers" \
            "Host memory=${mem_pct}% swap=${swap_pct}%. Stopped:${stopped}" \
            "Keep low-priority GPU/display workloads off until pressure clears"
        audit "HOST_PRESSURE" "host" "Mem=${mem_pct}% Swap=${swap_pct}% Stopped=${stopped}"
    fi
}

check_display_gpu_pressure() {
    command -v nvidia-smi >/dev/null 2>&1 || return 0

    local gpu_line util mem_used temp
    gpu_line=$(nvidia-smi --query-gpu=index,utilization.gpu,memory.used,temperature.gpu --format=csv,noheader,nounits 2>/dev/null | awk -F', ' -v gpu="$DISPLAY_GPU" '$1 == gpu {print $0}')
    [[ -n "$gpu_line" ]] || return 0

    util=$(echo "$gpu_line" | awk -F', ' '{print $2}')
    mem_used=$(echo "$gpu_line" | awk -F', ' '{print $3}')
    temp=$(echo "$gpu_line" | awk -F', ' '{print $4}')

    if (( util < DISPLAY_GPU_UTIL_WATERMARK_PCT && mem_used < DISPLAY_GPU_MEMORY_WATERMARK_MIB )); then
        return 0
    fi

    local stopped=""
    while read -r container; do
        [[ -z "$container" ]] && continue
        is_training_sensitive_container "$container" && continue
        if is_low_priority_container "$container"; then
            local gpu_info
            gpu_info=$(docker inspect --format='{{range .HostConfig.DeviceRequests}}{{.DeviceIDs}}{{end}}' "$container" 2>/dev/null || echo "")
            if [[ "$gpu_info" == *"${DISPLAY_GPU}"* ]]; then
                docker stop "$container" --time 20 >/dev/null 2>&1 || true
                stopped="${stopped} ${container}"
            fi
        fi
    done < <(docker ps --format '{{.Names}}' 2>/dev/null)

    if [[ -n "$stopped" ]]; then
        send_telegram_event \
            "Display GPU guard triggered" \
            "Prevent GNOME/VS Code freeze by protecting the desktop GPU" \
            "display GPU ${DISPLAY_GPU}, low-priority GPU workloads" \
            "GPU ${DISPLAY_GPU}: util=${util}% memory=${mem_used}MiB temp=${temp}°C. Stopped:${stopped}" \
            "Leave GPU ${DISPLAY_GPU} idle until desktop responsiveness is stable"
        audit "DISPLAY_GPU_PRESSURE" "GPU-${DISPLAY_GPU}" "Util=${util}% Mem=${mem_used}MiB Temp=${temp}C Stopped=${stopped}"
    fi
}

# ---------------------------------------------------------------------------
# GPU isolation — protect training
# ---------------------------------------------------------------------------
check_training_gpu_safety() {
    if ! command -v nvidia-smi &>/dev/null; then
        TRAINING_PROTECTED=0
        return 0
    fi

    # Detect active training processes on GPU 0
    if nvidia-smi --id="${TRAINING_GPU}" --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -q "[0-9]"; then
        TRAINING_PROTECTED=1
    else
        TRAINING_PROTECTED=0
    fi

    local training_gpu_mem
    training_gpu_mem=$(nvidia-smi --id="${TRAINING_GPU}" \
        --query-gpu=memory.used,memory.total \
        --format=csv,noheader,nounits 2>/dev/null) || return 0

    local used total
    used=$(echo "$training_gpu_mem" | cut -d',' -f1 | tr -d ' ')
    total=$(echo "$training_gpu_mem" | cut -d',' -f2 | tr -d ' ')

    if [[ -z "$used" || -z "$total" ]]; then
        return 0
    fi

    local usage_pct=$(( used * 100 / total ))

    # If training GPU is >95% full, check for non-training leakers
    if (( usage_pct > 95 )); then
        log "WARN: Training GPU ${TRAINING_GPU} at ${usage_pct}% (${used}/${total} MiB)"

        local gpu_procs
        gpu_procs=$(nvidia-smi --id="${TRAINING_GPU}" \
            --query-compute-apps=pid,process_name,used_gpu_memory \
            --format=csv,noheader 2>/dev/null) || gpu_procs=""

        if [[ -n "$gpu_procs" ]]; then
            while IFS=',' read -r pid pname mem; do
                mem=$(echo "$mem" | tr -d ' MiB')
                pname=$(echo "$pname" | tr -d ' ')
                # Skip known training processes
                if [[ "$pname" == *"train"* || "$pname" == *"rfdetr"* || "$pname" == *"ray"* || "$pname" == *"python"* ]]; then
                    continue
                fi
                if [[ "$mem" =~ ^[0-9]+$ ]] && (( mem > 1024 )); then
                    log "ALERT: Non-training process ${pname} (PID ${pid}) using ${mem} MiB on training GPU"
                    send_alert_card \
                        --container "${pname}" \
                        --severity "warning" \
                        --event "gpu_guard_intrusion" \
                        --problem "Non-training process ${pname} (PID ${pid}) is using ${mem} MiB on training GPU ${TRAINING_GPU}. This competes with the active training job." \
                        --action "Requesting GPU yield from gpu-manager to evict non-training workload" \
                        --agent "shml-watchdog" \
                        --outcome "GPU yield request sent. Training job protection active."
                    audit "GPU_INTRUSION" "$pname" "PID=${pid} GPU=${TRAINING_GPU} MEM=${mem}MiB"
                    request_gpu_yield "$pname"
                fi
            done <<< "$gpu_procs"
        fi
    fi
}

request_gpu_yield() {
    local process_name="$1"
    local response
    response=$(curl -sf -X POST "http://gpu-manager:8000/api/v1/yield" \
        -H "Content-Type: application/json" \
        -d "{\"gpu_id\": ${TRAINING_GPU}, \"reason\": \"watchdog: training protection\", \"source\": \"${process_name}\"}" \
        2>/dev/null) || {
        log "WARN: gpu-manager yield request failed for ${process_name}"
        return 1
    }
    log "OK: GPU yield requested for ${process_name}: ${response}"
    audit "GPU_YIELD_REQUEST" "$process_name" "GPU=${TRAINING_GPU}"
}

# ---------------------------------------------------------------------------
# Memory leak detection
# ---------------------------------------------------------------------------
check_memory_leaks() {
    for container in "${MEMORY_WATCH_CONTAINERS[@]}"; do
        is_excluded "$container" && continue

        # Get current memory usage
        local mem_raw
        mem_raw=$(docker stats --no-stream --format '{{.MemUsage}}' "$container" 2>/dev/null | head -1) || continue

        local mem_bytes
        mem_bytes=$(echo "$mem_raw" | awk -F'/' '{print $1}' | tr -d ' ')

        # Convert to MB
        local mem_mb=0
        if [[ "$mem_bytes" == *"GiB"* ]]; then
            mem_mb=$(echo "$mem_bytes" | tr -d 'GiB' | awk '{printf "%.0f", $1 * 1024}')
        elif [[ "$mem_bytes" == *"MiB"* ]]; then
            mem_mb=$(echo "$mem_bytes" | tr -d 'MiB' | awk '{printf "%.0f", $1}')
        elif [[ "$mem_bytes" == *"KiB"* ]]; then
            mem_mb=$(echo "$mem_bytes" | tr -d 'KiB' | awk '{printf "%.0f", $1 / 1024}')
        else
            continue
        fi

        local state_file="${MEMORY_DIR}/${container}.mem"
        local now
        now=$(date +%s)

        if [[ -f "$state_file" ]]; then
            local prev_ts prev_mb
            read -r prev_ts prev_mb < "$state_file"

            local elapsed=$(( now - prev_ts ))
            if (( elapsed > 1800 )); then  # Check after 30 min baseline
                local growth=$(( mem_mb - prev_mb ))
                local growth_per_hour=0
                if (( elapsed > 0 )); then
                    growth_per_hour=$(( growth * 3600 / elapsed ))
                fi

                if (( growth_per_hour > MEMORY_LEAK_THRESHOLD_MB )); then
                    TOTAL_MEMORY_LEAKS=$((TOTAL_MEMORY_LEAKS + 1))
                    log "LEAK: ${container} growing ${growth_per_hour} MB/hr (${prev_mb}→${mem_mb} MB over $((elapsed/60))m)"
                    send_alert_card \
                        --container "${container}" \
                        --severity "warning" \
                        --event "memory_leak" \
                        --problem "Memory growing at ${growth_per_hour} MB/hr (${prev_mb} MB → ${mem_mb} MB over $((elapsed / 60))min). Threshold=${MEMORY_LEAK_THRESHOLD_MB} MB/hr." \
                        --action "Evaluating preemptive restart if usage exceeds 80% of container memory limit" \
                        --agent "shml-watchdog" \
                        --outcome "Escalating to memory leak handler. Restart may be issued." \
                        --gitlab "Issue created — type::bug priority::high source::watchdog"
                    audit "MEMORY_LEAK" "$container" "Growth=${growth_per_hour}MB/hr Now=${mem_mb}MB"
                    create_gitlab_issue \
                        "Memory Leak: ${container}" \
                        "Container \`${container}\` is leaking memory.\n\nGrowth: ${growth_per_hour} MB/hr\nCurrent: ${mem_mb} MB (was ${prev_mb} MB)\nWindow: $((elapsed / 60)) minutes\n\nDetected by watchdog at $(date -u '+%Y-%m-%d %H:%M UTC')" \
                        "type::bug,priority::high,status::todo,source::watchdog,component::infra"
                    handle_memory_leak "$container" "$mem_mb" "$growth_per_hour"
                fi

                echo "$now $mem_mb" > "$state_file"
            fi
        else
            echo "$now $mem_mb" > "$state_file"
        fi
    done
}

handle_memory_leak() {
    local container="$1"
    local current_mb="$2"
    local growth_rate="$3"

    # Get container memory limit
    local mem_limit
    mem_limit=$(docker inspect --format='{{.HostConfig.Memory}}' "$container" 2>/dev/null) || mem_limit=0

    local limit_mb=0
    if (( mem_limit > 0 )); then
        limit_mb=$(( mem_limit / 1048576 ))
    fi

    # Preemptive restart at >80% of limit
    if (( limit_mb > 0 && current_mb * 100 / limit_mb > 80 )); then
        log "PREEMPTIVE: ${container} at ${current_mb}/${limit_mb} MB (${growth_rate} MB/hr)"
        send_alert_card \
            --container "${container}" \
            --severity "warning" \
            --event "preemptive_restart" \
            --problem "Memory at $((current_mb * 100 / limit_mb))% of limit (${current_mb}/${limit_mb} MB). Growing at ${growth_rate} MB/hr." \
            --action "Issuing preemptive restart before OOM occurs to preserve service continuity" \
            --agent "shml-watchdog" \
            --outcome "Restart in progress. Memory state will be cleared."
        audit "PREEMPTIVE_RESTART" "$container" "Mem=${current_mb}/${limit_mb}MB Growth=${growth_rate}MB/hr"
        restart_container "$container" "memory-leak-preemptive" || true
        return
    fi

    # For agent-service: clear internal state by restarting if growth is aggressive
    if [[ "$container" == *"agent-service"* ]]; then
        if (( growth_rate > MEMORY_LEAK_THRESHOLD_MB * 2 )); then
            log "REMEDIATE: agent-service aggressive leak (${growth_rate} MB/hr) — restarting"
            restart_container "$container" "agent-service-memory-leak" || true
        fi
    fi

    # For inference-gateway: httpx client pool leak — restart cleans it
    if [[ "$container" == *"inference-gateway"* ]]; then
        if (( growth_rate > MEMORY_LEAK_THRESHOLD_MB )); then
            log "REMEDIATE: inference-gateway connection pool leak — restarting"
            restart_container "$container" "gateway-connection-pool-leak" || true
        fi
    fi
}

check_oom_killed() {
    local oom_containers
    oom_containers=$(docker ps -a --filter "status=exited" \
        --format '{{.Names}} {{.Status}}' 2>/dev/null | \
        grep -i "137" || true)

    if [[ -n "$oom_containers" ]]; then
        while read -r name status; do
            [[ -z "$name" ]] && continue
            TOTAL_OOM_KILLS=$((TOTAL_OOM_KILLS + 1))
            log "OOM: Container ${name}: ${status}"
            audit "OOM_KILLED" "$name" "$status"

            # ── Training-active + low-priority: accept kill, mark blocked ──────
            if is_low_priority_container "$name" && is_training_active; then
                log "SKIP: ${name} is low-priority and training is active — OOM is expected, not a bug"
                send_alert_card \
                    --container "${name}" \
                    --severity "info" \
                    --event "oom_training_expected" \
                    --problem "OOM-killed by kernel. Exit: ${status}. Training is occupying host RAM — low-priority container yields to active training job on GPU ${TRAINING_GPU}." \
                    --action "No restart attempted. Low-priority policy: training jobs take precedence over display/UI containers." \
                    --agent "shml-watchdog" \
                    --outcome "Container suspended for training duration. Will auto-recover when training completes." \
                    --learning "Low-priority OOM policy enforced. GitLab issue updated to status::blocked."

                create_gitlab_issue \
                    "OOM Kill: ${name}" \
                    "Container \`${name}\` was OOM-killed because training is occupying host RAM.\n\nThis is expected behaviour while training is active — \`${name}\` is low-priority and will not be restarted until training completes.\n\nAction: No restart attempted. Container will be brought back when training finishes.\n\nStatus: ${status}\nTime: $(date -u '+%Y-%m-%d %H:%M UTC')" \
                    "type::bug,status::blocked,source::watchdog,component::fiftyone,priority::low"
                audit "OOM_BLOCKED_TRAINING" "$name" "low-priority container suppressed during active training"
                continue
            fi

            # ── Standard OOM path ───────────────────────────────────────────────
            send_alert_card \
                --container "${name}" \
                --severity "critical" \
                --event "oom_kill" \
                --problem "Container killed by Linux OOM manager. Exit: ${status}. Host RAM under pressure." \
                --action "Issuing docker restart (subject to GPU/training policy check)" \
                --agent "shml-watchdog" \
                --outcome "Restart in progress. See recovery event for post-restart state." \
                --gitlab "Issue created — type::bug priority::high source::watchdog"
            create_gitlab_issue \
                "OOM Kill: ${name}" \
                "Container \`${name}\` was OOM-killed.\n\nStatus: ${status}\n\nDetected by watchdog at $(date -u '+%Y-%m-%d %H:%M UTC')" \
                "type::bug,priority::high,status::todo,source::watchdog,component::infra"

            # Check if container uses training GPU exclusively
            local gpu_info
            gpu_info=$(docker inspect --format='{{range .HostConfig.DeviceRequests}}{{.DeviceIDs}}{{end}}' "$name" 2>/dev/null || echo "")

            if [[ "$gpu_info" == *"${TRAINING_GPU}"* ]] && [[ "$gpu_info" != *"${WATCHDOG_GPU}"* ]]; then
                log "SKIP: ${name} uses training GPU — NOT restarting"
                send_alert_card \
                    --container "${name}" \
                    --severity "warning" \
                    --event "oom_restart_skipped" \
                    --problem "OOM-killed container uses exclusive training GPU ${TRAINING_GPU}. Restart suppressed to protect active training job." \
                    --action "No restart issued. Container will remain stopped until training completes." \
                    --agent "shml-watchdog" \
                    --outcome "Container stopped. Training on GPU ${TRAINING_GPU} protected."
                audit "OOM_SKIP_TRAINING" "$name" "Uses GPU ${TRAINING_GPU}"
            else
                restart_container "$name" "oom-killed" || true
            fi
        done <<< "$oom_containers"
    fi
}

# ---------------------------------------------------------------------------
# Container health
# ---------------------------------------------------------------------------
check_container_health() {
    local container="$1"
    local severity="${2:-standard}"

    local status
    status=$(docker inspect --format='{{.State.Status}}' "$container" 2>/dev/null) || {
        return 2
    }

    if [[ "$status" != "running" ]]; then
        log "ALERT: Container ${container} is ${status}"
        return 1
    fi

    local health
    health=$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container" 2>/dev/null) || health="unknown"

    if [[ "$health" == "unhealthy" ]]; then
        log "ALERT: Container ${container} is unhealthy"
        return 1
    fi

    return 0
}

check_prometheus() {
    if curl -sf "${PROMETHEUS_URL}/-/healthy" > /dev/null 2>&1; then
        return 0
    fi
    log "WARN: Prometheus not reachable at ${PROMETHEUS_URL}"
    return 1
}

check_gitlab_application_health() {
    if curl -fsS --max-time 8 "${GITLAB_INTERNAL_HEALTH_URL}" > /dev/null 2>&1; then
        return 0
    fi

    log "ALERT: GitLab application endpoint unhealthy at ${GITLAB_INTERNAL_HEALTH_URL}"
    send_telegram_event \
        "GitLab application health failed" \
        "Keep GitLab available for CI, issue tracking, and runner coordination" \
        "gitlab, traefik, watchdog" \
        "Endpoint check failed: ${GITLAB_INTERNAL_HEALTH_URL}" \
        "Watchdog will attempt a controlled restart if policy allows"
    audit "GITLAB_APP_UNHEALTHY" "${PLATFORM_PREFIX}-gitlab" "URL=${GITLAB_INTERNAL_HEALTH_URL}"
    create_gitlab_issue \
        "GitLab Application Health Check Failed" \
        "GitLab endpoint \`${GITLAB_INTERNAL_HEALTH_URL}\` is not responding.\n\nDetected by watchdog at $(date -u '+%Y-%m-%d %H:%M UTC')" \
        "type::bug,priority::critical,status::todo,source::watchdog,component::infra"
    return 1
}

# ---------------------------------------------------------------------------
# HTTP-level health probes for all platform services
# ---------------------------------------------------------------------------
# Checks the HTTP_SERVICES array (container|url|label).
# HTTP 2xx = healthy.  401/403 = OAuth gate active = healthy.
# Timeout or 5xx = unhealthy → restart the container.
# Returns 0 if all healthy, 1 if any probe failed.
check_http_services() {
    local failed=0
    local http_fail_list=""

    for entry in "${HTTP_SERVICES[@]}"; do
        IFS='|' read -r restart_target probe_url label <<< "$entry"

        # Skip if container is not running (container-level watchdog handles that)
        local cstatus
        cstatus=$(docker inspect --format='{{.State.Status}}' "$restart_target" 2>/dev/null) || cstatus="missing"
        if [[ "$cstatus" != "running" ]]; then
            continue
        fi

        # Probe the HTTP endpoint
        # Docker's embedded DNS (127.0.0.11) works via getent but not via
        # musl/curl's c-ares resolver on Alpine (Tailscale search domains interfere).
        # Resolve hostname first via getent, then probe with --resolve.
        local http_code resolved_ip probe_host probe_port
        probe_host=$(echo "$probe_url" | sed -E 's|https?://([^:/]+).*|\1|')
        probe_port=$(echo "$probe_url" | sed -E 's|https?://[^:/]+:([0-9]+).*|\1|')
        resolved_ip=$(getent hosts "$probe_host" 2>/dev/null | awk '{print $1; exit}')
        if [[ -z "$resolved_ip" ]]; then
            http_code="000"
        else
            http_code=$(curl -s --max-time 8 --resolve "${probe_host}:${probe_port}:${resolved_ip}" -o /dev/null -w "%{http_code}" "$probe_url" 2>/dev/null) || http_code="000"
        fi

        # 2xx = healthy; 401/403 = OAuth gate (service is up); anything else = problem
        if [[ "$http_code" =~ ^(2[0-9][0-9]|3[0-9][0-9]|401|403)$ ]]; then
            continue
        fi

        # Failed probe
        log "HTTP-PROBE: ${label} (${restart_target}) returned ${http_code} from ${probe_url}"
        failed=1
        http_fail_list="${http_fail_list} ${label}(${http_code})"

        if (( IS_PAUSED == 0 )); then
            if ! is_excluded "$restart_target"; then
                send_telegram_event \
                    "HTTP probe failed: ${label}" \
                    "Restore the service before it cascades into auth/UI outages" \
                    "${restart_target}, traefik, watchdog" \
                    "HTTP ${http_code} from ${probe_url}. Restart target: ${restart_target}" \
                    "Watchdog is issuing a single controlled restart"
                audit "HTTP_PROBE_FAIL" "$restart_target" "Code=${http_code} URL=${probe_url}"
                restart_container "$restart_target" "http-probe-${http_code}" || true
            fi
        fi
    done

    if (( failed == 1 )); then
        log "HTTP-PROBE: Failed services:${http_fail_list}"
    fi

    return "$failed"
}

check_gpu_health() {
    if ! command -v nvidia-smi &>/dev/null; then
        return 0
    fi

    local gpu_status
    gpu_status=$(nvidia-smi --query-gpu=index,gpu_name,temperature.gpu,utilization.gpu,memory.used,memory.total \
        --format=csv,noheader 2>/dev/null) || {
        log "WARN: nvidia-smi failed"
        send_telegram_event \
            "GPU telemetry failed" \
            "Keep host and training visibility intact" \
            "nvidia-smi, watchdog, GPU monitoring" \
            "nvidia-smi command failed inside the watchdog container" \
            "Watchdog will retry next cycle"
        audit "GPU_ERROR" "nvidia-smi" "Command failed"
        return 1
    }

    while IFS=',' read -r idx name temp util mem_used mem_total; do
        idx=$(echo "$idx" | tr -d ' ')
        temp=$(echo "$temp" | tr -d ' ')
        if [[ "$temp" =~ ^[0-9]+$ ]] && (( temp > 90 )); then
            log "CRITICAL: GPU ${idx} at ${temp}°C — thermal throttling"
            send_telegram_event \
                "GPU thermal event" \
                "Prevent a display hang or CUDA reset" \
                "GPU ${idx}, desktop session, training/inference" \
                "${name} is at ${temp}°C" \
                "Reduce GPU load immediately and inspect cooling"
            audit "GPU_THERMAL" "GPU-${idx}" "Temp=${temp}°C"
        fi
    done <<< "$gpu_status"
}

# ---------------------------------------------------------------------------
# Autonomous agent orchestration for cross-service resolution
# ---------------------------------------------------------------------------
request_agent_resolution() {
    local issue_type="$1"
    local description="$2"
    local containers_affected="$3"

    log "AGENT: Requesting autonomous resolution for ${issue_type}"

    # ── Phase 1: Try shl-nano fast diagnosis (T8.5) ───────────────────────
    # shl-nano is a small domain model running on GPU 1 at port 8021.
    # It provides a fast JSON diagnosis in < 2s without triggering the full
    # ACE agent workflow. Only escalate to Phase 2 if requires_escalation=true.
    if [[ -n "${NANO_SERVICE_URL:-}" ]]; then
        local nano_prompt="Watchdog alert: ACTION=${issue_type} TARGET=${containers_affected} DETAIL=${description} Time=$(date -u '+%Y-%m-%dT%H:%M:%SZ'). Diagnose and respond with JSON."
        local nano_response
        nano_response=$(curl -sf -X POST "${NANO_SERVICE_URL}/v1/chat/completions" \
            -H "Content-Type: application/json" \
            -d "{\"model\":\"shl-nano\",\"messages\":[{\"role\":\"user\",\"content\":$(printf '%s' "$nano_prompt" | jq -Rs '.' 2>/dev/null || echo '\"watchdog alert\"')}],\"max_tokens\":256,\"temperature\":0.1}" \
            --max-time 5 2>/dev/null) || nano_response=""

        if [[ -n "$nano_response" ]]; then
            local nano_text
            nano_text=$(echo "$nano_response" | jq -r '.choices[0].message.content // ""' 2>/dev/null) || nano_text=""
            local nano_requires_escalation
            nano_requires_escalation=$(echo "$nano_text" | jq -r '.requires_escalation // false' 2>/dev/null) || nano_requires_escalation="false"
            local nano_severity
            nano_severity=$(echo "$nano_text" | jq -r '.severity // "info"' 2>/dev/null) || nano_severity="info"
            local nano_action
            nano_action=$(echo "$nano_text" | jq -r '.recommended_action // ""' 2>/dev/null) || nano_action=""
            local nano_restart
            nano_restart=$(echo "$nano_text" | jq -r '.restart_order // [] | join(" ")' 2>/dev/null) || nano_restart=""

            log "NANO DIAGNOSIS: severity=${nano_severity} escalate=${nano_requires_escalation}"
            audit "NANO_DIAGNOSIS" "$issue_type" "sev=${nano_severity} action=${nano_action:0:80}"

            if [[ "$nano_requires_escalation" == "false" && "$nano_severity" != "critical" ]]; then
                # nano handled it — execute recommended action without full agent
                send_alert_card \
                    --container "${containers_affected}" \
                    --severity "${nano_severity}" \
                    --event "nano_diagnosis" \
                    --problem "Cross-service issue detected: ${issue_type}" \
                    --action "${nano_action:-See audit log for nano-directed resolution}" \
                    --agent "shl-nano (T8.5 fast domain model — GPU ${WATCHDOG_GPU}, sub-2s inference)" \
                    --outcome "Resolved by shl-nano without full agent escalation. Severity: ${nano_severity}." \
                    --learning "shl-nano decision logged to audit trail. Pattern contributes to next T8 training cycle."
                if [[ -n "$nano_restart" ]]; then
                    log "NANO: Restart order: ${nano_restart}"
                    for container in $nano_restart; do
                        restart_container "$container" "nano-directed-${issue_type}" || true
                        sleep 10
                    done
                fi
                audit "NANO_RESOLVED" "$issue_type" "No escalation needed"
                return 0
            fi

            log "AGENT: Nano flagged escalation (sev=${nano_severity}) — calling full agent"
        fi
    fi

    # ── Phase 2: Full agent-service resolution (original behavior) ────────
    local task="You are the platform watchdog autonomous agent. A cross-service issue detected.

Issue: ${issue_type}
Details: ${description}
Affected: ${containers_affected}
Time: $(date -u '+%Y-%m-%dT%H:%M:%SZ')

Instructions:
1. Diagnose root cause by checking logs and health endpoints
2. Determine if cascading failure (postgres→fusionauth→oauth→all UIs)
3. Suggest correct restart order for affected services
4. Check if GPU services need to yield before restart
5. Report findings as JSON

Respond: {\"diagnosis\": \"...\", \"root_cause\": \"...\", \"restart_order\": [...], \"gpu_yield_needed\": bool, \"severity\": \"critical|warning|info\"}"

    local response
    response=$(curl -sf -X POST "${AGENT_SERVICE_URL}/api/v1/agent/execute" \
        -H "Content-Type: application/json" \
        -d "{
            \"task\": $(printf '%s' "$task" | jq -Rs '.' 2>/dev/null || echo "\"cross-service issue\""),
            \"session_id\": \"watchdog-$(date +%s)\",
            \"user_id\": \"watchdog\",
            \"role\": \"admin\"
        }" \
        --max-time 60 2>/dev/null) || {
        log "WARN: Agent service unavailable for resolution"
        return 1
    }

    log "AGENT RESPONSE: $(echo "$response" | head -c 500)"
    audit "AGENT_RESOLUTION" "$issue_type" "Response received"

    # Extract restart order from agent response
    local restart_order
    restart_order=$(echo "$response" | jq -r '
        (.answer // .response // "") |
        capture("\\{(?<json>[^}]+)\\}") |
        .json | "{" + . + "}" |
        fromjson | .restart_order // [] | join(" ")
    ' 2>/dev/null) || restart_order=""

    if [[ -n "$restart_order" ]]; then
        log "AGENT: Restart order: ${restart_order}"
        send_alert_card \
            --container "${containers_affected}" \
            --severity "warning" \
            --event "agent_resolution" \
            --problem "Cascading failure: ${issue_type}" \
            --action "Agent-directed restart sequence: ${restart_order}" \
            --agent "shml-agent-service (ACE full orchestration — cross-service dependency analysis)" \
            --outcome "Executing agent restart sequence. Services brought up in dependency order." \
            --learning "Agent diagnosis and restart order logged. Cross-service dependency pattern recorded."
        audit "AGENT_RESTART_ORDER" "$issue_type" "Order: ${restart_order}"

        for container in $restart_order; do
            restart_container "$container" "agent-directed-${issue_type}" || true
            sleep 10
        done
    else
        log "AGENT: No restart order extracted — falling back to sequential restart"
        # Fallback: restart affected containers in dependency order
        for container in $containers_affected; do
            restart_container "$container" "cascading-${issue_type}" || true
            sleep 10
        done
    fi
}

detect_cascading_failure() {
    local unhealthy_list="$1"
    local count
    count=$(echo "$unhealthy_list" | wc -w)

    if (( count >= 2 )); then  # #531: lowered from 3→2 for faster autonomous escalation
        TOTAL_AGENT_ESCALATIONS=$((TOTAL_AGENT_ESCALATIONS + 1))
        log "CASCADE: ${count} containers unhealthy — requesting agent analysis"
        request_agent_resolution \
            "cascading_failure" \
            "${count} containers unhealthy: ${unhealthy_list}" \
            "$unhealthy_list" || log "WARN: Agent resolution unavailable, will retry next cycle"
        return 0
    fi
    return 1
}

# ---------------------------------------------------------------------------
# Platform state discovery
# ---------------------------------------------------------------------------
discover_platform_state() {
    log "DISCOVERY: Collecting full platform state..."

    local now
    now=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

    # Container inventory (jq -s slurps lines into array)
    local containers_json
    containers_json=$(docker ps --format '{"name":"{{.Names}}","image":"{{.Image}}","status":"{{.Status}}"}' 2>/dev/null | \
        jq -s '.' 2>/dev/null) || containers_json="[]"

    # UI service status
    local ui_status=""
    for entry in "${UI_SERVICES[@]}"; do
        IFS='|' read -r svc_name path label <<< "$entry"
        local svc_status="down"
        if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "$svc_name"; then
            svc_status="running"
        fi
        ui_status="${ui_status}${svc_name}=${svc_status} "
    done

    # GPU state
    local gpu_json="[]"
    if command -v nvidia-smi &>/dev/null; then
        gpu_json=$(nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu,temperature.gpu \
            --format=csv,noheader 2>/dev/null | \
            awk -F', ' -v tgpu="${TRAINING_GPU}" '{
                role = ($1 == tgpu) ? "training (PROTECTED)" : "inference/watchdog"
                printf "{\"index\":%d,\"name\":\"%s\",\"memory_used\":\"%s\",\"memory_total\":\"%s\",\"utilization\":\"%s\",\"temperature\":\"%s\",\"role\":\"%s\"}\n", $1, $2, $3, $4, $5, $6, role
            }' | jq -s '.' 2>/dev/null) || gpu_json="[]"
    fi

    # Active training jobs from Ray
    local training_json="[]"
    training_json=$(curl -sf "http://ray-head:8265/api/jobs/" --max-time 5 2>/dev/null | \
        jq '[.[] | select(.status == "PENDING" or .status == "RUNNING") | {id: .submission_id, status: .status, entrypoint: (.entrypoint // "?")[0:80]}]' 2>/dev/null) || training_json="[]"

    # Alertmanager alerts
    local alerts_json="[]"
    alerts_json=$(curl -sf "http://alertmanager:9093/api/v2/alerts" --max-time 5 2>/dev/null | \
        jq '[.[:20][] | {name: (.labels.alertname // "?"), severity: (.labels.severity // "?")}]' 2>/dev/null) || alerts_json="[]"

    local container_count
    container_count=$(docker ps -q 2>/dev/null | wc -l) || container_count=0
    local unhealthy_count
    unhealthy_count=$(docker ps --filter "health=unhealthy" -q 2>/dev/null | wc -l) || unhealthy_count=0

    # Write state file (use jq to safely build JSON without bash interpolation)
    jq -n \
        --arg ts "$now" \
        --argjson count "${container_count:-0}" \
        --argjson unhealthy "${unhealthy_count:-0}" \
        --argjson containers "$containers_json" \
        --arg ui "$ui_status" \
        --argjson gpus "$gpu_json" \
        --argjson training "$training_json" \
        --argjson alerts "$alerts_json" \
        --argjson tgpu "${TRAINING_GPU}" \
        --argjson wgpu "${WATCHDOG_GPU}" \
        --argjson interval "${CHECK_INTERVAL}" \
        --argjson maxr "${MAX_RESTARTS}" \
        --argjson mlt "${MEMORY_LEAK_THRESHOLD_MB}" \
        '{
            timestamp: $ts,
            containers: {total: $count, unhealthy: $unhealthy, inventory: $containers},
            ui_services: ($ui | split(" ") | map(select(. != ""))),
            gpus: $gpus,
            training_jobs: $training,
            alerts: $alerts,
            watchdog: {training_gpu: $tgpu, watchdog_gpu: $wgpu, check_interval: $interval, max_restarts: $maxr, memory_leak_threshold_mb: $mlt}
        }' > "$DISCOVERY_FILE" 2>/dev/null || log "WARN: State discovery JSON failed"

    log "DISCOVERY: ${container_count} containers, ${unhealthy_count} unhealthy, UIs: ${ui_status}"
    audit "DISCOVERY" "platform" "Total=${container_count} Unhealthy=${unhealthy_count}"
}

# ---------------------------------------------------------------------------
# Remediation
# ---------------------------------------------------------------------------
restart_container() {
    local container="$1"
    local reason="${2:-unhealthy}"

    if cooldown_active "$container"; then
        log "COOLDOWN: ${container} still within ${COOLDOWN_SECONDS}s cooldown window"
        return 1
    fi

    # Low-priority containers (e.g. fiftyone) are OOM-killed repeatedly when training is active.
    # Do not attempt restart — it will just be killed again, triggering throttle issues.
    if is_low_priority_container "$container" && is_training_active; then
        log "DEFER: ${container} is low-priority and training is active — skipping restart (will recover when training ends)"
        audit "RESTART_DEFER_LOW_PRIORITY" "$container" "Reason=${reason} training active"
        return 1
    fi

    if is_training_sensitive_container "$container" && is_training_active; then
        log "PROTECT: Deferring restart of ${container} (${reason}) — training activity detected on GPU ${TRAINING_GPU}"
        send_telegram "🛡️ <b>Training Protected</b>: Deferred restart of <code>${container}</code> (reason: ${reason}).
Training active on GPU ${TRAINING_GPU}. Restart will be retried when training completes."
        audit "RESTART_DEFER_TRAINING" "$container" "Reason=${reason} GPU=${TRAINING_GPU}"
        return 1
    fi

    # GPU safety — never restart something that disrupts training GPU
    local gpu_info
    gpu_info=$(docker inspect --format='{{range .HostConfig.DeviceRequests}}{{.DeviceIDs}}{{end}}' "$container" 2>/dev/null || echo "")

    if [[ "$gpu_info" == *"${TRAINING_GPU}"* ]] && [[ "$gpu_info" != *"${WATCHDOG_GPU}"* ]]; then
        local training_active
        training_active=$(nvidia-smi --id="${TRAINING_GPU}" --query-compute-apps=pid --format=csv,noheader 2>/dev/null | wc -l || echo "0")
        if (( training_active > 0 )); then
            log "PROTECT: Skipping restart of ${container} — training active on GPU ${TRAINING_GPU}"
            send_telegram "🛡️ <b>Training Protected</b>: Restart of <code>${container}</code> suppressed.
GPU ${TRAINING_GPU} is actively running a training job. Avoiding VRAM disruption."
            audit "RESTART_SKIP_TRAINING" "$container" "Training active on GPU ${TRAINING_GPU}"
            return 1
        fi
    fi

    local count
    count=$(get_restart_count "$container")
    if (( count >= MAX_RESTARTS )); then
        log "THROTTLE: ${container} hit ${count}/${MAX_RESTARTS} restarts"
        audit "THROTTLE" "$container" "Count=${count}/${MAX_RESTARTS}"
        # Don't create throttle issues for low-priority containers during training —
        # the repeated restarts are caused by training-time OOM, not a real bug.
        if is_low_priority_container "$container" && is_training_active; then
            log "SKIP THROTTLE ISSUE: ${container} is low-priority and training is active"
            return 1
        fi
        send_alert_card \
            --container "${container}" \
            --severity "critical" \
            --event "restart_throttle" \
            --problem "${container} has been restarted ${count}/${MAX_RESTARTS} times this hour. Automated cooldown of ${COOLDOWN_SECONDS}s engaged to prevent a restart loop." \
            --action "No further automated restarts until cooldown expires. GitLab issue created for manual review." \
            --agent "shml-watchdog" \
            --outcome "Container remains in current failing state. Manual intervention required." \
            --gitlab "Issue created — type::bug priority::critical source::watchdog" \
            --learning "Repeated-restart pattern recorded in audit log. Review root cause and clear restart counter before next attempt."
        create_gitlab_issue \
            "Container Throttled: ${container}" \
            "Container \`${container}\` has been restarted ${count}/${MAX_RESTARTS} times in the last hour.\nManual intervention required.\n\nDetected by watchdog at $(date -u '+%Y-%m-%d %H:%M UTC')" \
            "type::bug,priority::critical,status::todo,source::watchdog,component::infra"
        return 1
    fi

    # #531: LLM diagnosis before the final restart attempt (gives agent context before we exhaust retries)
    if (( count + 1 >= MAX_RESTARTS )); then
        log "DIAGNOSE: ${container} on final restart attempt — requesting LLM root-cause analysis"
        request_agent_resolution \
            "pre_final_restart" \
            "${container} is about to receive its final automated restart (attempt $((count+1))/${MAX_RESTARTS}). Reason: ${reason}. Perform root-cause analysis and recommend fix before restart loop exhausts." \
            "$container" || log "WARN: LLM diagnosis unavailable — proceeding with restart"
    fi

    log "REMEDIATE: Restarting ${container} (${reason}, attempt $((count+1))/${MAX_RESTARTS})"
    send_alert_card \
        --container "${container}" \
        --severity "warning" \
        --event "controlled_restart" \
        --problem "Container requires restart. Reason: ${reason}." \
        --action "docker restart --timeout 30 (attempt $((count+1))/${MAX_RESTARTS} — max ${MAX_RESTARTS}/hr)" \
        --agent "shml-watchdog" \
        --outcome "Restart issued. Health validation in 15s."
    audit "RESTART" "$container" "Reason=${reason} Attempt=$((count+1))/${MAX_RESTARTS}"

    if docker restart "$container" --timeout 30 2>/dev/null; then
        increment_restart_count "$container"
        TOTAL_RESTARTS=$((TOTAL_RESTARTS + 1))
        log "OK: ${container} restart issued"
        sleep 15

        if check_container_health "$container" > /dev/null 2>&1; then
            log "OK: ${container} recovered"
            send_alert_card \
                --container "${container}" \
                --severity "ok" \
                --event "container_recovered" \
                --problem "Container was restarted due to: ${reason}" \
                --action "docker restart --timeout 30 (attempt $((count+1))/${MAX_RESTARTS})" \
                --agent "shml-watchdog" \
                --outcome "✅ Passed post-restart health check. Container is running and healthy." \
                --learning "Restart resolved the issue. Monitoring at ${CHECK_INTERVAL}s intervals. Pattern logged to audit trail."
            audit "RECOVERED" "$container" "Healthy after restart"
            local _recovery_comment="Container ${container} recovered after restart (reason: ${reason}). Passed post-restart health check at $(date -u '+%Y-%m-%d %H:%M UTC')."
            case "$reason" in
                oom-killed)
                    close_gitlab_incident "OOM Kill: ${container}" "${_recovery_comment}" ;;
                memory-leak-preemptive)
                    close_gitlab_incident "Memory Leak: ${container}" "${_recovery_comment}" ;;
                *)
                    # Generic unhealthy / http-probe / gitlab-app-health restarts
                    close_gitlab_incident "Container Unhealthy: ${container}" "${_recovery_comment}"
                    close_gitlab_incident "GitLab Application Health Check Failed" "${_recovery_comment}" ;;
            esac
        else
            log "WARN: ${container} still unhealthy"
            audit "STILL_UNHEALTHY" "$container" "Post-restart failed"
        fi
    else
        log "ERROR: Failed to restart ${container}"
        send_alert_card \
            --container "${container}" \
            --severity "critical" \
            --event "restart_failed" \
            --problem "docker restart --timeout 30 returned non-zero exit code. Reason: ${reason}. Container is unresponsive to standard restart." \
            --action "Automated restart attempted and failed. Automated remediation exhausted for this cycle." \
            --agent "shml-watchdog" \
            --outcome "❌ Container in unknown/failed state. Manual intervention required." \
            --gitlab "Issue created — type::bug priority::critical source::watchdog" \
            --learning "Restart failure logged to audit trail. Next watchdog cycle will re-assess container state."
        audit "RESTART_FAILED" "$container" "Docker restart failed"
        create_gitlab_issue \
            "Restart Failed: ${container}" \
            "Docker restart command failed for \`${container}\`.\nReason: ${reason}\n\nDetected by watchdog at $(date -u '+%Y-%m-%d %H:%M UTC')" \
            "type::bug,priority::critical,status::todo,source::watchdog,component::infra"
    fi
}

# ---------------------------------------------------------------------------
# Pushgateway metrics export
# ---------------------------------------------------------------------------
push_metrics() {
    local monitored_count=$(( ${#CRITICAL_CONTAINERS[@]} + ${#STANDARD_CONTAINERS[@]} ))
    local uptime=$(($(date +%s) - WATCHDOG_START_TIME))

    cat <<METRICS | curl -sf --data-binary @- \
        "${PUSHGATEWAY_URL}/metrics/job/watchdog/instance/self-healing" \
        2>/dev/null || true
# HELP watchdog_up Whether the watchdog is running
# TYPE watchdog_up gauge
watchdog_up 1
# HELP watchdog_cycle_total Total monitoring cycles completed
# TYPE watchdog_cycle_total counter
watchdog_cycle_total ${cycle:-0}
# HELP watchdog_uptime_seconds Watchdog uptime in seconds
# TYPE watchdog_uptime_seconds gauge
watchdog_uptime_seconds $uptime
# HELP watchdog_unhealthy_containers Current unhealthy container count
# TYPE watchdog_unhealthy_containers gauge
watchdog_unhealthy_containers ${unhealthy_count:-0}
# HELP watchdog_restarts_total Total container restarts performed
# TYPE watchdog_restarts_total counter
watchdog_restarts_total $TOTAL_RESTARTS
# HELP watchdog_agent_escalations_total Total agent escalation requests
# TYPE watchdog_agent_escalations_total counter
watchdog_agent_escalations_total $TOTAL_AGENT_ESCALATIONS
# HELP watchdog_oom_kills_total Total OOM kills detected
# TYPE watchdog_oom_kills_total counter
watchdog_oom_kills_total $TOTAL_OOM_KILLS
# HELP watchdog_memory_leaks_total Total memory leaks detected
# TYPE watchdog_memory_leaks_total counter
watchdog_memory_leaks_total $TOTAL_MEMORY_LEAKS
# HELP watchdog_training_protected Whether training GPU has active processes
# TYPE watchdog_training_protected gauge
watchdog_training_protected $TRAINING_PROTECTED
# HELP watchdog_monitored_containers Total containers being monitored
# TYPE watchdog_monitored_containers gauge
watchdog_monitored_containers $monitored_count
# HELP watchdog_paused Whether watchdog is paused by admin
# TYPE watchdog_paused gauge
watchdog_paused $IS_PAUSED
METRICS
}

# ---------------------------------------------------------------------------
# Admin control file — pause/resume/stop-all
# ---------------------------------------------------------------------------
check_control() {
    if [[ -f "$CONTROL_FILE" ]]; then
        local cmd
        cmd=$(cat "$CONTROL_FILE")
        case "$cmd" in
            pause)
                if (( IS_PAUSED == 0 )); then
                    IS_PAUSED=1
                    log "CONTROL: Watchdog PAUSED by admin"
                    send_telegram "⏸️ <b>Watchdog Paused</b> — monitoring continues but auto-remediation is suspended.
<i>Trigger: admin control file  ·  $(date -u '+%H:%M UTC')</i>"
                    audit "ADMIN_PAUSE" "watchdog" "Paused by admin"
                fi
                ;;
            resume)
                IS_PAUSED=0
                rm -f "$CONTROL_FILE"
                log "CONTROL: Watchdog RESUMED by admin"
                send_telegram "▶️ <b>Watchdog Resumed</b> — auto-remediation is active.
<i>$(date -u '+%H:%M UTC')</i>"
                audit "ADMIN_RESUME" "watchdog" "Resumed by admin"
                ;;
            stop-all)
                IS_PAUSED=1
                log "CONTROL: All interventions STOPPED by admin"
                send_telegram "🛑 <b>All Interventions Stopped</b> — watchdog paused by admin control.
<i>$(date -u '+%H:%M UTC')</i>"
                audit "ADMIN_STOP_ALL" "watchdog" "All interventions stopped"
                echo "pause" > "$CONTROL_FILE"
                ;;
        esac
    fi
}

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
log "============================================="
log "Self-Healing Watchdog v2 starting"
log "  Check interval: ${CHECK_INTERVAL}s"
log "  Max restarts/hour: ${MAX_RESTARTS}"
log "  Cooldown: ${COOLDOWN_SECONDS}s"
log "  Training GPU: ${TRAINING_GPU} (PROTECTED)"
log "  Display GPU: ${DISPLAY_GPU} (desktop protected)"
log "  Watchdog GPU: ${WATCHDOG_GPU} (preferred)"
log "  Memory leak threshold: ${MEMORY_LEAK_THRESHOLD_MB} MB/hr"
log "  Host memory watermarks: soft=${HOST_MEMORY_SOFT_WATERMARK_PCT}% high=${HOST_MEMORY_HIGH_WATERMARK_PCT}%"
log "  Host swap watermark: ${HOST_SWAP_HIGH_WATERMARK_PCT}%"
log "  Training-sensitive restarts deferred for: ${TRAINING_SENSITIVE_CONTAINERS}"
log "  Low-priority containers: ${LOW_PRIORITY_CONTAINERS}"
log "  Agent service: ${AGENT_SERVICE_URL}"
log "  Critical: ${#CRITICAL_CONTAINERS[@]}"
log "  Standard: ${#STANDARD_CONTAINERS[@]}"
log "  Memory-watched: ${#MEMORY_WATCH_CONTAINERS[@]}"
log "  Excluded: ${EXCLUDED[*]:-none}"
log "============================================="

send_alert_card \
    --container "shml-watchdog" \
    --severity "info" \
    --event "watchdog_started" \
    --problem "Platform watchdog initialized after restart or first launch." \
    --action "Loaded ${#CRITICAL_CONTAINERS[@]} critical + ${#STANDARD_CONTAINERS[@]} standard containers. Health monitoring starting at ${CHECK_INTERVAL}s intervals." \
    --agent "shml-watchdog v2 (self-healing, GPU-aware, agent-integrated)" \
    --outcome "✅ Monitoring active. Auto-remediation enabled. Swap guard: ${HOST_SWAP_HIGH_WATERMARK_PCT}%. RAM guard: ${HOST_MEMORY_HIGH_WATERMARK_PCT}%." \
    --learning "Excluded: ${EXCLUDED[*]:-none} | Low-priority: ${LOW_PRIORITY_CONTAINERS} | Protected: ${PROTECTED_CONTAINERS:-none}"

# Verify docker socket access
if ! docker ps -q >/dev/null 2>&1; then
    log "ERROR: Docker socket not accessible — retrying in 10s"
    sleep 10
    if ! docker ps -q >/dev/null 2>&1; then
        log "FATAL: Docker socket still not accessible"
        exit 1
    fi
fi
log "Docker socket verified: $(docker ps -q 2>/dev/null | wc -l) containers visible"

# Initial state discovery
discover_platform_state || log "WARN: Initial discovery failed, continuing"

cycle=0
while true; do
    cycle=$((cycle + 1))

    # Check admin controls (pause/resume/stop-all)
    check_control

    unhealthy_count=0
    action_count=0
    unhealthy_list=""

    # --- Critical containers ---
    for container in "${CRITICAL_CONTAINERS[@]}"; do
        is_excluded "$container" && continue
        if ! check_container_health "$container" "critical"; then
            unhealthy_count=$((unhealthy_count + 1))
            unhealthy_list="${unhealthy_list} ${container}"
        fi
    done

    # --- Standard containers ---
    for container in "${STANDARD_CONTAINERS[@]}"; do
        is_excluded "$container" && continue
        if ! check_container_health "$container" "standard"; then
            unhealthy_count=$((unhealthy_count + 1))
            unhealthy_list="${unhealthy_list} ${container}"
        fi
    done

    # --- Cascading failure detection via agent ---
    if (( IS_PAUSED == 0 )); then
        if (( unhealthy_count >= 3 )); then
            detect_cascading_failure "$unhealthy_list"
            action_count=$((action_count + 1))
        elif (( unhealthy_count > 0 )); then
            for container in $unhealthy_list; do
                restart_container "$container" "unhealthy" || true
                action_count=$((action_count + 1))
            done
        fi
    elif (( unhealthy_count > 0 )); then
        log "PAUSED: ${unhealthy_count} unhealthy but remediation paused by admin"
    fi

    # --- Training GPU protection (every cycle) ---
    check_training_gpu_safety || true

    # --- Host pressure protection (every cycle) ---
    check_host_pressure || true

    # --- Display GPU protection (every 2 cycles) ---
    if (( cycle % 2 == 0 )); then
        check_display_gpu_pressure || true
    fi

    # --- GPU thermal (every 5 cycles) ---
    if (( cycle % 5 == 0 )); then
        check_gpu_health || true
    fi

    # --- Memory leak detection (every 10 cycles ≈ 10 min) ---
    if (( cycle % 10 == 0 )); then
        check_memory_leaks || true
        # #68: psutil-based host process memory guard (VSCode, Python/training)
        if command -v python3 &>/dev/null; then
            python3 "${SCRIPT_DIR}/host_process_guard.py" \
                --state-dir "${STATE_DIR}/host-process-guard" \
                --threshold-mb "${HOST_PROCESS_LEAK_THRESHOLD_MB:-500}" \
                --baseline-secs "${HOST_PROCESS_BASELINE_SECS:-1800}" \
                2>/dev/null || true
        fi
    fi

    # --- OOM detection (every 5 cycles) ---
    if (( cycle % 5 == 0 )); then
        check_oom_killed || true
    fi

    # --- Prometheus connectivity (every 3 cycles) ---
    if (( cycle % 3 == 0 )); then
        check_prometheus || true
    fi

    # --- GitLab app-level health (every 2 cycles) ---
    if (( cycle % 2 == 0 )); then
        if ! check_gitlab_application_health; then
            if (( IS_PAUSED == 0 )); then
                restart_container "${PLATFORM_PREFIX}-gitlab" "gitlab-app-health" || true
                action_count=$((action_count + 1))
            else
                log "PAUSED: GitLab unhealthy but remediation paused by admin"
            fi
        fi
    fi

    # --- HTTP endpoint probes for ALL services (every 2 cycles) ---
    # Catches cases where containers are "running" but the app is wedged
    # (crashed, OOM'd internally, DB connection lost, etc.)
    if (( cycle % 2 == 0 )); then
        check_http_services || action_count=$((action_count + 1))
    fi

    # --- Full state discovery (every 30 cycles ≈ 30 min) ---
    if (( cycle % 30 == 0 )); then
        discover_platform_state || true
    fi

    # --- Track totals & push metrics ---
    TOTAL_ACTIONS=$((TOTAL_ACTIONS + action_count))
    record_resource_snapshot || true
    push_metrics || true

    sleep "$CHECK_INTERVAL"
done
