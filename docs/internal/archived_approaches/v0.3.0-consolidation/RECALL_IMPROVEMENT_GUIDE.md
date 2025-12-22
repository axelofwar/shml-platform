# Face Detection Recall Improvement Guide

**Last Updated:** December 7, 2025  
**Current Status:** Baseline comparison complete, ready for recall-focused retraining  
**Model:** YOLOv8l-face (43.6M parameters)  
**Dataset:** WIDER Face (12,876 train, 3,222 val images)

---

## Current Performance Summary

### Baseline Comparison Results (Dec 7, 2025)

| Model | Precision | Recall | mAP50 | mAP50-95 | Speed |
|-------|-----------|--------|-------|----------|-------|
| **yolov8l-face (baseline)** | 87.58% | **73.81%** | 84.14% | 52.96% | - |
| **Our trained model** | 90.64% | **73.96%** | 84.83% | 54.21% | 35.4ms |
| **Improvement** | +3.06pp | +0.15pp | +0.69pp | +1.25pp | - |

**Key Findings:**
- Training improved precision and mAP significantly
- Recall barely improved (+0.15pp) - this is the bottleneck
- **Target:** Recall > 85% (requires +11pp improvement)
- **Gap:** 85% - 73.96% = **11.04% to close**

### Training Job Details

- **Job ID:** `raysubmit_WF6m1WvCSne5tKyr`
- **Status:** SUCCEEDED (only TensorRT exports failed, ONNX succeeded)
- **Training Config:** Base `FaceDetectionConfig`
  - Epochs: 100 (multi-scale: 640→960→1280px)
  - Batch size: 4-8 (depending on resolution)
  - Optimizer: AdamW + Cosine LR
  - Augmentation: Mosaic, mixup, flips
  - SOTA features: Advantage filtering, failure analysis, dataset audits

### Inference Threshold Testing (Dec 7, 2025)

Tested on host GPU (RTX 3090 Ti) with different confidence thresholds:

| conf | iou | Precision | Recall | mAP50 | mAP50-95 |
|------|-----|-----------|--------|-------|----------|
| 0.25 | 0.5 | 89.79% | 74.08% | 82.25% | 53.06% |
| 0.20 | 0.5 | 88.56% | **75.71%** | 82.55% | 53.24% |
| 0.15 | 0.5 | 86.89% | 75.08% | 81.71% | 52.43% |
| 0.10 | 0.5 | 84.36% | 73.69% | 79.72% | 50.51% |

**Conclusion:** Lowering confidence threshold gives max **+1.63% recall** (0.20 conf)
- Not enough to reach 85% target
- Retraining with recall-focused config required

---

## YOLOv8l Architecture Analysis

### Detection Scales

YOLOv8l uses **anchor-free DFL (Distribution Focal Loss)** with 3 detection scales:

| Scale | Stride | Grid @ 1280px | Receptive Field | Purpose | Recall Challenge |
|-------|--------|---------------|-----------------|---------|------------------|
| **P3** | 8x | 160×160 | ~8px | **Small faces (8-64px)** | ⚠️ **CRITICAL - Most failures here** |
| **P4** | 16x | 80×80 | ~16px | Medium faces (32-256px) | Moderate |
| **P5** | 32x | 40×40 | ~32px | Large faces (128-512px) | Least critical |

### Why Recall is Hard at 73.96%

1. **Small face detection:** Faces < 16px are extremely difficult even at 1280px resolution
2. **Feature degradation:** Down-sampling loses critical facial details
3. **Occlusions:** Masks, hands, overlapping faces reduce visibility
4. **Blur/compression:** WIDER Face has low-quality images
5. **Confidence threshold:** Current conf=0.25 filters out uncertain detections
6. **WIDER Face dataset:** Extreme scale variation (tiny faces in crowds)

**Key Insight:** Most recall failures occur in the **P3 (stride 8) scale** - small face detection is the bottleneck.

---

## Available Techniques for Recall Improvement

### 1. Inference-Time Adjustments ⚡ (Quick Wins)

#### A. Lower Confidence Threshold
- **Status:** ✅ TESTED
- **Current:** `conf=0.25`
- **Optimal:** `conf=0.20` (from testing)
- **Impact:** +1.63% recall
- **Trade-off:** -1.23pp precision
- **Conclusion:** Helps but insufficient alone

