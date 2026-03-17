#!/bin/bash
# =============================================================================
# Setup Google Identity Provider in FusionAuth
# =============================================================================
# This script adds Google as an Identity Provider to FusionAuth, enabling
# "Sign in with Google" for users.
#
# Prerequisites:
# 1. Create Google OAuth credentials at: https://console.cloud.google.com/apis/credentials
# 2. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to your .env file
# 3. Add authorized redirect URI in Google Console:
#    https://${PUBLIC_DOMAIN}/oauth2/callback
#    OR your FusionAuth instance: http://localhost:9011/oauth2/callback
#
# Usage:
#   ./scripts/setup_google_idp.sh
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Load environment variables
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

# Configuration
FUSIONAUTH_URL="${FUSIONAUTH_URL:-http://localhost:9011}"
FUSIONAUTH_API_KEY="${FUSIONAUTH_API_KEY}"
GOOGLE_IDP_ID="${GOOGLE_IDP_ID:-82339786-3dff-42a6-aac6-1f1ceecb6c46}"

# Application IDs - use env vars or defaults from FusionAuth setup
OAUTH2_PROXY_APP_ID="${OAUTH2_PROXY_APP_ID:-${FUSIONAUTH_PROXY_CLIENT_ID}}"
MLFLOW_APP_ID="${MLFLOW_APP_ID:-${FUSIONAUTH_MLFLOW_CLIENT_ID}}"
RAY_APP_ID="${RAY_APP_ID:-${FUSIONAUTH_RAY_CLIENT_ID}}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=== FusionAuth Google Identity Provider Setup ===${NC}"
echo ""

# Validate required variables
if [[ -z "$FUSIONAUTH_API_KEY" ]]; then
    echo -e "${RED}ERROR: FUSIONAUTH_API_KEY not set in .env${NC}"
    exit 1
fi

# Support both GOOGLE_OAUTH_* and GOOGLE_* variable names
GOOGLE_CLIENT_ID="${GOOGLE_OAUTH_CLIENT_ID:-$GOOGLE_CLIENT_ID}"
GOOGLE_CLIENT_SECRET="${GOOGLE_OAUTH_CLIENT_SECRET:-$GOOGLE_CLIENT_SECRET}"

if [[ -z "$GOOGLE_CLIENT_ID" ]]; then
    echo -e "${RED}ERROR: GOOGLE_CLIENT_ID not set in .env${NC}"
    echo ""
    echo -e "${YELLOW}To get Google OAuth credentials:${NC}"
    echo "1. Go to https://console.cloud.google.com/apis/credentials"
    echo "2. Create a new 'OAuth 2.0 Client ID' (Web application)"
    echo "3. Add authorized redirect URI:"
    echo "   - https://${PUBLIC_DOMAIN}/oauth2/callback"
    echo "   - http://localhost:9011/oauth2/callback (for local testing)"
    echo "4. Copy Client ID and Client Secret to your .env file:"
    echo "   GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com"
    echo "   GOOGLE_CLIENT_SECRET=your-client-secret"
    exit 1
fi

if [[ -z "$GOOGLE_CLIENT_SECRET" ]]; then
    echo -e "${RED}ERROR: GOOGLE_CLIENT_SECRET not set in .env${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Found Google credentials${NC}"
echo "  Client ID: ${GOOGLE_CLIENT_ID:0:30}..."

# Check FusionAuth connectivity
echo ""
echo -e "${BLUE}Checking FusionAuth connectivity...${NC}"
if ! curl -sf "${FUSIONAUTH_URL}/api/status" > /dev/null 2>&1; then
    echo -e "${RED}ERROR: Cannot connect to FusionAuth at ${FUSIONAUTH_URL}${NC}"
    exit 1
fi
echo -e "${GREEN}✓ FusionAuth is accessible${NC}"

# Check if Google IDP already exists
echo ""
echo -e "${BLUE}Checking for existing Google Identity Provider...${NC}"
EXISTING_IDP=$(curl -sf -H "Authorization: ${FUSIONAUTH_API_KEY}" \
    "${FUSIONAUTH_URL}/api/identity-provider/${GOOGLE_IDP_ID}" 2>/dev/null || echo "")

if [[ -n "$EXISTING_IDP" && "$EXISTING_IDP" != *"error"* ]]; then
    echo -e "${YELLOW}⚠ Google Identity Provider already exists${NC}"
    echo ""
    read -p "Do you want to update it? (y/N): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi
    HTTP_METHOD="PUT"
else
    HTTP_METHOD="POST"
fi

# Create/Update Google Identity Provider
echo ""
echo -e "${BLUE}${HTTP_METHOD}ing Google Identity Provider...${NC}"

RESPONSE=$(curl -sf -X "${HTTP_METHOD}" \
    -H "Authorization: ${FUSIONAUTH_API_KEY}" \
    -H "Content-Type: application/json" \
    "${FUSIONAUTH_URL}/api/identity-provider/${GOOGLE_IDP_ID}" \
    -d '{
        "identityProvider": {
            "type": "Google",
            "name": "Google",
            "enabled": true,
            "client_id": "'"${GOOGLE_CLIENT_ID}"'",
            "client_secret": "'"${GOOGLE_CLIENT_SECRET}"'",
            "buttonText": "Sign in with Google",
            "scope": "openid email profile",
            "linkingStrategy": "LinkByEmail",
            "applicationConfiguration": {
                "'"${OAUTH2_PROXY_APP_ID}"'": {
                    "enabled": true,
                    "createRegistration": true
                },
                "'"${MLFLOW_APP_ID}"'": {
                    "enabled": true,
                    "createRegistration": false
                },
                "'"${RAY_APP_ID}"'": {
                    "enabled": true,
                    "createRegistration": false
                }
            }
        }
    }' 2>&1)

if [[ $? -eq 0 ]]; then
    echo -e "${GREEN}✓ Google Identity Provider configured successfully!${NC}"
    echo ""
    echo -e "${BLUE}Configuration Summary:${NC}"
    echo "  - OAuth2-Proxy: Auto-registration ENABLED (instant access to dashboards)"
    echo "  - MLflow: Auto-registration DISABLED (admin must grant access)"
    echo "  - Ray Compute: Auto-registration DISABLED (admin must grant access)"
    echo ""
    echo -e "${YELLOW}Next Steps:${NC}"
    echo "1. Verify Google Console has these redirect URIs:"
    echo "   - https://${PUBLIC_DOMAIN}/oauth2/callback"
    echo "   - http://localhost:9011/oauth2/callback"
    echo ""
    echo "2. Test by visiting: https://${PUBLIC_DOMAIN}/"
    echo "   You should see 'Sign in with Google' button"
    echo ""
    echo "3. To grant users access to MLflow/Ray after Google sign-in:"
    echo "   - Go to FusionAuth Admin: http://localhost:9011/admin"
    echo "   - Find user under 'Users'"
    echo "   - Click 'Add Registration' and select the application"
else
    echo -e "${RED}ERROR: Failed to configure Google Identity Provider${NC}"
    echo "Response: $RESPONSE"
    exit 1
fi
