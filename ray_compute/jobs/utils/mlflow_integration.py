"""
MLflow integration helpers.
Simplified API for common MLflow operations.

Usage:
    helper = MLflowHelper(tracking_uri="http://localhost:8080")

    # Start training run
    run_id = helper.start_training_run(
        experiment_name="face-detection-training",
        run_name="phase1-wider-face-200epochs",
        params={"epochs": 200, "batch_size": 8},
        tags={"phase": "phase1", "dataset": "wider_face"}
    )

    # Log metrics
    for epoch in range(200):
        helper.log_epoch_metrics(epoch, {"loss": 0.5, "mAP50": 0.85})

    # Promote model to production
    helper.promote_model_to_production("face-detection-yolov8l", version=3)
"""

import mlflow
from typing import Dict, Any, Optional, List
from pathlib import Path


class MLflowHelper:
    """Helper class for MLflow operations."""

    def __init__(self, tracking_uri: str = "http://mlflow-server:5000"):
        mlflow.set_tracking_uri(tracking_uri)
        self.tracking_uri = tracking_uri
        self.client = mlflow.tracking.MlflowClient()

    def start_training_run(
        self,
        experiment_name: str,
        run_name: str,
        params: Dict[str, Any],
        tags: Dict[str, str] = None,
    ) -> str:
        """Start a new MLflow run for training."""

        # Create/get experiment
        try:
            experiment_id = mlflow.create_experiment(experiment_name)
        except Exception:
            experiment = mlflow.get_experiment_by_name(experiment_name)
            experiment_id = experiment.experiment_id if experiment else None

        if experiment_id:
            mlflow.set_experiment(experiment_name)

        # Start run
        run = mlflow.start_run(run_name=run_name, tags=tags or {})

        # Log parameters
        mlflow.log_params(params)

        print(f"✓ Started MLflow run: {run.info.run_id}")
        return run.info.run_id

    def log_epoch_metrics(
        self, epoch: int, metrics: Dict[str, float], prefix: str = "train"
    ):
        """Log metrics for a specific epoch."""
        mlflow.log_metrics({f"{prefix}/{k}": v for k, v in metrics.items()}, step=epoch)

    def end_run(self, status: str = "FINISHED"):
        """End the current MLflow run."""
        if mlflow.active_run():
            mlflow.end_run(status=status)
            print(f"✓ Ended MLflow run with status: {status}")

    def load_model_from_registry(
        self, model_name: str, stage: str = "Production"  # or "Staging", "None"
    ) -> str:
        """Load model from MLflow Model Registry."""

        try:
            model_uri = f"models:/{model_name}/{stage}"
            model_path = mlflow.artifacts.download_artifacts(model_uri)

            print(f"✓ Loaded model: {model_name} ({stage})")
            return model_path
        except Exception as e:
            print(f"✗ Failed to load model: {e}")
            return None

    def promote_model_to_production(self, model_name: str, version: int):
        """Promote model version to Production stage."""

        try:
            # Archive current production model
            try:
                current_prod_versions = self.client.get_latest_versions(
                    model_name, stages=["Production"]
                )
                for model_version in current_prod_versions:
                    self.client.transition_model_version_stage(
                        name=model_name, version=model_version.version, stage="Archived"
                    )
                    print(
                        f"✓ Archived previous production model: v{model_version.version}"
                    )
            except Exception:
                pass  # No current production model

            # Promote new model
            self.client.transition_model_version_stage(
                name=model_name, version=version, stage="Production"
            )

            print(f"✓ Promoted {model_name} v{version} to Production")
        except Exception as e:
            print(f"✗ Model promotion failed: {e}")

    def compare_models(
        self, model_name: str, versions: List[int], metric: str = "mAP50"
    ) -> Dict[int, float]:
        """Compare model versions by metric."""

        results = {}

        for version in versions:
            try:
                model_version = self.client.get_model_version(model_name, version)
                run = self.client.get_run(model_version.run_id)
                results[version] = run.data.metrics.get(metric, 0.0)
            except Exception as e:
                print(f"✗ Failed to get metrics for v{version}: {e}")
                results[version] = 0.0

        # Sort by metric (descending)
        sorted_results = dict(sorted(results.items(), key=lambda x: x[1], reverse=True))

        print(f"✓ Model comparison ({metric}):")
        for version, value in sorted_results.items():
            print(f"  v{version}: {value:.4f}")

        return sorted_results

    def get_best_model_version(
        self, model_name: str, metric: str = "mAP50", stage: Optional[str] = None
    ) -> Optional[int]:
        """Get best model version by metric."""

        try:
            if stage:
                versions = self.client.get_latest_versions(model_name, stages=[stage])
            else:
                # Get all versions
                versions = self.client.search_model_versions(f"name='{model_name}'")

            best_version = None
            best_metric = -1

            for model_version in versions:
                try:
                    run = self.client.get_run(model_version.run_id)
                    metric_value = run.data.metrics.get(metric, 0.0)
                    if metric_value > best_metric:
                        best_metric = metric_value
                        best_version = int(model_version.version)
                except Exception:
                    continue

            if best_version:
                print(f"✓ Best model: v{best_version} ({metric}={best_metric:.4f})")

            return best_version
        except Exception as e:
            print(f"✗ Failed to find best model: {e}")
            return None
