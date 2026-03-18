#!/usr/bin/env bash
# =============================================================================
# platform_audit.sh — Full platform service health audit (Phase 0.3)
#
# Iterates all known containers, checks health, verifies Traefik routes,
# and creates GitLab issues for any failures found.
#
# Usage:
#   bash scripts/platform/platform_audit.sh [--report-only] [--gitlab-issues]
#
# Options:
#   --report-only    Print JSON report to stdout, don't create GitLab issues
#   --gitlab-issues  Create GitLab issues for each failed service
#
# Outputs:
#   data/platform-audit/audit-YYYY-MM-DD.json  — structured audit snapshot
#
# Exit codes:
#   0  All services healthy
#   1  One or more services unhealthy (or Traefik route missing)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
AUDIT_DIR="$PLATFORM_DIR/data/platform-audit"
DATE_STAMP=$(date -u '+%Y-%m-%d')
AUDIT_JSON="$AUDIT_DIR/audit-${DATE_STAMP}.json"
GITLAB_UTILS="$SCRIPT_DIR/gitlab_utils.py"

REPORT_ONLY=false
CREATE_ISSUES=false

for arg in "$@"; do
    case "$arg" in
        --report-only)   REPORT_ONLY=true ;;
        --gitlab-issues) CREATE_ISSUES=true ;;
    esac
done

mkdir -p "$AUDIT_DIR"

log() { echo "[audit $(date '+%H:%M:%S')] $*" >&2; }
ok()  { echo "[audit $(date '+%H:%M:%S')] ✓ $*" >&2; }
fail(){ echo "[audit $(date '+%H:%M:%S')] ✗ $*" >&2; }

# ── 1. Docker container inventory ──────────────────────────────────────────
log "Gathering container inventory..."

CONTAINERS_JSON=$(docker ps --format '{{json .}}' 2>/dev/null | \
    jq -s '[.[] | {name: .Names, image: .Image, status: .Status, state: .State, ports: .Ports}]' || echo "[]")

TOTAL_CONTAINERS=$(echo "$CONTAINERS_JSON" | jq 'length')
log "Found $TOTAL_CONTAINERS running containers"

# ── 2. Per-container health check ──────────────────────────────────────────
log "Checking Docker health status for each container..."

HEALTH_RESULTS=()
UNHEALTHY=()

