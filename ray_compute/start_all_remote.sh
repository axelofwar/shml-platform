#!/bin/bash

# Start Ray Compute Services - Remote Edition
# Starts Ray cluster and remote API server

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================================="
echo "Starting Ray Compute - Remote Edition"
echo "=================================================="

# Check if Ray is installed
if ! command -v ray &> /dev/null; then
    echo "ERROR: Ray is not installed. Please run scripts/install_ray_cluster.sh first"
    exit 1
fi

# Check if services are already running
if pgrep -f "ray start --head" > /dev/null; then
    echo "⚠️  Ray head node already running"
else
    echo ""
    echo "1. Starting Ray Head Node..."
    bash scripts/start_ray_head.sh
    sleep 3
fi

# Check Ray Dashboard
echo ""
echo "2. Checking Ray Dashboard..."
if curl -s http://localhost:8265 > /dev/null; then
    echo "   ✓ Ray Dashboard accessible at http://localhost:8265"
else
    echo "   ⚠️  Ray Dashboard not accessible (may need a moment to start)"
fi

# Check MLflow connectivity
echo ""
echo "3. Checking MLflow Server..."
if curl -s http://localhost:8080/health > /dev/null; then
    echo "   ✓ MLflow Server accessible at http://localhost:8080"
else
    echo "   ✗ MLflow Server not accessible"
    echo "   Please start MLflow server first"
    exit 1
fi

# Start Remote API Server
echo ""
echo "4. Starting Remote API Server..."

# Stop existing API server if running
if pgrep -f "ray_compute/api/server_remote.py" > /dev/null; then
    echo "   Stopping existing API server..."
    pkill -f "ray_compute/api/server_remote.py" || true
    sleep 2
fi

# Start API server
python3 api/server_remote.py > logs/api_remote.log 2>&1 &
API_PID=$!
echo "   API server started (PID: $API_PID)"
sleep 3

# Verify API server
if curl -s http://localhost:8266/health > /dev/null; then
    echo "   ✓ Remote API accessible at http://localhost:8266"
else
    echo "   ✗ Failed to start API server"
    echo "   Check logs/api_remote.log for errors"
    exit 1
fi

# Get Tailscale IP
echo ""
echo "5. Getting Tailscale VPN Address..."
TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "not available")
if [ "$TAILSCALE_IP" != "not available" ]; then
    echo "   ✓ Tailscale IP: $TAILSCALE_IP"
    echo ""
    echo "   Remote clients should connect to:"
    echo "   http://$TAILSCALE_IP:8266"
else
    echo "   ⚠️  Tailscale not running or not configured"
    echo "   Remote access will not be available"
fi

echo ""
echo "=================================================="
echo "Ray Compute - Remote Edition Started"
echo "=================================================="
echo ""
echo "Services:"
echo "  - Ray Dashboard:  http://localhost:8265"
echo "  - MLflow Server:  http://localhost:8080"
echo "  - Compute API:    http://localhost:8266"
if [ "$TAILSCALE_IP" != "not available" ]; then
echo "  - Remote API:     http://$TAILSCALE_IP:8266"
fi
echo ""
echo "Logs:"
echo "  - Ray:            $SCRIPT_DIR/logs/ray_head.log"
echo "  - API:            $SCRIPT_DIR/logs/api_remote.log"
echo ""
echo "Check status:       bash scripts/check_status.sh"
echo "Stop services:      bash stop_all_remote.sh"
echo "Run validation:     python3 test_remote_compute.py http://$TAILSCALE_IP:8266"
echo ""
