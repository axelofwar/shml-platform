#!/usr/bin/env python3
"""
RF-DETR Face Fine-Tuning — WIDER Face with Full Platform Integration
======================================================================

Fine-tunes RF-DETR Large (DINOv2 backbone, 128M params) on WIDER Face
for the PII face-detection use case. Uses RF-DETR's native training API
with callbacks for real-time platform integration.

**Pipeline Position:**
  1. face_detection_benchmark.py  → zero-shot baselines (YOLO + RF-DETR)
  2. ➜  train_rfdetr_face.py      → fine-tune RF-DETR on WIDER Face (THIS)
  3. face_detection_benchmark.py  → re-benchmark with --rfdetr-checkpoint

**Why RF-DETR?**
  Zero-shot RF-DETR achieves mAP50≈0.001 on faces (COCO classes only).
  After fine-tuning on WIDER Face (12,876 train + 3,222 val images),
  we expect ≥85% mAP50 — competitive with YOLOv11m-face baseline.

**Integrations:**
┌─────────────┬──────────────────────────────────────────────────────────┐
│ Service     │ How                                                      │
├─────────────┼──────────────────────────────────────────────────────────┤
│ MLflow      │ Built-in (mlflow=True) + manual artifacts at end         │
│ Nessie      │ Branch per experiment, tag on completion                 │
│ Prometheus  │ Per-epoch gauges via Pushgateway + GPU stats             │
│ Grafana     │ Passive: reads ml-training-live dashboard                │
│ FiftyOne    │ Post-training eval: predictions, Brain, hard samples     │
│ FeatureStore│ Eval metrics + training lineage materialization          │
└─────────────┴──────────────────────────────────────────────────────────┘

**PII KPI Targets:**
   mAP50 ≥ 94%  |  Recall ≥ 95%  |  Precision ≥ 90%
   Hard mAP50 ≥ 85%  |  Tiny(<32px) Recall ≥ 85%

Usage:
    python train_rfdetr_face.py                                # defaults
    python train_rfdetr_face.py --epochs 30 --batch-size 4     # custom
    python train_rfdetr_face.py --dry-run                      # config check
    python train_rfdetr_face.py --resume /path/to/ckpt.pth     # resume

Author: SHML Platform
Date: February 2026
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# ═══════════════════════════════════════════════════════════════════════════
# GPU YIELD (before torch import)
# ═══════════════════════════════════════════════════════════════════════════
_utils_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _utils_path not in sys.path:
    sys.path.insert(0, _utils_path)

_job_id = os.environ.get("RAY_JOB_ID", f"rfdetr-face-{os.getpid()}")

try:
    from utils.gpu_yield import yield_gpu_for_training, reclaim_gpu_after_training

    yield_gpu_for_training(gpu_id=0, job_id=_job_id, timeout=30)
except ImportError:
    print("[gpu] yield not available, continuing")

import torch

# ═══════════════════════════════════════════════════════════════════════════
# CUDA OPTIMIZATIONS
# ═══════════════════════════════════════════════════════════════════════════
os.environ.setdefault(
    "PYTORCH_CUDA_ALLOC_CONF",
    "expandable_segments:True,garbage_collection_threshold:0.8,max_split_size_mb:512",
)

if torch.cuda.is_available():
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    torch.backends.cudnn.benchmark = True
    torch.backends.cudnn.deterministic = False
    gpu_name = torch.cuda.get_device_name(0)
    vram_gb = torch.cuda.get_device_properties(0).total_mem / 1e9
    print(f"[cuda] {gpu_name} — {vram_gb:.1f} GB VRAM")
else:
    print("[cuda] NOT available — training will be extremely slow")

# ═══════════════════════════════════════════════════════════════════════════
# PLATFORM IMPORTS (graceful fallback)
# ═══════════════════════════════════════════════════════════════════════════

_script_dir = os.path.dirname(os.path.abspath(__file__))
for _p in [
    os.path.join(_script_dir, "..", "..", "..", "sdk"),
    os.path.join(_script_dir, "..", "..", "sdk"),
    os.path.join(_script_dir, "..", "sdk"),
    os.path.join(_script_dir, "..", "libs"),
    os.path.join(_script_dir, "..", "..", "..", "libs"),
    os.path.join(_script_dir, "..", "..", "libs"),
]:
    _p = os.path.abspath(_p)
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import requests

# ── MLflow ──
MLFLOW_AVAILABLE = False
try:
    import mlflow

    MLFLOW_AVAILABLE = True
    print("[mlflow] available")
except ImportError:
    print("[mlflow] not available")

# ── FiftyOne ──
FIFTYONE_AVAILABLE = False
try:
    if "FIFTYONE_DATABASE_URI" not in os.environ:
        os.environ["FIFTYONE_DATABASE_URI"] = "mongodb://fiftyone-mongodb:27017"
    import fiftyone as fo

    FIFTYONE_AVAILABLE = True
    print(f"[fiftyone] v{fo.__version__}")
except ImportError:
    print("[fiftyone] not available")

# ── Feature Store ──
FEATURE_CLIENT_AVAILABLE = False
try:
    from shml_features import FeatureClient

    FEATURE_CLIENT_AVAILABLE = True
    print("[features] FeatureClient available")
except ImportError:
    print("[features] FeatureClient not available")

# ── Prometheus ──
PROMETHEUS_AVAILABLE = False
try:
    from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

    PROMETHEUS_AVAILABLE = True
    print("[prometheus] available")
except ImportError:
    print("[prometheus] not available")

# ── RF-DETR ──
RFDETR_AVAILABLE = False
try:
    from rfdetr import RFDETRLarge

    RFDETR_AVAILABLE = True
    print("[rfdetr] available")
except ImportError:
    print("[rfdetr] NOT installed — pip install rfdetr>=1.5.0")

# ── pycocotools ──
PYCOCOTOOLS_AVAILABLE = False
try:
    from pycocotools.coco import COCO
    from pycocotools.cocoeval import COCOeval

    PYCOCOTOOLS_AVAILABLE = True
except ImportError:
    pass


# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

NESSIE_URI = os.environ.get("NESSIE_URI", "http://shml-nessie:19120")
MLFLOW_TRACKING_URI = os.environ.get(
    "MLFLOW_TRACKING_URI_INTERNAL", "http://mlflow-nginx:80"
)
PUSHGATEWAY_URL = os.environ.get("PUSHGATEWAY_URL", "shml-pushgateway:9091")

DATASET_DIR_DEFAULT = "/tmp/ray/data/wider_face_rfdetr"
YOLO_DIR_DEFAULT = "/tmp/ray/data/wider_face_yolo"
CHECKPOINT_DIR = Path(
    os.environ.get("CHECKPOINT_DIR", "/tmp/ray/checkpoints/face_detection")
)

# Previous baselines
PHASE5_BASELINE = {"mAP50": 0.859, "recall": 0.769, "precision": 0.881}
PHASE8_BASELINE = {"mAP50": 0.812, "recall": 0.738, "precision": 0.891}
RFDETR_ZERO_SHOT = {"mAP50": 0.0014}

# PII KPI targets
KPI_TARGETS = {
    "mAP50": 0.94,
    "recall": 0.95,
    "precision": 0.90,
    "hard_mAP50": 0.85,
    "tiny_recall": 0.85,
}

MLFLOW_EXPERIMENT = "rfdetr-face-finetune"
MLFLOW_TAGS = {
    "model": "rfdetr-large",
    "backbone": "dinov2",
    "dataset": "wider-face",
    "task": "face-detection",
    "purpose": "pii-compliance",
}


# ═══════════════════════════════════════════════════════════════════════════
# DATA PREPARATION — ensure COCO annotations exist
# ═══════════════════════════════════════════════════════════════════════════


def ensure_coco_annotations(dataset_dir: str, yolo_dir: str) -> bool:
    """Ensure _annotations.coco.json exists for train and val splits.

    COCO annotations in /tmp/ are ephemeral. This function regenerates
    them from YOLO labels if missing, using the yolo_to_rfdetr_coco
    converter or an inline fallback.
    """
    dataset_path = Path(dataset_dir)
    train_annot = dataset_path / "train" / "_annotations.coco.json"
    val_annot = dataset_path / "val" / "_annotations.coco.json"

    if train_annot.exists() and val_annot.exists():
        # Verify they're not empty
        try:
            with open(train_annot) as f:
                td = json.load(f)
            with open(val_annot) as f:
                vd = json.load(f)
            if len(td.get("images", [])) > 0 and len(vd.get("images", [])) > 0:
                print(
                    f"[data] COCO annotations exist: train={len(td['images'])}, val={len(vd['images'])}"
                )
                return True
        except (json.JSONDecodeError, KeyError):
            pass

    print(
        "[data] COCO annotations missing or invalid — regenerating from YOLO labels..."
    )

    # Try using the dedicated converter
    converter_path = os.path.join(
        os.path.dirname(__file__), "data", "yolo_to_rfdetr_coco.py"
    )
    try:
        sys.path.insert(0, os.path.dirname(converter_path))
        from yolo_to_rfdetr_coco import convert_yolo_to_coco

        convert_yolo_to_coco(yolo_dir=yolo_dir, output_dir=dataset_dir)
        print("[data] COCO annotations regenerated via yolo_to_rfdetr_coco")
        return True
    except Exception as e:
        print(f"[data] converter import failed: {e}")

    # Inline fallback: convert YOLO labels to COCO format
    return _inline_yolo_to_coco(yolo_dir, dataset_dir)


def _inline_yolo_to_coco(yolo_dir: str, output_dir: str) -> bool:
    """Minimal inline YOLO-to-COCO conversion as a fallback."""
    try:
        from PIL import Image as PILImage
    except ImportError:
        print("[data] ERROR: PIL not available for conversion")
        return False

    yolo_path = Path(yolo_dir)
    out_path = Path(output_dir)

    for split in ["train", "val"]:
        images_dir = yolo_path / "images" / split
        labels_dir = yolo_path / "labels" / split
        target_dir = out_path / split

        if not images_dir.exists() or not labels_dir.exists():
            print(f"[data] YOLO {split} dirs not found: {images_dir}")
            return False

        target_dir.mkdir(parents=True, exist_ok=True)

        coco = {
            "images": [],
            "annotations": [],
            "categories": [{"id": 0, "name": "face", "supercategory": "person"}],
        }

        ann_id = 1
        img_files = sorted(images_dir.glob("*.jpg")) + sorted(images_dir.glob("*.png"))

        for img_id, img_file in enumerate(img_files, start=1):
            try:
                pil_img = PILImage.open(img_file)
                w, h = pil_img.size
            except Exception:
                continue

            coco["images"].append(
                {
                    "id": img_id,
                    "file_name": img_file.name,
                    "width": w,
                    "height": h,
                }
            )

            # Symlink image if not already present
            target_img = target_dir / img_file.name
            if not target_img.exists():
                try:
                    os.symlink(str(img_file.resolve()), str(target_img))
                except OSError:
                    pass

            # Convert YOLO labels
            label_file = labels_dir / (img_file.stem + ".txt")
            if not label_file.exists():
                continue

            with open(label_file) as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) < 5:
                        continue
                    cls_id = int(parts[0])
                    cx, cy, bw, bh = (
                        float(parts[1]),
                        float(parts[2]),
                        float(parts[3]),
                        float(parts[4]),
                    )

                    # YOLO normalized → COCO absolute
                    abs_w = bw * w
                    abs_h = bh * h
                    abs_x = (cx * w) - (abs_w / 2)
                    abs_y = (cy * h) - (abs_h / 2)

                    coco["annotations"].append(
                        {
                            "id": ann_id,
                            "image_id": img_id,
                            "category_id": cls_id,
                            "bbox": [
                                round(abs_x, 2),
                                round(abs_y, 2),
                                round(abs_w, 2),
                                round(abs_h, 2),
                            ],
                            "area": round(abs_w * abs_h, 2),
                            "iscrowd": 0,
                        }
                    )
                    ann_id += 1

        annot_path = target_dir / "_annotations.coco.json"
        with open(annot_path, "w") as f:
            json.dump(coco, f)

        print(
            f"[data] {split}: {len(coco['images'])} images, {len(coco['annotations'])} annotations"
        )

    return True


# ═══════════════════════════════════════════════════════════════════════════
# NESSIE HELPERS
# ═══════════════════════════════════════════════════════════════════════════


def nessie_create_branch(name: str) -> str | None:
    """Create a Nessie experiment branch from main."""
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
            print(f"  [nessie] branch '{name}' ready")
            return name
        return None
    except Exception as e:
        print(f"  [nessie] branch error: {e}")
        return None


def nessie_tag(name: str) -> bool:
    """Create a Nessie tag at current main HEAD."""
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
# PROMETHEUS METRICS REPORTER
# ═══════════════════════════════════════════════════════════════════════════


class MetricsReporter:
    """Push training metrics to Prometheus Pushgateway."""

    def __init__(self, job_name: str = "rfdetr_face_finetune"):
        self.enabled = False
        self.job_name = job_name
        self.best_map50 = 0.0
        self.best_recall = 0.0
        self.registry = None
        self.gauges: dict[str, Any] = {}

        if not PROMETHEUS_AVAILABLE:
            return
        try:
            resp = requests.get(f"http://{PUSHGATEWAY_URL}/metrics", timeout=2)
            if resp.status_code == 200:
                self.enabled = True
                self.registry = CollectorRegistry()
                print("[prometheus] pushgateway connected")
        except Exception:
            print(f"[prometheus] pushgateway not reachable: {PUSHGATEWAY_URL}")

    def _gauge(self, name: str, desc: str = "") -> Any:
        if name not in self.gauges:
            safe = name.replace(".", "_").replace("-", "_").replace("/", "_")
            self.gauges[name] = Gauge(safe, desc or name, registry=self.registry)
        return self.gauges[name]

    def report_start(self, total_epochs: int, batch_size: int):
        if not self.enabled:
            return
        self._gauge("training_active").set(1)
        self._gauge("training_total_epochs").set(total_epochs)
        self._gauge("training_batch_size").set(batch_size)
        self._gauge("training_start_time").set(time.time())
        self._push()

    def report_epoch(self, log_stats: dict, epoch: int, total_epochs: int):
        """Extract and push metrics from RF-DETR's per-epoch log_stats.

        log_stats keys from RF-DETR pycocotools COCO eval:
          test_coco_eval_bbox: [mAP, mAP50, mAP75, mAP_s, mAP_m, mAP_l,
                                AR@1, AR@10, AR@100, AR_s, AR_m, AR_l]
          train_loss, train_loss_ce, train_loss_bbox, train_loss_giou
          epoch, n_parameters, epoch_time
        """
        if not self.enabled:
            return

        self._gauge("training_epoch").set(epoch)
        self._gauge("training_progress").set(epoch / max(total_epochs, 1))

        coco_bbox = log_stats.get("test_coco_eval_bbox", [])
        if coco_bbox and len(coco_bbox) >= 6:
            map50 = coco_bbox[1]
            self._gauge("training_mAP50_95").set(coco_bbox[0])
            self._gauge("training_mAP50").set(map50)
            self._gauge("training_mAP75").set(coco_bbox[2])
            self._gauge("training_mAP_small").set(coco_bbox[3])
            self._gauge("training_mAP_medium").set(coco_bbox[4])
            self._gauge("training_mAP_large").set(coco_bbox[5])

            if map50 > self.best_map50:
                self.best_map50 = map50
            self._gauge("training_best_mAP50").set(self.best_map50)

            # Recall metrics (AR@100 = recall proxy)
            if len(coco_bbox) >= 9:
                recall = coco_bbox[8]  # AR@100
                if recall > self.best_recall:
                    self.best_recall = recall
                self._gauge("training_AR100").set(recall)
                self._gauge("training_best_AR100").set(self.best_recall)

            # KPI gaps
            self._gauge("training_kpi_gap_mAP50").set(KPI_TARGETS["mAP50"] - map50)
            self._gauge("training_vs_phase5_mAP50").set(
                map50 - PHASE5_BASELINE["mAP50"]
            )
            self._gauge("training_vs_rfdetr_zero_shot").set(
                map50 - RFDETR_ZERO_SHOT["mAP50"]
            )

        # Training loss
        for loss_key in [
            "train_loss",
            "train_loss_ce",
            "train_loss_bbox",
            "train_loss_giou",
        ]:
            if loss_key in log_stats:
                self._gauge(f"training_{loss_key}").set(log_stats[loss_key])

        self._push()

    def report_gpu(self):
        if not self.enabled or not torch.cuda.is_available():
            return
        try:
            import pynvml

            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            self._gauge("gpu_0_utilization").set(util.gpu)
            self._gauge("gpu_0_memory_used_mb").set(mem.used / 1e6)
            self._gauge("gpu_0_memory_total_mb").set(mem.total / 1e6)
            self._gauge("gpu_0_temperature").set(temp)
            self._push()
        except Exception:
            pass

    def report_end(self, success: bool, metrics: dict):
        if not self.enabled:
            return
        self._gauge("training_active").set(0)
        self._gauge("training_end_time").set(time.time())
        self._gauge("training_success").set(1 if success else 0)
        for k, v in metrics.items():
            if isinstance(v, (int, float)):
                self._gauge(f"training_final_{k}").set(v)
        self._push()

    def _push(self):
        if not self.enabled or not self.registry:
            return
        try:
            push_to_gateway(
                PUSHGATEWAY_URL,
                job=self.job_name,
                registry=self.registry,
                grouping_key={"model": "rfdetr-large", "task": "face-finetune"},
            )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# FEATURE STORE
# ═══════════════════════════════════════════════════════════════════════════


def materialize_features(run_id: str, metrics: dict) -> dict:
    """Materialize eval features and training lineage to the feature store."""
    results = {"eval": False, "lineage": False}

    if not FEATURE_CLIENT_AVAILABLE:
        print("  [features] FeatureClient not available")
        return results

    password = os.environ.get("POSTGRES_PASSWORD", "")
    if not password:
        for sp in [
            "/run/secrets/shared_db_password",
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "..",
                "secrets",
                "shared_db_password.txt",
            ),
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "secrets",
                "shared_db_password.txt",
            ),
        ]:
            try:
                with open(sp) as f:
                    password = f.read().strip()
                    break
            except FileNotFoundError:
                continue

    if not password:
        print("  [features] DB password not available")
        return results

    try:
        client = FeatureClient(
            postgres_host=os.environ.get("POSTGRES_HOST", "postgres"),
            postgres_port=int(os.environ.get("POSTGRES_PORT", "5432")),
            postgres_db=os.environ.get("POSTGRES_DB", "inference"),
            postgres_user=os.environ.get("POSTGRES_USER", "inference"),
            postgres_password=password,
        )
        client.init_schema()

        try:
            ok = client.materialize_eval_features(run_id=run_id)
            results["eval"] = ok
            if ok:
                print(f"  [features] eval materialized for {run_id[:12]}")
        except Exception as e:
            print(f"  [features] eval error: {e}")

        try:
            ok = client.materialize_training_lineage(run_id=run_id)
            results["lineage"] = ok
            if ok:
                print(f"  [features] lineage materialized for {run_id[:12]}")
        except Exception as e:
            print(f"  [features] lineage error: {e}")

        client.close()
    except Exception as e:
        print(f"  [features] error: {e}")

    return results


# ═══════════════════════════════════════════════════════════════════════════
# FIFTYONE POST-TRAINING EVAL
# ═══════════════════════════════════════════════════════════════════════════


def fiftyone_post_training(model, dataset_dir: Path, run_id: str, metrics: dict):
    """Create FiftyOne dataset with predictions for post-training analysis."""
    if not FIFTYONE_AVAILABLE:
        print("  [fiftyone] not available, skipping")
        return

    try:
        val_dir = dataset_dir / "val"
        annot_path = val_dir / "_annotations.coco.json"

        dataset_name = f"rfdetr-face-finetune-{run_id[:8] if run_id else 'eval'}"

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
                "model": "rfdetr-large-finetuned",
                "dataset": "wider-face",
                "run_id": run_id or "",
                "metrics": {
                    k: v for k, v in metrics.items() if isinstance(v, (int, float, str))
                },
            }
        )

        # Add predictions (limit for speed)
        from PIL import Image as PILImage

        n_predict = min(300, len(dataset))
        view = dataset.take(n_predict)
        print(f"  [fiftyone] running inference on {n_predict} val samples...")

        pred_count = 0
        for sample in view:
            try:
                pil_img = PILImage.open(sample.filepath).convert("RGB")
                dets = model.predict(pil_img, threshold=0.3)

                fo_dets = []
                if dets is not None and len(dets) > 0:
                    w_img, h_img = pil_img.size
                    for i in range(len(dets.xyxy)):
                        x1, y1, x2, y2 = dets.xyxy[i].tolist()
                        conf = float(dets.confidence[i])
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
                        pred_count += 1

                sample["predictions_rfdetr_finetuned"] = fo.Detections(
                    detections=fo_dets
                )
                sample.save()
            except Exception:
                continue

        dataset.save()
        print(
            f"  [fiftyone] dataset '{dataset_name}': {len(dataset)} samples, {pred_count} predictions"
        )

        # Run evaluation
        try:
            results = dataset.evaluate_detections(
                "predictions_rfdetr_finetuned",
                gt_field="ground_truth",
                eval_key="eval_rfdetr_finetuned",
                compute_mAP=True,
            )
            report = results.report()
            print(f"  [fiftyone] COCO eval:\n{report}")
        except Exception as e:
            print(f"  [fiftyone] eval error: {e}")

    except Exception as e:
        print(f"  [fiftyone] error: {e}")
        import traceback

        traceback.print_exc()


# ═══════════════════════════════════════════════════════════════════════════
# MLFLOW SETUP
# ═══════════════════════════════════════════════════════════════════════════


def setup_mlflow(experiment_ts: str) -> str | None:
    """Configure MLflow tracking (RF-DETR's built-in mlflow=True will use it)."""
    if not MLFLOW_AVAILABLE:
        return None

    try:
        os.environ["MLFLOW_TRACKING_URI"] = MLFLOW_TRACKING_URI
        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
        mlflow.set_experiment(MLFLOW_EXPERIMENT)
        print(f"  [mlflow] URI={MLFLOW_TRACKING_URI}, experiment={MLFLOW_EXPERIMENT}")
        return MLFLOW_EXPERIMENT
    except Exception as e:
        print(f"  [mlflow] setup error: {e}")
        return None


def register_model(checkpoint_path: str, run_id: str, metrics: dict):
    """Register the fine-tuned model in MLflow Model Registry."""
    if not MLFLOW_AVAILABLE or not run_id:
        return

    try:
        model_name = "rfdetr-face-v1"

        # Log checkpoint as artifact
        with mlflow.start_run(run_id=run_id):
            mlflow.log_artifact(checkpoint_path, "model")

            # Log final metrics
            for k, v in metrics.items():
                if isinstance(v, (int, float)):
                    mlflow.log_metric(f"final_{k}", v)

            mlflow.log_params(MLFLOW_TAGS)

        # Register model
        model_uri = f"runs:/{run_id}/model"
        mv = mlflow.register_model(model_uri, model_name)
        print(f"  [mlflow] registered '{model_name}' version {mv.version}")

        # Set alias
        client = mlflow.tracking.MlflowClient()
        try:
            client.set_registered_model_alias(model_name, "challenger", mv.version)
            print(f"  [mlflow] alias @challenger → version {mv.version}")
        except Exception as e:
            print(f"  [mlflow] alias error: {e}")

    except Exception as e:
        print(f"  [mlflow] registration error: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# TRAINING
# ═══════════════════════════════════════════════════════════════════════════


def train_rfdetr_face(args: argparse.Namespace) -> dict[str, Any]:
    """Run RF-DETR Large fine-tuning on WIDER Face with platform callbacks."""

    result = {"success": False, "metrics": {}, "run_id": None, "checkpoint": None}

    if not RFDETR_AVAILABLE:
        print("[ERROR] RF-DETR not installed. pip install rfdetr>=1.5.0")
        return result

    dataset_dir = Path(args.dataset_dir)
    experiment_ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = CHECKPOINT_DIR / f"rfdetr_face_{experiment_ts}"
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Ensure COCO annotations exist ──
    if not ensure_coco_annotations(str(dataset_dir), args.yolo_dir):
        print("[ERROR] Failed to prepare COCO annotations")
        return result

    # ── Validate dataset ──
    val_annot = dataset_dir / "val" / "_annotations.coco.json"
    train_annot = dataset_dir / "train" / "_annotations.coco.json"

    if not val_annot.exists() or not train_annot.exists():
        print(f"[ERROR] COCO annotations not found after preparation")
        print(f"  Expected: {dataset_dir}/{{train,val}}/_annotations.coco.json")
        return result

    with open(train_annot) as f:
        train_coco = json.load(f)
    with open(val_annot) as f:
        val_coco = json.load(f)

    n_train = len(train_coco["images"])
    n_val = len(val_coco["images"])
    n_train_ann = len(train_coco["annotations"])
    n_val_ann = len(val_coco["annotations"])
    class_names = [c["name"] for c in train_coco["categories"]]

    print()
    print("=" * 72)
    print("    RF-DETR Face Fine-Tuning — WIDER Face")
    print("=" * 72)
    print(f"  Model:        RF-DETR Large (DINOv2 backbone, 128M params)")
    print(f"  Dataset:      {dataset_dir}")
    print(f"  Train:        {n_train:,} images, {n_train_ann:,} annotations")
    print(f"  Val:          {n_val:,} images, {n_val_ann:,} annotations")
    print(f"  Classes:      {class_names}")
    print(f"  Epochs:       {args.epochs}")
    print(
        f"  Batch size:   {args.batch_size} (grad_accum={args.grad_accum}, "
        f"effective={args.batch_size * args.grad_accum})"
    )
    print(f"  Resolution:   704×704 (native)")
    print(f"  LR:           {args.lr} (encoder: {args.lr_encoder})")
    print(f"  Warmup:       {args.warmup_epochs} epochs")
    print(f"  Output:       {output_dir}")
    if args.resume:
        print(f"  Resume from:  {args.resume}")
    print()

    # ── Initialize integrations ──
    print("--- Platform Integrations ---")

    # MLflow
    setup_mlflow(experiment_ts)

    # Nessie
    branch_name = nessie_create_branch(f"experiment/rfdetr-face-{experiment_ts}")

    # Prometheus
    reporter = MetricsReporter()
    reporter.report_start(total_epochs=args.epochs, batch_size=args.batch_size)

    # ── Load model ──
    print("\n--- Model Initialization ---")
    model = RFDETRLarge()

    if args.resume:
        resume_path = Path(args.resume)
        if resume_path.exists():
            print(f"  Loading checkpoint: {resume_path}")
            try:
                state_dict = torch.load(str(resume_path), map_location="cpu")
                if "model" in state_dict:
                    state_dict = state_dict["model"]
                model.model.load_state_dict(state_dict, strict=False)
                print("  Checkpoint loaded successfully")
            except Exception as e:
                print(f"  WARNING: checkpoint load failed: {e}")
                print("  Continuing with pretrained COCO weights")
        else:
            print(f"  WARNING: checkpoint not found: {resume_path}")

    print(f"  RF-DETR Large initialized (resolution={model.model.resolution})")

    # ── Build callbacks ──
    epoch_metrics_log: list[dict] = []  # Capture per-epoch metrics

    def on_epoch_end(log_stats: dict):
        """Called by RF-DETR after each epoch with pycocotools results."""
        epoch = log_stats.get("epoch", 0)
        coco_bbox = log_stats.get("test_coco_eval_bbox", [])

        map50 = coco_bbox[1] if len(coco_bbox) > 1 else 0.0
        map50_95 = coco_bbox[0] if len(coco_bbox) > 0 else 0.0
        map75 = coco_bbox[2] if len(coco_bbox) > 2 else 0.0
        train_loss = log_stats.get("train_loss", 0.0)

        # Size-specific mAP
        map_small = coco_bbox[3] if len(coco_bbox) > 3 else 0.0
        map_medium = coco_bbox[4] if len(coco_bbox) > 4 else 0.0
        map_large = coco_bbox[5] if len(coco_bbox) > 5 else 0.0

        # Recall (AR@100)
        ar100 = coco_bbox[8] if len(coco_bbox) > 8 else 0.0

        print(
            f"\n  [epoch {epoch:3d}] mAP50={map50:.4f}  mAP75={map75:.4f}  "
            f"AR100={ar100:.4f}  loss={train_loss:.4f}  "
            f"mAP_s={map_small:.4f}  mAP_m={map_medium:.4f}  mAP_l={map_large:.4f}"
        )

        # KPI gap
        gap_50 = KPI_TARGETS["mAP50"] - map50
        vs_phase5 = map50 - PHASE5_BASELINE["mAP50"]
        print(f"           KPI gap: {gap_50:+.4f}  vs Phase5: {vs_phase5:+.4f}")

        # Prometheus
        reporter.report_epoch(log_stats, epoch, args.epochs)
        reporter.report_gpu()

        epoch_metrics_log.append(
            {
                "epoch": epoch,
                "mAP50": round(map50, 4),
                "mAP50_95": round(map50_95, 4),
                "mAP75": round(map75, 4),
                "mAP_small": round(map_small, 4),
                "mAP_medium": round(map_medium, 4),
                "mAP_large": round(map_large, 4),
                "AR100": round(ar100, 4),
                "train_loss": round(train_loss, 6) if train_loss else None,
                "epoch_time": log_stats.get("epoch_time", ""),
            }
        )

    def on_train_end():
        """Called by RF-DETR after training completes."""
        print("\n--- Post-Training Integration ---")

        final = epoch_metrics_log[-1] if epoch_metrics_log else {}
        run_id = ""

        # Get MLflow run ID
        if MLFLOW_AVAILABLE:
            try:
                active_run = mlflow.active_run()
                if active_run:
                    run_id = active_run.info.run_id
                    result["run_id"] = run_id

                    # Log platform-specific params
                    mlflow.log_params(
                        {
                            "script": "train_rfdetr_face.py",
                            "task": "face-detection",
                            "platform_integrations": "mlflow,nessie,fiftyone,features,prometheus",
                            "kpi_target_mAP50": KPI_TARGETS["mAP50"],
                            "kpi_target_recall": KPI_TARGETS["recall"],
                        }
                    )

                    # Log epoch history as custom metrics
                    for entry in epoch_metrics_log:
                        ep = entry.get("epoch", 0)
                        for k, v in entry.items():
                            if k != "epoch" and isinstance(v, (int, float)):
                                mlflow.log_metric(f"platform_{k}", v, step=ep)

                    # Log best checkpoint as artifact
                    best_ckpt = output_dir / "checkpoint_best_total.pth"
                    if best_ckpt.exists():
                        mlflow.log_artifact(str(best_ckpt), "model")
                        result["checkpoint"] = str(best_ckpt)
                        print(f"  [mlflow] best checkpoint logged")

                    print(f"  [mlflow] run_id={run_id[:12]}...")
            except Exception as e:
                print(f"  [mlflow] post-training: {e}")

        # Nessie tag
        tag_name = f"rfdetr-face-{experiment_ts}"
        if nessie_tag(tag_name):
            print(f"  [nessie] tagged '{tag_name}'")

        # FiftyOne eval
        fiftyone_post_training(model, dataset_dir, run_id, final)

        # Feature Store
        if run_id:
            materialize_features(run_id, final)

        # Prometheus — signal completion
        reporter.report_end(success=True, metrics=final)

        print("  [integrations] post-training complete")

    # Register callbacks
    model.callbacks["on_fit_epoch_end"].append(on_epoch_end)
    model.callbacks["on_train_end"].append(on_train_end)

    # ── Train ──
    print("\n--- Training ---")
    train_start = time.time()

    try:
        model.train(
            dataset_dir=str(dataset_dir),
            epochs=args.epochs,
            batch_size=args.batch_size,
            grad_accum_steps=args.grad_accum,
            lr=args.lr,
            lr_encoder=args.lr_encoder,
            weight_decay=args.weight_decay,
            warmup_epochs=float(args.warmup_epochs),
            output_dir=str(output_dir),
            class_names=class_names,
            use_ema=True,
            num_workers=args.num_workers,
            multi_scale=True,
            early_stopping=args.early_stopping,
            mlflow=MLFLOW_AVAILABLE,
            project=MLFLOW_EXPERIMENT,
            run=f"rfdetr-face-{experiment_ts}",
        )

        train_duration = time.time() - train_start
        print(f"\n  Training completed in {train_duration / 60:.1f} minutes")

    except torch.cuda.OutOfMemoryError:
        train_duration = time.time() - train_start
        print(f"\n[ERROR] CUDA OOM after {train_duration / 60:.1f}m")
        print(
            "  Try reducing batch_size (--batch-size 2) or grad_accum (--grad-accum 2)"
        )
        reporter.report_end(success=False, metrics={"error": "OOM"})
        _cleanup_on_failure()
        return result

    except Exception as e:
        train_duration = time.time() - train_start
        print(f"\n[ERROR] Training failed after {train_duration / 60:.1f}m: {e}")
        import traceback

        traceback.print_exc()
        reporter.report_end(success=False, metrics={})
        _cleanup_on_failure()
        return result

    # ── Locate best checkpoint ──
    best_ckpt = output_dir / "checkpoint_best_total.pth"
    if not best_ckpt.exists():
        # Try alternative checkpoint names
        for alt in ["checkpoint_best.pth", "best.pth", "checkpoint.pth"]:
            alt_path = output_dir / alt
            if alt_path.exists():
                best_ckpt = alt_path
                break

    if best_ckpt.exists():
        result["checkpoint"] = str(best_ckpt)
        ckpt_size_mb = best_ckpt.stat().st_size / 1e6
        print(f"\n  Best checkpoint: {best_ckpt} ({ckpt_size_mb:.1f} MB)")

        # Also copy to a well-known location for the benchmark script
        stable_path = CHECKPOINT_DIR / "rfdetr_face_best.pth"
        try:
            import shutil

            shutil.copy2(str(best_ckpt), str(stable_path))
            print(f"  Copied to: {stable_path}")
        except Exception as e:
            print(f"  Copy failed: {e}")
    else:
        print("\n  WARNING: no best checkpoint found in output dir")
        # List what we do have
        if output_dir.exists():
            ckpts = list(output_dir.glob("*.pth"))
            if ckpts:
                print(f"  Available checkpoints: {[c.name for c in ckpts]}")
                result["checkpoint"] = str(ckpts[0])

    # ── Final Summary ──
    final = epoch_metrics_log[-1] if epoch_metrics_log else {}
    result["metrics"] = final
    result["success"] = True

    # Find best epoch
    if epoch_metrics_log:
        best_epoch = max(epoch_metrics_log, key=lambda x: x.get("mAP50", 0))
        print(
            f"\n  Best epoch: {best_epoch.get('epoch')} "
            f"(mAP50={best_epoch.get('mAP50', 0):.4f})"
        )

    # KPI assessment
    print("\n--- KPI Assessment ---")
    print(f"  {'Metric':<15s} {'Value':>8s} {'Target':>8s} {'Gap':>8s} {'Status':>8s}")
    print(f"  {'─' * 55}")

    final_map50 = final.get("mAP50", 0)
    final_ar100 = final.get("AR100", 0)

    kpi_checks = [
        ("mAP50", final_map50, KPI_TARGETS["mAP50"]),
        ("Recall(AR100)", final_ar100, KPI_TARGETS["recall"]),
        ("mAP_small", final.get("mAP_small", 0), KPI_TARGETS.get("hard_mAP50", 0.85)),
    ]

    for name, value, target in kpi_checks:
        gap = value - target
        status = "✅ PASS" if value >= target else "❌ MISS"
        print(f"  {name:<15s} {value:>8.4f} {target:>8.4f} {gap:>+8.4f} {status:>8s}")

    # Baseline comparisons
    print(
        f"\n  vs RF-DETR zero-shot: mAP50 Δ = {final_map50 - RFDETR_ZERO_SHOT['mAP50']:+.4f}"
    )
    print(
        f"  vs Phase 5 YOLOv8m:  mAP50 Δ = {final_map50 - PHASE5_BASELINE['mAP50']:+.4f}"
    )
    print(
        f"  vs Phase 8 P2:       mAP50 Δ = {final_map50 - PHASE8_BASELINE['mAP50']:+.4f}"
    )

    # Register model in MLflow
    if result["checkpoint"] and result.get("run_id"):
        register_model(result["checkpoint"], result["run_id"], final)

    # Save results JSON
    results_path = output_dir / "rfdetr_face_results.json"
    with open(results_path, "w") as f:
        json.dump(
            {
                "experiment": f"rfdetr-face-{experiment_ts}",
                "run_id": result.get("run_id", ""),
                "config": {
                    "epochs": args.epochs,
                    "batch_size": args.batch_size,
                    "grad_accum_steps": args.grad_accum,
                    "lr": args.lr,
                    "lr_encoder": args.lr_encoder,
                    "warmup_epochs": args.warmup_epochs,
                    "resolution": 704,
                    "weight_decay": args.weight_decay,
                    "early_stopping": args.early_stopping,
                },
                "metrics": final,
                "best_epoch": best_epoch if epoch_metrics_log else {},
                "epoch_history": epoch_metrics_log,
                "checkpoint": result.get("checkpoint", ""),
                "baselines": {
                    "phase5": PHASE5_BASELINE,
                    "phase8": PHASE8_BASELINE,
                    "rfdetr_zero_shot": RFDETR_ZERO_SHOT,
                },
                "kpi_targets": KPI_TARGETS,
                "duration_min": round(train_duration / 60, 2),
                "output_dir": str(output_dir),
            },
            f,
            indent=2,
            default=str,
        )
    print(f"\n  Results saved: {results_path}")

    # End MLflow run
    if MLFLOW_AVAILABLE:
        try:
            if mlflow.active_run():
                mlflow.end_run("FINISHED")
        except Exception:
            pass

    # ── Next steps ──
    if result["checkpoint"]:
        print(f"\n--- Next Steps ---")
        print(f"  Re-benchmark with fine-tuned model:")
        print(
            f"    python face_detection_benchmark.py --rfdetr-checkpoint {result['checkpoint']}"
        )
        print(f"  Or use the stable path:")
        stable = CHECKPOINT_DIR / "rfdetr_face_best.pth"
        print(f"    python face_detection_benchmark.py --rfdetr-checkpoint {stable}")

    # ── Reclaim GPU ──
    try:
        reclaim_gpu_after_training(gpu_id=0, job_id=_job_id)
    except Exception as e:
        print(f"[gpu] reclaim failed: {e}")

    return result


def _cleanup_on_failure():
    """Clean up resources after a training failure."""
    # End MLflow run
    if MLFLOW_AVAILABLE:
        try:
            mlflow.end_run("FAILED")
        except Exception:
            pass
    # Reclaim GPU
    try:
        reclaim_gpu_after_training(gpu_id=0, job_id=_job_id)
    except Exception:
        pass
    # Clear CUDA cache
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        gc.collect()


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        description="RF-DETR Face Fine-Tuning on WIDER Face",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Quick test (1 epoch)
  python train_rfdetr_face.py --epochs 1

  # Standard training
  python train_rfdetr_face.py --epochs 30 --batch-size 4

  # Conservative (lower memory)
  python train_rfdetr_face.py --epochs 30 --batch-size 2 --grad-accum 8

  # Resume from checkpoint
  python train_rfdetr_face.py --epochs 30 --resume /path/to/checkpoint.pth

  # After training, re-benchmark:
  python face_detection_benchmark.py --rfdetr-checkpoint /tmp/ray/checkpoints/face_detection/rfdetr_face_best.pth
        """,
    )
    parser.add_argument(
        "--epochs", type=int, default=30, help="Training epochs (default: 30)"
    )
    parser.add_argument(
        "--batch-size", type=int, default=4, help="Batch size per step (default: 4)"
    )
    parser.add_argument(
        "--grad-accum",
        type=int,
        default=4,
        help="Gradient accumulation steps (default: 4, effective batch=16)",
    )
    parser.add_argument(
        "--lr", type=float, default=1e-4, help="Decoder learning rate (default: 1e-4)"
    )
    parser.add_argument(
        "--lr-encoder",
        type=float,
        default=1.5e-5,
        help="Encoder (DINOv2) learning rate (default: 1.5e-5)",
    )
    parser.add_argument(
        "--weight-decay", type=float, default=1e-4, help="Weight decay (default: 1e-4)"
    )
    parser.add_argument(
        "--warmup-epochs", type=int, default=3, help="Warmup epochs (default: 3)"
    )
    parser.add_argument(
        "--num-workers", type=int, default=2, help="DataLoader workers (default: 2)"
    )
    parser.add_argument(
        "--dataset-dir",
        default=DATASET_DIR_DEFAULT,
        help="RF-DETR COCO dataset directory",
    )
    parser.add_argument(
        "--yolo-dir",
        default=YOLO_DIR_DEFAULT,
        help="YOLO source directory (for annotation regeneration)",
    )
    parser.add_argument(
        "--resume", default=None, help="Path to checkpoint to resume from"
    )
    parser.add_argument(
        "--early-stopping", action="store_true", help="Enable early stopping"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Config check only, no training"
    )

    args = parser.parse_args()

    if args.dry_run:
        print("=" * 60)
        print("DRY RUN — Configuration Check")
        print("=" * 60)
        print(f"\nTraining Config:")
        print(f"  Epochs:        {args.epochs}")
        print(
            f"  Batch size:    {args.batch_size} × {args.grad_accum} = {args.batch_size * args.grad_accum} effective"
        )
        print(f"  LR:            {args.lr} (encoder: {args.lr_encoder})")
        print(f"  Warmup:        {args.warmup_epochs} epochs")
        print(f"  Weight decay:  {args.weight_decay}")
        print(f"  Resolution:    704×704")
        print(f"  Resume:        {args.resume or 'None (from COCO pretrained)'}")

        print(f"\nData:")
        print(f"  Dataset dir:   {args.dataset_dir}")
        print(f"  YOLO dir:      {args.yolo_dir}")

        dataset_dir = Path(args.dataset_dir)
        for split in ["train", "val"]:
            annot = dataset_dir / split / "_annotations.coco.json"
            if annot.exists():
                with open(annot) as f:
                    d = json.load(f)
                print(
                    f"  {split}: {len(d['images']):,} images, {len(d['annotations']):,} annotations"
                )
            else:
                print(f"  {split}: MISSING ({annot})")

        print(f"\nIntegrations:")
        print(f"  RF-DETR:      {'✅' if RFDETR_AVAILABLE else '❌ MISSING'}")
        print(f"  MLflow:       {'✅' if MLFLOW_AVAILABLE else '⚠️  not available'}")
        print(f"  FiftyOne:     {'✅' if FIFTYONE_AVAILABLE else '⚠️  not available'}")
        print(
            f"  Features:     {'✅' if FEATURE_CLIENT_AVAILABLE else '⚠️  not available'}"
        )
        print(f"  Prometheus:   {'✅' if PROMETHEUS_AVAILABLE else '⚠️  not available'}")
        print(
            f"  CUDA:         {'✅ ' + torch.cuda.get_device_name(0) if torch.cuda.is_available() else '❌ MISSING'}"
        )

        print(f"\nKPI Targets:")
        for k, v in KPI_TARGETS.items():
            print(f"  {k}: {v}")

        print(f"\nEstimated Training Time:")
        est_min = args.epochs * 8  # ~8 min/epoch on 3090 Ti
        print(f"  ~{est_min} min ({est_min / 60:.1f} hours) on RTX 3090 Ti")

        return

    result = train_rfdetr_face(args)

    if result["success"]:
        print(f"\n{'=' * 60}")
        print("RF-DETR Face Fine-Tuning COMPLETED")
        print(f"{'=' * 60}")
        if result.get("checkpoint"):
            print(f"  Checkpoint: {result['checkpoint']}")
        if result.get("metrics"):
            m = result["metrics"]
            print(f"  Final mAP50: {m.get('mAP50', 'N/A')}")
    else:
        print(f"\n{'=' * 60}")
        print("RF-DETR Face Fine-Tuning FAILED")
        print(f"{'=' * 60}")
        sys.exit(1)


if __name__ == "__main__":
    main()
