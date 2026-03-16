#!/bin/bash
# =============================================================================
# Unified Backup & Restore Script for SHML Platform
# =============================================================================
# Consolidates: backup_databases.sh, backup_platform.sh, restore_databases.sh,
#               restore_platform.sh, setup_daily_backup.sh
#
# Usage:
#   ./scripts/backup.sh db backup              # Backup all databases
#   ./scripts/backup.sh db restore [timestamp] # Restore databases
#   ./scripts/backup.sh db list                # List available DB backups
#   ./scripts/backup.sh platform backup        # Full platform backup
#   ./scripts/backup.sh platform restore <ts>  # Full platform restore
#   ./scripts/backup.sh platform list          # List platform backups
#   ./scripts/backup.sh cron setup             # Setup daily backup cron
#   ./scripts/backup.sh cron remove            # Remove backup cron
# =============================================================================

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

# Backup directories
DB_BACKUP_DIR="${PROJECT_ROOT}/backups/postgres"
PLATFORM_BACKUP_DIR="${PROJECT_ROOT}/backups/platform"

# Configuration
BACKUP_RETENTION=${BACKUP_RETENTION:-10}
BACKUP_COMPRESSION=${BACKUP_COMPRESSION:-auto}
BACKUP_COMPRESSION_LEVEL=${BACKUP_COMPRESSION_LEVEL:-1}
BACKUP_THREADS=${BACKUP_THREADS:-0}
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

if [ "$BACKUP_THREADS" -le 0 ] 2>/dev/null; then
    BACKUP_THREADS=$(nproc 2>/dev/null || echo 1)
fi

# =============================================================================
# Helper Functions
# =============================================================================

print_header() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo
}

print_success() { echo -e "${GREEN}✓ $1${NC}"; }
print_error() { echo -e "${RED}✗ $1${NC}"; }
print_warning() { echo -e "${YELLOW}⚠ $1${NC}"; }
print_info() { echo -e "${CYAN}ℹ $1${NC}"; }

resolve_compression_mode() {
    local mode="${BACKUP_COMPRESSION}"
    case "$mode" in
        auto)
            if command -v zstd >/dev/null 2>&1; then
                BACKUP_COMPRESSION="zstd"
            elif command -v pigz >/dev/null 2>&1; then
                BACKUP_COMPRESSION="pigz"
            elif command -v gzip >/dev/null 2>&1; then
                BACKUP_COMPRESSION="gzip"
            else
                BACKUP_COMPRESSION="none"
            fi
            ;;
        zstd|pigz|gzip|none)
            ;;
        *)
            print_error "Invalid BACKUP_COMPRESSION=${mode}. Use auto|zstd|pigz|gzip|none"
            exit 1
            ;;
    esac

    case "$BACKUP_COMPRESSION" in
        zstd)
            command -v zstd >/dev/null 2>&1 || { print_error "zstd not installed"; exit 1; }
            ;;
        pigz)
            command -v pigz >/dev/null 2>&1 || { print_error "pigz not installed"; exit 1; }
            ;;
        gzip)
            command -v gzip >/dev/null 2>&1 || { print_error "gzip not installed"; exit 1; }
            ;;
    esac
}

volume_archive_ext() {
    case "$BACKUP_COMPRESSION" in
        zstd) echo "tar.zst" ;;
        pigz|gzip) echo "tar.gz" ;;
        none) echo "tar" ;;
    esac
}

compress_stdin_to_file() {
    local output_file="$1"
    case "$BACKUP_COMPRESSION" in
        zstd)
            zstd -q -T"${BACKUP_THREADS}" -"${BACKUP_COMPRESSION_LEVEL}" -o "$output_file"
            ;;
        pigz)
            pigz -p "${BACKUP_THREADS}" -"${BACKUP_COMPRESSION_LEVEL}" > "$output_file"
            ;;
        gzip)
            gzip -"${BACKUP_COMPRESSION_LEVEL}" > "$output_file"
            ;;
        none)
            cat > "$output_file"
            ;;
    esac
}

