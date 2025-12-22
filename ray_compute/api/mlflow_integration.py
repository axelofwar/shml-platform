"""
Automatic MLflow Integration for Ray Jobs
This module provides automatic MLflow tracking for all Ray compute jobs with opt-out capability.
"""

import os
import mlflow
from functools import wraps
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class MLflowAutoLogger:
    """
    Automatic MLflow logger for Ray jobs

    Features:
    - Automatically initializes MLflow tracking
    - Logs job metadata, parameters, and metrics
    - Supports opt-out via environment variable
    - Handles errors gracefully to not break jobs
    """

    def __init__(self):
        self.enabled = os.getenv("DISABLE_MLFLOW_LOGGING", "false").lower() != "true"
        self.tracking_uri = os.getenv(
            "MLFLOW_TRACKING_URI", "http://mlflow-server:5000"
        )
        self.experiment_name = os.getenv("MLFLOW_EXPERIMENT_NAME", "Ray-Jobs")
        self._initialized = False

    def initialize(self, experiment_name: Optional[str] = None):
        """Initialize MLflow tracking"""
        if not self.enabled:
            logger.info("MLflow auto-logging is disabled (DISABLE_MLFLOW_LOGGING=true)")
            return

        if self._initialized:
            return

        try:
            # Set tracking URI
            mlflow.set_tracking_uri(self.tracking_uri)

            # Set or create experiment
            exp_name = experiment_name or self.experiment_name
            experiment = mlflow.get_experiment_by_name(exp_name)

            if experiment is None:
                experiment_id = mlflow.create_experiment(
                    name=exp_name,
                    tags={"source": "ray-compute", "auto_created": "true"},
                )
                logger.info(
                    f"Created MLflow experiment: {exp_name} (ID: {experiment_id})"
                )
            else:
                experiment_id = experiment.experiment_id

            mlflow.set_experiment(exp_name)
            self._initialized = True
            logger.info(
                f"MLflow tracking initialized: {self.tracking_uri}, experiment: {exp_name}"
            )

        except Exception as e:
            logger.error(f"Failed to initialize MLflow tracking: {e}")
            self.enabled = False

    def start_run(
        self, run_name: Optional[str] = None, tags: Optional[Dict[str, str]] = None
    ):
        """Start a new MLflow run"""
        if not self.enabled:
            return None

        try:
            self.initialize()

            run_tags = {"source": "ray-compute", "auto_logged": "true"}
            if tags:
                run_tags.update(tags)

            run = mlflow.start_run(run_name=run_name, tags=run_tags)
            logger.info(f"Started MLflow run: {run.info.run_id}")
            return run

        except Exception as e:
            logger.error(f"Failed to start MLflow run: {e}")
            return None

    def log_params(self, params: Dict[str, Any]):
        """Log parameters to MLflow"""
        if not self.enabled or not self._initialized:
            return

        try:
            mlflow.log_params(params)
            logger.debug(f"Logged {len(params)} parameters to MLflow")
        except Exception as e:
            logger.error(f"Failed to log parameters: {e}")

    def log_metrics(self, metrics: Dict[str, float], step: Optional[int] = None):
        """Log metrics to MLflow"""
        if not self.enabled or not self._initialized:
            return

        try:
            mlflow.log_metrics(metrics, step=step)
            logger.debug(f"Logged {len(metrics)} metrics to MLflow")
        except Exception as e:
            logger.error(f"Failed to log metrics: {e}")

    def log_artifact(self, local_path: str, artifact_path: Optional[str] = None):
        """Log artifact to MLflow"""
        if not self.enabled or not self._initialized:
            return

        try:
            mlflow.log_artifact(local_path, artifact_path)
            logger.debug(f"Logged artifact: {local_path}")
        except Exception as e:
            logger.error(f"Failed to log artifact: {e}")

    def end_run(self, status: str = "FINISHED"):
        """End the current MLflow run"""
        if not self.enabled or not self._initialized:
            return

        try:
            mlflow.end_run(status=status)
            logger.info(f"Ended MLflow run with status: {status}")
        except Exception as e:
            logger.error(f"Failed to end MLflow run: {e}")


