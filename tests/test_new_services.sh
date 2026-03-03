#!/usr/bin/env bash
# =============================================================================
# test_new_services.sh — Smoke tests for newly added SHML Platform services
# =============================================================================
#
# Tests: Nessie, FiftyOne, FiftyOne-MongoDB, ML SLO Exporter
#
# Usage:
#   ./tests/test_new_services.sh              # Run all tests
#   ./tests/test_new_services.sh --quick      # Container health only
#   ./tests/test_new_services.sh --auth       # Include OAuth tests (needs token)
#
# Prerequisites:
#   - Docker running with SHML platform services
#   - curl, jq, docker CLI available
#
# Exit codes:
#   0 = all tests passed
#   1 = one or more tests failed
# =============================================================================

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Counters
PASS=0
FAIL=0
SKIP=0

# Platform prefix
PREFIX="${PLATFORM_PREFIX:-shml}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

pass() {
    PASS=$((PASS + 1))
    echo -e "  ${GREEN}✓${NC} $1"
}

fail() {
    FAIL=$((FAIL + 1))
    echo -e "  ${RED}✗${NC} $1"
}

skip() {
    SKIP=$((SKIP + 1))
    echo -e "  ${YELLOW}⊘${NC} $1 (skipped)"
}

check_container_health() {
    local container="$1"
    local label="${2:-$container}"
    local status
    status=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "not_found")
    case "$status" in
        healthy) pass "$label container healthy" ;;
        starting) skip "$label container still starting" ;;
        unhealthy) fail "$label container unhealthy" ;;
        *) skip "$label container not found" ;;
    esac
}

check_container_running() {
    local container="$1"
    local label="${2:-$container}"
    if docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
        pass "$label container running"
    else
        fail "$label container not running"
    fi
}

# ---------------------------------------------------------------------------
# Parse args
# ---------------------------------------------------------------------------

QUICK=false
AUTH=false
for arg in "$@"; do
    case "$arg" in
        --quick) QUICK=true ;;
        --auth)  AUTH=true ;;
        --help|-h)
            echo "Usage: $0 [--quick] [--auth]"
            echo "  --quick  Only check container health"
            echo "  --auth   Include OAuth-authenticated API tests"
            exit 0
            ;;
    esac
done

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   SHML Platform — New Services Smoke Tests          ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════╝${NC}"
echo ""

# ==========================================================================
# 1. Container Health Checks
# ==========================================================================

echo -e "${CYAN}━━━ Container Health Checks ━━━${NC}"

check_container_health "${PREFIX}-nessie" "Nessie"
check_container_health "${PREFIX}-fiftyone" "FiftyOne"
check_container_health "${PREFIX}-fiftyone-mongodb" "FiftyOne MongoDB"
check_container_health "${PREFIX}-ml-slo-exporter" "ML SLO Exporter"

echo ""

if $QUICK; then
    echo -e "${CYAN}━━━ Results (quick mode) ━━━${NC}"
    echo -e "  Pass: ${GREEN}${PASS}${NC}  Fail: ${RED}${FAIL}${NC}  Skip: ${YELLOW}${SKIP}${NC}"
    [ "$FAIL" -eq 0 ] && exit 0 || exit 1
fi

# ==========================================================================
# 2. Nessie API Tests
# ==========================================================================

echo -e "${CYAN}━━━ Nessie API Tests ━━━${NC}"

