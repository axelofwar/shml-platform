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
# 7. NVIDIA MPS Daemon vs Docker GPU Access (December 2025):
#    - NVIDIA MPS (Multi-Process Service) enables GPU sharing between processes
#    - CRITICAL: MPS daemon at 100% thread allocation BLOCKS ALL new CUDA contexts
#    - This includes Docker containers trying to access GPUs!
#    - Symptom: torch.cuda.is_available() hangs indefinitely in Ray container
#    - Root cause: CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps in container env
#    - Solution: REMOVED MPS config from ray_compute/docker-compose.yml
#    - The host MPS daemon must be STOPPED for Ray containers to access GPUs
#    - This script now auto-stops MPS before starting Ray services
#    - To restart MPS later: sudo nvidia-cuda-mps-control -d
#    - Check MPS status: ps aux | grep nvidia-cuda-mps
#    - Trade-off: Ray gets exclusive GPU access (no MPS sharing during training)
#    - Future: Investigate K8s + KubeRay + Kueue for true GPU pooling
#
# 8. MLflow 3.x API Changes (December 2025):
#    - MLflow 3.x uses --static-prefix /mlflow for URL routing
#    - API endpoint format changed to /mlflow/ajax-api/2.0/mlflow/...
#    - MLFLOW_ALLOWED_HOSTS must include hostname:port variants (strict matching)
#    - Example: mlflow-server,mlflow-server:5000,mlflow-nginx,mlflow-nginx:80
#    - The Python MLflow client auto-handles the prefix when using MLFLOW_TRACKING_URI
#
# 9. Docker Compose Include vs Explicit Files (December 2025):
#    - Docker Compose `include:` directive CONFLICTS with network definitions
#    - If included file has `networks: platform: external: true`, it conflicts with
#      the parent's definition even though they refer to the same network
#    - Solution: This script is the ONLY entry point for starting services
#    - Individual compose files have `external: true` for network (standalone capable)
#    - Script ensures network exists before starting services
#    - DO NOT use `docker compose up` with the main deploy/compose/docker-compose.yml directly
#    - Always use: ./start_all_safe.sh [command] [service]
#
# Usage:
#   ./start_all_safe.sh                    # Full restart (stop + cleanup + start all)
#   ./start_all_safe.sh start              # Start all services (assumes clean state)
#   ./start_all_safe.sh stop               # Stop all services
#   ./start_all_safe.sh restart            # Full restart (default)
#   ./start_all_safe.sh status             # Show service status
#   ./start_all_safe.sh diagnose           # Verify auth protection and middleware
#   ./start_all_safe.sh fix-oauth          # Fix FusionAuth OAuth redirect URLs
#
# Individual Service Commands:
#   ./start_all_safe.sh start infra        # Start only infrastructure
#   ./start_all_safe.sh start auth         # Start FusionAuth + OAuth2 Proxy
#   ./start_all_safe.sh start mlflow       # Start MLflow services
#   ./start_all_safe.sh start ray          # Start Ray compute services
#   ./start_all_safe.sh start inference    # Start coding models + chat API
#   ./start_all_safe.sh start monitoring   # Start Prometheus + Grafana
#   ./start_all_safe.sh start sba-portal   # Start SBA Resource Portal (Gemini AI)
#   ./start_all_safe.sh stop inference     # Stop only inference services
#   ./start_all_safe.sh restart ray        # Restart only Ray services
#   ./start_all_safe.sh restart sba-portal # Restart SBA Resource Portal

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-shml-platform}"