# Global instance
_auto_logger = MLflowAutoLogger()


def auto_log_mlflow(
    experiment_name: Optional[str] = None,
    run_name: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
):
    """
    Decorator to automatically log Ray job execution to MLflow

    Usage:
        @auto_log_mlflow(experiment_name="MyExperiment", run_name="job-1")
        def my_ray_job(config):
            # Your job code here
            return results

    To disable MLflow logging for a specific job:
        Set environment variable: DISABLE_MLFLOW_LOGGING=true
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Check if MLflow logging is disabled
            if not _auto_logger.enabled:
                logger.info("Executing job without MLflow logging (disabled)")
                return func(*args, **kwargs)

            # Start MLflow run
            run = _auto_logger.start_run(run_name=run_name, tags=tags)

            try:
                # Log job configuration
                job_config = {
                    "function": func.__name__,
                    "module": func.__module__,
                }

                # Extract parameters from kwargs if available
                if "config" in kwargs:
                    job_config.update(kwargs["config"])
                elif len(args) > 0 and isinstance(args[0], dict):
                    job_config.update(args[0])

                _auto_logger.log_params(job_config)

                # Execute the job
                result = func(*args, **kwargs)

                # Log results if they're dict-like
                if isinstance(result, dict):
                    metrics = {
                        k: v for k, v in result.items() if isinstance(v, (int, float))
                    }
                    if metrics:
                        _auto_logger.log_metrics(metrics)

                _auto_logger.end_run(status="FINISHED")
                return result

            except Exception as e:
                logger.error(f"Job execution failed: {e}")
                _auto_logger.end_run(status="FAILED")
                raise

        return wrapper

    return decorator


def get_auto_logger() -> MLflowAutoLogger:
    """Get the global MLflow auto-logger instance"""
    return _auto_logger


def is_mlflow_enabled() -> bool:
    """Check if MLflow auto-logging is enabled"""
    return _auto_logger.enabled


# Convenience functions
def log_job_start(job_name: str, config: Dict[str, Any]):
    """Log the start of a Ray job"""
    _auto_logger.initialize()
    _auto_logger.start_run(run_name=job_name, tags={"job_name": job_name})
    _auto_logger.log_params(config)


def log_job_metrics(metrics: Dict[str, float], step: Optional[int] = None):
    """Log metrics during job execution"""
    _auto_logger.log_metrics(metrics, step=step)


def log_job_artifact(artifact_path: str, artifact_name: Optional[str] = None):
    """Log an artifact from the job"""
    _auto_logger.log_artifact(artifact_path, artifact_name)


def log_job_end(status: str = "FINISHED"):
    """Log the end of a Ray job"""
    _auto_logger.end_run(status=status)


# ============================================================================
# REST API Client for Server-Side MLflow Integration
# ============================================================================
# The functions below use REST API calls instead of the mlflow Python package
# This allows the Ray Compute API server to create/update MLflow runs
# without requiring the mlflow package in the container.

import httpx
from datetime import datetime
from typing import Tuple

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow-nginx:80")


class MLflowRESTClient:
    """Simple MLflow REST API client for server-side job tracking integration."""

    def __init__(self, tracking_uri: str = None):
        self.tracking_uri = tracking_uri or MLFLOW_TRACKING_URI
        self._client = httpx.Client(timeout=30.0)

    def _api_call(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make an API call to MLflow tracking server."""
        url = f"{self.tracking_uri}/api/2.0/mlflow{endpoint}"
        try:
            if method == "GET":
                response = self._client.get(url, params=kwargs.get("params", {}))
            elif method == "POST":
                response = self._client.post(url, json=kwargs.get("json", {}))
            else:
                raise ValueError(f"Unsupported method: {method}")

            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"MLflow API error: {e.response.status_code} - {e.response.text}"
            )
            raise
        except Exception as e:
            logger.error(f"MLflow API call failed: {e}")
            raise

    def get_or_create_experiment(self, name: str) -> str:
        """Get existing experiment by name or create a new one."""
        # First, try to get by name
        try:
            response = self._api_call(
                "GET", "/experiments/get-by-name", params={"experiment_name": name}
            )
            experiment_id = response.get("experiment", {}).get("experiment_id")
            if experiment_id:
                logger.info(
                    f"Found existing MLflow experiment '{name}' with ID {experiment_id}"
                )
                return experiment_id
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404:
                raise
            # Experiment doesn't exist, create it

        # Create new experiment
        response = self._api_call("POST", "/experiments/create", json={"name": name})
        experiment_id = response.get("experiment_id")
        logger.info(f"Created new MLflow experiment '{name}' with ID {experiment_id}")
        return experiment_id

    def create_run(
        self,
        experiment_id: str,
        run_name: str,
        tags: Optional[Dict[str, str]] = None,
    ) -> str:
        """Create a new MLflow run."""
        run_tags = [
            {"key": "mlflow.runName", "value": run_name},
            {"key": "mlflow.source.type", "value": "JOB"},
            {"key": "mlflow.source.name", "value": "ray-compute-api"},
        ]

        if tags:
            for key, value in tags.items():
                run_tags.append({"key": key, "value": str(value)})

        response = self._api_call(
            "POST",
            "/runs/create",
            json={
                "experiment_id": experiment_id,
                "start_time": int(datetime.utcnow().timestamp() * 1000),
                "tags": run_tags,
            },
        )

        run_id = response.get("run", {}).get("info", {}).get("run_id")
        logger.info(f"Created MLflow run {run_id} in experiment {experiment_id}")
        return run_id

    def log_params(self, run_id: str, params: Dict[str, Any]) -> None:
        """Log parameters to an MLflow run."""
        param_list = []
        for key, value in params.items():
            if value is not None:
                param_list.append({"key": key, "value": str(value)[:500]})

        if param_list:
            self._api_call(
                "POST",
                "/runs/log-batch",
                json={
                    "run_id": run_id,
                    "params": param_list,
                },
            )
            logger.debug(f"Logged {len(param_list)} params to run {run_id}")

    def log_metrics_batch(
        self, run_id: str, metrics: Dict[str, float], step: int = 0
    ) -> None:
        """Log metrics to an MLflow run."""
        timestamp = int(datetime.utcnow().timestamp() * 1000)
        metric_list = []
        for key, value in metrics.items():
            if value is not None and isinstance(value, (int, float)):
                metric_list.append(
                    {
                        "key": key,
                        "value": float(value),
                        "timestamp": timestamp,
                        "step": step,
                    }
                )

        if metric_list:
            self._api_call(
                "POST",
                "/runs/log-batch",
                json={
                    "run_id": run_id,
                    "metrics": metric_list,
                },
            )
            logger.debug(f"Logged {len(metric_list)} metrics to run {run_id}")

    def set_tag(self, run_id: str, key: str, value: str) -> None:
        """Set a tag on an MLflow run."""
        self._api_call(
            "POST",
            "/runs/set-tag",
            json={
                "run_id": run_id,
                "key": key,
                "value": str(value)[:5000],
            },
        )

    def update_run_status(
        self, run_id: str, status: str, end_time: Optional[datetime] = None
    ) -> None:
        """Update the status of an MLflow run."""
        # Map Ray job status to MLflow run status
        status_map = {
            "PENDING": "SCHEDULED",
            "RUNNING": "RUNNING",
            "SUCCEEDED": "FINISHED",
            "COMPLETED": "FINISHED",
            "FAILED": "FAILED",
            "STOPPED": "KILLED",
            "CANCELLED": "KILLED",
        }
        mlflow_status = status_map.get(status.upper(), "RUNNING")

        payload = {
            "run_id": run_id,
            "status": mlflow_status,
        }

        if end_time:
            payload["end_time"] = int(end_time.timestamp() * 1000)
        elif mlflow_status in ("FINISHED", "FAILED", "KILLED"):
            payload["end_time"] = int(datetime.utcnow().timestamp() * 1000)

        self._api_call("POST", "/runs/update", json=payload)
        logger.info(f"Updated MLflow run {run_id} status to {mlflow_status}")

    def close(self):
        """Close the HTTP client."""
        self._client.close()


