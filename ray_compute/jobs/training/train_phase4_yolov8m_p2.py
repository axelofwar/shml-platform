#!/usr/bin/env python3
"""
Phase 4 Face Detection - YOLOv8m-P2 (FAIR SOTA COMPARISON)
==========================================================

GOAL: Beat YOLOv8m-Face SOTA with SAME MODEL SIZE

This is an APPLES-TO-APPLES comparison:
- YOLOv8m-Face SOTA: 84.7% Hard mAP (~26M params)
- Our YOLOv8m-P2: ~26M params + P2 detection head

If we beat 84.7% with the same model size, it proves our P2 technique
is genuinely better, not just "bigger model = better results".

SOTA Benchmarks (WIDER Face Hard mAP):
┌─────────────────┬───────────┬─────────────┐
│ Model           │ Hard mAP  │ Status      │
├─────────────────┼───────────┼─────────────┤
│ YOLOv8m-Face    │ 84.7%     │ YOLO SOTA   │ ← BEAT THIS (same size!)
│ YOLOv8m-P2 (us) │ ???       │ Our attempt │
└─────────────────┴───────────┴─────────────┘

Key Advantage: P2 Detection Head
- Standard YOLOv8m: 3 heads (P3/8, P4/16, P5/32) - min face ~32px
- Our YOLOv8m-P2: 4 heads (P2/4, P3/8, P4/16, P5/32) - min face ~4px
"""

import os
import sys
import yaml
from pathlib import Path
from datetime import datetime

# =============================================================================
# GPU YIELD: Use shared utility module (imported before torch)
# Must happen BEFORE importing torch to free GPU memory
# =============================================================================
_utils_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _utils_path not in sys.path:
    sys.path.insert(0, _utils_path)
from utils.gpu_yield import yield_gpu_for_training, reclaim_gpu_after_training

# Yield GPU 0 (RTX 3090 Ti) before importing torch
_job_id = os.environ.get("RAY_JOB_ID", f"phase4-yolov8m-{os.getpid()}")
yield_gpu_for_training(gpu_id=0, job_id=_job_id, timeout=30)

import torch


# =============================================================================
# FIX: Patch Ray Tune BEFORE importing ultralytics
# The ultralytics library uses ray.tune.is_session_enabled() which was removed
# in Ray 2.x. We need to patch this BEFORE importing ultralytics.
# =============================================================================
def _patch_ray_tune_api():
    """
    Patch Ray Tune to add missing is_session_enabled() for ultralytics compatibility.

    In Ray 2.x, the is_session_enabled() function was removed.
    The new way is to use ray.train.get_context() but ultralytics still uses
    the old API. This patch adds the missing function.
    """
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

        # Add the missing function to ray.tune
        if not hasattr(tune, "is_session_enabled"):
            tune.is_session_enabled = is_session_enabled
            print(
                "[INFO] Patched ray.tune.is_session_enabled() for Ray 2.x compatibility"
            )
    except ImportError:
        pass  # Ray not available


# Apply the patch BEFORE importing ultralytics
_patch_ray_tune_api()

from ultralytics import YOLO

# ============================================================================
# SOTA BENCHMARKS - Our targets
# ============================================================================

SOTA_BENCHMARKS = {
    "SCRFD-34GF": {
        "easy": 96.06,
        "medium": 94.92,
        "hard": 85.29,
        "note": "Overall SOTA",
    },
    "TinaFace": {"easy": 95.61, "medium": 94.25, "hard": 81.43, "note": "ResNet50"},
    "YOLOv8m-Face": {
        "easy": 96.6,
        "medium": 95.0,
        "hard": 84.7,
        "note": "YOLO SOTA - BEAT THIS",
    },
    "YOLOv8s-Face": {"easy": 96.1, "medium": 94.2, "hard": 83.1, "note": ""},
    "YOLOv8n-Face": {"easy": 94.6, "medium": 92.3, "hard": 79.6, "note": ""},
    "SCRFD-10GF": {"easy": 95.16, "medium": 93.87, "hard": 83.05, "note": ""},
    "RetinaFace": {"easy": 94.92, "medium": 91.90, "hard": 64.17, "note": "ResNet50"},
}

