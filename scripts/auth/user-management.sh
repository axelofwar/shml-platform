#!/bin/bash
# =============================================================================
# Unified User Management Script for SHML Platform
# =============================================================================
# Consolidates: verify_user_email.sh, verify_all_registrations.sh,
#               user_verification_report.sh
#
# Usage:
#   ./scripts/user-management.sh verify <email|user-id>  # Verify single user
#   ./scripts/user-management.sh verify-all              # Verify all registrations
#   ./scripts/user-management.sh report                  # Generate verification report
#   ./scripts/user-management.sh list                    # List all users
#   ./scripts/user-management.sh roles <email>           # Show user roles
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Load environment variables
if [ -f "${PROJECT_ROOT}/.env" ]; then
    source "${PROJECT_ROOT}/.env"
fi

# Configuration
FUSIONAUTH_API_KEY="${FUSIONAUTH_API_KEY:-}"
OAUTH2_PROXY_APP_ID="${OAUTH2_PROXY_APP_ID:-acda34f0-7cf2-40eb-9cba-7cb0048857d3}"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-shml-postgres}"

# =============================================================================
# Helper Functions
# =============================================================================

print_header() {
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════════════════${NC}"
    echo
}

print_success() { echo -e "${GREEN}✓ $1${NC}"; }
print_error() { echo -e "${RED}✗ $1${NC}"; }
print_warning() { echo -e "${YELLOW}⚠ $1${NC}"; }
print_info() { echo -e "${CYAN}ℹ $1${NC}"; }

check_fusionauth() {
    if ! docker ps --format '{{.Names}}' | grep -q "fusionauth"; then
        print_error "FusionAuth container is not running"
        exit 1
    fi
}

check_postgres() {
    if ! docker ps --format '{{.Names}}' | grep -qE "^(shml-postgres|shared-postgres|fusionauth-postgres)$"; then
        print_error "PostgreSQL container is not running"
        exit 1
    fi
    # Find the actual container name
    POSTGRES_CONTAINER=$(docker ps --format '{{.Names}}' | grep -E "^(shml-postgres|shared-postgres)$" | head -1)
}

get_api_key() {
    if [ -z "$FUSIONAUTH_API_KEY" ]; then
        # Try to find it in various places
        if [ -f "${PROJECT_ROOT}/.env" ]; then
            FUSIONAUTH_API_KEY=$(grep "^FUSIONAUTH_API_KEY=" "${PROJECT_ROOT}/.env" | cut -d= -f2 | tr -d '"' | tr -d "'")
        fi
    fi

    if [ -z "$FUSIONAUTH_API_KEY" ]; then
        print_error "FUSIONAUTH_API_KEY not found"
        echo "Set it in .env or export FUSIONAUTH_API_KEY=..."
        exit 1
    fi
}

# =============================================================================
# Verify Single User
# =============================================================================

verify_user() {
    local user_identifier="$1"

    if [ -z "$user_identifier" ]; then
        echo "Usage: $0 verify <email|user-id>"
        echo "Example: $0 verify user@example.com"
        exit 1
    fi

    check_fusionauth
    get_api_key

    print_header "User Verification: ${user_identifier}"

    local user_id=""

    # Determine if it's an email or user ID
    if [[ "$user_identifier" == *"@"* ]]; then
        echo "🔍 Searching for user by email..."
        user_id=$(docker exec fusionauth curl -s "http://localhost:9011/api/user/search" \
            -X POST \
            -H "Authorization: $FUSIONAUTH_API_KEY" \
            -H "Content-Type: application/json" \
            -d "{\"search\":{\"queryString\":\"email:$user_identifier\"}}" | jq -r '.users[0].id // empty')

        if [ -z "$user_id" ]; then
            print_error "User not found with email: $user_identifier"
            exit 1
        fi
        print_success "Found user ID: $user_id"
    else
        user_id="$user_identifier"
    fi

    echo
    echo "📋 Current user details:"
    docker exec fusionauth curl -s "http://localhost:9011/api/user/$user_id" \
        -H "Authorization: $FUSIONAUTH_API_KEY" | jq '{
            id: .user.id,
            email: .user.email,
            verified: .user.verified,
            active: .user.active,
            registrations: [.user.registrations[]? | {
                applicationId: .applicationId,
                roles: .roles,
                verified: .verified
            }]
        }'

    echo
    read -p "🔧 Do you want to verify this user's email and registrations? (y/n): " -n 1 -r
    echo

    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_warning "Cancelled"
        exit 0
    fi

    # Verify email
    echo "Verifying email..."
    docker exec fusionauth curl -s -X PUT "http://localhost:9011/api/user/$user_id" \
        -H "Authorization: $FUSIONAUTH_API_KEY" \
        -H "Content-Type: application/json" \
        -d '{"user":{"verified":true}}' > /dev/null

    # Verify registrations via direct DB update
    check_postgres
    echo "Verifying registrations..."
    docker exec "$POSTGRES_CONTAINER" psql -U fusionauth -d fusionauth -c \
        "UPDATE user_registrations SET verified = true WHERE users_id = '$user_id';" > /dev/null 2>&1

    print_success "User verified successfully"

    echo
    echo "📋 Updated user details:"
    docker exec fusionauth curl -s "http://localhost:9011/api/user/$user_id" \
        -H "Authorization: $FUSIONAUTH_API_KEY" | jq '{
            email: .user.email,
            verified: .user.verified,
            registrations: [.user.registrations[]? | {verified: .verified}]
        }'
}

