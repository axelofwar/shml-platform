#!/bin/bash
# Quick Start Script - Run after installation is complete
# This script starts the entire Ray Compute system

set -e

echo "================================================"
echo "Ray Compute - Quick Start"
echo "================================================"
echo ""

# Check prerequisites
echo "Checking prerequisites..."

# Check NVIDIA drivers
if ! nvidia-smi &>/dev/null; then
    echo "❌ NVIDIA drivers not found!"
    echo "Run: ./scripts/install_nvidia_drivers.sh"
    exit 1
fi
echo "✓ NVIDIA drivers installed"

# Check Docker
if ! docker info &>/dev/null; then
    echo "❌ Docker not accessible!"
    echo "Run: ./scripts/install_docker_nvidia.sh"
    exit 1
fi
echo "✓ Docker accessible"

# Check Docker GPU access
if ! docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu20.04 nvidia-smi &>/dev/null 2>&1; then
    echo "❌ GPU not accessible in Docker!"
    echo "Run: ./scripts/install_docker_nvidia.sh"
    exit 1
fi
echo "✓ GPU accessible in Docker"

# Check Ray
if ! python3 -c "import ray" &>/dev/null; then
    echo "❌ Ray not installed!"
    echo "Run: ./scripts/install_ray_cluster.sh"
    exit 1
fi
echo "✓ Ray installed"

# Check Docker images
if ! docker images | grep -q "mlflow-compute-gpu"; then
    echo "⚠️  Docker images not built"
    echo "Building images now..."
    cd docker && ./build_images.sh && cd ..
fi
echo "✓ Docker images available"

echo ""
echo "================================================"
echo "Starting Services"
echo "================================================"
echo ""

# Stop any existing Ray cluster
echo "Stopping any existing Ray cluster..."
ray stop --force 2>/dev/null || true
sleep 2

# Start Ray head node
echo ""
echo "Starting Ray head node..."
./scripts/start_ray_head.sh

# Wait for Ray to be ready
echo ""
echo "Waiting for Ray cluster to be ready..."
sleep 5

# Verify Ray is running
if ! ray status &>/dev/null 2>&1; then
    echo "❌ Ray cluster failed to start"
    echo "Check logs: cat /opt/ray/logs/ray_*.log"
    exit 1
fi
echo "✓ Ray cluster running"

# Start API server in background
echo ""
echo "Starting API server..."
cd api
python3 server.py > /opt/ray/logs/api_server.log 2>&1 &
API_PID=$!
cd ..

# Wait for API to be ready
echo "Waiting for API server to be ready..."
for i in {1..30}; do
    if curl -s http://localhost:8266/health &>/dev/null; then
        echo "✓ API server running (PID: $API_PID)"
        break
    fi
    sleep 1
done

if ! curl -s http://localhost:8266/health &>/dev/null; then
    echo "❌ API server failed to start"
    echo "Check logs: tail -f /opt/ray/logs/api_server.log"
    kill $API_PID 2>/dev/null || true
    exit 1
fi

echo ""
echo "================================================"
echo "✓ Ray Compute Started Successfully!"
echo "================================================"
echo ""
echo "Services running:"
echo "  • Ray Dashboard:  http://localhost:8265"
echo "  • Compute API:    http://localhost:8266"
echo "  • API Docs:       http://localhost:8266/docs"
echo "  • MLflow UI:      http://localhost:8080"
echo ""
echo "Status commands:"
echo "  • Check status:   ./scripts/check_status.sh"
echo "  • View API logs:  tail -f /opt/ray/logs/api_server.log"
echo "  • View Ray logs:  tail -f /opt/ray/logs/ray_*.log"
echo ""
echo "Stop services:"
echo "  • Stop all:       ./stop_all.sh"
echo "  • Stop Ray:       ./scripts/stop_ray.sh"
echo "  • Stop API:       kill $API_PID"
echo ""
echo "Next steps:"
echo "  1. Test GPU: python3 -c 'from api.client import *; submit_training_job(\"gpu-test\", \"import torch; print(torch.cuda.get_device_name(0))\", gpu=True)'"
echo "  2. Run example: cd pipelines && python3 yolo_training.py"
echo "  3. Check dashboard: firefox http://localhost:8265"
echo ""
