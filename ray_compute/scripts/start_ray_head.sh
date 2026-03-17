#!/bin/bash
# Start Ray head node

set -e

echo "================================================"
echo "Starting Ray Head Node"
echo "================================================"

# Stop any existing Ray instance
ray stop --force 2>/dev/null || true

# Start Ray head node
ray start \
    --head \
    --port=6379 \
    --dashboard-host=0.0.0.0 \
    --dashboard-port=8265 \
    --num-cpus=4 \
    --num-gpus=0 \
    --object-store-memory=2147483648 \
    --temp-dir=/opt/ray/tmp \
    --log-style=pretty \
    --log-color=True

echo ""
echo "✓ Ray head node started"
echo ""
echo "Dashboard: http://localhost:8265"
echo "Ray address: ray://localhost:10001"
echo ""
echo "To connect workers:"
echo "  ray start --address='localhost:6379' --num-cpus=8 --num-gpus=1"
echo ""
echo "To stop:"
echo "  ray stop"
echo ""
