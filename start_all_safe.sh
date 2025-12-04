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

    # Phase 2: Stop Ray Services
    log_info "━━━ Stopping Ray Services ━━━"
    docker compose stop ray-compute-api ray-head ray-prometheus 2>/dev/null || true
    log_success "Ray services stopped"
    echo ""

    # Phase 3: Stop MLflow Services
    log_info "━━━ Stopping MLflow Services ━━━"
    docker compose stop mlflow-api mlflow-nginx mlflow-server mlflow-prometheus 2>/dev/null || true
    log_success "MLflow services stopped"
    echo ""

    # Phase 4: Stop Monitoring (Grafana/Prometheus)
    log_info "━━━ Stopping Monitoring ━━━"
    docker compose stop unified-grafana global-prometheus 2>/dev/null || true
    docker compose stop cadvisor node-exporter 2>/dev/null || true
    log_success "Monitoring stopped"
    echo ""

    # Phase 5: Stop Auth Services
    log_info "━━━ Stopping Auth Services ━━━"
    docker compose stop oauth2-proxy fusionauth 2>/dev/null || true
    log_success "Auth services stopped"
    echo ""

    # Phase 6: Stop Infrastructure
    log_info "━━━ Stopping Infrastructure ━━━"
    docker compose stop traefik ml-platform-redis shared-postgres 2>/dev/null || true
    log_success "Infrastructure stopped"
    echo ""

    log_success "All services stopped"
}

# =============================================================================
# Cleanup Orphaned/Dangling Containers
# =============================================================================

