"""Hermes Client — public API for dispatching tasks to the Hermes agent.

Cross-project usage (robotics, sba, etc.):
    import sys, os
    sys.path.insert(0, "/home/axelofwar/Projects/shml-platform")
    from libs.hermes_client import dispatch_issue, dispatch_task

In-platform usage:
    from libs.hermes_client import dispatch_issue, dispatch_task
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional, Union

from ._types import BackgroundJob, DispatchResult, DispatchTask, JobStatus
from ._process import run_foreground, launch_background
from ._jobs import get_job, list_jobs, new_job_id, register_job, update_job_state, cleanup_old_jobs, JOBS_DIR

logger = logging.getLogger(__name__)

PLATFORM_ROOT = Path(os.environ.get(
    "HERMES_CLIENT_PLATFORM_ROOT",
    Path(__file__).resolve().parents[2],
))
DEFAULT_PROJECT_ID = int(os.environ.get("GITLAB_PROJECT_ID", "2"))


# ---------------------------------------------------------------------------
# Public dispatch API
# ---------------------------------------------------------------------------

def dispatch_issue(
    iid: int,
    project_id: int = DEFAULT_PROJECT_ID,
    *,
    background: bool = False,
    monitor: bool = True,
    timeout: int = 600,
    skills: Optional[list[str]] = None,
    worktree: bool = False,
    session: Optional[str] = None,
    on_failure: Optional[list[str]] = None,
    on_success: Optional[list[str]] = None,
) -> Union[DispatchResult, BackgroundJob]:
    """Fetch a GitLab issue and dispatch Hermes to resolve it.

    Args:
        iid: GitLab issue IID (the #N number shown in the UI).
        project_id: GitLab project ID (default: 2 = shml-platform).
        background: If True, launch detached and return BackgroundJob immediately.
        monitor: If True (and background=False), stream output to terminal.
        timeout: Seconds before giving up (foreground only).
        skills: Hermes --skills flag value.
        worktree: Pass --worktree to Hermes.
        session: None = fresh session; "last" = --continue; SESSION_ID = --resume.
        on_failure: Channels for surface_failure (default: ["gitlab", "telegram"]).
        on_success: Channels for surface_result (default: ["gitlab", "telegram", "vault"]).

    Returns:
        DispatchResult (foreground) or BackgroundJob (background).
    """
    issue = _fetch_gitlab_issue(iid, project_id)
    title = issue.get("title", f"Issue #{iid}")
    description = issue.get("description", "")
    raw_labels = issue.get("labels", [])
    # labels may be strings or dicts (depending on GitLab API version)
    if raw_labels and isinstance(raw_labels[0], dict):
        labels = [lbl["name"] for lbl in raw_labels]
    else:
        labels = list(raw_labels)

    task = DispatchTask(
        task_type="issue",
        title=title,
        description=description,
        project_id=project_id,
        gitlab_issue_iid=iid,
        labels=labels if isinstance(labels, list) else [],
        session=session,
        skills=skills or [],
        worktree=worktree,
        timeout=timeout,
        on_failure=on_failure or ["gitlab", "telegram"],
        on_success=on_success or ["gitlab", "telegram", "vault"],
    )
    return dispatch_task(task, background=background, monitor=monitor, timeout=timeout)


def dispatch_task(
    task: DispatchTask,
    *,
    background: bool = False,
    monitor: bool = True,
    timeout: Optional[int] = None,
) -> Union[DispatchResult, BackgroundJob]:
    """Dispatch a DispatchTask to Hermes.

    Args:
        task: Full task specification.
        background: If True, launch as a detached background process.
        monitor: If True (foreground), stream output to terminal in real-time.
        timeout: Override task.timeout.

    Returns:
        DispatchResult (foreground) or BackgroundJob (background).
    """
    eff_timeout = timeout or task.timeout

    if background:
        job_id = new_job_id()
        job_dir = JOBS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        log_file = job_dir / "hermes.log"
        state_file = job_dir / "state.json"

        job = launch_background(task, job_id, log_file, state_file)
        register_job(job)
        logger.info("Background job launched: %s (pid=%d)", job_id, job.pid)
        print(f"[hermes_client] Background job started: {job_id} (pid={job.pid})")
        print(f"  Log: {log_file}")
        print(f"  Monitor: python3 -m libs.hermes_client jobs tail {job_id}")
        return job

    # Foreground execution
    result = run_foreground(task, timeout=eff_timeout, stream=monitor)

    # Surface result/failure via configured channels
    from ._notify import surface_failure, surface_result
    if result.success:
        surface_result(task, result)
    else:
        surface_failure(task, result.error or "dispatch failed")

    return result


# ---------------------------------------------------------------------------
# Job management helpers
# ---------------------------------------------------------------------------

def get_job_status(job_id: str) -> Optional[JobStatus]:
    """Return the current status of a background job, or None if not found."""
    job = get_job(job_id)
    if job is None:
        return None
    # Refresh: if registered as RUNNING but process is dead, mark as failed
    if job.status == JobStatus.RUNNING and not job.is_alive():
        update_job_state(job_id, JobStatus.FAILED)
        return JobStatus.FAILED
    return job.status


def tail_job(job_id: str, *, n: int = 50, follow: bool = False) -> None:
    """Print the last n lines of a background job's log, optionally following."""
    job = get_job(job_id)
    if job is None:
        print(f"Job {job_id} not found.", file=sys.stderr)
        return
    if not job.log_file.exists():
        print(f"Log file not found: {job.log_file}", file=sys.stderr)
        return

    if not follow:
        lines = job.log_file.read_text(errors="replace").splitlines()
        for line in lines[-n:]:
            print(line)
        return

    import time
    with open(job.log_file, errors="replace") as fh:
        # Fast-forward to tail
        all_lines = fh.readlines()
        for line in all_lines[-n:]:
            print(line, end="")
        # Follow
        while True:
            line = fh.readline()
            if line:
                print(line, end="", flush=True)
            else:
                if not job.is_alive():
                    break
                time.sleep(0.2)


# ---------------------------------------------------------------------------
# GitLab issue fetching
# ---------------------------------------------------------------------------

def _fetch_gitlab_issue(iid: int, project_id: int) -> dict:
    """Fetch issue details from GitLab. Returns a dict with title/description/labels."""
    try:
        sys.path.insert(0, str(PLATFORM_ROOT / "scripts" / "platform"))
        import gitlab_utils as _gu  # type: ignore[import]
        old = os.environ.get("GITLAB_PROJECT_ID")
        os.environ["GITLAB_PROJECT_ID"] = str(project_id)
        try:
            # Use raw API to get full issue body including description.
            # get_issue() returns an Issue dataclass that has no description field.
            pid = _gu._project_id()
            raw = _gu._api("GET", f"/projects/{pid}/issues/{iid}")
            if not raw:
                return {"title": f"Issue #{iid}", "description": ""}
            raw_labels = raw.get("labels", [])
            if raw_labels and isinstance(raw_labels[0], dict):
                labels = [lbl["name"] for lbl in raw_labels]
            else:
                labels = list(raw_labels)
            return {
                "title": raw.get("title", f"Issue #{iid}"),
                "description": raw.get("description", "") or "",
                "labels": labels,
                "state": raw.get("state", "opened"),
                "web_url": raw.get("web_url", ""),
            }
        finally:
            if old is not None:
                os.environ["GITLAB_PROJECT_ID"] = old
            elif "GITLAB_PROJECT_ID" in os.environ:
                del os.environ["GITLAB_PROJECT_ID"]
    except Exception as exc:
        logger.warning("Could not fetch GitLab issue #%d: %s", iid, exc)
        return {"title": f"Issue #{iid}", "description": "(could not fetch from GitLab)"}


__all__ = [
    "dispatch_issue",
    "dispatch_task",
    "get_job_status",
    "tail_job",
    "get_job",
    "list_jobs",
    "cleanup_old_jobs",
    "DispatchTask",
    "DispatchResult",
    "BackgroundJob",
    "JobStatus",
]
