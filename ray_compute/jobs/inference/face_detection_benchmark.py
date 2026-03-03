#!/usr/bin/env python3
"""
Face Detection Model Comparison Benchmark
==========================================

Runs YOLOv11m-face AND RF-DETR Large on the same WIDER Face validation set,
stores both sets of predictions as separate toggleable fields in a single
FiftyOne dataset, then runs Brain computations (CLIP embeddings, similarity,
uniqueness, per-model hardness, UMAP) for hard-sample mining.

Ground truth comes exclusively from WIDER Face human annotations (no model
involvement): wider_face_val_bbx_gt.txt → YOLO .txt → COCO _annotations.coco.json

Integrations:
  - FiftyOne:    shared dataset with toggleable per-model predictions
  - MLflow:      per-model runs under shared experiment
  - Nessie:      experiment branch + tags
  - Prometheus:  pushes per-model metrics
  - Feature Store: exports hard examples with CLIP embeddings (pgvector)

Usage (inside ray-head container):
    python face_detection_benchmark.py
    python face_detection_benchmark.py --max-images 500
    python face_detection_benchmark.py --rfdetr-checkpoint /path/to/finetuned.pth
    python face_detection_benchmark.py --skip-brain   # skip Brain computations
    python face_detection_benchmark.py --skip-yolo    # RF-DETR only
    python face_detection_benchmark.py --skip-rfdetr  # YOLO only
"""

from __future__ import annotations

# ── GPU Yield (must be before torch) ──────────────────────────────────────
import os
import sys

_script_dir = os.path.dirname(os.path.abspath(__file__))
_utils_candidates = [
    os.path.join(_script_dir, "..", "utils"),
    os.path.join(_script_dir, "..", "..", "jobs", "utils"),
]
for p in _utils_candidates:
    p = os.path.abspath(p)
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

try:
    from gpu_yield import yield_gpu_for_training, reclaim_gpu_after_training

    yield_gpu_for_training(purpose="face-detection-benchmark")
except Exception:
    pass

# SDK / libs path setup
_sdk_candidates = [
    os.path.join(_script_dir, "..", "..", "sdk"),
    os.path.join(_script_dir, "..", "..", "..", "sdk"),
]
_libs_candidates = [
    os.path.join(_script_dir, "..", "libs"),
    os.path.join(_script_dir, "..", "..", "..", "libs"),
    os.path.join(_script_dir, "..", "..", "libs"),
]
for p in _sdk_candidates + _libs_candidates:
    p = os.path.abspath(p)
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

# ── Standard imports ──────────────────────────────────────────────────────
import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

NESSIE_URI = os.environ.get("NESSIE_URI", "http://shml-nessie:19120")
MLFLOW_TRACKING_URI = os.environ.get(
    "MLFLOW_TRACKING_URI_INTERNAL", "http://mlflow-nginx:80"
)
PUSHGATEWAY_URL = os.environ.get("PUSHGATEWAY_URL", "shml-pushgateway:9091")
DATASET_DIR_DEFAULT = "/tmp/ray/data/wider_face_rfdetr"
YOLO_DATA_DIR_DEFAULT = "/tmp/ray/data/wider_face_yolo"

DATASET_NAME = "face-detection-model-comparison"
EXPERIMENT_NAME = "face-detection-benchmark"

# PII KPI targets
KPI_TARGETS = {
    "mAP50": 0.94,
    "recall": 0.95,
    "precision": 0.90,
    "hard_mAP50": 0.85,
    "tiny_recall": 0.85,
}

# Previous baselines for comparison
PREV_BASELINES = {
    "Phase 8 YOLOv8m-P2": {"mAP50": 0.812, "precision": 0.891, "recall": 0.738},
    "Phase 5 YOLOv8m": {"mAP50": 0.859, "precision": 0.881, "recall": 0.769},
    "RF-DETR 0-shot": {"mAP50": 0.0014, "precision": 0.0, "recall": 0.0},
}

# ═══════════════════════════════════════════════════════════════════════════
# OPTIONAL IMPORTS (graceful fallback)
# ═══════════════════════════════════════════════════════════════════════════

import requests

MLFLOW_AVAILABLE = False
try:
    import mlflow

    MLFLOW_AVAILABLE = True
except ImportError:
    pass

PROMETHEUS_AVAILABLE = False
try:
    from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

    PROMETHEUS_AVAILABLE = True
except ImportError:
    pass

FIFTYONE_AVAILABLE = False
try:
    if "FIFTYONE_DATABASE_URI" not in os.environ:
        os.environ["FIFTYONE_DATABASE_URI"] = "mongodb://fiftyone-mongodb:27017"
    import fiftyone as fo
    import fiftyone.brain as fob

    FIFTYONE_AVAILABLE = True
except ImportError:
    pass

PYCOCOTOOLS_AVAILABLE = False
try:
    from pycocotools.coco import COCO
    from pycocotools.cocoeval import COCOeval

    PYCOCOTOOLS_AVAILABLE = True
except ImportError:
    pass

FEATURE_CLIENT_AVAILABLE = False
try:
    from shml_features import FeatureClient

    FEATURE_CLIENT_AVAILABLE = True
except ImportError:
    pass


# ═══════════════════════════════════════════════════════════════════════════
# NESSIE HELPERS
# ═══════════════════════════════════════════════════════════════════════════


def nessie_create_branch(name: str) -> str | None:
    try:
        resp = requests.get(f"{NESSIE_URI}/api/v1/trees/tree/main", timeout=10)
        if resp.status_code != 200:
            return None
        main_hash = resp.json().get("hash", "")
        if not main_hash:
            return None
        resp = requests.post(
            f"{NESSIE_URI}/api/v1/trees/tree",
            json={"type": "BRANCH", "name": name, "hash": main_hash},
            timeout=10,
        )
        if resp.status_code in (200, 201, 409):
            print(f"  Nessie: branch '{name}' ready")
            return name
        return None
    except Exception as e:
        print(f"  Nessie branch: {e}")
        return None


def nessie_tag(name: str) -> bool:
    try:
        resp = requests.get(f"{NESSIE_URI}/api/v1/trees/tree/main", timeout=10)
        if resp.status_code != 200:
            return False
        main_hash = resp.json().get("hash", "")
        resp = requests.post(
            f"{NESSIE_URI}/api/v1/trees/tree",
            json={"type": "TAG", "name": name, "hash": main_hash},
            timeout=10,
        )
        return resp.status_code in (200, 201, 409)
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════
# DATA PREPARATION
# ═══════════════════════════════════════════════════════════════════════════


