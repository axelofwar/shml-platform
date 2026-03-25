---
name: fiftyone-datasets
description: "Inspect, query, and evaluate FiftyOne datasets on this platform. Use when the user asks about face detection datasets, evaluation results, failure clusters, sample tagging, brain operations, or launching the FiftyOne App."
license: MIT
compatibility: Requires fiftyone installed and FIFTYONE_DATABASE_URI pointing to mongodb://fiftyone-mongodb:27017. Read-only operations are safe during training.
metadata:
  author: shml-platform
  version: "1.0"
  db: mongodb://fiftyone-mongodb:27017
allowed-tools: Bash(python3:*) Bash(curl:*)
---

# FiftyOne Datasets Skill

## When to use this skill
Use this skill when the user asks to:
- List available FiftyOne datasets
- Inspect samples, views, tags, or label fields
- Summarise evaluation metrics (mAP, recall, precision, F1)
- Identify failure clusters — false positives / false negatives
- Run brain operations (uniqueness, hardness, mistakenness, UMAP embeddings)
- Launch the FiftyOne App for interactive visualisation
- Export hard examples or create filtered views for re-training
- Check FiftyOne / MongoDB health

## Platform Setup

- **MongoDB** (FiftyOne backend): `mongodb://fiftyone-mongodb:27017`
- **Set env before any import:**
  ```bash
  export FIFTYONE_DATABASE_URI=mongodb://fiftyone-mongodb:27017
  ```
- **SDK entry point:** `sdk/shml/integrations/fiftyone.py` → `FiftyOneClient`
- **Eval pipeline:** `ray_compute/jobs/evaluation/fiftyone_eval_pipeline.py`
- **Typical dataset names:** `phase9_rfdetr_eval`, `wider_face_val`, `pii_face_v*`

## Operations

### List datasets
```python
import os
os.environ.setdefault("FIFTYONE_DATABASE_URI", "mongodb://fiftyone-mongodb:27017")
import fiftyone as fo
print(fo.list_datasets())
```

Or via the SDK wrapper:
```bash
python3 - <<'EOF'
import sys; sys.path.insert(0, "sdk")
from shml.integrations.fiftyone import FiftyOneClient
c = FiftyOneClient()
print(c.list_datasets())
EOF
```

### Load dataset and show summary
```python
import os, fiftyone as fo
os.environ.setdefault("FIFTYONE_DATABASE_URI", "mongodb://fiftyone-mongodb:27017")
ds = fo.load_dataset("phase9_rfdetr_eval")
print(ds)           # counts, fields, tags
print(ds.stats())   # storage
```

### Inspect evaluation metrics
After an eval run has been stored (key `coco_eval` is typical):
```python
results = ds.load_evaluation_results("coco_eval")
results.print_report()           # full classification report
print(results.metrics())         # dict: mAP50, mAP, recall, precision, F1
```

To check what eval runs exist:
```python
print(ds.list_evaluations())
```

### View false negatives (missed faces)
```python
fn_view = ds.load_evaluation_results("coco_eval").view(
    eval_key="coco_eval", TP=False, FP=False, FN=True
)
print(f"False negatives: {len(fn_view)}")
for s in fn_view.head(5):
    print(s.filepath, s.tags)
```

### View false positives
```python
fp_view = ds.load_evaluation_results("coco_eval").view(
    eval_key="coco_eval", TP=False, FP=True, FN=False
)
print(f"False positives: {len(fp_view)}")
```

### Summarise failure clusters (hardest samples)
```python
# Requires brain run with hardness key
hard_view = ds.sort_by("hardness", reverse=True).limit(20)
for s in hard_view:
    print(s.filepath, round(getattr(s, "hardness", 0), 3))
```

### Brain operations (compute similarity / hardness / uniqueness)
```python
import fiftyone.brain as fob

# Uniqueness (find near-duplicates)
fob.compute_uniqueness(ds)

# Hardness (samples the model struggles with)
fob.compute_hardness(ds, "predictions")

# Image similarity (CLIP embeddings + UMAP)
fob.compute_similarity(ds, model="clip-vit-base32-torch", brain_key="img_sim")

# UMAP visualisation (requires embeddings first)
fob.compute_visualization(ds, embeddings="img_sim", method="umap", brain_key="umap")
```

### Tag samples for re-training
```python
# Tag the 50 hardest samples for review
hard_view = ds.sort_by("hardness", reverse=True).limit(50)
hard_view.tag_samples("needs_review")

# Export tagged samples
tagged = ds.match_tags("needs_review")
tagged.export(
    export_dir="/tmp/hard_examples",
    dataset_type=fo.types.COCODetectionDataset,
    label_field="ground_truth",
)
```

### Launch FiftyOne App (local / remote)
```bash
# Start on host (opens browser at http://localhost:5151)
FIFTYONE_DATABASE_URI=mongodb://fiftyone-mongodb:27017 python3 -c "
import fiftyone as fo
ds = fo.load_dataset('phase9_rfdetr_eval')
session = fo.launch_app(ds, port=5151, remote=True)
session.wait()
"
```

### Run the full evaluation pipeline (Ray job)
```bash
cd ray_compute/jobs/evaluation
FIFTYONE_DATABASE_URI=mongodb://fiftyone-mongodb:27017 \
python3 fiftyone_eval_pipeline.py \
  --model-path /path/to/best.pt \
  --dataset-name phase9_rfdetr_eval
```

## Typical workflow for a new model checkpoint

1. Run evaluation pipeline (creates `_eval` dataset + stores results)
2. `ds.load_evaluation_results("coco_eval").print_report()` — check recall vs baseline
3. If recall < 0.760: tag `fn_view` samples as `recall_failure`, export for hard-negative mining
4. If recall > target: summarise metrics → create GitLab issue to close the training round

## Expected Dataset Fields

| Field | Type | Notes |
|---|---|---|
| `ground_truth` | Detections | WIDER Face / PII ground truth |
| `predictions` | Detections | Model inference results |
| `hardness` | Float | fob.compute_hardness score |
| `uniqueness` | Float | fob.compute_uniqueness score |
| `mistakenness` | Float | fob.compute_mistakenness score |

## Safety Constraints

- ✅ `list_datasets`, `load_dataset`, `print_report` — safe at any time
- ✅ All read-only views — safe during training
- ⚠️ `fob.compute_similarity(model=...)` — downloads CLIP on first run, ~400 MB
- ⚠️ `launch_app` — binds a port; avoid on production without explicit intent
- ❌ `ds.delete()` / `fo.delete_dataset()` — requires explicit user confirmation
