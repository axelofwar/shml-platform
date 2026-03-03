#!/bin/bash
# =============================================================================
# Feature Materialization Scheduler
# =============================================================================
# Cron-like scheduler that submits the scheduled_materialize.py Ray job
# at regular intervals. Runs inside a lightweight container on the platform
# network so it can reach the Ray head node directly.
#
# Schedule: Every hour (configurable via MATERIALIZE_INTERVAL)
# =============================================================================

set -euo pipefail

INTERVAL="${MATERIALIZE_INTERVAL:-3600}"          # Default: 1 hour
RAY_HEAD="${RAY_HEAD_ADDRESS:-ray-head:8265}"      # Ray Job Submission API
JOB_NAME="feature-materialize"
ENTRYPOINT="python3 /opt/ray/job_workspaces/scheduled_materialize.py"
LOG_DIR="/var/log/feature-scheduler"
TELEGRAM_ENABLED="${TELEGRAM_BOT_TOKEN:+true}"

mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] $1" | tee -a "$LOG_DIR/scheduler.log"
}

send_telegram() {
    local msg="$1"
    if [[ "${TELEGRAM_ENABLED:-}" == "true" && -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
        curl -sf -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d chat_id="${TELEGRAM_CHAT_ID}" \
            -d text="${msg}" \
            -d parse_mode=Markdown \
            > /dev/null 2>&1 || true
    fi
}

submit_job() {
    local mode="${1:-}"
    local extra_args=""
    [[ "$mode" == "--force" ]] && extra_args=" --force"
    [[ "$mode" == "--dry-run" ]] && extra_args=" --dry-run"

    log "Submitting materialization job to Ray (${RAY_HEAD})${extra_args}"

    local response
    response=$(curl -sf -X POST "http://${RAY_HEAD}/api/jobs/" \
        -H "Content-Type: application/json" \
        -d "{
            \"entrypoint\": \"${ENTRYPOINT}${extra_args}\",
            \"submission_id\": \"${JOB_NAME}-$(date +%s)\",
            \"runtime_env\": {
                \"working_dir\": \"/opt/ray/job_workspaces\"
            },
            \"metadata\": {
                \"name\": \"${JOB_NAME}\",
                \"source\": \"feature-scheduler\",
                \"submitted_at\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
            }
        }" 2>&1) || {
        log "ERROR: Failed to submit job — ${response}"
        send_telegram "⚠️ *Feature Materialization* submission failed at $(date '+%H:%M %Z')"
        return 1
    }

    local job_id
    job_id=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('submission_id','unknown'))" 2>/dev/null || echo "unknown")
    log "Job submitted: ${job_id}"
    return 0
}

wait_for_ray() {
    log "Waiting for Ray head node (${RAY_HEAD})..."
    local retries=0
    while ! curl -sf "http://${RAY_HEAD}/api/version" > /dev/null 2>&1; do
        retries=$((retries + 1))
        if [[ $retries -ge 60 ]]; then
            log "ERROR: Ray head not reachable after 5 minutes"
            exit 1
        fi
        sleep 5
    done
    log "Ray head node is ready"
}

# -----------------------------------------------------------------------------
# Main loop
# -----------------------------------------------------------------------------
log "Feature Materialization Scheduler starting"
log "  Interval: ${INTERVAL}s"
log "  Ray head: ${RAY_HEAD}"
log "  Telegram: ${TELEGRAM_ENABLED:-false}"

wait_for_ray

# Initial dry-run to validate connectivity
submit_job "--dry-run" || log "WARN: Initial dry-run failed, will retry on next cycle"

log "Entering scheduler loop (every ${INTERVAL}s)"
send_telegram "📊 *Feature Scheduler* started — materializing every $((INTERVAL / 60))min"

while true; do
    sleep "$INTERVAL"
    submit_job || true
done
