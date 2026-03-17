#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# gepa_trigger.sh — Manually fire a GEPA skill-evolution cycle
# ─────────────────────────────────────────────────────────────────────────────
# Usage:
#   ./scripts/gepa_trigger.sh                 # threshold-gated (default)
#   ./scripts/gepa_trigger.sh --force         # bypass PATTERN_THRESHOLD
#
# Environment (override via export or .env):
#   FUSIONAUTH_URL          FusionAuth base URL  (default: http://localhost:9011)
#   FUSIONAUTH_PROXY_CLIENT_ID   OAuth2 client ID
#   FA_USERNAME             FusionAuth user email with elevated-developer role
#   FA_PASSWORD             Matching password
#   GATEWAY_URL             Platform gateway     (default: http://localhost)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

FUSIONAUTH_URL="${FUSIONAUTH_URL:-http://localhost:9011}"
CLIENT_ID="${FUSIONAUTH_PROXY_CLIENT_ID:?Set FUSIONAUTH_PROXY_CLIENT_ID in .env}"
FA_USERNAME="${FA_USERNAME:-admin@shml.local}"
FA_PASSWORD="${FA_PASSWORD:-}"
GATEWAY_URL="${GATEWAY_URL:-http://localhost}"
FORCE="${1:-}"

# ── Resolve force flag ────────────────────────────────────────────────────────
FORCE_PARAM=""
[[ "${FORCE}" == "--force" ]] && FORCE_PARAM="?force=true"

echo "=== GEPA Manual Trigger ==="
echo "  Gateway:  ${GATEWAY_URL}"
echo "  Force:    ${FORCE_PARAM:-false}"
echo ""

# ── Obtain FusionAuth bearer token ────────────────────────────────────────────
if [[ -z "${FA_PASSWORD}" ]]; then
  echo "ERROR: FA_PASSWORD is not set. Export it or add to .env:" >&2
  echo "  export FA_USERNAME=admin@shml.local" >&2
  echo "  export FA_PASSWORD=<your-password>" >&2
  exit 1
fi

echo "1. Obtaining bearer token from FusionAuth..."
TOKEN_RESP=$(curl -s -X POST "${FUSIONAUTH_URL}/oauth2/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password" \
  -d "client_id=${CLIENT_ID}" \
  -d "username=${FA_USERNAME}" \
  -d "password=${FA_PASSWORD}")

ACCESS_TOKEN=$(echo "${TOKEN_RESP}" | jq -r '.access_token // empty')
if [[ -z "${ACCESS_TOKEN}" ]]; then
  echo "ERROR: Could not obtain token. Response:" >&2
  echo "${TOKEN_RESP}" >&2
  exit 1
fi
echo "   Token acquired (${#ACCESS_TOKEN} chars)."

# ── Trigger GEPA ──────────────────────────────────────────────────────────────
echo ""
echo "2. Triggering GEPA evolution cycle..."
EVOLVE_RESP=$(curl -s -w "\n%{http_code}" -X POST \
  "${GATEWAY_URL}/api/agent/admin/skills/evolve${FORCE_PARAM}" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json")

HTTP_BODY=$(echo "${EVOLVE_RESP}" | head -n -1)
HTTP_CODE=$(echo "${EVOLVE_RESP}" | tail -n 1)

echo "   HTTP ${HTTP_CODE}"
echo "   Response: ${HTTP_BODY}"

if [[ "${HTTP_CODE}" == "200" ]]; then
  echo ""
  echo "✓ Evolution cycle accepted. Monitor logs:"
  echo "  docker logs -f shml-agent-service | grep -i 'gepa\|skill\|evolve'"
elif [[ "${HTTP_CODE}" == "422" ]]; then
  echo ""
  echo "  Hint: Too few lessons accumulated. Use --force to bypass, or wait for"
  echo "  the nightly scheduler to trigger automatically."
else
  echo ""
  echo "✗ Unexpected response. Check agent-service logs:" >&2
  echo "  docker logs --tail 50 shml-agent-service" >&2
  exit 1
fi

# ── Verify scheduler status ───────────────────────────────────────────────────
echo ""
echo "3. Verifying scheduler status..."
SCHED_RESP=$(curl -s "${GATEWAY_URL}/api/agent/admin/scheduler" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}")
echo "${SCHED_RESP}" | jq '.' 2>/dev/null || echo "${SCHED_RESP}"

echo ""
echo "Done."
