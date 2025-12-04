#!/bin/bash
# =============================================================================
# TAILSCALE RECOVERY SCRIPT
# =============================================================================
# Use this script after a Tailscale reset (e.g., TPM lockout, re-authentication)
#
# What this script does:
# 1. Sets the hostname back to 'shml-platform'
# 2. Re-enables Tailscale Funnel
# 3. Updates .env with the new Tailscale IP
# 4. Validates FusionAuth OAuth configuration
# 5. Restarts affected services
#
# Usage: sudo ./scripts/recover-tailscale.sh
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo -e "${GREEN}=== SFML Platform Tailscale Recovery ===${NC}"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root: sudo $0${NC}"
    exit 1
fi

# Step 1: Check Tailscale status
echo -e "${YELLOW}Step 1: Checking Tailscale status...${NC}"
if ! tailscale status &>/dev/null; then
    echo -e "${RED}Tailscale is not running or not authenticated.${NC}"
    echo "Please run: sudo tailscale up"
    exit 1
fi

CURRENT_IP=$(tailscale ip -4)
CURRENT_HOSTNAME=$(tailscale status --json | jq -r '.Self.HostName')
echo "  Current IP: $CURRENT_IP"
echo "  Current Hostname: $CURRENT_HOSTNAME"

# Step 2: Set hostname to shml-platform
echo ""
echo -e "${YELLOW}Step 2: Setting hostname to 'shml-platform'...${NC}"
tailscale set --hostname=shml-platform
sleep 2
NEW_HOSTNAME=$(tailscale status --json | jq -r '.Self.HostName')
echo "  Hostname set to: $NEW_HOSTNAME"

# Step 3: Enable Tailscale Funnel
echo ""
echo -e "${YELLOW}Step 3: Enabling Tailscale Funnel...${NC}"
PUBLIC_DOMAIN=$(grep "^PUBLIC_DOMAIN=" "$PROJECT_DIR/.env" | cut -d'=' -f2)
PUBLIC_DOMAIN="${PUBLIC_DOMAIN:-shml-platform.tail38b60a.ts.net}"
tailscale funnel --set-path=/ --bg 80
echo "  Funnel enabled: https://$PUBLIC_DOMAIN → port 80"

# Step 4: Update .env file
echo ""
echo -e "${YELLOW}Step 4: Updating .env with new Tailscale IP...${NC}"
ENV_FILE="$PROJECT_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    OLD_IP=$(grep "^TAILSCALE_IP=" "$ENV_FILE" | cut -d'=' -f2)
    if [ "$OLD_IP" != "$CURRENT_IP" ]; then
        sed -i "s/^TAILSCALE_IP=.*/TAILSCALE_IP=$CURRENT_IP/" "$ENV_FILE"
        echo "  Updated TAILSCALE_IP: $OLD_IP → $CURRENT_IP"
    else
        echo "  TAILSCALE_IP already correct: $CURRENT_IP"
    fi
else
    echo -e "${RED}  .env file not found at $ENV_FILE${NC}"
fi

# Step 5: Update sub-project .env files
echo ""
echo -e "${YELLOW}Step 5: Updating sub-project .env files...${NC}"
for subenv in "$PROJECT_DIR/ray_compute/.env" "$PROJECT_DIR/mlflow-server/.env"; do
    if [ -f "$subenv" ]; then
        if grep -q "TAILSCALE_IP\|SERVER_TAILSCALE_IP" "$subenv"; then
            sed -i "s/TAILSCALE_IP=.*/TAILSCALE_IP=$CURRENT_IP/" "$subenv"
            sed -i "s/SERVER_TAILSCALE_IP=.*/SERVER_TAILSCALE_IP=$CURRENT_IP/" "$subenv"
            echo "  Updated: $subenv"
        fi
    fi
done

