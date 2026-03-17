#!/usr/bin/env bash
# =============================================================================
# LLM Control Script - Manages Qwen3.5-27B via llama.cpp on GPU 0
# =============================================================================
#
# Uses llama.cpp (llama-server) with Vulkan backend for GPU acceleration.
# Provides OpenAI-compatible API at http://localhost:8000/v1
#
# Usage:
#   ./scripts/llm_control.sh start       # Start llama-server on GPU 0
#   ./scripts/llm_control.sh stop        # Stop llama-server gracefully
#   ./scripts/llm_control.sh restart     # Restart
#   ./scripts/llm_control.sh status      # Check if running
#   ./scripts/llm_control.sh health      # Health check (test inference)
#   ./scripts/llm_control.sh yield       # Stop for training (GPU 0 freed)
#   ./scripts/llm_control.sh restore     # Restart after training
#
# Environment variables:
#   LLM_MODEL_PATH   - Path to GGUF file (default: inference/llama-cpp/models/Qwen3.5-27B-Q4_K_M.gguf)
#   LLM_PORT         - Port to serve on (default: 8000)
#   LLM_GPU_LAYERS   - Number of layers on GPU (default: 99 = all layers)
#   LLM_CONTEXT_LEN  - Context length (default: 32768)
#   LLM_THREADS      - CPU threads (default: auto)
#   LLM_FLASH_ATTN   - Enable flash attention (default: 1)
#
# Integration with GPU manager's training workflow:
#   1. Training calls: ./llm_control.sh yield
#   2. Training runs on GPU 0
#   3. Training calls: ./llm_control.sh restore
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Configuration — prefer CUDA build, fall back to Vulkan build
if [[ -x "${PROJECT_DIR}/inference/llama-cpp/llama-b8373-cuda/llama-server" ]]; then
    LLM_SERVER="${LLM_SERVER:-${PROJECT_DIR}/inference/llama-cpp/llama-b8373-cuda/llama-server}"
else
    LLM_SERVER="${LLM_SERVER:-${PROJECT_DIR}/inference/llama-cpp/llama-b8373/llama-server}"
fi
LLM_MODEL_PATH="${LLM_MODEL_PATH:-${PROJECT_DIR}/inference/llama-cpp/models/Qwen3.5-27B-Q4_K_M.gguf}"
LLM_PORT="${LLM_PORT:-8000}"
LLM_GPU_LAYERS="${LLM_GPU_LAYERS:-99}"
LLM_CONTEXT_LEN="${LLM_CONTEXT_LEN:-32768}"
LLM_THREADS="${LLM_THREADS:-$(nproc)}"
LLM_FLASH_ATTN="${LLM_FLASH_ATTN:-1}"
LLM_LOG_DIR="${LLM_LOG_DIR:-${PROJECT_DIR}/logs}"
LLM_PID_FILE="${LLM_PID_FILE:-/tmp/llm-server.pid}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[llm]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[llm]${NC} $*"; }
log_error() { echo -e "${RED}[llm]${NC} $*"; }

# =============================================================================
# Core Functions
# =============================================================================

