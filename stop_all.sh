#!/bin/bash
# ML Platform - Unified Stop Script
# Creates backup, stops all services, and removes built images

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "ML Platform - Stopping All Services"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Run backup before stopping
echo "📦 Creating backup before shutdown..."
if [ -f "./scripts/backup_platform.sh" ]; then
    ./scripts/backup_platform.sh
else
    echo -e "${YELLOW}⚠ Backup script not found - skipping backup${NC}"
fi
echo ""

# Stop inference stack first (if running)
echo -e "${BLUE}Checking for inference stack...${NC}"
if [ -f "./inference/docker-compose.inference.yml" ]; then
    if docker ps --filter "name=qwen3-vl-api" --filter "status=running" | grep -q "qwen3-vl-api" 2>/dev/null || \
       docker ps --filter "name=z-image-api" --filter "status=running" | grep -q "z-image-api" 2>/dev/null || \
       docker ps --filter "name=inference-gateway" --filter "status=running" | grep -q "inference-gateway" 2>/dev/null; then
        echo -e "${YELLOW}Stopping inference stack...${NC}"
        docker compose -f ./inference/docker-compose.inference.yml down --remove-orphans 2>&1 | grep -v "WARNING:" || true
        echo -e "${GREEN}✓ Inference stack stopped${NC}"
    else
        echo "No inference services running"
    fi
fi
echo ""

# Stop all services and remove built images
echo "Stopping main platform services and removing images..."
docker-compose down --rmi local

echo ""
echo -e "${YELLOW}Pruning Docker build cache...${NC}"
docker builder prune -af

echo ""
echo -e "${YELLOW}Removing any remaining ml-platform images...${NC}"
docker images | grep -E "projects_|ml-platform|inference" | awk '{print $3}' | xargs -r docker rmi -f 2>/dev/null || true

echo ""
echo -e "${GREEN}✓ All services stopped and images removed${NC}"
echo -e "${GREEN}✓ Build cache cleared - images will rebuild on next start${NC}"
echo ""
echo "Note: Data volumes are preserved. To remove volumes:"
echo "  docker-compose down -v --rmi local"
if [ -f "./inference/docker-compose.inference.yml" ]; then
    echo "  docker compose -f ./inference/docker-compose.inference.yml down -v"
fi
echo ""
