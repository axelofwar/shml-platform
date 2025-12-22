#!/bin/bash
# Debug Authentication Flow
# Run this script in one terminal, then attempt to sign in, then Ctrl+C to stop
# This will capture all logs related to authentication

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Authentication Flow Debugger"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Instructions:"
echo "1. This script is now monitoring all authentication traffic"
echo "2. Open your browser to: https://shml-platform.tail38b60a.ts.net/ray/ui"
echo "3. Click the 'Sign in with OpenID Connect' button"
echo "4. Complete the login flow (or watch where it fails)"
echo "5. Press Ctrl+C to stop monitoring"
echo ""
echo "Monitoring started at $(date)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Tail all relevant logs in parallel with clear labels
(docker logs -f oauth2-proxy 2>&1 | sed 's/^/[OAUTH2-PROXY] /') &
OAUTH_PID=$!

(docker logs -f fusionauth 2>&1 | grep -E "oauth|token|login|authorize|callback" -i | sed 's/^/[FUSIONAUTH] /') &
FUSION_PID=$!

(docker logs -f shml-traefik 2>&1 | grep -E "oauth|ray/ui|sign_in|callback" -i | sed 's/^/[TRAEFIK] /') &
TRAEFIK_PID=$!

(docker logs -f ray-compute-ui 2>&1 | sed 's/^/[RAY-UI] /') &
RAY_PID=$!

# Also tail Traefik access log if it exists
if [ -f ./logs/traefik/access.log ]; then
  (tail -f ./logs/traefik/access.log | sed 's/^/[TRAEFIK-ACCESS] /') &
  ACCESS_PID=$!
fi

# Wait for Ctrl+C
trap "echo ''; echo 'Stopping monitors...'; kill $OAUTH_PID $FUSION_PID $TRAEFIK_PID $RAY_PID $ACCESS_PID 2>/dev/null; exit 0" INT

echo "Monitoring... (Press Ctrl+C to stop)"
echo ""
wait
