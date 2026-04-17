"""Process management for Hermes dispatch: foreground and background launch."""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ._types import BackgroundJob, DispatchResult, DispatchTask, JobStatus
from ._prompt import build_prompt

logger = logging.getLogger(__name__)

PLATFORM_ROOT = Path(os.environ.get(
    "HERMES_CLIENT_PLATFORM_ROOT",
    Path(__file__).resolve().parents[2],
))
HERMES_BIN = Path(os.environ.get(
    "HERMES_BIN",
    Path.home() / ".hermes" / "hermes-agent" / "venv" / "bin" / "hermes",
))
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _hermes_command(task: DispatchTask, hermes_bin: Path) -> list[str]:
    """Build the Hermes CLI command for the task."""
    cmd = [str(hermes_bin), "chat", "--yolo", "-Q"]

    # Session control
    if task.session == "last":
        cmd.append("--continue")  # resume most recent — no name
    elif task.session:
        cmd.extend(["--resume", task.session])
    # else: None → fresh session per task (default, best for clean history)

    if task.worktree:
        cmd.append("--worktree")
    if task.skills:
        cmd.extend(["--skills", ",".join(task.skills)])
    if task.max_turns != 90:
        cmd.extend(["--max-turns", str(task.max_turns)])

    # Always last — Hermes reads -q as the terminal query
    cmd.extend(["-q", build_prompt(task)])
    return cmd


def _hermes_env() -> dict[str, str]:
    """Build env with HOME set correctly for the Hermes virtualenv."""
    env = os.environ.copy()
    parts = HERMES_BIN.parts
    if ".hermes" in parts:
        idx = parts.index(".hermes")
        if idx > 0:
            env["HOME"] = str(Path(*parts[:idx]))
    return env


def clean_output(text: str) -> str:
    """Strip ANSI escape codes and carriage returns."""
    return ANSI_ESCAPE.sub("", text).replace("\r", "")


