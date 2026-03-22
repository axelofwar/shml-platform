#!/usr/bin/env python3
"""Catalogue SHML training datasets in FiftyOne with canonical metadata.

Run once after a training dataset is prepared, or to resync names/tags:

    python3 scripts/registry/init_fiftyone_datasets.py

Registers:
  - wider-face-train    WIDER Face training split
  - wider-face-val      WIDER Face validation split
  - face-merged         Merged multi-source face detection dataset

Persistent datasets survive FiftyOne App restarts and can be queried by
training jobs via:
    import fiftyone as fo
    ds = fo.load_dataset("wider-face-train")
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

FIFTYONE_DB_URI = os.environ.get(
    "FIFTYONE_DATABASE_URI", "mongodb://fiftyone-mongo:27017"
)
SHML_DATA_DIR = Path(os.environ.get("SHML_DATA_DIR", "/opt/shml/data"))

# Canonical dataset definitions. Add new datasets here.
DATASET_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "wider-face-train",
        "description": (
            "WIDER Face training split — 12,880 images, 159,424 face annotations. "
            "Used for all SHML face detection model training. "
            "Source: http://shuoyang1213.me/WIDERFACE/"
        ),
        "tags": ["wider-face", "face-detection", "training", "shml"],
        "source_url": "http://shuoyang1213.me/WIDERFACE/",
        "data_path": SHML_DATA_DIR / "wider_face" / "train",
        "label_type": "detections",
        "annotation_format": "wider-face",
    },
    {
        "name": "wider-face-val",
        "description": (
            "WIDER Face validation split — 3,226 images with ground truth bounding boxes. "
            "Primary offline benchmark for model evaluation."
        ),
        "tags": ["wider-face", "face-detection", "validation", "shml"],
        "source_url": "http://shuoyang1213.me/WIDERFACE/",
        "data_path": SHML_DATA_DIR / "wider_face" / "val",
        "label_type": "detections",
        "annotation_format": "wider-face",
    },
    {
        "name": "face-merged",
        "description": (
            "Merged multi-source face detection dataset: WIDER Face + YOLO converted "
            "RF-DETR COCO format. Used for late-phase multi-architecture training."
        ),
        "tags": ["merged", "face-detection", "coco", "rfdetr", "shml"],
        "source_url": None,
        "data_path": SHML_DATA_DIR / "face_merged",
        "label_type": "detections",
        "annotation_format": "coco",
    },
]


def _ensure_or_update_dataset(spec: dict[str, Any]) -> None:
    import fiftyone as fo

    name = spec["name"]
    data_path = spec["data_path"]

    if not data_path.exists():
        print(f"  ⚠  {name}: data path not found: {data_path} — creating placeholder record only")

    existing = fo.dataset_exists(name)

    if existing:
        ds = fo.load_dataset(name)
        ds.description = spec["description"]
        ds.tags = spec["tags"]
        ds.save()
        print(f"  ✓ Updated metadata: {name}  ({len(ds)} samples)")
    else:
        ds = fo.Dataset(name=name, persistent=True, overwrite=False)
        ds.description = spec["description"]
        ds.tags = spec["tags"]
        ds.info.update(
            {
                "source_url": spec.get("source_url") or "",
                "data_path": str(data_path),
                "annotation_format": spec.get("annotation_format", ""),
                "owner": "axelofwar.web3@gmail.com",
                "project": "shml-platform",
            }
        )
        ds.save()
        print(f"  ✓ Registered (empty placeholder): {name}")
        print(
            f"     Populate with: fo.Dataset.from_dir("
            f"dataset_dir={str(data_path)!r}, ..., name={name!r})"
        )


def main() -> int:
    try:
        import fiftyone as fo
    except ImportError:
        print(
            "fiftyone not installed. Install with:\n"
            "  pip install fiftyone\n"
            "or run within the fiftyone container.",
            file=sys.stderr,
        )
        return 1

    if FIFTYONE_DB_URI != "mongodb://fiftyone-mongo:27017":
        fo.config.database_uri = FIFTYONE_DB_URI

    print(f"FiftyOne DB: {fo.config.database_uri}")
    print(f"Data dir:    {SHML_DATA_DIR}")
    print()

    errors = 0
    for spec in DATASET_DEFINITIONS:
        try:
            _ensure_or_update_dataset(spec)
        except Exception as exc:
            print(f"  ✗ {spec['name']} failed: {exc}", file=sys.stderr)
            errors += 1

    print()
    print(
        f"Done. {len(DATASET_DEFINITIONS) - errors}/{len(DATASET_DEFINITIONS)} datasets registered."
    )
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
