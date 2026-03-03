#!/usr/bin/env python3
"""
Phase 9 — Multi-Dataset Face Detection Data Preparation
=========================================================

Downloads and merges WIDER Face, CrowdHuman, and MAFA into a single
COCO-format dataset for RF-DETR fine-tuning.

Output structure:
    {output_dir}/
        images/
            train/
            val/
        annotations/
            train.json     # COCO format
            val.json       # COCO format

Usage:
    python prepare_face_datasets.py --output /data/face_detection
    python prepare_face_datasets.py --output /data/face_detection --skip-crowdhuman
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WIDER_HF_URLS = {
    "train_images": "https://huggingface.co/datasets/wider_face/resolve/main/data/WIDER_train.zip",
    "val_images": "https://huggingface.co/datasets/wider_face/resolve/main/data/WIDER_val.zip",
    "annotations": "https://huggingface.co/datasets/wider_face/resolve/main/data/wider_face_split.zip",
}

CROWDHUMAN_HF = "CrowdHuman"  # huggingface_hub download
MAFA_URL = "https://huggingface.co/datasets/Kuixiang/MAFA/resolve/main"

CATEGORY = [{"id": 1, "name": "face", "supercategory": "person"}]


# ---------------------------------------------------------------------------
# Download Helpers
# ---------------------------------------------------------------------------


def download_file(url: str, dest: Path, desc: str = "") -> Path:
    """Download a file with progress bar."""
    import urllib.request

    if dest.exists():
        print(f"  ✓ Already downloaded: {dest.name}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  ⬇ Downloading {desc or dest.name}...")
    try:
        urllib.request.urlretrieve(url, str(dest))
        print(f"  ✓ Downloaded: {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)")
    except Exception as e:
        print(f"  ✗ Download failed: {e}")
        raise
    return dest


def extract_zip(zip_path: Path, dest_dir: Path) -> None:
    """Extract a zip file."""
    print(f"  📦 Extracting {zip_path.name}...")
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(dest_dir)
    print(f"  ✓ Extracted to {dest_dir}")


# ---------------------------------------------------------------------------
# WIDER Face
# ---------------------------------------------------------------------------


def parse_wider_annotations(annot_file: Path) -> dict[str, list[list[int]]]:
    """Parse WIDER Face annotation format.

    Returns {filename: [[x, y, w, h], ...]}
    """
    annotations = {}
    with open(annot_file) as f:
        while True:
            filename = f.readline().strip()
            if not filename:
                break
            n_faces = int(f.readline().strip())
            boxes = []
            if n_faces == 0:
                f.readline()  # Skip the "0 0 0 0 0 0 0 0 0 0" line
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


def prepare_wider_face(
    cache_dir: Path,
    output_dir: Path,
    split: str,
    image_id_start: int,
    annot_id_start: int,
) -> tuple[list[dict], list[dict], int, int]:
    """Download, parse, and flatten WIDER Face into COCO format.

    Returns (images, annotations, next_image_id, next_annot_id)
    """
    print(f"\n━━━ WIDER Face ({split}) ━━━")

    # Download
    if split == "train":
        img_zip = download_file(
            WIDER_HF_URLS["train_images"],
            cache_dir / "WIDER_train.zip",
            "WIDER train images",
        )
        ann_zip = download_file(
            WIDER_HF_URLS["annotations"],
            cache_dir / "wider_face_split.zip",
            "WIDER annotations",
        )
    else:
        img_zip = download_file(
            WIDER_HF_URLS["val_images"], cache_dir / "WIDER_val.zip", "WIDER val images"
        )
        ann_zip = download_file(
            WIDER_HF_URLS["annotations"],
            cache_dir / "wider_face_split.zip",
            "WIDER annotations",
        )

    # Extract
    wider_dir = cache_dir / "wider_face"
    if not (wider_dir / f"WIDER_{split}").exists():
        extract_zip(img_zip, cache_dir)
    if not (wider_dir / "wider_face_split").exists():
        extract_zip(ann_zip, cache_dir)

    # Parse annotations
    if split == "train":
        annot_file = wider_dir / "wider_face_split" / "wider_face_train_bbx_gt.txt"
    else:
        annot_file = wider_dir / "wider_face_split" / "wider_face_val_bbx_gt.txt"

    wider_anns = parse_wider_annotations(annot_file)
    print(f"  Parsed {len(wider_anns)} annotated images")

    # Flatten images to output
    images_list = []
    annotations_list = []
    img_id = image_id_start
    ann_id = annot_id_start
    src_dir = cache_dir / f"WIDER_{split}" / "images"
    dst_dir = output_dir / "images" / split

    for filename, boxes in wider_anns.items():
        src_path = src_dir / filename
        if not src_path.exists():
            continue

        # Flatten event/filename.jpg → event_filename.jpg
        flat_name = filename.replace("/", "_")
        dst_path = dst_dir / f"wider_{flat_name}"
        if not dst_path.exists():
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dst_path)

        # Get image dimensions
        try:
            from PIL import Image

            with Image.open(dst_path) as img:
                w_img, h_img = img.size
        except Exception:
            continue

        images_list.append(
            {
                "id": img_id,
                "file_name": dst_path.name,
                "width": w_img,
                "height": h_img,
            }
        )

        for box in boxes:
            x, y, w, h = box
            annotations_list.append(
                {
                    "id": ann_id,
                    "image_id": img_id,
                    "category_id": 1,
                    "bbox": [x, y, w, h],
                    "area": w * h,
                    "iscrowd": 0,
                }
            )
            ann_id += 1

        img_id += 1

    print(f"  ✓ {len(images_list)} images, {len(annotations_list)} face annotations")
    return images_list, annotations_list, img_id, ann_id


# ---------------------------------------------------------------------------
# CrowdHuman
# ---------------------------------------------------------------------------


def prepare_crowdhuman(
    cache_dir: Path,
    output_dir: Path,
    split: str,
    image_id_start: int,
    annot_id_start: int,
) -> tuple[list[dict], list[dict], int, int]:
    """Download and convert CrowdHuman to COCO face annotations.

    CrowdHuman provides 'hbox' (head bbox) and 'fbox' (full body).
    We use 'hbox' as face proxy — head bboxes are tight face approximations.
    """
    print(f"\n━━━ CrowdHuman ({split}) ━━━")

    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("  ⚠ huggingface_hub not installed, skipping CrowdHuman")
        return [], [], image_id_start, annot_id_start

    ch_dir = cache_dir / "crowdhuman"
    ch_dir.mkdir(parents=True, exist_ok=True)

    # Download annotation odgt file
    odgt_name = f"annotation_{split}.odgt"
    try:
        odgt_path = hf_hub_download(
            repo_id="zhiqwang/CrowdHuman",
            filename=odgt_name,
            cache_dir=str(ch_dir),
            repo_type="dataset",
        )
    except Exception as e:
        print(f"  ⚠ CrowdHuman download failed: {e}")
        return [], [], image_id_start, annot_id_start

    # Parse odgt (one JSON object per line)
    images_list = []
    annotations_list = []
    img_id = image_id_start
    ann_id = annot_id_start
    dst_dir = output_dir / "images" / split

    with open(odgt_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            image_id_str = record.get("ID", "")
            gtboxes = record.get("gtboxes", [])

            # Try to download the image
            img_name = f"{image_id_str}.jpg"
            try:
                img_path = hf_hub_download(
                    repo_id="zhiqwang/CrowdHuman",
                    filename=f"Images/{img_name}",
                    cache_dir=str(ch_dir),
                    repo_type="dataset",
                )
            except Exception:
                continue

            dst_path = dst_dir / f"ch_{img_name}"
            if not dst_path.exists():
                dst_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(img_path, dst_path)

            try:
                from PIL import Image

                with Image.open(dst_path) as img:
                    w_img, h_img = img.size
            except Exception:
                continue

            has_faces = False
            for gt in gtboxes:
                tag = gt.get("tag", "")
                if tag != "person":
                    continue
                # Use head bbox as face proxy
                hbox = gt.get("hbox")
                if hbox is None:
                    continue
                x, y, w, h = hbox
                if w <= 0 or h <= 0:
                    continue

                # Clamp to image bounds
                x = max(0, x)
                y = max(0, y)
                w = min(w, w_img - x)
                h = min(h, h_img - y)

                annotations_list.append(
                    {
                        "id": ann_id,
                        "image_id": img_id,
                        "category_id": 1,
                        "bbox": [x, y, w, h],
                        "area": w * h,
                        "iscrowd": 0,
                    }
                )
                ann_id += 1
                has_faces = True

            if has_faces:
                images_list.append(
                    {
                        "id": img_id,
                        "file_name": dst_path.name,
                        "width": w_img,
                        "height": h_img,
                    }
                )
                img_id += 1

    print(f"  ✓ {len(images_list)} images, {len(annotations_list)} head annotations")
    return images_list, annotations_list, img_id, ann_id


# ---------------------------------------------------------------------------
# MAFA (Masked Faces)
# ---------------------------------------------------------------------------


def prepare_mafa(
    cache_dir: Path,
    output_dir: Path,
    split: str,
    image_id_start: int,
    annot_id_start: int,
) -> tuple[list[dict], list[dict], int, int]:
    """Download and convert MAFA masked face dataset.

    MAFA provides occluded/masked face annotations — critical for
    achieving 85%+ hard recall KPI.
    """
    print(f"\n━━━ MAFA Masked Faces ({split}) ━━━")

    mafa_dir = cache_dir / "mafa"
    mafa_dir.mkdir(parents=True, exist_ok=True)

    try:
        from huggingface_hub import hf_hub_download

        # Try to download MAFA from HuggingFace
        annot_path = hf_hub_download(
            repo_id="Kuixiang/MAFA",
            filename=(
                f"MAFA-Label-{'Train' if split == 'train' else 'Test'}/LabelTrainAll.txt"
                if split == "train"
                else f"MAFA-Label-Test/LabelTestAll.txt"
            ),
            cache_dir=str(mafa_dir),
            repo_type="dataset",
        )
    except Exception as e:
        print(f"  ⚠ MAFA download failed: {e}")
        print(f"  ℹ MAFA is optional — training will proceed with WIDER + CrowdHuman")
        return [], [], image_id_start, annot_id_start

    # Parse MAFA annotations — format: filename x y w h occ_type occ_degree
    images_list = []
    annotations_list = []
    img_id = image_id_start
    ann_id = annot_id_start
    dst_dir = output_dir / "images" / split

    current_file = None
    current_boxes = []

    try:
        with open(annot_path) as f:
            for line in f:
                parts = line.strip().split()
                if not parts:
                    continue
                # Detect image line vs bbox line
                if len(parts) == 1 and parts[0].endswith((".jpg", ".png", ".jpeg")):
                    # Save previous image
                    if current_file and current_boxes:
                        images_list.append(current_file)
                        annotations_list.extend(current_boxes)
                    current_file = None
                    current_boxes = []

                    # Try to get image
                    img_name = parts[0]
                    try:
                        img_path = hf_hub_download(
                            repo_id="Kuixiang/MAFA",
                            filename=f"images/{img_name}",
                            cache_dir=str(mafa_dir),
                            repo_type="dataset",
                        )
                        dst_path = dst_dir / f"mafa_{img_name}"
                        if not dst_path.exists():
                            shutil.copy2(img_path, dst_path)
                        from PIL import Image

                        with Image.open(dst_path) as img:
                            w_img, h_img = img.size
                        current_file = {
                            "id": img_id,
                            "file_name": dst_path.name,
                            "width": w_img,
                            "height": h_img,
                        }
                        img_id += 1
                    except Exception:
                        continue
                elif len(parts) >= 4 and current_file:
                    try:
                        x, y, w, h = (
                            float(parts[0]),
                            float(parts[1]),
                            float(parts[2]),
                            float(parts[3]),
                        )
                        if w > 0 and h > 0:
                            current_boxes.append(
                                {
                                    "id": ann_id,
                                    "image_id": current_file["id"],
                                    "category_id": 1,
                                    "bbox": [x, y, w, h],
                                    "area": w * h,
                                    "iscrowd": 0,
                                }
                            )
                            ann_id += 1
                    except ValueError:
                        continue

        # Don't forget last image
        if current_file and current_boxes:
            images_list.append(current_file)
            annotations_list.extend(current_boxes)
    except Exception as e:
        print(f"  ⚠ MAFA parsing error: {e}")

    print(
        f"  ✓ {len(images_list)} images, {len(annotations_list)} masked face annotations"
    )
    return images_list, annotations_list, img_id, ann_id


# ---------------------------------------------------------------------------
# Merge & Write
# ---------------------------------------------------------------------------


def write_coco_json(
    images: list[dict],
    annotations: list[dict],
    output_path: Path,
) -> None:
    """Write a COCO-format annotation file."""
    coco = {
        "images": images,
        "annotations": annotations,
        "categories": CATEGORY,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(coco, f)
    print(
        f"  ✓ Wrote {output_path} ({len(images)} images, {len(annotations)} annotations)"
    )


def compute_dataset_stats(
    images: list[dict],
    annotations: list[dict],
) -> dict[str, Any]:
    """Compute dataset quality statistics for feature store."""
    if not annotations:
        return {}

    areas = [a["area"] for a in annotations]
    sizes = []
    for a in annotations:
        w, h = a["bbox"][2], a["bbox"][3]
        sizes.append(max(w, h))

    size_buckets = {
        "tiny_lt32": sum(1 for s in sizes if s < 32),
        "small_32_96": sum(1 for s in sizes if 32 <= s < 96),
        "medium_96_256": sum(1 for s in sizes if 96 <= s < 256),
        "large_gt256": sum(1 for s in sizes if s >= 256),
    }

    faces_per_image = {}
    for a in annotations:
        faces_per_image[a["image_id"]] = faces_per_image.get(a["image_id"], 0) + 1

    return {
        "total_images": len(images),
        "total_annotations": len(annotations),
        "faces_per_image_mean": np.mean(list(faces_per_image.values())),
        "faces_per_image_median": np.median(list(faces_per_image.values())),
        "face_size_distribution": size_buckets,
        "min_area": min(areas),
        "max_area": max(areas),
        "mean_area": np.mean(areas),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Prepare merged face detection dataset"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="/data/face_detection",
        help="Output directory for merged dataset",
    )
    parser.add_argument(
        "--cache",
        type=str,
        default="/tmp/face_data_cache",
        help="Cache directory for downloads",
    )
    parser.add_argument(
        "--skip-crowdhuman", action="store_true", help="Skip CrowdHuman dataset"
    )
    parser.add_argument(
        "--skip-mafa", action="store_true", help="Skip MAFA masked faces dataset"
    )
    args = parser.parse_args()

    output_dir = Path(args.output)
    cache_dir = Path(args.cache)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("PHASE 9: Face Detection Dataset Preparation")
    print("=" * 70)
    print(f"  Output: {output_dir}")
    print(f"  Cache:  {cache_dir}")
    print(
        f"  Datasets: WIDER Face"
        + (" + CrowdHuman" if not args.skip_crowdhuman else "")
        + (" + MAFA" if not args.skip_mafa else "")
    )
    print()

    all_stats = {}

    for split in ["train", "val"]:
        print(f"\n{'='*50}")
        print(f"  Split: {split.upper()}")
        print(f"{'='*50}")

        all_images = []
        all_annotations = []
        img_id = 1
        ann_id = 1

        # WIDER Face (always included)
        w_imgs, w_anns, img_id, ann_id = prepare_wider_face(
            cache_dir, output_dir, split, img_id, ann_id
        )
        all_images.extend(w_imgs)
        all_annotations.extend(w_anns)

        # CrowdHuman
        if not args.skip_crowdhuman:
            ch_imgs, ch_anns, img_id, ann_id = prepare_crowdhuman(
                cache_dir, output_dir, split, img_id, ann_id
            )
            all_images.extend(ch_imgs)
            all_annotations.extend(ch_anns)

        # MAFA
        if not args.skip_mafa:
            m_imgs, m_anns, img_id, ann_id = prepare_mafa(
                cache_dir, output_dir, split, img_id, ann_id
            )
            all_images.extend(m_imgs)
            all_annotations.extend(m_anns)

        # Write merged COCO JSON
        write_coco_json(
            all_images, all_annotations, output_dir / "annotations" / f"{split}.json"
        )

        stats = compute_dataset_stats(all_images, all_annotations)
        all_stats[split] = stats

    # Write dataset info
    info = {
        "dataset": "face_detection_merged",
        "version": "1.0",
        "sources": ["WIDER_Face"],
        "categories": CATEGORY,
        "stats": all_stats,
    }
    if not args.skip_crowdhuman:
        info["sources"].append("CrowdHuman")
    if not args.skip_mafa:
        info["sources"].append("MAFA")

    with open(output_dir / "dataset_info.json", "w") as f:
        json.dump(info, f, indent=2, default=str)

    # Summary
    print("\n" + "=" * 70)
    print("DATASET SUMMARY")
    print("=" * 70)
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
    print("=" * 70)


if __name__ == "__main__":
    main()
