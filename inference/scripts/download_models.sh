#!/bin/bash
# Download models for offline use
# Run this ONCE with internet, then models are cached for air-gapped operation

set -e

MODEL_DIR="${MODEL_DIR:-./data/models}"
mkdir -p "$MODEL_DIR"

echo "=========================================="
echo "Downloading models for offline inference"
echo "=========================================="
echo ""

# Check if huggingface-cli is available
if ! command -v huggingface-cli &> /dev/null; then
    echo "Installing huggingface_hub..."
    pip install huggingface_hub
fi

echo "[1/2] Downloading Qwen3-VL-8B-Instruct..."
echo "      This is ~16GB and may take 10-30 minutes"
huggingface-cli download Qwen/Qwen3-VL-8B-Instruct \
    --local-dir "$MODEL_DIR/Qwen/Qwen3-VL-8B-Instruct" \
    --local-dir-use-symlinks False

echo ""
echo "[2/2] Downloading Z-Image-Turbo..."
echo "      This is ~12GB and may take 10-20 minutes"
huggingface-cli download Tongyi-MAI/Z-Image-Turbo \
    --local-dir "$MODEL_DIR/Tongyi-MAI/Z-Image-Turbo" \
    --local-dir-use-symlinks False

echo ""
echo "=========================================="
echo "Downloads complete!"
echo "=========================================="
echo ""
echo "Models saved to: $MODEL_DIR"
echo "Total size: $(du -sh $MODEL_DIR | cut -f1)"
echo ""
echo "To use offline, mount this directory as /models in containers"
echo "and set TRANSFORMERS_OFFLINE=1"
