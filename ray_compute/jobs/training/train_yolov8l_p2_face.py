#!/usr/bin/env python3
"""
Phase 6B — YOLOv8L-P2 Face Detection Training
================================================

Fine-tunes YOLOv8L with a P2/4 detection head on WIDER Face at 960px.
The P2 head enables detection of faces as small as ~7px, critical for
crowd scenes and distant/tiny faces in PII compliance.

**Why P2?**
  Phase 5 proved P2 detection head improves small-face recall significantly.
  Phase 6A showed YOLOv8L wins over v11L and v12L. This combines both:
  the proven L-scale backbone with the P2 extra detection layer.

**Architecture:**
  - Backbone: YOLOv8L (depth=1.0, width=1.0, max_channels=512)
  - Head: 4-scale Detect (P2/4, P3/8, P4/16, P5/32)
  - P2/4 detects faces ≥5px at 1280px input
  - Config: configs/yolov8l-face-p2.yaml

**Training Strategy:**
  - Input: 960px (vs 1280 — saves ~35% VRAM while keeping P2 effective)
  - Pretrained: yolov8l-face.pt (lindevs face-trained base)
  - Augmentations: copy_paste=0.3, mosaic=1.0, mixup=0.15
  - Detection: max_det=500, iou=0.7 (for crowd scenes)
  - Batch 2 + rect=True + cache=ram for memory efficiency
  - amp=True (mixed precision) for ~30% memory savings

**Pipeline Position:**
  Phase 6A: YOLOv8L baseline comparison → YOLOv8L wins ✓
  ➜ Phase 6B: YOLOv8L-P2 training (THIS)
  Phase 6C: Final head-to-head → production model selection

**Targets (PII KPI):**
  mAP50 ≥ 94%  |  Recall ≥ 95%  |  Precision ≥ 90%
  Crowd recall (100+ faces) ≥ 70%  |  Tiny(<16px) recall ≥ 85%

Usage:
    python train_yolov8l_p2_face.py                        # defaults
    python train_yolov8l_p2_face.py --epochs 100           # custom epochs
    python train_yolov8l_p2_face.py --resume               # resume last
    python train_yolov8l_p2_face.py --batch-size 2         # reduce batch

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
from typing import Any, Optional

# ═══════════════════════════════════════════════════════════════════════════
# FIX: Monkey-patch ray.tune BEFORE ultralytics import
# Ultralytics 8.0.200 calls ray.tune.is_session_enabled() which was removed
# in newer Ray versions. Patching here ensures it's fixed before any
# Ultralytics code registers its raytune callback.
# ═══════════════════════════════════════════════════════════════════════════
try:
    import ray.tune

    if not hasattr(ray.tune, "is_session_enabled"):
        ray.tune.is_session_enabled = lambda: False
        print("[fix] Patched ray.tune.is_session_enabled (removed in this Ray version)")
except ImportError:
    pass

# ═══════════════════════════════════════════════════════════════════════════
# GPU YIELD — MUST happen before torch import
# ═══════════════════════════════════════════════════════════════════════════
_script_dir_yield = os.path.dirname(os.path.abspath(__file__))
# Support both project layout (utils/ sibling) and flat container layout
for _yp in [
    os.path.join(_script_dir_yield, ".."),  # project: ray_compute/jobs/
    _script_dir_yield,  # flat: /opt/ray/job_workspaces/
]:
    _yp = os.path.abspath(_yp)
    if os.path.isdir(_yp) and _yp not in sys.path:
        sys.path.insert(0, _yp)

_job_id = os.environ.get("RAY_JOB_ID", f"yolov8l-p2-{os.getpid()}")
_gpu_yielded = False

try:
    from utils.gpu_yield import yield_gpu_for_training, reclaim_gpu_after_training

    _gpu_yielded = yield_gpu_for_training(gpu_id=0, job_id=_job_id, timeout=30)
except ImportError:
    try:
        # Flat layout: gpu_yield.py in same directory
        from gpu_yield import yield_gpu_for_training, reclaim_gpu_after_training

        _gpu_yielded = yield_gpu_for_training(gpu_id=0, job_id=_job_id, timeout=30)
    except ImportError:
        print("[gpu] GPU yield module not available — continuing without yield")
except Exception as e:
    print(f"[gpu] GPU yield failed: {e} — continuing anyway")

# Now safe to import torch
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
    vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
    print(f"[cuda] {gpu_name} — {vram_gb:.1f} GB VRAM")
    print(f"[cuda] VRAM free: {torch.cuda.mem_get_info(0)[0] / 1e9:.1f} GB")
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

# ── Prometheus ──
PROMETHEUS_AVAILABLE = False
try:
    from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

    PROMETHEUS_AVAILABLE = True
    print("[prometheus] available")
except ImportError:
    print("[prometheus] not available")

# ── Ultralytics ──
try:
    from ultralytics import YOLO
    from ultralytics.utils import LOGGER as yolo_logger

    print(f"[ultralytics] available")
except ImportError:
    print("[ultralytics] NOT installed — pip install ultralytics>=8.3")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

NESSIE_URI = os.environ.get("NESSIE_URI", "http://shml-nessie:19120")
MLFLOW_TRACKING_URI = os.environ.get(
    "MLFLOW_TRACKING_URI_INTERNAL", "http://mlflow-nginx:80"
)
PUSHGATEWAY_URL = os.environ.get("PUSHGATEWAY_URL", "shml-pushgateway:9091")

DATASET_DIR = "/tmp/ray/data/wider_face_yolo"
# Support both project layout and flat container layout
_script_dir_cfg = Path(__file__).parent
CONFIG_DIR = _script_dir_cfg / "configs"
P2_CONFIG_CANDIDATES = [
    CONFIG_DIR / "yolov8l-face-p2.yaml",  # project layout
    _script_dir_cfg / "yolov8l-face-p2.yaml",  # flat container layout
]
P2_CONFIG = next(
    (p for p in P2_CONFIG_CANDIDATES if p.exists()), P2_CONFIG_CANDIDATES[0]
)
PRETRAINED_WEIGHTS = "/tmp/ray/yolov8l-face.pt"
CHECKPOINT_DIR = Path(
    os.environ.get("CHECKPOINT_DIR", "/tmp/ray/checkpoints/face_detection")
)

# Previous baselines for comparison
BASELINES = {
    "phase5_yolov8m_p2": {"mAP50": 0.859, "recall": 0.769, "precision": 0.881},
    "phase6a_yolov8l": {
        "mAP@50:95": 0.3462,
        "precision": 0.8737,
        "recall": 0.7526,
        "F1": 0.8086,
    },
    "phase6a_yolov11l": {"mAP@50:95": 0.3614, "precision": 0.8609, "recall": 0.6894},
    "rfdetr_finetuned": {"mAP@50:95": 0.3208, "precision": 0.8064, "recall": 0.6002},
}

# PII KPI targets
KPI_TARGETS = {
    "mAP50": 0.94,
    "recall": 0.95,
    "precision": 0.90,
    "crowd_recall": 0.70,
    "tiny_recall": 0.85,
}

MLFLOW_EXPERIMENT = "yolov8l-p2-face-phase6b"
MLFLOW_TAGS = {
    "model": "yolov8l-p2",
    "backbone": "yolov8l",
    "head": "P2-P3-P4-P5",
    "dataset": "wider-face",
    "task": "face-detection",
    "purpose": "pii-compliance",
    "phase": "6B",
    "imgsz": "960",
}

# ═══════════════════════════════════════════════════════════════════════════
# PROMETHEUS METRICS
# ═══════════════════════════════════════════════════════════════════════════


class TrainingMetrics:
    """Push training metrics to Prometheus for Grafana dashboards."""

    def __init__(self, job_name: str = "yolov8l_p2_training"):
        self.enabled = PROMETHEUS_AVAILABLE
        self.job_name = job_name
        if self.enabled:
            self.registry = CollectorRegistry()
            self.epoch_gauge = Gauge(
                "training_epoch", "Current epoch", registry=self.registry
            )
            self.loss_gauge = Gauge(
                "training_loss", "Training loss", ["loss_type"], registry=self.registry
            )
            self.map50_gauge = Gauge(
                "training_map50", "Validation mAP@50", registry=self.registry
            )
            self.map_gauge = Gauge(
                "training_map", "Validation mAP@50:95", registry=self.registry
            )
            self.lr_gauge = Gauge(
                "training_lr", "Learning rate", registry=self.registry
            )
            self.gpu_mem_gauge = Gauge(
                "training_gpu_memory_gb",
                "GPU memory used (GB)",
                registry=self.registry,
            )

    def push(self, epoch: int, metrics: dict):
        if not self.enabled:
            return
        try:
            self.epoch_gauge.set(epoch)
            if "train/box_loss" in metrics:
                self.loss_gauge.labels("box").set(metrics["train/box_loss"])
            if "train/cls_loss" in metrics:
                self.loss_gauge.labels("cls").set(metrics["train/cls_loss"])
            if "train/dfl_loss" in metrics:
                self.loss_gauge.labels("dfl").set(metrics["train/dfl_loss"])
            if "metrics/mAP50(B)" in metrics:
                self.map50_gauge.set(metrics["metrics/mAP50(B)"])
            if "metrics/mAP50-95(B)" in metrics:
                self.map_gauge.set(metrics["metrics/mAP50-95(B)"])
            if "lr/pg0" in metrics:
                self.lr_gauge.set(metrics["lr/pg0"])
            if torch.cuda.is_available():
                self.gpu_mem_gauge.set(torch.cuda.memory_allocated(0) / 1e9)
            push_to_gateway(PUSHGATEWAY_URL, job=self.job_name, registry=self.registry)
        except Exception as e:
            print(f"[prometheus] push error: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# NESSIE INTEGRATION — catalog lineage
# ═══════════════════════════════════════════════════════════════════════════


def nessie_create_branch(branch_name: str) -> bool:
    """Create a Nessie branch for this experiment."""
    try:
        # Get default branch hash
        resp = requests.get(f"{NESSIE_URI}/api/v1/trees/tree/main", timeout=5)
        if resp.status_code != 200:
            return False
        main_hash = resp.json().get("hash", "")

        resp = requests.post(
            f"{NESSIE_URI}/api/v1/trees/branch",
            json={"name": branch_name, "hash": main_hash},
            timeout=5,
        )
        if resp.status_code in (200, 201, 409):  # 409 = already exists
            print(f"[nessie] branch '{branch_name}' ready")
            return True
    except Exception as e:
        print(f"[nessie] branch creation failed: {e}")
    return False


def nessie_tag_model(branch_name: str, tag_name: str, metrics: dict) -> bool:
    """Tag a successful model checkpoint in Nessie."""
    try:
        resp = requests.get(f"{NESSIE_URI}/api/v1/trees/tree/{branch_name}", timeout=5)
        if resp.status_code != 200:
            return False
        branch_hash = resp.json().get("hash", "")

        resp = requests.post(
            f"{NESSIE_URI}/api/v1/trees/tag",
            json={"name": tag_name, "hash": branch_hash},
            timeout=5,
        )
        if resp.status_code in (200, 201, 409):
            print(f"[nessie] tagged '{tag_name}' on '{branch_name}'")
            return True
    except Exception as e:
        print(f"[nessie] tagging failed: {e}")
    return False


# ═══════════════════════════════════════════════════════════════════════════
# CALLBACKS — Ultralytics YOLO callbacks for integration
# ═══════════════════════════════════════════════════════════════════════════


class Phase6BCallbacks:
    """Training callbacks for Phase 6B metrics tracking and integration."""

    def __init__(self, metrics_pusher: TrainingMetrics, run_name: str):
        self.metrics_pusher = metrics_pusher
        self.run_name = run_name
        self.best_map50 = 0.0
        self.best_map = 0.0
        self.best_epoch = 0
        self.epoch_times = []
        self.start_time = time.time()

    def on_train_epoch_end(self, trainer):
        """Called at the end of each training epoch."""
        epoch = trainer.epoch + 1
        metrics = trainer.metrics or {}

        # Push to Prometheus
        self.metrics_pusher.push(epoch, metrics)

        # Track best
        map50 = metrics.get("metrics/mAP50(B)", 0.0)
        map_val = metrics.get("metrics/mAP50-95(B)", 0.0)
        if map50 > self.best_map50:
            self.best_map50 = map50
            self.best_map = map_val
            self.best_epoch = epoch

        # Log epoch summary
        elapsed = time.time() - self.start_time
        box_loss = metrics.get("train/box_loss", 0.0)
        cls_loss = metrics.get("train/cls_loss", 0.0)
        dfl_loss = metrics.get("train/dfl_loss", 0.0)
        lr = metrics.get("lr/pg0", 0.0)

        print(
            f"  [epoch {epoch:3d}] "
            f"box={box_loss:.4f} cls={cls_loss:.4f} dfl={dfl_loss:.4f} | "
            f"mAP50={map50:.4f} mAP={map_val:.4f} | "
            f"lr={lr:.6f} | "
            f"best={self.best_map50:.4f}@{self.best_epoch} | "
            f"{elapsed/60:.0f}min"
        )

        # Log to MLflow
        if MLFLOW_AVAILABLE and mlflow.active_run():
            try:
                mlflow.log_metrics(
                    {
                        "epoch": epoch,
                        "train_box_loss": box_loss,
                        "train_cls_loss": cls_loss,
                        "train_dfl_loss": dfl_loss,
                        "val_mAP50": map50,
                        "val_mAP50_95": map_val,
                        "lr": lr,
                        "best_mAP50": self.best_map50,
                    },
                    step=epoch,
                )
            except Exception:
                pass

    def on_train_end(self, trainer):
        """Called when training completes."""
        total_time = time.time() - self.start_time
        print(f"\n{'═' * 70}")
        print(f"Training complete in {total_time/3600:.1f}h")
        print(
            f"Best: mAP50={self.best_map50:.4f} mAP={self.best_map:.4f} @ epoch {self.best_epoch}"
        )
        print(f"{'═' * 70}\n")

    def register(self, model: YOLO):
        """Register callbacks with YOLO model."""
        model.add_callback("on_train_epoch_end", self.on_train_epoch_end)
        model.add_callback("on_train_end", self.on_train_end)


# ═══════════════════════════════════════════════════════════════════════════
# TRAINING
# ═══════════════════════════════════════════════════════════════════════════


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase 6B — YOLOv8L-P2 face detection training"
    )
    parser.add_argument(
        "--epochs", type=int, default=100, help="Training epochs (default: 100)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=2,
        help="Batch size per GPU (default: 2, conservative for 1280px P2)",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=960,
        help="Input image size (default: 960, memory-optimized for P2)",
    )
    parser.add_argument(
        "--device", type=int, default=0, help="GPU device ID (default: 0)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Dataloader workers (default: 4, reduced to save CPU/memory)",
    )
    parser.add_argument(
        "--resume", action="store_true", help="Resume from last checkpoint"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate config without training"
    )
    parser.add_argument(
        "--patience", type=int, default=30, help="Early stopping patience (default: 30)"
    )
    parser.add_argument(
        "--lr0", type=float, default=0.01, help="Initial learning rate (default: 0.01)"
    )
    parser.add_argument(
        "--lrf", type=float, default=0.01, help="Final LR fraction (default: 0.01)"
    )
    parser.add_argument(
        "--optimizer", type=str, default="AdamW", help="Optimizer (default: AdamW)"
    )
    parser.add_argument(
        "--weight-decay",
        type=float,
        default=0.0005,
        help="Weight decay (default: 0.0005)",
    )
    parser.add_argument(
        "--cos-lr",
        action="store_true",
        default=True,
        help="Cosine LR scheduler (default: True)",
    )
    parser.add_argument("--no-cos-lr", action="store_false", dest="cos_lr")
    parser.add_argument(
        "--pretrained",
        type=str,
        default=PRETRAINED_WEIGHTS,
        help="Pretrained weight path",
    )
    parser.add_argument(
        "--name", type=str, default=None, help="Run name (auto-generated if not set)"
    )
    return parser.parse_args()


def validate_environment(args: argparse.Namespace) -> dict:
    """Pre-flight checks — validate all resources exist."""
    issues = []
    info = {}

    # Check P2 config
    if not P2_CONFIG.exists():
        issues.append(f"P2 config not found: {P2_CONFIG}")
    else:
        info["config"] = str(P2_CONFIG)

    # Check pretrained weights
    pretrained = Path(args.pretrained)
    if not pretrained.exists():
        issues.append(f"Pretrained weights not found: {pretrained}")
    else:
        info["pretrained"] = str(pretrained)
        info["pretrained_size_mb"] = pretrained.stat().st_size / 1e6

    # Check dataset
    data_yaml = Path(DATASET_DIR) / "data.yaml"
    if not data_yaml.exists():
        issues.append(f"Dataset config not found: {data_yaml}")
    else:
        info["dataset"] = str(data_yaml)

    train_dir = Path(DATASET_DIR) / "images" / "train"
    val_dir = Path(DATASET_DIR) / "images" / "val"
    if train_dir.exists():
        info["train_images"] = len(list(train_dir.glob("*")))
    else:
        issues.append(f"Training images not found: {train_dir}")

    if val_dir.exists():
        info["val_images"] = len(list(val_dir.glob("*")))
    else:
        issues.append(f"Validation images not found: {val_dir}")

    # Check GPU
    if torch.cuda.is_available():
        info["gpu"] = torch.cuda.get_device_name(args.device)
        free_mem, total_mem = torch.cuda.mem_get_info(args.device)
        info["gpu_free_gb"] = free_mem / 1e9
        info["gpu_total_gb"] = total_mem / 1e9
        if free_mem / 1e9 < 14:
            issues.append(
                f"GPU {args.device} has only {free_mem/1e9:.1f}GB free — "
                f"need ~16GB for 960px P2 training. Was GPU yield successful?"
            )
    else:
        issues.append("No CUDA GPU available")

    # Check output dir
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    info["output_dir"] = str(CHECKPOINT_DIR)

    if issues:
        print("╔═══════════════ PRE-FLIGHT ISSUES ═══════════════╗")
        for issue in issues:
            print(f"  ✗ {issue}")
        print("╚═════════════════════════════════════════════════╝")

    return {"issues": issues, "info": info}


def estimate_batch_size(device: int, imgsz: int) -> int:
    """Estimate max batch size for P2 training on given GPU.

    P2 head adds ~30% activation memory over standard P3-P5 YOLOv8L.
    With rect=True (~10-15% savings) and amp=True (~30% savings),
    the practical limits on a 24GB GPU are:
      - 1280px: batch=1-2 (tight, OOM risk)
      - 960px:  batch=2-4 (comfortable)
      - 640px:  batch=8-16
    """
    if not torch.cuda.is_available():
        return 1

    free_mem, _ = torch.cuda.mem_get_info(device)
    free_gb = free_mem / 1e9

    # P2 stride-4 creates 4x feature maps vs stride-8
    # Memory estimates include P2 activation overhead
    if imgsz >= 1280:
        # ~20-22GB for batch=2, very tight on 24GB
        if free_gb >= 22:
            return 2
        else:
            return 1
    elif imgsz >= 960:
        # ~14-16GB for batch=2, ~18-20GB for batch=4
        if free_gb >= 22:
            return 4
        elif free_gb >= 16:
            return 2
        else:
            return 1
    elif imgsz >= 640:
        if free_gb >= 22:
            return 16
        elif free_gb >= 14:
            return 8
        else:
            return 4
    return 2


def train(args: argparse.Namespace) -> Optional[dict]:
    """Execute Phase 6B YOLOv8L-P2 training."""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_name = args.name or f"phase6b_yolov8l_p2_{timestamp}"
    nessie_branch = f"phase6b/{run_name}"

    print(f"\n{'═' * 70}")
    print(f"  Phase 6B — YOLOv8L-P2 Face Detection Training")
    print(f"  Run: {run_name}")
    print(f"  Config: {P2_CONFIG}")
    print(f"  Pretrained: {args.pretrained}")
    print(f"  Image Size: {args.imgsz}px")
    print(f"  Epochs: {args.epochs}")
    print(f"  Batch Size: {args.batch_size}")
    print(f"  Device: GPU {args.device}")
    print(f"{'═' * 70}\n")

    # ── Pre-flight ──
    preflight = validate_environment(args)
    if preflight["issues"]:
        if args.dry_run:
            print("\n[dry-run] Pre-flight issues found. Fix before training.")
            return None
        print("\n⚠ Pre-flight issues detected — attempting to proceed anyway")

    info = preflight["info"]
    print(
        f"[data] train={info.get('train_images', '?')} val={info.get('val_images', '?')}"
    )
    print(
        f"[gpu] {info.get('gpu', 'N/A')} — {info.get('gpu_free_gb', 0):.1f}/{info.get('gpu_total_gb', 0):.1f} GB free"
    )

    if args.dry_run:
        print("\n[dry-run] Config validated. Ready to train.")
        print(f"  Estimated batch size: {estimate_batch_size(args.device, args.imgsz)}")
        return None

    # ── Auto-adjust batch size if needed ──
    recommended_batch = estimate_batch_size(args.device, args.imgsz)
    if args.batch_size > recommended_batch:
        print(
            f"[auto] Reducing batch {args.batch_size} → {recommended_batch} (GPU memory)"
        )
        args.batch_size = recommended_batch

    # ── Initialize integrations ──
    metrics_pusher = TrainingMetrics(job_name=f"phase6b_{run_name}")
    nessie_create_branch(nessie_branch)

    # ── MLflow setup ──
    mlflow_run = None
    if MLFLOW_AVAILABLE:
        try:
            mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
            mlflow.set_experiment(MLFLOW_EXPERIMENT)
            mlflow_run = mlflow.start_run(run_name=run_name, tags=MLFLOW_TAGS)
            mlflow.log_params(
                {
                    "epochs": args.epochs,
                    "batch_size": args.batch_size,
                    "imgsz": args.imgsz,
                    "optimizer": args.optimizer,
                    "lr0": args.lr0,
                    "lrf": args.lrf,
                    "weight_decay": args.weight_decay,
                    "cos_lr": args.cos_lr,
                    "patience": args.patience,
                    "pretrained": args.pretrained,
                    "config": str(P2_CONFIG),
                    "model_architecture": "yolov8l-p2",
                    "detection_heads": "P2/4,P3/8,P4/16,P5/32",
                }
            )
            print(f"[mlflow] run started: {mlflow_run.info.run_id}")
        except Exception as e:
            print(f"[mlflow] setup error: {e}")

    # ── Build model ──
    print(f"\n[model] Loading YOLOv8L-P2 from config: {P2_CONFIG}")

    if args.resume:
        # Resume from last checkpoint
        last_ckpt = CHECKPOINT_DIR / run_name / "weights" / "last.pt"
        if last_ckpt.exists():
            print(f"[model] Resuming from {last_ckpt}")
            model = YOLO(str(last_ckpt))
        else:
            print(f"[model] No checkpoint found at {last_ckpt}, starting fresh")
            model = YOLO(str(P2_CONFIG))
    else:
        model = YOLO(str(P2_CONFIG))

    # Register callbacks
    callbacks = Phase6BCallbacks(metrics_pusher, run_name)
    callbacks.register(model)

    # ── Output directory ──
    project_dir = str(CHECKPOINT_DIR)
    run_dir = run_name

    # ── Training ──
    print(f"\n{'─' * 70}")
    print(f"  Starting training: {args.epochs} epochs @ {args.imgsz}px")
    print(
        f"  Batch: {args.batch_size} × grad_accum ≈ effective {args.batch_size * max(1, 16 // args.batch_size)}"
    )
    print(f"  Output: {project_dir}/{run_dir}/")
    print(f"{'─' * 70}\n")

    start_time = time.time()

    try:
        results = model.train(
            # Data
            data=f"{DATASET_DIR}/data.yaml",
            # Architecture
            imgsz=args.imgsz,
            # Training schedule
            epochs=args.epochs,
            batch=args.batch_size,
            patience=args.patience,
            # Optimizer
            optimizer=args.optimizer,
            lr0=args.lr0,
            lrf=args.lrf,
            weight_decay=args.weight_decay,
            cos_lr=args.cos_lr,
            warmup_epochs=5,
            warmup_bias_lr=0.1,
            warmup_momentum=0.8,
            # Augmentations — Phase 6B specific
            mosaic=1.0,
            mixup=0.15,
            copy_paste=0.3,  # Crowd scene synthesis (reduced for memory)
            degrees=10.0,
            translate=0.2,
            scale=0.9,
            fliplr=0.5,
            hsv_h=0.015,
            hsv_s=0.7,
            hsv_v=0.4,
            # Detection
            max_det=500,  # Crowd scenes (500 sufficient for WIDER)
            iou=0.7,  # Stricter NMS for crowded faces
            # Memory optimizations
            rect=True,  # Rectangular batches (~10-15% VRAM savings)
            cache="ram",  # Cache images in RAM (faster, avoids disk I/O)
            # Hardware
            device=args.device,
            workers=args.workers,
            amp=True,  # Mixed precision (~30% VRAM savings)
            # Output
            project=project_dir,
            name=run_dir,
            exist_ok=True,
            # Logging
            verbose=True,
            plots=True,
            save=True,
            save_period=10,  # Checkpoint every 10 epochs
            # Pretrained weights
            pretrained=args.pretrained if not args.resume else False,
        )

    except torch.cuda.OutOfMemoryError:
        print(f"\n{'!' * 70}")
        print(f"  OOM at batch_size={args.batch_size}, imgsz={args.imgsz}")
        print(f"{'!' * 70}\n")

        # Fully clear GPU before retry
        del model
        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
        time.sleep(3)

        if args.batch_size > 1:
            new_batch = max(1, args.batch_size // 2)
            print(f"  Retrying with batch_size={new_batch}...")
            model = YOLO(str(P2_CONFIG))
            callbacks.register(model)
            results = model.train(
                data=f"{DATASET_DIR}/data.yaml",
                imgsz=args.imgsz,
                epochs=args.epochs,
                batch=new_batch,
                patience=args.patience,
                optimizer=args.optimizer,
                lr0=args.lr0,
                lrf=args.lrf,
                weight_decay=args.weight_decay,
                cos_lr=args.cos_lr,
                warmup_epochs=5,
                mosaic=1.0,
                mixup=0.15,
                copy_paste=0.3,
                max_det=500,
                iou=0.7,
                rect=True,
                cache="ram",
                device=args.device,
                workers=args.workers,
                amp=True,
                project=project_dir,
                name=run_dir,
                exist_ok=True,
                verbose=True,
                plots=True,
                save=True,
                save_period=10,
                pretrained=args.pretrained if not args.resume else False,
            )
        else:
            print("FATAL: OOM even at batch_size=1. Try imgsz=960.")
            return None

    training_time = time.time() - start_time

    # ── Extract results ──
    result_metrics = {}
    if results:
        result_metrics = {
            "mAP50": float(results.results_dict.get("metrics/mAP50(B)", 0)),
            "mAP50_95": float(results.results_dict.get("metrics/mAP50-95(B)", 0)),
            "precision": float(results.results_dict.get("metrics/precision(B)", 0)),
            "recall": float(results.results_dict.get("metrics/recall(B)", 0)),
            "training_time_hours": training_time / 3600,
            "best_epoch": callbacks.best_epoch,
            "epochs_actual": args.epochs,
        }

    # ── Results summary ──
    print(f"\n{'═' * 70}")
    print(f"  Phase 6B Training Results")
    print(f"{'═' * 70}")
    print(f"  Model:     YOLOv8L-P2 @ {args.imgsz}px")
    print(f"  Time:      {training_time/3600:.1f}h ({training_time/60:.0f}min)")
    print(f"  mAP50:     {result_metrics.get('mAP50', 0):.4f}")
    print(f"  mAP50-95:  {result_metrics.get('mAP50_95', 0):.4f}")
    print(f"  Precision: {result_metrics.get('precision', 0):.4f}")
    print(f"  Recall:    {result_metrics.get('recall', 0):.4f}")
    print(
        f"  Best:      epoch {callbacks.best_epoch} (mAP50={callbacks.best_map50:.4f})"
    )
    print()

    # Compare with baselines
    print("  vs Baselines:")
    p5_map50 = BASELINES["phase5_yolov8m_p2"]["mAP50"]
    current_map50 = result_metrics.get("mAP50", 0)
    delta = current_map50 - p5_map50
    print(
        f"    Phase 5 YOLOv8m-P2:  mAP50={p5_map50:.3f} → {current_map50:.3f} ({delta:+.3f})"
    )

    p6a_map = BASELINES["phase6a_yolov8l"]["mAP@50:95"]
    current_map = result_metrics.get("mAP50_95", 0)
    delta2 = current_map - p6a_map
    print(
        f"    Phase 6A YOLOv8L:    mAP@50:95={p6a_map:.4f} → {current_map:.4f} ({delta2:+.4f})"
    )

    # KPI check
    print()
    kpi_met = 0
    for kpi, target in KPI_TARGETS.items():
        val = result_metrics.get(kpi, 0)
        status = "✓" if val >= target else "✗"
        if val >= target:
            kpi_met += 1
        print(f"    [{status}] {kpi}: {val:.3f} (target: {target:.3f})")
    print(f"    KPI: {kpi_met}/{len(KPI_TARGETS)} met")
    print(f"{'═' * 70}\n")

    # ── Log final metrics to MLflow ──
    if MLFLOW_AVAILABLE and mlflow.active_run():
        try:
            mlflow.log_metrics(
                {
                    f"final_{k}": v
                    for k, v in result_metrics.items()
                    if isinstance(v, (int, float))
                }
            )

            # Log best weights as artifact
            best_weights = Path(project_dir) / run_dir / "weights" / "best.pt"
            if best_weights.exists():
                mlflow.log_artifact(str(best_weights), "weights")

            # Log training plots
            plots_dir = Path(project_dir) / run_dir
            for plot_file in plots_dir.glob("*.png"):
                mlflow.log_artifact(str(plot_file), "plots")

            mlflow.end_run()
            print(f"[mlflow] run logged successfully")
        except Exception as e:
            print(f"[mlflow] finalization error: {e}")
            try:
                mlflow.end_run()
            except Exception:
                pass

    # ── Nessie tag ──
    if result_metrics.get("mAP50", 0) > 0.5:
        tag_name = f"phase6b-best-{timestamp}"
        nessie_tag_model(nessie_branch, tag_name, result_metrics)

    # ── Save metadata ──
    meta_path = Path(project_dir) / run_dir / "training_metadata.json"
    metadata = {
        "phase": "6B",
        "model": "yolov8l-p2",
        "config": str(P2_CONFIG),
        "pretrained": args.pretrained,
        "imgsz": args.imgsz,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "optimizer": args.optimizer,
        "augmentations": {
            "copy_paste": 0.3,
            "mosaic": 1.0,
            "mixup": 0.15,
            "max_det": 500,
            "iou": 0.7,
            "rect": True,
            "cache": "ram",
        },
        "results": result_metrics,
        "baselines": BASELINES,
        "kpis_met": kpi_met,
        "timestamp": timestamp,
        "training_time_hours": training_time / 3600,
        "gpu": info.get("gpu", "unknown"),
        "gpu_yielded": _gpu_yielded,
    }
    try:
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        with open(meta_path, "w") as f:
            json.dump(metadata, f, indent=2)
        print(f"[meta] Saved: {meta_path}")
    except Exception as e:
        print(f"[meta] Save error: {e}")

    return result_metrics


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════


def main():
    args = parse_args()

    print(f"╔════════════════════════════════════════════════════════════════╗")
    print(f"║  Phase 6B — YOLOv8L-P2 Face Detection Training              ║")
    print(
        f"║  GPU Yield: {'YES' if _gpu_yielded else 'NO (manual yield may be needed)':42s} ║"
    )
    print(f"╚════════════════════════════════════════════════════════════════╝")

    try:
        results = train(args)
    except KeyboardInterrupt:
        print("\n\n⚠ Training interrupted by user")
        results = None
    except Exception as e:
        print(f"\n\n✗ Training failed: {e}")
        import traceback

        traceback.print_exc()
        results = None
    finally:
        # ALWAYS reclaim GPU for inference services
        try:
            reclaim_gpu_after_training(gpu_id=0, job_id=_job_id)
        except Exception as e:
            print(f"[gpu] Reclaim error: {e}")

    if results:
        best_weights = (
            CHECKPOINT_DIR
            / f"phase6b_yolov8l_p2_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            / "weights"
            / "best.pt"
        )
        print(f"\n[next] Phase 6C: Benchmark with face_detection_benchmark.py")
        print(
            f"[next] Best weights should be at: {CHECKPOINT_DIR}/phase6b_*/weights/best.pt"
        )

    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