decompress_file_to_stdout() {
    local input_file="$1"
    case "$input_file" in
        *.tar.zst) zstd -d -q -c "$input_file" ;;
        *.tar.gz) gzip -d -c "$input_file" ;;
        *.tar) cat "$input_file" ;;
        *)
            print_error "Unsupported archive format: $input_file"
            return 1
            ;;
    esac
}

strip_archive_ext() {
    local file_name="$1"
    file_name="${file_name%.tar.zst}"
    file_name="${file_name%.tar.gz}"
    file_name="${file_name%.tar}"
    echo "$file_name"
}

get_mlflow_backup_volumes() {
    docker volume ls --format '{{.Name}}' | grep -E '(^|-)mlflow(-|$)|mlruns|artifacts' | sort -u
}

check_container() {
    local container=$1
    if ! docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
        print_error "Container ${container} is not running"
        return 1
    fi
    return 0
}

# =============================================================================
# Database Backup Functions
# =============================================================================

db_backup() {
    print_header "Database Backup - ${TIMESTAMP}"

    mkdir -p "$DB_BACKUP_DIR"

    # Check if primary postgres container is running
    if ! check_container "shml-postgres"; then
        print_warning "shml-postgres not found, trying alternative container names..."
    fi

    local backed_up=0

    # Backup MLflow database
    if docker ps --format '{{.Names}}' | grep -qE "^(shml-postgres|shared-postgres|mlflow-postgres)$"; then
        local container=$(docker ps --format '{{.Names}}' | grep -E "^(shml-postgres|shared-postgres|mlflow-postgres)$" | head -1)
        echo "Backing up MLflow database from ${container}..."

        local backup_file="${DB_BACKUP_DIR}/mlflow_${TIMESTAMP}.sql.gz"
        if docker exec "$container" pg_dump -U mlflow mlflow_db 2>/dev/null | gzip > "$backup_file"; then
            print_success "MLflow database backed up: $(du -h "$backup_file" | cut -f1)"
            backed_up=$((backed_up + 1))
        else
            print_error "Failed to backup MLflow database"
        fi
    fi

    # Backup Ray database
    if docker ps --format '{{.Names}}' | grep -qE "^(shml-postgres|shared-postgres|ray-compute-db|ray-postgres)$"; then
        local container=$(docker ps --format '{{.Names}}' | grep -E "^(shml-postgres|shared-postgres|ray-compute-db|ray-postgres)$" | head -1)
        echo "Backing up Ray database from ${container}..."

        local backup_file="${DB_BACKUP_DIR}/ray_${TIMESTAMP}.sql.gz"
        if docker exec "$container" pg_dump -U ray_compute ray_compute 2>/dev/null | gzip > "$backup_file"; then
            print_success "Ray database backed up: $(du -h "$backup_file" | cut -f1)"
            backed_up=$((backed_up + 1))
        fi
    fi

    # Backup FusionAuth database
    if docker ps --format '{{.Names}}' | grep -qE "^(shared-postgres|shml-postgres|fusionauth-postgres)$"; then
        local container=$(docker ps --format '{{.Names}}' | grep -E "^(shared-postgres|shml-postgres|fusionauth-postgres)$" | head -1)
        echo "Backing up FusionAuth database from ${container}..."

        local backup_file="${DB_BACKUP_DIR}/fusionauth_${TIMESTAMP}.sql.gz"
        if docker exec "$container" pg_dump -U fusionauth fusionauth 2>/dev/null | gzip > "$backup_file"; then
            print_success "FusionAuth database backed up: $(du -h "$backup_file" | cut -f1)"
            backed_up=$((backed_up + 1))
        fi
    fi

    if [ $backed_up -eq 0 ]; then
        print_error "No databases were backed up"
        return 1
    fi

    # Cleanup old backups
    db_cleanup

    echo
    print_success "Backed up ${backed_up} database(s)"
    echo "Location: ${DB_BACKUP_DIR}"
}

