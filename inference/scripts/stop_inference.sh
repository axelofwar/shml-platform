#!/bin/bash
# Stop inference stack without affecting main platform

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFERENCE_DIR="$(dirname "$SCRIPT_DIR")"

echo "Stopping Inference Stack..."
docker compose -f "$INFERENCE_DIR/docker-compose.inference.yml" down

echo "Inference stack stopped."
echo "Main platform (MLflow, Ray, etc.) is unaffected."
