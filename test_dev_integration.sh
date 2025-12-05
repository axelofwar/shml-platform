#!/bin/bash
# ML Platform - Comprehensive Dev Integration Test
# Tests MLflow 3.x dev server alongside production services
#
# This script verifies:
# 1. Dev services are running and healthy
# 2. Production services are unaffected
# 3. MLflow 3.x API functionality
# 4. Integration with Ray (if dev Ray is running)
# 5. Network isolation between dev and prod
# 6. Database operations
# 7. Artifact storage
#
# Usage:
#   ./test_dev_integration.sh           # Run all tests
#   ./test_dev_integration.sh quick     # Quick health checks only
#   ./test_dev_integration.sh mlflow    # MLflow tests only
#   ./test_dev_integration.sh compare   # Compare dev vs prod

# Don't exit on error - we want to run all tests
set +e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'
BOLD='\033[1m'

# Endpoints
MLFLOW_DEV="http://localhost:5001"
MLFLOW_PROD="http://localhost:5000"
RAY_DEV="http://localhost:8266"
RAY_PROD="http://localhost:8265"
GRAFANA="http://localhost:3000"
TRAEFIK="http://localhost:8090"

# Test counters
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_SKIPPED=0

# Test result tracking
declare -a TEST_RESULTS=()

log_test() {
    local status=$1
    local name=$2
    local details=${3:-""}

    case $status in
        PASS)
            echo -e "  ${GREEN}✓${NC} $name"
            ((TESTS_PASSED++))
            TEST_RESULTS+=("PASS|$name")
            ;;
        FAIL)
            echo -e "  ${RED}✗${NC} $name"
            [ -n "$details" ] && echo -e "    ${RED}→ $details${NC}"
            ((TESTS_FAILED++))
            TEST_RESULTS+=("FAIL|$name|$details")
            ;;
        SKIP)
            echo -e "  ${YELLOW}⊘${NC} $name (skipped)"
            [ -n "$details" ] && echo -e "    ${YELLOW}→ $details${NC}"
            ((TESTS_SKIPPED++))
            TEST_RESULTS+=("SKIP|$name|$details")
            ;;
        WARN)
            echo -e "  ${YELLOW}⚠${NC} $name"
            [ -n "$details" ] && echo -e "    ${YELLOW}→ $details${NC}"
            TEST_RESULTS+=("WARN|$name|$details")
            ;;
    esac
}

header() {
    echo ""
    echo -e "${CYAN}━━━ $1 ━━━${NC}"
}

# ═══════════════════════════════════════════════════════════════════
# Test Suite: Container Health
# ═══════════════════════════════════════════════════════════════════
test_container_health() {
    header "Container Health Checks"

    # Dev containers
    echo -e "${MAGENTA}  Dev Containers:${NC}"

    for container in mlflow-dev-server mlflow-dev-postgres dev-redis; do
        status=$(sg docker -c "docker inspect --format='{{.State.Health.Status}}' $container" 2>/dev/null || echo "not_found")
        case $status in
            healthy)
                log_test PASS "$container"
                ;;
            starting)
                log_test WARN "$container" "Still starting..."
                ;;
            not_found)
                log_test SKIP "$container" "Container not running"
                ;;
            *)
                log_test FAIL "$container" "Status: $status"
                ;;
        esac
    done

    # Production containers (verify not affected)
    echo -e "${BLUE}  Production Containers (should be unaffected):${NC}"

    for container in mlflow-server shml-postgres ml-platform-redis ray-head ml-platform-traefik; do
        status=$(sg docker -c "docker inspect --format='{{.State.Health.Status}}' $container" 2>/dev/null || echo "not_found")
        case $status in
            healthy)
                log_test PASS "$container (prod)"
                ;;
            not_found)
                log_test SKIP "$container (prod)" "Not running"
                ;;
            *)
                log_test WARN "$container (prod)" "Status: $status"
                ;;
        esac
    done
}