db_restore() {
    local timestamp="${1:-}"

    print_header "Database Restore"

    if [ -z "$timestamp" ]; then
        echo "Available backups:"
        db_list
        echo
        echo "Usage: $0 db restore <timestamp>"
        echo "Example: $0 db restore 20251211_120000"
        return 1
    fi

    # Find backup files
    local mlflow_backup="${DB_BACKUP_DIR}/mlflow_${timestamp}.sql.gz"
    local ray_backup="${DB_BACKUP_DIR}/ray_${timestamp}.sql.gz"
    local fusionauth_backup="${DB_BACKUP_DIR}/fusionauth_${timestamp}.sql.gz"

    local found=0
    [ -f "$mlflow_backup" ] && found=$((found + 1))
    [ -f "$ray_backup" ] && found=$((found + 1))
    [ -f "$fusionauth_backup" ] && found=$((found + 1))

    if [ $found -eq 0 ]; then
        print_error "No backups found for timestamp: ${timestamp}"
        return 1
    fi

    echo "Found ${found} backup(s) for ${timestamp}"
    echo
    read -p "⚠️  This will OVERWRITE existing data. Continue? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        print_warning "Restore cancelled"
        return 0
    fi

    # Restore MLflow
    if [ -f "$mlflow_backup" ]; then
        echo "Restoring MLflow database..."
        local container=$(docker ps --format '{{.Names}}' | grep -E "^(shml-postgres|shared-postgres|mlflow-postgres)$" | head -1)
        if [ -n "$container" ]; then
            gunzip -c "$mlflow_backup" | docker exec -i "$container" psql -U mlflow mlflow_db
            print_success "MLflow database restored"
        fi
    fi

    # Restore Ray
    if [ -f "$ray_backup" ]; then
        echo "Restoring Ray database..."
        local container=$(docker ps --format '{{.Names}}' | grep -E "^(shml-postgres|shared-postgres|ray-compute-db|ray-postgres)$" | head -1)
        if [ -n "$container" ]; then
            gunzip -c "$ray_backup" | docker exec -i "$container" psql -U ray_compute ray_compute
            print_success "Ray database restored"
        fi
    fi

    # Restore FusionAuth
    if [ -f "$fusionauth_backup" ]; then
        echo "Restoring FusionAuth database..."
        local container=$(docker ps --format '{{.Names}}' | grep -E "^(shml-postgres|shared-postgres|fusionauth-postgres)$" | head -1)
        if [ -n "$container" ]; then
            gunzip -c "$fusionauth_backup" | docker exec -i "$container" psql -U fusionauth fusionauth
            print_success "FusionAuth database restored"
        fi
    fi

    echo
    print_success "Database restore complete"
}

