#!/bin/bash
# FusionAuth JWT Lambda Setup - Quick Reference
# Last Updated: 2025-12-06
#
# This script provides copy-paste commands to verify JWT lambda configuration.
# It does NOT automatically configure FusionAuth (must be done via admin UI).

set -e

echo "╔════════════════════════════════════════════════════════════════════════════╗"
echo "║                   FusionAuth JWT Lambda Setup Guide                       ║"
echo "╚════════════════════════════════════════════════════════════════════════════╝"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${YELLOW}PROBLEM:${NC} Users have 'viewer' role assigned but keep getting redirected to sign-in page"
echo -e "${YELLOW}CAUSE:${NC} FusionAuth not including 'roles' claim in JWT tokens"
echo -e "${GREEN}SOLUTION:${NC} Configure JWT Populate Lambda in FusionAuth"
echo ""

# Check if lambda files exist
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1. Verify Lambda Files"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ -f "fusionauth/lambdas/jwt-populate-roles.js" ]; then
    echo -e "${GREEN}✓${NC} JWT Populate Lambda exists: fusionauth/lambdas/jwt-populate-roles.js"
else
    echo -e "${RED}✗${NC} JWT Populate Lambda NOT FOUND"
    exit 1
fi

if [ -f "fusionauth/lambdas/google-registration-default-role.js" ]; then
    echo -e "${GREEN}✓${NC} Google Reconcile Lambda exists (optional)"
else
    echo -e "${YELLOW}⚠${NC} Google Reconcile Lambda not found (optional)"
fi

if [ -f "fusionauth/lambdas/README.md" ]; then
    echo -e "${GREEN}✓${NC} Lambda documentation exists"
fi

echo ""

# Display lambda code
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "2. JWT Populate Lambda Code (Copy-Paste into FusionAuth)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo -e "${BLUE}File:${NC} fusionauth/lambdas/jwt-populate-roles.js"
echo ""
cat fusionauth/lambdas/jwt-populate-roles.js
echo ""

# Configuration steps
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "3. Configuration Steps (MANUAL - Do in FusionAuth Admin UI)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo -e "${YELLOW}Step 1:${NC} Open FusionAuth Admin Panel"
echo "   URL: https://${PUBLIC_DOMAIN}/admin"
echo ""
echo -e "${YELLOW}Step 2:${NC} Create JWT Populate Lambda"
echo "   1. Go to: Settings → Lambdas"
echo "   2. Click: ➕ Add Lambda (top right)"
echo "   3. Configure:"
echo "      - Name: ${GREEN}JWT Populate - Include Roles Claim${NC}"
echo "      - Type: ${GREEN}JWT populate${NC}"
echo "      - Enabled: ${GREEN}✓ (checked)${NC}"
echo "      - Debug: ${GREEN}✓ (checked)${NC}"
echo "   4. Copy-paste code from above (or from jwt-populate-roles.js)"
echo "   5. Click: ${GREEN}Save${NC}"
echo ""
echo -e "${YELLOW}Step 3:${NC} Attach Lambda to Tenant"
echo "   1. Go to: Tenants → ML Platform → ${BLUE}Edit (pencil icon)${NC}"
echo "   2. Scroll down to: ${BLUE}JWT section${NC}"
echo "   3. Find: ${BLUE}Id Token populate lambda${NC} dropdown"
echo "   4. Select: ${GREEN}JWT Populate - Include Roles Claim${NC}"
echo "   5. Click: ${GREEN}Save (💾 icon at top right)${NC}"
echo ""
echo -e "${YELLOW}Step 4:${NC} Verify Lambda Execution"
echo "   1. Go to: System → Event Log"
echo "   2. Have a user sign in"
echo "   3. Look for: ${GREEN}\"Added roles to JWT for user...\"${NC}"
echo "   4. If not found, lambda not executing (check attachment)"
echo ""
echo -e "${YELLOW}Step 5:${NC} Force Users to Get New Tokens"
echo "   Option A: Users clear cookies for ${PUBLIC_DOMAIN}"
echo "   Option B: Restart OAuth2-Proxy (invalidates all sessions):"
echo "            ${BLUE}docker restart oauth2-proxy${NC}"
echo ""

# Verification commands
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "4. Verification Commands"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo -e "${BLUE}Check OAuth2-Proxy logs for roles:${NC}"
echo "   docker logs oauth2-proxy --tail 50"
echo ""
echo -e "${BLUE}Verify user has roles in FusionAuth:${NC}"
echo "   Go to: FusionAuth Admin → Users → [user] → Registrations"
echo "   OAuth2-Proxy app should show 'viewer' role checked"
echo ""
echo -e "${BLUE}Decode JWT to verify roles claim:${NC}"
echo "   1. Sign in to platform"
echo "   2. Browser DevTools → Application → Cookies → _sfml_oauth2"
echo "   3. Copy JWT value"
echo "   4. Paste at: https://jwt.io"
echo "   5. Look for: ${GREEN}\"roles\": [\"viewer\"]${NC} in payload"
echo ""
echo -e "${BLUE}Test role-auth middleware:${NC}"
echo "   curl -H \"X-Auth-Request-Groups: viewer\" http://localhost:8080/auth/developer"
echo "   Expected: 403 Forbidden (viewer doesn't have developer role)"
echo ""
echo "   curl -H \"X-Auth-Request-Groups: viewer,developer\" http://localhost:8080/auth/developer"
echo "   Expected: 200 OK \"Authorized\""
echo ""

# Affected users
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "5. Current Affected Users"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo -e "${YELLOW}Users experiencing redirect loop (but have 'viewer' role):${NC}"
echo "   - bnccyberspace@msn.com (William Caton)"
echo "   - soundsbystoney@gmail.com (Kay Rodgers)"
echo ""
echo -e "${GREEN}After lambda configuration, both users should be able to access:${NC}"
echo "   - Homer Dashboard (https://${PUBLIC_DOMAIN}/)"
echo "   - Grafana (https://${PUBLIC_DOMAIN}/grafana)"
echo ""

# Documentation
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "6. Additional Resources"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "   Lambda Setup Guide:    fusionauth/lambdas/README.md"
echo "   Troubleshooting:       docs/internal/TROUBLESHOOTING.md"
echo "   OAuth2-Proxy Config:   deploy/compose/docker-compose.infra.yml (lines 260-400)"
echo "   FusionAuth Kickstart:  fusionauth/kickstart/kickstart.json"
echo ""
echo "   FusionAuth Lambda Docs: https://fusionauth.io/docs/v1/tech/lambdas/"
echo "   JWT Decoder:            https://jwt.io"
echo ""

echo "╔════════════════════════════════════════════════════════════════════════════╗"
echo "║                              Setup Complete                                ║"
echo "║                                                                            ║"
echo "║  ⚠️  REMEMBER: Lambda must be configured via FusionAuth Admin UI          ║"
echo "║              Users must clear cookies or restart oauth2-proxy             ║"
echo "╚════════════════════════════════════════════════════════════════════════════╝"
echo ""
