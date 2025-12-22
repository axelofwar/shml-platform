#!/usr/bin/env python3
"""
Initialize MLflow with default experiments and dataset information
This sets up the MLflow Model Registry with proper schema
"""

import mlflow
from mlflow.tracking import MlflowClient
import os

# MLflow configuration
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow-server:5000")
mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)

client = MlflowClient()

print("=" * 70)
print("MLflow Initialization")
print("=" * 70)
print(f"Tracking URI: {MLFLOW_TRACKING_URI}")
print()

# Create default experiments with proper tags
experiments = [
    {
        "name": "face-detection-training",
        "tags": {
            "framework": "yolov8",
            "task": "object-detection",
            "model_type": "face-detector",
            "dataset": "wider_face",
        },
    },
    {
        "name": "model-evaluation",
        "tags": {
            "task": "validation",
            "purpose": "model-benchmarking",
        },
    },
    {
        "name": "production-models",
        "tags": {
            "env": "production",
            "stage": "deployment",
        },
    },
    {
        "name": "development-models",
        "tags": {
            "env": "development",
            "stage": "experimentation",
        },
    },
]

print("Creating default experiments...")
print("-" * 70)
for exp in experiments:
    try:
        experiment_id = client.create_experiment(exp["name"], tags=exp["tags"])
        print(f"✓ Created: {exp['name']} (ID: {experiment_id})")
    except Exception as e:
        if "already exists" in str(e).lower():
            print(f"  Exists: {exp['name']}")
        else:
            print(f"✗ Error creating {exp['name']}: {e}")

print()

# Register WiderFace dataset information
print("Registering WiderFace dataset...")
print("-" * 70)
mlflow.set_experiment("face-detection-training")

try:
    with mlflow.start_run(run_name="wider_face_dataset_v1.0"):
        # Dataset metadata
        mlflow.log_param("dataset_name", "WIDER FACE")
        mlflow.log_param("dataset_version", "v1.0")
        mlflow.log_param("dataset_source", "http://shuoyang1213.me/WIDERFACE/")

        # Statistics
        mlflow.log_param("total_images", 32203)
        mlflow.log_param("train_images", 12880)
        mlflow.log_param("val_images", 3226)
        mlflow.log_param("test_images", 16097)
        mlflow.log_param("total_faces", 393703)

        # Training configuration
        mlflow.log_param("image_format", "jpg")
        mlflow.log_param("label_format", "yolo")
        mlflow.log_param("classes", "face")
        mlflow.log_param("num_classes", 1)

        # Recommended training parameters
        mlflow.log_param("recommended_batch_size", 4)
        mlflow.log_param("recommended_imgsz", [480, 640, 800, 960, 1280])
        mlflow.log_param("recommended_epochs", 50)

        # Tags
        mlflow.set_tag("mlflow.runName", "wider_face_dataset_v1.0")
        mlflow.set_tag("dataset", "wider_face")
        mlflow.set_tag("task", "face-detection")
        mlflow.set_tag("data_type", "images")
        mlflow.set_tag("annotation_type", "bounding_boxes")

        # Log dataset description
        mlflow.log_text(
            """WIDER FACE Dataset - Face Detection Benchmark

            The WIDER FACE dataset is a comprehensive face detection benchmark consisting of 32,203 images
            and 393,703 labeled face bounding boxes. It contains a high degree of variability in scale,
            pose, occlusion, expression, makeup, and illumination.

            Dataset Split:
            - Training: 12,880 images (40%)
            - Validation: 3,226 images (10%)
            - Testing: 16,097 images (50%)

            Difficulty Levels:
            - Easy: Large, clear faces
            - Medium: Medium-sized faces with moderate occlusion
            - Hard: Small faces, heavy occlusion, extreme poses

            Use Cases:
            - Face detection model training
            - Multi-scale detection evaluation
            - Robustness testing for various conditions
            """,
            "dataset_description.txt",
        )

        print("✓ WiderFace dataset registered")

except Exception as e:
    print(f"✗ Error registering dataset: {e}")

print()

# Verify Model Registry is available
print("Verifying Model Registry...")
print("-" * 70)
try:
    # Try to list registered models (should be empty initially)
    models = client.search_registered_models()
    print(f"✓ Model Registry operational ({len(models)} models registered)")
    print("  Ready to register models via:")
    print("    - mlflow.register_model() in Python")
    print("    - MLflow UI -> Models tab")
    print("    - REST API /api/2.0/mlflow/registered-models/create")
except Exception as e:
    print(f"✗ Model Registry error: {e}")

print()

# Display experiment summary
print("Experiment Summary:")
print("-" * 70)
all_experiments = client.search_experiments()
for exp in all_experiments:
    if exp.name != "Default":
        tags_str = ", ".join([f"{k}={v}" for k, v in (exp.tags or {}).items()][:2])
        print(f"  • {exp.name} (ID: {exp.experiment_id})")
        if tags_str:
            print(f"    Tags: {tags_str}")

# Get Tailscale IP from environment or use localhost
tailscale_ip = os.getenv("TAILSCALE_IP", "localhost")

print()
print("=" * 70)
print("✅ MLflow initialization complete!")
print("=" * 70)
print()
print("Access Points:")
print(f"  - UI: http://{tailscale_ip}/mlflow/")
print(f"  - API: http://{tailscale_ip}/api/2.0/mlflow/")
print()
print("Next Steps:")
print("  1. Start training runs with mlflow.start_run()")
print("  2. Log parameters, metrics, and artifacts")
print("  3. Register models to Model Registry")
print("  4. Transition models through stages (None → Staging → Production)")