# =============================================================================
# Modular Deploy Library (Phase 1 refactor)
# Each module is independently sourceable and guards against double-loading.
# =============================================================================
_DEPLOY_LIBS="${SCRIPT_DIR}/scripts/deploy"
# shellcheck disable=SC1090,SC1091
source "${_DEPLOY_LIBS}/lib.sh"      # Colors, logging, timeouts, env, tailscale helpers
source "${_DEPLOY_LIBS}/networks.sh" # PLATFORM_NETWORK, ensure_networks
source "${_DEPLOY_LIBS}/docker.sh"   # dc_pull, dc_up, dc_stop, dc_down, dc_restart
source "${_DEPLOY_LIBS}/health.sh"   # wait_for_health, wait_for_http, wait_for_middleware
source "${_DEPLOY_LIBS}/gpu.sh"      # check_mps_status, stop_mps_daemon, verify_gpu_access
source "${_DEPLOY_LIBS}/backup.sh"   # backup/restore functions + BACKUP_DIR


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
        if can_run_privileged; then
            run_privileged_quiet tailscale funnel --https=443 off 2>/dev/null || true
            log_success "Tailscale Funnel stopped"
        else
            log_warn "Skipping funnel shutdown (no non-interactive sudo)"
        fi
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
    docker compose --env-file .env -f ray_compute/docker-compose.yml stop ray-compute-api ray-head ray-prometheus 2>/dev/null || true
    log_success "Ray services stopped"
    echo ""

    # Phase 4: Stop MLflow Services
    log_info "━━━ Stopping MLflow Services ━━━"
    docker compose --env-file .env -f mlflow-server/docker-compose.yml stop mlflow-api mlflow-nginx mlflow-server mlflow-prometheus 2>/dev/null || true
    log_success "MLflow services stopped"
    echo ""

    # Phase 4.5: Stop Data Platform (FiftyOne, Nessie)
    log_info "━━━ Stopping Data Platform ━━━"
    docker compose --env-file .env -f deploy/compose/docker-compose.infra.yml stop fiftyone fiftyone-mongodb nessie 2>/dev/null || true
    log_success "Data platform stopped"
    echo ""

    # Phase 5: Stop Monitoring (Grafana/Prometheus/Pushgateway/SLO Exporter/DCGM)
    log_info "━━━ Stopping Monitoring ━━━"
    docker compose --env-file .env -f deploy/compose/docker-compose.infra.yml stop unified-grafana global-prometheus pushgateway ml-slo-exporter 2>/dev/null || true
    docker compose --env-file .env -f deploy/compose/docker-compose.infra.yml stop cadvisor node-exporter 2>/dev/null || true
    # Stop DCGM exporter (GPU metrics)
    if [ -f "monitoring/dcgm-exporter/docker-compose.yml" ]; then
        docker compose -f monitoring/dcgm-exporter/docker-compose.yml stop 2>/dev/null || true
    fi
    log_success "Monitoring stopped"
    echo ""

    # Phase 6: Stop Auth Services
    log_info "━━━ Stopping Auth Services ━━━"
    docker compose --env-file .env -f deploy/compose/docker-compose.auth.yml stop oauth2-proxy role-auth fusionauth 2>/dev/null || true
    log_success "Auth services stopped"
    echo ""

    # Phase 7: Stop Infrastructure
    log_info "━━━ Stopping Infrastructure ━━━"

    # Stop Infisical if it exists
    if [ -f "deploy/compose/docker-compose.secrets.yml" ]; then
        docker compose -f deploy/compose/docker-compose.secrets.yml stop 2>/dev/null || true
    fi

    docker compose --env-file .env -f deploy/compose/docker-compose.infra.yml stop traefik redis postgres 2>/dev/null || true
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
    docker compose --env-file .env -f deploy/compose/docker-compose.infra.yml down --remove-orphans 2>/dev/null || true
    if [ -f "deploy/compose/docker-compose.secrets.yml" ]; then
        docker compose -f deploy/compose/docker-compose.secrets.yml down --remove-orphans 2>/dev/null || true
    fi
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
        "unified-grafana" "global-prometheus" "dcgm-exporter" "${PLATFORM_PREFIX:-shml}-pushgateway"
        # Infrastructure - old naming
        "ml-platform-cadvisor" "ml-platform-node-exporter"
        "ml-platform-traefik" "ml-platform-redis" "shml-postgres"
        # Infrastructure - new naming with prefix
        "${PLATFORM_PREFIX:-shml}-cadvisor" "${PLATFORM_PREFIX:-shml}-node-exporter"
        "${PLATFORM_PREFIX:-shml}-traefik" "${PLATFORM_PREFIX:-shml}-redis" "${PLATFORM_PREFIX:-shml}-postgres"
        # UI
        "homer" "dozzle" "postgres-backup" "webhook-deployer"
        # Data Platform
        "${PLATFORM_PREFIX:-shml}-nessie" "${PLATFORM_PREFIX:-shml}-fiftyone" "${PLATFORM_PREFIX:-shml}-fiftyone-mongodb"
        "${PLATFORM_PREFIX:-shml}-ml-slo-exporter"
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
    if docker compose --env-file .env -f deploy/compose/docker-compose.infra.yml -f mlflow-server/docker-compose.yml -f ray_compute/docker-compose.yml build mlflow-server >/dev/null 2>&1; then
        echo -e " ${GREEN}✓${NC}"
    else
        echo -e " ${YELLOW}⚠ (using existing)${NC}"
        build_failed=$((build_failed + 1))
    fi

    # MLflow API
    echo -n "  Building mlflow-api..."
    if docker compose --env-file .env -f deploy/compose/docker-compose.infra.yml -f mlflow-server/docker-compose.yml -f ray_compute/docker-compose.yml build mlflow-api >/dev/null 2>&1; then
        echo -e " ${GREEN}✓${NC}"
    else
        echo -e " ${YELLOW}⚠ (using existing)${NC}"
        build_failed=$((build_failed + 1))
    fi

    # Ray head (if custom Dockerfile exists)
    echo -n "  Building ray-head..."
    if docker compose --env-file .env -f deploy/compose/docker-compose.infra.yml -f mlflow-server/docker-compose.yml -f ray_compute/docker-compose.yml build ray-head >/dev/null 2>&1; then
        echo -e " ${GREEN}✓${NC}"
    else
        echo -e " ${YELLOW}⚠ (using existing)${NC}"
        build_failed=$((build_failed + 1))
    fi

    # Ray compute API
    echo -n "  Building ray-compute-api..."
    if docker compose --env-file .env -f deploy/compose/docker-compose.infra.yml -f mlflow-server/docker-compose.yml -f ray_compute/docker-compose.yml build ray-compute-api >/dev/null 2>&1; then
        echo -e " ${GREEN}✓${NC}"
    else
        echo -e " ${YELLOW}⚠ (using existing)${NC}"
        build_failed=$((build_failed + 1))
    fi

    # Role Auth (RBAC middleware)
    echo -n "  Building role-auth..."
    if docker compose --env-file .env -f deploy/compose/docker-compose.auth.yml build role-auth >/dev/null 2>&1; then
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
    # Pre-flight: Dynamic Environment Initialization
    # Auto-discovers LAN_IP and TAILSCALE_IP and updates .env files before
    # any services start. Handles network changes (DHCP, hotspot, Tailscale
    # re-auth) transparently so stale IPs never break Traefik or OAuth2.
    # =========================================================================
    if [ -f "$SCRIPT_DIR/scripts/platform/env-init.sh" ]; then
        bash "$SCRIPT_DIR/scripts/platform/env-init.sh"
        # Reload .env so the rest of this script sees fresh values
        set -a; source "$SCRIPT_DIR/.env"; set +a
    else
        log_warn "scripts/platform/env-init.sh not found — skipping dynamic IP detection"
    fi

    # =========================================================================
    # Phase 1: Core Infrastructure (No dependencies)
    # =========================================================================
    log_info "━━━ Phase 1: Core Infrastructure ━━━"
    echo "Starting: Traefik, PostgreSQL, Redis..."
    docker compose --env-file .env -f deploy/compose/docker-compose.infra.yml up -d --force-recreate \
        traefik postgres redis \
        node-exporter cadvisor 2>&1 | grep -v "orphan" || true

    wait_for_health "${PLATFORM_PREFIX:-shml}-postgres" $POSTGRES_TIMEOUT || { log_error "PostgreSQL failed to start"; exit 1; }
    wait_for_health "${PLATFORM_PREFIX:-shml}-traefik" $TRAEFIK_TIMEOUT || { log_error "Traefik failed to start"; exit 1; }
    wait_for_health "${PLATFORM_PREFIX:-shml}-redis" $DEFAULT_TIMEOUT || log_warn "Redis may still be initializing"

    # Verify Traefik API is accessible
    wait_for_http "http://localhost:8090/api/overview" 30 || log_warn "Traefik API not yet accessible"

    # Nessie Iceberg catalog (depends on PostgreSQL)
    echo "Starting: Nessie (Iceberg catalog)..."
    docker compose --env-file .env -f deploy/compose/docker-compose.infra.yml up -d --force-recreate \
        nessie 2>&1 | grep -v "orphan" || true
    wait_for_health "${PLATFORM_PREFIX:-shml}-nessie" $DEFAULT_TIMEOUT || log_warn "Nessie may still be starting"

    log_success "Infrastructure ready"
    echo ""

    # =========================================================================
    # Phase 1.5: Database Integrity Check & Auto-Restore
    # Checks if databases appear empty (e.g., after volume reset) and restores
    # from the largest backup within the last 25 hours for data continuity
    # =========================================================================
    check_and_restore_databases

    # =========================================================================
    # Phase 1.6: Infisical Secrets Manager (Needs PostgreSQL, Redis)
    # =========================================================================
    if [ -f "deploy/compose/docker-compose.secrets.yml" ]; then
        log_info "━━━ Phase 1.6: Infisical Secrets Manager ━━━"
        echo "Starting: Infisical (secrets manager for API keys, GitHub tokens)..."
        docker compose -f deploy/compose/docker-compose.secrets.yml up -d --force-recreate 2>&1 | grep -v "orphan" || true

        wait_for_health "${PLATFORM_PREFIX:-shml}-infisical" $DEFAULT_TIMEOUT || log_warn "Infisical may still be initializing"
        log_success "Infisical secrets manager ready"
        echo ""
    fi

    # =========================================================================
    # Phase 2: FusionAuth (Needs PostgreSQL)
    # =========================================================================
    log_info "━━━ Phase 2: FusionAuth (OAuth Provider) ━━━"
    echo "Starting: FusionAuth OAuth/SSO server..."
    docker compose --env-file .env -f deploy/compose/docker-compose.auth.yml up -d --force-recreate fusionauth 2>&1 | grep -v "orphan" || true

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
        local EXPECTED_PUBLIC_DOMAIN="${PUBLIC_DOMAIN:-}"

        # Get current Tailscale hostname
        local CURRENT_HOSTNAME=$(tailscale status --json 2>/dev/null | jq -r '.Self.HostName' 2>/dev/null || echo "unknown")
        local MAGIC_DNS_SUFFIX=$(tailscale status --json 2>/dev/null | jq -r '.MagicDNSSuffix' 2>/dev/null || echo "")

        local can_manage_tailscale=false
        if can_run_privileged; then
            can_manage_tailscale=true
        else
            log_warn "Skipping privileged Tailscale changes during startup (no non-interactive sudo)"
        fi

        # Check and fix hostname if needed
        if [ "$CURRENT_HOSTNAME" != "$EXPECTED_HOSTNAME" ]; then
            log_warn "Tailscale hostname mismatch: '$CURRENT_HOSTNAME' != '$EXPECTED_HOSTNAME'"
            echo "  Correcting Tailscale hostname to '$EXPECTED_HOSTNAME'..."
            if [ "$can_manage_tailscale" = true ] && run_privileged_quiet tailscale set --hostname="$EXPECTED_HOSTNAME" 2>/dev/null; then
                log_success "Hostname corrected to '$EXPECTED_HOSTNAME'"
                # Give Tailscale a moment to propagate the change
                sleep 3
            else
                log_warn "Could not update Tailscale hostname automatically"
            fi
        else
            echo "  Tailscale hostname: $CURRENT_HOSTNAME ✓"
        fi

        # Get the public domain (re-read after potential hostname change)
        PUBLIC_DOMAIN=$(detect_tailscale_public_domain)
        if [ -z "$PUBLIC_DOMAIN" ]; then
            PUBLIC_DOMAIN="${EXPECTED_PUBLIC_DOMAIN}"
        fi
        echo "  Public domain: https://${PUBLIC_DOMAIN}"

        if [ "$can_manage_tailscale" = true ]; then
            # Reset any existing funnel configuration to avoid conflicts
            echo "  Resetting funnel configuration..."
            run_privileged_quiet tailscale funnel reset 2>/dev/null || true
            sleep 2

            # Start the funnel - routes HTTPS to local Traefik on port 80
            echo "  Starting Tailscale Funnel..."
            if run_privileged_quiet tailscale funnel --bg 80 2>/dev/null; then
                log_success "Funnel started on https://${PUBLIC_DOMAIN}"
            else
                log_warn "Funnel command may have failed"
            fi

            # Give funnel time to establish connection
            sleep 5
        else
            if funnel_active_for_domain "$PUBLIC_DOMAIN"; then
                log_success "Existing Tailscale Funnel detected for https://${PUBLIC_DOMAIN}"
            else
                log_error "Tailscale Funnel is required but cannot be managed without non-interactive sudo"
                return 1
            fi
        fi

        if ! funnel_active_for_domain "$PUBLIC_DOMAIN"; then
            log_error "Tailscale Funnel is not active for https://${PUBLIC_DOMAIN}"
            return 1
        fi

        # Verify local OIDC discovery through Traefik.
        # Internal startup no longer depends on reaching Funnel over the Tailscale IP.
        echo -n "  Verifying local OIDC discovery endpoint"
        local oidc_wait=0
        local oidc_success=false
        while [ $oidc_wait -lt 60 ]; do
            if check_local_oidc_discovery "$PUBLIC_DOMAIN"; then
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
            log_warn "OIDC not accessible on first attempt - retrying local verification..."

            if [ "$can_manage_tailscale" = true ]; then
                run_privileged_quiet tailscale funnel reset 2>/dev/null || true
                sleep 2
                run_privileged_quiet tailscale funnel --bg 80 2>/dev/null || true
                sleep 5
            else
                log_error "Cannot repair Funnel automatically without non-interactive sudo"
                return 1
            fi

            echo -n "  Retry local OIDC verification"
            oidc_wait=0
            while [ $oidc_wait -lt 30 ]; do
                if check_local_oidc_discovery "$PUBLIC_DOMAIN"; then
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
            log_error "Local OIDC discovery endpoint not accessible!"
            echo ""
            echo -e "${RED}╔════════════════════════════════════════════════════════════════╗${NC}"
            echo -e "${RED}║  LOCAL OIDC DISCOVERY NOT WORKING                              ║${NC}"
            echo -e "${RED}╠════════════════════════════════════════════════════════════════╣${NC}"
            echo -e "${RED}║  OAuth2 Proxy requires Traefik + FusionAuth discovery.         ║${NC}"
            echo -e "${RED}║                                                                ║${NC}"
            echo -e "${RED}║  Check locally:                                                ║${NC}"
            echo -e "${RED}║    curl --resolve ${PUBLIC_DOMAIN}:443:127.0.0.1 https://${PUBLIC_DOMAIN}/.well-known/openid-configuration${NC}"
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
    # - deploy/compose/docker-compose.infra.yml must have "healthcheck: disable: true"
    # - Traefik filters out containers that are "unhealthy" or "starting"
    # - Without disabled healthcheck, middleware is NEVER registered
    # - OAuth2 Proxy uses /oauth2-proxy/* prefix (NOT /oauth2/*) to avoid
    #   conflict with FusionAuth's OIDC endpoints
    # =========================================================================
    log_info "━━━ Phase 4: OAuth2 Proxy (Auth Middleware) ━━━"
    echo "Starting: OAuth2 Proxy (provides forwardAuth middleware)..."
    echo "  Note: Using /oauth2-proxy/* prefix (FusionAuth uses /oauth2/*)"
    docker compose --env-file .env -f deploy/compose/docker-compose.auth.yml up -d --force-recreate oauth2-proxy 2>&1 | grep -v "orphan" || true

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
            echo -e "${RED}║  FIX: In deploy/compose/docker-compose.infra.yml, set:                        ║${NC}"
            echo -e "${RED}║       healthcheck:                                             ║${NC}"
            echo -e "${RED}║         disable: true                                          ║${NC}"
            echo -e "${RED}║                                                                ║${NC}"
            echo -e "${RED}║  Then restart: docker compose --env-file .env -f deploy/compose/docker-compose.auth.yml up -d --force-recreate oauth2-proxy${NC}"
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
            log_warn "OAuth2 Proxy OIDC discovery failed - retrying local OIDC verification"
            echo ""

            # Stop oauth2-proxy
            docker stop oauth2-proxy 2>/dev/null || true
            sleep 2

            # Refresh funnel only when privileged access is available.
            if can_run_privileged; then
                echo "  Refreshing Tailscale Funnel..."
                run_privileged_quiet tailscale funnel reset 2>/dev/null || true
                sleep 2
                run_privileged_quiet tailscale funnel --bg 80 2>/dev/null || true
                sleep 5
            elif ! funnel_active_for_domain "$check_domain"; then
                log_error "Tailscale Funnel is required for OAuth2 Proxy recovery"
                return 1
            fi

            # Wait for local OIDC endpoint
            local oidc_retry=0
            local check_domain="${PUBLIC_DOMAIN:-$(tailscale status --json 2>/dev/null | jq -r '.Self.HostName + "." + .MagicDNSSuffix' 2>/dev/null || echo 'localhost')}"
            while [ $oidc_retry -lt 30 ]; do
                if check_local_oidc_discovery "$check_domain"; then
                    log_success "OIDC endpoint accessible"
                    break
                fi
                echo -n "."
                sleep 2
                oidc_retry=$((oidc_retry + 2))
            done

            # Restart oauth2-proxy
            echo "  Restarting OAuth2 Proxy..."
            docker compose --env-file .env -f deploy/compose/docker-compose.auth.yml up -d --force-recreate oauth2-proxy 2>&1 | grep -v "orphan" || true
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
            echo -e "${YELLOW}  Ensure deploy/compose/docker-compose.auth.yml has 'healthcheck: disable: true'${NC}"
        fi

        # Final recovery attempt: restart oauth2-proxy
        echo "  Final recovery attempt..."
        docker compose --env-file .env -f deploy/compose/docker-compose.auth.yml up -d --force-recreate oauth2-proxy 2>&1 | grep -v "orphan" || true
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
    docker compose --env-file .env -f deploy/compose/docker-compose.auth.yml up -d --force-recreate --build role-auth 2>&1 | grep -v "orphan" || true

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
    echo "Starting: Global Prometheus, Pushgateway, Unified Grafana..."
    docker compose --env-file .env -f deploy/compose/docker-compose.infra.yml up -d --force-recreate \
        global-prometheus pushgateway unified-grafana 2>&1 | grep -v "orphan" || true

    wait_for_health "global-prometheus" $PROMETHEUS_TIMEOUT || log_warn "Prometheus may still be loading data"
    wait_for_health "${PLATFORM_PREFIX:-shml}-pushgateway" $DEFAULT_TIMEOUT || log_warn "Pushgateway may still be starting"
    wait_for_health "unified-grafana" $GRAFANA_TIMEOUT || log_warn "Grafana may still be initializing"

    # ML SLO Exporter (depends on MLflow/Ray APIs existing on network)
    echo "Starting: ML SLO Exporter..."
    docker compose --env-file .env -f deploy/compose/docker-compose.infra.yml up -d --force-recreate \
        ml-slo-exporter 2>&1 | grep -v "orphan" || true
    wait_for_health "${PLATFORM_PREFIX:-shml}-ml-slo-exporter" $DEFAULT_TIMEOUT || log_warn "ML SLO Exporter may still be starting"

    log_success "Monitoring ready (Prometheus, Pushgateway, Grafana, SLO Exporter)"
    echo ""

    # =========================================================================
    # Phase 6: MLflow Services (Protected by OAuth2)
    # =========================================================================
    log_info "━━━ Phase 6: MLflow Services (Protected by OAuth2) ━━━"
    echo "Starting: MLflow server, Nginx, API, Prometheus..."
    ensure_network
    docker compose --env-file .env -f mlflow-server/docker-compose.yml up -d --force-recreate \
        mlflow-server mlflow-prometheus 2>&1 | grep -v "orphan" || true

    wait_for_health "mlflow-server" $MLFLOW_TIMEOUT || log_warn "MLflow server may still be initializing"

    docker compose --env-file .env -f mlflow-server/docker-compose.yml up -d --force-recreate \
        mlflow-nginx mlflow-api 2>&1 | grep -v "orphan" || true

    wait_for_health "mlflow-nginx" $DEFAULT_TIMEOUT || log_warn "MLflow nginx may still be starting"
    log_success "MLflow services ready"
    echo ""

    # =========================================================================
    # Phase 7: Ray Compute (Protected by OAuth2)
    # IMPORTANT: MPS daemon must be stopped before Ray starts, otherwise
    # torch.cuda.is_available() will hang indefinitely in the container.
    # See LESSONS LEARNED #7 above for details.
    # =========================================================================
    log_info "━━━ Phase 7: Ray Compute (Protected by OAuth2) ━━━"

    # Stop MPS daemon if running (blocks Docker GPU access)
    if check_mps_status; then
        stop_mps_daemon
    fi

    # Verify GPU access before starting Ray
    verify_gpu_access || log_warn "GPU access check failed - Ray may not have GPU access"

    # Run database migration before starting Ray API
    migrate_ray_database || log_warn "Database migration skipped"

    echo "Starting: Ray head, API, Prometheus..."
    ensure_network
    docker compose --env-file .env -f ray_compute/docker-compose.yml up -d --force-recreate \
        ray-head ray-prometheus 2>&1 | grep -v "orphan" || true

    wait_for_health "ray-head" $RAY_TIMEOUT || log_warn "Ray head may still be initializing"

    # Verify Ray has GPU access
    echo -n "  Verifying Ray GPU access..."
    if timeout 30 docker exec ray-head python3 -c "import torch; assert torch.cuda.is_available(), 'No GPU'" 2>/dev/null; then
        local ray_gpus=$(docker exec ray-head python3 -c "import torch; print(torch.cuda.device_count())" 2>/dev/null || echo "?")
        echo -e " ${GREEN}✓${NC} ($ray_gpus GPU(s))"
    else
        echo -e " ${YELLOW}⚠${NC} (Ray may not have GPU access)"
        log_warn "Ray GPU access failed - check if MPS daemon is still running"
    fi

    docker compose --env-file .env -f ray_compute/docker-compose.yml up -d --force-recreate \
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
    # Phase 9: Main Inference Gateway (Qwen3-VL + Z-Image + Gateway + P4 Services)
    # =========================================================================
    log_info "━━━ Phase 9: Main Inference Gateway (Viewer+ Access) ━━━"
    if [ "$OPTIONAL_AI_STACK_ENABLED" != "true" ]; then
        log_warn "Boot-safe mode active — skipping optional inference GPU stack to protect the desktop GPU"
    elif [ -f "inference/docker-compose.inference.yml" ]; then
        echo "Starting: Qwen3-VL (RTX 2070), Z-Image (RTX 2070), Gateway, PII-Blur (RTX 2070), Audio-Copyright (CPU)..."
        # Ensure network exists before starting (compose file uses external: true)
        ensure_network
        dc_up inference/docker-compose.inference.yml --force-recreate

        if [ -f "inference/gpu-manager/docker-compose.yml" ]; then
            echo "Starting: Unified GPU Manager..."
            dc_up inference/gpu-manager/docker-compose.yml --force-recreate
            wait_for_health "gpu-manager" ${GPU_MANAGER_TIMEOUT:-60} || log_warn "GPU manager may still be initializing"
        fi

        # Model loading takes significant time - extended timeouts
        QWEN3_VL_TIMEOUT=${QWEN3_VL_TIMEOUT:-300}
        Z_IMAGE_TIMEOUT=${Z_IMAGE_TIMEOUT:-300}
        INFERENCE_GW_TIMEOUT=${INFERENCE_GW_TIMEOUT:-30}
        PII_BLUR_TIMEOUT=${PII_BLUR_TIMEOUT:-300}
        AUDIO_COPYRIGHT_TIMEOUT=${AUDIO_COPYRIGHT_TIMEOUT:-120}

        echo "  Waiting for Qwen3-VL LLM (8B INT4 on RTX 2070)..."
        wait_for_health "qwen3-vl-api" $QWEN3_VL_TIMEOUT || log_warn "Qwen3-VL may still be loading (INT4 quantization takes 2-3 minutes)"

        echo "  Waiting for Z-Image generator (on-demand, RTX 2070)..."
        wait_for_health "z-image-api" $Z_IMAGE_TIMEOUT || log_warn "Z-Image may still be loading (can take 3-5 minutes)"

        echo "  Waiting for Inference Gateway (queue/rate limiting/history)..."
        wait_for_health "inference-gateway" $INFERENCE_GW_TIMEOUT || log_error "Inference Gateway failed to start"

        echo "  Waiting for PII Blur API (YOLOv8l + SAM3 on RTX 2070)..."
        wait_for_health "pii-blur-api" $PII_BLUR_TIMEOUT || log_warn "PII Blur API may still be loading"

        echo "  Waiting for Audio Copyright API (fingerprinting + MusicGen)..."
        wait_for_health "audio-copyright-api" $AUDIO_COPYRIGHT_TIMEOUT || log_warn "Audio Copyright API may still be loading"

        log_success "Main inference gateway services started"
    else
        log_warn "Main inference gateway configuration not found - skipping"
    fi
    echo ""

    # Start embedding service (CPU-based, no GPU dependencies)
    if [ -f "inference/embedding-service/docker-compose.yml" ]; then
        echo "Starting: Embedding Service (CPU-based sentence-transformers)..."
        dc_up inference/embedding-service/docker-compose.yml --force-recreate

        EMBEDDING_TIMEOUT=${EMBEDDING_TIMEOUT:-60}
        echo "  Waiting for embedding service (model loading ~60s)..."
        wait_for_health "${PLATFORM_PREFIX:-shml}-embedding-service" $EMBEDDING_TIMEOUT || log_warn "Embedding service may still be loading"

        log_success "Embedding service started"
    else
        log_warn "Embedding service configuration not found - skipping"
    fi
    echo ""

    # =========================================================================
    # Phase 9a: Coding Model Services (Protected by OAuth2 - Developer role)
    # =========================================================================
    log_info "━━━ Phase 9a: Coding Model Services (Developer+ Access) ━━━"
    if [ "$OPTIONAL_AI_STACK_ENABLED" != "true" ]; then
        log_warn "Boot-safe mode active — skipping coding model services on startup"
    elif [ -f "inference/nemotron/docker-compose.yml" ] || [ -f "inference/coding-model/docker-compose.yml" ]; then
        echo "Starting: Coding Models (Primary: 30B on 3090Ti, Fallback: 3B on 2070)..."
        # Ensure network exists before starting (compose file uses external: true)
        ensure_network

        # Model loading takes time, use extended timeout
        CODING_MODEL_TIMEOUT=${CODING_MODEL_TIMEOUT:-300}

        if [ -f "inference/nemotron/docker-compose.yml" ]; then
            dc_up inference/nemotron/docker-compose.yml --force-recreate
            echo "  Waiting for Nemotron primary model (30B on RTX 3090Ti)..."
            wait_for_health "nemotron-coding" $CODING_MODEL_TIMEOUT || log_warn "Nemotron may still be loading (this can take 2-5 minutes)"
        else
            log_warn "Nemotron configuration not found - skipping primary coding model"
        fi

        if [ -f "inference/coding-model/docker-compose.yml" ]; then
            dc_up inference/coding-model/docker-compose.yml --force-recreate
            echo "  Waiting for fallback model (3B)..."
            wait_for_health "coding-model-fallback" 180 || log_warn "Fallback model may still be loading"
        else
            log_warn "Fallback coding model configuration not found - skipping"
        fi

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
    if [ "$OPTIONAL_AI_STACK_ENABLED" != "true" ]; then
        log_warn "Boot-safe mode active — skipping Chat API because its model backends are disabled"
    elif [ -f "inference/chat-api/docker-compose.yml" ]; then
        echo "Starting: Chat API (OpenAI-compatible endpoint for Cursor/editors)..."
        ensure_network
        docker compose --env-file .env -f inference/chat-api/docker-compose.yml up -d --force-recreate 2>&1 | grep -v "orphan" || true

        # Wait for Chat API to be healthy
        wait_for_health "${PLATFORM_PREFIX:-shml}-chat-api" $DEFAULT_TIMEOUT || log_warn "Chat API may still be starting"
        log_success "Chat API service started"
    else
        log_warn "Chat API configuration not found - skipping"
    fi
    echo ""

    # =========================================================================
    # Phase 9c: Chat UI Service (Web interface for chat)
    # =========================================================================
    log_info "━━━ Phase 9c: Chat UI Service ━━━"
    if [ -f "chat-ui-v2/docker-compose.yml" ]; then
        echo "Starting: Chat UI (Web interface)..."
        ensure_network
        docker compose --env-file .env -f chat-ui-v2/docker-compose.yml up -d --force-recreate 2>&1 | grep -v "orphan" || true

        # Wait for Chat UI to be healthy
        wait_for_health "${PLATFORM_PREFIX:-shml}-chat-ui" $DEFAULT_TIMEOUT || log_warn "Chat UI may still be starting"
        log_success "Chat UI service started"
    else
        log_warn "Chat UI configuration not found - skipping"
    fi
    echo ""

    # =========================================================================
    # Phase 9d: Code Server (VS Code IDE - Admin Only)
    # Requires: OAuth2 middleware + role-auth-admin middleware
    # =========================================================================
    log_info "━━━ Phase 9d: Code Server (Admin Only) ━━━"
    echo "Starting: VS Code IDE with GitHub Copilot..."
    docker compose --env-file .env -f deploy/compose/docker-compose.infra.yml up -d --force-recreate code-server 2>&1 | grep -v "orphan" || true

    # Wait for code-server health
    wait_for_health "${PLATFORM_PREFIX:-shml}-code-server" $DEFAULT_TIMEOUT || log_warn "Code Server may still be starting"

    # Install Copilot extensions if not present
    echo -n "  Checking GitHub Copilot extensions..."
    if ! docker exec "${PLATFORM_PREFIX:-shml}-code-server" code-server --list-extensions 2>/dev/null | grep -q "github.copilot"; then
        echo -e " installing..."
        docker exec "${PLATFORM_PREFIX:-shml}-code-server" code-server --install-extension GitHub.copilot --install-extension GitHub.copilot-chat 2>/dev/null || log_warn "Copilot installation may require manual setup"
        log_success "Copilot extensions installed"
    else
        echo -e " ${GREEN}✓${NC} already installed"
    fi

    log_success "Code Server ready (accessible at /ide - admin only)"
    echo ""

    # =========================================================================
    # Phase 9e: Agent Service (ACE-based Autonomous Agent - Developer+ Access)
    # Requires: Postgres, Redis, Coding Models, Inference Gateway
    # =========================================================================
    log_info "━━━ Phase 9e: Agent Service (Developer+ Access) ━━━"
    if [ "$OPTIONAL_AI_STACK_ENABLED" != "true" ]; then
        log_warn "Boot-safe mode active — skipping Agent Service to avoid GPU/memory pressure on desktop restarts"
    elif [ -f "inference/agent-service/docker-compose.yml" ]; then
        echo "Starting: ACE Agent Service (LangGraph G-R-C workflow)..."
        ensure_network
        docker compose --env-file .env -f inference/agent-service/docker-compose.yml up -d --force-recreate --build 2>&1 | grep -v "orphan" || true

        # Wait for agent service health
        AGENT_TIMEOUT=${AGENT_TIMEOUT:-60}
        echo "  Waiting for agent service (embedding model loading ~60s)..."
        wait_for_health "${PLATFORM_PREFIX:-shml}-agent-service" $AGENT_TIMEOUT || log_warn "Agent service may still be initializing"

        log_success "Agent service started (accessible at /api/agent - developer+ only)"
    else
        log_warn "Agent service configuration not found - skipping"
    fi
    echo ""

    # =========================================================================
    # Phase 10: Observability Services
    # =========================================================================
    log_info "━━━ Phase 10: Observability & Landing Page ━━━"
    echo "Starting: Homer (landing), Dozzle (logs), Postgres Backup..."
    # Force recreate Homer to ensure config mounts are fresh
    docker compose --env-file .env -f deploy/compose/docker-compose.infra.yml up -d --force-recreate homer 2>&1 | grep -v "orphan" || true
    docker compose --env-file .env -f deploy/compose/docker-compose.infra.yml up -d --force-recreate dozzle postgres-backup 2>&1 | grep -v "orphan" || true

    # FiftyOne visual dataset curation (depends on fiftyone-mongodb)
    echo "Starting: FiftyOne (dataset curation)..."
    docker compose --env-file .env -f deploy/compose/docker-compose.infra.yml up -d --force-recreate \
        fiftyone-mongodb fiftyone 2>&1 | grep -v "orphan" || true

    # Wait for services
    wait_for_health "homer" $DEFAULT_TIMEOUT || log_warn "Homer may still be starting"
    wait_for_health "postgres-backup" $DEFAULT_TIMEOUT || log_warn "Postgres Backup may still be starting"
    wait_for_health "${PLATFORM_PREFIX:-shml}-fiftyone-mongodb" $DEFAULT_TIMEOUT || log_warn "FiftyOne MongoDB may still be starting"
    wait_for_health "${PLATFORM_PREFIX:-shml}-fiftyone" $DEFAULT_TIMEOUT || log_warn "FiftyOne may still be starting"

    # Dozzle doesn't have healthcheck (minimal image)
    if docker ps --format '{{.Names}}' | grep -q "^dozzle$"; then
        log_success "Dozzle running"
    else
        log_warn "Dozzle may not have started"
    fi

    log_success "Observability services ready"
    echo ""

    # =========================================================================
    # Phase 10.5: Self-Healing Watchdog
    # =========================================================================
    log_info "━━━ Phase 10.5: Self-Healing Watchdog ━━━"
    echo "Starting: Watchdog (container health), Watchdog Admin, Alertmanager..."
    dc_up deploy/compose/docker-compose.watchdog.yml

    # Wait for watchdog to be running
    sleep 3
    if docker ps --format '{{.Names}}' | grep -q "watchdog"; then
        log_success "Watchdog self-healing active"
    else
        log_warn "Watchdog may not have started — containers will NOT auto-recover"
    fi
    echo ""

    # =========================================================================
    # Phase 11: Generate Container ID Mapping (for Grafana dashboards)
    # =========================================================================
    log_info "━━━ Phase 11: Container Metrics Mapping ━━━"
    echo "Generating container ID to name mapping for Grafana..."
    if [ -x "${SCRIPT_DIR}/scripts/generate_container_mapping.sh" ]; then
        "${SCRIPT_DIR}/scripts/generate_container_mapping.sh" >/dev/null 2>&1 && \
            log_success "Container mapping generated" || \
            log_warn "Container mapping generation failed"
    else
        log_warn "Container mapping script not found"
    fi
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
            echo -e "${YELLOW}  Fix: Set 'healthcheck: disable: true' in deploy/compose/docker-compose.infra.yml${NC}"
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
    local TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "${TAILSCALE_IP:-}")
    local PUBLIC_DOMAIN=$(detect_tailscale_public_domain)
    [ -n "$PUBLIC_DOMAIN" ] || PUBLIC_DOMAIN="${PUBLIC_DOMAIN:-}"

    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    log_success "Platform startup complete!"
    echo ""
    echo "Service Status:"
    docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAME|traefik|postgres|redis|mlflow|ray|grafana|prometheus|fusionauth|oauth2|cadvisor|node-exporter|dozzle|homer|backup|coding-model|chat-api|code-server|nessie|fiftyone|slo-exporter" || true
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
        echo "  Data Platform (Developer role required):"
        echo "  • Nessie Catalog:    https://${PUBLIC_DOMAIN}/nessie/"
        echo "  • FiftyOne:          https://${PUBLIC_DOMAIN}/fiftyone/"
        echo ""
        echo "  Admin-Only Services:"
        echo "  • VS Code IDE:       https://${PUBLIC_DOMAIN}/ide/ (with GitHub Copilot)"
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
    echo "  Data Platform (Developer role required):"
    echo "  • Nessie Catalog:  http://${LAN_IP}/nessie/"
    echo "  • FiftyOne:        http://${LAN_IP}/fiftyone/"
    echo ""
    echo "  Inference APIs (Developer role required):"
    echo "  • Coding Model:    http://${LAN_IP}/api/coding/v1/chat/completions"
    echo ""
    echo "  Admin-Only Services:"
    echo "  • VS Code IDE:     http://${LAN_IP}/ide/ (with GitHub Copilot)"
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
            echo "  FIX: In deploy/compose/docker-compose.auth.yml, change:"
            echo "       healthcheck:"
            echo "         disable: true"
            echo ""
            echo "  Then run: docker compose --env-file .env -f deploy/compose/docker-compose.auth.yml up -d --force-recreate oauth2-proxy"
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
        echo "  # Edit deploy/compose/docker-compose.auth.yml and change oauth2-proxy healthcheck to:"
        echo "  #   healthcheck:"
        echo "  #     disable: true"
        echo ""
        echo "  # Then restart:"
        echo "  docker compose --env-file .env -f deploy/compose/docker-compose.auth.yml up -d --force-recreate oauth2-proxy"
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
    local FUSIONAUTH_API_KEY="${FUSIONAUTH_API_KEY:?FUSIONAUTH_API_KEY must be set}"
    local OAUTH_CLIENT_ID="${OAUTH2_PROXY_CLIENT_ID:?OAUTH2_PROXY_CLIENT_ID must be set}"
    local PUBLIC_DOMAIN="${PUBLIC_DOMAIN:?PUBLIC_DOMAIN must be set}"

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

