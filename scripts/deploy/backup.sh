#!/usr/bin/env bash
# scripts/deploy/backup.sh — PostgreSQL backup/restore with auto-detect and smart restore
#
# Automatically restores databases from backups if they appear empty.
# Uses the largest backup from the last 25 hours for data integrity.
#
# Provides: find_best_backup, is_database_empty, restore_database_from_backup,
#           check_and_restore_databases, create_pre_restart_backup

[[ -n "${_SHML_BACKUP_LOADED:-}" ]] && return 0
_SHML_BACKUP_LOADED=1

BACKUP_DIR="${SCRIPT_DIR}/backups/postgres"
BACKUP_MAX_AGE_HOURS=${BACKUP_MAX_AGE_HOURS:-25}

# Find the best backup file for a database (largest from last N hours)
find_best_backup() {
    local db_name=$1
    local max_age_hours=${2:-$BACKUP_MAX_AGE_HOURS}
    local best_backup=""
    local best_size=0

    local backup_dirs=(
        "${BACKUP_DIR}/daily"
        "${BACKUP_DIR}/last"
        "${BACKUP_DIR}/weekly"
        "${BACKUP_DIR}"
    )

    local cutoff_time
    cutoff_time=$(date -d "${max_age_hours} hours ago" +%s 2>/dev/null || date -v-${max_age_hours}H +%s 2>/dev/null)

    for dir in "${backup_dirs[@]}"; do
        if [ -d "$dir" ]; then
            for backup_file in "$dir"/${db_name}*.sql.gz "$dir"/${db_name}*.sql; do
                if [ -f "$backup_file" ] && [ ! -L "$backup_file" ]; then
                    local file_time file_size
                    file_time=$(stat -c %Y "$backup_file" 2>/dev/null || stat -f %m "$backup_file" 2>/dev/null)
                    file_size=$(stat -c %s "$backup_file" 2>/dev/null || stat -f %z "$backup_file" 2>/dev/null)

                    if [ -n "$file_time" ] && [ "$file_time" -ge "$cutoff_time" ] && [ "$file_size" -gt "$best_size" ]; then
                        best_backup="$backup_file"
                        best_size="$file_size"
                    fi
                fi
            done
        fi
    done

    echo "$best_backup"
}

postgres_container_for_db() {
    local db_name=$1

    case "$db_name" in
        gitlab)
            echo "${PLATFORM_PREFIX:-shml}-gitlab-postgres"
            ;;
        *)
            echo "${PLATFORM_PREFIX:-shml}-postgres"
            ;;
    esac
}

postgres_admin_user_for_db() {
    local db_name=$1

    case "$db_name" in
        gitlab)
            echo "gitlab"
            ;;
        *)
            echo "postgres"
            ;;
    esac
}

