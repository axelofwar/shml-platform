#!/usr/bin/env python3
"""
Register YOLOv8 Model in MLflow Model Registry

Properly registers a trained model with:
- Model weights (actual .pt file)
- Training configuration (args.yaml)
- Training data manifest (data.yaml)
- Training results and plots
- Metadata and tags for reproducibility
"""

import os
import sys
import argparse
from pathlib import Path
import yaml
import mlflow
from mlflow.tracking import MlflowClient
import shutil

# Set remote tracking
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://<SERVER_IP>:5000")
mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)


def register_yolo_model(
    model_path: str,
    model_name: str,
    version_name: str,
    description: str = "",
    stage: str = "None",
    run_id: str = None,
):
    """
    Register a YOLOv8 model with all artifacts

    Args:
        model_path: Path to model directory (e.g., models/face_detection/face_recall_and_negatives_v3)
        model_name: Model registry name (e.g., "pii-face-detector")
        version_name: Version identifier (e.g., "v3.0", "baseline")
        description: Model description
        stage: Model stage (None, Staging, Production, Archived)
        run_id: Optional existing MLflow run ID
    """

    model_path = Path(model_path)
    if not model_path.exists():
        raise ValueError(f"Model path not found: {model_path}")

    # Find best.pt weights
    best_weights = model_path / "weights" / "best.pt"
    if not best_weights.exists():
        raise ValueError(f"Model weights not found: {best_weights}")

    print("=" * 70)
    print(f"Registering Model: {model_name} - {version_name}")
    print("=" * 70)
    print(f"Model path: {model_path}")
    print(f"Weights: {best_weights}")
    print(f"Registry: {MLFLOW_TRACKING_URI}")
    print()

    # Get model size
    model_size_mb = best_weights.stat().st_size / (1024 * 1024)
    print(f"Model size: {model_size_mb:.1f} MB")

    # Load training args if available
    args_file = model_path / "args.yaml"
    training_config = {}
    if args_file.exists():
        with open(args_file, "r") as f:
            training_config = yaml.safe_load(f)
        print(f"Training config loaded: {len(training_config)} parameters")

    # Load results if available
    results_file = model_path / "results.csv"
    final_metrics = {}
    if results_file.exists():
        import pandas as pd

        results_df = pd.read_csv(results_file)
        # Get final epoch metrics
        if len(results_df) > 0:
            final_row = results_df.iloc[-1]
            final_metrics = {
                "final_precision": float(final_row.get("metrics/precision(B)", 0)),
                "final_recall": float(final_row.get("metrics/recall(B)", 0)),
                "final_mAP50": float(final_row.get("metrics/mAP50(B)", 0)),
                "final_mAP50-95": float(final_row.get("metrics/mAP50-95(B)", 0)),
            }
        print(f"Final metrics loaded: mAP50={final_metrics.get('final_mAP50', 'N/A')}")

    # Start MLflow run
    if run_id:
        # Use existing run
        client = MlflowClient()
        run = client.get_run(run_id)
        experiment_id = run.info.experiment_id
        print(f"\nUsing existing run: {run_id}")
    else:
        # Create new run
        experiment_name = "pii-pro-model-registry"
        try:
            experiment = mlflow.get_experiment_by_name(experiment_name)
            if experiment:
                experiment_id = experiment.experiment_id
            else:
                experiment_id = mlflow.create_experiment(experiment_name)
        except:
            experiment_id = mlflow.create_experiment(experiment_name)

        print(f"\nCreating new registration run...")

    with mlflow.start_run(
        run_id=run_id, experiment_id=experiment_id if not run_id else None
    ) as run:
        run_id = run.info.run_id
        print(f"Run ID: {run_id}")

        # Log parameters from training config
        if training_config:
            print("\nLogging training parameters...")
            for key, value in training_config.items():
                if isinstance(value, (str, int, float, bool)):
                    mlflow.log_param(f"train_{key}", value)

        # Log final metrics
        if final_metrics:
            print("Logging final metrics...")
            for key, value in final_metrics.items():
                mlflow.log_metric(key, value)

        # Log tags
        print("Logging tags...")
        mlflow.set_tag("model_version", version_name)
        mlflow.set_tag("model_type", "YOLOv8")
        mlflow.set_tag("task", "face-detection")
        mlflow.set_tag("model_size_mb", f"{model_size_mb:.1f}")
        if description:
            mlflow.set_tag("description", description)

        # Log artifacts
        print("\nLogging artifacts...")

        # 1. Model weights (critical!)
        print("  - Model weights (best.pt)...")
        mlflow.log_artifact(str(best_weights), "model")

        # 2. Training config
        if args_file.exists():
            print("  - Training config (args.yaml)...")
            mlflow.log_artifact(str(args_file), "config")

        # 3. Training results
        if results_file.exists():
            print("  - Training results (results.csv)...")
            mlflow.log_artifact(str(results_file), "results")

        # 4. Training data manifest
        if training_config.get("data"):
            data_yaml_path = training_config["data"]
            if Path(data_yaml_path).exists():
                print(f"  - Data manifest ({Path(data_yaml_path).name})...")
                mlflow.log_artifact(data_yaml_path, "data")

        # 5. Training plots
        plots_to_log = [
            "labels.jpg",
            "labels_correlogram.jpg",
            "train_batch0.jpg",
            "train_batch1.jpg",
            "train_batch2.jpg",
        ]
        for plot_name in plots_to_log:
            plot_path = model_path / plot_name
            if plot_path.exists():
                print(f"  - Plot ({plot_name})...")
                mlflow.log_artifact(str(plot_path), "plots")

        # 6. Additional weights (last, epoch checkpoints)
        weights_dir = model_path / "weights"
        if weights_dir.exists():
            for weight_file in weights_dir.glob("*.pt"):
                if weight_file.name != "best.pt":  # Already logged
                    print(f"  - Checkpoint ({weight_file.name})...")
                    mlflow.log_artifact(str(weight_file), "checkpoints")

        # Register model in Model Registry using PyFunc
        print(f"\nRegistering model in Model Registry as '{model_name}'...")

        # Create a simple wrapper for YOLO model
        model_uri = f"runs:/{run_id}/model/best.pt"

        try:
            # Register the model
            model_version = mlflow.register_model(
                model_uri=model_uri,
                name=model_name,
                tags={
                    "version": version_name,
                    "model_type": "YOLOv8",
                    "task": "face-detection",
                },
            )

            print(f"\n✓ Model registered successfully!")
            print(f"  Model name: {model_name}")
            print(f"  Version: {model_version.version}")
            print(f"  Version name: {version_name}")

            # Update model version stage
            if stage and stage != "None":
                client = MlflowClient()
                client.transition_model_version_stage(
                    name=model_name, version=model_version.version, stage=stage
                )
                print(f"  Stage: {stage}")

            # Add description to model version
            if description:
                client = MlflowClient()
                client.update_model_version(
                    name=model_name,
                    version=model_version.version,
                    description=description,
                )

        except Exception as e:
            print(f"\n✗ Error registering model: {e}")
            print(
                "\nModel artifacts logged successfully, but registry registration failed."
            )
            print("Check MLflow server permissions for model registry.")

    print("\n" + "=" * 70)
    print("Registration Complete!")
    print("=" * 70)
    print(f"\nView in MLflow:")
    print(f"  Run: {MLFLOW_TRACKING_URI}/#/experiments/{experiment_id}/runs/{run_id}")
    print(f"  Models: {MLFLOW_TRACKING_URI}/#/models/{model_name}")
    print()

    return run_id


def main():
    parser = argparse.ArgumentParser(
        description="Register YOLOv8 model in MLflow Model Registry with all artifacts"
    )
    parser.add_argument(
        "--model-path",
        required=True,
        help="Path to model directory (e.g., models/face_detection/face_recall_and_negatives_v3)",
    )
    parser.add_argument(
        "--model-name",
        default="pii-face-detector",
        help="Model registry name (default: pii-face-detector)",
    )
    parser.add_argument(
        "--version-name",
        required=True,
        help="Version identifier (e.g., v3.0, baseline, v2.0)",
    )
    parser.add_argument("--description", default="", help="Model description")
    parser.add_argument(
        "--stage",
        choices=["None", "Staging", "Production", "Archived"],
        default="None",
        help="Model stage (default: None)",
    )
    parser.add_argument("--run-id", help="Optional: Use existing MLflow run ID")

    args = parser.parse_args()

    try:
        register_yolo_model(
            model_path=args.model_path,
            model_name=args.model_name,
            version_name=args.version_name,
            description=args.description,
            stage=args.stage,
            run_id=args.run_id,
        )
    except Exception as e:
        print(f"\nError: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
