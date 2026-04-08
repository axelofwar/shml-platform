#!/usr/bin/env python3
"""Poll GitLab issues tagged assignee::agent and dispatch to Hermes.

Designed to run as:
- A systemd timer (every 10min)
- A one-shot CLI invocation
- Imported by the agent-service scheduler

Usage:
    python3 scripts/hermes/poll_agent_issues.py [--project-id 2] [--dry-run] [--once]
    python3 scripts/hermes/poll_agent_issues.py --project-id 3  # robotics
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLATFORM_ROOT / "scripts" / "platform"))
sys.path.insert(0, str(PLATFORM_ROOT / "scripts" / "hermes"))
sys.path.insert(0, str(PLATFORM_ROOT))

from dispatch import DispatchTask, dispatch
from gitlab_utils import add_issue_comment, list_issues, update_issue

logger = logging.getLogger(__name__)

STATE_DIR = PLATFORM_ROOT / "data" / "hermes-dispatch"
LOCK_LABEL = "status::in-progress"
DONE_LABEL = "status::done"
AGENT_LABEL = "assignee::agent"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Poll GitLab for agent-assigned issues")
    parser.add_argument("--project-id", type=int, default=int(os.environ.get("GITLAB_PROJECT_ID", "2")))
    parser.add_argument("--dry-run", action="store_true", help="List issues but don't dispatch")
    parser.add_argument("--once", action="store_true", help="Process one issue then exit")
    parser.add_argument("--max-issues", type=int, default=3, help="Max issues per poll cycle")
    parser.add_argument("--timeout", type=int, default=300, help="Hermes timeout per task")
    return parser.parse_args()


def is_already_processing(issue_iid: int) -> bool:
    """Check if we already dispatched this issue (avoid double-dispatch)."""
    lock_file = STATE_DIR / f"issue-{issue_iid}.lock"
    return lock_file.exists()


def mark_processing(issue_iid: int) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    lock_file = STATE_DIR / f"issue-{issue_iid}.lock"
    lock_file.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")


def clear_lock(issue_iid: int) -> None:
    lock_file = STATE_DIR / f"issue-{issue_iid}.lock"
    lock_file.unlink(missing_ok=True)


def save_result(issue_iid: int, result_data: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    result_file = STATE_DIR / f"issue-{issue_iid}-result.json"
    result_file.write_text(json.dumps(result_data, indent=2), encoding="utf-8")


def fetch_agent_issues(project_id: int, max_issues: int) -> list:
    """Get open issues tagged assignee::agent that aren't already in-progress."""
    os.environ["GITLAB_PROJECT_ID"] = str(project_id)
    issues = list_issues(state="opened", labels=AGENT_LABEL, per_page=max_issues * 2)

    eligible = []
    for issue in issues:
        if LOCK_LABEL in issue.labels:
            logger.debug("Skipping issue #%d — already in-progress", issue.iid)
            continue
        if DONE_LABEL in issue.labels:
            logger.debug("Skipping issue #%d — already done", issue.iid)
            continue
        if is_already_processing(issue.iid):
            logger.debug("Skipping issue #%d — lock file exists", issue.iid)
            continue
        eligible.append(issue)
        if len(eligible) >= max_issues:
            break

    return eligible


def dispatch_issue(issue, project_id: int, timeout: int) -> dict:
    """Dispatch a single issue to Hermes and return result metadata."""
    os.environ["GITLAB_PROJECT_ID"] = str(project_id)

    # Mark as in-progress
    mark_processing(issue.iid)
    current_labels = list(issue.labels)
    if LOCK_LABEL not in current_labels:
        current_labels.append(LOCK_LABEL)
    update_issue(issue.iid, labels=current_labels)
    add_issue_comment(issue.iid, "🤖 Hermes agent is working on this issue...")

    task = DispatchTask(
        task_type="issue",
        title=issue.title,
        description=getattr(issue, "description", "") or issue.title,
        project_id=project_id,
        gitlab_issue_iid=issue.iid,
        labels=issue.labels,
    )

    result = dispatch(
        task,
        timeout=timeout,
        update_issue=True,
        notify_telegram=True,
        sync_vault=True,
        close_on_complete=False,  # Agent marks ready-for-review, human closes
    )

    # Update labels based on result
    final_labels = [l for l in current_labels if l != LOCK_LABEL]
    payload = result.payload

    if result.success:
        status = payload.get("status", "completed")
        if status == "completed":
            final_labels.append("status::review")
        elif status == "blocked":
            final_labels.append("status::blocked")
        else:
            final_labels.append("status::in-progress")
    else:
        final_labels.append("status::blocked")
        add_issue_comment(issue.iid, f"❌ Hermes dispatch failed: {result.error}")

    update_issue(issue.iid, labels=final_labels)
    clear_lock(issue.iid)

    result_data = {
        "issue_iid": issue.iid,
        "title": issue.title,
        "success": result.success,
        "status": payload.get("status", "unknown"),
        "duration": result.duration_seconds,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "error": result.error,
    }
    save_result(issue.iid, result_data)
    return result_data


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    args = parse_args()
    logger.info("Polling project %d for assignee::agent issues", args.project_id)

    issues = fetch_agent_issues(args.project_id, args.max_issues)

    if not issues:
        logger.info("No eligible agent issues found")
        return 0

    logger.info("Found %d eligible issues", len(issues))

    for issue in issues:
        logger.info("Processing issue #%d: %s", issue.iid, issue.title)

        if args.dry_run:
            logger.info("  [DRY RUN] Would dispatch: %s", issue.title)
            continue

        result = dispatch_issue(issue, args.project_id, args.timeout)
        logger.info(
            "  Result: success=%s status=%s duration=%.1fs",
            result["success"], result["status"], result["duration"],
        )

        if args.once:
            break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