def ensure_coco_annotations(dataset_dir: Path) -> Path:
    """Ensure COCO annotation JSONs exist, regenerate if needed.

    The _annotations.coco.json files are ephemeral (generated into /tmp/)
    and may not persist across container restarts. The source of truth is
    the WIDER Face YOLO-format labels in wider_face_yolo/labels/val/*.txt,
    which are purely human-annotated (no model involvement).
    """
    val_dir = dataset_dir / "val"
    annot_path = val_dir / "_annotations.coco.json"

    if annot_path.exists():
        print(f"  ✓ COCO annotations found: {annot_path}")
        return annot_path

    print("  COCO annotations missing — regenerating from YOLO labels...")

    # Try importing the conversion script
    _data_candidates = [
        os.path.join(_script_dir, "..", "training", "data"),
        os.path.join(_script_dir, "..", "..", "jobs", "training", "data"),
    ]
    for p in _data_candidates:
        p = os.path.abspath(p)
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)

    try:
        from yolo_to_rfdetr_coco import convert_yolo_to_coco

        yolo_dir = Path(YOLO_DATA_DIR_DEFAULT)
        if not yolo_dir.exists():
            print(f"  ERROR: YOLO dataset not found at {yolo_dir}")
            sys.exit(1)

        convert_yolo_to_coco(str(yolo_dir), str(dataset_dir))
        if annot_path.exists():
            print(f"  ✓ Regenerated: {annot_path}")
            return annot_path
    except ImportError:
        pass

    # Fallback: manual inline conversion
    print("  Performing inline YOLO→COCO conversion...")
    yolo_dir = Path(YOLO_DATA_DIR_DEFAULT)
    yolo_labels_dir = yolo_dir / "labels" / "val"
    yolo_images_dir = yolo_dir / "images" / "val"

    if not yolo_labels_dir.exists():
        print(f"  ERROR: YOLO labels not found at {yolo_labels_dir}")
        sys.exit(1)

    coco_data = {
        "images": [],
        "annotations": [],
        "categories": [{"id": 1, "name": "face", "supercategory": "person"}],
    }
    ann_id = 1

    label_files = sorted(yolo_labels_dir.glob("*.txt"))
    for img_id, label_file in enumerate(label_files, start=1):
        img_name = label_file.stem + ".jpg"

        # Try to get image dimensions
        img_path_yolo = yolo_images_dir / img_name
        img_path_coco = val_dir / img_name
        img_path = img_path_coco if img_path_coco.exists() else img_path_yolo

        if not img_path.exists():
            continue

        try:
            with Image.open(img_path) as img:
                w_img, h_img = img.size
        except Exception:
            continue

        coco_data["images"].append(
            {"id": img_id, "file_name": img_name, "width": w_img, "height": h_img}
        )

        with open(label_file) as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) < 5:
                    continue
                # YOLO format: class_id cx cy w h (normalized)
                cx, cy, bw, bh = (
                    float(parts[1]),
                    float(parts[2]),
                    float(parts[3]),
                    float(parts[4]),
                )
                x = (cx - bw / 2) * w_img
                y = (cy - bh / 2) * h_img
                w = bw * w_img
                h = bh * h_img

                coco_data["annotations"].append(
                    {
                        "id": ann_id,
                        "image_id": img_id,
                        "category_id": 1,
                        "bbox": [round(x, 2), round(y, 2), round(w, 2), round(h, 2)],
                        "area": round(w * h, 2),
                        "iscrowd": 0,
                    }
                )
                ann_id += 1

    val_dir.mkdir(parents=True, exist_ok=True)
    with open(annot_path, "w") as f:
        json.dump(coco_data, f)

    print(
        f"  ✓ Created {annot_path}: "
        f"{len(coco_data['images'])} images, {len(coco_data['annotations'])} annotations"
    )
    return annot_path


def extract_scene_category(filename: str) -> str:
    """Extract WIDER Face scene category from filename.

    e.g. '2--Demonstration_2_Demonstration_...' → 'Demonstration'
    """
    parts = filename.split("--", 1)
    if len(parts) > 1:
        category = parts[1].split("_")[0]
        return category
    return "unknown"


# ═══════════════════════════════════════════════════════════════════════════
# FIFTYONE DATASET CREATION
# ═══════════════════════════════════════════════════════════════════════════


def create_shared_dataset(
    val_dir: Path,
    annot_path: Path,
    overwrite: bool = False,
) -> Any:
    """Create the shared FiftyOne dataset with GT only (no predictions).

    Ground truth comes from WIDER Face human annotations only —
    no model is involved in generating the ground_truth field.
    """
    if not FIFTYONE_AVAILABLE:
        print("  ⚠️  FiftyOne not available — dataset creation skipped")
        return None

    if fo.dataset_exists(DATASET_NAME):
        if overwrite:
            print(f"  Deleting existing dataset '{DATASET_NAME}'...")
            fo.delete_dataset(DATASET_NAME)
        else:
            print(f"  Loading existing dataset '{DATASET_NAME}'...")
            return fo.load_dataset(DATASET_NAME)

    print(f"  Creating shared dataset '{DATASET_NAME}'...")
    dataset = fo.Dataset.from_dir(
        dataset_type=fo.types.COCODetectionDataset,
        data_path=str(val_dir),
        labels_path=str(annot_path),
        name=DATASET_NAME,
    )
    dataset.persistent = True

    # Tag each sample with scene category
    print("  Adding scene category tags...")
    for sample in dataset.iter_samples(progress=True):
        fname = os.path.basename(sample.filepath)
        category = extract_scene_category(fname)
        sample.tags.append(category)

        # Count GT faces for filtering
        n_faces = 0
        if sample.ground_truth:
            n_faces = len(sample.ground_truth.detections)
        sample["num_gt_faces"] = n_faces
        sample.save()

    dataset.info.update(
        {
            "description": "WIDER Face model comparison benchmark",
            "gt_source": "WIDER Face human annotations (wider_face_val_bbx_gt.txt)",
            "gt_provenance": "WIDER Face → YOLO .txt → COCO _annotations.coco.json",
            "created": datetime.now().isoformat(),
        }
    )
    dataset.save()
    print(f"  ✓ Dataset created: {len(dataset)} samples")
    return dataset


# ═══════════════════════════════════════════════════════════════════════════
# MODEL INFERENCE
# ═══════════════════════════════════════════════════════════════════════════


