#!/usr/bin/env python3
"""
Precision-Recall Curve Sweep for Face Detection
==================================================

Evaluates a face detection model at multiple confidence thresholds to
find the optimal operating point where recall is maximized subject to
a minimum precision constraint (default: P > 0.85).

Also computes metrics at each TTA mode (fast, balanced, accurate) for
comparison.

Usage:
    python pr_curve_sweep.py --model best.pt                      # Default sweep
    python pr_curve_sweep.py --model best.pt --min-precision 0.90 # Stricter
    python pr_curve_sweep.py --model best.pt --tta                # Include TTA modes
    python pr_curve_sweep.py --model best.pt --plot               # Save PR curve plot

Author: SHML Platform
Date: March 2026
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np

# Patch ray.tune
try:
    import ray.tune

    if not hasattr(ray.tune, "is_session_enabled"):
        ray.tune.is_session_enabled = lambda: False
except ImportError:
    pass

from ultralytics import YOLO


# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

WIDER_YOLO_DIR = "/tmp/ray/data/wider_face_yolo"
MERGED_YOLO_DIR = "/tmp/ray/data/face_merged_yolo"

# Baselines
BASELINES = {
    "Phase 5 (YOLOv8m-P2)": {"R": 0.716, "P": 0.889, "mAP50": 0.798},
    "Phase 9 (finetune)": {"R": 0.729, "P": 0.883, "mAP50": 0.814},
}

CONF_THRESHOLDS = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]
IOU_THRESHOLDS = [0.45, 0.50, 0.60, 0.70]


def detect_val_dataset() -> str:
    """Find validation dataset path."""
    # Always use WIDER Face val for fair comparison
    wider_yaml = Path(WIDER_YOLO_DIR) / "data.yaml"
    if wider_yaml.exists():
        return WIDER_YOLO_DIR

    merged_yaml = Path(MERGED_YOLO_DIR) / "data.yaml"
    if merged_yaml.exists():
        return MERGED_YOLO_DIR

    print("✗ No dataset found")
    sys.exit(1)


def run_validation(
    model_path: str,
    data_yaml: str,
    conf: float,
    iou: float,
    imgsz: int = 960,
    device: int = 0,
) -> dict:
    """Run model.val() at specific thresholds and return metrics."""
    model = YOLO(model_path)

    results = model.val(
        data=data_yaml,
        imgsz=imgsz,
        conf=conf,
        iou=iou,
        max_det=1500,
        device=device,
        verbose=False,
        plots=False,
    )

    metrics = {
        "precision": float(results.results_dict.get("metrics/precision(B)", 0)),
        "recall": float(results.results_dict.get("metrics/recall(B)", 0)),
        "mAP50": float(results.results_dict.get("metrics/mAP50(B)", 0)),
        "mAP50_95": float(results.results_dict.get("metrics/mAP50-95(B)", 0)),
        "conf": conf,
        "iou": iou,
        "imgsz": imgsz,
    }
    f1 = (
        2
        * metrics["precision"]
        * metrics["recall"]
        / (metrics["precision"] + metrics["recall"])
        if (metrics["precision"] + metrics["recall"]) > 0
        else 0
    )
    metrics["F1"] = f1

    del model
    import gc
    import torch

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    return metrics


def conf_sweep(
    model_path: str,
    data_yaml: str,
    conf_thresholds: list,
    iou: float = 0.7,
    imgsz: int = 960,
    device: int = 0,
    min_precision: float = 0.85,
) -> list:
    """Sweep confidence thresholds and find optimal operating point."""
    results = []

    print(f"\n{'═' * 75}")
    print(f"  Confidence Threshold Sweep (IoU NMS={iou}, imgsz={imgsz})")
    print(f"  Constraint: P ≥ {min_precision}")
    print(f"{'═' * 75}")
    print(
        f"  {'Conf':<8} {'P':<8} {'R':<8} {'F1':<8} {'mAP50':<8} {'mAP':<8} {'Status':<12}"
    )
    print(f"  {'─' * 68}")

    best_recall_at_constraint = 0.0
    best_conf_at_constraint = None

    for conf in conf_thresholds:
        metrics = run_validation(model_path, data_yaml, conf, iou, imgsz, device)
        results.append(metrics)

        p = metrics["precision"]
        r = metrics["recall"]
        meets_constraint = p >= min_precision

        if meets_constraint and r > best_recall_at_constraint:
            best_recall_at_constraint = r
            best_conf_at_constraint = conf

        status = "✓ VALID" if meets_constraint else "✗ P too low"
        marker = (
            " ◀ BEST" if meets_constraint and r == best_recall_at_constraint else ""
        )

        print(
            f"  {conf:<8.2f} {p:<8.3f} {r:<8.3f} {metrics['F1']:<8.3f} "
            f"{metrics['mAP50']:<8.3f} {metrics['mAP50_95']:<8.3f} "
            f"{status}{marker}"
        )

    print(f"  {'─' * 68}")
    if best_conf_at_constraint is not None:
        print(
            f"  ★ Optimal: conf={best_conf_at_constraint} → R={best_recall_at_constraint:.3f} (P≥{min_precision})"
        )
    else:
        print(f"  ✗ No threshold meets P≥{min_precision}")
    print()

    return results


def iou_sweep(
    model_path: str,
    data_yaml: str,
    conf: float,
    iou_thresholds: list,
    imgsz: int = 960,
    device: int = 0,
) -> list:
    """Sweep NMS IoU thresholds at a fixed confidence."""
    results = []

    print(f"\n{'═' * 75}")
    print(f"  NMS IoU Threshold Sweep (conf={conf}, imgsz={imgsz})")
    print(f"{'═' * 75}")
    print(f"  {'IoU':<8} {'P':<8} {'R':<8} {'F1':<8} {'mAP50':<8} {'mAP':<8}")
    print(f"  {'─' * 48}")

    for iou in iou_thresholds:
        metrics = run_validation(model_path, data_yaml, conf, iou, imgsz, device)
        results.append(metrics)

        print(
            f"  {iou:<8.2f} {metrics['precision']:<8.3f} {metrics['recall']:<8.3f} "
            f"{metrics['F1']:<8.3f} {metrics['mAP50']:<8.3f} {metrics['mAP50_95']:<8.3f}"
        )

    print()
    return results


def plot_pr_curve(conf_results: list, output_path: str, min_precision: float = 0.85):
    """Generate and save a PR curve plot."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not available, skipping plot")
        return

    precisions = [r["precision"] for r in conf_results]
    recalls = [r["recall"] for r in conf_results]
    confs = [r["conf"] for r in conf_results]

    fig, ax = plt.subplots(1, 1, figsize=(10, 7))

    # PR curve
    ax.plot(recalls, precisions, "b-o", linewidth=2, markersize=8, label="PR Curve")

    # Annotate conf values
    for p, r, c in zip(precisions, recalls, confs):
        ax.annotate(
            f"c={c}", (r, p), textcoords="offset points", xytext=(10, 5), fontsize=8
        )

    # Min precision line
    ax.axhline(
        y=min_precision,
        color="r",
        linestyle="--",
        alpha=0.7,
        label=f"Min P = {min_precision}",
    )

    # Baselines
    colors = ["green", "orange"]
    for (name, bl), color in zip(BASELINES.items(), colors):
        ax.plot(
            bl["R"],
            bl["P"],
            "x",
            color=color,
            markersize=12,
            markeredgewidth=3,
            label=name,
        )

    ax.set_xlabel("Recall", fontsize=12)
    ax.set_ylabel("Precision", fontsize=12)
    ax.set_title(
        "Face Detection — Precision vs Recall at Various Conf Thresholds", fontsize=14
    )
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.set_xlim(0.5, 1.0)
    ax.set_ylim(0.5, 1.0)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    print(f"  Plot saved: {output_path}")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="PR Curve Sweep for Face Detection")
    parser.add_argument("--model", type=str, required=True, help="Path to YOLO weights")
    parser.add_argument(
        "--data", type=str, default=None, help="Dataset dir (auto-detect)"
    )
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument(
        "--min-precision", type=float, default=0.85, help="Minimum precision constraint"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="/tmp/ray/pr_sweep_results",
        help="Output directory",
    )
    parser.add_argument("--plot", action="store_true", help="Generate PR curve plot")
    parser.add_argument(
        "--iou-sweep", action="store_true", help="Also sweep NMS IoU thresholds"
    )
    parser.add_argument(
        "--tta", action="store_true", help="Compare TTA modes at optimal conf"
    )
    parser.add_argument(
        "--confs",
        type=str,
        default=None,
        help="Custom conf thresholds (comma-separated)",
    )
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Dataset
    data_dir = args.data or detect_val_dataset()
    data_yaml = f"{data_dir}/data.yaml"
    print(f"[data] Validating on: {data_yaml}")
    print(f"[model] {args.model}")

    # Conf thresholds
    confs = CONF_THRESHOLDS
    if args.confs:
        confs = [float(x) for x in args.confs.split(",")]

    # Run confidence sweep
    start = time.time()
    conf_results = conf_sweep(
        args.model,
        data_yaml,
        confs,
        iou=0.7,
        imgsz=args.imgsz,
        device=args.device,
        min_precision=args.min_precision,
    )
    elapsed = time.time() - start

    # Find optimal operating point
    valid_results = [r for r in conf_results if r["precision"] >= args.min_precision]
    if valid_results:
        optimal = max(valid_results, key=lambda r: r["recall"])
        print(f"★ OPTIMAL: conf={optimal['conf']:.2f}, IoU=0.7")
        print(
            f"  P={optimal['precision']:.3f} R={optimal['recall']:.3f} "
            f"F1={optimal['F1']:.3f} mAP50={optimal['mAP50']:.3f}"
        )
    else:
        optimal = max(conf_results, key=lambda r: r["F1"])
        print(
            f"⚠ No conf meets P≥{args.min_precision}. Best F1 at conf={optimal['conf']:.2f}"
        )

    # IoU sweep at optimal conf
    iou_results = []
    if args.iou_sweep and optimal:
        iou_results = iou_sweep(
            args.model,
            data_yaml,
            optimal["conf"],
            IOU_THRESHOLDS,
            args.imgsz,
            args.device,
        )

    # TTA mode comparison at optimal conf
    tta_results = {}
    if args.tta and optimal:
        print(f"\n{'═' * 75}")
        print(f"  TTA Mode Comparison (conf={optimal['conf']}, imgsz=960)")
        print(f"{'═' * 75}")

        # Import TTA module
        tta_dir = Path(__file__).parent.parent / "inference"
        sys.path.insert(0, str(tta_dir))
        try:
            from tta_face_inference import FaceDetector, MODES

            # We can't run full TTA validation here (too slow on whole val set)
            # Instead, run on a sample and report speed difference
            import cv2

            val_dir = Path(data_dir) / "images" / "val"
            sample_images = sorted(val_dir.glob("*.jpg"))[:10]

            for mode in ["fast", "balanced", "accurate"]:
                detector = FaceDetector(args.model, mode=mode, device=args.device)
                times = []
                total_dets = 0
                for img_path in sample_images:
                    img = cv2.imread(str(img_path))
                    if img is None:
                        continue
                    result = detector.predict(img)
                    times.append(result.inference_time_ms)
                    total_dets += result.num_faces

                avg_time = np.mean(times) if times else 0
                avg_dets = total_dets / max(len(sample_images), 1)
                tta_results[mode] = {
                    "avg_time_ms": float(avg_time),
                    "avg_detections": float(avg_dets),
                    "passes": MODES[mode].num_passes,
                }
                print(
                    f"  {mode:<12} {avg_dets:.1f} faces/img  {avg_time:.1f}ms  {MODES[mode].num_passes} passes"
                )

            print()
        except ImportError as e:
            print(f"  ⚠ TTA module not available: {e}")

    # Save results
    all_results = {
        "model": args.model,
        "dataset": data_dir,
        "imgsz": args.imgsz,
        "min_precision": args.min_precision,
        "conf_sweep": conf_results,
        "iou_sweep": iou_results,
        "tta_comparison": tta_results,
        "optimal": optimal,
        "baselines": BASELINES,
        "total_time_seconds": elapsed,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    json_path = output_dir / "pr_sweep_results.json"
    with open(json_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"Results saved: {json_path}")

    # Plot
    if args.plot:
        plot_path = str(output_dir / "pr_curve.png")
        plot_pr_curve(conf_results, plot_path, args.min_precision)

    # Summary
    print(f"\n{'═' * 75}")
    print(f"  SUMMARY")
    print(f"{'═' * 75}")
    print(f"  Model:            {Path(args.model).name}")
    if valid_results:
        print(f"  Optimal conf:     {optimal['conf']:.2f}")
        print(f"  → Precision:      {optimal['precision']:.3f}")
        print(f"  → Recall:         {optimal['recall']:.3f}")
        print(f"  → F1:             {optimal['F1']:.3f}")
        print(f"  → mAP50:          {optimal['mAP50']:.3f}")
    for name, bl in BASELINES.items():
        r_delta = optimal["recall"] - bl["R"]
        print(f"  vs {name}: R{r_delta:+.3f}")
    print(f"  Total sweep time: {elapsed/60:.1f}min")
    print(f"{'═' * 75}")


if __name__ == "__main__":
    main()
