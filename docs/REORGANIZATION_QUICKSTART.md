# Repository Reorganization: Quick Start Guide

**Version:** 2.0  
**Date:** 2025-12-12  
**Status:** 🔄 Ready to Execute

---

## 🎯 What We're Doing

Reorganizing the repository to unify Ray Compute + MLflow with:
- ✅ Dual storage (local + MLflow)
- ✅ Ray Compute API for all jobs
- ✅ MLflow native model registry
- ✅ Organized directory structure
- ✅ SAM2 auto-annotation pipeline

---

## 🚀 Step-by-Step Execution

### Step 1: Review the Plan

**Read these documents:**
```bash
# Architecture redesign (complete implementation)
cat docs/ARCHITECTURE_REDESIGN.md

# Lessons learned (why we're doing this)
cat docs/LESSONS_LEARNED.md

# Project board (12-month plan)
cat docs/PLATFORM_IMPROVEMENTS_PROJECT_BOARD.md
```

**What you'll see:**
- Directory structure design
- DualStorageManager implementation
- MLflowHelper API
- SAM2AnnotationPipeline code
- Migration timeline

---

### Step 2: Run Reorganization Script

**Execute the automation:**
```bash
cd /home/axelofwar/Projects/shml-platform

# Dry run (see what will happen)
./scripts/reorganize_repo.sh

# When prompted, type "yes" to proceed
```

**What it does:**
1. ✅ Backs up current structure (timestamped)
2. ✅ Creates new directories (jobs/, models/, mlflow_projects/)
3. ✅ Moves existing files to organized locations
4. ✅ Creates utility stubs (DualStorageManager, MLflowHelper, SAM2Pipeline)
5. ✅ Creates MLflow Projects (face_detection_training, auto_annotation)
6. ✅ Updates imports in Python files

**Output:**
```
Backup: backups/platform/repo_backup_20251212_143045/
New structure: ray_compute/jobs/{training,evaluation,annotation,utils}
Models: ray_compute/models/{registry,checkpoints,deployed,exports}
MLflow Projects: ray_compute/mlflow_projects/
```

---

### Step 3: Review Changes

**Check the new structure:**
```bash
# View directory tree
tree -L 3 -I '__pycache__|*.pyc|*.bak' ray_compute/jobs ray_compute/models ray_compute/mlflow_projects

# Should show:
# ray_compute/jobs/
# ├── training/
# │   ├── phase1_foundation.py    (was: face_detection_training.py)
# │   └── configs/
# ├── evaluation/
# │   ├── wider_face_eval.py      (was: evaluate_wider_face.py)
# │   └── configs/
# ├── annotation/
# │   ├── sam2_pipeline.py        (NEW stub)
# │   └── configs/
# └── utils/
#     ├── checkpoint_manager.py   (NEW stub)
#     ├── mlflow_integration.py   (NEW stub)
#     └── artifact_sync.py
```

**Verify moved files:**
```bash
# Check training job moved correctly
ls -lh ray_compute/jobs/training/phase1_foundation.py

# Check evaluation job moved correctly
ls -lh ray_compute/jobs/evaluation/wider_face_eval.py

# Check model registry copied
ls -lh ray_compute/models/registry/MODEL_REGISTRY.md
```

---

### Step 4: Implement Dual Storage Manager

**Open the stub file:**
```bash
vim ray_compute/jobs/utils/checkpoint_manager.py
```

**Copy implementation from:**
```bash
# See docs/ARCHITECTURE_REDESIGN.md Section 1: Dual Storage Manager
# Copy the full DualStorageManager class (100+ lines)
```

**Key features:**
- Saves to local disk (fast I/O during training)
- Async syncs to MLflow (no training overhead)
- Methods: `save()`, `load_best()`, `register_model()`

**Test it:**
```python
from ray_compute.jobs.utils.checkpoint_manager import DualStorageManager

manager = DualStorageManager(
    local_dir="/ray_compute/models/checkpoints/phase1_wider_face",
    mlflow_experiment="face-detection-training",
    sync_strategy="async"
)

# Should initialize without errors
print("✓ DualStorageManager working")
```

---

### Step 5: Implement MLflow Helper

**Open the stub file:**
```bash
vim ray_compute/jobs/utils/mlflow_integration.py
```

**Copy implementation from:**
```bash
# See docs/ARCHITECTURE_REDESIGN.md Section 2: MLflow Integration Helper
# Copy the full MLflowHelper class (80+ lines)
```

**Key features:**
- `start_training_run()` - Creates experiment and logs params
- `log_epoch_metrics()` - Logs metrics per epoch
- `load_model_from_registry()` - Loads production models
- `promote_model_to_production()` - Model promotion workflow
- `compare_models()` - Compares versions by metric

