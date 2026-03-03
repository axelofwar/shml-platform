#!/bin/bash
# stop_nemotron.sh
# Stop Nemotron-3-Nano coding model service

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🛑 Stopping Nemotron-3-Nano coding model..."

if docker ps | grep -q nemotron-coding; then
    docker compose down
    echo "✅ Nemotron-3-Nano stopped"

    # Show GPU memory freed
    GPU_USED=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits | awk -F, '$1==0 {print $2}')
    echo "📊 RTX 3090 Ti memory: ${GPU_USED}MB"
else
    echo "ℹ️  Nemotron-3-Nano was not running"
fi
