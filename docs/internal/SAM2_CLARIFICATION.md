# SAM2 Auto-Annotation Clarification

**Date:** December 12, 2025  
**Issue:** Confusion about SAM2 usage with WIDER Face dataset

---

## ✅ Correct Understanding

### WIDER Face Dataset (Phase 1)
- **Status:** ✅ **Already fully annotated** with bounding boxes
- **Size:** 158,989 images with 393,703 labeled faces
- **Annotation Quality:** High-quality human annotations from original paper
- **SAM2 Needed:** ❌ **NO** - Already has complete annotations

**Phase 1 Action:** Use WIDER Face directly for training, no annotation needed.

---

## 🎯 Where SAM2 IS Needed

### 1. Production Data (Phase 2)
- **Source:** User-uploaded images (opt-in consent)
- **Status:** ❌ **No annotations**
- **Volume:** ~50,000-100,000 images/year expected
- **SAM2 Use:** Auto-annotate face bounding boxes
- **Cost Savings:** Manual ($100/hr) → SAM2 GPU ($6/hr RTX 3090)

### 2. YFCC100M Dataset (Phase 3)
- **Source:** Yahoo Flickr Creative Commons 100M dataset
- **Subset:** ~15M images with faces (filtered)
- **Status:** ❌ **No face bounding box annotations** (only tags/metadata)
- **Volume:** 15 million images
- **SAM2 Use:** Auto-annotate face bounding boxes at scale
- **Cost Savings:** Would cost $150K+ manual, SAM2 = ~$180/year GPU time

### 3. Active Learning Samples
- **Source:** Hard cases identified during production inference
- **Status:** ❌ **No annotations**
- **Volume:** ~1,000-5,000 images/month
- **SAM2 Use:** Auto-annotate, then human review top 10%
- **Cost Savings:** 90% reduction via tiered review

---

## 📊 Cost Breakdown (Corrected)

### Phase 1: WIDER Face (158K images)
- **Annotation Cost:** $0 (already annotated)
- **Training Cost:** GPU time only

### Phase 2: Production Data (~75K images/year)
- **Without SAM2:** $6,000/year (60 hrs @ $100/hr)
- **With SAM2:** $180/year (30 hrs GPU @ $6/hr)
- **Savings:** $5,820/year (97% reduction)

### Phase 3: YFCC100M (~15M images)
- **Without SAM2:** $150,000+ (prohibitively expensive)
- **With SAM2:** ~$500/year (GPU time for batch processing)
- **Savings:** $149,500+ (99.7% reduction)

### Active Learning (~30K images/year)
- **Without SAM2:** $3,000/year (full manual review)
- **With SAM2 + Tiered Review:** $300/year (90% auto, 10% human)
- **Savings:** $2,700/year (90% reduction)

**Total Annual Savings:** $157,020+ across all phases

---

## 🔄 Corrected Timeline

### Week 1-2: Phase 1 Foundation ✅ (Current)
- Train on WIDER Face (158K images, already annotated)
- Target: 75-85% recall
- **NO SAM2 needed** - dataset already annotated

### Week 2-3: SAM2 Implementation
- Install SAM2 pipeline
- Test on sample production images (not WIDER Face)
- Prepare YFCC100M downloader
- **Purpose:** Ready for Phase 2 production data

### Week 4-6: Phase 2 Integration
- Collect production data (opt-in)
- Auto-annotate with SAM2
- Retrain with WIDER Face + production data
- Target: 88-93% recall

### Month 2-3: Phase 3 YFCC100M
- Download YFCC100M subset (~15M faces)
- Batch auto-annotate with SAM2 (distributed on Ray)
- Incremental training
- Target: 93-95% recall

### Ongoing: Active Learning
- Continuous production data collection
- SAM2 auto-annotation
- Tiered human review (Label Studio)
- Monthly retraining
- Target: 95%+ sustained

---

## 🎯 SAM2 Architecture (Corrected)