# =============================================================================
# Individual Service Start Functions
# =============================================================================

# Helper function to update container ID mapping for Grafana dashboards
update_container_mapping() {
    # Generate JSON mapping file
    if [ -x "${SCRIPT_DIR}/scripts/generate_container_mapping.sh" ]; then
        "${SCRIPT_DIR}/scripts/generate_container_mapping.sh" >/dev/null 2>&1 || true
    fi
    # Generate Prometheus metrics file for container name labels
    if [ -x "${SCRIPT_DIR}/scripts/generate_container_name_metrics.sh" ]; then
        "${SCRIPT_DIR}/scripts/generate_container_name_metrics.sh" >/dev/null 2>&1 || true
    fi
}

start_infra() {
    log_info "━━━ Starting Infrastructure (Core Layer) ━━━"
    dc_up deploy/compose/docker-compose.core.yml
    wait_for_health "${PLATFORM_PREFIX:-shml}-postgres" $POSTGRES_TIMEOUT
    wait_for_health "${PLATFORM_PREFIX:-shml}-traefik" $TRAEFIK_TIMEOUT
    update_container_mapping
    log_success "Infrastructure started (Traefik + PostgreSQL + Redis)"
}

start_auth() {
    log_info "━━━ Starting Auth Services (Auth Layer) ━━━"
    dc_up deploy/compose/docker-compose.auth.yml
    wait_for_health "fusionauth" $FUSIONAUTH_TIMEOUT
    wait_for_health "${PLATFORM_PREFIX:-shml}-role-auth" ${DEFAULT_TIMEOUT} || log_warn "role-auth may still be starting"
    update_container_mapping
    log_success "Auth services started (FusionAuth + OAuth2 Proxy + role-auth)"
}