# Internal health check (direct port, bypasses Traefik)
NESSIE_URL="http://localhost:19120"
NESSIE_RESP=$(curl -sS -o /dev/null -w "%{http_code}" "$NESSIE_URL/api/v2/config" 2>/dev/null || echo "000")
if [ "$NESSIE_RESP" = "200" ]; then
    pass "Nessie config endpoint (internal :19120)"

    # Check default branch is 'main'
    DEFAULT_BRANCH=$(curl -sS "$NESSIE_URL/api/v2/config" 2>/dev/null | jq -r '.defaultBranch' 2>/dev/null || echo "")
    if [ "$DEFAULT_BRANCH" = "main" ]; then
        pass "Nessie default branch is 'main'"
    else
        fail "Nessie default branch: expected 'main', got '$DEFAULT_BRANCH'"
    fi

    # Test branch CRUD
    BRANCH_NAME="smoke-test-$(date +%s)"
    MAIN_HASH=$(curl -sS "$NESSIE_URL/api/v2/trees/main" 2>/dev/null | jq -r '.hash' 2>/dev/null || echo "")

    if [ -n "$MAIN_HASH" ] && [ "$MAIN_HASH" != "null" ]; then
        # Create branch
        CREATE_RESP=$(curl -sS -o /dev/null -w "%{http_code}" \
            -X POST "$NESSIE_URL/api/v2/trees" \
            -H "Content-Type: application/json" \
            -d "{\"type\":\"BRANCH\",\"name\":\"$BRANCH_NAME\",\"hash\":\"$MAIN_HASH\"}" 2>/dev/null)
        if [ "$CREATE_RESP" = "200" ] || [ "$CREATE_RESP" = "201" ]; then
            pass "Nessie branch create ($BRANCH_NAME)"
        else
            fail "Nessie branch create: HTTP $CREATE_RESP"
        fi

        # List branches — find our test branch
        BRANCHES=$(curl -sS "$NESSIE_URL/api/v2/trees" 2>/dev/null | jq -r '.references[].name' 2>/dev/null || echo "")
        if echo "$BRANCHES" | grep -q "$BRANCH_NAME"; then
            pass "Nessie branch list contains test branch"
        else
            fail "Nessie branch list missing test branch"
        fi

        # Delete branch
        DEL_RESP=$(curl -sS -o /dev/null -w "%{http_code}" \
            -X DELETE "$NESSIE_URL/api/v2/trees/$BRANCH_NAME" 2>/dev/null)
        if [ "$DEL_RESP" = "200" ] || [ "$DEL_RESP" = "204" ]; then
            pass "Nessie branch delete ($BRANCH_NAME)"
        else
            fail "Nessie branch delete: HTTP $DEL_RESP"
        fi
    else
        skip "Nessie branch CRUD (could not get main hash)"
    fi
else
    skip "Nessie internal port not reachable (container-only network)"
fi

# Traefik auth redirect (unauthenticated)
TRAEFIK_RESP=$(curl -sS -o /dev/null -w "%{http_code}" -L --max-redirs 0 "http://localhost/nessie/api/v2/config" 2>/dev/null || echo "000")
if [ "$TRAEFIK_RESP" = "302" ] || [ "$TRAEFIK_RESP" = "401" ] || [ "$TRAEFIK_RESP" = "403" ]; then
    pass "Nessie OAuth redirect (unauthenticated → $TRAEFIK_RESP)"
elif [ "$TRAEFIK_RESP" = "000" ]; then
    skip "Traefik not reachable on localhost:80"
else
    fail "Nessie no auth redirect: expected 302/401/403, got $TRAEFIK_RESP"
fi

# Nessie metrics endpoint
METRICS_RESP=$(curl -sS -o /dev/null -w "%{http_code}" "http://localhost:9000/q/metrics" 2>/dev/null || echo "000")
if [ "$METRICS_RESP" = "200" ]; then
    METRICS_CONTENT=$(curl -sS "http://localhost:9000/q/metrics" 2>/dev/null)
    if echo "$METRICS_CONTENT" | grep -q "jvm_\|http_\|nessie_"; then
        pass "Nessie Prometheus metrics exposed"
    else
        fail "Nessie metrics endpoint returned unexpected content"
    fi