# Global REST client instance
_rest_client: Optional[MLflowRESTClient] = None


def get_mlflow_rest_client() -> MLflowRESTClient:
    """Get or create the global MLflow REST client instance."""
    global _rest_client
    if _rest_client is None:
        _rest_client = MLflowRESTClient()
    return _rest_client


async def create_mlflow_run_for_job(
    experiment_name: str,
    job_id: str,
    job_name: str,
    user: str,
    job_type: str,
    job_params: Dict[str, Any],
) -> Tuple[str, str]:
    """
    Create an MLflow run for a Ray job (server-side, uses REST API).

    Args:
        experiment_name: Name of the MLflow experiment
        job_id: Ray job ID
        job_name: Human-readable job name
        user: Username who submitted the job
        job_type: Type of job (training, inference, etc.)
        job_params: Job parameters to log

    Returns:
        Tuple of (experiment_id, run_id)
    """
    client = get_mlflow_rest_client()

    try:
        # Get or create experiment
        experiment_id = client.get_or_create_experiment(experiment_name)

        # Create run with tags
        tags = {
            "ray.job_id": job_id,
            "ray.job_type": job_type,
            "ray.user": user,
            "mlflow.note.content": f"Ray job: {job_name}\nSubmitted by: {user}",
        }

        run_id = client.create_run(
            experiment_id=experiment_id,
            run_name=job_name,
            tags=tags,
        )

        # Log job parameters
        params_to_log = {
            "job_id": job_id,
            "job_name": job_name,
            "job_type": job_type,
            "user": user,
            **{k: v for k, v in job_params.items() if v is not None},
        }
        client.log_params(run_id, params_to_log)

        logger.info(
            f"Created MLflow run {run_id} for job {job_id} in experiment {experiment_name}"
        )
        return experiment_id, run_id

    except Exception as e:
        logger.error(f"Failed to create MLflow run for job {job_id}: {e}")
        raise


