#!/bin/bash
# ML Platform - Stop Dev Services Only
# Safely stops all development containers without affecting production
#
# Usage:
#   ./stop_dev.sh           # Stop all dev services
#   ./stop_dev.sh --volumes # Stop and remove dev volumes
#   ./stop_dev.sh --status  # Show current dev container status

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

# Dev container patterns
DEV_CONTAINERS=(
    "mlflow-dev-server"
    "mlflow-dev-postgres"
    "dev-redis"
    "ray-dev-head"
    "ray-dev-worker"
)

# Dev volumes
DEV_VOLUMES=(
    "mlflow-dev-postgres-data"
    "mlflow-dev-artifacts"
    "mlflow-dev-logs"
    "ray-dev-data"
)

# Dev networks
DEV_NETWORKS=(
    "mlflow-dev-network"
    "dev-network"
)

echo ""
echo -e "${MAGENTA}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${MAGENTA}║                                                        ║${NC}"
echo -e "${MAGENTA}║     ML Platform - Stop Dev Services                    ║${NC}"
echo -e "${MAGENTA}║     (Production services will NOT be affected)         ║${NC}"
echo -e "${MAGENTA}║                                                        ║${NC}"
echo -e "${MAGENTA}╚════════════════════════════════════════════════════════╝${NC}"
echo ""

# Handle --status flag
if [ "$1" = "--status" ]; then
    echo -e "${CYAN}Current Dev Container Status:${NC}"
    echo ""

    found_any=false
    for container in "${DEV_CONTAINERS[@]}"; do
        status=$(sg docker -c "docker inspect --format='{{.State.Status}} ({{.State.Health.Status}})' $container" 2>/dev/null || echo "not running")
        if [ "$status" != "not running" ]; then
            echo -e "  ${GREEN}●${NC} $container: $status"
            found_any=true
        fi
    done

    if [ "$found_any" = false ]; then
        echo -e "  ${YELLOW}No dev containers running${NC}"
    fi

    echo ""
    echo -e "${CYAN}Dev Networks:${NC}"
    for network in "${DEV_NETWORKS[@]}"; do
        if sg docker -c "docker network inspect $network" > /dev/null 2>&1; then
            echo -e "  ${GREEN}●${NC} $network"
        fi
    done

    echo ""
    echo -e "${CYAN}Dev Volumes:${NC}"
    for volume in "${DEV_VOLUMES[@]}"; do
        if sg docker -c "docker volume inspect $volume" > /dev/null 2>&1; then
            size=$(sg docker -c "docker system df -v 2>/dev/null" | grep "$volume" | awk '{print $4}' || echo "unknown")
            echo -e "  ${GREEN}●${NC} $volume ($size)"
        fi
    done

    exit 0
fi

# Show what will be stopped
echo -e "${CYAN}The following will be stopped:${NC}"
echo ""

running_containers=()
for container in "${DEV_CONTAINERS[@]}"; do
    if sg docker -c "docker ps -q -f name=$container" 2>/dev/null | grep -q .; then
        running_containers+=("$container")
        echo -e "  ${GREEN}●${NC} $container"
    fi
done

if [ ${#running_containers[@]} -eq 0 ]; then
    echo -e "  ${YELLOW}No dev containers currently running${NC}"
fi

echo ""

# Confirm production safety
echo -e "${BLUE}Production containers (will NOT be affected):${NC}"
prod_containers=$(sg docker -c "docker ps --format '{{.Names}}'" | grep -v "dev" | grep -E "mlflow|ray|traefik|postgres|redis|grafana|prometheus|fusionauth" || true)
if [ -n "$prod_containers" ]; then
    echo "$prod_containers" | while read container; do
        echo -e "  ${BLUE}●${NC} $container"
    done
else
    echo -e "  ${YELLOW}No production containers detected${NC}"
fi
echo ""

# Stop dev services
echo -e "${YELLOW}Stopping dev services...${NC}"
echo ""

# Method 1: Use docker-compose if available
if [ -f "mlflow-server/docker-compose.dev.yml" ]; then
    echo "  Stopping MLflow dev..."
    cd mlflow-server
    sg docker -c "docker compose -f docker-compose.dev.yml down" 2>/dev/null || true
    cd "$SCRIPT_DIR"
fi

if [ -f "ray_compute/docker-compose.dev.yml" ]; then
    echo "  Stopping Ray dev..."
    cd ray_compute
    sg docker -c "docker compose -f docker-compose.dev.yml down" 2>/dev/null || true
    cd "$SCRIPT_DIR"
fi

if [ -f "docker-compose.dev.yml" ]; then
    echo "  Stopping dev infrastructure..."
    sg docker -c "docker compose -f docker-compose.dev.yml down" 2>/dev/null || true
fi

# Method 2: Direct container stop (backup)
echo ""
echo "  Ensuring all dev containers stopped..."
for container in "${DEV_CONTAINERS[@]}"; do
    if sg docker -c "docker ps -q -f name=$container" 2>/dev/null | grep -q .; then
        echo "    Stopping $container..."
        sg docker -c "docker stop $container" 2>/dev/null || true
        sg docker -c "docker rm $container" 2>/dev/null || true
    fi
done

# Handle --volumes flag
if [ "$1" = "--volumes" ]; then
    echo ""
    echo -e "${YELLOW}Removing dev volumes...${NC}"
    for volume in "${DEV_VOLUMES[@]}"; do
        if sg docker -c "docker volume inspect $volume" > /dev/null 2>&1; then
            echo "  Removing $volume..."
            sg docker -c "docker volume rm $volume" 2>/dev/null || true
        fi
    done
fi

# Clean up networks
echo ""
echo "  Cleaning up dev networks..."
for network in "${DEV_NETWORKS[@]}"; do
    if sg docker -c "docker network inspect $network" > /dev/null 2>&1; then
        sg docker -c "docker network rm $network" 2>/dev/null || true
    fi
done

# Final verification
echo ""
echo -e "${CYAN}━━━ Final Status ━━━${NC}"
echo ""

echo -e "${GREEN}Dev containers stopped:${NC}"
remaining=0
for container in "${DEV_CONTAINERS[@]}"; do
    if sg docker -c "docker ps -q -f name=$container" 2>/dev/null | grep -q .; then
        echo -e "  ${RED}✗${NC} $container still running"
        ((remaining++))
    fi
done

if [ $remaining -eq 0 ]; then
    echo -e "  ${GREEN}✓${NC} All dev containers stopped"
fi

echo ""
echo -e "${BLUE}Production containers (should still be running):${NC}"
prod_after=$(sg docker -c "docker ps --format '{{.Names}}'" | grep -v "dev" | grep -E "mlflow-server|ray-head|shared-postgres|ml-platform" | head -5 || true)
if [ -n "$prod_after" ]; then
    echo "$prod_after" | while read container; do
        echo -e "  ${GREEN}●${NC} $container"
    done
else
    echo -e "  ${YELLOW}No production containers detected${NC}"
fi

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  ✓ Dev services stopped safely                         ║${NC}"
echo -e "${GREEN}║    Production services unaffected                      ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════╝${NC}"
echo ""

# Helpful commands
echo -e "${CYAN}Helpful commands:${NC}"
echo "  # Start dev again:"
echo "  ./start_all_dev.sh"
echo ""
echo "  # Check production status:"
echo "  sg docker -c 'docker ps' | grep -v dev"
echo ""
echo "  # Remove dev volumes too:"
echo "  ./stop_dev.sh --volumes"
echo ""
