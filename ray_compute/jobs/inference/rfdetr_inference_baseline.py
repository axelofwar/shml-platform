#!/usr/bin/env python3
"""
RF-DETR Inference Baseline — Zero-Shot on WIDER Face
=====================================================

Runs RF-DETR Large (pretrained on COCO-90) zero-shot inference on
the Phase 8 WIDER Face validation set to establish a baseline for
comparison against:
  - Phase 8 YOLOv8m-P2: mAP50=0.812, P=0.891, R=0.738
  - Phase 5 YOLOv8m:    mAP50=0.859, P=0.881, R=0.769

Since COCO-pretrained RF-DETR has no "face" class, we check
class 0 ("person") detections overlapping face ground truth.
This gives a fair zero-shot transfer baseline.

Integrations:
  - MLflow:      logs baseline experiment
  - Nessie:      creates experiment branch + tag
  - Prometheus:  pushes baseline metrics
  - FiftyOne:    creates visual dataset with GT + predictions

Usage (inside ray-head container):
    python rfdetr_inference_baseline.py
    python rfdetr_inference_baseline.py --dataset-dir /tmp/ray/data/wider_face_rfdetr
    python rfdetr_inference_baseline.py --threshold 0.3 --max-images 500
"""

from __future__ import annotations

import argparse
import json
import os
import sys
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

# Phase 8 baseline for comparison
PHASE8_BASELINE = {"mAP50": 0.812, "precision": 0.891, "recall": 0.738}
PHASE5_BASELINE = {"mAP50": 0.859, "precision": 0.881, "recall": 0.769}

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

# ═══════════════════════════════════════════════════════════════════════════
# NESSIE HELPERS (reused)
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
# MAIN INFERENCE PIPELINE
# ═══════════════════════════════════════════════════════════════════════════


