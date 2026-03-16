#!/bin/bash
# Stop all Ray Compute and MLflow services

set -e

echo "=== Stopping All Services ==="

# Get script directory and navigate to project root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "Stopping Web UI..."
docker-compose -f docker-compose.ui.yml down

echo "Stopping Observability Stack..."
docker-compose -f docker-compose.observability.yml down

echo "Stopping API Server..."
docker-compose -f docker-compose.api.yml down

echo "Stopping Authentication Services..."
docker-compose -f docker-compose.auth.yml down

cd /opt/shml-platform/mlflow-server
echo "Stopping MLflow Server..."
docker-compose down

echo ""
echo "=== All Services Stopped ==="
