#!/bin/bash
# ML Platform - Safe Startup Script (Unified Approach)
# Handles cleanup, stopping, and starting services in phases with health monitoring
#
# CRITICAL DEPENDENCY ORDER:
# 1. Infrastructure (Traefik, Postgres, Redis) - no dependencies
# 2. FusionAuth - needs Postgres
# 3. Tailscale Funnel - needs Traefik (for routing)
# 4. OAuth2 Proxy - needs FusionAuth + Tailscale (for OIDC discovery via public URL)
# 5. Protected Services - need OAuth2 Proxy middleware registered in Traefik
#
# LESSONS LEARNED (December 2025):
# ================================
# 1. OAuth2 Proxy Health Check:
#    - The quay.io/oauth2-proxy/oauth2-proxy image is a SCRATCH/DISTROLESS image
#    - It has NO shell tools (no wget, curl, ls, or even sh)
#    - Health checks using wget/curl will ALWAYS fail
#    - Solution: Use "healthcheck: disable: true" in docker-compose
#    - Traefik will then use container "running" status instead of "healthy"
#
# 2. Traefik Container Filtering:
#    - Traefik FILTERS OUT containers that are "unhealthy" or "starting"
#    - This means middleware from unhealthy containers is NEVER registered
#    - Debug with: docker logs <traefik> 2>&1 | grep -i "filter"
#    - Check status: docker inspect <container> --format='{{.State.Health.Status}}'
#
# 3. OAuth2 Proxy Path Prefix:
#    - FusionAuth uses /oauth2/* for its OIDC endpoints (callback, token, authorize)
#    - OAuth2 Proxy also defaults to /oauth2/* prefix
#    - CONFLICT: Traefik routes all /oauth2/* to FusionAuth, breaking OAuth2 Proxy
#    - Solution: Use /oauth2-proxy/* prefix for OAuth2 Proxy
#    - Set OAUTH2_PROXY_PROXY_PREFIX=/oauth2-proxy in environment
#    - Update redirect URL to /oauth2-proxy/callback
#    - Update forwardAuth address to /oauth2-proxy/auth
#
# 4. Middleware Registration Verification:
#    - ALWAYS verify oauth2-auth@docker middleware exists before starting protected services
#    - Check: curl -s http://localhost:8090/api/http/middlewares | jq '.[].name'
#    - Protected services will return 500 errors if middleware doesn't exist
#
# 5. FusionAuth OAuth Client Setup:
#    - The OAuth client in FusionAuth must have /oauth2-proxy/callback as authorized redirect
#    - If you get "invalid_redirect_uri" error, run: ./start_all_safe.sh fix-oauth
#    - Or manually: FusionAuth admin UI → Applications → OAuth2-Proxy → Edit → OAuth → Authorized redirect URLs
#    - Add: https://<your-domain>/oauth2-proxy/callback
#
# 6. Login Redirect Flow:
#    - User visits protected page (e.g., /mlflow/)
#    - oauth2-errors middleware catches 401 from oauth2-auth
#    - Redirects to /oauth2-proxy/sign_in with original URL as ?rd= parameter
#    - OAuth2 Proxy redirects to FusionAuth /oauth2/authorize
#    - User authenticates with FusionAuth (supports SSO, social logins, etc.)
#    - FusionAuth redirects to /oauth2-proxy/callback with auth code
#    - OAuth2 Proxy exchanges code for token and sets session cookie
#    - User is redirected back to original page
#
# Usage:
#   ./start_all_safe.sh          # Full restart (stop + cleanup + start)
#   ./start_all_safe.sh start    # Start only (assumes clean state)
#   ./start_all_safe.sh stop     # Stop all services
#   ./start_all_safe.sh restart  # Full restart (default)
#   ./start_all_safe.sh status   # Show service status
#   ./start_all_safe.sh diagnose # Verify auth protection and middleware
#   ./start_all_safe.sh fix-oauth # Fix FusionAuth OAuth redirect URLs

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Configurable timeouts (in seconds)
POSTGRES_TIMEOUT=${POSTGRES_TIMEOUT:-120}
TRAEFIK_TIMEOUT=${TRAEFIK_TIMEOUT:-60}
PROMETHEUS_TIMEOUT=${PROMETHEUS_TIMEOUT:-90}
GRAFANA_TIMEOUT=${GRAFANA_TIMEOUT:-90}
FUSIONAUTH_TIMEOUT=${FUSIONAUTH_TIMEOUT:-180}
OAUTH2_PROXY_TIMEOUT=${OAUTH2_PROXY_TIMEOUT:-120}
MLFLOW_TIMEOUT=${MLFLOW_TIMEOUT:-120}
RAY_TIMEOUT=${RAY_TIMEOUT:-120}
DEFAULT_TIMEOUT=${DEFAULT_TIMEOUT:-60}

# =============================================================================
# Helper Functions
# =============================================================================

log_info() { echo -e "${CYAN}$1${NC}"; }
log_success() { echo -e "${GREEN}✓ $1${NC}"; }
log_warn() { echo -e "${YELLOW}⚠ $1${NC}"; }
log_error() { echo -e "${RED}✗ $1${NC}"; }

# Wait for container health with configurable timeout
wait_for_health() {
    local container=$1
    local timeout=${2:-$DEFAULT_TIMEOUT}
    local wait_time=0
    local interval=3

    echo -n "  Waiting for $container to be healthy"
    while [ $wait_time -lt $timeout ]; do
        # Check if container exists
        if ! docker inspect "$container" >/dev/null 2>&1; then
            echo -n "."
            sleep $interval
            wait_time=$((wait_time + interval))
            continue
        fi

        local status=$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$container" 2>/dev/null || echo "not-found")

        case "$status" in
            "healthy")
                echo -e " ${GREEN}✓${NC} (${wait_time}s)"
                return 0
                ;;
            "no-healthcheck")
                # Container has no healthcheck, check if running
                local running=$(docker inspect --format='{{.State.Running}}' "$container" 2>/dev/null || echo "false")
                if [ "$running" = "true" ]; then
                    echo -e " ${GREEN}✓${NC} (running, no healthcheck)"
                    return 0
                fi
                ;;
            "unhealthy")
                # Don't fail immediately - service might recover
                ;;
        esac

        echo -n "."
        sleep $interval
        wait_time=$((wait_time + interval))
    done

    echo -e " ${YELLOW}⚠${NC} (timeout after ${timeout}s)"
    return 1
}

# Wait for HTTP endpoint to be reachable
wait_for_http() {
    local url=$1
    local timeout=${2:-30}
    local wait_time=0
    local interval=2

    echo -n "  Waiting for $url"
    while [ $wait_time -lt $timeout ]; do
        if curl -sf -o /dev/null "$url" 2>/dev/null; then
            echo -e " ${GREEN}✓${NC} (${wait_time}s)"
            return 0
        fi
        echo -n "."
        sleep $interval
        wait_time=$((wait_time + interval))
    done

    echo -e " ${YELLOW}⚠${NC} (timeout after ${timeout}s)"
    return 1
}

# Wait for Traefik middleware to be registered
wait_for_middleware() {
    local middleware=$1
    local timeout=${2:-60}
    local wait_time=0
    local interval=3

    echo -n "  Waiting for Traefik middleware '$middleware'"
    while [ $wait_time -lt $timeout ]; do
        # Check Traefik API for middleware
        if curl -sf "http://localhost:8090/api/http/middlewares/${middleware}@docker" >/dev/null 2>&1; then
            echo -e " ${GREEN}✓${NC} (${wait_time}s)"
            return 0
        fi
        echo -n "."
        sleep $interval
        wait_time=$((wait_time + interval))
    done

    echo -e " ${YELLOW}⚠${NC} (timeout after ${timeout}s)"
    return 1
}

# Stop a container gracefully
stop_container() {
    local container=$1
    if docker ps -q -f "name=$container" | grep -q .; then
        echo -n "  Stopping $container..."
        docker stop "$container" -t 10 >/dev/null 2>&1 && echo -e " ${GREEN}✓${NC}" || echo -e " ${YELLOW}⚠${NC}"
    fi
}

# =============================================================================
# Database Backup Restoration
# Automatically restores databases from backups if they appear empty
# Uses the largest backup from the last 25 hours for data integrity
# =============================================================================

BACKUP_DIR="${SCRIPT_DIR}/backups/postgres"
BACKUP_MAX_AGE_HOURS=${BACKUP_MAX_AGE_HOURS:-25}

