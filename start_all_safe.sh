#!/bin/bash
# Production-grade startup script with resource management and health monitoring
# Uses dynamic resource allocation based on actual system capacity

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "==============================================="
echo "ML Platform Safe Startup Script"
echo "==============================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
MAX_WAIT_TIME=300  # 5 minutes max wait for all services
HEALTH_CHECK_INTERVAL=5

# Function to print colored output
print_status() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

# Function to check service health
check_service_health() {
    local service=$1
    local status=$(docker inspect --format='{{.State.Health.Status}}' "${service}" 2>/dev/null || echo "no-healthcheck")
    echo "$status"
}

# Function to monitor startup progress
monitor_startup() {
    local start_time=$(date +%s)
    local phase=$1
    
    print_status "$BLUE" "\n📊 Monitoring $phase startup..."
    
    while true; do
        local current_time=$(date +%s)
        local elapsed=$((current_time - start_time))
        
        if [ $elapsed -gt $MAX_WAIT_TIME ]; then
            print_status "$RED" "⏱️  Timeout waiting for services to become healthy"
            docker-compose ps
            return 1
        fi
        
        # Get service status
        local unhealthy_count=$(docker-compose ps --services --filter "status=starting" --filter "status=unhealthy" 2>/dev/null | wc -l)
        local running_count=$(docker-compose ps --services --filter "status=running" 2>/dev/null | wc -l)
        
        echo -ne "\r⏳ Elapsed: ${elapsed}s | Running: ${running_count} | Checking health..."
        
        if [ $unhealthy_count -eq 0 ] && [ $running_count -gt 0 ]; then
            print_status "$GREEN" "\n✅ $phase services are healthy!"
            return 0
        fi
        
        sleep $HEALTH_CHECK_INTERVAL
    done
}

# Step 1: Pre-flight checks
print_status "$BLUE" "Step 1: Pre-flight checks..."
print_status "$BLUE" "---------------------------------------"

if ! command -v docker &> /dev/null; then
    print_status "$RED" "Error: Docker is required but not found"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    print_status "$RED" "Error: docker-compose is required but not found"
    exit 1
fi

print_status "$GREEN" "✓ Docker and docker-compose available"

# Step 2: Stop any running services
print_status "$BLUE" "\nStep 2: Stopping any running services..."
print_status "$BLUE" "---------------------------------------"

# First, stop and remove all containers managed by docker-compose
docker-compose down --remove-orphans 2>&1 | grep -v "WARNING: The following deploy" || true

# Then, forcibly remove any orphaned containers with our service names
print_status "$BLUE" "Checking for orphaned containers..."
ORPHANED_CONTAINERS=$(docker ps -a --format '{{.Names}}' | grep -E 'mlflow-|ray-|authentik-|ml-platform-' || true)

if [ ! -z "$ORPHANED_CONTAINERS" ]; then
    print_status "$YELLOW" "Found orphaned containers, removing..."
    echo "$ORPHANED_CONTAINERS" | while read container; do
        docker rm -f "$container" 2>/dev/null || true
    done
    print_status "$GREEN" "✓ Orphaned containers removed"
fi

print_status "$GREEN" "✓ All services stopped and cleaned up"

# Step 3: Start infrastructure services
print_status "$BLUE" "\nStep 3: Starting infrastructure services..."
print_status "$BLUE" "---------------------------------------"
print_status "$YELLOW" "Starting: traefik, redis, postgres databases..."

docker-compose up -d traefik redis mlflow-postgres ray-postgres authentik-db authentik-redis node-exporter cadvisor 2>&1 | grep -v "WARNING:" | tail -5

sleep 10
print_status "$GREEN" "✓ Infrastructure services started"

# Step 4: Start core application services  
print_status "$BLUE" "\nStep 4: Starting core application services..."
print_status "$BLUE" "---------------------------------------"
print_status "$YELLOW" "Starting: mlflow-server, ray-head, authentik-server..."

docker-compose up -d mlflow-server ray-head authentik-server 2>&1 | grep -v "WARNING:" | tail -5

print_status "$BLUE" "Waiting for core services to become healthy (this may take 60-90 seconds)..."
sleep 30

