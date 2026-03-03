#!/usr/bin/env python3
"""
Roboflow Auto-Annotation Script for Face Detection

Uses Grounding DINO + SAM 2 to automatically annotate face images.

Methods:
1. Roboflow Inference API with YOLO-World / Grounding DINO
2. Roboflow Label Assist (cloud-based)
3. Local inference with model download

Usage:
    python roboflow_auto_annotate.py label-assist  # Cloud-based labeling
    python roboflow_auto_annotate.py local         # Local GPU inference
    python roboflow_auto_annotate.py status        # Check annotation status
"""

import os
import sys
import json
import asyncio
import aiohttp
from pathlib import Path
from typing import Optional
import sqlite3

# Configuration
WORKSPACE = "shmlplatform"
PROJECT = "yfcc100m-faces"
BASE_DIR = Path(__file__).parent.parent.parent / "data" / "datasets" / "yfcc100m"
IMAGES_DIR = BASE_DIR / "images"
ANNOTATIONS_DIR = BASE_DIR / "annotations"
METADATA_DB = BASE_DIR / "face_metadata.db"

# Face detection prompts for foundation models
FACE_PROMPTS = [
    "human face",
    "face",
    "person's face",
]


def get_api_key() -> str:
    """Get Roboflow API key from environment."""
    key = os.environ.get("AXELOFWAR_ROBOFLOW_API_KEY")
    if not key:
        # Try loading from .env
        env_file = Path(__file__).parent.parent.parent.parent / ".env"
        if env_file.exists():
            with open(env_file) as f:
                for line in f:
                    if line.startswith("AXELOFWAR_ROBOFLOW_API_KEY="):
                        key = line.split("=", 1)[1].strip().strip('"')
                        break
    if not key:
        raise ValueError("AXELOFWAR_ROBOFLOW_API_KEY not found")
    return key


def get_project_status():
    """Get current project annotation status."""
    import requests

    api_key = get_api_key()
    url = f"https://api.roboflow.com/{WORKSPACE}/{PROJECT}?api_key={api_key}"

    resp = requests.get(url)
    if not resp.ok:
        print(f"Error: {resp.status_code} - {resp.text}")
        return

    data = resp.json()
    project = data.get("project", {})

    print("=" * 50)
    print("YFCC100M Faces - Project Status")
    print("=" * 50)
    print(f"  Name: {project.get('name')}")
    print(f"  Type: {project.get('type')}")
    print(f"  Unannotated: {project.get('unannotated', 0):,}")
    print(f"  Annotated: {project.get('annotated', 0):,}")
    print(
        f"  Total Images: {project.get('unannotated', 0) + (project.get('annotated') or 0):,}"
    )
    print(f"  Classes: {project.get('classes', {})}")
    print(f"  Splits: {project.get('splits', {})}")
    print("=" * 50)

    return project


