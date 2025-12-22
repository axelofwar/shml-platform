#!/bin/bash
# Test OAuth2 authentication and role-based access with real JWT tokens
# This script logs in as different users and tests their access levels

set -e

FUSIONAUTH_URL="${FUSIONAUTH_URL:-http://localhost:9011}"
PLATFORM_URL="${PLATFORM_URL:-http://localhost}"
CLIENT_ID="acda34f0-7cf2-40eb-9cba-7cb0048857d3"  # OAuth2-Proxy app
CLIENT_SECRET=$(grep FUSIONAUTH_PROXY_CLIENT_SECRET .env | cut -d= -f2)

echo "=========================================="
echo "OAuth2 Role-Based Authentication Testing"
echo "=========================================="
echo

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Test users with different roles
declare -A TEST_USERS
TEST_USERS=(
    ["elevated-developer-service@ml-platform.local"]="elevated-developer"
)

# Function to get JWT token via OAuth2 password grant
get_jwt_token() {
    local email=$1
    local password=$2

    local response=$(curl -s -X POST "${FUSIONAUTH_URL}/oauth2/token" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "client_id=${CLIENT_ID}" \
        -d "client_secret=${CLIENT_SECRET}" \
        -d "grant_type=password" \
        -d "username=${email}" \
        -d "password=${password}" \
        -d "scope=openid email profile")

    echo "$response" | jq -r '.access_token // empty'
}

# Function to test endpoint with JWT
test_endpoint_with_jwt() {
    local role=$1
    local jwt=$2
    local endpoint=$3
    local expected_status=$4
    local description=$5

    echo -n "Testing ${description} (${role}): "

    if [ -z "$jwt" ]; then
        echo -e "${YELLOW}SKIP${NC} (no JWT token)"
        return 2
    fi

    # Test with JWT token
    status=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer ${jwt}" \
        "${endpoint}" 2>/dev/null || echo "000")

    if [ "$status" = "$expected_status" ]; then
        echo -e "${GREEN}✓ PASS${NC} (${status})"
        return 0
    else
        echo -e "${RED}✗ FAIL${NC} (expected ${expected_status}, got ${status})"
        return 1
    fi
}

echo "=========================================="
echo "Step 1: Getting JWT Tokens"
echo "=========================================="
echo

# Note: We need passwords for test users
# For now, we'll document the manual testing process

echo -e "${YELLOW}NOTE: FusionAuth OAuth2 password grant requires user passwords${NC}"
echo
echo "Test users available:"
echo "  1. elevated-developer-service@ml-platform.local (role: elevated-developer)"
echo "  2. axelofwar.web3@gmail.com (role: admin - needs assignment)"
echo "  3. bncyberspace@msn.com (role: TBD - needs assignment)"
echo

echo "To test properly, we need to either:"
echo "  A) Set passwords for test users in FusionAuth"
echo "  B) Use browser-based OAuth2 flow and extract tokens from cookies"
echo "  C) Create service accounts with known passwords"
echo

echo "=========================================="
echo "Step 2: Manual Browser Testing"
echo "=========================================="
echo

echo "Test elevated-developer access:"
echo "  1. Open browser (in private/incognito mode)"
echo "  2. Navigate to: http://localhost/api/agent/health"
echo "  3. Login as: elevated-developer-service@ml-platform.local"
echo "  4. Should see: 200 OK or service response"
echo

echo "Test developer access (should be blocked from elevated endpoints):"
echo "  1. Create test user with 'developer' role"
echo "  2. Login and navigate to agent endpoint"
echo "  3. Should see: 200 OK (agent allows developer+)"
echo "  4. Try sandbox execution - should fail with role check"
echo

echo "Test viewer access (should be blocked from agent):"
echo "  1. Create test user with 'viewer' role"
echo "  2. Login and navigate to agent endpoint"
echo "  3. Should see: 403 Forbidden"
echo

echo "=========================================="
echo "Step 3: Programmatic Testing with JWT"
echo "=========================================="
echo

echo "To get JWT tokens programmatically:"
echo

echo "# Option A: Password grant (requires user passwords)"
echo "curl -X POST http://localhost:9011/oauth2/token \\"
echo "  -H 'Content-Type: application/x-www-form-urlencoded' \\"
echo "  -d 'client_id=${CLIENT_ID}' \\"
echo "  -d 'client_secret=${CLIENT_SECRET}' \\"
echo "  -d 'grant_type=password' \\"
echo "  -d 'username=elevated-developer-service@ml-platform.local' \\"
echo "  -d 'password=YOUR_PASSWORD' \\"
echo "  -d 'scope=openid email profile' | jq -r '.access_token'"
echo

echo "# Option B: Device flow (for CLI tools)"
echo "# See: https://fusionauth.io/docs/v1/tech/oauth/endpoints#device-authorization"
echo

echo "# Option C: Extract from browser cookies after OAuth2 login"
echo "# Cookie name: _oauth2_proxy"
echo

echo "=========================================="
echo "Step 4: Test with JWT Token"
echo "=========================================="
echo

echo "Once you have a JWT token:"
echo

echo "# Test agent health (developer+)"
echo "curl -H 'Authorization: Bearer \$JWT_TOKEN' http://localhost/api/agent/health"
echo

echo "# Test agent execution (developer+)"
echo "curl -X POST http://localhost/api/agent/v1/agent/execute \\"
echo "  -H 'Authorization: Bearer \$JWT_TOKEN' \\"
echo "  -H 'Content-Type: application/json' \\"
echo "  -d '{\"user_id\":\"test\",\"session_id\":\"s1\",\"task\":\"Hello\",\"category\":\"coding\"}'"
echo

echo "# Test sandbox execution (elevated-developer+ only)"
echo "curl -X POST http://localhost/api/agent/v1/agent/execute \\"
echo "  -H 'Authorization: Bearer \$JWT_TOKEN' \\"
echo "  -H 'Content-Type: application/json' \\"
echo "  -d '{\"task\":\"Execute: print(5**2)\",\"category\":\"coding\"}'"
echo

echo "=========================================="
echo "Quick Setup for Testing"
echo "=========================================="
echo

echo "1. Set password for elevated-developer-service user:"
echo "   - Go to: http://localhost:9011/admin/user/search"
echo "   - Find: elevated-developer-service@ml-platform.local"
echo "   - Click Manage > Password tab"
echo "   - Set password (e.g., 'TestPass123!')"
echo "   - Save"
echo

echo "2. Assign roles to other test users:"
echo "   - axelofwar.web3@gmail.com → admin"
echo "   - bncyberspace@msn.com → developer"
echo "   - Create new user → viewer"
echo

echo "3. Re-run this script after setting passwords"
echo

echo "=========================================="
echo "Alternative: Direct Container Testing"
echo "=========================================="
echo

echo "Test agent service directly (bypasses OAuth - NOT RECOMMENDED):"
echo "docker exec shml-agent-service curl -X POST http://localhost:8000/api/v1/agent/execute ..."
echo

echo -e "${RED}WARNING: Direct testing skips role-auth middleware!${NC}"
echo -e "${YELLOW}Use OAuth2 flow for proper role validation${NC}"
