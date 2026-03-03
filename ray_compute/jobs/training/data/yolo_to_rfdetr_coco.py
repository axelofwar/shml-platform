#!/usr/bin/env python3
"""
YOLO → RF-DETR COCO Format Converter
=====================================

Converts Phase 8 WIDER Face YOLO-format dataset into the Roboflow-style
COCO layout that RF-DETR expects:

    Input (YOLO):
        wider_face_yolo/
        ├── data.yaml
        ├── images/{train,val}/*.jpg
        └── labels/{train,val}/*.txt      (class_id cx cy w h, normalized)

    Output (RF-DETR / Roboflow COCO):
        wider_face_rfdetr/
        ├── train/
        │   ├── *.jpg  (symlinks to originals)
        │   └── _annotations.coco.json
        └── val/
            ├── *.jpg  (symlinks to originals)
            └── _annotations.coco.json

Images are **symlinked** to avoid copying ~2.5GB of data.
Annotations are converted from YOLO normalized (cx, cy, w, h) to
COCO absolute (x, y, width, height).

Usage:
    python yolo_to_rfdetr_coco.py [--yolo-dir DIR] [--output-dir DIR]
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from PIL import Image


def parse_yolo_label(label_path: str) -> list[tuple[int, float, float, float, float]]:
    """Parse a YOLO label file → list of (class_id, cx, cy, w, h) normalized."""
    annotations = []
    with open(label_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 5:
                continue
            class_id = int(parts[0])
            cx, cy, w, h = (
                float(parts[1]),
                float(parts[2]),
                float(parts[3]),
                float(parts[4]),
            )
            annotations.append((class_id, cx, cy, w, h))
    return annotations


def yolo_to_coco_bbox(
    cx: float, cy: float, w: float, h: float, img_w: int, img_h: int
) -> list[float]:
    """Convert YOLO normalized (cx, cy, w, h) to COCO absolute [x, y, width, height]."""
    abs_w = w * img_w
    abs_h = h * img_h
    abs_x = (cx * img_w) - (abs_w / 2)
    abs_y = (cy * img_h) - (abs_h / 2)
    # Clamp to image boundaries
    abs_x = max(0, abs_x)
    abs_y = max(0, abs_y)
    abs_w = min(abs_w, img_w - abs_x)
    abs_h = min(abs_h, img_h - abs_y)
    return [round(abs_x, 2), round(abs_y, 2), round(abs_w, 2), round(abs_h, 2)]


def get_image_size(img_path: str) -> tuple[int, int]:
    """Get (width, height) without full decode."""
    with Image.open(img_path) as im:
        return im.size  # (width, height)


def convert_split(
    yolo_dir: Path,
    output_dir: Path,
    split: str,
    class_names: list[str],
) -> dict:
    """Convert one split (train or val) from YOLO to Roboflow COCO format."""
    images_dir = yolo_dir / "images" / split
    labels_dir = yolo_dir / "labels" / split
    out_split_dir = output_dir / split

    out_split_dir.mkdir(parents=True, exist_ok=True)

    # Build category list (RF-DETR expects 1-indexed categories)
    categories = [
        {"id": i + 1, "name": name, "supercategory": "none"}
        for i, name in enumerate(class_names)
    ]

    images_list = []
    annotations_list = []
    annotation_id = 1
    skipped = 0

    image_files = sorted(
        [
            f
            for f in os.listdir(images_dir)
            if f.lower().endswith((".jpg", ".jpeg", ".png"))
        ]
    )

    print(f"  [{split}] Processing {len(image_files)} images...")

    for img_idx, img_filename in enumerate(image_files):
        img_path = images_dir / img_filename
        label_filename = Path(img_filename).stem + ".txt"
        label_path = labels_dir / label_filename

        # Get image dimensions
        try:
            img_w, img_h = get_image_size(str(img_path))
        except Exception as e:
            print(f"  Warning: Cannot read {img_filename}: {e}")
            skipped += 1
            continue

        image_id = img_idx + 1

        images_list.append(
            {
                "id": image_id,
                "file_name": img_filename,
                "width": img_w,
                "height": img_h,
            }
        )

        # Create symlink in output directory
        symlink_path = out_split_dir / img_filename
        if not symlink_path.exists():
            os.symlink(str(img_path), str(symlink_path))

        # Parse YOLO annotations
        if label_path.exists():
            yolo_annots = parse_yolo_label(str(label_path))
            for class_id, cx, cy, w, h in yolo_annots:
                bbox = yolo_to_coco_bbox(cx, cy, w, h, img_w, img_h)
                area = bbox[2] * bbox[3]
                if area < 1.0:
                    continue  # Skip degenerate boxes

                annotations_list.append(
                    {
                        "id": annotation_id,
                        "image_id": image_id,
                        "category_id": class_id + 1,  # YOLO 0-indexed → COCO 1-indexed
                        "bbox": bbox,
                        "area": round(area, 2),
                        "iscrowd": 0,
                    }
                )
                annotation_id += 1

        if (img_idx + 1) % 2000 == 0:
            print(f"    Processed {img_idx + 1}/{len(image_files)}...")

    # Write COCO JSON
    coco_json = {
        "images": images_list,
        "annotations": annotations_list,
        "categories": categories,
    }

    annotation_path = out_split_dir / "_annotations.coco.json"
    with open(annotation_path, "w") as f:
        json.dump(coco_json, f)

    stats = {
        "split": split,
        "images": len(images_list),
        "annotations": len(annotations_list),
        "skipped": skipped,
        "avg_annotations_per_image": round(
            len(annotations_list) / max(len(images_list), 1), 2
        ),
    }
    print(
        f"  [{split}] Done: {stats['images']} images, {stats['annotations']} annotations "
        f"({stats['avg_annotations_per_image']} avg/img), {skipped} skipped"
    )
    return stats


def load_class_names(yolo_dir: Path) -> list[str]:
    """Load class names from data.yaml."""
    import yaml

    data_yaml = yolo_dir / "data.yaml"
    with open(data_yaml, "r") as f:
        data = yaml.safe_load(f)

    names = data.get("names", {})
    if isinstance(names, dict):
        return [names[k] for k in sorted(names.keys())]
    elif isinstance(names, list):
        return names
    else:
        raise ValueError(f"Unexpected 'names' format in data.yaml: {type(names)}")


def main():
    parser = argparse.ArgumentParser(
        description="Convert YOLO dataset to RF-DETR COCO format"
    )
    parser.add_argument(
        "--yolo-dir",
        default="/tmp/ray/data/wider_face_yolo",
        help="Path to YOLO dataset directory (default: /tmp/ray/data/wider_face_yolo)",
    )
    parser.add_argument(
        "--output-dir",
        default="/tmp/ray/data/wider_face_rfdetr",
        help="Output directory for RF-DETR COCO format (default: /tmp/ray/data/wider_face_rfdetr)",
    )
    args = parser.parse_args()

    yolo_dir = Path(args.yolo_dir)
    output_dir = Path(args.output_dir)

    print("=" * 70)
    print("YOLO → RF-DETR COCO Format Converter")
    print("=" * 70)
    print(f"  YOLO dir:   {yolo_dir}")
    print(f"  Output dir: {output_dir}")

    # Validate input
    if not yolo_dir.exists():
        print(f"ERROR: YOLO directory not found: {yolo_dir}")
        sys.exit(1)

    for subdir in ["images/train", "images/val", "labels/train", "labels/val"]:
        if not (yolo_dir / subdir).exists():
            print(f"ERROR: Missing required subdirectory: {yolo_dir / subdir}")
            sys.exit(1)

    # Load class names
    class_names = load_class_names(yolo_dir)
    print(f"  Classes:    {class_names}")
    print()

    output_dir.mkdir(parents=True, exist_ok=True)

    start = time.time()
    all_stats = {}

    for split in ["train", "val"]:
        stats = convert_split(yolo_dir, output_dir, split, class_names)
        all_stats[split] = stats

    # RF-DETR expects 'valid/' not 'val/' — create symlink
    valid_link = output_dir / "valid"
    if not valid_link.exists():
        valid_link.symlink_to("val")
        print("  Created symlink: valid → val (RF-DETR compatibility)")

    # RF-DETR also expects 'test/' — point to val
    test_link = output_dir / "test"
    if not test_link.exists():
        test_link.symlink_to("val")
        print("  Created symlink: test → val (RF-DETR compatibility)")

    elapsed = time.time() - start

    # Write conversion metadata
    meta = {
        "source": str(yolo_dir),
        "output": str(output_dir),
        "format": "roboflow_coco",
        "class_names": class_names,
        "splits": all_stats,
        "conversion_time_sec": round(elapsed, 2),
    }
    with open(output_dir / "conversion_meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    print()
    print(f"Conversion complete in {elapsed:.1f}s")
    print(f"Output: {output_dir}")
    print(
        f"  train/ — {all_stats['train']['images']} images, {all_stats['train']['annotations']} annotations"
    )
    print(
        f"  val/   — {all_stats['val']['images']} images, {all_stats['val']['annotations']} annotations"
    )
    print()
    print("Ready for RF-DETR training:")
    print(f"  model.train(dataset_dir='{output_dir}', ...)")


if __name__ == "__main__":
    main()
