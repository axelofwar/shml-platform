#!/bin/bash
# Verify Identity Provider Configuration
# Checks that GitHub, Google, and Twitter are properly configured for OAuth2-Proxy

set -e

echo "╔════════════════════════════════════════════════════════════════════════════╗"
echo "║             Identity Provider Configuration Verification                  ║"
echo "╚════════════════════════════════════════════════════════════════════════════╝"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1. Environment Variables Check"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check .env file exists
if [ ! -f ".env" ]; then
    echo -e "${RED}✗${NC} .env file not found!"
    exit 1
fi

# Load environment
source .env 2>/dev/null || true

# Check Google credentials
if [ -n "$GOOGLE_OAUTH_CLIENT_ID" ] && [ -n "$GOOGLE_OAUTH_CLIENT_SECRET" ]; then
    echo -e "${GREEN}✓${NC} Google OAuth credentials configured"
    echo "   Client ID: ${GOOGLE_OAUTH_CLIENT_ID:0:20}..."
else
    echo -e "${RED}✗${NC} Google OAuth credentials missing"
fi

# Check GitHub credentials
if [ -n "$GITHUB_OAUTH_CLIENT_ID" ] && [ -n "$GITHUB_OAUTH_CLIENT_SECRET" ]; then
    echo -e "${GREEN}✓${NC} GitHub OAuth credentials configured"
    echo "   Client ID: ${GITHUB_OAUTH_CLIENT_ID}"
else
    echo -e "${YELLOW}⚠${NC} GitHub OAuth credentials missing"
fi

# Check Twitter credentials
if [ -n "$TWITTER_OAUTH_CLIENT_ID" ] && [ -n "$TWITTER_OAUTH_CLIENT_SECRET" ]; then
    echo -e "${GREEN}✓${NC} Twitter OAuth credentials configured"
    echo "   Client ID: ${TWITTER_OAUTH_CLIENT_ID:0:20}..."
else
    echo -e "${YELLOW}⚠${NC} Twitter OAuth credentials missing"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "2. FusionAuth Identity Providers Check"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check FusionAuth is running
if ! docker ps | grep -q "fusionauth"; then
    echo -e "${RED}✗${NC} FusionAuth container not running"
    echo "   Start with: ./start_all_safe.sh start infra"
    exit 1
fi

echo -e "${GREEN}✓${NC} FusionAuth container running"
echo ""

echo -e "${BLUE}Manual Verification Required:${NC}"
echo ""
echo "1. Open FusionAuth Admin:"
echo "   https://shml-platform.tail38b60a.ts.net/admin"
echo ""
echo "2. Go to: Settings → Identity Providers"
echo ""
echo "3. For EACH provider (Google, GitHub, Twitter), verify:"
echo "   a) Provider is ${GREEN}Enabled${NC} (green checkmark in 'Enabled' column)"
echo "   b) Click ${BLUE}Edit${NC} (pencil icon)"
echo "   c) Scroll to ${BLUE}'Applications'${NC} section"
echo "   d) Find ${GREEN}'OAuth2-Proxy'${NC} application"
echo "   e) Verify these settings:"
echo "      - ${GREEN}✓${NC} Enabled checkbox is checked"
echo "      - ${GREEN}✓${NC} 'Create registration' is checked"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "3. Expected Configuration Summary"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

