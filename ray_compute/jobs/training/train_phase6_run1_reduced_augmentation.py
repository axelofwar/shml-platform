#!/usr/bin/env python3
"""
Phase 6 Run 1 - YOLOv8m-P2 (REDUCED AUGMENTATION)
==================================================================

Hypothesis: Phase 5's AGGRESSIVE augmentation prevents optimal convergence

Evidence from Phase 5 Analysis:
- Training mAP@50: 83.06% (with augmentation active during validation)
- Evaluation mAP@50: 85.90% (no augmentation)
- Gap: +2.84% suggests model struggles with heavy augmentation
- close_mosaic=15 helped last 15 epochs → disabling augmentation improves convergence

Augmentation Changes (Phase 5 → Phase 6 Run 1):
┌─────────────────────┬──────────────────────┬────────────────────────┐
│ Parameter           │ Phase 5 (Heavy)      │ Phase 6 Run 1 (Gentler)│
├─────────────────────┼──────────────────────┼────────────────────────┤
│ mosaic              │ 1.0 (always)         │ 0.5 (50% of time)      │
│ mixup               │ 0.15 (15%)           │ 0.05 (5%)              │
│ scale               │ 0.5 (±50%)           │ 0.3 (±30%)             │
│ erasing             │ 0.4 (40%)            │ 0.2 (20%)              │
│ close_mosaic        │ 15 epochs            │ 30 epochs              │
│ hsv_h               │ 0.015                │ 0.01                   │
│ hsv_s               │ 0.7                  │ 0.5                    │
│ hsv_v               │ 0.4                  │ 0.3                    │
└─────────────────────┴──────────────────────┴────────────────────────┘

Memory Optimizations (BATCH=4 @ 1280px on RTX 3090):
┌─────────────────────────────┬────────────────────────────────────────┐
│ Optimization                │ Effect                                 │
├─────────────────────────────┼────────────────────────────────────────┤
│ PYTORCH_CUDA_ALLOC_CONF     │ Expandable segments, GC threshold 0.8  │
│ TF32 Tensor Cores           │ ~7x faster matmul, minimal precision   │
│ workers=4 (from 8)          │ Reduces DataLoader memory overhead     │
│ Explicit memory cleanup     │ torch.cuda.empty_cache() between runs  │
│ nbs=64 (nominal batch)      │ Gradient accumulation for larger eff.  │
└─────────────────────────────┴────────────────────────────────────────┘

Strategy:
1. Transfer Learning: Initialize from Phase 5 best.pt (85.90% eval mAP@50)
2. Reduce Augmentation Intensity: Test if heavy augmentation was bottleneck
3. Earlier close_mosaic: Disable augmentation 30 epochs before end (vs 15)
4. Same Optimizer/LR: AdamW with cosine schedule (proven in Phase 5)
5. Same Training Duration: 150 epochs with patience=50

Expected Outcome:
- Training mAP50: 83.06% → 85-87% (close the eval>training gap)
- Evaluation mAP50: 85.90% → 86-88% (modest improvement from gentler augmentation)
- Decision Point: If ≥87% eval mAP@50 → proceed to Phase 6 Run 2 (YOLOv8l-P2)
                  If <85% eval mAP@50 → model capacity limit, need bigger model

PII KPI Targets:
- mAP50 ≥ 94% (faces ≥10px)
- Recall ≥ 95% (for PII, missing faces is worse than false positives)
- Precision ≥ 90%
- Hard mAP50 ≥ 85% (tiny faces 10-65px)
- FPS@1280 ≥ 30 (real-time)
"""

import os
import sys
import yaml
import argparse
from pathlib import Path
from datetime import datetime
import shutil

# =============================================================================
# GPU YIELD: Use shared utility module (imported before torch)
# =============================================================================
_utils_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _utils_path not in sys.path:
    sys.path.insert(0, _utils_path)
from utils.gpu_yield import yield_gpu_for_training, reclaim_gpu_after_training

_job_id = os.environ.get("RAY_JOB_ID", f"phase6-reduced-aug-{os.getpid()}")
yield_gpu_for_training(gpu_id=0, job_id=_job_id, timeout=30)

import torch

# =============================================================================
# SOTA MEMORY OPTIMIZATION: Set CUDA allocator config BEFORE any CUDA ops
# =============================================================================
# Source: PyTorch CUDA docs - https://pytorch.org/docs/stable/notes/cuda.html
#
# expandable_segments=True: Better handles variable allocation sizes (batch changes)
# garbage_collection_threshold=0.8: Reclaim memory at 80% usage (avoid fragmentation)
# max_split_size_mb=512: Prevent large block splitting that causes fragmentation
#
os.environ.setdefault(
    "PYTORCH_CUDA_ALLOC_CONF",
    "expandable_segments:True,garbage_collection_threshold:0.8,max_split_size_mb:512",
)

# Enable TF32 for Ampere+ GPUs (RTX 30-series) - ~7x faster matmul
# Source: PyTorch TensorFloat-32 documentation
# Precision impact: ~0.002 relative error vs FP32 (acceptable for training)
if torch.cuda.is_available():
    # TF32 for matmul operations (convolutions, linear layers)
    torch.backends.cuda.matmul.allow_tf32 = True
    # TF32 for cuDNN operations (conv2d, etc.)
    torch.backends.cudnn.allow_tf32 = True
    # Enable cuDNN autotuner for optimal kernel selection
    torch.backends.cudnn.benchmark = True
    # Deterministic mode (disable for max speed, enable for reproducibility)
    torch.backends.cudnn.deterministic = False


# =============================================================================
# FIX: Patch Ray Tune BEFORE importing ultralytics
# =============================================================================
def _patch_ray_tune_api():
    """Patch Ray Tune to add missing is_session_enabled() for ultralytics compatibility."""
    try:
        import ray.tune as tune

        def is_session_enabled():
            """Check if we're inside a Ray Tune/Train session."""
            try:
                from ray.train import get_context

                ctx = get_context()
                return ctx is not None
            except (ImportError, RuntimeError):
                return False

        if not hasattr(tune, "is_session_enabled"):
            tune.is_session_enabled = is_session_enabled
            print(
                "[INFO] Patched ray.tune.is_session_enabled() for Ray 2.x compatibility"
            )
    except ImportError:
        pass


_patch_ray_tune_api()

from ultralytics import YOLO

# MLflow integration
try:
    import mlflow

    MLFLOW_AVAILABLE = True
except ImportError:
    MLFLOW_AVAILABLE = False
    print("⚠️  MLflow not available - training will proceed without tracking")

# Prometheus Pushgateway integration
try:
    from prometheus_client import (
        CollectorRegistry,
        Gauge,
        Counter,
        push_to_gateway,
        delete_from_gateway,
    )

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    print(
        "⚠️  prometheus_client not available - install with: pip install prometheus_client"
    )

# ============================================================================
# PROMETHEUS PUSHGATEWAY CONFIGURATION
# ============================================================================

PUSHGATEWAY_CONFIG = {
    "url": "172.30.0.16:9091",  # shml-pushgateway container IP
    "job_name": "face_detection_training",
    "instance": "phase_5_yolov8m_p2",
}

# ============================================================================
# REGRESSION MONITORING - EARLY WARNING THRESHOLDS
# ============================================================================

