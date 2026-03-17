"""
Ray Compute Python SDK
Convenient Python interface for job submission and monitoring
"""

import requests
from typing import Dict, List, Optional, Any
from enum import Enum
import json
import time


class JobType(str, Enum):
    TRAINING = "training"
    INFERENCE = "inference"
    DATASET_CURATION = "dataset_curation"
    PIPELINE = "pipeline"
    CUSTOM = "custom"


class RayComputeClient:
    """Client for interacting with Ray Compute API"""

    def __init__(self, base_url: str = "http://localhost:8266"):
        self.base_url = base_url
        self.session = requests.Session()

    def submit_job(
        self,
        name: str,
        code: str,
        job_type: JobType = JobType.CUSTOM,
        cpu: int = 4,
        memory_gb: int = 8,
        gpu: int = 0,
        timeout_minutes: int = 120,
        mlflow_experiment: Optional[str] = None,
        mlflow_tags: Optional[Dict[str, str]] = None,
        env_vars: Optional[Dict[str, str]] = None,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Submit a job to the cluster

        Args:
            name: Job name
            code: Python code to execute
            job_type: Type of job
            cpu: Number of CPU cores
            memory_gb: Memory in GB
            gpu: Number of GPUs (0 or 1)
            timeout_minutes: Job timeout
            mlflow_experiment: MLflow experiment name
            mlflow_tags: Tags for MLflow run
            env_vars: Environment variables
            arguments: Job arguments

        Returns:
            job_id: Unique job identifier
        """
        payload = {
            "name": name,
            "job_type": job_type.value,
            "code": code,
            "requirements": {
                "cpu": cpu,
                "memory_gb": memory_gb,
                "gpu": gpu,
                "timeout_minutes": timeout_minutes,
            },
            "mlflow_experiment": mlflow_experiment,
            "mlflow_tags": mlflow_tags or {},
            "env_vars": env_vars or {},
            "arguments": arguments or {},
        }

        response = self.session.post(f"{self.base_url}/jobs/submit", json=payload)
        response.raise_for_status()

        result = response.json()
        return result["job_id"]

    def get_job(self, job_id: str) -> Dict[str, Any]:
        """Get job information"""
        response = self.session.get(f"{self.base_url}/jobs/{job_id}")
        response.raise_for_status()
        return response.json()

    def list_jobs(
        self,
        status: Optional[str] = None,
        job_type: Optional[JobType] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List jobs with optional filtering"""
        params = {"limit": limit}
        if status:
            params["status"] = status
        if job_type:
            params["job_type"] = job_type.value

        response = self.session.get(f"{self.base_url}/jobs", params=params)
        response.raise_for_status()
        return response.json()

    def get_logs(self, job_id: str) -> str:
        """Get job logs"""
        response = self.session.get(f"{self.base_url}/jobs/{job_id}/logs")
        response.raise_for_status()
        return response.json()["logs"]

    def cancel_job(self, job_id: str) -> Dict[str, Any]:
        """Cancel a running job"""
        response = self.session.post(f"{self.base_url}/jobs/{job_id}/cancel")
        response.raise_for_status()
        return response.json()

    def delete_job(self, job_id: str) -> Dict[str, Any]:
        """Delete a job"""
        response = self.session.delete(f"{self.base_url}/jobs/{job_id}")
        response.raise_for_status()
        return response.json()

    def get_resources(self) -> Dict[str, Any]:
        """Get cluster resource information"""
        response = self.session.get(f"{self.base_url}/resources")
        response.raise_for_status()
        return response.json()

    def wait_for_job(
        self, job_id: str, timeout: Optional[int] = None, poll_interval: int = 5
    ) -> Dict[str, Any]:
        """
        Wait for job to complete

        Args:
            job_id: Job ID
            timeout: Maximum wait time in seconds (None = infinite)
            poll_interval: Polling interval in seconds

        Returns:
            Final job information
        """
        start_time = time.time()

        while True:
            job = self.get_job(job_id)
            status = job["status"]

            if status in ["SUCCEEDED", "FAILED", "STOPPED"]:
                return job

            if timeout and (time.time() - start_time) > timeout:
                raise TimeoutError(
                    f"Job {job_id} did not complete within {timeout} seconds"
                )

            time.sleep(poll_interval)


# Convenience functions
def submit_training_job(
    name: str,
    code: str,
    gpu: bool = True,
    mlflow_experiment: Optional[str] = None,
    **kwargs,
) -> str:
    """Submit a training job with sensible defaults"""
    client = RayComputeClient()
    return client.submit_job(
        name=name,
        code=code,
        job_type=JobType.TRAINING,
        cpu=8,
        memory_gb=8,
        gpu=1 if gpu else 0,
        timeout_minutes=240,
        mlflow_experiment=mlflow_experiment,
        **kwargs,
    )


def submit_inference_job(name: str, code: str, gpu: bool = True, **kwargs) -> str:
    """Submit an inference job with sensible defaults"""
    client = RayComputeClient()
    return client.submit_job(
        name=name,
        code=code,
        job_type=JobType.INFERENCE,
        cpu=4,
        memory_gb=4,
        gpu=1 if gpu else 0,
        timeout_minutes=60,
        **kwargs,
    )


def submit_dataset_curation_job(name: str, code: str, **kwargs) -> str:
    """Submit a dataset curation job (CPU-only)"""
    client = RayComputeClient()
    return client.submit_job(
        name=name,
        code=code,
        job_type=JobType.DATASET_CURATION,
        cpu=12,
        memory_gb=6,
        gpu=0,
        timeout_minutes=180,
        **kwargs,
    )
