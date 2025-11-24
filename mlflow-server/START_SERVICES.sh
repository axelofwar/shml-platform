#!/bin/bash
# Unified ML Platform Startup Script
# Starts all services via Traefik routing

set -e

echo "========================================="
echo "Starting ML Platform Services (Unified)"
echo "========================================="
echo ""

# Check if ml-platform network exists
if ! docker network inspect ml-platform >/dev/null 2>&1; then
    echo "Creating ml-platform network..."
    docker network create ml-platform
    echo "✓ Network created"
fi

# Check if Traefik gateway is running
if ! docker ps | grep -q ml-platform-gateway; then
    echo "⚠  Traefik gateway not running. Start Ray Compute first:"
    echo "   cd ../ray_compute && docker-compose up -d"
    echo ""
    read -p "Press Enter to continue when Ray Compute is running..."
fi

# Start MLflow services
echo "Starting MLflow services..."
cd "$(dirname "$0")"
docker-compose up -d

echo ""
echo "Waiting for services to be healthy..."
sleep 15

echo ""
echo "========================================="
echo "Service Status"
echo "========================================="
docker-compose ps

echo ""
echo "========================================="
echo "Access URLs (via Traefik)"
echo "========================================="
echo "MLflow UI:        http://localhost/mlflow/"
echo "MLflow Grafana:   http://localhost/grafana/"
echo "MLflow Prometheus: http://localhost/prometheus/"
echo "Adminer:          http://localhost/adminer/"
echo "Ray Dashboard:    http://localhost/ray/"
echo "Ray Grafana:      http://localhost/ray-grafana/"
echo "Traefik Dashboard: http://localhost:8090/"
echo ""
echo "========================================="
echo "Remote Client Configuration"
echo "========================================="
echo "Python:"
echo "  mlflow.set_tracking_uri('http://localhost/mlflow')"
echo ""
echo "Environment Variable:"
echo "  export MLFLOW_TRACKING_URI='http://localhost/mlflow'"
echo ""
echo "✓ All services accessible via unified Traefik routing"
echo "========================================="
