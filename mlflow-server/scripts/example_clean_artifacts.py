"""
Example training script with proper artifact organization.

Demonstrates best practices for logging artifacts to MLflow with clean organization.
"""

import os
import mlflow
import yaml
from pathlib import Path


def train_model_with_clean_artifacts():
    """Train model and log artifacts in organized structure."""

    # Configuration - use environment variable or localhost
    tailscale_ip = os.getenv("TAILSCALE_IP", "localhost")
    TRACKING_URI = f"http://{tailscale_ip}:8080"
    mlflow.set_tracking_uri(TRACKING_URI)
    mlflow.set_experiment("model-registry-v2")

    # Start run with descriptive name
    with mlflow.start_run(run_name="yolov5-face-detection-v1.2") as run:

        # 1. SET COMPREHENSIVE TAGS
        # Artifact organization tags
        mlflow.set_tag("artifact_type", "model")
        mlflow.set_tag("model_type", "yolov5")
        mlflow.set_tag("task", "face_detection")
        mlflow.set_tag("version", "1.2")

        # Dataset linkage tags
        mlflow.set_tag("dataset_name", "WIDER-face")
        mlflow.set_tag("dataset_version", "1.0")
        mlflow.set_tag("dataset_split", "train+val")

        # Training metadata
        mlflow.set_tag("framework", "pytorch")
        mlflow.set_tag("hardware", "NVIDIA RTX 3090")
        mlflow.set_tag("training_duration", "4.5h")

        # 2. LOG PARAMETERS (for searchability)
        params = {
            # Model architecture
            "model_size": "medium",
            "input_size": 640,
            "backbone": "CSPDarknet",
            # Training hyperparameters
            "epochs": 100,
            "batch_size": 32,
            "learning_rate": 0.001,
            "optimizer": "Adam",
            "weight_decay": 0.0005,
            # Data augmentation
            "augmentation": "mosaic+mixup",
            "hsv_h": 0.015,
            "hsv_s": 0.7,
            "hsv_v": 0.4,
            # Dataset stats
            "num_train_images": 12880,
            "num_val_images": 3226,
            "num_classes": 1,
        }

        for key, value in params.items():
            mlflow.log_param(key, value)

        # 3. LOG METRICS (throughout training)
        # Final metrics
        metrics = {
            "final_map": 0.847,
            "final_map50": 0.932,
            "final_precision": 0.89,
            "final_recall": 0.86,
            "final_loss": 0.032,
            "best_epoch": 87,
        }

        for key, value in metrics.items():
            mlflow.log_metric(key, value)

        # 4. LOG ARTIFACTS - ORGANIZED STRUCTURE

        # MODEL FILES (essential only)
        model_dir = Path("runs/train/exp/weights")
        if (model_dir / "best.pt").exists():
            mlflow.log_artifact(str(model_dir / "best.pt"), "model")
            print("✓ Logged: model/best.pt")

        # Optional: Log model info
        model_info = {
            "architecture": "YOLOv5m",
            "parameters": "21.2M",
            "size_mb": 42.1,
            "framework": "PyTorch 2.0.1",
            "input_shape": [3, 640, 640],
            "output_format": "YOLO detection format",
        }
        model_info_path = Path("/tmp/model_info.yaml")
        with open(model_info_path, "w") as f:
            yaml.dump(model_info, f)
        mlflow.log_artifact(str(model_info_path), "model")
        print("✓ Logged: model/model_info.yaml")

        # CONFIGURATION (training config)
        config_dir = Path("runs/train/exp")
        if (config_dir / "args.yaml").exists():
            mlflow.log_artifact(str(config_dir / "args.yaml"), "config")
            print("✓ Logged: config/args.yaml")

        # RESULTS (summary metrics)
        results_dir = Path("runs/train/exp")
        if (results_dir / "results.csv").exists():
            mlflow.log_artifact(str(results_dir / "results.csv"), "results")
            print("✓ Logged: results/results.csv")

        # Optional: Create summary JSON
        results_summary = {
            "best_epoch": 87,
            "final_metrics": metrics,
            "training_time": "4.5 hours",
            "convergence": "stable",
        }
        summary_path = Path("/tmp/training_summary.yaml")
        with open(summary_path, "w") as f:
            yaml.dump(results_summary, f)
        mlflow.log_artifact(str(summary_path), "results")
        print("✓ Logged: results/training_summary.yaml")

        # PLOTS (KEY VISUALIZATIONS ONLY - 5-10 max)
        plots_dir = Path("runs/train/exp")

        # Essential plots
        essential_plots = [
            "confusion_matrix.png",
            "PR_curve.png",
            "F1_curve.png",
            "results.png",  # Training curves
            "labels.jpg",  # Label distribution
            "labels_correlogram.jpg",  # Label correlation
        ]

        for plot in essential_plots:
            plot_path = plots_dir / plot
            if plot_path.exists():
                mlflow.log_artifact(str(plot_path), "plots")
                print(f"✓ Logged: plots/{plot}")

        # DO NOT LOG: train_batch0.jpg, train_batch1.jpg, ..., train_batch85742.jpg
        # These are intermediate visualizations not needed for analysis

        # OPTIONAL: Sample predictions (2-3 examples)
        predictions_dir = Path("runs/train/exp/predictions")
        if predictions_dir.exists():
            sample_predictions = list(predictions_dir.glob("*.jpg"))[:3]
            for pred in sample_predictions:
                mlflow.log_artifact(str(pred), "predictions")
                print(f"✓ Logged: predictions/{pred.name}")

        # 5. REGISTER MODEL (if performance meets threshold)
        if metrics["final_map"] >= 0.80:  # Threshold
            model_uri = f"runs:/{run.info.run_id}/model"

            model_details = mlflow.register_model(
                model_uri=model_uri,
                name="yolov5-face-detection",
                tags={
                    "version": "1.2",
                    "dataset": "WIDER-face-v1.0",
                    "performance": f"mAP: {metrics['final_map']:.3f}",
                },
            )

            print(
                f"\n✓ Model registered: {model_details.name} v{model_details.version}"
            )

        # Print summary
        print("\n" + "=" * 60)
        print("ARTIFACT LOGGING COMPLETE")
        print("=" * 60)
        print(f"Run ID: {run.info.run_id}")
        print(f"Run Name: yolov5-face-detection-v1.2")
        print(f"Experiment: model-registry-v2")
        print(f"\nArtifacts logged:")
        print("  model/")
        print("    ├── best.pt (42.1 MB)")
        print("    └── model_info.yaml")
        print("  config/")
        print("    └── args.yaml")
        print("  results/")
        print("    ├── results.csv")
        print("    └── training_summary.yaml")
        print("  plots/ (6 key visualizations)")
        print("    ├── confusion_matrix.png")
        print("    ├── PR_curve.png")
        print("    ├── F1_curve.png")
        print("    ├── results.png")
        print("    ├── labels.jpg")
        print("    └── labels_correlogram.jpg")
        print("  predictions/ (3 samples)")
        print("\nView in UI:")
        print(f"  {TRACKING_URI}/#/experiments/4/runs/{run.info.run_id}")
        print("=" * 60)


