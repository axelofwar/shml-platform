#!/usr/bin/env bash
# scripts/deploy/networks.sh — Docker network management
#
# Creates/verifies two-tier network isolation:
#   shml-platform  — Traefik routing network (all HTTP-routed services)
#   shml-core-net  — DB/cache isolation (postgres + redis only)

[[ -n "${_SHML_NETWORKS_LOADED:-}" ]] && return 0
_SHML_NETWORKS_LOADED=1

PLATFORM_NETWORK="${PLATFORM_PREFIX:-shml}-platform"
CORE_NETWORK="shml-core-net"

ensure_networks() {
    # Platform network (Traefik routing — subnet kept for backward compat)
    if ! docker network inspect "$PLATFORM_NETWORK" >/dev/null 2>&1; then
        log_info "Creating platform network: $PLATFORM_NETWORK"
        docker network create "$PLATFORM_NETWORK" \
            --driver bridge \
            --subnet 172.30.0.0/16 \
            2>/dev/null || true
        log_success "Network created: $PLATFORM_NETWORK"
    fi

    # Core network (DB/cache isolation — no external routing)
    if ! docker network inspect "$CORE_NETWORK" >/dev/null 2>&1; then
        log_info "Creating core isolation network: $CORE_NETWORK"
        docker network create "$CORE_NETWORK" \
            --driver bridge \
            --internal \
            2>/dev/null || true
        log_success "Network created: $CORE_NETWORK"
    fi
}

# Backward-compat alias
ensure_network() { ensure_networks; }
