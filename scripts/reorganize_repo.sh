#!/bin/bash
# Repository Reorganization Script
# Version: 2.0
# Purpose: Reorganize Ray Compute + MLflow for unified architecture

set -e  # Exit on error

PROJECT_ROOT="/home/axelofwar/Projects/shml-platform"
RAY_COMPUTE="$PROJECT_ROOT/ray_compute"

echo "==================================================================="
echo "Repository Reorganization: Ray Compute + MLflow Integration"
echo "==================================================================="
echo ""
echo "This script will:"
echo "  1. Create new organized directory structure"
echo "  2. Move existing training jobs to new locations"
echo "  3. Update imports in all Python files"
echo "  4. Create MLflow Projects structure"
echo "  5. Backup original structure"
echo ""
read -p "Continue? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

# Backup current structure
echo ""
echo "[1/7] Backing up current structure..."
BACKUP_DIR="$PROJECT_ROOT/backups/platform/repo_backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
cp -r "$RAY_COMPUTE/jobs" "$BACKUP_DIR/" 2>/dev/null || true
cp -r "$RAY_COMPUTE/models" "$BACKUP_DIR/" 2>/dev/null || true
echo "✓ Backup created: $BACKUP_DIR"

# Create new directory structure
echo ""
echo "[2/7] Creating new directory structure..."

# Jobs directories
mkdir -p "$RAY_COMPUTE/jobs/training/configs"
mkdir -p "$RAY_COMPUTE/jobs/evaluation/configs"
mkdir -p "$RAY_COMPUTE/jobs/annotation/configs"
mkdir -p "$RAY_COMPUTE/jobs/utils"

# Models directories
mkdir -p "$RAY_COMPUTE/models/registry"
mkdir -p "$RAY_COMPUTE/models/checkpoints/phase1_wider_face"
mkdir -p "$RAY_COMPUTE/models/checkpoints/phase2_production"
mkdir -p "$RAY_COMPUTE/models/checkpoints/phase3_active_learning"
mkdir -p "$RAY_COMPUTE/models/deployed"
mkdir -p "$RAY_COMPUTE/models/exports"

# Data directories
mkdir -p "$RAY_COMPUTE/data/datasets/wider_face"
mkdir -p "$RAY_COMPUTE/data/datasets/production/raw"
mkdir -p "$RAY_COMPUTE/data/datasets/production/annotated"
mkdir -p "$RAY_COMPUTE/data/datasets/production/reviewed"
mkdir -p "$RAY_COMPUTE/data/datasets/yfcc100m/downloaded"
mkdir -p "$RAY_COMPUTE/data/datasets/yfcc100m/filtered"
mkdir -p "$RAY_COMPUTE/data/datasets/yfcc100m/annotated"
mkdir -p "$RAY_COMPUTE/data/datasets/annotations/auto"
mkdir -p "$RAY_COMPUTE/data/datasets/annotations/reviewed"
mkdir -p "$RAY_COMPUTE/data/datasets/annotations/final"

# MLflow Projects
mkdir -p "$RAY_COMPUTE/mlflow_projects/face_detection_training"
mkdir -p "$RAY_COMPUTE/mlflow_projects/auto_annotation"
mkdir -p "$RAY_COMPUTE/mlflow_projects/model_evaluation"

echo "✓ Directory structure created"

# Move existing files
echo ""
echo "[3/7] Moving existing files..."

# Move training jobs
if [ -f "$RAY_COMPUTE/jobs/face_detection_training.py" ]; then
    mv "$RAY_COMPUTE/jobs/face_detection_training.py" \
       "$RAY_COMPUTE/jobs/training/phase1_foundation.py"
    echo "✓ Moved face_detection_training.py → training/phase1_foundation.py"
fi

# Move evaluation jobs
if [ -f "$RAY_COMPUTE/jobs/evaluate_wider_face.py" ]; then
    mv "$RAY_COMPUTE/jobs/evaluate_wider_face.py" \
       "$RAY_COMPUTE/jobs/evaluation/wider_face_eval.py"
    echo "✓ Moved evaluate_wider_face.py → evaluation/wider_face_eval.py"
