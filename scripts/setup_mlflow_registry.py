#!/usr/bin/env python3
"""
MLflow Model Registry Setup Script

Configures the model registry for face detection models with:
- Staging and Production stages
- Model versioning and comparison
- Automated promotion workflows
- Model cards with metadata

Usage:
    python setup_mlflow_registry.py
"""

import os
import sys
from datetime import datetime
from typing import Optional, Dict, Any

# MLflow imports
import mlflow
from mlflow.tracking import MlflowClient
from mlflow.entities.model_registry import ModelVersion

# Configuration
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow-nginx:80")
MODEL_NAME = os.getenv("MLFLOW_REGISTRY_MODEL_NAME", "face-detection-yolov8l-p2")


def setup_registry():
    """Configure MLflow model registry for face detection models."""

    print("=" * 60)
    print("MLflow Model Registry Setup")
    print("=" * 60)

    # Connect to MLflow
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    client = MlflowClient()

    print(f"Connected to MLflow: {MLFLOW_TRACKING_URI}")

    # List experiments
    experiments = client.search_experiments()
    print(f"\nExperiments found: {len(experiments)}")
    for exp in experiments:
        print(f"  - {exp.name} (ID: {exp.experiment_id})")

    # Check if model exists, create if not
    try:
        model = client.get_registered_model(MODEL_NAME)
        print(f"\nModel '{MODEL_NAME}' already exists")
    except mlflow.exceptions.MlflowException:
        print(f"\nCreating model '{MODEL_NAME}'...")
        model = client.create_registered_model(
            name=MODEL_NAME,
            description="""
Face Detection Model (YOLOv8 Architecture)

**Purpose:** High-accuracy face detection for privacy protection (PII redaction)

**Training Strategy:**
- Phase 1: Foundation (WIDER Face, 200 epochs)
- Phase 2: Production data fine-tuning
- Phase 3: YFCC100M augmentation

**Performance Targets:**
- mAP50: ≥90%
- Recall: ≥95%
- Precision: ≥90%

**Model Card:**
- Architecture: YOLOv8L (Large)
- Input: 1280x1280 RGB
- Output: Bounding boxes + confidence scores
- License: GPL-3.0 (Ultralytics)
            """.strip(),
            tags={
                "task": "face_detection",
                "architecture": "yolov8",
                "framework": "ultralytics",
                "use_case": "pii_protection",
            },
        )
        print(f"Created model '{MODEL_NAME}'")

    # Update model tags if it already exists
    client.set_registered_model_tag(
        MODEL_NAME, "updated_at", datetime.now().isoformat()
    )
    client.set_registered_model_tag(MODEL_NAME, "owner", "ml-platform")
    client.set_registered_model_tag(MODEL_NAME, "domain", "computer_vision")

    # List model versions
    versions = client.search_model_versions(f"name='{MODEL_NAME}'")
    print(f"\nModel versions: {len(list(versions))}")

    return model


def register_model_from_run(
    run_id: str,
    model_path: str = "model",
    alias: str = "challenger",
    description: Optional[str] = None,
) -> ModelVersion:
    """
    Register a model from an MLflow run.

    Args:
        run_id: MLflow run ID containing the model
        model_path: Path to model artifacts within run
        alias: Target alias ('challenger', 'champion')
        description: Version description

    Returns:
        Registered ModelVersion
    """
    client = MlflowClient()

    # Build model URI
    model_uri = f"runs:/{run_id}/{model_path}"

    # Register model
    print(f"Registering model from run {run_id}...")
    mv = mlflow.register_model(model_uri, MODEL_NAME)

    # Set version description
    if description:
        client.update_model_version(
            name=MODEL_NAME,
            version=mv.version,
            description=description,
        )

    # Assign alias
    if alias:
        client.set_registered_model_alias(
            name=MODEL_NAME,
            alias=alias,
            version=mv.version,
        )
        print(f"Assigned alias @{alias} to v{mv.version}")

    return mv


def compare_model_versions(
    version_a: int,
    version_b: int,
    metrics: list = ["mAP50", "recall", "precision"],
) -> Dict[str, Any]:
    """
    Compare two model versions by their metrics.

    Returns dict with comparison results.
    """
    client = MlflowClient()

    # Get versions
    va = client.get_model_version(MODEL_NAME, version_a)
    vb = client.get_model_version(MODEL_NAME, version_b)

    # Get runs
    run_a = client.get_run(va.run_id)
    run_b = client.get_run(vb.run_id)

    # Compare metrics
    comparison = {
        "version_a": version_a,
        "version_b": version_b,
        "metrics": {},
        "winner": None,
    }

    for metric in metrics:
        val_a = run_a.data.metrics.get(metric, 0)
        val_b = run_b.data.metrics.get(metric, 0)
        comparison["metrics"][metric] = {
            "version_a": val_a,
            "version_b": val_b,
            "diff": val_b - val_a,
            "better": "b" if val_b > val_a else "a" if val_a > val_b else "tie",
        }

    # Determine overall winner (by mAP50)
    if "mAP50" in comparison["metrics"]:
        comparison["winner"] = comparison["metrics"]["mAP50"]["better"]

    return comparison


