#!/usr/bin/env python3
"""
Quick threshold comparison test for face detection model.
Tests different confidence thresholds to find optimal recall/precision tradeoff.
"""

import os

os.environ["PYTORCH_CUDA_ALLOC_CONF"] = (
    "max_split_size_mb:512,expandable_segments:False"
)

import torch
from ultralytics import YOLO
from pathlib import Path


def main():
    # Load the best model from training
    model_path = "/tmp/ray/checkpoints/face_detection/phase_3_phase_3/weights/best.pt"
    print(f"Loading model: {model_path}")

    if not Path(model_path).exists():
        print(f"ERROR: Model not found at {model_path}")
        return

    model = YOLO(model_path)

    # Get validation data path
    data_yaml = "/tmp/ray/data/wider_face_yolo/data.yaml"

    if not Path(data_yaml).exists():
        print(f"ERROR: Data config not found at {data_yaml}")
        return

    # Device setup
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")
    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name(0)}")

    # Test configurations
    test_configs = [
        {"conf": 0.25, "iou": 0.60, "name": "Original (conf=0.25, iou=0.6)"},
        {"conf": 0.25, "iou": 0.50, "name": "Looser NMS (conf=0.25, iou=0.5)"},
        {"conf": 0.20, "iou": 0.50, "name": "Lower conf (conf=0.20, iou=0.5)"},
        {"conf": 0.15, "iou": 0.50, "name": "Recall-focused (conf=0.15, iou=0.5)"},
        {"conf": 0.10, "iou": 0.50, "name": "Aggressive (conf=0.10, iou=0.5)"},
        {"conf": 0.15, "iou": 0.45, "name": "Max recall (conf=0.15, iou=0.45)"},
    ]

    print("\n" + "=" * 90)
    print("CONFIDENCE/IOU THRESHOLD COMPARISON")
    print("=" * 90)
    print(
        f'{"Config":<40} | {"Precision":>10} | {"Recall":>10} | {"mAP50":>10} | {"mAP50-95":>10}'
    )
    print("-" * 90)

    results_summary = []

    for cfg in test_configs:
        print(f'\nTesting: {cfg["name"]}...')

        results = model.val(
            data=data_yaml,
            conf=cfg["conf"],
            iou=cfg["iou"],
            verbose=False,
            device=device,
            workers=8,
            batch=16,
        )

        precision = results.results_dict.get("metrics/precision(B)", 0)
        recall = results.results_dict.get("metrics/recall(B)", 0)
        map50 = results.results_dict.get("metrics/mAP50(B)", 0)
        map50_95 = results.results_dict.get("metrics/mAP50-95(B)", 0)

        results_summary.append(
            {
                "config": cfg["name"],
                "conf": cfg["conf"],
                "iou": cfg["iou"],
                "precision": precision,
                "recall": recall,
                "map50": map50,
                "map50_95": map50_95,
            }
        )

        print(
            f'{cfg["name"]:<40} | {precision:>10.4f} | {recall:>10.4f} | {map50:>10.4f} | {map50_95:>10.4f}'
        )

    print("\n" + "=" * 90)
    print("SUMMARY")
    print("=" * 90)

    # Find best recall configuration
    best_recall = max(results_summary, key=lambda x: x["recall"])
    print(f'\nBest Recall: {best_recall["recall"]:.4f} with {best_recall["config"]}')
    print(f'  Precision: {best_recall["precision"]:.4f}')
    print(f'  mAP50: {best_recall["map50"]:.4f}')

    # Calculate recall improvement
    original = results_summary[0]
    print(f"\nRecall improvement from original:")
    for r in results_summary[1:]:
        delta = (r["recall"] - original["recall"]) * 100
        prec_delta = (r["precision"] - original["precision"]) * 100
        print(f'  {r["config"]}: {delta:+.2f}% recall, {prec_delta:+.2f}% precision')

    print("\n" + "=" * 90)


if __name__ == "__main__":
    main()