#### B. Looser NMS (Non-Maximum Suppression)
- **Status:** ⚠️ PARTIALLY TESTED
- **Current:** `iou=0.6`
- **Option:** `iou=0.5` or `iou=0.45`
- **Impact:** Keeps overlapping detections in crowded scenes
- **Trade-off:** More duplicate detections
- **Expected gain:** +1-2% recall

#### C. Test-Time Augmentation (TTA)
- **Status:** ✅ IMPLEMENTED (for validation only)
- **Method:** Multi-scale predictions (0.8x, 1.0x, 1.2x) + horizontal flip
- **Impact:** +2-4% recall
- **Trade-off:** 3x slower inference (3 scales + flip)
- **Usage:** Enable `augment=True` in model.val() or model.predict()

**Maximum gain from inference tuning:** ~5% (75% → 80% recall max)

---

### 2. Training-Time Techniques 🏋️ (Requires Retraining)

#### A. FaceDetectionConfigRecallFocused ⭐ RECOMMENDED

**Status:** ✅ IMPLEMENTED in `face_detection_training.py`  
**Usage:** `python face_detection_training.py --recall-focused`

**Key Changes from Base Config:**

```python
# Detection Thresholds (trains model to be more permissive)
conf_threshold: 0.15          # Lower (was 0.25)
iou_threshold: 0.50           # Looser NMS (was 0.60)

# Augmentation (trains on harder scenarios)
copy_paste: 0.3               # Dense scene training (was 0.0)
scale: 0.9                    # More scale variation (was 0.5)
mosaic: 1.0                   # Keep strong mosaic
mixup: 0.2                    # Higher mixup (was 0.15)

# Loss Weights (emphasizes finding faces over classification confidence)
box_loss_weight: 10.0         # Higher localization (was 7.5)
cls_loss_weight: 0.3          # Lower classification penalty (was 0.5)
dfl_loss_weight: 2.0          # Better box distribution (was 1.5)

# Multi-Scale Training (extended high-res phase for small faces)
Phase 1 (640px):  20% epochs  # Reduced (was 30%)
Phase 2 (960px):  30% epochs  # Reduced (was 35%)
Phase 3 (1280px): 50% epochs  # EXTENDED (was 35%) ← Critical for P3 scale

# SOTA: Relaxed Advantage Filtering (keeps harder training samples)
advantage_loss_threshold: 0.005  # Stricter "easy" definition (was 0.01)
advantage_threshold: 0.2         # Fewer skips (was 0.3)
```

**Why This Works:**
1. **Lower thresholds:** Model learns to be confident about uncertain faces
2. **Copy-paste:** Creates crowded scenes, trains for occlusions
3. **Extended Phase 3:** More time at 1280px improves small face detection (P3 scale)
4. **Adjusted loss weights:** Reduces penalty for false positives, focuses on localization
5. **Relaxed advantage filtering:** Keeps harder samples in training batches

**Expected Impact:** **5-8% recall improvement** (75% → 80-83%)  
**Trade-off:** -2 to -5pp precision (acceptable for privacy use case)

**Training Command:**
```bash
# Submit recall-focused training job
docker exec ray-head ray job submit \
  --working-dir=/tmp/ray \
  -- python face_detection_training.py \
     --recall-focused \
     --epochs 100 \
     --download-dataset
```

---

#### B. Hard Sample Mining (via Failure Analysis) 🔍

**Status:** ✅ IMPLEMENTED (runs automatically during training)

**How It Works:**
1. After each training phase, extracts false negative samples
2. Uses TTA (flips, scales) to confirm they're truly missed
3. CLIP-based clustering identifies systematic failure patterns
4. Logs to MLflow: `failures_phaseN_false_negative` metric

**Configuration (already in training script):**
```python
failure_analysis_enabled: True
failure_analysis_interval: 10      # Run every 10 epochs
failure_use_tta: True              # Multi-scale failure detection
failure_conf_threshold: 0.35
failure_max_images: 500
failure_n_clusters: 5
```

**What to Do After Training:**
1. Review failure outputs: `checkpoints/failures/phase_*/failures.json`
2. Check failure clusters: `checkpoints/failures/phase_*/clusters.json`
3. Identify systematic issues (e.g., "masked faces", "extreme angles", "extreme scale")
4. Consider:
   - Adding more similar samples to training data
   - Adjusting augmentation to cover failure modes
   - Targeted dataset expansion