cat <<EOF
┌─────────────────────────────────────────────────────────────────────────┐
│ Identity Provider: Google                                               │
├─────────────────────────────────────────────────────────────────────────┤
│ Status: Enabled                                                         │
│ OAuth2-Proxy App:                                                       │
│   ✓ Enabled: Yes                                                        │
│   ✓ Create registration: Yes (assigns default 'viewer' role)           │
│   ✓ Linking strategy: LinkByEmail (merges accounts with same email)    │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│ Identity Provider: GitHub                                               │
├─────────────────────────────────────────────────────────────────────────┤
│ Status: Enabled                                                         │
│ OAuth2-Proxy App:                                                       │
│   ✓ Enabled: Yes                                                        │
│   ✓ Create registration: Yes (assigns default 'viewer' role)           │
│   ✓ Linking strategy: LinkByEmail (merges accounts with same email)    │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│ Identity Provider: Twitter                                              │
├─────────────────────────────────────────────────────────────────────────┤
│ Status: Enabled                                                         │
│ OAuth2-Proxy App:                                                       │
│   ✓ Enabled: Yes                                                        │
│   ✓ Create registration: Yes (assigns default 'viewer' role)           │
│   ✓ Linking strategy: LinkByEmail (merges accounts with same email)    │
└─────────────────────────────────────────────────────────────────────────┘
EOF

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "4. Testing Each Authentication Method"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

cat <<EOF
Test each sign-in method to verify JWT lambda is working:

${BLUE}Test 1: Google Sign-In${NC}
  1. Open incognito window: https://shml-platform.tail38b60a.ts.net/
  2. Click "Sign in with Google"
  3. Should reach Homer dashboard without redirect loop ✓

${BLUE}Test 2: GitHub Sign-In${NC}
  1. Open new incognito window: https://shml-platform.tail38b60a.ts.net/
  2. Click "Sign in with GitHub"
  3. Should reach Homer dashboard without redirect loop ✓

${BLUE}Test 3: Twitter Sign-In${NC}
  1. Open new incognito window: https://shml-platform.tail38b60a.ts.net/
  2. Click "Sign in with Twitter"
  3. Should reach Homer dashboard without redirect loop ✓

${BLUE}Test 4: Email/Password Registration${NC}
  1. Open new incognito window: https://shml-platform.tail38b60a.ts.net/
  2. Click "Create account" (if available)
  3. Register with email/password
  4. Should reach Homer dashboard with 'viewer' role ✓

${BLUE}Verify JWT Contains Roles:${NC}
  After signing in with ANY method:
  1. Browser DevTools (F12) → Application → Cookies
  2. Find cookie: _sfml_oauth2
  3. Copy JWT value
  4. Paste at: https://jwt.io
  5. Check payload contains:
     {
       "email": "user@example.com",
       "roles": ["viewer"],  ${GREEN}← Should exist for ALL methods${NC}
       ...
     }
EOF

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "5. Troubleshooting"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

cat <<EOF
${YELLOW}If sign-in fails for specific provider:${NC}

1. Check FusionAuth Event Log:
   FusionAuth Admin → System → Event Log
   Look for errors related to that provider

2. Verify OAuth app configuration:
   - Google: https://console.cloud.google.com/apis/credentials
   - GitHub: https://github.com/settings/developers
   - Twitter: https://developer.twitter.com/en/portal/dashboard

3. Check redirect URLs are correct:
   Must include: https://shml-platform.tail38b60a.ts.net/auth/callback

4. Verify 'createRegistration' is enabled:
   If disabled, user won't get OAuth2-Proxy registration
   Even if they authenticate, they can't access platform

${YELLOW}If JWT doesn't contain roles:${NC}

1. Verify JWT lambda is enabled:
   FusionAuth Admin → Applications → OAuth2-Proxy → Edit → JWT tab
   "Enabled" toggle should be ON (blue/green)
   "Id token populate lambda" should show: JWT Populate - Add Roles

2. Check lambda execution in Event Log:
   Should see: "Added roles to JWT for user..."

3. Ensure user has registration with roles:
   FusionAuth Admin → Users → [user] → Registrations → OAuth2-Proxy
   Should show "viewer" role checked
EOF

echo ""
echo "╔════════════════════════════════════════════════════════════════════════════╗"
echo "║                          Verification Complete                             ║"
echo "║                                                                            ║"
echo "║  Next: Manually verify identity providers in FusionAuth Admin UI          ║"
echo "║        Test each sign-in method in incognito mode                         ║"
echo "╚════════════════════════════════════════════════════════════════════════════╝"
echo ""