def log_dataset_reference():
    """Example: Log a dataset reference (not the actual files)."""

    tailscale_ip = os.getenv("TAILSCALE_IP", "localhost")
    TRACKING_URI = f"http://{tailscale_ip}:8080"
    mlflow.set_tracking_uri(TRACKING_URI)
    mlflow.set_experiment("dataset-registry")

    with mlflow.start_run(run_name="WIDER-face-v1.0") as run:

        # Set tags
        mlflow.set_tag("artifact_type", "dataset")
        mlflow.set_tag("dataset_name", "WIDER-face")
        mlflow.set_tag("dataset_version", "1.0")
        mlflow.set_tag("dataset_type", "face_detection")

        # Log parameters (metadata, not files)
        mlflow.log_param("num_images_train", 12880)
        mlflow.log_param("num_images_val", 3226)
        mlflow.log_param("num_images_test", 16097)
        mlflow.log_param("num_classes", 1)
        mlflow.log_param("format", "PASCAL VOC")
        mlflow.log_param("annotation_type", "bounding_boxes")

        # Log file locations (reference, not upload)
        mlflow.log_param("train_data_path", "/data/WIDER_train")
        mlflow.log_param("val_data_path", "/data/WIDER_val")
        mlflow.log_param("test_data_path", "/data/WIDER_test")

        # Log dataset statistics
        dataset_stats = {
            "total_images": 32203,
            "total_faces": 393703,
            "avg_faces_per_image": 12.2,
            "min_image_size": [75, 75],
            "max_image_size": [1920, 1080],
            "image_formats": ["jpg", "jpeg"],
            "split_ratio": "40:10:50 (train:val:test)",
        }

        stats_path = Path("/tmp/dataset_stats.yaml")
        with open(stats_path, "w") as f:
            yaml.dump(dataset_stats, f)

        mlflow.log_artifact(str(stats_path), "metadata")

        print(f"\n✓ Dataset reference logged: {run.info.run_id}")
        print(f"  This run contains metadata only (no large files uploaded)")


if __name__ == "__main__":
    print("Example 1: Training with clean artifacts")
    print("-" * 60)
    train_model_with_clean_artifacts()

    print("\n\nExample 2: Dataset reference (metadata only)")
    print("-" * 60)
    # Uncomment to run:
    # log_dataset_reference()
