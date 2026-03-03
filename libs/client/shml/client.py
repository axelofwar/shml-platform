"""
SHML Client - Main client class for interacting with the SHML Platform API.
"""

import os
from typing import Optional, List, Dict, Any
from datetime import datetime

import httpx

from .config import get_config, Config
from .models import (
    Job,
    JobSubmitResponse,
    User,
    Quota,
    ApiKey,
    ApiKeyWithSecret,
    ImpersonationToken,
)


class SHMLError(Exception):
    """Base exception for SHML client errors."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        details: Optional[dict] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


class AuthenticationError(SHMLError):
    """Authentication failed."""

    pass


class PermissionError(SHMLError):
    """Permission denied."""

    pass


class NotFoundError(SHMLError):
    """Resource not found."""

    pass


class Client:
    """
    SHML Platform API Client.

    Usage:
        # With API key
        client = Client(api_key="shml_xxx")

        # With environment variable SHML_API_KEY
        client = Client()

        # With OAuth token
        client = Client(oauth_token="...")

        # With credentials file profile
        client = Client(profile="dev")
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        oauth_token: Optional[str] = None,
        profile: str = "default",
        timeout: float = 30.0,
        api_prefix: str = "/api/ray",
    ):
        """
        Initialize the SHML client.

        Args:
            base_url: Platform URL (default: env or https://shml-platform.tail38b60a.ts.net)
            api_key: API key for authentication (default: from env SHML_API_KEY)
            oauth_token: OAuth token (alternative to API key)
            profile: Credentials file profile to use
            timeout: Request timeout in seconds
            api_prefix: API path prefix (default: /api/ray for Traefik routing)
        """
        self.config = get_config(
            base_url=base_url,
            api_key=api_key,
            oauth_token=oauth_token,
            profile=profile,
        )
        self.timeout = timeout
        self.api_prefix = api_prefix
        self._client: Optional[httpx.Client] = None

    @property
    def client(self) -> httpx.Client:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.config.base_url,
                timeout=self.timeout,
            )
        return self._client

    def _get_headers(self) -> Dict[str, str]:
        """Get authentication headers."""
        headers = {"Content-Type": "application/json"}

        if self.config.api_key:
            headers["X-API-Key"] = self.config.api_key
        elif self.config.oauth_token:
            headers["Authorization"] = f"Bearer {self.config.oauth_token}"

        return headers

    def _handle_response(self, response: httpx.Response) -> dict:
        """Handle API response, raising appropriate exceptions for errors."""
        if response.status_code == 401:
            raise AuthenticationError(
                "Authentication failed. Check your API key or OAuth token.",
                status_code=401,
                details=response.json() if response.text else None,
            )
        elif response.status_code == 403:
            raise PermissionError(
                "Permission denied. You don't have access to this resource.",
                status_code=403,
                details=response.json() if response.text else None,
            )
        elif response.status_code == 404:
            raise NotFoundError(
                "Resource not found.",
                status_code=404,
                details=response.json() if response.text else None,
            )
        elif response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise SHMLError(
                f"API error: {detail}",
                status_code=response.status_code,
                details=response.json() if response.text else None,
            )

        if response.status_code == 204:  # No content
            return {}

        return response.json()

    # ========================================================================
    # Job Operations
    # ========================================================================

    def submit(
        self,
        code: Optional[str] = None,
        script_path: Optional[str] = None,
        script_url: Optional[str] = None,
        entrypoint: Optional[str] = None,
        entrypoint_args: Optional[List[str]] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        job_type: str = "training",
        cpu: int = 2,
        memory_gb: int = 8,
        gpu: float = 0.0,
        timeout_hours: int = 2,
        no_timeout: bool = False,
        priority: str = "normal",
        requirements: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        mlflow_experiment: Optional[str] = None,
        additional_files: Optional[Dict[str, str]] = None,
    ) -> JobSubmitResponse:
        """
        Submit a new job.

        Args:
            code: Inline Python code to execute
            script_path: Path to local Python script file
            script_url: URL to script file (alternative to code)
            entrypoint: Custom entrypoint command (e.g., 'python train.py --epochs 50')
            entrypoint_args: Arguments for the script (used with script_path)
            name: Job name (auto-generated if not provided)
            description: Job description
            job_type: Job type (training, inference, pipeline)
            cpu: CPU cores (1-96)
            memory_gb: RAM in GB (1-512)
            gpu: GPU fraction (0.0-1.0)
            timeout_hours: Max execution time
            no_timeout: Disable timeout (requires admin role)
            priority: Job priority (low, normal, high, critical)
            requirements: Python packages to install
            tags: Job tags for filtering
            mlflow_experiment: MLflow experiment name
            additional_files: Additional files to include {filename: filepath}

        Returns:
            JobSubmitResponse with job_id and status
        """
        import base64
        from pathlib import Path

        # Validate inputs
        submission_modes = sum(
            [
                bool(code),
                bool(script_path),
                bool(script_url),
                bool(entrypoint),
            ]
        )

        if submission_modes == 0:
            raise ValueError(
                "Must provide one of: 'code', 'script_path', 'script_url', or 'entrypoint'"
            )

        # Auto-generate name if not provided
        if not name:
            if script_path:
                name = f"{Path(script_path).stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            else:
                name = f"job-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        payload = {
            "name": name,
            "job_type": job_type,
            "cpu": cpu,
            "memory_gb": memory_gb,
            "gpu": gpu,
            "timeout_hours": timeout_hours,
            "no_timeout": no_timeout,
            "priority": priority,
        }

        if description:
            payload["description"] = description

        # Handle different submission modes
        if script_path:
            # Read and encode the script file
            script_file = Path(script_path)
            if not script_file.exists():
                raise FileNotFoundError(f"Script file not found: {script_path}")

            script_content = script_file.read_text()
            payload["script_content"] = base64.b64encode(
                script_content.encode()
            ).decode()
            payload["script_name"] = script_file.name

            if entrypoint_args:
                payload["entrypoint_args"] = entrypoint_args

        elif entrypoint:
            payload["entrypoint"] = entrypoint

        elif code:
            payload["code"] = code

        elif script_url:
            payload["script_url"] = script_url

        # Handle additional files
        if additional_files:
            working_dir_files = {}
            for filename, filepath in additional_files.items():
                file_path = Path(filepath)
                if file_path.exists():
                    content = file_path.read_text()
                    working_dir_files[filename] = base64.b64encode(
                        content.encode()
                    ).decode()
            if working_dir_files:
                payload["working_dir_files"] = working_dir_files

        if requirements:
            payload["requirements"] = requirements
        if tags:
            payload["tags"] = tags
        if mlflow_experiment:
            payload["mlflow_experiment"] = mlflow_experiment

        response = self.client.post(
            f"{self.api_prefix}/jobs",
            json=payload,
            headers=self._get_headers(),
        )

        data = self._handle_response(response)
        return JobSubmitResponse(
            job_id=data["job_id"],
            name=data["name"],
            status=data["status"],
        )

    def submit_script(
        self,
        script_path: str,
        args: Optional[List[str]] = None,
        name: Optional[str] = None,
        gpu: float = 0.0,
        cpu: int = 4,
        memory_gb: int = 16,
        timeout_hours: int = 4,
        mlflow_experiment: Optional[str] = None,
        requirements: Optional[List[str]] = None,
        **kwargs,
    ) -> JobSubmitResponse:
        """
        Convenience method to submit a Python script file.

        Args:
            script_path: Path to the Python script
            args: Command-line arguments for the script
            name: Job name (defaults to script filename)
            gpu: GPU fraction (0.0-1.0)
            cpu: CPU cores
            memory_gb: RAM in GB
            timeout_hours: Max execution time
            mlflow_experiment: MLflow experiment name
            requirements: Python packages to install
            **kwargs: Additional arguments passed to submit()

        Returns:
            JobSubmitResponse with job_id and status
        """
        return self.submit(
            script_path=script_path,
            entrypoint_args=args,
            name=name,
            gpu=gpu,
            cpu=cpu,
            memory_gb=memory_gb,
            timeout_hours=timeout_hours,
            mlflow_experiment=mlflow_experiment,
            requirements=requirements,
            job_type="training",
            **kwargs,
        )

    def status(self, job_id: str) -> Job:
        """
        Get job status.

        Args:
            job_id: Job ID

        Returns:
            Job with current status
        """
        response = self.client.get(
            f"{self.api_prefix}/jobs/{job_id}",
            headers=self._get_headers(),
        )

        data = self._handle_response(response)
        return Job(**data)

    def logs(self, job_id: str) -> str:
        """
        Get job logs.

        Args:
            job_id: Job ID

        Returns:
            Job logs as string
        """
        response = self.client.get(
            f"{self.api_prefix}/jobs/{job_id}/logs",
            headers=self._get_headers(),
        )

        data = self._handle_response(response)
        return data.get("logs", "")

    def cancel(self, job_id: str, reason: Optional[str] = None) -> Job:
        """
        Cancel a running job.

        Args:
            job_id: Job ID
            reason: Cancellation reason

        Returns:
            Updated Job
        """
        payload = {}
        if reason:
            payload["reason"] = reason

        response = self.client.post(
            f"{self.api_prefix}/jobs/{job_id}/cancel",
            json=payload,
            headers=self._get_headers(),
        )

        data = self._handle_response(response)
        return Job(**data)

    def list_jobs(
        self,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
    ) -> List[Job]:
        """
        List jobs.

        Args:
            page: Page number (1-indexed)
            page_size: Jobs per page
            status: Filter by status

        Returns:
            List of Jobs
        """
        params = {"page": page, "page_size": page_size}
        if status:
            params["status"] = status

        response = self.client.get(
            f"{self.api_prefix}/jobs",
            params=params,
            headers=self._get_headers(),
        )

        data = self._handle_response(response)
        return [Job(**j) for j in data.get("jobs", [])]

    # ========================================================================
    # User Operations
    # ========================================================================

    def me(self) -> User:
        """Get current user profile."""
        response = self.client.get(
            f"{self.api_prefix}/user/me",
            headers=self._get_headers(),
        )

        data = self._handle_response(response)
        return User(**data)

    def quota(self) -> Quota:
        """Get current user's quota."""
        response = self.client.get(
            f"{self.api_prefix}/user/quota",
            headers=self._get_headers(),
        )

        data = self._handle_response(response)
        return Quota(**data)

    # ========================================================================
    # API Key Operations
    # ========================================================================

    def list_api_keys(self) -> List[ApiKey]:
        """List user's API keys."""
        response = self.client.get(
            f"{self.api_prefix}/keys",
            headers=self._get_headers(),
        )

        data = self._handle_response(response)
        return [ApiKey(**k) for k in data]

    def create_api_key(
        self,
        name: str,
        description: Optional[str] = None,
        expires_in_days: Optional[int] = None,
        scopes: List[str] = ["jobs:submit", "jobs:read"],
    ) -> ApiKeyWithSecret:
        """
        Create a new API key.

        Args:
            name: Key name
            description: Key description
            expires_in_days: Days until expiration (None = never)
            scopes: Permissions for this key

        Returns:
            ApiKeyWithSecret with the actual key (shown only once!)
        """
        payload = {
            "name": name,
            "scopes": scopes,
        }
        if description:
            payload["description"] = description
        if expires_in_days:
            payload["expires_in_days"] = expires_in_days

        response = self.client.post(
            f"{self.api_prefix}/keys",
            json=payload,
            headers=self._get_headers(),
        )

        data = self._handle_response(response)
        return ApiKeyWithSecret(**data)

    def rotate_api_key(self, key_id: str) -> dict:
        """
        Rotate an API key (24h grace period).

        Args:
            key_id: Key ID to rotate

        Returns:
            Dict with new key and grace period info
        """
        response = self.client.post(
            f"{self.api_prefix}/keys/{key_id}/rotate",
            headers=self._get_headers(),
        )

        return self._handle_response(response)

    def revoke_api_key(self, key_id: str) -> None:
        """
        Revoke an API key immediately.

        Args:
            key_id: Key ID to revoke
        """
        response = self.client.delete(
            f"{self.api_prefix}/keys/{key_id}",
            headers=self._get_headers(),
        )

        self._handle_response(response)

    # ========================================================================
    # Impersonation
    # ========================================================================

    def impersonate(self, service_account: str) -> "Client":
        """
        Start service account impersonation.

        Requires membership in the 'impersonation-enabled' FusionAuth group.

        Args:
            service_account: Service account to impersonate
                             (admin, elevated_developer, developer, viewer)

        Returns:
            New Client instance with impersonation token
        """
        response = self.client.post(
            f"{self.api_prefix}/keys/impersonate",
            json={"service_account": service_account},
            headers=self._get_headers(),
        )

        data = self._handle_response(response)
        token_response = ImpersonationToken(**data)

        # Return a new client with the impersonation token
        return Client(
            base_url=self.config.base_url,
            oauth_token=token_response.token,
            timeout=self.timeout,
        )

    # ========================================================================
    # Cleanup
    # ========================================================================

    def close(self):
        """Close the HTTP client."""
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
