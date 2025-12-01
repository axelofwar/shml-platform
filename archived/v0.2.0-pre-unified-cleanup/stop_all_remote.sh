#!/bin/bash

# Stop Ray Compute Services - Remote Edition

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================================="
echo "Stopping Ray Compute - Remote Edition"
echo "=================================================="

# Stop API server
echo ""
echo "1. Stopping Remote API Server..."
if pgrep -f "ray_compute/api/server_remote.py" > /dev/null; then
    pkill -f "ray_compute/api/server_remote.py"
    echo "   ✓ API server stopped"
else
    echo "   ⚠️  API server not running"
fi

# Stop Ray
echo ""
echo "2. Stopping Ray Cluster..."
bash scripts/stop_ray.sh

echo ""
echo "=================================================="
echo "Ray Compute - Remote Edition Stopped"
echo "=================================================="
echo ""
