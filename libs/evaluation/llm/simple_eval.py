#!/usr/bin/env python3
"""
Simple WIDER Face Model Evaluation
Compares curriculum-trained model vs base YOLOv8l-face
"""

import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime

print("=" * 80)
print("  WIDER FACE MODEL EVALUATION")
print("=" * 80)

# Check environment
import torch

print("PyTorch:", torch.__version__)
print("CUDA:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("GPU:", torch.cuda.get_device_name(0))
    mem_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
    print("VRAM:", round(mem_gb, 1), "GB")

from ultralytics import YOLO

# Model paths
MODELS = {
    "curriculum_phase3": "/tmp/ray/checkpoints/face_detection/phase_3_phase_3/weights/best.pt",
    "curriculum_phase1": "/tmp/ray/checkpoints/face_detection/phase_1_phase_1/weights/best.pt",
    "yolov8l_face": "/tmp/ray/data/yolov8l-face.pt",
}

# Data config
DATA_YAML = "/tmp/ray/data/wider_face_yolo/data.yaml"

# Find available models
print("\nLocating models...")
available_models = {}
for name, path in MODELS.items():
    p = Path(path)
    if p.exists():
        size_mb = p.stat().st_size / 1e6
        print("  Found", name, "-", round(size_mb, 1), "MB")
        available_models[name] = path
    else:
        print("  Missing:", name)

if not Path(DATA_YAML).exists():
    print("\nData config not found:", DATA_YAML)
    sys.exit(1)

print("\nData config:", DATA_YAML)

# Select models to compare - use phase 1 as the trained model
curriculum_model = available_models.get("curriculum_phase1") or available_models.get(
    "curriculum_phase3"
)
base_model = available_models.get("yolov8l_face")

if not curriculum_model:
    print("\nNo curriculum model found!")
    sys.exit(1)

if not base_model:
    print("\nNo base model found!")
    # Try alternate path
    alt_path = "/tmp/ray/yolov8l-face.pt"
    if Path(alt_path).exists():
        base_model = alt_path
        print("Found base model at:", alt_path)
    else:
        sys.exit(1)

models_to_eval = {
    "base_yolov8l_face": base_model,
    "curriculum_trained": curriculum_model,
}

print("\nModels to evaluate:")
for name, path in models_to_eval.items():
    print(" -", name, ":", path)

# PII Enterprise Targets
PII_TARGETS = {
    "mAP50": 0.94,
    "recall": 0.95,
    "precision": 0.90,
}

print("\nPII Enterprise Targets:")
for k, v in PII_TARGETS.items():
    pct = round(v * 100)
    print(" ", k, ">=", str(pct) + "%")

# Run evaluation
print("\n" + "=" * 80)
print("Starting Evaluation...")
print("=" * 80)

results = {}

for model_name, model_path in models_to_eval.items():
    print("\n" + "-" * 40)
    print("Evaluating:", model_name)
    print("-" * 40)

    try:
        model = YOLO(model_path)

        # Run validation
        metrics = model.val(
            data=DATA_YAML,
            batch=16,
            imgsz=640,
            verbose=True,
            device=0 if torch.cuda.is_available() else "cpu",
        )

        # Extract metrics
        result = {
            "model_path": model_path,
            "mAP50": round(float(metrics.box.map50), 4),
            "mAP50-95": round(float(metrics.box.map), 4),
            "precision": round(float(metrics.box.mp), 4),
            "recall": round(float(metrics.box.mr), 4),
        }

        # Calculate F1
        p = result["precision"]
        r = result["recall"]
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0
        result["f1_score"] = round(f1, 4)

        results[model_name] = result

        print("\nResults for", model_name + ":")
        print("  mAP50:", result["mAP50"])
        print("  mAP50-95:", result["mAP50-95"])
        print("  Precision:", result["precision"])
        print("  Recall:", result["recall"])
        print("  F1 Score:", result["f1_score"])

        # Check against PII targets
        print("\nPII Target Check:")
        for metric, target in PII_TARGETS.items():
            if metric in result:
                val = result[metric]
                status = "PASS" if val >= target else "FAIL"
                print("  ", metric, ":", val, "vs", target, "-", status)

        # Clear GPU memory
        del model
        torch.cuda.empty_cache()

    except Exception as e:
        print("Error evaluating", model_name + ":", str(e))
        results[model_name] = {"error": str(e)}

# Summary
print("\n" + "=" * 80)
print("EVALUATION SUMMARY")
print("=" * 80)

if "base_yolov8l_face" in results and "curriculum_trained" in results:
    base = results["base_yolov8l_face"]
    curr = results["curriculum_trained"]

    if "error" not in base and "error" not in curr:
        print("\nComparison (Curriculum vs Base):")
        for metric in ["mAP50", "mAP50-95", "precision", "recall", "f1_score"]:
            base_val = base.get(metric, 0)
            curr_val = curr.get(metric, 0)
            diff = curr_val - base_val
            pct = diff / base_val * 100 if base_val > 0 else 0
            sign = "+" if diff >= 0 else ""
            print(
                "  ",
                metric + ":",
                "Base",
                base_val,
                "| Curriculum",
                curr_val,
                "| Change:",
                sign + str(round(diff, 4)),
                "(" + sign + str(round(pct, 1)) + "%)",
            )

        # Overall assessment
        print("\nPII Enterprise Assessment:")
        meets_targets = True
        for metric, target in PII_TARGETS.items():
            if metric in curr:
                if curr[metric] < target:
                    meets_targets = False
                    shortfall = target - curr[metric]
                    print(
                        "  FAIL:",
                        metric,
                        "needs",
                        round(shortfall * 100, 1),
                        "% improvement",
                    )

        if meets_targets:
            print("  STATUS: MEETS PII ENTERPRISE STANDARDS")
        else:
            print("  STATUS: DOES NOT MEET PII ENTERPRISE STANDARDS")
            print("  Recommendation: Continue curriculum training")

# Save results
output_path = "/tmp/ray/evaluation_results.json"
with open(output_path, "w") as f:
    output = {
        "timestamp": datetime.now().isoformat(),
        "pii_targets": PII_TARGETS,
        "results": results,
    }
    json.dump(output, f, indent=2)
print("\nResults saved to:", output_path)

print("\n" + "=" * 80)
print("Evaluation Complete!")
print("=" * 80)
