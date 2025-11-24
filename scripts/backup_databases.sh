#!/bin/bash
# Database Backup Script for ML Platform
# Backs up all PostgreSQL databases to local backup directories

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

# Backup directories
MLFLOW_BACKUP_DIR="${PROJECT_ROOT}/mlflow-server/backups/postgres"
RAY_BACKUP_DIR="${PROJECT_ROOT}/ray_compute/backups/postgres"
AUTHENTIK_BACKUP_DIR="${PROJECT_ROOT}/authentik/backups/postgres"

# Create backup directories
mkdir -p "$MLFLOW_BACKUP_DIR"
mkdir -p "$RAY_BACKUP_DIR"
mkdir -p "$AUTHENTIK_BACKUP_DIR"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}ML Platform Database Backup${NC}"
echo -e "${BLUE}Timestamp: ${TIMESTAMP}${NC}"
echo -e "${BLUE}========================================${NC}\n"

# Function to backup a database
backup_database() {
    local service_name=$1
    local container_name=$2
    local db_name=$3
    local db_user=$4
    local backup_dir=$5
    local backup_file="${backup_dir}/${db_name}_${TIMESTAMP}.sql"
    local backup_compressed="${backup_file}.gz"
    
    echo -e "${YELLOW}Backing up ${service_name}...${NC}"
    
    # Check if container is running
    if ! docker ps --format '{{.Names}}' | grep -q "^${container_name}$"; then
        echo -e "${RED}✗ Container ${container_name} is not running${NC}"
        return 1
    fi
    
    # Perform backup
    if docker exec -t "$container_name" pg_dump -U "$db_user" -d "$db_name" > "$backup_file"; then
        # Compress backup
        gzip "$backup_file"
        
        # Get backup size
        local size=$(du -h "$backup_compressed" | cut -f1)
        echo -e "${GREEN}✓ Backup completed: ${backup_compressed} (${size})${NC}"
        
        # Keep only last 10 backups
        cd "$backup_dir"
        ls -t "${db_name}_"*.sql.gz 2>/dev/null | tail -n +11 | xargs -r rm
        local count=$(ls -1 "${db_name}_"*.sql.gz 2>/dev/null | wc -l)
        echo -e "${GREEN}  Retained ${count} backup(s)${NC}\n"
        return 0
    else
        echo -e "${RED}✗ Backup failed for ${service_name}${NC}\n"
        rm -f "$backup_file"
        return 1
    fi
}

# Backup MLflow database
backup_database \
    "MLflow" \
    "mlflow-postgres" \
    "mlflow_db" \
    "mlflow" \
    "$MLFLOW_BACKUP_DIR"

# Backup Ray Compute database
backup_database \
    "Ray Compute" \
    "ray-compute-db" \
    "ray_compute" \
    "ray_compute" \
    "$RAY_BACKUP_DIR"

# Backup Authentik database
backup_database \
    "Authentik" \
    "authentik-postgres" \
    "authentik" \
    "authentik" \
    "$AUTHENTIK_BACKUP_DIR"

echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}Backup process completed${NC}"
echo -e "${BLUE}========================================${NC}"

# Summary
echo -e "\n${BLUE}Backup Locations:${NC}"
echo -e "  MLflow:    ${MLFLOW_BACKUP_DIR}"
echo -e "  Ray:       ${RAY_BACKUP_DIR}"
echo -e "  Authentik: ${AUTHENTIK_BACKUP_DIR}"

exit 0
