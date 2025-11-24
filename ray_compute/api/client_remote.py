"""
Remote Client SDK for Ray Compute
Submit jobs from remote machine and retrieve results
"""

import requests
import time
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Any
from enum import Enum
import json


class JobType(str, Enum):
    TRAINING = "training"
    INFERENCE = "inference"
    BENCHMARKING = "benchmarking"
    EVALUATION = "evaluation"
    DATASET_CURATION = "dataset_curation"
    PIPELINE = "pipeline"
    CUSTOM = "custom"


class RemoteComputeClient:
    """Client for remote job submission and result retrieval"""
    
    def __init__(self, server_url: str):
        """
        Initialize remote compute client
        
        Args:
            server_url: Server URL (e.g., "http://100.69.227.36:8266")
        """
        self.server_url = server_url.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
    
    def health_check(self) -> Dict[str, Any]:
        """Check if server is healthy"""
        response = self.session.get(f"{self.server_url}/health")
        response.raise_for_status()
        return response.json()
    
    def get_resources(self) -> Dict[str, Any]:
        """Get available cluster resources"""
        response = self.session.get(f"{self.server_url}/resources")
        response.raise_for_status()
        return response.json()
    
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
        return_artifacts: bool = True,
        cleanup_after: bool = True
    ) -> str:
        """
        Submit a job to remote cluster
        
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
            return_artifacts: Return artifacts to client
            cleanup_after: Delete artifacts after retrieval
        
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
                "timeout_minutes": timeout_minutes
            },
            "mlflow_experiment": mlflow_experiment,
            "mlflow_tags": mlflow_tags or {},
            "env_vars": env_vars or {},
            "return_artifacts": return_artifacts,
            "cleanup_after": cleanup_after
        }
        
        response = self.session.post(f"{self.server_url}/jobs/submit", json=payload)
        response.raise_for_status()
        
        result = response.json()
        return result["job_id"]
    
    def get_job(self, job_id: str) -> Dict[str, Any]:
        """Get job information"""
        response = self.session.get(f"{self.server_url}/jobs/{job_id}")
        response.raise_for_status()
        return response.json()
    
    def list_jobs(
        self,
        status: Optional[str] = None,
        job_type: Optional[JobType] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """List jobs with optional filtering"""
        params = {"limit": limit}
        if status:
            params["status"] = status
        if job_type:
            params["job_type"] = job_type.value
        
        response = self.session.get(f"{self.server_url}/jobs", params=params)
        response.raise_for_status()
        return response.json()
    
    def get_logs(self, job_id: str) -> str:
        """Get job logs"""
        response = self.session.get(f"{self.server_url}/jobs/{job_id}/logs")
        response.raise_for_status()
        return response.json()["logs"]
    
    def download_artifacts(self, job_id: str, output_dir: str = ".") -> Path:
        """
        Download job artifacts
        
        Args:
            job_id: Job ID
            output_dir: Directory to extract artifacts
        
        Returns:
            Path to extracted artifacts directory
        """
        response = self.session.get(
            f"{self.server_url}/jobs/{job_id}/artifacts/download",
            stream=True
        )
        response.raise_for_status()
        
        # Save zip file
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        zip_path = output_path / f"{job_id}_artifacts.zip"
        
        with open(zip_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        # Extract artifacts
        extract_dir = output_path / f"{job_id}_artifacts"
        extract_dir.mkdir(parents=True, exist_ok=True)
        
        with zipfile.ZipFile(zip_path, 'r') as zipf:
            zipf.extractall(extract_dir)
        
        # Remove zip file
        zip_path.unlink()
        
        return extract_dir
    
    def cancel_job(self, job_id: str) -> Dict[str, Any]:
        """Cancel a running job"""
        response = self.session.post(f"{self.server_url}/jobs/{job_id}/cancel")
        response.raise_for_status()
        return response.json()
    
    def delete_job(self, job_id: str) -> Dict[str, Any]:
        """Delete a job"""
        response = self.session.delete(f"{self.server_url}/jobs/{job_id}")
        response.raise_for_status()
        return response.json()
    
    def wait_for_job(
        self,
        job_id: str,
        timeout: Optional[int] = None,
        poll_interval: int = 5
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
                raise TimeoutError(f"Job {job_id} did not complete within {timeout} seconds")
            
            time.sleep(poll_interval)
    
    def submit_and_wait(
        self,
        name: str,
        code: str,
        download_artifacts: bool = True,
        output_dir: str = ".",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Submit job, wait for completion, and optionally download artifacts
        
        Args:
            name: Job name
            code: Python code
            download_artifacts: Whether to download artifacts
            output_dir: Directory for artifacts
            **kwargs: Additional arguments for submit_job
        
        Returns:
            Dictionary with job info and artifact path
        """
        # Submit job
        job_id = self.submit_job(name, code, **kwargs)
        print(f"Job submitted: {job_id}")
        
        # Wait for completion
        print("Waiting for job to complete...")
        job = self.wait_for_job(job_id, poll_interval=10)
        print(f"Job completed with status: {job['status']}")
        
        result = {
            "job_id": job_id,
            "status": job["status"],
            "mlflow_run_id": job.get("mlflow_run_id"),
            "artifact_path": None
        }
        
        # Download artifacts if requested and available
        if download_artifacts and job.get("artifacts_ready"):
            print("Downloading artifacts...")
            try:
                artifact_path = self.download_artifacts(job_id, output_dir)
                result["artifact_path"] = str(artifact_path)
                print(f"Artifacts downloaded to: {artifact_path}")
            except Exception as e:
                print(f"Warning: Failed to download artifacts: {e}")
        
        return result


