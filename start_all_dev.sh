#!/bin/bash
# ML Platform - Development Environment Startup Script
# Starts dev services on different ports to test upgrades alongside production
#
# Dev Ports (different from production):
#   - MLflow Dev:    5001 (production: 5000)
#   - PostgreSQL:    5433 (production: 5432)
#   - Ray Dev:       8266 (production: 8265)
#   - Grafana Dev:   3001 (production: 3000)
#   - Redis Dev:     6380 (production: 6379)
#
# NOTE: Dev environment does NOT include OAuth2 authentication
#       This is intentional for local development/testing
#       Production uses start_all_safe.sh which handles OAuth2 properly
#
# LESSONS LEARNED (applies to production, documented here for reference):
# - OAuth2 Proxy image is scratch/distroless - no wget/curl for healthchecks
# - Use "healthcheck: disable: true" in docker-compose for oauth2-proxy
# - OAuth2 Proxy uses /oauth2-proxy/* prefix (not /oauth2/*) to avoid FusionAuth conflict
#
# Usage:
#   ./start_all_dev.sh          # Start all dev services
#   ./start_all_dev.sh mlflow   # Start only MLflow dev
#   ./start_all_dev.sh ray      # Start only Ray dev
#   ./start_all_dev.sh stop     # Stop all dev services

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

# Dev environment prefix
DEV_PREFIX="dev"

echo ""
echo -e "${MAGENTA}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${MAGENTA}║                                                        ║${NC}"
echo -e "${MAGENTA}║     ML Platform - Development Environment              ║${NC}"
echo -e "${MAGENTA}║     Testing MLflow 3.x Upgrade                         ║${NC}"
echo -e "${MAGENTA}║                                                        ║${NC}"
echo -e "${MAGENTA}╚════════════════════════════════════════════════════════╝${NC}"
echo ""

# Handle stop command
if [ "$1" = "stop" ]; then
    echo -e "${YELLOW}Stopping all dev services...${NC}"
    echo ""

    # Stop MLflow dev
    echo "  Stopping MLflow dev..."
    cd mlflow-server && sg docker -c "docker compose -f docker-compose.dev.yml down" 2>/dev/null || true
    cd "$SCRIPT_DIR"

    # Stop Ray dev
    echo "  Stopping Ray dev..."
    cd ray_compute && sg docker -c "docker compose -f docker-compose.dev.yml down" 2>/dev/null || true
    cd "$SCRIPT_DIR"

    # Stop infra dev
    echo "  Stopping dev infrastructure..."
    sg docker -c "docker compose -f docker-compose.dev.yml down" 2>/dev/null || true

    echo ""
    echo -e "${GREEN}✓ All dev services stopped${NC}"
    exit 0
fi

# Function to wait for service health
wait_for_health() {
    local service=$1
    local max_wait=${2:-60}
    local wait_time=0

    echo -n "  Waiting for $service to be healthy"
    while [ $wait_time -lt $max_wait ]; do
        local status=$(sg docker -c "docker inspect --format='{{.State.Health.Status}}' $service" 2>/dev/null || echo "starting")
        if [ "$status" = "healthy" ]; then
            echo -e " ${GREEN}✓${NC}"
            return 0
        elif [ "$status" = "unhealthy" ]; then
            echo -e " ${RED}✗${NC}"
            return 1
        fi
        echo -n "."
        sleep 2
        wait_time=$((wait_time + 2))
    done
    echo -e " ${YELLOW}⚠ (timeout)${NC}"
    return 0  # Continue anyway
}

# Function to check if container is running
is_running() {
    sg docker -c "docker ps --format '{{.Names}}' | grep -q '^$1$'" 2>/dev/null
}

# ═══════════════════════════════════════════════════════════════════
# Phase 1: Dev Infrastructure (Redis, PostgreSQL for dev only)
# ═══════════════════════════════════════════════════════════════════
start_dev_infra() {
    echo -e "${CYAN}━━━ Phase 1: Dev Infrastructure ━━━${NC}"

    # Check if dev infra compose exists, if not create minimal one
    if [ ! -f "docker-compose.dev.yml" ]; then
        echo "  Creating dev infrastructure compose file..."
        cat > docker-compose.dev.yml << 'EOF'
# Development Infrastructure
# Separate from production - uses different ports

services:
  # Dev Redis (port 6380)
  dev-redis:
    image: redis:7-alpine
    container_name: dev-redis
    ports:
      - "6380:6379"
    command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 3
    networks:
      - dev-network

networks:
  dev-network:
    name: dev-network
    driver: bridge
EOF
    fi

    sg docker -c "docker compose -f docker-compose.dev.yml up -d"
    wait_for_health "dev-redis" 30
    echo -e "${GREEN}✓ Dev infrastructure ready${NC}"
    echo ""
}

