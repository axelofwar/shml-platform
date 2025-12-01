#!/bin/bash
# Provision Grafana Dashboards
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DASHBOARD_DIR="$SCRIPT_DIR/dashboards"

echo "Provisioning Grafana dashboards..."

# Create dashboard directories
mkdir -p "$DASHBOARD_DIR"/{platform,mlflow,ray}

# Copy platform dashboards
cp "$SCRIPT_DIR/../../ray_compute/config/grafana/dashboards/system-metrics.json" "$DASHBOARD_DIR/platform/"

# Check if custom container-metrics dashboard exists, otherwise copy default
if [ ! -f "$DASHBOARD_DIR/platform/container-metrics.json" ]; then
    cp "$SCRIPT_DIR/../../ray_compute/config/grafana/dashboards/container-metrics.json" "$DASHBOARD_DIR/platform/"
    echo "  ✓ Container metrics dashboard copied (default)"
else
    echo "  ✓ Container metrics dashboard already exists (preserved)"
fi

# Ensure Panel 100 (container ID reference table) exists in container-metrics dashboard
if ! jq -e '.panels[] | select(.id == 100)' "$DASHBOARD_DIR/platform/container-metrics.json" >/dev/null 2>&1; then
    echo "  → Adding container ID reference table (Panel 100)..."
    jq '.panels += [{
      "datasource": {"type": "prometheus", "uid": "global-metrics"},
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
      "id": 100,
      "options": {
        "code": {"language": "plaintext", "showLineNumbers": false, "showMiniMap": false},
        "content": "## Container ID Reference\n\nThis table will be populated during setup.",
        "mode": "markdown"
      },
      "pluginVersion": "10.2.2",
      "title": "Container ID to Service Name Reference",
      "type": "text"
    }] | (.panels[] | select(.id == 1) | .gridPos) = {"h": 8, "w": 12, "x": 0, "y": 0} | .panels |= sort_by(.gridPos.y, .gridPos.x)' "$DASHBOARD_DIR/platform/container-metrics.json" > "$DASHBOARD_DIR/platform/container-metrics.json.tmp"
    mv "$DASHBOARD_DIR/platform/container-metrics.json.tmp" "$DASHBOARD_DIR/platform/container-metrics.json"
    echo "  ✓ Container ID reference table added (side-by-side with CPU Usage)"
fi

# Copy GPU monitoring dashboard if it exists (created during setup)
if [ -f "$DASHBOARD_DIR/platform/gpu-monitoring.json" ]; then
    echo "  ✓ GPU monitoring dashboard already exists"
else
    echo "  ⚠ GPU monitoring dashboard will be created during setup"
fi

# Fix platform dashboard datasources (all string formats)
sed -i 's/"datasource": "Ray Prometheus"/"datasource": {"type": "prometheus", "uid": "global-metrics"}/g' "$DASHBOARD_DIR/platform/"*.json
sed -i 's/"datasource": "prometheus"/"datasource": {"type": "prometheus", "uid": "global-metrics"}/g' "$DASHBOARD_DIR/platform/"*.json
sed -i 's/"datasource": "Global Metrics"/"datasource": {"type": "prometheus", "uid": "global-metrics"}/g' "$DASHBOARD_DIR/platform/"*.json
sed -i 's/"uid": "prometheus"/"uid": "global-metrics"/g' "$DASHBOARD_DIR/platform/"*.json
echo "  ✓ Platform dashboards copied and fixed"

# Copy Ray dashboards
cp "$SCRIPT_DIR/../../ray_compute/config/grafana/dashboards/ray-cluster-metrics.json" "$DASHBOARD_DIR/ray/"

# Fix Ray dashboard datasources
sed -i 's/"datasource": "Ray Prometheus"/"datasource": {"type": "prometheus", "uid": "ray-metrics"}/g' "$DASHBOARD_DIR/ray/"*.json
sed -i 's/"datasource": "prometheus"/"datasource": {"type": "prometheus", "uid": "ray-metrics"}/g' "$DASHBOARD_DIR/ray/"*.json
sed -i 's/"datasource": "Ray Metrics"/"datasource": {"type": "prometheus", "uid": "ray-metrics"}/g' "$DASHBOARD_DIR/ray/"*.json
sed -i 's/"uid": "prometheus"/"uid": "ray-metrics"/g' "$DASHBOARD_DIR/ray/"*.json
echo "  ✓ Ray dashboards copied and fixed"

# Copy MLflow dashboards (excluding infrastructure dashboards that belong in platform/)
for dashboard in "$SCRIPT_DIR/../../mlflow-server/docker/grafana/dashboards"/*.json; do
    filename=$(basename "$dashboard")
    # Skip infrastructure dashboards - they belong in platform/ folder
    if [ "$filename" != "system-metrics.json" ] && [ "$filename" != "container-metrics.json" ]; then
        cp "$dashboard" "$DASHBOARD_DIR/mlflow/"
    fi
done

# Fix MLflow dashboard datasources
sed -i 's/"datasource": "Ray Prometheus"/"datasource": {"type": "prometheus", "uid": "mlflow-metrics"}/g' "$DASHBOARD_DIR/mlflow/"*.json 2>/dev/null || true
sed -i 's/"datasource": "prometheus"/"datasource": {"type": "prometheus", "uid": "mlflow-metrics"}/g' "$DASHBOARD_DIR/mlflow/"*.json 2>/dev/null || true
sed -i 's/"datasource": "MLflow Metrics"/"datasource": {"type": "prometheus", "uid": "mlflow-metrics"}/g' "$DASHBOARD_DIR/mlflow/"*.json 2>/dev/null || true
sed -i 's/"uid": "prometheus"/"uid": "mlflow-metrics"/g' "$DASHBOARD_DIR/mlflow/"*.json 2>/dev/null || true
echo "  ✓ MLflow dashboards copied and fixed (infrastructure dashboards excluded)"

# Set ownership
chown -R 472:472 "$DASHBOARD_DIR"
echo "✓ Dashboard provisioning complete"
