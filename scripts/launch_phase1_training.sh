#!/bin/bash
# Phase 1 Foundation Training - Launch Script
# YOLOv8-L on WIDER Face with all SOTA features

set -e

echo "╔══════════════════════════════════════════════════════════════════════════════╗"
echo "║                                                                              ║"
echo "║                   PHASE 1 FOUNDATION TRAINING LAUNCH                         ║"
echo "║                                                                              ║"
echo "║                   YOLOv8-L + WIDER Face + SOTA Features                      ║"
echo "║                                                                              ║"
echo "╚══════════════════════════════════════════════════════════════════════════════╝"
echo ""

PROJECT_ROOT="/home/axelofwar/Projects/shml-platform"
cd "$PROJECT_ROOT"

# Parse arguments
OPTION="${1:-balanced}"  # balanced, recall-focused, test
EPOCHS="${2:-200}"
DRY_RUN="${DRY_RUN:-false}"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PRE-FLIGHT CHECKS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check GPU availability
echo "1. GPU Availability:"
if nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader,nounits | grep -q "3090"; then
    GPU_INFO=$(nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader,nounits | grep "3090")
    echo "  ✓ $GPU_INFO"
    GPU_FREE=$(echo "$GPU_INFO" | awk -F',' '{print $3}')
    if [ "$GPU_FREE" -lt 20000 ]; then
        echo "  ⚠ Warning: Only ${GPU_FREE} MB free (need 20+ GB for Phase 3)"
        echo "  Consider freeing GPU memory before training"
    fi
else
    echo "  ✗ RTX 3090 Ti not found!"
    exit 1
fi
echo ""

# Check Ray container
echo "2. Ray Container:"
if docker ps | grep -q ray-head; then
    echo "  ✓ Ray head container running"
    RAY_MEM=$(docker inspect ray-head --format='{{.HostConfig.Memory}}' | awk '{print $1/1024/1024/1024}')
    echo "  ✓ Container memory limit: ${RAY_MEM} GB"
else
    echo "  ✗ Ray head container not running!"
    echo "  Start with: ./start_all_safe.sh start ray"
    exit 1
fi
echo ""

# Check MLflow connectivity
echo "3. MLflow Server:"
if curl -sf http://localhost:8080/api/2.0/mlflow/experiments/list > /dev/null 2>&1; then
    echo "  ✓ MLflow server accessible"
else
    echo "  ⚠ MLflow server not accessible (will run offline)"
fi
echo ""

# Check disk space
echo "4. Disk Space:"
DISK_FREE=$(df -BG "$PROJECT_ROOT" | tail -1 | awk '{print $4}' | tr -d 'G')
if [ "$DISK_FREE" -gt 50 ]; then
    echo "  ✓ ${DISK_FREE} GB free (sufficient)"
else
    echo "  ⚠ Warning: Only ${DISK_FREE} GB free (need 50+ GB recommended)"
fi
echo ""

# Check dataset
echo "5. WIDER Face Dataset:"
if [ -d "$PROJECT_ROOT/ray_compute/data/datasets/wider_face/WIDER_train" ]; then
    IMG_COUNT=$(find "$PROJECT_ROOT/ray_compute/data/datasets/wider_face/WIDER_train" -name "*.jpg" | wc -l)
    echo "  ✓ Dataset found (${IMG_COUNT} training images)"
else
    echo "  ⚠ Dataset not found - will download automatically"
    DOWNLOAD_FLAG="--download-dataset"
fi
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "TRAINING CONFIGURATION"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

RUN_DATE=$(date +%Y%m%d-%H%M%S)

case "$OPTION" in
    "balanced")
        echo "Mode: Balanced (Recommended)"
        echo "  Target: 80-85% recall, 200 epochs, ~60-72 hours"
        echo "  Expected mAP50: 75-80%"
        echo "  Expected Recall: 80-85%"
        echo ""

        TRAIN_CMD="python ray_compute/jobs/training/phase1_foundation.py \
            ${DOWNLOAD_FLAG:-} \
            --epochs $EPOCHS \
            --batch-size 4 \
            --imgsz 1280 \
            --device cuda:0 \
            --experiment Phase1-WIDER-Balanced \
            --run-name yolov8l-${EPOCHS}ep-sota-${RUN_DATE} \
            --workers 8"
        ;;

    "recall-focused")
        echo "Mode: Recall-Focused (Maximum Recall)"
        echo "  Target: 85-88% recall, 250 epochs, ~75-90 hours"
        echo "  Expected mAP50: 72-78%"
        echo "  Expected Recall: 85-88%"
        echo ""

        TRAIN_CMD="python ray_compute/jobs/training/phase1_foundation.py \
            ${DOWNLOAD_FLAG:-} \
            --epochs ${EPOCHS:-250} \
            --batch-size 4 \
            --imgsz 1280 \
            --device cuda:0 \
            --recall-focused \
            --experiment Phase1-WIDER-RecallMax \
            --run-name yolov8l-${EPOCHS:-250}ep-recall-${RUN_DATE} \
            --conf-threshold 0.15 \
            --iou-threshold 0.50 \
            --copy-paste 0.3 \
            --scale 0.9 \
            --phase-3-ratio 0.50 \
            --workers 8"
        ;;

    "test")
        echo "Mode: Quick Validation (Testing)"
        echo "  Target: Validate pipeline, 50 epochs, ~15 hours"
        echo "  Purpose: Verify no OOM, test SOTA features"
        echo ""

        TRAIN_CMD="python ray_compute/jobs/training/phase1_foundation.py \
            ${DOWNLOAD_FLAG:-} \
            --epochs 50 \
            --batch-size 4 \
            --imgsz 1280 \
            --device cuda:0 \
            --experiment Phase1-WIDER-Test \
            --run-name yolov8l-50ep-validation-${RUN_DATE} \
            --workers 8"
        ;;

    *)
        echo "❌ Invalid option: $OPTION"
        echo ""
        echo "Usage: $0 [balanced|recall-focused|test] [epochs]"
        echo ""
        echo "Examples:"
        echo "  $0 balanced 200           # Recommended (60-72 hours)"
        echo "  $0 recall-focused 250     # Maximum recall (75-90 hours)"
        echo "  $0 test 50                # Quick validation (12-15 hours)"
        echo ""
        exit 1
        ;;