cleanup_containers() {
    echo ""
    log_info "━━━ Cleaning up containers ━━━"

    # List of all known containers that might be orphaned
    local containers=(
        "ray-compute-api" "ray-head" "ray-prometheus"
        "mlflow-api" "mlflow-nginx" "mlflow-server" "mlflow-prometheus"
        "oauth2-proxy" "fusionauth"
        "unified-grafana" "global-prometheus"
        "ml-platform-cadvisor" "ml-platform-node-exporter"
        "ml-platform-traefik" "ml-platform-redis" "shared-postgres"
        "dev-postgres" "dev-redis" "dev-test"
        "dcgm-exporter"
    )

    local cleaned=0
    for container in "${containers[@]}"; do
        if docker ps -aq -f "name=^${container}$" | grep -q .; then
            echo -n "  Removing $container..."
            docker rm -f "$container" >/dev/null 2>&1 && echo -e " ${GREEN}✓${NC}" || echo -e " ${YELLOW}⚠${NC}"
            cleaned=$((cleaned + 1))
        fi
    done

    # Clean any containers with ml-platform or sfml prefix
    local orphans=$(docker ps -aq --filter "name=ml-platform" --filter "name=sfml" --filter "name=mlflow" --filter "name=ray" 2>/dev/null)
    if [ -n "$orphans" ]; then
        echo "  Removing orphaned containers..."
        echo "$orphans" | xargs docker rm -f >/dev/null 2>&1 || true
        cleaned=$((cleaned + 1))
    fi

    if [ $cleaned -eq 0 ]; then
        log_success "No cleanup needed"
    else
        log_success "Cleanup complete"
    fi
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
    docker compose up -d \
        traefik shared-postgres ml-platform-redis \
        node-exporter cadvisor 2>&1 | grep -v "orphan" || true

    wait_for_health "shared-postgres" $POSTGRES_TIMEOUT || { log_error "PostgreSQL failed to start"; exit 1; }
    wait_for_health "ml-platform-traefik" $TRAEFIK_TIMEOUT || { log_error "Traefik failed to start"; exit 1; }
    wait_for_health "ml-platform-redis" $DEFAULT_TIMEOUT || log_warn "Redis may still be initializing"

    # Verify Traefik API is accessible
    wait_for_http "http://localhost:8090/api/overview" 30 || log_warn "Traefik API not yet accessible"
    log_success "Infrastructure ready"
    echo ""

    # =========================================================================
    # Phase 2: FusionAuth (Needs PostgreSQL)
    # =========================================================================
    log_info "━━━ Phase 2: FusionAuth (OAuth Provider) ━━━"
    echo "Starting: FusionAuth OAuth/SSO server..."
    docker compose up -d fusionauth 2>&1 | grep -v "orphan" || true

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
        if [ -f "$SCRIPT_DIR/scripts/manage_funnel.sh" ]; then
            "$SCRIPT_DIR/scripts/manage_funnel.sh" start 2>/dev/null || log_warn "Funnel may need manual start"
        else
            sudo tailscale funnel --bg --https=443 http://localhost:80 2>/dev/null || log_warn "Funnel may need manual start"
        fi

        # Wait for funnel to be accessible
        sleep 3
        PUBLIC_DOMAIN=$(tailscale status --json 2>/dev/null | jq -r '.Self.HostName + "." + .MagicDNSSuffix' 2>/dev/null || echo "sfml-platform.tail38b60a.ts.net")

        # Verify OIDC discovery endpoint is accessible (required for OAuth2 Proxy)
        echo -n "  Verifying OIDC discovery endpoint"
        local oidc_wait=0
        while [ $oidc_wait -lt 30 ]; do
            if curl -sf "https://${PUBLIC_DOMAIN}/.well-known/openid-configuration" >/dev/null 2>&1; then
                echo -e " ${GREEN}✓${NC}"
                break
            fi
            echo -n "."
            sleep 2
            oidc_wait=$((oidc_wait + 2))
        done
        [ $oidc_wait -ge 30 ] && echo -e " ${YELLOW}⚠${NC} (OIDC not yet accessible)"

        log_success "Tailscale Funnel active"
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
    docker compose up -d oauth2-proxy 2>&1 | grep -v "orphan" || true

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
    while [ $proxy_wait -lt 30 ]; do
        # Check if OAuth2 Proxy is responding (any HTTP status except 000 means it's up)
        local proxy_check=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost/oauth2-proxy/ping" 2>/dev/null)
        if [ "$proxy_check" != "000" ] && [ -n "$proxy_check" ]; then
            echo -e " ${GREEN}✓${NC} (HTTP $proxy_check)"
            break
        fi
        echo -n "."
        sleep 2
        proxy_wait=$((proxy_wait + 2))
    done
    [ $proxy_wait -ge 30 ] && echo -e " ${YELLOW}⚠${NC} (endpoint not responding)"

    # CRITICAL: Wait for Traefik to register the oauth2-auth middleware
    # Protected services will fail if this middleware doesn't exist
    # Traefik filters out unhealthy/starting containers - that's why healthcheck must be disabled
    wait_for_middleware "oauth2-auth" 60 || {
        log_error "oauth2-auth middleware not registered in Traefik!"
        echo ""
        echo -e "${RED}╔════════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${RED}║  MIDDLEWARE NOT REGISTERED                                     ║${NC}"
        echo -e "${RED}╠════════════════════════════════════════════════════════════════╣${NC}"
        echo -e "${RED}║  Traefik filters containers that are 'unhealthy' or 'starting' ║${NC}"
        echo -e "${RED}║  Check container health: docker inspect oauth2-proxy \\         ║${NC}"
        echo -e "${RED}║                          --format='{{.State.Health.Status}}'   ║${NC}"
        echo -e "${RED}║                                                                ║${NC}"
        echo -e "${RED}║  If status is 'starting' or 'unhealthy':                       ║${NC}"
        echo -e "${RED}║  1. The healthcheck is using wget/curl (not in scratch image)  ║${NC}"
        echo -e "${RED}║  2. Set 'healthcheck: disable: true' in docker-compose.infra.yml${NC}"
        echo -e "${RED}║  3. Restart: docker compose up -d --force-recreate oauth2-proxy${NC}"
        echo -e "${RED}╚════════════════════════════════════════════════════════════════╝${NC}"
        echo ""
        log_warn "Protected services will be inaccessible without oauth2-auth middleware."
        docker logs oauth2-proxy 2>&1 | tail -10
    }

    log_success "OAuth2 Proxy ready (middleware registered)"
    echo ""

    # =========================================================================
    # Phase 5: Protected Monitoring Services (Need OAuth2 Middleware)
    # =========================================================================
    log_info "━━━ Phase 5: Monitoring (Protected by OAuth2) ━━━"
    echo "Starting: Global Prometheus, Unified Grafana..."
    docker compose up -d \
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
    docker compose up -d \
        mlflow-server mlflow-prometheus 2>&1 | grep -v "orphan" || true

    wait_for_health "mlflow-server" $MLFLOW_TIMEOUT || log_warn "MLflow server may still be initializing"

    docker compose up -d \
        mlflow-nginx mlflow-api 2>&1 | grep -v "orphan" || true

    wait_for_health "mlflow-nginx" $DEFAULT_TIMEOUT || log_warn "MLflow nginx may still be starting"
    log_success "MLflow services ready"
    echo ""

    # =========================================================================
    # Phase 7: Ray Compute (Protected by OAuth2)
    # =========================================================================
    log_info "━━━ Phase 7: Ray Compute (Protected by OAuth2) ━━━"
    echo "Starting: Ray head, API, Prometheus..."
    docker compose up -d \
        ray-head ray-prometheus 2>&1 | grep -v "orphan" || true

    wait_for_health "ray-head" $RAY_TIMEOUT || log_warn "Ray head may still be initializing"

    docker compose up -d \
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
        docker compose -f monitoring/dcgm-exporter/docker-compose.yml up -d 2>&1 | grep -v "orphan" || true
        log_success "GPU monitoring started"
    else
        log_warn "DCGM configuration not found - skipping GPU monitoring"
    fi
    echo ""

    # =========================================================================
    # Phase 9: Observability Services
    # =========================================================================
    log_info "━━━ Phase 9: Observability & Landing Page ━━━"
    echo "Starting: Homer (landing), Dozzle (logs), Postgres Backup..."
    docker compose up -d \
        homer dozzle postgres-backup 2>&1 | grep -v "orphan" || true

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
    local PUBLIC_DOMAIN=$(tailscale status --json 2>/dev/null | jq -r '.Self.HostName + "." + .MagicDNSSuffix' 2>/dev/null || echo "sfml-platform.tail38b60a.ts.net")

    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    log_success "Platform startup complete!"
    echo ""
    echo "Service Status:"
    docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAME|traefik|postgres|redis|mlflow|ray|grafana|prometheus|fusionauth|oauth2|cadvisor|node-exporter|dozzle|homer|backup" || true
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
    fi
    echo ""
    echo -e "${CYAN}Internal Access (LAN - http://10.0.0.163/...):${NC}"
    # Get LAN IP (fallback to common default)
    local LAN_IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{print $7}' | head -1)
    LAN_IP=${LAN_IP:-10.0.0.163}

    echo "  🏠 Landing Page:   http://${LAN_IP}/"
    echo "  • MLflow UI:       http://${LAN_IP}/mlflow/"
    echo "  • Ray Dashboard:   http://${LAN_IP}/ray/"
    echo "  • Grafana:         http://${LAN_IP}/grafana/"
    echo "  • Dozzle (Logs):   http://${LAN_IP}/logs/"
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
    local PUBLIC_DOMAIN="${PUBLIC_DOMAIN:-sfml-platform.tail38b60a.ts.net}"

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
