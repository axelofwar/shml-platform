#!/usr/bin/env python3
"""
Phase 10 — Multi-Source Face Detection Dataset (YOLO Format)
=============================================================

Downloads WIDER Face, CrowdHuman, and MAFA, converts to YOLO format,
and merges into a single dataset. Also runs offline tiny-face zoom
augmentation to generate supplemental crops.

Output structure:
    {output_dir}/
        images/
            train/   # All merged training images
            val/     # Validation (WIDER Face only for fair comparison)
        labels/
            train/
            val/
        data.yaml    # Ultralytics dataset config

Usage:
    python prepare_merged_yolo.py                                  # Full merge
    python prepare_merged_yolo.py --skip-crowdhuman --skip-mafa    # WIDER only
    python prepare_merged_yolo.py --skip-mafa                      # WIDER + CrowdHuman
    python prepare_merged_yolo.py --tiny-face-zoom                 # + zoom augmentation
    python prepare_merged_yolo.py --dry-run                        # Show plan only

Author: SHML Platform
Date: March 2026
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import zipfile
from pathlib import Path
from typing import Optional

import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WIDER_HF_URLS = {
    "train_images": "https://huggingface.co/datasets/wider_face/resolve/main/data/WIDER_train.zip",
    "val_images": "https://huggingface.co/datasets/wider_face/resolve/main/data/WIDER_val.zip",
    "annotations": "https://huggingface.co/datasets/wider_face/resolve/main/data/wider_face_split.zip",
}

# ---------------------------------------------------------------------------
# Download Helpers
# ---------------------------------------------------------------------------


def download_file(url: str, dest: Path, desc: str = "") -> Path:
    """Download a file with progress."""
    import urllib.request

    if dest.exists():
        print(f"  ✓ Already downloaded: {dest.name}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  ⬇ Downloading {desc or dest.name}...")
    urllib.request.urlretrieve(url, str(dest))
    print(f"  ✓ Downloaded: {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)")
    return dest


def extract_zip(zip_path: Path, dest_dir: Path) -> None:
    """Extract a zip file."""
    print(f"  📦 Extracting {zip_path.name}...")
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(dest_dir)


# ---------------------------------------------------------------------------
# WIDER Face → YOLO
# ---------------------------------------------------------------------------


def parse_wider_annotations(annot_file: Path) -> dict[str, list[list[int]]]:
    """Parse WIDER Face annotation format → {filename: [[x,y,w,h], ...]}"""
    annotations = {}
    with open(annot_file) as f:
        while True:
            filename = f.readline().strip()
            if not filename:
                break
            n_faces = int(f.readline().strip())
            boxes = []
            if n_faces == 0:
                f.readline()
            else:
                for _ in range(n_faces):
                    parts = f.readline().strip().split()
                    x, y, w, h = (
                        int(parts[0]),
                        int(parts[1]),
                        int(parts[2]),
                        int(parts[3]),
                    )
                    invalid = int(parts[7]) if len(parts) > 7 else 0
                    if w > 0 and h > 0 and invalid == 0:
                        boxes.append([x, y, w, h])
            if boxes:
                annotations[filename] = boxes
    return annotations


def prepare_wider_yolo(
    cache_dir: Path,
    output_dir: Path,
    split: str,
) -> dict:
    """Download and convert WIDER Face to YOLO format."""
    print(f"\n━━━ WIDER Face ({split}) ━━━")

    # Download
    img_key = "train_images" if split == "train" else "val_images"
    img_zip = download_file(
        WIDER_HF_URLS[img_key],
        cache_dir / f"WIDER_{split}.zip",
        f"WIDER {split} images",
    )
    ann_zip = download_file(
        WIDER_HF_URLS["annotations"],
        cache_dir / "wider_face_split.zip",
        "WIDER annotations",
    )

    # Extract
    wider_dir = cache_dir / "wider_face"
    if not (cache_dir / f"WIDER_{split}").exists():
        extract_zip(img_zip, cache_dir)
    if not (wider_dir / "wider_face_split").exists():
        wider_dir.mkdir(parents=True, exist_ok=True)
        extract_zip(ann_zip, cache_dir)

    # Parse
    ann_subdir = "wider_face_split"
    ann_file = cache_dir / ann_subdir / f"wider_face_{split}_bbx_gt.txt"
    if not ann_file.exists():
        # Try alternative path
        ann_file = wider_dir / ann_subdir / f"wider_face_{split}_bbx_gt.txt"
    if not ann_file.exists():
        # Search for it
        import glob

        candidates = glob.glob(
            str(cache_dir / "**" / f"wider_face_{split}_bbx_gt.txt"), recursive=True
        )
        if candidates:
            ann_file = Path(candidates[0])
        else:
            print(f"  ✗ Annotation file not found")
            return {"images": 0, "annotations": 0}

    wider_anns = parse_wider_annotations(ann_file)
    print(f"  Parsed {len(wider_anns)} annotated images")

    # Convert to YOLO format
    img_dst = output_dir / "images" / split
    lbl_dst = output_dir / "labels" / split
    img_dst.mkdir(parents=True, exist_ok=True)
    lbl_dst.mkdir(parents=True, exist_ok=True)

    src_dir = cache_dir / f"WIDER_{split}" / "images"
    n_images = 0
    n_annotations = 0

    for filename, boxes in wider_anns.items():
        src_path = src_dir / filename
        if not src_path.exists():
            continue

        # Flatten path: event/img.jpg → wider_event_img.jpg
        flat_name = filename.replace("/", "_")
        img_path = img_dst / f"wider_{flat_name}"
        lbl_path = lbl_dst / f"wider_{flat_name}".replace(".jpg", ".txt").replace(
            ".png", ".txt"
        )

        if not img_path.exists():
            shutil.copy2(src_path, img_path)

        # Get image dimensions
        try:
            from PIL import Image

            with Image.open(img_path) as img:
                w_img, h_img = img.size
        except Exception:
            continue

        # Write YOLO labels: class x_center y_center width height (normalized)
        yolo_lines = []
        for box in boxes:
            x, y, w, h = box
            # Convert from (x,y,w,h) top-left to (x_center, y_center, w, h) normalized
            x_center = (x + w / 2) / w_img
            y_center = (y + h / 2) / h_img
            w_norm = w / w_img
            h_norm = h / h_img
            # Clamp to [0, 1]
            x_center = max(0.0, min(1.0, x_center))
            y_center = max(0.0, min(1.0, y_center))
            w_norm = max(0.001, min(1.0, w_norm))
            h_norm = max(0.001, min(1.0, h_norm))
            yolo_lines.append(
                f"0 {x_center:.6f} {y_center:.6f} {w_norm:.6f} {h_norm:.6f}"
            )
            n_annotations += 1

        with open(lbl_path, "w") as f:
            f.write("\n".join(yolo_lines) + "\n")
        n_images += 1

    print(f"  ✓ {n_images} images, {n_annotations} face annotations")
    return {"images": n_images, "annotations": n_annotations}


# ---------------------------------------------------------------------------
# CrowdHuman → YOLO
# ---------------------------------------------------------------------------

# HuggingFace token — set via env HUGGING_FACE_HUB_TOKEN or --hf-token CLI arg
_HF_TOKEN: Optional[str] = os.environ.get("HUGGING_FACE_HUB_TOKEN")


def _get_hf_token() -> Optional[str]:
    return _HF_TOKEN


def prepare_crowdhuman_yolo(
    cache_dir: Path,
    output_dir: Path,
    split: str,
    max_images: int = 15000,
) -> dict:
    """Download and convert CrowdHuman head boxes to YOLO face format.

    CrowdHuman 'hbox' (head bbox) is used as face proxy.
    Images are downloaded as zip archives from sshao0516/CrowdHuman on HuggingFace.
    Only downloads train split for augmenting training data.
    """
    print(f"\n━━━ CrowdHuman ({split}) ━━━")

    if split == "val":
        print("  ℹ Skipping CrowdHuman val (use WIDER Face val for fair comparison)")
        return {"images": 0, "annotations": 0}

    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("  ⚠ huggingface_hub not installed, skipping CrowdHuman")
        return {"images": 0, "annotations": 0}

    CROWDHUMAN_REPO = "sshao0516/CrowdHuman"
    hf_token = _get_hf_token()

    ch_dir = cache_dir / "crowdhuman"
    ch_dir.mkdir(parents=True, exist_ok=True)
    extract_dir = ch_dir / "images_extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)

    img_dst = output_dir / "images" / split
    lbl_dst = output_dir / "labels" / split
    img_dst.mkdir(parents=True, exist_ok=True)
    lbl_dst.mkdir(parents=True, exist_ok=True)

    # Step 1: Download annotation file
    odgt_name = f"annotation_{split}.odgt"
    print(f"  Downloading {odgt_name} ...")
    try:
        odgt_path = hf_hub_download(
            repo_id=CROWDHUMAN_REPO,
            filename=odgt_name,
            cache_dir=str(ch_dir),
            repo_type="dataset",
            token=hf_token,
        )
        print(
            f"  ✓ Annotations downloaded ({Path(odgt_path).stat().st_size / 1e6:.1f} MB)"
        )
    except Exception as e:
        print(f"  ⚠ CrowdHuman annotation download failed: {e}")
        return {"images": 0, "annotations": 0}

    # Step 2: Parse annotations first to build image ID → boxes mapping
    print(f"  Parsing annotations ...")
    image_records = {}  # image_id → list of hboxes
    with open(odgt_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            image_id = record.get("ID", "")
            gtboxes = record.get("gtboxes", [])
            hboxes = []
            for gt in gtboxes:
                if gt.get("tag") != "person":
                    continue
                hbox = gt.get("hbox")
                if hbox and len(hbox) == 4:
                    hboxes.append(hbox)
            if hboxes:
                image_records[image_id] = hboxes
    print(f"  ✓ Found {len(image_records)} images with head annotations")

    # Step 3: Download and extract image zip files
    if split == "train":
        zip_files = [
            "CrowdHuman_train01.zip",
            "CrowdHuman_train02.zip",
            "CrowdHuman_train03.zip",
        ]
    else:
        zip_files = [f"CrowdHuman_{split}.zip"]

    all_image_paths: dict[str, Path] = {}  # image_id → extracted path
    for zip_name in zip_files:
        zip_marker = extract_dir / f".{zip_name}.done"
        if zip_marker.exists():
            print(f"  ✓ {zip_name} already extracted")
        else:
            print(f"  Downloading {zip_name} (this may take a while) ...")
            try:
                zip_path = hf_hub_download(
                    repo_id=CROWDHUMAN_REPO,
                    filename=zip_name,
                    cache_dir=str(ch_dir),
                    repo_type="dataset",
                    token=hf_token,
                )
            except Exception as e:
                print(f"  ⚠ Failed to download {zip_name}: {e}")
                continue

            print(f"  Extracting {zip_name} ...")
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(extract_dir)
                zip_marker.touch()
                print(f"  ✓ {zip_name} extracted")
            except Exception as e:
                print(f"  ⚠ Failed to extract {zip_name}: {e}")
                continue

    # Index extracted images — CrowdHuman zips contain Images/*.jpg
    for img_path in extract_dir.rglob("*.jpg"):
        stem = img_path.stem  # e.g. "273271,1a0d6000b9e1f5b7"
        all_image_paths[stem] = img_path
    print(f"  ✓ Indexed {len(all_image_paths)} extracted images")

    # Step 4: Convert to YOLO format
    n_images = 0
    n_annotations = 0
    skipped = 0

    for image_id, hboxes in image_records.items():
        if n_images >= max_images:
            break

        img_path = all_image_paths.get(image_id)
        if img_path is None:
            skipped += 1
            continue

        # Copy image to output
        dst_img_name = f"ch_{image_id}.jpg"
        dst_img = img_dst / dst_img_name
        if not dst_img.exists():
            shutil.copy2(img_path, dst_img)

        # Get image dimensions
        try:
            from PIL import Image

            with Image.open(dst_img) as img:
                w_img, h_img = img.size
        except Exception:
            skipped += 1
            continue

        # Convert head boxes to YOLO format
        yolo_lines = []
        for hbox in hboxes:
            x, y, w, h = hbox
            if w <= 0 or h <= 0:
                continue
            # Clamp
            x = max(0, x)
            y = max(0, y)
            w = min(w, w_img - x)
            h = min(h, h_img - y)
            # YOLO normalized format
            x_center = (x + w / 2) / w_img
            y_center = (y + h / 2) / h_img
            w_norm = w / w_img
            h_norm = h / h_img
            x_center = max(0.0, min(1.0, x_center))
            y_center = max(0.0, min(1.0, y_center))
            w_norm = max(0.001, min(1.0, w_norm))
            h_norm = max(0.001, min(1.0, h_norm))
            yolo_lines.append(
                f"0 {x_center:.6f} {y_center:.6f} {w_norm:.6f} {h_norm:.6f}"
            )
            n_annotations += 1

        if yolo_lines:
            lbl_path = lbl_dst / dst_img_name.replace(".jpg", ".txt")
            with open(lbl_path, "w") as f_out:
                f_out.write("\n".join(yolo_lines) + "\n")
            n_images += 1

        if n_images % 2000 == 0 and n_images > 0:
            print(f"    ... {n_images} images processed ({n_annotations} annotations)")

    if skipped:
        print(f"  ℹ Skipped {skipped} images (not found in extracted zips)")
    print(f"  ✓ {n_images} images, {n_annotations} head-as-face annotations")
    return {"images": n_images, "annotations": n_annotations}


# ---------------------------------------------------------------------------
# MAFA → YOLO
# ---------------------------------------------------------------------------


def prepare_mafa_yolo(
    cache_dir: Path,
    output_dir: Path,
    split: str,
    max_images: int = 25000,
) -> dict:
    """Download and convert MAFA masked face dataset to YOLO format."""
    print(f"\n━━━ MAFA Masked Faces ({split}) ━━━")

    if split == "val":
        print("  ℹ Skipping MAFA val (use WIDER Face val for fair comparison)")
        return {"images": 0, "annotations": 0}

    mafa_dir = cache_dir / "mafa"
    mafa_dir.mkdir(parents=True, exist_ok=True)

    img_dst = output_dir / "images" / split
    lbl_dst = output_dir / "labels" / split
    img_dst.mkdir(parents=True, exist_ok=True)
    lbl_dst.mkdir(parents=True, exist_ok=True)

    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("  ⚠ huggingface_hub not installed, skipping MAFA")
        return {"images": 0, "annotations": 0}

    # Try MAFA annotation download
    try:
        annot_subdir = "MAFA-Label-Train" if split == "train" else "MAFA-Label-Test"
        annot_name = "LabelTrainAll.txt" if split == "train" else "LabelTestAll.txt"
        annot_path = hf_hub_download(
            repo_id="Kuixiang/MAFA",
            filename=f"{annot_subdir}/{annot_name}",
            cache_dir=str(mafa_dir),
            repo_type="dataset",
            token=_get_hf_token(),
        )
    except Exception as e:
        print(f"  ⚠ MAFA download failed: {e}")
        print(f"  ℹ MAFA is optional — training proceeds with other datasets")
        return {"images": 0, "annotations": 0}

    n_images = 0
    n_annotations = 0
    current_img_name = None
    current_yolo_lines = []

    def flush_image():
        nonlocal n_images
        if current_img_name and current_yolo_lines:
            lbl_path = lbl_dst / f"mafa_{current_img_name}".replace(
                ".jpg", ".txt"
            ).replace(".png", ".txt")
            with open(lbl_path, "w") as f_out:
                f_out.write("\n".join(current_yolo_lines) + "\n")
            n_images += 1

    try:
        with open(annot_path) as f:
            for line in f:
                if n_images >= max_images:
                    break

                parts = line.strip().split()
                if not parts:
                    continue

                # Detect image filename line
                if len(parts) == 1 and parts[0].endswith((".jpg", ".png", ".jpeg")):
                    flush_image()
                    current_yolo_lines = []
                    current_img_name = parts[0]

                    # Download image
                    try:
                        img_path = hf_hub_download(
                            repo_id="Kuixiang/MAFA",
                            filename=f"images/{current_img_name}",
                            cache_dir=str(mafa_dir),
                            repo_type="dataset",
                            token=_get_hf_token(),
                        )
                        dst_img = img_dst / f"mafa_{current_img_name}"
                        if not dst_img.exists():
                            shutil.copy2(img_path, dst_img)
                    except Exception:
                        current_img_name = None
                        continue

                elif len(parts) >= 4 and current_img_name:
                    try:
                        x, y, w, h = (
                            float(parts[0]),
                            float(parts[1]),
                            float(parts[2]),
                            float(parts[3]),
                        )
                        if w <= 0 or h <= 0:
                            continue

                        # Need image dimensions for normalization
                        dst_img = img_dst / f"mafa_{current_img_name}"
                        from PIL import Image

                        with Image.open(dst_img) as img:
                            w_img, h_img = img.size

                        x_center = (x + w / 2) / w_img
                        y_center = (y + h / 2) / h_img
                        w_norm = w / w_img
                        h_norm = h / h_img
                        x_center = max(0.0, min(1.0, x_center))
                        y_center = max(0.0, min(1.0, y_center))
                        w_norm = max(0.001, min(1.0, w_norm))
                        h_norm = max(0.001, min(1.0, h_norm))
                        current_yolo_lines.append(
                            f"0 {x_center:.6f} {y_center:.6f} {w_norm:.6f} {h_norm:.6f}"
                        )
                        n_annotations += 1
                    except ValueError:
                        continue

                if n_images % 1000 == 0 and n_images > 0:
                    print(f"    ... {n_images} images processed")

        flush_image()  # Don't forget last image
    except Exception as e:
        print(f"  ⚠ MAFA parsing error: {e}")

    print(f"  ✓ {n_images} images, {n_annotations} masked face annotations")
    return {"images": n_images, "annotations": n_annotations}


# ---------------------------------------------------------------------------
# Tiny Face Zoom Augmentation (Offline)
# ---------------------------------------------------------------------------


def run_tiny_face_zoom(
    output_dir: Path,
    split: str = "train",
    zoom_prob: float = 1.0,
    max_images: int = 5000,
) -> dict:
    """Run offline tiny-face zoom augmentation on the merged dataset.

    Creates new cropped/upscaled images focusing on tiny face regions,
    and adds them as supplemental training data.
    """
    print(f"\n━━━ Tiny Face Zoom Augmentation ({split}) ━━━")

    # Try to import the augmentation module
    script_dir = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(script_dir / "jobs" / "utils"))
    sys.path.insert(0, str(script_dir / "jobs"))

    try:
        from utils.tiny_face_augmentation import TinyFaceZoomAugmentation
    except ImportError:
        try:
            from tiny_face_augmentation import TinyFaceZoomAugmentation
        except ImportError:
            print("  ⚠ tiny_face_augmentation module not found, skipping")
            return {"images": 0, "annotations": 0}

    import cv2

    augmenter = TinyFaceZoomAugmentation(
        zoom_probability=zoom_prob,
        min_zoom=2.0,
        max_zoom=4.0,
        tiny_face_threshold=0.03,
        small_face_threshold=0.08,
        min_faces_in_crop=1,
    )

    img_dir = output_dir / "images" / split
    lbl_dir = output_dir / "labels" / split

    if not img_dir.exists():
        print(f"  ✗ Image dir not found: {img_dir}")
        return {"images": 0, "annotations": 0}

    img_files = sorted(img_dir.glob("*.jpg")) + sorted(img_dir.glob("*.png"))
    print(f"  Found {len(img_files)} images to scan for tiny faces")

    n_generated = 0
    n_annotations = 0

    for img_file in img_files:
        if n_generated >= max_images:
            break

        lbl_file = lbl_dir / img_file.with_suffix(".txt").name
        if not lbl_file.exists():
            continue

        # Load image and labels
        image = cv2.imread(str(img_file))
        if image is None:
            continue

        try:
            labels = np.loadtxt(str(lbl_file)).reshape(-1, 5)
        except Exception:
            continue

        if len(labels) == 0:
            continue

        # Apply zoom augmentation
        zoomed_img, zoomed_labels, metadata = augmenter.maybe_zoom_tiny_faces(
            image, labels
        )

        if metadata.get("zoom_applied", False) and len(zoomed_labels) > 0:
            # Save augmented image and labels
            zoom_name = f"zoom_{img_file.stem}"
            zoom_img_path = img_dir / f"{zoom_name}.jpg"
            zoom_lbl_path = lbl_dir / f"{zoom_name}.txt"

            cv2.imwrite(str(zoom_img_path), zoomed_img)
            yolo_lines = []
            for lbl in zoomed_labels:
                yolo_lines.append(
                    f"0 {lbl[1]:.6f} {lbl[2]:.6f} {lbl[3]:.6f} {lbl[4]:.6f}"
                )
            with open(zoom_lbl_path, "w") as f:
                f.write("\n".join(yolo_lines) + "\n")

            n_generated += 1
            n_annotations += len(zoomed_labels)

        if n_generated % 500 == 0 and n_generated > 0:
            print(f"    ... {n_generated} zoom images generated")

    stats = augmenter.get_statistics()
    print(
        f"  ✓ Generated {n_generated} zoom-augmented images ({n_annotations} annotations)"
    )
    print(f"    Tiny faces found: {stats.get('tiny_faces_found', 0)}")
    print(f"    Zoom rate: {stats.get('zoom_rate', 0):.1%}")

    return {"images": n_generated, "annotations": n_annotations}


# ---------------------------------------------------------------------------
# Dataset Statistics
# ---------------------------------------------------------------------------


def compute_yolo_stats(output_dir: Path, split: str) -> dict:
    """Compute statistics for a YOLO-format dataset split."""
    lbl_dir = output_dir / "labels" / split
    img_dir = output_dir / "images" / split

    if not lbl_dir.exists():
        return {}

    n_images = len(list(img_dir.glob("*.jpg"))) + len(list(img_dir.glob("*.png")))
    label_files = list(lbl_dir.glob("*.txt"))

    total_annotations = 0
    sizes = []
    faces_per_image = []

    for lbl_file in label_files:
        try:
            labels = np.loadtxt(str(lbl_file)).reshape(-1, 5)
        except Exception:
            continue

        n_faces = len(labels)
        total_annotations += n_faces
        faces_per_image.append(n_faces)

        for lbl in labels:
            max_side = max(lbl[3], lbl[4])  # normalized
            # Approximate pixel size assuming ~1024px image
            px_size = max_side * 1024
            sizes.append(px_size)

    size_buckets = {
        "tiny_lt32": sum(1 for s in sizes if s < 32),
        "small_32_96": sum(1 for s in sizes if 32 <= s < 96),
        "medium_96_256": sum(1 for s in sizes if 96 <= s < 256),
        "large_gt256": sum(1 for s in sizes if s >= 256),
    }

    return {
        "total_images": n_images,
        "total_annotations": total_annotations,
        "label_files": len(label_files),
        "faces_per_image_mean": (
            float(np.mean(faces_per_image)) if faces_per_image else 0
        ),
        "faces_per_image_median": (
            float(np.median(faces_per_image)) if faces_per_image else 0
        ),
        "face_size_distribution": size_buckets,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Prepare merged face detection dataset (YOLO format)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="/tmp/ray/data/face_merged_yolo",
        help="Output directory for merged YOLO dataset",
    )
    parser.add_argument(
        "--cache",
        type=str,
        default="/tmp/ray/data/face_data_cache",
        help="Cache directory for downloads",
    )
    parser.add_argument(
        "--skip-crowdhuman", action="store_true", help="Skip CrowdHuman dataset"
    )
    parser.add_argument(
        "--skip-mafa", action="store_true", help="Skip MAFA masked faces dataset"
    )
    parser.add_argument(
        "--tiny-face-zoom",
        action="store_true",
        help="Run offline tiny-face zoom augmentation",
    )
    parser.add_argument(
        "--max-crowdhuman",
        type=int,
        default=15000,
        help="Max CrowdHuman images to include",
    )
    parser.add_argument(
        "--max-mafa", type=int, default=25000, help="Max MAFA images to include"
    )
    parser.add_argument(
        "--max-zoom",
        type=int,
        default=5000,
        help="Max zoom-augmented images to generate",
    )
    parser.add_argument(
        "--link-wider",
        action="store_true",
        help="Symlink existing WIDER YOLO data instead of re-downloading",
    )
    parser.add_argument(
        "--wider-yolo-dir",
        type=str,
        default="/tmp/ray/data/wider_face_yolo",
        help="Path to existing WIDER Face YOLO dataset",
    )
    parser.add_argument(
        "--hf-token",
        type=str,
        default=None,
        help="HuggingFace API token (or set HUGGING_FACE_HUB_TOKEN env var)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show plan and exit")
    args = parser.parse_args()

    # Wire HF token from CLI or env
    global _HF_TOKEN
    if args.hf_token:
        _HF_TOKEN = args.hf_token
        os.environ["HUGGING_FACE_HUB_TOKEN"] = args.hf_token

    output_dir = Path(args.output)
    cache_dir = Path(args.cache)

    print("=" * 70)
    print("PHASE 10: Multi-Source Face Detection Dataset (YOLO Format)")
    print("=" * 70)
    print(f"  Output:     {output_dir}")
    print(f"  Cache:      {cache_dir}")
    sources = ["WIDER Face"]
    if not args.skip_crowdhuman:
        sources.append(f"CrowdHuman (max {args.max_crowdhuman})")
    if not args.skip_mafa:
        sources.append(f"MAFA (max {args.max_mafa})")
    if args.tiny_face_zoom:
        sources.append(f"Tiny Face Zoom (max {args.max_zoom})")
    print(f"  Datasets:   {' + '.join(sources)}")
    print(f"  Link WIDER: {args.link_wider}")
    print()

    if args.dry_run:
        print("[dry-run] Plan validated. Run without --dry-run to execute.")
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    all_stats = {}
    start_time = time.time()

    for split in ["train", "val"]:
        print(f"\n{'=' * 50}")
        print(f"  Split: {split.upper()}")
        print(f"{'=' * 50}")

        split_stats = {}

        # --- WIDER Face ---
        if args.link_wider and Path(args.wider_yolo_dir).exists():
            print(f"\n━━━ WIDER Face ({split}) — Linking existing ━━━")
            src_img_dir = Path(args.wider_yolo_dir) / "images" / split
            src_lbl_dir = Path(args.wider_yolo_dir) / "labels" / split
            dst_img_dir = output_dir / "images" / split
            dst_lbl_dir = output_dir / "labels" / split
            dst_img_dir.mkdir(parents=True, exist_ok=True)
            dst_lbl_dir.mkdir(parents=True, exist_ok=True)

            # Copy (not symlink) for Docker compatibility
            n_copied = 0
            for src_img in src_img_dir.iterdir():
                dst_img = dst_img_dir / src_img.name
                if not dst_img.exists():
                    shutil.copy2(src_img, dst_img)
                n_copied += 1

            for src_lbl in src_lbl_dir.iterdir():
                dst_lbl = dst_lbl_dir / src_lbl.name
                if not dst_lbl.exists():
                    shutil.copy2(src_lbl, dst_lbl)

            split_stats["wider"] = {"images": n_copied, "annotations": "linked"}
            print(f"  ✓ Linked {n_copied} images from existing WIDER YOLO dataset")
        else:
            split_stats["wider"] = prepare_wider_yolo(cache_dir, output_dir, split)

        # --- CrowdHuman (train only) ---
        if not args.skip_crowdhuman:
            split_stats["crowdhuman"] = prepare_crowdhuman_yolo(
                cache_dir, output_dir, split, max_images=args.max_crowdhuman
            )

        # --- MAFA (train only) ---
        if not args.skip_mafa:
            split_stats["mafa"] = prepare_mafa_yolo(
                cache_dir, output_dir, split, max_images=args.max_mafa
            )

        # --- Tiny Face Zoom (train only) ---
        if args.tiny_face_zoom and split == "train":
            split_stats["zoom"] = run_tiny_face_zoom(
                output_dir, split, max_images=args.max_zoom
            )

        # Compute combined stats
        all_stats[split] = compute_yolo_stats(output_dir, split)
        all_stats[split]["sources"] = split_stats

    # Write data.yaml
    data_yaml = output_dir / "data.yaml"
    yaml_content = f"""# Multi-Source Face Detection Dataset — YOLO Format