# ═══════════════════════════════════════════════════════════════════
# Phase 2: MLflow 3.x Dev Server
# ═══════════════════════════════════════════════════════════════════
start_mlflow_dev() {
    echo -e "${CYAN}━━━ Phase 2: MLflow 3.x Development Server ━━━${NC}"

    if [ ! -f "mlflow-server/docker-compose.dev.yml" ]; then
        echo -e "${RED}✗ MLflow dev compose not found${NC}"
        echo "  Run: Create mlflow-server/docker-compose.dev.yml first"
        return 1
    fi

    cd mlflow-server
    echo "  Building MLflow 3.x container..."
    sg docker -c "docker compose -f docker-compose.dev.yml build" 2>&1 | grep -E "^(\[|\s+✔|Building|Successfully)" || true

    echo "  Starting MLflow dev services..."
    sg docker -c "docker compose -f docker-compose.dev.yml up -d"

    wait_for_health "mlflow-dev-postgres" 45
    wait_for_health "mlflow-dev-server" 60

    cd "$SCRIPT_DIR"
    echo -e "${GREEN}✓ MLflow 3.x dev server ready on port 5001${NC}"
    echo ""
}

# ═══════════════════════════════════════════════════════════════════
# Phase 3: Ray Dev Server
# ═══════════════════════════════════════════════════════════════════
start_ray_dev() {
    echo -e "${CYAN}━━━ Phase 3: Ray Development Server ━━━${NC}"

    # Check if Ray dev compose exists
    if [ ! -f "ray_compute/docker-compose.dev.yml" ]; then
        echo "  Creating Ray dev compose file..."
        create_ray_dev_compose
    fi

    cd ray_compute
    echo "  Starting Ray dev services..."
    sg docker -c "docker compose -f docker-compose.dev.yml up -d" 2>&1 || {
        echo -e "${YELLOW}⚠ Ray dev startup had warnings (may still work)${NC}"
    }

    wait_for_health "ray-dev-head" 60 || true

    cd "$SCRIPT_DIR"
    echo -e "${GREEN}✓ Ray dev server ready on port 8266${NC}"
    echo ""
}

