#!/usr/bin/env python3
"""Create a GitLab MR from Hermes agent work using the Agent MR template.

Called by the dispatch pipeline when Hermes reports mr_ready=true.
Updates the GitLab issue with the MR link and sends a Telegram notification.

Usage:
    python3 scripts/hermes/create_agent_mr.py \
        --project-id 3 \
        --issue-iid 50 \
        --source-branch feat/robotics-50-my-fix \
        --target-branch main \
        --title "fix: resolve GPU OOM in training job" \
        --summary "..." \
        --analysis "..." \
        --changes "file1: ...\nfile2: ..."
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLATFORM_ROOT / "scripts" / "platform"))
sys.path.insert(0, str(PLATFORM_ROOT))

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create an agent-authored GitLab MR")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--issue-iid", type=int, required=True)
    parser.add_argument("--source-branch", required=True)
    parser.add_argument("--target-branch", default="main")
    parser.add_argument("--title", required=True)
    parser.add_argument("--summary", default="")
    parser.add_argument("--analysis", default="")
    parser.add_argument("--changes", default="")
    parser.add_argument("--actions", default="")
    parser.add_argument("--vault-note", default="")
    parser.add_argument("--assign-to-self", action="store_true", default=True)
    return parser.parse_args()


def _api_request(path: str, method: str = "GET", data: Optional[dict] = None) -> Any:
    from gitlab_utils import _base_url, _token
    base = _base_url()
    tok = _token()
    url = f"{base}/api/v4{path}"
    payload = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=payload, method=method)
    req.add_header("PRIVATE-TOKEN", tok)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def build_description(args: argparse.Namespace) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    vault_ref = f"[[20-Decisions/{args.vault_note}]]" if args.vault_note else "N/A"

    changes_md = ""
    if args.changes:
        changes_md = "\n".join(f"- {line}" for line in args.changes.strip().split("\n") if line)
    else:
        changes_md = "- See diff below"

    actions_md = ""
    if args.actions:
        actions_md = "\n".join(f"- {line}" for line in args.actions.strip().split("\n") if line)

    return f"""## 🤖 Agent-Generated MR

**Agent:** Hermes | **Task type:** issue | **Created:** {now}

## Summary

{args.summary or 'Automated fix by Hermes agent.'}

## Related Issue

Closes #{args.issue_iid}

## Changes

{changes_md}

## Agent Analysis

{args.analysis or 'N/A'}

## Actions Taken

{actions_md or 'See agent issue comments for full transcript.'}

## Vault Reference

- Decision log: {vault_ref}
- Related: [[50-Projects/INDEX|Projects]]

## Testing

- [ ] CI pipeline passes
- [ ] GitNexus impact analysis reviewed
- [ ] Gitleaks scan passes
- [ ] Danger review passes

## Checklist

- [x] Code follows project style (agent-enforced)
- [x] No hardcoded secrets (gitleaks will verify)
- [ ] Human review of code logic
- [ ] Human review of test coverage

---
*This MR was created by the Hermes autonomous agent. Please review carefully before merging.*
"""


def create_mr(args: argparse.Namespace) -> dict:
    description = build_description(args)

    mr_data: dict[str, Any] = {
        "source_branch": args.source_branch,
        "target_branch": args.target_branch,
        "title": args.title,
        "description": description,
        "remove_source_branch": True,
        "squash": False,
        "labels": "type::feature,source::agent",
    }

    response = _api_request(
        f"/projects/{args.project_id}/merge_requests",
        method="POST",
        data=mr_data,
    )
    return response


def tag_issue_ready_for_review(
    project_id: int,
    issue_iid: int,
    mr_url: str,
    mr_iid: int,
) -> None:
    from gitlab_utils import add_issue_comment, update_issue

    old_project = os.environ.get("GITLAB_PROJECT_ID")
    os.environ["GITLAB_PROJECT_ID"] = str(project_id)
    try:
        update_issue(issue_iid, labels=["status::review", "assignee::agent"])
        add_issue_comment(
            issue_iid,
            f"🔍 **Ready for review** — MR created: {mr_url} (!{mr_iid})",
        )
    finally:
        if old_project:
            os.environ["GITLAB_PROJECT_ID"] = old_project


def notify_telegram(mr_url: str, title: str, issue_iid: int, summary: str = "") -> None:
    try:
        from libs.notify import send_mr_ready_notification
        send_mr_ready_notification(mr_url, title, issue_iid, summary=summary)
    except ImportError:
        logger.warning("libs.notify not available — skipping Telegram")


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    args = parse_args()

    logger.info("Creating MR for issue #%d on project %d", args.issue_iid, args.project_id)
    os.environ["GITLAB_PROJECT_ID"] = str(args.project_id)

    try:
        mr = create_mr(args)
    except Exception as e:
        logger.error("Failed to create MR: %s", e)
        return 1

    mr_url = mr.get("web_url", "")
    mr_iid = mr.get("iid", 0)
    logger.info("Created MR !%d: %s", mr_iid, mr_url)

    tag_issue_ready_for_review(args.project_id, args.issue_iid, mr_url, mr_iid)
    notify_telegram(mr_url, args.title, args.issue_iid, summary=args.summary)

    print(json.dumps({"mr_iid": mr_iid, "mr_url": mr_url, "issue_iid": args.issue_iid}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