while IFS= read -r name; do
    health=$(docker inspect "$name" \
        --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' 2>/dev/null || echo "inspect-failed")
    if [[ "$health" == "healthy" || "$health" == "no-healthcheck" ]]; then
        ok "$name: $health"
        HEALTH_RESULTS+=("{\"container\":\"$name\",\"health\":\"$health\",\"ok\":true}")
    else
        fail "$name: $health"
        HEALTH_RESULTS+=("{\"container\":\"$name\",\"health\":\"$health\",\"ok\":false}")
        UNHEALTHY+=("$name")
    fi
done < <(docker ps --format '{{.Names}}' 2>/dev/null | sort)

HEALTH_JSON="[$(IFS=,; echo "${HEALTH_RESULTS[*]:-}")]"

# ── 3. Traefik route audit ──────────────────────────────────────────────────
log "Auditing Traefik routes via API..."

TRAEFIK_API="${TRAEFIK_API_URL:-http://localhost:8090}"
ROUTES_JSON="[]"
ROUTE_FAILURES=()

if curl -sf --max-time 5 "${TRAEFIK_API}/ping" >/dev/null 2>&1; then
    ROUTES_RAW=$(curl -sf --max-time 10 "${TRAEFIK_API}/api/http/routers" 2>/dev/null || echo "[]")
    ROUTES_JSON=$(echo "$ROUTES_RAW" | jq '[.[] | {name: .name, rule: .rule, status: .status, service: .service}]' 2>/dev/null || echo "[]")
    ROUTE_COUNT=$(echo "$ROUTES_JSON" | jq 'length')
    log "Found $ROUTE_COUNT Traefik routes"

    # Check for any routes not in 'enabled' status
    while IFS= read -r route_name; do
        route_status=$(echo "$ROUTES_JSON" | jq -r --arg n "$route_name" '.[] | select(.name==$n) | .status')
        if [[ "$route_status" != "enabled" ]]; then
            fail "Traefik route '$route_name' status: $route_status"
            ROUTE_FAILURES+=("$route_name")
        fi
    done < <(echo "$ROUTES_JSON" | jq -r '.[].name')
else
    fail "Traefik API not reachable at ${TRAEFIK_API}"
    ROUTE_FAILURES+=("traefik-api-unreachable")
fi

# ── 4. Key HTTP endpoint probes ─────────────────────────────────────────────
log "Probing key service endpoints..."

declare -A ENDPOINTS=(
    ["traefik-dashboard"]="${TRAEFIK_API}/dashboard/"
    ["mlflow-server"]="http://localhost:5000/health"
    ["ray-dashboard"]="http://localhost:8265/"
    ["ray-compute-api"]="http://localhost:8000/health"
    ["fusionauth"]="http://localhost:9011/api/status"
    ["inference-gateway"]="http://localhost:8020/health"
    ["qwen3-vl"]="http://localhost:8003/health"
    ["grafana"]="http://localhost:3000/api/health"
)

PROBE_RESULTS=()
PROBE_FAILURES=()

for svc in "${!ENDPOINTS[@]}"; do
    url="${ENDPOINTS[$svc]}"
    http_code=$(curl -sf -o /dev/null -w "%{http_code}" --max-time 5 "$url" 2>/dev/null || echo "000")
    if [[ "$http_code" =~ ^(200|301|302|401|403)$ ]]; then
        ok "$svc ($url): HTTP $http_code"
        PROBE_RESULTS+=("{\"service\":\"$svc\",\"url\":\"$url\",\"http_code\":$http_code,\"ok\":true}")
    else
        fail "$svc ($url): HTTP $http_code (unreachable or error)"
        PROBE_RESULTS+=("{\"service\":\"$svc\",\"url\":\"$url\",\"http_code\":$http_code,\"ok\":false}")
        PROBE_FAILURES+=("$svc: $url -> $http_code")
    fi
done

PROBE_JSON="[$(IFS=,; echo "${PROBE_RESULTS[*]:-}")]"

# ── 5. Compile audit report ──────────────────────────────────────────────────
TOTAL_UNHEALTHY=${#UNHEALTHY[@]}
TOTAL_ROUTE_FAILURES=${#ROUTE_FAILURES[@]}
TOTAL_PROBE_FAILURES=${#PROBE_FAILURES[@]}
OVERALL_OK=true
[[ $TOTAL_UNHEALTHY -gt 0 || $TOTAL_ROUTE_FAILURES -gt 0 || $TOTAL_PROBE_FAILURES -gt 0 ]] && OVERALL_OK=false

AUDIT_REPORT=$(jq -n \
    --arg date "$DATE_STAMP" \
    --argjson ok "$OVERALL_OK" \
    --argjson containers "$CONTAINERS_JSON" \
    --argjson health "$HEALTH_JSON" \
    --argjson routes "$ROUTES_JSON" \
    --argjson probes "$PROBE_JSON" \
    --argjson unhealthy "$(printf '%s\n' "${UNHEALTHY[@]:-}" | jq -R . | jq -s .)" \
    --argjson route_failures "$(printf '%s\n' "${ROUTE_FAILURES[@]:-}" | jq -R . | jq -s .)" \
    --argjson probe_failures "$(printf '%s\n' "${PROBE_FAILURES[@]:-}" | jq -R . | jq -s .)" \
    '{
        audit_date: $date,
        overall_ok: $ok,
        summary: {
            total_containers: ($containers | length),
            unhealthy_containers: ($unhealthy | length),
            traefik_route_failures: ($route_failures | length),
            endpoint_probe_failures: ($probe_failures | length)
        },
        unhealthy_containers: $unhealthy,
        traefik_route_failures: $route_failures,
        endpoint_probe_failures: $probe_failures,
        container_health: $health,
        traefik_routes: $routes,
        endpoint_probes: $probes
    }')

if [[ "$REPORT_ONLY" == "true" ]]; then
    echo "$AUDIT_REPORT"
    exit 0
fi

# Write to file
echo "$AUDIT_REPORT" > "$AUDIT_JSON"
log "Audit report written to $AUDIT_JSON"

# ── 6. Create GitLab issues for failures ────────────────────────────────────
if [[ "$CREATE_ISSUES" == "true" ]] && command -v python3 >/dev/null 2>&1; then
    log "Creating GitLab issues for failures..."

    for container in "${UNHEALTHY[@]:-}"; do
        python3 "$GITLAB_UTILS" upsert-issue \
            "Unhealthy container: $container (audit $DATE_STAMP)" \
            --labels "type::bug,priority::high,component::infra,source::scan" \
            --description "## Platform Audit Finding

Container **\`$container\`** reported unhealthy during automated audit on \`$DATE_STAMP\`.

### Steps to investigate
1. \`docker inspect $container\`
2. \`docker logs $container --tail 50\`
3. Check health endpoint if defined in docker-compose

### Source
Auto-created by \`platform_audit.sh --gitlab-issues\`" 2>/dev/null || true
    done

    for probe in "${PROBE_FAILURES[@]:-}"; do
        svc="${probe%%:*}"
        python3 "$GITLAB_UTILS" upsert-issue \
            "Endpoint unreachable: $svc (audit $DATE_STAMP)" \
            --labels "type::bug,priority::medium,component::infra,source::scan" \
            --description "## Platform Audit Finding

Service **\`$svc\`** endpoint probe failed during automated audit on \`$DATE_STAMP\`.

Details: \`$probe\`

### Source
Auto-created by \`platform_audit.sh --gitlab-issues\`" 2>/dev/null || true
    done
fi

# ── 7. Print summary ─────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════"
echo "  Platform Audit Summary — $DATE_STAMP"
echo "════════════════════════════════════════"
echo "  Running containers:     $TOTAL_CONTAINERS"
echo "  Unhealthy containers:   $TOTAL_UNHEALTHY"
echo "  Traefik route failures: $TOTAL_ROUTE_FAILURES"
echo "  Endpoint probe failures: $TOTAL_PROBE_FAILURES"
if [[ "$OVERALL_OK" == "true" ]]; then
    echo "  Overall status:         ✓ HEALTHY"
else
    echo "  Overall status:         ✗ DEGRADED"
fi
echo "════════════════════════════════════════"
echo "  Report: $AUDIT_JSON"
echo ""

[[ "$OVERALL_OK" == "true" ]]
