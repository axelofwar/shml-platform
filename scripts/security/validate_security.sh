#!/usr/bin/env bash
# =============================================================================
# SHML Platform Security Validation Script
# =============================================================================
# Validates all security hardening changes from the security audit.
# Run AFTER deploying the updated compose files.
#
# Usage:
#   chmod +x scripts/security/validate_security.sh
#   ./scripts/security/validate_security.sh
#
# Requirements:
#   - Platform must be running (docker compose up)
#   - curl must be installed
#   - jq must be installed (for JSON parsing)
#   - docker CLI must be available
# =============================================================================

set -uo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Counters
PASS=0
FAIL=0
WARN=0
SKIP=0

# Platform URL
PLATFORM_URL="${PUBLIC_DOMAIN:-https://${PUBLIC_DOMAIN}}"
PLATFORM_PREFIX="${PLATFORM_PREFIX:-shml}"

pass() {
    echo -e "  ${GREEN}✓ PASS${NC}: $1"
    PASS=$((PASS + 1))
}

fail() {
    echo -e "  ${RED}✗ FAIL${NC}: $1"
    FAIL=$((FAIL + 1))
}

warn() {
    echo -e "  ${YELLOW}⚠ WARN${NC}: $1"
    WARN=$((WARN + 1))
}

skip() {
    echo -e "  ${CYAN}○ SKIP${NC}: $1"
    SKIP=$((SKIP + 1))
}

header() {
    echo ""
    echo -e "${CYAN}══════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}══════════════════════════════════════════════════════════════${NC}"
}

# =============================================================================
# Phase 1: Critical Security Fixes
# =============================================================================
header "PHASE 1: Critical Security Fixes"

echo ""
echo "--- 1.1 Docker Socket Removal ---"

# Check agent-service has no docker socket
if docker inspect "${PLATFORM_PREFIX}-agent-service" 2>/dev/null | grep -q '/var/run/docker.sock'; then
    fail "agent-service still has Docker socket mounted"
else
    pass "agent-service: Docker socket removed"
fi

# Check gpu-manager has no docker socket
if docker inspect "gpu-manager" 2>/dev/null | grep -q '/var/run/docker.sock'; then
    fail "gpu-manager still has Docker socket mounted"
else
    pass "gpu-manager: Docker socket removed"
fi

# Check nemotron-manager has no docker socket
if docker inspect "nemotron-manager" 2>/dev/null | grep -q '/var/run/docker.sock'; then
    fail "nemotron-manager still has Docker socket mounted"
else
    pass "nemotron-manager: Docker socket removed"
fi

# Check docker-proxy is running
if docker ps --format '{{.Names}}' | grep -q 'docker-proxy'; then
    pass "docker-proxy container is running"
else
    warn "docker-proxy container not found (deploy deploy/compose/docker-compose.docker-proxy.yml)"
fi

# Check docker-proxy only allows read operations
if docker inspect "${PLATFORM_PREFIX}-docker-proxy" 2>/dev/null | grep -q '"POST": "0"'; then
    pass "docker-proxy: POST operations blocked"
else
    skip "docker-proxy: Cannot verify POST blocking (container may not be running)"
fi

echo ""
echo "--- 1.2 DEV_MODE Disabled ---"

# Check DEV_MODE env var
DEV_MODE=$(docker inspect "${PLATFORM_PREFIX}-agent-service" 2>/dev/null | grep -o 'DEV_MODE=[^"]*' | head -1 || echo "")
if [[ "$DEV_MODE" == "DEV_MODE=false" ]]; then
    pass "agent-service: DEV_MODE=false"
elif [[ -z "$DEV_MODE" ]]; then
    fail "agent-service: DEV_MODE not set (defaults to true!)"
else
    fail "agent-service: DEV_MODE=$DEV_MODE (should be false)"
fi

echo ""
echo "--- 1.3 Previously Unprotected Routes ---"

# Test GPU Manager requires auth (should return 302 redirect or 401)
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${PLATFORM_URL}/api/gpu-manager/status" 2>/dev/null || echo "000")
if [[ "$HTTP_CODE" == "302" || "$HTTP_CODE" == "401" || "$HTTP_CODE" == "403" ]]; then
    pass "GPU Manager requires auth (HTTP $HTTP_CODE)"
