#!/bin/bash
# Signal Z-Image to yield GPU to training

set -e

echo "Signaling Z-Image to unload and free RTX 3090..."

response=$(curl -s -X POST http://localhost/api/image/yield-to-training)

if echo "$response" | grep -q "yielded"; then
    echo "✓ Z-Image unloaded, RTX 3090 is free for training"
    echo "  VRAM freed: $(echo $response | jq -r '.vram_freed_gb')GB"
else
    echo "Z-Image was not loaded (already free)"
fi

echo ""
echo "You can now start training on RTX 3090."
echo "Z-Image will reload automatically on next request."
