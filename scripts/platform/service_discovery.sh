#!/usr/bin/env bash
# =============================================================================
# service_discovery.sh — Dynamic platform endpoint discovery helpers
# =============================================================================
# Source from host scripts or container scripts.
#
# Examples:
#   source scripts/platform/service_discovery.sh
#   resolve_gitlab_base_url
#   resolve_service_url shml-gitlab 8929 http /gitlab/users/sign_in
# =============================================================================

set -uo pipefail

platform_network_name() {
    echo "${PLATFORM_PREFIX:-shml}-platform"
}

have_cmd() {
    command -v "$1" >/dev/null 2>&1
}

running_in_container() {
    [[ -f /.dockerenv ]] && return 0
    grep -qaE '(docker|containerd|kubepods)' /proc/1/cgroup 2>/dev/null
}

can_resolve_host() {
    local host="$1"
    getent hosts "$host" >/dev/null 2>&1
}

resolve_container_ip() {
    local name="$1"
    have_cmd docker || return 1
    docker inspect "$name" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null | awk 'NF {print; exit}'
}

first_nonempty() {
    for value in "$@"; do
        [[ -n "$value" ]] && { echo "$value"; return 0; }
    done
    return 1
}

resolve_service_host() {
    local primary="$1"
    local secondary="${2:-}"

    if can_resolve_host "$primary"; then
        echo "$primary"
        return 0
    fi
    if [[ -n "$secondary" ]] && can_resolve_host "$secondary"; then
        echo "$secondary"
        return 0
    fi

    local ip=""
    ip=$(first_nonempty "$(resolve_container_ip "$primary" 2>/dev/null || true)" "$(resolve_container_ip "$secondary" 2>/dev/null || true)" || true)
    [[ -n "$ip" ]] && { echo "$ip"; return 0; }

    if [[ "$primary" == "shml-gitlab" || "$secondary" == "gitlab" ]]; then
        echo "127.0.0.1"
        return 0
    fi

    return 1
}

resolve_service_url() {
    local primary="$1"
    local port="$2"
    local scheme="${3:-http}"
    local path="${4:-}"
    local secondary="${5:-}"
    local host

    host=$(resolve_service_host "$primary" "$secondary") || return 1
    echo "${scheme}://${host}:${port}${path}"
}

resolve_gitlab_base_url() {
    if [[ -n "${GITLAB_BASE_URL:-}" ]]; then
        echo "${GITLAB_BASE_URL%/}"
        return 0
    fi

    local host
    host=$(resolve_service_host "shml-gitlab" "gitlab") || return 1
    echo "http://${host}:8929/gitlab"
}

resolve_gitlab_api_url() {
    local base
    base=$(resolve_gitlab_base_url) || return 1
    echo "${base}/api/v4"
}

resolve_mlflow_tracking_url() {
    if [[ -n "${MLFLOW_TRACKING_URI:-}" ]]; then
        echo "$MLFLOW_TRACKING_URI"
        return 0
    fi

    if running_in_container; then
        echo "http://mlflow-nginx:80"
        return 0
    fi

    local url
    url=$(resolve_service_url "mlflow-nginx" 80 http "" "mlflow-nginx") || return 1
    echo "$url"
}
