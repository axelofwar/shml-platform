#!/bin/bash
# yield_to_training.sh
# Called by Ray training jobs before GPU allocation
# Stops Nemotron-3 to free RTX 3090 Ti for training

set -e

echo "[$(date)] Yield-to-training: Stopping Nemotron coding model..."

# Check if Nemotron is running
if docker ps | grep -q qwopus-coding; then
    docker stop qwopus-coding || true
    echo "[$(date)] ✓ Nemotron stopped - RTX 3090 Ti (cuda:0) available for training"
else
    echo "[$(date)] ℹ Nemotron not running - RTX 3090 Ti already available"
fi

# Wait for GPU to be fully released
sleep 2

# Verify GPU is free
GPU_USED=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits | awk -F, '$1==0 {print $2}')
if [ "$GPU_USED" -lt 1000 ]; then
    echo "[$(date)] ✓ RTX 3090 Ti memory: ${GPU_USED}MB (ready for training)"
    exit 0
else
    echo "[$(date)] ⚠ RTX 3090 Ti memory: ${GPU_USED}MB (some processes still active)"
    nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader | grep -v "N/A"
    exit 1
fi
