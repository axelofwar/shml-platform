#!/bin/bash
################################################################################
# Face Detection Model Evaluation Runner
################################################################################
#
# PURPOSE: Run face detection model evaluation with proper environment setup.
#
# USAGE:
#   ./run_evaluation.sh                    # Use default settings
#   ./run_evaluation.sh --model phase_2    # Evaluate phase 2 checkpoint
#   ./run_evaluation.sh --device cuda:1    # Use RTX 2070
#
# OUTPUTS:
#   - Evaluation report (JSON + Markdown)
#   - Metrics CSV
#   - MLflow tracking
#   - Console summary
#
# Author: SHML Platform Team
# Date: December 2025
################################################################################

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Project root
PROJECT_ROOT="${PLATFORM_ROOT:-.}"
SCRIPT_DIR="$PROJECT_ROOT/ray_compute/scripts"
JOBS_DIR="$PROJECT_ROOT/ray_compute/jobs"
CHECKPOINTS_DIR="$PROJECT_ROOT/ray_compute/data/ray/checkpoints/face_detection"
OUTPUT_DIR="$PROJECT_ROOT/ray_compute/evaluation_results"

# Default settings
MODEL_CHECKPOINT="phase_3_phase_3"  # Latest curriculum learning phase
DEVICE="cuda:0"  # RTX 3090 Ti for evaluation
BATCH_SIZE=16
IMAGE_SIZE=1280

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --model)
            MODEL_CHECKPOINT="$2"
            shift 2
            ;;
        --device)
            DEVICE="$2"
            shift 2
            ;;
        --batch-size)
            BATCH_SIZE="$2"
            shift 2
            ;;
        --image-size)
            IMAGE_SIZE="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --model CHECKPOINT      Model checkpoint to evaluate (default: phase_3_phase_3)"
            echo "  --device DEVICE         Device for evaluation (default: cuda:0)"
            echo "  --batch-size SIZE       Batch size (default: 16)"
            echo "  --image-size SIZE       Image size (default: 1280)"
            echo "  --help                  Show this help message"
            echo ""
            echo "Available checkpoints:"
            find "$CHECKPOINTS_DIR" -maxdepth 1 -type d | grep -v "^$CHECKPOINTS_DIR$" | xargs -I {} basename {}
            exit 0
            ;;
        *)
            echo -e "${RED}❌ Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Banner
echo -e "${BLUE}"
echo "╔════════════════════════════════════════════════════════════════════════════╗"
echo "║                   FACE DETECTION MODEL EVALUATION                          ║"
echo "║                         SHML Platform v0.2.0                               ║"
echo "╚════════════════════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Configuration
MODEL_PATH="$CHECKPOINTS_DIR/$MODEL_CHECKPOINT/weights/best.pt"

echo -e "${YELLOW}📋 Configuration:${NC}"
echo "   Model:      $MODEL_CHECKPOINT"
echo "   Path:       $MODEL_PATH"
echo "   Device:     $DEVICE"
echo "   Batch Size: $BATCH_SIZE"
echo "   Image Size: ${IMAGE_SIZE}px"
echo "   Output:     $OUTPUT_DIR"
echo ""

# Validate model exists
if [ ! -f "$MODEL_PATH" ]; then
    echo -e "${RED}❌ Model checkpoint not found: $MODEL_PATH${NC}"
    echo ""
    echo "Available checkpoints:"
    find "$CHECKPOINTS_DIR" -maxdepth 1 -type d | grep -v "^$CHECKPOINTS_DIR$" | while read -r dir; do
        checkpoint=$(basename "$dir")
        if [ -f "$dir/weights/best.pt" ]; then
            echo -e "  ${GREEN}✅ $checkpoint${NC}"
        else
            echo -e "  ${RED}❌ $checkpoint (best.pt missing)${NC}"
        fi
    done
    exit 1
fi

# Check GPU availability
echo -e "${YELLOW}🔍 Checking GPU availability...${NC}"
if command -v nvidia-smi &> /dev/null; then
    nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader
    echo ""
else
    echo -e "${RED}⚠️ nvidia-smi not found - GPU may not be available${NC}"
fi

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Activate virtual environment if exists
if [ -d "$PROJECT_ROOT/venv" ]; then
    echo -e "${YELLOW}🐍 Activating virtual environment...${NC}"
    source "$PROJECT_ROOT/venv/bin/activate"
fi

# Check Python dependencies
echo -e "${YELLOW}📦 Checking dependencies...${NC}"
python3 -c "import torch; print(f'   PyTorch: {torch.__version__}')"
python3 -c "import ultralytics; print(f'   Ultralytics: {ultralytics.__version__}')"
python3 -c "import mlflow; print(f'   MLflow: {mlflow.__version__}')" 2>/dev/null || echo "   MLflow: Not installed (optional)"
echo ""

# Run evaluation
echo -e "${GREEN}🚀 Starting evaluation...${NC}"
echo ""

cd "$PROJECT_ROOT"

python3 "$JOBS_DIR/evaluate_face_detection.py" \
    --model "$MODEL_PATH" \
    --dataset-root "$PROJECT_ROOT/data" \
    --output-dir "$OUTPUT_DIR" \
    --device "$DEVICE" \
    --batch-size "$BATCH_SIZE" \
    --image-size "$IMAGE_SIZE"

EXIT_CODE=$?

echo ""

# Check results
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✅ Evaluation completed successfully!${NC}"
    echo ""
    echo -e "${YELLOW}📁 Results Location:${NC}"
    echo "   Directory: $OUTPUT_DIR"
    echo ""

    # List generated files
    echo "   Generated files:"
    find "$OUTPUT_DIR" -maxdepth 1 -type f -mmin -5 | while read -r file; do
        size=$(du -h "$file" | cut -f1)
        echo "     - $(basename "$file") ($size)"
    done

    echo ""
    echo -e "${YELLOW}📊 View Results:${NC}"
    echo "   JSON Report:     cat $OUTPUT_DIR/evaluation_report_*.json | jq"
    echo "   Markdown Report: cat $OUTPUT_DIR/evaluation_report_*.md"
    echo "   Metrics CSV:     cat $OUTPUT_DIR/metrics_*.csv"
    echo ""

    # Show latest markdown report summary
    LATEST_REPORT=$(find "$OUTPUT_DIR" -name "evaluation_report_*.md" -type f -mmin -5 | head -1)
    if [ -f "$LATEST_REPORT" ]; then
        echo -e "${BLUE}═══════════════════════════════════════════════════════════════════════════${NC}"
        head -30 "$LATEST_REPORT"
        echo -e "${BLUE}═══════════════════════════════════════════════════════════════════════════${NC}"
    fi
else
    echo -e "${RED}❌ Evaluation failed with exit code: $EXIT_CODE${NC}"
    exit $EXIT_CODE
fi

echo ""
echo -e "${GREEN}🎉 All done!${NC}"
