"""
MLflow Integration Callback
License: Apache 2.0

Callback for logging training metrics, parameters, and artifacts to MLflow.

Usage:
    from shml_training.integrations import MLflowCallback
    from shml_training.core import UltralyticsTrainer

    callback = MLflowCallback(
        tracking_uri="http://localhost:8080",
        experiment_name="face-detection",
        run_name="yolov8l-v1",
    )

    trainer = UltralyticsTrainer(
        config=config,
        callbacks=[callback],
    )

    results = trainer.train()
"""

import os
from typing import Dict, Any, Optional
from pathlib import Path

try:
    import mlflow

    MLFLOW_AVAILABLE = True
except ImportError:
    MLFLOW_AVAILABLE = False

from ..core.callbacks import TrainingCallback


class MLflowCallback(TrainingCallback):
    """
    MLflow tracking callback for training runs.

    Logs:
    - Run configuration and hyperparameters
    - Training and validation metrics per epoch
    - Checkpoints and model artifacts
    - Final model exports
    """

    def __init__(
        self,
        tracking_uri: Optional[str] = None,
        experiment_name: str = "training",
        run_name: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
        log_artifacts: bool = True,
        log_checkpoints: bool = True,
    ):
        """
        Initialize MLflow callback.

        Args:
            tracking_uri: MLflow tracking server URI
            experiment_name: MLflow experiment name
            run_name: MLflow run name (auto-generated if None)
            tags: Additional tags for the run
            log_artifacts: Whether to log model artifacts
            log_checkpoints: Whether to log checkpoints
        """
        if not MLFLOW_AVAILABLE:
            raise ImportError(
                "MLflow is not installed. Install with: pip install mlflow"
            )

        self.tracking_uri = tracking_uri
        self.experiment_name = experiment_name
        self.run_name = run_name
        self.tags = tags or {}
        self.log_artifacts = log_artifacts
        self.log_checkpoints = log_checkpoints

        self.run = None

        # Setup MLflow
        if self.tracking_uri:
            mlflow.set_tracking_uri(self.tracking_uri)
        mlflow.set_experiment(self.experiment_name)

        print(f"✅ MLflowCallback initialized")
        print(f"   Tracking URI: {tracking_uri or 'default'}")
        print(f"   Experiment: {experiment_name}")

    def on_run_start(self, trainer, config: Dict[str, Any]):
        """Start MLflow run and log configuration."""
        run_name = self.run_name or trainer.run_id

        self.run = mlflow.start_run(run_name=run_name, tags=self.tags)

        # Log all configuration parameters
        mlflow.log_params(
            {k: v for k, v in config.items() if isinstance(v, (int, float, str, bool))}
        )

        print(f"📝 MLflow run started: {self.run.info.run_id}")

    def on_epoch_end(self, trainer, epoch: int, metrics: Dict[str, Any]):
        """Log epoch metrics."""
        if self.run is None:
            return

        # Log all numeric metrics
        log_metrics = {k: v for k, v in metrics.items() if isinstance(v, (int, float))}

        mlflow.log_metrics(log_metrics, step=epoch)

    def on_validation_end(self, trainer, epoch: int, metrics: Dict[str, Any]):
        """Log validation metrics."""
        if self.run is None:
            return

        # Prefix validation metrics
        val_metrics = {
            f"val_{k}": v for k, v in metrics.items() if isinstance(v, (int, float))
        }

        mlflow.log_metrics(val_metrics, step=epoch)

    def on_checkpoint_saved(
        self, trainer, checkpoint_path: str, metrics: Dict[str, Any]
    ):
        """Log checkpoint artifact."""
        if self.run is None or not self.log_checkpoints:
            return

        checkpoint_path = Path(checkpoint_path)
        if checkpoint_path.exists():
            mlflow.log_artifact(str(checkpoint_path), "checkpoints")
            print(f"📝 Checkpoint logged to MLflow: {checkpoint_path.name}")

    def on_run_end(self, trainer, metrics: Dict[str, Any]):
        """End MLflow run and log final metrics."""
        if self.run is None:
            return

        # Log final metrics
        final_metrics = {
            f"final_{k}": v for k, v in metrics.items() if isinstance(v, (int, float))
        }
        mlflow.log_metrics(final_metrics)

        # Log artifacts if requested
        if self.log_artifacts and hasattr(trainer, "model"):
            # Try to log model directory
            checkpoint_dir = getattr(trainer.config, "checkpoint_dir", None)
            if checkpoint_dir and Path(checkpoint_dir).exists():
                mlflow.log_artifacts(checkpoint_dir, "model")

        mlflow.end_run()
        print(f"📝 MLflow run complete: {self.run.info.run_id}")
        self.run = None

    def on_error(self, trainer, error: Exception):
        """Mark MLflow run as failed."""
        if self.run is not None:
            mlflow.log_param("error", str(error)[:250])
            mlflow.end_run(status="FAILED")
            self.run = None


__all__ = ["MLflowCallback"]
