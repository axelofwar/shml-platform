#!/bin/bash
# ============================================================================
# SHML Face Detection Training - Recall Focused v2
# ============================================================================
# Submit a new training job with recall-optimized configuration.
#
# Prerequisites:
# - Previous training completed (job-2a587dc74743)
# - Checkpoint available at: /tmp/ray/checkpoints/face_detection/phase_3_phase_3/weights/best.pt
#
# Usage:
#   ./submit_recall_training_v2.sh                    # Full training from scratch
#   ./submit_recall_training_v2.sh --resume           # Resume from Phase 3 checkpoint
#   ./submit_recall_training_v2.sh --fine-tune        # Fine-tune only (Phase 3)
#   ./submit_recall_training_v2.sh --evaluate-first   # Evaluate then train
#
# Created: 2025-12-11
# Target: mAP50 > 94%, Recall > 95%
# ============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Default settings
MODE="full"
CHECKPOINT_PATH=""
EPOCHS=100

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --resume)
            MODE="resume"
            shift
            ;;
        --fine-tune)
            MODE="finetune"
            EPOCHS=50  # Shorter for fine-tuning
            shift
            ;;
        --checkpoint)
            CHECKPOINT_PATH="$2"
            shift 2
            ;;
        --evaluate-first)
            MODE="eval-then-train"
            shift
            ;;
        --epochs)
            EPOCHS="$2"
            shift 2
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

echo -e "${BLUE}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     SHML Face Detection Training - Recall Focused v2         ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check if previous training is still running
echo -e "${YELLOW}Checking for active training jobs...${NC}"
ACTIVE_JOBS=$(docker exec ray-head ray job list 2>/dev/null | grep -E "RUNNING|PENDING" | wc -l || echo "0")

if [[ "$ACTIVE_JOBS" -gt 0 ]]; then
    echo -e "${RED}⚠️  Active training jobs detected!${NC}"
    docker exec ray-head ray job list 2>/dev/null | grep -E "RUNNING|PENDING" || true
    echo ""
    echo -e "${YELLOW}Options:${NC}"
    echo "  1. Wait for current training to complete"
    echo "  2. Cancel current job: docker exec ray-head ray job stop <job_id>"
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Find best checkpoint
if [[ -z "$CHECKPOINT_PATH" ]]; then
    CHECKPOINT_PATH="/tmp/ray/checkpoints/face_detection/phase_3_phase_3/weights/best.pt"
    LOCAL_CHECKPOINT="$PROJECT_ROOT/ray_compute/data/ray/checkpoints/face_detection/phase_3_phase_3/weights/best.pt"

    if [[ -f "$LOCAL_CHECKPOINT" ]]; then
        echo -e "${GREEN}✓ Found checkpoint: $LOCAL_CHECKPOINT${NC}"
    else
        echo -e "${YELLOW}⚠️  No local checkpoint found. Will use default pretrained model.${NC}"
        CHECKPOINT_PATH=""
    fi
fi

# Build job arguments based on mode
echo -e "${BLUE}Mode: ${MODE}${NC}"
echo -e "${BLUE}Epochs: ${EPOCHS}${NC}"

EXTRA_ARGS=""
case $MODE in
    full)
        echo -e "${GREEN}Running full training from scratch with recall-focused config${NC}"
        EXTRA_ARGS="--epochs $EPOCHS"
        ;;
    resume)
        echo -e "${GREEN}Resuming from checkpoint: $CHECKPOINT_PATH${NC}"
        EXTRA_ARGS="--resume $CHECKPOINT_PATH --epochs $EPOCHS"
        ;;
    finetune)
        echo -e "${GREEN}Fine-tuning Phase 3 only from checkpoint${NC}"
        EXTRA_ARGS="--start-phase 3 --resume $CHECKPOINT_PATH --epochs $EPOCHS"
        ;;
    eval-then-train)
        echo -e "${GREEN}Running evaluation first, then training${NC}"
        # Run evaluation first
        echo -e "${YELLOW}Running evaluation...${NC}"
        bash "$SCRIPT_DIR/run_evaluation.sh" --model "$LOCAL_CHECKPOINT" || true
        EXTRA_ARGS="--epochs $EPOCHS"
        ;;
esac

# Key recall-focused hyperparameters
echo ""
echo -e "${BLUE}━━━ Recall-Focused Configuration ━━━${NC}"
echo -e "  copy_paste:     ${GREEN}0.3${NC} (was 0.0) - dense scene training"
echo -e "  scale:          ${GREEN}0.9${NC} (was 0.5) - more scale variation"
echo -e "  box_loss:       ${GREEN}10.0${NC} (was 7.5) - better localization"
echo -e "  cls_loss:       ${GREEN}0.3${NC} (was 0.5) - less FP penalty"
echo -e "  conf_threshold: ${GREEN}0.15${NC} (was 0.25) - catch more faces"
echo -e "  Phase 3:        ${GREEN}50%${NC} of epochs (was 35%)"
echo ""

# Confirm before submitting
echo -e "${YELLOW}Ready to submit training job?${NC}"
read -p "Press Enter to continue or Ctrl+C to cancel..."

# Submit job
echo -e "${BLUE}Submitting training job...${NC}"

JOB_ID=$(docker exec ray-head ray job submit \
    --working-dir /opt/ray/job_workspaces \
    --runtime-env-json '{"env_vars": {"MLFLOW_TRACKING_URI": "http://mlflow-nginx:80"}}' \
    -- python face_detection_training.py \
        --model yolov8l-face-lindevs.pt \
        --imgsz 1280 \
        --download-dataset \
        --copy-paste 0.3 \
        --scale 0.9 \
        --box-loss 10.0 \
        --cls-loss 0.3 \
        --conf-threshold 0.15 \
        --mixup 0.2 \
        --phase-3-ratio 0.50 \
        --mlflow-experiment "face_detection_recall_v2" \
        $EXTRA_ARGS 2>&1 | grep -oP "Job '\K[^']+")

if [[ -n "$JOB_ID" ]]; then
    echo -e "${GREEN}✓ Training job submitted successfully!${NC}"
    echo -e "  Job ID: ${BLUE}$JOB_ID${NC}"
    echo ""
    echo -e "${YELLOW}Monitor training:${NC}"
    echo "  docker exec ray-head ray job logs $JOB_ID --follow"
    echo ""
    echo -e "${YELLOW}Check status:${NC}"
    echo "  docker exec ray-head ray job status $JOB_ID"
    echo ""
    echo -e "${YELLOW}Stop if needed:${NC}"
    echo "  docker exec ray-head ray job stop $JOB_ID"
else
    echo -e "${RED}Failed to submit job. Check Ray cluster status.${NC}"
    exit 1
fi
