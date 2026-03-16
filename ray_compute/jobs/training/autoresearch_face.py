#!/usr/bin/env python3
"""
Autoresearch Adaptation — Face Detection Hyperparameter Search
==============================================================

Adapts Karpathy's autoresearch pattern to iterate on YOLOv8m-P2 face
detection hyperparameters using FiftyOne metrics as the validation signal.

Loop:
  1. Agent proposes a hyperparameter mutation (via LLM or schedule)
  2. Run a CONSTRAINED training iteration (5-15 min, 3-5 epochs)
  3. Evaluate on WIDER Face val via quick YOLO val (or FiftyOne)
  4. Compare mAP50 + recall against baselines (Phase 5, Phase 9)
  5. KEEP if improved, DISCARD if regressed
  6. Log everything to MLflow + results journal
  7. Repeat

Key adaptations from Karpathy's original:
  - Fixed-time budget per experiment (not fixed epochs)
  - VRAM-aware: respects 24GB 3090 Ti constraint
  - Uses YOLO val instead of custom train loop for speed
  - FiftyOne Brain integration for failure analysis on best runs
  - GPU yield integration for coexistence with coding model
  - program.md teaches the agent about WIDER Face / YOLOv8m-P2 constraints

Usage:
  # Run with default schedule (grid over loss weights + LR):
  python autoresearch_face.py --weights /path/to/phase9_best.pt \
                               --dataset /tmp/ray/data/wider_face_yolo \
                               --budget-minutes 5 --max-iterations 20

  # Run with LLM-driven mutations:
  python autoresearch_face.py --weights /path/to/phase9_best.pt \
                               --llm-url http://localhost:8020/v1 \
                               --budget-minutes 10 --max-iterations 10

  # Dry run:
  python autoresearch_face.py --dry-run
"""

import argparse
import copy
import gc
import json
import math
import os
import shutil
import subprocess
import sys
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import requests
import yaml

# ═══════════════════════════════════════════════════════════════════════════
# GPU YIELD (same pattern as Phase 10)
# ═══════════════════════════════════════════════════════════════════════════
_script_dir = os.path.dirname(os.path.abspath(__file__))
for _p in [os.path.join(_script_dir, ".."), _script_dir]:
    _p = os.path.abspath(_p)
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

_job_id = os.environ.get("RAY_JOB_ID", f"autoresearch-{os.getpid()}")
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

import torch

os.environ.setdefault(
    "PYTORCH_CUDA_ALLOC_CONF",
    "expandable_segments:True,garbage_collection_threshold:0.7,max_split_size_mb:256",
)

if torch.cuda.is_available():
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    gpu_name = torch.cuda.get_device_name(0)
    vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
    print(f"[cuda] {gpu_name} — {vram_gb:.1f} GB VRAM")

try:
    from ultralytics import YOLO
except ImportError:
    print("[ultralytics] NOT installed")
    sys.exit(1)

MLFLOW_AVAILABLE = False
try:
    import mlflow
    MLFLOW_AVAILABLE = True
except ImportError:
    pass

import threading

# ═══════════════════════════════════════════════════════════════════════════
# REDIS PUB/SUB — live per-epoch metrics + experiment events
# Silently disabled when Redis is unavailable; training continues normally.
# Channel: shml:autoresearch:progress
#   event types: "epoch" (per epoch) and "experiment_complete" (end of run)
# ═══════════════════════════════════════════════════════════════════════════

_REDIS_AVAILABLE = False
_redis_client = None
try:
    import redis as _redis_lib
    _REDIS_URL = os.environ.get("REDIS_URL", "redis://shml-redis:6379/0")
    _redis_client = _redis_lib.from_url(
        _REDIS_URL, decode_responses=True, socket_connect_timeout=2, socket_timeout=2
    )
    _redis_client.ping()
    _REDIS_AVAILABLE = True
    print(f"[redis] Connected: {_REDIS_URL}")
except Exception as _redis_err:
    print(f"[redis] Not available ({_redis_err.__class__.__name__}) — pub/sub disabled")


def publish_event(channel: str, payload: dict) -> None:
    """Publish a JSON event to Redis pub/sub. No-ops silently if Redis unavailable."""
    if not _REDIS_AVAILABLE or _redis_client is None:
        return
    try:
        _redis_client.publish(channel, json.dumps(payload, default=str))
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# GPU ORCHESTRATOR
# Manages cycling the full 24 GB 3090 Ti between training and inference:
#   acquire() → stop inference container → train on GPU 0 with full VRAM
#   release() → start inference container → LLM mutation proposal
# ═══════════════════════════════════════════════════════════════════════════

import subprocess as _subprocess


class GpuOrchestrator:
    """Stop/start the Qwen inference container to free/reclaim GPU 0.

    Workflow per autoresearch iteration:
        orchestrator.acquire()   → docker stop qwen-coding  (free ~23 GB)
        ... train YOLOv8 on GPU 0 with full 24 GB ...
        orchestrator.release()   → docker start qwen-coding (load model back)
        ... call LLM for next mutation proposal             ...
        orchestrator.acquire()   → repeat
    """

    def __init__(
        self,
        containers: list[str] | None = None,
        llm_url: str = "http://localhost:8020/v1",
        gpu_id: int = 0,
        free_vram_threshold_gb: float = 2.0,
        inference_ready_timeout: int = 120,
    ):
        # Containers that host models on GPU 0 (in stop-priority order)
        self.containers = containers or ["qwen-coding"]
        self.llm_url = llm_url
        self.gpu_id = gpu_id
        self.free_vram_threshold_gb = free_vram_threshold_gb
        self.inference_ready_timeout = inference_ready_timeout
        self._held = False  # True when we own the GPU for training

    # ── internal helpers ────────────────────────────────────────────────

    def _run(self, cmd: list[str], timeout: int = 30) -> bool:
        try:
            r = _subprocess.run(cmd, timeout=timeout, capture_output=True, text=True)
            return r.returncode == 0
        except Exception as e:
            print(f"  [orchestrator] cmd {cmd[0]} failed: {e}")
            return False

    def _vram_free_gb(self) -> float:
        try:
            r = _subprocess.run(
                ["nvidia-smi", f"--id={self.gpu_id}", "--query-gpu=memory.free",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            return float(r.stdout.strip()) / 1024.0
        except Exception:
            return 0.0

    def _wait_vram_free(self, timeout: int = 60) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            free = self._vram_free_gb()
            if free >= self.free_vram_threshold_gb:
                print(f"  [orchestrator] GPU {self.gpu_id} free: {free:.1f} GB ✓")
                return True
            time.sleep(2)
        print(f"  [orchestrator] WARNING: VRAM still low after {timeout}s "
              f"(free={self._vram_free_gb():.1f} GB)")
        return False

    def _container_healthy(self, name: str) -> bool:
        try:
            r = _subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Status}}", name],
                capture_output=True, text=True, timeout=5,
            )
            return r.stdout.strip() in ("running",)
        except Exception:
            return False

    def _wait_llm_ready(self, timeout: int | None = None) -> bool:
        deadline = time.time() + (timeout or self.inference_ready_timeout)
        while time.time() < deadline:
            try:
                r = requests.get(f"{self.llm_url}/models", timeout=5)
                if r.status_code == 200:
                    print(f"  [orchestrator] LLM ready at {self.llm_url} ✓")
                    return True
            except Exception:
                pass
            time.sleep(3)
        print(f"  [orchestrator] WARNING: LLM not ready after {timeout}s")
        return False

    # ── public interface ────────────────────────────────────────────────

    def acquire(self) -> bool:
        """Stop inference containers and free GPU 0 for training.

        Returns True when GPU VRAM is available for training.
        """
        if self._held:
            return True  # Already acquired

        print(f"\n  ┌─ [orchestrator] Acquiring GPU {self.gpu_id} for training …")
        stopped = []
        for name in self.containers:
            if self._container_healthy(name):
                print(f"  │  Stopping {name} …")
                if self._run(["docker", "stop", name], timeout=45):
                    stopped.append(name)
                    print(f"  │  {name} stopped ✓")
                else:
                    print(f"  │  ⚠ Could not stop {name} — will try anyway")

        # Wait for VRAM to drain
        ok = self._wait_vram_free(timeout=60)
        # Claim full GPU memory budget
        if torch.cuda.is_available():
            torch.cuda.set_per_process_memory_fraction(0.95, self.gpu_id)
        self._held = True
        print(f"  └─ [orchestrator] GPU {self.gpu_id} acquired "
              f"({self._vram_free_gb():.1f} GB free)\n")
        return ok

    def release(self) -> bool:
        """Start inference containers and wait for LLM to be ready.

        Returns True when LLM endpoint is responding.
        """
        if not self._held:
            return True  # Already released

        print(f"\n  ┌─ [orchestrator] Releasing GPU {self.gpu_id} for inference …")
        # Relax memory fraction before starting containers
        if torch.cuda.is_available():
            torch.cuda.set_per_process_memory_fraction(0.05, self.gpu_id)
        gc.collect()
        torch.cuda.empty_cache()

        for name in reversed(self.containers):
            print(f"  │  Starting {name} …")
            self._run(["docker", "start", name], timeout=30)

        print(f"  │  Waiting for LLM to load model …")
        ok = self._wait_llm_ready()
        self._held = False
        print(f"  └─ [orchestrator] Inference ready ✓\n")
        return ok

    def cleanup(self):
        """Ensure inference containers are running on exit."""
        if self._held:
            print("[orchestrator] cleanup: releasing GPU back to inference")
            self.release()


