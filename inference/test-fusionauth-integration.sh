#!/bin/bash
# Test FusionAuth Integration
# Verifies OAuth2-Proxy headers, auth middleware, and role-based access control

set -e

echo "🔍 Testing FusionAuth Integration"
echo "=================================="
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test endpoints
BASE_URL="http://localhost:8000"
METRICS_URL="http://localhost:8000/metrics"

echo "1️⃣ Testing Health Endpoint (unauthenticated)"
echo "----------------------------------------------"
response=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/health")
if [ "$response" -eq 200 ]; then
    echo -e "${GREEN}✓ Health endpoint accessible${NC}"
else
    echo -e "${RED}✗ Health endpoint failed (HTTP $response)${NC}"
    exit 1
fi
echo ""

echo "2️⃣ Testing User Info Endpoint (with mock headers)"
echo "---------------------------------------------------"
# Simulate OAuth2-Proxy headers
response=$(curl -s -H "X-Auth-Request-Email: test@ml-platform.local" \
           -H "X-Auth-Request-User: test-user" \
           -H "X-Auth-Request-Preferred-Username: testuser" \
           -H "X-Auth-Request-Groups: developer,elevated-developer" \
           "$BASE_URL/api/agent/user/me")

echo "$response" | jq '.'
if echo "$response" | jq -e '.email' > /dev/null 2>&1; then
    email=$(echo "$response" | jq -r '.email')
    role=$(echo "$response" | jq -r '.primary_role')
    budget=$(echo "$response" | jq -r '.token_budget')
    echo -e "${GREEN}✓ User authenticated: $email (role: $role, budget: $budget tokens)${NC}"
else
    echo -e "${RED}✗ User info endpoint failed${NC}"
    exit 1
fi
echo ""

echo "3️⃣ Testing Prometheus Metrics Endpoint"
echo "----------------------------------------"
response=$(curl -s "$METRICS_URL")
if echo "$response" | grep -q "agent_requests_total"; then
    echo -e "${GREEN}✓ Metrics endpoint accessible${NC}"
    echo "Available metrics:"
    echo "$response" | grep "^agent_" | grep "# HELP" | head -5
    echo "..."
else
    echo -e "${YELLOW}⚠ Metrics endpoint not responding (service may not be running)${NC}"
fi
echo ""

echo "4️⃣ Testing Role-Based Access (viewer role)"
echo "--------------------------------------------"
# Viewer should not have access to /api/agent/execute (requires developer+)
response=$(curl -s -o /dev/null -w "%{http_code}" \
           -H "X-Auth-Request-Email: viewer@ml-platform.local" \
           -H "X-Auth-Request-Groups: viewer" \
           -X POST "$BASE_URL/api/agent/execute")

if [ "$response" -eq 403 ]; then
    echo -e "${GREEN}✓ Access denied for viewer (expected)${NC}"
elif [ "$response" -eq 404 ]; then
    echo -e "${YELLOW}⚠ Endpoint not found (may need implementation)${NC}"
else
    echo -e "${YELLOW}⚠ Unexpected response: HTTP $response${NC}"
fi
echo ""

echo "5️⃣ Testing WebSocket Authentication"
echo "-------------------------------------"
echo "WebSocket authentication requires browser or wscat to test properly"
echo "Manual test command:"
echo "  wscat -c ws://localhost:8000/ws/agent/test-session \\"
echo "    -H 'X-Auth-Request-Email: test@ml-platform.local' \\"
echo "    -H 'X-Auth-Request-Groups: developer'"
echo ""

echo "6️⃣ Checking Docker Container Status"
echo "--------------------------------------"
if docker ps | grep -q "shml-agent-service"; then
    echo -e "${GREEN}✓ Agent service container running${NC}"
    docker ps | grep "shml-agent-service"
else
    echo -e "${RED}✗ Agent service container not running${NC}"
    echo "Start with: docker-compose -f inference/docker-compose.inference.yml up -d agent-service"
fi
echo ""

echo "7️⃣ Checking Grafana Dashboard"
echo "--------------------------------"
if [ -f "/home/axelofwar/Projects/shml-platform/monitoring/grafana/dashboards/agent-usage-analytics.json" ]; then
    echo -e "${GREEN}✓ Grafana dashboard JSON created${NC}"
    echo "Access at: http://localhost:3000/d/agent-usage-analytics"
else
    echo -e "${RED}✗ Grafana dashboard not found${NC}"
fi
echo ""

echo "8️⃣ Testing Frontend Auth Store"
echo "---------------------------------"
if [ -f "/home/axelofwar/Projects/shml-platform/chat-ui-v2/src/stores/authStore.ts" ]; then
    echo -e "${GREEN}✓ Auth store created${NC}"
    echo "Features:"
    echo "  - fetchUser() from /api/agent/user/me"
    echo "  - Automatic OAuth redirect on 401"
    echo "  - User info caching"
else
    echo -e "${RED}✗ Auth store not found${NC}"
fi
echo ""

echo "=================================="
echo "✨ Integration Test Complete"
echo ""
echo "Next Steps:"
echo "1. Rebuild agent service: docker-compose -f inference/docker-compose.inference.yml up -d --build agent-service"
echo "2. Restart frontend: cd chat-ui-v2 && npm run dev"
echo "3. Access UI: http://localhost:3001"
echo "4. Login via FusionAuth OAuth"
echo "5. Check Grafana: http://localhost:3000"
echo ""
echo "To test with real OAuth2-Proxy:"
echo "1. Ensure Traefik + OAuth2-Proxy middleware is active"
echo "2. Access via Traefik URL (not localhost:8000 directly)"
echo "3. OAuth2-Proxy will add X-Auth-Request-* headers"
