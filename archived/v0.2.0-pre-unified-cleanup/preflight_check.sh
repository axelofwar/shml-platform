#!/bin/bash
# Pre-flight checklist - Verify all configuration before starting platform

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}═══════════════════════════════════════════${NC}"
echo -e "${BLUE}  ML Platform Pre-Flight Checklist${NC}"
echo -e "${BLUE}═══════════════════════════════════════════${NC}"
echo ""

ERRORS=0
WARNINGS=0

# Check function
check_pass() {
    echo -e "${GREEN}✓${NC} $1"
}

check_fail() {
    echo -e "${RED}✗${NC} $1"
    ((ERRORS++))
}

check_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
    ((WARNINGS++))
}

echo -e "${BLUE}[1/8] Docker Configuration${NC}"
if docker --version &>/dev/null; then
    check_pass "Docker installed: $(docker --version | cut -d' ' -f3)"
else
    check_fail "Docker not installed"
fi

if docker compose version &>/dev/null; then
    check_pass "Docker Compose installed: $(docker compose version | cut -d' ' -f4)"
else
    check_fail "Docker Compose not installed"
fi

if groups | grep -q docker; then
    check_pass "User in docker group"
else
    check_warn "User not in docker group (may need sudo)"
fi

echo ""
echo -e "${BLUE}[2/8] NVIDIA GPU Configuration${NC}"
if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
    GPU_COUNT=$(nvidia-smi --query-gpu=count --format=csv,noheader 2>/dev/null | head -1)
    check_pass "NVIDIA drivers installed (${GPU_COUNT} GPUs detected)"
    nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader 2>/dev/null | while read line; do
        echo "    → $line"
    done
else
    check_fail "NVIDIA drivers not found"
fi

# Only test GPU in Docker if we can run docker without sudo
if docker ps &>/dev/null 2>&1; then
    if docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu20.04 nvidia-smi &>/dev/null 2>&1; then
        check_pass "GPU accessible in Docker"
    else
        check_fail "GPU not accessible in Docker"
    fi
else
    check_warn "Cannot test GPU in Docker (need sudo access)"
fi

echo ""
echo -e "${BLUE}[3/8] Network Configuration${NC}"
if docker network ls | grep -q ml-platform; then
    check_pass "Docker network 'ml-platform' exists"
else
    check_warn "Docker network 'ml-platform' not found (will be created)"
fi

LOCAL_IP=$(hostname -I | awk '{print $1}')
check_pass "Local IP: ${LOCAL_IP}"

if tailscale status &>/dev/null 2>&1; then
    TAILSCALE_IP=$(tailscale ip -4)
    check_pass "Tailscale configured: ${TAILSCALE_IP}"
else
    check_warn "Tailscale not configured (optional)"
fi

echo ""
echo -e "${BLUE}[4/8] Environment Files${NC}"
if [ -f .env ]; then
    check_pass ".env exists"
else
    check_fail ".env not found"
fi

if [ -f ray_compute/.env ]; then
    check_pass "ray_compute/.env exists"
else
    check_fail "ray_compute/.env not found"
fi

if [ -f mlflow-server/.env ]; then
    check_pass "mlflow-server/.env exists"
else
    check_fail "mlflow-server/.env not found"
fi

echo ""
echo -e "${BLUE}[5/8] Secrets Configuration${NC}"
if grep -q "^AUTHENTIK_SECRET_KEY=.\{40,\}" .env; then
    check_pass "Authentik secret configured"
else
    check_fail "Authentik secret not configured"
fi

if grep -q "^GRAFANA_ADMIN_PASSWORD=.\{12,\}" .env; then
    check_pass "Grafana password configured"
else
    check_fail "Grafana password not configured"
fi

if grep -q "^POSTGRES_PASSWORD=.\{12,\}" ray_compute/.env; then
    check_pass "Ray database password configured"
else
    check_fail "Ray database password not configured"
fi

if grep -q "^DB_PASSWORD=.\{12,\}" mlflow-server/.env; then
    check_pass "MLflow database password configured"
else
    check_fail "MLflow database password not configured"
fi

# Check for placeholder values
PLACEHOLDERS=$(grep -r "<generate\|<from\|XXX\|TODO\|NOT_CONFIGURED" .env ray_compute/.env mlflow-server/.env 2>/dev/null | grep -v "AUTHENTIK_CLIENT_SECRET" | wc -l)
if [ "$PLACEHOLDERS" -eq 0 ]; then
    check_pass "No placeholder values found"
else
    check_warn "${PLACEHOLDERS} placeholder value(s) found (may need manual configuration)"
fi

echo ""
echo -e "${BLUE}[6/8] Port Availability${NC}"
PORTS=(80 443 8090 5432 5433 6379)
for port in "${PORTS[@]}"; do
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
        check_warn "Port $port already in use"
    else
        check_pass "Port $port available"
    fi
done

echo ""
echo -e "${BLUE}[7/8] System Resources${NC}"
TOTAL_MEM=$(free -g | awk '/^Mem:/{print $2}')
AVAIL_MEM=$(free -g | awk '/^Mem:/{print $7}')

if [ "$TOTAL_MEM" -ge 16 ]; then
    check_pass "Total RAM: ${TOTAL_MEM}GB"
else
    check_warn "Total RAM: ${TOTAL_MEM}GB (16GB+ recommended)"
fi

if [ "$AVAIL_MEM" -ge 8 ]; then
    check_pass "Available RAM: ${AVAIL_MEM}GB"
else
    check_warn "Available RAM: ${AVAIL_MEM}GB (8GB+ recommended)"
fi

DISK_AVAIL=$(df -h / | awk 'NR==2 {print $4}')
check_pass "Available disk space: ${DISK_AVAIL}"

echo ""
echo -e "${BLUE}[8/8] Docker Compose Files${NC}"
if [ -f docker-compose.yml ]; then
    check_pass "Main docker-compose.yml exists"
else
    check_fail "Main docker-compose.yml not found"
fi

if [ -f ray_compute/docker-compose.yml ]; then
    check_pass "Ray docker-compose.yml exists"
else
    check_fail "Ray docker-compose.yml not found"
fi

if [ -f mlflow-server/docker-compose.yml ]; then
    check_pass "MLflow docker-compose.yml exists"
else
    check_fail "MLflow docker-compose.yml not found"
fi

# Validate docker-compose files
for compose_file in docker-compose.yml ray_compute/docker-compose.yml mlflow-server/docker-compose.yml; do
    if docker compose -f "$compose_file" config >/dev/null 2>&1; then
        check_pass "$(basename $(dirname $compose_file))/$(basename $compose_file) valid"
    else
        check_fail "$(basename $(dirname $compose_file))/$(basename $compose_file) has syntax errors"
    fi
done

echo ""
echo -e "${BLUE}═══════════════════════════════════════════${NC}"
echo -e "${BLUE}  Summary${NC}"
echo -e "${BLUE}═══════════════════════════════════════════${NC}"
echo ""

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✓ All checks passed! Ready to start platform.${NC}"
    echo ""
    echo "Next step:"
    echo "  sudo ./start_all_safe.sh"
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠ ${WARNINGS} warning(s) found, but can proceed.${NC}"
    echo ""
    echo "Review warnings above, then run:"
    echo "  sudo ./start_all_safe.sh"
    exit 0
else
    echo -e "${RED}✗ ${ERRORS} error(s) and ${WARNINGS} warning(s) found.${NC}"
    echo ""
    echo "Fix errors before starting platform."
    echo "Run this checklist again: ./preflight_check.sh"
    exit 1
fi
