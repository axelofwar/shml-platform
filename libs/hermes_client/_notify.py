"""Error surfacing: Telegram + GitLab comments for Hermes dispatch outcomes."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

from ._types import BackgroundJob, DispatchResult, DispatchTask

logger = logging.getLogger(__name__)

PLATFORM_ROOT = Path(os.environ.get(
    "HERMES_CLIENT_PLATFORM_ROOT",
    Path(__file__).resolve().parents[2],
))


# ---------------------------------------------------------------------------
# GitLab helpers
# ---------------------------------------------------------------------------

def _gitlab_comment(task: DispatchTask, body: str) -> bool:
    """Post a comment to the GitLab issue. Returns True on success."""
    if not task.gitlab_issue_iid:
        return False
    try:
        sys.path.insert(0, str(PLATFORM_ROOT / "scripts" / "platform"))
        from gitlab_utils import add_issue_comment  # type: ignore[import]
        old = os.environ.get("GITLAB_PROJECT_ID")
        os.environ["GITLAB_PROJECT_ID"] = str(task.project_id)
        try:
            add_issue_comment(task.gitlab_issue_iid, body)
            return True
        finally:
            if old is not None:
                os.environ["GITLAB_PROJECT_ID"] = old
            elif "GITLAB_PROJECT_ID" in os.environ:
                del os.environ["GITLAB_PROJECT_ID"]
    except Exception as exc:
        logger.warning("GitLab comment failed: %s", exc)
        return False


def _gitlab_close_issue(task: DispatchTask) -> None:
    """Close the GitLab issue on successful completion."""
    if not task.gitlab_issue_iid:
        return
    try:
        sys.path.insert(0, str(PLATFORM_ROOT / "scripts" / "platform"))
        from gitlab_utils import update_issue  # type: ignore[import]
        old = os.environ.get("GITLAB_PROJECT_ID")
        os.environ["GITLAB_PROJECT_ID"] = str(task.project_id)
        try:
            update_issue(task.gitlab_issue_iid, state_event="close")
        finally:
            if old is not None:
                os.environ["GITLAB_PROJECT_ID"] = old
            elif "GITLAB_PROJECT_ID" in os.environ:
                del os.environ["GITLAB_PROJECT_ID"]
    except Exception as exc:
        logger.warning("GitLab issue close failed: %s", exc)


# ---------------------------------------------------------------------------
# Telegram helpers
# ---------------------------------------------------------------------------

def _telegram(message: str) -> bool:
    try:
        sys.path.insert(0, str(PLATFORM_ROOT))
        from libs.notify import send_telegram  # type: ignore[import]
        return send_telegram(message, parse_mode="HTML")
    except Exception as exc:
        logger.warning("Telegram notification failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Public surface functions
# ---------------------------------------------------------------------------

def surface_failure(
    task: DispatchTask,
    error: str,
    job: Optional[BackgroundJob] = None,
    *,
    channels: Optional[list[str]] = None,
) -> None:
    """Surface a Hermes dispatch failure via configured channels.

    Called when Hermes exits with error, times out, or is interrupted.
    """
    channels = channels if channels is not None else list(task.on_failure)

    issue_ref = f" (issue #{task.gitlab_issue_iid})" if task.gitlab_issue_iid else ""
    label = f"[interrupted]" if "interrupt" in error.lower() else "[failed]"

    if "telegram" in channels:
        bg_info = f"\nPID: {job.pid} | Job: {job.job_id}" if job else ""
        _telegram(
            f"🔴 <b>Hermes dispatch {label}</b>\n"
            f"<b>Task:</b> {task.title}{issue_ref}\n"
            f"<b>Error:</b> {error[:400]}"
            f"{bg_info}"
        )

    if "gitlab" in channels:
        _gitlab_comment(
            task,
            f"🔴 **Hermes dispatch {label}**\n\n"
            f"**Error:** {error}\n\n"
            f"Task: {task.title}  \n"
            f"Requires human follow-up.",
        )


def surface_result(
    task: DispatchTask,
    result: DispatchResult,
    *,
    channels: Optional[list[str]] = None,
    close_on_complete: bool = False,
) -> None:
    """Surface a successful (or partially successful) Hermes dispatch result."""
    channels = channels if channels is not None else list(task.on_success)

    issue_ref = f" (issue #{task.gitlab_issue_iid})" if task.gitlab_issue_iid else ""
    status = result.payload.get("status", "completed")
    emoji = "✅" if result.success and status == "completed" else "⚠️"

    if "telegram" in channels:
        summary = result.payload.get(
            "vault_summary",
            result.payload.get("diagnosis", "No summary available."),
        )
        _telegram(
            f"{emoji} <b>Hermes dispatch complete</b>\n"
            f"<b>Task:</b> {task.title}{issue_ref}\n"
            f"<b>Status:</b> {status}\n"
            f"<b>Summary:</b> {summary[:400]}"
        )

    if "gitlab" in channels:
        summary = result.payload.get("vault_summary", "")
        actions = result.payload.get("actions_taken", [])
        actions_text = "\n".join(f"- {a}" for a in actions[:8]) if actions else ""
        comment_body = (
            f"{emoji} **Hermes dispatch complete** — status: `{status}`\n\n"
            + (f"**Summary:** {summary}\n\n" if summary else "")
            + (f"**Actions taken:**\n{actions_text}\n\n" if actions_text else "")
            + f"*Duration: {result.duration_seconds:.0f}s*"
        )
        _gitlab_comment(task, comment_body)
        if close_on_complete and result.success and status == "completed":
            _gitlab_close_issue(task)

    if "vault" in channels:
        _sync_vault(task, result)


def _sync_vault(task: DispatchTask, result: DispatchResult) -> None:
    """Best-effort vault sync (no-op if vault sync not available)."""
    try:
        sys.path.insert(0, str(PLATFORM_ROOT / "scripts" / "hermes"))
        from dispatch import sync_to_obsidian  # type: ignore[import]
        sync_to_obsidian(task, result)
    except Exception:
        pass  # vault sync is non-critical