# ═══════════════════════════════════════════════════════════════════════════
# BASELINES (from Phase 5 and Phase 9)
# ═══════════════════════════════════════════════════════════════════════════

BASELINE_PHASE5 = {
    "precision": 0.889, "recall": 0.716, "F1": 0.793,
    "mAP50": 0.798, "mAP50_95": 0.461,
}
BASELINE_PHASE9 = {
    "precision": 0.883, "recall": 0.729, "F1": 0.797,
    "mAP50": 0.814, "mAP50_95": 0.441,
}

# PII priority: recall is the primary champion metric.
# A missed face = privacy violation; a false positive = minor overhead.
# Secondary tiebreak on mAP50 prevents precision from collapsing.
# Hard floors: mAP50 >= Phase 5 floor (guards degenerate detect-all models);
#              recall >= Phase 9 floor (don't regress from best checkpoint).
CHAMPION_METRIC = "recall"  # Primary metric for keep/discard (PII: never miss a face)
SECONDARY_METRIC = "mAP50"  # Secondary: tiebreak keeps precision from collapsing


# ═══════════════════════════════════════════════════════════════════════════
# HYPERPARAMETER SPACE
# ═══════════════════════════════════════════════════════════════════════════

# Default config — MULTI-SCALE v4 from Phase 9 baseline
# Phase 9: imgsz=960, batch=4, cache=ram, 50 epochs, close_mosaic=10
#          box=7.5, cls=0.5, dfl=1.5, iou=0.7, max_det=500
# Autoresearch v4: multi_scale=0.33 trains at 643-1280px each batch
#   - batch=2 for stable BatchNorm statistics (batch=1 was instance-norm noise)
#   - multi_scale=0.33 keeps peak at 1280px → batch=2 fits in ~16GB / 24GB
#   - 30 epochs minimum: Phase 9 peaked at ep 9; autoresearch peaked at ep 4 then
#     regressed — need enough epochs for cosine LR to bring stability
#   - cache=ram eliminates I/O penalty at every scale (dataset ~1.6 GB in 64 GB RAM)
DEFAULT_CONFIG = {
    "imgsz": 960,        # Center of multi-scale range (643–1280px)
    "batch": 2,          # batch=2 at peak 1280px ≈ 16GB; clean BN stats
    "epochs": 30,        # 30 epochs: Phase 9 needed 9+, autoresearch peaked at 4 then regressed
    "lr0": 0.0005,
    "lrf": 0.01,         # Phase 9 value — gentler LR decay than 0.05
    "warmup_epochs": 3,  # Phase 9 value — 1 was too short
    "patience": 20,      # YOLO fitness-based early stop; 20 prevents killing recall-climbing runs
    # Augmentation (Phase 9 was more conservative than Phase 10)
    "mosaic": 1.0,
    "mixup": 0.1,        # Phase 9: 0.1 (not 0.2)
    "copy_paste": 0.3,
    "scale": 0.5,        # Phase 9: 0.5 (not 0.9 — too aggressive for short runs)
    "degrees": 5.0,
    "translate": 0.1,
    "fliplr": 0.5,
    "label_smoothing": 0.0,  # Phase 9: 0.0
    "close_mosaic": 5,       # Turn off mosaic for last 5 epochs (Phase 9: 10)
    "hsv_h": 0.015,
    "hsv_s": 0.5,        # Phase 9: 0.5 (not 0.7)
    "hsv_v": 0.3,        # Phase 9: 0.3 (not 0.4)
    # Loss weights (Phase 9 defaults)
    "box": 7.5,          # Phase 9: 7.5 (not 10.0)
    "cls": 0.5,          # Phase 9: 0.5 (not 0.3)
    "dfl": 1.5,          # Phase 9: 1.5 (not 2.0)
    # Detection
    "max_det": 1000,     # PII: 1000 to handle dense crowd/concert frames (500 too low)
    "iou": 0.7,          # Phase 9: 0.7 (not 0.6)
    # Memory
    "cache": "ram",      # Entire dataset in RAM (~1.6 GB) — zero I/O at any scale
    "rect": True,
    "multi_scale": 0.33, # ±33%: trains at 643–1280px; peak ~16 GB at batch=2
}

# PII FUTURE TODO: box padding at inference — expand each detected box by 5%, scale to 15% as needed.
# Deferred until raw recall is maximised; zero training cost when implemented.

# WIDER Face Hard event IDs (crowd density / small face / sports scenes — PII risk is highest here).
# Based on events where avg smallest face height < 30px or crowd density > 20 faces/image.
WIDER_FACE_HARD_EVENTS = {
    0,   # Parade
    3,   # Riot
    5,   # Car_Accident
    10,  # People_Marching
    18,  # Concerts
    21,  # Festival
    23,  # Shoppers
    24,  # Soldier_Firing
    25,  # Soldier_Patrol
    26,  # Soldier_Drilling
    29,  # Students_Schoolkids
    33,  # Running
    34,  # Baseball
    35,  # Basketball
    36,  # Football
    37,  # Soccer
    38,  # Tennis
    39,  # Ice_Skating
    40,  # Gymnastics
    41,  # Swimming
    44,  # Aerobics
    46,  # Jockey
    47,  # Matador_Bullfighter
    50,  # Celebration_Or_Party
    53,  # Raid
    54,  # Rescue
    58,  # Hockey
    61,  # Street_Battle
}

# Mutation schedule v4: Phase 9 loss weights LOCKED as default.
# Experiment #0 is a CONTROL — runs DEFAULT_CONFIG with zero mutations.
# Each subsequent mutation changes ONE dimension at a time.
# Round 1+2 proved: resolution > everything, loss weight changes HURT recall,
# batch=1 BN noise + too few epochs caused regression after epoch 4.
MUTATION_SCHEDULE = [
    # ── #0: Control run — DEFAULT_CONFIG, no mutations ─────────────────
    # MUST come first: validates the pipeline reproduces Phase 9 recall.
    # If control fails, there's a pipeline bug; mutations won't help.
    {"name": "control_baseline"},
    # ── Augmentation strength ──────────────────────────────────────────
    {"name": "more_copypaste", "copy_paste": 0.5},
    {"name": "light_aug", "mixup": 0.0, "copy_paste": 0.1, "scale": 0.3},
    {"name": "heavy_mosaic", "mosaic": 1.0, "mixup": 0.3, "scale": 0.7},
    # ── LR schedule ─────────────────────────────────────────────────────
    {"name": "lr_warmer", "lr0": 0.0008, "lrf": 0.02},
    {"name": "lr_colder", "lr0": 0.0003, "lrf": 0.005},
    # ── Multi-scale variants ───────────────────────────────────────────
    {"name": "ms_centered_1120", "imgsz": 1120, "multi_scale": 0.33, "batch": 1},  # 736-1504
    {"name": "ms_high_1280", "imgsz": 1280, "multi_scale": 0.25, "batch": 1},     # 960-1632, ~23GB peak
    {"name": "fixed_1280", "imgsz": 1280, "multi_scale": 0.0, "batch": 1},        # fixed 1280
    # ── Close-mosaic timing ────────────────────────────────────────────
    {"name": "close_mosaic_8", "close_mosaic": 8},
    {"name": "close_mosaic_0", "close_mosaic": 0},
    # ── IOU threshold ──────────────────────────────────────────────────
    {"name": "iou_06", "iou": 0.6},
    {"name": "iou_05", "iou": 0.5},
    # ── Copy-paste + IOU combos (keep Phase 9 loss weights) ────────────
    {"name": "recall_copypaste_iou", "copy_paste": 0.5,
     "close_mosaic": 8, "iou": 0.6},
    {"name": "highres_copypaste", "imgsz": 1120, "multi_scale": 0.33,
     "copy_paste": 0.5},
    # ── Mild loss weight exploration (small deltas from Phase 9) ───────
    # Phase 9: box=7.5, cls=0.5. Only small nudges — large changes hurt.
    {"name": "box8_cls04", "box": 8.0, "cls": 0.4},
    {"name": "box9_cls04", "box": 9.0, "cls": 0.4},
    # ── Max-recall combos (PII: missing a face = privacy violation) ────
    {"name": "iou_045", "iou": 0.45},  # More inclusive matching than iou_05
    {"name": "max_recall_combo", "copy_paste": 0.5, "iou": 0.45,
     "close_mosaic": 8},  # All recall knobs together, Phase 9 loss weights
    # ── YOLOv11m architecture trials (fresh COCO pretrained, different C3k2 backbone) ──
    # YOLOv11m has improved small-object detection vs YOLOv8m — relevant for dense small faces.
    # Starts from COCO pretrained (cannot transfer Phase 9 YOLOv8m weights).
    # Needs longer budget than fine-tuning runs to converge from scratch.
    {"name": "yolo11m_baseline", "model_variant": "yolo11m",
     "epochs": 30, "lr0": 0.001, "lrf": 0.01},  # Standard COCO-→-WIDER transfer
    {"name": "yolo11m_recall_iou", "model_variant": "yolo11m",
     "epochs": 30, "lr0": 0.001, "iou": 0.45, "copy_paste": 0.5},  # Recall focus
    {"name": "yolo11m_highres", "model_variant": "yolo11m",
     "epochs": 30, "imgsz": 1120, "multi_scale": 0.33, "batch": 1,
     "lr0": 0.001},  # High-res small face emphasis
]