# Step 5: Start API and dependent services
print_status "$BLUE" "\nStep 5: Starting API and dependent services..."
print_status "$BLUE" "---------------------------------------"
print_status "$YELLOW" "Starting: mlflow-api, mlflow-nginx, ray-compute-api, authentik-worker..."

docker-compose up -d mlflow-nginx mlflow-api ray-compute-api authentik-worker 2>&1 | grep -v "WARNING:" | tail -5

sleep 20

# Step 6: Start monitoring services
print_status "$BLUE" "\nStep 6: Starting monitoring services..."
print_status "$BLUE" "---------------------------------------"
print_status "$YELLOW" "Starting: prometheus, grafana, adminer..."

docker-compose up -d mlflow-prometheus mlflow-grafana ray-prometheus ray-grafana mlflow-adminer 2>&1 | grep -v "WARNING:" | tail -5

sleep 10

# Step 7: Final status check
print_status "$BLUE" "\nStep 7: Checking final service status..."
print_status "$BLUE" "---------------------------------------"

docker-compose ps 2>&1 | grep -v "WARNING: The following deploy"

echo ""
print_status "$BLUE" "Checking service health..."
echo ""

# Check critical services
CRITICAL_SERVICES=("ml-platform-traefik" "mlflow-server" "mlflow-postgres" "ray-head")
FAILED_SERVICES=()

for service in "${CRITICAL_SERVICES[@]}"; do
    if docker ps --filter "name=$service" --filter "status=running" | grep -q "$service"; then
        health=$(check_service_health "$service")
        if [ "$health" = "healthy" ] || [ "$health" = "no-healthcheck" ]; then
            print_status "$GREEN" "  ✓ $service: Running"
        else
            print_status "$YELLOW" "  ⚠ $service: Running but health=$health"
            FAILED_SERVICES+=("$service")
        fi
    else
        print_status "$RED" "  ✗ $service: Not running"
        FAILED_SERVICES+=("$service")
    fi
done

echo ""

if [ ${#FAILED_SERVICES[@]} -eq 0 ]; then
    print_status "$GREEN" "================================================"
    print_status "$GREEN" "🎉 ML Platform started successfully!"
    print_status "$GREEN" "================================================"
    echo ""
    print_status "$BLUE" "📍 Access URLs:"
    echo ""
    
    LAN_IP=$(hostname -I | awk '{print $1}')
    TAILSCALE_HOST="axelofwar-dev-terminal-1.tail38b60a.ts.net"
    
    echo "  🌐 Local Access:"
    echo "    MLflow UI:          http://localhost/mlflow/"
    echo "    MLflow API:         http://localhost/api/v1/health"
    echo "    Ray Dashboard:      http://localhost/ray/"
    echo "    Traefik Dashboard:  http://localhost:8090/"
    echo ""
    echo "  🏠 LAN Access (${LAN_IP}):"
    echo "    MLflow UI:          http://${LAN_IP}/mlflow/"
    echo "    Ray Dashboard:      http://${LAN_IP}/ray/"
    echo ""
    echo "  🔐 VPN Access (Tailscale):"
    echo "    MLflow UI:          http://${TAILSCALE_HOST}/mlflow/"
    echo "    Ray Dashboard:      http://${TAILSCALE_HOST}/ray/"
    echo ""
    print_status "$BLUE" "📊 Management:"
    echo "    View logs:          docker-compose logs -f [service-name]"
    echo "    Check status:       docker-compose ps"
    echo "    Stop all:           docker-compose down"
    echo ""
    
    # Test API endpoint
    print_status "$BLUE" "🧪 Testing MLflow API..."
    if curl -s -m 3 http://localhost/api/v1/health > /dev/null 2>&1; then
        print_status "$GREEN" "  ✓ MLflow API is responding"
    else
        print_status "$YELLOW" "  ⚠ MLflow API not responding yet (may need more time)"
    fi
    
    exit 0
else
    print_status "$YELLOW" "================================================"
    print_status "$YELLOW" "⚠️  Platform started with warnings"
    print_status "$YELLOW" "================================================"
    echo ""
    print_status "$YELLOW" "Failed/Unhealthy services:"
    for service in "${FAILED_SERVICES[@]}"; do
        echo "  - $service"
    done
    echo ""
    print_status "$BLUE" "To investigate:"
    echo "  docker-compose logs [service-name]"
    echo "  docker-compose ps"
    echo ""
    exit 1
fi
