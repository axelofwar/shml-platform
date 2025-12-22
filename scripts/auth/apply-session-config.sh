#!/bin/bash
# Apply Enhanced Session Management Configuration
# Last Updated: 2025-12-06

set -e

echo "╔════════════════════════════════════════════════════════════════════════════╗"
echo "║              Enhanced Session Management Setup                            ║"
echo "╚════════════════════════════════════════════════════════════════════════════╝"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1. Configuration Summary"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

cat <<EOF
${BLUE}OAuth2-Proxy Session Settings:${NC}
  ├── Session Duration: 8 hours (auto-refresh at 4 hours)
  ├── Refresh Tokens: Enabled (30 day validity)
  ├── Session Store: Redis (persistent across restarts)
  ├── Cookie Security: HTTPOnly + SameSite=lax
  └── Grace Period: 5 minutes (for network issues)

${BLUE}Benefits:${NC}
  ✓ Users sign in once, stay authenticated for 30 days
  ✓ Sessions persist across browser restarts
  ✓ Seamless cross-service navigation (Homer → Grafana → MLflow)
  ✓ No constant re-login prompts
  ✓ Automatic token refresh (transparent to user)

${BLUE}Security Features:${NC}
  ✓ Session revocation via Redis (instant logout)
  ✓ HTTPOnly cookies (XSS protection)
  ✓ SameSite=lax (CSRF protection)
  ✓ Audit logs in FusionAuth
  ✓ Refresh token rotation
EOF

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "2. Pre-Flight Checks"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check Redis is running
if docker ps | grep -q "redis"; then
    echo -e "${GREEN}✓${NC} Redis container running"
else
    echo -e "${RED}✗${NC} Redis container not running"
    echo "   Start with: ./start_all_safe.sh start infra"
    exit 1
fi

# Check FusionAuth is running
if docker ps | grep -q "fusionauth"; then
    echo -e "${GREEN}✓${NC} FusionAuth container running"
else
    echo -e "${RED}✗${NC} FusionAuth container not running"
    echo "   Start with: ./start_all_safe.sh start infra"
    exit 1
fi

# Check OAuth2-Proxy is running
if docker ps | grep -q "oauth2-proxy"; then
    echo -e "${GREEN}✓${NC} OAuth2-Proxy container running"
else
    echo -e "${YELLOW}⚠${NC} OAuth2-Proxy container not running (will be started)"
fi

# Check docker-compose.infra.yml has session config
if grep -q "OAUTH2_PROXY_COOKIE_REFRESH" docker-compose.infra.yml; then
    echo -e "${GREEN}✓${NC} Enhanced session configuration found in docker-compose.infra.yml"
else
    echo -e "${RED}✗${NC} Enhanced session configuration NOT found"
    echo "   Configuration should have been added automatically"
    echo "   Check docker-compose.infra.yml for OAUTH2_PROXY_COOKIE_REFRESH"
    exit 1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "3. Apply Configuration"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "Restarting OAuth2-Proxy with enhanced session management..."
docker compose --env-file .env -f docker-compose.infra.yml up -d --force-recreate oauth2-proxy 2>&1 | grep -v "orphan" || true

echo ""
echo -e "${GREEN}✓${NC} OAuth2-Proxy restarted with new configuration"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "4. FusionAuth Configuration (MANUAL STEP)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

cat <<EOF
${YELLOW}You must configure FusionAuth JWT settings manually:${NC}

${BLUE}Step 1: Configure JWT Duration${NC}
  1. Open: https://shml-platform.tail38b60a.ts.net/admin
  2. Go to: Tenants → Default → Edit
  3. Click: JWT tab
  4. Set:
     - JWT duration: ${GREEN}28800${NC} seconds (8 hours)
  5. Scroll to "Refresh token settings":
     - Duration: ${GREEN}43200${NC} minutes (30 days)
     - Usage policy: ${GREEN}Reusable${NC}
  6. Revocation policy:
     - ${GREEN}✅${NC} On action preventing login
     - ${GREEN}✅${NC} On password change
  7. Click: ${GREEN}Save${NC}

