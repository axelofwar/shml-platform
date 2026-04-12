#!/usr/bin/env bash
# =============================================================================
# watchdog-ctl — Host-side control for the SHML self-healing watchdog
# =============================================================================
# Usage:
#   watchdog-ctl pause [DURATION]  — Pause remediation (optional: auto-resume after Ns/m/h)
#   watchdog-ctl resume            — Resume remediation
#   watchdog-ctl status            — Show watchdog state
#   watchdog-ctl stop-all          — Emergency stop all interventions
# =============================================================================
set -euo pipefail

CONTAINER="${WATCHDOG_CONTAINER:-shml-watchdog}"
STATE_DIR="/var/lib/watchdog"
CONTROL_FILE="${STATE_DIR}/control"

_exec() { docker exec "$CONTAINER" "$@"; }

case "${1:-status}" in
    pause)
        _exec sh -c "echo pause > ${CONTROL_FILE}"
        echo "✅  Watchdog paused — auto-remediation suspended"

        # Optional auto-resume after duration (e.g. 30m, 1h, 300s)
        if [[ -n "${2:-}" ]]; then
            duration="$2"
            # Convert to seconds
            if [[ "$duration" =~ ^([0-9]+)m$ ]]; then
                secs=$(( ${BASH_REMATCH[1]} * 60 ))
            elif [[ "$duration" =~ ^([0-9]+)h$ ]]; then
                secs=$(( ${BASH_REMATCH[1]} * 3600 ))
            elif [[ "$duration" =~ ^([0-9]+)s?$ ]]; then
                secs="${BASH_REMATCH[1]}"
            else
                echo "Invalid duration: $duration (use Ns, Nm, Nh)" >&2
                exit 1
            fi
            echo "⏱️  Auto-resume in ${duration} (${secs}s)"
            # Background: sleep then resume
            (
                sleep "$secs"
                docker exec "$CONTAINER" sh -c "echo resume > ${CONTROL_FILE}" 2>/dev/null
                echo "▶️  Watchdog auto-resumed after ${duration}"
            ) &
            disown
        fi
        ;;

    resume)
        _exec sh -c "echo resume > ${CONTROL_FILE}"
        echo "▶️  Watchdog resumed — auto-remediation active"
        ;;

    stop-all)
        _exec sh -c "echo stop-all > ${CONTROL_FILE}"
        echo "🛑  All watchdog interventions stopped"
        ;;

    status)
        echo "=== Watchdog Container ==="
        docker ps --format 'table {{.Names}}\t{{.Status}}' --filter "name=${CONTAINER}"
        echo ""
        if _exec test -f "$CONTROL_FILE" 2>/dev/null; then
            state=$(_exec cat "$CONTROL_FILE" 2>/dev/null)
            echo "Control state: ${state}"
        else
            echo "Control state: running (no control file)"
        fi
        echo ""
        echo "=== Recent Log ==="
        _exec tail -5 /var/log/watchdog/watchdog.log 2>/dev/null || echo "(no log)"
        ;;

    *)
        echo "Usage: watchdog-ctl {pause [DURATION]|resume|status|stop-all}"
        echo "  pause 30m   — pause for 30 minutes then auto-resume"
        echo "  pause 2h    — pause for 2 hours then auto-resume"
        echo "  pause       — pause until manually resumed"
        exit 1
        ;;
esac
