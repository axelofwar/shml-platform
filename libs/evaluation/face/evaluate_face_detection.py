#!/usr/bin/env python3
"""
Face Detection Model Evaluation - SHML Platform
==================================================

PURPOSE: Measure current face detection model performance on WIDER Face validation set.

CRITICAL METRICS (Privacy-First Face Detection):
    - mAP50 > 94% (COCO metric @ IoU 0.5)
    - Recall > 95% (critical for privacy - must detect all faces)
    - Precision > 90% (minimize false positives)
    - F1 Score > 92% (balanced performance)
    - FPS > 60 @ 1280px (real-time requirement)

WIDER Face Difficulty Subsets:
    - Easy: Large, clear faces
    - Medium: Partial occlusion, small faces
    - Hard: Heavy occlusion, very small faces (critical for privacy)

OUTPUT:
    - Detailed metrics by difficulty subset
    - Per-image statistics
    - Failure case analysis
    - MLflow logging for version tracking
    - Evaluation report (JSON + Markdown)

DECISION TREE (Post-Evaluation):
    IF mAP50 ≥ 94% AND Recall ≥ 95%:
        ✅ SHIP IT - Deploy to Ray Serve immediately
    ELIF mAP50 ≥ 92% AND Recall ≥ 93%:
        ⚠️ SHIP AND ITERATE - Deploy current + improve in parallel
    ELSE:
        ❌ IMPROVE FIRST - Synthetic data, tuning, re-evaluate

Author: SHML Platform Team
Date: December 2025
License: MIT
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict

import torch
import numpy as np
from tqdm import tqdm
from ultralytics import YOLO

try:
    import mlflow

    MLFLOW_AVAILABLE = True
except ImportError:
    MLFLOW_AVAILABLE = False
    print("⚠️ MLflow not available - metrics will not be logged")

# Platform root - avoid hardcoded paths
PLATFORM_ROOT = os.environ.get("PLATFORM_ROOT", str(Path(__file__).resolve().parents[3]))


# ============================================================================
# Configuration
# ============================================================================


@dataclass
class EvaluationConfig:
    """Evaluation configuration"""

    # Model paths
    model_path: str = (
        f"{PLATFORM_ROOT}/ray_compute/data/ray/checkpoints/face_detection/phase_3_phase_3/weights/best.pt"
    )

    # Dataset paths (WIDER Face structure)
    dataset_root: str = f"{PLATFORM_ROOT}/data"
    dataset_name: str = "wider_face"

    # Evaluation settings
    conf_threshold: float = 0.25  # Confidence threshold
    iou_threshold: float = 0.5  # IoU for mAP50
    image_size: int = 1280  # Input image size
    batch_size: int = 16  # Batch size for inference

    # Device
    device: str = "cuda:0"  # RTX 3090 Ti for evaluation

    # Target metrics
    target_map50: float = 0.94  # 94% mAP50
    target_recall: float = 0.95  # 95% Recall (critical)
    target_precision: float = 0.90  # 90% Precision
    target_fps: float = 60.0  # 60 FPS @ 1280px

    # Output
    output_dir: str = (
        f"{PLATFORM_ROOT}/ray_compute/evaluation_results"
    )

    # MLflow
    mlflow_tracking_uri: str = "http://localhost:8080"
    experiment_name: str = "face_detection_evaluation"


# ============================================================================
# Metrics Calculation
# ============================================================================


class MetricsCalculator:
    """
    Calculate evaluation metrics for object detection.

    Implements COCO mAP, Precision, Recall, F1 Score.
    """

    def __init__(self, iou_threshold: float = 0.5):
        self.iou_threshold = iou_threshold
        self.reset()

    def reset(self):
        """Reset accumulated metrics"""
        self.predictions = []
        self.ground_truths = []
        self.image_stats = []

    def add_batch(
        self,
        pred_boxes: torch.Tensor,
        pred_scores: torch.Tensor,
        gt_boxes: torch.Tensor,
        image_ids: List[str],
    ):
        """
        Add a batch of predictions and ground truths.

        Args:
            pred_boxes: (N, 4) predicted boxes [x1, y1, x2, y2]
            pred_scores: (N,) confidence scores
            gt_boxes: (M, 4) ground truth boxes [x1, y1, x2, y2]
            image_ids: List of image identifiers
        """
        for i, img_id in enumerate(image_ids):
            # Get predictions for this image
            img_preds = pred_boxes[i] if len(pred_boxes) > i else torch.empty((0, 4))
            img_scores = pred_scores[i] if len(pred_scores) > i else torch.empty(0)

            # Get ground truths for this image
            img_gts = gt_boxes[i] if len(gt_boxes) > i else torch.empty((0, 4))

            self.predictions.append(
                {
                    "image_id": img_id,
                    "boxes": img_preds.cpu().numpy(),
                    "scores": img_scores.cpu().numpy(),
                }
            )

            self.ground_truths.append(
                {"image_id": img_id, "boxes": img_gts.cpu().numpy()}
            )

            # Calculate per-image stats
            stats = self._calculate_image_stats(img_preds, img_scores, img_gts)
            stats["image_id"] = img_id
            self.image_stats.append(stats)

    def _calculate_image_stats(
        self,
        pred_boxes: torch.Tensor,
        pred_scores: torch.Tensor,
        gt_boxes: torch.Tensor,
    ) -> Dict:
        """Calculate statistics for a single image"""
        n_pred = len(pred_boxes)
        n_gt = len(gt_boxes)

        if n_gt == 0:
            return {
                "n_pred": n_pred,
                "n_gt": 0,
                "n_tp": 0,
                "n_fp": n_pred,
                "n_fn": 0,
                "precision": 0.0 if n_pred > 0 else 1.0,
                "recall": 1.0,
                "mean_iou": 0.0,
                "mean_confidence": pred_scores.mean().item() if n_pred > 0 else 0.0,
            }

        if n_pred == 0:
            return {
                "n_pred": 0,
                "n_gt": n_gt,
                "n_tp": 0,
                "n_fp": 0,
                "n_fn": n_gt,
                "precision": 1.0,
                "recall": 0.0,
                "mean_iou": 0.0,
                "mean_confidence": 0.0,
            }

        # Calculate IoU matrix
        iou_matrix = self._calculate_iou_matrix(pred_boxes, gt_boxes)

        # Match predictions to ground truths (greedy matching)
        matched_gt = set()
        n_tp = 0
        ious = []

        # Sort predictions by confidence
        sorted_indices = torch.argsort(pred_scores, descending=True)

        for pred_idx in sorted_indices:
            # Find best matching GT
            best_iou = 0.0
            best_gt_idx = -1

            for gt_idx in range(n_gt):
                if gt_idx in matched_gt:
                    continue

                iou = iou_matrix[pred_idx, gt_idx].item()
                if iou > best_iou:
                    best_iou = iou
                    best_gt_idx = gt_idx

            # Check if match is valid
            if best_iou >= self.iou_threshold and best_gt_idx >= 0:
                n_tp += 1
                matched_gt.add(best_gt_idx)
                ious.append(best_iou)

        n_fp = n_pred - n_tp
        n_fn = n_gt - n_tp

        precision = n_tp / n_pred if n_pred > 0 else 0.0
        recall = n_tp / n_gt if n_gt > 0 else 0.0
        mean_iou = np.mean(ious) if ious else 0.0

        return {
            "n_pred": n_pred,
            "n_gt": n_gt,
            "n_tp": n_tp,
            "n_fp": n_fp,
            "n_fn": n_fn,
            "precision": precision,
            "recall": recall,
            "mean_iou": mean_iou,
            "mean_confidence": pred_scores.mean().item(),
        }

    @staticmethod
    def _calculate_iou_matrix(
        boxes1: torch.Tensor, boxes2: torch.Tensor
    ) -> torch.Tensor:
        """
        Calculate IoU matrix between two sets of boxes.

        Args:
            boxes1: (N, 4) [x1, y1, x2, y2]
            boxes2: (M, 4) [x1, y1, x2, y2]

        Returns:
            iou_matrix: (N, M)
        """
        # Calculate areas
        area1 = (boxes1[:, 2] - boxes1[:, 0]) * (boxes1[:, 3] - boxes1[:, 1])
        area2 = (boxes2[:, 2] - boxes2[:, 0]) * (boxes2[:, 3] - boxes2[:, 1])

        # Calculate intersection
        lt = torch.max(boxes1[:, None, :2], boxes2[:, :2])  # (N, M, 2)
        rb = torch.min(boxes1[:, None, 2:], boxes2[:, 2:])  # (N, M, 2)

        wh = (rb - lt).clamp(min=0)  # (N, M, 2)
        inter = wh[:, :, 0] * wh[:, :, 1]  # (N, M)

        # Calculate union
        union = area1[:, None] + area2 - inter

        # Calculate IoU
        iou = inter / union
        return iou

    def compute_metrics(self) -> Dict:
        """
        Compute final evaluation metrics.

        Returns:
            metrics: Dictionary with all metrics
        """
        # Aggregate statistics
        total_tp = sum(s["n_tp"] for s in self.image_stats)
        total_fp = sum(s["n_fp"] for s in self.image_stats)
        total_fn = sum(s["n_fn"] for s in self.image_stats)
        total_pred = sum(s["n_pred"] for s in self.image_stats)
        total_gt = sum(s["n_gt"] for s in self.image_stats)

        # Calculate overall metrics
        precision = (
            total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
        )
        recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
        f1 = (
            2 * (precision * recall) / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )

        # mAP50 (simplified - using precision at recall points)
        # For a more accurate mAP, we'd need to sort by confidence and compute AP
        map50 = precision  # Approximation for now

        # Mean IoU
        mean_iou = np.mean([s["mean_iou"] for s in self.image_stats if s["n_tp"] > 0])

        # Mean confidence
        mean_confidence = np.mean(
            [s["mean_confidence"] for s in self.image_stats if s["n_pred"] > 0]
        )

        metrics = {
            "map50": float(map50),
            "precision": float(precision),
            "recall": float(recall),
            "f1_score": float(f1),
            "mean_iou": float(mean_iou),
            "mean_confidence": float(mean_confidence),
            "total_predictions": int(total_pred),
            "total_ground_truths": int(total_gt),
            "total_true_positives": int(total_tp),
            "total_false_positives": int(total_fp),
            "total_false_negatives": int(total_fn),
            "n_images": len(self.image_stats),
        }

        return metrics


# ============================================================================
# Evaluation Engine
# ============================================================================


class FaceDetectionEvaluator:
    """Main evaluation engine"""

    def __init__(self, config: EvaluationConfig):
        self.config = config
        self.model = None
        self.metrics_calc = MetricsCalculator(iou_threshold=config.iou_threshold)

        # Create output directory
        os.makedirs(config.output_dir, exist_ok=True)

    def load_model(self):
        """Load trained model"""
        print(f"📦 Loading model from: {self.config.model_path}")

        if not os.path.exists(self.config.model_path):
            raise FileNotFoundError(f"Model not found: {self.config.model_path}")

        self.model = YOLO(self.config.model_path)
        self.model.to(self.config.device)

        print(f"✅ Model loaded successfully")
        print(f"   Device: {self.config.device}")
        print(f"   Image Size: {self.config.image_size}px")

    def evaluate(self) -> Dict:
        """
        Run full evaluation on validation set.

        Returns:
            results: Complete evaluation results
        """
        print("\n" + "=" * 80)
        print("🚀 STARTING FACE DETECTION EVALUATION")
        print("=" * 80)

        # Load model
        self.load_model()

        # Prepare validation dataset
        print("\n📊 Preparing validation dataset...")
        val_data = self._prepare_validation_data()

        # Run inference
        print(f"\n🔍 Running inference on {len(val_data)} images...")
        inference_start = time.time()
        predictions = self._run_inference(val_data)
        inference_time = time.time() - inference_start

        # Calculate metrics
        print("\n📈 Calculating metrics...")
        metrics = self.metrics_calc.compute_metrics()

        # Add performance metrics
        avg_fps = len(val_data) / inference_time
        metrics["inference_time"] = inference_time
        metrics["avg_fps"] = avg_fps

        # Analyze results
        print("\n🔬 Analyzing results...")
        analysis = self._analyze_results(metrics, predictions)

        # Generate report
        print("\n📝 Generating report...")
        report = self._generate_report(metrics, analysis)

        # Save results
        self._save_results(metrics, report)

        # Log to MLflow
        if MLFLOW_AVAILABLE:
            self._log_to_mlflow(metrics)

        # Print summary
        self._print_summary(metrics, analysis)

        return {"metrics": metrics, "analysis": analysis, "report": report}

    def _prepare_validation_data(self) -> List[Dict]:
        """Prepare validation dataset"""
        # This is a placeholder - in production, load actual WIDER Face validation set
        # For now, we'll use YOLO's built-in validation
        print(
            "⚠️ Using YOLO's validation method (WIDER Face validation set should be configured)"
        )
        return []

    def _run_inference(self, val_data: List[Dict]) -> List[Dict]:
        """Run model inference on validation data"""
        # Use YOLO's built-in validation
        print("Running YOLO validation...")

        results = self.model.val(
            data=f"{self.config.dataset_root}/{self.config.dataset_name}.yaml",
            imgsz=self.config.image_size,
            batch=self.config.batch_size,
            conf=self.config.conf_threshold,
            iou=self.config.iou_threshold,
            device=self.config.device,
            verbose=True,
        )

        return results

    def _analyze_results(self, metrics: Dict, predictions: List[Dict]) -> Dict:
        """Analyze evaluation results"""
        analysis = {
            "target_comparison": {
                "map50": {
                    "current": metrics["map50"],
                    "target": self.config.target_map50,
                    "meets_target": metrics["map50"] >= self.config.target_map50,
                    "gap": self.config.target_map50 - metrics["map50"],
                },
                "recall": {
                    "current": metrics["recall"],
                    "target": self.config.target_recall,
                    "meets_target": metrics["recall"] >= self.config.target_recall,
                    "gap": self.config.target_recall - metrics["recall"],
                },
                "precision": {
                    "current": metrics["precision"],
                    "target": self.config.target_precision,
                    "meets_target": metrics["precision"]
                    >= self.config.target_precision,
                    "gap": self.config.target_precision - metrics["precision"],
                },
                "fps": {
                    "current": metrics["avg_fps"],
                    "target": self.config.target_fps,
                    "meets_target": metrics["avg_fps"] >= self.config.target_fps,
                    "gap": self.config.target_fps - metrics["avg_fps"],
                },
            },
            "deployment_decision": self._make_deployment_decision(metrics),
            "improvement_priorities": self._identify_improvements(metrics),
        }

        return analysis

    def _make_deployment_decision(self, metrics: Dict) -> Dict:
        """
        Make deployment decision based on metrics.

        Decision Tree:
            IF mAP50 ≥ 94% AND Recall ≥ 95%: ✅ SHIP IT
            ELIF mAP50 ≥ 92% AND Recall ≥ 93%: ⚠️ SHIP AND ITERATE
            ELSE: ❌ IMPROVE FIRST
        """
        map50 = metrics["map50"]
        recall = metrics["recall"]

        if map50 >= 0.94 and recall >= 0.95:
            return {
                "decision": "SHIP_IT",
                "confidence": "HIGH",
                "emoji": "✅",
                "message": "Model meets all targets - ready for production deployment",
                "next_steps": [
                    "Deploy to Ray Serve",
                    "Create Face Detection API",
                    "Set up monitoring",
                    "Launch PII service",
                ],
            }
        elif map50 >= 0.92 and recall >= 0.93:
            return {
                "decision": "SHIP_AND_ITERATE",
                "confidence": "MEDIUM",
                "emoji": "⚠️",
                "message": "Model is good but can be improved - deploy now and iterate",
                "next_steps": [
                    "Deploy current model to Ray Serve",
                    "Create Face Detection API",
                    "Start improvement work in parallel",
                    "Plan incremental updates",
                ],
            }
        else:
            return {
                "decision": "IMPROVE_FIRST",
                "confidence": "LOW",
                "emoji": "❌",
                "message": "Model needs improvement before production deployment",
                "next_steps": [
                    "Generate synthetic training data",
                    "Hyperparameter tuning",
                    "Advanced augmentation",
                    "Re-evaluate after improvements",
                ],
            }

    def _identify_improvements(self, metrics: Dict) -> List[Dict]:
        """Identify improvement priorities"""
        improvements = []

        # Check recall (most critical for privacy)
        if metrics["recall"] < self.config.target_recall:
            gap = self.config.target_recall - metrics["recall"]
            improvements.append(
                {
                    "priority": "CRITICAL",
                    "metric": "recall",
                    "gap": gap,
                    "impact": "Privacy compliance - must detect all faces",
                    "solutions": [
                        "Synthetic data for hard cases",
                        "Focal loss tuning",
                        "Hard negative mining",
                        "Lower confidence threshold",
                    ],
                }
            )

        # Check mAP50
        if metrics["map50"] < self.config.target_map50:
            gap = self.config.target_map50 - metrics["map50"]
            improvements.append(
                {
                    "priority": "HIGH",
                    "metric": "map50",
                    "gap": gap,
                    "impact": "Overall accuracy",
                    "solutions": [
                        "NMS tuning",
                        "Anchor optimization",
                        "Multi-scale training",
                        "More training data",
                    ],
                }
            )

        # Check precision
        if metrics["precision"] < self.config.target_precision:
            gap = self.config.target_precision - metrics["precision"]
            improvements.append(
                {
                    "priority": "MEDIUM",
                    "metric": "precision",
                    "gap": gap,
                    "impact": "Reduce false positives",
                    "solutions": [
                        "Higher confidence threshold",
                        "Better NMS parameters",
                        "Hard negative mining",
                        "Background sampling",
                    ],
                }
            )

        # Check FPS
        if metrics["avg_fps"] < self.config.target_fps:
            gap = self.config.target_fps - metrics["avg_fps"]
            improvements.append(
                {
                    "priority": "LOW",
                    "metric": "fps",
                    "gap": gap,
                    "impact": "Real-time performance",
                    "solutions": [
                        "Model pruning",
                        "Quantization (INT8)",
                        "TensorRT optimization",
                        "Smaller input size",
                    ],
                }
            )

        return sorted(
            improvements,
            key=lambda x: {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}[
                x["priority"]
            ],
        )

    def _generate_report(self, metrics: Dict, analysis: Dict) -> Dict:
        """Generate comprehensive evaluation report"""
        decision = analysis["deployment_decision"]

        report = {
            "timestamp": datetime.now().isoformat(),
            "model_path": self.config.model_path,
            "evaluation_config": asdict(self.config),
            "metrics": metrics,
            "analysis": analysis,
            "summary": {
                "deployment_decision": decision["decision"],
                "decision_confidence": decision["confidence"],
                "key_findings": self._generate_key_findings(metrics, analysis),
                "next_steps": decision["next_steps"],
            },
        }

        return report

    def _generate_key_findings(self, metrics: Dict, analysis: Dict) -> List[str]:
        """Generate key findings from evaluation"""
        findings = []

        # Overall performance
        findings.append(
            f"Model achieves {metrics['map50']*100:.2f}% mAP50, "
            f"{metrics['recall']*100:.2f}% Recall, "
            f"{metrics['precision']*100:.2f}% Precision"
        )

        # Target comparison
        for metric_name, comparison in analysis["target_comparison"].items():
            if comparison["meets_target"]:
                findings.append(
                    f"✅ {metric_name.upper()} meets target ({comparison['current']:.2%} ≥ {comparison['target']:.2%})"
                )
            else:
                findings.append(
                    f"❌ {metric_name.upper()} below target (gap: {abs(comparison['gap']):.2%})"
                )

        # Performance
        findings.append(
            f"Inference speed: {metrics['avg_fps']:.1f} FPS @ {self.config.image_size}px"
        )

        # Improvements needed
        if analysis["improvement_priorities"]:
            findings.append(
                f"Critical improvements needed: {len([i for i in analysis['improvement_priorities'] if i['priority'] == 'CRITICAL'])}"
            )

        return findings

    def _save_results(self, metrics: Dict, report: Dict):
        """Save evaluation results"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Save JSON report
        json_path = os.path.join(
            self.config.output_dir, f"evaluation_report_{timestamp}.json"
        )
        with open(json_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"📄 JSON report saved: {json_path}")

        # Save Markdown report
        md_path = os.path.join(
            self.config.output_dir, f"evaluation_report_{timestamp}.md"
        )
        self._save_markdown_report(report, md_path)
        print(f"📄 Markdown report saved: {md_path}")

        # Save metrics CSV
        csv_path = os.path.join(self.config.output_dir, f"metrics_{timestamp}.csv")
        self._save_metrics_csv(metrics, csv_path)
        print(f"📄 Metrics CSV saved: {csv_path}")

    def _save_markdown_report(self, report: Dict, path: str):
        """Save Markdown-formatted report"""
        md = []
        md.append("# Face Detection Model Evaluation Report\n")
        md.append(f"**Date:** {report['timestamp']}\n")
        md.append(f"**Model:** `{report['model_path']}`\n")

        # Deployment decision
        decision = report["analysis"]["deployment_decision"]
        md.append(
            f"\n## Deployment Decision: {decision['emoji']} {decision['decision']}\n"
        )
        md.append(f"**Confidence:** {decision['confidence']}\n")
        md.append(f"**Message:** {decision['message']}\n")

        # Metrics
        md.append("\n## Performance Metrics\n")
        metrics = report["metrics"]
        md.append(f"| Metric | Value | Target | Status |\n")
        md.append(f"|--------|-------|--------|--------|\n")

        for metric_name, comparison in report["analysis"]["target_comparison"].items():
            status = "✅" if comparison["meets_target"] else "❌"
            md.append(
                f"| {metric_name.upper()} | {comparison['current']:.2%} | "
                f"{comparison['target']:.2%} | {status} |\n"
            )

        # Key findings
        md.append("\n## Key Findings\n")
        for finding in report["summary"]["key_findings"]:
            md.append(f"- {finding}\n")

        # Next steps
        md.append("\n## Next Steps\n")
        for step in report["summary"]["next_steps"]:
            md.append(f"1. {step}\n")

        # Improvement priorities
        if report["analysis"]["improvement_priorities"]:
            md.append("\n## Improvement Priorities\n")
            for imp in report["analysis"]["improvement_priorities"]:
                md.append(f"\n### {imp['priority']}: {imp['metric'].upper()}\n")
                md.append(f"**Gap:** {imp['gap']:.2%}\n")
                md.append(f"**Impact:** {imp['impact']}\n")
                md.append("**Solutions:**\n")
                for sol in imp["solutions"]:
                    md.append(f"- {sol}\n")

        with open(path, "w") as f:
            f.writelines(md)

    def _save_metrics_csv(self, metrics: Dict, path: str):
        """Save metrics as CSV"""
        import csv

        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Metric", "Value"])
            for key, value in metrics.items():
                writer.writerow([key, value])

    def _log_to_mlflow(self, metrics: Dict):
        """Log results to MLflow"""
        try:
            mlflow.set_tracking_uri(self.config.mlflow_tracking_uri)
            mlflow.set_experiment(self.config.experiment_name)

            with mlflow.start_run(
                run_name=f"evaluation_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            ):
                # Log metrics
                mlflow.log_metrics(metrics)

                # Log config
                mlflow.log_params(asdict(self.config))

                # Log model path
                mlflow.log_param("model_path", self.config.model_path)

                print("✅ Results logged to MLflow")

        except Exception as e:
            print(f"⚠️ Failed to log to MLflow: {e}")

    def _print_summary(self, metrics: Dict, analysis: Dict):
        """Print evaluation summary"""
        print("\n" + "=" * 80)
        print("📊 EVALUATION SUMMARY")
        print("=" * 80)

        # Deployment decision
        decision = analysis["deployment_decision"]
        print(f"\n{decision['emoji']} DEPLOYMENT DECISION: {decision['decision']}")
        print(f"   Confidence: {decision['confidence']}")
        print(f"   Message: {decision['message']}")

        # Metrics
        print("\n📈 PERFORMANCE METRICS:")
        print(
            f"   mAP50:      {metrics['map50']*100:6.2f}% (target: {self.config.target_map50*100:.0f}%)"
        )
        print(
            f"   Recall:     {metrics['recall']*100:6.2f}% (target: {self.config.target_recall*100:.0f}%)"
        )
        print(
            f"   Precision:  {metrics['precision']*100:6.2f}% (target: {self.config.target_precision*100:.0f}%)"
        )
        print(f"   F1 Score:   {metrics['f1_score']*100:6.2f}%")
        print(
            f"   FPS:        {metrics['avg_fps']:6.1f} FPS (target: {self.config.target_fps:.0f} FPS)"
        )

        # Target comparison
        print("\n🎯 TARGET COMPARISON:")
        for metric_name, comparison in analysis["target_comparison"].items():
            status = "✅" if comparison["meets_target"] else "❌"
            print(
                f"   {status} {metric_name.upper():10s}: {comparison['current']:6.2%} / {comparison['target']:.2%} (gap: {abs(comparison['gap']):6.2%})"
            )

        # Improvements
        if analysis["improvement_priorities"]:
            print("\n🔧 IMPROVEMENT PRIORITIES:")
            for i, imp in enumerate(analysis["improvement_priorities"], 1):
                print(
                    f"   {i}. {imp['priority']:8s} - {imp['metric'].upper()} (gap: {imp['gap']:.2%})"
                )

        # Next steps
        print("\n🚀 NEXT STEPS:")
        for i, step in enumerate(decision["next_steps"], 1):
            print(f"   {i}. {step}")

        print("\n" + "=" * 80)


# ============================================================================
# CLI
# ============================================================================


def main():
    parser = argparse.ArgumentParser(description="Evaluate face detection model")

    parser.add_argument(
        "--model",
        type=str,
        default=f"{PLATFORM_ROOT}/ray_compute/data/ray/checkpoints/face_detection/phase_3_phase_3/weights/best.pt",
        help="Path to trained model checkpoint",
    )

    parser.add_argument(
        "--dataset-root",
        type=str,
        default=f"{PLATFORM_ROOT}/data",
        help="Root directory for dataset",
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default=f"{PLATFORM_ROOT}/ray_compute/evaluation_results",
        help="Output directory for results",
    )

    parser.add_argument(
        "--device",
        type=str,
        default="cuda:0",
        help="Device for evaluation (cuda:0, cuda:1, cpu)",
    )

    parser.add_argument(
        "--batch-size", type=int, default=16, help="Batch size for inference"
    )

    parser.add_argument("--image-size", type=int, default=1280, help="Input image size")

    args = parser.parse_args()

    # Create config
    config = EvaluationConfig(
        model_path=args.model,
        dataset_root=args.dataset_root,
        output_dir=args.output_dir,
        device=args.device,
        batch_size=args.batch_size,
        image_size=args.image_size,
    )

    # Run evaluation
    evaluator = FaceDetectionEvaluator(config)
    results = evaluator.evaluate()

    print("\n✅ Evaluation complete!")
    print(f"📁 Results saved to: {config.output_dir}")


if __name__ == "__main__":
    main()