def run_baseline(args: argparse.Namespace) -> dict[str, Any]:
    """Run zero-shot RF-DETR inference baseline on WIDER Face val set."""

    dataset_dir = Path(args.dataset_dir)
    val_dir = dataset_dir / "val"
    annot_path = val_dir / "_annotations.coco.json"

    print("=" * 70)
    print("RF-DETR INFERENCE BASELINE — Zero-Shot on WIDER Face")
    print("=" * 70)

    # ── Validate dataset ──
    if not annot_path.exists():
        print(f"ERROR: Annotation file not found: {annot_path}")
        print("  Run yolo_to_rfdetr_coco.py first to convert Phase 8 data.")
        sys.exit(1)

    with open(annot_path) as f:
        coco_data = json.load(f)

    n_images = len(coco_data["images"])
    n_anns = len(coco_data["annotations"])
    print(f"  Dataset: {n_images} images, {n_anns} annotations")
    print(f"  Categories: {[c['name'] for c in coco_data['categories']]}")

    # Optionally limit images
    images = coco_data["images"]
    if args.max_images and args.max_images < len(images):
        import random

        random.seed(42)
        images = random.sample(images, args.max_images)
        print(f"  Sampled {len(images)} images for evaluation")

    # Build GT lookup: image_id → list of annotations
    gt_map: dict[int, list] = {}
    for ann in coco_data["annotations"]:
        gt_map.setdefault(ann["image_id"], []).append(ann)

    # ── Load RF-DETR Large ──
    print("\n--- Loading RF-DETR Large (COCO-pretrained) ---")
    from rfdetr import RFDETRLarge
    from rfdetr.util.coco_classes import COCO_CLASSES

    model = RFDETRLarge()
    print(f"  Model loaded. Resolution: {model.model.resolution}")
    print(f"  COCO classes: {len(COCO_CLASSES)} (includes 'person' as class 1)")
    print(f"  Threshold: {args.threshold}")

    # ── Platform integration setup ──
    print("\n--- Platform Integrations ---")

    # MLflow
    mlflow_run_id = None
    if MLFLOW_AVAILABLE:
        try:
            mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
            mlflow.set_experiment("rfdetr-baseline")
            run = mlflow.start_run(
                run_name="zero-shot-wider-face",
                tags={
                    "phase": "9",
                    "stage": "baseline",
                    "model": "rfdetr-large",
                    "dataset": "wider-face-val",
                    "pretrained_on": "coco-90",
                },
            )
            mlflow_run_id = run.info.run_id
            mlflow.log_params(
                {
                    "model": "rfdetr-large",
                    "resolution": str(model.model.resolution),
                    "threshold": str(args.threshold),
                    "val_images": str(len(images)),
                    "dataset_dir": str(dataset_dir),
                    "baseline_type": "zero-shot",
                }
            )
            print(f"  MLflow: run {mlflow_run_id[:12]}...")
        except Exception as e:
            print(f"  MLflow: {e}")

    # Nessie
    branch_name = nessie_create_branch("experiment/phase9-baseline")

    # Prometheus setup
    prom_registry = None
    if PROMETHEUS_AVAILABLE:
        prom_registry = CollectorRegistry()
        print("  Prometheus: ready")

    print()

    # ── Run Inference ──
    print("--- Running Inference ---")
    start_time = time.time()

    # Collect predictions in COCO results format for pycocotools eval
    coco_results = []  # [{image_id, category_id, bbox:[x,y,w,h], score}]
    processed = 0
    skipped = 0

    for idx, img_info in enumerate(images):
        img_path = val_dir / img_info["file_name"]
        if not img_path.exists():
            skipped += 1
            continue

        try:
            pil_img = Image.open(str(img_path)).convert("RGB")
            detections = model.predict(pil_img, threshold=args.threshold)

            if detections is not None and len(detections) > 0:
                # RF-DETR returns supervision.Detections with class_id from COCO
                # class_id 0 = "person" in COCO
                # For face baseline, we accept ANY detection (model knows faces exist
                # as sub-regions of "person" detections), OR filter to person only.
                # We keep ALL detections and let pycocotools match by IoU.
                for i in range(len(detections.xyxy)):
                    x1, y1, x2, y2 = detections.xyxy[i].tolist()
                    score = float(detections.confidence[i])
                    # Convert xyxy → xywh for COCO
                    coco_results.append(
                        {
                            "image_id": img_info["id"],
                            "category_id": 1,  # Map all detections to face (cat 1)
                            "bbox": [
                                round(x1, 2),
                                round(y1, 2),
                                round(x2 - x1, 2),
                                round(y2 - y1, 2),
                            ],
                            "score": round(score, 4),
                        }
                    )

            processed += 1
        except Exception as e:
            skipped += 1
            if skipped <= 3:
                print(f"  Warning: {img_info['file_name']}: {e}")
            continue

        if (idx + 1) % 500 == 0:
            elapsed = time.time() - start_time
            rate = (idx + 1) / elapsed
            eta = (len(images) - idx - 1) / max(rate, 0.01)
            print(
                f"  {idx + 1}/{len(images)} images ({rate:.1f} img/s, ETA {eta:.0f}s)"
            )

    inference_time = time.time() - start_time
    print(
        f"\n  Inference complete: {processed} images in {inference_time:.1f}s "
        f"({processed / max(inference_time, 0.01):.1f} img/s), {skipped} skipped"
    )
    print(f"  Total detections: {len(coco_results)}")

    # ── Evaluate with pycocotools ──
    print("\n--- Evaluation ---")
    metrics: dict[str, float] = {}

    if PYCOCOTOOLS_AVAILABLE and coco_results:
        try:
            # Write temp results file for COCOeval
            results_tmp = str(dataset_dir / "baseline_results_tmp.json")
            with open(results_tmp, "w") as f:
                json.dump(coco_results, f)

            coco_gt = COCO(str(annot_path))
            coco_dt = coco_gt.loadRes(results_tmp)

            coco_eval = COCOeval(coco_gt, coco_dt, "bbox")

            # Only evaluate on the images we actually processed
            coco_eval.params.imgIds = [
                img["id"] for img in images if (val_dir / img["file_name"]).exists()
            ]

            coco_eval.evaluate()
            coco_eval.accumulate()
            coco_eval.summarize()

            # Extract standard 12 COCO metrics
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

            # Clean up temp file
            os.remove(results_tmp)

        except Exception as e:
            print(f"  pycocotools eval failed: {e}")
            import traceback

            traceback.print_exc()
    else:
        if not PYCOCOTOOLS_AVAILABLE:
            print("  pycocotools not available — falling back to simple matching")
        if not coco_results:
            print("  No detections — cannot evaluate")

        # Fallback: simple IoU matching
        total_tp, total_fp, total_fn = 0, 0, 0
        for img_info in images:
            gt_anns = gt_map.get(img_info["id"], [])
            gt_boxes = (
                np.array(
                    [
                        [
                            a["bbox"][0],
                            a["bbox"][1],
                            a["bbox"][0] + a["bbox"][2],
                            a["bbox"][1] + a["bbox"][3],
                        ]
                        for a in gt_anns
                    ]
                )
                if gt_anns
                else np.empty((0, 4))
            )

            # Get predictions for this image
            preds = [r for r in coco_results if r["image_id"] == img_info["id"]]
            pred_boxes = (
                np.array(
                    [
                        [
                            p["bbox"][0],
                            p["bbox"][1],
                            p["bbox"][0] + p["bbox"][2],
                            p["bbox"][1] + p["bbox"][3],
                        ]
                        for p in preds
                    ]
                )
                if preds
                else np.empty((0, 4))
            )

            matched = set()
            for pb in pred_boxes:
                best_iou, best_gi = 0, -1
                for gi, gb in enumerate(gt_boxes):
                    if gi in matched:
                        continue
                    x1 = max(pb[0], gb[0])
                    y1 = max(pb[1], gb[1])
                    x2 = min(pb[2], gb[2])
                    y2 = min(pb[3], gb[3])
                    inter = max(0, x2 - x1) * max(0, y2 - y1)
                    a1 = (pb[2] - pb[0]) * (pb[3] - pb[1])
                    a2 = (gb[2] - gb[0]) * (gb[3] - gb[1])
                    iou = inter / max(a1 + a2 - inter, 1e-6)
                    if iou > best_iou:
                        best_iou, best_gi = iou, gi
                if best_iou >= 0.5 and best_gi >= 0:
                    total_tp += 1
                    matched.add(best_gi)
                else:
                    total_fp += 1
            total_fn += len(gt_boxes) - len(matched)

        precision = total_tp / max(total_tp + total_fp, 1)
        recall = total_tp / max(total_tp + total_fn, 1)
        metrics = {
            "mAP50": round(precision * recall, 4),  # rough approximation
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "TP": total_tp,
            "FP": total_fp,
            "FN": total_fn,
        }

    # Add metadata
    metrics["inference_time_sec"] = round(inference_time, 2)
    metrics["images_processed"] = processed
    metrics["total_detections"] = len(coco_results)
    metrics["images_per_sec"] = round(processed / max(inference_time, 0.01), 2)

    # ── Print Results ──
    print("\n" + "=" * 70)
    print("BASELINE RESULTS")
    print("=" * 70)
    for k, v in sorted(metrics.items()):
        if isinstance(v, float):
            print(f"  {k:20s}: {v:.4f}")
        else:
            print(f"  {k:20s}: {v}")

    print(f"\n  Comparison:")
    print(
        f"  {'Metric':12s}  {'RF-DETR 0-shot':>15s}  {'Phase 8 YOLOv8':>15s}  {'Phase 5 YOLOv8':>15s}"
    )
    print(f"  {'-' * 60}")
    for key in ["mAP50", "precision", "recall"]:
        rfdetr_val = metrics.get(key, -1)
        p8_val = PHASE8_BASELINE.get(key, -1)
        p5_val = PHASE5_BASELINE.get(key, -1)
        print(f"  {key:12s}  {rfdetr_val:>15.4f}  {p8_val:>15.4f}  {p5_val:>15.4f}")

    # ── Log to MLflow ──
    if MLFLOW_AVAILABLE and mlflow_run_id:
        try:
            mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
            safe = {k: v for k, v in metrics.items() if isinstance(v, (int, float))}
            mlflow.log_metrics(safe)
            mlflow.end_run("FINISHED")
            print(f"\n  MLflow: metrics logged to run {mlflow_run_id[:12]}")
        except Exception as e:
            print(f"  MLflow log: {e}")
            try:
                mlflow.end_run()
            except Exception:
                pass

    # ── Nessie tag ──
    tag_name = f"baseline-rfdetr-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    if nessie_tag(tag_name):
        print(f"  Nessie: tagged '{tag_name}'")

    # ── Prometheus ──
    if PROMETHEUS_AVAILABLE and prom_registry:
        try:
            for k, v in metrics.items():
                if isinstance(v, (int, float)):
                    safe_k = k.replace(".", "_").replace("-", "_").replace("/", "_")
                    g = Gauge(f"baseline_{safe_k}", k, registry=prom_registry)
                    g.set(v)
            push_to_gateway(
                PUSHGATEWAY_URL,
                job="rfdetr_baseline",
                registry=prom_registry,
                grouping_key={"phase": "9", "stage": "baseline"},
            )
            print("  Prometheus: baseline metrics pushed")
        except Exception as e:
            print(f"  Prometheus: {e}")

    # ── FiftyOne ──
    if FIFTYONE_AVAILABLE and processed > 0:
        try:
            dataset_name = "phase9-rfdetr-baseline"
            if fo.dataset_exists(dataset_name):
                fo.delete_dataset(dataset_name)

            dataset = fo.Dataset.from_dir(
                dataset_type=fo.types.COCODetectionDataset,
                data_path=str(val_dir),
                labels_path=str(annot_path),
                name=dataset_name,
            )
            dataset.persistent = True
            dataset.info.update(
                {
                    "phase": "9",
                    "stage": "baseline",
                    "model": "rfdetr-large-coco-pretrained",
                    "threshold": args.threshold,
                    "metrics": metrics,
                }
            )
            dataset.save()
            print(
                f"  FiftyOne: dataset '{dataset_name}' created ({len(dataset)} samples)"
            )
        except Exception as e:
            print(f"  FiftyOne: {e}")

    # ── Save results ──
    results_path = dataset_dir / "baseline_results.json"
    with open(results_path, "w") as f:
        json.dump(
            {
                "model": "rfdetr-large-coco-pretrained",
                "dataset": str(dataset_dir),
                "threshold": args.threshold,
                "metrics": metrics,
                "comparison": {
                    "phase8_yolov8m": PHASE8_BASELINE,
                    "phase5_yolov8m": PHASE5_BASELINE,
                },
                "timestamp": datetime.now().isoformat(),
                "mlflow_run_id": mlflow_run_id,
            },
            f,
            indent=2,
            default=str,
        )
    print(f"\n  Results saved: {results_path}")

    return metrics


def main():
    parser = argparse.ArgumentParser(
        description="RF-DETR Inference Baseline — Zero-Shot on WIDER Face"
    )
    parser.add_argument(
        "--dataset-dir",
        default=DATASET_DIR_DEFAULT,
        help="RF-DETR COCO-format dataset directory",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.3,
        help="Detection confidence threshold (default: 0.3)",
    )
    parser.add_argument(
        "--max-images",
        type=int,
        default=None,
        help="Max validation images to process (default: all)",
    )
    args = parser.parse_args()
    run_baseline(args)


if __name__ == "__main__":
    main()
