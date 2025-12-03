#!/bin/bash
# Validate all services are ready after reboot

echo "=== Ray Compute Platform Health Check ==="
echo ""

# Check Docker
echo "1. Checking Docker..."
if ! systemctl is-active --quiet docker; then
    echo "   ❌ Docker is not running!"
    echo "   Run: sudo systemctl start docker"
    exit 1
else
    echo "   ✅ Docker is running"
fi

# Get script directory and navigate to project root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Check environment files
echo ""
echo "2. Checking environment files..."
if [ -f "$PROJECT_ROOT/.env" ]; then
    echo "   ✅ Ray Compute .env exists"
else
    echo "   ❌ Ray Compute .env missing!"
    echo "   Copy from: cp $PROJECT_ROOT/.env.example $PROJECT_ROOT/.env"
    exit 1
fi

# Check containers
echo ""
echo "3. Checking containers..."

EXPECTED_CONTAINERS=(
    "fusionauth"
    "ray-compute-api"
    "ray-compute-ui"
    "ray-redis"
    "ray-prometheus"
    "ray-grafana"
)

RUNNING=0
STOPPED=0

for container in "${EXPECTED_CONTAINERS[@]}"; do
    if docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
        echo "   ✅ $container is running"
        ((RUNNING++))
    else
        if docker ps -a --format '{{.Names}}' | grep -q "^${container}$"; then
            echo "   ⚠️  $container exists but is stopped"
            ((STOPPED++))
        else
            echo "   ❌ $container does not exist"
        fi
    fi
done

# Check services
echo ""
echo "4. Checking service endpoints..."

services=(
    "http://localhost:3002|Ray Compute Web UI"
    "http://localhost:8000/docs|Ray Compute API"
    "http://localhost:9000|Authentik"
    "http://localhost:3001|Grafana"
    "http://localhost:9090|Prometheus"
)

for service in "${services[@]}"; do
    IFS='|' read -r url name <<< "$service"
    if curl -s -f -o /dev/null "$url" --max-time 5; then
        echo "   ✅ $name is responding"
    else
        echo "   ⚠️  $name is not responding (may still be starting)"
    fi
done

echo ""
echo "=== Summary ==="
echo "Running containers: $RUNNING / ${#EXPECTED_CONTAINERS[@]}"
if [ $STOPPED -gt 0 ]; then
    echo "Stopped containers: $STOPPED"
    echo ""
    echo "To start stopped containers, run:"
    echo "  cd /home/axelofwar/Desktop/Projects"
    echo "  ./start_all_services.sh"
fi

if [ $RUNNING -eq ${#EXPECTED_CONTAINERS[@]} ]; then
    echo ""
    echo "✅ All critical services are running!"
    echo ""
    echo "Access the platform at: http://localhost:3002"
else
    echo ""
    echo "⚠️  Some services are not running. Check logs:"
    echo "  docker logs <container-name> -f"
fi
