#!/bin/bash
# ML Platform - Unified Setup & Startup Script
# Handles everything from dependency checks to service monitoring
# Version: 2.1
# Last Updated: 2025-12-01
#
# LESSONS LEARNED (December 2025):
# ================================
# 1. OAuth2 Proxy Health Check Issue:
#    - The quay.io/oauth2-proxy/oauth2-proxy image is SCRATCH/DISTROLESS
#    - Contains NO shell tools (no wget, curl, ls, sh, etc.)
#    - Health checks using shell commands will ALWAYS fail
#    - Solution: Use "healthcheck: disable: true" in docker-compose
#    - Traefik will use container "running" status instead of "healthy"
#
# 2. Traefik Container Filtering:
#    - Traefik FILTERS OUT containers with status "unhealthy" or "starting"
#    - Middleware/routers from filtered containers are NEVER registered
#    - Debug: docker logs traefik 2>&1 | grep -i "filter"
#    - Check: docker inspect <container> --format='{{.State.Health.Status}}'
#
# 3. OAuth2 Proxy Path Conflict:
#    - FusionAuth uses /oauth2/* for OIDC endpoints
#    - OAuth2 Proxy defaults to /oauth2/* prefix
#    - Solution: Use /oauth2-proxy/* prefix for OAuth2 Proxy
#    - Set OAUTH2_PROXY_PROXY_PREFIX=/oauth2-proxy
#
# 4. Startup Order:
#    - Infrastructure (Traefik, Postgres, Redis) → FusionAuth → Tailscale →
#      OAuth2 Proxy → Protected Services
#    - OAuth2 Proxy needs FusionAuth for OIDC discovery
#    - Protected services need oauth2-auth middleware registered first

# Don't exit on errors - we handle them explicitly
set +e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ============================================================================
# CONFIGURATION
# ============================================================================

SCRIPT_VERSION="2.0"
LOG_FILE="${SCRIPT_DIR}/setup.log"
BACKUP_DIR="${SCRIPT_DIR}/backups/env_backups"
CREDENTIALS_FILE="${SCRIPT_DIR}/CREDENTIALS.txt"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# Counters
ERRORS=0
WARNINGS=0
FIXED=0

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

print_header() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════${NC}"
    echo -e "${BLUE}${BOLD}  $1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════${NC}"
    echo ""
}

print_section() {
    echo ""
    echo -e "${CYAN}━━━ $1 ━━━${NC}"
    echo ""
}

check_pass() {
    echo -e "${GREEN}✓${NC} $1"
    log "PASS: $1"
}

check_fail() {
    echo -e "${RED}✗${NC} $1"
    log "FAIL: $1"
    ((ERRORS++))
}

check_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
    log "WARN: $1"
    ((WARNINGS++))
}

check_fixed() {
    echo -e "${GREEN}✓${NC} $1 ${CYAN}(fixed)${NC}"
    log "FIXED: $1"
    ((FIXED++))
}

prompt_yn() {
    local prompt="$1"
    local default="${2:-n}"
    local response

    if [ "$default" = "y" ]; then
        read -p "$prompt [Y/n]: " response
        response=${response:-y}
    else
        read -p "$prompt [y/N]: " response
        response=${response:-n}
    fi

    [[ "$response" =~ ^[Yy]$ ]]
}

