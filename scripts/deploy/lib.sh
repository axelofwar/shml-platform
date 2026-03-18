#!/usr/bin/env bash
# scripts/deploy/lib.sh — Core deploy library: env, logging, colors, timeouts, helpers
#
# Sourced by start_all_safe.sh and Taskfile tasks. Safe to source multiple times.
# Requires: SCRIPT_DIR set and cwd = $SCRIPT_DIR before sourcing.

# Guard against double-sourcing
[[ -n "${_SHML_LIB_LOADED:-}" ]] && return 0
_SHML_LIB_LOADED=1

# =============================================================================
# Environment Loading
# =============================================================================

load_shml_env() {
    local env_file=".env"
    local key
    local value

    [ -f "$env_file" ] || return 0

    while IFS='=' read -r key value; do
        case "$key" in
            SHML_REGISTRY_IMAGE_PREFIX|SHML_IMAGE_TAG|SHML_IMAGE_PULL_POLICY|SHML_LATEST_TAG|SHML_BUILD_TARGETS)
                export "$key=$value"
                ;;
        esac
    done < <(grep -E '^(SHML_REGISTRY_IMAGE_PREFIX|SHML_IMAGE_TAG|SHML_IMAGE_PULL_POLICY|SHML_LATEST_TAG|SHML_BUILD_TARGETS)=' "$env_file" || true)
}

load_shml_env

# =============================================================================
# Colors & Logging
# =============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info()    { echo -e "${CYAN}$1${NC}"; }
log_success() { echo -e "${GREEN}✓ $1${NC}"; }
log_warn()    { echo -e "${YELLOW}⚠ $1${NC}"; }
log_error()   { echo -e "${RED}✗ $1${NC}"; }

# =============================================================================
# Configurable Timeouts (seconds)
# =============================================================================

POSTGRES_TIMEOUT=${POSTGRES_TIMEOUT:-120}
TRAEFIK_TIMEOUT=${TRAEFIK_TIMEOUT:-60}
PROMETHEUS_TIMEOUT=${PROMETHEUS_TIMEOUT:-90}
GRAFANA_TIMEOUT=${GRAFANA_TIMEOUT:-90}
FUSIONAUTH_TIMEOUT=${FUSIONAUTH_TIMEOUT:-180}
OAUTH2_PROXY_TIMEOUT=${OAUTH2_PROXY_TIMEOUT:-120}
MLFLOW_TIMEOUT=${MLFLOW_TIMEOUT:-120}
RAY_TIMEOUT=${RAY_TIMEOUT:-120}
DEFAULT_TIMEOUT=${DEFAULT_TIMEOUT:-60}
OPTIONAL_AI_STACK_ENABLED=${OPTIONAL_AI_STACK_ENABLED:-true}
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-shml-platform}"

# =============================================================================
# Privilege Helpers
# =============================================================================

can_run_privileged() {
    [ "$(id -u)" -eq 0 ] || sudo -n true >/dev/null 2>&1
}

run_privileged_quiet() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    else
        sudo -n "$@"
    fi
}

# =============================================================================
# Tailscale Helpers
# =============================================================================

check_local_oidc_discovery() {
    local domain="$1"
    curl -skf --resolve "${domain}:443:127.0.0.1" \
        "https://${domain}/.well-known/openid-configuration" >/dev/null 2>&1
}

detect_tailscale_public_domain() {
    local dns_name=""
    dns_name=$(tailscale status --json 2>/dev/null | jq -r '.Self.DNSName // empty' 2>/dev/null | sed 's/\.$//' || true)
    if [ -n "$dns_name" ] && [ "$dns_name" != "null" ]; then
        echo "$dns_name"
        return 0
    fi
    tailscale status --json 2>/dev/null | jq -r '.Self.HostName + "." + .MagicDNSSuffix' 2>/dev/null || echo ""
}

funnel_active_for_domain() {
    local domain="$1"
    tailscale funnel status 2>/dev/null | grep -Fq "https://${domain}"
}
