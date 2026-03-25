#!/usr/bin/env bash
# =============================================================================
# start-qwen35-cuda.sh
# Start Qwen3.5-27B-Q4_K_M with CUDA acceleration on RTX 3090 Ti
# Serves OpenAI-compatible API on http://localhost:8000/v1
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLAMA_DIR="${SCRIPT_DIR}/llama-b8373-cuda"
MODEL_PATH="${SCRIPT_DIR}/models/Qwen3.5-27B-Q4_K_M.gguf"
LOG_DIR="${SCRIPT_DIR}/logs"
PID_FILE="${SCRIPT_DIR}/qwen35-server.pid"
LOG_FILE="${LOG_DIR}/qwen35-server.log"

# Server config
HOST="0.0.0.0"
PORT=8000
CTX_SIZE=65536      # 65K context (native trained ctx = 262K; VRAM limits us here)
                    # Model is hybrid SSM+attention (16/64 attention layers) so
                    # KV cache is 4x smaller than a pure attention model.
N_GPU_LAYERS=99     # All layers on GPU (model ~14.3GB, 3090 Ti has 24GB)
N_THREADS=8         # CPU threads for prompt preprocessing
N_THREADS_BATCH=24  # All 24 cores for batch processing
PARALLEL=2          # 2 slots: each gets 65536/2 = 32768 tokens
                    # llama.cpp divides --ctx-size evenly across --parallel slots.
                    # With 4 slots each only got 16384 tokens (caused 400 errors).
BATCH_SIZE=512
KV_CACHE_TYPE=q8_0  # 8-bit KV cache: halves KV VRAM, negligible quality loss

# CRITICAL: restrict to RTX 3090 Ti (CUDA CC 8.6) only.
# This build was compiled with ARCHS=860. RTX 2070 is CC 7.5 and has no
# matching CUDA kernels - spreading layers across both GPUs causes a hard crash.
CUDA_VISIBLE_DEVICES=0

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} $*"; }
warn() { echo -e "${YELLOW}[$(date '+%H:%M:%S')] WARN:${NC} $*"; }
err()  { echo -e "${RED}[$(date '+%H:%M:%S')] ERROR:${NC} $*"; }

# --- Preflight checks --------------------------------------------------------
check_prerequisites() {
    if [[ ! -f "${LLAMA_DIR}/llama-server" ]]; then
        err "llama-server not found at: ${LLAMA_DIR}/llama-server"
        exit 1
    fi
    if [[ ! -f "${MODEL_PATH}" ]]; then
        err "Model not found at: ${MODEL_PATH}"
        exit 1
    fi
    if [[ -f "${PID_FILE}" ]]; then
        OLD_PID=$(cat "${PID_FILE}")
        if kill -0 "${OLD_PID}" 2>/dev/null; then
            warn "Server already running (PID ${OLD_PID}). Use stop-qwen35.sh first."
            exit 0
        else
            log "Stale PID file found, cleaning up..."
            rm -f "${PID_FILE}"
        fi
    fi

    # Check port is free
    if ss -tlnp 2>/dev/null | grep -q ":${PORT} "; then
        err "Port ${PORT} is already in use!"
        ss -tlnp | grep ":${PORT} "
        exit 1
    fi

    # Check CUDA
    if ! nvidia-smi &>/dev/null; then
        warn "nvidia-smi not available - CUDA acceleration may not work"
    else
        log "GPU status:"
        nvidia-smi --query-gpu=name,memory.total,memory.free,temperature.gpu \
            --format=csv,noheader | awk -F',' '{printf "  GPU: %s | Total: %s | Free: %s | Temp: %s\n", $1, $2, $3, $4}'
    fi
}

# --- Start server ------------------------------------------------------------
start_server() {
    mkdir -p "${LOG_DIR}"

    log "Starting Qwen3.5-27B CUDA server..."
    log "  Model:      ${MODEL_PATH}"
    log "  Host:       ${HOST}:${PORT}"
    log "  GPU Layers: ${N_GPU_LAYERS} (full GPU offload)"
    log "  Context:    ${CTX_SIZE} tokens"
    log "  Parallel:   ${PARALLEL} slots"
    log "  Logs:       ${LOG_FILE}"

    # Set library path so the CUDA shared libs are found
    export LD_LIBRARY_PATH="${LLAMA_DIR}:${LD_LIBRARY_PATH:-}"
    # Restrict to RTX 3090 Ti only (CC 8.6 - matches this binary's ARCHS)
    export CUDA_VISIBLE_DEVICES=0

    # Launch server
    "${LLAMA_DIR}/llama-server" \
        --model           "${MODEL_PATH}" \
        --host            "${HOST}" \
        --port            "${PORT}" \
        --n-gpu-layers    "${N_GPU_LAYERS}" \
        --ctx-size        "${CTX_SIZE}" \
        --threads         "${N_THREADS}" \
        --threads-batch   "${N_THREADS_BATCH}" \
        --parallel        "${PARALLEL}" \
        --batch-size      "${BATCH_SIZE}" \
        --ubatch-size     "${BATCH_SIZE}" \
        --cache-type-k    "${KV_CACHE_TYPE}" \
        --cache-type-v    "${KV_CACHE_TYPE}" \
        --api-key         none \
        --log-file        "${LOG_FILE}" \
        --alias           "Qwen3.5-27B-Q4_K_M" \
        &

    SERVER_PID=$!
    echo "${SERVER_PID}" > "${PID_FILE}"
    log "Server process started (PID ${SERVER_PID})"

    # Wait for server to become ready
    log "Waiting for server to initialize (model loading ~30-60s)..."
    for i in $(seq 1 120); do
        sleep 2
        if curl -sf "http://localhost:${PORT}/health" &>/dev/null; then
            log ""
            log "✓ Server is ready!"
            log "  OpenAI API:  http://localhost:${PORT}/v1"
            log "  Health:      http://localhost:${PORT}/health"
            log "  Web UI:      http://localhost:${PORT}"
            log ""
            log "  continue.dev and Cline are pre-configured to use this endpoint."
            log "  Run: curl http://localhost:${PORT}/v1/models"
            return 0
        fi
        # Check if process died
        if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
            err "Server process died during startup. Check logs: ${LOG_FILE}"
            tail -30 "${LOG_FILE}" 2>/dev/null || true
            rm -f "${PID_FILE}"
            exit 1
        fi
        printf "."
        (( i % 30 == 0 )) && printf "\n  Still loading... (${i}s / 240s)\n"
    done

    err "Timeout waiting for server to start. Check logs: ${LOG_FILE}"
    tail -50 "${LOG_FILE}" 2>/dev/null || true
    exit 1
}

# --- Main --------------------------------------------------------------------
main() {
    log "=== Qwen3.5-27B CUDA Server Startup ==="
    check_prerequisites
    start_server
}

main "$@"