get_pid() {
    if [[ -f "$LLM_PID_FILE" ]]; then
        local pid
        pid=$(cat "$LLM_PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo "$pid"
            return 0
        fi
        rm -f "$LLM_PID_FILE"
    fi

    local pid
    pid=$(pgrep -f "llama-server.*${LLM_PORT}" 2>/dev/null | head -1) || true
    if [[ -n "$pid" ]]; then
        echo "$pid"
        return 0
    fi
    return 1
}

is_running() { get_pid &>/dev/null; }

wait_for_healthy() {
    local timeout="${1:-300}"
    local elapsed=0

    log_info "Waiting for llama-server to become healthy (timeout: ${timeout}s)..."

    while [[ $elapsed -lt $timeout ]]; do
        if curl -sf "http://localhost:${LLM_PORT}/health" &>/dev/null; then
            log_info "llama-server is healthy at http://localhost:${LLM_PORT}"
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
        if (( elapsed % 30 == 0 )); then
            log_info "Still loading model... (${elapsed}s/${timeout}s)"
        fi
    done

    log_error "llama-server did not become healthy within ${timeout}s"
    return 1
}

do_start() {
    if is_running; then
        local pid
        pid=$(get_pid)
        log_info "llama-server already running (PID: $pid)"
        return 0
    fi

    # Validate model file exists
    if [[ ! -f "$LLM_MODEL_PATH" ]]; then
        log_error "Model file not found: $LLM_MODEL_PATH"
        log_error "Download it with:"
        log_error "  curl -L -o '$LLM_MODEL_PATH' 'https://huggingface.co/unsloth/Qwen3.5-27B-GGUF/resolve/main/Qwen3.5-27B-Q4_K_M.gguf'"
        return 1
    fi

    # Validate server binary exists
    if [[ ! -x "$LLM_SERVER" ]]; then
        log_error "llama-server not found or not executable: $LLM_SERVER"
        return 1
    fi

    mkdir -p "$LLM_LOG_DIR"

    local model_name
    model_name=$(basename "$LLM_MODEL_PATH" .gguf)

    log_info "Starting llama-server..."
    log_info "  Model: $model_name"
    log_info "  GPU layers: $LLM_GPU_LAYERS"
    log_info "  Context: $LLM_CONTEXT_LEN"
    log_info "  Port: $LLM_PORT"
    log_info "  Threads: $LLM_THREADS"
    log_info "  Flash attention: $LLM_FLASH_ATTN"

    local log_file="${LLM_LOG_DIR}/llama-server.log"
    local fa_flag=""
    if [[ "$LLM_FLASH_ATTN" == "1" ]]; then
        fa_flag="--flash-attn on"
    fi

    # Set library path for llama.cpp shared libs
    local llama_dir
    llama_dir="$(dirname "$LLM_SERVER")"

    LD_LIBRARY_PATH="${llama_dir}:${LD_LIBRARY_PATH:-}" \
    nohup "$LLM_SERVER" \
        --model "$LLM_MODEL_PATH" \
        --port "$LLM_PORT" \
        --host 0.0.0.0 \
        --n-gpu-layers "$LLM_GPU_LAYERS" \
        --ctx-size "$LLM_CONTEXT_LEN" \
        --threads "$LLM_THREADS" \
        $fa_flag \
        --metrics \
        --chat-template chatml \
        >> "$log_file" 2>&1 &

    local pid=$!
    echo "$pid" > "$LLM_PID_FILE"

    log_info "llama-server started (PID: $pid, log: $log_file)"

    if wait_for_healthy 300; then
        log_info "llama-server is ready for inference"
        return 0
    else
        log_error "llama-server failed to start. Check log: $log_file"
        tail -20 "$log_file" 2>/dev/null || true
        return 1
    fi
}

do_stop() {
    if ! is_running; then
        log_info "llama-server is not running"
        return 0
    fi

    local pid
    pid=$(get_pid)
    log_info "Stopping llama-server (PID: $pid)..."

    kill "$pid" 2>/dev/null || true

    local waited=0
    while kill -0 "$pid" 2>/dev/null && [[ $waited -lt 30 ]]; do
        sleep 1
        waited=$((waited + 1))
    done

    if kill -0 "$pid" 2>/dev/null; then
        log_warn "Force-killing llama-server (PID: $pid)..."
        kill -9 "$pid" 2>/dev/null || true
    fi

    pkill -9 -f "llama-server.*${LLM_PORT}" 2>/dev/null || true
    rm -f "$LLM_PID_FILE"
    log_info "llama-server stopped"

    sleep 3
    log_info "GPU 0 memory after stop:"
    nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader -i 0 2>/dev/null || true
}

do_restart() { do_stop; sleep 2; do_start; }

do_status() {
    if is_running; then
        local pid
        pid=$(get_pid)
        echo -e "${GREEN}● llama-server is running${NC}"
        echo "  PID: $pid"
        echo "  Port: $LLM_PORT"
        echo "  Model: $(basename "$LLM_MODEL_PATH")"

        if curl -sf "http://localhost:${LLM_PORT}/health" &>/dev/null; then
            echo -e "  Health: ${GREEN}healthy${NC}"
            # Show loaded model info
            local slots
            slots=$(curl -sf "http://localhost:${LLM_PORT}/health" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Status: {d.get(\"status\",\"unknown\")}')" 2>/dev/null) || true
            [[ -n "$slots" ]] && echo "  $slots"
        else
            echo -e "  Health: ${YELLOW}loading/unhealthy${NC}"
        fi

        echo "  GPU Memory:"
        nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader -i 0 2>/dev/null | \
            awk -F', ' '{printf "    Used: %s MiB / %s MiB (GPU Util: %s%%)\n", $1, $2, $3}'
        return 0
    else
        echo -e "${RED}● llama-server is not running${NC}"
        return 1
    fi
}

do_health() {
    if ! is_running; then
        echo '{"status": "not_running", "engine": "llama.cpp"}'
        return 1
    fi

    local response
    response=$(curl -sf "http://localhost:${LLM_PORT}/v1/models" 2>/dev/null) || {
        echo '{"status": "unhealthy", "engine": "llama.cpp", "error": "API not responding"}'
        return 1
    }

    echo "{\"status\": \"healthy\", \"engine\": \"llama.cpp\", \"port\": ${LLM_PORT}, \"models\": ${response}}"
    return 0
}

do_yield() {
    log_info "Yielding GPU 0 for training..."
    do_stop

    local mem_used
    mem_used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i 0 2>/dev/null || echo "0")
    if [[ "${mem_used}" -lt 1000 ]]; then
        log_info "GPU 0 freed (${mem_used} MiB in use)"
    else
        log_warn "GPU 0 still has ${mem_used} MiB in use"
    fi
}

do_restore() {
    log_info "Restoring llama-server after training..."
    sleep 5
    do_start
}

# =============================================================================
# Main
# =============================================================================

case "${1:-help}" in
    start)   do_start ;;
    stop)    do_stop ;;
    restart) do_restart ;;
    status)  do_status ;;
    health)  do_health ;;
    yield)   do_yield ;;
    restore) do_restore ;;
    help|*)
        echo "Usage: $0 {start|stop|restart|status|health|yield|restore}"
        echo ""
        echo "Commands:"
        echo "  start    - Start llama-server with GPU acceleration"
        echo "  stop     - Stop llama-server gracefully"
        echo "  restart  - Stop then start"
        echo "  status   - Show status"
        echo "  health   - JSON health check"
        echo "  yield    - Stop for training (free GPU)"
        echo "  restore  - Restart after training"
        echo ""
        echo "Environment:"
        echo "  LLM_MODEL_PATH=$LLM_MODEL_PATH"
        echo "  LLM_PORT=$LLM_PORT"
        echo "  LLM_GPU_LAYERS=$LLM_GPU_LAYERS"
        echo "  LLM_CONTEXT_LEN=$LLM_CONTEXT_LEN"
        ;;
esac
