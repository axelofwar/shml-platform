#!/bin/bash
#
# ML Platform - Unified Shutdown Script
# Stops all services gracefully
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=================================================="
echo "ML Platform - Shutdown"
echo "=================================================="
echo ""

# Ask for confirmation
read -p "Stop all ML Platform services? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

echo ""
echo "Stopping services..."
echo ""

# Stop Ray Compute
echo "1. Stopping Ray Compute..."
cd "$PROJECT_ROOT/ray_compute"
docker compose -f docker-compose.unified.yml down 2>/dev/null || true
echo "   ✓ Ray Compute stopped"

echo ""
echo "2. Stopping MLflow Server..."
cd "$PROJECT_ROOT/mlflow-server"
docker compose -f docker-compose.unified.yml down 2>/dev/null || true
echo "   ✓ MLflow stopped"

echo ""
echo "3. Stopping Traefik Gateway..."
cd "$PROJECT_ROOT"
docker compose -f docker-compose.gateway.yml down 2>/dev/null || true
echo "   ✓ Traefik stopped"

echo ""
echo "=================================================="
echo "All services stopped"
echo "=================================================="
echo ""
echo "Data persists in:"
echo "  - $PROJECT_ROOT/ml-platform/mlflow-server/data/"
echo "  - $PROJECT_ROOT/ml-platform/ray_compute/data/"
echo ""
echo "To restart: bash $SCRIPT_DIR/start-ml-platform.sh"
echo ""

# Optionally stop MPS
if pgrep -f nvidia-cuda-mps > /dev/null; then
    read -p "Also stop GPU sharing (MPS)? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Stopping NVIDIA MPS..."
        echo quit | sudo nvidia-cuda-mps-control 2>/dev/null || true
        echo "✓ MPS stopped"
    fi
fi

echo ""
