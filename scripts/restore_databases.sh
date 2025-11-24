#!/bin/bash
# Database Restore Script for ML Platform
# Restores PostgreSQL databases from backup files

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

# Backup directories
MLFLOW_BACKUP_DIR="${PROJECT_ROOT}/mlflow-server/backups/postgres"
RAY_BACKUP_DIR="${PROJECT_ROOT}/ray_compute/backups/postgres"
AUTHENTIK_BACKUP_DIR="${PROJECT_ROOT}/authentik/backups/postgres"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}ML Platform Database Restore${NC}"
echo -e "${BLUE}========================================${NC}\n"

# Function to list available backups
list_backups() {
    local backup_dir=$1
    local db_name=$2
    
    if [ ! -d "$backup_dir" ]; then
        echo -e "${RED}Backup directory not found: ${backup_dir}${NC}"
        return 1
    fi
    
    local backups=($(ls -t "${backup_dir}/${db_name}_"*.sql.gz 2>/dev/null || true))
    
    if [ ${#backups[@]} -eq 0 ]; then
        echo -e "${RED}No backups found for ${db_name}${NC}"
        return 1
    fi
    
    echo -e "${BLUE}Available backups for ${db_name}:${NC}"
    for i in "${!backups[@]}"; do
        local size=$(du -h "${backups[$i]}" | cut -f1)
        local date=$(echo "${backups[$i]}" | grep -oP '\d{8}_\d{6}')
        echo -e "  $((i+1)). ${date} (${size})"
    done
    echo
}

# Function to restore a database
restore_database() {
    local service_name=$1
    local container_name=$2
    local db_name=$3
    local db_user=$4
    local backup_file=$5
    
    echo -e "${YELLOW}Restoring ${service_name}...${NC}"
    
    # Check if container is running
    if ! docker ps --format '{{.Names}}' | grep -q "^${container_name}$"; then
        echo -e "${RED}✗ Container ${container_name} is not running${NC}"
        echo -e "${YELLOW}  Start services with: ./start_all.sh${NC}"
        return 1
    fi
    
    # Check if backup file exists
    if [ ! -f "$backup_file" ]; then
        echo -e "${RED}✗ Backup file not found: ${backup_file}${NC}"
        return 1
    fi
    
    # Confirm restore
    echo -e "${RED}WARNING: This will OVERWRITE the current ${service_name} database!${NC}"
    read -p "Are you sure you want to continue? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        echo -e "${YELLOW}Restore cancelled${NC}\n"
        return 1
    fi
    
    # Decompress and restore
    echo -e "${YELLOW}Decompressing backup...${NC}"
    local temp_file="/tmp/${db_name}_restore.sql"
    gunzip -c "$backup_file" > "$temp_file"
    
    echo -e "${YELLOW}Dropping existing database...${NC}"
    docker exec -t "$container_name" psql -U "$db_user" -d postgres -c "DROP DATABASE IF EXISTS ${db_name};"
    
    echo -e "${YELLOW}Creating fresh database...${NC}"
    docker exec -t "$container_name" psql -U "$db_user" -d postgres -c "CREATE DATABASE ${db_name};"
    
    echo -e "${YELLOW}Restoring from backup...${NC}"
    if docker exec -i "$container_name" psql -U "$db_user" -d "$db_name" < "$temp_file"; then
        echo -e "${GREEN}✓ Restore completed successfully${NC}\n"
        rm -f "$temp_file"
        return 0
    else
        echo -e "${RED}✗ Restore failed${NC}\n"
        rm -f "$temp_file"
        return 1
    fi
}

# Main menu
while true; do
    echo -e "${BLUE}Select database to restore:${NC}"
    echo "  1. MLflow"
    echo "  2. Ray Compute"
    echo "  3. Authentik"
    echo "  4. Exit"
    echo
    read -p "Enter choice (1-4): " choice
    echo
    
    case $choice in
        1)
            list_backups "$MLFLOW_BACKUP_DIR" "mlflow_db"
            backups=($(ls -t "${MLFLOW_BACKUP_DIR}/mlflow_db_"*.sql.gz 2>/dev/null || true))
            if [ ${#backups[@]} -gt 0 ]; then
                read -p "Select backup number to restore (or 0 to cancel): " backup_num
                if [ "$backup_num" -ge 1 ] && [ "$backup_num" -le "${#backups[@]}" ]; then
                    backup_file="${backups[$((backup_num-1))]}"
                    restore_database "MLflow" "mlflow-postgres" "mlflow_db" "mlflow" "$backup_file"
                fi
            fi
            ;;
        2)
            list_backups "$RAY_BACKUP_DIR" "ray_compute"
            backups=($(ls -t "${RAY_BACKUP_DIR}/ray_compute_"*.sql.gz 2>/dev/null || true))
            if [ ${#backups[@]} -gt 0 ]; then
                read -p "Select backup number to restore (or 0 to cancel): " backup_num
                if [ "$backup_num" -ge 1 ] && [ "$backup_num" -le "${#backups[@]}" ]; then
                    backup_file="${backups[$((backup_num-1))]}"
                    restore_database "Ray Compute" "ray-compute-db" "ray_compute" "ray_compute" "$backup_file"
                fi
            fi
            ;;
        3)
            list_backups "$AUTHENTIK_BACKUP_DIR" "authentik"
            backups=($(ls -t "${AUTHENTIK_BACKUP_DIR}/authentik_"*.sql.gz 2>/dev/null || true))
            if [ ${#backups[@]} -gt 0 ]; then
                read -p "Select backup number to restore (or 0 to cancel): " backup_num
                if [ "$backup_num" -ge 1 ] && [ "$backup_num" -le "${#backups[@]}" ]; then
                    backup_file="${backups[$((backup_num-1))]}"
                    restore_database "Authentik" "authentik-postgres" "authentik" "authentik" "$backup_file"
                fi
            fi
            ;;
        4)
            echo -e "${GREEN}Exiting${NC}"
            exit 0
            ;;
        *)
            echo -e "${RED}Invalid choice${NC}\n"
            ;;
    esac
done