def extract_json_payload(text: str) -> dict[str, Any]:
    """Extract the last valid JSON object from Hermes output (prefers end-of-output)."""
    decoder = json.JSONDecoder()
    cleaned = clean_output(text)
    for marker in ("```json", "```"):
        cleaned = cleaned.replace(marker, "")

    # Strip Rich Panel box-drawing characters (│ borders, corner chars, horizontal rules)
    box_chars = "│╭╮╰╯─╴╶"
    cleaned = "".join(ch if ch not in box_chars else " " for ch in cleaned)

    # Strip │-prefix lines: "   content text   " → join mid-wrapped lines
    # Collapse runs of whitespace within lines, then collapse line-wrapping
    lines = [ln.strip() for ln in cleaned.splitlines()]
    # Join consecutive non-empty lines that look like mid-string wraps
    merged: list[str] = []
    for ln in lines:
        if not ln:
            merged.append("")
        elif merged and merged[-1] and not merged[-1].endswith((",", "{", "[", ":", "}")):
            merged[-1] = merged[-1] + " " + ln
        else:
            merged.append(ln)
    cleaned = "\n".join(merged)

    positions = [i for i, ch in enumerate(cleaned) if ch == "{"]
    for index in reversed(positions):
        try:
            payload, _ = decoder.raw_decode(cleaned[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise ValueError("No valid JSON object found in Hermes output")


def run_foreground(
    task: DispatchTask,
    *,
    hermes_bin: Optional[Path] = None,
    timeout: Optional[int] = None,
    stream: bool = True,
) -> DispatchResult:
    """Run Hermes synchronously.

    When stream=True, output is printed to stdout in real-time (terminal monitoring).
    When stream=False, output is captured silently (used by background worker).

    timeout=None means no hard wall-clock cap — Hermes runs until its own --max-turns
    limit or natural completion. Use this for background jobs to avoid premature kills.
    A numeric timeout (seconds) acts as a hard kill if Hermes hasn't exited by then.
    """
    bin_path = hermes_bin or HERMES_BIN
    # Caller owns the timeout. None = no hard cap (rely on Hermes --max-turns).
    # Do NOT fall back to task.timeout — task.timeout is informational metadata,
    # not a kill timer. Background workers should always pass timeout=None.
    t_out: Optional[int] = timeout  # None → no wall-clock kill

    if not bin_path.exists():
        return DispatchResult(
            success=False, payload={}, transcript="",
            error=f"Hermes binary not found: {bin_path}",
        )

    cmd = _hermes_command(task, bin_path)
    env = _hermes_env()
    start = datetime.now(timezone.utc)

    try:
        if stream:
            # Popen with piped output → read line-by-line for real-time terminal output
            proc = subprocess.Popen(
                cmd,
                cwd=str(PLATFORM_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )
            lines: list[str] = []
            assert proc.stdout is not None

            if t_out is not None:
                # Read with a deadline: poll stdout until process exits or timeout
                import threading
                deadline = start.timestamp() + t_out
                timed_out = False

                def _read_lines() -> None:
                    for line in proc.stdout:  # type: ignore[union-attr]
                        print(line, end="", flush=True)
                        lines.append(line)

                reader = threading.Thread(target=_read_lines, daemon=True)
                reader.start()
                remaining = deadline - datetime.now(timezone.utc).timestamp()
                reader.join(timeout=max(remaining, 1))
                if reader.is_alive():
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    timed_out = True
            else:
                # No hard cap — read until Hermes exits naturally
                for line in proc.stdout:
                    print(line, end="", flush=True)
                    lines.append(line)
                timed_out = False

            proc.wait()  # reap zombie; already finished by this point
            raw_output = "".join(lines)
            returncode = proc.returncode

            if timed_out:
                elapsed = (datetime.now(timezone.utc) - start).total_seconds()
                return DispatchResult(
                    success=False, payload={}, transcript=raw_output,
                    duration_seconds=elapsed,
                    error=f"Hermes timed out after {t_out}s",
                )
        else:
            result = subprocess.run(
                cmd,
                cwd=str(PLATFORM_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=t_out,  # None = no cap for background non-stream mode
                env=env,
                check=False,
            )
            raw_output = result.stdout or ""
            returncode = result.returncode

    except subprocess.TimeoutExpired:
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        return DispatchResult(
            success=False, payload={}, transcript="",
            duration_seconds=elapsed,
            error=f"Hermes timed out after {t_out}s",
        )

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()

    if returncode != 0:
        return DispatchResult(
            success=False, payload={}, transcript=raw_output,
            duration_seconds=elapsed,
            error=f"Hermes exited with code {returncode}",
        )

    try:
        payload = extract_json_payload(raw_output)
    except ValueError as exc:
        return DispatchResult(
            success=False, payload={}, transcript=raw_output,
            duration_seconds=elapsed,
            error=str(exc),
        )

    return DispatchResult(
        success=True, payload=payload, transcript=raw_output,
        duration_seconds=elapsed,
    )


def launch_background(
    task: DispatchTask,
    job_id: str,
    log_file: Path,
    state_file: Path,
) -> BackgroundJob:
    """Launch Hermes as a detached background process.

    Spawns `python3 -m libs.hermes_client _bg-run STATE_FILE` as a new
    process group so that it survives the caller exiting.
    Returns immediately with a BackgroundJob handle.
    """
    import json as _json

    bg_worker = Path(__file__).parent / "_bg_worker.py"

    # Write task + metadata to state_file so the worker can load it
    state_data = {
        "job_id": job_id,
        "task": {
            "task_type": task.task_type,
            "title": task.title,
            "description": task.description,
            "project_id": task.project_id,
            "gitlab_issue_iid": task.gitlab_issue_iid,
            "labels": task.labels,
            "evidence_dir": str(task.evidence_dir) if task.evidence_dir else None,
            "containers": task.containers,
            "extra_context": task.extra_context,
            "session": task.session,
            "skills": task.skills,
            "worktree": task.worktree,
            "max_turns": task.max_turns,
            "timeout": task.timeout,
            "on_success": task.on_success,
            "on_failure": task.on_failure,
        },
        "status": "running",
        "log_file": str(log_file),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(_json.dumps(state_data, indent=2))
    log_file.parent.mkdir(parents=True, exist_ok=True)

    env = _hermes_env()
    env["PYTHONPATH"] = str(PLATFORM_ROOT) + ":" + env.get("PYTHONPATH", "")

    with open(log_file, "w") as log_fh:
        proc = subprocess.Popen(
            [sys.executable, str(bg_worker), str(state_file)],
            cwd=str(PLATFORM_ROOT),
            stdout=log_fh,
            stderr=log_fh,
            stdin=subprocess.DEVNULL,
            start_new_session=True,  # detach from calling process group
            env=env,
        )

    started_at = state_data["started_at"]
    return BackgroundJob(
        job_id=job_id,
        task_type=task.task_type,
        title=task.title,
        pid=proc.pid,
        started_at=started_at,
        log_file=log_file,
        state_file=state_file,
        project_id=task.project_id,
        gitlab_issue_iid=task.gitlab_issue_iid,
        status=JobStatus.RUNNING,
    )
