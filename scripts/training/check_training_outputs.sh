#!/bin/bash
# Check training outputs and checkpoint locations
# Usage: ./check_training_outputs.sh [job_id]

set -e

JOB_ID=${1:-"latest"}
HOST_CHECKPOINT_DIR="${PLATFORM_ROOT:-.}/ray_compute/data/ray/checkpoints"
CONTAINER_CHECKPOINT_DIR="/tmp/ray/checkpoints"

echo "╔════════════════════════════════════════════════════════╗"
echo "║         Training Outputs & Checkpoint Locations        ║"
echo "╚════════════════════════════════════════════════════════╝"

echo ""
echo "━━━ Host Machine Checkpoints ━━━"
if [ -d "$HOST_CHECKPOINT_DIR" ]; then
    echo "Location: $HOST_CHECKPOINT_DIR"
    echo ""
    find "$HOST_CHECKPOINT_DIR" -type f -name "*.pt" -o -name "*.json" | head -20
    echo ""
    du -sh "$HOST_CHECKPOINT_DIR"/* 2>/dev/null || echo "No checkpoints found"
else
    echo "⚠ Directory not found: $HOST_CHECKPOINT_DIR"
fi

echo ""
echo "━━━ Container Checkpoints ━━━"
echo "Location: $CONTAINER_CHECKPOINT_DIR"
echo ""
docker exec ray-head find "$CONTAINER_CHECKPOINT_DIR" -type f -name "*.pt" -o -name "*.json" 2>/dev/null | head -20 || echo "⚠ No checkpoints in container"

echo ""
echo "━━━ Latest Checkpoint Details ━━━"
docker exec ray-head ls -lah "$CONTAINER_CHECKPOINT_DIR/face_detection/" 2>/dev/null || echo "⚠ No face_detection directory"

echo ""
echo "━━━ Curriculum Progress ━━━"
docker exec ray-head cat "$CONTAINER_CHECKPOINT_DIR/face_detection/curriculum_progress.json" 2>/dev/null | jq '.' || echo "⚠ No curriculum progress file"

echo ""
echo "━━━ Epoch Summary ━━━"
docker exec ray-head cat "$CONTAINER_CHECKPOINT_DIR/face_detection/epoch_summary.json" 2>/dev/null | jq '.' || echo "⚠ No epoch summary file"

echo ""
echo "━━━ MLflow Artifacts ━━━"
MLFLOW_ARTIFACTS="/mlflow/artifacts"
docker exec ray-head find "$MLFLOW_ARTIFACTS" -type f -name "*.pt" -mtime -1 2>/dev/null | head -10 || echo "⚠ No recent MLflow artifacts"

echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║         Access Commands                                 ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""
echo "  View host checkpoints:"
echo "    ls -lah $HOST_CHECKPOINT_DIR/face_detection/"
echo ""
echo "  View container checkpoints:"
echo "    docker exec ray-head ls -lah $CONTAINER_CHECKPOINT_DIR/face_detection/"
echo ""
echo "  Copy checkpoint to current directory:"
echo "    docker cp ray-head:$CONTAINER_CHECKPOINT_DIR/face_detection/phase_1_*/weights/best.pt ./best_phase1.pt"
echo ""
echo "  Monitor training:"
echo "    docker exec ray-head tail -f $CONTAINER_CHECKPOINT_DIR/face_detection/epoch_table.txt"
echo ""
