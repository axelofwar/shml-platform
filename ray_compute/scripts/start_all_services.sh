#!/bin/bash
# Startup script for all Ray Compute services
# Run this on boot or after reboot

set -e

echo "=== Starting Ray Compute Platform ==="
echo "Timestamp: $(date)"

# Get script directory and navigate to project root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# Wait for network to be ready
echo "Waiting for network..."
sleep 5

# Start services in order
echo ""
echo "1. Starting Authentication Services (Authentik)..."
docker-compose -f docker-compose.auth.yml up -d
sleep 10

echo ""
echo "2. Starting API Server and Redis..."
docker-compose -f docker-compose.api.yml up -d
sleep 5

echo ""
echo "3. Starting Observability Stack (Prometheus, Grafana, Loki)..."
docker-compose -f docker-compose.observability.yml up -d
sleep 5

echo ""
echo "4. Starting Web UI..."
docker-compose -f docker-compose.ui.yml up -d
sleep 5

echo ""
echo "=== Checking Service Status ==="
docker-compose -f docker-compose.auth.yml ps
docker-compose -f docker-compose.api.yml ps
docker-compose -f docker-compose.observability.yml ps
docker-compose -f docker-compose.ui.yml ps

echo ""
echo "=== Services Started ==="
echo "✅ Ray Compute Web UI: http://localhost:3002"
echo "✅ Ray Compute API: http://localhost:8000/docs"
echo "✅ Authentik: http://localhost:9000"
echo "✅ Grafana: http://localhost:3001"
echo "✅ Prometheus: http://localhost:9090"
echo ""
echo "All services configured with restart: unless-stopped"
echo "Services will auto-start on system reboot"
echo ""
echo "Check service health: $PROJECT_ROOT/scripts/check_services.sh"