# ═══════════════════════════════════════════════════════════════════════════
# PROGRAM.MD EQUIVALENT (teaches LLM about constraints)
# ═══════════════════════════════════════════════════════════════════════════

PROGRAM_CONTEXT = """
# Face Detection Autoresearch — Program Context

## Model
- Architecture: YOLOv8m-P2 (43.6M params, P2 detection head for small faces)
- Task: Face detection on WIDER Face (+CrowdHuman +MAFA when merged)
- Val set: WIDER Face validation (3,222 images, 39,111 face annotations)

## Hardware
- GPU: RTX 3090 Ti (24GB VRAM) — full 24 GB available (Qwen stopped during training)
- RAM: 64 GB — cache=ram fits entire WIDER train set (~1.6 GB)
- Multi-scale sweet spot: imgsz=960, multi_scale=0.33, batch=2, cache=ram
  - Trains at 643–1280px per batch (random each step)
  - Peak VRAM ~16 GB at 1280px/batch=2 — safe headroom
  - batch=2 gives clean BatchNorm statistics (batch=1 was instance-norm noise)
  - nbs=64 gradient accumulation → effective batch=64
  - cache=ram = zero I/O penalty at any resolution

## Baselines to beat
- Phase 5 (champion): mAP50=0.798, Recall=0.716, Precision=0.889, F1=0.793
  - Trained at 1280px, batch=4, 200 epochs, cache=false
- Phase 9 (latest):   mAP50=0.814, Recall=0.729, Precision=0.883, F1=0.797
  - Trained at 960px, batch=4, 50 epochs, cache=ram, close_mosaic=10
  - Config: box=7.5, cls=0.5, dfl=1.5, lr0=0.0005, lrf=0.01, iou=0.7
  - Augmentation: mosaic=1.0, mixup=0.1, copy_paste=0.3, scale=0.5, hsv_s=0.5, hsv_v=0.3

## CRITICAL INSIGHTS FROM ROUNDS 1-2 (22 experiments, 0 kept)
- Resolution dominates all other hyperparameters
- 640px experiments ALL scored mAP50 in [0.719, 0.743] regardless of loss/LR/aug
- 800px scored 0.792, 960px scored 0.797 — with just 8 epochs!
- The P2 head (stride=4) specifically needs high resolution for small faces
- Phase 9 was trained AND evaluated at 960px — autoresearch must match this
- Changing loss weights from Phase 9 (box=7.5, cls=0.5) ALWAYS hurt recall
  - box=10/cls=0.3: R=0.695-0.711 vs Phase 9 R=0.729 — consistent -0.02 to -0.03
  - Higher box weight suppresses marginal detections — opposite of PII recall
- 8-15 epochs too few: model peaks at ep 4 then regresses (BN noise + multi-scale)
- batch=1 degrades BatchNorm → use batch=2 with multi_scale=0.33 (peak 1280px)
- Evaluation must use peak recall from results.csv, not final-epoch metrics

## Constraints
- Each experiment: ~20 min at 960px/batch=2, 30 epochs
- Must NOT regress mAP50 below Phase 5 baseline (0.798)
- Must NOT regress recall below Phase 9 baseline (0.729)
- CHAMPION METRIC IS RECALL — this is a PII blurring model; a missed face is a privacy violation
- Prefer recall improvements aggressively; small mAP50 drops are acceptable
- close_mosaic should be >= 3 (turn off mosaic before final convergence)
- DO NOT override Phase 9 loss weights (box=7.5, cls=0.5, dfl=1.5) with large deltas

## Loss weights (what they control)
- box: Bounding box regression loss weight. Higher = tighter boxes
- cls: Classification loss weight. Lower for single-class tasks
- dfl: Distribution focal loss weight. Controls quality of box edges

## What worked before (Phase 9 recipe)
- Gradient clipping (max_norm=10.0) prevents NaN explosion
- Copy-paste augmentation (flip mode) improves small face recall
- Cosine LR schedule with 3-epoch warm-up
- AdamW optimizer with weight_decay=0.0005
- NBS=64 (gradient accumulation to effective batch 64)
- cache=ram eliminates I/O bottleneck
- close_mosaic=10 stabilizes final epochs

## What to explore
- copy_paste=0.5 (more synthetic small faces — best single recall knob)
- multi_scale=0.33 at imgsz=1120 (range 736–1504, peak ~20 GB)
- multi_scale=0.25 at imgsz=1280 (range 960–1632, peak ~23 GB — tight)
- close_mosaic timing (5 vs 8)
- IOU threshold 0.5-0.6 (catches overlapping faces in crowds)
- Small loss weight nudges only (box=8-9, cls=0.4) — NOT large jumps
- Lower IOU threshold (0.5-0.6 vs 0.7) to catch more overlapping faces
"""


# ═══════════════════════════════════════════════════════════════════════════
# DATA TYPES
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ExperimentResult:
    iteration: int
    name: str
    config: dict
    metrics: dict = field(default_factory=dict)
    duration_sec: float = 0.0
    kept: bool = False
    reason: str = ""
    weights_path: str = ""
    error: str = ""
    vram_peak_mb: float = 0.0
    timestamp: str = ""

    def delta_vs(self, baseline: dict, label: str = "p9") -> dict:
        return {
            f"Δ{label}_mAP50": self.metrics.get("mAP50", 0) - baseline.get("mAP50", 0),
            f"Δ{label}_recall": self.metrics.get("recall", 0) - baseline.get("recall", 0),
            f"Δ{label}_precision": self.metrics.get("precision", 0) - baseline.get("precision", 0),
            f"Δ{label}_F1": self.metrics.get("F1", 0) - baseline.get("F1", 0),
        }


# ═══════════════════════════════════════════════════════════════════════════
# LLM MUTATION (optional)
# ═══════════════════════════════════════════════════════════════════════════

def _load_program_context() -> str:
    """Load program.md from disk, falling back to inline constant."""
    md_path = Path(__file__).parent / "program.md"
    if md_path.exists():
        try:
            return md_path.read_text()
        except Exception:
            pass
    return PROGRAM_CONTEXT


# ═══════════════════════════════════════════════════════════════════════════
# EPOCH WATCHER — live per-epoch metrics to Redis + GitLab
# Runs as a daemon thread alongside model.train(); never crashes training.
# ═══════════════════════════════════════════════════════════════════════════

class EpochWatcher:
    """Monitor results.csv during training; publish per-epoch metrics to Redis and GitLab.

    Redis channel ``shml:autoresearch:progress`` receives a JSON message every epoch::

        {"type": "epoch", "experiment": "...", "iteration": N, "epoch": E,
         "recall": 0.7xx, "mAP50": 0.8xx, "box_loss": 0.0xx}

    GitLab issue (if ``gitlab_issue_iid`` provided) receives a collapsible table
    comment every ``GITLAB_EVERY`` epochs so the ticket shows live training progress.
    """

    GITLAB_EVERY = 5  # Post GitLab comment every N epochs

    def __init__(
        self,
        csv_path: Path,
        experiment_name: str,
        iteration: int,
        gitlab_issue_iid: int | None = None,
    ):
        self.csv_path = csv_path
        self.experiment_name = experiment_name
        self.iteration = iteration
        self.gitlab_issue_iid = gitlab_issue_iid
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_epoch = -1
        self._epoch_buffer: list[dict] = []
        # Path to gitlab_utils.py; resolved once at construction time
        self._gitlab_path = Path(__file__).parents[3] / "scripts" / "platform"

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._watch, daemon=True,
            name=f"epoch-watcher-iter{self.iteration}",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=8)

    def _watch(self) -> None:
        poll_sec = 30  # Check YOLO's results.csv every 30 seconds
        while not self._stop.is_set():
            self._stop.wait(poll_sec)  # Wakes immediately on stop()
            if not self.csv_path.exists():
                continue
            try:
                lines = self.csv_path.read_text().strip().splitlines()
                if len(lines) < 2:
                    continue
                header = [h.strip() for h in lines[0].split(",")]
                col_map = {name: idx for idx, name in enumerate(header)}
                r_col = col_map.get("metrics/recall(B)")
                m50_col = col_map.get("metrics/mAP50(B)")
                ep_col = col_map.get("epoch")
                box_col = col_map.get("train/box_loss")
                if r_col is None or ep_col is None:
                    continue
                new_rows: list[dict] = []
                for line in lines[1:]:
                    cols = line.split(",")
                    try:
                        ep = int(float(cols[ep_col].strip()))
                        if ep <= self._last_epoch:
                            continue
                        self._last_epoch = ep
                        row = {
                            "epoch": ep,
                            "recall": float(cols[r_col].strip()),
                            "mAP50": float(cols[m50_col].strip()) if m50_col else 0.0,
                            "box_loss": float(cols[box_col].strip()) if box_col else 0.0,
                        }
                        new_rows.append(row)
                        self._epoch_buffer.append(row)
                        # Redis: emit every epoch (lightweight JSON)
                        publish_event("shml:autoresearch:progress", {
                            "type": "epoch",
                            "experiment": self.experiment_name,
                            "iteration": self.iteration,
                            **row,
                        })
                    except (IndexError, ValueError):
                        continue
                # GitLab: batch-post every GITLAB_EVERY epochs
                if (new_rows and self.gitlab_issue_iid
                        and len(self._epoch_buffer) % self.GITLAB_EVERY == 0):
                    self._push_to_gitlab(self._epoch_buffer[-self.GITLAB_EVERY:])
            except Exception:
                pass  # Watcher must never crash training

    def _push_to_gitlab(self, rows: list[dict]) -> None:
        """Append 5-epoch training table as a GitLab issue comment."""
        if not rows or not self.gitlab_issue_iid:
            return
        try:
            if str(self._gitlab_path) not in sys.path:
                sys.path.insert(0, str(self._gitlab_path))
            import gitlab_utils
            epoch_start = rows[0]["epoch"]
            epoch_end = rows[-1]["epoch"]
            table = "\n".join(
                f"| {r['epoch']} | {r['recall']:.4f} | {r['mAP50']:.4f} | {r['box_loss']:.4f} |"
                for r in rows
            )
            comment = (
                f"### 📊 Live Training — `{self.experiment_name}` "
                f"(epochs {epoch_start}–{epoch_end})\n\n"
                "| Epoch | Recall | mAP50 | Box Loss |\n"
                "|-------|--------|-------|----------|\n"
                f"{table}\n\n"
                "> 🎯 PII target: **recall > 0.760** (floor: mAP50 ≥ 0.798)"
            )
            gitlab_utils.add_issue_comment(self.gitlab_issue_iid, comment)
        except Exception:
            pass  # GitLab post must never crash training


