#!/usr/bin/env python3
"""
Download SOTA models for PII Face Blurring service

Models:
- YOLOv11m-face: SOTA face detection (97%+ mAP on WIDER FACE)
- SegFormer face-parsing: Pixel-perfect face segmentation (19 classes)
- OSNet Re-ID: Person re-identification for video tracking (BoT-SORT)

Run: python scripts/download_models.py
"""

import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import logging

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def download_yolo_face():
    """Download SOTA YOLOv11m-face model from HuggingFace"""
    from huggingface_hub import hf_hub_download

    logger.info("=" * 60)
    logger.info("Downloading YOLOv11m-Face (SOTA Face Detection)")
    logger.info("Source: https://huggingface.co/akanametov/yolov11m-face")
    logger.info("=" * 60)

    model_dir = Path("/models/yolo-face")
    model_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Primary: YOLOv11m-face from akanametov (SOTA)
        model_path = hf_hub_download(
            repo_id="akanametov/yolov11m-face",
            filename="yolov11m-face.pt",
            local_dir=str(model_dir),
        )
        logger.info(f"✅ Downloaded YOLOv11m-face to {model_path}")
        return model_path
    except Exception as e:
        logger.warning(f"Primary source failed: {e}")

    try:
        # Fallback: YOLOv8m-face from arnabdhar
        logger.info("Trying fallback: YOLOv8m-face...")
        model_path = hf_hub_download(
            repo_id="arnabdhar/YOLOv8-Face-Detection",
            filename="model.pt",
            local_dir=str(model_dir),
        )
        logger.info(f"✅ Downloaded YOLOv8m-face to {model_path}")
        return model_path
    except Exception as e:
        logger.error(f"All downloads failed: {e}")
        raise


def download_segformer_face_parsing():
    """Download SegFormer face-parsing model for pixel-perfect masks"""
    from transformers import SegformerImageProcessor, SegformerForSemanticSegmentation

    logger.info("=" * 60)
    logger.info("Downloading SegFormer Face Parsing (19-class segmentation)")
    logger.info("Source: https://huggingface.co/jonathandinu/face-parsing")
    logger.info("=" * 60)

    model_id = "jonathandinu/face-parsing"
    cache_dir = "/models/segformer"

    try:
        processor = SegformerImageProcessor.from_pretrained(
            model_id, cache_dir=cache_dir
        )
        model = SegformerForSemanticSegmentation.from_pretrained(
            model_id, cache_dir=cache_dir
        )
        logger.info(f"✅ Downloaded SegFormer face-parsing to {cache_dir}")
        logger.info(
            f"   Model: {model.config.num_labels} classes (skin, nose, eyes, etc.)"
        )
        return cache_dir
    except Exception as e:
        logger.error(f"SegFormer download failed: {e}")
        raise


def download_yolov8_seg_face():
    """Download YOLOv8-seg face model for fast segmentation"""
    from huggingface_hub import hf_hub_download

    logger.info("=" * 60)
    logger.info("Downloading YOLOv8n-seg Face (Fast Segmentation)")
    logger.info("Source: https://huggingface.co/jags/yolov8_model_segmentation-set")
    logger.info("=" * 60)

    model_dir = Path("/models/yolo-seg")
    model_dir.mkdir(parents=True, exist_ok=True)

    try:
        model_path = hf_hub_download(
            repo_id="jags/yolov8_model_segmentation-set",
            filename="face_yolov8n-seg2_60.pt",
            local_dir=str(model_dir),
        )
        logger.info(f"✅ Downloaded YOLOv8n-seg-face to {model_path}")
        return model_path
    except Exception as e:
        logger.error(f"YOLOv8-seg download failed: {e}")
        raise


def download_reid_weights():
    """Download Re-ID weights for BoT-SORT tracking"""
    from huggingface_hub import hf_hub_download

    logger.info("=" * 60)
    logger.info("Downloading OSNet Re-ID Weights (Video Tracking)")
    logger.info("Used by: BoT-SORT, StrongSORT, DeepOCSORT")
    logger.info("=" * 60)

    model_dir = Path("/models/reid")
    model_dir.mkdir(parents=True, exist_ok=True)

    try:
        # OSNet x0.25 trained on MSMT17 - lightweight Re-ID model
        model_path = hf_hub_download(
            repo_id="mikel-brostrom/osnet_x0_25_msmt17",
            filename="osnet_x0_25_msmt17.pt",
            local_dir=str(model_dir),
        )
        logger.info(f"✅ Downloaded OSNet Re-ID to {model_path}")
        return model_path
    except Exception as e:
        logger.warning(f"HuggingFace download failed: {e}")

    # Fallback: BoxMOT will download automatically
    logger.info("Re-ID weights will be downloaded by BoxMOT on first use")
    return None


def main():
    """Download all required models"""
    logger.info("🚀 Starting SOTA model downloads for PII Face Blurring")
    logger.info("")

    results = {}

    # 1. Face Detection
    try:
        results["yolo_face"] = download_yolo_face()
    except Exception as e:
        results["yolo_face"] = f"FAILED: {e}"

    # 2. Face Segmentation - SegFormer (quality)
    try:
        results["segformer"] = download_segformer_face_parsing()
    except Exception as e:
        results["segformer"] = f"FAILED: {e}"

    # 3. Face Segmentation - YOLOv8-seg (speed)
    try:
        results["yolo_seg"] = download_yolov8_seg_face()
    except Exception as e:
        results["yolo_seg"] = f"FAILED: {e}"

    # 4. Re-ID for video tracking
    try:
        results["reid"] = download_reid_weights()
    except Exception as e:
        results["reid"] = f"FAILED: {e}"

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("📋 DOWNLOAD SUMMARY")
    logger.info("=" * 60)
    for model, path in results.items():
        status = "✅" if path and "FAILED" not in str(path) else "❌"
        logger.info(f"{status} {model}: {path}")

    # Check if critical models succeeded
    critical = ["yolo_face"]
    failed = [m for m in critical if "FAILED" in str(results.get(m, "FAILED"))]

    if failed:
        logger.error(f"❌ Critical models failed: {failed}")
        sys.exit(1)
    else:
        logger.info("")
        logger.info("✅ All critical models downloaded successfully!")
        logger.info("   Run: docker compose restart pii-blur")


if __name__ == "__main__":
    main()
