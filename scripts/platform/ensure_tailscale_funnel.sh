#!/bin/bash
set -euo pipefail

EXPECTED_HOSTNAME="${EXPECTED_HOSTNAME:-shml-platform}"
EXPECTED_DOMAIN="${EXPECTED_DOMAIN:-shml-platform.${TAILNET_SUFFIX}}"
TARGET_PORT="${TAILSCALE_FUNNEL_TARGET_PORT:-80}"

until tailscale status >/dev/null 2>&1; do
    sleep 2
done

current_hostname="$(tailscale status --json | jq -r '.Self.HostName // empty' | tr -d '\n')"
current_domain="$(tailscale status --json | jq -r '.Self.DNSName // empty' | sed 's/\.$//' | tr -d '\n')"

if [ "$current_hostname" != "$EXPECTED_HOSTNAME" ]; then
    tailscale set --hostname="$EXPECTED_HOSTNAME" >/dev/null
    sleep 3
    current_domain="$(tailscale status --json | jq -r '.Self.DNSName // empty' | sed 's/\.$//' | tr -d '\n')"
fi

if [ "$current_domain" != "$EXPECTED_DOMAIN" ]; then
    echo "Unexpected Tailscale DNS name: $current_domain (expected $EXPECTED_DOMAIN)" >&2
    exit 1
fi

tailscale funnel reset >/dev/null 2>&1 || true
tailscale funnel --bg "$TARGET_PORT" >/dev/null
tailscale funnel status | grep -F "$EXPECTED_DOMAIN" >/dev/null