def llm_propose_mutation(
    llm_url: str,
    history: list[ExperimentResult],
    current_best: dict,
    model: str = "qwen-coding",
) -> dict:
    """Ask Qwen3.5 (or another local LLM) to propose the next hyperparameter mutation."""

    history_summary = []
    for r in history[-10:]:  # Last 10 experiments
        entry = {
            "name": r.name,
            "config_changes": {k: v for k, v in r.config.items() if k != "name"},
            "mAP50": r.metrics.get("mAP50", 0),
            "recall": r.metrics.get("recall", 0),
            "kept": r.kept,
            "reason": r.reason,
        }
        history_summary.append(entry)

    program_ctx = _load_program_context()

    prompt = f"""
{program_ctx}

## Experiment History (most recent)
{json.dumps(history_summary, indent=2)}

## Current Best
{json.dumps(current_best, indent=2)}

## Task
Propose ONE new hyperparameter configuration to try next.
Return ONLY a JSON object with the changed keys and a "name" field.
Example: {{"name": "my_experiment", "box": 12.0, "lr0": 0.0003}}

Think about:
1. What patterns do you see in successful vs failed experiments?
2. What combinations haven't been tried?
3. How can we push recall higher without crashing mAP50?

Stage 1 code-level hints — add "action" key to select a predefined code path:
- "action": "lower_conf_threshold"  → propose training changes that improve low-conf detection (inference already at conf=0.1)
- "action": "wider_iou_eval"        → evaluate at iou=0.45 (more inclusive crowd overlap matching)
- "action": "hard_event_focus"      → increase copy_paste specifically for WIDER_FACE_HARD_EVENTS categories (concerts/sports/riots)
- "action": "lr_warmup_extend"      → warmup_epochs=5 (longer warmup for large multi-scale range)
- "action": "mosaic_only_early"     → mosaic=1.0 for first 80% duration, copy_paste=0.0 early to stabilize
If you propose an action, include BOTH the action key AND any relevant numeric hyperparam changes.

Return the JSON object only, no explanation.
"""

    try:
        resp = requests.post(
            f"{llm_url}/chat/completions",
            json={
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are an expert ML hyperparameter optimization agent specializing "
                            "in YOLO face detection. Be precise and data-driven. Return ONLY "
                            "the requested JSON object — no markdown fences, no explanation."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 2048,  # Qwen3.5 thinks first, needs budget
                "temperature": 0.6,
            },
            timeout=120,  # Thinking mode takes longer
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]

        # Extract JSON from response
        import re
        json_match = re.search(r'\{[^{}]+\}', content, re.DOTALL)
        if json_match:
            mutation = json.loads(json_match.group())
            if "name" not in mutation:
                mutation["name"] = f"llm_iter{len(history)+1}"
            return mutation
    except Exception as e:
        print(f"  [llm] Mutation proposal failed: {e}")

    return {}


# ═══════════════════════════════════════════════════════════════════════════
# TRAINING RUNNER
# ═══════════════════════════════════════════════════════════════════════════

def run_experiment(
    weights_path: str,
    dataset_dir: str,
    config: dict,
    output_dir: Path,
    run_name: str,
    device: int = 0,
    time_budget_sec: float = 300,
    gitlab_issue_iid: int | None = None,
) -> ExperimentResult:
    """Run a single constrained training experiment."""

    result = ExperimentResult(
        iteration=0,
        name=config.get("name", run_name),
        config={k: v for k, v in config.items() if k != "name"},
        timestamp=datetime.now().isoformat(),
    )

    # Merge config with defaults — strip non-YOLO keys before passing to trainer
    _NON_YOLO_KEYS = {"name", "model_variant"}
    full_config = {**DEFAULT_CONFIG, **{k: v for k, v in config.items() if k not in _NON_YOLO_KEYS}}

    # model_variant: "yolo11m" → fresh COCO-pretrained YOLOv11m (different arch from YOLOv8m,
    # cannot transfer Phase 9 weights).  All other experiments fine-tune from weights_path.
    model_variant = config.get("model_variant")
    _model_source = f"yolo11m.pt" if model_variant == "yolo11m" else weights_path

    print(f"\n  ┌─ Experiment: {result.name}")
    print(f"  │  Model:  {_model_source}")
    print(f"  │  Config: {json.dumps({k: v for k, v in config.items() if k not in _NON_YOLO_KEYS}, indent=None)}")
    print(f"  │  Budget: {time_budget_sec/60:.0f}min | {full_config['imgsz']}px batch={full_config['batch']}")

    _watcher: EpochWatcher | None = None  # started once training begins

    try:
        model = YOLO(_model_source)

        t0 = time.time()

        # ── Epoch watcher: tail results.csv → Redis pub + GitLab live tables ──
        _watcher = EpochWatcher(
            csv_path=output_dir / run_name / "results.csv",
            experiment_name=result.name,
            iteration=result.iteration,
            gitlab_issue_iid=gitlab_issue_iid,
        )
        _watcher.start()

        results = model.train(
            data=f"{dataset_dir}/data.yaml",
            imgsz=full_config["imgsz"],
            epochs=full_config["epochs"],
            batch=full_config["batch"],
            patience=full_config["patience"],
            optimizer="AdamW",
            lr0=full_config["lr0"],
            lrf=full_config["lrf"],
            weight_decay=0.0005,
            cos_lr=True,
            warmup_epochs=full_config["warmup_epochs"],
            warmup_bias_lr=0.05,
            nbs=64,
            # Augmentation
            mosaic=full_config["mosaic"],
            mixup=full_config["mixup"],
            copy_paste=full_config["copy_paste"],
            degrees=full_config["degrees"],
            translate=full_config["translate"],
            scale=full_config["scale"],
            fliplr=full_config["fliplr"],
            hsv_h=full_config["hsv_h"],
            hsv_s=full_config["hsv_s"],
            hsv_v=full_config["hsv_v"],
            close_mosaic=full_config["close_mosaic"],
            label_smoothing=full_config.get("label_smoothing", 0.0),
            # Loss weights
            box=full_config["box"],
            cls=full_config["cls"],
            dfl=full_config["dfl"],
            # Detection
            max_det=full_config["max_det"],
            iou=full_config["iou"],
            multi_scale=full_config.get("multi_scale", False),
            copy_paste_mode="flip",
            # Budget: stop after time_budget_sec regardless of remaining epochs.
            # YOLO's `time` param (hours) overrides `epochs` gracefully — saves best.pt.
            time=time_budget_sec / 3600,
            # Memory
            rect=full_config.get("rect", True),
            cache=full_config.get("cache", "ram"),
            # Hardware
            device=device,
            workers=2,
            amp=True,
            # Output
            project=str(output_dir),
            name=run_name,
            exist_ok=True,
            verbose=False,
            plots=False,
            save=True,
        )

        result.duration_sec = time.time() - t0

        if results:
            result.metrics = {
                "mAP50": float(results.results_dict.get("metrics/mAP50(B)", 0)),
                "mAP50_95": float(results.results_dict.get("metrics/mAP50-95(B)", 0)),
                "precision": float(results.results_dict.get("metrics/precision(B)", 0)),
                "recall": float(results.results_dict.get("metrics/recall(B)", 0)),
            }
            p, r = result.metrics["precision"], result.metrics["recall"]
            result.metrics["F1"] = 2 * p * r / (p + r) if (p + r) > 0 else 0

            # ── Best-in-run recall from results.csv ────────────────────
            # YOLO saves best.pt by fitness (0.1*mAP50 + 0.9*mAP50-95),
            # NOT by recall.  For PII, we need the peak recall from any
            # epoch in this run.  Parse results.csv to find it.
            results_csv = output_dir / run_name / "results.csv"
            peak = _parse_peak_recall_from_csv(results_csv)
            if peak and peak["recall"] > result.metrics["recall"]:
                print(f"  │  Peak recall {peak['recall']:.4f} (ep {peak['epoch']}) "
                      f"> final {result.metrics['recall']:.4f} — using peak")
                result.metrics["recall"] = peak["recall"]
                result.metrics["precision"] = peak["precision"]
                result.metrics["mAP50"] = peak["mAP50"]
                result.metrics["mAP50_95"] = peak["mAP50_95"]
                result.metrics["peak_epoch"] = peak["epoch"]
                p, r = result.metrics["precision"], result.metrics["recall"]
                result.metrics["F1"] = 2 * p * r / (p + r) if (p + r) > 0 else 0

            # WIDER Hard subset eval — tracks recall on crowd/sports scenes (PII critical)
            hard = evaluate_wider_hard(
                weights_path=str(output_dir / run_name / "weights" / "best.pt"),
                dataset_dir=Path(dataset_dir),
                device=device,
                imgsz=full_config.get("imgsz", 960),
            )
            result.metrics.update(hard)

        # Find weights
        best_wt = output_dir / run_name / "weights" / "best.pt"
        last_wt = output_dir / run_name / "weights" / "last.pt"
        result.weights_path = str(best_wt if best_wt.exists() else last_wt if last_wt.exists() else "")

        if torch.cuda.is_available():
            result.vram_peak_mb = torch.cuda.max_memory_allocated(0) / 1e6
            torch.cuda.reset_peak_memory_stats(0)

    except torch.cuda.OutOfMemoryError:
        result.error = "OOM"
        result.reason = "Out of memory — config too aggressive for 24GB"
    except Exception as e:
        result.error = str(e)
        result.reason = f"Training error: {e}"
    finally:
        # Stop epoch watcher before GPU cleanup
        if _watcher is not None:
            _watcher.stop()
        # Cleanup
        try:
            del model
        except Exception:
            pass
        gc.collect()
        torch.cuda.empty_cache()
        time.sleep(2)

    return result


