---
name: face
description: "Skill for the Face area of shml-platform. 77 symbols across 16 files."
---

# Face

77 symbols | 16 files | Cohesion: 77%

## When to Use

- Working with code in `libs/`
- Understanding how save, main, compute_embeddings work
- Modifying face-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `libs/evaluation/face/evaluate_face_detection.py` | load_model, evaluate, _prepare_validation_data, _run_inference, _analyze_results (+17) |
| `libs/evaluation/face/wider_face_eval.py` | PIIEnterpriseStandards, get_compliance_report, to_dict, ComparisonResult, WIDERFaceEvaluator (+14) |
| `libs/evaluation/face/tiny_face_augmentation.py` | TinyFaceRegion, identify_tiny_faces, cluster_nearby_faces, _create_region_from_cluster, apply_zoom (+2) |
| `libs/evaluation/face/fiftyone_eval_pipeline.py` | load_or_create_dataset, run_model_predictions, run_evaluation, run_brain_computations, export_hard_examples (+1) |
| `libs/evaluation/face/pr_curve_sweep.py` | detect_val_dataset, run_validation, conf_sweep, iou_sweep, plot_pr_curve (+1) |
| `sdk/shml/integrations/fiftyone.py` | compute_embeddings, compute_similarity, compute_uniqueness, compute_hardness, compute_visualization |
| `scripts/registry/init_fiftyone_datasets.py` | _ensure_or_update_dataset, main |
| `ray_compute/jobs/inference/face_detection_benchmark.py` | run_brain_computations, run_coco_eval |
| `sdk/shml/config.py` | save |
| `ray_compute/jobs/evaluation/fiftyone_eval_pipeline.py` | run_fiftyone_evaluation |

## Entry Points

Start here when exploring this area:

- **`save`** (Function) — `sdk/shml/config.py:721`
- **`main`** (Function) — `scripts/registry/init_fiftyone_datasets.py:109`
- **`compute_embeddings`** (Function) — `sdk/shml/integrations/fiftyone.py:222`
- **`compute_similarity`** (Function) — `sdk/shml/integrations/fiftyone.py:261`
- **`compute_uniqueness`** (Function) — `sdk/shml/integrations/fiftyone.py:292`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `PIIEnterpriseStandards` | Class | `libs/evaluation/face/wider_face_eval.py` | 123 |
| `ComparisonResult` | Class | `libs/evaluation/face/wider_face_eval.py` | 269 |
| `WIDERFaceEvaluator` | Class | `libs/evaluation/face/wider_face_eval.py` | 295 |
| `TinyFaceRegion` | Class | `libs/evaluation/face/tiny_face_augmentation.py` | 41 |
| `EvaluationResult` | Class | `libs/evaluation/face/wider_face_eval.py` | 222 |
| `EvaluationConfig` | Class | `libs/evaluation/face/evaluate_face_detection.py` | 72 |
| `FaceDetectionEvaluator` | Class | `libs/evaluation/face/evaluate_face_detection.py` | 350 |
| `MetricsCalculator` | Class | `libs/evaluation/face/evaluate_face_detection.py` | 114 |
| `save` | Function | `sdk/shml/config.py` | 721 |
| `main` | Function | `scripts/registry/init_fiftyone_datasets.py` | 109 |
| `compute_embeddings` | Function | `sdk/shml/integrations/fiftyone.py` | 222 |
| `compute_similarity` | Function | `sdk/shml/integrations/fiftyone.py` | 261 |
| `compute_uniqueness` | Function | `sdk/shml/integrations/fiftyone.py` | 292 |
| `compute_hardness` | Function | `sdk/shml/integrations/fiftyone.py` | 356 |
| `compute_visualization` | Function | `sdk/shml/integrations/fiftyone.py` | 387 |
| `run_brain_computations` | Function | `ray_compute/jobs/inference/face_detection_benchmark.py` | 880 |
| `run_fiftyone_evaluation` | Function | `ray_compute/jobs/evaluation/fiftyone_eval_pipeline.py` | 5 |
| `evaluate_coding_model` | Function | `ray_compute/jobs/evaluation/eval_coding_model.py` | 5 |
| `analyze_failures_fiftyone` | Function | `libs/training/jobs/autoresearch_face.py` | 1358 |
| `load_or_create_dataset` | Function | `libs/evaluation/face/fiftyone_eval_pipeline.py` | 75 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Main → Save` | cross_community | 3 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Integrations | 23 calls |
| Libs | 8 calls |
| Inference | 2 calls |
| Unit | 1 calls |
| App | 1 calls |
| Benchmarking | 1 calls |
| Integration | 1 calls |

## How to Explore

1. `gitnexus_context({name: "save"})` — see callers and callees
2. `gitnexus_query({query: "face"})` — find related execution flows
3. Read key files listed above for implementation details