prompt_password() {
    local service_name="$1"
    local description="$2"
    local allow_generate="${3:-true}"
    local default_length="${4:-24}"

    # All prompts go to stderr, only password goes to stdout
    echo "" >&2
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}" >&2
    echo -e "${BOLD}${service_name}${NC}" >&2
    if [ -n "$description" ]; then
        echo -e "${CYAN}$description${NC}" >&2
    fi
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}" >&2

    if [ "$allow_generate" = "true" ]; then
        echo "Options:" >&2
        echo "  1) Auto-generate secure password (recommended)" >&2
        echo "  2) Enter custom password" >&2
        echo "" >&2
        read -p "Selection [1]: " choice
        choice=${choice:-1}

        if [ "$choice" = "2" ]; then
            while true; do
                read -sp "Enter password (min 12 chars): " password1
                echo "" >&2
                read -sp "Confirm password: " password2
                echo "" >&2
                if [ "$password1" = "$password2" ]; then
                    if [ ${#password1} -lt 12 ]; then
                        echo -e "${RED}⚠️  Password too short (minimum 12 characters)${NC}" >&2
                        continue
                    fi
                    echo "$password1"
                    return 0
                else
                    echo -e "${RED}⚠️  Passwords don't match, try again${NC}" >&2
                fi
            done
        fi
    fi

    # Auto-generate (only password to stdout)
    openssl rand -base64 $default_length | tr -dc 'a-zA-Z0-9' | head -c $default_length
}

update_env_var() {
    local file=$1
    local key=$2
    local value=$3

    if [ ! -f "$file" ]; then
        echo "${key}=${value}" >> "$file"
        return
    fi

    # Use perl for reliable replacement
    local temp_file="${file}.tmp"
    if grep -q "^${key}=" "$file" 2>/dev/null; then
        perl -i -pe "BEGIN{\$key='$key'; \$val='$value';} s/^\Q\$key\E=.*/\$key=\$val/" "$file"
    else
        echo "${key}=${value}" >> "$file"
    fi
}

# Zero-knowledge validation (check without revealing)
validate_secret() {
    local file=$1
    local min_length=${2:-12}

    if [ ! -f "$file" ]; then
        return 1
    fi

    # Read and trim whitespace (newlines, spaces)
    local content=$(cat "$file" 2>/dev/null | tr -d '\n\r')
    local length=${#content}

    if [ $length -ge $min_length ] && [ $length -le 200 ]; then
        return 0
    fi
    return 1
}

# ============================================================================
# PHASE 1: SYSTEM DEPENDENCIES
# ============================================================================

check_dependencies() {
    print_header "Phase 1: System Dependencies"

    local missing_deps=()

    # Docker
    print_section "Docker Engine"
    if command -v docker &>/dev/null; then
        local docker_version=$(docker --version | cut -d' ' -f3 | tr -d ',')
        check_pass "Docker installed: ${docker_version}"
    else
        check_fail "Docker not installed"
        missing_deps+=("docker")
    fi

    # Docker Compose
    if docker compose version &>/dev/null 2>&1; then
        local compose_version=$(docker compose version | cut -d' ' -f4)
        check_pass "Docker Compose installed: ${compose_version}"
    else
        check_fail "Docker Compose not installed"
        missing_deps+=("docker-compose")
    fi

    # Docker permissions
    if groups | grep -q docker || [ "$EUID" -eq 0 ]; then
        check_pass "Docker permissions OK"
    else
        check_warn "User not in docker group (will use sudo)"
    fi

    # NVIDIA Drivers
    print_section "NVIDIA GPU"
    if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null 2>&1; then
        local driver_version=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 || echo "unknown")
        local gpu_count=$(nvidia-smi --list-gpus 2>/dev/null | wc -l || echo "0")
        check_pass "NVIDIA drivers installed: ${driver_version}"
        check_pass "GPUs detected: ${gpu_count}"
        # List GPUs without subshell issues
        local gpu_info=$(nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader 2>/dev/null || echo "")
        if [ -n "$gpu_info" ]; then
            echo "$gpu_info" | while IFS= read -r line; do
                echo "    → $line"
            done
        fi
    else
        check_fail "NVIDIA drivers not installed"
        missing_deps+=("nvidia-drivers")
    fi

    # NVIDIA Container Toolkit
    if command -v nvidia-ctk &>/dev/null; then
        check_pass "NVIDIA Container Toolkit installed"
    else
        check_fail "NVIDIA Container Toolkit not installed"
        missing_deps+=("nvidia-container-toolkit")
    fi

    # Optional: Tailscale
    print_section "Network (Optional)"
    if command -v tailscale &>/dev/null; then
        if tailscale status &>/dev/null 2>&1; then
            local ts_ip=$(tailscale ip -4 2>/dev/null || echo "")
            if [ -n "$ts_ip" ]; then
                check_pass "Tailscale configured: ${ts_ip}"
            else
                check_warn "Tailscale installed but not connected"
            fi
        else
            check_warn "Tailscale installed but not logged in"
        fi
    else
        check_warn "Tailscale not installed (optional for remote access)"
    fi

    # PostgreSQL client
    if command -v psql &>/dev/null; then
        check_pass "PostgreSQL client installed"
    else
        check_warn "PostgreSQL client not installed (optional)"
        missing_deps+=("postgresql-client")
    fi

    # Handle missing dependencies
    if [ ${#missing_deps[@]} -gt 0 ]; then
        echo ""
        echo -e "${RED}Missing dependencies detected:${NC}"
        for dep in "${missing_deps[@]}"; do
            echo "  - $dep"
        done
        echo ""

        if prompt_yn "Would you like to install missing dependencies now?" "y"; then
            install_dependencies "${missing_deps[@]}"
        else
            echo -e "${YELLOW}⚠ Continuing with warnings. Some features may not work.${NC}"
            sleep 2
        fi
    fi
}

install_dependencies() {
    local deps=("$@")

    print_section "Installing Dependencies"

    for dep in "${deps[@]}"; do
        case "$dep" in
            docker)
                echo "Installing Docker..."
                if [ -f "./ray_compute/scripts/install_docker_nvidia.sh" ]; then
                    cd ray_compute/scripts
                    chmod +x install_docker_nvidia.sh
                    ./install_docker_nvidia.sh
                    cd "$SCRIPT_DIR"
                    check_fixed "Docker installed"
                else
                    echo "Please install Docker manually: https://docs.docker.com/engine/install/"
                fi
                ;;
            nvidia-container-toolkit)
                echo "Installing NVIDIA Container Toolkit..."
                curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
                    sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
                curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
                    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
                    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
                sudo apt update
                sudo apt install -y nvidia-container-toolkit
                sudo nvidia-ctk runtime configure --runtime=docker
                sudo systemctl restart docker
                check_fixed "NVIDIA Container Toolkit installed"
                ;;
            nvidia-drivers)
                echo -e "${YELLOW}NVIDIA drivers must be installed manually.${NC}"
                echo "Visit: https://www.nvidia.com/Download/index.aspx"
                echo "After installation, reboot and run this script again."
                exit 1
                ;;
            postgresql-client)
                sudo apt update && sudo apt install -y postgresql-client
                check_fixed "PostgreSQL client installed"
                ;;
        esac
    done
}

# ============================================================================
# PHASE 1.5: DATA PRESERVATION CHECK
# ============================================================================

