#!/bin/bash
# ML Platform Backup Script
# Creates comprehensive backup of MLflow and Ray data to host storage

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKUP_ROOT="${PROJECT_ROOT}/backups/platform"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="${BACKUP_ROOT}/${TIMESTAMP}"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "=========================================="
echo "ML Platform Backup"
echo "=========================================="
echo "Timestamp: ${TIMESTAMP}"
echo "Backup Location: ${BACKUP_DIR}"
echo ""

# Create backup directory
mkdir -p "${BACKUP_DIR}"

# Backup PostgreSQL databases
echo "📦 Backing up PostgreSQL databases..."
if docker ps --format '{{.Names}}' | grep -q "^mlflow-postgres$"; then
    echo "  → MLflow database..."
    docker exec mlflow-postgres pg_dump -U mlflow mlflow_db | gzip > "${BACKUP_DIR}/mlflow_db.sql.gz"
    echo -e "${GREEN}  ✓ MLflow database backed up${NC}"
else
    echo -e "${YELLOW}  ⚠ MLflow postgres not running${NC}"
fi

if docker ps --format '{{.Names}}' | grep -q "^ray-compute-db$"; then
    echo "  → Ray database..."
    docker exec ray-compute-db pg_dump -U ray_compute ray_compute | gzip > "${BACKUP_DIR}/ray_db.sql.gz"
    echo -e "${GREEN}  ✓ Ray database backed up${NC}"
else
    echo -e "${YELLOW}  ⚠ Ray postgres not running${NC}"
fi

# Backup Docker volumes (use docker run with alpine to handle permissions)
echo ""
echo "📁 Backing up Docker volumes..."

# Create backup directory with proper permissions
mkdir -p "${BACKUP_DIR}/volumes"

# Backup MLflow artifacts volume
echo "  → MLflow artifacts volume..."
docker run --rm \
    -v mlflow-artifacts:/source:ro \
    -v "${BACKUP_DIR}/volumes":/backup \
    alpine sh -c "cd /source && tar czf /backup/mlflow_artifacts.tar.gz ." 2>/dev/null
if [ $? -eq 0 ]; then
    echo -e "${GREEN}  ✓ MLflow artifacts backed up${NC}"
else
    echo -e "${YELLOW}  ⚠ MLflow artifacts backup failed (volume may be empty)${NC}"
fi

# Backup MLflow mlruns volume
echo "  → MLflow mlruns volume..."
docker run --rm \
    -v mlflow-mlruns:/source:ro \
    -v "${BACKUP_DIR}/volumes":/backup \
    alpine sh -c "cd /source && tar czf /backup/mlflow_mlruns.tar.gz ." 2>/dev/null
if [ $? -eq 0 ]; then
    echo -e "${GREEN}  ✓ MLflow mlruns backed up${NC}"
else
    echo -e "${YELLOW}  ⚠ MLflow mlruns backup skipped (may be empty)${NC}"
fi

# Backup configuration files
echo ""
echo "⚙️  Backing up configuration..."
(cd "${PROJECT_ROOT}" && tar -czf "${BACKUP_DIR}/config.tar.gz" \
    docker-compose.yml \
    start_all.sh \
    stop_all.sh \
    ml-platform/mlflow-server/config \
    ml-platform/mlflow-server/docker \
    ml-platform/mlflow-server/scripts \
    ml-platform/ray_compute/config \
    2>/dev/null) && echo -e "${GREEN}  ✓ Configuration backed up${NC}" || echo -e "${YELLOW}  ⚠ Some config files not found${NC}"

# Create backup manifest
echo ""
echo "📋 Creating backup manifest..."
cat > "${BACKUP_DIR}/manifest.json" << EOF
{
  "timestamp": "${TIMESTAMP}",
  "date": "$(date -Iseconds)",
  "hostname": "$(hostname)",
  "mlflow_version": "$(docker exec mlflow-server mlflow --version 2>/dev/null || echo 'unknown')",
  "backup_contents": {
    "mlflow_db": $([ -f "${BACKUP_DIR}/mlflow_db.sql.gz" ] && echo "true" || echo "false"),
    "ray_db": $([ -f "${BACKUP_DIR}/ray_db.sql.gz" ] && echo "true" || echo "false"),
    "mlflow_artifacts": $([ -f "${BACKUP_DIR}/mlflow_artifacts.tar.gz" ] && echo "true" || echo "false"),
    "config": $([ -f "${BACKUP_DIR}/config.tar.gz" ] && echo "true" || echo "false")
  },
  "volumes": {
    "mlflow-postgres-data": "persisted",
    "mlflow-artifacts": "persisted",
    "ray-postgres-data": "persisted"
  }
}
EOF

# Calculate backup size
BACKUP_SIZE=$(du -sh "${BACKUP_DIR}" | cut -f1)

echo ""
echo "=========================================="
echo -e "${GREEN}✓ Backup Complete!${NC}"
echo "=========================================="
echo "Location: ${BACKUP_DIR}"
echo "Size: ${BACKUP_SIZE}"
echo ""
echo "To restore this backup:"
echo "  ./scripts/restore_platform.sh ${TIMESTAMP}"
echo ""

# Cleanup old backups (keep last 7 days)
echo "🗑️  Cleaning up old backups (keeping last 7 days)..."
find "${BACKUP_ROOT}" -maxdepth 1 -type d -mtime +7 -exec rm -rf {} \; 2>/dev/null || true
echo -e "${GREEN}✓ Cleanup complete${NC}"
echo ""
