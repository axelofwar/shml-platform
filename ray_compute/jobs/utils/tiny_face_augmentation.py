#!/usr/bin/env python3
"""
Tiny Face Zoom Augmentation for WIDER Face Training

This module implements zoom augmentation specifically targeting tiny faces
(<2% of image size), which comprise 62% of WIDER Face annotations.

Key Insight: The 30% recall gap is largely due to tiny faces being:
1. Hard to detect at native resolution
2. Underrepresented in effective training (low gradient signal)
3. Lost in heavy augmentation (mosaic, scaling)

Solution: Crop regions containing tiny faces and upscale them, forcing
the model to learn tiny face patterns at a larger scale.

Usage:
    from tiny_face_augmentation import TinyFaceZoomAugmentation

    augmenter = TinyFaceZoomAugmentation(
        zoom_probability=0.3,
        min_zoom=2.0,
        max_zoom=4.0,
        tiny_face_threshold=0.03,  # <3% of image = tiny
    )

    # In training loop:
    image, labels = augmenter.maybe_zoom_tiny_faces(image, labels)

Author: SHML Platform
Date: 2025-12-11
Target: +5-10% recall on tiny faces
"""

import numpy as np
import cv2
from typing import Tuple, List, Optional, Dict, Any
from dataclasses import dataclass
import random


@dataclass
class TinyFaceRegion:
    """Represents a region containing tiny faces for zoom augmentation."""

    x_center: float
    y_center: float
    width: float
    height: float
    face_indices: List[int]  # Indices of tiny faces in this region
    zoom_factor: float


