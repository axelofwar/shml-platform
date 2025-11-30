#!/bin/bash
# Start inference stack
# Integrates with existing ml-platform without disrupting other services

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFERENCE_DIR="$(dirname "$SCRIPT_DIR")"

echo "=========================================="
echo "Starting Inference Stack"
echo "=========================================="

# Check if ml-platform network exists
if ! docker network inspect ml-platform &> /dev/null; then
    echo "ERROR: ml-platform network not found."
    echo "Start the main platform first: ./start_all_safe.sh"
    exit 1
fi

# Check if Redis is running
if ! docker ps | grep -q ml-platform-redis; then
    echo "ERROR: ml-platform-redis not running."
    echo "Start the main platform first: ./start_all_safe.sh"
    exit 1
fi

# Create secrets directory and password if needed
mkdir -p "$INFERENCE_DIR/secrets"
if [ ! -f "$INFERENCE_DIR/secrets/inference_db_password.txt" ]; then
    echo "Generating inference database password..."
    openssl rand -base64 32 > "$INFERENCE_DIR/secrets/inference_db_password.txt"
fi

# Create log directories
mkdir -p "$INFERENCE_DIR/logs/qwen3-vl"
mkdir -p "$INFERENCE_DIR/logs/z-image"
mkdir -p "$INFERENCE_DIR/logs/gateway"
mkdir -p "$INFERENCE_DIR/backups"

# Check if models are downloaded
if [ ! -d "$INFERENCE_DIR/data/models/Qwen" ]; then
    echo "WARNING: Models not found. Run scripts/download_models.sh first."
    echo "         Containers will fail to start without models."
    read -p "Continue anyway? (y/N): " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        exit 1
    fi
fi

echo ""
echo "Phase 1: Starting PostgreSQL..."
docker compose -f "$INFERENCE_DIR/docker-compose.inference.yml" up -d inference-postgres
sleep 5

echo ""
echo "Phase 2: Starting Qwen3-VL (RTX 2070)..."
docker compose -f "$INFERENCE_DIR/docker-compose.inference.yml" up -d qwen3-vl-api

echo ""
echo "Phase 3: Starting Z-Image (RTX 3090, on-demand)..."
docker compose -f "$INFERENCE_DIR/docker-compose.inference.yml" up -d z-image-api

echo ""
echo "Phase 4: Starting Gateway..."
docker compose -f "$INFERENCE_DIR/docker-compose.inference.yml" up -d inference-gateway

echo ""
echo "=========================================="
echo "Inference Stack Started"
echo "=========================================="
echo ""
echo "Endpoints (via Traefik):"
echo "  LLM:     http://localhost/api/llm/v1/chat/completions"
echo "  Image:   http://localhost/api/image/v1/generate"
echo "  Gateway: http://localhost/inference/health"
echo ""
echo "Note: First request may take 2-5 minutes (model loading)"
echo ""
echo "Check status: docker compose -f inference/docker-compose.inference.yml ps"
