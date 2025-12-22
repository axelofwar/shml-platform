#!/bin/bash
# Container Name Metrics Exporter
# Generates Prometheus metrics file mapping container short IDs to names
# Run this periodically or after container restarts

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
METRICS_FILE="${SCRIPT_DIR}/../monitoring/prometheus/container_names.prom"
TEXTFILE_DIR="${SCRIPT_DIR}/../monitoring/prometheus"

# Ensure directory exists
mkdir -p "$TEXTFILE_DIR"

# Generate metrics with container name labels
echo "# HELP container_info Container information with name label" > "${METRICS_FILE}.tmp"
echo "# TYPE container_info gauge" >> "${METRICS_FILE}.tmp"

# Get all running containers
docker ps --format '{{.ID}} {{.Names}}' | while read -r full_id name; do
    short_id="${full_id:0:12}"
    # Create a metric with both short_id and name as labels
    echo "container_info{container_short_id=\"${short_id}\",container_name=\"${name}\"} 1" >> "${METRICS_FILE}.tmp"
done

# Atomic move
mv "${METRICS_FILE}.tmp" "${METRICS_FILE}"

echo "Generated container name metrics at ${METRICS_FILE}"
echo "Containers mapped: $(grep -c 'container_info{' "$METRICS_FILE" || echo 0)"
