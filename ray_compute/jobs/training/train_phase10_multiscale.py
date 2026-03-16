#!/usr/bin/env python3
"""
Phase 10 — Multi-Scale Progressive Training for Maximum Recall
================================================================

Full research push to improve Phase 9 champion (R=0.729, P=0.883, mAP50=0.814).
Uses expanded multi-source dataset (WIDER + CrowdHuman + MAFA) with:

  - **Multi-scale progressive training**: 640→960→1280 px
  - **Recall-tuned loss weights**: box=10.0, cls=0.3, dfl=2.0
  - **Gradient accumulation**: nbs=64 (effective batch 64)
  - **Gradient clipping**: max_norm=10.0 (proven NaN prevention)
  - **close_mosaic=15**: disable mosaic for last 15 epochs
  - **scale=0.9**: aggressive scale variation for small faces
  - **Loss weights**: box=10.0, cls=0.3, dfl=2.0 (localization-focused for recall)
  - **label_smoothing=0.1**: better generalization
  - **max_det=1500**: more detections for crowd scenes

Target: R>0.80, P>0.85 on WIDER Face val

Usage:
    python train_phase10_multiscale.py                     # Full 3-phase training
    python train_phase10_multiscale.py --phase 2           # Start at phase 2 (960px)
    python train_phase10_multiscale.py --dry-run            # Validate config
    python train_phase10_multiscale.py --single-scale 960   # Fixed scale (no progressive)

Author: SHML Platform
Date: March 2026
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# NOTE: ray.tune.is_session_enabled monkey-patch removed — fixed in Ultralytics 8.3.50+
# (uses ray.train._internal.session._get_session() instead)

# ═══════════════════════════════════════════════════════════════════════════
# GPU YIELD
# ═══════════════════════════════════════════════════════════════════════════
_script_dir_yield = os.path.dirname(os.path.abspath(__file__))
for _yp in [os.path.join(_script_dir_yield, ".."), _script_dir_yield]:
    _yp = os.path.abspath(_yp)
    if os.path.isdir(_yp) and _yp not in sys.path:
        sys.path.insert(0, _yp)

_job_id = os.environ.get("RAY_JOB_ID", f"phase10-{os.getpid()}")
_gpu_yielded = False

try:
    from utils.gpu_yield import yield_gpu_for_training, reclaim_gpu_after_training

    _gpu_yielded = yield_gpu_for_training(gpu_id=0, job_id=_job_id, timeout=30)
except ImportError:
    try:
        from gpu_yield import yield_gpu_for_training, reclaim_gpu_after_training

        _gpu_yielded = yield_gpu_for_training(gpu_id=0, job_id=_job_id, timeout=30)
    except ImportError:
        print("[gpu] GPU yield module not available")
except Exception as e:
    print(f"[gpu] GPU yield failed: {e}")

# Now safe to import torch
import torch
import torch.nn.utils as nn_utils

# ═══════════════════════════════════════════════════════════════════════════
# CUDA OPTIMIZATIONS
# ═══════════════════════════════════════════════════════════════════════════
os.environ.setdefault(
    "PYTORCH_CUDA_ALLOC_CONF",
    "expandable_segments:True,garbage_collection_threshold:0.7,max_split_size_mb:256",
)
# Limit CUDA memory to 90% to leave headroom and prevent system freezes
torch.cuda.set_per_process_memory_fraction(0.90, 0)

if torch.cuda.is_available():
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    torch.backends.cudnn.benchmark = True
    gpu_name = torch.cuda.get_device_name(0)
    vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
    print(f"[cuda] {gpu_name} — {vram_gb:.1f} GB VRAM")
    free_mem = torch.cuda.mem_get_info(0)[0] / 1e9
    print(f"[cuda] VRAM free: {free_mem:.1f} GB")
else:
    print("[cuda] NOT available")

# ═══════════════════════════════════════════════════════════════════════════
# IMPORTS
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

MIN_HOST_MEM_AVAILABLE_MB = int(os.environ.get("MIN_HOST_MEM_AVAILABLE_MB", "4096"))
MIN_HOST_SWAP_FREE_MB = int(os.environ.get("MIN_HOST_SWAP_FREE_MB", "1024"))
MAX_HOST_COMMIT_PCT = float(os.environ.get("MAX_HOST_COMMIT_PCT", "200"))
TRAINING_TELEMETRY_INTERVAL_SEC = int(
    os.environ.get("TRAINING_TELEMETRY_INTERVAL_SEC", "30")
)
TRAINING_TELEMETRY_LOG = os.environ.get(
    "TRAINING_TELEMETRY_LOG", "/tmp/ray/data/phase10_resource_telemetry.csv"
)
ENABLE_TRAINING_TELEMETRY = os.environ.get(
    "ENABLE_TRAINING_TELEMETRY", "1"
).strip().lower() not in {"0", "false", "no"}

# Dataset paths
WIDER_YOLO_DIR = "/tmp/ray/data/wider_face_yolo"  # Original WIDER-only
MERGED_YOLO_DIR = "/tmp/ray/data/face_merged_yolo"  # Merged multi-source
CHECKPOINT_DIR = Path(
    os.environ.get("CHECKPOINT_DIR", "/tmp/ray/checkpoints/face_detection")
)

# Phase 9 best weights — our starting point
PRETRAINED_WEIGHTS = (
    "/tmp/ray/checkpoints/face_detection/model_comparison/phase9_finetune_best.pt"
)

# Baselines for comparison
BASELINE_PHASE5 = {
    "precision": 0.889,
    "recall": 0.716,
    "F1": 0.793,
    "mAP50": 0.798,
    "mAP50_95": 0.461,
}
BASELINE_PHASE9 = {
    "precision": 0.883,
    "recall": 0.729,
    "F1": 0.797,
    "mAP50": 0.814,
    "mAP50_95": 0.441,
}

MLFLOW_EXPERIMENT = "phase10-multiscale-recall"

# ═══════════════════════════════════════════════════════════════════════════
# MULTI-SCALE PHASE DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════

TRAINING_PHASES = [
    {
        "name": "Phase A — Coarse Features",
        "imgsz": 640,
        "batch": 2,  # Sized for multi_scale worst-case: 960px@batch=2 ≈12GB (safe on 24GB)
        "epochs": 15,
        "description": "Learn basic face patterns with random multi-scale (320-960px)",
        # Use full augmentation suite, higher LR for initial adaptation
        "lr0": 0.0005,
        "lrf": 0.05,
        "warmup_epochs": 3,
        "patience": 15,
        # Augmentations
        "mosaic": 1.0,
        "mixup": 0.2,
        "copy_paste": 0.3,
        "scale": 0.9,
        "degrees": 5.0,
        "translate": 0.1,
        "fliplr": 0.5,
        "label_smoothing": 0.1,
        "close_mosaic": 0,  # Keep mosaic on for all of Phase A
        "hsv_h": 0.015,
        "hsv_s": 0.7,
        "hsv_v": 0.4,
        # Detection
        "max_det": 1500,
        "iou": 0.6,
        # Memory — no RAM cache to avoid system freezes
        "cache": False,
        "rect": True,
        # multi_scale=True: random 0.5x-1.5x per batch (key for scale-invariant recall)
        # At 640px, worst case is 960px@batch=2 ≈12GB — safe on 24GB VRAM
        "multi_scale": True,
    },
    {
        "name": "Phase B — Medium Details",
        "imgsz": 960,
        "batch": 2,  # Reduced from 4 — 960px at batch 4 risks OOM on 24GB
        "epochs": 20,
        "description": "Refine at standard resolution with moderate batch",
        "lr0": 0.0003,
        "lrf": 0.02,
        "warmup_epochs": 2,
        "patience": 15,
        # Augmentations — moderate
        "mosaic": 1.0,
        "mixup": 0.15,
        "copy_paste": 0.3,
        "scale": 0.7,
        "degrees": 3.0,
        "translate": 0.1,
        "fliplr": 0.5,
        "label_smoothing": 0.1,
        "close_mosaic": 5,  # Disable mosaic for last 5 epochs
        "hsv_h": 0.015,
        "hsv_s": 0.5,
        "hsv_v": 0.3,
        "max_det": 1500,
        "iou": 0.6,
        "cache": False,
        "rect": True,
        # multi_scale=False: 960px * 1.5 = 1440px would OOM even at batch=1
        # Progressive training (640→960) already provides multi-scale benefit
        "multi_scale": False,
    },
    {
        "name": "Phase C — Fine Details + Tiny Faces",
        "imgsz": 1280,
        "batch": 1,  # Reduced from 2 — 1280px requires minimal batch on 24GB
        "epochs": 15,
        "description": "Maximum resolution for tiny faces. P2 head gets 320px feature maps.",
        "lr0": 0.0001,
        "lrf": 0.01,
        "warmup_epochs": 1,
        "patience": 12,
        # Augmentations — gentle (fine-tuning)
        "mosaic": 0.8,
        "mixup": 0.1,
        "copy_paste": 0.2,
        "scale": 0.5,
        "degrees": 2.0,
        "translate": 0.05,
        "fliplr": 0.5,
        "label_smoothing": 0.05,
        "close_mosaic": 10,  # Disable mosaic for last 10 of 15 epochs
        "hsv_h": 0.01,
        "hsv_s": 0.3,
        "hsv_v": 0.2,
        "max_det": 1500,
        "iou": 0.5,  # Looser NMS for final phase
        "cache": False,  # 1280px images too large for RAM cache
        "rect": True,
        # multi_scale=False: 1280px * 1.5 = 1920px, certain OOM at any batch on 24GB
        "multi_scale": False,
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# GRADIENT CLIPPING CALLBACK
# ═══════════════════════════════════════════════════════════════════════════


class GradientClipCallback:
    """Clip gradients to prevent NaN explosion (proven in Phase 9)."""

    def __init__(self, max_norm: float = 10.0):
        self.max_norm = max_norm
        self._patched = False
        self.clip_count = 0
        self.total_steps = 0

    def on_train_start(self, trainer):
        if self._patched:
            return
        original_step = trainer.optimizer.step
        max_norm = self.max_norm
        callback_ref = self

        def clipped_step(closure=None):
            total_norm = nn_utils.clip_grad_norm_(trainer.model.parameters(), max_norm)
            if total_norm > max_norm:
                callback_ref.clip_count += 1
            callback_ref.total_steps += 1
            return original_step(closure)

        trainer.optimizer.step = clipped_step
        self._patched = True
        print(f"[grad-clip] Enabled: max_norm={self.max_norm}")

    def reset(self):
        """Reset for new training phase."""
        self._patched = False
        self.clip_count = 0
        self.total_steps = 0

    def register(self, model: YOLO):
        model.add_callback("on_train_start", self.on_train_start)


# ═══════════════════════════════════════════════════════════════════════════
# PROMETHEUS METRICS
# ═══════════════════════════════════════════════════════════════════════════


class TrainingMetrics:
    def __init__(self, job_name: str = "phase10"):
        self.enabled = PROMETHEUS_AVAILABLE
        self.job_name = job_name
        if self.enabled:
            self.registry = CollectorRegistry()
            self.epoch_gauge = Gauge(
                "training_epoch", "Current epoch", registry=self.registry
            )
            self.phase_gauge = Gauge(
                "training_phase", "Current training phase", registry=self.registry
            )
            self.loss_gauge = Gauge(
                "training_loss", "Training loss", ["loss_type"], registry=self.registry
            )
            self.map50_gauge = Gauge(
                "training_map50", "Validation mAP@50", registry=self.registry
            )
            self.recall_gauge = Gauge(
                "training_recall", "Validation recall", registry=self.registry
            )
            self.precision_gauge = Gauge(
                "training_precision", "Validation precision", registry=self.registry
            )
            self.gpu_mem_gauge = Gauge(
                "training_gpu_memory_gb", "GPU memory (GB)", registry=self.registry
            )
            self.imgsz_gauge = Gauge(
                "training_imgsz", "Current image size", registry=self.registry
            )

    def push(self, epoch: int, phase: int, imgsz: int, metrics: dict):
        if not self.enabled:
            return
        try:
            self.epoch_gauge.set(epoch)
            self.phase_gauge.set(phase)
            self.imgsz_gauge.set(imgsz)
            for loss_name in ["train/box_loss", "train/cls_loss", "train/dfl_loss"]:
                if loss_name in metrics:
                    self.loss_gauge.labels(loss_name.split("/")[1]).set(
                        metrics[loss_name]
                    )
            if "metrics/mAP50(B)" in metrics:
                self.map50_gauge.set(metrics["metrics/mAP50(B)"])
            if "metrics/recall(B)" in metrics:
                self.recall_gauge.set(metrics["metrics/recall(B)"])
            if "metrics/precision(B)" in metrics:
                self.precision_gauge.set(metrics["metrics/precision(B)"])
            if torch.cuda.is_available():
                self.gpu_mem_gauge.set(torch.cuda.memory_allocated(0) / 1e9)
            push_to_gateway(PUSHGATEWAY_URL, job=self.job_name, registry=self.registry)
        except Exception as e:
            print(f"[prometheus] push error: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# NESSIE
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
        print(f"[nessie] branch: {e}")
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
        print(f"[nessie] tag: {e}")
    return False


# ═══════════════════════════════════════════════════════════════════════════
# TRAINING CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════


class Phase10Callbacks:
    def __init__(
        self,
        metrics_pusher: TrainingMetrics,
        run_name: str,
        grad_clip: GradientClipCallback,
        phase_idx: int,
        phase_name: str,
        imgsz: int,
        global_epoch_offset: int = 0,
    ):
        self.metrics_pusher = metrics_pusher
        self.run_name = run_name
        self.grad_clip = grad_clip
        self.phase_idx = phase_idx
        self.phase_name = phase_name
        self.imgsz = imgsz
        self.global_epoch_offset = global_epoch_offset
        self.best_recall = 0.0
        self.best_map50 = 0.0
        self.best_f1 = 0.0
        self.best_epoch = 0
        self.start_time = time.time()
        self.nan_count = 0

    def on_train_epoch_end(self, trainer):
        epoch = trainer.epoch + 1
        global_epoch = self.global_epoch_offset + epoch
        metrics = trainer.metrics or {}

        self.metrics_pusher.push(global_epoch, self.phase_idx, self.imgsz, metrics)

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
        if any(math.isnan(v) for v in [box_loss, cls_loss, dfl_loss] if v):
            self.nan_count += 1
            print(f"  ⚠ [ep {global_epoch}] NaN in losses! (count: {self.nan_count})")
            if self.nan_count >= 3:
                print(f"  ✗ DIVERGING — 3+ consecutive NaN epochs")
                return
        else:
            self.nan_count = 0  # Reset on clean epoch

        if recall > self.best_recall:
            self.best_recall = recall
            self.best_map50 = map50
            self.best_f1 = f1
            self.best_epoch = global_epoch

        elapsed = time.time() - self.start_time
        clip_pct = (
            self.grad_clip.clip_count / max(1, self.grad_clip.total_steps)
        ) * 100

        # Deltas vs Phase 9
        r_delta = recall - BASELINE_PHASE9["recall"]
        m_delta = map50 - BASELINE_PHASE9["mAP50"]

        print(
            f"  [{self.phase_name[:7]:7s} ep {global_epoch:3d}] "
            f"box={box_loss:.4f} cls={cls_loss:.4f} dfl={dfl_loss:.4f} | "
            f"R={recall:.4f} P={precision:.4f} F1={f1:.4f} | "
            f"mAP50={map50:.4f} mAP={map_val:.4f} | "
            f"vs_p9: R{r_delta:+.3f} m50{m_delta:+.3f} | "
            f"clips={clip_pct:.0f}% | {self.imgsz}px | {elapsed/60:.0f}min"
        )

        # MLflow
        if MLFLOW_AVAILABLE and mlflow.active_run():
            try:
                mlflow.log_metrics(
                    {
                        "epoch": global_epoch,
                        "phase": self.phase_idx,
                        "imgsz": self.imgsz,
                        "val_recall": recall,
                        "val_precision": precision,
                        "val_F1": f1,
                        "val_mAP50": map50,
                        "val_mAP50_95": map_val,
                        "train_box_loss": box_loss,
                        "train_cls_loss": cls_loss,
                        "train_dfl_loss": dfl_loss,
                        "best_recall": self.best_recall,
                        "grad_clip_pct": clip_pct,
                        "delta_recall_vs_p9": r_delta,
                        "delta_map50_vs_p9": m_delta,
                    },
                    step=global_epoch,
                )
            except Exception:
                pass

    def on_train_end(self, trainer):
        total_time = time.time() - self.start_time
        clip_pct = (
            self.grad_clip.clip_count / max(1, self.grad_clip.total_steps)
        ) * 100
        print(f"\n  {'─' * 60}")
        print(f"  {self.phase_name} complete in {total_time/60:.1f}min")
        print(
            f"  Best: R={self.best_recall:.4f} F1={self.best_f1:.4f} mAP50={self.best_map50:.4f} @ epoch {self.best_epoch}"
        )
        print(
            f"  Grad clips: {self.grad_clip.clip_count}/{self.grad_clip.total_steps} ({clip_pct:.1f}%)"
        )
        print(f"  {'─' * 60}\n")

    def register(self, model: YOLO):
        model.add_callback("on_train_epoch_end", self.on_train_epoch_end)
        model.add_callback("on_train_end", self.on_train_end)


class ResourceTelemetryLogger:
    def __init__(self, run_name: str, interval_sec: int, log_path: str):
        self.run_name = run_name
        self.interval_sec = max(5, interval_sec)
        self.log_path = Path(log_path)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @staticmethod
    def _read_meminfo() -> dict[str, int]:
        values: dict[str, int] = {}
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    key, rest = line.split(":", 1)
                    parts = rest.strip().split()
                    if not parts:
                        continue
                    values[key] = int(parts[0])
        except Exception:
            return {}
        return values

    @staticmethod
    def _nvidia_snapshot() -> tuple[str, str, str, str]:
        try:
            out = subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                text=True,
                timeout=2,
            ).strip()
            first = out.splitlines()[0].split(",") if out else []
            if len(first) >= 4:
                return (
                    first[0].strip(),
                    first[1].strip(),
                    first[2].strip(),
                    first[3].strip(),
                )
        except Exception:
            pass
        return ("", "", "", "")

    @staticmethod
    def _rss_mb() -> float:
        try:
            with open("/proc/self/statm") as f:
                parts = f.read().strip().split()
            if len(parts) >= 2:
                rss_pages = int(parts[1])
                page_size = os.sysconf("SC_PAGE_SIZE")
                return (rss_pages * page_size) / (1024 * 1024)
        except Exception:
            pass
        return 0.0

    def _ensure_header(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if self.log_path.exists() and self.log_path.stat().st_size > 0:
            return
        with self.log_path.open("w") as f:
            f.write(
                "timestamp,run_name,mem_available_mb,swap_free_mb,commit_pct,load1,load5,load15,"
                "gpu_mem_used_mb,gpu_mem_total_mb,gpu_util_pct,gpu_temp_c,process_rss_mb,"
                "torch_alloc_mb,torch_reserved_mb\n"
            )

    def _write_sample(self) -> None:
        mem = self._read_meminfo()
        mem_available_mb = mem.get("MemAvailable", 0) // 1024
        swap_free_mb = mem.get("SwapFree", 0) // 1024

        commit_limit = mem.get("CommitLimit", 0)
        committed_as = mem.get("Committed_AS", 0)
        commit_pct = (
            (committed_as / commit_limit * 100.0)
            if commit_limit and committed_as
            else 0.0
        )

        load1, load5, load15 = os.getloadavg()
        gpu_used, gpu_total, gpu_util, gpu_temp = self._nvidia_snapshot()

        torch_alloc_mb = 0.0
        torch_reserved_mb = 0.0
        try:
            if torch.cuda.is_available():
                torch_alloc_mb = torch.cuda.memory_allocated(0) / (1024 * 1024)
                torch_reserved_mb = torch.cuda.memory_reserved(0) / (1024 * 1024)
        except Exception:
            pass

        row = (
            f"{datetime.now().isoformat(timespec='seconds')},{self.run_name},"
            f"{mem_available_mb},{swap_free_mb},{commit_pct:.2f},"
            f"{load1:.2f},{load5:.2f},{load15:.2f},"
            f"{gpu_used},{gpu_total},{gpu_util},{gpu_temp},"
            f"{self._rss_mb():.2f},{torch_alloc_mb:.2f},{torch_reserved_mb:.2f}\n"
        )

        with self.log_path.open("a") as f:
            f.write(row)

    def _run(self) -> None:
        self._ensure_header()
        while not self._stop_event.is_set():
            try:
                self._write_sample()
            except Exception:
                pass
            self._stop_event.wait(self.interval_sec)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print(
            f"[telemetry] Logging resource samples every {self.interval_sec}s -> {self.log_path}"
        )

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=5)
        self._thread = None


# ═══════════════════════════════════════════════════════════════════════════
# TRAINING
# ═══════════════════════════════════════════════════════════════════════════


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase 10 — Multi-Scale Progressive Training"
    )
    parser.add_argument(
        "--phase",
        type=int,
        default=1,
        choices=[1, 2, 3],
        help="Start at phase (1=640px, 2=960px, 3=1280px)",
    )
    parser.add_argument(
        "--single-scale",
        type=int,
        default=None,
        help="Fixed scale training (skip progressive)",
    )
    parser.add_argument(
        "--epochs-override",
        type=int,
        default=None,
        help="Override total epochs per phase",
    )
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--max-norm", type=float, default=10.0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pretrained", type=str, default=PRETRAINED_WEIGHTS)
    parser.add_argument(
        "--dataset",
        type=str,
        default=None,
        help="Dataset directory (auto-detects merged vs WIDER)",
    )
    parser.add_argument("--name", type=str, default=None)
    parser.add_argument(
        "--allow-memory-pressure",
        action="store_true",
        help="Allow training to proceed even when host RAM/swap preflight thresholds are exceeded",
    )
    parser.add_argument(
        "--val-on-wider",
        action="store_true",
        default=True,
        help="Always validate on WIDER Face val (fair comparison)",
    )
    return parser.parse_args()


def detect_dataset(args) -> str:
    """Auto-detect which dataset to use."""
    if args.dataset:
        return args.dataset

    # Prefer merged dataset if available
    merged_yaml = Path(MERGED_YOLO_DIR) / "data.yaml"
    if merged_yaml.exists():
        print(f"[data] Using merged multi-source dataset: {MERGED_YOLO_DIR}")
        return MERGED_YOLO_DIR

    # Fall back to WIDER-only
    wider_yaml = Path(WIDER_YOLO_DIR) / "data.yaml"
    if wider_yaml.exists():
        print(f"[data] Using WIDER Face only: {WIDER_YOLO_DIR}")
        return WIDER_YOLO_DIR

    print("✗ No dataset found. Run prepare_merged_yolo.py first.")
    sys.exit(1)


def validate_environment(args: argparse.Namespace, dataset_dir: str) -> dict:
    """Pre-flight checks."""
    issues = []
    fatal_issues = []
    info = {}

    meminfo: dict[str, int] = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                key, rest = line.split(":", 1)
                value = rest.strip().split()[0]
                meminfo[key] = int(value)
    except Exception:
        pass

    if meminfo:
        mem_available_mb = meminfo.get("MemAvailable", 0) // 1024
        swap_free_mb = meminfo.get("SwapFree", 0) // 1024
        commit_limit = meminfo.get("CommitLimit", 0)
        committed_as = meminfo.get("Committed_AS", 0)
        commit_pct = (
            (committed_as / commit_limit * 100.0)
            if commit_limit and committed_as
            else 0.0
        )

        info["host_mem_available_mb"] = mem_available_mb
        info["host_swap_free_mb"] = swap_free_mb
        info["host_commit_pct"] = commit_pct

        if mem_available_mb < MIN_HOST_MEM_AVAILABLE_MB:
            fatal_issues.append(
                "Host MemAvailable "
                f"{mem_available_mb}MB < required {MIN_HOST_MEM_AVAILABLE_MB}MB"
            )

        if swap_free_mb < MIN_HOST_SWAP_FREE_MB:
            fatal_issues.append(
                "Host SwapFree "
                f"{swap_free_mb}MB < required {MIN_HOST_SWAP_FREE_MB}MB"
            )

        if commit_pct > MAX_HOST_COMMIT_PCT:
            fatal_issues.append(
                f"Host commit pressure {commit_pct:.1f}% > allowed {MAX_HOST_COMMIT_PCT:.1f}%"
            )

    pretrained = Path(args.pretrained)
    if not pretrained.exists():
        issues.append(f"Pretrained weights not found: {pretrained}")
    else:
        info["pretrained"] = str(pretrained)
        info["pretrained_size_mb"] = pretrained.stat().st_size / 1e6

    data_yaml = Path(dataset_dir) / "data.yaml"
    if not data_yaml.exists():
        issues.append(f"Dataset config not found: {data_yaml}")
    else:
        info["dataset"] = str(data_yaml)
        info["dataset_dir"] = dataset_dir

    train_dir = Path(dataset_dir) / "images" / "train"
    val_dir = Path(dataset_dir) / "images" / "val"
    if train_dir.exists():
        n_train = len(list(train_dir.glob("*.jpg"))) + len(
            list(train_dir.glob("*.png"))
        )
        info["train_images"] = n_train
    else:
        issues.append(f"Training images not found: {train_dir}")

    if val_dir.exists():
        n_val = len(list(val_dir.glob("*.jpg"))) + len(list(val_dir.glob("*.png")))
        info["val_images"] = n_val
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

    if fatal_issues:
        print("╔════════════ PRE-FLIGHT SAFETY GATES ════════════╗")
        for issue in fatal_issues:
            print(f"  ✗ {issue}")
        print("╚═════════════════════════════════════════════════╝")

    return {"issues": issues, "fatal_issues": fatal_issues, "info": info}


def run_training_phase(
    phase_config: dict,
    phase_idx: int,
    weights_path: str,
    dataset_dir: str,
    args: argparse.Namespace,
    run_name: str,
    metrics_pusher: TrainingMetrics,
    global_epoch_offset: int,
) -> tuple[Optional[dict], str, int]:
    """Run one phase of multi-scale training.

    Returns (result_metrics, best_weights_path, new_global_epoch_offset)
    """
    phase_name = phase_config["name"]
    imgsz = phase_config["imgsz"]
    batch = phase_config["batch"]
    epochs = args.epochs_override or phase_config["epochs"]

    print(f"\n{'═' * 70}")
    print(f"  {phase_name}")
    print(f"  {phase_config['description']}")
    print(f"  Size: {imgsz}px | Batch: {batch} | Epochs: {epochs}")
    print(f"  LR: {phase_config['lr0']} → {phase_config['lr0'] * phase_config['lrf']}")
    print(f"  Weights: {Path(weights_path).name}")
    print(f"{'═' * 70}\n")

    # Create gradient clipper for this phase
    grad_clip = GradientClipCallback(max_norm=args.max_norm)

    # Load model with current best weights
    print(f"  Loading: {weights_path}")
    model = YOLO(weights_path)

    # Register callbacks
    callbacks = Phase10Callbacks(
        metrics_pusher=metrics_pusher,
        run_name=run_name,
        grad_clip=grad_clip,
        phase_idx=phase_idx,
        phase_name=phase_name,
        imgsz=imgsz,
        global_epoch_offset=global_epoch_offset,
    )
    callbacks.register(model)
    grad_clip.register(model)

    # Phase output dir
    phase_dir_name = f"{run_name}_phase{phase_idx}_{imgsz}px"

    try:
        results = model.train(
            # Data
            data=f"{dataset_dir}/data.yaml",
            imgsz=imgsz,
            # Schedule
            epochs=epochs,
            batch=batch,
            patience=phase_config["patience"],
            # Optimizer
            optimizer="AdamW",
            lr0=phase_config["lr0"],
            lrf=phase_config["lrf"],
            weight_decay=0.0005,
            cos_lr=True,
            warmup_epochs=phase_config["warmup_epochs"],
            warmup_bias_lr=0.05,
            warmup_momentum=0.8,
            nbs=64,  # Gradient accumulation → effective batch 64
            # Augmentations — recall-tuned
            mosaic=phase_config["mosaic"],
            mixup=phase_config["mixup"],
            copy_paste=phase_config["copy_paste"],
            degrees=phase_config["degrees"],
            translate=phase_config["translate"],
            scale=phase_config["scale"],
            fliplr=phase_config["fliplr"],
            hsv_h=phase_config["hsv_h"],
            hsv_s=phase_config["hsv_s"],
            hsv_v=phase_config["hsv_v"],
            close_mosaic=phase_config["close_mosaic"],
            label_smoothing=phase_config.get("label_smoothing", 0.0),
            # Loss weights — recall-tuned (higher box = better localization)
            box=phase_config.get("box", 10.0),
            cls=phase_config.get("cls", 0.3),
            dfl=phase_config.get("dfl", 2.0),
            # Per-phase multi_scale: True for Phase A (640px, batch=2 handles 960px worst-case),
            # False for Phase B/C where 1.5x would exceed 24GB VRAM
            multi_scale=phase_config.get("multi_scale", False),
            copy_paste_mode="flip",
            # Detection
            max_det=phase_config["max_det"],
            iou=phase_config["iou"],
            # Memory — conservative for 24GB VRAM
            rect=phase_config.get("rect", True),
            cache=phase_config.get("cache", False),
            # Hardware
            device=args.device,
            workers=min(args.workers, 2),  # Cap workers to reduce RAM/VRAM pressure
            amp=True,
            # Output
            project=str(CHECKPOINT_DIR),
            name=phase_dir_name,
            exist_ok=True,
            verbose=True,
            plots=True,
            save=True,
            save_period=5,
        )

    except torch.cuda.OutOfMemoryError:
        print(f"\n  ⚠ OOM at batch={batch}, imgsz={imgsz}")
        del model
        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
        time.sleep(3)

        new_batch = max(1, batch // 2)
        print(f"  Retrying with batch={new_batch}...")
        model = YOLO(weights_path)
        callbacks = Phase10Callbacks(
            metrics_pusher,
            run_name,
            grad_clip,
            phase_idx,
            phase_name,
            imgsz,
            global_epoch_offset,
        )
        callbacks.register(model)
        grad_clip.register(model)

        try:
            results = model.train(
                data=f"{dataset_dir}/data.yaml",
                imgsz=imgsz,
                epochs=epochs,
                batch=new_batch,
                patience=phase_config["patience"],
                optimizer="AdamW",
                lr0=phase_config["lr0"],
                lrf=phase_config["lrf"],
                weight_decay=0.0005,
                cos_lr=True,
                warmup_epochs=phase_config["warmup_epochs"],
                nbs=64,
                mosaic=phase_config["mosaic"],
                mixup=phase_config["mixup"],
                copy_paste=phase_config["copy_paste"],
                scale=phase_config["scale"],
                close_mosaic=phase_config["close_mosaic"],
                label_smoothing=phase_config.get("label_smoothing", 0.0),
                box=phase_config.get("box", 10.0),
                cls=phase_config.get("cls", 0.3),
                dfl=phase_config.get("dfl", 2.0),
                # OOM retry: disable multi_scale even if phase had it enabled,
                # since we're already at halved batch and memory-constrained
                multi_scale=False,
                copy_paste_mode="flip",
                max_det=phase_config["max_det"],
                iou=phase_config["iou"],
                rect=True,
                cache=False,  # Disable cache on OOM retry
                device=args.device,
                workers=1,  # Minimum workers on OOM retry
                amp=True,
                project=str(CHECKPOINT_DIR),
                name=phase_dir_name,
                exist_ok=True,
                verbose=True,
                plots=True,
                save=True,
                save_period=5,
            )
        except torch.cuda.OutOfMemoryError:
            print(f"  ✗ OOM even at batch={new_batch}. Skipping this phase.")
            return None, weights_path, global_epoch_offset

    # Extract results
    result_metrics = {}
    if results:
        result_metrics = {
            "mAP50": float(results.results_dict.get("metrics/mAP50(B)", 0)),
            "mAP50_95": float(results.results_dict.get("metrics/mAP50-95(B)", 0)),
            "precision": float(results.results_dict.get("metrics/precision(B)", 0)),
            "recall": float(results.results_dict.get("metrics/recall(B)", 0)),
            "phase": phase_idx,
            "imgsz": imgsz,
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

    # Find best weights from this phase
    best_weights = CHECKPOINT_DIR / phase_dir_name / "weights" / "best.pt"
    if best_weights.exists():
        next_weights = str(best_weights)
    else:
        # Try last weights
        last_weights = CHECKPOINT_DIR / phase_dir_name / "weights" / "last.pt"
        next_weights = str(last_weights) if last_weights.exists() else weights_path

    new_offset = global_epoch_offset + epochs

    # Clean up
    del model
    gc.collect()
    torch.cuda.empty_cache()
    time.sleep(2)

    return result_metrics, next_weights, new_offset


def train(args: argparse.Namespace) -> Optional[dict]:
    """Run full multi-scale progressive training."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_name = args.name or f"phase10_{timestamp}"
    nessie_branch = f"phase10/{run_name}"

    # Detect dataset
    dataset_dir = detect_dataset(args)

    print(f"\n{'═' * 70}")
    print(f"  Phase 10 — Multi-Scale Progressive Training")
    print(f"  Run: {run_name}")
    print(f"  Base model: {args.pretrained}")
    print(f"  Dataset: {dataset_dir}")
    if args.single_scale:
        print(f"  Mode: Single-scale @ {args.single_scale}px")
    else:
        start_phase = args.phase
        end_phase = 3
        phases_str = " → ".join(
            f"{TRAINING_PHASES[i]['imgsz']}px"
            for i in range(start_phase - 1, end_phase)
        )
        print(f"  Mode: Progressive ({phases_str})")
    print(f"  Gradient Clipping: max_norm={args.max_norm}")
    print(f"{'═' * 70}\n")

    # Pre-flight
    preflight = validate_environment(args, dataset_dir)
    if preflight["issues"] and args.dry_run:
        print("[dry-run] Pre-flight issues found.")
        return None
    elif preflight["issues"]:
        print("⚠ Pre-flight issues — attempting to proceed")

    fatal_issues = preflight.get("fatal_issues", [])
    if fatal_issues and not args.allow_memory_pressure:
        print("\n✗ Aborting due to safety gates (RAM/swap/commit pressure).")
        print("  Use --allow-memory-pressure to override (not recommended).")
        return None

    info = preflight["info"]
    print(
        f"[data] train={info.get('train_images', '?')} val={info.get('val_images', '?')}"
    )
    print(
        f"[gpu] {info.get('gpu', 'N/A')} — {info.get('gpu_free_gb', 0):.1f}/{info.get('gpu_total_gb', 0):.1f} GB"
    )
    print(
        f"[host] mem_avail={info.get('host_mem_available_mb', 0)}MB "
        f"swap_free={info.get('host_swap_free_mb', 0)}MB "
        f"commit={info.get('host_commit_pct', 0):.1f}%"
    )
    print(
        f"[baseline/p9] R={BASELINE_PHASE9['recall']:.3f} P={BASELINE_PHASE9['precision']:.3f} mAP50={BASELINE_PHASE9['mAP50']:.3f}"
    )

    if args.dry_run:
        print("\n[dry-run] Config validated. Ready to train.")
        # Print phase plan
        for i, phase in enumerate(TRAINING_PHASES):
            if args.single_scale and phase["imgsz"] != args.single_scale:
                continue
            if not args.single_scale and i < args.phase - 1:
                continue
            ep = args.epochs_override or phase["epochs"]
            print(
                f"  Phase {i+1}: {phase['name']} — {phase['imgsz']}px, batch={phase['batch']}, "
                f"epochs={ep}, lr={phase['lr0']}"
            )
        return None

    # Initialize integrations
    metrics_pusher = TrainingMetrics(job_name=f"phase10_{run_name}")
    nessie_create_branch(nessie_branch)

    # MLflow
    if MLFLOW_AVAILABLE:
        try:
            mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
            mlflow.set_experiment(MLFLOW_EXPERIMENT)
            mlflow.start_run(
                run_name=run_name,
                tags={
                    "model": "yolov8m-p2",
                    "base": "phase9-champion",
                    "strategy": "multiscale-progressive",
                    "dataset": Path(dataset_dir).name,
                    "phase": "10",
                },
            )
            mlflow.log_params(
                {
                    "pretrained": args.pretrained,
                    "dataset": dataset_dir,
                    "max_norm": args.max_norm,
                    "mode": (
                        f"single-{args.single_scale}"
                        if args.single_scale
                        else "progressive"
                    ),
                    "start_phase": args.phase,
                    "base_recall_p9": BASELINE_PHASE9["recall"],
                    "base_mAP50_p9": BASELINE_PHASE9["mAP50"],
                }
            )
            print(f"[mlflow] run started: {run_name}")
        except Exception as e:
            print(f"[mlflow] setup error: {e}")

    start_time = time.time()
    telemetry: Optional[ResourceTelemetryLogger] = None
    if ENABLE_TRAINING_TELEMETRY:
        telemetry = ResourceTelemetryLogger(
            run_name=run_name,
            interval_sec=TRAINING_TELEMETRY_INTERVAL_SEC,
            log_path=TRAINING_TELEMETRY_LOG,
        )
        telemetry.start()

    # Determine which phases to run
    if args.single_scale:
        # Find matching phase config
        matching = [p for p in TRAINING_PHASES if p["imgsz"] == args.single_scale]
        if not matching:
            # Create config for arbitrary scale
            matching = [
                {
                    **TRAINING_PHASES[1],  # Use Phase B as template
                    "name": f"Single-Scale {args.single_scale}px",
                    "imgsz": args.single_scale,
                    "epochs": args.epochs_override or 50,
                }
            ]
        phases_to_run = [(0, matching[0])]
    else:
        phases_to_run = [
            (i, TRAINING_PHASES[i]) for i in range(args.phase - 1, len(TRAINING_PHASES))
        ]

    # Run progressive phases
    current_weights = args.pretrained
    global_epoch_offset = 0
    all_phase_results = []
    best_overall_recall = 0.0
    best_overall_weights = current_weights

    try:
        for phase_idx_0based, phase_config in phases_to_run:
            phase_idx = phase_idx_0based + 1

            result, next_weights, global_epoch_offset = run_training_phase(
                phase_config=phase_config,
                phase_idx=phase_idx,
                weights_path=current_weights,
                dataset_dir=dataset_dir,
                args=args,
                run_name=run_name,
                metrics_pusher=metrics_pusher,
                global_epoch_offset=global_epoch_offset,
            )

            if result:
                all_phase_results.append(result)
                current_weights = next_weights

                # Track overall best
                if result.get("recall", 0) > best_overall_recall:
                    best_overall_recall = result["recall"]
                    best_overall_weights = next_weights

                print(
                    f"  Phase {phase_idx} result: R={result.get('recall', 0):.4f} "
                    f"P={result.get('precision', 0):.4f} "
                    f"mAP50={result.get('mAP50', 0):.4f}"
                )
            else:
                print(f"  Phase {phase_idx} failed — continuing with previous weights")
    finally:
        if telemetry is not None:
            telemetry.stop()

    total_time = time.time() - start_time

    # Final results
    final_result = all_phase_results[-1] if all_phase_results else {}
    final_result["training_time_hours"] = total_time / 3600
    final_result["total_phases"] = len(all_phase_results)

    # Results summary
    print(f"\n{'═' * 70}")
    print(f"  Phase 10 — Multi-Scale Progressive Training RESULTS")
    print(f"{'═' * 70}")
    print(f"  Total time: {total_time/3600:.1f}h ({len(all_phase_results)} phases)")
    print(
        f"  Dataset:    {Path(dataset_dir).name} ({info.get('train_images', '?')} train)"
    )
    print()

    for i, res in enumerate(all_phase_results):
        p = res.get("phase", i + 1)
        sz = res.get("imgsz", "?")
        r_delta = res.get("recall", 0) - BASELINE_PHASE9["recall"]
        print(
            f"    Phase {p} ({sz}px): R={res.get('recall', 0):.4f} P={res.get('precision', 0):.4f} "
            f"F1={res.get('F1', 0):.4f} mAP50={res.get('mAP50', 0):.4f} "
            f"(R vs P9: {r_delta:+.3f})"
        )

    print()
    r_final = final_result.get("recall", 0)
    p_final = final_result.get("precision", 0)
    print(
        f"  FINAL:   R={r_final:.4f}  P={p_final:.4f}  mAP50={final_result.get('mAP50', 0):.4f}"
    )
    print(
        f"  vs P9:   R{r_final - BASELINE_PHASE9['recall']:+.4f}  |  vs P5: R{r_final - BASELINE_PHASE5['recall']:+.4f}"
    )
    print(
        f"  Target:  R>0.80 P>0.85 — {'✓ MET' if r_final > 0.80 and p_final > 0.85 else '✗ NOT MET'}"
    )
    print(f"{'═' * 70}\n")

    # MLflow finalization
    if MLFLOW_AVAILABLE and mlflow.active_run():
        try:
            mlflow.log_metrics(
                {
                    f"final_{k}": v
                    for k, v in final_result.items()
                    if isinstance(v, (int, float))
                }
            )
            if Path(best_overall_weights).exists():
                mlflow.log_artifact(best_overall_weights, "weights")
            for phase_res in all_phase_results:
                phase_n = phase_res.get("phase", 0)
                for k, v in phase_res.items():
                    if isinstance(v, (int, float)):
                        mlflow.log_metric(f"phase{phase_n}_{k}", v)
            mlflow.end_run()
            print("[mlflow] run logged")
        except Exception as e:
            print(f"[mlflow] finalization error: {e}")
            try:
                mlflow.end_run()
            except Exception:
                pass

    # Nessie tag
    if r_final > BASELINE_PHASE9["recall"]:
        tag = f"phase10-recall-{r_final:.3f}-{timestamp}"
        nessie_tag_model(nessie_branch, tag)

    # Copy best weights to comparison directory
    if Path(best_overall_weights).exists():
        dest = Path(
            "/tmp/ray/checkpoints/face_detection/model_comparison/phase10_multiscale_best.pt"
        )
        shutil.copy2(best_overall_weights, dest)
        print(f"[save] Best weights → {dest}")

    # Save metadata
    meta_path = CHECKPOINT_DIR / f"{run_name}_metadata.json"
    metadata = {
        "phase": "10",
        "model": "yolov8m-p2",
        "strategy": "multiscale-progressive",
        "base_model": args.pretrained,
        "dataset": dataset_dir,
        "phases": (
            [
                {
                    "config": {k: v for k, v in phase.items() if k != "description"},
                    "result": res,
                }
                for phase, (_, res) in zip(
                    [TRAINING_PHASES[i] for i, _ in phases_to_run],
                    enumerate(all_phase_results),
                )
            ]
            if len(all_phase_results) == len(phases_to_run)
            else []
        ),
        "final_result": final_result,
        "baseline_phase9": BASELINE_PHASE9,
        "baseline_phase5": BASELINE_PHASE5,
        "best_weights": best_overall_weights,
        "timestamp": timestamp,
        "total_time_hours": total_time / 3600,
        "gpu": info.get("gpu", "unknown"),
    }
    try:
        with open(meta_path, "w") as f:
            json.dump(metadata, f, indent=2, default=str)
        print(f"[meta] Saved: {meta_path}")
    except Exception as e:
        print(f"[meta] Save error: {e}")

    return final_result


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════


def main():
    args = parse_args()

    print(f"╔════════════════════════════════════════════════════════════════╗")
    print(f"║  Phase 10 — Multi-Scale Progressive Training                 ║")
    print(f"║  GPU Yield: {'YES' if _gpu_yielded else 'NO':46s} ║")
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
        except Exception:
            pass

    if results:
        r = results.get("recall", 0)
        target_met = r > 0.80 and results.get("precision", 0) > 0.85
        print(f"\n{'✓' if target_met else '→'} Final recall: {r:.4f}")
        print(
            f"[next] Best weights: /tmp/ray/checkpoints/face_detection/model_comparison/phase10_multiscale_best.pt"
        )
        print(f"[next] Run pr_curve_sweep.py to find optimal confidence threshold")

    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
