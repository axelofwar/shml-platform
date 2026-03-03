# PII Face Detection — Improvement Plan
## SHML Platform: Benchmark → Fine-Tune → Re-Benchmark Pipeline

> **Last Updated:** February 2026
> **Status:** Implementation Phase
> **Target:** Production-grade face detection for PII compliance

---

## 1. Executive Summary

This plan establishes a systematic pipeline to evaluate, fine-tune, and iterate on face detection models for PII (Personally Identifiable Information) compliance. The goal is to achieve reliable face detection that can be used for automated blurring, redaction, or consent-verification workflows.

**Pipeline:** `benchmark.py` → `train_rfdetr_face.py` → `benchmark.py --rfdetr-checkpoint`

### KPI Targets

| Metric | Target | Rationale |
|--------|--------|-----------|
| mAP50 | ≥ 94% | High overall detection quality |
| Recall | ≥ 95% | **Critical** — missed faces = PII violation |
| Precision | ≥ 90% | Minimize false positives (unnecessary blurring) |
| Hard mAP50 | ≥ 85% | Performance on occluded/crowded scenes |
| Tiny (<32px) Recall | ≥ 85% | Distant/small faces must still be detected |

**Why recall is paramount:** In PII compliance, a missed face (false negative) is far worse than a false positive (extra blur region). A 95% recall target means ≤5% of faces escape detection.

---

## 2. Current Baselines

### Model Inventory

| Model | Type | mAP50 | Recall | Precision | Notes |
|-------|------|-------|--------|-----------|-------|
| YOLOv8m (Phase 5) | Fine-tuned | 0.859 | 0.769 | 0.881 | Best existing model |
| YOLOv8m-P2 (Phase 8) | Fine-tuned | 0.812 | 0.738 | 0.891 | P2 head for small faces |
| YOLOv11m-face | Pre-trained | TBD | TBD | TBD | HuggingFace face-specific |
| RF-DETR Large (zero-shot) | COCO pretrained | 0.001 | ~0 | N/A | No face class in COCO |
| RF-DETR Large (fine-tuned) | TBD | TBD | TBD | TBD | After training pipeline |

### Dataset: WIDER Face

| Split | Images | Annotations | Source |
|-------|--------|-------------|--------|
| Train | 12,876 | 156,994 | WIDER Face (human-annotated) |
| Val | 3,222 | 39,112 | WIDER Face (human-annotated) |

**Ground truth provenance:** 100% human-annotated from the WIDER Face benchmark. Zero model involvement in GT labels. Full chain: `wider_face_val_bbx_gt.txt` → YOLO `.txt` → COCO `_annotations.coco.json`.

---

## 3. Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    BENCHMARK → FINE-TUNE → RE-BENCHMARK            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────────────┐                                           │
│  │ face_detection_       │  1. Create shared FiftyOne dataset       │
│  │ benchmark.py          │  2. Run YOLO + RF-DETR inference         │
│  │ (zero-shot baselines) │  3. COCO eval per model                  │
│  │                       │  4. Brain: CLIP → similarity → hardness  │
│  │                       │  5. Export hard samples                   │
│  └──────────┬────────────┘                                          │
│             │                                                       │
│             ▼                                                       │
│  ┌──────────────────────┐                                           │
│  │ train_rfdetr_face.py  │  1. Ensure COCO annotations              │
│  │ (fine-tune RF-DETR)   │  2. RF-DETR native .train() API         │
│  │                       │  3. on_epoch_end → Prometheus metrics    │
│  │                       │  4. on_train_end → FiftyOne + MLflow     │
│  │                       │  5. Save best checkpoint                 │
│  └──────────┬────────────┘                                          │
│             │                                                       │
│             ▼                                                       │
│  ┌──────────────────────┐                                           │
│  │ face_detection_       │  1. Same dataset, add finetuned preds    │
│  │ benchmark.py          │  2. 3-way comparison table               │
│  │ (--rfdetr-checkpoint) │  3. Updated Brain + hard samples         │
│  │                       │  4. Model disagreement analysis          │
│  └──────────────────────┘                                           │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Platform Integration Map

| Service | Benchmark | Training | Re-Benchmark |
|---------|-----------|----------|--------------|
| **FiftyOne** | Shared dataset, Brain, saved views | Post-training eval dataset | Updated predictions + Brain |
| **MLflow** | Per-model experiment logging | Built-in `mlflow=True` + artifacts | Updated experiment comparison |
| **Nessie** | Branch per benchmark run | Branch per training experiment | Tag for production candidate |
| **Prometheus** | Final metrics push | Real-time per-epoch gauges | Updated comparison metrics |
| **Feature Store** | Hard examples → pgvector | Eval + lineage materialization | Updated hard example pool |
| **GPU Yield** | Pre-inference yield/reclaim | Pre-training yield/reclaim | Pre-inference yield/reclaim |