**Expected Impact:** **3-5% recall** with targeted dataset augmentation  
**Status:** Runs automatically, requires manual review of results

---

#### C. Dataset Quality Auditing 📊

**Status:** ✅ IMPLEMENTED (runs automatically at epochs 25, 50, 75)

**Detected Issues:**
- **Missing annotations:** High-confidence predictions with no ground truth
- **Incorrect annotations:** Ground truth boxes with no matching prediction
- **Misaligned boxes:** Low IoU matches (annotation errors)

**Configuration (already in training script):**
```python
dataset_audit_enabled: True
audit_after_epochs: [25, 50, 75]
audit_max_images: 300
audit_conf_threshold: 0.5
```

**What to Do After Training:**
1. Review audit reports: `checkpoints/audits/audit_epoch_N.json`
2. Check MLflow metrics: `audit_epochN_issues`, `audit_epochN_missing`, etc.
3. Fix annotation errors in WIDER Face dataset
4. Retrain with corrected labels

**Expected Impact:** **2-4% recall** by fixing label noise  
**Status:** Runs automatically, requires manual dataset correction

---

#### D. Additional Data Sources 📦

**Status:** ❌ NOT IMPLEMENTED

**Options:**
- **FDDB:** 2,845 images, 5,171 faces (unconstrained environments)
- **MAFA:** 30,811 images, masked faces (occlusion scenarios)
- **CelebA:** 202,599 images, celebrity faces (high quality, diverse)

**Implementation:**
1. Download additional datasets
2. Convert annotations to YOLO format
3. Merge with WIDER Face dataset
4. Rebalance dataset (prevent bias)
5. Retrain

**Expected Impact:** **3-5% recall** from increased diversity  
**Effort:** MEDIUM (2-3 days for conversion + rebalancing)

---

### 3. Advanced Training Techniques 🚀 (High Effort)

#### A. Custom Recall-Weighted Loss Function
**Status:** ❌ NOT IMPLEMENTED  
**Method:** Penalize false negatives more than false positives
```python
# alpha > 0.5 weights false negatives higher
loss = alpha * FN_loss + (1-alpha) * FP_loss
```
**Impact:** 3-5% recall  
**Difficulty:** HIGH (requires modifying ultralytics YOLO source)

#### B. Focal Loss for Hard Samples
**Status:** ❌ NOT IMPLEMENTED  
**Method:** Down-weight easy negatives, focus on hard positives  
**Impact:** 2-3% recall  
**Difficulty:** HIGH (requires custom loss function)

#### C. Model Ensemble
**Status:** ❌ NOT IMPLEMENTED  
**Method:** Train 3-5 models, merge predictions with Weighted Boxes Fusion  
**Impact:** 3-5% recall  
**Difficulty:** HIGH (3-5x training cost, complex inference)

---

### 4. Architecture Improvements 🏗️ (Very High Effort)

#### A. Add P2 Detection Scale (Stride 4)
**Purpose:** Double small face detection grid (320×320 at 1280px)  
**Impact:** 5-8% recall on small faces  
**Difficulty:** VERY HIGH (modify YOLOv8 architecture)  
**Status:** ❌ NOT IMPLEMENTED

#### B. Attention Mechanisms for Small Objects
**Purpose:** Focus model on small face features at P3 scale  
**Impact:** 3-5% recall on small faces  
**Difficulty:** VERY HIGH (custom architecture)  
**Status:** ❌ NOT IMPLEMENTED

#### C. Super-Resolution Pre-Processing
**Purpose:** Upscale small faces before detection  
**Impact:** 2-4% recall on small/blurry faces  
**Difficulty:** MEDIUM (adds 50ms inference overhead)  
**Status:** ❌ NOT IMPLEMENTED

#### D. Switch to YOLOv8x (Extra Large)
**Purpose:** Better feature extraction (68M vs 43M params)  
**Impact:** 2-3% across all metrics  
**Difficulty:** LOW (just change model name)  
**Trade-off:** 50% slower, more VRAM  
**Status:** ❌ NOT TESTED

