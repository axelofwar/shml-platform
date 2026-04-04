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

echo -e "${CYAN}━━━ Phase 0: Qwen3.5 Coding Server (llama.cpp host process) ━━━${NC}"
LLAMA_PID_FILE="${SCRIPT_DIR}/../../inference/llama-cpp/qwen35-server.pid"
if [ -f "$LLAMA_PID_FILE" ]; then
    LLAMA_PID=$(cat "$LLAMA_PID_FILE")
    if kill -0 "$LLAMA_PID" 2>/dev/null; then
        echo "Stopping llama.cpp server (PID ${LLAMA_PID})..."
        kill "$LLAMA_PID" 2>/dev/null && sleep 2
        # Force-kill if still running after 5s
        if kill -0 "$LLAMA_PID" 2>/dev/null; then
            kill -9 "$LLAMA_PID" 2>/dev/null || true
        fi
        echo -e "${GREEN}✓ Qwen3.5 coding server stopped${NC}"
    else
        echo "llama.cpp server not running (stale PID file)"
    fi
    rm -f "$LLAMA_PID_FILE"
else
    echo "llama.cpp server not running"
fi
echo ""

# Stop services in reverse order
echo -e "${CYAN}━━━ Phase 1: GPU Monitoring ━━━${NC}"
if sudo docker compose -f monitoring/dcgm-exporter/deploy/compose/docker-compose.yml ps | grep -q "dcgm-exporter"; then
    sudo docker compose -f monitoring/dcgm-exporter/deploy/compose/docker-compose.yml down
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

echo -e "${CYAN}━━━ Phase 4: Authentication Services ━━━${NC}"
sudo docker compose -f deploy/compose/docker-compose.infra.yml stop oauth2-proxy fusionauth 2>&1 | grep -v "WARNING:" || true
echo -e "${GREEN}✓ Auth services stopped${NC}"
echo ""

echo -e "${CYAN}━━━ Phase 5: Monitoring & Infrastructure ━━━${NC}"
sudo docker compose -f deploy/compose/docker-compose.infra.yml stop unified-grafana global-prometheus 2>&1 | grep -v "WARNING:" || true
sudo docker compose -f deploy/compose/docker-compose.infra.yml stop cadvisor node-exporter 2>&1 | grep -v "WARNING:" || true
sudo docker compose -f deploy/compose/docker-compose.infra.yml stop traefik redis postgres 2>&1 | grep -v "WARNING:" || true
echo -e "${GREEN}✓ Infrastructure stopped${NC}"
echo ""

echo -e "${CYAN}━━━ Phase 6: Tailscale Funnel ━━━${NC}"
if command -v tailscale &>/dev/null; then
    if [ -f "$SCRIPT_DIR/scripts/manage_funnel.sh" ]; then
        "$SCRIPT_DIR/scripts/manage_funnel.sh" stop || true
    else
        tailscale funnel --https=443 off 2>/dev/null || true
    fi
    echo -e "${GREEN}✓ Tailscale Funnel stopped${NC}"
else
    echo "Tailscale not installed - skipping"
fi
echo ""

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✓ All services stopped${NC}"
echo ""
echo "To remove containers: sudo docker compose down"
echo "To restart:           bash start_all_safe.sh"
echo ""
