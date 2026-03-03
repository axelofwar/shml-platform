#!/bin/bash
# =============================================================================
# Nightly Test Runner — SHML Platform
# =============================================================================
# Runs the full test suite on schedule and reports results via Telegram.
# Logs test output and tracks pass/fail trends over time.
#
# Schedule: Once daily at 03:00 UTC (configurable via TEST_HOUR)
# =============================================================================

set -euo pipefail

TEST_HOUR="${TEST_HOUR:-3}"                  # Hour (UTC) to run tests
TEST_DIR="${TEST_DIR:-/workspace/tests}"
RESULTS_DIR="/var/log/test-runner"
TELEGRAM_ENABLED="${TELEGRAM_BOT_TOKEN:+true}"

mkdir -p "$RESULTS_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] $1" | tee -a "$RESULTS_DIR/runner.log"
}

send_telegram() {
    local msg="$1"
    if [[ "${TELEGRAM_ENABLED:-}" == "true" && -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
        curl -sf -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d chat_id="${TELEGRAM_CHAT_ID}" \
            -d text="${msg}" \
            -d parse_mode=Markdown \
            > /dev/null 2>&1 || log "WARN: Telegram send failed"
    fi
}

run_tests() {
    local date_stamp
    date_stamp=$(date '+%Y%m%d_%H%M%S')
    local report_file="${RESULTS_DIR}/report_${date_stamp}.txt"
    local json_file="${RESULTS_DIR}/results_${date_stamp}.json"

    log "Starting test run: ${date_stamp}"

    # Run pytest with JUnit XML and JSON output
    local exit_code=0
    cd /workspace

    python3 -m pytest "${TEST_DIR}" \
        -v \
        --tb=short \
        --no-header \
        -q \
        2>&1 | tee "$report_file" || exit_code=$?

    # Parse results from pytest output
    local last_line
    last_line=$(tail -1 "$report_file" 2>/dev/null || echo "unknown")

    # Extract counts (e.g., "128 passed, 0 failed")
    local passed failed skipped errors
    passed=$(echo "$last_line" | grep -oP '\d+ passed' | grep -oP '\d+' || echo "0")
    failed=$(echo "$last_line" | grep -oP '\d+ failed' | grep -oP '\d+' || echo "0")
    skipped=$(echo "$last_line" | grep -oP '\d+ skipped' | grep -oP '\d+' || echo "0")
    errors=$(echo "$last_line" | grep -oP '\d+ error' | grep -oP '\d+' || echo "0")

    # Save JSON summary
    cat > "$json_file" <<EOF
{
    "timestamp": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')",
    "passed": ${passed:-0},
    "failed": ${failed:-0},
    "skipped": ${skipped:-0},
    "errors": ${errors:-0},
    "exit_code": ${exit_code},
    "report_file": "${report_file}"
}
EOF

    # Also write to workspace for other tools to pick up
    cp "$json_file" /workspace/test-results.json 2>/dev/null || true

    # Determine overall status
    local status_icon="✅"
    local status_text="ALL PASSING"
    if [[ "$exit_code" -ne 0 ]] || [[ "${failed:-0}" -gt 0 ]] || [[ "${errors:-0}" -gt 0 ]]; then
        status_icon="❌"
        status_text="FAILURES DETECTED"
    fi

    log "Test run complete: ${passed} passed, ${failed} failed, ${skipped} skipped (exit: ${exit_code})"

    # Send Telegram report
    send_telegram "${status_icon} *Nightly Test Report*

${status_text}
✅ Passed: ${passed:-0}
❌ Failed: ${failed:-0}
⏭️ Skipped: ${skipped:-0}

Exit code: ${exit_code}
Timestamp: ${date_stamp}"

    # Cleanup old reports (keep 30 days)
    find "$RESULTS_DIR" -name "report_*.txt" -mtime +30 -delete 2>/dev/null || true
    find "$RESULTS_DIR" -name "results_*.json" -mtime +30 -delete 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Main loop — wait for scheduled hour, then run
# ---------------------------------------------------------------------------
log "Nightly Test Runner starting (scheduled hour: ${TEST_HOUR} UTC)"
send_telegram "🧪 *Nightly Test Runner* started — tests will run daily at ${TEST_HOUR}:00 UTC"

while true; do
    current_hour=$(date -u '+%H' | sed 's/^0//')
    current_min=$(date -u '+%M' | sed 's/^0//')

    if [[ "$current_hour" -eq "$TEST_HOUR" ]] && [[ "$current_min" -lt 5 ]]; then
        run_tests
        # Sleep past the trigger window to avoid double-runs
        sleep 3600
    fi

    # Check every 5 minutes
    sleep 300
done
