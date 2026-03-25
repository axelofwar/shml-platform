#!/usr/bin/env python3
"""Register pre-trained base model weights into the MLflow Model Registry.

Run once after initial setup or after downloading new base weights:

    python3 scripts/registry/register_base_models.py

Expects:
  - MLFLOW_TRACKING_URI in environment (default: http://localhost:8080)
  - SHML_MODELS_DIR in environment (default: /opt/shml/models)
  - Base weights present in $SHML_MODELS_DIR/yolo/ (or libs/training/jobs/ fallback)

Registers:
  - base-yolo11m     (yolo11m.pt)
  - base-yolo26n     (yolo26n.pt)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import mlflow
from mlflow.tracking import MlflowClient

MLFLOW_TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:8080")

# Canonical host model store; fallback to submodule location for dev
MODELS_DIR = Path(os.environ.get("SHML_MODELS_DIR", "/opt/shml/models"))
REPO_ROOT = Path(__file__).resolve().parents[2]
TRAINING_JOBS_DIR = REPO_ROOT / "libs" / "training" / "jobs"

BASE_MODELS: list[dict[str, Any]] = [
    {
        "registry_name": os.environ.get("MLFLOW_BASE_MODEL_YOLO11M", "base-yolo11m"),
        "filename": "yolo11m.pt",
        "description": "YOLOv11-M base weights (pre-trained on COCO). "
                       "Starting point for face detection fine-tuning.",
        "tags": {
            "architecture": "yolo11",
            "size": "medium",
            "pretrained_on": "coco",
            "task": "object-detection",
            "source": "ultralytics",
        },
        "search_dirs": [
            MODELS_DIR / "yolo",
            TRAINING_JOBS_DIR,
        ],
    },
    {
        "registry_name": os.environ.get("MLFLOW_BASE_MODEL_YOLO26N", "base-yolo26n"),
        "filename": "yolo26n.pt",
        "description": "YOLO26-N nano base weights. Lightweight backbone for "
                       "autoresearch candidate evaluation.",
        "tags": {
            "architecture": "yolo26",
            "size": "nano",
            "pretrained_on": "coco",
            "task": "object-detection",
            "source": "ultralytics",
        },
        "search_dirs": [
            MODELS_DIR / "yolo",
            TRAINING_JOBS_DIR,
        ],
    },
]


def _find_weight_file(filename: str, search_dirs: list[Path]) -> Path | None:
    for d in search_dirs:
        candidate = d / filename
        if candidate.is_file():
            return candidate
    return None


def ensure_model_dir(subdir: str) -> Path:
    target = MODELS_DIR / subdir
    target.mkdir(parents=True, exist_ok=True)
    return target


def register_base_model(client: MlflowClient, spec: dict[str, Any]) -> None:
    name = spec["registry_name"]
    filename = spec["filename"]
    weight_path = _find_weight_file(filename, spec["search_dirs"])

    if weight_path is None:
        print(
            f"  ⚠  {name}: weight file '{filename}' not found in any search dir — skipping."
        )
        print(f"     Searched: {[str(d) for d in spec['search_dirs']]}")
        return

    print(f"  → {name}: found at {weight_path}")

    # Copy to canonical store if not already there
    canonical = MODELS_DIR / "yolo" / filename
    if not canonical.exists():
        canonical.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(weight_path, canonical)
        print(f"     Copied to canonical store: {canonical}")

    # Create or ensure registry model exists with description
    try:
        client.create_registered_model(
            name=name,
            description=spec["description"],
            tags=spec["tags"],
        )
        print(f"     Created registry entry: {name}")
    except mlflow.exceptions.MlflowException as exc:
        if "already exists" in str(exc).lower() or "RESOURCE_ALREADY_EXISTS" in str(exc):
            client.update_registered_model(name=name, description=spec["description"])
            for k, v in spec["tags"].items():
                client.set_registered_model_tag(name, k, v)
            print(f"     Updated existing registry entry: {name}")
        else:
            raise

    # Log artifact in a dedicated run and register the version
    with mlflow.start_run(run_name=f"register-{name}", tags={"type": "base-model-registration"}):
        mlflow.log_artifact(str(canonical), artifact_path="weights")
        run_id = mlflow.active_run().info.run_id  # type: ignore[union-attr]

    model_uri = f"runs:/{run_id}/weights/{filename}"
    mv = client.create_model_version(
        name=name,
        source=model_uri,
        description=f"Base weights from {weight_path.name}",
        tags={"weight_file": filename},
    )
    client.transition_model_version_stage(
        name=name, version=mv.version, stage="Staging"
    )
    print(f"     Registered version {mv.version} → Staging  (run_id={run_id[:8]})")


def main() -> int:
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment("base-model-registry")
    client = MlflowClient()

    print(f"MLflow URI: {MLFLOW_TRACKING_URI}")
    print(f"Models dir: {MODELS_DIR}")
    print()

    errors = 0
    for spec in BASE_MODELS:
        try:
            register_base_model(client, spec)
        except Exception as exc:
            print(f"  ✗ {spec['registry_name']} failed: {exc}", file=sys.stderr)
            errors += 1

    print()
    print(f"Done. {len(BASE_MODELS) - errors}/{len(BASE_MODELS)} models registered.")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
