#!/usr/bin/env python3
"""
Enhanced model registration with local/remote artifact storage toggle.

Usage:
    # Store artifacts on remote server (SFTP)
    python register_model.py --model-path /path/to/model --version-name v3.0
    
    # Store artifacts locally only (no upload)
    python register_model.py --model-path /path/to/model --version-name v3.0 --local-only
    
    # Use custom artifact location
    python register_model.py --model-path /path/to/model --version-name v3.0 --artifact-location /custom/path
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any
import mlflow
from mlflow.tracking import MlflowClient


def get_model_info(model_path: Path) -> Dict[str, Any]:
    """Extract model information from directory."""
    info = {
        "weights": model_path / "weights" / "best.pt",
        "args": model_path / "args.yaml",
        "results": model_path / "results.csv",
        "data_yaml": None,
    }
    
    # Find data.yaml in various possible locations
    for data_file in [
        model_path / "data.yaml",
        model_path.parent.parent / "data.yaml",
        Path("/workspace/data/training") / "data.yaml",
    ]:
        if data_file.exists():
            info["data_yaml"] = data_file
            break
    
    # Validate required files
    if not info["weights"].exists():
        raise FileNotFoundError(f"Model weights not found: {info['weights']}")
    if not info["args"].exists():
        raise FileNotFoundError(f"Training config not found: {info['args']}")
    if not info["results"].exists():
        raise FileNotFoundError(f"Results file not found: {info['results']}")
    
    return info


def parse_args_yaml(args_file: Path) -> Dict[str, Any]:
    """Parse training arguments from YAML file."""
    import yaml
    with open(args_file) as f:
        return yaml.safe_load(f)


def parse_results_csv(results_file: Path) -> Dict[str, float]:
    """Parse final metrics from results.csv."""
    import pandas as pd
    df = pd.read_csv(results_file)
    df.columns = df.columns.str.strip()
    
    # Get final epoch metrics
    final_row = df.iloc[-1]
    
    metrics = {}
    metric_cols = {
        "metrics/precision(B)": "precision",
        "metrics/recall(B)": "recall", 
        "metrics/mAP50(B)": "mAP50",
        "metrics/mAP50-95(B)": "mAP50-95",
        "train/box_loss": "train_box_loss",
        "train/cls_loss": "train_cls_loss",
        "val/box_loss": "val_box_loss",
        "val/cls_loss": "val_cls_loss",
    }
    
    for csv_col, metric_name in metric_cols.items():
        if csv_col in final_row.index:
            metrics[metric_name] = float(final_row[csv_col])
    
    return metrics


def register_model_local(
    model_path: Path,
    model_name: str,
    version_name: str,
    description: str,
    stage: Optional[str] = None,
    run_id: Optional[str] = None,
    local_artifact_path: Optional[Path] = None,
) -> str:
    """
    Register model with artifacts stored LOCALLY (no remote upload).
    
    This mode:
    - Creates MLflow run with metadata
    - Stores artifact REFERENCES (paths) only
    - Does NOT upload files to server
    - Useful for local testing or when server storage is unavailable
    """
    print("\n" + "=" * 70)
    print(f"Registering Model (LOCAL ARTIFACTS): {model_name} - {version_name}")
    print("=" * 70)
    print(f"Model path: {model_path}")
    print(f"Mode: Local artifacts only (no remote upload)")
    print(f"Registry: {mlflow.get_tracking_uri()}")
    print()
    
    # Get model info
    info = get_model_info(model_path)
    model_size_mb = info["weights"].stat().st_size / (1024 * 1024)
    print(f"Model size: {model_size_mb:.1f} MB")
    
    # Parse config and metrics
    args = parse_args_yaml(info["args"])
    metrics = parse_results_csv(info["results"])
    print(f"Training config loaded: {len(args)} parameters")
    print(f"Final metrics loaded: mAP50={metrics.get('mAP50', 0):.3f}")
    
    # Create or use existing run
    if run_id:
        print(f"\nUsing existing run: {run_id}")
        mlflow.start_run(run_id=run_id)
    else:
        print("\nCreating new registration run...")
        mlflow.start_run(run_name=f"{model_name}_{version_name}_local")
        run_id = mlflow.active_run().info.run_id
        print(f"Run ID: {run_id}")
    
    try:
        # Log parameters (just metadata, no files)
        print("\nLogging training parameters...")
        for key, value in args.items():
            if isinstance(value, (int, float, str, bool)):
                mlflow.log_param(key, value)
        
        # Log metrics
        print("Logging final metrics...")
        for metric_name, metric_value in metrics.items():
            mlflow.log_metric(metric_name, metric_value)
        
        # Log tags (including file paths as references)
        print("Logging tags...")
        mlflow.set_tag("model_version", version_name)
        mlflow.set_tag("model_type", "YOLOv8")
        mlflow.set_tag("task", "face_detection")
        mlflow.set_tag("model_size_mb", f"{model_size_mb:.1f}")
        mlflow.set_tag("description", description)
        mlflow.set_tag("artifact_mode", "local_references")
        mlflow.set_tag("model_path", str(info["weights"]))
        mlflow.set_tag("config_path", str(info["args"]))
        mlflow.set_tag("results_path", str(info["results"]))
        if info["data_yaml"]:
            mlflow.set_tag("data_yaml_path", str(info["data_yaml"]))
        
        print("\n✓ Metadata logged (no artifact upload)")
        
        # Register model (without artifact upload)
        print(f"\nRegistering in Model Registry: {model_name}")
        print("  Note: Using path reference, not uploaded artifact")
        
        # Create a dummy model URI (just reference)
        model_uri = f"file://{info['weights']}"
        
        # Register model
        client = MlflowClient()
        model_version = client.create_registered_model(model_name) if model_name not in [m.name for m in client.search_registered_models()] else None
        
        # Create model version with tags
        model_version = client.create_model_version(
            name=model_name,
            source=model_uri,
            run_id=run_id,
            tags={
                "version": version_name,
                "model_type": "YOLOv8",
                "artifact_mode": "local_reference",
            }
        )
        
        print(f"✓ Model version registered: {model_version.version}")
        
        # Set stage if specified
        if stage and stage != "None":
            client.transition_model_version_stage(
                name=model_name,
                version=model_version.version,
                stage=stage,
            )
            print(f"✓ Model stage set to: {stage}")
        
        run_info = mlflow.active_run().info
        print("\n" + "=" * 70)
        print("Registration Complete (Local Mode)")
        print("=" * 70)
        print(f"Model: {model_name} v{model_version.version}")
        print(f"Stage: {stage or 'None'}")
        print(f"Run: {run_info.experiment_id}/{run_id}")
        print(f"Artifacts: Local references only")
        print("=" * 70)
        
        return model_version.version
    
    finally:
        mlflow.end_run()


def register_model_remote(
    model_path: Path,
    model_name: str,
    version_name: str,
    description: str,
    stage: Optional[str] = None,
    run_id: Optional[str] = None,
) -> str:
    """
    Register model with artifacts uploaded to REMOTE server (SFTP).
    
    This mode:
    - Creates MLflow run with metadata
    - Uploads ALL artifacts to server (weights, config, data, results, plots)
    - Stores artifacts securely via SFTP
    - Enables full reproducibility
    """
    print("\n" + "=" * 70)
    print(f"Registering Model (REMOTE ARTIFACTS): {model_name} - {version_name}")
    print("=" * 70)
    print(f"Model path: {model_path}")
    print(f"Mode: Remote artifact upload via SFTP")
    print(f"Registry: {mlflow.get_tracking_uri()}")
    print()
    
    # Get model info
    info = get_model_info(model_path)
    model_size_mb = info["weights"].stat().st_size / (1024 * 1024)
    print(f"Model size: {model_size_mb:.1f} MB")
    
    # Parse config and metrics
    args = parse_args_yaml(info["args"])
    metrics = parse_results_csv(info["results"])
    print(f"Training config loaded: {len(args)} parameters")
    print(f"Final metrics loaded: mAP50={metrics.get('mAP50', 0):.3f}")
    
    # Create or use existing run
    if run_id:
        print(f"\nUsing existing run: {run_id}")
        mlflow.start_run(run_id=run_id)
    else:
        print("\nCreating new registration run...")
        mlflow.start_run(run_name=f"{model_name}_{version_name}_remote")
        run_id = mlflow.active_run().info.run_id
        print(f"Run ID: {run_id}")
    
    try:
        # Log parameters
        print("\nLogging training parameters...")
        for key, value in args.items():
            if isinstance(value, (int, float, str, bool)):
                mlflow.log_param(key, value)
        
        # Log metrics
        print("Logging final metrics...")
        for metric_name, metric_value in metrics.items():
            mlflow.log_metric(metric_name, metric_value)
        
        # Log tags
        print("Logging tags...")
        mlflow.set_tag("model_version", version_name)
        mlflow.set_tag("model_type", "YOLOv8")
        mlflow.set_tag("task", "face_detection")
        mlflow.set_tag("model_size_mb", f"{model_size_mb:.1f}")
        mlflow.set_tag("description", description)
        mlflow.set_tag("artifact_mode", "remote_sftp")
        
        # Upload artifacts to server
        print("\nUploading artifacts to server...")
        
        # 1. Model weights
        print("  - Model weights (best.pt)...")
        mlflow.log_artifact(str(info["weights"]), "model")
        
        # 2. Training config
        print("  - Training config (args.yaml)...")
        mlflow.log_artifact(str(info["args"]), "config")
        
        # 3. Data manifest
        if info["data_yaml"]:
            print("  - Data manifest (data.yaml)...")
            mlflow.log_artifact(str(info["data_yaml"]), "data")
        
        # 4. Training results
        print("  - Training results (results.csv)...")
        mlflow.log_artifact(str(info["results"]), "results")
        
        # 5. Training plots
        print("  - Training plots...")
        plots_dir = model_path
        for plot_name in ["labels.jpg", "labels_correlogram.jpg", "confusion_matrix.png", "results.png"]:
            plot_path = plots_dir / plot_name
            if plot_path.exists():
                mlflow.log_artifact(str(plot_path), "plots")
        
        for batch_plot in plots_dir.glob("train_batch*.jpg"):
            mlflow.log_artifact(str(batch_plot), "plots")
        for val_plot in plots_dir.glob("val_batch*_*.jpg"):
            mlflow.log_artifact(str(val_plot), "plots")
        
        # 6. Checkpoint weights
        print("  - Checkpoint weights...")
        weights_dir = model_path / "weights"
        for weight_file in weights_dir.glob("*.pt"):
            if weight_file.name != "best.pt":  # already logged
                mlflow.log_artifact(str(weight_file), "checkpoints")
        
        print("✓ All artifacts uploaded")
        
        # Register model in Model Registry
        print(f"\nRegistering in Model Registry: {model_name}")
        model_uri = f"runs:/{run_id}/model/best.pt"
        
        model_version = mlflow.register_model(
            model_uri=model_uri,
            name=model_name,
            tags={
                "version": version_name,
                "model_type": "YOLOv8",
                "artifact_mode": "remote_sftp",
            }
        )
        
        print(f"✓ Model version registered: {model_version.version}")
        
        # Set stage if specified
        if stage and stage != "None":
            client = MlflowClient()
            client.transition_model_version_stage(
                name=model_name,
                version=model_version.version,
                stage=stage,
            )
            print(f"✓ Model stage set to: {stage}")
        
        run_info = mlflow.active_run().info
        print("\n" + "=" * 70)
        print("Registration Complete (Remote Mode)")
        print("=" * 70)
        print(f"Model: {model_name} v{model_version.version}")
        print(f"Stage: {stage or 'None'}")
        print(f"Run: {run_info.experiment_id}/{run_id}")
        print(f"View: {mlflow.get_tracking_uri()}/#/experiments/{run_info.experiment_id}/runs/{run_id}")
        print(f"Artifacts: Uploaded to server via SFTP")
        print("=" * 70)
        
        return model_version.version
    
    finally:
        mlflow.end_run()


def main():
    parser = argparse.ArgumentParser(
        description="Register YOLOv8 model in MLflow with local/remote artifact storage toggle"
    )
    parser.add_argument(
        "--model-path",
        type=str,
        required=True,
        help="Path to model directory (must contain weights/best.pt, args.yaml, results.csv)"
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default="pii-face-detector",
        help="Model name in registry (default: pii-face-detector)"
    )
    parser.add_argument(
        "--version-name",
        type=str,
        required=True,
        help="Version name (e.g., v1.0, v2.0, baseline)"
    )
    parser.add_argument(
        "--description",
        type=str,
        default="",
        help="Model description"
    )
    parser.add_argument(
        "--stage",
        type=str,
        choices=["None", "Staging", "Production", "Archived"],
        default="None",
        help="Model stage (default: None)"
    )
    parser.add_argument(
        "--run-id",
        type=str,
        help="Existing MLflow run ID to attach artifacts to (optional)"
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Store artifacts locally only (no remote upload)"
    )
    parser.add_argument(
        "--artifact-location",
        type=str,
        help="Custom local artifact storage path (only with --local-only)"
    )
    
    args = parser.parse_args()
    
    # Validate model path
    model_path = Path(args.model_path).resolve()
    if not model_path.exists():
        print(f"Error: Model path does not exist: {model_path}")
        sys.exit(1)
    
    # Check MLflow tracking URI
    tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000")
    mlflow.set_tracking_uri(tracking_uri)
    
    try:
        # Choose registration mode
        if args.local_only:
            version = register_model_local(
                model_path=model_path,
                model_name=args.model_name,
                version_name=args.version_name,
                description=args.description,
                stage=args.stage if args.stage != "None" else None,
                run_id=args.run_id,
                local_artifact_path=Path(args.artifact_location) if args.artifact_location else None,
            )
        else:
            version = register_model_remote(
                model_path=model_path,
                model_name=args.model_name,
                version_name=args.version_name,
                description=args.description,
                stage=args.stage if args.stage != "None" else None,
                run_id=args.run_id,
            )
        
        print(f"\n✓ Successfully registered model version: {version}")
        sys.exit(0)
    
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