elif [[ "$HTTP_CODE" == "200" ]]; then
    fail "GPU Manager still unprotected (HTTP 200)"
else
    warn "GPU Manager: unexpected HTTP $HTTP_CODE (may be down)"
fi

# Test SAM Audio requires auth
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${PLATFORM_URL}/api/audio/separate" 2>/dev/null || echo "000")
if [[ "$HTTP_CODE" == "302" || "$HTTP_CODE" == "401" || "$HTTP_CODE" == "403" ]]; then
    pass "SAM Audio requires auth (HTTP $HTTP_CODE)"
elif [[ "$HTTP_CODE" == "200" ]]; then
    fail "SAM Audio still unprotected (HTTP 200)"
else
    warn "SAM Audio: unexpected HTTP $HTTP_CODE (may be down)"
fi

# Test /cli requires auth
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${PLATFORM_URL}/cli/health" 2>/dev/null || echo "000")
if [[ "$HTTP_CODE" == "302" || "$HTTP_CODE" == "401" || "$HTTP_CODE" == "403" ]]; then
    pass "/cli route requires auth (HTTP $HTTP_CODE)"
elif [[ "$HTTP_CODE" == "200" ]]; then
    fail "/cli route still unprotected (HTTP 200)"
else
    warn "/cli route: unexpected HTTP $HTTP_CODE"
fi

# Test /v1/chat requires auth
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${PLATFORM_URL}/v1/chat/completions" 2>/dev/null || echo "000")
if [[ "$HTTP_CODE" == "302" || "$HTTP_CODE" == "401" || "$HTTP_CODE" == "403" ]]; then
    pass "/v1/chat route requires auth (HTTP $HTTP_CODE)"
elif [[ "$HTTP_CODE" == "200" ]]; then
    fail "/v1/chat route still unprotected (HTTP 200)"
else
    warn "/v1/chat route: unexpected HTTP $HTTP_CODE"
fi

# Test /ws-test requires auth
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${PLATFORM_URL}/ws-test" 2>/dev/null || echo "000")
if [[ "$HTTP_CODE" == "302" || "$HTTP_CODE" == "401" || "$HTTP_CODE" == "403" ]]; then
    pass "/ws-test route requires auth (HTTP $HTTP_CODE)"
elif [[ "$HTTP_CODE" == "200" ]]; then
    fail "/ws-test route still unprotected (HTTP 200)"
else
    warn "/ws-test route: unexpected HTTP $HTTP_CODE"
fi

echo ""
echo "--- 1.4 FusionAuth /admin Protection ---"

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${PLATFORM_URL}/admin" 2>/dev/null || echo "000")
if [[ "$HTTP_CODE" == "302" || "$HTTP_CODE" == "401" || "$HTTP_CODE" == "403" ]]; then
    pass "FusionAuth /admin requires auth (HTTP $HTTP_CODE)"
elif [[ "$HTTP_CODE" == "200" ]]; then
    fail "FusionAuth /admin still unprotected (HTTP 200)"
else
    warn "FusionAuth /admin: unexpected HTTP $HTTP_CODE"
fi

# =============================================================================
# Phase 2: Viewer Isolation
# =============================================================================
header "PHASE 2: Viewer Model Isolation"

echo ""
echo "--- 2.1 Security Module Exists ---"

if [[ -f "inference/agent-service/app/security.py" ]]; then
    pass "security.py module exists"
else
    fail "security.py module not found"
fi

echo ""
echo "--- 2.2 Role-Gated Skills (Static Checks) ---"

# Check that security.py defines viewer skill restrictions
if grep -q "VIEWER_SKILLS" inference/agent-service/app/security.py 2>/dev/null; then
    pass "VIEWER_SKILLS defined in security.py"
else
    fail "VIEWER_SKILLS not found in security.py"
fi

