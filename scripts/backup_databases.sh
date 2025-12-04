#!/bin/bash
# Database Backup Script for ML Platform
# Backs up all PostgreSQL databases from shared-postgres to local backup directories
# Updated: Uses shared-postgres container with all databases

set -euo pipefail

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Timestamp for backup files
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Backup directory (unified location)
BACKUP_DIR="${PROJECT_ROOT}/backups/postgres"

# Number of backups to retain per database
BACKUP_RETENTION=${BACKUP_RETENTION:-10}

# Create backup directory
mkdir -p "$BACKUP_DIR"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}ML Platform Database Backup${NC}"
echo -e "${BLUE}Timestamp: ${TIMESTAMP}${NC}"
echo -e "${BLUE}Container: shared-postgres${NC}"
echo -e "${BLUE}========================================${NC}\n"

# Check if shared-postgres container is running
if ! docker ps --format '{{.Names}}' | grep -q "^shared-postgres$"; then
    echo -e "${RED}✗ Container shared-postgres is not running${NC}"
    echo -e "${YELLOW}Start the platform first: ./start_all_safe.sh${NC}"
    exit 1
fi

# Function to backup a database
backup_database() {
    local db_name=$1
    local db_user=$2
    local backup_file="${BACKUP_DIR}/${db_name}_${TIMESTAMP}.sql"
    local backup_compressed="${backup_file}.gz"

    echo -e "${YELLOW}Backing up ${db_name}...${NC}"

    # Perform backup using shared-postgres container
    if docker exec -t shared-postgres pg_dump -U "$db_user" -d "$db_name" > "$backup_file" 2>/dev/null; then
        # Compress backup
        gzip "$backup_file"

        # Get backup size
        local size=$(du -h "$backup_compressed" | cut -f1)
        echo -e "${GREEN}✓ Backup completed: ${db_name} (${size})${NC}"

        # Keep only last N backups
        cd "$BACKUP_DIR"
        ls -t "${db_name}_"*.sql.gz 2>/dev/null | tail -n +$((BACKUP_RETENTION + 1)) | xargs -r rm
        local count=$(ls -1 "${db_name}_"*.sql.gz 2>/dev/null | wc -l)
        echo -e "${GREEN}  Retained ${count}/${BACKUP_RETENTION} backup(s)${NC}\n"
        return 0
    else
        echo -e "${RED}✗ Backup failed for ${db_name}${NC}\n"
        rm -f "$backup_file"
        return 1
    fi
}

# Track failures
failed=0

# Backup all databases from shared-postgres
# Database name and user are the same by convention in init-databases.sh

# MLflow database
backup_database "mlflow_db" "mlflow" || ((failed++))

# Ray Compute database
backup_database "ray_compute" "ray_compute" || ((failed++))

# Inference database
backup_database "inference" "inference" || ((failed++))

# FusionAuth database
backup_database "fusionauth" "fusionauth" || ((failed++))

echo -e "${BLUE}========================================${NC}"
if [ $failed -eq 0 ]; then
    echo -e "${GREEN}✓ All backups completed successfully${NC}"
else
    echo -e "${RED}✗ ${failed} backup(s) failed${NC}"
fi
echo -e "${BLUE}========================================${NC}"

# Summary
echo -e "\n${BLUE}Backup Location:${NC} ${BACKUP_DIR}"
echo -e "${BLUE}Total Size:${NC} $(du -sh "$BACKUP_DIR" | cut -f1)"

# List recent backups
echo -e "\n${BLUE}Recent Backups:${NC}"
ls -lht "$BACKUP_DIR"/*.sql.gz 2>/dev/null | head -8 || echo "No backups found"

# Send notification if configured
if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
    if [ $failed -eq 0 ]; then
        message="✅ ML Platform Backup Complete%0A📅 ${TIMESTAMP}%0A💾 $(du -sh "$BACKUP_DIR" | cut -f1)"
    else
        message="⚠️ ML Platform Backup Issues%0A📅 ${TIMESTAMP}%0A❌ ${failed} database(s) failed"
    fi
    curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage?chat_id=${TELEGRAM_CHAT_ID}&text=${message}" > /dev/null 2>&1 || true
fi

exit $failed
