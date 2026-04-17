#!/usr/bin/env python3
"""Background worker: runs Hermes for a dispatched task, handles signals, surfaces results.

Spawned by _process.launch_background() as a new session (detached from caller).
Usage: python3 _bg_worker.py STATE_FILE
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [bg_worker] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bootstrap: ensure platform libs are importable
# ---------------------------------------------------------------------------
_THIS_DIR = Path(__file__).resolve().parent
_PLATFORM_ROOT = _THIS_DIR.parents[1]  # libs/hermes_client/../../
sys.path.insert(0, str(_PLATFORM_ROOT))

from libs.hermes_client._types import DispatchTask, JobStatus  # noqa: E402
from libs.hermes_client._process import run_foreground  # noqa: E402
from libs.hermes_client._notify import surface_failure, surface_result  # noqa: E402
from libs.hermes_client._jobs import update_job_state  # noqa: E402


def _load_task(state: dict[str, Any]) -> DispatchTask:
    t = state["task"]
    return DispatchTask(
        task_type=t["task_type"],
        title=t["title"],
        description=t["description"],
        project_id=t.get("project_id", 2),
        gitlab_issue_iid=t.get("gitlab_issue_iid"),
        labels=t.get("labels", []),
        evidence_dir=Path(t["evidence_dir"]) if t.get("evidence_dir") else None,
        containers=t.get("containers", []),
        extra_context=t.get("extra_context", {}),
        session=t.get("session"),
        skills=t.get("skills", []),
        worktree=t.get("worktree", False),
        max_turns=t.get("max_turns", 90),
        timeout=t.get("timeout", 300),
        on_success=t.get("on_success", ["gitlab", "telegram", "vault"]),
        on_failure=t.get("on_failure", ["gitlab", "telegram"]),
    )


def main(state_file: Path) -> None:
    state = json.loads(state_file.read_text())
    job_id = state["job_id"]
    task = _load_task(state)

    logger.info("Starting job %s: %s", job_id, task.title)

    # Track the subprocess process object so signal handlers can terminate it
    _hermes_proc: dict[str, Any] = {"proc": None}

    def _handle_signal(signum: int, _frame: Any) -> None:
        logger.warning("Worker received signal %d — terminating Hermes", signum)
        proc = _hermes_proc.get("proc")
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        error = f"Worker interrupted by signal {signum}"
        update_job_state(job_id, JobStatus.INTERRUPTED)
        surface_failure(task, error)
        sys.exit(1)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # Patch run_foreground to capture the Popen object for signal handling.
    # We do this by monkey-patching subprocess.Popen temporarily.
    import subprocess as _sp

    _OrigPopen = _sp.Popen

    class _TrackingPopen(_OrigPopen):  # type: ignore[misc]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            _hermes_proc["proc"] = self

    _sp.Popen = _TrackingPopen  # type: ignore[misc]
    try:
        # stream=True: hermes stdout goes to sys.stdout which is the log file
        # (launch_background opens the log file and pipes bg_worker stdout to it)
        result = run_foreground(task, stream=True, timeout=None)  # no hard cap; Hermes --max-turns guards loops
    finally:
        _sp.Popen = _OrigPopen  # type: ignore[misc]

    if result.success:
        logger.info("Job %s succeeded in %.1fs", job_id, result.duration_seconds)
        update_job_state(job_id, JobStatus.COMPLETED, result)
        surface_result(task, result)
    else:
        logger.error("Job %s failed: %s", job_id, result.error)
        update_job_state(job_id, JobStatus.FAILED, result)
        surface_failure(task, result.error or "Hermes returned failure")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: _bg_worker.py STATE_FILE", file=sys.stderr)
        sys.exit(1)
    main(Path(sys.argv[1]))
