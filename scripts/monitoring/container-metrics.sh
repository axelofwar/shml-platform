#!/bin/bash
# =============================================================================
# Unified Container Metrics Script for SHML Platform
# =============================================================================
# Consolidates: generate_container_mapping.sh, generate_container_name_metrics.sh,
#               update_container_dashboard.sh
#
# Usage:
#   ./scripts/container-metrics.sh mapping     # Generate container ID→name mapping
#   ./scripts/container-metrics.sh metrics     # Generate Prometheus metrics file
#   ./scripts/container-metrics.sh dashboard   # Update Grafana dashboard
#   ./scripts/container-metrics.sh all         # Run all of the above
#   ./scripts/container-metrics.sh watch       # Continuous update mode
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Output directories
PROMETHEUS_DIR="${PROJECT_ROOT}/monitoring/prometheus"
GRAFANA_DIR="${PROJECT_ROOT}/monitoring/grafana"

# =============================================================================
# Helper Functions
# =============================================================================

print_success() { echo -e "${GREEN}✓ $1${NC}"; }
print_error() { echo -e "${RED}✗ $1${NC}"; }
print_info() { echo -e "${CYAN}ℹ $1${NC}"; }

ensure_dirs() {
    mkdir -p "$PROMETHEUS_DIR"
    mkdir -p "$GRAFANA_DIR"
}

# =============================================================================
# Generate Container ID Mapping (for Prometheus file_sd)
# =============================================================================

generate_mapping() {
    ensure_dirs

    local output_file="${PROMETHEUS_DIR}/container_id_mapping.json"

    echo "Generating container ID to name mapping..."

    # Generate mapping from running containers
    local mapping=$(docker ps --format '{{.ID}} {{.Names}}' | while read id name; do
        # Get full container ID
        full_id=$(docker inspect --format '{{.Id}}' "$id" 2>/dev/null || echo "")
        if [ -n "$full_id" ]; then
            echo "{\"targets\": [\"cadvisor:8080\"], \"labels\": {\"container_id\": \"$full_id\", \"container_name\": \"$name\", \"short_id\": \"$id\"}}"
        fi
    done | paste -sd ',')

    # Write to file
    echo "[${mapping}]" > "$output_file"

    # Also generate simple key-value format
    docker ps --format '{{.ID}}={{.Names}}' > "${PROMETHEUS_DIR}/container_names.txt"

    local count=$(docker ps -q | wc -l)
    print_success "Generated mapping for ${count} containers"
    echo "  → ${output_file}"
    echo "  → ${PROMETHEUS_DIR}/container_names.txt"
}

# =============================================================================
# Generate Prometheus Metrics File
# =============================================================================

generate_metrics() {
    ensure_dirs

    local metrics_file="${PROMETHEUS_DIR}/container_names.prom"

    echo "Generating Prometheus metrics file..."

    # Generate metrics with container name labels
    cat > "${metrics_file}.tmp" << 'EOF'
# HELP container_info Container information with name label
# TYPE container_info gauge
EOF

    # Get all running containers
    docker ps --format '{{.ID}} {{.Names}}' | while read -r full_id name; do
        short_id="${full_id:0:12}"
        # Create a metric with both short_id and name as labels
        echo "container_info{container_short_id=\"${short_id}\",container_name=\"${name}\"} 1" >> "${metrics_file}.tmp"
    done

    # Atomic move
    mv "${metrics_file}.tmp" "${metrics_file}"

    local count=$(grep -c 'container_info{' "$metrics_file" 2>/dev/null || echo 0)
    print_success "Generated metrics for ${count} containers"
    echo "  → ${metrics_file}"
}

# =============================================================================
# Update Grafana Dashboard
# =============================================================================

update_dashboard() {
    ensure_dirs

    local dashboard_file="${GRAFANA_DIR}/dashboards/container-metrics.json"

    if [ ! -f "$dashboard_file" ]; then
        print_info "Dashboard file not found, creating template..."
        mkdir -p "$(dirname "$dashboard_file")"
        create_dashboard_template "$dashboard_file"
    fi

    echo "Updating Grafana dashboard with current containers..."

    # Get container list for dashboard variables
    local containers=$(docker ps --format '{{.Names}}' | sort | tr '\n' ',' | sed 's/,$//')

    # Update dashboard if jq is available
    if command -v jq &> /dev/null; then
        # Create updated variable options
        local options=$(docker ps --format '{{.Names}}' | sort | jq -R -s -c 'split("\n") | map(select(length > 0)) | map({text: ., value: ., selected: false})')

        # Update the dashboard JSON
        local tmp_file=$(mktemp)
        jq --argjson opts "$options" '
            .templating.list |= map(
                if .name == "container" then
                    .options = $opts |
                    .current = {text: "All", value: "$__all"}
                else . end
            )
        ' "$dashboard_file" > "$tmp_file" 2>/dev/null && mv "$tmp_file" "$dashboard_file"

        print_success "Dashboard updated with ${containers}"
    else
        print_info "jq not installed, dashboard not updated"
    fi

    echo "  → ${dashboard_file}"

    # Notify Grafana to reload (if API available)
    if curl -s -o /dev/null -w "%{http_code}" "http://localhost:3000/api/health" 2>/dev/null | grep -q "200"; then
        print_info "Grafana is running - dashboard will reload automatically"
    fi
}