---

## 4. Phase-by-Phase Execution

### Phase 1: Zero-Shot Baselines (benchmark.py)

**Goal:** Establish performance floor for both models on WIDER Face val.

```bash
# Inside ray-head container
python face_detection_benchmark.py --max-samples 500  # quick test
python face_detection_benchmark.py                     # full 3,222 images
```

**Expected outputs:**
- FiftyOne dataset `face-detection-model-comparison` with toggleable predictions
- YOLO baseline: ~70-80% mAP50 (face-specific pretraining)
- RF-DETR baseline: ~0.1% mAP50 (no face class)
- Brain computations: CLIP embeddings, similarity, hardness
- Hard sample views in FiftyOne for visual inspection

### Phase 2: RF-DETR Fine-Tuning (train_rfdetr_face.py)

**Goal:** Train RF-DETR to achieve competitive face detection.

```bash
# Quick validation (1 epoch)
python train_rfdetr_face.py --epochs 1 --dry-run

# Standard training (~4 hours on 3090 Ti)
python train_rfdetr_face.py --epochs 30 --batch-size 4

# Conservative (if OOM)
python train_rfdetr_face.py --epochs 30 --batch-size 2 --grad-accum 8
```

**Training config:**
| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Epochs | 30 | Sufficient for fine-tuning on 12K images |
| Batch size | 4 | Fits in 24GB VRAM with 704×704 |
| Grad accum | 4 | Effective batch = 16 |
| LR (decoder) | 1e-4 | Standard fine-tuning rate |
| LR (encoder) | 1.5e-5 | Lower for frozen DINOv2 backbone |
| Warmup | 3 epochs | Stabilize early training |
| Resolution | 704×704 | RF-DETR native resolution |
| EMA | True | Smoother convergence |
| Multi-scale | True | Better generalization across face sizes |

**Expected outputs:**
- Best checkpoint: `/tmp/ray/checkpoints/face_detection/rfdetr_face_best.pth`
- MLflow experiment `rfdetr-face-finetune` with per-epoch metrics
- Nessie tag `rfdetr-face-{timestamp}`
- Prometheus live dashboard during training

### Phase 3: Re-Benchmark with Fine-Tuned Model

**Goal:** Quantify improvement and compare against YOLOv11m-face.

```bash
python face_detection_benchmark.py \
    --rfdetr-checkpoint /tmp/ray/checkpoints/face_detection/rfdetr_face_best.pth
```

**Expected outputs:**
- 3-way comparison: YOLO vs RF-DETR zero-shot vs RF-DETR fine-tuned
- Updated FiftyOne dataset with `predictions_rfdetr_finetuned` field
- Size-bucketed evaluation (tiny/small/medium/large faces)
- Model disagreement analysis (where models differ)
- KPI gap report against targets

---

## 5. Hard Sample Analysis Strategy

### FiftyOne Brain Pipeline

The benchmark script runs a complete Brain analysis using CLIP embeddings:

1. **Compute embeddings** — CLIP ViT-B/32 for 512-dimensional feature vectors
2. **Similarity index** — Find visually similar images for data augmentation
3. **Uniqueness scores** — Identify rare/unusual samples
4. **Per-model hardness** — Separate hardness scores for each model's predictions
5. **UMAP visualization** — 2D projection for cluster analysis

### Hard Sample Categories

| Category | Description | FiftyOne View |
|----------|-------------|---------------|
| **High hardness** | Low confidence, many misses | `hard_samples_{model}` |
| **Tiny faces** | GT faces < 32px | `tiny_faces` |
| **Crowded scenes** | > 20 faces per image | `crowded_scenes` |
| **Model disagreement** | One model detects, other misses | `model_disagreement` |
| **Occluded faces** | Partial visibility | Cluster analysis |

### Active Learning Loop

```
Hard samples identified → Export to JSON → Targeted augmentation →
Re-train with emphasis → Re-benchmark → Iterate
```

**Export paths:**
- JSON: `/tmp/ray/data/hard_samples/hard_samples_{model}.json`
- Feature Store: `feature_hard_examples` table (pgvector, 512d CLIP embeddings)

---

## 6. Model Selection Criteria

### Decision Matrix

| Factor | YOLO | RF-DETR | Weight |
|--------|------|---------|--------|
| mAP50 | TBD | TBD | 25% |
| Recall | TBD | TBD | **30%** |
| Tiny face recall | TBD | TBD | 15% |
| Inference speed | ~5-10ms | ~30-50ms | 10% |
| Hard sample mAP | TBD | TBD | 10% |
| Architecture fit | Anchor-based | Transformer | 10% |

