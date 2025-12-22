#!/bin/bash
# ML Platform Restore Script
# Restores MLflow and Ray data from backup

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKUP_ROOT="${PROJECT_ROOT}/backups/platform"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

if [ -z "$1" ]; then
    echo "Usage: $0 <backup_timestamp>"
    echo ""
    echo "Available backups:"
    ls -1 "${BACKUP_ROOT}" 2>/dev/null | tail -10 || echo "  No backups found"
    exit 1
fi

TIMESTAMP="$1"
BACKUP_DIR="${BACKUP_ROOT}/${TIMESTAMP}"

if [ ! -d "${BACKUP_DIR}" ]; then
    echo -e "${RED}✗ Backup not found: ${BACKUP_DIR}${NC}"
    exit 1
fi

echo "=========================================="
echo "ML Platform Restore"
echo "=========================================="
echo "Backup: ${TIMESTAMP}"
echo "Location: ${BACKUP_DIR}"
echo ""

# Check if services are running
if docker ps | grep -q "mlflow-server\|ray-head"; then
    echo -e "${RED}✗ Services are still running!${NC}"
    echo "Please stop services first: ./stop_all.sh"
    exit 1
fi

# Restore PostgreSQL databases
echo "📦 Restoring PostgreSQL databases..."
echo "  Starting temporary database containers..."
docker-compose up -d mlflow-postgres ray-postgres
sleep 10

if [ -f "${BACKUP_DIR}/mlflow_db.sql.gz" ]; then
    echo "  → Restoring MLflow database..."
    gunzip -c "${BACKUP_DIR}/mlflow_db.sql.gz" | docker exec -i mlflow-postgres psql -U mlflow -d mlflow_db
    echo -e "${GREEN}  ✓ MLflow database restored${NC}"
fi

if [ -f "${BACKUP_DIR}/ray_db.sql.gz" ]; then
    echo "  → Restoring Ray database..."
    gunzip -c "${BACKUP_DIR}/ray_db.sql.gz" | docker exec -i ray-compute-db psql -U ray_compute -d ray_compute
    echo -e "${GREEN}  ✓ Ray database restored${NC}"
fi

# Restore MLflow volumes
echo ""
echo "📁 Restoring Docker volumes..."

if [ -f "${BACKUP_DIR}/volumes/mlflow_artifacts.tar.gz" ]; then
    echo "  → MLflow artifacts volume..."
    docker run --rm \
        -v mlflow-artifacts:/target \
        -v "${BACKUP_DIR}/volumes":/backup:ro \
        alpine sh -c "cd /target && tar xzf /backup/mlflow_artifacts.tar.gz"
    echo -e "${GREEN}  ✓ MLflow artifacts restored${NC}"
fi

if [ -f "${BACKUP_DIR}/volumes/mlflow_mlruns.tar.gz" ]; then
    echo "  → MLflow mlruns volume..."
    docker run --rm \
        -v mlflow-mlruns:/target \
        -v "${BACKUP_DIR}/volumes":/backup:ro \
        alpine sh -c "cd /target && tar xzf /backup/mlflow_mlruns.tar.gz"
    echo -e "${GREEN}  ✓ MLflow mlruns restored${NC}"
fi

# Restore configuration (optional - be careful not to overwrite current config)
if [ -f "${BACKUP_DIR}/config.tar.gz" ]; then
    echo ""
    echo -e "${YELLOW}⚠ Configuration backup found but NOT restored automatically${NC}"
    echo "  To restore config: tar -xzf ${BACKUP_DIR}/config.tar.gz -C ${PROJECT_ROOT}"
fi

echo ""
echo "=========================================="
echo -e "${GREEN}✓ Restore Complete!${NC}"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Review restored data"
echo "  2. Start services: ./start_all.sh"
echo ""
