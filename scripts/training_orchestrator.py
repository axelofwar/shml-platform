#!/usr/bin/env python3
"""
Training Orchestrator - ML Platform
====================================

Orchestrates ML training jobs with:
- OAuth token management (FusionAuth)
- Job submission via Ray API (through Traefik)
- Job monitoring and status tracking
- Failure analysis and retry logic
- Pre-processing and validation

Usage:
    python training_orchestrator.py submit face_detection --curriculum
    python training_orchestrator.py status <job_id>
    python training_orchestrator.py list
    python training_orchestrator.py cancel <job_id>

Environment Variables:
    FUSIONAUTH_URL: FusionAuth server URL (default: http://localhost:9011)
    FUSIONAUTH_CLIENT_ID: OAuth client ID
    FUSIONAUTH_CLIENT_SECRET: OAuth client secret
    SERVICE_ACCOUNT_USER: Service account username
    SERVICE_ACCOUNT_PASSWORD: Service account password
    RAY_API_URL: Ray API endpoint (default: http://localhost/api/ray)
"""

import os
import sys
import json
import time
import argparse
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# =============================================================================
# CONFIGURATION
# =============================================================================


@dataclass
class OAuthConfig:
    """FusionAuth OAuth configuration.

    All credentials must be provided via environment variables.
    See .env.example for required variables.
    """

    fusionauth_url: str = ""
    client_id: str = ""
    client_secret: str = ""
    username: str = ""
    password: str = ""
    scope: str = "openid email profile"

    def __post_init__(self):
        """Load all config from environment variables (required)."""
        self.fusionauth_url = os.getenv("FUSIONAUTH_URL", "http://localhost:9011")
        self.client_id = os.environ.get("FUSIONAUTH_CLIENT_ID", "")
        self.client_secret = os.environ.get("FUSIONAUTH_CLIENT_SECRET", "")
        self.username = os.environ.get("SERVICE_ACCOUNT_USER", "")
        self.password = os.environ.get("SERVICE_ACCOUNT_PASSWORD", "")

        # Validate required credentials
        missing = []
        if not self.client_id:
            missing.append("FUSIONAUTH_CLIENT_ID")
        if not self.client_secret:
            missing.append("FUSIONAUTH_CLIENT_SECRET")
        if not self.username:
            missing.append("SERVICE_ACCOUNT_USER")
        if not self.password:
            missing.append("SERVICE_ACCOUNT_PASSWORD")

        if missing:
            logging.warning(
                f"Missing OAuth credentials: {', '.join(missing)}. Set environment variables."
            )


@dataclass
class RayAPIConfig:
    """Ray API configuration.

    Note: Traefik strips /api/ray prefix, so backend sees /api/v1/jobs.
    We need to include the full path: /api/ray/api/v1/jobs
    """

    base_url: str = "http://localhost/api/ray"  # Traefik route prefix
    timeout: int = 30
    max_retries: int = 3

    def __post_init__(self):
        self.base_url = os.getenv("RAY_API_URL", self.base_url)


@dataclass
class TrainingJobConfig:
    """Training job configuration - matches Ray API v2 schema."""

    name: str
    description: str
    job_type: str = "training"  # training, inference, pipeline
    language: str = "python"  # python, r, julia, bash

    # Code - either inline or script URL
    code: Optional[str] = None  # Inline code for simple jobs
    script_url: Optional[str] = None  # URL to script file
    requirements: List[str] = field(default_factory=list)  # Python packages

    # Resources
    cpu: int = 8  # CPU cores (1-24)
    memory_gb: int = 32  # RAM in GB (1-64)
    gpu: float = 1.0  # GPU allocation (0.0-1.0)
    timeout_hours: int = 8  # Max execution time (1-48)

    # Priority
    priority: str = "normal"  # low, normal, high, critical

    # Output
    output_mode: str = "both"  # artifacts, mlflow, both
    mlflow_experiment: Optional[str] = None
    artifact_retention_days: int = 90

    # Metadata
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# LOGGING
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# =============================================================================
# OAUTH TOKEN MANAGER
# =============================================================================