**Notes:**
- Recall gets highest weight (PII compliance)
- Inference speed matters for real-time video processing
- RF-DETR's DINOv2 backbone may excel at tiny/occluded faces
- YOLO's speed advantage is significant for edge deployment

### When to Choose RF-DETR

- Recall > YOLO by 3%+ (justifies slower inference)
- Hard sample mAP significantly better
- Tiny face detection meaningfully improved
- Batch processing (speed less critical)

### When to Choose YOLO

- Comparable recall (within 2%)
- 5-10x faster inference
- Real-time video requirements
- Edge deployment constraints

---

## 7. Iteration Strategy

### Round 1: Baseline Comparison
1. Run `face_detection_benchmark.py` (zero-shot)
2. Analyze FiftyOne Brain results
3. Identify hard sample categories
4. Document baseline gaps

### Round 2: First Fine-Tune
1. Train RF-DETR: `train_rfdetr_face.py --epochs 30`
2. Re-benchmark: `face_detection_benchmark.py --rfdetr-checkpoint ...`
3. Compare: YOLO vs RF-DETR fine-tuned
4. Document improvement

### Round 3: Targeted Improvement (if needed)
Based on Round 2 gaps:

| Gap | Action |
|-----|--------|
| Low tiny recall | Increase resolution to 800×800, multi-scale training |
| High false negatives | Lower confidence threshold, retrain with hard samples |
| Occlusion failures | Add MoA or CrowdHuman data |
| Crowded scene errors | Increase num_queries, use NMS post-processing |

### Round 4: Production Readiness
1. Stress test on diverse data (non-WIDER Face)
2. Inference latency profiling (batch + single-image)
3. Integration test with PII redaction pipeline
4. Deploy best model with `@champion` alias in MLflow

---

## 8. Success Criteria

### Minimum Viable (for initial deployment)
- [ ] mAP50 ≥ 85%
- [ ] Recall ≥ 90%
- [ ] Precision ≥ 85%
- [ ] End-to-end pipeline working (benchmark → train → re-benchmark)

### Target (for PII compliance)
- [ ] mAP50 ≥ 94%
- [ ] Recall ≥ 95%
- [ ] Precision ≥ 90%
- [ ] Hard mAP50 ≥ 85%
- [ ] Tiny Recall ≥ 85%

### Stretch (best-in-class)
- [ ] mAP50 ≥ 96%
- [ ] Recall ≥ 97%
- [ ] Sub-20ms inference (YOLO) or sub-50ms (RF-DETR)
- [ ] Cross-dataset generalization (FDDB, AFW)

---

## 9. Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| RF-DETR fine-tuning underperforms | Can't reach YOLO baseline | Fall back to YOLO; try YOLO fine-tuning on merged data |
| CUDA OOM during training | Training fails | Reduce batch_size to 2, increase grad_accum |
| Ephemeral annotations lost | Training data gone | `ensure_coco_annotations()` auto-regenerates from YOLO labels |
| Small face detection gap | PII violations | Multi-scale training + higher resolution + P2-style detection head |
| Model disagreement high | Hard to pick winner | Ensemble: run both, union of detections |
| Overfit to WIDER Face | Poor real-world performance | Validate on FDDB/CelebA; add CrowdHuman data |

---

## 10. File Reference

| File | Purpose |
|------|---------|
| `ray_compute/jobs/inference/face_detection_benchmark.py` | Dual-model benchmark with full platform integration |
| `ray_compute/jobs/training/train_rfdetr_face.py` | RF-DETR fine-tuning on WIDER Face |
| `ray_compute/jobs/training/data/yolo_to_rfdetr_coco.py` | YOLO→COCO format converter |
| `ray_compute/jobs/evaluation/fiftyone_eval_pipeline.py` | FiftyOne Brain evaluation (reference) |
| `ray_compute/jobs/inference/rfdetr_inference_baseline.py` | RF-DETR zero-shot baseline (reference) |
| `ray_compute/jobs/utils/gpu_yield.py` | GPU yield/reclaim utilities |

---

## 11. Quick Start

```bash
# Enter the ray-head container
docker exec -it ray-head bash
cd /home/ray/jobs

# Step 1: Zero-shot baselines
python inference/face_detection_benchmark.py

# Step 2: Fine-tune RF-DETR
python training/train_rfdetr_face.py --epochs 30

# Step 3: Re-benchmark with fine-tuned model
python inference/face_detection_benchmark.py \
    --rfdetr-checkpoint /tmp/ray/checkpoints/face_detection/rfdetr_face_best.pth

# View results in FiftyOne
# Navigate to Homer dashboard → FiftyOne → dataset "face-detection-model-comparison"
```