fi

# Move model registry
if [ -f "$RAY_COMPUTE/models/MODEL_REGISTRY.md" ]; then
    cp "$RAY_COMPUTE/models/MODEL_REGISTRY.md" \
       "$RAY_COMPUTE/models/registry/MODEL_REGISTRY.md"
    echo "✓ Copied MODEL_REGISTRY.md to registry/"
fi

# Create models.json index
cat > "$RAY_COMPUTE/models/registry/models.json" << 'EOF'
{
  "models": [
    {
      "name": "face-detection-yolov8l",
      "versions": [
        {
          "version": "phase1-v1",
          "path": "/ray_compute/models/checkpoints/phase1_wider_face/best.pt",
          "mlflow_uri": "models:/face-detection-yolov8l/Production",
          "metrics": {
            "mAP50": 0.8093,
            "recall": 0.6781,
            "precision": 0.8532
          },
          "dataset": "wider_face",
          "phase": "phase1",
          "created_at": "2025-12-10"
        }
      ]
    }
  ]
}
EOF
echo "✓ Created models.json index"

# Create __init__.py files
echo ""
echo "[4/7] Creating __init__.py files..."

touch "$RAY_COMPUTE/jobs/__init__.py"
touch "$RAY_COMPUTE/jobs/training/__init__.py"
touch "$RAY_COMPUTE/jobs/evaluation/__init__.py"
touch "$RAY_COMPUTE/jobs/annotation/__init__.py"
touch "$RAY_COMPUTE/jobs/utils/__init__.py"
echo "✓ Created __init__.py files"

# Create utility stub files
echo ""
echo "[5/7] Creating utility stubs..."

# checkpoint_manager.py stub
cat > "$RAY_COMPUTE/jobs/utils/checkpoint_manager.py" << 'EOF'
"""
Dual Storage Manager for model checkpoints.
Saves to both local disk (fast I/O) and MLflow (versioned).

See: docs/ARCHITECTURE_REDESIGN.md for full implementation.
"""

# TODO: Implement DualStorageManager class
# See docs/ARCHITECTURE_REDESIGN.md Section 1 for implementation

class DualStorageManager:
    def __init__(self, local_dir: str, mlflow_experiment: str):
        raise NotImplementedError("See docs/ARCHITECTURE_REDESIGN.md for implementation")
EOF

# mlflow_integration.py stub
cat > "$RAY_COMPUTE/jobs/utils/mlflow_integration.py" << 'EOF'
"""
MLflow integration helpers.
Simplified API for common MLflow operations.

See: docs/ARCHITECTURE_REDESIGN.md for full implementation.
"""

# TODO: Implement MLflowHelper class
# See docs/ARCHITECTURE_REDESIGN.md Section 2 for implementation

class MLflowHelper:
    def __init__(self, tracking_uri: str = "http://mlflow-server:5000"):
        raise NotImplementedError("See docs/ARCHITECTURE_REDESIGN.md for implementation")
EOF

# sam2_pipeline.py stub
cat > "$RAY_COMPUTE/jobs/annotation/sam2_pipeline.py" << 'EOF'
"""
SAM2 Auto-Annotation Pipeline.
YOLOv8 detection + SAM2 mask refinement.

See: docs/ARCHITECTURE_REDESIGN.md for full implementation.
"""

# TODO: Implement SAM2AnnotationPipeline class
# See docs/ARCHITECTURE_REDESIGN.md Section 3 for implementation

class SAM2AnnotationPipeline:
    def __init__(self, yolo_model_path: str, sam2_checkpoint: str):
        raise NotImplementedError("See docs/ARCHITECTURE_REDESIGN.md for implementation")
EOF

echo "✓ Created utility stubs"

# Create MLflow Projects
echo ""
echo "[6/7] Creating MLflow Projects..."

# face_detection_training MLproject
cat > "$RAY_COMPUTE/mlflow_projects/face_detection_training/MLproject" << 'EOF'
name: face_detection_training

conda_env: conda.yaml