create_ray_dev_compose() {
    cat > ray_compute/docker-compose.dev.yml << 'EOF'
# Ray Development Environment
# For testing with MLflow 3.x integration

services:
  ray-dev-head:
    build:
      context: .
      dockerfile: Dockerfile.ray-server
    container_name: ray-dev-head
    environment:
      - RAY_HEAD_ADDRESS=auto
      - RAY_DASHBOARD_HOST=0.0.0.0
      - RAY_DASHBOARD_PORT=8266
      - MLFLOW_TRACKING_URI=http://mlflow-dev-server:5001
    ports:
      - "8266:8265"   # Ray Dashboard (different from prod 8265)
      - "6380:6379"   # Ray GCS (if needed)
    volumes:
      - ray-dev-data:/tmp/ray
      - ./pipelines:/app/pipelines:ro
    healthcheck:
      test: ["CMD", "ray", "status"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    networks:
      - dev-network
      - mlflow-dev-network

volumes:
  ray-dev-data:
    name: ray-dev-data

networks:
  dev-network:
    external: true
  mlflow-dev-network:
    external: true
EOF
}

# ═══════════════════════════════════════════════════════════════════
# Integration Tests
# ═══════════════════════════════════════════════════════════════════
run_integration_tests() {
    echo -e "${CYAN}━━━ Integration Tests ━━━${NC}"

    # Test MLflow 3.x
    echo "  Testing MLflow 3.x API..."
    if curl -sf http://localhost:5001/health > /dev/null 2>&1; then
        echo -e "    MLflow Health: ${GREEN}✓${NC}"

        # Test experiment creation
        RESULT=$(curl -sf -X POST "http://localhost:5001/api/2.0/mlflow/experiments/create" \
            -H "Content-Type: application/json" \
            -d '{"name": "integration-test-'$(date +%s)'"}' 2>&1) || true

        if echo "$RESULT" | grep -q "experiment_id"; then
            echo -e "    Create Experiment: ${GREEN}✓${NC}"
        else
            echo -e "    Create Experiment: ${YELLOW}⚠${NC}"
        fi
    else
        echo -e "    MLflow Health: ${RED}✗${NC}"
    fi

    # Test Ray (if running)
    echo "  Testing Ray Dashboard..."
    if curl -sf http://localhost:8266 > /dev/null 2>&1; then
        echo -e "    Ray Dashboard: ${GREEN}✓${NC}"
    else
        echo -e "    Ray Dashboard: ${YELLOW}⚠ (not running or not ready)${NC}"
    fi

    echo ""
}

# ═══════════════════════════════════════════════════════════════════
# Run Unit/Integration Tests in Container
# ═══════════════════════════════════════════════════════════════════
run_container_tests() {
    echo -e "${CYAN}━━━ Container Tests ━━━${NC}"

    local test_args="${1:-/workspace/tests}"

    # Build test container if needed
    echo "  Building test container..."
    sg docker -c "docker compose -f docker-compose.dev.yml build dev-test" 2>&1 | grep -E "^(\[|\s+✔|Building|built)" || true

    # Run tests
    echo "  Running tests: $test_args"
    echo ""
    sg docker -c "docker compose -f docker-compose.dev.yml --profile test run --rm dev-test $test_args -v -s" || {
        echo -e "${RED}✗ Some tests failed${NC}"
        return 1
    }

    echo ""
    echo -e "${GREEN}✓ All tests passed${NC}"
}

# ═══════════════════════════════════════════════════════════════════
# Show Status
# ═══════════════════════════════════════════════════════════════════
show_status() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}✓ Dev environment startup complete!${NC}"
    echo ""

    echo -e "${CYAN}Dev Container Status:${NC}"
    sg docker -c "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'" | grep -E "NAME|dev" || echo "  No dev containers found"
    echo ""

    echo -e "${CYAN}Dev Access Points:${NC}"
    echo "  • MLflow 3.x Dev:   http://localhost:5001"
    echo "  • Ray Dev:          http://localhost:8266"
    echo "  • Dev Redis:        localhost:6380"
    echo "  • Dev PostgreSQL:   localhost:5434"
    echo ""

    echo -e "${CYAN}Production (unchanged):${NC}"
    echo "  • MLflow Prod:      http://localhost:5000 (v2.17.2)"
    echo "  • Ray Prod:         http://localhost:8265"
    echo "  • Grafana:          http://localhost/grafana/"
    echo ""

    echo -e "${CYAN}Test Commands:${NC}"
    echo "  # Run all tests in container:"
    echo "  ./start_all_dev.sh unittest"
    echo ""
    echo "  # Run specific test:"
    echo "  ./start_all_dev.sh unittest /workspace/tests/unit/test_copilot_suggestions.py"
    echo ""
    echo "  # Run MLflow upgrade tests:"
    echo "  ./mlflow-server/scripts/test-mlflow-upgrade.sh"
    echo ""
    echo "  # Compare versions:"
    echo "  curl -s http://localhost:5001/health  # Dev (3.x)"
    echo "  curl -s http://localhost:5000/health  # Prod (2.x)"
    echo ""

    echo -e "${YELLOW}To stop dev environment:${NC}"
    echo "  ./start_all_dev.sh stop"
    echo ""
}

# ═══════════════════════════════════════════════════════════════════
# Main Execution
# ═══════════════════════════════════════════════════════════════════

case "${1:-all}" in
    mlflow)
        start_mlflow_dev
        run_integration_tests
        show_status
        ;;
    ray)
        start_ray_dev
        run_integration_tests
        show_status
        ;;
    infra)
        start_dev_infra
        ;;
    test)
        run_integration_tests
        ;;
    unittest)
        # Run container-based unit/integration tests
        shift  # Remove 'unittest' from args
        start_dev_infra
        run_container_tests "${@:-/workspace/tests}"
        ;;
    all)
        start_dev_infra
        start_mlflow_dev
        # start_ray_dev  # Uncomment when ready to test Ray
        run_integration_tests
        show_status
        ;;
    *)
        echo "Usage: $0 [all|mlflow|ray|infra|test|unittest|stop]"
        echo ""
        echo "Commands:"
        echo "  all       - Start all dev services (default)"
        echo "  mlflow    - Start only MLflow dev"
        echo "  ray       - Start only Ray dev"
        echo "  infra     - Start only dev infrastructure"
        echo "  test      - Run integration tests (curl-based)"
        echo "  unittest  - Run unit tests in container"
        echo "  stop      - Stop all dev services"
        echo ""
        echo "Examples:"
        echo "  $0                                    # Start all"
        echo "  $0 unittest                           # Run all tests"
        echo "  $0 unittest /workspace/tests/unit    # Run unit tests only"
        echo "  $0 unittest -k copilot               # Run tests matching 'copilot'"
        exit 1
        ;;
esac
