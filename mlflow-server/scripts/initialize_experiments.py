#!/usr/bin/env python3
"""
Initialize MLflow Experiments and Schema for PII-PRO
Creates standard experiment structure optimized for privacy-focused computer vision
"""

import mlflow
from mlflow.tracking import MlflowClient
import os
import sys

# MLflow server connection
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")

# Experiment definitions for PII-PRO
EXPERIMENTS = {
    "development": {
        "name": "Development-Training",
        "description": "Development environment for model training and experimentation (Face/License Plate Detection, DMCA Audio, AI Music)",
        "tags": {
            "environment": "dev",
            "purpose": "training",
            "project": "pii-pro",
        },
    },
    "staging": {
        "name": "Staging-Model-Comparison",
        "description": "Model comparison against baselines (YOLO/MCTNN/ResNet) and version-to-version A/B testing",
        "tags": {
            "environment": "staging",
            "purpose": "comparison",
            "project": "pii-pro",
        },
    },
    "benchmarking": {
        "name": "Performance-Benchmarking",
        "description": "FPS benchmarking across resolutions, resource profiling, and privacy validation",
        "tags": {
            "environment": "benchmarking",
            "purpose": "performance",
            "project": "pii-pro",
        },
    },
    "production": {
        "name": "Production-Candidates",
        "description": "Production-ready models validated for privacy, performance, and accuracy",
        "tags": {
            "environment": "production",
            "purpose": "deployment",
            "project": "pii-pro",
        },
    },
    "datasets": {
        "name": "Dataset-Registry",
        "description": "Dataset versioning and tracking (train/val/test splits, labels, preprocessing)",
        "tags": {
            "environment": "data",
            "purpose": "dataset-management",
            "project": "pii-pro",
        },
    },
}


def initialize_experiments():
    """Create experiments with proper tags and descriptions"""

    print(f"🔗 Connecting to MLflow: {MLFLOW_TRACKING_URI}")
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    client = MlflowClient()

    print("\n📊 Initializing Experiment Structure...")
    print("=" * 60)

    created = []
    existing = []

    for exp_key, exp_config in EXPERIMENTS.items():
        exp_name = exp_config["name"]

        try:
            # Check if experiment exists
            experiment = client.get_experiment_by_name(exp_name)

            if experiment:
                exp_id = experiment.experiment_id
                existing.append(exp_name)
                print(f"✓ Existing: {exp_name} (ID: {exp_id})")

                # Update tags if needed
                for tag_key, tag_value in exp_config["tags"].items():
                    client.set_experiment_tag(exp_id, tag_key, tag_value)

            else:
                # Create new experiment
                exp_id = client.create_experiment(
                    name=exp_name, tags=exp_config["tags"]
                )
                created.append(exp_name)
                print(f"✨ Created: {exp_name} (ID: {exp_id})")

        except Exception as e:
            print(f"❌ Error with {exp_name}: {e}")
            continue

    print("\n" + "=" * 60)
    print(f"✅ Initialization Complete!")
    print(f"   Created: {len(created)} experiments")
    print(f"   Existing: {len(existing)} experiments")
    print("=" * 60)

    # Print usage examples
    print("\n📝 PII-PRO Usage Examples:")
    print("-" * 60)
    print("Face Detection Training:")
    print(f'  mlflow.set_experiment("Development-Training")')
    print(f'  with mlflow.start_run(run_name="yolov8-face-detection"):')
    print(f'      mlflow.set_tag("model_type", "yolov8")')
    print(f'      mlflow.set_tag("developer", "john")')
    print(f'      mlflow.set_tag("dataset_version", "wider-faces-v1.2")')
    print(f'      mlflow.log_metric("recall", 0.95)')
    print(f'      mlflow.log_metric("fps_1080p", 58.3)')
    print()
    print("Model Comparison (A/B Test):")
    print(f'  mlflow.set_experiment("Staging-Model-Comparison")')
    print(f'  with mlflow.start_run(run_name="yolov8-vs-resnet"):')
    print(f'      mlflow.set_tag("baseline_model", "resnet50")')
    print(f'      mlflow.set_tag("candidate_model", "yolov8n")')
    print(f'      mlflow.log_metric("recall_improvement", 0.08)')
    print(f'      mlflow.log_metric("fps_improvement", 12.5)')
    print()
    print("Dataset Registration:")
    print(f'  mlflow.set_experiment("Dataset-Registry")')
    print(f'  with mlflow.start_run(run_name="wider-faces-v1.2"):')
    print(f'      mlflow.log_artifact("train.zip", "datasets/train")')
    print(f'      mlflow.log_artifact("val.zip", "datasets/val")')
    print(f'      mlflow.set_tag("dataset_source", "wider-faces")')
    print("-" * 60)

    return True


if __name__ == "__main__":
    try:
        success = initialize_experiments()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Fatal Error: {e}")
        sys.exit(1)
