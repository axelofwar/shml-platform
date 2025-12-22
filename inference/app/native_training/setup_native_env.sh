#!/bin/bash
# =============================================================================
# Setup Native Training Environment
#
# Installs required packages for native YOLO training with SOTA techniques.
# Run this once before starting training.
#
# Usage:
#   ./setup_native_env.sh
#
# Author: SHML Platform
# =============================================================================

set -euo pipefail

echo "=== Setting up Native Training Environment ==="

# Check Python version
python_version=$(python3 --version 2>&1)
echo "Python: $python_version"

# Required packages for native training
packages=(
    "ultralytics>=8.0.0"        # YOLO training
    "mlflow>=2.0.0"             # Experiment tracking
    "numpy>=1.20.0"             # Numerical operations
    "aiohttp>=3.8.0"            # Async HTTP for coordinator
    "Pillow>=9.0.0"             # Image processing
    "opencv-python>=4.5.0"      # Computer vision
    "psutil>=5.9.0"             # System monitoring
    "requests>=2.28.0"          # HTTP client for MLflow
)

echo ""
echo "Installing packages..."
pip3 install --user "${packages[@]}"

echo ""
echo "Verifying installation..."
python3 -c "
import torch
import ultralytics
import mlflow
import numpy
import aiohttp
print('✓ torch:', torch.__version__)
print('✓ ultralytics:', ultralytics.__version__)
print('✓ mlflow:', mlflow.__version__)
print('✓ numpy:', numpy.__version__)
print('✓ aiohttp:', aiohttp.__version__)
print()
print('CUDA available:', torch.cuda.is_available())
"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "To start training:"
echo "  ./sandbox_training.sh --model yolov8n.pt --data wider_face --epochs 100"
echo ""
echo "Or via API:"
echo "  curl -X POST http://localhost:8000/training/start -H 'Content-Type: application/json' -d '{\"model\": \"yolov8n.pt\", \"epochs\": 100}'"
