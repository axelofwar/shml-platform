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
    helper.promote_model_to_production("face-detection-yolov8l-p2", version=3)
"""

import os
import mlflow
from typing import Dict, Any, Optional, List
from pathlib import Path


class MLflowHelper:
    """Helper class for MLflow operations."""

    def __init__(
        self,
        tracking_uri: str = None,
        model_name: str = None,
    ):
        tracking_uri = tracking_uri or os.environ.get(
            "MLFLOW_TRACKING_URI", "http://mlflow-nginx:80"
        )
        self.default_model_name = model_name or os.environ.get(
            "MLFLOW_REGISTRY_MODEL_NAME", "face-detection-yolov8l-p2"
        )
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

    def load_model_from_registry(self, model_name: str, alias: str = "champion") -> str:
        """Load model from MLflow Model Registry by alias.

        Args:
            model_name: Registered model name.
            alias: Model alias, e.g. 'champion' or 'challenger'.

        Returns:
            Local path to downloaded model artifacts, or None on failure.
        """

        try:
            model_uri = f"models:/{model_name}@{alias}"
            model_path = mlflow.artifacts.download_artifacts(model_uri)

            print(f"✓ Loaded model: {model_name}@{alias}")
            return model_path
        except Exception as e:
            print(f"✗ Failed to load model: {e}")
            return None

    def promote_model_to_production(self, model_name: str, version: int):
        """Promote model version to Production using @champion alias.

        The previous champion (if any) is demoted to @challenger.
        """

        try:
            # Demote current champion to challenger
            try:
                current_champion = self.client.get_model_version_by_alias(
                    model_name, "champion"
                )
                if int(current_champion.version) != version:
                    self.client.set_registered_model_alias(
                        model_name, "challenger", current_champion.version
                    )
                    print(
                        f"✓ Demoted previous champion to @challenger: v{current_champion.version}"
                    )
            except Exception:
                pass  # No current champion

            # Assign @champion alias to new version
            self.client.set_registered_model_alias(model_name, "champion", version)

            print(f"✓ Promoted {model_name} v{version} to @champion")
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
        self, model_name: str, metric: str = "mAP50", alias: Optional[str] = None
    ) -> Optional[int]:
        """Get best model version by metric.

        Args:
            model_name: Registered model name.
            metric: Metric to rank by (default: mAP50).
            alias: If provided, return the version for this alias directly.

        Returns:
            Best version number, or None.
        """

        try:
            if alias:
                try:
                    mv = self.client.get_model_version_by_alias(model_name, alias)
                    print(f"✓ Alias @{alias} → v{mv.version}")
                    return int(mv.version)
                except Exception:
                    print(f"✗ No model found for alias @{alias}")
                    return None

            # Search all versions
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

    def auto_promote_if_qualified(
        self,
        run_id: str,
        model_name: str = None,
        mAP50_threshold: float = 0.94,
        recall_threshold: float = 0.95,
        precision_threshold: float = 0.90,
    ) -> bool:
        """Check final metrics of a run and auto-promote if qualified.

        Thresholds (defaults match PII KPI targets):
            - mAP50    > 0.94
            - recall   > 0.95
            - precision > 0.90

        If all thresholds are met the model is registered (if not already)
        and the ``@challenger`` alias is assigned.  A tag
        ``auto_promotion=challenger`` is set on the run.

        Args:
            run_id: MLflow run ID to evaluate.
            model_name: Registered model name (defaults to
                ``self.default_model_name``).
            mAP50_threshold: Minimum mAP50 value.
            recall_threshold: Minimum recall value.
            precision_threshold: Minimum precision value.

        Returns:
            True if the model was promoted, False otherwise.
        """
        model_name = model_name or self.default_model_name

        try:
            run = self.client.get_run(run_id)
            metrics = run.data.metrics

            mAP50 = metrics.get("mAP50", 0.0)
            recall = metrics.get("recall", 0.0)
            precision = metrics.get("precision", 0.0)

            qualified = (
                mAP50 > mAP50_threshold
                and recall > recall_threshold
                and precision > precision_threshold
            )

            print(
                f"  Auto-promote check: mAP50={mAP50:.4f} (>{mAP50_threshold}), "
                f"recall={recall:.4f} (>{recall_threshold}), "
                f"precision={precision:.4f} (>{precision_threshold}) → "
                f"{'QUALIFIED' if qualified else 'NOT QUALIFIED'}"
            )

            if not qualified:
                return False

            # Register the model from this run
            model_uri = f"runs:/{run_id}/model"
            mv = mlflow.register_model(model_uri, model_name)

            # Assign @challenger alias
            self.client.set_registered_model_alias(model_name, "challenger", mv.version)

            # Tag the run
            self.client.set_tag(run_id, "auto_promotion", "challenger")

            print(
                f"✓ Auto-promoted run {run_id[:8]}… as {model_name} "
                f"v{mv.version} @challenger"
            )
            return True

        except Exception as e:
            print(f"✗ Auto-promote failed: {e}")
            return False