start_mlflow() {
    log_info "━━━ Starting MLflow Services Only ━━━"
    ensure_network
    docker compose --env-file .env -f mlflow-server/docker-compose.yml up -d --force-recreate 2>&1 | grep -v "orphan" || true
    wait_for_health "mlflow-server" $MLFLOW_TIMEOUT
    update_container_mapping
    log_success "MLflow services started"
}

# =============================================================================
# Ray Database Migration
# Ensures database schema is compatible with SQLAlchemy models
# =============================================================================

migrate_ray_database() {
    log_info "━━━ Migrating Ray Compute Database ━━━"

    local POSTGRES_CONTAINER="${PLATFORM_PREFIX:-shml}-postgres"

    # Check if postgres container is running
    if ! docker inspect "$POSTGRES_CONTAINER" >/dev/null 2>&1; then
        log_warn "PostgreSQL container not running, skipping migration"
        return 1
    fi

    # Check if ray_compute database exists
    if ! docker exec "$POSTGRES_CONTAINER" psql -U postgres -lqt 2>/dev/null | cut -d \| -f 1 | grep -qw ray_compute; then
        log_info "Creating ray_compute database..."
        docker exec "$POSTGRES_CONTAINER" psql -U postgres -c "CREATE DATABASE ray_compute;" 2>/dev/null || true
        docker exec "$POSTGRES_CONTAINER" psql -U postgres -c "CREATE USER ray_compute WITH ENCRYPTED PASSWORD 'ray_compute';" 2>/dev/null || true
        docker exec "$POSTGRES_CONTAINER" psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE ray_compute TO ray_compute;" 2>/dev/null || true
        log_success "Created ray_compute database"
    fi

    # Check if migration file exists
    if [ ! -f "ray_compute/config/migrate_schema.sql" ]; then
        log_warn "Migration file not found, skipping"
        return 0
    fi

    # Run migration script
    log_info "Applying database migrations..."
    if docker exec -i "$POSTGRES_CONTAINER" psql -U postgres -d ray_compute < ray_compute/config/migrate_schema.sql 2>&1 | grep -E "(NOTICE|ERROR|Migration complete)"; then
        log_success "Database migration complete"
    else
        log_warn "Migration had issues, check database manually"
    fi

    # Grant permissions to ray_compute user
    docker exec "$POSTGRES_CONTAINER" psql -U postgres -d ray_compute -c "GRANT ALL ON ALL TABLES IN SCHEMA public TO ray_compute;" 2>/dev/null || true
    docker exec "$POSTGRES_CONTAINER" psql -U postgres -d ray_compute -c "GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO ray_compute;" 2>/dev/null || true

    return 0
}

