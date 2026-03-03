# SOTA Face Detection Training

This document describes the state-of-the-art (SOTA) features integrated into the SHML face detection training pipeline.

## Overview

The face detection training job (`ray_compute/jobs/face_detection_training.py`) implements cutting-edge techniques from:
- **INTELLECT-3** by Prime Intellect (Online Advantage Filtering)
- **pii-pro** internal research (Failure Analysis, Dataset Curation)
- **Ultralytics YOLOv8** best practices (Multi-scale training, AdamW+Cosine LR)

## SOTA Features

### 1. Online Advantage Filtering (INTELLECT-3)

**Source:** INTELLECT-3 Technical Report, Prime Intellect

> "During training, problems for which all completions have received the same reward carry no training signal, as their advantages (and therefore losses) are zero. We filter out these problems and continue running inference until we have a full batch with non-zero advantages."

**For Object Detection:**
- "Zero advantage" = batch where model correctly detects ALL faces
- These batches provide no gradient signal (loss ≈ 0)
- Skip them to focus compute on informative samples

**Configuration:**
```python
advantage_filtering_enabled: bool = True
advantage_loss_threshold: float = 0.01  # Loss below = "easy"
advantage_threshold: float = 0.3        # Min fraction of hard samples
advantage_max_consecutive_skips: int = 10
```

**Usage:**
```bash
# Enable (default)
python face_detection_training.py

# Disable
python face_detection_training.py --no-advantage-filter
```

### 2. Failure Analysis

**Purpose:** Extract and cluster failure cases (false negatives) for dataset curation.

**Features:**
- Post-phase failure extraction from validation data
- Test-Time Augmentation (TTA) for better failure detection
- CLIP-based failure clustering to identify patterns
- Automatic MLflow logging of failure statistics

**Configuration:**
```python
failure_analysis_enabled: bool = True
failure_analysis_interval: int = 10  # Epochs between analysis
failure_use_tta: bool = True
failure_conf_threshold: float = 0.35
failure_max_images: int = 500
failure_n_clusters: int = 5
```

**Usage:**
```bash
# Enable (default)
python face_detection_training.py --analyze-failures

# Disable
python face_detection_training.py --no-analyze-failures
```

**Output:**
- `checkpoints/failures/phase_N/failures.json` - Detailed failure cases
- `checkpoints/failures/phase_N/clusters.json` - Clustered failure patterns
- MLflow metrics: `failures_phaseN_count`, `failures_phaseN_false_negative`, etc.

### 3. Dataset Quality Auditing

**Purpose:** Identify potential label quality issues using model predictions.

**Detected Issues:**
- **Missing annotations**: High-confidence predictions with no ground truth
- **Incorrect annotations**: Ground truth with no matching prediction
- **Misaligned boxes**: Low IoU between ground truth and prediction

**Configuration:**
```python
dataset_audit_enabled: bool = True
audit_after_epochs: List[int] = [25, 50, 75]  # When to run audits
audit_max_images: int = 300
audit_conf_threshold: float = 0.5
```

**Usage:**
```bash
# Enable (default)
python face_detection_training.py --audit-dataset

# Disable
python face_detection_training.py --no-audit-dataset
```

**Output:**
- `checkpoints/audits/audit_epoch_N.json` - Audit report with issues
- MLflow metrics: `audit_epochN_issues`, `audit_epochN_missing`, etc.

### 4. TTA Validation

**Purpose:** Use Test-Time Augmentation during failure detection for better recall.

**Augmentations:**
- Horizontal flip (mirror boxes back)
- Scale variations (0.8x, 1.0x, 1.2x)
- NMS merging of multi-scale predictions

**Configuration:**
```python
tta_validation_enabled: bool = True
tta_scales: List[float] = [0.8, 1.0, 1.2]
tta_flip: bool = True
```

## Multi-Scale Training

Training proceeds in 3 phases with progressive resolution:

| Phase | Resolution | Epochs | Batch Size | Purpose |
|-------|------------|--------|------------|---------|
| 1 | 640px | 30% | 8 | Learn basic patterns |
| 2 | 960px | 35% | 4 | Medium details |
| 3 | 1280px | 35% | 2 | Fine details, small faces |

**Rationale:**
- Start with lower resolution for fast convergence
- Progressively increase for fine-grained learning
- Reduce batch size as resolution increases (VRAM constraints)

## Training Configuration Summary

| Feature | Default | Description |
|---------|---------|-------------|
| Multi-Scale | ✅ ON | 640→960→1280px progressive training |
| AdamW + Cosine LR | ✅ ON | SOTA optimizer with LR schedule |
| Label Smoothing | 0.1 | Better generalization |
| Close Mosaic | 15 epochs | Disable mosaic for final fine-tuning |
| Advantage Filtering | ✅ ON | Skip easy batches (INTELLECT-3) |
| Failure Analysis | ✅ ON | Extract false negatives post-phase |
| Dataset Audit | ✅ ON | Verify label quality |
| TTA Validation | ✅ ON | Multi-augmentation failure detection |

## Command Line Examples

```bash
# Full training with all SOTA features (default)
python face_detection_training.py --download-dataset

# Training with custom epochs
python face_detection_training.py --epochs 150 --batch-size 4

# Disable specific SOTA features
python face_detection_training.py \
  --no-advantage-filter \
  --no-analyze-failures \
  --no-audit-dataset

# Export-only mode (after training)
python face_detection_training.py --export-only --weights best.pt

# Validation mode (test setup)
python face_detection_training.py --validate-only
```

## MLflow Metrics

The training job logs extensive metrics to MLflow:

### Training Metrics
- `final_mAP50`, `final_mAP50_95` - Final accuracy
- `final_precision`, `final_recall` - Detection metrics
- `training_hours` - Total training time
- `phaseN_mAP50`, `phaseN_recall` - Per-phase metrics

### SOTA Metrics
- `failures_phaseN_count` - Total failures found
- `failures_phaseN_false_negative` - False negative count
- `failures_phaseN_clusters` - Number of failure clusters
- `audit_epochN_issues` - Label quality issues
- `audit_epochN_missing` - Missing annotation count
- `audit_epochN_incorrect` - Incorrect annotation count
- `audit_epochN_misaligned` - Misaligned box count

## Architecture

```
face_detection_training.py
├── FaceDetectionConfig          # All configuration options
├── OnlineAdvantageFilter        # INTELLECT-3 batch filtering
├── FailureAnalyzer              # Post-training failure extraction
├── DatasetQualityAuditor        # Label quality verification
├── WIDERFaceDataset             # Dataset handling
├── AGUIEventEmitter             # Real-time progress streaming
├── CheckpointManager            # Preemption-safe checkpointing
├── ModelExporter                # ONNX/TensorRT export
├── _run_failure_analysis()      # SOTA failure analysis integration
├── _run_dataset_audit()         # SOTA dataset audit integration
├── _train_multiscale()          # Multi-phase training
└── train_face_detection()       # Main entry point
```

## References

1. **INTELLECT-3**: Prime Intellect. "INTELLECT-3 Technical Report." 2025.
2. **pii-pro**: Internal research on automated training pipelines.
3. **YOLOv8**: Ultralytics. "YOLOv8 Documentation." 2024.
4. **WIDER Face**: Yang et al. "WIDER FACE: A Face Detection Benchmark." CVPR 2016.