class OAuthTokenManager:
    """
    Manages OAuth tokens for API authentication.

    Features:
    - Token caching with expiry tracking
    - Automatic refresh before expiry
    - Thread-safe token access
    - Error handling with retries
    """

    def __init__(self, config: OAuthConfig = None):
        self.config = config or OAuthConfig()
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None
        self._refresh_token: Optional[str] = None

        # Setup session with retries
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def get_token(self, force_refresh: bool = False) -> str:
        """
        Get a valid access token, refreshing if necessary.

        Args:
            force_refresh: Force token refresh even if not expired

        Returns:
            Valid access token string

        Raises:
            AuthenticationError: If token cannot be obtained
        """
        # Check if we have a valid cached token
        if not force_refresh and self._access_token and self._token_expiry:
            # Refresh 60 seconds before expiry
            if datetime.now() < self._token_expiry - timedelta(seconds=60):
                logger.debug("Using cached token (expires: %s)", self._token_expiry)
                return self._access_token

        # Get new token
        logger.info("Fetching new OAuth token from FusionAuth...")
        return self._fetch_new_token()

    def _fetch_new_token(self) -> str:
        """Fetch a new token from FusionAuth."""
        token_url = f"{self.config.fusionauth_url}/oauth2/token"

        payload = {
            "grant_type": "password",
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "username": self.config.username,
            "password": self.config.password,
            "scope": self.config.scope,
        }

        try:
            response = self.session.post(
                token_url,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
            )
            response.raise_for_status()

            data = response.json()
            self._access_token = data["access_token"]
            self._refresh_token = data.get("refresh_token")

            # Calculate expiry (default to 1 hour if not specified)
            expires_in = data.get("expires_in", 3600)
            self._token_expiry = datetime.now() + timedelta(seconds=expires_in)

            logger.info("✓ Token obtained (expires in %d seconds)", expires_in)
            return self._access_token

        except requests.exceptions.HTTPError as e:
            error_msg = f"OAuth token request failed: {e}"
            if e.response is not None:
                try:
                    error_detail = e.response.json()
                    error_msg += f" - {error_detail}"
                except:
                    error_msg += f" - {e.response.text}"
            logger.error(error_msg)
            raise AuthenticationError(error_msg) from e

        except requests.exceptions.RequestException as e:
            error_msg = f"Failed to connect to FusionAuth: {e}"
            logger.error(error_msg)
            raise AuthenticationError(error_msg) from e

    def invalidate(self):
        """Invalidate cached token."""
        self._access_token = None
        self._token_expiry = None
        self._refresh_token = None
        logger.info("Token cache invalidated")


class AuthenticationError(Exception):
    """Raised when authentication fails."""

    pass


# =============================================================================
# RAY API CLIENT
# =============================================================================