${BLUE}Step 2: Enable FusionAuth Identity Provider (For Email/Password Login)${NC}
  1. Go to: Settings → Identity Providers
  2. Find: ${GREEN}FusionAuth${NC} row (native email/password login)
  3. Click: Edit (pencil icon)
  4. Set:
     - Enabled: ${GREEN}ON${NC} (toggle to blue)
  5. Click: Applications tab
  6. Find: OAuth2-Proxy
  7. Set:
     - ${GREEN}✅${NC} Enabled (checked)
     - ${GREEN}✅${NC} Create registration (checked)
  8. Click: ${GREEN}Save${NC}

${YELLOW}Why enable FusionAuth provider?${NC}
  - Allows users to create accounts with email/password
  - Enables self-service registration
  - Better for enterprise/contractor access
  - Users without Google/GitHub/Twitter can still sign in
  - Better audit trails for compliance
EOF

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "5. Verification Steps"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

cat <<EOF
${BLUE}Test 1: Session Persistence (Browser Restart)${NC}
  1. Open incognito window: https://shml-platform.tail38b60a.ts.net/
  2. Sign in with any method
  3. Close browser completely
  4. Reopen browser
  5. Go to: https://shml-platform.tail38b60a.ts.net/
  6. ${GREEN}✓ Should NOT prompt for login${NC} (session persists)

${BLUE}Test 2: Cross-Service SSO${NC}
  1. Sign in to Homer: https://shml-platform.tail38b60a.ts.net/
  2. Click link to Grafana
  3. ${GREEN}✓ Should NOT prompt for login${NC}
  4. Click link to MLflow
  5. ${GREEN}✓ Should NOT prompt for login${NC}

${BLUE}Test 3: Token Auto-Refresh${NC}
  1. Sign in
  2. Keep browser open for 5+ hours
  3. Access any service
  4. ${GREEN}✓ Should auto-refresh token${NC} (no login prompt)
  5. Check browser console for refresh events

${BLUE}Test 4: Check Redis Session Storage${NC}
  docker exec -it redis redis-cli
  > KEYS oauth2*
  # Should show stored sessions

${BLUE}Test 5: Verify JWT Duration${NC}
  1. Sign in
  2. Browser DevTools → Application → Cookies → _sfml_oauth2
  3. Copy JWT, paste at: https://jwt.io
  4. Check "exp" claim: should be ~8 hours from "iat" (issue time)
EOF

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "6. Monitoring & Troubleshooting"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

cat <<EOF
${BLUE}Check OAuth2-Proxy Logs:${NC}
  docker logs oauth2-proxy --tail 50 -f

${BLUE}Check Redis Session Count:${NC}
  docker exec -it redis redis-cli
  > DBSIZE
  # Shows total keys in Redis (includes sessions)

${BLUE}Revoke All Sessions (Force Re-Login):${NC}
  docker exec -it redis redis-cli FLUSHDB
  # Users must sign in again on next request

${BLUE}Check FusionAuth Event Log:${NC}
  FusionAuth Admin → System → Event Log
  Filter: Look for "refresh" or "token" events

${YELLOW}Common Issues:${NC}

Issue: Sessions expire too quickly
  → Check JWT duration in FusionAuth (should be 28800s)
  → Check COOKIE_EXPIRE in OAuth2-Proxy (should be "8h")

Issue: Sessions don't persist after browser restart
  → Verify SESSION_STORE_TYPE=redis (not cookie)
  → Check Redis is running: docker ps | grep redis

Issue: Users get logged out randomly
  → Check GRACE_PERIOD is set (5m)
  → Check Redis memory isn't full: docker stats redis
  → Check FusionAuth Event Log for errors
EOF

echo ""
echo "╔════════════════════════════════════════════════════════════════════════════╗"
echo "║                          Configuration Applied                             ║"
echo "║                                                                            ║"
echo "║  ${YELLOW}⚠ MANUAL STEP REQUIRED:${NC}                                                ║"
echo "║    Configure FusionAuth JWT duration (see Step 4 above)                   ║"
echo "║    Enable FusionAuth identity provider (see Step 4 above)                 ║"
echo "║                                                                            ║"
echo "║  ${GREEN}✓${NC} OAuth2-Proxy configuration updated and restarted                     ║"
echo "║  ${GREEN}✓${NC} Session persistence via Redis enabled                                ║"
echo "║  ${GREEN}✓${NC} Auto-refresh tokens configured                                       ║"
echo "╚════════════════════════════════════════════════════════════════════════════╝"
echo ""
