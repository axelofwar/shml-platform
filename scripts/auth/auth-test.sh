#!/bin/bash
# =============================================================================
# Unified Authentication Testing Script for SHML Platform
# =============================================================================
# Consolidates: test-oauth2-roles.sh, test-role-auth.sh, debug_auth_flow.sh
#
# Usage:
#   ./scripts/auth-test.sh oauth2 [user]     # Test OAuth2 with JWT tokens
#   ./scripts/auth-test.sh roles             # Test role-based API access
#   ./scripts/auth-test.sh debug [endpoint]  # Debug auth flow
#   ./scripts/auth-test.sh flow              # Trace full auth flow
#   ./scripts/auth-test.sh endpoints         # Test all protected endpoints
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Load environment variables
if [ -f "${PROJECT_ROOT}/.env" ]; then
    source "${PROJECT_ROOT}/.env"
fi

# Configuration
FUSIONAUTH_URL="${FUSIONAUTH_URL:-http://localhost:9011}"
PLATFORM_URL="${PLATFORM_URL:-http://localhost}"
CLIENT_ID="${FUSIONAUTH_PROXY_CLIENT_ID:-acda34f0-7cf2-40eb-9cba-7cb0048857d3}"
CLIENT_SECRET="${FUSIONAUTH_PROXY_CLIENT_SECRET:-}"

# Test counters
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# =============================================================================
# Helper Functions
# =============================================================================

print_header() {
    echo -e "${BLUE}══════════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}══════════════════════════════════════════════════════════════════════════${NC}"
    echo
}

print_subheader() {
    echo -e "${CYAN}── $1 ──${NC}"
}

print_success() { echo -e "${GREEN}✓ $1${NC}"; }
print_error() { echo -e "${RED}✗ $1${NC}"; }
print_warning() { echo -e "${YELLOW}⚠ $1${NC}"; }
print_info() { echo -e "${CYAN}ℹ $1${NC}"; }

test_result() {
    local name="$1"
    local expected="$2"
    local actual="$3"

    ((TESTS_RUN++))

    if [ "$expected" = "$actual" ]; then
        print_success "$name (expected: $expected, got: $actual)"
        ((TESTS_PASSED++))
        return 0
    else
        print_error "$name (expected: $expected, got: $actual)"
        ((TESTS_FAILED++))
        return 1
    fi
}

# =============================================================================
# OAuth2 JWT Token Testing
# =============================================================================