start_ray() {
    log_info "━━━ Starting Ray Services Only ━━━"
    ensure_network

    # Run database migration before starting Ray API
    migrate_ray_database || log_warn "Database migration skipped"

    docker compose --env-file .env -f ray_compute/docker-compose.yml up -d --force-recreate 2>&1 | grep -v "orphan" || true
    wait_for_health "ray-head" $RAY_TIMEOUT
    update_container_mapping
    log_success "Ray services started"
}

start_inference() {
    log_info "━━━ Starting Inference Services Only ━━━"
    ensure_network

    # Main inference gateway (Qwen3-VL + Z-Image + Gateway + PII Blur + Audio Copyright)
    if [ -f "inference/docker-compose.inference.yml" ]; then
        echo "Starting main inference gateway (Qwen3-VL, Z-Image, Gateway, PII-Blur, Audio-Copyright)..."
        dc_up inference/docker-compose.inference.yml --force-recreate
        if [ -f "inference/gpu-manager/docker-compose.yml" ]; then
            echo "Starting unified GPU manager..."
            dc_up inference/gpu-manager/docker-compose.yml --force-recreate
            wait_for_health "gpu-manager" ${GPU_MANAGER_TIMEOUT:-60} || log_warn "GPU manager may still be initializing"
        fi
        wait_for_health "qwen3-vl-api" ${QWEN3_VL_TIMEOUT:-300} || log_warn "Qwen3-VL may still be loading"
        wait_for_health "z-image-api" ${Z_IMAGE_TIMEOUT:-300} || log_warn "Z-Image may still be loading"
        wait_for_health "inference-gateway" ${INFERENCE_GW_TIMEOUT:-30}

        # P4 Content Creator Platform - PII Face Blurring (RTX 2070)
        wait_for_health "pii-blur-api" ${PII_BLUR_TIMEOUT:-300} || log_warn "PII Blur API may still be loading (YOLOv8l + SAM3)"

        # P4 Content Creator Platform - Audio Copyright Detection (CPU)
        wait_for_health "audio-copyright-api" ${AUDIO_COPYRIGHT_TIMEOUT:-120} || log_warn "Audio Copyright API may still be loading"
    fi

    # Embedding service (CPU-based)
    if [ -f "inference/embedding-service/docker-compose.yml" ]; then
        echo "Starting embedding service..."
        dc_up inference/embedding-service/docker-compose.yml --force-recreate
        wait_for_health "${PLATFORM_PREFIX:-shml}-embedding-service" ${EMBEDDING_TIMEOUT:-60} || log_warn "Embedding service may still be loading"
    fi

    # Nemotron coding model (PRIMARY - RTX 3090 Ti)
    # Replaces Qwen2.5-Coder-32B with superior quality (95% vs 90% Claude Sonnet)
    if [ -f "inference/nemotron/docker-compose.yml" ]; then
        echo "Starting Nemotron-3-Nano-30B primary coding model (RTX 3090 Ti)..."
        dc_up inference/nemotron/docker-compose.yml --force-recreate
        wait_for_health "nemotron-coding" ${NEMOTRON_TIMEOUT:-300} || log_warn "Nemotron may still be loading (22GB model)"
    fi

    # Coding model fallback (FALLBACK - RTX 2070)
    # Also available for agentic services (vision, etc.) when needed
    if [ -f "inference/coding-model/docker-compose.yml" ]; then
        echo "Starting coding model fallback (RTX 2070) + agentic services..."
        dc_up inference/coding-model/docker-compose.yml --force-recreate
        wait_for_health "coding-model-fallback" 180 || log_warn "Fallback model may still be loading"
        # Note: coding-model-primary is now deprecated, replaced by Nemotron
    fi

    # Chat API (Developer+ access)
    if [ -f "inference/chat-api/docker-compose.yml" ]; then
        echo "Starting chat API..."
        docker compose --env-file .env -f inference/chat-api/docker-compose.yml up -d --force-recreate 2>&1 | grep -v "orphan" || true
        wait_for_health "${PLATFORM_PREFIX:-shml}-chat-api" $DEFAULT_TIMEOUT
    fi

    # Chat UI (Developer+ access)
    if [ -f "chat-ui-v2/docker-compose.yml" ]; then
        echo "Starting chat UI..."
        docker compose --env-file .env -f chat-ui-v2/docker-compose.yml up -d --force-recreate 2>&1 | grep -v "orphan" || true
        wait_for_health "${PLATFORM_PREFIX:-shml}-chat-ui" $DEFAULT_TIMEOUT
    fi

    update_container_mapping
    log_success "Inference services started"
}