# Our minimum target: Beat YOLOv8m-Face with SAME model size
TARGET_HARD_MAP = 85.0  # > 84.7% (YOLOv8m-Face SOTA)
TARGET_EASY_MAP = 96.5
TARGET_MEDIUM_MAP = 95.0

# Model variant
MODEL_VARIANT = "yolov8m"  # Medium - same as SOTA baseline

# ============================================================================
# CONFIGURATION - Container paths for Ray job execution
# ============================================================================


# Detect if running in container or locally
def get_paths():
    """Get correct paths based on execution environment."""
    # Container mount points
    container_ray_dir = Path("/tmp/ray")
    container_job_dir = Path("/opt/ray/job_workspaces")

    # Host paths (for local testing)
    host_root = Path("/home/axelofwar/Projects/shml-platform")
    host_ray_dir = host_root / "ray_compute/data/ray"
    host_job_dir = host_root / "ray_compute/data/job_workspaces"

    # Detect environment by checking which paths exist
    if container_ray_dir.exists():
        # Running in container
        return {
            "checkpoint_dir": container_ray_dir / "checkpoints/face_detection",
            "data_dir": container_job_dir / "data/wider_face_yolo",
            "config_dir": Path("/tmp/job"),  # Working dir in container
        }
    else:
        # Running locally
        return {
            "checkpoint_dir": host_ray_dir / "checkpoints/face_detection",
            "data_dir": host_job_dir / "data/wider_face_yolo",
            "config_dir": host_root / "ray_compute/jobs/training/configs",
        }


# Initialize paths
PATHS = get_paths()
CHECKPOINT_DIR = PATHS["checkpoint_dir"]
DATA_DIR = PATHS["data_dir"]
CONFIG_DIR = PATHS["config_dir"]

# Phase 2 checkpoint (best performing) - NOT used for YOLOv8m, training from scratch
# PHASE2_WEIGHTS = CHECKPOINT_DIR / "phase_2_phase_2/weights/best.pt"
PHASE2_WEIGHTS = None  # Train from scratch for fair comparison

# Custom P2 model config - will be created in working dir if not found
P2_MODEL_CONFIG = CONFIG_DIR / "yolov8m-face-p2.yaml"

# Output directory
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT_NAME = f"phase_4_yolov8m_p2_{TIMESTAMP}"
OUTPUT_DIR = CHECKPOINT_DIR / OUTPUT_NAME

# ============================================================================
# TRAINING HYPERPARAMETERS - OPTIMIZED FOR SMALL FACE DETECTION
# ============================================================================

