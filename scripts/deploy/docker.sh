#!/usr/bin/env bash
# scripts/deploy/docker.sh — Docker Compose wrappers with retry, cleanup, and lifecycle management
#
# Provides: dc_pull, dc_up, dc_stop, dc_down, dc_restart (new),
#           cleanup_compose_conflicts, compose_declared_container_names, stop_container

[[ -n "${_SHML_DOCKER_LOADED:-}" ]] && return 0
_SHML_DOCKER_LOADED=1

# =============================================================================
# Registry Pull with Retry + Fallback
# =============================================================================
# Pull policy follows SHML_IMAGE_PULL_POLICY (always|missing|never).
# Retries up to 3 times with exponential backoff.
# If registry is unreachable and policy != "always", continues with local images.

dc_pull() {
    local compose_file="$1"
    local pull_policy="${SHML_IMAGE_PULL_POLICY:-missing}"

    # Skip pull entirely if no registry configured or policy is never
    if [ -z "${SHML_REGISTRY_IMAGE_PREFIX:-}" ] || [ "$pull_policy" = "never" ]; then
        return 0
    fi

    local attempt=1
    local max_attempts=3
    local backoff=5

    log_info "  Pulling images from registry (policy=${pull_policy})..."
    while [ $attempt -le $max_attempts ]; do
        if docker compose -p "$COMPOSE_PROJECT_NAME" --env-file .env \
            -f "$compose_file" pull --ignore-pull-failures 2>&1 | grep -v "orphan"; then
            return 0
        fi
        if [ $attempt -lt $max_attempts ]; then
            log_warn "  Pull attempt $attempt failed, retrying in ${backoff}s..."
            sleep $backoff
            backoff=$((backoff * 2))
        fi
        attempt=$((attempt + 1))
    done

    if [ "$pull_policy" = "always" ]; then
        log_error "  Registry pull failed after $max_attempts attempts (policy=always — cannot continue)"
        return 1
    fi

    log_warn "  Registry pull failed — continuing with local/cached images"
    return 0
}

# =============================================================================
# Compose Conflict Detection
# =============================================================================

compose_declared_container_names() {
    local compose_file="$1"
    grep -E '^[[:space:]]*container_name:' "$compose_file" 2>/dev/null | awk '{print $2}' | tr -d '"' | sort -u
}

cleanup_compose_conflicts() {
    local compose_file="$1"

    while IFS= read -r container_name; do
        [ -z "$container_name" ] && continue

        if ! docker inspect "$container_name" >/dev/null 2>&1; then
            continue
        fi

        local existing_project
        local existing_service
        existing_project=$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project" }}' "$container_name" 2>/dev/null || true)
        existing_service=$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.service" }}' "$container_name" 2>/dev/null || true)

        if [ "$existing_project" != "$COMPOSE_PROJECT_NAME" ] || [ -z "$existing_service" ]; then
            log_warn "Removing conflicting container: $container_name (project=${existing_project:-none})"
            docker rm -f "$container_name" >/dev/null 2>&1 || true
        fi
    done < <(compose_declared_container_names "$compose_file")
}

# =============================================================================
# Compose Lifecycle Wrappers
# =============================================================================

# dc_up: pull (with retry+fallback) → cleanup conflicts → start with remove-orphans
# Usage: dc_up <compose_file> [service...]
dc_up() {
    local compose_file="$1"
    shift
    ensure_networks
    cleanup_compose_conflicts "$compose_file"
    dc_pull "$compose_file"
    docker compose -p "$COMPOSE_PROJECT_NAME" --env-file .env \
        -f "$compose_file" up -d --remove-orphans \
        --pull "${SHML_IMAGE_PULL_POLICY:-missing}" "$@" 2>&1 | grep -v "orphan" || true
}

# dc_stop: stop containers (preserves container state, fast for temporary stops)
# Usage: dc_stop <compose_file> [service...]
dc_stop() {
    local compose_file="$1"
    shift
    docker compose -p "$COMPOSE_PROJECT_NAME" --env-file .env -f "$compose_file" stop "$@" 2>/dev/null || true
}

# dc_down: stop AND remove containers + orphans (use before restart for clean slate)
# Usage: dc_down <compose_file> [--volumes] [service...]
dc_down() {
    local compose_file="$1"
    shift
    docker compose -p "$COMPOSE_PROJECT_NAME" --env-file .env \
        -f "$compose_file" down --remove-orphans "$@" 2>/dev/null || true
}

# dc_restart: ordered stop → remove → pull → recreate (Phase 2 lifecycle primitive)
# Guarantees clean container state and picks up image updates.
# Usage: dc_restart <compose_file> [service...]
dc_restart() {
    local compose_file="$1"
    shift
    local services=("$@")
    log_info "  Restarting ${services[*]:-all} (${compose_file##*/})..."
    dc_down "$compose_file" "${services[@]}"
    dc_up  "$compose_file" "${services[@]}"
}

# stop_container: gracefully stop a single container by name
stop_container() {
    local container=$1
    if docker ps -q -f "name=$container" | grep -q .; then
        echo -n "  Stopping $container..."
        docker stop "$container" -t 10 >/dev/null 2>&1 && echo -e " ${GREEN}✓${NC}" || echo -e " ${YELLOW}⚠${NC}"
    fi
}