entry_points:
  main:
    parameters:
      epochs: {type: int, default: 200}
      batch_size: {type: int, default: 8}
      learning_rate: {type: float, default: 0.01}
      dataset: {type: str, default: "wider_face"}
      phase: {type: str, default: "phase1"}
    command: "python train.py --epochs {epochs} --batch-size {batch_size} --lr {learning_rate} --dataset {dataset} --phase {phase}"
EOF

cat > "$RAY_COMPUTE/mlflow_projects/face_detection_training/conda.yaml" << 'EOF'
name: face_detection_training
channels:
  - pytorch
  - nvidia
  - conda-forge
dependencies:
  - python=3.10
  - pytorch::pytorch=2.1.2
  - pytorch::torchvision=0.16.2
  - pytorch::torchaudio=2.1.2
  - pytorch::pytorch-cuda=12.1
  - pip
  - pip:
    - mlflow==2.17.2
    - ray[default]==2.8.1
    - ultralytics==8.3.59
    - opencv-python
    - pandas
    - numpy
EOF

cat > "$RAY_COMPUTE/mlflow_projects/face_detection_training/train.py" << 'EOF'
"""
MLflow Project: Face Detection Training
See: docs/ARCHITECTURE_REDESIGN.md for implementation
"""

# TODO: Implement training entry point
# Load from jobs/training/phase1_foundation.py

raise NotImplementedError("See docs/ARCHITECTURE_REDESIGN.md")
EOF

cat > "$RAY_COMPUTE/mlflow_projects/face_detection_training/README.md" << 'EOF'
# Face Detection Training (MLflow Project)

## Usage

```bash
# Run via MLflow CLI
mlflow run . -P epochs=200 -P batch_size=8

# Run via Python API
import mlflow
mlflow.run(".", parameters={"epochs": 200, "batch_size": 8})
```

## Parameters

- `epochs`: Training epochs (default: 200)
- `batch_size`: Batch size (default: 8)
- `learning_rate`: Learning rate (default: 0.01)
- `dataset`: Dataset name (default: "wider_face")
- `phase`: Training phase (default: "phase1")

## See Also

- `docs/ARCHITECTURE_REDESIGN.md` - Full architecture
- `ray_compute/jobs/training/phase1_foundation.py` - Implementation
EOF

echo "✓ Created MLflow Projects"

# Update imports (basic search/replace)
echo ""
echo "[7/7] Updating imports..."

# Find all Python files and update imports
find "$RAY_COMPUTE/jobs" -name "*.py" -type f | while read file; do
    # Backup file
    cp "$file" "${file}.bak"

    # Update imports (basic patterns)
    sed -i 's/from jobs\./from jobs.utils./g' "$file"
    sed -i 's/import jobs\./import jobs.utils./g' "$file"
done

echo "✓ Imports updated (backups created with .bak extension)"

# Summary
echo ""
echo "==================================================================="
echo "✓ Repository Reorganization Complete!"
echo "==================================================================="
echo ""
echo "Summary:"
echo "  - Backup: $BACKUP_DIR"
echo "  - New structure: $RAY_COMPUTE/jobs/{training,evaluation,annotation,utils}"
echo "  - Models: $RAY_COMPUTE/models/{registry,checkpoints,deployed,exports}"
echo "  - MLflow Projects: $RAY_COMPUTE/mlflow_projects/"
echo ""
echo "Next Steps:"
echo "  1. Review moved files: ls -R $RAY_COMPUTE/jobs/"
echo "  2. Implement DualStorageManager: vim $RAY_COMPUTE/jobs/utils/checkpoint_manager.py"
echo "  3. Test training: python $RAY_COMPUTE/jobs/training/phase1_foundation.py"
echo "  4. See docs/ARCHITECTURE_REDESIGN.md for full implementation guide"
echo ""
echo "⚠️  Import updates may need manual review. Check .bak files if needed."
echo ""

# Tree view (if installed)
if command -v tree &> /dev/null; then
    echo "Directory Structure:"
    tree -L 3 -I '__pycache__|*.pyc|*.bak' "$RAY_COMPUTE/jobs" "$RAY_COMPUTE/models" "$RAY_COMPUTE/mlflow_projects"
fi
