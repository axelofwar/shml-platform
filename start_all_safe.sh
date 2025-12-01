#!/bin/bash
# ML Platform - Safe Startup Script (Unified Approach)
# Starts services in phases with health monitoring

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo ""
echo -e "${BLUE}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                                                        ║${NC}"
echo -e "${BLUE}║         ML Platform - Safe Startup                     ║${NC}"
echo -e "${BLUE}║         Unified Docker Compose Approach                ║${NC}"
echo -e "${BLUE}║                                                        ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo -e "${RED}⚠️  Do not run this script as root (sudo)${NC}"
    echo "The script will request sudo when needed."
    exit 1
fi

# Function to wait for service health
wait_for_health() {
    local service=$1
    local max_wait=$2
    local wait_time=0
    
    echo -n "  Waiting for $service to be healthy"
    while [ $wait_time -lt $max_wait ]; do
        local status=$(sudo docker inspect --format='{{.State.Health.Status}}' "$service" 2>/dev/null || echo "starting")
        if [ "$status" = "healthy" ]; then
            echo -e " ${GREEN}✓${NC}"
            return 0
        fi
        echo -n "."
        sleep 2
        wait_time=$((wait_time + 2))
    done
    echo -e " ${YELLOW}⚠${NC}"
    return 1
}

# Phase 1: Infrastructure
echo -e "${CYAN}━━━ Phase 1: Infrastructure ━━━${NC}"
echo "Starting: Traefik, PostgreSQL, Redis, Monitoring..."
sudo docker compose -f docker-compose.infra.yml up -d \
    ml-platform-traefik shared-postgres ml-platform-redis \
    ml-platform-node-exporter ml-platform-cadvisor

wait_for_health "shared-postgres" 60
wait_for_health "ml-platform-traefik" 30
echo -e "${GREEN}✓ Infrastructure ready${NC}"
echo ""

# Phase 2: Monitoring
echo -e "${CYAN}━━━ Phase 2: Monitoring ━━━${NC}"
echo "Starting: Global Prometheus, Unified Grafana..."
sudo docker compose -f docker-compose.infra.yml up -d \
    global-prometheus unified-grafana

wait_for_health "global-prometheus" 30
wait_for_health "unified-grafana" 45
echo -e "${GREEN}✓ Monitoring ready${NC}"
echo ""

# Phase 3: Authentik (OAuth/SSO)
echo -e "${CYAN}━━━ Phase 3: Authentik ━━━${NC}"
echo "Starting: Authentik server and worker..."
sudo docker compose -f docker-compose.infra.yml up -d \
    authentik-postgres authentik-redis authentik-server authentik-worker

wait_for_health "authentik-postgres" 45
echo -e "${GREEN}✓ Authentik services starting${NC}"
echo ""

# Phase 4: MLflow Services
echo -e "${CYAN}━━━ Phase 4: MLflow Services ━━━${NC}"
echo "Starting: MLflow server, API, Prometheus..."
sudo docker compose up -d mlflow-server mlflow-prometheus mlflow-nginx mlflow-api

wait_for_health "mlflow-server" 60
wait_for_health "mlflow-nginx" 30
echo -e "${GREEN}✓ MLflow services ready${NC}"
echo ""

# Phase 5: Ray Compute
echo -e "${CYAN}━━━ Phase 5: Ray Compute ━━━${NC}"
echo "Starting: Ray head, API, Prometheus..."
sudo docker compose up -d ray-head ray-prometheus ray-compute-api

wait_for_health "ray-head" 60
echo -e "${GREEN}✓ Ray compute ready${NC}"
echo ""

# Phase 6: GPU Monitoring (if available)
echo -e "${CYAN}━━━ Phase 6: GPU Monitoring ━━━${NC}"
if sudo docker compose -f monitoring/dcgm-exporter/docker-compose.yml config >/dev/null 2>&1; then
    echo "Starting: DCGM Exporter..."
    sudo docker compose -f monitoring/dcgm-exporter/docker-compose.yml up -d
    echo -e "${GREEN}✓ GPU monitoring started${NC}"
else
    echo -e "${YELLOW}⚠ DCGM configuration not found - skipping GPU monitoring${NC}"
fi
echo ""

# Final Status Check
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✓ Platform startup complete!${NC}"
echo ""
echo "Service Status:"
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAME|traefik|postgres|mlflow|ray|grafana|prometheus|authentik"
echo ""
echo -e "${CYAN}Access Points:${NC}"
echo "  • MLflow UI:       http://localhost/mlflow/"
echo "  • Ray Dashboard:   http://localhost/ray/"
echo "  • Grafana:         http://localhost/grafana/"
echo "  • Authentik:       http://localhost:9000/"
echo "  • Traefik:         http://localhost:8090/"
echo ""
echo -e "${YELLOW}Note: Some services may take 2-3 minutes to fully initialize.${NC}"
echo "      Monitor with: sudo docker ps"
echo "      View logs:    sudo docker logs <container-name>"
echo ""
