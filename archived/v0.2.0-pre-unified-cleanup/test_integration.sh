#!/bin/bash
# ML Platform Integration Tests
# Tests all services after reorganization

echo "=========================================="
echo "  ML PLATFORM INTEGRATION TESTS"
echo "  Post-Reorganization Verification"
echo "=========================================="
echo ""

PASSED=0
FAILED=0

test_endpoint() {
    local name="$1"
    local url="$2"
    local expected="$3"

    echo -n "Testing $name... "
    response=$(curl -s "$url" 2>&1)

    if echo "$response" | grep -q "$expected"; then
        echo "✓ PASS"
        ((PASSED++))
    else
        echo "✗ FAIL"
        ((FAILED++))
        echo "  Expected: $expected"
        echo "  Got: ${response:0:100}"
    fi
}

test_http_code() {
    local name="$1"
    local url="$2"
    local expected_code="$3"

    echo -n "Testing $name... "
    http_code=$(curl -s -o /dev/null -w "%{http_code}" "$url")

    if [ "$http_code" = "$expected_code" ]; then
        echo "✓ PASS (HTTP $http_code)"
        ((PASSED++))
    else
        echo "✗ FAIL (Expected HTTP $expected_code, got HTTP $http_code)"
        ((FAILED++))
    fi
}

test_json_post() {
    local name="$1"
    local url="$2"
    local data="$3"
    local expected="$4"

    echo -n "Testing $name... "
    response=$(curl -s -X POST "$url" -H "Content-Type: application/json" -d "$data" 2>&1)

    if echo "$response" | grep -q "$expected"; then
        echo "✓ PASS"
        ((PASSED++))
    else
        echo "✗ FAIL"
        ((FAILED++))
        echo "  Expected: $expected"
        echo "  Got: ${response:0:150}"
    fi
}

echo "=== Core Service Tests ==="
test_endpoint "MLflow UI" "http://localhost/mlflow/" "<!doctype html"
test_endpoint "MLflow API Health" "http://localhost/api/v1/health" '"status"'
test_endpoint "Ray Dashboard" "http://localhost/ray/" "Ray Dashboard"
test_endpoint "Traefik Dashboard" "http://localhost:8090/api/overview" '"http"'

echo ""
echo "=== LAN Access Tests (${SERVER_IP}) ==="
test_endpoint "MLflow UI (LAN)" "http://localhost/mlflow/" "<!doctype html"
test_endpoint "MLflow API (LAN)" "http://localhost/api/v1/health" '"status"'
test_endpoint "Ray Dashboard (LAN)" "http://localhost/ray/" "Ray Dashboard"

echo ""
echo "=== API Functionality Tests ==="
test_json_post "MLflow Experiments API" "http://localhost/api/2.0/mlflow/experiments/search" '{"max_results": 10}' '"experiments"'
test_endpoint "Ray Cluster Status" "http://localhost/ray/api/cluster_status" '"result"'
test_endpoint "Ray Cluster Info" "http://localhost/ray/api/cluster_status" '"autoscalingStatus"'

echo ""
echo "=== Monitoring Tests ==="
test_http_code "MLflow Grafana" "http://localhost/mlflow-grafana/" "302"
test_http_code "Ray Grafana" "http://localhost/ray-grafana/" "302"
test_endpoint "MLflow Prometheus" "http://localhost/mlflow-prometheus/" "Found"

echo ""
echo "=== Database Management Tests ==="
test_endpoint "Adminer (MLflow)" "http://localhost/mlflow-adminer/" "Login - Adminer"

echo ""
echo "=== VPN Access Tests (Tailscale) ==="
test_http_code "MLflow UI (VPN)" "http://${TAILSCALE_IP}/mlflow/" "200"
test_http_code "Ray Dashboard (VPN)" "http://${TAILSCALE_IP}/ray/" "200"

echo ""
echo "=========================================="
echo "  TEST SUMMARY"
echo "=========================================="
echo "Passed: $PASSED"
echo "Failed: $FAILED"
echo ""

if [ $FAILED -eq 0 ]; then
    echo "✅ All tests passed!"
    echo "✅ Reorganization successful - all services working!"
    exit 0
else
    echo "⚠️  Some tests failed"
    exit 1
fi