REGRESSION_THRESHOLDS = {
    # Phase 3 baseline (our best so far)
    "phase3_map50": 0.8478,
    "phase3_recall": 0.7426,
    "phase3_precision": 0.9180,
    # Phase 4 regression (what to avoid)
    "phase4_map50": 0.8064,
    "phase4_recall": 0.6474,
    # Minimum acceptable (warn if below)
    "min_map50_epoch10": 0.75,  # By epoch 10, should be at least 75%
    "min_map50_epoch50": 0.80,  # By epoch 50, should be at least 80%
    "min_map50_epoch100": 0.82,  # By epoch 100, should be at least 82%
    # Critical regression (stop training if sustained)
    "critical_map50_drop": 0.10,  # 10% drop from best = critical
    "critical_recall_drop": 0.15,  # 15% recall drop = critical
    "sustained_epochs": 20,  # Must sustain for 20 epochs to trigger
}

# ============================================================================
# MLFLOW CONFIGURATION
# ============================================================================

MLFLOW_CONFIG = {
    "tracking_uri": "http://localhost/mlflow/",  # Via Traefik
    "experiment_name": "Face-Detection-P6",
    "run_name": None,  # Auto-generated if None
    "tags": {
        "model_type": "face_detection",
        "architecture": "yolov8m-p2",
        "dataset": "wider_face",
        "purpose": "privacy_protection",
        "phase": "6",
        "run": "1_reduced_augmentation",
        "transfer_from": "phase_5",
        "hypothesis": "aggressive_aug_bottleneck",
    },
}

# ============================================================================
# SOTA BENCHMARKS & PII KPI TARGETS
# ============================================================================

SOTA_BENCHMARKS = {
    "SCRFD-34GF": {
        "easy": 96.06,
        "medium": 94.92,
        "hard": 85.29,
        "note": "Overall SOTA",
    },
    "TinaFace": {"easy": 95.61, "medium": 94.25, "hard": 81.43, "note": "ResNet50"},
    "YOLOv8m-Face": {"easy": 96.6, "medium": 95.0, "hard": 84.7, "note": "YOLO SOTA"},
    "YOLOv8l-Face": {"easy": 96.9, "medium": 95.4, "hard": 85.6, "note": "YOLO Large"},
    "Our Phase 3": {
        "easy": 89.7,
        "medium": 87.2,
        "hard": 75.9,
        "note": "YOLOv8l, baseline",
    },
    "Our Phase 4": {"easy": 86.9, "medium": 83.8, "hard": 68.2, "note": "REGRESSION!"},
}

# PII-Level KPI Targets
PII_KPI = {
    "mAP50": 94.0,  # ≥94% overall accuracy
    "recall": 95.0,  # ≥95% find all faces (critical for PII)
    "precision": 90.0,  # ≥90% accurate detections
    "hard_mAP50": 85.0,  # ≥85% on tiny faces (10-65px)
    "fps_1280": 30.0,  # ≥30 FPS at 1280px
}

# Phase 5 Target: Beat Phase 3 + achieve P2 advantage
TARGET_MAP50 = 86.0  # > Phase 3's 84.78%
TARGET_RECALL = 78.0  # > Phase 3's 74.26%
TARGET_HARD_MAP = 78.0  # > Phase 4's 68.2% Hard mAP

# ============================================================================
# MLFLOW SETUP
# ============================================================================


def setup_mlflow(dry_run: bool = False) -> bool:
    """Initialize MLflow tracking for this training run."""
    if not MLFLOW_AVAILABLE:
        print("⚠️  MLflow not installed, skipping tracking setup")
        return False

    if dry_run:
        print("🔍 [DRY RUN] Would initialize MLflow tracking:")
        print(f"   URI: {MLFLOW_CONFIG['tracking_uri']}")
        print(f"   Experiment: {MLFLOW_CONFIG['experiment_name']}")
        return False

    try:
        mlflow.set_tracking_uri(MLFLOW_CONFIG["tracking_uri"])
        mlflow.set_experiment(MLFLOW_CONFIG["experiment_name"])

        # Test connection
        client = mlflow.tracking.MlflowClient()
        experiments = client.search_experiments()
        print(f"✓ MLflow connected: {len(experiments)} experiments found")
        return True
    except Exception as e:
        print(f"⚠️  MLflow connection failed: {e}")
        print("   Training will continue without MLflow tracking")
        return False


