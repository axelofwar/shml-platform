#!/bin/bash
# Test all ML Platform services
# Usage: ./test_all_services.sh
#
# This script dynamically loads credentials from .env to test authenticated endpoints

set -e

# Determine script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load environment variables from .env file
load_env() {
    local env_file="${PROJECT_ROOT}/.env"
    if [ -f "$env_file" ]; then
        echo "Loading credentials from .env..."
        # Export all non-comment, non-empty lines using set -a (auto-export)
        # This is safer than process substitution with source
        set -a
        . "$env_file"
        set +a
        return 0
    else
        echo "Warning: .env file not found at $env_file"
        return 1
    fi
}

# Load env vars
load_env

PLATFORM_PREFIX="${PLATFORM_PREFIX:-shml}"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "========================================"
echo "  ML PLATFORM SERVICE HEALTH CHECK"
echo "========================================"
echo ""

# Test function for unauthenticated requests
test_service() {
    local name="$1"
    local url="$2"
    local expected="$3"

    code=$(curl -s -o /dev/null -w "%{http_code}" "$url" 2>&1)

    if [[ "$code" == "$expected" ]] || [[ "$expected" == "ANY" && "$code" =~ ^(200|302|301)$ ]]; then
        echo -e "${GREEN}✓${NC} $name → HTTP $code"
        return 0
    else
        echo -e "${RED}✗${NC} $name → HTTP $code (expected $expected)"
        return 1
    fi
}

# Test function with API key authentication
test_service_with_api_key() {
    local name="$1"
    local url="$2"
    local api_key="$3"
    local expected="$4"

    if [ -z "$api_key" ]; then
        echo -e "${YELLOW}⚠${NC}  $name → Skipped (no API key configured)"
        return 0
    fi

    code=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $api_key" "$url" 2>&1)

    if [[ "$code" == "$expected" ]] || [[ "$expected" == "ANY" && "$code" =~ ^(200|302|301)$ ]]; then
        echo -e "${GREEN}✓${NC} $name → HTTP $code (authenticated)"
        return 0
    else
        echo -e "${RED}✗${NC} $name → HTTP $code (expected $expected)"
        return 1
    fi
}

# Test function with Basic auth
test_service_with_basic_auth() {
    local name="$1"
    local url="$2"
    local user="$3"
    local pass="$4"
    local expected="$5"

    if [ -z "$user" ] || [ -z "$pass" ]; then
        echo -e "${YELLOW}⚠${NC}  $name → Skipped (no credentials configured)"
        return 0
    fi

    code=$(curl -s -o /dev/null -w "%{http_code}" -u "$user:$pass" "$url" 2>&1)

    if [[ "$code" == "$expected" ]] || [[ "$expected" == "ANY" && "$code" =~ ^(200|302|301)$ ]]; then
        echo -e "${GREEN}✓${NC} $name → HTTP $code (authenticated)"
        return 0
    else
        echo -e "${RED}✗${NC} $name → HTTP $code (expected $expected)"
        return 1
    fi
}

# Test FusionAuth API with API key
test_fusionauth_api() {
    local name="$1"
    local endpoint="$2"
    local expected="$3"

    if [ -z "$FUSIONAUTH_API_KEY" ]; then
        echo -e "${YELLOW}⚠${NC}  $name → Skipped (FUSIONAUTH_API_KEY not set)"
        return 0
    fi

    code=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: $FUSIONAUTH_API_KEY" \
        "http://localhost:9011$endpoint" 2>&1)

    if [[ "$code" == "$expected" ]]; then
        echo -e "${GREEN}✓${NC} $name → HTTP $code"
        return 0
    else
        echo -e "${RED}✗${NC} $name → HTTP $code (expected $expected)"
        return 1
    fi
}

# Test container status
test_container() {
    local name="$1"

    if docker ps --format "{{.Names}}" | grep -q "^${name}$"; then
        status=$(docker ps --format "{{.Names}}: {{.Status}}" | grep "^${name}:")
        echo -e "${GREEN}✓${NC} $status"
        return 0
    else
        echo -e "${RED}✗${NC} $name not running"
        return 1
    fi
}

failed=0

echo "=== Container Status ==="
echo ""