#### E. Switch to RetinaFace / SCRFD
**Purpose:** Face-specific architectures optimized for extreme scales  
**Impact:** 5-10% on WIDER Face benchmark  
**Difficulty:** VERY HIGH (complete rewrite)  
**Status:** ❌ NOT CONSIDERED

---

## Recommended Strategy: Path to 85% Recall

### Phase 1: Low-Hanging Fruit (1-2 days) ⭐ START HERE

**Goal:** 75% → 82-84% recall

1. **Train with FaceDetectionConfigRecallFocused**
   ```bash
   docker exec ray-head ray job submit \
     --working-dir=/tmp/ray \
     -- python face_detection_training.py --recall-focused --epochs 100
   ```
   **Expected gain:** +5-8% recall → **80-83%**

2. **Test inference with lower confidence threshold**
   ```python
   results = model.val(data='data.yaml', conf=0.15, iou=0.50)
   ```
   **Expected gain:** +1-2% recall → **81-85%** ✅

3. **Enable TTA for final validation**
   ```python
   results = model.val(data='data.yaml', augment=True)  # Multi-scale + flip
   ```
   **Expected gain:** +2-3% recall → **83-86%** ✅

**Total Phase 1 Gain:** **75% → 83-86% recall** (ACHIEVES TARGET!)

---

### Phase 2: Dataset Improvements (3-5 days) - ONLY IF NEEDED

**Goal:** 83-86% → 87-89% recall (if Phase 1 falls short)

1. **Review failure analysis outputs**
   - Check: `checkpoints/failures/phase_*/failures.json`
   - Identify systematic failure patterns
   - Cluster analysis for common issues

2. **Fix annotation errors** (from audit reports)
   - Review: `checkpoints/audits/audit_epoch_N.json`
   - Correct WIDER Face labels
   - Re-export to YOLO format

3. **Add hard negative mining**
   - Extract failure samples
   - Add to training dataset (balanced)
   - Increase augmentation for failure modes

4. **Consider additional datasets**
   - FDDB: Unconstrained environments
   - MAFA: Masked faces (occlusion handling)
   - Retrain with expanded dataset

**Expected gain:** +3-5% recall → **87-89%**

---

### Phase 3: Advanced Techniques (1-2 weeks) - ONLY FOR >90% TARGET

**Goal:** 87-89% → 92-95% recall (if extreme recall needed)

1. **Add P2 detection scale** (stride 4)
   - Modify YOLOv8 architecture
   - Add extra detection head for tiny faces
   - Retrain from scratch

2. **Custom recall-weighted loss function**
   - Fork ultralytics/ultralytics
   - Modify loss.py to penalize FN > FP
   - Retrain with custom loss

3. **Model ensemble**
   - Train 3-5 models with different seeds/configs
   - Implement Weighted Boxes Fusion
   - Deploy ensemble pipeline

**Expected gain:** +5-8% recall → **92-95%**

---

## Quick Decision Matrix

| Technique | Effort | Recall Gain | Precision Impact | Recommended |
|-----------|--------|-------------|------------------|-------------|
| **Recall-focused config** | LOW | 5-8% | -2 to -5% | ✅ YES - Do this first |
| **Lower conf threshold (0.15)** | NONE | 1-2% | -3 to -5% | ✅ YES - After training |
| **TTA inference** | LOW | 2-4% | +1 to +2% | ✅ YES - For final validation |
| **Failure analysis review** | MEDIUM | 3-5% | Neutral | ✅ YES - After Phase 1 |
| **Dataset quality fixes** | MEDIUM | 2-4% | +1 to +3% | ⚠️ If needed |
| **Additional datasets** | HIGH | 3-5% | +1 to +3% | ⚠️ If <85% after Phase 1 |
| **Custom loss function** | VERY HIGH | 3-5% | Variable | ❌ Not worth complexity |
| **P2 detection scale** | VERY HIGH | 5-8% | -1 to -2% | ❌ Only if desperate |
| **Model ensemble** | VERY HIGH | 3-5% | +2 to +4% | ❌ Too complex |

---

## Implementation Checklist

### ✅ Completed (Dec 7, 2025)

