#!/bin/bash
# Build Docker images for Ray workers

set -e

echo "================================================"
echo "Building Docker Images for Ray Compute"
echo "================================================"

# Check if Docker is available
if ! docker info &>/dev/null; then
    echo "❌ Error: Docker is not running or accessible"
    echo "Run: sudo systemctl start docker"
    exit 1
fi

# Check if NVIDIA runtime is available
if docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu20.04 nvidia-smi &>/dev/null 2>&1; then
    echo "✓ NVIDIA Docker runtime detected"
    BUILD_GPU=true
else
    echo "⚠️  Warning: NVIDIA Docker runtime not available"
    echo "GPU image will not be built"
    BUILD_GPU=false
fi

echo ""
echo "Building CPU image..."
docker build -t mlflow-compute-cpu:latest -f Dockerfile.cpu .
echo "✓ CPU image built: mlflow-compute-cpu:latest"

if [ "$BUILD_GPU" = true ]; then
    echo ""
    echo "Building GPU image (this may take 10-15 minutes)..."
    docker build -t mlflow-compute-gpu:latest -f Dockerfile.gpu .
    echo "✓ GPU image built: mlflow-compute-gpu:latest"
    
    echo ""
    echo "Testing GPU image..."
    if docker run --rm --gpus all mlflow-compute-gpu:latest python3 -c "import torch; assert torch.cuda.is_available(); print(f'✓ GPU accessible: {torch.cuda.get_device_name(0)}')"; then
        echo "✓ GPU test passed"
    else
        echo "❌ GPU test failed"
        exit 1
    fi
fi

echo ""
echo "================================================"
echo "Images built successfully!"
echo "================================================"
echo ""
docker images | grep mlflow-compute
echo ""
echo "Next steps:"
echo "  1. Start Ray head node: cd ../scripts && ./start_ray_head.sh"
echo "  2. Deploy API server: cd ../api && python3 server.py"
echo ""
