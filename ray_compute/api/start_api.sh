#!/bin/bash
# Start the Ray Compute API server

set -e

echo "Starting Ray Compute API server..."

# Check if Ray is running
if ! ray status &>/dev/null 2>&1; then
    echo "❌ Ray cluster is not running"
    echo "Start Ray first: cd ../scripts && ./start_ray_head.sh"
    exit 1
fi

echo "✓ Ray cluster is running"

# Start API server
python3 server.py
