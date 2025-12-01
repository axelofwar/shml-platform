#!/bin/bash
# Stop all Ray Compute services

set -e

echo "Stopping Ray Compute services..."

# Stop API server
echo "Stopping API server..."
pkill -f "python3.*server.py" 2>/dev/null || true
pkill -f "uvicorn" 2>/dev/null || true

# Stop Ray cluster
echo "Stopping Ray cluster..."
ray stop --force 2>/dev/null || true

# Clean up temp files
echo "Cleaning up temporary files..."
rm -rf /opt/ray/tmp/* 2>/dev/null || true

echo ""
echo "✓ All services stopped"
echo ""
echo "To restart: ./start_all.sh"
echo ""