def _parse_peak_recall_from_csv(csv_path: Path) -> dict | None:
    """Parse results.csv and return metrics from the epoch with highest recall.

    YOLO results.csv has columns (with leading spaces in headers):
      epoch, train/box_loss, ..., metrics/precision(B), metrics/recall(B),
      metrics/mAP50(B), metrics/mAP50-95(B)
    Some runs include a 'time' column at position 2, shifting all indices.
    We detect this by checking the header row.
    """
    if not csv_path.exists():
        return None
    try:
        lines = csv_path.read_text().strip().splitlines()
        if len(lines) < 2:
            return None
        header = [h.strip() for h in lines[0].split(",")]
        # Find column indices by name (robust to column order)
        col_map = {name: idx for idx, name in enumerate(header)}
        r_col = col_map.get("metrics/recall(B)")
        p_col = col_map.get("metrics/precision(B)")
        m50_col = col_map.get("metrics/mAP50(B)")
        m5095_col = col_map.get("metrics/mAP50-95(B)")
        ep_col = col_map.get("epoch")
        if r_col is None:
            return None

        best_recall = -1.0
        best_row = None
        for line in lines[1:]:
            cols = line.split(",")
            try:
                recall = float(cols[r_col].strip())
                if recall > best_recall:
                    best_recall = recall
                    best_row = cols
            except (IndexError, ValueError):
                continue
        if best_row is None:
            return None
        return {
            "recall": float(best_row[r_col].strip()),
            "precision": float(best_row[p_col].strip()) if p_col is not None else 0.0,
            "mAP50": float(best_row[m50_col].strip()) if m50_col is not None else 0.0,
            "mAP50_95": float(best_row[m5095_col].strip()) if m5095_col is not None else 0.0,
            "epoch": int(float(best_row[ep_col].strip())) if ep_col is not None else -1,
        }
    except Exception as e:
        print(f"  [csv] Failed to parse peak recall from {csv_path}: {e}")
        return None


def evaluate_result(
    result: ExperimentResult,
    best_so_far: dict,
) -> bool:
    """Decide whether to KEEP or DISCARD this experiment.

    Returns True if the result should be kept (improves over best_so_far).
    Uses best-in-run recall (peak across all epochs) rather than final-epoch.
    """
    if result.error:
        result.kept = False
        result.reason = f"Error: {result.error}"
        return False

    m = result.metrics
    if not m:
        result.kept = False
        result.reason = "No metrics returned"
        return False

    # Gate: must not regress below Phase 5 baselines
    if m.get("mAP50", 0) < BASELINE_PHASE5["mAP50"]:
        result.kept = False
        result.reason = f"mAP50 {m['mAP50']:.4f} < Phase 5 floor {BASELINE_PHASE5['mAP50']:.4f}"
        return False

    if m.get("recall", 0) < BASELINE_PHASE9["recall"]:
        result.kept = False
        result.reason = f"Recall {m['recall']:.4f} < Phase 9 floor {BASELINE_PHASE9['recall']:.4f}"
        return False

    # Primary metric: must improve over current best
    current_primary = m.get(CHAMPION_METRIC, 0)
    best_primary = best_so_far.get(CHAMPION_METRIC, 0)

    if current_primary > best_primary:
        result.kept = True
        result.reason = (
            f"Improved {CHAMPION_METRIC}: {current_primary:.4f} > {best_primary:.4f} "
            f"(Δ = +{current_primary - best_primary:.4f})"
        )
        return True
    elif current_primary == best_primary:
        # Tiebreak on secondary metric
        current_secondary = m.get(SECONDARY_METRIC, 0)
        best_secondary = best_so_far.get(SECONDARY_METRIC, 0)
        if current_secondary > best_secondary:
            result.kept = True
            result.reason = (
                f"Tied on {CHAMPION_METRIC}, improved {SECONDARY_METRIC}: "
                f"{current_secondary:.4f} > {best_secondary:.4f}"
            )
            return True

    result.kept = False
    result.reason = (
        f"{CHAMPION_METRIC} {current_primary:.4f} ≤ best {best_primary:.4f} "
        f"(no improvement)"
    )
    return False


# ═══════════════════════════════════════════════════════════════════════════
# JOURNAL
# ═══════════════════════════════════════════════════════════════════════════

def write_journal(
    results: list[ExperimentResult],
    best: dict,
    journal_path: Path,
) -> None:
    """Write human-readable experiment journal."""

    lines = [
        "# Autoresearch Face Detection — Experiment Journal",
        f"Generated: {datetime.now().isoformat()}",
        f"Total experiments: {len(results)}",
        f"Best result: {json.dumps(best, indent=2)}",
        "",
        "## Baselines",
        f"- Phase 5: mAP50={BASELINE_PHASE5['mAP50']}, Recall={BASELINE_PHASE5['recall']}",
        f"- Phase 9: mAP50={BASELINE_PHASE9['mAP50']}, Recall={BASELINE_PHASE9['recall']}",
        "",
        "## Experiments",
        "",
    ]

    for r in results:
        status = "✓ KEPT" if r.kept else "✗ DISCARDED"
        deltas = r.delta_vs(BASELINE_PHASE9, "p9")
        lines.append(f"### [{r.iteration}] {r.name} — {status}")
        lines.append(f"- **Config:** `{json.dumps(r.config)}`")
        if r.metrics:
            lines.append(
                f"- **Results:** mAP50={r.metrics.get('mAP50', 0):.4f} "
                f"Recall={r.metrics.get('recall', 0):.4f} "
                f"Precision={r.metrics.get('precision', 0):.4f} "
                f"F1={r.metrics.get('F1', 0):.4f}"
            )
            lines.append(
                f"- **vs Phase 9:** ΔmAP50={deltas.get('Δp9_mAP50', 0):+.4f} "
                f"ΔRecall={deltas.get('Δp9_recall', 0):+.4f}"
            )
        lines.append(f"- **Duration:** {r.duration_sec/60:.1f} min")
        lines.append(f"- **Decision:** {r.reason}")
        if r.error:
            lines.append(f"- **Error:** {r.error}")
        lines.append("")

    journal_path.parent.mkdir(parents=True, exist_ok=True)
    with open(journal_path, "w") as f:
        f.write("\n".join(lines))
    print(f"[journal] Saved: {journal_path}")


# ═══════════════════════════════════════════════════════════════════════════
# OBSIDIAN VAULT INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════

_OBSIDIAN_VAULT = Path(__file__).parents[3] / "docs" / "obsidian-vault"
_OBSIDIAN_EXPERIMENTS = _OBSIDIAN_VAULT / "20-Experiments" / "autoresearch"


