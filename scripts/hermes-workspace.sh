#!/usr/bin/env bash
set -euo pipefail

# Hermes Workspace — start/stop/status for the web GUI
# Connects to Hermes gateway on :8642

WORKSPACE_DIR="/home/axelofwar/Projects/hermes-workspace"
PID_FILE="/tmp/hermes-workspace.pid"
LOG_FILE="/tmp/hermes-workspace.log"
# PORT is the fallback; actual value is read from workspace .env in cmd_start
PORT=$(grep -E '^PORT=' "${WORKSPACE_DIR}/.env" 2>/dev/null | head -1 | cut -d= -f2- || echo "3000")
PORT="${PORT:-3000}"

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
        echo "✅ Hermes workspace already running (PID $(cat "${PID_FILE}"))"
        return 0
    fi

    # Check gateway is running
    if ! python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8642/health', timeout=2)" 2>/dev/null; then
        echo "⚠️  Hermes gateway not reachable on :8642"
        echo "   Start it first: scripts/hermes-gateway.sh start"
        echo "   Starting workspace anyway (will retry connection)..."
    fi

    echo "Starting Hermes workspace..."
    cd "${WORKSPACE_DIR}"
    # VITE_BASE drives Vite's base option (vite.config.ts reads it) and router.tsx reads
    # import.meta.env.BASE_URL. Traefik PathPrefix is templated from HERMES_WORKSPACE_BASE
    # in platform .env → dynamic.yml. Change the path in one place (.env) and all layers follow.
    # VITE_PRE_CONNECTED skips the connection setup screen (gateway is platform-managed)
    # setsid creates a new process group so cmd_stop can kill vite + children
    local _vite_base _port
    _vite_base=$(grep -E '^VITE_BASE=' "${WORKSPACE_DIR}/.env" 2>/dev/null | head -1 | cut -d= -f2-)
    _port=$(grep -E '^PORT=' "${WORKSPACE_DIR}/.env" 2>/dev/null | head -1 | cut -d= -f2-)
    PORT="${_port:-${PORT}}"
    VITE_BASE="${_vite_base:-/hermes-workspace/}" PORT="${PORT}" VITE_PRE_CONNECTED=true setsid nohup pnpm dev > "${LOG_FILE}" 2>&1 &
    local pid=$!
    echo "${pid}" > "${PID_FILE}"
    sleep 3

    if kill -0 "${pid}" 2>/dev/null; then
        echo "✅ Hermes workspace started (PID ${pid})"
        echo "   URL: http://localhost:${PORT}"
        echo "   Logs: ${LOG_FILE}"
    else
        echo "❌ Hermes workspace failed to start"
        tail -20 "${LOG_FILE}" 2>/dev/null
        rm -f "${PID_FILE}"
        return 1
    fi
}

cmd_stop() {
    if ! _is_running; then
        echo "Hermes workspace is not running"
        # Clean up any orphaned node processes on the workspace port
        local orphan_pid
        orphan_pid=$(ss -tlnp | grep ":${PORT} " | grep -oP 'pid=\K[0-9]+' || true)
        if [[ -n "${orphan_pid}" ]]; then
            echo "  Killing orphaned process on port ${PORT} (PID ${orphan_pid})..."
            kill "${orphan_pid}" 2>/dev/null || true
        fi
        return 0
    fi

    local pid
    pid=$(cat "${PID_FILE}")
    echo "Stopping Hermes workspace (PID ${pid})..."
    # Kill entire process group so Vite child processes are also terminated
    kill -- -"${pid}" 2>/dev/null || kill "${pid}" 2>/dev/null || true
    sleep 2
    if kill -0 "${pid}" 2>/dev/null; then
        kill -9 -- -"${pid}" 2>/dev/null || kill -9 "${pid}" 2>/dev/null || true
    fi
    rm -f "${PID_FILE}"
    echo "✅ Hermes workspace stopped"
}

cmd_status() {
    if _is_running; then
        echo "✅ Hermes workspace running (PID $(cat "${PID_FILE}")) on :${PORT}"
    else
        echo "❌ Hermes workspace is not running"
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
