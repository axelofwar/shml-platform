"""
Shortcut functions for quick job submission.

These provide the <150 character API the user requested:

    from shml import ray_submit
    ray_submit("print('hello')", key="shml_xxx")  # 45 chars!
"""

from typing import Optional, List

from .client import Client
from .models import JobSubmitResponse, Job


def ray_submit(
    code: str,
    key: Optional[str] = None,
    impersonate: Optional[str] = None,
    gpu: float = 0.0,
    name: Optional[str] = None,
    timeout: int = 2,
    **kwargs,
) -> JobSubmitResponse:
    """
    Quick job submission - <150 chars!

    Usage:
        ray_submit("print('hello')", key="shml_xxx")
        ray_submit("print('hello')")  # Uses SHML_API_KEY env var
        ray_submit("print('hello')", impersonate="developer")

    Args:
        code: Python code to execute
        key: API key (or uses SHML_API_KEY env var)
        impersonate: Service account to impersonate
        gpu: GPU fraction (0.0-1.0)
        name: Job name
        timeout: Timeout in hours
        **kwargs: Additional job options

    Returns:
        JobSubmitResponse with job_id
    """
    client = Client(api_key=key)

    try:
        if impersonate:
            client = client.impersonate(impersonate)

        return client.submit(
            code=code,
            gpu=gpu,
            name=name,
            timeout_hours=timeout,
            **kwargs,
        )
    finally:
        client.close()


def ray_status(job_id: str, key: Optional[str] = None) -> Job:
    """
    Quick job status check.

    Usage:
        status = ray_status("job-123", key="shml_xxx")
        print(status.status)

    Args:
        job_id: Job ID
        key: API key (or uses SHML_API_KEY env var)

    Returns:
        Job with current status
    """
    with Client(api_key=key) as client:
        return client.status(job_id)


def ray_logs(job_id: str, key: Optional[str] = None) -> str:
    """
    Quick job logs retrieval.

    Usage:
        logs = ray_logs("job-123", key="shml_xxx")
        print(logs)

    Args:
        job_id: Job ID
        key: API key (or uses SHML_API_KEY env var)

    Returns:
        Job logs as string
    """
    with Client(api_key=key) as client:
        return client.logs(job_id)


def ray_cancel(
    job_id: str, key: Optional[str] = None, reason: Optional[str] = None
) -> Job:
    """
    Quick job cancellation.

    Usage:
        ray_cancel("job-123", key="shml_xxx")

    Args:
        job_id: Job ID
        key: API key (or uses SHML_API_KEY env var)
        reason: Cancellation reason

    Returns:
        Updated Job
    """
    with Client(api_key=key) as client:
        return client.cancel(job_id, reason=reason)
