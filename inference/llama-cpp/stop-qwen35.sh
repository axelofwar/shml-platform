#!/usr/bin/env bash
# Stop the Qwen3.5-27B llama-server
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${SCRIPT_DIR}/qwen35-server.pid"

if [[ -f "${PID_FILE}" ]]; then
    PID=$(cat "${PID_FILE}")
    if kill -0 "${PID}" 2>/dev/null; then
        echo "Stopping llama-server (PID ${PID})..."
        kill "${PID}"
        sleep 2
        kill -9 "${PID}" 2>/dev/null || true
        echo "Stopped."
    else
        echo "Process ${PID} not running (stale PID file)."
    fi
    rm -f "${PID_FILE}"
else
    # Fallback: kill any llama-server process
    PIDS=$(pgrep -f "llama-server.*Qwen" 2>/dev/null || true)
    if [[ -n "${PIDS}" ]]; then
        echo "Killing llama-server processes: ${PIDS}"
        kill ${PIDS} 2>/dev/null || true
        sleep 2
        kill -9 ${PIDS} 2>/dev/null || true
        echo "Done."
    else
        echo "No llama-server process found."
    fi
fi
