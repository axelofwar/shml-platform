#!/bin/bash
# ============================================================================
# SHML Platform - Start Nemotron-3 Coding Model (Self-Hosted)
# ============================================================================
#
# This script starts Nemotron-3 8B on RTX 3090 Ti (cuda:0) for code generation.
#
# PREREQUISITES:
#   - Phase 5 training must be COMPLETE (check: nvidia-smi)
#   - RTX 3090 Ti must have <4GB VRAM in use
#   - vLLM or text-generation-inference must be available
#
# PRIVACY: 100% local - no external API calls
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Configuration
MODEL_NAME="nvidia/Nemotron-3-8B-Instruct"
MODEL_DIR="${PROJECT_ROOT}/data/models/nemotron-3-8b"
GPU_DEVICE="cuda:0"  # RTX 3090 Ti
PORT=8001
MAX_MODEL_LEN=131072
GPU_MEMORY_UTILIZATION=0.90

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     SHML Platform - Nemotron-3 Coding Model (Self-Hosted)      ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check if training is still running
check_training() {
    local gpu_util=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits -i 0 2>/dev/null | tr -d ' ')
    local gpu_mem=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i 0 2>/dev/null | tr -d ' ')

    echo -e "${YELLOW}Checking RTX 3090 Ti (cuda:0) status...${NC}"
    echo "  GPU Utilization: ${gpu_util}%"
    echo "  GPU Memory Used: ${gpu_mem} MiB"

    if [ "$gpu_util" -gt 50 ] || [ "$gpu_mem" -gt 4000 ]; then
        echo ""
        echo -e "${RED}⚠️  WARNING: RTX 3090 Ti appears to be in use!${NC}"
        echo -e "${RED}   Training may still be running.${NC}"
        echo ""
        echo "Current processes on GPU 0:"
        nvidia-smi --query-compute-apps=pid,name,used_memory --format=csv,noheader -i 0 2>/dev/null || echo "  (none)"
        echo ""
        read -p "Continue anyway? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo -e "${RED}Aborted.${NC}"
            exit 1
        fi
    else
        echo -e "${GREEN}✓ RTX 3090 Ti is available${NC}"
    fi
}

# Download model if not present
download_model() {
    if [ ! -d "$MODEL_DIR" ]; then
        echo -e "${YELLOW}Downloading ${MODEL_NAME}...${NC}"
        echo "This may take a while (~16GB)"

        mkdir -p "$MODEL_DIR"

        # Use huggingface-cli if available
        if command -v huggingface-cli &> /dev/null; then
            huggingface-cli download "$MODEL_NAME" --local-dir "$MODEL_DIR"
        else
            echo -e "${RED}huggingface-cli not found. Install with: pip install huggingface_hub${NC}"
            exit 1
        fi
    else
        echo -e "${GREEN}✓ Model already downloaded at ${MODEL_DIR}${NC}"
    fi
}

# Start with vLLM
start_vllm() {
    echo ""
    echo -e "${GREEN}Starting Nemotron-3 with vLLM on port ${PORT}...${NC}"
    echo ""

    # Check if vLLM is available
    if ! command -v python -c "import vllm" &> /dev/null 2>&1; then
        echo -e "${YELLOW}vLLM not found in current environment.${NC}"
        echo "Trying Docker instead..."
        start_docker
        return
    fi

    CUDA_VISIBLE_DEVICES=0 python -m vllm.entrypoints.openai.api_server \
        --model "$MODEL_DIR" \
        --port $PORT \
        --max-model-len $MAX_MODEL_LEN \
        --gpu-memory-utilization $GPU_MEMORY_UTILIZATION \
        --trust-remote-code \
        --dtype auto \
        --api-key "local-nemotron" \
        2>&1 | tee "${PROJECT_ROOT}/logs/nemotron.log"
}

# Start with Docker (fallback)
start_docker() {
    echo ""
    echo -e "${GREEN}Starting Nemotron-3 with Docker vLLM...${NC}"
    echo ""

    docker run --rm -d \
        --name nemotron-3-vllm \
        --gpus '"device=0"' \
        -v "${MODEL_DIR}:/model:ro" \
        -p ${PORT}:8000 \
        --shm-size=16g \
        vllm/vllm-openai:latest \
        --model /model \
        --max-model-len $MAX_MODEL_LEN \
        --gpu-memory-utilization $GPU_MEMORY_UTILIZATION \
        --trust-remote-code

    echo ""
    echo -e "${GREEN}✓ Nemotron-3 container started${NC}"
    echo "  Container: nemotron-3-vllm"
    echo "  Port: ${PORT}"
    echo "  Logs: docker logs -f nemotron-3-vllm"
}

# Health check
health_check() {
    echo ""
    echo -e "${YELLOW}Waiting for model to load (this may take 1-2 minutes)...${NC}"

    for i in {1..60}; do
        if curl -s "http://localhost:${PORT}/health" > /dev/null 2>&1; then
            echo ""
            echo -e "${GREEN}✓ Nemotron-3 is ready!${NC}"
            echo ""
            echo "Endpoints:"
            echo "  • OpenAI-compatible: http://localhost:${PORT}/v1"
            echo "  • Health check: http://localhost:${PORT}/health"
            echo "  • Models: http://localhost:${PORT}/v1/models"
            echo ""
            echo "OpenCode will automatically use this for code generation."
            echo ""
            return 0
        fi
        sleep 2
        echo -n "."
    done

    echo ""
    echo -e "${RED}⚠️  Model did not become ready within 2 minutes${NC}"
    echo "Check logs: tail -f ${PROJECT_ROOT}/logs/nemotron.log"
    return 1
}

# Main
main() {
    check_training
    download_model
    start_vllm &
    health_check
}

main "$@"
