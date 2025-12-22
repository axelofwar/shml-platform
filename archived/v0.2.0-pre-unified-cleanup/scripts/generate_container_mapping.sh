#!/bin/bash
# Container ID to Name Mapping Generator
# This script generates a Prometheus file_sd config that maps container IDs to names
# Run this periodically (e.g., every 30 seconds) to keep mappings fresh after restarts

set -e

OUTPUT_DIR="${1:-/home/axelofwar/Projects/shml-platform/monitoring/prometheus}"
OUTPUT_FILE="${OUTPUT_DIR}/container_id_mapping.json"

# Ensure output directory exists
mkdir -p "$OUTPUT_DIR"

# Generate mapping from running containers
echo "Generating container ID to name mapping..."

# Get all running containers and create a mapping
MAPPING=$(docker ps --format '{{.ID}} {{.Names}}' | while read id name; do
    # Get full container ID
    full_id=$(docker inspect --format '{{.Id}}' "$id" 2>/dev/null || echo "")
    if [ -n "$full_id" ]; then
        echo "{\"targets\": [\"cadvisor:8080\"], \"labels\": {\"container_id\": \"$full_id\", \"container_name\": \"$name\", \"short_id\": \"$id\"}}"
    fi
done | paste -sd ',')

# Write to file
echo "[${MAPPING}]" > "$OUTPUT_FILE"

echo "Generated mapping for $(docker ps -q | wc -l) containers at $OUTPUT_FILE"

# Also generate a simple key-value format for Grafana
docker ps --format '{{.ID}}={{.Names}}' > "${OUTPUT_DIR}/container_names.txt"
echo "Also saved to ${OUTPUT_DIR}/container_names.txt"