**Test it:**
```python
from ray_compute.jobs.utils.mlflow_integration import MLflowHelper

helper = MLflowHelper(tracking_uri="http://localhost:8080")

# Should connect to MLflow
print("✓ MLflowHelper working")
```

---

### Step 6: Update Phase 1 Training Job

**Open the training job:**
```bash
vim ray_compute/jobs/training/phase1_foundation.py
```

**Add dual storage:**
```python
from ray_compute.jobs.utils.checkpoint_manager import DualStorageManager
from ray_compute.jobs.utils.mlflow_integration import MLflowHelper

# At top of training function
mlflow_helper = MLflowHelper()
run_id = mlflow_helper.start_training_run(
    experiment_name="face-detection-training",
    run_name="phase1-wider-face-200epochs",
    params={"epochs": 200, "batch_size": 8, "lr": 0.01},
    tags={"phase": "phase1", "dataset": "wider_face"}
)

checkpoint_manager = DualStorageManager(
    local_dir="/ray_compute/models/checkpoints/phase1_wider_face",
    mlflow_experiment="face-detection-training",
    sync_strategy="async"
)

# In training loop
for epoch in range(200):
    # Train
    results = model.train(...)

    # Save checkpoint (local + MLflow async)
    checkpoint_manager.save(
        epoch=epoch,
        model=model,
        metrics=results.results_dict,
        metadata={"dataset": "wider_face", "phase": "phase1"}
    )

    # Log to MLflow
    mlflow_helper.log_epoch_metrics(epoch, results.results_dict, prefix="train")

# After training, register best model
checkpoint_manager.register_model(
    model_name="face-detection-yolov8l",
    model_version="phase1-v1",
    model_path=str(checkpoint_manager.local_dir / "best.pt"),
    tags={"dataset": "wider_face", "phase": "phase1"}
)
```

---

### Step 7: Test End-to-End

**Run a small training test:**
```bash
cd ray_compute

# Test with 5 epochs only
python jobs/training/phase1_foundation.py \
  --epochs 5 \
  --batch-size 2 \
  --imgsz 640 \
  --device 0

# Should see:
# ✓ Saved checkpoint: /ray_compute/models/checkpoints/phase1_wider_face/epoch_1.pt
# ✓ Synced to MLflow: epoch 1
# ✓ Saved checkpoint: /ray_compute/models/checkpoints/phase1_wider_face/epoch_2.pt
# ✓ Synced to MLflow: epoch 2
# ...
# ✓ Registered model: face-detection-yolov8l v1
```

**Verify in MLflow UI:**
```bash
# Open browser
open http://localhost:8080

# Navigate to:
# - Experiments → face-detection-training
# - Should see run "phase1-wider-face-200epochs"
# - Artifacts tab should show checkpoints/ directory
# - Models tab should show "face-detection-yolov8l" registered
```

---

### Step 8: Implement SAM2 Pipeline (Week 2)

**Open the stub file:**
```bash
vim ray_compute/jobs/annotation/sam2_pipeline.py
```

**Copy implementation from:**
```bash
# See docs/ARCHITECTURE_REDESIGN.md Section 3: SAM2 Auto-Annotation Pipeline
# Copy the full SAM2AnnotationPipeline class (150+ lines)
```

**Install SAM2:**
```bash
# Clone SAM2 repo
cd /tmp
git clone https://github.com/facebookresearch/segment-anything-2.git
cd segment-anything-2

# Install
pip install -e .

# Download checkpoint
wget https://dl.fbaipublicfiles.com/segment_anything_2/072824/sam2_hiera_large.pt
mv sam2_hiera_large.pt /ray_compute/models/checkpoints/sam2/
```

**Test SAM2 pipeline:**
```python
from ray_compute.jobs.annotation.sam2_pipeline import SAM2AnnotationPipeline

pipeline = SAM2AnnotationPipeline(
    yolo_model_path="/ray_compute/models/checkpoints/phase1_wider_face/best.pt",
    sam2_checkpoint="/ray_compute/models/checkpoints/sam2/sam2_hiera_large.pt"
)

# Annotate a batch
image_paths = ["/path/to/image1.jpg", "/path/to/image2.jpg"]
pipeline.annotate_batch(
    image_paths=image_paths,
    output_path="/ray_compute/data/datasets/annotations/auto/batch1.json",
    conf_threshold=0.25
)

# Should output COCO format JSON
print("✓ SAM2 pipeline working")
```

---

## 🎯 Success Criteria

### After Step 7 (End of Week 1)