get_jwt_token() {
    local email="$1"
    local password="$2"

    if [ -z "$CLIENT_SECRET" ]; then
        print_error "CLIENT_SECRET not set. Export FUSIONAUTH_PROXY_CLIENT_SECRET"
        return 1
    fi

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

decode_jwt() {
    local token="$1"

    if [ -z "$token" ]; then
        echo "No token provided"
        return 1
    fi

    # Decode JWT payload (middle part)
    local payload=$(echo "$token" | cut -d'.' -f2)

    # Add padding if needed and decode
    local padding=$((4 - ${#payload} % 4))
    if [ $padding -ne 4 ]; then
        payload="${payload}$(printf '=%.0s' $(seq 1 $padding))"
    fi

    echo "$payload" | base64 -d 2>/dev/null | jq . 2>/dev/null || echo "Failed to decode"
}

test_oauth2() {
    local test_user="${1:-}"

    print_header "OAuth2 JWT Token Testing"

    if [ -z "$CLIENT_SECRET" ]; then
        print_error "FUSIONAUTH_PROXY_CLIENT_SECRET not set in environment"
        echo "Export it or add to .env file"
        return 1
    fi

    # Test service account if no user specified
    if [ -z "$test_user" ]; then
        test_user="${SERVICE_ACCOUNT_USER:-elevated-developer-service@ml-platform.local}"
        local test_password="${SERVICE_ACCOUNT_PASSWORD:-}"

        if [ -z "$test_password" ]; then
            print_warning "No test user specified and SERVICE_ACCOUNT_PASSWORD not set"
            echo "Usage: $0 oauth2 <email>"
            echo "Or export SERVICE_ACCOUNT_USER and SERVICE_ACCOUNT_PASSWORD"
            return 1
        fi
    else
        echo -n "Password for ${test_user}: "
        read -s test_password
        echo
    fi

    echo "Testing OAuth2 token flow for: ${test_user}"
    echo

    # Get token
    print_subheader "1. Getting JWT Token"
    local token=$(get_jwt_token "$test_user" "$test_password")

    if [ -z "$token" ]; then
        print_error "Failed to get JWT token"
        return 1
    fi

    print_success "Got JWT token (${#token} chars)"
    echo "Token preview: ${token:0:50}..."
    echo

    # Decode token
    print_subheader "2. Decoded JWT Payload"
    decode_jwt "$token"
    echo

    # Test endpoints with token
    print_subheader "3. Testing Protected Endpoints"

    local endpoints=(
        "/api/ray/health:200"
        "/api/mlflow/health:200"
        "/mlflow/:200"
    )

    for ep in "${endpoints[@]}"; do
        local endpoint="${ep%:*}"
        local expected="${ep#*:}"

        local status=$(curl -s -o /dev/null -w "%{http_code}" \
            -H "Authorization: Bearer ${token}" \
            "${PLATFORM_URL}${endpoint}" 2>/dev/null || echo "000")

        test_result "GET ${endpoint}" "$expected" "$status"
    done

    print_test_summary
}

# =============================================================================
# Role-Based API Testing
# =============================================================================

test_roles() {
    print_header "Role-Based API Access Testing"

    # Check for API keys
    if [ -z "$VIEWER_API_KEY" ] && [ -z "$DEVELOPER_API_KEY" ] && [ -z "$ADMIN_API_KEY" ]; then
        print_warning "No API keys found in environment"
        echo
        echo "Set one or more of these environment variables:"
        echo "  export VIEWER_API_KEY='...'"
        echo "  export DEVELOPER_API_KEY='...'"
        echo "  export ELEVATED_DEVELOPER_API_KEY='...'"
        echo "  export ADMIN_API_KEY='...'"
        echo
        echo "You can find these in FusionAuth Admin UI:"
        echo "  ${FUSIONAUTH_URL}/admin/api-key"
        echo

        # Try to proceed with any available authentication
        print_info "Testing with anonymous access..."
        echo
    fi

    # Define test matrix
    declare -A role_tests

    # [endpoint]=expected_status for each role
    # Format: "endpoint:viewer_expected:developer_expected:admin_expected"
    local test_cases=(
        "/api/ray/health:200:200:200"
        "/api/ray/api/v1/jobs:401:200:200"
        "/mlflow/:200:200:200"
        "/api/mlflow/experiments:200:200:200"
    )

    # Test each role
    for role in viewer developer elevated-developer admin; do
        local api_key_var="${role^^}_API_KEY"
        api_key_var="${api_key_var//-/_}"
        local api_key="${!api_key_var:-}"

        if [ -n "$api_key" ]; then
            print_subheader "Testing as: ${role}"

            for case in "${test_cases[@]}"; do
                local endpoint=$(echo "$case" | cut -d: -f1)

                local status=$(curl -s -o /dev/null -w "%{http_code}" \
                    -H "Authorization: Bearer ${api_key}" \
                    "${PLATFORM_URL}${endpoint}" 2>/dev/null || echo "000")

                echo -n "  GET ${endpoint}: "
                if [ "$status" = "200" ] || [ "$status" = "302" ]; then
                    print_success "${status}"
                    ((TESTS_PASSED++))
                elif [ "$status" = "401" ] || [ "$status" = "403" ]; then
                    print_warning "${status} (auth required)"
                else
                    print_error "${status}"
                    ((TESTS_FAILED++))
                fi
                ((TESTS_RUN++))
            done
            echo
        fi
    done

    # Test anonymous access
    print_subheader "Testing: Anonymous (no auth)"
    for endpoint in "/api/ray/health" "/mlflow/" "/"; do
        local status=$(curl -s -o /dev/null -w "%{http_code}" \
            "${PLATFORM_URL}${endpoint}" 2>/dev/null || echo "000")

        ((TESTS_RUN++))
        echo -n "  GET ${endpoint}: "
        if [ "$status" = "200" ] || [ "$status" = "302" ]; then
            print_success "${status}"
            ((TESTS_PASSED++))
        else
            print_warning "${status}"
        fi
    done

    print_test_summary
}

# =============================================================================
# Debug Auth Flow
# =============================================================================

debug_auth() {
    local endpoint="${1:-/}"

    print_header "Debug Auth Flow"

    echo "Endpoint: ${PLATFORM_URL}${endpoint}"
    echo

    # Test with verbose curl
    print_subheader "1. Initial Request (no auth)"
    curl -v -s -o /dev/null "${PLATFORM_URL}${endpoint}" 2>&1 | grep -E "^[<>*]" | head -30
    echo

    # Check OAuth2-Proxy
    print_subheader "2. OAuth2-Proxy Status"
    local proxy_health=$(curl -s "${PLATFORM_URL}/oauth2/healthz" 2>/dev/null || echo "unavailable")
    echo "Health: ${proxy_health}"
    echo

    # Check FusionAuth
    print_subheader "3. FusionAuth Status"
    local fa_health=$(curl -s "${FUSIONAUTH_URL}/api/status" 2>/dev/null | jq -r '.health // "unavailable"' 2>/dev/null || echo "unavailable")
    echo "Health: ${fa_health}"
    echo

    # Check cookies
    print_subheader "4. Cookie Analysis"
    local cookies=$(curl -s -c - "${PLATFORM_URL}${endpoint}" 2>/dev/null | grep -v "^#" | awk '{print $6"="$7}' | head -5)
    if [ -n "$cookies" ]; then
        echo "Cookies set:"
        echo "$cookies"
    else
        echo "No cookies set"
    fi
    echo

    # Check redirect chain
    print_subheader "5. Redirect Chain"
    curl -s -L -w "Final URL: %{url_effective}\nTotal redirects: %{num_redirects}\n" \
        -o /dev/null "${PLATFORM_URL}${endpoint}" 2>/dev/null
}

# =============================================================================
# Full Auth Flow Trace
# =============================================================================

trace_flow() {
    print_header "Full Authentication Flow Trace"

    echo "This will trace the complete OAuth2 flow."
    echo "You may need to interact with the browser."
    echo

    # Step 1: Initial request
    print_subheader "Step 1: Initial Request"
    local initial=$(curl -s -I "${PLATFORM_URL}/" 2>/dev/null)
    echo "$initial" | grep -E "^(HTTP|Location|Set-Cookie)" | head -5
    echo

    # Step 2: OAuth2-Proxy redirect
    print_subheader "Step 2: OAuth2-Proxy Redirect"
    local oauth_start=$(curl -s -I "${PLATFORM_URL}/oauth2/start" 2>/dev/null)
    echo "$oauth_start" | grep -E "^(HTTP|Location)" | head -3
    echo

    # Step 3: FusionAuth authorize
    print_subheader "Step 3: FusionAuth Authorize Endpoint"
    local auth_url="${FUSIONAUTH_URL}/oauth2/authorize?client_id=${CLIENT_ID}&response_type=code&redirect_uri=${PLATFORM_URL}/oauth2/callback&scope=openid%20email%20profile"
    echo "URL: ${auth_url:0:100}..."
    local auth_response=$(curl -s -I "$auth_url" 2>/dev/null)
    echo "$auth_response" | grep -E "^(HTTP|Location)" | head -3
    echo

    # Step 4: Check callback endpoint
    print_subheader "Step 4: Callback Endpoint"
    echo "Callback URL: ${PLATFORM_URL}/oauth2/callback"
    echo "(Requires valid authorization code)"
    echo

    # Summary
    print_subheader "Flow Summary"
    echo "1. User visits protected resource"
    echo "2. OAuth2-Proxy redirects to /oauth2/start"
    echo "3. OAuth2-Proxy redirects to FusionAuth /oauth2/authorize"
    echo "4. User authenticates with FusionAuth"
    echo "5. FusionAuth redirects to /oauth2/callback with code"
    echo "6. OAuth2-Proxy exchanges code for token"
    echo "7. OAuth2-Proxy sets session cookie"
    echo "8. User is redirected to original resource"
}

# =============================================================================
# Test All Endpoints
# =============================================================================

test_endpoints() {
    print_header "Protected Endpoint Testing"

    local endpoints=(
        "/:Homer Dashboard"
        "/mlflow/:MLflow UI"
        "/api/ray/health:Ray API Health"
        "/api/mlflow/health:MLflow API Health"
        "/grafana/:Grafana"
        "/prometheus/:Prometheus"
    )

    print_subheader "Testing without authentication"
    for ep in "${endpoints[@]}"; do
        local path="${ep%:*}"
        local name="${ep#*:}"

        local status=$(curl -s -o /dev/null -w "%{http_code}" \
            "${PLATFORM_URL}${path}" 2>/dev/null || echo "000")

        ((TESTS_RUN++))
        printf "  %-30s %s → " "$name" "$path"

        case "$status" in
            200) print_success "$status (public)"; ((TESTS_PASSED++)) ;;
            302) print_warning "$status (redirect to auth)"; ((TESTS_PASSED++)) ;;
            401) print_warning "$status (auth required)"; ((TESTS_PASSED++)) ;;
            403) print_error "$status (forbidden)"; ((TESTS_FAILED++)) ;;
            404) print_warning "$status (not found)" ;;
            502|503) print_error "$status (service down)"; ((TESTS_FAILED++)) ;;
            *) print_error "$status"; ((TESTS_FAILED++)) ;;
        esac
    done

    print_test_summary
}