create_dashboard_template() {
    local file="$1"
    cat > "$file" << 'EOF'
{
  "annotations": {"list": []},
  "editable": true,
  "fiscalYearStartMonth": 0,
  "graphTooltip": 0,
  "id": null,
  "links": [],
  "liveNow": false,
  "panels": [
    {
      "datasource": {"type": "prometheus", "uid": "prometheus"},
      "fieldConfig": {
        "defaults": {"color": {"mode": "palette-classic"}, "unit": "percent"},
        "overrides": []
      },
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
      "id": 1,
      "options": {"legend": {"displayMode": "list"}, "tooltip": {"mode": "single"}},
      "targets": [
        {
          "expr": "rate(container_cpu_usage_seconds_total{name=~\"$container\"}[5m]) * 100",
          "legendFormat": "{{name}}"
        }
      ],
      "title": "Container CPU Usage",
      "type": "timeseries"
    },
    {
      "datasource": {"type": "prometheus", "uid": "prometheus"},
      "fieldConfig": {
        "defaults": {"color": {"mode": "palette-classic"}, "unit": "bytes"},
        "overrides": []
      },
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
      "id": 2,
      "options": {"legend": {"displayMode": "list"}, "tooltip": {"mode": "single"}},
      "targets": [
        {
          "expr": "container_memory_usage_bytes{name=~\"$container\"}",
          "legendFormat": "{{name}}"
        }
      ],
      "title": "Container Memory Usage",
      "type": "timeseries"
    }
  ],
  "schemaVersion": 38,
  "style": "dark",
  "tags": ["containers", "docker"],
  "templating": {
    "list": [
      {
        "allValue": ".*",
        "current": {"text": "All", "value": "$__all"},
        "datasource": {"type": "prometheus", "uid": "prometheus"},
        "definition": "label_values(container_cpu_usage_seconds_total, name)",
        "includeAll": true,
        "multi": true,
        "name": "container",
        "options": [],
        "query": {"query": "label_values(container_cpu_usage_seconds_total, name)"},
        "refresh": 2,
        "type": "query"
      }
    ]
  },
  "time": {"from": "now-1h", "to": "now"},
  "title": "Container Metrics",
  "uid": "container-metrics",
  "version": 1
}
EOF
}

# =============================================================================
# Run All
# =============================================================================

run_all() {
    echo "=== Container Metrics Update ==="
    echo
    generate_mapping
    echo
    generate_metrics
    echo
    update_dashboard
    echo
    print_success "All container metrics updated"
}

# =============================================================================
# Watch Mode (Continuous Updates)
# =============================================================================

watch_mode() {
    local interval="${1:-30}"

    echo "Starting watch mode (interval: ${interval}s)"
    echo "Press Ctrl+C to stop"
    echo

    while true; do
        echo -e "${CYAN}[$(date '+%H:%M:%S')]${NC} Updating metrics..."
        generate_mapping > /dev/null
        generate_metrics > /dev/null
        echo "  Updated $(docker ps -q | wc -l) containers"
        sleep "$interval"
    done
}

# =============================================================================
# Main
# =============================================================================

show_usage() {
    echo "SHML Platform Container Metrics Tool"
    echo
    echo "Usage: $0 <command> [options]"
    echo
    echo "Commands:"
    echo "  mapping     Generate container ID to name mapping (JSON)"
    echo "  metrics     Generate Prometheus metrics file (.prom)"
    echo "  dashboard   Update Grafana dashboard with current containers"
    echo "  all         Run all of the above"
    echo "  watch [s]   Continuous update mode (default: 30s interval)"
    echo
    echo "Output Locations:"
    echo "  ${PROMETHEUS_DIR}/container_id_mapping.json"
    echo "  ${PROMETHEUS_DIR}/container_names.prom"
    echo "  ${PROMETHEUS_DIR}/container_names.txt"
    echo "  ${GRAFANA_DIR}/dashboards/container-metrics.json"
    echo
    echo "Examples:"
    echo "  $0 all              # Update everything once"
    echo "  $0 watch 60         # Update every 60 seconds"
    echo "  $0 metrics          # Just update Prometheus metrics"
}

main() {
    local command="${1:-}"
    shift 2>/dev/null || true

    case "$command" in
        mapping)
            generate_mapping
            ;;
        metrics)
            generate_metrics
            ;;
        dashboard)
            update_dashboard
            ;;
        all)
            run_all
            ;;
        watch)
            watch_mode "$@"
            ;;
        -h|--help|help|"")
            show_usage
            ;;
        *)
            print_error "Unknown command: $command"
            echo
            show_usage
            exit 1
            ;;
    esac
}

main "$@"
