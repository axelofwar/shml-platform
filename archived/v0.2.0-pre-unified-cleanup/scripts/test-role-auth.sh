#!/bin/bash
# Test role-based authentication with FusionAuth API keys
# Tests viewer, developer, elevated-developer, and admin access

set -e

PLATFORM_URL="${PLATFORM_URL:-http://localhost}"
FUSIONAUTH_URL="${FUSIONAUTH_URL:-http://localhost:9011}"

echo "=================================="
echo "Role-Based Auth Testing"
echo "=================================="
echo

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to test endpoint with API key
test_endpoint() {
    local role=$1
    local api_key=$2
    local endpoint=$3
    local expected_status=$4
    local description=$5

    echo -n "Testing ${description} (${role}): "

    # Get actual status code
    status=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer ${api_key}" \
        "${endpoint}" 2>/dev/null || echo "000")

    if [ "$status" = "$expected_status" ]; then
        echo -e "${GREEN}✓ PASS${NC} (${status})"
        return 0
    else
        echo -e "${RED}✗ FAIL${NC} (expected ${expected_status}, got ${status})"
        return 1
    fi
}

# Check if FusionAuth API keys are provided
if [ -z "$VIEWER_API_KEY" ] || [ -z "$DEVELOPER_API_KEY" ] || [ -z "$ADMIN_API_KEY" ]; then
    echo -e "${YELLOW}WARNING: API keys not found in environment${NC}"
    echo "Please set the following environment variables:"
    echo "  export VIEWER_API_KEY='...'"
    echo "  export DEVELOPER_API_KEY='...'"
    echo "  export ADMIN_API_KEY='...'"
    echo
    echo "You can find these in FusionAuth Admin UI:"
    echo "  ${FUSIONAUTH_URL}/admin/api-key"
    echo
    exit 1
fi

echo "Testing with API keys:"
echo "  Viewer:    ${VIEWER_API_KEY:0:20}..."
echo "  Developer: ${DEVELOPER_API_KEY:0:20}..."
echo "  Admin:     ${ADMIN_API_KEY:0:20}..."
echo

# Track pass/fail counts
PASS=0
FAIL=0

echo "=================================="
echo "1. Inference Endpoints (No Auth)"
echo "=================================="

# Inference endpoints should work without auth
test_endpoint "none" "" "${PLATFORM_URL}/api/coding/health" "200" "Coding model health" && ((PASS++)) || ((FAIL++))
test_endpoint "none" "" "${PLATFORM_URL}/api/chat/health" "200" "Chat API health" && ((PASS++)) || ((FAIL++))

echo
echo "=================================="
echo "2. Viewer Role Access"
echo "=================================="

# Viewer should access grafana but not MLflow/Ray
test_endpoint "viewer" "$VIEWER_API_KEY" "${PLATFORM_URL}/grafana/api/health" "200" "Grafana access" && ((PASS++)) || ((FAIL++))
test_endpoint "viewer" "$VIEWER_API_KEY" "${PLATFORM_URL}/mlflow/api/2.0/mlflow/experiments/list" "403" "MLflow blocked" && ((PASS++)) || ((FAIL++))
test_endpoint "viewer" "$VIEWER_API_KEY" "${PLATFORM_URL}/ray/api/version" "403" "Ray blocked" && ((PASS++)) || ((FAIL++))
test_endpoint "viewer" "$VIEWER_API_KEY" "${PLATFORM_URL}/api/agent/health" "403" "Agent blocked" && ((PASS++)) || ((FAIL++))

echo
echo "=================================="
echo "3. Developer Role Access"
echo "=================================="

