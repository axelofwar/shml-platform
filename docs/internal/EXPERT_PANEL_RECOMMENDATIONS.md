# Expert Panel Recommendations (2025-12-12)

**Status:** Phase 1 Training Running | SAM3 Pipeline Initialized
**Objective:** Identify high-value tasks to execute during training downtime.

---

## 🚨 Critical Recommendation: Integrate Trajectory Segment Filter (TSF)

**Expert:** ML Research Lead
**Impact:** High (Immediate Training Speedup)
**Effort:** Low (Code exists, needs wiring)

> "We have implemented the `TrajectorySegmentFilter` class in `libs/training/trajectory_filter.py`, but it is **NOT** currently used in the active training loop (`phase1_foundation.py`).
>
> The current `OnlineAdvantageFilter` only looks at individual batch losses. TSF looks at *sequences* of batches to identify if the model is 'stuck' or learning well. Integrating this NOW means Phase 2 training will converge **5-10% faster** by skipping uninformative data segments."

**Action Item:**
- Modify `ray_compute/jobs/training/phase1_foundation.py` to import and use `TrajectorySegmentFilter`.

---

## 🏗️ Infrastructure Recommendation: Streaming Dataloader for YFCC100M

**Expert:** Systems Engineer
**Impact:** Critical (Enables Phase 2)
**Effort:** Medium

> "We are downloading 65GB+ of YFCC100M data. Standard PyTorch `DataLoader` will struggle with random access on this scale, especially if we expand to the full dataset.
>
> We need a **Streaming Dataloader** (like WebDataset or Ray Data) that can stream shards of data to the GPU workers without loading everything into RAM. This is a prerequisite for Phase 2."

**Action Item:**
- Create `libs/data/streaming_loader.py` using Ray Data or WebDataset patterns.

---

## 🔄 Product Recommendation: Feedback Loop API

**Expert:** Product Manager
**Impact:** High (Flywheel Effect)
**Effort:** Medium

> "We have a Chat UI and an Agent Service. When a user sees a missed face or a wrong box, they need a way to 'Report' it.
>
> This 'Report' should:
> 1. Save the image + wrong annotation to a 'Review Queue'.
> 2. Send it to Roboflow project for correction (Human-in-the-loop).
> 3. Add it to the next training batch.
>
> This closes the loop and creates the **Data Flywheel**."

**Action Item:**
- Design `POST /api/feedback/correction` endpoint in `inference/gateway`.

---

## 📋 Summary of Priorities

1.  **Integrate TSF** (Immediate - affects training quality).
2.  **Streaming Dataloader** (Preparation - affects scale).
3.  **Feedback Loop** (Strategic - affects long-term value).
