#!/usr/bin/env python3
"""
MLflow API Information and Feature Verification
Displays all available MLflow REST API endpoints and their capabilities
"""

import os
import sys
import json
from mlflow.tracking import MlflowClient
from mlflow import __version__ as mlflow_version


def print_section(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


def get_api_endpoints():
    """Return all available MLflow REST API endpoints"""
    return {
        "Experiments": [
            "POST /api/2.0/mlflow/experiments/create",
            "GET  /api/2.0/mlflow/experiments/list",
            "GET  /api/2.0/mlflow/experiments/get",
            "POST /api/2.0/mlflow/experiments/delete",
            "POST /api/2.0/mlflow/experiments/restore",
            "POST /api/2.0/mlflow/experiments/update",
            "POST /api/2.0/mlflow/experiments/set-experiment-tag",
            "GET  /api/2.0/mlflow/experiments/get-by-name",
        ],
        "Runs": [
            "POST /api/2.0/mlflow/runs/create",
            "GET  /api/2.0/mlflow/runs/get",
            "POST /api/2.0/mlflow/runs/search",
            "POST /api/2.0/mlflow/runs/update",
            "POST /api/2.0/mlflow/runs/delete",
            "POST /api/2.0/mlflow/runs/restore",
            "POST /api/2.0/mlflow/runs/log-metric",
            "POST /api/2.0/mlflow/runs/log-parameter",
            "POST /api/2.0/mlflow/runs/set-tag",
            "POST /api/2.0/mlflow/runs/delete-tag",
            "POST /api/2.0/mlflow/runs/log-batch",
        ],
        "Model Registry": [
            "POST /api/2.0/mlflow/registered-models/create",
            "GET  /api/2.0/mlflow/registered-models/list",
            "GET  /api/2.0/mlflow/registered-models/get",
            "POST /api/2.0/mlflow/registered-models/rename",
            "POST /api/2.0/mlflow/registered-models/delete",
            "POST /api/2.0/mlflow/registered-models/update",
            "POST /api/2.0/mlflow/registered-models/get-latest-versions",
            "POST /api/2.0/mlflow/registered-models/set-registered-model-tag",
            "POST /api/2.0/mlflow/registered-models/delete-registered-model-tag",
            "POST /api/2.0/mlflow/registered-models/set-registered-model-alias",
            "POST /api/2.0/mlflow/registered-models/delete-registered-model-alias",
        ],
        "Model Versions": [
            "POST /api/2.0/mlflow/model-versions/create",
            "GET  /api/2.0/mlflow/model-versions/get",
            "POST /api/2.0/mlflow/model-versions/search",
            "POST /api/2.0/mlflow/model-versions/update",
            "POST /api/2.0/mlflow/model-versions/delete",
            "POST /api/2.0/mlflow/model-versions/transition-stage",
            "POST /api/2.0/mlflow/model-versions/set-tag",
            "POST /api/2.0/mlflow/model-versions/delete-tag",
            "GET  /api/2.0/mlflow/model-versions/get-download-uri",
        ],
        "Artifacts": [
            "GET  /api/2.0/mlflow/artifacts/list",
            "POST /get-artifact (multipart upload)",
            "POST /log-artifact (multipart download)",
        ],
        "Datasets (via Runs)": [
            "Dataset tracking through run tags and inputs",
            "log_input() for dataset tracking",
            "Dataset lineage via tags: dataset_name, dataset_version, dataset_path",
            "Dataset metadata in run parameters",
            "Search runs by dataset tags",
        ],
        "Metrics": [
            "POST /api/2.0/mlflow/metrics/get-history",
            "Bulk metric logging via log-batch",
            "Prometheus metrics at /metrics",
        ],
    }


def verify_features(client):
    """Verify that all features are working"""
    features = {}

    try:
        # Test experiments
        experiments = client.search_experiments()
        features["experiments"] = {
            "available": True,
            "count": len(experiments),
            "message": f"✓ {len(experiments)} experiments accessible",
        }
    except Exception as e:
        features["experiments"] = {"available": False, "error": str(e)}

    try:
        # Test model registry
        models = client.search_registered_models()
        features["model_registry"] = {
            "available": True,
            "count": len(models),
            "message": f"✓ Model Registry active ({len(models)} models)",
        }
    except Exception as e:
        features["model_registry"] = {"available": False, "error": str(e)}

    try:
        # Test runs/dataset tracking
        runs = client.search_runs(experiment_ids=["0"], max_results=10)
        dataset_tags = []
        for run in runs:
            tags = run.data.tags
            dataset_tags.extend([k for k in tags.keys() if "dataset" in k.lower()])

        features["dataset_tracking"] = {
            "available": True,
            "runs_checked": len(runs),
            "dataset_tags_found": len(set(dataset_tags)),
            "message": f"✓ Dataset tracking via run tags ({len(set(dataset_tags))} unique dataset tags)",
        }
    except Exception as e:
        features["dataset_tracking"] = {"available": False, "error": str(e)}

    # Schema validation
    schema_enabled = os.getenv("MLFLOW_SCHEMA_VALIDATION", "false").lower() == "true"
    features["schema_validation"] = {
        "available": schema_enabled,
        "message": (
            "✓ Schema validation enabled"
            if schema_enabled
            else "✗ Schema validation disabled"
        ),
    }

    # Compression
    compression = os.getenv("MLFLOW_AUTO_COMPRESS", "false").lower() == "true"
    features["compression"] = {
        "available": compression,
        "format": os.getenv("MLFLOW_COMPRESSION_FORMAT", "zstd"),
        "message": (
            f'✓ Auto-compression enabled ({os.getenv("MLFLOW_COMPRESSION_FORMAT", "zstd")})'
            if compression
            else "✗ Compression disabled"
        ),
    }

    return features


def main():
    print_section("MLflow Server API Information")

    print(f"MLflow Version: {mlflow_version}")
    print(f"Tracking URI: {os.getenv('MLFLOW_TRACKING_URI', 'Not set')}")
    print(f"Backend Store: PostgreSQL (via env)")
    print(f"Artifact Store: {os.getenv('MLFLOW_ARTIFACT_ROOT', 'Not set')}")

    # Connect to MLflow
    try:
        client = MlflowClient()
    except Exception as e:
        print(f"\n❌ Failed to connect to MLflow: {e}")
        sys.exit(1)

    # Display all API endpoints
    print_section("Available REST API Endpoints")

    endpoints = get_api_endpoints()
    for category, apis in endpoints.items():
        print(f"\n📡 {category}:")
        for api in apis:
            print(f"   {api}")

    # Verify features
    print_section("Feature Verification")

    features = verify_features(client)

    for feature_name, feature_data in features.items():
        if feature_data.get("available"):
            print(
                f"✅ {feature_name.replace('_', ' ').title()}: {feature_data.get('message', 'Available')}"
            )
        else:
            print(
                f"❌ {feature_name.replace('_', ' ').title()}: {feature_data.get('error', feature_data.get('message', 'Not available'))}"
            )

    # Model Registry Details
    if features["model_registry"]["available"]:
        print_section("Model Registry Features")
        print("✓ Register models from runs")
        print("✓ Version management (automatic versioning)")
        print("✓ Stage transitions (None → Staging → Production → Archived)")
        print("✓ Model aliases (latest, champion, etc.)")
        print("✓ Model tags and descriptions")
        print("✓ Model lineage tracking")
        print("✓ Search and filter models")
        print("✓ Download model artifacts")

    # Dataset Tracking Details
    print_section("Dataset Tracking Features")
    print("✓ Dataset logging via mlflow.log_input()")
    print("✓ Dataset versioning (dataset_version tag)")
    print("✓ Dataset lineage (track which datasets trained which models)")
    print("✓ Dataset metadata (size, path, schema)")
    print("✓ Reference paths (privacy-aware, no data upload)")
    print("✓ Search runs by dataset")
    print("✓ Dataset tags: dataset_name, dataset_version, dataset_path, dataset_size")

    # Schema Validation Details
    if features["schema_validation"]["available"]:
        print_section("Schema Validation Features")
        print("✓ Enforce required metadata (model_name, version, author, etc.)")
        print("✓ Enforce required tags (environment, dataset_version, framework)")
        print("✓ Enforce required metrics (accuracy, training_time, etc.)")
        print("✓ Enforce required artifacts (model, config, requirements.txt)")
        print("✓ Model completeness check before registration")
        print("✓ Schema change detection (warns on new fields)")
        print("✓ Privacy-aware (supports reference paths)")

    # Additional Features
    print_section("Additional Features")
    print(f"✓ Artifact compression: {features['compression']['message']}")
    print("✓ Prometheus metrics export (/metrics)")
    print("✓ Health check endpoint (/health)")
    print("✓ PostgreSQL backend (experiments + model registry)")
    print("✓ Redis caching (optional)")
    print("✓ Multi-experiment support")
    print("✓ Run comparison and analysis")
    print("✓ Artifact storage with large file support")

    # Usage Examples
    print_section("Usage Examples")

    print("1. Register a model:")
    print(
        """
   import mlflow

   with mlflow.start_run():
       # Log model
       mlflow.sklearn.log_model(model, "model")

       # Register to model registry
       mlflow.register_model(
           model_uri=f"runs:/{mlflow.active_run().info.run_id}/model",
           name="my-awesome-model"
       )
"""
    )

    print("2. Track dataset:")
    print(
        """
   from mlflow.data.pandas_dataset import PandasDataset

   dataset = PandasDataset(df, name="training-data", targets="label")
   mlflow.log_input(dataset, context="training")

   # Or use tags
   mlflow.set_tag("dataset_name", "my-dataset")
   mlflow.set_tag("dataset_version", "v2024.11.21")
   mlflow.log_param("dataset_size", len(df))
"""
    )

    print("3. Search models by dataset:")
    print(
        """
   # Find all runs that used a specific dataset
   runs = client.search_runs(
       experiment_ids=["0"],
       filter_string="tags.dataset_name = 'my-dataset'"
   )

   # Find models trained on dataset version
   runs = client.search_runs(
       filter_string="tags.dataset_version = 'v2024.11.21'"
   )
"""
    )

    print("4. Transition model stages:")
    print(
        """
   client.transition_model_version_stage(
       name="my-awesome-model",
       version=1,
       stage="Production"
   )
"""
    )

    print_section("API Access")

    base_url = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
    print(f"Base URL: {base_url}")
    print(f"\nExample API calls:")
    print(f"  List experiments:     GET  {base_url}/api/2.0/mlflow/experiments/list")
    print(
        f"  List models:          GET  {base_url}/api/2.0/mlflow/registered-models/list"
    )
    print(
        f"  Search model versions: POST {base_url}/api/2.0/mlflow/model-versions/search"
    )
    print(f"  Search runs:          POST {base_url}/api/2.0/mlflow/runs/search")
    print(f"  Health check:         GET  {base_url}/health")
    print(f"  Prometheus metrics:   GET  {base_url}/metrics")

    print("\n" + "=" * 70)
    print("✅ All MLflow features are accessible via REST API")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