# Core Infrastructure
echo "Core Infrastructure:"
test_container "${PLATFORM_PREFIX}-traefik" || ((failed++))
test_container "${PLATFORM_PREFIX}-postgres" || ((failed++))
test_container "${PLATFORM_PREFIX}-redis" || ((failed++))
test_container "oauth2-proxy" || ((failed++))
test_container "fusionauth" || ((failed++))
echo ""

# MLflow Stack
echo "MLflow Stack:"
test_container "mlflow-server" || ((failed++))
test_container "mlflow-nginx" || ((failed++))
test_container "mlflow-api" || ((failed++))
test_container "mlflow-prometheus" || ((failed++))
echo ""

# Ray Stack
echo "Ray Stack:"
test_container "ray-head" || ((failed++))
test_container "ray-compute-api" || ((failed++))
test_container "ray-prometheus" || ((failed++))
echo ""

# Monitoring Stack
echo "Monitoring Stack:"
test_container "unified-grafana" || ((failed++))
test_container "global-prometheus" || ((failed++))
test_container "${PLATFORM_PREFIX}-cadvisor" || ((failed++))
test_container "${PLATFORM_PREFIX}-node-exporter" || echo -e "${YELLOW}⚠${NC}  Node Exporter not found"
test_container "dcgm-exporter" || echo -e "${YELLOW}⚠${NC}  DCGM Exporter not found"
echo ""

# Observability Stack
echo "Observability Stack:"
test_container "homer" || echo -e "${YELLOW}⚠${NC}  Homer not deployed"
test_container "dozzle" || echo -e "${YELLOW}⚠${NC}  Dozzle not deployed"
test_container "postgres-backup" || echo -e "${YELLOW}⚠${NC}  Postgres Backup not deployed"
echo ""

echo "=== Web UI Endpoints ==="
echo ""

# OAuth Protected Services (expect 401 or redirect)
echo "OAuth Protected Services (expect 401/302):"
test_service "Homer (root)" "http://localhost/" "401" || ((failed++))
test_service "MLflow UI" "http://localhost/mlflow/" "401" || test_service "MLflow UI" "http://localhost/mlflow/" "302" || ((failed++))
test_service "Grafana" "http://localhost/grafana/" "302" || test_service "Grafana" "http://localhost/grafana/" "401" || ((failed++))
test_service "Prometheus" "http://localhost/prometheus/" "302" || test_service "Prometheus" "http://localhost/prometheus/" "401" || ((failed++))
test_service "Ray Dashboard" "http://localhost/ray/" "401" || test_service "Ray Dashboard" "http://localhost/ray/" "302" || ((failed++))
test_service "Dozzle (logs)" "http://localhost/logs/" "401" || echo -e "${YELLOW}⚠${NC}  Dozzle unexpected response"
echo ""

# Public Services (only auth endpoints)
echo "Public Services:"
test_service "FusionAuth" "http://localhost:9011" "200" || ((failed++))
echo ""

# Gateway
echo "Gateway:"
test_service "Traefik Dashboard" "http://localhost:8090/dashboard/" "200" || ((failed++))
test_service "Traefik API" "http://localhost:8090/api/http/routers" "200" || ((failed++))
echo ""

echo "=== Authentication Tests ==="
echo ""

# OAuth2 Proxy Check
echo "OAuth2 Proxy:"
# Check the oauth2-proxy endpoint
oauth_proxy_code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost/oauth2-proxy/ 2>&1)
if [[ "$oauth_proxy_code" =~ ^(200|302|401|403)$ ]]; then
    echo -e "${GREEN}✓${NC} OAuth2-proxy endpoint accessible (HTTP $oauth_proxy_code)"
else
    echo -e "${YELLOW}⚠${NC}  OAuth2-proxy endpoint returned HTTP $oauth_proxy_code"
fi

# Check the FusionAuth OAuth2 endpoint
oauth2_code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost/oauth2/.well-known/openid-configuration 2>&1)
if [[ "$oauth2_code" =~ ^(200|302)$ ]]; then
    echo -e "${GREEN}✓${NC} FusionAuth OAuth2 OIDC config accessible (HTTP $oauth2_code)"
