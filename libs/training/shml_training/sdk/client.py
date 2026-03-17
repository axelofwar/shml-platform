"""
SHML Training SDK - Remote Training Client
License: Apache 2.0

Simple and powerful client for remote training via SHML Platform API.
"""

import os
import json
import time
from typing import Optional, Dict, Any, List, Iterator
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime

try:
    import requests
except ImportError:
    raise ImportError(
        "requests is required for the SDK. Install with: pip install requests"
    )


# ==================== Data Models ====================


@dataclass
class TrainingConfig:
    """Training configuration for job submission"""

    # Required
    name: str
    model: str  # yolov8n, yolov8s, yolov8m, yolov8l, yolov8x
    dataset: str  # wider_face, custom_gcs, custom_s3, custom_http

    # Optional
    description: Optional[str] = None
    dataset_url: Optional[str] = None

    # Hyperparameters
    epochs: int = 100
    batch_size: int = 16
    learning_rate: float = 0.01
    optimizer: str = "SGD"
    momentum: float = 0.937
    weight_decay: float = 0.0005
    warmup_epochs: int = 3
    patience: int = 50
    imgsz: int = 640
    augment: bool = True

    # Proprietary techniques (Pro/Enterprise only)
    use_sapo: bool = False
    use_advantage_filter: bool = False
    use_curriculum_learning: bool = False

    # Compute resources
    gpu_fraction: float = 0.25
    cpu_cores: int = 4
    memory_gb: int = 8
    timeout_hours: int = 24
    priority: str = "normal"  # low, normal, high

    # MLflow integration
    mlflow_experiment: Optional[str] = None
    mlflow_tags: Optional[Dict[str, str]] = None
    enable_mlflow_callback: bool = True
    enable_prometheus_callback: bool = True

    def to_api_format(self) -> Dict[str, Any]:
        """Convert to API request format"""
        techniques = []

        if self.use_sapo:
            techniques.append({"name": "sapo", "enabled": True, "config": {}})

        if self.use_advantage_filter:
            techniques.append(
                {"name": "advantage_filter", "enabled": True, "config": {}}
            )

        if self.use_curriculum_learning:
            techniques.append(
                {"name": "curriculum_learning", "enabled": True, "config": {}}
            )

        return {
            "name": self.name,
            "description": self.description,
            "model": self.model,
            "dataset": self.dataset,
            "dataset_url": self.dataset_url,
            "hyperparameters": {
                "epochs": self.epochs,
                "batch_size": self.batch_size,
                "learning_rate": self.learning_rate,
                "optimizer": self.optimizer,
                "momentum": self.momentum,
                "weight_decay": self.weight_decay,
                "warmup_epochs": self.warmup_epochs,
                "patience": self.patience,
                "imgsz": self.imgsz,
                "augment": self.augment,
            },
            "techniques": techniques,
            "compute": {
                "gpu_fraction": self.gpu_fraction,
                "cpu_cores": self.cpu_cores,
                "memory_gb": self.memory_gb,
                "timeout_hours": self.timeout_hours,
                "priority": self.priority,
            },
            "mlflow_experiment": self.mlflow_experiment,
            "mlflow_tags": self.mlflow_tags or {},
            "enable_mlflow_callback": self.enable_mlflow_callback,
            "enable_prometheus_callback": self.enable_prometheus_callback,
        }


@dataclass
class JobStatus:
    """Training job status"""

    job_id: str
    ray_job_id: str
    name: str
    status: str  # PENDING, RUNNING, SUCCEEDED, FAILED, CANCELLED
    created_at: str
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration_seconds: Optional[float] = None

    # Progress
    current_epoch: Optional[int] = None
    total_epochs: Optional[int] = None
    progress_percent: Optional[float] = None

    # Metrics
    latest_metrics: Optional[Dict[str, Any]] = None

    # MLflow
    mlflow_run_id: Optional[str] = None
    mlflow_experiment: Optional[str] = None

    # Resources
    gpu_hours_used: Optional[float] = None
    cpu_hours_used: Optional[float] = None

    # Error
    error: Optional[str] = None

    def is_running(self) -> bool:
        return self.status in ["PENDING", "RUNNING"]

    def is_complete(self) -> bool:
        return self.status in ["SUCCEEDED", "FAILED", "CANCELLED"]

    def is_successful(self) -> bool:
        return self.status == "SUCCEEDED"


@dataclass
class QueueStatus:
    """Queue status for a job"""

    job_id: str
    status: str
    priority_score: float
    queue_position: Optional[int]
    queued_at: str
    started_at: Optional[str]
    estimated_start_time: Optional[str]


@dataclass
class QuotaInfo:
    """User quota information"""

    tier: str
    tier_name: str
    period: str  # day or month

    gpu_used: float
    gpu_limit: float
    gpu_remaining: float

    cpu_used: float
    cpu_limit: float
    cpu_remaining: float

    concurrent_jobs: int
    concurrent_jobs_limit: int

    percent_used: float