start_monitoring() {
    log_info "━━━ Starting Monitoring (Monitoring Layer) ━━━"
    dc_up deploy/compose/docker-compose.monitoring.yml

    wait_for_health "global-prometheus" $PROMETHEUS_TIMEOUT
    wait_for_health "${PLATFORM_PREFIX:-shml}-pushgateway" $DEFAULT_TIMEOUT || log_warn "Pushgateway may still be starting"
    wait_for_health "unified-grafana" $GRAFANA_TIMEOUT

    # DCGM exporter for GPU metrics (optional — requires NVIDIA drivers)
    if [ -f "monitoring/dcgm-exporter/docker-compose.yml" ] && \
       docker compose -f monitoring/dcgm-exporter/docker-compose.yml config >/dev/null 2>&1; then
        echo "Starting: DCGM Exporter (GPU metrics)..."
        dc_up monitoring/dcgm-exporter/docker-compose.yml
        log_success "DCGM exporter started"
    fi

    # Loki + Promtail (log aggregation)
    if [ -f "deploy/compose/docker-compose.logging.yml" ]; then
        echo "Starting: Loki + Promtail (log aggregation)..."
        dc_up deploy/compose/docker-compose.logging.yml
        wait_for_health "loki" ${LOKI_TIMEOUT:-60} || log_warn "Loki may still be starting"
        wait_for_health "promtail" ${PROMTAIL_TIMEOUT:-30} || log_warn "Promtail may still be starting"
    fi

    # Tempo + OpenTelemetry (distributed tracing)
    if [ -f "deploy/compose/docker-compose.tracing.yml" ]; then
        echo "Starting: Tempo + OpenTelemetry (distributed tracing)..."
        dc_up deploy/compose/docker-compose.tracing.yml
        wait_for_health "tempo" ${TEMPO_TIMEOUT:-60} || log_warn "Tempo may still be starting"
        wait_for_health "otel-collector" ${OTEL_TIMEOUT:-30} || log_warn "OTel Collector may still be starting"
    fi

    update_container_mapping
    log_success "Monitoring services started (Prometheus, Pushgateway, Grafana, DCGM, Loki, Tempo)"
}