# Convenience functions for common job types

def submit_training_job(
    server_url: str,
    name: str,
    code: str,
    gpu: bool = True,
    mlflow_experiment: Optional[str] = None,
    download_artifacts: bool = True,
    **kwargs
) -> Dict[str, Any]:
    """Submit a training job with sensible defaults"""
    client = RemoteComputeClient(server_url)
    return client.submit_and_wait(
        name=name,
        code=code,
        job_type=JobType.TRAINING,
        cpu=8,
        memory_gb=8,
        gpu=1 if gpu else 0,
        timeout_minutes=240,
        mlflow_experiment=mlflow_experiment,
        download_artifacts=download_artifacts,
        **kwargs
    )


def submit_inference_job(
    server_url: str,
    name: str,
    code: str,
    gpu: bool = True,
    download_artifacts: bool = True,
    **kwargs
) -> Dict[str, Any]:
    """Submit an inference job with sensible defaults"""
    client = RemoteComputeClient(server_url)
    return client.submit_and_wait(
        name=name,
        code=code,
        job_type=JobType.INFERENCE,
        cpu=4,
        memory_gb=4,
        gpu=1 if gpu else 0,
        timeout_minutes=60,
        download_artifacts=download_artifacts,
        **kwargs
    )


def submit_benchmarking_job(
    server_url: str,
    name: str,
    code: str,
    gpu: bool = True,
    download_artifacts: bool = True,
    **kwargs
) -> Dict[str, Any]:
    """Submit a benchmarking job"""
    client = RemoteComputeClient(server_url)
    return client.submit_and_wait(
        name=name,
        code=code,
        job_type=JobType.BENCHMARKING,
        cpu=4,
        memory_gb=4,
        gpu=1 if gpu else 0,
        timeout_minutes=120,
        download_artifacts=download_artifacts,
        **kwargs
    )


def submit_evaluation_job(
    server_url: str,
    name: str,
    code: str,
    gpu: bool = True,
    download_artifacts: bool = True,
    **kwargs
) -> Dict[str, Any]:
    """Submit an evaluation job"""
    client = RemoteComputeClient(server_url)
    return client.submit_and_wait(
        name=name,
        code=code,
        job_type=JobType.EVALUATION,
        cpu=4,
        memory_gb=4,
        gpu=1 if gpu else 0,
        timeout_minutes=120,
        download_artifacts=download_artifacts,
        **kwargs
    )