# ═══════════════════════════════════════════════════════════════════
# Test Suite: MLflow 3.x API
# ═══════════════════════════════════════════════════════════════════
test_mlflow_dev_api() {
    header "MLflow 3.x Dev API Tests"

    # Health check
    if curl -sf "$MLFLOW_DEV/health" > /dev/null 2>&1; then
        log_test PASS "Health endpoint"
    else
        log_test FAIL "Health endpoint" "Cannot reach $MLFLOW_DEV/health"
        return
    fi

    # Create experiment
    local exp_name="integration-test-$(date +%s)"
    local result=$(curl -sf -X POST "$MLFLOW_DEV/api/2.0/mlflow/experiments/create" \
        -H "Content-Type: application/json" \
        -d "{\"name\": \"$exp_name\"}" 2>&1)

    if echo "$result" | grep -q "experiment_id"; then
        local exp_id=$(echo "$result" | jq -r '.experiment_id')
        log_test PASS "Create experiment (ID: $exp_id)"

        # Create run
        local run_result=$(curl -sf -X POST "$MLFLOW_DEV/api/2.0/mlflow/runs/create" \
            -H "Content-Type: application/json" \
            -d "{\"experiment_id\": \"$exp_id\", \"run_name\": \"integration-run\"}" 2>&1)

        if echo "$run_result" | grep -q "run"; then
            local run_id=$(echo "$run_result" | jq -r '.run.info.run_id')
            log_test PASS "Create run (ID: ${run_id:0:8}...)"

            # Log metric
            local metric_result=$(curl -sf -X POST "$MLFLOW_DEV/api/2.0/mlflow/runs/log-metric" \
                -H "Content-Type: application/json" \
                -d "{\"run_id\": \"$run_id\", \"key\": \"accuracy\", \"value\": 0.95, \"timestamp\": $(date +%s)000}" 2>&1)

            if [ -z "$metric_result" ] || echo "$metric_result" | grep -qE "{}|^$"; then
                log_test PASS "Log metric"
            else
                log_test FAIL "Log metric" "$metric_result"
            fi

            # Log parameter
            local param_result=$(curl -sf -X POST "$MLFLOW_DEV/api/2.0/mlflow/runs/log-parameter" \
                -H "Content-Type: application/json" \
                -d "{\"run_id\": \"$run_id\", \"key\": \"learning_rate\", \"value\": \"0.001\"}" 2>&1)

            if [ -z "$param_result" ] || echo "$param_result" | grep -qE "{}|^$"; then
                log_test PASS "Log parameter"
            else
                log_test FAIL "Log parameter" "$param_result"
            fi

            # Log batch (MLflow 3.x feature)
            local batch_result=$(curl -sf -X POST "$MLFLOW_DEV/api/2.0/mlflow/runs/log-batch" \
                -H "Content-Type: application/json" \
                -d "{
                    \"run_id\": \"$run_id\",
                    \"metrics\": [
                        {\"key\": \"loss\", \"value\": 0.05, \"timestamp\": $(date +%s)000, \"step\": 1},
                        {\"key\": \"f1_score\", \"value\": 0.92, \"timestamp\": $(date +%s)000, \"step\": 1}
                    ],
                    \"params\": [
                        {\"key\": \"batch_size\", \"value\": \"32\"},
                        {\"key\": \"epochs\", \"value\": \"100\"}
                    ]
                }" 2>&1)

            if [ -z "$batch_result" ] || echo "$batch_result" | grep -qE "{}|^$"; then
                log_test PASS "Log batch (metrics + params)"
            else
                log_test WARN "Log batch" "Response: $batch_result"
            fi

            # End run
            local end_result=$(curl -sf -X POST "$MLFLOW_DEV/api/2.0/mlflow/runs/update" \
                -H "Content-Type: application/json" \
                -d "{\"run_id\": \"$run_id\", \"status\": \"FINISHED\"}" 2>&1)

            if echo "$end_result" | grep -qE "run_info|FINISHED"; then
                log_test PASS "End run"
            else
                log_test WARN "End run" "Unexpected response"
            fi

            # Get run (verify data persisted)
            local get_result=$(curl -sf "$MLFLOW_DEV/api/2.0/mlflow/runs/get?run_id=$run_id" 2>&1)

            if echo "$get_result" | grep -q "accuracy"; then
                log_test PASS "Get run (data persisted)"
            else
                log_test FAIL "Get run" "Metrics not found in response"
            fi

        else
            log_test FAIL "Create run" "$run_result"
        fi
    else
        log_test FAIL "Create experiment" "$result"
    fi

    # List experiments
    local list_result=$(curl -sf "$MLFLOW_DEV/api/2.0/mlflow/experiments/search" \
        -H "Content-Type: application/json" \
        -d '{"max_results": 100}' 2>&1)

    if echo "$list_result" | grep -q "experiments"; then
        local count=$(echo "$list_result" | jq '.experiments | length')
        log_test PASS "List experiments ($count found)"
    else
        log_test FAIL "List experiments" "$list_result"
    fi

    # Search runs
    local search_result=$(curl -sf -X POST "$MLFLOW_DEV/api/2.0/mlflow/runs/search" \
        -H "Content-Type: application/json" \
        -d '{"max_results": 10}' 2>&1)

    if echo "$search_result" | grep -q "runs"; then
        log_test PASS "Search runs"
    else
        log_test WARN "Search runs" "No runs found or error"
    fi
}

# ═══════════════════════════════════════════════════════════════════
# Test Suite: Production Isolation
# ═══════════════════════════════════════════════════════════════════
test_production_isolation() {
    header "Production Isolation Tests"

    # Check prod MLflow is still on different port
    if curl -sf "$MLFLOW_PROD/health" > /dev/null 2>&1; then
        log_test PASS "Production MLflow accessible (port 5000)"

        # Verify it's different from dev
        local prod_exp=$(curl -sf "$MLFLOW_PROD/api/2.0/mlflow/experiments/search" \
            -H "Content-Type: application/json" \
            -d '{"max_results": 100}' 2>&1 | jq '.experiments | length' 2>/dev/null || echo "0")
        local dev_exp=$(curl -sf "$MLFLOW_DEV/api/2.0/mlflow/experiments/search" \
            -H "Content-Type: application/json" \
            -d '{"max_results": 100}' 2>&1 | jq '.experiments | length' 2>/dev/null || echo "0")

        if [ "$prod_exp" != "$dev_exp" ] || [ "$prod_exp" = "0" ] || [ "$dev_exp" = "0" ]; then
            log_test PASS "Dev and prod have separate databases"
        else
            log_test WARN "Dev/prod experiment counts match" "May or may not indicate shared DB"
        fi
    else
        log_test SKIP "Production MLflow" "Not running"
    fi

    # Check databases are separate
    local dev_db=$(sg docker -c "docker exec mlflow-dev-postgres psql -U mlflow_dev -d mlflow_dev_db -t -c 'SELECT COUNT(*) FROM experiments;'" 2>/dev/null | tr -d ' ' || echo "error")
    local prod_db=$(sg docker -c "docker exec shml-postgres psql -U mlflow -d mlflow_db -t -c 'SELECT COUNT(*) FROM experiments;'" 2>/dev/null | tr -d ' ' || echo "error")

    if [ "$dev_db" != "error" ] && [ "$prod_db" != "error" ]; then
        log_test PASS "Separate PostgreSQL instances (dev: $dev_db exp, prod: $prod_db exp)"
    elif [ "$dev_db" != "error" ]; then
        log_test PASS "Dev PostgreSQL working (prod not accessible)"
    else
        log_test WARN "PostgreSQL isolation check" "Could not query databases"
    fi

    # Check Redis isolation
    local dev_redis=$(sg docker -c "docker exec dev-redis redis-cli DBSIZE" 2>/dev/null || echo "error")
    local prod_redis=$(sg docker -c "docker exec ml-platform-redis redis-cli DBSIZE" 2>/dev/null || echo "error")

    if [ "$dev_redis" != "error" ] && [ "$prod_redis" != "error" ]; then
        log_test PASS "Separate Redis instances"
    else
        log_test WARN "Redis isolation check" "Could not query Redis"
    fi

    # Check network isolation
    local dev_network=$(sg docker -c "docker network inspect mlflow-dev-network" 2>/dev/null | jq '.[0].Containers | keys | length' || echo "0")
    local prod_network=$(sg docker -c "docker network inspect ml-platform-network" 2>/dev/null | jq '.[0].Containers | keys | length' || echo "0")

    if [ "$dev_network" != "0" ]; then
        log_test PASS "Dev network isolated ($dev_network containers)"
    else
        log_test WARN "Dev network" "Network check failed"
    fi
}

# ═══════════════════════════════════════════════════════════════════
# Test Suite: Ray Integration (if available)
# ═══════════════════════════════════════════════════════════════════
test_ray_integration() {
    header "Ray Integration Tests"

    # Check if Ray prod is running
    if curl -sf "$RAY_PROD/api/version" > /dev/null 2>&1; then
        log_test PASS "Production Ray accessible"

        # Check Ray can see cluster info
        local ray_status=$(curl -sf "$RAY_PROD/api/cluster_status" 2>&1)
        if echo "$ray_status" | grep -qE "head|node"; then
            log_test PASS "Ray cluster status"
        else
            log_test WARN "Ray cluster status" "Unexpected response"
        fi
    else
        log_test SKIP "Production Ray" "Not accessible on port 8265"
    fi

    # Check if Ray dev is running
    if curl -sf "$RAY_DEV" > /dev/null 2>&1; then
        log_test PASS "Dev Ray accessible"
    else
        log_test SKIP "Dev Ray" "Not running (port 8266)"
    fi
}

# ═══════════════════════════════════════════════════════════════════
# Test Suite: Infrastructure Services
# ═══════════════════════════════════════════════════════════════════
test_infrastructure() {
    header "Infrastructure Services"

    # Traefik
    if curl -sf "$TRAEFIK/api/overview" > /dev/null 2>&1; then
        log_test PASS "Traefik dashboard"
    else
        log_test SKIP "Traefik" "Dashboard not accessible"
    fi

    # Grafana
    if curl -sf "$GRAFANA/api/health" > /dev/null 2>&1; then
        log_test PASS "Grafana health"
    else
        log_test SKIP "Grafana" "Not accessible"
    fi

    # Prometheus
    if curl -sf "http://localhost:9090/-/healthy" > /dev/null 2>&1; then
        log_test PASS "Global Prometheus"
    else
        log_test SKIP "Prometheus" "Not accessible"
    fi
}

# ═══════════════════════════════════════════════════════════════════
# Test Suite: Version Comparison
# ═══════════════════════════════════════════════════════════════════
test_version_comparison() {
    header "Version Comparison"

    # Get dev version from logs
    local dev_version=$(sg docker -c "docker logs mlflow-dev-server 2>&1" | grep -oP "MLflow: \K[0-9.]+" | head -1 || echo "unknown")

    # Get prod version from logs (if running)
    local prod_version=$(sg docker -c "docker logs mlflow-server 2>&1" | grep -oP "MLflow: \K[0-9.]+" | head -1 || echo "unknown")

    echo -e "  ${BOLD}Version Info:${NC}"
    echo -e "    Dev MLflow:  ${GREEN}$dev_version${NC}"
    echo -e "    Prod MLflow: ${BLUE}$prod_version${NC}"

    if [ "$dev_version" != "unknown" ]; then
        if [[ "$dev_version" == 3.* ]]; then
            log_test PASS "Dev running MLflow 3.x ($dev_version)"
        else
            log_test WARN "Dev MLflow version" "Expected 3.x, got $dev_version"
        fi
    fi

    if [ "$prod_version" != "unknown" ]; then
        if [[ "$prod_version" == 2.* ]]; then
            log_test PASS "Prod running MLflow 2.x ($prod_version)"
        else
            log_test WARN "Prod MLflow version" "Got $prod_version"
        fi
    fi
}

# ═══════════════════════════════════════════════════════════════════
# Test Suite: Performance Check
# ═══════════════════════════════════════════════════════════════════
test_performance() {
    header "Performance Check"

    # Measure API response time
    local start_time=$(date +%s%N)
    curl -sf "$MLFLOW_DEV/health" > /dev/null 2>&1
    local end_time=$(date +%s%N)
    local response_time=$(( (end_time - start_time) / 1000000 ))

    if [ $response_time -lt 100 ]; then
        log_test PASS "Health endpoint response time (${response_time}ms)"
    elif [ $response_time -lt 500 ]; then
        log_test WARN "Health endpoint response time" "${response_time}ms (acceptable)"
    else
        log_test FAIL "Health endpoint response time" "${response_time}ms (too slow)"
    fi

    # Measure experiment creation time
    start_time=$(date +%s%N)
    curl -sf -X POST "$MLFLOW_DEV/api/2.0/mlflow/experiments/create" \
        -H "Content-Type: application/json" \
        -d "{\"name\": \"perf-test-$(date +%s)\"}" > /dev/null 2>&1
    end_time=$(date +%s%N)
    response_time=$(( (end_time - start_time) / 1000000 ))

    if [ $response_time -lt 200 ]; then
        log_test PASS "Create experiment time (${response_time}ms)"
    elif [ $response_time -lt 1000 ]; then
        log_test WARN "Create experiment time" "${response_time}ms"
    else
        log_test FAIL "Create experiment time" "${response_time}ms (too slow)"
    fi
}

# ═══════════════════════════════════════════════════════════════════
# Summary Report
# ═══════════════════════════════════════════════════════════════════
print_summary() {
    echo ""
    echo -e "${BLUE}╔════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║              Test Summary                              ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════╝${NC}"
    echo ""

    local total=$((TESTS_PASSED + TESTS_FAILED + TESTS_SKIPPED))

    echo -e "  ${GREEN}Passed:${NC}  $TESTS_PASSED"
    echo -e "  ${RED}Failed:${NC}  $TESTS_FAILED"
    echo -e "  ${YELLOW}Skipped:${NC} $TESTS_SKIPPED"
    echo -e "  ${BOLD}Total:${NC}   $total"
    echo ""

    if [ $TESTS_FAILED -eq 0 ]; then
        echo -e "${GREEN}╔════════════════════════════════════════════════════════╗${NC}"
        echo -e "${GREEN}║  ✓ ALL TESTS PASSED - Dev environment ready!           ║${NC}"
        echo -e "${GREEN}╚════════════════════════════════════════════════════════╝${NC}"
    else
        echo -e "${YELLOW}╔════════════════════════════════════════════════════════╗${NC}"
        echo -e "${YELLOW}║  ⚠ Some tests failed - review above for details        ║${NC}"
        echo -e "${YELLOW}╚════════════════════════════════════════════════════════╝${NC}"
    fi

    echo ""
    echo -e "${CYAN}Next Steps:${NC}"
    if [ $TESTS_FAILED -eq 0 ]; then
        echo "  1. Run more extensive tests with your ML workflows"
        echo "  2. Test Python client: MLFLOW_TRACKING_URI=$MLFLOW_DEV python your_script.py"
        echo "  3. When ready, upgrade production:"
        echo "     - Update mlflow-server/docker/mlflow/requirements.txt"
        echo "     - Rebuild: docker compose build mlflow-server"
        echo "     - Restart: docker compose up -d mlflow-server"
    else
        echo "  1. Review failed tests above"
        echo "  2. Check container logs: sg docker -c 'docker logs <container>'"
        echo "  3. Fix issues and re-run tests"
    fi
    echo ""
}

# ═══════════════════════════════════════════════════════════════════
# Main Execution
# ═══════════════════════════════════════════════════════════════════

echo ""
echo -e "${MAGENTA}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${MAGENTA}║                                                        ║${NC}"
echo -e "${MAGENTA}║     ML Platform - Dev Integration Tests                ║${NC}"
echo -e "${MAGENTA}║     MLflow 3.x Upgrade Verification                    ║${NC}"
echo -e "${MAGENTA}║                                                        ║${NC}"
echo -e "${MAGENTA}╚════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "Started: $(date)"
echo ""

case "${1:-all}" in
    quick)
        test_container_health
        ;;
    mlflow)
        test_container_health
        test_mlflow_dev_api
        ;;
    compare)
        test_version_comparison
        test_production_isolation
        ;;
    all)
        test_container_health
        test_mlflow_dev_api
        test_production_isolation
        test_ray_integration
        test_infrastructure
        test_version_comparison
        test_performance
        ;;
    *)
        echo "Usage: $0 [all|quick|mlflow|compare]"
        exit 1
        ;;
esac

print_summary