class TinyFaceZoomAugmentation:
    """
    Zoom augmentation targeting tiny faces in WIDER Face dataset.

    Strategy:
    1. Identify tiny faces (<threshold% of image)
    2. Cluster nearby tiny faces into regions
    3. Randomly select a region to zoom
    4. Crop and upscale the region
    5. Adjust bounding box annotations

    This forces the model to see tiny faces at a larger scale during training,
    improving feature learning for small face detection.
    """

    def __init__(
        self,
        zoom_probability: float = 0.3,
        min_zoom: float = 2.0,
        max_zoom: float = 4.0,
        tiny_face_threshold: float = 0.03,  # <3% of image = tiny
        small_face_threshold: float = 0.08,  # <8% of image = small
        min_faces_in_crop: int = 1,
        crop_padding: float = 0.2,  # 20% padding around faces
        preserve_aspect_ratio: bool = True,
    ):
        """
        Initialize TinyFaceZoomAugmentation.

        Args:
            zoom_probability: Probability of applying zoom augmentation [0-1]
            min_zoom: Minimum zoom factor (2.0 = 2x upscale)
            max_zoom: Maximum zoom factor (4.0 = 4x upscale)
            tiny_face_threshold: Face size threshold for "tiny" (relative to image)
            small_face_threshold: Face size threshold for "small" (relative to image)
            min_faces_in_crop: Minimum faces required in crop region
            crop_padding: Padding around face region as fraction of region size
            preserve_aspect_ratio: Whether to preserve aspect ratio when cropping
        """
        self.zoom_probability = zoom_probability
        self.min_zoom = min_zoom
        self.max_zoom = max_zoom
        self.tiny_face_threshold = tiny_face_threshold
        self.small_face_threshold = small_face_threshold
        self.min_faces_in_crop = min_faces_in_crop
        self.crop_padding = crop_padding
        self.preserve_aspect_ratio = preserve_aspect_ratio

        # Statistics tracking
        self.stats = {
            "total_images": 0,
            "zoom_applied": 0,
            "tiny_faces_found": 0,
            "tiny_faces_zoomed": 0,
        }

    def identify_tiny_faces(
        self,
        labels: np.ndarray,
        img_width: int,
        img_height: int,
    ) -> Tuple[List[int], List[int]]:
        """
        Identify tiny and small faces in the image.

        Args:
            labels: YOLO format labels [class, x_center, y_center, width, height]
            img_width: Image width in pixels
            img_height: Image height in pixels

        Returns:
            Tuple of (tiny_face_indices, small_face_indices)
        """
        tiny_indices = []
        small_indices = []

        for i, label in enumerate(labels):
            if len(label) < 5:
                continue

            # YOLO format: normalized [0-1]
            w_norm = label[3]
            h_norm = label[4]

            # Calculate face area as fraction of image
            face_area = w_norm * h_norm

            # Categorize by size
            if face_area < self.tiny_face_threshold**2:
                tiny_indices.append(i)
            elif face_area < self.small_face_threshold**2:
                small_indices.append(i)

        return tiny_indices, small_indices

    def cluster_nearby_faces(
        self,
        labels: np.ndarray,
        face_indices: List[int],
        cluster_distance: float = 0.15,
    ) -> List[TinyFaceRegion]:
        """
        Cluster nearby tiny faces into regions for zoom augmentation.

        Args:
            labels: YOLO format labels
            face_indices: Indices of tiny faces
            cluster_distance: Maximum normalized distance for clustering

        Returns:
            List of TinyFaceRegion objects
        """
        if len(face_indices) == 0:
            return []

        # Simple greedy clustering
        regions = []
        used = set()

        for i in face_indices:
            if i in used:
                continue

            # Start new cluster
            cluster = [i]
            used.add(i)

            # Find nearby faces
            x1, y1 = labels[i][1], labels[i][2]

            for j in face_indices:
                if j in used:
                    continue

                x2, y2 = labels[j][1], labels[j][2]
                distance = np.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

                if distance < cluster_distance:
                    cluster.append(j)
                    used.add(j)

            # Create region from cluster
            if len(cluster) >= self.min_faces_in_crop:
                region = self._create_region_from_cluster(labels, cluster)
                regions.append(region)

        return regions

    def _create_region_from_cluster(
        self,
        labels: np.ndarray,
        face_indices: List[int],
    ) -> TinyFaceRegion:
        """Create a TinyFaceRegion from a cluster of face indices."""
        # Get bounding box of all faces in cluster
        min_x, min_y = 1.0, 1.0
        max_x, max_y = 0.0, 0.0

        for i in face_indices:
            x, y, w, h = labels[i][1:5]
            min_x = min(min_x, x - w / 2)
            min_y = min(min_y, y - h / 2)
            max_x = max(max_x, x + w / 2)
            max_y = max(max_y, y + h / 2)

        # Add padding
        width = max_x - min_x
        height = max_y - min_y
        pad_x = width * self.crop_padding
        pad_y = height * self.crop_padding

        min_x = max(0, min_x - pad_x)
        min_y = max(0, min_y - pad_y)
        max_x = min(1, max_x + pad_x)
        max_y = min(1, max_y + pad_y)

        # Calculate region properties
        region_width = max_x - min_x
        region_height = max_y - min_y
        x_center = (min_x + max_x) / 2
        y_center = (min_y + max_y) / 2

        # Calculate appropriate zoom factor
        region_size = max(region_width, region_height)
        zoom_factor = random.uniform(self.min_zoom, self.max_zoom)

        # Clamp zoom so we don't go beyond image bounds
        max_possible_zoom = min(1.0 / region_width, 1.0 / region_height)
        zoom_factor = min(zoom_factor, max_possible_zoom * 0.9)

        return TinyFaceRegion(
            x_center=x_center,
            y_center=y_center,
            width=region_width,
            height=region_height,
            face_indices=face_indices,
            zoom_factor=zoom_factor,
        )

    def apply_zoom(
        self,
        image: np.ndarray,
        labels: np.ndarray,
        region: TinyFaceRegion,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Apply zoom augmentation to a region.

        Args:
            image: Input image (HWC format)
            labels: YOLO format labels
            region: TinyFaceRegion to zoom

        Returns:
            Tuple of (zoomed_image, adjusted_labels)
        """
        h, w = image.shape[:2]

        # Calculate crop coordinates
        crop_w = int(region.width * w)
        crop_h = int(region.height * h)
        crop_x = int((region.x_center - region.width / 2) * w)
        crop_y = int((region.y_center - region.height / 2) * h)

        # Clamp to image bounds
        crop_x = max(0, min(crop_x, w - crop_w))
        crop_y = max(0, min(crop_y, h - crop_h))
        crop_w = min(crop_w, w - crop_x)
        crop_h = min(crop_h, h - crop_y)

        if crop_w < 10 or crop_h < 10:
            return image, labels

        # Crop the region
        cropped = image[crop_y : crop_y + crop_h, crop_x : crop_x + crop_w]

        # Upscale to original image size (or target size)
        target_w = min(w, int(crop_w * region.zoom_factor))
        target_h = min(h, int(crop_h * region.zoom_factor))

        if self.preserve_aspect_ratio:
            scale = min(target_w / crop_w, target_h / crop_h)
            target_w = int(crop_w * scale)
            target_h = int(crop_h * scale)

        zoomed = cv2.resize(
            cropped, (target_w, target_h), interpolation=cv2.INTER_LINEAR
        )

        # Pad to original size if needed
        if target_w < w or target_h < h:
            # Create canvas and place zoomed image
            canvas = np.zeros_like(image)
            paste_x = (w - target_w) // 2
            paste_y = (h - target_h) // 2
            canvas[paste_y : paste_y + target_h, paste_x : paste_x + target_w] = zoomed
            zoomed = canvas

            # Adjust offset for label transformation
            x_offset = paste_x / w
            y_offset = paste_y / h
            scale_x = target_w / w
            scale_y = target_h / h
        else:
            zoomed = zoomed[:h, :w]  # Crop to original size
            x_offset = 0
            y_offset = 0
            scale_x = 1.0
            scale_y = 1.0

        # Transform labels
        new_labels = []
        crop_x_norm = crop_x / w
        crop_y_norm = crop_y / h
        crop_w_norm = crop_w / w
        crop_h_norm = crop_h / h

        for i, label in enumerate(labels):
            if len(label) < 5:
                continue

            cls, x, y, lw, lh = label[:5]

            # Check if face is within crop region
            if (
                x - lw / 2 >= crop_x_norm
                and x + lw / 2 <= crop_x_norm + crop_w_norm
                and y - lh / 2 >= crop_y_norm
                and y + lh / 2 <= crop_y_norm + crop_h_norm
            ):

                # Transform to crop coordinates
                new_x = (x - crop_x_norm) / crop_w_norm
                new_y = (y - crop_y_norm) / crop_h_norm
                new_w = lw / crop_w_norm
                new_h = lh / crop_h_norm

                # Apply zoom transformation
                new_x = new_x * scale_x + x_offset
                new_y = new_y * scale_y + y_offset
                new_w = new_w * scale_x
                new_h = new_h * scale_y

                # Clamp to [0, 1]
                if 0 < new_x < 1 and 0 < new_y < 1:
                    new_w = min(new_w, min(new_x, 1 - new_x) * 2)
                    new_h = min(new_h, min(new_y, 1 - new_y) * 2)
                    new_labels.append([cls, new_x, new_y, new_w, new_h])

        if len(new_labels) == 0:
            return image, labels

        return zoomed, np.array(new_labels)

    def maybe_zoom_tiny_faces(
        self,
        image: np.ndarray,
        labels: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
        """
        Maybe apply tiny face zoom augmentation.

        Args:
            image: Input image (HWC format, BGR or RGB)
            labels: YOLO format labels [N, 5] - [class, x, y, w, h]

        Returns:
            Tuple of (processed_image, processed_labels, metadata)
        """
        self.stats["total_images"] += 1
        metadata = {"zoom_applied": False, "tiny_faces": 0, "zoomed_faces": 0}

        if len(labels) == 0:
            return image, labels, metadata

        h, w = image.shape[:2]

        # Identify tiny faces
        tiny_indices, small_indices = self.identify_tiny_faces(labels, w, h)
        self.stats["tiny_faces_found"] += len(tiny_indices)
        metadata["tiny_faces"] = len(tiny_indices)

        # Decide whether to apply zoom
        if len(tiny_indices) < self.min_faces_in_crop:
            return image, labels, metadata

        if random.random() > self.zoom_probability:
            return image, labels, metadata

        # Cluster tiny faces into regions
        regions = self.cluster_nearby_faces(labels, tiny_indices)

        if len(regions) == 0:
            return image, labels, metadata

        # Select random region to zoom
        region = random.choice(regions)

        # Apply zoom
        zoomed_image, zoomed_labels = self.apply_zoom(image, labels, region)

        if len(zoomed_labels) > 0:
            self.stats["zoom_applied"] += 1
            self.stats["tiny_faces_zoomed"] += len(region.face_indices)
            metadata["zoom_applied"] = True
            metadata["zoomed_faces"] = len(region.face_indices)
            metadata["zoom_factor"] = region.zoom_factor
            return zoomed_image, zoomed_labels, metadata

        return image, labels, metadata

    def get_statistics(self) -> Dict[str, Any]:
        """Get augmentation statistics."""
        stats = dict(self.stats)
        if stats["total_images"] > 0:
            stats["zoom_rate"] = stats["zoom_applied"] / stats["total_images"]
        if stats["tiny_faces_found"] > 0:
            stats["tiny_face_zoom_rate"] = (
                stats["tiny_faces_zoomed"] / stats["tiny_faces_found"]
            )
        return stats

    def reset_statistics(self):
        """Reset statistics counters."""
        self.stats = {
            "total_images": 0,
            "zoom_applied": 0,
            "tiny_faces_found": 0,
            "tiny_faces_zoomed": 0,
        }


class AdaptiveZoomSchedule:
    """
    Adaptive zoom schedule that increases zoom probability as training progresses.

    Rationale: Early training focuses on easy faces, later training emphasizes
    tiny faces. Zoom augmentation becomes more important in later phases.
    """

    def __init__(
        self,
        initial_probability: float = 0.1,
        final_probability: float = 0.5,
        warmup_epochs: int = 10,
    ):
        self.initial_probability = initial_probability
        self.final_probability = final_probability
        self.warmup_epochs = warmup_epochs

    def get_probability(self, epoch: int, total_epochs: int) -> float:
        """Get zoom probability for current epoch."""
        if epoch < self.warmup_epochs:
            # Linear warmup
            return self.initial_probability

        # Linear increase from initial to final
        progress = (epoch - self.warmup_epochs) / (total_epochs - self.warmup_epochs)
        progress = min(1.0, max(0.0, progress))

        return self.initial_probability + progress * (
            self.final_probability - self.initial_probability
        )


# =============================================================================
# YOLO Integration Helper
# =============================================================================


def create_tiny_face_callback(augmenter: TinyFaceZoomAugmentation):
    """
    Create a callback function for YOLO training that applies tiny face zoom.

    Note: This requires modifying the Ultralytics dataloader or using
    a custom dataset class. The callback signature matches what YOLO expects.
    """

    def on_batch_start(trainer):
        """Apply tiny face zoom to batch."""
        if hasattr(trainer, "batch") and trainer.batch is not None:
            images = trainer.batch["img"]
            labels = trainer.batch["bboxes"]

            # Apply to each image in batch
            for i in range(len(images)):
                img = images[i].cpu().numpy().transpose(1, 2, 0)
                lbl = labels[labels[:, 0] == i, 1:].cpu().numpy()

                zoomed_img, zoomed_lbl, _ = augmenter.maybe_zoom_tiny_faces(img, lbl)

                # Update batch (requires torch tensors)
                import torch

                images[i] = torch.from_numpy(zoomed_img.transpose(2, 0, 1))
                # Note: Label update is more complex, see YOLO docs

    return on_batch_start


# =============================================================================
# CLI for Testing
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test Tiny Face Zoom Augmentation")
    parser.add_argument("--image", type=str, required=True, help="Input image path")
    parser.add_argument("--labels", type=str, required=True, help="YOLO labels path")
    parser.add_argument("--output", type=str, default="zoomed.jpg", help="Output path")
    parser.add_argument("--zoom-prob", type=float, default=1.0, help="Zoom probability")
    parser.add_argument("--min-zoom", type=float, default=2.0, help="Min zoom factor")
    parser.add_argument("--max-zoom", type=float, default=4.0, help="Max zoom factor")
    args = parser.parse_args()

    # Load image and labels
    image = cv2.imread(args.image)
    if image is None:
        print(f"Error: Cannot load image {args.image}")
        exit(1)

    labels = np.loadtxt(args.labels).reshape(-1, 5)

    print(f"Image shape: {image.shape}")
    print(f"Labels: {len(labels)} faces")

    # Create augmenter
    augmenter = TinyFaceZoomAugmentation(
        zoom_probability=args.zoom_prob,
        min_zoom=args.min_zoom,
        max_zoom=args.max_zoom,
    )

    # Apply augmentation
    zoomed_image, zoomed_labels, metadata = augmenter.maybe_zoom_tiny_faces(
        image, labels
    )

    print(f"Zoom applied: {metadata['zoom_applied']}")
    print(f"Tiny faces found: {metadata['tiny_faces']}")
    print(f"Zoomed faces: {metadata.get('zoomed_faces', 0)}")
    print(f"Zoom factor: {metadata.get('zoom_factor', 'N/A')}")

    # Draw bounding boxes
    h, w = zoomed_image.shape[:2]
    for label in zoomed_labels:
        cls, x, y, lw, lh = label
        x1 = int((x - lw / 2) * w)
        y1 = int((y - lh / 2) * h)
        x2 = int((x + lw / 2) * w)
        y2 = int((y + lh / 2) * h)
        cv2.rectangle(zoomed_image, (x1, y1), (x2, y2), (0, 255, 0), 2)

    cv2.imwrite(args.output, zoomed_image)
    print(f"Saved: {args.output}")