# Auto-generated by SHML Phase 10 Data Preparation
# Date: {time.strftime('%Y-%m-%dT%H:%M:%S')}
# Sources: {', '.join(sources)}

path: {output_dir}
train: images/train
val: images/val

# Classes
nc: 1
names:
  0: face

# Dataset info
download: null  # Pre-prepared multi-source dataset

# Face detection settings
# - Single class (face)
# - High recall priority for PII compliance
# - Val uses WIDER Face only for fair comparison
"""
    with open(data_yaml, "w") as f:
        f.write(yaml_content)
    print(f"\n  ✓ Wrote {data_yaml}")

    # Write dataset info
    info = {
        "dataset": "face_detection_merged_yolo",
        "version": "1.0",
        "phase": "10",
        "sources": sources,
        "stats": {
            k: {kk: vv for kk, vv in v.items() if kk != "sources"}
            for k, v in all_stats.items()
        },
        "source_stats": {k: v.get("sources", {}) for k, v in all_stats.items()},
        "generation_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with open(output_dir / "dataset_info.json", "w") as f:
        json.dump(info, f, indent=2, default=str)

    elapsed = time.time() - start_time

    # Summary
    print(f"\n{'=' * 70}")
    print(f"DATASET SUMMARY")
    print(f"{'=' * 70}")
    for split, stats in all_stats.items():
        print(f"\n  {split.upper()}:")
        print(f"    Images:      {stats.get('total_images', 0):,}")
        print(f"    Annotations: {stats.get('total_annotations', 0):,}")
        print(f"    Faces/image: {stats.get('faces_per_image_mean', 0):.1f} (mean)")
        dist = stats.get("face_size_distribution", {})
        print(
            f"    Size dist:   tiny={dist.get('tiny_lt32', 0):,}, "
            f"small={dist.get('small_32_96', 0):,}, "
            f"medium={dist.get('medium_96_256', 0):,}, "
            f"large={dist.get('large_gt256', 0):,}"
        )
    print(f"\n  Total time: {elapsed/60:.1f} minutes")
    print(f"  Config: {data_yaml}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