# Check if a database appears to be empty/fresh
is_database_empty() {
    local db_name=$1
    local db_user=$2
    local postgres_container
    postgres_container=$(postgres_container_for_db "$db_name")

    if [ "$db_name" = "fusionauth" ]; then
        local user_count
        user_count=$(docker exec "$postgres_container" psql -U "$db_user" -d "$db_name" -t -c "SELECT COUNT(*) FROM users;" 2>/dev/null | tr -d ' ')
        [ "${user_count:-0}" -eq 0 ]
        return $?
    fi

    if [ "$db_name" = "mlflow_db" ]; then
        local exp_count
        exp_count=$(docker exec "$postgres_container" psql -U "$db_user" -d "$db_name" -t -c "SELECT COUNT(*) FROM experiments WHERE experiment_id > 0;" 2>/dev/null | tr -d ' ')
        [ "${exp_count:-0}" -eq 0 ]
        return $?
    fi

    if [ "$db_name" = "ray_compute" ]; then
        local table_exists
        table_exists=$(docker exec "$postgres_container" psql -U "$db_user" -d "$db_name" -t -c "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'jobs');" 2>/dev/null | tr -d ' ')
        if [ "$table_exists" = "t" ]; then
            local job_count
            job_count=$(docker exec "$postgres_container" psql -U "$db_user" -d "$db_name" -t -c "SELECT COUNT(*) FROM jobs;" 2>/dev/null | tr -d ' ')
            [ "${job_count:-0}" -eq 0 ]
            return $?
        fi
        return 0
    fi

    if [ "$db_name" = "gitlab" ]; then
        local table_count
        table_count=$(docker exec "$postgres_container" psql -U "$db_user" -d "$db_name" -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog', 'information_schema');" 2>/dev/null | tr -d ' ')
        [ "${table_count:-0}" -eq 0 ]
        return $?
    fi

    return 1  # Default: assume not empty
}

# Restore a database from backup
restore_database_from_backup() {
    local db_name=$1
    local db_user=$2
    local backup_file=$3
    local postgres_admin_user
    local postgres_container
    postgres_container=$(postgres_container_for_db "$db_name")
    postgres_admin_user=$(postgres_admin_user_for_db "$db_name")

    if [ ! -f "$backup_file" ]; then
        log_error "Backup file not found: $backup_file"
        return 1
    fi

    local file_type backup_size
    file_type=$(file -b "$backup_file" 2>/dev/null)
    backup_size=$(du -h "$backup_file" | cut -f1)

    echo "    Restoring $db_name from backup ($backup_size)..."

    docker exec "$postgres_container" psql -U "$postgres_admin_user" -c "DROP DATABASE IF EXISTS ${db_name};" >/dev/null 2>&1
    docker exec "$postgres_container" psql -U "$postgres_admin_user" -c "CREATE DATABASE ${db_name} OWNER ${db_user};" >/dev/null 2>&1

    if [[ "$file_type" == *"PostgreSQL custom database dump"* ]]; then
        cat "$backup_file" | docker exec -i "$postgres_container" pg_restore -U "$db_user" -d "$db_name" --no-owner --no-privileges 2>/dev/null
    elif [[ "$backup_file" == *.gz ]]; then
        gunzip -c "$backup_file" | docker exec -i "$postgres_container" psql -U "$db_user" -d "$db_name" >/dev/null 2>&1
    else
        cat "$backup_file" | docker exec -i "$postgres_container" psql -U "$db_user" -d "$db_name" >/dev/null 2>&1
    fi

    if [ $? -eq 0 ]; then
        log_success "  Restored $db_name successfully"

        if [ "$db_name" = "fusionauth" ]; then
            echo "    Applying FusionAuth migrations (sfml → shml)..."
            docker exec "$postgres_container" psql -U "$db_user" -d "$db_name" -c \
                "UPDATE tenants SET data = REPLACE(data::text, 'sfml-platform', 'shml-platform')::text WHERE data LIKE '%sfml-platform%';" >/dev/null 2>&1
            docker exec "$postgres_container" psql -U "$db_user" -d "$db_name" -c \
                "UPDATE applications SET data = REPLACE(data::text, 'sfml-platform', 'shml-platform')::text WHERE data LIKE '%sfml-platform%';" >/dev/null 2>&1
            log_success "  FusionAuth issuer URLs updated"
        fi
        return 0
    else
        log_warn "  Restore may have had warnings (check data)"
        return 0  # Non-fatal
    fi
}

# Main function to check and restore all databases
check_and_restore_databases() {
    log_info "━━━ Checking Database Integrity ━━━"
    echo "Looking for backups from the last ${BACKUP_MAX_AGE_HOURS} hours..."

    local databases=(
        "fusionauth:fusionauth:true"
        "mlflow_db:mlflow:false"
        "ray_compute:ray_compute:false"
        "inference:inference:false"
        "chat_api:chat_api:false"
        "gitlab:gitlab:false"
    )

    local restored_count=0

    for db_config in "${databases[@]}"; do
        local db_name db_user is_critical
        local postgres_admin_user
        local postgres_container
        db_name=$(echo "$db_config" | cut -d: -f1)
        db_user=$(echo "$db_config" | cut -d: -f2)
        is_critical=$(echo "$db_config" | cut -d: -f3)
        postgres_container=$(postgres_container_for_db "$db_name")
        postgres_admin_user=$(postgres_admin_user_for_db "$db_name")

        if ! docker ps --format '{{.Names}}' | grep -qx "$postgres_container"; then
            if [ "$db_name" = "gitlab" ]; then
                continue
            fi
        fi

        local db_exists
        db_exists=$(docker exec "$postgres_container" psql -U "$postgres_admin_user" -t -c "SELECT 1 FROM pg_database WHERE datname='${db_name}';" 2>/dev/null | tr -d ' ')

        if [ "$db_exists" != "1" ]; then
            echo "  Database $db_name does not exist, will create from backup..."
            local backup_file
            backup_file=$(find_best_backup "$db_name")
            if [ -n "$backup_file" ]; then
                docker exec "$postgres_container" psql -U "$postgres_admin_user" -c "CREATE DATABASE ${db_name} OWNER ${db_user};" >/dev/null 2>&1 || true
                restore_database_from_backup "$db_name" "$db_user" "$backup_file"
                restored_count=$((restored_count + 1))
            elif [ "$is_critical" = "true" ]; then
                log_warn "  No backup found for critical database $db_name!"
            fi
            continue
        fi

        if is_database_empty "$db_name" "$db_user"; then
            echo "  Database $db_name appears empty, looking for backup..."
            local backup_file
            backup_file=$(find_best_backup "$db_name")

            if [ -n "$backup_file" ]; then
                local backup_age
                backup_age=$(( ($(date +%s) - $(stat -c %Y "$backup_file" 2>/dev/null || stat -f %m "$backup_file")) / 3600 ))
                echo "    Found backup: $(basename "$backup_file") (${backup_age}h old)"
                restore_database_from_backup "$db_name" "$db_user" "$backup_file"
                restored_count=$((restored_count + 1))
            else
                if [ "$is_critical" = "true" ]; then
                    log_warn "  No recent backup found for critical database $db_name"
                else
                    echo "    No recent backup found for $db_name (non-critical)"
                fi
            fi
        else
            log_success "$db_name has existing data"
        fi
    done

    if [ $restored_count -gt 0 ]; then
        log_success "Restored $restored_count database(s) from backup"
    else
        log_success "All databases have existing data"
    fi
    echo ""
}

create_pre_restart_backup() {
    local backup_dir="${SCRIPT_DIR}/backups/postgres/pre-restart"
    local timestamp
    timestamp=$(date +%Y%m%d_%H%M%S)

    echo ""
    echo -e "${BLUE}╔════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║         Creating Pre-Restart Backup                    ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════╝${NC}"
    echo ""

    mkdir -p "$backup_dir"

    local databases=("fusionauth" "mlflow_db" "ray_compute" "inference" "chat_api" "gitlab")
    local backed_up=0

    for db in "${databases[@]}"; do
        local postgres_container
        local db_user
        postgres_container=$(postgres_container_for_db "$db")
        db_user="postgres"
        if [ "$db" = "gitlab" ]; then
            db_user="gitlab"
        fi

        if ! docker ps -q -f "name=^${postgres_container}$" | grep -q .; then
            continue
        fi

        if docker exec "$postgres_container" psql -U "$db_user" -lqt | cut -d \| -f 1 | grep -qw "$db"; then
            local backup_file="${backup_dir}/${db}_${timestamp}.sql.gz"
            echo -n "  Backing up $db..."

            if docker exec "$postgres_container" pg_dump -U "$db_user" -Fc "$db" 2>/dev/null | gzip > "$backup_file"; then
                local size
                size=$(du -h "$backup_file" | cut -f1)
                echo -e " ${GREEN}✓${NC} ($size)"
                backed_up=$((backed_up + 1))
            else
                echo -e " ${YELLOW}⚠${NC} (failed)"
                rm -f "$backup_file" 2>/dev/null
            fi
        fi
    done

    # Keep last 5 pre-restart backups per database
    if [ -d "$backup_dir" ]; then
        for db in "${databases[@]}"; do
            ls -t "$backup_dir"/${db}_*.sql.gz 2>/dev/null | tail -n +6 | xargs -r rm -f
        done
    fi

    echo ""
    if [ $backed_up -gt 0 ]; then
        log_success "Created $backed_up pre-restart backup(s) in $backup_dir"
    else
        log_warn "No databases backed up"
    fi
    echo ""
}