def run_yolo_inference(
    dataset: Any,
    threshold: float = 0.25,
    field_name: str = "predictions_yolo11m_face",
) -> dict[str, Any]:
    """Run YOLOv11m-face inference and store predictions in FiftyOne dataset.

    Downloads from HuggingFace if not cached. Stores as a named field
    so it can be toggled independently from other model predictions.
    """
    print("\n" + "=" * 70)
    print("YOLOv11m-face INFERENCE")
    print("=" * 70)

    from ultralytics import YOLO

    # Load YOLOv11m-face from HuggingFace
    print("  Loading YOLOv11m-face...")
    try:
        from huggingface_hub import hf_hub_download

        model_path = hf_hub_download(
            repo_id="akanametov/yolov11m-face",
            filename="yolov11m-face.pt",
        )
        model = YOLO(model_path)
    except Exception as e:
        print(f"  HuggingFace download failed ({e}), trying local fallback...")
        # Try common local paths
        local_paths = [
            Path.home() / ".cache" / "huggingface" / "yolov11m-face.pt",
            Path("/tmp/models/yolov11m-face.pt"),
        ]
        model = None
        for lp in local_paths:
            if lp.exists():
                model = YOLO(str(lp))
                break
        if model is None:
            # Last resort: try loading by name (ultralytics may resolve it)
            model = YOLO("yolo11m.pt")  # fallback to base YOLO
            print("  ⚠️  Using base YOLO11m (not face-specialized)")

    print(f"  Threshold: {threshold}")

    start_time = time.time()
    processed = 0
    total_dets = 0

    for sample in dataset.iter_samples(progress=True):
        try:
            results = model.predict(
                sample.filepath,
                conf=threshold,
                verbose=False,
                device=0 if torch.cuda.is_available() else "cpu",
            )

            fo_dets = []
            if results and len(results) > 0:
                result = results[0]
                boxes = result.boxes
                if boxes is not None and len(boxes) > 0:
                    img_h, img_w = result.orig_shape
                    for i in range(len(boxes)):
                        x1, y1, x2, y2 = boxes.xyxy[i].cpu().tolist()
                        conf = float(boxes.conf[i].cpu())

                        # Normalize to [0,1] for FiftyOne
                        fo_dets.append(
                            fo.Detection(
                                label="face",
                                bounding_box=[
                                    x1 / img_w,
                                    y1 / img_h,
                                    (x2 - x1) / img_w,
                                    (y2 - y1) / img_h,
                                ],
                                confidence=conf,
                            )
                        )

            sample[field_name] = fo.Detections(detections=fo_dets)
            sample.save()
            processed += 1
            total_dets += len(fo_dets)

        except Exception as e:
            if processed < 3:
                print(f"  ⚠️  {os.path.basename(sample.filepath)}: {e}")
            continue

    inference_time = time.time() - start_time
    fps = processed / max(inference_time, 0.01)

    metrics = {
        "model": "yolov11m-face",
        "threshold": threshold,
        "images_processed": processed,
        "total_detections": total_dets,
        "inference_time_sec": round(inference_time, 2),
        "fps": round(fps, 2),
    }

    print(
        f"\n  ✓ YOLO inference: {processed} images, {total_dets} detections "
        f"in {inference_time:.1f}s ({fps:.1f} fps)"
    )
    return metrics


def run_rfdetr_inference(
    dataset: Any,
    threshold: float = 0.3,
    checkpoint: str | None = None,
    field_name: str = "predictions_rfdetr_large",
) -> dict[str, Any]:
    """Run RF-DETR Large inference and store predictions in FiftyOne dataset.

    Zero-shot: maps ALL detections to label 'face' (category_id 1 in COCO
    format). RF-DETR has no face class — this gives a fair zero-shot baseline.

    With checkpoint: loads fine-tuned weights that know 'face' as class 0.
    """
    print("\n" + "=" * 70)
    model_desc = (
        "RF-DETR Large (fine-tuned)" if checkpoint else "RF-DETR Large (zero-shot)"
    )
    print(f"{model_desc} INFERENCE")
    print("=" * 70)

    from rfdetr import RFDETRLarge

    model = RFDETRLarge()

    if checkpoint and Path(checkpoint).exists():
        print(f"  Loading fine-tuned weights: {checkpoint}")
        state_dict = torch.load(checkpoint, map_location="cpu")
        model.model.load_state_dict(state_dict, strict=False)

    model.model.eval()
    if torch.cuda.is_available():
        model.model.cuda()

    print(f"  Threshold: {threshold}")

    start_time = time.time()
    processed = 0
    total_dets = 0

    for sample in dataset.iter_samples(progress=True):
        try:
            pil_img = Image.open(sample.filepath).convert("RGB")
            w_img, h_img = pil_img.size

            detections = model.predict(pil_img, threshold=threshold)

            fo_dets = []
            if (
                detections is not None
                and hasattr(detections, "xyxy")
                and len(detections.xyxy) > 0
            ):
                for i in range(len(detections.xyxy)):
                    x1, y1, x2, y2 = detections.xyxy[i].tolist()
                    conf = (
                        float(detections.confidence[i])
                        if detections.confidence is not None
                        else 1.0
                    )

                    # Normalize to [0,1] for FiftyOne
                    fo_dets.append(
                        fo.Detection(
                            label="face",
                            bounding_box=[
                                x1 / w_img,
                                y1 / h_img,
                                (x2 - x1) / w_img,
                                (y2 - y1) / h_img,
                            ],
                            confidence=conf,
                        )
                    )

            sample[field_name] = fo.Detections(detections=fo_dets)
            sample.save()
            processed += 1
            total_dets += len(fo_dets)

        except Exception as e:
            if processed < 3:
                print(f"  ⚠️  {os.path.basename(sample.filepath)}: {e}")
            continue

    inference_time = time.time() - start_time
    fps = processed / max(inference_time, 0.01)

    model_name = "rfdetr-large-finetuned" if checkpoint else "rfdetr-large-zero-shot"
    metrics = {
        "model": model_name,
        "threshold": threshold,
        "checkpoint": checkpoint or "coco-pretrained",
        "images_processed": processed,
        "total_detections": total_dets,
        "inference_time_sec": round(inference_time, 2),
        "fps": round(fps, 2),
    }

    print(
        f"\n  ✓ RF-DETR inference: {processed} images, {total_dets} detections "
        f"in {inference_time:.1f}s ({fps:.1f} fps)"
    )
    return metrics


# ═══════════════════════════════════════════════════════════════════════════
# EVALUATION
# ═══════════════════════════════════════════════════════════════════════════