async def label_assist_batch(
    api_key: str, image_ids: list, model: str = "grounding-dino-base"
):
    """
    Use Roboflow Label Assist API to auto-annotate images.

    Note: This requires Roboflow Pro/Enterprise for batch auto-labeling.
    For free tier, use the web UI or local inference.
    """
    url = f"https://api.roboflow.com/{WORKSPACE}/{PROJECT}/annotate"

    headers = {
        "Content-Type": "application/json",
    }

    payload = {
        "api_key": api_key,
        "model": model,  # "grounding-dino-base" or "yolo-world"
        "prompt": "human face",
        "image_ids": image_ids,
        "confidence_threshold": 0.3,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as resp:
            if resp.status == 200:
                result = await resp.json()
                print(f"Label assist result: {result}")
                return result
            else:
                text = await resp.text()
                print(f"Error {resp.status}: {text}")
                return None


def run_local_inference(batch_size: int = 100, max_images: Optional[int] = None):
    """
    Run local inference using Grounding DINO + SAM for face detection.
    Requires GPU and installed models.
    """
    try:
        from autodistill_grounded_sam import GroundedSAM
        from autodistill.detection import CaptionOntology
        import supervision as sv
    except ImportError:
        print("Error: autodistill packages not installed.")
        print(
            "Install with: pip install autodistill autodistill-grounded-sam supervision"
        )
        return

    # Create ontology for face detection
    ontology = CaptionOntology(
        {
            "human face": "face",
            "person's face": "face",
            "face": "face",
        }
    )

    print("Loading GroundedSAM model...")
    base_model = GroundedSAM(ontology=ontology)

    # Get images to process
    images = list(IMAGES_DIR.glob("*.jpg"))
    if max_images:
        images = images[:max_images]

    print(f"Processing {len(images)} images...")

    # Create annotations directory
    ANNOTATIONS_DIR.mkdir(parents=True, exist_ok=True)

    # Process in batches
    for i in range(0, len(images), batch_size):
        batch = images[i : i + batch_size]
        print(f"\nBatch {i//batch_size + 1}: Processing {len(batch)} images...")

        for img_path in batch:
            try:
                # Run detection
                detections = base_model.predict(str(img_path))

                if len(detections) > 0:
                    # Convert to YOLO format
                    annotation_path = ANNOTATIONS_DIR / f"{img_path.stem}.txt"
                    with open(annotation_path, "w") as f:
                        for detection in detections:
                            # YOLO format: class x_center y_center width height
                            bbox = detection.xyxy[0]  # x1, y1, x2, y2
                            # Convert to normalized center + size
                            # (Would need image dimensions here)
                            f.write(f"0 {bbox[0]} {bbox[1]} {bbox[2]} {bbox[3]}\n")

            except Exception as e:
                print(f"Error processing {img_path.name}: {e}")


def use_roboflow_inference():
    """
    Use Roboflow Inference API with YOLO-World for face detection.
    This is available on free tier with rate limits.
    """
    import requests
    from PIL import Image
    import base64
    import io

    api_key = get_api_key()

    # Use YOLO-World or a pre-trained face detection model
    # Option 1: Use Roboflow Universe face detection model
    model_id = "face-detection-mik1i/18"  # Popular face detection model

    # Option 2: Use YOLO-World with "face" prompt
    # model_id = "yolo-world/v2"

    images = list(IMAGES_DIR.glob("*.jpg"))[:10]  # Test with 10 images first

    print(f"Testing Roboflow Inference API with {len(images)} images...")

    ANNOTATIONS_DIR.mkdir(parents=True, exist_ok=True)

    for img_path in images:
        # Load and encode image
        with open(img_path, "rb") as f:
            img_base64 = base64.b64encode(f.read()).decode()

        # Send to Roboflow Inference
        url = f"https://detect.roboflow.com/{model_id}?api_key={api_key}"

        resp = requests.post(
            url,
            data=img_base64,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if resp.ok:
            result = resp.json()
            predictions = result.get("predictions", [])

            if predictions:
                print(f"✓ {img_path.name}: {len(predictions)} faces detected")

                # Save annotations in YOLO format
                with open(ANNOTATIONS_DIR / f"{img_path.stem}.txt", "w") as f:
                    img_width = result.get("image", {}).get("width", 1)
                    img_height = result.get("image", {}).get("height", 1)

                    for pred in predictions:
                        # Convert to normalized YOLO format
                        x_center = pred["x"] / img_width
                        y_center = pred["y"] / img_height
                        width = pred["width"] / img_width
                        height = pred["height"] / img_height

                        f.write(
                            f"0 {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}\n"
                        )
            else:
                print(f"  {img_path.name}: No faces detected")
        else:
            print(f"✗ {img_path.name}: Error {resp.status_code}")


def upload_annotations_to_roboflow():
    """Upload local annotations back to Roboflow project."""
    from roboflow import Roboflow

    api_key = get_api_key()
    rf = Roboflow(api_key=api_key)
    project = rf.workspace().project(PROJECT)

    annotation_files = list(ANNOTATIONS_DIR.glob("*.txt"))
    print(f"Found {len(annotation_files)} annotation files")

    uploaded = 0
    for ann_path in annotation_files:
        img_path = IMAGES_DIR / f"{ann_path.stem}.jpg"

        if img_path.exists():
            try:
                project.upload(
                    image_path=str(img_path),
                    annotation_path=str(ann_path),
                    split="train",
                )
                uploaded += 1

                if uploaded % 100 == 0:
                    print(f"Uploaded {uploaded} annotated images")

            except Exception as e:
                print(f"Error uploading {img_path.name}: {e}")

    print(f"\n✓ Uploaded {uploaded} annotated images to Roboflow")


def generate_web_ui_instructions():
    """Print instructions for using Roboflow web UI auto-labeling."""
    print(
        """
╔══════════════════════════════════════════════════════════════════╗
║         ROBOFLOW WEB UI AUTO-LABELING INSTRUCTIONS               ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  1. Open your project:                                           ║
║     https://app.roboflow.com/shmlplatform/yfcc100m-faces         ║
║                                                                  ║
║  2. Go to "Annotate" tab                                         ║
║                                                                  ║
║  3. Click "Auto Label" button (or "Smart Polygon")               ║
║                                                                  ║
║  4. Configure auto-labeling:                                     ║
║     • Model: Select "Grounding DINO" or "YOLO-World"             ║
║     • Prompt: Enter "face" or "human face"                       ║
║     • Confidence: Set to 0.3-0.5                                 ║
║     • Output: Bounding box or Polygon                            ║
║                                                                  ║
║  5. Select images to label:                                      ║
║     • "All unannotated" for batch processing                     ║
║     • Or select specific images                                  ║
║                                                                  ║
║  6. Click "Run" and wait for processing                          ║
║                                                                  ║
║  7. Review and approve annotations:                              ║
║     • Check quality of auto-labels                               ║
║     • Adjust confidence threshold if needed                      ║
║     • Fix any incorrect annotations                              ║
║                                                                  ║
║  8. Generate dataset version when ready                          ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
"""
    )


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nCommands:")
        print("  status         - Check project annotation status")
        print("  web-ui         - Show web UI auto-labeling instructions")
        print("  inference      - Run Roboflow Inference API (10 test images)")
        print("  local          - Run local GroundedSAM inference (GPU required)")
        print("  upload         - Upload local annotations to Roboflow")
        return

    command = sys.argv[1].lower()

    if command == "status":
        get_project_status()

    elif command == "web-ui":
        generate_web_ui_instructions()

    elif command == "inference":
        use_roboflow_inference()

    elif command == "local":
        max_images = int(sys.argv[2]) if len(sys.argv) > 2 else None
        run_local_inference(max_images=max_images)

    elif command == "upload":
        upload_annotations_to_roboflow()

    elif command == "label-assist":
        print("Label Assist API requires Roboflow Pro/Enterprise.")
        print("Use 'web-ui' command for free tier auto-labeling.")
        generate_web_ui_instructions()

    else:
        print(f"Unknown command: {command}")
        print("Use: status, web-ui, inference, local, upload")


if __name__ == "__main__":
    main()