def promote_to_production(version: int, archive_previous: bool = True):
    """
    Promote a model version to Production using @champion alias.

    Optionally demotes the previous champion to @challenger.
    """
    client = MlflowClient()

    # Demote current champion to challenger
    if archive_previous:
        try:
            current_champion = client.get_model_version_by_alias(MODEL_NAME, "champion")
            if int(current_champion.version) != version:
                print(
                    f"Demoting previous champion v{current_champion.version} to @challenger"
                )
                client.set_registered_model_alias(
                    name=MODEL_NAME,
                    alias="challenger",
                    version=current_champion.version,
                )
        except Exception:
            pass  # No current champion

    # Promote new version
    print(f"Promoting version {version} to @champion...")
    client.set_registered_model_alias(
        name=MODEL_NAME,
        alias="champion",
        version=version,
    )
    print(f"Version {version} is now @champion")


def get_production_model_uri() -> Optional[str]:
    """Get URI of current champion model."""
    client = MlflowClient()

    try:
        mv = client.get_model_version_by_alias(MODEL_NAME, "champion")
        return f"models:/{MODEL_NAME}@champion"
    except Exception:
        return None


def list_model_versions():
    """List all versions of the face detection model."""
    client = MlflowClient()

    print(f"\nModel Versions: {MODEL_NAME}")
    print("-" * 60)

    versions = list(client.search_model_versions(f"name='{MODEL_NAME}'"))

    if not versions:
        print("No versions registered yet.")
        print("\nTo register a model version after training:")
        print(f"  python setup_mlflow_registry.py --register <run_id>")
        return

    # Resolve current aliases
    alias_map: Dict[str, str] = {}
    for alias in ("champion", "challenger"):
        try:
            mv = client.get_model_version_by_alias(MODEL_NAME, alias)
            alias_map[mv.version] = alias
        except Exception:
            pass

    for v in versions:
        # Get run metrics
        try:
            run = client.get_run(v.run_id)
            mAP50 = run.data.metrics.get("mAP50", "N/A")
            recall = run.data.metrics.get("recall", "N/A")
            precision = run.data.metrics.get("precision", "N/A")
        except Exception:
            mAP50 = recall = precision = "N/A"

        alias_label = f" @{alias_map[v.version]}" if v.version in alias_map else ""
        print(f"Version {v.version}{alias_label}:")
        print(f"  Status: {v.status}")
        print(f"  Run ID: {v.run_id[:8]}...")
        print(f"  Metrics: mAP50={mAP50}, recall={recall}, precision={precision}")
        print(f"  Created: {v.creation_timestamp}")
        print()


def migrate_stages_to_aliases():
    """Migrate existing stage assignments to alias-based model management.

    Reads all model versions and creates matching aliases:
    - Production → @champion
    - Staging    → @challenger

    This is a one-time migration for moving from the deprecated
    ``transition_model_version_stage()`` API to ``set_registered_model_alias()``.
    """
    client = MlflowClient()

    versions = list(client.search_model_versions(f"name='{MODEL_NAME}'"))
    if not versions:
        print("No model versions found — nothing to migrate.")
        return

    migrated = 0
    for v in versions:
        stage = getattr(v, "current_stage", None)
        if stage == "Production":
            client.set_registered_model_alias(MODEL_NAME, "champion", v.version)
            print(f"  v{v.version}: Production → @champion")
            migrated += 1
        elif stage == "Staging":
            client.set_registered_model_alias(MODEL_NAME, "challenger", v.version)
            print(f"  v{v.version}: Staging → @challenger")
            migrated += 1
        else:
            print(f"  v{v.version}: {stage or 'None'} — skipped")

    print(f"\nMigrated {migrated} version(s) to aliases.")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="MLflow Model Registry Setup")
    parser.add_argument(
        "--register", metavar="RUN_ID", help="Register model from run ID"
    )
    parser.add_argument(
        "--alias",
        default="challenger",
        help="Target alias for registration (default: challenger)",
    )
    parser.add_argument(
        "--promote", type=int, metavar="VERSION", help="Promote version to @champion"
    )
    parser.add_argument(
        "--compare",
        nargs=2,
        type=int,
        metavar=("V1", "V2"),
        help="Compare two versions",
    )
    parser.add_argument("--list", action="store_true", help="List all model versions")
    parser.add_argument(
        "--migrate-stages",
        action="store_true",
        help="One-time migration: convert stage assignments to aliases",
    )

    args = parser.parse_args()

    # Always setup registry first
    setup_registry()

    if args.migrate_stages:
        migrate_stages_to_aliases()

    if args.register:
        register_model_from_run(args.register, alias=args.alias)

    if args.promote:
        promote_to_production(args.promote)

    if args.compare:
        result = compare_model_versions(args.compare[0], args.compare[1])
        print(f"\nComparison: v{result['version_a']} vs v{result['version_b']}")
        for metric, data in result["metrics"].items():
            print(
                f"  {metric}: {data['version_a']:.4f} vs {data['version_b']:.4f} ({data['diff']:+.4f})"
            )
        print(
            f"Winner: Version {result['winner'].upper() if result['winner'] else 'Tie'}"
        )

    if args.list or not any(
        [args.register, args.promote, args.compare, args.migrate_stages]
    ):
        list_model_versions()

    print("\n✓ MLflow Registry setup complete")


if __name__ == "__main__":
    main()