db_list() {
    echo "Database backups in ${DB_BACKUP_DIR}:"
    echo

    if [ ! -d "$DB_BACKUP_DIR" ] || [ -z "$(ls -A "$DB_BACKUP_DIR" 2>/dev/null)" ]; then
        print_warning "No backups found"
        return 0
    fi

    # Group by timestamp
    ls -1 "$DB_BACKUP_DIR"/*.sql.gz 2>/dev/null | \
        sed 's/.*_\([0-9]\{8\}_[0-9]\{6\}\)\.sql\.gz/\1/' | \
        sort -u | \
        while read ts; do
            echo -e "${CYAN}${ts}${NC}"
            for f in "$DB_BACKUP_DIR"/*_${ts}.sql.gz; do
                if [ -f "$f" ]; then
                    local name=$(basename "$f" | sed "s/_${ts}.sql.gz//")
                    local size=$(du -h "$f" | cut -f1)
                    echo "  └─ ${name}: ${size}"
                fi
            done
        done
}

db_cleanup() {
    print_info "Cleaning up old backups (keeping last ${BACKUP_RETENTION})..."

    for prefix in mlflow ray fusionauth; do
        local count
        count=$(find "${DB_BACKUP_DIR}" -maxdepth 1 -type f -name "${prefix}_*.sql.gz" 2>/dev/null | wc -l)
        if [ "$count" -gt "$BACKUP_RETENTION" ]; then
            local to_delete=$((count - BACKUP_RETENTION))
            find "${DB_BACKUP_DIR}" -maxdepth 1 -type f -name "${prefix}_*.sql.gz" -printf '%T@ %p\n' \
                | sort -nr \
                | tail -n "$to_delete" \
                | awk '{print $2}' \
                | xargs -r rm -f
            print_info "Removed ${to_delete} old ${prefix} backup(s)"
        fi
    done
}

# =============================================================================
# Platform Backup Functions
# =============================================================================

platform_backup() {
    print_header "Full Platform Backup - ${TIMESTAMP}"

    local backup_dir="${PLATFORM_BACKUP_DIR}/${TIMESTAMP}"
    mkdir -p "$backup_dir"

    echo "Backup location: ${backup_dir}"
    echo

    # 1. Backup databases
    echo "📦 Step 1/3: Backing up databases..."

    if docker ps --format '{{.Names}}' | grep -qE "postgres"; then
        db_backup || print_warning "Some database backups may have failed"
        # Copy DB backups to platform backup
        cp "${DB_BACKUP_DIR}"/*_${TIMESTAMP}.sql.gz "$backup_dir/" 2>/dev/null || true
    else
        print_warning "No database containers running"
    fi

    # 2. Backup Docker volumes
    echo
    echo "📁 Step 2/3: Backing up Docker volumes..."
    resolve_compression_mode
    local archive_ext
    archive_ext="$(volume_archive_ext)"
    print_info "Compression: ${BACKUP_COMPRESSION} (level=${BACKUP_COMPRESSION_LEVEL}, threads=${BACKUP_THREADS})"

    local volume_found=0
    while IFS= read -r volume; do
        [ -z "$volume" ] && continue
        volume_found=1
        local archive_file="${backup_dir}/${volume}.${archive_ext}"
        echo "  Backing up volume: ${volume}"
        docker run --rm \
            -v "${volume}:/source:ro" \
            -v "${backup_dir}:/backup" \
            alpine tar -cf - -C /source . 2>/dev/null | compress_stdin_to_file "${archive_file}" || \
            print_warning "Could not backup volume ${volume}"
    done < <(get_mlflow_backup_volumes)

    if [ "$volume_found" -eq 0 ]; then
        print_warning "No MLflow-related Docker volumes found for backup"
    fi

    if [ -d "/mlflow/artifacts" ]; then
        local host_artifact_archive="${backup_dir}/mlflow-artifacts-host.${archive_ext}"
        echo "  Backing up host path: /mlflow/artifacts"
        tar -cf - -C /mlflow/artifacts . 2>/dev/null | compress_stdin_to_file "${host_artifact_archive}" || \
            print_warning "Could not backup host path /mlflow/artifacts"
    else
        print_warning "Host path /mlflow/artifacts not found; skipping host artifact backup"
    fi

    # 3. Backup configurations
    echo
    echo "📋 Step 3/3: Backing up configurations..."

    mkdir -p "${backup_dir}/config"

    # Copy important configs (without secrets)
    for config_dir in mlflow-server/config ray_compute/config monitoring/prometheus monitoring/grafana; do
        if [ -d "${PROJECT_ROOT}/${config_dir}" ]; then
            local target="${backup_dir}/config/$(dirname "$config_dir")"
            mkdir -p "$target"
            cp -r "${PROJECT_ROOT}/${config_dir}" "$target/" 2>/dev/null || true
        fi
    done

    # Create manifest
    cat > "${backup_dir}/manifest.json" << EOF
{
    "timestamp": "${TIMESTAMP}",
    "date": "$(date -Iseconds)",
    "platform": "shml-platform",
    "contents": {
        "databases": $(ls -1 "${backup_dir}"/*.sql.gz 2>/dev/null | wc -l),
        "volumes": $(find "${backup_dir}" -maxdepth 1 -type f \( -name "*.tar.gz" -o -name "*.tar.zst" -o -name "*.tar" \) | wc -l),
        "configs": true
    }
}
EOF

    # Calculate total size
    local total_size=$(du -sh "$backup_dir" | cut -f1)

    echo
    print_success "Platform backup complete"
    echo "Location: ${backup_dir}"
    echo "Total size: ${total_size}"
}

platform_restore() {
    local timestamp="${1:-}"

    print_header "Platform Restore"

    if [ -z "$timestamp" ]; then
        echo "Available backups:"
        platform_list
        echo
        echo "Usage: $0 platform restore <timestamp>"
        return 1
    fi

    local backup_dir="${PLATFORM_BACKUP_DIR}/${timestamp}"

    if [ ! -d "$backup_dir" ]; then
        print_error "Backup not found: ${backup_dir}"
        return 1
    fi

    # Check if services are running
    if docker ps | grep -qE "mlflow-server|ray-head"; then
        print_error "Services are still running!"
        echo "Please stop services first: ./stop_all.sh"
        return 1
    fi

    echo "Restoring from: ${backup_dir}"
    echo
    read -p "⚠️  This will OVERWRITE all data. Continue? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        print_warning "Restore cancelled"
        return 0
    fi

    # 1. Restore databases
    echo
    echo "📦 Step 1/2: Restoring databases..."

    # Start only postgres containers
    docker compose -f "${PROJECT_ROOT}/deploy/compose/docker-compose.yml" up -d shml-postgres 2>/dev/null || true
    sleep 5

    for backup_file in "${backup_dir}"/*.sql.gz; do
        if [ -f "$backup_file" ]; then
            local db_name=$(basename "$backup_file" | sed 's/_[0-9]\{8\}_[0-9]\{6\}\.sql\.gz//')
            echo "  Restoring ${db_name}..."
            # Determine correct user and database
            case "$db_name" in
                mlflow) gunzip -c "$backup_file" | docker exec -i shml-postgres psql -U mlflow mlflow_db ;;
                ray) gunzip -c "$backup_file" | docker exec -i shml-postgres psql -U ray_compute ray_compute ;;
                fusionauth) gunzip -c "$backup_file" | docker exec -i shml-postgres psql -U fusionauth fusionauth ;;
            esac
        fi
    done

    # 2. Restore volumes
    echo
    echo "📁 Step 2/2: Restoring Docker volumes..."

    for volume_backup in "${backup_dir}"/*.tar*; do
        if [ -f "$volume_backup" ]; then
            local volume_file
            volume_file=$(basename "$volume_backup")
            local volume_name
            volume_name=$(strip_archive_ext "$volume_file")

            if [[ "$volume_file" == mlflow-artifacts-host.tar* ]]; then
                echo "  Restoring host path: /mlflow/artifacts"
                mkdir -p /mlflow/artifacts 2>/dev/null || true
                decompress_file_to_stdout "$volume_backup" | tar xf - -C /mlflow/artifacts 2>/dev/null || \
                    print_warning "Could not restore /mlflow/artifacts automatically"
                continue
            fi

            echo "  Restoring volume: ${volume_name}"

            # Create volume if not exists
            docker volume create "$volume_name" 2>/dev/null || true

            # Restore
            docker run --rm -v "${volume_name}:/target" alpine sh -c "rm -rf /target/*"
            decompress_file_to_stdout "$volume_backup" | docker run --rm \
                -i \
                -v "${volume_name}:/target" \
                alpine tar xf - -C /target
        fi
    done

    echo
    print_success "Platform restore complete"
    echo "Start services with: ./start_all_safe.sh"
}

platform_list() {
    echo "Platform backups in ${PLATFORM_BACKUP_DIR}:"
    echo

    if [ ! -d "$PLATFORM_BACKUP_DIR" ] || [ -z "$(ls -A "$PLATFORM_BACKUP_DIR" 2>/dev/null)" ]; then
        print_warning "No backups found"
        return 0
    fi

    for backup in "$PLATFORM_BACKUP_DIR"/*/; do
        if [ -d "$backup" ]; then
            local ts=$(basename "$backup")
            local size=$(du -sh "$backup" | cut -f1)
            local manifest="${backup}manifest.json"

            echo -e "${CYAN}${ts}${NC} (${size})"

            if [ -f "$manifest" ]; then
                local dbs=$(jq -r '.contents.databases' "$manifest" 2>/dev/null || echo "?")
                local vols=$(jq -r '.contents.volumes' "$manifest" 2>/dev/null || echo "?")
                echo "  └─ DBs: ${dbs}, Volumes: ${vols}"
            fi
        fi
    done
}