esac

echo "SOTA Features Enabled:"
echo "  ✓ YOLOv8-L Pretrained (lindevs face model)"
echo "  ✓ Multi-Scale Training (640→960→1280px)"
echo "  ✓ Curriculum Learning (4 stages)"
echo "  ✓ SAPO Optimizer (adaptive LR)"
echo "  ✓ Hard Negative Mining"
echo "  ✓ Online Advantage Filtering"
echo "  ✓ Enhanced Multi-Scale (up to 1536px)"
echo "  ✓ Failure Analysis (every 10 epochs)"
echo "  ✓ Dataset Quality Audit"
echo "  ✓ TTA Validation"
echo "  ✓ EMA (Exponential Moving Average) [NEW]"
echo ""

echo "Hardware Configuration:"
echo "  GPU: RTX 3090 Ti (24 GB VRAM)"
echo "  Batch Sizes: Phase1=8, Phase2=4, Phase3=2"
echo "  Gradient Accumulation: 4 steps (effective batch=16)"
echo "  Workers: 8 parallel data loaders"
echo "  AMP: Enabled (mixed precision)"
echo ""

if [ "$DRY_RUN" = "true" ]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "DRY RUN - Command that would execute:"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "$TRAIN_CMD"
    echo ""
    exit 0
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PARALLEL TASKS TO START"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "While training runs (~60 hours), work on these in parallel:"
echo ""
echo "1. YFCC100M Downloader (Week 2)"
echo "   cd ray_compute/jobs/annotation"
echo "   vim yfcc100m_downloader.py"
echo ""
echo "2. SAM2 Installation (Week 2)"
echo "   git clone https://github.com/facebookresearch/segment-anything-2.git"
echo "   cd segment-anything-2 && pip install -e ."
echo ""
echo "3. MLflow Model Registry (Week 2)"
echo "   Setup automated model registration"
echo ""
echo "4. Grafana Dashboard Verification"
echo "   Check: http://localhost:3001/d/face-detection"
echo ""
echo "5. Evaluation Pipeline Testing"
echo "   Test wider_face_eval.py on checkpoints"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
read -p "Launch training? (yes/no): " -n 3 -r
echo ""

if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    echo "❌ Training cancelled"
    exit 0
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 LAUNCHING PHASE 1 TRAINING"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Training will run for approximately $(echo "$EPOCHS * 0.3" | bc) hours"
echo ""
echo "Monitor progress:"
echo "  MLflow:  http://localhost:8080"
echo "  Grafana: http://localhost:3001/d/face-detection"
echo "  Logs:    tail -f logs/phase1_training_${RUN_DATE}.log"
echo ""
echo "To cancel: Ctrl+C (graceful shutdown will save checkpoint)"
echo ""

# Create log directory
mkdir -p logs

# Execute training command
echo "Executing: $TRAIN_CMD"
echo ""

eval "$TRAIN_CMD" 2>&1 | tee "logs/phase1_training_${RUN_DATE}.log"

EXIT_CODE=$?

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ TRAINING COMPLETED SUCCESSFULLY"
else
    echo "❌ TRAINING FAILED (exit code: $EXIT_CODE)"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ $EXIT_CODE -eq 0 ]; then
    echo "Next steps:"
    echo "  1. Evaluate model:"
    echo "     python ray_compute/jobs/evaluation/wider_face_eval.py --weights best.pt"
    echo ""
    echo "  2. Export models:"
    echo "     python ray_compute/jobs/training/phase1_foundation.py --export-only --weights best.pt"
    echo ""
    echo "  3. Review failure analysis:"
    echo "     cat /tmp/ray/checkpoints/face_detection/*/failure_analysis_*.json"
    echo ""
    echo "  4. Check MLflow:"
    echo "     open http://localhost:8080/#/experiments/Phase1-WIDER-Balanced"
    echo ""
fi

exit $EXIT_CODE