def evaluate_model_predictions(
    dataset: Any,
    pred_field: str,
    eval_key: str,
) -> dict[str, float]:
    """Run FiftyOne COCO-style evaluation for a single model's predictions."""
    print(f"\n━━━ Evaluating {pred_field} (eval_key={eval_key}) ━━━")

    if not dataset.has_sample_field(pred_field):
        print(f"  ⚠️  Field '{pred_field}' not found — skipping")
        return {}

    try:
        results = dataset.evaluate_detections(
            pred_field,
            gt_field="ground_truth",
            eval_key=eval_key,
            compute_mAP=True,
        )

        metrics = {}
        if hasattr(results, "mAP") and results.mAP is not None:
            metrics["mAP"] = round(results.mAP, 4)

        # Print report
        results.print_report()

        # Extract TP/FP/FN counts from eval fields
        tp_field = f"{eval_key}_tp"
        fp_field = f"{eval_key}_fp"
        fn_field = f"{eval_key}_fn"

        if dataset.has_sample_field(tp_field):
            tp_vals = dataset.values(tp_field)
            tp_total = sum(v for v in tp_vals if v is not None)
            fp_vals = dataset.values(fp_field)
            fp_total = sum(v for v in fp_vals if v is not None)
            fn_vals = dataset.values(fn_field)
            fn_total = sum(v for v in fn_vals if v is not None)

            precision = tp_total / max(tp_total + fp_total, 1)
            recall = tp_total / max(tp_total + fn_total, 1)
            f1 = 2 * precision * recall / max(precision + recall, 1e-6)

            metrics.update(
                {
                    "precision": round(precision, 4),
                    "recall": round(recall, 4),
                    "f1": round(f1, 4),
                    "TP": tp_total,
                    "FP": fp_total,
                    "FN": fn_total,
                }
            )

        print(f"  Results for {pred_field}:")
        for k, v in metrics.items():
            fmt = f"{v:.4f}" if isinstance(v, float) else str(v)
            print(f"    {k}: {fmt}")

        return metrics

    except Exception as e:
        print(f"  ⚠️  Evaluation failed: {e}")
        import traceback

        traceback.print_exc()
        return {}


def evaluate_by_face_size(
    dataset: Any,
    pred_field: str,
    eval_key_prefix: str,
) -> dict[str, dict]:
    """Evaluate predictions bucketed by ground truth face size.

    Size buckets (normalized bbox max dimension):
      tiny:   max_dim < 0.04  (~<32px in 800px image)
      small:  0.04 <= max_dim < 0.12  (~32-96px)
      medium: 0.12 <= max_dim < 0.32  (~96-256px)
      large:  max_dim >= 0.32  (~>256px)
    """
    print(f"\n━━━ Size-Bucketed Evaluation: {pred_field} ━━━")

    if not dataset.has_sample_field(pred_field):
        return {}

    buckets = {
        "tiny_lt32": {"max_dim_upper": 0.04, "samples": 0, "tp": 0, "fp": 0, "fn": 0},
        "small_32_96": {"max_dim_upper": 0.12, "samples": 0, "tp": 0, "fp": 0, "fn": 0},
        "medium_96_256": {
            "max_dim_upper": 0.32,
            "samples": 0,
            "tp": 0,
            "fp": 0,
            "fn": 0,
        },
        "large_gt256": {"max_dim_upper": 1.0, "samples": 0, "tp": 0, "fp": 0, "fn": 0},
    }

    for sample in dataset.iter_samples():
        if not sample.ground_truth:
            continue

        for gt_det in sample.ground_truth.detections:
            bw, bh = gt_det.bounding_box[2], gt_det.bounding_box[3]
            max_dim = max(bw, bh)

            if max_dim < 0.04:
                bucket = "tiny_lt32"
            elif max_dim < 0.12:
                bucket = "small_32_96"
            elif max_dim < 0.32:
                bucket = "medium_96_256"
            else:
                bucket = "large_gt256"

            buckets[bucket]["samples"] += 1

            # Check if this GT box was matched (has eval label)
            gt_eval = getattr(gt_det, eval_key_prefix, None)
            if gt_eval == "tp":
                buckets[bucket]["tp"] += 1
            else:
                buckets[bucket]["fn"] += 1

    results = {}
    print(f"  {'Bucket':<16} {'Count':>6} {'Recall':>8} {'FN':>6}")
    print(f"  {'-' * 40}")
    for name, data in buckets.items():
        total = data["tp"] + data["fn"]
        recall = data["tp"] / max(total, 1)
        results[name] = {"count": total, "recall": round(recall, 4), "fn": data["fn"]}
        print(f"  {name:<16} {total:>6} {recall:>8.4f} {data['fn']:>6}")

    return results


# ═══════════════════════════════════════════════════════════════════════════
# PYCOCOTOOLS EVALUATION (detailed mAP50/75/etc)
# ═══════════════════════════════════════════════════════════════════════════


def run_coco_eval(
    annot_path: Path,
    dataset: Any,
    pred_field: str,
    val_dir: Path,
) -> dict[str, float]:
    """Run pycocotools COCOeval for detailed metrics (mAP50, mAP75, per-size AR)."""
    if not PYCOCOTOOLS_AVAILABLE:
        print("  ⚠️  pycocotools not available — skipping detailed COCO eval")
        return {}

    if not dataset.has_sample_field(pred_field):
        return {}

    print(f"\n━━━ pycocotools COCO Eval: {pred_field} ━━━")

    # Build COCO-format predictions list
    # Need to map FiftyOne sample filepaths to COCO image IDs
    with open(annot_path) as f:
        coco_data = json.load(f)

    fname_to_id = {img["file_name"]: img["id"] for img in coco_data["images"]}
    fname_to_size = {
        img["file_name"]: (img["width"], img["height"]) for img in coco_data["images"]
    }

    coco_results = []
    for sample in dataset.iter_samples():
        fname = os.path.basename(sample.filepath)
        img_id = fname_to_id.get(fname)
        if img_id is None:
            continue

        preds = getattr(sample, pred_field, None)
        if preds is None:
            continue

        w_img, h_img = fname_to_size.get(fname, (1, 1))

        for det in preds.detections:
            # FiftyOne boxes are normalized [x, y, w, h]
            bx, by, bw, bh = det.bounding_box
            coco_results.append(
                {
                    "image_id": img_id,
                    "category_id": 1,
                    "bbox": [
                        round(bx * w_img, 2),
                        round(by * h_img, 2),
                        round(bw * w_img, 2),
                        round(bh * h_img, 2),
                    ],
                    "score": round(det.confidence, 4),
                }
            )

    if not coco_results:
        print("  No predictions to evaluate")
        return {}

    try:
        results_tmp = str(val_dir / f"_benchmark_{pred_field}_tmp.json")
        with open(results_tmp, "w") as f:
            json.dump(coco_results, f)

        coco_gt = COCO(str(annot_path))
        coco_dt = coco_gt.loadRes(results_tmp)

        coco_eval = COCOeval(coco_gt, coco_dt, "bbox")
        coco_eval.evaluate()
        coco_eval.accumulate()
        coco_eval.summarize()

        stats = coco_eval.stats
        metrics = {
            "mAP50_95": round(float(stats[0]), 4),
            "mAP50": round(float(stats[1]), 4),
            "mAP75": round(float(stats[2]), 4),
            "mAP_small": round(float(stats[3]), 4),
            "mAP_medium": round(float(stats[4]), 4),
            "mAP_large": round(float(stats[5]), 4),
            "AR_1": round(float(stats[6]), 4),
            "AR_10": round(float(stats[7]), 4),
            "AR_100": round(float(stats[8]), 4),
            "AR_small": round(float(stats[9]), 4),
            "AR_medium": round(float(stats[10]), 4),
            "AR_large": round(float(stats[11]), 4),
        }

        os.remove(results_tmp)
        return metrics

    except Exception as e:
        print(f"  pycocotools eval failed: {e}")
        import traceback

        traceback.print_exc()
        return {}


