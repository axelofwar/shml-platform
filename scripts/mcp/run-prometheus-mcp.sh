#!/usr/bin/env bash
# =============================================================================
# run-prometheus-mcp.sh — Non-interactive Prometheus MCP server launcher
#
# Sources .env from the platform root, then execs the Prometheus MCP server.
# Uses platform-internal Prometheus (global-prometheus at 172.30.0.23:9090).
#
# Used by: .vscode/mcp.json, mcp/mcp-config.json
# =============================================================================
set -euo pipefail

PLATFORM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Load config from .env
if [[ -f "$PLATFORM_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$PLATFORM_DIR/.env"
    set +a
fi

# global-prometheus Docker bridge IP — accessible from host
export PROMETHEUS_URL="${PROMETHEUS_URL:-http://172.30.0.23:9090}"

exec npx -y mcp-prometheus@latest