# =============================================================================
# Verify All Registrations
# =============================================================================

verify_all() {
    check_postgres

    print_header "Verify All User Registrations"

    echo "📋 Finding unverified registrations..."
    local unverified=$(docker exec "$POSTGRES_CONTAINER" psql -U fusionauth -d fusionauth -t -c "
        SELECT i.email, ur.users_id, ur.applications_id, ur.verified
        FROM user_registrations ur
        JOIN users u ON ur.users_id = u.id
        JOIN identities i ON u.id = i.users_id
        WHERE ur.applications_id = '$OAUTH2_PROXY_APP_ID' AND ur.verified = false;
    ")

    if [ -z "$(echo "$unverified" | tr -d '[:space:]')" ]; then
        print_success "All registrations are already verified!"
        exit 0
    fi

    echo "Found unverified registrations:"
    echo "$unverified"
    echo

    read -p "🤔 Do you want to verify all these registrations? (y/n): " -n 1 -r
    echo

    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_warning "Cancelled. No changes made."
        exit 0
    fi

    echo "✉️ Verifying all registrations..."
    docker exec "$POSTGRES_CONTAINER" psql -U fusionauth -d fusionauth -c "
        UPDATE user_registrations
        SET verified = true
        WHERE applications_id = '$OAUTH2_PROXY_APP_ID' AND verified = false;
    "

    print_success "All registrations verified!"

    echo
    echo "📋 Current registration status:"
    docker exec "$POSTGRES_CONTAINER" psql -U fusionauth -d fusionauth -c "
        SELECT
            i.email,
            CASE WHEN i.verified THEN '✅' ELSE '❌' END as email_verified,
            CASE WHEN ur.verified THEN '✅' ELSE '❌' END as registration_verified
        FROM user_registrations ur
        JOIN users u ON ur.users_id = u.id
        JOIN identities i ON u.id = i.users_id
        WHERE ur.applications_id = '$OAUTH2_PROXY_APP_ID'
        ORDER BY i.email;
    "
}

# =============================================================================
# Generate Verification Report
# =============================================================================

report() {
    check_fusionauth
    check_postgres
    get_api_key

    print_header "FUSIONAUTH USER VERIFICATION REPORT"

    # 1. Tenant Configuration
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "1️⃣  TENANT EMAIL VERIFICATION SETTINGS"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    docker exec fusionauth curl -s "http://localhost:9011/api/tenant" \
        -H "Authorization: $FUSIONAUTH_API_KEY" | \
        jq -r '.tenants[] |
            "Tenant: \(.name)\n" +
            "  ├─ Verify Email: \(.emailConfiguration.verifyEmail)\n" +
            "  ├─ Verify Email When Changed: \(.emailConfiguration.verifyEmailWhenChanged)\n" +
            "  └─ Verification Strategy: \(.emailConfiguration.verificationStrategy)"'
    echo

    # 2. Application Configuration
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "2️⃣  APPLICATION REGISTRATION VERIFICATION SETTINGS"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    docker exec fusionauth curl -s "http://localhost:9011/api/application/$OAUTH2_PROXY_APP_ID" \
        -H "Authorization: $FUSIONAUTH_API_KEY" | \
        jq -r '.application |
            "Application: \(.name)\n" +
            "  ├─ Verify Registration: \(.verifyRegistration)\n" +
            "  └─ Registration Type: \(.registrationConfiguration.type)"'
    echo

    # 3. User Verification Status
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "3️⃣  USER VERIFICATION STATUS"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    docker exec "$POSTGRES_CONTAINER" psql -U fusionauth -d fusionauth -c "
        SELECT
            i.email as \"Email\",
            CASE WHEN i.verified THEN '✅' ELSE '❌' END as \"Email\",
            CASE WHEN ur.verified THEN '✅' ELSE '❌' END as \"Reg\",
            COALESCE(
                (SELECT string_agg(ar.name, ', ')
                 FROM user_registrations_application_roles urar
                 JOIN application_roles ar ON urar.application_roles_id = ar.id
                 WHERE urar.user_registrations_id = ur.id
                 GROUP BY urar.user_registrations_id),
                'no roles'
            ) as \"Roles\",
            CASE
                WHEN i.verified AND ur.verified THEN '✅ OK'
                WHEN i.verified AND NOT ur.verified THEN '⚠️ Reg!'
                WHEN NOT i.verified AND ur.verified THEN '⚠️ Email!'
                ELSE '❌ Both'
            END as \"Status\"
        FROM user_registrations ur
        JOIN users u ON ur.users_id = u.id
        JOIN identities i ON u.id = i.users_id
        WHERE ur.applications_id = '$OAUTH2_PROXY_APP_ID'
        ORDER BY i.email;
    "

    # 4. Summary
    echo
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "4️⃣  SUMMARY"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    docker exec "$POSTGRES_CONTAINER" psql -U fusionauth -d fusionauth -t -c "
        SELECT
            'Total users: ' || COUNT(DISTINCT ur.users_id) ||
            ', Fully verified: ' || COUNT(CASE WHEN i.verified AND ur.verified THEN 1 END) ||
            ', Need attention: ' || COUNT(CASE WHEN NOT (i.verified AND ur.verified) THEN 1 END)
        FROM user_registrations ur
        JOIN users u ON ur.users_id = u.id
        JOIN identities i ON u.id = i.users_id
        WHERE ur.applications_id = '$OAUTH2_PROXY_APP_ID';
    "
}

# =============================================================================
# List All Users
# =============================================================================

list_users() {
    check_postgres

    print_header "All Platform Users"

    docker exec "$POSTGRES_CONTAINER" psql -U fusionauth -d fusionauth -c "
        SELECT
            i.email as \"Email\",
            u.active as \"Active\",
            i.verified as \"Verified\",
            to_char(to_timestamp(u.insert_instant/1000), 'YYYY-MM-DD') as \"Created\"
        FROM users u
        JOIN identities i ON u.id = i.users_id
        ORDER BY u.insert_instant DESC;
    "
}

# =============================================================================
# Show User Roles
# =============================================================================

show_roles() {
    local email="$1"

    if [ -z "$email" ]; then
        echo "Usage: $0 roles <email>"
        exit 1
    fi

    check_postgres

    print_header "Roles for: ${email}"

    docker exec "$POSTGRES_CONTAINER" psql -U fusionauth -d fusionauth -c "
        SELECT
            a.name as \"Application\",
            COALESCE(string_agg(ar.name, ', '), 'no roles') as \"Roles\"
        FROM user_registrations ur
        JOIN users u ON ur.users_id = u.id
        JOIN identities i ON u.id = i.users_id
        JOIN applications a ON ur.applications_id = a.id
        LEFT JOIN user_registrations_application_roles urar ON ur.id = urar.user_registrations_id
        LEFT JOIN application_roles ar ON urar.application_roles_id = ar.id
        WHERE i.email = '$email'
        GROUP BY a.name;
    "
}

# =============================================================================
# Main
# =============================================================================

show_usage() {
    echo "SHML Platform User Management Tool"
    echo
    echo "Usage: $0 <command> [options]"
    echo
    echo "Commands:"
    echo "  verify <email|id>   Verify a single user's email and registrations"
    echo "  verify-all          Verify all unverified registrations"
    echo "  report              Generate comprehensive verification report"
    echo "  list                List all platform users"
    echo "  roles <email>       Show roles for a specific user"
    echo
    echo "Examples:"
    echo "  $0 verify user@example.com"
    echo "  $0 verify-all"
    echo "  $0 report"
    echo "  $0 roles admin@example.com"
    echo
    echo "Environment Variables:"
    echo "  FUSIONAUTH_API_KEY     FusionAuth API key"
    echo "  OAUTH2_PROXY_APP_ID    OAuth2 Proxy application ID"
}

main() {
    local command="${1:-}"
    shift 2>/dev/null || true

    case "$command" in
        verify)
            verify_user "$@"
            ;;
        verify-all)
            verify_all
            ;;
        report)
            report
            ;;
        list)
            list_users
            ;;
        roles)
            show_roles "$@"
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