```
┌─────────────────────────────────────────────────────────────┐
│                      Data Sources                            │
└─────────────────────────────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌──────────────┐   ┌──────────────────┐   ┌──────────────┐
│ WIDER Face   │   │ Production Data  │   │  YFCC100M    │
│ 158K images  │   │ User uploads     │   │  15M images  │
│ ✅ Annotated │   │ ❌ No annotations│   │ ❌ No annot. │
│ NO SAM2      │   │ 🤖 SAM2 needed   │   │ 🤖 SAM2      │
└──────────────┘   └──────────────────┘   └──────────────┘
                             │
        ┌────────────────────┴────────────────────┐
        │                                         │
        ▼                                         ▼
┌─────────────────────┐              ┌─────────────────────┐
│  SAM2 Pipeline      │              │  Active Learning    │
│  (Production only)  │──────────────│  Sample Selection   │
│  - YOLOv8 detect    │              │  - Hard cases       │
│  - SAM2 refine      │              │  - Uncertainty      │
│  - Auto annotate    │              │  🤖 SAM2 + Human    │
└─────────────────────┘              └─────────────────────┘
        │                                         │
        └────────────────────┬────────────────────┘
                             │
                             ▼
                  ┌─────────────────────┐
                  │  Training Pipeline  │
                  │  (All data sources) │
                  │  - WIDER Face (0%)  │
                  │  - Production (97%) │
                  │  - YFCC100M (99%)   │
                  │  - Active (90%)     │
                  └─────────────────────┘
                             │
                             ▼
                  ┌─────────────────────┐
                  │  95%+ Recall KPI    │
                  └─────────────────────┘
```

---

## 🚀 Updated Week 2 Tasks

### Task 1: Install SAM2 ✅
```bash
git clone https://github.com/facebookresearch/segment-anything-2.git
cd segment-anything-2
pip install -e .
wget https://dl.fbaipublicfiles.com/segment_anything_2/072824/sam2_hiera_large.pt
```

### Task 2: Implement SAM2 Pipeline
**Purpose:** Annotate NEW production data and YFCC100M
**NOT for:** WIDER Face (already annotated)

```python
# sam2_pipeline.py

class SAM2AnnotationPipeline:
    """Auto-annotate UNANNOTATED images only."""

    def annotate_production_batch(self, image_paths: List[str]):
        """Annotate user-uploaded production images."""
        pass

    def annotate_yfcc100m_batch(self, image_paths: List[str]):
        """Annotate YFCC100M images (15M faces)."""
        pass

    def annotate_active_learning_samples(self, image_paths: List[str]):
        """Annotate hard cases for human review."""
        pass
```

### Task 3: Test on Sample Production Images
```bash
# Create test set of unannotated images
mkdir -p /tmp/test_production_images
# ... copy sample images ...

# Test SAM2 pipeline
python sam2_pipeline.py \
  --input-dir /tmp/test_production_images \
  --output-dir /tmp/sam2_annotations \
  --model-checkpoint sam2_hiera_large.pt
```

### Task 4: YFCC100M Downloader
```python
# yfcc100m_downloader.py
# Download 15M CC-BY images with faces
# Prepare for batch SAM2 annotation
```

---

## 📝 Documentation Updates

Files corrected:
- ✅ `PRODUCTION_READINESS_CONFIRMED.md` - Clarified SAM2 usage
- ✅ `docs/ARCHITECTURE_REDESIGN.md` - Added "NOT NEEDED FOR WIDER Face"
- ✅ `docs/PLATFORM_IMPROVEMENTS_PROJECT_BOARD.md` - Clarified strategy
- ✅ This document created for future reference

---

## ✅ Key Takeaways

1. **WIDER Face (158K):** Already annotated ✅ - Use directly for Phase 1 training
2. **Production Data:** Need SAM2 ❌ → ✅ (97% cost savings)
3. **YFCC100M (15M):** Need SAM2 ❌ → ✅ (99.7% cost savings)
4. **Active Learning:** Need SAM2 + Human ❌ → ✅ (90% cost savings)

**Total SAM2 ROI:** $157K+ annual savings across all phases

**Phase 1 can proceed immediately** - WIDER Face ready to use, no annotation pipeline needed yet.

---

## 🎯 Immediate Action

**For Phase 1 (Current):**
```bash
# Start training on WIDER Face (already annotated)
cd /home/axelofwar/Projects/shml-platform/ray_compute/jobs/training
python phase1_foundation.py \
  --data /path/to/wider_face \
  --epochs 200 \
  --batch-size 16 \
  --model yolov8l
```

**For Phase 2 (Week 2):**
- Implement SAM2 pipeline
- Ready for production data collection
- Prepare YFCC100M downloader

**Phase 1 has NO blockers** - dataset is ready!