# Step 6: Verify FusionAuth OAuth configuration
echo ""
echo -e "${YELLOW}Step 6: Verifying FusionAuth OAuth configuration...${NC}"
FUSIONAUTH_API_KEY=$(grep "^FUSIONAUTH_API_KEY=" "$ENV_FILE" | cut -d'=' -f2)
# Get OAuth App ID from .env or use default
OAUTH_APP_ID=$(grep "^OAUTH2_PROXY_APP_ID=" "$ENV_FILE" | cut -d'=' -f2)
OAUTH_APP_ID="${OAUTH_APP_ID:-}"
PUBLIC_DOMAIN=$(grep "^PUBLIC_DOMAIN=" "$ENV_FILE" | cut -d'=' -f2)
PUBLIC_DOMAIN="${PUBLIC_DOMAIN:-shml-platform.tail38b60a.ts.net}"

if [ -n "$FUSIONAUTH_API_KEY" ] && [ -n "$OAUTH_APP_ID" ]; then
    # Check if FusionAuth is accessible
    if curl -s -o /dev/null -w "%{http_code}" "http://$CURRENT_IP:9011/api/status" | grep -q "200"; then
        echo "  FusionAuth is accessible"

        # Check OAuth redirect URIs
        REDIRECT_URIS=$(curl -s -H "Authorization: $FUSIONAUTH_API_KEY" \
            "http://$CURRENT_IP:9011/api/application/$OAUTH_APP_ID" | \
            jq -r '.application.oauthConfiguration.authorizedRedirectURLs[]' 2>/dev/null)

        if echo "$REDIRECT_URIS" | grep -q "$PUBLIC_DOMAIN"; then
            echo "  OAuth redirect URIs include $PUBLIC_DOMAIN ✓"
        else
            echo -e "${RED}  WARNING: OAuth redirect URIs may need updating in FusionAuth${NC}"
            echo "  Go to: http://$CURRENT_IP:9011/admin/application/edit/$OAUTH_APP_ID"
        fi
    else
        echo "  FusionAuth not accessible yet (may need container restart)"
    fi
else
    if [ -z "$OAUTH_APP_ID" ]; then
        echo "  OAUTH2_PROXY_APP_ID not set in .env - skipping OAuth verification"
    else
        echo "  FUSIONAUTH_API_KEY not found in .env - skipping OAuth verification"
    fi
fi

# Step 7: Restart services
echo ""
echo -e "${YELLOW}Step 7: Restarting Docker services...${NC}"
cd "$PROJECT_DIR"

# Restart key services that use Tailscale configuration
docker compose up -d oauth2-proxy traefik mlflow-server --force-recreate
echo "  Services restarted"

# Step 8: Verify services
echo ""
echo -e "${YELLOW}Step 8: Verifying services...${NC}"
sleep 10

# Test OIDC discovery
if curl -sk "https://$PUBLIC_DOMAIN/.well-known/openid-configuration" | jq -e '.issuer' &>/dev/null; then
    echo "  OIDC Discovery: ✓"
else
    echo -e "${RED}  OIDC Discovery: FAILED${NC}"
fi

# Test OAuth2 Proxy
if docker logs oauth2-proxy 2>&1 | tail -5 | grep -q "OAuthProxy configured"; then
    echo "  OAuth2 Proxy: ✓"
else
    echo -e "${RED}  OAuth2 Proxy: Check logs with 'docker logs oauth2-proxy'${NC}"
fi

# Test MLflow
MLFLOW_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "https://$PUBLIC_DOMAIN/mlflow/health" 2>/dev/null || echo "000")
if [ "$MLFLOW_STATUS" = "200" ]; then
    echo "  MLflow Health: ✓"
else
    echo "  MLflow Health: Returns $MLFLOW_STATUS (may require auth)"
fi

echo ""
echo -e "${GREEN}=== Recovery Complete ===${NC}"
echo ""
echo "Next steps:"
echo "1. Clear browser cookies for $PUBLIC_DOMAIN"
echo "2. Test login at https://$PUBLIC_DOMAIN/mlflow/"
echo "3. If login fails, check: docker logs oauth2-proxy"
echo ""
echo "Tailscale Configuration:"
echo "  IP: $CURRENT_IP"
echo "  Hostname: shml-platform"
echo "  Domain: $PUBLIC_DOMAIN"
echo "  Funnel: Enabled (HTTPS → port 80)"
