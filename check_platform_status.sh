#!/bin/bash
# ML Platform - Unified Status Check
# Checks health of all platform services

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo ""
echo -e "${BLUE}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║         ML Platform - Status Check                     ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════╝${NC}"
echo ""

# Function to check service health
check_service() {
    local service=$1
    local status=$(sudo docker inspect --format='{{.State.Status}}' "$service" 2>/dev/null || echo "not found")
    local health=$(sudo docker inspect --format='{{.State.Health.Status}}' "$service" 2>/dev/null || echo "no healthcheck")

    if [ "$status" = "running" ]; then
        if [ "$health" = "healthy" ]; then
            echo -e "${GREEN}✓${NC} $service: running (healthy)"
        elif [ "$health" = "no healthcheck" ]; then
            echo -e "${GREEN}✓${NC} $service: running"
        else
            echo -e "${YELLOW}⚠${NC} $service: running ($health)"
        fi
    elif [ "$status" = "not found" ]; then
        echo -e "${RED}✗${NC} $service: not found"
    else
        echo -e "${RED}✗${NC} $service: $status"
    fi
}

# Infrastructure Services
echo -e "${CYAN}━━━ Infrastructure Services ━━━${NC}"
check_service "ml-platform-traefik"
check_service "shared-postgres"
check_service "ml-platform-redis"
check_service "ml-platform-node-exporter"
check_service "ml-platform-cadvisor"
echo ""

# Monitoring Services
echo -e "${CYAN}━━━ Monitoring Services ━━━${NC}"
check_service "global-prometheus"
check_service "unified-grafana"
check_service "dcgm-exporter"
echo ""

# Authentik Services
echo -e "${CYAN}━━━ Authentik (OAuth/SSO) ━━━${NC}"
check_service "authentik-postgres"
check_service "authentik-redis"
check_service "authentik-server"
check_service "authentik-worker"
echo ""

# MLflow Services
echo -e "${CYAN}━━━ MLflow Services ━━━${NC}"
check_service "mlflow-server"
check_service "mlflow-nginx"
check_service "mlflow-api"
check_service "mlflow-prometheus"
echo ""

# Ray Services
echo -e "${CYAN}━━━ Ray Compute Services ━━━${NC}"
check_service "ray-head"
check_service "ray-compute-api"
check_service "ray-prometheus"
echo ""

# Summary
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
RUNNING=$(sudo docker ps --filter "status=running" | grep -c "ml-platform\|mlflow\|ray\|authentik\|grafana\|prometheus" || echo "0")
TOTAL=19
echo -e "Running Services: ${GREEN}$RUNNING${NC}/$TOTAL"
echo ""

# Access Points
echo -e "${CYAN}Access Points:${NC}"
TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "localhost")
echo "  • MLflow UI:       http://${TAILSCALE_IP}/mlflow/"
echo "  • Ray Dashboard:   http://${TAILSCALE_IP}/ray/"
echo "  • Grafana:         http://${TAILSCALE_IP}/grafana/"
echo "  • Authentik:       http://${TAILSCALE_IP}:9000/"
echo "  • Traefik:         http://${TAILSCALE_IP}:8090/"
echo ""