start_devtools() {
    log_info "━━━ Starting Development Tools (DevTools Layer) ━━━"

    # Verify prerequisites (OAuth middleware must exist)
    if ! curl -sf "http://localhost:8090/api/http/middlewares/oauth2-auth@docker" >/dev/null 2>&1; then
        log_warn "oauth2-auth middleware not found - devtools OAuth won't work"
        log_warn "Start auth services first: ./start_all_safe.sh start auth"
    fi

    if ! curl -sf "http://localhost:8090/api/http/middlewares/role-auth-admin@docker" >/dev/null 2>&1; then
        log_warn "role-auth-admin middleware not found - starting role-auth first"
        dc_up deploy/compose/docker-compose.auth.yml role-auth
        wait_for_middleware "role-auth-admin" 30 || log_error "role-auth-admin middleware failed to register"
    fi

    dc_up deploy/compose/docker-compose.devtools.yml
    wait_for_health "${PLATFORM_PREFIX:-shml}-code-server" $DEFAULT_TIMEOUT || log_warn "Code Server may still be starting"

    # Install Copilot if not present
    if ! docker exec "${PLATFORM_PREFIX:-shml}-code-server" code-server --list-extensions 2>/dev/null | grep -q "github.copilot"; then
        echo "Installing GitHub Copilot extensions..."
        docker exec "${PLATFORM_PREFIX:-shml}-code-server" code-server \
            --install-extension GitHub.copilot \
            --install-extension GitHub.copilot-chat 2>/dev/null || true
    fi

    update_container_mapping
    log_success "Development tools started (VS Code IDE at /ide, Homer, GitLab, FiftyOne, Nessie, SBA Portal)"
}

start_agent() {
    log_info "━━━ Starting Agent Service Only ━━━"
    ensure_network

    # Verify prerequisites
    if ! docker ps --format '{{.Names}}' | grep -q "^${PLATFORM_PREFIX:-shml}-postgres$"; then
        log_warn "PostgreSQL not running - starting infrastructure first"
        start_infra
    fi

    if ! docker ps --format '{{.Names}}' | grep -Eq "^(nemotron-coding|coding-model-fallback)$"; then
        log_warn "Coding models not running - agent service requires them"
        log_warn "Start inference services first: ./start_all_safe.sh start inference"
    fi

    # Start agent service
    if [ -f "inference/agent-service/docker-compose.yml" ]; then
        echo "Starting ACE Agent Service (LangGraph G-R-C workflow)..."
        docker compose --env-file .env -f inference/agent-service/docker-compose.yml up -d --force-recreate --build 2>&1 | grep -v "orphan" || true
        wait_for_health "${PLATFORM_PREFIX:-shml}-agent-service" ${AGENT_TIMEOUT:-60} || log_warn "Agent service may still be initializing"
        update_container_mapping
        log_success "Agent service started (accessible at /api/agent - developer+ only)"
    else
        log_error "Agent service configuration not found at inference/agent-service/docker-compose.yml"
        exit 1
    fi
}

start_sba_portal() {
    log_info "━━━ Starting SBA Resource Portal ━━━"
    ensure_network

    # Verify prerequisites (OAuth middleware must exist for developer role)
    if ! curl -sf "http://localhost:8090/api/http/middlewares/oauth2-auth@docker" >/dev/null 2>&1; then
        log_warn "oauth2-auth middleware not found - SBA Portal OAuth won't work"
        log_warn "Start auth services first: ./start_all_safe.sh start auth"
    fi

    if ! curl -sf "http://localhost:8090/api/http/middlewares/role-auth-developer@docker" >/dev/null 2>&1; then
        log_warn "role-auth-developer middleware not found - starting role-auth first"
        dc_up deploy/compose/docker-compose.auth.yml role-auth
        wait_for_middleware "role-auth-developer" 30 || log_error "role-auth-developer middleware failed to register"
    fi

    echo "Building and starting SBA Resource Portal (Gemini AI Document Q&A)..."
    dc_up deploy/compose/docker-compose.devtools.yml sba-resource-portal
    wait_for_health "${PLATFORM_PREFIX:-shml}-sba-resource-portal" ${SBA_PORTAL_TIMEOUT:-60} || log_warn "SBA Portal may still be starting"

    update_container_mapping
    log_success "SBA Resource Portal started (accessible at /sba-portal/ - developer+ only)"
}

# =============================================================================
# STOP functions: pause containers (fast, keeps state — use for temporary stops)
# DOWN functions: remove containers cleanly (use before restart)
# =============================================================================

stop_infra() {
    log_info "━━━ Stopping Infrastructure ━━━"
    dc_stop deploy/compose/docker-compose.core.yml
    log_success "Infrastructure stopped"
}

down_infra() {
    log_info "━━━ Removing Infrastructure Containers ━━━"
    dc_down deploy/compose/docker-compose.core.yml
    log_success "Infrastructure containers removed"
}

stop_auth() {
    log_info "━━━ Stopping Auth Services ━━━"
    dc_stop deploy/compose/docker-compose.auth.yml
    log_success "Auth services stopped"
}

down_auth() {
    log_info "━━━ Removing Auth Containers ━━━"
    dc_down deploy/compose/docker-compose.auth.yml
    log_success "Auth containers removed"
}

stop_mlflow() {
    log_info "━━━ Stopping MLflow Services ━━━"
    dc_stop mlflow-server/docker-compose.yml
    log_success "MLflow services stopped"
}

down_mlflow() {
    log_info "━━━ Removing MLflow Containers ━━━"
    dc_down mlflow-server/docker-compose.yml
    log_success "MLflow containers removed"
}

stop_ray() {
    log_info "━━━ Stopping Ray Services ━━━"
    dc_stop ray_compute/docker-compose.yml
    log_success "Ray services stopped"
}

down_ray() {
    log_info "━━━ Removing Ray Containers ━━━"
    dc_down ray_compute/docker-compose.yml
    log_success "Ray containers removed"
}

stop_inference() {
    log_info "━━━ Stopping Inference Services ━━━"
    dc_stop inference/docker-compose.inference.yml
    dc_stop inference/gpu-manager/docker-compose.yml
    dc_stop inference/embedding-service/docker-compose.yml
    dc_stop inference/coding-model/docker-compose.yml
    dc_stop inference/nemotron/docker-compose.yml
    dc_stop inference/chat-api/docker-compose.yml
    dc_stop inference/agent-service/docker-compose.yml
    dc_stop chat-ui-v2/docker-compose.yml
    log_success "Inference services stopped"
}

down_inference() {
    log_info "━━━ Removing Inference Containers ━━━"
    dc_down inference/docker-compose.inference.yml
    dc_down inference/gpu-manager/docker-compose.yml
    dc_down inference/embedding-service/docker-compose.yml
    dc_down inference/coding-model/docker-compose.yml
    dc_down inference/nemotron/docker-compose.yml
    dc_down inference/chat-api/docker-compose.yml
    dc_down inference/agent-service/docker-compose.yml
    dc_down chat-ui-v2/docker-compose.yml
    log_success "Inference containers removed"
}

stop_monitoring() {
    log_info "━━━ Stopping Monitoring Services ━━━"
    dc_stop deploy/compose/docker-compose.monitoring.yml
    [ -f "monitoring/dcgm-exporter/docker-compose.yml" ] && \
        dc_stop monitoring/dcgm-exporter/docker-compose.yml
    [ -f "deploy/compose/docker-compose.logging.yml" ] && \
        dc_stop deploy/compose/docker-compose.logging.yml
    [ -f "deploy/compose/docker-compose.tracing.yml" ] && \
        dc_stop deploy/compose/docker-compose.tracing.yml
    log_success "Monitoring services stopped"
}

down_monitoring() {
    log_info "━━━ Removing Monitoring Containers ━━━"
    dc_down deploy/compose/docker-compose.monitoring.yml
    [ -f "monitoring/dcgm-exporter/docker-compose.yml" ] && \
        dc_down monitoring/dcgm-exporter/docker-compose.yml
    [ -f "deploy/compose/docker-compose.logging.yml" ] && \
        dc_down deploy/compose/docker-compose.logging.yml
    [ -f "deploy/compose/docker-compose.tracing.yml" ] && \
        dc_down deploy/compose/docker-compose.tracing.yml
    log_success "Monitoring containers removed"
}

stop_devtools() {
    log_info "━━━ Stopping Development Tools ━━━"
    dc_stop deploy/compose/docker-compose.devtools.yml
    log_success "Development tools stopped"
}

down_devtools() {
    log_info "━━━ Removing DevTools Containers ━━━"
    dc_down deploy/compose/docker-compose.devtools.yml
    log_success "DevTools containers removed"
}

stop_agent() {
    log_info "━━━ Stopping Agent Service ━━━"
    dc_stop inference/agent-service/docker-compose.yml
    log_success "Agent service stopped"
}

down_agent() {
    log_info "━━━ Removing Agent Containers ━━━"
    dc_down inference/agent-service/docker-compose.yml
    log_success "Agent containers removed"
}

stop_sba_portal() {
    log_info "━━━ Stopping SBA Resource Portal ━━━"
    dc_stop deploy/compose/docker-compose.devtools.yml sba-resource-portal
    log_success "SBA Resource Portal stopped"
}

down_sba_portal() {
    log_info "━━━ Removing SBA Portal Container ━━━"
    dc_down deploy/compose/docker-compose.devtools.yml sba-resource-portal
    log_success "SBA Portal container removed"
}