# ==================== Exceptions ====================


class SDKError(Exception):
    """Base exception for SDK errors"""

    pass


class AuthError(SDKError):
    """Authentication/authorization error"""

    pass


class APIError(SDKError):
    """API request error"""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response: Optional[Dict] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class JobError(SDKError):
    """Job execution error"""

    pass


class QuotaError(SDKError):
    """Quota exceeded error"""

    pass


# ==================== Training Client ====================


class TrainingClient:
    """
    Remote training client for SHML Platform

    Usage:
        # Initialize with API key
        client = TrainingClient(
            api_url="https://api.shml.ai",
            api_key="your-api-key"
        )

        # Or load from credentials file
        client = TrainingClient.from_credentials()

        # Submit training job
        config = TrainingConfig(
            name="face-detection-v1",
            model="yolov8l",
            dataset="wider_face",
            epochs=100,
            use_curriculum_learning=True
        )

        job_id = client.submit_training(config)

        # Monitor progress
        while True:
            status = client.get_job_status(job_id)
            print(f"Progress: {status.progress_percent}%")

            if status.is_complete():
                break

            time.sleep(10)

        # Download trained model
        client.download_artifacts(job_id, "./models/")
    """

    def __init__(
        self,
        api_url: str = "http://localhost",
        api_key: Optional[str] = None,
        timeout: int = 30,
        verify_ssl: bool = True,
    ):
        """
        Initialize training client

        Args:
            api_url: Base URL of SHML Platform API
            api_key: API key for authentication
            timeout: Request timeout in seconds
            verify_ssl: Verify SSL certificates
        """
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key or os.getenv("SHML_API_KEY")
        self.timeout = timeout
        self.verify_ssl = verify_ssl

        if not self.api_key:
            raise AuthError(
                "API key required. Provide via api_key parameter or SHML_API_KEY environment variable."
            )

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )

    @classmethod
    def from_credentials(
        cls, credentials_path: Optional[str] = None
    ) -> "TrainingClient":
        """
        Load client from credentials file

        Args:
            credentials_path: Path to credentials file (default: ~/.shml/credentials)

        Returns:
            TrainingClient instance
        """
        if credentials_path is None:
            credentials_path = os.path.expanduser("~/.shml/credentials")

        if not os.path.exists(credentials_path):
            raise AuthError(f"Credentials file not found: {credentials_path}")

        with open(credentials_path) as f:
            creds = json.load(f)

        return cls(
            api_url=creds.get("api_url", "http://localhost"),
            api_key=creds.get("api_key"),
            verify_ssl=creds.get("verify_ssl", True),
        )

    def _request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """Make API request with error handling"""
        url = f"{self.api_url}{endpoint}"

        try:
            response = self.session.request(
                method, url, timeout=self.timeout, verify=self.verify_ssl, **kwargs
            )

            if response.status_code == 401:
                raise AuthError("Invalid API key or expired token")

            if response.status_code == 403:
                raise AuthError("Insufficient permissions")

            if response.status_code == 429:
                error_data = response.json()
                raise QuotaError(
                    error_data.get("detail", {}).get("message", "Quota exceeded")
                )

            if response.status_code >= 400:
                try:
                    error_data = response.json()
                    message = error_data.get("detail", str(error_data))
                except:
                    message = response.text

                raise APIError(
                    f"API request failed: {message}",
                    status_code=response.status_code,
                    response=error_data if "error_data" in locals() else None,
                )

            return response

        except requests.exceptions.Timeout:
            raise APIError(f"Request timeout after {self.timeout}s")
        except requests.exceptions.ConnectionError as e:
            raise APIError(f"Connection error: {e}")

    # ==================== Training Job Submission ====================

    def submit_training(self, config: TrainingConfig) -> str:
        """
        Submit training job

        Args:
            config: Training configuration

        Returns:
            job_id: Job ID for tracking
        """
        response = self._request(
            "POST", "/api/v1/training/jobs", json=config.to_api_format()
        )

        data = response.json()
        return data["job_id"]

    def get_job_status(self, job_id: str) -> JobStatus:
        """Get current job status with metrics"""
        response = self._request("GET", f"/api/v1/training/jobs/{job_id}")

        data = response.json()
        return JobStatus(**data)

    def get_job_logs(self, job_id: str, tail: int = 100) -> str:
        """
        Get job logs

        Args:
            job_id: Job ID
            tail: Number of lines to return (default: 100)

        Returns:
            Log content as string
        """
        response = self._request(
            "GET", f"/api/v1/training/jobs/{job_id}/logs", params={"tail": tail}
        )

        data = response.json()
        return data.get("logs", "")

    def cancel_job(self, job_id: str) -> None:
        """Cancel a running job"""
        self._request("DELETE", f"/api/v1/training/jobs/{job_id}")

    def wait_for_completion(
        self, job_id: str, poll_interval: int = 10, verbose: bool = True
    ) -> JobStatus:
        """
        Wait for job to complete

        Args:
            job_id: Job ID
            poll_interval: Polling interval in seconds
            verbose: Print progress updates

        Returns:
            Final JobStatus
        """
        if verbose:
            print(f"Waiting for job {job_id} to complete...")

        last_progress = None

        while True:
            status = self.get_job_status(job_id)

            if verbose and status.progress_percent != last_progress:
                if status.progress_percent is not None:
                    print(
                        f"Progress: {status.progress_percent:.1f}% (Epoch {status.current_epoch}/{status.total_epochs})"
                    )
                    last_progress = status.progress_percent

            if status.is_complete():
                if verbose:
                    if status.is_successful():
                        print(f"✓ Job completed successfully!")
                        if status.latest_metrics:
                            print(f"  Final metrics: {status.latest_metrics}")
                    else:
                        print(f"✗ Job failed: {status.error}")

                return status

            time.sleep(poll_interval)

    # ==================== Queue Management ====================

    def get_queue_status(self, job_id: str) -> QueueStatus:
        """Get job's position in queue"""
        response = self._request("GET", f"/api/v1/training/queue/{job_id}")

        data = response.json()
        return QueueStatus(**data)

    def get_queue_overview(self) -> Dict[str, Any]:
        """Get queue overview with stats"""
        response = self._request("GET", "/api/v1/training/queue")

        return response.json()

    # ==================== Quota Management ====================

    def get_quota(self, period: str = "day") -> QuotaInfo:
        """
        Get quota information

        Args:
            period: "day" or "month"

        Returns:
            QuotaInfo with usage details
        """
        response = self._request(
            "GET", "/api/v1/training/quota", params={"period": period}
        )

        data = response.json()
        return QuotaInfo(
            tier=data["user"]["tier"],
            tier_name=data["user"]["tier_name"],
            period=data["period"],
            gpu_used=data["gpu"]["used"],
            gpu_limit=data["gpu"]["limit"],
            gpu_remaining=data["gpu"]["remaining"],
            cpu_used=data["cpu"]["used"],
            cpu_limit=data["cpu"]["limit"],
            cpu_remaining=data["cpu"]["remaining"],
            concurrent_jobs=data["concurrent_jobs"]["current"],
            concurrent_jobs_limit=data["concurrent_jobs"]["limit"],
            percent_used=data["percent_used"],
        )

    # ==================== Model & Dataset Management ====================

    def list_models(self) -> List[Dict[str, Any]]:
        """List available model architectures"""
        response = self._request("GET", "/api/v1/training/models")

        return response.json()["models"]

    def list_techniques(self) -> List[Dict[str, Any]]:
        """List available proprietary techniques"""
        response = self._request("GET", "/api/v1/training/techniques")

        return response.json()["techniques"]

    def list_tiers(self) -> List[Dict[str, Any]]:
        """List subscription tiers and limits"""
        response = self._request("GET", "/api/v1/training/tiers")

        return response.json()["tiers"]

    # ==================== Convenience Methods ====================

    def submit_and_wait(
        self, config: TrainingConfig, poll_interval: int = 10, verbose: bool = True
    ) -> JobStatus:
        """
        Submit job and wait for completion

        Convenience method that combines submit_training() and wait_for_completion()
        """
        job_id = self.submit_training(config)

        if verbose:
            print(f"Job submitted: {job_id}")

        return self.wait_for_completion(job_id, poll_interval, verbose)

    def quick_train(
        self,
        name: str,
        model: str = "yolov8l",
        epochs: int = 100,
        use_techniques: bool = True,
        **kwargs,
    ) -> str:
        """
        Quick training job submission with sensible defaults

        Args:
            name: Job name
            model: Model architecture (default: yolov8l)
            epochs: Number of epochs (default: 100)
            use_techniques: Enable all proprietary techniques (default: True)
            **kwargs: Additional config parameters

        Returns:
            job_id
        """
        config = TrainingConfig(
            name=name,
            model=model,
            dataset="wider_face",
            epochs=epochs,
            use_sapo=use_techniques,
            use_advantage_filter=use_techniques,
            use_curriculum_learning=use_techniques,
            **kwargs,
        )

        return self.submit_training(config)


# ==================== Helper Functions ====================


def save_credentials(
    api_url: str, api_key: str, credentials_path: Optional[str] = None
) -> None:
    """
    Save credentials to file

    Args:
        api_url: API base URL
        api_key: API key
        credentials_path: Path to save credentials (default: ~/.shml/credentials)
    """
    if credentials_path is None:
        credentials_path = os.path.expanduser("~/.shml/credentials")

    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(credentials_path), exist_ok=True)

    creds = {
        "api_url": api_url,
        "api_key": api_key,
        "verify_ssl": True,
    }

    with open(credentials_path, "w") as f:
        json.dump(creds, f, indent=2)

    # Set secure permissions (Unix only)
    try:
        os.chmod(credentials_path, 0o600)
    except:
        pass

    print(f"Credentials saved to {credentials_path}")