# Check viewer skills only has safe skills (grep the block between VIEWER_SKILLS and DEVELOPER_SKILLS)
VIEWER_BLOCK=$(sed -n '/^VIEWER_SKILLS/,/^$/p' inference/agent-service/app/security.py 2>/dev/null)
if echo "$VIEWER_BLOCK" | grep -q "ShellSkill"; then
    fail "ShellSkill is allowed for viewers (should be blocked)"
else
    pass "ShellSkill blocked for viewers"
fi

if echo "$VIEWER_BLOCK" | grep -q "SandboxSkill"; then
    fail "SandboxSkill is allowed for viewers (should be blocked)"
else
    pass "SandboxSkill blocked for viewers"
fi

echo ""
echo "--- 2.3 Blocked Patterns ---"

# Check that docker inspect is blocked
if grep -q "docker inspect" inference/agent-service/app/security.py 2>/dev/null; then
    pass "docker inspect is in BLOCKED_PATTERNS"
else
    fail "docker inspect NOT in BLOCKED_PATTERNS"
fi

# Check that /run/secrets is blocked
if grep -q "/run/secrets" inference/agent-service/app/security.py 2>/dev/null; then
    pass "/run/secrets is in BLOCKED_PATTERNS"
else
    fail "/run/secrets NOT in BLOCKED_PATTERNS"
fi

echo ""
echo "--- 2.4 Output Filtering ---"

if grep -q "filter_output" inference/agent-service/app/security.py 2>/dev/null; then
    pass "filter_output function exists"
else
    fail "filter_output function not found"
fi

if grep -q "SECRET_PATTERNS" inference/agent-service/app/security.py 2>/dev/null; then
    pass "SECRET_PATTERNS regex patterns defined"
else
    fail "SECRET_PATTERNS not found"
fi

echo ""
echo "--- 2.5 System Prompt Hardening ---"

if grep -q "NEVER reveal" inference/agent-service/app/security.py 2>/dev/null; then
    pass "Anti-extraction instructions in security.py"
else
    fail "Anti-extraction instructions missing from security.py"
fi

if grep -q "NEVER reveal" inference/chat-api/app/config.py 2>/dev/null; then
    pass "Anti-extraction instructions in chat-api system prompt"
else
    fail "Anti-extraction instructions missing from chat-api"
fi

echo ""
echo "--- 2.6 MCP Filesystem Disabled ---"

if grep -q "filesystem-DISABLED" mcp/mcp-config.json 2>/dev/null; then
    pass "MCP filesystem server disabled"
elif grep -q '"filesystem"' mcp/mcp-config.json 2>/dev/null; then
    fail "MCP filesystem server still enabled"
else
    pass "MCP filesystem server not present"
fi

# =============================================================================
# Phase 3: Infrastructure Hardening
# =============================================================================
header "PHASE 3: Infrastructure Hardening"

echo ""
echo "--- 3.1 Port Binding ---"

# Check FusionAuth port binding
FA_PORTS=$(docker inspect "${PLATFORM_PREFIX}-fusionauth" 2>/dev/null | grep -o '"HostPort": "[^"]*"' | head -1 || echo "")
FA_BIND=$(docker inspect "${PLATFORM_PREFIX}-fusionauth" 2>/dev/null | grep -o '"HostIp": "[^"]*"' | head -1 || echo "")
if echo "$FA_BIND" | grep -q "127.0.0.1"; then
    pass "FusionAuth port bound to 127.0.0.1"
elif echo "$FA_PORTS" | grep -q "9011"; then
    fail "FusionAuth port 9011 bound to 0.0.0.0 (should be 127.0.0.1)"
else
    skip "FusionAuth: could not verify port binding"
fi

# Check that nemotron has no direct port
NEMOTRON_PORTS=$(docker port qwopus-coding 2>/dev/null || echo "none")
if [[ "$NEMOTRON_PORTS" == "none" || -z "$NEMOTRON_PORTS" ]]; then
    pass "Nemotron: no direct port exposure"
else
    fail "Nemotron still has direct port: $NEMOTRON_PORTS"
fi

# Check that gpu-manager has no direct port
GPU_PORTS=$(docker port gpu-manager 2>/dev/null || echo "none")
if [[ "$GPU_PORTS" == "none" || -z "$GPU_PORTS" ]]; then
    pass "GPU Manager: no direct port exposure"