else
    # Metrics port (9000) is container-only, verify via docker exec instead
    DOCKER_METRICS=$(docker exec ${PLATFORM_PREFIX:-shml}-nessie curl -sS -o /dev/null -w "%{http_code}" http://localhost:9000/q/metrics 2>/dev/null || echo "000")
    if [ "$DOCKER_METRICS" = "200" ]; then
        pass "Nessie metrics reachable inside container"
    else
        skip "Nessie metrics port not reachable (container-only, docker exec: $DOCKER_METRICS)"
    fi
fi

echo ""

# ==========================================================================
# 3. FiftyOne Tests
# ==========================================================================

echo -e "${CYAN}━━━ FiftyOne Tests ━━━${NC}"

# FiftyOne internal health (direct port)
FO_RESP=$(curl -sS -o /dev/null -w "%{http_code}" "http://localhost:5151/" 2>/dev/null || echo "000")
if [ "$FO_RESP" = "200" ]; then
    pass "FiftyOne UI reachable (internal :5151)"
else
    # Port 5151 is container-only, verify via docker exec
    DOCKER_FO=$(docker exec ${PLATFORM_PREFIX:-shml}-fiftyone python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:5151/').status)" 2>/dev/null || echo "fail")
    if [ "$DOCKER_FO" = "200" ]; then
        pass "FiftyOne UI reachable inside container (:5151)"
    else
        skip "FiftyOne internal port not reachable (container-only, exec: $DOCKER_FO)"
    fi
fi

# Traefik auth redirect
FO_TRAEFIK=$(curl -sS -o /dev/null -w "%{http_code}" -L --max-redirs 0 "http://localhost/fiftyone/" 2>/dev/null || echo "000")
if [ "$FO_TRAEFIK" = "302" ] || [ "$FO_TRAEFIK" = "401" ] || [ "$FO_TRAEFIK" = "403" ]; then
    pass "FiftyOne OAuth redirect (unauthenticated → $FO_TRAEFIK)"
elif [ "$FO_TRAEFIK" = "000" ]; then
    skip "Traefik not reachable on localhost:80"
else
    fail "FiftyOne no auth redirect: expected 302/401/403, got $FO_TRAEFIK"
fi

# MongoDB not exposed externally
if ! nc -z localhost 27017 2>/dev/null; then
    pass "FiftyOne MongoDB NOT exposed on localhost:27017"
else
    fail "FiftyOne MongoDB exposed on localhost:27017 (security risk!)"
fi

echo ""

# ==========================================================================
# 4. ML SLO Exporter Tests
# ==========================================================================

echo -e "${CYAN}━━━ ML SLO Exporter Tests ━━━${NC}"

# Internal metrics endpoint
SLO_RESP=$(curl -sS -o /dev/null -w "%{http_code}" "http://localhost:9092/" 2>/dev/null || echo "000")
if [ "$SLO_RESP" = "200" ]; then
    SLO_METRICS=$(curl -sS "http://localhost:9092/" 2>/dev/null)
else
    # Port 9092 is container-only, try via docker exec with python (no curl in container)
    SLO_METRICS=$(docker exec ${PLATFORM_PREFIX:-shml}-ml-slo-exporter python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:9092/').read().decode())" 2>/dev/null || echo "")
fi

if [ -n "$SLO_METRICS" ]; then
    FOUND_METRICS=0
    for metric in ml_model_freshness_days ml_dataset_freshness_days ml_eval_completeness_ratio ml_training_success_rate_7d ml_inference_latency_p99_ms ml_feature_freshness_minutes ml_error_budget_remaining_pct ml_slo_violations_30d; do
        if echo "$SLO_METRICS" | grep -q "$metric"; then
            FOUND_METRICS=$((FOUND_METRICS + 1))
        fi
    done
    if [ "$FOUND_METRICS" -ge 4 ]; then
        pass "SLO exporter metrics ($FOUND_METRICS/8 gauges found)"
    else
        fail "SLO exporter metrics: only $FOUND_METRICS/8 gauges found"
    fi
else
    skip "SLO exporter not reachable (container-only, no curl in container)"
fi

# Should NOT have a Traefik route
SLO_TRAEFIK=$(curl -sS -o /dev/null -w "%{http_code}" "http://localhost/slo-exporter/" 2>/dev/null || echo "000")
if [ "$SLO_TRAEFIK" = "404" ] || [ "$SLO_TRAEFIK" = "502" ]; then
    pass "SLO exporter NOT exposed through Traefik (internal only)"
elif [ "$SLO_TRAEFIK" = "000" ]; then
    skip "Traefik not reachable"
else
    # If it hits catch-all (Homer, OAuth middleware), that's also acceptable
    if [ "$SLO_TRAEFIK" = "302" ] || [ "$SLO_TRAEFIK" = "200" ] || [ "$SLO_TRAEFIK" = "401" ]; then
        pass "SLO exporter path falls through to catch-all (no dedicated route)"
    else
        fail "SLO exporter may be exposed: HTTP $SLO_TRAEFIK"
    fi
fi

echo ""

# ==========================================================================
# 5. Homer Dashboard Verification
# ==========================================================================

echo -e "${CYAN}━━━ Homer Dashboard Config ━━━${NC}"

HOMER_CONFIG="$PROJECT_DIR/monitoring/homer/config.yml"
if [ -f "$HOMER_CONFIG" ]; then
    for entry in "Nessie" "FiftyOne" "ML SLO Dashboard"; do
        if grep -q "$entry" "$HOMER_CONFIG"; then
            pass "Homer config contains '$entry'"
        else
            fail "Homer config missing '$entry'"
        fi
    done

    for url_path in "/nessie/" "/fiftyone/" "ml-slo-overview"; do
        if grep -q "$url_path" "$HOMER_CONFIG"; then
            pass "Homer config contains URL '$url_path'"
        else
            fail "Homer config missing URL '$url_path'"
        fi
    done
else
    skip "Homer config file not found at $HOMER_CONFIG"
fi

echo ""

# ==========================================================================
# 6. Docker Compose Validation
# ==========================================================================

echo -e "${CYAN}━━━ Docker Compose Validation ━━━${NC}"

cd "$PROJECT_DIR"

# Validate infra compose
if docker compose -f docker-compose.infra.yml config --quiet 2>/dev/null; then
    pass "docker-compose.infra.yml valid"
else
    fail "docker-compose.infra.yml has errors"
fi

# Check new services are defined
SERVICES=$(docker compose -f docker-compose.infra.yml config --services 2>/dev/null || echo "")
for svc in nessie fiftyone fiftyone-mongodb ml-slo-exporter; do
    if echo "$SERVICES" | grep -q "^${svc}$"; then
        pass "Service '$svc' defined in compose"
    else
        fail "Service '$svc' NOT defined in compose"
    fi
done

echo ""

# ==========================================================================
# 7. start_all_safe.sh Integration
# ==========================================================================

echo -e "${CYAN}━━━ Startup Script Integration ━━━${NC}"

STARTUP_SCRIPT="$PROJECT_DIR/start_all_safe.sh"
if [ -f "$STARTUP_SCRIPT" ]; then
    for svc in nessie fiftyone fiftyone-mongodb ml-slo-exporter; do
        if grep -q "$svc" "$STARTUP_SCRIPT"; then
            pass "'$svc' referenced in start_all_safe.sh"
        else
            fail "'$svc' NOT referenced in start_all_safe.sh"
        fi
    done
else
    fail "start_all_safe.sh not found"
fi

echo ""

# ==========================================================================
# 8. Prometheus Scrape Targets
# ==========================================================================

echo -e "${CYAN}━━━ Prometheus Scrape Configuration ━━━${NC}"

PROM_CONFIG="$PROJECT_DIR/monitoring/global-prometheus.yml"
if [ -f "$PROM_CONFIG" ]; then
    for target in "ml-slo-exporter" "nessie"; do
        if grep -q "$target" "$PROM_CONFIG"; then
            pass "Prometheus scrape target '$target' configured"
        else
            fail "Prometheus scrape target '$target' missing"
        fi
    done
else
    fail "global-prometheus.yml not found"
fi

echo ""

# ==========================================================================
# Summary
# ==========================================================================

TOTAL=$((PASS + FAIL + SKIP))
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  ${GREEN}Pass: ${PASS}${NC}  ${RED}Fail: ${FAIL}${NC}  ${YELLOW}Skip: ${SKIP}${NC}  Total: ${TOTAL}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ "$FAIL" -eq 0 ]; then
    echo -e "\n${GREEN}All tests passed!${NC}\n"
    exit 0
else
    echo -e "\n${RED}${FAIL} test(s) failed.${NC}\n"
    exit 1
fi