# =============================================================================
# Test Summary
# =============================================================================

print_test_summary() {
    echo
    echo "═══════════════════════════════════════════"
    echo "Test Summary"
    echo "═══════════════════════════════════════════"
    echo "  Total:  ${TESTS_RUN}"
    echo -e "  ${GREEN}Passed: ${TESTS_PASSED}${NC}"
    if [ $TESTS_FAILED -gt 0 ]; then
        echo -e "  ${RED}Failed: ${TESTS_FAILED}${NC}"
    else
        echo "  Failed: 0"
    fi
    echo "═══════════════════════════════════════════"

    if [ $TESTS_FAILED -gt 0 ]; then
        return 1
    fi
    return 0
}

# =============================================================================
# Main
# =============================================================================

show_usage() {
    echo "SHML Platform Authentication Testing Tool"
    echo
    echo "Usage: $0 <command> [options]"
    echo
    echo "Commands:"
    echo "  oauth2 [email]    Test OAuth2 password grant flow"
    echo "  roles             Test role-based API access"
    echo "  debug [endpoint]  Debug auth flow for endpoint"
    echo "  flow              Trace complete OAuth2 flow"
    echo "  endpoints         Test all protected endpoints"
    echo
    echo "Environment Variables:"
    echo "  FUSIONAUTH_URL                FusionAuth server URL"
    echo "  PLATFORM_URL                  Platform base URL"
    echo "  FUSIONAUTH_PROXY_CLIENT_ID    OAuth client ID"
    echo "  FUSIONAUTH_PROXY_CLIENT_SECRET OAuth client secret"
    echo "  VIEWER_API_KEY                Viewer role API key"
    echo "  DEVELOPER_API_KEY             Developer role API key"
    echo "  ADMIN_API_KEY                 Admin role API key"
    echo
    echo "Examples:"
    echo "  $0 endpoints              # Quick endpoint check"
    echo "  $0 oauth2 user@email.com  # Test OAuth2 for user"
    echo "  $0 debug /mlflow/         # Debug MLflow auth"
    echo "  $0 roles                  # Test all role access"
}

main() {
    local command="${1:-}"
    shift 2>/dev/null || true

    case "$command" in
        oauth2)
            test_oauth2 "$@"
            ;;
        roles)
            test_roles
            ;;
        debug)
            debug_auth "$@"
            ;;
        flow)
            trace_flow
            ;;
        endpoints)
            test_endpoints
            ;;
        -h|--help|help|"")
            show_usage
            ;;
        *)
            print_error "Unknown command: $command"
            echo
            show_usage
            exit 1
            ;;
    esac
}

main "$@"
