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
NC='\033[0m'

# Run backup before stopping
echo "📦 Creating backup before shutdown..."
if [ -f "./scripts/backup_platform.sh" ]; then
    ./scripts/backup_platform.sh
else
    echo -e "${YELLOW}⚠ Backup script not found - skipping backup${NC}"
fi
echo ""

# Stop all services and remove built images
echo "Stopping services and removing images..."
docker-compose down --rmi local

echo ""
echo -e "${YELLOW}Pruning Docker build cache...${NC}"
docker builder prune -af

echo ""
echo -e "${YELLOW}Removing any remaining ml-platform images...${NC}"
docker images | grep -E "projects_|ml-platform" | awk '{print $3}' | xargs -r docker rmi -f 2>/dev/null || true

echo ""
echo -e "${GREEN}✓ All services stopped and images removed${NC}"
echo -e "${GREEN}✓ Build cache cleared - images will rebuild on next start${NC}"
echo ""
echo "Note: Data volumes are preserved. To remove volumes:"
echo "  docker-compose down -v --rmi local"
echo ""