# Developer should access MLflow/Ray/Agent but not admin tools
test_endpoint "developer" "$DEVELOPER_API_KEY" "${PLATFORM_URL}/grafana/api/health" "200" "Grafana access" && ((PASS++)) || ((FAIL++))
test_endpoint "developer" "$DEVELOPER_API_KEY" "${PLATFORM_URL}/mlflow/api/2.0/mlflow/experiments/list" "200" "MLflow access" && ((PASS++)) || ((FAIL++))
test_endpoint "developer" "$DEVELOPER_API_KEY" "${PLATFORM_URL}/ray/api/version" "200" "Ray access" && ((PASS++)) || ((FAIL++))
test_endpoint "developer" "$DEVELOPER_API_KEY" "${PLATFORM_URL}/api/agent/health" "200" "Agent access" && ((PASS++)) || ((FAIL++))
test_endpoint "developer" "$DEVELOPER_API_KEY" "${PLATFORM_URL}/prometheus/api/v1/query?query=up" "403" "Prometheus blocked" && ((PASS++)) || ((FAIL++))

echo
echo "=================================="
echo "4. Admin Role Access"
echo "=================================="

# Admin should access everything
test_endpoint "admin" "$ADMIN_API_KEY" "${PLATFORM_URL}/grafana/api/health" "200" "Grafana access" && ((PASS++)) || ((FAIL++))
test_endpoint "admin" "$ADMIN_API_KEY" "${PLATFORM_URL}/mlflow/api/2.0/mlflow/experiments/list" "200" "MLflow access" && ((PASS++)) || ((FAIL++))
test_endpoint "admin" "$ADMIN_API_KEY" "${PLATFORM_URL}/ray/api/version" "200" "Ray access" && ((PASS++)) || ((FAIL++))
test_endpoint "admin" "$ADMIN_API_KEY" "${PLATFORM_URL}/api/agent/health" "200" "Agent access" && ((PASS++)) || ((FAIL++))
test_endpoint "admin" "$ADMIN_API_KEY" "${PLATFORM_URL}/prometheus/api/v1/query?query=up" "200" "Prometheus access" && ((PASS++)) || ((FAIL++))

echo
echo "=================================="
echo "5. Agent Service Sandbox Access"
echo "=================================="

# Test agent execution with code execution (elevated-developer or admin only)
echo "Testing agent execution with sandbox access..."

# Developer should NOT be able to use sandboxes
echo -n "Testing sandbox with developer key: "
RESPONSE=$(curl -s -X POST "${PLATFORM_URL}/api/agent/v1/agent/execute" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${DEVELOPER_API_KEY}" \
    -d '{
        "user_id": "test-user",
        "session_id": "test-sandbox-dev",
        "task": "Write and execute a Python function that prints Hello World",
        "category": "coding",
        "max_iterations": 1
    }' 2>/dev/null || echo '{"error":"request failed"}')

if echo "$RESPONSE" | grep -q "error.*elevated"; then
    echo -e "${GREEN}✓ PASS${NC} (sandbox correctly blocked)"
    ((PASS++))
else
    echo -e "${RED}✗ FAIL${NC} (sandbox should be blocked)"
    ((FAIL++))
fi

# Admin SHOULD be able to use sandboxes
echo -n "Testing sandbox with admin key: "
RESPONSE=$(curl -s -X POST "${PLATFORM_URL}/api/agent/v1/agent/execute" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${ADMIN_API_KEY}" \
    -d '{
        "user_id": "test-admin",
        "session_id": "test-sandbox-admin",
        "task": "Write and execute a Python function that prints Hello World",
        "category": "coding",
        "max_iterations": 1
    }' 2>/dev/null || echo '{"error":"request failed"}')

if echo "$RESPONSE" | grep -q "generator_output\|session_id"; then
    echo -e "${GREEN}✓ PASS${NC} (sandbox access granted)"
    ((PASS++))
else
    echo -e "${RED}✗ FAIL${NC} (sandbox should be allowed)"
    ((FAIL++))
fi

echo
echo "=================================="
echo "Test Summary"
echo "=================================="
echo -e "Passed: ${GREEN}${PASS}${NC}"
echo -e "Failed: ${RED}${FAIL}${NC}"
echo "Total:  $((PASS + FAIL))"
echo

if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}✓ All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}✗ Some tests failed${NC}"
    exit 1
fi