# ═══════════════════════════════════════════════════════════════════════════
# FIFTYONE BRAIN COMPUTATIONS
# ═══════════════════════════════════════════════════════════════════════════


def run_brain_computations(
    dataset: Any,
    pred_fields: list[str],
    embedding_model: str = "clip-vit-base32-torch",
    batch_size: int = 32,
) -> None:
    """Run FiftyOne Brain: CLIP embeddings, similarity, uniqueness,
    per-model hardness, UMAP visualization."""
    print("\n" + "=" * 70)
    print("FIFTYONE BRAIN COMPUTATIONS")
    print("=" * 70)

    total_steps = 4 + len(pred_fields)
    step = 0

    # 1. CLIP embeddings
    step += 1
    print(f"  [{step}/{total_steps}] Computing CLIP embeddings...")
    try:
        fob.compute_embeddings(
            dataset,
            model=embedding_model,
            embeddings_field="clip_embeddings",
            batch_size=batch_size,
        )
        dataset.save()
        print("  ✓ CLIP embeddings computed")
    except Exception as e:
        print(f"  ⚠️  Embeddings failed: {e}")
        return  # Can't continue without embeddings

    # 2. Similarity index
    step += 1
    print(f"  [{step}/{total_steps}] Building similarity index...")
    try:
        fob.compute_similarity(
            dataset,
            embeddings="clip_embeddings",
            brain_key="img_sim",
        )
        dataset.save()
        print("  ✓ Similarity index built")
    except Exception as e:
        print(f"  ⚠️  Similarity failed: {e}")

    # 3. Uniqueness
    step += 1
    print(f"  [{step}/{total_steps}] Computing uniqueness scores...")
    try:
        fob.compute_uniqueness(
            dataset,
            embeddings="clip_embeddings",
            uniqueness_field="uniqueness",
        )
        dataset.save()
        print("  ✓ Uniqueness scores computed")
    except Exception as e:
        print(f"  ⚠️  Uniqueness failed: {e}")

    # 4. Per-model hardness
    for pred_field in pred_fields:
        step += 1
        hardness_field = f"hardness_{pred_field.replace('predictions_', '')}"
        print(f"  [{step}/{total_steps}] Computing hardness: {pred_field}...")
        try:
            if dataset.has_sample_field(pred_field):
                fob.compute_hardness(
                    dataset,
                    pred_field,
                    hardness_field=hardness_field,
                )
                dataset.save()
                print(f"  ✓ Hardness ({pred_field}) → {hardness_field}")
            else:
                print(f"  ⚠️  {pred_field} not found — skipping")
        except Exception as e:
            print(f"  ⚠️  Hardness failed for {pred_field}: {e}")

    # 5. UMAP visualization
    step += 1
    print(f"  [{step}/{total_steps}] Computing UMAP visualization...")
    try:
        fob.compute_visualization(
            dataset,
            embeddings="clip_embeddings",
            brain_key="img_viz",
            method="umap",
            num_dims=2,
        )
        dataset.save()
        print("  ✓ UMAP visualization computed")
    except Exception as e:
        print(f"  ⚠️  UMAP failed: {e}")

    print("  ✓ Brain computations complete")


# ═══════════════════════════════════════════════════════════════════════════
# HARD SAMPLE ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════


def create_hard_sample_views(
    dataset: Any,
    pred_fields: list[str],
) -> None:
    """Create saved views for hard samples and model disagreements."""
    print("\n━━━ Hard Sample Analysis ━━━")

    # 1. Per-model hard samples (high hardness)
    for pred_field in pred_fields:
        hardness_field = f"hardness_{pred_field.replace('predictions_', '')}"
        if not dataset.has_sample_field(hardness_field):
            continue

        view_name = f"hard_{pred_field.replace('predictions_', '')}"
        try:
            hard_view = dataset.match(fo.ViewField(hardness_field) > 0.7).sort_by(
                hardness_field, reverse=True
            )

            dataset.save_view(view_name, hard_view, overwrite=True)
            print(f"  ✓ Saved view '{view_name}': {len(hard_view)} samples")
        except Exception as e:
            print(f"  ⚠️  View '{view_name}' failed: {e}")

    # 2. Model disagreement view (YOLO detects, RF-DETR misses, or vice versa)
    if len(pred_fields) >= 2:
        try:
            f1, f2 = pred_fields[0], pred_fields[1]
            # Samples where one model has detections and the other doesn't
            disagreement_view = dataset.match(
                (fo.ViewField(f"{f1}.detections").length() > 0)
                != (fo.ViewField(f"{f2}.detections").length() > 0)
            )
            dataset.save_view("model_disagreement", disagreement_view, overwrite=True)
            print(
                f"  ✓ Saved view 'model_disagreement': {len(disagreement_view)} samples"
            )
        except Exception as e:
            print(f"  ⚠️  Disagreement view failed: {e}")

    # 3. Combined hard samples view
    hardness_fields = [
        f"hardness_{pf.replace('predictions_', '')}"
        for pf in pred_fields
        if dataset.has_sample_field(f"hardness_{pf.replace('predictions_', '')}")
    ]
    if hardness_fields:
        try:
            # Samples hard for ANY model
            conditions = [fo.ViewField(hf) > 0.7 for hf in hardness_fields]
            combined = conditions[0]
            for c in conditions[1:]:
                combined = combined | c
            hard_any = dataset.match(combined).sort_by(hardness_fields[0], reverse=True)
            dataset.save_view("hard_samples", hard_any, overwrite=True)
            print(f"  ✓ Saved view 'hard_samples': {len(hard_any)} samples")
        except Exception as e:
            print(f"  ⚠️  Combined hard view failed: {e}")