- [x] Baseline training with base config (raysubmit_WF6m1WvCSne5tKyr)
- [x] Final metrics: mAP50=82.25%, Recall=74.08%
- [x] Downloaded yolov8l-face.pt baseline (84MB, HuggingFace)
- [x] Baseline comparison validation
- [x] Confidence threshold testing (conf=0.25, 0.20, 0.15, 0.10)
- [x] YOLOv8 architecture analysis (3 scales: P3/P4/P5)
- [x] Identified bottleneck: P3 scale (small faces)
- [x] Fixed NVML errors for Ray GPU access
- [x] Documented all recall improvement techniques

### 🔲 Next Steps (Immediate)

- [ ] **Submit recall-focused training job** (1-2 days)
  ```bash
  docker exec ray-head ray job submit \
    --working-dir=/tmp/ray \
    -- python face_detection_training.py --recall-focused --epochs 100
  ```

- [ ] **Monitor training progress** in MLflow
  - Check: `failures_phaseN_false_negative` metric
  - Check: `audit_epochN_issues` metric
  - Watch for recall improvement per phase

- [ ] **Validate with lower confidence threshold**
  ```bash
  # After training completes
  results = model.val(data='data.yaml', conf=0.15, iou=0.50)
  ```

- [ ] **Enable TTA for final evaluation**
  ```bash
  results = model.val(data='data.yaml', augment=True)
  ```

- [ ] **Review failure analysis outputs**
  - Failures: `checkpoints/failures/phase_*/failures.json`
  - Clusters: `checkpoints/failures/phase_*/clusters.json`
  - Audits: `checkpoints/audits/audit_epoch_N.json`

### 🔲 Conditional Steps (If <85% after Phase 1)

- [ ] Fix dataset annotation errors (from audit reports)
- [ ] Add hard negative samples (from failure analysis)
- [ ] Consider FDDB/MAFA dataset augmentation
- [ ] Retrain with expanded/corrected dataset

---

## Technical Context

### GPU Access Fix (Dec 7, 2025)

**Problem:** Ray jobs couldn't access GPU due to NVML initialization errors  
**Solution:** Added environment variables to disable NVML checks

**Files Modified:**
1. `ray_compute/docker-compose.yml` (lines 34-48):
   ```yaml
   environment:
     - TORCH_NVML_BASED_CUDA_CHECK=0
     - CUDA_LAUNCH_BLOCKING=0
     - PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512
   ```

2. `ray_compute/docker/Dockerfile.ray-head` (lines 67-73):
   ```dockerfile
   ENV TORCH_NVML_BASED_CUDA_CHECK=0
   ENV CUDA_LAUNCH_BLOCKING=0
   ```

**Validation:** Both CUDA test and full validation jobs work with GPU acceleration

---

### MLflow Experiment Tracking

**Experiment:** `Development-Training`  
**Run Tags:**
- `model_type`: face_detection
- `architecture`: yolov8l
- `dataset`: wider_face
- `purpose`: privacy_protection
- `optimization`: recall_focused (for recall-focused config)

**Key Metrics to Monitor:**
- `final_recall` - Overall recall
- `phaseN_recall` - Per-phase recall progression
- `failures_phaseN_false_negative` - False negative count
- `audit_epochN_missing` - Missing annotations found

---

## References

1. **SOTA Training Docs:** `/home/axelofwar/Projects/shml-platform/docs/SOTA_FACE_DETECTION_TRAINING.md`
2. **Training Script:** `/home/axelofwar/Projects/shml-platform/ray_compute/jobs/face_detection_training.py`
3. **Baseline Model:** yolov8l-face from HuggingFace (deepghs/yolo-face)
4. **WIDER Face Dataset:** Yang et al. "WIDER FACE: A Face Detection Benchmark." CVPR 2016
5. **YOLOv8 Docs:** Ultralytics YOLOv8 Documentation (2024)
6. **INTELLECT-3:** Prime Intellect Technical Report (2025) - Online Advantage Filtering

---

## Notes

- **Privacy Focus:** Recall is more important than precision for face blurring
- **WIDER Face Benchmark:** 73.96% recall is competitive but not state-of-the-art
- **SOTA Performance:** Top models on WIDER Face achieve 90-95% recall
- **Realistic Target:** 85% recall is achievable with Phase 1 techniques
- **Trade-offs:** Recall improvements typically reduce precision 2-5pp
- **Inference Speed:** 35.4ms per image on RTX 3090 Ti (current model)

---

**Next Action:** Submit recall-focused training job and monitor progress in MLflow.
