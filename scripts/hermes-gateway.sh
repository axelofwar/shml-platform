#!/usr/bin/env bash
set -euo pipefail

# Hermes Gateway — start/stop/status management
# Runs hermes-agent in gateway mode (HTTP API on :8642)
# RBAC enforced via Traefik route /api/hermes/* (developer+ required)

HERMES_BIN="/home/axelofwar/.hermes/hermes-agent/venv/bin/hermes"
HERMES_HOME="/home/axelofwar/.hermes"
PID_FILE="/tmp/hermes-gateway.pid"
LOG_FILE="/tmp/hermes-gateway.log"

usage() {
    echo "Usage: $0 {start|stop|status|restart|logs}"
    exit 1
}

_is_running() {
    if [[ -f "${PID_FILE}" ]]; then
        local pid
        pid=$(cat "${PID_FILE}")
        if kill -0 "${pid}" 2>/dev/null; then
            return 0
        fi
        rm -f "${PID_FILE}"
    fi
    return 1
}

cmd_start() {
    if _is_running; then
        echo "✅ Hermes gateway already running (PID $(cat "${PID_FILE}"))"
        return 0
    fi

    echo "Starting Hermes gateway..."
    cd "${HERMES_HOME}/hermes-agent"
    nohup "${HERMES_BIN}" gateway run > "${LOG_FILE}" 2>&1 &
    local pid=$!
    echo "${pid}" > "${PID_FILE}"
    sleep 2

    if kill -0 "${pid}" 2>/dev/null; then
        echo "✅ Hermes gateway started (PID ${pid})"
        echo "   API: http://localhost:8642/v1"
        echo "   Traefik: /api/hermes/* (RBAC: developer+)"
        echo "   Logs: ${LOG_FILE}"
    else
        echo "❌ Hermes gateway failed to start"
        tail -20 "${LOG_FILE}" 2>/dev/null
        rm -f "${PID_FILE}"
        return 1
    fi
}

cmd_stop() {
    if ! _is_running; then
        echo "Hermes gateway is not running"
        return 0
    fi

    local pid
    pid=$(cat "${PID_FILE}")
    echo "Stopping Hermes gateway (PID ${pid})..."
    kill "${pid}" 2>/dev/null || true
    sleep 2
    if kill -0 "${pid}" 2>/dev/null; then
        kill -9 "${pid}" 2>/dev/null || true
    fi
    rm -f "${PID_FILE}"
    echo "✅ Hermes gateway stopped"
}

cmd_status() {
    if _is_running; then
        local pid
        pid=$(cat "${PID_FILE}")
        echo "✅ Hermes gateway running (PID ${pid})"
        # Check health
        if command -v python3 &>/dev/null; then
            python3 -c "
import urllib.request, json
try:
    r = urllib.request.urlopen('http://localhost:8642/health', timeout=3)
    d = json.loads(r.read())
    print(f'   Health: {d.get(\"status\", \"unknown\")}')
except Exception as e:
    print(f'   Health: unreachable ({e})')
" 2>/dev/null
        fi
    else
        echo "❌ Hermes gateway is not running"
    fi
}

cmd_logs() {
    if [[ -f "${LOG_FILE}" ]]; then
        tail -f "${LOG_FILE}"
    else
        echo "No log file found at ${LOG_FILE}"
    fi
}

case "${1:-}" in
    start)   cmd_start ;;
    stop)    cmd_stop ;;
    status)  cmd_status ;;
    restart) cmd_stop; sleep 1; cmd_start ;;
    logs)    cmd_logs ;;
    *)       usage ;;
esac