def export_hard_examples(
    dataset: Any,
    pred_fields: list[str],
    max_examples: int = 500,
    run_id: str = "",
) -> int:
    """Export hard examples with CLIP embeddings to Feature Store (pgvector)."""
    if not FEATURE_CLIENT_AVAILABLE:
        print("  ⚠️  FeatureClient not available — skipping export")
        return 0

    print("\n━━━ Exporting Hard Examples to Feature Store ━━━")

    password = os.environ.get("POSTGRES_PASSWORD", "")
    if not password:
        for sp in [
            "/run/secrets/shared_db_password",
            os.path.join(
                _script_dir, "..", "..", "..", "secrets", "shared_db_password.txt"
            ),
        ]:
            try:
                with open(sp) as f:
                    password = f.read().strip()
                    break
            except FileNotFoundError:
                continue

    if not password:
        print("  ⚠️  DB password not available")
        return 0

    try:
        client = FeatureClient(
            postgres_host=os.environ.get("POSTGRES_HOST", "postgres"),
            postgres_port=int(os.environ.get("POSTGRES_PORT", "5432")),
            postgres_db=os.environ.get("POSTGRES_DB", "inference"),
            postgres_user=os.environ.get("POSTGRES_USER", "inference"),
            postgres_password=password,
        )
        client.init_schema()

        # Use first available hardness field
        hardness_field = None
        for pf in pred_fields:
            hf = f"hardness_{pf.replace('predictions_', '')}"
            if dataset.has_sample_field(hf):
                hardness_field = hf
                break

        if not hardness_field:
            print("  ⚠️  No hardness field available — skipping")
            return 0

        hard_view = dataset.sort_by(hardness_field, reverse=True).limit(max_examples)

        conn = client._get_conn()
        exported = 0
        with conn.cursor() as cur:
            for sample in hard_view:
                embedding = None
                if (
                    hasattr(sample, "clip_embeddings")
                    and sample.clip_embeddings is not None
                ):
                    embedding = list(sample.clip_embeddings)

                hardness = getattr(sample, hardness_field, None)
                uniqueness = getattr(sample, "uniqueness", None)

                # Determine face size bucket from GT
                face_size_bucket = "unknown"
                if sample.ground_truth:
                    max_dim = 0
                    for det in sample.ground_truth.detections:
                        w, h = det.bounding_box[2], det.bounding_box[3]
                        max_dim = max(max_dim, max(w, h))
                    if max_dim < 0.04:
                        face_size_bucket = "tiny_lt32"
                    elif max_dim < 0.12:
                        face_size_bucket = "small_32_96"
                    elif max_dim < 0.32:
                        face_size_bucket = "medium_96_256"
                    else:
                        face_size_bucket = "large_gt256"

                try:
                    cur.execute(
                        """
                        INSERT INTO feature_hard_examples
                            (image_id, run_id, embedding, face_size_bucket,
                             false_negative_count, extra)
                        VALUES (%s, %s, %s::vector, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (
                            os.path.basename(sample.filepath),
                            run_id,
                            str(embedding) if embedding else None,
                            face_size_bucket,
                            0,
                            json.dumps(
                                {
                                    "hardness": hardness,
                                    "uniqueness": uniqueness,
                                    "source": "benchmark_brain",
                                    "benchmark": DATASET_NAME,
                                }
                            ),
                        ),
                    )
                    exported += 1
                except Exception:
                    continue

            conn.commit()
        client.close()
        print(f"  ✓ Exported {exported} hard examples to feature_hard_examples")
        return exported

    except Exception as e:
        print(f"  ⚠️  Export failed: {e}")
        return 0


def export_hard_samples_json(
    dataset: Any,
    pred_fields: list[str],
    output_path: str = "/tmp/ray/data/hard_samples_benchmark.json",
) -> None:
    """Export hard sample paths + metadata to JSON for active learning."""
    if not dataset.has_sample_field("hard_samples"):
        # Fall back to any hardness field
        hardness_field = None
        for pf in pred_fields:
            hf = f"hardness_{pf.replace('predictions_', '')}"
            if dataset.has_sample_field(hf):
                hardness_field = hf
                break

        if not hardness_field:
            return

        view = dataset.sort_by(hardness_field, reverse=True).limit(500)
    else:
        view = dataset.load_saved_view("hard_samples")

    records = []
    for sample in view:
        record = {
            "filepath": sample.filepath,
            "filename": os.path.basename(sample.filepath),
            "tags": list(sample.tags),
        }
        for pf in pred_fields:
            hf = f"hardness_{pf.replace('predictions_', '')}"
            record[hf] = getattr(sample, hf, None)

        record["uniqueness"] = getattr(sample, "uniqueness", None)
        record["num_gt_faces"] = getattr(sample, "num_gt_faces", 0)
        records.append(record)

    with open(output_path, "w") as f:
        json.dump(records, f, indent=2, default=str)

    print(f"  ✓ Exported {len(records)} hard samples to {output_path}")


# ═══════════════════════════════════════════════════════════════════════════
# PLATFORM INTEGRATION (MLflow, Nessie, Prometheus)
# ═══════════════════════════════════════════════════════════════════════════


def log_to_mlflow(
    model_name: str,
    inference_metrics: dict,
    eval_metrics: dict,
    coco_metrics: dict,
    size_metrics: dict,
    threshold: float,
    dataset_size: int,
) -> str | None:
    """Log a single model's results to MLflow."""
    if not MLFLOW_AVAILABLE:
        return None

    try:
        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
        mlflow.set_experiment(EXPERIMENT_NAME)

        with mlflow.start_run(
            run_name=f"benchmark-{model_name}",
            tags={
                "benchmark": DATASET_NAME,
                "model": model_name,
                "stage": "benchmark",
                "dataset": "wider-face-val",
                "gt_source": "wider_face_human_annotations",
            },
        ) as run:
            # Log params
            mlflow.log_params(
                {
                    "model": model_name,
                    "threshold": str(threshold),
                    "dataset_size": str(dataset_size),
                    "gt_source": "WIDER Face human annotations",
                }
            )

            # Log all numeric metrics
            all_metrics = {}
            for d in [inference_metrics, eval_metrics, coco_metrics]:
                for k, v in d.items():
                    if isinstance(v, (int, float)):
                        safe_k = k.replace(".", "_").replace("-", "_").replace("/", "_")
                        all_metrics[safe_k] = v

            # Add size-bucketed metrics
            for bucket, data in size_metrics.items():
                all_metrics[f"recall_{bucket}"] = data.get("recall", 0)
                all_metrics[f"count_{bucket}"] = data.get("count", 0)

            mlflow.log_metrics(all_metrics)

            run_id = run.info.run_id
            print(f"  MLflow: {model_name} → run {run_id[:12]}...")
            return run_id

    except Exception as e:
        print(f"  MLflow ({model_name}): {e}")
        return None


def push_to_prometheus(
    model_name: str,
    metrics: dict[str, Any],
) -> None:
    """Push per-model metrics to Prometheus Pushgateway."""
    if not PROMETHEUS_AVAILABLE:
        return

    try:
        registry = CollectorRegistry()
        for k, v in metrics.items():
            if isinstance(v, (int, float)):
                safe_k = (
                    f"benchmark_{k}".replace(".", "_")
                    .replace("-", "_")
                    .replace("/", "_")
                )
                g = Gauge(safe_k, k, registry=registry)
                g.set(v)

        push_to_gateway(
            PUSHGATEWAY_URL,
            job="face_detection_benchmark",
            registry=registry,
            grouping_key={"model": model_name},
        )
        print(f"  Prometheus: {model_name} metrics pushed")
    except Exception as e:
        print(f"  Prometheus ({model_name}): {e}")


# ═══════════════════════════════════════════════════════════════════════════
# COMPARISON REPORT
# ═══════════════════════════════════════════════════════════════════════════


def print_comparison_report(
    all_results: dict[str, dict],
    size_results: dict[str, dict],
) -> str:
    """Print and return a comparison table across all models."""
    print("\n" + "=" * 90)
    print("FACE DETECTION BENCHMARK — MODEL COMPARISON")
    print("=" * 90)

    models = list(all_results.keys())
    header_metrics = ["mAP50", "mAP50_95", "precision", "recall", "f1", "fps"]

    # Header
    col_w = 18
    print(f"\n  {'Metric':<16}", end="")
    print(f"  {'KPI Target':>{col_w}}", end="")
    for m in models:
        print(f"  {m:>{col_w}}", end="")
    print()
    print(f"  {'-' * (16 + (col_w + 2) * (len(models) + 1))}")

    # Metric rows
    for metric in header_metrics:
        kpi = KPI_TARGETS.get(metric, "—")
        kpi_str = f"{kpi:.2%}" if isinstance(kpi, float) else str(kpi)
        print(f"  {metric:<16}  {kpi_str:>{col_w}}", end="")
        for m in models:
            val = all_results[m].get(metric, None)
            if val is not None:
                if metric == "fps":
                    print(f"  {val:>{col_w}.1f}", end="")
                else:
                    print(f"  {val:>{col_w}.4f}", end="")
            else:
                print(f"  {'—':>{col_w}}", end="")
        print()

    # Size-bucketed recall
    if size_results:
        print(f"\n  {'Size Bucket':<16}", end="")
        print(f"  {'KPI Target':>{col_w}}", end="")
        for m in models:
            print(f"  {m:>{col_w}}", end="")
        print()
        print(f"  {'-' * (16 + (col_w + 2) * (len(models) + 1))}")

        for bucket in ["tiny_lt32", "small_32_96", "medium_96_256", "large_gt256"]:
            kpi = KPI_TARGETS.get("tiny_recall", "—") if bucket == "tiny_lt32" else "—"
            kpi_str = f"{kpi:.2%}" if isinstance(kpi, float) else str(kpi)
            print(f"  {bucket:<16}  {kpi_str:>{col_w}}", end="")
            for m in models:
                model_sizes = size_results.get(m, {})
                val = model_sizes.get(bucket, {}).get("recall", None)
                if val is not None:
                    print(f"  {val:>{col_w}.4f}", end="")
                else:
                    print(f"  {'—':>{col_w}}", end="")
            print()

    # KPI gap analysis
    print(f"\n  KPI Gap Analysis:")
    for m in models:
        gaps = []
        for kpi_name, target in KPI_TARGETS.items():
            actual = all_results[m].get(
                kpi_name if kpi_name != "hard_mAP50" else "mAP50", None
            )
            if actual is not None and actual < target:
                gap = target - actual
                gaps.append(f"{kpi_name}: -{gap:.2%}")
        if gaps:
            print(f"    {m}: {', '.join(gaps)}")
        else:
            print(f"    {m}: ✓ All KPIs met")

    print("=" * 90)

    # Build report string for artifacts
    report_lines = []
    report_lines.append("# Face Detection Benchmark Report")
    report_lines.append(f"Generated: {datetime.now().isoformat()}")
    report_lines.append(f"Dataset: WIDER Face validation ({DATASET_NAME})")
    report_lines.append(f"GT Source: WIDER Face human annotations\n")
    for m in models:
        report_lines.append(f"## {m}")
        for k, v in sorted(all_results[m].items()):
            report_lines.append(f"  {k}: {v}")
        report_lines.append("")
    return "\n".join(report_lines)


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        description="Face Detection Model Comparison Benchmark"
    )
    parser.add_argument(
        "--dataset-dir",
        default=DATASET_DIR_DEFAULT,
        help="RF-DETR COCO-format dataset directory",
    )
    parser.add_argument(
        "--yolo-threshold",
        type=float,
        default=0.25,
        help="YOLO confidence threshold (default: 0.25)",
    )
    parser.add_argument(
        "--rfdetr-threshold",
        type=float,
        default=0.3,
        help="RF-DETR confidence threshold (default: 0.3)",
    )
    parser.add_argument(
        "--rfdetr-checkpoint",
        type=str,
        default=None,
        help="Path to fine-tuned RF-DETR weights (optional)",
    )
    parser.add_argument(
        "--max-images",
        type=int,
        default=None,
        help="Max validation images to process (default: all)",
    )
    parser.add_argument("--skip-yolo", action="store_true", help="Skip YOLO inference")
    parser.add_argument(
        "--skip-rfdetr", action="store_true", help="Skip RF-DETR inference"
    )
    parser.add_argument(
        "--skip-brain", action="store_true", help="Skip Brain computations"
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="Overwrite existing dataset"
    )
    parser.add_argument(
        "--embedding-model",
        default="clip-vit-base32-torch",
        help="Embedding model for Brain (default: clip-vit-base32-torch)",
    )
    args = parser.parse_args()

    print("=" * 90)
    print("FACE DETECTION BENCHMARK — Multi-Model Comparison")
    print(f"  GT source: WIDER Face human annotations (no model involvement)")
    print(f"  Dataset dir: {args.dataset_dir}")
    print("=" * 90)

    dataset_dir = Path(args.dataset_dir)
    val_dir = dataset_dir / "val"

    # ── Phase 1: Data Preparation ──
    print("\n━━━ Phase 1: Data Preparation ━━━")
    annot_path = ensure_coco_annotations(dataset_dir)

    # Verify annotation count
    with open(annot_path) as f:
        coco_data = json.load(f)
    n_images = len(coco_data["images"])
    n_anns = len(coco_data["annotations"])
    print(f"  Dataset: {n_images} images, {n_anns} GT annotations (human-labeled)")

    # ── Phase 2: FiftyOne Dataset ──
    print("\n━━━ Phase 2: FiftyOne Dataset ━━━")
    if not FIFTYONE_AVAILABLE:
        print("  ⚠️  FiftyOne not available — running in metrics-only mode")
        dataset = None
    else:
        dataset = create_shared_dataset(val_dir, annot_path, overwrite=args.overwrite)

        # Optionally limit samples
        if args.max_images and dataset and len(dataset) > args.max_images:
            print(f"  Limiting to {args.max_images} samples...")
            import random

            random.seed(42)
            all_ids = dataset.values("id")
            keep_ids = random.sample(all_ids, args.max_images)
            dataset = dataset.select(keep_ids)

    # ── Platform setup ──
    print("\n━━━ Platform Setup ━━━")
    nessie_create_branch("experiment/face-detection-benchmark")

    # ── Phase 3: Model Inference ──
    pred_fields = []
    inference_results = {}

    if not args.skip_yolo and dataset:
        yolo_metrics = run_yolo_inference(
            dataset,
            threshold=args.yolo_threshold,
            field_name="predictions_yolo11m_face",
        )
        pred_fields.append("predictions_yolo11m_face")
        inference_results["yolo11m_face"] = yolo_metrics

    if not args.skip_rfdetr and dataset:
        rfdetr_field = (
            "predictions_rfdetr_finetuned"
            if args.rfdetr_checkpoint
            else "predictions_rfdetr_large"
        )
        rfdetr_metrics = run_rfdetr_inference(
            dataset,
            threshold=args.rfdetr_threshold,
            checkpoint=args.rfdetr_checkpoint,
            field_name=rfdetr_field,
        )
        pred_fields.append(rfdetr_field)
        model_key = "rfdetr_finetuned" if args.rfdetr_checkpoint else "rfdetr_large"
        inference_results[model_key] = rfdetr_metrics

    if not pred_fields:
        print("\n  No models were run — exiting")
        return

    # ── Phase 4: Evaluation ──
    print("\n━━━ Phase 4: Evaluation ━━━")
    all_results = {}
    size_results = {}

    for pred_field in pred_fields:
        model_key = pred_field.replace("predictions_", "")
        eval_key = f"eval_{model_key}"

        # FiftyOne evaluation
        eval_metrics = evaluate_model_predictions(dataset, pred_field, eval_key)

        # pycocotools evaluation (detailed mAP50/75/per-size)
        coco_metrics = run_coco_eval(annot_path, dataset, pred_field, val_dir)

        # Size-bucketed evaluation
        size_metrics = evaluate_by_face_size(dataset, pred_field, eval_key)

        # Merge all metrics
        merged = {}
        merged.update(inference_results.get(model_key, {}))
        merged.update(eval_metrics)
        merged.update(coco_metrics)
        all_results[model_key] = merged
        size_results[model_key] = size_metrics

    # ── Phase 5: Brain Computations ──
    if not args.skip_brain and dataset:
        run_brain_computations(
            dataset,
            pred_fields=pred_fields,
            embedding_model=args.embedding_model,
        )

        # ── Phase 6: Hard Sample Analysis ─
        create_hard_sample_views(dataset, pred_fields)

    # ── Phase 7: Platform Integration ──
    print("\n━━━ Phase 7: Platform Integration ━━━")

    mlflow_run_ids = {}
    for model_key, merged_metrics in all_results.items():
        pred_field = f"predictions_{model_key}"
        threshold = (
            args.yolo_threshold if "yolo" in model_key else args.rfdetr_threshold
        )

        run_id = log_to_mlflow(
            model_key,
            inference_results.get(model_key, {}),
            {
                k: v
                for k, v in merged_metrics.items()
                if k in ("precision", "recall", "f1", "mAP", "TP", "FP", "FN")
            },
            {
                k: v
                for k, v in merged_metrics.items()
                if k.startswith("mAP") or k.startswith("AR")
            },
            size_results.get(model_key, {}),
            threshold,
            len(dataset) if dataset else 0,
        )
        if run_id:
            mlflow_run_ids[model_key] = run_id

        push_to_prometheus(model_key, merged_metrics)

    # Nessie tag
    tag = f"benchmark-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    if nessie_tag(tag):
        print(f"  Nessie: tagged '{tag}'")

    # Feature Store export
    if not args.skip_brain and dataset:
        first_run_id = next(iter(mlflow_run_ids.values()), "")
        export_hard_examples(dataset, pred_fields, run_id=first_run_id)
        export_hard_samples_json(dataset, pred_fields)

    # ── Phase 8: Comparison Report ──
    report = print_comparison_report(all_results, size_results)

    # Save report
    report_path = dataset_dir / "benchmark_comparison.json"
    with open(report_path, "w") as f:
        json.dump(
            {
                "timestamp": datetime.now().isoformat(),
                "dataset": DATASET_NAME,
                "gt_source": "WIDER Face human annotations (no model involvement)",
                "models": all_results,
                "size_analysis": size_results,
                "kpi_targets": KPI_TARGETS,
                "previous_baselines": PREV_BASELINES,
                "mlflow_run_ids": mlflow_run_ids,
            },
            f,
            indent=2,
            default=str,
        )
    print(f"\n  Results saved: {report_path}")

    if dataset:
        print(
            f"\n  View in FiftyOne: navigate to /fiftyone/ → dataset '{DATASET_NAME}'"
        )
        print(f"  Toggle prediction fields: {', '.join(pred_fields)}")

    # ── GPU Reclaim ──
    try:
        reclaim_gpu_after_training()
    except Exception:
        pass

    print("\n✅ Benchmark complete")


if __name__ == "__main__":
    main()
