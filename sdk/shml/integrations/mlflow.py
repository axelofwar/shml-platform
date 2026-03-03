"""
MLflow Integration Client
==========================

Handles experiment setup, metric logging, model registry, and the
Ultralytics MLflow URI conflict.
"""

from __future__ import annotations

import os
import time
from typing import Any

from shml.config import PlatformConfig
from shml.exceptions import MLflowError


class MLflowClient:
    """Thin wrapper around mlflow that manages URI lifecycle.

    Solves the Ultralytics conflict: YOLO's built-in MLflow integration
    reads MLFLOW_TRACKING_URI and tries to log to a local file store.
    This client blanks the URI during model.train() and restores it for
    our own logging.
    """

    def __init__(self, config: PlatformConfig | None = None):
        self._config = config or PlatformConfig.from_env()
        self._uri = self._config.mlflow_uri
        self._run_id: str | None = None
        self._experiment_id: str | None = None
        self._mlflow: Any = None  # Lazy import

    def _import_mlflow(self) -> Any:
        if self._mlflow is None:
            try:
                import mlflow

                self._mlflow = mlflow
            except ImportError:
                raise MLflowError(
                    "mlflow package not installed. Install with: pip install mlflow"
                )
        return self._mlflow

    @property
    def run_id(self) -> str | None:
        return self._run_id

    @property
    def experiment_id(self) -> str | None:
        return self._experiment_id

    def setup_experiment(
        self,
        experiment_name: str,
        run_name: str,
        tags: dict[str, str] | None = None,
    ) -> str | None:
        """Create/get experiment and start a run.

        Returns the run_id or None on failure.
        """
        mlflow = self._import_mlflow()
        try:
            mlflow.set_tracking_uri(self._uri)
            mlflow.set_experiment(experiment_name)
            self._experiment_id = mlflow.get_experiment_by_name(
                experiment_name
            ).experiment_id

            run = mlflow.start_run(run_name=run_name, tags=tags)
            self._run_id = run.info.run_id
            return self._run_id
        except Exception as e:
            raise MLflowError(f"Failed to setup experiment: {e}")

    def log_params(self, params: dict[str, Any]) -> None:
        """Log parameters to the active run."""
        mlflow = self._import_mlflow()
        if not self._run_id:
            return
        try:
            self._ensure_tracking_uri()
            mlflow.log_params({k: str(v)[:250] for k, v in params.items()})
        except Exception as e:
            raise MLflowError(f"Failed to log params: {e}")

    def log_metric(self, key: str, value: float, step: int | None = None) -> None:
        """Log a single metric to the active run."""
        mlflow = self._import_mlflow()
        if not self._run_id:
            return
        try:
            self._ensure_tracking_uri()
            mlflow.log_metric(key, value, step=step)
        except Exception as e:
            # Metrics logging is non-fatal during training
            pass

    def log_metrics(self, metrics: dict[str, float], step: int | None = None) -> None:
        """Log multiple metrics to the active run."""
        mlflow = self._import_mlflow()
        if not self._run_id:
            return
        try:
            self._ensure_tracking_uri()
            mlflow.log_metrics(metrics, step=step)
        except Exception:
            pass

    def log_artifact(self, local_path: str, artifact_path: str | None = None) -> None:
        """Log a file artifact."""
        mlflow = self._import_mlflow()
        if not self._run_id:
            return
        try:
            self._ensure_tracking_uri()
            mlflow.log_artifact(local_path, artifact_path)
        except Exception as e:
            raise MLflowError(f"Failed to log artifact: {e}")

    def register_model(self, model_uri: str, name: str) -> Any:
        """Register a model in the MLflow model registry."""
        mlflow = self._import_mlflow()
        try:
            self._ensure_tracking_uri()
            return mlflow.register_model(model_uri, name)
        except Exception as e:
            raise MLflowError(f"Failed to register model: {e}")

    def end_run(self, status: str = "FINISHED") -> None:
        """End the active MLflow run."""
        mlflow = self._import_mlflow()
        if not self._run_id:
            return
        try:
            self._ensure_tracking_uri()
            mlflow.end_run(status)
        except Exception:
            pass
        finally:
            self._run_id = None

    def suppress_for_ultralytics(self) -> str:
        """Blank MLFLOW_TRACKING_URI to prevent Ultralytics conflict.

        Returns the original URI so it can be restored.
        Must be called BEFORE model.train().
        """
        original = os.environ.get("MLFLOW_TRACKING_URI", "")
        os.environ["MLFLOW_TRACKING_URI"] = ""
        return original

    def restore_after_ultralytics(self, original_uri: str = "") -> None:
        """Restore MLFLOW_TRACKING_URI after model.train() completes."""
        os.environ["MLFLOW_TRACKING_URI"] = original_uri or self._uri
        mlflow = self._import_mlflow()
        mlflow.set_tracking_uri(self._uri)

    def _ensure_tracking_uri(self) -> None:
        """Ensure mlflow is pointing at our server, not Ultralytics file store."""
        mlflow = self._import_mlflow()
        current = str(mlflow.get_tracking_uri())
        if current != self._uri and "mlflow-nginx" not in current:
            mlflow.set_tracking_uri(self._uri)