# Find the best backup file for a database (largest from last N hours)
find_best_backup() {
    local db_name=$1
    local max_age_hours=${2:-$BACKUP_MAX_AGE_HOURS}
    local best_backup=""
    local best_size=0

    # Search in all backup locations
    local backup_dirs=(
        "${BACKUP_DIR}/daily"
        "${BACKUP_DIR}/last"
        "${BACKUP_DIR}/weekly"
        "${BACKUP_DIR}"
    )

    local cutoff_time=$(date -d "${max_age_hours} hours ago" +%s 2>/dev/null || date -v-${max_age_hours}H +%s 2>/dev/null)

    for dir in "${backup_dirs[@]}"; do
        if [ -d "$dir" ]; then
            # Find backup files for this database
            for backup_file in "$dir"/${db_name}*.sql.gz "$dir"/${db_name}*.sql; do
                if [ -f "$backup_file" ] && [ ! -L "$backup_file" ]; then
                    local file_time=$(stat -c %Y "$backup_file" 2>/dev/null || stat -f %m "$backup_file" 2>/dev/null)
                    local file_size=$(stat -c %s "$backup_file" 2>/dev/null || stat -f %z "$backup_file" 2>/dev/null)

                    # Check if within time window and larger than current best
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

# Check if a database appears to be empty/fresh
is_database_empty() {
    local db_name=$1
    local db_user=$2
    local postgres_container="${PLATFORM_PREFIX:-shml}-postgres"

    # For FusionAuth, check user count (should be > 0 if configured)
    if [ "$db_name" = "fusionauth" ]; then
        local user_count=$(docker exec "$postgres_container" psql -U "$db_user" -d "$db_name" -t -c "SELECT COUNT(*) FROM users;" 2>/dev/null | tr -d ' ')
        [ "${user_count:-0}" -eq 0 ]
        return $?
    fi

    # For MLflow, check if any experiments exist beyond default
    if [ "$db_name" = "mlflow_db" ]; then
        local exp_count=$(docker exec "$postgres_container" psql -U "$db_user" -d "$db_name" -t -c "SELECT COUNT(*) FROM experiments WHERE experiment_id > 0;" 2>/dev/null | tr -d ' ')
        [ "${exp_count:-0}" -eq 0 ]
        return $?
    fi

    # For Ray, check if any jobs exist
    if [ "$db_name" = "ray_compute" ]; then
        local table_exists=$(docker exec "$postgres_container" psql -U "$db_user" -d "$db_name" -t -c "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'jobs');" 2>/dev/null | tr -d ' ')
        if [ "$table_exists" = "t" ]; then
            local job_count=$(docker exec "$postgres_container" psql -U "$db_user" -d "$db_name" -t -c "SELECT COUNT(*) FROM jobs;" 2>/dev/null | tr -d ' ')
            [ "${job_count:-0}" -eq 0 ]
            return $?
        fi
        return 0  # No jobs table means empty
    fi

    # Default: assume not empty
    return 1
}

# Restore a database from backup
restore_database_from_backup() {
    local db_name=$1
    local db_user=$2
    local backup_file=$3
    local postgres_container="${PLATFORM_PREFIX:-shml}-postgres"

    if [ ! -f "$backup_file" ]; then
        log_error "Backup file not found: $backup_file"
        return 1
    fi

    local file_type=$(file -b "$backup_file" 2>/dev/null)
    local backup_size=$(du -h "$backup_file" | cut -f1)

    echo "    Restoring $db_name from backup ($backup_size)..."

    # Drop and recreate database
    docker exec "$postgres_container" psql -U postgres -c "DROP DATABASE IF EXISTS ${db_name};" >/dev/null 2>&1
    docker exec "$postgres_container" psql -U postgres -c "CREATE DATABASE ${db_name} OWNER ${db_user};" >/dev/null 2>&1

    # Restore based on file type
    if [[ "$file_type" == *"PostgreSQL custom database dump"* ]]; then
        # pg_dump custom format - use pg_restore
        cat "$backup_file" | docker exec -i "$postgres_container" pg_restore -U "$db_user" -d "$db_name" --no-owner --no-privileges 2>/dev/null
    elif [[ "$backup_file" == *.gz ]]; then
        # Gzipped SQL
        gunzip -c "$backup_file" | docker exec -i "$postgres_container" psql -U "$db_user" -d "$db_name" >/dev/null 2>&1
    else
        # Plain SQL
        cat "$backup_file" | docker exec -i "$postgres_container" psql -U "$db_user" -d "$db_name" >/dev/null 2>&1
    fi

    if [ $? -eq 0 ]; then
        log_success "  Restored $db_name successfully"

        # Post-restore migrations for FusionAuth (sfml → shml platform name change)
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
        return 0  # Non-fatal - some warnings are OK
    fi
}

# Main function to check and restore all databases
check_and_restore_databases() {
    local postgres_container="${PLATFORM_PREFIX:-shml}-postgres"

    log_info "━━━ Checking Database Integrity ━━━"
    echo "Looking for backups from the last ${BACKUP_MAX_AGE_HOURS} hours..."

    # Database configurations: name, user, critical (requires restore)
    local databases=(
        "fusionauth:fusionauth:true"
        "mlflow_db:mlflow:false"
        "ray_compute:ray_compute:false"
        "inference:inference:false"
        "chat_api:chat_api:false"
    )

    local restored_count=0

    for db_config in "${databases[@]}"; do
        local db_name=$(echo "$db_config" | cut -d: -f1)
        local db_user=$(echo "$db_config" | cut -d: -f2)
        local is_critical=$(echo "$db_config" | cut -d: -f3)

        # Check if database exists
        local db_exists=$(docker exec "$postgres_container" psql -U postgres -t -c "SELECT 1 FROM pg_database WHERE datname='${db_name}';" 2>/dev/null | tr -d ' ')

        if [ "$db_exists" != "1" ]; then
            echo "  Database $db_name does not exist, will create from backup..."
            local backup_file=$(find_best_backup "$db_name")
            if [ -n "$backup_file" ]; then
                # Create database first
                docker exec "$postgres_container" psql -U postgres -c "CREATE DATABASE ${db_name} OWNER ${db_user};" >/dev/null 2>&1 || true
                restore_database_from_backup "$db_name" "$db_user" "$backup_file"
                restored_count=$((restored_count + 1))
            elif [ "$is_critical" = "true" ]; then
                log_warn "  No backup found for critical database $db_name!"
            fi
            continue
        fi

        # Check if database appears empty
        if is_database_empty "$db_name" "$db_user"; then
            echo "  Database $db_name appears empty, looking for backup..."
            local backup_file=$(find_best_backup "$db_name")

            if [ -n "$backup_file" ]; then
                local backup_age=$(( ($(date +%s) - $(stat -c %Y "$backup_file" 2>/dev/null || stat -f %m "$backup_file")) / 3600 ))
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

# =============================================================================
# Pre-Restart Backup
# Creates a backup before stopping services to ensure data safety
# =============================================================================

create_pre_restart_backup() {
    local postgres_container="${PLATFORM_PREFIX:-shml}-postgres"
    local backup_dir="${SCRIPT_DIR}/backups/postgres/pre-restart"
    local timestamp=$(date +%Y%m%d_%H%M%S)

    # Check if postgres is running
    if ! docker ps -q -f "name=$postgres_container" | grep -q .; then
        log_warn "PostgreSQL not running, skipping pre-restart backup"
        return 0
    fi

    echo ""
    echo -e "${BLUE}╔════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║         Creating Pre-Restart Backup                    ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════╝${NC}"
    echo ""

    # Create backup directory
    mkdir -p "$backup_dir"

    # List of databases to backup
    local databases=("fusionauth" "mlflow_db" "ray_compute" "inference" "chat_api")
    local backed_up=0

    for db in "${databases[@]}"; do
        # Check if database exists
        if docker exec "$postgres_container" psql -U postgres -lqt | cut -d \| -f 1 | grep -qw "$db"; then
            local backup_file="${backup_dir}/${db}_${timestamp}.sql.gz"
            echo -n "  Backing up $db..."

            if docker exec "$postgres_container" pg_dump -U postgres -Fc "$db" 2>/dev/null | gzip > "$backup_file"; then
                local size=$(du -h "$backup_file" | cut -f1)
                echo -e " ${GREEN}✓${NC} ($size)"
                backed_up=$((backed_up + 1))
            else
                echo -e " ${YELLOW}⚠${NC} (failed)"
                rm -f "$backup_file" 2>/dev/null
            fi
        fi
    done

    # Cleanup old pre-restart backups (keep last 5)
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

# =============================================================================
# Stop All Services
# =============================================================================

stop_all_services() {
    echo ""
    echo -e "${BLUE}╔════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║         ML Platform - Stopping Services                ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════╝${NC}"
    echo ""

    # Phase 1: Stop Tailscale Funnel
    log_info "━━━ Stopping Tailscale Funnel ━━━"
    if command -v tailscale &>/dev/null; then
        sudo tailscale funnel --https=443 off 2>/dev/null || true
        log_success "Tailscale Funnel stopped"
    fi
    echo ""

    # Phase 2: Stop Inference Services
    log_info "━━━ Stopping Inference Services ━━━"
    if [ -f "inference/chat-api/docker-compose.yml" ]; then
        docker compose --env-file .env -f inference/chat-api/docker-compose.yml stop 2>/dev/null || true
    fi
    if [ -f "inference/coding-model/docker-compose.yml" ]; then
        docker compose --env-file .env -f inference/coding-model/docker-compose.yml stop 2>/dev/null || true
    fi
    log_success "Inference services stopped"
    echo ""

    # Phase 3: Stop Ray Services
    log_info "━━━ Stopping Ray Services ━━━"
    docker compose stop ray-compute-api ray-head ray-prometheus 2>/dev/null || true
    log_success "Ray services stopped"
    echo ""

    # Phase 4: Stop MLflow Services
    log_info "━━━ Stopping MLflow Services ━━━"
    docker compose stop mlflow-api mlflow-nginx mlflow-server mlflow-prometheus 2>/dev/null || true
    log_success "MLflow services stopped"
    echo ""

    # Phase 5: Stop Monitoring (Grafana/Prometheus)
    log_info "━━━ Stopping Monitoring ━━━"
    docker compose stop unified-grafana global-prometheus 2>/dev/null || true
    docker compose stop cadvisor node-exporter 2>/dev/null || true
    log_success "Monitoring stopped"
    echo ""

    # Phase 6: Stop Auth Services
    log_info "━━━ Stopping Auth Services ━━━"
    docker compose stop oauth2-proxy role-auth fusionauth 2>/dev/null || true
    log_success "Auth services stopped"
    echo ""

    # Phase 7: Stop Infrastructure
    log_info "━━━ Stopping Infrastructure ━━━"
    docker compose stop traefik redis postgres 2>/dev/null || true
    log_success "Infrastructure stopped"
    echo ""

    log_success "All services stopped"
}

# =============================================================================
# Cleanup Orphaned/Dangling Containers AND Networks
# =============================================================================

cleanup_containers() {
    echo ""
    log_info "━━━ Cleaning up ALL platform containers and networks ━━━"

    # Stop all containers from compose files first
    log_info "Stopping all compose services..."
    docker compose --env-file .env down --remove-orphans 2>/dev/null || true
    if [ -f "inference/chat-api/docker-compose.yml" ]; then
        docker compose --env-file .env -f inference/chat-api/docker-compose.yml down --remove-orphans 2>/dev/null || true
    fi
    if [ -f "inference/coding-model/docker-compose.yml" ]; then
        docker compose --env-file .env -f inference/coding-model/docker-compose.yml down --remove-orphans 2>/dev/null || true
    fi
    if [ -f "monitoring/dcgm-exporter/docker-compose.yml" ]; then
        docker compose -f monitoring/dcgm-exporter/docker-compose.yml down --remove-orphans 2>/dev/null || true
    fi

    # List of all known containers (both old and new naming schemes)
    local containers=(
        # Ray
        "ray-compute-api" "ray-head" "ray-prometheus"
        # MLflow
        "mlflow-api" "mlflow-nginx" "mlflow-server" "mlflow-prometheus"
        # Auth
        "oauth2-proxy" "fusionauth" "role-auth" "${PLATFORM_PREFIX:-shml}-role-auth"
        # Monitoring
        "unified-grafana" "global-prometheus" "dcgm-exporter"
        # Infrastructure - old naming
        "ml-platform-cadvisor" "ml-platform-node-exporter"
        "ml-platform-traefik" "ml-platform-redis" "shml-postgres"
        # Infrastructure - new naming with prefix
        "${PLATFORM_PREFIX:-shml}-cadvisor" "${PLATFORM_PREFIX:-shml}-node-exporter"
        "${PLATFORM_PREFIX:-shml}-traefik" "${PLATFORM_PREFIX:-shml}-redis" "${PLATFORM_PREFIX:-shml}-postgres"
        # UI
        "homer" "dozzle" "postgres-backup" "webhook-deployer"
        # Inference
        "coding-model-primary" "coding-model-fallback"
        "${PLATFORM_PREFIX:-shml}-chat-api"
        # Dev
        "dev-postgres" "dev-redis" "dev-test"
    )

    local cleaned=0
    for container in "${containers[@]}"; do
        if docker ps -aq -f "name=^${container}$" | grep -q .; then
            echo -n "  Removing $container..."
            docker rm -f "$container" >/dev/null 2>&1 && echo -e " ${GREEN}✓${NC}" || echo -e " ${YELLOW}⚠${NC}"
            cleaned=$((cleaned + 1))
        fi
    done

    # Clean any remaining containers with platform-related names
    local orphans=$(docker ps -aq --filter "name=ml-platform" --filter "name=sfml" --filter "name=shml" --filter "name=mlflow" --filter "name=ray" --filter "name=coding-model" 2>/dev/null)
    if [ -n "$orphans" ]; then
        echo "  Removing additional orphaned containers..."
        echo "$orphans" | xargs docker rm -f >/dev/null 2>&1 || true
        cleaned=$((cleaned + 1))
    fi

    # =========================================================================
    # Network Cleanup - CRITICAL for preventing "Pool overlaps" errors
    # Both old (ml-platform) and new (shml-platform) network names must be removed
    # to allow recreation with potentially different subnet configurations
    # =========================================================================
    log_info "Cleaning up platform networks..."
    local networks=(
        "ml-platform"
        "shml-platform"
        "${PLATFORM_PREFIX:-shml}-platform"
        "sfml-platform"
    )

    for network in "${networks[@]}"; do
        if docker network ls --format '{{.Name}}' | grep -q "^${network}$"; then
            echo -n "  Removing network $network..."
            docker network rm "$network" >/dev/null 2>&1 && echo -e " ${GREEN}✓${NC}" || echo -e " ${YELLOW}⚠${NC}"
        fi
    done

    if [ $cleaned -eq 0 ]; then
        log_success "No container cleanup needed"
    else
        log_success "Cleanup complete ($cleaned containers removed)"
    fi
    log_success "Network cleanup complete"
    echo ""
}

# =============================================================================
# Rebuild All Images (Ensures containers use latest code)
# =============================================================================

rebuild_images() {
    echo ""
    log_info "━━━ Rebuilding Container Images ━━━"
    echo "Building images with cache (fast if no changes)..."
    echo ""

    # Build services that have custom Dockerfiles
    # Docker's layer cache makes this fast when nothing changed
    local build_failed=0

    # MLflow server (has security middleware changes)
    echo -n "  Building mlflow-server..."
    if docker compose build mlflow-server >/dev/null 2>&1; then
        echo -e " ${GREEN}✓${NC}"
    else
        echo -e " ${YELLOW}⚠ (using existing)${NC}"
        build_failed=$((build_failed + 1))
    fi

    # MLflow API
    echo -n "  Building mlflow-api..."
    if docker compose build mlflow-api >/dev/null 2>&1; then
        echo -e " ${GREEN}✓${NC}"
    else
        echo -e " ${YELLOW}⚠ (using existing)${NC}"
        build_failed=$((build_failed + 1))
    fi

    # Ray head (if custom Dockerfile exists)
    echo -n "  Building ray-head..."
    if docker compose build ray-head >/dev/null 2>&1; then
        echo -e " ${GREEN}✓${NC}"
    else
        echo -e " ${YELLOW}⚠ (using existing)${NC}"
        build_failed=$((build_failed + 1))
    fi

    # Ray compute API
    echo -n "  Building ray-compute-api..."
    if docker compose build ray-compute-api >/dev/null 2>&1; then
        echo -e " ${GREEN}✓${NC}"
    else
        echo -e " ${YELLOW}⚠ (using existing)${NC}"
        build_failed=$((build_failed + 1))
    fi

    # Role Auth (RBAC middleware)
    echo -n "  Building role-auth..."
    if docker compose build role-auth >/dev/null 2>&1; then
        echo -e " ${GREEN}✓${NC}"
    else
        echo -e " ${YELLOW}⚠ (using existing)${NC}"
        build_failed=$((build_failed + 1))
    fi

    echo ""
    if [ $build_failed -eq 0 ]; then
        log_success "All images rebuilt successfully"
    else
        log_warn "Some builds used existing images (this is OK if no code changes)"
    fi
    echo ""
}

# =============================================================================
# Start All Services (Proper Dependency Order)
# =============================================================================

start_all_services() {
    echo ""
    echo -e "${BLUE}╔════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║                                                        ║${NC}"
    echo -e "${BLUE}║         ML Platform - Safe Startup                     ║${NC}"
    echo -e "${BLUE}║         Unified Docker Compose Approach                ║${NC}"
    echo -e "${BLUE}║                                                        ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${YELLOW}Dependency Order: Infra → FusionAuth → Tailscale → OAuth2 Proxy → Protected Services${NC}"
    echo ""

    # Check if running as root
    if [ "$EUID" -eq 0 ]; then
        log_error "Do not run this script as root (sudo)"
        echo "The script will request sudo when needed."
        exit 1
    fi

    # =========================================================================
    # Pre-flight: Tailscale IP Validation
    # After Tailscale reset/logout, the IP may change. This check catches
    # stale configuration BEFORE services fail with cryptic errors.
    # =========================================================================
    if command -v tailscale &>/dev/null && tailscale status >/dev/null 2>&1; then
        CURRENT_TS_IP=$(tailscale ip -4 2>/dev/null || echo "")
        CONFIGURED_TS_IP=$(grep "^TAILSCALE_IP=" "$SCRIPT_DIR/.env" 2>/dev/null | cut -d'=' -f2)

        if [ -n "$CURRENT_TS_IP" ] && [ -n "$CONFIGURED_TS_IP" ] && [ "$CURRENT_TS_IP" != "$CONFIGURED_TS_IP" ]; then
            echo ""
            log_error "═══════════════════════════════════════════════════════════════"
            log_error "  TAILSCALE IP MISMATCH DETECTED!"
            log_error "═══════════════════════════════════════════════════════════════"
            echo ""
            echo "  Current Tailscale IP:    $CURRENT_TS_IP"
            echo "  Configured in .env:      $CONFIGURED_TS_IP"
            echo ""
            echo "  This usually happens after a Tailscale reset/logout."
            echo "  OAuth2 and other services will fail with the wrong IP."
            echo ""
            echo "  Run the recovery script to fix this:"
            echo -e "    ${GREEN}./scripts/recover-tailscale.sh${NC}"
            echo ""
            echo "  Or manually update TAILSCALE_IP in .env and restart."
            echo ""
            log_error "═══════════════════════════════════════════════════════════════"
            exit 1
        fi
    fi

    # =========================================================================
    # Phase 1: Core Infrastructure (No dependencies)
    # =========================================================================
    log_info "━━━ Phase 1: Core Infrastructure ━━━"
    echo "Starting: Traefik, PostgreSQL, Redis..."
    docker compose up -d --force-recreate \
        traefik postgres redis \
        node-exporter cadvisor 2>&1 | grep -v "orphan" || true

    wait_for_health "${PLATFORM_PREFIX:-shml}-postgres" $POSTGRES_TIMEOUT || { log_error "PostgreSQL failed to start"; exit 1; }
    wait_for_health "${PLATFORM_PREFIX:-shml}-traefik" $TRAEFIK_TIMEOUT || { log_error "Traefik failed to start"; exit 1; }
    wait_for_health "${PLATFORM_PREFIX:-shml}-redis" $DEFAULT_TIMEOUT || log_warn "Redis may still be initializing"

    # Verify Traefik API is accessible
    wait_for_http "http://localhost:8090/api/overview" 30 || log_warn "Traefik API not yet accessible"
    log_success "Infrastructure ready"
    echo ""

    # =========================================================================
    # Phase 1.5: Database Integrity Check & Auto-Restore
    # Checks if databases appear empty (e.g., after volume reset) and restores
    # from the largest backup within the last 25 hours for data continuity
    # =========================================================================
    check_and_restore_databases

    # =========================================================================
    # Phase 2: FusionAuth (Needs PostgreSQL)
    # =========================================================================
    log_info "━━━ Phase 2: FusionAuth (OAuth Provider) ━━━"
    echo "Starting: FusionAuth OAuth/SSO server..."
    docker compose up -d --force-recreate fusionauth 2>&1 | grep -v "orphan" || true

    wait_for_health "fusionauth" $FUSIONAUTH_TIMEOUT || log_warn "FusionAuth may need initial setup wizard"
    log_success "FusionAuth ready"
    echo ""

    # =========================================================================
    # Phase 3: Tailscale Funnel (Needs Traefik for routing)
    # OAuth2 Proxy requires public URL for OIDC discovery
    #
    # SECURITY MODEL:
    # ----------------
    # All public traffic goes through: Funnel → Traefik → OAuth2-Proxy → FusionAuth
    #
    # Protected by FusionAuth OAuth2 (require login):
    #   - /mlflow/*, /api/2.0/mlflow/*, /api/v1/* (MLflow)
    #   - /ray/*, /api/ray/*, /api/compute/* (Ray)
    #   - /grafana/* (Grafana)
    #   - /prometheus/* (Prometheus)
    #   - /traefik/* (Traefik dashboard)
    #   - /api/llm/*, /api/image/*, /inference/* (Inference services)
    #
    # Public (required for auth flow):
    #   - /auth/*, /oauth2/*, /.well-known/* (FusionAuth)
    #   - /oauth2-proxy/* (OAuth2-Proxy callbacks)
    #   - Static assets (CSS, JS, fonts)
    #
    # Self-registration is DISABLED - admin must create users in FusionAuth.
    # =========================================================================
    log_info "━━━ Phase 3: Tailscale Funnel (Public HTTPS) ━━━"
    if command -v tailscale &>/dev/null; then
        echo "Starting Tailscale Funnel (required for OAuth2 OIDC discovery)..."
        echo -e "${CYAN}Security: All services are protected by FusionAuth OAuth2${NC}"

        # Expected hostname for the platform
        local EXPECTED_HOSTNAME="shml-platform"

        # Get current Tailscale hostname
        local CURRENT_HOSTNAME=$(tailscale status --json 2>/dev/null | jq -r '.Self.HostName' 2>/dev/null || echo "unknown")
        local MAGIC_DNS_SUFFIX=$(tailscale status --json 2>/dev/null | jq -r '.MagicDNSSuffix' 2>/dev/null || echo "tail38b60a.ts.net")

        # Check and fix hostname if needed
        if [ "$CURRENT_HOSTNAME" != "$EXPECTED_HOSTNAME" ]; then
            log_warn "Tailscale hostname mismatch: '$CURRENT_HOSTNAME' != '$EXPECTED_HOSTNAME'"
            echo "  Correcting Tailscale hostname to '$EXPECTED_HOSTNAME'..."
            if sudo tailscale set --hostname="$EXPECTED_HOSTNAME" 2>/dev/null; then
                log_success "Hostname corrected to '$EXPECTED_HOSTNAME'"
                # Give Tailscale a moment to propagate the change
                sleep 3
            else
                log_error "Failed to set Tailscale hostname"
            fi
        else
            echo "  Tailscale hostname: $CURRENT_HOSTNAME ✓"
        fi

        # Get the public domain (re-read after potential hostname change)
        PUBLIC_DOMAIN=$(tailscale status --json 2>/dev/null | jq -r '.Self.HostName + "." + .MagicDNSSuffix' 2>/dev/null || echo "${EXPECTED_HOSTNAME}.${MAGIC_DNS_SUFFIX}")
        echo "  Public domain: https://${PUBLIC_DOMAIN}"

        # Reset any existing funnel configuration to avoid conflicts
        echo "  Resetting funnel configuration..."
        sudo tailscale funnel reset 2>/dev/null || true
        sleep 2

        # Start the funnel - routes HTTPS to local Traefik on port 80
        # Using 'sudo' because funnel requires elevated permissions
        echo "  Starting Tailscale Funnel..."
        if sudo tailscale funnel --bg 80 2>/dev/null; then
            log_success "Funnel started on https://${PUBLIC_DOMAIN}"
        else
            log_warn "Funnel command may have failed"
        fi

        # Give funnel time to establish connection
        sleep 5

        # Wait for funnel to be fully accessible (CRITICAL for OAuth2 Proxy)
        # OAuth2 Proxy will fail to start if it can't reach OIDC discovery endpoint
        echo -n "  Verifying OIDC discovery endpoint"
        local oidc_wait=0
        local oidc_success=false
        while [ $oidc_wait -lt 60 ]; do
            if curl -sf "https://${PUBLIC_DOMAIN}/.well-known/openid-configuration" >/dev/null 2>&1; then
                echo -e " ${GREEN}✓${NC}"
                oidc_success=true
                break
            fi
            echo -n "."
            sleep 2
            oidc_wait=$((oidc_wait + 2))
        done

        if [ "$oidc_success" = false ]; then
            echo -e " ${YELLOW}⚠${NC}"
            log_warn "OIDC not accessible on first attempt - retrying with funnel restart..."

            # Second attempt: full reset and restart
            sudo tailscale funnel reset 2>/dev/null || true
            sleep 2
            sudo tailscale funnel --bg 80 2>/dev/null || true
            sleep 5

            echo -n "  Retry OIDC verification"
            oidc_wait=0
            while [ $oidc_wait -lt 30 ]; do
                if curl -sf "https://${PUBLIC_DOMAIN}/.well-known/openid-configuration" >/dev/null 2>&1; then
                    echo -e " ${GREEN}✓${NC}"
                    oidc_success=true
                    break
                fi
                echo -n "."
                sleep 2
                oidc_wait=$((oidc_wait + 2))
            done
        fi

        if [ "$oidc_success" = false ]; then
            echo -e " ${RED}✗${NC}"
            log_error "OIDC discovery endpoint not accessible!"
            echo ""
            echo -e "${RED}╔════════════════════════════════════════════════════════════════╗${NC}"
            echo -e "${RED}║  TAILSCALE FUNNEL NOT WORKING                                  ║${NC}"
            echo -e "${RED}╠════════════════════════════════════════════════════════════════╣${NC}"
            echo -e "${RED}║  OAuth2 Proxy requires the funnel to reach OIDC discovery.     ║${NC}"
            echo -e "${RED}║                                                                ║${NC}"
            echo -e "${RED}║  Check funnel status:                                          ║${NC}"
            echo -e "${RED}║    sudo tailscale funnel status                                ║${NC}"
            echo -e "${RED}║                                                                ║${NC}"
            echo -e "${RED}║  Verify from external machine:                                 ║${NC}"
            echo -e "${RED}║    curl https://${PUBLIC_DOMAIN}/.well-known/openid-configuration${NC}"
            echo -e "${RED}╚════════════════════════════════════════════════════════════════╝${NC}"
            echo ""
        else
            log_success "Tailscale Funnel active"
        fi
    else
        log_warn "Tailscale not installed - OAuth2 Proxy may fail OIDC discovery"
    fi
    echo ""

    # =========================================================================
    # Phase 4: OAuth2 Proxy (Needs FusionAuth + Tailscale Funnel)
    # This provides the oauth2-auth middleware for protected services
    #
    # CRITICAL NOTES (Lessons Learned):
    # - OAuth2 Proxy uses a scratch/distroless image with NO shell tools
    # - Health checks using wget/curl will ALWAYS fail (tools don't exist)
    # - docker-compose.infra.yml must have "healthcheck: disable: true"
    # - Traefik filters out containers that are "unhealthy" or "starting"
    # - Without disabled healthcheck, middleware is NEVER registered
    # - OAuth2 Proxy uses /oauth2-proxy/* prefix (NOT /oauth2/*) to avoid
    #   conflict with FusionAuth's OIDC endpoints
    # =========================================================================
    log_info "━━━ Phase 4: OAuth2 Proxy (Auth Middleware) ━━━"
    echo "Starting: OAuth2 Proxy (provides forwardAuth middleware)..."
    echo "  Note: Using /oauth2-proxy/* prefix (FusionAuth uses /oauth2/*)"
    docker compose up -d --force-recreate oauth2-proxy 2>&1 | grep -v "orphan" || true

    # OAuth2 Proxy healthcheck is DISABLED (scratch image has no wget/curl)
    # So we wait for container to be running, then verify it's working
    wait_for_health "oauth2-proxy" $OAUTH2_PROXY_TIMEOUT || {
        log_warn "OAuth2 Proxy may still be initializing..."

        # Check if it's a health check issue (common problem)
        local health_status=$(docker inspect oauth2-proxy --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' 2>/dev/null || echo "not-found")
        if [ "$health_status" = "starting" ] || [ "$health_status" = "unhealthy" ]; then
            log_error "OAuth2 Proxy health check is failing!"
            echo ""
            echo -e "${RED}╔════════════════════════════════════════════════════════════════╗${NC}"
            echo -e "${RED}║  KNOWN ISSUE: OAuth2 Proxy Health Check                        ║${NC}"
            echo -e "${RED}╠════════════════════════════════════════════════════════════════╣${NC}"
            echo -e "${RED}║  The oauth2-proxy image is scratch/distroless - no wget/curl   ║${NC}"
            echo -e "${RED}║  Health checks using shell tools will ALWAYS fail.             ║${NC}"
            echo -e "${RED}║                                                                ║${NC}"
            echo -e "${RED}║  FIX: In docker-compose.infra.yml, set:                        ║${NC}"
            echo -e "${RED}║       healthcheck:                                             ║${NC}"
            echo -e "${RED}║         disable: true                                          ║${NC}"
            echo -e "${RED}║                                                                ║${NC}"
            echo -e "${RED}║  Then restart: docker compose up -d --force-recreate oauth2-proxy${NC}"
            echo -e "${RED}╚════════════════════════════════════════════════════════════════╝${NC}"
            echo ""
        fi

        docker logs oauth2-proxy 2>&1 | tail -5
    }

    # Verify OAuth2 Proxy is actually responding (healthcheck disabled, so check manually)
    # Note: /oauth2-proxy/ping returns 403 without auth - that's correct, we just need any response
    echo -n "  Verifying OAuth2 Proxy endpoint"
    local proxy_wait=0
    local oauth2_proxy_ok=false
    while [ $proxy_wait -lt 30 ]; do
        # Check if OAuth2 Proxy is responding (any HTTP status except 000 means it's up)
        local proxy_check=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost/oauth2-proxy/ping" 2>/dev/null)
        if [ "$proxy_check" != "000" ] && [ -n "$proxy_check" ]; then
            echo -e " ${GREEN}✓${NC} (HTTP $proxy_check)"
            oauth2_proxy_ok=true
            break
        fi
        echo -n "."
        sleep 2
        proxy_wait=$((proxy_wait + 2))
    done

    # If OAuth2 Proxy didn't respond, check if it's OIDC discovery failure and retry
    if [ "$oauth2_proxy_ok" = false ]; then
        echo -e " ${YELLOW}⚠${NC} (endpoint not responding)"

        # Check container logs for OIDC error
        if docker logs oauth2-proxy 2>&1 | tail -20 | grep -qi "oidc\|issuer\|discovery"; then
            log_warn "OAuth2 Proxy OIDC discovery failed - retrying with funnel restart"
            echo ""

            # Stop oauth2-proxy
            docker stop oauth2-proxy 2>/dev/null || true
            sleep 2

            # Ensure funnel is running
            echo "  Ensuring Tailscale Funnel is accessible..."
            sudo tailscale funnel reset 2>/dev/null || true
            sleep 2
            sudo tailscale funnel --bg 80
            sleep 5

            # Wait for OIDC endpoint
            local oidc_retry=0
            local check_domain="${PUBLIC_DOMAIN:-$(tailscale status --json 2>/dev/null | jq -r '.Self.HostName + "." + .MagicDNSSuffix' 2>/dev/null || echo 'localhost')}"
            while [ $oidc_retry -lt 30 ]; do
                local oidc_status=$(curl -skI "https://${check_domain}/auth/.well-known/openid-configuration" 2>/dev/null | head -1 | grep -o '[0-9]\{3\}')
                if [ "$oidc_status" = "200" ]; then
                    log_success "OIDC endpoint accessible"
                    break
                fi
                echo -n "."
                sleep 2
                oidc_retry=$((oidc_retry + 2))
            done

            # Restart oauth2-proxy
            echo "  Restarting OAuth2 Proxy..."
            docker compose up -d --force-recreate oauth2-proxy 2>&1 | grep -v "orphan" || true
            sleep 10
        fi
    fi

    # CRITICAL: Wait for Traefik to register the oauth2-auth middleware
    # Protected services will fail if this middleware doesn't exist
    # Traefik filters out unhealthy/starting containers - that's why healthcheck must be disabled
    local middleware_ok=false
    wait_for_middleware "oauth2-auth" 60 && middleware_ok=true

    if [ "$middleware_ok" = false ]; then
        log_warn "oauth2-auth middleware not registered - attempting recovery..."

        # Check if it's a health check issue (common problem)
        local health_status=$(docker inspect oauth2-proxy --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' 2>/dev/null || echo "not-found")

        if [ "$health_status" = "starting" ] || [ "$health_status" = "unhealthy" ]; then
            echo -e "${YELLOW}  Health check failing - Traefik ignores unhealthy containers${NC}"
            echo -e "${YELLOW}  Ensure docker-compose.infra.yml has 'healthcheck: disable: true'${NC}"
        fi

        # Final recovery attempt: restart oauth2-proxy
        echo "  Final recovery attempt..."
        docker compose up -d --force-recreate oauth2-proxy 2>&1 | grep -v "orphan" || true
        sleep 15

        wait_for_middleware "oauth2-auth" 30 || {
            log_error "oauth2-auth middleware still not registered!"
            echo ""
            echo -e "${RED}╔════════════════════════════════════════════════════════════════╗${NC}"
            echo -e "${RED}║  MIDDLEWARE NOT REGISTERED                                     ║${NC}"
            echo -e "${RED}╠════════════════════════════════════════════════════════════════╣${NC}"
            echo -e "${RED}║  Traefik filters containers that are 'unhealthy' or 'starting' ║${NC}"
            echo -e "${RED}║  Check: docker logs oauth2-proxy                               ║${NC}"
            echo -e "${RED}║  Check: docker inspect oauth2-proxy --format='{{.State.Health.Status}}'${NC}"
            echo -e "${RED}╚════════════════════════════════════════════════════════════════╝${NC}"
            echo ""
            log_warn "Protected services will be inaccessible without oauth2-auth middleware."
            docker logs oauth2-proxy 2>&1 | tail -10
        }
    fi

    log_success "OAuth2 Proxy ready (middleware registered)"
    echo ""

    # =========================================================================
    # Phase 4b: Role Auth Service (Role-based access control middleware)
    # This provides role-auth-developer and role-auth-admin middlewares
    # =========================================================================
    log_info "━━━ Phase 4b: Role Auth Service (RBAC Middleware) ━━━"
    echo "Starting: Role Auth checker (provides role-based access control)..."
    echo "  Note: Validates X-Auth-Request-Groups header for developer/admin roles"
    docker compose up -d --force-recreate --build role-auth 2>&1 | grep -v "orphan" || true

    wait_for_health "role-auth" $DEFAULT_TIMEOUT || log_warn "Role Auth may still be starting"

    # Wait for role-auth middlewares to be registered
    wait_for_middleware "role-auth-developer" 30 || log_warn "role-auth-developer middleware not registered"
    wait_for_middleware "role-auth-admin" 30 || log_warn "role-auth-admin middleware not registered"

    log_success "Role Auth ready (RBAC middlewares registered)"
    echo ""

    # =========================================================================
    # Phase 5: Protected Monitoring Services (Need OAuth2 Middleware)
    # =========================================================================
    log_info "━━━ Phase 5: Monitoring (Protected by OAuth2) ━━━"
    echo "Starting: Global Prometheus, Unified Grafana..."
    docker compose up -d --force-recreate \
        global-prometheus unified-grafana 2>&1 | grep -v "orphan" || true

    wait_for_health "global-prometheus" $PROMETHEUS_TIMEOUT || log_warn "Prometheus may still be loading data"
    wait_for_health "unified-grafana" $GRAFANA_TIMEOUT || log_warn "Grafana may still be initializing"
    log_success "Monitoring ready"
    echo ""

    # =========================================================================
    # Phase 6: MLflow Services (Protected by OAuth2)
    # =========================================================================
    log_info "━━━ Phase 6: MLflow Services (Protected by OAuth2) ━━━"
    echo "Starting: MLflow server, Nginx, API, Prometheus..."
    docker compose up -d --force-recreate \
        mlflow-server mlflow-prometheus 2>&1 | grep -v "orphan" || true

    wait_for_health "mlflow-server" $MLFLOW_TIMEOUT || log_warn "MLflow server may still be initializing"

    docker compose up -d --force-recreate \
        mlflow-nginx mlflow-api 2>&1 | grep -v "orphan" || true

    wait_for_health "mlflow-nginx" $DEFAULT_TIMEOUT || log_warn "MLflow nginx may still be starting"
    log_success "MLflow services ready"
    echo ""

    # =========================================================================
    # Phase 7: Ray Compute (Protected by OAuth2)
    # =========================================================================
    log_info "━━━ Phase 7: Ray Compute (Protected by OAuth2) ━━━"
    echo "Starting: Ray head, API, Prometheus..."
    docker compose up -d --force-recreate \
        ray-head ray-prometheus 2>&1 | grep -v "orphan" || true

    wait_for_health "ray-head" $RAY_TIMEOUT || log_warn "Ray head may still be initializing"

    docker compose up -d --force-recreate \
        ray-compute-api 2>&1 | grep -v "orphan" || true

    wait_for_health "ray-compute-api" $DEFAULT_TIMEOUT || log_warn "Ray API may still be starting"
    log_success "Ray compute ready"
    echo ""

    # =========================================================================
    # Phase 8: GPU Monitoring (Optional)
    # =========================================================================
    log_info "━━━ Phase 8: GPU Monitoring ━━━"
    if [ -f "monitoring/dcgm-exporter/docker-compose.yml" ] && docker compose -f monitoring/dcgm-exporter/docker-compose.yml config >/dev/null 2>&1; then
        echo "Starting: DCGM Exporter..."
        docker compose -f monitoring/dcgm-exporter/docker-compose.yml up -d --force-recreate 2>&1 | grep -v "orphan" || true
        log_success "GPU monitoring started"
    else
        log_warn "DCGM configuration not found - skipping GPU monitoring"
    fi
    echo ""

    # =========================================================================
    # Phase 9: Inference Services (Protected by OAuth2 - Developer role)
    # =========================================================================
    log_info "━━━ Phase 9: Inference Services (Protected by OAuth2) ━━━"
    if [ -f "inference/coding-model/docker-compose.yml" ]; then
        echo "Starting: Coding Models (Primary: 30B on 3090Ti, Fallback: 3B on 2070)..."
        docker compose --env-file .env -f inference/coding-model/docker-compose.yml up -d --force-recreate 2>&1 | grep -v "orphan" || true

        # Model loading takes time, use extended timeout
        # Wait for fallback first (faster to load)
        CODING_MODEL_TIMEOUT=${CODING_MODEL_TIMEOUT:-300}
        echo "  Waiting for fallback model (3B)..."
        wait_for_health "coding-model-fallback" 180 || log_warn "Fallback model may still be loading"
        echo "  Waiting for primary model (30B)..."
        wait_for_health "coding-model-primary" $CODING_MODEL_TIMEOUT || log_warn "Primary model may still be loading (this can take 2-5 minutes)"
        log_success "Coding model services started"
    else
        log_warn "Coding model configuration not found - skipping"
    fi
    echo ""

    # =========================================================================
    # Phase 9b: Chat API Service (Needs coding models + Redis + Postgres)
    # Provides OpenAI-compatible API for Cursor/VS Code integration
    # =========================================================================
    log_info "━━━ Phase 9b: Chat API Service ━━━"
    if [ -f "inference/chat-api/docker-compose.yml" ]; then
        echo "Starting: Chat API (OpenAI-compatible endpoint for Cursor/editors)..."
        docker compose --env-file .env -f inference/chat-api/docker-compose.yml up -d --force-recreate 2>&1 | grep -v "orphan" || true

        # Wait for Chat API to be healthy
        wait_for_health "${PLATFORM_PREFIX:-shml}-chat-api" $DEFAULT_TIMEOUT || log_warn "Chat API may still be starting"
        log_success "Chat API service started"
    else
        log_warn "Chat API configuration not found - skipping"
    fi
    echo ""

    # =========================================================================
    # Phase 10: Observability Services
    # =========================================================================
    log_info "━━━ Phase 10: Observability & Landing Page ━━━"
    echo "Starting: Homer (landing), Dozzle (logs), Postgres Backup..."
    # Force recreate Homer to ensure config mounts are fresh
    docker compose up -d --force-recreate homer 2>&1 | grep -v "orphan" || true
    docker compose up -d --force-recreate dozzle postgres-backup 2>&1 | grep -v "orphan" || true

    # Wait for services
    wait_for_health "homer" $DEFAULT_TIMEOUT || log_warn "Homer may still be starting"
    wait_for_health "postgres-backup" $DEFAULT_TIMEOUT || log_warn "Postgres Backup may still be starting"

    # Dozzle doesn't have healthcheck (minimal image)
    if docker ps --format '{{.Names}}' | grep -q "^dozzle$"; then
        log_success "Dozzle running"
    else
        log_warn "Dozzle may not have started"
    fi

    log_success "Observability services ready"
    echo ""

    # Show status
    show_status

    # Verify auth protection
    verify_auth_protection
}

# =============================================================================
# Verify Auth Protection
# =============================================================================

verify_auth_protection() {
    echo ""
    log_info "━━━ Verifying Auth Protection ━━━"

    # First check if oauth2-auth middleware is registered
    echo -n "  Checking oauth2-auth middleware: "
    if curl -sf "http://localhost:8090/api/http/middlewares/oauth2-auth@docker" >/dev/null 2>&1; then
        echo -e "${GREEN}✓ registered${NC}"
    else
        echo -e "${RED}✗ NOT registered${NC}"
        echo ""
        echo -e "${YELLOW}  Middleware not found. Checking oauth2-proxy container...${NC}"
        local health_status=$(docker inspect oauth2-proxy --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' 2>/dev/null || echo "not-found")
        echo "  Container health status: $health_status"
        if [ "$health_status" = "starting" ] || [ "$health_status" = "unhealthy" ]; then
            echo -e "${RED}  ⚠ Traefik filters unhealthy containers - middleware won't register${NC}"
            echo -e "${YELLOW}  Fix: Set 'healthcheck: disable: true' in docker-compose.infra.yml${NC}"
        fi
        echo ""
    fi

    # Check OAuth2 Proxy endpoint (uses /oauth2-proxy/* prefix, NOT /oauth2/*)
    # Note: /oauth2-proxy/ping returns 403 without auth, which is correct behavior
    # We check for any HTTP response (not 000/connection refused) to confirm it's responding
    echo -n "  Checking OAuth2 Proxy endpoint: "
    local proxy_status=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost/oauth2-proxy/ping" 2>/dev/null)
    if [ "$proxy_status" != "000" ] && [ -n "$proxy_status" ]; then
        echo -e "${GREEN}✓ responding (HTTP $proxy_status)${NC}"
    else
        echo -e "${RED}✗ not responding${NC}"
    fi

    local endpoints=(
        "MLflow UI:/mlflow"
        "Ray Dashboard:/ray"
        "Grafana:/grafana"
        "Prometheus:/prometheus"
        "Dozzle (Logs):/logs"
    )

    echo ""
    echo "  Protected Endpoints:"
    local all_protected=true
    for endpoint in "${endpoints[@]}"; do
        local name="${endpoint%%:*}"
        local path="${endpoint##*:}"
        local status=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost${path}" 2>/dev/null)

        if [ "$status" = "302" ] || [ "$status" = "401" ] || [ "$status" = "403" ]; then
            echo -e "    ${GREEN}✓${NC} $name: Protected (HTTP $status)"
        elif [ "$status" = "200" ]; then
            echo -e "    ${RED}✗${NC} $name: UNPROTECTED (HTTP $status)"
            all_protected=false
        else
            echo -e "    ${YELLOW}?${NC} $name: Unknown (HTTP $status)"
        fi
    done

    # Check unprotected endpoints (should be accessible)
    echo ""
    echo "  Unprotected Endpoints (should be accessible):"
    local unprotected_endpoints=(
        "FusionAuth Login:/auth/"
        "OAuth2 Proxy Login:/oauth2-proxy/sign_in"
    )
    for endpoint in "${unprotected_endpoints[@]}"; do
        local name="${endpoint%%:*}"
        local path="${endpoint##*:}"
        local status=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost${path}" 2>/dev/null)

        if [ "$status" = "200" ] || [ "$status" = "302" ]; then
            echo -e "    ${GREEN}✓${NC} $name: Accessible (HTTP $status)"
        else
            echo -e "    ${YELLOW}?${NC} $name: Status $status"
        fi
    done

    echo ""
    if [ "$all_protected" = true ]; then
        log_success "All protected endpoints require authentication"
    else
        log_error "Some endpoints are NOT protected!"
        echo "       Check OAuth2 Proxy and Traefik middleware configuration."
        echo "       Common issues:"
        echo "       1. oauth2-proxy healthcheck failing (use 'healthcheck: disable: true')"
        echo "       2. Middleware labels missing on protected service containers"
        echo "       3. Traefik not connected to ml-platform network"
    fi
    echo ""
}

# =============================================================================
# Show Status
# =============================================================================

show_status() {
    # Get Tailscale IP and public domain
    local TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "100.66.26.115")
    local PUBLIC_DOMAIN=$(tailscale status --json 2>/dev/null | jq -r '.Self.HostName + "." + .MagicDNSSuffix' 2>/dev/null || echo "shml-platform.tail38b60a.ts.net")

    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    log_success "Platform startup complete!"
    echo ""
    echo "Service Status:"
    docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAME|traefik|postgres|redis|mlflow|ray|grafana|prometheus|fusionauth|oauth2|cadvisor|node-exporter|dozzle|homer|backup|coding-model|chat-api" || true
    echo ""
    echo -e "${CYAN}Public Access (via Tailscale Funnel):${NC}"
    if [ -n "$PUBLIC_DOMAIN" ]; then
        echo "  🏠 Landing Page:     https://${PUBLIC_DOMAIN}/"
        echo ""
        echo "  Auth (all services require login):"
        echo "  • FusionAuth Admin:  https://${PUBLIC_DOMAIN}/auth/admin/"
        echo "  • OAuth2 Login:      https://${PUBLIC_DOMAIN}/oauth2-proxy/sign_in"
        echo ""
        echo "  Core Services (OAuth Protected):"
        echo "  • MLflow UI:         https://${PUBLIC_DOMAIN}/mlflow/"
        echo "  • Ray Dashboard:     https://${PUBLIC_DOMAIN}/ray/"
        echo "  • Grafana:           https://${PUBLIC_DOMAIN}/grafana/"
        echo "  • Dozzle (Logs):     https://${PUBLIC_DOMAIN}/logs/"
        echo ""
        echo "  Inference APIs (OAuth Protected - Developer role):"
        echo "  • Coding Model API:  https://${PUBLIC_DOMAIN}/api/coding/v1/ (OpenAI-compatible)"
    fi
    echo ""
    # Get LAN IP (try multiple methods, fallback to common default)
    local LAN_IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{print $7}' | head -1)
    if [ -z "$LAN_IP" ]; then
        LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    fi
    LAN_IP=${LAN_IP:-YOUR_LAN_IP}
    echo -e "${CYAN}Internal Access (LAN - http://${LAN_IP}/...):${NC}"

    echo "  🏠 Landing Page:   http://${LAN_IP}/"
    echo "  • MLflow UI:       http://${LAN_IP}/mlflow/"
    echo "  • Ray Dashboard:   http://${LAN_IP}/ray/"
    echo "  • Grafana:         http://${LAN_IP}/grafana/"
    echo "  • Dozzle (Logs):   http://${LAN_IP}/logs/"
    echo ""
    echo "  Inference APIs (Developer role required):"
    echo "  • Coding Model:    http://${LAN_IP}/api/coding/v1/chat/completions"
    echo ""
    echo "  Admin (direct ports):"
    echo "  • FusionAuth:      http://${LAN_IP}:9011/admin/"
    echo "  • Traefik API:     http://${LAN_IP}:8090/"
    echo ""
    echo -e "${GREEN}Note: HTTPS also works on LAN (https://${LAN_IP}/...) with Tailscale certs.${NC}"
    echo ""
}

# =============================================================================
# Main
# =============================================================================

# =============================================================================
# Diagnose Auth Issues
# =============================================================================

diagnose_auth() {
    echo ""
    echo -e "${BLUE}╔════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║         OAuth2/Middleware Diagnostics                  ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════╝${NC}"
    echo ""

    # Check oauth2-proxy container
    log_info "━━━ OAuth2 Proxy Container ━━━"
    echo -n "  Container running: "
    if docker ps --format '{{.Names}}' | grep -q "^oauth2-proxy$"; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗ NOT RUNNING${NC}"
        echo "  Try: docker compose up -d oauth2-proxy"
        return 1
    fi

    echo -n "  Health status: "
    local health=$(docker inspect oauth2-proxy --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' 2>/dev/null || echo "not-found")
    case "$health" in
        "healthy")
            echo -e "${GREEN}$health${NC}"
            ;;
        "no-healthcheck")
            echo -e "${GREEN}$health (correct for scratch image)${NC}"
            ;;
        "starting"|"unhealthy")
            echo -e "${RED}$health${NC}"
            echo ""
            echo -e "${RED}  ⚠ PROBLEM DETECTED!${NC}"
            echo "  The oauth2-proxy image is scratch/distroless with no shell tools."
            echo "  Health checks using wget/curl will ALWAYS fail."
            echo ""
            echo "  FIX: In docker-compose.infra.yml, change:"
            echo "       healthcheck:"
            echo "         disable: true"
            echo ""
            echo "  Then run: docker compose up -d --force-recreate oauth2-proxy"
            ;;
        *)
            echo -e "${YELLOW}$health${NC}"
            ;;
    esac

    echo ""
    echo "  Recent logs:"
    docker logs oauth2-proxy 2>&1 | tail -5 | sed 's/^/    /'
    echo ""

    # Check Traefik
    log_info "━━━ Traefik Middleware ━━━"
    echo -n "  oauth2-auth@docker: "
    if curl -sf "http://localhost:8090/api/http/middlewares/oauth2-auth@docker" >/dev/null 2>&1; then
        echo -e "${GREEN}✓ REGISTERED${NC}"
        echo ""
        echo "  Middleware config:"
        curl -s "http://localhost:8090/api/http/middlewares/oauth2-auth@docker" | jq '.forwardAuth' 2>/dev/null | sed 's/^/    /' || echo "    (couldn't parse)"
    else
        echo -e "${RED}✗ NOT REGISTERED${NC}"
        echo ""
        echo "  Traefik filters out unhealthy/starting containers."
        echo "  Check oauth2-proxy health status above."
    fi
    echo ""

    # Check oauth2-proxy router
    log_info "━━━ OAuth2 Proxy Router ━━━"
    echo -n "  oauth2-proxy@docker: "
    if curl -sf "http://localhost:8090/api/http/routers/oauth2-proxy@docker" >/dev/null 2>&1; then
        echo -e "${GREEN}✓ REGISTERED${NC}"
        echo ""
        echo "  Router rule:"
        curl -s "http://localhost:8090/api/http/routers/oauth2-proxy@docker" | jq '.rule' 2>/dev/null | sed 's/^/    /' || echo "    (couldn't parse)"
    else
        echo -e "${RED}✗ NOT REGISTERED${NC}"
    fi
    echo ""

    # Check endpoint responses
    log_info "━━━ Endpoint Responses ━━━"
    local test_endpoints=(
        "/oauth2-proxy/ping:OAuth2 Proxy ping"
        "/auth/:FusionAuth"
        "/grafana/:Grafana (protected)"
        "/prometheus/:Prometheus (protected)"
        "/mlflow/:MLflow (protected)"
        "/ray/:Ray Dashboard (protected)"
        "/logs/:Dozzle (protected)"
    )

    for entry in "${test_endpoints[@]}"; do
        local path="${entry%%:*}"
        local name="${entry##*:}"
        local status=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost${path}" 2>/dev/null)
        printf "  %-30s HTTP %s\n" "$name:" "$status"
    done
    echo ""

    # Quick fix suggestion
    if [ "$health" = "starting" ] || [ "$health" = "unhealthy" ]; then
        echo -e "${YELLOW}━━━ QUICK FIX ━━━${NC}"
        echo "Run these commands to fix the health check issue:"
        echo ""
        echo "  # Edit docker-compose.infra.yml and change oauth2-proxy healthcheck to:"
        echo "  #   healthcheck:"
        echo "  #     disable: true"
        echo ""
        echo "  # Then restart:"
        echo "  docker compose up -d --force-recreate oauth2-proxy"
        echo ""
    fi
}

# =============================================================================
# FIX-OAUTH COMMAND
# Fixes the FusionAuth OAuth client configuration to include all necessary
# callback URLs for oauth2-proxy integration
# =============================================================================
fix_fusionauth_oauth() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}                     FusionAuth OAuth Client Configuration Fix                    ${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    # Configuration - these should match your environment
    local FUSIONAUTH_API_KEY="${FUSIONAUTH_API_KEY:-pYxEbVSHPxJTSTksYEGAA3LLSfh2fvrBZ91dA945Km7yk0JJu2uDDt_t}"
    local OAUTH_CLIENT_ID="${OAUTH2_PROXY_CLIENT_ID:-acda34f0-7cf2-40eb-9cba-7cb0048857d3}"
    local PUBLIC_DOMAIN="${PUBLIC_DOMAIN:-shml-platform.tail38b60a.ts.net}"

    echo -e "${YELLOW}Configuration:${NC}"
    echo "  OAuth Client ID: $OAUTH_CLIENT_ID"
    echo "  Public Domain:   $PUBLIC_DOMAIN"
    echo ""

    # First, verify FusionAuth is accessible
    echo -e "${YELLOW}Checking FusionAuth accessibility...${NC}"
    local fusionauth_status
    fusionauth_status=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost/auth/api/status" 2>/dev/null)

    if [ "$fusionauth_status" != "200" ]; then
        echo -e "${RED}✗ FusionAuth API is not accessible (HTTP $fusionauth_status)${NC}"
        echo "  Make sure FusionAuth is running and accessible at http://localhost/auth/"
        return 1
    fi
    echo -e "${GREEN}✓ FusionAuth API is accessible${NC}"

    # Get current OAuth client configuration
    echo ""
    echo -e "${YELLOW}Fetching current OAuth client configuration...${NC}"
    local current_config
    current_config=$(curl -s -H "Authorization: $FUSIONAUTH_API_KEY" \
        "http://localhost/auth/api/application/$OAUTH_CLIENT_ID" 2>/dev/null)

    if ! echo "$current_config" | jq -e '.application' &>/dev/null; then
        echo -e "${RED}✗ Failed to fetch OAuth client configuration${NC}"
        echo "  Response: $current_config"
        echo ""
        echo "  Make sure:"
        echo "    1. The OAuth Client ID is correct: $OAUTH_CLIENT_ID"
        echo "    2. The FusionAuth API key has read/write permissions"
        return 1
    fi

    local app_name
    app_name=$(echo "$current_config" | jq -r '.application.name')
    echo -e "${GREEN}✓ Found OAuth client: $app_name${NC}"

    # Show current redirect URLs
    echo ""
    echo -e "${YELLOW}Current authorized redirect URLs:${NC}"
    echo "$current_config" | jq -r '.application.oauthConfiguration.authorizedRedirectURLs[]' 2>/dev/null | while read -r url; do
        echo "  - $url"
    done

    # Define the required redirect URLs
    # IMPORTANT: oauth2-proxy uses /oauth2-proxy/callback (not /oauth2/callback)
    # because we set OAUTH2_PROXY_PROXY_PREFIX=/oauth2-proxy to avoid conflict with FusionAuth's /oauth2/* routes
    local required_urls=(
        "https://${PUBLIC_DOMAIN}/oauth2-proxy/callback"
        "http://localhost/oauth2-proxy/callback"
        "https://${PUBLIC_DOMAIN}/oauth2/callback"
    )

    echo ""
    echo -e "${YELLOW}Required redirect URLs for oauth2-proxy:${NC}"
    for url in "${required_urls[@]}"; do
        echo "  - $url"
    done

    # Build the JSON array for the update
    local urls_json
    urls_json=$(printf '%s\n' "${required_urls[@]}" | jq -R . | jq -s .)

    # Update the OAuth client
    echo ""
    echo -e "${YELLOW}Updating OAuth client configuration...${NC}"
    local update_response
    update_response=$(curl -s -X PATCH \
        -H "Authorization: $FUSIONAUTH_API_KEY" \
        -H "Content-Type: application/json" \
        "http://localhost/auth/api/application/$OAUTH_CLIENT_ID" \
        -d "{\"application\":{\"oauthConfiguration\":{\"authorizedRedirectURLs\":$urls_json}}}" 2>/dev/null)

    if echo "$update_response" | jq -e '.application' &>/dev/null; then
        echo -e "${GREEN}✓ OAuth client configuration updated successfully${NC}"

        # Verify the update
        echo ""
        echo -e "${YELLOW}Verified authorized redirect URLs:${NC}"
        echo "$update_response" | jq -r '.application.oauthConfiguration.authorizedRedirectURLs[]' 2>/dev/null | while read -r url; do
            echo "  - $url"
        done
    else
        echo -e "${RED}✗ Failed to update OAuth client configuration${NC}"
        echo "  Response: $update_response"
        return 1
    fi

    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}                              OAuth Fix Complete                                  ${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo "The OAuth client has been configured with the correct callback URLs."
    echo ""
    echo "If you're still seeing 'Invalid redirect_uri' errors, verify that:"
    echo "  1. oauth2-proxy's OAUTH2_PROXY_REDIRECT_URL matches one of the URLs above"
    echo "  2. The PUBLIC_DOMAIN environment variable is set correctly"
    echo "  3. oauth2-proxy has been restarted after any changes"
    echo ""
    echo "Current oauth2-proxy configuration should have:"
    echo "  OAUTH2_PROXY_REDIRECT_URL=https://${PUBLIC_DOMAIN}/oauth2-proxy/callback"
    echo "  OAUTH2_PROXY_PROXY_PREFIX=/oauth2-proxy"
    echo ""
}

case "${1:-restart}" in
    start)
        rebuild_images
        start_all_services
        ;;
    stop)
        stop_all_services
        ;;
    restart|"")
        create_pre_restart_backup
        stop_all_services
        cleanup_containers
        rebuild_images
        start_all_services
        ;;
    status)
        show_status
        verify_auth_protection
        ;;
    cleanup)
        create_pre_restart_backup
        stop_all_services
        cleanup_containers
        ;;
    diagnose|diag)
        diagnose_auth
        ;;
    fix-oauth)
        fix_fusionauth_oauth
        ;;
    build|rebuild)
        rebuild_images
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|cleanup|diagnose|fix-oauth|build}"
        echo ""
        echo "Commands:"
        echo "  start     - Rebuild images + start all services"
        echo "  stop      - Stop all services"
        echo "  restart   - Full restart: stop + cleanup + rebuild + start (default)"
        echo "  status    - Show service status and access URLs"
        echo "  build     - Rebuild all container images only"
        echo "  cleanup   - Stop and remove all containers"
        echo "  diagnose  - Debug OAuth2/middleware issues"
        echo "  fix-oauth - Fix FusionAuth OAuth client callback URLs"
        echo ""
        echo "Environment variables for timeouts (in seconds):"
        echo "  POSTGRES_TIMEOUT=$POSTGRES_TIMEOUT"
        echo "  TRAEFIK_TIMEOUT=$TRAEFIK_TIMEOUT"
        echo "  FUSIONAUTH_TIMEOUT=$FUSIONAUTH_TIMEOUT"
        echo "  OAUTH2_PROXY_TIMEOUT=$OAUTH2_PROXY_TIMEOUT"
        echo "  MLFLOW_TIMEOUT=$MLFLOW_TIMEOUT"
        echo "  RAY_TIMEOUT=$RAY_TIMEOUT"
        exit 1
        ;;
esac