# =============================================================================
# Cron Setup Functions
# =============================================================================

cron_setup() {
    print_header "Setup Daily Backup Cron"

    local cron_cmd="0 2 * * * ${SCRIPT_DIR}/backup.sh db backup >> ${PROJECT_ROOT}/logs/backup.log 2>&1"

    # Check if already exists
    if crontab -l 2>/dev/null | grep -q "backup.sh db backup"; then
        print_warning "Backup cron job already exists"
        crontab -l | grep "backup.sh"
        return 0
    fi

    # Add to crontab
    (crontab -l 2>/dev/null || true; echo "$cron_cmd") | crontab -

    print_success "Daily backup cron job installed"
    echo "Schedule: Daily at 2:00 AM"
    echo "Log file: ${PROJECT_ROOT}/logs/backup.log"
    echo
    echo "Current crontab:"
    crontab -l | grep -E "backup|SHML" || true
}

cron_remove() {
    print_header "Remove Backup Cron"

    if ! crontab -l 2>/dev/null | grep -q "backup.sh"; then
        print_warning "No backup cron job found"
        return 0
    fi

    crontab -l | grep -v "backup.sh" | crontab -

    print_success "Backup cron job removed"
}

# =============================================================================
# Main
# =============================================================================

show_usage() {
    echo "SHML Platform Backup & Restore Tool"
    echo
    echo "Usage: $0 <category> <action> [options]"
    echo
    echo "Categories:"
    echo "  db        Database backup/restore operations"
    echo "  platform  Full platform backup/restore"
    echo "  cron      Scheduled backup management"
    echo
    echo "Database Commands:"
    echo "  $0 db backup              Backup all databases"
    echo "  $0 db restore <timestamp> Restore from backup"
    echo "  $0 db list                List available backups"
    echo
    echo "Platform Commands:"
    echo "  $0 platform backup              Full platform backup"
    echo "  $0 platform restore <timestamp> Full platform restore"
    echo "  $0 platform list                List platform backups"
    echo
    echo "Cron Commands:"
    echo "  $0 cron setup   Setup daily backup at 2 AM"
    echo "  $0 cron remove  Remove backup cron job"
    echo
    echo "Environment Variables:"
    echo "  BACKUP_RETENTION  Number of backups to keep (default: 10)"
    echo "  BACKUP_COMPRESSION  auto|zstd|pigz|gzip|none (default: auto)"
    echo "  BACKUP_COMPRESSION_LEVEL  Compression level (default: 1 for speed)"
    echo "  BACKUP_THREADS  Parallel threads for zstd/pigz (default: all CPUs)"
}

main() {
    local category="${1:-}"
    local action="${2:-}"
    shift 2 2>/dev/null || true

    case "$category" in
        db|database)
            case "$action" in
                backup) db_backup ;;
                restore) db_restore "$@" ;;
                list) db_list ;;
                cleanup) db_cleanup ;;
                *) show_usage; exit 1 ;;
            esac
            ;;
        platform)
            case "$action" in
                backup) platform_backup ;;
                restore) platform_restore "$@" ;;
                list) platform_list ;;
                *) show_usage; exit 1 ;;
            esac
            ;;
        cron)
            case "$action" in
                setup) cron_setup ;;
                remove) cron_remove ;;
                *) show_usage; exit 1 ;;
            esac
            ;;
        -h|--help|help)
            show_usage
            ;;
        *)
            show_usage
            exit 1
            ;;
    esac
}

main "$@"