else
    fail "GPU Manager still has direct port: $GPU_PORTS"
fi

echo ""
echo "--- 3.2 Docker Proxy ---"

if [[ -f "deploy/compose/docker-compose.docker-proxy.yml" ]]; then
    pass "Docker proxy compose file exists"
else
    fail "deploy/compose/docker-compose.docker-proxy.yml not found"
fi

echo ""
echo "--- 3.3 Infisical Keys ---"

if grep -q '?ERROR:' deploy/compose/docker-compose.secrets.yml 2>/dev/null; then
    pass "Infisical defaults removed (now requires .env)"
else
    fail "Infisical may still have hardcoded default keys"
fi

echo ""
echo "--- 3.4 Network Segmentation Plan ---"

if [[ -f "deploy/compose/docker-compose.networks.yml" ]]; then
    pass "Network segmentation plan file exists"
else
    warn "deploy/compose/docker-compose.networks.yml not found"
fi

echo ""
echo "--- 3.5 Container Hardening Overlay ---"

if [[ -f "inference/docker-compose.hardening.yml" ]]; then
    pass "Container hardening overlay file exists"
else
    warn "inference/docker-compose.hardening.yml not found"
fi

# =============================================================================
# Phase 4: Identity Provider Fixes
# =============================================================================
header "PHASE 4: Identity Provider Fixes"

echo ""
echo "--- 4.1 Reconcile Lambdas ---"

if [[ -f "fusionauth/lambdas/github-registration-default-role.js" ]]; then
    pass "GitHub reconcile lambda created"
else
    fail "GitHub reconcile lambda missing"
fi

if [[ -f "fusionauth/lambdas/twitter-registration-default-role.js" ]]; then
    pass "Twitter reconcile lambda created"
else
    fail "Twitter reconcile lambda missing"
fi

# Check lambdas assign 'viewer' role
if grep -q "'viewer'" fusionauth/lambdas/github-registration-default-role.js 2>/dev/null; then
    pass "GitHub lambda assigns viewer role"
else
    fail "GitHub lambda does not assign viewer role"
fi

if grep -q "'viewer'" fusionauth/lambdas/twitter-registration-default-role.js 2>/dev/null; then
    pass "Twitter lambda assigns viewer role"
else
    fail "Twitter lambda does not assign viewer role"
fi

# =============================================================================
# Phase 5: FiftyOne Fix
# =============================================================================
header "PHASE 5: FiftyOne Fixes"

echo ""
echo "--- 5.1 Server Path Prefix ---"

if grep -q "FIFTYONE_SERVER_PATH_PREFIX" deploy/compose/docker-compose.infra.yml 2>/dev/null; then
    pass "FIFTYONE_SERVER_PATH_PREFIX set in compose"
else
    fail "FIFTYONE_SERVER_PATH_PREFIX missing from compose"
fi

# =============================================================================
# Summary
# =============================================================================
header "SECURITY VALIDATION SUMMARY"

TOTAL=$((PASS + FAIL + WARN + SKIP))
echo ""
echo -e "  ${GREEN}Passed:  $PASS${NC}"
echo -e "  ${RED}Failed:  $FAIL${NC}"
echo -e "  ${YELLOW}Warnings: $WARN${NC}"
echo -e "  ${CYAN}Skipped: $SKIP${NC}"
echo -e "  Total:   $TOTAL"
echo ""

if [[ $FAIL -eq 0 ]]; then
    echo -e "${GREEN}══════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  ALL CRITICAL CHECKS PASSED${NC}"
    echo -e "${GREEN}══════════════════════════════════════════════════════════════${NC}"
    exit 0
else
    echo -e "${RED}══════════════════════════════════════════════════════════════${NC}"
    echo -e "${RED}  $FAIL CRITICAL CHECK(S) FAILED - FIX BEFORE ENABLING VIEWER ACCESS${NC}"
    echo -e "${RED}══════════════════════════════════════════════════════════════${NC}"
    exit 1
fi