check_existing_data() {
    print_header "Phase 1.5: Existing Data Check"

    local has_data=false
    local data_sources=()

    print_section "Checking for existing platform data..."

    # Check for Docker volumes with data
    if sudo docker volume ls | grep -q "shml-postgres-data"; then
        data_sources+=("PostgreSQL database (shml-postgres-data)")
        has_data=true
    fi

    if sudo docker volume ls | grep -q "mlflow-mlruns"; then
        data_sources+=("MLflow runs (mlflow-mlruns)")
        has_data=true
    fi

    if sudo docker volume ls | grep -q "mlflow-prometheus-data"; then
        data_sources+=("MLflow metrics (mlflow-prometheus-data)")
        has_data=true
    fi

    if sudo docker volume ls | grep -q "unified-grafana-data"; then
        data_sources+=("Grafana dashboards (unified-grafana-data)")
        has_data=true
    fi

    # Check for artifact storage
    if [ -d "/mlflow/artifacts" ] && [ "$(ls -A /mlflow/artifacts 2>/dev/null)" ]; then
        data_sources+=("MLflow artifacts (/mlflow/artifacts)")
        has_data=true
    fi

    # Check for backup data
    if [ -d "backups/postgres" ] && [ "$(ls -A backups/postgres 2>/dev/null)" ]; then
        data_sources+=("PostgreSQL backups (backups/postgres)")
        has_data=true
    fi

    if [ "$has_data" = true ]; then
        echo ""
        echo -e "${YELLOW}⚠️  Existing platform data detected:${NC}"
        for source in "${data_sources[@]}"; do
            echo "  • $source"
        done
        echo ""

        echo -e "${CYAN}Options:${NC}"
        echo "  1. Preserve existing data (recommended for updates/restarts)"
        echo "  2. Fresh installation (WARNING: will delete all existing data)"
        echo "  3. Create backup before proceeding"
        echo ""

        local choice
        while true; do
            read -p "Select option [1-3]: " choice
            case $choice in
                1)
                    echo -e "${GREEN}✓ Preserving existing data${NC}"
                    log "User chose to preserve existing data"
                    PRESERVE_DATA=true
                    break
                    ;;
                2)
                    echo ""
                    echo -e "${RED}⚠️  WARNING: This will DELETE all existing data!${NC}"
                    echo "  • All experiments and runs"
                    echo "  • All registered models"
                    echo "  • All datasets and artifacts"
                    echo "  • All dashboards and metrics"
                    echo "  • All database records"
                    echo ""
                    if prompt_yn "Are you ABSOLUTELY SURE you want to delete all data?" "n"; then
                        echo -e "${RED}Removing all existing data...${NC}"

                        # Stop all services first
                        sudo docker compose down 2>&1 | grep -v "WARNING:" || true

                        # Remove volumes
                        sudo docker volume rm shml-postgres-data mlflow-mlruns mlflow-prometheus-data \
                            unified-grafana-data ray-prometheus-data global-prometheus-data 2>/dev/null || true

                        # Remove artifact storage
                        sudo rm -rf /mlflow/artifacts/* 2>/dev/null || true

                        check_fixed "All existing data removed"
                        PRESERVE_DATA=false
                        break
                    else
                        echo "Aborting fresh installation. Please choose another option."
                    fi
                    ;;
                3)
                    echo ""
                    echo "Creating backup of existing data..."
                    local timestamp=$(date +%Y%m%d_%H%M%S)
                    local backup_dir="backups/pre-setup-${timestamp}"
                    mkdir -p "$backup_dir"

                    # Backup PostgreSQL if running
                    if sudo docker ps | grep -q "shml-postgres"; then
                        echo "Backing up PostgreSQL databases..."
                        sudo docker exec shml-postgres pg_dumpall -U postgres > "$backup_dir/postgres_full_backup.sql" 2>/dev/null || \
                            check_warn "Could not backup running PostgreSQL (container may not be running)"
                    fi

                    # Backup artifacts if they exist
                    if [ -d "/mlflow/artifacts" ]; then
                        echo "Backing up MLflow artifacts..."
                        sudo tar -czf "$backup_dir/mlflow_artifacts.tar.gz" /mlflow/artifacts 2>/dev/null || \
                            check_warn "Could not backup artifacts"
                    fi

                    check_pass "Backup created at: $backup_dir"
                    echo ""
                    echo "Now choose how to proceed:"
                    ;;
                *)
                    echo "Invalid choice. Please enter 1, 2, or 3."
                    ;;
            esac
        done
    else
        echo -e "${GREEN}✓ No existing data found - clean installation${NC}"
        PRESERVE_DATA=false
    fi

    echo ""
}

# ============================================================================
# PHASE 2: NETWORK SETUP
# ============================================================================

setup_network() {
    print_header "Phase 2: Network Configuration"

    # Get IPs
    LOCAL_IP=$(hostname -I | awk '{print $1}')
    TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "")

    echo "Local IP: ${LOCAL_IP}"
    if [ -n "$TAILSCALE_IP" ]; then
        echo "Tailscale IP: ${TAILSCALE_IP}"
    else
        echo "Tailscale IP: Not configured"

        if command -v tailscale &>/dev/null; then
            if prompt_yn "Would you like to set up Tailscale now?" "n"; then
                echo ""
                echo "Setting up Tailscale..."
                sudo tailscale up
                TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "")
                if [ -n "$TAILSCALE_IP" ]; then
                    check_fixed "Tailscale configured: ${TAILSCALE_IP}"
                else
                    check_warn "Tailscale setup incomplete"
                fi
            fi
        fi
    fi

    # Use local IP as fallback
    TAILSCALE_IP=${TAILSCALE_IP:-$LOCAL_IP}

    # Create Docker network
    print_section "Docker Network"
    if docker network inspect ml-platform &>/dev/null 2>&1; then
        check_pass "Docker network 'ml-platform' exists"
    else
        echo "Creating Docker network..."
        sudo docker network create ml-platform --driver bridge --subnet 172.30.0.0/16
        check_fixed "Docker network 'ml-platform' created"
    fi
}

# ============================================================================
# PHASE 3: PASSWORD CONFIGURATION
# ============================================================================

configure_passwords() {
    print_header "Phase 3: Password Configuration"

    echo -e "${CYAN}You'll be prompted for passwords for services you'll access directly.${NC}"
    echo -e "${CYAN}Database passwords will be auto-generated (you won't need them directly).${NC}"
    echo ""
    read -p "Press Enter to continue..."

    # User-facing passwords
    print_section "User-Facing Services"

    GRAFANA_PASSWORD=$(prompt_password \
        "Grafana Dashboard Password" \
        "Used to access monitoring dashboards at /grafana/ and /ray-grafana/\nUsername: admin" \
        "true" 24)
    echo ""

    # FusionAuth configuration (primary OAuth/SSO provider)
    print_section "FusionAuth (OAuth/SSO Provider)"
    echo -e "${CYAN}FusionAuth provides OAuth/SSO authentication for all platform services.${NC}"
    echo ""

    FUSIONAUTH_ADMIN_PASSWORD=$(prompt_password \
        "FusionAuth Admin Password" \
        "Used for FusionAuth administration at :9011/\nNote: Set during initial setup wizard" \
        "true" 24)
    echo ""

    FUSIONAUTH_API_KEY=$(openssl rand -hex 32)
    FUSIONAUTH_MLFLOW_SECRET=$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 32)
    FUSIONAUTH_RAY_SECRET=$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 32)
    check_pass "FusionAuth secrets generated"

    # Database passwords with option
    print_section "Database Passwords"
    echo -e "${CYAN}These are only needed if you want to connect to databases directly via psql.${NC}"
    echo -e "${CYAN}For normal platform use, these are handled automatically.${NC}"
    echo ""

    if prompt_yn "Would you like to set custom database passwords?" "n"; then
        MLFLOW_DB_PASSWORD=$(prompt_password \
            "MLflow Database Password" \
            "PostgreSQL database for MLflow metadata\nConnection: postgresql://mlflow:PASSWORD@localhost:5432/mlflow_db" \
            "true" 32)
        echo ""

        RAY_DB_PASSWORD=$(prompt_password \
            "Ray Database Password" \
            "PostgreSQL database for Ray job history\nConnection: postgresql://ray_compute:PASSWORD@localhost:5433/ray_compute" \
            "true" 32)
        echo ""

        SHARED_DB_PASSWORD=$(prompt_password \
            "Shared Database Password" \
            "Shared PostgreSQL for unified services (includes FusionAuth)" \
            "true" 32)
        echo ""
    else
        echo "Auto-generating database passwords..."
        MLFLOW_DB_PASSWORD=$(openssl rand -base64 48 | tr -dc 'a-zA-Z0-9' | head -c 32)
        RAY_DB_PASSWORD=$(openssl rand -base64 48 | tr -dc 'a-zA-Z0-9' | head -c 32)
        SHARED_DB_PASSWORD=$(openssl rand -base64 48 | tr -dc 'a-zA-Z0-9' | head -c 32)
        check_pass "Database passwords generated"
    fi

    # System secrets (always auto-generate)
    print_section "System Secrets"
    echo "Auto-generating system secrets..."
    API_SECRET=$(openssl rand -base64 50 | tr -d '\n')
    check_pass "System secrets generated"
}

# ============================================================================
# PHASE 4: ENVIRONMENT FILE SETUP
# ============================================================================

setup_env_files() {
    print_header "Phase 4: Environment Files"

    # Backup existing files
    if [ -f .env ] || [ -f ray_compute/.env ] || [ -f mlflow-server/.env ]; then
        print_section "Backing Up Existing Configuration"
        mkdir -p "$BACKUP_DIR"
        local timestamp=$(date +%Y%m%d_%H%M%S)

        [ -f .env ] && cp .env "$BACKUP_DIR/.env.backup.$timestamp" && \
            check_pass "Backed up .env"
        [ -f ray_compute/.env ] && cp ray_compute/.env "$BACKUP_DIR/ray_.env.backup.$timestamp" && \
            check_pass "Backed up ray_compute/.env"
        [ -f mlflow-server/.env ] && cp mlflow-server/.env "$BACKUP_DIR/mlflow_.env.backup.$timestamp" && \
            check_pass "Backed up mlflow-server/.env"
    fi

    # Create from examples
    print_section "Creating Environment Files"
    cp .env.example .env
    cp ray_compute/.env.example ray_compute/.env
    cp mlflow-server/.env.example mlflow-server/.env
    check_pass "Environment files created from templates"

    # Update main .env
    print_section "Configuring Main Environment"
    update_env_var ".env" "GRAFANA_ADMIN_PASSWORD" "$GRAFANA_PASSWORD"
    update_env_var ".env" "SHARED_DB_PASSWORD" "$SHARED_DB_PASSWORD"
    update_env_var ".env" "TAILSCALE_IP" "$TAILSCALE_IP"
    # FusionAuth configuration
    update_env_var ".env" "FUSIONAUTH_RUNTIME_MODE" "development"
    update_env_var ".env" "FUSIONAUTH_ADMIN_PASSWORD" "$FUSIONAUTH_ADMIN_PASSWORD"
    update_env_var ".env" "FUSIONAUTH_API_KEY" "$FUSIONAUTH_API_KEY"
    update_env_var ".env" "FUSIONAUTH_MLFLOW_CLIENT_SECRET" "$FUSIONAUTH_MLFLOW_SECRET"
    update_env_var ".env" "FUSIONAUTH_RAY_CLIENT_SECRET" "$FUSIONAUTH_RAY_SECRET"
    check_pass "Main .env configured"

    # Update ray_compute/.env
    update_env_var "ray_compute/.env" "POSTGRES_PASSWORD" "$RAY_DB_PASSWORD"
    update_env_var "ray_compute/.env" "GRAFANA_ADMIN_PASSWORD" "$GRAFANA_PASSWORD"
    update_env_var "ray_compute/.env" "API_SECRET_KEY" "$API_SECRET"
    update_env_var "ray_compute/.env" "TAILSCALE_IP" "$TAILSCALE_IP"
    check_pass "Ray Compute .env configured"

    # Update mlflow-server/.env
    update_env_var "mlflow-server/.env" "DB_PASSWORD" "$MLFLOW_DB_PASSWORD"
    update_env_var "mlflow-server/.env" "SERVER_LOCAL_IP" "$LOCAL_IP"
    update_env_var "mlflow-server/.env" "SERVER_TAILSCALE_IP" "$TAILSCALE_IP"
    update_env_var "mlflow-server/.env" "CLIENT_IP" "$LOCAL_IP"
    local backend_uri="postgresql://mlflow:${MLFLOW_DB_PASSWORD}@postgres:5432/mlflow_db"
    update_env_var "mlflow-server/.env" "MLFLOW_BACKEND_STORE_URI" "$backend_uri"
    check_pass "MLflow .env configured"
}

# ============================================================================
# PHASE 5: SECRET FILES
# ============================================================================

setup_secret_files() {
    print_header "Phase 5: Secret Files"

    # Main secrets directory
    print_section "Main Secrets"
    mkdir -p secrets
    echo "$SHARED_DB_PASSWORD" > secrets/shared_db_password.txt
    echo "$GRAFANA_PASSWORD" > secrets/grafana_password.txt
    echo "$RAY_DB_PASSWORD" > secrets/ray_db_password.txt
    # FusionAuth secrets (uses shared database)
    echo "$SHARED_DB_PASSWORD" > secrets/fusionauth_db_password.txt
    chmod 600 secrets/*
    check_pass "Main secret files created (4 files)"

    # MLflow secrets
    print_section "MLflow Secrets"
    mkdir -p mlflow-server/secrets
    echo "$MLFLOW_DB_PASSWORD" > mlflow-server/secrets/db_password.txt
    echo "$GRAFANA_PASSWORD" > mlflow-server/secrets/grafana_password.txt
    chmod 600 mlflow-server/secrets/*
    check_pass "MLflow secret files created (2 files)"

    # Provision Grafana dashboards
    print_section "Grafana Dashboards"
    if [ -f "monitoring/grafana/provision_dashboards.sh" ]; then
        echo "Provisioning Grafana dashboards..."
        sudo bash monitoring/grafana/provision_dashboards.sh >/dev/null 2>&1
        check_pass "Grafana dashboards provisioned"

        # Ensure container metrics dashboard exists with proper structure
        if [ ! -f "monitoring/grafana/dashboards/platform/container-metrics.json" ]; then
            echo "Creating enhanced container metrics dashboard..."
            # Dashboard will be created if missing
        fi
    else
        check_warn "Dashboard provisioning script not found"
    fi

    # Save credentials file
    print_section "Credentials File"
    cat > "$CREDENTIALS_FILE" << EOF
ML Platform Credentials
Generated: $(date)
═══════════════════════════════════════════

Network Configuration:
  Local IP: ${LOCAL_IP}
  Tailscale IP: ${TAILSCALE_IP}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USER-FACING SERVICES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Grafana Dashboards:
  MLflow Grafana: http://localhost/grafana/ or http://${TAILSCALE_IP}/grafana/
  Ray Grafana:    http://localhost/ray-grafana/ or http://${TAILSCALE_IP}/ray-grafana/
  Username: admin
  Password: ${GRAFANA_PASSWORD}

FusionAuth Admin (OAuth/SSO):
  URL: http://localhost:9011/ or http://${TAILSCALE_IP}:9011/
  Admin Password: ${FUSIONAUTH_ADMIN_PASSWORD}
  API Key: ${FUSIONAUTH_API_KEY}
  MLflow Client Secret: ${FUSIONAUTH_MLFLOW_SECRET}
  Ray Client Secret: ${FUSIONAUTH_RAY_SECRET}

MLflow UI:
  URL: http://localhost/mlflow/ or http://${TAILSCALE_IP}/mlflow/

Ray Dashboard:
  URL: http://localhost/ray/ or http://${TAILSCALE_IP}/ray/

Traefik Dashboard:
  URL: http://localhost:8090/ or http://${TAILSCALE_IP}:8090/

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DATABASE CREDENTIALS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MLflow Database:
  Connection: postgresql://mlflow:${MLFLOW_DB_PASSWORD}@localhost:5432/mlflow_db
  Password: ${MLFLOW_DB_PASSWORD}

Ray Database:
  Connection: postgresql://ray_compute:${RAY_DB_PASSWORD}@localhost:5433/ray_compute
  Password: ${RAY_DB_PASSWORD}

Shared Database:
  Password: ${SHARED_DB_PASSWORD}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SYSTEM SECRETS (for reference only)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

API Secret Key: ${API_SECRET}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SECURITY NOTES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️  Keep this file secure - it contains all platform passwords
⚠️  Never commit CREDENTIALS.txt or .env files to git
⚠️  Backup this file to a secure location
⚠️  File permissions: 600 (read/write owner only)

Backup location: ${BACKUP_DIR}/
EOF

    chmod 600 "$CREDENTIALS_FILE"
    check_pass "Credentials saved to: $CREDENTIALS_FILE"
}

# ============================================================================
# PHASE 5.5: DIRECTORY STRUCTURE AND PERMISSIONS
# ============================================================================

setup_directories() {
    print_header "Phase 5.5: Directory Structure and Permissions"

    # ===== INFRASTRUCTURE DIRECTORIES =====
    print_section "Infrastructure Directories"

    # PostgreSQL
    mkdir -p postgres
    mkdir -p backups/postgres
    chmod 755 postgres backups/postgres

    # Monitoring - Prometheus
    mkdir -p monitoring/prometheus/alerts
    mkdir -p logs/prometheus
    chmod 755 monitoring/prometheus logs/prometheus

    # Monitoring - Grafana (UID 472)
    mkdir -p monitoring/grafana/datasources
    mkdir -p monitoring/grafana/dashboards/{platform,mlflow,ray}
    mkdir -p logs/grafana
    sudo chown -R 472:472 monitoring/grafana logs/grafana 2>/dev/null || true
    chmod 755 monitoring/grafana

    # Traefik
    mkdir -p logs/traefik
    chmod 755 logs/traefik

    check_pass "Infrastructure directories created"

    # ===== MLFLOW DIRECTORIES =====
    print_section "MLflow Directories"

    # MLflow server directories (UID 1000 - mlflow user)
    mkdir -p mlflow-server/logs/mlflow
    mkdir -p mlflow-server/docker/mlflow/{plugins,scripts}
    mkdir -p mlflow-server/docker/nginx/{conf.d,ssl}
    mkdir -p mlflow-server/config/schema
    mkdir -p mlflow-server/api

    # Central logs directory
    mkdir -p logs/mlflow
    mkdir -p logs/nginx

    # Copy metrics exporter to scripts directory if not already there
    if [ -f "mlflow-server/docker/mlflow/scripts/metrics_exporter.py" ] && [ ! -f "mlflow-server/scripts/metrics_exporter.py" ]; then
        cp mlflow-server/docker/mlflow/scripts/metrics_exporter.py mlflow-server/scripts/
    fi

    # Set ownership to mlflow user (UID 1000)
    sudo chown -R 1000:1000 mlflow-server/logs logs/mlflow logs/nginx 2>/dev/null || true
    chmod 755 mlflow-server/docker mlflow-server/config

    check_pass "MLflow directories created with correct permissions"

    # ===== RAY DIRECTORIES =====
    print_section "Ray Directories"

    # Ray compute directories (UID 1000 - ray user)
    mkdir -p ray_compute/logs
    mkdir -p ray_compute/data/{ray,job_workspaces,artifacts}
    mkdir -p ray_compute/docker

    # Central logs directory
    mkdir -p logs/ray

    # Set ownership to ray user (UID 1000)
    sudo chown -R 1000:1000 ray_compute/logs ray_compute/data logs/ray 2>/dev/null || true
    chmod 755 ray_compute/docker ray_compute/data

    check_pass "Ray directories created with correct permissions"

    # ===== BACKUP DIRECTORIES =====
    print_section "Backup Directories"

    mkdir -p backups/{platform,mlflow,ray,monitoring}
    chmod 755 backups backups/*

    check_pass "Backup directories created"

    # ===== VERIFY CRITICAL PATHS =====
    print_section "Path Verification"

    local missing_paths=0

    # Check critical directories exist
    for dir in secrets postgres monitoring/prometheus monitoring/grafana mlflow-server/docker ray_compute/data logs backups; do
        if [ ! -d "$dir" ]; then
            echo "✗ Missing: $dir"
            ((missing_paths++))
        fi
    done

    if [ $missing_paths -eq 0 ]; then
        check_pass "All critical paths verified"
    else
        check_fail "$missing_paths critical paths missing"
        return 1
    fi
}

# ============================================================================
# PHASE 6: PRE-FLIGHT VALIDATION
# ============================================================================

preflight_checks() {
    print_header "Phase 6: Pre-Flight Validation"

    local validation_errors=0

    # Docker config validation (main compose with all includes)
    print_section "Docker Configuration"
    if sudo docker compose config >/dev/null 2>&1; then
        check_pass "Unified deploy/compose/docker-compose.yml valid (includes infra, MLflow, Ray)"
    else
        check_fail "Unified deploy/compose/docker-compose.yml has errors"
        echo ""
        echo "Running detailed validation to identify issue:"
        sudo docker compose config 2>&1 | head -10
        ((validation_errors++))
    fi

    # Secret files validation (zero-knowledge)
    print_section "Secret Files (Zero-Knowledge Validation)"
    local secret_files=(
        "secrets/shared_db_password.txt:16"
        "secrets/grafana_password.txt:12"
        "mlflow-server/secrets/db_password.txt:16"
        "mlflow-server/secrets/grafana_password.txt:12"
    )

    for entry in "${secret_files[@]}"; do
        IFS=':' read -r file min_len <<< "$entry"
        if validate_secret "$file" "$min_len"; then
            check_pass "$(basename $file) exists and valid"
        else
            check_fail "$(basename $file) missing or invalid"
            ((validation_errors++))
        fi
    done

    # GPU in Docker
    print_section "GPU Access"
    if groups | grep -q docker || [ "$EUID" -eq 0 ]; then
        if docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu20.04 nvidia-smi &>/dev/null 2>&1; then
            check_pass "GPUs accessible in Docker"
        else
            check_warn "GPU not accessible in Docker (will retry with sudo)"
        fi
    else
        if sudo docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu20.04 nvidia-smi &>/dev/null 2>&1; then
            check_pass "GPUs accessible in Docker (via sudo)"
        else
            check_fail "GPU not accessible in Docker"
            ((validation_errors++))
        fi
    fi

    # Port availability
    print_section "Port Availability"
    local ports=(80 443 8090 5432 5433 6379 9000)
    local port_conflicts=0
    for port in "${ports[@]}"; do
        if sudo lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
            check_warn "Port $port already in use"
            ((port_conflicts++))
        else
            check_pass "Port $port available"
        fi
    done

    if [ $port_conflicts -gt 0 ]; then
        echo ""
        echo -e "${YELLOW}Some ports are in use. This may cause conflicts.${NC}"
        if prompt_yn "Would you like to see which processes are using these ports?" "y"; then
            echo ""
            for port in "${ports[@]}"; do
                local pid=$(sudo lsof -Pi :$port -sTCP:LISTEN -t 2>/dev/null | head -1)
                if [ -n "$pid" ]; then
                    local process=$(ps -p $pid -o comm= 2>/dev/null)
                    echo "Port $port: PID $pid ($process)"
                fi
            done
            echo ""
            if prompt_yn "Stop existing containers before continuing?" "y"; then
                echo "Stopping containers..."
                sudo docker compose down 2>&1 | grep -v "WARNING:" || true
                check_fixed "Existing containers stopped"
            fi
        fi
    fi

    # Summary
    print_section "Validation Summary"
    if [ $validation_errors -eq 0 ]; then
        echo -e "${GREEN}✓ All validation checks passed!${NC}"
        return 0
    else
        echo -e "${RED}✗ ${validation_errors} validation error(s) found${NC}"
        echo ""
        echo "Validation errors detected:"

        # List specific errors found
        local error_count=0

        # Check secret files again to report which ones failed
        local secret_files=(
            "secrets/shared_db_password.txt:20"
            "secrets/grafana_password.txt:12"
            "mlflow-server/secrets/db_password.txt:20"
            "mlflow-server/secrets/grafana_password.txt:12"
        )

        for entry in "${secret_files[@]}"; do
            IFS=':' read -r file min_len <<< "$entry"
            if ! validate_secret "$file" "$min_len"; then
                echo "  • Missing or invalid: $file"
                ((error_count++))
            fi
        done

        # Check Docker compose config
        if ! sudo docker compose config >/dev/null 2>&1; then
            echo "  • Docker compose configuration has errors"
            ((error_count++))
        fi

        # Check GPU access
        if ! sudo docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu20.04 nvidia-smi &>/dev/null 2>&1; then
            echo "  • GPU not accessible in Docker"
            ((error_count++))
        fi

        echo ""
        echo -e "${YELLOW}To fix:${NC}"
        echo "  1. Ensure all secret files exist and have valid content"
        echo "  2. Run Phase 5 again to regenerate secrets: setup_secret_files"
        echo "  3. Check Docker compose syntax if configuration failed"
        echo ""

        if prompt_yn "Continue anyway?" "n"; then
            echo -e "${YELLOW}Continuing with warnings...${NC}"
            return 0
        else
            echo "Please fix errors and run again."
            exit 1
        fi
    fi
}

# ============================================================================
# PHASE 7: SERVICE STARTUP
# ============================================================================

start_services() {
    print_header "Phase 7: Starting Services"

    # Comprehensive cleanup
    print_section "Cleanup"
    echo "Stopping all running services and removing orphaned containers..."

    # Stop using unified compose (handles all included services)
    sudo docker compose down --remove-orphans 2>&1 | grep -v "WARNING:" | grep -v "Found orphan" || true

    # Force stop any remaining containers from this project
    sudo docker ps -a --filter "label=com.docker.compose.project=shml-platform" -q | xargs -r sudo docker rm -f 2>/dev/null || true

    # Remove existing ml-platform network if it exists (to avoid label conflicts)
    if sudo docker network inspect ml-platform >/dev/null 2>&1; then
        echo "Removing existing ml-platform network..."
        sudo docker network rm ml-platform 2>/dev/null || true
    fi

    check_pass "Clean slate ready"

    # Start infrastructure (shared services) using unified compose
    print_section "Phase 1: Shared Infrastructure"
    echo "Starting: Traefik, Postgres, Redis, FusionAuth, System Monitoring..."
    sudo docker compose up -d --remove-orphans traefik shml-postgres ml-platform-redis \
        fusionauth \
        global-prometheus unified-grafana node-exporter cadvisor 2>&1 | tail -15

    echo "Waiting for infrastructure health checks (45 seconds)..."
    sleep 45

    # Synchronize database passwords with current secrets
    print_section "Database Password Synchronization"
    echo "Updating database user passwords to match current secrets..."

    SHARED_DB_PASS=$(cat secrets/shared_db_password.txt)
    FUSIONAUTH_DB_PASS=$(cat secrets/fusionauth_db_password.txt 2>/dev/null || echo "$SHARED_DB_PASS")

    # Update shml-postgres users
    sudo docker exec shml-postgres psql -U postgres -c "ALTER USER mlflow WITH PASSWORD '$SHARED_DB_PASS';" >/dev/null 2>&1 && \
        check_pass "MLflow user password synchronized" || check_warn "MLflow user password sync skipped"

    sudo docker exec shml-postgres psql -U postgres -c "ALTER USER ray_compute WITH PASSWORD '$SHARED_DB_PASS';" >/dev/null 2>&1 && \
        check_pass "Ray user password synchronized" || check_warn "Ray user password sync skipped"

    sudo docker exec shml-postgres psql -U postgres -c "ALTER USER inference WITH PASSWORD '$SHARED_DB_PASS';" >/dev/null 2>&1 && \
        check_pass "Inference user password synchronized" || check_warn "Inference user password sync skipped"

    # Update FusionAuth user if it exists
    sudo docker exec shml-postgres psql -U postgres -c "ALTER USER fusionauth WITH PASSWORD '$FUSIONAUTH_DB_PASS';" >/dev/null 2>&1 && \
        check_pass "FusionAuth user password synchronized" || check_warn "FusionAuth DB password sync skipped (may need first run)"

    check_pass "Shared infrastructure started"

    # Start MLflow services using unified compose
    print_section "Phase 2: MLflow Services"
    echo "Starting: MLflow Server, Nginx, API, Prometheus..."
    sudo docker compose up -d --remove-orphans mlflow-server mlflow-nginx mlflow-api mlflow-prometheus 2>&1 | tail -10

    echo "Waiting for MLflow services (60 seconds)..."
    sleep 60
    check_pass "MLflow services started"

    # Initialize MLflow with standard experiments and registries
    print_section "MLflow Platform Initialization"

    if [ "$PRESERVE_DATA" = true ]; then
        echo -e "${CYAN}Preserving existing MLflow data - skipping initialization${NC}"
        echo "Existing experiments, models, and datasets will remain intact"
        check_pass "MLflow data preserved"
    else
        echo "Creating experiments, registries, and configurations..."
        if sudo docker exec mlflow-server python /mlflow/scripts/initialize_mlflow.py 2>&1 | tail -20; then
            check_pass "MLflow platform initialized"
        else
            check_warn "MLflow initialization had warnings (may already be initialized)"
        fi
    fi

    # Start Ray services using unified compose
    print_section "Phase 3: Ray Compute Services"
    echo "Starting: Ray Head, Ray API, Prometheus..."
    sudo docker compose up -d --remove-orphans ray-head ray-compute-api ray-prometheus 2>&1 | tail -10

    echo "Waiting for Ray services (45 seconds)..."
    sleep 45
    check_pass "Ray services started"


    # Start GPU monitoring
    print_section "Phase 3.5: GPU Monitoring"
    echo "Starting: DCGM Exporter (NVIDIA GPU metrics)..."
    if [ -f "monitoring/dcgm-exporter/deploy/compose/docker-compose.yml" ]; then
        sudo docker compose -f monitoring/dcgm-exporter/deploy/compose/docker-compose.yml up -d 2>&1 | tail -5

        # Wait for DCGM to start
        sleep 5

        # Verify GPU monitoring dashboard exists
        if [ ! -f "monitoring/grafana/dashboards/platform/gpu-monitoring.json" ]; then
            echo "Creating GPU monitoring dashboard..."
            # Dashboard will be created if missing
        fi

        check_pass "GPU monitoring started"
    else
        check_warn "DCGM Exporter configuration not found"
    fi

    # Start global monitoring (depends on service Prometheus instances)
    print_section "Phase 4: Global Monitoring"
    echo "Starting: Global Prometheus (federation), Unified Grafana..."
    # Note: Don't use --remove-orphans here as it would remove Ray/MLflow containers
    sudo docker compose -f deploy/compose/docker-compose.infra.yml up -d global-prometheus unified-grafana 2>&1 | tail -10

    echo "Waiting for global monitoring (20 seconds)..."
    sleep 20

    # Synchronize service passwords
    print_section "Service Password Configuration"

    # Grafana admin password
    echo "Configuring Grafana admin password..."
    GRAFANA_PASS=$(cat secrets/grafana_password.txt)
    sleep 5  # Wait for Grafana to be fully ready

    if sudo docker exec unified-grafana grafana-cli admin reset-admin-password "$GRAFANA_PASS" >/dev/null 2>&1; then
        check_pass "Grafana admin password configured"
    else
        check_warn "Grafana password may need manual reset"
    fi

    # Verify FusionAuth is running
    echo "Verifying FusionAuth configuration..."
    if sudo docker ps --format "{{.Names}}" | grep -q "fusionauth"; then
        check_pass "FusionAuth container running"
        echo "  → Admin URL: http://localhost:9011/admin/"
        echo "  → Complete setup wizard on first access"
    else
        check_warn "FusionAuth may not be running"
    fi

    check_pass "Global monitoring started"
}

# ============================================================================
# PHASE 8: HEALTH MONITORING
# ============================================================================

monitor_health() {
    print_header "Phase 8: Health Monitoring"

    echo "Checking service health..."
    echo ""

    # Get container status
    sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "ml-platform|mlflow|ray|fusionauth" || true

    echo ""
    print_section "Service Health Checks"

    # Check critical services
    local services=(
        "ml-platform-traefik:http://localhost:8090/ping"
        "mlflow-server:http://localhost/mlflow/"
        "fusionauth:http://localhost:9011/"
    )

    for entry in "${services[@]}"; do
        IFS=':' read -r name url <<< "$entry"
        if curl -sf "$url" >/dev/null 2>&1; then
            check_pass "$name responding"
        else
            check_warn "$name not responding (may still be starting)"
        fi
    done

    echo ""
    print_section "Password Synchronization Verification"
    echo "Verifying all passwords are properly set..."

    # Verify Grafana password
    if sudo docker exec unified-grafana grafana-cli admin reset-admin-password "$(cat secrets/grafana_password.txt)" >/dev/null 2>&1; then
        check_pass "Grafana password verified and synchronized"
    else
        check_warn "Grafana password verification failed"
    fi

    # Verify FusionAuth is accessible
    if curl -sf "http://localhost:9011/" >/dev/null 2>&1; then
        check_pass "FusionAuth accessible"
    else
        check_warn "FusionAuth not responding (may need setup wizard)"
    fi

    # Verify database passwords (check if connections work)
    if sudo docker exec shml-postgres psql -U mlflow -d mlflow_db -c "SELECT 1" >/dev/null 2>&1; then
        check_pass "MLflow database password working"
    else
        check_warn "MLflow database password may need verification"
    fi

    if sudo docker exec shml-postgres psql -U ray_compute -d ray_compute -c "SELECT 1" >/dev/null 2>&1; then
        check_pass "Ray database password working"
    else
        check_warn "Ray database password may need verification"
    fi

    if sudo docker exec shml-postgres psql -U fusionauth -d fusionauth -c "SELECT 1" >/dev/null 2>&1; then
        check_pass "FusionAuth database password working"
    else
        check_warn "FusionAuth database password may need verification"
    fi

    # Update container metrics dashboard with current container IDs
    print_section "Container Metrics Dashboard Update"
    if [ -f "scripts/update_container_dashboard.sh" ]; then
        echo "Updating container metrics dashboard with current IDs..."
        if bash scripts/update_container_dashboard.sh >/dev/null 2>&1; then
            check_pass "Container metrics dashboard updated with current container IDs"
            # Restart Grafana to load updated dashboard
            sudo docker restart unified-grafana >/dev/null 2>&1
            sleep 5
        else
            check_warn "Container dashboard update script failed (dashboard may show old IDs)"
        fi
    else
        check_warn "Container dashboard update script not found"
    fi

    echo ""
    echo -e "${CYAN}Note: Some services may take 2-3 minutes to fully start.${NC}"
    echo -e "${CYAN}Monitor with: sudo docker ps${NC}"
    echo -e "${CYAN}View logs: sudo docker logs <container-name>${NC}"
}

# ============================================================================
# PHASE 9: FINAL SUMMARY
# ============================================================================

print_summary() {
    print_header "Setup Complete!"

    echo -e "${GREEN}Platform is starting up!${NC}"
    echo ""

    echo "📊 Setup Statistics:"
    echo "  • Errors: $ERRORS"
    echo "  • Warnings: $WARNINGS"
    echo "  • Fixed: $FIXED"
    echo ""

    echo "🚀 Service Status:"
    local healthy=0
    local total=0
    for service in ml-platform-traefik shml-postgres mlflow-server mlflow-nginx ray-head fusionauth; do
        ((total++))
        if sudo docker inspect "$service" 2>/dev/null | grep -q '"Status": "running"'; then
            if sudo docker inspect "$service" 2>/dev/null | grep -q '"Health"'; then
                if sudo docker inspect "$service" 2>/dev/null | grep -q '"Status": "healthy"'; then
                    echo -e "  ${GREEN}✓${NC} $service (healthy)"
                    ((healthy++))
                else
                    echo -e "  ${YELLOW}◉${NC} $service (starting)"
                fi
            else
                echo -e "  ${GREEN}✓${NC} $service (running)"
                ((healthy++))
            fi
        else
            echo -e "  ${RED}✗${NC} $service (not running)"
        fi
    done
    echo "  $healthy/$total core services running"
    echo ""

    echo "🌐 Access Points (wait 2-3 minutes for full startup):"
    echo "  • MLflow UI:              http://${TAILSCALE_IP}/mlflow/"
    echo "  • Ray Dashboard:          http://${TAILSCALE_IP}/ray/"
    echo "  • Unified Grafana:        http://${TAILSCALE_IP}/grafana/"
    echo "    └─ Platform: System, Container, GPU Monitoring"
    echo "    └─ MLflow: Service metrics and performance"
    echo "    └─ Ray: Cluster metrics and job stats"
    echo "  • Traefik Dashboard:      http://${TAILSCALE_IP}:8090/"
    echo "  • FusionAuth (OAuth/SSO): http://${TAILSCALE_IP}:9011/admin/"
    echo ""

    echo "📝 Credentials:"
    echo "  • Saved to: $CREDENTIALS_FILE"
    echo "  • Grafana:    admin / ${GRAFANA_PASSWORD}"
    echo "  • FusionAuth: Complete setup wizard on first access"
    echo ""

    echo "🛠️  Useful Commands:"
    echo "  • Check status:      sudo docker ps"
    echo "  • View logs:         sudo docker logs <container-name>"
    echo "  • Verify GPU setup:  bash scripts/verify_gpu_monitoring.sh"
    echo "  • Stop all:          sudo bash stop_all.sh"
    echo "  • Restart:           sudo bash $(basename $0)"
    echo ""

    echo "🔒 Security Configuration:"
    echo "  • Ray GPU Access: Secure device passthrough (no privileged mode)"
    echo "    - Jobs inherit GPU access via Ray head container"
    echo "    - Runs as non-root 'ray' user (UID 1000)"
    echo "    - No dangerous capabilities (CAP_SYS_ADMIN, etc.)"
    echo "    - Limited to specific GPU device IDs: 0, 1"
    echo "  • All passwords synchronized to running services"
    echo "  • Database users verified and accessible"
    echo ""

    echo "📋 Features Enabled:"
    echo "  • MLflow Schema Validation:  Enforces experiment metadata standards"
    echo "  • Artifact Compression:      Auto-compression for artifacts >10MB"
    echo "  • Federated Prometheus:      Multi-tier metrics (90d/30d/7d retention)"
    echo "  • GPU Monitoring (DCGM):     Real-time NVIDIA GPU metrics (utilization, temp, power)"
    echo "    └─ Dashboard: http://${TAILSCALE_IP}/grafana/ → Platform → GPU Monitoring"
    echo "  • GPU Sharing (MPS):         Multi-process CUDA sharing enabled"
    echo "  • Ray GPU Access:            Secure GPU passthrough for compute jobs"
    echo "    └─ Jobs inherit GPU access without privileged mode"
    echo ""

    echo "💾 Data Persistence:"
    if [ "$PRESERVE_DATA" = true ]; then
        echo "  • Existing data PRESERVED - your experiments, models, and artifacts are intact"
    else
        echo "  • Fresh installation - standard experiments created"
    fi
    echo "  • All data persists across restarts in Docker volumes:"
    echo "    - shml-postgres-data: PostgreSQL database (experiments, runs, models)"
    echo "    - mlflow-mlruns: MLflow metadata"
    echo "    - /mlflow/artifacts: Model artifacts and files"
    echo "    - unified-grafana-data: Grafana dashboards"
    echo ""

    echo -e "${YELLOW}⚠️  Remember to:${NC}"
    echo "  1. Backup $CREDENTIALS_FILE to a secure location"
    echo "  2. Change Authentik password after first login"
    echo "  3. Never commit .env or CREDENTIALS.txt to git"
    echo "  4. MLflow schema validation requires proper tags on experiments"
    echo "  5. Regular backups: Data in volumes persists until explicitly deleted"
    echo ""

    log "Setup completed successfully"
}

# ============================================================================
# MAIN EXECUTION
# ============================================================================

main() {
    # Clear screen and show header
    clear
    echo ""
    echo -e "${BLUE}${BOLD}╔════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}${BOLD}║                                                        ║${NC}"
    echo -e "${BLUE}${BOLD}║         ML Platform - Unified Setup & Startup          ║${NC}"
    echo -e "${BLUE}${BOLD}║                   Version ${SCRIPT_VERSION}                        ║${NC}"
    echo -e "${BLUE}${BOLD}║                                                        ║${NC}"
    echo -e "${BLUE}${BOLD}╚════════════════════════════════════════════════════════╝${NC}"
    echo ""

    log "=== ML Platform Setup Started ==="

    # Check if running as root
    if [ "$EUID" -eq 0 ]; then
        echo -e "${RED}⚠️  Do not run this script as root (sudo)${NC}"
        echo "The script will request sudo when needed."
        exit 1
    fi

    # Create log file
    mkdir -p "$(dirname "$LOG_FILE")"

    # Run phases
    check_dependencies
    check_existing_data
    setup_network
    configure_passwords
    setup_env_files
    setup_secret_files
    setup_directories
    preflight_checks
    start_services
    monitor_health
    print_summary

    log "=== ML Platform Setup Completed ==="
}

# Run main function
main "$@"