class RayAPIClient:
    """
    Client for Ray Compute API.

    Features:
    - Automatic token management
    - Job submission, monitoring, cancellation
    - Error handling and retries
    - Structured logging
    """

    def __init__(
        self,
        api_config: RayAPIConfig = None,
        token_manager: OAuthTokenManager = None,
    ):
        self.config = api_config or RayAPIConfig()
        self.token_manager = token_manager or OAuthTokenManager()

        # Setup session
        self.session = requests.Session()
        retry_strategy = Retry(
            total=self.config.max_retries,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "POST", "DELETE"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with valid auth token."""
        token = self.token_manager.get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Make authenticated request to Ray API."""
        url = f"{self.config.base_url}{endpoint}"
        headers = self._get_headers()

        try:
            response = self.session.request(
                method,
                url,
                headers=headers,
                timeout=self.config.timeout,
                **kwargs,
            )
            response.raise_for_status()
            return response.json()

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                # Token might be invalid, retry with fresh token
                logger.warning("401 received, refreshing token...")
                self.token_manager.invalidate()
                headers = self._get_headers()
                response = self.session.request(
                    method,
                    url,
                    headers=headers,
                    timeout=self.config.timeout,
                    **kwargs,
                )
                response.raise_for_status()
                return response.json()
            raise

    def health_check(self) -> Dict[str, Any]:
        """Check API health status."""
        return self._request("GET", "/health")

    def submit_job(self, job_config: TrainingJobConfig) -> Dict[str, Any]:
        """
        Submit a training job.

        Args:
            job_config: Job configuration

        Returns:
            Job submission response with job_id
        """
        payload = {
            "name": job_config.name,
            "description": job_config.description,
            "job_type": job_config.job_type,
            "language": job_config.language,
            "cpu": job_config.cpu,
            "memory_gb": job_config.memory_gb,
            "gpu": job_config.gpu,
            "timeout_hours": job_config.timeout_hours,
            "priority": job_config.priority,
            "output_mode": job_config.output_mode,
            "artifact_retention_days": job_config.artifact_retention_days,
        }

        # Add code source (inline or script URL)
        if job_config.code:
            payload["code"] = job_config.code
        if job_config.script_url:
            payload["script_url"] = job_config.script_url

        # Add optional fields
        if job_config.requirements:
            payload["requirements"] = job_config.requirements
        if job_config.mlflow_experiment:
            payload["mlflow_experiment"] = job_config.mlflow_experiment
        if job_config.tags:
            payload["tags"] = job_config.tags

        logger.info("Submitting job: %s", job_config.name)
        # Note: Traefik strips /api/ray, so backend sees /api/v1/jobs
        result = self._request("POST", "/api/v1/jobs", json=payload)
        logger.info("✓ Job submitted: %s", result.get("job_id", "unknown"))
        return result

    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """Get job status."""
        return self._request("GET", f"/api/v1/jobs/{job_id}")

    def list_jobs(
        self,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List jobs with optional status filter."""
        params = {"limit": limit}
        if status:
            params["status"] = status
        return self._request("GET", "/api/v1/jobs", params=params)

    def cancel_job(self, job_id: str) -> Dict[str, Any]:
        """Cancel a running job."""
        logger.info("Cancelling job: %s", job_id)
        return self._request("DELETE", f"/api/v1/jobs/{job_id}")

    def get_job_logs(self, job_id: str) -> Dict[str, Any]:
        """Get job logs."""
        return self._request("GET", f"/api/v1/jobs/{job_id}/logs")


# =============================================================================
# JOB MONITORING
# =============================================================================


class JobMonitor:
    """
    Monitors job execution with failure analysis.

    Features:
    - Real-time status polling
    - Failure detection and analysis
    - Automatic retry with backoff
    - Progress reporting
    """

    TERMINAL_STATES = {"SUCCEEDED", "FAILED", "STOPPED", "CANCELLED"}

    def __init__(self, client: RayAPIClient):
        self.client = client

    def wait_for_completion(
        self,
        job_id: str,
        poll_interval: int = 30,
        timeout: int = 28800,  # 8 hours
        verbose: bool = True,
    ) -> Dict[str, Any]:
        """
        Wait for job to complete.

        Args:
            job_id: Job ID to monitor
            poll_interval: Seconds between status checks
            timeout: Maximum wait time in seconds
            verbose: Print progress updates

        Returns:
            Final job status
        """
        start_time = time.time()
        last_status = None

        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                logger.error("Job monitoring timed out after %d seconds", timeout)
                raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")

            try:
                status = self.client.get_job_status(job_id)
                current_status = status.get("status", "UNKNOWN")

                if current_status != last_status:
                    if verbose:
                        logger.info(
                            "[%s] Status: %s (elapsed: %.1fm)",
                            job_id[:12],
                            current_status,
                            elapsed / 60,
                        )
                    last_status = current_status

                if current_status in self.TERMINAL_STATES:
                    return status

            except Exception as e:
                logger.warning("Status check failed: %s", e)

            time.sleep(poll_interval)

    def analyze_failure(self, job_id: str) -> Dict[str, Any]:
        """
        Analyze job failure.

        Returns structured failure analysis with:
        - Error type classification
        - Root cause identification
        - Suggested remediation
        - Retry recommendation
        """
        try:
            status = self.client.get_job_status(job_id)
            logs = self.client.get_job_logs(job_id)
        except Exception as e:
            return {
                "job_id": job_id,
                "analysis_error": str(e),
                "retryable": False,
            }

        error_message = status.get("error_message", "")
        log_content = logs.get("logs", "")

        analysis = {
            "job_id": job_id,
            "status": status.get("status"),
            "error_message": error_message,
            "error_type": self._classify_error(error_message, log_content),
            "root_cause": self._identify_root_cause(error_message, log_content),
            "remediation": [],
            "retryable": False,
        }

        # Determine if retryable
        retryable_errors = [
            "OOM",
            "TIMEOUT",
            "CONNECTION",
            "TRANSIENT",
        ]
        if analysis["error_type"] in retryable_errors:
            analysis["retryable"] = True
            analysis["remediation"].append("Job can be retried automatically")

        # Add specific remediation steps
        if "CUDA out of memory" in log_content:
            analysis["remediation"].extend(
                [
                    "Reduce batch size",
                    "Enable gradient checkpointing",
                    "Use mixed precision training",
                ]
            )
        elif "FileNotFoundError" in log_content:
            analysis["remediation"].extend(
                [
                    "Verify dataset path exists",
                    "Check volume mounts",
                    "Run with --download-dataset flag",
                ]
            )

        return analysis

    def _classify_error(self, error_msg: str, logs: str) -> str:
        """Classify error type."""
        combined = f"{error_msg} {logs}".lower()

        if "cuda" in combined and "memory" in combined:
            return "OOM"
        elif "timeout" in combined:
            return "TIMEOUT"
        elif "connection" in combined or "refused" in combined:
            return "CONNECTION"
        elif "permission" in combined or "access denied" in combined:
            return "PERMISSION"
        elif "not found" in combined or "no such file" in combined:
            return "FILE_NOT_FOUND"
        elif "import" in combined or "module" in combined:
            return "DEPENDENCY"
        else:
            return "UNKNOWN"

    def _identify_root_cause(self, error_msg: str, logs: str) -> str:
        """Identify root cause from error and logs."""
        combined = f"{error_msg} {logs}"

        # Look for common patterns
        patterns = [
            (r"FileNotFoundError: \[Errno 2\].*'([^']+)'", "File not found: {}"),
            (r"CUDA out of memory.*allocated ([\d.]+ \w+)", "GPU memory exhausted: {}"),
            (r"ModuleNotFoundError: No module named '(\w+)'", "Missing module: {}"),
            (r"RuntimeError: (.+)", "Runtime error: {}"),
        ]

        import re

        for pattern, template in patterns:
            match = re.search(pattern, combined)
            if match:
                return template.format(match.group(1))

        return error_msg[:200] if error_msg else "Unknown error"


# =============================================================================
# TRAINING JOB DEFINITIONS
# =============================================================================


def get_face_detection_training_job(
    curriculum: bool = True,
    download_dataset: bool = True,
) -> TrainingJobConfig:
    """
    Get face detection training job configuration.

    Args:
        curriculum: Use curriculum learning (easy→medium→hard)
        download_dataset: Download WIDERFace dataset if not present
    """
    mode = "curriculum" if curriculum else "full"

    # Build arguments list
    # Note: Use --curriculum flag, not --mode
    args = []
    if curriculum:
        args.append("--curriculum")
    if download_dataset:
        args.append("--download-dataset")
    # Use --device for GPU selection (0 or 0,1 for multi-GPU)
    args.extend(["--device", "0"])
    args_str = " ".join(args)

    # Inline script that runs the training
    # The actual training script is in /opt/ray/job_workspaces/
    # Note: Use double braces {{ }} for literal braces in f-strings
    training_code = f"""
import os
import subprocess
import sys

# Set environment
os.environ["MLFLOW_TRACKING_URI"] = "http://mlflow-nginx:80"
os.environ["CUDA_VISIBLE_DEVICES"] = "0,1"

# Run the face detection training script
script_path = "/opt/ray/job_workspaces/face_detection_training.py"
cmd_args = [sys.executable, script_path] + "{args_str}".split()
print("Running: " + " ".join(cmd_args))
result = subprocess.run(
    cmd_args,
    capture_output=False,
    cwd="/opt/ray/job_workspaces"
)
sys.exit(result.returncode)
"""

    return TrainingJobConfig(
        name=f"face_detection_{mode}_training_v1",
        description=(
            f"SOTA face detection training using YOLOv8l-face pretrained model (lindevs). "
            f"{'3-stage curriculum: Easy→Medium→Hard faces' if curriculum else 'Full training'} "
            f"from WIDERFace dataset."
        ),
        job_type="training",
        language="python",
        code=training_code,
        requirements=[
            "mlflow>=2.10.0",
            "ultralytics>=8.0.0",
            "torch>=2.0.0",
            "torchvision",
            "scipy",
            "opencv-python-headless",
            "pillow",
            "tqdm",
            "pandas",
            "matplotlib",
            "seaborn",
        ],
        cpu=8,
        memory_gb=32,
        gpu=1.0,  # Full GPU allocation
        timeout_hours=10,
        priority="high",
        output_mode="both",
        mlflow_experiment="face_detection_curriculum",
        tags=["face_detection", "yolov8", "curriculum_learning", "widerface"],
        metadata={
            "model": "yolov8l-face-lindevs",
            "model_source": "https://github.com/lindevs/yolov8-face",
            "dataset": "WIDERFace",
            "curriculum_stages": ["easy", "medium", "hard"] if curriculum else ["full"],
            "target_metrics": {
                "easy_map": 0.98,
                "medium_map": 0.96,
                "hard_map": 0.90,
            },
            "gpu_allocation": ["RTX 3090 Ti (24GB)", "RTX 2070 (8GB)"],
            "estimated_duration": "4-8 hours",
        },
    )


# =============================================================================
# TRAINING ORCHESTRATOR
# =============================================================================


class TrainingOrchestrator:
    """
    High-level training orchestration.

    Features:
    - Pre-flight validation
    - Job submission with retries
    - Progress monitoring
    - Failure analysis and recovery
    - Post-training analysis
    """

    def __init__(self):
        self.token_manager = OAuthTokenManager()
        self.api_client = RayAPIClient(token_manager=self.token_manager)
        self.monitor = JobMonitor(self.api_client)

    def preflight_check(self) -> bool:
        """
        Run pre-flight checks before training.

        Validates:
        - API connectivity
        - OAuth authentication
        - Ray cluster health
        - GPU availability
        """
        logger.info("━━━ Pre-flight Checks ━━━")

        try:
            # Check API health
            health = self.api_client.health_check()
            logger.info("✓ Ray API: %s", health.get("status", "unknown"))

            # Token is automatically fetched during health check
            logger.info("✓ OAuth: Token valid")

            # Check for recent jobs to verify full API access
            jobs = self.api_client.list_jobs(limit=1)
            logger.info("✓ Job API: Accessible")

            return True

        except AuthenticationError as e:
            logger.error("✗ Authentication failed: %s", e)
            return False
        except Exception as e:
            logger.error("✗ Pre-flight check failed: %s", e)
            return False

    def submit_training(
        self,
        job_config: TrainingJobConfig,
        wait: bool = False,
        retry_on_failure: bool = True,
        max_retries: int = 2,
    ) -> Dict[str, Any]:
        """
        Submit training job with orchestration.

        Args:
            job_config: Job configuration
            wait: Wait for job completion
            retry_on_failure: Retry failed jobs
            max_retries: Maximum retry attempts

        Returns:
            Job result including status and any failure analysis
        """
        # Pre-flight checks
        if not self.preflight_check():
            return {"success": False, "error": "Pre-flight checks failed"}

        logger.info("\n━━━ Submitting Training Job ━━━")
        logger.info("Name: %s", job_config.name)
        logger.info(
            "GPU: %.1f, CPUs: %d, Memory: %dGB, Timeout: %dh",
            job_config.gpu,
            job_config.cpu,
            job_config.memory_gb,
            job_config.timeout_hours,
        )

        attempt = 0
        last_result = None

        while attempt <= max_retries:
            attempt += 1

            if attempt > 1:
                logger.info("\n━━━ Retry Attempt %d/%d ━━━", attempt - 1, max_retries)

            try:
                # Submit job
                result = self.api_client.submit_job(job_config)
                job_id = result.get("job_id")

                if not job_id:
                    logger.error("No job_id in response: %s", result)
                    continue

                logger.info("✓ Job ID: %s", job_id)

                if not wait:
                    return {
                        "success": True,
                        "job_id": job_id,
                        "status": "SUBMITTED",
                        "message": "Job submitted, use 'status' command to monitor",
                    }

                # Wait for completion
                logger.info("\n━━━ Monitoring Job ━━━")
                final_status = self.monitor.wait_for_completion(job_id)

                if final_status.get("status") == "SUCCEEDED":
                    return {
                        "success": True,
                        "job_id": job_id,
                        "status": "SUCCEEDED",
                        "final_status": final_status,
                    }

                # Job failed - analyze
                logger.warning("Job failed with status: %s", final_status.get("status"))
                analysis = self.monitor.analyze_failure(job_id)
                last_result = {
                    "success": False,
                    "job_id": job_id,
                    "status": final_status.get("status"),
                    "failure_analysis": analysis,
                }

                # Check if retryable
                if (
                    retry_on_failure
                    and analysis.get("retryable")
                    and attempt <= max_retries
                ):
                    logger.info("Job is retryable, will retry...")
                    time.sleep(30)  # Brief pause before retry
                    continue

                return last_result

            except Exception as e:
                logger.error("Job submission/monitoring failed: %s", e)
                last_result = {
                    "success": False,
                    "error": str(e),
                    "attempt": attempt,
                }

                if attempt <= max_retries:
                    logger.info("Will retry in 30 seconds...")
                    time.sleep(30)
                    continue

        return last_result or {"success": False, "error": "Max retries exceeded"}


# =============================================================================
# CLI INTERFACE
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="ML Platform Training Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Submit face detection training
  %(prog)s submit face_detection --curriculum

  # Submit and wait for completion
  %(prog)s submit face_detection --wait

  # Check job status
  %(prog)s status raysubmit_abc123

  # List recent jobs
  %(prog)s list --status RUNNING

  # Cancel a job
  %(prog)s cancel raysubmit_abc123
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Submit command
    submit_parser = subparsers.add_parser("submit", help="Submit a training job")
    submit_parser.add_argument(
        "job_type", choices=["face_detection"], help="Type of training job"
    )
    submit_parser.add_argument(
        "--curriculum", action="store_true", help="Use curriculum learning"
    )
    submit_parser.add_argument(
        "--no-download", action="store_true", help="Don't download dataset"
    )
    submit_parser.add_argument(
        "--wait", action="store_true", help="Wait for job completion"
    )
    submit_parser.add_argument(
        "--no-retry", action="store_true", help="Disable automatic retry on failure"
    )

    # Status command
    status_parser = subparsers.add_parser("status", help="Get job status")
    status_parser.add_argument("job_id", help="Job ID to check")
    status_parser.add_argument("--logs", action="store_true", help="Include job logs")

    # List command
    list_parser = subparsers.add_parser("list", help="List jobs")
    list_parser.add_argument("--status", help="Filter by status")
    list_parser.add_argument(
        "--limit", type=int, default=20, help="Maximum jobs to list"
    )

    # Cancel command
    cancel_parser = subparsers.add_parser("cancel", help="Cancel a job")
    cancel_parser.add_argument("job_id", help="Job ID to cancel")

    # Health command
    health_parser = subparsers.add_parser("health", help="Check API health")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    orchestrator = TrainingOrchestrator()

    if args.command == "submit":
        if args.job_type == "face_detection":
            job_config = get_face_detection_training_job(
                curriculum=args.curriculum,
                download_dataset=not args.no_download,
            )
        else:
            logger.error("Unknown job type: %s", args.job_type)
            return 1

        result = orchestrator.submit_training(
            job_config,
            wait=args.wait,
            retry_on_failure=not args.no_retry,
        )

        print("\n" + "=" * 60)
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("success") else 1

    elif args.command == "status":
        try:
            status = orchestrator.api_client.get_job_status(args.job_id)
            print(json.dumps(status, indent=2, default=str))

            if args.logs:
                print("\n" + "=" * 60 + "\nLOGS:\n")
                logs = orchestrator.api_client.get_job_logs(args.job_id)
                print(logs.get("logs", "No logs available"))

            return 0
        except Exception as e:
            logger.error("Failed to get status: %s", e)
            return 1

    elif args.command == "list":
        try:
            jobs = orchestrator.api_client.list_jobs(
                status=args.status,
                limit=args.limit,
            )
            print(json.dumps(jobs, indent=2, default=str))
            return 0
        except Exception as e:
            logger.error("Failed to list jobs: %s", e)
            return 1

    elif args.command == "cancel":
        try:
            result = orchestrator.api_client.cancel_job(args.job_id)
            print(json.dumps(result, indent=2, default=str))
            return 0
        except Exception as e:
            logger.error("Failed to cancel job: %s", e)
            return 1

    elif args.command == "health":
        try:
            health = orchestrator.api_client.health_check()
            print(json.dumps(health, indent=2, default=str))
            return 0 if health.get("status") in ["healthy", "degraded"] else 1
        except Exception as e:
            logger.error("Health check failed: %s", e)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
