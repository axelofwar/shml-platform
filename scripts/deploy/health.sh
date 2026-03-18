#!/usr/bin/env bash
# scripts/deploy/health.sh — Health check waiters with strict/warn modes
#
# Provides: wait_for_health, wait_for_http, wait_for_middleware

[[ -n "${_SHML_HEALTH_LOADED:-}" ]] && return 0
_SHML_HEALTH_LOADED=1

# Wait for container health with configurable timeout
# Usage: wait_for_health <container> [timeout_secs] [strict]
#   strict=1: exit 1 on timeout (for critical dependencies)
#   strict=0: warn only (default, for optional services)
wait_for_health() {
    local container=$1
    local timeout=${2:-$DEFAULT_TIMEOUT}
    local strict=${3:-0}
    local wait_time=0
    local interval=3

    echo -n "  Waiting for $container to be healthy"
    while [ $wait_time -lt $timeout ]; do
        if ! docker inspect "$container" >/dev/null 2>&1; then
            echo -n "."
            sleep $interval
            wait_time=$((wait_time + interval))
            continue
        fi

        local status
        status=$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$container" 2>/dev/null || echo "not-found")

        case "$status" in
            healthy)
                echo -e " ${GREEN}✓${NC} (${wait_time}s)"
                return 0
                ;;
            no-healthcheck)
                local running
                running=$(docker inspect --format='{{.State.Running}}' "$container" 2>/dev/null || echo "false")
                if [ "$running" = "true" ]; then
                    echo -e " ${GREEN}✓${NC} (running, no healthcheck)"
                    return 0
                fi
                ;;
            unhealthy)
                # Don't fail immediately — service might recover
                ;;
        esac

        echo -n "."
        sleep $interval
        wait_time=$((wait_time + interval))
    done

    if [ "$strict" = "1" ]; then
        echo -e " ${RED}✗${NC} (timeout after ${timeout}s — CRITICAL)"
        return 1
    fi
    echo -e " ${YELLOW}⚠${NC} (timeout after ${timeout}s)"
    return 1
}

# Wait for HTTP endpoint to be reachable
# Usage: wait_for_http <url> [timeout_secs]
wait_for_http() {
    local url=$1
    local timeout=${2:-30}
    local wait_time=0
    local interval=2

    echo -n "  Waiting for $url"
    while [ $wait_time -lt $timeout ]; do
        if curl -sf -o /dev/null "$url" 2>/dev/null; then
            echo -e " ${GREEN}✓${NC} (${wait_time}s)"
            return 0
        fi
        echo -n "."
        sleep $interval
        wait_time=$((wait_time + interval))
    done

    echo -e " ${YELLOW}⚠${NC} (timeout after ${timeout}s)"
    return 1
}

# Wait for Traefik middleware to be registered
# Usage: wait_for_middleware <middleware_name> [timeout_secs]
wait_for_middleware() {
    local middleware=$1
    local timeout=${2:-60}
    local wait_time=0
    local interval=3

    echo -n "  Waiting for Traefik middleware '$middleware'"
    while [ $wait_time -lt $timeout ]; do
        if curl -sf "http://localhost:8090/api/http/middlewares/${middleware}@docker" >/dev/null 2>&1; then
            echo -e " ${GREEN}✓${NC} (${wait_time}s)"
            return 0
        fi
        echo -n "."
        sleep $interval
        wait_time=$((wait_time + interval))
    done

    echo -e " ${YELLOW}⚠${NC} (timeout after ${timeout}s)"
    return 1
}
