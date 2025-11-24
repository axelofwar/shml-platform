#!/usr/bin/env python3
"""
Register Model Metadata in MLflow Model Registry
Creates model versions with metadata (without uploading large files)
"""

import mlflow
from mlflow.tracking import MlflowClient
from pathlib import Path
import hashlib

# Configuration
MLFLOW_URI = "http://<SERVER_IP>:5000"
MODEL_NAME = "pii-pro-face-detector"

# Models to register
MODELS = [
    {
        "version": "1.0.0",
        "name": "baseline-v1.0",
        "path": "/workspace/models/face_detection/face_occluded_safe/weights/best.pt",
        "description": "Baseline model - YOLOv8m trained on WIDER Face + occlusions (safe checkpoint)",
        "stage": "Archived",
        "aliases": ["baseline"],
        "metrics": {
            "map50": 0.88,
            "precision": 0.87,
            "recall": 0.80
        },
        "tags": {
            "version": "1.0.0",
            "dataset": "wider_face_occluded",
            "resolution": "640",
            "model_type": "yolov8m",
            "epochs": "30",
            "batch_size": "16"
        }
    },
    {
        "version": "2.0.0",
        "name": "v2.0-occluded",
        "path": "/workspace/models/face_detection/face_occluded_finetune_optimized/weights/best.pt",
        "description": "v2.0 - Optimized occlusion handling, improved recall. Comprehensive test: 880 detections",
        "stage": "Archived",
        "aliases": ["v2"],
        "metrics": {
            "map50": 0.89,
            "precision": 0.88,
            "recall": 0.82,
            "comprehensive_test_detections": 880
        },
        "tags": {
            "version": "2.0.0",
            "dataset": "wider_face_occluded_optimized",
            "resolution": "640",
            "model_type": "yolov8m",
            "epochs": "30",
            "batch_size": "16",
            "comprehensive_test": "880_detections"
        }
    },
    {
        "version": "3.0.0",
        "name": "v3.0-negatives",
        "path": "/workspace/models/face_detection/face_recall_and_negatives_v3/weights/best.pt",
        "description": "v3.0 - Hard negatives added, improved precision/recall balance. Comprehensive test: 916 detections (+4% vs v2.0)",
        "stage": "Production",
        "aliases": ["v3", "production"],
        "metrics": {
            "map50": 0.895,
            "precision": 0.89,
            "recall": 0.83,
            "comprehensive_test_detections": 916
        },
        "tags": {
            "version": "3.0.0",
            "dataset": "wider_face_occluded_with_negatives",
            "resolution": "640",
            "model_type": "yolov8m",
            "epochs": "30",
            "batch_size": "16",
            "comprehensive_test": "916_detections",
            "improvement_vs_v2": "+4%"
        }
    }
]

def get_file_hash(filepath):
    """Calculate SHA256 hash of file"""
    sha256 = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()

def register_model_version(model_info, client):
    """Register model version with metadata"""
    
    model_path = Path(model_info["path"])
    
    if not model_path.exists():
        print(f"  ⚠️  Model not found: {model_path}")
        return False
    
    print(f"\nRegistering: {model_info['name']} (v{model_info['version']})")
    print(f"  Path: {model_path}")
    
    size_mb = model_path.stat().st_size / (1024*1024)
    print(f"  Size: {size_mb:.1f} MB")
    
    try:
        # Calculate file hash for tracking
        print("  Computing hash...", end=" ", flush=True)
        file_hash = get_file_hash(model_path)[:16]  # First 16 chars
        print(f"✓ {file_hash}")
        
        # Create a run with model metadata
        experiment_name = "pii-pro-face-detection"
        try:
            exp = client.get_experiment_by_name(experiment_name)
            exp_id = exp.experiment_id if exp else None
        except:
            exp_id = None
        
        if not exp_id:
            exp_id = client.create_experiment(experiment_name)
        
        with mlflow.start_run(
            experiment_id=exp_id,
            run_name=f"model_registry_{model_info['name']}"
        ):
            # Log metrics
            for key, value in model_info.get("metrics", {}).items():
                mlflow.log_metric(key, value)
            
            # Log parameters/tags
            mlflow.log_param("model_path", str(model_path))
            mlflow.log_param("model_size_mb", f"{size_mb:.1f}")
            mlflow.log_param("file_hash", file_hash)
            
            for key, value in model_info["tags"].items():
                mlflow.set_tag(key, str(value))
            
            # Add model metadata
            mlflow.set_tag("mlflow.note.content", model_info["description"])
            mlflow.set_tag("model_location", str(model_path))
            
            run_id = mlflow.active_run().info.run_id
        
        # Register the model (using run_id reference, not uploading file)
        model_uri = f"runs:/{run_id}/model"
        
        # Create model version
        result = client.create_model_version(
            name=MODEL_NAME,
            source=model_uri,
            run_id=run_id,
            description=model_info["description"],
            tags=model_info["tags"]
        )
        
        version = result.version
        
        # Set stage
        if model_info.get("stage"):
            client.transition_model_version_stage(
                name=MODEL_NAME,
                version=version,
                stage=model_info["stage"],
                archive_existing_versions=False
            )
        
        # Set aliases
        for alias in model_info.get("aliases", []):
            try:
                client.set_registered_model_alias(
                    name=MODEL_NAME,
                    alias=alias,
                    version=version
                )
            except:
                pass  # Aliases might not be supported in older MLflow versions
        
        print(f"  ✓ Registered as version {version}")
        print(f"  ✓ Stage: {model_info.get('stage', 'None')}")
        if model_info.get("aliases"):
            print(f"  ✓ Aliases: {', '.join(model_info['aliases'])}")
        
        return True
        
    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("=" * 70)
    print("Register Model Versions to MLflow Model Registry")
    print("=" * 70)
    print(f"\nMLflow Server: {MLFLOW_URI}")
    print(f"Model Name: {MODEL_NAME}")
    print(f"Versions to register: {len(MODELS)}")
    print()
    
    mlflow.set_tracking_uri(MLFLOW_URI)
    client = MlflowClient(MLFLOW_URI)
    
    # Create or get registered model
    try:
        model = client.get_registered_model(MODEL_NAME)
        print(f"✓ Using existing registered model: {MODEL_NAME}")
    except:
        print(f"✓ Creating registered model: {MODEL_NAME}")
        client.create_registered_model(
            name=MODEL_NAME,
            description="PII-PRO Face Detection Model - YOLOv8m based detector for privacy protection in autonomous vehicle applications"
        )
    
    print()
    
    # Register each version
    registered = 0
    for model_info in MODELS:
        if register_model_version(model_info, client):
            registered += 1
    
    print("\n" + "=" * 70)
    print(f"✅ Registration Complete!")
    print(f"Successfully registered: {registered}/{len(MODELS)} model versions")
    print("=" * 70)
    print()
    print("📊 View Model Registry:")
    print(f"   {MLFLOW_URI}/#/models/{MODEL_NAME}")
    print()
    print("📥 Load production model:")
    print(f"   # Via stage")
    print(f"   model_uri = 'models:/{MODEL_NAME}/Production'")
    print()
    print(f"   # Via version")
    print(f"   model_uri = 'models:/{MODEL_NAME}/3'")
    print()
    print(f"   # Via alias")
    print(f"   model_uri = 'models:/{MODEL_NAME}@production'")
    print()
    print("💡 Model files remain at their local paths (not uploaded)")
    print("   Use tags to track file locations and hashes")
    print()

if __name__ == "__main__":
    main()