- [ ] Directory structure reorganized
- [ ] `DualStorageManager` implemented and tested
- [ ] `MLflowHelper` implemented and tested
- [ ] Phase 1 training job updated with dual storage
- [ ] Small test training (5 epochs) completes successfully
- [ ] Checkpoints saved to both local disk and MLflow
- [ ] Model registered in MLflow Model Registry
- [ ] MLflow UI shows experiment run with artifacts

### After Step 8 (End of Week 2)

- [ ] SAM2 installed and working
- [ ] `SAM2AnnotationPipeline` implemented
- [ ] Test batch annotation completes (10 images)
- [ ] COCO format JSON exported
- [ ] Auto-annotations visible in Label Studio

---

## 📊 Expected Outcomes

### Cost Savings
- **Before:** $6,000/year manual annotation
- **After:** $180/year SAM2 auto-annotation
- **Savings:** $5,820/year (97% reduction)

### Time Savings
- **Before:** 1000 hours/year manual annotation
- **After:** 30 hours/year review + 10 hours/year model retraining
- **Savings:** 960 hours/year

### Quality Improvements
- **Phase 1 (WIDER Face only):** 75-85% recall
- **Phase 2 (+ production data):** 88-93% recall
- **Phase 3 (+ YFCC100M):** 93-95% recall
- **Active learning:** 95%+ sustained

---

## 🔧 Troubleshooting

### Import Errors

**Problem:** `ModuleNotFoundError: No module named 'ray_compute.jobs.utils'`

**Solution:**
```bash
# Add to PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:/home/axelofwar/Projects/shml-platform"

# Or create __init__.py files
touch ray_compute/jobs/__init__.py
touch ray_compute/jobs/utils/__init__.py
```

### MLflow Connection Errors

**Problem:** `ConnectionError: MLflow server not reachable`

**Solution:**
```bash
# Start MLflow server
cd mlflow-server
docker-compose up -d

# Check status
curl http://localhost:8080/health

# Update tracking URI if needed
export MLFLOW_TRACKING_URI="http://localhost:8080"
```

### Checkpoint Save Errors

**Problem:** `PermissionError: /ray_compute/models/checkpoints/`

**Solution:**
```bash
# Fix permissions
sudo chown -R $USER:$USER /home/axelofwar/Projects/shml-platform/ray_compute/models
chmod -R 755 /home/axelofwar/Projects/shml-platform/ray_compute/models
```

---

## 📚 Reference Documents

| Document | Purpose |
|----------|---------|
| `docs/ARCHITECTURE_REDESIGN.md` | Complete architecture + implementation code |
| `docs/LESSONS_LEARNED.md` | Why we're doing this (failures + pivots) |
| `docs/PLATFORM_IMPROVEMENTS_PROJECT_BOARD.md` | 12-month plan + monthly costs |
| `ray_compute/models/registry/MODEL_REGISTRY.md` | SAM2 auto-annotation guide (400 lines) |
| `scripts/reorganize_repo.sh` | Automation script (this guide) |

---

## 🚨 Critical Notes

### ⚠️ ALWAYS Use start_all_safe.sh

**For ANY service restarts:**
```bash
# ✅ CORRECT
./start_all_safe.sh restart ray
./start_all_safe.sh restart mlflow

# ❌ WRONG (kills active jobs, skips migrations)
docker-compose restart ray-compute-api
docker-compose down
```

### ⚠️ Backup Before Reorganization

**The script auto-backs up, but you can also:**
```bash
# Manual backup
cp -r ray_compute/jobs backups/platform/manual_backup_$(date +%Y%m%d)
cp -r ray_compute/models backups/platform/manual_backup_$(date +%Y%m%d)
```

### ⚠️ Documentation Limit

**Current: 17/20 files. DO NOT exceed 20 total documentation files.**

If you need new docs, consolidate into existing files:
- Setup/Status → `README.md`
- Architecture → `ARCHITECTURE.md` or `docs/ARCHITECTURE_REDESIGN.md`
- Troubleshooting → `TROUBLESHOOTING.md`

---

## 🎉 Next Steps After Completion

1. **Week 1:** Dual storage implementation + testing
2. **Week 2:** SAM2 pipeline implementation
3. **Week 3:** YFCC100M downloader + active learning
4. **Week 4:** Label Studio integration + tiered review
5. **Month 2:** Production data collection opt-in
6. **Month 3:** First retraining with production data
7. **Month 6:** Achieve 95% recall target

---

**Last Updated:** 2025-12-12  
**Status:** 🔄 Ready to Execute  
**Estimated Time:** Week 1 (20-30 hours), Week 2 (10-15 hours)
