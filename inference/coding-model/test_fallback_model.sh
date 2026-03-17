#!/bin/bash
# Test Fallback Model Upgrade Script
# ==================================
# This script safely tests a new fallback model WITHOUT affecting:
# - The primary model container
# - Any running training jobs on GPU 0
#
# Usage:
#   ./test_fallback_model.sh [model_id] [max_context]
#
# Examples:
#   ./test_fallback_model.sh  # Use default (DeepSeek-Coder-6.7B-AWQ)
#   ./test_fallback_model.sh "TheBloke/deepseek-coder-6.7B-instruct-AWQ" 4096
#   ./test_fallback_model.sh "Qwen/Qwen2.5-Coder-7B-Instruct-AWQ" 2048

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
MODEL_ID="${1:-TheBloke/deepseek-coder-6.7B-instruct-AWQ}"
MAX_CONTEXT="${2:-4096}"
CONTAINER_NAME="coding-model-fallback"
COMPOSE_FILE="deploy/compose/docker-compose.yml"

echo -e "${YELLOW}=== Fallback Model Test Script ===${NC}"
echo ""
echo "Target model: $MODEL_ID"
echo "Max context: $MAX_CONTEXT"
echo ""

# Step 1: Check training status
echo -e "${YELLOW}Step 1: Checking training status...${NC}"
TRAINING_STATUS=$(docker exec ray-head ray job list 2>/dev/null | grep -c "RUNNING" || echo "0")
if [ "$TRAINING_STATUS" -gt 0 ]; then
    echo -e "${GREEN}✓ Training job is running on GPU 0 - it will NOT be affected${NC}"
else
    echo -e "${YELLOW}! No training job detected${NC}"
fi
echo ""

# Step 2: Check primary model status
echo -e "${YELLOW}Step 2: Checking primary model...${NC}"
PRIMARY_HEALTH=$(docker exec coding-model-primary curl -sf http://localhost:8000/health 2>/dev/null || echo "unhealthy")
if echo "$PRIMARY_HEALTH" | grep -q "healthy"; then
    echo -e "${GREEN}✓ Primary model is healthy - it will NOT be restarted${NC}"
else
    echo -e "${YELLOW}! Primary model is yielded (expected during training)${NC}"
fi
echo ""

# Step 3: Check current fallback model
echo -e "${YELLOW}Step 3: Current fallback model status...${NC}"
CURRENT_MODEL=$(docker exec $CONTAINER_NAME curl -sf http://localhost:8000/health 2>/dev/null | grep -o '"model_id":"[^"]*"' | cut -d'"' -f4 || echo "unknown")
echo "Current model: $CURRENT_MODEL"
echo ""

# Step 4: Check GPU 1 memory
echo -e "${YELLOW}Step 4: GPU 1 memory status...${NC}"
GPU1_MEM=$(nvidia-smi -i 1 --query-gpu=memory.used,memory.total --format=csv,noheader,nounits)
echo "GPU 1 memory: $GPU1_MEM MiB"
echo ""

# Confirmation
echo -e "${RED}=== IMPORTANT ===${NC}"
echo "This will:"
echo "  1. Stop ONLY the fallback container ($CONTAINER_NAME)"
echo "  2. Update its MODEL_ID to: $MODEL_ID"
echo "  3. Update MAX_MODEL_LEN to: $MAX_CONTEXT"
echo "  4. Restart the fallback container"
echo ""
echo "This will NOT touch:"
echo "  - coding-model-primary (will stay exactly as is)"
echo "  - Ray training jobs (training continues uninterrupted)"
echo "  - GPU 0 (3090 Ti)"
echo ""
read -p "Proceed? (y/N): " confirm

if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo -e "${YELLOW}Step 5: Stopping fallback container...${NC}"
docker stop $CONTAINER_NAME 2>/dev/null || true
docker rm $CONTAINER_NAME 2>/dev/null || true
echo -e "${GREEN}✓ Fallback container stopped${NC}"
echo ""

# Step 6: Start with new model
echo -e "${YELLOW}Step 6: Starting fallback with new model...${NC}"
echo "Model: $MODEL_ID"
echo "Context: $MAX_CONTEXT"

# Create temporary override for docker-compose
cat > /tmp/fallback-override.yml << EOF
services:
  coding-model-fallback:
    environment:
      - MODEL_ID=$MODEL_ID
      - MAX_MODEL_LEN=$MAX_CONTEXT
      - GPU_MEMORY_UTILIZATION=0.85
EOF

# Start only the fallback service
cd "$(dirname "$0")"
docker compose -f $COMPOSE_FILE -f /tmp/fallback-override.yml up -d coding-model-fallback

echo ""
echo -e "${YELLOW}Step 7: Waiting for model to load...${NC}"
echo "This may take 2-5 minutes for first download..."

# Wait for health check
MAX_WAIT=300
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    HEALTH=$(docker exec $CONTAINER_NAME curl -sf http://localhost:8000/health 2>/dev/null || echo "")
    if echo "$HEALTH" | grep -q '"status":"healthy"'; then
        echo ""
        echo -e "${GREEN}✓ New model loaded successfully!${NC}"
        echo "$HEALTH" | python3 -m json.tool 2>/dev/null || echo "$HEALTH"
        break
    fi
    echo -n "."
    sleep 5
    WAITED=$((WAITED + 5))
done

if [ $WAITED -ge $MAX_WAIT ]; then
    echo ""
    echo -e "${RED}✗ Timeout waiting for model to load${NC}"
    echo "Check logs: docker logs $CONTAINER_NAME"
    exit 1
fi

# Step 8: Quick inference test
echo ""
echo -e "${YELLOW}Step 8: Testing inference...${NC}"
RESPONSE=$(docker exec $CONTAINER_NAME curl -sf http://localhost:8000/v1/completions \
    -H "Content-Type: application/json" \
    -d '{
        "model": "'"$MODEL_ID"'",
        "prompt": "def fibonacci(n):",
        "max_tokens": 50,
        "temperature": 0.1
    }' 2>/dev/null || echo "FAILED")

if echo "$RESPONSE" | grep -q '"text"'; then
    echo -e "${GREEN}✓ Inference test passed!${NC}"
    echo "Response preview:"
    echo "$RESPONSE" | python3 -c "import json,sys; r=json.load(sys.stdin); print(r['choices'][0]['text'][:200])" 2>/dev/null || echo "$RESPONSE"
else
    echo -e "${RED}✗ Inference test failed${NC}"
    echo "$RESPONSE"
fi

# Step 9: Final status
echo ""
echo -e "${YELLOW}=== Final Status ===${NC}"
echo ""
nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv
echo ""
echo "To revert to original model:"
echo "  docker compose up -d coding-model-fallback"
echo ""
echo "To check logs:"
echo "  docker logs -f $CONTAINER_NAME"