def _write_obsidian_note(
    result: ExperimentResult,
    is_champion: bool,
    run_timestamp: str,
) -> None:
    """Write per-iteration Obsidian note for noteworthy results.

    Gate: write only when the result is KEPT (new champion) OR when recall
    beats the Phase 9 floor (recall > 0.729), so the vault only captures
    meaningful signal.
    """
    recall = result.metrics.get("recall", 0)
    beats_baseline = recall > BASELINE_PHASE9["recall"]

    if not (result.kept or beats_baseline):
        return  # Nothing noteworthy — skip

    try:
        _OBSIDIAN_EXPERIMENTS.mkdir(parents=True, exist_ok=True)

        status_tag = "new-champion" if is_champion else "beats-baseline"
        slug = f"iter-{result.iteration:03d}-{run_timestamp}"
        note_path = _OBSIDIAN_EXPERIMENTS / f"{slug}.md"

        deltas = result.delta_vs(BASELINE_PHASE9, "p9")
        mAP50 = result.metrics.get("mAP50", 0)
        precision = result.metrics.get("precision", 0)
        f1 = result.metrics.get("F1", 0)

        lines = [
            "---",
            f"tags: [autoresearch, face-detection, {status_tag}]",
            f"created: {datetime.now().isoformat()}",
            f"run: {run_timestamp}",
            f"iteration: {result.iteration}",
            f"recall: {recall:.4f}",
            f"mAP50: {mAP50:.4f}",
            f"champion: {is_champion}",
            "---",
            "",
            f"# Autoresearch Iter {result.iteration:03d} — {'🏆 NEW CHAMPION' if is_champion else '✓ Beats Baseline'}",
            "",
            "## Metrics",
            "",
            f"| Metric | Value | Δ Phase 9 |",
            f"|--------|-------|-----------|",
            f"| Recall | {recall:.4f} | {deltas.get('Δp9_recall', 0):+.4f} |",
            f"| mAP50 | {mAP50:.4f} | {deltas.get('Δp9_mAP50', 0):+.4f} |",
            f"| Precision | {precision:.4f} | {deltas.get('Δp9_precision', 0):+.4f} |",
            f"| F1 | {f1:.4f} | {deltas.get('Δp9_F1', 0):+.4f} |",
            "",
            "## Baselines",
            "",
            f"- Phase 5: recall={BASELINE_PHASE5['recall']}, mAP50={BASELINE_PHASE5['mAP50']}",
            f"- Phase 9: recall={BASELINE_PHASE9['recall']}, mAP50={BASELINE_PHASE9['mAP50']}",
            "",
            "## Config (hyperparams)",
            "",
            f"```json\n{json.dumps(result.config, indent=2)}\n```",
            "",
            "## Decision",
            "",
            f"- **Status:** {'KEPT' if result.kept else 'DISCARDED'}",
            f"- **Reason:** {result.reason}",
            f"- **Duration:** {result.duration_sec / 60:.1f} min",
        ]
        if result.weights_path:
            lines += ["", f"- **Weights:** `{result.weights_path}`"]

        note_path.write_text("\n".join(lines))

        # ── Update INDEX.md ─────────────────────────────────────────────
        index_path = _OBSIDIAN_EXPERIMENTS / "INDEX.md"
        entry = (
            f"| [{slug}]({slug}.md) | {result.iteration} | {recall:.4f} | "
            f"{mAP50:.4f} | {'🏆' if is_champion else '✓'} | {run_timestamp} |"
        )
        if index_path.exists():
            existing = index_path.read_text()
            index_path.write_text(existing.rstrip() + "\n" + entry + "\n")
        else:
            header = (
                "# Autoresearch Experiment Index\n\n"
                "| Note | Iter | Recall | mAP50 | Status | Run |\n"
                "|------|------|--------|-------|--------|-----|\n"
            )
            index_path.write_text(header + entry + "\n")

        print(f"[obsidian] Wrote note: {note_path.name}")

        # ── Optional Telegram notification ──────────────────────────────
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        if bot_token and chat_id:
            try:
                status_icon = "🏆" if is_champion else "✅"
                msg = (
                    f"{status_icon} <b>Autoresearch</b> — Iter {result.iteration:03d}"
                    f"\nRecall: <code>{recall:.4f}</code>  mAP50: <code>{mAP50:.4f}</code>"
                    f"\nΔp9 recall: <code>{deltas.get('Δp9_recall', 0):+.4f}</code>"
                    f"\nNote: <code>{note_path.name}</code>"
                )
                requests.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    data={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
                    timeout=5,
                )
            except Exception as te:
                print(f"[obsidian] Telegram notify failed (non-fatal): {te}")

    except Exception as e:  # vault write must never crash the research loop
        print(f"[obsidian] Warning: could not write note: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# WIDER FACE HARD SUBSET EVALUATION
# ═══════════════════════════════════════════════════════════════════════════

def evaluate_wider_hard(
    weights_path: str,
    dataset_dir: Path,
    device: int = 0,
    imgsz: int = 960,
) -> dict:
    """Secondary val pass on WIDER Face Hard events only.

    Filters val images to WIDER_FACE_HARD_EVENTS (crowd/sports/density-heavy
    scenes where PII risk is highest) and runs model.val() on that subset.
    Returns hard_recall, hard_mAP50 and hard_n_images.
    """
    import tempfile
    from ultralytics import YOLO as _YOLO

    val_img_dir = dataset_dir / "images" / "val"
    val_lbl_dir = dataset_dir / "labels" / "val"

    hard_imgs = [
        p for p in sorted(val_img_dir.glob("*.jpg"))
        if (m := re.match(r'^(\d+)--', p.name)) and int(m.group(1)) in WIDER_FACE_HARD_EVENTS
    ]
    total_val = sum(1 for _ in val_img_dir.glob("*.jpg"))
    print(f"  [hard-eval] {len(hard_imgs)}/{total_val} hard-event images ({100*len(hard_imgs)/max(total_val,1):.0f}%)")
    if not hard_imgs:
        return {}

    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "images" / "val").mkdir(parents=True)
            (tmp_path / "labels" / "val").mkdir(parents=True)
            for img in hard_imgs:
                lbl = val_lbl_dir / img.with_suffix(".txt").name
                os.symlink(img, tmp_path / "images" / "val" / img.name)
                if lbl.exists():
                    os.symlink(lbl, tmp_path / "labels" / "val" / lbl.name)
            data_yaml = tmp_path / "data_hard.yaml"
            data_yaml.write_text(
                f"path: {tmp}\ntrain: images/val\nval: images/val\nnc: 1\nnames:\n  0: face\n"
            )
            model = _YOLO(weights_path)
            r = model.val(
                data=str(data_yaml),
                imgsz=imgsz,
                conf=0.001,  # standard: low conf so full PR curve is evaluated
                iou=0.6,
                max_det=1000,
                device=device,
                verbose=False,
                plots=False,
            )
            hard_recall = float(r.results_dict.get("metrics/recall(B)", 0))
            hard_map50  = float(r.results_dict.get("metrics/mAP50(B)", 0))
            print(f"  [hard-eval] recall={hard_recall:.4f}  mAP50={hard_map50:.4f}")
            return {"hard_recall": hard_recall, "hard_mAP50": hard_map50, "hard_n_images": len(hard_imgs)}
    except Exception as e:
        print(f"  [hard-eval] failed: {e}")
        return {}


# ═══════════════════════════════════════════════════════════════════════════
# FIFTYONE BRAIN ANALYSIS (optional — failure analysis on kept experiments)
# ═══════════════════════════════════════════════════════════════════════════

