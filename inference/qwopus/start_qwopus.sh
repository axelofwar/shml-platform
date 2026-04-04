#!/bin/bash
# start_nemotron.sh
# Quick start script for Nemotron-3-Nano coding model

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🚀 Starting Nemotron-3-Nano-30B-A3B coding model..."

# Check if model is downloaded
MODEL_PATH="../../data/models/nemotron-3/Nemotron-3-Nano-30B-A3B-UD-Q4_K_XL.gguf"
if [ ! -f "$MODEL_PATH" ]; then
    echo "❌ Model not found at: $MODEL_PATH"
    echo ""
    echo "Download it first:"
    echo "  huggingface-cli download unsloth/Nemotron-3-Nano-30B-A3B-GGUF \\"
    echo "    --include '*UD-Q4_K_XL*' \\"
    echo "    --local-dir ../../data/models/nemotron-3/"
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
        echo "✅ Nemotron-3-Nano is ready!"
        echo ""
        echo "📊 Service Info:"
        echo "   - API Endpoint: http://localhost:8010/v1"
        echo "   - Model: Nemotron-3-Nano-30B-A3B (Q4_K_XL)"
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