stop_watchdog() {
    log_info "━━━ Stopping Watchdog ━━━"
    dc_stop deploy/compose/docker-compose.watchdog.yml
    log_success "Watchdog stopped"
}

down_watchdog() {
    log_info "━━━ Removing Watchdog Containers ━━━"
    dc_down deploy/compose/docker-compose.watchdog.yml
    log_success "Watchdog containers removed"
}

# =============================================================================
# Main Entry Point
# =============================================================================

# Handle service-specific commands
SERVICE="${2:-}"

case "${1:-restart}" in
    start)
        case "$SERVICE" in
            infra|infrastructure)
                start_infra
                ;;
            auth|authentication)
                start_auth
                ;;
            mlflow)
                start_mlflow
                ;;
            ray)
                start_ray
                ;;
            inference|models|coding)
                start_inference
                ;;
            monitoring|mon)
                start_monitoring
                ;;
            devtools|dev|ide|code-server)
                start_devtools
                ;;
            agent|ace)
                start_agent
                ;;
            sba|sba-portal|gemini)
                start_sba_portal
                ;;
            "")
                # Start all services
                rebuild_images
                start_all_services
                ;;
            *)
                echo "Unknown service: $SERVICE"
                echo "Available: infra, auth, mlflow, ray, inference, monitoring, devtools, agent, sba-portal"
                exit 1
                ;;
        esac
        ;;
    stop)
        case "$SERVICE" in
            infra|infrastructure)
                stop_infra
                ;;
            auth|authentication)
                stop_auth
                ;;
            mlflow)
                stop_mlflow
                ;;
            ray)
                stop_ray
                ;;
            inference|models|coding)
                stop_inference
                ;;
            monitoring|mon)
                stop_monitoring
                ;;
            devtools|dev|ide|code-server)
                stop_devtools
                ;;
            agent|ace)
                stop_agent
                ;;
            sba|sba-portal|gemini)
                stop_sba_portal
                ;;
            "")
                # Stop all services
                stop_all_services
                ;;
            *)
                echo "Unknown service: $SERVICE"
                echo "Available: infra, auth, mlflow, ray, inference, monitoring, devtools, agent"
                exit 1
                ;;
        esac
        ;;
    restart)
        # restart = down (remove containers) + start (fresh recreate)
        # This ensures a clean slate and picks up any image updates.
        case "$SERVICE" in
            infra|infrastructure)
                down_infra && start_infra
                ;;
            auth|authentication)
                down_auth && start_auth
                ;;
            mlflow)
                down_mlflow && start_mlflow
                ;;
            ray)
                down_ray && start_ray
                ;;
            inference|models|coding)
                down_inference && start_inference
                ;;
            monitoring|mon)
                down_monitoring && start_monitoring
                ;;
            devtools|dev|ide|code-server)
                down_devtools && start_devtools
                ;;
            agent|ace)
                down_agent && start_agent
                ;;
            sba|sba-portal|gemini)
                down_sba_portal && start_sba_portal
                ;;
            watchdog)
                down_watchdog && dc_up deploy/compose/docker-compose.watchdog.yml
                ;;
            "")
                # Full restart: backup → down all → start all
                create_pre_restart_backup
                stop_all_services
                cleanup_containers
                rebuild_images
                start_all_services
                ;;
            *)
                echo "Unknown service: $SERVICE"
                echo "Available: infra, auth, mlflow, ray, inference, monitoring, devtools, agent, sba-portal, watchdog"
                exit 1
                ;;
        esac
        ;;
    down)
        # down: stop AND remove containers (no volume removal)
        # Faster than restart when you just want a clean container state.
        case "$SERVICE" in
            infra|infrastructure)   down_infra ;;
            auth|authentication)    down_auth ;;
            mlflow)                 down_mlflow ;;
            ray)                    down_ray ;;
            inference|models|coding) down_inference ;;
            monitoring|mon)         down_monitoring ;;
            devtools|dev|ide)       down_devtools ;;
            agent|ace)              down_agent ;;
            sba|sba-portal)         down_sba_portal ;;
            watchdog)               down_watchdog ;;
            "")
                stop_all_services
                cleanup_containers
                ;;
            *)
                echo "Unknown service: $SERVICE"
                exit 1
                ;;
        esac
        ;;
    pull)
        # pull: pull latest images from GitLab registry for a service group
        # Falls back to local/cached images if registry unreachable.
        # Use SHML_IMAGE_PULL_POLICY=always to force fail on registry miss.
        SHML_IMAGE_PULL_POLICY=${SHML_IMAGE_PULL_POLICY:-always}
        case "$SERVICE" in
            infra|infrastructure)   dc_pull deploy/compose/docker-compose.core.yml ;;
            auth|authentication)    dc_pull deploy/compose/docker-compose.auth.yml ;;
            mlflow)                 dc_pull mlflow-server/docker-compose.yml ;;
            ray)                    dc_pull ray_compute/docker-compose.yml ;;
            inference|models|coding)
                dc_pull inference/docker-compose.inference.yml
                dc_pull inference/gpu-manager/docker-compose.yml
                dc_pull inference/embedding-service/docker-compose.yml
                dc_pull inference/coding-model/docker-compose.yml
                dc_pull inference/nemotron/docker-compose.yml
                dc_pull inference/chat-api/docker-compose.yml
                ;;
            monitoring|mon)         dc_pull deploy/compose/docker-compose.monitoring.yml ;;
            devtools|dev)           dc_pull deploy/compose/docker-compose.devtools.yml ;;
            agent|ace)              dc_pull inference/agent-service/docker-compose.yml ;;
            "")
                log_info "Pulling images for all services..."
                dc_pull deploy/compose/docker-compose.core.yml
                dc_pull deploy/compose/docker-compose.auth.yml
                dc_pull deploy/compose/docker-compose.monitoring.yml
                dc_pull deploy/compose/docker-compose.devtools.yml
                dc_pull inference/docker-compose.inference.yml
                dc_pull mlflow-server/docker-compose.yml
                dc_pull ray_compute/docker-compose.yml
                log_success "Pull complete"
                ;;
            *)
                echo "Unknown service: $SERVICE"; exit 1 ;;
        esac
        ;;
    deploy)
        # deploy: pull from registry THEN start (registry-first workflow)
        # Equivalent to: pull [service] + start [service]
        log_info "Registry-first deploy: pull then start"
        SHML_IMAGE_PULL_POLICY=${SHML_IMAGE_PULL_POLICY:-always}
        "$0" pull "${SERVICE:-}"
        "$0" start "${SERVICE:-}"
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
        echo "Usage: $0 {start|stop|restart|down|pull|deploy|status|cleanup|diagnose|fix-oauth|build} [service]"
        echo ""
        echo "Commands:"
        echo "  start [service]   - Start service(s) (uses local/cached images)"
        echo "  stop [service]    - Pause service(s) (keeps containers, fast)"
        echo "  restart [service] - Remove + recreate service(s) (clean slate)"
        echo "  down [service]    - Remove containers without volume removal"
        echo "  pull [service]    - Pull latest images from GitLab registry"
        echo "  deploy [service]  - Pull from registry then start (registry-first)"
        echo "  status            - Show service status and access URLs"
        echo "  build             - Rebuild all container images only"
        echo "  cleanup           - Stop and remove all containers"
        echo "  diagnose          - Debug OAuth2/middleware issues"
        echo "  fix-oauth         - Fix FusionAuth OAuth client callback URLs"
        echo ""
        echo "Services:"
        echo "  infra      - Core layer (Traefik, Postgres[core-net], Redis[core-net])"
        echo "  auth       - Auth layer (FusionAuth, OAuth2 Proxy, Role Auth)"
        echo "  mlflow     - MLflow tracking server"
        echo "  ray        - Ray compute cluster"
        echo "  inference  - Coding models + Chat API + Chat UI"
        echo "  monitoring - Monitoring layer (Prometheus, Grafana, Alertmanager)"
        echo "  devtools   - DevTools layer (VS Code, Homer, GitLab, FiftyOne, Nessie)"
        echo "  watchdog   - Self-healing watchdog"
        echo "  agent      - ACE Agent Service (LangGraph G-R-C workflow)"
        echo ""
        echo "Registry:"
        echo "  SHML_IMAGE_PULL_POLICY=always   # Force pull (fail if registry down)"
        echo "  SHML_IMAGE_PULL_POLICY=missing  # Pull only if not local (default)"
        echo "  SHML_IMAGE_PULL_POLICY=never    # Skip pulls entirely"
        echo ""
        echo "Examples:"
        echo "  $0 start              # Start all services (local images)"
        echo "  $0 deploy             # Pull from registry then start all"
        echo "  $0 deploy inference   # Pull + start inference services only"
        echo "  $0 restart auth       # Remove auth containers then recreate"
        echo "  $0 down               # Remove all containers"
        echo "  $0 pull inference     # Pull inference images from registry"
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
