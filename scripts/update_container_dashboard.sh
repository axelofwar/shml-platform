#!/bin/bash
# Update Container Metrics Dashboard with current container IDs
# Run this script after recreating containers to update the reference table

set -e

DASHBOARD_FILE="monitoring/grafana/dashboards/platform/container-metrics.json"

echo "Updating Container Metrics Dashboard with current container IDs..."

# Generate the markdown table content
CONTAINER_TABLE="## Container ID to Service Name Mapping\n\nMatch the **Container IDs** shown in the charts below with their **Service Names**:\n\n| Container ID | Service Name | Description |\n|--------------|--------------|-------------|"

# Get all running containers and add them to the table
while IFS= read -r line; do
    CONTAINER_ID=$(echo "$line" | awk '{print $1}')
    CONTAINER_NAME=$(echo "$line" | awk '{print $2}')

    # Add description based on container name
    case "$CONTAINER_NAME" in
        *ray-head*) DESC="Ray cluster head node" ;;
        *ray-compute*) DESC="Ray compute API" ;;
        *ray-prometheus*) DESC="Ray metrics collector" ;;
        *mlflow-server*) DESC="MLflow tracking server" ;;
        *mlflow-nginx*) DESC="MLflow reverse proxy" ;;
        *mlflow-api*) DESC="MLflow API service" ;;
        *mlflow-prometheus*) DESC="MLflow metrics collector" ;;
        *authentik-server*) DESC="OAuth/SSO server" ;;
        *authentik-worker*) DESC="Authentik background worker" ;;
        *authentik-postgres*) DESC="Authentik database" ;;
        *authentik-redis*) DESC="Authentik cache" ;;
        *shared-postgres*) DESC="Shared PostgreSQL database" ;;
        *redis*) DESC="Platform cache" ;;
        *traefik*) DESC="API gateway/reverse proxy" ;;
        *global-prometheus*) DESC="Global metrics collector (90d)" ;;
        *grafana*) DESC="This Grafana instance" ;;
        *dcgm*) DESC="GPU metrics collector" ;;
        *cadvisor*) DESC="Container metrics collector" ;;
        *node-exporter*) DESC="System metrics collector" ;;
        *) DESC="Service component" ;;
    esac

    CONTAINER_TABLE="${CONTAINER_TABLE}\n| **${CONTAINER_ID}** | ${CONTAINER_NAME} | ${DESC} |"
done < <(sudo docker ps --format "{{.ID}} {{.Names}}" | sort -k2)

CONTAINER_TABLE="${CONTAINER_TABLE}\n\n**Note:** Container IDs remain constant until the container is recreated. This table shows the current running containers. Run this script to refresh after container restarts."

# Create a temporary file with the updated content
TEMP_FILE=$(mktemp)

# Temporarily change ownership to allow reading
sudo chown $(id -u):$(id -g) "${DASHBOARD_FILE}"

# Use Python to update the JSON while preserving structure
python3 << EOF
import json
import sys

# Read the dashboard
with open("${DASHBOARD_FILE}", "r") as f:
    dashboard = json.load(f)

# Find the reference panel (id=100) and update its content
for panel in dashboard.get("panels", []):
    if panel.get("id") == 100 and panel.get("type") == "text":
        panel["options"]["content"] = """${CONTAINER_TABLE}"""
        print(f"✓ Updated reference panel")
        break

# Write back
with open("${TEMP_FILE}", "w") as f:
    json.dump(dashboard, f, indent=2)

print(f"✓ Dashboard updated")
EOF

# Move the temp file to the dashboard location
sudo mv "$TEMP_FILE" "$DASHBOARD_FILE"
sudo chown 472:472 "$DASHBOARD_FILE"

echo "✓ Container reference table updated"
echo ""
echo "Restart Grafana to see changes:"
echo "  sudo docker restart unified-grafana"
