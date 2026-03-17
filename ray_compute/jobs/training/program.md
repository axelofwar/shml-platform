# Autoresearch Program — Face Detection (YOLOv8m-P2)

> This file is the Karpathy-style "program.md" that teaches the autoresearch
> agent about the problem domain, constraints, and history. The agent reads this
> before proposing hyperparameter mutations.

## Problem Statement

We are training a **YOLOv8m-P2 face detection model** (43.6M params) on WIDER Face
dataset, aiming to maximize recall (face detection is recall-sensitive — missed faces
are worse than false positives) while maintaining high mAP50.

### Why P2 Head?
Standard YOLO detects at P3-P5 feature scales. The P2 detection head adds a higher-
resolution feature map (stride=4 instead of 8), producing 320×320 feature maps at
1280px input. This dramatically improves detection of **tiny and occluded faces** in
crowd scenes, which is the WIDER Face Hard subset's main challenge.

## Hardware Constraints

| Resource | Value | Implication |
|----------|-------|-------------|
| GPU | RTX 3090 Ti | 24 GB VRAM (full — Qwen stopped during training) |
| RAM | 64 GB | cache=ram fits entire WIDER train set (~1.6 GB) |
| **Default** | **imgsz=960, ms=0.5, b=1** | **Trains at 480–1472px; peak ~18 GB; nbs=64 grad accum** |
| ms=0.33/b=2 @ 960 | 640–1280px | Peak ~14 GB, fastest throughput |
| imgsz=1120/ms=0.33/b=1 | 736–1504px | Peak ~20 GB, higher ceiling |
| imgsz=1280/ms=0.25/b=1 | 960–1632px | Peak ~23 GB, tight but fits |
| 1280px fixed/b=1 | 1280px | ~15 GB, control experiment |

**Rules:** `cache=ram` always (64 GB RAM handles it). `batch=1` for any config peaking above 1280px.
`nbs=64` for gradient accumulation. `workers ≤ 2`.

## Training History

| Phase | Model | mAP50 | Recall | Precision | F1 | Notes |
|-------|-------|-------|--------|-----------|-----|-------|
| 1 | YOLOv8l | 0.809 | — | — | — | Foundation |
| 3 | YOLOv8m-P2 | 0.848 | — | — | — | P2 head added |
| **5** | **YOLOv8m-P2** | **0.798** | **0.716** | **0.889** | **0.793** | **YOLO champion** |
| 8 | YOLOv8m-P2 | 0.795 | — | — | — | SDK integration run |
| **9** | **YOLOv8m-P2** | **0.814** | **0.729** | **0.883** | **0.797** | **Latest baseline** |
| 10 | YOLOv8m-P2 | — | — | — | — | CRASHED (OOM at 1280px) |

### Key Observations
- Phase 5→9: mAP50 improved (+0.016), recall improved (+0.013), precision traded slightly (-0.006)
- Phase 9 used cosine LR, AdamW, gradient clipping, copy-paste augmentation
- Phase 10 attempted progressive 640→960→1280px but crashed due to system memory pressure
- The production model (YOLOv11m-Face) achieves ~97% mAP on WIDER Hard — this is our ceiling reference

### Round 1 Autoresearch Results (19 experiments, **0 kept**)
- **Root cause:** All experiments ran at 640px while Phase 9 was trained at 960px
- Resolution dominates all other hyperparameters:
  - 640px (14 exps): best mAP50 = 0.743
  - 800px (1 exp): mAP50 = 0.792
  - 960px (1 exp): mAP50 = 0.797 (only 0.001 below Phase 5 floor in 8 epochs!)
- 8 epochs was too few; aggressive augmentation (scale=0.9, hsv_s=0.7) hurt at short duration
- **Fix:** multi_scale=0.5 trains at 480–1472px per batch; P2 head gets full resolution diversity

## Loss Function Guidance

YOLO's loss has three components:

1. **box** (bounding box regression): Higher weight → tighter, more precise boxes
   - Default: 7.5. Phase 10 used 10.0 (recall-focused)
   - Range to explore: 5.0 — 15.0

2. **cls** (classification): Weight for class prediction
   - Since we have only ONE class (face), this is less critical
   - Lower values (0.1-0.3) can help the model focus on localization
   - Range to explore: 0.1 — 0.5

3. **dfl** (distribution focal loss): Controls box edge quality
   - Higher → smoother, more robust box predictions
   - Default: 1.5. Phase 10 used 2.0
   - Range to explore: 1.0 — 3.0

## Augmentation Effects

| Augmentation | Effect on Recall | Effect on Precision | Notes |
|-------------|------------------|--------------------:|-------|
| mosaic | ↑↑ (multi-face scenes) | → | Essential for crowd detection |
| mixup | ↑ (regularization) | ↓ slight | Diminishing returns above 0.2 |
| copy_paste (flip) | ↑↑ (more face instances) | → | Best augmentation for our task |
| scale | ↑ (scale invariance) | → | Higher values = more aggressive |
| close_mosaic N | ↑ (clean convergence) | ↑ | Disable mosaic for last N epochs |
| label_smoothing | → | → | Minor effect, 0.05-0.1 safe |

## What Doesn't Work (from our experience)

1. **Training at lower resolution than baseline** → Round 1 proved 640px can never beat 960px baseline
2. **cache=False at high resolution** → I/O bottleneck; cache=ram is cheap with 64 GB RAM
3. **batch > 1 at peak > 1280px** → VRAM OOM (multi_scale peaks can exceed imgsz by 50%)
4. **multi_scale with batch > 2** → Peak resolution * batch exceeds 24 GB
5. **workers > 2** → CPU/RAM pressure contributes to system instability
6. **Very high LR (>0.002)** → Training diverges (NaN losses within 5 epochs)
7. **Too few epochs (< 10)** → Insufficient convergence signal, especially with augmentation
8. **Aggressive augmentation + short runs** → scale=0.9, hsv_s=0.7 hurt at < 15 epochs

## Success Criteria

An experiment is KEPT if it satisfies ALL of:
- mAP50 ≥ Phase 5 baseline (0.798) — absolute floor
- Recall ≥ Phase 5 baseline (0.716) — absolute floor
- mAP50 > current best (starts at Phase 9: 0.814)
- OR: mAP50 = current best AND recall > current best recall

**Stretch goal:** Recall > 0.80 with Precision > 0.85

## Experiment Design Principles

1. **Change one thing at a time** when exploring a new dimension
2. **Combine winning changes** from successful single-variable experiments
3. **15-20 epochs minimum** for meaningful signal (8 was too short in Round 1)
4. **Always start from Phase 9 weights** (unless running cumulative mode)
5. **Log everything** — the journal is the output, not just the best weights
6. **Use multi_scale** by default — the P2 head benefits from scale diversity
7. **cache=ram always** — zero I/O penalty with 64 GB RAM
8. **batch=1 with nbs=64** when peak resolution could exceed 1280px