def analyze_failures_fiftyone(
    weights_path: str,
    dataset_yaml: str,
    run_name: str,
    device: int = 0,
) -> bool:
    """Run FiftyOne Brain analysis on a kept checkpoint.

    Computes hardness + uniqueness on val set false-negatives to identify
    which images most confuse the model (small/occluded face clusters).

    Returns True on success, False if fiftyone is unavailable/fails.
    """
    try:
        import fiftyone as fo
        import fiftyone.brain as fob
        from ultralytics import YOLO as _YOLO
    except ImportError:
        print("  [fiftyone] not available — skipping brain analysis")
        return False

    print(f"  [fiftyone] Starting failure analysis for: {run_name}")
    try:
        # Load dataset
        dataset_path = Path(dataset_yaml).parent
        val_images = dataset_path / "images" / "val"
        if not val_images.exists():
            print(f"  [fiftyone] val images not found at {val_images}")
            return False

        # Load model and predict
        model = _YOLO(weights_path)
        results = model.predict(
            source=str(val_images),
            conf=0.25,
            device=device,
            verbose=False,
            stream=True,
        )

        # Build FiftyOne dataset from false negatives
        fo_name = f"autoresearch_failures_{run_name}"
        try:
            fo.delete_dataset(fo_name)
        except Exception:
            pass

        dataset = fo.Dataset(fo_name)
        samples = []

        for r in results:
            sample = fo.Sample(filepath=r.path)
            boxes = r.boxes
            dets = []
            if boxes is not None:
                for box, conf, cls in zip(boxes.xyxy.cpu().numpy(),
                                          boxes.conf.cpu().numpy(),
                                          boxes.cls.cpu().numpy()):
                    dets.append(fo.Detection(
                        label="face",
                        bounding_box=[
                            box[0] / r.orig_shape[1],
                            box[1] / r.orig_shape[0],
                            (box[2] - box[0]) / r.orig_shape[1],
                            (box[3] - box[1]) / r.orig_shape[0],
                        ],
                        confidence=float(conf),
                    ))
            sample["predictions"] = fo.Detections(detections=dets)
            samples.append(sample)

        dataset.add_samples(samples)

        # Brain: hardness (hard-to-detect images)
        fob.compute_hardness(dataset, "predictions", label_field="predictions")
        # Brain: uniqueness (diverse failure modes)
        fob.compute_uniqueness(dataset)

        # Report top-10 hardest
        top_hard = dataset.sort_by("hardness", reverse=True).limit(10)
        print(f"  [fiftyone] Top-10 hardest images:")
        for s in top_hard:
            n_det = len(s.predictions.detections) if s.predictions else 0
            print(f"    hardness={s.hardness:.3f} | {n_det} detections | {Path(s.filepath).name}")

        # Summary stats
        stats = dataset.stats()
        print(f"  [fiftyone] Dataset: {stats['samples']} samples analysed")
        print(f"  [fiftyone] Brain analysis complete — results saved as '{fo_name}'")

        del model
        return True

    except Exception as e:
        print(f"  [fiftyone] Analysis failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Autoresearch — Face Detection Hyperparameter Search"
    )
    # Resolve paths relative to this script's repo root
    _repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    _ckpt_root = os.path.join(_repo_root, "data", "ray", "checkpoints", "face_detection")
    _default_weights = os.path.join(
        _ckpt_root,
        "phase9_finetune_20260302_145802", "weights", "best.pt",
    )
    _default_dataset = os.path.join(
        _repo_root, "data", "job_workspaces", "data", "wider_face_yolo",
    )
    _default_output = os.path.join(_ckpt_root, "autoresearch")

    parser.add_argument(
        "--weights", type=str,
        default=_default_weights,
        help="Starting weights path (default: phase 9 best.pt)",
    )
    parser.add_argument(
        "--dataset", type=str,
        default=_default_dataset,
        help="Dataset directory containing data.yaml (default: wider_face_yolo)",
    )
    parser.add_argument(
        "--output-dir", type=str,
        default=_default_output,
        help="Output directory for experiment results",
    )
    parser.add_argument(
        "--budget-minutes", type=float, default=30,
        help="Max minutes per experiment (v4: 30min for 30 epochs at 960px/b2)",
    )
    parser.add_argument(
        "--max-iterations", type=int, default=20,
        help="Maximum number of experiments",
    )
    parser.add_argument(
        "--device", type=int, default=0,
        help="CUDA device index",
    )
    parser.add_argument(
        "--epochs-per-iter", type=int, default=30,
        help="Epochs per experiment iteration (v4: 30 to let model converge past oscillation)",
    )
    parser.add_argument(
        "--batch", type=int, default=None,
        help="Override default batch size (e.g., 1 for GPU 1 / 8GB VRAM)",
    )
    parser.add_argument(
        "--llm-url", type=str, default=None,
        help="Local LLM endpoint for mutation proposals (optional)",
    )
    parser.add_argument(
        "--continue-from", type=str, default=None,
        help="Path to previous journal JSON to continue from",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print schedule without training",
    )
    parser.add_argument(
        "--fiftyone", action="store_true",
        help="Run FiftyOne Brain failure analysis on every KEPT checkpoint",
    )
    parser.add_argument(
        "--orchestrate", action="store_true",
        help=(
            "Cycle GPU 0 between training and inference: stops qwen-coding "
            "before each training run, restarts it for LLM mutation proposals, "
            "then stops it again. Requires --llm-url."
        ),
    )
    parser.add_argument(
        "--cumulative", action="store_true",
        help="Use best weights from previous iteration as starting point (vs always starting from initial weights)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Apply --batch override to DEFAULT_CONFIG and MUTATION_SCHEDULE
    if args.batch is not None:
        DEFAULT_CONFIG["batch"] = args.batch
        print(f"  [override] Default batch set to {args.batch}")
        # Cap MUTATION_SCHEDULE entries that specify higher batch sizes
        for m in MUTATION_SCHEDULE:
            if m.get("batch", 0) > args.batch:
                m["batch"] = args.batch

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"╔════════════════════════════════════════════════════════════════╗")
    print(f"║  Autoresearch — Face Detection Hyperparameter Search          ║")
    print(f"║  GPU Yield: {'YES' if _gpu_yielded else 'NO':47s}║")
    print(f"╚════════════════════════════════════════════════════════════════╝")
    print(f"  Weights:     {args.weights}")
    print(f"  Dataset:     {args.dataset}")
    print(f"  Budget:      {args.budget_minutes} min/iter, {args.max_iterations} iters")
    print(f"  Epochs/iter: {args.epochs_per_iter}")
    print(f"  Mode:        {'LLM-driven' if args.llm_url else 'Schedule-driven'}")
    print(f"  Cumulative:  {'Yes (chain best weights)' if args.cumulative else 'No (always from initial weights)'}")

    if args.dry_run:
        print(f"\n  DRY RUN — experiment schedule:")
        for i, mut in enumerate(MUTATION_SCHEDULE[:args.max_iterations]):
            name = mut.get("name", f"iter_{i}")
            changes = {k: v for k, v in mut.items() if k != "name"}
            print(f"    [{i+1:2d}] {name}: {changes}")
        return 0

    # Validate inputs
    if not Path(args.weights).exists():
        print(f"✗ Weights not found: {args.weights}")
        return 1

    data_yaml = Path(args.dataset) / "data.yaml"
    if not data_yaml.exists():
        print(f"✗ Dataset not found: {data_yaml}")
        return 1

    # Initialize tracking
    all_results: list[ExperimentResult] = []
    best_metrics = dict(BASELINE_PHASE9)  # Start from Phase 9 as bar to beat
    best_weights = args.weights
    current_weights = args.weights

    # Load previous run if continuing
    if args.continue_from and Path(args.continue_from).exists():
        with open(args.continue_from) as f:
            prev_data = json.load(f)
        best_metrics = prev_data.get("best_metrics", best_metrics)
        best_weights = prev_data.get("best_weights", best_weights)
        print(f"  Continuing from: {args.continue_from}")
        print(f"  Previous best: {json.dumps(best_metrics)}")

    # MLflow — probe server reachability first to avoid long hangs
    if MLFLOW_AVAILABLE:
        try:
            _mlflow_uri = os.environ.get("MLFLOW_TRACKING_URI_INTERNAL", "http://mlflow-nginx:80")
            # Quick connectivity probe before calling mlflow APIs
            _mlflow_reachable = False
            try:
                _probe = requests.get(f"{_mlflow_uri}/health", timeout=3)
                _mlflow_reachable = _probe.status_code < 500
            except Exception:
                pass

            if not _mlflow_reachable:
                # Fall back to local file tracking — never hangs
                _mlflow_uri = f"file:///tmp/mlruns"
                print(f"[mlflow] Remote server unreachable — using local tracking at {_mlflow_uri}")

            mlflow.set_tracking_uri(_mlflow_uri)
            mlflow.set_experiment("autoresearch-face-detection")
            mlflow.start_run(
                run_name=f"autoresearch_{timestamp}",
                tags={
                    "model": "yolov8m-p2",
                    "strategy": "autoresearch",
                    "mode": "llm" if args.llm_url else "schedule",
                },
            )
            print(f"[mlflow] Tracking: {_mlflow_uri}")
        except Exception as e:
            print(f"[mlflow] Setup error: {e}")

    total_start = time.time()

    # ── GitLab autoresearch tracking issue ──────────────────────────────
    # Find or create a single issue for this run so per-epoch tables appear
    # as comments and agents/humans can monitor progress from the board.
    _ar_issue_iid: int | None = None
    try:
        _gl_scripts = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts", "platform")
        )
        if _gl_scripts not in sys.path:
            sys.path.insert(0, _gl_scripts)
        import gitlab_utils as _gl
        _ar_issue = _gl.upsert_issue(
            "Autoresearch Round 3",
            title="Autoresearch Round 3 — PII Face Detection (recall > 0.760)",
            description=(
                "## Autoresearch Round 3 — Hardware-constrained PII Face Detection\n\n"
                f"**Started:** {datetime.now().isoformat()}\n"
                f"**Target:** recall > 0.760 (primary PII metric; floor: mAP50 ≥ 0.798)\n"
                f"**Baseline:** Phase 9 — recall=0.729, mAP50=0.814\n"
                f"**Weights:** {args.weights}\n"
                f"**Mode:** {'LLM-driven (Qwen)' if args.llm_url else 'Schedule-driven grid'}\n\n"
                "### Strategy\n"
                "- Champion metric: **recall** (PII: a missed face = privacy violation)\n"
                "- Secondary tiebreak: mAP50 (prevents precision collapse)\n"
                "- Hard floors: mAP50 ≥ 0.798, recall ≥ 0.729\n"
                "- Multi-scale ON: imgsz=960, multi_scale=0.33 (643–1280px per batch)\n"
                "- batch=2 (stable BatchNorm), 30 epochs minimum, cache=ram\n\n"
                "### Per-Epoch Progress\n"
                "_Epoch tables appended below as training runs (every 5 epochs)._\n\n"
                "### Links\n"
                "- MLflow: https://shml-platform.tail38b60a.ts.net/mlflow\n"
                f"- Weights dir: {args.output_dir}\n"
            ),
            labels=["type::training", "component::autoresearch", "component::pii-blurring",
                    "priority::critical", "status::in-progress", "metric::recall-primary",
                    "source::autoresearch"],
        )
        _ar_issue_iid = _ar_issue.iid
        print(f"[gitlab] Tracking issue #{_ar_issue_iid}: {_ar_issue.web_url}")
    except Exception as _gl_err:
        print(f"[gitlab] Could not find/create tracking issue (non-fatal): {_gl_err}")

    # ── GPU Orchestrator ────────────────────────────────────────────────
    # When --orchestrate is set, cycles the 3090 Ti between training and
    # inference (Qwen):  free GPU → train → reload Qwen → LLM → repeat.
    orchestrator: GpuOrchestrator | None = None
    if getattr(args, "orchestrate", False) and args.llm_url:
        orchestrator = GpuOrchestrator(
            containers=["qwen-coding"],
            llm_url=args.llm_url,
            gpu_id=0,
            free_vram_threshold_gb=2.0,
            inference_ready_timeout=150,
        )
        print(f"  [orchestrator] Enabled — will cycle GPU 0 between Qwen and training")

    try:
        for i in range(args.max_iterations):
            # ── Step 1: Release GPU → start Qwen for LLM proposal ─────────
            # On the very first iteration this is a no-op if qwen is already
            # running; on subsequent iterations it restarts after training.
            if orchestrator:
                orchestrator.release()

            # ── Step 2: Determine mutation (Qwen must be live) ─────────────
            # Strategy: use LLM from the very first iteration when --llm-url
            # is provided; fall back to the fixed schedule on LLM failure.
            # When no LLM URL is given, follow the schedule until exhausted.
            mutation = {}
            if args.llm_url:
                # LLM-first: always ask Qwen3.5
                print(f"  [llm] Asking Qwen3.5 for mutation proposal …")
                mutation = llm_propose_mutation(args.llm_url, all_results, best_metrics)
                if not mutation and i < len(MUTATION_SCHEDULE):
                    print("  [llm] Falling back to schedule entry")
                    mutation = MUTATION_SCHEDULE[i]
                elif not mutation:
                    print("  [llm] No mutation and schedule exhausted. Stopping.")
                    break
            elif i < len(MUTATION_SCHEDULE):
                mutation = MUTATION_SCHEDULE[i]
            else:
                print(f"  Schedule exhausted at iteration {i+1}. Stopping.")
                break

            # ── Step 3: Acquire GPU → stop Qwen, free full 24 GB ──────────
            if orchestrator:
                orchestrator.acquire()

            # Override epochs
            mutation_config = {**mutation, "epochs": args.epochs_per_iter}
            run_name = f"ar_{timestamp}_{i+1:03d}_{mutation.get('name', 'iter')}"

            # Choose starting weights
            if args.cumulative and best_weights and Path(best_weights).exists():
                current_weights = best_weights
            else:
                current_weights = args.weights

            print(f"\n{'─' * 60}")
            print(f"  Iteration {i+1}/{args.max_iterations}")
            print(f"  Starting from: {Path(current_weights).name}")

            # ── Per-iteration nested MLflow child run ──────────────────────
            _child_run_active = False
            if MLFLOW_AVAILABLE and mlflow.active_run():
                try:
                    child_run = mlflow.start_run(
                        run_name=run_name,
                        nested=True,
                        tags={"iteration": str(i + 1), "mutation": mutation.get("name", "unknown")},
                    )
                    _child_run_active = True
                    # Log all hyperparams for this iteration
                    child_params = {
                        k: str(v) for k, v in mutation_config.items() if k != "name"
                    }
                    child_params["starting_weights"] = Path(current_weights).name
                    child_params["cumulative"] = str(args.cumulative)
                    child_params["llm_driven"] = str(bool(args.llm_url))
                    mlflow.log_params(child_params)
                except Exception as e:
                    print(f"  [mlflow] child run start failed: {e}")

            # ── Run experiment ─────────────────────────────────────────────
            result = run_experiment(
                weights_path=current_weights,
                dataset_dir=args.dataset,
                config=mutation_config,
                output_dir=output_dir,
                run_name=run_name,
                device=args.device,
                time_budget_sec=args.budget_minutes * 60,
                gitlab_issue_iid=_ar_issue_iid,
            )
            result.iteration = i + 1

            # ── Evaluate ───────────────────────────────────────────────────
            kept = evaluate_result(result, best_metrics)

            if kept:
                best_metrics = dict(result.metrics)
                best_weights = result.weights_path
                print(f"  └─ ✓ KEPT — {result.reason}")
                # FiftyOne brain failure analysis on each kept result
                if args.fiftyone and result.weights_path and Path(result.weights_path).exists():
                    analyze_failures_fiftyone(
                        weights_path=result.weights_path,
                        dataset_yaml=str(Path(args.dataset) / "data.yaml"),
                        run_name=run_name,
                        device=args.device,
                    )
            else:
                print(f"  └─ ✗ DISCARDED — {result.reason}")

            if result.metrics:
                deltas = result.delta_vs(BASELINE_PHASE9, "p9")
                print(
                    f"     mAP50={result.metrics.get('mAP50', 0):.4f} "
                    f"R={result.metrics.get('recall', 0):.4f} "
                    f"P={result.metrics.get('precision', 0):.4f} "
                    f"F1={result.metrics.get('F1', 0):.4f} "
                    f"[Δp9: m50{deltas['Δp9_mAP50']:+.3f} R{deltas['Δp9_recall']:+.3f}]"
                )

            all_results.append(result)

            # ── Redis: publish experiment-complete event ─────────────────
            publish_event("shml:autoresearch:progress", {
                "type": "experiment_complete",
                "experiment": result.name,
                "iteration": i + 1,
                "kept": result.kept,
                "reason": result.reason,
                "metrics": result.metrics,
                "best_recall": best_metrics.get("recall", 0),
                "best_mAP50": best_metrics.get("mAP50", 0),
            })

            # ── Obsidian vault note for noteworthy results ─────────────────
            _write_obsidian_note(
                result=result,
                is_champion=kept,
                run_timestamp=timestamp,
            )

            # ── Log to nested child run ────────────────────────────────────
            if MLFLOW_AVAILABLE and _child_run_active:
                try:
                    if result.metrics:
                        mlflow.log_metrics({
                            "mAP50": result.metrics.get("mAP50", 0),
                            "recall": result.metrics.get("recall", 0),
                            "precision": result.metrics.get("precision", 0),
                            "F1": result.metrics.get("F1", 0),
                            "mAP50_95": result.metrics.get("mAP50_95", 0),
                            "delta_mAP50": result.metrics.get("mAP50", 0) - BASELINE_PHASE9["mAP50"],
                            "delta_recall": result.metrics.get("recall", 0) - BASELINE_PHASE9["recall"],
                        })
                    mlflow.log_metrics({
                        "kept": float(result.kept),
                        "duration_min": result.duration_sec / 60,
                        "vram_peak_mb": result.vram_peak_mb,
                    })
                    if result.error:
                        mlflow.set_tag("error", result.error)
                    mlflow.set_tag("decision", "KEPT" if result.kept else "DISCARDED")
                    mlflow.set_tag("reason", result.reason[:250])
                    if result.weights_path and Path(result.weights_path).exists() and result.kept:
                        mlflow.log_artifact(result.weights_path, "best_weights")
                    mlflow.end_run()
                except Exception as e:
                    print(f"  [mlflow] child run log failed: {e}")
                    try:
                        mlflow.end_run()
                    except Exception:
                        pass

            # ── Parent run rolling best ────────────────────────────────────
            if MLFLOW_AVAILABLE and mlflow.active_run():
                try:
                    mlflow.log_metrics({
                        "current_best_mAP50": best_metrics.get("mAP50", 0),
                        "current_best_recall": best_metrics.get("recall", 0),
                    }, step=i + 1)
                except Exception:
                    pass

    except KeyboardInterrupt:
        print("\n⚠ Search interrupted")
    finally:
        total_time = time.time() - total_start

        # Summary
        kept_count = sum(1 for r in all_results if r.kept)
        error_count = sum(1 for r in all_results if r.error)

        print(f"\n{'═' * 70}")
        print(f"  AUTORESEARCH SUMMARY")
        print(f"{'═' * 70}")
        print(f"  Total iterations: {len(all_results)}")
        print(f"  Kept:             {kept_count}")
        print(f"  Discarded:        {len(all_results) - kept_count - error_count}")
        print(f"  Errors:           {error_count}")
        print(f"  Total time:       {total_time/60:.1f} min")
        print(f"\n  Best result:")
        print(f"    mAP50:     {best_metrics.get('mAP50', 0):.4f} (Phase 9 baseline: {BASELINE_PHASE9['mAP50']})")
        print(f"    Recall:    {best_metrics.get('recall', 0):.4f} (Phase 9 baseline: {BASELINE_PHASE9['recall']})")
        print(f"    Precision: {best_metrics.get('precision', 0):.4f}")
        print(f"    F1:        {best_metrics.get('F1', 0):.4f}")
        if best_weights != args.weights:
            print(f"    Weights:   {best_weights}")
        else:
            print(f"    Weights:   (no improvement over starting weights)")
        print(f"{'═' * 70}\n")

        # Write journal
        write_journal(
            all_results,
            best_metrics,
            output_dir / f"journal_{timestamp}.md",
        )

        # Save machine-readable results
        state_path = output_dir / f"autoresearch_state_{timestamp}.json"
        state = {
            "timestamp": timestamp,
            "total_iterations": len(all_results),
            "total_time_minutes": total_time / 60,
            "best_metrics": best_metrics,
            "best_weights": best_weights,
            "baseline_phase5": BASELINE_PHASE5,
            "baseline_phase9": BASELINE_PHASE9,
            "results": [asdict(r) for r in all_results],
        }
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2, default=str)
        print(f"[state] Saved: {state_path}")

        # MLflow finalization
        if MLFLOW_AVAILABLE and mlflow.active_run():
            try:
                mlflow.log_metrics({
                    "final_mAP50": best_metrics.get("mAP50", 0),
                    "final_recall": best_metrics.get("recall", 0),
                    "total_iterations": len(all_results),
                    "kept_count": kept_count,
                })
                if best_weights and Path(best_weights).exists():
                    mlflow.log_artifact(best_weights, "best_weights")
                mlflow.log_artifact(str(output_dir / f"journal_{timestamp}.md"), "journal")
                mlflow.end_run()
            except Exception:
                try:
                    mlflow.end_run()
                except Exception:
                    pass

        # GPU reclaim
        try:
            reclaim_gpu_after_training(gpu_id=0, job_id=_job_id)
        except Exception:
            pass

        # Orchestrator cleanup — ensure Qwen is running when script exits
        if orchestrator:
            orchestrator.cleanup()

    return 0


if __name__ == "__main__":
    sys.exit(main())
