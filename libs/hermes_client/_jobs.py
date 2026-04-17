"""Background job registry: read/write state files in data/hermes-jobs/."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ._types import BackgroundJob, DispatchResult, JobStatus

logger = logging.getLogger(__name__)

PLATFORM_ROOT = Path(os.environ.get(
    "HERMES_CLIENT_PLATFORM_ROOT",
    Path(__file__).resolve().parents[2],
))
# Use ~/.hermes/jobs/ if platform data/ is root-owned; fall back to tmp
_default_jobs_dir = Path.home() / ".hermes" / "jobs"
JOBS_DIR = Path(os.environ.get("HERMES_JOBS_DIR", str(_default_jobs_dir)))


def new_job_id() -> str:
    """Generate a unique timestamp-based job ID."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    import secrets
    return f"{ts}_{secrets.token_hex(3)}"


def register_job(job: BackgroundJob) -> None:
    """Persist a BackgroundJob to the registry."""
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    registry_file = JOBS_DIR / f"{job.job_id}.json"
    registry_file.write_text(json.dumps(job.to_dict(), indent=2))


def update_job_state(
    job_id: str,
    status: JobStatus,
    result: Optional[DispatchResult] = None,
) -> None:
    """Update the status (and optionally result) of a registered job."""
    registry_file = JOBS_DIR / f"{job_id}.json"
    if not registry_file.exists():
        logger.warning("Job %s not found in registry", job_id)
        return

    data = json.loads(registry_file.read_text())
    data["status"] = status.value
    data["finished_at"] = datetime.now(timezone.utc).isoformat()

    if result is not None:
        data["result"] = {
            "success": result.success,
            "payload": result.payload,
            "duration_seconds": result.duration_seconds,
            "error": result.error,
            "session_id": result.session_id,
        }

    registry_file.write_text(json.dumps(data, indent=2))


def _load_job(registry_file: Path) -> Optional[BackgroundJob]:
    try:
        data = json.loads(registry_file.read_text())
        result = None
        if "result" in data:
            r = data["result"]
            result = DispatchResult(
                success=r.get("success", False),
                payload=r.get("payload", {}),
                transcript="",
                duration_seconds=r.get("duration_seconds", 0.0),
                error=r.get("error"),
                session_id=r.get("session_id"),
            )
        return BackgroundJob(
            job_id=data["job_id"],
            task_type=data.get("task_type", "unknown"),
            title=data.get("title", ""),
            pid=data.get("pid", 0),
            started_at=data.get("started_at", ""),
            log_file=Path(data.get("log_file", "")),
            state_file=registry_file,
            project_id=data.get("project_id", 2),
            gitlab_issue_iid=data.get("gitlab_issue_iid"),
            status=JobStatus(data.get("status", "running")),
            result=result,
        )
    except Exception as exc:
        logger.warning("Failed to load job from %s: %s", registry_file, exc)
        return None


def get_job(job_id: str) -> Optional[BackgroundJob]:
    """Load a job from the registry by ID."""
    registry_file = JOBS_DIR / f"{job_id}.json"
    if not registry_file.exists():
        return None
    return _load_job(registry_file)


def list_jobs(status: Optional[str] = None) -> list[BackgroundJob]:
    """List all registered jobs, optionally filtered by status string."""
    if not JOBS_DIR.exists():
        return []
    jobs = []
    for f in sorted(JOBS_DIR.glob("*.json"), reverse=True):
        job = _load_job(f)
        if job and (status is None or job.status.value == status):
            jobs.append(job)
    return jobs


def cleanup_old_jobs(max_age_days: int = 7) -> int:
    """Remove job state files older than max_age_days. Returns count removed."""
    if not JOBS_DIR.exists():
        return 0
    cutoff = datetime.now(timezone.utc).timestamp() - max_age_days * 86400
    removed = 0
    for f in JOBS_DIR.glob("*.json"):
        if f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)
            removed += 1
    return removed
