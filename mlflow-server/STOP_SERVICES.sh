#!/bin/bash
# Unified ML Platform Shutdown Script
# Stops MLflow services (keeps Ray Compute and Traefik running)

set -e

echo "========================================="
echo "Stopping MLflow Services"
echo "========================================="
echo ""

cd "$(dirname "$0")"
docker-compose down

echo ""
echo "✓ MLflow services stopped"
echo ""
echo "Note: Ray Compute and Traefik gateway still running"
echo "To stop everything:"
echo "  cd ../ray_compute && docker-compose down"
echo "========================================="
