"""Type definitions for the Hermes dispatch client."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    TIMEOUT = "timeout"


@dataclass
class DispatchTask:
    """Specification of a task to dispatch to Hermes."""

    task_type: str
    """One of: "issue", "incident", "manual"."""

    title: str
    description: str

    # GitLab context
    project_id: int = 2
    gitlab_issue_iid: Optional[int] = None
    labels: list[str] = field(default_factory=list)

    # Incident-specific
    evidence_dir: Optional[Path] = None
    containers: list[str] = field(default_factory=list)

    # Extra facts injected into prompt
    extra_context: dict[str, Any] = field(default_factory=dict)

    # Hermes session control
    # None  → fresh session per task (default)
    # "last" → --continue (resume most recent session)
    # "SESSION_ID" → --resume SESSION_ID
    session: Optional[str] = None

    # Hermes invocation options
    skills: list[str] = field(default_factory=list)
    worktree: bool = False
    max_turns: int = 90
    timeout: int = 300

    # Post-dispatch hooks (comma-separated or list)
    # Supported hooks: "gitlab", "telegram", "vault"
    on_success: list[str] = field(default_factory=lambda: ["gitlab", "telegram", "vault"])
    on_failure: list[str] = field(default_factory=lambda: ["gitlab", "telegram"])


@dataclass
class DispatchResult:
    """Result from a Hermes dispatch execution."""

    success: bool
    payload: dict[str, Any]
    transcript: str
    duration_seconds: float = 0.0
    error: Optional[str] = None
    session_id: Optional[str] = None
    """Hermes session ID extracted from output — can be used for --resume."""

    def status_label(self) -> str:
        if not self.success:
            return "failed"
        return self.payload.get("status", "completed")


@dataclass
class BackgroundJob:
    """Handle to a Hermes task launched in background mode."""

    job_id: str
    task_type: str
    title: str
    pid: int
    started_at: str
    log_file: Path
    state_file: Path
    project_id: int
    gitlab_issue_iid: Optional[int]
    status: JobStatus = JobStatus.RUNNING
    result: Optional[DispatchResult] = None

    def is_alive(self) -> bool:
        """Check if the background worker process is still running."""
        import signal
        try:
            import os
            os.kill(self.pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "task_type": self.task_type,
            "title": self.title,
            "pid": self.pid,
            "started_at": self.started_at,
            "log_file": str(self.log_file),
            "state_file": str(self.state_file),
            "project_id": self.project_id,
            "gitlab_issue_iid": self.gitlab_issue_iid,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BackgroundJob":
        return cls(
            job_id=d["job_id"],
            task_type=d.get("task_type", "issue"),
            title=d.get("title", ""),
            pid=d.get("pid", 0),
            started_at=d.get("started_at", ""),
            log_file=Path(d["log_file"]),
            state_file=Path(d["state_file"]),
            project_id=d.get("project_id", 2),
            gitlab_issue_iid=d.get("gitlab_issue_iid"),
            status=JobStatus(d.get("status", "running")),
        )
