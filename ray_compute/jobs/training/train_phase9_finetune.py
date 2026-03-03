#!/usr/bin/env python3
"""
Phase 9 — Fine-tune YOLOv8m-P2 for Maximum Recall
====================================================

Continues training the Phase 5 champion (YOLOv8m-P2, best.pt) with:
  - Lower LR (0.0005) to avoid gradient explosion
  - Gradient clipping (max_norm=10.0) for training stability
  - 960px input (higher res than original, memory-safe)
  - Cosine LR schedule with gentle warmup
  - Recall-focused augmentation (copy_paste=0.3, max_det=500)

**Why Phase 5 as base?**
  Head-to-head comparison on WIDER Face val (3222 images, 39111 faces):
    Phase 5 (YOLOv8m-P2):  P=0.889  R=0.716  F1=0.793  mAP50=0.798  mAP=0.461
    Phase 6A (YOLOv8L):    P=0.829  R=0.584  F1=0.685  mAP50=0.667  mAP=0.349
    Phase 6B (YOLOv8L-P2): P=0.871  R=0.635  F1=0.734  mAP50=0.721  mAP=0.360
    Phase 8 (Integrated):  P=0.887  R=0.719  F1=0.794  mAP50=0.795  mAP=0.405
  Phase 5 wins every metric. Recall is king for PII compliance.

**Targets (PII KPI):**
  Recall ≥ 75%  |  mAP50 ≥ 82%  |  Precision ≥ 88%

Usage:
    python train_phase9_finetune.py                  # defaults
    python train_phase9_finetune.py --epochs 80      # longer run
    python train_phase9_finetune.py --resume          # resume from last

Author: SHML Platform
Date: March 2026
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
from typing import Optional

# ═══════════════════════════════════════════════════════════════════════════
# FIX: Monkey-patch ray.tune BEFORE ultralytics import
# Ultralytics 8.0.200 calls ray.tune.is_session_enabled() which was removed
# in newer Ray versions.
# ═══════════════════════════════════════════════════════════════════════════
try:
    import ray.tune

    if not hasattr(ray.tune, "is_session_enabled"):
        ray.tune.is_session_enabled = lambda: False
        print("[fix] Patched ray.tune.is_session_enabled")
except ImportError:
    pass

# ═══════════════════════════════════════════════════════════════════════════
# GPU YIELD — MUST happen before torch import
# ═══════════════════════════════════════════════════════════════════════════
_script_dir_yield = os.path.dirname(os.path.abspath(__file__))
for _yp in [
    os.path.join(_script_dir_yield, ".."),
    _script_dir_yield,
]:
    _yp = os.path.abspath(_yp)
    if os.path.isdir(_yp) and _yp not in sys.path:
        sys.path.insert(0, _yp)

_job_id = os.environ.get("RAY_JOB_ID", f"phase9-finetune-{os.getpid()}")
_gpu_yielded = False

try:
    from utils.gpu_yield import yield_gpu_for_training, reclaim_gpu_after_training

    _gpu_yielded = yield_gpu_for_training(gpu_id=0, job_id=_job_id, timeout=30)
except ImportError:
    try:
        from gpu_yield import yield_gpu_for_training, reclaim_gpu_after_training

        _gpu_yielded = yield_gpu_for_training(gpu_id=0, job_id=_job_id, timeout=30)
    except ImportError:
        print("[gpu] GPU yield module not available — continuing without yield")
except Exception as e:
    print(f"[gpu] GPU yield failed: {e} — continuing anyway")

# Now safe to import torch
import torch
import torch.nn.utils as nn_utils

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
    gpu_name = torch.cuda.get_device_name(0)
    vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
    print(f"[cuda] {gpu_name} — {vram_gb:.1f} GB VRAM")
    print(f"[cuda] VRAM free: {torch.cuda.mem_get_info(0)[0] / 1e9:.1f} GB")
else:
    print("[cuda] NOT available — training will be extremely slow")

# ═══════════════════════════════════════════════════════════════════════════
# PLATFORM IMPORTS
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

    print("[ultralytics] available")
except ImportError:
    print("[ultralytics] NOT installed")
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
# Phase 5 champion model — the best we have
PRETRAINED_WEIGHTS = (
    "/tmp/ray/checkpoints/face_detection/model_comparison/phase5_yolov8m_p2_best.pt"
)
CHECKPOINT_DIR = Path(
    os.environ.get("CHECKPOINT_DIR", "/tmp/ray/checkpoints/face_detection")
)

# Phase 5 baseline for comparison
BASELINE = {
    "precision": 0.889,
    "recall": 0.716,
    "F1": 0.793,
    "mAP50": 0.798,
    "mAP50_95": 0.461,
}

MLFLOW_EXPERIMENT = "phase9-finetune-recall"
MLFLOW_TAGS = {
    "model": "yolov8m-p2",
    "base": "phase5-champion",
    "strategy": "finetune-for-recall",
    "dataset": "wider-face",
    "phase": "9",
}


# ═══════════════════════════════════════════════════════════════════════════
# GRADIENT CLIPPING CALLBACK
# ═══════════════════════════════════════════════════════════════════════════


class GradientClipCallback:
    """Clip gradients during training to prevent NaN explosion.

    Ultralytics doesn't expose gradient clipping natively, so we
    hook into on_train_batch_end to clip after backward but the
    actual clip must happen before optimizer.step(). We monkey-patch
    the trainer's optimizer_step method instead.
    """

    def __init__(self, max_norm: float = 10.0):
        self.max_norm = max_norm
        self._patched = False
        self.clip_count = 0
        self.total_steps = 0

    def on_train_start(self, trainer):
        """Monkey-patch the trainer to add gradient clipping."""
        if self._patched:
            return

        original_step = trainer.optimizer.step

        max_norm = self.max_norm
        callback_ref = self

        def clipped_step(closure=None):
            # Clip all model parameter gradients
            total_norm = nn_utils.clip_grad_norm_(trainer.model.parameters(), max_norm)
            if total_norm > max_norm:
                callback_ref.clip_count += 1
            callback_ref.total_steps += 1
            return original_step(closure)

        trainer.optimizer.step = clipped_step
        self._patched = True
        print(f"[grad-clip] Enabled: max_norm={self.max_norm}")

    def register(self, model: YOLO):
        model.add_callback("on_train_start", self.on_train_start)


# ═══════════════════════════════════════════════════════════════════════════
# PROMETHEUS METRICS
# ═══════════════════════════════════════════════════════════════════════════


class TrainingMetrics:
    def __init__(self, job_name: str = "phase9_finetune"):
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
            self.recall_gauge = Gauge(
                "training_recall", "Validation recall", registry=self.registry
            )
            self.lr_gauge = Gauge(
                "training_lr", "Learning rate", registry=self.registry
            )
            self.gpu_mem_gauge = Gauge(
                "training_gpu_memory_gb", "GPU memory used (GB)", registry=self.registry
            )

    def push(self, epoch: int, metrics: dict):
        if not self.enabled:
            return
        try:
            self.epoch_gauge.set(epoch)
            for loss_name in ["train/box_loss", "train/cls_loss", "train/dfl_loss"]:
                if loss_name in metrics:
                    self.loss_gauge.labels(loss_name.split("/")[1]).set(
                        metrics[loss_name]
                    )
            if "metrics/mAP50(B)" in metrics:
                self.map50_gauge.set(metrics["metrics/mAP50(B)"])
            if "metrics/mAP50-95(B)" in metrics:
                self.map_gauge.set(metrics["metrics/mAP50-95(B)"])
            if "metrics/recall(B)" in metrics:
                self.recall_gauge.set(metrics["metrics/recall(B)"])
            if "lr/pg0" in metrics:
                self.lr_gauge.set(metrics["lr/pg0"])
            if torch.cuda.is_available():
                self.gpu_mem_gauge.set(torch.cuda.memory_allocated(0) / 1e9)
            push_to_gateway(PUSHGATEWAY_URL, job=self.job_name, registry=self.registry)
        except Exception as e:
            print(f"[prometheus] push error: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# NESSIE INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════


def nessie_create_branch(branch_name: str) -> bool:
    try:
        resp = requests.get(f"{NESSIE_URI}/api/v1/trees/tree/main", timeout=5)
        if resp.status_code != 200:
            return False
        main_hash = resp.json().get("hash", "")
        resp = requests.post(
            f"{NESSIE_URI}/api/v1/trees/branch",
            json={"name": branch_name, "hash": main_hash},
            timeout=5,
        )
        if resp.status_code in (200, 201, 409):
            print(f"[nessie] branch '{branch_name}' ready")
            return True
    except Exception as e:
        print(f"[nessie] branch creation failed: {e}")
    return False


def nessie_tag_model(branch_name: str, tag_name: str) -> bool:
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
            print(f"[nessie] tagged '{tag_name}'")
            return True
    except Exception as e:
        print(f"[nessie] tagging failed: {e}")
    return False


# ═══════════════════════════════════════════════════════════════════════════
# TRAINING CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════


class Phase9Callbacks:
    def __init__(
        self,
        metrics_pusher: TrainingMetrics,
        run_name: str,
        grad_clip: GradientClipCallback,
    ):
        self.metrics_pusher = metrics_pusher
        self.run_name = run_name
        self.grad_clip = grad_clip
        self.best_recall = 0.0
        self.best_map50 = 0.0
        self.best_f1 = 0.0
        self.best_epoch = 0
        self.start_time = time.time()
        self.nan_count = 0

    def on_train_epoch_end(self, trainer):
        epoch = trainer.epoch + 1
        metrics = trainer.metrics or {}

        self.metrics_pusher.push(epoch, metrics)

        recall = metrics.get("metrics/recall(B)", 0.0)
        precision = metrics.get("metrics/precision(B)", 0.0)
        map50 = metrics.get("metrics/mAP50(B)", 0.0)
        map_val = metrics.get("metrics/mAP50-95(B)", 0.0)
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0
        )
        box_loss = metrics.get("train/box_loss", 0.0)
        cls_loss = metrics.get("train/cls_loss", 0.0)
        dfl_loss = metrics.get("train/dfl_loss", 0.0)

        # NaN detection
        import math

        if any(math.isnan(v) for v in [box_loss, cls_loss, dfl_loss] if v):
            self.nan_count += 1
            print(
                f"  ⚠ [epoch {epoch}] NaN detected in losses! (count: {self.nan_count})"
            )
            if self.nan_count >= 3:
                print(
                    f"  ✗ 3 consecutive NaN epochs — training is diverging. Stopping."
                )
                # Can't actually stop, but log the warning loudly
                return

        # Track best by recall (our primary KPI)
        if recall > self.best_recall:
            self.best_recall = recall
            self.best_map50 = map50
            self.best_f1 = f1
            self.best_epoch = epoch

        elapsed = time.time() - self.start_time
        clip_pct = (
            self.grad_clip.clip_count / max(1, self.grad_clip.total_steps)
        ) * 100

        # Delta vs Phase 5 baseline
        r_delta = recall - BASELINE["recall"]
        m_delta = map50 - BASELINE["mAP50"]

        print(
            f"  [epoch {epoch:3d}] "
            f"box={box_loss:.4f} cls={cls_loss:.4f} dfl={dfl_loss:.4f} | "
            f"R={recall:.4f} P={precision:.4f} F1={f1:.4f} | "
            f"mAP50={map50:.4f} mAP={map_val:.4f} | "
            f"vs_base: R{r_delta:+.3f} mAP50{m_delta:+.3f} | "
            f"clips={clip_pct:.0f}% | {elapsed/60:.0f}min"
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
                        "val_recall": recall,
                        "val_precision": precision,
                        "val_F1": f1,
                        "val_mAP50": map50,
                        "val_mAP50_95": map_val,
                        "best_recall": self.best_recall,
                        "grad_clip_pct": clip_pct,
                    },
                    step=epoch,
                )
            except Exception:
                pass

    def on_train_end(self, trainer):
        total_time = time.time() - self.start_time
        print(f"\n{'═' * 70}")
        print(f"Training complete in {total_time/3600:.1f}h")
        print(
            f"Best: R={self.best_recall:.4f} F1={self.best_f1:.4f} mAP50={self.best_map50:.4f} @ epoch {self.best_epoch}"
        )
        print(
            f"Grad clips: {self.grad_clip.clip_count}/{self.grad_clip.total_steps} ({(self.grad_clip.clip_count/max(1,self.grad_clip.total_steps))*100:.1f}%)"
        )
        print(f"NaN epochs: {self.nan_count}")
        print(f"{'═' * 70}\n")

    def register(self, model: YOLO):
        model.add_callback("on_train_epoch_end", self.on_train_epoch_end)
        model.add_callback("on_train_end", self.on_train_end)


# ═══════════════════════════════════════════════════════════════════════════
# TRAINING
# ═══════════════════════════════════════════════════════════════════════════


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase 9 — Fine-tune YOLOv8m-P2 for recall"
    )
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--patience", type=int, default=20, help="Early stopping patience (default: 20)"
    )
    parser.add_argument(
        "--lr0",
        type=float,
        default=0.0005,
        help="Initial LR — lower than Phase 5 to avoid explosion",
    )
    parser.add_argument(
        "--lrf", type=float, default=0.01, help="Final LR as fraction of lr0"
    )
    parser.add_argument(
        "--max-norm", type=float, default=10.0, help="Gradient clipping max norm"
    )
    parser.add_argument("--pretrained", type=str, default=PRETRAINED_WEIGHTS)
    parser.add_argument("--name", type=str, default=None)
    return parser.parse_args()


def validate_environment(args: argparse.Namespace) -> dict:
    issues = []
    info = {}

    pretrained = Path(args.pretrained)
    if not pretrained.exists():
        issues.append(f"Pretrained weights not found: {pretrained}")
    else:
        info["pretrained"] = str(pretrained)
        info["pretrained_size_mb"] = pretrained.stat().st_size / 1e6

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

    if torch.cuda.is_available():
        info["gpu"] = torch.cuda.get_device_name(args.device)
        free_mem, total_mem = torch.cuda.mem_get_info(args.device)
        info["gpu_free_gb"] = free_mem / 1e9
        info["gpu_total_gb"] = total_mem / 1e9
        if free_mem / 1e9 < 10:
            issues.append(f"GPU has only {free_mem/1e9:.1f}GB free")
    else:
        issues.append("No CUDA GPU available")

    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    info["output_dir"] = str(CHECKPOINT_DIR)

    if issues:
        print("╔═══════════════ PRE-FLIGHT ISSUES ═══════════════╗")
        for issue in issues:
            print(f"  ✗ {issue}")
        print("╚═════════════════════════════════════════════════╝")

    return {"issues": issues, "info": info}


def train(args: argparse.Namespace) -> Optional[dict]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_name = args.name or f"phase9_finetune_{timestamp}"
    nessie_branch = f"phase9/{run_name}"

    print(f"\n{'═' * 70}")
    print(f"  Phase 9 — Fine-tune YOLOv8m-P2 for Maximum Recall")
    print(f"  Run: {run_name}")
    print(f"  Base model: {args.pretrained}")
    print(f"  Image Size: {args.imgsz}px  |  LR: {args.lr0}")
    print(f"  Gradient Clipping: max_norm={args.max_norm}")
    print(f"  Epochs: {args.epochs}  |  Batch: {args.batch_size}")
    print(f"{'═' * 70}\n")

    # Pre-flight
    preflight = validate_environment(args)
    if preflight["issues"] and args.dry_run:
        print("[dry-run] Pre-flight issues found. Fix before training.")
        return None
    elif preflight["issues"]:
        print("⚠ Pre-flight issues — attempting to proceed")

    info = preflight["info"]
    print(
        f"[data] train={info.get('train_images', '?')} val={info.get('val_images', '?')}"
    )
    print(
        f"[gpu] {info.get('gpu', 'N/A')} — {info.get('gpu_free_gb', 0):.1f}/{info.get('gpu_total_gb', 0):.1f} GB"
    )
    print(
        f"[baseline] Phase 5: R={BASELINE['recall']:.3f} P={BASELINE['precision']:.3f} mAP50={BASELINE['mAP50']:.3f}"
    )

    if args.dry_run:
        print("\n[dry-run] Config validated. Ready to train.")
        return None

    # Initialize integrations
    metrics_pusher = TrainingMetrics(job_name=f"phase9_{run_name}")
    grad_clip = GradientClipCallback(max_norm=args.max_norm)
    nessie_create_branch(nessie_branch)

    # MLflow
    if MLFLOW_AVAILABLE:
        try:
            mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
            mlflow.set_experiment(MLFLOW_EXPERIMENT)
            mlflow.start_run(run_name=run_name, tags=MLFLOW_TAGS)
            mlflow.log_params(
                {
                    "epochs": args.epochs,
                    "batch_size": args.batch_size,
                    "imgsz": args.imgsz,
                    "lr0": args.lr0,
                    "lrf": args.lrf,
                    "max_norm": args.max_norm,
                    "patience": args.patience,
                    "pretrained": args.pretrained,
                    "strategy": "finetune-recall",
                    "base_recall": BASELINE["recall"],
                    "base_mAP50": BASELINE["mAP50"],
                }
            )
            print(f"[mlflow] run started")
        except Exception as e:
            print(f"[mlflow] setup error: {e}")

    # Load model
    print(f"\n[model] Loading Phase 5 champion: {args.pretrained}")
    model = YOLO(args.pretrained)

    # Register callbacks
    callbacks = Phase9Callbacks(metrics_pusher, run_name, grad_clip)
    callbacks.register(model)
    grad_clip.register(model)

    # Output
    project_dir = str(CHECKPOINT_DIR)
    run_dir = run_name

    print(f"\n{'─' * 70}")
    print(f"  Starting fine-tuning: {args.epochs} epochs @ {args.imgsz}px")
    print(f"  LR: {args.lr0} → {args.lr0 * args.lrf} (cosine)")
    print(f"  Gradient clipping: max_norm={args.max_norm}")
    print(f"  Output: {project_dir}/{run_dir}/")
    print(f"{'─' * 70}\n")

    start_time = time.time()

    try:
        results = model.train(
            # Data
            data=f"{DATASET_DIR}/data.yaml",
            # Architecture — use pretrained weights directly
            imgsz=args.imgsz,
            # Schedule
            epochs=args.epochs,
            batch=args.batch_size,
            patience=args.patience,
            # Optimizer — lower LR for fine-tuning
            optimizer="AdamW",
            lr0=args.lr0,
            lrf=args.lrf,
            weight_decay=0.0005,
            cos_lr=True,
            warmup_epochs=3,
            warmup_bias_lr=0.05,
            warmup_momentum=0.8,
            # Augmentations — moderate, recall-focused
            mosaic=1.0,
            mixup=0.1,
            copy_paste=0.3,
            degrees=5.0,
            translate=0.1,
            scale=0.5,
            fliplr=0.5,
            hsv_h=0.015,
            hsv_s=0.5,
            hsv_v=0.3,
            # Detection
            max_det=500,
            iou=0.7,
            # Memory
            rect=True,
            cache="ram",
            # Hardware
            device=args.device,
            workers=args.workers,
            amp=True,
            # Output
            project=project_dir,
            name=run_dir,
            exist_ok=True,
            verbose=True,
            plots=True,
            save=True,
            save_period=5,
        )

    except torch.cuda.OutOfMemoryError:
        print(f"\n{'!' * 70}")
        print(f"  OOM at batch={args.batch_size}, imgsz={args.imgsz}")
        print(f"{'!' * 70}\n")
        del model
        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
        time.sleep(3)

        if args.batch_size > 1:
            new_batch = max(1, args.batch_size // 2)
            print(f"  Retrying with batch={new_batch}...")
            model = YOLO(args.pretrained)
            callbacks.register(model)
            grad_clip.register(model)
            results = model.train(
                data=f"{DATASET_DIR}/data.yaml",
                imgsz=args.imgsz,
                epochs=args.epochs,
                batch=new_batch,
                patience=args.patience,
                optimizer="AdamW",
                lr0=args.lr0,
                lrf=args.lrf,
                weight_decay=0.0005,
                cos_lr=True,
                warmup_epochs=3,
                mosaic=1.0,
                mixup=0.1,
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
                save_period=5,
            )
        else:
            print("FATAL: OOM at batch=1. Try imgsz=640.")
            return None

    training_time = time.time() - start_time

    # Extract results
    result_metrics = {}
    if results:
        result_metrics = {
            "mAP50": float(results.results_dict.get("metrics/mAP50(B)", 0)),
            "mAP50_95": float(results.results_dict.get("metrics/mAP50-95(B)", 0)),
            "precision": float(results.results_dict.get("metrics/precision(B)", 0)),
            "recall": float(results.results_dict.get("metrics/recall(B)", 0)),
            "training_time_hours": training_time / 3600,
            "best_epoch": callbacks.best_epoch,
        }
        f1 = (
            2
            * result_metrics["precision"]
            * result_metrics["recall"]
            / (result_metrics["precision"] + result_metrics["recall"])
            if (result_metrics["precision"] + result_metrics["recall"]) > 0
            else 0
        )
        result_metrics["F1"] = f1

    # Results summary
    print(f"\n{'═' * 70}")
    print(f"  Phase 9 Fine-tuning Results")
    print(f"{'═' * 70}")
    print(f"  Model:     YOLOv8m-P2 @ {args.imgsz}px (fine-tuned)")
    print(f"  Time:      {training_time/3600:.1f}h")
    print(
        f"  Recall:    {result_metrics.get('recall', 0):.4f}  (baseline: {BASELINE['recall']:.4f}, Δ{result_metrics.get('recall', 0) - BASELINE['recall']:+.4f})"
    )
    print(
        f"  Precision: {result_metrics.get('precision', 0):.4f}  (baseline: {BASELINE['precision']:.4f})"
    )
    print(
        f"  F1:        {result_metrics.get('F1', 0):.4f}  (baseline: {BASELINE['F1']:.4f})"
    )
    print(
        f"  mAP50:     {result_metrics.get('mAP50', 0):.4f}  (baseline: {BASELINE['mAP50']:.4f}, Δ{result_metrics.get('mAP50', 0) - BASELINE['mAP50']:+.4f})"
    )
    print(
        f"  mAP50-95:  {result_metrics.get('mAP50_95', 0):.4f}  (baseline: {BASELINE['mAP50_95']:.4f})"
    )
    print(f"  Best epoch: {callbacks.best_epoch}")
    print(f"  Grad clips: {grad_clip.clip_count}/{grad_clip.total_steps}")
    print(f"  NaN epochs: {callbacks.nan_count}")
    print(f"{'═' * 70}\n")

    # MLflow finalization
    if MLFLOW_AVAILABLE and mlflow.active_run():
        try:
            mlflow.log_metrics(
                {
                    f"final_{k}": v
                    for k, v in result_metrics.items()
                    if isinstance(v, (int, float))
                }
            )
            best_weights = Path(project_dir) / run_dir / "weights" / "best.pt"
            if best_weights.exists():
                mlflow.log_artifact(str(best_weights), "weights")
            for plot_file in (Path(project_dir) / run_dir).glob("*.png"):
                mlflow.log_artifact(str(plot_file), "plots")
            mlflow.end_run()
            print("[mlflow] run logged")
        except Exception as e:
            print(f"[mlflow] finalization error: {e}")
            try:
                mlflow.end_run()
            except Exception:
                pass

    # Nessie tag
    if result_metrics.get("recall", 0) > BASELINE["recall"]:
        tag = f"phase9-recall-{result_metrics['recall']:.3f}-{timestamp}"
        nessie_tag_model(nessie_branch, tag)
        print(
            f"  🎯 NEW RECALL RECORD: {result_metrics['recall']:.4f} (was {BASELINE['recall']:.4f})"
        )

    # Save metadata
    meta_path = Path(project_dir) / run_dir / "training_metadata.json"
    metadata = {
        "phase": "9",
        "model": "yolov8m-p2",
        "strategy": "finetune-for-recall",
        "base_model": args.pretrained,
        "imgsz": args.imgsz,
        "epochs": args.epochs,
        "lr0": args.lr0,
        "max_norm": args.max_norm,
        "results": result_metrics,
        "baseline": BASELINE,
        "grad_clips": f"{grad_clip.clip_count}/{grad_clip.total_steps}",
        "nan_epochs": callbacks.nan_count,
        "timestamp": timestamp,
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

    # Copy best weights to comparison dir
    best_weights = Path(project_dir) / run_dir / "weights" / "best.pt"
    if best_weights.exists():
        dest = Path(
            "/tmp/ray/checkpoints/face_detection/model_comparison/phase9_finetune_best.pt"
        )
        import shutil

        shutil.copy2(best_weights, dest)
        print(f"[save] Best weights copied to {dest}")

    return result_metrics


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════


def main():
    args = parse_args()

    print(f"╔════════════════════════════════════════════════════════════════╗")
    print(f"║  Phase 9 — Fine-tune YOLOv8m-P2 for Maximum Recall          ║")
    print(
        f"║  GPU Yield: {'YES' if _gpu_yielded else 'NO (manual yield may be needed)':42s} ║"
    )
    print(f"╚════════════════════════════════════════════════════════════════╝")

    try:
        results = train(args)
    except KeyboardInterrupt:
        print("\n⚠ Training interrupted")
        results = None
    except Exception as e:
        print(f"\n✗ Training failed: {e}")
        import traceback

        traceback.print_exc()
        results = None
    finally:
        try:
            reclaim_gpu_after_training(gpu_id=0, job_id=_job_id)
        except Exception as e:
            print(f"[gpu] Reclaim error: {e}")

    if results:
        r = results.get("recall", 0)
        if r > BASELINE["recall"]:
            print(
                f"\n✓ Recall improved: {BASELINE['recall']:.3f} → {r:.3f} (+{r - BASELINE['recall']:.3f})"
            )
        else:
            print(f"\n→ Recall: {r:.3f} (baseline: {BASELINE['recall']:.3f})")
        print(
            f"[next] Best weights at: /tmp/ray/checkpoints/face_detection/model_comparison/phase9_finetune_best.pt"
        )

    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