else
    echo -e "${YELLOW}⚠${NC}  FusionAuth OAuth2 OIDC config returned HTTP $oauth2_code"
fi

# Note: Direct Grafana login is skipped since all services are OAuth protected
echo -e "${BLUE}ℹ${NC}  Direct service login skipped (all services OAuth protected)"
echo ""

echo "=== Authenticated API Tests ==="
echo ""

# FusionAuth API Tests (using FUSIONAUTH_API_KEY from .env)
echo "FusionAuth API (with API key):"
test_fusionauth_api "FusionAuth Status" "/api/status" "200" || ((failed++))
test_fusionauth_api "FusionAuth Applications" "/api/application" "200" || echo -e "${YELLOW}⚠${NC}  Applications endpoint failed"
test_fusionauth_api "FusionAuth Tenants" "/api/tenant" "200" || echo -e "${YELLOW}⚠${NC}  Tenants endpoint failed"
echo ""

# Grafana API Tests via Docker exec (internal network)
echo "Grafana API (internal via docker):"
grafana_health=$(docker exec unified-grafana wget -qO- http://localhost:3000/api/health 2>&1)
if [[ "$grafana_health" == *"database"* ]] || [[ "$grafana_health" == *"ok"* ]]; then
    echo -e "${GREEN}✓${NC} Grafana internal health check passed"
else
    echo -e "${YELLOW}⚠${NC}  Grafana internal health check: $grafana_health"
fi

grafana_ds=$(docker exec unified-grafana wget -qO- --user=admin --password="$GRAFANA_ADMIN_PASSWORD" http://localhost:3000/api/datasources 2>&1 | head -1)
if [[ "$grafana_ds" == "["* ]] || [[ "$grafana_ds" == *"datasources"* ]]; then
    echo -e "${GREEN}✓${NC} Grafana datasources accessible"
else
    echo -e "${YELLOW}⚠${NC}  Grafana datasources check - requires auth"
fi
echo ""

# Direct Service Health (via docker exec - bypassing network)
echo "Direct Service Health (via docker exec):"

# MLflow internal health
mlflow_health=$(docker exec mlflow-api wget -qO- http://localhost:5001/health 2>&1 || echo "failed")
if [[ "$mlflow_health" == *"healthy"* ]] || [[ "$mlflow_health" == *"ok"* ]] || [[ "$mlflow_health" == "{"* ]]; then
    echo -e "${GREEN}✓${NC} MLflow API internal health"
else
    # Try alternative health check
    mlflow_alt=$(docker exec mlflow-server curl -s http://localhost:5000/health 2>&1 || echo "failed")
    if [[ "$mlflow_alt" == *"OK"* ]] || [[ "$mlflow_alt" == "{"* ]]; then
        echo -e "${GREEN}✓${NC} MLflow Server internal health"
    else
        echo -e "${YELLOW}⚠${NC}  MLflow internal health → $mlflow_health"
    fi
fi

# Ray Dashboard internal
ray_health=$(docker exec ray-head curl -s http://localhost:8265/api/version 2>&1 || echo "failed")
if [[ "$ray_health" == "{"* ]]; then
    echo -e "${GREEN}✓${NC} Ray Dashboard internal API"
else
    echo -e "${YELLOW}⚠${NC}  Ray Dashboard internal → checking alternate..."
    ray_alt=$(docker exec ray-head ray status 2>&1 | head -1)
    if [[ "$ray_alt" == *"Nodes"* ]] || [[ "$ray_alt" == *"nodes"* ]]; then
        echo -e "${GREEN}✓${NC} Ray cluster status OK"
    else
        echo -e "${YELLOW}⚠${NC}  Ray status: $ray_alt"
    fi
fi

# Dozzle health - uses minimal/distroless image, use Traefik router check as primary
dozzle_router=$(curl -s http://localhost:8090/api/http/routers 2>/dev/null | grep -c "dozzle@docker")
if [[ "$dozzle_router" -gt 0 ]]; then
    echo -e "${GREEN}✓${NC} Dozzle registered in Traefik"
else
    echo -e "${YELLOW}⚠${NC}  Dozzle health unknown (not registered in Traefik)"
fi
echo ""

echo "=== Environment Variables Status ==="
echo ""

echo "Loaded credentials:"
[ -n "$FUSIONAUTH_API_KEY" ] && echo -e "${GREEN}✓${NC} FUSIONAUTH_API_KEY is set" || echo -e "${YELLOW}⚠${NC}  FUSIONAUTH_API_KEY not set"
[ -n "$GRAFANA_ADMIN_PASSWORD" ] && echo -e "${GREEN}✓${NC} GRAFANA_ADMIN_PASSWORD is set" || echo -e "${YELLOW}⚠${NC}  GRAFANA_ADMIN_PASSWORD not set"
[ -n "$OAUTH2_PROXY_COOKIE_SECRET" ] && echo -e "${GREEN}✓${NC} OAUTH2_PROXY_COOKIE_SECRET is set" || echo -e "${YELLOW}⚠${NC}  OAUTH2_PROXY_COOKIE_SECRET not set"
[ -n "$FUSIONAUTH_PROXY_CLIENT_ID" ] && echo -e "${GREEN}✓${NC} FUSIONAUTH_PROXY_CLIENT_ID is set" || echo -e "${YELLOW}⚠${NC}  FUSIONAUTH_PROXY_CLIENT_ID not set"
[ -n "$FUSIONAUTH_PROXY_CLIENT_SECRET" ] && echo -e "${GREEN}✓${NC} FUSIONAUTH_PROXY_CLIENT_SECRET is set" || echo -e "${YELLOW}⚠${NC}  FUSIONAUTH_PROXY_CLIENT_SECRET not set"
echo ""

echo "=== Database Connectivity ==="
echo ""

# Test Shared PostgreSQL
echo "Shared PostgreSQL Databases:"
if docker exec ${PLATFORM_PREFIX:-shml}-postgres psql -U postgres -d mlflow_db -c "SELECT 1" > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} MLflow database (mlflow_db)"
else
    echo -e "${YELLOW}⚠${NC}  MLflow database connection failed"
fi

if docker exec ${PLATFORM_PREFIX:-shml}-postgres psql -U postgres -d ray_compute -c "SELECT 1" > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Ray Compute database (ray_compute)"
else
    echo -e "${YELLOW}⚠${NC}  Ray Compute database connection failed"
fi

if docker exec ${PLATFORM_PREFIX:-shml}-postgres psql -U postgres -d fusionauth -c "SELECT 1" > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} FusionAuth database (fusionauth)"
else
    echo -e "${YELLOW}⚠${NC}  FusionAuth database connection failed"
fi

if docker exec ${PLATFORM_PREFIX:-shml}-postgres psql -U postgres -d inference -c "SELECT 1" > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Inference database (inference)"
else
    echo -e "${YELLOW}⚠${NC}  Inference database connection failed"
fi
echo ""

# Test Redis
echo "Redis:"
if docker exec ${PLATFORM_PREFIX:-shml}-redis redis-cli PING > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Platform Redis connection"
else
    echo -e "${YELLOW}⚠${NC}  Redis connection failed"
fi

echo ""
echo "========================================"
echo "  SUMMARY"
echo "========================================"

total_containers=$(docker ps | wc -l)
echo "Running Containers: $total_containers"

if [ $failed -eq 0 ]; then
    echo -e "${GREEN}✓ ALL TESTS PASSED${NC}"
    echo "All services are operational!"
    exit 0
else
    echo -e "${RED}✗ $failed TEST(S) FAILED${NC}"
    echo ""
    echo "Troubleshooting steps:"
    echo ""
    echo "1. Restart all services:"
    echo "   ./restart_all.sh"
    echo ""
    echo "2. Check specific service logs:"
    echo "   docker logs <container-name> --tail 50"
    echo ""
    echo "3. Check failed service status:"
    echo "   docker ps -a | grep <container-name>"
    echo ""
    echo "4. Restart individual stack:"
    echo "   MLflow:  cd mlflow-server && ./restart.sh"
    echo "   Ray:     cd ray_compute && ./restart.sh"
    echo ""
    echo "5. View logs for all services:"
    echo "   docker logs mlflow-server --tail 50"
    echo "   docker logs ray-head --tail 50"
    echo "   docker logs traefik --tail 50"
    echo ""
    exit 1
fi
