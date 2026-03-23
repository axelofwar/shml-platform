#!/usr/bin/env bash
# =============================================================================
# run-gitlab-mcp.sh — Non-interactive GitLab MCP server launcher
#
# Sources .env from the platform root, then execs the GitLab MCP server.
# This makes the MCP server fully self-contained: no interactive prompts,
# no requirement to pre-source .env in the shell before launching VS Code.
#
# Used by: .vscode/mcp.json, mcp/mcp-config.json
# =============================================================================
set -euo pipefail

PLATFORM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Load secrets from .env (non-interactive token injection)
if [[ -f "$PLATFORM_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$PLATFORM_DIR/.env"
    set +a
fi

# Map platform PAT name → what the GitLab MCP server expects
export GITLAB_PERSONAL_ACCESS_TOKEN="${GITLAB_PERSONAL_ACCESS_TOKEN:-${GITLAB_AXELOFWAR_PERSONAL_ACCESS_TOKEN:-}}"

if [[ -z "$GITLAB_PERSONAL_ACCESS_TOKEN" ]]; then
    echo "[run-gitlab-mcp] ERROR: No GitLab token found. Set GITLAB_AXELOFWAR_PERSONAL_ACCESS_TOKEN in .env" >&2
    exit 1
fi

# Resolve GitLab container IP dynamically — avoids hardcoded IPs that change on
# Docker restart.  We query the shml-platform network directly so the MCP server
# reaches GitLab without going through OAuth2-proxy (which would block API calls).
if [[ -z "${GITLAB_API_URL:-}" ]]; then
    _prefix="${PLATFORM_PREFIX:-shml}"
    _gitlab_ip=$(docker inspect "${_prefix}-gitlab" \
        --format='{{(index .NetworkSettings.Networks "shml-platform").IPAddress}}' \
        2>/dev/null || true)
    if [[ -n "$_gitlab_ip" ]]; then
        export GITLAB_API_URL="http://${_gitlab_ip}:8929/gitlab/api/v4"
    else
        echo "[run-gitlab-mcp] WARN: Could not resolve GitLab container IP; falling back to shml-platform Traefik route" >&2
        export GITLAB_API_URL="http://localhost/gitlab/api/v4"
    fi
fi

exec npx -y @modelcontextprotocol/server-gitlab
