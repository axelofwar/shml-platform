#!/usr/bin/env python3
"""
Validate yolov8l-face baseline model on WIDER Face dataset.
This script must be run as a Ray job to have GPU access.

Note: Uses training mode for validation because ultralytics' val() has
strict CUDA initialization that fails in Ray containers, while training
mode's validation works correctly.
"""

import sys
import os

sys.path.insert(0, "/tmp/ray")

# Suppress NVML warnings that cause issues
os.environ["CUDA_LAUNCH_BLOCKING"] = "1"

from ultralytics import YOLO
import torch


def main():
    print("=" * 70)
    print("YOLOv8l-Face Baseline Validation (via Training Mode)")
    print("=" * 70)

    # Check CUDA
    print(f"\nPyTorch version: {torch.__version__}")
    print(f"CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"CUDA device count: {torch.cuda.device_count()}")
        for i in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(i)
            print(f"  GPU {i}: {props.name} ({props.total_memory / 1024**3:.1f} GB)")

    # Load the yolov8l-face model
    model_path = "/tmp/ray/yolov8l-face.pt"
    print(f"\nLoading yolov8l-face baseline model: {model_path}")
    model = YOLO(model_path)

    # Count parameters
    total_params = sum(p.numel() for p in model.model.parameters())
    print(f"Total parameters: {total_params:,}")
    print(f"Model size: {total_params * 4 / 1024 / 1024:.2f} MB (FP32)")

    # NVML fix applied - torch.cuda.is_available() now works correctly!
    print("\n" + "=" * 70)
    print("Running validation on WIDER Face dataset...")
    print(f"Device: cuda:0 (CUDA available: {torch.cuda.is_available()})")
    print("=" * 70)

    data_yaml = "/tmp/ray/data/wider_face_yolo/data.yaml"

    # Use standard validation method now that CUDA works properly
    results = model.val(
        data=data_yaml, conf=0.25, iou=0.6, verbose=True, device="cuda:0"
    )

    # Extract metrics from validation results
    precision = results.results_dict.get("metrics/precision(B)", 0)
    recall = results.results_dict.get("metrics/recall(B)", 0)
    map50 = results.results_dict.get("metrics/mAP50(B)", 0)
    map50_95 = results.results_dict.get("metrics/mAP50-95(B)", 0)

    print("\n" + "=" * 70)
    print("YOLOv8l-Face Baseline Performance:")
    print("=" * 70)
    print(f"Precision:  {precision*100:.2f}%")
    print(f"Recall:     {recall*100:.2f}%")
    print(f"mAP50:      {map50*100:.2f}%")
    print(f"mAP50-95:   {map50_95*100:.2f}%")
    print("=" * 70)

    # Compare to our trained model
    print("\n" + "=" * 70)
    print("Loading our trained model for comparison...")
    print("=" * 70)

    trained_model_path = (
        "/tmp/ray/checkpoints/face_detection/phase_3_phase_3/weights/best.pt"
    )
    print(f"Loading: {trained_model_path}")
    trained_model = YOLO(trained_model_path)

    print("Running validation on trained model...")
    trained_results = trained_model.val(
        data=data_yaml, conf=0.25, iou=0.6, verbose=True, device="cuda:0"
    )

    # Extract trained metrics
    trained_precision = trained_results.results_dict.get("metrics/precision(B)", 0)
    trained_recall = trained_results.results_dict.get("metrics/recall(B)", 0)
    trained_map50 = trained_results.results_dict.get("metrics/mAP50(B)", 0)
    trained_map50_95 = trained_results.results_dict.get("metrics/mAP50-95(B)", 0)

    print("\n" + "=" * 70)
    print("Our Trained Model Performance:")
    print("=" * 70)
    print(f"Precision:  {trained_precision*100:.2f}%")
    print(f"Recall:     {trained_recall*100:.2f}%")
    print(f"mAP50:      {trained_map50*100:.2f}%")
    print(f"mAP50-95:   {trained_map50_95*100:.2f}%")
    print("=" * 70)

    # Show improvement
    print("\n" + "=" * 70)
    print("Improvement Over yolov8l-face Baseline:")
    print("=" * 70)
    print(f"Precision:  {(trained_precision - precision)*100:+.2f}pp")
    print(f"Recall:     {(trained_recall - recall)*100:+.2f}pp")
    print(f"mAP50:      {(trained_map50 - map50)*100:+.2f}pp")
    print(f"mAP50-95:   {(trained_map50_95 - map50_95)*100:+.2f}pp")
    print("=" * 70)


if __name__ == "__main__":
    main()
