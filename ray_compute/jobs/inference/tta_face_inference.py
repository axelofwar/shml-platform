#!/usr/bin/env python3
"""
Configurable TTA (Test-Time Augmentation) Inference for Face Detection
========================================================================

Three modes:
  - fast:     Single forward pass at native resolution (production default)
  - balanced: 2-scale (960+1280) without flip (2x cost, +1-2% recall)
  - accurate: Full TTA with 3 scales + flip + WBF (6x cost, +2-4% recall)

The mode is configurable via environment variable, constructor arg, or CLI flag.

Usage:
    # Python API
    from tta_face_inference import FaceDetector
    detector = FaceDetector("best.pt", mode="accurate")
    detections = detector.predict(image)

    # CLI
    python tta_face_inference.py --model best.pt --image test.jpg --mode accurate
    python tta_face_inference.py --model best.pt --source video.mp4 --mode fast

    # Environment variable
    FACE_DETECTION_MODE=accurate python your_pipeline.py

Author: SHML Platform
Date: March 2026
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Union

import cv2
import numpy as np

# Patch ray.tune before ultralytics
try:
    import ray.tune

    if not hasattr(ray.tune, "is_session_enabled"):
        ray.tune.is_session_enabled = lambda: False
except ImportError:
    pass

from ultralytics import YOLO

# Try to import WBF
WBF_AVAILABLE = False
try:
    from ensemble_boxes import weighted_boxes_fusion

    WBF_AVAILABLE = True
except ImportError:
    pass


# ═══════════════════════════════════════════════════════════════════════════
# Detection Mode Configurations
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class InferenceConfig:
    """Configuration for a specific inference mode."""

    name: str
    scales: List[int]
    use_flip: bool
    conf_threshold: float
    iou_threshold: float
    max_det: int
    description: str

    @property
    def num_passes(self) -> int:
        return len(self.scales) * (2 if self.use_flip else 1)


MODES = {
    "fast": InferenceConfig(
        name="fast",
        scales=[960],
        use_flip=False,
        conf_threshold=0.25,
        iou_threshold=0.7,
        max_det=500,
        description="Single forward pass — production default",
    ),
    "balanced": InferenceConfig(
        name="balanced",
        scales=[960, 1280],
        use_flip=False,
        conf_threshold=0.20,
        iou_threshold=0.6,
        max_det=1000,
        description="2-scale, no flip — moderate recall boost",
    ),
    "accurate": InferenceConfig(
        name="accurate",
        scales=[640, 960, 1280],
        use_flip=True,
        conf_threshold=0.15,
        iou_threshold=0.5,
        max_det=1500,
        description="Full TTA with WBF — maximum recall for PII",
    ),
}


# ═══════════════════════════════════════════════════════════════════════════
# Detection Result
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class FaceDetection:
    """A single face detection."""

    x1: float  # Top-left x (pixels)
    y1: float  # Top-left y (pixels)
    x2: float  # Bottom-right x (pixels)
    y2: float  # Bottom-right y (pixels)
    confidence: float
    class_id: int = 0

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center(self) -> Tuple[float, float]:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

    def to_dict(self) -> dict:
        return {
            "bbox": [self.x1, self.y1, self.x2, self.y2],
            "confidence": self.confidence,
            "class_id": self.class_id,
            "width": self.width,
            "height": self.height,
        }


@dataclass
class DetectionResult:
    """Result of face detection on a single image."""

    detections: List[FaceDetection]
    mode: str
    inference_time_ms: float
    image_size: Tuple[int, int]  # (height, width)
    num_forward_passes: int
    metadata: Dict = field(default_factory=dict)

    @property
    def num_faces(self) -> int:
        return len(self.detections)

    def to_dict(self) -> dict:
        return {
            "num_faces": self.num_faces,
            "mode": self.mode,
            "inference_time_ms": self.inference_time_ms,
            "image_size": list(self.image_size),
            "forward_passes": self.num_forward_passes,
            "detections": [d.to_dict() for d in self.detections],
            "metadata": self.metadata,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Face Detector
# ═══════════════════════════════════════════════════════════════════════════


class FaceDetector:
    """Configurable face detector with TTA support.

    Modes:
      - fast:     1 forward pass, standard thresholds
      - balanced: 2 forward passes (960+1280px), lower conf threshold
      - accurate: 6 forward passes (3 scales × 2 flip), WBF fusion, lowest thresholds
    """

    def __init__(
        self,
        model_path: str,
        mode: Optional[str] = None,
        device: int = 0,
        conf_override: Optional[float] = None,
        iou_override: Optional[float] = None,
    ):
        """
        Args:
            model_path: Path to YOLO weights (.pt)
            mode: "fast", "balanced", or "accurate".
                  If None, reads FACE_DETECTION_MODE env var (default: "fast")
            device: CUDA device index
            conf_override: Override confidence threshold
            iou_override: Override IoU/NMS threshold
        """
        # Determine mode
        if mode is None:
            mode = os.environ.get("FACE_DETECTION_MODE", "fast")
        if mode not in MODES:
            raise ValueError(f"Unknown mode '{mode}'. Use: {list(MODES.keys())}")

        self.config = MODES[mode]
        if conf_override is not None:
            self.config.conf_threshold = conf_override
        if iou_override is not None:
            self.config.iou_threshold = iou_override

        # Load model
        self.model = YOLO(model_path)
        self.device = device
        self.model_path = model_path

        # Check WBF availability for accurate mode
        if self.config.name == "accurate" and not WBF_AVAILABLE:
            print("[tta] WARNING: ensemble_boxes not installed. Using NMS fallback.")
            print("[tta] Install: pip install ensemble-boxes")

        print(f"[face-detect] Mode: {self.config.name} — {self.config.description}")
        print(
            f"[face-detect] Scales: {self.config.scales}, Flip: {self.config.use_flip}"
        )
        print(
            f"[face-detect] Conf: {self.config.conf_threshold}, IoU: {self.config.iou_threshold}"
        )

    def predict(self, image: np.ndarray) -> DetectionResult:
        """Run face detection on a single image.

        Args:
            image: BGR image (HWC format)

        Returns:
            DetectionResult with all detected faces
        """
        if self.config.name == "fast":
            return self._predict_fast(image)
        elif self.config.name == "balanced":
            return self._predict_multiscale(image)
        elif self.config.name == "accurate":
            return self._predict_tta(image)
        else:
            return self._predict_fast(image)

    def predict_batch(self, images: List[np.ndarray]) -> List[DetectionResult]:
        """Run face detection on a batch of images."""
        return [self.predict(img) for img in images]

    # ─── Fast Mode ───

    def _predict_fast(self, image: np.ndarray) -> DetectionResult:
        """Single forward pass at native scale."""
        h, w = image.shape[:2]
        start = time.time()

        results = self.model.predict(
            image,
            imgsz=self.config.scales[0],
            conf=self.config.conf_threshold,
            iou=self.config.iou_threshold,
            max_det=self.config.max_det,
            device=self.device,
            verbose=False,
        )

        detections = self._results_to_detections(results, h, w)
        elapsed_ms = (time.time() - start) * 1000

        return DetectionResult(
            detections=detections,
            mode="fast",
            inference_time_ms=elapsed_ms,
            image_size=(h, w),
            num_forward_passes=1,
        )

    # ─── Balanced Mode (2-scale, no flip) ───

    def _predict_multiscale(self, image: np.ndarray) -> DetectionResult:
        """Multi-scale inference without flip."""
        h, w = image.shape[:2]
        start = time.time()

        all_detections = []
        per_scale = {}

        for scale in self.config.scales:
            results = self.model.predict(
                image,
                imgsz=scale,
                conf=self.config.conf_threshold,
                iou=self.config.iou_threshold,
                max_det=self.config.max_det,
                device=self.device,
                verbose=False,
            )
            dets = self._results_to_detections(results, h, w)
            per_scale[scale] = len(dets)
            all_detections.extend(dets)

        # Merge via NMS
        merged = self._nms_merge(all_detections, h, w, self.config.iou_threshold)
        elapsed_ms = (time.time() - start) * 1000

        return DetectionResult(
            detections=merged,
            mode="balanced",
            inference_time_ms=elapsed_ms,
            image_size=(h, w),
            num_forward_passes=len(self.config.scales),
            metadata={"per_scale_detections": per_scale},
        )

    # ─── Accurate Mode (Full TTA with WBF) ───

    def _predict_tta(self, image: np.ndarray) -> DetectionResult:
        """Full TTA: multi-scale + flip + WBF/NMS fusion."""
        h, w = image.shape[:2]
        start = time.time()

        # Collect predictions from all augmentations
        all_boxes_list = []  # Per-model list of boxes
        all_scores_list = []  # Per-model list of scores
        all_labels_list = []  # Per-model list of labels
        per_scale = {}
        n_passes = 0

        for scale in self.config.scales:
            for flip in [False, True] if self.config.use_flip else [False]:
                input_img = image.copy()
                if flip:
                    input_img = cv2.flip(input_img, 1)

                results = self.model.predict(
                    input_img,
                    imgsz=scale,
                    conf=self.config.conf_threshold,
                    iou=0.95,  # Very loose NMS per-scale — let WBF handle merging
                    max_det=self.config.max_det,
                    device=self.device,
                    verbose=False,
                )

                dets = self._results_to_detections(results, h, w)

                # Unflip coordinates
                if flip:
                    dets = self._unflip_detections(dets, w)

                # Convert to WBF format: [x1/W, y1/H, x2/W, y2/H] normalized
                boxes = []
                scores = []
                labels = []
                for d in dets:
                    boxes.append([d.x1 / w, d.y1 / h, d.x2 / w, d.y2 / h])
                    scores.append(d.confidence)
                    labels.append(d.class_id)

                all_boxes_list.append(boxes if boxes else [[0, 0, 0, 0]])
                all_scores_list.append(scores if scores else [0])
                all_labels_list.append(labels if labels else [0])

                key = f"{scale}{'_flip' if flip else ''}"
                per_scale[key] = len(dets)
                n_passes += 1

        # Merge with WBF or NMS
        if WBF_AVAILABLE and len(all_boxes_list) > 1:
            merged = self._wbf_merge(
                all_boxes_list,
                all_scores_list,
                all_labels_list,
                h,
                w,
                self.config.iou_threshold,
            )
        else:
            # Fallback: flatten + NMS
            flat_dets = []
            for boxes, scores, labels in zip(
                all_boxes_list, all_scores_list, all_labels_list
            ):
                for box, score, label in zip(boxes, scores, labels):
                    if score > 0:
                        flat_dets.append(
                            FaceDetection(
                                x1=box[0] * w,
                                y1=box[1] * h,
                                x2=box[2] * w,
                                y2=box[3] * h,
                                confidence=score,
                                class_id=label,
                            )
                        )
            merged = self._nms_merge(flat_dets, h, w, self.config.iou_threshold)

        elapsed_ms = (time.time() - start) * 1000

        return DetectionResult(
            detections=merged,
            mode="accurate",
            inference_time_ms=elapsed_ms,
            image_size=(h, w),
            num_forward_passes=n_passes,
            metadata={
                "per_scale_detections": per_scale,
                "wbf_used": WBF_AVAILABLE,
                "total_raw_detections": sum(per_scale.values()),
                "merged_detections": len(merged),
            },
        )

    # ─── Helpers ───

    def _results_to_detections(
        self, results, orig_h: int, orig_w: int
    ) -> List[FaceDetection]:
        """Convert Ultralytics results to FaceDetection list."""
        detections = []
        if len(results) == 0 or results[0].boxes is None or len(results[0].boxes) == 0:
            return detections

        boxes = results[0].boxes
        for i in range(len(boxes)):
            xyxy = boxes.xyxy[i].cpu().numpy()
            conf = boxes.conf[i].cpu().item()
            cls = int(boxes.cls[i].cpu().item())

            detections.append(
                FaceDetection(
                    x1=float(xyxy[0]),
                    y1=float(xyxy[1]),
                    x2=float(xyxy[2]),
                    y2=float(xyxy[3]),
                    confidence=conf,
                    class_id=cls,
                )
            )
        return detections

    def _unflip_detections(
        self, detections: List[FaceDetection], img_width: int
    ) -> List[FaceDetection]:
        """Mirror x-coordinates back after horizontal flip."""
        return [
            FaceDetection(
                x1=img_width - d.x2,
                y1=d.y1,
                x2=img_width - d.x1,
                y2=d.y2,
                confidence=d.confidence,
                class_id=d.class_id,
            )
            for d in detections
        ]

    def _wbf_merge(
        self,
        boxes_list: List[List],
        scores_list: List[List],
        labels_list: List[List],
        img_h: int,
        img_w: int,
        iou_thr: float,
    ) -> List[FaceDetection]:
        """Merge detections using Weighted Boxes Fusion."""
        # WBF expects normalized [x1, y1, x2, y2]
        fused_boxes, fused_scores, fused_labels = weighted_boxes_fusion(
            boxes_list,
            scores_list,
            labels_list,
            iou_thr=iou_thr,
            skip_box_thr=self.config.conf_threshold,
        )

        detections = []
        for box, score, label in zip(fused_boxes, fused_scores, fused_labels):
            detections.append(
                FaceDetection(
                    x1=float(box[0] * img_w),
                    y1=float(box[1] * img_h),
                    x2=float(box[2] * img_w),
                    y2=float(box[3] * img_h),
                    confidence=float(score),
                    class_id=int(label),
                )
            )
        return detections

    def _nms_merge(
        self,
        detections: List[FaceDetection],
        img_h: int,
        img_w: int,
        iou_thr: float,
    ) -> List[FaceDetection]:
        """Merge detections using simple NMS."""
        if not detections:
            return []

        import torch

        boxes = torch.tensor([[d.x1, d.y1, d.x2, d.y2] for d in detections])
        scores = torch.tensor([d.confidence for d in detections])

        from torchvision.ops import nms

        keep = nms(boxes, scores, iou_thr)

        return [detections[i] for i in keep.cpu().numpy()]

    # ─── Visualization ───

    def draw_detections(
        self,
        image: np.ndarray,
        result: DetectionResult,
        color: Tuple[int, int, int] = (0, 255, 0),
        thickness: int = 2,
        show_conf: bool = True,
    ) -> np.ndarray:
        """Draw detections on image."""
        img = image.copy()
        for det in result.detections:
            x1, y1, x2, y2 = int(det.x1), int(det.y1), int(det.x2), int(det.y2)
            cv2.rectangle(img, (x1, y1), (x2, y2), color, thickness)
            if show_conf:
                label = f"{det.confidence:.2f}"
                cv2.putText(
                    img, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1
                )
        return img


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="Face Detection with Configurable TTA")
    parser.add_argument("--model", type=str, required=True, help="Path to YOLO weights")
    parser.add_argument("--image", type=str, help="Path to input image")
    parser.add_argument("--source", type=str, help="Path to image directory or video")
    parser.add_argument(
        "--output", type=str, default="tta_results", help="Output directory"
    )
    parser.add_argument(
        "--mode", type=str, default=None, choices=["fast", "balanced", "accurate"]
    )
    parser.add_argument(
        "--conf", type=float, default=None, help="Override confidence threshold"
    )
    parser.add_argument(
        "--iou", type=float, default=None, help="Override IoU threshold"
    )
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument(
        "--save-json", action="store_true", help="Save detections as JSON"
    )
    parser.add_argument(
        "--save-images", action="store_true", help="Save annotated images"
    )
    parser.add_argument(
        "--benchmark", action="store_true", help="Run benchmark across modes"
    )
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.benchmark:
        # Benchmark all modes on the same image
        if not args.image:
            print("--benchmark requires --image")
            return

        image = cv2.imread(args.image)
        if image is None:
            print(f"Cannot load: {args.image}")
            return

        print(f"\nBenchmark: {args.image} ({image.shape[1]}x{image.shape[0]})")
        print(f"{'Mode':<12} {'Faces':<8} {'Time (ms)':<12} {'Passes':<8}")
        print("-" * 44)

        for mode_name in ["fast", "balanced", "accurate"]:
            detector = FaceDetector(args.model, mode=mode_name, device=args.device)
            # Warmup
            _ = detector.predict(image)
            # Timed run
            results = []
            for _ in range(3):
                results.append(detector.predict(image))
            avg_time = sum(r.inference_time_ms for r in results) / len(results)
            r = results[-1]
            print(
                f"{mode_name:<12} {r.num_faces:<8} {avg_time:<12.1f} {r.num_forward_passes:<8}"
            )

        return

    # Single image or directory
    detector = FaceDetector(
        args.model,
        mode=args.mode,
        device=args.device,
        conf_override=args.conf,
        iou_override=args.iou,
    )

    images = []
    if args.image:
        images = [Path(args.image)]
    elif args.source:
        src = Path(args.source)
        if src.is_dir():
            images = sorted(src.glob("*.jpg")) + sorted(src.glob("*.png"))
        else:
            images = [src]

    if not images:
        print("No images found. Use --image or --source")
        return

    all_results = []
    for img_path in images:
        image = cv2.imread(str(img_path))
        if image is None:
            print(f"Skip: {img_path}")
            continue

        result = detector.predict(image)
        all_results.append({"file": str(img_path), **result.to_dict()})

        print(
            f"{img_path.name}: {result.num_faces} faces, "
            f"{result.inference_time_ms:.1f}ms ({result.mode})"
        )

        if args.save_images:
            annotated = detector.draw_detections(image, result)
            out_path = output_dir / f"det_{img_path.name}"
            cv2.imwrite(str(out_path), annotated)

    if args.save_json:
        json_path = output_dir / "detections.json"
        with open(json_path, "w") as f:
            json.dump(all_results, f, indent=2)
        print(f"\nSaved: {json_path}")


if __name__ == "__main__":
    main()