async def update_mlflow_run_for_job(
    run_id: str,
    status: str,
    metrics: Optional[Dict[str, float]] = None,
    end_time: Optional[datetime] = None,
    error_message: Optional[str] = None,
) -> None:
    """
    Update an MLflow run when job status changes (server-side, uses REST API).

    Args:
        run_id: MLflow run ID
        status: New job status
        metrics: Optional metrics to log
        end_time: Optional end time
        error_message: Optional error message for failed jobs
    """
    if not run_id:
        return

    client = get_mlflow_rest_client()

    try:
        # Log any metrics
        if metrics:
            client.log_metrics_batch(run_id, metrics)

        # Set error message as tag if present
        if error_message:
            client.set_tag(run_id, "ray.error_message", error_message[:5000])

        # Update run status
        client.update_run_status(run_id, status, end_time)

        logger.info(f"Updated MLflow run {run_id} with status {status}")

    except Exception as e:
        logger.error(f"Failed to update MLflow run {run_id}: {e}")
        # Don't raise - MLflow update failure shouldn't fail the job


def is_mlflow_server_available() -> bool:
    """Check if MLflow tracking server is available."""
    try:
        client = get_mlflow_rest_client()
        response = client._client.get(f"{client.tracking_uri}/health")
        return response.status_code == 200
    except Exception:
        return False