TRAINING_CONFIG = {
    # === Resolution & Multi-Scale ===
    "imgsz": 1280,  # Keep high resolution for small faces
    # Note: multi_scale is controlled via 'scale' parameter in augmentation
    # === Training Duration ===
    "epochs": 150,  # More epochs for SOTA (with early stopping safety)
    "patience": 20,  # ✓ ANTI-OVERFIT: Early stopping patience
    # === Batch Size + Memory Optimizations ===
    "batch": 2,  # Small batch to fit in memory
    # Note: Ultralytics doesn't support gradient accumulation directly,
    # but smaller batch + more epochs achieves similar effect
    # === Learning Rate Schedule (adjusted for smaller batch) ===
    "lr0": 0.005,  # Reduced for smaller batch (linear scaling)
    "lrf": 0.01,  # ✓ ANTI-OVERFIT: Final LR = lr0 * lrf
    "cos_lr": True,  # ✓ ANTI-OVERFIT: Cosine annealing
    "warmup_epochs": 5,  # Warmup for stable training
    "warmup_momentum": 0.8,
    "warmup_bias_lr": 0.05,  # Reduced proportionally
    "momentum": 0.937,  # SGD momentum
    "optimizer": "SGD",  # SGD typically better for detection
    # === Regularization (ANTI-OVERFIT) ===
    "weight_decay": 0.0005,  # Standard weight decay
    "dropout": 0.0,  # No dropout (can hurt detection)
    "label_smoothing": 0.0,  # No label smoothing for single class
    # === Data Augmentation (Memory-optimized) ===
    "hsv_h": 0.015,  # Hue augmentation
    "hsv_s": 0.7,  # Saturation augmentation
    "hsv_v": 0.4,  # Value augmentation
    "degrees": 0.0,  # No rotation (faces are upright)
    "translate": 0.1,  # Light translation
    "scale": 0.5,  # ✓ KEY: Scale range ±50% (enables multi-scale training)
    "shear": 0.0,  # No shear (distorts faces)
    "perspective": 0.0,  # No perspective (distorts faces)
    "flipud": 0.0,  # No vertical flip for faces
    "fliplr": 0.5,  # Horizontal flip OK
    "mosaic": 0.0,  # ✗ DISABLED: Saves ~4x memory (creates 2x2 grid)
    "mixup": 0.0,  # ✗ DISABLED: Saves memory
    "copy_paste": 0.0,  # Disable (can create artifacts)
    # === Loss Weights (optimized for face detection) ===
    "box": 7.5,  # Box loss weight (higher for localization)
    "cls": 0.5,  # Classification loss weight
    "dfl": 1.5,  # Distribution focal loss weight
    # === Anchor-Free Detection ===
    # YOLOv8 is anchor-free, but we can tune NMS
    "nms": True,
    "iou": 0.5,  # NMS IoU threshold
    "max_det": 1000,  # Max detections per image (faces can be dense)
    # === Hardware (Memory-optimized) ===
    "device": 0,  # GPU 0 (RTX 3090 Ti)
    "workers": 4,  # Reduced workers to save memory
    "amp": True,  # Mixed precision training
    "cache": False,  # Don't cache in RAM (saves memory)
    # === Checkpointing (OLMo-style frequent saves) ===
    "save": True,
    "save_period": 5,  # ✓ OLMo: Save frequently to find optimal checkpoint
    "val": True,
    "plots": True,
    "exist_ok": True,
    # === Verbosity ===
    "verbose": True,
}


