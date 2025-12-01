#!/bin/bash
# ML Platform - Unified Stop Script
# Stops all services in reverse order and optionally creates backup

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo ""
echo -e "${BLUE}=========================================="
echo "ML Platform - Stopping All Services"
echo "==========================================${NC}"
echo ""

# Optional backup before stopping
if [ "$1" = "--backup" ]; then
    echo "📦 Creating backup before shutdown..."
    if [ -f "./scripts/backup_platform.sh" ]; then
        ./scripts/backup_platform.sh
        echo ""
    else
        echo -e "${YELLOW}⚠ Backup script not found - skipping backup${NC}"
        echo ""
    fi
fi

# Stop services in reverse order
echo -e "${CYAN}━━━ Phase 1: GPU Monitoring ━━━${NC}"
if sudo docker compose -f monitoring/dcgm-exporter/docker-compose.yml ps | grep -q "dcgm-exporter"; then
    sudo docker compose -f monitoring/dcgm-exporter/docker-compose.yml down
    echo -e "${GREEN}✓ GPU monitoring stopped${NC}"
else
    echo "No GPU monitoring running"
fi
echo ""

echo -e "${CYAN}━━━ Phase 2: Ray Compute ━━━${NC}"
sudo docker compose stop ray-compute-api ray-head ray-prometheus 2>&1 | grep -v "WARNING:" || true
echo -e "${GREEN}✓ Ray services stopped${NC}"
echo ""

echo -e "${CYAN}━━━ Phase 3: MLflow Services ━━━${NC}"
sudo docker compose stop mlflow-api mlflow-nginx mlflow-server mlflow-prometheus 2>&1 | grep -v "WARNING:" || true
echo -e "${GREEN}✓ MLflow services stopped${NC}"
echo ""

echo -e "${CYAN}━━━ Phase 4: Authentik ━━━${NC}"
sudo docker compose -f docker-compose.infra.yml stop authentik-worker authentik-server 2>&1 | grep -v "WARNING:" || true
echo -e "${GREEN}✓ Authentik stopped${NC}"
echo ""

echo -e "${CYAN}━━━ Phase 5: Monitoring & Infrastructure ━━━${NC}"
sudo docker compose -f docker-compose.infra.yml stop unified-grafana global-prometheus 2>&1 | grep -v "WARNING:" || true
sudo docker compose -f docker-compose.infra.yml stop ml-platform-cadvisor ml-platform-node-exporter 2>&1 | grep -v "WARNING:" || true
sudo docker compose -f docker-compose.infra.yml stop ml-platform-traefik ml-platform-redis shared-postgres 2>&1 | grep -v "WARNING:" || true
sudo docker compose -f docker-compose.infra.yml stop authentik-redis authentik-postgres 2>&1 | grep -v "WARNING:" || true
echo -e "${GREEN}✓ Infrastructure stopped${NC}"
echo ""

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✓ All services stopped${NC}"
echo ""
echo "To remove containers: sudo docker compose down"
echo "To restart:           bash start_all_safe.sh"
echo ""