def start_mlflow_run(run_name: str = None) -> bool:
    """Start a new MLflow run for tracking."""
    if not MLFLOW_AVAILABLE:
        return False

    try:
        actual_run_name = (
            run_name or f"phase5_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        mlflow.start_run(run_name=actual_run_name, tags=MLFLOW_CONFIG["tags"])

        # Log training configuration
        mlflow.log_params(
            {
                "phase": 5,
                "base_model": "phase_5_best.pt",
                "architecture": "yolov8m-p2",
                "transfer_learning": True,
                "imgsz": TRAINING_CONFIG["imgsz"],
                "batch_size": TRAINING_CONFIG["batch"],
                "epochs": TRAINING_CONFIG["epochs"],
                "optimizer": TRAINING_CONFIG["optimizer"],
                "lr0": TRAINING_CONFIG["lr0"],
                "mosaic": TRAINING_CONFIG["mosaic"],
                "mixup": TRAINING_CONFIG["mixup"],
                "close_mosaic": TRAINING_CONFIG["close_mosaic"],
                "label_smoothing": TRAINING_CONFIG["label_smoothing"],
                "workers": TRAINING_CONFIG["workers"],
                "amp": TRAINING_CONFIG["amp"],
                "nbs": TRAINING_CONFIG.get("nbs", 64),
            }
        )

        # Log memory optimization settings
        mlflow.log_params(
            {
                "cuda_alloc_conf": os.environ.get("PYTORCH_CUDA_ALLOC_CONF", "default"),
                "tf32_enabled": (
                    torch.backends.cuda.matmul.allow_tf32
                    if torch.cuda.is_available()
                    else False
                ),
                "cudnn_benchmark": (
                    torch.backends.cudnn.benchmark
                    if torch.cuda.is_available()
                    else False
                ),
            }
        )

        print(f"✓ MLflow run started: {actual_run_name}")
        return True
    except Exception as e:
        print(f"⚠️  Failed to start MLflow run: {e}")
        return False


def log_training_results(results, output_dir: Path):
    """Log final training results to MLflow."""
    if not MLFLOW_AVAILABLE:
        return

    try:
        results_file = output_dir / "results.csv"
        if results_file.exists():
            import pandas as pd

            df = pd.read_csv(results_file)

            # Log best metrics
            mlflow.log_metrics(
                {
                    "best_mAP50": df["metrics/mAP50(B)"].max(),
                    "best_mAP50_95": df["metrics/mAP50-95(B)"].max(),
                    "best_precision": df["metrics/precision(B)"].max(),
                    "best_recall": df["metrics/recall(B)"].max(),
                    "final_epoch": len(df),
                }
            )

            # Log comparison to Phase 4
            phase4_map = 0.8064
            phase5_map = df["metrics/mAP50(B)"].max()
            improvement = (phase5_map - phase4_map) * 100
            mlflow.log_metric("improvement_over_phase4", improvement)

        # Log model artifacts
        weights_dir = output_dir / "weights"
        if weights_dir.exists():
            mlflow.log_artifacts(str(weights_dir), "weights")

        # Log training curves
        for plot_name in ["results.png", "confusion_matrix.png", "PR_curve.png"]:
            plot_path = output_dir / plot_name
            if plot_path.exists():
                mlflow.log_artifact(str(plot_path), "plots")

        print("✓ Results logged to MLflow")
    except Exception as e:
        print(f"⚠️  Failed to log results to MLflow: {e}")


def end_mlflow_run(status: str = "FINISHED"):
    """End the MLflow run."""
    if MLFLOW_AVAILABLE:
        try:
            mlflow.end_run(status=status)
            print(f"✓ MLflow run ended: {status}")
        except Exception as e:
            print(f"⚠️  Failed to end MLflow run: {e}")


# ============================================================================
# PROMETHEUS PUSHGATEWAY METRICS
# ============================================================================


class TrainingMetricsReporter:
    """Push training metrics to Prometheus Pushgateway for Grafana visualization."""

    def __init__(self, job_name: str = None, instance: str = None):
        self.enabled = PROMETHEUS_AVAILABLE
        self.job_name = job_name or PUSHGATEWAY_CONFIG["job_name"]
        self.instance = instance or PUSHGATEWAY_CONFIG["instance"]
        self.pushgateway_url = PUSHGATEWAY_CONFIG["url"]

        # Track best metrics for regression detection
        self.best_map50 = 0.0
        self.best_recall = 0.0
        self.best_precision = 0.0
        self.epochs_since_improvement = 0
        self.regression_warnings = []

        if not self.enabled:
            print("⚠️  Prometheus metrics disabled (prometheus_client not installed)")
            return

        # Create registry and metrics
        self.registry = CollectorRegistry()

        # Training progress metrics
        self.epoch_gauge = Gauge(
            "training_epoch",
            "Current training epoch",
            ["job_name", "instance", "phase"],
            registry=self.registry,
        )
        self.epoch_total_gauge = Gauge(
            "training_epoch_total",
            "Total epochs planned",
            ["job_name", "instance"],
            registry=self.registry,
        )
        self.progress_gauge = Gauge(
            "training_progress",
            "Training progress (0-1)",
            ["job_name", "instance"],
            registry=self.registry,
        )

        # Loss metrics
        self.box_loss_gauge = Gauge(
            "training_box_loss",
            "Box regression loss",
            ["job_name", "instance"],
            registry=self.registry,
        )
        self.cls_loss_gauge = Gauge(
            "training_cls_loss",
            "Classification loss",
            ["job_name", "instance"],
            registry=self.registry,
        )
        self.dfl_loss_gauge = Gauge(
            "training_dfl_loss",
            "Distribution focal loss",
            ["job_name", "instance"],
            registry=self.registry,
        )

        # Performance metrics
        self.map50_gauge = Gauge(
            "training_map50",
            "mAP at IoU=0.50",
            ["job_name", "instance"],
            registry=self.registry,
        )
        self.map50_95_gauge = Gauge(
            "training_map50_95",
            "mAP at IoU=0.50:0.95",
            ["job_name", "instance"],
            registry=self.registry,
        )
        self.precision_gauge = Gauge(
            "training_precision",
            "Model precision",
            ["job_name", "instance"],
            registry=self.registry,
        )
        self.recall_gauge = Gauge(
            "training_recall",
            "Model recall",
            ["job_name", "instance"],
            registry=self.registry,
        )

        # Best metrics (for tracking improvement)
        self.best_map50_gauge = Gauge(
            "training_best_map50",
            "Best mAP50 achieved",
            ["job_name", "instance"],
            registry=self.registry,
        )
        self.best_recall_gauge = Gauge(
            "training_best_recall",
            "Best recall achieved",
            ["job_name", "instance"],
            registry=self.registry,
        )

        # Regression monitoring
        self.regression_risk_gauge = Gauge(
            "training_regression_risk",
            "Regression risk level (0=none, 1=warning, 2=critical)",
            ["job_name", "instance"],
            registry=self.registry,
        )
        self.epochs_since_best_gauge = Gauge(
            "training_epochs_since_best",
            "Epochs since best mAP50",
            ["job_name", "instance"],
            registry=self.registry,
        )

        # GPU metrics
        self.gpu_memory_gauge = Gauge(
            "training_gpu_memory_gb",
            "GPU memory used (GB)",
            ["job_name", "instance", "gpu_id"],
            registry=self.registry,
        )
        self.gpu_utilization_gauge = Gauge(
            "training_gpu_utilization",
            "GPU utilization (0-1)",
            ["job_name", "instance", "gpu_id"],
            registry=self.registry,
        )

        # Comparison to baselines
        self.vs_phase3_gauge = Gauge(
            "training_vs_phase3",
            "Difference from Phase 3 mAP50",
            ["job_name", "instance"],
            registry=self.registry,
        )
        self.vs_phase4_gauge = Gauge(
            "training_vs_phase4",
            "Difference from Phase 4 mAP50",
            ["job_name", "instance"],
            registry=self.registry,
        )

        print(f"✓ Prometheus metrics reporter initialized")
        print(f"  Pushgateway: {self.pushgateway_url}")
        print(f"  Job: {self.job_name}, Instance: {self.instance}")

    def push_metrics(self):
        """Push all metrics to Pushgateway."""
        if not self.enabled:
            return
        try:
            push_to_gateway(
                self.pushgateway_url,
                job=self.job_name,
                registry=self.registry,
                grouping_key={"instance": self.instance},
            )
        except Exception as e:
            print(f"⚠️  Failed to push metrics: {e}")

    def report_epoch(
        self,
        epoch: int,
        total_epochs: int,
        box_loss: float = None,
        cls_loss: float = None,
        dfl_loss: float = None,
        map50: float = None,
        map50_95: float = None,
        precision: float = None,
        recall: float = None,
    ):
        """Report metrics for a training epoch."""
        if not self.enabled:
            return

        labels = {"job_name": self.job_name, "instance": self.instance}

        # Progress
        self.epoch_gauge.labels(phase="5", **labels).set(epoch)
        self.epoch_total_gauge.labels(**labels).set(total_epochs)
        self.progress_gauge.labels(**labels).set(epoch / total_epochs)

        # Losses
        if box_loss is not None:
            self.box_loss_gauge.labels(**labels).set(box_loss)
        if cls_loss is not None:
            self.cls_loss_gauge.labels(**labels).set(cls_loss)
        if dfl_loss is not None:
            self.dfl_loss_gauge.labels(**labels).set(dfl_loss)

        # Performance
        if map50 is not None:
            self.map50_gauge.labels(**labels).set(map50)
            # Track best
            if map50 > self.best_map50:
                self.best_map50 = map50
                self.epochs_since_improvement = 0
            else:
                self.epochs_since_improvement += 1
            self.best_map50_gauge.labels(**labels).set(self.best_map50)
            self.epochs_since_best_gauge.labels(**labels).set(
                self.epochs_since_improvement
            )

            # Comparison to baselines
            vs_phase3 = map50 - REGRESSION_THRESHOLDS["phase3_map50"]
            vs_phase4 = map50 - REGRESSION_THRESHOLDS["phase4_map50"]
            self.vs_phase3_gauge.labels(**labels).set(vs_phase3)
            self.vs_phase4_gauge.labels(**labels).set(vs_phase4)

        if map50_95 is not None:
            self.map50_95_gauge.labels(**labels).set(map50_95)

        if precision is not None:
            self.precision_gauge.labels(**labels).set(precision)

        if recall is not None:
            self.recall_gauge.labels(**labels).set(recall)
            if recall > self.best_recall:
                self.best_recall = recall
            self.best_recall_gauge.labels(**labels).set(self.best_recall)

        # Check for regression
        risk_level = self._check_regression(epoch, map50, recall)
        self.regression_risk_gauge.labels(**labels).set(risk_level)

        # Push to gateway
        self.push_metrics()

    def report_gpu_metrics(self):
        """Report GPU metrics."""
        if not self.enabled or not torch.cuda.is_available():
            return

        try:
            labels = {
                "job_name": self.job_name,
                "instance": self.instance,
                "gpu_id": "0",
            }
            memory_gb = torch.cuda.memory_allocated(0) / 1e9
            self.gpu_memory_gauge.labels(**labels).set(memory_gb)
            self.push_metrics()
        except Exception as e:
            pass  # Don't fail training for GPU metric errors

    def _check_regression(self, epoch: int, map50: float, recall: float) -> int:
        """Check for training regression. Returns risk level 0-2."""
        if map50 is None:
            return 0

        risk_level = 0
        warnings = []

        # Check epoch-based minimums
        if epoch >= 10 and map50 < REGRESSION_THRESHOLDS["min_map50_epoch10"]:
            warnings.append(
                f"mAP50 {map50:.2%} below epoch 10 minimum ({REGRESSION_THRESHOLDS['min_map50_epoch10']:.0%})"
            )
            risk_level = max(risk_level, 1)

        if epoch >= 50 and map50 < REGRESSION_THRESHOLDS["min_map50_epoch50"]:
            warnings.append(
                f"mAP50 {map50:.2%} below epoch 50 minimum ({REGRESSION_THRESHOLDS['min_map50_epoch50']:.0%})"
            )
            risk_level = max(risk_level, 1)

        if epoch >= 100 and map50 < REGRESSION_THRESHOLDS["min_map50_epoch100"]:
            warnings.append(
                f"mAP50 {map50:.2%} below epoch 100 minimum ({REGRESSION_THRESHOLDS['min_map50_epoch100']:.0%})"
            )
            risk_level = max(risk_level, 2)

        # Check for drop from best
        if self.best_map50 > 0:
            drop = self.best_map50 - map50
            if drop > REGRESSION_THRESHOLDS["critical_map50_drop"]:
                warnings.append(
                    f"mAP50 dropped {drop:.2%} from best ({self.best_map50:.2%})"
                )
                risk_level = max(risk_level, 2)

        # Check sustained no improvement
        if self.epochs_since_improvement >= REGRESSION_THRESHOLDS["sustained_epochs"]:
            warnings.append(
                f"No improvement for {self.epochs_since_improvement} epochs"
            )
            risk_level = max(risk_level, 1)

        # Log warnings
        for warning in warnings:
            if warning not in self.regression_warnings:
                self.regression_warnings.append(warning)
                print(f"⚠️  REGRESSION WARNING: {warning}")

        return risk_level

    def cleanup(self):
        """Clean up metrics from Pushgateway."""
        if not self.enabled:
            return
        try:
            delete_from_gateway(
                self.pushgateway_url,
                job=self.job_name,
                grouping_key={"instance": self.instance},
            )
            print("✓ Cleaned up Pushgateway metrics")
        except Exception as e:
            print(f"⚠️  Failed to cleanup metrics: {e}")


# Global metrics reporter instance
metrics_reporter = None


def init_metrics_reporter():
    """Initialize the global metrics reporter."""
    global metrics_reporter
    metrics_reporter = TrainingMetricsReporter()
    return metrics_reporter


# ============================================================================
# PATH CONFIGURATION
# ============================================================================


def get_paths():
    """Get correct paths based on execution environment."""
    container_ray_dir = Path("/tmp/ray")
    container_job_dir = Path("/opt/ray/job_workspaces")

    host_root = Path("/home/axelofwar/Projects/shml-platform")
    host_ray_dir = host_root / "ray_compute/data/ray"
    host_job_dir = host_root / "ray_compute/data/job_workspaces"

    if container_ray_dir.exists():
        return {
            "checkpoint_dir": container_ray_dir / "checkpoints/face_detection",
            "data_dir": container_job_dir / "data/wider_face_yolo",
            "config_dir": Path("/tmp/job"),
        }
    else:
        return {
            "checkpoint_dir": host_ray_dir / "checkpoints/face_detection",
            "data_dir": host_job_dir / "data/wider_face_yolo",
            "config_dir": host_root / "ray_compute/jobs/training/configs",
        }


PATHS = get_paths()
CHECKPOINT_DIR = PATHS["checkpoint_dir"]
DATA_DIR = PATHS["data_dir"]
CONFIG_DIR = PATHS["config_dir"]

# CRITICAL: Phase 5 checkpoint as base (transfer learning from Phase 5)
PHASE5_WEIGHTS = CHECKPOINT_DIR / "phase_5_yolov8m_p2_20251216_004521/weights/best.pt"

# Output directory
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT_NAME = f"phase_6_run1_yolov8m_p2_reduced_aug_{TIMESTAMP}"
OUTPUT_DIR = CHECKPOINT_DIR / OUTPUT_NAME

# P2 Model Config
P2_MODEL_CONFIG = CONFIG_DIR / "yolov8m-face-p2.yaml"

# ============================================================================
# TRAINING HYPERPARAMETERS - RESEARCH-BACKED OPTIMIZATIONS
# ============================================================================

TRAINING_CONFIG = {
    # === Resolution (same as Phase 4 for fair comparison) ===
    "imgsz": 1280,
    # === Training Duration (Same as Phase 5 for fair comparison) ===
    "epochs": 150,  # Reduced from 200 for faster iteration
    "patience": 50,  # ✓ Same as Phase 5: Don't early stop too soon
    # === MEMORY OPTIMIZATION: Batch Size & Gradient Accumulation ===
    # With PYTORCH_CUDA_ALLOC_CONF + TF32 + reduced workers, batch=4 is viable
    # Memory budget: ~12GB for batch=4 @ 1280px (RTX 3090 has 24GB)
    "batch": 4,  # ✓ UPGRADED from 2 (memory optimized)
    "nbs": 64,  # Nominal batch size for gradient accumulation
    # Effective accumulation = 64/4 = 16 steps
    # This simulates batch=64 for gradient smoothing
    # === Optimizer: AdamW (FIX: was SGD) ===
    # Research: AdamW better for fine-tuning, used successfully in Phase 3
    "optimizer": "AdamW",  # ✓ FIX: Phase 3 used AdamW successfully
    "lr0": 0.001,  # ✓ FIX: Lower for fine-tuning (was 0.005)
    "lrf": 0.01,  # Final LR = 0.001 * 0.01 = 0.00001
    "cos_lr": True,  # Cosine annealing
    "warmup_epochs": 3,  # Quick warmup for fine-tuning
    "warmup_momentum": 0.8,
    "warmup_bias_lr": 0.1,
    "momentum": 0.937,  # For AdamW's beta1
    "weight_decay": 0.0005,  # Standard L2 regularization
    # === Regularization ===
    "dropout": 0.0,  # Dropout hurts detection performance
    "label_smoothing": 0.1,  # ✓ NEW: From ML Engineering - helps generalization
    # === Data Augmentation (PHASE 6 RUN 1: REDUCED INTENSITY) ===
    # Hypothesis: Phase 5's heavy augmentation prevents optimal convergence
    # Evidence: +2.84% eval>training gap, close_mosaic=15 helped convergence
    "hsv_h": 0.01,  # ✓ REDUCED: 0.015 → 0.01 (gentler hue jitter)
    "hsv_s": 0.5,  # ✓ REDUCED: 0.7 → 0.5 (gentler saturation)
    "hsv_v": 0.3,  # ✓ REDUCED: 0.4 → 0.3 (gentler value/brightness)
    "degrees": 0.0,  # No rotation for faces
    "translate": 0.1,
    "scale": 0.3,  # ✓ REDUCED: 0.5 → 0.3 (±30% vs ±50%)
    "shear": 0.0,  # No shear for faces
    "perspective": 0.0,  # No perspective distortion
    "flipud": 0.0,  # No vertical flip
    "fliplr": 0.5,  # Horizontal flip OK (unchanged)
    "mosaic": 0.5,  # ✓ REDUCED: 1.0 → 0.5 (50% of time vs always)
    "mixup": 0.05,  # ✓ REDUCED: 0.15 → 0.05 (5% vs 15%)
    "copy_paste": 0.0,  # Keep disabled (artifacts)
    "erasing": 0.2,  # ✓ REDUCED: 0.4 → 0.2 (20% vs 40%)
    "auto_augment": "randaugment",  # Keep RandAugment (but with reduced intensity above)
    "close_mosaic": 30,  # ✓ INCREASED: 15 → 30 (disable augmentation earlier)
    # === Loss Weights (same as Phase 3/4) ===
    "box": 7.5,
    "cls": 0.5,
    "dfl": 1.5,
    # === Detection Settings ===
    "nms": True,
    "iou": 0.7,  # NMS IoU (Phase 3 used 0.7)
    "max_det": 300,  # Max detections per image
    # === Hardware (MEMORY OPTIMIZED) ===
    "device": 0,  # RTX 3090 Ti
    "workers": 4,  # ✓ REDUCED from 8 (saves ~2GB RAM per worker)
    # Each worker pre-loads batches; fewer = less memory
    "amp": True,  # Mixed precision (FP16/FP32) - critical for memory
    "cache": False,  # Don't cache in RAM (save memory for larger batch)
    # Alternative: cache='disk' for speed/memory tradeoff
    # === Single Class Mode ===
    "single_cls": True,  # ✓ FIX: Phase 3 had this, Phase 4 didn't
    # === Checkpointing ===
    "save": True,
    "save_period": 5,  # Save every 5 epochs
    "val": True,
    "plots": True,
    "exist_ok": True,
    "deterministic": True,
    "seed": 0,
    "verbose": True,
}


# YOLOv8m-P2 Model Architecture (same as Phase 4)
P2_MODEL_CONFIG_CONTENT = """
# YOLOv8m-Face-P2: Medium model with P2 detection head for tiny faces
# Phase 5: Uses this architecture but initializes from Phase 3 weights

nc: 1  # Single class: face
depth_multiple: 0.67  # YOLOv8m depth
width_multiple: 0.75  # YOLOv8m width

# Backbone (CSPDarknet)
backbone:
  - [-1, 1, Conv, [64, 3, 2]]      # 0-P1/2
  - [-1, 1, Conv, [128, 3, 2]]     # 1-P2/4
  - [-1, 3, C2f, [128, True]]      # 2
  - [-1, 1, Conv, [256, 3, 2]]     # 3-P3/8
  - [-1, 6, C2f, [256, True]]      # 4
  - [-1, 1, Conv, [512, 3, 2]]     # 5-P4/16
  - [-1, 6, C2f, [512, True]]      # 6
  - [-1, 1, Conv, [512, 3, 2]]     # 7-P5/32
  - [-1, 3, C2f, [512, True]]      # 8
  - [-1, 1, SPPF, [512, 5]]        # 9

# Head with P2 detection (4 output scales for tiny face detection)
head:
  - [-1, 1, nn.Upsample, [None, 2, "nearest"]]  # 10
  - [[-1, 6], 1, Concat, [1]]                   # 11 cat P4
  - [-1, 3, C2f, [512]]                         # 12

  - [-1, 1, nn.Upsample, [None, 2, "nearest"]]  # 13
  - [[-1, 4], 1, Concat, [1]]                   # 14 cat P3
  - [-1, 3, C2f, [256]]                         # 15 (P3/8-small)

  - [-1, 1, nn.Upsample, [None, 2, "nearest"]]  # 16 - P2 upsample
  - [[-1, 2], 1, Concat, [1]]                   # 17 - cat P2
  - [-1, 3, C2f, [128]]                         # 18 - P2/4-xsmall (stride 4)

  - [-1, 1, Conv, [128, 3, 2]]                  # 19 - Downsample
  - [[-1, 15], 1, Concat, [1]]                  # 20 cat P3
  - [-1, 3, C2f, [256]]                         # 21 (P3/8-small)

  - [-1, 1, Conv, [256, 3, 2]]                  # 22 - Downsample
  - [[-1, 12], 1, Concat, [1]]                  # 23 cat P4
  - [-1, 3, C2f, [512]]                         # 24 (P4/16-medium)

  - [-1, 1, Conv, [512, 3, 2]]                  # 25 - Downsample
  - [[-1, 9], 1, Concat, [1]]                   # 26 cat P5
  - [-1, 3, C2f, [512]]                         # 27 (P5/32-large)

  - [[18, 21, 24, 27], 1, Detect, [nc]]         # 28 - Detect 4 scales: P2, P3, P4, P5
"""


def create_p2_model_config():
    """Create the P2 model config file."""
    global P2_MODEL_CONFIG

    working_dir = Path.cwd()
    config_path = working_dir / "yolov8m-face-p2.yaml"

    with open(config_path, "w") as f:
        f.write(P2_MODEL_CONFIG_CONTENT.strip())

    print(f"  ✓ Created P2 model config: {config_path}")
    P2_MODEL_CONFIG = config_path
    return config_path


def check_prerequisites():
    """Verify all required files exist."""
    print("=" * 70)
    print("PHASE 5 TRAINING - TRANSFER LEARNING FROM PHASE 3")
    print("=" * 70)

    # Create P2 config if needed
    if not P2_MODEL_CONFIG.exists():
        create_p2_model_config()

    checks = [
        ("P2 model config", P2_MODEL_CONFIG),
        ("Phase 5 weights (BASE)", PHASE5_WEIGHTS),  # CRITICAL!
        ("Training data", DATA_DIR / "data.yaml"),
    ]

    all_ok = True
    for name, path in checks:
        exists = path.exists()
        status = "✓" if exists else "✗"
        print(f"  {status} {name}: {path}")
        if not exists:
            all_ok = False
            if "Phase 3" in name:
                print(
                    f"    ⚠️  CRITICAL: Phase 3 checkpoint required for transfer learning!"
                )

    # Check GPU
    gpu_available = torch.cuda.is_available()
    gpu_name = torch.cuda.get_device_name(0) if gpu_available else "N/A"
    print(f"  {'✓' if gpu_available else '✗'} GPU: {gpu_name}")

    if gpu_available:
        gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1e9
        free_mem = (
            torch.cuda.get_device_properties(0).total_memory
            - torch.cuda.memory_allocated(0)
        ) / 1e9
        print(f"    Total Memory: {gpu_mem:.1f} GB")
        print(f"    Free Memory: {free_mem:.1f} GB")

        # Memory optimization status
        print("\n  Memory Optimizations:")
        alloc_conf = os.environ.get("PYTORCH_CUDA_ALLOC_CONF", "default")
        print(f"    ✓ PYTORCH_CUDA_ALLOC_CONF: {alloc_conf[:50]}...")
        print(f"    ✓ TF32 matmul: {torch.backends.cuda.matmul.allow_tf32}")
        print(f"    ✓ TF32 cuDNN: {torch.backends.cudnn.allow_tf32}")
        print(f"    ✓ cuDNN benchmark: {torch.backends.cudnn.benchmark}")
        print(f"    ✓ Batch size: {TRAINING_CONFIG['batch']} (optimized)")
        print(f"    ✓ Workers: {TRAINING_CONFIG['workers']} (reduced from 8)")
        print(f"    ✓ nbs (nominal batch): {TRAINING_CONFIG.get('nbs', 64)}")

    print()
    return all_ok and gpu_available


def create_data_yaml():
    """Create/verify the data.yaml for training."""
    data_yaml = DATA_DIR / "data.yaml"

    if not data_yaml.exists():
        print("Creating data.yaml...")
        config = {
            "path": str(DATA_DIR),
            "train": "images/train",
            "val": "images/val",
            "names": {0: "face"},
            "nc": 1,
        }
        with open(data_yaml, "w") as f:
            yaml.dump(config, f, default_flow_style=False)

    train_dir = DATA_DIR / "images/train"
    val_dir = DATA_DIR / "images/val"

    train_count = len(list(train_dir.glob("*.jpg"))) if train_dir.exists() else 0
    val_count = len(list(val_dir.glob("*.jpg"))) if val_dir.exists() else 0

    print(f"Dataset: {train_count} train, {val_count} val images")
    return str(data_yaml)


def print_training_summary():
    """Print training configuration with emphasis on fixes."""
    print("=" * 70)
    print("PHASE 5: CRITICAL FIXES + RESEARCH-BACKED OPTIMIZATIONS")
    print("=" * 70)

    print("\n🔴 ROOT CAUSE OF PHASE 4 REGRESSION:")
    print("   Phase 4 trained FROM SCRATCH using yolov8m-face-p2.yaml")
    print("   instead of starting from Phase 3 checkpoint!")
    print("   Also: mosaic=0.0, mixup=0.0, SGD optimizer, too high LR")

    print("\n✅ PHASE 5 FIXES:")
    print("┌─────────────────────┬──────────────────────┬────────────────────────┐")
    print("│ Parameter           │ Phase 4 (WRONG)      │ Phase 5 (FIXED)        │")
    print("├─────────────────────┼──────────────────────┼────────────────────────┤")
    print("│ Base Model          │ yolov8m-p2.yaml      │ Phase 3 best.pt        │")
    print("│ Transfer Learning   │ ❌ FROM SCRATCH      │ ✅ TRANSFER LEARNING   │")
    print("│ Optimizer           │ SGD                  │ AdamW                  │")
    print("│ Learning Rate       │ 0.005                │ 0.001                  │")
    print("│ Mosaic              │ 0.0 (disabled)       │ 1.0 (enabled)          │")
    print("│ MixUp               │ 0.0 (disabled)       │ 0.15 (enabled)         │")
    print("│ close_mosaic        │ not set              │ 15 epochs              │")
    print("│ single_cls          │ not set              │ True                   │")
    print("│ patience            │ 20                   │ 50                     │")
    print("│ label_smoothing     │ 0.0                  │ 0.1                    │")
    print("└─────────────────────┴──────────────────────┴────────────────────────┘")

    print("\n📊 EXPECTED IMPROVEMENTS:")
    print("┌─────────────┬───────────┬───────────┬───────────┐")
    print("│ Metric      │ Phase 4   │ Phase 5   │ Target    │")
    print("├─────────────┼───────────┼───────────┼───────────┤")
    print("│ mAP50       │ 80.64%    │ →86%+     │ 94%       │")
    print("│ Recall      │ 64.74%    │ →78%+     │ 95%       │")
    print("│ Precision   │ 93.81%    │ →92%+     │ 90%       │")
    print("│ Hard mAP50  │ 68.2%     │ →78%+     │ 85%       │")
    print("└─────────────┴───────────┴───────────┴───────────┘")

    print("\n📚 RESEARCH-BACKED OPTIMIZATIONS:")
    print("  • ML Engineering Book: Label smoothing 0.1, gradient checkpointing")
    print("  • JAX Scaling Book: Proper learning rate for transfer learning")
    print("  • Ultralytics Best Practices: close_mosaic for final refinement")
    print("  • Phase 3 Success: AdamW, mosaic=1.0, mixup=0.15, single_cls=True")

    print("\n🔧 MEMORY OPTIMIZATIONS (Batch 4 @ 1280px):")
    print("┌─────────────────────────────┬────────────────────────────────────────┐")
    print("│ Optimization                │ Effect                                 │")
    print("├─────────────────────────────┼────────────────────────────────────────┤")
    print("│ PYTORCH_CUDA_ALLOC_CONF     │ expandable_segments, GC at 80%         │")
    print("│ TF32 Tensor Cores           │ ~7x faster matmul on RTX 3090          │")
    print("│ workers=4 (from 8)          │ Saves ~2GB per worker                  │")
    print("│ nbs=64                      │ Gradient accum: eff. batch=64          │")
    print("│ batch=4 (from 2)            │ 2x throughput with memory opts         │")
    print("└─────────────────────────────┴────────────────────────────────────────┘")

    print("\n⚙️  CONFIGURATION:")
    print(f"  • Base: {PHASE5_WEIGHTS}")
    print(f"  • Architecture: P2 Detection Head (stride 4 for ~4px faces)")
    print(
        f"  • Resolution: {TRAINING_CONFIG['imgsz']}px (±{TRAINING_CONFIG['scale']*100:.0f}% scale)"
    )
    print(
        f"  • Epochs: {TRAINING_CONFIG['epochs']} (patience={TRAINING_CONFIG['patience']})"
    )
    print(
        f"  • Optimizer: {TRAINING_CONFIG['optimizer']} (lr={TRAINING_CONFIG['lr0']})"
    )
    print(
        f"  • Augmentation: mosaic={TRAINING_CONFIG['mosaic']}, mixup={TRAINING_CONFIG['mixup']}"
    )
    print(f"  • close_mosaic: Last {TRAINING_CONFIG['close_mosaic']} epochs")
    print(f"  • Output: {OUTPUT_NAME}")
    print()


def run_training(dry_run: bool = False, epochs: int = None):
    """Execute Phase 5 training with transfer learning from Phase 3.

    Args:
        dry_run: If True, validate config without training
        epochs: Override default epochs (useful for testing)
    """
    print_training_summary()

    if not check_prerequisites():
        print("❌ Prerequisites check failed. Exiting.")
        return None

    # Setup MLflow
    mlflow_enabled = setup_mlflow(dry_run=dry_run)

    data_yaml = create_data_yaml()

    if dry_run:
        print("\n" + "=" * 70)
        print("🔍 DRY RUN - VALIDATION MODE")
        print("=" * 70)
        print("\n✓ All prerequisites validated")
        print("✓ Data configuration verified")
        print(f"✓ Phase 5 checkpoint exists: {PHASE5_WEIGHTS.exists()}")
        print(f"✓ Output directory: {OUTPUT_DIR}")
        print(f"✓ MLflow available: {MLFLOW_AVAILABLE}")

        # Show what would be trained
        print("\n📋 TRAINING CONFIGURATION (would use):")
        print(f"   • Base model: {PHASE5_WEIGHTS}")
        print(f"   • Data: {data_yaml}")
        print(f"   • Epochs: {epochs or TRAINING_CONFIG['epochs']}")
        print(f"   • Batch size: {TRAINING_CONFIG['batch']}")
        print(f"   • Resolution: {TRAINING_CONFIG['imgsz']}px")
        print(f"   • Optimizer: {TRAINING_CONFIG['optimizer']}")
        print(f"   • Learning rate: {TRAINING_CONFIG['lr0']}")
        print(f"   • Mosaic: {TRAINING_CONFIG['mosaic']}")
        print(f"   • MixUp: {TRAINING_CONFIG['mixup']}")

        # GPU check
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1e9
            print(f"\n🖥️  GPU: {gpu_name} ({gpu_mem:.1f} GB)")
            print(f"   Memory optimizations: ACTIVE")
            print(f"   TF32: {torch.backends.cuda.matmul.allow_tf32}")
            print(f"   cuDNN benchmark: {torch.backends.cudnn.benchmark}")

        # Service check
        print("\n🔗 SERVICE INTEGRATION:")
        print(f"   • MLflow: {MLFLOW_CONFIG['tracking_uri']}")
        print(f"   • Grafana: http://localhost/grafana/")
        print(f"   • Prometheus: http://localhost/prometheus/")
        print(f"   • Pushgateway: {PUSHGATEWAY_CONFIG['url']}")
        print(f"   • Prometheus available: {PROMETHEUS_AVAILABLE}")

        # Test pushgateway connection
        if PROMETHEUS_AVAILABLE:
            try:
                import urllib.request

                req = urllib.request.urlopen(
                    f"http://{PUSHGATEWAY_CONFIG['url']}/metrics", timeout=2
                )
                print(f"   • Pushgateway status: ✅ Connected")
            except Exception as e:
                print(f"   • Pushgateway status: ⚠️  {e}")

        print("\n✅ DRY RUN COMPLETE - Ready for training!")
        print(f"   Run without --dry-run to start training")
        return None

    print("=" * 70)
    print("STARTING PHASE 6 RUN 1 TRAINING (Reduced Augmentation)")
    print("=" * 70)

    # Initialize metrics reporter for Grafana
    reporter = init_metrics_reporter()

    # Start MLflow run
    if mlflow_enabled:
        start_mlflow_run()

    # === MEMORY OPTIMIZATION: Clear any existing allocations ===
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        print("\n🔧 Memory optimization: Cleared CUDA cache")
        print(f"   Current allocation: {torch.cuda.memory_allocated(0)/1e9:.2f} GB")
        print(f"   Reserved memory: {torch.cuda.memory_reserved(0)/1e9:.2f} GB")

    # CRITICAL: Load Phase 5 model as base
    print(f"\n📦 Loading Phase 5 checkpoint: {PHASE5_WEIGHTS}")
    print("   Phase 5 Performance: 85.90% eval mAP@50, 76.91% recall, 88.11% precision")
    print("   Testing hypothesis: Reduced augmentation improves convergence")

    # Verify Phase 5 checkpoint exists
    if not PHASE5_WEIGHTS.exists():
        raise FileNotFoundError(
            f"Phase 5 checkpoint not found: {PHASE5_WEIGHTS}\n"
            f"Expected location: {CHECKPOINT_DIR}/phase_5_yolov8m_p2_20251216_004521/weights/best.pt\n"
            "Please ensure Phase 5 training completed successfully."
        )

    # Load the Phase 5 model
    # Continue fine-tuning with reduced augmentation
    model = YOLO(str(PHASE5_WEIGHTS))

    print(f"\n✓ Phase 5 model loaded successfully")
    print(f"  Model type: {type(model)}")

    # Memory status after loading
    if torch.cuda.is_available():
        print(f"  Memory after model load: {torch.cuda.memory_allocated(0)/1e9:.2f} GB")

    # Configure training with all fixes
    train_config = TRAINING_CONFIG.copy()
    if epochs is not None:
        train_config["epochs"] = epochs
        print(f"  ⚠️  Epochs overridden: {epochs}")

    train_args = {
        "data": data_yaml,
        "project": str(CHECKPOINT_DIR),
        "name": OUTPUT_NAME,
        "pretrained": True,  # Use pretrained weights from Phase 5
        **train_config,
    }

    print(f"\n🚀 Starting training with {train_config['epochs']} epochs...")
    print(f"   Using transfer learning from Phase 5")
    print(
        f"   Hypothesis: Reduced augmentation (mosaic={train_config['mosaic']}, mixup={train_config['mixup']}) improves convergence"
    )
    print(f"   Phase 5 had: mosaic=1.0, mixup=0.15 (heavy)")
    print(
        f"   Phase 6 Run 1: mosaic={train_config['mosaic']}, mixup={train_config['mixup']} (gentler)"
    )
    print(f"   MixUp: {train_config['mixup']} (was 0.0 in Phase 4)")
    print(f"   Optimizer: {train_config['optimizer']} (was SGD in Phase 4)")
    print(f"   Batch size: {train_config['batch']} (memory optimized)")
    print(f"   Effective batch (nbs): {train_config.get('nbs', 64)}")

    # Disable Ultralytics built-in MLflow callback (uses OAuth-protected endpoint)
    # We'll log results manually after training completes
    if "MLFLOW_TRACKING_URI" in os.environ:
        del os.environ["MLFLOW_TRACKING_URI"]
    os.environ["MLFLOW_TRACKING_URI"] = ""  # Explicitly disable
    print("   MLflow: Disabled (OAuth protected, will log manually)")
    print(
        f"   Grafana metrics: {'✅ Enabled' if reporter and reporter.enabled else '⚠️  Disabled'}"
    )

    # Add custom callback for real-time metrics
    def on_train_epoch_end(trainer):
        """Callback to push metrics after each epoch."""
        if reporter and reporter.enabled:
            try:
                # Get metrics from trainer
                metrics = trainer.metrics
                epoch = trainer.epoch + 1
                total_epochs = trainer.epochs

                # Extract losses and performance metrics
                box_loss = (
                    float(trainer.loss_items[0])
                    if hasattr(trainer, "loss_items") and trainer.loss_items is not None
                    else None
                )
                cls_loss = (
                    float(trainer.loss_items[1])
                    if hasattr(trainer, "loss_items")
                    and trainer.loss_items is not None
                    and len(trainer.loss_items) > 1
                    else None
                )
                dfl_loss = (
                    float(trainer.loss_items[2])
                    if hasattr(trainer, "loss_items")
                    and trainer.loss_items is not None
                    and len(trainer.loss_items) > 2
                    else None
                )

                map50 = metrics.get("metrics/mAP50(B)", None)
                map50_95 = metrics.get("metrics/mAP50-95(B)", None)
                precision = metrics.get("metrics/precision(B)", None)
                recall = metrics.get("metrics/recall(B)", None)

                reporter.report_epoch(
                    epoch=epoch,
                    total_epochs=total_epochs,
                    box_loss=box_loss,
                    cls_loss=cls_loss,
                    dfl_loss=dfl_loss,
                    map50=map50,
                    map50_95=map50_95,
                    precision=precision,
                    recall=recall,
                )

                # Also report GPU metrics
                reporter.report_gpu_metrics()

                # Log progress
                if epoch % 10 == 0 or epoch == 1:
                    print(
                        f"\n📊 Epoch {epoch}/{total_epochs} metrics pushed to Grafana"
                    )
                    if map50 is not None:
                        print(
                            f"   mAP50: {map50:.4f} (best: {reporter.best_map50:.4f})"
                        )
                        print(
                            f"   vs Phase 3: {map50 - REGRESSION_THRESHOLDS['phase3_map50']:+.4f}"
                        )
                        print(
                            f"   vs Phase 4: {map50 - REGRESSION_THRESHOLDS['phase4_map50']:+.4f}"
                        )
                    if reporter.epochs_since_improvement > 10:
                        print(
                            f"   ⚠️  No improvement for {reporter.epochs_since_improvement} epochs"
                        )
            except Exception as e:
                print(f"   ⚠️  Metrics callback error: {e}")

    # Register callback with model
    model.add_callback("on_train_epoch_end", on_train_epoch_end)
    print("   ✓ Registered epoch callback for Grafana metrics")

    try:
        # Train!
        results = model.train(**train_args)

        print("\n" + "=" * 70)
        print("TRAINING COMPLETE")
        print("=" * 70)
        print(f"Output directory: {OUTPUT_DIR}")

        # Log results to MLflow
        if mlflow_enabled:
            log_training_results(results, OUTPUT_DIR)
            end_mlflow_run("FINISHED")

        # Final metrics push and summary
        if reporter and reporter.enabled:
            print("\n📊 REGRESSION MONITORING SUMMARY:")
            print(f"   Best mAP50 achieved: {reporter.best_map50:.4f}")
            print(f"   Best Recall achieved: {reporter.best_recall:.4f}")
            print(
                f"   vs Phase 3 mAP50: {reporter.best_map50 - REGRESSION_THRESHOLDS['phase3_map50']:+.4f}"
            )
            print(
                f"   vs Phase 4 mAP50: {reporter.best_map50 - REGRESSION_THRESHOLDS['phase4_map50']:+.4f}"
            )
            if reporter.regression_warnings:
                print(f"\n   ⚠️  Regression warnings during training:")
                for warning in reporter.regression_warnings[-5:]:  # Last 5 warnings
                    print(f"      - {warning}")
            else:
                print(f"   ✅ No regression warnings!")

        return results

    except Exception as e:
        print(f"\n❌ Training failed: {e}")
        if mlflow_enabled:
            if MLFLOW_AVAILABLE:
                mlflow.log_param("error", str(e)[:250])
            end_mlflow_run("FAILED")
        if reporter:
            reporter.cleanup()
        raise
    finally:
        # Don't cleanup metrics on success - keep them visible in Grafana
        pass


def analyze_training_results():
    """Analyze and compare results to Phase 3 and Phase 4."""
    results_file = OUTPUT_DIR / "results.csv"

    if results_file.exists():
        import pandas as pd

        df = pd.read_csv(results_file)

        print("\n📊 TRAINING RESULTS:")
        print(f"  Best mAP50: {df['metrics/mAP50(B)'].max():.4f}")
        print(f"  Best mAP50-95: {df['metrics/mAP50-95(B)'].max():.4f}")
        print(f"  Final Epoch: {len(df)}")

        # Compare to Phase 4
        phase4_map = 0.8064
        phase5_map = df["metrics/mAP50(B)"].max()
        improvement = (phase5_map - phase4_map) * 100

        print(f"\n📈 COMPARISON TO PHASE 4:")
        print(f"  Phase 4 mAP50: {phase4_map:.2%}")
        print(f"  Phase 5 mAP50: {phase5_map:.2%}")
        print(f"  Improvement: {'+' if improvement > 0 else ''}{improvement:.2f}%")

        if phase5_map > phase4_map:
            print("  ✅ Phase 5 outperforms Phase 4!")
        else:
            print("  ⚠️  Still investigating...")


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Phase 5 Face Detection Training - YOLOv8m-P2 with Transfer Learning",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run - validate configuration
  python train_phase5_yolov8m_p2.py --dry-run

  # Full training with MLflow
  python train_phase5_yolov8m_p2.py

  # Quick test with 5 epochs
  python train_phase5_yolov8m_p2.py --epochs 5

  # Specify MLflow experiment
  python train_phase5_yolov8m_p2.py --mlflow-experiment "my-experiment"
        """,
    )

    parser.add_argument(
        "--dry-run", action="store_true", help="Validate configuration without training"
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=None,
        help="Override number of epochs (default: 200)",
    )
    parser.add_argument(
        "--mlflow-uri",
        type=str,
        default=None,
        help="MLflow tracking URI (default: http://localhost/mlflow/)",
    )
    parser.add_argument(
        "--mlflow-experiment",
        type=str,
        default=None,
        help="MLflow experiment name (default: Face-Detection-P2)",
    )
    parser.add_argument(
        "--batch", type=int, default=None, help="Override batch size (default: 4)"
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    # Override MLflow config if specified
    if args.mlflow_uri:
        MLFLOW_CONFIG["tracking_uri"] = args.mlflow_uri
    if args.mlflow_experiment:
        MLFLOW_CONFIG["experiment_name"] = args.mlflow_experiment
    if args.batch:
        TRAINING_CONFIG["batch"] = args.batch

    print("\n" + "=" * 70)
    print("PHASE 5: YOLOv8m-P2 FACE DETECTION (FIXED TRANSFER LEARNING)")
    print("=" * 70)

    if args.dry_run:
        print("\n🔍 Running in DRY RUN mode - no training will occur")

    try:
        # Run training
        results = run_training(dry_run=args.dry_run, epochs=args.epochs)

        # Analyze results (only if actual training occurred)
        if results:
            analyze_training_results()
            print("\n✅ Phase 5 training complete!")
            print(f"   Output: {OUTPUT_DIR}")
            print(f"\n📊 View in MLflow: {MLFLOW_CONFIG['tracking_uri']}")
            print(f"📈 View in Grafana: http://localhost/grafana/")
            print(f"\n🔍 Next: Run evaluation with:")
            print(f"   python wider_face_eval.py --model {OUTPUT_DIR}/weights/best.pt")
    finally:
        # Always reclaim GPU after training
        reclaim_gpu_after_training(gpu_id=0, job_id=_job_id)
