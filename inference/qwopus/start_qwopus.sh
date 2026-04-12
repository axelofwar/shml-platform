#!/bin/bash
# start_qwopus.sh
# Quick start script for Qwopus coding model (Qwen3.5-27B Q4_K_M)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🚀 Starting Qwopus coding model (Qwen3.5-27B Q4_K_M)..."

# Check if model is downloaded
MODEL_PATH="../../data/models/qwopus/Qwen3.5-27B-Q4_K_M.gguf"
if [ ! -f "$MODEL_PATH" ]; then
    echo "❌ Model not found at: $MODEL_PATH"
    echo ""
    echo "Download it first:"
    echo "  huggingface-cli download Qwen/Qwen3.5-27B-GGUF \\"
    echo "    --include '*Q4_K_M*' \\"
    echo "    --local-dir ../../data/models/qwopus/"
    exit 1
fi

# Check if RTX 3090 Ti is available
GPU_USED=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits | awk -F, '$1==0 {print $2}')
if [ "$GPU_USED" -gt 5000 ]; then
    echo "⚠️  RTX 3090 Ti (cuda:0) has ${GPU_USED}MB in use"
    echo "   This may be training or another process."
    echo ""
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Start service
echo "📦 Starting Docker container..."
docker compose up -d

# Wait for service to be ready
echo "⏳ Waiting for llama-server to be ready..."
for i in {1..30}; do
    if curl -sf http://localhost:8010/health > /dev/null 2>&1; then
        echo "✅ Qwopus coding model is ready!"
        echo ""
        echo "📊 Service Info:"
        echo "   - API Endpoint: http://localhost:8010/v1"
        echo "   - Model: Qwen3.5-27B (Q4_K_M)"
        echo "   - Context: 32K tokens"
        echo "   - GPU: RTX 3090 Ti (cuda:0)"
        echo ""
        echo "🧪 Test inference:"
        echo "   curl http://localhost:8010/v1/chat/completions \\"
        echo "     -H 'Content-Type: application/json' \\"
        echo "     -d '{\"model\":\"qwopus-coding\",\"messages\":[{\"role\":\"user\",\"content\":\"Hello\"}]}'"
        echo ""
        echo "📝 Logs:"
        echo "   docker logs qwopus-coding -f"
        exit 0
    fi
    sleep 2
done

echo "❌ Service did not become ready in time"
echo "   Check logs: docker logs qwopus-coding"
exit 1
