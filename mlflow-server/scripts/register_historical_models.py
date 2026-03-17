#!/usr/bin/env python3
"""
Register Historical Models to MLflow Model Registry
Registers baseline, v2.0, and v3.0 models with proper versioning
"""

import mlflow
from mlflow.tracking import MlflowClient
from pathlib import Path
import sys

# Configuration
MLFLOW_URI = "http://<SERVER_IP>:5000"
MODEL_NAME = "pii-pro-face-detector"

# Models to register (in order)
MODELS = [
    {
        "name": "baseline-v1.0",
        "path": "/workspace/models/face_detection/face_occluded_safe/weights/best.pt",
        "description": "Baseline model - YOLOv8m trained on WIDER Face + occlusions (safe checkpoint)",
        "stage": "Archived",
        "tags": {
            "version": "1.0",
            "dataset": "wider_face_occluded",
            "resolution": "640",
            "model_type": "yolov8m",
        },
    },
    {
        "name": "v2.0-occluded",
        "path": "/workspace/models/face_detection/face_occluded_finetune_optimized/weights/best.pt",
        "description": "v2.0 - Optimized occlusion handling, improved recall",
        "stage": "Archived",
        "tags": {
            "version": "2.0",
            "dataset": "wider_face_occluded_optimized",
            "resolution": "640",
            "model_type": "yolov8m",
            "comprehensive_test_detections": "880",
        },
    },
    {
        "name": "v3.0-negatives",
        "path": "/workspace/models/face_detection/face_recall_and_negatives_v3/weights/best.pt",
        "description": "v3.0 - Hard negatives added, improved precision/recall balance",
        "stage": "Production",
        "tags": {
            "version": "3.0",
            "dataset": "wider_face_occluded_with_negatives",
            "resolution": "640",
            "model_type": "yolov8m",
            "comprehensive_test_detections": "916",
        },
    },
]


def register_model(model_info, client):
    """Register a single model version"""

    model_path = Path(model_info["path"])

    if not model_path.exists():
        print(f"  ⚠️  Model not found: {model_path}")
        return False

    print(f"\nRegistering: {model_info['name']}")
    print(f"  Path: {model_path}")
    print(f"  Size: {model_path.stat().st_size / (1024*1024):.1f} MB")

    try:
        # Log model as artifact first
        with mlflow.start_run(run_name=f"register_{model_info['name']}"):
            # Log the model
            mlflow.log_artifact(str(model_path), "model")

            # Log tags
            for key, value in model_info["tags"].items():
                mlflow.set_tag(key, value)

            # Register model
            model_uri = f"runs:/{mlflow.active_run().info.run_id}/model/best.pt"

            result = mlflow.register_model(
                model_uri=model_uri, name=MODEL_NAME, tags=model_info["tags"]
            )

            version = result.version

            # Update version description
            client.update_model_version(
                name=MODEL_NAME, version=version, description=model_info["description"]
            )

            # Set alias (migrated from deprecated transition_model_version_stage)
            stage = model_info.get("stage")
            if stage and stage != "None":
                alias = {"Production": "champion", "Staging": "challenger"}.get(
                    stage, stage.lower()
                )
                client.set_registered_model_alias(
                    name=MODEL_NAME, alias=alias, version=version
                )

            print(f"  ✓ Registered as version {version}")
            print(f"  ✓ Alias: @{alias if stage and stage != 'None' else 'none'}")

            return True

    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback

        traceback.print_exc()
        return False


def main():
    print("=" * 70)
    print("Register Historical Models to MLflow Model Registry")
    print("=" * 70)
    print(f"\nMLflow Server: {MLFLOW_URI}")
    print(f"Model Name: {MODEL_NAME}")
    print(f"Models to register: {len(MODELS)}")
    print()

    # Set tracking URI
    mlflow.set_tracking_uri(MLFLOW_URI)
    client = MlflowClient(MLFLOW_URI)

    # Create registered model if it doesn't exist
    try:
        client.get_registered_model(MODEL_NAME)
        print(f"Using existing registered model: {MODEL_NAME}")
    except:
        print(f"Creating registered model: {MODEL_NAME}")
        client.create_registered_model(
            name=MODEL_NAME,
            description="PII-PRO Face Detection Model - YOLOv8m based detector for privacy protection",
        )

    # Register each model
    registered = 0
    for model_info in MODELS:
        if register_model(model_info, client):
            registered += 1

    print("\n" + "=" * 70)
    print(f"Registration Complete!")
    print(f"Successfully registered: {registered}/{len(MODELS)} models")
    print("=" * 70)
    print()
    print("View in Model Registry:")
    print(f"  {MLFLOW_URI}/#/models/{MODEL_NAME}")
    print()
    print("Load a specific version:")
    print(f"  import mlflow")
    print(f"  model_uri = 'models:/{MODEL_NAME}/Production'")
    print(f"  model = mlflow.pyfunc.load_model(model_uri)")
    print()


if __name__ == "__main__":
    main()