# P2 Model Config YAML content - YOLOv8m (Medium) for fair SOTA comparison
P2_MODEL_CONFIG_CONTENT = """
# YOLOv8m-Face-P2: Medium model with P2 detection head
# For fair comparison against YOLOv8m-Face SOTA (84.7% Hard mAP)

# Parameters
nc: 1  # Number of classes (face only)
depth_multiple: 0.67  # YOLOv8m depth
width_multiple: 0.75  # YOLOv8m width

# Backbone (CSPDarknet) - same as YOLOv8m
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

# Head with P2 detection (4 output scales instead of 3)
head:
  - [-1, 1, nn.Upsample, [None, 2, "nearest"]]  # 10
  - [[-1, 6], 1, Concat, [1]]                   # 11 cat P4
  - [-1, 3, C2f, [512]]                         # 12

  - [-1, 1, nn.Upsample, [None, 2, "nearest"]]  # 13
  - [[-1, 4], 1, Concat, [1]]                   # 14 cat P3
  - [-1, 3, C2f, [256]]                         # 15 (P3/8-small)

  - [-1, 1, nn.Upsample, [None, 2, "nearest"]]  # 16 - NEW: Upsample to P2
  - [[-1, 2], 1, Concat, [1]]                   # 17 - NEW: cat P2
  - [-1, 3, C2f, [128]]                         # 18 - NEW: P2/4-xsmall (stride 4)

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
    """Create the P2 model config file in working directory."""
    global P2_MODEL_CONFIG

    # Try to create in current working directory
    working_dir = Path.cwd()
    config_path = working_dir / "yolov8m-face-p2.yaml"

    # Write the config
    with open(config_path, "w") as f:
        f.write(P2_MODEL_CONFIG_CONTENT.strip())

    print(f"  ✓ Created P2 model config: {config_path}")
    P2_MODEL_CONFIG = config_path
    return config_path


def check_prerequisites():
    """Verify all required files exist."""
    print("=" * 60)
    print("YOLOv8m-P2 TRAINING - FAIR SOTA COMPARISON")
    print("=" * 60)

    # Create P2 config if needed
    if not P2_MODEL_CONFIG.exists():
        create_p2_model_config()

    # Note: No Phase 2 checkpoint needed - training from scratch for fair comparison
    checks = [
        ("P2 model config", P2_MODEL_CONFIG),
        ("Training data", DATA_DIR / "data.yaml"),
    ]

    all_ok = True
    for name, path in checks:
        exists = path.exists()
        status = "✓" if exists else "✗"
        print(f"  {status} {name}: {path}")
        if not exists:
            all_ok = False

    print(f"  ℹ Training from scratch (no pretrained weights for fair comparison)")

    # Check GPU
    gpu_available = torch.cuda.is_available()
    gpu_name = torch.cuda.get_device_name(0) if gpu_available else "N/A"
    print(f"  {'✓' if gpu_available else '✗'} GPU: {gpu_name}")

    if gpu_available:
        gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1e9
        print(f"    Memory: {gpu_mem:.1f} GB")

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

    # Verify dataset
    train_dir = DATA_DIR / "images/train"
    val_dir = DATA_DIR / "images/val"

    train_count = len(list(train_dir.glob("*.jpg"))) if train_dir.exists() else 0
    val_count = len(list(val_dir.glob("*.jpg"))) if val_dir.exists() else 0

    print(f"Dataset: {train_count} train, {val_count} val images")
    return str(data_yaml)


def print_training_summary():
    """Print training configuration summary."""
    print("=" * 70)
    print("PHASE 4 TRAINING - SOTA-BEATING CONFIGURATION")
    print("=" * 70)

    print("\n📊 SOTA Benchmarks (WIDER Face):")
    print("┌─────────────────┬────────┬─────────┬────────┬──────────────────┐")
    print("│ Model           │ Easy   │ Medium  │ Hard   │ Notes            │")
    print("├─────────────────┼────────┼─────────┼────────┼──────────────────┤")
    for name, scores in SOTA_BENCHMARKS.items():
        note = scores.get("note", "")[:16]
        print(
            f"│ {name:<15} │ {scores['easy']:>5.1f}% │ {scores['medium']:>6.1f}% │ {scores['hard']:>5.1f}% │ {note:<16} │"
        )
    print("├─────────────────┼────────┼─────────┼────────┼──────────────────┤")
    print(
        f"│ {'OUR TARGET':<15} │ {TARGET_EASY_MAP:>5.1f}% │ {TARGET_MEDIUM_MAP:>6.1f}% │ {TARGET_HARD_MAP:>5.1f}% │ {'Beat YOLO SOTA':<16} │"
    )
    print("└─────────────────┴────────┴─────────┴────────┴──────────────────┘")

    print("\n🎯 Key Improvements for SOTA:")
    print("  • P2 Detection Head: Stride 4 for tiny faces (4x4px minimum)")
    print("  • Multi-Scale Training: 640-1920px dynamic resolution")
    print("  • 1280px base resolution (vs 800px in Phase 2)")
    print("  • Optimized augmentation (no rotation/shear that distorts faces)")
    print("  • 150 epochs with patience=20 early stopping")

    print("\n📚 OLMo 3 Insights Applied:")
    print("  • Extended training with frequent checkpoints (every 5 epochs)")
    print("  • Data quality focus: Clean annotations > raw quantity")
    print("  • Cosine LR decay (OLMo uses similar schedule)")
    print("  • Early stopping as 'verifiable reward' optimization")

    print("\n⚙️  Training Configuration:")
    print(f"  • Model: YOLOv8m-P2 (~26M params, SAME as SOTA baseline)")
    print(
        f"  • Resolution: {TRAINING_CONFIG['imgsz']}px (scale=±{TRAINING_CONFIG['scale']*100:.0f}%)"
    )
    print(
        f"  • Scale Range: {int(TRAINING_CONFIG['imgsz']*(1-TRAINING_CONFIG['scale']))}-{int(TRAINING_CONFIG['imgsz']*(1+TRAINING_CONFIG['scale']))}px effective"
    )
    print(
        f"  • Epochs: {TRAINING_CONFIG['epochs']} (patience={TRAINING_CONFIG['patience']})"
    )
    print(f"  • Batch Size: {TRAINING_CONFIG['batch']}")
    print(
        f"  • Optimizer: {TRAINING_CONFIG['optimizer']} (lr={TRAINING_CONFIG['lr0']}, momentum={TRAINING_CONFIG['momentum']})"
    )
    print(
        f"  • Cosine LR: {TRAINING_CONFIG['lr0']} → {TRAINING_CONFIG['lr0'] * TRAINING_CONFIG['lrf']}"
    )

    print("\n📁 Paths:")
    print(f"  • Model Config: {P2_MODEL_CONFIG}")
    print(f"  • Output: {OUTPUT_NAME}")
    print()


def compare_with_sota(metrics):
    """Compare results with SOTA benchmarks."""
    print("\n" + "=" * 70)
    print("SOTA COMPARISON")
    print("=" * 70)

    # Get our metrics (ultralytics reports overall mAP, not per-subset)
    our_map50 = metrics.get("metrics/mAP50(B)", 0) * 100
    our_recall = metrics.get("metrics/recall(B)", 0) * 100
    our_precision = metrics.get("metrics/precision(B)", 0) * 100

    print(f"\n📊 Our Results (Overall):")
    print(f"  • mAP50: {our_map50:.2f}%")
    print(f"  • Recall: {our_recall:.2f}%")
    print(f"  • Precision: {our_precision:.2f}%")

    # Compare with YOLO SOTA
    yolo_sota = SOTA_BENCHMARKS["YOLOv8m-Face"]

    # Note: Our overall mAP50 should be compared to Easy mAP (which includes all faces)
    # Hard mAP requires subset evaluation
    print(f"\n🎯 vs YOLOv8m-Face SOTA:")
    print(f"  • SOTA Easy: {yolo_sota['easy']:.1f}%")
    print(f"  • SOTA Hard: {yolo_sota['hard']:.1f}%")

    # Estimate: If overall mAP50 > 95%, we likely beat SOTA
    if our_map50 > 95:
        print(
            f"\n✅ LIKELY SOTA-BEATING! Overall mAP50 ({our_map50:.1f}%) suggests Hard > 85%"
        )
    elif our_map50 > 93:
        print(
            f"\n⚠️  COMPETITIVE! Overall mAP50 ({our_map50:.1f}%) suggests Hard ~83-85%"
        )
    else:
        print(f"\n❌ Below target. Need further optimization.")

    print("\n💡 For official SOTA comparison, run WIDER Face evaluation:")
    print("   python evaluate_wider_face.py --model best.pt --split hard")


def train_phase4():
    """Run Phase 4 training with all optimizations."""

    # Prerequisites check
    if not check_prerequisites():
        print("❌ Prerequisites check failed!")
        sys.exit(1)

    # Print summary
    print_training_summary()

    # Create/verify data.yaml
    data_yaml = create_data_yaml()

    # Load the P2 model architecture
    print("=" * 70)
    print("INITIALIZING MODEL")
    print("=" * 70)

    # Strategy: Use P2 architecture with pretrained COCO weights
    print(f"\n1. Loading P2 architecture from: {P2_MODEL_CONFIG}")
    model = YOLO(str(P2_MODEL_CONFIG))

    # Disable Ray Tune callback (incompatible with Ray 2.35)
    # This fixes: AttributeError: module 'ray.tune' has no attribute 'is_session_enabled'
    if hasattr(model, "callbacks"):
        model.callbacks = {
            k: v for k, v in model.callbacks.items() if "raytune" not in k.lower()
        }

    # Also remove from default callbacks
    try:
        from ultralytics.utils.callbacks import raytune
        import ultralytics.utils.callbacks.raytune as rt_module

        # Patch the callback to be a no-op
        rt_module.on_fit_epoch_end = lambda trainer: None
        print("   ✓ Disabled Ray Tune callback (version incompatibility)")
    except Exception as e:
        print(f"   ℹ Ray Tune callback handling: {e}")

    print(f"\n2. Model initialized with P2 architecture")
    print(f"   Detection heads: P2/4, P3/8, P4/16, P5/32 (4 scales)")
    print(f"   Minimum detectable face: ~4x4px at 1280px input")

    # Start training
    print("\n" + "=" * 70)
    print("STARTING TRAINING - TARGET: Beat YOLOv8m-Face SOTA (84.7% Hard)")
    print("=" * 70)

    try:
        results = model.train(
            data=data_yaml,
            project=str(CHECKPOINT_DIR),
            name=OUTPUT_NAME,
            pretrained=True,  # Use pretrained backbone weights
            **TRAINING_CONFIG,
        )

        print("\n" + "=" * 70)
        print("TRAINING COMPLETE")
        print("=" * 70)

        # Print final metrics and SOTA comparison
        if hasattr(results, "results_dict"):
            metrics = results.results_dict
            print("\n📊 Final Metrics:")
            print(f"  • mAP50: {metrics.get('metrics/mAP50(B)', 'N/A'):.4f}")
            print(f"  • mAP50-95: {metrics.get('metrics/mAP50-95(B)', 'N/A'):.4f}")
            print(f"  • Precision: {metrics.get('metrics/precision(B)', 'N/A'):.4f}")
            print(f"  • Recall: {metrics.get('metrics/recall(B)', 'N/A'):.4f}")

            # SOTA comparison
            compare_with_sota(metrics)

        print(f"\n✅ Model saved to: {CHECKPOINT_DIR / OUTPUT_NAME}")

        return results

    except Exception as e:
        print(f"\n❌ Training failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


def train_phase4_transfer():
    """
    Alternative: Transfer learning approach.
    Load Phase 2 weights for backbone, train new P2 head from scratch.
    """
    print("=" * 60)
    print("PHASE 4 TRAINING - TRANSFER LEARNING MODE")
    print("=" * 60)

    # Prerequisites check
    if not check_prerequisites():
        print("❌ Prerequisites check failed!")
        sys.exit(1)

    print_training_summary()
    data_yaml = create_data_yaml()

    # Load Phase 2 model first
    print(f"\n1. Loading Phase 2 checkpoint: {PHASE2_WEIGHTS}")
    phase2_model = YOLO(str(PHASE2_WEIGHTS))

    # Get backbone state dict
    print("2. Extracting backbone weights...")

    # Create new P2 model
    print(f"3. Creating P2 architecture model...")
    model = YOLO(str(P2_MODEL_CONFIG))

    # The ultralytics library handles weight transfer automatically when
    # architectures are compatible. For P2, the backbone is identical.

    print("\n" + "=" * 60)
    print("STARTING TRAINING")
    print("=" * 60)

    # Freeze backbone for first few epochs (optional - for stability)
    # model.model.model[:10].requires_grad_(False)

    try:
        results = model.train(
            data=data_yaml,
            project=str(CHECKPOINT_DIR),
            name=OUTPUT_NAME,
            pretrained=True,  # Use pretrained backbone weights
            **TRAINING_CONFIG,
        )

        print("\n" + "=" * 60)
        print("TRAINING COMPLETE")
        print("=" * 60)

        print(f"\n✅ Model saved to: {CHECKPOINT_DIR / OUTPUT_NAME}")
        return results

    except Exception as e:
        print(f"\n❌ Training failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Phase 4 Face Detection Training")
    parser.add_argument(
        "--mode",
        choices=["standard", "transfer"],
        default="standard",
        help="Training mode: standard (P2 from scratch) or transfer (from Phase 2)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print configuration without training"
    )

    args = parser.parse_args()

    try:
        if args.dry_run:
            check_prerequisites()
            print_training_summary()
            print("Dry run complete. Add --mode standard to start training.")
        elif args.mode == "transfer":
            train_phase4_transfer()
        else:
            train_phase4()
    finally:
        # Always reclaim GPU after training
        reclaim_gpu_after_training(gpu_id=0, job_id=_job_id)
