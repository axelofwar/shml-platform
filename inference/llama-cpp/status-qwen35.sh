#!/usr/bin/env bash
# Check status of Qwen3.5-27B llama-server
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${SCRIPT_DIR}/qwen35-server.pid"
PORT=8000

echo "=== Qwen3.5-27B Server Status ==="

# Process check
if [[ -f "${PID_FILE}" ]]; then
    PID=$(cat "${PID_FILE}")
    if kill -0 "${PID}" 2>/dev/null; then
        echo "Process:  RUNNING (PID ${PID})"
    else
        echo "Process:  DEAD (stale PID ${PID})"
    fi
else
    PIDS=$(pgrep -f "llama-server" 2>/dev/null || true)
    if [[ -n "${PIDS}" ]]; then
        echo "Process:  RUNNING (PID ${PIDS})"
    else
        echo "Process:  NOT RUNNING"
    fi
fi

# Health check
echo -n "Health:   "
HEALTH=$(curl -sf "http://localhost:${PORT}/health" 2>/dev/null || echo "UNREACHABLE")
echo "${HEALTH}"

# Model list
echo -n "Models:   "
MODELS=$(curl -sf "http://localhost:${PORT}/v1/models" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(', '.join(m['id'] for m in d.get('data', [])))" 2>/dev/null || echo "N/A")
echo "${MODELS}"

# GPU usage
if command -v nvidia-smi &>/dev/null; then
    echo ""
    echo "GPU Memory:"
    nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu \
        --format=csv,noheader | awk -F',' '{printf "  %s | Used: %s/%s | GPU: %s\n", $1, $2, $3, $4}'
fi

echo ""
echo "Logs: ${SCRIPT_DIR}/logs/qwen35-server.log"
echo "API:  http://localhost:${PORT}/v1"
